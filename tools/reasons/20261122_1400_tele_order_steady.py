"""TELE_ORDER_STEADY (fa.filed_number): a Gale Telegraph 1975-99 page refused "No N on DATE is out of date order with No
15302 on 1975-03-05 and No 18106 on 1984-06-12" (census r304 cluster 27: 60 rows 1980-84, mostly 1984-03..09). The
Telegraph run of those years is nearly all unfiled, and 1984-06-12 had filed a misread title, 18106 for 18166 (one reader,
the solution heading prints 18105/10165 for 18165), so that page was the only filed neighbour after every earlier spring
page: all of 18107..18165 were out of date order with it. The same stray holds 18106's real number (1984-04-02) as filed
for another day. filed_number placed titles among the steadily offset filed numbers for the FT alone (Held.steady, whose
spike test drops a number 60 off both its neighbours' offsets); the Telegraph now does too. A read-time change: no scan key
moves. Due: a Telegraph 1970-99 row refused out of date order / already filed for another day, read before the cutoff.
The misfiled telegraph-18106 itself is not shifted."""
from fix_reasons import Reason

TEXT = "Gale Telegraph page refused out of date order with a misfiled neighbour, placed among the steady neighbours since"
REREAD = "2026-11-22T13:11:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import re
    import file_archive_org_puzzles as fa
    edition = (row or {}).get("edition") or ""
    if not re.match(r"GaleTelegraph(19[7-9]\d)UKEnglish/", edition) or "inputs" not in row:
        return False
    return any(v.get("cause") == "number-date-mismatch"
               and ("out of date order" in str(v.get("refused")) or " is already filed for " in str(v.get("refused")))
               for v in row.get("verdicts") or ()) \
        and fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD))


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
