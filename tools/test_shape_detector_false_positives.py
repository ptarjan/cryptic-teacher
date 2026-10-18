#!/usr/bin/env python3
"""The shape detectors (shape_suspects, via shape_queue.findings) must not flag clues no
re-annotation can clear: a spoonerism's sound leaf and a select leaf are unchecked by
design, a word the clue says twice can be an indicator and sit in a leaf, and an
unclued "*" is not a rebus. Each case also has its true positive, which must still fire."""
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import shape_queue as Q
import validate_annotations as V

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

def kinds(clue, sol, wp, defs=()):
    entry = {"clue": {"text": clue}, "solution": sol,
             "annotation": {"wordplay": wp, "definitions": list(defs)}}
    return sorted(f.split(":")[0] for f in Q.findings(entry))

# 1. sundaytough-121#8a: the sound leaf under a spoonerism
spoon = lambda extra: {"op": "spoonerism", "unchecked": True, "gives": "POTHOLES",
    "indicators": [{"text": "according to Spooner"}],
    "parts": [{"unchecked": True, "words": "inflamed Europeans", "gives": "POTHOLES", **extra}]}
C1 = "Driving hazards inflamed Europeans according to Spooner"
check("spoonerism sound leaf is not flagged", [], kinds(C1, "POTHOLES", spoon({"soundsLike": "HOT POLES"})))
check("an unchecked leaf with no soundsLike still is", ["unchecked_leaf"], kinds(C1, "POTHOLES", spoon({})))
check("soundsLike outside a spoonerism still is", ["unchecked_leaf"], kinds(
    "x inflamed Europeans", "POTHOLES",
    {"op": "charade", "parts": [{"unchecked": True, "words": "inflamed Europeans", "gives": "POTHOLES", "soundsLike": "HOT POLES"}]}))

# 2. quiptic-1261#22a: a select leaf gives letters picked from its words
sel = lambda gives: {"op": "first", "unchecked": True, "gives": gives, "indicators": [{"text": "Half of"}],
    "parts": [{"unchecked": True, "words": "cons", "gives": gives, "select": "first"}]}
check("select leaf is not flagged", [], kinds("Half of cons stayed", "CO", sel("CO")))
check("select leaf giving letters not in its words still is", ["unchecked_leaf"], kinds("Half of cons stayed", "XY", sel("XY")))

# 3. cryptic-30041#17a: "without" said twice, indicator once and in a leaf once
def jog(clue):
    return {"op": "container", "unchecked": True, "indicators": [{"text": "without"}],
            "parts": [{"words": "without clothes", "gives": "NUDE"}, {"words": "much money", "gives": "G"}]}
check("a word the clue says twice is not flagged", 0, V.ind_in_leaf(jog(""), "Jog without clothes, without much money"))
check("a word the clue says once still is", 1, V.ind_in_leaf(jog(""), "Jog without clothes, much money"))
check("no clue given counts text only", 1, V.ind_in_leaf(jog("")))
check("detector agrees (twice)", [], [k for k in kinds("Jog without clothes, without much money", "NUDGE", jog(""))])
check("detector agrees (once)", ["ind_in_leaf"], kinds("Jog without clothes, much money", "NUDGE", jog("")))

# 4. genius-106#19a: an unclued "*" is no rebus; a real rebus clue still is
star = {"op": "cryptic", "parts": [{"words": "*"}]}
check("an unclued star is not a rebus", [], kinds("*", "ACTORS", star))
check("a capitals rebus still is", ["rebus"], kinds("HIJKLMNO", "WATER", star))

# 5. azed-2088#13d: sound leaves under spoonerism > charade
def spoon_charade(sounds):
    leaf = lambda w, g, s: {"unchecked": True, "words": w, "gives": g, **({"soundsLike": s} if sounds else {})}
    return {"op": "spoonerism", "unchecked": True, "gives": "SECONDBEST", "indicators": [{"text": "Spooner's"}],
            "parts": [{"op": "charade", "parts": [leaf("summoned", "SECOND", "BECKONED"), leaf("taxed", "BEST", "CESSED")]}]}
