#!/usr/bin/env python3
# Does tools/wordplay.py parse every op of the one-line wordplay expression,
# give the answer's letters at every node, refuse a parse that doesn't with
# the node that broke, and does annotation.view() derive today's fields
# (type, answer, indicators' for, linkWords, blocks, assembly) from the tree?
#
#     python3 tools/test_wordplay.py
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import copy
import annotation
import wordplay as w

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else detail)

def gives(expr, answer, clue=None):
    """Parses, gives the answer, and renders back to the same tree."""
    try:
        tree = w.parse(expr, clue)
        w.evaluate(tree, answer)
        again = w.parse(w.render(tree))
        bare = w.parse(expr)
        return again == {k: v for k, v in bare.items()} or f"render {w.render(tree)!r} parses differently"
    except w.WordplayError as e:
        return str(e)

def refused(expr, answer, *words, clue=None):
    """Refused, with every one of `words` in the message."""
    try:
        w.evaluate(w.parse(expr, clue), answer)
        return "accepted"
    except w.WordplayError as e:
        return all(x in str(e) for x in words) or str(e)

OK = [
    # The plan's examples.
    ("SPINE-TINGLING", "ins<in>([burn]STING, [tree]PINE) +<under> [fish]LING"),
    ("LOOBY", "[can]LOO + del<losing>([accept]BUY, [you]U)"),
    ("DISOWN", "rev<U-turn of>([papers]ID) +<following> [broadcast]SOWN"),
    ("EBONY", "rev<going round>(hid<Some>([say no before]YNOBE))"),
    ("DEFAMATORY", "ana<Fake>([folio]F + [made]) + [a] + [conservative]TORY"),
    ("WRITE OFF", "sound<on the radio>([sardonic]WRY + [nob]TOFF, WRITEOFF)"),
    ("CULMINATES", "ana<Destroying>([climate, sun])"),
    # One per op.
    ("UNSOILED", "ana<crazy>([delusion])"),
    ("REVEL", "rev<back>([lever])"),
    ("PIECE", "sound<Sung>([harmony]PEACE, PIECE)"),
    ("MADNESS", "rev<back>(hid<concealing>([Lunatics send a message]))"),
    ("LEVER", "hid<in>([travel everywhere])"),
    ("SALVO", "first<originally>([symbol]) + ana<broken>([oval])"),
    ("STOMACH", "ins<in>([pouch]SAC, [turkey]TOM) + first<head>([hen's])"),
    ("TWO AND TWO", "ana<to be molded>(middle<At heart>([metal]) + [wood] + [want])"),
    ("PARODIED", "ana<clumsily>(del<after the start>([Harpo], H)) + [did not get laughs]DIED"),
    ("FLUTTERBY", "spoon<Spooner's>([butter]BUTTER, [fly]FLY)"),
    ("CROW", "spoon<Spooner's>([bed]BED, [knob]KNOB, CROW)"),
    # A composite anagram: the fodder is the answer plus the letters named.
    ("DERTH", "comp<Sadly>([thirsted], [it's])"),
    ("BISK", "comp<possibly>([This is baked], [tea dish]TEADISH)"),
    # A reverse clue: the answer's pieces build the clue's words.
    ("OUTSTEP", 'reverse([What makes pets], "OUT + STEP")'),
    ("NIP IN", "pal<works either way>([Ulster]NI + [fix]PIN)"),
    ("ABBA", "pal<Reversible>()"),
    # A repeat: the leaf gives one copy, rep doubles it.
    ("ALFALF", "rep<called twice>([boy]ALF)"),
    ("DODO", "rep<twice>(first<originally>([died out]))"),
    ("INDIANROPETRICK", "ana<fancy>([Prank] + [no credit] + rep<repeatedly>([I]I))"),
    ("TUTUS", "rep<twice>([dancer]TU) + [plural]S"),
    ("SIEVE", "[special]S + [one]I + pal<reflective>([woman]EVE)"),
    ("BOAT", "sub<for>([coat], C, B)"),
    ("COTS", "sub<swaps>([cats], A, O)"),
    ("EARTH", "cyc<moving head to tail>([heart])"),
    ("TOE", "T + outer<edges of>([obstinate])"),
    ("DL", "alt<regularly>([oddly])"),
    ("KTDW", "regular<every third>([unknotted saw])"),
    ("E", "last<finally>([the])"),
    ("TA", "first<initially>([taken aback])"),
    ("T", "nth(3)<third letter of>([oat])"),
    ("OAT", "nth(2)<second letters of>([how fat it])"),
    ("RED HERRING", "cd([Something fishy])"),
    # Nesting.
    ("HEDGE FUND", "ins<in>([high definition]HD, [fringe]EDGE + [entertainment]FUN)"),
    ("IMPULSE", "ins<at the core of>(ana<explosion>([simple]), [uranium]U)"),
    ("FRANCIS POULENC", "FRANCIS + ins<embracing>(ana<Odd>([couple]), [Northern]N)"),
    ("STAR", "rev<up>(ins<about>([rs]RS, [at]AT))"),
    ("STAR", "rev<over>(RA + [ts]TS)"),
    ("DISOWN", "(rev([papers]ID)) + [broadcast]SOWN"),
    # Apostrophes, accents and linked answers: only the letters are checked.
    ("CAT-O'-NINE-TAILS", "[pet]CAT + [old]O + [number]NINE + [narratives]TAILS"),
    ("CAFÉ", "ana<at sea>([face])"),
    ("JOHN PAUL JONES", "JOHNPAUL + [addiction]JONES"),
    # A deletion may take out scattered letters, each given, in order (quiptic-834 4d).
    ("EQUAL", "del<going out>([Equably], [by]BY)"),
    # A deletion may name several pieces, taken out one after another (cyclops-583 17a).
    ("BADASS", "ana(del<minus>([bastards]BASTARDS, [T]T, [R]R))"),
    ("ASADS", "del<minus>([bastards]BASTARDS, [B]B, [T]T, [R]R)"),
    # A reversal turns round only the stretch its indicators name (azed-1806 25d).
    ("KARST", "rev<last pair of>([mini vehicles]KARTS)"),
    ("TSAR", "rev<turns head>([top of bill]STAR)"),
]
for answer, expr in OK:
    r = gives(expr, answer)
    check(f"{answer}: {expr}", r is True, r)

