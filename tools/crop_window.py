"""Clue-column windows chosen from the page's own ink, and the check that a
crop read as a clue column.

Every window the archive filer cuts is derived from fixed offsets (a title's
centre, a grid's edge, a share of its width) and so is right only for the
layout the offset was measured on; the 1945-49 Times' window began 100px
inside a column of small ads. What is true of every layout is that a
column of print is bounded by gutters, so a window edge is a gutter, and
that a crop that holds a clue column reads as numbered clues that lie on the
grid. This module is the first: gutters() finds them in the ink profile
(trimmed_lead's rule, for any span), edge_candidates() lists the ones near an
edge in order of nearness. The second is poor(), the verdict test the
filer's fallback uses to try the next candidate window before the VLM.
"""
import re

#: Ink share of a pixel column under which it is a gutter's; the narrowest
#: gutter (pixels, at a 4300px page); the widest rule a gutter may hold.
INK, MIN_WIDTH, RULE = 0.1, 6, 5
#: The print beside a gutter: pixel columns looked at, their mean ink, and
#: the share of them inked at all (a margin before numbers is blank in part).
SIDE, DENSE, SOLID = 40, 0.12, 0.75
#: A reading is poor when under this share of the grid's lights has a clue,
#: or more than this share is blank.
FILLED, BLANK = 0.85, 0.15


