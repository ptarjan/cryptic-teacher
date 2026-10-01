#!/bin/bash
# Does tools/listener_puzzles.py read a Listener archive PDF's bars, letters
# and two-column clue list?
#
#     bash tools/test_listener_puzzles.sh
#
# Hand-built inputs only: a 3x3 grid drawn as one filled rectangle per cell
# side, the way the archive PDFs draw it, and the text runs of a clue page.
# Nothing here reads the network, the PDF cache or the corpus.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import ft_pdf_puzzles
import listener_puzzles as L
text_runs = L.text_runs

# CAT / ORE / WED with a bar right of O: across 1 CAT, 4 RE, 5 WED; down
# 1 COW, 2 ARE, 3 TED. A side is 0.8pt; the bar and the frame are 2pt.
ROWS = ["CAT", "ORE", "WED"]
NUMBERS = {(0, 0): 1, (0, 1): 2, (0, 2): 3, (1, 1): 4, (2, 0): 5}
P, TOP = 20, 60
ops = [([0], b"g")]
for y in range(3):
    for x in range(4):        # vertical sides
        w = 2 if x in (0, 3) or (y, x) == (1, 1) else 0.8
        ops.append(([x * P - w / 2, TOP - (y + 1) * P, w, P], b"re"))
for y in range(4):            # horizontal sides
    for x in range(3):
        w = 2 if y in (0, 3) else 0.8
        ops.append(([x * P, TOP - y * P - w / 2, P, w], b"re"))
ops.append(([], b"f"))
runs = []
for y, row in enumerate(ROWS):
    for x, ch in enumerate(row):
        runs.append((0, x * P + 6, TOP - (y + 1) * P + 5, 12, ch))
for (y, x), n in NUMBERS.items():
    runs.append((0, x * P + 1, TOP - y * P - 7, 7.7, str(n)))
ft_pdf_puzzles.ops_of = lambda data: ("", ops)
L.text_runs = lambda data: runs
sol = L.read_solution(b"")
print("BARS", "/".join(sol["bars"]))
lights = L.lights(sol)
print("LIGHTS", " ".join(f"{n}{d[0]}=" + "".join(sol["letters"][c] for c in cells)
                         for (n, d), cells in sorted(lights.items())))

# The clue page: ACROSS on the left; DOWN and its clues on the right. A
# right-hand number sits at the end of a left-hand line, as pypdf reads it, a
# clue wraps, and the grid's small numbers above the heading are not clues.
page = [
    (0, 100, 600, 7.7, "1"),
    (0, 90, 500, 12, "ACROSS"), (0, 320, 500, 12, "DOWN"),
    (0, 100, 486, 12, "1 Feline"), (0, 320, 486, 12, "1 Bovine"),
    (0, 100, 472, 12, "4 Concerning, in"), (0, 320, 472, 12, "beast"),
    (0, 100, 458, 12, "a memo 2"), (0, 330, 458, 12, "Exist"),
    (0, 100, 444, 12, "5 Marry"), (0, 320, 444, 12, "3 Bear"),
]
left, right = L.column_lines(page, 300)
clues = L.parse_clues(left, right, set(lights))
print("CLUES", " | ".join(f"{n}{d[0]} {t}" for (n, d), t in sorted(clues.items())))

# A text run off a real content stream: a font whose /Differences moves codes
# 1-2 to the glyphs /A and /M (No 93's decorative grid letters), a TJ whose
# 2-em kern jumps to the right-hand column, and a string set where the last
# ended, mid-word, continuing it. Widths: every glyph 500/1000 em at 10pt.
def pdf(content, font):
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            font]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
font = (b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman /FirstChar 1 /LastChar 122 "
        b"/Widths [" + b" 500" * 122 + b"] /Encoding << /Type /Encoding "
        b"/BaseEncoding /WinAnsiEncoding /Differences [1 /A /M] >> >>")
content = (b"BT /F1 10 Tf 1 0 0 1 100 700 Tm (\x01\x02) Tj ET "
           b"BT /F1 10 Tf 1 0 0 1 50 500 Tm [(1 Le) -2000 (2 Ri)] TJ 60 0 Td (ght) Tj ET")
print("RUNS", [(round(x), t) for _p, x, _y, _s, t in text_runs(pdf(content, font))])

# Linked heads: "7 & 8" one answer led by 7; "60 & 27D" across a direction;
# "30, 33 See 40" points elsewhere; a head's notes stay in its clue; "25 See
# 34" printed after 34 named it still opens; "blind-" joins "man's".
wanted = {(7, "down"), (8, "down"), (60, "across"), (27, "down"), (30, "across"),
          (33, "across"), (40, "across"), (34, "across"), (25, "across"), (39, "across")}
clues, groups = L.parse_clue_list(
    ["ACROSS", "30, 33 See 40", "34 (rev.), 25 (rev.) Flower", "25 See 34",
     "39 (rev.) Half the rustle in blind-", "man's buff", "40, 30, 33 End of a Carol",
     "60 & 27D Lucentemque globum"],
    ["DOWN", "7 & 8 Noctes atque dies"], wanted)
