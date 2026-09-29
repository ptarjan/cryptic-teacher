#!/bin/bash
# A refused write must name entries by the id the _ann file uses, with no traceback.
#
#     bash tools/test_apply_refusal.sh
set -uo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import sys, copy, io
from pathlib import Path
sys.path.insert(0, "tools")
import apply_annotations as A, fetch_puzzle, puzzle_integrity, groups

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

# A real annotated puzzle whose first annotated entry loses its blocks.
for path in fetch_puzzle.puzzle_files():
    puzzle = fetch_puzzle.read_puzzle_file(path)
    idx = next((i for i, e in enumerate(puzzle["entries"])
                if "blocks" in (e.get("annotation") or {})), None)
    if idx is not None:
        break
del puzzle["entries"][idx]["annotation"]["blocks"]
eid = groups.entry_id(puzzle["entries"][idx])
try:
    puzzle_integrity.refuse_bad_write(puzzle)
    check("write refused", False)
except puzzle_integrity.RefusedWrite as err:
    msg = A.refusal(Path(path), puzzle, err)
    check("entry id named", f"{eid}: missing required key 'blocks'" in msg)
    check("says what to write", "annotate_prompt.md" in msg)
    check("no entries[N] path left", "entries[" not in msg)
    check("no Traceback", "Traceback" not in msg)
    print(msg)
sys.exit(fails)
PY
rc=$?
[ $rc = 0 ] && echo "apply_refusal: all checks passed" || echo "apply_refusal: FAILED"
exit $rc
