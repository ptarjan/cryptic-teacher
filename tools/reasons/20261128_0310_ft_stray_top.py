"""FT_STRAY_TOP (fa.columns, fa.ft_stray_top): a Gale FT page refused "no reading parses" with every reader "no ACROSS and DOWN
lists under the grid" (or none read) whose clue column opens on stray print over its ACROSS heading. 2003-06-11 No 11243: the
columns start FT_RISE (172) over the grid, which took in "8.6 Connaught f 297" (y 4295, a scrap of the page's text) 163px over
ACROSS (y 4458): columns() kept it as a clue's number-led first line, the gap to the heading ended the column there, and the
whole ACROSS list (1-27) was lost, DOWN read alone. A column's first line over its ACROSS heading with more than the gap
between them is no clue and is dropped. Read-time only (scan never parses): no scan key moves. Dry read: 2003-06-11 and
2003-01-09 file; 2003-05-28, 2003-10-09, 2007-04-18 stay refused (other causes).
Due: a Gale FT row read before the cutoff, refused "no reading parses" with no grid fault or image fault, every reader's
text "no ACROSS and DOWN lists under the grid" or none read."""
import re

from fix_reasons import Reason

TEXT = "Gale FT page refused no reading parses, stray print over its ACROSS heading no longer ending its clue column"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)

SHAPE = "no ACROSS and DOWN lists under the grid"


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleFT(19|20)\d\dUKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    for v in row.get("verdicts") or ():
        if v.get("refused") != "no reading parses" or v.get("imageUnread") or v.get("gridBox"):
            continue
        texts = [str(t) for t in (v.get("unparsed") or {}).values()]
        if all(SHAPE in t for t in texts):
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