BAD = [
    ("a wrong leaf names its letters", "LOOBY", "[can]LOO + del<losing>([accept]BUY, [you]Y)",
     "gives BU", "needs BY"),
    ("DI before a reversal: a leaf gives its letters before the op", "DISOWN",
     "rev([papers]DI) + [broadcast]SOWN", "[papers]DI already reads DI", "[papers]ID inside rev()"),
    ("DI with no reversal is told to add one", "DISOWN", "[papers]ID + [broadcast]SOWN", "ID reads backwards", "rev<"),
    ("letters short", "DEFAMATORY", "ana([folio]F + [made]) + [a] + [conservative]TOR", "9 letters against 10"),
    ("anagram short of a letter", "UNSOILED", "ana<crazy>([delusio])", "lacks N"),
    ("an anagram that changes nothing", "OVAL", "ana<broken>([oval])", "no anagram"),
    ("an anagram over an insertion that can already spell it in order", "SEMIBREVE",
     "ana<off>([house]SEMI + ins<around>([beer]BREE, [five]V))", "no anagram"),
    ("a composite anagram whose fodder lacks a letter", "DEATH", "comp<Sadly>([thirsted], [it's])", "lacks A"),
    ("a composite anagram with nothing taken out", "DERTH", "comp<Sadly>([dearth], [it's])", "to spare"),
    ("a reverse clue read as one piece", "OUTSTEP", 'reverse([What makes pets], "OUTSTEP")', "two or more"),
    ("a reverse clue whose pieces spell something else", "OUTSTEP", 'reverse([What makes pets], "OUT + PETS")', "not the answer"),
    ("a reverse clue inside a charade", "OUTSTEP", 'reverse([What makes], "OUT") + [pets]STEP', "whole wordplay"),
    ("a repeat of a piece that is not the answer's half", "ALFALF", "rep<twice>([boy]AL)", "gives ALAL"),
    ("a repeat of an odd-length answer", "ALFAL", "rep<twice>([boy]AL)", "needs ALFAL"),
    ("a reversal of a palindrome", "LEVEL", "rev<back>([level])", "reads the same backwards"),
    ("not hidden", "LEVER", "hid<in>([trap ever])", "needs LEVER"),
    ("hidden letters not in the words", "LEVER", "hid<in>([trap ever]LEVER)", "gives nothing"),
    ("a container that can't fit", "STOMACH", "ins<in>([turkey]TOM, [pouch]SAC) + first<head>([hen's])", "needs"),
    ("an anagram whose order nothing fixes", "ALE", "del<losing>(ana<mad>([leap]), P)", "write the letters"),
    ("homophone spelt wrong", "PIECE", "sound<Sung>([harmony]PEACE, PEACE)", "needs PIECE"),
    ("a palindrome that isn't one", "NIPINS", "pal<either way>([Ulster]NI + [fix]PINS)", "does not read the same"),
    ("an answer alone that isn't a palindrome", "ABBY", "pal<Reversible>()", "ABBY does not read the same"),
    ("scattered letters taken out in the wrong order", "EQUAL", "del<going out>([Equably], [yb]YB)", "gives nothing"),
    ("scattered letters taken out that leave another word", "EQUIL", "del<going out>([Equably], [by]BY)", "gives EQUAL"),
    ("a stretch of the wrong size reversed", "KARST", "rev<last three of>([mini vehicles]KARTS)", "needs"),
    ("a stretch from the wrong end reversed", "KARST", "rev<first pair of>([mini vehicles]KARTS)", "needs"),
    ("an indicator naming no stretch turns the whole word", "KARST", "rev<flip>([mini vehicles]KARTS)", "needs"),
    # book-24021 5D: the fodder's del gives nothing, which crashed diagnose()
    # with "min() iterable argument is empty" instead of naming the del.
    ("anagram fodder whose del finds no run", "NARCOTIC",
     "ana<Unexpected>(del<ruled out>([contraction]CONTRACTION, [not]NOT))",
     "gives nothing", "in order", "del(del("),
]
for name, answer, expr, *words in BAD:
    r = refused(expr, answer, *words)
    check(name, r is True, r)

def perr(expr, *words, clue=None):
    try:
        w.parse(expr, clue)
        return "parsed"
    except w.WordplayError as e:
        return all(x in str(e) for x in words) or str(e)

for name, expr, words, clue in [
    ("unknown op", "anna([x])", ["unknown op 'anna'", "ana"], None),
    ("unclosed bracket", "ana([x)", ["no closing ']'"], None),
    ("ins with one part", "ins([a]A)", ["ins(outer, inner)"], None),
    ("sound with no spelling", "sound([a]A)", ["sound(x, SPELT)"], None),
    ("trailing text", "[a]A [b]B", ["after the expression"], None),
    ("empty", "", ["empty"], None),
    ("words not in the clue", "ana<crazy>([delusions])", ["'delusions' is not in the clue"],
     "Immaculate? That's a crazy delusion"),
    ("a repeat that isn't there", "[in#3]IN", ["has 2 copies", "no copy #3"], "Tea in cup in a hurry"),
    ("gapped words name the clue's own run", "rev<swaps for>([x]X)",
     ["'swaps daughter for'", "'swaps', 'for'"], "Country fellow swaps daughter for piano!"),
    ("a reordering that two runs fit", "[b a]X", [], "a b c a b"),
    ("#n mid-quote with two different marks", "[ugly#2 this#3]X", ["no copy #3"],
     "This is ugly, terribly ugly this around"),
]:
    r = perr(expr, *words, clue=clue)
    check(f"parse refuses: {name}", r is True, r)

t = w.parse("[Trump's sidekick]X", "Force on Trump’s sidekick")
check("a curly apostrophe in the clue matches a straight one", t["words"] == "Trump’s sidekick", t)

# `at` from the clue: whole words first, #n for a repeat, clear of definitions.
clue = "Tea in cup in a hurry"
t = w.parse("[in#2]IN + [a]A", clue)
check("#2 picks the second copy", t["parts"][0]["at"] == 11 and t["parts"][0]["words"] == "in", t)
check("a is the word, not the letter in Tea", t["parts"][1]["at"] == 14, t)

tree = w.translate({"wp": "JOHNPAUL + [addiction]JONES",
                    "notes": {"JOHNPAUL": "a pope", "addiction": "slang for a craving"}},
                   "Naval war hero's addiction", "JOHN PAUL JONES")
check("translate puts notes on leaves and bare pieces",
      tree["parts"][0].get("note") == "a pope" and tree["parts"][1].get("note") == "slang for a craving", tree)
try:
    w.translate({"wp": "[a]A", "notes": {"b": "x"}}, "a", "A")
    check("a note naming no span is refused", False, "accepted")
except w.WordplayError as e:
    check("a note naming no span is refused", "name no span" in str(e), str(e))
tree = w.translate({"wp": "[a]A", "notes": {"a": "the letter", "frail numb": "stray"}}, "a", "A")
check("a stray note when every span has one is dropped", "the letter" in str(tree) and "stray" not in str(tree), tree)

# A repeat counts copies without regard to case: the clue's first "Fruit" is a copy.
t = w.parse("[fruit]APPLE + [fruit#2]PEAR", "Fruit fly turning peeled fruit")
check("#2 counts a capitalised first copy", [p["at"] for p in t["parts"]] == [0, 25], t)
# A note keyed by the span's words apart from case or punctuation lands on it; an
# ambiguous key stays refused and the refusal lists the spans still free.
tree = w.translate({"wp": "[Tea]T + [in]IN", "notes": {"tea,": "a drink"}}, "Tea in", "TIN")
check("a note key differing in case/punctuation is re-keyed", tree["parts"][0].get("note") == "a drink", tree)
try:
    w.translate({"wp": "[a]A + [b]B", "notes": {"zzz": "x"}}, "a b", "AB")
    check("an unmatched note lists the free spans", False, "accepted")
except w.WordplayError as e:
    check("an unmatched note lists the free spans", "'a'" in str(e) and "'b'" in str(e), str(e))

# Bare letters that spell a clue word the clue prints once and nothing else covers get that
# word quoted (real 'a block with no clueFragment' refusals: AND, HAT, WALL, CAGE, YEARNING,
# DASH, MIDDAY, annotate audit 10-24/25); anything less sure stays bare and refused.
def quoted(wp, clue, answer, taken=()):
    t = w.translate({"wp": wp, "notes": {}}, clue, answer, taken)
    return [(p.get("words"), p.get("gives")) for p in t["parts"]]


check("a bare AND is the clue's 'and'",
      quoted("[Tea]T + AND + [cup]CUP", "Tea and cup", "TANDCUP") == [("Tea", "T"), ("and", "AND"), ("cup", "CUP")],
      quoted("[Tea]T + AND + [cup]CUP", "Tea and cup", "TANDCUP"))
check("a bare run of two words is the words",
      quoted("[Tea]T + BITPART", "Tea bit part", "TBITPART")[1] == ("bit part", "BITPART"))
check("two copies of the word stay bare", quoted("[Tea]T + AND + [cup]CUP", "Tea and cup and", "TANDCUP")[1][0] is None)
check("a word the definition covers stays bare",
      quoted("[Tea]T + AND + [cup]CUP", "Tea and cup", "TANDCUP", [(4, 7)])[1][0] is None)
