#!/bin/bash
# Do puzzle_integrity's two exception tables still mean EXACT, and only exact?
#
#     bash tools/test_puzzle_integrity.sh
#
# PUBLISHED_WRONG and UNLINKED_IN_SOURCE are keyed by (puzzle id, whole finding
# string), so that forgiving one sentence forgives nothing else about that
# clue. Nothing in the type system enforces that shape — a future edit could
# turn the lookup into a prefix or substring match and start swallowing real
# defects, silently, because there was no test file for puzzle_integrity.py at
# all until this one. Their exactness was proved once by hand, in the commit
# that added UNLINKED_IN_SOURCE, and then the proof was thrown away; this
# rebuilds it as something CI runs on every push instead of something a human
# remembers to redo.
#
# The property under test: lengthening every key's finding string by one
# trailing space must reproduce every finding the tables currently forgive —
# a prefix or substring match would still swallow at least some of them. And
# baselining a finding must never blank out its whole puzzle: injecting an
# unrelated LENGTH defect into cryptic-24104, which already holds two
# baselined findings, must still report the new one while the two stay silent.
#
# Both tables are consulted independently, so their entry counts — read off
# the tables themselves with len(), never typed in here — are asserted
# separately: a merge that drops one table's contents must fail loudly rather
# than being absorbed into a combined total. Building the cache of
# (puzzle, checkable-entries) once and re-running check_length against it in
# memory is what makes six passes over a corpus this size cheap enough to run
# on every push; check_shape does not depend on either table, so it only ever
# needs to run once.
#
# Run against the real corpus on purpose, for the first, second and fourth
# properties above -- an exception table is only meaningful against the data
# it actually excuses. The third property (non-blanket suppression) mutates an
# in-memory copy of one real puzzle and never writes to disk, so nothing under
# puzzles/ is ever touched.
#
# "The real corpus" means the files fetch_puzzle.puzzle_files() walks off disk,
# not the rows in puzzles/index.json. The index is a build artefact, generated
# and not committed, and every tool that reads it rebuilds it first — so the
# two agree by construction and the disk is the shorter way to say it. Walking
# it here also keeps this test off the eleven-second rebuild it does not need:
# the exception tables are keyed on clue text, which no index carries.
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
fails=0
check() { if grep -qF -- "$2" <<<"$1"; then echo "  ok: $3"; else
  echo "  FAIL: $3"$'\n'"    wanted to find: $2"$'\n'"    in: $1"; fails=$((fails + 1)); fi; }
absent() { if grep -qF -- "$2" <<<"$1"; then
  echo "  FAIL: $3"$'\n'"    did not want to find: $2"$'\n'"    in: $1"; fails=$((fails + 1));
  else echo "  ok: $3"; fi; }
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }
field() { awk -v k="$1" '$1==k {print $2}' <<<"$2"; }

echo "the CLI's own LENGTH, GRID and NUMBER tallies are zero (DUPLICATE/CROSS/SHAPE are not this test's concern)"
out=$(python3 tools/puzzle_integrity.py 2>&1)
same "LENGTH tally" "$(awk '/^  LENGTH/ {print $2}' <<<"$out")" "0"
same "GRID tally" "$(awk '/^  GRID/ {print $2}' <<<"$out")" "0"
same "NUMBER tally" "$(awk '/^  NUMBER/ {print $2}' <<<"$out")" "0"

echo "exactness: a lengthened key must not still match, and dropping one table must not touch the other"
combo=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
from datetime import datetime, timezone
import fetch_puzzle
import puzzle_integrity as pi

today = datetime.now(timezone.utc).date()

# Walked straight off disk, not off puzzles/index.json -- see the file header
# for why the committed index is not "the real corpus" for this test's
# purposes. check_shape does not read either exception table, so the corpus
# is read from disk exactly once here; every variant below reruns
# check_length in memory.
cache = []
for path in fetch_puzzle.puzzle_files():
    puzzle = pi.read_puzzle_file(path)
    flags = []
    checkable = pi.check_shape(puzzle, today, flags)
    cache.append((puzzle, checkable))

