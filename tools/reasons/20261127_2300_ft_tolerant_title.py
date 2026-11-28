"""FT_TOLERANT (fa.ft_tolerant_lines, fa.ft_tolerant_titled): an archive.org FT 1985-94 page scanned to no puzzle whose title band
holds the title with its number line misread. r313 (11-27): of 106 FT editions with no verdict and no puzzle, 7 hold a title all
three readers or two of them read: "PUZZLE :No. 5,733" / "PUZZEE No. 5,733" (1985-06-03), "PUZZLE NG '6,011" / "PUZALE No 6,011"
(1986-05-01), "No. 6,3322" (an extra digit, 1987-05-21), "7,836 Set by GRIFFIN" (no "No", 1992-04-30), "CROSSW" over "No.8,313.Set by"
(1993-11-23), "No.8;334 Set by VIXEN" (a semicolon, 1993-12-17), "No.S.539 Set by HIGHLANDER" (S for 8, 1994-08-23). ft_headings
reads none of them. General rule (no year gate): the title band's lines are mended (PUZZLE misreads, "NG"/"Na" for "No", a truncated
CROSSWORD, "F.T: :", a separator other than a comma, a letter for a figure taken as the figure nearest the date's number, one
extra digit, a missing "No." before "N,NNN Set by") then read by ft_headings; the number stands when half the readers give it
within FT.slack of the date's. Read after scan() (scan_anywhere), so no scan key moves.
Due: an FT 1985-94 edition read (inputs) with no verdict, a scan (not failed) under a current key with no puzzle, not yet stamped
FT_TOLERANT_READ. Its scan is stale: scanned again once, then read."""
from fix_reasons import Reason

TEXT = "archive.org FT page with no puzzle found, its title band's misread number line mended since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def rescan(row):
    import file_archive_org_puzzles as fa
    scan = (row or {}).get("scan") or {}
    if not (fa.FT_RIGHT_EDITION.match(str(row.get("edition") or "")) and "inputs" in row and not row.get("verdicts")
            and not scan.get("failed") and not scan.get(fa.FT_TOLERANT_READ) and not scan.get("puzzles")):
        return False
    return row.get("scanKey") in fa.current_keys(fa.FT) and fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD))


REASON = Reason(TEXT, rank=1, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=rescan, rescan=rescan)