check("a two-letter bare piece stays bare", quoted("[Tea]T + IN + [cup]CUP", "Tea in cup", "TINCUP")[1][0] is None)
check("letters not in the clue stay bare", quoted("[Tea]T + AND + [cup]CUP", "Tea cup or", "TANDCUP")[1][0] is None)

# Notes keyed by several free spans' words joined, or a phrase round one span
# (real 'name no span' refusals, annotate audit 10-24/25); unrelated keys stay.
def rekeyed(wp, clue, notes):
    t = w.parse(wp, clue)
    left = dict(notes)
    w._rekey(left, t)
    return [(s[k], s.get("note")) for s, k in w._spans(t, True)], sorted(left)


got, left = rekeyed("[ultimately]U + [averse]A", "Ultimately averse", {"ultimately averse": "x"})
check("a joined key lands on each span", got == [("Ultimately", "x"), ("averse", "x")] and not left, got)
got, left = rekeyed("ins<within><separately>([Study], [academics])", "Study academics separately within",
                    {"separately within": "n"})
check("a joined indicator key in the other order lands on both", [n for _, n in got][:2] == ["n", "n"] and not left, got)
got, left = rekeyed("[Labour]L + [x]X", "Labour leader x", {"Labour leader": "n"})
check("a phrase round one free span lands on it", got[0] == ("Labour", "n") and not left, got)
got, left = rekeyed("[Winter]W", 'An extract from "If Winter Comes"', {'An extract from "If Winter Comes"': "n"})
check("a quoted phrase round one span lands on it", got == [("Winter", "n")] and not left, got)
got, left = rekeyed("[asthma]A", "asthma", {"Bill": "n"})
check("an unrelated key stays refused", left == ["Bill"] and got == [("asthma", None)], got)
got, left = rekeyed("[raspberry]R + [raspberry#2]S", "raspberry and raspberry", {"edges of raspberry": "n"})
check("a phrase round two copies is ambiguous", left == ["edges of raspberry"], got)
got, left = rekeyed("[a]A + [guy]G", "a guy", {"in a guy x": "n"})
check("a joined key with extra words stays refused", left == ["in a guy x"], got)
got, left = rekeyed("[a]A + [x]X", "a to x", {"a gold bar": "n"})
check("a link word alone is not a phrase's span", "a gold bar" in left, got)

# Quote-not-in-clue mends, from real refusals (annotate audit 10-24/25).
def spans_of(wp, clue):
    t = w.parse(wp, clue)
    return [(s[k], s.get("at")) for s, k in w._spans(t)]


# '#2' on a word the clue prints once: the only copy.
check("#2 on a single copy takes it", spans_of("[revolutionaries#2]X",
      "However, two revolutionaries may be killed") == [("revolutionaries", 13)])
check("a repeat counts whole words, so a lone 'a' takes it", spans_of("[a#2]A", "Animal inhabiting a region of Spain")
      == [("a", 18)])
check("reordered words with other words after", spans_of("[who in Paris]X", "Traitor in Paris who attracts support")
      == [("in Paris who", 8)])
# '#n' inside the quote, not at its end.
check("inner #2 is moved to the quote's copy", spans_of("[Greek#2 goddess]X", "Old Greek bronze captures Greek goddess, almost entirely")
      == [("Greek goddess", 26)])
check("inner #2 on a once-printed run takes it", spans_of("[Test#2 for one]X", "Test papers? Test for one cabbie")
      == [("Test for one", 13)])
check("inner #2 on every word picks the second run",
      spans_of("[guy#2 at#2 St#2 Andrews]X", "Guy at St Andrews? Liberal guy at St Andrews, not Conservative")
      == [("guy at St Andrews", 27)])
# The clue's order for the same words.
check("reordered words take the clue's run", spans_of("[read intensively]X", "Particular sketch intensively read by Brad, say")
      == [("intensively read", 18)])
check("reordered words with punctuation", spans_of("[flambé, perhaps]X", "Fifty tucking into meat, perhaps flambé, visible in the dark")
      == [("perhaps flambé", 25)])
# A definition 'talk#2' is the second copy of 'talk' (real clue); a lone copy is taken.
import definitions as D
placed = D.place([{"text": "talk#2"}], "Religious leader beginning to talk and talk")
check("a definition's #2 picks the second copy", placed[0]["text"] == "talk" and placed[0]["at"] == 39, placed)
placed = D.place([{"text": "reptile#2"}], "Roll reptile over eating lake reptile")
check("a definition's #2 on the clue's last word", placed[0]["at"] == 30, placed)
# A split indicator written with an ellipsis is two indicators.
tree = w.translate({"wp": "ins<putting ... into>([Go wrong]AB, [last message]CD)"},
                   "Go wrong, putting last message into place", "ACDB")
check("'a ... b' indicator splits into two",
      [i["text"] for i in tree.get("indicators") or []] == ["putting", "into"], tree)

# A selection whose leaf holds the pick, not the words it picks from (a third of the
# 'does not give' refusals in the annotate audit): translate drops the leaf's letters.
tree = w.translate({"wp": "[German agreement]JA + alt<regularly ignored>([most]MS)"},
                   "German agreement most regularly ignored", "JAMS")
check("translate drops a leaf's letters that are already its selection's pick",
      "gives" not in tree["parts"][1]["parts"][0], tree)
tree = w.translate({"wp": "rev<picked up>(alt<on odd occasions>([Hotel niff]HTLIF))"},
                   "Hotel niff on odd occasions picked up", "FILTH")
check("a written pick under a reversal is dropped too", "HTLIF" not in str(tree), tree)
tree = w.translate({"wp": "last<end of>([dog]CUR) + [eat]ATE"}, "End of dog eat", "RATE")
check("a synonym the selection picks from keeps its letters", "CUR" in str(tree), tree)
try:
    w.translate({"wp": "alt<regularly>([most]MS)"}, "most regularly", "MO")
    check("a written pick that still misses the answer stays refused", False, "accepted")
except w.WordplayError as e:
    check("a written pick that still misses the answer stays refused",
          "does not give MO" in str(e) and "[most]MS" in str(e), str(e))

# A possessive 's on bare words under a selection is the clue's, not the word's:
# "Observer's last" is R (110 of 810 sampled refusals).
check("last<>([Observer's]) is R", gives("last<last>([Observer's]) + [article]AN", "RAN") is True,
      gives("last<last>([Observer's]) + [article]AN", "RAN"))
check("outer<>([Calypso's]) is CO", gives("outer<exterior>([Calypso's])", "CO") is True,
      gives("outer<exterior>([Calypso's])", "CO"))
check("the 's still counts when the pick takes it", gives("last<last>([Observer's])", "S") is True)

# A two-piece charade written in clue order under an 'after' indicator (57 of 390 distinct
# refusals in 30h): MP after CHA is CHA + MP, and translate swaps the pieces.
tree = w.translate({"wp": "[Politician]MP +<after> [tea]CHA"}, "Politician after tea sees winner", "CHAMP")
check("a charade written in clue order under 'after' is swapped to answer order",
      [p["gives"] for p in tree["parts"]] == ["CHA", "MP"], tree)
tree = w.translate({"wp": "[tea]CHA +<after> [Politician]MP"}, "Politician after tea sees winner", "CHAMP")
check("a charade already in answer order is left alone",
      [p["gives"] for p in tree["parts"]] == ["CHA", "MP"], tree)
try:
    w.translate({"wp": "[Politician]MP +<with> [tea]CHA"}, "Politician with tea sees winner", "CHAMP")
    check("a non-placement indicator is not swapped", False, "accepted")
except w.WordplayError as e:
    check("a non-placement indicator is not swapped", "does not give CHAMP" in str(e), str(e))
