#!/usr/bin/env python3
# Does annotation.view() write on each step of the served tree the letters the
# check found it gives (`yields`), so the app's formula can say them?
#
#     python3 tests/test_stamp_yields.py
#
# Paul, on times-29692 (11-08): the formula read "IRON + ( anagram of ( corps −
# 1 letter ) ) + ( first letter of S )" and "swap in Anthea + letter + letter",
# with none of the letters each step makes. The app cannot always re-derive
# them (CROS is an anagram's order, known only against the answer), but
# wordplay.evaluate has matched every node already: view() keeps what it found.
import _path  # puts tools/ on sys.path
import os
import sys
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import annotation

failures = 0


def check(ok, msg):
    global failures
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        failures += 1


def entry(text, enum, solution, ann):
    return {"number": 1, "direction": "across", "position": {"x": 0, "y": 0}, "length": len(solution),
            "clue": {"text": text, "enumeration": enum}, "solution": solution, "annotation": ann}


def yields(node):
    """{op or words: yields} over the tree, root included."""
    out = {}

    def go(n):
        out[n.get("op") or n.get("words") or n.get("gives")] = n.get("yields")
        for p in n.get("parts") or ():
            go(p)
    go(node)
    return out


CASES = [
    ("14D IRON CROSS",
     entry("Press corps, powerless after reforming, beginning to seek medal", "4,5", "IRONCROSS", {
         "definitions": [{"text": "medal", "at": 58}],
         "wordplay": {"op": "charade", "parts": [
             {"words": "Press", "at": 0, "gives": "IRON"},
             {"op": "anagram", "indicators": [{"text": "after reforming", "at": 23}], "parts": [
                 {"op": "deletion", "indicators": [{"text": "powerless", "at": 13}],
                  "parts": [{"words": "corps", "at": 6}, {"gives": "P"}]}]},
             {"op": "first", "indicators": [{"text": "beginning to", "at": 40}],
              "parts": [{"words": "seek", "at": 53}]}]}}),
     {"charade": None, "anagram": "CROS", "deletion": "CORS", "first": "S", "corps": None, "P": None}),
    ("18A ADENOID",
     entry("American study papers over cracks regarding biological tissue", "7", "ADENOID", {
         "definitions": [{"text": "regarding biological tissue", "at": 34}],
         "wordplay": {"op": "charade", "parts": [
             {"words": "American", "at": 0, "gives": "A"},
             {"words": "study", "at": 9, "gives": "DEN"},
             {"op": "anagram", "indicators": [{"text": "cracks", "at": 27}], "parts": [
                 {"words": "papers", "at": 15, "gives": "ID"}, {"words": "over", "at": 22, "gives": "O"}]}]}}),
     {"charade": None, "anagram": "OID"}),
    ("18D ANTBEAR",
     entry("Voracious eater with big nose, Anthea Turner finally making husband billions", "7", "ANTBEAR", {
         "definitions": [{"text": "Voracious eater with big nose", "at": 0}],
         "wordplay": {"op": "charade", "parts": [
             {"op": "substitution", "indicators": [{"text": "making husband billions", "at": 53}],
              "parts": [{"words": "Anthea", "at": 31}, {"gives": "H"}, {"gives": "B"}]},
             {"op": "last", "indicators": [{"text": "finally", "at": 45}],
              "parts": [{"words": "Turner", "at": 38}]}]}}),
     {"charade": None, "substitution": "ANTBEA", "last": "R", "Anthea": None}),
]

for name, e, want in CASES:
    stored = repr(e["annotation"])
    v = annotation.view(e["annotation"], e, {"entries": [e]})
    got = yields(v["wordplay"])
    for k, y in want.items():
        check(got.get(k) == y, f"{name}: {k} yields {y!r} (got {got.get(k)!r})")
    # The stored annotation is untouched: yields is the view's, never the file's
    # (tools/data/puzzle.schema.json would refuse it there).
    check(repr(e["annotation"]) == stored, f"{name}: the stored annotation is left as it was")

print(f"{failures} failed" if failures else "all ok")
sys.exit(1 if failures else 0)
