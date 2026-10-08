#!/bin/bash
# Does a page saved into the Gale inbox become a Times edition the scan filer
# reads (tools/gale_inbox.py): matched to its date by the date or puzzle
# number in its name, numbered from the filed puzzles either side, laid out
# as GaleTimes<year>UKEnglish/<date> with a Gale document's link, due again
# when a file is added or replaced for that date and no other, and gone when
# the inbox no longer holds it? Is a Gale download recognised by its name or
# citation and routed to its paper's inbox, everything else left alone, and
# does the checklist lead with progress and what to search, sorting every
# file that is not a wanted page out by itself (set aside, never asked)?
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
# The Mac's own document cache must not leak in; CI has none.
g.gale_docs.load = lambda cache=None: {}

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
# One laid out under the portal's link, before its document was read off
# its name, is laid out again with the document's; then left alone.
pages["url"] = g.PORTAL
(d / "pages.json").write_text(json.dumps(pages))
import os as _os
_os.utime(d / "pages.json", (1000, 1000))
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES)
check("an edition laid out under the portal's link is relinked to its document's, still laid out when it was",
      (g.DOC_URL.format("IF0503151598"), 1000), (fa.page_url(d, {}, 0), int(fa.staged_at(d))))
check("a page set on an archive.org-wide page", fa.SCAN_WIDTH, Image.open(d / "leaf_0000.jpg").width)
check("a file that names no edition is listed, not staged", ["holiday snap.jpg"],
      [m["file"] for m in json.loads(un.read_text()) if not m.get("date")])
check("a staged page with no grid on it is listed", ["GALE|IF0503151598 1988-01-12.jpg"],
      [m["file"] for m in json.loads(un.read_text()) if m.get("date")])
check("each file's match is kept, so a tick re-reads only what moved", 2,
      len(json.loads(g.MATCHES.read_text())))
check("under the matcher's version, so a fix re-reads every file", True,
      all(k.startswith(g.MATCHER + "\t") for k in json.loads(g.MATCHES.read_text())))
check("the Gale run finds the staged edition", [d], [e for e in fa.edition_dirs(cache, fa.GALE)])
check("as a Gale page, filed as the Times", (fa.GALE, "times"), (fa.paper_of(d), fa.paper_of(d).series))
check("and no other run's", ([], []), (fa.edition_dirs(cache, fa.FT), fa.edition_dirs(cache, fa.TIMES)))
rel = f"{d.parent.name}/{d.name}"
now = (d / "pages.json").stat().st_mtime
check("fresh_unread: an edition just laid out and never read is read now", [rel], g.fresh_unread(cache, {}, now))
check("not once read with its current files", [],
      g.fresh_unread(cache, {rel: {"inputs": "x", "filesHash": fa.input_hash(d)}}, now))
check("again once its files change", [rel], g.fresh_unread(cache, {rel: {"inputs": "x", "filesHash": "old"}}, now))
check("one laid out before FRESH is the full pass's", [], g.fresh_unread(cache, {}, now + g.FRESH + 1))
launched = []
class FakePopen:
    pid = 1
    def __init__(self, cmd, **kw):
        launched.append((cmd, kw))
saved_popen, saved_fresh = g.subprocess.Popen, g.fresh_unread
g.subprocess.Popen, g.fresh_unread = FakePopen, lambda: [rel]
import os as _os
_os.environ["CT_IN_WORKTREE"], _os.environ["CT_MAIN_CHECKOUT"] = "1", "/tick/tree"
g.start_reads(io.StringIO(), job=Path("/x/gale_read.sh"), log=Path(sys.argv[1]) / "read.log")
check("start_reads starts the read job detached, out of this tick's worktree (its own lease and tree)",
      (["bash", "/x/gale_read.sh"], True, False, False),
      (launched[0][0], launched[0][1]["start_new_session"], "CT_IN_WORKTREE" in launched[0][1]["env"],
       "CT_MAIN_CHECKOUT" in launched[0][1]["env"]))
