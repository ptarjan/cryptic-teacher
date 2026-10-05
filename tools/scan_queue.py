"""The read queue the scan filers share (tools/file_archive_org_puzzles.py,
tools/file_trove_puzzles.py).

  - order(): what was never read comes first, in the caller's order; then
    what new input or an explicit --reread made stale, the longest since
    read first (a row's "readAt"), so a run never starts over: the unread
    still lead and the stale queue by age. A change of code alone makes
    nothing stale; when()/read_before() pick the rows --reread BEFORE
    reads again, so the slices of one re-read resume rather than restart.
  - parallel(): `workers` sources in flight at once, in a process pool, so
    one source's wait on the desktop VLM (one request at a time) overlaps
    another's OCR. No source starts once `deadline` (time.monotonic()) has
    passed. A source whose read raises is logged (the source and the
    traceback) and stands as `failed(item, error)`'s result, or is left out:
    one bad page never stops a run.
  - lock(): one run per ledger, so a long full pass and the nightly never
    write the same ledger at once.
  - request_reread(): an annotation that met a misread clue on an OCR'd
    puzzle (tools/annotate_check.py: a printedClue filed, or a rejection on a
    clue-text check) asks for its source to be read again. A request is open
    while the filer's ledger row for that source was last read before it
    ("readAt"), so the re-read itself closes it; the burn
    (tools/prereset_plan.py --backlog) leaves a puzzle with an open request
    alone, and tools/ocr_full_pass.sh reads the requested sources
    (`python3 tools/scan_queue.py requested <filer> [paper]`). One request per
    puzzle per reading of its clues: a re-read that gives the same clues
    leaves the puzzle annotatable, and its next failure asks for nothing.

    python3 tools/scan_queue.py requested archive times   # open editions, one a line
    python3 tools/scan_queue.py requested trove           # open articles
    python3 tools/scan_queue.py open                      # puzzle ids waiting on a re-read
"""
import contextlib
import datetime
import hashlib
import json
import multiprocessing
import os
import sys
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def when(text):
    """The datetime an ISO `text` names ("now": this moment), None for None:
    a --reread BEFORE."""
    if text is None:
        return None
    if text == "now":
        return datetime.datetime.now(datetime.timezone.utc)
    t = datetime.datetime.fromisoformat(text)
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def read_before(row, t):
    """Whether ledger `row` was last read before datetime `t` (no "readAt":
    it was)."""
    at = row.get("readAt")
    return not at or when(at) < t


def order(keys, rows, unread):
    """`keys` (in the caller's order) with the never-read first, then the
    rest by their row's "readAt", oldest first (none: first of all)."""
    fresh = [k for k in keys if unread(rows.get(k))]
    stale = [k for k in keys if not unread(rows.get(k))]
    stale.sort(key=lambda k: rows[k].get("readAt") or "")
    return fresh + stale


@contextlib.contextmanager
def lock(ledger, wait_for_it=False):
    """Yields whether this run holds `ledger`'s lock (<ledger>.lock); with
    `wait_for_it`, waits for it instead of yielding False."""
    import fcntl  # here, not at the top: the desktop (Windows) imports this module, never locks
    path = ledger.with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if not wait_for_it:
                yield False
                return
            # Said before blocking, so a log that stops here says why.
            print(f"{time.strftime('%H:%M:%S')} waiting for another run's hold on {path}",
                  file=sys.stderr, flush=True)
            fcntl.flock(f, fcntl.LOCK_EX)
        yield True


def failure(item, e):
    """The log line for `item`'s read raising `e`: the source and the whole
    traceback (a worker's included), so the log says what to look at."""
    text = "".join(traceback.format_exception(e)).rstrip()
    print(f"{time.strftime('%H:%M:%S')} failed {item[0]}: {type(e).__name__}: {e}\n{text}",
          file=sys.stderr, flush=True)
    return f"{type(e).__name__}: {e}"


def file_puzzle(write_puzzle_file, generator, path, puzzle, verdict):
    """Write `puzzle` to `path`, noting the outcome on `verdict`; True when
    written. A clue holding another clue's or the page's text
    (ocr_clues.bled), or a write puzzle_integrity refuses, is a
    refusedWrite; any other raise is a writeFailed, logged with its
    traceback: one puzzle that cannot be written never stops a run."""
    import ocr_clues
    import puzzle_integrity  # it imports the write path, so not at the top
    bleed = [f"{e.get('number')}-{e.get('direction')} {why}" for e in puzzle.get("entries") or ()
             if (why := ocr_clues.bled((e.get("clue") or {}).get("text")))]
    if bleed:
        verdict["refusedWrite"] = f"refusing to write {puzzle.get('id')}: " + "; ".join(bleed)
        return False
    try:
        write_puzzle_file(path, puzzle, generator=generator)
    except puzzle_integrity.RefusedWrite as e:
        verdict["refusedWrite"] = str(e)
    except Exception as e:  # noqa: BLE001 -- one bad puzzle is a verdict, not a crash
        verdict["writeFailed"] = failure((puzzle.get("id"),), e)
    else:
        verdict["wrote"] = True
        return True
    return False


