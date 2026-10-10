#!/bin/bash
# Does a long job lose what it filed when it is dropped (tools/durable.sh)?
#
# A fake job runs the way the full pass does: from its own worktree
# (tools/nightly_worktree.sh), a filer that records each item in a ledger
# outside the tree once its puzzle is written, under durable_run. It is then
#   1. left running: its checkpoint pushes what it filed while it still runs;
#   2. sent SIGTERM (corpus_queue.py stop): it ends the filer and pushes;
#   3. sent SIGKILL (OOM, reboot): the next start salvages the tree, modified
#      tracked files and a commit a failed push left, but not a cut-off file;
# and each restart files only what its ledger lacks, so no item is filed twice
# and every item the ledger holds is on origin. Then a job that sources
# durable.sh alone is checked to checkpoint, tools/corpus_queue.py stop to give
# the pass its TERM and time to commit before killing, and every scheduled job
# that can run long to use the mechanism.
set -euo pipefail
cd "$(dirname "$0")/.."
REAL="$PWD"
tmp=$(mktemp -d); [ -n "${KEEP:-}" ] && echo "tmp: $tmp"
trap '[ -n "${pid:-}" ] && pkill -KILL -s "$pid" 2>/dev/null; [ -n "${KEEP:-}" ] || rm -rf "$tmp"' EXIT
export HOME="$tmp/home" CT_WORKTREE_ROOT="$tmp/trees" GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
mkdir -p "$HOME"
git config --global init.defaultBranch master
git config --global advice.detachedHead false
git init -q --bare "$tmp/origin.git"
git clone -q "$tmp/origin.git" "$tmp/main" 2>/dev/null
M="$tmp/main"
mkdir -p "$M/tools" "$M/puzzles/a"
cp tools/durable.sh tools/nightly_worktree.sh tools/unstage_unparsable.sh tools/push_puzzle_commit.sh tools/commit_subject.py "$M/tools/"
cat >"$M/tools/alert.sh" <<'EOF'
alert() { echo "$*" >>"$HOME/alerts"; }
EOF
# The pre-push's judge, stubbed: it refuses a puzzle that says so.
cat >"$M/tools/puzzle_integrity.py" <<'EOF'
import json, sys
assert sys.argv[1] == "--refused"
for p in sys.argv[2:]:
    if json.load(open(p)).get("refuse"):
        print(f"{p}\tDATE {p}: refused")
EOF
echo '{"last": 0}' >"$M/puzzles/a/0.json"
cat >"$M/tools/fakejob.sh" <<'EOF'
#!/bin/bash
CT_GENERATED=none
CT_SALVAGE_PATHS="puzzles"
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
DURABLE_PATHS=(puzzles)
. tools/durable.sh
durable_run "fake pass" timeout 600 bash tools/fakefiler.sh
EOF
# Files items 1..3, each once: its puzzle, a change to the tracked 0.json,
# then the ledger row, as the scan filers do.
cat >"$M/tools/fakefiler.sh" <<'EOF'
for i in 1 2 3; do
  grep -qx "$i" "$HOME/ledger" 2>/dev/null && continue
  echo "{\"n\": $i}" >"puzzles/a/$i.json"
  echo "{\"last\": $i}" >puzzles/a/0.json
  [ "$i" = 3 ] && echo '{"cut off' >puzzles/a/bad.json
  echo "$i" >>"$HOME/ledger"
  echo "$i" >>"$HOME/filings"
  sleep "${FAKE_SLEEP:-30}"
done
EOF
git -C "$M" add -A && git -C "$M" commit -qm init && git -C "$M" push -q origin master 2>/dev/null

on_origin() { git --git-dir="$tmp/origin.git" show "master:$1" 2>/dev/null; }
wait_for() {  # wait_for <seconds> <command...>
  local n=$(($1 * 10))
  shift
  while ! "$@" >/dev/null 2>&1; do
    n=$((n - 1))
    [ "$n" -gt 0 ] || return 1
    sleep 0.1
  done
}
filed() { grep -qx "$1" "$HOME/ledger"; }
group_gone() { ! pgrep -s "$pid" >/dev/null; }
start() { setsid bash "$M/tools/fakejob.sh" >>"$tmp/job.log" 2>&1 & pid=$!; }
fail() { echo "FAIL: $*"; echo "--- job log:"; cat "$tmp/job.log"; exit 1; }

