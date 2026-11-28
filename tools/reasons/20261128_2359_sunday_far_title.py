"""SUNDAY_FAR_TITLE (fa.sunday_titled): a Gale Sunday Times page whose scan title is no number near its date's was refused
"No 2 is not near the 2485 the date implies" and never titled by the page-heading reader. r318 (11-28): 1972-74 titles read as
the first digits of a split "No. 2 516" ("2", "25"), 1976-85 titles that are a clue's number after "Crossword" ("Through the Looking
Crossword 12 Weighed down": 12): the page's own heading ("THE SUNDAY TIMES CROSSWORD No. 2516", "ACROSS No. N") is in the cached
whole-page reads. Rule: sunday_titled skips a scan only when it holds a title within the paper's slack of its date's number
(sunday_near_titled); a title further off counts as none, so sunday_read_title (every reader agreeing on a heading near the date,
or the label / "No N" matching the filed weekly run) titles the page, and the near-date check judges its number as for any page.
Filed pages cannot change: a filed title was near its date (or mended from its solution heading) and a row is rescanned only where
every verdict refused "is not near the". Read after scan() (scan_anywhere): no scan key moves.
Due: such a row read before the push whose cached reads give sunday_far_title_of a number."""
from fix_reasons import Reason

TEXT = "Gale Sunday Times title off its date (a clue's number, a split heading) read again from the cached page-heading reads"
REREAD = "2026-11-28T14:05:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def rescan(row):
    import file_archive_org_puzzles as fa
    return fa.sunday_far_stale(row) and fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)) \
        and fa.sunday_far_title_of(str(row.get("edition")), row["scan"]) is not None


def due(row):
    import file_archive_org_puzzles as fa
    return rescan(row) and not fa.specific_fix_reason(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, blanket=True, kept=True, due=due, rescan=rescan)
