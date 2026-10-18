#!/usr/bin/env python3
# A hint has to be followable: the walkthrough names each indicator and shows each
# intermediate result, and an anagram, reversal or hidden indicator touches its fodder.
# The two clues a solver could not follow: times-8 56D (EWE: "may come to" sits
# beyond "lamb", and the walkthrough never names it) and cryptic-21785 16D
# (DOMINATE: the walkthrough explains DOME and never says ANTI makes INAT).
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

EWE = "The wee lamb may come to this."
ewe = {"op": "anagram",
       "indicators": [{"text": "may come to", "at": 13}],
       "parts": [{"words": "wee", "at": 4}]}
check("EWE: the indicator is apart from its fodder by lamb", [("may come to", ["lamb"])],
      v.apart_indicators(ewe, EWE))
check("EWE: a walkthrough that never says 'may come to' is a gap", [("indicator", "may come to")],
      v.walkthrough_gaps(ewe, "EWE", "The whole clue does both jobs: a little lamb grows up to be a ewe."))
check("EWE: naming it closes the gap", [],
      v.walkthrough_gaps(ewe, "EWE", "'May come to' tells you to rearrange 'wee'; a lamb may come to be a ewe."))

DOM = "Wildly anti, getting into 13 millennium 11? That's 8"
dom = {"op": "container",
       "indicators": [{"text": "getting into", "at": 13}],
       "parts": [{"words": "13 millennium 11", "at": 26, "gives": "DOME"},
                 {"op": "anagram", "indicators": [{"text": "Wildly", "at": 0}],
                  "parts": [{"words": "anti", "at": 7}]}]}
bad = ("The Millennium Dome, built in Greenwich for the year 2000, was widely mocked "
       "as a naff project; the cross-references to 13 and 11 point to it.")
check("DOMINATE: the walkthrough never says ANTI becomes INAT or names either indicator",
      [("indicator", "getting into"), ("indicator", "Wildly"), ("gives", "INAT")],
      v.walkthrough_gaps(dom, "DOMINATE", bad))
good = ("13 Across is NAFF and 11 Across PROJECT: the Millennium Dome is DOME. Wildly says "
        "to jumble ANTI into INAT, and getting into puts INAT inside DOME: DOM(INAT)E.")
check("DOMINATE: INAT, 'Wildly' and 'getting into' named, no gap", [], v.walkthrough_gaps(dom, "DOMINATE", good))
check("DOMINATE: its indicators touch their fodder", [], v.apart_indicators(dom, DOM))

check("an inflected indicator counts as named", [],
      v.walkthrough_gaps(ewe, "EWE", "A lamb may come to this: wee rearranged."))
check("a link word between indicator and fodder is allowed", [], v.apart_indicators(
    {"op": "anagram", "indicators": [{"text": "mixed", "at": 0}], "parts": [{"words": "wee", "at": 9}]},
    "mixed up wee"))
first = {"op": "first", "indicators": [{"text": "first of", "at": 0}], "parts": [{"words": "learner", "at": 9}]}
check("'first of' read as 'the first L' is named", [],
      v.walkthrough_gaps(first, "L", "Only the first L of the shopping centres is swapped."))
first2 = {"op": "first", "indicators": [{"text": "leader", "at": 0}], "parts": [{"words": "learner", "at": 7}]}
check("a first-letter indicator paraphrased by 'first' is named", [],
      v.walkthrough_gaps(first2, "L", "Take the first letter of learner."))
check("a first-letter indicator with no position word is still a gap", [("indicator", "leader")],
      v.walkthrough_gaps(first2, "L", "Take the letter L from learner."))
tag = v.follow_warnings("56D", {"wordplay": ewe, "explanation": {"walkthrough": "A lamb grows up."}},
                        {"clue": {"text": EWE}, "solution": "EWE", "length": 3}, {})
check("the apart finding is a warning; the gap is not (the rung lists the tree's steps)", [True, False],
      [any(m in w for w in tag) for m in (v.INDICATOR_APART, v.WALKTHROUGH_GAP)])
blog = v.follow_warnings("56D", {"wordplay": ewe, "fromBlog": True, "explanation": {"walkthrough": "A lamb grows up."}},
                         {"clue": {"text": EWE}, "solution": "EWE", "length": 3}, {})
check("a blog ladder shows no step list, so its prose must follow the tree", True,
      any(v.WALKTHROUGH_GAP in w for w in blog))
raise SystemExit(fails)