try:
    w.translate({"wp": "[Politician]MP +<after> [tea]CHA"}, "Politician after tea sees winner", "CHAMPS")
    check("an 'after' charade that is wrong both ways stays refused", False, "accepted")
except w.WordplayError as e:
    check("an 'after' charade that is wrong both ways stays refused",
          "does not give CHAMPS" in str(e), str(e))

# ---------- annotation.view against stored annotations ----------
# Real clues (nation-3289, as filed), each written as a tree; the fields the
# tree implies must equal the stored ones. Notes are left out of the trees and
# out of the comparison except for the double definition's.
def entry(number, direction, solution, clue, seps=(), **kw):
    e = {"number": number, "direction": direction, "solution": solution,
         "clue": {"text": clue, **({"separators": [{"at": a, "mark": m} for a, m in seps]} if seps else {})}}
    e.update(kw)
    return e

def leaf(words, gives=None):
    return {"words": words, **({"gives": gives} if gives else {})}

def op(name, *parts, ind=(), **kw):
    n = {"op": name, "parts": list(parts), **kw}
    if ind:
        n["indicators"] = [{"text": t} for t in ind]
    return n

def plain_blocks(blocks):
    return [{k: v for k, v in b.items() if k != "note"} for b in blocks]

def anas(asm):
    return [{"fodder": annotation._letters(a["fodder"]), "gives": a["gives"]} for a in asm.get("anagrams", [])]

CASES = [
    (entry(1, "across", "JOHNPAULJONES", "Naval war hero's addiction", [(4, ","), (8, ",")]),
     {"definitions": [{"text": "Naval war hero", "at": 0}],
      "wordplay": op("charade", {"gives": "JOHNPAUL"}, leaf("addiction", "JONES"))},
     {"type": ["charade"], "answer": "JOHN PAUL JONES", "linkWords": ["'s"],
      "blocks": [{"gives": "JOHNPAUL"}, {"clueFragment": "addiction", "gives": "JONES"}],
      "assembly": {"pieces": ["JOHNPAUL", "JONES"]}}),
    (entry(3, "down", "PIECE", "Sung harmony in musical work"),
     {"definitions": [{"text": "musical work", "at": 16}],
      "wordplay": op("homophone", leaf("harmony", "PEACE"), ind=["Sung"], spelt="PIECE")},
     {"type": ["homophone"], "answer": "PIECE", "indicators": [{"text": "Sung", "for": "homophone"}],
      "linkWords": ["in"], "blocks": [{"clueFragment": "harmony", "gives": "PIECE", "soundsLike": "PEACE"}]}),
    (entry(4, "down", "UNSOILED", "Immaculate? That's a crazy delusion"),
     {"definitions": [{"text": "Immaculate", "at": 0}],
      "wordplay": op("anagram", leaf("delusion"), ind=["crazy"])},
     {"type": ["anagram"], "answer": "UNSOILED", "indicators": [{"text": "crazy", "for": "anagram"}],
      "linkWords": ["That's a"], "blocks": [{"clueFragment": "delusion", "gives": "DELUSION"}],
      "assembly": {"anagrams": [{"fodder": "DELUSION", "gives": "UNSOILED"}]}}),
    (entry(5, "down", "JOINTS", "Connections with cigarettes"),
     {"definitions": [{"text": "Connections", "at": 0, "meaning": "first meaning"},
                      {"text": "cigarettes", "at": 17, "meaning": "second meaning"}]},
     {"type": ["double_definition"], "answer": "JOINTS", "linkWords": ["with"],
      "blocks": [{"clueFragment": "Connections", "note": "first meaning"},
                 {"clueFragment": "cigarettes", "note": "second meaning"}]}),
    # A definition's `note` is the definitions rung's and never becomes its
    # block's note: the blocks rung comes first (times-29410 26A's note named
    # FLY BY NIGHT).
    (entry(6, "down", "JOINTS", "Connections with cigarettes"),
     {"definitions": [{"text": "Connections", "at": 0, "note": "read as JOINTS"},
                      {"text": "cigarettes", "at": 17, "meaning": "second meaning"}]},
     {"type": ["double_definition"], "answer": "JOINTS", "linkWords": ["with"],
      "blocks": [{"clueFragment": "Connections"},
                 {"clueFragment": "cigarettes", "note": "second meaning"}]}),
    (entry(7, "down", "SALVO", "Volley's symbol, originally: broken oval"),
     {"definitions": [{"text": "Volley", "at": 0}],
      "wordplay": op("charade", op("first", leaf("symbol"), ind=["originally"]),
                     op("anagram", leaf("oval"), ind=["broken"]))},
     {"type": ["letter_selection", "anagram", "charade"], "answer": "SALVO",
      "indicators": [{"text": "originally", "for": "letter_selection"}, {"text": "broken", "for": "anagram"}],
      "linkWords": ["'s"],
      "blocks": [{"clueFragment": "symbol", "gives": "S", "select": "first"}, {"clueFragment": "oval", "gives": "OVAL"}],
      "assembly": {"pieces": ["S", "ALVO"], "anagrams": [{"fodder": "OVAL", "gives": "ALVO"}]}}),
    (entry(9, "across", "MADNESS", "Lunatics send a message back, concealing mental instability"),
     {"definitions": [{"text": "mental instability", "at": 41}],
      "wordplay": op("reversal", op("hidden", leaf("Lunatics send a message"), ind=["concealing"]), ind=["back"])},
     {"type": ["hidden_word", "reversal"], "answer": "MADNESS",
      "indicators": [{"text": "back", "for": "reversal"}, {"text": "concealing", "for": "hidden_word"}],
      "blocks": [{"clueFragment": "Lunatics send a message", "gives": "SSENDAM"}],
      "assembly": {"reversals": [{"from": "SSENDAM", "to": "MADNESS"}]}}),
    (entry(10, "across", "IMPULSE", "Force of uranium at the core of simple explosion"),
     {"definitions": [{"text": "Force", "at": 0}],
      "wordplay": op("container", op("anagram", leaf("simple"), ind=["explosion"]), leaf("uranium", "U"),
                     ind=["at the core of"])},
     {"type": ["anagram", "container"], "answer": "IMPULSE",
      "indicators": [{"text": "at the core of", "for": "container"}, {"text": "explosion", "for": "anagram"}],
      "linkWords": ["of"],
      "blocks": [{"clueFragment": "simple", "gives": "SIMPLE"}, {"clueFragment": "uranium", "gives": "U"}],
      "assembly": {"pieces": ["IMP", "U", "LSE"], "anagrams": [{"fodder": "SIMPLE", "gives": "IMPLSE"}]}}),
    (entry(15, "down", "TWOANDTWO", "At heart, metal and wood want to be molded — you might put them together",
           [(3, ","), (6, ",")]),
     {"definitions": [{"text": "you might put them together", "at": 45}],
      "wordplay": op("anagram", op("charade", op("middle", leaf("metal"), ind=["At heart"]), leaf("wood"),
                                   leaf("want")), ind=["to be molded"])},
     {"type": ["letter_selection", "anagram"], "answer": "TWO AND TWO",
      "indicators": [{"text": "At heart", "for": "letter_selection"}, {"text": "to be molded", "for": "anagram"}],
      "linkWords": ["and"],
      "blocks": [{"clueFragment": "metal", "gives": "T", "select": "middle"},
                 {"clueFragment": "wood", "gives": "WOOD"}, {"clueFragment": "want", "gives": "WANT"}],
      "assembly": {"anagrams": [{"fodder": "TWOODWANT", "gives": "TWOANDTWO"}]}}),
    (entry(16, "down", "PARODIED", "Imitated Harpo clumsily after the start, and did not get laughs"),
     {"definitions": [{"text": "Imitated", "at": 0}],
      "wordplay": op("charade", op("anagram", op("deletion", leaf("Harpo"), {"gives": "H"}, ind=["after the start"]),
                                   ind=["clumsily"]), leaf("did not get laughs", "DIED"))},
     {"type": ["deletion", "anagram", "charade"], "answer": "PARODIED",
      "indicators": [{"text": "clumsily", "for": "anagram"}, {"text": "after the start", "for": "deletion"}],
      "linkWords": ["and"],
      "blocks": [{"clueFragment": "Harpo", "gives": "HARPO"}, {"clueFragment": "did not get laughs", "gives": "DIED"}],
      "assembly": {"pieces": ["PARO", "DIED"], "anagrams": [{"fodder": "ARPO", "gives": "PARO"}]}}),
    (entry(24, "across", "STOMACH", "Tolerate turkey in pouch, with hen's head…"),
     {"definitions": [{"text": "Tolerate", "at": 0}],
      "wordplay": op("charade", op("container", leaf("pouch", "SAC"), leaf("turkey", "TOM"), ind=["in"]),
                     op("first", leaf("hen's"), ind=["head"]))},
     {"type": ["container", "letter_selection", "charade"], "answer": "STOMACH",
      "indicators": [{"text": "in", "for": "container"}, {"text": "head", "for": "letter_selection"}],
      "linkWords": ["with"],
      "blocks": [{"clueFragment": "pouch", "gives": "SAC"}, {"clueFragment": "turkey", "gives": "TOM"},
                 {"clueFragment": "hen's", "gives": "H", "select": "first"}],
      "assembly": {"pieces": ["S", "TOM", "AC", "H"]}}),
    (entry(25, "across", "INVITRO", "…outside the body's opening, swallowing six", [(2, ",")]),
     {"definitions": [{"text": "outside the body", "at": 1}],
      "wordplay": op("container", leaf("opening", "INTRO"), leaf("six", "VI"), ind=["swallowing"])},
     {"type": ["container"], "answer": "IN VITRO", "indicators": [{"text": "swallowing", "for": "container"}],
      "linkWords": ["'s"],
      "blocks": [{"clueFragment": "opening", "gives": "INTRO"}, {"clueFragment": "six", "gives": "VI"}],
      "assembly": {"pieces": ["IN", "VI", "TRO"]}}),
]
for e, ann, want in CASES:
    name = f"view {e['solution']}"
    try:
        got = annotation.view(copy.deepcopy(ann), e)
    except w.WordplayError as x:
        check(name, False, str(x))
        continue
    # Indicators compare as a set: today's files list them in no one order.
    key = lambda xs: sorted(map(str, xs or []))
    diffs = [k for k in ("type", "answer", "linkWords") if got.get(k) != want.get(k)]
    diffs += ["indicators"] if key(got.get("indicators")) != key(want.get("indicators")) else []
    diffs += ["blocks"] if (got["blocks"] if not ann.get("wordplay") else plain_blocks(got["blocks"])) != want["blocks"] else []
    ga, wa = got.get("assembly", {}), want.get("assembly", {})
    diffs += ["assembly"] if (ga.get("pieces"), ga.get("reversals"), anas(ga)) != (wa.get("pieces"), wa.get("reversals"), anas(wa)) else []
    check(name, not diffs, "; ".join(f"{k}: got {got.get(k)!r}, want {want.get(k)!r}" for k in diffs))

