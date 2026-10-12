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
# Nothing here may reach the Mac; CI has none.
def _no_mac(command, **kw):
    raise AssertionError(f"the test ran ssh on the Mac: {command[:80]}")
g.ssh = _no_mac
# Nor read the live mirror and its matches (~/.cache).
g.MIRROR, g.MATCHES = Path(sys.argv[1]) / "mirror", Path(sys.argv[1]) / "matches.json"
g.DIR_CACHE = Path(sys.argv[1]) / "dir_cache.pickle"

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

# Every year Gale holds (1930-2019): dates and numbers in names of the
# 1950s and the 2000s; No 5,432 only after "No" (a bare 4 digits may be a year).
for name, want in [("The Times 12 Jan. 1955.pdf", D(1955, 1, 12)), ("2005-03-14 crossword.pdf", D(2005, 3, 14)),
                   ("19350102 p5.jpg", D(1935, 1, 2)), ("Times 1929-12-31.pdf", None), ("2020-01-02.pdf", None)]:
    check(f"the date in {name!r}", want, g.name_date(name))
for name, want in [("Times Crossword Puzzle No 5,432.pdf", 5432), ("No_543.pdf", 543), ("crossword 1955.pdf", None),
                   ("piano 123.pdf", None), ("No. 23,456 Times.pdf", 23456)]:
    check(f"the puzzle number in {name!r}", want, g.name_number(name))
check("the printed run spans every year Gale holds, into the January after (filed brackets)", (D(1930, 2, 1), D(2020, 1, 31)), (g.PRINTED[0], g.PRINTED[-1]))
# A date in a 43-year gap: the two brackets' counts disagree (holidays the
# calendar does not skip), so the difference is shared out by position.
gap = {1: D(1930, 2, 1), 13578: D(1974, 1, 5)}
lo_up = 1 + g.ISSUE[D(1952, 1, 2)] - g.ISSUE[D(1930, 2, 1)]
n52, sure52 = g.number_on(D(1952, 1, 2), gap)
check("a date deep in a gap gets a number between the brackets' counts, an estimate", (True, False),
      (13578 - (g.ISSUE[D(1974, 1, 5)] - g.ISSUE[D(1952, 1, 2)]) <= n52 <= lo_up, sure52))
check("a number in such a gap gets no date", None, g.day_of(7000, gap))
# next_up: No 1 first, the rows the list held before it was widened (1974-99,
# no scan) in their old order, then 2014-19, 2000-13, the rest, newest first.
wide = [(D(1955, 3, 1), "no-scan"), (D(1930, 2, 1), g.SCAN_UNFILED), (D(2005, 6, 1), "no-scan"),
        (D(2016, 5, 2), "no-scan"), (D(1988, 1, 13), "no-scan"), (D(1987, 3, 2), "no-scan"),
        (D(1988, 1, 12), "no-scan"), (D(1985, 2, 1), g.SCAN_UNFILED), (D(2015, 1, 5), "no-scan"),
        (D(2010, 1, 4), "no-scan"), (D(1962, 1, 2), "no-scan")]
check("next_up: No 1, the old list in its order, 2014-19, 2000-13, then the rest, newest first",
      [D(1930, 2, 1), D(1988, 1, 12), D(1988, 1, 13), D(1987, 3, 2), D(2016, 5, 2), D(2015, 1, 5), D(2010, 1, 4),
       D(2005, 6, 1), D(1985, 2, 1), D(1962, 1, 2), D(1955, 3, 1)], [d for d, _ in g.next_up(wide, (), None)])

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
# A fresh download is matched before the files a code change re-reads.
g.MATCHER, order = "again", []
def recorded(path, by_number):
    order.append(path.name)
    return saved_match(path, by_number)
g.match = recorded
Image.new("RGB", (400, 300), "white").save(inbox / "1999-12-31 page 1.png")
Image.new("RGB", (400, 300), "white").save(inbox / "1999-12-30 page 1.png")
import os as _os
_os.utime(inbox / "1999-12-31 page 1.png", (1e9, 1e9))
check("unread: the files no match has read, the oldest download first, so a tick stages them",
      ["1999-12-31 page 1.png", "1999-12-30 page 1.png"], [p.name for p in g.unread(inbox, g.MATCHES)])
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES)
check("never-matched files go first, the oldest download first, not by name",
      ["1999-12-31 page 1.png", "1999-12-30 page 1.png"], order[:2])
