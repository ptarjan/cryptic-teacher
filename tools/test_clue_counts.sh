#!/bin/bash
# Does a clue that carries its own letter count, or a stray letter, get refused?
#
#     bash tools/test_clue_counts.sh
#
# A source that prints the count in the clue, with the answer's count appended
# after it, left "Set meal ... (5,1’4)" over enumeration "5,5"; one stray "d"
# stuck to a "?" came off the Telegraph's own feed. enumeration.split() cuts
# the echo, and puzzle_integrity (so every write) refuses what is left.
# A year or a quantity in brackets ("(1917)", "(500)") is the clue's words.
set -uo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import copy, json, sys

sys.path.insert(0, "tools")
import enumeration
import puzzle_integrity as pi

fails = 0


def check(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        fails += 1
        print(f"FAIL: {name}: got {got!r}, want {want!r}")


check("echoed count is cut", enumeration.split("Set meal (5,1’4) (5,5)"), ("Set meal", "5,5"))
check("prime and non-breaking marks read", enumeration.split("Whip (3-1′-4-5)"), ("Whip", "3-1'4-5"))
check("a different total is not an echo", enumeration.split("Platform (7) (5)"), ("Platform (7)", "5"))
clue = {"text": "Set meal (5,1’4)", "enumeration": "5,5"}
check("count under an enumeration is unsplit", enumeration.unsplit(clue, {10}), True)
check("a year is kept", enumeration.unsplit({"text": "Exile (1917)", "enumeration": "5"}, {5}), False)
check("a quantity is kept", enumeration.unsplit({"text": "Sheets (500)", "enumeration": "5"}, {5}), False)
check("a cross-reference is kept", enumeration.unsplit({"text": "See (3dn.)", "enumeration": "5"}, {5}), False)

puzzle = json.load(open("puzzles/telegraph/2013/telegraph-27152.json"))


def shape(p):
    flags = []
    pi.check_shape(p, pi.datetime.now(pi.timezone.utc).date(), flags)
    return [w for _, _, w in flags if "enumeration" in w or "stray" in w]


check("filed puzzle is clean", shape(puzzle), [])
bad = copy.deepcopy(puzzle)
c = bad["entries"][0]["clue"]
c["text"] += f" ({c['enumeration']})"
check("a repeated count is refused", len(shape(bad)), 1)
bad = copy.deepcopy(puzzle)
bad["entries"][0]["clue"]["text"] += "?d"
check("a stray letter is refused", len(shape(bad)), 1)
sys.exit(1 if fails else 0)
PY
