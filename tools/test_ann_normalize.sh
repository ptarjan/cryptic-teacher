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

# A sample of stored puzzles: the answer derived from solution + enumeration
# is the one the annotators wrote, or differs only in where they left a break.
same = total = 0
bad = []
pick = None
for src in itertools.islice(F.puzzle_files(), 0, None, 400):
    puzzle = F.read_puzzle_file(src)
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
check(f"derived answer matches stored ({same}/{total})", same >= 0.95 * total)
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
# A block with no clueFragment is letters the preamble supplies.
import contextlib, io
import puzzle_schema, validate_annotations as V
for src in F.puzzle_files():
    pz = F.read_puzzle_file(src)
    ent = next((x for x in pz["entries"] if (x.get("annotation") or {}).get("blocks")
                and x["annotation"]["blocks"][0].get("gives")), None)
    if pz.get("preamble") and ent:
        break
ent["annotation"]["blocks"][0]["clueFragment"] = ""
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
