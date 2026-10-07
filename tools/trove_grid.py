#!/usr/bin/env python3
"""Read a crossword's black squares off a scanned grid image.

    python3 tools/trove_grid.py ~/.cache/trove/<id>/grid.jpg   # print the grid

read_grid(path) returns (rows, None), each row a string of "#" (block) and
"." (white), or (None, reason) when the picture does not prove one grid:

  1. Otsu's threshold splits ink from paper.
  2. The lattice is the largest connected patch of ink: rules, frame and
     blocks all touch, and a column rule or a headline beside it does not.
  3. Within its bounding box, the white cells are paper patches walled in by
     rules. Each is counted onto a row and column from its neighbours (a
     curled page's pitch drifts), and the rows and columns they fill give the
     cell count. Each cell's centre follows its row's and column's own line
     and the local warp of the patches around it.
  4. A block is solid ink or a halftone stipple whose dots reach every part
     of the cell; a light holds at most its number, a speck or a rule's
     edge. Each cell and its 180-degree mirror are scored together on how
     far ink spreads through their middles, and lights and blocks are the
     two sides of the widest gap between scores: a narrow gap, a light with
     no neighbouring light, lights in two patches, or a light's paper patch
     off its row's or column's line and outside its cell is a refusal, not a
     guess. A cell whose rules a sticker hides is read from its mirror. The
     grid returned is symmetric by construction.

Pure Pillow + numpy; the caller checks the result against the clue list.
"""
import sys
from collections import deque

import numpy as np
from PIL import Image

#: A white patch further than this share of a cell from its row's and
#: column's line, and not inside its cell's rules, refuses the grid.
OFF_LATTICE = 0.25
#: A cell's warp is the median misfit of the patches within this many rows
#: and columns of it, when there are at least WARP_MIN of them.
WARP_REACH = 2
WARP_MIN = 5
#: A cell whose rules show ink along less than this share of its sides is
#: hidden (a sticker over the grid) and read from its mirror.
RULES_SEEN = 0.8
#: Lights and blocks must be split by a gap at least this wide in pair score.
MIN_GAP = 0.15
SIZES = (9, 11, 13, 15, 17, 19, 21, 23, 27)


def otsu(gray):
    """The cut `gray < cut` splits ink from paper at: the darker class's top
    level, or one over it when that level is the class's only one, as on a
    bilevel page (0 and 255 only), so the darker class is never empty."""
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    total, sum_all = hist.sum(), (hist * np.arange(256)).sum()
    best, cut, w0, sum0 = -1.0, 128, 0.0, 0.0
    for t in range(256):
        w0 += hist[t]
        if w0 == 0 or w0 == total:
            continue
        sum0 += t * hist[t]
        m0, m1 = sum0 / w0, (sum_all - sum0) / (total - w0)
        between = w0 * (total - w0) * (m0 - m1) ** 2
        if between > best:
            best, cut = between, t
    return cut if hist[:cut].any() else cut + 1