check("sound leaves under spoonerism > charade are not flagged", [], kinds("Spooner's summoned, taxed", "SECONDBEST", spoon_charade(True)))
check("the same leaves with no soundsLike still are", ["unchecked_leaf"], kinds("Spooner's summoned, taxed", "SECONDBEST", spoon_charade(False)))

# 6. cryptic-29817#24d: a letterless leaf under a hidden whose gives is a run of its words
def hid(gives):
    return {"op": "hidden", "unchecked": True, "gives": gives, "indicators": [{"text": "includes"}],
            "parts": [{"unchecked": True, "words": "Article which", "note": "the run of letters"}]}
check("letterless hidden leaf is not flagged", [], kinds("Article which includes old part", "CLEW", hid("CLEW")))
check("a hidden whose gives is not in its words still is", ["unchecked_leaf"], kinds("Article which includes old part", "XQZ", hid("XQZ")))

# 7. toughie-1687#9a: a one-part substitution is a letter swap, not a redo
sub = lambda parts: {"op": "substitution", "unchecked": True, "gives": "SONNET", "indicators": [{"text": "switching"}],
                     "parts": parts}
tonnes = {"words": "weight", "gives": "TONNES"}
check("one-part substitution is not flagged", [], kinds("Poem given weight when switching", "SONNET", sub([tonnes])))
check("two-part substitution is not flagged", [], kinds("Poem given weight when switching", "SONNET", sub([tonnes, {"words": "x", "gives": "T"}])))
check("four-part substitution still is", ["arity_other"], kinds("Poem given weight when switching", "SONNET",
      sub([tonnes, {"words": "a", "gives": "T"}, {"words": "b", "gives": "S"}, {"words": "c", "gives": "S"}])))

# Multi-piece deletion: BADASS = ana(del(bastards, T, R)) is valid, not "del has 3 parts".
badass = {"op": "anagram", "indicators": [{"text": "wild"}], "parts": [
    {"op": "deletion", "unchecked": True, "parts": [{"words": "bastards", "gives": "BASTARDS"},
        {"words": "T", "gives": "T"}, {"words": "R", "gives": "R"}]}]}
check("a three-part deletion is not arity_other", [], kinds("Wild bastards", "BADASS", badass))

# Stale model-fixable / walkthrough rows are settled once the tree gives the answer / the walk follows it.
def row(sol, wp, walk=None):
    return {"clue": {"text": "Wild bastards"}, "solution": sol,
            "annotation": {"wordplay": wp, "explanation": {"walkthrough": walk}}}
BAD = "model-fixable: bad tree, the wordplay does not give the answer (wrong string, mechanical repairs tried)"
checked = {**badass, "parts": [{k: v for k, v in badass["parts"][0].items() if k != "unchecked"}]}
check("model-fixable row whose tree now gives the answer is settled", True, Q.settled(row("BADASS", checked), BAD))
check("model-fixable row whose tree misses the answer is kept", False, Q.settled(row("BADGER", checked), BAD))
check("walkthrough row with no walkthrough gap is settled", True,
      Q.settled(row("BADASS", badass), "walkthrough: it never names the indicators 'wild'"))

# Data bug: solution length against the printed count (reported, never queued).
import prune_shape_queue as PQ
check("solution shorter than its count is a data bug", True,
      bool(PQ.length_bug({"solution": "PARTING", "clue": {"text": "x", "enumeration": "7,4"}})))
check("a linked group's leader prints the whole count", None,
      PQ.length_bug({"solution": "PARTING", "group": ["4-down", "20-down"], "clue": {"text": "x", "enumeration": "7,4"}}))
check("a matching count is fine", None, PQ.length_bug({"solution": "AT HOME", "clue": {"text": "x", "enumeration": "2,4"}}))
check("a worded count with the right total is fine", None,
      PQ.length_bug({"solution": "MOSHAVOVDIM", "clue": {"text": "x (11, two words)"}}))

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
