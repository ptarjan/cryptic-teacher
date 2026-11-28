"""SUNTEL_TITLE (fa.suntel_titled): a Gale Sunday Telegraph page scanned to no puzzle ("puzzles: [], wholeUntitled", no verdict).
r314 (11-27): 61 of the paper's 1990-94 unfiled rows; 59 of the 61 cached pages hold ACROSS and DOWN lists (the crossword is on the
page, none is a wrong-page fetch) but the scan's crops found no title line: the page's "PRIZE PUZZLE No N" is a graphic or sits
where no crop reads it. Two cached whole-page facts give the number. (1) A title line (sunday_tel_headings) the whole-page reads
hold that the scan's crops did not (1990-01-28 "PRIZEPUZZLE1495", 1992-03-22, 1993-08-15, 1994-05-01). (2) The bare "COMPETITION No N"
solution heading (SUNDAY_TEL_BARE, no colon) of the puzzle a week back, one under this page's: it titles the page N + 1 (the
1990-92 note: 101 of 102 pages; here 172 of 172 filed 1990-2000 pages whose cached reads give one, 35 of 35 for 1990-94, 0 wrong).
General rule (no year or paper gate beyond Gale Sunday Telegraph): a number stands only when it lies within the paper's slack of
the date's expected number AND fits the filed run (suntel_run_fits: nearest filed neighbours either side, above the one before by
1..weeks since it, below the one after by 1..weeks until it, the one number where the run between them is unbroken) AND is the only
such number on the page; a misread ("1585", "3678", "173") fails the run. Read after scan() (scan_anywhere), so no scan key moves.
Due: a Gale Sunday Telegraph row read with no verdict, a scan (not failed) under a current key wholeUntitled with no puzzle, not yet
stamped SUNTEL_TITLE_LOOKED, read before the push, whose cached reads give suntel_title_of a number. Scanned again once, then read."""
from fix_reasons import Reason

TEXT = "Gale Sunday Telegraph page with no title found, its title line or bare COMPETITION No N solution heading read from the cached page reads since"
REREAD = "2026-11-28T04:35:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def rescan(row):
    import file_archive_org_puzzles as fa
    scan = (row or {}).get("scan") or {}
    rel = str(row.get("edition") or "")
    if not (fa.GALE_SUNDAY_TELEGRAPH.item.match(rel.split("/")[0]) and "inputs" in row and not row.get("verdicts")
            and not scan.get("failed") and scan.get(fa.WHOLE_UNTITLED) and not scan.get("puzzles")
            and not scan.get(fa.SUNTEL_TITLE_LOOKED)):
        return False
    return row.get("scanKey") in fa.current_keys(fa.GALE_SUNDAY_TELEGRAPH) \
        and fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)) and fa.suntel_title_of(rel) is not None


def due(row):
    import file_archive_org_puzzles as fa
    return rescan(row) and not fa.specific_fix_reason(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due, rescan=rescan)
