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
export PUSH_BATCH_SECS=0  # every push at once, not batched 5 min apart (tools/push_puzzle_commit.sh)
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
cp tools/durable.sh tools/nightly_worktree.sh tools/unstage_unparsable.sh tools/commit_puzzles.sh tools/push_puzzle_commit.sh tools/clobber_guard.py tools/commit_subject.py tools/renamed_ids.py "$M/tools/"
cat >"$M/tools/alert.sh" <<'EOF'
alert() { echo "$*" >>"$HOME/alerts"; }
EOF
# The checkpoint's hold-back judge, stubbed: it refuses a puzzle that says so.
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
git --git-dir="$tmp/origin.git" log --format=%s master | grep -E '^File 1$' >/dev/null || fail "a checkpoint does not commit each puzzle alone, named: $(git --git-dir="$tmp/origin.git" log --format=%s master | head -5 | tr "\n" "|")"
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

# 4a. One puzzle per commit (Paul 10-12: "one commit instead of one per
#     puzzle"), clues-only files included, for a checkpoint and for
#     acquire_books.sh's publish; the ledger and the series file ride in the
#     closing commit, and each commit's subject names its file.
git clone -q "$tmp/origin.git" "$tmp/multi" 2>/dev/null
cat >"$tmp/multi.sh" <<'EOF'
cd "$1" || exit 1
DURABLE_PATHS=(puzzles clues_only tools/data/book_reads.json)
. tools/durable.sh
mkdir -p puzzles/m clues_only tools/data
for i in 1 2; do echo "{\"n\": $i}" >puzzles/m/times-$i.json; echo "{\"c\": $i}" >clues_only/book-$i.json; done
echo '{"read": 1}' >tools/data/book_reads.json
durable_checkpoint "multi pass"
# publish() exactly as acquire_books.sh has it.
eval "$(sed -n '/^publish() {/,/^}/p' "$2/tools/acquire_books.sh")"
echo '{"n": 3}' >puzzles/m/times-3.json; echo '{"c": 3}' >clues_only/book-3.json
echo '{"read": 2}' >tools/data/book_reads.json
publish "Read a book"
EOF
out=$(bash "$tmp/multi.sh" "$tmp/multi" "$REAL" 2>&1) || fail "multi-puzzle checkpoint failed: $out"
git -C "$tmp/multi" fetch -q origin master
# The 8 newest: 3 puzzles, 3 clues-only files, 2 ledger commits - never two files in one.
for c in $(git -C "$tmp/multi" log --format=%H origin/master -n 8); do
  n=$(git -C "$tmp/multi" show --format= --name-only "$c" | grep -c '^\(puzzles\|clues_only\)/' || true)
  [ "$n" -le 1 ] || fail "a commit holds $n puzzle files: $(git -C "$tmp/multi" log -1 --format=%s "$c")"
done
subjects=$(git -C "$tmp/multi" log --format=%s origin/master -n 8 | sort | tr '\n' '|')
for want in "File times-1" "File times-2" "File times-3" "File book-1" "File book-2" "File book-3" "multi pass" "Read a book"; do
  case "$subjects" in *"$want|"*) ;; *) fail "no commit with subject '$want': $subjects" ;; esac
done
case "$(git -C "$tmp/multi" log -1 --format=%s origin/master)" in "Read a book") ;; *) fail "the ledger is not the closing commit" ;; esac

# 4a'. Rereads of filed puzzles go out together (Paul 10-21: "reasonable
#      batches ... Look at the annotation ones"): "Update 2 puzzles", ids in the body.
cat >"$tmp/upd.sh" <<'EOF'
cd "$1" || exit 1
DURABLE_PATHS=(puzzles clues_only tools/data/book_reads.json)
. tools/durable.sh
echo '{"n": 11}' >puzzles/m/times-1.json; echo '{"n": 12}' >puzzles/m/times-2.json
echo '{"n": 4}' >puzzles/m/times-4.json
durable_checkpoint "upd pass"
EOF
out=$(bash "$tmp/upd.sh" "$tmp/multi" 2>&1) || fail "update checkpoint failed: $out"
git -C "$tmp/multi" fetch -q origin master
subjects=$(git -C "$tmp/multi" log --format=%s origin/master -n 2 | sort | tr '\n' '|')
[ "$subjects" = "File times-4|Update 2 puzzles|" ] || fail "rereads not batched: $subjects"
c=$(git -C "$tmp/multi" log --format=%H --grep='^Update 2 puzzles' origin/master -n 1)
case "$(git -C "$tmp/multi" log -1 --format=%b "$c")" in *"times-1 times-2"*) ;; *) fail "batch body lacks the ids" ;; esac

