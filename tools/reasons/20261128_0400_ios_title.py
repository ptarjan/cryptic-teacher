"""IOS_TITLE (fa.ios_titled, ios_read_title, ios_headings_loose, ios_stale): a Gale Independent on Sunday page read whole with
no title found ("puzzles: [], wholeUntitled", no verdict), r315 cluster 13: 98 rows (1990-94 32, 2005-09 38, 2010-14 15, rest 13).
Every one of the 98 holds a clue column (about 30 enumerations per page read): none is a wrong fetch. The reader missed the heading
in three shapes: (1) 1990-92 "10 BEELZEBUB PRIZE Crossword No 28" (and the glued "BEELZEBUBPRIZECrosswordNo28"), a page number or
another column's words before it on the row, so no line opens on it (24 rows); (2) 2005-12 on "THE PRIZE Crossword" / "by Quixote"
with "No 1024, 27 September 2009" a line of its own right of it or under it, and the number's comma that SMALL_NUMBER refuses
(about 55 rows); (3) a heading either reader gave in the page read that the strip scan never saw (1994, 1999, 2004).
ios_titled reads the cached page reads of both readers (outside scan(): no scan key moves) and titles the page with a number both
readers give within the paper's slack, or one reader's backed by the page's "Mark entries Beelzebub N" or a "Winners of N" notice.
Offline: 81 of the 98 titled. Left 17: 1990-04-29, 1993-08-01, 1993-12-19, 1994-02-20, 1994-03-27, 1995-11-26, 1999-08-08,
1999-08-22, 1999-08-29, 2000-01-30, 2003-04-20, 2003-05-18, 2003-05-25, 2007-10-07, 2010-11-21, 2011-05-01, 2011-05-29 (one reader's
digits only, or the heading's number unread). Pages that scan() titled are untouched (ios_titled returns them whole). Due: the rows of
tools/data/ios_title.json."""
import re

from fix_reasons import Reason

TEXT = "Gale Independent on Sunday page with no title found, titled since from the heading both page readers give"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleIndependentSunday\d{4}UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    return fa.ios_stale(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
