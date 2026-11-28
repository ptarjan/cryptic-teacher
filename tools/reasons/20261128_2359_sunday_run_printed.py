"""SUNDAY_RUN_PRINTED (fa.sunday_read_title): a Gale Sunday Times page whose filed neighbours either side run unbroken, one number
a week (sunday_implied), takes that number as its title when a cached page reader prints it (heading, loose finder, "ACROSS No."
label or "No N" after a heading word), before the loose finder's other candidate (1983-07-17: loose "2984", the run's 2986).
Never a number the page does not print. Read-time only, outside scan(): scan boxes and keys unchanged.
Due: a Gale Sunday Times row refused (a verdict with a refusal) whose run-implied number appears in its cached page reads."""
from fix_reasons import Reason

TEXT = "Gale Sunday Times page refused whose filed weekly run implies a number its page reads print, filed since"
REREAD = "2026-11-28T15:55:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import datetime
    import file_archive_org_puzzles as fa
    rel = str((row or {}).get("edition") or "")
    if not rel.startswith("GaleSundayTimes") or "inputs" not in row:
        return False
    if not any(v.get("refused") for v in row.get("verdicts") or ()):
        return False
    if not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)) or fa.specific_fix_reason(row):
        return False
    try:
        d = fa.CACHE / rel
        day = datetime.date.fromisoformat(d.name[:10])
        fixed = fa.sunday_implied(day, fa.held_dates(fa.GALE_SUNDAY_TIMES.series))
        if not fixed:
            return False
        leaves = sorted({p["leaf"] for p in fa.json.loads((d / "pages.json").read_text()).get("crossword_pages", ())})
    except (OSError, ValueError, KeyError, TypeError):
        return False
    for leaf in leaves:
        for words in fa.sunday_page_reads(d, leaf) or ():
            for finder in (fa.sunday_headings_loose, fa.sunday_across_labels, fa.sunday_no_labels):
                if any(n == fixed for n, _ in finder(words, fixed, 0)):
                    return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
