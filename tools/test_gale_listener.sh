#!/bin/bash
# Does a Listener page saved into the Gale inbox (tools/gale_listener.py)
# match its puzzle by the date or number in its name, the Gale citation or
# its title, a report page as the solution of the puzzle it names; are its
# clue lists read in column order wherever DOWN falls, the 1930s lists by
# their numbers in bands across two columns when a heading goes unread, a
# clue a line when the lists print no counts; is each file read once (the
# ledger is keyed by its hash; one whose OCR times out stays unread); and
# does the checklist list every puzzle of
# the index, earliest first, marking what is filed or saved, and what the
# 3-minute tick saw arrive (matched by name or citation, each file once),
# asking for a saved puzzle's missing solution?
#
#     bash tools/test_gale_listener.sh
#
# Synthetic rows and words in a temp dir: no OCR, nothing asked of the Mac,
# Gale or listenercrossword.com, nothing written outside it.
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 - "$tmp" <<'PY'
import datetime, json, sys
from pathlib import Path
from PIL import Image
import archive_org_listener as al
import gale_listener as g

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

D = datetime.date
page = """<tr><td class="num">	1	</td><td class="title">	A Musical Crossword	</td>
<td class="setter">	&mdash;	</td><td class="date">	2 Apr	</td><td class="count">1</td></tr>
<tr><td class="num">	2	</td><td class="title">	A &lsquo;Scientific Crossword&rsquo;	</td>
<td class="setter">	<a href="x">Doggerel</a>	</td><td class="date">	9 Apr	</td></tr>"""
rows = g.parse_year(page, 1930)
check("an index row", {"number": 1, "title": "A Musical Crossword", "setter": None, "date": D(1930, 4, 2)}, rows[0])
check("a setter's link and an entity", ("‘Scientific Crossword’", "Doggerel"),
      (rows[1]["title"][2:], rows[1]["setter"]))
check("an issue's puzzle within its week", 2, g.by_date(rows, D(1930, 4, 10))["number"])
check("no puzzle a fortnight off", None, g.by_date(rows, D(1930, 4, 25)))

for name, want in [("Listener 1950.pdf", 1950), ("No. 2,345.jpg", 2345), ("1234.png", 1234),
                   ("Listener Historical Archive 1950.pdf", None), ("GALE|CR1234567890.pdf", None)]:
    check(f"the number in {name!r}", want, g.name_number(name))
check("a 1930 date in a name", D(1930, 4, 9), g.gi.name_date("The Listener 9 Apr 1930.jpg", g.DATES))
m = g.CITED.search("The Listener, vol. 3, no. 64, 9 Apr. 1930, p. 612")
check("the Gale citation's date", ("9", "Apr", "1930"), m.groups()[:3])
check("the title's number", "1,234", g.TITLE.search("THE LISTENER CROSSWORD No. 1,234").group(1))
check("a browser's copy suffix is no number", None, g.name_number("GM2500066057 (1).pdf"))
cite = '\n"No. 36—Wireless Crossword-Clue Competition. " The Listener, vol. \n4, no. 99, 3 Dec. 1930, p. 906.'
check("the citation title's number", (36, "PDF citation title", set()), g.cited(cite))
check("the citation's date across a line break", D(1930, 12, 3), g.cited_day(cite))
check("a report names the solved puzzle, not the page's",
      (None, None, {38}), g.cited('"Report on Wireless Crossword No. 38. " The Listener, vol. 4, no. 103, 31 Dec. 1930'))
check("a citation without \"The\"", (22, "PDF citation title", set()),
      g.cited('"No. 22—A French Crossword." Listener, 27 Aug. 1930, p. 308.'))
check("a competition's count is no puzzle number",
      (None, None, set()), g.cited('"Competition No. 8. " The Listener, vol. 3, no. 59, 26 Feb. 1930'))
check("a week with no crossword matches no date",
      None, g.by_date([{"number": 39, "title": "[No crossword]", "date": D(1930, 12, 24)}], D(1930, 12, 24)))

def line(text, x, y):
    out = []
    for w in text.split():
        out.append((x, y, x + 10 * len(w), y + 16, w))
        x += 10 * len(w) + 8
    return out

# DOWN under the across clues in the first column, running on into the second.
words = (line("Other article text", 100, 40) + line("ACROSS", 100, 100)
         + line("1 Spanish for aubade", 100, 130) + line("9 A river", 100, 160) + line("in France", 100, 190)
         + line("DOWN", 100, 230) + line("1 Animal in a zoo", 100, 260)
         + line("2 Composer of the Messiah", 600, 100) + line("12", 1100, 400))
cols = g.page_columns(words)
check("across clues, column order", ["1 Spanish for aubade", "9 A river", "in France"], [l[4] for l in cols[0]])
check("down runs on into the next column", ["1 Animal in a zoo", "2 Composer of the Messiah"],
      [l[4] for l in cols[1]])
parsed, _ = al.parse(al.tidy(al.text_of(cols)))
check("a clue a line without counts", ["Spanish for aubade", "A river in France"],
      [c["text"] for c in parsed["across"]])

# The 1930s layout: ACROSS centred over two columns under the grid, the
# across clues running on at the top of the next two columns, DOWN's
# heading unread, a misread "2." for "32.", and a report's prose after.
words = (line("12 13 14", 120, 60) + line("ACROSS", 300, 400)
         + line("1. Spanish for aubade", 100, 430) + line("An old song", 130, 450)
         + line("9. A river", 100, 480) + line("11. A brook", 100, 510)
         + line("26. A lake", 400, 430) + line("27. A sea", 400, 460) + line("30. A pond", 400, 490)
         + line("Some prose of another article", 700, 20)
         + line("40. A cape", 700, 100) + line("43. A bay", 700, 130)
         + line("45. A gulf", 1000, 100) + line("46. A sound", 1000, 130)
         + line("1. Animal in a zoo", 700, 220) + line("3. Bird of prey", 700, 250) + line("4. A fish", 700, 280)
         + line("13. A tree", 1000, 220) + line("2. A shrub", 1000, 250) + line("38. A flower", 1000, 280)
         + line("Report on Crossword No. 16", 700, 340) + line("We have to start with an apology", 700, 380)
         + line("1 Broom and the others", 700, 400))
cols = g.page_columns(words)
check("the 1930s across list in band order", ["1", "9", "11", "26", "27", "30", "40", "43", "45", "46"],
      [l[4].split(".")[0] for l in cols[0] if l[4][0].isdigit()])
check("its run-on line", "An old song", cols[0][1][4])
check("the down list without its heading, a misread number kept, no prose",
      ["1", "3", "4", "13", "2", "38"], [l[4].split(".")[0] for l in cols[1]])
words = (line("DOWN", 300, 400) + line("1. Knights", 100, 430) + line("2. A glutton", 100, 460)
         + line("3. That far", 100, 490) + line("ACROSS", 300, 530) + line("1. A hard stone", 100, 560)
         + line("10. Wherefore", 100, 590) + line("12. Porsena", 100, 620))
