#!/usr/bin/env python3
"""What makes a blocked British cryptic grid legal, and the check that enforces it.

The favicon motif was drawn by eye. It was 180-degree symmetric and looked the
part, but it was not a crossword: eight of its lights were two cells long, and no
British cryptic has a two-letter entry. A solver clocks that instantly, and an
icon is seen by people who have never seen the site.

So no grid here is drawn and trusted. `check()` is the shared rulebook —
tools/make_icons.py runs its 5x5 motif through it, and `mask()` derives a real
grid out of a published puzzle for anything that needs one to compare against.
Drawing a grid freehand is exactly the kind of thing that looks right and isn't.

The social card no longer carries a grid at all (see tools/make_og_card.py: it
shows one clue coming apart instead, which is the thing the site actually does).
The rules outlived the picture, which is why they live in their own module.

Usage:  python3 tools/grid_rules.py [puzzle-number]   # check a real grid passes
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PUZZLE = 30066          # Tramp, 15x15, fully annotated
# One light in accent blue, the way the app highlights the entry you're on.
# A middle row rather than the top one: against the border, row 1 read as a
# banner across the grid instead of as a single answer.
# The card used to light one entry in accent blue; mask() still reports it so a
# future picture can, and so the id is validated against the puzzle.
HIGHLIGHT = "14-across"


def load(number):
    text = (REPO / f"puzzles/{number}.js").read_text(encoding="utf-8")
    body = text.split("/*JSON-START*/", 1)[1].rsplit("/*JSON-END*/", 1)[0]
    return json.loads(body)


def mask(puz):
    """True where a letter goes. Cells no entry passes through are blocks."""
    cols, rows = puz["dimensions"]["cols"], puz["dimensions"]["rows"]
    white = [[False] * cols for _ in range(rows)]
    lit = set()
    for e in puz["entries"]:
        x, y = e["position"]["x"], e["position"]["y"]
        for i in range(e["length"]):
            cx, cy = (x + i, y) if e["direction"] == "across" else (x, y + i)
            white[cy][cx] = True
            if e["id"] == HIGHLIGHT:
                lit.add((cx, cy))
    return white, lit


def check(white):
    """The conventions a blocked British grid obeys. Raises if one is broken.

    A run of one white cell is fine — that is an unchecked square inside the
    perpendicular light. A run of two is not: it would be a two-letter entry.
    """
    rows, cols = len(white), len(white[0])
    problems = []

    for y in range(rows):
        for x in range(cols):
            if white[y][x] != white[rows - 1 - y][cols - 1 - x]:
                problems.append(f"not 180-degree symmetric at ({x},{y})")
                break
        if problems:
            break

    def runs(cells):
        n, out = 0, []
        for c in list(cells) + [False]:
            if c:
                n += 1
            else:
                out.append(n)
                n = 0
        return [r for r in out if r]

    for y in range(rows):
        if 2 in runs(white[y]):
            problems.append(f"row {y + 1} has a two-letter entry")
    for x in range(cols):
        if 2 in runs([white[y][x] for y in range(rows)]):
            problems.append(f"column {x + 1} has a two-letter entry")

    start = next(((x, y) for y in range(rows) for x in range(cols) if white[y][x]), None)
    seen, stack = {start}, [start]
    while stack:
        x, y = stack.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < cols and 0 <= ny < rows and white[ny][nx] and (nx, ny) not in seen:
                seen.add((nx, ny))
                stack.append((nx, ny))
    loose = sum(r.count(True) for r in white) - len(seen)
    if loose:
        problems.append(f"{loose} white cell(s) cut off from the rest of the grid")

    if problems:
        raise SystemExit("og grid is not a legal cryptic grid:\n  " + "\n  ".join(problems))


def main():
    """Prove the rules pass on a grid that is definitely legal — a published one.

    Without this the checker is only ever exercised by the icon motif, and a rule
    written too strictly would show up as a broken icon build rather than as what
    it is: a rule that real crosswords break.
    """
    number = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PUZZLE
    puz = load(number)
    white, _ = mask(puz)
    check(white)
    print(f"puzzle {number}: {len(white[0])}x{len(white)}, checks passed")


if __name__ == "__main__":
    main()
