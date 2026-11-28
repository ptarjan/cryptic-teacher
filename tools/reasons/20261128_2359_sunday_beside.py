"""SUNDAY_BESIDE (fa._read_window, the Sunday Times column cascade): a Gale Sunday Times page refused "no reading parses" ("no ACROSS
and DOWN lists under the grid") whose grid stands right of its title banner (locate_grid side "right", the grid's top in the
banner's own band), the ACROSS and DOWN headings side by side under the title, left of the grid (r318: about a quarter of the 84
open rows, 2002-11 to 2005 and scattered 1990s pages).
Cause: every column reader in the cascade needs side "below", so the side-by-side pair (sunday_times_pair, which the 2000-06 pages
that sit under their title already read) was never tried for a grid beside the title; only the prose to the right was read.
Fix (read-time; scan boxes and keys unchanged): a shaped grid whose top is in the title's band with the headings level and two
numbered columns left of it (the pair reader's own evidence) is read as below its title with those columns. A year only orders it.
Due: a Gale Sunday Times row refused no-reading-parses, read before the cutoff."""
from fix_reasons import Reason

TEXT = "Gale Sunday Times page refused no reading parses, its grid right of the title with the ACROSS and DOWN columns side by side under it read since"
REREAD = "2026-11-28T14:30:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = str((row or {}).get("edition") or "")
    if not rel.startswith("GaleSundayTimes") or "inputs" not in row:
        return False
    if not any(v.get("cause") == "no-reading-parses" for v in row.get("verdicts") or ()):
        return False
    return fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)) and not fa.specific_fix_reason(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
