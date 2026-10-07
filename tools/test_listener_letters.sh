#!/bin/bash
# Does trove_solution_ocr.read_grid_letters read the letters of a drawn,
# filled Listener report grid back through listener_grid's lattice?
#
#     bash tools/test_listener_letters.sh
#
# A 5 x 5 barred grid is drawn filled with words (a bar ends 1A's row early)
# and found by listener_grid.find_grids; its lattice and light_cells are
# handed to the letter reader, which must give every cell's letter back.
# Skipped without RapidOCR.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHONPATH="$REPO/tools" python3 - <<'PY'
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import listener_grid as lg
import trove_solution_ocr as ts

if ts.available():
    print("skip: " + ts.available())
    sys.exit(0)
ROWS = ("..r..", ".....", ".....", ".....", ".....")
WORDS = ("CATOD", "OTTER", "PEARL", "ERNST", "STAGE")
P, X0, Y0 = 100, 200, 300
img = Image.new("L", (1000, 1000), 235)
d = ImageDraw.Draw(img)
font = ImageFont.load_default(size=60)
for i in range(6):
    d.line((X0, Y0 + i * P, X0 + 5 * P, Y0 + i * P), fill=25, width=3)
    d.line((X0 + i * P, Y0, X0 + i * P, Y0 + 5 * P), fill=25, width=3)
d.rectangle((X0 + 3 * P - 5, Y0, X0 + 3 * P + 5, Y0 + P), fill=25)
for r, word in enumerate(WORDS):
    for c, ch in enumerate(word):
        d.text((X0 + c * P + P // 2, Y0 + r * P + P // 2), ch, fill=20, font=font, anchor="mm")
gray = np.asarray(img, dtype=np.uint8)
fails = 0
def check(what, want, got):
    global fails
    print(("ok   " if want == got else "FAIL ") + what + ("" if want == got else f": expected {want}, got {got}"))
    fails += want != got
grids = [g for g in lg.find_grids(gray) if g["rows"]]
check("one filled grid", (1, True), (len(grids), bool(grids) and grids[0]["filled"] > 0.5))
if grids:
    lts = lg.rg.light_cells(list(ROWS))
    out = ts.read_grid_letters(gray, *grids[0]["lattice"], lts)
    check("every letter read back", list(WORDS), out["grid"])
    check("1A stops at the bar", "CAT", out["lights"][(1, "across")])
sys.exit(1 if fails else 0)
PY
