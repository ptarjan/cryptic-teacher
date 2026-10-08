#!/bin/bash
# Does tools/listener_grid.py read a drawn grid's size, blocks and bars back,
# and number it as reconstruct_grid.light_cells does?
#
#     bash tools/test_listener_grid.sh
#
# A page is drawn: prose lines, a column rule and a boxed advertisement (no
# grid), and a 7 x 9 grid (not square, not symmetric) with thin rules, thick
# bars, a block and a number in each cell's corner, turned a fraction of a
# degree. The reader must find exactly one grid and give back the rows drawn.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHONPATH="$REPO/tools" python3 - <<'PY'
import sys
import numpy as np
from PIL import Image, ImageDraw
import listener_grid as lg

ROWS = ("..r..b..#",
        "b...+....",
        "...r..r..",
        "#b.......",
        "..b..r.b.",
        "....r....",
        ".r.......")
P, X0, Y0 = 90, 300, 900
img = Image.new("L", (1800, 2400), 235)
d = ImageDraw.Draw(img)
for y in range(150, 750, 40):                      # prose
    for x in range(100, 1600, 70):
        d.text((x, y), "word", fill=30)
d.line((900, 1700, 900, 2300), fill=20, width=3)    # a column rule
d.rectangle((1000, 1800, 1700, 2250), outline=20, width=4)  # an advert's box
nr, nc = len(ROWS), len(ROWS[0])
for i in range(nr + 1):
    d.line((X0, Y0 + i * P, X0 + nc * P, Y0 + i * P), fill=25, width=3)
for j in range(nc + 1):
    d.line((X0 + j * P, Y0, X0 + j * P, Y0 + nr * P), fill=25, width=3)
d.rectangle((X0 - 3, Y0 - 3, X0 + nc * P + 3, Y0 + nr * P + 3), outline=25, width=6)
for r, row in enumerate(ROWS):
    for c, ch in enumerate(row):
        x, y = X0 + c * P, Y0 + r * P
        if ch == "#":
            d.rectangle((x, y, x + P, y + P), fill=20)
        if ch in "r+":
            d.rectangle((x + P - 5, y, x + P + 5, y + P), fill=25)
        if ch in "b+":
            d.rectangle((x, y + P - 5, x + P, y + P + 5), fill=25)
for (n, _), cells in sorted(lg.rg.light_cells(ROWS).items()):
    y, x = cells[0]
    d.text((X0 + x * P + 6, Y0 + y * P + 5), str(n), fill=20)
img = img.rotate(0.3, fillcolor=235)

fails = 0
grids = [g for g in lg.find_grids(np.asarray(img, dtype=np.uint8)) if g["rows"]]
def check(what, want, got):
    global fails
    print(("ok   " if want == got else "FAIL ") + what + ("" if want == got else f": expected {want}, got {got}"))
    fails += want != got
check("one grid on the page", 1, len(grids))
if grids:
    check("rows, blocks and bars read back", list(ROWS), grids[0]["rows"])
    check("an empty grid is not a report's filled one", True, grids[0]["filled"] < 0.5)
    check("numbers are light_cells'", lg.numbers(list(ROWS)), lg.numbers(grids[0]["rows"]))

# A faint bar (a third wider than a rule, under BAR_RATIO) reads as a rule;
# one whose far cell starts no other light shows in the numbering, so
# the printed numbers put it back.
FAINT = (5, 4, "r")
img = Image.new("L", (1800, 2400), 235)
d = ImageDraw.Draw(img)
d.rectangle((X0 - 3, 297, X0 + nc * P + 3, 303 + nr * P), outline=25, width=6)
for y in range(1200, 1800, 40):                    # prose, so the page has its ink levels
    for x in range(100, 1600, 70):
        d.text((x, y), "word", fill=30)
for i in range(nr + 1):
    d.line((X0, 300 + i * P, X0 + nc * P, 300 + i * P), fill=25, width=3)
for j in range(nc + 1):
    d.line((X0 + j * P, 300, X0 + j * P, 300 + nr * P), fill=25, width=3)
