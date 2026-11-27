"""INDY_UNDER_RUN (fa.indy_under): a Gale Independent page with one clue column right of its grid and two under it had that
right window read only INDY_RIGHT_DROP (0.55) grid heights under the grid's foot, while the column's last clues run on
below it to the page's foot (1995-07-18 No 2729: window foot y 4689, the column's lines to y 4925; 19, 20, 22, 25 down
"no reading laid a clue on it"). r306: 89 of the 209 Independent pages with 4+ lights "no reading laid a clue on it" had
that shape (1995-2003), the right window's words reaching its foot and an under window a column's height lower. The right
window is now read down to the plain window's foot (1.8 grid widths under the grid) when a word of its clue column ends
within INDY_UNDER_RUN line heights of the old foot. Rule: a clue column's window runs as far as the print under it does.
Due: an Independent page, not filed, a light "no reading laid a clue on it", whose cached windows hold a right window
(left of it an under window, its foot lower by a line or more of lines) with words ending at its foot."""
import json
import re

from fix_reasons import Reason

TEXT = "Independent page whose right clue column ran on past its window's foot, the window read down to the page's clue foot since"
REREAD = "2026-11-27T16:25:00+00:00"
YEARS = re.compile(r"GaleIndependent(199\d|200\d|201\d)UKEnglish/")
RUN = 2


def cut_right(key):
    import file_archive_org_puzzles as fa
    for which in ("ch", "en5"):
        try:
            held = json.loads((fa.CROPS / "rapid" / f"{key}.{fa.reader_key(which)}.json").read_text())
        except (OSError, ValueError):
            continue
        try:
            wins = [held, *held.get("more", ())]
            under = [o["box"] for o in wins if len(o["box"]) == 4 and o["box"][3] - o["box"][1] > 600
                     and o["box"][0] < 0.25 * o["box"][2]]
            for o in wins:
                box = o["box"]
                if len(box) != 4 or not o["words"] or not under:
                    continue
                if not any(u[2] - 80 <= box[0] <= u[2] + 40 and box[1] < u[1] and u[3] >= box[3] + 100 for u in under):
                    continue
                heights = sorted(float(w[3]) - float(w[1]) for w in o["words"])
                line = heights[len(heights) // 2]
                if any(float(w[3]) >= box[3] - RUN * line for w in o["words"]):
                    return True
        except (KeyError, TypeError, IndexError, ValueError):
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
                and cut_right(f"{rel.split('/')[1]}_{v['number']}") \
                and not (fa.filed_state(v["id"].rsplit("-", 1)[0], v.get("number")) or (False, False))[1]:
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
