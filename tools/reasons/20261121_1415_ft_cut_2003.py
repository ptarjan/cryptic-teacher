"""FT_EDGE (fa.ft_clear_edge, in ft_foot and ft_third_column): a Gale FT page whose second clue column runs past
right_columns' fixed span was read through windows that cut its lines at x1 and its third column at x1 + 0.55 grids:
2003-12-10 (ftcryptic-11399, filed 11-20, withdrawn) and 2003-12-09 (ftcryptic-11398) read "for prim", "good st",
"unchar", "churc", "he sa now put on the kettle", "do wi out" (the lines' last word cut at x 1769 and 2165, the
words' middles lost where a window edge met a reading's boxes). x1 and the third edge now move out to the first
ink-free gutter. The cut clues are replaced through corrects()/ft_cut_restored; scan keys unmoved.
Due: the Gale FT editions the 2000-09 held files show with 4+ lowercase non-word clue fragments."""
from fix_reasons import Reason

TEXT = "a Gale FT page's clue columns cut at a fixed edge through their last words, clues filed cut"
REREAD = "2026-11-21T20:21:00+00:00"
EDITIONS = frozenset(f"GaleFT{d[:4]}UKEnglish/{d}" for d in (
    "2003-12-09", "2003-12-10", "2003-01-29", "2003-01-31", "2003-06-20", "2003-06-25", "2004-06-02",
    "2008-11-24", "2008-11-07", "2001-12-04"))


def due(row):
    import file_archive_org_puzzles as fa
    return (row.get("edition") in EDITIONS and fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)))


REASON = Reason(TEXT, rank=2, fix_landed=True, kept=True, due=due)
