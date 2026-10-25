#!/usr/bin/env python3
# Wordplay shapes that read wrongly are counted by validate_annotations under their
# own ratchet fields, and tidy_wordplay_shapes.py joins a charade inside a charade
# without changing what view() shows.
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import copy
import json
import annotation, wordplay
import validate_annotations as v
import tidy_wordplay_shapes as T

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

def tree(expr, clue):
    return wordplay.parse(expr, clue)

CLUE = "Fish and chips"
cc = {"op": "charade", "parts": [{"words": "Fish", "at": 0, "gives": "COD"},
      {"op": "charade", "parts": [{"words": "and", "at": 5, "gives": "A"}, {"words": "chips", "at": 9, "gives": "ND"}]}]}
check("a charade inside a charade is counted", 1, v.charade_in_charade(cc))
check("a charade with an indicator inside one is not", 0, v.charade_in_charade(
    {"op": "charade", "parts": [{"gives": "A"}, {"op": "charade", "indicators": [{"text": "x"}], "parts": [{"gives": "B"}, {"gives": "C"}]}]}))
new = copy.deepcopy(cc)
check("the migration joins it", 1, T.flatten_tree(new))
check("into the outer charade, in order", ["Fish", "and", "chips"], [p["words"] for p in new["parts"]])
check("a second run changes nothing", 0, T.flatten_tree(new))

check("an anagram with no indicator is counted", 1, v.unindicated_ops(tree("ana([ab])", "ab")))
check("one with its indicator is not", 0, v.unindicated_ops(tree("ana<odd>([ab])", "odd ab")))
check("a charade and a cryptic definition need none", 0,
      v.unindicated_ops({"op": "cryptic", "parts": [{"words": "x"}]}) + v.unindicated_ops(cc))
check("a cryptic definition's second leaf is counted", 1, v.cdef_repeats(
    {"op": "cryptic", "parts": [{"words": "a b"}, {"words": "a"}]}))
check("a palindrome with two parts has the wrong arity", 1, v.bad_arity(
    {"op": "palindrome", "parts": [{"words": "a"}, {"words": "b"}]}))
check("a homophone's spelling is not a part", 0, v.bad_arity(tree("sound<say>([bare], BARE)", "say bare")))
check("a one-part charade has the wrong arity", 1, v.bad_arity({"op": "charade", "parts": [{"words": "a"}]}))
two = {"op": "charade", "parts": [{"words": "ab", "at": 0}, {"words": "b c", "at": 1}]}
check("two leaves sharing clue words are counted", 1, v.span_overlaps(two))
check("and ones under a cryptic definition are not", 0, v.span_overlaps({"op": "cryptic", "parts": two["parts"]}))
spoon = {"op": "spoonerism", "indicators": [{"text": "Spooner's"}],
         "parts": [{"op": "homophone", "parts": [{"words": "white late"}, {"gives": "WIGHT"}]}, {"words": "x"}]}
check("a Spoonerism's own sound needs no indicator of its own", 0, v.unindicated_ops(spoon))
check("a homophone elsewhere still does", 1, v.unindicated_ops(
    {"op": "charade", "parts": [spoon["parts"][0], {"words": "y"}]}))
check("and a Spoonerism with no indicator is still counted", 1, v.unindicated_ops({**spoon, "indicators": []}))
same = {"op": "charade", "parts": [{"words": "Pieces", "at": 0, "gives": "BIT"}, {"words": "Pieces", "at": 0, "gives": "PART"}]}
check("one word on two leaves (a word doing two jobs) is not claimed twice", 0, v.span_overlaps(same))
check("but a leaf inside another leaf's span still is", 1, v.span_overlaps(
    {"op": "charade", "parts": [{"words": "daycare", "at": 0}, {"words": "care", "at": 3}]}))
check("and an indicator over a leaf still is", 1, v.span_overlaps(
    {"op": "container", "indicators": [{"text": "are covered in", "at": 0}], "parts": [{"words": "are", "at": 0}, {"words": "x", "at": 20}]}))
import shape_suspects as ss
check("the shape detector agrees", None, ss.d_span_overlap({"wp": same}))
ann = {"definitions": [{"text": "ab", "at": 0}], "wordplay": {"words": "ab", "at": 0, "gives": "X"}}
check("wordplay inside the definition is counted", 1, v.in_definition(ann))
check("unless the clue is &lit", 0, v.in_definition({**ann, "andLit": True}))
pal = {"definitions": [{"text": "Bread", "at": 0}], "wordplay": {"op": "palindrome", "indicators": [{"text": "either way", "at": 7}], "parts": [{"words": "Bread", "at": 0, "gives": "NAAN"}]}}
check("a palindrome over the definition's own words is the setter's", 0, v.in_definition(pal))
check("a charade leaf on the definition's words still is counted", 1, v.in_definition(
    {**pal, "wordplay": {"op": "charade", "parts": [pal["wordplay"]["parts"][0]]}}))
split = {"definitions": [{"text": "cock", "at": 34}], "wordplay": {"op": "charade", "parts": [{"words": "stopcock", "at": 30, "gives": "BAN"}]}}
check("a leaf on a word whose end is the definition (a split word) is not counted", 0, v.in_definition(split))
check("a leaf on two words that merely reach into the definition still is", 1, v.in_definition(
    {"definitions": [{"text": "a game", "at": 22}], "wordplay": {"words": "for a", "at": 18, "gives": "PER"}}))
dup = {"clue": {"text": "Small amount of money, very small, last in purse"}}
ann2 = {"definitions": [{"text": "Small amount of money", "at": 0}], "blocks": [{"clueFragment": "very small", "gives": "DIM"}]}
w = []
v.check_definition_not_fodder([{"number": 30, "direction": "across", **dup, "annotation": ann2}], [], w)
check("a block sharing a vocabulary word with the definition, but not its words, is no reuse", [], w)
w = []
ann2["definitions"][0]["at"] = 23
ann2["definitions"][0]["text"] = "very small"
v.check_definition_not_fodder([{"number": 30, "direction": "across", **dup, "annotation": {**ann2, "blocks": [{"clueFragment": "very small", "gives": "DIM"}]}}], [], w)
check("but a block on the definition's own words is", 1, len(w))
check("a leaf giving a stretch of its words is counted", 1, v.leaf_folds({"words": "bridge", "gives": "RID"}))
check("a leaf with a note is not", 0, v.leaf_folds({"words": "bridge", "gives": "RID", "note": "x"}))
check("a leaf under a hidden-word op is not", 0, v.leaf_folds({"op": "hidden", "parts": [{"words": "bridge", "gives": "RID"}]}))
check("a possessive S dropped is not", 0, v.leaf_folds({"words": "Mike's", "gives": "MIKE"}))
check("a standard abbreviation opening the word is not a fold", 0, v.leaf_folds({"words": "English", "gives": "ENG"}))
check("an unlisted stretch of the word is still a fold", 1, v.leaf_folds({"words": "engineering", "gives": "ENG"}))
check("an inner charade under an indicated charade is not counted", 0, v.charade_in_charade(
    {"op": "charade", "indicators": [{"text": "after"}], "parts": [
        {"op": "charade", "parts": [{"words": "a", "gives": "A"}, {"words": "b", "gives": "B"}]},
        {"op": "charade", "parts": [{"words": "c", "gives": "C"}, {"words": "d", "gives": "D"}]}]}))
check("a bare leaf whose note names the preamble is not counted", 0, v.bare_in_charade(
    {"op": "charade", "parts": [{"gives": "R", "note": "the letter the preamble says the wordplay omits"},
                                {"words": "b", "gives": "B"}]}))
check("a bare leaf whose note says nothing of the device is counted", 1, v.bare_in_charade(
    {"op": "charade", "parts": [{"gives": "R", "note": "an R"}, {"words": "b", "gives": "B"}]}))
sel = tree("(first([a]) + first([b]))", "a b")
check("a selection repeated word by word is counted", 1, v.repeated_selections(sel))
check("one leaf is no wordplay", 1, v.single_leaf({"words": "a", "gives": "A"}))
check("bare letters in a charade are counted", 1, v.bare_in_charade(
    {"op": "charade", "parts": [{"gives": "A"}, {"words": "b", "gives": "B"}]}))
bare = {"op": "charade", "parts": [{"gives": "A"}, {"words": "b", "gives": "B"}]}
check("a hiddenLetter clue's bare letters are not counted", 0,
      v.bare_in_charade(bare, {"hiddenLetter": {"kind": "omitted", "letter": "A"}}))
check("a clue with no hiddenLetter is still counted", 1, v.bare_in_charade(bare, {"wordplay": bare}))
dev = {"op": "charade", "parts": [{"gives": "A", "device": True}, {"words": "b", "gives": "B"}]}
check("a leaf marked as a preamble device is not counted", 0, v.bare_in_charade(dev, {"wordplay": dev}))
check("an unmarked bare leaf beside a marked one is counted", 1, v.bare_in_charade(
    {"op": "charade", "parts": [{"gives": "A", "device": True}, {"gives": "C"}, {"words": "b", "gives": "B"}]}))
import puzzle_schema
def _schema_problems(node):
    out = []
    puzzle_schema._check(node, puzzle_schema._resolve("#/$defs/wordplayNode"), "$", out)
    return out
check("the schema accepts the device marker on a bare leaf", [], _schema_problems(dev))
check("and refuses it on a leaf with a stray key", True, bool(_schema_problems({"gives": "A", "bogus": True})))
check("an anagram of a container is counted", 1, v.anagram_of_container(
    {"op": "anagram", "parts": [{"op": "container", "parts": [{"words": "a"}, {"words": "b"}]}]}))