check("(mirror) and once matched they are not unread", [], g.unread(inbox, g.MATCHES))
(inbox / "1999-12-31 page 1.png").unlink()
(inbox / "1999-12-30 page 1.png").unlink()
# The budget starts once the desktop's session is up: a slow connect
# (waiting behind other processes' code ships) spends none of it.
import time as _tm
connects = []
g.desktop_ready = lambda: (connects.append(1), _tm.sleep(0.3))
Image.new("RGB", (400, 300), "white").save(inbox / "1999-12-29 page 1.png")
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES, seconds=0.2)
check("a connect longer than the budget still leaves the budget for matching", (1, "1999-12-29 page 1.png"),
      (len(connects), order[-1]))
(inbox / "1999-12-29 page 1.png").unlink()
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES, seconds=0.2)
check("(mirror) with nothing to match, no connect", 1, len(connects))
g.match = saved_match
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

# The Times progress page: nothing to click (tools/gale_fetch.py downloads
# every row), each count, the latest downloads and Gale's refusals.
g.usual_pages = lambda: {1988: (16, 24, 18)}
rows = [(D(1987, 3, 2), "no-scan"), (D(1988, 1, 12), "no-scan"), (D(1988, 1, 13), "no-scan"),
        (D(1988, 1, 14), "no-scan")]
LOG = Path(sys.argv[1]) / "set_aside.json"
FETCHED = Path(sys.argv[1]) / "fetched.json"
FETCHED.write_text(json.dumps({"IF0502610073": {"date": "1988-01-13", "file": "GALE_IF0502610073.pdf",
                                                "at": datetime.datetime.now().astimezone().isoformat()}}))
LIMITS = Path(sys.argv[1]) / "limits.json"
LIMITS.write_text(json.dumps({"refusals": [{"at": "2026-10-11T15:00:00-06:00", "in_window": 480}],
                              "recoveries": [{"waited": 1800}]}))
html = g.checklist(rows, cache, un, docs={}, ledger={}, log=LOG, fetched=FETCHED, limits=LIMITS)
check("nothing to click: no Download, no script, no instructions; it reloads itself", (False, False, False, True),
      ('class="dl"' in html, "<script>" in html, 'id="instructions"' in html, 'http-equiv="refresh"' in html))
check("its counts: wanted, to fetch, waiting to be read", (True, True, True),
      ("<th>Wanted (no puzzle filed)</th><td>4</td>" in html, "<th>Still to fetch</th><td>3</td>" in html,
       "<th>Fetched, waiting to be read</th><td>1</td>" in html))
check("the script's downloads and Gale's refusals", (True, True, True),
      ("<td>1 (1 today)</td>" in html, "after 480 in its window" in html, "worked again after 30 min" in html))
check("the years in next_up's order, the worst first", True, html.index("<td>1988</td>") < html.index("<td>1987</td>"))
note = html[html.index('<details class="notes">'):]
check("a hand file that names no edition is a note: left in the inbox", True,
      "holiday snap.jpg" in note and "left in the inbox" in note and "nothing to do" in note)
rel88 = "GaleTimes1988UKEnglish/1988-01-12"
scanned = {rel88: {"edition": rel88, "scan": {"puzzles": [], "solutions": []}, "filesHash": fa.input_hash(d),
                  "scanKey": fa.scan_key()}}
check("(mirror) a scan of other files, by older code, or one that failed, is no reading of these", ({}, {}, {}),
      (g.titleless(g.staged_matches(cache), {rel88: {**scanned[rel88], "filesHash": "old"}}, cache),
       g.titleless(g.staged_matches(cache), {rel88: {**scanned[rel88], "scanKey": "old"}}, cache),
       g.titleless(g.staged_matches(cache), {rel88: {**scanned[rel88], "scan": {"puzzles": [], "failed": "Timeout"}}},
                   cache)))
html2 = g.checklist(rows, cache, un, docs={}, ledger=scanned, log=LOG, fetched=FETCHED, limits=LIMITS)
check("a read edition counts as read, not waiting", (True, True),
      ("<th>Read, no puzzle filed from it</th><td>1</td>" in html2, "<th>Fetched, waiting to be read</th><td>0</td>" in html2))

