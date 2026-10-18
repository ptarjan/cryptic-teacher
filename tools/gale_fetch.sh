#!/bin/bash
# The long run of tools/gale_fetch.py: every Times page the wanted list
# (gale_inbox.wanted) still lacks, downloaded at a hand's pace and laid out
# at once as its date's edition, which the full pass's queue files first
# (tools/edition_queue.py fresh). Started by
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
# Reloading it onto new code: kill -HUP the python3 child (never this wrapper).
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_GENERATED=none
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
export PYTHONUNBUFFERED=1
# Each page's layout (PDF decode, grid search, resize, JPEG) runs on the
# desktop (gale_inbox.layout_there via tools/ocr_remote.py), here when it is
# not answering: it was ~all this run's CPU on the host.
export OCR_REMOTE="${OCR_REMOTE-$(python3 tools/desktop_hosts.py remote)}"
# Hot reload (tools/hot_reload.py): `kill -HUP` the python3 child, or origin/master's
# tools/ code moving, ends it between two downloads with rc 75. The tree moves
# to origin/master and the script starts over on it (the same pid, the lease on
# fd 9 kept); the run resumes off its log.
python3 tools/gale_fetch.py "$@"
rc=$?
[ "$rc" -eq 75 ] || exit "$rc"
echo "=== reload asked; moving the tree to origin/master ==="
git fetch -q origin master && git reset -q --hard origin/master ||
  { echo "the tree did not move; starting again in 60s"; sleep 60; }
exec "$BASH" -c '. "$0"' "$PWD/tools/gale_fetch.sh" "$@"
