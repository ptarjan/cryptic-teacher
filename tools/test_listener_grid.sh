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
    wrong = dict(printed)
    wrong[(6, 1)] = 99
    f = lg.fit(g, {"ch": wrong, "en5": wrong})
    check("a number both readers misread makes it not exact", (False, [(6, 1)]), (f["exact"], f["disagree"]))
sys.exit(1 if fails else 0)
PY
