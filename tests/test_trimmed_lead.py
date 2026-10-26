#!/usr/bin/env python3
"""The 1945-49 Times' clue column stands right of a column of small ads, and
lead_column()'s window starts 100px into them: trimmed_lead() moves it to
the gutter, and leaves a window with only a number margin (1950s) alone.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import numpy as np
from PIL import Image

import file_archive_org_puzzles as f

rng = np.random.default_rng(0)


def page(width, height, text_from, text_to, gutter=None):
    """White page with `text_from`..`text_to` inked 30% (rows alike)."""
    a = np.full((height, width), 255, np.uint8)
    a[:, text_from:text_to][rng.random((height, text_to - text_from)) < 0.3] = 0
    return a


# Ads x 100..300, gutter 300..312 (a thin rule at 306), clue text after.
a = page(900, 400, 100, 300)
a[:, 312:600][rng.random((400, 288)) < 0.3] = 0
a[:200, 306] = 0
img = Image.fromarray(a)
x0, top = f.trimmed_lead(img, (600, 100, 900, 400), (140, 100))
assert 308 <= x0 <= 314, x0

# A margin left of numbers (blank 100..140, numbers 150..170, gap, text).
b = np.full((400, 900), 255, np.uint8)
b[:, 150:170][rng.random((400, 20)) < 0.3] = 0
b[:, 190:600][rng.random((400, 410)) < 0.3] = 0
assert f.trimmed_lead(Image.fromarray(b), (600, 100, 900, 400), (100, 100)) == (100, 100)
# 1948-11-10: a 7px heavy rule (inked 55%) between margins of 4px and 5px, each
# under GUTTER_MIN: the rule closes them into one gutter.
c = page(900, 400, 100, 300)
c[:, 304:311][rng.random((400, 7)) < 0.55] = 0
c[:, 316:600][rng.random((400, 284)) < 0.3] = 0
x0, top = f.trimmed_lead(Image.fromarray(c), (600, 100, 900, 400), (140, 100))
assert 312 <= x0 <= 316, x0
print("ok")
