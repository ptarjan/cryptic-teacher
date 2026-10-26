#!/usr/bin/env python3
# Does tools/gale_inbox.py lay a Times page tools/gale_fetch.py downloaded
# out as GaleTimes<year>UKEnglish/<date> with its Gale document's link (and
# another paper's under its own item), find editions fresh and unread and
# start the corpus tick for them, and order what is still wanted (next_up,
# wanted)? Does the Times progress page show its counts, downloads, Gale's
# refusals and the years with nothing to click, a page's grid set by its
# lattice and not a photo, and a sync tick publish it only after a download?
#
#     python3 tests/test_gale_inbox.py
#
# Synthetic pages and PDFs in a temp dir: no OCR, nothing asked of the Mac,
# the desktop or Gale, nothing written outside it.
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
os.chdir(TOOLS)
sys.path.insert(0, str(TOOLS))
tmp = tempfile.mkdtemp()
atexit.register(shutil.rmtree, tmp, True)
# A temp downloads root, its manifests beside it (media_manifest.DIR), as the
# one-off build leaves the Gale editions' one.
os.environ["CT_DOWNLOADS"] = os.path.join(tmp, "dl")
os.makedirs(os.path.join(tmp, "dl", ".manifest"))
for name in ("gale-editions.jsonl", "archiveorg-editions.jsonl"):
    open(os.path.join(tmp, "dl", ".manifest", name), "w").close()
sys.argv = [sys.argv[0], tmp]

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
# Nor read the live caches (~/.cache).
g.HOME = Path(sys.argv[1]) / "home"

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
check("a Sunday is no issue", None, g.ISSUE.get(D(1988, 1, 10)))
# Every year Gale holds (1930-2019): dates and numbers in names of the
# 1950s and the 2000s; No 5,432 only after "No" (a bare 4 digits may be a year).
for name, want in [("The Times 12 Jan. 1955.pdf", D(1955, 1, 12)), ("2005-03-14 crossword.pdf", D(2005, 3, 14)),
                   ("19350102 p5.jpg", D(1935, 1, 2)), ("Times 1929-12-31.pdf", None), ("2020-01-02.pdf", None)]:
    check(f"the date in {name!r}", want, g.name_date(name))
check("the printed run spans every year Gale holds, into the January after (filed brackets)", (D(1930, 2, 1), D(2015, 1, 31)), (g.PRINTED[0], g.PRINTED[-1]))
# next_up: No 1 first, the rows the list held before it was widened (1974-99,
# no scan) in their old order, then 2014-19, 2000-13, the rest, newest first.
wide = [(D(1955, 3, 1), "no-scan"), (D(1930, 2, 1), g.SCAN_UNFILED), (D(2005, 6, 1), "no-scan"),
        (D(2016, 5, 2), "no-scan"), (D(1988, 1, 13), "no-scan"), (D(1987, 3, 2), "no-scan"),
        (D(1988, 1, 12), "no-scan"), (D(1985, 2, 1), g.SCAN_UNFILED), (D(2015, 1, 5), "no-scan"),
        (D(2010, 1, 4), "no-scan"), (D(1962, 1, 2), "no-scan")]
check("next_up: No 1, the old list in its order, 2014-19, 2000-13, then the rest, newest first",
      [D(1930, 2, 1), D(1988, 1, 12), D(1988, 1, 13), D(1987, 3, 2), D(2016, 5, 2), D(2015, 1, 5), D(2010, 1, 4),
       D(2005, 6, 1), D(1985, 2, 1), D(1962, 1, 2), D(1955, 3, 1)], [d for d, _ in g.next_up(wide, (), None)])

