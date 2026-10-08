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
sys.exit(1 if fails else 0)
PY
