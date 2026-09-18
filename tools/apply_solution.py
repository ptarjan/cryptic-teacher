#!/usr/bin/env python3
"""Write a solved grid into a puzzle file — but only if the grid checks out.

Saturday prize puzzles publish without answers and only get them about a week
later, which used to mean they sat un-annotatable until the paper caught up.
This is the other route in: a model solves the puzzle cold and the fill lands
here, where it is checked against the grid before anything is written.

The check is the whole point. There is no answer key for these puzzles — that
is why we are solving them — so correctness cannot be verified directly. What
CAN be verified is self-consistency, mechanically and completely:

  * the grid itself coherent — every light on the board, no two lights in one
    direction on the same cell, one clue number per square, nothing uncrossed
    (check_geometry, which needs no fill and is what puzzle_integrity's GRID
    flag runs over the corpus)
  * every entry answered (a partial fill would publish a half-solved puzzle)
  * every answer the length the grid wants
  * letters only, so "?" and "TBC" can't sneak in as an answer
  * every crossing cell agreeing between its across and its down

A 15x15 has around 60 crossings. A fill that satisfies all of them is not
proven right, but it cannot be casually wrong either: one bad answer normally
breaks three or four crossings. Anything short of a clean sheet writes nothing
at all and exits non-zero, because a puzzle with no answers is honest and a
puzzle with wrong answers is worse than useless to someone learning.

Solutions written this way are marked in the file with solutionSource, so the
site can say whose answers these are, refresh_unsolved keeps re-fetching until
the paper publishes, and the official key — when it lands — grades this fill
automatically instead of quietly replacing it.

Usage:
  python3 tools/apply_solution.py 30080 --fill fill.json --model opus
  python3 tools/apply_solution.py 30080 --fill fill.json --check-only
"""
import argparse
import datetime
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import (PUZZLE_DIR, read_puzzle_file, reindex,  # noqa: E402
                          resolve_puzzle, write_puzzle_file)
from grid_fill import MIN_CHECKED_RATIO  # noqa: E402 — the authoring rulebook's floor


def normalise(answer):
    """"POPULAR FRONT" -> "POPULARFRONT". Solutions are stored as bare letters;
    the word breaks live in separatorLocations, which comes from the paper."""
    return re.sub(r"[^A-Z]", "", str(answer).upper())


def check_geometry(puzzle):
    """Do the entries describe a COHERENT GRID? Returns a list of problems.

    There is no block map in the puzzle format. The geometry IS the entry list:
    a start cell, a direction and a length per light, inside the puzzle's stated
    dimensions, and the shape of the grid has to be read back out of that. So a
    grid that was guessed or built off the wrong template can satisfy every
    length and every crossing and still be nonsense, and nothing else here would
    say so.

    The rules, each of which holds in every one of the 13,397 grids in puzzles/:

      * every light lies on the board, whole
      * no two lights in the same direction share a cell — two acrosses on one
        row means a template with the wrong blocks or a light split in two
      * lights starting in the same square carry the same clue number, because
        they are the same numbered square
      * every light longer than one cell is crossed by a light in the other
        direction; a cryptic has no unchecked word
      * checked cells are at least MIN_CHECKED_RATIO of the grid, the floor
        grid_fill applies to a grid we author ourselves. Imported rather than
        restated: one number, whether the grid arrived from a paper or from us.

    Fill-independent on purpose. An unsolved puzzle has a grid too, and the
    model-solve gate has to settle whether the grid is real BEFORE it weighs a
    fill against it — a fill checked against an incoherent grid proves nothing.
    """
    problems = []
    dims = puzzle.get("dimensions") or {}
    cols, rows = dims.get("cols"), dims.get("rows")
    if not cols or not rows:
        problems.append("the puzzle states no grid dimensions")

    placed, cells, starts = [], defaultdict(list), defaultdict(list)
    for entry in puzzle.get("entries") or []:
        eid = entry.get("id")
        pos = entry.get("position") or {}
        x, y = pos.get("x"), pos.get("y")
        length, direction = entry.get("length"), entry.get("direction")
        if (direction not in ("across", "down")
                or not all(isinstance(v, int) for v in (x, y, length)) or length < 1):
            problems.append(f"{eid}: position {pos}, length {length!r}, "
                            f"direction {direction!r} does not place a light")
            continue
        across = direction == "across"
        far_x, far_y = (x + length - 1, y) if across else (x, y + length - 1)
        if x < 0 or y < 0 or (cols and far_x >= cols) or (rows and far_y >= rows):
            problems.append(f"{eid}: {length} cells {direction} from ({x},{y}) "
                            f"runs off a {cols}x{rows} grid")
            continue
        placed.append(entry)
        starts[(x, y)].append(entry)
        for i in range(length):
            cells[(x + i, y) if across else (x, y + i)].append(entry)

    for cell, occupants in sorted(cells.items()):
        for direction in ("across", "down"):
            same = sorted(e["id"] for e in occupants if e["direction"] == direction)
            if len(same) > 1:
                problems.append(f"cell {cell}: {len(same)} {direction} lights "
                                f"share it — " + ", ".join(same))

    for cell, here in sorted(starts.items()):
        if len({e.get("number") for e in here}) > 1:
            detail = ", ".join(f"{e['id']} is numbered {e.get('number')}"
                               for e in sorted(here, key=lambda e: e["id"]))
            problems.append(f"cell {cell}: one square, {len(here)} clue "
                            f"numbers — {detail}")

    for entry in placed:
        if entry["length"] < 2:
            continue
        x, y = entry["position"]["x"], entry["position"]["y"]
        across = entry["direction"] == "across"
        crossed = any(
            o["direction"] != entry["direction"]
            for i in range(entry["length"])
            for o in cells[(x + i, y) if across else (x, y + i)])
        if not crossed:
            problems.append(f"{entry['id']}: {entry['length']} cells "
                            f"{entry['direction']} from ({x},{y}), crossing nothing")

    if cells:
        checked = sum(1 for occ in cells.values()
                      if len({e["direction"] for e in occ}) > 1)
        ratio = checked / len(cells)
        if ratio < MIN_CHECKED_RATIO:
            problems.append(f"only {ratio:.0%} of the {len(cells)} cells are "
                            f"checked, under the {MIN_CHECKED_RATIO:.0%} a grid needs")
    return problems


