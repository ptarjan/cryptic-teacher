#!/bin/bash
# Does tools/parse_penguin_book.py still read the DOTTED-NUMBER LAYOUT?
#
#     bash tools/test_penguin_layout.sh
#
# A scan set in that convention (running head glued to the header line,
# dotted clue numbers, "1 & 4 Ac." links, "See 14 Across" cross-references)
# does not degrade when the parser cannot read it — it collapses. Every
# puzzle in the book falls through to jigsaw mode, losing the Across/Down
# split, and clue-number recovery is exactly 0%. Measured on
# crypticcrossword0000unse: 17/17 puzzles jigsaw and 0/394 numbers before the
# variant, 0/17 and 68/401 after. It is 12 of the 33 scans on hand, so this
# gates a convention, not a book.
#
# THE FIXTURES ARE SYNTHETIC, written here in the layout rather than copied
# out of any scan: no book text lives in this repo, and a layout test should
# fail for layout reasons and not because one OCR line changed. The sharp
# edge they exist to hold is case 3 — "13. See 14 Across" is a real clue in
# this convention and it ENDS IN THE WORD ACROSS, so a glued-head rule loose
# enough to accept "Cryptic Across" will read it as a section header and
# throw away every clue above it. That failure is silent and looks like a
# short puzzle, which is why it is asserted directly.
set -u
cd "$(dirname "$0")/.."

python3 - <<'PYEOF'
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "tools")
import parse_penguin_book as P

failures = []


def fail(msg):
    failures.append(msg)
    print(f"  FAIL {msg}")


def ok(msg):
    print(f"  ok   {msg}")


def check(label, got, want):
    if got == want:
        ok(f"{label}: {got!r}")
    else:
        fail(f"{label}: got {got!r}, wanted {want!r}")


# ------------------------------------------------------------------ case 1
print("case 1: the running head glued onto the header line")
for line, want in (
        ("Cryptic Across", "ACROSS"),
        ("Cryptic Down", "DOWN"),
        ("CryBHE Across", "ACROSS"),          # the head itself OCR'd badly
        ("Cryptic Crossword Across", "ACROSS"),
        ("ACROSS", "ACROSS"),                  # the plain form still works
        ("| ACROSS", "ACROSS"),                # and the stray-glyph one
        ("Down", "DOWN"),
):
    check(f"header {line!r}", P._header_kind(line), want)

# ------------------------------------------------------------------ case 2
print("case 2: lines that merely end in a direction word are NOT headers")
for line in (
        "13. See 14 Across",     # a real clue in this very layout
        "See 14 Across",         # the same after OCR ate the number
        "15. See 4 Down",
        "Take a risk and ardently indulge in the game across",
):
    got = P._header_kind(line)
    if got is None:
        ok(f"not a header: {line!r}")
    else:
        fail(f"{line!r} was read as a {got} header — every clue above it on "
             f"the leaf is discarded when that happens")

# ------------------------------------------------------------------ case 3
print("case 3: dotted, linked and plain clue numbers")
for chunk, want_number, want_clue in (
        ("13. Dotted number clue (5)", "13", "Dotted number clue"),
        ("8. Another dotted one (7)", "8", "Another dotted one"),
        ("13 Plain penguin-style number (5)", "13", "Plain penguin-style number"),
        ("1 & 4 Ac. A linked pair (5,2,5)", "1,4", "A linked pair"),
        ("8 & 17Ac. Linked with no space (6-5)", "8,17", "Linked with no space"),
        ("4 &15 Dn. Linked downward (3-3,6)", "4,15", "Linked downward"),
        ("1,4 Comma-linked as the penguins print it (5,2,5)", "1,4",
         "Comma-linked as the penguins print it"),
        # The \b after the direction word is what keeps "Ac" out of "Acid".
        ("5 Acid test for the boundary (4)", "5", "Acid test for the boundary"),
        ("6 Downcast about the boundary (8)", "6", "Downcast about the boundary"),
):
    got = P.parse_clue_chunk(chunk)
    check(f"number of {chunk[:28]!r}", got["number"], want_number)
    if got["clue"] != want_clue:
        fail(f"clue text of {chunk[:28]!r}: got {got['clue']!r}, wanted "
             f"{want_clue!r}")

# ------------------------------------------------------------------ case 4
print("case 4: a number the OCR ate is left null, never invented")
got = P.parse_clue_chunk(". Orphan dot where the digit was (4)")
check("number", got["number"], None)
check("clue text carries no leading dot", got["clue"],
      "Orphan dot where the digit was")

print("case 4b: a brace is OCR noise, never clue text (book-23195)")
for chunk, want in (("}) Very wealthy tributary (8)", "Very wealthy tributary"),
                    ("28 Why a vocalist may be employed } cheaply... (3,1,4)",
                     "Why a vocalist may be employed cheaply..."),
                    ("...a {high-flying} vocalist (6)", "...a high-flying vocalist")):
    got = P.parse_clue_chunk(chunk)["clue"]
    check(f"braces dropped from {chunk[:24]!r}", got, want)

