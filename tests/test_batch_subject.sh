#!/bin/bash
# A batch commit's subject names only the puzzles whose file the commit changes
# (164738e46f2 listed 20 ids and changed just the queue file).
#
#     bash tests/test_batch_subject.sh
#
# worker_commit_batch is read out of tools/puzzle_worker.sh and run in a scratch
# git tree with the commit and staging stubbed to what the real ones leave in
# the index.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}
tree="$(mktemp -d)"
trap 'rm -rf "$tree"' EXIT
mkdir -p "$tree/tools" "$tree/p"
printf '#!/usr/bin/env python3\n' >"$tree/tools/own_rows.py"
cd "$tree" || exit 1
git init -q .
git config user.email t@t
git config user.name t
echo old >p/a.json
echo old >p/b.json
echo q0 >queue.json
git add -A
git commit -qm base

puzzle_spec() { echo "p/$1.json"; }
clues_spec() { echo "p/$1.clues.json"; }
eval "$(sed -n '/^puzzle_specs() {/,/^}/p' "$REPO/tools/puzzle_worker.sh")"
eval "$(sed -n '/^worker_commit_batch() {/,/^}/p' "$REPO/tools/puzzle_worker.sh")"
index_lock() { :; }
index_unlock() { :; }
alert() { echo "ALERT $*"; }
worker_settle() { :; }
stage_puzzles() { git add -A; }
worker_commit() { SUBJECT="$1"; BODY="${WORKER_COMMIT_BODY:-}"; WORKER_COMMIT_BODY=; }
declare -gA WORKER_BATCH_POST=([a]="||" [b]="||")
WORKER_JOB=t

echo new >p/a.json
echo q1 >queue.json
WORKER_BATCH_IDS=(a b)
worker_commit_batch Annotate >/dev/null
check "only the changed puzzle is named" "Annotate a" "$SUBJECT"

echo new >p/b.json
WORKER_BATCH_IDS=(a b)
worker_commit_batch Annotate >/dev/null
check "both changed: short subject" "Annotate 2 puzzles" "$SUBJECT"
check "both changed: ids in the body" "a b" "$BODY"

git add -A
git commit -qm two
echo q2 >queue.json
WORKER_BATCH_IDS=(a b)
worker_commit_batch Annotate >/dev/null
check "no puzzle file changed" "Annotate: queue rows of 2 puzzles, no puzzle file changed" "$SUBJECT"
exit $((fails > 0))
