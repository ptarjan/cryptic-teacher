#!/bin/bash
# What apply_annotations.normalize computes, so the run need not write it.
#
#     bash tools/test_ann_normalize.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools python3 - <<'PY'
import copy, itertools
from pathlib import Path
import apply_annotations as A
import fetch_puzzle as F

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

import annotation, wordplay
def leaves(node):
    parts = wordplay.parts_of(node) if "op" in node else []
    return [y for x in parts for y in leaves(x)] if "op" in node else [node]
# A sample of stored puzzles: the answer a legacy write derives from solution
# + enumeration is the one annotation.view() shows, or differs only in where
# a break falls.
same = total = 0
bad = []
pick = supplied = None
for src in itertools.islice(F.puzzle_files(), 0, None, 400):
    raw = F.read_puzzle_file(src)
    puzzle = annotation.view_puzzle(raw)
    for e in puzzle["entries"]:
        if e.get("annotation") and not e.get("group") and pick is None:
            pick = (puzzle, e)
        ann = e.get("annotation")
        if not ann or e.get("alteration"):
            continue
        total += 1
        got = A.derived_answer(e, puzzle["entries"])
        if got == ann["answer"] or (got and got.replace(" ", "").replace("-", "") ==
                                    ann["answer"].replace(" ", "").replace("-", "")
                                    and "-" not in got and " " not in ann["answer"]):
            same += 1
        else:
            bad.append((src.stem, e["number"], got, ann["answer"]))
    if supplied is None:
        for i, x in enumerate(raw["entries"]):
            tree = (x.get("annotation") or {}).get("wordplay")
            leaf = tree and next((n for n in leaves(tree) if n.get("words") and not n.get("unchecked")), None)
            if leaf:
                supplied = (src, i)
                break
check(f"derived answer matches the viewed one ({same}/{total})", same >= 0.95 * total)
for b in bad[:5]:
    print("   ", b)
puzzle, e = pick
ann = copy.deepcopy(e["annotation"]); want = ann.pop("answer")
check("a missing answer is derived", A.normalize(ann, e, puzzle["entries"]).get("answer", "").replace(" ", "").replace("-", "") == e["solution"])
check("a written answer stays", A.normalize({**ann, "answer": "X"}, e, puzzle["entries"])["answer"] == "X")
sel = {"type": ["charade"], "blocks": [{"clueFragment": "x", "select": "first", "at": 3}],
       "indicators": [{"text": "y", "at": 4}], "definitions": [{"text": "z", "at": 0}]}
got = A.normalize(sel, e, puzzle["entries"])
check("select adds letter_selection to type", got["type"] == ["charade", "letter_selection"])
check("at is dropped from blocks and indicators",
      "at" not in got["blocks"][0] and "at" not in got["indicators"][0])
check("a definition keeps its at", got["definitions"][0]["at"] == 0)
check("the input is not mutated", sel["type"] == ["charade"] and "at" in sel["blocks"][0])
# Clue words are written as the clue prints them, whatever the run typed.
typed = {"type": ["charade"], "blocks": [{"clueFragment": "Mammal's", "gives": "X"}],
         "indicators": [{"text": "COVERING", "for": "charade"}], "linkWords": ["it  with"]}
got = A.in_clue_spelling(typed, "Mammal’s covering it with bristles")
check("a block's typed apostrophe is the clue's", got["blocks"][0]["clueFragment"] == "Mammal’s")
check("an indicator's case is the clue's", got["indicators"][0]["text"] == "covering")
check("a link word's spacing is the clue's", got["linkWords"] == ["it with"])
check("and the input is not mutated", typed["blocks"][0]["clueFragment"] == "Mammal's")
# A leaf with no words (a block with no clueFragment) is letters the preamble supplies.
import contextlib, io
import puzzle_schema, validate_annotations as V
src, i = supplied
pz = {**F.read_puzzle_file(src), "preamble": "One letter in each answer is supplied."}
tree = pz["entries"][i]["annotation"]["wordplay"]
leaf = next(n for n in leaves(tree) if n.get("words") and not n.get("unchecked"))
leaf["gives"] = wordplay.letters(leaf.pop("gives", None) or leaf["words"])
del leaf["words"]
leaf.pop("at", None)
pz = puzzle_schema.order(pz)
def findings(pz):
    pz = puzzle_schema.prune(copy.deepcopy(pz))
    with contextlib.redirect_stdout(io.StringIO()):
        errs = V.validate_puzzle(pz)[1]
    return puzzle_schema.validate(pz) + [x for x in errs if "clueFragment" in x]
check("an empty clueFragment passes under a preamble", not findings(pz))
check("and is refused without one", len(findings({**pz, "preamble": ""})) == 1)
# explanation.walkthrough is optional: the blocks may say it all.
pz2 = F.read_puzzle_file(src)
for x in pz2["entries"]:
    (x.get("annotation") or {}).pop("explanation", None)
pz2 = puzzle_schema.prune(pz2)
with contextlib.redirect_stdout(io.StringIO()):
    errs2 = V.validate_puzzle(pz2)[1]
check("no explanation at all is not a finding",
      not [x for x in puzzle_schema.validate(pz2) + errs2 if "explanation" in x or "walkthrough" in x])
# An `alteration` in the _ann object lands on the stored entry.
import json, shutil, tempfile
import groups
tmp = Path(tempfile.mkdtemp())
try:
    src = F.resolve_puzzle("cryptic-23340")
    path = tmp / src.name
    shutil.copy(src, path)
    pz3 = F.read_puzzle_file(path)
    cont = groups.leader_of(pz3["entries"])
    full = {groups.entry_id(x): x.get("annotation") for x in pz3["entries"]
            if groups.entry_id(x) not in cont}
    victim = next(x for x in pz3["entries"] if x.get("alteration") and x.get("annotation"))
    vid, alt = groups.entry_id(victim), victim["alteration"]
    del victim["alteration"]
    F.write_puzzle_file(path, pz3)
    A.apply(path, {**full, vid: {**full[vid], "alteration": alt}}, by="human")
    got = next(x for x in F.read_puzzle_file(path)["entries"] if groups.entry_id(x) == vid)
    check("alteration moves onto the entry", got.get("alteration") == alt)
    check("and is not left in the annotation", "alteration" not in got["annotation"])
finally:
    shutil.rmtree(tmp)
raise SystemExit(1 if fails else 0)
PY