# A page tools/gale_fetch.py downloaded is laid out as its date's edition
# straight away, matched by nothing, and stage leaves it alone.
import PIL.Image, shutil, subprocess, shutil as _sh
_pdf = io.BytesIO()
PIL.Image.new("RGB", (1200, 1600), "white").save(_pdf, format="PDF")
fd = g.lay_out_fetched(D(1988, 1, 14), "IF0501710449", _pdf.getvalue(),
                       {"doc": "IF0501710449", "title": "The Times Crossword Puzzle No 17,565.", "page": 18}, cache)
_src = json.loads(next(fd.glob("sources-*.json")).read_text())
check("a fetched page is its date's edition, its match what the download knew", (True, "fetched", "IF0501710449",
      "The Times Crossword Puzzle No 17,565", True),
      ((fd / "leaf_0000.jpg").exists(), _src[0]["how"], _src[0]["docId"], _src[0]["cited"],
       g.cryptic_cited(_src[0])))
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES)
check("stage leaves a fetched edition alone: not removed though no inbox file holds it", True, fd.exists())
check("and it counts as staged", True, D(1988, 1, 14) in g.staged_files(cache))
_sib = inbox / "1988-01-14.jpg"
PIL.Image.new("RGB", (800, 1000), "white").save(_sib)
_out = io.StringIO()
g.stage(inbox, cache, _out, un, g.MATCHES)
check("a hand file for a fetched date does not replace it", (True, True),
      (json.loads(next(fd.glob("sources-*.json")).read_text())[0]["how"] == "fetched", "second copy" in _out.getvalue()))
_sib.unlink()
g.stage(inbox, cache, io.StringIO(), un, g.MATCHES)
shutil.rmtree(fd)

# Another paper's fetched page is laid out under its own item, its link
# that archive's, and leaves that paper's wanted list.
_e = {"doc": "IO0700000001", "title": "No. 12,212 across", "page": 14}
check("an OTHERS paper's date is wanted until laid out", True, D(1965, 3, 2) in g.other_wanted("TGRH", cache))
od = g.lay_out_fetched(D(1965, 3, 2), "IO0700000001", _pdf.getvalue(), _e, cache, prod="TGRH")
check("laid out under the paper's own item, with its archive's link", (cache / "GaleTelegraph1965UKEnglish" / "1965-03-02",
      "GaleTelegraph1965UKEnglish", True), (od, json.loads((od / "pages.json").read_text())["item"],
                                           "/TGRH?" in json.loads((od / "pages.json").read_text())["url"]))
check("and no longer wanted", False, D(1965, 3, 2) in g.other_wanted("TGRH", cache))
check("no Times edition", False, D(1965, 3, 2) in g.staged_files(cache))
shutil.rmtree(od.parent)

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
      (True, True, n), (ran[0].startswith("mkdir -p '/inbox/Set aside' && { [ ! -e "), "'/inbox/Set aside/'" in ran[0],
                        ran[0].count(" mv -n ")))
check("a move tolerates a source already gone", True, "[ ! -e /inbox/IF0501710448.pdf ] || mv -n" in ran[0])
ran2 = []
check("a file already in the set-aside log is not moved-and-logged again", 0,
      g.set_aside([("IF0501710448.pdf", D(1988, 1, 14), "again")], io.StringIO(), "/inbox", LOG, ran2.append))
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
html3 = g.checklist(rows, cache, un, docs=docs, ledger={}, log=LOG, fetched=FETCHED, limits=LIMITS)
check("such a date counts as not on Gale, not to fetch", True, "<th>Not on Gale</th><td>2</td>" in html3)
check("the files set aside are notes, not asks", (True, False),
      ("set aside into Set aside" in html3, "Check these" in html3))
check("a note older than ASIDE_DAYS is dropped", [], [f for f, w in g.notes({}, {}, Path("/nonexistent"), LOG,
      datetime.datetime.now().astimezone() + datetime.timedelta(days=g.ASIDE_DAYS + 1)) if "set aside" in w])
check("the citation's title is read off a Gale download's text", "Concise Crossword No 1154",
      g.CITED_TITLE.search('"Concise Crossword No 1154." Times, 13 Jan. 1987, p. 10.').group(1))
check("only the cryptic's title is the cryptic", (True, False, False),
      (g.cryptic_cited({"cited": cryptic}), g.cryptic_cited({"cited": concise}), g.cryptic_cited({})))