check("DOWN printed first", (["1. A hard stone", "10. Wherefore", "12. Porsena"], ["1. Knights", "2. A glutton", "3. That far"]),
      tuple([l[4] for l in c] for c in g.page_columns(words)))

# A heading centred over its column (No 103's): its clue numbers start far
# left of it, and an advert's text beside the column bridges the gutter.
words = (line("Kingfisher Library advert text runs wide here", 100, 380)
         + line("ACROSS", 700, 400) + line("1. First and last to some a sign at night", 520, 430)
         + line("7. A partner who excels is a wonder", 520, 460)
         + line("10. Last two letters of above", 520, 490) + line("DOWN", 700, 530)
         + line("1. A sign and a wonder of the world", 520, 560)
         + line("2. Wrote wonderful paraphrase of scripture", 520, 590) + line("3. Sign of a Saint", 520, 620)
         + line("advert words", 100, 470) + line("more advert", 100, 560))
check("a centred heading's list read from its clue numbers",
      (["1", "7", "10"], ["1", "2", "3"]),
      tuple([l[4].split(".")[0] for l in c] for c in g.page_columns(words) or ([], [])))

# Old-style figures read as letters open a clue all the same.
for text, want in [("I.", "1."), ("II. See 13.", "11. See 13."),
                   ("I3. Garden", "13. Garden"), ("O. Wonder", "O. Wonder"), ("Oo.", "Oo."),
                   ("I am here", "I am here"), ("12. A tree", "12. A tree"), ("1.An African bird", "1. An African bird"),
                   ("Io.Last two", "10. Last two"), ("at 8.15p.m.", "at 8.15p.m."),
                   ("20rev.,24.Charade:", "20 rev., 24. Charade:"), ("23rev.He'd", "23 rev. He'd"),
                   ("27rev.", "27 rev."), ("12. Revel", "12. Revel"), ("12 revels", "12 revels")]:
    check(f"figures: {text!r}", want, g.figures([(0, 0, 10, 16, text)])[0][4])

# No 97's page: the clue number set wide of its words (more than 40 px, under
# BESIDE heights), ACROSS centred under the grid and touching its first
# clue's line, DOWN at the top of the next column above it, its list broken
# by a gap after 3, and a report's notes below it.
def wide(n, text, x, y):
    return [(x, y - 2, x + 28, y + 18, n)] + line(text, x + 72, y)
words = ([(600, 1000, 700, 1024, "ACROSS")] + wide("I.", "Puzzler of one", 250, 1020)
         + wide("9.", "Such question", 250, 1050) + wide("II.", "To do this", 250, 1080)
         + wide("13.", "Of question", 250, 1110)
         + [(1500, 300, 1600, 324, "DOWN.")] + wide("I.", "This foreign boaster", 1150, 340)
         + wide("2.", "Add head", 1150, 370) + wide("3.", "A riddle", 1150, 400)
         + wide("9.", "Half sort", 1150, 520) + wide("10.", "Unpleasant jester", 1150, 550)
         + wide("12.", "A word for palm", 1150, 580)
         + line("Report on Crossword No. 95", 1150, 700)
         + wide("11.", "Anag. Greats.", 1150, 800) + wide("12.", "Hood: Epping Hunt.", 1150, 830)
         + wide("19.", "Sontag.", 1150, 860))
cols = g.page_columns(g.figures(words))
check("No 97's across list: wide-set numbers, a centred heading touching it",
      ["1", "9", "11", "13"], [l[4].split(".")[0] for l in cols[0]] if cols else None)
check("No 97's down list over its gap, the report's notes left out",
      ["1", "2", "3", "9", "10", "12"], [l[4].split(".")[0] for l in cols[1]] if cols else None)

# No 97's setter's note under DOWN 12 and a concert advert's heading under
# ACROSS 13 are no clue text: the column's lists end there.
words = ([(600, 1000, 700, 1024, "ACROSS")] + wide("I.", "Puzzler of one", 250, 1020)
         + wide("9.", "Such question", 250, 1050) + wide("II.", "To do this", 250, 1080)
         + wide("13.", "Of question", 250, 1110) + line("B.B.C. SYMPHONY CONCERT", 400, 1140)
         + line("In the Queen's Hall", 330, 1170)
         + [(1500, 300, 1600, 324, "DOWN.")] + wide("I.", "This foreign boaster", 1150, 340)
         + wide("2.", "Add head", 1150, 370) + wide("3.", "A riddle", 1150, 400)
         + wide("9.", "Half sort", 1150, 430) + wide("10.", "UNPLEASANT JESTER", 1150, 460)
         + wide("12.", "A word for palm", 1150, 490) + line("NoTE.--Clue for 3 down is in italics.", 1420, 515))
cols = g.page_columns(g.figures(words))
check("No 97: an advert's capitals and the setter's NOTE end the column's list",
      (True, True), (cols[0][-1][4].endswith("Of question"), cols[1][-1][4].endswith("A word for palm"))
      if cols else None)
check("a clue printed in capitals stays (mirror)", "10. UNPLEASANT JESTER",
      cols and next((l[4] for l in cols[1] if l[4].startswith("10")), None))

# No 9's page: ACROSS low on the left, so the columns right of it are read
# from the top, where the radio programmes' capitals stand over DOWN. Those
# capitals are above the lists, so the column's lists still follow; the
# same capitals under the lists end them (mirror).
def no9(advert_y):
    return ([(600, 3000, 700, 3024, "ACROSS")] + wide("1.", "Puzzler of one", 250, 3040)
            + wide("9.", "Such question", 250, 3070) + wide("11.", "To do this", 250, 3100)
            + line("FOREIGN STATIONS", 1200, 200) + line("SUNDAY, GOTTERDAMMERUNG", 1160, 240)
            + [(1500, 300, 1600, 324, "DOWN.")] + wide("1.", "This foreign boaster", 1150, 340)
            + wide("2.", "Add head", 1150, 370) + line("B.B.C. SYMPHONY CONCERT", 1300, advert_y)
            + wide("3.", "A riddle", 1150, 400) + wide("9.", "Half sort", 1150, 490)
            + wide("10.", "Unpleasant jester", 1150, 520))
# No 88's page: both lists in the left column, a report beside them whose
# prose quotes "for 1 Across (see notes)" and whose NOTES carry their own
# ACROSS and DOWN; a long clue line all but closes the gutter.
def no88(beside, notes=True):
    return ([(646, 1795, 747, 1812, "ACROSS")] + line("1. Her image.", 234, 1830)
            + line("14. Why hast thou nothing in thy face.", 234, 1860)
            + line("15. Four pounds of prunes and as many of the sun.", 234, 1890)
            + line("16. Found in arithmetic books.", 234, 1920)
            + [(654, 1960, 736, 1977, "DOWN")] + line("1. Accompaniment to dancing.", 234, 1990)
            + line("2. Infidels were blinded by the sight of it.", 234, 2020)
            + line("5. For whereso-e'er thou art in this world's globe, I'll have an", 234, 2050)
            + line("6. New.", 234, 2080)
            + beside + (notes and
            line("NOTES", 1500, 2200) + [(1360, 2240, 1462, 2257, "ACROSS")]
            + line("1. Lating night.", 1193, 2270) + line("5. Milton.", 1193, 2300)
            + [(1840, 2240, 1924, 2257, "DOWN")] + line("6. Burns.", 1668, 2270)
            + line("25. Gay.", 1668, 2300) + line("31. Keats.", 1668, 2330) or []))
