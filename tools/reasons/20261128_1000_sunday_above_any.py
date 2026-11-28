"""SUNDAY_ABOVE_ANY (fa._read_page, sunday_above): r317 cluster 14, Gale Sunday Telegraph pages left unfiled with 4+ lights "no reading
laid a clue on it" (89 rows, 1990-94 34, 1980-84 17, 1975-79 9, 1995-99 8). Shape of the biggest group, 31 of 89 (all 1990, 1990-01-07
to 1990-10-14): the ACROSS column starts far over the grid's title, as the 1980-89 pages' did (SUNDAY_ABOVE), so the first clue window
(from the title line, 1990-02-11 y 3674) opens mid-list on ACROSS 24-28 and the whole list above it (1, 5, 9-14, 16, 19, 22: all 16
ACROSS lights of 32 less the tail) stood outside every window; the DOWN list read, 21 clues of 32 lights. sunday_above() (the ACROSS
heading found in the strip left of the grid over its cut starts the column there) was gated to the years 1980-89 the 11-15 census
found the shape in; its evidence is the page's own heading, so the year gate is gone: it runs on every Sunday Telegraph page whose
sides_columns were found (before 1999). A page with no ACROSS heading in the strip reads as before.
Due: a Gale Sunday Telegraph row (before SUNDAY_SIDES_END) read before REREAD, a verdict not refused or complete with an ACROSS light
"no reading laid", whose cached first window (Times reader) opens on a clue numbered above the lowest such light (the list's head is
above the window), and no older reason due. Read-time only, no scan key moves."""
import json
import re

from fix_reasons import Reason

TEXT = "Gale Sunday Telegraph page whose ACROSS list starts over the grid's title, its ACROSS heading sought over the grid whatever the year since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def window_head(fa, rel, number):
    """The number of the first clue line (left edge of the first window) of the cached Times-reader reading, else None."""
    date = rel.split("/")[-1][:10]
    try:
        held = json.loads((fa.CROPS / "rapid" / f"{date}_{number}.{fa.reader_key('times')}.json").read_text())
        box, words = held["box"], held["words"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    left = sorted((float(w[1]), str(w[4])) for w in words if float(w[0]) < box[0] + 60
                  and re.fullmatch(r"\W*\d{1,2}\W*", str(w[4])))
    return int(re.sub(r"\D", "", left[0][1])) if left else None


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if fa.paper_of(fa.Path(rel)).key != fa.GALE_SUNDAY_TELEGRAPH.key or "inputs" not in row \
            or rel.split("/")[-1][:4] >= fa.SUNDAY_SIDES_END \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False
    for v in row.get("verdicts") or ():
        blank = v.get("blank")
        if v.get("refused") or v.get("skip") or v.get("complete") or not isinstance(blank, dict) or not v.get("number"):
            continue
        lost = [int(k.split("-")[0]) for k, why in blank.items()
                if k.endswith("-across") and "no reading laid a clue" in str(why)]
        head = window_head(fa, rel, v["number"]) if lost else None
        if head is not None and head >= 2 and min(lost) < head:
            return True
    return False


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
