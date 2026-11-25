"""UNDER_CROSSING: the 1950-59 Gale Times two clue columns under the grid are split at the gutter with fewer words
crossing it, the UNDER_FIFTIES window's or the usual middle window's (ties keep UNDER_FIFTIES'), not always the fixed
0.25-0.45 share window: a 1950-52 page's columns split at the middle, and the share window put the gutter where 30
words crossed it, against 1. Due: only the pages in tools/data/under_crossing_pages.json (the cached windows whose chosen
gutter changes), read before REREAD; a row an older, specific reason makes due keeps it."""
import json
from fix_reasons import Reason

TEXT = "Gale Times 1950-59 page whose clue columns under the grid are split at the gutter with fewer words crossing it since"
REREAD = "2026-11-25T13:04:00+00:00"
PAGES_FILE = "under_crossing_pages.json"


def pages():
    import file_archive_org_puzzles as fa
    here = fa.Path(__file__).resolve().parent.parent / "data" / PAGES_FILE
    return frozenset(json.loads(here.read_text())["pages"])


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if fa.paper_of(rel).key != "gale" or "inputs" not in row \
            or not "1950" <= fa.Path(rel).name[:4] <= "1959" \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    date = fa.Path(rel).name
    held = pages()
    numbers = {v.get("number") for v in row.get("verdicts") or ()}
    numbers |= {p.get("number") for p in (row.get("scan") or {}).get("puzzles", ())}
    if not any(f"{date}_{n}" in held for n in numbers if n is not None):
        return False
    return not fa.specific_fix_reason(row)  # an older, specific reason makes the row due: it keeps the row and its rank


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
