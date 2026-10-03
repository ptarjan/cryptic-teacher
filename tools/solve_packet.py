#!/usr/bin/env python3
"""Print everything needed to solve a puzzle cold: the clues and the grid's
own constraints, as text a solver can hold in one piece.

Handing a model the raw puzzle file does not work well — the answers a grid
allows are a function of where entries cross, and that lives in x/y positions
scattered across thirty objects. Precomputing the crossing map turns "letter 3
of 1 across is letter 1 of 3 down" from something to be re-derived per clue
into something stated once, which is the difference between the crossings
being used and being ignored.

Nothing here spends inference or touches the network; it is a view of a file
we already have.

Usage: python3 tools/solve_packet.py 30080
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import read_puzzle_file, resolve_puzzle  # noqa: E402
from groups import entry_id  # noqa: E402
from provenance import solution_detail  # noqa: E402


def crossing_map(entries):
    """entry id -> [(my position, other entry id, its position)], 1-based."""
    cells = {}
    for e in entries:
        x, y = e["position"]["x"], e["position"]["y"]
        for i in range(e["length"]):
            cell = (x + i, y) if e["direction"] == "across" else (x, y + i)
            cells.setdefault(cell, []).append((entry_id(e), i))
    cross = {}
    for occupants in cells.values():
        if len(occupants) < 2:
            continue
        for a_id, a_i in occupants:
            for b_id, b_i in occupants:
                if a_id != b_id:
                    cross.setdefault(a_id, []).append((a_i + 1, b_id, b_i + 1))
    return cross


def label(entry):
    return f"{entry['number']}{'A' if entry['direction'] == 'across' else 'D'}"


def packet(puzzle):
    lines = [
        f"{puzzle['name']} — setter {puzzle.get('setter') or 'unknown'}",
        f"grid {puzzle['dimensions']['cols']}x{puzzle['dimensions']['rows']}, "
        f"{len(puzzle['entries'])} entries",
        "",
    ]
    cross = crossing_map(puzzle["entries"])
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    # The answers the paper printed, where it printed some (a scan that kept
    # part of its answer grid): the fill must agree with them. A previous model
    # fill is not shown, since this solve may replace it.
    printed = not solution_detail(puzzle)
    for e in sorted(puzzle["entries"],
                    key=lambda e: (e["direction"], e["number"])):
        lines.append(f"{entry_id(e)}  {label(e)} ({e['length']}) {e['clue'].get('text', '')}")
        if printed and e.get("solution"):
            lines.append(f"    printed answer: {e['solution']}")
        pairs = sorted(cross.get(entry_id(e), []))
        if pairs:
            lines.append("    crossings: " + "; ".join(
                f"pos{i}={label(by_id[other])}pos{j}" for i, other, j in pairs))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("number", help="puzzle id or bare number")
    args = ap.parse_args()
    path = resolve_puzzle(args.number)
    print(packet(read_puzzle_file(path)))


if __name__ == "__main__":
    main()
