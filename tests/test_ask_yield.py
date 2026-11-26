#!/usr/bin/env python3
# Does edition_queue stop counting a reason as a VLM fill once its last finished reads averaged under one
# new VLM ask each (ask_dry, fed by ask_yield_note), keep it a fill with too little history, and keep the
# window in ~/.cache/corpus_queue/ask_yield.json across reloads?
#
#     python3 tests/test_ask_yield.py
#
# A temp HOME; no OCR, no VLM, no network, no pytest.
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
atexit.register(lambda: shutil.rmtree(_tmp, ignore_errors=True))
os.environ["HOME"] = _tmp  # before anything reads ~/.cache
os.environ.update(CT_LOCAL_CONFIG="/nonexistent", CT_AUTO_RELOAD="0")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import edition_queue as eq

fails = 0


def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")


FAR = "Gale Times page before 2014 refused for its clue columns, the strip right of the grid tried on it as a last window since"
NEW = "unfiled before its fix"


def unit(reason):
    return {"paper": "gale", "kind": "read", "rank": 2, "reason": reason, "needs": []}


path = eq.ask_yield_path()
check("the file lives under the fake HOME, not the live cache", True, str(path).startswith(_tmp))
check("no history: a fill", True, eq.fills_gpu(unit(FAR)))
for _ in range(2):
    eq.ask_yield_note(FAR, 0)
check("two finished reads is too few to judge: still a fill", True, eq.fills_gpu(unit(FAR)))
eq.ask_yield_note(FAR, 0)
check("three reads, 0 new asks each: no longer a fill", False, eq.fills_gpu(unit(FAR)))
check("another reason with no history is still one", True, eq.fills_gpu(unit(NEW)))
check("a unit that is not a read is not touched", False, eq.fills_gpu({**unit(FAR), "kind": "scan"}))
eq.ask_yield_note(FAR, 5)
check("5 asks over 4 reads (over one a read): a fill again", True, eq.fills_gpu(unit(FAR)))
eq.ask_yield_note(FAR, 0)
check("5 asks over 5 reads (one a read): a fill", True, eq.fills_gpu(unit(FAR)))
for _ in range(2):
    eq.ask_yield_note(FAR, 0)
check("5 asks over 7 reads: dry again", False, eq.fills_gpu(unit(FAR)))
for _ in range(6):
    eq.ask_yield_note(FAR, 0)
check("the window holds the last 8 reads", [0] * 8, eq.ask_yield_store()[FAR])
check("the window is on disk", [0] * 8, eq.ask_yield_load(path)[FAR])
eq._ASK_YIELD[:] = [None, {}]
check("a reload reads it back from the file: still dry", False, eq.fills_gpu(unit(FAR)))
path.write_text("not json")
eq._ASK_YIELD[:] = [None, {}]
check("a damaged file is no history: a fill", True, eq.fills_gpu(unit(FAR)))
check("hand exclusions kept: a LOW_ASK reason is no fill", False, eq.fills_gpu(unit(eq.LOW_ASK[0])))
for n in (3, 0, 2):
    eq.ask_yield_note(NEW, n)
check("a reason averaging 5/3 new asks a read stays a fill", True, eq.fills_gpu(unit(NEW)))
for k in range(eq.ASK_REASONS_MAX + 5):
    eq.ask_yield_note(f"r{k}", 1)
check("the file keeps at most ASK_REASONS_MAX reasons", eq.ASK_REASONS_MAX, len(eq.ask_yield_load(path)))
print("fails:", fails)
sys.exit(1 if fails else 0)