g.fresh_unread = lambda: []
check("and nothing when no fresh edition waits", None, g.start_reads(io.StringIO()))
g.subprocess.Popen, g.fresh_unread = saved_popen, saved_fresh
del _os.environ["CT_IN_WORKTREE"], _os.environ["CT_MAIN_CHECKOUT"]
first = fa.input_hash(d)
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES)
check("an inbox unchanged leaves the edition's inputs alone", first, fa.input_hash(d))
# A code change re-reads every file, MATCH_SECONDS at a time: past the
# budget a file keeps its last match, so no edition goes, and a lay-out a
# killed tick left half done is cleared.
saved_matcher, saved_match = g.MATCHER, g.match
g.MATCHER = "changed"
def no_match(*a, **k):
    raise AssertionError("matched past the budget")
g.match = no_match
(d.parent / (d.name + ".new")).mkdir()
log = io.StringIO()
g.stage(inbox, cache, log, un, g.MATCHES, seconds=-1)
check("past the budget: nothing re-read, the edition kept, the half lay-out gone, the rest said",
      (True, False, True), (d.exists(), (d.parent / (d.name + ".new")).exists(), "left to match next tick" in log.getvalue()))
g.match = saved_match
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES)
check("within it, every file re-read under the new code and kept", True,
      all(k.startswith("changed\t") for k in json.loads(g.MATCHES.read_text())))
g.MATCHER = saved_matcher
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES)
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

# The checklist: progress, what was sorted, the next editions with what to
# search for, then each year, the worst first.
g.usual_pages = lambda: {1988: (16, 24, 18)}
rows = [(D(1987, 3, 2), "no-scan"), (D(1988, 1, 12), "no-scan"), (D(1988, 1, 13), "no-scan"),
        (D(1988, 1, 14), "no-scan")]
LOG = Path(sys.argv[1]) / "set_aside.json"
html = g.checklist(rows, cache, un, docs={"TTDA/1988-01-13": {"doc": "IF0502610073", "title": "Crossword", "page": 18, "records": ["IF0502610073"]}}, log=LOG)
check("the worst year first", True, html.index("<b>1988</b>: 3 missing") < html.index("<b>1987</b>: 1 missing"))
check("progress counts the files downloaded (2 for one date and 1 naming none) against those and the editions to go",
      True, '<b id="count">3 of 6</b> files downloaded, <span id="togo">3</span> to go' in html)
nxt = html[html.index("<h2>Next up"):html.index("<h2>Everything")]
check("next up starts at the worst year's first edition not arrived", True,
      nxt.index("Wed 13 Jan 1988") < nxt.index("Thu 14 Jan 1988") < nxt.index("Mon 02 Mar 1987"))
check("an arrived edition is not next up", False, "Tue 12 Jan 1988" in nxt)
check("a search to copy for the puzzle's number", True,
      """onclick="cp(this,&quot;\\&quot;Crossword Puzzle No 17,564\\&quot;&quot;)">Copy</button>""" in nxt)
check("the ordering rule is said", True, g.ORDER in nxt)
check("next up is a pool that refills itself: no Next batch, a Clicked list under it, Refresh", (True, False, True, True),
      ('<table id="next">' in nxt, "nextBatch" in html or "Next batch" in html,
       '<div id="clicked" hidden><h3>Clicked</h3>' in nxt and '<table id="done">' in nxt, 'onclick="location.reload()"' in nxt))
check("each next-up row carries its place in the pool, so a row unclicked goes back where it was", True,
      all(f'data-i="{i}"' in nxt for i in range(3)))
check("a clicked row moves to Clicked after MOVE_SECONDS; mark() re-shows then", True,
      "MOVE=3*1e3" in html and "setTimeout(show,MOVE+50)" in html and "(gone?dn:nx).tBodies[0].appendChild(r)" in html)
