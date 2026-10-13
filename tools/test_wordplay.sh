#!/usr/bin/env bash
# Does tools/wordplay.py parse every op of the one-line wordplay expression,
# give the answer's letters at every node, refuse a parse that doesn't with
# the node that broke, and does annotation.view() derive today's fields
# (type, answer, indicators' for, linkWords, blocks, assembly) from the tree?
#
#     bash tools/test_wordplay.sh
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
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
    ("NIP IN", "pal<works either way>([Ulster]NI + [fix]PIN)"),
    ("ABBA", "pal<Reversible>()"),
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
    ("a reversal of a palindrome", "LEVEL", "rev<back>([level])", "reads the same backwards"),
    ("not hidden", "LEVER", "hid<in>([trap ever])", "needs LEVER"),
    ("hidden letters not in the words", "LEVER", "hid<in>([trap ever]LEVER)", "gives nothing"),
    ("a container that can't fit", "STOMACH", "ins<in>([turkey]TOM, [pouch]SAC) + first<head>([hen's])", "needs"),
    ("an anagram whose order nothing fixes", "ALE", "del<losing>(ana<mad>([leap]), P)", "write the letters"),
    ("homophone spelt wrong", "PIECE", "sound<Sung>([harmony]PEACE, PEACE)", "needs PIECE"),
    ("a palindrome that isn't one", "NIPINS", "pal<either way>([Ulster]NI + [fix]PINS)", "does not read the same"),
    ("an answer alone that isn't a palindrome", "ABBY", "pal<Reversible>()", "ABBY does not read the same"),
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
    ("a repeat that isn't there", "[in#2]IN", ["no copy #2"], "Tea in cup"),
]:
    r = perr(expr, *words, clue=clue)
    check(f"parse refuses: {name}", r is True, r)

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
     {"definitions": [{"text": "Connections", "at": 0, "note": "first meaning"},
                      {"text": "cigarettes", "at": 17, "note": "second meaning"}]},
     {"type": ["double_definition"], "answer": "JOINTS", "linkWords": ["with"],
      "blocks": [{"clueFragment": "Connections", "note": "first meaning"},
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

raise SystemExit(fails > 0)
PY
