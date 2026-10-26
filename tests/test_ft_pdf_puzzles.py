#!/usr/bin/env python3
# Does tools/ft_pdf_puzzles.py read the FT PDF's clue list and vector grid,
# and join each light to the answer fifteensquared printed under its number?
#
#     python3 tests/test_ft_pdf_puzzles.py
#
# Hand-built inputs only: a 5x5 grid drawn as content-stream operations, the
# text pypdf extracts from such a page, and a post in the 2010 answers-only
# layout. Nothing here reads the network, the PDF cache or the corpus.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import ft_pdf_puzzles as F
import genius_puzzles as G

fails = 0
lines = []


def emit(*parts):
    lines.append(" ".join(str(p) for p in parts))


def first(prefix):
    for l in lines:
        if l.startswith(prefix):
            return l.split(" ", 1)[1] if " " in l else ""
    return ""


def line(key):
    """The rest of the first output line that opens with KEY."""
    return first(key + " ")


def last(prefix):
    hits = [l for l in lines if l.startswith(prefix)]
    return hits[-1].split(" ", 1)[1] if hits else ""


def check(what, got, want):
    global fails
    if got == want:
        print(f"ok   {what}")
    else:
        print(f"FAIL {what}: expected [{want}], got [{got}]")
        fails += 1


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
emit("GRID", "/".join(F.read_grid(F.filled_rects(ops)) or ["none"]))

# The same grid drawn a second time through a cm shift back onto itself.
twice = ops + [([], b"q"), ([1, 0, 0, 1, 10, 10], b"cm"), ([0], b"g"),
               ([11, 51, 18, 18], b"re"), ([], b"f"), ([], b"Q")]
emit("TWICE", "/".join(F.read_grid(F.filled_rects(twice)) or ["none"]))

# White lights on a black square.
inv = [([0], b"k"), ([0, 0, 0, 1], b"k"), ([0, 0, 100, 100], b"re"), ([], b"f"), ([1], b"g")]
for y, row in enumerate(GRID):
    for x, c in enumerate(row):
        if c == ".":
            inv.append(([x * 20 + 1, 100 - (y + 1) * 20 + 1, 18, 18], b"re"))
inv.append(([], b"f"))
emit("INVERTED", "/".join(F.read_grid(F.filled_rects(inv)) or ["none"]))

# The 2011-12 layout: blocks filled with tint 1 of a /DeviceN "Black" space
# (ink, so dark), one block drawn as a closed m/l path, and the grid ruled
# with thin bars and no square behind it.
ink = [([True], b"cs"), ([1], b"scn")]
for y, row in enumerate(GRID):
    for x, c in enumerate(row):
        if c == "#" and (x, y) != (3, 3):
            ink += [([x * 20, 100 - (y + 1) * 20, 20, 20], b"re"), ([], b"f")]
ink += [([], b"q"), ([1, 0, 0, 1, 60, 20], b"cm"), ([0, 0], b"m"), ([20, 0], b"l"),
        ([20, 20], b"l"), ([0, 20], b"l"), ([], b"f"), ([], b"Q")]
for i in range(6):
    ink += [([i * 20 - 0.5, 0, 1, 100], b"re"), ([], b"f"), ([0, i * 20 - 0.5, 100, 1], b"re"), ([], b"f")]
emit("INK", "/".join(F.read_grid(F.filled_rects(ink)) or ["none"]))

