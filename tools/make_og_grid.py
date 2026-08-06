#!/usr/bin/env python3
"""Build the social card's grid out of a REAL puzzle, and prove it is legal.

The card used to carry a hand-drawn 5x5 lattice. It was 180-degree symmetric and
looked the part, but it was not a crossword: eight of its lights were two cells
long, and no British cryptic has a two-letter entry. Anyone who solves these
would clock it in the thumbnail — which is the one image the site shows people
who have never been here.

So the grid is no longer drawn. It is derived from a puzzle we actually publish
(the entries give the white squares; everything else is a block), and then
checked against the conventions before it can be written out. Drawing a grid
freehand is exactly the kind of thing that looks right and isn't; deriving it
from a real one cannot be wrong, and the check is there for the day someone
points this at something that isn't a real grid.

Usage:  python3 tools/make_og_grid.py [puzzle-number]   (called by make_og.sh)
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CARD = REPO / "tools" / "og_card.html"
DEFAULT_PUZZLE = 30066          # Tramp, 15x15, fully annotated
# One light in accent blue, the way the app highlights the entry you're on.
# A middle row rather than the top one: against the border, row 1 read as a
# banner across the grid instead of as a single answer.
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
    number = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PUZZLE
    puz = load(number)
    white, lit = mask(puz)
    check(white)

    cols = len(white[0])

    def cls(x, y):
        if not white[y][x]:
            return "c b"
        return "c a" if (x, y) in lit else "c"

    cells = "".join(f'<div class="{cls(x, y)}"></div>'
                    for y in range(len(white)) for x in range(cols))
    block = (f'<!--GRID-START {puz["number"]}-->\n'
             f'  <div class="grid" style="grid-template-columns: repeat({cols}, var(--cell))">'
             f'{cells}</div>\n  <!--GRID-END-->')

    html = CARD.read_text(encoding="utf-8")
    html, n = re.subn(r"<!--GRID-START.*?<!--GRID-END-->", block, html, flags=re.S)
    if n != 1:
        raise SystemExit("og_card.html is missing its <!--GRID-START--> markers")
    CARD.write_text(html, encoding="utf-8")
    print(f"og grid: puzzle {puz['number']}, {cols}x{len(white)}, checks passed")


if __name__ == "__main__":
    main()
