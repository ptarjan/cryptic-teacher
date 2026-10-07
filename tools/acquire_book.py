#!/usr/bin/env python3
"""Take a book from an archive.org identifier to filed puzzles with NO model.

    python3 tools/acquire_book.py newpenguinbkguar0000perk
    python3 tools/acquire_book.py <id> --file --puzzle-dir puzzles

Acquiring a crossword book used to cost hours of inference per book: a model
read the OCR, eyeballed the clue lists, and hand-built the JSON. Every step of
that is arithmetic, and this is the arithmetic. What comes out the far end is
a filed, UNSOLVED puzzle -- grid and clue list, no answers -- which the
nightly cold-solve queue picks up on its own. The only thing left for a human
is to read the report and spot-check what it flagged.

FIVE STAGES, all CPU. Each one reports what it could not do rather than
guessing, because a wrong puzzle costs far more to find later than a missing
one costs now.

  1. TEXT. The item's OCR text layer, cheapest route first: an explicit
     --text, then a file left by an earlier tools/fetch_ia_book.py run, then
     archive.org's public <id>_djvu.txt, and finally — for a lending item,
     which is what every book on the acquire list is — a borrow, read and
     return through tools/fetch_ia_book.py. The borrow is not duplicated
     here: fetch_ia_book.borrowed() is a context manager that takes the loan
     and RETURNS IT on every path out of the block, including an exception
     or a Ctrl-C, because these are one-hour single-copy loans and a missed
     return locks the book for the next hour. One loan at a time, one book.
     Pass --no-borrow for a run that must stay entirely public.

     Borrowing is what makes the whole pipeline CPU end to end. It is also
     the one stage that can fail for a reason retrying will fix, so the
     three stop conditions are reported apart rather than as one "no text":
     "no-credentials" (no archive.org login is configured — the report says
     which file to create), "borrow-refused" (archive.org would not lend it,
     carrying its own reason verbatim, which after tools/fetch_ia_book.py's
     availability check distinguishes "all copies checked out, retry later"
     from "this item needs no loan"), and "text-not-public" (there is no
     text layer to get at all, for anyone). Any of them exits non-zero, so an
     unattended run cannot report success having acquired nothing.

     "lending-limit" is reported apart from "borrow-refused" and exits
     EXIT_LENDING_LIMIT (3) rather than 1, because it is the one refusal that
     is not about this book: archive.org has throttled the ACCOUNT, so the
     next identifier and every identifier after it gets the same answer. A
     driver looping over a book list must stop on 3. It is not a concurrency
     cap and returning loans need not clear it — see THE LENDING LIMIT in
     tools/fetch_ia_book.py.

     "not-lendable" exits EXIT_NOT_LENDABLE (4): archive.org lends no copy of
     the book and will not let this account read it, so no retry changes
     anything. It is written to tools/data/book_reads.json with its reason
     (book_queue.record_not_lendable), which drops it from the queue; a driver
     moves on to the next book.
  2. SPLIT. tools/parse_penguin_book.py cuts the book into puzzles and reads
     each one's setter, number and clue list.
  3. GEOMETRY. tools/light_spec.py turns one clue list into a light spec,
     tools/grid_verdict.py throws out the specs that cannot be a 15x15
     before any search happens, tools/reconstruct_grid.py derives the grid,
     and grid_verdict judges the fills that come back.
  4. FILE. tools/file_penguin_puzzle.py --unsolved, called in process, writes
     the puzzle. One whose search did not settle on one grid (none, several,
     out of budget: often a scan that lost the clue numbers) is filed as its
     clues alone through tools/clues_only.py; its answers derive the grid. DEFAULT IS A SCRATCH DIRECTORY, not the corpus: filing is
     the one irreversible stage, so it takes --file and an explicit
     --puzzle-dir to touch puzzles/.
  5. REPORT. One JSON row per puzzle: lights recovered, status, the
     measurements behind the status, and the reason for every refusal.

WHY THE LIGHT COUNT IS THE HEADLINE NUMBER, not the clue numbers. Clue
numbers OCR badly and are recoverable: the reconstructor takes a list with
holes in it. Whole missing clues are not recoverable by anything, because the
grid that gets derived is then the grid of a DIFFERENT, looser puzzle, and it
comes back looking clean. A 15x15 prints at least 24 lights and the known-good
set prints 26-32, so 11-23 lights means reconstruction is impossible no matter
how tidy the numbering looks. That gate is in tools/grid_verdict.py with every
other threshold and the corpus measurement that set it.

THE SEARCH IS BOUNDED TWICE, by node count and by wall clock, because a
single pathological clue list will otherwise eat the run. A puzzle that hits
either bound is reported as budget-exhausted, which is a statement about this
machine and not about the puzzle, and is deliberately not folded into either
the successes or the failures.

THE GATE. tools/test_acquire_book.sh reproduces the ten-puzzle vol-5 control
and fails if a single grid or a single NODE COUNT moves. The search is
deterministic, so a node count is a fingerprint of the spec that went in: it
catches a parser change that a grid comparison would sleep through.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import book_queue  # noqa: E402
import grid_verdict  # noqa: E402
from light_spec import build_spec, coverage  # noqa: E402
from parse_penguin_book import build_quality_report, parse_book  # noqa: E402
from reconstruct_grid import conventions_broken, reconstruct  # noqa: E402
import clues_only  # noqa: E402
from series import BOOK_SERIES, book_number, puzzle_id  # noqa: E402
from clues_only import entries_from_grid  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (cryptic-teacher; personal educational use)"}
PUBLIC_TEXT_URL = "https://archive.org/download/{id}/{id}_djvu.txt"
METADATA_URL = "https://archive.org/metadata/{id}"
# Where tools/fetch_ia_book.py leaves what a human borrowed earlier.
FETCHED_TEXT_DIR = book_queue.TEXT_DIR
# Durable, not /tmp: the nightly restart empties /tmp, and tools/coverage.py
# reads each book's report.json here for why its unfiled puzzles are unfiled.
DEFAULT_OUT = Path.home() / ".cache" / "acquire_book"

# Stage 1 refused because the ACCOUNT is throttled, not because this book is
# unavailable. Its own exit code so a driver can tell "this book failed" from
# "every remaining book will fail" without parsing a message.
EXIT_LENDING_LIMIT = 3
# Stage 1 refused because archive.org lends this book to no one
# (fetch_ia_book.NotLendable). Recorded in book_queue's ledger, which drops it
# from the queue, so a driver moves on to the next book instead of alerting.
EXIT_NOT_LENDABLE = 4

NODE_BUDGET = 8_000_000   # the budget the vol-5 control was measured under
WALL_SECONDS = 240        # per puzzle, enforced inside the worker
SOLUTION_LIMIT = 40
# Searches in flight on the desktop at once (tools/ocr_remote.py): it has 28
# threads, and the OCR full pass holds 20 sessions of two.
REMOTE_SLOTS = 8


# ------------------------------------------------------------------ stage 1

def fetch_text(identifier, override=None, allow_borrow=True, max_pages=None):
    """(path, how, status) for the item's OCR text. status is None when there
    is text, and otherwise names which stop this was, since they want
    different things from whoever reads the run: "no-credentials" is fixed by
    creating a file, "borrow-refused" often by waiting an hour, and
    "text-not-public" by nothing at all.

    CHEAPEST ROUTE FIRST, so archive.org is asked for a loan only when the
    free routes are genuinely exhausted: --text, then an earlier run's cached
    text, then the public <id>_djvu.txt, then a borrow. A lending item's text
    layer is never publicly served -- <id>_djvu.txt stays HTTP 401 even for
    someone holding a loan, which tools/fetch_ia_book.py documents in detail
    -- so for those the borrow is not an optimisation, it is the only route.
    """
    if override:
        p = Path(override)
        if not p.exists():
            return None, f"--text {p} does not exist", "text-not-public"
        return p, f"--text {p}", None

    cached = FETCHED_TEXT_DIR / f"{identifier}.txt"
    if cached.exists() and cached.stat().st_size > 0:
        return cached, (f"{cached}, left by an earlier borrow (no loan taken "
                        f"this run)"), None

    url = PUBLIC_TEXT_URL.format(id=identifier)
    body = None
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
    except urllib.error.HTTPError as err:
        why = _not_public(identifier, url, f"HTTP {err.code}")
    except urllib.error.URLError as err:
        return None, f"{url} could not be reached: {err.reason}", "text-not-public"
    else:
        if not body.strip():
            body, why = None, _not_public(identifier, url, "an empty body")

    if body is not None:
        DEFAULT_OUT.mkdir(parents=True, exist_ok=True)
        out = DEFAULT_OUT / f"{identifier}.txt"
        out.write_bytes(body)
        return out, f"{url} (public text layer, {len(body)} bytes)", None

    kind, _ = item_restriction(identifier)
    if kind == "lending":
        if not allow_borrow:
            return None, f"{why}; --no-borrow was given, so no loan was taken", \
                "text-not-public"
        return borrow_text(identifier, max_pages)
    return None, why, "text-not-public"


def item_restriction(identifier):
    """(kind, detail) for why archive.org serves no public text: "lending",
    "missing", "public-no-ocr", or "unknown" when the metadata call itself
    failed. Kept separate from the message because stage 1 has to ACT on the
    answer — a lending item is the one case there is a route around."""
    try:
        req = urllib.request.Request(METADATA_URL.format(id=identifier), headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            meta = json.loads(r.read()).get("metadata", {})
    except Exception as err:
        return "unknown", f"; archive.org's metadata could not be read ({err})"
    if not meta:
        return "missing", "; archive.org has no item with that identifier"
    if meta.get("access-restricted-item") in ("true", True):
        return "lending", ("; this is a lending item — archive.org serves no "
                           "public text layer for one, and a loan does not "
                           "unlock <id>_djvu.txt either, so the text has to "
                           "come from the BookReader page OCR behind a loan")
    return "public-no-ocr", ("; the item is public but has no _djvu.txt, so it "
                             "was never OCR'd")


def _not_public(identifier, url, what):
    """Say WHY the text is unavailable, naming the restriction if there is
    one. "404" sends someone to check their spelling; "this is a lending
    item" says which route is left."""
    _, detail = item_restriction(identifier)
    return f"{url} returned {what}{detail}"


