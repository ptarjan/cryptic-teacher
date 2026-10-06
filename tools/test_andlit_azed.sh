#!/bin/bash
# Does tools/andlit_azed.py read the Guardian's printable Azed copies: the
# bars off a PDF's ruled lines (stroked or filled, next to a smaller solution
# grid), the HTML print page's bordered table, and the clue list?
#
#     bash tools/test_andlit_azed.sh
#
# Hand-built inputs only. Nothing here reads the network, the cache or the corpus.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import andlit_azed as A
import listener_puzzles as L
import reconstruct_grid as rg

# A 6x6 grid at pitch 20 whose bars sit right of (1, 2) and below (3, 4),
# beside a 6x6 solution grid at pitch 10 with a bar of its own.
def lattice_ops(x0, y0, pitch, thin, bars, stroked):
    ops = []
    def line(x1, y1, x2, y2, w):
        if stroked:
            ops.extend([([w], b"w"), ([x1, y1], b"m"), ([x2, y2], b"l"), ([], b"S")])
        elif x1 == x2:
            ops.extend([([x1 - w / 2, y1, w, y2 - y1], b"re"), ([], b"f")])
        else:
            ops.extend([([x1, y1 - w / 2, x2 - x1, w], b"re"), ([], b"f")])
    top = y0 + 6 * pitch
    for i in range(7):
        line(x0 + i * pitch, y0, x0 + i * pitch, top, thin)
        line(x0, y0 + i * pitch, x0 + 6 * pitch, y0 + i * pitch, thin)
    for kind, y, x in bars:
        if kind == "r":     # the line right of cell (y, x), drawn 1pt off it
            line(x0 + (x + 1) * pitch + 1, top - (y + 1) * pitch, x0 + (x + 1) * pitch + 1, top - y * pitch, 2.5)
        else:
            line(x0 + x * pitch, top - (y + 1) * pitch, x0 + (x + 1) * pitch, top - (y + 1) * pitch, 2.5)
    return ops

for stroked in (True, False):
    ops = (lattice_ops(300, 300, 10, 0.25, [("b", 0, 0)], stroked)
           + lattice_ops(40, 100, 20, 0.5, [("r", 1, 2), ("b", 3, 4)], stroked))
    grid, xs, ys = A.read_bars(A.segments(ops))
    print(f"bars-{'stroked' if stroked else 'filled'}", "/".join(grid))

# Cell numbers that came out of the text as one string are split as the grid reads them.
starts = {(0, 0): 1, (0, 8): 8, (0, 9): 9}
print("split", sorted(A.split_numbers({(0, 0): "1", (0, 8): "89"}, starts).items()))
print("nosplit", sorted(A.split_numbers({(0, 0): "1", (0, 8): "89", (0, 9): "9"}, starts).items()))

# The HTML print page: a 2px right or bottom border is a bar; the frame is not.
cell = '<td valign="top" id=square{}><font>{}</font></td>'
rows = []
for y in range(3):
    tds = ""
    for x in range(3):
        style = []
        if (y, x) == (0, 1) or x == 2:
            style.append("border-right: solid 2px black;")
        if (y, x) == (1, 0) or y == 2:
            style.append("border-bottom: solid 2px black;")
        num = {(0, 0): "1", (0, 1): "2", (0, 2): "3", (1, 0): "4"}.get((y, x), "&nbsp;")
        tds += cell.format(f' style="{"".join(style)}"' if style else "", num)
    rows.append(f"<tr>{tds}</tr>")
page = ("<h1>Azed Crossword No. 1736</h1><B>Special instructions: </B>The Chambers Dictionary"
        " (2003) is recommended.</font><table>" + "".join(rows) + "</table>"
        "<B>Across</b><TR><TD><B>1</B>&nbsp;</TD><TD>Some clue&nbsp;(2)</TD></TR></table>")
h = A.read_html(page)
print("html", h["number"], "/".join(h["grid"]), sorted(h["printed"].items()))
print("plain", A.special("Plain", h), A.special("", h), A.special("‘Playfair’", h))

# A clue opens only on the next light the grid numbers, and ends at its count,
# so the notes and form lines between clues fall away.
lines = {"across": ["1 First clue that runs", "on (5)", "Name", "Address", "1, anag. note",
                    "7Second (4)"],
         "down": ["2 Down one (3, 2 words)", "Post code", "3 Down two (4)"]}
print("clues", A.clue_list(lines, {(1, "across"), (7, "across"), (2, "down"), (3, "down")}))
print("entry", A.entry_of((2, "down"), "Down one (3, 2 words)", {})["clue"])

# An unanswered light is written from crossings that cover every one of its cells.
grid = ["...", "...", "..."]
lights = rg.light_cells(grid)
entries = [{"number": n, "direction": d, "answer": a} for (n, d), a in zip(
    sorted(lights), ["CAT", "COW", None, "TED", "ORE", "WED"])]
filled = A.fill_from_crossings(grid, entries)
print("fill", filled and [e["answer"] for e in filled])

# Ligature and digit glyphs an encoding's /Differences names.
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject
font = DictionaryObject({NameObject("/Encoding"): DictionaryObject({NameObject("/Differences"): ArrayObject(
    [NumberObject(27), NameObject("/T_h"), NameObject("/ffl"), NameObject("/fi"),
     NameObject("/figuredash"), NameObject("/f.short"), NameObject("/one")])})})
chars, _ = L._font_table(font)
print("glyphs", [chars[c] for c in range(27, 33)])
PY
)
echo "$out" | sed 's/^/  | /'
line() { echo "$out" | grep "^$1 " | head -1 | cut -d' ' -f2-; }
check "PDF bars, stroked, beside a smaller grid" \
  "....../..r.../....../....b./....../......" "$(line bars-stroked)"
check "PDF bars, filled rectangles" \
  "....../..r.../....../....b./....../......" "$(line bars-filled)"
check "two cell numbers run together are split" "[((0, 0), 1), ((0, 8), 8), ((0, 9), 9)]" "$(line split)"
check "a number whose neighbour prints its own stays" "[((0, 0), 1), ((0, 8), 89), ((0, 9), 9)]" "$(line nosplit)"
check "HTML bars and numbers" "1736 .r./b../... [((0, 0), 1), ((0, 1), 2), ((0, 2), 3), ((1, 0), 4)]" "$(line html)"
check "the Chambers line alone is a plain puzzle" "False False True" "$(line plain)"
check "clues read past notes and form lines" \
  "{(1, 'across'): 'First clue that runs on (5)', (7, 'across'): 'Second (4)', (2, 'down'): 'Down one (3, 2 words)', (3, 'down'): 'Down two (4)'}" \
  "$(line clues)"
check "a count in figures is written in words" "Down one (3, two words)" "$(line entry)"
check "a missing answer comes from its crossings" "['CAT', 'COW', 'ARE', 'TED', 'ORE', 'WED']" "$(line fill)"
check "ligature and digit glyphs" "['Th', 'ffl', 'fi', '–', 'f', '1']" "$(line glyphs)"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
