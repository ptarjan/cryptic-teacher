#!/bin/bash
# Does every Guardian clue record land on the light its number names?
#
#     bash tools/test_clue_record_shift.sh
#
# The page serves each entry as a clue record zipped to a light. Drop one of
# either and every later record in that direction rides the wrong light:
# cryptic-25949 put 21's clue (7) on ORDER (5) and lost 29-across entirely.
# fetch_puzzle.align_clue_records() moves each record to the light whose grid
# number it carries; puzzle_integrity's LENGTH check refuses a count that does
# not fit its light or its group.
set -uo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import copy
import sys
from datetime import date

sys.path.insert(0, "tools")
import fetch_puzzle
import puzzle_integrity

fails = 0


def check(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        fails += 1
        print(f"FAIL: {name}: got {got!r}, want {want!r}")


def light(n, d, x, y, length, clue, solution):
    return {"id": f"{n}-{d}", "number": n, "direction": d,
            "position": {"x": x, "y": y}, "length": length, "clue": clue,
            "group": [f"{n}-{d}"], "solution": solution}


# 5x5: rows 0, 2 and 4 full, columns 0, 2 and 4 full. Lights 1a 1d 2d 3d 4a 5a.
GOOD = {"id": "crosswords/cryptic/1", "number": 1,
        "dimensions": {"cols": 5, "rows": 5}, "entries": [
            light(1, "across", 0, 0, 5, "One (5)", "ABCDE"),
            light(1, "down", 0, 0, 5, "Down one (5)", "AFKPU"),
            light(2, "down", 2, 0, 5, "Down two (5)", "CHMRW"),
            light(3, "down", 4, 0, 5, "Down three (5)", "EJOTY"),
            light(4, "across", 0, 2, 5, "Four (5)", "KLMNO"),
            light(5, "across", 0, 4, 5, "Five (5)", "UVWXY"),
        ]}


def ids(entries):
    return sorted((e["id"], e["clue"], e["solution"]) for e in entries)


check("an aligned page is left as served",
      ids(fetch_puzzle.align_clue_records("cryptic-1", GOOD)), ids(GOOD["entries"]))

# The page loses 4-across's record and serves a 6 for a light it never had:
# record 5 rides row 2 and record 6 rides row 4.
shifted = copy.deepcopy(GOOD)
shifted["entries"] = [e for e in shifted["entries"] if e["id"] not in ("4-across", "5-across")]
shifted["entries"] += [light(5, "across", 0, 2, 5, "Five (5)", "KLMNO"),
                       light(6, "across", 0, 4, 5, "Six (5)", "UVWXY")]
try:
    fetch_puzzle.align_clue_records("cryptic-1", shifted)
    check("a record naming no light is refused", "written", "ValueError")
except ValueError as err:
    check("a record naming no light is refused", "6-across" in str(err), True)

# A misprinted number on a light no other record claims takes the grid's.
misnumbered = copy.deepcopy(GOOD)
misnumbered["entries"][4] = light(7, "across", 0, 2, 5, "Four (5)", "KLMNO")
got = {e["id"]: e for e in fetch_puzzle.align_clue_records("cryptic-1", misnumbered)}
check("a misprinted number takes the grid's", got["4-across"]["clue"], "Four (5)")

# The page loses 4-across's record and 5-across's light: record 5 rides row 2.
shifted["entries"] = shifted["entries"][:-1]

fetch_puzzle.SOURCE_LIGHT_MISSING[("cryptic-1", "5-across")] = (
    {"position": {"x": 0, "y": 4}, "length": 5, "solution": "UVWXY"}, "test")
got = {e["id"]: e for e in fetch_puzzle.align_clue_records("cryptic-1", shifted)}
check("the record moves to the light its number names",
      (got["5-across"]["clue"], got["5-across"]["solution"]), ("Five (5)", "UVWXY"))
check("the light it left has no record, so no clue",
      (got["4-across"]["clue"], got["4-across"]["solution"]), ("", "KLMNO"))
del fetch_puzzle.SOURCE_LIGHT_MISSING[("cryptic-1", "5-across")]

# The repaired puzzle passes; the shape it was stored in before does not.
path = fetch_puzzle.ROOT / "puzzles/cryptic/2013/cryptic-25949.json"
puzzle = fetch_puzzle.read_puzzle_file(path)
flags = []
puzzle_integrity.check_puzzle(puzzle, date.today(), flags)
check("cryptic-25949 as repaired has no LENGTH or NUMBER finding",
      [f for f in flags if f[0] in ("LENGTH", "NUMBER")], [])
mangled = copy.deepcopy(puzzle)
order = next(e for e in mangled["entries"] if e["solution"] == "ORDER")
order["clue"] = {"text": "Accompaniment to 17 19 across", "enumeration": "7"}
for e in mangled["entries"]:
    e.pop("group", None)
flags = []
puzzle_integrity.check_puzzle(mangled, date.today(), flags)
check("a (7) riding a five-letter light is a LENGTH finding",
      any(f[0] == "LENGTH" and "20-across" in f[2] for f in flags), True)

sys.exit(1 if fails else 0)
PY