# 4b. A commit that conflicts with origin/master (another job filed the same
#     puzzle meanwhile) is set aside, never blocking the commits after it:
#     they are pushed, origin's version stands, its puzzle asks a re-read
#     (scan_queue.py conflicted, stubbed), and the resync moves the tree to
#     origin/master past it, keeping what the job has not committed yet. A
#     commit nothing re-reads is kept under refs/durable/conflicts/ and alerted.
conflict_case() {  # conflict_case <dir> <stub status>: sha of the conflicting commit
  local d="$tmp/$1" o="$tmp/$1-other" i
  git clone -q "$tmp/origin.git" "$d" 2>/dev/null && git clone -q "$tmp/origin.git" "$o" 2>/dev/null
  printf 'import os, sys\nopen(os.environ["HOME"] + "/conflicted", "a").write(sys.argv[2] + "\\n")\nprint("re-read asked")\nsys.exit(%s)\n' "$2" >"$d/tools/scan_queue.py"
  mkdir -p "$d/puzzles/$1" "$o/puzzles/$1"
  echo '{"n": "mine"}' >"$d/puzzles/$1/1.json" && git -C "$d" add puzzles && git -C "$d" commit -qm "File c1 (mine)"
  echo '{"n": "theirs"}' >"$o/puzzles/$1/1.json" && git -C "$o" add puzzles && git -C "$o" commit -qm "File c1 (theirs)"
  git -C "$o" push -q origin HEAD:master 2>/dev/null
  for i in 2 3; do
    echo "{\"n\": $i}" >"$d/puzzles/$1/$i.json" && git -C "$d" add puzzles && git -C "$d" commit -qm "File c$i"
  done
  git -C "$d" rev-parse HEAD~2
}
cat >"$tmp/cf.sh" <<'EOF'
cd "$1" || exit 1
DURABLE_PATHS=(puzzles)
. tools/durable.sh
durable_checkpoint "conflict pass" || { echo "checkpoint failed"; exit 1; }
echo '{"n": 4}' >"puzzles/$(basename "$1")/4.json"
durable_resync || { echo "resync failed"; exit 1; }
EOF
rm -f "$HOME/conflicted" "$HOME/alerts"
cf=$(conflict_case cf 0)
out=$(bash "$tmp/cf.sh" "$tmp/cf" 2>&1) || fail "a conflicting commit failed the checkpoint or the resync: $out"
on_origin puzzles/cf/2.json >/dev/null || fail "the commit after a conflicting one was not pushed: $out"
on_origin puzzles/cf/3.json >/dev/null || fail "a conflicting commit kept the later ones from origin: $out"
[ "$(on_origin puzzles/cf/1.json)" = '{"n": "theirs"}' ] || fail "origin's version of a conflicting puzzle did not stand"
[ "$(cat "$HOME/conflicted" 2>/dev/null)" = "$cf" ] || fail "the conflicting commit asked no re-read: $out"
[ "$(git -C "$tmp/cf" rev-parse HEAD)" = "$(git --git-dir="$tmp/origin.git" rev-parse master)" ] ||
  fail "the resync did not move the tree past the set-aside commit: $out"
[ "$(cat "$tmp/cf/puzzles/cf/1.json")" = '{"n": "theirs"}' ] || fail "the tree kept the set-aside reading over origin's"
[ -e "$tmp/cf/puzzles/cf/4.json" ] || fail "the resync dropped a file the job had not committed"
[ ! -s "$HOME/alerts" ] || fail "a re-read conflict alerted: $(cat "$HOME/alerts")"
cf=$(conflict_case cf2 1)
out=$(bash "$tmp/cf.sh" "$tmp/cf2" 2>&1) || true
[ "$(git -C "$tmp/cf2" rev-parse -q --verify "refs/durable/conflicts/$cf")" = "$cf" ] ||
  fail "a conflicting commit nothing re-reads was not kept: $out"
