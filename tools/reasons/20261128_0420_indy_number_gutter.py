"""INDY_NUMBER_GUTTER (fa.number_gutter, OPEN_NUMBERS; r317): a Gale Independent 2001-05 page with two clue columns under its grid
whose numbers are boxes of their own (2004-12-21 No 5672: the DOWN column's numbers at x 1787-1802, its words from 1830, the
ACROSS column's words ending at 1775). under_gutter() cut the two columns at 1825, in the gap between the DOWN numbers and their
words (38 px right of the column's opening, inside opening_gutter's OPEN_MISS 60), and column_start() never saw an opening: its
CLUE_OPENING wants the capital in the number's own box. The DOWN numbers 1-7 read into the ACROSS lines' ends ("speaking at speed
(9) 24" ... "1" "2" "3") and their clues stood without numbers: 5 down, "no reading laid a clue on it", the page left unfiled.
Rule (measured page property, no year gate): a number box whose row neighbour right of it opens with a capital counts as a clue
opening; when no capital-in-the-box opening exists, those number openings stand on OPEN_ROWS+ rows within OPEN_ALIGN px, and the
gutter lies between their right edges and the words' left edges on OPEN_ROWS+ rows, the gutter is sought in the OPEN_REACH px left
of the numbers. A page whose openings were found before is untouched. Of 750 filed Independent pages with cached windows 6 daily
ones trip it (see the commit message for how their reads came out).
Due: an Independent row read before the cutoff, unfiled, with a blank clue and a cached window (indy_number_read) showing the
number box between the gutter and its words, that no older specific reason is due for."""
import re

from fix_reasons import Reason

TEXT = "Independent page whose second clue column under the grid was cut between its numbers and their words, cut left of the numbers since"
REREAD = "2026-11-28T11:06:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


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
        if v.get("refused") or v.get("skip") or v.get("number") is None or not isinstance(blank, dict) or not blank \
                or fa.filed_state(series, v["number"]) is not None:
            continue
        if fa.indy_number_read(f"{rel.split('/')[1]}_{v['number']}"):
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
