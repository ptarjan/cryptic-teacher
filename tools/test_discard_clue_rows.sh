#!/bin/bash
# Does discarding a run take its SOURCE_CLUE_WRONG rows with it?
#
#     bash tools/test_discard_clue_rows.sh
#
# discard_puzzle is read out of tools/prereset_backfill.sh and run in a scratch
# git tree holding this repo's tools and one puzzle. A run is simulated: it
# prints a corrected clue into the puzzle and files the row, and another files
# a row whose served text the file never held. After the discard:
#   - the puzzle file is back as committed;
#   - every SOURCE_CLUE_WRONG row for it names a clue the file shows, which is
#     what tools/test_source_answer_wrong.sh holds CI to;
#   - the rows committed with its earlier annotation are kept;
#   - the rest of fetch_puzzle.py is byte for byte as it was;
#   - a puzzle the run wrote new is removed, with its rows.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

tree="$(mktemp -d)"
trap 'rm -rf "$tree"' EXIT
mkdir -p "$tree/tools" "$tree/puzzles/times/1984"
cp "$REPO"/tools/*.py "$tree/tools/"
ln -s "$REPO/tools/data" "$tree/tools/data"
PID=times-16348
cp "$REPO/puzzles/times/1984/$PID.json" "$tree/puzzles/times/1984/"
cd "$tree" || exit 1
git init -q && git add -A && git -c user.name=t -c user.email=t@t commit -qm base

eval "$(sed -n '/^puzzle_spec() {/p' "$REPO/tools/prereset_backfill.sh")"
eval "$(sed -n '/^discard_puzzle() {/,/^}/p' "$REPO/tools/prereset_backfill.sh")"
ALERTS="$tree/alerts"
alert() { echo "$*" >>"$ALERTS"; }

# The run: a printed clue in the file plus its row, a row whose served text the
# file never held, and a new puzzle with a row of its own.
PYTHONPATH=tools python3 - "$PID" <<'PY'
import json, sys
from pathlib import Path
import fetch_puzzle as fetcher
from groups import entry_id

pid = sys.argv[1]
path = fetcher.puzzle_paths.find(pid)
puzzle = json.loads(path.read_text())
held = {e for (p, e) in fetcher.SOURCE_CLUE_WRONG if p == pid}
fresh = [e for e in puzzle["entries"] if entry_id(e) not in held][:2]
printed, mismatched = fresh
printed["clue"]["text"] = "Mended " + printed["clue"]["text"]
path.write_text(json.dumps(puzzle, indent=2) + "\n")
new = Path("puzzles/times/1984/times-99999.json")
new.write_text(path.read_text().replace(pid, "times-99999"))

src = Path(fetcher.__file__)
rows = (f'    ("{pid}", "{entry_id(printed)}"): (\n'
        f'        {printed["clue"]["text"][7:]!r},\n'
        f'        {printed["clue"]["text"]!r},\n'
        '        "OCR misread: simulated by test_discard_clue_rows"),\n'
        f'    ("{pid}", "{entry_id(mismatched)}"): (\n'
        '        "A served text the file never held",\n'
        '        "A printed text the file never held",\n'
        '        "OCR misread: simulated by test_discard_clue_rows"),\n'
        '    ("times-99999", "1-across"): (\n'
        '        "Served", "Printed",\n'
        '        "OCR misread: simulated by test_discard_clue_rows"),\n')
text = src.read_text()
anchor = "SOURCE_CLUE_WRONG = {\n"
src.write_text(text.replace(anchor, anchor + rows, 1))
PY
check "the simulated run filed three rows" "3" \
  "$(git diff -U0 -- tools/fetch_puzzle.py | grep -c '^+    ("times-')"

discard_puzzle "$PID"
discard_puzzle times-99999

check "the puzzle file is back as committed" "" "$(git status --porcelain -- puzzles)"
check "fetch_puzzle.py is byte for byte as committed" "" "$(git diff --stat -- tools/fetch_puzzle.py)"
check "no alert" "" "$(cat "$ALERTS" 2>/dev/null)"

out=$(PYTHONPATH=tools python3 - "$PID" <<'PY'
import sys
import fetch_puzzle as fetcher
from groups import entry_id

pid = sys.argv[1]
shown = {entry_id(e): e["clue"]["text"]
         for e in fetcher.read_puzzle_file(fetcher.puzzle_paths.find(pid))["entries"]}
rows = {e: printed for (p, e), (_s, printed, _w) in fetcher.SOURCE_CLUE_WRONG.items() if p == pid}
bad = [e for e, printed in rows.items()
       if fetcher.clue_words(shown.get(e)) != fetcher.clue_words(printed)]
print("KEPT", len(rows))
print("BAD", " ".join(bad) or "none")
print("NEW", sum(p == "times-99999" for p, _ in fetcher.SOURCE_CLUE_WRONG))
PY
)
field() { awk -v k="$1" '$1==k {$1=""; sub(/^ /, ""); print}' <<<"$out"; }
check "every row left for the puzzle names a clue its file shows" "none" "$(field BAD)"
check "the rows committed with its annotation are kept" \
  "$(grep -c "(\"$PID\"," "$REPO/tools/fetch_puzzle.py")" "$(field KEPT)"
check "a new puzzle's rows go with it" "0" "$(field NEW)"

# A row the run filed and a sibling already committed is dropped all the same:
# the table must agree with the file, whatever HEAD holds.
python3 - <<'PY'
from pathlib import Path
src = Path("tools/fetch_puzzle.py")
anchor = "SOURCE_CLUE_WRONG = {\n"
src.write_text(src.read_text().replace(anchor, anchor +
    '    ("times-16348", "1-across"): (\n        "Served",\n        "Printed",\n'
    '        "OCR misread: simulated by test_discard_clue_rows"),\n', 1))
PY
git -c user.name=t -c user.email=t@t commit -qam sibling
discard_puzzle "$PID"
check "a row a sibling already committed is dropped too" "0" \
  "$(grep -c '("times-16348", "1-across")' tools/fetch_puzzle.py)"

[ "$fails" = 0 ] && echo "discard_clue_rows: all checks passed" \
  || echo "discard_clue_rows: $fails FAILED"
exit $((fails > 0))
