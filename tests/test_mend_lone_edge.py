#!/usr/bin/env python3
# The mend for an anagram holding a lone letter the answer shows at its edge (anaLoneEdge): the letter
# moves beside the anagram in a charade when exactly one pull still gives the answer.
#
#     python3 tests/test_mend_lone_edge.py
import _path  # puts tools/ on sys.path
import mend_lone_edge as M
import validate_annotations as V
import wordplay

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


# REAWAKEN: ana(A + WEAKER) + N, written with N inside the fodder
CLUE = "Stir a weaker, north"
tree = {"op": "anagram", "indicators": [{"text": "Stir"}], "parts": [
    {"words": "a"}, {"words": "weaker"}, {"words": "north", "gives": "N"}]}
a = {"wp": wordplay.render(tree)}
check("the shape is a lone-edge finding to begin with", V.ana_lone_edge(wordplay.parse(a["wp"], CLUE), "REAWAKEN", CLUE) >= 1)
check("the mend reports a change", M.mend(a, CLUE, "REAWAKEN"))
fixed = wordplay.parse(a["wp"], CLUE)
check("no lone-edge finding is left", V.ana_lone_edge(fixed, "REAWAKEN", CLUE) == 0)
check("the tree still gives the answer", wordplay.evaluate(fixed, "REAWAKEN") is not None)

ok = {"op": "anagram", "indicators": [{"text": "struggling"}], "parts": [{"words": "onward"}, {"words": "we"}]}
b = {"wp": wordplay.render(ok)}
check("genuine fodder is left alone", not M.mend(b, "Onward we struggling", "WEONWARD") and b["wp"] == wordplay.render(ok))
check("no clue or answer, no change", not M.mend({"wp": a["wp"]}, "", ""))

print("FAILED" if fails else "all ok")
raise SystemExit(1 if fails else 0)
