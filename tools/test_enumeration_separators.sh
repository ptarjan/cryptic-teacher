#!/bin/bash
# Do word breaks read off a clue's printed enumeration land where the paper puts them?
#
#     bash tools/test_enumeration_separators.sh
#
# Metro and the Private Eye ship clue text but no word breaks, so
# fetch_puzzle.enumeration_separators() reads "(5,4)" off the clue. Without it
# every phrase there is one word to the grid, the letter strip and the scorer.
# An apostrophe is an "'" mark, never a "," (puzzle_integrity.check_apostrophes).
set -uo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import sys

sys.path.insert(0, "tools")
from fetch_puzzle import enumeration_separators
import enumeration

fails = 0


def check(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        fails += 1
        print(f"FAIL: {name}: got {got!r}, want {want!r}")


def seps(*entries):
    es = [{**e, "clue": enumeration.clue(e["clue"])} for e in entries]
    enumeration_separators(es)
    return [e["clue"].get("separators") for e in es]


check("a phrase in one light", seps({"number": 1, "direction": "across", "length": 9, "clue": "Foo bar (5,4)"}),
      [[{"at": 5, "mark": ","}]])
check("hyphens and commas together",
      seps({"number": 1, "direction": "across", "length": 13, "clue": "Q (5-2-3,3)"}), [[{"at": 5, "mark": "-"}, {"at": 7, "mark": "-"}, {"at": 10, "mark": ","}]])
check("a single word gets none", seps({"number": 1, "direction": "across", "length": 5, "clue": "Q (5)"}), [None])
check("an apostrophe is its own mark", seps({"number": 1, "direction": "across", "length": 5, "clue": "Q (1'4)"}),
      [[{"at": 1, "mark": "'"}]])
check("an apostrophe beside a word break",
      seps({"number": 1, "direction": "across", "length": 15, "clue": "Q (6,1'8)"}),
      [[{"at": 6, "mark": ","}, {"at": 7, "mark": "'"}]])
check("a total that fits nothing is left alone",
      seps({"number": 1, "direction": "across", "length": 6, "clue": "Q (3,4)"}), [None])
check("a clue with no enumeration is left alone",
      seps({"number": 1, "direction": "across", "length": 6, "clue": "Q"}), [None])
check("a group's enumeration is split across its lights",
      seps({"number": 1, "direction": "across", "length": 7, "clue": "Q (4,3,5)", "group": ["1-across", "2-across"]},
           {"number": 2, "direction": "across", "length": 5, "clue": "See 1"}),
      [[{"at": 4, "mark": ","}, {"at": 7, "mark": ","}], None])
check("a continuation printing the whole answer's count splits nothing",
      seps({"number": 9, "direction": "across", "length": 4, "clue": "x", "group": ["9-across", "8-across"]},
           {"number": 8, "direction": "across", "length": 4, "clue": "Q (3,5)"}),
      [None, None])
check("a group head whose own light is the phrase",
      seps({"number": 1, "direction": "across", "length": 10, "clue": "Q (7,3)", "group": ["1-across", "2-across"]},
           {"number": 2, "direction": "across", "length": 4, "clue": "(see 1) (4)"}),
      [[{"at": 7, "mark": ","}], None])
es = [{"number": 1, "direction": "across", "length": 9, "clue": {"text": "Q", "enumeration": "5,4", "italics": [{"at": 0, "length": 1}]},
       "solution": "ABCDEFGHI"}]
enumeration_separators(es)
check("written inside the clue, between its enumeration and its italics",
      list(es[0]["clue"]), ["text", "enumeration", "separators", "italics"])
es = [{"number": 1, "direction": "across", "length": 9, "clue": {"text": "Q", "enumeration": "5,4"}, "solution": "ABCDEFGHI"}]
enumeration_separators(es)
check("the entry's own keys are untouched", list(es[0]), ["number", "direction", "length", "clue", "solution"])

# Every writer's path to an apostrophe mark, and the integrity check that
# refuses a write where one is missing.
from fetch_puzzle import separators
from normalise_linked_enumerations import enumeration_parts, format_parts
import puzzle_integrity

check("separators() over a curly apostrophe", separators("6,1\u20198", [15]),
      [[{"at": 6, "mark": ","}, {"at": 7, "mark": "'"}]])
check("separators() splits an apostrophe across a group", separators("2,5,1'6", [7, 7]),
      [[{"at": 2, "mark": ","}, {"at": 7, "mark": ","}], [{"at": 1, "mark": "'"}]])
check("enumeration_parts keeps the apostrophe", enumeration_parts("6-1'8"), [(6, "-"), (1, "'"), (8, "")])
check("format_parts writes it back", format_parts(enumeration_parts("1'3-1-4")), "1'3-1-4")


def apostrophe_flags(*entries):
    flags = []
    puzzle_integrity.check_apostrophes({"id": "t", "entries": [
        {"number": n, "direction": d, "length": ln, "clue": c, **({"group": g} if g else {})}
        for n, d, ln, c, g in entries]}, flags)
    return [what for _, _, what in flags]


bad = (10, "across", 15, {"text": "Q", "enumeration": "6,1'8",
                          "separators": [{"at": 6, "mark": ","}, {"at": 7, "mark": ","}]}, None)
check("a comma where the enumeration prints an apostrophe is flagged", apostrophe_flags(bad),
      ["10-across: enumeration (6,1'8) prints an apostrophe at 10-across at 7; separators "
       "mark \"'\" at none and a break at 10-across at 7"])
check("the apostrophe mark passes", apostrophe_flags(
    (10, "across", 15, {"text": "Q", "enumeration": "6,1'8",
                        "separators": [{"at": 6, "mark": ","}, {"at": 7, "mark": "'"}]}, None)), [])
check("an apostrophe mark the enumeration does not print is flagged", len(apostrophe_flags(
    (1, "across", 6, {"text": "Q", "enumeration": "6", "separators": [{"at": 1, "mark": "'"}]}, None))), 1)
check("a group's apostrophe on its second light passes", apostrophe_flags(
    (9, "down", 7, {"text": "Q", "enumeration": "2,5,1'6", "separators": [{"at": 2, "mark": ","}, {"at": 7, "mark": ","}]},
     ["9-down", "13-down"]),
    (13, "down", 7, {"text": "See 9", "separators": [{"at": 1, "mark": "'"}]}, None)), [])
import json
real = json.load(open("puzzles/sundaytough/2024/sundaytough-107.json"))
for e in real["entries"]:
    if e["clue"].get("enumeration") == "6,1'8":
        e["clue"]["separators"] = bad[3]["separators"]
try:
    puzzle_integrity.refuse_bad_write(real)
    refused = ""
except ValueError as e:
    refused = str(e)
check("the write gate refuses it", "APOSTROPHE 10-across" in refused, True)

print(f"FAILED: {fails}" if fails else "all ok")
sys.exit(1 if fails else 0)
PY
