#!/usr/bin/env bash
# The (type, key) pairs a clue's indicators give /indicators/ and the burn's
# indicator cover: a phrase links the longest key inside it, but only in a
# one-type clue, and never through link words alone.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
from indicator_keys import clue_pairs

LEX = {"anagram": {"VARIETY": 9, "TOUCHED": 5, "OF": 1, "ALL OVER": 3, "OVER": 2},
       "charade": {"ON": 4}, "reversal": {"UPSIDEDOWN": 3}}

fails = 0
def check(name, want, got):
    global fails
    fails += got != want
    print(("ok  " if got == want else "FAIL"), name, "" if got == want else got)

check("a phrase that is a key is an exact match",
      {("anagram", "VARIETY"): True}, clue_pairs(LEX, ["anagram"], ["variety"]))
check("a longer phrase in a one-type clue links the key inside it",
      {("anagram", "VARIETY"): False}, clue_pairs(LEX, ["anagram"], ["Variety of"]))
check("the longest key inside wins",
      {("anagram", "ALL OVER"): False}, clue_pairs(LEX, ["anagram"], ["strewn all over"]))
check("link words alone never match, even when the lexicon has them",
      {}, clue_pairs(LEX, ["anagram"], ["out of"]))
check("in a clue of several types only an exact phrase counts",
      {}, clue_pairs(LEX, ["charade", "anagram"], ["touched on"]))
check("a type the clue does not name gives nothing",
      {}, clue_pairs(LEX, ["charade"], ["variety"]))
check("hyphens key as blogs key them",
      {("reversal", "UPSIDEDOWN"): True}, clue_pairs(LEX, ["reversal"], ["upside-down"]))
raise SystemExit(fails)
PY
