#!/bin/bash
# Does tools/fetch_archive_org_editions.py retry a 5xx only within the
# edition's ITEM_SECONDS, then raise so the run moves on? Does an edition
# whose text shows no daily crossword title also fetch the leaves the paper
# prints it on? Offline: urlopen is stubbed.
#
#     bash tools/test_fetch_archive_org_editions.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$REPO/tools" <<'PY'
import contextlib, io, sys, tempfile, time, urllib.error
sys.path.insert(0, sys.argv[1])
import fetch_archive_org_editions as fa
fa.RETRY_WAITS = (0, 0, 0)
calls = []
def script(*steps):
    it = iter(steps); calls.clear()
    def urlopen(req, timeout):
        calls.append(req.full_url); s = next(it)
        if isinstance(s, Exception): raise s
        return contextlib.nullcontext(io.BytesIO(s))
    fa.urllib.request.urlopen = urlopen
def e500():
    return urllib.error.HTTPError("u", 500, "boom", {}, None)
fails = 0
def check(what, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + what, file=sys.stderr); fails += not ok
fx = fa.Fetcher(tempfile.mkdtemp(), 0)
with contextlib.redirect_stdout(io.StringIO()):
    script(e500(), e500(), b"fine")
    check("500s retried within the edition's time", fx.get("https://x/a", "a") == b"fine" and len(calls) == 3)
    fx.deadline = time.monotonic() - 1
    script(e500(), b"never")
    try: fx.get("https://x/b", "b"); code = None
    except urllib.error.HTTPError as e: code = e.code
    check("no retry past the edition's deadline", code == 500 and len(calls) == 1)
    script(urllib.error.URLError("refused"), b"never")
    try: fx.get("https://x/c", "c"); msg = ""
    except urllib.error.URLError as e: msg = str(e)
    check("network error past the deadline raises too", "refused" in msg and len(calls) == 1)

# Page selection: an edition whose text shows no daily crossword title also
# fetches its last leaf and the leaves its item's other editions print the
# crossword on; one whose text shows the title fetches only that page.
import collections, json, os
item = tempfile.mkdtemp()
for name, leaves, leaf in (("1980-04-15_1", 28, 27), ("1980-04-17_3", 30, 29), ("1980-04-18_4", 28, 21)):
    os.makedirs(f"{item}/{name}")
    with open(f"{item}/{name}/pages.json", "w") as f:
        json.dump({"leaves": leaves, "crossword_pages": [
            {"leaf": leaf, "headings": ["Times Crossword Puzzle No 15,138"]},
            {"leaf": 5, "headings": ["CONCISE CROSSWORD NO 2157"]}]}, f)
os.makedirs(f"{item}/1980-04-16_2")
prior = fa.prior_leaves(f"{item}/1980-04-16_2", 28)
check("prior leaves: the last, and the siblings' crossword leaves front and back", prior == [21, 27])
check("a sibling's Concise page is no prior", 5 not in prior)
page = lambda t: (100, 200, t)
blank = [page("news " * 60)] * 28
hits = fa.crossword_hits(blank, prior)
check("no page detected: the prior leaves are fetched, marked prior",
      [h["leaf"] for h in hits] == [21, 27] and all(h["prior"] for h in hits))
concise = list(blank); concise[5] = page("CONCISE CROSSWORD NO 2157\nACROSS\n1 Dog (3)")
hits = fa.crossword_hits(concise, prior)
check("only a Concise page detected: the prior leaves are fetched beside it",
      [h["leaf"] for h in hits] == [5, 21, 27] and not hits[0].get("prior"))
sol = list(blank); sol[9] = page("Solution of Puzzle No 15,138 ACROSS DOWN" + " (5)" * 20)
check("only the solution heading detected: the prior leaves are fetched too",
      [h["leaf"] for h in fa.crossword_hits(sol, prior)] == [9, 21, 27])
cryptic = list(blank); cryptic[13] = page("Times Crossword Puzzle No 15,139\nACROSS\n1 Dog (3)")
check("the daily title detected: no prior leaves",
      [h["leaf"] for h in fa.crossword_hits(cryptic, prior)] == [13])
