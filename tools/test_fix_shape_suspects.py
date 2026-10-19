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

# wrongRole: indicators on the wrong one of two nested ops (timesquick-1113 9a ASIMOV).
swap = {"op": "container", "indicators": [{"text": "returned"}], "parts": [
    {"op": "reversal", "indicators": [{"text": "opened by"}], "parts": [{"words": "visa", "gives": "VISA"}]},
    {"words": "medic", "gives": "MO"}]}
new, used = F.repair_tree(swap, "US writer's visa returned, opened by medic", "ASIMOV", {"wrongRole": F.r_wrong_role})
check("returned/opened by trade places", used == ["wrongRole"] and new["indicators"][0]["text"] == "opened by"
      and new["parts"][0]["indicators"][0]["text"] == "returned")
# an op with no indicator takes its parent's word for its type (BUSHRANGER: ana<ignoring>(del(..))).
down = {"op": "anagram", "indicators": [{"text": "ignoring"}], "parts": [
    {"op": "deletion", "parts": [{"words": "a Reagan", "gives": "AREAGAN"}, {"words": "a", "gives": "A"}]}]}
new, used = F.repair_tree(down, "ignoring a Reagan", "REAGAN", {"wrongRole": F.r_wrong_role})
check("ignoring moves down to the deletion", used == ["wrongRole"] and "indicators" not in new
      and new["parts"][0]["indicators"][0]["text"] == "ignoring")
ok_tree = {"op": "container", "indicators": [{"text": "opened by"}], "parts": [
    {"op": "reversal", "indicators": [{"text": "returned"}], "parts": [{"words": "visa", "gives": "VISA"}]},
    {"words": "medic", "gives": "MO"}]}
new, used = F.repair_tree(ok_tree, "visa returned, opened by medic", "ASIMOV", {"wrongRole": F.r_wrong_role})
check("a tree with the words in place is left alone", used == [])
# delSelection: the indicator that names the source word splits into del<not> + first<beginning in>(Hull).
hull = {"op": "deletion", "indicators": [{"text": "not beginning in Hull"}],
        "parts": [{"words": "river at Hull", "gives": "HUMBER"}, {"gives": "H"}]}
new, used = F.repair_tree(hull, "Brown river at Hull (not beginning in Hull)", "UMBER",
                          {"delSelection": F.r_del_selection})
check("not beginning in Hull splits into del + first",
      used == ["delSelection"] and new["indicators"][0]["text"] == "not"
      and new["parts"][1]["op"] == "first" and new["parts"][1]["indicators"][0]["text"] == "beginning in")
wrong = {**hull, "parts": [hull["parts"][0], {"gives": "X"}]}
check("a letter the word does not give is left alone",
      F.repair_tree(wrong, "Brown river at Hull (not beginning in Hull)", "UMBER",
                    {"delSelection": F.r_del_selection})[1] == [])

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