import subprocess, shutil as _sh
if _sh.which("node"):
    js = html[html.index("<script>") + 8:html.index("</script>")]
    (Path(sys.argv[1]) / "page.js").write_text(js)
    check("the page's script parses", 0, subprocess.run(["node", "--check", str(Path(sys.argv[1]) / "page.js")]).returncode)
check("no download-limit text", False, "downloads a session" in html)
check("the pool is POOL long; links are looked up for every wanted edition", ([D(1988, 1, 13)], 60, None),
      ([d for d, _ in g.next_up(rows, {D(1988, 1, 12): []}, 1)], g.POOL, g.LOOKAHEAD))
check("each row to fetch has a state badge the script fills", True, '<span class="st"></span>' in nxt)
check("which says downloading, then late, then in the inbox", True,
      all(w in html for w in ("downloading&hellip; clicked", 'not arrived: <a class="retry"', "&#10003; in the inbox")))
check("an estimated number says so", True, "number estimated" in nxt[nxt.index("Mon 02 Mar 1987"):])
check("a date's likely page", True, "p. 18 (or 16-24)" in nxt)
check("an arrived edition is marked", True, "arrived (1988-01-12 page 2.png, GALE|IF0503151598 1988-01-12.jpg)" in html)
text = html[html.index("</script>"):]
check("no box asks anything of Paul", (False, False, False), ("Check these files" in text, "Rename it" in text,
                                                               "delete" in text.lower()))
note = html[html.index('<details class="notes">'):html.index('<div class="how">')]
check("a file that names no edition is a note: left in the inbox", True,
      "holiday snap.jpg" in note and "left in the inbox" in note and "nothing to do" in note)
check("the page reads its status file, no blind refresh", (True, False),
      ('SRC="Checklist.status.js"' in html, 'http-equiv="refresh"' in html))
arrived = next(r for r in html.split("\n") if 'data-k="1988-01-12"' in r)
check("an arrived row says so and offers no Download", (True, True, False, False),
      ('data-in="1"' in arrived, "in the inbox" in arrived, 'class="dl"' in arrived, "Open in Gale" in arrived))
check("Download is a big button", True, all(w in g.CSS for w in ("a.dl{display:inline-block;padding:8px 18px;font-size:17px",)))
# A page saved for a date, read, holding no cryptic's title: back to fetch
# unless Gale's citation names it the cryptic (a reader miss: it counts).
rel88 = "GaleTimes1988UKEnglish/1988-01-12"
scanned = {rel88: {"edition": rel88, "scan": {"puzzles": [], "solutions": []}, "filesHash": fa.input_hash(d),
                  "scanKey": fa.scan_key()}}
html2 = g.checklist(rows, cache, un, ledger=scanned, log=LOG)
nxt2 = html2[html2.index("<h2>Next up"):html2.index("<h2>Everything")]
check("a page with no cryptic's title: its edition next up again and to go, nothing asked",
      (True, True, False), ("Tue 12 Jan 1988" in nxt2, "<b id=\"count\">3 of 7</b>" in html2, "Check these" in html2))
check("(mirror) a scan of other files, by older code, or one that failed, is no reading of these", ({}, {}, {}),
      (g.titleless(g.staged_matches(cache), {rel88: {**scanned[rel88], "filesHash": "old"}}, cache),
       g.titleless(g.staged_matches(cache), {rel88: {**scanned[rel88], "scanKey": "old"}}, cache),
       g.titleless(g.staged_matches(cache), {rel88: {**scanned[rel88], "scan": {"puzzles": [], "failed": "Timeout"}}},
                   cache)))
html2 = g.checklist(rows, cache, un, ledger={k: {**v, "scan": {"puzzles": [{"number": 17564}], "solutions": []}}
                                             for k, v in scanned.items()}, log=LOG)
