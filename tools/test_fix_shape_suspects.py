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

# delSelection, two ends: "off with Tony's beginning and end" with bare T and Y is two selections.
bush = {"op": "deletion", "indicators": [{"text": "off with Tony's beginning and end", "at": 10}],
        "parts": [{"op": "charade", "parts": [{"words": "Bet", "gives": "BET"}, {"words": "Dubya", "gives": "DUBYA"}]},
                  {"gives": "T"}, {"gives": "Y"}]}
clue5 = "Bet Dubya off with Tony's beginning and end"
new, used = F.repair_tree(bush, clue5, "BEDAUB", {"delSelection": F.r_del_selection})
check("off with Tony's beginning and end splits into del + first + last",
      used == ["delSelection"] and new["indicators"][0]["text"] == "off with"
      and [p.get("op") for p in new["parts"]] == ["charade", "first", "last"]
      and new["parts"][1]["indicators"][0]["text"] == "beginning" and new["parts"][2]["indicators"][0]["text"] == "end")
check("ends the word does not have are left alone",
      F.repair_tree({**bush, "parts": [bush["parts"][0], {"gives": "T"}, {"gives": "N"}]}, clue5, "BEDAUB",
                    {"delSelection": F.r_del_selection})[1] == [])
check("two first-type selectors are left alone",
      F.repair_tree({**bush, "indicators": [{"text": "off with Tony's beginning and start", "at": 10}]},
                    "Bet Dubya off with Tony's beginning and start", "BEDAUB", {"delSelection": F.r_del_selection})[1] == [])

# the word sits on the enclosing charade but belongs to a child op, the child holding a wrong word
# (independent-12410 1a BUSHRANGER): charade<mistakenly>(BUSH, ana<ignoring>(del(..))).
bush = {"op": "charade", "indicators": [{"text": "mistakenly"}], "parts": [
    {"words": "Former US President", "gives": "BUSH"},
    {"op": "anagram", "indicators": [{"text": "ignoring"}], "parts": [
        {"op": "deletion", "parts": [{"words": "R Reagan", "gives": "RANGER"}, {"words": "a", "gives": "A"}]}]}]}
new, used = F.repair_tree(bush, "Former US President — R Reagan — mistakenly ignoring a backwoodsman",
                          "BUSHRANGER", {"wrongRole": F.r_wrong_role})
ana, dele = new["parts"][1], new["parts"][1]["parts"][0]
check("mistakenly moves down to the anagram, ignoring to the deletion",
      "indicators" not in new and ana["indicators"][0]["text"] == "mistakenly"
      and dele["indicators"][0]["text"] == "ignoring")
# three words each on the wrong op rotate (quiptic-1368 14d).
rot = {"op": "container", "indicators": [{"text": "order"}], "parts": [
    {"words": "river", "gives": "EED"},
    {"op": "reversal", "indicators": [{"text": "to enter"}], "parts": [
        {"op": "anagram", "indicators": [{"text": "rising"}], "parts": [{"words": "a silly"}]}]}]}
new, used = F.repair_tree(rot, "Trusting a silly order to enter rising river", "EASILYLED", {"wrongRole": F.r_wrong_role})
check("order/to enter/rising rotate to their ops", new["indicators"][0]["text"] == "to enter"
      and new["parts"][1]["indicators"][0]["text"] == "rising"
      and new["parts"][1]["parts"][0]["indicators"][0]["text"] == "order")
# a parent word the corpus has no owner for trades with the child's: ins<frenziedly>(ana<crossing>(..), R).
unk = {"op": "container", "indicators": [{"text": "frenziedly"}], "parts": [
    {"op": "anagram", "indicators": [{"text": "crossing"}], "parts": [{"words": "A squire"}]},
    {"words": "river", "gives": "R"}]}
