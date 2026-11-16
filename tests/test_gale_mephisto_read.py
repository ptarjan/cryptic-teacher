#!/usr/bin/env python3
# Does tools/gale_mephisto_read.py take a Sunday Times Mephisto page's number from its citation (checked
# against the weekly count), find the 12x12 barred grid by its broken rules and thick bars, plan the saved pages
# afresh each call (the fetch is still adding them), and bring a crashed page back as due?
#
#     python3 tests/test_gale_mephisto_read.py
#
# A fake HOME and temp folders: no OCR, no ~/.cache, no tools/data, nothing waited on.
import _path  # puts tools/ on sys.path
import atexit
import os
import shutil
import sys
import tempfile
tmp = tempfile.mkdtemp()
atexit.register(shutil.rmtree, tmp, True)
os.environ["HOME"] = tmp
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import datetime
from pathlib import Path
import numpy as np
import gale_mephisto_read as gm

fails = 0


def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")


D = datetime.date

# --- citations and numbers
cite = '"Mephisto 2250." Sunday Times, 5 Oct. 2003, p. 382. The Sunday Times Historical Archive'
check("the citation's number and date", (2250, D(2003, 10, 5)), gm.cite_of(cite))
check("a bare title has no number", (None, D(2003, 10, 12)), gm.cite_of('"Mephisto." Sunday Times, 12 Oct. 2003, p. 394.'))
check("the weekly count", 2264, gm.estimate(D(2004, 1, 11)))
check("a typo'd number is refused", None, gm.checked(2239, D(2005, 4, 10)))
check("citation number taken", (2250, "citation"), gm.number_of((2250, D(2003, 10, 5)), ""))
check("a typo'd citation falls to the solution printed (two back)", (2329, "solution printed"),
      gm.number_of((2239, D(2005, 4, 10)), "Solution to Mephisto 2327: Across"))
check("a page with none falls to the weekly count", (2251, "weekly count"), gm.number_of((None, D(2003, 10, 12)), "nothing here"))

# --- the grid: 13 broken horizontal rules and thick bars on a 12x12 lattice of pitch 40
pitch, x0, y0 = 40, 30, 20
ink = np.zeros((600, 700), bool)
for k in range(13):
    y = y0 + k * pitch
    for a in range(x0 + 5, x0 + 12 * pitch, 110):  # a rule broken every 110 px
        ink[y - 1:y + 2, a:a + 100] = True
    ink[y0:y0 + 12 * pitch + 3, x0 - 1:x0 + 2] = True if k == 0 else ink[y0:y0 + 12 * pitch + 3, x0 - 1:x0 + 2]
for c in (3, 5, 8):  # thick vertical bars one cell tall in different rows
    for r in (1, 4, 7):
        ink[y0 + r * pitch:y0 + (r + 1) * pitch, x0 + c * pitch - 5:x0 + c * pitch + 5] = True
rules = gm.long_rules(ink)
got = gm.lattice_1d([r[0] for r in rules], 20, 100)
check("13 evenly spaced rules found", 13, got and len(got[0]))
check("their spacing", pitch, got and round(got[0][1] - got[0][0]))
found = gm.find_lattice(ink)
check("the lattice found", True, bool(found) and len(found[0]) == 13 and len(found[1]) == 13)
check("its x pitch", True, bool(found) and abs((found[1][12] - found[1][0]) / 12 - pitch) <= 2)
check("no lattice on a blank page", None, gm.find_lattice(np.zeros((300, 300), bool)))

# --- the plan lists the folder each time and skips a page read at VERSION
saved, store = Path(tmp) / "Fetched", Path(tmp) / "store"
saved.mkdir()
(saved / "GALE_FP1.pdf").write_bytes(b"%PDF")
check("one unread page planned", ["mephisto:GALE_FP1.pdf"], [u["rel"] for u in gm.plan(saved, store)])
(saved / "GALE_FP2.pdf").write_bytes(b"%PDF")
check("a page the fetch added is planned too", 2, len(gm.plan(saved, store)))
gm.append_row({"file": "GALE_FP1.pdf", "version": gm.VERSION}, store)
check("a page read at VERSION is not due", ["mephisto:GALE_FP2.pdf"], [u["rel"] for u in gm.plan(saved, store)])
gm.append_row({"file": "GALE_FP2.pdf", "failed": "crashed: X", "attempts": 1, "version": None}, store)
check("a crashed page stays due", ["mephisto:GALE_FP2.pdf"], [u["rel"] for u in gm.plan(saved, store)])
gm.append_row({"file": "GALE_FP1.pdf", "version": gm.VERSION - 1}, store)
check("an older version is read again", 2, len(gm.plan(saved, store)))
refused = {"file": "GALE_FP1.pdf", "version": gm.VERSION, "refused": "grid unread: the bars are 0.10 symmetric"}
check("a grid refusal before the comb search is due", False, gm.read_done(refused))
check("a grid refusal at GRID_FIX stands", True, gm.read_done({**refused, "gridFix": gm.GRID_FIX}))
check("another refusal is not re-read", True, gm.read_done({**refused, "refused": "no Mephisto clue lists found on the page"}))
# the comb search finds a grid drawn with dotted thin rules and thick bars
dotted = np.zeros((1300, 1300), bool)
for i in range(13):
    dotted[100 + 80 * i - 1:100 + 80 * i + 2, 100:1060:3] = True
    dotted[100:1060:3, 100 + 80 * i - 1:100 + 80 * i + 2] = True
combed = gm.comb_lattices(dotted, keep=1)
check("the comb search finds a dotted lattice", True, bool(combed) and abs(combed[0][0][0] - 100) < 6 and abs(combed[0][1][12] - 1060) < 8)

# --- the Down list's head at the left column's foot (1 and 2 Down, under a "Down" heading)
import gale_listener as gl
W = [(100, 1500 + 40 * i, 140, 1530 + 40 * i, str(i)) for i in range(1, 3)]
right = [(600, 100 + 40 * i, 640, 130 + 40 * i, str(3 + i)) for i in range(6)]
check("the right column's left edge", 600, gm.right_edge(right, 1000, 100))
check("too few numbers: no edge", None, gm.right_edge(right[:3], 1000, 100))
foot = [(100, 3000, 180, 3030, "Down"), (600, 3000, 700, 3030, "solution"),
        (100, 3040, 140, 3070, "1"), (150, 3040, 400, 3070, "Marshal"),
        (100, 3080, 300, 3110, "stick"), (100, 3120, 140, 3150, "2"), (150, 3120, 400, 3150, "Could"),
        (100, 3160, 300, 3190, "arrangement"), (100, 3280, 400, 3310, "The editor's decision")]
got = gm.tail_strip(foot, ((90, 1400, 1040, 2950), []), 500, gl)
check("the strip runs from the Down heading to the gap", True, bool(got) and got[1] < 3000 and 3190 < got[3] < 3280)
check("it stops left of the right column", True, bool(got) and got[2] <= 590)
check("no Down heading at the foot: no strip", None, gm.tail_strip(foot[1:], ((90, 1400, 1040, 2950), []), 500, gl))

check("a count's own words are dropped", "bit (11)", gm.WORDS_COUNT.sub(r"(\1)", "bit (11, three words)"))
check("a plain count is left", "bit (5,4)", gm.WORDS_COUNT.sub(r"(\1)", "bit (5,4)"))

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
