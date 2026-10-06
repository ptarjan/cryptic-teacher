#!/bin/bash
# Read every archive.org edition and Trove article the scan filers find due,
# to the end, then stop: never read, inputs changed, read without the VLM
# that now answers, or read before REREAD_BEFORE (each filer's due_reason),
# then the sources annotation asked to be read again.
#
#     (started by: python3 tools/corpus_queue.py tick, hourly, whenever no
#     corpus job runs; `corpus_queue.py adopt PID` claims one started by hand)
#
# This is the one standing corpus job. It takes no edition list: the filers
# decide what is due, so running it again is always safe and a pass with
# nothing due ends in minutes. A source read while the VLM was down is read
# again by the first pass after it answers.
#
# A code change makes nothing due by itself: whoever makes one that should
# change past readings sets REREAD_BEFORE to the time it landed, and the next
# pass reads again every source last read before then (each filer's
# --reread). Rows read after it are done, so slices and reruns resume, not
# restart. A Canberra Times reprint downloaded or read after its London
# edition makes that edition due by itself: the reprint's cached texts are
# among the edition's inputs (file_archive_org_puzzles.inputs_of). So does a
# puzzle filed off an edition holding a clue ocr_clues.stray flags (a
# doubled word, a stray letter): the read mends or blanks it (mend_held),
# and the same for a Trove article (file_trove_puzzles.inputs_of).
#
# The scans are cached by hand-run fetchers (tools/fetch_trove.py fetch,
# then fetch_trove.py zones for the clue columns of articles left pending;
# tools/fetch_archive_org_editions.py). This pass only reads caches and never
# downloads: an article whose clue columns are not cached stays pending ("no
# reading of the page's clues") until fetch_trove.py zones caches them.
# Resumable: each filer's ledger (~/.cache/trove/filed.jsonl,
# ~/.cache/archive_org_editions/filed.jsonl) is saved after every source,
# the never-read go first, and a rerun picks up where a killed one stopped.
# Each filer runs in OCR_FULL_PASS_CHUNK-second slices, each under a hard
# `timeout`; after each, the puzzles it filed are committed and pushed, so a
# kill loses at most one slice's files (their readings stay in
# archiveorg-source). --wait queues behind any other filer holding a ledger.
#
# Runs in a worktree of its own (tools/nightly_worktree.sh), at origin/master.
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1

# Every line reaches the log as it is printed, never at a slice's end.
export PYTHONUNBUFFERED=1
CHUNK="${OCR_FULL_PASS_CHUNK:-3600}"
# A slice starts no source after CHUNK seconds; one still reading this long
# after is stuck, and the slice ends there (the pass resumes next tick).
GRACE=1800
# Each archive.org edition is read on the desktop, the vote and all
# (tools/ocr_remote.py; OCR_REMOTE= to read here), so most of each worker's
# time is a wait on it: this host keeps the scans, the Trove filer's parsing
# and the filing, at nice 19, one OCR thread a worker when the desktop is off.
export OCR_REMOTE="${OCR_REMOTE-micro@100.68.145.15,micro@192.168.1.198}"
export OCR_THREADS="${OCR_THREADS:-1}"
WORKERS="${OCR_FULL_PASS_WORKERS:-20}"
# Scan filer: the clue vote files counts, capitals, hyphens and words as
# the readings print them and settles misread words on the lexicon (5b97ed5,
# 0188ade), after the skewed-page clue line fix (fc9ff99) and the grid
# lattice fit (e9b8d39)
REREAD_BEFORE="${OCR_FULL_PASS_REREAD_BEFORE:-2026-10-05T23:13:40+00:00}"
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
    timeout "$((CHUNK + GRACE))" nice -n 19 "$@" --seconds "$CHUNK" --workers "$WORKERS" --wait 2>&1 | tee "$out"
    rc=${PIPESTATUS[0]}
    publish "$what" || echo "commit failed for $what"
    [ "$rc" -eq 0 ] || { echo "$what failed (rc=$rc); stopping"; rm -f "$out"; return 1; }
    grep -q "left for the next run" "$out" || { rm -f "$out"; return 0; }
  done
}

mkdir -p "$HOME/.cache/archive_org_crops/unfiled"
# The Times pages Paul saves by hand from Gale's Times Digital Archive into
# his Mac's inbox become Times editions for the Times slices to read, each
# due when its file lands (tools/gale_inbox.py asks the Mac, never Gale);
# the checklist of editions still wanted is written back beside them.
python3 tools/gale_inbox.py sync ||
  echo "gale_inbox sync failed (rc=$?); the Gale pages staged before stand, the checklist is not refreshed"
for paper in telegraph guardian ft times; do
  slices "$paper off archive.org" python3 tools/file_archive_org_puzzles.py --paper "$paper" \
    --reread "$REREAD_BEFORE" --out "$HOME/.cache/archive_org_crops/unfiled" || exit 1
done
slices "Canberra Times off Trove" python3 tools/file_trove_puzzles.py --reread "$REREAD_BEFORE" || exit 1
# The sources an annotation run asked to be read again, having met a misread
# clue on a puzzle filed from them (tools/scan_queue.py request_reread): each
# read closes its request, and the burn takes the puzzle again after it.
for paper in telegraph guardian ft times; do
  asked=()
  while read -r src; do asked+=(--edition "$src"); done < <(python3 tools/scan_queue.py requested archive "$paper")
  [ "${#asked[@]}" -gt 0 ] || continue
  slices "$paper re-reads annotation asked for" python3 tools/file_archive_org_puzzles.py --paper "$paper" \
    "${asked[@]}" --out "$HOME/.cache/archive_org_crops/unfiled" || exit 1
done
asked=()
while read -r src; do asked+=(--article "$src"); done < <(python3 tools/scan_queue.py requested trove)
if [ "${#asked[@]}" -gt 0 ]; then
  slices "Trove re-reads annotation asked for" python3 tools/file_trove_puzzles.py "${asked[@]}" || exit 1
fi
# Name the London Times puzzle each canberra file reprints (source.reprintOf).
# The Times slices match too, but before this pass's canberra files exist.
nice -n 19 python3 tools/file_archive_org_puzzles.py --match-canberra ||
  echo "file_archive_org_puzzles --match-canberra failed (rc=$?); canberra files keep the reprintOf they had"
publish "Canberra reprints named" || echo "commit failed for the Canberra reprints"
echo "=== full pass done $(date '+%F %T') ==="
