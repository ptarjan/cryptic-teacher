#!/usr/bin/env python3
# Does /progress/ count each phase right? The backfill must date each puzzle's
# phases where tools/progress.py says, the build must replace today's file
# phases with its own index while carrying the ledger's counts forward, the
# paces must divide by days and not by points, and the page must draw every
# chart with today's totals in it. A deploy after tonight's row must show its
# own filed/solved/hinted with the recorded known and queue, and its time.
#
#     python3 tools/test_progress.py
#
# A synthetic history and index, so nothing here reads the corpus or writes to
# the tree.
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
TMPDIR = tempfile.mkdtemp()
atexit.register(shutil.rmtree, TMPDIR, ignore_errors=True)
import subprocess
sys.path.insert(0, str(REPO / "tools"))
os.environ["TMP"] = TMPDIR

import os
from datetime import date
from pathlib import Path
import progress as P
import progress_record as R
import build_seo_pages as B

rows = [("times-1", "times", "2026-10-01", "2026-10-01", True),
        ("times-2", "times", "2026-10-01", "2026-10-03", True),
        ("times-3", "times", "2026-10-02", None, False),
        ("azed-9", "azed", "2026-10-03", "2026-10-03", True)]
ledgers = {"2026-10-03": {"series": {"times": {"exist": 10, "filed": 3}}}}
days = R.backfill_days(rows, {"times-2": "2026-10-04"}, ledgers, "2026-10-04")
assert list(days) == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"], list(days)
assert days["2026-10-01"] == {"times": [None, None, 2, 1, 1, None, None]}, days["2026-10-01"]
assert days["2026-10-03"] == {"azed": [None, None, 1, 1, 1, None, None], "times": [10, 3, 3, 2, 1, None, None]}, days["2026-10-03"]
# times-2's hints date from its Annotate commit, not its filing.
assert days["2026-10-04"]["times"] == [None, None, 3, 2, 2, None, None], days["2026-10-04"]

path = Path(os.environ["TMP"]) / "progress.json"
P.save(days, path)
assert P.load(path) == days and len(path.read_text().splitlines()) == len(days) + 2
# A row saved before the queue phases existed stays five long on disk.
assert '"times":[10,3,3,2,1]' in path.read_text(), path.read_text()

# The read queue: downloaded and queued, recorded on two nights.
days["2026-10-05"] = P.day_row({"times": [3, 2, 2], "azed": [1, 1, 1]}, None, {"times": [100, 40]})
days["2026-10-07"] = P.day_row({"times": [3, 2, 2], "azed": [1, 1, 1]}, None, {"times": [110, 30]})
assert days["2026-10-07"]["times"] == [None, None, 3, 2, 2, 110, 30]
P.save(days, path)
assert P.load(path) == days

# The queue's backfill: a scan counts from the day it landed, leaves queued
# the day it was first read, and a recorded count is never replaced.
import edition_backlog as E
scans = [("times", 1, "2026-10-02", "2026-10-03"), ("times", 1, "2026-10-03", None),
         ("canberra", 0.5, "2026-10-03", None), ("canberra", 0.5, "2026-10-03", None)]
