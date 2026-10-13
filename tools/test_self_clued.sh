#!/bin/bash
# Can a light with a clue of its own also finish another linked answer?
#
#     bash tools/test_self_clued.sh
#
# cryptic-21893's 11-across BATTLE HYMN OF "(6,4,2,3,8)" runs on through
# 21-down THERE and 1-across PUBLIC, each of which carries its own clue (and
# 1-across leads PUBLIC NUISANCE besides). The holder lists them in
# `selfClued` (tools/groups.py): they stay answers of their own, and are not
# continuations. This pins the schema, the groups readers, the shape checks
# and the length check for that case.
set -uo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools python3 - <<'PY'
import copy

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


def entry(n, d, x, y, solution, text, enum=None, **more):
    clue = {"text": text, **({"enumeration": enum} if enum else {})}
    return {"number": n, "direction": d, "position": {"x": x, "y": y}, "length": len(solution),
            "clue": clue, "solution": solution, **more}


ann = {"type": ["charade"], "answer": "x", "definitions": [{"text": "x"}],
       "blocks": [{"clueFragment": "x", "gives": "X"}], "explanation": {"walkthrough": "x"}}
# 1-across HYMNOF leads HYMN OF THE RE PUBLIC; 2-down THERE and 3-across
# PUBLIC are clued too, and 3-across leads PUBLIC NUISANCE with 4-down.
puzzle = {
    "id": "cryptic-99999", "number": 99999, "series": "cryptic", "name": "Cryptic 99,999",
    "setter": "Paul", "date": "2000-05-09", "dimensions": {"cols": 15, "rows": 15},
    "source": {"url": "https://example.com/c99999", "gridOrigin": "published"},
    "entries": [
        entry(1, "across", 0, 0, "HYMNOF", "Martial air", "4,2,3,8",
              group=["1-across", "2-down", "3-across"], selfClued=["2-down", "3-across"]),
        entry(2, "down", 14, 0, "THERE", "Not here", "5", annotation=copy.deepcopy(ann)),
        entry(3, "across", 0, 6, "PUBLIC", "Menace in club", "6,8",
              group=["3-across", "4-down"], annotation=copy.deepcopy(ann)),
        entry(4, "down", 0, 7, "NUISANCE", "See 3"),
    ]}
entries = puzzle["entries"]

print("the schema takes selfClued")
check("accepted", [p for p in puzzle_schema.validate(puzzle) if "selfClued" in p], [])
bad = copy.deepcopy(puzzle)
bad["entries"][0]["selfClued"] = ["2 down"]
check("a malformed id refused", any("selfClued" in p for p in puzzle_schema.validate(bad)), True)

print("groups: a self-clued light is nobody's continuation")
check("leader_of", groups.leader_of(entries), {"4-down": "3-across"})
check("holder_of", sorted(groups.holder_of(entries)), ["4-down"])
check("group_of 2-down", groups.group_of(entries).get("2-down"), None)
check("group_of 3-across is its own", groups.group_of(entries)["3-across"], ["3-across", "4-down"])
check("group_of 1-across", groups.group_of(entries)["1-across"], ["1-across", "2-down", "3-across"])

print("shape checks")
errors = []
validate_annotations.check_groups(puzzle, errors)
check("no group errors", errors, [])
plain = copy.deepcopy(puzzle)
del plain["entries"][0]["selfClued"]
errors = []
validate_annotations.check_groups(plain, errors)
check("without selfClued the clued legs are refused",
      sorted(e.split(":")[0] for e in errors), ["2-down", "3-across", "3-across"])
stray = copy.deepcopy(puzzle)
stray["entries"][0]["selfClued"] = ["2-down", "3-across", "4-down"]
errors = []
validate_annotations.check_groups(stray, errors)
check("selfClued outside the group refused", any("not a later light" in e for e in errors), True)
pointer = copy.deepcopy(puzzle)
pointer["entries"][1]["clue"]["text"] = "See 1"
errors = []
validate_annotations.check_groups(pointer, errors)
check("a pointer leg in selfClued refused", any("its clue is a pointer" in e for e in errors), True)
# cryptic-25126's MINOR, "See 17", ends MAJOR AND MINOR and ASIA MINOR too.
borrowed = copy.deepcopy(puzzle)
borrowed["entries"][0]["group"] = ["1-across", "2-down", "3-across", "4-down"]
borrowed["entries"][0]["selfClued"] = ["2-down", "3-across", "4-down"]
errors = []
validate_annotations.check_groups(borrowed, errors)
check("a pointer that continues another answer may be borrowed", errors, [])
check("and stays that answer's continuation", groups.leader_of(borrowed["entries"]), {"4-down": "3-across"})

print("length check: each answer against its own count")
flags = []
puzzle_integrity.check_length(puzzle, entries, flags)
check("counts agree", [f for f in flags if f[0] == "LENGTH"], [])
short = copy.deepcopy(puzzle)
short["entries"][0]["clue"]["enumeration"] = "4,2,3,6"
flags = []
puzzle_integrity.check_length(short, short["entries"], flags)
check("the leader still counts the whole answer", any(f[2].startswith("1-across + 2-down + 3-across")
                                                     for f in flags if f[0] == "LENGTH"), True)

print(f"self_clued: {'all checks passed' if not fails else f'{fails} FAILED'}")
raise SystemExit(1 if fails else 0)
PY
