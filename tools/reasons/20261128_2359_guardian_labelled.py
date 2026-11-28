"""GUARDIAN_LABELLED (fa.fourth_labelled in guardian_fourth): r317 Guardian census, the "no reading laid a clue on it" rows
(blanks 1: 13, 2-3: 9, 4+: 15; mostly 1997-98). Shape of the single-light group: the down list's last clue is not in the
third clue column at all but alone in a fourth column right of it, under the solution grid printed there and its label
("CROSSWORD SOLUTION 21,171" then "22 One's within one's right to retain possession of one's bed (3-2)", then "Solution
tomorrow"): 1998-01-15 22 down (label y 3717-3736, the clue's number at y 3748, x 2673, the window ending x 2699),
1997-11-25 22 down, 1997-12-09 17 down, 1998-05-19 21 down. guardian_fourth (GUARDIAN_FOURTH) opened the fourth window on three
numbered lines, GUARDIAN_PAIR on two: one line never did, so the clue stood blank and the page unfiled (23 of 24 clues read
each time). The fourth window now also opens on one numbered line (number 12 or more, a word right of it) standing within
LABELLED_GAP px under a solution label line (a "sol/sou" word of 6-9 letters, no leading number, not "tomorrow") at the same
edge. A general rule: the page's own label is the evidence, no edition or year is named.
Other shapes of the 59 rows (22 "no reading parses", 37 blanks): 15 pages whose ACROSS/DOWN lists no reader found (1985,
Sunday-sized layouts, adverts), 9 whose blank clues are the page's tail columns, 1985 whole-list blanks (14 to 28 lights):
no rule found in this round.
Due: a Guardian archive.org row read before REREAD, a verdict (skip "a clue is blank" is the norm) not refused or complete with a down light "no reading laid"
whose number opens a djvu line under a solution label (label_over) and no older reason due. Read-time only: no scan key moves."""
import re

from fix_reasons import Reason

TEXT = "Guardian page whose last down clue stands under the solution grid's label in a fourth column, read since"
REREAD = "2026-11-19T23:59:00+00:00"  # placeholder: the lander stamps the push minute (UTC)


def labelled(fa, rel, v):
    """Whether verdict `v` of edition `rel` has a blank down light whose clue number opens a djvu line under a solution label."""
    blank = v.get("blank")
    if not isinstance(blank, dict) or v.get("leaf") is None:
        return False
    lost = {k.split("-")[0] for k, why in blank.items() if k.endswith("-down") and "no reading laid a clue" in str(why)}
    if not lost:
        return False
    try:
        lines = fa.leaf_lines(fa.downloads.ARCHIVE_ORG / rel / "djvu.xml.gz", {v["leaf"]}).get(v["leaf"], [])
    except (OSError, ValueError, KeyError, AttributeError):
        return False
    for ws in lines:
        ws = sorted(ws)
        if len(ws) > 1 and ws[0][4] in lost and re.search(r"[A-Za-z]{2}", str(ws[1][4])) and fa.label_over(lines, ws[0][0], ws[0][1]):
            return True
    return False


def due(row):
    import file_archive_org_puzzles as fa
    rel = (row or {}).get("edition") or ""
    if fa.paper_of(fa.Path(rel)).key != fa.GUARDIAN.key or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    if fa.specific_fix_reason(row):
        return False
    return any(not v.get("refused") and not v.get("complete") and labelled(fa, rel, v)
               for v in row.get("verdicts") or ())


REASON = Reason(TEXT, rank=2, unfiled_first=True, newest_landed=True, blanket=True, kept=True, due=due)