for r, row in enumerate(ROWS):
    for c, ch in enumerate(row):
        x, y = X0 + c * P, 300 + r * P
        if ch == "#":
            d.rectangle((x, y, x + P, y + P), fill=20)
        faint = (r, c, "r") == FAINT
        if ch in "r+":
            d.rectangle((x + P - (2 if faint else 5), y, x + P + (1 if faint else 5), y + P), fill=25)
        if ch in "b+":
            d.rectangle((x, y + P - 5, x + P, y + P + 5), fill=25)
found = lg.find_grids(np.asarray(img, dtype=np.uint8))
grids = [g for g in found if g["rows"]]
check("one grid on the faint page", 1, len(grids))
if grids:
    g = grids[0]
    check("the faint bar reads as a rule", ".", g["rows"][5][4])
    printed = lg.starts(list(ROWS))
    f = lg.fit(g, {"ch": printed, "en5": printed})
    check("the printed numbers put the faint bar back", list(ROWS), f["rows"])
    check("its numbering is exact", (True, []), (f["exact"], f["disagree"]))
    last = max(printed)
    wrong = {**printed, last: printed[last] + 1}
    f = lg.fit(g, {"ch": wrong, "en5": wrong})
    check("a number both readers misread makes it not exact", (False, [last]), (f["exact"], f["disagree"]))
    noisy = {**printed, (6, 8): 1, (5, 8): 99}
    f = lg.fit(g, {"ch": noisy, "en5": noisy})
    check("a stray 1 late in the grid and a number above its lights are dropped", (True, []), (f["exact"], f["disagree"]))
# A bar that ends one light and starts another: no one side helps alone.
truth = [".rb..", ".....", ".....", ".....", "....."]
two = {"rows": ["....."] * 5, "thin": 1.0,
       "sides": {**{(r, c, d): 1.0 for r in range(5) for c in range(5) for d in "rb"
                    if (d == "r" and c < 4) or (d == "b" and r < 4)},
                 (0, 1, "r"): 1.3, (0, 2, "b"): 1.3}}
want = lg.starts(truth)
f = lg.fit(two, {"ch": want, "en5": want})
check("two unsure sides set together when no single flip helps", (truth, True), (f["rows"], f["exact"]))
got = {(0, 0): 23, (0, 3): 24, (0, 5): 75, (1, 0): 26, (1, 2): 27, (2, 0): 2, (2, 4): 28}
check("in_order keeps the run rising in reading order",
      {(0, 0): 23, (0, 3): 24, (1, 0): 26, (1, 2): 27, (2, 4): 28}, lg.in_order(got, 60))
check("in_order drops numbers above the most lights", {(0, 0): 23}, lg.in_order({(0, 0): 23, (0, 1): 61}, 60))
check("in_order keeps neither cell of a number read twice where both fit (No 17's 40 read 41)",
      {(10, 3): 37, (12, 0): 42}, lg.in_order({(10, 3): 37, (11, 0): 41, (11, 6): 41, (12, 0): 42}, 100))
check("but keeps the one that fits when the other is out of order (No 9's 12 read 2)",
      {(0, 1): 1, (0, 3): 2, (1, 10): 11}, lg.in_order({(0, 1): 1, (0, 3): 2, (1, 10): 11, (2, 1): 2}, 100))

# A row and a column mostly blocks (No 15's last row is 9 blocks of 13):
# the band of blocks covers as much as a rule, and its edges are the rules.
BANDED = (".....#.",
          ".#.#...",
          ".......",
          "#.#.#.#",
          ".......",
          "##.###.")
img = Image.new("L", (1400, 1400), 235)
d = ImageDraw.Draw(img)
for y in range(1000, 1300, 40):                    # prose, so the page has its ink levels
    for x in range(100, 1200, 70):
        d.text((x, y), "word", fill=30)
nr, nc = len(BANDED), len(BANDED[0])
for i in range(nr + 1):
    d.line((X0, 200 + i * P, X0 + nc * P, 200 + i * P), fill=25, width=3)
for j in range(nc + 1):
    d.line((X0 + j * P, 200, X0 + j * P, 200 + nr * P), fill=25, width=3)
for r, row in enumerate(BANDED):
    for c, ch in enumerate(row):
        if ch == "#":
            d.rectangle((X0 + c * P, 200 + r * P, X0 + (c + 1) * P, 200 + (r + 1) * P), fill=20)
