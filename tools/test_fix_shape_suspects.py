#!/usr/bin/env python3
# fix_shape_suspects.py ins_split: a container over a flat 3-part charade is part 2 inside
# parts 1+3 when the letters say so and no other reading spells the answer.
#
#     python3 tools/test_fix_shape_suspects.py
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fix_shape_suspects as F
import validate_annotations as V

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
# r_container_cut: a cut word on the container goes onto a deletion over the leaf it cuts.
dol = {"op": "charade", "indicators": [{"text": "broken by"}], "parts": [
    {"words": "note", "gives": "DO"},
    {"op": "container", "indicators": [{"text": "endlessly"}], "parts": [
        {"words": "records", "gives": "LPS"}, {"words": "China", "gives": "HIN", "note": "cHINa without its two ends"}]}]}
new, used = F.repair_tree(dol, "Swimmers note records broken by China endlessly", "DOLPHINS", {"wrongRole": F.r_wrong_role})
cont = new["parts"][1] if used else {}
check("endlessly moves onto del(China, C, A) and broken by onto the container (DOLPHINS)",
      "wrongRole" in used and cont.get("indicators", [{}])[0].get("text") == "broken by"
      and cont["parts"][1].get("op") == "deletion" and cont["parts"][1]["indicators"][0]["text"] == "endlessly"
      and [p.get("gives") for p in cont["parts"][1]["parts"][1:]] == ["C", "A"])
mor = {"op": "container", "indicators": [{"text": "accepting"}, {"text": "nearly"}], "parts": [
    {"words": "Increasingly", "gives": "MORE"}, {"words": "everyone", "gives": "AL", "note": "ALL minus its last letter"}]}
new, used = F.repair_tree(mor, "Increasingly accepting nearly everyone's state of mind", "MORALE", {"wrongRole": F.r_wrong_role})
check("nearly moves onto del(ALL, L) from the capital word in the note (MORALE)",
      used and new["indicators"][0]["text"] == "accepting" and new["parts"][1]["op"] == "deletion"
      and new["parts"][1]["parts"][0]["gives"] == "ALL")
# a cut that fits no end is left alone
bad = {"op": "container", "indicators": [{"text": "accepting"}, {"text": "nearly"}], "parts": [
    {"words": "Increasingly", "gives": "MORE"}, {"words": "everyone", "gives": "LA", "note": "ALL minus its last letter"}]}
new, used = F.repair_tree(bad, "Increasingly accepting nearly everyone's state of mind", "MORLAE", {"wrongRole": F.r_wrong_role})
check("a cut word whose end does not fit is left alone", new["parts"][1].get("op") is None)

# r_ind_trade: two ops each carrying the other's word (loose bar), nested or siblings, or one unknown word.
trade = {"op": "container", "indicators": [{"text": "mad"}], "parts": [
    {"op": "anagram", "indicators": [{"text": "about"}], "parts": [{"words": "Americans"}]},
    {"words": "work", "gives": "GO"}]}
new, used = F.repair_tree(trade, "Americans mad about work, as this lot are", "ERGOMANIACS", {"wrongRole": F.r_wrong_role})
check("mad/about trade places (ERGOMANIACS)", used == ["wrongRole"] and new["indicators"][0]["text"] == "about"
      and new["parts"][0]["indicators"][0]["text"] == "mad")
sib = {"op": "charade", "parts": [
    {"op": "reversal", "indicators": [{"text": "first to"}], "parts": [{"words": "Laid"}]},
    {"op": "first", "indicators": [{"text": "back"}], "parts": [{"words": "English"}]}]}
new, used = F.repair_tree(sib, "Laid back English", "DIALE", {"wrongRole": F.r_wrong_role})
check("sibling ops trade first to/back (DIALECT)", used == ["wrongRole"] and new["parts"][0]["indicators"][0]["text"] == "back"
      and new["parts"][1]["indicators"][0]["text"] == "first to")
unk = {"op": "container", "indicators": [{"text": "Awfully"}], "parts": [
    {"op": "anagram", "indicators": [{"text": "to have pocketed"}], "parts": [{"words": "sorry"}]}, {"words": "a", "gives": "A"}]}
new, used = F.repair_tree(unk, "Awfully sorry to have pocketed a", "ROSARY", {"wrongRole": F.r_wrong_role})
check("an unseen word trades with the anagram word (ROSARY)", used == ["wrongRole"] and new["indicators"][0]["text"] == "to have pocketed"
      and new["parts"][0]["indicators"][0]["text"] == "Awfully")
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
PGE = {"poolGap": F.RULE_REPAIRS["poolGap"]}
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
# Since round 17 an enclosing op's indicator standing between the pieces is no pool gap
# (V.pool_gaps skips it), so poolGap no longer flags this clue and the repair leaves it alone.
check("an enclosing container's indicator between the pieces is no pool gap: left alone",
      used == [] and new["op"] == "container")
pg3 = {"op": "container", "indicators": [{"text": "embraced by"}], "parts": [
    {"op": "anagram", "indicators": [{"text": "dishevelled"}], "parts": [{"words": "rake"}, {"words": "whore", "gives": "SHAG"}]}]}
new, used = F.repair_tree(pg3, pgc, "SHAGRAKE", PG)
check("no piece order that gives the answer: left for the model", used == [])
pg4 = {"op": "container", "indicators": [{"text": "split", "at": 0}], "parts": [
    {"op": "anagram", "indicators": [{"text": "frightfully", "at": 6}], "parts": [{"words": "large", "at": 18}, {"words": "One", "gives": "I", "at": 14}]},
    {"words": "therefore", "gives": "SO", "at": 24}]}
new, used = F.repair_tree(pg4, "split One frightfully large therefore", "GIRASOLE", PG)
check("split (a container word too) over an anagram is a real insertion: not folded into one pool", used == [])