want = ("https://go.gale.com/ps/advancedSearch.do?inputFieldNames%5B0%5D=TI&inputFieldValues%5B0%5D=crossword"
        "&dateIndices=DA&dateLimiterValues%5BDA%5D.dateMode=2&dateLimiterValues%5BDA%5D.fromYear=1988"
        "&dateLimiterValues%5BDA%5D.fromMonth=01&dateLimiterValues%5BDA%5D.fromDay=13"
        "&dateLimiterValues%5BDA%5D.fromEra=1&searchType=AdvancedSearchForm&method=doSearch&searchMethod=advanced"
        "&searchResultsType=SingleTab&prodId=TTDA&userGroupName=alberta_portal&u=alberta_portal&p=TTDA")
check("a date's link is Gale's title search on that day, month and day zero-padded", want,
      g.search_url(D(1988, 1, 13)))
check("a row whose document is known opens Gale's permalink for it, as its citation prints; else the search",
      ("https://link.gale.com/apps/doc/IF0500470778/TTDA?u=alberta_portal&sid=bookmark-TTDA", None),
      (g.gale_docs.permalink("TTDA", D(1987, 1, 19), {"TTDA/1987-01-19": {"doc": "IF0500470778"}}),
       g.gale_docs.permalink("TTDA", D(1987, 1, 13), {"TTDA/1987-01-13": {"why": "no crossword"}})))
check("the Listener's link searches its own archive", True, "prodId=LSNR" in g.search_url(D(1930, 4, 9), "LSNR"))

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
# A compact-era (2004-) page: its grid ~37% of the page wide, too wide to
# be grid-shaped at an archive.org page's width, beside a wider square photo
# (Times 24,662): scaled by the lattice, not the widest square of ink.
compact = Image.new("L", (4600, 6000), 255)
draw = ImageDraw.Draw(compact)
draw.rectangle((100, 600, 2700, 3200), fill=0)  # the photo
draw.ellipse((900, 1200, 1900, 2200), fill=255)  # a face in it
pitch = 113
for i in range(16):  # a 15x15 grid, 1695px wide
    draw.rectangle((2800 + i * pitch, 600, 2808 + i * pitch, 600 + 15 * pitch + 8), fill=0)
    draw.rectangle((2800, 600 + i * pitch, 2800 + 15 * pitch + 8, 608 + i * pitch), fill=0)
for r, c in [(1, 1), (1, 3), (3, 5), (5, 1), (7, 7), (9, 9), (11, 3), (13, 13), (13, 11), (9, 13), (1, 13)]:
    draw.rectangle((2800 + c * pitch, 600 + r * pitch, 2800 + (c + 1) * pitch, 600 + (r + 1) * pitch), fill=0)
grid_box = (2800, 600, 2809 + 15 * pitch, 609 + 15 * pitch)
check("a lattice of white cells is a grid; a photo, however square, is not", (True, False),
      (trove_grid.lattice(compact.crop((2794, 594, grid_box[2] + 6, grid_box[3] + 6))),
       trove_grid.lattice(compact.crop((94, 594, 2706, 3206)))))
page, found = g.scaled(compact.convert("1").convert("RGB"))
check("a compact page is scaled by its grid, not the wider photo beside it", (True, True),
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
# A 1950s and a 2005 download: dated by the citation, whatever the era's
# title says, and the article it names kept.
for docid, cite, want in [
        ("IF0500111111", '"The Times Crossword Puzzle No 8,116." Times, 14 Mar. 1955, p. 9. ', (D(1955, 3, 14), 9)),
        ("IF0500222222", '"Times Crossword No 23,123." Times, 14 Mar. 2005, p. 22. ', (D(2005, 3, 14), 22))]:
    era = Path(sys.argv[1]) / f"{docid}.pdf"
    w = pypdf.PdfWriter()
    w.add_page(pypdf.PdfReader(buf).pages[0])
    w.add_page(pypdf.PdfReader(io.BytesIO(pdf(cite + f"The Times Digital Archive, link.gale.com/apps/doc/{docid}/"))).pages[0])
    w.write(era)
    m = g.match(era, held)
    check(f"a {want[0].year} Gale download is dated by its citation, its title and document kept",
          (want[0], "PDF citation", want[1], cite.split('"')[1].rstrip("."), docid),
          (m["date"], m["how"], m["page"], m["cited"], m["docId"]))
    era.unlink()
check("a 2000s Gale edition is the Gale run's", (fa.GALE, "2005"),
      (fa.paper_of(Path("GaleTimes2005UKEnglish/2005-03-14")), fa.GALE_ITEM.match("GaleTimes2005UKEnglish").group(1)))
import gale_docs as _gd
check("Gale's 2000s TOC: the cryptic, not the Jumbo or Times Two's", 2,
      _gd.crossword("TTDA", ["Times Jumbo Crossword No 512", "Times Two Crossword No 2,001", "Times Crossword No 23,123"]))
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
      ('data-doc="GM2500000001"' in lnext[0], g.row_docs({"dl": None, "search": g.search_url(D(1988, 1, 12))})))
