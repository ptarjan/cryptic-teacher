#!/bin/bash
# The long run of tools/gale_fetch.py: every Times page the wanted list
# (gale_inbox.wanted) still lacks, downloaded at a hand's pace and laid out
# at once as its date's edition, which tools/gale_read.sh files. Started by
# hand through track-job (--restart: every row it already got is skipped,
# so a restart resumes):
#
#     /app/tools/track-job.sh --log "$HOME/.cache/gale_fetch.log" --restart cryptic-crosswords \
#       --run "Gale downloads" "tail -1 $HOME/.cache/gale_fetch.log" -- bash tools/gale_fetch.sh
#
# Runs from its own worktree at origin/master (tools/nightly_worktree.sh),
# whose lease keeps it to one run at a time. It files nothing into git (the
# reads do), so there is nothing for tools/durable.sh to checkpoint: each
# edition is renamed in whole or not at all, and logged in
# ~/.cache/gale_inbox/fetched.json as it lands. A refusal (Gale's limit) is
# recorded in ~/.cache/gale_inbox/limits.json and waited out. Exit 2: a
# captcha, a wrong PDF, Gale refusing through every probe, or repeated
# errors; the room was woken, and it must not be restarted until someone
# has looked. Stopping it: kill the python3 child as well as this wrapper.
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_GENERATED=none
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
export PYTHONUNBUFFERED=1
exec python3 tools/gale_fetch.py "$@"
