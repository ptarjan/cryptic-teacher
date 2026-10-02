#!/bin/bash
# Read every Trove article and archive.org edition the scan filers have not
# read yet, to the end, then stop.
#
#     setsid nohup bash tools/ocr_full_pass.sh >>~/.cache/ocr_full_pass.log 2>&1 </dev/null &
#
# The nightly reads a wall-clock slice of each (daily_update.sh, steps 1c2
# and 1c2b); this reads the rest. Resumable: each filer's ledger
# (~/.cache/trove/filed.jsonl, ~/.cache/archive_org_editions/filed.jsonl)
# is saved after every source, the never-read go first, and a rerun picks up
# where a killed one stopped. Each filer runs in OCR_FULL_PASS_CHUNK-second
# slices; after each, the puzzles it filed are committed and pushed, so a
# kill loses at most one slice's files (their readings stay in
# archiveorg-source). While this holds a ledger, the nightly's step for it
# reads nothing; this waits for the nightly's hold in turn.
#
# Runs in a worktree of its own (tools/nightly_worktree.sh), at origin/master.
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1

CHUNK="${OCR_FULL_PASS_CHUNK:-3600}"
WORKERS="${OCR_FULL_PASS_WORKERS:-2}"
SERIES=(puzzles/canberra puzzles/telegraph puzzles/cryptic puzzles/ftcryptic puzzles/times)

attempt_push() {
  git fetch -q origin master && { git rebase -q origin/master || { git rebase --abort; false; }; } &&
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
  while :; do
    echo "=== $what: slice from $(date '+%F %T') ==="
    out=$(nice -n 10 "$@" --seconds "$CHUNK" --workers "$WORKERS" --wait 2>&1)
    rc=$?
    echo "$out"
    publish "$what" || echo "commit failed for $what"
    [ "$rc" -eq 0 ] || { echo "$what failed (rc=$rc); stopping"; return 1; }
    grep -q "left for the next run" <<<"$out" || return 0
  done
}

slices "Canberra Times off Trove" python3 tools/file_trove_puzzles.py || exit 1
mkdir -p "$HOME/.cache/archive_org_crops/unfiled"
for paper in telegraph guardian ft times; do
  slices "$paper off archive.org" python3 tools/file_archive_org_puzzles.py --paper "$paper" \
    --out "$HOME/.cache/archive_org_crops/unfiled" || exit 1
done
echo "=== full pass done $(date '+%F %T') ==="