# poolGap, a piece in the pool that is really another op's: it leaves the pool
pge = {"op": "charade", "parts": [{"words": "bloke", "gives": "HE", "at": 22},
    {"op": "anagram", "indicators": [{"text": "Unusual", "at": 0}], "parts": [
        {"op": "last", "indicators": [{"text": "close to", "at": 28}], "parts": [{"words": "union", "at": 37}]},
        {"words": "thing", "at": 8}]}]}
new, used = F.repair_tree(pge, "Unusual thing to have bloke close to union at?", "HENNIGHT", PGE)
check("a last-letter piece far from the pool leaves the anagram and charades beside it",
      used == ["poolGap"] and [p.get("op") or p["words"] for p in new["parts"]] == ["bloke", "last", "anagram"]
      and [p["words"] for p in new["parts"][2]["parts"]] == ["thing"])
pge2 = {"op": "container", "indicators": [{"text": "in", "at": 25}], "parts": [
    {"op": "anagram", "indicators": [{"text": "wrought", "at": 28}], "parts": [{"words": "gold", "at": 36}, {"words": "a", "at": 12}]},
    {"words": "small coin", "gives": "P", "at": 14}]}
new, used = F.repair_tree(pge2, "Toady given a small coin in wrought gold", "LAPDOG", PGE)
check("a piece goes into the container arm beside the anagram",
      used == ["poolGap"] and new["parts"][1]["op"] == "charade" and [p["words"] for p in new["parts"][0]["parts"]] == ["gold"])

# apply's landed(): the model's poolGap tree is mended before the redo gate judges it
import apply_annotations as AA
pg_entry = {"clue": {"text": "Unusual thing to have bloke close to union at?"}, "solution": "HENNIGHT"}
pg_new = AA.repair_pool_gap({"wordplay": pge}, pg_entry)
check("repair_pool_gap returns a tree (mended or as given) without raising", isinstance(pg_new.get("wordplay"), dict))
check("repair_pool_gap leaves a non-tree alone", AA.repair_pool_gap({"x": 1}, pg_entry) == {"x": 1})
# ...and a bare op whose indicator the model hung on the charade is mended before the first check
ub_wp = {"op": "charade", "indicators": [{"text": "guards", "at": 21}], "parts": [
    {"words": "Detective", "gives": "DET", "at": 0},
    {"op": "container", "parts": [{"words": "and", "gives": "PLUS", "at": 10}, {"words": "caught", "gives": "C", "at": 14}]}]}
ub_new = AA.repair_pool_gap({"wordplay": ub_wp}, {"clue": {"text": "Detective and caught guards going to pieces"},
                                              "solution": "DETPCLUS"})
check("repair_pool_gap moves a charade's word to the bare container (no noIndicator failure)",
      ub_new["wordplay"]["parts"][1]["indicators"][0]["text"] == "guards" and "indicators" not in ub_new["wordplay"])

# tidy_wordplay_shapes.write_allowances: only the puzzles a run touched move, and only down
import json
import pathlib
import tempfile
import tidy_wordplay_shapes as T
bl = pathlib.Path(tempfile.mkdtemp()) / "annotation_backlog.json"
bl.write_text(json.dumps({"_why": "x", "wrongRole": {"a-1": 5, "a-2": 3, "a-3": 2}}))
saved = T.V.BACKLOG_PATH
T.V.BACKLOG_PATH = bl
try:
    # a stale run saw 0 for a-2 and a-3 and 9 for a-1; only a-1 and a-3 were touched
    T.write_allowances({"wrongRole": {"a-1": 9}}, {"a-1", "a-3"})
finally:
    T.V.BACKLOG_PATH = saved
got = json.loads(bl.read_text())["wrongRole"]
check("a touched puzzle's allowance never rises, a cleared one is dropped, an untouched one stays",
      got == {"a-1": 5, "a-2": 3})

# deletionInside: del(charade(a, b), x) with x from ONE piece moves into that piece
DI = {"deletionInside": F.r_deletion_inside}
dic = "Italian group of workers all but bare"
di = {"op": "deletion", "indicators": [{"text": "all but"}], "parts": [
    {"op": "charade", "parts": [{"words": "group of workers", "gives": "TU"}, {"words": "bare", "gives": "SCANT"}]},
    {"gives": "T"}]}
new, used = F.repair_tree(di, dic, "TUSCAN", DI)
check("del over TU+SCANT less T becomes TU + del(SCANT, T), the indicator with the deletion",
      used == ["deletionInside"] and new["op"] == "charade" and new["parts"][1]["op"] == "deletion"
      and new["parts"][1]["parts"][0]["gives"] == "SCANT" and new["parts"][1]["indicators"][0]["text"] == "all but")
dw = {"op": "deletion", "indicators": [{"text": "throwing"}], "parts": [
    {"op": "charade", "parts": [{"words": "initially", "gives": "FIST"}, {"words": "couple of rights", "gives": "RR"}]},
    {"gives": "RR"}]}
new, used = F.repair_tree(dw, "Throwing couple of rights, initially fear", "FIST", DI)
check("a cut that is a whole added piece is left for the model", used == [])

# delOnePiece: del(charade(MELODY, RAM), Y) cuts the one piece holding the letters
NSO = {"nestedSameOp": F.r_nested_same_op}
nso = {"op": "deletion", "indicators": [{"text": "left by"}], "parts": [
    {"op": "deletion", "parts": [{"words": "loo", "gives": "LATRINE"}, {"words": "King", "gives": "R"}]},
    {"words": "Earl", "gives": "E"}]}
new, used = F.repair_tree(nso, "Language seen in loo left by King and Earl", "LATIN", NSO)
check("del(del(X, a), b) with one indicator becomes del<ind>(X, a, b)",
      used == ["nestedSameOp"] and new["op"] == "deletion" and len(new["parts"]) == 3
      and new["indicators"][0]["text"] == "left by" and "op" not in new["parts"][0])
