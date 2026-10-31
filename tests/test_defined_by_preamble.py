#!/usr/bin/env python3
# definedByPreamble stands in for `definitions` only where the puzzle prints a
# preamble, and never beside a definition.
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import os
import sys
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

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
            if "missing annotation field 'blocks'" not in e
            and ("definition" in e or "Preamble" in e or "preamble" in e)]

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

# The first check mends a flag that sits beside a definition in a puzzle with no preamble
# (annotate audit 10-30), and leaves every other shape to the validator.
import apply_annotations as A
defd = {"definedByPreamble": True, "definitions": [{"text": "colour", "at": 8}], "x": 1}
bare = {"definedByPreamble": True, "x": 1}
mended = A.drop_spare_preamble_flag(defd, {"entries": []})
check("spare flag beside a definition is dropped", False,
      [] if "definedByPreamble" not in mended and mended["definitions"] == defd["definitions"] else ["kept"])
check("flag with no definition stays (the preamble we lack)", False,
      [] if A.drop_spare_preamble_flag(bare, {"entries": []}) == bare else ["changed"])
check("a puzzle with a preamble is the validator's", False,
      [] if A.drop_spare_preamble_flag(defd, {"entries": [], "preamble": "Birds."}) == defd else ["changed"])
check("no puzzle given, nothing mended", False,
      [] if A.drop_spare_preamble_flag(defd, None) == defd else ["changed"])
# the refusal says what to write
msg = [e for e in v.validate_puzzle(puzzle_schema.order({"id": "t-1", "entries": [{"number": 1,
       "direction": "across", "clue": {"text": "Changes colour", "enumeration": "9"},
       "solution": "TURNSTONE", "annotation": {"definedByPreamble": True}}]}))[1]
       if "has no preamble" in e]
check("refusal keeps the alert's prefix and names the way out", False,
      [] if msg and "as `def` and drop the flag" in msg[0] else msg)
import discard_alert
check("discard_alert still reads it as the silent kind", False,
      [] if discard_alert.silent({}, msg) else msg)
if fails:
    raise SystemExit(fails)
print("all definedByPreamble checks passed")