# A page tools/gale_fetch.py downloaded is its date's Times edition, found
# by the Gale run, fresh until read.
import PIL.Image, shutil, subprocess, shutil as _sh
cache = fa.CACHE
cache.mkdir(parents=True)
_pdf = io.BytesIO()
PIL.Image.new("RGB", (1200, 1600), "white").save(_pdf, format="PDF")
d = g.lay_out_fetched(D(1988, 1, 12), "IF0503151598", _pdf.getvalue(),
                      {"doc": "IF0503151598", "title": "The Times Crossword Puzzle No 17,563.", "page": 18}, cache)
pages = json.loads((d / "pages.json").read_text())
check("a fetched page is laid out as that date's Times edition", (cache / "GaleTimes1988UKEnglish" / "1988-01-12", True, "1988-01-12", 1),
      (d, (d / "leaf_0000.jpg").exists(), pages["date"], pages["leaves"]))
check("its source link is the Gale document's", g.DOC_URL.format("IF0503151598"), fa.page_url(d, {}, 0))
check("the Gale run finds the staged edition", [d], [e for e in fa.edition_dirs(cache, fa.GALE)])
check("as a Gale page, filed as the Times", (fa.GALE, "times"), (fa.paper_of(d), fa.paper_of(d).series))
check("and no other run's", ([], []), (fa.edition_dirs(cache, fa.FT), fa.edition_dirs(cache, fa.TIMES)))
rel = f"{d.parent.name}/{d.name}"
now = g.editions()[rel]["at"]
check("lay_out_fetched notes the edition in the SSD manifest, its files' hash and sources",
      (fa.input_hash(d), "IF0503151598"), (g.editions()[rel]["files"], g.editions()[rel]["sources"][0]["docId"]))
check("fresh_unread: an edition just laid out and never read is read now", [rel], g.fresh_unread({}, now))
check("not once read with its current files", [],
      g.fresh_unread({rel: {"inputs": "x", "filesHash": fa.input_hash(d)}}, now))
check("again once its files change", [rel], g.fresh_unread({rel: {"inputs": "x", "filesHash": "old"}}, now))
check("one laid out before FRESH is the full pass's", [], g.fresh_unread({}, now + g.FRESH + 1))
def _no_ledger():
    raise AssertionError("fresh_unread read the ledger with no fresh edition")
_real_ledger, g.archive_coverage.ledger = g.archive_coverage.ledger, _no_ledger
try:
    check("with none fresh it reads no ledger", [], g.fresh_unread(None, now + g.FRESH + 1))
finally:
    g.archive_coverage.ledger = _real_ledger
launched = []
class FakePopen:
    pid = 1
    def __init__(self, cmd, **kw):
        launched.append((cmd, kw))
import corpus_queue
saved_popen, saved_fresh = g.subprocess.Popen, g.fresh_unread
saved_cq = corpus_queue.running, corpus_queue.load_state
g.subprocess.Popen, g.fresh_unread = FakePopen, lambda: [rel]
corpus_queue.running, corpus_queue.load_state = lambda: None, lambda: {}
import os as _os
_os.environ["CT_IN_WORKTREE"], _os.environ["CT_MAIN_CHECKOUT"] = "1", "/tick/tree"
g.kick(io.StringIO(), tick=Path("/x/corpus_queue.sh"), log=Path(sys.argv[1]) / "kick.log")
check("kick: a fresh edition and no pass running starts the corpus tick detached, out of this tick's worktree",
      (["bash", "/x/corpus_queue.sh", "tick"], True, False, False),
      (launched[0][0], launched[0][1]["start_new_session"], "CT_IN_WORKTREE" in launched[0][1]["env"],
       "CT_MAIN_CHECKOUT" in launched[0][1]["env"]))
