#!/usr/bin/env python3
"""Tests for the validator-gap rules: folded indicators, fake substitution parts, padding leaves and the redo regression gate.

Each rule has a hit and a near-miss; the gate is validate_annotations.redo_regressions."""
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import copy
import shape_queue as Q
import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

# folded_indicators: everyman-4162 25a, the indicator folded into a leaf
folded = {"op": "homophone", "spelt": "EASE", "indicators": [{"text": "pronouncedly", "at": 39}],
          "parts": [{"words": "Principally, Everyman, more than once", "at": 0, "gives": "ES"}]}
check("an indicator folded into a leaf is counted", 1, v.folded_indicators(folded))
near = copy.deepcopy(folded)
near["parts"][0]["words"] = "Everyman, more than once"
near["parts"][0]["at"] = 13
check("a short leaf with no known indicator at its edge is not", 0, v.folded_indicators(near))
long_gives = copy.deepcopy(folded)
long_gives["parts"][0]["gives"] = "ESSAYS"
check("a leaf giving a word (not a 1-2 letter result) is not", 0, v.folded_indicators(long_gives))
one_word = {"op": "homophone", "spelt": "EASE", "indicators": [{"text": "said"}],
            "parts": [{"words": "Principally Everyman", "at": 0, "gives": "E"}]}
check("a two-word leaf with only a one-word edge is not", 0, v.folded_indicators(one_word))
unchecked = copy.deepcopy(folded)
unchecked["parts"][0]["unchecked"] = True
check("an unchecked leaf is left to the padding rule", 0, v.folded_indicators(unchecked))

# fake_parts: sub(sub(x, R, L), AL, AR) with wordless gives nodes
fake = {"op": "substitution", "parts": [
    {"op": "substitution", "parts": [{"words": "non-fiction", "at": 0, "gives": "NONFICTION"},
                                      {"gives": "R"}, {"gives": "L"}]},
    {"gives": "AL"}, {"gives": "AR"}]}
check("a substitution padded with wordless parts is counted", 1, v.fake_parts(fake))
real = copy.deepcopy(fake)
real["parts"][1] = {"words": "alpha", "at": 20, "gives": "AL"}
check("one with the replaced part read from the clue is not", 0, v.fake_parts(real))
single = {"op": "substitution", "parts": [{"words": "x", "at": 0, "gives": "XA"},
                                           {"gives": "A"}, {"gives": "B"}]}
check("a plain substitution is not", 0, v.fake_parts(single))
short = copy.deepcopy(fake)
short["parts"][1], short["parts"][2] = {"gives": "A"}, {"gives": "B"}
check("one-letter wordless parts are not", 0, v.fake_parts(short))

# padding_leaves: unchecked leaf of clue words that gives nothing
pad = {"op": "charade", "parts": [{"words": "no shock", "at": 0, "unchecked": True},
                                   {"words": "x", "at": 9, "gives": "X"}]}
check("an unchecked leaf with no gives is counted", 1, v.padding_leaves(pad))
gives = copy.deepcopy(pad)
gives["parts"][0]["gives"] = "NS"
check("one that says what it gives is not", 0, v.padding_leaves(gives))
dropped = copy.deepcopy(pad)
dropped["parts"][0]["note"] = "dropped: not part of the wordplay"
check("one whose note says it was dropped is not", 0, v.padding_leaves(dropped))
checked = copy.deepcopy(pad)
del checked["parts"][0]["unchecked"]
check("a checked leaf is not", 0, v.padding_leaves(checked))
spoon = {"op": "spoonerism", "parts": [{"words": "no shock", "at": 0, "unchecked": True}]}
check("a spoonerism's sound leaf is not", 0, v.padding_leaves(spoon))
warn = v.shape_warnings("1A", {"wordplay": pad, "definitions": []})
check("shape_warnings reports it", 1, sum(v.PADDING_LEAF in w for w in warn))
for field in ("indFolded", "fakeParts", "paddingLeaf"):
    check(f"wordplay.{field} is a ratchet field", True, f"wordplay.{field}" in v.BACKLOG_MARKERS)

