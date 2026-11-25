"""INDY_NEAR_MEASURED (fa.indy_near): the Gale Independent third clue column beside the grid opens at the grid's edge + 5 where
its own clue numbers (indy_starts' group) stand left of the usual opening (the edge + 15), measured on the page, not only on the
2002-03 pages the first of them were found in (INDY_NEAR_YEARS). A 1996-2004 page with the same print (1998-06-24, 2001-05-09:
number starts 8-11 px right of the grid's edge) lost those numbers' clues outside its window ("no reading laid a clue on it").
Offline over 300 cached pages: 29 repairs (their number starts gained), 28 neutral (2002-03 pages whose numbers stand 15 px or
more out: the gap held no word), 0 regressions. Read-time only: no scan or solution key moves. Due: an Independent page outside
2002-03 (those read since INDY_NEAR), not filed, a down light "no reading laid a clue on it", whose cached right-of-grid
window holds two or more lone clue numbers that close to its edge."""
import json
import re

from fix_reasons import Reason

TEXT = "Independent page whose third clue column's numbers stood left of its window by measure, read since"
REREAD = "2026-11-19T23:59:00+00:00"
NUMBER = re.compile(r"\d{1,2}$")
YEARS = re.compile(r"GaleIndependent(?!200[23])(199[6-9]|20[01]\d)UKEnglish/")


def near_numbers(key):
    import file_archive_org_puzzles as fa
    for which in ("ch", "en5"):
        try:
            held = json.loads((fa.CROPS / "rapid" / f"{key}.{fa.reader_key(which)}.json").read_text())
            for o in [held, *held.get("more", ())]:
                box = o["box"]
                if len(box) != 4 or box[0] < 800 or box[3] - box[1] < 600:
                    continue
                if sum(1 for w in o["words"] if NUMBER.match(str(w[4]).strip()) and 0 <= float(w[0]) - box[0] < 10) >= 2:
                    return True
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            continue
    return False


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not YEARS.match(rel) or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    for v in row.get("verdicts", ()):
        blank = v.get("blank")
        if v.get("refused") or v.get("skip") or not v.get("id") or v.get("number") is None or not isinstance(blank, dict):
            continue
        if any(k.endswith("-down") and "no reading laid a clue" in str(why) for k, why in blank.items()) \
                and near_numbers(f"{rel.split('/')[1]}_{v['number']}") \
                and not (fa.filed_state(v["id"].rsplit("-", 1)[0], v.get("number")) or (False, False))[1]:
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, due=due)