cols = g.page_columns(g.figures(no88(
    line("wise correct. It was thought", 1176, 1795) + line("for 1 Across (see notes) in", 1176, 1825)
    + line("prominence given by some of", 1176, 1855) + line("the daily papers to the", 1176, 1885))))
check("No 88: the lists beside a report, its prose and NOTES left out",
      (["1", "14", "15", "16"], ["1", "2", "5", "6"]),
      tuple([l[4].split(".")[0] for l in c] for c in cols) if cols else None)
cols = g.page_columns(g.figures(no88(
    line("7. All downward to the banks of the river.", 1193, 1795)
    + line("8. rev. Would this be an accurate one?", 1193, 1825)
    + line("9. Turn to the left.", 1193, 1855), notes=False)))
check("a list running on at the next column's top is still read (mirror)",
      ["1", "2", "5", "6", "7", "8", "9"], [l[4].split(".")[0] for l in cols[1]] if cols else None)

# No 2's page: a prize notice set across the page under the lists, after
# a wider gap ("Mr. A. R. Morton, c/o Mrs. ..., 68 Essex Road, ... prize
# of Half-a-Guinea"), is no clue text, and its "68" is no clue; one
# reading loses the right half's notice words ("68 Essex I"), and the left
# half's notice still ends that column. The preamble's "No prizes will be
# offered" above the lists and a clue "A prize" inside them end nothing
# (mirrors).
def no2(right=("68 Essex Road,", "prize of Half-a-Guinea"), clue2="2. A basic volcanic rock.", apart=0):
    return (line("Crossword No. 2. No prizes will be offered,", 100, 900)
            + line("but any reader who sends a solution", 100, 930)
            + [(300, 1000, 400, 1016, "ACROSS")] + line("1. A covering.", 100, 1030)
            + line("33. Irish for juice.", 100, 1060) + line("34. An implement for writing.", 100, 1090)
            + line("Mr. A. R. Morton, c/o Mrs.", 100, 1140) + line("is invited to apply to us", 100, 1170)
            + [(800, 1000, 880, 1016, "DOWN")] + line("1. A covering.", 600, 1030)
            + line(clue2, 600, 1060) + line("35. A waterfall.", 600, 1090)
            + line(right[0], 640, 1140) + (line(right[1], 600, 1170 + apart) if right[1] else []))
# One reading sets "68 Essex I" further over its "prize" line than the
# notice's pitch: the paragraph still starts where the left half's does.
for what, page in (("the notice's words in both halves", no2()),
                   ("one reading lost the right half's notice words", no2(("68 Essex I", None))),
                   ("one reading set the right half's first notice line apart", no2(("68 Essex I", "prize of Half-a-Guinea"), apart=25))):
    cols = g.page_columns(g.figures(page))
    check(f"No 2: a prize notice under the lists ends them ({what})",
          (["1", "33", "34"], ["1", "2", "35"]),
          tuple([l[4].split(".")[0] for l in c] for c in cols) if cols else None)
cols = g.page_columns(g.figures(no2(clue2="2. A prize for writing.")))
check("a clue naming a prize, and the preamble's prizes, end nothing (mirror)",
      (["1", "33", "34"], ["1", "2", "35"], "2. A prize for writing."),
      (*(tuple([l[4].split(".")[0] for l in c] for c in cols)), cols[1][1][4]) if cols else None)

# No 3's page: ACROSS and DOWN low on the left under the grid, both lists
# running on at the top of the right half. The headings give only the
# first band; the clue numbers give all of it, so they are taken. Without
# the right half the two agree (mirror).
def no3(right_half):
    return ([(300, 1000, 400, 1016, "ACROSS")] + line("1. Hunted in India.", 100, 1030)
            + line("5. A town in the Punjab.", 100, 1060) + line("6. Site of an old town.", 100, 1090)
            + [(800, 1000, 880, 1016, "DOWN")] + line("1. A famous pass.", 600, 1030)
            + line("2. An exclamation.", 600, 1060) + line("3. Army Temperance.", 600, 1090)
            + (line("36. A not infrequent occurrence.", 1100, 200) + line("37. A town in Baltistan.", 1100, 230)
               + line("39. Junction for Dehra Dun.", 1100, 260) + line("16. Termination meaning meadow.", 1600, 200)
               + line("17. A town in Assam.", 1600, 230) + line("18. A capital of the Moghul Empire.", 1600, 260)
               if right_half else []))
cols = g.page_columns(g.figures(no3(True)))
check("No 3: the lists' second band, beyond the headings' reach",
      (["1", "5", "6", "36", "37", "39"], ["1", "2", "3", "16", "17", "18"]),
      tuple([l[4].split(".")[0] for l in c] for c in cols) if cols else None)
cols = g.page_columns(g.figures(no3(False)))
check("one band: the headings' lists (mirror)", (["1", "5", "6"], ["1", "2", "3"]),
      tuple([l[4].split(".")[0] for l in c] for c in cols) if cols else None)

cols = g.page_columns(g.figures(no9(900)))
check("No 9: capitals above the lists end no column",
      ["1", "2", "3", "9", "10"], [l[4].split(".")[0] for l in cols[1]] if cols else None)
cols = g.page_columns(g.figures(no9(445)))
check("capitals under a list's clue still end its column (mirror)",
      ["1", "2", "3"], [l[4].split(".")[0] for l in cols[1]] if cols else None)

# No 15's page: ACROSS under the grid, its list running on at the top of the
# next two columns over a centred DOWN; DOWN 22 straight under ACROSS 34 in
# the last column, a heading's space between; a report's prose quoting
# "38 Down" under the down list.
words = (line("ACROSS", 300, 1000) + line("7. A flying monkey", 100, 1030) + line("12. Spoken in Switzerland", 100, 1060)
         + line("13. The sort of name", 100, 1090) + line("14. A limestone cave", 600, 1030)
         + line("16. A real bug", 600, 1060) + line("17. Once", 600, 1090)
         + line("24. Stop", 1000, 100) + line("25. A dugout", 1000, 130) + line("26. A famous murderer", 1000, 160)
         + line("DOWN", 1250, 185) + line("1. The carousing of seamen", 1000, 215) + line("2. Potbellied", 1000, 245)
         + line("3. Initials of a writer", 1000, 275) + line("Report on Crossword No. 13", 1000, 330)
         + line("38 Down deserves a prize for this", 1000, 360)
         + line("32. Add head and tail", 1500, 100) + line("33. Squares of their body", 1500, 130)
         + line("34. One who uses a glass", 1500, 160) + line("22. Expressive slang", 1500, 210)
         + line("23. A printer might say", 1500, 240) + line("27. An Oriental theory", 1500, 270))
