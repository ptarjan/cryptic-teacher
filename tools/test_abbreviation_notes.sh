#!/usr/bin/env bash
# Is an abbreviation gloss derived from the table, never stored?
#
#     bash tools/test_abbreviation_notes.sh
#
# A format v2 leaf whose clue words -> letters pair is in
# build_abbreviations.table() needs no note: annotation.view() shows
# ABBREVIATION_GLOSS. A stored note that only restates it is refused by
# validate_annotations, dropped by from_model (and to_model, and
# convert_v2.check), and stripped from the corpus by strip_abbreviation_notes.py.
# A note that adds anything (a domain, a source) stays. All in memory, on a
# copy of quiptic-619 (11-across: [folio]F).
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
import json
from pathlib import Path

import annotation as A
import fetch_puzzle as fp
import puzzle_paths
import strip_abbreviation_notes as S
import validate_annotations as V
import wordplay as W

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else detail)

p = fp.read_puzzle_file(puzzle_paths.find("quiptic-619"))
S.strip_puzzle(p)  # the puzzle as migrated, whether or not the corpus is yet
i = next(k for k, e in enumerate(p["entries"]) if e["number"] == 11 and e["direction"] == "across")
e = p["entries"][i]
folio = lambda ann: ann["wordplay"]["parts"][0]["parts"][0]["parts"][0]

def with_note(note):
    q = copy.deepcopy(p)
    leaf = folio(q["entries"][i]["annotation"])
    assert leaf["words"] == "folio" and leaf["gives"] == "F", leaf
    if note is None:
        leaf.pop("note", None)
    else:
        leaf["note"] = note
    return q

def block(q):
    v = A.view(q["entries"][i]["annotation"], q["entries"][i], q)
    return next(b for b in v["blocks"] if b.get("clueFragment") == "folio")

# The table holds folio F and with W; it does not hold deserted D.
check("the table holds folio F", A.is_abbreviation({"words": "folio", "gives": "F"}))
check("a pair the table lacks is no abbreviation", not A.is_abbreviation({"words": "deserted", "gives": "D"}))

# view(): a leaf with no note shows the gloss; a stored note wins.
bare = with_note(None)
check("view shows the table's gloss on a bare leaf",
      block(bare).get("note") == "F is a standard abbreviation for folio", block(bare))
kept = with_note("F is the abbreviation for folio, as printed on old books")
check("view keeps a note that adds something", block(kept)["note"].endswith("old books"), block(kept))
check("a clue-initial capital reads in lower case",
      A.abbreviation_gloss({"words": "With", "gives": "W", "at": 0}) == "W is a standard abbreviation for with")
check("a capital mid-clue is kept",
      A.abbreviation_gloss({"words": "Conservative", "gives": "C", "at": 9}) == "C is a standard abbreviation for Conservative")

# restates_abbreviation: precise both ways.
leaf = lambda note, w="folio", g="F": {"words": w, "gives": g, "note": note}
for note in ("F is the abbreviation for folio", "F is the standard abbreviation for folio.",
             "F is a recorded abbreviation for folio", "standard abbreviation", "abbreviation for folio",
             "F = folio", "F abbreviates folio", "F is short for folio", "the usual abbreviation",
             "f. is the dictionary abbreviation of 'folio'"):
    check(f"restates: {note!r}", A.restates_abbreviation(leaf(note)))
for note in ("F is the abbreviation for folio, as printed on old books", "F is the paper-size abbreviation for folio",
             "a folio is a sheet folded once", "F for folio, the page size; then reversed"):
    check(f"adds something: {note!r}", not A.restates_abbreviation(leaf(note)))
check("a note on a pair the table lacks stays (deserted D)",
      not A.restates_abbreviation(leaf("D is a recorded abbreviation for deserted", "deserted", "D")))

# A run's own puzzle: until the corpus is stripped, only a note the committed
# file does not hold is refused, so files still carrying them keep validating.
path = puzzle_paths.find("quiptic-619")
V.ABBREVIATION_NOTES_STRIPPED = False
run = []
V.check_no_new_abbreviation_notes(with_note("F stands for folio"), path, run)
check("a run's new restating note is refused", len(run) == 1 and "11-across" in run[0], run)
run = []
V.check_no_new_abbreviation_notes(fp.read_puzzle_file(path), path, run)
check("notes the committed file holds are not a run's", run == [], run)

# Once stripped, the validator refuses the restating note anywhere and passes the bare leaf.
V.ABBREVIATION_NOTES_STRIPPED = True
def errors(q):
    _, errs, _ = V.validate_puzzle(q)
    return [m for m in errs if "restates the abbreviation table" in m]
check("validate refuses a note that restates the table",
      len(errors(with_note("F is the standard abbreviation for folio"))) == 1,
      errors(with_note("F is the standard abbreviation for folio")))
check("validate passes the bare leaf", errors(bare) == [], errors(bare))
check("validate passes a note that adds something", errors(kept) == [], errors(kept))

# from_model drops the note rather than failing; to_model never offers it.
m = A.to_model(with_note(None)["entries"][i]["annotation"])
m["notes"]["folio"] = "F is the standard abbreviation for folio"
got = A.from_model(copy.deepcopy(m), e, p)
check("from_model drops a restating note", "note" not in folio(got), folio(got))
m["notes"]["folio"] = "F is the abbreviation for folio, as printed on old books"
check("from_model keeps a note that adds something", "note" in folio(A.from_model(copy.deepcopy(m), e, p)))
check("to_model leaves a restating note out",
      "folio" not in A.to_model(with_note("F is the abbreviation for folio")["entries"][i]["annotation"]).get("notes", {}))

# The migration: strip_puzzle drops exactly those notes and is idempotent.
q = with_note("F is the abbreviation for folio")
dropped = S.strip_puzzle(q)
check("strip_puzzle drops the restating note", [d[1:3] for d in dropped] == [("folio", "F")], dropped)
check("a second strip finds nothing", S.strip_puzzle(q) == [])
check("strip leaves other notes", folio(kept["entries"][i]["annotation"]).get("note") and not S.strip_puzzle(kept))

print("abbreviation notes:", "all checks passed" if not fails else f"FAILED {fails}")
raise SystemExit(1 if fails else 0)
PY
