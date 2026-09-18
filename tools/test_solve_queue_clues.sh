#!/bin/bash
# Does the cold-solve queue skip a grid there is nothing to read in?
#
# A model cannot solve a puzzle whose clues the paper printed blank, so handing
# it one costs a full run and ends in an alert blaming the solver for a hole in
# the data. The index says how much clue text each puzzle actually has, and the
# selection block in tools/daily_update.sh is read OUT of that file by its own
# first and last lines and driven against a made-up index here, rather than
# copied — a queue rule asserted against a copy is a rule about the copy.
#
#     bash tools/test_solve_queue_clues.sh
#
# Three things, and each fails on its own: the index carries the counts, the
# counts agree with the puzzle files, and the queue drops what it cannot read
# while every other reason a puzzle leaves the queue still works.
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }

pick=$(awk '/^unsolved=\$\(python3 /,/^\)$/' tools/daily_update.sh)
[ -n "$pick" ] ||
  { echo "FAIL: the solve-queue block is no longer where this test reads it from"; exit 1; }

echo "the index counts the clues a solver can read, per puzzle"
# Straight at the function the index is built from, so this still says what the
# field means on a day the corpus holds no puzzle with a gap in it.
out=$(python3 - <<'EOF'
import sys
sys.path.insert(0, "tools")
from fetch_puzzle import clue_coverage
p = {"entries": [{"clue": "Vehicle for a comeback (3)"},    # readable
                 {"clue": " (8)"},                          # printed blank
                 {"clue": "Nonsense the paper garbled (5)", "clueCorrupt": True},
                 {"clue": "␣␣ 9 (5)"}]}           # bare cross-reference
c = clue_coverage(p)
print(f"{c['present']}/{c['total']}")
EOF
) || out="raised: $out"
check "a blank clue and a corrupt one are unreadable, a cross-reference is not" \
  "$out" "2/4"

echo "and every puzzle on disk is counted the same way in puzzles/index.json"
# Generated and untracked, so it is built before it is read: CI is a fresh clone.
python3 tools/fetch_puzzle.py --reindex >/dev/null
out=$(python3 - <<'EOF'
import json, re, sys
sys.path.insert(0, "tools")
from fetch_puzzle import puzzle_files, read_puzzle_file


# Counted here rather than imported: a test that asks the writer what the writer
# wrote asserts nothing. Readable is anything left once the enumeration is off —
# "␣␣ 9 (5)" is a whole clue, cryptic-30059 14-down, and so is ")" on its own,
# the whole of CLOSE BRACKETS — and not marked corrupt.
def readable(e):
    return (bool(re.sub(r"\([\d,\-. ]*\)", "", e["clue"]).strip())
            and not e.get("clueCorrupt"))


want = {}
for path in puzzle_files():
    p = read_puzzle_file(path)
    present, total = sum(1 for e in p["entries"] if readable(e)), len(p["entries"])
    if present < total:
        want[p["id"]] = {"present": present, "total": total}
got = {p["id"]: p["clues"] for p in json.load(open("puzzles/index.json"))["puzzles"]
       if "clues" in p}
if got == want:
    print(f"agreed on {len(want)}")
else:
    missing = {k: v for k, v in want.items() if got.get(k) != v}
    extra = {k: v for k, v in got.items() if k not in want}
    print("index disagrees — wrong or absent: "
          f"{dict(list(missing.items())[:4])} spurious: {dict(list(extra.items())[:4])}")
EOF
)
check "the counts in the index are the counts in the files" \
  "$(printf '%s' "$out" | grep -c '^index disagrees')" "0"

echo "the queue takes the readable grids and leaves the rest"
# A sandbox index of its own, so nothing here depends on which puzzles the
# corpus happens to hold tonight, and a ledger of its own: the real
# .solve_attempts.json is live state this test must not read or rewrite.
sand=$(mktemp -d)
trap 'rm -rf "$sand"' EXIT
ln -s "$REPO/tools" "$sand/tools"
mkdir -p "$sand/puzzles"
python3 - "$sand/puzzles/index.json" <<'EOF'
import json, sys
# id, date, hasSolutions, clues — newest first, so a queue that ignored the clue
# counts would hand back the blank one at the head of the list.
rows = [("ct-blank", 900, False, {"present": 0, "total": 28}),
        ("ct-half", 800, False, {"present": 14, "total": 28}),
        ("ct-most", 700, False, {"present": 15, "total": 28}),
        ("ct-gap", 600, False, {"present": 27, "total": 28}),
        ("ct-whole", 500, False, None),
        ("ct-tried", 400, False, None),
        ("ct-answered", 300, True, None)]
json.dump({"puzzles": [
    {"id": i, "date": d, "hasSolutions": s, **({"clues": c} if c else {})}
    for i, d, s, c in rows]}, open(sys.argv[1], "w"))
EOF
echo '{"ct-tried": 1, "ct-answered": 1}' > "$sand/attempts.json"
run() (  # the block itself against the sandbox; the skip note goes to $sand/note
  cd "$sand" && SOLVE_MAX=${1:-5} SOLVE_ATTEMPTS_MAX=1 REPO="$sand" \
    CT_MAIN_CHECKOUT="$sand" SOLVE_ATTEMPTS_FILE="$sand/attempts.json" \
    eval "$pick" 2>"$sand/note" && printf '%s\n' "$unsolved"
)
check "the blank grid and the half-blank one are not handed to a model" \
  "$(run)" "ct-most ct-gap ct-whole"
check "and the log says why, by name and by count" \
  "$(grep -c 'ct-blank (0/28 clues), ct-half (14/28 clues)' "$sand/note")" "1"
check "a puzzle missing one clue of 28 is still a solvable grid" \
  "$(grep -c 'ct-gap\|ct-most\|ct-whole' "$sand/note")" "0"
check "the one-attempt cap still holds" "$(run | grep -c ct-tried)" "0"
check "a puzzle with answers is still out of the queue" "$(run | grep -c ct-answered)" "0"
check "SOLVE_MAX still bounds the night" "$(run 2)" "ct-most ct-gap"
check "and a stale count against a puzzle that has answers now is still forgotten" \
  "$(python3 -c "import json; print(sorted(json.load(open('$sand/attempts.json'))))")" \
  "['ct-tried']"

[ "$fails" = 0 ] && echo "solve queue clues: all checks passed" || echo "solve queue clues: $fails FAILED"
exit $((fails > 0))