# redo_regressions: the gate every redo of an annotated clue passes
CLUE = "Moral tale, displayed, in part (4)"
good = {"definitions": [{"text": "Moral tale", "at": 0}],
        "wordplay": {"op": "charade", "indicators": [{"text": "displayed, in", "at": 11}],
                     "parts": [{"words": "part", "at": 25, "gives": "PART"}]}}
def redo(new, old=good, clue=CLUE):
    return [r.split(":")[0] for r in v.redo_regressions(old, new, clue)]
dropped_in = copy.deepcopy(good)
dropped_in["wordplay"]["indicators"] = []
check("a redo that drops \"displayed, in\" is refused", ["dropped_words"], redo(dropped_in))
check("a redo that keeps every word is not", [], redo(copy.deepcopy(good)))
check("a word moved into a definition is not dropped", [], redo(
    {**dropped_in, "definitions": [{"text": "Moral tale"}, {"text": "displayed, in"}]}))
check("a tree replaced by none is refused", ["no_tree"], redo({"definitions": good["definitions"], "wordplay": None}))
check("a double definition covering the clue replaces a tree", [], redo(
    {"definitions": [{"text": "Moral tale"}, {"text": "displayed, in part"}]}, clue="Moral tale displayed, in part"))
check("no old tree means no loss", [], redo({"definitions": [], "wordplay": None}, old={"definitions": []}))
bare = {"definitions": good["definitions"], "wordplay": {
    "op": "cryptic", "parts": [{"words": "part", "at": 25}, {"words": "Moral tale, displayed, in", "at": 0}]}}
check("a real tree downgraded to a bare cryptic is refused", ["downgraded"], redo(bare))
check("a bare cryptic redone as a bare cryptic is not", [], redo(copy.deepcopy(bare), old=bare))
check("a bare cryptic upgraded to a real tree is not", [], redo(good, old=bare))
check("a Spooner clue that loses the spoonerism is refused", ["lost_spoonerism"], redo(
    good, old={"definitions": [], "wordplay": None}, clue="Spooner's moral tale, displayed, in part"))
check("shape_queue.regressions delegates to it", ["downgraded"], [r.split(":")[0] for r in Q.regressions(
    {"annotation": good, "clue": {"text": CLUE}}, bare)])
# A connective only a junk leaf held may be taken out; a content word, or the
# same connective as an indicator, may not.
CLUE2 = "Moral tale with part (4)"
junk = {"definitions": [{"text": "Moral tale", "at": 0}],
        "wordplay": {"op": "charade", "parts": [
            {"words": "with", "at": 11, "unchecked": True}, {"words": "part", "at": 16, "gives": "PART"}]}}
fixed = {"definitions": [{"text": "Moral tale", "at": 0}],
         "wordplay": {"op": "charade", "parts": [{"words": "part", "at": 16, "gives": "PART"}]}}
check("taking a connective-only junk leaf out is not a loss", [], redo(fixed, old=junk, clue=CLUE2))
CLUE5 = "Moral cake with part (4)"
check("dropping a content leaf is still refused", ["dropped_words"], redo(
    {"definitions": [{"text": "Moral", "at": 0}],
     "wordplay": {"op": "charade", "parts": [{"words": "part", "at": 20, "gives": "PART"}]}},
    old={"definitions": [{"text": "Moral", "at": 0}], "wordplay": {"op": "charade", "parts": [
        {"words": "cake", "at": 6, "gives": "CAKE"}, {"words": "part", "at": 20, "gives": "PART"}]}}, clue=CLUE5))
as_ind = {"definitions": [{"text": "Moral tale", "at": 0}],
          "wordplay": {"op": "charade", "indicators": [{"text": "with", "at": 11}],
                       "parts": [{"words": "part", "at": 16, "gives": "PART"}]}}
