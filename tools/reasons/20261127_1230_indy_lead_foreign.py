"""INDY_LEAD_FOREIGN (fa.lead_foreign): a Gale Independent clue window right of the grid that opens on a column of other print
(the Saturday's "Last Saturday's solution" box and prize rules, 2014-11-08: x 975-1230 against ACROSS's numbers at 1262) left of
its first column of clue numbers. Its lines shared rows with the clues, so a clue number no longer opened its line and the
clue laid on no light ("no reading laid a clue on it": 22, 24, 25 across). The boxes left of that first column are now
dropped (measured: INDY_LEAD_FOREIGN_MIN or more boxes ending left of it). 2014-11-08 No 8758 read 27 of 28 lights agreed on
a dry read with no VLM (15 before). Due: an Independent page, not filed, a light "no reading laid a clue on it", whose cached
clue window holds such a column (fa.lead_foreign_cut on its words); a row an older, specific reason makes due keeps it."""
import json
import re

from fix_reasons import Reason

TEXT = "Independent page whose clue window opened on a column of other print left of its clue numbers, that print cut since"
REREAD = "2026-11-19T23:59:00+00:00"
YEARS = re.compile(r"GaleIndependent(199\d|20[01]\d)UKEnglish/")


def foreign_lead(key):
    import file_archive_org_puzzles as fa
    for which in ("ch", "en5"):
        try:
            held = json.loads((fa.CROPS / "rapid" / f"{key}.{fa.reader_key(which)}.json").read_text())
            for o in [held, *held.get("more", ())]:
                box = o["box"]
                if len(box) != 4 or box[0] < 800 or box[3] - box[1] < 600:
                    continue
                words = [(float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])) for w in o["words"]]
                if fa.lead_foreign_cut(words, box[0], box[1], box[2], box[3]) is not None:
                    return True
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            continue
    return False


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not YEARS.match(rel) or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    for v in row.get("verdicts", ()):
        blank = v.get("blank")
        if v.get("refused") or v.get("skip") or not v.get("id") or v.get("number") is None or not isinstance(blank, dict):
            continue
        if any("no reading laid a clue" in str(why) for why in blank.values()) \
                and foreign_lead(f"{rel.split('/')[1]}_{v['number']}") \
                and not (fa.filed_state(v["id"].rsplit("-", 1)[0], v.get("number")) or (False, False))[1]:
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
