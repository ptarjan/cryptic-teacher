#!/bin/bash
# Push local commits to origin/master, each first checked by tools/clobber_guard.py.
#
#     tools/push_checked.sh            # commits in origin/master..HEAD
#
# For code and docs a session commits itself and pushes as is (puzzle commits go
# through tools/push_puzzle_commit.sh, which runs the same guard). Refuses, with
# the guard's exit 4, a stack holding a commit made from a stale tree. A stack that edits
# the validator's rules also gets a requeue commit (see the end), so the deploy stays green.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
git fetch -q origin master || exit 1
for c in $(git rev-list --reverse origin/master..HEAD); do
  python3 "$here/clobber_guard.py" "$c" || exit $?
done
# A rule edit must never turn the deploy red: when the stack changes the validator's code or a
# data file it reads (validate_scope.py says the deploy would re-check every puzzle for that),
# the puzzles the edit newly flags are requeued here, in a commit of their own, as
# daily_update.sh does after a lexicon rebuild (tools/requeue_drift.py).
scope=$(python3 "$here/validate_scope.py" origin/master 2>/dev/null | head -n 1)
case "$scope" in
  "full the check's code changed"*|"full "*"a file the check reads"*)
    echo "push_checked: $scope; requeuing puzzles the rule change newly flags"
    if python3 "$here/requeue_drift.py" --write; then
      if ! git diff --quiet -- tools/data/shape_reannotate.json tools/annotation_backlog.json; then
        git add tools/data/shape_reannotate.json tools/annotation_backlog.json &&
          git commit -q -m "Requeue puzzles newly flagged by a validator rule change

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" || exit 1
        echo "push_checked: committed the requeue"
      fi
    else
      echo "push_checked: requeue_drift.py failed; the deploy may fail on the rule change" >&2
    fi ;;
esac
exec git push -q origin HEAD:master
