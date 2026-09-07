#!/bin/bash
# When the nightly push loses a race, does it rebuild or does it strand the day?
#
# The daily job commits in its own worktree and pushes last, so anything an
# interactive session pushed while it worked is on master first. The files that
# collide are always the GENERATED ones — puzzles/index.json, puzzles/index.js,
# README.md, the per-puzzle pages — because both sides rebuilt them from their
# own view of the corpus. That is not a disagreement, and on 2026-09-06 and
# 2026-09-07 it cost the site a day each time: the rebase stopped, the push
# never happened, and a finished night's annotations sat in a detached worktree
# until someone went looking.
#
#     bash tools/test_push_conflict.sh
#
# rebuild_generated_conflicts is READ OUT of tools/daily_update.sh by its own
# first and last lines rather than copied here, so the thing under test is the
# thing that runs. The case that matters is the third one: a conflict in a file
# no builder owns must NOT be resolved, or the job silently publishes one side
# of somebody's real edit.
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }

fn=$(awk '/^  rebuild_generated_conflicts\(\) \{$/,/^  \}$/' tools/daily_update.sh)
[ -n "$fn" ] ||
  { echo "FAIL: rebuild_generated_conflicts is no longer where this test reads it from"; exit 1; }

# A throwaway clone, because every case here ends mid-rebase and the real
# checkout is not a place to leave one.
sand=$(mktemp -d)
trap 'rm -rf "$sand"' EXIT
git clone -q --local --no-hardlinks "$REPO" "$sand/work" || { echo "FAIL: clone"; exit 1; }
cd "$sand/work" || exit 1
git config user.email nobody@example.com
git config user.name "test"
eval "$fn"

rebase_running() { [ -d "$(git rev-parse --git-path rebase-merge)" ] ||
                   [ -d "$(git rev-parse --git-path rebase-apply)" ]; }
base=$(git rev-parse HEAD)
# Rewrite one line of a file, so the two sides collide on it and nothing else.
poke() { python3 -c '
import sys
path, line, text = sys.argv[1], int(sys.argv[2]), sys.argv[3]
lines = open(path, encoding="utf-8").read().split("\n")
lines[line] = text
open(path, "w", encoding="utf-8").write("\n".join(lines))
' "$1" "$2" "$3"; }

echo "a rebase that never started is not a conflict:"
rebuild_generated_conflicts; check "returns non-zero with no rebase in progress" "$?" "1"

echo "a conflict in a generated file is rebuilt and the pick lands:"
git checkout -q -B upstream "$base"
poke puzzles/index.json 1 ' "latest": "upstream-side",'
git commit -qam "upstream rebuilt the index"
git checkout -q -B nightly "$base"
poke puzzles/index.json 1 ' "latest": "nightly-side",'
# A second, non-colliding change, so the pick is not empty once the index is
# rebuilt. It has to be an existing tracked file: build_readme.py refuses to run
# against a new file with no row in its layout table, and this function runs it.
printf '\n<!-- the night'"'"'s own work -->\n' >> APP.md
git commit -qam "the night's work"
git rebase -q upstream >/dev/null 2>&1
check "the rebase did stop" "$(git diff --name-only --diff-filter=U)" "puzzles/index.json"
rebuild_generated_conflicts; check "returns zero" "$?" "0"
# The state directory, not REBASE_HEAD: git leaves that ref behind afterwards.
check "the rebase finished" "$(rebase_running && echo yes)" ""
check "the night's own change survived" \
  "$(grep -c "the night's own work" APP.md)" "1"
check "no markers left in the index" "$(grep -c '^<<<<<<< ' puzzles/index.json)" "0"
check "the index is valid JSON again" \
  "$(python3 -c 'import json;json.load(open("puzzles/index.json"));print("ok")' 2>&1)" "ok"
check "nothing left uncommitted" "$(git status --porcelain)" ""
# index.html is not one of the conflicted files, but it carries the content
# hash of an index.js the rebuild just rewrote. Nothing else here would
# notice it going stale: the page loads, and only a cache serves the wrong
# bytes.
check "the asset stamps match what was rebuilt" \
  "$(python3 tools/stamp_assets.py --check 2>&1)" "asset stamps up to date"

echo "a conflict no builder owns is left alone:"
git checkout -q -B upstream2 "$base"
printf '\n// upstream edited this by hand\n' >> app.js
git commit -qam "a human edited app.js"
git checkout -q -B nightly2 "$base"
printf '\n// the night edited this by hand\n' >> app.js
git commit -qam "the night edited app.js"
git rebase -q upstream2 >/dev/null 2>&1
rebuild_generated_conflicts; check "returns non-zero" "$?" "1"
check "the rebase is still in progress for the caller to abort" \
  "$(rebase_running && echo yes)" "yes"
check "app.js was not resolved behind anyone's back" \
  "$(git diff --name-only --diff-filter=U)" "app.js"
git rebase --abort

if [ "$fails" -eq 0 ]; then echo "push conflict: all checks passed"; else
  echo "push conflict: $fails check(s) failed"; exit 1; fi
