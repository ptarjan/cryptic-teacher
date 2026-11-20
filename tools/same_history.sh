#!/bin/bash
# Refuse a tree whose history shares nothing with origin/master.
#
#     tools/same_history.sh [<rev>]      # <rev> defaults to HEAD
#
# Exit 0 when <rev> and origin/master have a common ancestor, 1 (with a message on
# stderr) when they have none. It fetches nothing: call it right after the fetch and
# before any rebase, pull or push. Master was once squashed to a single orphan
# commit; a tree still on the old history that rebased onto the new root would replay
# all of the old history on top of it and push it back.
rev="${1:-HEAD}"
if ! git merge-base "$rev" origin/master >/dev/null 2>&1; then
  echo "$rev shares no history with origin/master — this tree predates the history squash; hard-reset it to origin/master and redo the work" >&2
  exit 1
fi