new, used = F.repair_tree(unk, "A squire frenziedly crossing river", "QUARRIES", {"wrongRole": F.r_wrong_role})
check("an unowned word trades with the child's", new["indicators"][0]["text"] == "crossing"
      and new["parts"][0]["indicators"][0]["text"] == "frenziedly")
# a leaf folding two cuts (cyclops-770 14d TRICOLOUR): Labour's lacking a British -> LOUR.
clue2 = "Cor! It's awful — Labour's lacking a British standard"
fold = {"words": "Labour's lacking a British", "gives": "LOUR", "at": clue2.index("Labour")}
got = F.r_leaf_fold(fold, None, {"clue": clue2, "under_unchecked": set()})
check("two cuts become a deletion of A and B from Labour", got is not None and got["op"] == "deletion"
      and [p["words"] for p in got["parts"]] == ["Labour", "a", "British"]
      and [p.get("gives") for p in got["parts"][1:]] == ["A", "B"])
bad = {**fold, "gives": "LOUX"}
check("two cuts that do not spell the letters are left", F.r_leaf_fold(bad, None, {"clue": clue2, "under_unchecked": set()}) is None)

# A role move leaves the selection op without a word, and its leaf holding the selector
# (cyclops-757 28a TRUCE): the leaf keeps the source, the selector becomes the indicator.
clue3 = "Faithful embracing Conservative leader"
sel = {"op": "container", "parts": [{"words": "Faithful", "gives": "TRUE"},
       {"op": "first", "indicators": [{"text": "embracing"}], "parts": [{"words": "Conservative leader"}]}]}
new, used = F.repair_tree(sel, clue3, "TRUCE", {"wrongRole": F.r_wrong_role})
new, used2 = F.repair_tree(new, clue3, "TRUCE", F.FOLLOW_ON)
check("the container takes its word back", new["indicators"][0]["text"] == "embracing")
check("the selection takes the selector off its leaf", used2 == ["sel_edge"]
      and new["parts"][1]["indicators"][0]["text"] == "leader" and new["parts"][1]["parts"][0]["words"] == "Conservative")
# the selector already the op's indicator: the leaf just loses it (cyclops-490 13d, unchecked).
un = {"op": "last", "unchecked": True, "gives": "E", "indicators": [{"text": "ultimately"}], "parts": [
    {"unchecked": True, "words": "substitute, ultimately", "gives": "E", "at": 0}]}
got = F.r_sel_edge(un, None, {})
check("an unchecked pick keeps its letters and loses the selector", got["parts"][0]["words"] == "substitute"
      and got["parts"][0]["gives"] == "E" and got["indicators"][0]["text"] == "ultimately")
# a leaf filed with a pick (cyclops-454 8a): the selection op, the end named by the selector.
clue4 = "Players pissed round toilet's entrance"
got = F.r_leaf_select({"words": "toilet's entrance", "gives": "T", "at": clue4.index("toilet")}, {"op": "container"}, {})
check("toilet's entrance is first<entrance>(toilet)", got["op"] == "first" and got["indicators"][0]["text"] == "entrance"
      and got["parts"][0]["words"] == "toilet")
# a deletion a repair makes new gets a note
tr = F.note_deletions({"op": "deletion", "indicators": [{"text": "lacking heart"}], "parts": [{"words": "Scot"}, {"gives": "CO"}]})
check("a new deletion indicator is noted", tr["indicators"][0]["note"])
# extremely on a one-end pick: outer, only when the letters then spell the answer
ex = {"op": "charade", "parts": [{"words": "Lion", "gives": "LION"},
      {"op": "last", "indicators": [{"text": "extremely"}], "parts": [{"words": "tough"}]}]}
new, used = F.repair_tree(ex, "Lion extremely tough", "LIONTH", {"wrongRole": F.r_wrong_role})
check("last<extremely> becomes outer when both ends spell the answer", used == ["wrongRole"] and new["parts"][1]["op"] == "outer")
new, used = F.repair_tree(ex, "Lion extremely tough", "LIONH", {"wrongRole": F.r_wrong_role})
check("and stays one end when they do not", new["parts"][1]["op"] == "last")

