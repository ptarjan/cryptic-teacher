#!/bin/bash
# Read the Times pages Paul has just saved from Gale, minutes after each
# lands: tools/gale_inbox.py sync starts this (detached, so its minute tick
# stays short) whenever a Gale edition it laid out in the last FRESH seconds
# has no reading of its current files (gale_inbox.fresh_unread). The
# editions laid out earlier are the full pass's (tools/ocr_full_pass.sh,
# whose queue takes Gale pages first and plans again every minute).
#
# One run at a time (tools/nightly_worktree.sh's lease: a second start while
# one reads exits at once); each run is tools/edition_queue.py over the
# fresh Gale editions alone, newest first, none started after SECONDS_CAP:
# one unit an edition, each locking its edition and adding its own row to
# the Gale pages' ledger (downloads.GALE_LEDGER), so it runs beside the full
# pass's queue and neither reads an edition the other is reading. What it
# files is committed and pushed as it goes (tools/durable.sh).
#
#     bash tools/gale_read.sh        # log: ~/.cache/gale_read.log when gale_inbox starts it
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_SALVAGE_PATHS="puzzles"
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
# All of puzzles/: filing a newspaper puzzle can delete the held book file
# that reprints it (fetch_puzzle.supersede_book).
# shellcheck disable=SC2034  # read by the sourced durable.sh
DURABLE_PATHS=(puzzles)
. tools/durable.sh

export PYTHONUNBUFFERED=1
export OCR_REMOTE="${OCR_REMOTE-micro@100.68.145.15,micro@192.168.1.198}"
export OCR_THREADS="${OCR_THREADS:-1}"
FRESH="$(python3 -c 'import sys; sys.path.insert(0, "tools"); import gale_inbox; print(gale_inbox.FRESH)')"
SECONDS_CAP=900
# A unit runs at most edition_queue.READ_SECONDS past the cap.
GRACE=1300
mkdir -p "$HOME/.cache/archive_org_crops/unfiled"
echo "=== Gale reads from $(date '+%F %T'), editions laid out in the last ${FRESH}s ==="
durable_run "Gale Times pages read" \
  timeout "$((SECONDS_CAP + GRACE))" nice -n 19 python3 tools/edition_queue.py run --paper gale \
  --newer-than "$FRESH" --seconds "$SECONDS_CAP" --workers 2 --out "$HOME/.cache/archive_org_crops/unfiled"
rc=$?
durable_checkpoint "Gale Times pages read" || echo "commit failed for the Gale reads; the next start salvages them"
echo "=== Gale reads done $(date '+%F %T') (rc=$rc) ==="
exit "$rc"
