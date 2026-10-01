#!/bin/bash
# Does the write gate hold `unclued` lights and `printed` letters to the grid?
#
#     bash tools/test_unclued_printed.sh
#
# An unclued light (a shaded quotation round a ring) owns squares no entry
# covers, and a printed letter is given to the player. Both have to agree with
# the grid the entries describe, or the app would check the player against a
# letter the crossing answer contradicts. A real puzzle carrying both is
# written through puzzle_integrity.refuse_bad_write, then broken one way at a time.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }

out=$(PYTHONPATH=tools python3 - <<'PY'
import copy
import fetch_puzzle as fetcher
import puzzle_integrity, puzzle_schema
from reconstruct_grid import grid_of

real = fetcher.read_puzzle_file(fetcher.resolve_puzzle("cryptic-30066"))
grid = grid_of(real)
# The first answered across light, and the black square after it if there is one.
e = next(e for e in real["entries"] if e["direction"] == "across" and e.get("solution")
         and e["position"]["x"] + e["length"] < real["dimensions"]["cols"])
x0, y = e["position"]["x"], e["position"]["y"]
own = [{"x": x0 + i, "y": y} for i in range(e["length"])]
black = {"x": x0 + e["length"], "y": y}
assert grid[y][black["x"]] == "#"
good = copy.deepcopy(real)
good["unclued"] = [{"cells": own + [black], "solution": e["solution"] + "Q",
                    "enumeration": f"{e['length'] + 1}", "note": "Shaded quotation round the grid"}]
good["printed"] = [{**black, "letter": "Q"}, {**own[0], "letter": e["solution"][0]}]


def verdict(p):
    try:
        puzzle_integrity.refuse_bad_write(puzzle_schema.order(p))
        return "accepted"
    except ValueError as err:
        return " | ".join(f"{k} {w}" for k, _, w in err.flags)


print("GOOD", verdict(good))


def broken(name, change):
    p = copy.deepcopy(good)
    change(p)
    print(name, verdict(p))


broken("OFFBOARD", lambda p: p["unclued"][0]["cells"].__setitem__(-1, {"x": 99, "y": y}))
broken("LENGTH", lambda p: p["unclued"][0].__setitem__("solution", e["solution"]))
broken("CLASH", lambda p: p["unclued"][0].__setitem__(
    "solution", ("Z" if e["solution"][0] != "Z" else "Y") + e["solution"][1:] + "Q"))
broken("TWICE", lambda p: p["unclued"][0]["cells"].__setitem__(-1, dict(own[0])))
broken("BLACK", lambda p: p.__setitem__("unclued", [{"cells": own, "solution": e["solution"]}]))
broken("WRONG", lambda p: p["printed"][1].__setitem__(
    "letter", "Z" if e["solution"][0] != "Z" else "Y"))
broken("SHAPE", lambda p: p["unclued"][0].__setitem__("cells", own[:1]) or
       p["unclued"][0].__setitem__("solution", e["solution"][0]))
PY
)
grep -q '^GOOD ' <<<"$out" || { echo "$out"; exit 1; }
has() { if grep "^$1 " <<<"$out" | grep -qF -- "$2"; then echo "  ok: $3"; else
  echo "  FAIL: $3"$'\n'"    want $2 in"$'\n'"    $(grep "^$1 " <<<"$out")"; fails=$((fails + 1)); fi; }

same "a puzzle with an unclued light over a black square and printed letters is written" \
  "$(grep '^GOOD ' <<<"$out")" "GOOD accepted"
has OFFBOARD "is off the 15x15 board" "an unclued square off the board is refused"
has LENGTH "letters for" "an unclued solution the wrong length is refused"
has CLASH "but the entry crossing it has" "an unclued letter that clashes with an entry is refused"
has TWICE "lists a square twice" "an unclued light listing a square twice is refused"
has BLACK "is not on a white square" "a printed letter on a black square is refused"
has WRONG "but the solution there is" "a printed letter that is not the solution is refused"
has SHAPE "SCHEMA" "an unclued light of one square fails the schema"

# An unclued light checks the entries it crosses: a grid whose clued entries
# alone fall under the checked-cell floor passes once the light is counted.
ratio=$(PYTHONPATH=tools python3 - <<'PY'
from apply_solution import check_geometry
# Three parallel 5-cell downs joined top and bottom by unclued rows: the downs
# cross nothing clued, so only the unclued rows can make the grid coherent.
p = {"dimensions": {"cols": 5, "rows": 5}, "entries": [
    {"number": 1, "direction": "down", "position": {"x": 0, "y": 0}, "length": 5},
    {"number": 2, "direction": "down", "position": {"x": 2, "y": 0}, "length": 5},
    {"number": 3, "direction": "down", "position": {"x": 4, "y": 0}, "length": 5}]}
ring = [{"cells": [{"x": x, "y": 0} for x in range(5)], "solution": "AAAAA"},
        {"cells": [{"x": x, "y": 4} for x in range(5)], "solution": "AAAAA"}]
bare = [q for q in check_geometry(p) if "checked" in q]
lit = [q for q in check_geometry({**p, "unclued": ring}) if "checked" in q]
print("BARE" if bare else "NOBARE", "LIT" if lit else "NOLIT")
PY
)
same "the checked-cell floor counts unclued lights as lights" "$ratio" "BARE NOLIT"

if [ "$fails" -gt 0 ]; then echo "unclued_printed: $fails check(s) failed"; exit 1; fi
echo "unclued_printed: all checks passed"