# a selection indicator hung on the one-letter "a" belongs to the neighbouring word (cyclops-542 15a AMBUSH)
sc = "Ex-president's after a lead from Monica to jump"
sw = {"op": "charade", "parts": [
    {"op": "first", "indicators": [{"text": "lead from"}], "parts": [{"words": "a"}]},
    {"words": "Monica", "gives": "M"}, {"words": "Ex-president", "gives": "BUSH"}]}
new, used = F.repair_tree(sw, sc, "AMBUSH", {"wrongRole": F.r_wrong_role})
check("first<lead from>(a) moves onto Monica", used == ["wrongRole"] and new["parts"][0] == {"words": "a"}
      and new["parts"][1]["op"] == "first" and new["parts"][1]["parts"][0]["words"] == "Monica")
sw2 = {"op": "charade", "parts": [
    {"op": "first", "indicators": [{"text": "at first"}], "parts": [{"words": "a"}]},
    {"words": "lager at first", "gives": "L"}]}
new, used = F.repair_tree(sw2, "a lager at first", "AL", {"wrongRole": F.r_wrong_role})
check("a selector at the edge of the other leaf's words is trimmed off it",
      used == ["wrongRole"] and new["parts"][1]["op"] == "first" and new["parts"][1]["parts"][0]["words"] == "lager")
sw3 = {"op": "charade", "parts": [
    {"op": "first", "indicators": [{"text": "lead from"}], "parts": [{"words": "a"}]},
    {"words": "Monica", "gives": "X"}]}
new, used = F.repair_tree(sw3, sc, "AX", {"wrongRole": F.r_wrong_role})
check("no neighbour whose pick matches: left for the model", used == [])
# a cut by a table abbreviation inside a folded deletion leaf (dive, leaving five -> DIE)
fc = "Mistake during dive, leaving five engineers behind"
fl = {"op": "charade", "parts": [{"words": "dive, leaving five", "gives": "DIE", "at": fc.index("dive")}]}
new, used = F.repair_tree(fl, fc, "DIE", {"wrongRole": F.r_wrong_role})
check("dive, leaving five is del<leaving>(dive, V)", used == ["wrongRole"] and (new := new["parts"][0])["op"] == "deletion"
      and new["indicators"][0]["text"] == "leaving" and new["parts"][1]["gives"] == "V")

# sharedIndicator: the deletion indicator's words filed again as a leaf giving the result
SI = {"sharedIndicator": F.r_shared_indicator}
sic = "Pen exclusive news item, not the first"
si = {"op": "deletion", "indicators": [{"text": "not the first"}], "parts": [
    {"op": "charade", "parts": [{"words": "exclusive news item", "gives": "SCOOP"},
                                {"words": "not the first", "gives": "COOP"}]}, {"gives": "SCOOP"}]}
new, used = F.repair_tree(si, sic, "COOP", SI)
check("the restated result goes, the removed letter is read off",
      used == ["sharedIndicator"] and new["op"] == "deletion" and new["parts"][0]["words"] == "exclusive news item"
      and new["parts"][1] == {"gives": "S"} and len(new["parts"]) == 2)
sic2 = "Man snubbed sullen young woman"
si2 = {"op": "deletion", "indicators": [{"text": "snubbed"}], "parts": [{"op": "charade", "parts": [
    {"words": "sullen", "gives": "DOUR"}, {"words": "snubbed", "gives": "DOU"}, {"words": "young woman", "gives": "GAL"}]},
    {"gives": "DOUR"}]}
new, used = F.repair_tree(si2, sic2, "DOUGAL", SI)
check("the other charade parts stay outside the deletion", used == ["sharedIndicator"] and new["op"] == "charade"
      and new["parts"][0]["op"] == "deletion" and new["parts"][1]["words"] == "young woman")