cols = g.page_columns(words)
check("No 15's lists: ACROSS over three columns, DOWN under it after a heading's space, no report prose",
      (["7", "12", "13", "14", "16", "17", "24", "25", "26", "32", "33", "34"], ["1", "2", "3", "22", "23", "27"]),
      tuple([l[4].split(".")[0] for l in c] for c in cols) if cols else None)

# No 15's down list: a clue ending short ("6. Lenten.") and the next one's
# number lost ("park" under it, set at the words' indent), then a list's
# footnote under its last clue.
words = (line("DOWN", 300, 1000) + line("5. A musical direction for the band to play", 100, 1030)
         + line("loud", 130, 1050) + line("6. Lenten.", 100, 1070) + line("park", 130, 1090)
         + line("9. A Scottish island off the west coast here", 100, 1120)
         + line("36. A blood fine paid by a murderer in", 100, 1150) + line("Ireland.", 130, 1170)
         + line("*One letter missing.", 130, 1200) + line("ACROSS", 300, 1300)
         + line("1. A flying monkey", 100, 1330) + line("2. Spoken in Switzerland", 100, 1360)
         + line("3. The sort of name", 100, 1390))
cols = g.page_columns(words)
check("a line under a short one is no run-on, nor is a footnote",
      ["5. A musical direction for the band to play", "loud", "6. Lenten.",
       "9. A Scottish island off the west coast here", "36. A blood fine paid by a murderer in", "Ireland."],
      [l[4] for l in cols[1]] if cols else None)
for text, want in [("28.tNot far", "28. \u2020Not far"), ("fA", "\u2020A"), ("29tA town", "29 \u2020A town"), ("29A town", "29 A town"), ("3D film", "3D film"), ("28.\u2020Not", "28. \u2020Not"),
                   ("tRNA", "tRNA"), ("Then", "Then"), ("TA", "TA")]:
    check(f"a footnote's dagger: {text!r}", want, g.figures([(0, 0, 10, 16, text)])[0][4])
check("a clue opening on a footnote's mark is one clue", (True, True, False),
      (al.sound("*God."), al.sound("\u2020Not far from 13"), al.sound("*one 12 Two")))

check("numbers read into one box over three lines go, as a speck's does (No 97's ch \"450\")",
      ["Why did"], [w[4] for w in g.figures([(100, 1085, 130, 1155, "450"), (160, 1090, 260, 1110, "Why did"),
                                 (160, 1115, 260, 1135, "In sol"), (160, 1140, 260, 1160, "He rid")])][:1])
check("a number one line tall stays (mirror)", ["450", "12."],
      [w[4] for w in g.figures([(100, 1085, 130, 1105, "450"), (100, 1110, 130, 1130, "12."),
                                 (160, 1140, 260, 1160, "He rid")])][:2])

# No 97's down list: the numbers of 4-8 lost (one read as a speck whose
# box spans three lines), as many lines as numbers between 3 and 7 here; No 17's
# grid numbers beside the list; one line lost between 10 and 13 of two
# numbers is no clue.
words = (line("DOWN", 300, 1000) + line("2. Add head and turn about you get here", 100, 1030) + line("3. A riddle", 100, 1060)
         + [(100, 1085, 112, 1140, "+")] + line("Why did", 160, 1090) + line("In sol", 160, 1120)
         + line("He rid", 160, 1150) + line("7. Half sort of Scottish guillotine here", 100, 1180) + line("21", 700, 1180)
         + line("22", 790, 1180) + line("10. Oxen.", 100, 1210) + line("Lost one", 160, 1240)
         + line("13. Last", 100, 1270)
         + line("ACROSS", 300, 1400) + line("1. A flying monkey", 100, 1430) + line("2. Spoken here", 100, 1460)
         + line("3. The sort of name", 100, 1490))
cols = g.page_columns(g.figures(words))
check("lost numbers put back when the gap counts them; grid numbers and an uncounted line left out",
      ["2. Add head and turn about you get here", "3. A riddle", "4. Why did", "5. In sol", "6. He rid",
       "7. Half sort of Scottish guillotine here", "10. Oxen.", "13. Last"], [l[4] for l in cols[1]] if cols else None)

# No 17's down list: a clue number whose box ran left over specks ("7."
# from x 784) set the column's edge into the across column; the entry
# form beside the list ("NAME....", two lines tall) joined 33's last line
# to 34's. No 15's 22 across ran on into the next article's title.
words = (line("ACROSS", 300, 1000) + line("1. Are acquired characteristics in-", 250, 1030)
         + line("11. Red.", 250, 1060) + line("12. A hairy caterpillar.", 250, 1090)
         + line("DOWN.", 1100, 1000) + line("1. A Mediterranean shrub.", 880, 1030)
         + line("2. An antidote to poison.", 880, 1060) + line("3. An astronomical term.", 880, 1090)
         + [(784, 1120, 903, 1138, "7.")] + line("Anag. of a lovely word", 920, 1120)
         + line("33. One shade the more, one ray the", 864, 1150) + line("less'.", 920, 1175)
         + [(1814, 1170, 2004, 1220, "NAME....")]
         + line("34. An anatomatical adjective of the", 864, 1200) + line("depression at the place", 920, 1225)
         + line("13. A rope stretched to prevent gear", 250, 1120) + line("from getting fouled.", 300, 1145)
         + [(330, 1175, 900, 1240, "Points from Letters")])
cols = g.page_columns(g.figures(words))
check("a number's box run left over specks sets no column edge; the form and a title stay out",
      (["1. Are acquired characteristics in-", "11. Red.", "12. A hairy caterpillar.",
        "13. A rope stretched to prevent gear", "from getting fouled."],
       ["1. A Mediterranean shrub.", "2. An antidote to poison.", "3. An astronomical term.",
        "7. Anag. of a lovely word", "33. One shade the more, one ray the", "less'.",
        "34. An anatomatical adjective of the", "depression at the place"]),
      tuple([l[4] for l in c] for c in cols) if cols else None)
check("a number's box too wide for it is cut to its right end (mirror: one that fits stays)",
      [(876, 1120, 903, 1138, "7."), (864, 1150, 900, 1170, "33.")],
      [w[:5] for w in g.figures([(784, 1120, 903, 1138, "7."), (864, 1150, 900, 1170, "33.")])])

# A clue line a RapidOCR reading lost its number on (No 15's "8. A park."
# read as "park") is read again alone, from the page words' number.
reads = []
def read_box(img, key, box, which):
    reads.append(box)
    return [(box[0] + 17, 848, box[0] + 30, 865, "8"), (1095, 848, 1112, 864, "A"), (1122, 848, 1181, 872, "park.")]
g.read_box, real_read_box = read_box, g.read_box
PAGE = type("Page", (), {"width": 3000, "height": 4000})()
page = [(1063, 828, 1080, 843, "6."), (1095, 827, 1175, 844, "Lenten."), (1064, 848, 1081, 865, "8."),
        (1095, 848, 1112, 864, "A"), (1122, 848, 1181, 872, "park.")]
