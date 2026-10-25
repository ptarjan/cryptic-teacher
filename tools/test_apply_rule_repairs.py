#!/usr/bin/env python3
# The first check runs every bag fixer (fix_shape_suspects.RULE_REPAIRS) whose rule fires, so a
# fixer added later is picked up with no edit here, and an anaLoneEdge anagram is mended in place.
#
#     python3 tools/test_apply_rule_repairs.py
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "tools")
import apply_annotations as A
import fix_shape_suspects as F

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

# delSelection is no validator rule (its rows come from --ids): nothing can fire it.
NO_DETECTOR = {"delSelection"}
missing = sorted(set(F.RULE_REPAIRS) - set(A.rule_counters()) - NO_DETECTOR)
check("every RULE_REPAIRS key has a detector the first check can count: " + ", ".join(missing), not missing)

# CASTANCHOR: two lone C's in the fodder, the answer starts with one: C + ana(TAR HAS + C + ON)
leaf = lambda w, g=None: {"words": w, "note": "taken as written"} if g is None else {"words": w, "gives": g, "note": "abbreviation"}
wp = {"op": "anagram", "indicators": [{"text": "windy", "note": "windy things are blown about"}],
      "parts": [leaf("Tar has"), leaf("caught", "C"), leaf("cold", "C"), leaf("on")]}
entry = {"solution": "CASTANCHOR", "clue": {"text": "Tar has caught cold on windy moor"}}
new = A.repair_pool_gap({"wordplay": wp}, entry)["wordplay"]
check("anaLoneEdge anagram is mended in place", new.get("op") == "charade" and not A.rule_counters()["anaLoneEdge"](new, {"_answer": "CASTANCHOR"}, ""))
counters = A.rule_counters()

# DADAIST (cryptic-29712 24a): the container's indicator "is captivated by" swallows the leaf "is"
ind = lambda t: {"text": t, "note": "n"}
wp = {"op": "charade", "parts": [leaf("Family man", "DAD"),
      {"op": "container", "indicators": [ind("is captivated by")],
       "parts": [{"op": "outer", "indicators": [ind("extremes")], "parts": [leaf("artist's", "ARTIST")]}, leaf("is")]}]}
entry = {"solution": "DADAIST", "clue": {"text": "Family man is captivated by artist's extremes: one's a shocker"}}
check("spanOverlap fires on the swallowed leaf", counters["spanOverlap"](wp, {}, entry["clue"]["text"]) == 1)
new = A.repair_pool_gap({"wordplay": wp}, entry)["wordplay"]
check("spanOverlap: the indicator gives the leaf its word back", new["parts"][1]["indicators"][0]["text"] == "captivated by"
      and not counters["spanOverlap"](new, {}, entry["clue"]["text"]))

# TENORDRUM (times-26927 16d): one leaf inside another is the model's to read, so the fixer declines
check("spanOverlap: a leaf inside another leaf is left alone",
      A.repair_pool_gap({"wordplay": {"op": "charade", "parts": [leaf("pound", "LB"), leaf("a few pound", "XX")]}},
                        {"solution": "LBXX", "clue": {"text": "a few pound"}})["wordplay"]["parts"][1]["words"] == "a few pound")

# SANGRIA (telegraph-31055 21d): a charade of the clue's own words under the anagram is the anagram's parts
wp = {"op": "anagram", "indicators": [ind("fighting")], "parts": [{"op": "charade", "parts": [leaf("Gran is"), leaf("a")]}]}
entry = {"solution": "SANGRIA", "clue": {"text": "Gran is fighting over a drink"}}
check("anaCharade fires on the charade under the anagram", counters["anaCharade"](wp, {"_answer": "SANGRIA"}, "") == 1)
new = A.repair_pool_gap({"wordplay": wp}, entry)["wordplay"]
check("anaCharade: the pieces become the anagram's parts, in order",
      [p["words"] for p in new["parts"]] == ["Gran is", "a"] and not counters["anaCharade"](new, {"_answer": "SANGRIA"}, ""))

# an abbreviation piece (DRAWERS, times-26720 9a "Doctor") is never flattened into the scramble
wp = {"op": "anagram", "indicators": [ind("madly")], "parts": [{"op": "charade", "parts": [leaf("Doctor", "DR"), leaf("was")]}]}
entry = {"solution": "DRAWS", "clue": {"text": "Doctor was madly"}}
new = A.repair_pool_gap({"wordplay": wp}, entry)["wordplay"]
check("anaCharade: an abbreviation piece does not join the anagram's parts",
      not any(n.get("op") == "anagram" and any(p.get("words") == "Doctor" for p in n.get("parts") or [])
              for n in F.V._walk(new)))
sys.exit(1 if fails else 0)