ad = list(blank); ad[27] = page("CROSSWORD ENTHUSIASTS: Times Crossword Book 12,000 copies ACROSS")
check("a crossword book advert is no title", [h["leaf"] for h in fa.crossword_hits(ad, prior)] == [21, 27])
dense = list(blank); dense[11] = page("1 Garbled clue (5)\n" * 12); dense[3] = page("news " * 60 + "a film (5) " * 4)
hits = fa.crossword_hits(dense, prior)
check("no title and no headings: the page densest with clue counts is fetched too, marked dense",
      [(h["leaf"], h.get("dense")) for h in hits] == [(11, True), (21, None), (27, None)])
sparse = list(blank); sparse[11] = page("news " * 60 + "1 Garbled clue (5)\n" * (fa.DENSE_ENUMS - 1))
check("a page with fewer counts than DENSE_ENUMS is not",
      [h["leaf"] for h in fa.crossword_hits(sparse, prior)] == [21, 27])
ut = list(blank); ut[17] = page("FT UNIT TRUST INFORMATION SERVICE\n" + "Authorised Unit Trusts 12.3 45.6 " * 10)
check("no title: the unit trust page is fetched too, marked unit_trust",
      [(h["leaf"], h.get("unit_trust")) for h in fa.crossword_hits(ut, prior)] == [(17, True), (21, None), (27, None)])
check("a titled page found: no unit trust page",
      [h["leaf"] for h in fa.crossword_hits([*cryptic[:17], ut[17], *cryptic[18:]], prior)] == [13])
check("a titled page found: no dense page",
      [h["leaf"] for h in fa.crossword_hits([*cryptic[:11], dense[11], *cryptic[12:]], prior)] == [13])

# An item holding one edition alone (the 1930 Times: an item an issue) counts
# the crossword leaves of the items nearest it by date named like it; a done
# edition with no title and no text-shown page among those leaves is due again.
root = tempfile.mkdtemp()
def edition(item, leaves, hits):
    os.makedirs(f"{root}/{item}/{item}")
    with open(f"{root}/{item}/{item}/pages.json", "w") as f:
        json.dump({"leaves": leaves, "crossword_pages": hits}, f)
    return f"{root}/{item}/{item}"
title = ["THE TIMES CROSSWORD PUZZLE No. 12"]
for i, (day, leaf) in enumerate((("02-14", 6), ("02-15", 4), ("02-18", 6), ("02-19", 6))):
    edition(f"per_times_the-times_1930-{day}_{45437 + i}", 26, [{"leaf": leaf, "headings": title}])
edition("per_times_the-times_1930-06-02_45528", 26, [{"leaf": 9, "headings": title}] * 3)
edition("per_sunday-times_sunday-times_1930-02-16_5575", 26, [{"leaf": 11, "headings": title}])
fa.NEIGHBOURS = 4
lone = edition("per_times_the-times_1930-02-17_45439", 26, [{"leaf": 5, "dense": True}, {"leaf": 25, "prior": True}])
prior = fa.prior_leaves(lone, 26)
check("an item's lone edition: the nearest same-named items' crossword leaves are prior",
      {4, 6, 25} <= set(prior) and not {9, 11} & set(prior))
check("lone edition fetched dense and last leaves only: due again", fa.prior_unfetched(lone))
dense6 = edition("per_times_the-times_1930-03-24_45469", 26, [{"leaf": 6, "dense": True}, {"leaf": 25, "prior": True}])
check("lone edition whose leaf 6 is only the densest: due again", fa.prior_unfetched(dense6))
shown = edition("per_times_the-times_1930-02-20_45441", 26, [{"leaf": 6, "headings": ["CROSSWORD PUZZLE"]}, {"leaf": 25, "prior": True}])
check("lone edition whose text shows a crossword on a common leaf: not due", not fa.prior_unfetched(shown))
whole = edition("per_times_the-times_1930-02-21_45442", 26, [{"leaf": n, "prior": True} for n in prior])
check("lone edition holding every prior leaf: not due", not fa.prior_unfetched(whole))

