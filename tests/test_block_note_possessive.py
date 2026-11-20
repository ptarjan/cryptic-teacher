#!/usr/bin/env python3
# A leaf of a word and 's that gives just the word's letters (`[Celia's]CELIA`) needs a note the
# validator wants and only one sentence fits; fix_shape_notes._block_note_for writes it. Other
# unnoted leaves (a synonym) stay refused, and the refusal's example is worded for the block's shape.
#
#     python3 tests/test_block_note_possessive.py
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
import _path  # puts tools/ on sys.path
os.chdir(REPO)

import fix_shape_notes as F
import validate_annotations as V

fails = 0


def same(what, got, want):
    global fails
    if got == want:
        print(f"  ok: {what}")
    else:
        print(f"  FAIL: {what}\n    want {want!r}\n    got  {got!r}")
        fails += 1


def note(words, gives):
    leaf = {"words": words, "gives": gives}
    return F._block_note_for(leaf, {"op": "charade", "parts": [leaf, {"gives": "X"}]}, {"op": "charade"}, "ANSWER")


for w, g in [("Celia's", "CELIA"), ("a seed’s", "ASEED"), ("that's", "THAT")]:
    n = note(w, g)
    same(f"{w} noted", bool(n) and "possession" in n, True)
    same(f"{w} note names no letters", g.lower() in n.lower(), False)
same("synonym stays refused", note("jacketed", "GILET"), None)
same("own letters need none", note("in", "IN"), None)
same("'s with other letters refused", note("Celia's", "CELIAS"), None)

ex = lambda f, g: V._block_note_example([f"3D: block {f!r} > '{g}' {V.BLOCK_NO_NOTE}. x"])
same("abbreviation hint", "convention" in ex("Empty", "O"), True)
same("cut-letters hint", "which letters" in ex("Befogged", "FOG"), True)
same("synonym hint", "another word for jacketed" in ex("jacketed", "GILET"), True)

sys.exit(1 if fails else 0)
