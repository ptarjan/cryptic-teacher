#!/usr/bin/env python3
# The rewrites annotate_check makes on the model's `wp` before the first check (repairs.MODEL_MENDS),
# each run alone: it mends its own shape, keeps the answer, changes nothing on a second run, and
# leaves genuine fodder, a wrong answer or a missing clue alone.
#
#     python3 tests/test_model_mends.py
import _path  # puts tools/ on sys.path
import repairs as R
import validate_annotations as V
import wordplay

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


def mend(name, a, clue, answer):
    """Whether mend `name` alone changed `a`."""
    return R.mend_wp(a, clue, answer, only=[name]) == [name]


def gives(wp, clue, answer):
    try:
        wordplay.evaluate(wordplay.parse(wp, clue), answer)
        return True
    except wordplay.WordplayError:
        return False


check("every mend has a distinct name", len({m.name for m in R.MODEL_MENDS}) == len(R.MODEL_MENDS))

# truncInLeaf: [Bird almost]BIR becomes del<almost>(Bird, D)
CLUE = "Bird almost"
a = {"wp": wordplay.render({"words": "Bird almost", "gives": "BIR"})}
check("truncInLeaf: the shape is a finding to begin with", V.trunc_in_leaf(wordplay.parse(a["wp"], CLUE)))
check("truncInLeaf: the mend reports a change", mend("truncInLeaf", a, CLUE, "BIR"))
check("truncInLeaf: no finding is left", not V.trunc_in_leaf(wordplay.parse(a["wp"], CLUE)))
check("truncInLeaf: the deletion still gives the answer", gives(a["wp"], CLUE, "BIR"))
check("truncInLeaf: a second mend changes nothing", not mend("truncInLeaf", a, CLUE, "BIR"))
check("truncInLeaf: no clue or answer, no change", not mend("truncInLeaf", {"wp": a["wp"]}, "", ""))

# halvedAsDeletion: a deletion under "half of" is the first/last selection it is
CLUE = "Half of mother"
a = {"wp": wordplay.render({"op": "deletion", "indicators": [{"text": "Half of"}],
                            "parts": [{"words": "mother"}, {"gives": "HER"}]})}
check("halvedAsDeletion: the shape is a finding to begin with", V.halved_as_deletion(wordplay.parse(a["wp"], CLUE)))
check("halvedAsDeletion: the mend reports a change", mend("halvedAsDeletion", a, CLUE, "MOT"))
check("halvedAsDeletion: no finding is left", not V.halved_as_deletion(wordplay.parse(a["wp"], CLUE)))
check("halvedAsDeletion: no clue or answer, no change", not mend("halvedAsDeletion", {"wp": a["wp"]}, "", ""))

# anaLoneEdge: the lone N at the answer's edge comes out of the anagram
CLUE = "Stir a weaker, north"
a = {"wp": wordplay.render({"op": "anagram", "indicators": [{"text": "Stir"}], "parts": [
    {"words": "a"}, {"words": "weaker"}, {"words": "north", "gives": "N"}]})}
check("anaLoneEdge: the shape is a finding to begin with",
      V.ana_lone_edge(wordplay.parse(a["wp"], CLUE), "REAWAKEN", CLUE) >= 1)
check("anaLoneEdge: the mend reports a change", mend("anaLoneEdge", a, CLUE, "REAWAKEN"))
check("anaLoneEdge: no finding is left", V.ana_lone_edge(wordplay.parse(a["wp"], CLUE), "REAWAKEN", CLUE) == 0)
check("anaLoneEdge: the tree still gives the answer", gives(a["wp"], CLUE, "REAWAKEN"))
ok = wordplay.render({"op": "anagram", "indicators": [{"text": "struggling"}], "parts": [{"words": "onward"}, {"words": "we"}]})
b = {"wp": ok}
check("anaLoneEdge: genuine fodder is left alone", not mend("anaLoneEdge", b, "Onward we struggling", "WEONWARD") and b["wp"] == ok)
check("anaLoneEdge: no clue or answer, no change", not mend("anaLoneEdge", {"wp": a["wp"]}, "", ""))