nso2 = {"op": "container", "indicators": [{"text": "in"}], "parts": [
    {"op": "container", "parts": [{"words": "a", "gives": "A"}, {"words": "b", "gives": "B"}]},
    {"words": "c", "gives": "C"}]}
check("a nested container has no unique flat form", F.repair_tree(nso2, "a b in c", "ABCA", NSO)[1] == [])

RSL = {"repeatedSelection": F.r_repeated_selection}
rsl_clue = "Leading Tea Eats Rice"
rsl = F.W.parse("(first<Leading>([Tea]) + first<Leading>([Eats]) + first<Leading>([Rice]))", rsl_clue)
new, used = F.repair_tree(rsl, rsl_clue, "TER", RSL)
check("a pick written word by word becomes one pick over the words",
      used == ["repeatedSelection"] and new["op"] == "first" and new["parts"][0]["words"] == "Tea Eats Rice"
      and not V.repeated_selections(new))
rsl2 = F.W.parse("(first<Leading>([Tea]) + first<Leading>([Rice]))", "Leading Tea, Eats Rice")
check("words with others between them are left for the model",
      F.repair_tree(rsl2, "Leading Tea, Eats Rice", "TR", RSL)[1] == [])

DWC = {"delWrapsCharade": F.r_del_wraps_charade}
dwc = {"op": "reversal", "indicators": [{"text": "backing"}], "parts": [{"op": "deletion", "indicators": [{"text": "Manx"}], "parts": [
    {"op": "charade", "parts": [{"words": "vermin", "gives": "RATS"}, {"words": "concerning", "gives": "RE"},
                                {"words": "cat", "gives": "PUSS"}]}, {"gives": "S"}]}]}
new, used = F.repair_tree(dwc, "Legend backing vermin concerning Manx cat", "SUPERSTAR", DWC)
check("del<Manx> over RATS+RE+PUSS cuts PUSS, the piece beside it",
      used == ["delWrapsCharade"] and new["parts"][0]["op"] == "charade"
      and new["parts"][0]["parts"][2]["op"] == "deletion" and new["parts"][0]["parts"][2]["indicators"][0]["text"] == "Manx")
dwc2 = {"op": "deletion", "indicators": [{"text": "caught"}], "parts": [
    {"op": "charade", "parts": [{"words": "vacation", "gives": "LEAVE"}, {"words": "stinging creature", "gives": "BEE"}]},
    {"gives": "E"}]}
check("a cut that lies in two pieces beside the indicator is left for the model",
      F.repair_tree(dwc2, "stinging creature caught vacation", "LEAVEBE", DWC)[1] == [])

DOP = {"delOnePiece": F.r_del_one_piece}
dop = {"op": "deletion", "indicators": [{"text": "no end of"}], "parts": [
    {"op": "charade", "parts": [{"words": "tune", "gives": "MELODY"}, {"words": "ram", "gives": "RAM"}]},
    {"gives": "Y"}]}
new, used = F.repair_tree(dop, "Tune ram, no end of", "MELODRAM", DOP)
check("del over MELODY+RAM less Y becomes del(MELODY, Y) + RAM",
      used == ["delOnePiece"] and new["op"] == "charade" and new["parts"][0]["op"] == "deletion"
      and new["parts"][0]["indicators"][0]["text"] == "no end of" and new["parts"][1]["gives"] == "RAM")

# deletionScope: the same move; an end word picks the piece whose end holds the letters, an anagram flattens
DS = {"deletionScope": F.r_deletion_inside}
ds = {"op": "deletion", "indicators": [{"text": "Almost"}], "parts": [
    {"op": "charade", "parts": [{"words": "sorry", "gives": "SADE"}, {"words": "cheat", "gives": "CE"}]},
    {"gives": "E"}]}
new, used = F.repair_tree(ds, "Almost sorry cheat", "SADCE", DS)
check("an end word with the letter in two pieces moves the cut into the piece it ends",
      used == ["deletionScope"] and new["parts"][0]["op"] == "deletion" and new["parts"][1]["gives"] == "CE")
dan = {"op": "anagram", "indicators": [{"text": "upset"}], "parts": [{"op": "deletion", "indicators": [{"text": "Almost"}], "parts": [
    {"op": "charade", "parts": [{"words": "sorry", "gives": "SORRY"}, {"words": "cheat", "gives": "CHEAT"}]},
    {"gives": "Y"}]}]}
new, used = F.repair_tree(dan, "Almost sorry cheat upset group of players", "ORCHESTRA", DS)
check("under an anagram the charade is flattened into the anagram's parts",
      used == ["deletionScope"] and [p.get("op") for p in new["parts"]] == ["deletion", None])

# unindicatedBare: a word filed on a charade moves to the bare op it signals; a spare clue word is attached
UB = {"unindicatedBare": F.r_unindicated_move}
ubc = "Detective and caught guards going to pieces"
ub = {"op": "charade", "indicators": [{"text": "guards"}], "parts": [
    {"words": "Detective", "gives": "DET"},
    {"op": "container", "parts": [{"words": "and", "gives": "PLUS"}, {"words": "caught", "gives": "C"}]}]}
new, used = F.repair_tree(ub, ubc, "DETPCLUS", UB)
check("a container word hung on the charade moves to the bare container",
      used == ["unindicatedBare"] and "indicators" not in new and new["parts"][1]["indicators"][0]["text"] == "guards")
US = {"unindicatedBare": F.r_unindicated_spare}
ubs = "Detective and caught hosting mate"
us = {"op": "charade", "parts": [{"words": "Detective", "gives": "DET"},
      {"op": "container", "parts": [{"words": "and", "gives": "PLUS"}, {"words": "caught", "gives": "C"}]}]}
new, used = F.repair_tree(us, ubs, "DETPCLUS", US)
check("a bare container takes the unused container word beside its pieces",
      used == [] or new["parts"][1]["indicators"][0]["text"] == "hosting")

