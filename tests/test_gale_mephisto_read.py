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

# --- numbering before 1995: Gale's misread titles, the neighbours' bounds, the page's own printed number
off = 1253 - gm.week(D(1986, 1, 5))
titles = [(d, gm.week(d) + off) for d in (D(1986, 1, 5), D(1986, 1, 12), D(1986, 2, 2))]
check("a title between two agreeing offsets gives the missing week", gm.week(D(1986, 1, 19)) + off, gm.docs_number(D(1986, 1, 19), None, titles))
bad = [(D(1990, 1, 7), gm.week(D(1990, 1, 7)) - 188), (D(1990, 1, 14), 1601), (D(1990, 1, 21), gm.week(D(1990, 1, 21)) - 188)]
check("a misread title (one rising 100 over its neighbours) is dropped", [bad[0], bad[2]], gm.sane_titles(bad))
check("a title falling 90 under the next is dropped", 2, len(gm.sane_titles([(D(2005, 4, 3), gm.week(D(2005, 4, 3)) - 189),
                                                                            (D(2005, 4, 10), 2239), (D(2005, 4, 17), gm.week(D(2005, 4, 17)) - 189)])))
gap = [(D(1965, 9, 26), gm.week(D(1965, 9, 26)) - 110), (D(1985, 12, 1), gm.week(D(1985, 12, 1)) - 187)]
check("20 years with no title: neighbours differ, no number", None, gm.docs_number(D(1975, 3, 9), None, gap))
d75 = D(1975, 3, 9)
check("bounds of the gap", (-188, -109), gm.offset_bounds(d75, gap))
check("printed title number", [826], gm.printed_numbers("Mophisto Crosaword No 826 Across"))
check("last week's solution plus one, the entry form's own", [1122, 1122],
      gm.printed_numbers("SOLUTION TO MEPHISTO 1121 -Selenic and solutions to Mophiste 1122, The Times"))
check("a Times crossword number is not a Mephisto's", [], gm.printed_numbers("CROSSWORD 2907 SOLUTION TO CROSSWORD 2907"))
o = 826 - gm.week(d75)
check("one printed number alone is not sure", (o, False), gm.printed_offset(d75, "Mophisto Crosaword No 826", gap))
check("a near page with the same offset makes it sure", (o, True), gm.printed_offset(d75, "Mophisto Crosaword No 826", gap, {o}))
check("two numbers that agree are sure", (o, True),
      gm.printed_offset(d75, "Mephisto Crossword No 826 solutions to Mephisto 826", gap))
check("a number outside the neighbours' offsets is refused", None, gm.printed_offset(d75, "Mephisto Crossword No 2826", gap))
check("no titled neighbour after: no bounds", None, gm.offset_bounds(D(1999, 1, 3), gap))
near_rows = [{"file": "a", "date": "1975-03-16", "number": 827, "numberFrom": "page printed"},
             {"file": "b", "date": "1975-03-23", "seen": o}, {"file": "c", "date": "1976-03-23", "seen": 5}]
check("near offsets from the ledger", {827 - gm.week(D(1975, 3, 16)), o}, gm.near_offsets(d75, near_rows))
unconf = {"file": "p", "date": "1975-03-09", "version": gm.VERSION, "refused": gm.UNCONFIRMED, "seen": o}
check("an unconfirmed page stays until a neighbour agrees", True, gm.read_done(unconf, {"p": unconf}))
check("it is due once a neighbour has its offset", False, gm.read_done(unconf, {"p": unconf, "b": near_rows[1]}))
stale = {"file": "p", "date": "1975-03-09", "version": gm.VERSION, "refused": gm.UNNUMBERED}
check("a number refusal before NUMBER_FIX is due", False, gm.read_done(stale))
check("a number refusal at NUMBER_FIX inside an offset run is due for RUN_FIX", False,
      gm.read_done({**stale, "numberFix": gm.NUMBER_FIX}))
