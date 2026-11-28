"""FT_THIRD_RISING (fa.ft_third_numbered, ft_third_column): a Gale FT page whose third clue column (the down list's tail, 18-27 down on
2004-11-24 No 11695) has stray print over its first clue ("Emdex Trd.", a masthead scrap at y 4276 over "18 It could require serum"
at 4425) lost the whole column: ft_third_column kept it only when its first line opened on a clue number. Now also when at least 3
lines open on clue numbers rising line by line. Read-time only (no scan key moves). Cause tally of 232 Gale FT rows blank "no reading
laid a clue on it" (r315): 136 have no third-column read at all (1982-87 and 1991 layouts, 2005: other causes, not fixed here),
71 a third read with no numbered lines, 17 a third read closed by stray top print over rising numbers (this fix), 8 a third column
already kept (other causes).
Due: a Gale FT row read before the cutoff with a down light no reading laid whose third-column cache holds rising clue numbers."""
import re

from fix_reasons import Reason

TEXT = "Gale FT page with a down clue blank, its third clue column kept past stray print over its first clue"
REREAD = "2026-11-28T06:41:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def due(row):
    import glob
    import json
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if not re.match(r"GaleFT(19|20)\d\dUKEnglish/", rel) or "inputs" not in row \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False
    for v in row.get("verdicts") or ():
        if not any(str(k).endswith("-down") and "no reading laid" in str(w) for k, w in (v.get("blank") or {}).items()):
            continue
        for f in glob.glob(str(fa.CROPS / "rapid" / f"{rel.split('/')[-1]}_{v.get('number')}.*.third.json")):
            try:
                words = json.load(open(f))["words"]
            except (OSError, ValueError, KeyError):
                continue
            if fa.ft_third_numbered(words):
                return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