grids = [g for g in lg.find_grids(np.asarray(img, dtype=np.uint8)) if g["rows"]]
check("a grid with a row of blocks is found", 1, len(grids))
if grids:
    check("its rows, the band of blocks one row", list(BANDED), grids[0]["rows"])

# A map-shaped grid (No 3's India, No 4's England): cells inside a stepped
# outline, paper around it. Few rules cross the whole box, so they are
# measured against the outline's own width; the cells off it are blocks.
MAP = ("##...###",
       "#.r...##",
       "........",
       "...b....",
       "##.....#",
       "###..###",
       "###r.###")
img = Image.new("L", (1400, 1400), 235)
d = ImageDraw.Draw(img)
for y in range(1050, 1300, 40):                    # prose, so the page has its ink levels
    for x in range(100, 1200, 70):
        d.text((x, y), "word", fill=30)
for r, row in enumerate(MAP):
    for c, ch in enumerate(row):
        if ch == "#":
            continue
        x, y = X0 + c * P, 200 + r * P
        d.rectangle((x, y, x + P, y + P), outline=25, width=3)
        if ch in "r+":
            d.rectangle((x + P - 5, y, x + P + 5, y + P), fill=25)
        if ch in "b+":
            d.rectangle((x, y + P - 5, x + P, y + P + 5), fill=25)
img = img.rotate(0.3, fillcolor=235)
grids = [g for g in lg.find_grids(np.asarray(img, dtype=np.uint8)) if g["rows"]]
check("a map-shaped grid is found", 1, len(grids))
if grids:
    check("its cells read back, those off the outline blocks", list(MAP), grids[0]["rows"])
    check("its numbers are light_cells'", lg.numbers(list(MAP)), lg.numbers(grids[0]["rows"]))

# A rectangle whose frame breaks for a third of a cell (No 1's report on
# No 3's page, its right frame faded beside row 1): the paper outside does
# not leak in through the break, so every cell stays a cell.
img = Image.new("L", (1400, 1400), 235)
d = ImageDraw.Draw(img)
for y in range(1050, 1300, 40):                    # prose, so the page has its ink levels
    for x in range(100, 1200, 70):
        d.text((x, y), "word", fill=30)
for i in range(7):
    d.line((X0, 200 + i * P, X0 + 6 * P, 200 + i * P), fill=25, width=3)
    d.line((X0 + i * P, 200, X0 + i * P, 200 + 6 * P), fill=25, width=3)
for r in range(6):
    for c in range(6):
        d.text((X0 + c * P + 40, 200 + r * P + 40), "E", fill=20)
d.rectangle((X0 + 6 * P - 3, 200 + P + 30, X0 + 6 * P + 3, 200 + P + 60), fill=235)  # the break
img = img.rotate(0.3, fillcolor=235)
grids = [g for g in lg.find_grids(np.asarray(img, dtype=np.uint8)) if g["rows"]]
check("a rectangle with a break in its frame is found", 1, len(grids))
if grids:
    check("every cell of it stays a cell", ["......"] * 6, grids[0]["rows"])

# A small scan's two-digit number fills most of its corner: only the rules
# along the corner's edges are painted out, never a stroke of the number.
tile = np.full((40, 60), 235, np.uint8)
tile[0:3, :] = 20                                  # the rule above
tile[:, 0:3] = 20                                  # the rule left
tile[12, 8:48] = 20                                # the tops of "75", 2/3 of the width
tile[12:30, 30] = 20
got = lg.corner(tile, [0, 80], [0, 97], 0, 0, 128)
check("the rules are painted out", (False, False), (bool((got[0:3, 10:] < 128).any()), bool((got[10:, 0:3] < 128).any())))
check("the number's stroke is kept", True, bool((got[12, 8:48] < 128).all()))

# A grid whose two-letter runs go unnumbered (No 15, "no clues are given for
# words of two letters"): the fit bars them shut, so light_cells numbers
# the rows it gives as the page does.
SHORT = ["#...#",
         "..#..",
         "....."]
grid = {"rows": SHORT, "thin": 1.0,
        "sides": {(r, c, d): 1.0 for r in range(3) for c in range(5) for d in "rb"
                  if SHORT[r][c] != "#" and ((d == "r" and c < 4 and SHORT[r][c + 1] != "#")
                                             or (d == "b" and r < 2 and SHORT[r + 1][c] != "#"))}}
