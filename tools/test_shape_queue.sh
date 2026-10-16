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
Q.REAL = Q.PATH
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
check("and the clue stays listed, marked tried", aid in Q.listed(pz) and aid not in Q.flagged(pz))

# A refused write (bad wordplay) changes nothing and keeps the row.
try:
    A.apply(path, {aid: {"definitions": [], "wordplay": {"op": "bogus"}}}, by="human")
except BaseException:
    pass
check("a refused write keeps the old hint",
      json.dumps(F.read_puzzle_file(path)["entries"], sort_keys=True) == pz_before)
check("and the row", aid in Q.listed(pz))

# A filed annotation the detectors pass settles the row.
check("this clue's tree passes the detectors", not Q.findings(a))
A.apply(path, {aid: full[aid]}, by="human")
check("a filed clue leaves the pending list", aid not in Q.flagged(pz))
check("the list did not grow", len(json.loads(Q.PATH.read_text())) <= 2)

# The detectors are the gate: a listed clue whose tree they still flag (a real
# row of the live list) cannot be re-filed with that tree, prose changed or not.
real = None
for r in (json.loads(Q.REAL.read_text()) if Q.REAL.exists() else [])[:50]:
    pid, _, ck = r["id"].partition("#")
    src2 = next(Path("puzzles").glob(f"**/{pid}.json"), None)
    if src2 is None:
        continue
    p2 = F.read_puzzle_file(src2)
    e2 = next((e for e in p2["entries"] if Q.clue_key(e) == ck and e.get("annotation")), None)
    if e2 is not None and Q.findings(e2):
        real = (src2, p2, e2, r)
        break
if real is None:
    print("  skip: no live row whose tree is still flagged (the list is clean)")
else:
    src2, p2, e2, r = real
    path2 = tmp / src2.name
    for old in tmp.glob(f"_*{p2['id']}.json"):
        old.unlink()
    shutil.copy(src2, path2)
    eid = groups.entry_id(e2)
    Q.PATH.write_text(json.dumps([r]))
    check("the run's view writes just that clue", json.loads(AC.write_view(path2).read_text()).get("annotateOnly") == [eid])
    before2 = json.dumps(F.read_puzzle_file(path2)["entries"], sort_keys=True)
    same = json.loads(json.dumps(e2["annotation"]))
    same.setdefault("explanation", {})["walkthrough"] = "new prose, same tree"
    try:
        A.apply(path2, {eid: same}, by="human")
        refused = False
    except SystemExit as err:
        refused = "shape re-annotation list" in str(err) and "same tree" in str(err)
    check(f"the old tree with new prose is refused ({r['id']})", refused)
    check("the file is unchanged", json.dumps(F.read_puzzle_file(path2)["entries"], sort_keys=True) == before2)
    check("the row is still pending", eid in Q.flagged(p2))
    A.apply(path2, {eid: None}, by="human")
    check("a null keeps the old hint", json.dumps(F.read_puzzle_file(path2)["entries"], sort_keys=True) == before2)
    check("and marks the row tried, so it is not requeued", eid not in Q.flagged(p2) and eid in Q.listed(p2))
    try:
        A.apply(path2, {eid: same}, by="human")
        refused = False
    except SystemExit:
        refused = True
    check("a tried row is still gated", refused)

# The row changes ship in the puzzle's commit: splice takes one puzzle's rows.
base = Q.dump([{"id": "p-1#1a", "reason": "x"}, {"id": "q-2#3d", "reason": "y"}, {"id": "p-1#2d", "reason": "z"}])
donor = Q.dump([{"id": "q-2#3d", "reason": "y", "tried": True}, {"id": "p-1#2d", "reason": "z", "tried": True}, {"id": "r-3#1a", "reason": "new elsewhere"}])
check("splice prunes and marks one puzzle's rows only",
      json.loads(Q.splice(base, donor, "p-1")) == [{"id": "q-2#3d", "reason": "y"},
                                                   {"id": "p-1#2d", "reason": "z", "tried": True}])
check("splice back to base is base", Q.splice(Q.splice(base, donor, "p-1"), base, "p-1") == base)

# Two commits pruning neighbouring rows merge per id (.gitattributes json-keys).
import json_merge as M
o = [{"id": f"p-{i}#1a", "reason": "r"} for i in range(4)]
got = json.loads(M.merge_rows(o, [o[0], o[2], o[3]], [o[0], o[1], {**o[2], "tried": True}]))
check("neighbouring prunes merge per id", got == [o[0], {**o[2], "tried": True}])
print("FAILED" if fails else "shape queue: all pass")
raise SystemExit(1 if fails else 0)
PY
