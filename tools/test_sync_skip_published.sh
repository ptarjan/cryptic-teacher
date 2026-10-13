#!/bin/bash
# The burn's sync (tools/prereset_backfill.sh sync_attempt + sync_tree), with
# runs in flight: publishing drops a commit whose puzzle origin/master already
# holds and stops on any other conflict; moving the tree brings origin's code in
# and keeps a run's uncommitted edit, or refuses whole when origin changed the
# file that run is writing.
set -u
here=$(cd "$(dirname "$0")" && pwd)
eval "$(sed -n '/^sync_attempt() {/,/^}/p;/^publish_commits() {/,/^}/p;/^sync_tree() {/,/^}/p;/^shelve_code_edits() {/,/^}/p' "$here/prereset_backfill.sh")"
alert() { echo "$*" >>"$t/alerts"; }
tools/push_puzzle_commit.sh() { bash "$here/push_puzzle_commit.sh" "$@" 2>/dev/null; }
t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
export PRERESET_SHELF="$t/shelf"
fail=0; check() { if eval "$2"; then echo "ok - $1"; else echo "FAIL - $1"; fail=1; fi; }
g() { git -c user.name=t -c user.email=t@t "$@"; }
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
git init -q --bare "$t/o.git"
g clone -q "$t/o.git" "$t/m" 2>/dev/null; cd "$t/m"
mkdir -p puzzles/x/1 tools; echo a > puzzles/x/1/p.json; echo a > puzzles/x/1/q.json
printf 'row0\n' > tools/t.py; echo v1 > tools/plan.py
g add -A; g commit -qm base; g push -q origin HEAD:master
g clone -q "$t/o.git" "$t/b"; cd "$t/b"; g checkout -q --detach

# A commit of the burn's whose puzzle origin already has, beside a side file
# that conflicts.
echo annotated > puzzles/x/1/p.json; printf 'row0\nrow1\n' > tools/t.py; g commit -qam burn
cd "$t/m"; echo annotated > puzzles/x/1/p.json; printf 'moved\n' > tools/t.py; echo v2 > tools/plan.py
g commit -qam master; g push -q origin HEAD:master
cd "$t/b"
# A run in flight writing q.json, which origin did not change.
echo inflight > puzzles/x/1/q.json
sync_attempt 2>/dev/null && sync_tree
check "published commit dropped, tree at origin/master" '[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/master)" ]'
check "origin's code change reached the tree" '[ "$(cat tools/plan.py)" = v2 ]'
check "the in-flight edit survives the sync" '[ "$(cat puzzles/x/1/q.json)" = inflight ]'

# A run in flight writing a file origin changed: the move refuses, touching nothing.
cd "$t/m"; g pull -q origin master 2>/dev/null; echo fixed > puzzles/x/1/q.json; echo v3 > tools/plan.py
g commit -qam fix; g push -q origin HEAD:master
cd "$t/b"; before=$(git rev-parse HEAD)
sync_attempt 2>/dev/null; rc=$?
check "nothing to publish succeeds" '[ "$rc" -eq 0 ]'
sync_tree 2>/dev/null; rc=$?
check "the move refuses over an in-flight file origin changed" '[ "$rc" -ne 0 ]'
check "a refused move leaves HEAD, the run's file and the code as they were" \
  '[ "$(git rev-parse HEAD)" = "$before" ] && [ "$(cat puzzles/x/1/q.json)" = inflight ] && [ "$(cat tools/plan.py)" = v2 ]'
git checkout -q -- puzzles/x/1/q.json; sync_tree

# An unpublished commit that conflicts stops publishing and keeps HEAD.
echo other > puzzles/x/1/p.json; printf 'mine\n' > tools/t.py; g commit -qam burn2
cd "$t/m"; g pull -q origin master 2>/dev/null; echo theirs > puzzles/x/1/p.json; printf 'theirs\n' > tools/t.py
g commit -qam m2; g push -q origin HEAD:master
cd "$t/b"; mine=$(git rev-parse HEAD)
sync_attempt 2>/dev/null; rc=$?
check "unpublished conflict fails" '[ "$rc" -ne 0 ]'
check "unpublished conflict leaves HEAD and origin alone" \
  '[ "$(git rev-parse HEAD)" = "$mine" ] && [ "$(git show origin/master:tools/t.py)" = theirs ]'
# A run's uncommitted edit to CODE origin also changed (genius-263's
# tools/hidden_messages.py, 10-13): the worker never commits code, so left in
# place it refuses every move. It is saved as a patch, put back, and alerted;
# a code edit origin did not touch, and a run's puzzle, are left alone.
g reset -q --hard origin/master
printf 'local fix\n' > tools/plan.py; printf 'local t\n' > tools/t.py; echo inflight2 > puzzles/x/1/q.json
cd "$t/m"; g pull -q origin master 2>/dev/null; echo v4 > tools/plan.py; g commit -qam v4; g push -q origin HEAD:master
cd "$t/b"; git fetch -q origin master
sync_tree 2>/dev/null; rc=$?
check "a code edit origin changed no longer blocks the move" '[ "$rc" -eq 0 ] && [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/master)" ]'
check "the tree takes origin's code" '[ "$(cat tools/plan.py)" = v4 ]'
check "the shelved edit is kept as a patch" 'grep -q "^+local fix" "$t"/shelf/*.patch'
check "and said out loud" 'grep -q "tools/plan.py" "$t/alerts"'
check "a code edit origin did not change stays" '[ "$(cat tools/t.py)" = "local t" ] && ! grep -q "local t" "$t"/shelf/*.patch'
check "the run's puzzle is untouched" '[ "$(cat puzzles/x/1/q.json)" = inflight2 ]'
# Nowhere to save it: nothing is put back and the move waits.
cd "$t/m"; g pull -q origin master 2>/dev/null; echo v5 > tools/plan.py; g commit -qam v5; g push -q origin HEAD:master
cd "$t/b"; git fetch -q origin master; printf 'again\n' > tools/plan.py; before=$(git rev-parse HEAD)
PRERESET_SHELF=/dev/null/x sync_tree 2>/dev/null; rc=$?
check "an unsavable edit is kept and the move refused" '[ "$rc" -ne 0 ] && [ "$(cat tools/plan.py)" = again ] && [ "$(git rev-parse HEAD)" = "$before" ]'
exit $fail
