#!/usr/bin/env python3
# Does tools/clue_repair.repair_rows (split_run_on and order, the repairs a
# single reading needs) split a clue the OCR ran into the one before it only at a
# number the lists skip, and put misnumbered clues in order? (Cyclops Nos 71, 96, 98, 111, 113.)
#
#     python3 tests/test_clue_repair_one_reading.py
#
# Offline.
import io
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

fails = 0


def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        print(f"FAIL {what}: want [{want}] got [{got}]")
        fails += 1


# What the shell's $(...) captured: everything the checks below print.
_stdout = sys.stdout
sys.stdout = io.StringIO()


import clue_repair as pw


def r(n, clue, enum):
    return {"number": n, "clue": clue, "enumeration": enum}


def show(a, d):
    return [(x["number"], x["clue"], x["enumeration"]) for x in a + d]


# A lost count: 15's "(6)" is 17's, the numbers skip 17.
a = [r("1", "One", "4"), r("15", "Action at one time 17 Go down sportingly", "6"), r("18", "Eighteen", "5")]
d = [r("2", "Two", "3"), r("16", "Sixteen", "4")]
a2, d2 = pw.repair_rows(a, d)
print("LOST", show(a2, d2)[1:3])

# A cross-reference with no count, run into the next clue.
a = [r("1", "One", "4"), r("5", "Five", "5")]
d = [r("2", "(sce 4) 3 Supported while bestowing", "4"), r("6", "Six", "5")]
a2, d2 = pw.repair_rows(a, d)
print("SEE", show(a2, d2))

# A count inside the text: the row's own is the later clue's.
a = [r("%d" % n, "Clue", "4") for n in (1, 3, 5, 7, 9)] + [r("10", "Quite able (7) 1] Those who have been honoured", "5")]
d = [r("%d" % n, "Clue", "4") for n in (2, 4, 6, 8, 12)]
a2, d2 = pw.repair_rows(a, d)
print("INSIDE", show(a2, d2)[5:7])

# No number skipped: nothing is touched.
a = [r("1", "Whole 2 Clue here", "5")]
d = [r("2", "Two", "3")]
a2, d2 = pw.repair_rows(a, d)
print("WHOLE", show(a2, d2)[0])

# A down list that starts with the across list's tail.
a = [r("1", "A", "4"), r("5", "B", "4")]
d = [r("6", "C", "4"), r("8", "D", "4"), r("2", "E", "4"), r("3", "F", "4")]
a2, d2 = pw.repair_rows(a, d)
print("TAIL", [x["number"] for x in a2], [x["number"] for x in d2])

# A misread number between two good neighbours.
a = [r("1", "A", "4"), r("7", "B", "4"), r("4", "C", "4"), r("5", "D", "4")]
d = [r("2", "E", "4"), r("6", "F", "4")]
a2, d2 = pw.repair_rows(a, d)
print("MISREAD", [x["number"] for x in a2])

out_text = sys.stdout.getvalue()
sys.stdout = _stdout


def got(key):
    return "\n".join(l[len(key) + 1:] for l in out_text.splitlines() if l.startswith(key + " "))


check('a lost count: the clue splits at the skipped number',
      "[('15', 'Action at one time', None), ('17', 'Go down sportingly', '6')]", got("LOST"))
check('a bare cross-reference splits off as See N',
      "[('1', 'One', '4'), ('5', 'Five', '5'), ('2', 'See 4', None), ('3', 'Supported while bestowing', '4'), ('6', 'Six', '5')]", got("SEE"))
check("a count inside the text is the earlier clue's",
      "[('10', 'Quite able', '7'), ('11', 'Those who have been honoured', '5')]", got("INSIDE"))
check('a list with no skipped number is left alone',
      "('1', 'Whole 2 Clue here', '5')", got("WHOLE"))
check('a down list opening with the across tail moves to across',
      "['1', '5', '6', '8'] ['2', '3']", got("TAIL"))
check('a number out of place between neighbours is the one gap number',
      "['1', '3', '4', '5']", got("MISREAD"))

if fails:
    print(f"{fails} failed")
    sys.exit(1)
print("all ok")
