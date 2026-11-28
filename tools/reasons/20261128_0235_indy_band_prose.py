"""INDY_BAND_PROSE (fa.indy_band_edge: INDY_BAND_HEIGHTS 5.0 -> 2.5 with the count-end test; r314): a Gale Independent 2010-12 window
right of the grid whose single clue column (x 1875-2475 on 2010-07-12 No 7406) stands left of two article columns in the same
window, the blank band between them only ~3 line heights wide. The article's lines ran row by row into the clue lines (ACROSS 1, 5,
9-17 and DOWN 22/24 laid by no reading, "no reading laid a clue on it"; 2010-09-13's DOWN list stopped "cannot find a clue number
at: 'legal at all, since if he wasn't legally'", article prose in the same column).
Rule (measured page property, no year gate): the window is cut at the middle of a blank x-run 2.5+ median box heights wide, twice
wider than any blank run left of it, with 4+ clue-number starts left of it and, right of it, under 4 numbered clue openings AND
under 4 count-ended tokens ("(4,5)"): a second clue column (8-28 counts on the filed 2004-05 pages) is never cut.
Due: an Independent row read before the cutoff, unfiled, a verdict with 4+ lights "no reading laid a clue on it", whose cached
en5 window (or any of its windows) gives such a band, and that no older specific reason (INDY_BAND_CUT's too) is due for."""
import re

from fix_reasons import Reason

TEXT = "Independent page whose clue column stood beside article columns in its window, cut at the blank band between them since"
REREAD = "2026-11-28T03:08:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


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
