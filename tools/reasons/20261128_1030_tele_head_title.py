"""TELE_HEAD_TITLE (fa.tele_head_titled): a Gale Telegraph page read whole with no title found ("puzzles: [], wholeUntitled", no
verdict), looked over by tele_sol_titled (TELE_SOL_LOOKED) and still untitled. r317 cluster 10: 92 open rows, of three shapes by
the cached whole-page reads: 41 pages with no puzzle at all (news or advertisements: no ACROSS heading, under six clue counts;
listed for the fetcher as missing-page candidates, not fixable here), 8 whose title the strict read dropped, and the rest
without any number printed over the cryptic. The 8: a themed title line ("ALL SAINTS DAY CROSSWORD-No.17,668",
"CHRISTMAS CROSSWORD -No.16.788"), a bare number line ("19,153"), or the day before's "Solution Ne. 19,152" with its "No"
misread, which tele_sol_titled's strict regexes (a clean "No.", a number alone, EVERY page reader agreeing) took none of; and
a page whose cryptic heading the OCR lost, the Quick's caption over its own ACROSS, so only the clue block's heading
(clue_block_heading, both readers agreeing) stands for the box. tele_head_titled reads the same cached page reads with those
forms, one number in all, within the paper's slack of the date's, read twice (two readers or two lines), a page of six clue
counts. Outside scan(): no scan key moves. Due: a row tele_sol_stale (now: not yet looked over by tele_head_titled) whose
cached reads tele_head_titled titles (tele_head_would_title), not due for an older specific reason; scanned again, then read."""
import re

from fix_reasons import Reason

TEXT = "Gale Telegraph page with no title found, its themed title line, bare number or misread solution heading read since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleTelegraph\d{4}UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    return fa.tele_head_stale(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
