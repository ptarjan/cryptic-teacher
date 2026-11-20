#!/usr/bin/env python3
# The mend for an anagram holding a clue word as written at its edge (anaLiteralEdge): the word moves
# beside the anagram in a charade when exactly one pull still gives the answer.
#
#     python3 tests/test_mend_literal_edge.py
import _path  # puts tools/ on sys.path
import mend_literal_edge as M
import validate_annotations as V
import wordplay

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


CLUE = "Love reforming to cleaner"
zero = {"op": "charade", "parts": [{"words": "Love", "gives": "ZERO"}, {"op": "anagram", "indicators": [{"text": "reforming"}], "parts": [
    {"words": "to"}, {"words": "cleaner"}]}]}
a = {"wp": wordplay.render(zero)}
check("the shape is a literal-edge finding to begin with", V.ana_literal_edge(wordplay.parse(a["wp"], CLUE), "ZEROTOLERANCE", CLUE) == 1)
check("the mend reports a change", M.mend(a, CLUE, "ZEROTOLERANCE"))
fixed = wordplay.parse(a["wp"], CLUE)
check("no literal-edge finding is left", V.ana_literal_edge(fixed, "ZEROTOLERANCE", CLUE) == 0)
check("the tree still gives the answer", bool(wordplay.evaluate(fixed, "ZEROTOLERANCE") is not None))

moved = {"op": "anagram", "indicators": [{"text": "struggling"}], "parts": [{"words": "onward"}, {"words": "we"}]}
b = {"wp": wordplay.render(moved)}
check("genuine fodder is left alone", not M.mend(b, "Onward we struggling", "WEONWARD") and b["wp"] == wordplay.render(moved))
check("no clue or answer, no change", not M.mend({"wp": a["wp"]}, "", "") )

print("FAILED" if fails else "all ok")
raise SystemExit(1 if fails else 0)
