#!/bin/bash
# Does a page saved into the Gale inbox become a Times edition the scan filer
# reads (tools/gale_inbox.py): matched to its date by the date or puzzle
# number in its name, numbered from the filed puzzles either side, laid out
# as GaleTimes<year>UKEnglish/<date> with a Gale document's link, due again
# when a file is added or replaced for that date and no other, and gone when
# the inbox no longer holds it?
#
#     bash tools/test_gale_inbox.sh
#
# Synthetic pages in a temp dir: no OCR, nothing asked of the Mac or Gale,
# nothing written outside it.
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 - "$tmp" <<'PY'
import datetime, io, json, sys
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
g.stage(inbox, cache, out, un)
d = cache / "GaleTimes1988UKEnglish" / "1988-01-12"
pages = json.loads((d / "pages.json").read_text())
check("a dated page is staged as that date's Times edition", (True, "1988-01-12", 1),
      ((d / "leaf_0000.jpg").exists(), pages["date"], pages["leaves"]))
check("its source link is the Gale document's", g.DOC_URL.format("IF0503151598"), fa.page_url(d, {}, 0))
check("a page set on an archive.org-wide page", fa.SCAN_WIDTH, Image.open(d / "leaf_0000.jpg").width)
check("a file that names no edition is listed, not staged", ["holiday snap.jpg"],
      [m["file"] for m in json.loads(un.read_text())])
check("the Times filer finds the staged edition", [d], [e for e in fa.edition_dirs(cache, fa.TIMES)])
check("as a Times edition", fa.TIMES, fa.paper_of(d))
check("and no other paper's", [], fa.edition_dirs(cache, fa.FT))
first = fa.input_hash(d)
g.stage(inbox, cache, io.StringIO(), un)
check("an inbox unchanged leaves the edition's inputs alone", first, fa.input_hash(d))
check("and its inputs are its files' (inputs_of)", first, fa.inputs_of(first, {"puzzles": []}, "times"))
Image.new("RGB", (400, 300), "white").save(inbox / "1988-01-12 page 2.png")
g.stage(inbox, cache, io.StringIO(), un)
second = fa.input_hash(d)
check("a second page for the date makes that edition due", (True, 2),
      (second != first, json.loads((d / "pages.json").read_text())["leaves"]))
Image.new("RGB", (401, 300), "black").save(inbox / "1988-01-12 page 2.png")
g.stage(inbox, cache, io.StringIO(), un)
check("a page replaced makes it due again", True, fa.input_hash(d) not in (first, second))
other = cache / "GaleTimes1988UKEnglish" / "1988-01-13"
Image.new("RGB", (400, 300), "white").save(inbox / "1988-01-13.jpg")
before = fa.input_hash(d)
g.stage(inbox, cache, io.StringIO(), un)
check("a page for another date is its own edition, the first left alone", (True, before),
      (other.exists(), fa.input_hash(d)))
(inbox / "1988-01-13.jpg").unlink()
g.stage(inbox, cache, io.StringIO(), un)
check("a page gone from the inbox takes its edition with it", False, other.exists())

# The checklist: each wanted date with its number, the worst year first,
# an edition in the inbox marked.
g.usual_pages = lambda: {1988: (16, 24, 18)}
html = g.checklist([(D(1987, 3, 2), "no-scan"), (D(1988, 1, 12), "no-scan"), (D(1988, 1, 13), "no-scan")],
                   cache, un)
check("the worst year first", True, html.index("<h2>1988: 2 missing") < html.index("<h2>1987: 1 missing"))
check("a date's number and page", True, "<td>Tue 12 Jan 1988</td><td>17,563</td><td>p. 16-24 (most 18)</td>" in html)
check("an estimated number is marked", True, "<td>Mon 02 Mar 1987</td><td>~" in html)
check("a staged date is marked in the inbox", True, "in inbox (1988-01-12 page 2.png, GALE|IF0503151598 1988-01-12.jpg)" in html)
check("the unmatched file is listed", True, "holiday snap.jpg" in html)
print("FAILS", fails)
sys.exit(1 if fails else 0)
PY
