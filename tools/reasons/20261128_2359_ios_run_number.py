"""IOS_RUN_NUMBER (fa.indy_sunday_run_number): a Gale Independent on Sunday page refused "No N is already filed for D, not
D'" (r317: 54 rows, 2005-14). The Independent on Sunday numbers one puzzle a week, but placed()/implied() count six issues a
week, so a title read one off (the issue before's solution heading or the next issue's title: 2008-06-22 read "958" between
956 on 06-15 and 958 on 06-29, really 957) was never mended by the weekly run. Rule: filed neighbours either side a whole
number of weeks off that run unbroken, one number a week, fix the number when the title is one off that run and equals a
neighbour's number, and no puzzle holds the run's number. A title two or more off (the blog-filed 2012-15 copies) stays
refused. Due: every such refusal read before the fix; the reread decides (about 12 of the 21 Gale-neighbour rows mend)."""
import re

from fix_reasons import Reason

TEXT = "Gale Independent on Sunday title one off its weekly run, refused as filed for another day, numbered by the run since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleIndependentSunday\d{4}UKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    return any(v.get("cause") == "number-date-mismatch" and "is already filed for" in (v.get("refused") or "")
               for v in row.get("verdicts") or ())


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
