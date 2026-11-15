#!/usr/bin/env python3
# Does tools/gale_mephisto_read.py take a Sunday Times Mephisto page's number from its citation (checked
# against the weekly count), find the 12x12 barred grid by its broken rules and thick bars, plan the saved pages
# afresh each call (the fetch is still adding them), and bring a crashed page back as due?
#
#     python3 tests/test_gale_mephisto_read.py
#
# A fake HOME and temp folders: no OCR, no ~/.cache, no tools/data, nothing waited on.
import _path  # noqa: F401  puzzles tools/ on sys.path
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
check("a page with none has none", (None, None), gm.number_of((None, D(2003, 10, 12)), "nothing here"))

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

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