check("a container with one part is counted", 1, v.arity_ins({"op": "container", "unchecked": True, "parts": [{"words": "a"}]}))
check("a checked one is the arity rule's, not this", 0, v.arity_ins({"op": "container", "parts": [{"words": "a"}]}))
check("a substitution with two parts is counted", 1, v.arity_other({"op": "substitution", "unchecked": True, "parts": [{"words": "a"}, {"words": "b"}]}))
check("a deletion with three parts is not (the evaluator takes several pieces)", 0, v.arity_other({"op": "deletion", "unchecked": True, "parts": [{}, {}, {}]}))
check("a deletion with ten parts is counted", 1, v.arity_other({"op": "deletion", "unchecked": True, "parts": [{}] * 10}))
check("a deletion with one part is counted", 1, v.del_single({"op": "deletion", "unchecked": True, "parts": [{"words": "a"}]}))
check("and is not an arityOther", 0, v.arity_other({"op": "deletion", "unchecked": True, "parts": [{"words": "a"}]}))
one = lambda part, ind=True: {"op": "deletion", "unchecked": True, "gives": "STAG",
                              **({"indicators": [{"text": "short"}]} if ind else {}), "parts": [part]}
check("a lone leaf under an indicated deletion is not (STAGE short > STAG)", 0, v.del_single(one({"words": "leg", "gives": "STAGE"})))
check("a lone leaf with no indicator is", 1, v.del_single(one({"words": "leg", "gives": "STAGE"}, ind=False)))
check("a lone composite (GON+AD as one deletion) is", 1, v.del_single(one(
    {"op": "charade", "parts": [{"words": "a", "gives": "GON"}, {"words": "b", "gives": "AD"}]})))
leaf = {"words": "nearly obtains", "gives": "HA"}
check("an indicator inside a leaf is counted", 1, v.ind_in_leaf({"op": "deletion", "unchecked": True, "indicators": [{"text": "nearly"}], "parts": [leaf, {"words": "x"}]}))
check("on a checked op it is cosmetic (azed-1928 8d)", 0, v.ind_in_leaf({"op": "deletion", "indicators": [{"text": "nearly"}], "parts": [leaf, {"words": "x"}]}))
check("a leaf under another op is a misfiled indicator, even on a checked op (times-29198 24a)", 1, v.ind_in_leaf(
    {"op": "container", "indicators": [{"text": "regularly"}], "parts": [{"words": "x", "gives": "X"},
     {"op": "alternate", "unchecked": True, "parts": [{"words": "roubles regularly", "gives": "OUE"}]}]}))
check("under a selection op it is cosmetic (times-29067 1d)", 0, v.ind_in_leaf({"op": "outer", "unchecked": True, "indicators": [{"text": "peeled"}], "parts": [{"words": "peeled fruit", "gives": "ANG"}]}))
check("a whole-leaf indicator is not", 0, v.ind_in_leaf({"op": "deletion", "indicators": [{"text": "nearly"}], "parts": [{"words": "nearly"}]}))

sl = lambda w, g: v.scrambled_leaves({"op": "charade", "parts": [{"words": w, "gives": g}]})
check("a permuted leaf is scrambled", 1, sl("gaunt", "GUTAN"))
check("so is a spaced one", 1, sl("one raged", "ORGEANED"))
check("a sub-multiset out of order is not (coincident synonym)", 0, sl("summer clothes", "SHORTS"))
check("a leaf directly under an anagram is scrambled too (round 3: fodder is verbatim)", 1, v.scrambled_leaves({"op": "anagram", "parts": [{"words": "sword", "gives": "WORDS"}]}))
check("a leaf directly under a reversal is not", 0, v.scrambled_leaves({"op": "reversal", "parts": [{"words": "stressed", "gives": "DESSERTS"}]}))
check("an unchecked leaf too", 1, v.scrambled_leaves({"words": "tent", "gives": "ENTT", "unchecked": True}))
check("an abbreviation is not", 0, sl("about", "C"))
check("a synonym is not", 0, sl("clever", "CUTE"))
check("a leaf giving its own letters is not", 0, sl("tent", "TENT"))
check("a selection in order is not", 0, sl("garden", "GARD"))
check("a one-letter or short leaf is not", 0, sl("to", "OT"))

abuse = {"op": "container", "parts": [
    {"op": "container", "parts": [{"words": "Lincoln", "gives": "ABE"}, {"words": "United", "gives": "U"}]},
    {"words": "struggle", "gives": "S"}]}
check("ABUSE as ins(ins(ABE, U), S) evaluates to the answer: the evaluator is not what refuses it", True,
      bool(v.wordplay.match(abuse, "ABUSE")))
check("a container holding a container as its holder is counted", 1, v.nested_containers(abuse))
check("the other nesting, ins(third, ins(second, first)), is not", 0, v.nested_containers(
    {"op": "container", "parts": [{"words": "x", "gives": "AE"}, abuse["parts"][0]]}))
check("an unchecked container is not", 0, v.nested_containers({**abuse, "unchecked": True}))
sep = {**abuse, "parts": [{**abuse["parts"][0], "indicators": [{"text": "separately"}]}, abuse["parts"][1]]}
check("pieces put in separately at different points are not", 0, v.nested_containers(sep))
twice = {**abuse, "parts": [abuse["parts"][0], {"words": "x", "gives": "U"}]}
check("the same letter put in twice is not", 0, v.nested_containers(twice))
check("close to on a charade is an ordering word, not misplaced", 0, v.misplaced_indicators(
    {"op": "charade", "indicators": [{"text": "close to"}], "parts": [{"words": "a", "gives": "A"}, {"words": "b", "gives": "B"}]}))
wis = {"op": "anagram", "parts": [{"op": "charade", "parts": [
    {"words": "cows in"}, {"words": "wrong", "gives": "SIN"}]}]}
check("a synonym beside literal fodder under an anagram is counted", 1, v.anagram_synonyms(wis))
check("a lone synonym scrambled (indirect anagram) is not", 0, v.anagram_synonyms(
    {"op": "anagram", "parts": [{"words": "arbitrator", "gives": "UMPIRE"}]}))
check("a one-letter abbreviation beside fodder is not", 0, v.anagram_synonyms(
    {"op": "anagram", "parts": [{"op": "charade", "parts": [{"words": "lido"}, {"words": "southern", "gives": "S"}]}]}))
check("a word given twice over is a literal doubling, not a synonym (IDENTITY ITIT)", 0, v.anagram_synonyms(
    {"op": "anagram", "parts": [{"words": "deny"}, {"words": "it - twice", "gives": "ITIT"}]}))
heard = {"op": "charade", "parts": [{"words": "detective", "gives": "DI"}, {"op": "anagram", "parts": [
    {"words": "caught", "gives": "HEARD"}]}]}
check("a lone synonym scrambled with a clue word left over is counted (DIEHARD)", 1, v.anagram_synonyms(
    heard, {"wordplay": heard, "definitions": [{"text": "Reactionary"}]}, "Reactionary detective caught dropping heroin"))
check("a lone synonym scrambled with every word claimed is not", 0, v.anagram_synonyms(
    heard, {"wordplay": heard, "definitions": [{"text": "Reactionary"}]}, "Reactionary detective caught"))
mean = {"op": "charade", "parts": [{"words": "Everyman", "gives": "ME"}, {"op": "regular", "indicators": [{"text": "not until the fourth"}],
        "parts": [{"words": "a", "gives": "A"}]}, {"words": "round", "gives": "N"}]}
check("a selection with an indicator over a one-letter word is counted (MEAN)", 1, v.wrong_role_indicators(mean))
check("a selection over a longer word is not", 0, v.wrong_role_indicators(
    {"op": "first", "indicators": [{"text": "primarily"}], "parts": [{"words": "Guard", "gives": "G"}]}))
subst = {"op": "substitution", "unchecked": True, "gives": "GULES", "parts": [
    {"words": "Guard", "gives": "G"}, {"words": "holds sway", "gives": "RULES"}]}
check("an unchecked substitution of one end letter the pieces compute is verified", 0, len(v.unverified_unchecked(subst)))
swap = {"op": "substitution", "unchecked": True, "gives": "WELLNESS", "parts": [
    {"words": "points", "gives": "SW"}, {"words": "what paper shops do", "gives": "SELLNEWS"}]}
check("an unchecked swap of two letters the pieces compute is verified", 0, len(v.unverified_unchecked(swap)))
check("one whose result the pieces do not compute stays unchecked", 1, len(v.unverified_unchecked(
    {**swap, "gives": "WELLNESX"})))
check("a reversal indicator on a charade is misplaced", 1, v.misplaced_indicators(
    {"op": "charade", "indicators": [{"text": "returned"}], "parts": [{"words": "a", "gives": "A"}, {"words": "b", "gives": "B"}]}))
check("a charade indicator on a charade is not", 0, v.misplaced_indicators(
    {"op": "charade", "indicators": [{"text": "after"}], "parts": [{"words": "a", "gives": "A"}, {"words": "b", "gives": "B"}]}))
for w in ("at first", "opening", "off", "taking", "backing"):
    check(f"ordering word '{w}' on a charade is not misplaced", 0, v.misplaced_indicators(
        {"op": "charade", "indicators": [{"text": w}], "parts": [{"words": "a", "gives": "A"}, {"words": "b", "gives": "B"}]}))
