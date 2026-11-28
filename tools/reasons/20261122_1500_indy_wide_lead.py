"""INDY_WIDE_LEAD (fa.indy_wide_lead): a Gale Independent 2005-08 Saturday page whose title box is about 1830 px wide (x 160-190)
over a grid set in from it (x 810-1550), its ACROSS and DOWN columns left of the grid (x 200, 530) and the Concise right of it
(2007-01-27 No 6328). INDY_OVER_PLAIN's overhang() took the Concise's print under the grid's right edge for a third column, so the
plain window was cut under the grid and the lead window from x 0 (cropFrom "gutter") that had filed 2007-01-13 and -20 on 11-11
was never read: ~45 pages refused "no reading parses" ("no ACROSS and DOWN lists under the grid" / "no clue words").
Due: such a page, a puzzle not filed, refused "no reading parses", whose title box is at least 1400 px wide and starts left of
x 400, and that no other fix is due for (fa.specific_fix_reason asked first: the older, specific reasons win, as for the any-year reasons)."""
import re
from fix_reasons import Reason

TEXT = "Independent page whose clue columns stood left of its grid under a wide title, read from them since"
REREAD = "2026-11-22T13:55:00+00:00"  # placeholder: the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not re.match(r"GaleIndependent200[5-8]UKEnglish/", rel) \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    boxes = {p.get("number"): p.get("box") for p in (row.get("scan") or {}).get("puzzles") or ()}
    series = fa.paper_of(rel).series
    for v in row.get("verdicts", ()):
        box = boxes.get(v.get("number"))
        if v.get("refused") == "no reading parses" and not v.get("skip") and v.get("number") is not None and box \
                and box[0] < 400 and box[2] - box[0] >= 1400 and fa.filed_state(series, v["number"]) is None:
            return fa.specific_fix_reason(row) is None
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