def parallel(items, fn, workers=1, deadline=None, init=None, initargs=(), failed=None):
    """Yields (item, fn(*item)) as each finishes, at most `workers` at once
    (1: in this process, in order). `init(*initargs)` runs first in each
    process. No item starts once `deadline` has passed. An item whose fn
    raises is logged and yields (item, failed(item, "Type: message")), or
    nothing without `failed`. A dead pool (a worker killed) still raises:
    that is the host, not the item."""
    def due():
        return deadline is not None and time.monotonic() >= deadline
    items = iter(items)
    if workers <= 1:
        if init:
            init(*initargs)
        for item in items:
            if due():
                return
            try:
                result = fn(*item)
            except Exception as e:  # noqa: BLE001 -- one bad source is logged, not the run's end
                error = failure(item, e)
                if failed is not None:
                    yield item, failed(item, error)
                continue
            yield item, result
        return
    # Forked, so a worker starts with the parent's lexicon and modules loaded
    # (the parent loads no OCR model, so no thread is forked mid-call).
    method = "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
    with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context(method),
                             initializer=init, initargs=initargs) as pool:
        running = {}

        def top_up():
            while len(running) < workers and not due():
                item = next(items, None)
                if item is None:
                    return
                running[pool.submit(fn, *item)] = item
        top_up()
        while running:
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for fut in done:
                item = running.pop(fut)
                try:
                    result = fut.result()
                except BrokenProcessPool:
                    raise
                except Exception as e:  # noqa: BLE001 -- one bad source is logged, not the run's end
                    error = failure(item, e)
                    if failed is not None:
                        yield item, failed(item, error)
                    continue
                yield item, result
            top_up()


#: Each filer's ledger, the one place a source's last read ("readAt") is kept.
LEDGERS = {"archive": Path(os.path.expanduser("~/.cache/archive_org_editions/filed.jsonl")),
           "trove": Path(os.path.expanduser("~/.cache/trove/filed.jsonl"))}
#: The re-read requests, appended to by annotation runs in any worktree.
REQUESTS = Path(os.environ.get("SCAN_REREAD_REQUESTS")
                or os.path.expanduser("~/.cache/scan_reread_requests.jsonl"))


def _rows(path):
    """A jsonl file's rows; none when it is missing. A filer replaces its
    ledger whole (a rename), so a line is never half-written."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def sources():
    """{puzzle id: (filer, source key, ledger row)} for every puzzle a scan
    filer's ledger says it read: an archive.org edition's verdicts, a Trove
    article's id."""
    out = {}
    for row in _rows(LEDGERS["archive"]):
        for v in row.get("verdicts") or ():
            if v.get("id"):
                out[v["id"]] = ("archive", row["edition"], row)
    for row in _rows(LEDGERS["trove"]):
        if row.get("id"):
            out[row["id"]] = ("trove", row["article"], row)
    return out


def clue_key(entries):
    """A hash of the clues as read: [(entry id, printed clue)]."""
    return hashlib.sha256(json.dumps(sorted(entries)).encode()).hexdigest()[:16]


def is_open(req, ledgers=None):
    """Whether request `req` waits on its source's re-read: the ledger row for
    it was last read before the request (no row: never read since)."""
    rows = {}
    for filer, key, row in (ledgers or sources()).values():
        rows[(filer, key)] = row
    row = rows.get((req["filer"], req["source"]))
    return row is None or read_before(row, when(req["requestedAt"]))


def requests():
    return _rows(REQUESTS)


def open_requests():
    """The requests whose source has not been read since."""
    known = sources()
    return [r for r in requests() if is_open(r, known)]


def request_reread(puzzle, clues, why):
    """Ask for `puzzle`'s source to be read again; `clues` is [(entry id,
    printed clue)] as the source gave them, `why` the checks that met a
    misread. Returns the request filed, or None: not an OCR channel
    (provenance.OCR_CHANNELS, read off source.retrievedFrom), no filer
    ledger names its source (a book has no re-read), or these clues were
    asked about already."""
    import provenance
    if (puzzle.get("source") or {}).get("retrievedFrom") not in provenance.OCR_CHANNELS:
        return None
    found = sources().get(puzzle["id"])
    if found is None:
        return None
    key = clue_key(clues)
    if any(r["id"] == puzzle["id"] and r["clues"] == key for r in requests()):
        return None
    req = {"id": puzzle["id"], "filer": found[0], "source": found[1], "clues": key,
           "why": sorted(set(why)), "requestedAt": now()}
    REQUESTS.parent.mkdir(parents=True, exist_ok=True)
    with open(REQUESTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(req) + "\n")
    return req


def main(argv):
    if argv[:1] == ["open"]:
        print("\n".join(sorted({r["id"] for r in open_requests()})))
        return 0
    if argv[:1] == ["requested"] and len(argv) >= 2:
        filer, paper = argv[1], (argv[2] if len(argv) > 2 else None)
        want = None
        if paper:
            import file_archive_org_puzzles
            want = file_archive_org_puzzles.PAPERS[paper].series
        import provenance
        print("\n".join(sorted({r["source"] for r in open_requests() if r["filer"] == filer
                                and (want is None or provenance.series_of_id(r["id"]) == want)})))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
