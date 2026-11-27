"""TELE_NUMBERED_HEAD (fa.tele_early_heading): a Gale Telegraph 1970-79 page whose clue lists were cut at the title box's top (the
Quick crossword's ACROSS or a clue line) because the cryptic's heading row was not found. r307: 160 rows 1970-79 (1974-12-24,
1975-01-03), 4+ lights "no reading laid a clue on it" scattered through both lists, not the lists' first clues, so TELE_EARLY_HEAD
(1975-89, one blank numbered 1-3) never claimed them, and 1970-74 lay outside its years. These pages head the cryptic with one row,
"No. 15,250 ACROSS", and no DOWN heading (the down column starts at its first clue under it); tele_early_heading looked for a
lone DOWN word, and the lone one the band holds is the Quick's, under its caption, so the heading was lost and the columns started
at the Quick's title. It now takes the one row of the band that names a puzzle number before ACROSS, and TELE_EARLY_YEARS starts
at 1970. A read-time change: no scan key moves. Due: a Gale Telegraph 1970-79 row read before the cutoff, not complete or refused,
written unfiled with 4+ lights "no reading laid a clue on it"."""
import re

from fix_reasons import Reason

TEXT = "Gale Telegraph 1970-79 page whose clue lists were cut at the Quick's title (its 'No. N ACROSS' heading unfound), the columns' top set at that heading since"
REREAD = "2026-11-27T16:47:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleTelegraph197\dUKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    for v in row.get("verdicts") or ():
        blank = v.get("blank")
        if not isinstance(blank, dict) or v.get("complete") or not v.get("lights") or v.get("refused") or not v.get("unfiled"):
            continue
        if sum(1 for why in blank.values() if str(why).startswith("no reading laid a clue on it")) >= 4:
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
