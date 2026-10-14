#!/bin/bash
# A leader that prints its clue on a later light, and a count the paper
# printed wrong.
#
#     bash tools/test_off_start_leader.sh
#
# cryptic-21673 prints VESTED INTEREST's clue at 26-across and nothing at
# 25-across, so 26-across holds ["25-across", "26-across"]: the group is in
# word order and its leader is not first (tools/groups.py). cryptic-23821's
# RIGHT AS RAIN is clued at 22-across and starts on 23-down, which has a clue
# of its own, so 22-across names it in selfClued. This pins the groups
# readers, collapse(), check_groups, the GROUP_ORDER pin and the length check
# for that shape; then fetch_puzzle.PRINTED_COUNT_WRONG's write-time mend and
# puzzle_integrity.check_printed_counts.
set -uo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools python3 - <<'PY'
import copy

import fetch_puzzle
import groups
import puzzle_integrity
import validate_annotations

fails = 0


def check(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        fails += 1
        print(f"  FAIL: {name}\n    want {want!r}\n    got  {got!r}")


def entry(n, d, x, y, solution, text=None, enum=None, **more):
    clue = {"text": text} if text else {"missing": True}
    if enum:
        clue["enumeration"] = enum
    return {"number": n, "direction": d, "position": {"x": x, "y": y}, "length": len(solution),
            "clue": clue, "solution": solution, **more}


ann = {"definitions": [{"text": "x"}], "explanation": {"walkthrough": "x"}}
# 1-across VESTED prints nothing; 2-across INTEREST holds the clue (6,8).
# 3-down RIGHT is clued (5,4) and leads RIGHT NOTE with 4-across; 5-across
# ASRAIN holds RIGHT AS RAIN's clue (5,2,4) from its second light.
puzzle = {
    "id": "cryptic-99998", "dimensions": {"cols": 15, "rows": 15},
    "entries": [
        entry(1, "across", 0, 0, "VESTED"),
        entry(2, "across", 0, 2, "INTEREST", "Personal involvement", "6,8",
              group=["1-across", "2-across"], annotation=copy.deepcopy(ann)),
        entry(3, "down", 14, 0, "RIGHT", "Entitled", "5,4",
              group=["3-down", "4-across"], annotation=copy.deepcopy(ann)),
        entry(4, "across", 0, 6, "NOTE", "See 3"),
        entry(5, "across", 0, 8, "ASRAIN", "Perfectly OK", "5,2,4",
              group=["3-down", "5-across"], selfClued=["3-down"]),
    ]}
entries = puzzle["entries"]

print("groups: the lights before an off-start leader are its continuations")
check("leader_of", groups.leader_of(entries), {"1-across": "2-across", "4-across": "3-down"})
check("holder_of 1-across", groups.holder_of(entries)["1-across"]["clue"]["text"], "Personal involvement")
check("group_of 1-across", groups.group_of(entries)["1-across"], ["1-across", "2-across"])
check("group_of 3-down is its own", groups.group_of(entries)["3-down"], ["3-down", "4-across"])
check("off_start", groups.off_start(entries),
      {"2-across": ["1-across", "2-across"], "5-across": ["3-down", "5-across"]})

print("collapse keeps an off-start leader's group when told, and only then")
spread = copy.deepcopy(entries)
kept = groups.off_start(spread)
groups.spread(spread)
check("spread gives the first light the group", spread[0].get("group"), ["1-across", "2-across"])
groups.collapse(spread, kept)
check("the leader keeps it", [e.get("group") for e in spread], [e.get("group") for e in entries])
blind = copy.deepcopy(entries)
groups.spread(blind)
groups.collapse(blind)
check("untold, the group lands on its first light", blind[1].get("group"), None)

print("check_groups")
errors = []
validate_annotations.check_groups(puzzle, errors)
check("no group errors", errors, [])
clued = copy.deepcopy(puzzle)
clued["entries"][0]["clue"] = {"text": "Clothed", "enumeration": "6"}
errors = []
validate_annotations.check_groups(clued, errors)
check("a first light with a clue of its own is refused",
      any("whose clue is a clue of its own" in e for e in errors), True)
plain = copy.deepcopy(puzzle)
del plain["entries"][4]["selfClued"]
errors = []
validate_annotations.check_groups(plain, errors)
check("without selfClued the clued first light is refused",
      any("5-across: group" in e and "3-down" in e for e in errors), True)
pointer = copy.deepcopy(puzzle)
pointer["entries"][1]["clue"] = {"text": "See 1"}
errors = []
validate_annotations.check_groups(pointer, errors)
check("an off-start leader that prints no clue is refused",
      any("prints no clue to lead it from" in e for e in errors), True)
outside = copy.deepcopy(puzzle)
outside["entries"][1]["group"] = ["1-across", "4-across"]
errors = []
validate_annotations.check_groups(outside, errors)
check("a group not naming its holder is refused",
      any("does not name this entry" in e for e in errors), True)

print("the length check reads the group in word order")
flags = []
puzzle_integrity.check_length(puzzle, [e for e in entries], flags)
check("no LENGTH findings", [f for f in flags if f[0] == "LENGTH"], [])

print("GROUP_ORDER pins an off-start leader, so a re-fetch keeps it")
served = copy.deepcopy(puzzle)
served["id"] = "cryptic-21673"
for e in served["entries"]:
    e.pop("group", None)
    e.pop("selfClued", None)
served["entries"][0]["number"], served["entries"][1]["number"] = 25, 26
served["entries"][1]["group"] = ["26-across", "25-across"]
check("group_orders", fetch_puzzle.group_orders(served), {"26-across": ["25-across", "26-across"]})
mended = fetch_puzzle.order_groups(served)
check("separators split in word order",
      [mended["entries"][i]["clue"].get("separators") for i in (0, 1)],
      [[{"at": 6, "mark": ","}], None])

print("PRINTED_COUNT_WRONG: the printed count stays, the breaks follow the intended one")
rhode = {
    "id": "cryptic-22045", "dimensions": {"cols": 15, "rows": 15},
    "entries": [
        entry(2, "down", 1, 0, "RHODE", "State how to harden solid form", "0,11",
              group=["2-down", "20-down"]),
        entry(20, "down", 9, 7, "ISLAND", "See 2"),
    ]}
fixed = fetch_puzzle.mend_printed_counts(rhode)
check("enumeration kept as printed", fixed["entries"][0]["clue"]["enumeration"], "0,11")
check("separators cut from (5,6)", fixed["entries"][0]["clue"].get("separators"), [{"at": 5, "mark": ","}])
check("the input is not touched", "separators" in rhode["entries"][0]["clue"], False)
flags = []
puzzle_integrity.check_printed_counts(fixed, flags)
check("a mended file passes", flags, [])
flags = []
puzzle_integrity.check_printed_counts(rhode, flags)
check("unmended breaks are a finding", any("mend_printed_counts writes them" in f[2] for f in flags), True)
stale = copy.deepcopy(fixed)
stale["entries"][0]["clue"]["enumeration"] = "5,6"
flags = []
puzzle_integrity.check_printed_counts(stale, flags)
check("a row the file no longer prints is stale", any("delete or mend the row" in f[2] for f in flags), True)
check("and a stale row mends nothing", fetch_puzzle.mend_printed_counts(stale)["entries"][0]["clue"].get("separators"),
      [{"at": 5, "mark": ","}])
flags = []
puzzle_integrity.check_length(fixed, fixed["entries"], flags)
check("the length check measures the intended count", flags, [])

print("off_start_leader: all checks passed" if not fails else f"off_start_leader: {fails} FAILED")
raise SystemExit(1 if fails else 0)
PY
