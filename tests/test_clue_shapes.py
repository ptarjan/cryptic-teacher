#!/usr/bin/env python3
# Does tools/clue_shapes.py reduce a tree to the right skeleton, and does its judgement file hold together?
#
#     python3 tests/test_clue_shapes.py
#
# Hand-built trees stand in for the corpus (the real census takes minutes): a charade, an anagram whose
# fodder is cut into verbatim leaves, a cryptic definition that repeats its own words, a tree four
# levels deep. Each must give its skeleton and the verdict tools/data/clue_shape_verdicts.json holds
# for it, and the verdict file must pass its own check, so a typo in a regular expression or a verdict
# name fails here and not in the nightly. docs/CLUE_SHAPES.md, if present, must keep its markers.
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import sys
sys.path.insert(0, "tools")
import clue_shapes as cs

v = cs.load_verdicts()
bad = cs.check_verdicts(v)
assert not bad, bad
pats = [(p, re.compile(p.get("re", "."))) for p in v["patterns"]]


def leaf(words, gives=None):
    n = {"words": words}
    if gives:
        n["gives"] = gives
    return n


def sk(tree):
    return cs.analyse(tree)[0]


def verdict(skel):
    row, _ = cs.judge(skel, v, pats)
    return row["verdict"] if row else None


cases = [
    ({"op": "charade", "parts": [leaf("huge", "OS"), leaf("temporary accommodation", "TENTS")]}, "(A+S)", "ok"),
    ({"op": "anagram", "indicators": [{"text": "wild"}],
      "parts": [{"op": "charade", "parts": [leaf("must"), leaf("if")]}]}, "ana((V+V))", "redundant"),
    ({"op": "anagram", "indicators": [{"text": "wild"}], "parts": [leaf("must if")]}, "ana(V)", "ok"),
    ({"op": "cryptic", "parts": [leaf("Rags"), leaf("Rags")]}, "cdef(D,D)", "redundant"),
    ({"op": "cryptic", "parts": [leaf("Like intimate combat"), leaf("that you've just seen")]}, "cdef(V,V)", "ok"),
    ({"op": "container", "indicators": [{"text": "in"}],
      "parts": [leaf("fur", "FITCH"), {"op": "anagram", "indicators": [{"text": "crooked"}], "parts": [leaf("ply")]}]},
     "ins(S,ana(V))", "ok"),
    ({"op": "anagram", "unchecked": True,
      "parts": [{"op": "container", "unchecked": True, "parts": [leaf("fur", "FITCH"), leaf("ply", "LYP")]}]},
     "ana?(ins?(S,S))", "mislabelled"),
    ({"op": "reversal", "parts": [{"op": "reversal", "parts": [{"op": "reversal", "parts": [{"op": "reversal",
      "parts": [leaf("x", "AB")]}]}]}]}, "rev(rev(rev(rev(A))))", "rare"),
]
for tree, want_sk, want_v in cases:
    got = sk(tree)
    assert got == want_sk, (got, want_sk)
    assert verdict(got) == want_v, (got, verdict(got), want_v)

assert cs.depth_of("(S+ins(S,A))") == 1 and cs.depth_of("rev(ins(ana(V),S))") == 3 and cs.mechanisms_of("(S+ins(S,A))") == 1
assert cs.leaf_type({"words": "a rose by", "gives": "ROSE"}, None) == "F"
assert cs.leaf_type({"words": "a rose by", "gives": "ROSE"}, "first") == "V"
assert cs.leaf_type({"words": "huge", "gives": "OS"}, None) == "A"
assert cs.leaf_type({"gives": "IE"}, "deletion") == "B"

# tiers: (skeleton, tier 1 mechanism set, tier 2 mechanism tree)
for skel, t1, t2 in [
    ("(A+S)", "charade only", "x"),
    ("(S+S+S)", "charade only", "x"),
    ("ana(V)", "anagram", "ana(x)"),
    ("ana((V+V))", "anagram", "ana(x)"),
    ("DD", "double definition", "DD"),
    ("cdef(V,V)", "cryptic definition", "cdef(x)"),
    ("ins(S,ana(V))", "anagram + container", "ins(ana(x),x)"),
    ("ins(ana(V),S)", "anagram + container", "ins(ana(x),x)"),
    ("ana(ins(S,A))", "anagram + container", "ana(ins(x))"),
    ("(S+first(V)+S)", "letter selection", "(x+select(x))"),
    ("ins?(first(V),(S+S))", "container + letter selection", "ins(select(x),x)"),
    ("(S+ins(S,A)+rev(S))", "container + reversal", "(x+ins(x)+rev(x))"),
    ("rev(rev(rev(rev(A))))", "reversal", "4+ ops"),
]:
    assert cs.tier1(skel) == t1, (skel, cs.tier1(skel), t1)
    assert cs.tier2(skel) == t2, (skel, cs.tier2(skel), t2)
assert cs.tier2("ins(S,ana(V))") != cs.tier2("ana(ins(S,S))")
assert cs.tier1("ana(rev(del(ins(S,A))))").startswith("4+")
# every name the doc prints comes from the one OPS table
assert cs.SHORT["anagram"] == "ana" and cs.NAME["charade"] == "charade" and cs.BYABBR["ins"] == "container"

doc = cs.DOC
if doc.exists():
    text = doc.read_text()
    assert cs.START in text and cs.END in text, "docs/CLUE_SHAPES.md lost its generated markers"
print("clue_shapes: ok")
