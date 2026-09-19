#!/bin/bash
# Is a linked answer still stored on its LEADER, and is the other shape still
# impossible to file?
#
#     bash tools/test_linked_enumerations.sh
#
# An answer spanning two lights is stored one way in this corpus: the whole
# answer's enumeration on the leader, null on the continuation.
# puzzles/penguin5-3.js is the settled example — 15-down "(9,5,4)" over
# NEWCASTLE, 17-down "See 15" with no count over UNDERLYME.
#
# The solve scripts emit the opposite shape, a per-light count on each half,
# because a light is what they measured. tools/file_penguin_puzzle.py refused
# that shape one puzzle at a time, which is how one mistake in one script cost
# three separate hand investigations (books 18, 27 and 45, 2026-09-18) before
# anybody wrote it down. Refusing is not the fix; converting is, and a
# convention nothing tests is a convention that drifts back. So this holds both
# ends: the corpus on disk still reads leader form, and the route that writes it
# converts rather than trusting its input.
#
# THE COUNT COMES FROM THE ANSWER. "(5,3,6)" describes UNTER DEN LINDEN's words;
# the per-light numbers describe the grid, which already knows its own lights,
# and no reading of "5" and "9" can say where DEN ends. So the normaliser reads
# the fill's spaces and hyphens, and a printed per-light count is used only to
# refuse when it disagrees with the answer. The no-op property below is what
# protects an already-correct record from that derivation: UNDERLYME is stored
# without its space, so deriving over it would produce "(9,9)" — a record that
# is already in leader form is left alone rather than re-derived.
#
# The corpus sweep globs puzzles/penguin*.js rather than walking all 15,000
# puzzles: the Guardian's own pre-2015 markup prints a leg's own count beside
# its pointer ("See 2 (6)"), which fetch_puzzle.is_continuation and
# puzzle_integrity.check_length exist to tolerate. That is the paper's shape in
# the fetched series and is not this convention. The penguin series is written
# by us, from a solve record, so it is held to one shape exactly. The sweep also
# asserts it found groups at all, so a glob that stops matching fails instead of
# passing over nothing.
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"

PYTHONPATH="$REPO/tools" python3 - <<'PY'
import copy
import json
import re
import sys
from pathlib import Path

import file_penguin_puzzle as filing

# Volume 7's real archive.org id is not recorded anywhere in the repo, and
# file_penguin_puzzle refuses to invent one — it used to stamp volume 5's
# scan on every volume. A fixture id keeps these cases about enumerations.
FIXTURE_SCAN = "fixture-penguin-volume-7"
from normalise_linked_enumerations import normalise_record, resolve_groups

fails = []


def ok(name):
    print(f"  ok: {name}")


def same(name, got, want):
    if got == want:
        ok(name)
    else:
        fails.append(name)
        print(f"  FAIL: {name}\n    want {want!r}\n    got  {got!r}")


def refuses(name, record, wanted):
    """The group cannot be resolved: it must stop, and say which light and why."""
    try:
        normalise_record(copy.deepcopy(record))
    except SystemExit as exc:
        for want in wanted:
            if want in str(exc):
                ok(f"{name}: says {want!r}")
            else:
                fails.append(name)
                print(f"  FAIL: {name}\n    wanted to find: {want}\n    in: {exc}")
        return
    fails.append(name)
    print(f"  FAIL: {name}\n    it accepted a record it cannot resolve")


def light(eid, number, direction, length, clue, enumeration, x=0, y=0):
    return {"id": eid, "number": number, "direction": direction,
            "position": {"x": x, "y": y}, "length": length,
            "clue": clue, "enumeration": enumeration}


def record(entries, fill):
    return {"book_number": 99, "setter": "Test",
            "puzzle": {"dimensions": {"cols": 15, "rows": 15}, "entries": entries},
            "fill": fill,
            "entries": {k: {"answer": v, "confidence": "CONFIDENT"} for k, v in fill.items()}}


def enum_of(entry):
    return entry.get("enumeration")


