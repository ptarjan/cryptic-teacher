#!/bin/bash
# Read every archive.org edition, Gale page and Trove article the scan
# filers find due, to the end: never read, inputs changed, read without the
# VLM that now answers, or read before REREAD_BEFORE (each filer's
# due_reason), and the sources annotation asked to be read again; and,
# beside the reads from the start, fetch what is missing from archive.org
# and Trove, for the reads to take up.
#
# All of it is one queue of small units (tools/edition_queue.py): an
# edition's scan, an edition's or a Trove article's read and filing, an
# archive.org edition's or a Trove article's (or its clue zones') fetch,
# each with its own time limit and lock and its own ledger row, in pools of
# their own, the most urgent first (Gale pages saved by hand, then the
# never-read, then the re-reads) and planned again every minute, so new
# input waits minutes, not behind hours of re-reads, and a slow unit holds
# up only its own slot. A fetch never waits on a read nor a read on it.
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
# The fetches are units of the same queue (--fetch): an archive.org
# edition not in done.tsv at the current DETECTOR_VERSION, so bumping it
# makes the editions due by itself (fetch_archive_org_editions.fetch_unit);
# the clue zones of a Trove article the filer left pending, then a listed
# Trove article not yet cached (fetch_trove.fetch_unit, every unit pacing
# Trove to one request a second between them). What a fetch lands is
# scanned and read from the next plan, a minute later. The filers only read
# caches. A pass that ends having fetched something starts the next
# one at once (tools/corpus_queue.py chain), which reads what it fetched, so
# a backlog does not wait for the hourly tick.
# Resumable: each unit appends its own ledger row as it ends (filed.jsonl,
# filed-gale.jsonl in tools/downloads.py's ARCHIVE_ORG, the Trove filer's
# filed.jsonl, archive.org's done.tsv), and a rerun picks up where a killed
# one stopped.
# A ledger row marks its source read, so the puzzles it filed must reach git
# or they are never filed again: each filer runs under tools/durable.sh,
# which commits and pushes them every DURABLE_EVERY seconds while it reads,
# and on a stop (SIGTERM: corpus_queue.py stop) ends the filer and commits
# before exiting; what a SIGKILL or reboot leaves in the tree the next start
# salvages (CT_SALVAGE_PATHS). The queue runs in OCR_FULL_PASS_CHUNK-second
# slices, each under a hard `timeout`, the tree moved to origin/master
# between them.
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
# The last change to the scan filers that should alter past readings: a
# printed solution grid read on its own rules, its numbered and unsure
# cells matched to its own letters (trove_solution_ocr.read_framed), and a
# re-read's answers merged into the held filing.
REREAD_BEFORE="${OCR_FULL_PASS_REREAD_BEFORE:-2026-10-08T02:56:21+00:00}"

# The Listener pages Paul saves from Gale's Listener Historical Archive: each
# new file's clues read once (ledger by file hash), each puzzle whose grid
# and clues agree filed unsolved, its report's answers kept as a check
# (tools/file_gale_listener.py), the checklist published.
# Started at the pass's start and before every slice, beside the reads (its
# own ledger), so a page saved mid-pass is read within about a slice, not at
# the next pass, and a long batch of new pages holds up no slice; one runs at
# a time. A read cut off by LISTENER_SECONDS resumes at the next start.
LISTENER_SECONDS=1800
listener_pid=""
listener() {
  [ -n "$listener_pid" ] && kill -0 "$listener_pid" 2>/dev/null && return 0
  {
    timeout "$LISTENER_SECONDS" nice -n 19 python3 tools/gale_listener.py sync ||
      echo "gale_listener sync failed or ran out of time (rc=$?); the readings before stand, the next start resumes"
  } &
  listener_pid=$!
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


mkdir -p "$HOME/.cache/archive_org_crops/unfiled"
# The Times pages Paul downloads by hand from Gale's Times Digital Archive
# become Gale editions for the queue to read first, each due when its file
# lands (tools/gale_inbox.py asks the Mac and the desktop, never Gale). The
# cryptic-gale-inbox plugin does the same every 3 minutes; this run makes
# sure the pass starts from everything that has arrived.
python3 tools/gale_inbox.py sync ||
  echo "gale_inbox sync failed (rc=$?); the Gale pages staged before stand, the checklist is not refreshed"
listener
finish() {  # finish <rc>: let the Listener sync end, commit what it filed, exit
  wait
  publish "Listener pages read" || echo "commit failed for the Listener pages; the next start salvages them"
  echo "=== full pass done $(date '+%F %T') (rc=$1) ==="
  exit "$1"
}
# Every edition and Trove article, one unit each (tools/edition_queue.py):
# an edition's scan, an edition's or article's read and filing, or a fetch,
# each in a process of its own with its own time limit and lock, adding its
# own ledger row, the most urgent first: the Gale pages Paul saved, then
# the never-read and the re-reads annotation asked for, then those whose
# inputs moved, then the re-reads REREAD_BEFORE makes due. The queue is
# planned again every minute, so a source that lands mid-slice is read
# within minutes, and a read waits only on the scans its solution needs.
# Each slice starts nothing after CHUNK seconds, lets its units finish, and
# the tree moves to origin/master before the next.
TROVE_WORKERS="${OCR_FULL_PASS_TROVE_WORKERS:-6}"
slices "editions off archive.org and Gale, Trove articles, and their fetches" python3 tools/edition_queue.py run \
  --reread "$REREAD_BEFORE" --out "$HOME/.cache/archive_org_crops/unfiled" --trove-workers "$TROVE_WORKERS" \
  --fetch archive.org --fetch trove || finish 1
# Fill the canberra files' empty answers from solution grids fetched since
# they were filed (a puzzle's solution prints in a later article).
nice -n 19 python3 tools/trove_solution_ocr.py --fill ||
  echo "trove_solution_ocr --fill failed (rc=$?); the answers read before stand"
# Name the London Times puzzle each canberra file reprints (source.reprintOf).
# The Times reads match too, but before this pass's canberra files exist.
nice -n 19 python3 tools/file_archive_org_puzzles.py --match-canberra ||
  echo "file_archive_org_puzzles --match-canberra failed (rc=$?); canberra files keep the reprintOf they had"
publish "Canberra reprints named" || echo "commit failed for the Canberra reprints"

finish 0