[ -s "$HOME/alerts" ] || fail "a conflicting commit nothing re-reads was not alerted: $out"
rm -f "$HOME/alerts"

# 4c. A push that fails every checkpoint (10-13: the pre-push refused what the
#     pass's old code wrote, 5 hours unnoticed) alerts once the streak reaches
#     DURABLE_ALERT_AFTER, once per streak, and a checkpoint that pushes ends it.
git clone -q "$tmp/origin.git" "$tmp/pf" 2>/dev/null
cat >"$tmp/pf.sh" <<'EOF'
cd "$1" || exit 1
DURABLE_PATHS=(puzzles)
DURABLE_ALERT_AFTER=3
. tools/durable.sh
mkdir -p puzzles/pf && echo "{\"n\": $2}" >"puzzles/pf/$2.json"
durable_checkpoint "failing pass"
EOF
git -C "$tmp/pf" remote set-url origin "$tmp/nowhere.git"
rm -f "$HOME/alerts"
for i in 1 2; do bash "$tmp/pf.sh" "$tmp/pf" "$i" >/dev/null 2>&1 && fail "a checkpoint whose push cannot work succeeded"; done
[ ! -s "$HOME/alerts" ] || fail "alerted before DURABLE_ALERT_AFTER failed checkpoints: $(cat "$HOME/alerts")"
bash "$tmp/pf.sh" "$tmp/pf" 3 >/dev/null 2>&1 || true
grep -q "failed 3 checkpoints in a row" "$HOME/alerts" 2>/dev/null || fail "3 failed checkpoints in a row did not alert"
bash "$tmp/pf.sh" "$tmp/pf" 4 >/dev/null 2>&1 || true
[ "$(wc -l <"$HOME/alerts")" = 1 ] || fail "a streak alerted more than once: $(cat "$HOME/alerts")"
git -C "$tmp/pf" remote set-url origin "$tmp/origin.git"
out=$(bash "$tmp/pf.sh" "$tmp/pf" 5 2>&1) || fail "the checkpoint after the push came back failed: $out"
on_origin puzzles/pf/1.json >/dev/null || fail "the commits a failed streak left were not pushed: $out"
[ ! -e "$(git -C "$tmp/pf" rev-parse --path-format=absolute --git-path durable-push-failures)" ] || fail "a pushing checkpoint did not end the streak"
rm -f "$HOME/alerts"

# 4d. A fetch whose transport stalls (10-23 12:46: the ssh to github.com hung a relaunch 4.5 min
#     after a network blip) is cut off after CT_NET_TIMEOUT, and the move goes on with the
#     origin/master last fetched. The remote here is a command that never answers.
git clone -q "$tmp/origin.git" "$tmp/nf" 2>/dev/null
git -C "$tmp/nf" config protocol.ext.allow always
git -C "$tmp/nf" remote set-url origin "ext::sleep 600"
cat >"$tmp/nf.sh" <<'EOF'
cd "$1" || exit 1
DURABLE_PATHS=(puzzles)
. tools/durable.sh
durable_resync
EOF
began=$SECONDS
rc=0
out=$(CT_NET_TIMEOUT=2 timeout 120 bash "$tmp/nf.sh" "$tmp/nf" 2>&1) || rc=$?
{ [ "$rc" = 0 ] && [ $((SECONDS - began)) -lt 60 ]; } ||
  fail "a stalled fetch held the move: rc $rc after $((SECONDS - began))s: $out"
grep -q "fetch of origin/master failed or timed out" <<<"$out" || fail "a cut-off fetch was not said: $out"