def by_id(rec):
    return {e["id"]: e for e in rec["puzzle"]["entries"]}


# Book 18's shape: TEAM + MATE, a per-light "4" printed on each half.
SPLIT = record(
    [light("7-down", 7, "down", 4, "Fellow player makes anagrams", "4"),
     light("8-down", 8, "down", 4, "See 7", "4")],
    {"7-down": "TEAM", "8-down": "MATE"})

# penguin5-3's shape, already right: the whole count on the leader, none on the
# continuation, and the continuation's fill stored without the space that its
# two words would need — which is exactly what re-deriving would get wrong.
LEADER = record(
    [light("15-down", 15, "down", 9, "Where under Lyme is", "9,5,4"),
     light("17-down", 17, "down", 9, "See 15", None)],
    {"15-down": "NEWCASTLE", "17-down": "UNDERLYME"})

# Book 45's shape: "See 19" names both 19-across and 19-down, and 19-across is
# itself a pointer, so it cannot be the one leading TURNED TO STONE.
AMBIGUOUS = record(
    [light("17-across", 17, "across", 6, "What a patrolling PC does", "6"),
     light("19-across", 19, "across", 7, "See 17", "3,4"),
     light("19-down", 19, "down", 6, "Faced holy man, single, petrified", "6"),
     light("20-down", 20, "down", 7, "See 19", "2,5")],
    {"17-across": "POUNDS", "19-across": "THE BEAT",
     "19-down": "TURNED", "20-down": "TO STONE"})

print("a split record is rewritten into leader form, the count read off the answer")
rec = copy.deepcopy(SPLIT)
changes = normalise_record(rec)
same("the leader carries the whole answer", enum_of(by_id(rec)["7-down"]), "4,4")
same("the continuation carries null", enum_of(by_id(rec)["8-down"]), None)
same("it says what it changed", len(changes), 1)
same("and names both lights", "7-down + 8-down" in changes[0], True)

print("UNTER DEN LINDEN: the words come from the answer, not from the light lengths")
rec = record(
    [light("7-down", 7, "down", 5, "That's the Berliner's way!", "5"),
     light("17-down", 17, "down", 9, "See 7", None)],
    {"7-down": "UNTER", "17-down": "DEN LINDEN"})
normalise_record(rec)
same("5 + 9 cells read as three words", enum_of(by_id(rec)["7-down"]), "5,3,6")

print("a record already in leader form is left exactly alone, twice over")
rec = copy.deepcopy(LEADER)
same("nothing to change", normalise_record(rec), [])
same("the leader's own count survives", enum_of(by_id(rec)["15-down"]), "9,5,4")
same("nothing was re-derived from UNDERLYME", rec, LEADER)
rec = copy.deepcopy(SPLIT)
normalise_record(rec)
twice = copy.deepcopy(rec)
same("rewriting twice changes nothing", normalise_record(twice), [])
same("and leaves the same record", twice, rec)

print('"See 19" with two lights numbered 19: a pointer cannot lead a group')
rec = copy.deepcopy(AMBIGUOUS)
normalise_record(rec)
ids = by_id(rec)
same("TURNED TO STONE hangs off 19-down", enum_of(ids["19-down"]), "6,2,5")
same("its continuation is cleared", enum_of(ids["20-down"]), None)
same("POUNDS THE BEAT is untouched by that", enum_of(ids["17-across"]), "6,3,4")
same("19-across stays a continuation", enum_of(ids["19-across"]), None)
same("groups are leader-first", resolve_groups(rec["puzzle"]["entries"])["20-down"],
     ["19-down", "20-down"])

print("it refuses rather than guesses")
refuses("a pointer at a number no other light holds",
        record([light("7-down", 7, "down", 4, "Fellow player makes anagrams", "4"),
                light("8-down", 8, "down", 4, "See 42", "4")],
               {"7-down": "TEAM", "8-down": "MATE"}),
        ["8-down", "points at No 42", "names no other light"])
