#!/bin/bash
# Does tools/same_history.sh refuse a tree whose history shares no root with
# origin/master (one that predates the history squash), and pass a related one?
#
#     bash tests/test_same_history.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else
  echo "FAIL $1"; echo "       want $3"; echo "       got  $2"; fails=$((fails + 1)); fi; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com

git init -q --bare -b master "$tmp/origin.git"
git init -q -b master "$tmp/old"
git -C "$tmp/old" commit -q --allow-empty -m old
git -C "$tmp/old" remote add origin "$tmp/origin.git"
git -C "$tmp/old" push -q origin master
git clone -q "$tmp/origin.git" "$tmp/related"
git -C "$tmp/related" commit -q --allow-empty -m next

(cd "$tmp/related" && bash "$ROOT/tools/same_history.sh" 2>/dev/null); check "related history passes" "$?" 0

# origin is squashed to an orphan commit; the old tree fetches it
git init -q -b master "$tmp/new"
git -C "$tmp/new" commit -q --allow-empty -m squashed
git -C "$tmp/new" push -q -f "$tmp/origin.git" master
git -C "$tmp/old" fetch -q origin master
out=$(cd "$tmp/old" && bash "$ROOT/tools/same_history.sh" 2>&1); rc=$?
check "unrelated history refused" "$rc" 1
case "$out" in
  *"predates the history squash"*) check "message says why" ok ok ;;
  *) check "message says why" "$out" "predates the history squash" ;;
esac

exit "$fails"
