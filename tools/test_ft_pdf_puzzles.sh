#!/bin/bash
# Does tools/ft_pdf_puzzles.py read the FT PDF's clue list and vector grid,
# and join each light to the answer fifteensquared printed under its number?
#
#     bash tools/test_ft_pdf_puzzles.sh
#
# Hand-built inputs only: a 5x5 grid drawn as content-stream operations, the
# text pypdf extracts from such a page, and a post in the 2010 answers-only
# layout. Nothing here reads the network, the PDF cache or the corpus.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import ft_pdf_puzzles as F

# SATIN / OPERA / TENTS across; SHOOT, TWEEN, NEARS down.
GRID = [".....", ".#.#.", ".....", ".#.#.", "....."]
ops = [([1], b"g"), ([0, 0, 100, 100], b"re"), ([], b"f"),     # white frame
       ([], b"q"), ([0], b"g")]
for y, row in enumerate(GRID):
    for x, c in enumerate(row):
        if c == "#":
            ops.append(([x * 20 + 1, 100 - (y + 1) * 20 + 1, 18, 18], b"re"))
ops += [([], b"f"), ([], b"Q"),
        # After Q the fill is white again: this square is not a block.
        ([41, 41, 18, 18], b"re"), ([], b"f"),
        # A stroked square is never a block.
        ([0], b"g"), ([1, 1, 18, 18], b"re"), ([], b"S")]
print("GRID", "/".join(F.read_grid(F.filled_rects(ops)) or ["none"]))

# The same grid drawn a second time through a cm shift back onto itself.
twice = ops + [([], b"q"), ([1, 0, 0, 1, 10, 10], b"cm"), ([0], b"g"),
               ([11, 51, 18, 18], b"re"), ([], b"f"), ([], b"Q")]
print("TWICE", "/".join(F.read_grid(F.filled_rects(twice)) or ["none"]))

# White lights on a black square.
inv = [([0], b"k"), ([0, 0, 0, 1], b"k"), ([0, 0, 100, 100], b"re"), ([], b"f"), ([1], b"g")]
for y, row in enumerate(GRID):
    for x, c in enumerate(row):
        if c == ".":
            inv.append(([x * 20 + 1, 100 - (y + 1) * 20 + 1, 18, 18], b"re"))
inv.append(([], b"f"))
print("INVERTED", "/".join(F.read_grid(F.filled_rects(inv)) or ["none"]))

TEXT = """CROSSWORD
No. 13,412 Set by CRUX
1 2 3
4
5
ACROSS
1 Fabric in a sat-
in finish (5)
4 Show
2 voices at the
opera house (5)
5 Camping gear (5)
DOWN
1 Fire (5)
2 Child aged
10 to 12 (5)
3 Gets closer (5)
Crossword winners' names will be published
The Financial Times Crossword Book"""
p = F.parse_clues(TEXT)
print("HEAD", p["number"], p["setter"], len(p["clues"]))
for c in p["clues"]:
    print("CLUE", ",".join(f"{n}{d[0]}" for n, d in c["lights"]), c["clue"], "|", c["enumeration"])
print("MATCH", F.grid_matches(GRID, p["clues"]))
bad = [dict(c) for c in p["clues"]]
bad[0] = dict(bad[0], enumeration="6")
print("MISMATCH", F.grid_matches(GRID, bad))

linked = F.parse_clues("ACROSS\n1 Fabric (5)\n4,5 Show in a field (5,5)\nDOWN\n"
                       "1 Fire (5)\n2 Child (5)\n3 Gets closer (5)\n")
print("LINKED", ",".join(f"{n}{d[0]}" for n, d in linked["clues"][1]["lights"]),
      F.grid_matches(GRID, linked["clues"]))

odd = F.parse_clues("Crossword 13,422 Set by Mudd\nACROSS\n1, 5 Pity (5,5)\n4 Show (5)\n"
                    "5 See 1\nDOWN\n1 Fire (5)\n2 A manner of\nspeaking (5)\n3 Gets closer (5)\n")
print("ODDHEAD", odd["number"], odd["setter"])
print("ODDLIGHTS", " ".join(",".join(f"{n}{d[0]}" for n, d in c["lights"]) for c in odd["clues"]))
print("ODDMATCH", F.grid_matches(GRID, odd["clues"]))

print("JOIN", F.join_lines("to for-", "tunate nine"), "|", F.join_lines("is bad-", "tempered"))

IDX = {"100": {"date": "2010-06-11"}, "103": {"date": "2010-06-15"}, "110": {"date": "2010-07-01"}}
print("NEIGHBOUR", F.neighbour_date(101, IDX), F.neighbour_date(102, IDX), F.neighbour_date(105, IDX))