_inner = {"op": "container", "parts": [{"words": "a", "gives": "A"}, {"words": "b", "gives": "B"}]}
for w in ("eating", "to secure", "around"):
    # a charade of bare leaves is only joined by the word (DIVAN "carrying", fix round 4);
    # one with a container among its pieces, or held by one, has the word on the wrong op
    check(f"container verb '{w}' on a charade holding a container is misplaced", 1, v.misplaced_indicators(
        {"op": "charade", "indicators": [{"text": w}], "parts": [_inner, {"words": "b", "gives": "B"}]}))
    check(f"container verb '{w}' on a charade under a container is misplaced", 1, v.misplaced_indicators(
        {"op": "container", "parts": [{"words": "c", "gives": "C"}, {"op": "charade", "indicators": [{"text": w}],
         "parts": [{"words": "a", "gives": "A"}, {"words": "b", "gives": "B"}]}]}))
    check(f"container verb '{w}' joining bare leaves is a link word", 0, v.misplaced_indicators(
        {"op": "charade", "indicators": [{"text": w}], "parts": [{"words": "a", "gives": "A"}, {"words": "b", "gives": "B"}]}))
check("a reversal word on bare leaves is still misplaced", 1, v.misplaced_indicators(
    {"op": "charade", "indicators": [{"text": "returned"}], "parts": [{"words": "a", "gives": "A"}, {"words": "b", "gives": "B"}]}))
check("a deletion lone leaf under an anagram is cut then scrambled", 0, v.del_single(
    {"op": "anagram", "parts": [{"op": "deletion", "unchecked": True, "indicators": [{"text": "unlimited"}],
                                 "parts": [{"words": "picketing"}]}]}))
check("a deletion over a charade saying 'both' covers each piece", 0, v.del_single(
    {"op": "deletion", "unchecked": True, "indicators": [{"text": "both topless"}],
     "parts": [{"op": "charade", "parts": [{"words": "a", "gives": "AB"}, {"words": "b", "gives": "CD"}]}]}))
check("a deletion over a charade saying 'nearly all' is still one piece's", 1, v.del_single(
    {"op": "deletion", "unchecked": True, "indicators": [{"text": "nearly all"}],
     "parts": [{"op": "charade", "parts": [{"words": "a", "gives": "AB"}, {"words": "b", "gives": "CD"}]}]}))
_pick = {"op": "first", "unchecked": True, "gives": "L", "parts": [{"unchecked": True, "words": "beginning of loving", "gives": "L", "select": "first"}]}
check("a first-letter step the words make is verified", [], v.unverified_unchecked(_pick))
check("a pick the words cannot make stays unchecked", 2, len(v.unverified_unchecked(
    {**_pick, "gives": "R", "parts": [{**_pick["parts"][0], "gives": "R"}]})))
check("a verified step in a tree that misses the answer stays unchecked", 2, len(v.unverified_unchecked(_pick, "WEDLOCK")))
check("a spoonerism of two sound words is verified", [], v.unverified_unchecked(
    {"op": "spoonerism", "unchecked": True, "gives": "FASTCAR", "parts": [
        {"unchecked": True, "words": "thrown a long way", "gives": "FASTCAR", "soundsLike": "CAST FAR"}]}))
check("the abbreviation 'volume's' V is not a bare initial", 0, v.bare_initials(
    {"op": "charade", "parts": [{"words": "volume's", "gives": "V"}, {"words": "x", "gives": "Y"}]}))
import shape_queue
import lesson_checks
check("the redo gate names the nested container", True, any(
    f.startswith("nestedContainer") for f in shape_queue.findings(
        {"clue": {"text": "x"}, "solution": "ABUSE"}, {"wordplay": abuse, "definitions": []})))

def del_over(ind, removed, *pieces):
    return {"op": "deletion", "indicators": [{"text": ind}], "parts": [
        {"op": "charade", "parts": [{"words": "w", "gives": g} for g in pieces]}, {"words": "x", "gives": removed}]}

check("endlessly over BORE+ON taking an E (not at the end) is counted", 1, v.deletion_scope(del_over("endlessly", "E", "BORE", "ON")))
check("endlessly over a charade whose end is the letter taken is not", 0, v.deletion_scope(del_over("endlessly", "N", "BORE", "ON")))
check("beheaded over CAD+FENCE taking F is counted", 1, v.deletion_scope(del_over("beheaded", "F", "CAD", "FENCE")))
check("beheaded over a charade whose head is the letter taken is not", 0, v.deletion_scope(del_over("beheaded", "C", "CAD", "FENCE")))
check("an indicator naming no end is not read", 0, v.deletion_scope(del_over("losing", "E", "BORE", "ON")))
check("a deletion over a single leaf is not this rule's", 0, v.deletion_inside_component(
    {"op": "deletion", "indicators": [{"text": "endlessly"}], "parts": [{"words": "bore", "gives": "BORE"}, {"words": "x", "gives": "B"}]}))
check("a deletion naming an end each way is not read", 0, v.deletion_scope(del_over("endlessly beheaded", "E", "BORE", "ON")))

arch = {"op": "deletion", "indicators": [{"text": "originally dismissed"}], "parts": [
    {"op": "charade", "parts": [{"words": "Triumphal building", "gives": "ARCH"}, {"words": "notion", "gives": "IDEA"},
                                {"words": "right-winger", "gives": "CON"}]}, {"gives": "I"}]}
arch_clue = "Triumphal building, notion originally dismissed by right-winger, senior minister"
check("an indicator between the pieces over letters inside one piece is counted", 1,
      v.deletion_inside_component(arch, arch_clue))
check("the same without the clue text counts nothing", 0, v.deletion_inside_component(arch))
check("an indicator after every piece over letters in one piece is counted (everyman-3750 11a)", 1,
      v.deletion_inside_component(arch, clue="Triumphal building, notion, right-winger originally dismissed"))
check("an end indicator is deletion_scope's, not this rule's", 0, v.deletion_inside_component(
    {**arch, "indicators": [{"text": "endlessly"}]}, clue="Triumphal building, notion, right-winger endlessly"))

def del_one(ind, removed, *pieces):
    return {"op": "deletion", "indicators": [{"text": ind}], "parts": [
        {"op": "charade", "parts": [{"words": "w", "gives": g} for g in pieces]}, {"gives": removed}]}

check("half-hearted over CON+SIDE+RABBLE taking B is counted (sundaytel-2922 3d)", 1,
      v.deletion_inside_component(del_one("half-hearted", "B", "CON", "SIDE", "RABBLE"), "Tory party followed by half-hearted mob"))
check("a heart word taking the whole's own centre is not", 0,
      v.deletion_inside_component(del_one("heartless", "E", "AB", "CED"), "x heartless y"))
check("half-cut over FAVE+LAGS taking GS, at the whole's end, is counted (sundaytimes-4834 21d)", 1,
      v.deletion_inside_component(del_one("half-cut", "GS", "FAVE", "LAGS"), "best-loved by half-cut lags"))
check("letters taken from the end of the last piece are counted too (round 6: FATAL, ODOROUS)", 1,
      v.deletion_inside_component(del_one("finished early", "E", "FAT", "ALE"), "porter finished early after extra baggage"))
check("letters that are one piece, the charade's end, are counted", 1,
      v.deletion_inside_component(del_one("losing", "S", "FAVE", "LAGS", "S"), "best-loved lags losing s"))
check("letters spread over two pieces are not", 0,
      v.deletion_inside_component(del_one("losing", "EL", "FAVE", "LAGS"), "best-loved losing lags"))
ach = {"op": "deletion", "indicators": [{"text": "disposing of"}], "parts": [
    {"op": "charade", "parts": [{"words": "a", "gives": "A"}, {"words": "system", "gives": "CHING"}, {"words": "one", "gives": "I"}]},
    {"gives": "I"}]}
check("a piece added then removed is counted though its letter also sits in another piece (ACHING)", 1,
      v.deletion_inside_component(ach, "A system of divination disposing of one longing"))
check("letters that are a whole piece are counted: a piece added to be removed", 1, v.deletion_inside_component(
    {**arch, "parts": [arch["parts"][0], {"gives": "IDEA"}]}, clue=arch_clue))

def role_tree(outer_ind, inner_ind=None):
    inner = {"op": "reversal", "parts": [{"words": "x", "gives": "AB"}]}
    if inner_ind:
        inner["indicators"] = [{"text": inner_ind}]
    return {"op": "container", "indicators": [{"text": outer_ind}], "parts": [{"words": "y", "gives": "CD"}, inner]}

check("a reversal word on the container beside an unindicated reversal is counted", 1,
      v.wrong_role_indicators(role_tree("returned")))
check("a container word on the container is not", 0, v.wrong_role_indicators(role_tree("entering")))
check("a lone owned word with no op of its owner type to take it is not", 0, v.wrong_role_indicators(
    {"op": "container", "indicators": [{"text": "returned"}], "parts": [{"words": "y", "gives": "CD"}, {"words": "x", "gives": "AB"}]}))
check("an ambiguous word (about) is never counted", 0, v.wrong_role_indicators(role_tree("about")))
check("a reversal word on the container beside a reversal that has its own indicator is not", 0,
      v.wrong_role_indicators(role_tree("returned", "back")))

sesame = {"op": "charade", "parts": [{"words": "Sesame", "gives": "S"}, {"words": "street", "gives": "TREET"}]}
check("a first letter given by a leaf, with no selection above it, is counted", 1, v.bare_initials(sesame))
check("under a first-letter selection it is not", 0, v.bare_initials({"op": "first", "parts": [sesame["parts"][0]]}))
check("a flagged selection leaf is not", 0, v.bare_initials({"op": "charade", "parts": [{**sesame["parts"][0], "select": True}]}))
check("a short word (above A) is not", 0, v.bare_initials({"op": "charade", "parts": [{"words": "above", "gives": "A"}]}))
check("a word with a one-letter reading in the usage lexicon (canine C) is not", 0, v.bare_initials(
    {"op": "charade", "parts": [{"words": "canine", "gives": "C"}]}))
