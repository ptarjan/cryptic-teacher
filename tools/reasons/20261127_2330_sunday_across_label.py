"""SUNDAY_ACROSS_LABEL (fa.sunday_read_title / sunday_across_labels): a Gale Sunday Times page read whole with no title found
("puzzles: [], wholeUntitled", no verdict), r313 census cluster 4: 172 rows (1970-74 47, 1980-84 34, 1975-79 32, 1965-69 25).
The torn-heading fix (SUNDAY_LOOSE_TITLE) re-read the 30 whose cached reads hold a crossword-word heading; 30 of the 172 now
hold a verdict (varied: not-a-grid, no reading parses, number-date mismatch). Shapes of the 142 left, off the cached
whole-page reads (both readers): ~43 pages with no crossword text at all (TV listings, Brain-Teaser, another article: no puzzle in
the scan, dates sent to the fetcher room), ~36 a crossword word but no number near the date's, ~15 a number but no heading word
(1967-68 pages: bare number beside "Solution TO No. N-1"), ~25 heading torn with the readers giving different numbers (digit
misreads, 2255/2256, 2405 for 2465: left, a lone reader's digits are not trusted), 16 the clue column's own label "ACROSS No. 2833"
(1976-2000, the heading lost). That last shape and the torn headings whose readers disagree are titled now, but only to the number the filed weekly run around the date implies (sunday_implied; run-implied equalled the filed number on 1569 of 1579 filed pages, the rest filed misreads): where scan() and the loose heading find none, a number any reader gives (heading or an ACROSS No. label)
that the run implies titles the page. Due: the 22 rows of tools/data/sunday_run_title.json. Outside scan(): no scan key moves; the
downstream read holds the number to its neighbours (placed, weekly run). Due: such a row (sunday_stale) not due for an older
specific reason, scanned again once. General rule, no year or paper special case."""
import re

from fix_reasons import Reason

TEXT = "Gale Sunday Times page with no title found, titled since from its cached page reads and the filed weekly run"
REREAD = "2026-11-28T02:03:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


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
