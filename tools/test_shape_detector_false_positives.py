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
    return {"op": "container", "indicators": [{"text": "without"}],
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

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
