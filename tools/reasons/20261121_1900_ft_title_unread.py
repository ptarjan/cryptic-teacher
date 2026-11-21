"""FT_TITLE_UNREAD: an archive.org FT 1985-94 edition whose scan titled a puzzle (the title bands, or ft_right_titled's band
right of the grid, read it) but whose read never gave a verdict (census r303: 24 rows, 1989-94, scanned 11-17). The old
UNREAD_TITLES reread was due only for rows read before 2026-10-28, so these stood unread though unread_titles(row) holds:
no verdict, no solutions-only read, none of the titled puzzles held. Due: such a row, read before the cutoff."""
import re
from fix_reasons import Reason

TEXT = "archive.org FT page whose title the scan found but whose puzzle was never read, read since"
REREAD = "2026-11-19T23:59:00+00:00"
EDITION = re.compile(r"FinancialTimes19(8[5-9]|9[0-4])UKEnglish/")


def due(row):
    import file_archive_org_puzzles as fa
    scan = row.get("scan") or {}
    if not EDITION.match(str(row.get("edition") or "")) or "inputs" not in row or row.get("verdicts") \
            or scan.get("failed") or not scan.get("puzzles"):
        return False
    return fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)) and fa.unread_titles(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, kept=True, due=due)
