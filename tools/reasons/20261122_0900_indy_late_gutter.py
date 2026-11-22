"""INDY_LATE_GUTTER (fa.indy_under_columns): a Gale Independent page with three evenly pitched clue columns under/beside
its grid whose second gutter lay right of the third column's clue numbers (2003-08-13 No 5248: heads at x 214, 582, 953,
gutters 574 and 986), so the third column's numbers joined the second column's window and 4-8, 13, 14, 19, 20 down laid on
no light ("no reading laid a clue on it"). The second gutter is now cut just left of the third head. Due: such a page
(2000-14), a light "no reading laid a clue on it", not filed, whose cached window holds three evenly pitched print columns
of clue numbers (at least INDY_LATE_MIN starts each) and whose last column's numbers lie 8-40 px right of the grid's edge."""
import json
import re
from fix_reasons import Reason

TEXT = "Independent page whose third clue column's numbers stood in the second window, its second gutter cut at them since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the push minute (UTC)
INDY_LATE_MIN = 5


def three_heads(key):
    import file_archive_org_puzzles as fa
    for which in ("ch", "en5"):
        try:
            held = json.loads((fa.CROPS / "rapid" / f"{key}.{fa.reader_key(which)}.json").read_text())
            for o in (held, *held.get("more", ())):
                words = [(float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])) for w in o.get("words") or ()]
                if not words:
                    continue
                top = min(w[1] for w in words)
                heads = [g[len(g) // 2] for g in fa.indy_starts(words, 0, 1e9, top, 1e9) if len(g) >= INDY_LATE_MIN]
                if len(heads) != 3:
                    continue
                p = (heads[1] - heads[0], heads[2] - heads[1])
                if min(p) >= 150 and abs(p[0] - p[1]) <= 0.25 * max(p):
                    return True
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            continue
    return False


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not re.match(r"GaleIndependent(200\d|201[0-4])UKEnglish/", rel) \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    for v in row.get("verdicts", ()):
        blank = v.get("blank")
        if v.get("refused") or v.get("skip") or not v.get("id") or v.get("number") is None or not isinstance(blank, dict):
            continue
        if any("no reading laid a clue" in str(why) for why in blank.values()) \
                and three_heads(f"{rel.split('/')[1]}_{v['number']}") \
                and not (fa.filed_state(v["id"].rsplit("-", 1)[0], v.get("number")) or (False, False))[1]:
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, due=due)
