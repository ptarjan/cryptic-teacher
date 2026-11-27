"""INDY_INDENT_LEAD (fa.indy_indent_lead): a Gale Independent page whose grid is set in from its title (2004-02-02 No 5395: title x
184-982, grid x 584-1306) has its ACROSS list in a column left of the grid and DOWN on under it; the plain window's overhang() took
the print right of the grid for a third column, so the window began at the grid and the left column was never read ("no ACROSS and
DOWN lists under the grid", r307: 40 of 77 Independent 2000-04 pages refused no reading parses). The ("plain", "flat") window, read
from the lead column with no overhang, is tried since. Rule: a grid set in from its title by TITLE_INDENT with text inked left of it.
Due: such a page, not filed, refused "no reading parses" with every unparsed value "no ACROSS and DOWN lists", whose cached under-grid
window starts at the grid's edge (40 px margin) at least TITLE_INDENT of the title's width right of the title's left edge."""
import json

from PIL import Image
import re

from fix_reasons import Reason

TEXT = "Independent page whose clue column stood left of its grid under its title, read from that column since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the push minute (UTC)
MARGIN = 40


def grid_lefts(key):
    import file_archive_org_puzzles as fa
    try:
        held = json.loads((fa.CROPS / "rapid" / f"{key}.{fa.reader_key('en5')}.json").read_text())
        wins = [held, *held.get("more", ())]
        return [o["box"][0] + MARGIN for o in wins if len(o["box"]) == 4 and o["box"][3] - o["box"][1] > 600
                and o["box"][0] > 0]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not re.match(r"GaleIndependent\d{4}UKEnglish/", rel) or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False
    boxes = {p.get("number"): p.get("box") for p in (row.get("scan") or {}).get("puzzles") or ()}
    series = fa.paper_of(rel).series
    for v in row.get("verdicts", ()):
        box = boxes.get(v.get("number"))
        un = [str(x) for x in (v.get("unparsed") or {}).values()]
        if v.get("refused") != "no reading parses" or v.get("skip") or v.get("number") is None or not box or not un \
                or not all("no ACROSS and DOWN lists" in x for x in un) or fa.filed_state(series, v["number"]) is not None:
            continue
        lefts = grid_lefts(f"{rel.split('/')[1]}_{v['number']}")
        # the grid's width: its cached image is the grid box 6 px over on every side (a window right of the grid starts a
        # grid's width or more in from the title, not the grid's own edge)
        try:
            gw = Image.open(fa.CROPS / "grids" / f"{rel.split('/')[1]}_{v['number']}.png").width - 12
        except OSError:
            continue
        if any(fa.TITLE_INDENT * gw <= gx0 - box[0] < gw for gx0 in lefts):
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
