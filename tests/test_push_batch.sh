#!/bin/bash
# Does tools/push_puzzle_commit.sh batch pushes that come inside its window,
# and does the batch always reach origin, with every commit kept as its own?
#
# The burn pushing each puzzle alone backed GitHub Actions up four hours
# (10-21), so pushes from a machine go out at most once per PUSH_BATCH_SECS.
# This runs it against a real origin: the first push goes, the next ones wait
# in refs/push-batch/tip, --flush (as the detached flusher runs it) publishes
# them in one push, a batch origin moved under is replayed onto origin, and
# PUSH_NOW=1 pushes at once.
#
#     bash tests/test_push_batch.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else
  echo "FAIL $1"; echo "       want $3"; echo "       got  $2"; fails=$((fails + 1)); fi; }

export PUSH_BATCH_SECS=300 PUSH_BATCH_FLUSHER=0
unset PUSH_NOW
tmp="$(mktemp -d)"
trap '[ -n "${KEEP_TMP:-}" ] && echo "kept $tmp" || rm -rf "$tmp"' EXIT
cd "$tmp" || exit 1
ident() { git config user.email nobody@example.com; git config user.name test; }
git init -q --bare -b master origin.git
git clone -q origin.git seed 2>/dev/null && cd seed && ident || exit 1
mkdir -p tools puzzles/cryptic/2026
cp "$ROOT/tools/push_puzzle_commit.sh" "$ROOT/tools/clobber_guard.py" tools/
echo '{"id":"cryptic-0"}' > puzzles/cryptic/2026/cryptic-0.json
git add -A && git commit -qm base && git push -q origin master
cd .. && git clone -q origin.git burn && git clone -q origin.git upstream
(cd burn && ident) && (cd upstream && ident)

cd burn || exit 1
file() { echo "{\"id\":\"$1\"}" > "puzzles/cryptic/2026/$1.json" && git add -A && git commit -qm "Annotate $1"; }
origin_log() { git --git-dir="$tmp/origin.git" log --format=%s master | tr '\n' ' '; }

file cryptic-1; tools/push_puzzle_commit.sh 2>/dev/null
check "first push goes at once" "$(origin_log)" "Annotate cryptic-1 base "

file cryptic-2; tools/push_puzzle_commit.sh 2>/dev/null; rc2=$?
file cryptic-3; tools/push_puzzle_commit.sh 2>/dev/null; rc3=$?
check "pushes inside the window exit 0" "$rc2 $rc3" "0 0"
check "and leave origin alone" "$(origin_log)" "Annotate cryptic-1 base "
check "they wait in the batch, one commit each" \
  "$(git log --format=%s origin/master..refs/push-batch/tip | tr '\n' ' ')" "Annotate cryptic-3 Annotate cryptic-2 "
check "--sync-target names the batch" "$(tools/push_puzzle_commit.sh --sync-target)" "$(git rev-parse refs/push-batch/tip)"
tools/push_puzzle_commit.sh HEAD~1 2>/dev/null
check "re-pushing a batched commit adds nothing" "$(git rev-list --count origin/master..refs/push-batch/tip)" "2"

# Window still closed: --flush holds; with it open (stamp aged), it publishes.
echo $(( $(date +%s) - 301 )) > "$(git rev-parse --git-common-dir)/push_batch.last"
tools/push_puzzle_commit.sh --flush 2>/dev/null
check "--flush publishes the batch in one push" "$(origin_log)" "Annotate cryptic-3 Annotate cryptic-2 Annotate cryptic-1 base "
check "and clears it" "$(git rev-parse -q --verify refs/push-batch/tip)" ""
check "--sync-target is origin/master again" "$(tools/push_puzzle_commit.sh --sync-target)" "$(git rev-parse origin/master)"

# Origin moves under a waiting batch: the flush replays the batch onto it.
file cryptic-4; tools/push_puzzle_commit.sh 2>/dev/null
(cd ../upstream && git pull -q --rebase origin master && echo x > other.txt && git add -A &&
  git commit -qm "upstream code" && git push -q origin master)
PUSH_NOW=1 tools/push_puzzle_commit.sh --flush 2>/dev/null
check "a batch origin moved under is replayed onto it" "$(origin_log)" \
  "Annotate cryptic-4 upstream code Annotate cryptic-3 Annotate cryptic-2 Annotate cryptic-1 base "

# PUSH_NOW: a commit inside the window goes at once, with any batch before it.
file cryptic-5; tools/push_puzzle_commit.sh 2>/dev/null
file cryptic-6; PUSH_NOW=1 tools/push_puzzle_commit.sh 2>/dev/null
check "PUSH_NOW pushes the batch and the commit at once" "$(origin_log | cut -d' ' -f1-4)" \
  "Annotate cryptic-6 Annotate cryptic-5"

# The last commit of a run is never stranded: the detached flusher pushes it
# once the window opens, with nothing else calling (a 2s window here).
file cryptic-7; PUSH_BATCH_SECS=2 PUSH_BATCH_FLUSHER=1 tools/push_puzzle_commit.sh 2>/dev/null
for _ in $(seq 30); do
  [ "$(origin_log | cut -d' ' -f1-2)" = "Annotate cryptic-7" ] && break
  sleep 0.5
done
check "the detached flusher pushes the last batched commit" "$(origin_log | cut -d' ' -f1-2)" "Annotate cryptic-7"

exit $((fails > 0))
