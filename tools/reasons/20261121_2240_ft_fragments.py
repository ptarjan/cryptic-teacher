"""FT_FRAGMENTS (fa.ft_fragments_mended, in corrected_clues): a held Gale FT clue with words cut INSIDE it ("Express
disapproval, ing prohibition, for prim", "Moving boats with po from port", "do wi out", "good st for baby", "unchar 100
in type of bog", "the p-1 on gas": ftcryptic-11399, 2003-12-10) was never replaced by a reread that reads it whole:
ft_cut_restored wants more words than the held clue has and corrects() takes one gained word. A dry read of
GaleFT2003UKEnglish/2003-12-10 after the ft_clear_edge fix gives all 28 clues whole, so the held text was the gate.
The held fragments (a start or end of the next word, a split word, a digit speck) now give way to the whole clue.
Due: the Gale FT editions whose held files show 2+ lowercase non-word tokens in a clue (hyphenated words aside), or one
with a digit; scan keys unmoved."""
from fix_reasons import Reason

TEXT = "a held Gale FT clue with words cut inside it (fragments, a split word), filed as clean"
REREAD = "2026-11-21T22:42:00+00:00"
DATES = frozenset((
    "1989-11-23", "1990-04-10", "1991-07-17", "1992-07-24", "1992-09-03",
    "1993-02-01", "1993-07-01", "1993-07-08", "1993-07-28", "1993-08-04",
    "1993-11-02", "1994-02-05", "1994-05-19", "1995-07-13", "1998-04-27",
    "1999-03-20", "1999-08-20", "2000-05-19", "2000-07-05", "2001-05-02",
    "2001-09-05", "2001-10-04", "2001-12-04", "2002-03-13", "2002-06-14",
    "2002-07-10", "2002-07-13", "2003-01-29", "2003-01-31", "2003-04-30",
    "2003-06-20", "2003-08-09", "2003-09-23", "2003-10-22", "2003-12-10",
    "2003-12-31", "2004-02-06", "2004-03-11", "2004-03-16", "2004-03-23",
    "2004-03-25", "2004-05-07", "2004-05-27", "2004-06-02", "2004-06-03",
    "2004-07-08", "2004-08-13", "2004-09-23", "2004-10-22", "2005-01-07",
    "2005-03-21", "2005-11-10", "2006-06-09", "2007-06-13", "2007-07-25",
    "2008-01-19", "2008-07-14", "2008-12-31", "2009-05-06", "2009-10-21",
    "2009-12-09", "2010-03-03", "2010-04-12"))


def due(row):
    import file_archive_org_puzzles as fa
    edition = str(row.get("edition") or "")
    return (edition.startswith("GaleFT") and edition.rsplit("/", 1)[-1] in DATES
            and fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)))


REASON = Reason(TEXT, rank=2, fix_landed=True, kept=True, due=due)
