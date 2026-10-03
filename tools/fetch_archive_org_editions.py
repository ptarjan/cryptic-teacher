#!/usr/bin/env python3
"""Fetch archive.org newspaper editions' OCR, word positions and crossword page scans.

Usage:
  python3 tools/fetch_archive_org_editions.py --list                 # editions per group
  python3 tools/fetch_archive_org_editions.py                        # everything, Times first
  python3 tools/fetch_archive_org_editions.py --group times --group listener
  python3 tools/fetch_archive_org_editions.py --item NewsUK1998UKEnglish --edition 'Jul 25 1998'
  python3 tools/fetch_archive_org_editions.py --limit 20             # stop after 20 editions
  --out DIR     cache root (default ~/.cache/archive_org_editions)
  --delay S     minimum seconds between requests (default 1.0)
  --min-free-gb N  stop cleanly when the cache disk has less free (default 30)

Sources, in fetch order (GROUPS below): the Times 1965/1974-99 full editions
(NewsUK<year>UKEnglish, one item per year holding ~200 editions); the BBC
Listener magazine (pub_listener, one item per issue); the same uploader's
Financial Times, Guardian, Daily/Sunday Telegraph and 1971 Sunday Times; and
archive.org's pub_times / pub_sunday-times (1930 on; the Times crossword began
1 Feb 1930, so earlier issues are skipped).

Layout under --out:
  items/<item>.json           cached /metadata/<item> response
  done.tsv                    item, edition, detector version: finished editions
  failures.tsv                time, item, edition, error (append-only log)
  <item>/<slug>/djvu.txt.gz   the edition's _djvu.txt OCR, gzipped
  <item>/<slug>/djvu.xml.gz   the edition's _djvu.xml (per-word page coords), gzipped
  <item>/<slug>/pages.json    edition name, leaf count, and each crossword page:
                              leaf, enumeration count, the headings found
                              ("CROSSWORD NO 20,853"), or ocr_empty (below)
  <item>/<slug>/leaf_NNNN.jpg full-resolution scan of each crossword page

<slug> is YYYY-MM-DD_<issue> for the dated multi-edition items and the
identifier itself for one-issue items. djvu.xml is the word-position file
because it is the one every edition has (the hOCR page index and search text
are missing from whole years, e.g. 1985). Its <OBJECT> elements are the
pages in leaf order, and leaf N is <edition>_jp2/<edition>_NNNN.jp2 inside
the edition's _jp2.zip.

Page images come from BookReaderImages.php, the reader's per-page endpoint,
which unpacks one leaf of the jp2.zip server-side and returns a JPEG. Never
the whole _jp2.zip: ~120 MB per edition, terabytes in total.

When no page's text shows a crossword, every leaf whose OCR is blank (under
EMPTY_OCR_CHARS) is fetched instead, marked ocr_empty: ABBYY returns nothing
for a page of dense share tables, and the 1980s FT prints its crossword on
one (FT 3 Apr 1985, leaf 41). The filer finds the grid in those by image.

A rerun skips every edition in done.tsv at the current DETECTOR_VERSION.
Bumping DETECTOR_VERSION re-runs detection from the cached djvu.xml and
fetches only the page images it newly finds; no text is downloaded again.

Politeness: one request at a time, at least --delay seconds apart, and a
retry with backoff (honouring Retry-After) on 429, 5xx and network errors.
A 404 is permanent: logged to failures.tsv, and the edition stays undone.
"""

import argparse
import datetime
import gzip
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = "cryptic-teacher-fetcher/1.0 (cryptic-teacher@paulisageek.com)"
SAMAAN = 'uploader:"samaan.alshayef@gmail.com"'
DETECTOR_VERSION = 3
EMPTY_OCR_CHARS = 200
RETRY_WAITS = (5, 15, 45, 120, 300, 600)

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

ENUM = re.compile(r"\(\s*\d{1,2}(?:\s*[,\-.]\s*\d{1,2}){0,4}\s*\)")
HEADING = re.compile(
    r"(?i)(?:listener|jumbo|times|cryptic|prize|quick|concise|polymath|mephisto|"
    r"inquisitor|azed|everyman|enigmatic|genius)?\W{0,3}cross\s?word[^\n]{0,30}"
    r"|puzzle\s+no\.?\s*\d[\d,.]*")


