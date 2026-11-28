"""IOS_BEELZEBUB_HEADING (fa.indy_sunday_headings): a Gale Independent on Sunday page of 2011-16 prints the Concise's solution
under "Solution for last issue" and the barred Beelzebub's own title ("BEELZEBUB Crossword No.1139", 2012-01-01) below it.
indy_sunday_headings took every title under the note for last week's solution (the note heads the Concise's solution only),
so such a page scanned with no Beelzebub puzzle (its title came only from the fallback read of a page scan() found none on).
Rule: a Beelzebub title line (IOS_BEELZEBUB_LINE) set under the note is a fresh puzzle heading. Due: every such page not yet
filed whose refusal was a number-date mismatch (the "already filed for D" collisions with ids now in the other series since
abd8d60e9bf, and the out-of-date-order refusals) or that has no verdict; the reread decides (about 40 rows, 2011-15)."""
import re

from fix_reasons import Reason

TEXT = "Gale Independent on Sunday Beelzebub title under the Concise's \"Solution for last issue\" note is a puzzle heading"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    m = re.match(r"GaleIndependentSunday(\d{4})UKEnglish/", rel)
    if not m or not 2011 <= int(m.group(1)) <= 2016 or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False  # an older, specific reason makes the row due: it keeps the row and its rank
    verdicts = row.get("verdicts") or ()
    if any(v.get("id") or v.get("wrote") for v in verdicts):
        return False
    return not verdicts or any(v.get("cause") == "number-date-mismatch" for v in verdicts)


REASON = Reason(TEXT, rank=2, unfiled_first=True, blanket=True, kept=True, due=due)