# Longer spans are placed first: genius-209 22A's container "in" sits after
# the deletion "lost in" in the clue but before it in the tree, and placed in
# tree order it took the "in" of "lost in", leaving the second "in" a link word.
clue = "Short key, article lost in pilgrimage, in great journey"
t = op("charade", op("container", op("deletion", op("charade", leaf("key", "IVORY"), leaf("great", "HUGE")),
                                     {"gives": "Y"}, ind=["Short"]),
                     op("deletion", leaf("pilgrimage", "HAJ"), leaf("article", "A"), ind=["lost in"]), ind=["in"]),
       leaf("journey", "GO"))
w.locate(t, clue)
ins = t["parts"][0]
check("locate: a short span does not take a copy inside a longer one",
      ins["indicators"][0]["at"] == clue.index(", in ") + 2
      and ins["parts"][1]["indicators"][0]["at"] == clue.index("lost in"),
      (ins["indicators"], ins["parts"][1]["indicators"]))

# Two definitions beside wordplay are a double definition too: the type keeps
# both, and the definitions' own words are not link words.
e = entry(33, "across", "CLEAN", "Entirely without a catch. Circle angling will admit that")
got = annotation.view({"definitions": [{"text": "Entirely", "at": 0}, {"text": "without a catch", "at": 9}],
                       "wordplay": op("charade", leaf("Circle", "C"), leaf("angling", "LEAN"))}, e)
check("view: two definitions and wordplay are a double definition",
      got["type"] == ["double_definition", "charade"] and got["linkWords"] == ["will admit that"], got)
# An indicator on a definition is for the double definition, or the &lit
# when there is one definition; it is not a link word.
e = entry(3, "down", "STEEL", "Steel, silver, silicon or scandium, say?")
got = annotation.view({"definitions": [{"text": "Steel", "at": 0},
                                       {"text": "silver, silicon or scandium", "at": 7,
                                        "indicators": [{"text": "say", "note": "by example"}]}]}, e)
check("view: a definition's indicator is for the double definition",
      got.get("indicators") == [{"text": "say", "for": "double_definition", "note": "by example"}]
      and "linkWords" not in got and all("indicators" not in d for d in got["definitions"]), got)
e = entry(8, "across", "PLACE", "Place holding final of competition?")
got = annotation.view({"definitions": [{"text": "Place holding final of competition?", "at": 0,
                                        "indicators": [{"text": "holding"}]}],
                       "wordplay": op("charade", leaf("Place", "PLA"), leaf("competition", "CE")),
                       "andLit": True}, e)
check("view: a lone definition's indicator is for the &lit",
      {"text": "holding", "for": "and_lit"} in got.get("indicators", []), got.get("indicators"))
got = annotation.view({"definitions": [{"text": "camel-hair coat", "at": 11}],
                       "wordplay": op("palindrome", ind=["Reversible"])},
                      entry(21, "down", "ABBA", "Reversible camel-hair coat"))
check("view: a palindrome op is the palindrome type and gives no block",
      got["type"] == ["palindrome"] and got["blocks"] == []
      and got["indicators"] == [{"text": "Reversible", "for": "palindrome"}], got)

got = annotation.view({"definitions": [{"text": "bird", "at": 0}],
                       "wordplay": op("repeat", leaf("it", "DO"), ind=["twice"])},
                      entry(3, "across", "DODO", "bird, it twice"))
check("view: a repeat op is a charade-type step, its indicator filed for it and its one copy the block",
      got["type"] == ["charade"] and [b["gives"] for b in got["blocks"]] == ["DO"]
      and got["indicators"] == [{"text": "twice", "for": "charade"}], got)

check("view leaves its input unchanged", "at" not in CASES[0][1]["wordplay"]["parts"][1])

# A linked answer joins its group's lights; a mark at a light's length falls between lights.
puzzle = {"entries": [
    entry(21, "across", "VERY", "Very good, with two cases (4,4)", [(4, ",")], group=["21-across", "25-across"]),
    entry(25, "across", "GOOD", "See 21")]}
check("linked answer", annotation.display_answer(puzzle["entries"][0], puzzle) == "VERY GOOD",
      annotation.display_answer(puzzle["entries"][0], puzzle))
e = entry(1, "across", "CATONINETAILS", "x", [(3, "-"), (4, "'"), (4, "-"), (8, "-")])
check("apostrophe and hyphens from separators", annotation.display_answer(e) == "CAT-O'-NINE-TAILS",
      annotation.display_answer(e))
