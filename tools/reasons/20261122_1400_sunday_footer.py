"""SUNDAY_FOOTER (fa.sunday_footer_cut): a Gale Sunday Times 2000-02 page whose ACROSS column runs down to the page's folio
line ("54-STYLE": the page number and the Style section's name) read that line as a clue numbered 54 with no words.
Since SUNDAY_PAIR_LATE read the lists (11-21) the clue list held a clue naming no light, so the page's grid was backsolved
from it and found none: pending "no grid: the search found no grid" (census r304 cluster 16: 81 rows 2000-02, 93 open vs
47 in r303; ~60 rows with the folio at the foot of the ACROSS column, 2000-01-16 to 2002-08-04, "imageDisagrees: across
clue [] names no light"). Those pages were refused "no reading parses" before the pair fix, so no later change regressed
them. sunday_footer_cut drops a line that is a number and STYLE and nothing else from every reading. A read-time change:
no scan key moves. Due: a Sunday Times 2000-02 row pending "no grid" whose clue list names no light, read before the cutoff."""
import re
from fix_reasons import Reason

TEXT = "a Gale Sunday Times 2000-02 page pending no grid, its folio line (number and STYLE) read as a clue, dropped since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not re.match(r"GaleSundayTimes200[0-2]UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    # The left-column pages are numbered 38xx-39xx (the 20xx titles are the right-hand layout, another shape).
    return any(str(v.get("pending") or "").startswith("no grid") and "clue [] names no light" in str(v.get("imageDisagrees"))
               and 3800 <= (v.get("number") or 0) <= 3999 for v in row.get("verdicts") or ())


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
