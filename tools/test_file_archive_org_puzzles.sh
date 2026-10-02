#!/bin/bash
# Does tools/file_archive_org_puzzles.py find the Times cryptic's title and
# not its neighbours', read the clue columns in order, keep only the clues
# both readings agree on, and match a Canberra reprint only when it is one?
#
#     bash tools/test_file_archive_org_puzzles.sh
#
# Pure functions on made-up words and puzzles: no scan, no RapidOCR, nothing
# written outside a temp dir.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

out=$(cd "$REPO/tools" && TMP="$tmp" python3 - <<'EOF'
import json, os
from pathlib import Path
import file_archive_org_puzzles as f

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

def line(text, x=100, y=100):
    words, out = text.split(), []
    for w in words:
        out.append((x, y, x + 10 * len(w), y + 16, w))
        x += 10 * len(w) + 8
    return out

# The title: the daily cryptic's, its number, a box ending at the number.
hits = f.headings([line("THE TIMES CROSSWORD NO 19,742 1 1 times weathercall")], f.TITLE)
check("1990s title read, junk after the number left out", (19742, 100 + 10*3+8 + 10*5+8 + 10*9+8 + 10*2+8 + 10*6),
      (hits[0][0], hits[0][1][2]))
check("1970s title read", [13677], [n for n, _ in f.headings([line("The Times Crossword Puzzle No 13,677")], f.TITLE)])
check("Concise, Times Two and Jumbo titles are not the cryptic's", [],
      f.headings([line("CONCISE CROSSWORD NO 2065"), line("Times Two Crossword, page 32"),
                  line("Times Jumbo Crossword No 812")], f.TITLE))
check("the cryptic's solution heading read", [18179],
      [n for n, _ in f.headings([line("Solution to Puzzle No 18,179"), line("SOLUTION TO NO 2064")], f.SOLUTION)])
check("1970s solution heading read", [13676],
      [n for n, _ in f.headings([line("Solution of Puzzle No 13,676 B.A. &so.")], f.SOLUTION)])

# The columns: left then right, a number read apart joined to its row, a
# second copy of words dropped, cut at the solution heading.
grid = (100, 100, 800, 800)
lines = [line("ACROSS", 100, 820), [(100, 842, 118, 858, "1")], line("Nymph with broken heart (8)", 130, 840),
         line("DOWN", 470, 820), line("2 Hermit is strangely secure (7)", 470, 840),
         line("2 Hermit is strangely secure (7)", 470, 841),
         line("Solution to Puzzle No 13,676", 100, 870), line("rubbish (3)", 100, 890)]
check("columns read left then right, a row joined, a copy dropped, cut at the solution",
      "ACROSS\n1 Nymph with broken heart (8)\nDOWN\n2 Hermit is strangely secure (7)",
      f.column_text(f.columns(lines, grid)))
far = [line("ACROSS", 100, 820), line("1 Nymph (8)", 100, 840), line("9 Gap (5)", 100, 840 + f.GAP + 40)]
check("a gap ends a column", "ACROSS\n1 Nymph (8)", f.column_text(f.columns(far, grid)))

# tidy(): OCR's slips in the print's shape.
check("braces and square brackets read as round ones", "1 Poet's way (5)\n2 Talks (3,2)",
      f.tidy("1 Poet's way {5}\n2 Talks [3,2]"))
check("a number run into its word split off", "1 Mythical king (9)", f.tidy("1Mythical king (9)"))
check("a number lost after a count marked for the grid", "10 Nurse (7)\n? Holds fast (5)",
      f.tidy("10 Nurse (7)\nHolds fast (5)"))
check("a number lost after the heading marked", "ACROSS\n? Nymph (8)", f.tidy("ACROSS\nNymph (8)"))
check("a wrapped line is not marked", "10 Nurse holding\nNote (7)", f.tidy("10 Nurse holding\nNote (7)"))
check("a count with a broken close read as one", "19 Stole pig (3)", f.tidy("19 Stole pig off3j".replace(" off", "")))

# agree(): only what both readings say, or what the dictionary settles.
stream = f.tokens("8 Hope created this exalted 9 Bottom of a ship (3) 10 Nurse hoiding note (7) 11 Prinz Ahdk (5)")
check("both readings agree", ("Bottom of a ship", "agree"), f.agree("Bottom of a ship", stream))
check("a misread settled by the other reading's dictionary word",
      ("Nurse holding note", "settled by the dictionary"), f.agree("Nurse holding note", stream))
check("the clue's misread replaced by the other reading's word",
      ("Hope created this exalted", "settled by the dictionary"), f.agree("Hope crealed this exalted", stream))
check("two non-words are a disagreement", None, f.agree("Prinz Ahdq", stream)[0])
check("a word the other reading lacks is a disagreement", None, f.agree("Bottom of a big ship", stream)[0])
check("both readers' one non-word mended to the known word a letter off", "Nurse holding note",
      f.agree("Nurse hoiding note", stream)[0])

check("a capital only one reader saw inside the clue dropped", ("What is stated", "settled by the dictionary"),
      f.agree("What Is stated", f.tokens("27 What is stated (9)")))
got, _ = f.reconcile({"25-across": ("As worn by agitator in back- street", "8", None)},
                     "25 As worn by agitator in back-\nstreet (8)")
check("a word hyphenated over a line end is joined as the corpus prints it", "As worn by agitator in backstreet",
      got["25-across"][0])
check("the clue's first word keeps its capital", ("Bottom of a ship", "agree"),
      f.agree("Bottom of a ship", f.tokens("bottom of a ship")))

# Three readings: a word the other two share outvotes mine; a mark no other
# reading has is dropped; a non-word all three read is kept.
two = [f.marked("8 Wisdom shown by school-head when dress is questionable (10)"),
       f.marked("8 Wisdom shown by school-head when dress is questionabie (10)")]
check("a lone comma no other reading has dropped",
      "Wisdom shown by school-head when dress is questionable",
      f.agree("Wisdom shown by, school-head when dress is questionable", two)[0])
check("a comma two readings have kept", "Talk, about a fellow",
      f.agree("Talk, about a fellow", [f.marked("Talk, about a fellow"), f.marked("Talk about a fellow")])[0])
check("the spelling the other two readings share outvotes mine (dictionary words both)",
      "Cashing in on Nigel's air", f.agree("Cashing in on Nigel's ail",
                                           [f.marked("Cashing in on Nigel's air")] * 2)[0])
check("a word one of two other readings has stands", "Sun god's not out",
      f.agree("Sun god's not out", [f.marked("Son god's not out"), f.marked("Sun gods not out")])[0])
check("a non-word all three readings have, no letter from a word, kept", "Get production up qzxvbn",
      f.agree("Get production up qzxvbn", [f.marked("Get production up qzxvbn")] * 2)[0])
check("a name the corpus's clues know is a word", "Captain Hornblower at sea",
      f.agree("Captain Hornblower at sea", [f.marked("3 Captain Hornblower at sea (7)", breaks=True)] * 2)[0])
check("a lone letter no other reading has is a speck", "Annual production",
      f.agree("Annual l production", [f.marked("4 Annual production (5)", breaks=True)] * 2)[0])
got, blank = f.reconcile({"8-down": ("Wisdom shown by, school-head", "10", None)},
                         ["8 Wisdom shown by school-head (10)", "8 Wisdom shown by school-head (10)"])
check("reconcile votes with every reading it is given", "Wisdom shown by school-head", got["8-down"][0])

# Words and marks this reading lost, and the print's commonest mark slips.
three = [f.marked(t, breaks=True) for t in ("9 Hurtful stuff, nicer as a cocktail? (7)",
                                            "9 Hurtful stuff, nicer as a cocktail? (7)",
                                            "9 Hurtfui stuff nicer as a cocktail (7)")]
check("a comma most other readings have put in", "Hurtful stuff, nicer as a cocktail?",
      f.agree("Hurtful stuff nicer as a cocktail?", three)[0])
lost = [f.marked(t, breaks=True) for t in ("18 It's no go when caught (8)", "18 It's no go when caught (8)",
                                           "18 Its no go when caught (8)")]
check("lost opening words most readings have put in, with the capital", "It's no go when caught",
      f.agree("Go when caught", lost)[0])
check("lost opening words the readings differ on blank the clue", None,
      f.agree("Go when caught", [f.marked(t, breaks=True) for t in
                                 ("18 It's no go when caught (8)", "18 Is so go when caught (8)")])[0])
check("lost closing words most readings have put in", "Girls were well sustained by it",
      f.agree("Girls were well sustained by", [f.marked("19 Girls were well sustained by it (7)", breaks=True)] * 2)[0])
check("a dictionary tie goes to the word the corpus's clues put there", "A boy is backward",
      f.agree("A bny is backward", [f.marked("19 A boy is backward (4)", breaks=True),
                                    f.marked("19 A bay is backward (4)", breaks=True)])[0])
check("a dictionary tie no neighbour settles blanks the word", None,
      f.agree("Qxv bny qxv", [f.marked("1 Qxv boy qxv (3)", breaks=True),
                              f.marked("1 Qxv bay qxv (3)", breaks=True)])[0])
check("one reading's far shorter dictionary word is no rival", "Chucked one in",
      f.agree("Chucked one in", [f.marked("24 Chuckeu one in (5)", breaks=True),
                                 f.marked("24 Che one in (5)", breaks=True)])[0])
check("a rare word one ink slip from a far commoner one takes the commoner", "Bob hangs on to this",
      f.agree("Bob hangs ou to this", [f.marked("3 Bob hangs ou to this (5)", breaks=True)] * 3)[0])
check("the next clue run on is cut off, the count from the grid",
      ({"5-down": ("Twists ends of osier into knot", "7", None)}, {}),
      f.reconcile({"5-down": ("Twists ends of osier into knot (7k 6 Protection for working", None, None)},
                  ["5 Twists ends of osier into knot (7) 6 Protection for working"], {"5-down": 7, "6-down": 3}))
check("a lone letter after the clue is its misread count, the count from the grid",
      ({"2-down": ("A bit of nice dark wood", "5", None)}, {}),
      f.reconcile({"2-down": ("A bit of nice dark wood", None, None)},
                  ["2 A bit of nice dark wood s 3 Next", "2 A bit of nice dark wood a 3 Next"], {"2-down": 5}))
check("a mark dropped between two words leaves their space", "Lack of spirit after a storm",
      f.agree("Lack of spirit:after a storm", [f.marked("1 Lack of spirit after a storm (4)", breaks=True)] * 2)[0])
check("a misread clue number before the capital dropped", "Not small horse-pistols",
      f.agree("I Not small horse-pistols", [f.marked(t, breaks=True) for t in
                                            ("21 Not small horse-pistols (5)", "21 Not smal horse-pistols (5)")])[0])
check("a full stop before a lower-case word is a comma", "Let nine go loose, being merciful",
      f.clean("Let nine go loose. being merciful"))
check("an ellipsis and an abbreviation keep their stops", "Oval . . . the C.I.D. man",
      f.clean("Oval . . . the C.I.D. man"))
check("an I last before the count is an exclamation mark", "Flirted outrageously! (7)",
      f.clean("Flirted outrageously I (7)"))
check("a word broken over a line end is joined", "Almost admire a lieutenant unknown",
      f.clean("Almost admire a lieutenant un-\nknown"))
check("a line-end hyphen the corpus's clues print closed is the line break's", "agitator in backstreet",
      f.clean("agitator in back-\nstreet"))
check("a line-end hyphen the corpus's clues print hyphenated is the compound's", "start is short-lived",
      f.clean("start is short-\nlived"))
check("a name hyphenated over a line end is joined", "resembling Palgrave's Treasury",
      f.clean("resembling Pal-\ngrave's Treasury"))
check("a compound the corpus never prints keeps its hyphen", "Wisdom shown by school-head",
      f.clean("Wisdom shown by school-\nhead"))
check("a 1 standing as a word inside a clue is an I", "in letter I posted (4)", f.clean("in letter 1 posted (4)"))
check("a 1 naming a light stays", ["see 1 down", "Cross 1 and 2 (5)", "in 1 Across (4)", "in 1982 film"],
      [f.clean(t) for t in ("see 1 down", "Cross 1 and 2 (5)", "in 1 Across (4)", "in 1982 film")])
check("a lone I some reading lacks is a speck", ["Turn on at length an item", "Turn on at length an item"],
      [f.agree("Turn on at length an item", [f.marked(t, breaks=True) for t in (
           "8 Turn on at length 1 an item (6)", "8 Turn on at length 1 an item (6)", "8 Turn on at length an item (6)")])[0],
       f.agree("Turn on at length I an item", [f.marked(t, breaks=True) for t in (
           "8 Turn on at length an item (6)", "8 Turn on at length an item (6)", "8 Turn on at length I an item (6)")])[0]])
check("a lone I every reading has stands", "in letter I posted",
      f.agree("in letter I posted", [f.marked(f.clean("8 in letter 1 posted (6)"), breaks=True)] * 3)[0])
got, blank = f.reconcile({"1-down": ("Unusual way over the mountains", "7", None)},
                         ["25 Vanquished (8)\nDOWN\nI Unusual way over the mountains (7)"] * 2)
check("the DOWN heading over 1 down is no lost word of it", "Unusual way over the mountains", got["1-down"][0])
check("a heading read badly is still the heading; a stray capital word is not",
      ["DOWN", "DOWN", "ACROSS", None, None],
      [f.heading_of(t) for t in ("DOW'N", "DOIN", "AROSS", "Down in", "SOLUTION")])
check("a line starting a lower-case down carries on the line before", "9 Engineer tbe break down (8).\n10 Next (4)",
      f.tidy("9 Engineer tbe break\ndown (8).\n10 Next (4)"))
check("a possessive of a dictionary word is a word", True, f.is_word("Lear's") and f.is_word("bookie's"))

# The solution grid's blocks: a heavy print's block flecked with paper is a
# block; a light whose letter is fat is not.
import numpy as np, trove_solution_ocr as tso
rng = np.random.default_rng(1)
gray = np.full((300, 300), 255, np.uint8)
for k in range(6):
    gray[k * 60:k * 60 + 6, :] = 0
    gray[:, k * 60:k * 60 + 6] = 0
gray[60:120, 60:120] = 0
fleck = rng.random((60, 60)) < 0.15
gray[60:120, 60:120][fleck] = 255           # the block: 15% white flecks
gray[130:170, 140:160] = 0                  # a fat letter in the light at (2, 2)
gray[130:150, 125:175] = 0
gray = np.where(gray == 0, rng.integers(0, 40, gray.shape), rng.integers(200, 256, gray.shape)).astype(np.uint8)
grid5 = [".....", ".#...", ".....", ".....", "....."]
check("a flecked block read as a block, a fat letter's light as a light", 1.0,
      tso.block_agreement(gray, grid5, (0, 0, 60, 60)))

# improves(): a reading replaces a file this tool filed when it beats it.
pz = Path(os.environ["TMP"]) / "pz"; pz.mkdir()
def p3(texts, acq=f.TOOL):
    return {"source": {"acquiredBy": acq}, "dimensions": {"cols": 3, "rows": len(texts)},
            "entries": [{"number": i + 1, "direction": "across", "position": {"x": 0, "y": i}, "length": 3,
                         "clue": {"text": t}, "solution": None} for i, t in enumerate(texts)]}
(pz / "own.json").write_text(json.dumps(p3([""])))
(pz / "theirs.json").write_text(json.dumps(p3([""], "tools/acquire_book.py")))
(pz / "two.json").write_text(json.dumps(p3(["Top", "", ""])))
check("a fuller reading that blanks a clue the file has does not replace it", False,
      f.improves(p3(["", "Low", "Mid"]), pz / "two.json"))
check("a fuller reading replaces this tool's file, never another tool's or an equal one",
      [True, False, False], [f.improves(p3(["Top"]), pz / "own.json"),
                             f.improves(p3(["Top"]), pz / "theirs.json"),
                             f.improves(p3([""]), pz / "own.json")])

# expected_number(): a misdated item is caught, a dated one passes.
import datetime
check("numbers the dates imply, either side of the shutdown",
      [True, True, True, True, False],
      [abs(n - f.expected_number(datetime.date.fromisoformat(d))) <= f.NUMBER_SLACK
       for d, n in [("1974-05-02", 13677), ("1985-07-11", 16786), ("1995-01-03", 19742),
                    ("1998-07-25", 20853), ("1965-07-05", 20212)]])

# lay_loose(): each clue alone on its own light; a misread count is not laid.
g = ["...", ".#.", "..."]
parsed = {"across": [{"tokens": [{1}], "text": "Top", "enums": {"3"}, "see": None},
                     {"tokens": [{3}], "text": "Bottom", "enums": {"5"}, "see": None}],
          "down": [{"tokens": [{1}], "text": "Left", "enums": {"3"}, "see": None},
                   {"tokens": [{2, 3}], "text": "Right", "enums": {"3"}, "see": None}]}
loose, bad = f.lay_loose(parsed, g)
check("clues laid on their own lights, a number read two ways on the one light it names; a wrong count not",
      ({"1-across": "Top", "1-down": "Left", "2-down": "Right"}, ["3-across"]),
      ({k: v[0] for k, v in loose.items()}, bad))

# A clue whose number was lost takes the one light its neighbours leave free.
g = ["...#...", ".......", "...#..."]
lost = {"across": [{"tokens": [{1}], "text": "Top", "enums": {"3"}, "see": None},
                   {"tokens": [set()], "text": "Lost", "enums": {"3"}, "see": None},
                   {"tokens": [{7}], "text": "Middle", "enums": {"7"}, "see": None},
                   {"tokens": [{8}], "text": "Low", "enums": {"3"}, "see": None},
                   {"tokens": [{9}], "text": "End", "enums": {"3"}, "see": None}],
        "down": []}
base = {"1-across": "Top", "7-across": "Middle", "8-across": "Low", "9-across": "End"}
check("a lost number laid between its neighbours only with every reading's numbered lights known",
      (base, {**base, "4-across": "Lost"}, base),
      tuple({k: v[0] for k, v in f.lay_loose(lost, g, *t)[0].items()} for t in ((), (set(),), ({"4-across"},))))

# Short last line: "turn (6)" under a line whose box overhangs it is kept;
# a second copy of the line is not.
rows = f.merge_rows([(4264, 4302, 2279, 2590, "3 The friends got sea sick in"), (4286, 4315, 2303, 2382, "turn (6)"),
                     (4266, 4300, 2280, 2588, "3 The friends got sea sick in"), (4270, 4290, 2250, 2270, "5")])
check("a short line under an overhanging box kept, a copy dropped, a number beside joined",
      ["5 3 The friends got sea sick in", "turn (6)"], [r[4] for r in rows])

# A comma one reading lacks costs less than a word: the words after it pair.
others = [f.marked(f.clean(t), breaks=True) for t in ("27 Only. 28 A leisurely drink, doubtless, inside (8) 29 The",
                                                      "28 A leisurely drink, doubtless, inslde (8) 29 The")]
check("a lost comma put back, not the clue's end lost", "A leisurely drink, doubtless, inside",
      f.agree("A leisurely drink, doubtless inside", others)[0])
check("a word split at a line end joined again; two words are not", (["people", "tastefully", "dressed"], ["lots", "of", "fish"]),
      (f.rejoin(["people", "taste", ",", "fully", "dressed"], ["tastefully"]),
       f.rejoin(["lots", "of", "fish"], ["offish"])))

laid = {"1-across": ("Bottom of a ship", "3", None), "2-across": ("Bottom of a ship", None, None),
        "3-across": ("Smoothed it 18 Warning of one", "7", None), "4-down": ("See 1", None, None),
        "5-down": ("s about a ship", "3", None)}
got, blank = f.reconcile(laid, "Bottom of a ship (3)")
check("a clue without a count, holding another clue's number, or starting mid-clue filed blank; See kept",
      ({"1-across": "Bottom of a ship", "2-across": "", "3-across": "", "4-down": "See 1", "5-down": ""},
       ["2-across", "3-across", "5-down"]),
      ({k: v[0] for k, v in got.items()}, sorted(blank)))

# edition_dirs(): the years in turn, so a capped run reaches every decade.
cache = Path(os.environ["TMP"]) / "cache"
for item, eds in (("NewsUK1974UKEnglish", ["1974-05-01_1", "1974-05-02_2"]),
                  ("NewsUK1990UKEnglish", ["1990-01-02_3"]), ("FinancialTimes1975UKEnglish", ["1975-01-01_4"])):
    for e in eds:
        (cache / item / e).mkdir(parents=True)
        (cache / item / e / "pages.json").write_text("{}")
check("editions taken a year at a time, the FT left out", ["1974-05-01_1", "1990-01-02_3", "1974-05-02_2"],
      [d.name for d in f.edition_dirs(cache)])
check("the FT's editions are the FT phase's, and their paper is the FT",
      (["1975-01-01_4"], "ftcryptic", "times"),
      ([d.name for d in f.edition_dirs(cache, f.FT)], f.paper_of(cache / "FinancialTimes1975UKEnglish" / "x").series,
       f.paper_of(cache / "NewsUK1990UKEnglish" / "x").series))

# The FT: "CROSSWORD" over "No. 8,650 Set by DANTE" (1990s), one line in the
# 1970s; "Solution 8,650", or "SOLUTION TO PUZZLE" over "No. 2,765".
titles, sols = f.ft_headings([line("CROSSWORD", 2429, 2957), line("No. 8,650 Set by DANTE", 2417, 3017),
                              line("Solution 8,649", 2691, 3958),
                              line("Solution to Saturday's prize puzzle on Saturday January 14.", 2253, 4293),
                              line("No. 1,234 reasons to buy", 900, 100)])
check("1990s FT title over its number line, setter read, box the grid's width; prize-date line no heading",
      ([(8650, "Dante", f.FT_GRID_SPAN)], [8649]),
      ([(n, s, b[2] - b[0]) for n, b, s in titles], [n for n, _ in sols]))
titles, sols = f.ft_headings([line("F.T. CROSSWORD PUZZLE No. 2,766", 200, 2841),
                              line("SOLUTION TO PUZZLE", 573, 4049), line("No. 2,765", 656, 4073)])
check("1970s FT title on one line, solution number on the line under", ([2766], [2765]),
      ([n for n, _, _ in titles], [n for n, _ in sols]))
check("FT numbers the dates imply, and our first ftcryptic's", [True, True, True, False],
      [abs(n - f.ft_expected_number(datetime.date.fromisoformat(d))) <= f.NUMBER_SLACK
       for d, n in [("1975-05-01", 2766), ("1992-06-11", 7870), ("2009-11-12", 13232), ("1995-01-03", 19742)]])

# match_canberra(): the reading sharing the clue list, printed first, same grid.
def puzzle(pid, date, clues, cols=3):
    return {"id": pid, "date": date, "dimensions": {"cols": cols, "rows": 3},
            "entries": [{"number": i + 1, "direction": "across", "position": {"x": 0, "y": i},
                         "length": cols, "clue": {"text": t}} for i, t in enumerate(clues)]}
words = [chr(97 + i // 26) + chr(97 + i % 26) + "x" for i in range(30)]
clues = [" ".join(words[k * 10:k * 10 + 10]) for k in range(3)]
src = Path(os.environ["TMP"]) / "src"; src.mkdir()
(src / "times-13677.json").write_text(json.dumps(puzzle("times-13677", "1974-05-02", clues)))
(src / "times-13678.json").write_text(json.dumps(puzzle("times-13678", "1974-05-03", ["quite other words here and there", "x y z", "q r s"])))
can = Path(os.environ["TMP"]) / "canberra"; (can / "1975").mkdir(parents=True)
misread = [clues[0].replace("abx", "abz"), clues[1], clues[2]]
(can / "1975" / "canberra-750101.json").write_text(json.dumps(puzzle("canberra-750101", "1975-01-01", misread)))
(can / "1975" / "canberra-750102.json").write_text(json.dumps(puzzle("canberra-750102", "1975-01-02", clues, cols=4)))
(can / "1973").mkdir()
(can / "1973" / "canberra-730101.json").write_text(json.dumps(puzzle("canberra-730101", "1973-01-01", clues)))
import io
got = f.match_canberra(src, write=False, out=io.StringIO(), canberra=can)
check("a reprint matched through a misread; another grid, or a print before the London one, is not", {"canberra-750101": "times-13677"}, got)

# read_solution(): the solution grid under its heading, answers keyed as
# trove_solution_ocr.fill() looks them up, nothing from a grid of other blocks.
from PIL import Image, ImageDraw
ed = Path(os.environ["TMP"]) / "ed"; ed.mkdir()
im = Image.new("L", (1200, 1400), 255)
ImageDraw.Draw(im).rectangle((110, 160, 460, 510), fill=0)
im.save(ed / "leaf_0003.jpg")
f.CROPS = Path(os.environ["TMP"]) / "crops"
import trove_solution_ocr
seen = []
def fake(path, grid):
    seen.append(Image.open(path).size)
    return {(1, "across"): "ABC"}, {"blocks": stats_blocks}
trove_solution_ocr.read_answers = fake
sol = {"dir": ed, "leaf": 3, "number": 7, "box": (100, 100, 400, 140)}
stats_blocks = 1.0
got, _ = f.read_solution(sol, ["..."])
check("solution answers keyed as fill() reads them, the grid cropped tight at 3x",
      ({"1-across": "ABC"}, (352 * 3, 352 * 3)), (got, seen[0]))
stats_blocks = 0.9
got, info = f.read_solution(sol, ["..."])
check("a solution grid whose blocks are not the puzzle's gives no answers", ({}, True), (got, "refused" in info))

check("editions from --file-from's year go to the corpus, earlier ones to --out",
      ["out", None, None, "out", None],
      [f.destination("out", 1983, "1982-12-31"), f.destination("out", 1983, "1983-01-03"),
       f.destination(None, 1983, "1975-01-01"), f.destination("out", None, "1999-01-01"),
       f.destination(None, None, "1999-01-01")])

check("a puzzle with a blank clue goes to --out or nowhere, never the corpus",
      ["out", False, "out"],
      [f.destination("out", 1983, "1990-01-01", False), f.destination(None, None, "1990-01-01", False),
       f.destination("out", None, "1975-01-01", False)])
check("complete() is every clue having text", [True, False],
      [f.complete({"entries": [{"clue": {"text": "A"}}, {"clue": {"text": "B"}}]}),
       f.complete({"entries": [{"clue": {"text": "A"}}, {"clue": {"text": " "}}]})])

import fetch_puzzle
ed_dir = Path(os.environ["TMP"]) / "runcache" / "NewsUK1990UKEnglish" / "1990-01-01_1"
ed_dir.mkdir(parents=True)
wrote = []
saved = (f.edition_dirs, f.scan, f.read_puzzle, f.input_hash, f.held_numbers,
         fetch_puzzle.puzzle_path, fetch_puzzle.write_puzzle_file)
f.edition_dirs = lambda cache, paper=None: [ed_dir]
f.scan = lambda d: {"date": "1990-01-01", "item": "NewsUK1990UKEnglish", "solutions": [],
                    "puzzles": [{"number": 18179, "leaf": 1, "box": None},
                                {"number": 18180, "leaf": 2, "box": None}]}
def fake_read(d, found, hit, solutions):
    blank = hit["number"] == 18179
    return {"number": hit["number"]}, {"id": f"times-{hit['number']}", "number": hit["number"],
            "entries": [{"clue": {"text": "Top"}}, {"clue": {"text": "" if blank else "Left"}}]}
f.read_puzzle = fake_read
f.input_hash = lambda d, code: "h"
f.held_numbers = lambda series="times": set()
fetch_puzzle.puzzle_path = lambda series, n: Path(os.environ["TMP"]) / "corpus" / f"times-{n}.json"
fetch_puzzle.write_puzzle_file = lambda path, puzzle, generator: wrote.append(path.parent.name + "/" + path.name)
rows = f.run(cache=ed_dir.parent.parent, puzzles=Path(os.environ["TMP"]) / "unfiled", file_from=1983,
             source=Path(os.environ["TMP"]) / "src", out=open(os.devnull, "w"))
check("run files the complete puzzle in the corpus and the one with a blank clue in --out",
      ["unfiled/times-18179.json", "corpus/times-18180.json"], sorted(wrote, reverse=True))
wrote.clear()
rows = f.run(cache=ed_dir.parent.parent, ledger=Path(os.environ["TMP"]) / "l2.jsonl",
             source=Path(os.environ["TMP"]) / "src", out=open(os.devnull, "w"))
check("without --out a puzzle with a blank clue is written nowhere", ["corpus/times-18180.json"], wrote)
(f.edition_dirs, f.scan, f.read_puzzle, f.input_hash, f.held_numbers,
 fetch_puzzle.puzzle_path, fetch_puzzle.write_puzzle_file) = saved

import cross_validate
a = cross_validate.ArchiveOrg()
check("archiveorg does not compare a file it filed with itself", [False, True],
      [a.covers({"source": {"acquiredBy": "tools/file_archive_org_puzzles.py"}}),
       a.covers({"source": {"acquiredBy": "tools/acquire_book.py"}})])
# A retrained Tesseract model gets its own cache name; RapidOCR's keep theirs.
model = Path(os.environ["TMP"]) / "m.traineddata"
saved = dict(f.TESS_MODELS), dict(f._MODEL_HASHES)
f.TESS_MODELS["times"] = model
for body in (b"old", b"new"):
    model.write_bytes(body)
    f._MODEL_HASHES.clear()
    check(f"reader_key hashes the model ({body.decode()})", True,
          f.reader_key("times").startswith("times-"))
    if body == b"old":
        old_key = f.reader_key("times")
check("a changed model changes the cache name", True, f.reader_key("times") != old_key)
check("RapidOCR readers keep their name", "en5", f.reader_key("en5"))
f.TESS_MODELS.clear(); f.TESS_MODELS.update(saved[0])
f._MODEL_HASHES.clear(); f._MODEL_HASHES.update(saved[1])

print(f"FAILS {fails}")
EOF
)
echo "$out"
echo "$out" | grep -q '^FAILS 0$' || { echo "test_file_archive_org_puzzles: failed"; exit 1; }
echo "test_file_archive_org_puzzles: all passed"