print("case 4c: the Down list continues on the grid page after the clue page")
leaves = ["Across\n1 First across clue (5)\nDown\n1 First down (5)\n2 Second down (4)",
          "GRIDNOISE\n3 Third down clue that\nwraps a line (4)\nQXZ\n2 Next puzzle? (3)\n"
          "26 Late down (4)\nSetter: Someone"]
more = P.continued_down([{"number": "1"}, {"number": "2"}], [1], leaves)
check("continued numbers, ascending, noise and lower numbers dropped",
      [c["number"] for c in more], ["3", "26"])
check("a wrapped continued clue is joined", more[0]["clue"], "Third down clue that wraps a line")
check("no numbered Down list, nothing continued", P.continued_down([], [1], leaves), [])
check("a page of clues with no heading continues the puzzle before it",
      P.is_continuation_leaf("12 Recount (4,1,5)\n13 Prior (10)"), True)
check("a jigsaw page is a puzzle of its own",
      P.is_continuation_leaf("Method: Solve the clues\n\nA clue (5)"), False)
check("an Across page is a puzzle of its own",
      P.is_continuation_leaf("ACROSS\n1 A clue (5)"), False)

print("case 4e: a Down heading the OCR mangled or never printed still splits")
# Real excerpts. timescrypticcros0000time #52 (Times book 21): every Down
# heading in the book OCRs as "DOwNn". heraldcrosswordb0000unse #69: "DOWN i".
# guardiancrosswor0000perk #12: no Down heading on the leaf at all.
for line, want in (("DOwNn", "DOWN"), ("DOWN i", "DOWN"), ("ACROSS", "ACROSS"),
                   ("Down a pint (4)", None)):
    check(f"header {line!r}", P._header_kind(line), want)
times = """ACROSS
1 Agree to redraft of letters (6,3)
6 Note rolls filled with uncooked meat (5)
26 Finally detain suspect making a stink (5)
27 Nothing to do when visiting islands, of course (4-5)

DOwNn
1 Rubbish loaded up into metal skip (5)
2 Objects to a few kids at movie getting fidgety (5,1,3,4,2)
23 It takes twenty-four hours — that’s right — to make spicy food (5)"""
guardian = """ACROSS
1 Consider cocaine, say? (5, 2, 1, 8
8, 9 Left directly across the way (5, 8
11 How ranks may be disposed to
the sound of weeping (2, 5)
12 Carry out to kill (7)
25 Stupendous deficit in fuel (8)
26 Put the question like Kidder-
minster’s first journalist (5)
1 Facing the opposite way ercaee 3
out sailor’s ejection (7, 5
2 During rain, go to the bar (5)
3 Trinket, for example, made in 4
Northants (9)
5 Little boys used to pinch (7)"""
for name, text, want in (("Times 'DOwNn'", times, (4, 3)),
                         ("Guardian, no heading", guardian, (4, 3))):
    p = P.build_puzzle(1, 0, [], [text])
    check(f"{name}: across/down counts", (len(p["across"]), len(p["down"])), want)
    check(f"{name}: Down opens at 1", p["down"][0]["number"], "1")
check("a misread number mid-Across ('9 1 11') is not the cut",
      P.down_restart([{"number": n} for n in
                      ("1", "9", "1", "11", "12", "25", "4", "5", "7")]), 6)
check("numbers that never fall: no Down list invented",
      P.down_restart([{"number": n} for n in ("1", "5", "9", "10", "12", "14")]), None)

print("case 4d: two clues OCR'd onto one line are cut at the enumeration")
chunks = P.segment_clues(["11 Historical example of violence run forth (4, 5). 12 Lower the flag (5)",
                          "13 Not (2) a number cut (3)"])
check("run-on line split, '(4, 5)' read as an enumeration",
      [P.parse_clue_chunk(c)["enumeration"] for c in chunks], ["4,5", "5", "3"])
check("a bracket mid-clue with no number after it does not cut",
      P.parse_clue_chunk(chunks[2])["clue"], "Not (2) a number cut")

print("case 5: clue TEXT that opens with a number keeps every character")
for chunk in ("1,000 request face-covering (4)",
              "100 resigned because of the split (5)"):
    got = P.parse_clue_chunk(chunk)
    if got["number"] is not None:
        fail(f"{chunk!r} was renumbered as {got['number']!r} — that number is "
             f"part of the clue, not a label")
    elif not got["clue"].startswith(chunk.split(" ")[0]):
        fail(f"{chunk!r} lost its opening number from the text: {got['clue']!r}")
    else:
        ok(f"left alone: {chunk[:24]!r}")

# ------------------------------------------------------------------ case 6
print("case 6: cross-references that name a direction close their own clue")
for line in ("13. See 14 Across", "15. See 4 Down", "See 15"):
    if not P.SEE_REFERENCE_RE.match(line.split(". ", 1)[-1]):
        fail(f"{line!r} does not register as a cross-reference, so it never "
             f"ends a clue and glues itself onto the next one")
    else:
        ok(f"closes a clue: {line!r}")

