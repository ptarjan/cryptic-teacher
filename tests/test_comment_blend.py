#!/usr/bin/env python3
# Does tools/difficulty.py blend() move only the puzzles whose blog comments
# state enough solve times, re-rate a puzzle as its comments arrive, and leave
# a series' mean and spread where the clue index put them?
#
#     python3 tests/test_comment_blend.py
#
# Synthetic rows, so nothing here reads the corpus or the comment cache.
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import difficulty as D

fails = 0


def check(what, got, want):
    global fails
    if got == want:
        print(f"ok   {what}")
    else:
        print(f"FAIL {what}: expected [{want}], got [{got}]")
        fails += 1


rnd = random.Random(1)
idx, com = {}, {}
for i in range(60):
    pid = f"times-{i}"
    idx[pid] = rnd.gauss(0.2, 0.5)
    com[pid] = {"comments": 20, "dnf": rnd.randint(0, 6), "stated_times": 5,
                "median_minutes": rnd.uniform(15, 60)}
for i in range(10):  # a series under COMMENT_SERIES_MIN is never blended
    idx[f"timesjumbo-{i}"] = 0.0
    com[f"timesjumbo-{i}"] = {"comments": 9, "dnf": 1, "stated_times": 4, "median_minutes": 50}
cm = D.comment_moments(idx, com)
b = {p: D.blend(p, x, com, cm) for p, x in idx.items() if p.startswith("times-")}
m = D.moments(list(b.values()))
o = D.moments([idx[p] for p in b])
few = dict(com["times-0"], stated_times=D.COMMENT_MIN_TIMES - 1)
slow = dict(com["times-0"], median_minutes=120)

check("a series needs COMMENT_SERIES_MIN puzzles", sorted(cm), ["times"])
check("the blend keeps the series' mean and spread",
      (abs(m["mean"] - o["mean"]) < 1e-4, abs(m["sd"] - o["sd"]) < 1e-4), (True, True))
check("too few stated times leaves the clue index",
      D.blend("times-0", idx["times-0"], {"times-0": few}, cm), None)
check("no comments leaves the clue index", D.blend("times-0", idx["times-0"], {}, cm), None)
check("slower stated times rate the puzzle harder",
      D.blend("times-0", idx["times-0"], {"times-0": slow}, cm) > b["times-0"], True)
sys.exit(fails)
