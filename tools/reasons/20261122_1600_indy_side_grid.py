"""INDY_SIDE_GRID (fa.located_loose, fa.indy_title_grid): a Gale Independent 2000-04 page whose title stands right of a photograph
the scan's locate_grid took for the live grid ("left"): the real grid, 720px under the title, was passed over as the day's
solution (LIVE_OVER_SOLUTION: the picture, 1.5 times as wide, dwarfs it). 2001-02-26 No 4480: "left" box x 270-1364 (a dark
picture, no lattice), the grid x 1797-2517 under the title x 1391-2192; "too few neighbouring white cells" / "only N white cells
found", then "no grid: the search found no grid" (42 pages 2000-04). Due: such a page, a puzzle not filed, its grid image unread
for a lattice it could not measure, whose title box starts right of x 1300 and is at least 700 px wide."""
import re
from fix_reasons import Reason

TEXT = "Independent 2000-04 page whose grid under its title was taken for a solution beside a picture, the grid under the title read since"
REREAD = "2026-11-22T21:15:00+00:00"  # placeholder: the push minute (UTC)


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
        if not v.get("skip") and v.get("number") is not None and not v.get("wrote") and box \
                and box[0] >= 1300 and box[2] - box[0] >= 700 and fa.filed_state(series, v["number"]) is None \
                and str(v.get("imageUnread") or "").startswith(("too few neighbouring white cells", "only ")):
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
