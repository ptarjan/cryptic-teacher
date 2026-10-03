#!/bin/bash
# Read every archive.org edition and Trove article the scan filers have not
# read yet, and those REREAD_BEFORE asks for again, to the end, then stop.
#
#     setsid nohup bash tools/ocr_full_pass.sh >>~/.cache/ocr_full_pass.log 2>&1 </dev/null &
#
# The nightly reads none of them: the scans are cached by hand-run fetchers
# (tools/fetch_trove.py fetch, then fetch_trove.py zones for the clue columns
# of articles left pending; tools/fetch_archive_org_editions.py), so run this
# after one, or after changing a reader, to file what they now read. This
# pass only reads caches and never downloads: an article whose clue columns
# are not cached stays pending ("no reading of the page's clues") until
# fetch_trove.py zones caches them. Resumable: each filer's ledger
# (~/.cache/trove/filed.jsonl, ~/.cache/archive_org_editions/filed.jsonl)
# is saved after every source, the never-read go first, and a rerun picks up
# where a killed one stopped. Each filer runs in OCR_FULL_PASS_CHUNK-second
# slices; after each, the puzzles it filed are committed and pushed, so a
# kill loses at most one slice's files (their readings stay in
# archiveorg-source). --wait queues behind any other filer holding a ledger.
#
# A code change makes nothing due by itself: whoever makes one that should
# change past readings sets REREAD_BEFORE to the time it landed, and this
# reads again every source last read before then (each filer's --reread).
# Rows read after it are done, so slices and reruns resume, not restart.
#
# Runs in a worktree of its own (tools/nightly_worktree.sh), at origin/master.
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1

# Every line reaches the log as it is printed, never at a slice's end.
export PYTHONUNBUFFERED=1
CHUNK="${OCR_FULL_PASS_CHUNK:-3600}"
WORKERS="${OCR_FULL_PASS_WORKERS:-2}"
# Trove filer: clue numbers put in order, glued clues split, OCR slips
REREAD_BEFORE="${OCR_FULL_PASS_REREAD_BEFORE:-2026-10-03T06:00:00+00:00}"
SERIES=(puzzles/canberra puzzles/telegraph puzzles/cryptic puzzles/ftcryptic puzzles/times)

attempt_push() {
  # The filer's reindex restamps index.html (CI restamps it anyway), and a
  # dirty tree refuses the rebase.
  git checkout -q -- index.html && git fetch -q origin master && { git rebase -q origin/master || { git rebase --abort; false; }; } &&
    git push -q origin HEAD:master
}

publish() {  # publish <what>: commit and push the puzzles filed so far
  git add -- "${SERIES[@]}" || return 1
  git diff --cached --quiet && return 0
  git commit -q -m "$(printf 'Full OCR pass: %s\n\n%s' "$1" "$(python3 tools/provenance.py trailer)")" || return 1
  push_race_retry attempt_push || echo "push failed; the commit stays here and goes with the next slice"
}

slices() {  # slices <what> <filer command...>: run the filer until nothing is left
  local what="$1" out rc
  shift
  out=$(mktemp) || return 1
  while :; do
    echo "=== $what: slice from $(date '+%F %T') ==="
    # Streamed as it goes (a line per source read), so the log shows what it
    # is doing now; the copy in $out is read for the slice's tally.
    nice -n 10 "$@" --seconds "$CHUNK" --workers "$WORKERS" --wait 2>&1 | tee "$out"
    rc=${PIPESTATUS[0]}
    publish "$what" || echo "commit failed for $what"
    [ "$rc" -eq 0 ] || { echo "$what failed (rc=$rc); stopping"; rm -f "$out"; return 1; }
    grep -q "left for the next run" "$out" || { rm -f "$out"; return 0; }
  done
}

mkdir -p "$HOME/.cache/archive_org_crops/unfiled"
for paper in telegraph guardian ft times; do
  slices "$paper off archive.org" python3 tools/file_archive_org_puzzles.py --paper "$paper" \
    --reread "$REREAD_BEFORE" --out "$HOME/.cache/archive_org_crops/unfiled" || exit 1
done
slices "Canberra Times off Trove" python3 tools/file_trove_puzzles.py --reread "$REREAD_BEFORE" || exit 1
echo "=== full pass done $(date '+%F %T') ==="
