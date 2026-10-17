#!/usr/bin/env python3
# The shape re-annotation list (tools/shape_queue.py): a listed clue is written
# by a run on its hinted puzzle, the old hint is never lost, and a filed clue
# leaves the list. The queue tier's ordering is in prereset_plan.py --self-test.
#
#     python3 tools/test_shape_queue.py
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))

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
# A rewrite must not give up what the old tree had (Q.regressions): the weak
# fixes audited on the first burn, trees taken from their before/after pairs.
def leaf(w, g=None, **kw): return {"words": w, "gives": g, **kw} if g else {"words": w, **kw}
def ann(wp, defs=("x",), **kw): return {"definitions": [{"text": d} for d in defs], "wordplay": wp, **kw}
def ent(clue, old): return {"clue": {"text": clue}, "annotation": old}
cases = [
  ("22257 8d: an unchecked leaf deleted", "Quite good translation of 100",
   ann({"op": "charade", "parts": [leaf("translation", unchecked=True), leaf("of", "DE"), leaf("100", "CENT")]}, ("Quite good",)),
   ann({"op": "charade", "parts": [leaf("of", "DE"), leaf("100", "CENT")]}, ("Quite good",)), "translation"),
  ("22425 10a: 'the' dropped", "Moral tale has the bloody lot on ecstasy",
   ann({"op": "charade", "parts": [leaf("the", unchecked=True), leaf("lot", "ALL"), leaf("ecstasy", "E"), leaf("bloody", "GORY")]}, ("Moral tale",)),
   ann({"op": "charade", "indicators": [{"text": "on"}], "parts": [leaf("lot", "ALL"), leaf("ecstasy", "E"), leaf("bloody", "GORY")]}, ("Moral tale",)), "the"),
  ("22139 20a: wordplay nulled", "Fast runner doesn't sound honest",
   ann({"op": "homophone", "spelt": "CHEETAH", "indicators": [{"text": "sound"}], "parts": [leaf("doesn't sound honest", "CHEATER")]}, ("Fast runner",)),
   {"definitions": [{"text": "Fast runner"}]}, "no_tree"),
  ("16642 15a: leaf cut to one word", "Two outspoken characters gelling together in a German town",
   ann({"op": "homophone", "spelt": "ESSEN", "indicators": [{"text": "outspoken"}], "parts": [leaf("Two outspoken characters gelling together", "SN")]}, ("a German town",)),
   ann({"op": "homophone", "spelt": "ESSEN", "indicators": [{"text": "outspoken"}], "parts": [leaf("characters", "SN")]}, ("a German town",)), "gelling"),
  ("22225 11a: spoonerism relabelled", "Hawk Spooner's cruel registrar or priest",
   ann({"op": "spoonerism", "indicators": [{"text": "Spooner's"}], "parts": [leaf("cruel registrar or priest", "HARSHMARRIER")]}, ("Hawk",)),
   ann({"op": "homophone", "spelt": "MARSHHARRIER", "indicators": [{"text": "Spooner's"}], "parts": [leaf("cruel registrar or priest", "HARSHMARRIER")]}, ("Hawk",)), "lost_spoonerism"),
  ("16018 26a: an indicator dropped with the structure", "No plain girl worked without a kitchen tool",
   ann({"op": "anagram", "indicators": [{"text": "worked"}], "parts": [{"op": "deletion", "indicators": [{"text": "without"}], "parts": [leaf("No"), leaf("plain"), leaf("girl"), leaf("a")]}]}, ("kitchen tool",)),
   ann({"op": "composite", "indicators": [{"text": "worked"}], "parts": [leaf("No plain girl"), leaf("a")]}, ("kitchen tool",)), "without"),
]
for name, clue, old, new, word in cases:
    got = Q.regressions(ent(clue, old), new)
    check(f"refused: {name}", bool(got) and word in got[0])
good = ann({"op": "charade", "parts": [leaf("lot", "ALL"), leaf("the", "T")]}, ("Moral tale",))
check("kept words, relabelled, pass", not Q.regressions(ent("Moral tale the lot", good), json.loads(json.dumps(good))))
check("a word moved into the definition passes",
      not Q.regressions(ent("Quite good translation of 100", cases[0][2]),
                        ann({"op": "charade", "parts": [leaf("of", "DE"), leaf("100", "CENT")]}, ("Quite good translation",))))
check("a Spooner clue with a spoonerism passes",
      not Q.regressions(ent(cases[4][1], cases[4][2]), json.loads(json.dumps(cases[4][2]))))
# 24a of book-16004: "Assign no Gospels?" is a double definition, two definitions and no tree.
allot = ent("Assign no Gospels?", {"definitions": [{"text": "Assign"}],
            "wordplay": {"words": "no Gospels", "gives": "ALLOT"}})
check("a double definition with no tree passes",
      not Q.regressions(allot, {"definitions": [{"text": "Assign"}, {"text": "no Gospels"}]}))
check("one definition with no tree is still refused",
      bool(Q.regressions(allot, {"definitions": [{"text": "Assign"}]})))
check("two definitions leaving a clue word uncovered are refused",
      bool(Q.regressions(allot, {"definitions": [{"text": "Assign"}, {"text": "Gospels"}]})))

# pending() is memoized per rows() list; a changed file rebuilds it.
Q.PATH.write_text(json.dumps([{"id": "m-1#1a", "reason": "x"}]))
check("pending is built from the rows", Q.pending() == {"m-1": {"1a": "x"}})
check("and reused while the rows are unchanged", Q.pending() is Q.pending())
Q.PATH.write_text(json.dumps([{"id": "m-1#1a", "reason": "x", "tried": True}, {"id": "m-2#2d", "reason": "yy"}]))
check("a changed file rebuilds it", Q.pending() == {"m-2": {"2d": "yy"}})

print("FAILED" if fails else "shape queue: all pass")
raise SystemExit(1 if fails else 0)
