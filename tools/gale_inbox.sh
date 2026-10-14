#!/bin/bash
# The scheduled entry point for tools/gale_inbox.py (the cryptic-gale-inbox
# plugin): runs it from a worktree at origin/master (tools/nightly_worktree.sh).
# A tick publishes the Times progress page, ticks the Listener's inbox and
# starts the full pass for editions tools/gale_fetch.py laid out; it reads no
# generated file, so nothing is rebuilt. Arguments pass through.
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_GENERATED=none
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
# A Listener page's read runs on the desktop (tools/ocr_remote.py) while
# it is idle; OCR_REMOTE= keeps it here.
export OCR_REMOTE="${OCR_REMOTE-$(python3 "$(dirname "$0")/desktop_hosts.py" remote)}"
exec python3 tools/gale_inbox.py "$@"