def borrow_text(identifier, max_pages=None):
    """(path, how, status) — stage 1 for a lending item: borrow it, read its
    page OCR, return the loan, and leave the text where the cache above will
    find it so a second run never borrows the same book twice.

    THE LOAN IS RETURNED BY THE SHAPE OF THE CODE, not by remembering to.
    fetch_ia_book.borrowed() is a context manager whose finally clause hands
    the loan back on every exit — success, exception, or KeyboardInterrupt —
    and this function adds no path that escapes it. One identifier, one loan,
    held for exactly as long as the read takes.

    fetch_ia_book is imported HERE rather than at module scope on purpose: it
    needs the third-party `requests`, and tools/test_acquire_book.sh imports
    this module on a runner that has no third-party packages at all. A
    missing dependency must cost the borrow route, not every caller of the
    file.
    """
    try:
        import fetch_ia_book as ia
    except ModuleNotFoundError as err:
        return None, (f"borrowing {identifier} needs the `requests` package, "
                      f"which is not installed here ({err}). Install it, or "
                      f"run tools/fetch_ia_book.py elsewhere and pass the "
                      f"result to --text"), "no-borrow-dependency"

    creds_path = Path(os.environ.get("IA_CREDS", ia.DEFAULT_CREDS)).expanduser()
    try:
        ia.load_credentials(creds_path)
    except SystemExit as err:
        # load_credentials already names the exact path and the exact file
        # shape to create. Quoting it beats writing that sentence twice and
        # letting the two drift.
        return None, (f"{identifier} is a lending item, so acquiring it needs "
                      f"an archive.org login, and there isn't one: {err}"), \
            "no-credentials"

    try:
        with ia.borrowed(identifier) as session:
            text = ia.fetch_full_text(session, identifier, max_pages)
    except ia.LendingLimitReached as err:
        # Caught ahead of SystemExit, which it subclasses. Folding it into
        # "borrow-refused" is what let one run report the same account-level
        # refusal 24 times, once per book, and acquire nothing.
        return None, str(err), "lending-limit"
    except ia.NotLendable as err:
        # Also a SystemExit, and the one refusal about the book for good.
        return None, str(err), "not-lendable"
    except SystemExit as err:
        # Carries archive.org's real condition verbatim — including "all
        # copies checked out, retry later", which is a retry, not a defeat.
        return None, str(err), "borrow-refused"

    if not text.strip():
        return None, (f"the loan for {identifier} succeeded but every page "
                      f"came back empty — the item has no text layer even "
                      f"behind a loan"), "text-not-public"

    FETCHED_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    if max_pages is None:
        out = FETCHED_TEXT_DIR / f"{identifier}.txt"
        note = f", cached at {out}"
    else:
        # A sample must never land under the whole-book name: the cache check
        # at the top of fetch_text would find it on the next run and acquire
        # a fraction of a book without anything looking wrong.
        out = FETCHED_TEXT_DIR / f"{identifier}.sample-{max_pages}p.txt"
        note = (f", written to {out} as a SAMPLE of the first {max_pages} "
                f"pages — not the book, and not cached as one")
    out.write_text(text, encoding="utf-8")
    return out, (f"borrowed from archive.org, {len(text)} chars of page OCR "
                 f"read, loan returned{note}"), None


