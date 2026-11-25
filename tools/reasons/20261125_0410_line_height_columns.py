"""LINE_HEIGHT_COLUMNS: the clue-column readers' pixel thresholds (GAP, DOWN_GAP, DOWN_FOOT_RUN, HEADING_ROOM, ACROSS_GUTTER,
SPLIT_SLACK) were set for text 30 px high (TYPICAL_LINE) and are now that many lines of the page's own median line height
where it stands more than LINE_JITTER over it (at_line(): never less than the old pixels). A page set in larger print (the
1991-2004 Gale Times and Independents at 33-52 px) had its columns cut after a few lines by a gap of two lines, and a line
crossing its gutter by a line and a half taken for a notice across both columns. Read-time only: no scan or solution key
moves. Due: a refused edition on tools/data/line_height_columns.json (the refused pages with cached OCR whose columns change
under the new thresholds, measured offline on the cached readings of the windows under the grid), read before REREAD."""
import json
from pathlib import Path

from fix_reasons import Reason

TEXT = "page of larger print refused for its columns, the clue-column thresholds scaled to its line height since"
REREAD = "2026-11-25T04:26:00+00:00"
EDITIONS = Path(__file__).resolve().parent.parent / "data" / "line_height_columns.json"
_EDS = []


def editions():
    if not _EDS:
        _EDS.append(frozenset(json.loads(EDITIONS.read_text(encoding="utf-8"))))
    return _EDS[0]


def due(row):
    import file_archive_org_puzzles as fa
    if (row.get("edition") or "") not in editions() or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    return any(v.get("refused") for v in row.get("verdicts") or ())


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, due=due)
