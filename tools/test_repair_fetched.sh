#!/bin/bash
# Does the repair tool actually fix what the fetcher no longer writes?
#
#     bash tools/test_repair_fetched.sh
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

work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
mkdir -p "$work/tools" "$work/puzzles"
cp "$REPO"/tools/*.py "$work/tools/"
# The one fixture that is NOT built here. The false-cross-reference rule is
# gated off for the series that enumerate light by light, and a hand-written
# Private Eye puzzle would only prove the gate against our idea of Private Eye.
# This is the paper's own file, groups and counts as Cyclops printed them.
cp "$REPO"/puzzles/cyclops-401.js "$work/puzzles/"
run() { (cd "$work" && python3 tools/repair_fetched.py "$@" 2>&1); }
# One fixture at a time: a --apply over the whole scratch tree would repair the
# next section's fixture before that section had looked at it.
one() { local n=$1; shift; run --series "${n%%-*}" --from "${n##*-}" --to "${n##*-}" "$@"; }
groups() { (cd "$work" && PYTHONPATH=tools python3 -c '
import json, sys, fetch_puzzle as fetcher
from pathlib import Path
puzzle = fetcher.read_puzzle_file(Path(sys.argv[1]))
print(json.dumps([[e["id"], e.get("group")] for e in puzzle["entries"]]))' "$1"); }

# Written through the fetcher's own writer, so a fixture cannot be in a format
# the tool would reject for reasons of its own.
PYTHONPATH="$work/tools" python3 - "$work" <<'PY'
import sys
from datetime import datetime, timezone
from pathlib import Path
root = Path(sys.argv[1])
import fetch_puzzle as fetcher
fetcher.PUZZLE_DIR = root / "puzzles"

DAY = 86_400_000
def entry(eid, num, direction, x, y, length, clue, solution, group=None):
    e = {"id": eid, "number": num, "direction": direction,
         "position": {"x": x, "y": y}, "length": length, "clue": clue,
         "separatorLocations": {}, "solution": solution, "annotation": None}
    if group:
        e["group"] = group
    return e

def write(series, number, date, entries):
    pid = f"{series}-{number}"
    puzzle = {"id": pid, "number": number, "series": series,
              "name": f"Fixture {number}", "setter": "Nobody", "date": date,
              "dimensions": {"cols": 15, "rows": 15},
              "sourceUrl": f"https://example.invalid/{pid}", "entries": entries}
    fetcher.write_puzzle_file(fetcher.PUZZLE_DIR / f"{pid}.js", puzzle)

base = 1_600_000_000_000

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

# 103 — three lights of one answer, each naming a different pair as the group.
# The enumeration on the leading clue is what settles the order.
write("cryptic", 103, base + 3 * DAY, [
    entry("13-across", 13, "across", 0, 4, 8, "Second word (8)", "SYMPHONY",
          ["3-down", "13-across"]),
    entry("21-across", 21, "across", 0, 8, 9, "Third word (9)", "ORCHESTRA",
          ["3-down", "21-across"]),
    entry("3-down", 3, "down", 2, 0, 6, "The whole thing (6,8,9)", "LONDON",
          ["3-down", "21-across"])])

# 104 — cryptic 27,884's defect: 20-across's "See 5 across" is WORDPLAY, and
# the Guardian's parser read it as a cross-reference and linked the two. Both
# lights agree about the membership, so reconcile_groups has nothing to fix —
# what gives it away is that each clue already counts its own light in full.
write("cryptic", 104, base + 4 * DAY, [
    entry("5-across", 5, "across", 0, 2, 7,
          "Tempted to carry Olympic torch, at last took faltering steps (7)",
          "LURCHED", ["5-across", "20-across"]),
    entry("20-across", 20, "across", 0, 10, 10,
          "See 5 across out to find another date (10)", "RESCHEDULE",
          ["5-across", "20-across"])])

# 105 — a genuine Guardian link, which must survive untouched: the whole count
# sits on the leading light and the continuation carries none at all.
write("cryptic", 105, base + 5 * DAY, [
    entry("1-across", 1, "across", 0, 0, 3, "The whole phrase (3,4)", "ODD",
          ["1-across", "5-across"]),
    entry("5-across", 5, "across", 0, 2, 4, "See 1", "JOBS",
          ["1-across", "5-across"])])

# 106 — cryptic-25,430's defect: a real linked answer with a stranger hung off
# it. NATURE I LOVED... runs over three lights and is counted once, on 22-down;
# 19-down ALL RIGHT "(3,5)" counts its own eight cells in full and is nobody
# else's business. Only the stranger leaves.
write("cryptic", 106, base + 6 * DAY, [
    entry("22-down", 22, "down", 0, 0, 6, "The whole quotation (6,1,5,3,5)",
          "NATURE", ["22-down", "23-down", "12-across", "19-down"]),
    entry("23-down", 23, "down", 2, 0, 6, "See 22", "ILOVED",
          ["22-down", "23-down", "12-across", "19-down"]),
    entry("12-across", 12, "across", 0, 6, 8, "See 22 down", "ANDNEXTX",
          ["22-down", "23-down", "12-across", "19-down"]),
    entry("19-down", 19, "down", 4, 0, 8, "None left, which is good (3,5)",
          "ALLRIGHT", ["22-down", "23-down", "12-across", "19-down"])])

# 107 — cryptic-23,578: IGNATIUS LOYOLA, counted "(8,6)" on the light that
# carries the clue, and a continuation that ALSO prints a count — its own six
# cells, beside the pointer. The Guardian did that routinely before about 2015.
# A bare "See 2 (6)" has no wordplay to count anything but itself, so it is not
# evidence of a false link and this answer must survive whole.
write("cryptic", 107, base + 7 * DAY, [
    entry("2-down", 2, "down", 0, 0, 8, "Saint? Saint! You and I go all funny (8,6)",
          "IGNATIUS", ["2-down", "7-down"]),
    entry("7-down", 7, "down", 4, 0, 6, "See 2 (6)", "LOYOLA",
          ["2-down", "7-down"])])

# 108 — cryptic-23,987: DIS, TEN, CON and TED, four three-letter answers the
# paper cross-referenced and its parser linked. 13-across counts its own three
# cells, and what that leaves is three bare "See 13" legs with no clue between
# them — not an answer, so the whole group goes rather than its leader alone.
write("cryptic", 108, base + 8 * DAY, [
    entry("13-across", 13, "across", 0, 0, 3, "The other three are not (3)",
          "DIS", ["13-across", "18-down", "16-down", "24-across"]),
    entry("18-down", 18, "down", 4, 0, 3, "See 13", "TEN",
          ["13-across", "18-down", "16-down", "24-across"]),
    entry("16-down", 16, "down", 6, 0, 3, "See 13", "CON",
          ["13-across", "18-down", "16-down", "24-across"]),
    entry("24-across", 24, "across", 0, 4, 3, "See 13", "TED",
          ["13-across", "18-down", "16-down", "24-across"])])

# 109 — cryptic-23,541: a quotation over three lights whose counts do NOT add
# up, because the Guardian's data leaves out a light the enumeration counts.
# Its last leg is printed "See 4 (2,6,3)" — a pointer with the leg's own eleven
# cells beside it. That count is not a claim to be a whole answer, so the leg
# stays where the paper put it and the group is left exactly as published.
write("cryptic", 109, base + 9 * DAY, [
    entry("4-down", 4, "down", 0, 0, 6, "The quotation (6,1,5 and 4,2,6,3)",
          "NATURE", ["4-down", "19-down", "8-down"]),
    entry("19-down", 19, "down", 2, 0, 6, "See 4", "ILOVED",
          ["4-down", "19-down", "8-down"]),
    entry("8-down", 8, "down", 4, 0, 11, "See 4 (2,6,3)", "TONATUREART",
          ["4-down", "19-down", "8-down"])])

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

# 112 — cryptic-23,609, which holds both ways of not being able to say. BACK DOWN
# is counted "(4,4)" over four cells and the puzzle has TWO unclued four-cell
# lights: both readings cut the enumeration exactly, so the data does not say which
# is the answer. MISTRUST is counted "(8)" over four cells, and no reading cuts at
# all, because an enumerated word cannot be split across two lights. Zero fits or
# several, nothing is written and the count goes on contradicting itself in
# tools/puzzle_integrity.py, where somebody can see it.
write("cryptic", 112, base + 12 * DAY, [
    entry("7-down", 7, "down", 2, 0, 4, "Doubt if small droplets corrode (8)", "MIST"),
    entry("22-down", 22, "down", 8, 0, 4, "Pull out tail feathers (4,4)", "BACK"),
    entry("8-down", 8, "down", 4, 0, 4, "", "RUST"),
    entry("23-down", 23, "down", 6, 0, 4, "", "DOWN")])

# 113 — cryptic-24,951: SET THE CAT AMONG THE PIGEONS "(3,3,3,5,3,7)" needs the THE
# in 24-across, and the paper has already spent that light on LET THE DOG SEE THE
# RABBIT. One `group` field cannot hold a light that ends two answers, so the
# enumeration is left unsatisfied rather than 18-down quietly robbed.
write("cryptic", 113, base + 13 * DAY, [
    entry("16-down", 16, "down", 2, 0, 3,
          "To facilitate predation, dodgy mate's gone cheetah spotting (3,3,3,5,3,7)",
          "SET"),
    entry("13-across", 13, "across", 0, 2, 3, "See 16", "CAT"),
    entry("1-down", 1, "down", 0, 0, 15, "See 16", "AMONGTHEPIGEONS"),
    entry("18-down", 18, "down", 4, 0, 3, "Forgetfulness about time (3,3)", "LET",
          ["18-down", "24-across"]),
    entry("24-across", 24, "across", 0, 8, 3, "See 16", "THE",
          ["18-down", "24-across"])])

# 114 — cryptic-24,640: FROM THE NEW WORLD over 13-across, 18-across and
# 20-across, which the Guardian's markup grouped as "18-DOWN" — a light the
# puzzle does not have. The light that was meant is not in the data, so the
# group goes whole rather than being shortened to the two lights that are here
# and storing FROM THE + WORLD as a finished answer. 20-across then names its
# three leading clues, which is a light ending three answers and is allowed to
# disagree with every one of them: NEW WORLD ORDER keeps its group.
write("cryptic", 114, base + 14 * DAY, [
    entry("13-across", 13, "across", 0, 4, 7,
          "Work of 23, originating in 9 or 29, say (4,3,3,2)", "FROMTHE",
          ["13-across", "18-down", "20-across"]),
    entry("17-across", 17, "across", 0, 6, 5,
          "Novel utterance from 25, originally in 14 (5,3,5)", "BRAVE",
          ["17-across", "18-down", "20-across"]),
    entry("18-across", 18, "across", 0, 8, 3,
          "Dr Low, possibly, providing answer to all our ills (3,5,5)", "NEW",
          ["18-across", "20-across", "31-across"]),
    entry("20-across", 20, "across", 0, 10, 5, "See 13, 17 and 18", "WORLD",
          ["13-across", "18-down", "20-across"]),
    entry("31-across", 31, "across", 0, 12, 5, "See 18", "ORDER",
          ["18-across", "20-across", "31-across"])])

# 115 — cryptic-25,126: MAJOR AND MINOR over three lights, with ASIA MINOR and
# DRUM MAJOR each claiming one of them for a second answer. Every claim adds up,
# so reconcile_groups leaves all three as published — and two of them are stated
# by one side only, because 17-across and 20-across store the answer they are
# both in. "See 17" names ONE leading clue, so it is held to its group and the
# claims on it go; MAJOR AND MINOR is untouched.
write("cryptic", 115, base + 15 * DAY, [
    entry("6-down", 6, "down", 0, 0, 4, "Romania is unsettled region near Greece (4,5)",
          "ASIA", ["6-down", "20-across"]),
    entry("8-down", 8, "down", 2, 0, 4, "NCO and daughter having drink with PM once (4,5)",
          "DRUM", ["8-down", "17-across"]),
    entry("17-across", 17, "across", 0, 4, 5,
          "Like 4 and 11, or 24 down and 22 down, or 13 across, 14 and 27 (5,3,5)",
          "MAJOR", ["17-across", "19-across", "20-across"]),
    entry("19-across", 19, "across", 0, 6, 3, "See 17", "AND",
          ["17-across", "19-across", "20-across"]),
    entry("20-across", 20, "across", 0, 8, 5, "See 17", "MINOR",
          ["17-across", "19-across", "20-across"])])

# A series whose numbers and dates climb together, except for one puzzle served
# under a date from 1934 — the Guardian does this at /cryptic/1183, which is
# Quiptic 1,183 wearing a cryptic's URL.
for n in range(200, 207):
    when = base + (n - 200) * 7 * DAY
    if n == 203:
        when = int(datetime(1934, 1, 18, tzinfo=timezone.utc).timestamp() * 1000)
    write("quiptic", n, when, [
        entry("1-across", 1, "across", 0, 0, 4, "Plain (4)", "EASY")])
PY

echo "a clean file is not touched, and the run says so"
before=$(cksum < "$work/puzzles/cryptic-100.js")
out=$(one cryptic-100 --apply)
absent "$out" "cryptic-100:" "the control puzzle is not reported"
same "byte-identical after a repair run" \
  "$(cksum < "$work/puzzles/cryptic-100.js")" "$before"

echo "an accented or mixed-case solution is normalised to what the cells hold"
out=$(one cryptic-101)
check "$out" "cryptic-101: 3 solution(s) normalised" "all three are seen"
check "$out" "eVEREST→EVEREST" "case"
check "$out" "ACORUÑA→ACORUNA" "accent"
check "$out" "office→OFFICE" "a solution in lower case throughout"
check "$(cat "$work/puzzles/cryptic-101.js")" '"solution": "eVEREST"' \
  "a dry run wrote nothing"
one cryptic-101 --apply >/dev/null
check "$(cat "$work/puzzles/cryptic-101.js")" '"solution": "ACORUNA"' "written on --apply"
absent "$(one cryptic-101)" "cryptic-101:" "clean on the second run"

echo "one masked light takes the whole puzzle unsolved, as a fetch would"
out=$(one cryptic-102)
check "$out" "cryptic-102" "the puzzle is reported"
check "$out" "2-down T?S?R" "naming the light the paper withheld"
check "$out" "all 2 entries stored unsolved" "and what that costs"
check "$out" "WARNING: cryptic-102: solution masked on" "warned on stderr"
one cryptic-102 --apply >/dev/null
same "the masked light is stored unsolved" \
  "$(grep -c '"solution": null' "$work/puzzles/cryptic-102.js")" "2"
absent "$(grep '"solution"' "$work/puzzles/cryptic-102.js")" "T?S?R" \
  "the mask is gone rather than kept as an answer"
absent "$(one cryptic-102)" "cryptic-102:" "clean on the second run"

echo "lights that disagree about their group are reconciled"
out=$(one cryptic-103)
check "$out" "cryptic-103" "the puzzle is reported"
check "$out" "linked-clue group(s) reconciled" "and why"
one cryptic-103 --apply >/dev/null
same "every member now names the same three lights, in enumeration order" \
  "$(groups puzzles/cryptic-103.js)" \
  '[["13-across", ["3-down", "13-across", "21-across"]], ["21-across", ["3-down", "13-across", "21-across"]], ["3-down", ["3-down", "13-across", "21-across"]]]'
absent "$(one cryptic-103)" "cryptic-103:" "clean on the second run"

echo "a group whose every light counts itself in full is not a linked answer"
out=$(one cryptic-104)
check "$out" "cryptic-104" "the puzzle is reported"
check "$out" "1 false cross-reference(s) dissolved: 5-across + 20-across" \
  "naming the two lights the paper linked"
check "$out" "WARNING: 5-across + 20-across: every light carries a full" \
  "warned on stderr, with the reason"
check "$(groups puzzles/cryptic-104.js)" '"5-across", ["5-across", "20-across"]' \
  "a dry run wrote nothing"
one cryptic-104 --apply >/dev/null
same "both lights go back to being their own answers" \
  "$(groups puzzles/cryptic-104.js)" '[["5-across", null], ["20-across", null]]'
absent "$(one cryptic-104)" "cryptic-104:" "clean on the second run"

echo "a real linked answer is left alone"
before=$(cksum < "$work/puzzles/cryptic-105.js")
out=$(one cryptic-105 --apply)
absent "$out" "cryptic-105" "the whole count on the leading light is not a false link"
same "byte-identical after a repair run" \
  "$(cksum < "$work/puzzles/cryptic-105.js")" "$before"
same "the group survives" "$(groups puzzles/cryptic-105.js)" \
  '[["1-across", ["1-across", "5-across"]], ["5-across", ["1-across", "5-across"]]]'

echo "Private Eye prints a count per light, so the rule is off for cyclops"
before=$(cksum < "$work/puzzles/cyclops-401.js")
out=$(one cyclops-401 --apply)
absent "$out" "cyclops-401" "nothing is wrong with the paper's own file"
absent "$out" "dissolved" "and none of its five per-light groups is dissolved"
same "byte-identical after a repair run" \
  "$(cksum < "$work/puzzles/cyclops-401.js")" "$before"
same "2-down (4-6) and 22-down (6) are still one answer" \
  "$(groups puzzles/cyclops-401.js | python3 -c 'import json,sys; \
     print(json.dumps(dict(json.load(sys.stdin))["22-down"]))')" \
  '["2-down", "22-down"]'

echo "a light that counts itself in full leaves the group it was hung on"
out=$(one cryptic-106)
check "$out" "cryptic-106" "the puzzle is reported"
check "$out" "1 false cross-reference(s) dissolved: 19-down" \
  "naming the stranger and not the answer it was hung on"
check "$out" "WARNING: 19-down: counts its own light in full" \
  "warned on stderr, with the reason"
one cryptic-106 --apply >/dev/null
same "the quotation keeps its three lights and the stranger is free" \
  "$(groups puzzles/cryptic-106.js)" \
  '[["22-down", ["22-down", "23-down", "12-across"]], ["23-down", ["22-down", "23-down", "12-across"]], ["12-across", ["22-down", "23-down", "12-across"]], ["19-down", null]]'
absent "$(one cryptic-106)" "cryptic-106:" "clean on the second run"

echo "a continuation that prints its own cell count is not a false link"
before=$(cksum < "$work/puzzles/cryptic-107.js")
out=$(one cryptic-107 --apply)
absent "$out" "cryptic-107" "\"See 2 (6)\" counts the leg, not the answer"
same "byte-identical after a repair run" \
  "$(cksum < "$work/puzzles/cryptic-107.js")" "$before"
same "IGNATIUS LOYOLA survives whole" "$(groups puzzles/cryptic-107.js)" \
  '[["2-down", ["2-down", "7-down"]], ["7-down", ["2-down", "7-down"]]]'

echo "a group left with no clue in it is four answers, not one"
out=$(one cryptic-108)
check "$out" "1 false cross-reference(s) dissolved: 13-across + 18-down + 16-down + 24-across" \
  "the whole group goes, not just the light that counts itself"
check "$out" "WARNING: 13-across + 18-down + 16-down + 24-across: 13-across counts its own light in full and what is left carries no clue" \
  "warned on stderr, with the reason"
one cryptic-108 --apply >/dev/null
same "all four are their own answers again" "$(groups puzzles/cryptic-108.js)" \
  '[["13-across", null], ["18-down", null], ["16-down", null], ["24-across", null]]'
absent "$(one cryptic-108)" "cryptic-108:" "clean on the second run"

echo "a counted leg is still a leg when the paper's own counts do not add up"
before=$(cksum < "$work/puzzles/cryptic-109.js")
out=$(one cryptic-109 --apply)
absent "$out" "cryptic-109" "\"See 4 (2,6,3)\" is not a light claiming to be an answer"
same "byte-identical after a repair run" \
  "$(cksum < "$work/puzzles/cryptic-109.js")" "$before"
same "all three lights stay in the quotation" "$(groups puzzles/cryptic-109.js)" \
  '[["4-down", ["4-down", "19-down", "8-down"]], ["19-down", ["4-down", "19-down", "8-down"]], ["8-down", ["4-down", "19-down", "8-down"]]]'

echo "a light the paper left out of the group is put back when the counts say so"
out=$(one cryptic-110)
check "$out" "cryptic-110" "the puzzle is reported"
check "$out" "1 linked answer(s) reassembled: 9-across + 10-across" \
  "naming the light that was missing"
check "$out" "WARNING: 9-across: its enumeration counts 10-across" \
  "warned on stderr, with the reason"
same "a dry run wrote nothing" "$(groups puzzles/cryptic-110.js)" \
  '[["9-across", null], ["10-across", null], ["20-down", null]]'
one cryptic-110 --apply >/dev/null
same "TREAD THE BOARDS is one answer, and the light that counts itself is not in it" \
  "$(groups puzzles/cryptic-110.js)" \
  '[["9-across", ["9-across", "10-across"]], ["10-across", ["9-across", "10-across"]], ["20-down", null]]'
absent "$(one cryptic-110)" "cryptic-110:" "clean on the second run"

echo "a light the paper printed no clue for is free, and the counts say whose"
out=$(one cryptic-111)
check "$out" "2 linked answer(s) reassembled: 13-across + 15-across, 17-across + 19-across" \
  "both answers, each taking the unclued light its own count fits"
one cryptic-111 --apply >/dev/null
same "RESERVE RATIOS and RETAIL THERAPY, not crossed over" \
  "$(groups puzzles/cryptic-111.js)" \
  '[["13-across", ["13-across", "15-across"]], ["15-across", ["13-across", "15-across"]], ["17-across", ["17-across", "19-across"]], ["19-across", ["17-across", "19-across"]]]'
absent "$(one cryptic-111)" "cryptic-111:" "clean on the second run"

echo "two readings that both add up mean the data does not say, so nothing is written"
before=$(cksum < "$work/puzzles/cryptic-112.js")
out=$(one cryptic-112 --apply)
absent "$out" "cryptic-112" "an ambiguous reconstruction is not a repair"
same "byte-identical after a repair run" \
  "$(cksum < "$work/puzzles/cryptic-112.js")" "$before"
same "all four lights are left as published" "$(groups puzzles/cryptic-112.js)" \
  '[["7-down", null], ["22-down", null], ["8-down", null], ["23-down", null]]'

echo "a light already in somebody else's answer is not taken for this one"
before=$(cksum < "$work/puzzles/cryptic-113.js")
out=$(one cryptic-113 --apply)
absent "$out" "cryptic-113" "the enumeration is left unsatisfied instead"
same "byte-identical after a repair run" \
  "$(cksum < "$work/puzzles/cryptic-113.js")" "$before"
same "24-across stays where the paper put it" "$(groups puzzles/cryptic-113.js)" \
  '[["16-down", null], ["13-across", null], ["1-down", null], ["18-down", ["18-down", "24-across"]], ["24-across", ["18-down", "24-across"]]]'

echo "a group naming a light the puzzle does not have is dropped, not shortened"
out=$(one cryptic-114)
check "$out" "cryptic-114" "the puzzle is reported"
check "$out" "3 one-sided group(s) dropped" "all three lights that named 18-down"
check "$out" "WARNING: 17-across: 18-down is in no group with it" \
  "warned on stderr, naming the light that is not there"
check "$out" "is an answer with a light missing — group dropped" "and why the whole group goes"
same "a dry run wrote nothing" "$(groups puzzles/cryptic-114.js)" \
  '[["13-across", ["13-across", "18-down", "20-across"]], ["17-across", ["17-across", "18-down", "20-across"]], ["18-across", ["18-across", "20-across", "31-across"]], ["20-across", ["13-across", "18-down", "20-across"]], ["31-across", ["18-across", "20-across", "31-across"]]]'
one cryptic-114 --apply >/dev/null
same "no group names 18-down, and NEW WORLD ORDER is untouched behind a light that names three leaders" \
  "$(groups puzzles/cryptic-114.js)" \
  '[["13-across", ["13-across", "20-across"]], ["17-across", null], ["18-across", ["18-across", "20-across", "31-across"]], ["20-across", ["13-across", "20-across"]], ["31-across", ["18-across", "20-across", "31-across"]]]'
absent "$(one cryptic-114)" "cryptic-114:" "clean on the second run"

echo "a group naming a light that stores an answer of its own is dropped"
out=$(one cryptic-115)
check "$out" "cryptic-115: 2 one-sided group(s) dropped: 6-down 6-down + 20-across, 8-down 8-down + 17-across" \
  "both claims, and neither of the lights they were made on"
check "$out" "WARNING: 6-down: 20-across is in no group with it" \
  "warned on stderr, naming the light that stores another answer"
one cryptic-115 --apply >/dev/null
same "ASIA MINOR and DRUM MAJOR go, MAJOR AND MINOR stays whole" \
  "$(groups puzzles/cryptic-115.js)" \
  '[["6-down", null], ["8-down", null], ["17-across", ["17-across", "19-across", "20-across"]], ["19-across", ["17-across", "19-across", "20-across"]], ["20-across", ["17-across", "19-across", "20-across"]]]'
absent "$(one cryptic-115)" "cryptic-115:" "clean on the second run"

echo "a date its own neighbours contradict is reported and never guessed at"
out=$(run)
check "$out" "quiptic-203: dated 1934-01-18" "the stored date"
check "$out" "mis-filed, re-fetch it" "what to do about it"
check "$out" "1 mis-filed date(s)" "counted apart from the repairs"
absent "$out" "quiptic-202" "a puzzle in line with its neighbours is not flagged"
before=$(cksum < "$work/puzzles/quiptic-203.js")
run --series quiptic --apply >/dev/null
same "left exactly as it was, because the real date is not here to be had" \
  "$(cksum < "$work/puzzles/quiptic-203.js")" "$before"

echo "the selection flags keep a run off everything else"
out=$(run --series quiptic)
absent "$out" "cryptic-" "--series quiptic examines no cryptics"
check "$out" "7 file(s) examined" "and all seven quiptics"
out=$(run --series quiptic --from 204)
check "$out" "3 file(s) examined" "--from cuts the range"
absent "$out" "quiptic-203" "a file outside the range is not reported"
out=$(run --series quiptic --from 203 --to 203)
check "$out" "quiptic-203: dated 1934-01-18" \
  "but its neighbours are still read, or one file could not be judged at all"
out=$(run --series nosuchseries 2>&1)
check "$out" "no series 'nosuchseries'" "a misspelt series is an error, not an empty run"
out=$(run --apply --dry-run 2>&1)
check "$out" "--apply and --dry-run say opposite things" "and so is asking for both"

[ "$fails" = 0 ] && echo "repair_fetched: all checks passed" || echo "repair_fetched: $fails FAILED"
exit $((fails > 0))
