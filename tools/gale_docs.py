#!/usr/bin/env python3
"""Gale's PDF download link for the crossword of each of the checklists'
next rows (tools/gale_inbox.py's Times, tools/gale_listener.py's Listener).

Paul allowed this lookup on 2026-10-07: each 3-minute sync looks up at most
PER_TICK uncached rows per paper, PACE seconds apart, and nothing else. A
row's lookup is the Alberta Research Portal's session (geo-IP, no login),
Gale's month of issues (issuesForMonth, once per month), then that date's
issue (navigateToIssue), whose table of contents names the crossword's
document id, page and page-image record ids. CACHE keeps each answer, a miss
too, so no date is asked twice.

The link is Gale's own Download target, BulkPDF as a GET: it needs a Gale
session in the browser (the checklists' "Start Gale session"), not this
one's, and returns the crossword's page with a citation page whose text the
inbox sweep recognises and files by.

    python3 tools/gale_docs.py TTDA 1988-01-12   # look up one date, print its link
"""
import datetime
import http.client
import http.cookiejar
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path.home() / ".cache/gale_inbox/docs.json"
PER_TICK = 15
PACE = 2.0
PORTAL = "https://abresearchportal.ca"
GALE = "https://go.gale.com/ps"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36"
#: product: (the portal's db code, the citation's paper, the archive's name)
PRODUCTS = {"TTDA": ("ttda", "Times", "The Times Digital Archive"),
            "LSNR": ("lsnr", "The Listener", "The Listener Historical Archive")}
MONTHS = ["Jan.", "Feb.", "Mar.", "Apr.", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]
DVI = re.compile(r"var dviResponse = (\{.*?\});\s*\n")


