#!/bin/bash
# Does a puzzle's commit carry its own rows of fetch_puzzle.py and no sibling's?
#
#     bash tools/test_own_rows.sh
#
# stage_puzzle and discard_puzzle are read out of tools/prereset_backfill.sh and
# run in a scratch git tree holding this repo's tools and two puzzles, both in
# flight at once as the pool runs them: each prints a corrected clue into its
# file and files rows into the one shared fetch_puzzle.py. A commits, B is
# discarded. Then:
#   - A's commit holds A's rows, and none of B's;
#   - B's rows are still in the tree after A's commit, for B's own;
#   - after B's discard the tree is clean, so nothing of B's reaches master;
#   - every SOURCE_CLUE_WRONG row committed names a clue its file shows, which
#     is what tools/test_source_answer_wrong.sh holds CI to;
#   - a puzzle with no rows commits fetch_puzzle.py as HEAD has it.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

tree="$(mktemp -d)"
trap 'rm -rf "$tree"' EXIT
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$tree/tools" "$tree/puzzles/times/1984"
cp "$REPO"/tools/*.py "$tree/tools/"
ln -s "$REPO/tools/data" "$tree/tools/data"
A=times-16348 B=times-16347
cp "$REPO/puzzles/times/1984/$A.json" "$REPO/puzzles/times/1984/$B.json" "$tree/puzzles/times/1984/"
cd "$tree" || exit 1
git init -q && git add -A && git -c user.name=t -c user.email=t@t commit -qm base
commit() { git -c user.name=t -c user.email=t@t commit -qm "$1"; }

eval "$(sed -n '/^puzzle_spec() {/p' "$REPO/tools/prereset_backfill.sh")"
eval "$(sed -n '/^discard_puzzle() {/,/^}/p' "$REPO/tools/prereset_backfill.sh")"
eval "$(sed -n '/^stage_puzzle() {/,/^}/p' "$REPO/tools/prereset_backfill.sh")"
ALERTS="$tree/alerts"
# shellcheck disable=SC2329  # called by the eval'd discard_puzzle
alert() { echo "$*" >>"$ALERTS"; }

# Both runs: A first, then B, each filing at the top of the table the way
# apply_annotations' callers do, so B's rows sit above A's. B also files a
# SOURCE_ANSWER_WRONG row, which must stay out of A's commit just the same.
PYTHONPATH=tools python3 - "$A" "$B" <<'PY'
import json, sys
from pathlib import Path
import fetch_puzzle as fetcher
from groups import entry_id

src = Path(fetcher.__file__)
for pid in sys.argv[1:]:
    path = fetcher.puzzle_paths.find(pid)
    puzzle = json.loads(path.read_text())
    held = {e for (p, e) in fetcher.SOURCE_CLUE_WRONG if p == pid}
    entry = next(e for e in puzzle["entries"] if entry_id(e) not in held)
    served = entry["clue"]["text"]
    entry["clue"]["text"] = "Mended " + served
    path.write_text(json.dumps(puzzle, indent=2) + "\n")
    text = src.read_text()
    anchor = "SOURCE_CLUE_WRONG = {\n"
    text = text.replace(anchor, anchor +
        f'    # filed by the simulated run for {pid}\n'
        f'    ("{pid}", "{entry_id(entry)}"): (\n'
        f'        {served!r},\n        {entry["clue"]["text"]!r},\n'
        '        "OCR misread: simulated by test_own_rows"),\n', 1)
    if pid == sys.argv[2]:
        anchor = "SOURCE_ANSWER_WRONG = {\n"
        text = text.replace(anchor, anchor +
            f'    ("{pid}", "99-across"): ("SERVED", "PRINTED", "simulated"),\n', 1)
    src.write_text(text)
PY

stage_puzzle "$A" && commit "Annotate $A"
shown() { git show "$1" -- tools/fetch_puzzle.py | grep -c "^+.*(\"$2\","; }
check "A's commit carries A's row" "1" "$(shown HEAD "$A")"
check "A's commit carries none of B's rows" "0" "$(shown HEAD "$B")"
check "A's commit carries A's comment" "1" \
  "$(git show HEAD -- tools/fetch_puzzle.py | grep -c "^+    # filed by the simulated run for $A")"
check "A's commit carries A's puzzle" "puzzles/times/1984/$A.json" \
  "$(git show --name-only --format= HEAD -- puzzles)"
check "B's rows are still in the tree for B's commit" "2" \
  "$(git diff -U0 -- tools/fetch_puzzle.py | grep -c "^+.*(\"$B\",")"
check "and nothing else is" "6" "$(git diff -U0 -- tools/fetch_puzzle.py | grep -c "^+[^+]")"

discard_puzzle "$B"
check "after B's discard the tree is clean" "" "$(git status --porcelain)"
check "no alert" "" "$(cat "$ALERTS" 2>/dev/null)"

bad=$(PYTHONPATH=tools python3 - <<'PY'
import fetch_puzzle as fetcher
from groups import entry_id

bad = []
for (pid, eid), (_served, printed, _why) in fetcher.SOURCE_CLUE_WRONG.items():
    path = fetcher.puzzle_paths.find(pid)
    if path is None:
        continue
    shown = {entry_id(e): e["clue"]["text"] for e in fetcher.read_puzzle_file(path)["entries"]}
    if fetcher.clue_words(shown.get(eid)) != fetcher.clue_words(printed):
        bad.append(f"{pid} {eid}")
print(" ".join(bad) or "none")
PY
)
check "every committed clue row holds on disk" "none" "$bad"

# A puzzle with no rows, committed while a sibling's rows sit in the tree.
python3 - "$B" <<'PY'
import sys
from pathlib import Path
src = Path("tools/fetch_puzzle.py")
anchor = "SOURCE_CLUE_WRONG = {\n"
src.write_text(src.read_text().replace(anchor, anchor +
    f'    ("{sys.argv[1]}", "99-across"): ("Served", "Printed", "simulated"),\n', 1))
PY
printf '\n' >>"puzzles/times/1984/$A.json"
stage_puzzle "$A" && commit "Reannotate $A"
check "a puzzle with no rows commits fetch_puzzle.py as HEAD had it" "" \
  "$(git show --name-only --format= HEAD -- tools/fetch_puzzle.py)"
check "and the sibling's row stays in the tree" "1" \
  "$(git diff -U0 -- tools/fetch_puzzle.py | grep -c "^+.*(\"$B\",")"

[ "$fails" = 0 ] && echo "own_rows: all checks passed" || echo "own_rows: $fails FAILED"
exit $((fails > 0))
