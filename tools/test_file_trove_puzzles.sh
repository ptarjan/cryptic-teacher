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
# The desktop VLM is never asked here.
export VLM_READER_URL=
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
# Our readers' text of the 1 June 1972 article's clue zones, as
# file_trove_puzzles.page_readings caches it: the vote's other voters.
cp -r "$REPO/tools/fixtures/trove-clues" "$tmp/cache-clues"
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
cp -r "$REPO/tools/fixtures/trove-clues" "$tmp/nogrid-clues"
(cd "$REPO" && python3 tools/file_trove_puzzles.py --cache "$tmp/nogrid" --out "$tmp/out2" >/dev/null)
got=$(python3 -c "
import json
a = json.load(open('$tmp/out/canberra-720601.json'))
b = json.load(open('$tmp/out2/canberra-720601.json'))
cells = lambda p: sorted((e['number'], e['direction'], e['position']['x'], e['position']['y'], e['length']) for e in p['entries'])
print(b['source']['gridOrigin'], cells(a) == cells(b))")
check "no grid image: filed from the clues, rebuilt" "reconstructed True" "$got"

# A lost clue repaired from RapidOCR's reading of the clue columns: in the
# 14 July 1967 cryptic Trove read 5-down's "(6, 4)" as "(6,\n4> , ," and
# glued 6-down onto it. The reading (tools/fixtures/trove-repair/cache-clues,
# cached as tools/trove_clue_ocr.py leaves it) gives 6-down back and 5-down
# its length, so the clues agree with the picture and the puzzle files;
# without the reading it waits.
cp -r "$REPO/tools/fixtures/trove-repair" "$tmp/repair"
mkdir "$tmp/out3"
(cd "$REPO" && python3 tools/file_trove_puzzles.py --cache "$tmp/repair/cache" --out "$tmp/out3" >/dev/null)
got=$(python3 -c "
import json
p = json.load(open('$tmp/out3/canberra-670714.json'))
e = {(x['number'], x['direction']): x['clue'] for x in p['entries']}
print(p['source']['gridOrigin'], e[(5, 'down')]['text'], '|', e[(5, 'down')].get('enumeration'),
      '|', e[(6, 'down')]['text'], e[(6, 'down')]['enumeration'])")
check "a lost clue repaired from the clue columns, its words voted" "published Under which possibly neither Irving Berlin nor Edward German ever sat | None | Rumour that's hardly about the bishop. 11" "$got"
rm -r "$tmp/repair/cache-clues" "$tmp/repair/cache/filed.jsonl"
got=$(cd "$REPO" && python3 tools/file_trove_puzzles.py --cache "$tmp/repair/cache" --out "$tmp/out3" | grep -c 'pending: no grid')
check "without the clue columns it waits" "1" "$got"

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

# Without a picture the rebuild takes what the OCR leaves uncertain as
# unknown -- a number read two ways, a count read two ways, a linked clue's
# lights -- and the numbering still pins the grid down.
got=$(cd "$REPO/tools" && python3 -c "
import file_trove_puzzles as F
F.SIDE = 5
across, _ = F.clues('1 One (5). 4 Two (5). 5 Three (5).')
down, _ = F.clues('1 Four (5). 2 Five (5). 3 Six (5).')
across[1]['tokens'][0] = {4, 9}
down[0]['enums'] = {'5', '6'}
print(F.rebuild({'across': across, 'down': down}))
# Several grids the clues allow: the scan picks the nearest, when clearly so.
a, b = ('.....', '.#.#.'), ('.....', '#...#')
print(F.closest(('.....', '.#.##'))([a, b]) == a, F.closest(('.....', '##.##'))([a, b]),
      F.closest(None))")
check "uncertain numbers and counts go in unknown; the grid still rebuilds" \
  "(['.....', '.#.#.', '.....', '.#.#.', '.....'], None)
True None None" "$got"
# The solution grid's pairing and numbering need no OCR engine.
got=$(cd "$REPO/tools" && python3 -c "
import datetime, trove_solution_ocr as O
sat = datetime.date(1970, 12, 19)
print(O.lag_allowed('the crossword published today', 0, sat),
      O.lag_allowed('the crossword published today', 1, sat),
      O.lag_allowed('published on , Saturday,', 2, sat),
      O.lag_allowed('published on , Saturday,', 1, sat + datetime.timedelta(1)))
print(sorted(O.lights(['...', '.#.', '...'])))")
check "solution pairing and light numbering" "True False True False
[(1, 'across'), (1, 'down'), (2, 'down'), (3, 'across')]" "$got"

# An accepted answer must be a word: -d, -r and -st inflect only a lemma
# ending in e, and -es only one ending in a sibilant or o, so a misread
# letter that lands on such an ending stays unknown (WOOER read as WOOFR).
got=$(cd "$REPO/tools" && python3 -c "
import trove_solution_ocr as O
print(*[O.known(w) for w in ('WOOFR', 'WOOFST', 'WOOFD', 'WOOFES', 'RUGE')],
      *[O.known(w) for w in ('WOOER', 'WISER', 'WISEST', 'BAKED', 'BOXES', 'WOOFED')])")
check "a misread on an inflection is no word" "False False False False False True True True True True True" "$got"

# Reading the 2 June 1972 solution against that day's grid: whatever it
# accepts fits its light and is one of the answers a person reads off the
# scan. Skipped where the OCR engine is not installed (CI's test job).
got=$(cd "$REPO/tools" && python3 -c "
import json, trove_solution_ocr as O
if O.available():
    print('skip'); raise SystemExit
p = json.load(open('$REPO/tools/fixtures/trove-solution/canberra-720602.json'))
grid = O.puzzle_grid(p)
acc, st = O.read_answers('$FIX/102024518/grid.jpg', grid)
hand = {(1, 'across'): 'FOOTPAD', (5, 'across'): 'ALMANAC', (9, 'across'): 'INTERESTS',
        (10, 'across'): 'LIGHT', (1, 'down'): 'FRIDAY'}
lts = O.lights(grid)
bad = [k for k, w in acc.items() if len(w) != len(lts[k]) or (k in hand and hand[k] != w)]
print('ok' if not bad and st['sureClashes'] <= st['sureCrossings'] else bad)")
[ "$got" = skip ] && echo "skip solution OCR: rapidocr-onnxruntime not installed" || \
  check "solution OCR accepts only fitting, hand-checked answers" "ok" "$got"

# OCR's made-up words never file. ocr_clues.suspect() names each word no
# setter wrote -- the 30 June 1972 cryptic's "Start trom Hint" and "What
# don't they know7", a capital inside a word, a stray mark -- and passes
# names, abbreviations, counts and the corpus's own coinages. The vote then
# mends a real word misread as another ("ministers arc" where the readings
# have "are") and a word only Trove misspelt.
got=$(cd "$REPO/tools" && python3 -c "
import ocr_clues as O
for t in ('Start trom Hint', \"What don't they know7 God knows\", 'RcbufT bacK ofTer',
          \". . cloudy skirts Wi'.h ethereal\", 'Steps for Plaved'):
    print([w for w, _ in O.suspect(t)])
print(O.suspect('Miss Jenkyns of the TUC rang 17ac on the 1st, about 10cc of rosé, iPad and EastEnders'))
print(O.suspect('Murat here', {'murat'}), O.suspect('A counterthrust; ceasefires overtakin\\' nighttime'))
others = [O.marked('# Cabinet ministers are - naturally not #', True)] * 2
print(O.agree('Cabinet ministers arc - naturally not', others)[0])
print(O.agree('Start trom Hint', [O.marked('# Start from Hint #', True)] * 3)[0])")
check "made-up words named, real ones passed, misreads voted out" "['trom']
['know7']
['RcbufT', 'bacK', 'ofTer']
[\"Wi'.h\"]
['Plaved']
[]
[] []
Cabinet ministers are - naturally not
Start from Hint" "$got"

# A puzzle files only when the vote wins every clue: with the readings it
# files mended, without them it waits for them.
got=$(cd "$REPO/tools" && python3 -c "
import file_trove_puzzles as F, pathlib, tempfile
d = pathlib.Path(tempfile.mkdtemp())
(d / 'trove' / '1').mkdir(parents=True)
z = d / 'trove-clues' / '1'; z.mkdir(parents=True)
grid = ['...', '.#.', '...']
laid = {'1-across': ('Start trom Hint', '3', None), '3-across': ('Top', '3', None),
        '1-down': ('Bun', '3', None), '2-down': ('Arc', '3', None)}
print(F.vote(d / 'trove' / '1', dict(laid), grid)[1][:30])
for k in F.ocr_clues.READERS:
    (z / f'read.{F.ocr_clues.reader_key(k)}.txt').write_text('ACROSS\n1 Start from Hint (3).\n3 Top (3).\nDOWN\n1 Bun (3).\n2 Arc (3).')
print(F.vote(d / 'trove' / '1', dict(laid), grid)[0]['1-across'][0])
z2 = d / 'trove-clues' / '1' / 'read.ch.txt'
z2.write_text(z2.read_text().replace('Start from Hint', 'Start trom Hint'))
laid['1-across'] = ('Start trom Hint', '3', None)
print(F.vote(d / 'trove' / '1', dict(laid), grid)[0]['1-across'][0])
del laid['2-down']
print(F.vote(d / 'trove' / '1', dict(laid), grid)[1])")
check "the vote mends a clue, and a lost clue keeps the puzzle back" "no reading of the page's clues
Start from Hint
Start from Hint
no clue for 2-down" "$got"

# "(Solution Monday)" mid-line ends the DOWN list: the next puzzle's lists
# after it on the page are not its last clue's text.
got=$(cd "$REPO/tools" && python3 -c "
import file_trove_puzzles as F
print(F.sections('X\\nACROSS\\n1 A b (3).\\nDOWN\\n2 C d (3). (Solution Monday).\\nPlain crossword 59\\nACROSS 1 Hill.\\n25 Pen.')['down'])")
check "the list ends at a solution note mid-line" "2 C d (3)." "$got"

# The vote's segmentation: a word other readings spaced out letter by letter,
# a number in the clue's own text, a mark misread as a digit glued to a word,
# a speck beside or between words, and "1" for an opening "I".
got=$(cd "$REPO/tools" && python3 -c "
import ocr_clues as O
M = lambda *t: [O.marked(x, breaks=True) for x in t]
print(O.agree(\"didn't have to walk\", M(\"28 didn't have to w a lk (9). 29 X\", \"28 didn't have to w al k (9) 29 X\"), True)[0])
print(O.reconcile({'24-across': ('Of the Vale, turn to Map 10 E', '7', None)},
                  ['24 Of the Vale, turn to Map 10 E (7). 26 The'] * 2, {'24-across': 7, '26-across': 7}))
print(O.agree(\"What don't they know7 God knows\", M(\"2 What don't they know? God knows (9). 3 S\") * 2, True)[0])
print(O.agree('Useful people in Hunts7', M('29 Useful people in Hunts? (9). 30 Part') * 3, True)[0])
print(O.agree('Bombed in WW2 town', M('3 Bombed in WW2 town (5) 4 X') * 2, True)[0])
print(O.agree('Proposal i» noted?', M('9 Proposal is noted? (4). 10 S') * 2, True)[0])
print(O.agree('After talk, ■ permitted return', M('16 After talk, permitted return (7). 20 N') * 2, True)[0])
print(O.reconcile({'12-down': ('1 hear prisons might hold churchgoers', '12', None)},
                  ['12 I hear prisons might hold churchgoers (12). 15 P'] * 2, {'12-down': 12}, True)[0])")
check "spaced letters, in-clue numbers, glued digits, specks and an opening 1 voted" "didn't have to walk
({'24-across': ('Of the Vale, turn to Map 10 E', '7', None)}, {})
What don't they know? God knows
Useful people in Hunts?
Bombed in WW2 town
Proposal is noted?
After talk, permitted return
{'12-down': ('I hear prisons might hold churchgoers', '12', None)}" "$got"

# The nightly is bounded by wall clock: no read starts once the budget is
# spent, and what is left gets no ledger row, so the next run reads it.
got=$(cd "$REPO/tools" && python3 -c "
import file_trove_puzzles as F, io, json, pathlib, shutil, tempfile, time
d = pathlib.Path(tempfile.mkdtemp())
shutil.copytree('$FIX', d / 'cache')
read = []
def slow(a, taken):
    read.append(a.name); time.sleep(0.2); return {'skip': 'test'}, None
F.consider = slow
t = F.run(d / 'cache', ledger=d / 'filed.jsonl', out=io.StringIO(), puzzles=d / 'out', seconds=0.1)
rows = [json.loads(l)['article'] for l in (d / 'filed.jsonl').read_text().splitlines()]
print(len(read), t.get('left for the next run'), rows == read)
F.run(d / 'cache', ledger=d / 'filed.jsonl', out=io.StringIO(), puzzles=d / 'out', seconds=60)
print(len(read), len(set(read)))")
check "the time budget stops new reads and leaves the rest pending" "1 2 True
3 3" "$got"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