class Gale:
    """One portal session per product, asked one thing at a time."""

    def __init__(self, pace=PACE):
        self.pace, self.last, self.openers, self.months = pace, 0.0, {}, {}

    def get(self, prod, url, xhr=False):
        if prod not in self.openers:
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                             urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
            op.addheaders = [("User-Agent", UA)]
            self.openers[prod] = op
            self.get(prod, f"{PORTAL}/collections")
            self.get(prod, f"{PORTAL}/actions/auth.php?db={PRODUCTS[prod][0]}")
        time.sleep(max(0.0, self.last + self.pace - time.time()))
        try:
            req = urllib.request.Request(url, headers={"X-Requested-With": "XMLHttpRequest"} if xhr else {})
            with self.openers[prod].open(req, timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        finally:
            self.last = time.time()

    def issues(self, prod, day):
        """Gale's issues of `day`: [{mcode, date, issueNumber, volume}]."""
        key = (prod, day.year, day.month)
        if key not in self.months:
            self.months[key] = json.loads(self.get(
                prod, f"{GALE}/browseByDate/issuesForMonth?monthYear=1{day:%Y%m}&prodId={prod}&u=alberta_portal",
                xhr=True))
        return self.months[key].get(f"1{day:%Y%m%d}", [])

    def issue(self, prod, i):
        """The issue's viewer data: its contents and page records."""
        q = urllib.parse.urlencode({"u": "alberta_portal", "p": prod, "mCode": i["mcode"], "issueDate": i["date"],
                                    "issueNumber": i["issueNumber"], "volume": i["volume"], "loadFormat": "page"})
        m = DVI.search(self.get(prod, f"{GALE}/navigateToIssue?{q}"))
        if not m:
            raise ValueError(f"Gale's issue page for {i['date']} has no viewer data (session refused?)")
        return json.loads(m.group(1))


def articles(toc):
    for a in toc or ():
        if a.get("docId"):
            yield a
        yield from articles(a.get("subArticleDocuments"))


def crossword(prod, titles, number=None):
    """The index into `titles` of the day's crossword, or None: a title
    naming a crossword, not the Concise or a solution or winners' list;
    the one naming `number` first."""
    bad = re.compile(r"concise|solution|winners|report on|quick", re.IGNORECASE)
    cands = [i for i, t in enumerate(titles) if re.search(r"crossword", t, re.IGNORECASE) and not bad.search(t)]
    if number is not None:
        named = re.compile(rf"(?<![\d,.]){number // 1000},?{number % 1000:03}(?![\d,])" if number >= 1000
                           else rf"(?<![\d,.]){number}(?![\d,])")
        cands.sort(key=lambda i: not named.search(titles[i]))
    return cands[0] if cands else None


def entry(prod, dvi, number=None):
    """The cache entry for the crossword in issue `dvi`."""
    arts = list(articles(dvi["originalDocument"].get("articleTableOfContents")))
    k = crossword(prod, [a["docTitle"] for a in arts], number)
    if k is None:
        return None
    a = arts[k]
    pages = {int(p["pageNumber"]): p["mediaRecordId"] for p in dvi.get("pageDocuments") or ()}
    first = int(a["startingPage"])
    records = [pages[p] for p in range(first, first + int(a.get("pageCount") or 1)) if p in pages]
    if not records:
        return None
    return {"doc": a["docId"], "title": a["docTitle"], "page": first, "records": records}


def lookup(prod, day, gale, number=None):
    """The entry for `day`, or {"why": ...} when Gale has no such crossword."""
    issues = gale.issues(prod, day)
    if not issues:
        return {"why": "Gale has no issue that day"}
    titles = []
    for i in issues:
        dvi = gale.issue(prod, i)
        e = entry(prod, dvi, number)
        if e:
            return e
        titles += [a["docTitle"] for a in articles(dvi["originalDocument"].get("articleTableOfContents"))]
    return {"why": "no crossword in the issue's contents", "crosswordish": [t for t in titles if "ross" in t.lower()]}


def download_url(prod, day, e):
    """Gale's Download (PDF) for entry `e` of `day`, as a GET."""
    _, paper, archive = PRODUCTS[prod]
    cite = (f'"{e["title"].strip().rstrip(". ")}." {paper}, {day.day} {MONTHS[day.month - 1]} {day.year}, p. {e["page"]}. '
            f"{archive}, link.gale.com/apps/doc/{e['doc']}/{prod}?u=alberta_portal&sid=bookmark-{prod}.")
    q = urllib.parse.urlencode({"dl": e["doc"], "u": "alberta_portal", "p": prod, "recordIds": ",".join(e["records"]),
                                "citationTextJson": urllib.parse.quote(cite, safe="")})
    return f"{GALE}/callisto/BulkPDF/UBER2?{q}"


def load(cache=CACHE):
    return json.loads(cache.read_text()) if cache.exists() else {}


def link(prod, day, docs):
    """The Download URL for `day` from the loaded cache `docs`, else None."""
    e = docs.get(f"{prod}/{day.isoformat()}")
    return download_url(prod, day, e) if e and "doc" in e else None


def resolve(prod, rows, out=sys.stdout, gale=None, cache=CACHE, limit=PER_TICK):
    """Look up the first `limit` of `rows` ([(date, number or None)]) not in
    the cache; stop at Gale's first error (said to `out`). Returns how many
    links were added."""
    docs = load(cache)
    todo = {}  # one lookup a date, though two puzzles share it
    for d, n in rows:
        if f"{prod}/{d.isoformat()}" not in docs:
            todo.setdefault(d, n)
    added = 0
    for day, number in list(todo.items())[:limit]:
        gale = gale or Gale()
        try:
            e = lookup(prod, day, gale, number)
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, KeyError) as ex:
            # A network or Gale error: the row is asked again next tick.
            print(f"gale_docs: {prod} {day}: {type(ex).__name__}: {ex}", file=out)
            break
        e["at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        docs[f"{prod}/{day.isoformat()}"] = e
        added += "doc" in e
        print(f"gale_docs: {prod} {day}: " + (f"{e['doc']} {e['title']}" if "doc" in e else e["why"]), file=out)
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(docs, indent=0, sort_keys=True))
        tmp.replace(cache)
    return added


if __name__ == "__main__":
    prod, day = sys.argv[1], datetime.date.fromisoformat(sys.argv[2])
    e = lookup(prod, day, Gale())
    print(json.dumps(e, indent=1))
    if "doc" in e:
        print(download_url(prod, day, e))
