"""INDY_DEEP_OVER: a Gale Independent page whose Down list ran on in a third clue column under the grid that no window read
(r318 cluster 6, shape A: ~24 rows, 1996-2004; 1999-12-03 No 4096 read 22 of 29 clues, down 15-23 blank).
Measured on the cached leaf's ink, not an image read: beside the grid's foot a box or white space leaves overhang()'s band
(0.05-0.6 of the grid's width under the foot) clean (0.00-0.02 against OVER_INK 0.03), while the band under it, to 1.0 of the
width, is inked like text (0.13-0.26), the third column starting there at x 900-1250; the plain window ended at the grid's
right edge + RIGHT_REACH and the right-hand windows at y 4519, so no reading held it.
Fix (read-time, read_page's window choice; scan boxes and keys unchanged): general rule, no year gate: where overhang() finds no
third column and overhang_deep() (the same band test and column end, one band lower) does, a "deepover" window with the third
column is tried after the layout's, only where its read is poor (blank lights), and kept only if _read_best scores it better,
so a page that files is untouched by construction.
Due: a Gale Independent daily row with 4+ lights "no reading laid a clue on it", all down and none under 14 (the list's tail),
read before the cutoff."""
from fix_reasons import Reason

TEXT = "Independent page whose Down list's third column stood lower under the grid than the band looked at, read from a window with it since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = str((row or {}).get("edition") or "")
    if not rel.startswith("GaleIndependent") or rel.startswith("GaleIndependentSunday") or "inputs" not in row:
        return False
    for v in row.get("verdicts") or ():
        blank = v.get("blank")
        if v.get("refused") or v.get("skip") or not isinstance(blank, dict):
            continue
        lights = [k for k, why in blank.items() if "no reading laid a clue" in str(why)]
        nums = [(k.split("-")[0], k.split("-")[-1]) for k in lights]
        if len(lights) >= 4 and all(d == "down" and n.isdigit() and int(n) >= 14 for n, d in nums):
            return fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)) and not fa.specific_fix_reason(row)
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
