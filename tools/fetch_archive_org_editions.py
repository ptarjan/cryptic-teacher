#!/usr/bin/env python3
"""Fetch archive.org newspaper editions' OCR, word positions and crossword page scans.

Usage:
  python3 tools/fetch_archive_org_editions.py --list                 # editions per group
  python3 tools/fetch_archive_org_editions.py                        # everything, Times first
  python3 tools/fetch_archive_org_editions.py --group times --group listener
  python3 tools/fetch_archive_org_editions.py --item NewsUK1998UKEnglish --edition 'Jul 25 1998'
  python3 tools/fetch_archive_org_editions.py --limit 20             # stop after 20 editions
  --out DIR     cache root (default ~/.cache/archive_org_editions)
  --delay S     minimum seconds between one connection's requests (default 1.0)
  --jobs N      editions fetched at once (default 4)
  --min-free-gb N  stop cleanly when the cache disk has less free (default 30)
  --seconds N   start no edition after N seconds; the ones not started are
                counted "left for the next run" (tools/ocr_full_pass.sh runs
                it this way, so the corpus queue fetches in bounded slices)

Sources (GROUPS below), whose items a run opens in turn, one item of each
group then the next, so no group starves the rest within --seconds: the Times 1965/1974-99 full editions
(NewsUK<year>UKEnglish, one item per year holding ~200 editions); the BBC
Listener magazine (pub_listener, one item per issue); the same uploader's
Financial Times, Guardian, Daily/Sunday Telegraph and 1971 Sunday Times; and
archive.org's pub_times / pub_sunday-times (1930 on; the Times crossword began
1 Feb 1930, so earlier issues are skipped).

Leaf N is scan leaf N throughout: the jp2.zip member, the hOCR page index
entry and pages.json's leaf. The djvu.xml and BookReaderGetTextWrapper.php
number only the access-format leaves, so an issue whose scan starts with a
colour card (the Listener's) has its djvu page k on leaf k+1; each OBJECT's
PAGE param ("<edition>_0001.djvu") names its scan leaf, and page_texts places
it there. The per-page endpoint cannot be asked by scan leaf, so when its
reply is empty or names another leaf the edition takes the whole-_djvu.xml
path, and the stored djvu.xml.gz gets an empty OBJECT for each leaf the
djvu.xml skips (scan_aligned), so its n-th OBJECT is leaf n for the filer too.

Layout under --out:
  items/<item>.json           cached /metadata/<item> response
  done.tsv                    item, edition, detector version: finished editions
  failures.tsv                time, item, edition, error (append-only log)
  <item>/<slug>/pagetext.json.gz  the page texts, one string per leaf, from the
                              _hocr_searchtext.txt.gz (detection re-runs from this)
  <item>/<slug>/djvu.xml.gz   per-word page coords, gzipped. Whole-edition _djvu.xml
                              for old and fallback editions; for new ones only the
                              crossword leaves' OBJECTs, the other leaves empty
                              placeholders, so the n-th <OBJECT> is still leaf n
  <item>/<slug>/djvu.txt.gz   _djvu.txt, only in the fallback (no hOCR files)
  <item>/<slug>/pages.json    edition name, leaf count, and each crossword page:
                              leaf, enumeration count, the headings found
                              ("CROSSWORD NO 20,853"), or ocr_empty (below)
  <item>/<slug>/leaf_NNNN.jpg full-resolution scan of each crossword page

<slug> is YYYY-MM-DD_<issue> for the dated multi-edition items and the
identifier itself for one-issue items. The page texts come from the 440 KB
_hocr_searchtext.txt.gz cut by the 600-byte _hocr_pageindex.json.gz (char
offsets per page): a 13 MB _djvu.xml costs minutes at archive.org's ~90 KB/s
per connection. The words' coordinates for each crossword leaf come from
BookReaderGetTextWrapper.php, the reader's one-page djvu.xml (~200 KB, with the
page's width and height). An edition without the two hOCR files (whole years,
e.g. 1985) or whose offsets do not fit, or whose per-page endpoint fails with
a 4xx or by another numbering (above), takes the whole-_djvu.xml path instead; so does one already cached
that way. Leaf N is <edition>_jp2/<edition>_NNNN.jp2 inside the edition's
_jp2.zip.

Page images come from BookReaderImages.php, the reader's per-page endpoint,
which unpacks one leaf of the jp2.zip server-side and returns a JPEG. Never
the whole _jp2.zip: ~120 MB per edition, terabytes in total.

When no page's text shows a crossword, every leaf whose OCR is blank (under
EMPTY_OCR_CHARS) is fetched instead, marked ocr_empty: ABBYY returns nothing
for a page of dense share tables, and the 1980s FT prints its crossword on
one (FT 3 Apr 1985, leaf 41). The filer finds the grid in those by image.

An edition archive.org holds only as an image PDF, never OCR'd (FT 1981:
~12 MB, one 1-bit scan a page, no _djvu.txt and mostly no _jp2.zip), is
read by image (fetch_pdf_edition): each page is searched for a grid-shaped
patch that trove_grid reads as a grid, and those pages are saved greyed and
scaled to the scans' width, marked pdf, beside a djvu.xml.gz of empty
OBJECTs, so the filer reads the title over the grid as on a blank-OCR leaf.

When no page's text holds a daily crossword's numbered title (titled()),
the OCR has garbled it or the page has no text, so the leaves the paper
usually prints it on are fetched too, marked prior: the edition's last leaf
(the 1970s-80s Times back page, ~90% of filed ones) and the PRIOR_LEAVES
commonest crossword leaves of the item's other cached editions, counted both
from the front and from the back (prior_leaves). The filer reads their titles
by image (ocr_titles). An edition none of whose fetched leaves holds a title
is one whose scan lacks the crossword page. So is the page densest with
clue enumerations, DENSE_ENUMS or more, marked dense: the 1970s-80s OCR
loses the title and the ACROSS/DOWN headings of a page whose counts it
keeps (1977-07-22, leaf 21: 64 counts, no heading).

A rerun skips every edition in done.tsv at the current DETECTOR_VERSION,
except one whose per-page words (pagetext.json.gz beside a djvu.xml.gz) hold
an OBJECT on a leaf other than the one its PAGE names (misplaced): the
per-page endpoint gave another leaf's words before the fetcher checked them,
so the edition is fetched again by the whole-djvu.xml path, and its changed
files make the filer read it again.
Bumping DETECTOR_VERSION re-runs detection from the cached djvu.xml and
fetches only the page images it newly finds; no text is downloaded again.

Politeness: archive.org throttles per connection, not per client, so up to
--jobs editions are in flight at once, each one request at a time and at least
--delay seconds between its own requests. A 429 lowers the number allowed in
flight by one (never below 1) for the rest of the run. Every request retries
with backoff (honouring Retry-After) on 429, 5xx and network errors.

No edition holds the queue: retries stop once it has had ITEM_SECONDS, and
an edition whose request then fails is logged to failures.tsv and left
undone for the next run, and the run moves on. FAILURES_IN_A_ROW editions
failing back to back on a connection error, a timeout or a 5xx (outage())
means archive.org itself is down: the run stops with exit 4 and the errors in
its log. Any other failure (a 404, an empty reply) is the edition's own, and
shows archive.org answering, so it resets the count.
"""

