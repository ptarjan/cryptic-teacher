# Archive coverage: every archive year as full as a modern one

Paul, 2026-10-05: "make sure you structure your ocr project so you can't forget
about it, i want the archive numbers to be like the same as the modern day
ones".

A modern Times year files about 300 puzzles (Mon-Sat). Most archive years file
under 100. The goal is to bring every archive year close to the modern count
using archive.org's newspaper scans (and Trove for the Canberra Times), read by
CPU OCR with no Claude inference. Three pieces keep that work from being
forgotten.

## 1. The tracker: `tools/archive_coverage.py`

For each scanned series (`times`, `cryptic`, `ftcryptic`, `telegraph`) and
each year, it counts:

- **printed**: the editions the paper printed. This comes from the `PRINTED`
  table: the weekdays, the first day, and the gaps (the Times lock-out of
  1978-79). Christmas Day is never counted.
- **scanned**: how many of those archive.org holds a scan of.
- **filed**: how many of those dates have a puzzle file.

Every unfiled edition gets exactly one class, read off the filer's ledger
(`~/.cache/archive_org_editions/filed.jsonl`). The classes include not fetched,
not read, blank clues held back, no grid, clues don't fit, no reading parses,
not a grid, no crossword found, archive.org's date wrong, and no scan at
all. The 1930 Times (`pub_times`, one item per issue) is listed with the
Times, as `<item>/<item>`. Its clues print no counts, so a clue whose
number was lost would run into the one before under the grid's count; the
filer drops any clue next to a break in the grid's light order instead, and
such an issue files only when another reading has those clues whole.
Classes this pipeline can still
recover are listed first, largest first.

Two classes need code, not time (each class's fix text in `CLASSES` names
the next step):

- **no crossword found** (Times): the filer reads garbled titles ("Tfee Th:es
  Crossword PuzzleNo 16,587") and the fetcher also fetches the page densest
  with clue counts when no title is in the text (`DENSE_ENUMS`,
  `DETECTOR_VERSION` 5). What is left needs a grid search by image over
  every leaf.
- **no grid** (Times): of 163, 155 were a scanned grid that reads true
  under clue OCR too poor (1970s-80s scans) to lay 80% of its lights, with
  no grid rebuilt from those clues. The scan's grid now stands there and
  the unlaid lights go blank, so they move to **blank clues**. The 8 left
  are crops `trove_grid.read_grid` cannot measure (stippled or faint).
- **FT 1981** (285 editions) is held only as image PDFs with no OCR. The
  fetcher lists them as editions and reads each PDF by image
  (`fetch_pdf_edition`): the page whose grid-shaped ink `trove_grid` reads
  is saved greyed at the scans' width, and the filer reads the "F.T.
  CROSSWORD PUZZLE No. 4,534" title over it by OCR. The crossword is on the
  TV page. They count as not fetched until the hourly pass reaches them.

Blank clues are mostly the VLM being down, not faint print. On 2026-10-06,
4,283 of the 4,425 Times editions had been read while llama-swap on the
desktop was dead, and 88% of those verdicts held a blank clue, against 8% of
the editions read with the VLM. Re-reading a 20-edition sample with the VLM
cut 82 blanks to 18, and 14 of the 20 came out complete. The print was
legible in every case checked. So an edition read without the VLM is due
again whenever the VLM answers (`due_reason`), and the bucket drains as the
full pass reads it, at a median of 48 s an edition with the VLM (21-290 s; llama-server serves one request at a time, so 20 workers do not go faster).

`--json FILE` writes the same data as JSON. `--save` keeps it in
`~/.cache/archive_coverage/latest.json`, and the next run prints each year's
change against it.

## 2. The standing job: `tools/ocr_full_pass.sh`, kept running by `tools/corpus_queue.py`

There is one corpus OCR job, and it takes no edition list. `ocr_full_pass.sh`
runs each scan filer over its whole cache. The filers decide what is due
(`due_reason` in `tools/file_archive_org_puzzles.py` and
`tools/file_trove_puzzles.py`):

- never read;
- its inputs changed (new files, or the solutions it can see);
- read without the VLM, and the VLM answers now;
- read before `REREAD_BEFORE` in `ocr_full_pass.sh`.

The pass then reads the sources annotation asked to have read again
(`tools/scan_queue.py requested`), and ends. Running it again is always safe:
a pass with nothing due ends in minutes.

So nothing is ever queued by hand:

- **A reader change** that should change past readings sets `REREAD_BEFORE`
  to the time it landed. The next pass reads again everything read before it.
- **A VLM outage** leaves the sources read during it without a `vlm` stamp.
  That includes outages that start mid-run: a failed ask marks the VLM down
  for the rest of that worker's run. The first pass after the VLM answers
  again reads those sources again.

An edition-list job cannot be written: `tools/test_corpus_queue.sh` fails if a
queue file or a job argument appears.

`python3 tools/corpus_queue.py tick` starts the pass whenever no corpus job is
running. Another job counts as running in two cases:

- the pid in `~/.cache/corpus_queue/running.json` is alive, with the same
  kernel start time (a pass started by hand is recorded with `adopt PID`);
- a scan filer holds a ledger lock (`tools/scan_queue.py` `lock()`), such as
  a filer run by hand.

The pass runs in its own worktree. Each filer runs in hour-long slices, each
slice is under a hard `timeout`, and after every slice the puzzles it filed
are committed and pushed. Each filer's ledger is saved after every source, so
a killed pass resumes where it stopped. It logs to
`~/.cache/corpus_queue/full_pass.log`.

The pass fetches from archive.org and Trove at the same time, each for at most
an hour, and starts filing once both have ended. A pass that finishes having
fetched something starts the next one at once (`corpus_queue.py chain`, a
`tick --chained`), so a fetch backlog runs back to back. The first pass that
fetches nothing leaves the next start to the hourly tick.

The hourly tick also checks that the pass is making progress:

- It wakes the room once when the log stops growing for an hour.
- It kills whatever is left of a dead pass's session before it starts
  anything.
- A launch that ends unfinished without reading a source (no ledger moved) is
  a dead launch. Two in a row hold the pass, and the room is told.

To stop the pass, run `corpus_queue.py stop`, which kills its whole session
and holds it. To let it start again, run `corpus_queue.py release`. `status`
shows whether it is running, held or idle, and how the last pass ended.

## 3. The nightly: `household-plugins/cryptic-archive-coverage`

- **`cryptic-corpus-queue`** runs `tools/corpus_queue.sh tick` every hour at
  :35. It wakes the room on a stall and when it holds the pass.
- **`cryptic-archive-coverage`** runs `tools/coverage.sh daily` at 05:50: the
  coverage ledger (`tools/coverage.py`, see the README's "Coverage ledger").
  The ledger takes this tracker's classes for the scan series and adds every
  other source (blogs, FT PDFs, Gale, Trove, books). It queues the top
  recoverable buckets and any regression for #cryptic-crosswords, and stays
  silent when there are none.
