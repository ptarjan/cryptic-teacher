#!/usr/bin/env python3
# Does puzzle_integrity refuse a blog clue that opens with what is left of the
# blog's clue number, and pass the clues that only look like one?
#
#     python3 tests/test_clue_number_residue.py
#
# Every blog writes the number and its direction before the clue, "1a" or
# "1ac." or "1 a.", and a parser that takes the number but not the suffix files
# "a Bizarre eponym ...". The opposite slip eats the clue's own "A" off "1 A
# moral purge ...", so the message asks for that to be checked too.
# Real clues open lowercase as well ("e.g.", "iPads are epic!", "see 24dn.",
# "eBay"), and those must pass.
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, str(REPO / "tools"))

import puzzle_integrity as P

fails = 0


def same(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        print(f"  FAIL: {name}\n    want {want}\n    got  {got}")
        fails += 1


def flagged(text, retrieved="blog"):
    flags = []
    puzzle = {"id": "telegraph-1", "source": {"retrievedFrom": retrieved},
              "entries": [{"number": 1, "direction": "across", "position": {"x": 0, "y": 0},
                           "length": 4, "clue": {"text": text, "enumeration": "4"},
                           "solution": "ABCD"}]}
    P.check_shape(puzzle, "2026-10-01", flags)
    return "Y" if any("clue number" in f[2] for f in flags) else "n"


bad = ["a Bizarre eponym worked for lad on warship", "d Not complete in showing bias",
       "ac. Seaman, getting posted", "dn Fares", "dFares going up on flights?",
       "aWorthless gemstone", "s Sailor carries drugs back", "aa Reject sugar"]
good = ["A moral purge modified indoor pastime", "e.g. registered undertakings",
        "eg registered undertakings", "iPads are epic!", "eBay seller", "see 24dn.",
        "e + r ÷ (51 + 11) = magic formula", "i newspaper printed in New York",
        "makes new plans about navy pennants"]
same("every number residue is refused", "".join(flagged(t) for t in bad), "YYYYYYYY")
same("lowercase-opening clues that are clues pass", "".join(flagged(t) for t in good), "nnnnnnnnn")
same("only a blog transcription is held to it", flagged("a Bizarre eponym", retrieved="publisher"), "n")

if fails:
    print(f"{fails} failed")
    sys.exit(1)
print("all passed")