import argparse
import collections
import concurrent.futures
import datetime
import gzip
import io
import itertools
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

UA = "cryptic-teacher-fetcher/1.0 (cryptic-teacher@paulisageek.com)"
SAMAAN = 'uploader:"samaan.alshayef@gmail.com"'
DETECTOR_VERSION = 5
#: How many of the leaves its item's other editions print their crossword on
#: an edition with no crossword title in its text also fetches (prior_leaves).
PRIOR_LEAVES = 2
EMPTY_OCR_CHARS = 200
#: The fewest clue enumerations ("(5)", "(3,4)") on the page an edition
#: with no crossword title in its text fetches as its densest (crossword_hits).
DENSE_ENUMS = 10
RETRY_WAITS = (5, 15, 45, 120)
ITEM_SECONDS = 300
FAILURES_IN_A_ROW = 10

# (group, advancedsearch query, title regex that keeps an item, first date kept)
GROUPS = [
    ("times", SAMAAN + " AND identifier:NewsUK*", r"^The Times ,", None),
    ("listener", "collection:pub_listener", r"^Listener ", None),
    ("ft", SAMAAN + " AND identifier:FinancialTimes*", r"^Financial Times ,", None),
    ("guardian", SAMAAN + " AND identifier:TheGuardian*", r"^The Guardian", None),
    ("telegraph", SAMAAN + " AND (identifier:TheDailyTelegraph* OR identifier:SundayTelegraph*)",
     r"Telegraph ,", None),
    ("sunday-times", SAMAAN + " AND identifier:NewsUK*", r"^Sunday Times ,", None),
    ("pub_times", "collection:pub_times", r"^The Times ", "1930-02-01"),
    ("pub_sunday-times", "collection:pub_sunday-times", r"^Sunday Times ", None),
]

#: The groups holding one item a year of ~300 editions, whose listings are
#: cheap to fetch whole (one metadata call an item).
YEARLY_GROUPS = {g[0] for g in GROUPS if g[1].startswith(SAMAAN)}

