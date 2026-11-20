"""SOLO_VLM (fa.solo_vlm_laid): a blank light one OCR reader alone holds the clue of is read by the VLM from a crop
of that reader's lines, which is the second reader when the vote accepts the reader's words against it. Due: an
unfiled Gale Times 1930-49, Sunday Telegraph 1975-99 or Independent 2000-15 page with 1 to 6 blank lights, one of
them "no reading laid a clue on it" or "no other reading has W" (r286 census: 376 + 118 + 230 editions)."""
import re
from fix_reasons import Reason

TEXT = "unfiled before its fix, a blank light one reader holds the clue of, read by the VLM as the second reader"
REREAD = "2026-11-19T23:59:00+00:00"
YEARS = {"gale": ("1930", "1949"), "galesundaytelegraph": ("1975", "1999"), "galeindependent": ("2000", "2015")}
WHY = ("no reading laid a clue on it", "no other reading has")
MOST = 6
#: Set while due() asks fix_reason about the row, so the registry's call back here answers False.
_ASKING = []


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    m = re.search(r"(\d{4})-\d\d-\d\d", rel)
    span = YEARS.get(fa.paper_of(fa.Path(rel)).key)
    if not m or not span or not span[0] <= m.group(1) <= span[1] \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    for v in row.get("verdicts", ()):
        blank = v.get("blank")
        if v.get("refused") or v.get("skip") or not v.get("id") or not isinstance(blank, dict) \
                or v.get("number") is None or not 1 <= len(blank) <= MOST:
            continue
        if not any(str(why).startswith(WHY) for why in blank.values()):
            continue
        if not (fa.filed_state(v["id"].rsplit("-", 1)[0], v.get("number")) or (False, False))[1]:
            # Another fix due for the row reads it again as well, with this code: it goes first, and this one
            # is the reason only for the rows nothing else names (it would steal their tests and rank).
            if _ASKING:
                return False
            _ASKING.append(1)
            try:
                return fa.fix_reason(row) is None
            finally:
                _ASKING.pop()
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, solution_fix=True, due=due)
