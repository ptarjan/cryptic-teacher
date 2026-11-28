"""INDY_TWO_LINE (fa.indy_two_line, read by fa.indy_titled): a Gale Independent page of 1993-12..1994-12 scanned to no puzzle whose
crossword heading stands on two lines, "THE INDEPENDENT Crossword" in big capitals over "No. 2297 ... by Aelred" (the number first
at the left, the setter apart). r314 (11-27): 186 of the 188 GaleIndependent 1990-94 rows "no verdict/no puzzle found" hold the
heading (the crossword is on the page: none is a wrong-article fetch); independent_headings reads only a heading whose one line
holds the number, and the readers split this one's lines (or ran the neighbour column's words onto its title line, and misread
"No." as "o.", "[o.", "0."), so no reader gave a title, and indy_titled's two-reader rule found none.
General rule (no year gate): a line opening "No. NNNN" (any misread of "No", or none), NNNN within the paper's slack of the date's
number, with "by <setter>" after it or beside it on the same row, standing under a printed line holding INDEPENDENT CROSSWORD (its
top above the number line's, within 10 banner heights; the Saturday prize crossword's number sits on the ACROSS/DOWN row under
the entry coupon) is a heading; the number stands when two or more readers (ch, en5, times; strips and whole-page reads) give it. Read after scan() (scan_anywhere), so no scan key moves.
Due: a Gale Independent (daily) row read with no verdict, a scan (not failed) under a current key wholeUntitled with no puzzle,
not yet stamped INDY_TWO_LINE_LOOKED, read before the push. Its scan is stale: scanned again once, then read."""
from fix_reasons import Reason

TEXT = "Gale Independent page whose two-line heading (THE INDEPENDENT Crossword over No. NNNN by Setter) went untitled, read since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def rescan(row):
    import file_archive_org_puzzles as fa
    scan = (row or {}).get("scan") or {}
    rel = str(row.get("edition") or "")
    if not (fa.GALE_INDEPENDENT.item.match(rel.split("/")[0]) and "inputs" in row and not row.get("verdicts")
            and not scan.get("failed") and scan.get(fa.WHOLE_UNTITLED) and not scan.get("puzzles")
            and not scan.get(fa.INDY_TWO_LINE_LOOKED)):
        return False
    return row.get("scanKey") in fa.current_keys(fa.GALE_INDEPENDENT) and fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD))


def due(row):
    import file_archive_org_puzzles as fa
    return rescan(row) and not fa.specific_fix_reason(row)


REASON = Reason(TEXT, rank=1, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due, rescan=rescan)