check("spelling overrides the separators",
      annotation.view({"spelling": "CAFÉ", "wordplay": op("anagram", leaf("face"), ind=["at sea"]),
                       "definitions": [{"text": "Bistro", "at": 0}]},
                      entry(1, "across", "CAFE", "Bistro face at sea"))["answer"] == "CAFÉ")
try:
    annotation.view({"wordplay": op("anagram", leaf("fade"), ind=["at sea"]), "definitions": [{"text": "Bistro", "at": 0}]},
                    entry(1, "across", "CAFE", "Bistro fade at sea"))
    check("view refuses a tree that misses the answer", False, "accepted")
except w.WordplayError as x:
    check("view refuses a tree that misses the answer", "CAFE" in str(x), str(x))

# cryptic-30080 17D: the setter printed (8) and the model wrote WAR PAINT. The
# displayed answer takes its breaks and hyphens from the enumeration, never
# from the model's spelling, and from_model stores no spelling for it.
wclue = "Fight coat for battle decoration"
wmodel = {"def": "battle decoration", "wp": "[Fight]WAR + [coat]PAINT", "answer": "WAR PAINT"}
for enum, seps, want in [("8", (), "WARPAINT"), ("3,5", (), "WAR PAINT"), ("3,5", [(3, ",")], "WAR PAINT"),
                         ("3-5", (), "WAR-PAINT"), ("3-5", [(3, "-")], "WAR-PAINT")]:
    e = entry(17, "down", "WARPAINT", wclue, seps)
    e["clue"]["enumeration"] = enum
    stored = annotation.from_model(dict(wmodel), e)
    check(f"({enum}) seps={list(seps)}: model WAR PAINT is no spelling", "spelling" not in stored,
          stored.get("spelling"))
    check(f"({enum}) seps={list(seps)}: view answers {want}", annotation.view(stored, e)["answer"] == want,
          annotation.view(stored, e)["answer"])
    check(f"({enum}) seps={list(seps)}: a stored WAR PAINT spelling still shows {want}",
          annotation.view({**stored, "spelling": "WAR PAINT"}, e)["answer"] == want)
e = entry(17, "down", "WARPAINT", wclue)
e["clue"]["enumeration"] = "8"
check("(8): from_model keeps no WAR PAINT spelling", "spelling" not in annotation.from_model(dict(wmodel), e))
# A charade's order word written as `+ +<after>` or a prefix `+<after>(a, b)` (annotate audit 10-24/25:
# 64 doubled '+', 73 prefix) is said the way the parser takes it; translate still checks the answer.
for was, now in [
    ("[Old]O + [baddy]RAT + +<leading>[men]OR", "[Old]O + [baddy]RAT +<leading>[men]OR"),
    ("[huge]OS + [lake]L + +<on>[Duck]O", "[huge]OS + [lake]L +<on>[Duck]O"),
    ("[mum]MA + +<to follow>(ins<hampered by>([desire]WISH, [knight]K))",
     "[mum]MA +<to follow>(ins<hampered by>([desire]WISH, [knight]K))"),
    ("+<Add>([page]P + [rental agreement]LEASE)", "([page]P +<Add> [rental agreement]LEASE)"),
    ("+<after>([signal]FLAG, [shout]RANT)", "([signal]FLAG +<after> [shout]RANT)"),
    ("+<after>([second]S + [old person]OAP, [Fight]BOX)", "(([second]S + [old person]OAP) +<after> [Fight]BOX)"),
    ("ins<in>([sweeper's]BROOM, +<leading>([Journalist]ED, [session]SITTING))",
     "ins<in>([sweeper's]BROOM, ([Journalist]ED +<leading> [session]SITTING))"),
]:
    check(f"charade indicator mend: {was}", w.mend_charade_indicator(was) == now, w.mend_charade_indicator(was))
    w.parse(now)
for ok in ["[Old]O + [baddy]RAT +<leading>[men]OR", "[a]A + [b]B", "ins<in>([a]A, [b]B)"]:
    check(f"charade indicator mend leaves {ok}", w.mend_charade_indicator(ok) is None)
# stays refused, and says how to write it: an indicator before its piece, a '+' with nothing after, a count
for bad, hint in [("ins(del<having no right>([Lord]PEER, R), <to accept>[jibe]DIG + [about]RE)", "right after the op"),
                  ("[party]CON + [appropriate]FIT +<after>", "needs the piece it joins"),
                  ("first(3)<Half of>([arbiters]JUDGES)", "take no count")]:
    check(f"charade indicator mend declines {bad[:30]}", w.mend_charade_indicator(bad) is None)
    r = perr(bad, hint)
    check(f"parse refuses with a hint: {bad[:30]}", r is True, r)
tree = w.translate({"wp": w.mend_charade_indicator("[Old]O + [baddy]RAT + +<leading>[men]OR")},
                   "Old baddy leading men", "ORATOR")
check("the mended doubled '+' gives the answer with the indicator on the charade",
      [i["text"] for i in tree.get("indicators") or []] == ["leading"], tree)
tree = w.translate({"wp": w.mend_charade_indicator("+<after>([signal]FLAG, [shout]RANT)")},
                   "Signal after shout", "RANTFLAG")
check("the mended prefix op is swapped by the answer like any 'after' charade",
      [p.get("gives") for p in tree["parts"]] == ["RANT", "FLAG"], tree)
e = entry(3, "across", "ORATOR", "Old baddy leading men is a speaker")
stored = annotation.from_model({"def": "a speaker", "wp": "[Old]O + [baddy]RAT + +<leading>[men]OR"}, e)
check("from_model mends the doubled '+' in place", stored["wordplay"]["op"] == "charade", stored)
check("apostrophe spelling survives (8)",
      annotation.spaced("DON'T", {"number": 1, "direction": "across", "clue": {"enumeration": "4"}}) == "DON'T")
check("enumeration's apostrophe is not doubled",
      annotation.spaced("DON'T", {"number": 1, "direction": "across", "clue": {"enumeration": "3'1"}}) == "DON'T")
check("no enumeration leaves the spacing",
      annotation.spaced("WAR PAINT", {"number": 1, "direction": "across", "clue": {}}) == "WAR PAINT")

import series
for pid, extra, want in [
    ("times-29000", {}, "Times cryptic crossword No 29,000"),
    ("nation-3289", {}, "The Nation cryptic crossword No 3289"),
    ("toughie-3224", {}, "Telegraph Toughie No 3,224"),
    ("cryptic-30134", {"prize": True}, "Prize crossword No 30,134"),
    ("listener-3999", {"title": "Tobacco"}, "Listener crossword No 3,999: Tobacco"),
    ("canberra-920427", {"label": "English cryptic"},
     "Canberra Times cryptic crossword, Monday 27 April 1992 (English cryptic)"),
]:
    got = series.display_name({"id": pid, **extra})
    check(f"display_name {pid}", got == want, f"got {got!r}")

# independent-11469 21D: a checked tree whose top op is a deletion builds the
# answer in one chunk, so view() gives no assembly.pieces. The validator must
# not ask for `assembly`: the schema refuses the key, so a run that obeyed
# "Give `assembly.pieces`" had its next write refused (one extra turn).
import validate_annotations as va
screed = entry(21, "down", "SCREED", "Long document's ruined week off")
screed["clue"]["enumeration"] = "6"
screed["annotation"] = {
    "definitions": [{"text": "Long document", "at": 0}],
    "wordplay": {"op": "deletion", "indicators": [{"text": "off", "at": 28, "note": "taken away"}],
                 "parts": [{"words": "ruined", "at": 16, "gives": "SCREWED", "note": "slang for ruined"},
                           {"words": "week", "at": 23, "gives": "W"}]}}
_, errs, warns = va.validate_puzzle({"id": "test-1", "entries": [screed]})
check("a checked deletion tree is not asked for assembly.pieces",
      not [x for x in warns if "machine-checkable" in x or "assembly.anagrams" in x], warns)
