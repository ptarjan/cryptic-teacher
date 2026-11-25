"""SUNDAY_LAYOUTS_ANY_YEAR: the Gale Sunday Times layout readers (scaled_under, sunday_times_over / _mid / _band / _column /
_pair / _right / _live, the title-grid, caption and tall-grid readers) are tried on every page whose located grid or clue
column failed, whatever its year; they were each gated to the years they were found in (1960-67, 1965-69, 1968-76, 1976-78,
1980-84, 1985-89, 1985-94, 2000-06). A page's own evidence accepts or refuses a candidate (a lattice, the grid's shape, the
heading's level, the numbered lines of a column); the years only order them (the page's own first, the others after), so a
page another candidate reads keeps that read. Due: a Gale Sunday Times edition refused "not a grid" or "no reading parses"
whatever its year, read before REREAD (each old reason's own rows are due by their own gates)."""
from fix_reasons import Reason

TEXT = "Gale Sunday Times page of any year refused not a grid or no reading parses, every layout reader tried on it since"
REREAD = "2026-11-19T23:59:00+00:00"


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if fa.paper_of(rel).key != "galesundaytimes" or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    return any(v.get("cause") in ("not-a-grid", "no-reading-parses") for v in row.get("verdicts") or ())


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, due=due)