mine = [(1058, 823, 1179, 846, "6. Lenten."), (1108, 849, 1170, 868, "park")]
got = sorted(w[4] for w in g.reread_lines(PAGE, "k", "ch", mine, [page]))
check("a line whose number a reading lost is read again alone, its stop put back",
      (["6. Lenten.", "8.", "A", "park."], 1), (got, len(reads)))
check("a line the reading has whole is not (mirror)", (["6. Lenten."], 1),
      (sorted(w[4] for w in g.reread_lines(PAGE, "k", "ch", mine[:1], [page[:2]])), len(reads)))
# No 97's DOWN 4-8: the page words lost the numbers and ch the lines, but
# en5 numbers them, so ch reads the line alone from en5's number.
reads.clear()
lost = [(1095, 827, 1175, 844, "Lenten."), (1095, 848, 1112, 864, "A"), (1122, 848, 1181, 872, "park.")]
en5 = [(1063, 828, 1080, 843, "6."), (1095, 827, 1175, 844, "Lenten."), (1064, 848, 1081, 865, "8."),
       (1095, 848, 1112, 864, "A"), (1122, 848, 1181, 872, "park.")]
check("a line only another reading numbers is read again alone",
      (["6. Lenten.", "8.", "A", "park."], 1),
      (sorted(w[4] for w in g.reread_lines(PAGE, "k", "ch", mine[:1], [lost, en5])), len(reads)))
reads.clear()
check("a number misread as letters (No 97's \"DI.\" for \"11.\") is no number: the line is read again",
      (["6. Lenten.", "8.", "A", "park."], 1),
      (sorted(w[4] for w in g.reread_lines(PAGE, "k", "ch", mine[:1] + [(1064, 848, 1081, 865, "DI.")], [en5])),
       len(reads)))
def read_box(img, key, box, which):
    reads.append(box)
    return [(1064, 848, 1081, 865, "8."), (1095, 848, 1181, 868, "A park."), (1095, 858, 1181, 876, "saidthis")]
g.read_box = read_box
tight = mine[:1] + [(1095, 859, 1181, 875, "'Tis said this")]
check("a line set close under the one read again is kept, not taken from the crop",
      ["'Tis said this", "6. Lenten.", "8.", "A park."],
      sorted(w[4] for w in g.reread_lines(PAGE, "k", "ch", tight, [en5])))
check("the line read again is still put in (mirror)", True,
      "8." in [w[4] for w in g.reread_lines(PAGE, "k", "ch", tight, [en5])])
def read_box(img, key, box, which):
    reads.append(box)
    return [(1064, 848, 1081, 865, "II."), (1095, 848, 1181, 868, "A park.")]
g.read_box = read_box
check("a line read again whose number reads as letters (\"II.\") is put in as 11",
      ["11.", "6. Lenten.", "A park."], sorted(w[4] for w in g.reread_lines(PAGE, "k", "ch", mine[:1], [en5])))
reads.clear()
check("a line no reading numbers is not (mirror)", (["6. Lenten."], 0),
      (sorted(w[4] for w in g.reread_lines(PAGE, "k", "ch", mine[:1], [lost])), len(reads)))
g.read_box = real_read_box

# No 97's "20 rev., 24.": one clue for two lights, the first reversed, laid
# in the corpus's linked form; a reversed light alone keeps its "rev.".
parsed = al.by_lines("ACROSS\n19. See 1 across.\n20 rev., 24. Charade: components I postpone.\n"
                     "21. An African for riddles known.\nDOWN\n23 rev. He'd nothing solve.\n26. This, how to pay.")
laid = al.lay(parsed)
check("one clue for two lights: the group on the first, the clue its words",
      ("rev. Charade: components I postpone.", ["20-across", "24-across"]),
      laid["20-across"][::2])
check("a reversed light alone is a sound clue with its rev.", (True, "rev. He'd nothing solve."),
      (al.sound(laid["23-down"][0]), laid["23-down"][0]))
check("a plain clue has no group (mirror)", None, laid["21-across"][2])
def linked_page(c20):
    return (line("ACROSS", 100, 100) + line("19. See 1 across.", 100, 130) + line(c20, 100, 160)
            + line("21. An African for riddles known.", 100, 190) + line("DOWN", 100, 230)
            + line("1. The carousing of seamen.", 100, 260) + line("2. Potbellied.", 100, 290))
_, laid = al.vote({k: linked_page("20 rev., 24. Charade: components I postpone.") for k in "abc"}, {}, cols=g.page_columns)
check("the vote keeps a linked clue's words, and lays See 20 on its second light",
      ("rev. Charade: components I postpone.", ("See 20", None, None)), (laid["20-across"][0], laid.get("24-across")))
_, laid = al.vote({k: linked_page("20. revels in it.") for k in "abc"}, {}, cols=g.page_columns)
check("a clue that opens mid-word is still blank, with no light laid after it (mirror)",
      ("", None), (laid["20-across"][0], laid.get("24-across")))

# No 97's 34D: two readers take its stops for commas ("34 rev, ... kind,"),
# outvoting "rev." and leaving "kind,."; that is no run-on.
_, laid = al.vote({"a": linked_page("23 rev. Its rite's of a deceptive kind."),
                   "b": linked_page("23 rev. Its rite's of a deceptive kind."),
                   "c": linked_page("23 rev, Its rite's of a deceptive kind,"),
                   "d": linked_page("23 rev, Its rite's of a deceptive kind,")}, {}, cols=g.page_columns)
check("a reversed light's stops voted to commas: still its rev. and one end mark",
      "rev. Its rite's of a deceptive kind.", laid.get("23-across", ("MISSING",))[0])
_, laid = al.vote({k: linked_page("23. Revel, Its rite's of a deceptive kind.") for k in "abcd"}, {}, cols=g.page_columns)
check("a word opening on rev is no reversed light's head (mirror)",
      "Revel, Its rite's of a deceptive kind.", laid.get("23-across", ("MISSING",))[0])

# Azed 1874's readers lost 8 down's count: the scan's grid counts each
# light, so the vote is given the grid's lengths and such a clue is voted
# on (reconcile counts it), not held for "no count read".
seen_lengths = []
real_reconcile = al.ocr_clues.reconcile
def spy(laid, streams, lengths=None, **kw):
    seen_lengths.append(dict(lengths or {}))
    return real_reconcile(laid, streams, lengths, **kw)
al.ocr_clues.reconcile = spy
al.vote({k: linked_page("20. A fine bust, trembling?") for k in "abc"}, {}, cols=g.page_columns,
        lengths={"20-across": 7})
al.vote({k: linked_page("20. A fine bust, trembling?") for k in "abc"}, {}, cols=g.page_columns)
al.ocr_clues.reconcile = real_reconcile
check("the grid's lengths reach the vote", 7, seen_lengths[0].get("20-across"))
check("with no grid the vote has none (mirror)", None, seen_lengths[1].get("20-across"))
check("reconcile counts a clue no reading counted by its light", ("A fine bust, trembling?", "7"),
      al.ocr_clues.reconcile({"2-across": ("A fine bust, trembling?", None, None)},
                             ["2 A fine bust, trembling? 3 Next"], {"2-across": 7})[0]["2-across"][:2])