check("the deletion tree evaluates (no wordplay error)",
      not [x for x in errs if "wordplay" in x], [x for x in errs if "wordplay" in x])

# A stored tree with the wrong number of parts is a clean WordplayError, not a crash.
def refused(tree, answer):
    try:
        w.evaluate(tree, answer)
    except w.WordplayError as e:
        return str(e)
    except Exception as e:
        return f"CRASH {type(e).__name__}: {e}"
    return "evaluated"
leaf = lambda x, g=None: {"words": x, "gives": g or x.upper()}
for name, tree in [
    ("a container with one part", {"op": "container", "parts": [leaf("ab")]}),
    ("a deletion with ten parts", {"op": "deletion", "parts": [leaf("ab")] + [leaf("a")] * 9}),
    ("a deletion with one part", {"op": "deletion", "parts": [leaf("ab")]}),
    ("a substitution with four parts", {"op": "substitution", "parts": [leaf("ab"), leaf("a"), leaf("b"), leaf("c")]}),
    ("a reversal with none", {"op": "reversal"}),
    ("a nested bad count", {"op": "charade", "parts": [leaf("a"), {"op": "container", "parts": [leaf("b")]}]}),
]:
    r = refused(tree, "AB")
    check(f"{name} is a WordplayError naming the count", r.startswith(("(", "")) and "part(s)" in r and "CRASH" not in r, r)
# One op per indicator: first(A, B) over a list is the first letter of each piece (AC here),
# so it is a clean refusal when the answer differs, and evaluates when it matches.
_r = refused({"op": "first", "parts": [leaf("ab"), leaf("cd")]}, "AB")
check("a first over two pieces is the first letter of each, refused cleanly",
      "does not give" in _r and "CRASH" not in _r, _r)
check("a first over two pieces gives AC", refused({"op": "first", "parts": [leaf("ab"), leaf("cd")]}, "AC") == "evaluated")
_r = refused({"op": "anagram", "parts": [{"op": "deletion", "parts": [leaf("ab"), leaf("x"), leaf("y")]}]}, "AB")
check("a failing three-piece deletion under an anagram is diagnosed, not a crash",
      "gives nothing" in _r and "CRASH" not in _r, _r)
check("an unchecked node with a wrong count is left alone",
      refused({"op": "container", "unchecked": True, "gives": "AB", "parts": [leaf("ab")]}, "AB") == "evaluated")

# Selections of a stretch, from a run of the leaf's words, every other pair.
def _sel(op, words, answer, pre=None, n=None):
    node = {"op": op, "parts": [{"words": words}]}
    if n:
        node["n"] = n
    tree = {"op": "charade", "parts": ([pre] if pre else []) + [node]}
    return refused(tree, answer) == "evaluated"
check("first two letters of a word (40% of Truro)", _sel("first", "Truro", "TR"))
check("first stretch can not be the whole answer wrongly", not _sel("first", "Truro", "TU"))
check("last stretch of a word", _sel("last", "Plymouth", "OUTH"))
check("centred stretch (ACHE from teachers)", _sel("middle", "teachers", "ACHE"))
check("an off-centre stretch is no middle", not _sel("middle", "teachers", "TEAC"))
check("outer pair of letters", _sel("outer", "city", "CY"))
check("odd couples of Decrepit", _sel("regular", "Decrepit", "DEEP"))
check("regularly discarded letters (LUBE from plumber)", _sel("regular", "Plumber", "LUBE"))
check("nth of each word in a run, indicator word riding along", _sel("nth", "seconds of blancmange and jelly", "LE", n=2))
check("alternate letters", _sel("alternate", "true", "TU"))
check("a wrong alternate fails", not _sel("alternate", "true", "TR"))
_mo = {"op": "reversal", "parts": [{"op": "charade", "parts": [leaf("mo"), leaf("c"), leaf("ha")]}]}
check("a reversal of MO+C+HA is not MOCHA", "does not give" in refused(_mo, "MOCHA"), refused(_mo, "MOCHA"))

# A spoonerism filed as one leaf with the phrase before the swap (soundsLike), a centre
# substitution filed as two parts, and the selections the unchecked-step sweep met.
def _spoon1(sounds, answer):
    return {"op": "spoonerism", "parts": [{"words": "x y", "gives": answer, "soundsLike": sounds}]}
check("a one-leaf spoon by sound (HAD MATTER -> MADHATTER)", refused(_spoon1("HAD MATTER", "MADHATTER"), "MADHATTER") == "evaluated")
check("a one-leaf spoon by sound (BEST GEAR -> GUESTBEER)", refused(_spoon1("BEST GEAR", "GUESTBEER"), "GUESTBEER") == "evaluated")
check("a one-leaf spoon whose answer is not the swap", "does not give" in refused(_spoon1("HAD MATTER", "BUTTERPAT"), "BUTTERPAT"))
check("a one-leaf spoon with no soundsLike is a part count",
      "part(s)" in refused({"op": "spoonerism", "parts": [leaf("ab")]}, "AB"))
def _written(expr):
    try:
        w.parse(expr)
    except w.WordplayError:
        return False
    return True
check("a one-part spoon and a two-part sub are stored forms, not written ones",
      not _written("spoon([a]A)") and not _written("sub([ab]AB, [a]A)"))
check("sub of the centre, x then new (CADIZ, P -> CAPIZ)",
      refused({"op": "substitution", "parts": [leaf("port", "CADIZ"), leaf("peso", "P")]}, "CAPIZ") == "evaluated")
check("sub of the centre, new then x (VISOR in EYE)",
      refused({"op": "reversal", "parts": [{"op": "substitution", "parts": [leaf("face protection", "VISOR"), leaf("eye")]}]},
              "EROSIVE") == "evaluated")
check("sub of the centre must give the answer",
      "does not give" in refused({"op": "substitution", "parts": [leaf("port", "CADIZ"), leaf("peso", "P")]}, "CADPZ"))
check("alternate letters of a run stopping short (Does Joan vouch -> DEJAVU)", _sel("alternate", "Does Joan vouch", "DEJAVU"))
check("a short alternate is not trimmed", not _sel("alternate", "true", "T"))
_last = {"op": "last", "parts": [{"words": "Durham's", "gives": "AM", "select": "last"}]}
check("a leaf that names its pick, possessive 's dropped (Durham's -> AM)",
      refused({"op": "container", "parts": [leaf("cricket match", "TEST"), _last]}, "TAMEST") == "evaluated")

def wp_refused(expr, answer, *words):
    """A written expression refused, with every one of `words` in the message."""
    try:
        w.evaluate(w.parse(expr), answer)
        return "accepted"
    except w.WordplayError as e:
        return all(x in str(e) for x in words) or str(e)


# A selection over a `+` list works on the joined letters; the refusal names the comma form
# (ftcryptic-18509 KHAKI, ftcryptic-18319 FUEGO from the annotate audit).
check("first over a + list names the comma form",
      wp_refused("first<initially>([kept] + [here] + [as] + [knitting] + [is])", "KHAKI",
              "first<initially>([kept], [here], [as], [knitting], [is])"))
check("first over a + list with a gives leaf names the comma form",
      wp_refused("first<leaders for>([frustrating] + [USA's] + [excessively] + [gung-ho] + [operation])", "FUEGO",
              "first<leaders for>([frustrating], [USA's], [excessively], [gung-ho], [operation])"))
check("comma form passes", gives("first<initially>([kept], [here], [as], [knitting], [is])", "KHAKI"))
check("a + list that no comma form fixes still says commas apply to each word",
      wp_refused("middle<Central parts of>([Slough] + [utterly])", "ABCD", "commas apply it to each word"))
