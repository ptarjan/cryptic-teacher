#!/usr/bin/env python3
# tools/fill_spellings.py: the spelling it writes where unambiguous, the grace for
# the lesson-check ratchets, and the burn leaving spelling.unsaid to the filler.
import os
import re
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import fill_spellings as F
import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

prose = lambda text: {"explanation": {"walkthrough": text}}
held = lambda sol, enum: {"solution": sol, "clue": {"text": "x", "enumeration": enum}}

check("a known spelling is filled", "GET SOMEONE'S GOAT",
      F.fillable(prose("to annoy someone"), held("GETSOMEONESGOAT", "3,7,4")))
check("a known spelling whose words the enumeration does not count is left", None,
      F.fillable(prose("to annoy someone"), held("GETSOMEONESGOAT", "3,7")))
check("an accent the prose writes is filled, in capitals", "FLÂNEUR",
      F.fillable(prose("a flâneur strolls"), held("FLANEUR", "7")))
check("a clue already carrying a spelling is not touched", None,
      F.fillable({**prose("a flâneur"), "spelling": "FLÂNEUR"}, held("FLANEUR", "7")))
check("two different spellings in the prose are ambiguous", None,
      F.fillable(prose("café or cafè"), held("CAFE", "4")))
check("a clue in a group is left", None,
      F.fillable(prose("a flâneur"), {**held("FLANEUR", "7"), "group": ["a", "b"]}))
check("prose spellings are distinct and upper case", ["FLÂNEUR"],
      F.L.prose_spellings(prose("a flâneur; the flâneur again"), "FLANEUR", "7"))

for field in ("wordplay.ddMissesWordplay", "spelling.unsaid"):
    check(f"{field} is in the shape grace", True, field in v.SHAPE_GRACE_FIELDS)

sh = open("prereset_backfill.sh").read()
check("the burn skips spelling.unsaid", True,
      bool(re.search(r"spelling\.unsaid\)[^\n]*continue ;;", sh)))
raise SystemExit(fails)