POST = """<p>Nice one. I liked 3 down and 1 across best.</p>
<p>Across</p>
<p>1</p><p>SATIN  hidden in sat in</p>
<p>4, 5</p><p>OPERA TENTS  charade</p>
<p>Down</p>
<p>1</p><p>SHOOT  dd</p>
<p>2</p><p>TWEEN  cd; 2 is not a number here</p>
<p>3</p><p>NEARS  NEAR + S</p>"""
answers = F.blog_answers(POST, linked["clues"])
print("ANSWERS", " ".join(f"{n}{d[0]}={a}" for (n, d), a in sorted(answers.items())))
entries = F.entries_of(linked, answers, GRID)
print("ENTRIES", " ".join(f"{e['number']}{e['direction'][0]}={e['answer']}" for e in entries))
print("SEE", entries[2]["clue"])

missing = F.blog_answers(POST.replace("NEARS", "Nears"), linked["clues"])
print("MISSING", F.entries_of(linked, missing, GRID))
import datetime
pdf = dict(linked, number=13412, setter="Crux", grid=GRID)
post = {"id": 1, "link": "https://www.fifteensquared.net/x", "date": "2010-06-15",
        "content": {"rendered": POST.replace("NEARS", "Nears")}}
for name, p in (("UNANSWERED", post), ("NOPOST", None)):
    pz, why = F.assemble(13412, pdf, p, datetime.date(2010, 6, 15), "https://media.ft.com/x.pdf", "live")
    print(name, why, pz["solutions"], any("solution" in e for e in pz["entries"]))
PY
)
echo "$out" | sed 's/^/  | /'
g() { echo "$out" | grep "^$1 " | head -1 | cut -d' ' -f2-; }

check "grid read from the filled squares; a restored fill and a stroke are not blocks" \
  "...../.#.#./...../.#.#./....." "$(g GRID)"
check "a second copy shifted by cm lands on the same cells" \
  "...../.#.#./...../.#.#./....." "$(g TWICE)"
check "white lights on a black square" "...../.#.#./...../.#.#./....." "$(g INVERTED)"
check "header: number and setter, capitals title-cased" "13412 Crux 6" "$(g HEAD)"
check "a clue broken at a hyphen keeps it, no space" \
  "1a Fabric in a sat-in finish (5) | 5" "$(echo "$out" | grep '^CLUE 1a' | cut -d' ' -f2-)"
check "an unfinished clue's next line opening with a number is its next line" \
  "4a Show 2 voices at the opera house (5) | 5" "$(echo "$out" | grep '^CLUE 4a' | cut -d' ' -f2-)"
check "the footer ends the list" "3d Gets closer (5) | 5" \
  "$(echo "$out" | grep '^CLUE' | tail -1 | cut -d' ' -f2-)"
check "the grid's numbering matches the clue list" "None" "$(g MATCH)"
check "an enumeration the grid disagrees with is refused" \
  "1 across's enumeration disagrees with the grid" "$(g MISMATCH)"
check "a linked clue lists both lights and counts both" "4a,5a None" "$(g LINKED)"
check "answers read by enumeration; prose numbers ignored" \
  "1a=SATIN 1d=SHOOT 2d=TWEEN 3d=NEARS 4a=OPERATENTS" "$(g ANSWERS)"
check "a linked answer is shared out by the grid's light lengths" \
  "1a=SATIN 4a=OPERA 5a=TENTS 1d=SHOOT 2d=TWEEN 3d=NEARS" "$(g ENTRIES)"
check "the second light of a link points at its leader" "See 4" "$(g SEE)"
check "a light the blog does not answer gets no entries from it" "None" "$(g MISSING)"
check "a light the blog does not answer files the puzzle unsolved" \
  "None {'origin': 'unsolved'} False" "$(g UNANSWERED)"
check "no write-up at all files the puzzle unsolved" \
  "None {'origin': 'unsolved'} False" "$(g NOPOST)"

check "a header with no \"No.\"" "13422 Mudd" "$(g ODDHEAD)"
check "\"2 A manner\" is 2 down, not 2 across; a link's second light is listed once" \
  "1a,5a 4a 5a 1d 2d 3d" "$(g ODDLIGHTS)"
check "a \"See 1\" naming a light already listed still matches the grid" "None" "$(g ODDMATCH)"

check "a word hyphenated to fit the line is rejoined; a compound keeps its hyphen" \
  "to fortunate nine | is bad-tempered" "$(g JOIN)"

check "an undated number takes a day only when the printing days between its neighbours are exactly the numbers" \
  "2010-06-12 2010-06-14 None" "$(g NEIGHBOUR)"

if [ "$fails" -eq 0 ]; then echo "all passed"; else echo "$fails failed"; exit 1; fi
