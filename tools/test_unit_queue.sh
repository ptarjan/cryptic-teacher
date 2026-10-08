#!/bin/bash
# Does tools/unit_queue.py run a queue as small units? A fake queue's tick
# starts each due unit detached and returns at once; a unit that runs past its
# limit is killed and recorded as 124 and alerted; a failure waits out its
# retry; a unit that ended well is not due again until its cadence; `cls`
# caps how many of a kind run at once; a running unit is never started twice;
# `after` holds a unit back while what it names is due or running; `trigger`
# makes one due when what it names ended well since; one that reports backlog
# left (backlog_left) runs again at the next tick, despite its cadence. Then a queue with tree
# slots: each unit runs in its own worktree (tools/nightly_worktree.sh, CT_JOB),
# two units in two trees at once, and a third waits for a tree.
#
#     bash tools/test_unit_queue.sh
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'pkill -KILL -f "$tmp/" 2>/dev/null || true; rm -rf "$tmp"' EXIT
export UNIT_QUEUE_STATE="$tmp/state" UNIT_QUEUE_PATH="$tmp/q" CT_MAIN_CHECKOUT="$tmp/main"
export UNIT_QUEUE_ALERT="$tmp/q/alert.sh"
mkdir -p "$tmp/q" "$tmp/main"
cat >"$tmp/q/alert.sh" <<'SH'
#!/bin/sh
echo "$1" >>"$(dirname "$0")/alerts"
SH
chmod +x "$tmp/q/alert.sh"
cat >"$tmp/q/fake_units.py" <<'PY'
import os
from unit_queue import Unit
LOG = "fake.log"
LIMITS = {"one": 1}
D = os.path.dirname(__file__)
def sh(key, cmd, **kw):
    return Unit(key=key, argv=["sh", "-c", cmd], **kw)
def plan(ledger, now):
    return [
        sh("ok", f"echo ran >>{D}/ok.runs", timeout=30, every=3600),
        sh("fail", "echo boom; exit 2", timeout=30, every=60),
        sh("slow", "sleep 30", timeout=2, every=3600),
        sh("a", f"echo a >>{D}/one.runs; sleep 8", timeout=30, cls="one"),
        sh("b", f"echo b >>{D}/one.runs; sleep 1", timeout=30, cls="one"),
        sh("late", f"echo late >>{D}/late.runs", timeout=30, after=("ok",), trigger=("ok",)),
        sh("drain", f"[ -e {D}/drain.runs ] || : >\"$UNIT_MORE\"; echo run >>{D}/drain.runs",
           timeout=30, every=3600),
    ]
PY
# This host's own load must not gate the ticks under test.
export CT_LOAD_PER_CORE=1e9
q() { python3 tools/unit_queue.py "$@"; }
UNIT_MORE="$tmp/more" python3 -c 'import sys; sys.path.insert(0, "tools"); import unit_queue; unit_queue.backlog_left()'
[ -e "$tmp/more" ] || { echo "FAIL: backlog_left() did not mark \$UNIT_MORE"; exit 1; }
fail() { echo "FAIL: $*"; echo "--- log:"; cat "$tmp/main/fake.log" 2>/dev/null; exit 1; }
ended() { python3 - "$1" <<'PY'
import sys
sys.path.insert(0, "tools")
import unit_queue as u
u.LOAD_READER = lambda: 0.0  # this host's load must not gate the tests' starts
e = u.Ledger("fake").last_end.get(sys.argv[1])
print("" if e is None else e["rc"])
PY
}
wait_end() {  # wait_end <key> <rc>
  for _ in $(seq 200); do [ "$(ended "$1")" = "$2" ] && return 0; sleep 0.2; done
  fail "$1 did not end with rc $2 (got '$(ended "$1")')"
}

t0=$(date +%s)
out=$(q tick fake)
[ $(($(date +%s) - t0)) -le 5 ] || fail "the tick waited for its units"
grep -q "start ok" <<<"$out" || fail "ok was not started: $out"
grep -q "start a" <<<"$out" || fail "a was not started: $out"
grep -q "start b" <<<"$out" && fail "b started beside a although cls one allows one: $out"
grep -q "start late" <<<"$out" && fail "late started while ok, which it is after, was due: $out"
wait_end ok 0
wait_end fail 2
wait_end drain 0
wait_end slow 124
grep -q "slow" "$tmp/q/alerts" || fail "the overrun was not alerted"
grep -q "^\[fail\] boom" "$tmp/main/fake.log" || fail "a unit's output is not in the log under its key"