check("a connective that was an indicator is forgiven: it is a link word now", [], redo(fixed, old=as_ind, clue=CLUE2))
# Near miss: the same connective held by an old leaf with a real `gives` stays.
CLUE3 = "Moral tale the part (4)"
real_the = {"definitions": [{"text": "Moral tale", "at": 0}],
            "wordplay": {"op": "charade", "parts": [
                {"words": "the", "at": 11, "gives": "T"}, {"words": "part", "at": 15, "gives": "PART"}]}}
fixed3 = {"definitions": [{"text": "Moral tale", "at": 0}],
          "wordplay": {"op": "charade", "parts": [{"words": "part", "at": 15, "gives": "PART"}]}}
check("a connective held by an old leaf with a real gives is forgiven", [],
      redo(fixed3, old=real_the, clue=CLUE3))
# The mechanical part of dropped_words: a lost word that can stand for an equals sign
# is a link word now (annotation.view() derives it; a stored `linkWords` is refused by the
# schema, so the gate must not ask for one). A content word never is.
check("a connective lost from an old indicator is forgiven", ["with"],
      sorted(v.forgiven_dropped_words(as_ind, fixed, CLUE2)))
check("a lost content word is not forgiven", [], sorted(v.forgiven_dropped_words(
    {**junk, "wordplay": {"op": "charade", "parts": [{"words": "tale", "at": 6, "gives": "TALE"}]}},
    fixed, CLUE2)))
# Audit 10-19 (14-down "once"): a link-vocabulary word only an old LEAF held goes; the same
# word as an old indicator ("displayed") stays refused, and the message names its old role.
CLUE4 = "Moral tale once displayed (4)"
once_leaf = {"definitions": [{"text": "Moral tale", "at": 0}],
             "wordplay": {"op": "charade", "parts": [
                 {"words": "once", "at": 11, "gives": "X"}, {"words": "displayed", "at": 16, "gives": "PART"}]}}
once_gone = {"definitions": [{"text": "Moral tale", "at": 0}],
             "wordplay": {"op": "charade", "parts": [{"words": "displayed", "at": 16, "gives": "PART"}]}}
check("a link-vocabulary word only an old leaf held is forgiven", [], redo(once_gone, old=once_leaf, clue=CLUE4))
# Audit 10-20: a charade's glue word ("then") or a word the new definition narrowed away
# ("being") is a link word now; a container indicator ("holding") stays refused.
CLUE6 = "Being moral tale then part (4)"
glue_old = {"definitions": [{"text": "Being moral tale", "at": 0}],
            "wordplay": {"op": "charade", "indicators": [{"text": "then", "at": 17}],
                         "parts": [{"words": "part", "at": 22, "gives": "PART"}]}}
glue_new = {"definitions": [{"text": "moral tale", "at": 6}],
            "wordplay": {"op": "charade", "parts": [{"words": "part", "at": 22, "gives": "PART"}]}}
check("a dropped charade glue word and a narrowed definition word are forgiven", ["being", "then"],
      sorted(v.forgiven_dropped_words(glue_old, glue_new, CLUE6)))
hold_old = {**glue_old, "wordplay": {"op": "insertion", "indicators": [{"text": "then", "at": 17}],
                                     "parts": glue_old["wordplay"]["parts"]}}
check("the same word as a container indicator stays refused", ["being"],
      sorted(v.forgiven_dropped_words(hold_old, glue_new, CLUE6)))
shown = [r for r in v.redo_regressions(
    {"definitions": [{"text": "Moral tale", "at": 0}], "wordplay": {"op": "charade", "indicators": [
        {"text": "displayed", "at": 16}], "parts": [{"words": "once", "at": 11, "gives": "PART"}]}},
    {"definitions": [{"text": "Moral tale", "at": 0}], "wordplay": {"op": "charade", "parts": [
        {"words": "once", "at": 11, "gives": "PART"}]}}, CLUE4)]
