"""FT_EDGE_FAR (fa.ft_clear_edge): a Gale FT page whose second clue column is inked past the edge right_columns set (more than
FT_EDGE_REACH of the grid's width, 0.12) lost the tails of its lines and the head of the third column's. 2004-10-13 No 11659: the
edge at x 1682, the second column's lines to x 1773 (91 px, 0.13 grids of 716), the third column from x 1800: the third window
(1682-2076) held the second column's last words ("ve-boat", "villa in") over the third's lines, ft_clear_edge found no ink-free
pixel columns within its reach and kept the edge where it was, and 19, 22, 23, 24, 27 down stood "no reading laid a clue on it".
The search for the gutter goes on to FT_EDGE_FAR (0.22) of the grid's width when the near one finds none. Read-time only (scan
never reads these windows): no scan key moves.
Cause tally of the 110 Gale FT rows "blanks(4+): no reading laid a clue on it" (r316, none due or planned): 15 third-column
numbered rising (FT_THIRD_RISING, landing), 49 no third-column read (1982-87 layouts with the clues right of the earlier solution
grid, 2000-03 across lists missing their top lines), 46 a third read with no rising numbered lines (7 of them this edge, the rest
cut lines or a first-clue stray), so the biggest shape not covered by a landing fix is this one among the down-tail rows.
Due: a Gale FT row read before the cutoff with a down light no reading laid whose third-column cache holds the second column's
words more than FT_EDGE_REACH of the grid's width (0.2 of the third window's width) right of its box's left edge."""
import re

from fix_reasons import Reason

TEXT = "Gale FT page with its second clue column running past the column edge, the gutter searched for further out"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def bled(words, box):
    """How far (px) from `box`' left edge the words of the clue column left of the third column's numbered lines run."""
    import statistics
    starts = [w[0] for w in words if re.match(r"^\W{0,2}\d{1,2}(\s|[A-Z\"']|$)", str(w[4])) and len(str(w[4])) >= 2 and w[0] > box[0] + 3]
    if len(starts) < 3:
        return 0
    col = statistics.median(starts)
    near = [s for s in starts if abs(s - col) < 25]
    if len(near) < 3:
        return 0
    col = statistics.median(near)
    top = box[1] + 0.8 * (box[3] - box[1])
    return max([w[2] for w in words if w[2] < col - 8 and w[3] - w[1] > 12 and w[1] < top], default=box[0]) - box[0]


def due(row):
    import glob
    import json
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleFT(19|20)\d\dUKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    for v in row.get("verdicts") or ():
        if not any(str(k).endswith("-down") and "no reading laid" in str(w) for k, w in (v.get("blank") or {}).items()):
            continue
        for f in glob.glob(str(fa.CROPS / "rapid" / f"{rel.split('/')[-1]}_{v.get('number')}.*.third.json")):
            try:
                d = json.load(open(f))
                box = d["box"]
                words = d["words"]
            except (OSError, ValueError, KeyError):
                continue
            if bled(words, box) > 0.2 * (box[2] - box[0]):
                return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
