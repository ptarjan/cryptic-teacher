"""TELE_SOL_TITLE (fa.tele_sol_titled): a Gale Telegraph page read whole with no title found ("puzzles: [], wholeUntitled", no
verdict). r308: 170 open rows (1970-74 66, 1975-79 30, 1980-84 33, 1985-89 20, 1990-94 21), all one ledger shape. Gale cites
"No. 13,770 across" or "Crossword" for about a third; the rest cite another article (the City page's Financial Crossword, news
of crosswords, an advertisement), whose pages hold no clue lists. On the cryptic's own page the title's number was lost and the
solution heading of the day before ("Solution NO. 13,769") was read with the next column's words run on after its number
("Solution NO. 13,769 MIsNi"), so TELEGRAPH_SOLUTION (the number must end the line) took none, and a page of two ACROSS
headings without a QUICK caption line left gale_telegraph_headings' lone-solution rule no cryptic one. The scan now looks the
cached whole-page reads over once (tele_sol_titled, outside scan(): no scan key moves) and titles a page of at least six clue
counts whose page readers all give one number, from that heading (+1) or a bare "No.19,938" line, at its topmost lone ACROSS
word. Due: such a row (tele_sol_stale) not due for an older specific reason, scanned again once, then read."""
import re

from fix_reasons import Reason

TEXT = "Gale Telegraph page with no title found, its solution heading or bare number line read through the run-on words since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleTelegraph\d{4}UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    return fa.tele_sol_stale(row)


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