check("and holds it with no length (mirror)", "no count read",
      al.ocr_clues.reconcile({"2-across": ("A fine bust, trembling?", None, None)},
                             ["2 A fine bust, trembling? 3 Next"], {})[1].get("2-across"))

# A page that prints the clues or the diagram on another page says which.
check("the pages it sends to, over a line break; a report's page is none",
      [675, 885, 1057], g.elsewhere(line("Closing date: Tuesday. Diagram", 100, 100) + line("and rules on page 885.", 100, 120)
                               + line("Prize and rules on page 675.", 100, 200)
                               + line("(FOR CLUES SEE PAGE 1057)", 100, 300)
                               + line("Report on Crossword No. 101 on page 319.", 100, 500)))

# The ledger: each file read once, again when it changes.
# A blank page has no title to read, and the test asks nothing of Tesseract.
g.page_words = lambda img, key: []
inbox, store = Path(sys.argv[1]) / "inbox", Path(sys.argv[1]) / "store"
inbox.mkdir()
Image.new("RGB", (300, 200), "white").save(inbox / "1930-04-02.png")
Image.new("RGB", (300, 200), "white").save(inbox / "holiday snap.jpg")
reads = []
def reader(m):
    reads.append(m["file"])
    return {"clues": 1, "agreed": 1}, {"1-across": ("Spanish for aubade", None, None)}
out = open("/dev/null", "w")
g.run(inbox, store, rows, out=out, reader=reader)
check("a dated page read, the unnamed one not", ["1930-04-02.png"], reads)
check("its reading", "Spanish for aubade",
      json.loads((store / "listener-1.json").read_text())["clues"]["1-across"]["text"])
g.run(inbox, store, rows, out=out, reader=reader)
check("nothing read twice", 1, len(reads))
Image.new("RGB", (300, 201), "white").save(inbox / "1930-04-02.png")
import subprocess
def slow(m):
    raise subprocess.TimeoutExpired("tesseract", 300)
Image.new("RGB", (300, 199), "white").save(inbox / "1930-04-02.png")
g.run(inbox, store, rows, out=out, reader=slow)
check("a Tesseract timeout is no reading: the file stays to read", False,
      g.file_hash(inbox / "1930-04-02.png") in g.load_ledger(store))
def broken(m):
    raise RuntimeError("the reader fell over")
Image.new("RGB", (300, 198), "white").save(inbox / "1930-04-02.png")
g.run(inbox, store, rows, out=out, reader=broken)
check("a page whose read raises is ledgered with its error, its number kept",
      (1, "read failed: RuntimeError: the reader fell over"),
      next((e["number"], e["why"]) for e in g.load_ledger(store).values() if e["file"] == "1930-04-02.png"
           and e["why"]))
Image.new("RGB", (300, 201), "white").save(inbox / "1930-04-02.png")
g.run(inbox, store, rows, out=out, reader=reader)
check("a changed file read again", 2, len(reads))
real_match = g.match
g.match = lambda p, idx, **k: {"file": p.name, "number": None, "reports": [1], "pages": []}
Image.new("RGB", (300, 202), "white").save(inbox / "report.png")
g.run(inbox, store, rows, out=out, reader=reader)
check("a report-only page is not lost", ([1], None),
      next((e["reports"], e["why"]) for e in g.load_ledger(store).values() if e["file"] == "report.png"))
(inbox / "report.png").unlink()
g.match = real_match

root = Path(sys.argv[1]) / "repo"
(root / "puzzles" / "listener" / "1930").mkdir(parents=True)
(root / "puzzles" / "listener" / "1930" / "listener-2.json").write_text("{}")
page = g.checklist(rows, store, root)
check("the saved puzzle is marked", True, "saved: 1 of 1 clues read" in page)
check("the filed puzzle is marked", True, ">filed<" in page)
check("the unmatched file is listed", True, "holiday snap.jpg" in page)
check("a saved solution is marked", True, "solution saved" in page)
bare = g.checklist(rows, Path(sys.argv[1]) / "nostore", Path(sys.argv[1]) / "none", arrivals=[])
check("a session link, then a Listener search on each puzzle still to save, in next up and its year", (True, 4),
      (g.gi.SESSION.format("LSNR") in bare, bare.count("prodId=LSNR")))
check("next up lists them with the ordering rule, refilling itself (no Next batch)", (True, False),
      ('<table id="next">' in bare and g.ORDER in bare and '<table id="done">' in bare, "nextBatch" in bare))
check("nothing on the page asks for a rename", False, "Rename it" in page)
check("years collapsed", True, "<details><summary><b>1930</b>" in bare)
check("no search link once a puzzle is saved or filed", 0, page.count("prodId=LSNR"))
inbox2, store2 = Path(sys.argv[1]) / "inbox2", Path(sys.argv[1]) / "store2"
inbox2.mkdir()
Image.new("RGB", (300, 203), "white").save(inbox2 / "1930-04-09.png")
g.run(inbox2, store2, rows, out=out, reader=reader)
page2 = g.checklist(rows, store2, Path(sys.argv[1]) / "none", arrivals=[])
check("a read puzzle's missing solution is asked for", True,
      "save its solution too: “Report on Crossword No. 2”" in page2)
check("and offers its solution as the row's job", True, 'data-k="r2"' in page2)
check("still asked for while an unrelated saved file waits to be read", True, "save its solution too:" in g.checklist(
    rows, store2, Path(sys.argv[1]) / "none", arrivals=[{"file": "new.pdf", "number": 1}]))
check("earliest first", True, page.index("Wed 02 Apr 1930") < page.index("Wed 09 Apr 1930"))
# A page that sends its grid or clues to another page (No 24's "see page
# 381") files only with that page too: the checklist asks for it in next up.
inbox3, store3 = Path(sys.argv[1]) / "inbox3", Path(sys.argv[1]) / "store3"
inbox3.mkdir()
Image.new("RGB", (300, 204), "white").save(inbox3 / "1930-04-09.png")
g.run(inbox3, store3, rows, out=out, reader=lambda m: ({"clues": 1, "agreed": 1, "seePages": [381]},
                                                       {"1-across": ("Spanish for aubade", None, None)}))
page3 = g.checklist(rows, store3, Path(sys.argv[1]) / "none", arrivals=[])
next3 = page3.split('<table id="next">')[1].split("</table>")[0]
check("a read page's other page is asked for in next up, as the row's job", (True, True),
      ("save p. 381 of this issue too" in next3, 'data-k="e2"' in next3))
check("mirror: a read page that sends nowhere asks for no other page", False, "of this issue too" in page2)
Image.new("RGB", (300, 205), "white").save(inbox3 / "1930-04-09 p381.png")
g.run(inbox3, store3, rows, out=out, reader=lambda m: ({"refused": "no clue list on the page"}, None))
check("mirror: once a second page of the puzzle is saved, it is not asked for", False,
      "of this issue too" in g.checklist(rows, store3, Path(sys.argv[1]) / "none", arrivals=[]))
