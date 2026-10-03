#!/bin/bash
# Does a light whose clue names two leaders end both answers?
#
#     bash tools/test_shared_continuation.sh
#
# cryptic-23753's 51-across LIKE reads "See 6 and 48 down": it ends SOME LIKE IT
# HOT and WARLIKE, but the page groups it with 6-across alone, so 48-down WAR's
# "(7)" held three letters and the refetch was refused. A light already in one
# group is spare for another leader only when its own clue names that leader
# among two or more (fetch_puzzle._spare_light); a pointer naming one leader is
# never taken from the group it sits in.
set -uo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import copy
import sys

sys.path.insert(0, "tools")
import fetch_puzzle
import groups

fails = 0


def check(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        fails += 1
        print(f"FAIL: {name}: got {got!r}, want {want!r}")


def light(n, d, x, y, length, text, enum, group):
    return {"number": n, "direction": d, "position": {"x": x, "y": y},
            "length": length, "clue": {"text": text, "enumeration": enum},
            "group": group}


SOME = ["6-across", "51-across", "30-down"]
PAGE = [
    light(6, "across", 10, 0, 4, "Drag picture", "4,4,2,3", SOME),
    light(30, "down", 3, 12, 5, "See 6 across", None, SOME),
    light(48, "down", 1, 17, 3, "Open eyes about both sides", "7", ["48-down"]),
    light(51, "across", 5, 19, 4, "See 6 and 48 down", None, SOME),
]


def leaders(entries):
    fetch_puzzle.reconstruct_groups(entries, "cryptic")
    return groups.leaders(groups.collapse(entries))


got = leaders(copy.deepcopy(PAGE))
check("51-across ends both answers it names", got,
      {"6-across": SOME, "48-down": ["48-down", "51-across"]})

one = copy.deepcopy(PAGE)
one[3]["clue"]["text"] = "See 6"
check("a pointer naming one leader stays in its own group", leaders(one),
      {"6-across": SOME, "48-down": ["48-down"]})

other = copy.deepcopy(PAGE)
other[3]["clue"]["text"] = "See 6 and 30"
check("a light naming two leaders is not taken by a third", leaders(other),
      {"6-across": SOME, "48-down": ["48-down"]})

sys.exit(1 if fails else 0)
PY
