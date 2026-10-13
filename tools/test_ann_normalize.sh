#!/bin/bash
# What apply_annotations.normalize computes, so the run need not write it.
#
#     bash tools/test_ann_normalize.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools python3 - <<'PY'
import copy
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

# A frozen copy (tools/fixtures/quiptic-619.json), so the corpus can move on under it.
src = Path("tools/fixtures/quiptic-619.json")
puzzle = F.read_puzzle_file(src)
by = {annotation.entry_id(e): e for e in puzzle["entries"]}

# The answer is the grid's: the model writes `answer` only to correct or
# respell it, and one that is not the grid's is refused.
e = by["11-across"]
m = {"def": "libellous", "wp": "ana<Fake>([folio]F + [made] + [a]) + [conservative]TORY"}
got = A.normalize(m, e, puzzle["entries"], puzzle=puzzle)
check("no answer written, none stored", "answer" not in got and "spelling" not in got)
check("the view's answer is the grid's", annotation.view(got, e, puzzle)["answer"] == "DEFAMATORY")
try:
    A.normalize({**m, "answer": "LIBELLOUS"}, e, puzzle["entries"], puzzle=puzzle)
    refused = ""
except wordplay.WordplayError as x:
    refused = str(x)
check("an answer that is not the grid's is refused", "not the grid's" in refused)
check("the input is not mutated", "answer" not in m)

# Clue words are written as the clue prints them, whatever the run typed.
got = A.normalize({"def": "LIBELLOUS", "wp": "ana<FAKE>([folio]F + [made] + [a]) + [Conservative]TORY"},
                  e, puzzle["entries"], puzzle=puzzle)
leaf = next(n for n in leaves(got["wordplay"]) if n.get("gives") == "TORY")
check("a leaf's case is the clue's", leaf["words"] == "conservative")
check("an indicator's case is the clue's", got["wordplay"]["parts"][0]["indicators"][0]["text"] == "Fake")
check("a definition's case is the clue's", got["definitions"][0]["text"] == "libellous")
curly = dict(by["16-down"], clue=dict(by["16-down"]["clue"], text=by["16-down"]["clue"]["text"].replace("'", "’")))
got = A.normalize({"def": "disfigurement", "wp": "ins<restricted by>([frightening]SCARING, [King's]R)"},
                  curly, puzzle["entries"], puzzle=puzzle)
check("a leaf's typed apostrophe is the clue's",
      any(n.get("words") == "King’s" for n in leaves(got["wordplay"])))

# A leaf with no words is letters the preamble supplies.
import contextlib, io
import puzzle_schema, validate_annotations as V
i = next(i for i, x in enumerate(puzzle["entries"])
         if any(n.get("words") and not n.get("unchecked")
                for n in leaves((x.get("annotation") or {}).get("wordplay") or {"words": ""})))
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
# explanation.walkthrough is optional: the wordplay may say it all.
pz2 = F.read_puzzle_file(src)
for x in pz2["entries"]:
    (x.get("annotation") or {}).pop("explanation", None)
pz2 = puzzle_schema.prune(pz2)
with contextlib.redirect_stdout(io.StringIO()):
    errs2 = V.validate_puzzle(pz2)[1]
check("no explanation at all is not a finding",
      not [x for x in puzzle_schema.validate(pz2) + errs2 if "explanation" in x or "walkthrough" in x])
# An `alteration` in the _ann object lands on the stored entry.
import shutil, tempfile
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
