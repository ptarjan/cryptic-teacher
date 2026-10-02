#!/bin/bash
# Is a barred grid's checking rated against barred grids, not blocked ones?
#
#     bash tools/test_difficulty_barred.sh
#
# A barred grid is checked far more by convention, so against the blocked
# grids' spread every Listener rated Gentle. More crossing letters still mean
# easier, against its own kind.
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

fails = 0
for name, want, got in [
        ("a blocked grid's checking is z-scored against the corpus", "checking", D.reference("checking", puzzle(False))),
        ("a barred grid's checking against the barred grids", "checking_barred", D.reference("checking", puzzle(True))),
        ("a barred grid's other components against the corpus", "rarity", D.reference("rarity", puzzle(True))),
        ("the baseline holds the barred grids' spread", True, "checking_barred" in D.load_baseline())]:
    ok = want == got
    print(("  ok: " if ok else "  FAIL: ") + name + ("" if ok else f"\n    want {want}\n    got  {got}"))
    fails += not ok
sys.exit(1 if fails else 0)
PY
