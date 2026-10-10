#!/usr/bin/env python3
"""Fetch archive.org newspaper editions' OCR, word positions and crossword page scans.

Usage:
  python3 tools/fetch_archive_org_editions.py --list                 # editions per group
  python3 tools/fetch_archive_org_editions.py                        # everything, Times first
  python3 tools/fetch_archive_org_editions.py --group times --group listener
  python3 tools/fetch_archive_org_editions.py --item NewsUK1998UKEnglish --edition 'Jul 25 1998'
  python3 tools/fetch_archive_org_editions.py --limit 20             # stop after 20 editions
  --out DIR     cache root (default downloads.ARCHIVE_ORG)
  --delay S     minimum seconds between one connection's requests (default 1.0)
  --jobs N      editions fetched at once (default 4)
  --min-free-gb N  stop cleanly when the cache disk has less free (default 30)
  --seconds N   start no edition after N seconds; the ones not started are
                counted "left for the next run" (tools/ocr_full_pass.sh runs
                it this way, so the corpus queue fetches in bounded slices)

Sources (GROUPS below), whose items a run opens in turn, each group getting
an equal share of editions (by_editions), so no group starves the rest within --seconds: the Times 1965/1974-99 full editions
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
from the front and from the back (prior_leaves); an item holding one edition
alone (the 1930 Times prints its crossword on leaf 4 or 6) counts the
editions of the items nearest it by date instead (sibling_pages). The filer reads their titles
by image (ocr_titles). An edition none of whose fetched leaves holds a title
is one whose scan lacks the crossword page. So is the page densest with
clue enumerations, DENSE_ENUMS or more, marked dense: the 1970s-80s OCR
loses the title and the ACROSS/DOWN headings of a page whose counts it
keeps (1977-07-22, leaf 21: 64 counts, no heading). So is each page headed
"FT UNIT TRUST INFORMATION SERVICE", marked unit_trust: the 1984-86 FT
prints its crossword there (1986-03-17, leaf 40).

A rerun skips every edition in done.tsv at the current DETECTOR_VERSION,
except one with no daily title on its fetched pages and no text-shown crossword page among the leaves its siblings print
it on most (prior_unfetched): only the prior_leaves it lacks are fetched.
Siblings of the edition's own leaf count vote apart too (common_leaves): an
item mixing 52- and 56-leaf issues splits the count.
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
import contextlib
import datetime
import gzip
import hashlib
import io
import itertools
import json
import os
import pickle
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

import dir_cache
import downloads

#: The tools modules a queue unit's fetch_unit may load, loaded as the unit
#: starts (under the queue's code lock, edition_queue.snapshot), so none is
#: loaded later from a tree that moved meanwhile. test_edition_queue.sh
#: checks this is what code_reach finds fetch_unit reaching.
MODULES = ("desktop_busy", "file_archive_org_puzzles", "ocr_clues", "ocr_remote", "scan_queue", "trove_grid",
           "trove_solution_ocr", "vlm_reader")

UA = "cryptic-teacher-fetcher/1.0 (cryptic-teacher@paulisageek.com)"
SAMAAN = 'uploader:"samaan.alshayef@gmail.com"'
DETECTOR_VERSION = 6
#: How many of the leaves its item's other editions print their crossword on
#: an edition with no crossword title in its text also fetches (prior_leaves).
PRIOR_LEAVES = 2
#: An item holding one edition alone (the 1930 Times: an item an issue) has no
#: other editions to count: prior_leaves counts the editions of this many
#: items nearest it by date whose names match its own up to the date.
NEIGHBOURS = 30
#: The fewest siblings of an edition's own leaf count printing a titled
#: crossword on one leaf that make it prior (common_leaves): fewer is noise.
SIZED_AGREE = 3
EMPTY_OCR_CHARS = 200
#: The fewest clue enumerations ("(5)", "(3,4)") on the page an edition
#: with no crossword title in its text fetches as its densest (crossword_hits).
DENSE_ENUMS = 10
#: The 1984-86 FT prints its crossword on its unit trust price page (431
#: of the 549 found there whose text names that page), whose tables the OCR
#: often reads but whose title it loses: an edition with no crossword title
#: in its text fetches each page so headed too (crossword_hits).
UNIT_TRUST = re.compile(r"(?i)unit\s+trust\s+information\s+service")
RETRY_WAITS = (5, 15, 45, 120)
ITEM_SECONDS = 300
#: Least gap between refetches of one item's metadata after a 404 (refresh_metadata).
REFRESH_SECONDS = 600
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
#: Numbered headings that are not the daily cryptic: its sister puzzles, the
#: book adverts ("CROSSWORD ENTHUSIASTS") and the 1993-98 Times Two
#: ("TIMES TWO CROSSWORD 747 In association with BRITISH MIDLAND").
NOT_DAILY = re.compile(r"(?i)concise|jumbo|listener|quick|enthusiast|title|book|\btwo\b|asso[cd]|\bbrit")
ENUM = re.compile(r"\(\s*\d{1,2}(?:\s*[,\-.]\s*\d{1,2}){0,4}\s*\)")
HEADING = re.compile(
    r"(?i)(?:listener|jumbo|times|two|cryptic|prize|quick|concise|polymath|mephisto|"
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


def memo(path, fn):
    """fn(path), worked out again only when the file at `path` changed (its
    mtime or size): the queue plans every minute off the same caches."""
    key = file_key(path)
    if key is None:
        return fn(path)
    hit = _MEMO.get((fn, path))
    if hit is None or hit[0] != key:
        hit = _MEMO[(fn, path)] = (key, fn(path))
    return hit[1]


_MEMO = {}
#: This thread's one_pass: {path: file_key} of the files it has stat'd.
_PASS = threading.local()


def file_key(path):
    """(mtime, size) of the file at `path`, None when it is missing; within
    one_pass, each path is stat'd once."""
    seen = getattr(_PASS, "keys", None)
    path = os.fspath(path)
    if seen is not None and path in seen:
        return seen[path]
    try:
        st = os.stat(path)
        key = (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        key = None
    if seen is not None:
        seen[path] = key
    return key


@contextlib.contextmanager
def one_pass():
    """Within it, memo stats each file once and crossword_leaves works each
    edition out once: a plan reads the siblings of every done edition
    (load_done), each sibling's pages.json shared by up to NEIGHBOURS
    editions, off a disk where a stat is slow."""
    if getattr(_PASS, "keys", None) is not None:
        yield
        return
    _PASS.keys, _PASS.leaves = {}, {}
    try:
        yield
    finally:
        _PASS.keys = _PASS.leaves = None


def stale(d):
    """Whether a done edition is fetched again (prior_unfetched)."""
    return prior_unfetched(d)


def prior_unfetched(d):
    """Whether an edition with no daily crossword title on the pages it
    fetched has no page its text shows a crossword on (detect) among the
    leaves its siblings print it on most often (common_leaves): it is fetched
    again, for the prior_leaves it lacks. A page fetched only as dense, blank
    or prior is no such page (1930-03-24's leaf 6 is sport results; its
    crossword is on leaf 4)."""
    path = os.path.join(d, "pages.json")
    if file_key(path) is None:
        return False
    try:
        pages = memo(path, read_pages)
    except (OSError, ValueError):
        return False
    hits = pages.get("crossword_pages") or ()
    if any(titled(h) or h.get("pdf") for h in hits):
        return False
    shown = {h["leaf"] for h in hits if not any(h.get(k) for k in GUESSED) and not sister(h)}
    common = common_leaves(d, pages["leaves"])
    return bool(common) and not common & shown \
        and bool(set(prior_leaves(d, pages["leaves"])) - {h["leaf"] for h in hits})


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
        self.refresh_lock = threading.Lock()
        self.refreshed = {}
        self.moved = {}
        #: Whether archive.org answered a request 429 (a queue unit says so
        #: in its exit, and the queue lowers its fetches in flight).
        self.throttled = False

    @property
    def deadline(self):
        return getattr(self.local, "deadline", float("inf"))

    @deadline.setter
    def deadline(self, value):
        self.local.deadline = value

    def _throttled(self):
        self.throttled = True
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

    def refresh_metadata(self, item, meta):
        """Update the cached `meta` in place from archive.org when the item has
        moved servers (its cached server/dir then 404 for every page image).
        True when the server or directory changed. At most one refetch an item
        every REFRESH_SECONDS, however many editions fail at once."""
        with self.refresh_lock:
            now = time.monotonic()
            if now - self.refreshed.get(item, -REFRESH_SECONDS) < REFRESH_SECONDS:
                return self.moved.get(item, False)
            self.refreshed[item] = now
            live = json.loads(self.get("https://archive.org/metadata/" + item, "metadata " + item))
            keys = ("server", "d1", "d2", "dir")
            self.moved[item] = bool(live.get("files")) and any(live.get(k) != meta.get(k) for k in keys)
            if self.moved[item]:
                meta.update(live)
                write_atomic(os.path.join(self.out, "items", item + ".json"), json.dumps(meta).encode())
            return self.moved[item]


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
    one per scan PDF ("Image Container PDF", not the lending library's
    encrypted copy or the text PDF) archive.org never OCR'd
    (FinancialTimes1981UKEnglish: 285, no _djvu.txt), which fetch_edition
    reads by image."""
    names = {f["name"][: -len("_djvu.txt")] for f in meta["files"] if f["name"].endswith("_djvu.txt")}
    names |= {f["name"][: -len(".pdf")] for f in meta["files"]
              if f.get("format") == "Image Container PDF" and f["name"].endswith(".pdf")}
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


def _fold_done(done, line):
    parts = line.decode().rstrip("\n").split("\t")
    if len(parts) == 3 and parts[2] == str(DETECTOR_VERSION):
        done.add((parts[0], parts[1]))


#: {edition dir: (dirs read, their dir_cache.dir_key, stale(edition dir),
#: near_items read or None)} of each verdict whose dirs had all settled
#: (load_done). The near items, not the out root's key: every new item
#: fetched moves the root.
_STALE = {}
#: Where load_done keeps _STALE between processes, on local disk: a plan in
#: a fresh process (each slice of the full pass, each re-exec) stats the
#: dirs a verdict read, not their pages.json (thousands of reads off the
#: media mount, minutes).
STALE_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "cryptic-teacher"
#: Seconds between saves of _STALE within one plan, so a plan cut short
#: (its slice ends first) leaves what it worked out to the next.
STALE_SAVE_SECONDS = 300
#: The out roots whose saved verdicts this process has loaded.
_STALE_LOADED = set()
#: This module's source as imported: the verdicts' code key is of the code
#: running, not of a file edited since.
_SOURCE = Path(__file__).read_text(encoding="utf-8")
_STALE_VERSION = []


def stale_version():
    """The code key the saved verdicts are kept under: what stale and
    stale_dirs reach (tools/code_reach.py)."""
    if not _STALE_VERSION:
        import code_reach  # here: a fetch unit loads only its MODULES
        _STALE_VERSION.append(code_reach.key("fetch_archive_org_editions", {"stale", "stale_dirs"},
                                             {"fetch_archive_org_editions": _SOURCE}))
    return _STALE_VERSION[0]


def stale_cache_path(out):
    return STALE_CACHE / f"archive_org_stale-{hashlib.sha256(os.fspath(out).encode()).hexdigest()[:12]}.pickle"


def load_stale(out):
    """Fill _STALE with the verdicts saved for `out` under this code, once a process."""
    out = os.fspath(out)
    if out in _STALE_LOADED:
        return
    _STALE_LOADED.add(out)
    try:
        with open(stale_cache_path(out), "rb") as f:
            saved = pickle.load(f)
    except (OSError, ValueError, EOFError, pickle.UnpicklingError):
        return
    if saved.get("out") == out and saved.get("version") == stale_version():
        for d, hit in saved["stale"].items():
            _STALE.setdefault(d, hit)


def save_stale(out, dirs):
    """Write _STALE's verdicts of the edition `dirs` for the next process,
    atomically; each dir and key once in the file, however many share it.
    With none there is nothing to keep, and no file is left (a test's
    empty root)."""
    same = {}
    one = lambda x: same.setdefault(x, x)
    keep = {d: ([one(x) for x in hit[0]], [one(k) for k in hit[1]], hit[2], None if hit[3] is None else tuple(map(one, hit[3])))
            for d in dirs if (hit := _STALE.get(d))}
    if not keep:
        return
    path = stale_cache_path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.part")
    with open(tmp, "wb") as f:
        pickle.dump({"out": os.fspath(out), "version": stale_version(), "stale": keep}, f, pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def load_done(out):
    """{(item, edition)} of done.tsv's rows at DETECTOR_VERSION that are not
    stale. done.tsv is parsed only as far as it grew (dir_cache.appended);
    an edition's stale verdict is kept until a dir it read (stale_dirs)
    moves its dir_cache.dir_key, across processes (load_stale, save_stale)."""
    rows = dir_cache.appended(os.path.join(out, "done.tsv"), set, _fold_done)
    load_stale(out)
    rows = list(rows)
    dirs = [os.path.join(out, item, slug_of(item, name)) for item, name in rows]
    done, keys = set(), {}
    changed, saved = False, time.monotonic()

    def key(d):
        if d not in keys:
            try:
                k, settled = dir_cache.dir_key(d)
            except (FileNotFoundError, NotADirectoryError):
                k, settled = None, False
            keys[d] = k if settled else None
        return keys[d]

    with one_pass():
        for (item, name), d in zip(rows, dirs):
            hit = _STALE.get(d)
            if hit is None or [key(x) for x in hit[0]] != hit[1] or (hit[3] is not None and near_items(d) != hit[3]):
                dirs_read, near = stale_dirs(d)
                ks = [key(x) for x in dirs_read]
                hit = (dirs_read, ks, stale(d), near)
                changed = True
                if None in ks:
                    _STALE.pop(d, None)
                else:
                    _STALE[d] = hit
                if time.monotonic() - saved > STALE_SAVE_SECONDS:
                    save_stale(out, dirs)
                    saved = time.monotonic()
            if not hit[2]:
                done.add((item, name))
    if changed:
        save_stale(out, dirs)
    return done


def stale_dirs(d):
    """(dirs, near): the dirs whose files stale(d) reads (the edition's,
    those of the siblings it counts and those listed to find them) and the
    near items it took them from (sibling_dirs)."""
    editions, listed, near = sibling_dirs(d)
    return [os.fspath(x) for x in (d, *editions, *listed)], near


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


def sister(hit):
    """Whether a crossword_pages hit's text names only a puzzle other than the
    daily (NOT_DAILY): a Times Two page shows no daily crossword."""
    numbered = [h for h in hit.get("headings") or () if NUMBERED.search(h)]
    return bool(numbered) and all(NOT_DAILY.search(h) for h in numbered)


#: The marks of a crossword_hits page fetched with no crossword in its text.
GUESSED = ("prior", "dense", "ocr_empty", "unit_trust")
ITEM_DATED = re.compile(r"(.+?)_(\d{4}-\d{2}-\d{2})_[^/]*")


def iso_day(text):
    """The day number of an ISO date, or None for one no calendar holds."""
    try:
        return datetime.date.fromisoformat(text).toordinal()
    except ValueError:
        return None


def sibling_pages(edition_dir):
    """The pages.json paths prior_leaves counts: those of sibling_dirs."""
    return [e / "pages.json" for e in sibling_dirs(edition_dir)[0]]


def sibling_dirs(edition_dir):
    """(editions, listed, near): the dirs of the item's other editions, or,
    for an item holding this edition alone, those of the near items
    (near_items); the dirs listed to find them; and the near items' names
    (None for the item's own editions)."""
    d = Path(edition_dir)
    own = [d.parent / e for e in memo(d.parent, subdirs) if e != d.name]
    near = None if own else near_items(d)
    if near is None:
        return own, [d.parent], None
    items = [d.parent.parent / item for item in near]
    return [i / e for i in items for e in memo(i, subdirs)], [d.parent, *items], near


def near_items(edition_dir):
    """The names of the NEIGHBOURS items nearest the edition's by date named
    like it up to the date ("per_times_the-times_1930-02-17_45439":
    "per_times_the-times"), off the out root's listing; None for an item
    named with no date."""
    d = Path(edition_dir)
    m = ITEM_DATED.fullmatch(d.parent.name)
    day = m and iso_day(m[2])
    if not day:
        return None
    near = sorted((abs(iso_day(date) - day), item) for prefix, date, item in memo(d.parent.parent, dated_items)
                  if prefix == m[1] and item != d.parent.name)
    return tuple(item for _, item in near[:NEIGHBOURS])


def subdirs(path):
    """The names of the directories in `path` (an item's editions)."""
    try:
        return sorted(e.name for e in os.scandir(path) if e.is_dir())
    except FileNotFoundError:
        return []


def dated_items(root):
    """[(name up to the date, ISO date, item)] of the items under `root` named with a date."""
    out = []
    for item in os.listdir(root):
        m = ITEM_DATED.fullmatch(item)
        if m and iso_day(m[2]):
            out.append((m[1], m[2], item))
    return out


def read_pages(path):
    return json.loads(Path(path).read_text())


def crossword_leaves(edition_dir):
    """(fronts, backs, sized): Counters of the leaves its siblings
    (sibling_pages) print a titled crossword on, by leaf number, by distance
    from the back, and by (sibling's leaf count, leaf number)."""
    seen = getattr(_PASS, "leaves", None)
    if seen is None:
        return _crossword_leaves(edition_dir)
    key = os.fspath(edition_dir)
    if key not in seen:
        seen[key] = _crossword_leaves(edition_dir)
    return seen[key]


def _crossword_leaves(edition_dir):
    fronts, backs, sized = collections.Counter(), collections.Counter(), collections.Counter()
    for pj in sibling_pages(edition_dir):
        try:
            pages = memo(pj, read_pages)
        except (OSError, ValueError):
            continue
        for hit in pages.get("crossword_pages") or ():
            if titled(hit):
                fronts[hit["leaf"]] += 1
                backs[pages["leaves"] - 1 - hit["leaf"]] += 1
                sized[pages["leaves"], hit["leaf"]] += 1
    return fronts, backs, sized


def common_leaves(edition_dir, count):
    """The PRIOR_LEAVES leaves its siblings print a titled crossword on most
    often (crossword_leaves), and those of its siblings of `count` leaves: an
    item mixing sizes splits the count (1998-11-26, 56 leaves: 52-leaf
    siblings print it on leaf 25, 56-leaf ones on leaf 27)."""
    fronts, _, sized = crossword_leaves(edition_dir)
    same = collections.Counter({leaf: k for (n, leaf), k in sized.items() if n == count and k >= SIZED_AGREE})
    return {n for n, _ in fronts.most_common(PRIOR_LEAVES)} | {n for n, _ in same.most_common(PRIOR_LEAVES)}


def prior_leaves(edition_dir, count):
    """The leaves of an edition of `count` leaves its crossword most likely
    lies on: its last, the common_leaves, and the PRIOR_LEAVES commonest
    leaves holding a titled crossword in its siblings by distance from the
    back (crossword_leaves)."""
    _, backs, _ = crossword_leaves(edition_dir)
    leaves = {count - 1} | common_leaves(edition_dir, count) \
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
        have |= {h["leaf"] for h in hits}
        hits += [{"leaf": leaf, "unit_trust": True, "width": w, "height": h}
                 for leaf, (w, h, text) in enumerate(pages) if leaf not in have and UNIT_TRUST.search(text)]
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


def pdf_pages(data):
    """({"leaves": page count, "hits": [hit]}, JPEG bytes) of an image PDF:
    each page with a grid on it, at SCAN_WIDTH, its JPEG's length in its
    hit's "bytes", the JPEGs end to end in the hits' order. Run on the
    desktop when tools/ocr_remote.py can (~20 s of CPU an edition)."""
    import pypdf
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    pdf = pypdf.PdfReader(io.BytesIO(data))
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
    hits, jpegs = [], []
    for leaf, page, _ in keep:
        buf = io.BytesIO()
        page.save(buf, "JPEG", quality=90)
        jpegs.append(buf.getvalue())
        hits.append({"leaf": leaf, "pdf": True, "width": page.width, "height": page.height, "bytes": len(jpegs[-1])})
    return {"leaves": len(pdf.pages), "hits": hits}, b"".join(jpegs)


def fetch_pdf_edition(fx, item, name, d, bases):
    """An edition archive.org holds as an image PDF only (one scanned image a
    page, no OCR): each page with a grid on it is a crossword page, saved as
    its leaf JPEG at SCAN_WIDTH and marked pdf (pdf_pages). The djvu.xml.gz
    holds an empty OBJECT a page, so the filer reads the titles by image
    (ocr_titles) as it does a blank-OCR leaf."""
    import ocr_remote
    data = fetch_first(fx, bases, ".pdf", name + ".pdf")
    got = ocr_remote.call("pdf_pages", data=data)
    if got is None:
        with ocr_remote.local_slot():
            got = pdf_pages(data)
    found, jpegs = got
    hits, at = [], 0
    for hit in found["hits"]:
        n = hit.pop("bytes")
        write_atomic(os.path.join(d, f"leaf_{hit['leaf']:04d}.jpg"), jpegs[at:at + n])
        at += n
        hits.append(hit)
    count = found["leaves"]
    write_atomic(os.path.join(d, "djvu.xml.gz"), gzip.compress(
        b'<?xml version="1.0" encoding="UTF-8"?>\n<DjVuXML><BODY>\n'
        + b'<OBJECT width="0" height="0"></OBJECT>\n' * count + b"</BODY></DjVuXML>\n", 6))
    write_atomic(os.path.join(d, "pages.json"), json.dumps({
        "item": item, "edition": name, "date": edition_date(name),
        "leaves": count, "detector_version": DETECTOR_VERSION, "crossword_pages": hits}, indent=1).encode())
    return hits


#: How long a group's cached item listing stands before it is searched again.
LISTING_SECONDS = 7 * 86400


def listing_path(out, group):
    return os.path.join(out, "items", f"_group_{group}.json")


def items_of(fx, group, refresh=False):
    """The group's items, from its cached listing while that is under
    LISTING_SECONDS old (and not `refresh`), else searched afresh."""
    path = listing_path(fx.out, group)
    if not refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < LISTING_SECONDS:
        with open(path) as f:
            docs = json.load(f)
    else:
        docs = fx.search(next(g for g in GROUPS if g[0] == group)[1])
        write_atomic(path, json.dumps(docs).encode())
    return kept_items(group, docs)


def kept_items(group, docs):
    _, _, title_re, since = next(g for g in GROUPS if g[0] == group)
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


def by_editions(lists, weight):
    """The lists' items merged so each list gets an equal share of editions,
    not of items: the next item is the next of the list with the fewest
    editions taken so far (ties to the earlier list); weight(x) is x's
    editions still to fetch. So a group of one-issue items (pub_times, the
    Listener) keeps pace with the groups of one-year items, ~300 editions
    each, instead of getting one edition a round."""
    taken, at, out = [0] * len(lists), [0] * len(lists), []
    while True:
        live = [i for i in range(len(lists)) if at[i] < len(lists[i])]
        if not live:
            return out
        i = min(live, key=lambda i: (taken[i], i))
        x = lists[i][at[i]]
        at[i] += 1
        out.append(x)
        taken[i] += weight(x)


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
        """Fetch one edition and log it; True when it was done, None when
        another process is fetching it (its lock beside done.tsv)."""
        import scan_queue  # here: the desktop imports this module for pdf_pages alone
        with scan_queue.source_lock(Path(self.out) / "done.tsv", f"{item}/{name}") as mine:
            if not mine:
                log(f"  {name}: another fetch has it; skipped")
                return None
            return self._edition(fx, item, meta, name)

    def _edition(self, fx, item, meta, name):
        t = time.monotonic()
        fx.deadline = t + ITEM_SECONDS
        try:
            try:
                hits = fetch_edition(fx, item, meta, name)
            except urllib.error.HTTPError as e:
                # The cached metadata names the server the item lived on; a 404
                # after the item moved is cured by the live metadata.
                if e.code != 404 or not fx.refresh_metadata(item, meta):
                    raise
                log(f"  {name}: {item} moved servers; metadata refreshed, trying again")
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
        kinds = {"pdf": "(PDF page with a grid)", "ocr_empty": "(blank OCR)", "prior": "(prior leaf)",
                 "dense": "(densest with counts)", "unit_trust": "(unit trust page)"}
        heads = "; ".join(h for hit in hits for h in (hit.get("headings")
                          or [next((v for k, v in kinds.items() if hit.get(k)), "(no heading)")])[:2])
        with self.lock:
            self.in_a_row = 0
            self.n += 1
            append(self.out, "done.tsv", [item, name, DETECTOR_VERSION])
            log(f"  {name}: leaves {[h['leaf'] for h in hits]} {heads[:120]} ({time.monotonic() - t:.0f}s)")
        return True


def cached_meta(out, item):
    """The item's editions from its cached metadata, or None when it has none
    cached; reads no network."""
    path = os.path.join(out, "items", item + ".json")
    if not os.path.exists(path):
        return None
    return memo(path, lambda p: editions_of(json.loads(Path(p).read_bytes())))


def plan(out, groups=None):
    """The fetch units due (tools/edition_queue.py), most urgent first, off
    the caches alone, no network: a group whose item listing is missing or
    over LISTING_SECONDS old is listed first ({"group": g}); then, in
    by_editions order, each item with no cached metadata ({"item": it},
    its metadata fetched and, when it holds one edition, that edition) and
    each edition not in done.tsv ({"item": it, "name": edition}), the
    groups taking turns an edition each, so none starves the rest.""" 
    done = load_done(out)
    units, lists = [], []
    for group in groups or [g[0] for g in GROUPS]:
        path = listing_path(out, group)
        fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < LISTING_SECONDS
        if not fresh:
            units.append({"group": group, "rel": f"_group_{group}", "reason": "item listing stale"})
        if not os.path.exists(path):
            lists.append([])
            continue
        lists.append([(group, it) for it in memo(path, lambda p, g=group: kept_items(g, json.loads(Path(p).read_bytes())))])
    per_group = []
    for row in lists:
        per_group.append([])
        for _, item in row:
            names = cached_meta(out, item)
            if names is None:
                per_group[-1].append({"item": item, "rel": item, "reason": "metadata not cached"})
            else:
                per_group[-1] += [{"item": item, "name": x, "rel": f"{item}/{x}", "reason": "not fetched"}
                                  for x in names if (item, x) not in done]
    return units + by_editions(per_group, lambda u: 1)


def fetch_unit(out, unit, min_free_gb=30):
    """In a queue unit's own process: fetch what plan()'s `unit` names, one
    connection at --delay 1. Returns "fetched", "current" (nothing left to
    do), "busy" (another fetch has it), "failed" (the edition's own fault,
    logged to failures.tsv), "outage" (archive.org looks down: outage()),
    "throttled" (fetched, but archive.org answered 429) or "disk" (under
    `min_free_gb` free)."""
    fx = Fetcher(out, 1.0, 1)
    if "group" in unit:
        try:
            items_of(fx, unit["group"], refresh=True)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            log(f"{unit['group']}: item listing failed, left for the next run: {type(e).__name__}: {e}")
            return "outage" if outage(e) else "failed"
        return "fetched"
    if shutil.disk_usage(out).free / 1e9 < min_free_gb:
        log(f"under {min_free_gb} GB free in {out}; no fetch")
        return "disk"
    item = unit["item"]
    fx.deadline = time.monotonic() + ITEM_SECONDS
    try:
        meta = fx.metadata(item)
    except (urllib.error.URLError, RuntimeError, OSError, ValueError) as e:
        log(f"{item}: metadata failed, left for the next run: {e}")
        append(out, "failures.tsv", [time.strftime("%F %T"), item, "", f"metadata: {e}"])
        return "outage" if outage(e) else "failed"
    names = [unit["name"]] if unit.get("name") else editions_of(meta)
    if len(names) != 1:
        # Several editions: the next plan lists each as a unit of its own.
        return "fetched"
    if edition_done(out, item, names[0]):
        return "current"
    run = Run(out)
    ok = run.edition(fx, item, meta, names[0])
    if ok is None:
        return "busy"
    if ok:
        return "throttled" if fx.throttled else "fetched"
    return "outage" if run.in_a_row else "failed"


def edition_done(out, item, name):
    """Whether done.tsv holds this one edition as load_done would."""
    want = f"{item}\t{name}\t{DETECTOR_VERSION}"
    try:
        with open(os.path.join(out, "done.tsv")) as f:
            if not any(line.rstrip("\n") == want for line in f):
                return False
    except FileNotFoundError:
        return False
    return not stale(os.path.join(out, item, slug_of(item, name)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(downloads.ARCHIVE_ORG))
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
        lists = [[(g, it) for it in items_of(fx, g)] for g in (args.group or [g[0] for g in GROUPS])]
        # Every one-item-a-year listing first: archive_coverage reads them, an
        # edition run can stop long before it reaches a group's last item, and
        # the plan's order weighs each item by its editions to do.
        todo_of = {}
        for group, item in (x for row in lists for x in row):
            if group in YEARLY_GROUPS:
                try:
                    todo_of[item] = sum((item, x) not in done for x in editions_of(fx.metadata(item)))
                except (urllib.error.URLError, RuntimeError, OSError, ValueError) as e:
                    log(f"{item}: metadata failed, left for the next run: {e}")
        done_items = {it for it, _ in done}
        plan = by_editions(lists, lambda x: todo_of.get(x[1], 0 if x[1] in done_items else 1))

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
