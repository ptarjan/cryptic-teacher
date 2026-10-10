#!/bin/bash
# The scheduled entry point for tools/gale_inbox.py (the cryptic-gale-inbox
# plugin): runs it from a worktree at origin/master (tools/nightly_worktree.sh).
# A tick sweeps the Gale files Paul downloaded into their inboxes and, when
# anything moved, stages them and re-renders the checklist; it reads no
# generated file, so nothing is rebuilt. Arguments pass through.
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_GENERATED=none
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
# A file's page work (match) runs on the desktop (tools/ocr_remote.py) while
# it is idle; OCR_REMOTE= keeps it here.
export OCR_REMOTE="${OCR_REMOTE-micro@192.168.1.198,micro@100.68.145.15}"
exec python3 tools/gale_inbox.py "$@"