# r_hidden_link: a bare hid() takes the unused link word right before its leaf
HL = {"unindicatedBare": F.r_hidden_link}
hl = {"op": "reversal", "indicators": [{"text": "wheels"}], "parts": [
    {"op": "hidden", "parts": [{"words": "delivery truck", "gives": "ERYT"}]}]}
new, used = F.repair_tree(hl, "Covering for wheels, wheels in delivery truck", "TYRE", HL)
check("a bare hidden word takes the 'in' before its leaf",
      used == ["unindicatedBare"] and new["parts"][0]["indicators"][0]["text"] == "in")

# del_single: a deletion over a composite whose letters come out of one literal leaf filed already cut
D1 = {"del_single": F.r_del_single}
d1 = {"op": "deletion", "unchecked": True, "indicators": [{"text": "endless"}], "parts": [
    {"op": "charade", "parts": [{"words": "Graduate's", "gives": "BAS"}, {"words": "mum", "gives": "MA"},
                                {"words": "Tim", "gives": "TI"}]}]}
new, used = F.repair_tree(d1, "Graduate's mum endless Tim", "BASMATI", D1)
check("a cut leaf filed short moves the deletion onto it and the wrapper goes",
      used == ["del_single"] and new["op"] == "charade" and new["parts"][2]["op"] == "deletion"
      and new["parts"][2]["parts"][0]["gives"] == "TIM" and new["parts"][2]["parts"][1]["gives"] == "M")
d2 = {"op": "deletion", "unchecked": True, "indicators": [{"text": "Short"}], "parts": [
    {"op": "charade", "parts": [{"words": "talk", "gives": "RABBI"}, {"words": "x", "gives": "CAL"}]}]}
new, used = F.repair_tree(d2, "Short talk x", "RABBICAL", D1)
check("a synonym filed short takes the whole word the usage table attests (talk > RABBIT)",
      used == ["del_single"] and new["op"] == "charade" and new["parts"][0]["op"] == "deletion"
      and new["parts"][0]["parts"][0]["gives"] == "RABBIT" and new["parts"][0]["parts"][1]["gives"] == "T")
d3 = {"op": "deletion", "unchecked": True, "indicators": [{"text": "Short"}], "parts": [
    {"op": "charade", "parts": [{"words": "zzqx", "gives": "RABBI"}, {"words": "x", "gives": "CAL"}]}]}
new, used = F.repair_tree(d3, "Short zzqx x", "RABBICAL", D1)
check("a synonym nothing attests is left for the model", used == [])

# anaSynonym: a synonym scrambled with the fodder is charaded on; only the fodder is anagrammed
AS = {"anaSynonym": F.r_ana_synonym_charade}
asn = {"op": "anagram", "indicators": [{"text": "Somehow"}], "parts": [{"words": "warn"}, {"words": "Harry", "gives": "HAL"}]}
new, used = F.repair_tree(asn, "Somehow warn Harry", "NARWHAL", AS)
check("ana(warn, Harry=HAL) becomes ana(warn) + HAL",
      used == ["anaSynonym"] and new["op"] == "charade" and new["parts"][0]["op"] == "anagram"
      and len(new["parts"][0]["parts"]) == 1 and new["parts"][1]["gives"] == "HAL")
asp = {"op": "anagram", "indicators": [{"text": "wrong"}], "parts": {"op": "charade", "parts": [
    {"words": "In"}, {"words": "stalked", "gives": "TROD"}, {"words": "cue"}]}}
asp["parts"] = [asp["parts"]]
new, used = F.repair_tree(asp, "In stalked on wrong cue", "INTRODUCE", AS)
check("only the word the indicator reaches is scrambled; the others stay literal",
      used == ["anaSynonym"] and [p.get("op") for p in new["parts"]] == [None, None, "anagram"])
asx = {"op": "anagram", "indicators": [{"text": "Somehow"}], "parts": [{"words": "warn"}, {"words": "Harry", "gives": "HAL"}]}
new, used = F.repair_tree(asx, "Somehow warn Harry", "LANWHAR", AS)
check("a tree that cannot reach the answer is left alone", used == [])

# unindicatedBare, widened: a swap through a charade (the charade's word goes to the op that needs it, that op's
# unknown word to the bare op beside it) and a first/last head word the lexicon lists
swc = "Awkward, grand and long initially uncle's hosted"
swt = {"op": "charade", "indicators": [{"text": "initially", "at": 24}], "parts": [
    {"op": "first", "indicators": [{"text": "hosted", "at": 42}], "parts": [{"words": "grand", "at": 9, "gives": "G"}]},
    {"op": "container", "parts": [{"words": "long", "at": 19, "gives": "ACHE"}, {"words": "uncle's", "at": 34, "gives": "U"}]}]}
new, used = F.repair_tree(swt, swc, "GACHEU", UB)
check("a charade's word and a mismatched word swap into place by elimination",
      used == ["unindicatedBare"] and "indicators" not in new
      and new["parts"][0]["indicators"][0]["text"] == "initially"
      and new["parts"][1]["indicators"][0]["text"] == "hosted")

# indInLeaf: a leaf that took an indicator's words as well loses them
IL = {"indInLeaf": F.r_ind_in_leaf}
il = {"op": "container", "indicators": [{"text": "End of"}], "parts": [
    {"words": "thread", "gives": "YARN"}, {"op": "last", "indicators": [{"text": "about"}], "parts": [{"words": "End of Empire"}]}]}
new, used = F.repair_tree(il, "Long thread about End of Empire", "YEARN", IL)
check("an indicator's words come off the edge of the leaf that held them too",
      used == ["indInLeaf"] and new["parts"][1]["parts"][0]["words"] == "Empire")

