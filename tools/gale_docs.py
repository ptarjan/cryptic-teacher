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
MATCHER = {"TTDA": 8, "LSNR": 2, "TGRH": 6, "FTHA": 3, "INDA": 2, "STHA": 3, "TLSH": 2}
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
#: The citation's paper on a Sunday, for the archives holding a Sunday paper
#: (gale_inbox.SUNDAYS) beside the daily.
SUNDAY_PAPER = {"TGRH": "Sunday Telegraph", "INDA": "Independent on Sunday"}
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


def crossword(prod, titles, number=None, sunday=False):
    """The index into `titles` of the day's crossword, or None: a title
    naming a crossword, not the Concise or a solution or winners' list;
    the one naming `number` first. `sunday`: the Sunday Telegraph's or
    Independent on Sunday's issue, where only a numbered puzzle counts
    (SUNDAY_NUMBERED), not the book ads, features and winners notices."""
    # The 2000s also print the Saturday Jumbo and Times Two's quick crossword;
    # the Sunday papers their Mephisto, French, general knowledge and
    # two-into-one puzzles.
    # The Times' index on page 2 lists "Crossword 95 Today's Weather" (the
    # page it is on), and its news reports the championship.
    bad = re.compile(r"concise|solution|winners|report on|quick|jumbo|times ?(two|2)\b|\bt2\b|mephisto|french"
                     r"|general knowledge|champion\b|\bcontest|today's weather|miscellany"
                     + ("" if prod in ("TGRH", "TTDA") else r"|two-into-one")
                     + ("" if prod == "LSNR" else r"|listener")
                     + (r"|\btimes?\W+today\b" if prod == "TTDA" else "")
                     + (r"|^\W*[cg]ross-? ?w[oa]rd \d{1,3}\W*$" if prod == "TTDA" else ""), re.IGNORECASE)
    # Gale's OCR'd titles: "Grossword", "Crossward", "Cross-number" too; the
    # Telegraph's to 1990 or so are its clue heading, "No. 12,212 across".
    kind = re.compile(f"{KIND.pattern}|{ACROSS.pattern}|{SUNDAY_PUZZLE.pattern}", re.IGNORECASE) if prod == "TGRH" else \
        TIMES_KIND if prod == "TTDA" else KIND
    cands = [i for i, t in enumerate(titles) if kind.search(t) and not bad.search(t)]
    if sunday and prod in SUNDAY_PAPER:
        cands = [i for i in cands if sunday_numbered(prod, titles[i])]
    if prod == "TLSH":
        # The TLS's last solution is indexed under its puzzle's own title
        # ("TLS Crossword 603" beside "TLS Crossword 604"): the newest first.
        cands.sort(key=lambda i: -max(map(int, re.findall(r"\d+", titles[i].replace(",", ""))), default=0))
    if prod == "TTDA":
        cands.sort(key=lambda i: not TIMES_CRYPTIC.search(titles[i]))
    if prod == "INDA":  # the Sunday's puzzle is "Beelzebub Crossword No 954", beside "The Prize Crossword"
        cands.sort(key=lambda i: not re.search(r"beelzebub", titles[i], re.IGNORECASE))
    if prod == "TGRH":
        cands.sort(key=lambda i: not (TELEGRAPH_DAILY.search(titles[i]) or TELEGRAPH_PLAIN.search(titles[i])))
    if prod == "TGRH":  # the Sunday Telegraph: "Prize Puzzle No. 1976" (1990s), "Two-in-One Crossword" before
        cands.sort(key=lambda i: not SUNDAY_PUZZLE.search(titles[i]))
    if prod == "FTHA":
        # The puzzle itself is titled "Crossword" or "Crossword / N"; promos
        # ("Tomorrow: Out 10,000th Crossword") and "Ft Money Crossword" come after.
        cands = [i for i in cands if not re.search(r"money|tomorrow", titles[i], re.IGNORECASE)] or cands
        cands.sort(key=lambda i: not FT_DAILY.search(titles[i]))
    if number is not None:
        cands.sort(key=lambda i: not named(number).search(titles[i]))
    return cands[0] if cands else None


#: The Telegraph's daily puzzle as Gale titles it: "Crossword / 21,053" or
#: "Prize Crossword", ranked above articles about the paper's competition
#: ("How to Crack the Cryptic Crossword and Win £5,000", "Crossword
#: Competition / 14", "... Answers").
TELEGRAPH_DAILY = re.compile(r"^\W*(?:[cg]ross-? ?w[oa]rd\W*(?:/|no\.?)\W*\d[\d,]{2,}|prize\s+[cg]ross-? ?w[oa]rd)",
                             re.IGNORECASE)


