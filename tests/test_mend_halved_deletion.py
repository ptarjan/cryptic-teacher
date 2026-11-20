#!/usr/bin/env python3
# The mend for a deletion whose indicator says half (halvedAsDeletion): it becomes the first/last
# selection it is when the cut is exactly one end half and the tree still gives the answer.
#
#     python3 tests/test_mend_halved_deletion.py
import _path  # puts tools/ on sys.path
import mend_halved_deletion as M
import validate_annotations as V
import wordplay

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


CLUE = "Half of mother"
tree = {"op": "deletion", "indicators": [{"text": "Half of"}], "parts": [
    {"words": "mother"}, {"gives": "HER"}]}
a = {"wp": wordplay.render(tree)}
check("the shape is a halved-deletion finding to begin with", V.halved_as_deletion(wordplay.parse(a["wp"], CLUE)))
check("the mend reports a change", M.mend(a, CLUE, "MOT"))
fixed = wordplay.parse(a["wp"], CLUE)
check("no halved-deletion finding is left", not V.halved_as_deletion(fixed))
check("no clue or answer, no change", not M.mend({"wp": a["wp"]}, "", ""))

print("FAILED" if fails else "all ok")
raise SystemExit(1 if fails else 0)