#: A crossword title with its number ("Times Crossword Puzzle No 14,011",
#: "CROSSWORD No. 8,650", "Crossword Puzzle No"). A front-page index line
#: ("CROSSWORD - 28") has a two-digit page number, so a title needs three.
NUMBERED = re.compile(r"(?i)cross\s?word\W{0,3}(?:puzzle\W{0,3})?(?:no\.?\s*)?\d[\d,.]{2,}|cross\s?word\s+puzzle\s+no")
#: Numbered headings that are not the daily cryptic: its sister puzzles and
#: the book adverts ("CROSSWORD ENTHUSIASTS").
NOT_DAILY = re.compile(r"(?i)concise|jumbo|listener|quick|enthusiast|title|book")
ENUM = re.compile(r"\(\s*\d{1,2}(?:\s*[,\-.]\s*\d{1,2}){0,4}\s*\)")
HEADING = re.compile(
    r"(?i)(?:listener|jumbo|times|cryptic|prize|quick|concise|polymath|mephisto|"
    r"inquisitor|azed|everyman|enigmatic|genius)?\W{0,3}cross\s?word[^\n]{0,30}"
    r"|puzzle\s+no\.?\s*\d[\d,.]*")


class PageNumbering(Exception):
    """The per-page words endpoint numbers this edition's leaves otherwise
    than its scan: the caller takes the whole djvu.xml instead."""


def outage(e):
    """Whether a fetch error shows archive.org down rather than this edition
    failing: no connection, a timeout, or a 5xx."""
    if isinstance(e, urllib.error.HTTPError):
        return e.code >= 500
    return isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError))


def page_leaf(value):
    """The scan leaf a PAGE param's value ("<edition>_0036.djvu") names, or None."""
    m = re.search(r"_(\d+)\.djvu$", value or "")
    return int(m.group(1)) if m else None


def object_leaf(el):
    """The scan leaf a djvu.xml OBJECT holds, from its PAGE param, or None."""
    for p in el.iter("PARAM"):
        if p.get("name") == "PAGE":
            return page_leaf(p.get("value"))
    return None


#: An OBJECT's start, or its PAGE param's value: the tokens object_leaves
#: reads without parsing a 13 MB djvu.xml's words.
OBJECT_OR_PAGE = re.compile(rb'<OBJECT\b|<PARAM name="PAGE" value="([^"]*)"')


def object_leaves(xml):
    """[(byte offset, PAGE leaf or None)] of each OBJECT in a djvu.xml, in order."""
    out = []
    for m in OBJECT_OR_PAGE.finditer(xml):
        if m.group(1) is None:
            out.append((m.start(), None))
        elif out and out[-1][1] is None:
            out[-1] = (out[-1][0], page_leaf(m.group(1).decode("utf-8", "replace")))
    return out


def misplaced(xml):
    """Whether a djvu.xml holds an OBJECT at a position other than the scan
    leaf its PAGE names."""
    return any(leaf is not None and leaf != n for n, (_, leaf) in enumerate(object_leaves(xml)))


def scan_aligned(xml):
    """The djvu.xml with an empty OBJECT before each one whose PAGE names a
    later leaf than its position (a skipped colour card), so the n-th OBJECT
    is scan leaf n."""
    parts, at, n = [], 0, 0
    for start, leaf in object_leaves(xml):
        if leaf is not None and leaf > n:
            parts += [xml[at:start], b'<OBJECT width="0" height="0"></OBJECT>\n' * (leaf - n)]
            at, n = start, leaf
        n += 1
    return xml if not parts else b"".join(parts) + xml[at:]


def words_misplaced(d):
    """Whether an edition dir's per-page words were stored on another leaf
    than the one they belong to (misplaced)."""
    xml_path = os.path.join(d, "djvu.xml.gz")
    if not (os.path.exists(os.path.join(d, "pagetext.json.gz")) and os.path.exists(xml_path)):
        return False
    with gzip.open(xml_path) as f:
        return misplaced(f.read())


class Fetcher:
    def __init__(self, out, delay, jobs=1):
        self.out = out
        self.delay = delay
        #: Per thread: when its last request ended, and the time.monotonic()
        #: after which one of its failed requests is not retried.
        self.local = threading.local()
        self.allowed = jobs
        self.cond = threading.Condition()
        self.in_flight = 0

    @property
    def deadline(self):
        return getattr(self.local, "deadline", float("inf"))

    @deadline.setter
    def deadline(self, value):
        self.local.deadline = value

    def _throttled(self):
        with self.cond:
            if self.allowed > 1:
                self.allowed -= 1
                log(f"  HTTP 429: at most {self.allowed} requests in flight from now on")

    def get(self, url, what, retry=True):
        """GET url politely; returns bytes, raises HTTPError on 404/403/400.

        retry=False raises on the first failure instead of waiting and retrying,
        and so does any failure whose wait would end past self.deadline.
        """
        for attempt, wait in enumerate(RETRY_WAITS + (None,) if retry else (None,)):
            gap = getattr(self.local, "last", 0.0) + self.delay - time.monotonic()
            if gap > 0:
                time.sleep(gap)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with self.cond:
                    self.cond.wait_for(lambda: self.in_flight < self.allowed)
                    self.in_flight += 1
                try:
                    with urllib.request.urlopen(req, timeout=120) as r:
                        data = r.read()
                finally:
                    with self.cond:
                        self.in_flight -= 1
                        self.cond.notify_all()
                self.local.last = time.monotonic()
                return data
            except urllib.error.HTTPError as e:
                self.local.last = time.monotonic()
                if e.code == 429:
                    self._throttled()
                if e.code not in (429, 500, 502, 503, 504) or wait is None:
                    raise
                wait = max(wait, int(e.headers.get("Retry-After") or 0))
                if time.monotonic() + wait > self.deadline:
                    raise
                err = f"HTTP {e.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                self.local.last = time.monotonic()
                if wait is None or time.monotonic() + wait > self.deadline:
                    raise
                err = f"{type(e).__name__}: {e}"
            log(f"  retry {attempt + 1} in {wait}s: {what}: {err}")
            time.sleep(wait)

    def search(self, query):
        params = {"q": query, "fl[]": ["identifier", "title", "date"], "rows": 5000,
                  "output": "json", "sort[]": "identifier asc"}
        url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params, doseq=True)
        return json.loads(self.get(url, "search " + query))["response"]["docs"]

    def metadata(self, item):
        path = os.path.join(self.out, "items", item + ".json")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        meta = json.loads(self.get("https://archive.org/metadata/" + item, "metadata " + item))
        if not meta.get("files"):
            raise RuntimeError(f"/metadata/{item} has no files (dark or missing item)")
        write_atomic(path, json.dumps(meta).encode())
        return meta


