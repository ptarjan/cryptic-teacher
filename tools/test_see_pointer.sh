#!/bin/bash
# Is a "See N" continuation the pointer and nothing else, in every reader?
#
#     bash tools/test_see_pointer.sh
#
# The Nation's 3257 printed 1-across "See 2 if confused about final two parts
# of clues (7)": a real clue (WITNESS, TWINS+ES) whose wordplay names 2-down's
# answer. tools/normalise_linked_enumerations.py read any clue OPENING "See N"
# as a continuation, so the puzzle was filed with 2-down "(5,7)" leading
# ['2-down', '1-across'] and 1-across stripped of its count, and the hint burn
# could not apply its solve. The shape is stated once, groups.POINTER, and every
# reader asks groups.is_pointer / pointer_target; this holds each of them to it,
# and holds the nation corpus to no such false group.
#
# Also: the page chrome above The Nation's clue list (share bar, byline, issue
# line, newsletter blurbs) is not a preamble (fetch_nation.preamble_of,
# tools/boilerplate.py).
set -uo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH="$PWD/tools" python3 - <<'PY'
import glob
import json
import sys

import boilerplate
import fetch_nation
import fetch_puzzle
import genius_puzzles
import groups
import parse_timesforthetimes as tftt
from normalise_linked_enumerations import continuation_target, resolve_groups

fails = []


def check(name, got, want):
    if got == want:
        print(f"  ok: {name}")
    else:
        fails.append(name)
        print(f"FAIL: {name}: got {got!r}, want {want!r}")


CLUE = "See 2 if confused about final two parts of clues"
for text, want in [("See 2", 2), ("See 11 down", 11), ("See 23 13 across, or 11", 23),
                   ("See10", 10), ("See 12a", 12), ("See 6 and 48 down", 6),
                   (CLUE, None), (CLUE + " (7)", None),
                   ("See 5 across out to find another date", None), ("Seen 2", None)]:
    check(f"pointer_target({text!r})", groups.pointer_target(text, counted=True), want)
check("a counted pointer is a pointer only when asked",
      (groups.pointer_target("See 2 (6)"), groups.pointer_target("See 2 (6)", counted=True),
       groups.pointer_target("(See 16 Across) (3)", counted=True)), (None, 2, 16))
check("fetch_puzzle.is_continuation refuses the clue", fetch_puzzle.is_continuation(CLUE), False)
check("normalise continuation_target refuses the clue", continuation_target(CLUE), None)
check("tftt continuation_target refuses the clue", tftt.continuation_target(CLUE + " (7)"), None)

entries = [
    {"number": 1, "direction": "across", "length": 7, "clue": CLUE, "enumeration": "7"},
    {"number": 2, "direction": "down", "length": 5, "enumeration": "5",
     "clue": "Ties at first, then victories for baseball team"},
    {"number": 9, "direction": "across", "length": 4, "clue": "Dog (4,5)", "enumeration": "4,5"},
    {"number": 3, "direction": "down", "length": 5, "clue": "See 9"},
]
check("resolve_groups: 3257's 1-across leads nothing, a bare pointer still links",
      resolve_groups(entries), {"9-across": ["9-across", "3-down"], "3-down": ["9-across", "3-down"]})

lists, head = fetch_nation.clue_lists(
    ["ACROSS", "1 See 2 if confused about", "final two parts of clues (7)", "5 See 1", "DOWN",
     "2 Ties at first, then victories for baseball team (5)"])
check("fetch_nation: a clue opening 'See 2' runs on to its count",
      lists["across"], [{"number": "1", "clue": CLUE, "enumeration": "7"},
                        {"number": "5", "clue": "See 1", "enumeration": None}])

m = genius_puzzles.CLUE_AT.match("1 " + CLUE + " (7) 2 Ties at first (5)")
check("genius: a clue opening 'See 2' is no stub", m and m.group("text"), CLUE + " (7)")
m = genius_puzzles.CLUE_AT.match("1 See 7 (8) 2 Ties at first (5)")
check("genius: a counted stub is still a stub", m and m.group("text"), "See 7 (8)")

CHROME = ("Joshua Kosman and Henri Picciotto Share Copy Link Facebook X (Twitter) Bluesky "
          "Pocket Email October 16, 2012 This article appears in the November 5, 2012 issue.")
check("boilerplate: The Nation's share bar is no preamble", boilerplate.strip(CHROME), None)
check("preamble_of: chrome after the blog line is no preamble",
      fetch_nation.preamble_of(["And don’t miss Kosman and Picciotto’s crossword blog, Word Salad.",
                                "Joshua Kosman and Henri Picciotto", "Share", "Copy Link",
                                "October 16, 2012", "This article appears in the November 5, 2012 issue.",
                                "Puzzled? No more cross words! Read Kosman and Picciotto on "
                                "“Solving The Nation’s Cryptic Puzzles.” Or watch this video."]), None)
check("preamble_of: a real note stays",
      fetch_nation.preamble_of(["Click HERE to download a printable PDF of this puzzle.",
                                "Each answer contains a hidden animal."]),
      "Each answer contains a hidden animal.")

# The corpus: no nation light sits in a group whose clue has words of its own
# after "See N" — that is a clue, not a continuation leg.
bad, seen = [], 0
for path in sorted(glob.glob("puzzles/nation/*/*.json")):
    puzzle = json.load(open(path))
    by_id = {groups.entry_id(e): e for e in puzzle.get("entries") or []}
    for e in by_id.values():
        for gid in (e.get("group") or [])[1:]:
            seen += 1
            text = ((by_id.get(gid) or {}).get("clue") or {}).get("text") or ""
            if text.lower().startswith("see") and not groups.is_pointer(text, counted=True):
                bad.append(f"{puzzle['id']} {gid}: {text!r}")
check(f"nation corpus: no continuation leg with its own wordplay ({seen} legs)", bad, [])
check("nation corpus: the sweep found linked legs at all", seen > 0, True)

print(f"{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
PY
