#!/usr/bin/env python3
# An anagram's fodder is one pool: its pieces are the anagram's own parts, never
# a charade under it. The parser stores ana(x + y) that way, the validator counts
# a charade directly under an anagram, and tools/flatten_anagram_fodder.py
# rewrites the filed ones without changing what view() shows.
import os
import sys
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import copy, json
import annotation, wordplay, validate_annotations as v
import flatten_anagram_fodder as F

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

CLUE = "Dreadfully slay with a cut, producing this?"
t = wordplay.parse("ana<Dreadfully>([slay] + [a] + [cut])", CLUE)
check("ana(x + y + z) stores the pieces as the anagram's parts",
      ["slay", "a", "cut"], [p.get("words") for p in t["parts"]])
check("and renders back the same", "ana<Dreadfully>([slay] + [a] + [cut])", wordplay.render(t))
check("a nested join flattens too", 3,
      len(wordplay.parse("ana<x>(([slay] + [a]) + [cut])")["parts"]))
check("a compound anagram keeps its non-verbatim piece",
      [None, "first"], [p.get("op") for p in wordplay.parse("ana<x>([slay] + first([cut]))")["parts"]])
try:
    wordplay.parse("ana<Dreadfully>([slay] +<with> [a] + [cut])")
    check("an indicator on a join inside ana() is refused", True, False)
except wordplay.WordplayError as e:
    check("an indicator on a join inside ana() is refused", True, "link word" in str(e))
got = wordplay.evaluate(t, "CASUALTY")
check("several parts evaluate to the answer", "CASUALTY", got[id(t)])
check("each part keeps its letters", ["SLAY", "A", "CUT"], [got[id(p)] for p in t["parts"]])
try:
    wordplay.evaluate(wordplay.parse("ana<x>([cas] + [ualty])"), "CASUALTY")
    check("pieces already reading the answer are no anagram", True, False)
except wordplay.WordplayError as e:
    check("pieces already reading the answer are no anagram", True, "no anagram" in str(e))

entry = {"number": 1, "direction": "across", "clue": {"text": CLUE, "enumeration": "8"},
         "solution": "CASUALTY"}
old = {"definitions": [{"text": CLUE, "at": 0}], "andLit": True,
       "wordplay": {"op": "anagram", "indicators": [{"text": "Dreadfully", "at": 0}],
                    "parts": [{"op": "charade", "parts": [{"words": "slay", "at": 11},
                                                          {"words": "a", "at": 21},
                                                          {"words": "cut", "at": 23}]}]}}
check("the validator counts a charade under an anagram", 1, v.anagram_charades(old["wordplay"]))
new = copy.deepcopy(old)
check("the migration flattens it", 1, F.flatten_tree(new["wordplay"]))
check("into the anagram's parts", ["slay", "a", "cut"], [p["words"] for p in new["wordplay"]["parts"]])
check("leaving none to count", 0, v.anagram_charades(new["wordplay"]))
def shown(a):  # view() also echoes the raw wordplay tree, which is what the migration rewrites
    return {k: v for k, v in annotation.view(a, entry).items() if k != "wordplay"}
check("view() shows the same before and after", shown(old), shown(new))
check("the ring deals the clue's fodder", [{"fodder": "SLAYACUT", "gives": "CASUALTY"}],
      annotation.view(new, entry)["assembly"]["anagrams"])
again = copy.deepcopy(new)
check("a second run changes nothing", (0, new), (F.flatten_tree(again["wordplay"]), again))

# Out of clue order: the parts go in clue order.
swapped = copy.deepcopy(old)
swapped["wordplay"]["parts"][0]["parts"].reverse()
F.flatten_tree(swapped["wordplay"])
check("pieces filed out of order come out in clue order", ["slay", "a", "cut"],
      [p["words"] for p in swapped["wordplay"]["parts"]])

kept = copy.deepcopy(old)
kept["wordplay"]["parts"][0]["indicators"] = [{"text": "with", "at": 16}]
check("a join with its own indicator is left for a reading", 0, F.flatten_tree(kept["wordplay"]))
slip = copy.deepcopy(old)
slip["wordplay"].update(unchecked=True, gives="CASUALTY")
check("a charade under an unchecked anagram is left as filed", 0, F.flatten_tree(slip["wordplay"]))

warn = [f"1A: 1 {v.ANAGRAM_CHARADE}: ..."]
check("the ratchet counts it under wordplay.anagramCharade", 1,
      v.count_backlog(warn)["wordplay.anagramCharade"])
check("and refuses one more than a puzzle is allowed", 1,
      len(v.backlog_errors("x-1", warn, {"wordplay.anagramCharade": {}})))
raise SystemExit(fails)
