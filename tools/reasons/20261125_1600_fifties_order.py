"""FIFTIES_ORDER: the gutter between the two clue columns under a 1950-59 Gale Times grid is sought in the decade's window
(UNDER_FIFTIES, 0.25-0.45 of the grid's width: that decade's first column is the narrower), whatever the page. On a 1950-52 page
the columns split at the middle and that window put the gutter at 0.40-0.45 (1952-07-28: 30 words crossed it, against 1 at the
default window's). The year now only ORDERS the windows: the decade's stays first, and the default window's gutter is the last
window ("plainunder", _read_window's alt), tried once the first is poor (crop_window.poor) and taken only if it scores better
(_read_best): a page that files is untouched. Due: a Gale Times edition of 1950-59 whose verdicts show a grid or column refusal
(no-reading-parses, or a light "no clue read for it"), read before REREAD; a row an older, specific reason makes due keeps it,
and FAR_RIGHT's rows are left to it."""
from fix_reasons import Reason, registered

TEXT = "Gale Times 1950-59 page refused for its clue columns, the under-grid gutter of the default window tried on it as a last window since"
REREAD = "2026-11-19T23:59:00+00:00"


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if fa.paper_of(rel).key != "gale" or "inputs" not in row or not "1950" <= fa.Path(rel).name[:4] <= "1959" \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    if registered()["20261125_1500_far_right"].due(row):
        return False  # FAR_RIGHT's row: it defers to that reason
    for v in row.get("verdicts") or ():
        if v.get("cause") == "no-reading-parses":
            return True
        blank = v.get("blank")
        if isinstance(blank, dict) and any("no clue read for it" in str(w) or "no reading laid a clue" in str(w)
                                           for w in blank.values()):
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
