"""INDY_TITLE_EDGE: an Independent lead window is never trimmed past its title's left edge; its refused row is due once."""
import _path  # puts tools/ on sys.path

import file_archive_org_puzzles as fa
import fix_reasons
import edition_queue

fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


paper = fa.paper_of(fa.Path("GaleIndependent2007UKEnglish/2007-12-08"))
title = [170, 1551, 2007, 1591]
check("trim past the title edge is held", fa.indy_title_kept(paper, (315, 1591), title) == (130, 1591))
check("a trim left of it stands", fa.indy_title_kept(paper, (0, 1591), title) == (0, 1591))
check("a Times page is left alone", fa.indy_title_kept(fa.paper_of(fa.Path("GaleTimes2007UKEnglish/2007-12-08")), (315, 1591), title) == (315, 1591))
reason = fix_reasons.registered()["20261127_2100_indy_title_edge"]
check("reason ranked", reason.text in fa.RANKS and reason.rank == 2)
row = {"edition": "GaleIndependent2003UKEnglish/2003-09-29", "readAt": "2026-11-17T15:36:45+00:00", "inputs": "x",
       "scan": {"date": "2003-09-29", "item": "GaleIndependent2003UKEnglish",
                "puzzles": [{"number": 6598, "leaf": 0, "box": [185, 2853, 993, 2925]}], "solutions": []},
       "verdicts": [{"number": 6598, "leaf": 0, "refused": "no reading parses"}]}
check("a refused row is due", bool(reason.due(row)))
check("a row read after the push is not due", not reason.due(dict(row, readAt="2026-11-28T00:00:00+00:00")))
check("all unfiled-first reasons are ranked", all(r in fa.RANKS for r in edition_queue.UNFILED_FIRST))
raise SystemExit(1 if fails else 0)
