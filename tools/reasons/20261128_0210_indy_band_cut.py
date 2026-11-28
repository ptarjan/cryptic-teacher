"""INDY_BAND_CUT (fa.indy_band_edge, fa.indy_band_cut): a Gale Independent window right of the grid whose clue print stands in ONE
narrow column (ACROSS and DOWN lists both, 1998-09-28 No 3727: x 980-1330) with a column of other print (a results table, an
article) far right of it in the same window behind a blank band 12+ line heights wide. right_foreign() looks for other print only
within a fifth of a grid's width of the window's edge, so the table's numbered lines ran into the DOWN list, its parse failed and
1-7 down, 26-27 across were laid by no reading ("no reading laid a clue on it", ~11 pages 1996-99; the dry read gives 28 clues
and 2 blanks, was 17 and 11). The window is cut at the middle of a blank x-run 5+ median box heights wide, twice wider than any
blank run left of it, with 4+ clue-number starts left of it and under 4 numbered clue openings right of it. Measured page
property, no year gate.
Due: an Independent row read before the cutoff, unfiled, a verdict with 4+ lights "no reading laid a clue on it", whose cached
en5 window (or any of its windows) gives such a band, and that no older specific reason is due for."""
import re

from fix_reasons import Reason

TEXT = "Independent page whose single clue column had a column of other print far right in its window, cut at the blank band since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def changed(key):
    """Whether a cached window of `key` has indy_band_edge()'s blank band."""
    import json
    import file_archive_org_puzzles as fa
    try:
        held = json.loads((fa.CROPS / "rapid" / f"{key}.{fa.reader_key('en5')}.json").read_text())
        wins = [held["words"], *(o.get("words") or () for o in held.get("more") or ())]
        return any(fa.indy_band_edge([(float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])) for w in ws]) is not None
                   for ws in wins if ws)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        return False


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
