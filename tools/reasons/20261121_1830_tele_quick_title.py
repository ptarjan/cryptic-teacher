"""TELE_QUICK_TITLE (fa.tele_quick_title): a Gale Telegraph 1980-99 page refused "the ink under the title is ~480x500, not
a grid" (census r302: 122 rows, 1982-85 mostly, read 11-18..21; 13 in r301). Its scan, made before gale_telegraph_headings
stopped taking the Quick crossword's ACROSS (under its QUICK CROSSWORD caption) for the cryptic's title, stands under a
pinned scan key: the title box is that one word (~105x40 px, y ~4300 under the SOLUTION heading) and the grid under it the
Quick's 13x13. TELEQUICK/TELE_GRID/TELE_OVER were due only for 1985-89 rows read before their cutoffs, and TELE_OVER finds no
ACROSS/DOWN row (the cryptic's heading is lost to art). The read now takes the cryptic's clue-block heading over the
caption when both page readers find it (a read-time change: no scan key moves). Due: a Gale Telegraph 1980-99 row with a
verdict refused "not a grid" whose title box is one word wide (WORD), read before the cutoff."""
import re
from fix_reasons import Reason

TEXT = "a Gale Telegraph page refused not a grid for the Quick crossword's ink (its title box the Quick's ACROSS), the cryptic's clue block heading read since"
REREAD = "2026-11-19T23:59:00+00:00"
WORD = 150


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not re.match(r"GaleTelegraph(198\d|199\d)UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    boxes = {p.get("number"): p.get("box") for p in (row.get("scan") or {}).get("puzzles") or ()}
    for v in row.get("verdicts") or ():
        box = boxes.get(v.get("number")) or boxes.get(v.get("read_as"))
        if v.get("cause") == "not-a-grid" and str(v.get("refused") or "").startswith("the ink under the title is ") \
                and "titleBox" not in v and box and box[2] - box[0] <= WORD:
            return True
    return False


REASON = Reason(TEXT, rank=2, fix_landed=True, kept=True, due=due)
