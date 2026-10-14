#!/bin/bash
# Does tools/privateeye_scans.py find a Private Eye page's clue columns from
# its djvu words, take the crossword's number and not the entry address's,
# read a linked head and a cross-reference, and hand privateeye_wayback's
# read_capture a list it parses? And does the shared tidy read RapidOCR's
# full-width bracket as a round one?
#
#     bash tools/test_privateeye_scans.sh
#
# Offline: the page's words are written here.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {
  if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: want [$2] got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import privateeye_scans as ps
import privateeye_wayback as pw
import file_archive_org_puzzles as fa


def line(*words):
    """A djvu LINE of (x0, y0, x1, text) words, 30px tall."""
    return "<LINE>" + "".join(
        f'<WORD coords="{x0},{y0 + 30},{x1},{y0}">{t}</WORD>' for x0, y0, x1, t in words) + "</LINE>"


rows = [line((100, 50, 300, "EYE"), (320, 50, 600, "CROSSWORD"), (620, 50, 660, "13"), (680, 50, 900, "Cyclops"))]
left = ["ACROSS", "1 Clue one here (5)", "5 Clue five (4)", "7 Another clue (6)", "9 Last across (8)"]
right = ["DOWN", "1 First down clue (4,4)", "2 This crossword is first (4)", "20/12 Linked clue (6,6)",
         "12 (See 20 down)"]
y = 200
for a, b in zip(left, right):
    # archive.org's OCR runs a row of both columns into one LINE.
    wa = [(100 + 60 * k, y, 150 + 60 * k, t) for k, t in enumerate(a.split())]
    wb = [(1300 + 60 * k, y, 1350 + 60 * k, t) for k, t in enumerate(b.split())]
    rows.append(line(*(wa + wb)))
    y += 45
rows.append(line((1300, y + 20, 1500, "Send"), (1520, y + 20, 1700, "entries"), (1720, y + 20, 1800, "to"),
                 (1820, y + 20, 2000, "“Crossword”,"), (2020, y + 20, 2100, "Private"),
                 (2120, y + 20, 2200, "Eye,"), (2220, y + 20, 2240, "6")))
rows.append(line((1300, y + 80, 1500, "SOLUTION"), (1520, y + 80, 1560, "TO"),
                 (1580, y + 80, 1800, "CROSSWORD"), (1820, y + 80, 1850, "12")))
xml = ("<OBJECT>" + "".join(rows) + "</OBJECT>").encode()
lines = ps.page_lines(xml)
print("SPLIT", len(lines))
cols = ps.columns(lines)
print("COLS", len(cols), cols[0][0] < 200, cols[1][0] > 1200 and cols[1][3] > 200 + 45 * 4)
print("NUMBER", ps.number_of(lines, 858), ps.number_of(lines[1:], 858), ps.number_of(lines[1:], 900))
words = [w for ws in lines for w in ws]
across, down = ps.column_cols(cols)(words)
print("SIDES", len(across), len(down), down[2][4])

laid = {"1-across": ("Clue one here", "5", None), "1-down": ("First down clue", "4,4", None),
        "20-down": ("Linked clue", "6,6", ["20-down", "12-down"]), "12-down": ("See 20", None, None)}
text = ps.page_text(13, laid)
print("TEXT", text)
cap = pw.read_capture(text.encode(), "utf-8", plain=True, issue=858)
print("CAPTURE", cap["number"], [(r["number"], r["clue"], r["enumeration"]) for r in cap["rows"]["down"]])

verdict = {"blank": {"12-down": "no count read", "5-across": "no count read"}}
reads = {k: words for k in ("a", "b")}
laid2, v2 = ps.see_filled({"12-down": ("", None, None), "5-across": ("", "4", None)}, verdict, reads,
                          ps.column_cols(cols))
print("SEE", laid2["12-down"][0], sorted(v2.get("blank", {})))
two = {"clues": [(f"{i}_page", {"across": [{"number": "1", "clue": c, "enumeration": "5"}], "down": []})
                 for i, c in ((974, "One"), (975, "Two"))]}
print("CLASH", pw.build(129, two)[1])
cross = ps.linked_across({"14-across": ("Ramble by the sea?", "10,6", ["14-across", "22-across"]),
                          "22-across": ("See 14", None, None), "22-down": ("", "14", None),
                          "12-across": ("See 20", None, None), "20-down": ("Linked", "6,6", ["20-down", "12-down"]),
                          "12-down": ("See 20", None, None)})
print("CROSS", sorted(cross), cross["22-down"][0], cross["12-across"][0])
print("TIDY", fa.tidy("ACROSS\n23 Maybe Charles slips one inside 4）").splitlines()[-1])
PY
)
echo "$out" | sed 's/^/  | /'
get() { echo "$out" | sed -n "s/^$1 //p"; }

check "a LINE across both columns is cut at the gap" "13" "$(get SPLIT)"
check "two clue columns found, left then right, a clue saying crossword in them" "2 True True" "$(get COLS)"
check "the heading's number, else the solution's + 1, never the address's 6" "13 13 None" "$(get NUMBER)"
check "the columns read ACROSS then DOWN, a linked head's slash a comma" "4 4 20, 12 Linked clue (6,6)" "$(get SIDES)"
check "a linked head prints 20/12 and a continuation See 20" \
  "EYE CROSSWORD 13 ACROSS 1 Clue one here (5) DOWN 1 First down clue (4,4) 12 See 20 20/12 Linked clue (6,6)" \
  "$(get TEXT)"
check "read_capture parses the page text" \
  "13 [('1', 'First down clue', '4,4'), ('12', 'See 20', None), ('20,12', 'Linked clue', '6,6')]" \
  "$(get CAPTURE)"
check "a blank two readings print as (See 20 down) is See 20; others stay blank" "See 20 ['5-across']" "$(get SEE)"
check "two pages reading one number with different clues are refused" \
  "two scans' page images print different clues under this number" "$(get CLASH)"
check "a link across directions: the other direction's See light kept, the vote's made one gone" \
  "['12-across', '14-across', '20-down', '22-down'] See 14 See 20" "$(get CROSS)"
check "a full-width bracket reads as a round one" "23 Maybe Charles slips one inside (4)" "$(get TIDY)"

[ "$fails" = 0 ] && echo "all ok" || { echo "$fails failed"; exit 1; }