# 4e. A checkpoint inside the push window only batches its commit
#     (push_puzzle_commit.sh's refs/push-batch/tip); the resync after it must
#     move the tree onto that batch, not origin/master alone, or the file just
#     filed is gone from the tree until the batch pushes (10-24 23:30: times-14417
#     and times-16746 batched, then removed from the queue's tree 5 s later).
#     The next checkpoint pushes only its own commit, not the batch's again.
git clone -q "$tmp/origin.git" "$tmp/bt" 2>/dev/null
cat >"$tmp/bt.sh" <<'EOF'
cd "$1" || exit 1
DURABLE_PATHS=(puzzles)
. tools/durable.sh
mkdir -p puzzles/bt
for i in $2; do echo "{\"n\": $i}" >"puzzles/bt/$i.json"; done
durable_checkpoint "batch pass" || { echo "checkpoint failed"; exit 1; }
durable_resync || { echo "resync failed"; exit 1; }
EOF
out=$(PUSH_BATCH_SECS=0 bash "$tmp/bt.sh" "$tmp/bt" 1 2>&1) || fail "the first batch-window checkpoint failed: $out"
on_origin puzzles/bt/1.json >/dev/null || fail "a checkpoint outside the window was not pushed: $out"
out=$(PUSH_BATCH_SECS=3600 PUSH_BATCH_FLUSHER=0 bash "$tmp/bt.sh" "$tmp/bt" 2 2>&1) || fail "a batched checkpoint or its resync failed: $out"
case "$out" in *"batched 1 commit(s)"*) ;; *) fail "the second checkpoint was not batched, so the test proves nothing: $out" ;; esac
on_origin puzzles/bt/2.json >/dev/null && fail "a batched commit reached origin before its window: $out"
[ -e "$tmp/bt/puzzles/bt/2.json" ] || fail "the resync dropped a batched puzzle from the tree: $out"
[ "$(git -C "$tmp/bt" rev-parse HEAD)" = "$(git -C "$tmp/bt" rev-parse refs/push-batch/tip)" ] ||
  fail "the resync did not move the tree onto the batch: $out"
[ -z "$(git -C "$tmp/bt" status --porcelain)" ] || fail "the batched puzzle is left untracked or changed: $(git -C "$tmp/bt" status --porcelain)"
# The same shell keeps _durable_pushed across checkpoints, as durable_run does
# (a fresh shell's first checkpoint replays the batch's commits as no-ops).
cat >"$tmp/bt2.sh" <<'EOF'
cd "$1" || exit 1
DURABLE_PATHS=(puzzles)
. tools/durable.sh
echo '{"n": 3}' >puzzles/bt/3.json
durable_checkpoint "batch pass" || exit 1
durable_resync || exit 1
echo "--- moved"
echo '{"n": 4}' >puzzles/bt/4.json
durable_checkpoint "batch pass" || exit 1
EOF
out=$(PUSH_BATCH_SECS=3600 PUSH_BATCH_FLUSHER=0 bash "$tmp/bt2.sh" "$tmp/bt" 2>&1) || fail "checkpoints on the batch failed: $out"
case "${out#*--- moved}" in *"already has"*) fail "a checkpoint after the move replayed the batch's commits again: $out" ;; esac
case "${out#*--- moved}" in *"batched 3 commit(s)"*) ;; *) fail "the checkpoint after the move did not add to the batch: $out" ;; esac
[ -e "$tmp/bt/puzzles/bt/3.json" ] || fail "the second move dropped a batched puzzle: $out"
[ "$(git -C "$tmp/bt" rev-list --count origin/master..refs/push-batch/tip)" = 3 ] ||
  fail "the batch holds $(git -C "$tmp/bt" rev-list --count origin/master..refs/push-batch/tip) commits, not 3: $out"
out=$(cd "$tmp/bt" && PUSH_NOW=1 bash tools/push_puzzle_commit.sh --flush 2>&1) || fail "the batch did not flush: $out"
for i in 2 3 4; do on_origin "puzzles/bt/$i.json" >/dev/null || fail "batched puzzle $i never reached origin: $out"; done
out=$(PUSH_BATCH_SECS=0 bash "$tmp/bt.sh" "$tmp/bt" "" 2>&1) || fail "the move after the flush failed: $out"
[ "$(git -C "$tmp/bt" rev-parse HEAD)" = "$(git --git-dir="$tmp/origin.git" rev-parse master)" ] ||
  fail "with no batch waiting the resync did not move the tree to origin/master: $out"

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
# Not the bridge's track-job.sh: a real one would register the fake pass with the room.
tj = home / "track-job.sh"
tj.write_text('#!/bin/bash\nwhile [ "$1" != "--" ]; do shift; done; shift\n'
              'setsid "$@" >> "$HOME/pass.log" 2>&1 < /dev/null &\necho $!\n')
