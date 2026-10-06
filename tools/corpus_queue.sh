#!/bin/bash
# The scheduled entry point for tools/corpus_queue.py tick: runs it
# from a worktree at origin/master (tools/nightly_worktree.sh). Arguments pass through.
# The tick must return in seconds (the plugin's timeout is 600s), and neither
# it nor tools/coverage.sh reads puzzles/index.* or abbreviations.js:
# no rebuild here. The job it starts rebuilds them in its own session.
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_GENERATED=none
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
exec python3 tools/corpus_queue.py "$@"
