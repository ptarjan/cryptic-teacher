#!/usr/bin/env python3
"""Read a crossword's black squares off a scanned grid image.

    python3 tools/trove_grid.py ~/.cache/trove/<id>/grid.jpg   # print the grid

read_grid(path) returns (rows, None), each row a string of "#" (block) and
"." (white), or (None, reason) when the picture does not prove one grid:

  1. Otsu's threshold splits ink from paper.
  2. The lattice is the largest connected patch of ink: rules, frame and
     blocks all touch, and a column rule or a headline beside it does not.
  3. Within its bounding box, a grid line is a row (or column) of pixels that
     is ink nearly all the way across. The line centres must fall on one
     regular pitch, which gives the cell count.
  4. Each cell's middle (clear of its rules and of the number in its corner)
     is either mostly ink or mostly paper. A cell in between is a refusal:
     a smudge or a fold, not a guess.

Pure Pillow + numpy; the caller checks the result against the clue list.
"""
import sys
from collections import deque

import numpy as np
from PIL import Image

#: A cell with no white patch is a block only if its middle is this inky.
BLOCK_ABOVE = 0.85
#: ...and a light only if it is at most this inky.
WHITE_BELOW = 0.25
SIZES = (9, 11, 13, 15, 17, 19, 21, 23)


def otsu(gray):
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
    return cut


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
    """[(area, cy, cx, height, width)] of the 4-connected True patches."""
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
        out.append((n, sy / n, sx / n, by1 - by0 + 1, bx1 - bx0 + 1))
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
    small = pooled(sub, step)
    walls = pooled(not_paper[y0:y0 + h, x0:x0 + w], step)
    sh, sw = small.shape
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
    place = [tuple(round(float(v)) for v in inv @ np.array([c[1] - seed[1], c[2] - seed[2]]))
             for c in patches]
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

    def centre(r, c):
        return fy[0] + fy[1] * r + fy[2] * c, fx[0] + fx[1] * r + fx[2] * c

    cells = set()
    for (area, cy, cx, hh, ww), (r, c) in zip(patches, place):
        ey, ex = centre(r, c)
        if abs(cy - ey) > 0.25 * pitch or abs(cx - ex) > 0.25 * pitch:
            return None, f"the white patch at r{r + 1}c{c + 1} sits off the lattice"
        cells.add((r, c))
    grid = []
    for r in range(n):
        row = ""
        for c in range(n):
            # The middle of the cell, clear of its rules and of the number in
            # its top-left corner: solid ink is a block, bare paper a light.
            ey, ex = centre(r, c)
            q = pitch * 0.18
            ey, ex = ey + pitch * 0.08, ex + pitch * 0.08
            share = float(small[max(0, int(ey - q)):int(ey + q) + 1,
                                max(0, int(ex - q)):int(ex + q) + 1].mean())
            if (r, c) in cells or share <= WHITE_BELOW:
                row += "."
            elif share >= BLOCK_ABOVE:
                row += "#"
            else:
                return None, f"r{r + 1}c{c + 1} is neither a light nor a block ({share:.0%} ink)"
        grid.append(row)
    return grid, None


def symmetric(grid):
    n = len(grid)
    return all(grid[y][x] == grid[n - 1 - y][len(grid[0]) - 1 - x]
               for y in range(n) for x in range(len(grid[0])))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        g, why = read_grid(p)
        print(p, why or ("symmetric" if symmetric(g) else "NOT symmetric"))
        for row in g or ():
            print(" ", row)
