#!/usr/bin/env python3
# A reread may not put page prose in front of a held clue.
#
#     python3 tests/test_glued_rewrite.py
#
# times-2110's 18-across ("Moving house") was reread 11-17 as the notice paragraph, the
# tail of 17-across and a stray "118" glued in front of the same two words.
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
import _path  # puts tools/ on sys.path

import puzzle_integrity as pi

GLUED = ("The two thousand with -the solution, Copies of The As puzzles and Publishers, Messrs, "
         "parentheses denote the 17 fang to vacate 118 Moving house")


def puzzle(text):
    return {"id": "times-9999", "entries": [
        {"number": 18, "direction": "across", "length": 7, "clue": {"text": text, "enumeration": "7"},
         "solution": "CARAVAN"}]}


def refused(old, new):
    flags = []
    pi.check_rewrite(puzzle(old), puzzle(new), flags)
    return [f for f in flags if "page prose" in f[2]]


fails = 0
for name, ok in [
    ("glued prose refused", bool(refused("Moving house", GLUED))),
    ("a fuller clue passes", not refused("Moving house", "Relocating, as one might, a home")),
    ("a short head passes", not refused("house", "Moving 18 house")),
    ("a long head with no number passes",
     not refused("of the lamp", "The thing that was said to be hidden inside the wall of the lamp")),
]:
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok
sys.exit(1 if fails else 0)