print("LINKS", " | ".join(f"{n}{d[0]} {t}" for (n, d), t in sorted(clues.items())))
print("GROUPS", sorted((f"{n}{d[0]}", [f"{m}{e[0]}" for m, e in g]) for (n, d), g in groups.items()))

# A run nothing clues is barred shut: QO, numbered only for 1-down, and XY,
# unnumbered.
sol = {"rows": 2, "cols": 3, "letters": {(0, 0): "Q", (0, 1): "O", (1, 0): "X", (1, 1): "Y"},
       "numbers": {(0, 0): 1, (0, 1): 2}, "bars": ["...", "..."]}
L.close_unclued(sol, {(1, "down"), (2, "down")})
print("CLOSE", "/".join(sol["bars"]), sorted(L.lights(sol)))

# Bars and black squares in one grid: the bars say where lights end, the
# squares no entry covers are still black, and an unclued light's square is not.
import reconstruct_grid as R
mixed = {"dimensions": {"cols": 3, "rows": 2}, "bars": ["rr.", "r.."],
         "entries": [{"number": 1, "direction": "down", "position": {"x": 0, "y": 0}, "length": 2},
                     {"number": 2, "direction": "down", "position": {"x": 1, "y": 0}, "length": 2}],
         "unclued": [{"cells": [{"x": 2, "y": 0}]}]}
print("MIXED", "/".join(R.grid_of(mixed)), sorted(R.lights_from_grid(R.grid_of(mixed))))

# The Times' pages: how a preamble alters an answer, as every entry it could make.
print("MOVES", sorted(e for e, _ in L._moves("CANOPY", "NO", -1)))
print("SNT", "AGOUTI" in [e for e, _ in L._sn_to_t("SAGOUIN")], L._sn_to_t("BAIT"))
print("SYM", L.symmetric(["r..", "...", ".r."]), L.symmetric(["r..", "...", "..."]))
notes = ("<tr><td class='cluegrouphead'>Across</td></tr>"
         "<tr><td> 1 </td><td> A: Nates </td><td> CANOPY </td><td> CAN + O </td></tr>"
         "<tr><td class='cluegrouphead'>Down</td></tr>"
         "<tr><td> 2 </td><td> T </td><td> BOS&rsquo;NS </td><td> BOSS about N </td></tr>")
print("NOTES", L.notes_answers(notes))
PY
)

check "bars: a thick side between two letters is a bar, the frame is not" \
  "BARS .../r../..." "$(grep '^BARS' <<<"$out")"
check "lights: a barred-off single cell is no light" \
  "LIGHTS 1a=CAT 1d=COW 2d=ARE 3d=TED 4a=RE 5a=WED" "$(grep '^LIGHTS' <<<"$out")"
check "clues: wrapped lines join, a stray right-hand number moves across" \
  "CLUES 1a Feline | 1d Bovine beast | 2d Exist | 3d Bear | 4a Concerning, in a memo | 5a Marry" \
  "$(grep '^CLUES' <<<"$out")"

check "text runs: a /Differences glyph, a column-gap kern, a mid-word continuation" \
  "RUNS [(100, 'AM'), (50, '1 Le'), (90, '2 Right')]" "$(grep '^RUNS' <<<"$out")"
check "linked heads: one answer led by the first light, See heads link nothing" \
  "LINKS 7d Noctes atque dies | 8d See 7 | 25a See 34 | 27d See 60 | 30a See 40 | 33a See 40 | 34a (rev.), 25 (rev.) Flower | 39a (rev.) Half the rustle in blind-man's buff | 40a End of a Carol | 60a Lucentemque globum" \
  "$(grep '^LINKS' <<<"$out")"
check "linked heads: groups in printed order" \
  "GROUPS [('34a', ['34a', '25a']), ('40a', ['40a', '30a', '33a']), ('60a', ['60a', '27d']), ('7d', ['7d', '8d'])]" \
  "$(grep '^GROUPS' <<<"$out")"
check "an unclued run is barred shut" \
  "CLOSE r../r.. [(1, 'down'), (2, 'down')]" "$(grep '^CLOSE' <<<"$out")"
check "bars and black squares in one grid number as printed" \
  "MIXED rr./r.# [(1, 'down', 2), (2, 'down', 2)]" "$(grep '^MIXED' <<<"$out")"
check "a run moved leftwards: every place to its left" \
  "MOVES ['CNOAPY', 'NOCAPY']" "$(grep '^MOVES' <<<"$out")"
check "No 3999's change: S and N out, T in anywhere" "SNT True []" "$(grep '^SNT' <<<"$out")"
check "bars symmetric turned half round, not when one is missing" "SYM True False" "$(grep '^SYM' <<<"$out")"
check "notes: the answer is the capitalised cell after the number" \
  "NOTES {(1, 'across'): 'CANOPY', (2, 'down'): 'BOS’NS'}" "$(grep '^NOTES' <<<"$out")"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
