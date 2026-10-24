#!/usr/bin/env python3
"""Gale's PDF download link for the crossword of each row tools/gale_fetch.py
wants (the Times', the other papers', the Listener's).

A row is a puzzle's issue, or (lookup_report) the Listener's "Report on
Crossword No. N" with its answers, searched in the issues one to
REPORT_WEEKS weeks after the puzzle's. A row's lookup is the Alberta
Research Portal's session (geo-IP, no login), Gale's month of issues
(issuesForMonth, once per month), then that date's issue
(navigateToIssue), whose table of contents names the crossword's document
id, page and page-image record ids. CACHE keeps each answer, a miss too,
so no date is asked twice; one from an older MATCHER is asked once more
when stale.

The link is Gale's own Download target, BulkPDF as a GET (download_url),
fetched in a portal session; it returns the crossword's page with a
citation page naming its document.

    python3 tools/gale_docs.py TTDA 1988-01-12   # look up one date, print its link
"""
import datetime
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from gale_http import Chrome, click_headers, verifies

CACHE = Path.home() / ".cache/gale_inbox/docs.json"
PACE = 2.0
#: Per product, bumped when crossword() or report() would pick differently:
#: entries cached by an older one are looked up again (stale).
MATCHER = {"TTDA": 5, "LSNR": 2, "TGRH": 2, "FTHA": 2, "INDA": 2, "STHA": 2, "TLSH": 2}
REPORT_WEEKS = 5
PORTAL = "https://abresearchportal.ca"
GALE = "https://go.gale.com/ps"
#: product: (the portal's db code, the citation's paper, the archive's name)
PRODUCTS = {"TTDA": ("ttda", "Times", "The Times Digital Archive"),
            "LSNR": ("lsnr", "The Listener", "The Listener Historical Archive"),
            "TGRH": ("tgrh", "Daily Telegraph", "The Telegraph Historical Archive"),
            "FTHA": ("ftha", "Financial Times", "Financial Times Historical Archive"),
            "INDA": ("inda", "Independent", "The Independent Digital Archive"),
            "STHA": ("stha", "Sunday Times", "The Sunday Times Historical Archive"),
            "TLSH": ("tlsh", "Times Literary Supplement", "The Times Literary Supplement Historical Archive")}
MONTHS = ["Jan.", "Feb.", "Mar.", "Apr.", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]
DVI = re.compile(r"var dviResponse = (\{.*?\});\s*\n")


