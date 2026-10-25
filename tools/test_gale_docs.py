#!/usr/bin/env python3
# Does tools/gale_docs.py find the day's crossword in a Gale issue's contents
# (the numbered Times or Listener puzzle, not the Concise or a competition)
# and a Listener report in the weeks after its puzzle, build Gale's Download
# link with a citation naming its document, and look a miss up again only
# when an older matcher made it? Does tools/gale_listener.py want each
# Listener puzzle not filed or read, then its report?
#
#     python3 tools/test_gale_docs.py
#
# Gale is a stand-in object: nothing is asked of Gale, the portal, the Mac or
# the desktop, and nothing is written outside a temp dir.
import os
import sys
import atexit
import shutil
import tempfile
os.chdir(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
atexit.register(shutil.rmtree, tmp, True)
sys.argv[1:] = [tmp]

import datetime, sys, urllib.parse
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

# lookup: a day with no issue is a miss, said so.
check("a day with no issue is a miss", "Gale has no issue that day", gd.lookup("TTDA", D(1988, 1, 7), FakeGale({}))["why"])
check("a day's crossword is found", "IF0000001001", gd.lookup("TTDA", day, FakeGale({day: times}), 17563)["doc"])

# What tools/gale_fetch.py fetches for the Listener: each printed puzzle not
# filed or read, earliest first, its report page after it.
idx = [{"number": 1309, "title": "Crossword No. 1,309", "setter": None, "date": lday},
       {"number": 1310, "title": "[No crossword]", "setter": None, "date": lday + datetime.timedelta(weeks=1)}]
check("to_save lists it", [1309], [r["number"] for r in gl.to_save(idx, tmp / "store", tmp / "none")])
check("wanted: its page, then its report", [(lday, 1309, False), (lday, 1309, True)],
      gl.wanted(idx, tmp / "store", tmp / "none"))

# Gale's OCR'd titles still find the crossword; a report is found by its number.
check("OCR'd crossword titles", [0, 0, 0, 0], [gd.crossword("LSNR", [t], n) for t, n in [
    ("Grossword No. 630", 630), ("Crossward No. 607", 607), ("No. 360. 'Cross-number XIV'. By Afrit", 360),
    ("Crossnumber No. 793", 793)]])
check("a report is not the crossword", None, gd.crossword("LSNR", ["Report on Crossword No. 81"], 83))
# The other papers' titles, as their archives' contents give them.
check("the Telegraph's clue heading names its cryptic, not the Quick's", [1, 0, None],
      [gd.crossword("TGRH", ["Quick Crossword across", "No. 12,212 across"]),
       gd.crossword("TGRH", ["Crossword / 21,502", "Quick crossword"]),
       gd.crossword("TTDA", ["No. 12,212 across"])])
check("the Sunday Times' cryptic, not its Mephisto or French one", [1, 1],
      [gd.crossword("STHA", ["Mephisto Crossword", "Crossword"]),
       gd.crossword("STHA", ['"Sunday Times" French Cross-Word No. 15', '"Sunday Times" Cross-Word Puzzle No. 792'])])
check("FT and Independent titles", [0, 1, 1],
      [gd.crossword("FTHA", ["F. T. Crossword Puzzle No. 2,718"]), gd.crossword("INDA", ["Concise crossword #9171",
       "Cryptic crossword #9172"]), gd.crossword("INDA", ["BritishRedCross", "The Tuesday Crossword"])])
check("the TLS's newest crossword, not the last one's solution under its title", 0,
      gd.crossword("TLSH", ["TLS Crossword 604", "TLS Crossword 603", "Engrossing items"]))
check("the report on the number asked", 1, gd.report(["Report on Crossword No. 1,308", "Report on Crossword No. 1,309"],
                                                    1309))
# 2006's Times: the cryptic, not page 2's index entry for it, Times2's quick,
# the Listener, or a championship report printed before it.
check("the Times cryptic among 2006's crossword titles", [2, 1, None, 1, 1],
      [gd.crossword("TTDA", ["Crossword Today's Weather", "Crossword 95", "The Times Crossword 23,296",
                             "times2 Crossword No 3910"]),
       gd.crossword("TTDA", ["Are you the next Times Crossword Champion?", "The Times Crossword 23,359",
                             "Times2 Crossword No 3973"]),
       gd.crossword("TTDA", ["The Listener Crossword 3890", "Crossword 67 Miscellany"]),
       gd.crossword("TTDA", ["Crossword", "Times Crossword"]),
       gd.crossword("TTDA", ["Crossword contest gives clue to staying young", "The Times Crossword Puzzle No 17,563"])])
check("the Times cryptic under Gale's OCR misreadings of its title", [0, 0, 0, 0, 0, None],
      [gd.crossword("TTDA", [t]) for t in (
          "The Times Crossworld Puzzle No. 426", "The Times Crossmord Puzzle No. 714", "The Times Crosssword Puzzle No 19,888",
          "The Times Crossw0rd 22,568", "The Times Crosswor", "Gross worth of Times Two")])
# 2004: page 2's "The Times Today ... Crossword; 26" line was kept as the
# crossword (saving page 1); the real one is "The Temes Crossword" / "The
# Times Corssword", or untitled, then its page is the contents line's number.
check("the Times Today contents line is never the crossword", [1, 1, None],
      [gd.crossword("TTDA", ["The Time Today; page 2. Crossword; 26 law Roport; 41", "The Temes Crossword"]),
       gd.crossword("TTDA", ["The Times Today page 2. Crossword: and weather: 30.", "The Times Corssword"]),
       gd.crossword("TTDA", ["The Times Today: page2. crossword: 22. The Register.", "The Times"])])
d04 = D(2004, 4, 8)
g04 = FakeGale({d04: issue([("The Times Today: page2. crossword: 22. The Register.", 1, 1), ("The Times", 21, 1)])})
check("no crossword article: the contents line's page", ("Crossword", 22),
      (lambda e: (e["title"], e["page"]))(gd.lookup("TTDA", d04, g04)))
check("a Times link an older matcher picked is stale unless the cryptic's", [True, True, False, False],
      [gd.stale("TTDA", {"doc": "x", "title": t, **m}) for t, m in [
          ("Crossword 95", {}), ("Crossword", {}), ("The Times Crossword 23,296", {}),
          ("Crossword 95", {"matcher": gd.MATCHER["TTDA"]})]])
rej = tmp / "rejected.txt"
rej.write_text("# note\n1976-04-17 jumbo cs0000001001\n\n2010-04-22..27 front-page IF0000001002\n")
check("the rejected list's docIds, upper-cased", {"CS0000001001", "IF0000001002"}, gd.rejected(rej))
check("no rejected file, none", set(), gd.rejected(tmp / "none.txt"))
check("the shipped list holds the reported documents", True,
      {"CS117669521", "IF0503933187", "IF0504059963"} <= gd.REJECTED_DOCS)
rtimes = issue([("The Times Crossword Puzzle No 17,563", 18, 1), ("Crossword", 20, 1)])
gd.REJECTED_DOCS = {"IF0000001000"}
check("a rejected document is never picked, the next-best is", ("IF0000001001", 20),
      (lambda e: (e["doc"], e["page"]))(gd.entry("TTDA", rtimes, 17563)))
check("an entry naming it is stale even under the current matcher", [True, False],
      [gd.stale("TTDA", {"doc": "if0000001000", "title": "The Times Crossword 23,296", "matcher": gd.MATCHER["TTDA"]}),
       gd.stale("TTDA", {"doc": "IF0000001001", "title": "The Times Crossword 23,296", "matcher": gd.MATCHER["TTDA"]})])
gd.REJECTED_DOCS = gd.rejected()
check("the other papers' links are not", False, gd.stale("LSNR", {"doc": "x", "title": "Competition"}))
# The Saturday Times' Listener article: its own kind, picked from the issue's
# contents, apart from the daily crossword (which still rejects it).
check("the Listener article among a Saturday's titles", [1, None, None, 1],
      [gd.listener_article(ts) for ts in (["The Times Crossword 23,296", "The Listener Crossword 3890"],
                                          ["The Times Crossword 23,296", "Crossword 67 Miscellany"],
                                          ["Report on Listener Crossword No 3,890", "Listener crossword solution"],
                                          ["Times2 Crossword", "Listener crossword"])])
check("the numbered Listener article first", 1, gd.listener_article(["Listener Crossword 3889", "Listener Crossword 3890"], 3890))
check("the daily pick never takes it", None, gd.crossword("TTDA", ["The Listener Crossword 3890"]))
sat = D(2006, 8, 12)
lk = FakeGale({sat: issue([("The Times Crossword 23,296", 60, 1), ("The Listener Crossword 3890", 70, 1)], 80)})
le = gd.lookup("TTDA", sat, lk, kind="listener")
daily = gd.lookup("TTDA", sat, lk)
check("lookup(kind) takes the Listener article, marked", ("The Listener Crossword 3890", 70, "listener"),
      (le["title"], le["page"], le["kind"]))
check("the daily lookup still takes the cryptic", ("The Times Crossword 23,296", 60), (daily["title"], daily["page"]))
check("no Listener article that day, a why", "no crossword in the issue's contents",
      gd.lookup("TTDA", sat, FakeGale({sat: issue([("The Times Crossword 23,296", 60, 1)], 80)}), kind="listener")["why"])
check("a Listener-kind miss is stale only under an older matcher", [True, False],
      [gd.stale("TTDA", {"kind": "listener", "why": "x"}), gd.stale("TTDA", {"kind": "listener", "why": "x", "matcher": gd.MATCHER["listener"]})])
check("a Listener-kind hit is never stale, whatever its title", False,
      gd.stale("TTDA", {"kind": "listener", "doc": "x", "title": "Listener 3890"}))
# A miss from an older matcher is asked again once; a current one is not.
check("an old miss is stale", True, gd.stale("LSNR", {"why": "no crossword in the issue's contents"}))
check("a current miss is not", False, gd.stale("LSNR", {"why": "x", "matcher": gd.MATCHER["LSNR"]}))
# The report on a puzzle: in an issue some weeks after it, its issue's date kept.
rday = lday + datetime.timedelta(weeks=2)
fake = FakeGale({rday: issue([("Report on Crossword No. 1,309", 40, 1)], 44)})
r = gd.lookup_report("LSNR", lday, fake, 1309)
check("its issue's date kept", "1955-06-16", r["day"])
rq = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(gd.download_url("LSNR", D.fromisoformat(r["day"]), r)).query))
check("its link cites the report's issue", True, "16 June 1955, p. 40" in urllib.parse.unquote(rq["citationTextJson"]))
check("no report, a miss", True, "no report" in gd.lookup_report("LSNR", lday, FakeGale({}), 1309)["why"])

# report_lookups reads the ledger once, not once a row (it took 55 s on 3,000 rows).
calls = []
real = gl.solutions
gl.solutions = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
try:
    gl.report_lookups([{"number": n, "title": "x", "date": D(1950, 1, 1)} for n in range(1, 50)],
                      store=tmp / "nostore", root=tmp / "noroot")
finally:
    gl.solutions = real
check("report_lookups asks for the solutions a fixed number of times", True, len(calls) <= 3)

print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
