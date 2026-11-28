"""TELE_QUICK_STACKED (fa.quick_captions): a Gale Telegraph 1970-79 page whose scan titled it by the Quick crossword's ACROSS
and whose Quick grid (a small square lattice under its clue list) read as the puzzle's, so the cryptic's clue lists were
never read (census r314: ~65 rows 1972-77, 10-26 lights "no reading laid a clue on it", the Quick's 20ish clues counted as
the page's, "across clue [1] names no light the grid numbers after the start"). tele_quick_title, the read of the cryptic's
clue block heading over a Quick caption, was tried only for 1980-99 and, for the other years, only where the grid under the
title is not a grid: the Quick's grid is one. Its caption test also needed "QUICK CROSSWORD" on ONE line, but the 1970s
print stacks it ("QUICK" over "CROSSWORD"), so under_quick never held. The read now tries it for every Telegraph year (the
years only order the candidates; the page's own evidence, the caption found, the title box under it, the block heading
agreed by both page readers within TELE_QUICK_AGREE px, decides) and reads a stacked caption as one (quick_captions). A
read-time change: no scan key moves. Due: a Gale Telegraph 1970-89 row with a verdict not complete, no title box taken,
its grid "under its clues, a small square lattice", 4+ lights "no reading laid a clue on it", read before REREAD."""
from fix_reasons import Reason

TEXT = "Gale Telegraph page read on the Quick crossword's grid (its caption stacked over two lines), the cryptic's clue block heading read since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import re
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleTelegraph(19[78]\d)UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    for v in row.get("verdicts") or ():
        blank = v.get("blank")
        if not isinstance(blank, dict) or v.get("complete") or v.get("titleBox") \
                or v.get("gridBox") != "under its clues, a small square lattice":
            continue
        if sum(str(why).startswith("no reading laid a clue on it") for why in blank.values()) >= 4:
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
