"""FT_FAINT_RIGHT (fa.right_or_over faint=, fa.otsu_cut): a Gale FT page printed light, refused "no reading parses" with every
reader "no ACROSS and DOWN lists under the grid" or none read (r311: 2010-04-13, 2010-04-20, 2010-05-11, 2010-12-14). The ACROSS
and DOWN columns stand right of the grid (2010-05-11: x 971 on, grid 224-944, y 4562-5265, the page 3601x5789), but the strip
right_columns() tests is 1% ink under its fixed grey cut of 128 (the page's blacks read 65-80, its paper 245; the clue print is
lighter than 128), under RIGHT_INK 0.03, so no right window was tried and the strip under the grid read the Penguin Books advert.
A Gale FT page whose right_columns() refused now gets the strip tried again with the grey cut Otsu's method finds on the grid's own
crop (the page's own blacks and paper), when that cut is above 128. A read-time change: no scan key moves.
Due: a Gale FT row read before the cutoff, refused "no reading parses" with no grid fault, every reader's text "no ACROSS and DOWN
lists under the grid" or none read."""
import re

from fix_reasons import Reason

TEXT = "Gale FT page refused no reading parses, its clue columns right of a light-printed grid judged by the page's own grey cut and read since"
REREAD = "2026-11-27T20:03:00+00:00"  # placeholder: the lander stamps the push minute (UTC)

SHAPE = "no ACROSS and DOWN lists under the grid"


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleFT(200[4-9]|2010)UKEnglish/", rel) or "inputs" not in row \
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
