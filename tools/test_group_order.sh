#!/bin/bash
# Is a linked answer's group stored in the order its words read, on every
# write, and does the corpus sweep report one that is not?
#
#     bash tools/test_group_order.sh
#
# cryptic-24447's ALL AND SUNDRY is four three-letter lights under "(3,3,6)":
# every order of them cuts, so only the words say which is right. The groups
# here are built so that the stored order spells a non-word.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PYTHONPATH=tools python3 - <<'PY'
import copy
import json
import sys
import tempfile
from pathlib import Path

import corroborate
import fetch_puzzle
import puzzle_integrity
from groups import entry_id

fails = 0


def check(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        fails += 1
        print(f"FAIL: {name}: got {got!r}, want {want!r}")


def light(n, d, sol, text, enum=None, group=None, x=0, y=0):
    e = {"number": n, "direction": d, "position": {"x": x, "y": y},
         "length": len(sol), "clue": {"text": text}, "solution": sol}
    if enum:
        e["clue"]["enumeration"] = enum
    if group:
        e["group"] = group
    return e


def puzzle(pid, entries):
    return {"id": pid, "series": "cryptic", "entries": entries}


sundry = puzzle("cryptic-1", [
    light(13, "across", "ALL", "Countries ...", "3,3,6",
          ["13-across", "16-down", "24-across", "18-down"]),
    light(16, "down", "SUN", "See 13"),
    light(24, "across", "AND", "See 13"),
    light(18, "down", "DRY", ""),
])
want = ["13-across", "24-across", "16-down", "18-down"]
check("a group whose order spells a non-word is put in the order that reads",
      fetch_puzzle.group_orders(sundry), {"13-across": want})
fixed = fetch_puzzle.order_groups(sundry)
by_id = {entry_id(e): e for e in fixed["entries"]}
check("the reordered group is the one written", by_id["13-across"]["group"], want)
check("the word break after AND goes on AND", by_id["24-across"]["clue"].get("separators"),
      [{"at": 3, "mark": ","}])
check("SUN, inside SUNDRY, carries no break", by_id["16-down"]["clue"].get("separators"), None)
check("the caller's puzzle is not mutated", sundry["entries"][0]["group"][1], "16-down")
check("a group in word order is left alone", fetch_puzzle.group_orders(fixed), {})

flags = []
puzzle_integrity.check_group_order(sundry, flags)
check("the sweep reports the misordered group", [f[0] for f in flags], ["ORDER"])
flags = []
puzzle_integrity.check_group_order(fixed, flags)
check("and not the fixed one", flags, [])

# THE SETBED SUN does not read, but THE SUNSET BED and THE SUNBED SET both do.
open_ = puzzle("cryptic-2", [
    light(1, "across", "THE", "x", "3,6,3", ["1-across", "2-across", "3-across", "4-across"]),
    light(2, "across", "SET", "See 1"),
    light(3, "across", "BED", "See 1"),
    light(4, "across", "SUN", "See 1"),
])
check("THE SUNSET BED reads", fetch_puzzle.spells_words([3, 6, 3], "THESUNSETBED"), True)
check("two readable orders and no pin: left as stored", fetch_puzzle.group_orders(open_), {})

# GROUP_ORDER pins what the lexicon cannot settle.
pinned = copy.deepcopy(fetch_puzzle.GROUP_ORDER)
fetch_puzzle.GROUP_ORDER[("cryptic-3", "1-across")] = ["1-across", "3-across", "2-across"]
pin = puzzle("cryptic-3", [
    light(1, "across", "WHITE", "x", "5,3,5,4", ["1-across", "2-across", "3-across"]),
    light(2, "across", "MANSPEAK", "See 1"),
    light(3, "across", "WITH", "See 1"),
])
check("a pinned order is applied even when the stored one reads",
      fetch_puzzle.group_orders(pin), {"1-across": ["1-across", "3-across", "2-across"]})
fetch_puzzle.GROUP_ORDER.clear()
fetch_puzzle.GROUP_ORDER.update(pinned)

# A source printing the group's own letters in another light order.
nice = puzzle("independent-1", [
    light(23, "down", "ANICE", "Wise ...", "1,4,6,6", ["23-down", "1-down", "22-down"]),
    light(1, "down", "EARNER", "See 23", x=1),
    light(22, "down", "LITTLE", "See 23", x=2),
])
check("A NICE EARNER LITTLE reads", fetch_puzzle.spells_words([1, 4, 6, 6], "ANICEEARNERLITTLE"), True)
check("every order reads, so the words alone change nothing",
      fetch_puzzle.group_orders(nice), {})
rec = corroborate.Record("fifteensquared", "fifteensquared",
                         answers={(23, "down"): "ANICELITTLEEARNER"})
check("a source's answer that is our lights reordered reorders the group",
      corroborate.source_orders(nice, [rec]), {"23-down": ["23-down", "22-down", "1-down"]})
rec = corroborate.Record("fifteensquared", "fifteensquared",
                         answers={(23, "down"): "ANICELITTLEBANNER"})
check("a source's different answer is a dispute, not an order",
      corroborate.source_orders(nice, [rec]), {})

# The write path: a misordered group cannot reach disk.
real = Path("puzzles/cryptic/2008/cryptic-24447.json")
held = json.loads(real.read_text())
lead = next(e for e in held["entries"] if entry_id(e) == "13-across")
check("the corpus files ALL AND SUNDRY in word order", lead["group"], want)
lead["group"] = ["13-across", "16-down", "24-across", "18-down"]
with tempfile.TemporaryDirectory() as tmp:
    fetch_puzzle.write_shim = lambda *a, **k: None
    out = fetch_puzzle.write_puzzle_file(Path(tmp) / real.name, held)
    written = json.loads(out.read_text())
lead = next(e for e in written["entries"] if entry_id(e) == "13-across")
check("write_puzzle_file writes the group in word order", lead["group"], want)

sys.exit(1 if fails else 0)
PY
