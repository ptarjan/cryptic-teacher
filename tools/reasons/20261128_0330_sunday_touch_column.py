"""SUNDAY_TOUCH_COLUMN (fa._read_page, the Gale Sunday Times column readers): r315 cluster, 102 Gale Sunday Times rows refused
"no reading parses" (1980-84 28, 1995-99 21, 1975-79 13, 2000-04 12). 21 of them, 1993-99, are a grid found by touching_grid
(verdict gridBox "touching its title", backsolved): the one clue column left of the grid (ACROSS over DOWN, 1999-10-10: DOWN
heading at x 788 y 1819, the column from x 654, the grid right of it) was never looked for, because the column readers'
second pass (every layout whose years are not the page's) skipped a backsolved grid (`not (late and backsolve)`) and the
first pass is year-ordered (sunday_times_right 1985-89). The second pass now runs for a backsolved page too: each reader
still accepts only the page's own evidence (an ACROSS heading with a DOWN under it at one x, numbered lines at one edge),
and it runs only while no column was found. 1999-10-10 reads whole (32 lights, 32 agreed). The other shapes of the 102 (1983
page-top titles with clues on the grid, 1978 white-cell counts, 2002-03 no gridBox) are left. Read-time, no scan key moves."""
import re

from fix_reasons import Reason

TEXT = "Gale Sunday Times page refused no reading parses, its grid touching its title, the clue column left of it read since"
REREAD = "2026-11-28T06:19:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleSundayTimes\d{4}UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False
    return any(v.get("cause") == "no-reading-parses" and v.get("gridBox") == "touching its title"
               for v in row.get("verdicts") or ())


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
