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

  1. TEXT. The item's OCR text layer, from a PUBLIC route only: an explicit
     --text, then a file left by an earlier tools/fetch_ia_book.py run, then
     archive.org's public <id>_djvu.txt. This script never logs in, never
     borrows and never works around a restriction; a lending item whose text
     is not publicly served is reported as "text-not-public" and the run
     stops cleanly. Borrowing one is a separate, credentialed, human-run
     decision and it lives in tools/fetch_ia_book.py where it belongs.
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

NODE_BUDGET = 8_000_000   # the budget the vol-5 control was measured under
WALL_SECONDS = 240        # per puzzle, enforced inside the worker
SOLUTION_LIMIT = 40


# ------------------------------------------------------------------ stage 1

def fetch_text(identifier, override=None):
    """(path, how) for the item's OCR text, or (None, why) if there isn't one.

    PUBLIC ROUTES ONLY, in order of what costs archive.org least. A lending
    item's text layer is not publicly served -- <id>_djvu.txt stays HTTP 401
    even for someone holding a loan, which tools/fetch_ia_book.py documents
    in detail -- and that is a stop, not an obstacle to get around.
    """
    if override:
        p = Path(override)
        if not p.exists():
            return None, f"--text {p} does not exist"
        return p, f"--text {p}"

    cached = FETCHED_TEXT_DIR / f"{identifier}.txt"
    if cached.exists() and cached.stat().st_size > 0:
        return cached, (f"{cached}, left by an earlier tools/fetch_ia_book.py "
                        f"run (borrowed and returned by a human, not by this "
                        f"script)")

    url = PUBLIC_TEXT_URL.format(id=identifier)
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
    except urllib.error.HTTPError as err:
        return None, _not_public(identifier, url, f"HTTP {err.code}")
    except urllib.error.URLError as err:
        return None, f"{url} could not be reached: {err.reason}"
    if not body.strip():
        return None, _not_public(identifier, url, "an empty body")

    DEFAULT_OUT.mkdir(parents=True, exist_ok=True)
    out = DEFAULT_OUT / f"{identifier}.txt"
    out.write_bytes(body)
    return out, f"{url} (public text layer, {len(body)} bytes)"


def _not_public(identifier, url, what):
    """Say WHY the text is unavailable, naming the restriction if there is
    one. "404" sends someone to check their spelling; "this is a lending
    item" tells them the only lawful route is a human borrowing it."""
    detail = ""
    try:
        req = urllib.request.Request(METADATA_URL.format(id=identifier), headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            meta = json.loads(r.read()).get("metadata", {})
        if not meta:
            detail = "; archive.org has no item with that identifier"
        elif meta.get("access-restricted-item") in ("true", True):
            detail = ("; this is a lending item — archive.org does not serve a "
                      "public text layer for one, and a loan does not unlock "
                      "it either. The only lawful route is a human running "
                      "tools/fetch_ia_book.py with their own credentials and "
                      "passing the result to --text")
        else:
            detail = ("; the item is public but has no _djvu.txt, so it was "
                      "never OCR'd")
    except Exception:
        detail = ""
    return f"{url} returned {what}{detail}"


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


def file_unsolved(puzzle_meta, grid, across, down, volume, out_dir,
                  identifier=None):
    """(path, problems). Reuses tools/file_penguin_puzzle.py's own guard, in
    process, so everything it knows about these books -- the id, the null
    date, the absent solutionSource, how a linked group is stored -- is
    applied here too instead of being restated and drifting."""
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
        built = build_penguin(record, volume, "unsolved", unsolved=True,
                              identifier=identifier)
    except SystemExit as err:
        # file_penguin_puzzle refuses rather than guesses, which is right; a
        # refusal is this puzzle's problem and not the run's, so it is caught,
        # named, and the other puzzles carry on.
        return None, [f"tools/file_penguin_puzzle.py refused it: {err}"]
    except Exception as err:
        return None, [f"tools/file_penguin_puzzle.py raised "
                      f"{type(err).__name__}: {err}"]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{built['id']}.js"
    write_puzzle_file(path, built, generator="tools/acquire_book.py")
    return path, []


# ------------------------------------------------------------------- driver

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("identifier", help="archive.org item id")
    ap.add_argument("--volume", type=int,
                    help="which Penguin volume this is; the series key is "
                         "penguin<N>. Required to file anything")
    ap.add_argument("--text", help="an OCR .txt already on disk, instead of fetching")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"where the report and any filed puzzles go (default {DEFAULT_OUT})")
    ap.add_argument("--puzzle-dir", type=Path,
                    help="where to file puzzles (default <out>/<identifier>/puzzles, "
                         "a scratch directory; pass puzzles/ to file for real)")
    ap.add_argument("--file", action="store_true",
                    help="actually write puzzle files; without it stages 1-3 and "
                         "5 run and nothing is written but the report")
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
    text_path, how = fetch_text(args.identifier, args.text)
    if text_path is None:
        report = {"identifier": args.identifier, "stage": "text",
                  "status": "text-not-public", "reason": how, "puzzles": []}
        report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"{args.identifier}: no public text layer — {how}")
        print(f"report -> {report_path}")
        return 0
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
            row["filing"] = "refused: --volume is needed to know the series key"
            continue
        meta = {"book_number": bn, "setter": row["setter"]}
        spec = next(j for j in jobs if j["book_number"] == bn)
        path, problems = file_unsolved(meta, tuple(row["grids"][0]),
                                        spec["across"], spec["down"],
                                        args.volume, puzzle_dir,
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
