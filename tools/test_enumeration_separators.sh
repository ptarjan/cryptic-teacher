#!/bin/bash
# Do word breaks read off a clue's printed enumeration land where the paper puts them?
#
#     bash tools/test_enumeration_separators.sh
#
# Metro and the Private Eye ship clue text but no word breaks, so
# fetch_puzzle.enumeration_separators() reads "(5,4)" off the clue. Without it
# every phrase there is one word to the grid, the letter strip and the scorer.
set -uo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import sys

sys.path.insert(0, "tools")
from fetch_puzzle import enumeration_separators

fails = 0


def check(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        fails += 1
        print(f"FAIL: {name}: got {got!r}, want {want!r}")


def seps(*entries):
    es = [{**e, "clue": {"text": e["clue"]}} for e in entries]
    enumeration_separators(es)
    return [e["clue"].get("separators") for e in es]


check("a phrase in one light", seps({"id": "1", "length": 9, "clue": "Foo bar (5,4)"}),
      [[{"at": 5, "mark": ","}]])
check("hyphens and commas together",
      seps({"id": "1", "length": 13, "clue": "Q (5-2-3,3)"}), [[{"at": 5, "mark": "-"}, {"at": 7, "mark": "-"}, {"at": 10, "mark": ","}]])
check("a single word gets none", seps({"id": "1", "length": 5, "clue": "Q (5)"}), [None])
check("an apostrophe is not a break", seps({"id": "1", "length": 5, "clue": "Q (1'4)"}), [None])
check("a total that fits nothing is left alone",
      seps({"id": "1", "length": 6, "clue": "Q (3,4)"}), [None])
check("a clue with no enumeration is left alone",
      seps({"id": "1", "length": 6, "clue": "Q"}), [None])
check("a group's enumeration is split across its lights",
      seps({"id": "1", "length": 7, "clue": "Q (4,3,5)", "group": ["1", "2"]},
           {"id": "2", "length": 5, "clue": "See 1"}),
      [[{"at": 4, "mark": ","}, {"at": 7, "mark": ","}], None])
check("a continuation printing the whole answer's count splits nothing",
      seps({"id": "9", "length": 4, "clue": "x", "group": ["9", "8"]},
           {"id": "8", "length": 4, "clue": "Q (3,5)"}),
      [None, None])
check("a group head whose own light is the phrase",
      seps({"id": "1", "length": 10, "clue": "Q (7,3)", "group": ["1", "2"]},
           {"id": "2", "length": 4, "clue": "(see 1) (4)"}),
      [[{"at": 7, "mark": ","}], None])
es = [{"id": "1", "length": 9, "clue": {"text": "Q (5,4)", "italics": [{"at": 0, "length": 1}]},
       "solution": "ABCDEFGHI"}]
enumeration_separators(es)
check("written inside the clue, between its text and its italics",
      list(es[0]["clue"]), ["text", "separators", "italics"])
es = [{"id": "1", "length": 9, "clue": {"text": "Q (5,4)"}, "solution": "ABCDEFGHI"}]
enumeration_separators(es)
check("the entry's own keys are untouched", list(es[0]), ["id", "length", "clue", "solution"])

print(f"FAILED: {fails}" if fails else "all ok")
sys.exit(1 if fails else 0)
PY
