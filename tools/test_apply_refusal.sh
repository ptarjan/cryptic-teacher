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

# A cold solve's stated definition must sit at one end of its clue: the one
# that defined HALLWAY by the middle words "entrance area" is refused.
import apply_solution
hw = fetch_puzzle.read_puzzle_file(fetch_puzzle.resolve_puzzle("everyman-4168"))
hw = {**hw, "entries": [e for e in hw["entries"] if groups.entry_id(e) == "15-across"]}
got = apply_solution.check_definitions(hw, {"15-across": "entrance area"})
check("middle definition refused", len(got) == 1 and "sits in the middle" in got[0])
check("end definition passes", not apply_solution.check_definitions(hw, {"15-across": "At midpoint"}))
check("definition not in the clue refused",
      "not words of the clue" in "".join(apply_solution.check_definitions(hw, {"15-across": "corridor"})))
answers, defs = apply_solution.split_fill({"15-across": "HALLWAY"})
check("bare answer string needs a definition",
      apply_solution.check_definitions(hw, defs) == ["15-across: no definition given"])
see = {**hw, "entries": [{**hw["entries"][0], "clue": {"text": "See 5"}}]}
check("a See clue needs none", not apply_solution.check_definitions(see, {}))
sys.exit(fails)
PY
rc=$?
[ $rc = 0 ] && echo "apply_refusal: all checks passed" || echo "apply_refusal: FAILED"
exit $rc
