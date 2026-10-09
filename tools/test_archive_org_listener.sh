#!/bin/bash
# Does tools/archive_org_listener.py find the Listener's own heading (not the
# coupon's), split the clue columns at DOWN (not the title's "8 DOWN"), carry
# across clues that run into the second column, read a list past a line that
# does not parse, read an uncounted list a clue a line past a stray count,
# and blank a clue no two readings agree on or that runs on?
#
#     bash tools/test_archive_org_listener.sh
#
# Pure functions on made-up words: no scan, no OCR, nothing written.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

out=$(cd "$REPO/tools" && python3 - <<'EOF'
import archive_org_listener as al

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

def line(text, x=100, y=100):
    out = []
    for w in text.split():
        out.append((x, y, x + 10 * len(w), y + 16, w))
        x += 10 * len(w) + 8
    return out

# Headings: the grid's line, the coupon's, the title, a solution box.
check("heading", "3472", al.HEAD.match("LISTENER CROSSWORD No 3472").group(1))
m = al.TITLE.match("No. 3472: Marital Progression by Gnivri")
check("title and setter", ("3472", "Marital Progression", "Gnivri"), m.groups())
check("solution box heading", "3469", al.SOLUTION.match("Solution and notes for No. 3469").group(1))
check("a puzzle's announced solution ends the columns", True,
      bool(al.END.match("The solution grid and notes for Christmas Puzzle by Smokey")))

# Counts the daily's parser takes; a split number; specks before it.
check("(6, two words) is (6)", "Every colonist (6)", al.tidy("Every colonist (6. (wo words)"))
check("1 9 is 19", "19 Nurse with silly plait (5)", al.tidy("1 9 Nurse with silly plait (5)"))
check("a count set wide is one number", "Dealing with deliveries (11)", al.tidy("Dealing with deliveries (1 1)"))
check("specks before a number go", "11 To some extent (6)", al.tidy(":. 11 To some extent (6)"))
check("a backtick is an opening quote, its lost space put back",
      "26 Of a \u2018squatter's right'.", al.tidy("26 Of a`squatter's right'."))
check("an opening quote read as one stands (mirror)",
      "26 Of a \u2018squatter's right'.", al.tidy("26 Of a \u2018squatter's right'."))

# Columns: DOWN level with ACROSS; the title's "DOWN" above the lists is not it.
words = (line("No 3444: 8 DOWN 12 DOWN", x=100, y=40)
         + line("ACROSS", x=100, y=100) + line("DOWN", x=700, y=100)
         + line("1 Answering letters induces spasm (5)", x=100, y=130)
         + line("1 Shed built from timber (4)", x=700, y=130)
         + line("4 Notice (3)", x=100, y=160) + line("2 Dry wet valley up (3)", x=700, y=160)
         + line("47632", x=1250, y=160))
cols = al.columns(words)
check("across column", ["1 Answering letters induces spasm (5)", "4 Notice (3)"], [l[4] for l in cols[0]])
check("down column, the bridge hands right of it left out",
      ["1 Shed built from timber (4)", "2 Dry wet valley up (3)"], [l[4] for l in cols[1]])

# Across clues that run on at the top of the second column, DOWN under them.
words = (line("ACROSS", x=100, y=100)
         + line("1 Answering letters induces spasm (5)", x=100, y=130)
         + line("44 Many a trumpet put back (5)", x=700, y=130)
         + line("DOWN", x=700, y=190)
         + line("1 Shed built from timber (4)", x=700, y=220))
cols = al.columns(words)
check("second column's top is across", ["1 Answering letters induces spasm (5)", "44 Many a trumpet put back (5)"],
      [l[4] for l in cols[0]])
check("down under it", ["1 Shed built from timber (4)"], [l[4] for l in cols[1]])

# A list read past a line that does not parse.
got = al.clues("Answering letters (5) 7 Fences with retired divine (9) 9 Like an old woman (4)")
check("clues after an unreadable one", [{7}, {9}], [c["tokens"][0] for c in got])

# pick: two readings must lay alike text on a light; a run-on is not sound.
a = {"1-across": ("Answering letters induces spasm", "5", None),
     "4-across": ("Gassed with staff", "3", None)}
b = {"1-across": ("Answering letlers induces spasm", "5", None),
     "4-across": ("Form separatist state", "8", None)}
got = al.pick([a, b])
check("corroborated light kept", "Answering letters induces spasm", got["1-across"][0])
check("light the readings disagree on is blank, count kept", ("", "3"), got["4-across"][:2])
# A clue one reading alone lays, that another reading lays under its number
# the other way, is that clue read into the wrong list (No 3's 28D read
# under ACROSS); a clue unlike its number's other-way clue is laid.
texts = ["ACROSS\nA junction on the East In diafy\n", "DOWN\nA junction on the East Indian Railway.\n"]
a = {"28-across": ("A junction on the East In diafy", None, None)}
b = {"28-down": ("A junction on the East Indian Railway.", None, None)}
check("a clue laid the wrong way by one reading is blank", "", al.pick([a, b], texts)["28-across"][0])
a = {"28-across": ("A tree that grows in Burma.", None, None)}
texts = ["ACROSS\nA tree that grows in Burma.\n", "A tree that grows in Burma.\nA junction on the East Indian Railway.\n"]
check("a clue unlike its number's other-way clue is laid (mirror)", "A tree that grows in Burma.",
      al.pick([a, b], texts)["28-across"][0])

# Readings parsing as many clues: the one with more known words leads.
check("a reading running words together knows fewer of them", True,
      al.spaced("Indian servant looks forward to.") > al.spaced("Indian servantlooksforwardto."))

# No 3's "India's greatest neighbour": en5 numbers it 42, ch 40, Tesseract 2
# (out of order, guessed): the figure a third reading keeps names the light.
a = {"39-across": ("Junction for Dehra Dun.", None, None), "42-across": ("India's greatest neighbour", None, None)}
b = {"39-across": ("Junction for Dehra Dun.", None, None), "40-across": ("India's greatest neighbour", None, None)}
c = {"39-across": ("Junction for Dehra Dun.", None, None), "2-across": ("India's greatest neighbour,", None, None)}
got = al.pick([a, b, c], guessed=[set(), set(), {"2-across"}])
check("a clue two readings number apart goes where a third reading's figures end",
      ("India's greatest neighbour", False), (got["42-across"][0], "40-across" in got))
got = al.pick([a, b, {"39-across": ("Junction for Dehra Dun.", None, None)}])
check("without a third reading's figures neither is laid (mirror)", ("", ""), (got["42-across"][0], got["40-across"][0]))

# A light one reading alone lays is dropped on no evidence of a light: its
# words another light's agreed clue (No 3's Tesseract laying 16D as 16A),
# its number out of order, or its words no clue. Laid by two, or a sound
# clue nothing else holds, it stays blank: a clue to read.
a = {"16-down": ("Termination meaning meadow.", None, None), "17-down": ("A town in Assam.", None, None)}
b = dict(a)
c = {"16-across": ("Termination meaning meadow.", None, None), "8-across": ("A of the fof", None, None),
     "41-across": ("1t1cttll UL ( 411 te", None, None)}
got = al.pick([a, b, c], guessed=[set(), set(), {"8-across"}])
check("a light one reading lays on no evidence is dropped", ["16-down", "17-down"], sorted(got))
c = {"16-across": ("A tree that grows in Burma.", None, None)}
check("a sound clue one reading alone lays stays blank (mirror)", ("", True),
      (al.pick([a, b, c])["16-across"][0], "16-across" in al.pick([a, b, c])))
d = {"16-across": ("A shrub of Burma.", None, None)}
check("a light two readings lay unlike stays blank (mirror)", "", al.pick([a, c, d])["16-across"][0])

# A number out of order whose last figure is its lookalike's (old-style 8
# read "3", 9 read "0") is the one number between its neighbours it gives;
# none, or two, and it is a misread number left unlaid.
def listed(*nums):
    return {"across": [{"tokens": [{n}], "enums": [], "text": f"Clue {n}."} for n in nums], "down": []}
guessed = set()
check("a misread figure laid between its neighbours", ["43-across", "46-across", "48-across", "50-across"],
      sorted(al.lay(listed(43, 46, 43, 50), guessed)))
check("... as read, not guessed", (set(), "Clue 43."), (guessed, al.lay(listed(43, 46, 43, 50))["48-across"][0]))
check("a misread figure whose lookalike is out of its place is not laid (mirror)",
      ["43-across", "46-across", "47-across", "50-across"], sorted(al.lay(listed(43, 46, 43, 47, 50))))
check("a misread number with no lookalike figure is not laid (mirror)", ["44-across", "46-across", "50-across"],
      sorted(al.lay(listed(44, 46, 44, 50))))
check("a misread number at a list's end is not laid (mirror)", ["43-across", "46-across"],
      sorted(al.lay(listed(43, 46, 43))))

check("a count inside the text is a run-on", False, al.sound("NEW HAMPSHIRE () Points restricting"))
check("a misread next number inside the text is a run-on", False,
      al.sound("Like an old woman >0 In some places"))
check("an ellipsis opening is sound", True, al.sound(". . . their Peasant's Revolt"))

# The Listener's readings set each filed clue's count and words as they
# print them (ocr_clues.as_printed with this filer's parse), and leave a
# clue alone when they print it as laid.
texts = {k: "ACROSS\n1 Shoddy re-forms (5-4)\n10 Hill (4)\nDOWN\n2 Ore (3)\n" for k in ("djvu", "ch", "en5")}
laid = {"1-across": ("Shoddy reforms", "9", None), "10-across": ("Hill", "4", None), "2-down": ("Ore", "3", None)}
lengths = {"1-across": 9, "10-across": 4, "2-down": 3}
got, blank = al.ocr_clues.as_printed(texts, laid, {}, al.parse, lengths)
check("a Listener clue takes the count and hyphen its readings print", ("Shoddy re-forms", "5-4"), got["1-across"][:2])
check("a Listener clue printed as laid is left alone", (("Hill", "4", None), {}), (got["10-across"], blank))

# An uncounted 1930s list with one bracket misread as a count is still read a
# clue a line (No 9's "(Pope)" ran 14 downs into 2); a counted list is not.
text = ("ACROSS\n12. Metallic of a kind.\n13. A very modern type.\n14. Milton called this.\n"
        "DOWN\n1. An African bird.\n2. A fungus.\n9. Or whirl the (7)\n10. A drink.\n11. A golfer.")
parsed, _ = al.parse(text)
check("an uncounted list with a stray count, a clue a line", ([12, 13, 14], [1, 2, 9, 10, 11]),
      tuple([min(c["tokens"][0]) for c in parsed[d]] for d in ("across", "down")))
parsed, _ = al.parse("ACROSS\n1 Fish (4)\n5 Bird of\n3 prey (5)\nDOWN\n2 Tree (3)\n4 Shrub (6)")
check("a counted list ends its clues at the counts", ["Fish", "Bird of 3 prey"],
      [c["text"] for c in parsed["across"]] if parsed else None)

print("FAILS", fails)
EOF
)
echo "$out"
grep -q "^FAILS 0$" <<<"$out"