check("hid over a + list says one leaf", wp_refused("hid<in>([peril] + [I'll])", "LILLE", "hid() takes one leaf"))
check("hid over a + list names the merged leaf",
      wp_refused("hid<in>([peril] + [I'll])", "RILL", "hid<in>([peril I'll])"))

# A spoonerism with sound() inside: spoon swaps the starts itself and takes the spelling heard.
check("spoon of sound() pieces names spoon(a, b, SPELT)",
      wp_refused("spoon<Spooner's>(sound([destiny]FATE, HATE), sound([coastal city]HULL, FUL))", "HATEFUL",
              "spoon<Spooner's>([destiny]FATE, [coastal city]HULL, HATEFUL)"))
check("spoon of sound() FERRYMAN",
      wp_refused("spoon<Spooner's>(sound([happy]MERRY, FERRY), [supporter]FAN)", "FERRYMAN",
              "spoon<Spooner's>([happy]MERRY, [supporter]FAN, FERRYMAN)"))
check("spoon of sound() with the answer as a part gets the general form",
      wp_refused("spoon<in Spooner's speech>(sound([body parts]HEADTEETH, TEDHEATH), TEDHEATH)", "TEDHEATH",
              "spoon(a, b, SPELT)"))
check("the suggested spoon form is accepted",
      gives("spoon<Spooner's>([destiny]FATE, [coastal city]HULL, HATEFUL)", "HATEFUL"))

# A hidden word written as one leaf per word (hid<ind>([Sign] + [a] + [road's]), the
# 'hid() takes one leaf' refusal): translate joins the side-by-side leaves itself.
tree = w.translate({"wp": "hid<contents>([Sign] + [a] + [road's])"}, "Sign a road's contents", "IGNARO")
check("translate joins a hidden word's per-word leaves into one",
      len(tree["parts"]) == 1 and tree["parts"][0].get("words") == "Sign a road's", tree)
tree = w.translate({"wp": "hid<jointly kept by>([law] + [order])"}, "Law order jointly kept by", "WORD")
check("translate joins a two-word hidden run (WORD in law order)",
      len(tree["parts"]) == 1 and tree["parts"][0].get("words") == "Law order", tree)
try:
    w.translate({"wp": "hid<contents>([Sign] + [road's])"}, "Sign a road's contents", "IGNARO")
    check("leaves with a clue word between them are not joined", False, "accepted")
except w.WordplayError as e:
    check("leaves with a clue word between them are not joined", "does not give IGNARO" in str(e), str(e))

# A refusal names the clue words nothing accounts for (NUDIST style: ins<>(NUTS, DI) misses).
NUD = "Lunatics imprisoned by detectives lacking clothes"
try:
    w.translate({"wp": "ins<imprisoned by>([Lunatics]NUTS, [detectives]DI)"}, NUD, "NUDIST",
                [(NUD.index("lacking"), len(NUD))])
    check("a wrong tree is refused", False, "accepted")
except w.WordplayError as e:
    check("the refusal keeps the letters diagnosis", "does not give NUDIST" in str(e), str(e))
    check("the definition's words are not listed as left over", "'lacking'" not in str(e), str(e))
try:
    w.translate({"wp": "ins<imprisoned by>([Lunatics]NUTS, [detectives]DI)"}, NUD, "NUDIST")
except w.WordplayError as e:
    check("clue words no leaf covers are listed", "'lacking', 'clothes'" in str(e), str(e))
check("unaccounted_words skips leaves and indicators",
      w.unaccounted_words(w.locate_copy({"wp": "ins<imprisoned by>([Lunatics]NUTS, [detectives]DI)"}, NUD, ()), NUD)
      == ["lacking", "clothes"])

# "variously interrupting" / "separately within": the inner letters go in one by one.
tree = w.translate({"wp": "ins<variously interrupting>([reception]LEVEE, [first two characters]AB)"},
                   "Don't mess with first two characters variously interrupting reception", "LEAVEBE")
check("a scattering indicator spreads the inner letters (AB in LEVEE is LEAVEBE)", tree is not None, tree)
tree = w.translate({"wp": "ins<separately within>([Study], first<leads to>([academics], [rebutting], [arguments]))"},
                   "Study leads to academics rebutting arguments separately within 24-hour period", "SATURDAY")
check("separately within: A, R, A one by one into STUDY is SATURDAY", tree is not None, tree)
try:
    w.translate({"wp": "ins<within>([reception]LEVEE, [first two characters]AB)"},
                "Don't mess with first two characters within reception", "LEAVEBE")
    check("a plain container indicator does not spread the inner", False, "accepted")
except w.WordplayError as e:
    check("a plain container indicator does not spread the inner", "does not give LEAVEBE" in str(e), str(e))

# A hedge word the clue itself prints is quoted, not used (annotate audit 10-24/25: 'somehow' as the
# anagram indicator was a third of the hedge refusals); a hedge in the walkthrough's own words stays.
for walk, clue, want in [
    ("'somehow' rearranges UNCLE to EUCLN, and 'Grasped by' puts it round A.", "Grasped by uncle somehow", []),
    ("'Somehow' shuffles CATCH A LONE.", "Somehow catch a lone", []),
    ("'somehow combined' rearranges WEAR and TAY.", "Wear tay somehow combined", []),
    ("'somehow' rearranges UNCLE, then somehow it fits.", "Grasped by uncle somehow", ["somehow"]),
    ("'somehow' rearranges UNCLE.", "Grasped by uncle in a mess", ["somehow"]),
    ("The Latin phrase is used jokingly in Britain for old age itself.", "Old age, in Latin", ["jokingly"]),
]:
    got = va.walkthrough_hedges(walk, clue)
    check(f"walkthrough hedges {walk[:40]!r}", got == want, got)

# pal<ind>() over a clue with one definition: the definition's words are the palindrome, so the
# wordplay gets its block (annotate audit 10-24/25: 16 'missing annotation field blocks').
e = entry(6, "down", "TOT", "Add up as well as down")
stored = annotation.from_model({"def": "Add up", "wp": "pal<as well as down>()", "notes": {"as well as down": "n"}}, e)
check("pal() takes the definition's words as its one leaf",
      stored["wordplay"]["parts"] == [{"words": "Add up", "at": 0, "gives": "TOT"}], stored["wordplay"])
check("the viewed pal() clue has its block", annotation.view(stored, e)["blocks"], annotation.view(stored, e))
e = entry(8, "across", "NOON", "Time of day to return unchanged")
stored = annotation.from_model({"def": "Time of day", "wp": "pal<to return unchanged>()",
                                "notes": {"Time of day": "midday, twelve o'clock", "to return unchanged": "reads the same backwards"}}, e)
check("pal() leaf carries the definition's note",
      stored["wordplay"]["parts"][0].get("note") == "midday, twelve o'clock", stored["wordplay"])
e = entry(8, "across", "NOON", "Time of day, or midday, to return unchanged")
stored = annotation.from_model({"def": ["Time of day", "midday"], "wp": "pal<to return unchanged>()"}, e)
check("pal() with two definitions is left empty", not stored["wordplay"].get("parts"), stored["wordplay"])
# a clue given only an explanation (a --patch onto a null entry) is refused whole, in one line
import apply_annotations as AA
try:
    AA.normalize({"explanation": {"surface": "x"}, "features": {}}, entry(3, "down", "TOT", "Add up"), [])
    check("a stub clue is refused", False, "accepted")
except w.WordplayError as x:
    check("a stub clue is refused with what to write", "no `def` and no `wp`" in str(x), str(x))
check("a stored double definition is not a stub",
      AA.normalize({"definitions": [{"text": "a", "at": 0}, {"text": "b", "at": 2}]}, entry(3, "down", "TOT", "a b"), [])
      .get("definitions"))
check("a missing definitions field says to write `def`", "write the clue words that define" in va.MISSING_FIELD_FIX["definitions"])

raise SystemExit(fails > 0)