# An item mixing edition sizes: the leaf its same-sized siblings print the
# crossword on is prior and makes a done edition lacking it due (1998-11-26,
# 56 leaves: leaf 27; the 52-leaf majority print it on leaf 25). The Times
# Two title is no daily one: it neither stops the search nor votes.
mixed = tempfile.mkdtemp()
def sized(name, leaves, hits):
    os.makedirs(f"{mixed}/{name}")
    with open(f"{mixed}/{name}/pages.json", "w") as f:
        json.dump({"leaves": leaves, "crossword_pages": hits}, f)
    return f"{mixed}/{name}"
daily = ["TIMES CROSSWORD NO 20,956"]
two = ["CROSSWORD 747 In association with BRITI"]
for i in range(5):
    sized(f"1998-11-{10 + i}_{i}", 52, [{"leaf": 25, "headings": daily}, {"leaf": 51, "headings": two}])
for i in range(4):
    sized(f"1998-10-{10 + i}_{i}", 52, [{"leaf": 23, "headings": daily}])
for i in range(fa.SIZED_AGREE):
    sized(f"1998-11-{20 + i}_{i}", 56, [{"leaf": 27, "headings": daily}])
sized("1998-11-01_0", 56, [{"leaf": 31, "headings": daily}])
big = sized("1998-11-26_9", 56, [{"leaf": n, "prior": True} for n in (23, 25, 29, 31, 55)])
check("a sibling of its own size votes its leaf prior", 27 in fa.prior_leaves(big, 56))
check("the majority size's leaf stays prior", 25 in fa.prior_leaves(big, 56))
check("mirror: one same-sized sibling is no vote", 31 not in fa.prior_leaves(big, 56))
check("an edition lacking its same-sized siblings' leaf: due again", fa.prior_unfetched(big))
small = sized("1998-11-25_9", 52, [{"leaf": n, "prior": True} for n in fa.prior_leaves(f"{mixed}/x", 52)])
check("mirror: an edition holding its own size's leaves: not due", not fa.prior_unfetched(small))
# One plan (load_done) stats each sibling's pages.json once, not once per
# edition per crossword_leaves call, and reaches the same verdicts.
eds = sorted(f"{mixed}/{n}" for n in os.listdir(mixed))
apart = [fa.prior_unfetched(d) for d in eds]
stats, real_stat = collections.Counter(), os.stat
os.stat = lambda p, *a, **k: (stats.update([os.fspath(p)]), real_stat(p, *a, **k))[1]
try:
    with fa.one_pass():
        together = [fa.prior_unfetched(d) for d in eds]
finally:
    os.stat = real_stat
check("one pass: the same verdicts as edition by edition", together == apart and any(apart))
check("one pass: each pages.json stat'd once", max(stats.values()) == 1 and f"{big}/pages.json" in stats)
check("a Times Two title is no daily title", not fa.titled({"headings": two}))
check("mirror: the daily title still is", fa.titled({"headings": daily}))
check("Times Two pages cast no vote", 51 not in fa.crossword_leaves(big)[0])
check("a Times Two page on a common leaf is no shown crossword: due again",
      fa.prior_unfetched(sized("1996-04-10_9", 52, [{"leaf": 25, "enums": 21, "headings": two}])))
check("mirror: a page showing an untitled crossword there is: not due",
      not fa.prior_unfetched(sized("1996-04-11_9", 52, [{"leaf": 25, "enums": 21, "headings": []}])))
t2 = [page("news " * 60)] * 48
t2[47] = page("SOLUTION TO TIMES TWO CROSSWORD 747 In association with BRITISH MIDLAND ACROSS 1 Bath (4) 2 Cat (3) 3 Dog (3) 4 Ant (3) 5 Bee (3) 6 Cow (3)")
hits = fa.crossword_hits(t2, [23, 47])
check("only a Times Two title on the pages: the prior leaves are fetched too",
      [h["leaf"] for h in hits] == [23, 47] and hits[0].get("prior") and not hits[1].get("prior"))