def log(msg):
    print(time.strftime("%H:%M:%S ") + msg, flush=True)


def write_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def editions_of(meta):
    """Edition base names in an item, in date order: one per _djvu.txt, and
    one per image PDF archive.org never OCR'd (FinancialTimes1981UKEnglish:
    285 PDFs, no _djvu.txt), which fetch_edition reads by image."""
    names = {f["name"][: -len("_djvu.txt")] for f in meta["files"] if f["name"].endswith("_djvu.txt")}
    names |= {f["name"][: -len(".pdf")] for f in meta["files"]
              if f["name"].endswith(".pdf") and not f["name"].endswith("_text.pdf")}
    return sorted(names, key=lambda n: (edition_date(n) or "", n))


def edition_date(name):
    m = re.match(r"([A-Z][a-z]{2}) (\d{2}) (\d{4}),", name)
    if m:
        try:
            return datetime.date(*time.strptime(" ".join(m.groups()), "%b %d %Y")[:3]).isoformat()
        except ValueError:
            return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    return m.group(1) if m else None


def slug_of(item, name):
    if name == item:
        return item
    date = edition_date(name)
    issue = re.search(r"#(\d+)", name)
    if date:
        return date + ("_" + issue.group(1) if issue else "")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")


def page_texts(xml_bytes):
    """[(width, height, text)] per scan leaf, from a djvu.xml; a leaf it has
    no OBJECT for (a colour card) is (0, 0, "")."""
    pages = []
    for _, el in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if el.tag != "OBJECT":
            continue
        leaf = object_leaf(el)
        while leaf is not None and len(pages) < leaf:
            pages.append((0, 0, ""))
        lines = []
        for line in el.iter("LINE"):
            lines.append(" ".join((w.text or "") for w in line.iter("WORD")))
        pages.append((int(el.get("width") or 0), int(el.get("height") or 0), "\n".join(lines)))
        el.clear()
    return pages


def detect(text):
    """(score, enumerations, headings) for one page; score >= 1 means a crossword.

    A numbered crossword title ("Times Crossword Puzzle No 14,011", "LISTENER
    CROSSWORD No 3472", "Jumbo Crossword 177", 1930's "CROSSWORD PUZZLE No.")
    is enough on its own: the 1970s OCR turns the clue list itself to noise.
    So is "PUZZLE No. 309." over an ACROSS heading (the 1930 Sunday Times).
    Otherwise a crossword word plus an ACROSS heading or a few enumerations
    "(5)", "(3,4)", or a page dense with enumerations under an across/down pair. A front-page index line
    ("CROSSWORD - 28") has a two-digit page number, so a title needs three.
    """
    enums = len(ENUM.findall(text))
    headings = sorted({re.sub(r"\s+", " ", m.group(0)).strip() for m in HEADING.finditer(text)})
    numbered = bool(NUMBERED.search(text))
    titled = bool(re.search(r"(?i)cross\s?word", text))
    across = bool(re.search(r"\bACROSS\b|\bAcross\b", text))
    numbered = numbered or (across and bool(re.search(r"(?i)puzzle\s+no\.?\s*\d", text)))
    down = bool(re.search(r"\bDOWN\b|\bDown\b", text))
    score = 0
    if numbered or (titled and (across or enums >= 6)) or (across and down and enums >= 15):
        score = 1
    return score, enums, headings[:12]


def load_done(out):
    done = set()
    path = os.path.join(out, "done.tsv")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 3 and parts[2] == str(DETECTOR_VERSION) \
                        and not words_misplaced(os.path.join(out, parts[0], slug_of(parts[0], parts[1]))):
                    done.add((parts[0], parts[1]))
    return done