tj.chmod(0o755)
q.TRACK_JOB = str(tj)
os.environ.pop("STATE_DIR", None)
os.environ.pop("TRACKED_JOBS_DIR", None)
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
                       "there can move a file to another (fetch_puzzle.write_puzzle_file unlinks "
                       "the old path), and that deletion would never be committed")
    if "durable.sh" in text and "durable_run" not in text and "durable_checkpoint" not in text:
        bad.append(f"tools/{script} sources tools/durable.sh but never checkpoints")
assert not bad, "\n".join(bad)
assert "durable_run" in corpus_queue.FULL_PASS.read_text(), "the full pass files without checkpoints"
print(f"long jobs: {', '.join(sorted(long_jobs))}")
PY
# 7. Slice boundaries: the real tools/ocr_full_pass.sh, its queue stubbed.
#    The first slice files a puzzle and pushes a change to the script to
#    origin, as a fix landing mid-pass would. Its commit and push run
#    beside the second slice; the puzzle still reaches origin. The second slice's end re-execs onto the
#    moved script (the same process, the handover kept), and the third runs
#    the new code.
git clone -q "$tmp/origin.git" "$tmp/fp" 2>/dev/null
cp tools/ocr_full_pass.sh "$tmp/fp/tools/"
for stub in gale_inbox trove_solution_ocr file_archive_org_puzzles; do echo 'pass' >"$tmp/fp/tools/$stub.py"; done
cat >"$tmp/fp/tools/edition_queue.py" <<'EOF'
import os, subprocess, sys, time
home = os.environ["HOME"]
handoff = sys.argv[sys.argv.index("--handoff") + 1]
n = 1 + sum(1 for _ in open(f"{home}/slices")) if os.path.exists(f"{home}/slices") else 1
with open(f"{home}/slices", "a") as f:
    f.write(f"{n}\n")
open(handoff, "w").write("[]")
if n == 1:
    open("puzzles/a/fp1.json", "w").write('{"n": "fp1"}\n')
    edit = f"{home}/fp-edit"
    subprocess.run(["git", "clone", "-q", os.environ["FP_ORIGIN"], edit], check=True)
    path = f"{edit}/tools/ocr_full_pass.sh"
    text = open(path).read()
    assert '=== $what: slice from' in text
    open(path, "w").write(text.replace('=== $what: slice from', '=== $what: new code, slice from'))
    subprocess.run(["git", "-C", edit, "commit", "-qam", "a fix to the pass"], check=True)
    subprocess.run(["git", "-C", edit, "push", "-q", "origin", "HEAD:master"], check=True)
    print("3 left for the next run")
elif n == 2:
    print("2 left for the next run")
else:
    print("handoff kept" if os.path.exists(handoff) else "handoff lost")
EOF
git -C "$tmp/fp" add -A && git -C "$tmp/fp" commit -qm "the full pass" && git -C "$tmp/fp" push -q origin HEAD:master 2>/dev/null
FP_ORIGIN="$tmp/origin.git" setsid bash "$tmp/fp/tools/ocr_full_pass.sh" >"$tmp/fp.log" 2>&1 & pid=$!
wait "$pid" || { cat "$tmp/fp.log"; fail "the full pass failed across its re-exec"; }
pid=""
on_origin puzzles/a/fp1.json | grep fp1 >/dev/null || { cat "$tmp/fp.log"; fail "what the first slice filed never reached origin"; }
grep -q "=== shell code moved: re-execing onto" "$tmp/fp.log" || { cat "$tmp/fp.log"; fail "the full pass did not re-exec when its script moved"; }
grep -q "new code, slice from" "$tmp/fp.log" || { cat "$tmp/fp.log"; fail "the slice after the re-exec ran the old code"; }
grep -q "handoff kept" "$tmp/fp.log" || { cat "$tmp/fp.log"; fail "the re-exec dropped what the slice before it handed over"; }
[ "$(wc -l <"$HOME/slices")" = 3 ] || { cat "$tmp/fp.log"; fail "the pass re-ran a slice"; }

echo "durable: ok"
