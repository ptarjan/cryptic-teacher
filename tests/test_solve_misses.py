#!/usr/bin/env python3
# Is each graded miss diagnosed exactly once, and does the solve prompt stay lean?
#
# Drives tools/solve_misses.py against scratch copies of blind_misses.json and
# diagnosed_misses.json: a miss is pending until a verdict is recorded, a new
# grading surfaces only the new miss, and a verdict for an entry that was never
# missed is refused. Nothing in the checkout is written; the last check says so.
#
#     python3 tests/test_solve_misses.py
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, str(REPO / "tools"))
import solve_misses as sm

rc = 0


def tree():
    return subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout


tree_before = tree()
scratch = Path(tempfile.mkdtemp(prefix="solve-misses."))
fails = 0


def check(name, got, want):
    global fails
    print(f"  {'ok' if got == want else 'FAIL'}: {name}")
    if got != want:
        print(f"    expected: {want}\n    got:      {got}")
        fails += 1


try:
    sm.MISSES = scratch / "blind_misses.json"
    sm.DIAGNOSED = scratch / "diagnosed_misses.json"

    sm.MISSES.write_text(json.dumps({"p-1": {"1-down": "ROOD"}}))
    check("an undiagnosed miss is pending", sm.pending(), [("p-1", "1-down")])
    sm.record("p-1", "1-down", "fixed", "a rule")
    check("a recorded verdict clears it", sm.pending(), [])
    check("the verdict keeps our answer", json.loads(sm.DIAGNOSED.read_text())["p-1"]["1-down"]["ours"], "ROOD")
    sm.MISSES.write_text(json.dumps({"p-1": {"1-down": "ROOD", "9-across": "X"}, "p-2": {"3-down": "Y"}}))
    check("a later grading surfaces only the new misses", sm.pending(),
          [("p-1", "9-across"), ("p-2", "3-down")])
    sys.argv = ["solve_misses.py", "record", "p-9", "1-across", "--verdict", "fixed", "--note", "n"]
    try:
        sm.main()
        refused = False
    except SystemExit as err:
        refused = bool(err.code)
    check("a verdict for an entry never missed is refused", refused, True)
finally:
    shutil.rmtree(scratch, ignore_errors=True)
if fails:
    rc = 1

if tree() != tree_before:
    print("  FAIL: the test wrote to the checkout")
    rc = 1
else:
    print("  ok: nothing in the checkout was written")
# Every solve reads all of solve_prompt.md, so the diagnoses that add rules to
# it must trade, not append.
words = len((REPO / "tools" / "solve_prompt.md").read_text().split())
if words > 500:
    print(f"  FAIL: tools/solve_prompt.md is {words} words, over the 500 cap")
    rc = 1
else:
    print(f"  ok: tools/solve_prompt.md is {words} words, within the 500 cap")
sys.exit(rc)
