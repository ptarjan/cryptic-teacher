#!/usr/bin/env python3
# fix_shape_suspects.py ins_split: a container over a flat 3-part charade is part 2 inside
# parts 1+3 when the letters say so and no other reading spells the answer.
#
#     python3 tools/test_fix_shape_suspects.py
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fix_shape_suspects as F

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

def leaf(words, gives):
    return {"words": words, "gives": gives}

def tree(answer, parts):
    return {"op": "container", "unchecked": True, "gives": answer,
            "indicators": [{"text": "in"}], "parts": [{"op": "charade", "parts": parts}]}

clue = "Inn where student's in charge"
wp = tree("PUBLIC", [leaf("Inn", "PUB"), leaf("student", "L"), leaf("in charge", "IC")])
new, used = F.repair_tree(wp, clue)
check("PUB+L+IC becomes PUB(L)IC", used == ["ins_split"] and len(new["parts"]) == 2
      and not new.get("unchecked") and new["parts"][1].get("gives") == "L")
check("outer is parts 1 and 3", [p.get("gives") for p in new["parts"][0]["parts"]] == ["PUB", "IC"])

# O+N+SET: ONSET is N inside O..SET.
new, used = F.repair_tree(tree("ONSET", [leaf("Start", "O"), leaf("number", "N"), leaf("set", "SET")]),
                         "Start number in set")
check("O+N+SET becomes N inside OSET", used == ["ins_split"])

# Letters that do not work either way leave the tree alone.
new, used = F.repair_tree(tree("PUBLIC", [leaf("Inn", "PUB"), leaf("student", "X"), leaf("in charge", "IC")]), clue)
check("wrong letters are not rewritten", used == [] and new.get("unchecked"))

# Ambiguous: two parts could each be the held one.
amb = tree("ABAB", [leaf("a", "AB"), leaf("b", "A"), leaf("c", "B")])
new, used = F.repair_tree(amb, "a b c")
check("an ambiguous nesting is skipped", used == [])

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
