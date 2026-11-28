"""SUNTEL_OWN_TITLE (fa.suntel_own_title): a Gale Sunday Telegraph puzzle titled from the bare "COMPETITION No N" solution heading
(SUNTEL_TITLE, 11-28 04:35) was refused "the ink under the title is WxH, not a grid" (r317: 35 rows 1990-93).
Cause: the title box suntel_titled gave is the heading's own, the SOLUTION heading of the puzzle a week back (the scan's "puzzles"
and "solutions" hold the same box), not the cryptic's title, which the crops never read. locate_grid looked under it and took the
solution's small grid (324x336, 1990), a clue column's blank (12x32) or a line of print (2120x134). The cryptic's grid is elsewhere: on
the pages checked it is the largest grid-shaped ink that no solution grid fits, at the page's left, its foot ~530 px over the solution
heading (1991-12-01: grid 238,3620-994,4382, heading 260,4915; the Quickie's 568 px grid right of it). Filed 1990-93 pages (40
sampled) print their title under that grid, its top 28 px under to 40 px over the grid's foot.
Shape tally of the 35: 21 specks (12-110 px), 7 wide strips of print (1700-2700 x 100-150), 4 the 1990 solution grid (324-344
square), 3 other small blocks.
Fix (read-time, _read_puzzle; scan boxes and keys unchanged): the puzzle's box moves to the heading's own size laid on the foot of the
leaf's largest non-solution grid (on its top where the heading stands over the grid's middle). Filed pages are untouched: only a puzzle
whose titleReadBy holds suntelWhole and whose box equals one of the scan's solution boxes is moved.
Due: a Gale Sunday Telegraph row with such a puzzle, refused not-a-grid under the title, read before the cutoff."""
from fix_reasons import Reason

TEXT = "Gale Sunday Telegraph page titled from its solution heading, its own grid sought rather than the ink under that heading, read since"
REREAD = "2026-11-28T10:45:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = str((row or {}).get("edition") or "")
    if not fa.GALE_SUNDAY_TELEGRAPH.item.match(rel.split("/")[0]) or "inputs" not in row:
        return False
    scan = row.get("scan") or {}
    boxes = {tuple(s.get("box") or ()) for s in scan.get("solutions") or ()}
    if not any(fa.SUNTEL_OWN_TITLE in (p.get("titleReadBy") or ()) and tuple(p.get("box") or ()) in boxes
               for p in scan.get("puzzles") or ()):
        return False
    if not any(v.get("cause") == "not-a-grid" and str(v.get("refused") or "").startswith("the ink under the title is ")
               for v in row.get("verdicts") or ()):
        return False
    return fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)) and not fa.specific_fix_reason(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