def append(out, fname, fields):
    with open(os.path.join(out, fname), "a") as f:
        f.write("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in fields) + "\n")


def fetch_first(fx, bases, suffix, what):
    for i, base in enumerate(bases):
        last = i == len(bases) - 1
        try:
            return fx.get(base + suffix, what, retry=last)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if last:
                raise
            log(f"  {what}: {base.split('/')[2]} failed ({e}); trying the next server")


def hocr_page_texts(fx, bases, name):
    """[text] per leaf from the hOCR search text cut by the page index, or None
    when the offsets do not fit the text (the caller then takes the djvu.xml)."""
    index = json.loads(gzip.decompress(fetch_first(fx, bases, "_hocr_pageindex.json.gz", name + " page index")))
    text = gzip.decompress(fetch_first(fx, bases, "_hocr_searchtext.txt.gz", name + " search text")).decode("utf-8", "replace")
    if not index or index[0][0] != 0 or any(a[1] != b[0] for a, b in itertools.pairwise(index)) \
            or index[-1][1] != len(text):
        return None
    return [re.sub(r"[ \t]+", " ", text[start:end]) for start, end, *_ in index]


def sparse_djvu_xml(fx, meta, item, name, leaves, count):
    """(djvu.xml bytes with only `leaves` filled in, {leaf: (width, height)}):
    each leaf's OBJECT is BookReaderGetTextWrapper.php's one-page djvu.xml."""
    parts, dims = [b'<?xml version="1.0" encoding="UTF-8"?>\n<DjVuXML><BODY>\n'], {}
    for leaf in range(count):
        if leaf not in leaves:
            parts.append(b'<OBJECT width="0" height="0"></OBJECT>\n')
            continue
        url = f"https://{meta['server']}/BookReader/BookReaderGetTextWrapper.php?" + urllib.parse.urlencode(
            {"path": f"{meta['dir']}/{name}_djvu.xml", "mode": "djvu_xml", "page": leaf})
        data = fx.get(url, f"{name} page {leaf} words")
        start = data.find(b"<OBJECT")
        if not data.strip():
            raise PageNumbering(f"page {leaf} words: empty reply, past the djvu.xml's last page")
        if start < 0 or b"</OBJECT>" not in data:
            raise RuntimeError(f"page {leaf} words: no OBJECT in the reply ({data[:60]!r})")
        el = ET.fromstring(data[start:data.rindex(b"</OBJECT>") + len(b"</OBJECT>")])
        if object_leaf(el) not in (None, leaf):
            raise PageNumbering(f"page {leaf} words: the reply holds leaf {object_leaf(el)}")
        dims[leaf] = (int(el.get("width") or 0), int(el.get("height") or 0))
        parts.append(data[start:data.rindex(b"</OBJECT>") + len(b"</OBJECT>")] + b"\n")
    parts.append(b"</BODY></DjVuXML>\n")
    return b"".join(parts), dims


def titled(hit):
    """Whether a crossword_pages hit's text holds a daily crossword's numbered title."""
    return any(NUMBERED.search(h) and not NOT_DAILY.search(h) for h in hit.get("headings") or ())


def prior_leaves(edition_dir, count):
    """The leaves of an edition of `count` leaves its crossword most likely
    lies on: its last, and the PRIOR_LEAVES commonest leaves holding a titled
    crossword in its item's other cached editions, by leaf number and by
    distance from the back."""
    fronts, backs = collections.Counter(), collections.Counter()
    for pj in Path(edition_dir).parent.glob("*/pages.json"):
        if pj.parent.name == Path(edition_dir).name:
            continue
        try:
            pages = json.loads(pj.read_text())
        except (OSError, ValueError):
            continue
        for hit in pages.get("crossword_pages") or ():
            if titled(hit):
                fronts[hit["leaf"]] += 1
                backs[pages["leaves"] - 1 - hit["leaf"]] += 1
    leaves = {count - 1} | {n for n, _ in fronts.most_common(PRIOR_LEAVES)} \
        | {count - 1 - n for n, _ in backs.most_common(PRIOR_LEAVES)}
    return sorted(n for n in leaves if 0 <= n < count)


def crossword_hits(pages, prior=()):
    """The pages.json crossword_pages for [(width, height, text)] pages; when
    none holds a crossword title, the `prior` leaves (prior_leaves) too."""
    hits = []
    for leaf, (w, h, text) in enumerate(pages):
        score, enums, headings = detect(text)
        if score:
            hits.append({"leaf": leaf, "enums": enums, "headings": headings, "width": w, "height": h})
    if not hits:
        # ABBYY gives up on a page of dense share tables, and the FT prints its
        # crossword on one: a blank-OCR leaf is a candidate when no text hit.
        hits = [{"leaf": leaf, "ocr_empty": True, "width": w, "height": h}
                for leaf, (w, h, text) in enumerate(pages) if len(text.strip()) < EMPTY_OCR_CHARS]
    if not any(titled(h) for h in hits):
        have = {h["leaf"] for h in hits}
        hits += [{"leaf": leaf, "prior": True, "width": pages[leaf][0], "height": pages[leaf][1]}
                 for leaf in prior if leaf not in have]
        # The OCR can lose the title and the ACROSS/DOWN headings but keep
        # the clues' counts: the page densest with them is the clue list.
        enums, leaf = max(((len(ENUM.findall(t)), leaf) for leaf, (_, _, t) in enumerate(pages)), default=(0, 0))
        if enums >= DENSE_ENUMS and leaf not in have | set(prior):
            hits.append({"leaf": leaf, "enums": enums, "dense": True,
                         "width": pages[leaf][0], "height": pages[leaf][1]})
        hits.sort(key=lambda h: h["leaf"])
    return hits


def fetch_edition(fx, item, meta, name):
    q = urllib.parse.quote
    d = os.path.join(fx.out, item, slug_of(item, name))
    # /download/ redirects to a mirror that can answer 500 for hours; the item's
    # own d1/d2 servers are tried first, with no retry, and /download/ is last.
    bases = [f"https://{meta[k]}{meta['dir']}/{q(name)}" for k in ("d1", "d2") if meta.get(k) and meta.get("dir")]
    bases.append(f"https://archive.org/download/{q(item)}/{q(name)}")
    files = {f["name"] for f in meta["files"]}
    if name + "_djvu.txt" not in files:
        return fetch_pdf_edition(fx, item, name, d, bases)
    text_path = os.path.join(d, "pagetext.json.gz")
    xml_path = os.path.join(d, "djvu.xml.gz")
    cached = None  # {"texts": [...], "words": {leaf: [width, height]}}: the hOCR route
    if words_misplaced(d):
        log(f"  {name}: cached words lie on other leaves; fetching the djvu.xml")
        os.remove(text_path)
        os.remove(xml_path)
    if os.path.exists(text_path):
        with gzip.open(text_path) as f:
            cached = json.load(f)
    elif not os.path.exists(xml_path) and name + "_hocr_pageindex.json.gz" in files \
            and name + "_hocr_searchtext.txt.gz" in files:
        texts = hocr_page_texts(fx, bases, name)
        if texts is None:
            log(f"  {name}: hOCR page offsets do not fit the text; using the djvu.xml")
        else:
            cached = {"texts": texts, "words": {}}
    if cached is not None:
        texts, words = cached["texts"], cached["words"]
        hits = crossword_hits([(0, 0, t) for t in texts], prior_leaves(d, len(texts)))
        need = {h["leaf"] for h in hits} - {int(k) for k in words}
        try:
            if need or not os.path.exists(xml_path):
                xml, dims = sparse_djvu_xml(fx, meta, item, name,
                                            {h["leaf"] for h in hits} | {int(k) for k in words}, len(texts))
                words = {str(k): v for k, v in dims.items()}
                write_atomic(xml_path, gzip.compress(xml, 6))
                write_atomic(text_path, gzip.compress(json.dumps({"texts": texts, "words": words}).encode(), 6))
            pages = [(*words.get(str(i), (0, 0)), t) for i, t in enumerate(texts)]
            for h in hits:
                h["width"], h["height"] = words[str(h["leaf"])]
        except urllib.error.HTTPError as e:
            if e.code not in (400, 403, 404):
                raise
            log(f"  {name}: per-page words refused (HTTP {e.code}); using the djvu.xml")
            cached = None
        except PageNumbering as e:
            log(f"  {name}: {e}; using the djvu.xml")
            cached = None
    if cached is None:
        for suffix, local in (("_djvu.txt", "djvu.txt.gz"), ("_djvu.xml", "djvu.xml.gz")):
            path = os.path.join(d, local)
            if not os.path.exists(path):
                write_atomic(path, gzip.compress(fetch_first(fx, bases, suffix, name + suffix), 6))
        with gzip.open(xml_path) as f:
            xml = f.read()
        aligned = scan_aligned(xml)
        if aligned != xml:
            write_atomic(xml_path, gzip.compress(aligned, 6))
        pages = page_texts(aligned)
        hits = crossword_hits(pages, prior_leaves(d, len(pages)))
    jp2 = {f for f in files if f.endswith("_jp2.zip")}
    zipname = name + "_jp2.zip"
    if hits and zipname not in jp2:
        raise RuntimeError(f"{zipname} not in the item's file list")
    for hit in hits:
        path = os.path.join(d, f"leaf_{hit['leaf']:04d}.jpg")
        if os.path.exists(path):
            continue
        member = f"{name}_jp2/{name}_{hit['leaf']:04d}.jp2"
        url = f"https://{meta['server']}/BookReader/BookReaderImages.php?" + urllib.parse.urlencode(
            {"zip": f"{meta['dir']}/{zipname}", "file": member, "id": item, "scale": 1, "rotate": 0})
        data = fx.get(url, f"{name} leaf {hit['leaf']}")
        if not data.startswith(b"\xff\xd8"):
            raise RuntimeError(f"leaf {hit['leaf']} image is not a JPEG ({data[:60]!r})")
        write_atomic(path, data)
    write_atomic(os.path.join(d, "pages.json"), json.dumps({
        "item": item, "edition": name, "date": edition_date(name), "leaves": len(pages),
        "detector_version": DETECTOR_VERSION, "crossword_pages": hits}, indent=1).encode())
    return hits


def scan_page(img):
    """A PDF page image greyed and scaled to the jp2 scans' width (the filer's
    SCAN_WIDTH, which its sizes assume). A 1-bit page at full size joins a
    grid's frame to the ink round it, so grids_on finds no grid on it; the
    antialiased grey page parts them."""
    import file_archive_org_puzzles as filer
    from PIL import Image
    gray = img.convert("L")
    return gray.resize((filer.SCAN_WIDTH, round(gray.height * filer.SCAN_WIDTH / gray.width)), Image.LANCZOS)


def grid_boxes(img):
    """[box] of the grid-shaped patches of ink on a PDF page (the filer's
    grids_on), looked for on the page halved (~2 s a page), in the
    coordinates of scan_page(img)."""
    import file_archive_org_puzzles as filer
    half = img.convert("L").reduce(2)
    k = filer.SCAN_WIDTH / half.width
    return [tuple(round(v * k) for v in box) for box in filer.grids_on(half, step=1, shaped=lambda b: filer.shaped_on(half, b))]


def reads_as_grid(page, box):
    """Whether trove_grid reads the box's ink as a grid: photos and adverts
    are grid-shaped too (6 such pages in FT 1981-04-01, one of them the grid)."""
    import trove_grid
    buf = io.BytesIO()
    page.crop((box[0] - 6, box[1] - 6, box[2] + 6, box[3] + 6)).save(buf, "PNG")
    buf.seek(0)
    return trove_grid.read_grid(buf)[0] is not None


def fetch_pdf_edition(fx, item, name, d, bases):
    """An edition archive.org holds as an image PDF only (one scanned image a
    page, no OCR): each page with a grid on it is a crossword page, saved as
    its leaf JPEG at SCAN_WIDTH and marked pdf. The djvu.xml.gz holds an empty
    OBJECT a page, so the filer reads the titles by image (ocr_titles) as it
    does a blank-OCR leaf."""
    import pypdf
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    pdf = pypdf.PdfReader(io.BytesIO(fetch_first(fx, bases, ".pdf", name + ".pdf")))
    shaped = []  # (leaf, page, read as a grid) of each page with grid-shaped ink
    for leaf, p in enumerate(pdf.pages):
        images = p.images
        if len(images) != 1:
            raise RuntimeError(f"page {leaf} holds {len(images)} images, not one scan")
        boxes = grid_boxes(images[0].image)
        if boxes:
            page = scan_page(images[0].image)
            shaped.append((leaf, page, any(reads_as_grid(page, box) for box in boxes)))
    # The pages whose grid reads; when none does (a faint grid), every
    # grid-shaped page, so the filer still looks for a title on each.
    keep = [x for x in shaped if x[2]] or shaped
    hits = []
    for leaf, page, _ in keep:
        buf = io.BytesIO()
        page.save(buf, "JPEG", quality=90)
        write_atomic(os.path.join(d, f"leaf_{leaf:04d}.jpg"), buf.getvalue())
        hits.append({"leaf": leaf, "pdf": True, "width": page.width, "height": page.height})
    count = len(pdf.pages)
    write_atomic(os.path.join(d, "djvu.xml.gz"), gzip.compress(
        b'<?xml version="1.0" encoding="UTF-8"?>\n<DjVuXML><BODY>\n'
        + b'<OBJECT width="0" height="0"></OBJECT>\n' * count + b"</BODY></DjVuXML>\n", 6))
    write_atomic(os.path.join(d, "pages.json"), json.dumps({
        "item": item, "edition": name, "date": edition_date(name),
        "leaves": count, "detector_version": DETECTOR_VERSION, "crossword_pages": hits}, indent=1).encode())
    return hits


def items_of(fx, group):
    _, query, title_re, since = next(g for g in GROUPS if g[0] == group)
    path = os.path.join(fx.out, "items", f"_group_{group}.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
        with open(path) as f:
            docs = json.load(f)
    else:
        docs = fx.search(query)
        write_atomic(path, json.dumps(docs).encode())
    keep = []
    for doc in docs:
        if not re.search(title_re, doc.get("title") or ""):
            continue
        if "_index" in doc["identifier"]:
            continue
        if since and (doc.get("date") or "")[:10] < since:
            continue
        keep.append(doc["identifier"])
    return sorted(keep)


def interleave(lists):
    """The lists' items taken in turn, one from each: [[a, b, c], [x]] -> [a, x, b, c]."""
    return [x for row in itertools.zip_longest(*lists) for x in row if x is not None]


class Run:
    """The editions in flight and the tallies; the done/failure logs are appended under a lock."""

    def __init__(self, out):
        self.out = out
        self.lock = threading.Lock()
        self.n = 0
        self.in_a_row = 0
        self.stop = False
        self.exit_code = 4

    def edition(self, fx, item, meta, name):
        """Fetch one edition and log it; True when it was done."""
        t = time.monotonic()
        fx.deadline = t + ITEM_SECONDS
        try:
            hits = fetch_edition(fx, item, meta, name)
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, OSError,
                ET.ParseError, EOFError, ValueError, KeyError) as e:
            with self.lock:
                log(f"  FAIL {name} after {time.monotonic() - t:.0f}s, left for the next run: "
                    f"{type(e).__name__}: {e}")
                append(self.out, "failures.tsv", [time.strftime("%F %T"), item, name, f"{type(e).__name__}: {e}"])
                self.in_a_row = self.in_a_row + 1 if outage(e) else 0
                if self.in_a_row >= FAILURES_IN_A_ROW and not self.stop:
                    self.stop = True
                    log(f"stopping: {self.in_a_row} editions in a row failed; archive.org looks down")
            return False
        heads = "; ".join(h for hit in hits for h in hit.get("headings", ["(blank OCR)"])[:2])
        with self.lock:
            self.in_a_row = 0
            self.n += 1
            append(self.out, "done.tsv", [item, name, DETECTOR_VERSION])
            log(f"  {name}: leaves {[h['leaf'] for h in hits]} {heads[:120]} ({time.monotonic() - t:.0f}s)")
        return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.expanduser("~/.cache/archive_org_editions"))
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--group", action="append", choices=[g[0] for g in GROUPS])
    ap.add_argument("--item", action="append")
    ap.add_argument("--edition", help="only editions whose name contains this")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--min-free-gb", type=float, default=30)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--seconds", type=float)
    args = ap.parse_args()
    stop_at = time.monotonic() + args.seconds if args.seconds else float("inf")
    os.makedirs(args.out, exist_ok=True)
    jobs = max(1, args.jobs)
    fx = Fetcher(args.out, max(args.delay, 1.0), jobs)
    done = load_done(args.out)
    run = Run(args.out)

    if args.item:
        plan = [("item", it) for it in args.item]
    else:
        plan = interleave([[(g, it) for it in items_of(fx, g)] for g in (args.group or [g[0] for g in GROUPS])])

    # Every one-item-a-year listing first: archive_coverage reads them, and an
    # edition run can stop long before it reaches a group's last item.
    for group, item in plan:
        if group in YEARLY_GROUPS:
            try:
                fx.metadata(item)
            except (urllib.error.URLError, RuntimeError, OSError, ValueError) as e:
                log(f"{item}: metadata failed, left for the next run: {e}")

    submitted = 0
    left = items_left = 0
    pending = set()
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        def room(limit):
            """Wait until fewer than `limit` editions are in flight."""
            nonlocal pending
            while len(pending) >= limit:
                _, pending = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)

        for k, (group, item) in enumerate(plan):
            if run.stop:
                break
            if time.monotonic() >= stop_at:
                items_left = len(plan) - k
                break
            fx.deadline = time.monotonic() + ITEM_SECONDS
            try:
                meta = fx.metadata(item)
            except (urllib.error.URLError, RuntimeError, OSError, ValueError) as e:
                log(f"{item}: metadata failed, left for the next run: {e}")
                append(args.out, "failures.tsv", [time.strftime("%F %T"), item, "", f"metadata: {e}"])
                continue
            names = editions_of(meta)
            if args.edition:
                names = [x for x in names if args.edition in x]
            todo = [x for x in names if (item, x) not in done]
            if args.list:
                print(f"{group}\t{item}\t{len(names)} editions\t{len(todo)} to do")
                continue
            if todo:
                log(f"{group} {item}: {len(todo)}/{len(names)} editions to do")
            for i, name in enumerate(todo):
                room(jobs)
                if run.stop:
                    break
                if time.monotonic() >= stop_at:
                    left += len(todo) - i
                    break
                if args.limit is not None and submitted >= args.limit:
                    log(f"stopped at --limit {args.limit}")
                    break
                free = shutil.disk_usage(args.out).free / 1e9
                if free < args.min_free_gb:
                    log(f"stopping: {free:.0f} GB free < --min-free-gb {args.min_free_gb}")
                    run.stop = True
                    run.exit_code = 3
                    break
                submitted += 1
                pending.add(pool.submit(run.edition, fx, item, meta, name))
            if run.stop or (args.limit is not None and submitted >= args.limit):
                break
    if run.stop:
        return run.exit_code
    if args.limit is not None and submitted >= args.limit:
        return 0
    if left or items_left:
        log(f"--seconds {args.seconds:g} reached: {run.n} editions this run; left for the next run: "
            f"{left} editions of the item it stopped in, and {items_left} items not opened")
        return 0
    log(f"finished: {run.n} editions this run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