sic3 = "Destitution unlimited is plain"
si3 = {"op": "deletion", "indicators": [{"text": "unlimited"}], "parts": [{"op": "charade", "parts": [
    {"words": "Destitution", "gives": "POVERTY"}, {"words": "unlimited", "gives": "OVERT"}]}, {"gives": "POVERTY"}]}
new, used = F.repair_tree(si3, sic3, "OVERT", SI)
check("unlimited takes both ends", used == ["sharedIndicator"] and new["parts"][1] == {"gives": "PY"})
si4 = {"op": "deletion", "indicators": [{"text": "short"}], "parts": [{"op": "charade", "parts": [
    {"words": "fat", "gives": "LARD"}, {"words": "short", "gives": "BLAH"}]}, {"gives": "LARD"}]}
new, used = F.repair_tree(si4, "fat short", "BLAH", SI)
check("a result the source does not give is left for the model", used == [])

# containerInside under a reversal: rev(ins(NOTE+L, P)) is NOT(P)E+L reversed; the P goes into NOTE
# even though the two shapes tie on simplicity (cryptic-29035 9a LEPTON).
cic = "Observe learner keeping quiet - backward type interacting weakly"
lep = {"op": "reversal", "indicators": [{"text": "backward"}], "parts": [
    {"op": "container", "indicators": [{"text": "keeping"}], "parts": [
        {"op": "charade", "parts": [{"words": "Observe", "gives": "NOTE"}, {"words": "learner", "gives": "L"}]},
        {"words": "quiet", "gives": "P"}]}]}
new, used = F.repair_tree(lep, cic, "LEPTON", {"containerInside": F.r_container_inside})
check("ins(NOTE+L, P) under rev becomes NOTE-with-P + L", used == ["containerInside"]
      and new["parts"][0]["op"] == "charade" and new["parts"][0]["parts"][0]["op"] == "container"
      and new["parts"][0]["parts"][1]["gives"] == "L")

# poolGap: an anagram's fodder pieces with another op's words between them
PG = {"poolGap": F.r_pool_gap}
pgc = "dishevelled rake embraced by whore"
pg = {"op": "container", "unchecked": True, "gives": "SHAKERAG", "indicators": [{"text": "embraced by"}], "parts": [
    {"op": "anagram", "indicators": [{"text": "dishevelled"}], "parts": [
        {"words": "rake"}, {"words": "whore", "gives": "SHAG"}]}]}
new, used = F.repair_tree(pg, pgc, "SHAKERAG", PG)
check("a fodder piece that is the container's other arm leaves the pool",
      used == ["poolGap"] and new["op"] == "container" and len(new["parts"]) == 2
      and new["parts"][0]["words"] == "whore" and [p["words"] for p in new["parts"][1]["parts"]] == ["rake"])
pgc2 = "Camels wandering about every second"
pg2 = {"op": "container", "indicators": [{"text": "wandering"}], "parts": [
    {"op": "anagram", "indicators": [{"text": "about"}], "parts": [{"words": "Camels"}, {"words": "every", "gives": "ALL"}]},
    {"words": "second", "gives": "S"}]}
new, used = F.repair_tree(pg2, pgc2, "SMALLSCALE", PG)
check("an anagram-word container indicator beside the anagram's folds the pieces into one pool",
      used == ["poolGap"] and new["op"] == "anagram" and len(new["parts"]) == 3
      and [i["text"] for i in new["indicators"]] == ["wandering", "about"])
pg3 = {"op": "container", "indicators": [{"text": "embraced by"}], "parts": [
    {"op": "anagram", "indicators": [{"text": "dishevelled"}], "parts": [{"words": "rake"}, {"words": "whore", "gives": "SHAG"}]}]}
new, used = F.repair_tree(pg3, pgc, "SHAGRAKE", PG)
check("no piece order that gives the answer: left for the model", used == [])

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
