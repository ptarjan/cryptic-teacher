#!/bin/bash
# The scheduled entry point for tools/corpus_queue.py (tick, nightly): runs it
# from a worktree at origin/master (tools/nightly_worktree.sh). Arguments pass through.
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
exec python3 tools/corpus_queue.py "$@"
