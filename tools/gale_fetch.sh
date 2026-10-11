#!/bin/bash
# The long run of tools/gale_fetch.py: Gale's Times pages the checklist
# wants, downloaded at a hand's pace into the Mac's Times inbox, where the
# cryptic-gale-inbox sync files them. Started by hand through track-job
# (--restart: every row it already got is skipped, so a restart resumes):
#
#     /app/tools/track-job.sh --log "$HOME/.cache/gale_fetch.log" --restart cryptic-crosswords \
#       --run "Gale downloads" "tail -1 $HOME/.cache/gale_fetch.log" -- bash tools/gale_fetch.sh
#
# Runs from its own worktree at origin/master (tools/nightly_worktree.sh),
# whose lease keeps it to one run at a time. It files nothing into git (the
# sync and the reads do), so there is nothing for tools/durable.sh to
# checkpoint: each download is whole in the inbox or not there at all, and
# logged in ~/.cache/gale_inbox/fetched.json as it lands. Exit 2: Gale
# refused (login page, captcha, not a PDF, repeated errors); the room was
# woken, and it must not be restarted until someone has looked.
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_GENERATED=none
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
export PYTHONUNBUFFERED=1
exec python3 tools/gale_fetch.py "$@"
