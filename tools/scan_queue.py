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
    python3 tools/scan_queue.py conflicted COMMIT         # ask re-reads for a commit set aside

  - conflicted(): a filing commit that will not replay onto origin/master
    (tools/push_puzzle_commit.sh's CONFLICT: another job filed the same
    puzzle meanwhile) is set aside by tools/durable.sh, origin's version
    standing; each puzzle it filed asks for its source to be read again
    ("pushConflict"), so the next read files over origin's file and nothing
    its reading held is lost. Exit 1 when a path it changed has no re-read
    (not an OCR'd puzzle, or not a puzzle): the caller keeps the commit.
"""
import contextlib
import datetime
import hashlib
import importlib
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

#: The modules file_puzzle() loads lazily (importing this module must not
#: load them), which parallel() loads up front.
WRITE_PATH_MODULES = ("ocr_clues", "puzzle_integrity")

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


#: How long a unit waits out a hold on its ledger before it ends "held": a
#: slice's upkeep (edition_queue.ledger_upkeep: compact(), tens of seconds on
#: the media mount) holds it as the slice's first units start, and those
#: ended at once left the desktop idle until the next plan (10-13); a batch
#: run holding it throughout outlasts this.
UNIT_HOLD_WAIT = 180


def held(ledger, wait=0):
    """Whether a run holds `ledger`'s lock, still after `wait` seconds."""
    import fcntl
    path = ledger.with_suffix(".lock")
    if not path.exists():
        return False
    deadline = time.monotonic() + wait
    with open(path, "a") as f:
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    return True
                time.sleep(min(1.0, max(0.05, deadline - time.monotonic())))
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
    except Exception as e:  # any raise: one bad puzzle is a verdict, not a crash
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
    for name in WRITE_PATH_MODULES:
        importlib.import_module(name)
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
            except Exception as e:  # any raise: one bad source is logged, not the run's end
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
                except Exception as e:  # any raise: one bad source is logged, not the run's end
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
#: readers now lay when they agree on its clue; the third join_split()'s
#: word a reading broke at a kept hyphen or a speck read as a comma; the
#: fifth ocr_clues' clue number or count read as letters (number_read),
#: taken for a start or end the clue lost; the sixth suspect()'s word that
#: drops its aitch after an apostrophe ("'igher"), refused as no word; the
#: seventh join_split()'s word broken at a comma that one other reading also
#: broke, or into two words, which most readings print whole; the eighth
#: agree()'s figure run onto a word that no reading prints ("3Island",
#: "said the1 Rev"), refused as a digit inside a word; the ninth agree()'s
#: stop or middle dot glued between two words ("visionary.lose.his", "for
#: .concealed"), refused as a stray mark inside a word, and the Times
#: filer's word every reading spells alike ("ignis"), refused as no word;
#: the tenth parted()'s misread most readings print whole as a known word
#: ("reorgauized", once "re orgau ized") and agree()'s halves of a word
#: joined once the next word is parted off ("orig inallyby"), refused as
#: no word; the eleventh agree()'s first letter read as a bracket the clue
#: never closes ("(ornwall"), dropped once the vote puts the letter back;
#: the twelfth join_split()'s line-end halves every reading breaks ("phy,
#: sics"), parted()'s corpus word kept whole ("Ignatius") and formed()'s
#: de-, -ist and -ion for -or ("decentralization"), refused as no word;
#: the last agree()'s count or next clue number run onto the clue's last
#: word or its "?" ("for her7", "say?14") and letter read as its figure
#: that the vote put back ("to0", "Result0f"), refused as a digit inside
#: a word, and its last letter read as a bracket the clue never opened
#: ("vita)"), dropped once the vote puts the letter back. The entry for "a
#: stray letter" is unstrayed()'s lone letter read for the one short word
#: the readings print between its neighbours ("throws d sprightly"). The
#: 06:50 one is join_split()'s halves a letter off the one word most
#: readings print whole ("Rea dins", "builds ngs"), held blank as no other
#: reading has it, readings differ, or not a word. The 07:05 one is agree()
#: passing figure-shaped specks ("is" for "(5)", "down i") at a clue's edge
#: when no number or count is known (number_shaped), held as an end lost.
#: The 07:31 one is agree() taking the clue's own edge word split or run
#: apart in other readings ("broom slick", "prer criptious ?") as that word,
#: not an end lost (edge_split). The 07:55 one is agree() not counting figure
#: specks no word ("fS", "ll", "ii") as words seen at a clue's edge, so
#: words one reading of many sees there are no end lost (figure_specks).
#: The 08:10 one is consensus() taking the word one reading prints when
#: every other reading lies within PRINTED_SLIPS of it ("with" for "ujLh /
#: ujth"), held as readings differ. The 08:23 one is agree() taking a
#: capital S a reader ran onto a word ("driveS", "STakes") as a vote for
#: the word in a tie with its plural (speck_free), held as readings differ.
#: The 09:07 one is agree() laying a clue no other reading prints word for
#: word ("Yardous" for "Various") from the clue most of them print (relay).
#: The 09:57 one is agree() re-laying a clue unless a reading prints every
#: laid word in a row ("This bouse is surrounded trees"), held as readings
#: differ, no other reading has, not a word, or an end lost.
VOTE_MENDED = (
    ("2026-10-09T07:56:00+00:00", ("a stray mark inside a word", "end is lost: other readings have",
                                   "start is lost: other readings have")),
    ("2026-10-09T09:45:00+00:00", ("no reading laid a clue on it",)),
    ("2026-10-09T22:50:00+00:00", ("readings differ", "no other reading has", "not a word")),
    ("2026-10-10T01:00:00+00:00", ("no other reading has",)),
    ("2026-10-10T01:35:00+00:00", ("end is lost: other readings have", "start is lost: other readings have")),
    ("2026-10-10T14:30:00+00:00", ("not a word",)),
    ("2026-10-10T20:00:00+00:00", ("readings differ", "not a word")),
    ("2026-10-11T01:50:00+00:00", ("a digit inside a word",)),
    ("2026-10-11T02:31:00+00:00", ("a stray mark inside a word", "not a word")),
    ("2026-10-11T02:50:00+00:00", ("not a word",)),
    ("2026-10-11T03:31:00+00:00", ("a bracket never closed or opened",)),
    ("2026-10-11T04:12:00+00:00", ("not a word",)),
    ("2026-10-11T04:40:00+00:00", ("a digit inside a word",)),
    ("2026-10-11T05:00:00+00:00", ("a bracket never closed or opened",)),
    ("2026-10-11T06:19:00+00:00", ("a stray mark inside a word",)),
    ("2026-10-11T06:35:00+00:00", ("a stray letter",)),
    ("2026-10-11T06:50:00+00:00", ("no other reading has", "readings differ", "not a word")),
    ("2026-10-11T07:05:00+00:00", ("end is lost: other readings have", "start is lost: other readings have")),
    ("2026-10-11T07:31:00+00:00", ("end is lost: other readings have", "start is lost: other readings have")),
    ("2026-10-11T07:55:00+00:00", ("end is lost: other readings have", "start is lost: other readings have")),
    ("2026-10-11T08:10:00+00:00", ("readings differ",)),
    ("2026-10-11T08:23:00+00:00", ("readings differ",)),
    ("2026-10-11T08:42:00+00:00", ("no other reading has",)),
    ("2026-10-11T09:07:00+00:00", ("no other reading has",)),
    ("2026-10-11T09:38:00+00:00", ("no other reading has",)),
    ("2026-10-11T09:57:44+00:00", ("readings differ", "no other reading has", "not a word", "agree on a non-word",
                                   "end is lost: other readings have", "start is lost: other readings have")),
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
        at = mended_at(row, v)
        if at and not v.get("wrote"):
            out.append({"id": i, "filer": f, "source": key, "why": ["voteMended"], "requestedAt": at})
    return out


def mended_at(row, verdict):
    """When the last VOTE_MENDED change that mends a blank clue of
    `verdict` (of ledger `row`) landed, if one landed since its read for
    every blank clue it has; else None (none blank, or one no change mends)."""
    whys = list((verdict.get("blank") or {}).values())
    since = [(at, mends) for at, mends in VOTE_MENDED if read_before(row, when(at))]
    due = [max((at for at, mends in since if any(m in why for m in mends)), default=None) for why in whys]
    return max(due) if whys and all(due) else None


#: When each scan filer learned to drop a misread count left after a
#: clue's last word ("Overdone quality 7"), by filer: archive.org's vote
#: (agree) and corrected_clues(), Trove's build(). A filed puzzle read
#: before it with such a clue (count_left) is read again.
COUNT_LEFT_AT = {"archive": "2026-10-11T05:39:14+00:00", "trove": "2026-10-11T06:04:08+00:00"}


def count_left_requests():
    """A request per filed scan puzzle read before its filer's
    COUNT_LEFT_AT with a clue that ends in its count misread (count_left).
    Derived from the files, so the re-read closes it."""
    import puzzle_paths
    from file_archive_org_puzzles import count_left
    out = []
    for i, (f, key, row) in sorted(sources().items()):
        if not read_before(row, when(COUNT_LEFT_AT[f])) or not (path := puzzle_paths.find(i)):
            continue
        entries = json.loads(path.read_text(encoding="utf-8")).get("entries") or ()
        lights = {e["number"] for e in entries}
        if any(count_left((e.get("clue") or {}).get("text"), e.get("length"), lights) for e in entries):
            out.append({"id": i, "filer": f, "source": key, "why": ["countLeft"], "requestedAt": COUNT_LEFT_AT[f]})
    return out


def all_open_requests():
    return open_requests() + flagged_requests() + vote_mended_requests() + count_left_requests()


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


def conflicted(commit):
    """Ask a re-read of each puzzle `commit` filed; [(path, request or None)]
    for every path it changed, None where nothing re-reads it."""
    import subprocess

    import enumeration
    from groups import entry_id
    git = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout
    out = []
    for line in git("diff-tree", "--no-commit-id", "-r", "--name-status", "-M", commit).splitlines():
        status, *paths = line.split("\t")
        path = paths[-1]
        req = None
        if status[0] != "D" and path.startswith("puzzles/") and path.endswith(".json"):
            puzzle = json.loads(git("show", f"{commit}:{path}"))
            clues = [(entry_id(e), enumeration.printed(e["clue"])) for e in puzzle.get("entries") or ()]
            req = request_reread(puzzle, clues, ["pushConflict"]) or next(
                (r for r in open_requests() if r["id"] == puzzle.get("id")), None)
        out.append((path, req))
    return out


def main(argv):
    if argv[:1] == ["conflicted"] and len(argv) == 2:
        got = conflicted(argv[1])
        for path, req in got:
            print(f"{path}: " + (f"re-read asked of {req['filer']} {req['source']}" if req else "nothing re-reads it"))
        return 0 if got and all(req for _, req in got) else 1
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