# Listings: a PDF archive.org never OCR'd is an edition, read by image;
# a run caches every yearly item's listing before it fetches any edition.
scan = "Image Container PDF"
meta = {"files": [{"name": "Apr 01 1981, Financial Times, #28435, UK (en).pdf", "format": scan},
                  {"name": "Apr 02 1981, Financial Times, #28436, UK (en).pdf", "format": scan},
                  {"name": "Apr 02 1981, Financial Times, #28436, UK (en)_djvu.txt"},
                  {"name": "Apr 02 1981, Financial Times, #28436, UK (en)_text.pdf", "format": "Additional Text PDF"},
                  {"name": "listener_1933-11-01_10_251_encrypted.pdf", "format": "ACS Encrypted PDF"}]}
check("a scan PDF with no _djvu.txt is an edition, listed once beside one with text; "
      "an encrypted or text PDF is none",
      fa.editions_of(meta) == ["Apr 01 1981, Financial Times, #28435, UK (en)",
                               "Apr 02 1981, Financial Times, #28436, UK (en)"])
check("the yearly groups are the one-uploader ones",
      {"ft", "times", "guardian", "telegraph"} <= fa.YEARLY_GROUPS
      and not {"pub_times", "listener"} & fa.YEARLY_GROUPS)
out = tempfile.mkdtemp()
os.makedirs(f"{out}/items")
with open(f"{out}/items/_group_ft.json", "w") as f:
    json.dump([{"identifier": f"FinancialTimes{y}UKEnglish", "title": f"Financial Times , {y}, UK, English"}
               for y in (1980, 1981)], f)
meta_bytes = json.dumps(meta).encode()
script(meta_bytes, meta_bytes)
sys.argv = ["fetch", "--out", out, "--group", "ft", "--limit", "0", "--delay", "0"]
with contextlib.redirect_stdout(io.StringIO()):
    fa.main()
check("a run lists every yearly item before its first edition",
      all(os.path.exists(f"{out}/items/FinancialTimes{y}UKEnglish.json") for y in (1980, 1981))
      and len(calls) == 2)

# A run is idempotent and bounded: done.tsv at the current DETECTOR_VERSION
# is skipped, an older version is due again, and --seconds starts nothing past
# its end. Offline: the group search and the item's metadata are cached.
import json, os, subprocess, tempfile
out = tempfile.mkdtemp()
os.makedirs(os.path.join(out, "items"))
item = "NewsUK1980UKEnglish"
with open(os.path.join(out, "items", "_group_times.json"), "w") as f:
    json.dump([{"identifier": item, "title": "The Times , 1980, UK, English"}], f)
eds = [f"Jan 0{d} 1980, The Times, #6000{d}, UK (en)" for d in (2, 3, 4)]
with open(os.path.join(out, "items", item + ".json"), "w") as f:
    json.dump({"files": [{"name": e + "_djvu.txt"} for e in eds]}, f)
with open(os.path.join(out, "done.tsv"), "w") as f:
    f.write(f"{item}\t{eds[0]}\t{fa.DETECTOR_VERSION}\n{item}\t{eds[1]}\t{fa.DETECTOR_VERSION - 1}\n")
