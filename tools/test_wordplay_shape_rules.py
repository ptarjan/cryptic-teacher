#!/usr/bin/env python3
# Wordplay shapes that read wrongly are counted by validate_annotations under their
# own ratchet fields, and tidy_wordplay_shapes.py joins a charade inside a charade
# without changing what view() shows.
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import copy
import annotation, wordplay
import validate_annotations as v
import tidy_wordplay_shapes as T

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

def tree(expr, clue):
    return wordplay.parse(expr, clue)

CLUE = "Fish and chips"
cc = {"op": "charade", "parts": [{"words": "Fish", "at": 0, "gives": "COD"},
      {"op": "charade", "parts": [{"words": "and", "at": 5, "gives": "A"}, {"words": "chips", "at": 9, "gives": "ND"}]}]}
check("a charade inside a charade is counted", 1, v.charade_in_charade(cc))
check("a charade with an indicator inside one is not", 0, v.charade_in_charade(
    {"op": "charade", "parts": [{"gives": "A"}, {"op": "charade", "indicators": [{"text": "x"}], "parts": [{"gives": "B"}, {"gives": "C"}]}]}))
new = copy.deepcopy(cc)
check("the migration joins it", 1, T.flatten_tree(new))
check("into the outer charade, in order", ["Fish", "and", "chips"], [p["words"] for p in new["parts"]])
check("a second run changes nothing", 0, T.flatten_tree(new))

check("an anagram with no indicator is counted", 1, v.unindicated_ops(tree("ana([ab])", "ab")))
check("one with its indicator is not", 0, v.unindicated_ops(tree("ana<odd>([ab])", "odd ab")))
check("a charade and a cryptic definition need none", 0,
      v.unindicated_ops({"op": "cryptic", "parts": [{"words": "x"}]}) + v.unindicated_ops(cc))
check("a cryptic definition's second leaf is counted", 1, v.cdef_repeats(
    {"op": "cryptic", "parts": [{"words": "a b"}, {"words": "a"}]}))
check("a palindrome with two parts has the wrong arity", 1, v.bad_arity(
    {"op": "palindrome", "parts": [{"words": "a"}, {"words": "b"}]}))
check("a homophone's spelling is not a part", 0, v.bad_arity(tree("sound<say>([bare], BARE)", "say bare")))
check("a one-part charade has the wrong arity", 1, v.bad_arity({"op": "charade", "parts": [{"words": "a"}]}))
two = {"op": "charade", "parts": [{"words": "ab", "at": 0}, {"words": "b c", "at": 1}]}
check("two leaves sharing clue words are counted", 1, v.span_overlaps(two))
check("and ones under a cryptic definition are not", 0, v.span_overlaps({"op": "cryptic", "parts": two["parts"]}))
spoon = {"op": "spoonerism", "indicators": [{"text": "Spooner's"}],
         "parts": [{"op": "homophone", "parts": [{"words": "white late"}, {"gives": "WIGHT"}]}, {"words": "x"}]}
check("a Spoonerism's own sound needs no indicator of its own", 0, v.unindicated_ops(spoon))
check("a homophone elsewhere still does", 1, v.unindicated_ops(
    {"op": "charade", "parts": [spoon["parts"][0], {"words": "y"}]}))
check("and a Spoonerism with no indicator is still counted", 1, v.unindicated_ops({**spoon, "indicators": []}))
same = {"op": "charade", "parts": [{"words": "Pieces", "at": 0, "gives": "BIT"}, {"words": "Pieces", "at": 0, "gives": "PART"}]}
check("one word on two leaves (a word doing two jobs) is not claimed twice", 0, v.span_overlaps(same))
check("but a leaf inside another leaf's span still is", 1, v.span_overlaps(
    {"op": "charade", "parts": [{"words": "daycare", "at": 0}, {"words": "care", "at": 3}]}))
check("and an indicator over a leaf still is", 1, v.span_overlaps(
    {"op": "container", "indicators": [{"text": "are covered in", "at": 0}], "parts": [{"words": "are", "at": 0}, {"words": "x", "at": 20}]}))
