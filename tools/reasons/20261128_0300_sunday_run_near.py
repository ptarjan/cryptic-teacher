"""SUNDAY_RUN_NEAR (fa.sunday_read_title, sunday_no_labels): a Gale Sunday Times page read whole with no title
found ("puzzles: [], wholeUntitled", no verdict), r314 census cluster 6: 142 rows (1970-74 46, 1975-79 26, 1980-84 23, 1965-69 20).
Shapes of the 142, off the cached whole-page reads of both readers and the filed weekly run: 21 already titled by SUNDAY_ACROSS_LABEL
(ledger rows with sundayLooked, a verdict the census does not count); 12 more whose heading or label gives the run-implied number
but the finders asked for it only within the slack of the paper's date-expected number, which stands 15-35 off the real number on
1970-86 pages ("ACROSS 2231" a line under its word, "No.2601" torn from its heading, "Crossword No 3840", "ACROSS 2832" with
expected 2850). 58 pages hold a clue column (8 or more
enumerations in both readers) and no heading word or number at all (the 1970-75 heading lost to the reader): left, no title box to
place the grid by; 31 pages hold no clue column (TV listings, property ads, Brain-Teaser): the wrong page, dates for the fetcher room; the other 19 a number one off the run's or fewer than 8 enumerations.
The titling now asks sunday_headings_loose, sunday_across_labels and the new sunday_no_labels (a number after "No"/"ACROSS"/
"Crossword" in a block of near lines, no "solution" word) again for the number the run implies: that number from any reader
titles the page (weeklyRun); a number near it does not (tried, 2 of the filed pages it hit were one off). Outside scan(): no scan key moves; the downstream read holds the number to its neighbours (placed). Due: the 12 rows
of tools/data/sunday_implied_title.json. General rule, no year or paper special case."""
import re

from fix_reasons import Reason

TEXT = "Gale Sunday Times page with no title found, titled since from a heading or label giving the number the filed weekly run implies"
REREAD = "2026-11-28T03:52:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleSundayTimes\d{4}UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    return fa.sunday_stale(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
