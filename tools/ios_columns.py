"""The clue columns of an Independent on Sunday Beelzebub page printed before 1995-07-23, fitted to where their ink
really sits.

Those pages set the lists in four narrow columns left of the grid (1994-08-14: x 212-556, 594-939, 975-1320, 1356-1702,
the grid from 1741) or in two wide ones right of a grid at the page's left edge (1992-04-19: x 1033-1580, 1606-2154,
the grid 278-998, the bridge column from 2216), where the 1996 page has two columns left of the grid. The columns are
the bands of x that the words of a wide read cover, the gaps between them the gutters; the band count is read from the
page: leftward from the grid up to the ACROSS heading's band, rightward from the grid up to the DOWN heading's band
(and on while the next band opens on a clue number).
"""
import re

#: The date the pages print the 1996 layout from (the two columns left of the grid and a third under it).
FOUR_END = "1995-07-23"
#: How many grid widths left of the grid, or right of it, the wide read reaches.
REACH = 2.5
#: The narrowest gap, in pixels, between two columns; a band's width may differ from its neighbour's by this share.
GAP = 14
WIDTH = (0.7, 1.35)
MOST = 5
#: The headings are set in capitals: a clue's last word "down" is not one.
ACROSS_HEAD = re.compile(r"ACROSS\W*$")
DOWN_HEAD = re.compile(r"DOWN\W*$")
NUMBERED = re.compile(r"\d{1,2}\s*[A-Za-z(]")


class IosLeft(tuple):
    """A (x0, first edge, foot) tuple of clue columns fitted from the words: `edges` (each column's left edge and the last
    one's right) and `top` (the first line a clue column holds)."""
    edges = ()
    top = 0


def four_layout(paper_key, name, side, grid, width):
    """"left" (the columns left of the grid), "right" (right of it) or None for a page of Gale Independent on Sunday
    `name` (a date) printed before FOUR_END."""
    if paper_key != "galeindysunday" or name >= FOUR_END:
        return None
    gw = grid[2] - grid[0]
    if side == "left" or grid[0] < 1.2 * gw:
        return "right" if width - grid[2] > 1.2 * gw else None
    return "left"


def crop_of(layout, grid, height, width):
    """The (x0, bottom, x1) crop the wide read takes: REACH grid widths left of the grid (to its edge) or right of it."""
    gw = grid[2] - grid[0]
    if layout == "left":
        return max(0, int(grid[0] - REACH * gw)), height, grid[0]
    return grid[2] + 5, height, min(width, int(grid[2] + REACH * gw))


def bands(words, lo, hi, top, bottom):
    """[(x0, x1)] of the bands of x in [lo, hi) the `words` (x0, y0, x1, y1, text; from `top` down) cover, split at gaps of
    GAP pixels or more that at most a few words cross."""
    cover = [0] * max(0, hi - lo)
    for w in words:
        if w[1] < top or w[1] >= bottom:
            continue
        for x in range(max(lo, int(w[0])), min(hi, int(w[2]))):
            cover[x - lo] += 1
    if not cover:
        return []
    least = max(1, max(cover) // 12)
    out, start, last = [], None, None
    for k, c in enumerate(cover):
        if c > least:
            if start is not None and k - last > GAP:
                out.append((lo + start, lo + last + 1))
                start = None
            if start is None:
                start = k
            last = k
    if start is not None:
        out.append((lo + start, lo + last + 1))
    return [b for b in out if b[1] - b[0] >= GAP]


def _head_in(words, band, pattern, top):
    return any(pattern.match(w[4].strip()) and band[0] - 5 <= w[0] < band[1] and w[1] >= top for w in words)


def _first_line(words, band, top):
    """The text of the highest word starting in `band` under `top`."""
    inside = [w for w in words if band[0] - 5 <= w[0] < band[1] and w[1] >= top]
    return min(inside, key=lambda w: (round(w[1] / 20), w[0]))[4] if inside else ""


def fit(words, layout, grid, top, bottom, width):
    """The edges of the fitted columns: the x each starts at and the last one's right edge, from the wide read's
    `words`, or None when the page's bands do not make a clue block (no ACROSS heading's band left of the grid, no DOWN
    heading's right of it)."""
    gx0, _, gx1, _ = grid
    gw = gx1 - gx0
    if layout == "left":
        found = bands(words, max(0, int(gx0 - REACH * gw)), gx0, top, bottom)
        picked = []
        for b in reversed(found):
            if picked and not WIDTH[0] <= (b[1] - b[0]) / (picked[0][1] - picked[0][0]) <= WIDTH[1]:
                break
            picked.insert(0, b)
            if _head_in(words, b, ACROSS_HEAD, top) or len(picked) >= MOST:
                break
        if not picked or not any(_head_in(words, b, ACROSS_HEAD, top) for b in picked):
            return None
        edges = [picked[0][0] - 8] + [(a[1] + b[0]) // 2 for a, b in zip(picked, picked[1:])] + [gx0 - 5]
        return edges
    found = bands(words, gx1 + 5, min(width, int(gx1 + REACH * gw)), top, bottom)
    picked, seen = [], False
    for b in found:
        if picked and not WIDTH[0] <= (b[1] - b[0]) / (picked[0][1] - picked[0][0]) <= WIDTH[1]:
            break
        if seen and not NUMBERED.match(_first_line(words, b, top)):
            break
        picked.append(b)
        seen = seen or _head_in(words, b, DOWN_HEAD, top)
        if len(picked) >= MOST:
            break
    if not picked or not seen:
        return None
    return [gx1 + 5] + [(a[1] + b[0]) // 2 for a, b in zip(picked, picked[1:])] + [picked[-1][1] + 8]
