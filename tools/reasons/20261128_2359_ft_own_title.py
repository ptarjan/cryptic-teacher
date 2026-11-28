"""FT_OWN_TITLE (fa.ft_own_title): a Gale FT puzzle whose title box stands clear of every grid on its leaf was refused "the ink under
the title is WxH, not a grid" (r317 cluster 23: 73 rows).
Shape tally of the 73 by the size in the verdict: 38 specks (under 250 px either way: 4x170, 116x22, 330x28 ...), 5 thin strips or
columns of print (2120x106, 2600x82, 10x828, 8x738, 2250x652), 30 patches of 300-1100 px (a clue block's corner, a solution-sized
square, 1452x1654 of a whole column of print). By where the box sits against the grids grids_on finds on the leaf: 38 rows
(1983-94 and a few 1976-82 and 2005) have the page's cryptic grid (a 720 px square at 3450 px wide) a thousand-odd px OVER
the box, the box standing at the page's foot (y 4040-4480 of 4900), 960 wide and 18-45 tall, its number read a fortnight
(12 puzzles) before the date's: the SOLUTION heading of the puzzle two weeks back, not the cryptic's own title (the same shape
as the Sunday Telegraph's, SUNTEL_OWN_TITLE). The 1974 rows (25) are another shape: the box stands over a grid (solution-sized or
not) that locate_grid cut short or whose ink found none: not changed here. The 14 filed 1985-94 pages sampled have the title's
foot 14-33 px over the grid's top and its middle on the grid's middle.
Fix (read-time, _read_puzzle; scan boxes and keys unchanged): a puzzle whose box, grown by its own height, meets no grid-shaped
ink on its leaf (solution grids included, so a title with its grid beside it is kept) is laid on the top of the nearest
non-solution grid, centred on it. Offline, the moved box found a shaped grid under it on 37 of the 38 rows moved.
Due: a Gale FT row refused not-a-grid under the title, read before the cutoff."""
from fix_reasons import Reason

TEXT = "Gale FT page whose title box stood clear of every grid (the solution heading's) laid on its own grid's top and read since"
REREAD = "2026-11-28T11:56:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = str((row or {}).get("edition") or "")
    if not fa.GALE_FT.item.match(rel.split("/")[0]) or "inputs" not in row:
        return False
    if not any(v.get("cause") == "not-a-grid" and str(v.get("refused") or "").startswith("the ink under the title is ")
               for v in row.get("verdicts") or ()):
        return False
    return fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)) and not fa.specific_fix_reason(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
