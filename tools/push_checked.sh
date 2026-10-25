#!/bin/bash
# Push local commits to origin/master, each first checked by tools/clobber_guard.py.
#
#     tools/push_checked.sh            # commits in origin/master..HEAD
#
# For code and docs a session commits itself and pushes as is (puzzle commits go
# through tools/push_puzzle_commit.sh, which runs the same guard). Refuses, with
# the guard's exit 4, a stack holding a commit made from a stale tree.
#
# A rule edit that newly flags committed puzzles is not requeued here: the deploy's full
# check (pages.yml, "Requeue what the rules newly flag") raises their allowances and
# queues the clues as a commit of its own (tools/requeue_drift.py --publish). By hand:
# python3 tools/requeue_drift.py --write.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

git fetch -q origin master || exit 1
for c in $(git rev-list --reverse origin/master..HEAD); do
  python3 "$here/clobber_guard.py" "$c" || exit $?
done
git push -q origin HEAD:master || exit $?
exit 0