# ------------------------------------------------------------------ stage 3

class _Timeout(Exception):
    pass


def _reconstruct_one(job):
    """One puzzle's geometry, in its own process under both budgets."""
    across, down = job["across"], job["down"]
    triples = ([(lg[0], "across", lg[1]) for lg in across]
               + [(lg[0], "down", lg[1]) for lg in down])
    found, info, error, timed_out = [], {"nodes": 0, "truncated": False}, None, False
    started = time.time()

    def _alarm(signum, frame):
        raise _Timeout()

    # Windows (the desktop, tools/ocr_remote.py) has no SIGALRM: there the
    # node budget is the bound.
    alarm = getattr(signal, "SIGALRM", None)
    if alarm is not None:
        signal.signal(alarm, _alarm)
        signal.alarm(WALL_SECONDS)
    try:
        found, info = reconstruct(triples, cols=15, rows=15, limit=SOLUTION_LIMIT,
                                  symmetry=True, max_nodes=NODE_BUDGET,
                                  fallback=False)
    except _Timeout:
        timed_out = True
    except Exception as err:
        # A spec reconstruct refuses (numbers that do not increase even after
        # repair, say) is a parse failure, not a crash of the run.
        error = f"{type(err).__name__}: {err}"
    finally:
        if alarm is not None:
            signal.alarm(0)

    grids = [tuple(g) for g in found]
    if error is not None:
        status, detail = "unparseable", {"reasons": [
            f"tools/reconstruct_grid.py refused this light spec — {error}"]}
    else:
        status, detail = grid_verdict.verdict(
            grids, truncated=bool(info["truncated"]) or timed_out)
    return {"book_number": job["book_number"], "status": status, "detail": detail,
            "grids": [list(g) for g in grids], "nodes": info["nodes"],
            "truncated": bool(info["truncated"]) or timed_out,
            "wall_clock_exhausted": timed_out, "error": error,
            "elapsed_sec": round(time.time() - started, 2),
            "conventions_broken": [conventions_broken(g) for g in grids]}


