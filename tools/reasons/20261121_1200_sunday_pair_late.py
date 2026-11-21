"""SUNDAY_PAIR_LATE (fa.sunday_times_pair late=True, fa.heading_room): the Gale Sunday Times 2000-06 pages set ACROSS and
DOWN side by side left of the grid (2004-12-12: ACROSS at x 237, DOWN at x 608, grid x 921-1641), DOWN's numbers 0.045
grids left of its heading (sunday_times_pair wanted 0.05, and only for 1985-89), and the first clue 85 px under each
heading (columns() cut a column at a gap over GAP's 80). No clue was read: "no reading parses", every reader "no ACROSS
and DOWN lists under the grid". What is due: a 2000-06 Gale Sunday Times row refused no-reading-parses."""
import re
from fix_reasons import Reason

TEXT = "a Gale Sunday Times 2000-06 page refused, its ACROSS and DOWN columns side by side left of the grid read since"
REREAD = "2026-11-21T18:18:00+00:00"


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not re.match(r"GaleSundayTimes200[0-6]UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    return any(v.get("cause") == "no-reading-parses" for v in row.get("verdicts") or ())


REASON = Reason(TEXT, rank=2, fix_landed=True, kept=True, due=due)
