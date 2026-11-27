"""TELE_LEFT_CUT (fa.tele_left_edge): a Gale Telegraph 1969-77 page refused "no reading parses", its unparsed text "cannot find a
clue number at: 'lesmanfound under net (12) ...'" (r308: ~49 editions, 1974-09-25). The ACROSS list's numbers stand left of the
edge clues_left() sets (the grid's left less the margin: x 383 of a grid from x 423, the print from x 313), so the crop cut
every ACROSS line's first 6-7 letters with its clue number. The edge is now measured: when print crosses it, it moves left to
the white gutter before the leftmost ink of the columns' rows (no year table gates it). A read-time change: no scan key moves.
Due: a Gale Telegraph 1969-77 row read before the cutoff with a verdict refused "no reading parses" whose unparsed text holds
"cannot find a clue number"."""
import re

from fix_reasons import Reason

TEXT = "Gale Telegraph 1969-77 page refused no reading parses with its ACROSS clue numbers cut off, its clue columns' left edge measured from the ink since"
REREAD = "2026-11-27T18:00:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleTelegraph(196[9]|197[0-7])UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    for v in row.get("verdicts") or ():
        if v.get("refused") != "no reading parses":
            continue
        if any("cannot find a clue number" in str(t) for t in (v.get("unparsed") or {}).values()):
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
