#!/usr/bin/env python3
# Does the repair tool fix the defects it knows about in already-fetched files?
#
#     python3 tools/test_repair_fetched.py
#
# Every defect tools/repair_fetched.py knows about is built here into a puzzle
# file that has it, because a repair proved only against a clean corpus is a
# repair proved against nothing — and the defects are all ones no current fetch
# produces, so the corpus cannot supply them. The fixtures go in a scratch tree
# with its own tools/ and puzzles/, which is what makes ROOT point at the
# scratch: the real corpus is never opened, and neither is whatever archive walk
# is writing into it.
#
# The two properties that matter as much as the fixes: a file with nothing wrong
# is left byte-identical, and a repaired file is clean on the second run. A
# repair that rewrites every file it reads would bury a night's real changes in
# 8,000 lines of reformatting, and one that is not idempotent cannot be run on a
# schedule.

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
fails = 0


def check(got, want, name):
    global fails
    if want in got:
        print(f"  ok: {name}")
    else:
        print(f"  FAIL: {name}\n    wanted to find: {want}\n    in: {got}")
        fails += 1


def absent(got, want, name):
    global fails
    if want in got:
        print(f"  FAIL: {name}\n    did not want to find: {want}\n    in: {got}")
        fails += 1
    else:
        print(f"  ok: {name}")


