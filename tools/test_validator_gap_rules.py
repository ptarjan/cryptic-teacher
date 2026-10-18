#!/usr/bin/env python3
"""Tests for the validator-gap rules: folded indicators, fake substitution parts, padding leaves and the redo regression gate.

Each rule has a hit and a near-miss; the gate is validate_annotations.redo_regressions."""
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import copy
import shape_queue as Q
import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

# folded_indicators: everyman-4162 25a, the indicator folded into a leaf
folded = {"op": "homophone", "spelt": "EASE", "indicators": [{"text": "pronouncedly", "at": 39}],
          "parts": [{"words": "Principally, Everyman, more than once", "at": 0, "gives": "ES"}]}
check("an indicator folded into a leaf is counted", 1, v.folded_indicators(folded))
near = copy.deepcopy(folded)
near["parts"][0]["words"] = "Everyman, more than once"
near["parts"][0]["at"] = 13
check("a short leaf with no known indicator at its edge is not", 0, v.folded_indicators(near))
long_gives = copy.deepcopy(folded)
long_gives["parts"][0]["gives"] = "ESSAYS"
check("a leaf giving a word (not a 1-2 letter result) is not", 0, v.folded_indicators(long_gives))
one_word = {"op": "homophone", "spelt": "EASE", "indicators": [{"text": "said"}],
            "parts": [{"words": "Principally Everyman", "at": 0, "gives": "E"}]}
check("a two-word leaf with only a one-word edge is not", 0, v.folded_indicators(one_word))
unchecked = copy.deepcopy(folded)
unchecked["parts"][0]["unchecked"] = True
check("an unchecked leaf is left to the padding rule", 0, v.folded_indicators(unchecked))

# fake_parts: sub(sub(x, R, L), AL, AR) with wordless gives nodes
fake = {"op": "substitution", "parts": [
    {"op": "substitution", "parts": [{"words": "non-fiction", "at": 0, "gives": "NONFICTION"},
                                      {"gives": "R"}, {"gives": "L"}]},
    {"gives": "AL"}, {"gives": "AR"}]}
check("a substitution padded with wordless parts is counted", 1, v.fake_parts(fake))
real = copy.deepcopy(fake)
real["parts"][1] = {"words": "alpha", "at": 20, "gives": "AL"}
check("one with the replaced part read from the clue is not", 0, v.fake_parts(real))
single = {"op": "substitution", "parts": [{"words": "x", "at": 0, "gives": "XA"},
                                           {"gives": "A"}, {"gives": "B"}]}
check("a plain substitution is not", 0, v.fake_parts(single))
short = copy.deepcopy(fake)
short["parts"][1], short["parts"][2] = {"gives": "A"}, {"gives": "B"}
check("one-letter wordless parts are not", 0, v.fake_parts(short))

# padding_leaves: unchecked leaf of clue words that gives nothing
pad = {"op": "charade", "parts": [{"words": "no shock", "at": 0, "unchecked": True},
                                   {"words": "x", "at": 9, "gives": "X"}]}
check("an unchecked leaf with no gives is counted", 1, v.padding_leaves(pad))
gives = copy.deepcopy(pad)
gives["parts"][0]["gives"] = "NS"
check("one that says what it gives is not", 0, v.padding_leaves(gives))
dropped = copy.deepcopy(pad)
dropped["parts"][0]["note"] = "dropped: not part of the wordplay"
check("one whose note says it was dropped is not", 0, v.padding_leaves(dropped))
checked = copy.deepcopy(pad)
del checked["parts"][0]["unchecked"]
check("a checked leaf is not", 0, v.padding_leaves(checked))
spoon = {"op": "spoonerism", "parts": [{"words": "no shock", "at": 0, "unchecked": True}]}
check("a spoonerism's sound leaf is not", 0, v.padding_leaves(spoon))
warn = v.shape_warnings("1A", {"wordplay": pad, "definitions": []})
check("shape_warnings reports it", 1, sum(v.PADDING_LEAF in w for w in warn))
for field in ("indFolded", "fakeParts", "paddingLeaf"):
    check(f"wordplay.{field} is a ratchet field", True, f"wordplay.{field}" in v.BACKLOG_MARKERS)

# redo_regressions: the gate every redo of an annotated clue passes
CLUE = "Moral tale, displayed, in part (4)"
good = {"definitions": [{"text": "Moral tale", "at": 0}],
        "wordplay": {"op": "charade", "indicators": [{"text": "displayed, in", "at": 11}],
                     "parts": [{"words": "part", "at": 25, "gives": "PART"}]}}
def redo(new, old=good, clue=CLUE):
    return [r.split(":")[0] for r in v.redo_regressions(old, new, clue)]
dropped_in = copy.deepcopy(good)
dropped_in["wordplay"]["indicators"] = []
check("a redo that drops \"displayed, in\" is refused", ["dropped_words"], redo(dropped_in))
check("a redo that keeps every word is not", [], redo(copy.deepcopy(good)))
check("a word moved into a definition is not dropped", [], redo(
    {**dropped_in, "definitions": [{"text": "Moral tale"}, {"text": "displayed, in"}]}))
check("a tree replaced by none is refused", ["no_tree"], redo({"definitions": good["definitions"], "wordplay": None}))
check("a double definition covering the clue replaces a tree", [], redo(
    {"definitions": [{"text": "Moral tale"}, {"text": "displayed, in part"}]}, clue="Moral tale displayed, in part"))
check("no old tree means no loss", [], redo({"definitions": [], "wordplay": None}, old={"definitions": []}))
bare = {"definitions": good["definitions"], "wordplay": {
    "op": "cryptic", "parts": [{"words": "part", "at": 25}, {"words": "Moral tale, displayed, in", "at": 0}]}}
check("a real tree downgraded to a bare cryptic is refused", ["downgraded"], redo(bare))
check("a bare cryptic redone as a bare cryptic is not", [], redo(copy.deepcopy(bare), old=bare))
check("a bare cryptic upgraded to a real tree is not", [], redo(good, old=bare))
check("a Spooner clue that loses the spoonerism is refused", ["lost_spoonerism"], redo(
    good, old={"definitions": [], "wordplay": None}, clue="Spooner's moral tale, displayed, in part"))
check("shape_queue.regressions delegates to it", ["downgraded"], [r.split(":")[0] for r in Q.regressions(
    {"annotation": good, "clue": {"text": CLUE}}, bare)])
raise SystemExit(fails)