check("(mirror) one with a title is not", False,
      "Tue 12 Jan 1988" in html2[html2.index("<h2>Next up"):html2.index("<h2>Everything")])
src88 = next(d.glob("sources-*.json"))
kept_src = src88.read_text()
src88.write_text(json.dumps([{**m, "cited": "The Times Crossword Puzzle No 17,563"} for m in json.loads(kept_src)]))
scanned[rel88]["filesHash"] = fa.input_hash(d)
html2 = g.checklist(rows, cache, un, ledger=scanned, log=LOG)
check("titleless but cited as the cryptic: arrived, a note says our readers missed it", (False, True, True),
      ("Tue 12 Jan 1988" in html2[html2.index("<h2>Next up"):html2.index("<h2>Everything")],
       "<b id=\"count\">3 of 6</b>" in html2, "our readers read no title on it yet" in html2))
src88.write_text(kept_src)
scanned[rel88]["filesHash"] = fa.input_hash(d)

# Sorting files out: each class set aside with its reason, nothing asked.
M = lambda f, **k: {"file": f, "grid": True, "cited": None, **k}
cryptic, concise = "The Times Crossword Puzzle No 17,275", "Concise Crossword No 1154"
staged = {D(1988, 1, 13): [M("IF0502610073.pdf", cited=cryptic), M("IF0502610073 (1).pdf", cited=cryptic),
                           M("IF0502610073 (2).pdf", cited=cryptic)],
          D(1988, 1, 14): [M("IF0501710448.pdf", cited=concise)],
          D(1988, 2, 1): [M("IF0500000001.pdf")],
          D(1987, 6, 30): [M("IF0500000002.pdf")],
          D(1987, 3, 2): [M("IF0500000003.pdf", grid=False)],
          D(1988, 1, 12): [M("IF0500000004.pdf"), M("IF0500000005.pdf", cited=cryptic, grid=False)]}
plan = {f: why for f, _, why in g.to_set_aside(staged, rows, {17396: D(1987, 6, 30)}, {D(1988, 1, 12): []})}
check("second copies of one Gale document go, the first kept",
      ["IF0502610073 (1).pdf", "IF0502610073 (2).pdf"], sorted(f for f, w in plan.items() if "second copy" in w))
check("a page Gale's citation names as another puzzle goes", True, "Concise Crossword No 1154" in plan["IF0501710448.pdf"])
check("a page for a date the list does not ask for goes; one already filed stays", (True, False),
      ("does not ask for" in plan.get("IF0500000001.pdf", ""), "IF0500000002.pdf" in plan))
check("a page with no grid goes", "no crossword grid on it", plan.get("IF0500000003.pdf"))
check("a titleless page goes; Gale's cryptic page stays, grid or title read or not", (True, False),
      ("no Times Crossword title" in plan.get("IF0500000004.pdf", ""), "IF0500000005.pdf" in plan))
check("the cryptic's copy is the one kept", False, "IF0502610073.pdf" in plan)
check("a file matched before citations were read is not judged by grid or title yet", [],
      g.to_set_aside({D(1987, 3, 2): [{"file": "old.pdf", "grid": False}]}, rows, {}, {D(1987, 3, 2): []}))
ran = []
n = g.set_aside(g.to_set_aside(staged, rows, {17396: D(1987, 6, 30)}, {}), io.StringIO(), "/inbox", LOG, ran.append)
check("set_aside moves them on the Mac into the inbox's Set aside folder, never over a file there",
      (True, True, n), (ran[0].startswith("mkdir -p '/inbox/Set aside' && mv -n "), "'/inbox/Set aside/'" in ran[0],
                        ran[0].count(" mv -n ")))
check("and nothing when there is nothing to move", (0, 1), (g.set_aside([], io.StringIO(), "/inbox", LOG, ran.append), len(ran)))
log = json.loads(LOG.read_text())
check("each is logged with its date and why", ("1988-01-14", True),
      (log["IF0501710448.pdf"]["date"], "Concise" in log["IF0501710448.pdf"]["why"]))
