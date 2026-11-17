"""INDY_BANNER: the Gale Independent's help-line banner is cut from every reading's column text, and a ledger row
whose clue stood blank for it is due once (indy_banner_due)."""
import sys
from datetime import datetime, timedelta

import _path  # puts tools/ on sys.path

import file_archive_org_puzzles as fa

fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


tail = "6 Route doesn't show parking on map area in (5) Can't wait until tomorrow? Get help now at www.independent.co.uk/crosswords"
check("banner run on after a count is cut", fa.banner_cut(tail) == "6 Route doesn't show parking on map area in (5)")
lines = "5 Another clue (4)\nCan't wait until tomorrow? Get help now at www.independent.co.uk/crosswords\n7 Next (3)"
check("banner on its own line is emptied", fa.banner_cut(lines) == "5 Another clue (4)\n\n7 Next (3)")
check("a clue without the banner is untouched", fa.banner_cut("1 Plain clue (4)") == "1 Plain clue (4)")
check("an empty text is untouched", fa.banner_cut("") == "")
check("phone line matched", bool(fa.INDY_BANNER_LINE.search("Across/Down clues 09068 446 002 Calls cost 60p/min")))
check("ordinary clue words not matched", not fa.INDY_BANNER_LINE.search("Can't wait for the independent trader (6)"))

row = {"edition": "GaleIndependent2008UKEnglish/2008-08-14", "readAt": "2026-11-14T00:00:00+00:00",
       "verdicts": [{"number": 6811, "id": "independent-6811", "unfiled": 1,
                     "blank": {"6-down": "'www.independent.co.uk/c': a stray mark inside a word"}}]}
check("a row blank for the banner, read before the fix, is due", fa.indy_banner_due(row))
check("fix_reason names it or an earlier Independent fix", bool(fa.fix_reason(row)))
late = dict(row, readAt=(datetime.fromisoformat(fa.REREAD_INDY_BANNER) + timedelta(hours=1)).isoformat())
check("a row read after the fix is not due", not fa.indy_banner_due(late))
other = dict(row, verdicts=[dict(row["verdicts"][0], blank={"6-down": "'solu': not a word"})])
check("a row blank for another cause is not due", not fa.indy_banner_due(other))
check("INDY_BANNER ranked", fa.INDY_BANNER in fa.RANKS)

if fails:
    print("test_indy_banner: failed")
    sys.exit(1)
print("test_indy_banner: all passed")
