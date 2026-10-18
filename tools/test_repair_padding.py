#!/usr/bin/env python3
"""Tests that repair_fetched takes link words out of the wordplay, and only those.

linkWords is derived from the clue words no span covers, so a padding leaf is fixed by
removing it. Hit: azed-1900 13a "with". Near misses: a note with another job, a pronoun,
a leaf whose note is not padding."""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repair_fetched as R

fails = 0


def same(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        print(f"  FAIL: {name}\n    want {want}\n    got  {got}")
        fails += 1


def entry(leaf):
    return {
        "number": 13, "direction": "across", "length": 10,
        "clue": {"text": "Slip sits with RA uneasily for some canvas", "enumeration": "10"},
        "solution": "SPRITSAILS",
        "annotation": {
            "definitions": [{"text": "some canvas", "at": 31}],
            "wordplay": {"op": "charade", "parts": [
                {"op": "anagram", "indicators": [{"text": "uneasily", "note": "shifts about"}],
                 "parts": [{"words": "Slip", "note": "as written"},
                           {"words": "sits", "note": "as written"},
                           {"words": "RA", "note": "as written"}]},
                leaf]}}}


puzzle = {"id": "azed-1900", "entries": []}
pad = {"unchecked": True, "words": "with", "note": "joins the two parts of the fodder"}

e = entry(dict(pad))
R.SKIPPED.clear()
same("hit: the padding leaf is removed", R.unpad_charades(e, puzzle), ["with"])
same("the lone remaining part replaces the charade", e["annotation"]["wordplay"]["op"], "anagram")

for name, leaf in [
    ("joining note that names letters", dict(pad, note="joins the two sets of letters")),
    ("placement note", dict(pad, words="for", note="places the first piece before the second")),
    ("surface padding that gives no letters", dict(pad, words="sits",
                                                   note="surface padding: it sets the scene and gives no letters")),
]:
    e = entry(leaf)
    same(f"hit: {name}", R.unpad_charades(e, puzzle), [leaf["words"]])

for name, leaf in [
    ("link word that is the letter removed", dict(pad, words="a", note="the letter removed")),
    ("joining word whose note says what is removed", dict(pad, note="joins what is removed from the fodder")),
    ("surface padding that supplies a letter", dict(pad, words="reads",
                                                    note="the extra word, surface padding whose first letter joins the hidden message")),
    ("note gives another job", dict(pad, note="second meaning of the clue")),
    ("pronoun that may refer back", dict(pad, words="it", note="surface padding")),
    ("not padding by its note", dict(pad, note="the printed word is read as its two halves")),
]:
    e = entry(leaf)
    before = copy.deepcopy(e)
    same(f"near miss kept: {name}", (R.unpad_charades(e, puzzle), e == before), ([], True))

e = entry(dict(pad))
e["annotation"]["wordplay"]["indicators"] = [{"text": "uneasily", "note": "x"}]
before = copy.deepcopy(e)
same("near miss kept: charade with fields of its own would be left one-piece",
     (R.unpad_charades(e, puzzle), e == before), ([], True))

print("repair_padding: all checks passed" if fails == 0 else f"repair_padding: {fails} FAILED")
sys.exit(1 if fails else 0)