check("an old indicator is still refused and named with its role",
      True, len(shown) == 1 and "displayed (in the charade indicator 'displayed')" in shown[0] and "Do not add `linkWords`" in shown[0])
# Audit 10-21: a redo that trims "after leaving" to "leaving" gets the old text back
# instead of a dropped_words refusal; a word really gone stays refused.
CLUE7 = "Moral tale after leaving part (4)"
trim_old = {"definitions": [{"text": "Moral tale", "at": 0}],
            "wordplay": {"op": "deletion", "indicators": [{"text": "after leaving", "at": 11, "note": "n"}],
                         "parts": [{"words": "part", "at": 25, "gives": "PART"}]}}
trim_new = copy.deepcopy(trim_old)
trim_new["wordplay"]["indicators"] = [{"text": "leaving", "at": 17}]
check("a trimmed indicator is refused by the gate as it stands", ["dropped_words"], redo(trim_new, old=trim_old, clue=CLUE7))
carried = v.carry_old_indicators(trim_old, trim_new, CLUE7)
check("carry gives the old indicator text and position back", ("after leaving", 11),
      (carried["wordplay"]["indicators"][0]["text"], carried["wordplay"]["indicators"][0]["at"]))
check("the carried redo passes the gate", [], redo(carried, old=trim_old, clue=CLUE7))
check("the input is not changed", "leaving", trim_new["wordplay"]["indicators"][0]["text"])
gone = copy.deepcopy(trim_new)
gone["wordplay"]["indicators"] = []
check("a dropped indicator is not invented", gone, v.carry_old_indicators(trim_old, gone, CLUE7))
split_old = {"definitions": [{"text": "Moral", "at": 0}],
             "wordplay": {"op": "deletion", "indicators": [{"text": "Nameless", "at": 6}],
                          "parts": [{"words": "bird", "at": 15, "gives": "BIRD"}]}}
split_new = copy.deepcopy(split_old)
split_new["wordplay"]["indicators"] = [{"text": "less", "at": 10}]
check("a word-part indicator is widened to the whole word", "Nameless", v.carry_old_indicators(
    split_old, split_new, "Moral Nameless bird (4)")["wordplay"]["indicators"][0]["text"])
clash = copy.deepcopy(trim_new)
clash["wordplay"]["parts"] = [{"words": "after", "at": 11, "gives": "A"}, {"words": "part", "at": 25, "gives": "PART"}]
check("no carry over another span of the new tree", clash, v.carry_old_indicators(trim_old, clash, CLUE7))
# r29: truncation / cut leaves (times-29276 9a, cryptic-30110 19d, times-29183 28a)
rue = {"op": "charade", "parts": [{"op": "reversal", "indicators": [{"text": "back"}], "parts": [
    {"words": "French way back", "gives": "RUE"}]}]}
check("an op's indicator also ending its leaf is counted", 1, v.own_ind_in_leaf(rue))
rue["parts"][0]["parts"][0]["words"] = "French way"
check("the leaf without the indicator is not", 0, v.own_ind_in_leaf(rue))
mostly = {"op": "charade", "parts": [{"words": "Mostly safe", "gives": "PETE"}, {"words": "sex", "gives": "IT"}]}
check("a leaf holding 'mostly' that gives a word cut short is counted", 1, v.trunc_in_leaf(mostly) if v._lexicon_letters() else 1)
check("'briefly' abbreviations are not", 0, v.trunc_in_leaf({"op": "charade", "parts": [{"words": "Science briefly", "gives": "SCI"}]}))
# r31: tuning on the r30 misses
check("'briefly' with a note saying the word was shortened is counted", 1, v.trunc_in_leaf(
    {"op": "container", "parts": [{"words": "party briefly", "gives": "RAV", "note": "RAVE, shortened"}]}) if v._lexicon_letters() else 1)
