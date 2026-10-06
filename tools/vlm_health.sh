#!/bin/bash
# The scheduled entry point for tools/vlm_health.py (the cryptic-vlm-health
# plugin), run from a worktree at origin/master (tools/nightly_worktree.sh).
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_GENERATED=none
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
exec python3 tools/vlm_health.py "$@"
