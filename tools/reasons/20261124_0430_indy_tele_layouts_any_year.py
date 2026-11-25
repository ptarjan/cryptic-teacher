"""INDY_TELE_LAYOUTS_ANY_YEAR: the Gale Independent and Gale Telegraph layout readers are tried on every refused page, whatever
its year. The Telegraph's title readings (TELE_OVER 1985-89, the heading over the clue columns; TELE_QUICK_TITLE 1980-99, the
cryptic's clue block under a Quick caption) are taken on any page whose grid under the title as scanned is not a grid, each
accepted by the page's own evidence (the heading found, a shaped grid under it). The Independent's INDY_SIDE_GRID (a grid
under the title where the "left" box is no lattice) is any year's; its INDY_SIDE_RIGHT (columns right of a grid left of a wide
title, 2000-04), INDY_WIDE_LEAD (no overhang under a wide-titled plain window, 2005-08), INDY_RIGHT_RISE (2011-13) and
INDY_PAIR (the headings that pair the columns under the grid, 2010-13) are read for the other years as the windows after the
layout's, where its read is poor. The years only ORDER them, so a page one candidate reads keeps its read. Due: a Gale
Telegraph edition refused "the ink under the title is WxH, not a grid" with ink of a grid's size (400 px or more), or a Gale
Independent edition refused "no reading parses" or "not a grid", read before REREAD."""
import re

from fix_reasons import Reason

TEXT = "Gale Independent or Telegraph page of any year refused for its grid or columns, every layout candidate tried on it since"
REREAD = "2026-11-25T03:47:00+00:00"
INK = re.compile(r"the ink under the title is (\d+)x(\d+), not a grid")
GRID_INK = 400


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    key = fa.paper_of(rel).key
    if key not in ("galeindependent", "galetelegraph") or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    for v in row.get("verdicts") or ():
        cause = v.get("cause")
        if key == "galeindependent" and cause in ("not-a-grid", "no-reading-parses"):
            return True
        m = INK.search(str(v.get("refused") or "")) if key == "galetelegraph" and cause == "not-a-grid" else None
        if m and max(int(m.group(1)), int(m.group(2))) >= GRID_INK:
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, due=due)
