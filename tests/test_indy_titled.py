"""INDY_TITLED: a Gale Independent sports page scanned with no title is due once (indy_titled_due), and indy_titled
leaves a page that has a title alone."""
import sys

import _path  # puts tools/ on sys.path

import file_archive_org_puzzles as fa

fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


row = {"edition": "GaleIndependent2012UKEnglish/2012-03-13", "readAt": "2026-11-07T05:44:23+00:00", "inputs": "x",
       "scan": {"date": "2012-03-13", "item": "GaleIndependent2012UKEnglish", "puzzles": [], "solutions": [],
                "wholeUntitled": True}, "verdicts": []}
check("an untitled read-whole Independent row read before the fix is due", fa.indy_titled_due(row))
check("fix_reason names it", fa.fix_reason(row) == fa.INDY_TITLED)
check("a row read after the fix is not due", not fa.indy_titled_due(dict(row, readAt="2026-11-17T00:00:00+00:00")))
check("a row with a verdict is not due", not fa.indy_titled_due(dict(row, verdicts=[{"number": 1}])))
check("a titled scan is not due", not fa.indy_titled_due(
    dict(row, scan=dict(row["scan"], puzzles=[{"number": 7928, "leaf": 0, "box": [0, 0, 1, 1]}]))))
check("an Independent on Sunday row is not due", not fa.indy_titled_due(
    dict(row, edition="GaleIndependentSunday2012UKEnglish/2012-03-11")))
check("a Times row is not due", not fa.indy_titled_due(dict(row, edition="GaleTimes2012UKEnglish/2012-03-13")))
check("INDY_TITLED ranked", fa.INDY_TITLED in fa.RANKS)
found = {"date": "2012-03-13", "puzzles": [{"number": 7928, "leaf": 0, "box": [0, 0, 1, 1]}], "solutions": []}
check("a titled scan is left alone", fa.indy_titled(fa.Path("/nonexistent"), found) is found)

if fails:
    print("test_indy_titled: failed")
    sys.exit(1)
print("test_indy_titled: all passed")