check("the page loads the watcher's file with its status, every 5 s", (True, True, 5),
      ('ASRC="Arrived.js"' in lpage, "function poll(){load(SRC);load(ASRC)}" in lpage, g.POLL_SECONDS))
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
""" + lpage[lpage.index("<script>") + 8:lpage.index("</script>")] + """
galeStatus({page:0,at:Date.now()/1000,in:[],done:3,total:6});
galeArrived({GM2500000001:1});
console.log(JSON.stringify([rows.map(r=>r.dataset.s),rows[0].badge.innerHTML,ids.count.textContent]));
""")
    _r = subprocess.run(["node", str(Path(sys.argv[1]) / "rows.js")], capture_output=True, text=True)
    check("on the page, the arrived row says downloaded and the count moves",
          [["got", ""], "&#10003; DONE: downloaded, checking&hellip;", "4 of 6"], json.loads(_r.stdout or "null") or _r.stderr)
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
# The Times asks Gale for nothing in a tick (tools/gale_fetch.py looks its
# rows up); the Listener gets its full lookup allowance.
import gale_listener as gl2, time as _time
clock, asked, published = [0.0], {}, []
def fake_resolve(prod, rows, out=None, **kw):
    asked[prod] = kw["until"] - clock[0]
    if prod == "TTDA":
        clock[0] += g.GALE_SECONDS
real = (_time.monotonic, g.collect, g.mirror, g.gale_due, g.held, g.number_on, g.next_up, g.wanted, g.staged_files,
        g.last_render, g.publish_status, g.start_reads, g.install_watcher, g.gale_docs.resolve, gl2.tick, g.LOCK)
_time.monotonic = lambda: clock[0]
g.collect = g.mirror = lambda *a, **k: False
g.gale_due, g.held, g.number_on, g.next_up = (lambda: True), (lambda: {}), (lambda d, b: (None,)), (lambda *a: [])
g.wanted, g.staged_files, g.last_render, g.publish_status, g.start_reads = (lambda: {}), (lambda: []), (lambda: _time.time() + 10**9), (lambda *a: published.append((a[0].name, clock[0]))), (lambda *a: None)
g.gale_docs.resolve, g.install_watcher = fake_resolve, (lambda *a: None)
gl2.tick = lambda out, force, ask, until, changed: asked.update(LSNR=until - clock[0])
g.LOCK = Path(sys.argv[1]) / "sync2.lock"
g.sync(out=io.StringIO())
# A tick stages while the inbox holds a file no match has read, nothing else moved.
staged_by, real_stage = [], (g.stage, g.tidy, g.checklist, g.CHECKLIST)
g.stage, g.tidy = (lambda *a, **k: staged_by.append(a)), (lambda out: 0)
g.checklist, g.CHECKLIST, real_publish = (lambda: ""), Path(sys.argv[1]) / "tick" / "Checklist.html", g.publish
g.publish = lambda *a, **k: None
g.sync(out=io.StringIO())
check("(mirror) a tick with nothing moved and nothing unread stages nothing", [], staged_by)
g.MIRROR.mkdir(exist_ok=True)
(g.MIRROR / "IF0500000009.pdf").write_bytes(b"%PDF")
g.sync(out=io.StringIO())
check("a tick whose inbox holds an unread file stages it", 1, len(staged_by))
(g.MIRROR / "IF0500000009.pdf").unlink()
g.stage, g.tidy, g.checklist, g.CHECKLIST = real_stage
g.publish = real_publish
(_time.monotonic, g.collect, g.mirror, g.gale_due, g.held, g.number_on, g.next_up, g.wanted, g.staged_files,
 g.last_render, g.publish_status, g.start_reads, g.install_watcher, g.gale_docs.resolve, gl2.tick, g.LOCK) = real
check("no Times lookup in a tick; the Listener gets its full allowance", (False, g.GALE_SECONDS),
      ("TTDA" in asked, asked["LSNR"]))
check("no Times status file (its page does not poll); the Listener's is published before its lookups",
      [(gl2.CHECKLIST.name, 0.0)], published[:1])
check("an open page calls the status dead only after a sync's longest gap between publishes",
      True, g.STALE_SECONDS > 2 * g.GALE_SECONDS)
# staged_matches reads an unmoved edition dir once, across ticks, and again
# once it moves; while a year dir is unmoved, it is the one stat. Temp cache
# and cache file only.
import os, shutil, time, datetime, dir_cache, archive_coverage
sc = Path(sys.argv[1]) / "staged_cache"
def age(*ds):
    old = time.time() - 3600
    for d in ds:
        os.utime(d, (old, old))
def lay(day, data, key="1"):
    """As stage lays an edition out: built beside it, then swapped in whole."""
    d = sc / g.ITEM.format(day.year) / day.isoformat()
    tmp = d.with_name(d.name + ".new")
    tmp.mkdir(parents=True)
    (tmp / f"sources-{key}.json").write_text(json.dumps(data))
    if d.exists():
        shutil.rmtree(d)
    tmp.rename(d)
    age(d, d.parent)
d1, d2 = datetime.date(1960, 1, 4), datetime.date(1961, 2, 6)
lay(d1, [{"file": "a.pdf"}]); lay(d2, [{"file": "b.pdf"}])
(sc / "GaleTimes1960UKEnglish" / "1960-01-05").mkdir()
# A dir a killed stage left beside its edition is no edition.
(sc / "GaleTimes1960UKEnglish" / "1960-01-06.new").mkdir()
(sc / "GaleTimes1960UKEnglish" / "1960-01-06.new" / "sources-9.json").write_text("[]")
(sc / "other").mkdir()
age(*(sc / "GaleTimes1960UKEnglish").iterdir(), sc / "GaleTimes1960UKEnglish", sc)
dir_cache._SEEN.clear()
want = {d1: [{"file": "a.pdf"}], d2: [{"file": "b.pdf"}]}
check("staged_matches reads each edition's sources, skipping dirs without and a killed stage's .new",
      want, g.staged_matches(sc))
dir_cache.save(g.DIR_CACHE)
dir_cache._SEEN.clear()
dir_cache.load(g.DIR_CACHE)
real_read, real_key = Path.read_text, dir_cache.dir_key
stated = []
def no_read(self, *a, **k):
    raise AssertionError(f"re-read an unmoved edition: {self}")
def counted_key(d):
    stated.append(Path(d).name)
    return real_key(d)
Path.read_text, dir_cache.dir_key = no_read, counted_key
try:
    got = g.staged_matches(sc)
    has = (g.has_sources(sc / g.ITEM.format(1960) / "1960-01-04", "sources-1.json"),
           g.has_sources(sc / g.ITEM.format(1960) / "1960-01-04", "sources-2.json"),
           g.has_sources(sc / g.ITEM.format(1960) / "1960-01-07", "sources-1.json"),
           g.has_sources(sc / g.ITEM.format(1962) / "1962-01-01", "sources-1.json"))
finally:
    Path.read_text, dir_cache.dir_key = real_read, real_key
check("a later tick loads the unmoved editions from the cache file, reading none", want, got)
check("stat-ing the cache and each year dir, no edition dir",
      ["GaleTimes1960UKEnglish", "GaleTimes1961UKEnglish", "GaleTimes1962UKEnglish", "staged_cache"], sorted(set(stated)))
check("has_sources: the edition's own sources file, not another key's, a missing day's or year's",
      (True, False, False, False), has)
got[d1].append("mutated")
check("a caller changing a result does not change the next", want, g.staged_matches(sc))
lay(d1, [{"file": "c.pdf"}], key="2")
check("an edition swapped in again moves its year dir, so is read again",
      ({d1: [{"file": "c.pdf"}], d2: [{"file": "b.pdf"}]}, False, True),
      (g.staged_matches(sc), g.has_sources(sc / g.ITEM.format(1960) / "1960-01-04", "sources-1.json"),
       g.has_sources(sc / g.ITEM.format(1960) / "1960-01-04", "sources-2.json")))
shutil.rmtree(sc / g.ITEM.format(1961) / d2.isoformat())
age(sc / g.ITEM.format(1961))
check("and one removed is gone", {d1: [{"file": "c.pdf"}]}, g.staged_matches(sc))
# titleless stats no edition whose ledger row holds no scan; one that does
# is still checked against its files.
rel1 = f"{g.ITEM.format(1960)}/{d1.isoformat()}"
real_hash = fa.input_hash
hashed = []
fa.input_hash = lambda d: hashed.append(d.name) or real_hash(d)
try:
    unscanned = g.titleless(g.staged_matches(sc), {rel1: {"filesHash": "x"}}, sc)
    unhashed = list(hashed)
    scanned_row = {"filesHash": real_hash(sc / rel1), "scanKey": fa.scan_key(), "scan": {"puzzles": []}}
    scanned_one = g.titleless(g.staged_matches(sc), {rel1: scanned_row}, sc)
finally:
    fa.input_hash = real_hash
check("titleless: an edition never scanned is no titleless one, its dir not stat-ed", ({}, []), (unscanned, unhashed))
check("one scanned with its current files and no title read is titleless", [d1], list(scanned_one))
# fresh_unread looks inside a year dir only when it moved within FRESH.
year = sc / g.ITEM.format(1960)
os.utime(year / d1.isoformat(), None)
(year / d1.isoformat() / "pages.json").write_text("{}")
real_glob = Path.glob
def no_glob(self, pattern):
    raise AssertionError(f"globbed a year dir unmoved for FRESH: {self}")
Path.glob = no_glob
try:
    stale_year = g.fresh_unread(sc, {}, time.time())
finally:
    Path.glob = real_glob
check("fresh_unread: a year dir unmoved for FRESH is not looked in", [], stale_year)
os.utime(year, None)
check("one that moved is, and its fresh edition found", [rel1], g.fresh_unread(sc, {}, time.time()))
# wanted() asks unfiled only for the dates archive.org holds no scan of:
# those it skips need the ledgers and a stat of each edition's dir.
class _Paper:
    series = "x"
saved_ac = (archive_coverage.corpus, archive_coverage.scans, archive_coverage.printed_dates,
            archive_coverage.ledger, archive_coverage.failed_fetches)
archive_coverage.corpus = lambda series: ({"2000-01-01": 1}, {1: "2000-01-01"})
archive_coverage.scans = lambda paper: ({"2000-01-03": "item/slug"}, {2000: True})
archive_coverage.printed_dates = lambda series, today: ["2000-01-01", "2000-01-02", "2000-01-03"]
archive_coverage.ledger, archive_coverage.failed_fetches = lambda: {}, set
try:
    full = list(archive_coverage.unfiled(_Paper, datetime.date(2000, 2, 1)))
    def unread():
        raise AssertionError("unfiled(scanned=False) read the ledgers")
    archive_coverage.ledger = archive_coverage.failed_fetches = unread
    unscanned_only = list(archive_coverage.unfiled(_Paper, datetime.date(2000, 2, 1), scanned=False))
finally:
    (archive_coverage.corpus, archive_coverage.scans, archive_coverage.printed_dates,
     archive_coverage.ledger, archive_coverage.failed_fetches) = saved_ac
check("unfiled(scanned=False): the dates with no scan, as the full run classes them, reading no ledger",
      [r for r in full if not r[2]], unscanned_only)
check("the full run still classes a scanned date", ("2000-01-03", "not-fetched", "item/slug"), full[-1])
archive_coverage.corpus = lambda series: ({"2000-01-01": 1}, {1: "2000-01-01"})
archive_coverage.scans = lambda paper: ({"2000-01-03": "item/slug"}, {2000: True})
archive_coverage.printed_dates = lambda series, today: ["2000-01-01", "2000-01-02", "2000-01-03"]
archive_coverage.ledger = archive_coverage.failed_fetches = unread
try:
    listed = g.wanted(datetime.date(2000, 2, 1))
finally:
    (archive_coverage.corpus, archive_coverage.scans, archive_coverage.printed_dates,
     archive_coverage.ledger, archive_coverage.failed_fetches) = saved_ac
check("wanted(): every unfiled date, a scanned one too (unread, as SCAN_UNFILED), no filed one",
      [(D(2000, 1, 2), "no-scan"), (D(2000, 1, 3), g.SCAN_UNFILED)], listed)
print("FAILS", fails)
sys.exit(1 if fails else 0)
PY
