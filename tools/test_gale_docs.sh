#!/bin/bash
# Does tools/gale_docs.py find the day's crossword in a Gale issue's contents
# (the numbered Times or Listener puzzle, not the Concise or a competition),
# build Gale's Download link with a citation the inbox recognises and files,
# look up at most its limit of uncached rows, remember misses, stop at Gale's
# first error, and do both checklists offer Download beside Open in Gale?
#
#     bash tools/test_gale_docs.sh
#
# Gale is a stand-in object: nothing is asked of Gale, the portal, the Mac or
# the desktop, and nothing is written outside a temp dir.
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 - "$tmp" <<'PY'
import datetime, io, sys, urllib.parse
from pathlib import Path
import gale_docs as gd
import gale_inbox as gi
import gale_listener as gl

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

D = datetime.date
tmp = Path(sys.argv[1])

def issue(titles, pages=24):
    toc = [{"docId": None, "docTitle": f"Page {p}", "startingPage": p, "subArticleDocuments": [
        {"docId": f"IF{1000 + i:010}", "docTitle": t, "startingPage": p, "pageCount": n, "subArticleDocuments": []}
        for i, (t, p2, n) in enumerate(titles) if p2 == p]} for p in range(1, pages + 1)]
    return {"originalDocument": {"articleTableOfContents": toc},
            "pageDocuments": [{"pageNumber": p, "mediaRecordId": f"rec{p}%2F"} for p in range(1, pages + 1)]}

class FakeGale:
    def __init__(self, days, fail=()):
        self.days, self.fail, self.asked = days, set(fail), []
    def issues(self, prod, day):
        self.asked.append(day)
        if day in self.fail:
            raise OSError("Gale said 500")
        return [{"mcode": "0FFO", "date": f"1{day:%Y%m%d}", "issueNumber": "1", "volume": ""}] if day in self.days else []
    def issue(self, prod, i):
        return self.days[datetime.datetime.strptime(i["date"][1:], "%Y%m%d").date()]

times = issue([("Concise crossword No 1460", 8, 1), ("The Times Crossword Puzzle No 17,563", 18, 1),
               ("Solution to Puzzle No 17,562", 18, 1)])
e = gd.entry("TTDA", times, 17563)
check("the Times cryptic, not the Concise or the solution", ("IF0000001001", 18, ["rec18%2F"]),
      (e["doc"], e["page"], e["records"]))
listener = issue([("Competition No. 8", 13, 1), ("Crossword No. 1,309", 42, 2)], 44)
e = gd.entry("LSNR", listener, 1309)
check("the Listener crossword, both its pages", ("IF0000001001", ["rec42%2F", "rec43%2F"]), (e["doc"], e["records"]))
check("the numbered one first", 1, gd.crossword("TTDA", ["The Times Crossword Puzzle No 17,562",
                                                         "The Times Crossword Puzzle No 17,563"], 17563))
check("no crossword, no entry", None, gd.entry("LSNR", issue([("Competition No. 8", 13, 1)]), 8))

# The link: Gale's BulkPDF GET, its citation the one the inbox files by.
day = D(1988, 1, 12)
url = gd.download_url("TTDA", day, gd.entry("TTDA", times, 17563))
q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
check("the Download target", "https://go.gale.com/ps/callisto/BulkPDF/UBER2", url.split("?")[0])
check("the document and its page record", ("IF0000001001", "TTDA", "rec18%2F"), (q["dl"], q["p"], q["recordIds"]))
cite = urllib.parse.unquote(q["citationTextJson"])
check("the citation is recognised as Gale's", True, gi.is_gale("IF0000001001.pdf", cite))
m = gi.CITED.search(cite)
check("and dates the page", (day, 18), (D(int(m.group(3)), gi.MONTHS[m.group(2)[:3].lower()], int(m.group(1))),
                                        int(m.group(4))))
lday = D(1955, 6, 2)
lcite = urllib.parse.unquote(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(
    gd.download_url("LSNR", lday, gd.entry("LSNR", listener, 1309))).query))["citationTextJson"])
check("the Listener citation dates the page", lday, gl.cited_day(lcite))

# resolve: at most `limit` uncached rows, a miss kept, stops at an error.
cache = tmp / "docs.json"
days = [D(1988, 1, d) for d in range(4, 12)]
fake = FakeGale({d: times for d in days[:3] + [days[4]]}, fail=[days[5]])
out = io.StringIO()
check("links added, up to the limit", 4, gd.resolve("TTDA", [(d, None) for d in days], out, fake, cache, limit=5))
check("a day with no issue is kept as a miss", "Gale has no issue that day", gd.load(cache)["TTDA/1988-01-07"]["why"])
check("a date asked once for two puzzles", 0, gd.resolve("TTDA", [(D(1990, 1, 1), 1), (D(1990, 1, 1), 2)], out, fake,
                                                         tmp / "dup.json"))
check("once", 1, sum(d == D(1990, 1, 1) for d in fake.asked))
fake.asked.clear()
check("the next tick asks only what is not cached, up to the error", 0,
      gd.resolve("TTDA", [(d, None) for d in days], out, fake, cache, limit=5))
