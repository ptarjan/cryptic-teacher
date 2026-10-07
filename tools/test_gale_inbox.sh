#!/bin/bash
# Does a page saved into the Gale inbox become a Times edition the scan filer
# reads (tools/gale_inbox.py): matched to its date by the date or puzzle
# number in its name, numbered from the filed puzzles either side, laid out
# as GaleTimes<year>UKEnglish/<date> with a Gale document's link, due again
# when a file is added or replaced for that date and no other, and gone when
# the inbox no longer holds it? Is a Gale download recognised by its name or
# citation and routed to its paper's inbox, everything else left alone, and
# does the checklist lead with progress, pages to redo and what to search?
#
#     bash tools/test_gale_inbox.sh
#
# Synthetic pages and PDFs in a temp dir: no OCR, nothing asked of the Mac,
# the desktop or Gale, nothing written outside it.
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 - "$tmp" <<'PY'
import datetime, io, json, re, sys
from pathlib import Path
from PIL import Image
import file_archive_org_puzzles as fa
import gale_inbox as g

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

D = datetime.date
for name, want in [("1988-01-12.pdf", D(1988, 1, 12)), ("Times 19880112 p18.jpg", D(1988, 1, 12)),
                   ("The Times 12 Jan. 1988.pdf", D(1988, 1, 12)), ("Jan 12, 1988 crossword.png", D(1988, 1, 12)),
                   ("12th January 1988.jpg", D(1988, 1, 12)), ("GALE|IF0503151598.pdf", None),
                   ("Times issue 62975.pdf", None)]:
    check(f"the date in {name!r}", want, g.name_date(name))
for name, want in [("No 17,563.pdf", 17563), ("crossword-17563.jpg", 17563), ("GALE|IF0503151598.pdf", None),
                   ("Times issue 62975.pdf", None), ("GALE_IF0517563001.pdf", None)]:
    check(f"the puzzle number in {name!r}", want, g.name_number(name))

# Numbers from the filed puzzles either side, counted in printed issues:
# no Sunday, no Christmas Day.
held = {17396: D(1987, 6, 30), 17632: D(1988, 4, 1)}
check("a number off a bracket across Christmas is sure", (17563, True), g.number_on(D(1988, 1, 12), held))
check("the date of a number off the same bracket", D(1988, 1, 12), g.day_of(17563, held))
check("a Sunday is no issue", None, g.ISSUE.get(D(1988, 1, 10)))
broken = {17396: D(1987, 6, 30), 17640: D(1988, 4, 1)}
check("a broken bracket gives no date for a number", None, g.day_of(17563, broken))
check("a broken bracket's number is an estimate", False, g.number_on(D(1988, 1, 12), broken)[1])

# Staging: pages of one date are one edition, re-laid only when what the
# inbox holds for it moves.
inbox, cache, un = Path(sys.argv[1]) / "inbox", Path(sys.argv[1]) / "cache", Path(sys.argv[1]) / "unmatched.json"
inbox.mkdir()
cache.mkdir()
g.held = lambda: held
Image.new("RGB", (400, 300), "white").save(inbox / "GALE|IF0503151598 1988-01-12.jpg")
Image.new("RGB", (400, 300), "white").save(inbox / "holiday snap.jpg")
(inbox / "notes.txt").write_text("not a page")
out = io.StringIO()
g.MATCHES = Path(sys.argv[1]) / "matches.json"
g.stage(inbox, cache, out, un, g.MATCHES)
d = cache / "GaleTimes1988UKEnglish" / "1988-01-12"
pages = json.loads((d / "pages.json").read_text())
check("a dated page is staged as that date's Times edition", (True, "1988-01-12", 1),
      ((d / "leaf_0000.jpg").exists(), pages["date"], pages["leaves"]))
check("its source link is the Gale document's", g.DOC_URL.format("IF0503151598"), fa.page_url(d, {}, 0))
check("a page set on an archive.org-wide page", fa.SCAN_WIDTH, Image.open(d / "leaf_0000.jpg").width)
check("a file that names no edition is listed, not staged", ["holiday snap.jpg"],
      [m["file"] for m in json.loads(un.read_text()) if not m.get("date")])
check("a staged page with no grid on it is listed for redoing", ["GALE|IF0503151598 1988-01-12.jpg"],
      [m["file"] for m in json.loads(un.read_text()) if m.get("date")])
