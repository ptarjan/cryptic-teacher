#!/bin/bash
# The scheduled entry point for tools/coverage.py (daily): runs it from a
# worktree at origin/master (tools/nightly_worktree.sh), so "filed" counts
# what is pushed. Arguments pass through. It reads caches and puzzle files
# only, in seconds; it is not a corpus job and needs no rebuild.
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_GENERATED=none
# It files nothing into git: its ledger goes to ~/.cache/coverage_ledger
# (COVERAGE_STATE). Set empty, so a drop salvages no paths, only any local
# commit the tree holds; its 1800 s timeout puts it among the long jobs.
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_SALVAGE_PATHS=""
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
exec python3 tools/coverage.py "$@"
