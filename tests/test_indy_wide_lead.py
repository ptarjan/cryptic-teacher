"""INDY_WIDE_LEAD: a wide-title Independent page keeps its lead window (no overhang), and its refused row is due once."""
import _path  # puts tools/ on sys.path

import file_archive_org_puzzles as fa
import fix_reasons
import edition_queue

fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


d = fa.Path("GaleIndependent2007UKEnglish/2007-01-27")
paper = fa.paper_of(d)
grid, title = (814, 1609, 1534, 2329), [174, 1548, 2008, 1587]
check("2007-01-27 geometry keeps its lead window", fa.indy_wide_lead(paper, d, grid, title))
check("a narrow title is left alone", not fa.indy_wide_lead(paper, d, grid, [174, 1548, 1000, 1587]))
check("a title level with its grid is left alone", not fa.indy_wide_lead(paper, d, (200, 1609, 920, 2329), title))
check("a 2004 page is left alone", not fa.indy_wide_lead(paper, fa.Path("GaleIndependent2004UKEnglish/2004-01-24"), grid, title))
check("a Times page is left alone", not fa.indy_wide_lead(fa.paper_of(fa.Path("GaleTimes2007UKEnglish/2007-01-27")), d, grid, title))

reason = fix_reasons.registered()["20261122_1500_indy_wide_lead"]
check("reason ranked", reason.text in fa.RANKS and reason.rank == 2)
row = {"edition": "GaleIndependent2007UKEnglish/2007-01-27", "readAt": "2026-11-20T15:36:45+00:00", "inputs": "x",
       "scan": {"date": "2007-01-27", "item": "GaleIndependent2007UKEnglish",
                "puzzles": [{"number": 6328, "leaf": 0, "box": title}], "solutions": []},
       "verdicts": [{"number": 6328, "leaf": 0, "refused": "no reading parses"}]}
narrow = dict(row, scan=dict(row["scan"], puzzles=[{"number": 6328, "leaf": 0, "box": [174, 1548, 1000, 1587]}]))
check("a refused wide-title row is due", bool(reason.due(row)))
check("a narrow-title row is not due", not reason.due(narrow))
check("a row read after the fix is not due", not reason.due(dict(row, readAt="2026-11-23T00:00:00+00:00")))
check("a 2009 row is not due", not reason.due(dict(row, edition="GaleIndependent2009UKEnglish/2009-01-24")))
check("all unfiled-first reasons are ranked", all(r in fa.RANKS for r in edition_queue.UNFILED_FIRST))
raise SystemExit(1 if fails else 0)
