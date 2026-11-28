"""INDY_UNDER_ANY_READER (fa.indy_under; r318): a Gale Independent 1996-98 page with its grid bottom-left, ACROSS 1-25 in two print
columns under the grid and ACROSS 26-29 with the whole DOWN list in the column right of it (1997-09-22 No 3410: all 12 ACROSS
clues blank, 17 clues read). indy_under() counted the columns under the grid in ONE reader's plain window (en5), and that reader
lost clue numbers (3 of the first column's 5 starts, under INDY_COLUMN_MIN): one column stood under the grid, its pitch to the
column beside the grid matched no ACROSS heading, indy_under() returned None, and the right window and the under window were read
apart, never joined. Rule (page's own measures, no year gate): when the first reader's columns do not pitch evenly to the one
beside the grid, each other reader's columns under the grid are tried. Read-time only: no scan key moves.
Due: the Gale Independent rows (names below, from the r318 shape scan: 5+ ACROSS blank, 1995-99) read before the cutoff, that no
older specific reason is due for."""
import re

from fix_reasons import Reason

TEXT = "Independent page whose ACROSS columns under the grid were never joined to the column right of it, joined since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)
NAMES = frozenset("""
1998-12-21 1998-11-09 1998-10-05 1998-08-03 1998-06-15 1998-03-02 1998-01-19 1998-01-12 1997-10-27 1997-09-22
1997-08-11 1997-07-14 1997-03-03 1997-02-10 1996-08-26 1996-07-29
""".split())


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    m = re.match(r"GaleIndependent(\d{4})UKEnglish/(\d{4}-\d\d-\d\d)$", rel)
    if not m or m.group(2) not in NAMES or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    return True


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
