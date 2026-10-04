#!/bin/bash
# sync_attempt drops a conflicting commit whose puzzle origin/master already
# holds, and aborts cleanly on any other conflict.
set -u
here=$(cd "$(dirname "$0")" && pwd)
eval "$(sed -n '/^sync_attempt() {/,/^}/p;/^skip_published_conflicts() {/,/^}/p' "$here/prereset_backfill.sh")"
t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
fail=0; check() { if eval "$2"; then echo "ok - $1"; else echo "FAIL - $1"; fail=1; fi; }
g() { git -c user.name=t -c user.email=t@t "$@"; }
git init -q --bare "$t/o.git"
g clone -q "$t/o.git" "$t/m" 2>/dev/null; cd "$t/m"
mkdir -p puzzles/x/1 tools; echo a > puzzles/x/1/p.json; printf 'row0\n' > tools/t.py
g add -A; g commit -qm base; g push -q origin HEAD:master
g clone -q "$t/o.git" "$t/b"; cd "$t/b"; g checkout -q --detach
echo annotated > puzzles/x/1/p.json; printf 'row0\nrow1\n' > tools/t.py; g commit -qam burn
cd "$t/m"; echo annotated > puzzles/x/1/p.json; printf 'moved\n' > tools/t.py; g commit -qam master; g push -q origin HEAD:master
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
sync_attempt 2>/dev/null
check "published commit dropped" '[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/master)" ]'
check "no unmerged files" '[ -z "$(git ls-files -u)" ]'
echo other > puzzles/x/1/p.json; printf 'mine\n' > tools/t.py; git commit -qam burn2
cd "$t/m"; echo theirs > puzzles/x/1/p.json; printf 'theirs\n' > tools/t.py; g commit -qam m2; g push -q origin HEAD:master
cd "$t/b"; mine=$(git rev-parse HEAD)
sync_attempt 2>/dev/null; rc=$?
check "unpublished conflict fails" '[ "$rc" -ne 0 ]'
check "unpublished conflict aborted to the old HEAD" '[ "$(git rev-parse HEAD)" = "$mine" ] && [ ! -d "$(git rev-parse --git-path rebase-merge)" ]'
exit $fail
