#!/usr/bin/env python3
# The near-certain hidden words of tools/hidden_mechanical.py and the annotation
# tools/prefill_hidden.py builds from one.
import copy
import os
import sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import annotation
import hidden_mechanical as H
import prefill_hidden as P
import puzzle_schema
import validate_annotations as v

fails = 0
def check(name, want, got):
    global fails
    ok = want == got
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"want {want!r}, got {got!r}")

def parse(clue, answer):
    f = H.find(clue, answer)
    return f and (f["direction"], f["definition"], f["hidden"], f["reversal"], f["fodder"])

check("definition, indicator, fodder", ("forwards", "Chief", "some", None, "peculiar church"),
      parse("Chief of some peculiar church", "ARCH"))
check("fodder, indicator, definition", ("forwards", "narrow path", "A little", None, "climber manages"),
      parse("A little climber manages narrow path", "BERM"))
check("indicator after the fodder", ("forwards", "Scout", "to some extent", None, "leader eccentric"),
      parse("Scout leader eccentric to some extent", "RECCE"))
check("reversed under a reversal indicator", ("reversed", "Message from", None, "returned", "Australia, Melbourne"),
      parse("Message from Australia, Melbourne, returned", "EMAIL"))
check("no indicator, no parse", None, parse("Chief peculiar church", "ARCH"))
check("a run of whole words is no hidden word", None, parse("Is pinching it", "ITSA"))
check("under four letters is chance", None, parse("Chief of some peculiar church", "ARC"))
check("the answer inside one word is not across words", None, parse("Part of starting", "TART"))
check("a forward run does not read under a reversal indicator alone", None,
      parse("Message from Australia, Melbourne, returned", "AUSTRALIA"))

# A prefilled annotation lands through the model's own path and validates
# apart from the prose a model still writes (surface, definitionFit, features).
entry = {"number": 1, "direction": "across", "solution": "ARCH", "length": 4,
         "position": {"x": 0, "y": 0}, "clue": {"text": "Chief of some peculiar church", "enumeration": "4"}}
model = P.model_annotation(H.find(entry["clue"]["text"], "ARCH"), entry["clue"]["text"], "ARCH")
check("wordplay", "hid<some>([peculiar church]ARCH)", model["wp"])
check("definition", "Chief", model["def"])
check("reversed wordplay", "rev<returned>(hid([Australia, Melbourne]LIAME))",
      P.model_annotation(H.find("Message from Australia, Melbourne, returned", "EMAIL"),
                         "Message from Australia, Melbourne, returned", "EMAIL")["wp"])
stored = annotation.from_model(model, entry, {"entries": [entry]})
check("it evaluates to the answer", "hidden", stored["wordplay"]["op"])
# main() with --out on a tiny tree: one puzzle with a hidden word, one without clues.
import json, tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as tmp:
    src = next(Path("..", "puzzles").rglob("azed-2508.json"))
    (Path(tmp) / "in").mkdir()
    shutil_target = Path(tmp) / "in" / src.name
    shutil_target.write_text(src.read_text())
    (Path(tmp) / "in" / "junk.json").write_text("[]")
    out = Path(tmp) / "out"
    P.main(["--out", str(out), str(shutil_target), str(Path(tmp) / "in" / "junk.json")])
    written = sorted(f.name for f in out.glob("*.json"))
    check("main --out writes one file per prefilled puzzle", ["azed-2508.json"], written)
    check("has_unannotated skips junk", False, P.has_unannotated(Path(tmp) / "in" / "junk.json"))
    check("the file holds annotations", True, bool(json.loads((out / "azed-2508.json").read_text())))
if fails:
    sys.exit(1)
