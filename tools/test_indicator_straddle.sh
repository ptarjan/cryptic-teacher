#!/usr/bin/env bash
# An indicator may sit inside a definition (an &lit) but not across its edge,
# where app.js cannot mark both.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import validate_annotations as v

fails = 0
def check(name, want, clue, indicator, definition):
    global fails
    errors = []
    ann = {"definitions": [{"text": definition}], "indicators": [{"text": indicator}]}
    v.check_indicator_does_not_straddle_a_definition("1A", ann, clue, errors)
    ok = want == len(errors)
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else errors)

CLUE = "Spoil popular reefs in the middle of the sea"
check("across the definition's edge", 1, CLUE, "in the middle of", "of the sea")
check("clear of the definition", 0, CLUE, "in the middle", "of the sea")
check("inside the definition", 0, "What acknowledges performance of USA", "performance", "What acknowledges performance")
check("a free copy elsewhere", 0, "Of the sea, in the middle of reefs", "in the middle of", "Of the sea")
raise SystemExit(fails)
PY
