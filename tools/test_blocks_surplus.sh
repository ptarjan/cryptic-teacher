#!/usr/bin/env bash
# When a clue's blocks give too many letters and none too few, the warning names
# the single-block edits that take exactly the surplus away.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

def warned(answer, blocks, types=("charade",)):
    ann = {"type": list(types), "definitions": [{"text": "fixation"}], "blocks": blocks}
    entry = {"number": 10, "direction": "across", "solution": answer, "annotation": ann}
    errors, warnings = [], []
    v.check_blocks_account_for_answer([entry], errors, warnings)
    return warnings

w = warned("OBSESSION", [{"clueFragment": "old boys", "gives": "OBS"},
                         {"clueFragment": "meeting", "gives": "SESSION"}])
check("a doubled letter at a join: the edit that keeps answer order comes first", True,
      len(w) == 1 and "make the one the clue supports: block 'old boys' gives 'OB', not 'OBS'" in w[0]
      and "block 'meeting' gives 'ESSION', not 'SESSION'" in w[0])
w = warned("FLATBACK", [{"clueFragment": "apartment", "gives": "FLAT"},
                        {"clueFragment": "a", "gives": "A"},
                        {"clueFragment": "large tub", "gives": "BACK"}])
check("a surplus block: one edit, drop it", True,
      len(w) == 1 and "one edit makes them add up: drop block 'a' > 'A'" in w[0]
      and "note" not in w[0].split("drop block")[1])
w = warned("SCAR", [{"clueFragment": "vehicles", "gives": "CARS"},
                    {"clueFragment": "son", "gives": "S"}], ("cycling",))
check("a letter given twice: drop the block or cut the other", True,
      len(w) == 1 and "drop block 'son' > 'S'" in w[0] and "gives 'CAR', not 'CARS'" in w[0])
w = warned("NATTY", [{"clueFragment": "New York", "gives": "NY"},
                     {"clueFragment": "lawyer", "gives": "ATTY"}], ("container",))
check("a surplus no block can lose cleanly still names a cut", True,
      len(w) == 1 and "gives 'ATT', not 'ATTY'" in w[0])
w = warned("PANDA", [{"clueFragment": "father", "gives": "PA"}])
check("letters missing, none extra: no surplus edit", True, len(w) == 1 and "add up" not in w[0])
w = warned("CELT", [{"clueFragment": "cel", "gives": "LECR"}])
check("letters both extra and missing: no surplus edit", True, len(w) == 1 and "add up" not in w[0])
w = warned("OBSESSION", [{"clueFragment": "old boy", "gives": "OB"},
                         {"clueFragment": "meeting", "gives": "SESSION"}])
check("blocks already add up: no warning", [], w)
raise SystemExit(fails)
PY
