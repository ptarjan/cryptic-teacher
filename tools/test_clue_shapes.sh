#!/bin/bash
# Does tools/clue_shapes.py reduce a tree to the right skeleton, and does its judgement file hold together?
#
#     bash tools/test_clue_shapes.sh
#
# Hand-built trees stand in for the corpus (the real census takes minutes): a charade, an anagram whose
# fodder is cut into verbatim leaves, a cryptic definition that repeats its own words, a tree four
# levels deep. Each must give its skeleton and the verdict tools/data/clue_shape_verdicts.json holds
# for it, and the verdict file must pass its own check, so a typo in a regular expression or a verdict
# name fails here and not in the nightly. docs/CLUE_SHAPES.md, if present, must keep its markers.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
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

doc = cs.DOC
if doc.exists():
    text = doc.read_text()
    assert cs.START in text and cs.END in text, "docs/CLUE_SHAPES.md lost its generated markers"
print("clue_shapes: ok")
PY
