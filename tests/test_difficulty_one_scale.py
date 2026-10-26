#!/usr/bin/env python3
# Is every paper scored by the same function on the same scale?
#
#     python3 tests/test_difficulty_one_scale.py
#
# Two identical puzzles under different series ids must measure identically, and
# no function that measures or rates a puzzle may name a series. (The Times'
# SNITCH ranges and comment blend are data only the Times has, and live outside
# these functions; the blend is restandardised onto the series' own clue index.)
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import inspect
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONPATH"] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")

import difficulty as D

# An all-Latin grid: nothing here is in the lexicon.
RANK = {"THE": 1, "CAT": 2000, "DOG": 3000}


def puzzle(series, words):
    entries = [{"position": {"x": 0, "y": i}, "direction": "across", "length": len(w),
                "solution": w, "clue": {"text": f"Clue {i}", "separators": []}}
               for i, w in enumerate(words)]
    return {"id": f"{series}-1", "series": series, "entries": entries}


fails = 0


def check(name, ok, detail=""):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name + ("" if ok else "\n    " + detail))
    fails += not ok


latin = ["AMOR", "VINCIT", "OMNIA", "FORTIS", "VERITAS"]
mixed = ["CAT", "DOG", "THE", "FORTIS", "VERITAS"]
common = ["CAT", "DOG", "THE", "CAT", "DOG"]
for label, words in (("an all-Latin grid", latin), ("a mixed grid", mixed)):
    got = {s: D.rarity(puzzle(s, words), RANK)
           for s in ("times", "sundaytimes", "cryptic", "listener", "x")}
    check(f"{label} has one rarity under every series", len(set(got.values())) == 1, str(got))
check("an unlisted majority is rarer than a common grid",
      D.rarity(puzzle("times", latin), RANK) > D.rarity(puzzle("times", common), RANK))

measured = {"checking": 0.4, "rarity": 5.0, "device": 0.5, "clue_count": 28}
base = {k: {"mean": 0.0, "sd": 1.0} for k in measured} | {"index": {"mean": 0.0, "sd": 1.0}}
check("rate() takes no series", "series" not in inspect.signature(D.rate).parameters)
check("rate() is a pure function of the measurements",
      D.rate(measured, False, base) == D.rate(dict(measured), False, base))

for fn in (D.rarity, D.rate, D.raw, D.score, D.clue_parts, D.checking, D.device,
           D.machinery, D.question_marks, D.clue_count, D.definition_unrelated,
           D.band_of, D.banding, D.reference):
    src = inspect.getsource(fn)
    check(f"{fn.__name__}() names no series", "series" not in src and "SNITCH" not in src)
sys.exit(1 if fails else 0)