import shape_suspects as ss
check("the shape detector agrees", None, ss.d_span_overlap({"wp": same}))
ann = {"definitions": [{"text": "ab", "at": 0}], "wordplay": {"words": "ab", "at": 0, "gives": "X"}}
check("wordplay inside the definition is counted", 1, v.in_definition(ann))
check("unless the clue is &lit", 0, v.in_definition({**ann, "andLit": True}))
check("a leaf giving a stretch of its words is counted", 1, v.leaf_folds({"words": "bridge", "gives": "RID"}))
check("a leaf with a note is not", 0, v.leaf_folds({"words": "bridge", "gives": "RID", "note": "x"}))
check("a leaf under a hidden-word op is not", 0, v.leaf_folds({"op": "hidden", "parts": [{"words": "bridge", "gives": "RID"}]}))
check("a possessive S dropped is not", 0, v.leaf_folds({"words": "Mike's", "gives": "MIKE"}))
sel = tree("(first([a]) + first([b]))", "a b")
check("a selection repeated word by word is counted", 1, v.repeated_selections(sel))
check("one leaf is no wordplay", 1, v.single_leaf({"words": "a", "gives": "A"}))
check("bare letters in a charade are counted", 1, v.bare_in_charade(
    {"op": "charade", "parts": [{"gives": "A"}, {"words": "b", "gives": "B"}]}))
bare = {"op": "charade", "parts": [{"gives": "A"}, {"words": "b", "gives": "B"}]}
check("a hiddenLetter clue's bare letters are not counted", 0,
      v.bare_in_charade(bare, {"hiddenLetter": {"kind": "omitted", "letter": "A"}}))
check("a clue with no hiddenLetter is still counted", 1, v.bare_in_charade(bare, {"wordplay": bare}))
dev = {"op": "charade", "parts": [{"gives": "A", "device": True}, {"words": "b", "gives": "B"}]}
check("a leaf marked as a preamble device is not counted", 0, v.bare_in_charade(dev, {"wordplay": dev}))
check("an unmarked bare leaf beside a marked one is counted", 1, v.bare_in_charade(
    {"op": "charade", "parts": [{"gives": "A", "device": True}, {"gives": "C"}, {"words": "b", "gives": "B"}]}))
import puzzle_schema
def _schema_problems(node):
    out = []
    puzzle_schema._check(node, puzzle_schema._resolve("#/$defs/wordplayNode"), "$", out)
    return out
check("the schema accepts the device marker on a bare leaf", [], _schema_problems(dev))
check("and refuses it on a leaf with a stray key", True, bool(_schema_problems({"gives": "A", "bogus": True})))
check("an anagram of a container is counted", 1, v.anagram_of_container(
    {"op": "anagram", "parts": [{"op": "container", "parts": [{"words": "a"}, {"words": "b"}]}]}))

check("a container with one part is counted", 1, v.arity_ins({"op": "container", "unchecked": True, "parts": [{"words": "a"}]}))
check("a checked one is the arity rule's, not this", 0, v.arity_ins({"op": "container", "parts": [{"words": "a"}]}))
check("a substitution with two parts is counted", 1, v.arity_other({"op": "substitution", "unchecked": True, "parts": [{"words": "a"}, {"words": "b"}]}))
check("a deletion with three parts is counted", 1, v.arity_other({"op": "deletion", "unchecked": True, "parts": [{}, {}, {}]}))
check("a deletion with one part is counted", 1, v.del_single({"op": "deletion", "unchecked": True, "parts": [{"words": "a"}]}))
check("and is not an arityOther", 0, v.arity_other({"op": "deletion", "unchecked": True, "parts": [{"words": "a"}]}))
leaf = {"words": "nearly obtains", "gives": "HA"}
check("an indicator inside a leaf is counted", 1, v.ind_in_leaf({"op": "deletion", "indicators": [{"text": "nearly"}], "parts": [leaf, {"words": "x"}]}))
check("a whole-leaf indicator is not", 0, v.ind_in_leaf({"op": "deletion", "indicators": [{"text": "nearly"}], "parts": [{"words": "nearly"}]}))

for field in ("arityIns", "arityOther", "delSingle", "indInLeaf", "charadeInCharade", "noIndicator", "cdefRepeat", "arity", "spanOverlap", "inDefinition",
              "leafFold", "repeatedSelection", "singleLeaf", "bareInCharade", "anagramOfContainer"):
    check(f"wordplay.{field} is a ratchet field", True, f"wordplay.{field}" in v.BACKLOG_MARKERS)
warn = v.shape_warnings("1A", {"wordplay": cc, "definitions": []})
check("the ratchet refuses one more than a puzzle is allowed", 1,
      len(v.backlog_errors("x-1", warn, {"wordplay.charadeInCharade": {}})))
check("and allows what it has", 0, len(v.backlog_errors("x-1", warn, {"wordplay.charadeInCharade": {"x-1": 1}})))
raise SystemExit(fails)