check("each file's match is kept, so a tick re-reads only what moved", 2,
      len(json.loads(g.MATCHES.read_text())))
check("under the matcher's version, so a fix re-reads every file", True,
      all(k.startswith(g.MATCHER + "\t") for k in json.loads(g.MATCHES.read_text())))
check("the Times filer finds the staged edition", [d], [e for e in fa.edition_dirs(cache, fa.TIMES)])
check("as a Times edition", fa.TIMES, fa.paper_of(d))
check("and no other paper's", [], fa.edition_dirs(cache, fa.FT))
first = fa.input_hash(d)
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES)
check("an inbox unchanged leaves the edition's inputs alone", first, fa.input_hash(d))
check("and its inputs are its files' (inputs_of)", first, fa.inputs_of(first, {"puzzles": []}, "times"))
Image.new("RGB", (400, 300), "white").save(inbox / "1988-01-12 page 2.png")
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES)
second = fa.input_hash(d)
check("a second page for the date makes that edition due", (True, 2),
      (second != first, json.loads((d / "pages.json").read_text())["leaves"]))
Image.new("RGB", (401, 300), "black").save(inbox / "1988-01-12 page 2.png")
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES)
check("a page replaced makes it due again", True, fa.input_hash(d) not in (first, second))
other = cache / "GaleTimes1988UKEnglish" / "1988-01-13"
Image.new("RGB", (400, 300), "white").save(inbox / "1988-01-13.jpg")
before = fa.input_hash(d)
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES)
check("a page for another date is its own edition, the first left alone", (True, before),
      (other.exists(), fa.input_hash(d)))
(inbox / "1988-01-13.jpg").unlink()
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES)
check("a page gone from the inbox takes its edition with it", False, other.exists())

# The checklist: progress, pages to redo, the next editions with what to
# search for, then each year, the worst first.
g.usual_pages = lambda: {1988: (16, 24, 18)}
rows = [(D(1987, 3, 2), "no-scan"), (D(1988, 1, 12), "no-scan"), (D(1988, 1, 13), "no-scan"),
        (D(1988, 1, 14), "no-scan")]
html = g.checklist(rows, cache, un)
check("the worst year first", True, html.index("<b>1988</b>: 3 missing") < html.index("<b>1987</b>: 1 missing"))
check("progress counts the arrived editions", True, "<b>1 of 4</b> arrived, 3 to go" in html)
nxt = html[html.index("<h2>Next up"):html.index("<h2>Everything")]
check("next up starts at the worst year's first edition not arrived", True,
      nxt.index("Wed 13 Jan 1988") < nxt.index("Thu 14 Jan 1988") < nxt.index("Mon 02 Mar 1987"))
check("an arrived edition is not next up", False, "Tue 12 Jan 1988" in nxt)
check("a search to copy for the puzzle's number", True,
      """onclick="cp(this,&quot;\\&quot;Crossword Puzzle No 17,564\\&quot;&quot;)">Copy</button>""" in nxt)
check("the ordering rule is said", True, g.ORDER in nxt)
check("next up is a pool with its Next batch and Refresh", True,
      '<table id="next">' in nxt and 'onclick="nextBatch()"' in nxt and 'onclick="location.reload()"' in nxt)
check("the pool is POOL long, the lookahead longer", ([D(1988, 1, 13)], 60, 200),
      ([d for d, _ in g.next_up(rows, {D(1988, 1, 12): []}, 1)], g.POOL, g.LOOKAHEAD))
check("each row to fetch has a state badge the script fills", True, '<span class="st"></span>' in nxt)
check("which says downloading, then late, then in the inbox", True,
      all(w in html for w in ("downloading&hellip; clicked", 'not arrived: <a class="retry"', "&#10003; in the inbox")))
check("an estimated number says so", True, "number estimated" in nxt[nxt.index("Mon 02 Mar 1987"):])
check("a date's likely page", True, "p. 18 (or 16-24)" in nxt)
check("an arrived edition is marked", True, "arrived (1988-01-12 page 2.png, GALE|IF0503151598 1988-01-12.jpg)" in html)
bad = html[html.index("Check these files"):html.index('<div class="how">')]
check("an unmatched file is listed to redo", True, "holiday snap.jpg" in bad and "Rename it" in bad)
check("a page with no grid is listed to redo", True, "no crossword grid" in bad)
check("the page reads its status file, no blind refresh", (True, False),
      ('SRC="Checklist.status.js"' in html, 'http-equiv="refresh"' in html))