def _searched(jobs, local_jobs):
    """Each job's _reconstruct_one result, as each lands. With OCR_REMOTE
    set (tools/ocr_remote.py) up to REMOTE_SLOTS searches run on the desktop,
    each slot over its own ssh session; a slot with no desktop (unset, off,
    unreachable, or Paul gaming on it) hands its search to the local pool of
    local_jobs processes and tries the desktop again RETRY seconds later."""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import ocr_remote
    with ProcessPoolExecutor(max_workers=local_jobs) as pool:
        if not ocr_remote.hosts():
            yield from (f.result() for f in as_completed(
                [pool.submit(_reconstruct_one, j) for j in jobs]))
            return
        slot, opened = threading.local(), []

        def one(job):
            s = getattr(slot, "s", None)
            if s is None and time.monotonic() >= getattr(slot, "retry", 0.0) \
                    and not ocr_remote.desktop_busy.busy(ocr_remote.hosts()):
                s = slot.s = ocr_remote.connect()
                opened.append(s)
                if s is None:
                    slot.retry = time.monotonic() + ocr_remote.RETRY
            if s is not None:
                try:
                    got = s.reconstruct(job)
                    if "status" in got:
                        return got
                    print(f"  #{job['book_number']}: desktop search failed "
                          f"({got['error']}), searching here", file=sys.stderr)
                except ocr_remote.Unavailable as e:
                    print(f"  desktop lost ({e}), searching here", file=sys.stderr)
                    s.close()
                    slot.s, slot.retry = None, time.monotonic() + ocr_remote.RETRY
            return pool.submit(_reconstruct_one, job).result()

        with ThreadPoolExecutor(max_workers=REMOTE_SLOTS) as threads:
            try:
                yield from (f.result() for f in as_completed(
                    [threads.submit(one, j) for j in jobs]))
            finally:
                for s in filter(None, opened):
                    s.close()


