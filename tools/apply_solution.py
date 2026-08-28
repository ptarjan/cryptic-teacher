#!/usr/bin/env python3
"""Write a solved grid into a puzzle file — but only if the grid checks out.

Saturday prize puzzles publish without answers and only get them about a week
later, which used to mean they sat un-annotatable until the paper caught up.
This is the other route in: a model solves the puzzle cold and the fill lands
here, where it is checked against the grid before anything is written.

The check is the whole point. There is no answer key for these puzzles — that
is why we are solving them — so correctness cannot be verified directly. What
CAN be verified is self-consistency, mechanically and completely:

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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import (PUZZLE_DIR, read_puzzle_file, reindex,  # noqa: E402
                          resolve_puzzle, write_puzzle_file)


def normalise(answer):
    """"POPULAR FRONT" -> "POPULARFRONT". Solutions are stored as bare letters;
    the word breaks live in separatorLocations, which comes from the paper."""
    return re.sub(r"[^A-Z]", "", str(answer).upper())


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
