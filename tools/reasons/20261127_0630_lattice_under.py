"""LATTICE_UNDER: a Gale Telegraph page's grid under its clues is taken for the grid when its ink is a square that shows a
crossword's lattice, though it falls short of grid_shaped()'s pixel floor. r305: 582 Gale Telegraph pages refused "the ink under
the title is 602x576, not a grid" (41 at r304), 524 of them squared ink (1969-77 mostly): the page is 4,200-4,300 px wide and
its grid ~14% of that, 470 px at SCAN_WIDTH against the floor's 500 (1971-11-25: 602x576 on 4218, 1971-11-24: 632x648 on
4316; both box_lattice true). Not a regression of the 11-24 layout rework: the 1969-77 pages were first read from 11-25 on,
and a third of them hit the floor. The page's own evidence (the aspect, the lattice) stands for the grid, no pixel size.
Due: a Gale Telegraph edition refused "the ink under the title is WxH, not a grid" with squared ink (GRID_ASPECT) at least
GRID_INK px across, read before REREAD."""
import re

from fix_reasons import Reason

TEXT = "Gale Telegraph page refused 'not a grid' for a small square ink under its title, the lattice it shows taken for the grid since"
REREAD = "2026-11-19T23:59:00+00:00"
INK = re.compile(r"the ink under the title is (\d+)x(\d+), not a grid")
GRID_INK = 400


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if fa.paper_of(rel).key != "galetelegraph" or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    for v in row.get("verdicts") or ():
        m = INK.search(str(v.get("refused") or "")) if v.get("cause") == "not-a-grid" else None
        if m and min(int(m.group(1)), int(m.group(2))) >= GRID_INK and fa.squared(int(m.group(1)), int(m.group(2))):
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
