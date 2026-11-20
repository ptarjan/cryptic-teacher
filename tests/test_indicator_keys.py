#!/usr/bin/env python3
# The (type, key) pairs a clue's indicators give /indicators/ and the burn's
# indicator cover: each phrase under its own `for` only, the longest key inside
# it, and never through link words alone. /learn/ shows each type's most used, with counts.
import _path  # puts tools/ on sys.path
import os
import sys
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from indicator_keys import clue_pairs

LEX = {"anagram": {"VARIETY": 9, "TOUCHED": 5, "OF": 1, "ALL OVER": 3, "OVER": 2},
       "charade": {"ON": 4}, "reversal": {"UPSIDEDOWN": 3}}

fails = 0
def check(name, want, got):
    global fails
    fails += got != want
    print(("ok  " if got == want else "FAIL"), name, "" if got == want else got)

A = lambda text, t="anagram": {"text": text, "for": t}
check("a phrase that is a key is an exact match",
      {("anagram", "VARIETY"): True}, clue_pairs(LEX, [A("variety")]))
check("a longer phrase links the key inside it under its own for",
      {("anagram", "VARIETY"): False}, clue_pairs(LEX, [A("Variety of")]))
check("the longest key inside wins",
      {("anagram", "ALL OVER"): False}, clue_pairs(LEX, [A("strewn all over")]))
check("link words alone never match, even when the lexicon has them",
      {}, clue_pairs(LEX, [A("out of")]))
check("a charade's phrase is looked up among charade keys only, never as anagram TOUCHED",
      {}, clue_pairs(LEX, [A("touched on", "charade")]))
check("the same phrase for an anagram links the key inside it",
      {("anagram", "TOUCHED"): False}, clue_pairs(LEX, [A("touched on")]))
check("an indicator without for gives nothing",
      {}, clue_pairs(LEX, [{"text": "variety"}]))
check("a for the lexicon lacks gives nothing",
      {}, clue_pairs(LEX, [A("variety", "container")]))
check("hyphens key as blogs key them",
      {("reversal", "UPSIDEDOWN"): True}, clue_pairs(LEX, [A("upside-down", "reversal")]))

# /indicators/ links each pair to one clue: ours over a blog's, exact over contained.
import build_seo_pages as b
b.indicator_lexicon = lambda: LEX
def linked(*entries):
    found = {}
    puz = {"id": "t-1", "date": None, "entries": [dict(e, number=i, direction="across") for i, e in enumerate(entries)]}
    b.clue_indicators(found, puz, " ".join(f'id="{i}-across"' for i in range(len(entries))))
    return {k: v[2] for k, v in found.items()}

blog = {"annotation": None, "blog": {"type": ["anagram"], "indicators": [A("variety")]}}
check("a clue only a blog's facts explain is linked",
      {("anagram", "VARIETY"): "0-across"}, linked(blog))
check("our annotation outranks a blog's, even one matching the key exactly",
      {("anagram", "VARIETY"): "1-across"},
      linked(blog, {"annotation": {"type": ["anagram"], "indicators": [A("variety of")]}}))
check("an exact phrase outranks one containing the key",
      {("anagram", "VARIETY"): "1-across"},
      linked({"annotation": {"type": ["anagram"], "indicators": [A("variety of")], "explanation": {"walkthrough": "long " * 9}}},
             {"annotation": {"type": ["anagram"], "indicators": [A("variety")]}}))

# /learn/ lists a type's indicators most used first, each with its count, and
# only the head: "of" (1 clue) never sits beside "variety" (9).
import re
M = lambda t: re.match(r"<!-- indicators: (\w+) -->", f"<!-- indicators: {t} -->")
b.LEARN_INLINE = 2
plain = lambda h: re.sub(r"<[^>]+>|&nbsp;", " ", h).split()
line = b.learn_indicators(M("anagram"))
check("an inline list is the head, ranked, with counts",
      ["variety", "9", "&middot;", "touched", "5"], plain(line[line.index(":") + 1:line.rindex(" &middot; <a")]))
check("an inline list is joined with the site's dot, not a comma",
      True, b.build_abbreviations.LIST_SEP in line and "," not in line)
# Each lesson section carries its own type's line, linked to that type's list.
check("the line names its type and links to the type's full list",
      [("anagram", "anagram")], re.findall(r'Most used (\w+) indicators:.*?<a href="[^"]*/indicators/#(\w+)"', line))
try:
    b.learn_indicators(M("nonsense"))
    check("a marker for a type /indicators/ has no section is refused", True, False)
except SystemExit:
    check("a marker for a type /indicators/ has no section is refused", True, True)
raise SystemExit(fails)
