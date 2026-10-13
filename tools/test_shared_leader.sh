#!/bin/bash
# Can one light start more than one linked answer?
#
#     bash tools/test_shared_leader.sh
#
# Genius 209's 22 across, IVOR, starts both IVOR HUGH JEGO (22,17,3) and IVOR
# SORE BEACH BUM (22,2,5): two printed clues on one light. The light's first
# answer is its own clue, group and annotation; each further one is an item of
# its `alsoLeads` {clue, group, annotation} (tools/groups.py). This pins the
# schema, the groups readers, the shape checks, the annotate run's view and
# write, and the Genius parser's "See N" placing for that case.
set -uo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools python3 - <<'PY'
import copy
import sys

import annotate_check
import apply_annotations
import genius_puzzles
import groups
import puzzle_integrity
import puzzle_schema
import validate_annotations

fails = 0


def check(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        fails += 1
        print(f"  FAIL: {name}\n    want {want!r}\n    got  {got!r}")


def entry(n, d, x, y, length, solution, text, enum=None, **more):
    clue = {"text": text, **({"enumeration": enum} if enum else {})}
    return {"number": n, "direction": d, "position": {"x": x, "y": y}, "length": length,
            "clue": clue, "solution": solution, **more}


# 1-across ABC leads ABC+DE (1-across, 2-down) and ABC+FG (1-across, 3-down).
puzzle = {
    "id": "genius-999", "number": 999,
    "setter": "Paul", "date": "2020-12-07", "dimensions": {"cols": 5, "rows": 5},
    "source": {"url": "https://example.com/g999.pdf", "gridOrigin": "published"},
    "entries": [
        entry(1, "across", 0, 0, 3, "ABC", "First lead", "3,2", group=["1-across", "2-down"],
              alsoLeads=[{"clue": {"text": "Second lead", "enumeration": "3,2"},
                          "group": ["1-across", "3-down"]}]),
        entry(2, "down", 4, 0, 2, "DE", "See 1"),
        entry(3, "down", 4, 2, 2, "FG", "See 1"),
    ]}
entries = puzzle["entries"]

print("the schema takes alsoLeads, and refuses an item with no group")
check("alsoLeads accepted", [p for p in puzzle_schema.validate(puzzle) if "alsoLeads" in p], [])
bad = copy.deepcopy(puzzle)
del bad["entries"][0]["alsoLeads"][0]["group"]
check("item without group refused", any("alsoLeads" in p for p in puzzle_schema.validate(bad)), True)

print("groups: every linked answer, each continuation's leader and holder")
check("linked", [(groups.entry_id(e), h["group"]) for e, h in groups.linked(entries)],
      [("1-across", ["1-across", "2-down"]), ("1-across", ["1-across", "3-down"])])
check("leader_of", groups.leader_of(entries), {"2-down": "1-across", "3-down": "1-across"})
check("holder_of 3-down", groups.holder_of(entries)["3-down"]["clue"]["text"], "Second lead")
check("group_of 3-down", groups.group_of(entries)["3-down"], ["1-across", "3-down"])
check("clue ids", [c for c, *_ in groups.also_clues(entries)], ["1-across/2"])
view = groups.as_leader(puzzle, 0, 0)["entries"][0]
check("as_leader", (view["clue"]["text"], view["group"], "alsoLeads" in view),
      ("Second lead", ["1-across", "3-down"], False))
check("as_leader leaves the puzzle alone", entries[0]["clue"]["text"], "First lead")

print("shape checks: a continuation of an alsoLeads group is a continuation")
errors = []
validate_annotations.check_groups(puzzle, errors)
check("no group errors", errors, [])
lone = copy.deepcopy(puzzle)
del lone["entries"][0]["group"]
errors = []
validate_annotations.check_groups(lone, errors)
check("alsoLeads without group", any("alsoLeads with no group" in e for e in errors), True)
twice = copy.deepcopy(puzzle)
twice["entries"][0]["alsoLeads"][0]["group"] = ["1-across", "2-down"]
errors = []
validate_annotations.check_groups(twice, errors)
check("alsoLeads repeating the group", any("repeats the group" in e for e in errors), True)
flags = []
puzzle_integrity.check_puzzle_text(puzzle, flags)
check("counts agree", flags, [])
miscount = copy.deepcopy(puzzle)
miscount["entries"][0]["alsoLeads"][0]["clue"]["enumeration"] = "3,3"
flags = []
puzzle_integrity.check_puzzle_text(miscount, flags)
check("alsoLeads count against its group", any("alsoLeads[0] enumeration" in f[2] for f in flags), True)

print("the annotate run sees the second clue as its own and writes it there")
validate_annotations.blind_misses = lambda pid: {}
check("unsolved counts both clues", [e["clue"]["text"] for e in annotate_check.unsolved(puzzle)],
      ["First lead", "Second lead"])
ann = {"def": "lead", "wp": "[Second]ABCFG", "explanation": {"walkthrough": "x"}}
written = copy.deepcopy(puzzle)
errors = []
apply_annotations.apply_also(written, {"1-across/2": ann}, errors)
check("no landing errors", errors, [])
check("written to alsoLeads as the tree",
      written["entries"][0]["alsoLeads"][0].get("annotation", {}).get("wordplay"),
      {"words": "Second", "gives": "ABCFG", "at": 0})
check("the light's own clue untouched", "annotation" in written["entries"][0], False)
written = puzzle_schema.order(written)  # as write_puzzle_file stores it
before = copy.deepcopy(written)
_, errs, _ = validate_annotations.validate_puzzle(written)
check("its wordplay is checked against its own group", [e for e in errs if "alsoLeads[0]" in e], [])
check("validating leaves the puzzle as it was", written == before, True)
written = before
wrong = copy.deepcopy(puzzle)
errors = []
apply_annotations.apply_also(wrong, {"1-across/2": dict(ann, wp="[Second]ABCDE")}, errors)
check("wordplay giving the first group's answer is refused", (len(errors), "annotation" in wrong["entries"][0]["alsoLeads"][0]),
      (1, False))
stored = copy.deepcopy(written)
stored["entries"][0]["alsoLeads"][0]["annotation"]["wordplay"]["gives"] = "ABCDE"
_, errs, _ = validate_annotations.validate_puzzle(stored)
check("a stored alsoLeads tree giving the wrong answer is named", any("alsoLeads[0]" in e for e in errs), True)

print("Genius parser: a 'See 22' stub one clue on 22 already lists stays with it")
clues = [{"lights": [(22, "across"), (17, "down"), (3, "down")], "clue": "A (4,4,4)", "enumeration": "4,4,4"},
         {"lights": [(22, "across"), (2, "down"), (5, "down")], "clue": "B (4,4,8)", "enumeration": "4,4,8"},
         {"lights": [(2, "down")], "clue": "See 22", "enumeration": None},
         {"lights": [(3, "down")], "clue": "See 22", "enumeration": None},
         {"lights": [(17, "down")], "clue": "See 22", "enumeration": None}]
genius_puzzles.see_links(clues)
check("second 22 keeps its own lights", clues[1]["lights"], [(22, "across"), (2, "down"), (5, "down")])
check("first 22 keeps its own lights", clues[0]["lights"], [(22, "across"), (17, "down"), (3, "down")])

print("FAIL" if fails else "PASS")
sys.exit(1 if fails else 0)
PY
