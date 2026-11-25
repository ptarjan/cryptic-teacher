"""NUMBER_RIGHT_ANY_YEAR: number_right (the grid right of a Gale Sunday Times page's short "No N" heading) is tried on
every page whose located grid failed, whatever its year (it was gated to 1987-2009): the heading's number is placed in
the filed sequence first (filed_number) and the grid must be a lattice level with the heading, so the page accepts or
refuses it. 1986 pages (a 720x700 lattice right of the heading) were the first found. Due: a Gale Sunday Times edition
outside 1987-2009 refused "not a grid" for ink under 100 px each way, read before REREAD (the 1987-2009 rows are due
by number_grid_due and the 2000s reason)."""
import re
from fix_reasons import Reason

TEXT = "Gale Sunday Times page of any year refused not a grid under its short No N heading, its grid right of it read since"
REREAD = "2026-11-19T23:59:00+00:00"
INK = re.compile(r"the ink under the title is (\d+)x(\d+), not a grid")


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    m = re.match(r"GaleSundayTimes((?:19|20)\d\d)UKEnglish/", rel)
    if not m or fa.NUMBER_RIGHT_FIRST_YEARS[0] <= m.group(1) <= fa.NUMBER_RIGHT_FIRST_YEARS[1] or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    for v in row.get("verdicts", ()):
        g = INK.search(str(v.get("refused") or ""))
        if g and v.get("cause") == "not-a-grid" and all(int(x) < 100 for x in g.groups()):
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, due=due)