check("two clue words are not", 0, v.bare_initials({"op": "charade", "parts": [{"words": "Sesame street", "gives": "S"}]}))
check("a leaf giving other letters is not", 0, v.bare_initials({"op": "charade", "parts": [{"words": "Sesame", "gives": "T"}]}))
check("a deletion scope is warning-only (10-20 redo audit): the redo gate does not name it", False, any(
    f.startswith("deletionScope") for f in shape_queue.findings(
        {"clue": {"text": "x"}, "solution": "BORON"}, {"wordplay": del_over("endlessly", "E", "BORE", "ON"), "definitions": []})))

# Round 7: five shapes that passed every rule (12 of 300 passing clues wrong).
def mids(*inds):
    return {"op": "charade", "parts": [{"op": "middle", **({"indicators": [{"text": t}]} if t else {}),
                                        "parts": [{"words": w, "gives": g}]}
                                       for t, w, g in zip(inds, ("giving", "chord", "flat"), ("VI", "O", "LA"))]}
check("one indicator over a run of three middles is a list", 0, v.unindicated_uncovered(mids("essentially", None, None)))
far = mids("essentially", None, None)
for k, (at, p) in enumerate(zip((40, 47, 53), far["parts"])):
    p["parts"][0]["at"] = at
far["parts"][0]["indicators"][0]["at"] = 0
check("but an indicator far from the run it is said to cover is not (VIOLA)", 2, v.unindicated_uncovered(far))
check("a midword leaf holding a cut word (INTE from winter stripped) is counted", 1, v.midword_leaves(
    {"op": "charade", "parts": [{"words": "winter stripped", "gives": "INTE"}, {"words": "x", "gives": "Y"}]}))
check("one with no cut word (THED from the day) is not, r31", 0, v.midword_leaves(
    {"op": "charade", "parts": [{"words": "the day", "gives": "THED"}, {"words": "x", "gives": "Y"}]}))
check("a stretch on word edges is not", 0, v.midword_leaves({"op": "charade", "parts": [{"words": "up the road", "gives": "THEROAD"}]}))
check("an indicator on each is fine", 0, v.unindicated_uncovered(mids("essentially", "heart of", "inside")))
check("an adjacent pair of one selection may share one", 0, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"op": "first", "indicators": [{"text": "tops"}], "parts": [{"words": "so", "gives": "S"}]},
                                {"op": "first", "parts": [{"words": "extend", "gives": "E"}]}]}))
check("but not a pair of deletions far apart in the clue", 1, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"op": "deletion", "indicators": [{"text": "lacking", "at": 2}], "parts": [{"words": "a", "at": 0, "gives": "AB"}, {"gives": "B"}]},
                                {"op": "deletion", "parts": [{"words": "c", "at": 40, "gives": "CD"}, {"gives": "D"}]}]}))  # round 14: neighbours share one
poss = {"op": "charade", "parts": [{"op": "anagram", "indicators": [{"text": "possibly"}], "parts": [{"words": "wrap", "gives": "WRAP"}]},
                                   {"words": "possibly", "gives": "CRACKERS"}]}
check("an indicator that is also a leaf's words is claimed twice", 1, v.shared_indicators(poss))
check("unless the clue says the word twice", 0, v.shared_indicators(poss, "possibly wrap possibly"))
check("a deletion's own cut words are told truly", 0, v.shared_indicators(
    {"op": "deletion", "indicators": [{"text": "topless"}], "parts": [{"words": "x", "gives": "TERROR"}, {"words": "topless", "gives": "T"}]}))
check("two ops with the same indicator", 1, v.shared_indicators(
    {"op": "charade", "parts": [{"op": "reversal", "indicators": [{"text": "up", "at": 3}], "parts": [{"words": "a", "gives": "A"}]},
                                {"op": "reversal", "indicators": [{"text": "up", "at": 3}], "parts": [{"words": "b", "gives": "B"}]}]}))
half = {"op": "charade", "parts": [{"op": "deletion", "indicators": [{"text": "only half of"}],
                                    "parts": [{"words": "live"}, {"gives": "VE"}]},
                                   {"words": "ones", "gives": "ON"}]}
check("a bare half of a word beside a half indicator is counted", 1, v.half_leaves(half))
check("with no half indicator it is an abbreviation, not counted", 0, v.half_leaves(
    {"op": "charade", "parts": [{"words": "ones", "gives": "ON"}, {"words": "x", "gives": "Y"}]}))
tolkien = {"op": "deletion", "indicators": [{"text": "Not half"}],
           "parts": [{"op": "charade", "parts": [{"words": "Tolman", "gives": "TOLMAN"}, {"words": "Kili", "gives": "KILI"},
                                                 {"words": "Ents", "gives": "ENTS"}]}, {"gives": "MANLITS"}]}
check("one half deletion picking letters out of three words is counted", 1, v.deletion_scattered(tolkien))
check("a run of one piece is not", 0, v.deletion_scattered(
    {**tolkien, "parts": [tolkien["parts"][0], {"gives": "ILI"}]}))
check("a reverse reading over a phrase of 3+ words is counted", 1, v.reverse_phrase(
    {"op": "reverse", "reading": "ROUGH + HEWN", "parts": [{"words": "When cryptic maybe"}]}))
check("a short one, or one that says this, is not", 0, v.reverse_phrase(
    {"op": "reverse", "parts": [{"words": "by and"}]}) + v.reverse_phrase(
    {"op": "reverse", "parts": [{"words": "This could make pals"}]}))
inspiration = {"op": "deletion", "indicators": [{"text": "before its conclusion"}],
               "parts": [{"op": "charade", "parts": [{"words": "popular", "gives": "IN"}, {"words": "turn", "gives": "SPIN"},
                                                     {"words": "helping", "gives": "RATION"}]}, {"gives": "N"}]}
check("a cut that is one piece's N, once the answer picks the reading", 1, v.deletion_inside_component(
    inspiration, "Muse helping to support popular turn before its conclusion", "INSPIRATION"))
check("is not counted without the answer", 0, v.deletion_inside_component(
    inspiration, "Muse helping to support popular turn before its conclusion"))
check("OMEGA with G swapped for RT is a verified substitution", [], v.unverified_unchecked(
    {"op": "substitution", "unchecked": True, "gives": "OMERTA", "indicators": [{"text": "made"}],
     "parts": [{"words": "x", "gives": "OMEGA"}, {"words": "good", "gives": "G"}, {"words": "y", "gives": "RT"}]}))
check("twentieth giving T is not a bare initial", 0, v.bare_initials(
    {"op": "charade", "parts": [{"words": "collection of data", "gives": "FILE"}, {"words": "twentieth", "gives": "T"}]}))

# Round 11: three shapes that passed every rule (9 of 300 passing clues wrong).
def lf(words, gives=None, **kw):
    return {"words": words, **({"gives": gives} if gives else {}), **kw}
needier = {"op": "reversal", "indicators": [{"text": "turned up"}, {"text": "elevated"}],
           "parts": [{"op": "container", "indicators": [{"text": "in"}], "parts": [lf("check", "REIN"), lf("girl", "DEE")]}]}
check("a reversal with two indicators is counted (NEEDIER)", 1, v.double_indicators(needier))
check("one indicator is not", 0, v.double_indicators({**needier, "indicators": [{"text": "turned up"}]}))
check("two touching halves of one phrase are not", 0, v.double_indicators(
    {**needier, "indicators": [{"text": "turned", "at": 3}, {"text": "up", "at": 10}]}))
check("a deletion with two indicators is counted (IRON)", 1, v.double_indicators(
    {"op": "deletion", "indicators": [{"text": "'eadless"}, {"text": "without an aitch"}],
     "parts": [lf("'orseman of legend", "CHIRON"), {"gives": "CH"}]}))
check("an anagram with two indicators is left to the judges", 0, v.double_indicators(
    {"op": "anagram", "indicators": [{"text": "off"}, {"text": "out"}], "parts": [lf("x")]}))
earl = {"op": "hidden", "indicators": [{"text": "inside"}], "parts": [{"op": "middle", "parts": [lf("pearly", "EARL")]}]}
check("a hidden word over a selection with no indicator is counted (EARL)", 1, v.double_indicators(earl))
check("a selection with its own indicator is not", 0, v.double_indicators(
    {**earl, "parts": [{**earl["parts"][0], "indicators": [{"text": "centre of"}]}]}))

amer = {"op": "charade", "indicators": [{"text": "opened by"}], "parts": [
    {"op": "anagram", "indicators": [{"text": "tangled"}], "parts": [lf("in camera"), lf("pressure", "P")]},
    lf("that is", "IE")]}
amer_clue = "Film tangled in camera that is opened by pressure"
check("a pool piece placed beyond other ops' words is counted (AMERICANPIE)", 1, v.pool_gaps(amer, amer_clue))
check("a pool of adjacent pieces is not", 0, v.pool_gaps(
    {"op": "anagram", "indicators": [{"text": "tangled"}], "parts": [lf("in camera"), lf("pressure", "P")]},
    "Film tangled in camera pressure"))
check("the anagram's own indicator between its pieces is not", 0, v.pool_gaps(
    {"op": "anagram", "indicators": [{"text": "wildly"}], "parts": [lf("in camera"), lf("pressure")]},
    "in camera wildly pressure"))
