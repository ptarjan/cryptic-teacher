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

# a column's far edge has print on its left only
far = cw.edge_candidates(img, (0, 0, 900, 400), 790, side="left")
assert far[0] == 790 and len(far) > 1 and all(x != 790 for x in far[1:]), far
assert cw.edge_candidates(img, (0, 0, 900, 400), 790, reach=100) == [790]

assert cw.poor({"refused": "x", "cause": "no-reading-parses"})
assert not cw.poor({"refused": "x", "cause": "not-a-grid"})
assert cw.poor({"lights": 30, "agreed": 20})
assert cw.poor({"lights": 30, "agreed": 30, "imageDisagrees": "why"})
assert not cw.poor({"lights": 30, "agreed": 30, "imageDisagrees": "why"}, image_ok=True)
assert cw.poor({"lights": 30, "agreed": 20, "imageDisagrees": "why"}, image_ok=True)
assert cw.poor({"lights": 30, "agreed": 30, "blank": ["1-across"] * 6})
assert not cw.poor({"lights": 30, "agreed": 30, "blank": ["1-across"]})
assert cw.score({"agreed": 5}, None) < cw.score({"agreed": 1}, {})

# foreign_edge: the 2005-11-26 Times clue window (its RapidOCR boxes) ended at
# 1914, 90px inside the advert beside DOWN; the DOWN clues end by 1791, the
# advert's cut line ends start at 1824, a banner under the clues crosses the gap.
down = [(1356, 2409, 1719, 2435, "20 Raise sympathy with attitude (6)"),
        (1356, 2433, 1766, 2459, "22 Some ivory whisks utilised selectively"),
        (1355, 2480, 1690, 2508, "24 Thick cushion for nestling (5)"),
        (1355, 2504, 1775, 2532, "25 Chest rising under old ladies' fingers (4)"),
        (1358, 2165, 1791, 2204, "9 Small winger in school is a pain for the")]
advert = [(1824, 2324, 1913, 2348, "The Tim"), (1824, 2396, 1913, 2419, "Books Fi"),
          (1824, 2468, 1913, 2492, "Times re"), (1824, 2491, 1913, 2514, "15% disc")]
banner = [(1032, 2654, 1908, 2686, "75 Years of The Times Crossword is now available")]
x = cw.foreign_edge(down + advert + banner, 1914, 144)
assert x is not None and 1791 < x < 1824, x
# no print past a gap: nothing cut; one cut box alone is a speck
assert cw.foreign_edge(down, 1914, 144) is None
assert cw.foreign_edge(down + advert[:1], 1914, 144) is None
# a box crossing the gap level with the advert closes it
assert cw.foreign_edge(down + advert + [(1360, 2400, 1913, 2420, "20 Raise sympathy Books Fi")], 1914, 144) is None
# a window ending inside a clue column: its cut boxes open on clue numbers
assert cw.foreign_edge(down + [(1830, 2324, 1913, 2348, "20 Botch"), (1830, 2396, 1913, 2419, "25 Thro")],
                       1914, 144) is None
print("ok")
