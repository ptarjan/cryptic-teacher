#!/bin/bash
# Read the Times pages Paul has just saved from Gale, minutes after each
# lands: tools/gale_inbox.py sync starts this (detached, so its minute tick
# stays short) whenever a Gale edition it laid out in the last FRESH seconds
# has no reading of its current files (gale_inbox.fresh_unread). The
# editions laid out earlier are the full pass's (tools/ocr_full_pass.sh, the
# Gale slices first).
#
# One run at a time (tools/nightly_worktree.sh's lease: a second start while
# one reads exits at once); each run reads the fresh editions newest first,
# none started after SECONDS, under the Gale pages' own ledger
# (downloads.GALE_LEDGER), so it never waits on the full pass's hold on
# filed.jsonl. What it files is committed and pushed as it goes
# (tools/durable.sh).
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
GRACE=600
mkdir -p "$HOME/.cache/archive_org_crops/unfiled"
echo "=== Gale reads from $(date '+%F %T'), editions laid out in the last ${FRESH}s ==="
durable_run "Gale Times pages read" \
  timeout "$((SECONDS_CAP + GRACE))" nice -n 19 python3 tools/file_archive_org_puzzles.py --paper gale \
  --newer-than "$FRESH" --seconds "$SECONDS_CAP" --workers 2 --out "$HOME/.cache/archive_org_crops/unfiled"
rc=$?
durable_checkpoint "Gale Times pages read" || echo "commit failed for the Gale reads; the next start salvages them"
echo "=== Gale reads done $(date '+%F %T') (rc=$rc) ==="
exit "$rc"