# 1. Running: the checkpoint pushes item 1 while the job still runs.
DURABLE_EVERY=1 start
wait_for 60 filed 1 || fail "the fake job never filed item 1"
wait_for 30 on_origin puzzles/a/1.json || fail "item 1 was not pushed while the job ran"
# A checkpoint can land between the filer's writes, so 0.json's update may
# ride in a later commit; the commit carrying 1.json must still name it.
git --git-dir="$tmp/origin.git" log --format=%s master | grep -E '^File 1(; update 0)? \(fake pass\)$' >/dev/null || fail "a checkpoint commit does not name the puzzles it files: $(git --git-dir="$tmp/origin.git" log --format=%s master | head -5 | tr "\n" "|")"
kill -0 "$pid" || fail "the job ended early"
pkill -KILL -s "$pid"
wait_for 10 group_gone || fail "job 1 outlived SIGKILL"

# 2. SIGTERM: the job ends its filer and pushes item 2 before it exits.
DURABLE_EVERY=1000 start
wait_for 60 filed 2 || fail "the restarted job never filed item 2"
kill -TERM "$pid"
rc=0
wait "$pid" || rc=$?
[ "$rc" = 143 ] || fail "a stopped job exits 143, not $rc"
wait_for 10 group_gone || fail "the filer outlived the job's stop"
on_origin puzzles/a/2.json >/dev/null || fail "item 2 was not pushed on SIGTERM"
grep -q "stop asked" "$tmp/job.log" || fail "the stop was not logged"

# 3. SIGKILL: item 3 and the 0.json change are left in the tree, and a
#    committed-but-unpushed commit beside them; the next start pushes them.
DURABLE_EVERY=1000 start
wait_for 60 filed 3 || fail "the restarted job never filed item 3"
pkill -KILL -s "$pid"
wait_for 10 group_gone || fail "job 3 outlived SIGKILL"
on_origin puzzles/a/3.json >/dev/null && fail "item 3 reached origin before any salvage: the test proves nothing"
T="$CT_WORKTREE_ROOT/fakejob"
echo extra >"$T/puzzles/a/unpushed.json.txt"
git -C "$T" add puzzles/a/unpushed.json.txt && git -C "$T" commit -qm "a commit whose push failed"
DURABLE_EVERY=1000 start
wait "$pid" || fail "the salvaging start failed"
on_origin puzzles/a/3.json >/dev/null || fail "item 3 was lost to the SIGKILL: the next start did not salvage it"
[ "$(on_origin puzzles/a/0.json)" = '{"last": 3}' ] || fail "the change to tracked 0.json was lost to the reset"
on_origin puzzles/a/unpushed.json.txt >/dev/null || fail "an unpushed local commit was lost to the reset"
on_origin puzzles/a/bad.json >/dev/null && fail "a cut-off .json was salvaged"

# Each item filed once, and every one the ledger holds is on origin.
[ "$(sort "$HOME/filings" | tr '\n' ' ')" = "1 2 3 " ] || fail "items refiled on restart: $(tr '\n' ' ' <"$HOME/filings")"
while read -r i; do
  on_origin "puzzles/a/$i.json" >/dev/null || fail "ledger holds $i but origin does not"
done <"$HOME/ledger"
[ ! -s "$HOME/alerts" ] || fail "alerted: $(cat "$HOME/alerts")"
pid=""