corpus_queue.running = lambda: {"pid": 1}
check("not while the pass runs: its queue reads the fresh edition first itself", None, g.kick(io.StringIO()))
corpus_queue.running, corpus_queue.load_state = lambda: None, lambda: {"held": True}
said = io.StringIO()
check("nor while it is held, and says so", (None, True), (g.kick(said), "held" in said.getvalue()))
corpus_queue.load_state = lambda: {}
g.fresh_unread = lambda: []
check("and nothing when no fresh edition waits", None, g.kick(io.StringIO()))
check("one launch in all", 1, len(launched))
check("no second OCR runner: tools/gale_read.sh is gone", False, (Path(g.TOOLS) / "gale_read.sh").exists())
g.subprocess.Popen, g.fresh_unread = saved_popen, saved_fresh
corpus_queue.running, corpus_queue.load_state = saved_cq
del _os.environ["CT_IN_WORKTREE"], _os.environ["CT_MAIN_CHECKOUT"]

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
html = g.checklist(rows, None, docs={}, ledger={}, log=LOG, fetched=FETCHED, limits=LIMITS)
check("nothing to click: no Download, no script, no instructions; it reloads itself", (False, False, False, True),
      ('class="dl"' in html, "<script>" in html, 'id="instructions"' in html, 'http-equiv="refresh"' in html))
check("its counts: wanted, to fetch, waiting to be read", (True, True, True),
      ("<th>Wanted (no puzzle filed)</th><td>4</td>" in html, "<th>Still to fetch</th><td>3</td>" in html,
       "<th>Fetched, waiting to be read</th><td>1</td>" in html))
check("the script's downloads and Gale's refusals", (True, True, True),
      ("<td>1 (1 today)</td>" in html, "after 480 in its window" in html, "worked again after 30 min" in html))
check("the years in next_up's order, the worst first", True, html.index("<td>1988</td>") < html.index("<td>1987</td>"))
rel88 = "GaleTimes1988UKEnglish/1988-01-12"
scanned = {rel88: {"edition": rel88, "scan": {"puzzles": [], "solutions": []}, "filesHash": fa.input_hash(d),
                  "scanKey": fa.scan_key(fa.GALE)}}
html2 = g.checklist(rows, None, docs={}, ledger=scanned, log=LOG, fetched=FETCHED, limits=LIMITS)
check("a read edition counts as read, not waiting", (True, True),
      ("<th>Read, no puzzle filed from it</th><td>1</td>" in html2, "<th>Fetched, waiting to be read</th><td>0</td>" in html2))

# A page tools/gale_fetch.py downloaded is laid out with its match what the
# download knew.
fd = g.lay_out_fetched(D(1988, 1, 14), "IF0501710449", _pdf.getvalue(),
                       {"doc": "IF0501710449", "title": "The Times Crossword Puzzle No 17,565.", "page": 18}, cache)
_src = json.loads(next(fd.glob("sources-*.json")).read_text())
check("a fetched page is its date's edition, its match what the download knew", (True, "fetched", "IF0501710449",
      "The Times Crossword Puzzle No 17,565", True),
      ((fd / "leaf_0000.jpg").exists(), _src[0]["how"], _src[0]["docId"], _src[0]["cited"],
       g.cryptic_cited(_src[0])))
check("and it counts as staged", True, D(1988, 1, 14) in g.staged_matches())
shutil.rmtree(fd)

# Another paper's fetched page is laid out under its own item, its link
# that archive's, and leaves that paper's wanted list.
_e = {"doc": "IO0700000001", "title": "No. 12,212 across", "page": 14}
check("an OTHERS paper's date is wanted until laid out", True, D(1965, 3, 2) in g.other_wanted("TGRH"))
od = g.lay_out_fetched(D(1965, 3, 2), "IO0700000001", _pdf.getvalue(), _e, cache, prod="TGRH")
check("laid out under the paper's own item, with its archive's link", (cache / "GaleTelegraph1965UKEnglish" / "1965-03-02",
      "GaleTelegraph1965UKEnglish", True), (od, json.loads((od / "pages.json").read_text())["item"],
                                           "/TGRH?" in json.loads((od / "pages.json").read_text())["url"]))
check("and no longer wanted", False, D(1965, 3, 2) in g.other_wanted("TGRH"))
check("no Times edition", False, D(1965, 3, 2) in g.staged_matches())
shutil.rmtree(od.parent)

