"""SUNDAY_LOOSE_TITLE (fa.sunday_titled): a Gale Sunday Times page read whole with no title found ("puzzles: [], wholeUntitled", no
verdict). r311: 172 open rows (1970-74 47, 1980-84 34, 1975-79 32, 1965-69 25, the rest 1960-2009), one ledger shape. Cause on the
1973-74 pages (1974-12-29 No 2601): both whole-page readers tear the heading, "SUNDAYTIMES" over "rossword" and "No.2601" whose
boxes overlap, so printed_lines gives each its own line and no line holds the title (joined_titles wants the number right of the
word); others read "Mo." or "CROSSWDRD", or lose the heading's word (not helped here). The scan now looks the cached whole-page reads
over once (sunday_titled, outside scan(): no scan key moves, no filed page is scanned again) and titles a page whose page readers all
give one number near the date's for a block of near lines holding a word like "crossword" and a number, no solution word. Titled
only where scan() titled none; the downstream read still holds the number to its neighbours (placed). Due: such a row (sunday_stale)
not due for an older specific reason, scanned again once, then read. Shapes left: pages whose cached reads hold no heading at all
(about 115 of the 172: 1980-84 number-beside-ACROSS pages, pages of another article), unmeasured here."""
import re

from fix_reasons import Reason

TEXT = "Gale Sunday Times page with no title found, its torn crossword heading read from the cached page reads since"
REREAD = "2026-11-27T21:53:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


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