class Gale:
    """One portal session per product, asked one thing at a time."""

    def __init__(self, pace=PACE):
        self.pace, self.last, self.openers, self.pages, self.months = pace, 0.0, {}, {}, {}

    def get(self, prod, url, xhr=False):
        """`url`'s body, browsed as Chrome does (tools/gale_http.py): the
        portal's collections page, its link to the product (landing on
        Gale's search page), then each request with that page as Referer."""
        if prod not in self.openers:
            self.openers[prod] = Chrome()
            self.pages[prod] = None
            self.pages[prod] = self.fetch(prod, f"{PORTAL}/collections")[1]
            self.pages[prod] = self.fetch(prod, f"{PORTAL}/actions/auth.php?db={PRODUCTS[prod][0]}")[1]
        return self.fetch(prod, url, None, xhr)[0]

    def fetch(self, prod, url, wait=None, xhr=False):
        """(decoded body, final url) of `url`, paced."""
        time.sleep(max(0.0, self.last + self.pace - time.time()))
        wait = wait or 90
        try:
            status, body, final = self.openers[prod](url, click_headers(self.pages[prod], url, xhr),
                                                     verifies(url, PORTAL), wait)
            if status >= 400:
                raise urllib.error.HTTPError(final, status, f"HTTP {status}", None, None)
            return body.decode("utf-8", "replace"), final
        finally:
            self.last = time.time()

    def issues(self, prod, day):
        """Gale's issues of `day`: [{mcode, date, issueNumber, volume}]."""
        key = (prod, day.year, day.month)
        if key not in self.months:
            # A month the archive holds no issue of comes back empty, not {}.
            self.months[key] = json.loads(self.get(
                prod, f"{GALE}/browseByDate/issuesForMonth?monthYear=1{day:%Y%m}&prodId={prod}&u=alberta_portal",
                xhr=True) or "{}")
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
    # The 2000s also print the Saturday Jumbo and Times Two's quick crossword;
    # the Sunday papers their Mephisto, French, general knowledge and
    # two-into-one puzzles.
    # The Times' index on page 2 lists "Crossword 95 Today's Weather" (the
    # page it is on), and its news reports the championship.
    bad = re.compile(r"concise|solution|winners|report on|quick|jumbo|times ?(two|2)\b|\bt2\b|mephisto|french"
                     r"|general knowledge|two-into-one|champion\b|\bcontest|today's weather|miscellany"
                     + ("" if prod == "LSNR" else r"|listener")
                     + (r"|\btimes?\W+today\b" if prod == "TTDA" else "")
                     + (r"|^\W*[cg]ross-? ?w[oa]rd \d{1,3}\W*$" if prod == "TTDA" else ""), re.IGNORECASE)
    # Gale's OCR'd titles: "Grossword", "Crossward", "Cross-number" too; the
    # Telegraph's to 1990 or so are its clue heading, "No. 12,212 across".
    kind = re.compile(f"{KIND.pattern}|{ACROSS.pattern}", re.IGNORECASE) if prod == "TGRH" else \
        TIMES_KIND if prod == "TTDA" else KIND
    cands = [i for i, t in enumerate(titles) if kind.search(t) and not bad.search(t)]
    if prod == "TLSH":
        # The TLS's last solution is indexed under its puzzle's own title
        # ("TLS Crossword 603" beside "TLS Crossword 604"): the newest first.
        cands.sort(key=lambda i: -max(map(int, re.findall(r"\d+", titles[i].replace(",", ""))), default=0))
    if prod == "TTDA":
        cands.sort(key=lambda i: not TIMES_CRYPTIC.search(titles[i]))
    if number is not None:
        cands.sort(key=lambda i: not named(number).search(titles[i]))
    return cands[0] if cands else None


#: "Crossword" as Gale's OCR misreads it in the Times' own title: "Crossworld",
#: "Crossmord", "Crosswork", "Crosssword", "Crossoword", "Crossw0rd", "Crossworo",
#: "Crosswor" (found 2026-10-21 on dates whose contents then read as no crossword).
#: ("Corssword" too: the letters of "Cross" swapped, 2004-04-02.)
CROSSWORD_OCR = r"(?:[cg]ros{2,3}o?-?[wm][o0a]r[a-z0-9]{0,2}\b|[cg]ross-? ?w[oa]rd|[cg]orss-?w[oa]rd)"
#: Page 2's (or 1's) "The Times Today ... Crossword: 22" contents line, which
#: names the crossword's page: never the crossword itself, but its page when
#: the crossword's own article is untitled or misspelt beyond reading
#: (2004-03-10, 04-02, 04-08: the matcher kept this line as the crossword and
#: so saved page 1).
TIMES_TODAY = re.compile(r"\btimes?\W+today\b", re.IGNORECASE)
#: A title that may name the Times' crossword (TTDA's KIND).
TIMES_KIND = re.compile(f"{CROSSWORD_OCR}|[cg]ross-? ?number", re.IGNORECASE)

#: The Times' cryptic as Gale titles it: "The Times Crossword 23,303",
#: "Times Crossword", "The Times Crossword Puzzle No 17,563".
TIMES_CRYPTIC = re.compile(r"\btimes\W+" + CROSSWORD_OCR + r"\W*(puzzle\W*)?(no\b\W*)?(\d[\d,. ]*)?$", re.IGNORECASE)


#: The Saturday Times' own "Listener crossword" article (from No 3,090,
#: 1991-03-23): a row of kind LISTENER_KIND in TTDA, apart from the daily
#: crossword page (crossword() still rejects "listener" titles).
LISTENER_KIND = "listener"
#: Matcher version of that kind (own entry: the daily MATCHER is not moved).
MATCHER[LISTENER_KIND] = 1
LISTENER_ARTICLE = re.compile(r"\blistener\b.*\b(cross-? ?w[oa]rd|puzzle)|(cross-? ?w[oa]rd|puzzle).*\blistener\b",
                              re.IGNORECASE)
LISTENER_NOT = re.compile(r"report on|solution|winners|competition|champion\b|\bcontest|miscellany|"
                          r"today's weather|concise|quick", re.IGNORECASE)


