#!/bin/bash
# Does tools/fetch_times_feed.py turn the Times player's data.json into a
# puzzle, and refuse one whose clues do not cover the grid?
#
#     bash tools/test_fetch_times_feed.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

convert() {  # convert <drop a clue: 0|1> -> one line per entry, or the refusal
  REPO="$REPO" python3 - "$1" <<'PY'
import datetime, os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "tools"))
import fetch_times_feed as f
# 3x3 with a block in the middle; the solution string's space is the block,
# so the lights are the four edges: 1 across, 1 down, 2 down, 3 across.
data = {"headline": "Times Quick Cryptic (Number 01)", "copy": {
    "title": "Times Quick Cryptic (Number 01)", "id": "100", "setter": "Des",
    "crosswordtype": "Quick Cryptic", "gridsize": {"cols": "3", "rows": "3"},
    "settings": {"solution": "CATO EWED"},
    "clues": [
        {"title": "Across", "clues": [
            {"number": "1", "clue": "Pet", "format": "3", "answer": "CAT"},
            {"number": "3", "clue": "Married", "format": "1-2", "answer": "W-ED"}]},
        {"title": "Down", "clues": [
            {"number": "1", "clue": "Dairy animal", "format": "3", "answer": "COW"},
            {"number": "2", "clue": "Digit", "format": "3", "answer": "TED"}]}]}}
if sys.argv[1] == "1":
    data["copy"]["clues"][1]["clues"].pop()
p, why = f.convert(data, datetime.date(2014, 3, 10))
if why:
    print(why)
else:
    print(p["id"], p["date"], p["setter"], p["source"]["url"])
    for e in p["entries"]:
        print(e["number"], e["direction"], e["position"]["x"], e["position"]["y"],
              e["clue"]["text"], e["clue"]["enumeration"], e.get("solution"))
PY
}

check "data.json becomes a puzzle: lights placed, enumerations kept, answers as letters" \
"timesquick-1 2014-03-10 Des https://feeds.thetimes.co.uk/puzzles/crossword/20140310/100/
1 across 0 0 Pet 3 CAT
3 across 0 2 Married 1-2 WED
1 down 0 0 Dairy animal 3 COW
2 down 2 0 Digit 3 TED" "$(convert 0)"
check "a light with no clue is refused" "the clues do not cover the grid's lights" "$(convert 1)"

[ "$fails" -eq 0 ] && echo "all checks passed" || { echo "$fails check(s) failed"; exit 1; }
