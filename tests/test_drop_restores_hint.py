#!/usr/bin/env python3
# A failed redo of a clue that already had a committed hint puts that hint back
# (tools/drop_failed_clues.py); only a never-hinted clue is left blank.
#
#     python3 tests/test_drop_restores_hint.py
import copy
import os
import sys

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "tools")
import drop_failed_clues as D
import fetch_puzzle as F
import groups
import puzzle_paths
import validate_annotations as V

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

def fully_hinted(path):
    p = F.read_puzzle_file(path)
    return len(p["entries"]) > 6 and all("annotation" in e for e in p["entries"])

src = next(p for p in sorted(puzzle_paths.PUZZLE_DIR.rglob("*.json")) if fully_hinted(p))
good = F.read_puzzle_file(src)
ids = [groups.entry_id(e) for e in good["entries"]]
x, y = ids[2], ids[4]

committed = copy.deepcopy(good)
for e in committed["entries"]:
    if groups.entry_id(e) == y:
        e.pop("annotation", None)          # y was never hinted

bad = copy.deepcopy(good)
for e in bad["entries"]:
    if groups.entry_id(e) in (x, y):
        e["annotation"]["definitions"][0]["text"] = "zzz not in the clue"
check("both bad hints fail", len(V.run_errors(src, bad)) == 2)

got = D.dropped_clues(src, bad, committed)
by = {groups.entry_id(e): e for e in got[0]["entries"]}
want = {groups.entry_id(e): e for e in committed["entries"]}
check("the committed hint comes back", by[x].get("annotation") == want[x].get("annotation"))
check("a never-hinted clue is blanked", "annotation" not in by[y])
check("both are reported", got[1] == {x, y})

# The committed hint fails too: blanked rather than looping.
got = D.dropped_clues(src, bad, copy.deepcopy(bad))
by = {groups.entry_id(e): e for e in got[0]["entries"]}
check("a committed hint that fails as well is blanked",
      "annotation" not in by[x] and "annotation" not in by[y])
print("drop_restores_hint: all checks passed" if not fails else "drop_restores_hint: FAILED")
raise SystemExit(1 if fails else 0)