docs = {"TTDA/1988-01-14": {"why": "no crossword in the issue's contents"}, "TTDA/1988-01-13": {"why": "no crossword in the issue's contents"},
        "TTDA/1987-03-02": {"why": "Gale has no issue that day"}}
aside = g.aside_days(LOG)
check("Gale has no cryptic: no issue, or no crossword listed and the page found another puzzle; else still to fetch",
      (True, True, None), (bool(g.not_on_gale(D(1988, 1, 14), docs, aside)), bool(g.not_on_gale(D(1987, 3, 2), docs, aside)),
                           g.not_on_gale(D(1988, 1, 13), docs, aside)))
html3 = g.checklist(rows, cache, un, docs=docs, log=LOG)
nxt3 = html3[html3.index("<h2>Next up"):html3.index("<h2>Everything")]
check("such a date leaves next up, its year row saying why", (False, True),
      ("Thu 14 Jan 1988" in nxt3, "contents list no cryptic that day" in html3))
check("the files set aside are notes, not asks", (True, False),
      ("set aside into Set aside" in html3, "Check these" in html3))
check("a note older than ASIDE_DAYS is dropped", [], [f for f, w in g.notes({}, {}, Path("/nonexistent"), LOG,
      datetime.datetime.now().astimezone() + datetime.timedelta(days=g.ASIDE_DAYS + 1)) if "set aside" in w])
check("the citation's title is read off a Gale download's text", "Concise Crossword No 1154",
      g.CITED_TITLE.search('"Concise Crossword No 1154." Times, 13 Jan. 1987, p. 10.').group(1))
check("only the cryptic's title is the cryptic", (True, False, False),
      (g.cryptic_cited({"cited": cryptic}), g.cryptic_cited({"cited": concise}), g.cryptic_cited({})))
status = {}
g.checklist(rows, cache, un, status=status, log=Path("/nonexistent"))
check("a render's status names the page and its arrived rows", (True, ["1988-01-12"]),
      (status["page"] > 0, status["in"]))
check("and the count, which the page's poll writes into its progress bar and number", ((3, 6), True),
      ((status["done"], status["total"]), all(w in html for w in ('<progress id="prog"', '<b id="count">',
                                                                    'galeStatus(s){IN=new Set(s.in);AT=s.at*1000;BASE=s'))))
published = []
g.publish = lambda path, host_inbox=None, polled=False: published.append((path.name, polled))
page_path = Path(sys.argv[1]) / "Checklist.html"
g.publish_status(page_path, status)
g.publish_status(page_path)
js = (Path(sys.argv[1]) / "Checklist.status.js").read_text()
check("the status file is a script call, kept between renders, published each tick",
      (True, ["1988-01-12"], [("Checklist.status.js", True)] * 2),
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
        "&searchResultsType=SingleTab&prodId=TTDA&userGroupName=alberta_portal&u=alberta_portal&p=TTDA")
check("a date's link is Gale's title search on that day, month and day zero-padded", want,
      g.search_url(D(1988, 1, 13)))
row13 = nxt[nxt.index("13 Jan 1988"):nxt.index("14 Jan 1988")]
check("each next-up row keeps its Gale link beside Copy: the permalink of a known document, after its Download", True,
      bool(re.search(r'class="dl"[^>]*>Download</a><a class="go" href="https://link\.gale\.com/apps/doc/IF\d+/TTDA[^"]*" '
                     r'target="gale">Open in Gale</a> <button onclick="cp\(', row13)))
check("a row whose document is known opens Gale's permalink for it, as its citation prints; else the search",
      ("https://link.gale.com/apps/doc/IF0500470778/TTDA?u=alberta_portal&sid=bookmark-TTDA", None),
      (g.gale_docs.permalink("TTDA", D(1987, 1, 19), {"TTDA/1987-01-19": {"doc": "IF0500470778"}}),
       g.gale_docs.permalink("TTDA", D(1987, 1, 13), {"TTDA/1987-01-13": {"why": "no crossword"}})))
