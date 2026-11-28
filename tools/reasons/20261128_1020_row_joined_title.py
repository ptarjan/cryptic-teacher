"""ROW_JOINED_TITLE (fa.row_joined_lines in guardian_loose_titles, GUARDIAN_SPELT): an archive.org Guardian weekday edition read
with no puzzle ("puzzles: [], wholeUntitled") whose title the OCR cut in two lines on one printed row: "Guardian Crossi" |
"word No 20,576" (1996-02-15, leaf 15; the fetcher room's 11-28 list of held leaves), each half a line of its own, so no
line held "crossword" and a number together. The title reader now also tries every run of lines starting on one row (within
ROW_JOIN_RISE px of height, each at most ROW_JOIN_GAP right of the end of the one before), and GUARDIAN_SPELT lets a stray
letter sit between "Cross" and "word" ("Crossiword"). A general rule: no edition or year is named.
r317 Guardian census (110 rows, 6 planned): 15 no-puzzle rows are Sunday Guardian Weekly pages (weekly_reprint looked, nothing
to title: not this fix), 5 weekday no-puzzle rows are read for this: 1996-02-15 gets its title (number 20,576); 1985-06-22
prints "THE GUARDIAN PRIZE / PUZZLE 17,269" (another form), 1997-04-28 the garbled "uiuaraian urosswora no zu,>>4>>" and
1997-05-07 has no title in its text at all: they stay untitled. Outside scan(): no scan key moves.
Due: a Guardian archive.org weekday row read with no verdict, a scan (not failed) under a current key holding no puzzle,
stamped GUARDIAN_READ but not GUARDIAN_JOINED, read before the push. Scanned again once (text only), then read."""
from fix_reasons import Reason

TEXT = "archive.org Guardian page with no puzzle, its title cut in two lines on one row joined since"
REREAD = "2026-11-28T10:22:00+00:00"  # the lander stamps the push minute (UTC)


def rescan(row):
    import datetime
    import file_archive_org_puzzles as fa
    scan = (row or {}).get("scan") or {}
    try:
        sunday = datetime.date.fromisoformat(str(scan.get("date"))).weekday() == 6
    except ValueError:
        return False
    if not (str(scan.get("item", "")).startswith("TheGuardian") and "inputs" in row and not row.get("verdicts")
            and not scan.get("failed") and scan.get(fa.GUARDIAN_READ) and not scan.get(fa.GUARDIAN_JOINED)
            and not scan.get("puzzles") and not sunday):
        return False
    return row.get("scanKey") in fa.current_keys(fa.GUARDIAN) and fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD))


def due(row):
    import file_archive_org_puzzles as fa
    return rescan(row) and not fa.specific_fix_reason(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due, rescan=rescan)
