#!/usr/bin/env python3
# Does the write gate hold `unclued` lights and `printed` letters to the grid?
#
#     python3 tests/test_unclued_printed.py
#
# An unclued light (a shaded quotation round a ring) owns squares no entry
# covers, and a printed letter is given to the player. Both have to agree with
# the grid the entries describe, or the app would check the player against a
# letter the crossing answer contradicts. A real puzzle carrying both is
# written through puzzle_integrity.refuse_bad_write, then broken one way at a time.
import copy
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
os.chdir(REPO)
import craft_report
import difficulty
import fetch_puzzle as fetcher
import grid_rules
import puzzle_integrity
import puzzle_schema
import quotes
from apply_solution import check_geometry
from reconstruct_grid import grid_of

fails = 0


def same(what, got, want):
    global fails
    if got == want:
        print(f"  ok: {what}")
    else:
        print(f"  FAIL: {what}\n    want {want}\n    got  {got}")
        fails += 1


def has(key, needle, what):
    global fails
    if needle in out[key]:
        print(f"  ok: {what}")
    else:
        print(f"  FAIL: {what}\n    want {needle} in\n    {key} {out[key]}")
        fails += 1


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
        puzzle_integrity.refuse_bad_write(puzzle_schema.order(quotes.straighten(p)))
        return "accepted"
    except ValueError as err:
        return " | ".join(f"{k} {w}" for k, _, w in err.flags)


out = {"GOOD": verdict(good)}


def broken(name, change):
    p = copy.deepcopy(good)
    change(p)
    out[name] = verdict(p)


broken("OFFBOARD", lambda p: p["unclued"][0]["cells"].__setitem__(-1, {"x": 99, "y": y}))
broken("LENGTH", lambda p: p["unclued"][0].__setitem__("solution", e["solution"]))
broken("CLASH", lambda p: p["unclued"][0].__setitem__(
    "solution", ("Z" if e["solution"][0] != "Z" else "Y") + e["solution"][1:] + "Q"))
broken("TWICE", lambda p: p["unclued"][0]["cells"].__setitem__(-1, dict(own[0])))
broken("BLACK", lambda p: p.__setitem__("unclued", [{"cells": own, "solution": e["solution"]}]))
broken("WRONG", lambda p: p["printed"][1].__setitem__(
    "letter", "Z" if e["solution"][0] != "Z" else "Y"))
broken("UNSOLVED", lambda p: p["unclued"][0].pop("solution") and p["printed"].pop(0))
broken("SHAPE", lambda p: p["unclued"][0].__setitem__("cells", own[:1]) or
       p["unclued"][0].__setitem__("solution", e["solution"][0]))

same("a puzzle with an unclued light over a black square and printed letters is written",
     f"GOOD {out['GOOD']}", "GOOD accepted")
has("OFFBOARD", "is off the 15x15 board", "an unclued square off the board is refused")
has("LENGTH", "letters for", "an unclued solution the wrong length is refused")
has("CLASH", "but the entry crossing it has", "an unclued letter that clashes with an entry is refused")
has("TWICE", "lists a square twice", "an unclued light listing a square twice is refused")
has("BLACK", "is not on a white square", "a printed letter on a black square is refused")
has("WRONG", "but the solution there is", "a printed letter that is not the solution is refused")
same("an unclued light with no solution files unsolved",
     f"UNSOLVED {out['UNSOLVED']}", "UNSOLVED accepted")
has("SHAPE", "SCHEMA", "an unclued light of one square fails the schema")

# An unclued light checks the entries it crosses: a grid whose clued entries
# alone fall under the checked-cell floor passes once the light is counted.
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
ratio = f'{"BARE" if bare else "NOBARE"} {"LIT" if lit else "NOLIT"}'
same("the checked-cell floor counts unclued lights as lights", ratio, "BARE NOLIT")

# Every reader of "which squares are white" or "which are checked" counts an
# unclued light, and with it removed gives the old answer (the mirror).
e = next(e for e in real["entries"] if e["direction"] == "across"
         and e["position"]["x"] + e["length"] < real["dimensions"]["cols"])
x0, y = e["position"]["x"], e["position"]["y"]
p = copy.deepcopy(real)
used = Counter((q["position"]["x"] + (i if q["direction"] == "across" else 0),
                q["position"]["y"] + (i if q["direction"] == "down" else 0))
               for q in real["entries"] for i in range(q["length"]))
lone = next(c for c, n in sorted(used.items()) if n == 1)   # a square only one entry checks
p["unclued"] = [{"cells": [{"x": x0 + e["length"], "y": y}, {"x": lone[0], "y": lone[1]}], "solution": "QQ"}]
white = lambda q: sum(map(sum, grid_rules.mask(q)))
cnt = {"MASK": f"MASK {white(p) - white(real)}"}
cnt["CHECKING"] = f"CHECKING {difficulty.checking(p) < difficulty.checking(real)}"
cnt["CRAFT"] = f'CRAFT {craft_report.grid_mechanics(p)["weak_checking"] <= craft_report.grid_mechanics(real)["weak_checking"]}'
same("grid_rules.mask draws an unclued-only square white", cnt["MASK"], "MASK 1")
same("difficulty.checking counts the squares an unclued light checks", cnt["CHECKING"], "CHECKING True")
same("craft_report.grid_mechanics counts them too", cnt["CRAFT"], "CRAFT True")

if fails:
    print(f"unclued_printed: {fails} check(s) failed")
    sys.exit(1)
print("unclued_printed: all checks passed")
