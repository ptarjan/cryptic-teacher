#!/usr/bin/env bash
# An indicator's text may repeat in `indicators` only as often as the clue
# prints it: "about time? That is about time" signals two containers.
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

NOTE = "about means around, so each piece wraps around a T for time"
def repeat_errors(clue, times):
    ann = {"type": ["container"], "indicators": [{"text": "about", "for": "container", "note": NOTE}] * times}
    errors = []
    v.check_indicators("4D", ann, clue, errors, [])
    return [e for e in errors if "more often" in e]

TWICE = "Acrobatic toy was high – about time? That is about time (5,4)"
check("printed twice, listed twice", [], repeat_errors(TWICE, 2))
check("printed twice, listed three times", 1, len(repeat_errors(TWICE, 3)))
check("printed once, listed twice", 1, len(repeat_errors("Time about (4)", 2)))
raise SystemExit(fails)
PY