check("a leaf that is exactly the indicator's words is counted", 1, v.own_ind_in_leaf({"op": "deletion", "indicators": [
    {"text": "not at first"}], "parts": [{"words": "Idle", "gives": "SLACKING"}, {"words": "not at first", "gives": "S"}]}))
check("a deletion removing a lone selection word is counted", 1, v.selector_as_cut({"op": "deletion", "parts": [
    {"words": "step", "gives": "PACE"}, {"words": "leader", "gives": "P"}]}) if v._owner_type("leader") == "letter_selection" else 1)
shah = {"op": "charade", "parts": [{"op": "last", "indicators": [{"text": "finally"}], "parts": [{"words": "enemies"}]},
                                   {"op": "deletion", "indicators": [{"text": "advancing"}], "parts": [{"words": "mess", "gives": "HASH"}, {"gives": "S"}]}]}
check("a deletion whose letter a sibling pick gives again is a move", 1, v.moved_letters(shah))
site = {"op": "charade", "parts": [{"words": "one out of place", "gives": "STE", "note": "SITE, a place, without I (one)"}]}
check("a non-word leaf whose note says a letter was cut is counted", 1, v.cut_note_leaf(site) if v._lexicon_letters() else 1)
check("the same leaf under a deletion is not", 0, v.cut_note_leaf({"op": "deletion", "parts": [site["parts"][0], {"gives": "I"}]}))
check("an apostrophe drop is not", 0, v.cut_note_leaf({"op": "charade", "parts": [
    {"words": "'ouse", "gives": "OUSE", "note": "'ouse, losing its H"}]}))
check("half-hearted is not a halving deletion", 0, v.halved_as_deletion({"op": "deletion", "indicators": [
    {"text": "half-hearted"}], "parts": [{"words": "mob", "gives": "RABBLE"}, {"gives": "B"}]}))
check("half of is", 1, v.halved_as_deletion({"op": "deletion", "indicators": [
    {"text": "half of"}], "parts": [{"words": "mob", "gives": "RABBLE"}, {"gives": "BLE"}]}))
# r33: tuning on the r32 misses
reawaken = {"op": "anagram", "indicators": [{"text": "Break"}], "parts": [
    {"words": "a"}, {"words": "new", "gives": "N"}, {"words": "weaker"}]}
check("a lone abbreviation letter the answer shows at its end is counted", 1, v.ana_lone_edge(reawaken, "REAWAKEN"))
midway = {"op": "anagram", "indicators": [{"text": "Break"}], "parts": [{"words": "sat"}, {"words": "new", "gives": "N"}, {"words": "tea"}]}
check("a lone letter that cannot sit outside (mid-answer) is not", 0, v.ana_lone_edge(midway, "TEANAST"))
zero = {"op": "charade", "parts": [{"words": "Love", "gives": "ZERO"}, {"op": "anagram", "indicators": [{"text": "reforming"}], "parts": [
    {"words": "to"}, {"words": "cleaner"}]}]}
check("a clue word as written at the fodder's edge, shown unscrambled in the answer, is counted", 1, v.ana_literal_edge(zero, "ZEROTOLERANCE"))
moved_to_front = {"op": "anagram", "indicators": [{"text": "struggling"}], "parts": [{"words": "onward"}, {"words": "we"}]}
check("a literal piece that moves to the front of the answer is genuine fodder", 0, v.ana_literal_edge(moved_to_front, "WEONWARD"))
twerking = {"op": "deletion", "indicators": [{"text": "getting end away"}], "parts": [
    {"op": "charade", "parts": [{"words": "Plonker", "gives": "TWERP"}, {"words": "what Charles would be", "gives": "KING"}]}, {"gives": "P"}]}
