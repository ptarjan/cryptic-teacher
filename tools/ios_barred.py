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

The bars are then set as pairs. Beelzebub's are 180-degree symmetric, so a cell side and its mirror are one bar,
read from both: a side thick and its mirror thin (a stray rule, a number's ink beside the rule: 1996-03-10 read 5
such, its 3-letter downs at 29-33 numbered ahead of the lists' 29-32 across) is no bar. A pair thick on both sides
is a bar, thin on both none; the few between (UNSURE) are decided by the clue lists when read_grid is given
`wanted` (fit_rows): the bar set whose lights lie on the listed clue numbers and lengths, mirror pairs flipped one
at a time while that agrees better.
"""
import sys

import numpy as np
from PIL import Image

import listener_grid as lg
import reconstruct_grid as rg

#: Cells a side of the Beelzebub grid.
CELLS = 12
#: The share of the bars (and their mirrors) that lie 180-degree symmetric for the grid to stand.
BAR_SYMMETRY = 0.8
#: A cell side is a bar at this many times the grid's thin rule (listener_grid.BAR_RATIO), and unsure between
#: UNSURE_LOW (no side of its pair that thick) and UNSURE_HIGH (both sides at least that thick: a bar sure).
UNSURE_LOW, UNSURE_HIGH = 1.25, 2.5
#: A listed clue's light that lies on the grid with another length is worth this share of one that fits, and a
#: light no clue is listed for costs this much (the lists may be short a clue, never many).
LENGTH_OFF, UNLISTED = 0.3, 0.5


def sides_of(rows):
    """{(r, c, "r"|"b")} of the bars the puzzle-format `rows` hold."""
    return {(r, c, s) for r, row in enumerate(rows) for c, ch in enumerate(row)
            for s in "rb" if ch == "+" or ch == s}


def mirror_of(side, n=CELLS):
    """The side 180 degrees round the grid from `side` (r, c, "r"|"b")."""
    r, c, s = side
    return (n - 1 - r, n - 2 - c, s) if s == "r" else (n - 2 - r, n - 1 - c, s)


def symmetry(rows):
    """The share of the bars of `rows` (their mirrors too) that lie 180-degree symmetric, 1.0 for a grid with none."""
    n = len(rows)
    sides = sides_of(rows)
    mirror = {mirror_of(s, n) for s in sides}
    both = sides | mirror
    return len(sides & mirror) / len(both) if both else 1.0


def rows_of(bars, n=CELLS):
    """Puzzle-format rows of the cell sides `bars`."""
    out = []
    for r in range(n):
        row = ""
        for c in range(n):
            right, below = (r, c, "r") in bars, (r, c, "b") in bars
            row += "+" if right and below else "r" if right else "b" if below else "."
        out.append(row)
    return out


def pair_ratios(found):
    """{the first of a side and its mirror: (the thinner's, the thicker's)} widths in thin rules, from a
    listener_grid grid `found`."""
    thin = max(found["thin"], 1.0)
    ratio = {k: v / thin for k, v in found["sides"].items()}
    out = {}
    for k, v in ratio.items():
        m = mirror_of(k)
        out[min(k, m)] = tuple(sorted((v, ratio.get(m, 0.0))))
    return out


def wanted_of(parsed):
    """[(numbers, direction, length or None)] of the clues of a parsed list ({"across": [...], "down": [...]},
    file_archive_org_puzzles.parse): a clue whose number reads one of several ways has them all, a linked clue
    (several numbers) is left out, a length is its one count's letters (None for no count or two readings)."""
    out = []
    for direction, clues in (parsed or {}).items():
        for c in clues:
            tokens = c.get("tokens") or []
            if len(tokens) != 1 or not tokens[0]:
                continue
            counts = {sum(int(x) for x in "".join(ch if ch.isdigit() else " " for ch in e).split()) for e in c.get("enums") or ()}
            out.append((frozenset(tokens[0]), direction, counts.pop() if len(counts) == 1 else None))
    return out


def agreement(rows, wanted):
    """How well the lights of `rows` lie on the listed clues `wanted` (wanted_of): a light of a listed clue's
    number and direction scores 1 at its length, LENGTH_OFF at another, one no clue is listed for costs UNLISTED."""
    lights = rg.light_cells(rows)
    score = 0.0
    for numbers, direction, length in wanted:
        got = [len(cells) for (n, d), cells in lights.items() if d == direction and n in numbers]
        if got:
            score += 1.0 if length is None or length in got else LENGTH_OFF
    for (n, d) in lights:
        if not any(dd == d and n in nn for nn, dd, _ in wanted):
            score -= UNLISTED
    return score


def fit_rows(found, wanted=None):
    """The rows of listener_grid grid `found` with its bars set as mirror pairs (module docstring); with
    `wanted` the unsure pairs flipped where the lights agree better with the listed clues."""
    pairs = pair_ratios(found)
    bars = {p for p, (low, _) in pairs.items() if low >= lg.BAR_RATIO}
    if wanted:
        unsure = [p for p, (low, high) in pairs.items() if high >= UNSURE_LOW and low < UNSURE_HIGH]
        n = len(found["rows"])

        def lay(chosen):
            return rows_of({s for p in chosen for s in (p, mirror_of(p, n))}, n)

        best = agreement(lay(bars), wanted)
        while unsure:
            tries = [(agreement(lay(bars ^ {p}), wanted), -abs(sum(pairs[p]) / 2 - lg.BAR_RATIO), p) for p in unsure]
            score, _, p = max(tries)
            if score <= best + 1e-9:
                break
            bars ^= {p}
            best = score
    n = len(found["rows"])
    return rows_of({s for p in bars for s in (p, mirror_of(p, n))}, n)


#: {(path, size, mtime_ns): the 12x12 grid listener_grid finds in the crop (or its why)}: the clue fit reads the
#: crop again for the lattice's sides after scaled_grid did.
_FOUND = {}
FOUND_MAX = 8


def found_grid(path):
    """(listener_grid grid, None) of the crop at `path`, or (None, why)."""
    import os
    st = os.stat(path)
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _FOUND:
        with Image.open(path) as im:
            gray = np.asarray(im.convert("L"), dtype=np.uint8)
        found = [g for g in lg.find_grids(gray) if g.get("rows") and len(g["rows"]) == CELLS
                 and all(len(r) == CELLS for r in g["rows"])]
        found.sort(key=lambda g: (g["box"][2] - g["box"][0]) * (g["box"][3] - g["box"][1]), reverse=True)
        if len(_FOUND) >= FOUND_MAX:
            _FOUND.pop(next(iter(_FOUND)))
        _FOUND[key] = found[0] if found else None
    got = _FOUND[key]
    return (got, None) if got else (None, "no 12x12 lattice of rules in the crop")


def read_grid(path, wanted=None):
    """(rows, None) or (None, why) for the crop at `path`; `wanted` (wanted_of) lets the clue lists decide the
    unsure bars."""
    found, why = found_grid(path)
    if found is None:
        return None, why
    rows = found["rows"]
    if any("#" in r for r in rows):
        return None, "the barred reading has blocks"
    if not any(set(r) - {"."} for r in rows):
        return None, "the barred reading has no bars"
    share = symmetry(rows)
    if share < BAR_SYMMETRY:
        return None, f"the bars are {share:.2f} symmetric"
    return fit_rows(found, wanted), None


if __name__ == "__main__":
    for p in sys.argv[1:]:
        g, why = read_grid(p)
        print(p, why or "")
        for row in g or ():
            print(" ", row)
