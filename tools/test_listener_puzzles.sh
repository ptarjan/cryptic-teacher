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

check "a run moved leftwards: every place to its left" \
  "MOVES ['CNOAPY', 'NOCAPY']" "$(grep '^MOVES' <<<"$out")"
check "No 3999's change: S and N out, T in anywhere" "SNT True []" "$(grep '^SNT' <<<"$out")"
check "bars symmetric turned half round, not when one is missing" "SYM True False" "$(grep '^SYM' <<<"$out")"
check "notes: the answer is the capitalised cell after the number" \
  "NOTES {(1, 'across'): 'CANOPY', (2, 'down'): 'BOS’NS'}" "$(grep '^NOTES' <<<"$out")"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
