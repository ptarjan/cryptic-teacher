#!/bin/bash
# The scheduled entry point for tools/vlm_health.py (the cryptic-vlm-health
# plugin), run from a worktree at origin/master (tools/nightly_worktree.sh).
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_GENERATED=none
# Needs only tools/ and rebuilds in seconds: a sparse tree, removed when the run
# ends (tools/nightly_worktree.sh).
# shellcheck disable=SC2034
CT_SPARSE="tools"
# shellcheck disable=SC2034
CT_REMOVE_TREE=1
# An up VLM that was up last tick is nothing to do (vlm_health.py --quick, one
# HTTP request): stop before the worktree setup, ~20 processes and a reset of
# the whole tree. A full tick still runs hourly, which brings a pushed fix here.
if [ "${CT_IN_WORKTREE:-0}" != 1 ] && [ $# = 0 ]; then
  _vh_stamp=~/.cache/vlm_health/full_tick.stamp
  if [ -n "$(find "$_vh_stamp" -mmin -60 2>/dev/null)" ] &&
     PYTHONPATH="$(python3 "$(dirname "$0")/local_config.py" household_dir)/tools${PYTHONPATH:+:$PYTHONPATH}" \
       python3 "$(dirname "$0")/vlm_health.py" --quick; then
    exit 0
  fi
  mkdir -p "${_vh_stamp%/*}" && touch "$_vh_stamp"
fi
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
# watchlib, the wake's state, is household's.
PYTHONPATH="$(python3 tools/local_config.py household_dir)/tools${PYTHONPATH:+:$PYTHONPATH}" exec python3 tools/vlm_health.py "$@"
