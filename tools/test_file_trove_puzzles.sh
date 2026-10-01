#!/bin/bash
# Does tools/file_trove_puzzles.py read a Trove scan's grid, lay the OCR's
# clues on it, file only what agrees, and leave everything alone on a rerun?
#
#     bash tools/test_file_trove_puzzles.sh
#
# The fixtures are three real Canberra Times articles as tools/fetch_trove.py
# caches them (tools/fixtures/trove/<article id>/): the Times cryptic of
# 1 June 1972, the next day's SOLUTION grid, and the cryptic of 13 June 1972,
# whose OCR printed 1-across's "(5, 5)" as "(5, J)". Nothing reads the corpus
# but the held Guardian clues, and nothing is written outside a temp dir.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
FIX="$REPO/tools/fixtures/trove"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# The grid off the scan, cell for cell as the picture prints it.
got=$(cd "$REPO/tools" && python3 -c "
import trove_grid
g, why = trove_grid.read_grid('$FIX/102024288/grid.jpg')
print(' '.join(g) if g else why, trove_grid.symmetric(g) if g else '')")
check "grid read off the 1 June 1972 scan" ".....#......... .#.#.#.#.#.#.#. .........#..... .#.#.#.#.#.#.#. .....#......... .###.#.#.###.## .......#....... .#.#.#####.#.#. .......#....... ##.###.#.#.###. .........#..... .#.#.#.#.#.#.#. .....#......... .#.#.#.#.#.#.#. .........#..... True" "$got"

# A first run files the cryptic, skips the solution, holds back the one
# whose count disagrees with its picture.
cp -r "$FIX" "$tmp/cache"
mkdir "$tmp/out"
first=$(cd "$REPO" && python3 tools/file_trove_puzzles.py --cache "$tmp/cache" --out "$tmp/out")
check "first run: one filed" "1" "$(grep -c '  1  filed' <<<"$first")"
check "first run: the solution grid skipped" "1" "$(grep -c 'skipped: a solution grid' <<<"$first")"
check "first run: the disagreeing count held back" "1" "$(grep -c 'pending: no grid' <<<"$first")"

got=$(python3 -c "
import json
p = json.load(open('$tmp/out/canberra-720601.json'))
e = {(x['number'], x['direction']): x for x in p['entries']}
print(p['date'], len(p['entries']), p['source']['gridOrigin'], p['source']['retrievedFrom'],
      p['source']['url'], p['solutions']['origin'],
      e[(12, 'across')]['clue']['text'], '|', e[(3, 'down')]['clue']['enumeration'],
      e[(3, 'down')]['clue']['separators'], any('solution' in x for x in p['entries']))")
check "the filed puzzle" "1972-06-01 32 published newspaper https://trove.nla.gov.au/newspaper/article/102024288 unsolved Gallery of church architecture | 4,5 [{'at': 4, 'mark': ','}] False" "$got"

got=$(python3 -c "
import json
for line in open('$tmp/cache/filed.jsonl'):
    r = json.loads(line)
    if r['article'] == '102026080':
        print(r['imageDisagrees'])")
check "the disagreement is named, not forced" "1-across: the enumeration reads as ['5,1'], the grid holds 10 letters" "$got"

# A second run reads nothing new and writes nothing.
before=$(stat -c %Y "$tmp/out/canberra-720601.json" 2>/dev/null || stat -f %m "$tmp/out/canberra-720601.json")
sleep 1
second=$(cd "$REPO" && python3 tools/file_trove_puzzles.py --cache "$tmp/cache" --out "$tmp/out")
after=$(stat -c %Y "$tmp/out/canberra-720601.json" 2>/dev/null || stat -f %m "$tmp/out/canberra-720601.json")
check "second run: same verdicts" "$first" "$second"
check "second run: the filed puzzle untouched" "$before" "$after"

# No picture at all: the clues alone still file it, the grid rebuilt from
# them and marked so; the rebuild is the grid the picture shows.
mkdir -p "$tmp/nogrid/102024288" "$tmp/out2"
cp "$FIX/102024288/meta.json" "$FIX/102024288/ocr.txt" "$tmp/nogrid/102024288/"
(cd "$REPO" && python3 tools/file_trove_puzzles.py --cache "$tmp/nogrid" --out "$tmp/out2" >/dev/null)
got=$(python3 -c "
import json
a = json.load(open('$tmp/out/canberra-720601.json'))
b = json.load(open('$tmp/out2/canberra-720601.json'))
cells = lambda p: sorted((e['number'], e['direction'], e['position']['x'], e['position']['y'], e['length']) for e in p['entries'])
print(b['source']['gridOrigin'], cells(a) == cells(b))")
check "no grid image: filed from the clues, rebuilt" "reconstructed True" "$got"

# Slips are repaired only where the light decides: "(S)" over a five is 5,
# over an eight 8, and over a six it is a disagreement.
got=$(cd "$REPO/tools" && python3 -c "
import file_trove_puzzles as F
grid = ['.....', '.#.#.', '.....', '.#.#.', '.....']
def laid(a1):
    across, _ = F.clues(f'1 One (S). 3 Two (5). 5 Three (5).')
    down, _ = F.clues('1 Four (5). 2 Five (5). 4 Six (5).')
    across[0]['enums'] = F.enum_readings(a1)
    return F.match({'across': across, 'down': down}, grid)
print(laid('S')[0]['1-across'][1], laid('I0')[0], laid('6')[1])")
check "slips decided by the light" "5 None 1-across: the enumeration reads as ['6'], the grid holds 5 letters" "$got"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