check("a number refusal at NUMBER_FIX and RUN_FIX stands", True,
      gm.read_done({**stale, "numberFix": gm.NUMBER_FIX, "runFix": gm.RUN_FIX}))
check("outside any run it stands at NUMBER_FIX", True,
      gm.read_done({**stale, "date": "1979-03-09", "numberFix": gm.NUMBER_FIX}))
fixed = {**stale, "numberFix": gm.NUMBER_FIX, "runFix": gm.RUN_FIX}
check("a bridged gap's refusal before BRIDGE_FIX is due", False, gm.read_done({**fixed, "date": "1963-05-05"}))
check("a bridged gap's refusal at BRIDGE_FIX stands", True, gm.read_done({**fixed, "date": "1963-05-05", "bridgeFix": gm.BRIDGE_FIX}))
check("an unbridged gap (1976-02..1978-01) is not re-due", True, gm.read_done({**fixed, "date": "1977-03-06"}))
check("an anchored week's refusal before ANCHOR_FIX is due", False, gm.read_done({**fixed, "date": "1966-03-06"}))
check("an anchored week's refusal at ANCHOR_FIX stands", True,
      gm.read_done({**fixed, "date": "1966-03-06", "anchorFix": gm.ANCHOR_FIX}))
check("an anchored week takes the weekly count", -111, gm.run_offset(D(1966, 3, 6)))
check("the week after a missing Sunday (1979-12-23) is not anchored", None, gm.run_offset(D(1979, 12, 30)))
check("a gap between different offsets is not bridged", None, gm.run_offset(D(1977, 6, 5)))
check("the gap 1961-02-26..1965-07-04 (both ends -110) is bridged", -110, gm.run_offset(D(1963, 5, 5)))
check("the weeks before the first anchor are not", None, gm.run_offset(D(1960, 12, 18)))
check("a bridged page takes the weekly count", gm.week(D(1963, 5, 5)) - 110, gm.run_number(D(1963, 5, 5), ""))
check("a bridged page whose printed number disagrees is refused", None,
      gm.run_number(D(1963, 5, 5), f"Mephisto Crossword No {gm.week(D(1963, 5, 5)) - 100}"))
# offset runs: a page inside one takes the week count plus the run's offset when its printed numbers sit at it or just below
w = gm.week(D(1975, 3, 9))
check("a run holds its dates", -121, gm.run_offset(D(1975, 3, 9)))
check("the weeks the offset fell in have no run", None, gm.run_offset(D(1976, 6, 6)))
check("a page with nothing printed takes the run's number", w - 121, gm.run_number(D(1975, 3, 9), "no number here"))
check("last week's number alone sits one below: taken", w - 121, gm.run_number(D(1975, 3, 9), f"Mephisto Crossword No {w - 122}"))
check("a printed number far off the run refuses", None, gm.run_number(D(1975, 3, 9), f"Mephisto Crossword No {w - 130}"))
check("a number above the run's refuses", None, gm.run_number(D(1975, 3, 9), f"Mephisto Crossword No {w - 120}"))
check("a misread far off the run is ignored beside a number at its offset", w - 121,
      gm.run_number(D(1975, 3, 9), f"Mephisto Crossword No {w - 127} Solution to Mephisto {w - 122}"))
check("only misreads far off, none at the offset: refused", None,
      gm.run_number(D(1975, 3, 9), f"Mephisto Crossword No {w - 127}"))
check("NUMBER_FIX 3 re-dues a number refusal inside a run", False,
      gm.read_done({**stale, "numberFix": 2, "runFix": gm.RUN_FIX}))
check("NUMBER_FIX 3 leaves a gap page (no run) as it was", True,
      gm.read_done({**stale, "date": "1977-03-09", "numberFix": 2, "runFix": gm.RUN_FIX}))