def run(*extra):
    r = subprocess.run([sys.executable, fa.__file__, "--out", out,
                        "--group", "times", *extra], capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr
rc, log = run("--seconds", "1e-9")
check("--seconds past: no item opened, nothing fetched",
      rc == 0 and "0 editions this run; left for the next run: 0 editions of the item it stopped in, "
      "and 1 items not opened" in log and "FAIL" not in log)
rc, log = run("--list")
check("an old-version and an undone edition are due", rc == 0 and "3 editions\t2 to do" in log)
with open(os.path.join(out, "done.tsv"), "a") as f:
    f.write(f"{item}\t{eds[1]}\t{fa.DETECTOR_VERSION}\n{item}\t{eds[2]}\t{fa.DETECTOR_VERSION}\n")
rc, log = run()
check("nothing due: finishes with no request", rc == 0 and "finished: 0 editions" in log, )

# The "archive.org looks down" stop counts only connection errors, timeouts
# and 5xx; an edition's own failure (an empty reply, a 404) resets the count.
http = lambda c: urllib.error.HTTPError("u", c, "x", {}, None)
check("outage: 5xx, refused, timeout",
      all(fa.outage(e) for e in (http(500), http(503), urllib.error.URLError("refused"), TimeoutError(), ConnectionResetError())))
check("no outage: 404, 429, an empty reply, a parse error",
      not any(fa.outage(e) for e in (http(404), http(429), RuntimeError("no OBJECT"), fa.PageNumbering("empty"), ValueError())))
def streak(errors):
    r = fa.Run(tempfile.mkdtemp())
    fx.refreshed["i"] = time.monotonic()  # a 404 asks for no fresh metadata
    def boom(*a):
        raise next(it)
    it = iter(errors); real = fa.fetch_edition; fa.fetch_edition = boom
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in errors:
                r.edition(fx, "i", {}, "n")
    finally:
        fa.fetch_edition = real
    return r.stop
check("per-edition failures never stop the run", not streak([RuntimeError("no OBJECT")] * 20 + [http(404)] * 5))
check("FAILURES_IN_A_ROW 5xx stop it", streak([http(502)] * fa.FAILURES_IN_A_ROW))
check("a 404 between 5xx resets the count",
      not streak([http(502)] * (fa.FAILURES_IN_A_ROW - 1) + [http(404)] + [http(502)] * (fa.FAILURES_IN_A_ROW - 1)))

# Groups take turns: one item each, so a long group cannot starve the next.
check("groups share editions, not items",
      fa.by_editions([["t1", "t2"], ["l1", "l2", "l3", "l4"], ["d1", "l5"]], lambda x: 3 if x[0] == "t" else 0 if x[0] == "d" else 1)
      == ["t1", "l1", "d1", "l5", "l2", "l3", "t2", "l4"])

# Leaf numbering: a scan starting with a colour card has djvu page k on leaf
# k+1; the OBJECT's PAGE param places it, and the per-page endpoint's empty
# reply or other-leaf reply sends the edition to the whole djvu.xml.
obj = lambda n, t: (f'<OBJECT width="10" height="20"><PARAM name="PAGE" value="ed_{n:04d}.djvu"/>'
                    f'<LINE><WORD>{t}</WORD></LINE></OBJECT>')
xml = ("<DjVuXML><BODY>" + obj(1, "one") + obj(2, "two") + "</BODY></DjVuXML>").encode()
check("page_texts places each OBJECT on its scan leaf",
      fa.page_texts(xml) == [(0, 0, ""), (10, 20, "one"), (10, 20, "two")])
meta = {"server": "s", "dir": "/d"}
for reply, what in ((b"", "an empty words reply"), (obj(2, "two").encode(), "a words reply for another leaf")):
    script(reply)
    try: fa.sparse_djvu_xml(fx, meta, "ed", "ed", {1}, 3); raised = False
    except fa.PageNumbering: raised = True
    check(what + " raises PageNumbering", raised)
script(obj(1, "one").encode())
check("a words reply for its own leaf is kept",
      fa.sparse_djvu_xml(fx, meta, "ed", "ed", {1}, 3)[1] == {1: (10, 20)})
# An edition whose cached djvu.xml.gz has an OBJECT whose PAGE names a later
# leaf holds another leaf's words. It is due again at the same DETECTOR_VERSION, and its
# re-fetch takes the whole djvu.xml, stored so the n-th OBJECT is leaf n.
import gzip
check("scan_aligned pads the skipped colour card",
      fa.misplaced(xml) and not fa.misplaced(fa.scan_aligned(xml))
      and fa.scan_aligned(xml).count(b"<OBJECT") == 3 and fa.page_texts(fa.scan_aligned(xml)) == fa.page_texts(xml))
check("an aligned djvu.xml is left as it is", fa.scan_aligned(fa.scan_aligned(xml)) == fa.scan_aligned(xml))
out = tempfile.mkdtemp()
os.makedirs(os.path.join(out, "items"))
eds = ["listener_1932-10-05_8_195", "listener_1932-10-12_8_196"]
with open(os.path.join(out, "items", "_group_listener.json"), "w") as f:
    json.dump([{"identifier": e, "title": "Listener 1932"} for e in eds], f)
for e in eds:
    with open(os.path.join(out, "items", e + ".json"), "w") as f:
        json.dump({"server": "s", "dir": "/d", "files": [{"name": e + x} for x in ("_djvu.txt", "_jp2.zip")]}, f)
    with open(os.path.join(out, "done.tsv"), "a") as f:
        f.write(f"{e}\t{e}\t{fa.DETECTOR_VERSION}\n")
    d = os.path.join(out, e, e)
    os.makedirs(d)
    words = (b"<DjVuXML><BODY><OBJECT width=\"0\" height=\"0\"></OBJECT>"
             + obj(2 if e == eds[0] else 1, "w").encode() + b"</BODY></DjVuXML>")
    with open(os.path.join(d, "djvu.xml.gz"), "wb") as f:
        f.write(gzip.compress(words))
    with open(os.path.join(d, "pagetext.json.gz"), "wb") as f:
        f.write(gzip.compress(json.dumps({"texts": ["", "x"], "words": {"1": [10, 20]}}).encode()))
log = subprocess.run([sys.executable, fa.__file__, "--out", out, "--group", "listener", "--list"],
                     capture_output=True, text=True, timeout=60).stdout
check("done before the leaf check, words on another leaf: due again",
      f"{eds[0]}\t1 editions\t1 to do" in log and f"{eds[1]}\t1 editions\t0 to do" in log)
whole = ("<DjVuXML><BODY>" + obj(1, "news") + obj(2, "Crossword No. 132 ACROSS") + "</BODY></DjVuXML>").encode()
script(b"text", whole)
d = os.path.join(out, eds[0], eds[0])
open(os.path.join(d, "leaf_0002.jpg"), "wb").close()
fx.out = out
with contextlib.redirect_stdout(io.StringIO()):
    hits = fa.fetch_edition(fx, eds[0], json.load(open(os.path.join(out, "items", eds[0] + ".json"))), eds[0])
with gzip.open(os.path.join(d, "djvu.xml.gz")) as f:
    stored = f.read()
check("its re-fetch takes the whole djvu.xml and places the crossword on its scan leaf",
      [h["leaf"] for h in hits] == [2] and calls[-1].endswith("_djvu.xml")
      and not os.path.exists(os.path.join(d, "pagetext.json.gz"))
      and not fa.misplaced(stored) and not fa.words_misplaced(d))

# An edition held only as an image PDF of 1-bit page scans (FT 1981): the
# page with a grid on it is its crossword page, saved grey at SCAN_WIDTH,
# and the djvu.xml.gz holds an empty OBJECT a page so the filer reads its
# title by image.
from PIL import Image, ImageDraw
def page_scan(grid):
    im = Image.new("1", (1678, 2357), 1)
    dr = ImageDraw.Draw(im)
    dr.rectangle((100, 100, 1500, 120), fill=0)  # a column rule, no grid
    if grid:
        x0, y0, c = 200, 1200, 22  # 15 cells of 22px: ~650px at SCAN_WIDTH
        for k in range(16):
            dr.line((x0, y0 + k * c, x0 + 15 * c, y0 + k * c), fill=0, width=2)
            dr.line((x0 + k * c, y0, x0 + k * c, y0 + 15 * c), fill=0, width=2)
        for r in range(1, 15, 2):
            for col in range(1, 15, 2):
                dr.rectangle((x0 + col * c, y0 + r * c, x0 + (col + 1) * c, y0 + (r + 1) * c), fill=0)
    return im
buf = io.BytesIO()
page_scan(False).save(buf, "PDF", save_all=True, append_images=[page_scan(True), page_scan(False)])
out = tempfile.mkdtemp()
name = "Apr 01 1981, Financial Times, #28435, UK (en)"
meta = {"server": "s", "dir": "/d", "files": [{"name": name + ".pdf", "format": "Image Container PDF"}]}
script(buf.getvalue())
fx.out = out
with contextlib.redirect_stdout(io.StringIO()):
    hits = fa.fetch_edition(fx, "FinancialTimes1981UKEnglish", meta, name)
d = os.path.join(out, "FinancialTimes1981UKEnglish", "1981-04-01_28435")
with gzip.open(os.path.join(d, "djvu.xml.gz")) as f:
    stored = f.read()
leaf = Image.open(os.path.join(d, "leaf_0001.jpg"))
check("an image PDF's grid page is its crossword page, saved grey at SCAN_WIDTH",
      [(h["leaf"], h["pdf"]) for h in hits] == [(1, True)] and calls[-1].endswith(".pdf")
      and leaf.mode == "L" and leaf.width == 3296
      and json.load(open(os.path.join(d, "pages.json")))["leaves"] == 3
      and stored.count(b"<OBJECT") == 3 and b"<WORD" not in stored)

# ---- the queue's units: plan() off the caches alone, fetch_unit() one edition
out = tempfile.mkdtemp()
os.makedirs(os.path.join(out, "items"))
def put(rel, obj, age=0):
    path = os.path.join(out, "items", rel)
    with open(path, "w") as f:
        json.dump(obj, f)
    os.utime(path, (time.time() - age, time.time() - age))
put("_group_times.json", [{"identifier": "NewsUK1980UKEnglish", "title": "The Times , 1980"}])
put("_group_listener.json", [{"identifier": f"listener_{k}", "title": "Listener x"} for k in (1, 2)],
    age=fa.LISTING_SECONDS + 5)
names = [f"Jan 0{k} 1980, The Times, #{k}, UK (en)" for k in (1, 2, 3)]
put("NewsUK1980UKEnglish.json", {"files": [{"name": n + "_djvu.txt"} for n in names]})
put("listener_1.json", {"files": [{"name": "listener_1_djvu.txt"}]})
with open(os.path.join(out, "done.tsv"), "w") as f:
    f.write(f"NewsUK1980UKEnglish\t{names[0]}\t{fa.DETECTOR_VERSION}\n")
def no_network(*a, **k):
    raise AssertionError("plan() asked the network")
fa.urllib.request.urlopen = no_network
units = fa.plan(out, ["times", "listener"])
check("plan: a stale listing first, then the groups an edition each in turn, nothing done, no network",
      [u["rel"] for u in units] == ["_group_listener", f"NewsUK1980UKEnglish/{names[1]}", "listener_1/listener_1",
                                    f"NewsUK1980UKEnglish/{names[2]}", "listener_2"]
      and units[-1]["reason"] == "metadata not cached")
fetched = []
fa.fetch_edition = lambda fx, item, meta, name: fetched.append(name) or [{"leaf": 1, "headings": ["CROSSWORD NO 1"]}]
with contextlib.redirect_stdout(io.StringIO()):
    got = fa.fetch_unit(out, units[1], min_free_gb=0)
check("fetch_unit fetches its one edition and marks it done",
      got == "fetched" and fetched == [names[1]] and fa.edition_done(out, "NewsUK1980UKEnglish", names[1]))
with contextlib.redirect_stdout(io.StringIO()):
    check("an edition already done is current", fa.fetch_unit(out, units[1], min_free_gb=0) == "current")
check("the next plan leaves it out", f"NewsUK1980UKEnglish/{names[1]}" not in [u["rel"] for u in fa.plan(out, ["times"])])
import scan_queue
from pathlib import Path
with scan_queue.source_lock(Path(out) / "done.tsv", f"NewsUK1980UKEnglish/{names[2]}"):
    pid = os.fork()
    if pid == 0:
        with contextlib.redirect_stdout(io.StringIO()):
            os._exit(0 if fa.fetch_unit(out, units[3], min_free_gb=0) == "busy" else 1)
    check("an edition another fetch holds is busy, not fetched twice",
          os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]) == 0 and names[2] not in fetched)
with contextlib.redirect_stdout(io.StringIO()):
    check("under --min-free-gb nothing is fetched", fa.fetch_unit(out, units[3], min_free_gb=1e12) == "disk")
def down(*a, **k):
    raise urllib.error.URLError("refused")
fa.fetch_edition = down
fa.ITEM_SECONDS = 0
with contextlib.redirect_stdout(io.StringIO()):
    check("archive.org down is an outage, logged to failures.tsv",
          fa.fetch_unit(out, units[3], min_free_gb=0) == "outage" and "refused" in open(os.path.join(out, "failures.tsv")).read())
sys.exit(1 if fails else 0)
PY
