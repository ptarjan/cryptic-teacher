#!/bin/bash
# Does nation_key read The Nation's answers from the setters' printed solution
# and Braze's posts, and only the letters they really spell?
#
#     bash tools/test_nation_key.sh
#
# Shapes from the held pages: "ABSO(LUTE)LY (LA boys anag.)", "[s]TIFFIN[g]",
# "[s/N]-EEDLESS", "14 2 defs." (14's entry, not a 2), "13 & 10D pun", and
# "anag."/"hidden" giving no letters; Braze's "PU}L{SE" and "_UTTER". A
# "hidden" light is read off its clue only where one run fits its crossings.
set -uo pipefail
cd "$(dirname "$0")/.."
out=$(PYTHONPATH="$PWD/tools" python3 - <<'PY'
import nation_key as K
lines = ["23 Weakling (6)", "SOLUTION TO PUZZLE NO. 3272",
         "ACROSS 1 ABSO(LUTE)LY (LA boys anag.) 6 hidden 10 DOG + MA",
         "13 & 10D pun 14 2 defs. 16 [s/N]-EEDLESS",
         "DOWN 1 AB + DUCT 2 [s]TIFFIN[g] 9 dream is anag. 15 E(URA[l] + SI)A (is rev., &lit.)",
         "Puzzled? Read more"]
number, text = K.solution_text(lines)
print("NUMBER", number)
parts = K.sections(text)
across = K.items(parts["across"], [1, 6, 10, 13, 14, 16])
down = K.items(parts["down"], [1, 2, 9, 15])
for n, t in {**{f"{k}a": v for k, v in across.items()}, **{f"{k}d": v for k, v in down.items()}}.items():
    print(n, K.key_letters(t))
post = """<style>.post-body {}</style><div class='post-body entry-content'>Across<br>
21a<br>PU}L{SE<br>PU{R}SE ("pocketbook")<br>7d<br>_UTTER<br>_m_UTTER<br>
28a<br>MUSTY<br>Pun<br></div><div class='post-footer'>"""
print("BRAZE", sorted(K.braze_answers(post).items()))

# A 3x3 corner: 1-across HAT (keyed), 1-down HEN (keyed), 2-down "hidden" in
# its clue, 4-across a light every cell of which is crossed.
def light(n, d, x, y, length, clue):
    return {"number": n, "direction": d, "position": {"x": x, "y": y},
            "length": length, "clue": {"text": clue}}
entries = [light(1, "across", 0, 0, 3, ""), light(1, "down", 0, 0, 3, ""),
           light(3, "down", 2, 0, 3, "Pet a pig, perhaps"),
           light(4, "across", 0, 2, 3, "")]
entries[0]["solution"], entries[1]["solution"] = "HAT", "HEN"
print("DERIVED", K.derive(entries, {"3-down": "hidden"}),
      [e.get("solution") for e in entries])
entries = [light(1, "across", 0, 0, 3, ""), light(3, "down", 2, 0, 3, "Tapir")]
entries[0]["solution"] = "HAT"
print("OPEN", K.derive(entries, {"3-down": "rev. hidden"}), entries[1].get("solution"))

# A filed puzzle annotated before its key: a spelling the key agrees with is
# dropped (derived once the answer is filed); one it contradicts keeps the
# light open.
held = {"entries": [light(1, "across", 0, 0, 3, ""), light(1, "down", 0, 0, 3, "")]}
held["entries"][0]["annotation"] = {"spelling": "H AT"}
held["entries"][1]["annotation"] = {"spelling": "HIM"}
keyed = {"entries": [dict(light(1, "across", 0, 0, 3, ""), solution="HAT"),
                     dict(light(1, "down", 0, 0, 3, ""), solution="HEN")]}
merged = K.merge_filed(held, keyed)
print("CONTRADICTED", K.settle_spellings(merged["entries"]))
print("MERGED", [(e.get("solution"), e["annotation"]) for e in merged["entries"]])
moved = {"entries": [light(1, "across", 0, 1, 3, ""), light(1, "down", 0, 0, 3, "")]}
print("MOVED", K.merge_filed(moved, keyed))
PY
)
fail=0
expect() {
  grep -qxF -- "$1" <<<"$out" || { echo "FAIL: expected line: $1"; fail=1; }
}
expect "NUMBER 3272"
expect "1a ABSOLUTELY"
expect "6a None"
expect "10a DOGMA"
expect "13a None"
expect "14a None"
expect "16a NEEDLESS"
expect "1d ABDUCT"
expect "2d TIFFIN"
expect "9d None"
expect "15d EURASIA"
expect "BRAZE [(('across', 21), 'PULSE'), (('across', 28), 'MUSTY'), (('down', 7), 'UTTER')]"
# 3-down: the clue's letters hold one run T?? under HAT's T: TAP.
# 4-across is then N?P: its middle cell is uncrossed, so it stays open.
expect "DERIVED ['3-down'] ['HAT', 'HEN', 'TAP', None]"
# Reversed, "Tapir" reads RIPAT: no three-letter run starts with T, so
# 3-down stays open.
expect "OPEN [] None"
expect "MERGED [('HAT', {}), (None, {'spelling': 'HIM'})]"
expect "MOVED None"
expect "CONTRADICTED ['1-down']"
# The pictures (tools/nation_images.py): the page's blank grid read by
# pixels and held to the clue list's numbering, the solution read line by
# line and kept only where its letter runs are the grid's white runs.
pics=$(PYTHONPATH="$PWD/tools" python3 - <<'PY'
import io
from PIL import Image, ImageDraw
import nation_images as ni, nation_key as K
up = "https://www.thenation.com/wp-content/uploads/2020/03/"
page = f'<img src="{up}grid3527.jpg"> <img src="{up}solution3536.jpg">'
print("URLS", ni.image_url(page, "grid")[len(up):], ni.image_url(page, "solution")[len(up):])
print("SOL", ni.image_url(f'<img src="{up}Solution-3523.jpg">', "solution")[len(up):])
# A 5x5 picture: blocks at (1,1), (3,1), (1,3), (3,3), a letter's ink in (0,0).
grid = (".....", ".#.#.", ".....", ".#.#.", ".....")
img = Image.new("L", (5 * 40 + 1, 5 * 40 + 1), 255)
d = ImageDraw.Draw(img)
for y, row in enumerate(grid):
    for x, c in enumerate(row):
        d.rectangle([x * 40, y * 40, x * 40 + 40, y * 40 + 40], outline=0,
                    fill=0 if c == "#" else None)
d.rectangle([10, 12, 30, 30], fill=0)   # bold ink over the middle only
buf = io.BytesIO(); img.save(buf, format="JPEG")
print("BLOCKS", ni.blocks(buf.getvalue(), 5) == grid)
across = [[1, 5, "plain", None], [4, 5, "plain", None], [5, 5, "plain", None]]
down = [[1, 5, "plain", None], [2, 5, "plain", None], [3, 5, "plain", None]]
print("FITS", ni.fits(grid, across, down, []),
      ni.fits(grid, across, [[1, 5, "plain", None], [2, 4, "plain", None], [3, 5, "plain", None]], []))
# s3524 as the VLM read it: "###" written "#", a trailing block dropped, and
# a sparse row with one letter lost (refused, not shifted).
lines = ["MACADAMIA#GAMUT", "CHINATOWN#BANK", "O#A#I#P#O#E#H"]
want = [".........#.....", ".........#....#", ".#.#.#.#.#.#.#."]
got = ni.read_lines("\n".join(lines), want)
print("LINES", "".join(got.get((1, x), "-") for x in range(15)), sum(1 for i, _ in got if i == 2))
print("CLASH", K.clashes(("..", ".."), [(1, "across", 2), (1, "down", 2), (2, "down", 2)],
                         ["AB", "XC", "YD"]))
PY
)
check() { grep -qxF -- "$1" <<<"$pics" || { echo "FAIL: expected line: $1"; fail=1; }; }
check "URLS grid3527.jpg solution3536.jpg"
check "SOL Solution-3523.jpg"
check "BLOCKS True"
check "FITS True False"
check "LINES CHINATOWN-BANK- 0"
# 1-across "AB" clashes with both downs ("XC" at A, "YD" at B): it goes.
check "CLASH [0]"
[ "$fail" = 0 ] || echo "$pics"
if [ "$fail" = 0 ]; then echo "PASS: test_nation_key"; else echo "$out"; exit 1; fi
