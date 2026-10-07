#!/bin/bash
# Read every archive.org edition and Trove article the scan filers find due,
# to the end: never read, inputs changed, read without the VLM that now
# answers, or read before REREAD_BEFORE (each filer's due_reason), then the
# sources annotation asked to be read again; then fetch what the scan
# fetchers find missing, archive.org and Trove at once, each for up to
# FETCH_SECONDS, for the next pass to read.
#
# The desktop VLM reads only in the filers' reads, never in a fetch or a
# scan, so the work that keeps it busy goes first: every paper's due
# editions whose scans stand (--no-scan) before any paper's scans, and the
# fetch, which only CPU and network do, last.
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
# The scans are cached by the fetchers this pass runs last, archive.org's
# alongside Trove's, each host for at most FETCH_SECONDS and resumable, so a run with nothing missing costs seconds and
# a long backlog is fetched a slice per pass: tools/fetch_archive_org_editions.py
# (every group; an edition not in done.tsv at the current DETECTOR_VERSION is
# due, so bumping it makes the editions due by itself), tools/fetch_trove.py
# fetch (every listed article not yet cached) and fetch_trove.py zones (the
# clue columns of the articles the Trove filer left pending; a pending
# article is read again once its zones land, so the next pass files it).
# A fetcher already running (a hand run) is skipped, not doubled. The filers
# only read caches. A pass that ends having fetched something starts the next
# one at once (tools/corpus_queue.py chain), which reads what it fetched, so
# a backlog does not wait for the hourly tick.
# Resumable: each filer's ledger (~/.cache/trove/filed.jsonl,
# ~/.cache/archive_org_editions/filed.jsonl) is saved after every source,
# the never-read go first, and a rerun picks up where a killed one stopped.
# A ledger row marks its source read, so the puzzles it filed must reach git
# or they are never filed again: each filer runs under tools/durable.sh,
# which commits and pushes them every DURABLE_EVERY seconds while it reads,
# and on a stop (SIGTERM: corpus_queue.py stop) ends the filer and commits
# before exiting; what a SIGKILL or reboot leaves in the tree the next start
# salvages (CT_SALVAGE_PATHS). Each filer runs in OCR_FULL_PASS_CHUNK-second
# slices, each under a hard `timeout`. --wait queues behind any other filer
# holding a ledger.
#
# Runs in a worktree of its own (tools/nightly_worktree.sh), at origin/master.
# All of puzzles/, not the series it files: filing a newspaper puzzle deletes
# the held book file that reprints it (fetch_puzzle.supersede_book), and that
# deletion is part of the write.
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_SALVAGE_PATHS="puzzles"
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
# shellcheck disable=SC2034  # read by the sourced durable.sh
DURABLE_PATHS=(puzzles)
. tools/durable.sh

# Every line reaches the log as it is printed, never at a slice's end.
export PYTHONUNBUFFERED=1
CHUNK="${OCR_FULL_PASS_CHUNK:-3600}"
# A slice starts no source after CHUNK seconds; one still reading this long
# after is stuck, and the slice ends there (the pass resumes next tick).
GRACE=1800
# Each archive.org edition is read on the desktop, the vote and all
# (tools/ocr_remote.py; OCR_REMOTE= to read here), and so are the clue OCR,
# an image PDF's page search in the fetch and the Trove filer's grid search,
# so most of each worker's time is a wait on it: this host keeps the scans'
# headings, the Trove filer's parsing and the filing, at nice 19, one OCR
# thread a worker. Whatever is read here (the desktop off or gaming) holds
# one of ocr_remote's LOCAL_SLOTS (cores - 1) host-wide, so the 20 workers
# never put 20 reads on this 4-core host.
export OCR_REMOTE="${OCR_REMOTE-micro@100.68.145.15,micro@192.168.1.198}"
export OCR_THREADS="${OCR_THREADS:-1}"
WORKERS="${OCR_FULL_PASS_WORKERS:-20}"
# The last change to the scan filers that should alter past readings.
REREAD_BEFORE="${OCR_FULL_PASS_REREAD_BEFORE:-2026-10-06T13:45:00+00:00}"

# The Listener pages Paul saves from Gale's Listener Historical Archive: each
# new file's clues read once (ledger by file hash), each puzzle whose grid
# and clues agree filed unsolved, its report's answers kept as a check
# (tools/file_gale_listener.py), the checklist published.
# Run at the pass's start and before every slice, so a page saved mid-pass is
# read within about a slice, not at the next pass; with nothing new it costs
# seconds. A read cut off by LISTENER_SECONDS resumes at the next slice.
LISTENER_SECONDS=1800
listener() {
  timeout "$LISTENER_SECONDS" nice -n 19 python3 tools/gale_listener.py sync ||
    echo "gale_listener sync failed or ran out of time (rc=$?); the readings before stand, the next slice resumes"
}

