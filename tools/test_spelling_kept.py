#!/usr/bin/env python3
# A re-annotation may not drop the spelling HEAD's annotation of the same answer
# carries: book-26021 22D lost APERÇU in a shape re-annotation, and the
# per-puzzle spelling.unsaid allowance left over from before it was filled let
# the commit through. The run's own check against HEAD refuses it.
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
import validate_annotations as v


def puzzle(solution="APERCU", **ann):
    return {"entries": [{"number": 22, "direction": "down", "solution": solution,
                         "annotation": {"definitions": [], **ann}}]}


fails = 0
def check(name, ok, got=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else got)


real = v.committed_entries
cases = (
    ("spelling dropped", puzzle(spelling="APERÇU"), puzzle(), True),
    ("spelling kept", puzzle(spelling="APERÇU"), puzzle(spelling="APERÇU"), False),
    ("spelling changed", puzzle(spelling="APERÇU"), puzzle(spelling="APERCU'"), False),
    ("never had one", puzzle(), puzzle(), False),
    ("answer changed", puzzle(spelling="APERÇU"), puzzle("OTHER"), False),
    ("annotation withdrawn", puzzle(spelling="APERÇU"),
     {"entries": [{"number": 22, "direction": "down", "solution": "APERCU", "annotation": None}]}, False),
)
for name, head, now, want in cases:
    v.committed_entries = lambda path, h=head: {v.entry_id(e): e for e in h["entries"]}
    errs = []
    v.check_spelling_kept(now, Path("x"), errs)
    check(f"{name}: refused={want}", bool(errs) == want, errs)
v.committed_entries = lambda path: None
errs = []
v.check_spelling_kept(puzzle(), Path("x"), errs)
check("an uncommitted puzzle has nothing to compare", not errs, errs)
v.committed_entries = real

# And it is wired into the run's own checks against HEAD.
errs = []
v.committed_entries = lambda path: {"22-down": puzzle(spelling="APERÇU")["entries"][0]}
v.committed_top = lambda path: {}
v.check_clue_unchanged = v.check_theme_clue_unchanged = v.check_clue_rows_held = lambda *a: None
v.check_selectors_are_indicators = v.check_no_new_abbreviation_notes = lambda *a: None
v.check_against_committed(puzzle(), Path("x"), errs)
check("check_against_committed runs it", any("spells the answer" in e for e in errs), errs)
if fails:
    raise SystemExit(fails)
print("all spelling-kept checks passed")