def length_count():
    # EVERY check that consults the tables, so a dropped key shows up in this
    # total whichever check would have produced its finding. The counts below
    # are read off len(table), so a check left out here reads as keys that
    # forgive nothing and fails the run — which is what caught check_cross
    # being absent from this list the day it started consulting PUBLISHED_WRONG,
    # and check_numbering the day it started doing the same.
    flags = []
    for puzzle, checkable in cache:
        pi.check_length(puzzle, checkable, flags)
        pi.check_grid(puzzle, flags)
        pi.check_numbering(puzzle, flags)
        pi.check_cross(puzzle, checkable, flags)
    return len(flags)

orig_pw = dict(pi.PUBLISHED_WRONG)
orig_uis = dict(pi.UNLINKED_IN_SOURCE)
print("TABLE_SIZES", len(orig_pw), len(orig_uis))
print("BASELINE", length_count())

def lengthen(table):
    # One trailing space on every finding string. A prefix or substring match
    # would still find the original text inside this and stay silent; an exact
    # match cannot, and the finding must reappear.
    return {(pid, finding + " "): note for (pid, finding), note in table.items()}

pi.PUBLISHED_WRONG = lengthen(orig_pw)
pi.UNLINKED_IN_SOURCE = lengthen(orig_uis)
print("LENGTHENED_BOTH", length_count())
pi.PUBLISHED_WRONG, pi.UNLINKED_IN_SOURCE = orig_pw, orig_uis

pi.PUBLISHED_WRONG = {}
print("DROP_PUBLISHED_WRONG", length_count())
pi.PUBLISHED_WRONG = orig_pw

pi.UNLINKED_IN_SOURCE = {}
print("DROP_UNLINKED_IN_SOURCE", length_count())
pi.UNLINKED_IN_SOURCE = orig_uis

print("RESTORED", length_count())
PY
)
n_pw=$(awk '$1=="TABLE_SIZES" {print $2}' <<<"$combo")
n_uis=$(awk '$1=="TABLE_SIZES" {print $3}' <<<"$combo")
same "audit() finds no LENGTH defects on the real corpus today" \
  "$(field BASELINE "$combo")" "0"
same "lengthening every key by one trailing space reproduces all $((n_pw + n_uis)) findings" \
  "$(field LENGTHENED_BOTH "$combo")" "$((n_pw + n_uis))"
same "dropping PUBLISHED_WRONG alone reproduces its own $n_pw finding(s), not UNLINKED_IN_SOURCE's" \
  "$(field DROP_PUBLISHED_WRONG "$combo")" "$n_pw"
same "dropping UNLINKED_IN_SOURCE alone reproduces its own $n_uis finding(s), not PUBLISHED_WRONG's" \
  "$(field DROP_UNLINKED_IN_SOURCE "$combo")" "$n_uis"
same "both tables restored, corpus clean again" "$(field RESTORED "$combo")" "0"

echo "non-blanket suppression: baselining a finding must not blank out the rest of its puzzle"
out3=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import copy
from datetime import datetime, timezone
import puzzle_integrity as pi

today = datetime.now(timezone.utc).date()
path = pi.PUZZLE_DIR / "cryptic-24104.js"
puzzle = copy.deepcopy(pi.read_puzzle_file(path))
by_id = {e["id"]: e for e in puzzle["entries"]}
target = by_id["1-across"]
assert target.get("solution"), "fixture assumption broken: 1-across has no solution"
# A grid-length mismatch is checked and flagged before either exception table
# is even consulted (see check_length), so no baseline could ever suppress it
# -- exactly the kind of unrelated defect that must still surface next to the
# two findings cryptic-24104 already has baselined (13-across and 16-down).
target["length"] = target["length"] + 1

flags = []
checkable = pi.check_shape(puzzle, today, flags)
pi.check_length(puzzle, checkable, flags)
findings = [f[2] for f in flags if f[0] == "LENGTH"]
print("TOTAL", len(findings))
print("NEW_DEFECT", any(f.startswith("1-across:") for f in findings))
print("PAIR_SILENT", not any(f.startswith("13-across:") or f.startswith("16-down:")
                              for f in findings))
PY
)
same "exactly one LENGTH finding survives in the mutated cryptic-24104" \
  "$(field TOTAL "$out3")" "1"