def gutters(img, box, side="left"):
    """[x] (page pixels) of each gutter in `box` (x0, top, x1, bottom): a run
    of MIN_WIDTH or more pixel columns with next to no ink (a rule of RULE
    pixels or less does not break it) that has dense print on its left, or
    on its right, whichever `side` names ("both" asks for both). x is the
    run's middle."""
    import numpy as np
    x0, top, x1, bottom = (int(v) for v in box)
    share = (np.asarray(img.crop((x0, top, x1, bottom)).convert("L")) < 128).mean(axis=0)
    blank = share < INK
    runs, i = [], 0
    while i < len(blank):
        if not blank[i]:
            i += 1
            continue
        j = i
        while j < len(blank) and blank[j]:
            j += 1
        if runs and i - runs[-1][1] <= RULE:
            runs[-1][1] = j
        else:
            runs.append([i, j])
        i = j

    def dense(part):
        return len(part) == SIDE and part.mean() >= DENSE and (part >= INK).mean() >= SOLID

    out = []
    for lo, hi in runs:
        if hi - lo < MIN_WIDTH:
            continue
        left = dense(share[max(lo - SIDE, 0):lo])
        right = dense(share[hi:hi + SIDE])
        if {"left": left, "right": right, "both": left and right}[side]:
            out.append(x0 + (lo + hi) // 2)
    return out


def edge_candidates(img, box, nominal, reach=300, limit=3, side="both"):
    """[x]: `nominal` first, then up to `limit` gutters of `box` within `reach`
    pixels of it (dense print on the sides `side` names; a column's far edge
    has print on its left only), nearest first."""
    near = sorted((x for x in gutters(img, box, side) if abs(x - nominal) <= reach and abs(x - nominal) > MIN_WIDTH),
                  key=lambda x: abs(x - nominal))
    return [nominal] + near[:limit]


#: A word box ending within EDGE pixels of a window's right edge was cut by
#: it; FOREIGN or more such boxes past a clean gap are a column of other
#: print, not a clue's (one alone is a speck or a clipped count).
EDGE, FOREIGN = 3, 2
#: A box's text opening as a numbered clue does ("20 Botch", "1. 'Sweet").
CLUE_OPENING = re.compile(r"\s*\d{1,2}\.?\s+[\"'“‘]?[A-Z][a-z]")


def foreign_edge(words, x1, reach, gap=MIN_WIDTH):
    """The x of the gutter before a column of other print that a window
    ending at `x1` reaches into, read off the window's own reading, or None.
    `words` are its (x0, y0, x1, y1, text) boxes in page pixels. That print
    shows as FOREIGN or more boxes the edge cut (each ends within EDGE of
    `x1`) starting within `reach` of it. Level with them (from the first's
    top to the last's foot: a banner across the page under the clues is no
    neighbour), the gutter is the first run of `gap` or more pixels within
    `reach` of `x1`, left of every cut box, that no box crosses, with print
    left of it; the x is the run's middle. The 2005 Times page's clue window,
    1.45 grids' widths right of the grid, ended 90px inside the "Times
    Crossword Book" advert beside DOWN: "Books Fi" ran into 20 down and 24
    down was laid on no light."""
    lo = int(x1 - reach)
    cut = [w for w in words if w[2] >= x1 - EDGE and lo <= w[0] < x1 - EDGE]
    # A cut box opening on a clue number ("20 Botch") is a clue column the
    # window ends inside: its clues, never a neighbour's print.
    if len(cut) < FOREIGN or any(CLUE_OPENING.match(str(w[4])) for w in cut):
        return None
    top, foot, start = min(w[1] for w in cut), max(w[3] for w in cut), int(min(w[0] for w in cut))
    level = [w for w in words if w[3] > top and w[1] < foot]
    covered = [False] * (start - lo)
    for w in level:
        for x in range(max(lo, int(w[0])), min(start, int(w[2]))):
            covered[x - lo] = True
    x = 0
    while x < len(covered):
        if covered[x]:
            x += 1
            continue
        end = x
        while end < len(covered) and not covered[end]:
            end += 1
        if end - x >= gap and any(w[2] <= lo + x for w in level):
            return lo + (x + end) // 2
        x = end
    return None


#: A window's right edge cuts its own column when CUT or more of a reading's
#: boxes end at it (within EDGE); the column's far edge is sought this far
#: (a share of the window's width) past it.
#: The ink share under which a pixel column past such an edge is clear paper:
#: a ragged column's line ends run thinner than INK, so gutters() would take
#: them for gutter.
CUT, CUT_REACH, CLEAR = 4, 0.15, 0.03


def cut_edge(img, words, box):
    """The x past a window `box` (x0, top, x1, bottom) where the column its
    right edge runs through ends: the middle of the first run of MIN_WIDTH
    or more clear pixel columns (ink under CLEAR) right of x1, within
    CUT_REACH of the window's width, when CUT or more of `words` (one
    reading's (x0, y0, x1, y1, text) boxes, page pixels) end at x1; else
    None. The mid-2014 Times' down column ran ~30px past the window
    RIGHT_SPAN cut it at ("shaking out t", "is s", "part of the y"), a
    rule and a box just beyond: one clue blank as a stray letter, the page
    unfiled."""
    import numpy as np
    x0, top, x1, bottom = (int(v) for v in box)
    if sum(1 for w in words if w[2] >= x1 - EDGE and w[0] < x1 - EDGE) < CUT:
        return None
    end = min(img.width, x1 + int(CUT_REACH * (x1 - x0)))
    if end - x1 < MIN_WIDTH:
        return None
    share = (np.asarray(img.crop((x1, top, end, bottom)).convert("L")) < 128).mean(axis=0)
    clear = share < CLEAR
    i = 0
    while i < len(clear):
        if not clear[i]:
            i += 1
            continue
        j = i
        while j < len(clear) and clear[j]:
            j += 1
        if j - i >= MIN_WIDTH:
            # The middle of the gap: from the clear run's start to the next print or rule.
            k = next((k for k in range(j, len(share)) if share[k] >= INK), len(share))
            return x1 + (i + k) // 2
        i = j
    return None


def poor(verdict, image_ok=False):
    """True when a read_page verdict shows its crop did not hold the clue
    columns: refused as unreadable, no grid-fitting list, or too few of the
    grid's lights filled. `image_ok`: imageDisagrees (the grid image against
    the readings, which another clue window rarely changes) alone is not
    poor, so a VLM pass does not re-ask page after page for it."""
    if verdict.get("refused"):
        return verdict.get("cause") in ("no-reading-parses",)
    lights = verdict.get("lights") or 0
    if (verdict.get("imageDisagrees") and not image_ok) or not lights:
        return True
    return verdict.get("agreed", 0) < FILLED * lights or len(verdict.get("blank") or ()) > BLANK * lights


def score(verdict, puzzle):
    """Orders readings of the same page: a filed puzzle beats none, then the
    more lights filled and the fewer blank."""
    if puzzle is None:
        return (0, 0)
    return (1, verdict.get("agreed", 0) - len(verdict.get("blank") or ()))
