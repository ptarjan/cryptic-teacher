"""INDY_PAIR (fa.indy_under_pair): a Gale Independent 2010-13 page whose print sets two clue columns under the grid and a chess
box right of them (2011-10-10 No 7795: numbers at x 614 and 918 under a grid from 161 to 881, the box at x 1256). overhang()
took the box for a third clue column and over_gutters() cut the span in thirds; the second gutter (944) fell between the second
column's numbers (918-940) and its text (948), so the first window held the first column and the second's numbers, and 1, 5,
9, 10, 12-14 across laid on no light ("no reading laid a clue on it", the file unfiled with blank clues). The gutter is now cut
just left of the second column's numbers. A held blank clue takes the reread's words through improves() (a reading that keeps
every held clue and answer and adds the blanks replaces the file), and corrected_clues() leaves held words alone.
Due: such a page (2010-13), a light "no reading laid a clue on it", not filed, whose cached window under the grid holds two
print columns of clue numbers (INDY_CUT_DEPTH below the ACROSS heading), the first at least INDY_CUT_NEAR px from the
window's left edge."""
import json
import re
from fix_reasons import Reason

TEXT = "Independent 2010-13 page whose two clue columns under the grid stood right of its thirds, their gutter cut at their numbers since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the push minute (UTC)
INDY_CUT_NEAR, INDY_CUT_DEPTH = 250, 900


def under_heads(key):
    import file_archive_org_puzzles as fa
    for which in ("ch", "en5"):
        try:
            held = json.loads((fa.CROPS / "rapid" / f"{key}.{fa.reader_key(which)}.json").read_text())
            wins = [(o["box"], o.get("words") or ()) for o in (held, *held.get("more", ()))]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        for box, words in wins:
            try:
                if len(box) != 4 or box[3] - box[1] < 1000 or box[0] > 400:
                    continue
                words = [(float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])) for w in words]
                head = [w for w in words if fa.clue_text.heading_of(w[4]) == "ACROSS"]
                if not head:
                    continue
                top = min(w[1] for w in head)
                heads = [g[len(g) // 2] for g in fa.indy_starts(words, box[0], 1e9, top, top + INDY_CUT_DEPTH) if len(g) >= fa.INDY_COLUMN_MIN]
            except (ValueError, TypeError, IndexError):
                continue
            if len(heads) >= 2 and min(heads) - box[0] >= INDY_CUT_NEAR:
                return True
    return False


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not re.match(r"GaleIndependent201[0-3]UKEnglish/", rel) \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    for v in row.get("verdicts", ()):
        blank = v.get("blank")
        if v.get("refused") or v.get("skip") or not v.get("id") or v.get("number") is None or not isinstance(blank, dict):
            continue
        if any("no reading laid a clue" in str(why) for why in blank.values()) \
                and under_heads(f"{rel.split('/')[1]}_{v['number']}") \
                and not (fa.filed_state(v["id"].rsplit("-", 1)[0], v.get("number")) or (False, False))[1]:
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
