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
