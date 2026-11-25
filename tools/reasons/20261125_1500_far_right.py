"""FAR_RIGHT: the clue columns right of a pre-2014 Gale Times grid are tried by what the page reads, not its year. The
right strip was read only for 2014 pages and the 2009-13 Saturdays (clues_may_be_right): elsewhere it was vetoed, because
the strip right of a grid at the page's foot is often an advert column (1947-48 pages read for clue columns from the ads).
The years now only ORDER the windows: the right strip is the last window ("farright", _read_window's alt), tried once the
layout's is poor (crop_window.poor) and taken only if it scores better (_read_best). A page that files is untouched. Due:
a Gale Times edition before 2014 whose verdicts show a grid or column refusal (no-reading-parses, or a light "no clue
read for it"), read before REREAD; a row an older, specific reason makes due keeps it."""
from fix_reasons import Reason

TEXT = "Gale Times page before 2014 refused for its clue columns, the strip right of the grid tried on it as a last window since"
REREAD = "2026-11-19T23:59:00+00:00"


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if fa.paper_of(rel).key != "gale" or "inputs" not in row or fa.Path(rel).name[:4] >= "2014" \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    for v in row.get("verdicts") or ():
        if v.get("cause") == "no-reading-parses":
            return True
        blank = v.get("blank")
        if isinstance(blank, dict) and any("no clue read for it" in str(w) or "no reading laid a clue" in str(w)
                                           for w in blank.values()):
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
