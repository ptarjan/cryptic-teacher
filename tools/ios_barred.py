#!/usr/bin/env python3
"""The Independent on Sunday's Beelzebub grid: a 12x12 barred prize puzzle (no blocks) the blocked-grid reader
(trove_grid) cannot read, its SIZES having no 12 and its cells walled by thin rules all round ("the white cells span
12 rows and 12 columns", ~325 pages of 1990-2000 refused "no reading parses").

    python3 tools/ios_barred.py CROP.png [...]     # print each grid's rows

read_grid(path) reads the crop round the grid (as file_archive_org_puzzles cuts it) with listener_grid's rules, bars
and thickness: rows in the puzzle format ("r" a bar right of the cell, "b" below, "+" both, "." neither), or (None,
why). The grid is accepted when it is 12x12 with no block and its bars lie 180-degree symmetric (BAR_SYMMETRY of
them, as Beelzebub sets them: 11-13 page 1996-03-10 reads 0.95), the two checks standing for a second reader: a
stray rule read for a bar has no mirror.
"""
import sys

import numpy as np
from PIL import Image

import listener_grid as lg

#: Cells a side of the Beelzebub grid.
CELLS = 12
#: The share of the bars (and their mirrors) that lie 180-degree symmetric for the grid to stand.
BAR_SYMMETRY = 0.8


def sides_of(rows):
    """{(r, c, "r"|"b")} of the bars the puzzle-format `rows` hold."""
    return {(r, c, s) for r, row in enumerate(rows) for c, ch in enumerate(row)
            for s in "rb" if ch == "+" or ch == s}


def symmetry(rows):
    """The share of the bars of `rows` (their mirrors too) that lie 180-degree symmetric, 1.0 for a grid with none."""
    n = len(rows)
    sides = sides_of(rows)
    mirror = {(n - 1 - r, n - 2 - c, s) if s == "r" else (n - 2 - r, n - 1 - c, s) for r, c, s in sides}
    both = sides | mirror
    return len(sides & mirror) / len(both) if both else 1.0


def read_grid(path):
    """(rows, None) or (None, why) for the crop at `path`."""
    with Image.open(path) as im:
        gray = np.asarray(im.convert("L"), dtype=np.uint8)
    found = [g for g in lg.find_grids(gray) if g.get("rows") and len(g["rows"]) == CELLS
             and all(len(r) == CELLS for r in g["rows"])]
    if not found:
        return None, "no 12x12 lattice of rules in the crop"
    found.sort(key=lambda g: (g["box"][2] - g["box"][0]) * (g["box"][3] - g["box"][1]), reverse=True)
    rows = found[0]["rows"]
    if any("#" in r for r in rows):
        return None, "the barred reading has blocks"
    if not any(set(r) - {"."} for r in rows):
        return None, "the barred reading has no bars"
    share = symmetry(rows)
    if share < BAR_SYMMETRY:
        return None, f"the bars are {share:.2f} symmetric"
    return rows, None


if __name__ == "__main__":
    for p in sys.argv[1:]:
        g, why = read_grid(p)
        print(p, why or "")
        for row in g or ():
            print(" ", row)
