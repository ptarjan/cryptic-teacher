#!/usr/bin/env python3
# The mend for a leaf holding a truncation word (truncInLeaf): [Bird almost]BIR becomes
# del<almost>(Bird, D) when the whole word is in the leaf and the tree still gives the answer.
#
#     python3 tests/test_mend_trunc_leaf.py
import _path  # puts tools/ on sys.path
import mend_trunc_leaf as M
import validate_annotations as V
import wordplay

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


CLUE = "Bird almost"
a = {"wp": wordplay.render({"words": "Bird almost", "gives": "BIR"})}
check("the shape is a truncInLeaf finding to begin with", V.trunc_in_leaf(wordplay.parse(a["wp"], CLUE)))
check("the mend reports a change", M.mend(a, CLUE, "BIR"))
fixed = wordplay.parse(a["wp"], CLUE)
check("no truncInLeaf finding is left", not V.trunc_in_leaf(fixed))
check("the deletion still gives the answer", wordplay.evaluate(fixed, "BIR") is not None)
check("a second mend changes nothing", not M.mend(a, CLUE, "BIR"))
check("no clue or answer, no change", not M.mend({"wp": a["wp"]}, "", ""))

print("FAILED" if fails else "all ok")
raise SystemExit(1 if fails else 0)
