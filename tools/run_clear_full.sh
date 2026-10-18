#!/bin/bash
# The full clear_unchecked --write sweep, resumable and published as it goes.
#
#     tools/run_clear_full.sh [<last-done-id>]    # e.g. everyman-3416, the last id a killed run's log shows
#
# Run it from a worktree of its own (git worktree add), under tools/track-job.sh --restart.
# clear_unchecked commits each cleared puzzle and publishes every 100 commits
# (--push-every), so a kill loses at most the last batch; running the script again from the
# last id in the log (--start-after) continues where it stopped, and puzzles already cleared
# are skipped anyway. When the sweep ends it publishes the shrunken wordplay.unchecked
# allowance and prunes the shape queue.
set -uo pipefail
cd "$(dirname "$0")/.."
/app/tools/deprioritize.sh -q 19 $$
git pull --rebase -q origin master || exit 1
after=()
[ -n "${1:-}" ] && after=(--start-after "$1")
CT_JOBS=2 python3 tools/clear_unchecked.py --write --push-every 100 ${after[@]+"${after[@]}"} || exit 1
git add tools/annotation_backlog.json
if ! git diff --cached --quiet; then
  git commit -q -m "Shrink the wordplay.unchecked allowance after the clear_unchecked sweep" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
  tools/push_puzzle_commit.sh HEAD
fi
python3 tools/prune_shape_queue.py --write
if [ -n "$(git status --porcelain tools/data)" ]; then
  git add tools/data
  git commit -q -m "Prune the shape queue after the clear_unchecked sweep" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
  tools/push_puzzle_commit.sh HEAD
fi
echo "done"
