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
  - A ledger is append-only jsonl, one row per source read, the last row
    for a source standing (ledger_rows()): append() adds rows under a hold
    on the ledger's lock lasting only the write, so the per-edition units of
    tools/edition_queue.py each add their own row and none rewrites another's;
    a run holding the lock throughout (lock()) may rewrite it whole, and
    compact() folds it to one row a source. source_lock() keeps two units off
    one source.
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
import downloads


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


def ledger_rows(path, key):
    """{row[key]: row} of a jsonl ledger, the last row for a key standing;
    {} when it is missing. A final line still being appended (no newline
    yet) is not a row."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    out = {}
    lines = text.split("\n")
    for line in lines[:-1] if not text.endswith("\n") else lines:
        if line.strip():
            row = json.loads(line)
            out[row[key]] = row
    return out


def append(ledger, rows):
    """Add `rows` to `ledger`, one line each, in one write, under its lock
    held only for that write (a run holding it throughout keeps this
    waiting: append runs only when lock() is not held for a whole run)."""
    import fcntl
    if not rows:
        return
    data = "".join(json.dumps(r) + "\n" for r in rows).encode()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger.with_suffix(".lock"), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        fd = os.open(ledger, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)


def compact(ledger, key):
    """Rewrite `ledger` to one row a source (whole-or-none), unless a run
    holds its lock; returns (rows before, rows after), None when held."""
    import fcntl
    if not ledger.exists():
        return 0, 0
    with open(ledger.with_suffix(".lock"), "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        before = sum(1 for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip())
        rows = ledger_rows(ledger, key)
        tmp = ledger.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in rows.values()), encoding="utf-8")
        tmp.replace(ledger)
        return before, len(rows)


def held(ledger):
    """Whether a run holds `ledger`'s lock right now."""
    import fcntl
    path = ledger.with_suffix(".lock")
    if not path.exists():
        return False
    with open(path, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


@contextlib.contextmanager
def source_lock(ledger, source):
    """Yields whether this process holds `source`'s own lock (beside
    `ledger`, in <ledger stem>.locks/), never waiting: a source being read
    by another unit is not read twice."""
    import fcntl
    d = ledger.parent / f"{ledger.stem}.locks"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / (hashlib.sha256(source.encode()).hexdigest()[:20] + ".lock"), "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
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
             if (why := ocr_clues.bled((e.get("clue") or {}).get("text"), (e.get("clue") or {}).get("asPrinted") or ()))]
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
    # One snapshot of the code for the whole run: the write path loads
    # puzzle_integrity lazily, and a checkout that moved since this process
    # started would pair its new file with the older modules already loaded.
    import ocr_clues  # noqa: F401
    import puzzle_integrity  # noqa: F401
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
#: Each scan filer's ledger; "gale" is the archive filer's for the Gale
#: Times pages (file_archive_org_puzzles.GALE), its rows the archive filer's.
LEDGERS = {"archive": downloads.ARCHIVE_ORG / "filed.jsonl", "gale": downloads.GALE_LEDGER,
           "trove": downloads.TROVE / "filed.jsonl"}
#: The re-read requests, appended to by annotation runs in any worktree.
REQUESTS = Path(os.environ.get("SCAN_REREAD_REQUESTS")
                or os.path.expanduser("~/.cache/scan_reread_requests.jsonl"))


def jsonl_rows(path):
    """A jsonl file's rows, in order; none when it is missing. A final line
    still being appended (no newline yet) is not a row."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    lines = text.split("\n")
    return [json.loads(line) for line in (lines if text.endswith("\n") else lines[:-1]) if line.strip()]


def sources():
    """{puzzle id: (filer, source key, ledger row)} for every puzzle a scan
    filer's ledger says it read: an archive.org edition's verdicts, a Trove
    article's id (its last row: the Trove ledger is appended to)."""
    out = {}
    for row in [r for key in ("archive", "gale") if key in LEDGERS for r in jsonl_rows(LEDGERS[key])]:
        for v in row.get("verdicts") or ():
            if v.get("id"):
                out[v["id"]] = ("archive", row["edition"], row)
    for row in ledger_rows(LEDGERS["trove"], "article").values():
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
    return jsonl_rows(REQUESTS)


def open_requests():
    """The requests whose source has not been read since."""
    known = sources()
    return [r for r in requests() if is_open(r, known)]


#: Reads before this moment predate the re-read requests; a puzzle
#: they left with a printedClue row has not been re-read since.
FLAGGED_BEFORE = "2026-10-05T07:26:02-06:00"
CLUE_ROWS = Path(__file__).resolve().parent / "data" / "source_clue_wrong.json"


def flagged_requests():
    """A request per puzzle that has a source_clue_wrong row (a clue the
    scan misprinted or the OCR misread) and whose filer-ledger source was
    last read before FLAGGED_BEFORE: the same shape as request_reread's, so
    the source's next read closes it. Derived from the table, so it cannot go
    stale."""
    ids = {k.split("/", 1)[0] for k in json.loads(CLUE_ROWS.read_text(encoding="utf-8"))}
    known, t = sources(), when(FLAGGED_BEFORE)
    return [{"id": i, "filer": f, "source": key, "why": ["printedClue"], "requestedAt": FLAGGED_BEFORE}
            for i, (f, key, row) in sorted(known.items()) if i in ids and read_before(row, t)]


#: Each clue-vote change that mends blanks a held scan read left, as (when
#: it landed, the blank reasons it mends): each archive.org edition read
#: before it with a clue held blank for one of its reasons is read again.
#: The first is ocr_clues' speck between two words and clue cut at a line
#: wrap; the second relaid()'s light no reading laid, which the scan's own
#: readers now lay when they agree on its clue.
VOTE_MENDED = (
    ("2026-10-09T07:56:00+00:00", ("a stray mark inside a word", "end is lost: other readings have",
                                   "start is lost: other readings have")),
    ("2026-10-09T09:00:00+00:00", ("no reading laid a clue on it",)),
)


def vote_mended_requests():
    """A request per held archive.org puzzle the VOTE_MENDED changes may now
    file: a verdict with no file written whose every blank clue is one a
    change made since its read mends (another blank would hold it again).
    Derived from the ledger, so the re-read closes it."""
    out = []
    for i, (f, key, row) in sorted(sources().items()):
        if f != "archive":
            continue
        v = next((v for v in row.get("verdicts") or () if v.get("id") == i), {})
        whys = list((v.get("blank") or {}).values())
        since = [(at, mends) for at, mends in VOTE_MENDED if read_before(row, when(at))]
        due = [max((at for at, mends in since if any(m in why for m in mends)), default=None) for why in whys]
        if whys and all(due) and not v.get("wrote"):
            out.append({"id": i, "filer": f, "source": key, "why": ["voteMended"], "requestedAt": max(due)})
    return out


def all_open_requests():
    return open_requests() + flagged_requests() + vote_mended_requests()


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
        print("\n".join(sorted({r["id"] for r in all_open_requests()})))
        return 0
    if argv[:1] == ["requested"] and len(argv) >= 2:
        filer, paper = argv[1], (argv[2] if len(argv) > 2 else None)
        def owns(source):
            # The archive filer's papers by the edition's item, not the
            # series: the Gale Times pages are a run (and ledger) of their own.
            if not paper:
                return True
            import file_archive_org_puzzles as fa
            return fa.filer_of(source) is fa.FILERS[paper]
        print("\n".join(sorted({r["source"] for r in all_open_requests() if r["filer"] == filer
                                and owns(r["source"])})))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
