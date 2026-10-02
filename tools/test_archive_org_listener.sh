#!/bin/bash
# Does tools/archive_org_listener.py find the Listener's own heading (not the
# coupon's), split the clue columns at DOWN (not the title's "8 DOWN"), carry
# across clues that run into the second column, read a list past a line that
# does not parse, and blank a clue no two readings agree on or that runs on?
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
check("specks before a number go", "11 To some extent (6)", al.tidy(":. 11 To some extent (6)"))

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
check("a count inside the text is a run-on", False, al.sound("NEW HAMPSHIRE () Points restricting"))
check("a misread next number inside the text is a run-on", False,
      al.sound("Like an old woman >0 In some places"))
check("an ellipsis opening is sound", True, al.sound(". . . their Peasant's Revolt"))

print("FAILS", fails)
EOF
)
echo "$out"
echo "$out" | grep -q "^FAILS 0$"
