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
not a grid, no crossword found, archive.org's date wrong, a collection the
filer does not read yet, and no scan at all. Classes this pipeline can still
recover are listed first, largest first. An edition that is already listed in a
queued job counts as queued.

`--json FILE` writes the same data as JSON. `--save` keeps it in
`~/.cache/archive_coverage/latest.json`, and the next run prints each year's
change against it.

## 2. The queue: `tools/data/corpus_queue.json` and `tools/corpus_queue.py`

The queue file lists the corpus OCR jobs in the order they run. Each job is an
edition list (refile lists, re-read lists) or the open annotation re-read
requests (`"requested": true`). Only one corpus job runs at a time.
`python3 tools/corpus_queue.py tick` treats another job as running in two cases:

- the pid in `~/.cache/corpus_queue/running.json` is alive, with the same
  kernel start time (a job started by hand is recorded with `adopt NAME PID`);
- a scan filer holds a ledger lock (`tools/scan_queue.py` `lock()`).

If neither is true, `tick` starts the first job that is not done.

Each job runs through `tools/corpus_job.sh`, in its own worktree:

- The list is split into chunks of 20 editions. Each chunk is read with a
  `timeout`, committed by pathspec and pushed.
- Editions the ledger shows as read are struck from the chunk.
- A chunk that still has editions after three tries moves to `failed/`.
- When the last chunk is done, the job starts the next one in the queue.

Every job writes its own log, `~/.cache/corpus_queue/<name>.log`. The hourly
tick does three more things:

- It resumes a job that a restart killed.
- It wakes the room once when a job's log stops growing for an hour.
- It holds a job that dies twice without finishing a chunk, and says so.

A job with a `gate` (a check a person must make first) waits until
`corpus_queue.py pass-gate NAME "evidence"` is run. `status` lists every job.

To add work, append a job to the queue file and commit it.

## 3. The nightly: `household-plugins/cryptic-archive-coverage`

Two plugins run `tools/corpus_queue.sh`, which runs from a worktree at
origin/master:

- **`cryptic-corpus-queue`** runs `tick` every hour at :35.
- **`cryptic-archive-coverage`** runs `nightly` at 05:50. This runs the
  tracker with `--save`. If no corpus job is running and recoverable editions
  are left that no job covers, or the queue is stopped at a gate, it wakes
  #cryptic-crosswords. The message gives the top classes and the per-year
  filed/printed counts with their deltas, so the next fix gets started.