check("the Listener's link searches its own archive", True, "prodId=LSNR" in g.search_url(D(1930, 4, 9), "LSNR"))
check("no link fetches a document or names a session id", [], [u for u in re.findall(r'href="([^"]+)"', html)
      if "retrieve.do" in u or "PHPSESSID" in u or "jsessionid" in u.lower()])

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
# Its document, so a puzzle filed off it names the page at Gale (and its
# provenance says so: an OCR'd newspaper page, which annotation can ask to
# have read again), off its citation's permalink or Gale's own file name.
check("its document is named by its citation's permalink, renamed or not", ["IF0500004465"] * 2,
      [g.match(gale, held)["docId"], g.match(gale.rename(gale.with_name("times page.pdf")), held)["docId"]])
gale = gale.with_name("times page.pdf").rename(gale)
bare = Path(sys.argv[1]) / "IF0500254930 (1).png"
Image.new("RGB", (400, 300), "white").save(bare)
check("and by Gale's bare download name, a second copy's too", "IF0500254930", g.match(bare, held)["docId"])
bare.unlink()
import provenance
check("a Times puzzle filed off a Gale page, by its document or the portal, is an OCR'd newspaper page "
      "filed by the archive filer", [("newspaper", fa.TOOL)] * 2,
      [(s_["retrievedFrom"], s_["acquiredBy"]) for s_ in
       (provenance.derive({"id": "times-17246", "number": 17246, "source": {"url": u}}, fa.TOOL, None)["source"]
        for u in (g.DOC_URL.format("IF0500004465"), g.PORTAL))])

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
# A Listener puzzle still to save whose document is known gets a Download in
# next up, ahead of an earlier one Gale has no link for; the Times the same.
import gale_listener as gl
idx = [{"date": D(1930, 4, 2), "number": 1, "title": "A Musical Crossword", "setter": ""},
       {"date": D(1930, 4, 9), "number": 2, "title": "A Scientific Crossword", "setter": ""}]
known = {"doc": "GM2500000001", "title": "A Scientific Crossword", "page": 7, "records": ["R1"]}
lpage = gl.checklist(idx, Path(sys.argv[1]) / "nostore", Path(sys.argv[1]) / "norepo", arrivals=[],
                     docs={"LSNR/1930-04-09": known})
lnext = re.findall(r"<tr data-k.*?</tr>", lpage.split('<table id="next">')[1].split("</table>")[0], re.S)
check("a Listener next-up row with a known document has a Download, first", (2, ["p2", True, False]),
      (len(lnext), [re.search(r'data-k="([^"]*)"', lnext[0]).group(1), 'class="dl"' in lnext[0], 'class="dl"' in lnext[1]]))
g.held, g.usual_pages, g.archive_coverage.ledger = (lambda: {}), (lambda: {}), (lambda: {})
tpage = g.checklist([(D(1988, 1, 12), "no-scan"), (D(1988, 1, 13), "no-scan")], Path(sys.argv[1]) / "nocache",
                    Path(sys.argv[1]) / "none.json", docs={"TTDA/1988-01-13": dict(known, title="Crossword")},
                    log=Path(sys.argv[1]) / "aside.log")
tnext = re.findall(r"<tr data-k.*?</tr>", tpage.split('<table id="next">')[1].split("</table>")[0], re.S)
check("a Times one the same", ["1988-01-13", True, False],
      [re.search(r'data-k="([^"]*)"', tnext[0]).group(1), 'class="dl"' in tnext[0], 'class="dl"' in tnext[1]])