# nestedContainer under a reversal: the pair is judged against the whole tree, not the answer alone
NC = {"nestedContainer": F.r_nested_container}
ncc = "Fellow holding a fit of pique back"
nct = {"op": "reversal", "indicators": [{"text": "back"}], "parts": [
    {"op": "container", "indicators": [{"text": "holding"}], "parts": [
        {"op": "container", "parts": [{"words": "Fellow", "gives": "DON"}, {"words": "a", "gives": "A"}]},
        {"words": "fit of pique", "gives": "PET"}]}]}
new, used = F.repair_tree(nct, ncc, "NOTEPAD", NC)
check("a container pair under a reversal joins into one charade",
      used == ["nestedContainer"] and new["parts"][0]["parts"][1]["op"] == "charade")

# misplacedIndicator: a charade's word moves to the op it signals, swapping with a word fine on a charade
MP = {"misplacedIndicator": F.r_misplaced_indicator}
mpc = "Whale question in exam right at the start"
mpt = {"op": "charade", "indicators": [{"text": "in", "at": 18}], "parts": [
    {"words": "right", "at": 28, "gives": "R"},
    {"op": "container", "indicators": [{"text": "at the start", "at": 34}], "parts": [
        {"words": "exam", "at": 21, "gives": "ORAL"}, {"words": "question", "at": 6, "gives": "QU"}]}]}
new, used = F.repair_tree(mpt, mpc, "RORQUAL", MP)
check("in goes to the container, at the start stays with the charade",
      used == ["misplacedIndicator"] and new["indicators"][0]["text"] == "at the start"
      and new["parts"][1]["indicators"][0]["text"] == "in")
mpt3 = {"op": "charade", "indicators": [{"text": "in", "at": 18}, {"text": "then", "at": 34}], "parts": [
    {"words": "right", "at": 28, "gives": "R"},
    {"op": "container", "parts": [
        {"words": "exam", "at": 21, "gives": "ORAL"}, {"words": "question", "at": 6, "gives": "QU"}]}]}
new, used = F.repair_tree(mpt3, mpc, "RORQUAL", MP)
check("a charade with a second, sound indicator still gives the misplaced word to the container",
      used == ["misplacedIndicator"] and [i["text"] for i in new["indicators"]] == ["then"]
      and new["parts"][1]["indicators"][0]["text"] == "in")
mpc2 = "Drink taken by donkey leader"
mpt2 = {"op": "charade", "indicators": [{"text": "leader", "at": 22}], "parts": [
    {"words": "Drink", "at": 0, "gives": "TOT"}, {"words": "donkey", "at": 15, "gives": "D"}]}
new, used = F.repair_tree(mpt2, mpc2, "TOTD", MP)
check("a one-letter leaf under the charade's pick word is wrapped in first", used == ["misplacedIndicator"]
      and new["parts"][1]["op"] == "first")

# sharedIndicator, charade: the charade's word is also a leaf's words, so the charade drops it
shc = "Notice following raised charges"
sht = {"op": "charade", "indicators": [{"text": "following", "at": 7}], "parts": [
    {"words": "following", "at": 7, "gives": "F"},
    {"op": "reversal", "indicators": [{"text": "raised", "at": 17}], "parts": [{"words": "Notice", "at": 0, "gives": "SEE"}]}]}
new, used = F.repair_tree(sht, shc, "FEES", {"sharedIndicator": F.r_shared_charade})
check("a charade indicator that is a leaf's words is dropped", used == ["sharedIndicator"] and "indicators" not in new)

# arity_ins: an unchecked container over one anagram / charade of the held and the holder is split
AI = {"arity_ins": F.r_arity_ins}
aic = "Drink now mixed in separate container"
ait = {"op": "container", "unchecked": True, "indicators": [{"text": "in", "at": 16}], "parts": [
    {"op": "anagram", "indicators": [{"text": "mixed", "at": 9}], "parts": [
        {"words": "separate", "at": 19, "gives": "SUND"}, {"words": "now", "at": 6}, {"words": "separate", "at": 19, "gives": "ER"}]}]}
new, used = F.repair_tree(ait, aic, "SUNDOWNER", AI)
check("an anagram of the held among the holder's pieces makes a two-part container",
      used == ["arity_ins"] and len(new["parts"]) == 2 and not new.get("unchecked"))
aic2 = "Very small car carrying case of old alcohol"
ait2 = {"op": "container", "unchecked": True, "parts": [{"op": "charade", "indicators": [{"text": "carrying", "at": 15}], "parts": [
    {"words": "Very", "at": 0, "gives": "V"}, {"op": "outer", "indicators": [{"text": "case of", "at": 24}], "parts": [{"words": "old", "at": 32, "gives": "OD"}]},
    {"words": "small car", "at": 5, "gives": "KA"}]}]}
new, used = F.repair_tree(ait2, aic2, "VODKA", AI)
check("a charade of held and holder splits, its indicator moving to the container",
      used == ["arity_ins"] and len(new["parts"]) == 2 and new["indicators"][0]["text"] == "carrying")

# removed_leaf: the deleted word sits in the charade with no letters; the cut is shown
RL = {"unchecked_leaf": F.r_removed_leaf}
rlc = "Safe king avoids appearance in massacre"
rlt = {"op": "deletion", "unchecked": True, "gives": "PETERLOO", "indicators": [{"text": "avoids", "at": 10}], "parts": [
    {"op": "charade", "parts": [leaf("Safe", "PETER"), {**leaf("appearance", "LOO"), "note": "look, minus the K"},
                                {"unchecked": True, "words": "king", "at": 5}]}]}
new, used = F.repair_tree(rlt, rlc, "PETERLOO", RL)
check("a letterless removed leaf gets its letters, the cut word its full spelling",
      used == ["unchecked_leaf"] and "LOOK" in json.dumps(new) and "unchecked" not in json.dumps(new))