refuses("a fill whose words disagree with the count the book printed",
        record([light("7-down", 7, "down", 5, "That's the Berliner's way!", "5"),
                light("17-down", 17, "down", 9, "See 7", "3,6")],
               {"7-down": "UNTER", "17-down": "DENLINDEN"}),
        ["17-down", "the book counts (3,6)", "not the same answer"])
refuses("an answer that does not fit the light it is in",
        record([light("7-down", 7, "down", 4, "Fellow player makes anagrams", "4"),
                light("8-down", 8, "down", 4, "See 7", "4")],
               {"7-down": "TEAM", "8-down": "MATEY"}),
        ["8-down", "holds 5 letters, the light is 4 cells"])
refuses("a loop of pointers, which has no leader",
        record([light("7-down", 7, "down", 4, "See 8", "4"),
                light("8-down", 8, "down", 4, "See 7", "4")],
               {"7-down": "TEAM", "8-down": "MATE"}),
        ["leads back to itself", "no leader"])

print("the split shape cannot be FILED, not merely rejected")
puzzle = filing.build(copy.deepcopy(SPLIT), 5, "opus")
built = {e["id"]: e for e in puzzle["entries"]}
same("the leader's clue prints the whole answer's count",
     built["7-down"]["clue"].endswith("(4,4)"), True)
same("the continuation's clue prints no count at all", built["8-down"]["clue"], "See 7")
same("the word break sits in the light it falls in",
     built["7-down"]["separatorLocations"], {",": [4]})
same("the continuation carries no break", built["8-down"]["separatorLocations"], {})
same("both lights know the group", built["8-down"]["group"], ["7-down", "8-down"])

print("a record with no answers at all is still put into leader form")
# A puzzle filed UNSOLVED for the nightly cold solve to finish: the book's
# printed per-light counts are all there is, and the leader still has to end up
# carrying the whole answer's count, because that is what the app and
# puzzle_integrity read. The only thing derived is the join between two lights.
def unsolved_record(entries):
    return {"book_number": 98, "setter": "Test",
            "puzzle": {"dimensions": {"cols": 15, "rows": 15}, "entries": entries}}


SPLIT_UNSOLVED = unsolved_record(
    [light("7-down", 7, "down", 4, "Fellow player makes anagrams", "4"),
     light("8-down", 8, "down", 4, "See 7", "4")])
rec = copy.deepcopy(SPLIT_UNSOLVED)
changes = normalise_record(rec)
same("the leader carries both lights", enum_of(by_id(rec)["7-down"]), "4,4")
same("the continuation carries null", enum_of(by_id(rec)["8-down"]), None)
same("it says what it changed", len(changes), 1)

print("each light keeps the words the book printed in it, joined at the split")
rec = unsolved_record(
    [light("22-down", 22, "down", 4, "Leaps out of bed", "4"),
     light("23-down", 23, "down", 4, "See 22", "1,3")])
normalise_record(rec)
same('"4" and "1,3" over two lights read as (4,1,3)',
     enum_of(by_id(rec)["22-down"]), "4,1,3")
same("and the continuation is cleared", enum_of(by_id(rec)["23-down"]), None)

print("a continuation the book printed no count over counts its own cells")
# Book 27's shape, and one in four of the volume-5 puzzles: 7-down prints "5"
# for its own five cells and 17-down, nine cells of UNTER DEN LINDEN, prints
# nothing at all. Unsolved there is no answer to read the words off, so the
# unknown light counts as one word — the weakest true statement there is. What
# it must NOT do is drop the break between the lights and print one total:
# "(14)" would say the answer is a single fourteen-letter word, which is the one
# thing the grid already disproves.
rec = unsolved_record(
    [light("7-down", 7, "down", 5, "That's the Berliner's way!", "5"),
     light("17-down", 17, "down", 9, "See 7", None)])
normalise_record(rec)
same("the counted light keeps its count and the uncounted one its cells",
     enum_of(by_id(rec)["7-down"]), "5,9")
