"""Does hintcheck's per-clue comparison classify what it should, and stay silent otherwise?

    python3 tools/test_ctc_hintcheck.py

A solver who names a different definition is a def_span; one who says nothing
adds no class. A rung before the blocks that spells the answer is an
early_giveaway, but one that only quotes the clue is not. A template word no
solver says is jargon_unsaid.
"""
import collections
import sys

import inspect
import json
import subprocess
from pathlib import Path

import ctc_transcripts
from ctc_transcripts import app_rungs, hint_differences

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


# The rungs hintcheck judges are the app's own: read off the booted app.js, not
# a Python copy of its wording (compare_mc.ladder_steps drifted, and did not
# mask the answer).
ROOT = Path(__file__).resolve().parent.parent
APP_ORDER = ["indicators", "definition", "type", "blocks", "walkthrough"]
shown = app_rungs(["times-28739"])["times-28739"]
steps = shown["1-across"]
keys = [k for k, _ in steps]
by = dict(steps)
direct = json.loads(subprocess.run(["node", str(ROOT / "tools" / "hint_rungs.js"), "times-28739"],
                                   capture_output=True, text=True, check=True).stdout)
RUNG_CASES = [
    ("hintcheck no longer uses the Python ladder", "ladder_steps" not in inspect.getsource(ctc_transcripts.hintcheck), True),
    ("rungs are keys of the app's ladder", set(keys) <= set(APP_ORDER) and "walkthrough" in keys, True),
    ("rungs come in the app's order", keys == sorted(keys, key=APP_ORDER.index), True),
    ("same rungs per clue as the node tool's own output (wording varies between boots)",
     {e: [k for k, _ in v] for e, v in shown.items()} == {e: [k for k, _ in v] for e, v in direct["times-28739"].items()}, True),
    ("answer is masked before the walkthrough", "BASSO" not in " ".join(by.get(k, "") for k in ("indicators", "definition", "type")), True),
]
for name, got, want in RUNG_CASES:
    ok = got == want
    fails += not ok
    print(("  ok: " if ok else "  FAIL: ") + name)
print("all ok" if not fails else f"{fails} failed")
sys.exit(1 if fails else 0)