class Fetcher:
    def __init__(self, out, delay):
        self.out = out
        self.delay = delay
        self.last = 0.0

    def get(self, url, what, retry=True):
        """GET url politely; returns bytes, raises HTTPError on 404/403/400.

        retry=False raises on the first failure instead of waiting and retrying.
        """
        for attempt, wait in enumerate(RETRY_WAITS + (None,) if retry else (None,)):
            gap = self.last + self.delay - time.monotonic()
            if gap > 0:
                time.sleep(gap)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=300) as r:
                    data = r.read()
                self.last = time.monotonic()
                return data
            except urllib.error.HTTPError as e:
                self.last = time.monotonic()
                if e.code not in (429, 500, 502, 503, 504) or wait is None:
                    raise
                wait = max(wait, int(e.headers.get("Retry-After") or 0))
                err = f"HTTP {e.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                self.last = time.monotonic()
                if wait is None:
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
    """Edition base names in an item: one per _djvu.txt, in date order."""
    names = [f["name"][: -len("_djvu.txt")] for f in meta["files"] if f["name"].endswith("_djvu.txt")]
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
    """[(width, height, text)] per leaf, from a djvu.xml."""
    pages = []
    for _, el in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if el.tag != "OBJECT":
            continue
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
    numbered = bool(re.search(r"(?i)cross\s?word\W{0,3}(?:puzzle\W{0,3})?(?:no\.?\s*)?\d[\d,.]{2,}", text))
    numbered = numbered or bool(re.search(r"(?i)cross\s?word\s+puzzle\s+no", text))
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
                if len(parts) == 3 and parts[2] == str(DETECTOR_VERSION):
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


def fetch_edition(fx, item, meta, name):
    q = urllib.parse.quote
    d = os.path.join(fx.out, item, slug_of(item, name))
    # /download/ redirects to a mirror that can answer 500 for hours; the item's
    # own d1/d2 servers are tried first, with no retry, and /download/ is last.
    bases = [f"https://{meta[k]}{meta['dir']}/{q(name)}" for k in ("d1", "d2") if meta.get(k) and meta.get("dir")]
    bases.append(f"https://archive.org/download/{q(item)}/{q(name)}")
    for suffix, local in (("_djvu.txt", "djvu.txt.gz"), ("_djvu.xml", "djvu.xml.gz")):
        path = os.path.join(d, local)
        if not os.path.exists(path):
            write_atomic(path, gzip.compress(fetch_first(fx, bases, suffix, name + suffix), 6))
    with gzip.open(os.path.join(d, "djvu.xml.gz")) as f:
        pages = page_texts(f.read())
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
    jp2 = {f["name"] for f in meta["files"] if f["name"].endswith("_jp2.zip")}
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.expanduser("~/.cache/archive_org_editions"))
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--group", action="append", choices=[g[0] for g in GROUPS])
    ap.add_argument("--item", action="append")
    ap.add_argument("--edition", help="only editions whose name contains this")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--min-free-gb", type=float, default=30)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    fx = Fetcher(args.out, max(args.delay, 1.0))
    done = load_done(args.out)

    if args.item:
        plan = [("item", it) for it in args.item]
    else:
        plan = [(g, it) for g in (args.group or [g[0] for g in GROUPS]) for it in items_of(fx, g)]

    n = 0
    for group, item in plan:
        try:
            meta = fx.metadata(item)
        except (urllib.error.HTTPError, RuntimeError) as e:
            log(f"{item}: metadata failed: {e}")
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
        for name in todo:
            if args.limit is not None and n >= args.limit:
                log(f"stopped at --limit {args.limit}")
                return 0
            free = shutil.disk_usage(args.out).free / 1e9
            if free < args.min_free_gb:
                log(f"stopping: {free:.0f} GB free < --min-free-gb {args.min_free_gb}")
                return 3
            t = time.monotonic()
            try:
                hits = fetch_edition(fx, item, meta, name)
            except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, OSError,
                    ET.ParseError, EOFError) as e:
                log(f"  FAIL {name}: {type(e).__name__}: {e}")
                append(args.out, "failures.tsv", [time.strftime("%F %T"), item, name, f"{type(e).__name__}: {e}"])
                continue
            append(args.out, "done.tsv", [item, name, DETECTOR_VERSION])
            n += 1
            heads = "; ".join(h for hit in hits for h in hit.get("headings", ["(blank OCR)"])[:2])
            log(f"  {name}: leaves {[h['leaf'] for h in hits]} {heads[:120]} ({time.monotonic() - t:.0f}s)")
    log(f"finished: {n} editions this run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