# ------------------------------------------------------------------ stage 4

def file_unsolved(puzzle_meta, grid, across, down, identifier, out_dir):
    """(path, problems). Reuses tools/file_penguin_puzzle.py's own guard, in
    process, so everything it knows about these books -- the id, the
    book's year, the absent solution detail, how a linked group is stored -- is
    applied here too instead of being restated and drifting.

    `identifier` is the archive.org item THIS RUN read, and it is the ONLY
    thing that names the book: tools/data/books.json turns it into the index
    the number is built from, the title and source.url alike. Reading one
    volume's text while filing under another used to be this route's one
    silent mistake, and every puzzle it filed cited a book it did not come
    from for good. There is no second argument to disagree with now.
    """
    import puzzle_integrity
    from fetch_puzzle import write_puzzle_file
    from file_penguin_puzzle import build as build_penguin

    entries, problems = entries_from_grid(grid, across, down)
    if problems:
        return None, problems
    record = {"book_number": puzzle_meta["book_number"],
              "setter": puzzle_meta.get("setter"),
              "puzzle": {"dimensions": {"cols": len(grid[0]), "rows": len(grid)},
                          "entries": entries}}
    try:
        built = build_penguin(record, identifier, "unsolved", unsolved=True)
    except SystemExit as err:
        # file_penguin_puzzle refuses rather than guesses, which is right; a
        # refusal is this puzzle's problem and not the run's, so it is caught,
        # named, and the other puzzles carry on.
        return None, [f"tools/file_penguin_puzzle.py refused it: {err}"]
    except Exception as err:
        return None, [f"tools/file_penguin_puzzle.py raised "
                      f"{type(err).__name__}: {err}"]
    out_dir.mkdir(parents=True, exist_ok=True)
    # Named in out_dir; when out_dir is the corpus, write_puzzle_file files it
    # under its series and year folder instead and returns that path.
    try:
        path = write_puzzle_file(out_dir / f"{built['id']}.json", built,
                                 generator="tools/acquire_book.py")
    except puzzle_integrity.RefusedWrite as err:
        return None, [str(err)]
    return path, []


def file_clues_only(puzzle_meta, across, down, identifier, clues_dir):
    """(path, problems): the puzzle held as its clues alone (tools/clues_only
    .py), for one whose grid the search did not settle. The nightly solve
    answers it and the answers derive the grid. The id, title and year come
    from tools/file_penguin_puzzle.py, as for a grid puzzle."""
    import puzzle_integrity
    from file_penguin_puzzle import build as build_penguin
    try:
        meta = build_penguin({"book_number": puzzle_meta["book_number"],
                              "setter": puzzle_meta.get("setter"),
                              "puzzle": {"dimensions": {"cols": 15, "rows": 15},
                                         "entries": []}},
                             identifier, "unsolved", unsolved=True)
    except SystemExit as err:
        return None, [f"tools/file_penguin_puzzle.py refused it: {err}"]
    record, problems = clues_only.from_book(meta, across, down, "tools/acquire_book.py")
    if problems:
        return None, problems
    try:
        return clues_only.write(record, clues_dir), []
    except puzzle_integrity.RefusedWrite as err:
        return None, [str(err)]


def reprint_of(pid, across, down, index=None):
    """The held puzzle a book leaf reprints, or None: the id sharing at least
    clue_index.THRESHOLD of its clues (clue_index.matches; a listed reprint
    pair does not count). Such a leaf is not filed as `pid`: a Times
    anthology's page is the daily Times puzzle printed again, so it becomes
    one more reading of that puzzle (book_queue.save_reprint)."""
    if index is None:
        from fetch_puzzle import clue_index
        index = clue_index()
    hits = index.matches(pid, leaf_keys(across, down))
    return hits[0][0] if hits else None


def leaf_keys(across, down):
    """The clue_index keys of a leaf's printed clues."""
    from clue_index import clue_keys
    texts = [((light[3] if len(light) > 3 else None) or {}).get("clue")
             for light in list(across) + list(down)]
    return clue_keys({"entries": [{"clue": t} for t in texts if t]})


