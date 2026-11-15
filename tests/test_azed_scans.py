#!/usr/bin/env python3
# Does tools/azed_scans.py read a page's puzzle number off its headings, take the item's lag between a page's own
# number and the solution it prints, count the weeks to a year, and lay the wanted clue lengths the grid fit uses?
#
#     python3 tests/test_azed_scans.py
#
# Offline: the lines are made up, no scan is opened.
import datetime
import sys

import _path  # puts tools/ on sys.path
import azed_scans as az

fails = 0


def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        print(f"FAIL {what}: want [{want}] got [{got}]")
        fails += 1


def line(text):
    return [(0, 0, 10, 10, w) for w in text.split()]


got = az.readings([line("AZED CROSSWORD"), line("No. 75: PLAIN"), line("AZED No-73: Solution and notes"),
                   line("AZED CROSSWORD No. 1 17: ")])
check("titled", [75], got["titled"])
check("notes", [73], got["notes"])
check("crossed with a split number", [117], got["crossed"])
item = "dli.bengal.10689.23415"
check("lag", 2, az.item_lag(item, {1: {"titled": [75], "notes": [73]}, 2: {"titled": [87], "notes": [85]}}))
check("candidates", {75}, az.candidates(item, {"titled": [75], "notes": [73], "crossed": [200, 4]}, 2))
check("date from weeks", datetime.date(2006, 1, 8), az.puzzle_year(1755, {1740: datetime.date(2005, 9, 25)}))
check("wanted", [(frozenset([4]), "down", 7)],
      az.wanted_of_laid({"4-down": ("Bit of cloth", "7", None), "5-down": ("See 4", None, None)}))
import numpy as np

# A drawn 12x12 grid whose lattice listener_grid miscounted is re-read evenly over its frame.
img = np.full((700, 700), 255, np.uint8)
for i in range(13):
    img[60 + i * 40:62 + i * 40, 50:532] = 0
    img[60:542, 50 + i * 40:52 + i * 40] = 0
img[138:142, 130:170] = 0
even = az.evened(img, {"box": (50, 60, 530, 540), "rows": ["."] * 11, "lattice": None})
check("evened 12x12", (12, 12), (len(even["rows"]), len(even["rows"][0])) if even else None)
check("evened bar", "b", even["rows"][1][2] if even else None)
check("evened refuses a thin strip", None, az.evened(img, {"box": (50, 60, 530, 200), "rows": None}))

sys.exit(1 if fails else 0)