hist = E.history(scans, ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-05"])
assert hist["2026-10-01"] == {} and hist["2026-10-02"] == {"times": [1, 1]}, hist
assert hist["2026-10-03"] == {"times": [2, 1], "canberra": [1, 1]}, hist
q = {d: {s: list(c) for s, c in r.items()} for d, r in days.items()}
q["2026-10-04"]["times"][5:] = [0, 0]   # a bogus zero is replaced
hist["2026-10-04"] = hist["2026-10-03"]
assert R.fill_queue(q, hist) == ["2026-10-02", "2026-10-03", "2026-10-04"]
assert q["2026-10-04"]["times"][5:] == [2, 1] and "canberra" not in q["2026-10-04"], q["2026-10-04"]
assert q["2026-10-03"]["times"] == [10, 3, 3, 2, 1, 2, 1] and q["2026-10-03"]["canberra"] == [None, None, 0, 0, 0, 1, 1], q
assert q["2026-10-05"]["times"][5:] == [100, 40], "a recorded night is kept"
assert "canberra" not in q["2026-10-05"], "a counted night's missing series stays missing"
assert all(a >= b for r in q.values() for c in r.values() for a, b in zip(P.nested(c), P.nested(c)[1:]))

# One puzzle a series and print date, however many copies are on disk: the
# Gale Times and archive.org's NewsUK Times hold the same 1970-1999 dates, and
# FT items hold a date twice under two issue numbers. A date is read once any
# copy is; an undated dir counts on its own.
assert E.edition_day("1989-10-10_30968") == "1989-10-10" and E.edition_day("1970-04-07") == "1970-04-07"
assert E.edition_day("19891010") == "19891010" and E.edition_day("2001-01-019") == "2001-01-019"
eds = [("times", "1975-03-01", True), ("times", "1975-03-01", False),     # Gale read, NewsUK not
       ("times", "1975-03-02", False), ("times", "1975-03-02", False),    # neither read
       ("times", "1975-03-03", False),
       ("ftcryptic", "1989-10-10_30968", False), ("ftcryptic", "1989-10-10_30969", True),
       ("ftcryptic", "1989-10-11_30970", False)]
assert E.by_day(eds) == {"times": [3, 2], "ftcryptic": [2, 1]}, E.by_day(eds)
# Read and not filed: a date some copy of which was read, with no puzzle filed
# for it (none of these dates is filed), so To fetch never counts it.
_corpus = E.archive_coverage.corpus
E.archive_coverage.corpus = lambda series: ({"1989-10-10": 1} if series == "ftcryptic" else {}, {})
assert E.read_not_filed(eds) == {"times": 1}, E.read_not_filed(eds)
E.archive_coverage.corpus = _corpus

# A Trove row is a Canberra puzzle when it is filed or held back as itself:
# not a Times reprint (refused, renamed, or numbered by
# canberra_london_numbers), not a copy of another number's clues, and not a
# clean write whose file is gone (folded into the Times). On 2026-10-15 760
# rows held an id and the page said 760 downloaded; 664 were Canberra's.
held, renamed, london = {"canberra-1"}, {"canberra-3"}, {"a7"}
rows = [{"article": "a1", "id": "canberra-1"},                       # filed
        {"article": "a2", "id": "canberra-2", "pending": "clues unread"},  # held back
        {"article": "a3", "id": "canberra-3", "wrote": True},        # renamed to the Times
        {"article": "a4", "id": "canberra-4", "refusedWrite": "refusing to write canberra-4: REPRINT reprints times-1: ..."},
        {"article": "a5", "id": "canberra-5", "refusedWrite": "requested canberra-5 but the page served the clues of canberra-9 (30 of 30 clues are the same)"},
        {"article": "a6", "id": "canberra-6", "wrote": True},        # folded: file gone
        {"article": "a7", "id": "canberra-7", "pending": "x"},       # a London reprint
        {"article": "a8", "id": "canberra-8", "refusedWrite": "refusing to write canberra-8: 9-across holds a clue number"},
        {"article": "a9"}]                                           # no puzzle
got = [E.trove_puzzle(r, held, renamed, london) for r in rows]
assert got == [True, True, False, False, False, False, False, True, False], got

# Listener pages count once per puzzle number read (606 pages were 552
# numbers on 2026-10-15); an unread page or an unmatched one counts alone.
import json, tempfile
from pathlib import Path
import gale_listener as GL
with tempfile.TemporaryDirectory() as t:
    inbox, store = Path(t, "in"), Path(t, "store")
    inbox.mkdir(), store.mkdir()
    for n in "abcdef":
        (inbox / f"{n}.pdf").write_bytes(b"%PDF")
    led = [{"sha": "1", "file": "a.pdf", "number": 36}, {"sha": "2", "file": "b.pdf", "number": 36},
           {"sha": "3", "file": "c.pdf", "number": 15}, {"sha": "4", "file": "d.pdf", "number": None}]
    (store / GL.LEDGER).write_text("".join(json.dumps(r) + "\n" for r in led))
    assert E.listener_counts(inbox, store) == [6, 2, 5, 2], E.listener_counts(inbox, store)

live = P.with_today(days, {"times": [5, 4, 3], "azed": [1, 1, 1]}, "2026-10-08")
assert live["2026-10-08"] == {"azed": [None, None, 1, 1, 1, None, None], "times": [10, 3, 5, 4, 3, 110, 30]}, live["2026-10-08"]
assert P.totals(live["2026-10-08"]) == [10, 3, 6, 5, 4, 110, 30]
# The three queues: depths from one row, flows from the recorded nights.
assert B.queue_depths([10, 3, 5, 4, 3, 110, 30]) == (0, 75, 30, 2)
assert B.queue_depths([100, 3, 5, 4, 3, 40, 30]) == (60, 5, 30, 2)
assert B.queue_depths([None, None, 1, 1, 1, None, None]) == (None, None, None, 0)
# Filed from a blog: filed 5,542 vs downloaded 319 must not read as to fetch.
assert B.queue_depths([6000, 0, 5542, 0, 0, 319, 10]) == (448, 0, 10, 5542)
assert B.queue_depths([100, 0, 120, 0, 0, 5, 3]) == (0, 0, 3, 120)   # never negative
# Times: 29,668 known, 23,714 downloaded, 16,416 filed, 4,161 queued.
assert B.queue_depths([29668, 0, 16416, 0, 0, 23714, 4161])[:3] == (5954, 3137, 4161)
# A falling known count makes fetch's in negative, shown with its sign.
fall = {"2026-10-01": {"blog": [100, 0, 50, 0, 0, 5, 2]}, "2026-10-03": {"blog": [96, 0, 54, 0, 0, 6, 2]}}
ff = B.queue_flows(fall, 7)
assert ff[0] == (-2, 2) and ff[1] == (2, 2), ff
assert B.flow_text(ff[0]) == "&minus;2 / &minus;2", B.flow_text(ff[0])
assert "<td>40 " in B.queue_table(fall["2026-10-03"], fall)
flows = B.queue_flows(days, 7)
# Filed + queued fell 42 -> 33 over the two days between the queue's nights, so
# fetch's out is -5 a day; read's in is queued's gain plus filed's; known is
# recorded on one night only here.
assert flows[0] == (None, -5) and abs(flows[1][0] - (-5 + flows[1][1])) < 1e-9 and flows[2][0] == flows[1][1], flows
assert B.flow_text((None, None)) == "needs 2 nights" and B.flow_text((5, 2)) == "+5 / &minus;2"
assert B.flow_text((None, 2)) == "? / &minus;2"
html = B.queue_table({"times": [100, 3, 5, 4, 3, 40, 30], "azed": [1, 1, 1, 1, 1, 1, 0], "x": [0, 0, 0, 0, 0, 0, 0]}, days)
assert "Downloaded" not in html and "<th>To fetch</th>" in html and "All series" in html, html
assert html.index("Times") < html.index("Azed") if "Azed" in html else True
assert ">x<" not in html and "<td>60 " in html and "<th>Read failed</th>" in html, html

pts = P.series_of(live, P.HINTED)
assert P.daily(pts)[-1] == ("2026-10-08", 1), P.daily(pts)
# Three puzzles hinted in the seven days since 10-01 (times-2, azed-9, the
# live one): a mean over days, not over the five points.
assert abs(P.rate(pts, 7) - 3 / 7) < 1e-9, P.rate(pts, 7)
assert P.rate(P.series_of(live, P.KNOWN), 7) == 0

# Every stage nests in the one above, per series and in total: downloaded is
# filed plus the unread, capped at known-but-unfiled; hinted needs solved.
assert P.file_counts([("a", True, True), ("a", False, True), ("a", True, False)]) == {"a": [3, 2, 1]}
cases = [[100, 90, 40, 30, 20, 500, 400],   # unread capped at known - filed = 60
         [100, 90, 40, 30, 20, 50, 10],
         [None, None, 76, 76, 76, None, None],   # no ledger: known follows downloaded
         [10, 10, 12, 12, 12, 3, 3],            # more filed than known
         [50, 5, 30, 40, 45, None, None]]       # stale solved/hinted above filed
for c in cases:
    n = P.nested(c)
    assert all(a >= b for a, b in zip(n, n[1:])), (c, n)
assert P.nested(cases[0]) == [100, 100, 40, 30, 20] and P.nested(cases[1]) == [100, 50, 40, 30, 20]
assert P.nested(cases[2]) == [76, 76, 76, 76, 76]
tot = P.nested_totals(dict(enumerate(cases)))
assert all(a >= b for a, b in zip(tot, tot[1:])), tot
assert tot == [sum(P.nested(c)[i] for c in cases) for i in range(5)]

assert B.at_pace(0, 5) == "done" and B.at_pace(10, 0) == "not moving"
assert B.at_pace(100, 10) == "10 days" and B.at_pace(3650, 1) == "10 years"

P.HISTORY = path

# Where the Gale downloader is: recorded nightly from its plan (its state is
# on the downloader's host), drawn under the queues table.
from datetime import date as _d
rows = [("TTDA", _d(1935, 1, 16), None), ("TTDA", _d(1935, 1, 15), None), ("TTDA", _d(1934, 12, 31), None),
        ("LSNR", _d(1935, 1, 1), None)]
cur = R.fetching(rows, {"TTDA": "The Times"})
assert cur == {"paper": "The Times", "year": 1935, "left": 2, "back": True}, cur
assert R.fetching([]) is None
assert R.fetching([("TLSH", _d(1992, 1, 3)), ("TLSH", _d(1992, 1, 10))])["back"] is False
P.FETCHING = Path(tempfile.mkdtemp()) / "fetching.json"
assert P.load_fetching() == {} and B.fetching_note(P.load_fetching()) == ""
P.save_fetching({"at": "2026-10-18", **cur})
assert B.fetching_note(P.load_fetching()) == (
    '<p class="muted small-note">Fetching: Gale (The Times), working back through 1935 '
    '(2 pages left in that bucket), as of the 18 Oct night count.</p>'), B.fetching_note(P.load_fetching())
idx = {"puzzles": [{"series": "times", "hasSolutions": True, "annotated": True}] * 4
                  + [{"series": "times", "hasSolutions": False, "annotated": False}]}
def ided(idx):
    """Index rows as the build has them: an id, a number and a date each."""
    idx["puzzles"] = [{**p, "id": f"{p['series']}-{i}", "number": i, "date": "2026-10-01"}
                      for i, p in enumerate(idx["puzzles"])]
    return idx
ided(idx)
html = B.progress_page(idx, today=date(2026, 10, 8))
assert html.count("<svg") == 5, html.count("<svg")
assert "<h2>The queues</h2>" in html and "<th>To annotate</th>" in html and "Not read" not in html
assert html.index("</table>", html.index("<h2>The queues</h2>")) < html.index("Fetching: Gale (The Times)")
assert "30 <span" in html and "(&minus;5 / " in html, "read queue fell 40 to 30 with 1 filed"
assert "<polyline" in html, html[:2000]

# The table is the bars: same stages, labels, numbers, order and colours, from
# one source, and one known total everywhere on the page (Paul 10-12: "why are
# the entries in the table different than the bars").
import re
main = html.split("<main", 1)[1].split("</main>")[0]
funnel = main.split('<svg', 1)[1].split("</svg>")[0]
bars = re.findall(r'text-anchor="end">([^<]+)</text><rect class="track"[^>]*/>'
                  r'<rect class="ph-([a-z]+)"[^>]*/><text[^>]*>([\d,]+) ·', funnel)
table = main.split('class="progress-table"', 1)[1].split("</table>")[0]
trs = re.findall(r'<tr><td><span class="key-dot ph-([a-z]+)"></span>([^<]+)</td><td>([\d,]+)</td>'
                 r'(.*?)</tr>', table)
assert len(trs) == table.count("<tr>") - 1, ("every row is a stage with a dot", table)
assert [(l, c, n) for l, c, n in bars] == [(l, c, n) for c, l, n, _ in trs], (bars, trs)
assert [l for l, _, _ in bars] == list(B.FUNNEL_LABEL), bars
assert len({c for _, c, _ in bars}) == 5, "no two stages share a colour"
want = P.nested_totals(P.with_today(P.load(path), P.file_counts(
    (p["series"], p.get("hasSolutions"), p.get("annotated")) for p in idx["puzzles"]), "2026-10-08")["2026-10-08"])
assert [int(n.replace(",", "")) for _, _, n in bars] == want, (bars, want)
assert all(a >= b for a, b in zip(want, want[1:])), want
knowns = set(re.findall(r"([\d,]+) (?:are known to exist|puzzles known to exist)", main))
assert knowns == {f"{want[0]:,}"}, ("one known total", knowns)
assert "not read yet</td>" not in main and "acquired" not in main.lower(), "no queue or acquired row"
assert "unread" not in main, "the downloaded bar is drawn like every other"
solved = next(rest for c, l, n, rest in trs if l == "solved")
assert re.sub(r"<[^>]+>", "", solved).replace("%", "").strip().isdigit(), ("solved has no pace", solved)
assert "{" not in html.split("<main", 1)[1].split("</main>")[0], "an unfilled placeholder"

# The live overlay (Paul 10-12: "The progress page should update more
# regularly"): a deploy hours after tonight's row was recorded shows its own
# index's filed/solved/hinted, keeps the recorded known and queue, and stays
# nested; the page says the time it was built.
from datetime import datetime
night = dict(P.load(path))
night["2026-10-09"] = {"times": [10, 3, 4, 3, 2, 30, 4], "azed": [None, None, 1, 1, 1, None, None]}
P.save(night, path)
idx2 = {"puzzles": [{"series": "times", "hasSolutions": True, "annotated": True}] * 6
                   + [{"series": "times", "hasSolutions": True, "annotated": False}] * 2
                   + [{"series": "times", "hasSolutions": False, "annotated": True}] * 2
                   + [{"series": "azed", "hasSolutions": True, "annotated": True}]}
ided(idx2)
live = P.with_today(P.load(path), P.index_counts(idx2["puzzles"]), "2026-10-09")["2026-10-09"]
assert live == {"times": [10, 3, 10, 8, 6, 30, 4], "azed": [None, None, 1, 1, 1, None, None]}, live
chain = P.nested_totals(live)
assert chain == [11, 11, 11, 9, 7], chain   # times: known 10, downloaded 10 + min(4, 0)
assert all(a >= b for a, b in zip(chain, chain[1:])), chain
html = B.progress_page(idx2, now=datetime(2026, 10, 9, 14, 5))
want = "As of 14:05 on 9 Oct."
assert want in html, re.search(r"As of[^<]*", html).group(0)
assert "recounted every time the site updates" in html
assert P.load(path)["2026-10-09"]["times"][2:5] == [4, 3, 2], "the build never writes the history"
# One counting path: a night's row and the overlay apply the index's own tests.
import inspect, fetch_puzzle
assert "puzzle_is_solved(p)" in inspect.getsource(fetch_puzzle.index_row)
src = inspect.getsource(R.puzzle_row)
assert "puzzle_is_solved(p)" in src and "puzzle_is_annotated(p)" in src, src

# puzzle_row views only fully annotated files (2026-10-15: viewing all ~55k
# serially under nice ran past 900s), and still counts as the view does: an
# annotation whose tree no longer gives its answer is no hint.
import json, puzzle_paths
def viewed_row(f):
    p = fetch_puzzle.read_puzzle_view(f)
    got = p["source"]["acquiredOn"]
    solved = max(got, (p.get("solutions") or {}).get("date") or got) if fetch_puzzle.puzzle_is_solved(p) else None
    return p["id"], p["series"], got, solved, fetch_puzzle.puzzle_is_annotated(p)
picked = {}
for f in puzzle_paths.puzzle_files("times"):
    picked.setdefault(fetch_puzzle.puzzle_is_annotated(fetch_puzzle.read_puzzle_file(f)), f)
    if len(picked) == 2:
        break
assert len(picked) == 2, picked
work = Path(os.environ["TMP"]) / "puzzles"
work.mkdir()
broken = json.loads(picked[True].read_text())
for e in broken["entries"]:
    if "annotation" in e:   # every tree names words the clue no longer has
        e["clue"]["text"] = "Xq zv."   # (not just the first: some trees, e.g. a cryptic definition's, name none)
files = [work / "a.json", work / "b.json", work / "c.json"]
files[0].write_text(picked[True].read_text())
files[1].write_text(picked[False].read_text())
files[2].write_text(json.dumps(broken))
assert fetch_puzzle.puzzle_is_annotated(broken), "raw: every clue still has an annotation"
want = [viewed_row(f) for f in files]
assert [w[4] for w in want] == [True, False, False], want
assert [R.puzzle_row(f) for f in files] == want, ([R.puzzle_row(f) for f in files], want)

# The row cache: a second run reads nothing, a file that moved is read again,
# a gone file is dropped, and a change to the deriving code reads every file.
cache, reads, real = Path(os.environ["TMP"]) / "rows.json", [], R.puzzle_row
R.puzzle_row = lambda f: reads.append(f.name) or real(f)
try:
    assert R.cached_rows(files, cache) == want and len(reads) == 3, reads
    reads.clear()
    assert R.cached_rows(files, cache) == want and reads == [], reads
    files[2].write_text(picked[True].read_text())
    assert R.cached_rows(files, cache) == want[:2] + [want[0]] and reads == ["c.json"], reads
    reads.clear()
    files[1].unlink()
    assert R.cached_rows(files, cache) == [want[0], want[0]] and reads == [], reads
    assert len(json.loads(cache.read_text())["rows"]) == 2
    R.code_digest, digest = (lambda: "changed"), R.code_digest
    try:
        assert R.cached_rows(files, cache) == [want[0], want[0]] and len(reads) == 2, reads
    finally:
        R.code_digest = digest
finally:
    R.puzzle_row = real

# By series links each series to its own page (Paul 10-12: "clicking By series
# should take you to that series"): every row whose series has a page is one
# link, the whole row, to a page the build writes; a series with no page has
# no link.
byseries = html.split("<h2>By series</h2>", 1)[1].split("</svg>")[0]
pages = {"/" + str(p.relative_to(B.ROOT).parent) + "/" for p, _ in B.series_pages(idx2)}
names = re.findall(r'text-anchor="end">([^<]+)</text><rect class="track"', byseries)
links = re.findall(r'<a class="row" href="([^"]+)">.*?text-anchor="end">([^<]+)</text>.*?</a>', byseries)
assert names and len(links) == sum(B.series_name(s) in names for s in B.listings(idx2)), (names, links)
for href, name in links:
    s = next(s for s in B.listings(idx2) if B.series_name(s) == name)
    assert href == B.site_url(B.series_path(s)) and B.series_path(s) in pages, (href, name, pages)
    assert '<rect class="hit" x="0"' in byseries, "the whole row is the link"
assert not re.search(r'<a class="row"', B.series_chart(live, ())), "no page, no link"

# Running totals (Paul 10-12: "the number goes off the side and it goes far
# back without much resolution"). A long flat lead-in, then fast growth to
# six-figure totals, with downloaded and filed ending close together.
from datetime import timedelta
long, d0 = {}, date(2026, 7, 26)
for i in range(79):
    grow = max(0, i - 52) / 26                     # flat until day 52
    filed = int(300 + 150_541 * grow ** 1.5)
    hinted = min(filed, int(i * 4 + 16_300 * grow))
    queued = 4_714 if i >= 70 else None
    long[(d0 + timedelta(days=i)).isoformat()] = {
        "times": [400_000, None, filed, hinted, hinted, None if queued is None else filed + queued, queued]}
last = (d0 + timedelta(days=78)).isoformat()
assert P.nested_totals(long[last])[1:3] == [155_555, 150_841], P.nested_totals(long[last])
def geometry(chart):
    W, H = map(float, re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', chart).groups())
    keys = [(float(x), float(y), t) for x, y, t in
            re.findall(r'<text class="ph-[a-z]+ key" x="([\d.]+)" y="([\d.]+)">([^<]+)</text>', chart)]
    xs = [float(p.split(",")[0]) for pl in re.findall(r'points="([^"]+)"', chart) for p in pl.split()]
    ticks = re.findall(r'<text class="tick"[^>]*>([^<]+)</text>', chart)
    return W, H, keys, xs, ticks
for chart, trimmed in (B.cumulative_chart(long), (B.cumulative_chart(long, full=True)[0], False)):
    W, H, keys, xs, ticks = geometry(chart)
    # Four lines; scans on disk and not read are the recorded raw counts, so
    # the scans line is not filed plus the unread (it was, via nested()).
    assert len(keys) == 4 and {t for *_, t in keys} >= {"scans on disk 155,555", "scans not read 4,714"}, keys
    # Labels never clip: each one's generous width ends inside the viewBox, at any screen width.
    assert B.KEY_EM >= .6, "a bold 11px label is at least .6em a character"
    for x, y, t in keys:
        assert x + B.key_width(t) <= W and 0 < y <= H, (x, y, t, W)
    ys = sorted(y for _, y, _ in keys)
    assert all(b - a >= B.KEY_GAP - .05 for a, b in zip(ys, ys[1:])), ("labels overlap", ys)
    assert max(xs) < min(x for x, _, _ in keys), "labels sit right of every line"
    assert 2 <= len(ticks) <= 6 and ticks[-1] == B.short_day(last), ticks
    assert ("since" in chart) == trimmed
# The axis starts where the lines move, not in the 52 flat days before.
chart, trimmed = B.cumulative_chart(long)
assert trimmed, "a flat lead-in is cut"
since = datetime.strptime(re.search(r"Running totals by day since (\d+ \w+)", chart).group(1) + " 2026", "%d %b %Y").date()
rises = min(date.fromisoformat(d) for d, r in long.items() if r["times"][2] > .05 * 155_555)
assert d0 + timedelta(days=45) <= since < rises, (since, rises)
assert min(geometry(chart)[3]) >= 52 - .05, "nothing drawn left of the axis"
# History that moves from the first day is shown whole, and the page offers
# all time only when it cut something.
steady = {(d0 + timedelta(days=i)).isoformat(): {"times": [9_000, None, 100 * i + 500, 50 * i + 300, 50 * i + 300, None, None]}
          for i in range(60)}
assert B.cumulative_chart(steady)[1] is False
assert "All time" not in B.progress_page(idx2, now=datetime(2026, 10, 9, 14, 5))
print("ok")

# edition_backlog counts off the SSD manifests, with nothing on the "media
# disk": the archiveorg-editions and gale-editions rows, the trove-titles rows.
mt = Path(tempfile.mkdtemp())
try:
    (mt / "dl" / ".manifest").mkdir(parents=True)
    (mt / "dl" / "trove").mkdir()
    man = mt / "dl" / ".manifest"
    (man / "archiveorg-editions.jsonl").write_text('{"edition": "GaleTelegraph1975UKEnglish/1975-03-04", "at": 1}\n')
    (man / "gale-editions.jsonl").write_text(
        '{"edition": "GaleTelegraph1975UKEnglish/1975-03-04", "at": 1}\n'
        '{"edition": "GaleTelegraph1975UKEnglish/1975-03-05", "at": 1}\n')
    (man / "trove-titles.jsonl").write_text(
        '{"article": "1", "title": "x", "at": 1}\n{"article": "2", "title": "y", "at": 1}\n')
    (man / "trove-titles.complete").write_text("{}\n")
    (mt / "dl" / "trove" / "filed.jsonl").write_text('{"article": "1", "inputs": "a"}\n')
    code = ("import downloads, edition_backlog as E\n"
            "print([e[2] for e in E._editions(downloads.ARCHIVE_ORG)], E.trove_counts(downloads.TROVE))")
    got = subprocess.run([sys.executable, "-c", code], cwd=REPO / "tools", stdout=subprocess.PIPE, text=True,
                         env={**os.environ, "CT_DOWNLOADS": str(mt / "dl")}).stdout.strip()
finally:
    shutil.rmtree(mt, ignore_errors=True)
if got != "['1975-03-04', '1975-03-05'] [2, 1, 0, 1]":
    print(f"FAIL edition_backlog off the manifests: {got}")
    sys.exit(1)
print("edition_backlog off the manifests: ok")

# annotate_dates reads a batch's ids from the old subject and the new body.
import progress, progress_record
_repo = tempfile.mkdtemp(dir=TMPDIR)
_g = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=_repo, check=True, capture_output=True)
_g("init", "-q")
for _m in ("Annotate solo-1", "Annotate 2 puzzles: old-1 old-2",
           "Annotate 3 puzzles\n\nnew-1 new-2\nnew-3\n\nProvenance: x y z"):
    _g("commit", "-q", "--allow-empty", "-m", _m)
_saved, progress.ROOT = progress.ROOT, _repo
try:
    _first = progress_record.annotate_dates()
finally:
    progress.ROOT = _saved
if sorted(_first) != ["new-1", "new-2", "new-3", "old-1", "old-2", "solo-1"]:
    print(f"FAIL annotate_dates: {sorted(_first)}")
    sys.exit(1)
print("annotate_dates, old and new batch forms: ok")