check("without the clue nothing is counted", 0, v.pool_gaps(amer, ""))

surface = {"op": "deletion", "indicators": [{"text": "nearly"}], "parts": [
    {"op": "charade", "parts": [lf("safe", "SURE"), lf("following", "F"), lf("powerful shot", "ACE")]}, {"gives": "E"}]}
check("an end deletion whose answer-making letter is a middle piece's is counted (SURFACE)", 1,
      v.deletion_scope_answer(surface, "SURFACE"))
check("plain deletion_scope still passes it", 0, v.deletion_scope(surface))
check("without the answer it is not counted", 0, v.deletion_scope_answer(surface, None))
check("a cut that is at the end and makes the answer is not", 0, v.deletion_scope_answer(
    {**surface, "parts": [{"op": "charade", "parts": [lf("safe", "SURF"), lf("powerful shot", "ACE")]}, {"gives": "E"}]}, "SURFAC"))
for field in ("deletionScopeAnswer", "doubleIndicator", "poolGap"):
    check(f"wordplay.{field} is a ratchet field", True, f"wordplay.{field}" in v.BACKLOG_MARKERS)
check("the redo gate names them", {"deletionScopeAnswer", "doubleIndicator", "poolGap"} <= set(shape_queue._validator_rules()), True)

# round 11 false positives
for w, g in (("kosher", "K"), ("Little", "L"), ("quality", "Q")):
    check(f"{w} giving {g} is a known abbreviation, not a bare initial", 0, v.bare_initials(
        {"op": "charade", "parts": [{"words": w, "gives": g}]}))
check("perhaps on a charade of plain leaves marks an example, not misplaced", 0, v.misplaced_indicators(
    {"op": "charade", "indicators": [{"text": "perhaps"}], "parts": [
        {"words": "commercial vehicle", "gives": "VAN"}, {"words": "Person keeping eye on", "gives": "GUARD"}]}))
check("in the end on a charade is an ordering word, not misplaced", 0, v.misplaced_indicators(
    {"op": "charade", "indicators": [{"text": "in the end"}], "parts": [
        {"words": "without", "gives": "SINE"}, {"words": "Weak", "gives": "W"}]}))
check("last over 'final of competition' needs no separate indicator", 0, v.unindicated_uncovered(
    {"op": "container", "indicators": [{"text": "hosting"}], "parts": [
        {"words": "Place", "gives": "AREA"}, {"op": "last", "parts": [{"words": "final of competition"}]}]}))
check("first over 'mountaintop' needs no separate indicator", 0, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"words": "Distant", "gives": "FAR"},
                                {"op": "first", "parts": [{"words": "mountaintop"}]}]}))
check("last over a plain leaf still needs one", 1, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"words": "Distant", "gives": "FAR"},
                                {"op": "last", "parts": [{"words": "competition"}]}]}))
check("first over 'skinhead' is S, as skin + head (round 14: STALKER, SURFEIT judged fine)", 0, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"op": "first", "parts": [{"words": "Skinhead"}]}, {"words": "running off", "gives": "PRINTING"}]}))
check("'what's left of it' is the remainder, not a deletion folded in a leaf", 0, v.folded_deletion_leaves(
    {"op": "charade", "parts": [{"words": "what's left of it", "gives": "ASH"}]}))
check("'dropping dead' as one phrase is a synonym reading now (round 18, 8 of 9 judged fine)", 0, v.folded_deletion_leaves(
    {"op": "charade", "parts": [{"words": "stylish man dropping dead", "gives": "UDE"}]}))

check("'What's left after necessary deductions' is no folded deletion", 0, v.folded_deletion_leaves(
    {"op": "charade", "parts": [{"words": "What's left after necessary deductions", "gives": "NET"}]}))
check("'party left wing' is no folded deletion", 0, v.folded_deletion_leaves(
    {"op": "charade", "parts": [{"words": "party left wing", "gives": "COR"}]}))
check("'drop of water' is no folded deletion", 0, v.folded_deletion_leaves(
    {"op": "charade", "parts": [{"words": "drop of water", "gives": "RAIN"}]}))
check("'shed light on' is no folded deletion", 0, v.folded_deletion_leaves(
    {"op": "charade", "parts": [{"words": "shed light on", "gives": "LIT"}]}))
check("'one lacking sense' is no folded deletion", 0, v.folded_deletion_leaves(
    {"op": "charade", "parts": [{"words": "one lacking sense", "gives": "NIT"}]}))

# round 12 false positives
check("'to lose relish' meaning PALL is no folded deletion", 0, v.folded_deletion_leaves(
    {"op": "charade", "parts": [{"words": "to lose relish", "gives": "PALL"}]}))
check("'play without hindrance' meaning HAM is no folded deletion", 0, v.folded_deletion_leaves(
    {"op": "charade", "parts": [{"words": "play without hindrance", "gives": "HAM", "note": "to ham is to overact"}]}))
check("'pupils? Half missing' is still a folded deletion", 1, v.folded_deletion_leaves(
    {"op": "charade", "parts": [{"words": "pupils? Half missing", "gives": "PUP"}]}))
check("a note naming the longer word is a synonym phrase now ('Smaug' losing A, round 18)", 0, v.folded_deletion_leaves(
    {"op": "charade", "parts": [{"words": "Dragon losing a", "gives": "SMUG", "note": "Smaug without the A"}]}))
for w in ("ringleader", "redhead", "knucklehead"):
    check(f"first over '{w}' is the head of a compound: no separate indicator", 0, v.unindicated_uncovered(
        {"op": "charade", "parts": [{"op": "first", "parts": [{"words": w}]}, {"words": "running off", "gives": "PRINTING"}]}))
check("first over \"champion's top\" names its own pick", 0, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"op": "first", "parts": [{"words": "champion's top"}]}, {"words": "running off", "gives": "PRINTING"}]}))
check("first over President is P, a known abbreviation", 0, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"op": "first", "parts": [{"words": "President"}]}, {"words": "running off", "gives": "PRINTING"}]}))
check("an anagram leaf with the indicator folded in (Outdated -> DATED) needs no more", 0, v.unindicated_uncovered(
    {"op": "anagram", "parts": [{"words": "Outdated", "gives": "DATED"}, {"words": "CID", "gives": "CID"}]}))
check("Failing giving F is a grade, not a bare initial", 0, v.bare_initials(
    {"op": "charade", "parts": [{"words": "Failing", "gives": "F"}]}))
dd = {"definitions": [{"text": "A novelist, perhaps", "at": 0}, {"text": "for trees?", "at": 21}]}
check("an anagram inside one definition of a double definition is chance", None, lesson_checks.dd_misses_wordplay(
    dd, "A novelist, perhaps, for trees?", "FORESTER"))
check("an anagram across the definitions is still wordplay", "anagram", lesson_checks.dd_misses_wordplay(
    {"definitions": [{"text": "A novelist, perhaps", "at": 0}, {"text": "trees?", "at": 25}]}, "A novelist, perhaps, for trees?", "FORESTER"))

# round 12 false negatives
mixed = {"op": "container", "indicators": [{"text": "capturing"}, {"text": "retreating"}], "parts": [
    {"words": "Enemy", "gives": "FOE"}, {"words": "retreating king", "gives": "RC"}]}
check("a reversal word filed on a container and again inside its leaf is counted (FORCE)", 1, v.ind_in_leaf(mixed))
check("... a container word in the container's own leaf stays cosmetic", 0, v.ind_in_leaf(
    {"op": "container", "indicators": [{"text": "capturing"}], "parts": [
        {"words": "Enemy", "gives": "FOE"}, {"words": "capturing king", "gives": "RC"}]}))
check("a selection phrase on an anagram is the wrong op's", 1, v.wrong_role_indicators(
    {"op": "anagram", "indicators": [{"text": "Last couple in"}, {"text": "re-ordered"}], "parts": [{"words": "bar"}]}))
swap = {"op": "charade", "parts": [{"words": "Greek character", "gives": "RHO"}, {"op": "container", "indicators": [{"text": "almost"}], "parts": [
    {"words": "late", "gives": "DEA"}, {"op": "reversal", "indicators": [{"text": "provides cover"}], "parts": [{"words": "is"}]}]}]}
check("a cut word on a container where the tree has no deletion is counted (RHODESIA)", 1, v.wrong_role_indicators(swap))
check("a lone reversal word with no reversal op is still let go", 0, v.wrong_role_indicators(
    {"op": "container", "indicators": [{"text": "returned"}], "parts": [{"words": "y", "gives": "CD"}, {"words": "x", "gives": "AB"}]}))
check("an indicator word and a synonym leaf on the same words are claimed twice (BERATED)", 1, v.shared_indicators(
    {"op": "container", "indicators": [{"text": "sleeping"}], "parts": [
        {"words": "sleeping", "gives": "BED"}, {"words": "judge", "gives": "RATE"}]}))
check("a short reading of the container word (onboard SS) is still one word", 0, v.shared_indicators(
    {"op": "container", "indicators": [{"text": "onboard"}], "parts": [
        {"words": "onboard", "gives": "SS"}, {"words": "judge", "gives": "RATE"}]}))
two_firsts = {"op": "anagram", "indicators": [{"text": "awash", "at": 10}], "parts": [
    {"words": "was", "at": 6},
    {"op": "first", "parts": [{"words": "Marsh", "at": 0}]},
    {"op": "first", "indicators": [{"text": "initially", "at": 28}], "parts": [{"words": "plants", "at": 21}]}]}