# ------------------------------------------------------------------- driver

def filed_positions(identifier, puzzle_dir):
    """{position: first Across clue} of identifier's puzzles under puzzle_dir."""
    books = json.loads((TOOLS / "data" / "books.json")
                       .read_text(encoding="utf-8"))["books"]
    index = next((b["book_index"] for b in books
                  if b["identifier"] == identifier), None)
    if index is None:
        return {}
    held = {}
    for path in Path(puzzle_dir).rglob("book-*.json"):
        number = path.stem.split("-", 1)[1]
        if number.isdigit() and int(number) // book_queue.POSITIONS_PER_VOLUME == index:
            entries = json.loads(path.read_text(encoding="utf-8")).get("entries") or []
            held[int(number) % book_queue.POSITIONS_PER_VOLUME] = first_clue(
                [(e.get("clue") or {}).get("text") for e in entries
                 if e.get("direction") == "across"])
    return held


def first_clue(texts):
    """A puzzle's first Across clue, folded for comparison, or None."""
    text = next((t for t in texts if t), None)
    return " ".join(text.lower().split())[:40] if text else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # The identifier is the whole answer to "which book is this". It names the
    # item this run reads AND the row in tools/data/books.json that says what
    # the book is, so a --series and a --volume beside it could only ever be a
    # second opinion about the text already on the page.
    ap.add_argument("identifier", help="archive.org item id, as registered in "
                                       "tools/data/books.json")
    ap.add_argument("--text", help="an OCR .txt already on disk, instead of fetching")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"where the report and any filed puzzles go (default {DEFAULT_OUT})")
    ap.add_argument("--puzzle-dir", type=Path,
                    help="where to file puzzles (default <out>/<identifier>/puzzles, "
                         "a scratch directory; pass puzzles/ to file for real)")
    ap.add_argument("--file", action="store_true",
                    help="actually write puzzle files; without it stages 1-3 and "
                         "5 run and nothing is written but the report")
    ap.add_argument("--no-borrow", action="store_true",
                    help="never take a loan: public routes only, and a lending "
                         "item stops the run instead of being borrowed")
    ap.add_argument("--max-pages", type=int,
                    help="when borrowing, read only the first N pages. A "
                         "SAMPLE for checking the route end to end; it is not "
                         "the whole book and is not cached as one")
    ap.add_argument("--jobs", type=int, default=4, help="parallel reconstructions here")
    ap.add_argument("--text-only", action="store_true",
                    help="stop after stage 1: get the text onto disk (borrowing "
                         "if need be, the loan returned) and read nothing")
    ap.add_argument("--limit", type=int, help="only the first N puzzles, for a smoke run")
    ap.add_argument("--only", type=int, nargs="*",
                    help="only these book numbers, for checking a known result")
    args = ap.parse_args(argv)

    work = args.out / args.identifier
    work.mkdir(parents=True, exist_ok=True)
    puzzle_dir = args.puzzle_dir or (work / "puzzles")
    report_path = work / "report.json"

    # ---- stage 1
    text_path, how, status = fetch_text(args.identifier, args.text,
                                         allow_borrow=not args.no_borrow,
                                         max_pages=args.max_pages)
    if text_path is None:
        report = {"identifier": args.identifier, "stage": "text",
                  "status": status, "reason": how, "puzzles": []}
        report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
        # The reason IS the message. Whoever reads this run is reading this
        # line, not a log somewhere, and the three stops want three different
        # things done about them.
        print(f"{args.identifier}: {status} — {how}", file=sys.stderr)
        print(f"report -> {report_path}")
        if status == "not-lendable":
            book_queue.record_not_lendable(args.identifier, how)
            return EXIT_NOT_LENDABLE
        return EXIT_LENDING_LIMIT if status == "lending-limit" else 1
    print(f"text: {how}")
    if args.text_only:
        return 0

    # ---- stage 2
    puzzles = parse_book(text_path)
    quality = {p["book_number"]: p for p in build_quality_report(puzzles)["puzzles"]}
    if args.only:
        puzzles = [p for p in puzzles if p["book_number"] in set(args.only)]
    if args.limit:
        puzzles = puzzles[:args.limit]
    print(f"split: {len(puzzles)} puzzles")
    split_count = len(puzzles)
    # A leaf the corpus already holds is not read again: re-reading a book is
    # how a reader change reaches it, and the filed copy may carry answers.
    held = filed_positions(args.identifier, puzzle_dir) if args.file else {}
    # A filed puzzle is also known by its clues, so a reader that splits the
    # book differently cannot file it a second time under another position.
    held_clues = {c: n for n, c in held.items() if c}
    seen_as = {p["book_number"]: held_clues.get(
        first_clue([c.get("clue") for c in p.get("across") or []])) for p in puzzles}
    # A position whose filed puzzle this split puts somewhere else.
    moved_off = {s for n, s in seen_as.items() if s is not None and s != n}
    fresh, rows = [], {}
    for p in puzzles:
        bn, seen = p["book_number"], seen_as[p["book_number"]]
        if seen is not None and seen != bn:
            print(f"  #{bn} is filed as #{seen}: the split moved", file=sys.stderr)
            rows[bn] = {"book_number": bn, "status": "split-moved", "filed_as": seen}
        elif seen is None and bn in moved_off:
            print(f"  #{bn} is not filed: #{bn}'s id holds another puzzle of "
                  f"this book (the split moved)", file=sys.stderr)
            rows[bn] = {"book_number": bn, "status": "id-taken"}
        if bn not in held and seen is None:
            fresh.append(p)
    if held:
        print(f"skip: {len(puzzles) - len(fresh)} already filed, {len(fresh)} to read")
    puzzles = fresh

    import puzzle_paths
    # Clues-only puzzles go beside the puzzles: the corpus's clues_only/ when
    # filing for real, the scratch tree's otherwise.
    clues_dir = (None if puzzle_paths.in_corpus(puzzle_dir / "x.json")
                 else work / "clues_only")
    clues_filed = 0

    # ---- stage 3a, screening, before any search is paid for
    jobs = []
    # The leaves of this read headed for filing, by their clues: a scan that
    # holds one page twice yields one puzzle at two positions, and the second
    # is the first read again, not a puzzle the corpus lacks.
    from clue_index import ClueIndex
    this_read = ClueIndex()
    for p in puzzles:
        bn = p["book_number"]
        pid = puzzle_id(BOOK_SERIES, book_number(args.identifier, bn))
        across, down, notes, damage = build_spec(p)
        copy = reprint_of(pid, across, down) if args.file else None
        if copy:
            path = book_queue.save_reprint(copy, args.identifier, bn, across, down)
            print(f"  #{bn} reprints {copy}: kept as a reading of it at {path}",
                  file=sys.stderr)
            rows[bn] = {"book_number": bn, "status": "reprint", "reprint_of": copy}
            continue
        twin = reprint_of(pid, across, down, this_read)
        if twin:
            print(f"  #{bn} is {twin} read again: not filed", file=sys.stderr)
            rows[bn] = {"book_number": bn, "status": "duplicate-in-read", "same_as": twin}
            continue
        reasons = list(damage) + grid_verdict.screen_spec(across, down)
        q = quality.get(bn, {})
        if q.get("confidence") == "low":
            reasons.append("the quality pass rated this leaf's OCR confidence low")
        # Both keys are None, not {}, on a puzzle with no across/down split at
        # all — the two Araucaria jigsaw specials print one flat list under a
        # "Method:" heading. That is a real shape in this book, not a bug.
        blank = ((q.get("across") or {}).get("empty_text", 0)
                 + (q.get("down") or {}).get("empty_text", 0))
        if blank:
            reasons.append(f"{blank} clue(s) have no text at all")
        rows[bn] = {"book_number": bn, "setter": p.get("setter"),
                    "lights_recovered": len(across) + len(down),
                    "number_coverage": round(coverage(across, down), 3),
                    "parsing_notes": notes, "reasons": reasons,
                    "warnings": grid_verdict.spec_warnings(across, down),
                    "light_spec": {
                        "across": [[lg[0], lg[1], lg[2]] for lg in across],
                        "down": [[lg[0], lg[1], lg[2]] for lg in down]}}
        if reasons:
            rows[bn]["status"] = "rejected-before-search"
        elif args.file and clues_only.find(
                puzzle_id(BOOK_SERIES, book_number(args.identifier, bn)), clues_dir):
            # Held clues-only already: its answers will place it, so the
            # search (most of a re-read's wall clock) is not paid again; the
            # clues are re-filed from this reading, so a parser fix reaches them.
            rows[bn]["status"] = "held-clues-only"
            this_read.add_keys(pid, leaf_keys(across, down))
            path, problems = file_clues_only({"book_number": bn, "setter": p.get("setter")},
                                             across, down, args.identifier, clues_dir)
            rows[bn]["filed"] = str(path) if path else None
            rows[bn]["filing"] = "re-filed clues-only" if path else "refused clues-only"
            if problems:
                rows[bn]["filing_problems"] = problems
            clues_filed += 1 if path else 0
        else:
            this_read.add_keys(pid, leaf_keys(across, down))
            jobs.append({"book_number": bn, "across": across, "down": down})
    print(f"screen: {len(jobs)} to search, {len(puzzles) - len(jobs)} rejected "
          f"or held clues-only")

    def file_row(bn, row):
        """Stage 4 for one searched puzzle; 1 when it was filed with a grid."""
        nonlocal clues_filed
        row["filed"] = None
        if not args.file:
            row["filing"] = "not attempted (--file not given)"
            return 0
        meta = {"book_number": bn, "setter": row["setter"]}
        spec = next(j for j in jobs if j["book_number"] == bn)
        if row["status"] != "exact-unique":
            # Only the clues are mandatory: a search that did not settle on
            # one grid leaves the answers to settle it.
            if row["status"] == "unparseable":
                return 0
            path, problems = file_clues_only(meta, spec["across"], spec["down"],
                                             args.identifier, clues_dir)
            if path is None:
                row["filing"] = "refused clues-only"
                row["filing_problems"] = problems
            else:
                row["filed"] = str(path)
                row["filing"] = "filed clues-only"
                clues_filed += 1
            return 0
        path, problems = file_unsolved(meta, tuple(row["grids"][0]),
                                        spec["across"], spec["down"],
                                        args.identifier, puzzle_dir)
        if path is None:
            row["filing"] = "refused"
            row["filing_problems"] = problems
            return 0
        row["filed"] = str(path)
        row["filing"] = "filed unsolved"
        return 1

    # ---- stage 3b, the search
    started = time.time()
    filed = 0

    def save_report():
        """report.json as it stands. Written as each search lands, so a run
        killed by its bound leaves every unlanded search marked cut-short."""
        ordered = [dict(rows[k], status=rows[k].get("status", "cut-short"))
                   for k in sorted(rows)]
        report = {"identifier": args.identifier,
                  "text_source": how, "puzzles_found": split_count,
                  "searched": len(jobs), "filed": filed, "filed_clues_only": clues_filed,
                  "elapsed_sec": round(time.time() - started, 1),
                  "thresholds": grid_verdict.THRESHOLDS,
                  "discarded_rules": grid_verdict.DISCARDED,
                  "puzzles": ordered}
        report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
        return ordered

    save_report()
    if jobs:
        for done, r in enumerate(_searched(jobs, args.jobs), 1):
            row = rows[r["book_number"]]
            row.update({k: r[k] for k in
                        ("status", "nodes", "truncated", "wall_clock_exhausted",
                         "elapsed_sec", "conventions_broken")})
            row["verdict_detail"] = r["detail"]
            row["grids"] = r["grids"]
            print(f"  [{done}/{len(jobs)}] #{r['book_number']} "
                  f"lights={row['lights_recovered']} -> {r['status']} "
                  f"nodes={r['nodes']} t={r['elapsed_sec']}s", flush=True)
            # ---- stage 4, as each search lands: a run killed by its
            # timeout keeps every puzzle it had already derived.
            filed += file_row(r["book_number"], row)
            save_report()

    for row in rows.values():
        row.setdefault("grids", [])
        row.setdefault("filed", None)

    # ---- stage 5
    if args.file and args.max_pages is None and not (args.only or args.limit):
        book_queue.record_read(args.identifier, split_count, filed + len(held))
    ordered = save_report()

    from collections import Counter
    tally = Counter(r["status"] for r in ordered)
    print(f"\n{args.identifier}: {len(puzzles)} puzzles, {filed} filed with a grid, "
          f"{clues_filed} clues-only")
    for status, n in tally.most_common():
        print(f"  {n:>3}  {status}")
    unique = [r for r in ordered if r["status"] == "exact-unique"]
    if unique:
        print("  exact-unique: " + ", ".join(f"#{r['book_number']}" for r in unique))
    print(f"report -> {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