publish() {  # publish <what>: commit and push the puzzles filed so far
  durable_checkpoint "Full OCR pass: $1" || return 1
  durable_resync
}

slices() {  # slices <what> <filer command...>: run the filer until nothing is left
  local what="$1" out rc
  shift
  out=$(mktemp) || return 1
  while :; do
    listener
    echo "=== $what: slice from $(date '+%F %T') ==="
    # Streamed as it goes (a line per source read), so the log shows what it
    # is doing now; the copy in $out is read for the slice's tally.
    DURABLE_TEE="$out" durable_run "Full OCR pass: $what" \
      timeout "$((CHUNK + GRACE))" nice -n 19 "$@" --seconds "$CHUNK" --workers "$WORKERS" --wait
    rc=$?
    durable_resync
    [ "$rc" -eq 0 ] || { echo "$what failed (rc=$rc); stopping"; rm -f "$out"; return 1; }
    grep -q "left for the next run" "$out" || { rm -f "$out"; return 0; }
  done
}

FETCH_SECONDS="${OCR_FULL_PASS_FETCH_SECONDS:-3600}"
fetch() {  # fetch <what> <process regex> <seconds> <fetcher command...>: one bounded fetch slice
  local what="$1" running="$2" seconds="$3" rc
  shift 3
  if pgrep -f "$running" >/dev/null; then
    echo "=== $what: skipped, a fetch is already running: $(pgrep -af "$running" | head -1 | cut -c1-200)"
    return 0
  fi
  if [ "$seconds" -le 0 ]; then
    echo "=== $what: skipped, no time left this pass"
    return 0
  fi
  echo "=== $what: from $(date '+%F %T'), at most ${seconds}s ==="
  timeout "$((seconds + GRACE))" nice -n 19 "$@" --seconds "$seconds" 2>&1
  rc=$?
  [ "$rc" -eq 0 ] || echo "$what failed (rc=$rc); the next pass reads what is cached and fetches again"
}

mkdir -p "$HOME/.cache/archive_org_crops/unfiled"
# The Times pages Paul downloads by hand from Gale's Times Digital Archive
# become Times editions for the Times slices to read, each due when its file
# lands (tools/gale_inbox.py asks the Mac and the desktop, never Gale). The
# cryptic-gale-inbox plugin does the same every 3 minutes; this run makes
# sure the pass starts from everything that has arrived.
python3 tools/gale_inbox.py sync ||
  echo "gale_inbox sync failed (rc=$?); the Gale pages staged before stand, the checklist is not refreshed"
listener
# The reads that wait on no scan first, the VLM's work: every paper's
# editions whose scans stand, then the Trove articles (that filer scans
# nothing); then each paper's scans and the reads they make due.
for paper in times telegraph guardian ft; do
  slices "$paper off archive.org, scanned" python3 tools/file_archive_org_puzzles.py --paper "$paper" --no-scan \
    --reread "$REREAD_BEFORE" --out "$HOME/.cache/archive_org_crops/unfiled" || exit 1
done
slices "Canberra Times off Trove" python3 tools/file_trove_puzzles.py --reread "$REREAD_BEFORE" || exit 1
for paper in telegraph guardian ft times; do
  slices "$paper off archive.org" python3 tools/file_archive_org_puzzles.py --paper "$paper" \
    --reread "$REREAD_BEFORE" --out "$HOME/.cache/archive_org_crops/unfiled" || exit 1
done
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

# archive.org and Trove are different hosts, so their fetches run at once,
# each within FETCH_SECONDS (Trove's article fetch takes at most half, its
# clue zones the rest); the next pass reads what they cached.
# archive.org throttles each connection to ~100 KB/s, not the client (16 at
# once measured ~100 KB/s each), so --jobs scales the fetch; a 429 lowers it.
fetch "archive.org fetch" '^python3 (-u )?\S*fetch_archive_org_editions\.py' "$FETCH_SECONDS" \
  python3 tools/fetch_archive_org_editions.py --jobs 12 &
{
  trove_start=$SECONDS
  fetch "Trove fetch" '^python3 (-u )?\S*fetch_trove\.py' "$((FETCH_SECONDS / 2))" python3 tools/fetch_trove.py fetch
  fetch "Trove clue zones" '^python3 (-u )?\S*fetch_trove\.py' "$((FETCH_SECONDS - (SECONDS - trove_start)))" \
    python3 tools/fetch_trove.py zones
} &
wait
echo "=== full pass done $(date '+%F %T') ==="