check("one 'initially' over two picks far apart in the clue leaves the first with none (SWAMP)", 1, v.unindicated_uncovered(two_firsts))
near = {**two_firsts, "parts": [two_firsts["parts"][0],
        {"op": "first", "parts": [{"words": "so", "at": 0}]},
        {"op": "first", "indicators": [{"text": "tops", "at": 10}], "parts": [{"words": "extend", "at": 3}]}]}
check("two picks side by side share the one", 0, v.unindicated_uncovered(near))
nad = {"op": "reversal", "indicators": [{"text": "turned up"}], "parts": [{"op": "container", "indicators": [{"text": "to welcome"}], "parts": [
    {"op": "charade", "parts": [{"words": "called", "gives": "NAMED"}, {"words": "Garfunkel", "gives": "ART"}]}, {"words": "son", "gives": "S"}]}]}
check("a piece put inside one piece of a holder under a reversal is counted (TRADESMAN)", 1, v.container_inside_component(nad, "TRADESMAN"))
half = {"op": "anagram", "indicators": [{"text": "in a storm"}], "parts": [{"op": "deletion", "indicators": [{"text": "not half"}], "parts": [
    {"op": "charade", "parts": [{"words": "Make sail", "gives": "MAKESAIL"}, {"words": "neat", "gives": "NEAT"}]}, {"words": "x", "gives": "AT"}]}]}
check("'not half' acts on one piece even under an anagram", 1, v.deletion_inside_component(half, "Make sail neat (not half) in a storm"))
motors = {"op": "deletion", "indicators": [{"text": "around"}], "parts": [
    {"op": "charade", "parts": [{"words": "Majority", "gives": "MOST"}, {"words": "forbears", "gives": "ANCESTORS"}]},
    {"words": "motors", "gives": "MOTORS"}]}
check("a whole word cut from a charade it is not a run of is scattered (STANCES)", 1, v.deletion_scattered(motors))
check("... and one that is a run of it is not", 0, v.deletion_scattered({**motors, "parts": [motors["parts"][0], {"words": "ancestors", "gives": "ANCESTORS"}]}))

for field in ("sharedIndicator", "halfLeaf", "deletionScattered", "reversePhrase",
              "deletionScope", "wrongRole", "deletionInside", "nestedContainer","anagramSynonym", "misplacedIndicator", "scrambledLeaf", "arityIns", "arityOther", "delSingle", "indInLeaf", "charadeInCharade", "noIndicator", "cdefRepeat", "arity", "spanOverlap", 
              "leafFold", "repeatedSelection", "singleLeaf", "bareInCharade", "anagramOfContainer"):
    check(f"wordplay.{field} is a ratchet field", True, f"wordplay.{field}" in v.BACKLOG_MARKERS)
check("wordplay.containerInside is a ratchet field", True, "wordplay.containerInside" in v.BACKLOG_MARKERS)
lag = {"op": "container", "indicators": [{"text": "kidnapping"}], "parts": [
    {"op": "charade", "parts": [{"words": "criminal", "gives": "LAG"}, {"words": "killer", "gives": "ASP"}]},
    {"words": "saint", "gives": "ST"}]}
check("a piece put inside one piece of the holder is counted (LASTGASP)", 1, v.container_inside_component(lag, "LASTGASP"))
check("with no answer it counts nothing", 0, v.container_inside_component(lag))
seam = {**lag, "parts": [lag["parts"][0], {"words": "x", "gives": "T"}]}
check("a piece that can go in at the join is not (LAGTASP is no answer, LAGTASP join)", 0,
      v.container_inside_component(seam, "LAGTASP"))
sel = {"op": "container", "indicators": [{"text": "holding"}], "parts": [
    {"op": "charade", "parts": [{"words": "love", "gives": "O"}, {"op": "last", "indicators": [{"text": "tips from"}],
        "parts": [{"words": "Wills", "gives": "S"}, {"words": "Kate", "gives": "E"}]}]},
    {"words": "newly-delivered", "gives": "BORN"}]}
check("a selection over two words has the join between its letters, where a piece may go in (cyclops-503 4d)", 0,
      v.container_inside_component({**sel, "parts": [sel["parts"][0], {"words": "x", "gives": "T"}]}, "OSTE"))
check("three daughters scrambled as DDD is literal, not a synonym", 0, v.anagram_synonyms(
    {"op": "anagram", "parts": [{"words": "an emu"}, {"words": "three daughters", "gives": "DDD"}]}))
check("two ends as ENDEND is literal too", 0, v.anagram_synonyms(
    {"op": "anagram", "parts": [{"words": "two ends", "gives": "ENDEND"}, {"words": "have"}]}))
check("a repeat word on a charade covers its exact copy", 0, v.unindicated_uncovered({"op": "charade", "indicators": [{"text": "repeatedly"}], "parts": [
    {"op": "container", "indicators": [{"text": "by"}], "parts": [{"words": "a", "gives": "GIS"}, {"words": "b", "gives": "R"}]},
    {"op": "container", "parts": [{"words": "a", "gives": "GIS"}, {"words": "b", "gives": "R"}]}]}))
warn = v.shape_warnings("1A", {"wordplay": cc, "definitions": []})
check("the ratchet refuses one more than a puzzle is allowed", 1,
      len(v.backlog_errors("x-1", warn, {"wordplay.charadeInCharade": {}})))
check("and allows what it has", 0, len(v.backlog_errors("x-1", warn, {"wordplay.charadeInCharade": {"x-1": 1}})))
# Round 13: the trees the verdicts read, {id: [answer, clue, wordplay]}
R13 = json.loads(r'''{"times-28370#4d": ["RUNES", "Characters could be extras possibly around edge of scene", {"op": "container", "indicators": [{"text": "around", "at": 36}], "parts": [{"words": "extras possibly", "at": 20, "gives": "RUNS"}, {"op": "last", "indicators": [{"text": "edge of", "at": 43}], "parts": [{"words": "scene", "at": 51}]}]}], "cyclops-410#10a": ["DARK", "& 25ac. Sun quite lacking and Times not exactly remembered for cultural advancement!", {"op": "charade", "parts": [{"words": "Sun quite lacking", "gives": "DARK"}, {"words": "Times", "gives": "AGES"}]}], "times-20052#18d": ["THOUGHT", "It's an idea, albeit daft in the extreme", {"op": "charade", "parts": [{"words": "albeit", "gives": "THOUGH"}, {"op": "last", "indicators": [{"text": "in the extreme"}], "parts": [{"words": "daft"}]}]}], "toughie-3442#18d": ["OPTICAL", "Like some illusions, best when using the other extreme of magic", {"op": "substitution", "indicators": [{"text": "when using", "at": 26}], "parts": [{"words": "best", "at": 21, "gives": "OPTIMAL"}, {"gives": "M"}, {"op": "last", "indicators": [{"text": "the other extreme of", "at": 37}], "parts": [{"words": "magic", "at": 58}]}]}], "times-29667#22d": ["WILDE", "Writer lacking in cultivation, we're told", {"op": "homophone", "spelt": "WILDE", "indicators": [{"text": "we're told"}], "parts": [{"words": "lacking in cultivation", "gives": "WILD"}]}], "toughie-832#1d": ["RASP", "Cuff catches edge of school file", {"op": "container", "indicators": [{"text": "catches"}], "parts": [{"words": "Cuff", "gives": "RAP"}, {"op": "first", "indicators": [{"text": "edge of"}], "parts": [{"words": "school"}]}]}], "cryptic-22221#25a": ["ARGENT", "Silver rouble accepted by representative", {"op": "container", "indicators": [{"text": "accepted by"}], "parts": [{"words": "representative", "gives": "AGENT"}, {"words": "rouble", "gives": "R"}]}], "cryptic-30087#18a": ["RAW", "Harsh fightback", {"op": "reversal", "indicators": [{"text": "fightback"}], "parts": [{"words": "fightback", "gives": "WAR"}]}], "cryptic-21817#4d": ["SEWN", "Tacked, choosing directions in sequence", {"op": "charade", "unchecked": true, "gives": "SEWN", "indicators": [{"text": "in sequence"}], "parts": [{"words": "directions", "gives": "SEWN"}]}], "times-19431#2d": ["WOOED", "Courted sweetheart in a club", {"op": "container", "indicators": [{"text": "in"}], "parts": [{"words": "a club", "gives": "WOOD"}, {"op": "middle", "unchecked": true, "gives": "E", "parts": [{"unchecked": true, "words": "sweetheart", "gives": "E", "select": "middle"}]}]}], "cryptic-29063#7d": ["RACONTEUR", "Storyteller, creator uninvolved?", {"op": "anagram", "parts": [{"words": "creator", "at": 13}, {"words": "uninvolved", "at": 21, "gives": "UN"}]}], "nation-3499#8d": ["FREE", "Iron roundabout, without a charge", {"op": "container", "parts": [{"words": "Iron", "at": 0, "gives": "FE"}, {"words": "roundabout", "at": 5, "gives": "RE"}]}], "cryptic-22406#1d": ["HINGIS", "Something I said to 27 on court", {"op": "hidden", "parts": [{"words": "Something I said", "gives": "HINGIS"}]}], "timesquick-3294#7d": ["STURGEON", "Scot lacking heart to encourage SNP politician", {"op": "charade", "parts": [{"words": "Scot lacking heart", "gives": "ST"}, {"words": "to encourage", "gives": "URGEON"}]}], "times-29328#22a": ["SUSHI", "Vessel losing power carrying American food from Japan", {"op": "container", "indicators": [{"text": "carrying"}], "parts": [{"words": "Vessel losing power", "gives": "SHI", "note": "SHIP without P, for power"}, {"words": "American", "gives": "US", "note": "US = American"}]}], "cryptic-29305#1d": ["CHATEAU", "Supply thé and café au lait for French drink supplier", {"op": "anagram", "indicators": [{"text": "Supply"}], "parts": [{"words": "thé"}, {"words": "café au lait"}]}], "times-28709#22d": ["RHEAS", "When rook soars, catches birds that can't", {"op": "cycling", "unchecked": true, "gives": "RHEAS", "indicators": [{"text": "rook soars"}], "parts": [{"words": "catches", "gives": "HEARS"}]}], "times-29578#26a": ["UNSPORTSMANLIKE", "Most plans run poorly by president playing unfairly", {"op": "charade", "indicators": [{"text": "poorly"}], "parts": [{"op": "anagram", "indicators": [{"text": "by"}], "parts": [{"words": "Most plans run"}]}, {"words": "president", "gives": "IKE"}]}], "azed-1946#17a": ["TURNTURTLE", "'Flip!' This instruction makes sow feel sexy! (10, two words)", {"op": "charade", "parts": [{"words": "This instruction", "gives": "TURN"}, {"op": "reversal", "indicators": [{"text": "This instruction makes"}], "parts": [{"op": "charade", "parts": [{"words": "sow", "gives": "ELT"}, {"words": "feel sexy", "gives": "RUT"}]}]}]}]}''')