out=$(q tick fake)
grep -qE "start (ok|fail|slow)" <<<"$out" && fail "a unit ran again before its cadence or retry: $out"
grep -q "start a" <<<"$out" && fail "a was started twice: $out"
grep -q "start b" <<<"$out" && fail "b started while a holds cls one: $out"
grep -q "start late" <<<"$out" || fail "late was not started once ok ended well: $out"
grep -q "start drain (backlog left)" <<<"$out" || fail "drain left backlog but was not started again: $out"
wait_end a 0
wait_end late 0
out=$(q tick fake)
grep -q "start b" <<<"$out" || fail "b was not started once a ended: $out"
grep -q "start late" <<<"$out" && fail "late ran again with no new ok: $out"
wait_end b 0
for _ in $(seq 200); do [ "$(wc -l <"$tmp/q/drain.runs")" = 2 ] && break; sleep 0.2; done
wait_end drain 0
out=$(q tick fake)
grep -q "start drain" <<<"$out" && fail "drain ran again with its backlog done: $out"
[ "$(wc -l <"$tmp/q/drain.runs")" = 2 ] || fail "drain ran $(wc -l <"$tmp/q/drain.runs") times, not twice"
[ "$(wc -l <"$tmp/q/ok.runs")" = 1 ] || fail "ok ran $(wc -l <"$tmp/q/ok.runs") times"
st=$(q status fake)
grep -q "fail .*1 failures in a row" <<<"$st" || fail "status does not show the failure: $st"
# Tree slots, in a scratch repo: the units run tools/nightly_worktree.sh as
# the real ones do.
export HOME="$tmp/home" CT_WORKTREE_ROOT="$tmp/trees" GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
mkdir -p "$HOME"
git config --global init.defaultBranch master
git init -q --bare "$tmp/origin.git"
git clone -q "$tmp/origin.git" "$tmp/repo" 2>/dev/null
mkdir -p "$tmp/repo/tools"
cp tools/nightly_worktree.sh tools/unstage_unparsable.sh tools/unit_queue.py "$tmp/repo/tools/"
echo 'alert() { echo "$*" >>"$HOME/alerts"; }' >"$tmp/repo/tools/alert.sh"
cat >"$tmp/repo/tools/slotjob.sh" <<'SH'
#!/bin/bash
CT_GENERATED=none
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
echo "in $(basename "$PWD") main $(basename "$CT_MAIN_CHECKOUT") job $(printenv CT_JOB || echo unset)"
sleep 2
SH
git -C "$tmp/repo" add -A && git -C "$tmp/repo" commit -qm init && git -C "$tmp/repo" push -q origin master 2>/dev/null
cat >"$tmp/q/slots_units.py" <<'PY'
import os
from unit_queue import Unit
LOG = "slots.log"
LIMITS = {}
SLOTS = 2
TREE = "slot"
def plan(ledger, now):
    job = os.path.join(os.environ["CT_MAIN_CHECKOUT"], "tools", "slotjob.sh")
    return [Unit(key=k, argv=["bash", job], timeout=60) for k in ("u1", "u2", "u3")]
PY
export CT_MAIN_CHECKOUT="$tmp/repo"
out=$(q tick slots)
grep -q "start u1" <<<"$out" && grep -q "start u2" <<<"$out" || fail "two slots did not start two units: $out"
grep -q "start u3" <<<"$out" && fail "a third unit started with both trees taken: $out"
log="$tmp/repo/slots.log"
for _ in $(seq 150); do [ "$(grep -c 'end: rc=0' "$log" 2>/dev/null)" = 2 ] && break; sleep 0.2; done
[ "$(grep -c 'end: rc=0' "$log")" = 2 ] || { cat "$log"; fail "the slot units did not both end well"; }
trees=$(grep -o "in slot-[12] main repo job unset" "$log" | sort -u | wc -l || true)
[ "$trees" = 2 ] || { cat "$log"; fail "the two units did not run in trees slot-1 and slot-2, each with the main checkout's state and CT_JOB kept from their children"; }
out=$(q tick slots)
grep -q "start u3" <<<"$out" || fail "u3 did not start once a tree was free: $out"
echo "unit_queue: ok"