# The Mac's arrival watcher (tools/gale_arrived.py): a file named for a
# row's document marks that row downloaded within seconds, no sync; any
# other file changes nothing.
import gale_arrived as ga, plistlib, time as _t
drop, arr = Path(sys.argv[1]) / "chrome", Path(sys.argv[1]) / "Arrived.js"
drop.mkdir()
(drop / "holiday.pdf").write_bytes(b"x")
(drop / "GM2500000001.crdownload").write_bytes(b"x")
check("an unknown file, or one still downloading, marks nothing", ([], {}), (ga.scan([drop], arr), ga.read(arr)))
(drop / "GM2500000001 (2).pdf").write_bytes(b"x")
check("a file named for a known document marks it arrived without a sync", (["GM2500000001"], ["GM2500000001"]),
      ([d for d, _, _ in ga.scan([drop, Path(sys.argv[1]) / "missing"], arr)], list(ga.read(arr))))
check("as a script call the page loads", True, arr.read_text().startswith("galeArrived("))
_before = arr.stat().st_mtime_ns
(drop / "notes.pdf").write_bytes(b"x")
check("a later unknown file leaves the arrivals file untouched", ([], _before), (ga.scan([drop], arr), arr.stat().st_mtime_ns))
_ino = arr.stat().st_ino
(drop / "GM2500000001 (2).pdf").unlink()
ga.scan([drop], arr)
check("the arrivals file is rewritten in place, never renamed over (Windows reads it through a cached SMB handle)",
      _ino, arr.stat().st_ino)
check("the mark outlives the sync's sweep of the file, and goes after KEEP", (["GM2500000001"], {}),
      (list(ga.read(arr)), (ga.scan([drop], arr, now=_t.time() + ga.KEEP + 1), ga.read(arr))[1]))
(drop / "IF0500375892.pdf").write_bytes(b"x")
check("a file older than KEEP is not marked", [], ga.scan([drop], Path(sys.argv[1]) / "old.js", now=_t.time() + ga.KEEP + 1))
check("a row carries the documents its links name", (True, []),
      ('data-doc="GM2500000001"' in tnext[0], g.row_docs({"dl": None, "search": g.search_url(D(1988, 1, 12))})))
check("the page loads the watcher's file with its status, every 5 s", (True, True, 5),
      ('ASRC="Arrived.js"' in tpage, "function poll(){load(SRC);load(ASRC)}" in tpage, g.POLL_SECONDS))
if _sh.which("node"):
    # The page's own script on a stub DOM: the row whose document arrived
    # says so and is counted at once; the other is untouched.
    (Path(sys.argv[1]) / "rows.js").write_text("""
const el=()=>({dataset:{},classList:{toggle(){}},querySelector(){return null},textContent:'',hidden:false});
const row=(k,doc)=>{const b=el();b.dataset={};const r=el();r.dataset={k,doc};r.badge=b;
  r.querySelector=q=>q==='.st'?b:null;return r};
const rows=[row('1988-01-13','GM2500000001'),row('1988-01-12','')],ids={count:el(),prog:el(),togo:el()};
globalThis.document={querySelectorAll:q=>q==='tr[data-k]'?rows:[],getElementById:i=>ids[i]||null,head:{appendChild(){}},
  createElement:()=>({remove(){}})};
const store={};globalThis.localStorage={getItem:k=>store[k]??null,setItem:(k,v)=>{store[k]=v}};
globalThis.sessionStorage=localStorage;globalThis.addEventListener=()=>{};globalThis.setInterval=()=>{};
globalThis.location={reload(){}};
""" + tpage[tpage.index("<script>") + 8:tpage.index("</script>")] + """
galeStatus({page:0,at:Date.now()/1000,in:[],done:3,total:6});
galeArrived({GM2500000001:1});
console.log(JSON.stringify([rows.map(r=>r.dataset.s),rows[0].badge.innerHTML,ids.count.textContent]));
""")
    _r = subprocess.run(["node", str(Path(sys.argv[1]) / "rows.js")], capture_output=True, text=True)
    check("on the page, the arrived row says downloaded and the count moves",
          [["got", ""], "&#10003; downloaded, checking&hellip;", "4 of 6"], json.loads(_r.stdout or "null") or _r.stderr)