arrived = next(r for r in html.split("\n") if 'data-k="1988-01-12"' in r)
check("an arrived row says so and offers no Download", (True, True, False, False),
      ('data-in="1"' in arrived, "in the inbox" in arrived, 'class="dl"' in arrived, "Open in Gale" in arrived))
check("Download is a big button", True, all(w in g.CSS for w in ("a.dl{display:inline-block;padding:8px 18px;font-size:17px",)))
status = {}
g.checklist(rows, cache, un, status=status)
check("a render's status names the page and its arrived rows", (True, ["1988-01-12"]),
      (status["page"] > 0, status["in"]))
published = []
g.publish = lambda path, host_inbox=None: published.append(path.name)
page_path = Path(sys.argv[1]) / "Checklist.html"
g.publish_status(page_path, status)
g.publish_status(page_path)
js = (Path(sys.argv[1]) / "Checklist.status.js").read_text()
check("the status file is a script call, kept between renders, published each tick",
      (True, ["1988-01-12"], ["Checklist.status.js"] * 2),
      (js.startswith("galeStatus("), json.loads(js[len("galeStatus("):js.rindex(")")])["in"], published))
check("the session link comes before any row's link", True,
      html.index(g.SESSION.format("TTDA")) < html.index('class="go"'))
check("the session link and every row's Gale link open in one tab", [],
      [a for a in re.findall(r'<a [^>]*href="https://[^"]*gale\.com[^>]*>', html) if 'target="gale"' not in a])
check("and there are such links: the session and each row's search", True,
      html.count('target="gale"') >= 1 + nxt.count("Open in Gale"))
want = ("https://go.gale.com/ps/advancedSearch.do?inputFieldNames%5B0%5D=TI&inputFieldValues%5B0%5D=crossword"
        "&dateIndices=DA&dateLimiterValues%5BDA%5D.dateMode=2&dateLimiterValues%5BDA%5D.fromYear=1988"
        "&dateLimiterValues%5BDA%5D.fromMonth=01&dateLimiterValues%5BDA%5D.fromDay=13"
        "&dateLimiterValues%5BDA%5D.fromEra=1&searchType=AdvancedSearchForm&method=doSearch&searchMethod=advanced"
        "&searchResultsType=SingleTab&prodId=TTDA&userGroupName=alberta_portal")
check("a date's link is Gale's title search on that day, month and day zero-padded", want,
      g.search_url(D(1988, 1, 13)))
check("each next-up row links its date's search, kept beside Copy", True,
      f'<a class="go" href="{g.html.escape(want)}" target="gale" onclick="mark(\'1988-01-13\')">Open in Gale</a> '
      '<button onclick="cp(' in nxt)
check("the Listener's link searches its own archive", True, "prodId=LSNR" in g.search_url(D(1930, 4, 9), "LSNR"))
check("no link fetches a document or names a session id", [], [u for u in re.findall(r'href="([^"]+)"', html)
      if "retrieve.do" in u or "PHPSESSID" in u or "jsessionid" in u.lower()])
check("a page for a date the list does not ask for is flagged", [("x.pdf", True)],
      [(f, "not on the list" in why) for f, why in g.problems(rows, held, {D(1988, 2, 1): ["x.pdf"]}, Path("/nonexistent"))])
check("but not one already filed", [], g.problems(rows, {17396: D(1987, 6, 30)}, {D(1987, 6, 30): ["y.pdf"]},
                                                  Path("/nonexistent")))

