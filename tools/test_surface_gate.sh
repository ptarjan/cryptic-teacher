#!/bin/bash
# Does tools/author_trial.py refuse a candidate the clue judge refuses, and does
# the judge refuse "Hacks are on the stouts" and the nerazzurri INTER?
#
#     bash tools/test_surface_gate.sh
#
# The plumbing half stubs the model: a candidate is refused only when both
# judge calls refuse it, and a reply missing a verdict is an error. The
# judgement half needs `claude` on PATH, so CI skips it: it sends A001 with two
# clues Paul refused, a surface that is not a real sentence ("Hacks are on the
# stouts") and a definition that needs a football fan ("Milan side" for INTER,
# explained by the nerazzurri), and wants those two refused and A001 passed.
set -uo pipefail
cd "$(dirname "$0")/.."

PYTHONPATH=tools python3 - <<'PY'
import json
import os
import shutil
import sys

import author_trial

def cand(text, answer, definition, explanation):
    return {"clue": {"text": text}, "annotation": {
        "answer": answer, "definitions": [{"text": definition}],
        "explanation": {"walkthrough": explanation, "definitionFit": ""}}}

HACKS = cand("Hacks are on the stouts", "REPORTERS", "Hacks",
             "'On the stouts' reads like 'on the beer'. RE plus PORTERS, a dark beer.")
MILAN = cand("Milan side buried in print errors", "INTER", "Milan side",
             "A definition by naming. Of Milan's two clubs, this is the nerazzurri, whose "
             "full name Internazionale gets cut short in every match report.")
fails = []

calls = []
def stub(prompt, model, effort, timeout=1800):
    calls.append(prompt)
    lines = [l for l in prompt.splitlines() if l[:1].isdigit() and ". " in l]
    return json.dumps({"verdicts": [
        {"n": int(l.split(".")[0]), "real": "stouts" not in l,
         "known": "nerazzurri" not in l or len(calls) == 1, "why": "stub"} for l in lines]})

real_claude = author_trial.claude
author_trial.claude = stub
got = author_trial.judge_refusals(
    [cand("Son leaves room for walk", "PACE", "walk", ""), HACKS, MILAN], "stub")
if set(got) != {1}:
    fails.append(f"stubbed judge refused {sorted(got)}, want [1]: a refusal "
                 "from one call of two must not refuse")
author_trial.claude = lambda *a, **k: json.dumps({"verdicts": [{"n": 1, "real": True}]})
try:
    author_trial.judge_refusals([HACKS, MILAN], "stub")
    fails.append("a judge reply missing a verdict was accepted")
except ValueError:
    pass
author_trial.claude = real_claude

if os.environ.get("CI") or not shutil.which("claude"):
    print("  skip: no claude on PATH, so the judgement half did not run")
else:
    clues = json.load(open("tools/data/authored_A001_clues.json"))
    a001 = [v for k, v in clues.items() if not k.startswith("_")]
    refused = author_trial.judge_refusals(a001 + [HACKS, MILAN], "claude-opus-5-5")
    for i, name in ((len(a001), "Hacks are on the stouts"), (len(a001) + 1, "the nerazzurri INTER")):
        if i not in refused:
            fails.append(f"the judge passed {name}")
    for i, why in refused.items():
        if i < len(a001):
            fails.append(f"the judge refused A001's {a001[i]['clue']['text']!r}: {why}")

for f in fails:
    print("  FAIL:", f)
if fails:
    sys.exit(1)
print("  ok: the clue judge refuses what it should, and only when both calls agree")
PY
