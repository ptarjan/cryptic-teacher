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
# not the rows in the committed puzzles/index.json. That index is a build
# artefact this repo deliberately never stages from a test run (it collides
# between whatever else is fetching or annotating at the same time — see
# tools/test_push_conflict.sh), so at any given moment it can be stale in
# either direction: entries for files a later commit removed, or files a
# later commit added that it was never re-run to pick up. Neither kind of
# staleness is a LENGTH defect or anything the exception tables touch, and a
# test that read the index instead of the disk would go red for either one
# and teach everybody to ignore its failures. check_shape's own "not on disk"
# SHAPE flag is what catches an index that has drifted; this file has nothing
# to add to that and does not try.
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

echo "the CLI's own LENGTH tally is zero (DUPLICATE/CROSS/SHAPE are not this test's concern)"
out=$(python3 tools/puzzle_integrity.py 2>&1)
same "LENGTH tally" "$(awk '/^  LENGTH/ {print $2}' <<<"$out")" "0"

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
    flags = []
    for puzzle, checkable in cache:
        pi.check_length(puzzle, checkable, flags)
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

[ "$fails" = 0 ] && echo "puzzle_integrity: all checks passed" || echo "puzzle_integrity: $fails FAILED"
exit $((fails > 0))