#: The Sunday Telegraph's cryptic as Gale titles it: "Prize Puzzle No. 1976"
#: (1990s; its "General Knowledge Prize Crossword" is not it), "Sunday
#: Telegraph Two-in-One Crossword" / "Two-into-One" (to 1990), "Crossword
#: Competition No 1512".
SUNDAY_PUZZLE = re.compile(r"prize\s+puzzle\W*no\b\W*\d|two-in(?:to)?-one\s+cross", re.IGNORECASE)


#: A Sunday paper's puzzle as Gale titles it, always with its number or the
#: Two-in-One name: "Crossword No 954", "Beelzebub Crossword No 954",
#: "Prize Puzzle No. 2022", "Prize Crossword Competition No 1512". Not the
#: "Millennium Crossword Book" ads, features ("Crossword fun for all the
#: family"), holiday specials with no number or winners notices.
SUNDAY_NUMBERED = re.compile(r"[cg]ross-? ?w[oa]rd\W*(?:competition\W*)?no\b\.?\W*\d|prize\s+puzzle\W*no\b\W*\d"
                             r"|beelzebub\b.*\bno\b\.?\W*\d|competition\W*no\b\.?\W*\d", re.IGNORECASE)
#: The Independent on Sunday's cryptic goes unnumbered in some years (1999
#: "Beelzebub prize crossword", 2014-16 "Beelzebub Crossword" and, alone in
#: 2011, "The Prize Crossword"); the Beelzebub name or that exact title is no ad.
INDA_CRYPTIC = re.compile(r"^\W*(?:beelzebub\b.*cross|the prize cross-? ?w[oa]rd\W*$)", re.IGNORECASE)
#: Gale's OCR spells the dashes as hyphens, en or em dashes, spaced or not,
#: and once a "Christmas" or a hyphen before "Crossword" (1988-91).
SUNDAY_TWO_IN_ONE = re.compile(r"two\s*[-\u2013\u2014]\s*in(?:to)?\s*[-\u2013\u2014]\s*one[\s\-\u2013\u2014]*(?:christmas\s+)?cross",
                               re.IGNORECASE)


def sunday_numbered(prod, title):
    """Whether `title` is a real Sunday puzzle of `prod` (see SUNDAY_NUMBERED);
    the Two-in-One is the Sunday Telegraph's only."""
    if prod == "INDA" and INDA_CRYPTIC.search(title):
        return True
    return bool(SUNDAY_NUMBERED.search(title) or (prod == "TGRH" and SUNDAY_TWO_IN_ONE.search(title)))


#: The FT's daily puzzle title: "Crossword" or "Crossword / 9,876".
FT_DAILY = re.compile(r"^\W*[cg]ross-? ?w[oa]rd(\W*/\W*\d[\d,]*)?\W*$", re.IGNORECASE)


#: The Telegraph's early (and some later) daily puzzle, titled with no number.
TELEGRAPH_PLAIN = re.compile(r"^\W*(today's )?crossword( puzzle)?\W*$", re.IGNORECASE)


def numbered(title):
    """Whether a Telegraph `title` carries its puzzle's number ("Crossword /
    21,053", "No. 12,212 across") or is the "Prize Crossword": not a
    competition article ("... Win £5,000", "Crossword Competition / 14"), or
    its plain "Crossword", "Today's Crossword Puzzle" (TELEGRAPH_PLAIN)."""
    return bool(TELEGRAPH_PLAIN.search(title) or re.search(r"(?<![£\d,.])\d{1,2},?\d{3}(?![\d,])", title)
                or re.search(r"prize\s+[cg]ross-? ?w[oa]rd", title, re.IGNORECASE)
                or re.search(r"[cg]ross-? ?w[oa]rd\W*no\.?\W*\d", title, re.IGNORECASE) or SUNDAY_PUZZLE.search(title))  # the Sunday's "Crossword No. 214"


