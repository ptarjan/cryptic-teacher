#!/usr/bin/env python3
# A worker run's bare number resolves to the run's own puzzle when papers share it.
#
#     python3 tools/test_resolve_task_puzzle.py
#
# tools/puzzle_worker.sh sets CT_TASK_PUZZLE; the cold-solve prompt shows
# `solve_packet.py <number>`, and a number two papers share used to cost the
# run a turn on "names more than one puzzle". Without the variable, or for a
# number that is not the task's, it is still an error: never a guess.
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import puzzle_paths as P

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

tmp = Path(tempfile.mkdtemp())
for series in ("nation", "everyman"):
    d = tmp / series / "2020"
    d.mkdir(parents=True)
    (d / f"{series}-3129.json").write_text("{}")
P.PUZZLE_DIR = tmp
os.environ.pop(P.TASK_ENV, None)

def refused(arg):
    try:
        P.resolve_puzzle(arg)
    except SystemExit as e:
        return "more than one" in str(e)
    return False

check("ambiguous bare number is an error with no task", refused("3129"))
os.environ[P.TASK_ENV] = "nation-3129"
check("the task's own puzzle wins", P.resolve_puzzle("3129").stem == "nation-3129")
check("an id still resolves as typed", P.resolve_puzzle("everyman-3129").stem == "everyman-3129")
os.environ[P.TASK_ENV] = "nation-9999"
check("another puzzle's task does not decide it", refused("3129"))
sys.exit(1 if fails else 0)
