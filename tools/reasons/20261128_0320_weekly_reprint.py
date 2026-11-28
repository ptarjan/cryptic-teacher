"""WEEKLY_REPRINT (fa.weekly_reprint): an archive.org Guardian edition read with no puzzle and no verdict ("puzzles: [],
wholeUntitled"/guardianRead), 104 in census r316 ("no verdict/no puzzle found"; 97 of 1995-99). Tallied by shape from the
cached pages (r316/guardian): 36 are Guardian Weekly pages ("The Guardian Supplement") printing the clues of a cryptic already
held as cryptic-N (a held puzzle's clues read on the page at 70% of their word pairs, 8+ clues and
35%+ of that puzzle's clues; 33 pages one puzzle, 3 two), with no number, no solution and no title the scan could number;
33 more Weekly pages have a cryptic heading and clues, matching no held puzzle within 120 days (the reprinted daily is not held:
the fetcher room's list, not a reader miss); 22 Weekly pages hold only the Quick (or no heading); 13 daily pages are wrong-page
or Quick/solution-only fetches. A reprint is recognised by its clue text, not a heading, and recorded on the scan
(reprintOf [held ids], weeklyLooked): nothing is filed (the puzzle is held; a copy is never written), and the census counts a
row whose scan has reprintOf as filed, like a heldSkip row. Read after scan() (scan_anywhere), so no scan key moves.
Due: a Guardian archive.org row read with no verdict, a scan (not failed) under a current key holding no puzzle and not yet
stamped weeklyLooked, read before the push. Scanned again once (a text-only look: no image is read), then read."""
from fix_reasons import Reason

TEXT = "archive.org Guardian page with no puzzle, its clues matched to the held cryptics a Guardian Weekly reprints since"
REREAD = "2026-11-28T08:05:00+00:00"  # the lander stamps the push minute (UTC)


def rescan(row):
    import file_archive_org_puzzles as fa
    scan = (row or {}).get("scan") or {}
    if not (str(scan.get("item", "")).startswith("TheGuardian") and "inputs" in row and not row.get("verdicts")
            and not scan.get("failed") and not scan.get("puzzles") and not scan.get(fa.WEEKLY_LOOKED)):
        return False
    return row.get("scanKey") in fa.current_keys(fa.GUARDIAN) and fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD))


def due(row):
    import file_archive_org_puzzles as fa
    return rescan(row) and not fa.specific_fix_reason(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due, rescan=rescan)