# Not on Gale: no issue, or no crossword listed and the page saved for the
# day set aside (the set-aside log) as another puzzle.
cryptic, concise = "The Times Crossword Puzzle No 17,275", "Concise Crossword No 1154"
LOG.write_text(json.dumps({"IF0501710448.pdf": {"date": "1988-01-14", "at": datetime.datetime.now().astimezone().isoformat(),
                                                "why": f"Gale's citation names {concise!r}, not the cryptic"}}))
docs = {"TTDA/1988-01-14": {"why": "no crossword in the issue's contents"}, "TTDA/1988-01-13": {"why": "no crossword in the issue's contents"},
        "TTDA/1987-03-02": {"why": "Gale has no issue that day"}}
aside = g.aside_days(LOG)
check("Gale has no cryptic: no issue, or no crossword listed and the page found another puzzle; else still to fetch",
      (True, True, None), (bool(g.not_on_gale(D(1988, 1, 14), docs, aside)), bool(g.not_on_gale(D(1987, 3, 2), docs, aside)),
                           g.not_on_gale(D(1988, 1, 13), docs, aside)))
html3 = g.checklist(rows, None, docs=docs, ledger={}, log=LOG, fetched=FETCHED, limits=LIMITS)
check("such a date counts as not on Gale, not to fetch", True, "<th>Not on Gale</th><td>2</td>" in html3)
check("only the cryptic's title is the cryptic", (True, False, False),
      (g.cryptic_cited({"cited": cryptic}), g.cryptic_cited({"cited": concise}), g.cryptic_cited({})))

# A PDF's text: a one-page PDF to read.
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

# A Gale page: a whole bilevel page (ink 0, paper 255) whose grid is found
# among a bigger photo.
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
        for u in (g.DOC_URL.format("IF0500004465"), "https://abresearchportal.ca/collections"))])

times = g.pdf_text(pdf("The Times, 12 Jan. 1988, p. 18. The Times Digital Archive. Gale Document Number: GALE|IF0503151598"))
listener = g.pdf_text(pdf("The Listener, 5 Feb. 1970, p. 190. The Listener Historical Archive. link.gale.com/apps/doc/X"))
tax = g.pdf_text(pdf("Notice of assessment 2025. Canada Revenue Agency"))
check("a PDF's text is read", True, "Times Digital Archive" in times)
check("a file that is not a PDF has no text", "", g.pdf_text(b"\xff\xd8 jpeg bytes"))
g.LOCK = Path(sys.argv[1]) / "sync.lock"
with g.locked():
    buf = io.StringIO()
    g.sync(out=buf)
check("a sync while another holds the lock skips at once, not waits", "another sync holds the lock; this one skips\n",
      buf.getvalue())
# A tick publishes the progress page only after a download (or RENDER_EVERY).
import time as _time
real = (g.next_up, g.wanted, g.last_render, g.kick, g.LOCK, g.checklist, g.publish, g.CHECKLIST, g.FETCHED)
g.next_up, g.wanted = (lambda *a: []), (lambda: {})
g.last_render, g.kick = (lambda: _time.time() + 10**9), (lambda *a: None)
g.LOCK = Path(sys.argv[1]) / "sync2.lock"
pages_made, pushed = [], []
g.checklist, g.publish = (lambda: pages_made.append(1) or ""), (lambda *a, **k: pushed.append(1))
g.CHECKLIST, g.FETCHED = Path(sys.argv[1]) / "tick" / "Checklist.html", Path(sys.argv[1]) / "tick_fetched.json"
g.sync(out=io.StringIO())
check("a tick with no download since the last page publishes none", ([], []), (pages_made, pushed))
g.last_render = lambda: 0
g.FETCHED.write_text("{}")
g.sync(out=io.StringIO())
check("a tick after a download (or RENDER_EVERY) publishes the progress page", ([1], [1]), (pages_made, pushed))
(g.next_up, g.wanted, g.last_render, g.kick, g.LOCK, g.checklist, g.publish, g.CHECKLIST, g.FETCHED) = real
# A tick reads the editions off the SSD manifest, never the media disk: no
# listing, glob or stat of the cache.
import os, time, datetime, archive_coverage
import media_manifest
real_fs = (os.listdir, os.scandir, os.stat, Path.glob, Path.iterdir)
def _no_disk(*a, **k):
    raise AssertionError(f"a tick looked at the disk: {a[:1]}")