#: "Crossword" as Gale's OCR misreads it in the Times' own title: "Crossworld",
#: "Crossmord", "Crosswork", "Crosssword", "Crossoword", "Crossw0rd", "Crossworo",
#: "Crosswor" (found 2026-10-21 on dates whose contents then read as no crossword).
#: ("Corssword" too: the letters of "Cross" swapped, 2004-04-02; "Cossword",
#: its "r" lost, 1936-02-06; "Crcssword", its "o" read "c", 1968-08-10;
#: "Crassword", 1978-06-27; "Crosword", an "s" lost, 2003-12-27.)
CROSSWORD_OCR = r"(?:[cg]r?[o0ca]s{1,3}o?-?[wm][o0a]r[a-z0-9]{0,2}\b|[cg]ross-? ?w[oa]rd|[cg]orss-?w[oa]rd)"
#: Page 2's (or 1's) "The Times Today ... Crossword: 22" contents line, which
#: names the crossword's page: never the crossword itself, but its page when
#: the crossword's own article is untitled or misspelt beyond reading
#: (2004-03-10, 04-02, 04-08: the matcher kept this line as the crossword and
#: so saved page 1).
TIMES_TODAY = re.compile(r"\btimes?\W+today\b", re.IGNORECASE)
#: The Times' solution to its previous cryptic, which it prints on the
#: cryptic's own page: "Solution of Puzzle No 16,022" (1983), "Solution to
#: yesterday's crossword 22,544" (2003). Some issues index their crossword
#: page only by this line, the puzzle itself untitled (1983's Saturdays,
#: 2003-12-27), and a room asking for the issue that holds an earlier
#: puzzle's answers wants this page. A five-digit number only: the Concise,
#: Times Two, Jumbo and Listener solutions name fewer digits or no
#: "crossword"/"puzzle" ("Solution to No 3549 Why?").
TIMES_SOLUTION = re.compile(r"^\W*solution\W+(?:of|to)\W+(?:yesterday'?s\W+)?(?:the\W+)?(?:times\W+)?(?:puzzle|"
                            + CROSSWORD_OCR + r")\W*(?:puzzle\W*)?(?:no\b\.?\W*)?\d{2}[,.]?\d{3}\W*$", re.IGNORECASE)
#: The Sunday Times cryptic's title as OCR left it with "Cross" lost: "The
#: Sunday Times Word" (1998-02-08, its No 3742 and the solution to 3741).
STHA_WORD = re.compile(r"^\W*the\W+sunday\W+times\W+word\W*$", re.IGNORECASE)
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


#: The Times Jumbo cryptic (Saturdays, and Bank Holiday weekdays) as Gale
#: titles it: "Jumbo Crossword 129" (1997), "Jumbo crossword no 838" (2009),
#: "Christmas Jumbo Crossword 141", OCR-misread ("Jumbo Crosswrd 140"). A row
#: of kind JUMBO_KIND in TTDA, apart from the daily cryptic that crossword()
#: still picks (it rejects "jumbo") and from the Listener article. Not its
#: solution or winners, a competition or prize article ("Win GBP 100 in the
#: May Day jumbo crossword"), the Concise or sports Jumbo, or Times Two's.
JUMBO_KIND = "jumbo"
MATCHER[JUMBO_KIND] = 1
JUMBO_ARTICLE = re.compile(r"\bjumbo\b\W*(?:\w+\W+){0,2}?[cg]ro?s", re.IGNORECASE)
JUMBO_NOT = re.compile(r"solution|winners|answers|report on|competition|\bwin\b|concise|sports|knowledge|quick|mini\b"
                       r"|times ?(two|2)\b|\bt2\b|today's weather", re.IGNORECASE)


def jumbo_article(titles, number=None):
    """The index into `titles` of the Times Jumbo cryptic, or None: the one
    naming `number` first, then a numbered title ("Jumbo Crossword 129")
    before an unnumbered one."""
    cands = [i for i, t in enumerate(titles) if JUMBO_ARTICLE.search(t) and not JUMBO_NOT.search(t)]
    cands.sort(key=lambda i: not re.search(r"\d", titles[i]))
    if number is not None:
        cands.sort(key=lambda i: not named(number).search(titles[i]))
    return cands[0] if cands else None


