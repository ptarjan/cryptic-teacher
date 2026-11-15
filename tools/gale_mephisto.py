"""The Sunday Times' Mephisto puzzles on Gale's Sunday Times Historical Archive (STHA).

Mephisto (the barred-grid cryptic) is printed in the Sunday Times' magazine
section from 1957 (No. 29 is 1958-03-02, No. 107 1961-03-05; fortnightly at first, its solution the Sunday after) and the archive ends with 2006. One
row per Sunday of each of two kinds (gale_docs.MEPHISTO_KIND, the puzzle's
page, and MEPHISTO_SOLUTION_KIND, the "Solution to Mephisto Crossword No N"
page): a Sunday with none is a cached miss, so wanted() lists them all.
tools/gale_fetch.py saves the PDFs under "Gale crosswords/Mephisto/Fetched" and
".../Solutions" (the layout of TimesJumbo) for the desktop's reader.
"""
import datetime

FIRST, LAST = datetime.date(1957, 1, 6), datetime.date(2006, 12, 31)


def wanted():
    """[date] of each Sunday from FIRST to LAST, newest first."""
    d = FIRST
    out = []
    while d <= LAST:
        out.append(d)
        d += datetime.timedelta(days=7)
    return out[::-1]