os.listdir = os.scandir = os.stat = Path.glob = Path.iterdir = _no_disk
try:
    staged = g.staged_matches()
    fresh = g.fresh_unread({}, time.time() + g.FRESH + 1)
    other = D(1965, 3, 2) in g.other_wanted("TGRH", today=D(1966, 1, 1))
finally:
    os.listdir, os.scandir, os.stat, Path.glob, Path.iterdir = real_fs
check("staged_matches, fresh_unread and other_wanted touch no disk", (True, [], False),
      (D(1988, 1, 14) in staged, fresh, other))
staged[D(1988, 1, 14)].append("mutated")
check("a caller changing a result does not change the next", False, "mutated" in g.staged_matches()[D(1988, 1, 14)])
# A later row for an edition stands over an earlier; another paper's is no Times match.
media_manifest.record(g.EDITIONS, fa.CACHE / "x", edition=g.ITEM.format(1960) + "/1960-01-04", files="a",
                      sources=[{"file": "a.pdf"}])
media_manifest.record(g.EDITIONS, fa.CACHE / "x", edition=g.ITEM.format(1960) + "/1960-01-04", files="b",
                      sources=[{"file": "c.pdf"}])
check("the last row for an edition stands", [{"file": "c.pdf"}], g.staged_matches()[D(1960, 1, 4)])
media_manifest.record(g.EDITIONS, Path(sys.argv[1]) / "elsewhere", edition="x/y", files="a", sources=[])
check("a dir outside the downloads root is not recorded", False, "x/y" in g.editions())
# The one-off build writes the same rows as the lay-outs did.
laid = {e: (r["files"], r["sources"]) for e, r in g.editions().items() if (fa.CACHE / e).is_dir()}
built = {r["edition"]: (r["files"], r["sources"]) for r in g.build_manifest(out=io.StringIO())}
check("gale_inbox.py build-manifest finds every laid-out edition", laid, built)
os.unlink(media_manifest.path(g.EDITIONS))
try:
    g.staged_matches()
    check("a manifest never built is an error, not an empty disk", True, False)
except SystemExit as e:
    check("a manifest never built is an error, not an empty disk", True, "media_manifest.py build" in str(e))
said = io.StringIO()
g.sync(out=said)
check("and a sync tick skips until it is built", True, "not built yet" in said.getvalue())
media_manifest.write(g.EDITIONS, [])
# unfiled asks archive.org's edition manifest too (archive_coverage.fetched_editions).
media_manifest.write(media_manifest.ARCHIVE_EDITIONS, [])
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
# Gale's Times Digital Archive ends with 2014: no later date is ever wanted.
archive_coverage.corpus = lambda series: ({}, {})
archive_coverage.scans = lambda paper: ({}, {})
archive_coverage.printed_dates = lambda series, today: ["2014-12-31", "2015-01-02", "2017-08-24", "2018-04-16"]
archive_coverage.ledger = archive_coverage.failed_fetches = unread
try:
    late = [d for d, _ in g.wanted(datetime.date(2026, 1, 1))]
finally:
    (archive_coverage.corpus, archive_coverage.scans, archive_coverage.printed_dates,
     archive_coverage.ledger, archive_coverage.failed_fetches) = saved_ac
check("wanted(): no date after 2014, where Gale's Times archive ends", [D(2014, 12, 31)], late)
print("FAILS", fails)
sys.exit(1 if fails else 0)
