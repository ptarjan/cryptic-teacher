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
check("both readers' one non-word is not kept", None, f.agree("Nurse hoiding note", stream)[0])

check("a capital only one reader saw inside the clue dropped", ("What is stated", "settled by the dictionary"),
      f.agree("What Is stated", f.tokens("27 What is stated (9)")))
got, _ = f.reconcile({"25-across": ("As worn by agitator in back- street", "8", None)},
                     "25 As worn by agitator in back-\nstreet (8)")
check("a word hyphenated over a line end keeps its hyphen, no space", "As worn by agitator in back-street",
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
check("a non-word all three readings have kept", "Get production up sevenfoldx",
      f.agree("Get production up sevenfoldx", [f.marked("Get production up sevenfoldx")] * 2)[0])
got, blank = f.reconcile({"8-down": ("Wisdom shown by, school-head", "10", None)},
                         ["8 Wisdom shown by school-head (10)", "8 Wisdom shown by school-head (10)"])
check("reconcile votes with every reading it is given", "Wisdom shown by school-head", got["8-down"][0])

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

import cross_validate
a = cross_validate.ArchiveOrg()
check("archiveorg does not compare a file it filed with itself", [False, True],
      [a.covers({"source": {"acquiredBy": "tools/file_archive_org_puzzles.py"}}),
       a.covers({"source": {"acquiredBy": "tools/acquire_book.py"}})])
print(f"FAILS {fails}")
EOF
)
echo "$out"
echo "$out" | grep -q '^FAILS 0$' || { echo "test_file_archive_org_puzzles: failed"; exit 1; }
echo "test_file_archive_org_puzzles: all passed"
