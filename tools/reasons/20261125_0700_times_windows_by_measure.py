"""TIMES_WINDOWS_BY_MEASURE: the Gale Times four-column "quarters" window, and the clue block's "block" and "halves"
windows, are tried by what the page measures, not its year. "quarters" was tried first for 1936-40 only (QUARTER_ALT_YEARS)
and "block" / "halves" for 1930-49 (block_year): now "quarters" whenever the ink under the grid holds all three gutters
at about 0.25 / 0.5 / 0.75 of the grid's width (quarter_gutters), and "block" / "halves" whenever the layout's crop is
wider than the RapidOCR down-scale cap at read_words' 2x (block_wide) or those gutters are found. A page that reads keeps
its read (the windows are alternatives, tried once the layout's leaves a light blank). Due: a Gale Times edition outside the
old years (before 1930 or after 1949) whose verdicts show a grid or column refusal (not-a-grid, no-reading-parses, or a
light "no clue read for it"), read before REREAD; a row an older, specific reason makes due keeps it."""
from fix_reasons import Reason

TEXT = "Gale Times page of any year refused for its grid or clue columns, the quarters and block windows tried on it by measure since"
REREAD = "2026-11-25T09:36:00+00:00"
OLD_YEARS = ("1930", "1949")


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if fa.paper_of(rel).key != "gale" or "inputs" not in row \
            or OLD_YEARS[0] <= fa.Path(rel).name[:4] <= OLD_YEARS[1] \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    for v in row.get("verdicts") or ():
        if v.get("cause") in ("not-a-grid", "no-reading-parses"):
            return True
        blank = v.get("blank")
        if isinstance(blank, dict) and any("no clue read for it" in str(w) or "no reading laid a clue" in str(w)
                                           for w in blank.values()):
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
