#!/bin/bash
# Does a barred grid keep `checking` out of its difficulty rating?
#
#     bash tools/test_difficulty_barred.sh
#
# A barred grid is checked almost everywhere by convention, so its checking
# sits far below every blocked grid's and would rate every Listener Gentle.
set -uo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools python3 - <<'PY'
import sys
import difficulty as D

def puzzle(bars):
    entries = [{"position": {"x": 0, "y": 0}, "direction": "across", "length": 3},
               {"position": {"x": 0, "y": 0}, "direction": "down", "length": 3}]
    p = {"id": "x-1", "entries": entries}
    if bars:
        p["bars"] = [{"x": 1, "y": 0, "side": "right"}]
    return p

ctx = type("C", (), {"history": {}, "rank": {}})()
D.rarity = D.device = D.machinery = D.question_marks = D.definition_unrelated = D.clue_count = lambda *a: None
fails = 0
for name, want, got in [
        ("a blocked grid is scored on its checking", True, D.raw(puzzle(False), ctx)["checking"] is not None),
        ("a barred grid's checking is left out", None, D.raw(puzzle(True), ctx)["checking"])]:
    ok = want == got
    print(("  ok: " if ok else "  FAIL: ") + name + ("" if ok else f"\n    want {want}\n    got  {got}"))
    fails += not ok
sys.exit(1 if fails else 0)
PY
