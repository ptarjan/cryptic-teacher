"""LATTICE_WHOLE (fa.lattice_whole): a Gale Telegraph page whose grid under its clues the crop of grid_under_clues cut short.
r318, Gale Telegraph 1970-79 open rows (421): the biggest single failure shape, ~100 rows (1971-77), is a grid read from a
square ink that is only part of the grid: grid_under_clues opens its crop at the title's foot and runs CLUES_ABOVE_SPAN wide
from the title's left, and a 1970s title stands beside the upper part of its grid, so the crop took the grid's lower-left part
(1971-11-25: ink 602x576 from y 4312, the grid itself 714x720 from y 4166). Too small for grid_shaped, a square lattice
(LATTICE_UNDER), it was read as a 12 or 13 row lattice of a 15x15 grid: "pending: no grid: numbers [...] lost from the clue
list", "the white cells span 12 rows and 13 columns", "refused: no reading parses" and blank lights, 15x15 solutions seen
nowhere in the ink. The page's own evidence holds the whole grid: a grid-shaped ink on the page that holds the cut ink and
shares its left and foot (2% of its width), the smallest such. It is laid in the cut ink's place when the cut ink is not
grid-shaped itself, so a page whose ink was shaped reads as it did. Read-time only (read_page): no scan key moves.
Due: a Gale Telegraph row holding an unwritten verdict whose grid was that small square lattice, read before the cutoff."""
from fix_reasons import Reason

TEXT = "Gale Telegraph page whose grid under its clues the crop cut short, the whole grid ink read since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = str((row or {}).get("edition") or "")
    if not rel.startswith("GaleTelegraph") or "inputs" not in row:
        return False
    if not any(v.get("gridBox") == "under its clues, a small square lattice" and not v.get("wrote") and not v.get("skip")
               for v in row.get("verdicts") or ()):
        return False
    return fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)) and not fa.specific_fix_reason(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
