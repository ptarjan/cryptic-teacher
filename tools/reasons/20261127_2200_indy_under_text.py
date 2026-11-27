"""INDY_UNDER_TEXT (fa.indy_texty, fa.indy_under_heads, fa.indy_under_pitch): a Gale Independent page whose ACROSS list opens in a
column under the grid (the heading's x over its numbers) and runs on in a column right of the grid, with a puzzle of digits (the
Sudoku, 2011-01-24 No 7573: 322 boxes, its digits in columns of nine) printed under the same grid. indy_under() counted the
Sudoku's digit columns as clue columns (22 heads against the one), the pitch of its last two matched nothing and the plain window's
ACROSS list (1 to 17) was never joined to the right column: "no reading laid a clue on it", 1-17 across blank (r313: ~35 Independent
2010-11 pages). A number start counts as a clue column's only when it opens a line of words (own letters, or the next box on its
row has them), and ONE such column under the grid, the ACROSS heading over it, with one right of the grid, is a pair.
Due: an Independent row read before the cutoff, unfiled, a verdict with 4+ lights "no reading laid a clue on it", whose cached
windows give one print column of clue numbers right of the grid, ACROSS under the grid, and under heads that pass
indy_under_pitch() by the text rule but not by the plain count."""
import re

from fix_reasons import Reason

TEXT = "Independent page whose ACROSS list under the grid was lost among a Sudoku's digit columns, its clue columns joined since"
REREAD = "2026-11-27T22:23:00+00:00"  # placeholder: the lander stamps the push minute (UTC)
MARGIN = 40


def windows(key):
    import file_archive_org_puzzles as fa
    import json
    try:
        held = json.loads((fa.CROPS / "rapid" / f"{key}.{fa.reader_key('en5')}.json").read_text())
        wins = [(held["box"], held["words"]), *((o["box"], o.get("words") or ()) for o in held.get("more") or ())]
        return [(b, [(float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])) for w in ws]) for b, ws in wins
                if len(b) == 4 and ws]
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return []


def changed(key):
    """Whether the cached windows of `key` give an under-grid pair the text rule joins and the plain count does not."""
    import file_archive_org_puzzles as fa
    from clue_text import heading_of
    wins = windows(key)
    if not wins:
        return False
    under_win = min(wins, key=lambda bw: (bw[0][0], -len(bw[1])))
    rights = [bw for bw in wins if bw[0][0] > under_win[0][0] + 300 and bw[0][1] < under_win[0][1]]
    if not rights:
        return False
    right = max(rights, key=lambda bw: len(bw[1]))
    gx0, gx1, gy1 = under_win[0][0] + MARGIN, right[0][0] - 5, under_win[0][1]
    beside = [g for g in fa.indy_starts(right[1], gx1 + fa.INDY_NEAR_X, right[0][2], right[0][1], right[0][3])
              if len(g) >= fa.INDY_COLUMN_MIN]
    big = max((len(g) for g in beside), default=0)
    heads = [g[len(g) // 2] for g in beside if len(g) >= fa.INDY_COLUMN_THIN * big]
    if len(heads) != 1:
        return False
    acr = [w[0] for w in under_win[1] if heading_of(w[4]) == "ACROSS" and gx0 - MARGIN <= w[0] < gx1 and w[1] >= gy1]
    if not acr:
        return False
    plain = fa.indy_under_pitch(fa.indy_under_heads(under_win[1], gx0, gx1, gy1, MARGIN), heads[0], acr)
    texty = fa.indy_under_pitch(fa.indy_under_heads(under_win[1], gx0, gx1, gy1, MARGIN, True), heads[0], acr, True)
    return plain is None and texty is not None


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleIndependent\d{4}UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    series = fa.paper_of(rel).series
    for v in row.get("verdicts") or ():
        blank = v.get("blank")
        if v.get("refused") or v.get("skip") or v.get("number") is None or not isinstance(blank, dict) \
                or sum("no reading laid a clue" in str(w) for w in blank.values()) < 4 \
                or fa.filed_state(series, v["number"]) is not None:
            continue
        if changed(f"{rel.split('/')[1]}_{v['number']}"):
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