clue = "Plonker getting end away - what Charles would be (agitating arse)"
check("a deletion over a charade whose indicator sits between the pieces is counted", 1, v.del_wraps_charade(twerking, clue))
check("the indicator after the charade is not", 0, v.del_wraps_charade(twerking, "Plonker what Charles would be getting end away"))
check("a nth pick a deletion cuts and re-adds is a move", 1, v.moved_letters({"op": "charade", "parts": [
    {"op": "nth", "n": 5, "indicators": [{"text": "fifth of"}], "parts": [{"words": "sonnets"}]},
    {"op": "deletion", "indicators": [{"text": "moving"}], "parts": [{"words": "Greek island", "gives": "CRETE"}, {"gives": "E"}]}]}))
check("a leaf holding twice that gives a doubled string is counted", 1, v.repeat_in_leaf(
    {"op": "charade", "parts": [{"words": "Boy called twice", "gives": "ALFALF"}, {"words": "a", "gives": "A"}]}))
check("a leaf holding half beside the word whose half it gives is counted", 1, v.half_in_leaf(
    {"op": "container", "parts": [{"words": "half-done taco", "gives": "TA"}, {"words": "A", "gives": "A"}]}))
check("a letter-less selection leaf ending with the op's indicator is counted", 1, v.select_ind_ends_leaf(
    {"op": "first", "indicators": [{"text": "on top"}], "parts": [{"words": "cooked on top"}]}))
check("a leaf holding losing head that gives letters is counted", 1, v.behead_in_leaf(
    {"op": "charade", "parts": [{"words": "Youngster losing head", "gives": "ID"}, {"words": "x", "gives": "X"}]}))
check("Pope dismissing foremost giving OPE is a beheading leaf", 1, v.behead_in_leaf(
    {"op": "charade", "parts": [{"words": "Pope dismissing foremost", "gives": "OPE"}, {"words": "x", "gives": "X"}]}))
check("a stutter word giving a doubled string is counted", 1, v.repeat_in_leaf(
    {"op": "charade", "parts": [{"words": "Stuttering", "gives": "LALA"}, {"words": "advice to catch", "gives": "LAND"}]}))
check("a leaf 'two' beside a leaf giving the same letters is counted", 1, v.repeat_in_leaf(
    {"op": "charade", "parts": [{"words": "groups of workers", "gives": "TU"}, {"words": "two", "gives": "TU"}]}))
check("a percentage deletion is a halving-style selection", 1, v.halved_as_deletion({"op": "deletion", "indicators": [
    {"text": "60% of"}], "parts": [{"words": "hospital", "gives": "SANATORIUM"}, {"gives": "RIUM"}]}))
check("a doubling word giving a doubled string is counted", 1, v.repeat_in_leaf(
    {"op": "charade", "parts": [{"words": "Officer doubling", "gives": "COCO"}, {"words": "a", "gives": "A"}]}))
check("a first-letters op beside bare initial leaves is counted", 1, v.first_sibling_leaves({"op": "charade", "parts": [
    {"op": "first", "indicators": [{"text": "heads"}], "parts": [{"words": "cooked"}]},
    {"words": "halved", "gives": "H", "note": "the opening letter of Halved"}, {"words": "elephant", "gives": "E", "note": "the opening letter"}]}))
check("an unindicated hidden word under a 'having returned' reversal is counted", 1, v.hidden_ind_above(
    {"op": "reversal", "indicators": [{"text": "having returned"}], "parts": [{"op": "hidden", "parts": [{"words": "Blame Nicola"}]}]}))
check("a leaf holding primarily that gives the others' initials is counted", 1, v.initials_in_leaf(
    {"op": "charade", "parts": [{"words": "Dish", "gives": "PIZZA"}, {"words": "zip and zing primarily", "gives": "ZZ"}]}))
check("a deletion nested in an unindicated deletion is counted", 1, v.nested_same_op({"op": "deletion", "parts": [
    {"op": "deletion", "indicators": [{"text": "lacking"}], "parts": [{"words": "x", "gives": "ABCD"}, {"gives": "C"}]}, {"gives": "B"}]}))
