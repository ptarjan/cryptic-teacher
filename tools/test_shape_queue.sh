#!/bin/bash
# The shape re-annotation list (tools/shape_queue.py): a listed clue is written
# by a run on its hinted puzzle, the old hint is never lost, and a filed clue
# leaves the list. The queue tier's ordering is in prereset_plan.py --self-test.
#
#     bash tools/test_shape_queue.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools python3 - <<'PY'
import json, shutil, tempfile
from pathlib import Path
import apply_annotations as A
import annotate_check as AC
import fetch_puzzle as F
import groups
import shape_queue as Q

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

tmp = Path(tempfile.mkdtemp())
A.TOOLS = tmp
Q.PATH = tmp / "shape_reannotate.json"
for src in F.puzzle_files():
    puzzle = F.read_puzzle_file(src)
    cont = groups.leader_of(puzzle["entries"])
    clues = [e for e in puzzle["entries"] if groups.entry_id(e) not in cont]
    if len(clues) >= 6 and F.puzzle_is_annotated(puzzle) and all(e.get("annotation") for e in clues):
        break
path = tmp / src.name
shutil.copy(src, path)
a, b = clues[0], clues[1]
aid, bid = groups.entry_id(a), groups.entry_id(b)
Q.PATH.write_text(json.dumps([
    {"id": f"{puzzle['id']}#{Q.clue_key(a)}", "reason": "del_single: test"},
    {"id": f"{puzzle['id']}#{Q.clue_key(b)}", "reason": "old", "tried": True}]))

view = json.loads(AC.write_view(path).read_text())
check("a fully hinted puzzle writes just the listed clue", view.get("annotateOnly") == [aid])
check("the tried clue is not redone", bid not in view.get("annotateOnly", []))
check("the view says why", "del_single: test" in view.get("flagged", {}).get(aid, ""))

full = {groups.entry_id(e): e["annotation"] for e in clues}
pz = F.read_puzzle_file(path)
pz_before = json.dumps(pz["entries"], sort_keys=True)

# A null for a listed clue keeps the hint on the site.
A.apply(path, {aid: None}, by="human")
check("a null leaves the old hint live",
      json.dumps(F.read_puzzle_file(path)["entries"], sort_keys=True) == pz_before)
check("and the clue stays listed", aid in Q.flagged(pz))

# A refused write (bad wordplay) changes nothing and keeps the row.
try:
    A.apply(path, {aid: {"definitions": [], "wordplay": {"op": "bogus"}}}, by="human")
except BaseException:
    pass
check("a refused write keeps the old hint",
      json.dumps(F.read_puzzle_file(path)["entries"], sort_keys=True) == pz_before)
check("and the row", aid in Q.flagged(pz))

# A filed annotation settles the row: pruned, or marked tried if still flagged.
A.apply(path, {aid: full[aid]}, by="human")
check("a filed clue leaves the pending list", aid not in Q.flagged(pz))
check("the list did not grow", len(json.loads(Q.PATH.read_text())) <= 2)
print("FAILED" if fails else "shape queue: all pass")
raise SystemExit(1 if fails else 0)
PY
