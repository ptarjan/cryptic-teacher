"""NUMBER_RIGHT_2000S (fa.NUMBER_RIGHT_YEARS now to 2009): a Gale Sunday Times 2000-09 page whose title is the short
"No N" heading (after sunday_winners_mended moved the title to it, 11-20 rereads) was refused "the ink under the title
is 14x20, not a grid": the grid stands right of that heading with its top level with it, as on the 1987-99 pages, which
number_right finds (a 720x720 lattice on 2004-11-21 and 2005-09-04). Due: a Gale Sunday Times 2000-09 edition refused
"not a grid" for ink under 100 px each way, read before REREAD."""
import re
from fix_reasons import Reason

TEXT = "Gale Sunday Times 2000-09 page refused not a grid under its short No N heading, its grid right of it read since"
REREAD = "2026-11-21T18:18:00+00:00"
INK = re.compile(r"the ink under the title is (\d+)x(\d+), not a grid")


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not re.match(r"GaleSundayTimes20(?:0\d)UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    for v in row.get("verdicts", ()):
        m = INK.search(str(v.get("refused") or ""))
        if m and v.get("cause") == "not-a-grid" and all(int(g) < 100 for g in m.groups()):
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, due=due)