def r13(id_):
    ans, clue, wp = R13[id_]
    return wp, clue, ans

for id_ in ("times-28370#4d", "cyclops-410#10a", "times-20052#18d", "toughie-3442#18d", "times-29667#22d", "toughie-832#1d"):
    check(f"{id_}: a one-end pick, a linked-clue charade or a homophone is not a wrong role", 0, v.wrong_role_indicators(r13(id_)[0]))
check("timesquick-3294#7d: ST runs in order through the leaf's own word Scot, still a folded cut", 1, v.wrong_role_indicators(r13("timesquick-3294#7d")[0]))
check("times-29328#22a: SHIP less P named only in the note is a synonym phrase now (round 18)", 0, v.wrong_role_indicators(r13("times-29328#22a")[0]))
check("indicators swapped between an anagram and a charade are counted (UNSPORTSMANLIKE)", 1,
      v.wrong_role_indicators(r13("times-29578#26a")[0]))
check("an unchecked cycling that moves one letter to the front is not cycling (RHEAS)", 1, v.fake_parts(r13("times-28709#22d")[0]))
wp, clue, ans = r13("azed-1946#17a")
check("a leaf's words inside the reversal indicator are one word doing two jobs (TURNTURTLE)", 1, v.shared_indicators(wp, clue))
wp, clue, ans = r13("cryptic-30087#18a")
check("fightback is fight + back, the leaf and the indicator at once (RAW)", 0, v.shared_indicators(wp, clue))
check("rouble is R", 0, v.bare_initials(r13("cryptic-22221#25a")[0]))
for id_ in ("cryptic-21817#4d", "times-19431#2d"):
    check(f"{id_}: a step the leaf computes is not unchecked", [], v.unverified_unchecked(r13(id_)[0], r13(id_)[2]))
for id_ in ("cryptic-29063#7d", "nation-3499#8d", "cryptic-22406#1d"):
    check(f"{id_}: a compound word that carries its indicator needs no other", 0, v.unindicated_uncovered(r13(id_)[0]))
try:
    wordplay.evaluate(r13("cryptic-29305#1d")[0], "CHATEAU")
    got = "evaluates"
except wordplay.WordplayError:
    got = "fails"
check("the anagram of a linked pair gives the whole answer, not its first light (CHATEAU LAFITE)", "fails", got)
wordplay.evaluate(r13("cryptic-29305#1d")[0], "CHATEAULAFITE")

# round 14: one deletion word over two neighbouring words, a moved letter, and annotations filed without places
SAMFOO = {"op": "charade", "parts": [
    {"op": "deletion", "indicators": [{"text": "tails off"}], "parts": [{"words": "Unchanged", "gives": "SAME"}, {"gives": "E"}]},
    {"op": "deletion", "parts": [{"words": "fare", "gives": "FOOD"}, {"gives": "D"}]}]}
check("tails off cuts both neighbouring words (SAMFOO)", 0, v.unindicated_uncovered(SAMFOO))
SAMFOO["parts"][0]["indicators"] = []
check("two deletions with no indicator at all are still counted", 2, v.unindicated_uncovered(SAMFOO))
NERVE = {"op": "container", "indicators": [{"text": "advancing"}], "parts": [
    {"op": "deletion", "parts": [{"words": "Not once", "gives": "NEVER"}, {"gives": "R"}]}, {"words": "rook", "gives": "R"}]}
check("a letter the sibling puts back is an error again, Paul round 15 (NERVE)", 1, v.unindicated_uncovered(NERVE))
NATANT = {"definitions": [{"text": "Swimming", "at": 0}], "wordplay": {"op": "anagram", "indicators": [{"text": "Swimming"}],
          "parts": [{"words": "tan repeatedly", "gives": "TANTAN"}]}}
check("an indicator on the definition's words is found without places (NATANT)", 1,
      v.in_definition(NATANT, "Swimming gives you that tan repeatedly"))
ALBINO = {"op": "charade", "parts": [{"op": "deletion", "indicators": [{"text": "dropping"}], "parts": [
    {"words": "England", "gives": "ALBION"}, {"gives": "O"}]}, {"words": "ball", "gives": "O"}]}
check("a deletion whose letter a sibling leaf gives again is a moved letter (ALBINO)", 1, v.moved_letters(ALBINO))
check("a deletion whose letter no sibling gives is not", 0, v.moved_letters(
    {**ALBINO, "parts": [ALBINO["parts"][0], {"words": "ball", "gives": "X"}]}))
check("wordplay.movedLetter is a ratchet field the redo gate names", True,
      "wordplay.movedLetter" in v.BACKLOG_MARKERS and "movedLetter" in shape_queue._validator_rules())
# round 15: four borderline classes judged fine (unindicatedBare, bareInitial, reversePhrase, anaSynonym)
HAIRLESS = {"op": "deletion", "parts": [lf("far from 'irsute", "HAIRLESS"), {"gives": "H"}]}
check("an apostrophe in the leaf marks the dropped letter ('irsute)", 0, v.unindicated_uncovered(HAIRLESS))
check("the same deletion without the apostrophe is counted", 1, v.unindicated_uncovered(
    {**HAIRLESS, "parts": [lf("far from hirsute", "HAIRLESS"), {"gives": "H"}]}))
ATTEMPT = {"op": "container", "indicators": [{"text": "usurps"}], "parts": [
    {"op": "deletion", "parts": [lf("evidence", "ATTEST"), lf("society", "S")]}, lf("politician", "MP")]}
check("a container word that says one letter replaces another covers the deletion", 0, v.unindicated_uncovered(ATTEMPT))
check("a plain container word does not", 1, v.unindicated_uncovered({**ATTEMPT, "indicators": [{"text": "holds"}]}))
check("the second of a leaf's own named half or ordinal needs no indicator", 0, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"op": "nth", "parts": [lf("Labour's second", "LABOURSECOND")]}, lf("triumph", "GAIN")]}))
check("a plural possessive pick word is the leaf's own", 0, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"op": "first", "parts": [lf("Communists' initial", "C")]}, lf("rule", "ORDER")]}))
PIAF = {"op": "charade", "parts": [{"op": "first", "indicators": [{"text": "primarily"}], "parts": [lf("Proudly")]},
                                    lf("impenitent", "I"), lf("artiste", "A")]}
check("an acrostic run after a 'primarily' pick is not bare initials", 0, v.bare_initials(PIAF))
check("a pick with another indicator does not license bare initials", 1, v.bare_initials(
    {**PIAF, "parts": [{**PIAF["parts"][0], "indicators": [{"text": "starts to"}]}] + PIAF["parts"][1:2]}))
check("a leaf whose own words name the end, cut by a deletion, is not a bare initial", 0, v.bare_initials(
    {"op": "deletion", "parts": [lf("Mistake", "LAPSE"), lf("leader", "L")]}))
check("a hyphenated word whose part is the abbreviation is not a bare initial", 0, v.bare_initials(
    {"op": "charade", "parts": [lf("gravity-force", "G"), lf("canoeing", "CANOEING")]}))
check("a reverse reading that anagrams a run of the clue's words is not counted", 0, v.reverse_phrase(
    {"op": "reverse", "reading": "ALTER NATE", "parts": [lf("How to make neat")]}))
check("a reading with no such word still is", 1, v.reverse_phrase(
    {"op": "reverse", "reading": "ROUGH + HEWN", "parts": [lf("When cryptic maybe")]}))
check("the annotate prompt tells the model when reverse([words]) is refused (reversePhrase)", True,
      "reversePhrase" in open(os.path.join(os.path.dirname(__file__), "annotate_prompt.md")).read())
check("a leaf that doubles its own words by a repeat word is not a synonym", 0, v.anagram_synonyms(
    {"op": "anagram", "indicators": [{"text": "damaged"}], "parts": [lf("double-headed besom's", "BBESOM"), lf("it")]}))
check("a leaf that gives other letters is still one", 1, v.anagram_synonyms(
    {"op": "anagram", "indicators": [{"text": "damaged"}], "parts": [lf("fine ale", "PINT"), lf("it")]}))
