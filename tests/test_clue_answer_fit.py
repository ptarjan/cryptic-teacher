#!/usr/bin/env python3
# Does the pre-session check refuse a puzzle whose clues belong to other answers?
#
#     python3 tests/test_clue_answer_fit.py
#
# Tiny fixtures in, a reason or None out (tools/clue_answer_fit.py).
import json
import os
import sys
import tempfile
from pathlib import Path
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # puts tools/ on sys.path
import clue_answer_fit as F

fails = 0


def check(got, want, what):
    global fails
    if got != want:
        fails += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


# (clue, answer) pairs whose clue shows its answer: hidden, anagram, acrostic, shared run.
GOOD = [("Part of a Greek island contains chaos (5)", "ISLAN"),
        ("Dreadful lemon is served up (5)", "MELON"),
        ("Always visit our neighbours (4)", "AVON"),
        ("Contains tolerable stew (4)", "TOLE")]
# The same answers under clues lifted from another puzzle.
OTHER = ["Ship caught twice during a fuel change (7)", "Sign of religious ban on football grounds (8)",
         "Errors made when I rush into writing (9)", "Passionate speech makes one go into business (6)",
         "Being a playwright without love he wastes away (5)", "Somewhere to sleep with a politician (7)"]


def puzzle(pairs, annotated=False):
    entries = []
    for i, (text, answer) in enumerate(pairs):
        e = {"number": i + 1, "direction": "down", "clue": {"text": text}, "solution": answer}
        if annotated and i == 0:
            e["annotation"] = {"x": 1}
        entries.append(e)
    return {"id": "t-1", "entries": entries}


answers = ["STALEST", "SPENCER", "ADMISSION", "EASEL", "THEIST", "NUDISTS", "NICKNAME", "DISCHARGE"]
mismatched = [(OTHER[i % len(OTHER)] + " " * 0, answers[i % len(answers)]) for i in range(F.MIN_CLUES)]
check(F.misfiled(puzzle(mismatched)) is not None, True, "clues from elsewhere are refused")
check(F.misfiled(puzzle(mismatched, annotated=True)), None, "an annotated puzzle is let through")
check(F.misfiled(puzzle(mismatched[:F.MIN_CLUES - 1])), None, "too few clues say nothing")
fits = [GOOD[i % len(GOOD)] for i in range(F.MIN_CLUES)]
check(F.shows_answer(*GOOD[1]), True, "anagram shows")
check(F.shows_answer(*GOOD[0]), True, "hidden shows")
check(F.shows_answer(*GOOD[2]), True, "acrostic shows")
check(F.misfiled(puzzle(fits)), None, "clues that show their answers pass")
check(F.shows_answer("Cat (3)", "CAT"), None, "a three-letter answer says nothing")
check(F.misfiled({"id": "t-2", "entries": [{"clue": {"text": "x"}}]}), None, "no answers, nothing to compare")

with tempfile.TemporaryDirectory() as d:
    f = os.path.join(d, "ok.txt")
    Path(f).write_text("# header\nfoo-1  # fits\n\nfoo-2\n")
    check(F.reviewed_ok(f), {"foo-1", "foo-2"}, "allowlist parses ids, drops comments")
    check(F.reviewed_ok(os.path.join(d, "none.txt")), set(), "a missing allowlist is empty")
    # main() passes an allowlisted id even though its clues are refused.
    import puzzle_paths
    pf = os.path.join(d, "foo-1.json")
    Path(pf).write_text(json.dumps(puzzle(mismatched)))
    puzzle_paths.find = lambda pid: pf
    F.OK_FILE = f
    check(F.main(["check", "foo-1"]), 0, "an allowlisted puzzle passes check")
    check(F.main(["check", "bar-9"]), 1, "a non-listed mismatched puzzle fails check")
check({"sundaytimes-2167", "sundaytimes-3435"} <= F.reviewed_ok(os.path.join("tools", "data", "clue_answer_fit_ok.txt")),
      True, "the seeded ids are listed")

sys.exit(1 if fails else 0)
