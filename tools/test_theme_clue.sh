#!/usr/bin/env bash
# themeClue: the entry whose clue states the theme, filed by hand on a themed
# puzzle that prints no preamble. It lets a block with no clue words stand as
# a preamble would, must name a worded entry, re-queues a recorded annotate
# failure, survives clues-only promotion, and no annotation may set or change it.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
from pathlib import Path
import apply_annotations
import clues_only
import failed_inputs
import puzzle_integrity
import puzzle_schema
import validate_annotations as v

import annotation

ENTRY = {"number": 1, "direction": "across", "position": {"x": 0, "y": 0}, "length": 7,
         "clue": {"text": "Instrument: zero on", "enumeration": "7"}, "solution": "BASSOON"}
# BASS is the theme's piece: no clue word gives it.
ANN = annotation.from_model({"def": "Instrument", "wp": "BASS + [zero]O + [on]ON",
                             "explanation": {"walkthrough": "w"}}, ENTRY)


def puzzle(**top):
    p = {"id": "nation-1", "number": 1, "date": "2020-01-01",
         "dimensions": {"rows": 1, "cols": 7},
         "source": {"url": "https://example.com/1"}, "solutions": {"origin": "official"},
         **top, "entries": [{**ENTRY, "annotation": copy.deepcopy(ANN)}]}
    return puzzle_schema.order(p)


def block_errors(p):
    return [e for e in v.validate_puzzle(p)[1] if "clueFragment" in e]


fails = 0
def check(name, ok, got=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else got)


got = block_errors(puzzle())
check("bare block without preamble or themeClue is refused", bool(got), got)
got = block_errors(puzzle(preamble="Five answers start with a fish."))
check("bare block with a preamble stands", not got, got)
got = block_errors(puzzle(themeClue="1-across"))
check("bare block with a themeClue stands", not got, got)
check("theme_source cites the clue", v.theme_source(puzzle(themeClue="1-across")) == "1-across")
check("schema takes an entry id", not [e for e in puzzle_schema.validate(puzzle(themeClue="1-across")) if "themeClue" in e])
check("schema refuses the short tag", any("themeClue" in e for e in puzzle_schema.validate(puzzle(themeClue="1A"))))

flags = []
puzzle_integrity.check_theme_clue(puzzle(themeClue="9-down"), flags)
check("integrity refuses an id the puzzle lacks", bool(flags), flags)
flags = []
puzzle_integrity.check_theme_clue(puzzle(themeClue="1-across"), flags)
check("integrity takes a worded entry", not flags, flags)

# The annotator may not add, change or drop it.
real = v.committed_top
for head, now, want in ((None, "1-across", True), ("1-across", None, True),
                        ("1-across", "1-across", False), (None, None, False)):
    v.committed_top = lambda path, h=head: puzzle(**({"themeClue": h} if h else {}))
    errs = []
    v.check_theme_clue_unchanged(puzzle(**({"themeClue": now} if now else {})), Path("x"), errs)
    check(f"HEAD {head} -> run {now} refused={want}", bool(errs) == want, errs)
v.committed_top = real

apply_annotations.read_puzzle_file = lambda path: puzzle()
try:
    apply_annotations.apply(Path("t-1.json"), {"1-across": None, "themeClue": "1-across"})
    check("apply refuses a themeClue key", False)
except SystemExit as err:
    check("apply refuses a themeClue key", "themeClue" in str(err), err)

# Filing it changes the failed-inputs hash, so a withdrawn run is due again.
before = failed_inputs.input_hash("t-1", ("puzzle", puzzle()))
after = failed_inputs.input_hash("t-1", ("puzzle", puzzle(themeClue="1-across")))
check("filing themeClue changes the failed-inputs hash", before != after)

# A clues-only record's themeClue reaches the grid puzzle, or refuses.
built = puzzle()
record = {"source": {"acquiredOn": "2026-10-13"}}
built["source"] = {"url": "https://example.com/1"}
clues_only.builder = lambda r: (lambda r, a: (copy.deepcopy(built), []))
p, probs = clues_only.promote({**record, "themeClue": "1-across"}, {})
check("promote carries themeClue", p and p.get("themeClue") == "1-across", probs)
p, probs = clues_only.promote({**record, "themeClue": "4-down"}, {})
check("promote refuses an id the grid lacks", p is None and probs, probs)
raise SystemExit(fails)
PY
echo "all themeClue checks passed"