def listener_article(titles, number=None):
    """The index into `titles` of the Saturday Times' Listener crossword
    article, or None: the one naming `number` first."""
    cands = [i for i, t in enumerate(titles) if LISTENER_ARTICLE.search(t) and not LISTENER_NOT.search(t)]
    if number is not None:
        cands.sort(key=lambda i: not named(number).search(titles[i]))
    return cands[0] if cands else None


def stale(prod, e):
    """Whether cache entry `e` is to be looked up again: cached by an older
    matcher, and a miss or (the Times) a title this one rejects or ranks
    below the cryptic's."""
    if e.get("kind") == LISTENER_KIND:
        return e.get("matcher", 0) < MATCHER[LISTENER_KIND] and "doc" not in e
    if e.get("matcher", 0) >= MATCHER[prod]:
        return False
    if "doc" not in e:
        return True
    return prod == "TTDA" and not (crossword(prod, [e["title"]]) == 0 and TIMES_CRYPTIC.search(e["title"]))


KIND = re.compile(r"[cg]ross-? ?(word|ward|number)", re.IGNORECASE)
ACROSS = re.compile(r"^\W*no\.? ?\d{1,2},?\d{3} across\W*$", re.IGNORECASE)


def named(number):
    """A title naming puzzle `number`, as 1309 or 1,309."""
    return re.compile(rf"(?<![\d,.]){number // 1000},?{number % 1000:03}(?![\d,])" if number >= 1000
                      else rf"(?<![\d,.]){number}(?![\d,])")


def report(titles, number):
    """The index into `titles` of the report on puzzle `number`, or None."""
    return next((i for i, t in enumerate(titles) if re.search(r"report on", t, re.IGNORECASE)
                 and named(number).search(t)), None)


def entry(prod, dvi, number=None, find=None):
    """The cache entry for the crossword in issue `dvi` (or the article
    `find(titles)` picks)."""
    arts = list(articles(dvi["originalDocument"].get("articleTableOfContents")))
    titles = [a["docTitle"] for a in arts]
    k = find(titles) if find else crossword(prod, titles, number)
    pages = {int(p["pageNumber"]): p["mediaRecordId"] for p in dvi.get("pageDocuments") or ()}
    if k is None and prod == "TTDA" and not find:
        # No article reads as the crossword: its page, from the contents line.
        for a in arts:
            m = TIMES_TODAY.search(a["docTitle"]) and re.search(r"crossw?\w*\W{1,3}(\d{1,3})\b", a["docTitle"], re.IGNORECASE)
            if m and int(m.group(1)) in pages:
                return {"doc": a["docId"], "title": "Crossword", "page": int(m.group(1)),
                        "records": [pages[int(m.group(1))]], "how": "contents-line page"}
    if k is None:
        return None
    a = arts[k]
    first = int(a["startingPage"])
    records = [pages[p] for p in range(first, first + int(a.get("pageCount") or 1)) if p in pages]
    if not records:
        return None
    return {"doc": a["docId"], "title": a["docTitle"], "page": first, "records": records}


def lookup(prod, day, gale, number=None, kind=None):
    """The entry for `day`, or {"why": ...} when Gale has no such crossword.
    `kind` LISTENER_KIND: the Saturday Times' Listener article, its entry
    marked with that kind."""
    issues = gale.issues(prod, day)
    if not issues:
        return {"why": "Gale has no issue that day"}
    titles = []
    for i in issues:
        dvi = gale.issue(prod, i)
        if kind == LISTENER_KIND:
            e = entry(prod, dvi, find=lambda ts: listener_article(ts, number))
            e = e and {**e, "kind": kind}
        else:
            e = entry(prod, dvi, number)
        if e:
            return e
        titles += [a["docTitle"] for a in articles(dvi["originalDocument"].get("articleTableOfContents"))]
    return {"why": "no crossword in the issue's contents", "crosswordish": [t for t in titles if "ross" in t.lower()]}


