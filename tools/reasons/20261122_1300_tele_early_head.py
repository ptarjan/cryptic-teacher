"""TELE_EARLY_HEAD (fa.tele_early_heading): a Gale Telegraph 1975-89 page whose grid read but whose clue lists were cut at
the title box's top, mid-list (census r304: 169 rows 1979-89, 120 of them 1980-84; 10-16 of 28-32 clues laid, 1-across,
1-down and each list's first clues "no reading laid a clue on it"). The scan's title box lay on a clue line (1983-10-25: y 3162,
the heading "No. 18,329 ACROSS / DOWN" at y 2861) or, since TELE_QUICK_TITLE, was the block heading found from the first run
of clue counts in a band whose reader returned no word over y 3190 (1984-12-19). TELE_HEAD raised the columns' top to the
cryptic's heading only for 1990-2000, through telegraph_over_title, which declines a title box far over the SOLUTION
heading. tele_head_top now reads, for 1975-89, a narrow band over the SOLUTION heading for the lone DOWN heading
(tele_early_heading) and starts the columns there. A read-time change: no scan key moves. Due: such a row (fa.tele_early_due:
4+ lights "no reading laid a clue on it", one numbered 1-3), read before the cutoff."""
from fix_reasons import Reason

TEXT = "Gale Telegraph 1975-89 page whose clue lists began mid-list (the first clues laid on no light), the columns' top set at its heading since"
REREAD = "2026-11-22T12:46:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    return fa.tele_early_due(row) and fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD))


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
