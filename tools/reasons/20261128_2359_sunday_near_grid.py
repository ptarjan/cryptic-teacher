"""SUNDAY_NEAR_GRID (fa.sunday_near_grid): a Gale Sunday Times page refused "the ink under the title is WxH, not a grid" whose
title box stands against a grid of the page (r318: 52 rows, 1962-2003).
Shapes by the page's own boxes (cached title box against grids_on's shaped ink): the title box runs on over its grid's top frame
(1962-03-25: title to y 4178, frame from 4160; 1964-69, 1968-03/04: the title line wider than its grid or only over its corner;
locate_grid's under-crop opens at the title's foot and takes TITLE_OVERLAP = 12 px of overlap), the grid lies over the title
(a caption line wider than the grid, 1991-92, or a short heading over the grid's foot further than 0.6 of its width), and pages
of other shapes (grid far under the title with the clue columns between, a heading left of a grid number_right and the mid
layout miss, 1979-80 winners-caption pages): not changed here.
Fix (read-time, _read_puzzle's refusal point; scan boxes and keys unchanged): only where every other layout left the page
refused, a shaped grid whose span is covered by the title's by 25% of its width and whose top frame is in the title's box is
the grid (side below); else the grid over the title with the clue columns over it found (sunday_times_over, reach 1.6 of its
width, span instead of middle); else the caption line's grid (sunday_caption_grid's gap, span instead of middle).
Due: a Gale Sunday Times row refused not-a-grid under the title, read before the cutoff."""
from fix_reasons import Reason

TEXT = "Gale Sunday Times page refused 'not a grid' whose title box stood against a grid of the page, the grid read since"
REREAD = "2026-11-28T13:40:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = str((row or {}).get("edition") or "")
    if not rel.startswith("GaleSundayTimes") or "inputs" not in row:
        return False
    if not any(v.get("cause") == "not-a-grid" and str(v.get("refused") or "").startswith("the ink under the title is ")
               for v in row.get("verdicts") or ()):
        return False
    return fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)) and not fa.specific_fix_reason(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