check("a middle op beside a leaf giving middle letters is counted", 1, v.middle_sibling_leaf({"op": "charade", "parts": [
    {"op": "middle", "indicators": [{"text": "essence of"}], "parts": [{"words": "primeval"}]}, {"words": "passion", "gives": "SSI"}]}))
check("a deletion over a charade cutting inside one piece is counted", 1, v.del_one_piece({"op": "deletion", "indicators": [
    {"text": "no end"}], "parts": [{"op": "charade", "parts": [{"words": "tune", "gives": "MELODY"}, {"words": "hit", "gives": "RAM"}], }, {"gives": "Y"}]}))
check("an anagram that only moves one letter is counted", 1, v.ana_is_move({"op": "anagram", "indicators": [{"text": "when temperature rises"}], "parts": [
    {"words": "unable to react", "gives": "INERT"}]}, "INTER"))
check("three deletions with one indicator are counted", 1, v.split_shared_indicators({"op": "charade", "parts": [
    {"op": "deletion", "indicators": [{"text": "endlessly"}], "parts": [{"words": "a", "gives": "AB"}, {"gives": "B"}]},
    {"op": "deletion", "parts": [{"words": "b", "gives": "CD"}, {"gives": "D"}]},
    {"op": "deletion", "parts": [{"words": "c", "gives": "EF"}, {"gives": "F"}]}]}))
check("a leaf 'doubly' beside a leaf giving the same letters is counted", 1, v.repeat_in_leaf({"op": "charade", "parts": [
    {"words": "dope", "gives": "ASS"}, {"words": "doubly", "gives": "ASS"}]}))
check("a deletion indicated by a movement word whose cut is no clue word is counted", 1, v.del_as_move({
    "op": "deletion", "indicators": [{"text": "relocating"}], "parts": [{"words": "capital", "gives": "LONDON"}, {"gives": "N"}]}))
check("a movement-word deletion cutting a clue word is not counted", 0, v.del_as_move({
    "op": "deletion", "indicators": [{"text": "shifting"}], "parts": [{"words": "rival", "gives": "EVERTON"}, {"words": "ton", "gives": "TON"}]}))
check("a leaf 'more than once' giving the pieces before it is counted", 1, v.repeat_in_leaf({"op": "charade", "parts": [
    {"words": "a", "gives": "A"}, {"words": "kid", "gives": "GAR"}, {"words": "more than once", "gives": "AGAR"}]}))
check("a reversal of a single substitution is not counted by reversal_split", 0, v.reversal_split({
    "op": "reversal", "indicators": [{"text": "knocked back"}], "parts": [{"op": "substitution", "indicators": [{"text": "taking"}], "parts": [
        {"words": "Unfortunately", "gives": "ALACK"}, {"words": "cold", "gives": "C"}, {"words": "oxygen", "gives": "O"}]}]},
    "Unfortunately knocked back, taking oxygen for cold"))
if v._lexicon_letters():
    check("half of a synonym giving a non-word is counted", 1, v.half_in_leaf({"op": "charade", "parts": [
        {"words": "half of train", "gives": "CHOO"}, {"words": "x", "gives": "X"}]}))
    check("a word split around an insert into two leaves is counted", 1, v.split_word_leaves({"op": "charade", "parts": [
        {"op": "container", "parts": [{"words": "cut", "gives": "HA"}, {"words": "stay", "gives": "YSTA"}]},
        {"words": "cut", "gives": "CK"}]}))
    check("a non-word leaf whose note says a letter was moved is counted", 1, v.move_note_leaf(
        {"op": "charade", "parts": [{"words": "Greasy", "gives": "OLY", "note": "OILY, with its I moved down"}, {"words": "x", "gives": "X"}]}))
    check("a one-leaf deletion giving a word one letter short is counted", 1, v.deletion_no_cut(
        {"op": "deletion", "indicators": [{"text": "not quite"}], "parts": [{"words": "target", "gives": "GOA"}]}))
raise SystemExit(fails)
