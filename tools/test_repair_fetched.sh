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