inbox4, store4 = Path(sys.argv[1]) / "inbox4", Path(sys.argv[1]) / "store4"
inbox4.mkdir()
Image.new("RGB", (300, 206), "white").save(inbox4 / "1930-04-09.png")
g.run(inbox4, store4, rows, out=out, reader=lambda m: ({"refused": "no clue list on the page (it sends to p. 1057)",
                                                        "seePages": [1057]}, None))
check("a refused page's other page is asked for too (the ledger keeps where it sends)", True,
      "save p. 1057 of this issue too" in g.checklist(rows, store4, Path(sys.argv[1]) / "none", arrivals=[]))

# The 3-minute tick: a page matched by its name alone is ticked off as
# arrived before the full pass reads it; one naming no puzzle waits for it.
Image.new("RGB", (300, 200), "white").save(inbox / "Listener 9 Apr 1930.png")
Image.new("RGB", (300, 200), "white").save(inbox / "download.png")
came = g.arrived(inbox, rows, Path(sys.argv[1]) / "arrived.json")
check("arrivals matched by name, no OCR", {"1930-04-02.png": 1, "Listener 9 Apr 1930.png": 2, "download.png": None,
                                           "holiday snap.jpg": None},
      {a["file"]: a["number"] for a in came})
g.match = lambda *a, **k: (_ for _ in ()).throw(AssertionError("opened again"))
check("a file already matched is not opened again", 4, len(g.arrived(inbox, rows, Path(sys.argv[1]) / "arrived.json")))
(root / "puzzles" / "listener" / "1930" / "listener-2.json").unlink()
page = g.checklist(rows, store, root, arrivals=came)
check("an arrived page is ticked off", True, "arrived: the full pass reads it at its next slice" in page)
check("and counted by the files downloaded", True, "<b id=\"count\">4 of 4</b> files downloaded" in page)
check("a page naming no puzzle waits for the pass", True, "<li><b>download.png</b>: arrived, puzzle not yet known" in page)
check("one the pass already read is not waiting", False,
      "<li><b>holiday snap.jpg</b>: arrived, puzzle not yet known" in page)
row1 = next(r for r in page.split("\n") if 'data-k="p2"' in r)
check("an arrived puzzle's row says so and offers no Download", (True, False, False),
      ('data-in="1"' in row1, "Open in Gale" in row1, 'class="dl"' in row1))

# One page for both papers: gale_inbox.page builds both, and this module
# holds no page markup of its own.
import re
import inspect
src = inspect.getsource(g.checklist) + inspect.getsource(g.render) + "".join(g.STEPS) + g.UNKNOWN + g.ORDER
check("the Listener's checklist writes no page structure of its own", [],
      re.findall(r"</?(?:html|head|meta|title|style|script|h1|h2|div|p|ol|ul|li|table|tr|td|th|details|summary|"
                 r"progress|span|button)\b", src))
gi = g.gi
gi.held, gi.usual_pages, gi.archive_coverage.ledger = (lambda: {}), (lambda: {}), (lambda: {})
un = Path(sys.argv[1]) / "un.json"
un.write_text(json.dumps([{"file": "x.pdf", "why": "nothing"}]))
times = gi.checklist([(D(1988, 1, 13), "no-scan")], Path(sys.argv[1]) / "nocache", un, docs={})
listener = g.checklist(rows, Path(sys.argv[1]) / "nostore", Path(sys.argv[1]) / "none",
                       arrivals=[{"file": "x.pdf", "number": None, "reports": []}], docs={})
def skeleton(page):
    """The page's tags with every text, attribute value, table, list and
    script body gone: what is left is the shell either paper shares."""
    s = re.sub(r"<script>.*?</script>", "<script/>", page, flags=re.S)
    s = re.sub(r"<(table|ol|ul)\b.*?</\1>", r"<\1/>", s, flags=re.S)
    s = re.sub(r'="[^"]*"', "", re.sub(r">[^<]*<", "><", s))
    return re.sub(r"^[^<]*|[^>]*$", "", s)
check("the Times and Listener pages share one skeleton", skeleton(times), skeleton(listener))
check("and one script, but for the paper's store and status file", True,
      re.sub(r'const S=.*?,SRC=[^,]*,|PAGE=\d+', "", re.search(r"<script>.*?</script>", times, re.S).group(0))
      == re.sub(r'const S=.*?,SRC=[^,]*,|PAGE=\d+', "", re.search(r"<script>.*?</script>", listener, re.S).group(0)))
check("each paper's status file is its own", True,
      'SRC="Checklist.status.js"' in times and 'SRC="Listener%20checklist.status.js"' in listener)
# The Guardian's Azed scans (tools/andlit_azed.py): ACROSS and DOWN level,
# bare clue numbers, a gutter of ~50px a reader's words may bridge.
def azed(down_y=100, down="DOWN", gutter=50, extra=()):
    right = 10 + 360 + gutter
    words = line("ACROSS", 10, 100) + line(down, right, down_y)
    for k, n in enumerate((1, 7, 10)):
        words += line(f"{n} Clue words set wide right up to here", 10, 130 + 30 * k)
    for k, n in enumerate((1, 2, 3)):
        words += line(f"{n} Down clue", right, 130 + 30 * k)
    return words + list(extra)
def heads(words):
    cols = g.page_columns(words)
    return cols and tuple([l[4].split()[0] for l in c] for c in cols)
want = (["1", "7", "10"], ["1", "2", "3"])
check("Azed: both lists", want, heads(azed()))
check("Azed: a speck in the gutter parts no list", want, heads(azed(extra=[(400, 160, 406, 176, "|")])))
check("Azed: a DOWN read above ACROSS still heads its list", want, heads(azed(down_y=70)))
words = line("ACROSS", 10, 100) + line("DOWN", 420, 100)
for k, n in enumerate((1, 7, 10)):
    words += line(f"{n} Clue words set wide to here", 10, 130 + 60 * k) + line("(12, 3 words)", 200, 160 + 60 * k)
for k, n in enumerate((1, 2, 3)):
    words += line(f"{n} Down clue", 420, 130 + 30 * k)
check("Azed: counts run on to their own lines are no clue column",
      (["1", "(12,", "7", "(12,", "10", "(12,"], ["1", "2", "3"]), heads(words))
check("Azed: a gutter too narrow to see parts the lists at DOWN's numbers", want, heads(azed(gutter=20)))
lent = g.lend_heads({"a": azed(), "b": azed(down="DOVVN")})
check("Azed: a reading misreading DOWN is lent the other's", want, heads(lent["b"]))
check("Azed: and keeps no word of its own there", False, any(w[4] == "DOVVN" for w in lent["b"]))
# Clue lists: linked heads, misread heads, one reader's number (No 103, No 9).
lined = al.by_lines(al.tidy("ACROSS\n24. Another.\n29, 39. In wonderful poem.\n32, 39 Sign of a tavern.\n"
                            "DOWN\n4. Student.\n5rey.Last word.\n20 rev., 24. Charade: x.\n"))
