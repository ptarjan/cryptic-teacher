"""TELE_REACH_WIDE (fa.tele_left_edge, TELE_CUT_REACH 0.2 -> 0.5): a Gale Telegraph 1969-77 page refused "no reading parses" whose
every reading was "no ACROSS and DOWN lists under the grid" (r310: 16 of the 69 1970-74 rows, no grid fault in the verdict:
1972-05-05, 1971-01-26, 1973-01-12). The ACROSS column's print starts further left of the edge clues_left() sets than
TELE_LEFT_CUT looked (1972-05-05: the gutter at x 240, the edge at 439, 0.28 of the grid's width; TELE_CUT_REACH was 0.2), so the
crop still cut every ACROSS line's number and first letters and no list parsed. The edge now walks up to half the grid's width
for the white gutter. A read-time change: no scan key moves. Dry read of 1972-05-05: "no reading parses" before; 32 clues, 32
lights agreed, a puzzle laid after.
Due: a Gale Telegraph 1969-77 row read before the cutoff with a verdict refused "no reading parses" with no grid fault
(imageUnread, gridBox) whose unparsed text is "no ACROSS and DOWN lists under the grid" or "cannot find a clue number"."""
import re

from fix_reasons import Reason

TEXT = "Gale Telegraph 1969-77 page refused no reading parses with its ACROSS column's left part cut off, the columns' left edge searched further left since"
REREAD = "2026-11-27T18:36:00+00:00"  # placeholder: the lander stamps the push minute (UTC)

SHAPES = ("no ACROSS and DOWN lists under the grid", "cannot find a clue number")


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleTelegraph(196[9]|197[0-7])UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    for v in row.get("verdicts") or ():
        if v.get("refused") != "no reading parses" or v.get("imageUnread") or v.get("gridBox"):
            continue
        texts = [str(t) for t in (v.get("unparsed") or {}).values()]
        if texts and all(any(s in t for s in SHAPES) for t in texts):
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