same "it is the injected 1-across defect" "$(field NEW_DEFECT "$out3")" "True"
same "the baselined 13-across/16-down pair stays silent" \
  "$(field PAIR_SILENT "$out3")" "True"

echo "a grid with no puzzle in it: every clue blank is one finding, one blank clue is none"
out4=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import copy
from datetime import datetime, timezone
import puzzle_integrity as pi

today = datetime.now(timezone.utc).date()
# A real puzzle, so the fixture cannot drift out of the shape the checker reads.
# clueMissing on every entry is the state the 2005-2008 Saturday prize puzzles are
# in: answers scraped, clue text never fetched. Per-entry forgiveness finds nothing
# wrong with any single one of them, which is the whole reason the puzzle is asked.
puzzle = copy.deepcopy(pi.read_puzzle_file(pi.PUZZLE_DIR / "cryptic-24104.js"))


def blank(p, entries):
    for e in entries:
        e["clue"], e["clueMissing"] = f"({e['length']})", True
    flags = []
    pi.check_shape(p, today, flags)
    return [f[2] for f in flags if "blank" in f[2]]


one = copy.deepcopy(puzzle)
print("ONE_BLANK", len(blank(one, one["entries"][:1])))
whole = copy.deepcopy(puzzle)
found = blank(whole, whole["entries"])
print("ALL_BLANK", len(found))
print("BLANK_SAYS", found == [f"all {len(whole['entries'])} clues are blank"])
PY
)
same "one clue the setter left blank is not a defect" "$(field ONE_BLANK "$out4")" "0"
same "a puzzle with no clue text at all is exactly one finding" \
  "$(field ALL_BLANK "$out4")" "1"
same "and it counts the clues it actually read" "$(field BLANK_SAYS "$out4")" "True"

echo "grid geometry: a light off the board and two acrosses on one cell are findings"
out5=$(PYTHONPATH="$REPO/tools" python3 - <<'XPY'
import copy
import puzzle_integrity as pi
from apply_solution import check_geometry

# A real 15x15, so the fixture cannot drift out of the shape the checker reads.
puzzle = pi.read_puzzle_file(pi.PUZZLE_DIR / "cryptic-24104.js")
print("PRISTINE", len(check_geometry(puzzle)))

# 1-across is 15 cells of a 15-wide grid. Shifted one column right it is the
# same light, still crossing everything, and no longer on the board.
off = copy.deepcopy(puzzle)
by_id = {e["id"]: e for e in off["entries"]}
assert by_id["1-across"]["length"] == off["dimensions"]["cols"], "fixture assumption broken"
by_id["1-across"]["position"]["x"] = 1
found = check_geometry(off)
print("OFFBOARD", len(found))
print("OFFBOARD_SAYS", found == ["1-across: 15 cells across from (1,0) runs off a 15x15 grid"])

# A second across laid over the first four cells of 1-across: the shape a
# mis-templated grid takes when a light is split or a block lands in the wrong
# square. Numbered like 1-across so that only the overlap rule can speak.
over = copy.deepcopy(puzzle)
twin = copy.deepcopy({e["id"]: e for e in over["entries"]}["1-across"])
twin["id"], twin["length"] = "1-across-twin", 4
over["entries"].append(twin)
found = check_geometry(over)
print("OVERLAP", len(found))
print("OVERLAP_SAYS", all(f == f"cell ({x}, 0): 2 across lights share it — "
                          "1-across, 1-across-twin" for x, f in enumerate(found)))
XPY
)
same "the puzzle as published is a coherent grid" "$(field PRISTINE "$out5")" "0"
same "a light off the board is exactly one finding" "$(field OFFBOARD "$out5")" "1"
same "and it names the light, the run and the board" "$(field OFFBOARD_SAYS "$out5")" "True"
same "two acrosses over four cells is four findings" "$(field OVERLAP "$out5")" "4"
same "each names the cell and both lights" "$(field OVERLAP_SAYS "$out5")" "True"

[ "$fails" = 0 ] && echo "puzzle_integrity: all checks passed" || echo "puzzle_integrity: $fails FAILED"
exit $((fails > 0))
