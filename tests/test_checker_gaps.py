#!/usr/bin/env python3
# Five correct parses the annotation checker once refused (annotate runs withdrew them):
# a middle pick over 10 words, a "half of" middle (LIC from POLICE), an anagram that takes two
# separate insertions, a plain "most of" cut beside a half that holds the same letter, and a
# hidden word inside a number written out. Run it from the repo root with python3.
import _path  # puts tools/ on sys.path

import annotation
import validate_features as VF
import validate_shape_folds as F
import validate_shape_order as O
import wordplay

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else detail)

def tree(clue, answer, model):
    entry = {"clue": {"text": clue, "enumeration": str(len(answer))}, "solution": answer}
    return annotation.from_model(model, entry)

# cryptic-26133 6d: the middle letter of each of ten words under one indicator.
ten = ", ".join(f"[{w}]" for w in ["it's", "not", "about", "odd", "man", "Charlie", "and", "the", "Chocolate", "Factory's"])
try:
    t = tree("Essentially, it's not about odd man — Charlie and the Chocolate Factory's musical song", "TOODARNHOT",
             {"def": "musical song", "wp": f"middle<Essentially>({ten})",
              "notes": {"Essentially": "Essentially points at the middle of each word."}})
    check("middle over ten words", t["wordplay"]["op"] == "middle" and len(t["wordplay"]["parts"]) == 10)
except wordplay.WordplayError as e:
    check("middle over ten words", False, str(e))
try:
    wordplay.parse("middle(" + ", ".join(["[a]"] * (wordplay.SELECT_MAX + 1)) + ")")
    check("a selection list still has a cap", False)
except wordplay.WordplayError:
    check("a selection list still has a cap", True)

# telegraph-27897 11d: "half of police" is LIC, the central three letters.
try:
    tree("Brief half of police catching a criminal", "LACONIC",
         {"def": "Brief", "wp": "ins<catching>(middle<half of>([police]), [a]A + [criminal]CON)",
          "notes": {"half of": "Half of police is its central half, LIC.", "criminal": "A criminal is a con."}})
    check("half of police is LIC", True)
except wordplay.WordplayError as e:
    check("half of police is LIC", False, str(e))
try:
    tree("Brief middle of police catching a criminal", "LACONIC",
         {"def": "Brief", "wp": "ins<catching>(middle<centre of>([police]), [a]A + [criminal]CON)", "notes": {}})
    check("without 'half' the middle is still centred", False)
except wordplay.WordplayError:
    check("without 'half' the middle is still centred", True)

# telegraph-30339 13a: PERHAPS* takes ELITE round the S and RA after PRE: two gaps, one nesting.
t = tree("Painters like Millais perhaps worked outside best, artist admitted", "PRERAPHAELITES",
         {"def": "Painters like Millais",
          "wp": "ins<outside>(ins<admitted>(ana<worked>([perhaps]), [artist]RA), [best]ELITE)",
          "notes": {"worked": "Worked is reworked, so PERHAPS is rearranged.", "outside": "Outside puts ELITE round.",
                    "admitted": "Admitted lets RA in.", "best": "Best is ELITE.", "artist": "An artist is an RA."}})
check("anagram with two separate insertions", F.nested_containers(t["wordplay"], "PRERAPHAELITES") == 0)
flat = {"op": "container", "parts": [
    {"op": "container", "parts": [{"op": "anagram", "parts": [{"words": "x", "gives": "AB"}]},
                                  {"words": "y", "gives": "C"}]},
    {"words": "z", "gives": "D"}]}
check("a flat insertion into an anagram stays flagged", F.nested_containers(flat, "ACDB") == 1)

# times-25158 6a: ME is the closing half of TIME; AGRE is AGREE cut by "most of". The cut E is not put back.
t = tree("After half time most of match is lacking in quality", "MEAGRE",
         {"def": "lacking in quality", "wp": "first<half>([time]) + del<most of>([match]AGREE, E)",
          "notes": {"half": "Half of time is its closing half.", "most of": "Most of agree drops its last letter.",
                    "match": "A match is an agree."}})
check("most of beside a half holding the same letter", O.moved_letters(t["wordplay"]) == 0)

# toughie-336 4d: NEIGH hidden in 1982 written out, only when the annotation gives the spelling.
t = tree("What was heard of Shergar in 1982", "NEIGH",
         {"def": "What was heard of Shergar", "wp": "hid<in>([1982]NINETEENEIGHTYTWO)",
          "notes": {"in": "In says the answer sits inside."}})
spelled = VF.spelled_numbers(t)
check("spelled number found", any("NEIGH" in s for s in spelled), str(spelled))
check("not a number word is not a spelling", not VF.spelled_numbers(
    {"wordplay": {"op": "hidden", "parts": [{"words": "1982", "gives": "HORSEFEED"}]}}))
check("no digits, no spelling", not VF.spelled_numbers(
    {"wordplay": {"op": "hidden", "parts": [{"words": "nineteen eighty", "gives": "NINETEENEIGHTY"}]}}))

raise SystemExit(1 if fails else 0)