check("the unchecked_leaf detector counts the old tree and not the new",
      F._DETECTOR_RULES["unchecked_leaf"](rlt, {"wordplay": rlt, "_answer": "PETERLOO"}, rlc)
      and not F._DETECTOR_RULES["unchecked_leaf"](new, {"wordplay": new, "_answer": "PETERLOO"}, rlc))

# literal_fodder: an anagram filed with its fodder's results is the clue's own words scrambled
lfc = "Paint half of them in striped materials"
lft = {"op": "anagram", "unchecked": True, "gives": "DISTEMPER", "indicators": [{"text": "materials", "at": 31}], "parts": [
    {"op": "container", "indicators": [{"text": "in"}], "parts": [
        {"words": "striped", "gives": "STRIPED"}, {"op": "last", "unchecked": True, "gives": "EM", "indicators": [{"text": "half of"}], "parts": [
            {"unchecked": True, "words": "them", "gives": "EM", "select": "last"}]}]}]}
new, used = F.repair_tree(lft, lfc, "DISTEMPER", {"unchecked_step": F.r_literal_fodder})
check("an unchecked anagram over results becomes a checked one over the clue words",
      used == ["unchecked_step"] and "unchecked" not in json.dumps(new) and "EM" not in json.dumps(new))

# arity_other: a 4-part substitution is the three it takes plus a leftover charade piece; a
# container over a many-part cycling splits the pieces into holder and held
AO = {"arity_other": F.r_arity_other}
aoc = "Quiet Rev's partner for hard drink"
aot = {"op": "substitution", "unchecked": True, "indicators": [{"text": "for", "at": 20}], "parts": [
    {"words": "Keen", "at": 0, "gives": "SHREWD"}, {"words": "hard", "at": 24, "gives": "H"},
    {"words": "about", "at": 8, "gives": "C"}, {"words": "running water", "at": 30, "gives": "RIVER"}]}
new, used = F.repair_tree(aot, aoc, "SCREWDRIVER", AO)
check("a 4-part sub becomes a 3-part sub beside the leftover piece",
      used == ["arity_other"] and new["op"] == "charade" and len(new["parts"][0]["parts"]) == 3
      and "unchecked" not in json.dumps(new))
new, used = F.repair_tree(aot, aoc, "SCREWDRIVERX", AO)
check("a reading that misses the answer is left alone", used == [] and new.get("unchecked"))
aoc2 = "Dance, lifting bottom in mock revelation"
aot2 = {"op": "container", "unchecked": True, "indicators": [{"text": "in", "at": 22}], "parts": [
    {"op": "cycling", "unchecked": True, "indicators": [{"text": "lifting bottom", "at": 7}], "parts": [
        {"words": "Dance", "at": 0, "gives": "CALYPSO"}, {"words": "mock", "at": 25, "gives": "APE"}]}]}
new, used = F.repair_tree(aot2, aoc2, "APOCALYPSE", AO)
check("a container over a many-part cycling holds the cycled piece in the other",
      used == ["arity_other"] and [p.get("gives") for p in new["parts"]][0] == "APE"
      and new["parts"][1]["op"] == "cycling" and "unchecked" not in json.dumps(new))

# deletionScopeAnswer: the cut names an end of one piece, not of the whole charade
dsc = "Almost certain aspect will be lacking depth"
dst = {"op": "deletion", "indicators": [{"text": "Almost", "at": 0}], "parts": [
    {"op": "charade", "parts": [{"words": "certain", "at": 7, "gives": "SURE"}, {"words": "aspect", "at": 15, "gives": "FACE"}]},
    {"gives": "E"}]}
new, used = F.repair_tree(dst, dsc, "SURFACE", {"deletionScopeAnswer": F.RULE_REPAIRS["deletionScopeAnswer"]})
check("a deletion over a charade moves onto the piece the cut comes out of",
      used == ["deletionScopeAnswer"] and new["op"] == "charade" and new["parts"][0]["op"] == "deletion")

# anagramOfContainer: ana(ins(a, b)) over literal words is one anagram of them together; over one
# arm it is ins(ana(arm), other) with the anagram's word taken off the container
AC = {"anagramOfContainer": F.r_ana_of_container}
acc = "Ship off clothes tried out where culture's displayed"
act = {"op": "anagram", "indicators": [{"text": "off", "at": 5}, {"text": "out", "at": 25}], "parts": [
    {"op": "container", "indicators": [{"text": "clothes", "at": 9}], "parts": [
        {"words": "Ship", "at": 0}, {"words": "tried", "at": 17}]}]}
new, used = F.repair_tree(act, acc, "PETRIDISH", AC)
check("a literal-word anagram of a container is a plain anagram of the words",
      used == ["anagramOfContainer"] and new["op"] == "anagram" and len(new["parts"]) == 2)
acc3 = "Novel she wrote about one being different"
act3 = {"op": "anagram", "parts": [{"op": "container", "indicators": [{"text": "Novel", "at": 0}, {"text": "about", "at": 15}], "parts": [
    {"words": "she wrote", "at": 6}, {"words": "one", "at": 21, "gives": "I"}]}]}
new, used = F.repair_tree(act3, acc3, "OTHERWISE", AC)
check("a container's two words: the anagram word goes to the anagram",
      used == ["anagramOfContainer"] and new["op"] == "container" and [i["text"] for i in new["indicators"]] == ["about"]
      and new["parts"][0]["op"] == "anagram" and new["parts"][0]["indicators"][0]["text"] == "Novel")

# halfLeaf: the "half" word sits on the op beside the leaf that gives half its word; it moves onto
# a first/last pick over that leaf, and a deletion that was nothing else goes
HL = {"halfLeaf": F.r_half_leaf}
hlc = "Spread pate, leaving half in tin"
hlt = {"op": "deletion", "indicators": [{"text": "leaving half", "at": 13}], "parts": [
    {"op": "container", "indicators": [{"text": "in", "at": 27}], "parts": [
        {"words": "tin", "at": 30, "gives": "SN"}, {"words": "pate", "at": 7, "gives": "PA"}]}]}
