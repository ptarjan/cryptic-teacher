"""INDY_NEAR (fa.indy_under's ThirdFrom): a Gale Independent 2002-03 page whose third clue column stands beside the grid
with its clue numbers 0-9 px past the window's left edge (the grid's edge + 5; windows_of opened the column at + 15), so
those numbers (5, 6, 8, 9, 16, 17 down on 2002-07-10) fell outside it and their clues laid on no light. 2002-07-10 read
28 of 30 agreed, 29 clues (19 agreed, 24 clues before; readers only). Due: such a page, a down light "no reading laid a
clue on it", not filed, whose cached right-of-grid window holds two or more lone clue numbers that close to its edge."""
import json
import re
from fix_reasons import Reason

TEXT = "Independent 2002-03 page whose third clue column's numbers stood left of its window, read since"
REREAD = "2026-11-21T19:18:00+00:00"
NUMBER = re.compile(r"\d{1,2}$")


def near_numbers(key):
    import file_archive_org_puzzles as fa
    for which in ("ch", "en5"):
        try:
            held = json.loads((fa.CROPS / "rapid" / f"{key}.{fa.reader_key(which)}.json").read_text())
            wins = [held, *held.get("more", ())]
            for o in wins:
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
    if not re.match(r"GaleIndependent200[23]UKEnglish/", rel) \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
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
