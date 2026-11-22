"""INDY_SIDE_RIGHT (fa.indy_side_right): a Gale Independent 2000-04 page whose grid stands left of its title with the clue
columns right of the grid under the title (2001-02-26 No 4480: grid x 270-1364, title 1391-2192, three columns from x 1391).
Only Times-family pages read the strip right of a "left" grid; the Independent's were read from a crop left of it (0 words),
refused "no reading parses" (~48 pages 2001-03). Due: such a page, a puzzle not filed, refused "no reading parses", whose
title box starts right of x 1300 and is at least 700 px wide."""
import re
from fix_reasons import Reason

TEXT = "Independent 2000-04 page whose grid stood left of its title, its clue columns right of the grid read since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not re.match(r"GaleIndependent200[0-4]UKEnglish/", rel) \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    boxes = {p.get("number"): p.get("box") for p in (row.get("scan") or {}).get("puzzles") or ()}
    series = fa.paper_of(rel).series
    for v in row.get("verdicts", ()):
        box = boxes.get(v.get("number"))
        if v.get("refused") == "no reading parses" and not v.get("skip") and v.get("number") is not None and box \
                and box[0] >= 1300 and box[2] - box[0] >= 700 and fa.filed_state(series, v["number"]) is None:
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