new, used = F.repair_tree(hlt, hlc, "SPAN", HL)
check("del<half>(ins(SN, PA)) becomes ins(SN, first<half>(pate))",
      used == ["halfLeaf"] and new["op"] == "container" and new["parts"][1]["op"] == "first"
      and new["parts"][1]["indicators"][0]["text"] == "leaving half" and "gives" not in new["parts"][1]["parts"][0])
new, used = F.repair_tree(hlt, hlc, "SPANX", HL)
check("a tree that does not give the answer is left alone", used == [] and new["op"] == "deletion")

# halvedAsDeletion: del<half of>(WORD, other half) is first/last<half of>(WORD)
HD = {"halvedAsDeletion": F.r_halved_deletion}
hdc = "Hinder half of solution"
hdt = {"op": "charade", "parts": [{"words": "Hinder", "at": 0, "gives": "BALK"}, {"op": "deletion", "indicators": [{"text": "half of", "at": 7}], "parts": [
    {"words": "solution", "at": 15, "gives": "ANSWER"}, {"gives": "WER"}]}]}
new, used = F.repair_tree(hdt, hdc, "BALKANS", HD)
check("del<half of>(ANSWER, WER) becomes first<half of>(solution)",
      used == ["halvedAsDeletion"] and new["parts"][1]["op"] == "first" and new["parts"][1]["parts"][0]["gives"] == "ANSWER")
new, used = F.repair_tree(hdt, hdc, "BALKANSX", HD)
check("halvedAsDeletion: a tree that does not give the answer is left alone", used == [])

# anaCharade: the fodder pieces already spell the answer; the piece that is the scramble of its own
# words is the real fodder, the rest are charade pieces
ACH = {"anaCharade": F.r_ana_charade}
acc = "Light pates upset queen"
act = {"op": "anagram", "unchecked": True, "gives": "TAPER", "indicators": [{"text": "upset", "at": 12}], "parts": [
    {"op": "charade", "parts": [{"words": "pates", "at": 6, "gives": "TAPE"}, {"words": "queen", "at": 18, "gives": "R"}]}]}
new, used = F.repair_tree(act, acc, "TAPER", ACH)
check("TAPE from pates + R: the anagram is over pates alone, the queen beside it",
      used == ["anaCharade"] and new["op"] == "charade" and new["parts"][0]["op"] == "anagram"
      and new["parts"][0]["parts"][0]["words"] == "pates" and new["parts"][1]["gives"] == "R")
act2 = {**act, "parts": [{"op": "charade", "parts": [{"words": "pates", "at": 6, "gives": "TAPX"}, {"words": "queen", "at": 18, "gives": "R"}]}]}
new, used = F.repair_tree(act2, acc, "TAPXR", ACH)
check("a piece that is no scramble of its words is left for the model", used == [])

# anaCharade, pulled out (Paul 10-19): a piece the answer starts or ends with stands outside the anagram
AP = {"anaCharade": F.r_ana_pull}
apc = "Fellow troubled by fire, a sorrow"
apt = {"op": "anagram", "indicators": [{"text": "troubled", "at": 7}], "parts": [
    {"op": "charade", "parts": [{"words": "Fellow", "at": 0, "gives": "G"}, {"words": "fire", "at": 20}]}]}
new, used = F.repair_tree(apt, apc, "GRIEF", AP)
check("ana(G + FIRE) = GRIEF is G then ana(FIRE)",
      used == ["anaCharade"] and new["op"] == "charade" and new["parts"][0]["gives"] == "G"
      and new["parts"][1]["op"] == "anagram" and new["parts"][1]["parts"][0]["words"] == "fire"
      and new["parts"][1]["indicators"][0]["text"] == "troubled")
apt2 = {**apt, "parts": [{"op": "charade", "parts": [{"words": "fire", "at": 20}, {"words": "Fellow", "at": 0, "gives": "R"}]}]}
new, used = F.repair_tree(apt2, apc, "FIRERX", AP)
check("neither end spelling the answer leaves the clue for the model", used == [])
new, used = F.repair_tree(apt2, apc, "RIFER", AP)
check("a trailing piece goes after the anagram", used == ["anaCharade"] and new["parts"][1].get("gives") == "R"
      and new["parts"][0]["op"] == "anagram")

# anaCharade, any depth (r24): quiptic-1157#15a, N folded into the anagram beside I
aec = "Setter's new and unusual RIP sign is thought-provoking"
aet = {"op": "charade", "parts": [{"words": "Setter's", "at": 0, "gives": "I"}, {"op": "anagram", "indicators": [{"text": "unusual", "at": 18}], "parts": [
    {"words": "new", "at": 9, "gives": "N"}, {"words": "RIP sign", "at": 26}]}]}
new, used = F.repair_tree(aet, aec, "INSPIRING", {"anaCharade": F.r_ana_edge})
check("N comes out of the anagram, joined into the charade: I + N + ana(RIP sign)",
      used == ["anaCharade"] and [p.get("gives") or p["op"] for p in new["parts"]] == ["I", "N", "anagram"]
      and new["parts"][2]["parts"][0]["words"] == "RIP sign")
check("the validator counts it before and not after", V.anagram_charades(aet, "INSPIRING") == 1 and V.anagram_charades(new, "INSPIRING") == 0)

# scrambledLeaf: the anagram word sits over the synonym while the scrambled result sits on the other leaf
SW = {"scrambledLeaf": F.r_scrambled_swap}
swc = "Celebration over treaty drafted in Pennsylvania"
swt = {"op": "container", "indicators": [{"text": "in", "at": 35}], "parts": [
    {"words": "treaty", "at": 17, "gives": "TEARTY"},
    {"op": "anagram", "indicators": [{"text": "drafted", "at": 24}], "parts": [{"words": "Pennsylvania", "at": 38, "gives": "PA"}]}]}