TEXT = """CROSSWORD
No. 13,412 Set by CRUX
1 2 3
4
5
ACROSS
1 Fabric in a far-
reaching finish (5)
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
emit("HEAD", p["number"], p["setter"], len(p["clues"]))
for c in p["clues"]:
    emit("CLUE", ",".join(f"{n}{d[0]}" for n, d in c["lights"]), c["clue"], "|", c["enumeration"])
emit("MATCH", F.grid_matches(GRID, p["clues"]))
bad = [dict(c) for c in p["clues"]]
bad[0] = dict(bad[0], enumeration="6")
emit("MISMATCH", F.grid_matches(GRID, bad))

linked = F.parse_clues("ACROSS\n1 Fabric (5)\n4,5 Show in a field (5,5)\nDOWN\n"
                       "1 Fire (5)\n2 Child (5)\n3 Gets closer (5)\n")
emit("LINKED", ",".join(f"{n}{d[0]}" for n, d in linked["clues"][1]["lights"]),
      F.grid_matches(GRID, linked["clues"]))

odd = F.parse_clues("Crossword 13,422 Set by Mudd\nACROSS\n1, 5 Pity (5,5)\n4 Show (5)\n"
                    "5 See 1\nDOWN\n1 Fire (5)\n2 A manner of\nspeaking (5)\n3 Gets closer (5)\n")
emit("ODDHEAD", odd["number"], odd["setter"])
emit("ODDLIGHTS", " ".join(",".join(f"{n}{d[0]}" for n, d in c["lights"]) for c in odd["clues"]))
emit("ODDMATCH", F.grid_matches(GRID, odd["clues"]))

emit("JOIN", F.join_lines("to for-", "tunate nine"), "|", F.join_lines("is bad-", "tempered"))
emit("JOINRARE", F.join_lines("despite shad-", "owed"), "|", F.join_lines("do it unac-", "ceptably"),
      "|", F.join_lines("a level playing-", "field"))
zero = F.parse_clues("ACROSS\n1 Fabric (5)\n4 Show (5)\n5 Gear (5)\nD0WN\n"
                     "1 Fire (5)\n2 Child (5)\n3 Gets closer (5)\n")
emit("ZERO", " ".join(f"{n}{d[0]}" for c in zero["clues"] for n, d in c["lights"]))
# No. 13,680: a linked head alone on its line, a light it leaves unsaid that its
# stub lists in the other section, an enumeration broken at its hyphen.
# No. 13,774: "(9’s 7)".
apart = F.parse_clues("ACROSS\n1 Fabric (5)\n4 Show (3’s 2)\n5 See 2\nDOWN\n1 Fire (5)\n"
                      "2, 5\nChild given a\ntent (4-\n1,5)\n3 Gets closer (5)\n")
emit("APART", " ".join(",".join(f"{n}{d[0]}" for n, d in c["lights"]) for c in apart["clues"]),
      "|", " ".join(str(c["enumeration"]) for c in apart["clues"]),
      "|", F.grid_matches(GRID, apart["clues"]))
emit("APARTCLUE", apart["clues"][4]["clue"])
# No. 13,833 prints its note under the grid's numbers, above ACROSS.
noted = F.parse_clues("CROSSWORD\nNo. 13,833 Set by GAFF\n1 2 3\n4\n10 solutions are connected to 11\n"
                      "across, which is unclued and 50\ntoday\nACROSS\n1 Fabric (5)\n4 See preamble (5)\n"
                      "5 Gear (5)\nDOWN\n1 Fire (5)\n2 Child (5)\n3 Gets closer (5)\n")
emit("NOTE", noted["preamble"], "|", p["preamble"])

IDX = {"100": {"date": "2010-06-11"}, "103": {"date": "2010-06-15"}, "110": {"date": "2010-07-01"}}
emit("NEIGHBOUR", F.neighbour_date(101, IDX), F.neighbour_date(102, IDX), F.neighbour_date(105, IDX))

POST = """<p>Nice one. I liked 3 down and 1 across best.</p>
<p>Across</p>
<p>1</p><p>SATIN  hidden in sat in</p>
<p>4, 5</p><p>OPERA TENTS  charade</p>
<p>Down</p>
<p>1</p><p>SHOOT  dd</p>
<p>2</p><p>TWEEN  cd; 2 is not a number here</p>
<p>3</p><p>NEARS  NEAR + S</p>"""
answers = F.blog_answers(POST, linked["clues"])
emit("ANSWERS", " ".join(f"{n}{d[0]}={a}" for (n, d), a in sorted(answers.items())))
entries = F.entries_of(linked, answers, GRID)
emit("ENTRIES", " ".join(f"{e['number']}{e['direction'][0]}={e['answer']}" for e in entries))
emit("SEE", entries[2]["clue"])
across = F.entries_of({"clues": [{"lights": [(1, "down"), (5, "across")], "clue": "Go to tents (5,5)",
                                  "enumeration": "5,5"}]}, {(1, "down"): "SHOOTTENTS"}, GRID)
emit("SEEWAY", across[1]["clue"])

missing = F.blog_answers(POST.replace("NEARS", "Nears"), linked["clues"])
emit("MISSING", F.entries_of(linked, missing, GRID))
import datetime
pdf = dict(linked, number=13412, setter="Crux", grid=GRID)
post = {"id": 1, "link": "https://www.fifteensquared.net/x", "date": "2010-06-15",
        "content": {"rendered": POST.replace("NEARS", "Nears")}}
for name, p in (("UNANSWERED", post), ("NOPOST", None)):
    pz, why = F.assemble(13412, pdf, p, datetime.date(2010, 6, 15), "https://media.ft.com/x.pdf", "live")
    emit(name, why, pz["solutions"], any("solution" in e for e in pz["entries"]))
# No vector grid, or one misread: the clue list's numbering rebuilds it, and
# the file says the grid was rebuilt rather than read.
F.tg.SIZE["FT"] = 5
for name, g in (("BACKSOLVED", None), ("MISREAD", ["#...."] + list(GRID[1:]))):
    pz, why = F.assemble(13412, dict(pdf, grid=g), post | {"content": {"rendered": POST}},
                         datetime.date(2010, 6, 15), "https://media.ft.com/x.pdf", "live")
    emit(name, why, pz and pz["source"]["gridOrigin"], pz and pz["dimensions"],
          pz and "backsolved" in pz["solutions"]["check"])

for name, clue in (("SEMI", "Top of old letter's given new heading (5;3)"),
                   ("SEMISPACE", "Heather's singularly flashy jewellery (5; 9)"),
                   ("ROW", "After onset of winter, ordinary leaves disappear (4,3) (7)"),
                   ("ROWSEMI", "Warns dinosaur's health is suffering (6,3,5); (6,3,6)"),
                   ("NESTED", "Hector, complete philosopher (6,5 (9))"),
                   ("AND", "Going on a while, male poet cut free verse (10 and 5)"),
                   ("YEAR", "Wall Street share prices (1929) crashed")):
    m = F.ENUM.search(clue)
    emit(name, m and m.group(1))
def read(t):
    return " ; ".join(f"{c['lights'][0][0]}={c['enumeration']}:{c['clue']}"
                      for c in G.section(t, 0, "across")[0])
emit("GSEMI", read(" 1 Top of letter (5;3) 2 Pop group member? (8)"))
emit("GROW", read(" 20 Thus new dons fast (5,2) (7) 21 String player lives with tenor (7)"))
emit("GNESTED", read(" 5,8 Hector (6,5 (9)) 8 See 5 9 Lass (4)"))
emit("GSTUB", read(" 17 See 7 (8) 29 [unclued] (4) 30 Bug (6)"))
emit("GBARE", read(" 1 (6) 2 (6) 3 (4)"))
emit("GXREF", read(" 5 (2) What gets branch of police together? (6)"))

check('grid read from the filled squares; a restored fill and a stroke are not blocks',
      line('GRID'), '...../.#.#./...../.#.#./.....')
check('a second copy shifted by cm lands on the same cells',
      line('TWICE'), '...../.#.#./...../.#.#./.....')
check('white lights on a black square',
      line('INVERTED'), '...../.#.#./...../.#.#./.....')
check('ink tints, a block drawn as a path, a grid ruled with no frame square',
      line('INK'), '...../.#.#./...../.#.#./.....')
check('header: number and setter, capitals title-cased',
      line('HEAD'), '13412 Crux 6')
check('the note above ACROSS is the preamble; grid numbers and header are not',
      line('NOTE'), '10 solutions are connected to 11 across, which is unclued and 50 today | None')
check('a clue broken at a hyphen keeps it, no space',
      first('CLUE 1a'), '1a Fabric in a far-reaching finish (5) | 5')
check("an unfinished clue's next line opening with a number is its next line",
      first('CLUE 4a'), '4a Show 2 voices at the opera house (5) | 5')
check('the footer ends the list',
      last('CLUE'), '3d Gets closer (5) | 5')
check("the grid's numbering matches the clue list",
      line('MATCH'), 'None')
check('an enumeration the grid disagrees with is refused',
      line('MISMATCH'), "1 across's enumeration disagrees with the grid")
check('a linked clue lists both lights and counts both',
      line('LINKED'), '4a,5a None')
check('no vector grid: backsolved from the clue list, marked reconstructed',
      line('BACKSOLVED'), "None reconstructed {'cols': 5, 'rows': 5} True")
check('a misread vector grid: backsolved from the clue list too',
      line('MISREAD'), "None reconstructed {'cols': 5, 'rows': 5} True")
check('answers read by enumeration; prose numbers ignored',
      line('ANSWERS'), '1a=SATIN 1d=SHOOT 2d=TWEEN 3d=NEARS 4a=OPERATENTS')
check("a linked answer is shared out by the grid's light lengths",
      line('ENTRIES'), '1a=SATIN 4a=OPERA 5a=TENTS 1d=SHOOT 2d=TWEEN 3d=NEARS')
check('the second light of a link points at its leader',
      line('SEE'), 'See 4')
check("a linked light running the other way names its leader's direction",
      line('SEEWAY'), 'See 1 down')
check('a light the blog does not answer gets no entries from it',
      line('MISSING'), 'None')
check('a light the blog does not answer files the puzzle unsolved',
      line('UNANSWERED'), "None {'origin': 'unsolved'} False")
check('no write-up at all files the puzzle unsolved',
      line('NOPOST'), "None {'origin': 'unsolved'} False")
check('a header with no "No."',
      line('ODDHEAD'), '13422 Mudd')
check('"2 A manner" is 2 down, not 2 across; a link\'s second light is listed once',
      line('ODDLIGHTS'), '1a,5a 4a 5a 1d 2d 3d')
check('a "See 1" naming a light already listed still matches the grid',
      line('ODDMATCH'), 'None')
check('a word hyphenated to fit the line is rejoined; a compound keeps its hyphen',
      line('JOIN'), 'to fortunate nine | is bad-tempered')
check('a word rarer than its first half is still rejoined; two words that are no word keep the hyphen',
      line('JOINRARE'), 'despite shadowed | do it unacceptably | a level playing-field')
check('a heading set with a zero, D0WN, still opens the down clues',
      line('ZERO'), '1a 4a 5a 1d 2d 3d')
check("a linked head alone on its line opens the clue; its unsaid light takes its stub's section; (3’s 2) is an enumeration, counted as entered",
      line('APART'), '1a 4a 5a 1d 2d,5a 3d | 5 3 2 None 5 4-1,5 5 | None')
check('a clue under a head-only line starts at its next line',
      line('APARTCLUE'), 'Child given a tent (4-1,5)')
check('an undated number takes a day only when the printing days between its neighbours are exactly the numbers',
      line('NEIGHBOUR'), '2010-06-12 2010-06-14 None')

check("(5;3): two counts in one bracket, the grid's after the semicolon",
      line('SEMI'), '3')
check('(5; 9): a spaced semicolon too',
      line('SEMISPACE'), '9')
check("(4,3) (7): two brackets in a row, the grid's the second",
      line('ROW'), '7')
check('(6,3,5); (6,3,6): two brackets split by a semicolon',
      line('ROWSEMI'), '6,3,6')
check("(6,5 (9)): a nested count, the grid's the outer",
      line('NESTED'), '6,5')
check('(10 and 5): counts joined by and',
      line('AND'), '10 and 5')
check("a year in the clue's words is no enumeration",
      line('YEAR'), 'None')
check('Genius: a (5;3) clue does not end the list',
      line('GSEMI'), '1=3:Top of letter (5;3) ; 2=8:Pop group member? (8)')
check('Genius: a (5,2) (7) clue does not end the list',
      line('GROW'), '20=7:Thus new dons fast (5,2) (7) ; 21=7:String player lives with tenor (7)')
check('Genius: a nested (6,5 (9)) clue does not end the list',
      line('GNESTED'), '5=6,5:Hector (6,5 (9)) ; 8=None:See 5 ; 9=4:Lass (4)')
check("Genius: a stub's printed count is dropped, the stub kept",
      line('GSTUB'), '17=None:See 7 ; 29=None:[unclued] ; 30=6:Bug (6)')
check('Genius: lights printed with a count and no clue',
      line('GBARE'), '1=6:(6) ; 2=6:(6) ; 3=4:(4)')
check('Genius: a clue opening on a bracketed cross-reference is one clue',
      line('GXREF'), '5=6:(2) What gets branch of police together? (6)')

if not fails:
    print("all passed")
else:
    print(f"{fails} failed")
    sys.exit(1)
