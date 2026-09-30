#!/bin/bash
# Is each graded miss diagnosed exactly once?
#
# Drives tools/solve_misses.py against scratch copies of blind_misses.json and
# diagnosed_misses.json: a miss is pending until a verdict is recorded, a new
# grading surfaces only the new miss, and a verdict for an entry that was never
# missed is refused. Nothing in the checkout is written; the last check says so.
#
#     bash tools/test_solve_misses.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
tree_before=$(git status --porcelain)
scratch=$(mktemp -d "${TMPDIR:-/tmp}/solve-misses.XXXXXX")
trap 'rm -rf "$scratch"' EXIT

python3 - "$scratch" <<'EOF'
import json, sys
from pathlib import Path
sys.path.insert(0, "tools")
import solve_misses as sm

scratch = Path(sys.argv[1])
sm.MISSES = scratch / "blind_misses.json"
sm.DIAGNOSED = scratch / "diagnosed_misses.json"
fails = 0
def check(name, got, want):
    global fails
    print(f"  {'ok' if got == want else 'FAIL'}: {name}")
    if got != want:
        print(f"    expected: {want}\n    got:      {got}")
        fails += 1

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
sys.exit(1 if fails else 0)
EOF
rc=$?
if [ "$(git status --porcelain)" != "$tree_before" ]; then
  echo "  FAIL: the test wrote to the checkout"
  rc=1
else
  echo "  ok: nothing in the checkout was written"
fi
exit $rc
