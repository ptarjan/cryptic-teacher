"""INDY_STRAY_STARTS (fa.indy_print_groups): a Gale Independent (daily) page refused "no reading parses" whose readers all said
"no ACROSS and DOWN lists under the grid" (r318 cluster #7: 103 open rows, 6 whose cached window text opens at DOWN with both
print columns glued row by row, 2003-09-06 the first).
Shape: two clue columns right of the grid (ACROSS at x 986 holding 42 number starts, DOWN at x 1341 holding 31, the window's
gutter beyond them at 1703), plus stray groups of 3-4 number starts (mid-line numbers near one x). indy_two_columns() wants
exactly two groups of INDY_COLUMN_MIN starts left of the gutter, so the strays made it four and it cut nothing: one window held
both columns, the lines read across, and no list parsed.
Rule (shared reader code, no year gate, no fixed px): with more than two groups of starts, a group thinner than INDY_COLUMN_THIN
(0.5) of the second biggest group is no print column and is left out of indy_two_columns()'s decision.
Due: a Gale Independent daily row refused "no reading parses" with a reader's "no ACROSS and DOWN lists" among its unparsed
values, read before the cutoff."""
from fix_reasons import Reason

TEXT = "Independent page whose two clue columns stood in one window under stray number starts, its columns split since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = str((row or {}).get("edition") or "")
    if not rel.startswith("GaleIndependent") or rel.startswith("GaleIndependentSunday") or "inputs" not in row:
        return False
    if not any(v.get("refused") == "no reading parses"
               and any(str(u).startswith("no ACROSS and DOWN lists") for u in (v.get("unparsed") or {}).values())
               for v in row.get("verdicts") or ()):
        return False
    return fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)) and not fa.specific_fix_reason(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
