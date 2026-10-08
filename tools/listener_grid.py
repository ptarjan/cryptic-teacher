#!/usr/bin/env python3
"""Read a Listener grid off a scanned magazine page: its size, its black
squares, its bars, and the clue numbers they give.

    python3 tools/listener_grid.py PAGE.png [...]          # print each grid found
    python3 tools/listener_grid.py --check PAGE.png WORDS.json   # numbers against the clue lists
    python3 tools/listener_grid.py --fit PAGE.png [...]    # bars fitted to the printed cell numbers

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
     RULE_COVER of the way across its shape: the patch's outline filled
     in, a rectangle's being its box, a map-shaped grid's (No 3's India,
     No 4's England) the cells within the outline, those off it blocks
     in its rows. The rule
     positions give the cell edges, each cell its own, so a page that is
     curled or scaled a little stays on the lattice. A row (column) mostly
     blocks covers as much as a rule, so a covered run wider than half the
     pitch is such a band and its edges are the rules (No 15's last row is
     9 blocks of 13). A rule too faint to find is filled in at the pitch.
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

A bar printed faint reads as a rule, so the grid's own printed cell numbers
settle the sides whose width is unsure: printed_numbers() reads each cell's
corner (all corners laid out apart in one image, read by NUMBER_READERS) and
fit() sets each unsure side so the numbering agrees, reporting "exact" when
no number both readers read disagrees and they read at least EXACT_COVER of
the lights.

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
#: share of it (or a band of blocks: lattice_lines tells them apart).
RULE_COVER = 0.7
#: A grid's filled outline covering this share of its box is a rectangle's
#: (a faded frame lets the paper into an edge cell or two); a map's (No 3's
#: India, No 4's England) covers well under it.
RECTANGLE = 0.85
#: A rule wanders this many pixels either way over a grid's height.
SMEAR = 4
#: A rule's print breaks for up to this many pixels and stays one run (No
#: 4's England: the 40 cell's left frame breaks for 2 halfway down).
RULE_GAP = 3
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


def bridged(mask, axis, gap=RULE_GAP):
    """`mask` with every break of up to `gap` pixels along `axis` between
    two Trues filled."""
    m = mask
    out = m.copy()
    for a in range(1, gap + 1):
        for b in range(1, gap + 2 - a):
            out |= np.roll(m, a, axis) & np.roll(m, -b, axis)
    return out


def smeared(mask, axis, k=SMEAR):
    """`mask` with each True spread k pixels either way along `axis`."""
    out = mask.copy()
    for i in range(1, k + 1):
        out |= np.roll(mask, i, axis) | np.roll(mask, -i, axis)
    return out


def rule_lines(profile, cover):
    """[(first, last)] of each run of `profile` at or above `cover`."""
    on = profile >= cover
    out, start = [], None
    for i, v in enumerate(list(on) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def lattice_lines(runs, span, smear=SMEAR):
    """The n+1 rule positions from the covered runs (rule_lines'), each
    widened `smear` either way: a run is a rule at its centre, but one wider
    than half the pitch is a band of blocks (a row or column mostly blocks
    covers as much as a rule does), and its two edges are the rules. Runs
    closer than a third of the pitch are one rule (a bar's two edges), and
    a gap of k pitches has k-1 faint rules filled in. None when they are no
    lattice."""
    def gaps_pitch(found):
        gaps = np.diff(found)
        big = gaps[gaps > span / (MAX_CELLS + 1)]
        return float(np.median(big)) if big.size else 0
    if len(runs) < 2:
        return None
    pitch = gaps_pitch([(a + b) / 2 for a, b in runs])
    if pitch <= 0:
        return None
    found = []
    for a, b in runs:
        if b - a - 2 * smear > pitch / 2:
            found += [a + smear, b - smear]
        else:
            found.append((a + b) / 2)
    pitch = gaps_pitch(found)
    if pitch <= 0:
        return None
    merged = [found[0]]
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


def read_box(ink, dark, ys, xs, inside=None):
    """(rows, sides, thin) for the lattice whose rules lie at ys and xs:
    the puzzle-format rows, each cell side's ink mass, and the thin rule's.
    A cell whose middle lies mostly off `inside` (shape()'s mask, the box's
    size) is no cell of the grid, and a block in the rows."""
    nr, nc = len(ys) - 1, len(xs) - 1
    blocks = np.zeros((nr, nc), bool)
    for r in range(nr):
        for c in range(nc):
            h, w = ys[r + 1] - ys[r], xs[c + 1] - xs[c]
            middle = (slice(int(ys[r] + 0.2 * h), int(ys[r + 1] - 0.2 * h)),
                      slice(int(xs[c] + 0.2 * w), int(xs[c + 1] - 0.2 * w)))
            if inside is not None and inside[middle].mean() < 0.5:
                blocks[r, c] = True
                continue
            mid = ink[middle]
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


def grown(mask, r):
    """`mask` widened r pixels every way (a square's reach)."""
    out = mask.copy()
    for _ in range(r):
        step = out.copy()
        step[1:] |= out[:-1]
        step[:-1] |= out[1:]
        step[:, 1:] |= out[:, :-1]
        step[:, :-1] |= out[:, 1:]
        out = step
    return out


def cell_span(patch):
    """The median run of paper between two rules along the rows and
    columns of `patch`: the grid's pitch less a rule."""
    spans = []
    for m in (patch, patch.T):
        for line in m:
            at = np.flatnonzero(line)
            if len(at) > 1:
                d = np.diff(at) - 1
                spans.extend(d[d > 1])
    return int(np.median(spans)) if spans else 0


def shape(patch):
    """The grid's outline filled in: `patch` (its pooled walls) with every
    hole the paper outside cannot reach through an opening a third of a
    cell wide, widened a pixel so a rule's smear stays inside. A frame
    printed with a shorter break stays shut (the outside floods against
    walls grown a sixth of a cell each way, then grows back as far), and a
    cell-wide bay of paper along a map's outline stays open. A rectangle's
    is its box; a map-shaped grid's (No 3's India) leaves the paper around
    the outline out. An outline filling RECTANGLE of the box is a
    rectangle's whose frame has faded for a cell or more, and its shape is
    the box."""
    r = max(1, cell_span(patch) // 6)
    wall = grown(patch, 1 + r)
    out = np.zeros_like(patch)
    out[0], out[-1], out[:, 0], out[:, -1] = ~wall[0], ~wall[-1], ~wall[:, 0], ~wall[:, -1]
    while True:
        more = grown(out, 1) & ~wall
        if (more == out).all():
            break
        out = more
    inside = grown(~(grown(out, r) & ~grown(patch, 1)), 1)
    return inside if inside.mean() < RECTANGLE else np.ones_like(patch)


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
    # The outline's walls: a frame stroke broken for a pixel or two is one.
    walls = trove_grid.pooled(runs_at_least(bridged(ink, 1), RULE_RUN, 1)
                              | runs_at_least(bridged(ink, 0), RULE_RUN, 0), step)
    crossing = trove_grid.pooled(across, step) & trove_grid.pooled(down, step)
    out = []
    for area, _, _, hh, ww, top, left in trove_grid.components(lines):
        y0, x0, y1, x1 = top * step, left * step, (top + hh) * step, (left + ww) * step
        if crossing[top:top + hh, left:left + ww].sum() < MIN_CROSSINGS or hh < 20 or ww < 20:
            continue
        inside = np.repeat(np.repeat(shape(walls[top:top + hh, left:left + ww]), step, 0), step, 1)
        # A rule a scan has turned a little wanders over a few pixels.
        a = smeared(across[y0:y1, x0:x1], 0) & inside
        d = smeared(down[y0:y1, x0:x1], 1) & inside
        ys = lattice_lines(rule_lines(a.sum(1) / np.maximum(inside.sum(1), 1), RULE_COVER), y1 - y0)
        xs = lattice_lines(rule_lines(d.sum(0) / np.maximum(inside.sum(0), 1), RULE_COVER), x1 - x0)
        found = {"box": (x0, y0, x1, y1), "rows": None, "why": None, "filled": 0.0}
        if ys is None or xs is None:
            found["why"] = "its rules are no regular lattice"
            out.append(found)
            continue
        sub = ink[y0:y1, x0:x1]
        rows, sides, thin = read_box(sub, darkness(gray[y0:y1, x0:x1]), ys, xs, inside)
        found["rows"] = rows
        found["sides"], found["thin"] = sides, thin
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


# ------------------------------------------------------------ printed numbers

#: The readers that read the cells' printed numbers (ocr_clues.READERS names).
NUMBER_READERS = ("ch", "en5")
#: A side whose width is this many thin rules either way is one the printed
#: numbers may settle: below LO it is a rule, above HI a bar, whatever they say.
UNSURE = (1.0, 2.4)
#: A disagreement both readers make costs this many of one reader's alone.
AGREED_WEIGHT = 3
#: A grid's numbering is exact when no number both readers read disagrees
#: with it and they agree on at least this share of its lights.
EXACT_COVER = 0.5


#: The rule along a corner's top (left) edge lies within this share of its
#: height (width), allowing for a lattice a few pixels off.
RULE_REACH = 0.35


def edge_rule(share, cover):
    """How many of the leading lines (`share`, each line's ink share) a rule
    takes: through the last of the first run at or above `cover`, if it
    starts within RULE_REACH of the edge; 0 when none does."""
    reach = max(1, int(RULE_REACH * len(share)))
    on = [i for i in range(reach) if share[i] > cover]
    if not on:
        return 0
    end = on[0]
    while end + 1 < len(share) and share[end + 1] > cover:
        end += 1
    return end + 1


def corner(gray, ys, xs, r, c, cut):
    """Cell (r, c)'s top-left, where its number prints, with the rules along
    its top and left edges painted out, and all beyond them: only a run of
    lines mostly ink touching the edge is a rule, as a two-digit number
    fills most of a small scan's corner too."""
    h, w = ys[r + 1] - ys[r], xs[c + 1] - xs[c]
    a = gray[int(ys[r]):int(ys[r] + 0.5 * h), int(xs[c]):int(xs[c] + 0.62 * w)].copy()
    ink = a < cut
    a[:edge_rule(ink.mean(1), 0.5), :] = 255
    a[:, :edge_rule(ink.mean(0), 0.6)] = 255
    return a


def mosaic(gray, grid):
    """(image, slot) of every open cell's corner laid out as the grid is, a
    corner's width of paper between them so no reader joins two numbers:
    slot(x, y) is the cell a word centred at (x, y) belongs to."""
    ys, xs = grid["lattice"]
    cut = trove_grid.otsu(gray)
    rows = grid["rows"]
    tiles = {(r, c): corner(gray, ys, xs, r, c, cut)
             for r, row in enumerate(rows) for c, ch in enumerate(row) if ch != "#"}
    th = max(t.shape[0] for t in tiles.values())
    tw = max(t.shape[1] for t in tiles.values())
    out = np.full((len(rows) * 2 * th + th, len(rows[0]) * 2 * tw + tw), 255, np.uint8)
    for (r, c), t in tiles.items():
        y, x = r * 2 * th + th // 2, c * 2 * tw + tw // 2
        out[y:y + t.shape[0], x:x + t.shape[1]] = t
    return Image.fromarray(out), lambda x, y: (int((y - th // 2) // (2 * th)), int((x - tw // 2) // (2 * tw)))


def printed_numbers(gray, grid, readers=NUMBER_READERS):
    """{reader: {(r, c): number}} each reader reads in the grid's cells
    (ocr_clues.read_words, the shared clue readers)."""
    import ocr_clues
    img, slot = mosaic(gray, grid)
    out = {}
    for which in readers:
        got = {}
        for x0, y0, x1, y1, t in ocr_clues.read_words(img, which):
            d = re.sub(r"\D", "", t)
            if d and 0 < int(d) < 100:
                got[slot((x0 + x1) / 2, (y0 + y1) / 2)] = int(d)
        out[which] = got
    return out


def starts(rows, shortest=2, reads=None):
    """{(r, c): number} of light_cells' numbering when no light is shorter
    than `shortest` cells: 2 is light_cells' own; a 1930 blocked grid may
    leave its 2-cell runs unnumbered (3). With 3, a 2-cell run is numbered
    still where `reads` ({(r, c): {numbers read}}) holds the next number at
    its start: No 103 clues "10. Last two letters of above" and leaves
    another 2-cell run unnumbered."""
    if shortest == 2:
        return {cells[0]: n for (n, _), cells in rg.light_cells(rows).items()}
    out = {}
    for (_, _), cells in sorted(rg.light_cells(rows).items()):
        if cells[0] in out:
            continue
        if len(cells) >= shortest or len(out) + 1 in (reads or {}).get(cells[0], ()):
            out[cells[0]] = len(out) + 1
    return out


def closed(rows, shortest, keep=()):
    """`rows` with every run shorter than `shortest` barred shut into single
    cells, so light_cells numbers it as a grid that leaves those runs
    unnumbered (listener_puzzles.close_unclued's way: No 15's and No 29's
    two-letter runs are no lights), but a run starting at a cell of `keep`."""
    out = [list(row) for row in rows]
    both = {("r", "b"): "+", ("b", "r"): "+", (".", "r"): "r", (".", "b"): "b"}
    for (_, d), cells in rg.light_cells(rows).items():
        if len(cells) >= shortest or cells[0] in keep:
            continue
        mark = "r" if d == "across" else "b"
        for y, x in cells[:-1]:
            out[y][x] = both.get((out[y][x], mark), out[y][x])
    return ["".join(row) for row in out]


def with_bars(rows, bars):
    return ["".join(ch if ch == "#" else "+" if bars.get((r, c, "r")) and bars.get((r, c, "b"))
                    else "r" if bars.get((r, c, "r")) else "b" if bars.get((r, c, "b")) else "."
                    for c, ch in enumerate(row)) for r, row in enumerate(rows)]


def in_order(got, most):
    """The reads of `got` ({(r, c): number}) that can be printed numbers:
    none above `most` (the grid's open cells, more than it can have lights), and the longest run that
    rises in reading order, as a grid numbers its cells. A stray "1" off a
    rule remnant, or 75 read for 25, falls out of that run; a number read
    in two cells the run could each hold is kept in neither."""
    cells = sorted(c for c, n in got.items() if 0 < n <= most)
    # Longest strictly rising run, also no number below its place in it.
    best = []  # best[i]: the longest rising run ending at cells[i]
    for i, c in enumerate(cells):
        prev = max((best[j] for j in range(i) if got[cells[j]] < got[c]), key=len, default=[])
        best.append(prev + [c])
    keep = max(best, key=len, default=[])
    # A number read in two cells either of which the run could hold (No
    # 17's 40 read 41 beside the real 41) is misread in one, and which
    # cannot be told: neither is kept.
    for c2 in cells:
        if c2 in keep:
            continue
        same = [c for c in keep if got[c] == got[c2]]
        rest = [c for c in keep if c not in same]
        before = max((got[c] for c in rest if c < c2), default=0)
        after = min((got[c] for c in rest if c > c2), default=most + 1)
        if same and before < got[c2] < after:
            keep = rest
    return {c: got[c] for c in keep}


def fit(grid, printed):
    """{"rows", "shortest", "exact", "agreed", "disagree", "moved"}: the grid with each
    unsure side (UNSURE) set so its numbering agrees with the printed numbers
    (`printed` as printed_numbers gives them), flipping the side the width
    says least, one at a time while that lowers the disagreements. Light
    starts follow from bars and blocks alone, so a misread bar shows as
    numbers out of place. When the numbers leave 2-cell runs unnumbered
    ("shortest" 3; else 2), "rows" has them barred shut (closed()), so
    light_cells numbers "rows" as the page does either way. "moved" are the
    read numbers printed a cell off their light's start."""
    import math
    thin = max(grid["thin"], 1.0)
    q = {k: v / thin for k, v in grid["sides"].items()}
    most = sum(ch != "#" for row in grid["rows"] for ch in row)
    raw = printed
    printed = {k: in_order(got, most) for k, got in printed.items()}
    reads = {}
    for got in printed.values():
        for cell, n in got.items():
            reads.setdefault(cell, set()).add(n)
    agreed = {c: next(iter(v)) for c, v in reads.items()
              if len(v) == 1 and all(c in got for got in printed.values())}
    unsure = [k for k, x in q.items() if UNSURE[0] <= x <= UNSURE[1]]
    edge = math.log(BAR_RATIO)

    def score(bars, mode):
        shortest, by_reads = mode
        st = starts(with_bars(grid["rows"], bars), shortest, reads if by_reads else None)
        bad = sum(AGREED_WEIGHT if c in agreed else 1 for c, v in reads.items() if st.get(c) not in v)
        return bad, sum(abs(math.log(q[k]) - edge) for k in unsure if bars[k] != (q[k] >= BAR_RATIO))

    best = None
    # Numbers left off 2-cell runs: none, all, or all but where a reader
    # read the next number (tried last, so it wins only by fitting better).
    for shortest in ((2, False), (3, False), (3, True)):
        bars = {k: x >= BAR_RATIO for k, x in q.items()}
        now = score(bars, shortest)
        while True:
            tries = [(score(b, shortest), b) for k in unsure for b in [{**bars, k: not bars[k]}]]
            step = min(tries, key=lambda t: t[0], default=None)
            if step is None or step[0] >= now:
                # A bar that ends one light and starts another moves two numbers.
                tries = [(score(b, shortest), b) for i, k in enumerate(unsure) for j in unsure[i + 1:]
                         for b in [{**bars, k: not bars[k], j: not bars[j]}]]
                step = min(tries, key=lambda t: t[0], default=None)
            if step is None or step[0] >= now:
                break
            now, bars = step
        if best is None or now < best[0]:
            best = (now, shortest, bars)
    _, (shortest, by_reads), bars = best
    rows = with_bars(grid["rows"], bars)
    kept = reads if by_reads else None
    # Runs of two are barred shut only when the page leaves one unnumbered:
    # where both numberings are the same the numbers cannot tell, and
    # closing them would drop lights.
    if shortest == 3 and starts(rows, 3, kept) != starts(rows):
        long = {cells[0] for cells in rg.light_cells(rows).values() if len(cells) >= 3}
        rows = closed(rows, 3, set(starts(rows, 3, kept)) - long)
    else:
        shortest = 2
    st = starts(rows)
    at = {n: c for c, n in st.items()}
    disagree, moved = [], []
    for c, n in sorted(agreed.items()):
        if st.get(c) == n:
            continue
        # The printer set the number a cell off its light's start (No 9's 8
        # sits left of the cell the blocks start 8-down at): the start is
        # read blank and c starts nothing, so no bar can mend it.
        to = at.get(n)
        if c not in st and to and to not in reads and abs(to[0] - c[0]) + abs(to[1] - c[1]) == 1:
            moved.append(c)
        else:
            disagree.append(c)
    out = {"rows": rows, "shortest": shortest, "agreed": len(agreed), "disagree": disagree,
           "moved": moved, "exact": not disagree and len(agreed) >= EXACT_COVER * len(st)}
    if not out["exact"] and (by_place := positional(grid["rows"], raw, len(st))):
        # The numbers say nothing of the bars here: each side as its width says.
        return {"rows": with_bars(grid["rows"], {k: x >= BAR_RATIO for k, x in q.items()}), "shortest": 2,
                "agreed": by_place, "disagree": [], "moved": [], "exact": True, "numbering": "position"}
    # A stray number: the fitted bars, or them with one flip back to the
    # width's reading (the search may flip a side chasing the stray).
    tries = [bars] + [{**bars, k: q[k] >= BAR_RATIO} for k in unsure if bars[k] != (q[k] >= BAR_RATIO)]
    if not out["exact"] and shortest == 2 and (got := next(
            (x for b in tries for x in [stray(with_bars(grid["rows"], b), agreed)] if x), None)):
        return {"rows": got[0], "shortest": 2, "agreed": len(agreed), "disagree": [], "moved": [],
                "exact": True, "stray": list(got[1])}
    return out


def stray(rows, agreed):
    """(rows, cell) when the page numbers one cell that starts no light of
    `rows` (each side as its width says) and every agreed number is the
    page's once that cell takes its place in the count: No 3 prints 61 in
    a cell inside 59-down, so its tail runs one ahead of its lights. The
    filer then reads the clue list by the page's numbers, and refuses when
    a clue bears the stray number, which a misread bar would have."""
    if len(agreed) < EXACT_COVER * len(starts(rows)):
        return None
    st = set(starts(rows))
    for c in sorted(set(agreed) - st):
        page = {cell: i + 1 for i, cell in enumerate(sorted(st | {c}))}
        if all(page.get(cell) == n for cell, n in agreed.items()):
            return rows, c
    return None


def positional(rows, printed, lights):
    """How many cell numbers both readers read alike, when the page numbers
    every square by its place (No 0's 9x9: width * row + col + 1) rather
    than its lights' starts, and they fit that exactly: every one of them
    is its cell's place, and they are at least EXACT_COVER of `lights` (the
    starts the bars give) and more than any light-start numbering could
    print, some in cells starting no light. Else 0."""
    width = len(rows[0])
    reads = {}
    for got in printed.values():
        for cell, n in got.items():
            reads.setdefault(cell, set()).add(n)
    agreed = {c: next(iter(v)) for c, v in reads.items()
              if len(v) == 1 and all(c in got for got in printed.values())}
    if not agreed or any(n != width * r + c + 1 for (r, c), n in agreed.items()):
        return 0
    starts_at = {cells[0] for cells in rg.light_cells(rows).values()}
    if len(agreed) < EXACT_COVER * lights or not set(agreed) - starts_at:
        return 0
    return len(agreed)


def read_page(path):
    return find_grids(np.asarray(Image.open(path).convert("L"), dtype=np.uint8))


def main(argv):
    if argv and argv[0] == "--fit":
        for p in argv[1:]:
            gray = np.asarray(Image.open(p).convert("L"), dtype=np.uint8)
            for g in find_grids(gray):
                if not g["rows"] or g["filled"] > 0.5:
                    continue
                f = fit(g, printed_numbers(gray, g))
                print(p, g["box"], "EXACT" if f["exact"] else "NOT EXACT", f"shortest {f['shortest']}",
                      f"agreed {f['agreed']}", "disagree", f["disagree"])
                for row in f["rows"]:
                    print(" ", row)
        return
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