# anaLiteralEdge: TO, taken as written at the anagram's edge, goes beside it
CLUE = "Love reforming to cleaner"
a = {"wp": wordplay.render({"op": "charade", "parts": [{"words": "Love", "gives": "ZERO"}, {
    "op": "anagram", "indicators": [{"text": "reforming"}], "parts": [{"words": "to"}, {"words": "cleaner"}]}]})}
check("anaLiteralEdge: the shape is a finding to begin with",
      V.ana_literal_edge(wordplay.parse(a["wp"], CLUE), "ZEROTOLERANCE", CLUE) == 1)
check("anaLiteralEdge: the mend reports a change", mend("anaLiteralEdge", a, CLUE, "ZEROTOLERANCE"))
check("anaLiteralEdge: no finding is left",
      V.ana_literal_edge(wordplay.parse(a["wp"], CLUE), "ZEROTOLERANCE", CLUE) == 0)
check("anaLiteralEdge: the tree still gives the answer", gives(a["wp"], CLUE, "ZEROTOLERANCE"))
b = {"wp": ok}
check("anaLiteralEdge: genuine fodder is left alone",
      not mend("anaLiteralEdge", b, "Onward we struggling", "WEONWARD") and b["wp"] == ok)
check("anaLiteralEdge: no clue or answer, no change", not mend("anaLiteralEdge", {"wp": a["wp"]}, "", ""))

# anaInDeletion: del(ana(F), D) is the composite anagram comp(F, D)
CLUE = "Perhaps someone has lost a rare sapphire"
WP = "del<lost>(ana<rare>([sapphire]), [someone]I)"
a = {"wp": WP}
check("anaInDeletion: the filed shape is refused", not gives(WP, CLUE, "PERHAPS"))
check("anaInDeletion: the mend reports a change", mend("anaInDeletion", a, CLUE, "PERHAPS"))
check("anaInDeletion: the new wp is a comp", a["wp"].startswith("comp<lost><rare>("))
check("anaInDeletion: the new wp gives the answer", gives(a["wp"], CLUE, "PERHAPS"))
check("anaInDeletion: a wrong answer is not mended", not mend("anaInDeletion", {"wp": WP}, CLUE, "PERHAPT"))
check("anaInDeletion: an anagram under sub is left alone",
      not mend("anaInDeletion", {"wp": "sub<lost>(ana<rare>([sapphire]), [someone]I, [a]A)"}, CLUE, "PERHAPS"))
check("anaInDeletion: no clue or answer, no change", not mend("anaInDeletion", {"wp": WP}, "", ""))

# noteLetters: a lone leaf of "keys" over an A-G answer is one note per letter
CLUE = "Beg for keys"
a = {"wp": "[keys]CADGE", "notes": {"keys": "keys are notes"}}
check("noteLetters: the shape is a singleLeaf finding to begin with", V.single_leaf(wordplay.parse(a["wp"], CLUE)))
check("noteLetters: the mend reports a change", mend("noteLetters", a, CLUE, "CADGE"))
check("noteLetters: no singleLeaf finding is left", not V.single_leaf(wordplay.parse(a["wp"], CLUE)))
check("noteLetters: it still gives the answer", gives(a["wp"], CLUE, "CADGE"))
check("noteLetters: a second mend changes nothing", not mend("noteLetters", a, CLUE, "CADGE"))
check("noteLetters: a leaf that names no notes is left alone", not mend("noteLetters", {"wp": "[Beg]CADGE"}, CLUE, "CADGE"))
check("noteLetters: an answer with letters outside A-G is left alone",
      not mend("noteLetters", {"wp": "[keys]CLOSE"}, "Keys", "CLOSE"))
check("noteLetters: no clue or answer, no change", not mend("noteLetters", {"wp": "[keys]CADGE"}, "", ""))

print("FAILED" if fails else "all ok")
raise SystemExit(1 if fails else 0)