_calls, _st = [], Path(sys.argv[1]) / "watcher.sha"
_run = lambda c, input=None: _calls.append(c)
check("the sync installs the watcher once, then leaves it until it changes", (True, False, 2),
      (g.install_watcher(io.StringIO(), _run, _st), g.install_watcher(io.StringIO(), _run, _st), len(_calls)))
_job = plistlib.loads(ga.plist(g.WATCHER_PYTHON, g.WATCHER, g.WATCHED, "/x/Arrived.js", g.WATCHER_LOG).encode())
check("its job watches the download folders and runs the installed script on them",
      (ga.LABEL, list(g.WATCHED), [g.WATCHER_PYTHON, g.WATCHER, "--out", "/x/Arrived.js", *g.WATCHED]),
      (_job["Label"], _job["WatchPaths"], _job["ProgramArguments"]))
stamp = Path(sys.argv[1]) / "looked_up"
check("Gale is asked at most every LOOKUP_EVERY, however often the tick runs", [True, False, False, True],
      [g.gale_due(t, stamp) for t in (1000, 1060, 1120, 1000 + g.LOOKUP_EVERY)])
g.LOCK = Path(sys.argv[1]) / "sync.lock"
with g.locked():
    buf = io.StringIO()
    g.sync(out=buf)
check("a sync while another holds the lock skips at once, not waits", "another sync holds the lock; this one skips\n",
      buf.getvalue())
# Each paper has its own lookup allowance: the Times using all of its leaves
# the Listener a full one.
import gale_listener as gl2, time as _time
clock, asked, published = [0.0], {}, []
def fake_resolve(prod, rows, out=None, **kw):
    asked[prod] = kw["until"] - clock[0]
    if prod == "TTDA":
        clock[0] += g.GALE_SECONDS
real = (_time.monotonic, g.collect, g.mirror, g.gale_due, g.held, g.number_on, g.next_up, g.wanted, g.staged_files,
        g.last_render, g.publish_status, g.start_reads, g.gale_docs.resolve, gl2.tick, g.LOCK)
_time.monotonic = lambda: clock[0]
g.collect = g.mirror = lambda *a, **k: False
g.gale_due, g.held, g.number_on, g.next_up = (lambda: True), (lambda: {}), (lambda d, b: (None,)), (lambda *a: [])
g.wanted, g.staged_files, g.last_render, g.publish_status, g.start_reads = (lambda: {}), (lambda: []), (lambda: _time.time() + 10**9), (lambda *a: published.append((a[0].name, clock[0]))), (lambda *a: None)
g.gale_docs.resolve = fake_resolve
gl2.tick = lambda out, force, ask, until, changed: asked.update(LSNR=until - clock[0])
g.LOCK = Path(sys.argv[1]) / "sync2.lock"
g.sync(out=io.StringIO())
(_time.monotonic, g.collect, g.mirror, g.gale_due, g.held, g.number_on, g.next_up, g.wanted, g.staged_files,
 g.last_render, g.publish_status, g.start_reads, g.gale_docs.resolve, gl2.tick, g.LOCK) = real
check("the Listener gets a full allowance when the Times used all of its own", [g.GALE_SECONDS, g.GALE_SECONDS],
      [asked["TTDA"], asked["LSNR"]])
check("both pages' status files are published before any Gale lookup",
      [(g.CHECKLIST.name, 0.0), (gl2.CHECKLIST.name, 0.0)], published[:2])
check("an open page calls the status dead only after a sync's longest gap between publishes",
      True, g.STALE_SECONDS > 2 * g.GALE_SECONDS)
print("FAILS", fails)
sys.exit(1 if fails else 0)
PY
