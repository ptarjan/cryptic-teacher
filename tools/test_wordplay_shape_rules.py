#!/usr/bin/env python3
# Wordplay shapes that read wrongly are counted by validate_annotations under their
# own ratchet fields, and tidy_wordplay_shapes.py joins a charade inside a charade
# without changing what view() shows.
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import copy
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
check("the redo gate names a deletion scope", True, any(
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
check("a midword leaf (THED from the day) is counted", 1, v.midword_leaves(
    {"op": "charade", "parts": [{"words": "the day", "gives": "THED"}, {"words": "x", "gives": "Y"}]}))
check("a stretch on word edges is not", 0, v.midword_leaves({"op": "charade", "parts": [{"words": "up the road", "gives": "THEROAD"}]}))
check("an indicator on each is fine", 0, v.unindicated_uncovered(mids("essentially", "heart of", "inside")))
check("an adjacent pair of one selection may share one", 0, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"op": "first", "indicators": [{"text": "tops"}], "parts": [{"words": "so", "gives": "S"}]},
                                {"op": "first", "parts": [{"words": "extend", "gives": "E"}]}]}))
check("but not a pair of deletions", 1, v.unindicated_uncovered(
    {"op": "charade", "parts": [{"op": "deletion", "indicators": [{"text": "lacking"}], "parts": [{"words": "a", "gives": "AB"}, {"gives": "B"}]},
                                {"op": "deletion", "parts": [{"words": "c", "gives": "CD"}, {"gives": "D"}]}]}))
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

for field in ("unindicatedBare", "sharedIndicator", "halfLeaf", "deletionScattered", "reversePhrase",
              "bareInitial", "deletionScope", "wrongRole", "deletionInside", "nestedContainer","anagramSynonym", "misplacedIndicator", "scrambledLeaf", "arityIns", "arityOther", "delSingle", "indInLeaf", "charadeInCharade", "noIndicator", "cdefRepeat", "arity", "spanOverlap", "inDefinition",
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
raise SystemExit(fails)
