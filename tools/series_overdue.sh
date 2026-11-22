#!/bin/bash
# The scheduled entry point for tools/series_overdue.py: runs it from a
# worktree at origin/master, so a fix that is pushed is the code the next run
# runs (see tools/nightly_worktree.sh). Arguments pass through. It reads the live puzzle index only.
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_GENERATED=none
# Needs only tools/ (its imports are all there) and rebuilds in seconds, so the
# tree is sparse and removed when the run ends (tools/nightly_worktree.sh).
# shellcheck disable=SC2034
CT_SPARSE="tools"
# shellcheck disable=SC2034
CT_REMOVE_TREE=1
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
exec python3 tools/series_overdue.py "$@"
