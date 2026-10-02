#!/bin/bash
# What apply_annotations.normalize computes, so the run need not write it.
#
#     bash tools/test_ann_normalize.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools python3 - <<'PY'
import copy, itertools
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
raise SystemExit(1 if fails else 0)
PY
