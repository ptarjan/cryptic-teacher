#!/usr/bin/env python3
"""crop_window finds the gutters between columns of print from the ink
alone, lists the ones near a window's edge nearest first, and judges a
reading's crop: refused, no grid-fitting list or lights left blank is poor.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image

import crop_window as cw

rng = np.random.default_rng(0)
a = np.full((400, 900), 255, np.uint8)
for lo, hi in ((100, 300), (320, 500), (520, 800)):
    a[:, lo:hi][rng.random((400, hi - lo)) < 0.3] = 0
a[:200, 310] = 0  # a rule inside the first gutter
img = Image.fromarray(a)
g = cw.gutters(img, (0, 0, 900, 400), "both")
assert len(g) == 2 and 305 <= g[0] <= 315 and 505 <= g[1] <= 515, g
assert cw.gutters(img, (0, 0, 900, 400), "left")[-1] > 800 - 20
c = cw.edge_candidates(img, (0, 0, 900, 400), 480)
assert c[0] == 480 and c[1] == g[1] and c[2] == g[0], c
assert cw.edge_candidates(img, (0, 0, 900, 400), 410, reach=50) == [410]

assert cw.poor({"refused": "x", "cause": "no-reading-parses"})
assert not cw.poor({"refused": "x", "cause": "not-a-grid"})
assert cw.poor({"lights": 30, "agreed": 20})
assert cw.poor({"lights": 30, "agreed": 30, "imageDisagrees": "why"})
assert cw.poor({"lights": 30, "agreed": 30, "blank": ["1-across"] * 6})
assert not cw.poor({"lights": 30, "agreed": 30, "blank": ["1-across"]})
assert cw.score({"agreed": 5}, None) < cw.score({"agreed": 1}, {})
print("ok")