check("a one-page run needs its own number printed", None, gm.run_number(D(1978, 2, 26), "nothing"))
check("number_of takes the run's number before 1995", (w - 121, "offset run"),
      gm.number_of((None, D(1975, 3, 9)), "Mephisto Crossword No %d" % (w - 121), None))
part = {"file": "x.pdf", "number": 2055, "whole": False, "blank": ["1-down", "2-down"], "version": gm.VERSION}
check("a page read with 1-down blank before TAIL_FIX is due", False, gm.read_done(part))
check("a page read with 1-down blank at TAIL_FIX stands", True, gm.read_done({**part, "tailFix": gm.TAIL_FIX, "columnFix": gm.COLUMN_FIX}))
check("a page blank elsewhere is not due for TAIL_FIX", True, gm.read_done({**part, "blank": ["5-down"], "columnFix": gm.COLUMN_FIX}))
check("a page blank before COLUMN_FIX is due", False, gm.read_done({**part, "blank": ["5-down"], "tailFix": gm.TAIL_FIX}))
many = {**part, "date": "1972-03-19", "blank": ["%d-down" % k for k in range(2, 8)], "tailFix": gm.TAIL_FIX, "columnFix": gm.COLUMN_FIX, "solutionFix": gm.SOLUTION_FIX, "vlmMissFix": gm.VLM_MISS_FIX, "stripFix": gm.STRIP_FIX}
check("a 1970s page with 4+ blanks before MID_FIX is due", False, gm.read_done(many))
check("a 1970s page with 4+ blanks at MID_FIX stands", True, gm.read_done({**many, "midFix": gm.MID_FIX}))
check("a 2000s page with 4+ blanks is not due for MID_FIX", True, gm.read_done({**many, "date": "2003-10-05"}))
_unasked = {k: v for k, v in many.items() if k != "vlmMissFix"}
check("a page with 4+ blanks and no VLM column asked before VLM_MISS_FIX is due", False, gm.read_done({**_unasked, "midFix": gm.MID_FIX}))
check("the same page that asked the VLM stands", True, gm.read_done({**_unasked, "midFix": gm.MID_FIX, "vlmColumns": 2, "stripFix": gm.STRIP_FIX}))
_nostrip = {k: v for k, v in many.items() if k != "stripFix"}
check("a page 4+ blank after VLM columns, before STRIP_FIX, is due", False, gm.read_done({**_nostrip, "midFix": gm.MID_FIX, "vlmColumns": 2}))
check("a page with 3 blank after VLM columns is not due for STRIP_FIX", True, gm.read_done({**_nostrip, "midFix": gm.MID_FIX, "vlmColumns": 2, "blank": ["2-down", "3-down", "4-down"]}))
check("a whole page is not due for STRIP_FIX", True, gm.read_done({**_nostrip, "midFix": gm.MID_FIX, "vlmColumns": 2, "whole": True}))
noparse = {"file": "x.pdf", "refused": "no reading parses", "date": "2003-04-06", "version": gm.VERSION, "listsFix": gm.LISTS_FIX,
           "leftFix": gm.LEFT_FIX, "midFix": gm.MID_FIX, "solutionFix": gm.SOLUTION_FIX, "enumFix": gm.ENUM_FIX, "downGap": gm.DOWN_GAP}