def same(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        print(f"  FAIL: {name}\n    want {want}\n    got  {got}")
        fails += 1


def sh(args, cwd, env=None, stdin=None):
    """Run a command; stdout+stderr merged, trailing newlines stripped (like $(...))."""
    p = subprocess.run(args, cwd=cwd, env=env, input=stdin, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.stdout.rstrip("\n")


work = Path(tempfile.mkdtemp())
try:
    # Readers look cached blog posts up off the SSD manifests (media_manifest):
    # empty ones here (CI has none), never the household's own.
    manifest = work / ".manifest"
    os.environ["CT_MANIFEST"] = str(manifest)
    manifest.mkdir()
    (manifest / "posts-fifteensquared.jsonl").write_text("")
    (work / "tools" / "data").mkdir(parents=True)
    (work / "puzzles").mkdir()
    for f in (REPO / "tools").glob("*.py"):
        shutil.copy(f, work / "tools")
    # The fixtures are defects in two- and three-light grids, which the writer's
    # corpus checks refuse by design; that gate has its own test,
    # tools/test_puzzle_invariants.py. Here it stands aside.
    with open(work / "tools" / "puzzle_integrity.py", "a") as f:
        f.write("\n\ndef refuse_bad_write(puzzle, old=None):\n    return None\n")
    # The tables those modules read at import (the book registry, the lexicon,
    # the source-correction tables). Copy them all: a scratch tree with the code
    # and not every table is a tree where nothing importable imports.
    shutil.copytree(REPO / "tools" / "data", work / "tools" / "data", dirs_exist_ok=True)
    # The one fixture that is NOT built here. The false-cross-reference rule is
    # gated off for the series that enumerate light by light, and a hand-written
    # Private Eye puzzle would only prove the gate against our idea of Private Eye.
    # This is the paper's own file, groups and counts as Cyclops printed them.
    cyclops = sh(["python3", "tools/puzzle_paths.py", "cyclops-401"], REPO)
    (work / cyclops).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / cyclops, work / cyclops)

    def at(pid):  # a fixture's path in the tree
        return sh(["python3", "tools/puzzle_paths.py", pid], work)

    def run(*a):
        return sh(["python3", "tools/repair_fetched.py", *a], work)

    def one(n, *a):
        # One fixture at a time: a --apply over the whole scratch tree would repair
        # the next section's fixture before that section had looked at it.
        series, num = n.split("-", 1)[0], n.rsplit("-", 1)[1]
        return run("--series", series, "--from", num, "--to", num, *a)

    GROUPS_PY = """
import json, sys, fetch_puzzle as fetcher
from pathlib import Path
from groups import entry_id
puzzle = fetcher.read_puzzle_file(Path(sys.argv[1]))
print(json.dumps([[entry_id(e), e.get("group")] for e in puzzle["entries"]]))"""

    def groups(path):
        env = dict(os.environ, PYTHONPATH="tools")
        return sh(["python3", "-c", GROUPS_PY, path], work, env=env)

    def cksum(pid):
        return hashlib.sha256((work / at(pid)).read_bytes()).hexdigest()

    def text(pid):
        return (work / at(pid)).read_text()

    # Written through the fetcher's own writer, so a fixture cannot be in a format
    # the tool would reject for reasons of its own.
    FIXTURES = r"""
from datetime import date, timedelta
import enumeration
import fetch_puzzle as fetcher
import puzzle_paths

DAY = timedelta(days=1)
def entry(eid, num, direction, x, y, length, clue, solution, group=None):
    e = {"number": num, "direction": direction,
         "position": {"x": x, "y": y}, "length": length,
         "clue": enumeration.clue(clue or ""), "solution": solution}
    if not fetcher.has_words(e["clue"].get("text", "")):
        e["clue"]["missing"] = True
    if group:
        e["group"] = group
    return e

def write(series, number, date, entries):
    pid = f"{series}-{number}"
    puzzle = {"id": pid, "number": number, "series": series,
              "name": f"Fixture {number}", "setter": "Nobody", "date": date.isoformat(),
              "dimensions": {"cols": 15, "rows": 15},
              "source": {"url": f"https://www.theguardian.com/crosswords/{series}/{number}"}, "entries": entries}
    fetcher.write_puzzle_file(puzzle_paths.PUZZLE_DIR / f"{pid}.json", puzzle)

base = date(2020, 9, 13)

# 100 — nothing wrong with it. The control: every run below must leave it alone.
write("cryptic", 100, base, [
    entry("1-across", 1, "across", 0, 0, 6, "Fail in court recess (6)", "CLOSET"),
    entry("2-down", 2, "down", 1, 0, 4, "Take a breather (4)", "LUNG")])

# 101 — the shift key missed, and an accent the grid has no cell for.
write("cryptic", 101, base + DAY, [
    entry("1-across", 1, "across", 0, 0, 7, "Highest of the lot (7)", "eVEREST"),
    entry("2-down", 2, "down", 1, 0, 7, "Galician city (7)", "ACORUÑA"),
    entry("3-down", 3, "down", 2, 0, 6, "Where the work is (6)", "office")])

# 102 — a prize puzzle whose answers are not out: one light comes back as the
# shape of the answer with the letters withheld.
write("cryptic", 102, base + 2 * DAY, [
    entry("1-across", 1, "across", 0, 0, 6, "One who tries (6)", "TESTER"),
    entry("2-down", 2, "down", 1, 0, 5, "Withheld (5)", "T?S?R")])

# 104 — cryptic 27,884's defect: 20-across's "See 5 across" is WORDPLAY, and
# the Guardian's parser read it as a cross-reference and linked the two.
# What gives it away is that each clue already counts its own light in full.
write("cryptic", 104, base + 4 * DAY, [
    entry("5-across", 5, "across", 0, 2, 7,
          "Tempted to carry Olympic torch, at last took faltering steps (7)",
          "LURCHED", ["5-across", "20-across"]),
    entry("20-across", 20, "across", 0, 10, 10,
          "See 5 across out to find another date (10)", "RESCHEDULE")])

# 105 — a genuine Guardian link, which must survive untouched: the whole count
# sits on the leading light and the continuation carries none at all.
write("cryptic", 105, base + 5 * DAY, [
    entry("1-across", 1, "across", 0, 0, 3, "The whole phrase (3,4)", "ODD",
          ["1-across", "5-across"]),
    entry("5-across", 5, "across", 0, 2, 4, "See 1", "JOBS")])

# 106 — cryptic-25,430's defect: a real linked answer with a stranger hung off
# it. NATURE I LOVED... runs over three lights and is counted once, on 22-down;
# 19-down ALL RIGHT "(3,5)" counts its own eight cells in full and is nobody
# else's business. Only the stranger leaves.
write("cryptic", 106, base + 6 * DAY, [
    entry("22-down", 22, "down", 0, 0, 6, "The whole quotation (6,1,5,3,5)",
          "NATURE", ["22-down", "23-down", "12-across", "19-down"]),
    entry("23-down", 23, "down", 2, 0, 6, "See 22", "ILOVED"),
    entry("12-across", 12, "across", 0, 6, 8, "See 22 down", "ANDNEXTX"),
    entry("19-down", 19, "down", 4, 0, 8, "None left, which is good (3,5)",
          "ALLRIGHT")])

# 107 — cryptic-23,578: IGNATIUS LOYOLA, counted "(8,6)" on the light that
# carries the clue, and a continuation that ALSO prints a count — its own six
# cells, beside the pointer. The Guardian did that routinely before about 2015.
# A bare "See 2 (6)" has no wordplay to count anything but itself, so it is not
# evidence of a false link and this answer must survive whole.
write("cryptic", 107, base + 7 * DAY, [
    entry("2-down", 2, "down", 0, 0, 8, "Saint? Saint! You and I go all funny (8,6)",
          "IGNATIUS", ["2-down", "7-down"]),
    entry("7-down", 7, "down", 4, 0, 6, "See 2 (6)", "LOYOLA")])

# 108 — cryptic-23,987: DIS, TEN, CON and TED, four three-letter answers the
# paper cross-referenced and its parser linked. 13-across counts its own three
# cells, and what that leaves is three bare "See 13" legs with no clue between
# them — not an answer, so the whole group goes rather than its leader alone.
write("cryptic", 108, base + 8 * DAY, [
    entry("13-across", 13, "across", 0, 0, 3, "The other three are not (3)",
          "DIS", ["13-across", "18-down", "16-down", "24-across"]),
    entry("18-down", 18, "down", 4, 0, 3, "See 13", "TEN"),
    entry("16-down", 16, "down", 6, 0, 3, "See 13", "CON"),
    entry("24-across", 24, "across", 0, 4, 3, "See 13", "TED")])

# 109 — cryptic-23,541: a quotation over three lights whose counts do NOT add
# up, because the Guardian's data leaves out a light the enumeration counts.
# Its last leg is printed "See 4 (2,6,3)" — a pointer with the leg's own eleven
# cells beside it. That count is not a claim to be a whole answer, so the leg
# stays where the paper put it and the group is left exactly as published.
write("cryptic", 109, base + 9 * DAY, [
    entry("4-down", 4, "down", 0, 0, 6, "The quotation (6,1,5 and 4,2,6,3)",
          "NATURE", ["4-down", "19-down", "8-down"]),
    entry("19-down", 19, "down", 2, 0, 6, "See 4", "ILOVED"),
    entry("8-down", 8, "down", 4, 0, 11, "See 4 (2,6,3)", "TONATUREART")])

# 110 — cryptic-23,816's defect, the other way round: TREAD is counted "(5,3,6)"
# over five cells and THE BOARDS sits in 10-across under "See above", in no group
# at all. The pointer names no light, so the enumeration is what says which light
# it means — and 20-down, nine cells that would fit just as well, counts itself in
# full and is an answer of its own.
write("cryptic", 110, base + 10 * DAY, [
    entry("9-across", 9, "across", 0, 4, 5, "Act in walk-on parts? (5,3,6)", "TREAD"),
    entry("10-across", 10, "across", 0, 6, 9, "See above", "THEBOARDS"),
    entry("20-down", 20, "down", 8, 0, 9,
          "Idiot with blonde hair? Don't be starting that (9)", "AIRHEADED")])

# 111 — cryptic-23,640: two answers over two lights each, and the paper printed no
# clue at all on either continuation. A light it published nothing for cannot be an
# answer by itself, so both are free — and the counts are what say which goes with
# which, RESERVE RATIOS "(7,6)" taking the six and RETAIL THERAPY "(6,7)" the seven.
write("cryptic", 111, base + 11 * DAY, [
    entry("13-across", 13, "across", 0, 2, 7,
          'Minima for bank book "A" - or it\'s going bust (7,6)', "RESERVE"),
    entry("15-across", 15, "across", 0, 6, 6, "", "RATIOS"),
    entry("17-across", 17, "across", 0, 8, 6,
          "Some relaxation in store - for 8? (6,7)", "RETAIL"),
    entry("19-across", 19, "across", 0, 10, 7, "", "THERAPY")])

# 112 — cryptic-23,609, where the arithmetic alone cannot say and the clue list
# can. Two answers of eight letters over four cells each, and TWO unclued
# four-cell lights to finish them with: every reading adds up, so the counts
# settle nothing on their own. What settles it is that an unclued leg continues
# the clue printed before it — MIST takes the RUST at 8-down, BACK the DOWN at
# 23-down. MISTRUST's "(8)" is also a word split across two lights, so it arrives
# by the arithmetic path with nothing cutting cleanly at all.
write("cryptic", 112, base + 12 * DAY, [
    entry("7-down", 7, "down", 2, 0, 4, "Doubt if small droplets corrode (8)", "MIST"),
    entry("22-down", 22, "down", 8, 0, 4, "Pull out tail feathers (4,4)", "BACK"),
    entry("8-down", 8, "down", 4, 0, 4, "", "RUST"),
    entry("23-down", 23, "down", 6, 0, 4, "", "DOWN")])

# 116 — 112's shape with the clue printed last: both unclued lights are numbered
# BEFORE the count that would take one of them. A leg the paper left unclued lost
# a pointer to a clue earlier in the list, so neither of these is this clue's, and
# nothing is written.
write("cryptic", 116, base + 16 * DAY, [
    entry("8-down", 8, "down", 4, 0, 4, "", "RUST"),
    entry("23-down", 23, "down", 6, 0, 4, "", "DOWN"),
    entry("24-down", 24, "down", 8, 0, 4, "Pull out tail feathers (4,4)", "BACK")])

# 117 — and 112's shape with the two unclued lights the same distance away,
# sharing the cell that numbers them both. The clue list puts neither nearer than
# the other, so it says no more than the arithmetic does and nothing is written:
# the count goes on contradicting itself in tools/puzzle_integrity.py, where
# somebody can see it.
write("cryptic", 117, base + 17 * DAY, [
    entry("7-down", 7, "down", 2, 0, 4, "Pull out tail feathers (4,4)", "BACK"),
    entry("8-across", 8, "across", 0, 4, 4, "", "DOWN"),
    entry("8-down", 8, "down", 0, 4, 4, "", "RUST")])

# 113 — cryptic-24,951: SET THE CAT AMONG THE PIGEONS "(3,3,3,5,3,7)" needs the THE
# in 24-across, and the paper has already spent that light on LET THE DOG SEE THE
# RABBIT. A reconstruction takes only lights the paper left spare, so the
# enumeration is left unsatisfied rather than 24-across claimed for a second answer.
write("cryptic", 113, base + 13 * DAY, [
    entry("16-down", 16, "down", 2, 0, 3,
          "To facilitate predation, dodgy mate's gone cheetah spotting (3,3,3,5,3,7)",
          "SET"),
    entry("13-across", 13, "across", 0, 2, 3, "See 16", "CAT"),
    entry("1-down", 1, "down", 0, 0, 15, "See 16", "AMONGTHEPIGEONS"),
    entry("18-down", 18, "down", 4, 0, 3, "Forgetfulness about time (3,3)", "LET",
          ["18-down", "24-across"]),
    entry("24-across", 24, "across", 0, 8, 3, "See 16", "THE")])

# A series whose numbers and dates climb together, except for one puzzle served
# under a date from 1934 — the Guardian does this at /cryptic/1183, which is
# Quiptic 1,183 wearing a cryptic's URL.
for n in range(200, 207):
    when = base + (n - 200) * 7 * DAY
    if n == 203:
        when = date(1934, 1, 18)
    # The fetcher now refuses this very write (refuse_misdated_write); the
    # fixture is the damage already on disk, so the guard is stood aside.
    import puzzle_integrity
    real = puzzle_integrity.refuse_misdated_write
    if n == 203:
        puzzle_integrity.refuse_misdated_write = lambda *a, **k: None
    write("quiptic", n, when, [
        entry("1-across", 1, "across", 0, 0, 4, "Plain (4)", "EASY")])
    puzzle_integrity.refuse_misdated_write = real
"""
    env = dict(os.environ, PYTHONPATH=str(work / "tools"))
    p = subprocess.run(["python3", "-"], input=FIXTURES, text=True, cwd=work, env=env)
    if p.returncode:
        print("FAIL: fixture build")
        sys.exit(1)

    print("a clean file is not touched, and the run says so")
    before = cksum("cryptic-100")
    out = one("cryptic-100", "--apply")
    absent(out, "cryptic-100:", "the control puzzle is not reported")
    same("byte-identical after a repair run", cksum("cryptic-100"), before)

    print("an accented or mixed-case solution is normalised to what the cells hold")
    out = one("cryptic-101")
    check(out, "cryptic-101: 3 solution(s) normalised", "all three are seen")
    check(out, "eVEREST→EVEREST", "case")
    check(out, "ACORUÑA→ACORUNA", "accent")
    check(out, "office→OFFICE", "a solution in lower case throughout")
    check(text("cryptic-101"), '"solution": "eVEREST"', "a dry run wrote nothing")
    one("cryptic-101", "--apply")
    check(text("cryptic-101"), '"solution": "ACORUNA"', "written on --apply")
    absent(one("cryptic-101"), "cryptic-101:", "clean on the second run")

    print("one masked light takes the whole puzzle unsolved, as a fetch would")
    out = one("cryptic-102")
    check(out, "cryptic-102", "the puzzle is reported")
    check(out, "2-down T?S?R", "naming the light the paper withheld")
    check(out, "all 2 entries stored unsolved", "and what that costs")
    check(out, "WARNING: cryptic-102: solution masked on", "warned on stderr")
    one("cryptic-102", "--apply")
    same("the masked puzzle is stored unsolved: no light carries a solution",
         text("cryptic-102").count('"solution"'), 0)
    absent(text("cryptic-102"), "T?S?R", "the mask is gone rather than kept as an answer")
    absent(one("cryptic-102"), "cryptic-102:", "clean on the second run")

    print("a group whose every light counts itself in full is not a linked answer")
    out = one("cryptic-104")
    check(out, "cryptic-104", "the puzzle is reported")
    check(out, "1 false cross-reference(s) dissolved: 5-across + 20-across",
          "naming the two lights the paper linked")
    check(out, "WARNING: 5-across + 20-across: every light carries a full",
          "warned on stderr, with the reason")
    check(groups(at("cryptic-104")), '"5-across", ["5-across", "20-across"]',
          "a dry run wrote nothing")
    one("cryptic-104", "--apply")
    same("both lights go back to being their own answers",
         groups(at("cryptic-104")), '[["5-across", null], ["20-across", null]]')
    absent(one("cryptic-104"), "cryptic-104:", "clean on the second run")

    print("a real linked answer is left alone")
    before = cksum("cryptic-105")
    out = one("cryptic-105", "--apply")
    absent(out, "cryptic-105", "the whole count on the leading light is not a false link")
    same("byte-identical after a repair run", cksum("cryptic-105"), before)
    same("the group survives", groups(at("cryptic-105")),
         '[["1-across", ["1-across", "5-across"]], ["5-across", null]]')

    print("Private Eye prints a count per light, so the rule is off for cyclops")
    before = cksum("cyclops-401")
    out = one("cyclops-401", "--apply")
    absent(out, "cyclops-401", "nothing is wrong with the paper's own file")
    absent(out, "dissolved", "and none of its five per-light groups is dissolved")
    same("byte-identical after a repair run", cksum("cyclops-401"), before)
    same("2-down (4-6) and 22-down (6) are still one answer",
         json.dumps(dict(json.loads(groups(at("cyclops-401"))))["2-down"]),
         '["2-down", "22-down"]')

    print("a light that counts itself in full leaves the group it was hung on")
    out = one("cryptic-106")
    check(out, "cryptic-106", "the puzzle is reported")
    check(out, "1 false cross-reference(s) dissolved: 19-down",
          "naming the stranger and not the answer it was hung on")
    check(out, "WARNING: 19-down: counts its own light in full",
          "warned on stderr, with the reason")
    one("cryptic-106", "--apply")
    same("the quotation keeps its three lights and the stranger is free",
         groups(at("cryptic-106")),
         '[["22-down", ["22-down", "23-down", "12-across"]], ["23-down", null], ["12-across", null], ["19-down", null]]')
    absent(one("cryptic-106"), "cryptic-106:", "clean on the second run")

    print("a continuation that prints its own cell count is not a false link")
    before = cksum("cryptic-107")
    out = one("cryptic-107", "--apply")
    absent(out, "cryptic-107", '"See 2 (6)" counts the leg, not the answer')
    same("byte-identical after a repair run", cksum("cryptic-107"), before)
    same("IGNATIUS LOYOLA survives whole", groups(at("cryptic-107")),
         '[["2-down", ["2-down", "7-down"]], ["7-down", null]]')

    print("a group left with no clue in it is four answers, not one")
    out = one("cryptic-108")
    check(out, "1 false cross-reference(s) dissolved: 13-across + 18-down + 16-down + 24-across",
          "the whole group goes, not just the light that counts itself")
    check(out, "WARNING: 13-across + 18-down + 16-down + 24-across: 13-across counts its own light in full and what is left carries no clue",
          "warned on stderr, with the reason")
    one("cryptic-108", "--apply")
    same("all four are their own answers again", groups(at("cryptic-108")),
         '[["13-across", null], ["18-down", null], ["16-down", null], ["24-across", null]]')
    absent(one("cryptic-108"), "cryptic-108:", "clean on the second run")

    print("a counted leg is still a leg when the paper's own counts do not add up")
    before = cksum("cryptic-109")
    out = one("cryptic-109", "--apply")
    absent(out, "cryptic-109", '"See 4 (2,6,3)" is not a light claiming to be an answer')
    same("byte-identical after a repair run", cksum("cryptic-109"), before)
    same("all three lights stay in the quotation", groups(at("cryptic-109")),
         '[["4-down", ["4-down", "19-down", "8-down"]], ["19-down", null], ["8-down", null]]')

    print("a light the paper left out of the group is put back when the counts say so")
    out = one("cryptic-110")
    check(out, "cryptic-110", "the puzzle is reported")
    check(out, "1 linked answer(s) reassembled: 9-across + 10-across",
          "naming the light that was missing")
    check(out, "WARNING: 9-across: its enumeration counts 10-across",
          "warned on stderr, with the reason")
    same("a dry run wrote nothing", groups(at("cryptic-110")),
         '[["9-across", null], ["10-across", null], ["20-down", null]]')
    one("cryptic-110", "--apply")
    same("TREAD THE BOARDS is one answer, and the light that counts itself is not in it",
         groups(at("cryptic-110")),
         '[["9-across", ["9-across", "10-across"]], ["10-across", null], ["20-down", null]]')
    absent(one("cryptic-110"), "cryptic-110:", "clean on the second run")

    print("a light the paper printed no clue for is free, and the counts say whose")
    out = one("cryptic-111")
    check(out, "2 linked answer(s) reassembled: 13-across + 15-across, 17-across + 19-across",
          "both answers, each taking the unclued light its own count fits")
    one("cryptic-111", "--apply")
    same("RESERVE RATIOS and RETAIL THERAPY, not crossed over",
         groups(at("cryptic-111")),
         '[["13-across", ["13-across", "15-across"]], ["15-across", null], ["17-across", ["17-across", "19-across"]], ["19-across", null]]')
    absent(one("cryptic-111"), "cryptic-111:", "clean on the second run")

    print("when several readings add up, the unclued leg belongs to the clue before it")
    out = one("cryptic-112")
    check(out, "2 linked answer(s) reassembled: 22-down + 23-down, 7-down + 8-down",
          "each count takes the unclued light that follows it, not the other one")
    check(out, "WARNING: 7-down: 2 sets of spare lights hold the letters it counts",
          "warned on stderr, saying the choice was made and how")
    one("cryptic-112", "--apply")
    same("MISTRUST and BACK DOWN, not crossed over", groups(at("cryptic-112")),
         '[["7-down", ["7-down", "8-down"]], ["22-down", ["22-down", "23-down"]], ["8-down", null], ["23-down", null]]')
    absent(one("cryptic-112"), "cryptic-112:", "clean on the second run")

    print("an unclued light numbered before the clue is not that clue's continuation")
    before = cksum("cryptic-116")
    out = one("cryptic-116", "--apply")
    absent(out, "cryptic-116", "nothing follows the count, so nothing is reassembled")
    same("byte-identical after a repair run", cksum("cryptic-116"), before)
    same("all three lights are left as published", groups(at("cryptic-116")),
         '[["8-down", null], ["23-down", null], ["24-down", null]]')

    print("two readings the clue list cannot separate mean the data does not say")
    before = cksum("cryptic-117")
    out = one("cryptic-117", "--apply")
    absent(out, "cryptic-117", "an ambiguous reconstruction is not a repair")
    same("byte-identical after a repair run", cksum("cryptic-117"), before)
    same("all three lights are left as published", groups(at("cryptic-117")),
         '[["7-down", null], ["8-across", null], ["8-down", null]]')

    print("a light already in somebody else's answer is not taken for this one")
    before = cksum("cryptic-113")
    out = one("cryptic-113", "--apply")
    absent(out, "cryptic-113", "the enumeration is left unsatisfied instead")
    same("byte-identical after a repair run", cksum("cryptic-113"), before)
    same("24-across stays where the paper put it", groups(at("cryptic-113")),
         '[["16-down", null], ["13-across", null], ["1-down", null], ["18-down", ["18-down", "24-across"]], ["24-across", null]]')

    print("a date its own neighbours contradict is reported and never guessed at")
    out = run()
    check(out, "quiptic-203: dated 1934-01-18", "the stored date")
    check(out, "mis-filed, re-fetch it", "what to do about it")
    check(out, "1 mis-filed date(s)", "counted apart from the repairs")
    absent(out, "quiptic-202", "a puzzle in line with its neighbours is not flagged")
    before = cksum("quiptic-203")
    run("--series", "quiptic", "--apply")
    same("left exactly as it was, because the real date is not here to be had",
         cksum("quiptic-203"), before)

    print("the selection flags keep a run off everything else")
    out = run("--series", "quiptic")
    absent(out, "cryptic-", "--series quiptic examines no cryptics")
    check(out, "7 file(s) examined", "and all seven quiptics")
    out = run("--series", "quiptic", "--from", "204")
    check(out, "3 file(s) examined", "--from cuts the range")
    absent(out, "quiptic-203", "a file outside the range is not reported")
    out = run("--series", "quiptic", "--from", "203", "--to", "203")
    check(out, "quiptic-203: dated 1934-01-18",
          "but its neighbours are still read, or one file could not be judged at all")
    out = run("--series", "nosuchseries")
    check(out, "no series 'nosuchseries'", "a misspelt series is an error, not an empty run")
    out = run("--apply", "--dry-run")
    check(out, "--apply and --dry-run say opposite things", "and so is asking for both")
finally:
    shutil.rmtree(work, ignore_errors=True)

print("a scan's slips in a clue's text are mended in place, annotation offsets moved with the words")
sys.path.insert(0, str(REPO / "tools"))
os.environ["VLM_READER_URL"] = ""
import repair_fetched as rf
slips = {"entries": [
    {"number": 9, "direction": "across", "clue": {"text": "Mostly smart English group indulging in idle gossip 9.", "enumeration": "9"}},
    {"number": 10, "direction": "across", "clue": {"text": "I Long pair of shorts?", "enumeration": "6"}},
    {"number": 1, "direction": "down", "clue": {
        "text": "Fodder for the right variety of grey . donkey", "enumeration": "6", "italics": [{"at": 39, "length": 6}]},
        "annotation": {"definition": {"at": 39, "length": 6}}},
    {"number": 2, "direction": "down", "clue": {"text": "Plain clue about a thing", "enumeration": "5"}}]}
done = rf.mend_clue_text(slips)
check(" ".join(sorted(done)), "1-down 10-across 9-across", "the three slipped lights are named and the plain one is not")
check(slips["entries"][0]["clue"]["text"], "Mostly smart English group indulging in idle gossip", "the count left in the text is cut")
check(slips["entries"][1]["clue"]["text"], "Long pair of shorts?", "a bar read as I is cut")
check(slips["entries"][2]["clue"]["text"], "Fodder for the right variety of grey donkey", "a lone stop is cut")
check(str(slips["entries"][2]["clue"]["italics"][0]["at"]), "37", "the italics stay on donkey")
check(slips["entries"][3]["clue"]["text"], "Plain clue about a thing", "a plain clue is untouched")
check(str(rf.offsets("ab . cd", "ab cd")), "[0, 1, 2, 3, 3, 3, 4, 5]", "offsets: kept characters move with their block")
check(str(rf.mend_clue_text(slips)), "{}", "a second run changes nothing")

print("a count with a bar glued on is cut unless a light of the puzzle has that number")
barred = {"entries": [
    {"number": 3, "direction": "across", "clue": {"text": "One caught in the actual act of robbing 81", "enumeration": "8"}},
    {"number": 15, "direction": "across", "clue": {"text": "Mum not seen to follow 15", "enumeration": "5"}},
    {"number": 4, "direction": "down", "clue": {"text": "Birds follow 15", "enumeration": "5"}},
    {"number": 5, "direction": "down", "clue": {"text": "Girl getting dreadfully hot in boat 17", "enumeration": "7"}},
    {"number": 6, "direction": "down", "clue": {"text": "Each movement causes pain 141", "enumeration": "4"}}]}
done = rf.mend_clue_text(barred)
check(" ".join(sorted(done)), "3-across 5-down 6-down", "81, 17 (no light 17) and 141 are cut; 15 is a light, so a reference")
check(barred["entries"][1]["clue"]["text"], "Mum not seen to follow 15", "a number a light has is kept")

print("the learned mends alone leave the older text rules to their own repair")
only = {"entries": [
    {"number": 1, "direction": "across", "clue": {"text": "Decide to change denims, with lipstick 0on?", "enumeration": "7"}},
    {"number": 2, "direction": "across", "clue": {"text": "Run up loose dress as a tem temporary measure", "enumeration": "9"}},
    {"number": 3, "direction": "down", "clue": {"text": "Education initially by _the three Rs contains no fault", "enumeration": "9"}},
    {"number": 4, "direction": "down", "clue": {"text": "I Long pair of shorts?", "enumeration": "6"}},
    {"number": 5, "direction": "down", "clue": {"text": "Fodder for the right variety of grey . donkey", "enumeration": "6"}}]}
done = rf.mend_clue_text(only, learned_only=True)
check(" ".join(sorted(done)), "1-across 2-across 3-down", "a speck, a stub and a stroke are mended; a drop bar and a lone stop are not")
check(only["entries"][3]["clue"]["text"], "I Long pair of shorts?", "the older bar rule is not run")

print("--mends runs the full mend_text less the rules found wrong on held text, and names the rule of each change")
full = {"entries": [
    {"number": 1, "direction": "across", "clue": {"text": "Origin of . High Church music ?", "enumeration": "5"}},
    {"number": 2, "direction": "across", "clue": {"text": "D Day, camouflage?", "enumeration": "5"}},
    {"number": 3, "direction": "down", "clue": {"text": "Put in the slippers, de rigueur for travel", "enumeration": "5"}},
    {"number": 4, "direction": "down", "clue": {"text": "Lose one's footing in an expedition (4) 271 Becoming hot", "enumeration": "4"}},
    {"number": 5, "direction": "down", "clue": {"text": "4In a manner of speaking", "enumeration": "5"}}]}
trail = []
done = rf.mend_clue_text(full, skip=rf.EXCLUDED_MENDS, log=trail)
check(" ".join(sorted(done)), "1-across 4-down 5-down", "a stray stop, a bled neighbour and a glued number are mended; D Day is left")
check(full["entries"][1]["clue"]["text"], "D Day, camouflage?", "lead_speck keeps D Day")
check(full["entries"][2]["clue"]["text"], "Put in the slippers, de rigueur for travel", "mend_words keeps de rigueur")
check(" ".join(sorted(r for _p, _l, r, _w, _n in trail)), "bled_count glued_number stray_underscore", "each change is logged under its rule")
check(str(len(rf.EXCLUDED_MENDS)), "0", "the tightened rules are no longer excluded")

print("a reread's stray neighbouring words are what a spoiled clue's repair takes back")
check(str(rf.grown("Fluid that comes with a plant", "Fluid that comes with a plant Wales. Midlands.")), "True", "two stray words after the clue are grown")
check(str(rf.grown("Understand something in a tongue", "Understand I something in a tongue")), "True", "a stray letter inside is grown")
check(str(rf.grown("Love a fellow", "Love a fellow and a friend too")), "False", "a run of real words is a clue the held copy cut short")
check(str(rf.grown("Fellow in city shell", "Fellow in city's shell")), "False", "a changed word is no growth")
check(str(rf.grown("Frontier cantonment", "Frontier cantonment")), "False", "the same words are no growth")

print("a reread that cut a word is taken back from the commit's parent")
import copy
def reading(*texts):
    return {"entries": [{"number": n + 1, "direction": "across", "clue": {"text": t, "enumeration": "5"}}
                        for n, t in enumerate(texts)]}
parent, child = reading("Boy, good at heart", "Dog the 1st Earl"), reading("Boy, good at hear", "Dog the 1st Earl, now")
current = copy.deepcopy(child)
saved = {}
real = (rf.spoiled_commits, rf.git_out, rf.puzzle_paths.find, rf.fetcher.read_puzzle_file, rf.fetcher.write_puzzle_file)
rf.spoiled_commits = lambda since, ref: {"times-1": [("abc", "puzzles/times/1/times-1.json")]}
rf.git_out = lambda *a: json.dumps(parent if a[1] == "abc^:puzzles/times/1/times-1.json" else child)
rf.puzzle_paths.find = lambda pid: Path("times-1.json")
rf.fetcher.read_puzzle_file = lambda path: copy.deepcopy(current)
rf.fetcher.write_puzzle_file = lambda path, p: saved.update(wrote=copy.deepcopy(p))
try:
    dry = rf.repair_regressed_clues()
    wrote_dry = "wrote" in saved
    done = rf.repair_regressed_clues(apply_it=True)
finally:
    rf.spoiled_commits, rf.git_out, rf.puzzle_paths.find, rf.fetcher.read_puzzle_file, rf.fetcher.write_puzzle_file = real
same("only the cut word is restored", dry, [("times-1", "1-across", "Boy, good at hear", "Boy, good at heart")])
same("a dry run writes nothing", wrote_dry, False)
same("an applied repair writes the held words and leaves the other clue",
     [saved["wrote"]["entries"][0]["clue"]["text"], saved["wrote"]["entries"][1]["clue"]["text"]],
     ["Boy, good at heart", "Dog the 1st Earl, now"])

print("only a count the grid gave is given its word breaks back; a bare count that was read stays")
breaks = ({"SHEEPSHEARING": "5,8"}, frozenset())
lights = {"entries": [
    {"number": 1, "direction": "across", "solution": "SHEEPSHEARING", "clue": {"text": "Printed bare", "enumeration": "13"}},
    {"number": 2, "direction": "across", "solution": "SHEEPSHEARING",
     "clue": {"text": "Grid gave it", "enumeration": "13", "countFrom": "grid"}}]}
same("lost_word_breaks names only the grid-counted light", rf.fetcher.lost_word_breaks(lights, breaks), {"2-across": "5,8"})
rf.fetcher.answer_breaks.cache_clear()

print("misdated_ft: an FT date on a Sunday, another number's day or out of number order is redated "
      "to the day its numbered neighbours count to, or left")
import datetime as _d
D = _d.date.fromisoformat
url = ("https://archive.org/details/FinancialTimes1989UKEnglish/"
       "Jan%2022%201989%2C%20Financial%20Times%2C%20%2330749%2C%20UK%20%28en%29/page/n43/mode/1up")
same("an FT page url names its item and edition dir", rf.ft_edition(url),
     ("FinancialTimes1989UKEnglish", "1989-01-22_30749"))
rows = [(6839, D("1989-01-20"), None), (6840, D("1989-01-22"), url), (6841, D("1989-01-23"), None)]
same("a Sunday between Friday's and Monday's numbers is the Saturday",
     [(n, fixed) for n, _s, fixed, _c, _w in rf.misdated_ft(rows)], [(6840, D("1989-01-21"))])
rows = [(2259, D("1973-08-28"), None), (2260, D("1973-08-29"), None), (2261, D("1973-08-30"), None),
        (2262, D("1973-08-30"), None), (2264, D("1973-09-03"), None)]
same("of two numbers on one day, the one its neighbours count elsewhere moves and the other is left (ftcryptic-2262)",
     [(n, fixed) for n, _s, fixed, _c, _w in rf.misdated_ft(rows)], [(2261, None), (2262, D("1973-08-31"))])
rows = [(3681, D("1978-07-01"), None), (3682, D("1978-07-02"), None), (3683, D("1978-07-03"), None)]
same("(mirror) a Sunday with no free day between its numbered neighbours is left",
     [(n, fixed) for n, _s, fixed, _c, _w in rf.misdated_ft(rows)], [(3682, None)])
rows = [(2829, D("1975-07-15"), None), (2833, D("1975-07-16"), None), (2834, D("1975-07-21"), None),
        (2832, D("1975-07-18"), None)]
same("a date out of number order moves to the day its neighbours count to (ftcryptic-2833)",
     [(n, fixed) for n, _s, fixed, _c, _w in rf.misdated_ft(rows) if n == 2833], [(2833, D("1975-07-19"))])
same("(mirror) dates in number order are not listed",
     rf.misdated_ft([(1, D("1975-07-15"), None), (2, D("1975-07-16"), None)]), [])

print("misnumbered_titles: a Times puzzle filed one below the title its page prints is renamed to it, "
      "newest first; one whose title another day holds is left")
# Times 2002: 22129 filed for Wed 08-28, whose page prints No 22130 over the solution of 22129;
# Thu 08-29's No 22131 filed as 22130, Sat 08-31's No 22133 (its heading only the prize's, 22127)
# as 22132, Mon 09-02's No 22134 (no heading: Tuesday's names it) as 22133; 08-27's No 22129 was
# refused as taken. 08-26's 22128 is right.
titles = {D("2002-08-26"): [22128], D("2002-08-27"): [22129], D("2002-08-28"): [22130], D("2002-08-29"): [22131],
          D("2002-08-30"): [22132], D("2002-08-31"): [22133], D("2002-09-02"): [22134], D("2002-09-03"): [22135]}
headings = {D("2002-08-27"): [22128], D("2002-08-28"): [22129], D("2002-08-29"): [22130], D("2002-08-30"): [22131],
            D("2002-08-31"): [22127], D("2002-09-03"): [22134]}
held = {22128: D("2002-08-26"), 22129: D("2002-08-28"), 22130: D("2002-08-29"), 22131: D("2002-08-30"),
        22132: D("2002-08-31"), 22133: D("2002-09-02"), 22135: D("2002-09-03")}
same("each one-low file moves to its title, newest first, each target freed by the one before",
     rf.misnumbered_titles(titles, headings, held),
     [(22133, D("2002-09-02"), 22134, None), (22132, D("2002-08-31"), 22133, None), (22131, D("2002-08-30"), 22132, None),
      (22130, D("2002-08-29"), 22131, None), (22129, D("2002-08-28"), 22130, None)])
same("(mirror) a title no heading bears out is not moved",
     [r[0] for r in rf.misnumbered_titles(titles, {}, held)], [])
# 1992: Tue 05-05 and Wed 05-06 both print No 18911 (Thursday's heading names Wednesday's).
same("a title another day's file holds is left, named",
     rf.misnumbered_titles({D("1992-05-05"): [18911], D("1992-05-06"): [18911]}, {D("1992-05-05"): [18910]},
                           {18910: D("1992-05-05"), 18911: D("1992-05-06")}),
     [(18910, D("1992-05-05"), 18911, "No 18911 is filed for 1992-05-06")])
same("a title the same day's other file holds is a duplicate",
     [r[3] for r in rf.misnumbered_titles({D("2002-08-28"): [22130]}, {D("2002-08-28"): [22129]},
                                          {22129: D("2002-08-28"), 22130: D("2002-08-28")})], ["duplicate"])
moved_dir = Path(tempfile.mkdtemp())
try:
    src = moved_dir / "times-22129.json"
    puzzle = {"id": "times-22129", "number": 22129, "date": "2002-08-28", "entries": []}
    src.write_text(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n")
    (moved_dir / "times-22129.js").write_text("// old shim\n")
    same("(dry run) renumber_file names the new path and writes nothing",
         [rf.renumber_file(src, puzzle, 22130).name, sorted(p.name for p in moved_dir.iterdir())],
         ["times-22130.json", ["times-22129.js", "times-22129.json"]])
    dest = rf.renumber_file(src, puzzle, 22130, apply_it=True)
    same("renumber_file moves the file and its shim to the title's id and number",
         [sorted(p.name for p in moved_dir.iterdir()), json.loads(dest.read_text())["id"],
          json.loads(dest.read_text())["number"]],
         [["times-22130.js", "times-22130.json"], "times-22130", 22130])
finally:
    shutil.rmtree(moved_dir, ignore_errors=True)

print("repair_fetched: all checks passed" if fails == 0 else f"repair_fetched: {fails} FAILED")
sys.exit(1 if fails else 0)