def largest_component(ink, step=2):
    """Bounding box (x0, y0, x1, y1) of the largest 4-connected ink patch,
    found on a 1/step subsample (rules are thicker than step pixels)."""
    small = ink[::step, ::step]
    h, w = small.shape
    seen = np.zeros_like(small, dtype=bool)
    best, box = 0, None
    ys, xs = np.nonzero(small)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if seen[y0, x0]:
            continue
        seen[y0, x0] = True
        q, n = deque([(y0, x0)]), 0
        bx0 = bx1 = x0
        by0 = by1 = y0
        while q:
            y, x = q.popleft()
            n += 1
            bx0, bx1, by0, by1 = min(bx0, x), max(bx1, x), min(by0, y), max(by1, y)
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < h and 0 <= nx < w and small[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        if n > best:
            best, box = n, (bx0 * step, by0 * step, bx1 * step + step, by1 * step + step)
    return box


def pooled(ink, step=2):
    """Ink max-pooled over step x step blocks, so a rule thinner than a
    block survives the shrink."""
    h, w = (ink.shape[0] // step) * step, (ink.shape[1] // step) * step
    return ink[:h, :w].reshape(h // step, step, w // step, step).any(axis=(1, 3))


def components(mask):
    """[(area, cy, cx, height, width, top, left)] of the 4-connected True
    patches."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if seen[y0, x0]:
            continue
        seen[y0, x0] = True
        q, n, sy, sx = deque([(y0, x0)]), 0, 0, 0
        by0 = by1 = y0
        bx0 = bx1 = x0
        while q:
            y, x = q.popleft()
            n += 1
            sy += y
            sx += x
            by0, by1, bx0, bx1 = min(by0, y), max(by1, y), min(bx0, x), max(bx1, x)
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        out.append((n, sy / n, sx / n, by1 - by0 + 1, bx1 - bx0 + 1, by0, bx0))
    return out


def steps(pos):
    """Each position's index on a line of cells, `pos` counted in cells:
    positions within half a cell of the one before are one cluster, and each
    cluster's index is the last one's plus the gap between their means,
    rounded. Counting from the neighbour, not from the first cell, keeps a
    curled page's few percent of pitch from adding up to a whole cell
    across a 27-cell grid."""
    order = sorted(range(len(pos)), key=lambda i: pos[i])
    groups = [[order[0]]]
    for j in order[1:]:
        if pos[j] - float(np.mean([pos[i] for i in groups[-1]])) > 0.5:
            groups.append([])
        groups[-1].append(j)
    out, index, last = [0] * len(pos), 0, None
    for g in groups:
        mean = float(np.mean([pos[i] for i in g]))
        if last is not None:
            index += max(1, round(mean - last))
        last = mean
        for i in g:
            out[i] = index
    return out


def read_grid(path):
    """(rows, None) or (None, why): see the module docstring."""
    gray = np.asarray(Image.open(path).convert("L"), dtype=np.uint8)
    cut = otsu(gray)
    ink = gray < cut
    # Paper is only what is clearly paper: a faint rule between two white
    # cells is grey, not white, and must still wall them apart.
    not_paper = gray < (cut + float(np.percentile(gray, 90))) / 2
    box = largest_component(ink)
    if box is None:
        return None, "no ink in the image"
    x0, y0, x1, y1 = box
    sub = ink[y0:min(y1, ink.shape[0]), x0:min(x1, ink.shape[1])]
    h, w = sub.shape
    if w < 100 or not 0.85 <= w / h <= 1.18:
        return None, f"the largest ink patch is {w}x{h}, not a square grid"
    step = 2
    walls = pooled(not_paper[y0:y0 + h, x0:x0 + w], step)
    sh, sw = walls.shape
    # The white cells: paper patches walled in by rules. A cell's number
    # leaves it one patch; specks and the margin outside the frame are not
    # cell-sized. Their median side is the pitch less a rule.
    patches = [c for c in components(~walls)
               if c[3] < sh * 0.3 and c[4] < sw * 0.3 and c[0] > 20]
    if len(patches) < 20:
        return None, f"only {len(patches)} white cells found"
    side = float(np.median([max(c[3], c[4]) for c in patches]))
    # Paper caught inside a digit's loop or between a number and a rule.
    # Two lights merged through a faint rule are not cell-sized either: they
    # are read by their ink below, once the lattice is known.
    patches = [c for c in patches if 0.3 * side * side <= c[0] <= 1.6 * side * side
               and max(c[3], c[4]) <= 1.3 * side]
    # Each patch's place on the lattice, counted in cells from the top-left
    # patch, then an affine fit of centre against place: the scan is often
    # turned a fraction of a degree, which a fixed box would read as drift.
    p0 = side * 1.1
    across = [(b[1] - a[1], b[2] - a[2]) for a in patches for b in patches
              if abs(b[1] - a[1]) < 0.3 * p0 and 0.7 * p0 < b[2] - a[2] < 1.4 * p0]
    down = [(b[1] - a[1], b[2] - a[2]) for a in patches for b in patches
            if abs(b[2] - a[2]) < 0.3 * p0 and 0.7 * p0 < b[1] - a[1] < 1.4 * p0]
    if len(across) < 10 or len(down) < 10:
        return None, "too few neighbouring white cells to measure the lattice"
    m = np.array([[np.median([d[0] for d in down]), np.median([d[0] for d in across])],
                  [np.median([d[1] for d in down]), np.median([d[1] for d in across])]])
    seed = min(patches, key=lambda c: c[1] + c[2])
    inv = np.linalg.inv(m)
    frac = [inv @ np.array([c[1] - seed[1], c[2] - seed[2]]) for c in patches]
    place = list(zip(steps([float(f[0]) for f in frac]), steps([float(f[1]) for f in frac])))
    a = np.array([[1, r, c] for r, c in place], dtype=float)
    fy, *_ = np.linalg.lstsq(a, np.array([c[1] for c in patches]), rcond=None)
    fx, *_ = np.linalg.lstsq(a, np.array([c[2] for c in patches]), rcond=None)
    pitch = (fy[1] + fx[2]) / 2
    r0, c0 = min(p[0] for p in place), min(p[1] for p in place)
    place = [(r - r0, c - c0) for r, c in place]
    fy[0] += fy[1] * r0 + fy[2] * c0
    fx[0] += fx[1] * r0 + fx[2] * c0
    rows, cols = max(p[0] for p in place) + 1, max(p[1] for p in place) + 1
    if rows != cols or rows not in SIZES:
        return None, f"the white cells span {rows} rows and {cols} columns"
    n = rows
    if sw / pitch < n - 0.6 or sh / pitch < n - 0.6:
        return None, (f"a {n}x{n} lattice at {pitch * step:.0f}px a cell is "
                      f"larger than the {w}x{h}px frame")

    # A curled page bends the lattice: rows and columns keep their own
    # spacing, so each row's (column's) offset from the affine fit is the
    # mean of its patches', interpolated across a row with no white cell.
    def bend(key, err):
        got = {}
        for (r, c), e in zip(place, err):
            got.setdefault((r, c)[key], []).append(e)
        at = sorted(got)
        return np.interp(np.arange(n), at, [float(np.mean(got[k])) for k in at])

    ey = [c[1] - fy[0] - fy[1] * r - fy[2] * k for c, (r, k) in zip(patches, place)]
    ex = [c[2] - fx[0] - fx[1] * r - fx[2] * k for c, (r, k) in zip(patches, place)]
    dy, dx = bend(0, ey), bend(1, ex)
    # A warped scan bends a row's line along its length, which no offset
    # per row or column follows: each cell also takes the median of what is
    # left over in the patches within WARP_REACH cells of it.
    left = [(r, k, e - dy[r], f - dx[k]) for (r, k), e, f in zip(place, ey, ex)]
    warp = np.zeros((n, n, 2))
    for r in range(n):
        for c in range(n):
            near = [(e, f) for pr, pc, e, f in left
                    if abs(pr - r) <= WARP_REACH and abs(pc - c) <= WARP_REACH]
            if len(near) >= WARP_MIN:
                warp[r, c] = np.median(near, axis=0)

    def centre(r, c):
        return (fy[0] + fy[1] * r + fy[2] * c + dy[r] + warp[r, c, 0],
                fx[0] + fx[1] * r + fx[2] * c + dx[c] + warp[r, c, 1])

    # A block is solid ink or a halftone stipple, which can be pale enough to
    # leave paper patches as big as a light's. What tells them apart is
    # spread: a stipple's dots reach every part of the cell, while a light
    # holds at most its number (top-left, skipped), a speck, or the edge of
    # a rule. Each cell is scored on its middle, cut into tiles a tenth of a
    # pitch: the share of tiles holding ink, times the least share of tile
    # rows and of tile columns holding any.
    big = pitch * step
    t = max(2, round(big / 10))
    half = 0.32 * big
    score = np.zeros((n, n))
    for r in range(n):
        for c in range(n):
            cy, cx = centre(r, c)
            cy, cx = cy * step + y0, cx * step + x0
            m = not_paper[max(0, int(cy - half)):int(cy + half), max(0, int(cx - half)):int(cx + half)]
            th, tw = m.shape[0] // t, m.shape[1] // t
            if not th or not tw:
                return None, f"r{r + 1}c{c + 1} lies outside the image"
            tiles = m[:th * t, :tw * t].reshape(th, t, tw, t).any(axis=(1, 3))
            tiles[:th // 2, :tw // 2] = False
            rest = th * tw - (th // 2) * (tw // 2)
            score[r, c] = tiles.sum() / rest * min(tiles.any(axis=1).mean(), tiles.any(axis=0).mean())
    # A sticker or a smudge over the grid hides its rules: the share of
    # each side of a cell, a band a quarter pitch deep on its rule, that
    # holds ink. A cell whose sides are below RULES_SEEN is not read; its
    # mirror is read for it.
    seen = np.zeros((n, n))
    band = max(1, round(0.12 * big))
    for r in range(n):
        for c in range(n):
            cy, cx = centre(r, c)
            cy, cx = cy * step + y0, cx * step + x0
            near = (max(0, int(cx - 0.35 * big)), int(cx + 0.35 * big),
                    max(0, int(cy - 0.35 * big)), int(cy + 0.35 * big))
            sides = [not_paper[max(0, int(ry - band)):int(ry + band) + 1, near[0]:near[1]].any(axis=0)
                     for ry in (cy - big / 2, cy + big / 2)]
            sides += [not_paper[near[2]:near[3], max(0, int(rx - band)):int(rx + band) + 1].any(axis=1)
                      for rx in (cx - big / 2, cx + big / 2)]
            seen[r, c] = np.mean([sd.mean() if sd.size else 0.0 for sd in sides])
    # The grid is 180-degree symmetric, so a cell and its mirror are one
    # reading: a pale block's score is lifted by its mirror's, and a speck in
    # a light is halved. Lights and blocks are the two sides of the widest
    # gap between pair scores; a narrow one is no split at all.
    hidden = seen < RULES_SEEN
    mirror = score[::-1, ::-1]
    pair = np.where(hidden & ~hidden[::-1, ::-1], mirror,
                    np.where(hidden[::-1, ::-1] & ~hidden, score, (score + mirror) / 2))
    vals = np.unique(pair)
    if len(vals) < 2:
        return None, "every cell reads alike"
    i = int(np.argmax(np.diff(vals)))
    if vals[i + 1] - vals[i] < MIN_GAP:
        return None, f"no clear split between lights and blocks (widest gap {vals[i + 1] - vals[i]:.2f})"
    cut_at = (vals[i] + vals[i + 1]) / 2
    grid = ["".join("#" if pair[r, c] > cut_at else "." for c in range(n)) for r in range(n)]
    for (area, cy, cx, hh, ww, top, lft), (r, c) in zip(patches, place):
        if grid[r][c] == "#":
            continue  # paper between a stipple's dots
        ey, ex = centre(r, c)
        # A stray mark across a light cuts its paper short, its centre off
        # the cell's but its box still inside the cell's rules (give or take
        # a pooled pixel).
        inside = (ey - pitch / 2 - 1 <= top and top + hh <= ey + pitch / 2 + 1
                  and ex - pitch / 2 - 1 <= lft and lft + ww <= ex + pitch / 2 + 1)
        if (abs(cy - ey) > OFF_LATTICE * pitch or abs(cx - ex) > OFF_LATTICE * pitch) and not inside:
            return None, f"the white patch at r{r + 1}c{c + 1} sits off the lattice"
    why = unchecked(grid)
    return (None, why) if why else (grid, None)


def unchecked(grid):
    """Why these blocks are no crossword's, or None: every light cell lies
    in a run of two or more lights across or down, and the lights are one
    connected patch."""
    n = len(grid)
    white = {(r, c) for r in range(n) for c in range(n) if grid[r][c] == "."}
    if not white:
        return "no light cells"
    for r, c in sorted(white):
        if not ({(r, c - 1), (r, c + 1), (r - 1, c), (r + 1, c)} & white):
            return f"the light at r{r + 1}c{c + 1} has no neighbouring light"
    seen, todo = set(), [min(white)]
    while todo:
        r, c = todo.pop()
        if (r, c) in seen:
            continue
        seen.add((r, c))
        todo += [p for p in ((r, c - 1), (r, c + 1), (r - 1, c), (r + 1, c)) if p in white]
    return None if seen == white else "the lights are not one connected patch"


if __name__ == "__main__":
    for p in sys.argv[1:]:
        g, why = read_grid(p)
        print(p, why or "")
        for row in g or ():
            print(" ", row)
