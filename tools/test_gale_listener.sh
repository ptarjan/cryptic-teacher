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
                   ("Io.Last two", "10. Last two"), ("at 8.15p.m.", "at 8.15p.m.")]:
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
check("next up lists them with the ordering rule and a Next batch", True,
      '<table id="next">' in bare and g.ORDER in bare and "nextBatch()" in bare)
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
check("not while a saved file waits to be read", False, "save its solution too:" in g.checklist(
    rows, store2, Path(sys.argv[1]) / "none", arrivals=[{"file": "new.pdf", "number": 1}]))
check("earliest first", True, page.index("Wed 02 Apr 1930") < page.index("Wed 09 Apr 1930"))

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
check("and counted", True, "<b>2 of 2</b> saved or filed" in page)
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
print(f"FAILS {fails}")
sys.exit(1 if fails else 0)
PY