# round 17: unindicatedBare (holder that says it holds, lone implicit op, chained cuts, swap word), anaSynonym, poolGap
SHIPS = {"op": "container", "parts": [lf("on board", "SS"), {"op": "charade", "parts": [lf("welcome", "HI"), lf("Penny", "P")]}]}
check("a holder whose words carry the container word is its own indicator (SHIPS)", 0, v.unindicated_uncovered(SHIPS))
check("a short holder whose words carry none is still bare (the tree has another indicator)", 1, v.unindicated_uncovered(
    {**SHIPS, "parts": [lf("party", "DO"), {"op": "reversal", "indicators": [{"text": "back"}], "parts": [lf("ship", "PIHS")]}]}))
check("a lone bare hidden word is the clue's own signal", 0, v.unindicated_uncovered(
    {"op": "hidden", "parts": [lf("Radio Taliban", "IOTA")]}))
check("a bare anagram beside an indicated op is still counted", 1, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"op": "anagram", "parts": [lf("Radio Taliban", "IOTA")]},
                                {"op": "reversal", "indicators": [{"text": "back"}], "parts": [lf("fish", "TUNA")]}]}))
check("a bare hidden word beside indicated ops is the setter's unsigned run", 0, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"op": "hidden", "parts": [lf("Radio Taliban", "IOTA")]},
                                {"op": "reversal", "indicators": [{"text": "back"}], "parts": [lf("fish", "TUNA")]}]}))
# round 18: unindicatedBare (paired ends, runs of picks and sounds, lone initial, root container), deletion of fodder, unchecked recompute
TERR = lambda a, b: {"op": "charade", "parts": [{"op": "first", "indicators": a, "parts": [lf("terrific", "")]}, lf("Either", "OR"),
                                                 {"op": "last", "indicators": b, "parts": [lf("terrific", "")]}]}
check("both ends of one word: the one indicator naming ends serves the twin", 0, v.unindicated_uncovered(TERR([{"text": "end of"}], [])))
check("a one-end word on a twin of the same word is a swap and stays counted", 1, v.unindicated_uncovered(TERR([{"text": "start"}], [])))
check("a lone bare initial of a word used once is the setter's unsigned initial", 0, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"op": "first", "parts": [lf("Halpern", "")]}, lf("sign of hesitation", "ER")]}))
check("a bare initial in a charade with an indicator of its own is a swap, counted", 1, v.unindicated_uncovered(
    {"op": "charade", "indicators": [{"text": "chief"}], "parts": [{"op": "first", "parts": [lf("Halpern", "")]}, lf("sign", "ER")]}))
check("a run of three sounds sharing one indicator", 0, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"op": "homophone", "indicators": [{"text": "Trumpet"}], "parts": [lf("to", "TO")]},
                                {"op": "homophone", "parts": [lf("purchase", "BUY")]}, {"op": "homophone", "parts": [lf("in place of", "FOR")]}]}))
check("an unchecked anagram whose fodder letters differ from its gives stays flagged", 1, len(v.unverified_unchecked(
    {"op": "anagram", "unchecked": True, "gives": "CANCEL", "parts": [lf("lance 100", "LANCED")]}, "CANCEL")))
check("an unchecked anagram whose fodder letters are its gives is recomputed", [], v.unverified_unchecked(
    {"op": "anagram", "unchecked": True, "gives": "CANCEL", "parts": [lf("lance 100", "LANCEC")]}, "CANCEL"))
OPAL = {"op": "deletion", "indicators": [{"text": "taken out of"}], "parts": [
    {"op": "deletion", "parts": [lf("Pop Sails", "POPSAILS"), lf("p", "P")]}, lf("s", "S")]}
check("a run of cuts under one indicated deletion needs one indicator", 0, v.unindicated_uncovered(OPAL))
BLUFFS = {"op": "container", "parts": [{"op": "deletion", "indicators": [{"text": "ousting"}], "parts": [
    lf("Tories", "BLUES"), lf("European", "E")]}, lf("fellows", "FF")]}
check("a swap word on the deletion covers the container (BLUFFS)", 0, v.unindicated_uncovered(BLUFFS))
check("a plain word on the deletion does not", 1, v.unindicated_uncovered(
    {**BLUFFS, "parts": [{**BLUFFS["parts"][0], "indicators": [{"text": "without"}]}, BLUFFS["parts"][1]]}))
check("a repeat word giving its sibling again is not a synonym (TSETSE)", 0, v.anagram_synonyms(
    {"op": "anagram", "indicators": [{"text": "torment"}], "parts": [lf("set", "SET"), lf("again", "SET")]}))
# round 19: tradedIndicator (REALALES, ADORE)
REAL = {"op": "reversal", "indicators": [{"text": "about"}], "parts": [{"op": "container", "indicators": [{"text": "knocking back"}], "parts": [
    lf("Sybil", "SEER"), lf("to sing chorus", "LALA")]}]}
check("two ops trading indicator words are counted (REALALES)", 2, v.traded_indicators(REAL))
check("each on its own op is not", 0, v.traded_indicators(
    {"op": "reversal", "indicators": [{"text": "knocking back"}], "parts": [{"op": "container", "indicators": [{"text": "about"}], "parts": [
        lf("Sybil", "SEER"), lf("to sing chorus", "LALA")]}]}))
ADORE = {"op": "reversal", "indicators": [{"text": "masks"}], "parts": [{"op": "hidden", "indicators": [{"text": "up"}], "parts": [
    lf("superhero darning", "ERODA")]}]}
check("a hidden word on a reversal's word with an unknown reversal word is counted (ADORE)", 1, v.traded_indicators(ADORE))
check("round 21: unindicatedBare is a warning, not a gated or ratcheted rule", (False, False),
      ("unindicatedBare" in shape_queue.gated(), "wordplay.unindicatedBare" in v.BACKLOG_MARKERS))
check("round 21: azed and genius are exempt, times is not", (True, True, False),
      (shape_queue.exempt("azed-1734"), shape_queue.exempt("genius-100"), shape_queue.exempt("times-1")))
# round 22: charadeOrder (DODGE), reversalSplit (DEGAS), cutInLeaf (IDEA)
DODGE = {"op": "charade", "parts": [lf("party", "DO"), lf("Duke", "D"), {"op": "reversal", "indicators": [{"text": "flipped"}], "parts": [lf("for one", "EG")]}]}
check("pieces joined against the clue's order are counted (DODGE)", 1, v.charade_out_of_order(DODGE, "Duke flipped for one party"))
check("a joiner word between them is not (after)", 0, v.charade_out_of_order(
    {"op": "charade", "parts": [lf("party", "DO"), lf("Duke", "D")]}, "Duke after party"))
DEGAS = {"op": "reversal", "indicators": [{"text": "repelled"}], "parts": [{"op": "charade", "parts": [lf("flatulence", "SAG"), lf("editor", "ED")]}]}
check("a reversal indicator between its pieces is counted (DEGAS)", 1, v.reversal_split(DEGAS, "Painter editor repelled with flatulence"))
check("one at the edge is not", 0, v.reversal_split(
    {"op": "reversal", "indicators": [{"text": "repelled"}], "parts": [lf("editor", "ED")]}, "Painter editor repelled with flatulence"))
check("a cut word opening a leaf that gives less is counted (IDEA)", 1, v.cut_in_leaf(
    {"op": "charade", "parts": [lf("One", "I"), lf("half of deal", "DEA")]}))
check("a cut word that is a plain synonym ('short contract') is not (round 22c)", 0, v.cut_in_leaf(lf("short contract", "DEA")))
check("a leaf giving all its words is not", 0, v.cut_in_leaf(lf("short story", "SHORTSTORY")))
# round 25: wrong-scope detectors from the r23 false negatives
GLEAM = {"op": "anagram", "indicators": [{"text": "breaks"}], "parts": [lf("Male", "MALE"), {"op": "first", "indicators": [{"text": "head"}], "parts": [lf("gymnast's", "G")]}]}
check("a first-letter pick at the edge of an anagram that the answer shows outside is counted (GLEAM)", 1, v.ana_select_edge(GLEAM, "GLEAM"))
PAPA = {"op": "deletion", "indicators": [{"text": "briefly"}], "parts": [{"op": "charade", "parts": [lf("Photographer", "PAPARAZZO"), lf("a", "A")]}, {"gives": "RAZZOA"}]}
check("a deletion cutting across two charade pieces is counted (PAPA)", 1, v.del_straddle(PAPA))
check("a deletion cutting the last piece alone is not", 0, v.del_straddle(
    {"op": "deletion", "indicators": [{"text": "briefly"}], "parts": [{"op": "charade", "parts": [lf("Photographer", "PAPARAZZO"), lf("a", "A")]}, {"gives": "A"}]}))
check("a two-word indicator whose word is also a leaf is counted (STOIC)", 1, v.ind_leaf_overlap(
    {"op": "anagram", "indicators": [{"text": "is broken"}], "parts": [lf("cot", "COT"), lf("is", "IS")]}, "Long-suffering person reveals cot is broken"))
check("a leaf opening with a link word that the rest alone gives is counted (SWAMI)", 1, v.link_in_leaf(
    {"op": "charade", "parts": [lf("in Southwest", "SW"), lf("Do I exist", "AMI")]}))
check("round 25: nonWordOperand is a warning only, the rest are gated", (True, False),
      ("nonWordOperand" in shape_queue.WARN_ONLY, "nonWordOperand" in shape_queue.gated()))
check("a warning-only rule never fails a puzzle, whatever its allowance", ([], True),
      (v.backlog_errors("x-1", [v.BARE_INITIAL, v.IND_FOLDED], {"wordplay.bareInitial": {}, "wordplay.indFolded": {}}),
       bool(v.backlog_errors("x-1", [v.SINGLE_LEAF], {"wordplay.singleLeaf": {}}))))
raise SystemExit(fails)