printed = lg.starts(SHORT, 3)
f = lg.fit(grid, {"ch": printed, "en5": printed})
check("unnumbered two-letter runs fit exactly", (3, True), (f["shortest"], f["exact"]))
check("and are barred shut, so light_cells numbers as printed", printed, lg.starts(f["rows"]))
check("no light of two is left", [], [k for k, cells in lg.rg.light_cells(f["rows"]).items() if len(cells) < 3])
# A grid that leaves one 2-cell run unnumbered but clues another (No 103:
# "10. Last two letters of above"): the run read with the next number at
# its start stays a light; the other is barred shut. Sides are all certain
# rules here, so only the numbering can move.
MIX = [".....",
       ".#..#",
       ".....",
       "#..#.",
       "....."]


def certain(rows):
    """Every side a certain rule, so only the numbering can move."""
    h, w = len(rows), len(rows[0])
    return {"rows": rows, "thin": 1.0,
            "sides": {(r, c, d): 0.5 for r in range(h) for c in range(w) for d in "rb"
                      if rows[r][c] != "#" and ((d == "r" and c < w - 1 and rows[r][c + 1] != "#")
                                                or (d == "b" and r < h - 1 and rows[r + 1][c] != "#"))}}


printed = lg.starts(lg.closed(MIX, 3, {(1, 2)}))     # the run at r1c2 numbered, r3c1's not
f = lg.fit(certain(MIX), {"ch": printed, "en5": printed})
runs = {cells[0]: len(cells) for (_, d), cells in lg.rg.light_cells(f["rows"]).items() if d == "across"}
check("a 2-cell run printed with the next number stays a light", (True, 2), (f["exact"], runs.get((1, 2))))
check("and the unnumbered one is barred shut", (None, printed), (runs.get((3, 1)), lg.starts(f["rows"])))
base = lg.starts(MIX, 3)
stray = {**base, (3, 1): 1}
check("a 2-cell run read with a number out of turn stays shut (mirror)", base,
      lg.starts(MIX, 3, {c: {n} for c, n in stray.items()}))

# The printer set a number a cell off its light's start (No 9's 8, left of
# 8-down): the start reads blank and the cell starts nothing.
OPEN3 = ["#..", "...", "..."]
assert lg.starts(OPEN3) == {(0, 1): 1, (0, 2): 2, (1, 0): 3, (2, 0): 4}
off = {(0, 1): 1, (0, 2): 2, (1, 1): 3, (2, 0): 4}
f = lg.fit(certain(OPEN3), {"ch": off, "en5": off})
check("a number printed a cell off its start is moved, not a disagreement", (True, [], [(1, 1)]),
      (f["exact"], f["disagree"], f["moved"]))
far = {(0, 1): 1, (0, 2): 2, (1, 2): 3, (2, 0): 4}
f = lg.fit(certain(OPEN3), {"ch": far, "en5": far})
check("one two cells off stays a disagreement (mirror)", ([(1, 2)], []), (f["disagree"], f["moved"]))

# No 0's 9x9 numbers every square by its place (width * row + col + 1),
# not its lights' starts: an exact fit of that kind is taken.
place = {(r, c): 3 * r + c + 1 for r in range(3) for c in range(3) if OPEN3[r][c] != "#"}
f = lg.fit(certain(OPEN3), {"ch": place, "en5": {**place, (2, 2): 1}})
check("squares numbered by their place fit as such", (True, "position", 7),
      (f["exact"], f.get("numbering"), f["agreed"]))
check("one read off its place is no positional fit (mirror)", 0,
      lg.positional(OPEN3, {"ch": {**place, (2, 2): 8}, "en5": {**place, (2, 2): 8}}, 4))
OPEN = ["...", "...", "..."]
starts_only = {(0, 0): 1, (0, 1): 2, (0, 2): 3, (1, 0): 4}
check("light-start numbers that equal their places are no positional fit (mirror)", 0,
      lg.positional(OPEN, {"ch": starts_only, "en5": starts_only}, 5))
sys.exit(1 if fails else 0)
PY
