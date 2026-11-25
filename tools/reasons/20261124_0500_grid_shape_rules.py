"""GRID_SHAPE_RULES: the read-time grid shape tests measure a grid against the page's own widths, not pixel counts.
wide_shaped (a TLS grid right of its clues) takes a grid 0.7-3.0 of its title's width, small_grid (a 1940-41 Times
page printed small) one 0.7-1.05 of it with no pixel floor or ceiling, and loose_shaped (an Independent page scanned
2640-4986px wide) one 0.10-0.425 of the page's width; all three share squared()'s aspect. The pages whose located grid
that moves are listed in tools/data/shape_rules.json (the editions the offline old-vs-new run of the grid location
functions found refused before and read now). Due: a listed edition still refused, read before REREAD."""
import json
from pathlib import Path

from fix_reasons import Reason

TEXT = "grid shape tests sized against the title's or the page's width, not pixels, refused before"
REREAD = "2026-11-25T05:51:00+00:00"
RULES = Path(__file__).resolve().parent.parent / "data" / "shape_rules.json"


def listed():
    return frozenset(json.loads(RULES.read_text(encoding="utf-8"))["editions"])


def due(row):
    import file_archive_org_puzzles as fa
    return (row.get("edition") in listed() and "inputs" in row
            and fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD))
            and any(v.get("refused") for v in row.get("verdicts") or ()))


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, due=due)
