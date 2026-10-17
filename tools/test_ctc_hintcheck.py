"""Does hintcheck's per-clue comparison classify what it should, and stay silent otherwise?

    python3 tools/test_ctc_hintcheck.py

A solver who names a different definition is a def_span; one who says nothing
adds no class. A rung before the blocks that spells the answer is an
early_giveaway, but one that only quotes the clue is not. A template word no
solver says is jargon_unsaid.
"""
import collections
import sys

from ctc_transcripts import hint_differences

E = {"clue": {"text": "Firm legislator replacing a line in union agreement"}, "solution": "COMPLIANCE",
     "_phrase": "COMPLIANCE",
     "annotation": {"type": ["charade"], "definitions": [{"text": "agreement"}],
                    "indicators": [{"text": "replacing", "for": "substitution"}],
                    "blocks": [{"clueFragment": "union", "gives": "ALLIANCE"}]}}
VOCAB = collections.defaultdict(lambda: 99, SEPARABLE=0)


def classes(explain, steps, hard=False, unlock=""):
    return {d["class"] for d in hint_differences(E, steps, explain, unlock, hard, VOCAB)}


CASES = [
    ("silent solver", classes("", [("definition", "The definition is agreement.")]), set()),
    ("other definition", classes("THE DEFINITION IS FIRM LEGISLATOR",
                                 [("definition", "The definition is agreement.")]), {"def_span"}),
    ("answer in an early rung", classes("", [("definition", "The definition is agreement, COMPLIANCE.")]),
     {"early_giveaway"}),
    ("clue words in an early rung",
     classes("", [("definition", "The definition is agreement; firm legislator is wordplay.")]), set()),
    ("template word nobody says", classes("", [("type", "Charade. Built from separable parts.")]),
     {"jargon_unsaid"}),
]
fails = 0
for name, got, want in CASES:
    ok = got == want
    fails += not ok
    print(("  ok: " if ok else "  FAIL: ") + name + ("" if ok else f" want {want} got {got}"))
print("all ok" if not fails else f"{fails} failed")
sys.exit(1 if fails else 0)