new, used = F.repair_tree(swt, swc, "TEAPARTY", SW)
check("the anagram moves onto the scrambled leaf and the synonym stands bare",
      used == ["scrambledLeaf"] and new["parts"][0]["op"] == "anagram" and "gives" not in new["parts"][0]["parts"][0]
      and new["parts"][1].get("gives") == "PA")
new, used = F.repair_tree(swt, swc, "TEAPARTX", SW)
check("a swap that does not give the answer is left alone", used == [])

# reversalSplit: the reversal's indicator stands between its pieces; it reverses the one beside it
rsc = "East to west, head for German city"
rst = {"op": "reversal", "indicators": [{"text": "to west", "at": 5}], "parts": [{"op": "charade", "parts": [
    {"words": "head", "at": 14, "gives": "NESS"}, {"words": "East", "at": 0, "gives": "E"}]}]}
new, used = F.repair_tree(rst, rsc, "ESSEN", {"reversalSplit": F.r_reversal_split})
check("only the piece beside the indicator is reversed: E + rev(NESS)",
      used == ["reversalSplit"] and new["op"] == "charade" and new["parts"][0].get("gives") == "E"
      and new["parts"][1]["op"] == "reversal")
new, used = F.repair_tree(rst, rsc, "ESSEX", {"reversalSplit": F.r_reversal_split})
check("no piece reversal gives the answer: left alone", used == [])

# half_cut (round 15):"not half" over DARING less ING is the first half of DARING (SIRDAR)
hc = "Military commander given title of respect, bold, not half!"
hct = {"op": "charade", "parts": [{"words": "title of respect", "gives": "SIR"}, {"op": "deletion", "indicators": [{"text": "not half"}], "parts": [
    {"words": "bold", "gives": "DARING"}, {"gives": "ING"}]}]}
new, used = F.repair_tree(hct, hc, "SIRDAR", {"half_cut": F.r_half_cut})
check("a deletion of exactly half under 'not half' becomes first over the word",
      used == ["half_cut"] and new["parts"][1]["op"] == "first" and new["parts"][1]["indicators"][0]["text"] == "not half")
hct2 = {**hct, "parts": [hct["parts"][0], {**hct["parts"][1], "parts": [{"words": "bold", "gives": "DARING"}, {"gives": "NG"}]}]}
new, used = F.repair_tree(hct2, hc, "SIRDARI", {"half_cut": F.r_half_cut})
check("a cut that is not half is left alone", used == [])

# moved_letter: the letter taken out and put back by a sibling is one move
mlc = "Eastern sea creature shedding tail in spring"
mlt = {"op": "charade", "parts": [{"words": "Eastern", "at": 0, "gives": "E"}, {"op": "deletion", "indicators": [{"text": "shedding tail", "at": 21}], "parts": [
    {"words": "sea creature", "at": 8, "gives": "MANATEE"}, {"gives": "E"}]}]}
new, used = F.repair_tree(mlt, mlc, "EMANATE", {"movedLetter": F.r_moved_letter})
check("del(WORD, E) beside a leaf E becomes move(WORD, E)",
      used == ["movedLetter"] and new["op"] == "move" and new["parts"][1].get("words") == "Eastern")
new, used = F.repair_tree(mlt, mlc, "EMANATES", {"movedLetter": F.r_moved_letter})
check("a move that does not give the answer is left alone", used == [])
mlc2 = "Short month in which temperature rises a degree"
mlt2 = {"op": "container", "indicators": [{"text": "rises", "at": 35}], "parts": [{"op": "deletion", "parts": [
    {"words": "Short month", "at": 0, "gives": "SEPT"}, {"gives": "T"}]}, {"words": "temperature", "at": 23, "gives": "T"}]}
new, used = F.repair_tree(mlt2, mlc2, "STEP", {"movedLetter": F.r_moved_letter})
check("container indicator goes onto the move", used == ["movedLetter"] and new["op"] == "move"
      and new["indicators"][0]["text"] == "rises")
# cutNoteLeaf: a leaf holding the cut's indicator and giving the word short becomes a deletion
CN = {"cutNoteLeaf": F.r_cut_note_leaf}
cnc = "Toughest ordeal after unfinished beer"
cnt = {"op": "charade", "indicators": [{"text": "after", "at": 17}], "parts": [
    {"words": "unfinished beer", "at": 23, "gives": "STOU", "note": "STOUT without its final T"},
    {"words": "ordeal", "at": 10, "gives": "TEST"}]}
new, used = F.repair_tree(cnt, cnc, "STOUTEST", CN)
check("'unfinished beer' giving STOU is del<unfinished>(beer STOUT, T)",
      used == ["cutNoteLeaf"] and new["parts"][0]["op"] == "deletion" and new["parts"][0]["parts"][0]["gives"] == "STOUT"
      and new["parts"][0]["parts"][0]["words"] == "beer" and new["parts"][0]["parts"][1]["gives"] == "T")
cnt2 = {"op": "charade", "parts": [
    {"words": "meal, ignoring large", "at": 0, "gives": "UNCH", "note": "LUNCH without L, the abbreviation for large"},
    {"words": "Rest", "at": 21, "gives": "RUM"}]}
new, used = F.repair_tree(cnt2, "meal, ignoring large Rest", "UNCHRUM", CN)
check("a letter named by a clue word is a part of its own: del<ignoring>(meal LUNCH, large L)",
      used == ["cutNoteLeaf"] and new["parts"][0]["parts"][1]["words"] == "large" and new["parts"][0]["parts"][1]["gives"] == "L")
new, used = F.repair_tree(cnt, cnc, "STOUTESX", CN)
check("cutNoteLeaf: a tree that does not give the answer is left alone", used == [])

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
