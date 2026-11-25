#!/usr/bin/env python3
# Does the 1950-59 Times split under the grid at the gutter with fewer words crossing it, and does its
# reread reason take only the listed pages?
#
#     python3 tests/test_under_crossing.py
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import file_archive_org_puzzles as fa

fails = 0


def check(name, want, got):
    global fails
    ok = want == got
    print(("  ok: " if ok else "  FAIL: ") + name + ("" if ok else f" (want {want!r:.200}, got {got!r:.200})"))
    fails += not ok


# A grid 720 wide at x 0; its two clue columns split at x 360 (0.5), left words ending at 345, right starting 375.
# The share window (0.25-0.45 = 180-324) holds no gutter, so words cross it wherever it lands.
grid = (0, 100, 720, 400)
rows = []
for k in range(12):
    y = 420 + k * 30
    rows.append([(0, y, 170, y + 20, "a"), (172, y, 345, y + 20, "b"), (375, y, 540, y + 20, "c"), (545, y, 715, y + 20, "d")])
usual = fa.under_gutter(rows, grid)
check("the usual window finds the gutter between the columns", True, 345 < usual < 375)
check("the fifties' window gives way to the usual gutter, fewer words cross it", usual, fa.under_gutter(rows, grid, fa.UNDER_FIFTIES))
# Columns split at 0.4: the fifties' window gutter has no words crossing it, the usual's does (a tie keeps the fifties').
rows = []
for k in range(12):
    y = 420 + k * 30
    rows.append([(0, y, 150, y + 20, "a"), (152, y, 255, y + 20, "b"), (300, y, 480, y + 20, "c"), (482, y, 715, y + 20, "d")])
got = fa.under_gutter(rows, grid, fa.UNDER_FIFTIES)
check("the fifties' gutter stays when it is the one with no crossing words", True, 255 < got < 300)
# The reason takes only listed pages.
import importlib
sys.path.insert(0, os.path.join(ROOT, "tools", "reasons"))
mod = importlib.import_module("20261125_1400_under_crossing")
held = sorted(mod.pages())
check("the list holds date_number pages of 1950-59", True, bool(held) and all("1950" <= p[:4] <= "1959" and "_" in p for p in held))
date, number = held[0].split("_")
row = {"edition": f"GaleTimes{date[:4]}UKEnglish/{date}", "inputs": "x", "scan": {"puzzles": [{"number": int(number)}]},
       "readAt": "2026-01-01T00:00:00+00:00"}
other = dict(row, scan={"puzzles": [{"number": 1}]})
check("a listed page is due unless an older, specific reason has it", not fa.specific_fix_reason(row), bool(mod.due(row)))
check("an unlisted page is not due", False, mod.due(other))
print("FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