def check_fill(puzzle, fill):
    """Return (cells, problems). Never raises on bad input — the caller decides
    what to do with the list, and an empty list is the only thing that writes."""
    problems = []
    by_id = {e["id"]: e for e in puzzle["entries"]}

    for key in fill:
        if key not in by_id:
            problems.append(f"{key}: not an entry in this puzzle")

    cells = {}
    for entry in puzzle["entries"]:
        raw = fill.get(entry["id"])
        if raw is None or not str(raw).strip():
            problems.append(f"{entry['id']}: no answer given")
            continue
        answer = normalise(raw)
        if not answer:
            problems.append(f"{entry['id']}: {raw!r} has no letters in it")
            continue
        if len(answer) != entry["length"]:
            problems.append(
                f"{entry['id']}: {raw!r} is {len(answer)} letters, grid wants {entry['length']}")
            continue
        x, y = entry["position"]["x"], entry["position"]["y"]
        for i, ch in enumerate(answer):
            cell = (x + i, y) if entry["direction"] == "across" else (x, y + i)
            cells.setdefault(cell, {})[entry["id"]] = ch

    crossings = 0
    for cell, occupants in sorted(cells.items()):
        if len(occupants) < 2:
            continue
        crossings += 1
        if len(set(occupants.values())) > 1:
            detail = ", ".join(f"{k}={v}" for k, v in sorted(occupants.items()))
            problems.append(f"cell {cell}: crossing letters disagree — {detail}")
    return cells, crossings, problems


def render_grid(puzzle, cells):
    w, h = puzzle["dimensions"]["cols"], puzzle["dimensions"]["rows"]
    rows = []
    for y in range(h):
        rows.append("".join(
            next(iter(cells[(x, y)].values())) if (x, y) in cells else "."
            for x in range(w)))
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # A puzzle id ("everyman-4166") or the bare number ("4166"), the same pair
    # resolve_puzzle takes and every other tool here accepts. It was type=int,
    # which is what ids looked like before they were namespaced: from then until
    # 2026-08-28 the nightly job solved every unsolved non-Guardian puzzle with a
    # model, passed the id it had, and this exited on `invalid int value` before
    # reading the fill. The solve was paid for and thrown away, nightly.
    ap.add_argument("number", metavar="puzzle",
                    help="puzzle id (everyman-4166) or bare number (4166)")
    ap.add_argument("--fill", required=True,
                    help='JSON file mapping entry id -> answer, e.g. {"1-across": "POPULAR FRONT"}')
    ap.add_argument("--model", default="unknown", help="which model produced the fill")
    ap.add_argument("--check-only", action="store_true",
                    help="report and exit without touching the puzzle file")
    args = ap.parse_args()

    path = resolve_puzzle(args.number)
    puzzle = read_puzzle_file(path)

    fill = json.loads(Path(args.fill).read_text(encoding="utf-8"))
    if not isinstance(fill, dict):
        raise SystemExit("--fill must be a JSON object of entry id -> answer")

    cells, crossings, problems = check_fill(puzzle, fill)
    # The grid before the fill: a fill that agrees with an incoherent grid has
    # agreed with nothing, so nothing may be written into one.
    problems = check_geometry(puzzle) + problems
    print(f"{args.number}: {len(puzzle['entries'])} entries, {len(fill)} answers given, "
          f"{crossings} crossing cells")
    if problems:
        print(f"REJECTED — {len(problems)} problem(s), nothing written:")
        for p in problems[:40]:
            print(f"  {p}")
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more")
        raise SystemExit(1)

    print("all entries answered, all lengths right, every crossing agrees")
    print(render_grid(puzzle, cells))
    if args.check_only:
        return

    if any(e.get("solution") for e in puzzle["entries"]) and "solutionSource" not in puzzle:
        # Refuse to paint over the paper's own answers. Only a puzzle that is
        # unsolved, or already carrying a model fill, can be written here.
        raise SystemExit(f"{args.number} already has published solutions — refusing to overwrite")

    for entry in puzzle["entries"]:
        entry["solution"] = normalise(fill[entry["id"]])
    puzzle["solutionSource"] = {
        "kind": "model",
        "model": args.model,
        "date": datetime.date.today().isoformat(),
        "check": f"{len(puzzle['entries'])} entries, {crossings} crossings, 0 conflicts",
    }
    write_puzzle_file(path, puzzle, generator="tools/apply_solution.py")
    print(f"wrote {len(puzzle['entries'])} solutions into {path} (marked unofficial)")
    reindex()


if __name__ == "__main__":
    main()
