#!/usr/bin/env bash
# definedByPreamble stands in for `definitions` only where the puzzle prints a
# preamble, and never beside a definition.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import puzzle_schema
import validate_annotations as v

def errors(ann, preamble=None):
    base = {"type": ["charade"], "answer": "TURNSTONE", "explanation": {"walkthrough": "w"},
            "assembly": {"pieces": ["TURNS", "TONE"]},
            "blocks": [{"clueFragment": "Changes", "gives": "TURNS"},
                       {"clueFragment": "colour", "gives": "TONE"}]}
    puzzle = {"id": "t-1", "entries": [{"number": 1, "direction": "across",
              "clue": {"text": "Changes colour", "enumeration": "9"}, "solution": "TURNSTONE",
              "annotation": {**base, **ann}}]}
    if preamble:
        puzzle["preamble"] = preamble
    return [e for e in v.validate_puzzle(puzzle_schema.order(puzzle))[1]
            if "definition" in e or "Preamble" in e or "preamble" in e]

fails = 0
def check(name, want_error, got):
    global fails
    ok = bool(got) == want_error
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else got)

check("flag with a preamble replaces the definition", False,
      errors({"definedByPreamble": True}, "Unclued answers are birds."))
check("flag without a preamble", True, errors({"definedByPreamble": True}))
check("flag beside a definition", True,
      errors({"definedByPreamble": True, "definitions": [{"text": "colour", "at": 8}]}, "Birds."))
check("flag false is not a spelling of absent", True,
      errors({"definedByPreamble": False, "definitions": [{"text": "colour", "at": 8}]}, "Birds."))
check("no flag, no definition", True, errors({}, "Birds."))
raise SystemExit(fails)
PY
echo "all definedByPreamble checks passed"