#: The Jumbo's solution, printed one or two Saturdays after the puzzle (same
#: Saturday/Bank Holiday issues, on the puzzles page): "Solution to Jumbo 477",
#: "Solution to Bank Holiday Jumbo 168", "Solution to Jumbo Corssword 169"
#: (OCR). The title's number is the puzzle's, not the issue's own Jumbo. A row
#: of kind JUMBO_SOLUTION_KIND, saved apart from the puzzles (gale_fetch
#: JUMBO_SOLUTIONS_DIR); crossword() keeps rejecting "solution" titles.
JUMBO_SOLUTION_KIND = "jumbo-solution"
#: Matcher 2: 1997-2003 days also search the SOLUTION_WEEKS issues after the
#: puzzle for the one naming its number (the matcher 1 misses are looked up again).
MATCHER[JUMBO_SOLUTION_KIND] = 2
SOLUTION_WEEKS = 5
SOLUTION_WINDOW_END = datetime.date(2004, 1, 1)
JUMBO_SOLUTION_ARTICLE = re.compile(r"\bsolutions?\b.*\bj?umbo\b|\bj?umbo\b.*\bsolutions?\b", re.IGNORECASE)
JUMBO_SOLUTION_NOT = re.compile(r"winners|report on|competition|\bwin\b|concise|sports|knowledge|quick|mini\b"
                                r"|times ?(two|2)\b|\bt2\b|today's weather|listener", re.IGNORECASE)


def jumbo_solution_article(titles, number=None):
    """The index into `titles` of the solution to a Times Jumbo, or None: the
    one naming `number` first, then a numbered title before an unnumbered one."""
    cands = [i for i, t in enumerate(titles)
             if JUMBO_SOLUTION_ARTICLE.search(t) and not JUMBO_SOLUTION_NOT.search(t)]
    cands.sort(key=lambda i: not re.search(r"\d", titles[i]))
    if number is not None:
        cands.sort(key=lambda i: not named(number).search(titles[i]))
    return cands[0] if cands else None


#: From about 2004 the Jumbo's solution is no article of its own: it is one of the
#: answers on the page titled "Answers" ("Solution to Cryptic Jumbo 569", 2005-03-19
#: p.151), so that article is read for a line of the Jumbo solution.
ANSWERS_ARTICLE = re.compile(r"^\W*(?:crossword\W+)?(?:answers|solutions?)\W*$", re.IGNORECASE)
JUMBO_SOLUTION_TEXT = JUMBO_SOLUTION_ARTICLE


def jumbo_answers_entry(prod, dvis, gale):
    """The entry of an "Answers" article of the issues `dvis` whose scanned text has
    a Jumbo solution line, marked how "answers page", or None. One viewer-page
    request per candidate (not a download)."""
    for dvi in dvis:
        arts = [a for a in articles(dvi["originalDocument"].get("articleTableOfContents"))
                if str(a["docId"]).upper() not in REJECTED_DOCS and ANSWERS_ARTICLE.search(a["docTitle"] or "")]
        by_page = {int(p["pageNumber"]): p["mediaRecordId"] for p in dvi.get("pageDocuments") or ()}
        for a in arts[:TEXT_LOOKUPS]:
            if any(JUMBO_SOLUTION_TEXT.search(t[:60]) and not JUMBO_SOLUTION_NOT.search(t[:60]) for t in viewer_text(gale.get(prod, page_url(prod, a["docId"])))):
                e = entry_of(a, by_page)
                if e:
                    return {**e, "how": "answers page"}
    return None


#: The finder of each kind of row in TTDA beside the daily cryptic.
KINDS = {LISTENER_KIND: listener_article, JUMBO_KIND: jumbo_article, JUMBO_SOLUTION_KIND: jumbo_solution_article}


#: Documents known not to be the day's cryptic (one line each, last word the
#: docId): never picked, and an entry naming one is looked up again.
REJECTED = Path(__file__).with_name("gale_rejected.txt")