def lookup_report(prod, day, gale, number):
    """The entry for the report on puzzle `number` of `day`, with the "day"
    of its issue, or {"why": ...}."""
    for w in range(1, REPORT_WEEKS + 1):
        for i in gale.issues(prod, day + datetime.timedelta(weeks=w)):
            e = entry(prod, gale.issue(prod, i), find=lambda titles: report(titles, number))
            if e:
                d = i["date"]  # 1YYYYMMDD
                return {**e, "day": f"{d[1:5]}-{d[5:7]}-{d[7:9]}"}
    return {"why": f"no report on No {number} in the {REPORT_WEEKS} weeks after"}


def download_url(prod, day, e):
    """Gale's Download (PDF) for entry `e` of `day`, as a GET."""
    _, paper, archive = PRODUCTS[prod]
    cite = (f'"{e["title"].strip().rstrip(". ")}." {paper}, {day.day} {MONTHS[day.month - 1]} {day.year}, p. {e["page"]}. '
            f"{archive}, link.gale.com/apps/doc/{e['doc']}/{prod}?u=alberta_portal&sid=bookmark-{prod}.")
    q = urllib.parse.urlencode({"dl": e["doc"], "u": "alberta_portal", "p": prod, "recordIds": ",".join(e["records"]),
                                "citationTextJson": urllib.parse.quote(cite, safe="")})
    return f"{GALE}/callisto/BulkPDF/UBER2?{q}"


def page_url(prod, doc):
    """Gale's page for document `doc` (its citation's link.gale.com address
    lands here): the viewer a person reads it in and clicks Download from."""
    q = urllib.parse.urlencode({"p": prod, "u": "alberta_portal", "id": f"GALE|{doc}", "v": "2.1", "it": "r",
                                "sid": f"bookmark-{prod}"})
    return f"{GALE}/i.do?{q}"


def load(cache=CACHE):
    """The entries of `cache`: see read_log."""
    return read_log(cache)[0]


#: Gale's permalink for a document, the one its citation prints: opens the
#: article in the viewer in a portal session.
PERMALINK = "https://link.gale.com/apps/doc/{doc}/{prod}?u=alberta_portal&sid=bookmark-{prod}"


#: The cache files are append-only logs (SSD wear: docs.json, 19 MB, and
#: fetched.json, 3.6 MB, were rewritten whole after EVERY download, 75 GB in 23
#: h while the data grew by 4 GB). A file is the old single JSON object (the
#: snapshot, still read as before) followed by one line per later change,
#: {"_key": k, "_val": entry}; the last line for a key wins. `keep` appends one
#: line; `compact` folds the lines back into one snapshot, rarely.
RECORD = {"_key", "_val"}


def read_log(path):
    """({key: entry}, number of record lines) of a snapshot + record-lines file.
    A torn last line (a crash mid-append) is skipped."""
    try:
        text = Path(path).read_text()
    except OSError:
        return {}, 0
    dec, i, out, n = json.JSONDecoder(), 0, {}, 0
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            return out, n
        try:
            v, i = dec.raw_decode(text, i)
        except ValueError:
            j = text.find("\n", i)
            if j < 0:
                return out, n
            i = j
            continue
        if isinstance(v, dict) and set(v) == RECORD:
            out[v["_key"]] = v["_val"]
            n += 1
        elif isinstance(v, dict):
            out.update(v)


def keep(key, e, cache=CACHE):
    """Set `key` to `e` in `cache` by appending one line, under its own lock:
    two runs of tools/gale_fetch.py never lose each other's entries."""
    import fcntl
    cache.parent.mkdir(parents=True, exist_ok=True)
    line = "\n" + json.dumps({"_key": key, "_val": e}, sort_keys=True) + "\n"
    with open(cache.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(cache, "a") as f:
            f.write(line)


def compact(cache=CACHE, min_lines=1000):
    """Fold the record lines into one snapshot (tmp + replace), once there are
    `min_lines` of them: run at startup, so a file is rewritten once a run, not
    once a download."""
    import fcntl
    cache.parent.mkdir(parents=True, exist_ok=True)
    with open(cache.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        docs, n = read_log(cache)
        if n < min_lines:
            return False
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(docs, indent=0, sort_keys=True))
        tmp.replace(cache)
    return True


if __name__ == "__main__":
    prod, day = sys.argv[1], datetime.date.fromisoformat(sys.argv[2])
    e = lookup(prod, day, Gale())
    print(json.dumps(e, indent=1))
    if "doc" in e:
        print(download_url(prod, day, e))