# 4. A job that sources tools/durable.sh alone, outside any worktree, checkpoints
#    too: durable.sh brings every function it calls.
git clone -q "$tmp/origin.git" "$tmp/solo" 2>/dev/null
cat >"$tmp/solo.sh" <<'EOF'
cd "$1" || exit 1
DURABLE_PATHS=(puzzles)
. tools/durable.sh
mkdir -p puzzles/b && echo '{"n": 1}' >puzzles/b/1.json
echo '{"refuse": true}' >puzzles/b/2.json
durable_checkpoint "solo pass"
EOF
out=$(bash "$tmp/solo.sh" "$tmp/solo" 2>&1) || fail "a job sourcing only durable.sh could not checkpoint: $out"
case "$out" in *"command not found"*) fail "durable.sh calls a function it does not bring: $out" ;; esac
on_origin puzzles/b/1.json >/dev/null || fail "a job sourcing only durable.sh did not push what it filed: $out"
# A puzzle the pre-push would refuse is held in the tree and named, so it
# strands neither its checkpoint nor the ones after it.
on_origin puzzles/b/2.json >/dev/null && fail "a checkpoint committed a puzzle the pre-push refuses"
[ -e "$tmp/solo/puzzles/b/2.json" ] || fail "the refused puzzle was dropped from the tree"
case "$out" in *"held out of the commit"*"puzzles/b/2.json"*) ;; *) fail "the held puzzle was not named: $out" ;; esac

# 5. corpus_queue.py stop gives the pass's leader TERM and waits for it.
python3 - "$REAL" <<'PY'
import os, sys, time
from pathlib import Path
sys.path.insert(0, os.path.join(sys.argv[1], "tools"))
import corpus_queue as q
home = Path(os.environ["HOME"])
fake = home / "pass.sh"
fake.write_text('trap \'sleep 2; echo committed > "$HOME/committed"; exit 143\' TERM\n'
                'echo up > "$HOME/up"\nwhile :; do sleep 1 & wait $!; done\n')
q.FULL_PASS, q.CHAIN = fake, ["true"]
q.wake = lambda text, dry: None
q.launch(False)
for _ in range(100):
    if (home / "up").exists():
        break
    time.sleep(0.1)
sid = q.running()["pid"]
q.STOP_GRACE = 20
q.main(["stop"])
assert (home / "committed").exists(), "stop killed the pass before it could commit"
assert q.session_pids(sid) == [], q.session_pids(sid)
assert q.exit_status() == 143, q.exit_status()
assert q.load_state().get("held"), "a stopped pass is held"
PY

# 6. Every scheduled job that can run past LONG seconds (no timeout, or a
#    longer one) either commits as it goes through tools/durable.sh or has its
#    dropped runs salvaged; so does the pass the corpus queue starts.
python3 - <<'PY'
import re, sys, tomllib
from pathlib import Path
sys.path.insert(0, "tools")
import corpus_queue
LONG = 900
long_jobs = {corpus_queue.FULL_PASS.name: "started by tools/corpus_queue.py",
             "gale_read.sh": "started by tools/gale_inbox.py sync (start_reads)",
             "daily_update.sh": "its units, started by tools/unit_queue.py",
             "acquire_books.sh": "its units, started by tools/unit_queue.py"}
for manifest in sorted(Path("household-plugins").glob("*/plugin.toml")):
    m = tomllib.loads(manifest.read_text())
    if m.get("timeout", 0) and m["timeout"] <= LONG:
        continue
    long_jobs[Path(m["run"]).name] = f"{manifest.parent.name}, timeout {m.get('timeout', 'none')}"
bad = []
for script, why in long_jobs.items():
    text = (Path("tools") / script).read_text()
    if not re.search(r"^CT_SALVAGE_PATHS=", text, re.M):
        bad.append(f"tools/{script} ({why}) sets no CT_SALVAGE_PATHS: a drop loses what it filed")
    for m in re.finditer(r"^(CT_SALVAGE_PATHS|DURABLE_PATHS)=(.*)$", text, re.M):
        if re.search(r"\bpuzzles/\w", m.group(2)):
            bad.append(f"tools/{script}'s {m.group(1)} names a folder inside puzzles/: a write "
                       "there can delete a book file in another (fetch_puzzle.supersede_book), "
                       "and that deletion would never be committed")
    if "durable.sh" in text and "durable_run" not in text and "durable_checkpoint" not in text:
        bad.append(f"tools/{script} sources tools/durable.sh but never checkpoints")
assert not bad, "\n".join(bad)
assert "durable_run" in corpus_queue.FULL_PASS.read_text(), "the full pass files without checkpoints"
print(f"long jobs: {', '.join(sorted(long_jobs))}")
PY
echo "durable: ok"