check("a 2000s no-parse refusal before HEAD_FIX is due", False, gm.read_done(noparse))
check("a 2000s no-parse refusal at HEAD_FIX stands", True, gm.read_done({**noparse, "headFix": gm.HEAD_FIX}))
check("a 1970s no-parse refusal is not due for HEAD_FIX", True, gm.read_done({**noparse, "date": "1972-03-19"}))
box = (180, 1729, 1044, 2630)
ws =[(1057, 1650 + 28 * k, 1090, 1670 + 28 * k, str(20 + k)) for k in range(6)] + [(200, 2700, 260, 2720, "1")]
check("the right column's split is its numbers' left edge", 1049, gm.column_split(ws, box, 1068, 1700, 2600, 24))
check("numbers right of the half way line leave it", 1068, gm.column_split([(1090, 1700 + 28 * k, 1100, 1720, "5") for k in range(6)], box, 1068, 1700, 2600, 24))

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
check("a grid refusal at GRID_FIX 2 is due", False, gm.read_done({**refused, "gridFix": 2}))
_page = np.zeros((600, 600), bool)
check("a page with no solid black area is left as it is", None, gm.unblobbed(_page))
_page[100:400, 100:400] = True
_solid = gm.unblobbed(_page)
check("a solid black area is taken out of the ink", True, _solid is not None and not _solid[250, 250])
bare = {"file": "GALE_FP1.pdf", "version": gm.VERSION, "refused": "no clue list on the page", "bareFix": gm.BARE_FIX,
        "downFix": gm.DOWN_FIX, "date": "1960-01-03"}
check("a no-clue-list refusal before the wrapped lists is due", False, gm.read_done(bare))
check("a no-clue-list refusal at WRAP_FIX but before LEFT_FIX is due", False, gm.read_done({**bare, "wrapFix": gm.WRAP_FIX}))
_stamped = {**bare, "wrapFix": gm.WRAP_FIX, "leftFix": gm.LEFT_FIX, "downFix": gm.DOWN_FIX, "headRowFix": gm.HEAD_ROW_FIX, "enumFix": gm.ENUM_FIX, "downGap": gm.DOWN_GAP}
check("a 1960s no-clue-list refusal before LATTICE_FIX is due", False, gm.read_done(_stamped))
check("a no-clue-list refusal at LEFT_FIX stands", True, gm.read_done({**_stamped, "latticeFix": gm.LATTICE_FIX}))
check("a 1970s no-reading-parses refusal before ENUM_FIX is due", False, gm.read_done({
    **bare, "refused": "no reading parses", "date": "1973-11-18", "wrapFix": gm.WRAP_FIX, "leftFix": gm.LEFT_FIX,
    "headRowFix": gm.HEAD_ROW_FIX, "listsFix": gm.LISTS_FIX, "headFix": gm.HEAD_FIX, "midFix": gm.MID_FIX,
    "solutionFix": gm.SOLUTION_FIX, "latticeFix": gm.LATTICE_FIX}))
check("the same refusal at ENUM_FIX stands", True, gm.read_done({
    **bare, "refused": "no reading parses", "date": "1973-11-18", "wrapFix": gm.WRAP_FIX, "leftFix": gm.LEFT_FIX,
    "headRowFix": gm.HEAD_ROW_FIX, "listsFix": gm.LISTS_FIX, "headFix": gm.HEAD_FIX, "midFix": gm.MID_FIX,
    "solutionFix": gm.SOLUTION_FIX, "latticeFix": gm.LATTICE_FIX, "enumFix": gm.ENUM_FIX, "downGap": gm.DOWN_GAP}))
check("the same refusal at ENUM_FIX but before DOWN_GAP is due", False, gm.read_done({
    **bare, "refused": "no reading parses", "date": "1973-11-18", "wrapFix": gm.WRAP_FIX, "leftFix": gm.LEFT_FIX,
    "headRowFix": gm.HEAD_ROW_FIX, "listsFix": gm.LISTS_FIX, "headFix": gm.HEAD_FIX, "midFix": gm.MID_FIX,
    "solutionFix": gm.SOLUTION_FIX, "latticeFix": gm.LATTICE_FIX, "enumFix": gm.ENUM_FIX}))
# ENUM_FIX: the Down heading is placed above the first Down number after Across numbers when no enumeration marks the foot
_lh = 24
_across = [(1100, 1600 + 27 * i, 1130, 1623 + 27 * i, str(n)) for i, n in enumerate((28, 29, 30, 32, 33))]
_downs = [(1100, 1600 + 27 * 4 + 83 + 27 * i, 1130, 1623 + 27 * 4 + 83 + 27 * i, str(n)) for i, n in enumerate((1, 2, 3, 4, 5, 6))]
_bx = (200, 1600, 1000, 2500)
_nums = _across + _downs
check("a Down heading is set over the first Down number when no enumeration line is read", 1,
      len(gm.missing_down(_nums, _bx, _lh, 1900)))