# Recognising and routing Gale files: by Gale's document id in the name or
# Gale's citation in a PDF's text; the drop folder takes any page file;
# nothing else in Downloads is touched.
def pdf(text):
    """A one-page PDF whose text is `text`."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)

# A Gale page download: a whole bilevel page (ink 0, paper 255) as an image,
# then a page of citation text quoting the article's title. Its grid is
# found among a bigger photo, and its date read off the citation.
import numpy as np, pypdf, trove_grid
from PIL import ImageDraw
bi = np.array([[0, 255, 255], [255, 0, 255]], dtype=np.uint8)
check("a bilevel page's ink is all its black", 2, int((bi < trove_grid.otsu(bi)).sum()))
whole = Image.new("L", (4600, 7200), 255)
draw = ImageDraw.Draw(whole)
draw.rectangle((1200, 400, 3300, 2400), fill=0)  # a photo, square and bigger than any grid
for i in range(16):  # a 15x15 grid, 1000px wide
    draw.rectangle((200 + i * 66, 4700, 206 + i * 66, 5696), fill=0)
    draw.rectangle((200, 4700 + i * 66, 1196, 4706 + i * 66), fill=0)
for r, c in [(1, 1), (1, 3), (3, 5), (5, 1), (7, 7), (9, 9), (11, 3), (13, 13)]:
    draw.rectangle((200 + c * 66, 4700 + r * 66, 266 + c * 66, 4766 + r * 66), fill=0)
whole = whole.convert("1")
page, found = g.scaled(whole.convert("RGB"))
check("a whole page is scaled by its grid, not its photo", (True, True),
      (found, any(abs(b[2] - b[0] - g.GRID_WIDTH) < 20 for b in fa.grids_on(page))))
gale = Path(sys.argv[1]) / "IF0500004465.pdf"
buf = io.BytesIO()
whole.save(buf, "PDF")
w = pypdf.PdfWriter()
w.add_page(pypdf.PdfReader(buf).pages[0])
w.add_page(pypdf.PdfReader(io.BytesIO(pdf('"The Times Crossword Puzzle No 17,244." Times, 3 Jan. 1987, p. 20. '
                                          "The Times Digital Archive, link.gale.com/apps/doc/IF0500004465/"))).pages[0])
w.write(gale)
m = g.match(gale, held)
check("a Gale download is dated by its citation page", (D(1987, 1, 3), "PDF citation", 20, True),
      (m["date"], m["how"], m["page"], m["grid"]))

times = g.pdf_text(pdf("The Times, 12 Jan. 1988, p. 18. The Times Digital Archive. Gale Document Number: GALE|IF0503151598"))
listener = g.pdf_text(pdf("The Listener, 5 Feb. 1970, p. 190. The Listener Historical Archive. link.gale.com/apps/doc/X"))
tax = g.pdf_text(pdf("Notice of assessment 2025. Canada Revenue Agency"))
check("a PDF's text is read", True, "Times Digital Archive" in times)
check("a file that is not a PDF has no text", "", g.pdf_text(b"\xff\xd8 jpeg bytes"))
for name, text, dropped, want in [
        ("GALE_IF0503151598.pdf", times, False, "times"),
        ("GALE|IF0503151598.jpg", "", False, "times"),
        ("download.pdf", times, False, "times"),
        ("download.pdf", listener, False, "listener"),
        ("GALE_CS123456789.pdf", listener, False, "listener"),
        ("TARJAN.pdf", tax, False, None),
        ("holiday.jpg", "", False, None),
        ("Borderlands.iso", "", False, None),
        ("GALE_IF0503151598.crdownload", "", False, None),
        ("scan of 1988-01-12.jpg", "", True, "times"),
        ("listener 1970-02-05.png", "", True, "listener"),
        ("notes.txt", "", True, None)]:
    check(f"{name!r} ({'drop folder' if dropped else 'Downloads'}) goes to", want, g.classify(name, text, dropped))
check("a Downloads PDF without Gale's name is read to tell", True, g.needs_text("download.pdf", False))
check("one with Gale's name is not", False, g.needs_text("GALE_IF0503151598.pdf", False))
check("a drop-folder PDF is read for its paper", True, g.needs_text("x.pdf", True))
check("a name already in the inbox gets a free one", "a (3).pdf", g.free_name("a.pdf", {"a.pdf", "a (2).pdf"}))
check("listing lines parse, junk skipped", [("downloads", 10, 1759700000, "GALE_X 1.pdf"), ("desktop", 5, 1, "y.pdf")],
      g.parse_listing("downloads\t10\t1759700000\t./GALE_X 1.pdf\nstat: junk\ndesktop\t5\t1\ty.pdf\r\n"))
check("the inboxes share one root on the Media share", (True, True),
      (g.HOST_INBOX.startswith(g.GALE_ROOT + "/"), g.LISTENER_INBOX.startswith(g.GALE_ROOT + "/")))
stamp = Path(sys.argv[1]) / "looked_up"
check("Gale is asked at most every LOOKUP_EVERY, however often the tick runs", [True, False, False, True],
      [g.gale_due(t, stamp) for t in (1000, 1060, 1120, 1000 + g.LOOKUP_EVERY)])
print("FAILS", fails)
sys.exit(1 if fails else 0)
PY
