"""INDY_THIRD_LATE (fa.indy_third_window's late years): a Gale Independent 2010-13 page of three clue columns under its grid
whose third column stands beside the grid its whole height (2012-08-20 No 8065: x 1695, y 1291-2278 over a grid ending
y 2062: the across list's last clues, the DOWN heading, 1 to 9 down). The plain window began at the grid's foot, so the
column's top lines were never read and 1-9 down and 25-26 across laid nothing ("no reading laid a clue on it"). The 2004
chain (INDY_THIRD_TOP, gap 60, reach 260) now runs at gap 110 and reach 900 for these years: 2012-08-20 read 28 of 28
clues, 10 blank before (readers only). Due: such a page, a light "no reading laid a clue on it", not filed, whose cached
windows hold the three columns under the grid and a third column's lines chained up from its top (indy_third_late_read)."""
import re
from fix_reasons import Reason

TEXT = "Independent 2010-13 page whose third clue column stood beside the grid over its foot, read since"
REREAD = "2026-11-21T21:20:00+00:00"


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not re.match(r"GaleIndependent201[0-3]UKEnglish/", rel) \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    for v in row.get("verdicts", ()):
        blank = v.get("blank")
        if v.get("refused") or v.get("skip") or not v.get("id") or v.get("number") is None or not isinstance(blank, dict):
            continue
        if any("no reading laid a clue" in str(why) for why in blank.values()) \
                and fa.indy_third_late_read(f"{rel.split('/')[1]}_{v['number']}") \
                and not (fa.filed_state(v["id"].rsplit("-", 1)[0], v.get("number")) or (False, False))[1]:
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
