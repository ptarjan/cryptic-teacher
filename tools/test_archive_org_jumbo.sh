#!/bin/bash
# Does tools/archive_org_jumbo.py take the Jumbo's number from the prize text
# (the banner's is cut short), read "SOLUTION TO JUMBO 17 8" as 178, look for
# an unheaded solution in the edition two weeks on, blank a light whose count
# is short of it, keep the clue columns left of the Times Two's, and match a
# solution grid by its blocks when its middle prints grey?
#
#     bash tools/test_archive_org_jumbo.sh
#
# Pure functions on made-up words and drawn grids: no scan, no OCR, nothing written.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

out=$(cd "$REPO/tools" && python3 - <<'EOF'
import numpy as np
from pathlib import Path
import archive_org_jumbo as aj
import trove_solution_ocr as so

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

check("banner number", 174, aj.number(aj.TITLE.match("JUMBO CROSSWORD 174")))
check("prize text number", 177, aj.number(aj.ENTRY.search(
    "J should be sent to: Jumbo Crossword 177, The Times ,")))
check("solution heading with a split number", 178, aj.number(aj.SOLUTION.match("SOLUTION TO JUMBO 17 8")))
check("solution heading with CROSSWORD", 132, aj.number(aj.SOLUTION.match("SOLUTION TO JUMBO CROSSWORD 132")))
check("a book advert is no heading", None, aj.TITLE.match("The Times Jumbo Crosswords Book 3"))

# The edition two weeks on is searched when no heading names the solution.
a, b, c = Path("a"), Path("b"), Path("c")
scans = {a: {"date": "1998-07-25", "puzzles": [{"number": 177}], "solutions": [{"number": 175, "leaf": 90}]},
         b: {"date": "1998-08-08", "puzzles": [{"number": 179}], "solutions": []},
         c: {"date": "1998-07-11", "puzzles": [{"number": 175}], "solutions": []}}
sols = aj.solutions_of(scans)
check("headed solution", (a, 90), (sols[175]["dir"], sols[175]["leaf"]))
check("unheaded solution two weeks on, by image", (b, False), (sols[177]["dir"], "leaf" in sols[177]))
check("no edition two weeks on, no solution", False, 179 in sols)

# Lights: a short count blanks; a linked clue's longer count is dropped; an
# unread light is blank.
grid = ["....", ".#.#", "....", ".#.#"]
laid = {"1-across": ("Good clue", "4", None), "2-down": ("Linked head", "4,3", None),
        "1-down": ("Short count", "3", None)}
got, blank = aj.lay_on(laid, grid)
check("fitting clue kept", ("Good clue", "4"), got["1-across"][:2])
check("linked clue keeps text, loses count", ("Linked head", None), got["2-down"][:2])
check("short count blanked", "", got["1-down"][0])
check("short count says why", True, "short" in blank["1-down"])
check("unread light blank", ("", "no clue read for it"), (got["3-across"][0], blank["3-across"]))

# The clue box ends a little past the DOWN column, before the Times Two.
class Img:
    width, height = 3296, 4672
words = [(1453, 2612, 1549, 2631, "ACROSS"), (1852, 2614, 1931, 2632, "DOWN")]
box, split = aj.clue_box(Img, (224, 2982, 1412, 4146), {"box": (558, 2851, 1345, 2890)}, words)
check("columns split left of DOWN", 1832, split)
check("box right of the grid", 1427, box[0])
check("box ends past DOWN's column", True, 2300 < box[2] < 2450)
check("no headings: 0.8 of the grid", int(1412 + 0.8 * 1188),
      aj.clue_box(Img, (224, 2982, 1412, 4146), {"box": (558, 2851, 1345, 2890)})[0][2])

# A drawn 5x5 solution grid: frame and rules 3px, cells 40px, blocks solid,
# lights holding a heavy letter, and the middle row's block printed grey
# (a third of it paper).
n, p = 5, 40
blocks = {(1, 1), (1, 3), (3, 1), (3, 3), (2, 2)}
img = np.full((n * p + 3, n * p + 3), 255, np.uint8)
for k in range(n + 1):
    img[k * p:k * p + 3, :] = 0
    img[:, k * p:k * p + 3] = 0
for r in range(n):
    for c in range(n):
        y, x = r * p + 3, c * p + 3
        if (r, c) in blocks:
            img[y:y + p - 3, x:x + p - 3] = 0
            if r == 2:
                # Every third line paper: a third of the block reads white.
                img[y:y + p - 3:3, x:x + p - 3] = 255
        else:
            img[y + 10:y + 28, x + 12:x + 26] = 0
# Scan noise: real scans have no two-level histogram, and Otsu's cut needs one.
img = np.clip(img.astype(int) + np.random.default_rng(1).integers(-20, 21, img.shape), 0, 255).astype(np.uint8)
want = ["".join("#" if (r, c) in blocks else "." for c in range(n)) for r in range(n)]
lat = so.lattice(img, n, tight=True)
check("tight lattice from the frame", (0.0, 0.0), (round(lat[0]), round(lat[1])))
check("tight lattice pitch", True, abs(lat[2] - p) < 1 and abs(lat[3] - p) < 1)
check("its own blocks fit", 1.0, aj.block_fit(img, want, lat))
other = list(want)
other[0] = "#...#"
check("another grid's blocks do not", True, aj.block_fit(img, other, lat) < 1.0)

print("FAILS", fails)
EOF
)
echo "$out"
echo "$out" | grep -q "^FAILS 0$"