check("and asked just those", [days[5]], fake.asked)
check("the error is said", True, "OSError: Gale said 500" in out.getvalue())
check("the failed day is asked again later", False, "TTDA/1988-01-09" in gd.load(cache))
check("a cached link", True, (gd.link("TTDA", days[0], gd.load(cache)) or "").startswith("https://go.gale.com/ps/callisto"))
check("no link for a miss", None, gd.link("TTDA", days[3], gd.load(cache)))

# The checklists: Download where a link is cached, Open in Gale always.
docs = {"TTDA/1988-01-12": gd.entry("TTDA", times, 17563)}
row = next(r for r in gi.checklist([(day, "no-scan"), (D(1988, 1, 13), "no-scan")], tmp / "cache", tmp / "un.json",
                                   docs=docs).split("\n") if 'data-k="1988-01-12"' in r)
check("Times row has Download", True, ">Download</a>" in row and "callisto/BulkPDF" in row)
check("its Download is the row's click, and marks it", True,
      'class="dl"' in row and "onclick=\"mark('1988-01-12')\">Download" in row)
check("and still Open in Gale", True, "Open in Gale" in row)
other = next(r for r in gi.checklist([(day, "no-scan"), (D(1988, 1, 13), "no-scan")], tmp / "cache", tmp / "un.json",
                                     docs=docs).split("\n") if 'data-k="1988-01-13"' in r)
check("an unlinked Times row: Open in Gale only", (False, True), ("Download</a>" in other, "Open in Gale" in other))
check("Open in Gale marks only a row with no Download", (False, True),
      ("onclick=\"mark('1988-01-12')\">Open in Gale" in row, "onclick=\"mark('1988-01-13')\">Open in Gale" in other))
idx = [{"number": 1309, "title": "Crossword No. 1,309", "setter": None, "date": lday}]
page = gl.checklist(idx, tmp / "store", tmp / "none", arrivals=[],
                    docs={"LSNR/1955-06-02": gd.entry("LSNR", listener, 1309)})
check("Listener row has Download", True, ">Download</a>" in page and "p=LSNR" in page)
check("the Listener's Download marks its row", True,
      'class="dl"' in page and "onclick=\"mark('p1309')\">Download</a>" in page)
check("to_save lists it", [1309], [r["number"] for r in gl.to_save(idx, tmp / "store", tmp / "none", arrivals=[])])

# Gale's OCR'd titles still find the crossword; a report is found by its number.
check("OCR'd crossword titles", [0, 0, 0, 0], [gd.crossword("LSNR", [t], n) for t, n in [
    ("Grossword No. 630", 630), ("Crossward No. 607", 607), ("No. 360. 'Cross-number XIV'. By Afrit", 360),
    ("Crossnumber No. 793", 793)]])
check("a report is not the crossword", None, gd.crossword("LSNR", ["Report on Crossword No. 81"], 83))
check("the report on the number asked", 1, gd.report(["Report on Crossword No. 1,308", "Report on Crossword No. 1,309"],
                                                    1309))
# A miss from an older matcher is asked again once; a current one is not.
mcache = tmp / "miss.json"
mcache.write_text('{"LSNR/1955-06-02": {"why": "no crossword in the issue\'s contents"}}')
fake = FakeGale({lday: listener})
check("an old miss is looked up again", 1, gd.resolve("LSNR", [(lday, 1309)], out, fake, mcache))
mcache.write_text('{"LSNR/1955-06-02": {"why": "x", "matcher": %d}}' % gd.MATCHER)
check("a current miss is not", (0, []), (gd.resolve("LSNR", [(lday, 1309)], out, fake, mcache), fake.asked[1:]))
# The report on a puzzle: in an issue some weeks after it, linked as its own row.
rday = lday + datetime.timedelta(weeks=2)
fake = FakeGale({rday: issue([("Report on Crossword No. 1,309", 40, 1)], 44)})
rcache = tmp / "rep.json"
check("a report looked up after its row's doc link, in the same limit", 2,
      len([gd.resolve("LSNR", [(lday, 1309)], out, fake, rcache, limit=2, reports=[(lday, 1309)])] and gd.load(rcache)))
ocache = tmp / "order.json"
d1, d2 = lday, lday + datetime.timedelta(weeks=1)
gd.resolve("LSNR", [(d1, 1), (d2, 2)], out, FakeGale({}), ocache, limit=3, reports=[(d1, 1), (d2, 2)])
check("by row: doc and report of the first row, then the second row's doc, its report left for later",
      (True, False), ("LSNR/report/1" in gd.load(ocache) and "LSNR/1955-06-09" in gd.load(ocache), "LSNR/report/2" in gd.load(ocache)))
check("its issue's date kept", "1955-06-16", gd.load(rcache)["LSNR/report/1309"]["day"])
rq = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(gd.report_link("LSNR", 1309, gd.load(rcache))).query))
check("its link cites the report's issue", True, "16 June 1955, p. 40" in urllib.parse.unquote(rq["citationTextJson"]))
check("no report, a miss", True, "no report" in gd.lookup_report("LSNR", lday, FakeGale({}), 1309)["why"])

print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
PY