same("and the continuation is still cleared", enum_of(by_id(rec)["17-down"]), None)
same("a puzzle with a countless continuation can be filed unsolved",
     filing.build(unsolved_record(
         [light("7-down", 7, "down", 5, "That's the Berliner's way!", "5"),
          light("17-down", 17, "down", 9, "See 7", None)]),
         5, "opus", unsolved=True)["entries"][0]["clue"].endswith("(5,9)"), True)

print("with no answer to fall back on it refuses rather than inventing a count")
refuses("a printed count that does not fit its own light",
        unsolved_record([light("7-down", 7, "down", 4, "Fellow player", "4"),
                         light("8-down", 8, "down", 4, "See 7", "3")]),
        ["8-down", "the book counts (3)", "the light is 4 cells"])

print("an unsolved puzzle files with the same counts and no answers")
puzzle = filing.build(copy.deepcopy(SPLIT_UNSOLVED), 7, "opus", unsolved=True,
                      identifier=FIXTURE_SCAN)
built = {e["id"]: e for e in puzzle["entries"]}
same("the leader's clue prints the whole answer's count",
     built["7-down"]["clue"].endswith("(4,4)"), True)
same("the continuation's clue prints no count", built["8-down"]["clue"], "See 7")
same("the word break is placed without an answer to place it from",
     built["7-down"]["separatorLocations"], {",": [4]})
same("every light is answerless", [e["solution"] for e in puzzle["entries"]], [None, None])
# hasSolutions in puzzles/index.json is all(e["solution"]), and false is what
# puts the puzzle in the cold-solve queue. A puzzle carrying a solutionSource
# with no solve behind it would also satisfy apply_solution.py's overwrite
# guard on behalf of a solve that never happened, and turn that queue away.
same("and nothing claims to have solved it", "solutionSource" in puzzle, False)

print("and the guard on a SOLVED filing is untouched")
short = record([light("7-down", 7, "down", 4, "Fellow player makes anagrams", "4"),
                light("8-down", 8, "down", 4, "See 7", "4")],
               {"7-down": "TEAM"})
try:
    filing.build(short, 7, "opus", identifier=FIXTURE_SCAN)
    fails.append("a solved filing still refuses a missing answer")
    print("  FAIL: a solved filing still refuses a missing answer\n"
          "    it filed a puzzle with no answer for 8-down")
except SystemExit as exc:
    same("a missing answer is still fatal without --unsolved",
         "no answer for 8-down" in str(exc), True)

print("every linked answer in the penguin series on disk still reads leader form")
COUNT = re.compile(r"\((\d[\d,\-–/ ]*)\)\s*$")
groups_seen = 0
for path in sorted(Path("puzzles").glob("penguin*.js")):
    text = path.read_text(encoding="utf-8")
    puzzle = json.loads(text.split("/*JSON-START*/")[1].split("/*JSON-END*/")[0])
    entries = {e["id"]: e for e in puzzle["entries"]}
    for eid, entry in entries.items():
        group = entry.get("group") or []
        if len(group) < 2 or group[0] != eid:
            continue
        groups_seen += 1
        where = f"{puzzle['id']} {' + '.join(group)}"
        cells = sum(entries[gid]["length"] for gid in group)
        m = COUNT.search(entry["clue"])
        if not m:
            fails.append(where)
            print(f"  FAIL: {where}: the leader prints no count")
            continue
        counted = sum(int(n) for n in re.findall(r"\d+", m.group(1)))
        if counted != cells:
            fails.append(where)
            print(f"  FAIL: {where}: leader counts {counted}, the group holds {cells}")
        for gid in group[1:]:
            if COUNT.search(entries[gid]["clue"]):
                fails.append(where)
                print(f"  FAIL: {where}: {gid} is a continuation and prints its own count")
if groups_seen:
    ok(f"{groups_seen} linked groups, every one of them leader form")
else:
    fails.append("corpus sweep")
    print("  FAIL: the sweep found no linked groups at all — it is testing nothing")

print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
PY
