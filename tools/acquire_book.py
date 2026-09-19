#!/usr/bin/env python3
"""Take a book from an archive.org identifier to filed puzzles with NO model.

    python3 tools/acquire_book.py newpenguinbkguar0000perk --volume 5
    python3 tools/acquire_book.py <id> --volume 7 --file --puzzle-dir puzzles

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
  2. SPLIT. tools/parse_penguin_book.py cuts the book into puzzles and reads
     each one's setter, number and clue list.
  3. GEOMETRY. tools/light_spec.py turns one clue list into a light spec,
     tools/grid_verdict.py throws out the specs that cannot be a 15x15
     before any search happens, tools/reconstruct_grid.py derives the grid,
     and grid_verdict judges the fills that come back.
  4. FILE. tools/file_penguin_puzzle.py --unsolved, called in process, writes
     the puzzle. DEFAULT IS A SCRATCH DIRECTORY, not the corpus: filing is
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

import grid_verdict  # noqa: E402
from light_spec import build_spec, coverage  # noqa: E402
from parse_penguin_book import build_quality_report, parse_book  # noqa: E402
from reconstruct_grid import conventions_broken, reconstruct  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (cryptic-teacher; personal educational use)"}
PUBLIC_TEXT_URL = "https://archive.org/download/{id}/{id}_djvu.txt"
METADATA_URL = "https://archive.org/metadata/{id}"
# Where tools/fetch_ia_book.py leaves what a human borrowed earlier.
FETCHED_TEXT_DIR = Path("/tmp/cryptic-teacher-ia-books")
DEFAULT_OUT = Path("/tmp/acquire_book")

# Stage 1 refused because the ACCOUNT is throttled, not because this book is
# unavailable. Its own exit code so a driver can tell "this book failed" from
# "every remaining book will fail" without parsing a message.
EXIT_LENDING_LIMIT = 3

NODE_BUDGET = 8_000_000   # the budget the vol-5 control was measured under
WALL_SECONDS = 240        # per puzzle, enforced inside the worker
SOLUTION_LIMIT = 40


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

    signal.signal(signal.SIGALRM, _alarm)
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


# ------------------------------------------------------------------ stage 4

def entries_from_grid(grid, across, down):
    """The puzzle's entry list: grid geometry married to the printed clues.

    THE NUMBERS COME FROM THE GRID, never from the OCR. tools/puzzle_integrity
    .py checks that a puzzle's clue numbers are a function of its grid, so the
    derived numbering is the only one that can be right -- and the OCR'd digit,
    which is among the worst-read tokens on the page, is corroboration only.
    Both lists are in printed (row-major) order, which is the order
    tools/light_spec.py emits and the order this walk produces, so they zip.
    """
    rows, cols = len(grid), len(grid[0])
    white = [[c == "." for c in row] for row in grid]
    slots = {"across": [], "down": []}
    number = 0
    for y in range(rows):
        for x in range(cols):
            if not white[y][x]:
                continue
            a = (x == 0 or not white[y][x - 1]) and x + 1 < cols and white[y][x + 1]
            d = (y == 0 or not white[y - 1][x]) and y + 1 < rows and white[y + 1][x]
            if not (a or d):
                continue
            number += 1
            if a:
                run = 1
                while x + run < cols and white[y][x + run]:
                    run += 1
                slots["across"].append((number, x, y, run))
            if d:
                run = 1
                while y + run < rows and white[y + run][x]:
                    run += 1
                slots["down"].append((number, x, y, run))

    entries, problems = [], []
    for direction, spec in (("across", across), ("down", down)):
        got = slots[direction]
        if len(got) != len(spec):
            problems.append(
                f"the grid prints {len(got)} {direction} lights but the clue "
                f"list holds {len(spec)}; they cannot be matched up")
            continue
        for (num, x, y, run), light in zip(got, spec):
            printed = light[3] if len(light) > 3 else None
            clue = (printed or {}).get("clue")
            if not clue:
                problems.append(
                    f"{num}-{direction} has no clue text: it is a linked light "
                    f"whose partner printed no 'See' entry, so the book's own "
                    f"words for it were never on the page this was read from")
                continue
            if run != light[1] and light[1] is not None:
                problems.append(
                    f"{num}-{direction} is {run} cells in the grid but its "
                    f"enumeration reads {light[1]}")
            entries.append({"id": f"{num}-{direction}", "number": num,
                            "direction": direction, "position": {"x": x, "y": y},
                            "length": run, "clue": clue,
                            "enumeration": (printed or {}).get("enumeration")})
    entries.sort(key=lambda e: (e["number"], e["direction"] != "across"))
    return entries, problems


def file_unsolved(puzzle_meta, grid, across, down, series, volume, out_dir,
                  identifier=None):
    """(path, problems). Reuses tools/file_penguin_puzzle.py's own guard, in
    process, so everything it knows about these books -- the id, the null
    date, the absent solutionSource, how a linked group is stored -- is
    applied here too instead of being restated and drifting.

    `identifier` is the archive.org item THIS RUN read. It is checked against
    the volume's own scan in tools/series.py, never used: reading volume 7's
    text while passing --volume 5 is the one mistake this route can make in
    silence, and every puzzle it filed would cite a book it did not come from
    for good.
    """
    from fetch_puzzle import write_puzzle_file
    from file_penguin_puzzle import build as build_penguin
    from series import book_number, scan_identifier

    if identifier:
        number = book_number(series, volume, puzzle_meta["book_number"])
        expected = scan_identifier(series, number)
        if identifier != expected:
            return None, [f"this run is reading {identifier} but {series} "
                          f"volume {volume} is scanned from {expected} in "
                          f"tools/series.py — one of the two is wrong, and "
                          f"filing either way makes the puzzle cite the wrong "
                          f"book"]

    entries, problems = entries_from_grid(grid, across, down)
    if problems:
        return None, problems
    record = {"book_number": puzzle_meta["book_number"],
              "setter": puzzle_meta.get("setter"),
              "puzzle": {"dimensions": {"cols": len(grid[0]), "rows": len(grid)},
                          "entries": entries}}
    try:
        built = build_penguin(record, volume, "unsolved", unsolved=True,
                              series=series)
    except SystemExit as err:
        # file_penguin_puzzle refuses rather than guesses, which is right; a
        # refusal is this puzzle's problem and not the run's, so it is caught,
        # named, and the other puzzles carry on.
        return None, [f"tools/file_penguin_puzzle.py refused it: {err}"]
    except Exception as err:
        return None, [f"tools/file_penguin_puzzle.py raised "
                      f"{type(err).__name__}: {err}"]
    out_dir.mkdir(parents=True, exist_ok=True)
    # puzzle_path() always resolves against the real puzzles/ dir; this out_dir
    # defaults to /tmp and can be pointed anywhere, so it can't stand in here.
    path = out_dir / f"{built['id']}.json"
    write_puzzle_file(path, built, generator="tools/acquire_book.py")
    return path, []


# ------------------------------------------------------------------- driver

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("identifier", help="archive.org item id")
    ap.add_argument("--series", default="penguin",
                    help="which book this is: a series key from tools/series.py "
                         "(default penguin; herald is the other)")
    ap.add_argument("--volume", type=int,
                    help="which volume of that book. Required to file anything: "
                         "the id is <series>-<volume*1000+position>, so volume "
                         "5's No 18 is penguin-5018")
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
    ap.add_argument("--jobs", type=int, default=4, help="parallel reconstructions")
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
        return EXIT_LENDING_LIMIT if status == "lending-limit" else 1
    print(f"text: {how}")

    # ---- stage 2
    puzzles = parse_book(text_path)
    quality = {p["book_number"]: p for p in build_quality_report(puzzles)["puzzles"]}
    if args.only:
        puzzles = [p for p in puzzles if p["book_number"] in set(args.only)]
    if args.limit:
        puzzles = puzzles[:args.limit]
    print(f"split: {len(puzzles)} puzzles")

    # ---- stage 3a, screening, before any search is paid for
    jobs, rows = [], {}
    for p in puzzles:
        bn = p["book_number"]
        across, down, notes, damage = build_spec(p)
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
        else:
            jobs.append({"book_number": bn, "across": across, "down": down})
    print(f"screen: {len(jobs)} to search, {len(puzzles) - len(jobs)} rejected first")

    # ---- stage 3b, the search
    started = time.time()
    if jobs:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for done, r in enumerate(pool.map(_reconstruct_one, jobs), 1):
                row = rows[r["book_number"]]
                row.update({k: r[k] for k in
                            ("status", "nodes", "truncated", "wall_clock_exhausted",
                             "elapsed_sec", "conventions_broken")})
                row["verdict_detail"] = r["detail"]
                row["grids"] = r["grids"]
                print(f"  [{done}/{len(jobs)}] #{r['book_number']} "
                      f"lights={row['lights_recovered']} -> {r['status']} "
                      f"nodes={r['nodes']} t={r['elapsed_sec']}s", flush=True)

    # ---- stage 4
    filed = 0
    for bn, row in rows.items():
        row.setdefault("grids", [])
        row["filed"] = None
        if row["status"] != "exact-unique":
            continue
        if not args.file:
            row["filing"] = "not attempted (--file not given)"
            continue
        if args.volume is None:
            row["filing"] = "refused: --volume is needed to build the number"
            continue
        meta = {"book_number": bn, "setter": row["setter"]}
        spec = next(j for j in jobs if j["book_number"] == bn)
        path, problems = file_unsolved(meta, tuple(row["grids"][0]),
                                        spec["across"], spec["down"],
                                        args.series, args.volume, puzzle_dir,
                                        identifier=args.identifier)
        if path is None:
            row["filing"] = "refused"
            row["filing_problems"] = problems
        else:
            row["filed"] = str(path)
            row["filing"] = "filed unsolved"
            filed += 1

    # ---- stage 5
    ordered = [rows[k] for k in sorted(rows)]
    report = {"identifier": args.identifier, "volume": args.volume,
              "text_source": how, "puzzles_found": len(puzzles),
              "searched": len(jobs), "filed": filed,
              "elapsed_sec": round(time.time() - started, 1),
              "thresholds": grid_verdict.THRESHOLDS,
              "discarded_rules": grid_verdict.DISCARDED,
              "puzzles": ordered}
    report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")

    from collections import Counter
    tally = Counter(r["status"] for r in ordered)
    print(f"\n{args.identifier}: {len(puzzles)} puzzles, {filed} filed")
    for status, n in tally.most_common():
        print(f"  {n:>3}  {status}")
    unique = [r for r in ordered if r["status"] == "exact-unique"]
    if unique:
        print("  exact-unique: " + ", ".join(f"#{r['book_number']}" for r in unique))
    print(f"report -> {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