# ------------------------------------------------------------------ case 7
# End to end, because every piece above can be right while the leaf still
# falls through to jigsaw mode.
print("case 7: a whole leaf in this layout parses as across/down, not jigsaw")


def leaf(n):
    across = [f"{i}. Across clue number {i} here ({i + 3})" for i in range(1, 9)]
    down = [f"{i}. Down clue number {i} here ({i + 3})" for i in range(1, 9)]
    return "\n".join(
        [f"{n}]", "Cryptic Across"] + across
        + ["Cryptic Down"] + down)


book = "\f".join([
    "Front matter with nothing much on it",
    "The Puzzles",
    leaf(1),
    "grid image noise\nRufus\n12",
    leaf(2),
    "grid image noise\nCustos\n14",
    "Solutions",
])
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "synthetic.txt"
    path.write_text(book, encoding="utf-8")
    puzzles = P.parse_book(path)

check("puzzles found", len(puzzles), 2)
modes = sorted({p["mode"] for p in puzzles})
if modes != ["across_down"]:
    fail(f"modes {modes} — the layout fell through to jigsaw, which is the "
         f"whole-book failure this variant exists to prevent")
else:
    ok("both puzzles parsed as across_down, none lost to jigsaw")

for p in puzzles:
    check(f"#{p['book_number']} across clues", len(p["across"]), 8)
    check(f"#{p['book_number']} down clues", len(p["down"]), 8)
    numbered = sum(1 for c in p["across"] + p["down"] if c["number"])
    total = len(p["across"]) + len(p["down"])
    if numbered != total:
        missing = [c["clue"][:30] for c in p["across"] + p["down"]
                   if not c["number"]]
        fail(f"#{p['book_number']}: {numbered}/{total} numbers recovered, "
             f"missing {missing}")
    else:
        ok(f"#{p['book_number']}: {numbered}/{total} clue numbers recovered")
    if p["setter"] is None:
        fail(f"#{p['book_number']}: setter lost")

print("case 7b: a page that is only a Down list is the rest of the puzzle before it")
# Shaped like heraldcrosswordb0000unse #41: the Across list fills its page and
# the Down list follows on a page of its own, numbers in a column apart from
# the clues. Counted as a puzzle, that page put every later one a place late.
long_across = "\n".join(["ACROSS"] + [f"{i} Long across clue {i} ({i % 9 + 3})"
                                      for i in range(1, 27)])
down_page = "\n".join(["DOWN", "", "1", "2", "4", ""]
                      + [f"Down clue on its own page {i} ({i % 9 + 3})" for i in range(1, 10)])
other_across = "\n".join(["Across clue in a lost heading's puzzle (5)"] * 8
                         + ["DOWN"] + ["Down clue under it (5)"] * 8)
book = "\f".join(["The Puzzles", "One\n" + long_across, down_page, "grid noise\n91",
                  "Two\n" + leaf(2), "grid noise\n96", other_across, "Solutions"])
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "synthetic.txt"
    path.write_text(book, encoding="utf-8")
    puzzles = P.parse_book(path)
check("puzzles found", [p["raw_number_ocr"] for p in puzzles], ["One", "Two", "Across clue in a lost heading's puzzle (5)"])
check("#1 keeps its Across list", len(puzzles[0]["across"]), 26)
check("#1 takes the Down page as its Down list", len(puzzles[0]["down"]), 9)
check("#2 is the next printed puzzle", puzzles[1]["book_number"], 2)
check("a page with clues above its Down heading is a puzzle of its own",
      P.is_continuation_leaf(other_across), False)

# ------------------------------------------------------------------ case 5
print("case 5: a book grouped by setter names each group once, on a prose leaf")
PROSE = "\n".join(["A line of the setter's profile, long enough to be prose."] * 5)
codes = {}
for head, prose, want in (
        ("RFS: Roger F. Squires", PROSE, "Roger F. Squires"),   # initials -> name
        ("CJM: Calum J]. Macdonald", PROSE, "Calum J. Macdonald"),  # OCR bracket
        ("Myops: John McKie", PROSE, "Myops"),                  # a word IS the byline
        ("General knowledge by CJM", PROSE, "Calum J. Macdonald"),  # code seen above
        ("lan Rankin", PROSE, "Ian Rankin"),                    # OCR l for I
        ("RFS: Roger F. Squires", "grid noise\n14", None),     # no prose, no section
        # The contents page lists every byline; it must not open a section.
        ("Cryptic classics: Roger F. Squires", PROSE, None),
        ("Preface", PROSE, None),
):
    check(f"section byline of {head!r}", P.section_byline(f"{head}\n{prose}", codes), want)

print()
if failures:
    print(f"FAILED: {len(failures)} problem(s)")
    sys.exit(1)
print("PASSED")
PYEOF
