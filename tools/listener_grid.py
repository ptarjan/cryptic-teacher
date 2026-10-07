#!/usr/bin/env python3
"""Read a Listener grid off a scanned magazine page: its size, its black
squares, its bars, and the clue numbers they give.

    python3 tools/listener_grid.py PAGE.png [...]          # print each grid found
    python3 tools/listener_grid.py --check PAGE.png WORDS.json   # numbers against the clue lists

The 1930s Listener prints a barred grid (thick bars between cells) or a
blocked one (No 22), not necessarily square and not necessarily symmetric,
anywhere on a page of prose, and a "Report on Crossword No. N" prints the
filled solution grid of an earlier puzzle. find_grids(gray) reads every grid
on the page:

  1. Rules are ink runs at least RULE_RUN of a typical cell long, across
     (for the horizontal rules) or down (vertical): text and headlines have
     no such runs, a grid's frame, rules, bars and blocks do.
  2. A grid is a patch of joined rules that crosses itself at least
     MIN_CROSSINGS times: an advertisement's box or a column rule does not.
  3. Its rules are the rows (columns) of the patch that rules cover
     RULE_COVER of the way across; a block-filled row covers less. The rule
     positions give the cell edges, each cell its own, so a page that is
     curled or scaled a little stays on the lattice. A rule too faint to
     find is filled in at the pitch.
  4. A cell is a block when ink fills BLOCK_INK of its middle; a cell
     number sits in the corner, a report's letter in the middle leaves more
     paper than that.
  5. A bar is a cell side whose ink, measured across the rule away from the
     corner where numbers print, is thicker than BAR_RATIO times the page's
     thin rule.

A grid is (rows, None) with rows in the puzzle format's one string per row
("#" a block, "r" a bar on the cell's right, "b" one below, "+" both, "."
neither; the outer edge never written), so reconstruct_grid.light_cells, the
one numbering function, gives its lights; or (None, why) when the patch is
no grid this can read. No symmetry is assumed.

For the filer: numbers(rows) is {"across": [...], "down": [...]}, to match
against gale_listener.page_columns' lists (clue_numbers(words)); match(rows,
words) says whether they agree. The grid and its clues may be on different
pages ("For Clues see page 340").
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reconstruct_grid as rg
import trove_grid

#: A rule run is at least this long (pixels at the page's scan size; a 1930
#: cell is 70-120 px).
RULE_RUN = 45
#: A grid crosses itself at least this many times (a 5x5 lattice's 36).
MIN_CROSSINGS = 30
#: A row (column) of the grid's box is a rule when rule ink covers this
#: share of it; blocks cover less, as no row of a crossword is all blocks.
RULE_COVER = 0.7
#: A rule wanders this many pixels either way over a grid's height.
SMEAR = 4
#: A cell is a block when ink covers this share of its middle.
BLOCK_INK = 0.6
#: A cell side is a bar when it is this many times as wide as the thin
#: rule (the sides' median width).
BAR_RATIO = 1.5
#: Cells per side a grid may have.
MIN_CELLS, MAX_CELLS = 4, 27


def runs_at_least(mask, n, axis):
    """The pixels of `mask` lying in a run of at least n Trues along `axis`."""
    m = np.moveaxis(mask, axis, -1).astype(np.int32)
    c = np.concatenate([np.zeros(m.shape[:-1] + (1,), np.int32), np.cumsum(m, -1)], -1)
    full = (c[..., n:] - c[..., :-n]) == n  # window starting at i is all ink
    hit = np.concatenate([np.zeros(m.shape[:-1] + (1,), np.int32),
                          np.cumsum(full.astype(np.int32), -1)], -1)
    # A pixel j is covered when some window starting in [j-n+1, j] is full.
    j = np.arange(m.shape[-1])
    lo, hi = np.clip(j - n + 1, 0, full.shape[-1]), np.clip(j + 1, 0, full.shape[-1])
    out = (hit[..., hi] - hit[..., lo]) > 0
    return np.moveaxis(out, -1, axis)


def smeared(mask, axis, k=SMEAR):
    """`mask` with each True spread k pixels either way along `axis`."""
    out = mask.copy()
    for i in range(1, k + 1):
        out |= np.roll(mask, i, axis) | np.roll(mask, -i, axis)
    return out


def rule_lines(profile, cover):
    """Centres of the runs of `profile` at or above `cover`."""
    on = profile >= cover
    out, start = [], None
    for i, v in enumerate(list(on) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start + i - 1) / 2)
            start = None
    return out


def lattice_lines(found, span):
    """The n+1 rule positions from those found: runs closer than a third of
    the pitch are one rule (a bar's two edges), and a gap of k pitches has
    k-1 faint rules filled in. None when they are no lattice."""
    if len(found) < 2:
        return None
    merged = [found[0]]
    gaps = np.diff(found)
    pitch = float(np.median(gaps[gaps > span / (MAX_CELLS + 1)])) if (gaps > span / (MAX_CELLS + 1)).any() else 0
    if pitch <= 0:
        return None
    for f in found[1:]:
        if f - merged[-1] < pitch / 3:
            merged[-1] = (merged[-1] + f) / 2
        else:
            merged.append(f)
    out = [merged[0]]
    for f in merged[1:]:
        k = round((f - out[-1]) / pitch)
        if k < 1 or abs((f - out[-1]) / pitch - k) > 0.25:
            return None
        out += [out[-1] + (f - out[-1]) * i / k for i in range(1, k)] + [f]
    n = len(out) - 1
    return out if MIN_CELLS <= n <= MAX_CELLS else None


def thickness(dark, at, lo, hi, reach, axis):
    """The rule's width at `at`, measured across it (along `axis`: 1 for a
    vertical rule) over positions lo..hi along it: the area of its mean
    darkness profile over the profile's peak, so a faintly printed rule is
    as wide as a dark one and a bar is wider than both."""
    a, b = max(0, int(at - reach)), int(at + reach) + 1
    lo, hi = int(lo), max(int(lo) + 1, int(hi))
    band = dark[lo:hi, a:b] if axis == 1 else dark[a:b, lo:hi].T
    if not band.size:
        return 0.0
    profile = band.mean(0)
    return float(profile.sum() / max(profile.max(), 0.05))


def read_box(ink, dark, ys, xs):
    """(rows, sides, thin) for the lattice whose rules lie at ys and xs:
    the puzzle-format rows, each cell side's ink mass, and the thin rule's."""
    nr, nc = len(ys) - 1, len(xs) - 1
    blocks = np.zeros((nr, nc), bool)
    for r in range(nr):
        for c in range(nc):
            h, w = ys[r + 1] - ys[r], xs[c + 1] - xs[c]
            mid = ink[int(ys[r] + 0.2 * h):int(ys[r + 1] - 0.2 * h), int(xs[c] + 0.2 * w):int(xs[c + 1] - 0.2 * w)]
            blocks[r, c] = mid.size and mid.mean() >= BLOCK_INK
    pitch = ((ys[-1] - ys[0]) / nr + (xs[-1] - xs[0]) / nc) / 2
    reach = 0.15 * pitch
    sides = {}
    for r in range(nr):
        for c in range(nc):
            if blocks[r, c]:
                continue
            h, w = ys[r + 1] - ys[r], xs[c + 1] - xs[c]
            # Right side, on the rows below where the next cell's number prints.
            if c + 1 < nc and not blocks[r, c + 1]:
                sides[(r, c, "r")] = thickness(dark, xs[c + 1], ys[r] + 0.45 * h, ys[r + 1] - 0.15 * h, reach, 1)
            # Bottom side, on the columns right of where the cell below numbers.
            if r + 1 < nr and not blocks[r + 1, c]:
                sides[(r, c, "b")] = thickness(dark, ys[r + 1], xs[c] + 0.5 * w, xs[c + 1] - 0.15 * w, reach, 0)
    thin = float(np.median(list(sides.values()))) if sides else 0.0
    bar = {k for k, v in sides.items() if v >= BAR_RATIO * max(thin, 1.0)}
    rows = []
    for r in range(nr):
        row = ""
        for c in range(nc):
            if blocks[r, c]:
                row += "#"
                continue
            right, below = (r, c, "r") in bar, (r, c, "b") in bar
            row += "+" if right and below else "r" if right else "b" if below else "."
        rows.append(row)
    return rows, sides, thin


def darkness(gray):
    """Each pixel's share of full ink, 0 on the paper and 1 on the darkest
    print."""
    paper, full = np.percentile(gray, 90), np.percentile(gray, 2)
    return np.clip((paper - gray.astype(float)) / max(1.0, paper - full), 0, 1)


def find_grids(gray):
    """[{"box": (x0, y0, x1, y1), "rows": [...] or None, "why": str or None,
    "filled": share of light cells holding ink}] for every grid on the page
    (a page image as a 2-D uint8 array), top to bottom."""
    cut = trove_grid.otsu(gray)
    ink = gray < cut
    across = runs_at_least(ink, RULE_RUN, 1)
    down = runs_at_least(ink, RULE_RUN, 0)
    step = 4
    lines = trove_grid.pooled(across | down, step)
    crossing = trove_grid.pooled(across, step) & trove_grid.pooled(down, step)
    out = []
    for area, _, _, hh, ww, top, left in trove_grid.components(lines):
        y0, x0, y1, x1 = top * step, left * step, (top + hh) * step, (left + ww) * step
        if crossing[top:top + hh, left:left + ww].sum() < MIN_CROSSINGS or hh < 20 or ww < 20:
            continue
        # A rule a scan has turned a little wanders over a few pixels.
        a = smeared(across[y0:y1, x0:x1], 0)
        d = smeared(down[y0:y1, x0:x1], 1)
        ys = lattice_lines(rule_lines(a.mean(1), RULE_COVER), y1 - y0)
        xs = lattice_lines(rule_lines(d.mean(0), RULE_COVER), x1 - x0)
        found = {"box": (x0, y0, x1, y1), "rows": None, "why": None, "filled": 0.0}
        if ys is None or xs is None:
            found["why"] = "its rules are no regular lattice"
            out.append(found)
            continue
        sub = ink[y0:y1, x0:x1]
        rows, _, _ = read_box(sub, darkness(gray[y0:y1, x0:x1]), ys, xs)
        found["rows"] = rows
        found["lattice"] = ([y + y0 for y in ys], [x + x0 for x in xs])
        found["filled"] = filled_share(sub, ys, xs, rows)
        if not rg.light_cells(rows):
            found["why"] = "no lights"
        out.append(found)
    return sorted(out, key=lambda g: g["box"][1])


def filled_share(ink, ys, xs, rows):
    """Share of light cells with ink in their middle (a report's letters)."""
    got = []
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == "#":
                continue
            h, w = ys[r + 1] - ys[r], xs[c + 1] - xs[c]
            mid = ink[int(ys[r] + 0.3 * h):int(ys[r + 1] - 0.2 * h), int(xs[c] + 0.3 * w):int(xs[c + 1] - 0.3 * w)]
            got.append(mid.size and mid.mean() > 0.08)
    return float(np.mean(got)) if got else 0.0


def numbers(rows):
    """{"across": [...], "down": [...]} the clue numbers the grid gives."""
    out = {"across": [], "down": []}
    for n, d in rg.light_cells(rows):
        out[d].append(n)
    return {d: sorted(v) for d, v in out.items()}


def clue_numbers(words):
    """{"across": [...], "down": [...]} the clue numbers gale_listener's
    clue reader finds in a page's words, or None without two lists."""
    import archive_org_listener as al
    import gale_listener as gl
    cols = gl.page_columns([tuple(w) for w in words])
    if not cols:
        return None
    out = {}
    for d, lines in zip(("across", "down"), cols):
        out[d] = sorted({int(m.group(1)) for line in lines if (m := al.LINE_CLUE.match(line[4]))})
    return out


def match(rows, words):
    """(agrees, detail): do the grid's numbers equal the clue lists'? The
    detail's "clues only" are numbers read in a list that the grid has no
    such light for: a misread bar or a misread clue number. "grid only"
    lights are often clues the list reader dropped."""
    want = clue_numbers(words)
    got = numbers(rows)
    if want is None:
        return False, "no clue lists read"
    diff = {d: {"grid only": sorted(set(got[d]) - set(want[d])), "clues only": sorted(set(want[d]) - set(got[d]))}
            for d in got}
    return got == want, diff


def read_page(path):
    return find_grids(np.asarray(Image.open(path).convert("L"), dtype=np.uint8))


def main(argv):
    check = argv and argv[0] == "--check"
    if check:
        path, words = argv[1], json.loads(Path(argv[2]).read_text())
        paths = [path]
    else:
        paths = argv
    for p in paths:
        for g in read_page(p):
            rows = g["rows"]
            size = f"{len(rows)}x{len(rows[0])}" if rows else "-"
            print(p, g["box"], size, f"filled {g['filled']:.2f}", g["why"] or "")
            for row in rows or ():
                print(" ", row)
            if rows and check:
                ok, diff = match(rows, words)
                print("  numbers", "AGREE" if ok else "DIFFER", re.sub(r"'", "", json.dumps(diff)))


if __name__ == "__main__":
    main(sys.argv[1:])