# DOWN_GAP: a lone garbled word ("own") between the Across foot and the first Down clue is the heading; so is the empty
# line above a misread first Down number
_ax = [(1100, 1600 + 27 * i, 1130, 1623 + 27 * i, str(n)) for i, n in enumerate((28, 29, 30, 31))]
_ax += [(1135, 1600 + 27 * 4, 1400, 1623 + 27 * 4, "Across foot (5)"), (1167, 1600 + 27 * 5, 1221, 1617 + 27 * 5, "own")]
_dn = [(1100, 1600 + 27 * 6 + 27 * i, 1130, 1623 + 27 * 6 + 27 * i, str(n)) for i, n in enumerate((3, 4, 5, 6, 7))]
check("a lone garbled word between the lists is set as the Down heading", [(1100, 1735, 1196, 1752 + 7, "Down")],
      gm.missing_down(_ax + _dn, _bx, _lh, 1900))
_ax2 = [(1100, 1600 + 27 * i, 1130, 1623 + 27 * i, str(n)) for i, n in enumerate((28, 29, 31, 2))] + [
    (1135, 1600 + 27 * 4, 1400, 1623 + 27 * 4, "Across foot (5)"), (1135, 1600 + 27 * 5, 1400, 1623 + 27 * 5, "more words")]
_dn2 = [(1100, 1600 + 27 * 8 + 27 * i, 1130, 1623 + 27 * 8 + 27 * i, str(n)) for i, n in enumerate((1, 2, 3, 4, 5))]
check("the empty line above a Down number is set as the Down heading", 1, len(gm.missing_down(_ax2 + _dn2, _bx, _lh, 1900)))
check("no heading is set in a list of Across clues alone", [], gm.missing_down(_ax + _ax2, _bx, _lh, 1900))
check("a later no-clue-list refusal is not due", True, gm.read_done({**bare, "date": "1998-01-04"}))
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

def numbered(x, n, y0=100):
    return [w for i in range(n) for w in ((x, y0 + 40 * i, x + 20, y0 + 40 * i + 25, str(i + 1)),
                                          (x + 30, y0 + 40 * i, x + 90, y0 + 40 * i + 25, "Word"))]
cols = numbered(20, 10) + numbered(620, 10) + numbered(140, 3, 900)
check("a short run of numbers inside a column is no column", [5, 605], gm.column_lefts(cols, 1200))
check("two real columns stay", [5, 605], gm.column_lefts(numbered(20, 10) + numbered(620, 8), 1200))

# DOWN_GAP: the entry rules' notice ("12 Coley Street") over the Across heading is not an Across number of 12
_nl = [(100, 1000, 300, 1030, "Solutions"), (100, 1040, 140, 1070, "12"), (150, 1040, 400, 1070, "Coley"),
       (100, 1100, 180, 1130, "Across")]
_nl += [(100, 1140 + 40 * i, 140, 1170 + 40 * i, str(n)) for i, n in enumerate((1, 9, 10, 11))]
_nl += [(100, 1300, 140, 1330, "30"), (100, 1340, 140, 1370, "1"), (100, 1380, 140, 1410, "2")]
_cut = ((90, 900, 1000, 1500), [])
_got = gm.headless_tail(_nl, _cut, 500, gl)
check("the notice's number is no Across number: the Down list opens at its first clue", 1340 - 6, _got and _got[1])
check("without the Across heading the notice's number still counts", 1140 - 6, gm.headless_tail(
    [w for w in _nl if w[4] != "Across"], _cut, 500, gl)[1])

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
