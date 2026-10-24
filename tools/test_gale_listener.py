#!/usr/bin/env python3
# Does a saved Listener page (tools/gale_listener.py)
# match its puzzle by the date or number in its name, the Gale citation or
# its title, a report page as the solution of the puzzle it names; are its
# clue lists read in column order wherever DOWN falls, the 1930s lists by
# their numbers in bands across two columns when a heading goes unread, a
# clue a line when the lists print no counts; is each file read once (the
# ledger is keyed by its hash; one whose OCR times out stays unread); is a
# read on the desktop the read here, its OCR and grids kept here, a page's
# grids found there cached as found here; does wanted() ask
# tools/gale_fetch.py for every printed puzzle not filed or read, earliest
# first, and each one's missing solution report; and is a downloaded page
# saved whole under a name match() reads?
#
#     python3 tools/test_gale_listener.py
#
# Synthetic rows and words in a temp dir: no OCR, nothing asked of the Mac,
# Gale or listenercrossword.com, nothing written outside it.
import os
import sys
import atexit
import shutil
import tempfile
os.chdir(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
atexit.register(shutil.rmtree, tmp, True)
sys.argv[1:] = [tmp]

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
check("a thousands comma is one number, not No 1", (1001, "PDF citation title", set()),
      g.cited('"Crossword No. 1,001. " The Listener, 2 June 1949, p. 42.'))
check("Gale's \"1.403\" and \"1, 349\" alike", [1403, 1349],
      [g.cited(f'"Crossword No. {n}. " The Listener, 18 Apr. 1957')[0] for n in ("1.403", "1, 349")])
check("a report's comma number", (None, None, {1309}), g.cited('"Report on Crossword No. 1,309. " The Listener'))
check("\"Notes on\" is a report", (None, None, {287}), g.cited('"Notes on Crossword No. 287. " The Listener'))
check("a pointer to a report on another page is none (No 17's page, 1930), a report's heading is",
      [[], [], ["17"]], [g.REPORT.findall("missing. (The Report on Crossword No. 15 twill be found on page 155)"),
                         g.REPORT.findall("(The report on Crossword No 18 gill be found on the next page)"),
                         g.REPORT.findall("Report on Crossword No. 17\nIt is difficult to say why fifty-nine")])
check("a page's title is its own number, not a report's it points to (No 17, 1930)", "17",
      g.title_of("(The Report on Crossword No. 15 twill be found on page 155)\nCrossword No. 17\nCLUES").group(1))
check("the week's puzzle printed: its CLUES heading, its title read \"(rossword\", its entry form",
      [True, True, True], [g.puzzle_here(t, 147) for t in
                           ("CLUES\nACROSS", "This Weeks (rossword", "Prize: The Adventures of the Black Girl")])
check("its own number titled, not as the report's", [True, False],
      [g.puzzle_here("No, 123 Old Wives' Tales", 123), g.puzzle_here("Report on (Crossword No. 123", 123)])
check("a report's notes, rules and pointer are no puzzle (mirror)", False,
      g.puzzle_here("Report on Crossword No. 138\nNOTES\nAcross. 11\nPrizewinners: A. B.\n2. Clues are not given\n"
                    "This Week's Crossword is printed on page 709", 140))
check("a pointer to the week's puzzle elsewhere, or a report's heading, is no puzzle but says so",
      [False, False, True, True],
      [g.puzzle_here(t, 151) for t in ("This week's Crossword will be found on page vii", "This weeks Crossword\nbe - -")]
      + [bool(g.ELSEWHERE.search(t)) for t in ("This week's Crossword will be found on page vii",
                                               "Report on (rossword Vo. 144 (reek")])
check("two lights' numbers run into the first word are parted",
      ["9,36. Inversely top-shaped.", "16&17*. What happens"],
      [w[4] for w in g.figures([(0, 0, 300, 30, "9,36.Inversely top-shaped."), (0, 40, 300, 70, "16&17*.What happens")])])
# No 141 (1932): numbers set in their own column ~125 px left of the texts.
table = [(100, 40 * i, 140, 40 * i + 22, f"{n}.") for i, n in enumerate((12, 13, 14, 19, 22))] \
    + [(265, 40 * i, 600, 40 * i + 22, f"Clue {n} words.") for i, n in enumerate((12, 13, 14, 19, 22))] \
    + [(119, 200, 136, 222, "I"), (265, 200, 600, 222, "One of the accompaniments.")]
hung = g.hanging_numbers(table)
check("a table's numbers set beside their clues, a lone I there read 1",
      [(213, 253, "12."), (236, 253, "1.")], [(hung[0][0], hung[0][2], hung[0][4]), (hung[10][0], hung[10][2], hung[10][4])])
near = table[:2] + [(150, w[1], 485, w[3], w[4]) for w in table[5:7]]
check("numbers beside their clues already stay put (mirror)", near, g.hanging_numbers(near))
dot_mark, dot_opens, dot_split = g.DOTTED
check("the 1949-90 run-on lists: each \"N.\" after a stop or count opens a clue, run on with no space too",
      ["1", "5", "6", "7", "24"],
      [m.group(1) for m in dot_mark.finditer("1. Not a bag (8). 5. Bold widow (6). 6. Final （7).7.‘The road (9). "
                                             "24. 7, for example (5).") if dot_split.match(m.string, m.start())])
check("its opens follow a count: a 1930s line read across two columns is no paragraph (mirror)", [3, 0],
      [len(dot_opens.findall("soldier (8). 5. Bold (6). 10. No place (9). 11. It is")),
       len(dot_opens.findall("1. Hector did not see this dawn. 25. Behead the word."))])
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

check("a DOWN set a little left under ACROSS is still read in its column (mirror)",
      (["1", "7", "10"], ["1", "2", "3"]),
      tuple([l[4].split(".")[0] for l in c] for c in g.page_columns(
          [w if w[4] != "DOWN" else (670, 530, 710, 546, "DOWN") for w in words]) or ([], [])))

# No 4's lists either side of its map: ACROSS centred over two columns at
# the top right, DOWN under the map in the left column, centred over two
# columns of its own, an article's prose beside it.
words = (line("St. Cross", 400, 1320) + line("ACROSS", 1970, 1300)
         + line("3. Add an E", 1450, 1340) + line("6. A king", 1450, 1370) + line("8. A shame", 1450, 1400)
         + line("18. Found in England", 2080, 1340) + line("22. An eagle", 2080, 1370)
         + line("The Scientific Crossword Solution", 1450, 1800)
         + line("DOWN", 743, 3326) + line("1. Our subject", 220, 3370) + line("2. An Englishman", 220, 3400)
         + line("4. A family", 220, 3430)
         + line("20. Add an M", 830, 3370) + line("26. A form", 830, 3400)
         + line("Writers and readers alike will say", 1450, 3330) + line("that prose is no clue", 1450, 3360))
check("lists either side of a map, each read from its own heading's column",
      (["3", "6", "8", "18", "22"], ["1", "2", "4", "20", "26"]),
      tuple([l[4].split(".")[0] for l in c] for c in g.page_columns(words) or ([], [])))

# No 3's "6o. A resin." read "6." under 58 across, DOWN's heading unread:
# the small-o 0 put back;
# a "6." after a list's restart gap, or one standing for a number more
# than ZERO_STEP past the clue before it, is read as printed.
def no3(gap, n="6"):
    return (line("ACROSS", 200, 100) + line("56. A small coin.", 100, 130) + line("57. A great part", 100, 160)
            + line("58. A large number.", 100, 190) + line(f"{n}. A resin.", 100, 220 + gap)
            + line("62. A fairly common ending", 100, 250 + gap)
            + line("1. A pass", 600, 130) + line("2. An exclamation", 600, 160)
            + line("3. An association", 600, 190))
check("a clue number's lost old-style 0 put back",
      ["56", "57", "58", "60", "62"], [l[4].split(".")[0] for l in g.page_columns(no3(0))[0]])
check("a one-figure number after a restart gap not made 60 (mirror)",
      [], [l[4] for c in g.page_columns(no3(60)) for l in c if l[4].startswith("60.")])
check("a one-figure number far past or below its run's last kept (mirror)",
      False, g.lost_zero(58, 5) or g.lost_zero(51, 6) or g.lost_zero(9, 6) or g.lost_zero(13, 2))

# No 3's "Indian servant looks forward to." under the full 45A line, its
# box stretched left over a speck to where the numbers stand, runs on 45A;
# a line there opening on a misread number ("4S.") runs on nothing.
def no3_45(second):
    return (line("ACROSS", 200, 100) + line("43. The name of a town in Sind.", 100, 130)
            + line("45. Insert an A and this is what every", 100, 160) + line(second, 104, 190)
            + line("46. Part of 7 down.", 100, 220) + line("50. A place in the hills.", 100, 250)
            + line("1. A pass", 600, 130) + line("2. An exclamation", 600, 160)
            + line("3. An association", 600, 190))
check("a line stretched over a speck to the numbers runs on the full line above",
      ["43.", "45.", "Indian", "46.", "50."],
      [l[4].split()[0] for l in g.page_columns(no3_45("Indian servant looks forward to."))[0]])
check("a line there opening on a misread number does not (mirror)",
      ["43.", "45.", "46.", "50."],
      [l[4].split()[0] for l in g.page_columns(no3_45("4S. A fairly frequent thing."))[0]])

# Old-style figures read as letters open a clue all the same.
for text, want in [("I.", "1."), ("II. See 13.", "11. See 13."),
                   ("I3. Garden", "13. Garden"), ("O. Wonder", "O. Wonder"), ("Oo.", "Oo."),
                   ("I am here", "I am here"), ("12. A tree", "12. A tree"), ("1.An African bird", "1. An African bird"),
                   ("Io.Last two", "10. Last two"), ("at 8.15p.m.", "at 8.15p.m."),
                   ("20rev.,24.Charade:", "20 rev., 24. Charade:"), ("23rev.He'd", "23 rev. He'd"),
                   ("27rev.", "27 rev."), ("12. Revel", "12. Revel"), ("12 revels", "12 revels"),
                   ("4S.A fairly", "48. A fairly"), ("S. America", "S. America"), ("SS. Ship", "SS. Ship")]:
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
# No 174's page (1933): beside its lists No 172's report, whose prose opens
# on the light it is about ("30 Down, the word TANLING ..."): numbered_columns
# takes no such line for a clue, so the down list's run-on at the next
# column's top (26-35) still follows 25.
check("CITING: a sentence on a light, not a clue line",
      [True, False, False], [bool(g.CITING.match(t)) for t in
                             ("30 Down, the word TANLING", "30. Down in the mouth.", "12 Down in the dumps")])

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

# No 8's page: a letter above the puzzle in the first column, one of its
# lines opening on a date's "23," (a clue number's shape), then the
# preamble ("Solutions should be addressed"), then ACROSS low in that
# column. One numbered line is no list for the preamble to be a notice
# under: the column's clues are read. With the lists above it, the same
# paragraph still ends them (mirror).
def no8(lists_above=False):
    across = line("1. A tiny wild flower.", 100, 1030) + line("9. First three letters.", 100, 1060) \
        + line("12. A shrub used for perfumes.", 100, 1090)
    down = line("1. Takes its name from the chessboard.", 600, 1030) + line("2. This King.", 600, 1060) \
        + line("3. Half of a plant.", 600, 1090)
    letter = (line("work of equal merit in this view", 100, 600) + line("23, about scientific experiments in", 100, 630)
              + line("vinced that they are not a waste", 100, 660))
    preamble = (line("This week we are offering a copy", 100, 760)
                + line("Solutions should be addressed to The Editor", 100, 790))
    heads = [(300, 1000, 400, 1016, "ACROSS"), (800, 1000, 880, 1016, "DOWN")]
    if lists_above:
        return heads + across + down + line("Solutions should be addressed to The Editor", 100, 1140) \
            + line("of the Listener at Savoy Hill", 100, 1170)
    return letter + preamble + heads + across + down
for what, page, want in (("a letter's \"23,\" over the preamble cuts nothing", no8(), ["1", "9", "12"]),
                         ("the same paragraph under the lists ends them (mirror)", no8(True), ["1", "9", "12"])):
    cols = g.page_columns(g.figures(page))
    check(f"No 8: {what}", (want, ["1", "2", "3"]),
          tuple([l[4].split(".")[0] for l in c] for c in cols) if cols else None)
check("No 8: a notice under one prose line opening \"23,\" is no notice under a list", None,
      g.notice_top(al.fa.merge_rows([(w[1], w[3], w[0], w[2], w[4]) for w in no8() if w[0] < 500])))

# No 447's last down clue read on into the rules under the lists: the
# clue ends at its stop, the rules' "(5)" and "(7)" are no clues; a list
# run on past the rules keeps its clues there.
rules = [(0, 20, 0, 900, "(33) Rose of Sharon."),
         (30, 50, 0, 900, "(36) The did not answer; his stool'. addressed to the Editor of The Listener,"),
         (60, 80, 0, 900, "(5) Subject to the above rules, the sender of each correct solution"),
         (90, 110, 0, 900, "(7) In all matters the Editor's decision is final.")]
check("a clue read on into the rules ends at its stop, the rules go", ["(33) Rose of Sharon.", "(36) The did not answer; his stool'."],
      [l[4] for l in g.rules_cut(rules)])
check("a list run on past the rules keeps its clues (mirror)", ["(33) Rose of Sharon.", "(36) The did not answer; his stool'.", "(38) A tree."],
      [l[4] for l in g.rules_cut(rules + [(120, 140, 0, 900, "(38) A tree.")])])
check("a list with no rules is left alone (mirror)", rules[:1], g.rules_cut(rules[:1]))

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

# No 197's ACROSS heading is "CLUES—ACROSS", read as two words ("CLUF",
# "ACROSS"): the CLUES word is the heading's own. Prose beside a heading
# still makes it no heading (mirror).
def no197(beside):
    return ([beside, (1550, 657, 1650, 675, "ACROSS")] + line("1. The mistletoe hung.", 1100, 680)
            + line("3. A blind beggar.", 1100, 720) + line("5. Beverage.", 1100, 760)
            + [(1510, 800, 1590, 817, "DOWN")] + line("1. Their tops are off.", 1100, 830)
            + line("2. The old wish.", 1100, 870) + line("3. The grave voice.", 1100, 910))
for what, beside, want in (("a CLUES word left of ACROSS heads it too", (1436, 656, 1499, 673, "CLUF"),
                            ["ACROSS", "DOWN"]),
                           ("prose left of ACROSS still unheads it (mirror)", (1436, 656, 1499, 673, "for"), None)):
    heads = g.list_heads(g.figures(no197(beside)))
    check(f"No 197: {what}", want, heads and [h[4] for h in heads])
check("No 197: a CLUES word opening a line is the heading's", "ACROSS", g.heading("CLUES—ACROSS"))

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

# A clue quoting Greek (No 10's 13 across, "φλογὸς μέγαν—Aeschylus.") the
# English readers garble ("Hoyos yov") takes its Greek words from the Greek
# model, its English ones from the Tesseract readings, the number dropped.
LINE = [(100, 100, 700, 140)]
greek_line = [(110, 105, 140, 135, "13."), (150, 105, 250, 135, "φλογὸς"), (260, 105, 500, 135, "μέγαν---ΑΘΞοΗν")]
tess_line = [(110, 105, 140, 135, "13."), (150, 105, 250, 135, "Hoyos"), (260, 105, 500, 135, "yov—Aeschylus.")]
g.greek_box, real_greek_box = (lambda img, key, box: greek_line), g.greek_box
g.read_box, real_read_box = (lambda img, key, box, which: tess_line), g.read_box
greek_words = {"page": tess_line, "times": [w[:4] + (w[4].replace(".", ","),) for w in tess_line],
               "ch": [(110, 105, 560, 135, "13. pAoyos μeyavAeschylus.")],
               "en5": [(110, 105, 560, 135, "13. Φλoyos μéyav—Aeschylus.")]}
check("a clue's Greek words the English readers garble are the Greek model's",
      "φλογὸς μέγαν—Aeschylus.", g.greek_text(None, "k", greek_words, LINE))
# Mirror: a line no RapidOCR reading prints Greek letters on is English,
# though the Greek model reads its lowercase words as Greek ("απὰ" for "and").
greek_line = [(110, 105, 140, 135, "7."), (150, 105, 250, 135, "Ἀδὰ"), (260, 105, 330, 135, "απὰ"), (340, 105, 400, 135, "νοι")]
tess_line = [(110, 105, 140, 135, "7."), (150, 105, 250, 135, "Adb"), (260, 105, 330, 135, "and"), (340, 105, 400, 135, "yon")]
english = {"page": tess_line, "times": tess_line, "ch": [(110, 105, 400, 135, "7. Adb and yon")],
           "en5": [(110, 105, 400, 135, "7. Add and you")]}
check("and a line no reader sees Greek on is never read for it", None, g.greek_text(None, "k", english, LINE))
# A Greek word two English readers agree on as a word ("pos" for "μος")
# is still Greek where a RapidOCR reading prints a Greek letter in it.
greek_line = [(110, 105, 140, 135, "7."), (150, 105, 250, 135, "Add"), (260, 105, 330, 135, "--μος"), (340, 105, 400, 135, "απὰ")]
tess_line = [(110, 105, 140, 135, "7."), (150, 105, 250, 135, "Add"), (260, 105, 330, 135, "pos"), (340, 105, 400, 135, "and")]
mixed = {"page": tess_line, "times": tess_line, "ch": [(110, 105, 400, 135, "7.Add μos and")],
         "en5": [(110, 105, 400, 135, "7. Add —μos and")]}
check("a known word the English readers agree on is Greek where RapidOCR prints a Greek letter in it",
      "Add—μος and", g.greek_text(None, "k", mixed, LINE))
# No 10 20A: the page reading's number "6" stretches over the Greek words
# after it, and the dash parts the comma from "ὀξὺ".
greek_line = [(110, 105, 140, 135, "20."), (150, 105, 250, 135, "αἰετὸς"), (260, 105, 330, 135, "ὀξὺ---,"),
              (340, 105, 420, 135, "Ηοτηρτ,")]
tess_line = [(110, 105, 140, 135, "20."), (150, 105, 250, 135, "aeos"), (260, 105, 330, 135, "ou,"),
             (340, 105, 420, 135, "Homer,")]
homer = {"page": [(110, 100, 330, 140, "6")], "times": [],
         "ch": [(110, 105, 420, 135, "20. aietosof-,Homer.")], "en5": [(110, 105, 420, 135, "20. aletòs ou-, Homer.")]}
check("a number stretched over the Greek after it numbers none of it; a parted comma is kept (No 10 20A)",
      "αἰετὸς ὀξὺ—, Homer,", g.greek_text(None, "k", homer, LINE))
check("a number leading the line is still dropped (mirror)", "αἰετὸς",
      g.greek_text(None, "k", {**homer, "page": [(110, 100, 140, 140, "20")]}, LINE).split()[0])
real_lines, real_text = g.clue_lines, g.greek_text
g.clue_lines = lambda img, words, lid: [(0, 0, 10, 10)] if lid == "20-across" else []
g.greek_text = lambda img, key, words, boxes: "αἰετὸς ὀξὺ—, Homer."
v = {"blank": {"20-across": "x"}}
laid = g.greek_mended(None, "k", {}, v, {"20-across": ("", None, None), "1-across": ("Cats.", None, None)})
check("a mended clue's Greek words are as printed, so suspect() passes them (No 10 20A)",
      (["αἰετὸς", "ὀξὺ—,"], []), (v["asPrinted"]["20-across"], g.ocr_clues.suspect(laid["20-across"][0], printed=v["asPrinted"]["20-across"])))
check("a clue the vote read is no mend's (mirror)", None, v["asPrinted"].get("1-across"))
g.clue_lines, g.greek_text = real_lines, real_text
check("a reader's Latin lookalikes of a Greek word show it", (True, True, False),
      (g.lookalike("αἰετὸς", "aletòs"), g.lookalike("χλωρὸν", "xAwpov"), g.lookalike("χλωρὸν", "Homer")))
check("a box tightened by an eighth top and bottom", (0, 106, 50, 142), g.tighter((0, 100, 50, 148)))
g.greek_box, g.read_box = real_greek_box, real_read_box

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
# No 4's DOWN "1. Our subject.": ch reads ".Our subject.", and alone
# "Our subject.": a thin number lost again; the anchor's number stands.
def read_box(img, key, box, which):
    reads.append(box)
    return [(1095, 848, 1112, 864, "A"), (1122, 848, 1181, 872, "park.")]
g.read_box = read_box
check("a line read again alone that loses its number again takes the anchor's (No 4 1D)",
      ["6. Lenten.", "8.", "A", "park."],
      sorted(w[4] for w in g.reread_lines(PAGE, "k", "ch", mine[:1] + [(1064, 848, 1181, 868, ".A park.")], [en5])))
def read_box(img, key, box, which):
    reads.append(box)
    return [(1066, 848, 1112, 864, "SA"), (1122, 848, 1181, 872, "park.")]
g.read_box = read_box
check("words read alone over the anchor's number are no clue line (mirror)", ["6. Lenten.", "park"],
      sorted(w[4] for w in g.reread_lines(PAGE, "k", "ch", mine, [en5])))
# No 4's "38. 'or as a moat defensive to a house'.": the anchor's row ends
# at "a", and ch holds the line whole past it: the crop reads it whole.
reads.clear()
def read_box(img, key, box, which):
    reads.append(box)
    return [(1064, 848, 1081, 865, "8."), (1095, 848, 1400, 868, "A park by the house.")]
g.read_box = read_box
whole = mine[:1] + [(1060, 848, 1081, 865, "B."), (1095, 849, 1400, 868, "A park by the house.")]
g.reread_lines(PAGE, "k", "ch", whole, [en5])
check("a crop reaches the end of a word of the reading it would cut (No 4 38A)", 1400 + 17, reads[-1][2])
reads.clear()
g.reread_lines(PAGE, "k", "ch", mine[:1] + [(1060, 848, 1081, 865, "B."), (1095, 900, 1400, 920, "A park.")], [en5])
check("a word on another line leaves the crop (mirror)", 1181 + 17, reads[-1][2])
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

# No 8's 32 across: a worn "a" that Tesseract reads "2" (and its number "32."
# as "2.") and another reading drops is seen twice, not voted blank.
worn = {"32-across": ("Half of part of a palm used for a special purpose.", None, None)}
check("a word another reading reads as a figure in its place stands", "Half of part of a palm used for a special purpose.",
      al.ocr_clues.reconcile(worn, ["31. Flowers' sickness. 32. Half of part of  palm used for a special purpose. 33. The tulip tree.",
                                    "31. Flowers' sickness. 2. Half of part of 2 palm used for a special purpose, 3. The tulip tree,"],
                             uncounted=True)[0]["32-across"][0])
check("and with no figure there, a word one reading alone has is blank (mirror)", "no other reading has 'a'",
      al.ocr_clues.reconcile(worn, ["31. Flowers' sickness. 32. Half of part of  palm used for a special purpose. 33. The tulip tree.",
                                    "31. Flowers' sickness. 2. Half of part of palm used for a special purpose, 3. The tulip tree,"],
                             uncounted=True)[1].get("32-across"))

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

# A page read on the desktop (read_remote; ocr_remote.call as the desktop
# answers it, JSON both ways) gives the ledger row and the reading a read
# here gives; the OCR it cached and the page's grids are kept here, and the
# next read there is sent that OCR (the page's Tesseract read is made here).
# The reader is stubbed: it caches a file.
import ocr_remote
import file_gale_listener as fgl
tmp = Path(sys.argv[1])
g.OCR_CACHE, fgl.GRIDS = tmp / "ocr", tmp / "grids"
had = []
def cached_read(m):
    path = g.OCR_CACHE / f"{m['pages'][0][1]}.0-0-300-200.x.json"
    had.append(path.exists())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[[1, 2, 3, 4, \"aubade\"]]")
    return {"clues": 1, "agreed": 1, "asPrinted": {"1-across": ["aubade"]}}, {"1-across": ("Spanish for aubade", "(6)", None)}
g.read_file = cached_read
calls = []
def over_json(name, *args, data=b"", **kwargs):
    calls.append(name)
    mac, ocr_remote.call = ocr_remote.call, lambda *a, **k: None  # the desktop names no desktop of its own
    try:
        result, back = ocr_remote.run_call(name, data, json.loads(json.dumps(args)), kwargs)
    finally:
        ocr_remote.call = mac
    return json.loads(json.dumps(result)), back
saved = inbox / "1930-04-02.png"
Image.new("RGB", (300, 200), "white").save(saved)
h = g.file_hash(saved)
ocr_remote.session = lambda: "a session"
def read(call, store):
    ocr_remote.call = call
    e = g.read_one(saved, h, rows, {r["number"]: r for r in rows}, store, out=out, reader=g.read_file)
    return {k: v for k, v in e.items() if k != "readOn"}, (store / "listener-1.json").read_text()
here = read(lambda *a, **k: None, tmp / "here")
here_ocr = {f.name: f.read_text() for f in g.OCR_CACHE.iterdir()}
here_grids = fgl.page_grids(saved, h, cache=tmp / "grids-here")
for f in g.OCR_CACHE.iterdir():
    f.unlink()
there = read(over_json, tmp / "there")
check("a page read there gives the ledger row and reading a read here does", (["listener_read"], here), (calls, there))
check("the OCR it cached there is cached here", here_ocr, {f.name: f.read_text() for f in g.OCR_CACHE.iterdir()})
check("and the page's grids are filing's, read here from the cache", here_grids, fgl.page_grids(saved, h))
read(over_json, tmp / "there2")
check("a read there again is sent the OCR cached here", [False, False, True], had)

# A page's grids found there (page_grids over "listener_grids") are cached
# byte for byte as found here, and given back as here. The search is stubbed:
# a grid with numpy floats and tuple-keyed sides, fitted to tuples.
import numpy as np
lg = fgl.lg
real = lg.find_grids, lg.printed_numbers, lg.fit
lg.find_grids = lambda gray: [{"box": (1, 2, 30, 40), "rows": ["..", ".#"], "why": None, "filled": 0.1,
                               "sides": {(0, 0, "r"): 1.5}, "thin": 2.0,
                               "lattice": [np.array([1.25, 2.5]), np.array([3.0, 4.75])]},
                              {"box": (0, 0, 9, 9), "rows": None, "why": "too small", "filled": 0.0}]
lg.printed_numbers = lambda gray, g: {(0, 0): 1}
lg.fit = lambda g, printed: {"rows": ["..", ".#"], "at": (0, 1)}
calls.clear()
ocr_remote.call = lambda *a, **k: None
here = fgl.page_grids(saved, "a-sha", cache=tmp / "grids-h")
ocr_remote.call = over_json
there = fgl.page_grids(saved, "a-sha", cache=tmp / "grids-t")
check("a page's grids found there are cached as found here, and given back the same",
      (["listener_grids"], (tmp / "grids-h" / "a-sha.json").read_bytes(), here),
      (calls, (tmp / "grids-t" / "a-sha.json").read_bytes(), there))
check("and as the cache gives them back", here, fgl.page_grids(saved, "a-sha", cache=tmp / "grids-h"))
lg.find_grids, lg.printed_numbers, lg.fit = real
ocr_remote.call = lambda *a, **k: None

root = Path(sys.argv[1]) / "repo"
(root / "puzzles" / "listener" / "1930").mkdir(parents=True)
(root / "puzzles" / "listener" / "1930" / "listener-2.json").write_text("{}")
check("nothing wanted once read or filed, its solution saved", [], g.wanted(rows, store, root))
nostore, noroot = Path(sys.argv[1]) / "nostore", Path(sys.argv[1]) / "none"
check("every printed puzzle wanted, earliest first, its page then its report",
      [(D(1930, 4, 2), 1, False), (D(1930, 4, 2), 1, True), (D(1930, 4, 9), 2, False), (D(1930, 4, 9), 2, True)],
      g.wanted(rows, nostore, noroot))
inbox2, store2 = Path(sys.argv[1]) / "inbox2", Path(sys.argv[1]) / "store2"
inbox2.mkdir()
Image.new("RGB", (300, 203), "white").save(inbox2 / "1930-04-09.png")
g.run(inbox2, store2, rows, out=out, reader=reader)
check("a read puzzle's page is not wanted, its missing report is",
      [(D(1930, 4, 2), 1, False), (D(1930, 4, 2), 1, True), (D(1930, 4, 9), 2, True)], g.wanted(rows, store2, noroot))
inbox3, store3 = Path(sys.argv[1]) / "inbox3", Path(sys.argv[1]) / "store3"
inbox3.mkdir()
Image.new("RGB", (300, 204), "white").save(inbox3 / "1930-04-09.png")
g.run(inbox3, store3, rows, out=out, reader=lambda m: ({"refused": "no clue list on the page"}, None))
check("a page read with no reading kept is still wanted (gale_fetch passes over its document)", True,
      (D(1930, 4, 9), 2, False) in g.wanted(rows, store3, noroot))
# A page tools/gale_fetch.py downloaded is saved whole, named for its date
# (match() gives it that issue's puzzle); a report by its document alone.
saved_dir = Path(sys.argv[1]) / "fetched"
got = g.lay_out_fetched(D(1930, 4, 9), "GM2500000001", b"%PDF-1.4 page", saved=saved_dir)
rpt = g.lay_out_fetched(D(1930, 4, 23), "GM2500000002", b"%PDF-1.4 report", report=True, saved=saved_dir)
check("saved whole, under names the reader lists",
      (["1930-04-09 GALE_GM2500000001.pdf", "GALE_GM2500000002.pdf"], b"%PDF-1.4 page"),
      ([q.name for q in g.page_files(saved_dir)], got.read_bytes()))
check("the page's name gives its issue's puzzle; the report's names none", (2, None, None),
      (g.by_date(rows, g.gi.name_date(got.name, g.DATES))["number"], g.gi.name_date(rpt.name, g.DATES),
       g.name_number(rpt.name)))
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
check("a clue holding another light's whole clue is a run-on, not filed (No 17 58D)", "",
      al.pick(two, ["58. The top of the head. Italian police.", "56. The top of the head.\nItalian police."]).get("58-down", ("",))[0])
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
    (inbox / "c.pdf").write_bytes(b"c")
    rows.append({"sha": g.file_hash(inbox / "c.pdf"), "version": g.PARAGRAPHS - 1, "why": g.UNPARSED})
    (store / g.LEDGER).write_text("".join(json.dumps(r) + "\n" for r in rows))
    due = {u["rel"]: (u["reason"], u["rank"]) for u in g.plan(inbox, store)}
    check("a page no reading parsed before the paragraph lists is due for their fix, ranked by fa.RANKS",
          ("refused no-reading-parses before its fix", g.fa.RANKS["refused no-reading-parses before its fix"]),
          due.get("c.pdf"))
    check("a page that parsed is a blanket re-read (mirror)", ("version changed", g.fa.BLANKET), due.get("a.pdf"))
    check("and the evidence reason is one the queue plans with blanket rereads off", True,
          __import__("edition_queue").evidence_reason(due["c.pdf"][0]))
    check("a page read short before the table lists' fix is due for it, an evidence reason ranked by fa.RANKS",
          (g.SHORT, g.fa.RANKS[g.SHORT], True),
          (g.due_reason({"version": g.CLUES_FIX - 1, "agreed": 34, "clues": 41}), g.rank_of(g.SHORT),
           __import__("edition_queue").evidence_reason(g.SHORT)))
    check("one read whole, or short since, is not (mirror)", ["version changed", "version changed"],
          [g.due_reason({"version": g.CLUES_FIX - 1, "agreed": 41, "clues": 41}),
           g.due_reason({"version": g.CLUES_FIX, "agreed": 34, "clues": 41})])
    check("of the pages read short, the nearest whole is read first; other reasons follow in file order",
          [1, 9, float("inf"), float("inf")],
          [g.clues_left({"agreed": 41, "clues": 42}, g.SHORT), g.clues_left({"agreed": 35, "clues": 44}, g.SHORT),
           g.clues_left({"why": g.UNPARSED}, "refused no-reading-parses before its fix"),
           g.clues_left(None, "never read (Gale fetch)")])

# CITE_FIX: the paragraph lists' "(33)Down." regex once shadowed CITED, so
# cited_day read no date and a page was numbered by its title read
# ("Report on Crossword No. 15" under No 17's script title; "No. 65[1]").
check("a report page's citation dates the issue's own puzzle (No 651, not its title read 65)",
      D(1942, 9, 3), g.cited_day('"Report on No. 649. " The Listener, 3 Sept. 1942, p. 29. The Listener Historical Archive'))
check("the clue regex is no longer the citation's", (None, True),
      (g.SEE_DIRECTION.search("The Listener, 3 Sept. 1942, p. 29."), bool(g.SEE_DIRECTION.match(" Down."))))
check("a page numbered by its title read, or by nothing, while the date went unread is read again, rank 0",
      [(g.MISNUMBERED, 0, True), (g.MISNUMBERED, 0, True)],
      [(r := g.due_reason(row), g.rank_of(r), __import__("edition_queue").evidence_reason(r)) for row in (
          {"version": g.CITE_FIX - 1, "how": "title read", "number": 65, "agreed": 42, "clues": 53},
          {"version": g.PARAGRAPHS, "how": None, "number": None, "why": "no date or number in the name, citation or title"})])
check("one the citation numbered, or read before the shadowing, is not (mirror)", ["version changed"] * 2,
      [g.due_reason({"version": g.CITE_FIX - 1, "how": "PDF citation title", "number": 3, "agreed": 9, "clues": 9}),
       g.due_reason({"version": g.PARAGRAPHS - 1, "how": None, "number": None})])
with tempfile.TemporaryDirectory() as tmp:
    store = Path(tmp)
    def wrote(n, f):
        (store / f"listener-{n}.json").write_text(json.dumps({"number": n, "source": {"file": f}}))
    wrote(65, "GALE_GM2500030496.pdf")
    wrote(15, "GM2500066057 (1).pdf")
    page = Path(tmp) / "GALE_GM2500030496.pdf"
    check("a reading a page wrote under the number it no longer matches is dropped",
          ("listener-65.json", False), (g.disown(page, {"number": 65}, 651, store), (store / "listener-65.json").exists()))
    wrote(65, "GALE_GM2500030496.pdf")
    check("not when it matches that number still, nor one another page wrote (mirror)", [None, None, True, True],
          [g.disown(page, {"number": 65}, 65, store), g.disown(Path(tmp) / "GM2500066057.pdf", {"number": 15}, 17, store),
           (store / "listener-65.json").exists(), (store / "listener-15.json").exists()])
    check("nor the number a hand repair dropped from its row, when this page wrote that reading", "listener-15.json",
          g.disown(Path(tmp) / "GM2500066057 (1).pdf", {"number": 17, "numberDropped": {"was": 15}}, 17, store))

# The 1934-40 lists, run on as paragraphs (No 400): "(N)" opens each clue
# mid-line, the across list runs on from the left column's foot to the
# next's top, DOWN's heading is centred in that column, a report beside
# them and the rules under them are no clue's.
def para_words(lines):
    out = []
    for y, x, text in lines:
        for word in text.split():
            out.append((x, y, x + 12 * len(word), y + 17, word))
            x += 12 * len(word) + 10
    return out
para = para_words([(1744, 300, "CLUESACROSS"),
                   (1772, 88, "(1) Bird. (5) Fish in a"), (1794, 88, "pond. (7) Tree."),
                   (1816, 88, "(9) Stone (cut). (11)"), (1838, 88, "Ten of them, a decade."),
                   (1751, 765, "Long river. (12) Plant."), (1773, 765, "(14) Hill and dale."),
                   (1795, 900, "DOWN"),
                   (1817, 765, "(1) Cart. (2) Song (5)."), (1839, 765, "(3) Mule. (4) Lamb."),
                   (1861, 765, "CROSSWORD RULES. (1) Entries"),
                   (1751, 1450, "Report on the Competition"), (1773, 1450, "(1) was hard. (2) The"),
                   (1795, 1450, "entries were many."),
                   (1700, 88, "Prize: a book. (Closing date: First post Tuesday.)")])
cols = g.paragraph_columns(para)
check("paragraph lists: a clue a number, run on across the gutter; counts and the report's numbers no clue's",
      (["1. Bird.", "5. Fish in a pond.", "7. Tree.", "9. Stone (cut).", "11. Ten of them, a decade. Long river.",
        "12. Plant.", "14. Hill and dale."], ["1. Cart.", "2. Song (5).", "3. Mule.", "4. Lamb."]),
      cols and ([l[4] for l in cols[0]], [l[4] for l in cols[1]]))
check("page_columns takes them", cols, g.page_columns(para))
# No 582's (1941): a clue a line, its "(N)" set in a gutter of its own left
# of the clue texts and the ACROSS heading; a line's count runs into the
# next clue's number ("Scotland (7) (5) Puts"), a count misread "(1)"
# mid-list, and DOWN's heading under a gap wider than the lines' pitch.
gutter = [(2524, 1107, "CLUESACROSS")]
for i, (n, text) in enumerate([(1, "Qualified for a degree in Scotland (7)"), (5, "Puts about and goes in (7)."),
                               (9, "Where the drama is portrayed? (15)."), (10, "Everyone in colour (7)."),
                               (11, "Religion gives a sergeant-major"), (None, "bad back (7)."),
                               (12, "Where real tweed is seen (9)."), (13, "Found in a famous beer"),
                               ("(1)", None), (16, "Crinoline for peace time services (9).")]):
    y = 2575 + 38 * i
    if n is not None:
        gutter.append((y, 815, n if isinstance(n, str) else f"({n})"))
    if text:
        gutter.append((y, 899, text))
gutter.append((2575 + 38 * 9 + 120, 1150, "DOWN"))
for i, (n, text) in enumerate([(1, "Horsey half of an astronomer (5)."), (2, "Choose your weapon, woodman (7)."),
                               (3, "Boy discovered at the day's end (5).")]):
    gutter += [(2575 + 38 * 9 + 170 + 38 * i, 815, f"({n})"), (2575 + 38 * 9 + 170 + 38 * i, 899, text)]
cols = g.paragraph_columns(para_words(gutter))
check("No 582's lists: numbers in their own gutter; a count before the next number, a stray (1), DOWN under a gap",
      [[1, 5, 9, 10, 11, 12, 13, 16], [1, 2, 3]],
      cols and [[int(l[4].split(".")[0].split(",")[0]) for l in c] for c in cols])
# No 443's (1938): lights clued together share a bracket, numbered by the
# first ("(1, 8, 52)", "(40-22)"), an anagram says so in it ("(47 anag.)"),
# and DOWN's heading, unread, leaves a gap over the down list's "(1)".
no443 = [(1744, 300, "CLUESACROSS"),
         (1772, 88, "(1, 8, 52) The nightingale. (5, 9D) Its"), (1794, 88, "post-mortem. (9) A democrat."),
         (1816, 88, "(14) Perfect. (40-22) Thracian torturers."), (1838, 88, "(47 anag.) Shivering made him so."),
         (1898, 88, "(1) No post-mortem. (2U anag.) Oath-"), (1920, 88, "offerings. (3) Pan is the"),
         (1942, 88, "Great Mother's."), (2010, 88, "CROSSWORD RULES. (1) Entries")]
cols = g.paragraph_columns(para_words(no443))
check("No 443's lists: a bracket of lights numbered by its first, an anagram's, an unread DOWN's gap",
      [[1, 5, 9, 14, 40, 47], [1, 2, 3]], cols and [[int(l[4].split(".")[0].split(",")[0]) for l in c] for c in cols])
check("a gap over a line that is no restart still ends the lists (mirror)", None,
      g.paragraph_columns(para_words([r if r[2] != "(1) No post-mortem. (2U anag.) Oath-"
                                      else (r[0], r[1], "A note. (2U anag.) Oath-") for r in no443])))
linked = [(1744, 300, "CLUESACROSS"), (1772, 88, "(1) Doom. (8) Fisher come. (10) The"),
          (1794, 88, "name. (1, 40) Leads proof. (42)"), (1816, 88, "Last one."),
          (1876, 88, "(1) Professor here. (2) His coat"), (1898, 88, "lost. (3) Boat here.")]
cols = g.paragraph_columns(para_words(linked))
check("a bracket set at its later light's place is numbered by it, no restart of the list",
      [[1, 8, 10, 40, 42], [1, 2, 3]], cols and [[int(l[4].split(".")[0].split(",")[0]) for l in c] for c in cols])
# No 242's (1934): "CLUES—ACROSS" at the left column's foot, the list run
# on at the next column's top far above it (an advert over that), a
# report under the heading's level there; a clue's "See 37 Across." is no
# heading, and "(45 rev.)" a clue's number.
no242 = [(300, 765, "Royal Soldiers Home advert"), (1744, 300, "CLUESACROSS"),
         (1772, 88, "(2) Victim of Scorpio. (10) A monster"), (1794, 88, "of note. (13) See 6."),
         (1000, 765, "Epical hero met him. (19) A laddie."), (1022, 765, "(21) One thought. (24) See 35."),
         (1044, 765, "(45 rev.) Better be chastised."), (1088, 900, "DOWN"),
         (1110, 765, "(1) Ay, in the word. (3) See 12."), (1132, 765, "(4) Another animal. (11) See"),
         (1154, 765, "37 Across."),
         (1800, 765, "Prizewinners: C. A. Adams (London, N.8);"), (1822, 765, "were very successful.")]
cols = g.paragraph_columns(para_words(no242))
check("No 242's lists: run on above the heading in the next column, a report below it",
      [[2, 10, 13, 19, 21, 24, 45], [1, 3, 4, 11]], cols and [[int(l[4].split(".")[0].split(",")[0]) for l in c] for c in cols])
cols = g.paragraph_columns(para_words(no242[:-3] + [(1154, 765, "37 Across. (12 in 3) Really a kind"),
                                                    (1176, 765, "of sand-stars. (14) If you are in.")] + no242[-2:]))
check("No 242's (12 in 3) numbers its clue, set inside 3 unreversed",
      ["11. See 37 Across.", "12. Really a kind of sand-stars."], cols and [l[4] for l in cols[1][3:5]])
# No 273's (1935): a plural's bracket, an anagram's, lettered links, and a
# later light's figure read as a letter.
no273 = [(1744, 300, "CLUESACROSS"),
         (1772, 88, "(1) Whitsun 13. (8-s) Proverbs at these. (9-IoD)"), (1794, 88, "'Heaven will make a feast'."),
         (1816, 88, "(24, 27) See 36, 25D. (Anag. 28B) With 39A, Ceremony."), (1838, 88, "(30) With second letter."),
         (1882, 300, "DOWN"),
         (1904, 88, "(1) Whitsun symbol. (2-4oA) Some affirm. (3-s)"), (1926, 88, "Whit Sunday. (25-31, 27A-39)"),
         (1948, 88, "Frolicked it. (29-35U) See 19. (33U) Its anagram.")]
cols = g.paragraph_columns(para_words(no273))
check("No 273's lists: (8-s), (9-IoD), (Anag. 28B), (2-4oA) and (3-s) number their clues",
      [["1. Whitsun 13.", "8. Proverbs at these.", "9, 10. 'Heaven will make a feast'.", "24, 27. See 36, 25D.",
        "28. With 39A, Ceremony.", "30. With second letter."],
       ["1. Whitsun symbol.", "2, 40. Some affirm.", "3. Whit Sunday.", "25, 31. Frolicked it.", "29, 35. See 19.",
        "33. Its anagram."]], cols and [[l[4] for l in c] for c in cols])
check("a lettered link joins a light of its list's own way, or the other list's lettered so",
      [31, 35, 40, 10, 39, 29, 28],
      [g.para_linked(g.PARA_MARK.search(t), s) for t, s in (("(25-31, 27A-39)", "DOWN"), ("(29-35U)", "DOWN"),
                                                             ("(2-40A)", "DOWN"), ("(9-10D)", "ACROSS"),
                                                             ("(38, 39)", "DOWN"), ("(12-29D)", "ACROSS"),
                                                             ("(34-28D)", "ACROSS"))])
check("but not with its first light lettered, nor up among the across clues (mirror)", [None, None],
      [g.para_linked(g.PARA_MARK.search(t), s) for t, s in (("(2A-40D)", "ACROSS"), ("(2-40U)", "ACROSS"))])
# No 447's (1938) theme line over its lists: the lights it names, as two
# readings read them ("S," a 5, "IA" 1A, "The 26s" 26; the word "I" none).
canvas = [(950, 1759, 1080, 1780, "CANVAS"), (682, 1779, 760, 1800, "The"), (765, 1779, 800, 1800, "26s"),
          (805, 1779, 850, 1800, "that"), (855, 1779, 900, 1800, "28U"), (905, 1779, 935, 1800, "7D"),
          (940, 1779, 970, 1800, "7A"), (975, 1779, 990, 1800, "S,"), (1000, 1779, 1030, 1800, "IA,"),
          (1040, 1779, 1060, 1800, "I"), (1380, 1779, 1500, 1800, "printed"),
          (875, 1817, 1145, 1838, "CLUES—ACROSS"), (700, 1850, 1100, 1871, "(8) Because it was")]
check("a theme line under its title over ACROSS names its lights",
      ("CANVAS", ["26", "28U", "7D", "7A", "5", "1A"]), g.theme_line(canvas))
check("the lights two readings read are the theme's, one alone reads none of it",
      {"title": "CANVAS", "lights": ["26", "28U", "7D", "7A", "1A"]},
      g.theme_lights({"a": canvas, "b": [w for w in canvas if w[4] != "S,"]}))
check("no title word over ACROSS, no theme line (mirror)", None, g.theme_line(canvas[1:]))
# No 133's (1932): "CLUES—ACROSS" read as specks, only DOWN read: the
# across list is read from its "1." line up the column, not dropped.
no133 = (line("Name and address", 100, 300) + line("¢t 3", 300, 400) + line("1. Claustra olim", 100, 430)
         + line("10. Occurs here", 100, 460) + line("11. Temptato feminae", 100, 490) + line("DOWN", 300, 530)
         + line("1. A freedman", 100, 560) + line("2. A river", 100, 590) + line("3. Cibi peremptum", 100, 620))
check("only DOWN read: the across list above it, from its 1.",
      (["1", "10", "11"], ["1", "2", "3"]),
      tuple([l[4].split(".")[0] for l in c] for c in g.page_columns(no133) or ([], [])))
check("with no 1. above DOWN, nothing above it is a list (mirror)", None,
      g.numbered_columns([w for w in no133 if w[4] != "1." or w[1] > 500]))
# No 261's (1935): a reader reads a bracket's figure as a letter ("(Is)",
# "(3o)", "(z1)", "(1g rev.)"), sets a capital hard on it ("(26rev.)Muddled"),
# and a clue's "See (31) Down." refers to a light, numbering no clue.
no261 = [(1744, 300, "CLUESACROSS"),
         (1772, 88, "(12) The schoolboy's face? (13)* One"), (1794, 88, "tramp. (Is)* A Harpy. (16 rev.)"),
         (1816, 88, "& (1o rev.) Medea. (1g rev.) See (3o)."), (1838, 88, "(z1)* Platitudinous remark. (26rev.)Muddled"),
         (1860, 88, "corpse-cover. (3I rev.) Woollens."),
         (1882, 300, "DOWN"),
         (1904, 88, "(1) Obvious reference. (2) Christmas."), (1926, 88, "(3)** See (31) Down. (4) & (28) Might"),
         (1948, 88, "have described a web. (s rev.)* See (32).")]
cols = g.paragraph_columns(para_words(no261))
check("No 261's lists: figures read as letters in a bracket, a capital hard on it, a See (N) no clue",
      [[12, 13, 15, 16, 19, 21, 26, 31], [1, 2, 3, 4, 5]], cols and [[int(l[4].split(".")[0].split(",")[0]) for l in c] for c in cols])
check("its 3 down is the See, its 26 across the words after the bracket",
      ["3. See (31) Down.", "26. Muddled corpse-cover."],
      cols and [next(l[4] for l in cols[1] if l[4].startswith("3.")), next(l[4] for l in cols[0] if l[4].startswith("26."))])
check("a word in brackets stays a word (mirror)", "(I) and (so) and (is)", g.figures_read("(I) and (so) and (is)"))
# No 245's (1934): the across list runs on at the next column's top, above
# the heading's level, DOWN's heading there too and the down list running
# on below that level; a grid's numbers under the left column close the gap
# to its "NAME AND ADDRESS".
no245 = [(1744, 300, "CLUESACROSS"), (1772, 88, "(1) Protects the arm. (5) Old English"),
         (1794, 88, "would drink. (10) Victim of nursery.")]
no245 += [(1830 + 40 * i, 88, " ".join(str(n) for n in range(6 * i + 1, 6 * i + 7))) for i in range(7)]
no245 += [(2110, 88, "NAME AND ADDRESS"), (1534, 765, "(35) Assumed arms. (38-45) Defect in"),
          (1556, 765, "a bow. (40) When doubled."), (1578, 900, "DOWN")]
no245 += [(1600 + 22 * i, 765, f"({2 * i + 1}) Down clue. ({2 * i + 2}) Another one.") for i in range(18)]
no245 += [(2100, 765, "Report on Crossword No. 243"), (2122, 765, "(1) was hard. (2) The")]
cols = g.page_columns(para_words(no245))
check("No 245's lists: run on above the heading's level with DOWN there, over a grid's numbers",
      [[1, 5, 10, 35, 38, 40], list(range(1, 37))], cols and [[int(l[4].split(".")[0].split(",")[0]) for l in c] for c in cols])
check("its (38-45) clues both lights", "38, 45. Defect", cols and cols[0][4][4][:14])
check("one clue a line is no paragraph list (mirror)", None,
      g.paragraph_columns(para_words([(100, 88, "ACROSS"), (130, 88, "1. Bird (4)"), (160, 88, "5. Fish (4)")])))


def para_heads(lines):
    cols = g.paragraph_columns(para_words(lines))
    return cols and [[l[4].split(".")[0] for l in c] for c in cols]


# No 254's (1935): "(11, 40)" read "(1, 40)" or "(II, 40)": no 40 across
# dropping the list's (15) to (38) as lower; "(10, 39)" clues both lights.
def no254(eleven):
    return [(1744, 300, "CLUESACROSS"), (1772, 88, f"(1) Doom. (8) Fisher come. (10, 39) The"),
            (1794, 88, f"name. {eleven} Leads proof. (15) One"), (1816, 88, "of rank. (16) A locum. (18) Bog-latin."),
            (1838, 300, "DOWN"), (1860, 88, "(1) Professor here. (2) His coat"),
            (1882, 88, "lost. (3) Boat here. (36) Assembly"), (1904, 88, "please. Report on Crossword No. 252")]


check("No 254: a number misread high drops no clue after it; a bracket of two lights clues both",
      [["1", "8", "10, 39", "15", "16", "18"], ["1", "2", "3", "36"]], para_heads(no254("(1, 40)")))
check("its \"(II, 40)\" read as 11", [["1", "8", "10, 39", "11, 40", "15", "16", "18"], ["1", "2", "3", "36"]],
      para_heads(no254("(II, 40)")))
check("the last report's heading is no part of the last clue", "36. Assembly please.",
      (g.paragraph_columns(para_words(no254("(II, 40)"))) or [[], [("", "", "", "", "")]])[1][-1][4])
past = [(y, x, t.replace("(15)", "(41)").replace("(16)", "(42)").replace("(18)", "(43)")) for y, x, t in no254("(1, 40)")]
check("a bracket at its later light's place with the list going on past it stays (mirror)",
      [["1", "8", "10, 39", "40", "41", "42", "43"], ["1", "2", "3", "36"]], para_heads(past))
# No 245's (1934): stars inside the bracket, a light reversed in another,
# a reading losing a bracket's close.
no245b = [(1744, 300, "CLUESACROSS"), (1772, 88, "(1 Protects the arm. (**10) Victim"),
          (1794, 88, "of nursery. (43 rev. in 42) Alleged destroyers."), (1816, 88, "(*44 rev.) Shooting-ground. (**46) Mark."),
          (1838, 300, "DOWN"), (1860, 88, "(1) If he would. (2) Shaft. (*8) Mounted"),
          (1882, 88, "Sagittarius. (9) Sagittarius. (12) Here.")]
check("No 245: stars in the bracket, \"(43 rev. in 42)\" and an unclosed \"(1 Protects\" number their clues",
      [["1", "10", "43", "44", "46"], ["1", "2", "8", "9", "12"]], para_heads(no245b))
check("and no star is left on the clue before", "2. Shaft.",
      (g.paragraph_columns(para_words(no245b)) or [[], [(), ("", "", "", "", "")]])[1][1][4])
check("a light's count in brackets stays the clue's words (mirror)", "(2 words) and (5)",
      g.figures_read("(2 words) and (5)"))
check("and a light cited by its direction is no unclosed number (mirror)", "Part of (43 Ac.). (32 Down) and",
      g.figures_read("Part of (43 Ac.). (32 Down) and"))
# A heading lent from another reading takes no word of the line set close under it.
heads = [(100, 1680, 320, 1705, "CLUES-ACROSS"), (100, 1897, 190, 1919, "DOWN")]
under = [(150, 1706, 260, 1722, "monarch's"), (100, 1684, 300, 1703, "CLUESACR0SS")]
lent = g.lend_heads({"a": heads, "b": under})
check("a lent heading takes its own line's misread words, not the line under it",
      ["monarch's", "CLUES-ACROSS", "DOWN"], [w[4] for w in lent["b"]])

# The media disk's Listener folder: Paul's pages loose, the fetcher's in Fetched/.
# One unit per Gale document: a second download of one read already (stamped
# apart, so hashed apart) is none, and of two unread copies the dated one is read.
with tempfile.TemporaryDirectory() as tmp:
    inbox, store = Path(tmp) / "Listener", Path(tmp) / "store"
    (inbox / g.FETCHED).mkdir(parents=True); store.mkdir()
    (inbox / "GM2500000001.pdf").write_bytes(b"paul's")
    (inbox / g.FETCHED / "GALE_GM2500000001.pdf").write_bytes(b"fetched again")
    (inbox / g.FETCHED / "GALE_GM2500000002.pdf").write_bytes(b"fetched")
    (inbox / "1930-04-09 GALE_GM2500000002.pdf").write_bytes(b"fetched")
    (inbox / g.FETCHED / "GALE_GM2500000003.pdf").write_bytes(b"new")
    (inbox / g.FETCHED / ".GALE_GM2500000004.pdf.part").write_bytes(b"half")
    (store / g.LEDGER).write_text(json.dumps({"sha": g.file_hash(inbox / "GM2500000001.pdf"), "version": g.VERSION,
                                              "file": "GM2500000001.pdf"}) + "\n")
    check("both folders listed, a part-written page not", 5, len(g.page_files(inbox)))
    check("one unit a document; read ones none; the dated copy first",
          ["1930-04-09 GALE_GM2500000002.pdf", "GALE_GM2500000003.pdf"], sorted(u["rel"] for u in g.plan(inbox, store)))
    check("a unit's page is found in Fetched/", inbox / g.FETCHED / "GALE_GM2500000003.pdf",
          g.page_path(inbox, "GALE_GM2500000003.pdf"))
    check("and a loose one where it is (mirror)", inbox / "GM2500000001.pdf", g.page_path(inbox, "GM2500000001.pdf"))

# Report lookups: a saved puzzle's and an upcoming one's; not one whose
# report a saved page holds.
with tempfile.TemporaryDirectory() as tmp:
    store, root = Path(tmp) / "store", Path(tmp) / "root"
    store.mkdir(); root.mkdir()
    idx = [{"number": n, "title": "T", "setter": None, "date": D(1930, 4, 2) + datetime.timedelta(days=7 * n)}
           for n in (1, 2, 3, 4)]
    (store / "listener-2.json").write_text(json.dumps({"number": 2, "verdict": {}}))
    (store / g.LEDGER).write_text(json.dumps({"sha": "r", "version": g.VERSION, "file": "r.pdf", "number": 3,
                                              "reports": [1]}) + "\n")
    got = [r["number"] for r in g.report_lookups(idx, store, root)]
    check("reports looked up for a saved and an upcoming row, not one whose report is saved", [2, 3, 4], got)
    check("unsolved lists the saved puzzles with no report saved", [2, 3], [r["number"] for r in g.unsolved(idx, store)])

print(f"FAILS {fails}")
sys.exit(1 if fails else 0)
