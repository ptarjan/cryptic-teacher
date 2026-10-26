#!/usr/bin/env python3
# A re-annotation scoped to some clues (annotateOnly) writes just those, and a
# redo that is the same tree and letters in other words leaves the old hint as
# it was (10-16..18: ~17% of reruns rewrote clues that were not due, ~6% redid
# one into the same tree).
#
#     python3 tests/test_redo_unchanged.py
import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "tools")
import apply_annotations as A
import fetch_puzzle as F
import groups
import shape_queue as Q

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

# bones(): prose is not the tree.
old = {"definitions": [{"text": "d"}],
       "wordplay": {"op": "charade", "parts": [{"words": "x", "gives": "X", "at": 3, "note": "one"}]},
       "explanation": {"walkthrough": "w"}, "features": {"aptDefinition": False}}
reworded = copy.deepcopy(old)
reworded["wordplay"]["parts"][0]["note"] = "other words"
reworded["explanation"]["walkthrough"] = "new prose"
check("same tree, new prose: adds nothing", A.redo_adds_nothing(old, reworded))
check("identical: adds nothing", A.redo_adds_nothing(old, copy.deepcopy(old)))
for what, edit in [("letters", lambda a: a["wordplay"]["parts"][0].update(gives="Y")),
                   ("op", lambda a: a["wordplay"].update(op="anagram")),
                   ("position", lambda a: a["wordplay"]["parts"][0].update(at=4)),
                   ("unchecked flag", lambda a: a["wordplay"]["parts"][0].update(unchecked=True)),
                   ("definition", lambda a: a["definitions"][0].update(text="e"))]:
    changed = copy.deepcopy(reworded)
    edit(changed)
    check(f"a changed {what} is a real redo", not A.redo_adds_nothing(old, changed))
check("a clue listed for its walkthrough is redone for the prose",
      not A.redo_adds_nothing(old, reworded, "walkthrough: step unnamed"))
check("no old hint: nothing to keep", not A.redo_adds_nothing(None, reworded))

# apply(): a key outside annotateOnly never rewrites its clue.
tmp = Path(tempfile.mkdtemp())
A.TOOLS = tmp
Q.PATH = tmp / "shape_reannotate.json"
Q.PATH.write_text("[]")
for src in F.puzzle_files():
    puzzle = F.read_puzzle_file(src)
    cont = groups.leader_of(puzzle["entries"])
    clues = [e for e in puzzle["entries"] if groups.entry_id(e) not in cont]
    if len(clues) >= 6 and all(e.get("annotation") for e in clues):
        break
path = tmp / src.name
shutil.copy(src, path)
a, b = clues[0], clues[1]
aid, bid = groups.entry_id(a), groups.entry_id(b)
before = F.read_puzzle_file(path)
want_b = json.dumps(next(e for e in before["entries"] if groups.entry_id(e) == bid), sort_keys=True)

# The run sends b back as it is, but landing it would rewrite it (stand-in for
# the "at" and prose a normalisation derives).
landed = A.landed
def rewriting(ann, entry, entries, eid, errors):
    got = copy.deepcopy(landed(ann, entry, entries, eid, errors))
    if got is not None and eid == bid:
        got["explanation"] = {"walkthrough": "rewritten on landing"}
    return got
A.landed = rewriting
A.apply(path, {aid: a["annotation"], bid: copy.deepcopy(b["annotation"])}, by="human", only=[aid])
A.landed = landed
after = F.read_puzzle_file(path)
check("a clue outside annotateOnly stays byte for byte",
      json.dumps(next(e for e in after["entries"] if groups.entry_id(e) == bid), sort_keys=True) == want_b)

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
