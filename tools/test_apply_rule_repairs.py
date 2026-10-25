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
sys.exit(1 if fails else 0)
