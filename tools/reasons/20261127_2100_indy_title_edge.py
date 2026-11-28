"""INDY_TITLE_EDGE (fa.indy_title_kept): an Independent page's lead window was trimmed at a blank run inside its clue column
(2007-12-08: x 315 of an ACROSS column at x 203 under a title from x 170), so the ACROSS list's heading and heads were lost.
Due: a page, a puzzle refused "no reading parses" whose title box starts left of x 400 and whose readings failed for no
ACROSS and DOWN lists / unparsed clue lists / no clue words, read before the push, that no other fix is due for."""
import re
from fix_reasons import Reason

TEXT = "Independent page whose clue column left of its grid was cut inside its first words, read from the title's edge since"
REREAD = "2026-11-27T22:23:00+00:00"  

def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not re.match(r"GaleIndependent\d{4}UKEnglish/", rel) or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    boxes = {p.get("number"): p.get("box") for p in (row.get("scan") or {}).get("puzzles") or ()}
    series = fa.paper_of(rel).series
    for v in row.get("verdicts", ()):
        box = boxes.get(v.get("number"))
        if v.get("refused") == "no reading parses" and not v.get("skip") and v.get("number") is not None and box \
                and box[0] < 400 and fa.filed_state(series, v["number"]) is None:
            return fa.specific_fix_reason(row) is None
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