def rejected(path=None):
    """The upper-cased docIds in the rejected list (none if no file)."""
    try:
        lines = (path or REJECTED).read_text().splitlines()
    except OSError:
        return set()
    return {ln.split()[-1].upper() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")}


REJECTED_DOCS = rejected()


def stale(prod, e):
    """Whether cache entry `e` is to be looked up again: its document is
    rejected, or it was cached by an older matcher, and a miss or (the
    Times) a title this one rejects or ranks below the cryptic's, or (the
    Telegraph) a title with no puzzle number."""
    if str(e.get("doc", "")).upper() in REJECTED_DOCS:
        return True
    if e.get("kind") in KINDS:
        return e.get("matcher", 0) < MATCHER[e["kind"]] and "doc" not in e
    if e.get("matcher", 0) >= MATCHER[prod]:
        return False
    if "doc" not in e:
        return True
    if prod == "TGRH":  # a competition article the older matcher picked
        return not numbered(e.get("title") or "")
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


def entry(prod, dvi, number=None, find=None, sunday=False):
    """The cache entry for the crossword in issue `dvi` (or the article
    `find(titles)` picks)."""
    arts = [a for a in articles(dvi["originalDocument"].get("articleTableOfContents"))
            if str(a["docId"]).upper() not in REJECTED_DOCS]
    titles = [a["docTitle"] for a in arts]
    k = find(titles) if find else crossword(prod, titles, number, sunday)
    pages = {int(p["pageNumber"]): p["mediaRecordId"] for p in dvi.get("pageDocuments") or ()}
    if k is None and prod == "TTDA" and not find:
        # No article reads as the crossword: its page, from the contents line.
        for a in arts:
            m = TIMES_TODAY.search(a["docTitle"]) and re.search(r"crossw?\w*\W{1,3}(\d{1,3})\b", a["docTitle"], re.IGNORECASE)
            if m and int(m.group(1)) in pages:
                return {"doc": a["docId"], "title": "Crossword", "page": int(m.group(1)),
                        "records": [pages[int(m.group(1))]], "how": "contents-line page"}
    if k is None and prod == "TTDA" and not find:
        # Nor a contents line: the page of the solution to the last cryptic.
        k = next((i for i, t in enumerate(titles) if TIMES_SOLUTION.search(t)), None)
        e = entry_of(arts[k], pages) if k is not None else None
        return {**e, "how": "solution's page"} if e else None
    if k is None and prod == "STHA" and not find:
        # Its cryptic's title with "Cross" lost to OCR (1998-02-08: No 3742).
        k = next((i for i, t in enumerate(titles) if STHA_WORD.search(t)), None)
    if k is None:
        return None
    return entry_of(arts[k], pages)


def entry_of(a, pages):
    """The cache entry for article `a`, its pages' records among `pages`
    ({page number: record}), or None when Gale holds none of them."""
    first = int(a["startingPage"])
    records = [pages[p] for p in range(first, first + int(a.get("pageCount") or 1)) if p in pages]
    if not records:
        return None
    return {"doc": a["docId"], "title": a["docTitle"], "page": first, "records": records}


#: A Times article whose title does not name the crossword: none, or the
#: paper's own masthead ("The Saturday Times", "The Times"): a whole-page
#: article of scanned text, which may hold the crossword (2000-02-05 p.32).
MASTHEAD = re.compile(r"^\W*(?:no\s+title|untitled|(?:the\W+)?(?:saturday\W+|weekend\W+)?times)?\W*$", re.IGNORECASE)
#: Lookups of viewer pages per issue, and the weeks either side of a day whose
#: found crossword names the page to try first.
TEXT_LOOKUPS = 3
NEAR_WEEKS = 6
#: A line of an article's scanned text that is the Times' cryptic's title with
#: its five-digit number ("THE TIMES CROSSWORD NO 21,331"), or its solution
#: notice (TIMES_SOLUTION: "Solution to Puzzle No 21,330").
TEXT_PUZZLE = re.compile(r"^\W*(?:the\W+)?(?:times\W+)?" + CROSSWORD_OCR + r"\W*(?:puzzle\W*)?(?:no\b\.?\W*)?\d{2}[,.]?\d{3}\b",
                         re.IGNORECASE)
TEXT_SOLUTION = TIMES_SOLUTION


def viewer_text(body):
    """The lines of scanned text on a Gale viewer page ("fullTexts" in its
    data), [] when it carries none."""
    i = body.find('"fullTexts":')
    if i < 0:
        return []
    try:
        v, _ = json.JSONDecoder().raw_decode(body, i + len('"fullTexts":'))
    except ValueError:
        return []
    return [t for t in v if isinstance(t, str)]


def text_is_crossword(lines):
    """Whether scanned `lines` hold a numbered Times cryptic title or the
    notice of an earlier puzzle's solution."""
    return any(len(t) < 80 and (TEXT_PUZZLE.search(t) or TEXT_SOLUTION.search(t)) for t in lines)


def near_pages(prod, day, docs):
    """The pages the nearest found issues on `day`'s weekday had their
    crossword on, nearest first (NEAR_WEEKS weeks either side)."""
    out = []
    for w in range(1, NEAR_WEEKS + 1):
        for sign in (-1, 1):
            e = docs.get(f"{prod}/{day + datetime.timedelta(weeks=sign * w)}")
            if e and "doc" in e and e.get("page") not in out:
                out.append(e["page"])
    return out


def text_candidates(arts, pages):
    """Up to TEXT_LOOKUPS of articles `arts` to read, best first: one whose
    title names a crossword the title matcher rejects ("Jumbo crossword
    winners", the winners article that prints the puzzle, 1971-04-15 p.30),
    then those on `pages` (nearest page first; untitled or masthead-titled
    ones, then the longer), then any other untitled or masthead-titled one."""
    def bare(a):
        return bool(MASTHEAD.search(a["docTitle"] or ""))
    def rank(a):
        p = int(a["startingPage"])
        return (not TIMES_KIND.search(a["docTitle"] or ""), pages.index(p) if p in pages else len(pages),
                not bare(a), -int(a.get("pageCount") or 1))
    pool = [a for a in arts if int(a["startingPage"]) in pages or bare(a) or TIMES_KIND.search(a["docTitle"] or "")]
    return sorted(pool, key=rank)[:TEXT_LOOKUPS]


def text_entry(prod, day, dvis, gale, docs=None):
    """The entry of the article whose scanned text reads as the crossword,
    among a few candidates of the issues `dvis` that the contents index did
    not name (see text_candidates), or None. Each is one viewer-page request in
    `gale`'s session: not downloads, so outside the download cap."""
    if prod != "TTDA":
        return None
    if docs is None:
        docs = load()
    pages = near_pages(prod, day, docs)
    seen, n = set(), 0
    for dvi in dvis:
        arts = [a for a in articles(dvi["originalDocument"].get("articleTableOfContents"))
                if str(a["docId"]).upper() not in REJECTED_DOCS and a["docId"] not in seen]
        by_page = {int(p["pageNumber"]): p["mediaRecordId"] for p in dvi.get("pageDocuments") or ()}
        for a in text_candidates(arts, pages)[:TEXT_LOOKUPS - n]:
            n += 1
            seen.add(a["docId"])
            if text_is_crossword(viewer_text(gale.get(prod, page_url(prod, a["docId"])))):
                e = entry_of(a, by_page)
                if e:
                    return {**e, "title": "Crossword", "how": "text search"}
    return None


def jumbo_solution_window(prod, day, gale):
    """The entry of the "Solution to Jumbo N" article, N the Jumbo printed on
    `day`, in the SOLUTION_WEEKS issues after it (1997-2003: the solution
    runs a few weeks after the puzzle), marked kind, or None."""
    import gale_jumbo
    number = gale_jumbo.number_on(day)
    if number is None:
        return None
    for w in range(1, SOLUTION_WEEKS + 1):
        for i in gale.issues(prod, day + datetime.timedelta(weeks=w)):
            dvi = gale.issue(prod, i)
            e = entry(prod, dvi, find=lambda ts: jumbo_solution_article(ts, number))
            if e and named(number).search(e.get("title") or ""):
                return {**e, "kind": JUMBO_SOLUTION_KIND, "how": f"solution window +{w}w"}
    return None


def lookup(prod, day, gale, number=None, kind=None, docs=None):
    """The entry for `day`, or {"why": ...} when Gale has no such crossword.
    `kind` LISTENER_KIND: the Saturday Times' Listener article, JUMBO_KIND:
    its Jumbo cryptic, the entry marked with that kind."""
    issues = gale.issues(prod, day)
    if not issues:
        return {"why": "Gale has no issue that day"}
    titles, dvis = [], []
    for i in issues:
        dvi = gale.issue(prod, i)
        dvis.append(dvi)
        if kind in KINDS:
            e = entry(prod, dvi, find=lambda ts: KINDS[kind](ts, number))
            e = e and {**e, "kind": kind}
        else:
            e = entry(prod, dvi, number, sunday=day.weekday() == 6)
        if e:
            return e
        titles += [a["docTitle"] for a in articles(dvi["originalDocument"].get("articleTableOfContents"))]
    if kind not in KINDS:
        e = text_entry(prod, day, dvis, gale, docs)
        if e:
            return e
    if kind == JUMBO_SOLUTION_KIND and day < SOLUTION_WINDOW_END:
        e = jumbo_solution_window(prod, day, gale)
        if e:
            return e
    if kind == JUMBO_SOLUTION_KIND:
        e = jumbo_answers_entry(prod, dvis, gale)
        if e:
            return {**e, "kind": kind}
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
    if day.weekday() == 6 and prod in SUNDAY_PAPER:
        paper = SUNDAY_PAPER[prod]
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
