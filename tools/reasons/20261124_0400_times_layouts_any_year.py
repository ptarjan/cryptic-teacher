"""TIMES_LAYOUTS_ANY_YEAR: the Gale Times (daily) grid-location layouts are tried on every page refused "not a grid", whatever
its year. band_grid (a grid whose top lies in its title's line, OFFSET_UNDER 1939-49 and BAND_LATE 1950-67), small_grid
(1940-41 pages printed small, SMALL_PAGE), closed_grid (a frame the scan broke into pieces, 1940-41) and scaled_under (the
wide pages' solution-sized grid, 1939-67) were each gated to the years they were found in. A page's own evidence accepts or
refuses a candidate (shaped ink straddling the title's middle, its top in the title's line, a small page's square); the years
only order them (the page's own first, the others after, only where the page would be refused), so a page that reads keeps
its read. Due: a Gale Times edition refused "the ink under the title is WxH, not a grid" with ink of a grid's width or height
(400 px or more; the 2x2-8x8 refusals have no ink under the title for a candidate to find), read before REREAD. Offline,
83 cached pages 1930-2014: 72 read the same, 0 changed, 11 of the 24 refused pages newly reach a grid."""
import re

from fix_reasons import Reason

TEXT = "Gale Times page of any year refused not a grid for ink of a grid's size, every grid-location layout tried on it since"
REREAD = "2026-11-25T03:24:00+00:00"
INK = re.compile(r"the ink under the title is (\d+)x(\d+), not a grid")
GRID_INK = 400


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if fa.paper_of(rel).key != "gale" or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    for v in row.get("verdicts") or ():
        m = INK.search(str(v.get("refused") or "")) if v.get("cause") == "not-a-grid" else None
        if m and max(int(m.group(1)), int(m.group(2))) >= GRID_INK:
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, due=due)
