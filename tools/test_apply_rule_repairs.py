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
# spanOverlap residue (10-26 audit, 9 first checks): the clue words one piece shares with another at its edge
# NOTED (cryptic-27795 23d): the charade's "on top of" and the selection's "top of" -> the outer gives back "top of"
wp = {"op": "charade", "indicators": [ind("on top of")], "parts": [leaf("Letter", "NOTE"),
      {"op": "first", "indicators": [ind("top of")], "parts": [leaf("desk")]}]}
entry = {"solution": "NOTED", "clue": {"text": "Letter on top of desk is prominent"}}
check("spanOverlap fires on two indicators sharing 'top of'", counters["spanOverlap"](wp, {}, entry["clue"]["text"]) == 1)
new = A.repair_pool_gap({"wordplay": wp}, entry)["wordplay"]
check("spanOverlap: the outer indicator is cut back to 'on'", new["indicators"][0]["text"] == "on"
      and not counters["spanOverlap"](new, {}, entry["clue"]["text"]))

# GRAUNIAD (cryptic-27782 2d): the leaf "A place for learning" (UNI) swallows the leaf "A" before it
wp = {"op": "charade", "parts": [leaf("A", "A"), leaf("A place for learning", "UNI")]}
entry = {"solution": "AUNI", "clue": {"text": "A place for learning"}}
new = A.repair_pool_gap({"wordplay": wp}, entry)["wordplay"]
check("spanOverlap: the outer leaf gives its first word to the leaf before it",
      new["parts"][1]["words"] == "place for learning" and not counters["spanOverlap"](new, {}, entry["clue"]["text"]))

# NINJA (ftcryptic-16385 9a): "in#2" printed inside the hidden-word leaf, the clue prints "in" free before it
wp = {"op": "hidden", "indicators": [ind("in")], "parts": [leaf("competition in Japan")]}
entry = {"solution": "NINJA", "clue": {"text": "Martial art expert in competition in Japan"}}
wp["indicators"][0]["at"] = 34
new = A.repair_pool_gap({"wordplay": wp}, entry)["wordplay"]
check("spanOverlap: an indicator inside the leaf moves to its one free occurrence",
      new["indicators"][0]["at"] == 19 and not counters["spanOverlap"](new, {}, entry["clue"]["text"]))

# the refusal names the words: DODO (cryptic-27779 10a) uses "parties" as indicator and leaf
import validate_annotations as V
import wordplay
wp = wordplay.locate({"op": "repeat", "indicators": [ind("parties")], "parts": [leaf("parties", "DO")]},
                     "Old-fashioned person's parties")
msgs = V.shape_warnings("10A", {"wordplay": wp})
check("spanOverlap message names the shared words",
      any("indicator 'parties' and leaf 'parties' both claim 'parties'" in m for m in msgs))

# doesNotGive residue (10-24..26 audit, 665 distinct refusals sampled): a container's arguments the wrong way round
# (CALLOW) and a charade out of order (TSHIRT) are mended when exactly one edit gives the answer; the rest are named
def mend(wp, clue, ans):
    try:
        return wordplay.render(wordplay.translate({"wp": wp, "notes": {}}, clue, ans))
    except wordplay.WordplayError as e:
        return "REFUSED " + str(e)
check("doesNotGive: a container with its arguments swapped is mended in place",
      mend("ins<worn by>([Everyone]ALL, [Jersey, say]COW)", "Everyone is worn by Jersey, say", "CALLOW")
      == "ins<worn by>([Jersey, say]COW, [Everyone]ALL)")
check("doesNotGive: a charade out of order is mended in place",
      mend("last<end of>([market]) + ana<new>([this]) + last<ultimately>([couturier])",
           "market this new ultimately couturier end of", "TSHIRT").startswith("ana<new>([this]) + last<ultimately>"))
amb = {"op": "charade", "parts": [leaf("a", "A"), leaf("b", "B"), leaf("ab", "AB")]}
bad = dict(amb, parts=[amb["parts"][0], amb["parts"][2], amb["parts"][1]])
check("doesNotGive fixer declines when two orders give the answer (A+AB+B: AB+A+B and A+B+AB both do)",
      F.RULE_REPAIRS["doesNotGive"](bad, None, {"clue": "a b ab", "answer": "ABAB"}) is None)
check("doesNotGive counter fires on a tree that does not give the answer, not on one that does",
      counters["doesNotGive"](bad, {"_answer": "ABAB"}, "a b ab") == 1 and counters["doesNotGive"](amb, {"_answer": "ABAB"}, "") == 0)
msg = mend("[Perfect]HONEY + rev<brought about>([team]PARTY)", "Perfect team brought about", "HONEYTRAP")
check("doesNotGive: a letter doubled at the join is named, not mended", msg.startswith("REFUSED") and "one letter too many" in msg and "extra Y" in msg)
msg = mend("[Question]Q + [concerned with]IN + [church]CE", "Question concerned with church", "QUINCE")
check("doesNotGive: a letter missing at the join is named, not mended", "one letter short of QUINCE: U is missing at letter 2" in msg)
sys.exit(1 if fails else 0)
