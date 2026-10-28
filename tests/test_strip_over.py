#!/usr/bin/env python3
"""The 1945-49 Times prints its last clues in a strip between the title and the
grid (1945-07-12: 26 and 27 down): strip_over() finds it and where its columns
split, windows() adds a column for each with its own foot, and columns() reads
the words there (and nothing else's) into them.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import numpy as np
from PIL import Image

import file_archive_org_puzzles as f

rng = np.random.default_rng(0)
grid = (1000, 500, 1720, 1220)
title = (700, 400, 1500, 440)

# Two clues' text over the grid, 1000..1400 and 1500..1720, a rule at 1450.
a = np.full((1300, 2000), 255, np.uint8)
for x0, x1 in ((1000, 1400), (1500, 1720)):
    a[450:490, x0:x1][rng.random((40, x1 - x0)) < 0.3] = 0
a[445:495, 1450] = 0
img = Image.fromarray(a)
strip = f.strip_over(img, grid, title, "1945")
assert strip and strip[0] == 438 and strip[1] == 497, strip
assert len(strip[2]) == 1 and 1405 <= strip[2][0] <= 1495, strip
# The 1940-44 Times sets its down list's tail there too (10-28: 1942-06-20's 22-27 down, STRIP_TAIL).
assert f.strip_over(img, grid, title, "1942") == strip
# Another year's page has none; nor one with no ink between title and grid.
assert f.strip_over(img, grid, title, "1951") is None
assert f.strip_over(img, grid, title, "1939") is None
assert f.strip_over(Image.fromarray(np.full((1300, 2000), 255, np.uint8)), grid, title, "1945") is None

# A short clue's line end leaves a blank, not a gutter: no rule, no cut.
b = np.full((1300, 2000), 255, np.uint8)
b[450:490, 1000:1300][rng.random((40, 300)) < 0.3] = 0
b[450:490, 1330:1720][rng.random((40, 390)) < 0.3] = 0
assert f.strip_over(Image.fromarray(b), grid, title, "1945")[2] == []

# windows(): the strip's columns come last, each with its foot.
wins = f.windows(grid, strip=strip)
assert wins[:2] == f.windows_of(grid)
assert wins[2:] == [(995, strip[2][0], strip[2][0], 438, 497), (strip[2][0], 1735, 1735, 438, 497)], wins
assert f.windows(grid, strip=strip, above=(400, 1300, 1720)) == f.windows_of(grid, above=(400, 1300, 1720))

# columns(): a clue in the strip is read, the grid's number row below it is not.
lines = [[(1005, 450, 1090, 466, "26"), (1100, 450, 1300, 466, "The blood more stirs")],
         [(1010, 520, 1090, 536, "7")],
         [(1520, 450, 1560, 466, "27"), (1570, 450, 1700, 466, "Old soldier (5).")]]
cols = f.columns(lines, grid, strip=strip)
got = [[ln[4] for ln in c] for c in cols]
assert got[-2] == ["26 The blood more stirs"], got
assert got[-1] == ["27 Old soldier (5)."], got
assert f.columns(lines, grid)[-1] == [] or "27" not in f.columns(lines, grid)[-1][0][4]
print("ok")