check("a plain linked head groups its lights (No 103 \"29, 39.\")", [[{29}, {39}], [{32}, {39}]],
      [c["tokens"] for c in lined["across"][1:]])
check("a clue opening on a comma is no linked head (mirror)", [[{20}]],
      [c["tokens"] for c in al.by_lines("ACROSS\n20, Has wonderfully calming effect.\nDOWN\n1. A.\n")["across"]])
check("rev. read \"rey.\" and glued to its number (No 103 5D)", ([{5}], "rev. Last word."),
      (lined["down"][1]["tokens"], lined["down"][1]["text"]))
check("the No 97 head \"20 rev., 24.\" stays linked (mirror)", ([{20}, {24}], "rev. Charade: x."),
      (lined["down"][2]["tokens"], lined["down"][2]["text"]))
check("a cross-reference with its 1 read as I is laid (No 103 11A)", ("See 13.", None, None),
      al.lay(al.by_lines(al.tidy("ACROSS\n11. SeeI3.\nDOWN\n1. A.\n")))["11-across"])
guess = set()
laid = al.lay(al.by_lines("ACROSS\n10. Last two.\n37. Removes.\n10. Often forbidden.\nDOWN\n1. A.\n"), guess)
check("a number below the last never displaces a light laid in order (No 103's \"10.\" for 40)",
      ("Last two.", set()), (laid["10-across"][0], guess))
guess = set()
laid = al.lay(al.by_lines("ACROSS\n37. Removes.\n4 Often forbidden.\nDOWN\n1. A.\n"), guess)
check("a light only a number below the last lays is a guess (mirror)", {"4-across"}, guess)
one = [{"40-across": ("Often forbidden by sign.", None, None), "42-across": ("This belongs.", None, None)},
       {"42-across": ("This belongs.", None, None)}]
check("one reader's number, every reader's words (No 103 40A)", "Often forbidden by sign.",
      al.pick(one, ["40. Often forbidden by sign.", "Often forbidden by sign.\n42. This belongs."])["40-across"][0])
check("no other reading prints the words: blank (mirror)", "",
      al.pick(one, ["40. Often forbidden by sign.", "42. This belongs."])["40-across"][0])
rival = [one[0], {"42-across": ("This belongs.", None, None), "41-across": ("Often forbidden by sign.", None, None)}]
check("another reading numbers the words as another light in order: blank (mirror)", "",
      al.pick(rival, ["40. Often forbidden by sign.", "41. Often forbidden by sign."])["40-across"][0])
runon = [{"44-across": ("rev. Its waters credited with powers.", None, None)},
         {"43-across": ("Wrote the 19. rev. Its waters credited with powers.", None, None)}]
check("a run-on into the words is no rival (No 103 44A)", "rev. Its waters credited with powers.",
      al.pick(runon, ["44 rev. Its waters credited with powers.",
                      "43. Wrote the 19.\nrev. Its waters credited with powers."])["44-across"][0])
short = [{"38-down": ("God,", None, None)}, {}]
check("a word or two one reading numbers is no clue another reading vouches for (No 15 38D)", "",
      al.pick(short, ["38. God,", "God, and man."])["38-down"][0])
two = [{"58-down": ("The top of the head. Italian police.", None, None)},
       {"56-down": ("*The top of the head.", None, None)}]
check("a clue holding another light's whole clue is a run-on, no clue (No 17 58D)", "",
      al.pick(two, ["58. The top of the head. Italian police.", "56. The top of the head.\nItalian police."])["58-down"][0])
check("words run together are split where another reading parts them (No 9 39A)",
      "of a reddish pulp used to add colour",
      al.unjoined({"a": "ofa reddish pulp usedtoaddcolour", "b": "of a reddish pulp usedto add colour",
                   "c": "x used to add colour"})["a"])
check("a known word another reading parts stays whole (mirror)", "cannot",
      al.unjoined({"a": "cannot", "b": "can not"})["a"])

# A VERSION bump reads every saved page again.
import tempfile
with tempfile.TemporaryDirectory() as tmp:
    inbox, store = Path(tmp) / "in", Path(tmp) / "store"
    inbox.mkdir(); store.mkdir()
    (inbox / "a.pdf").write_bytes(b"a")
    (inbox / "b.pdf").write_bytes(b"b")
    rows = [{"sha": g.file_hash(inbox / "a.pdf"), "version": g.VERSION - 1},
            {"sha": g.file_hash(inbox / "b.pdf"), "version": g.VERSION}]
    (store / g.LEDGER).write_text("".join(json.dumps(r) + "\n" for r in rows))
    planned = [u["rel"] for u in g.plan(inbox, store)]
    check("a page read at an older VERSION is read again", True, "a.pdf" in planned)
    check("a page read at this VERSION is not (mirror)", False, "b.pdf" in planned)

# Report lookups: a saved puzzle is asked for while a file is unread; an
# upcoming one too; a puzzle whose report arrived, read or not, is not.
with tempfile.TemporaryDirectory() as tmp:
    store, root = Path(tmp) / "store", Path(tmp) / "root"
    store.mkdir(); root.mkdir()
    idx = [{"number": n, "title": "T", "setter": None, "date": D(1930, 4, 2) + datetime.timedelta(days=7 * n)}
           for n in (1, 2, 3, 4)]
    (store / "listener-2.json").write_text(json.dumps({"number": 2, "verdict": {}}))
    arrivals = [{"file": "unread.pdf", "number": 3, "reports": [1]}]
    got = [r["number"] for r in g.report_lookups(idx, store, root, arrivals)]
    check("reports looked up for a saved and an upcoming row, not one whose report arrived unread", [2, 4], got)
    check("unsolved lists a saved puzzle though a file is unread", [2], [r["number"] for r in g.unsolved(idx, store, arrivals)])
    # An upcoming row offers its solution beside its Download once the report link is cached.
    day4 = idx[3]["date"]
    ent = lambda doc, day: {"doc": doc, "title": "T", "page": 1, "records": ["r"], "day": day.isoformat()}
    docs = {f"LSNR/{day4.isoformat()}": ent("D4", day4), "LSNR/report/4": ent("R4", day4 + datetime.timedelta(days=14))}
    row4 = next(r for r in g.checklist(idx, store, root, arrivals=arrivals, docs=docs).split("\n") if 'data-k="p4"' in r)
    check("an upcoming row offers Download, then Download solution", (True, True),
          ("Download</a>" in row4, "Download solution</a>" in row4 and row4.index("Download</a>") < row4.index("Download solution")))
    row4 = next(r for r in g.checklist(idx, store, root, arrivals=arrivals, docs={f"LSNR/{day4.isoformat()}": docs[f"LSNR/{day4.isoformat()}"]}).split("\n") if 'data-k="p4"' in r)
    check("and no solution link before it is cached", False, "Download solution" in row4)

print(f"FAILS {fails}")
sys.exit(1 if fails else 0)
PY
