#!/usr/bin/env python3
"""The Listener crosswords of 1930-91, read from the pages
tools/gale_fetch.py downloads from Gale's Listener Historical Archive
(through the Alberta Research Portal), and those of 1991-2014 from the
Saturday Times pages it downloads from the Times Digital Archive (SAVED/TIMES):
a Times page is matched by its citation ("Listener Crossword No. 3138: ..."
Times, 22 Feb. 1992) against the year index's Times rows (index(times=True)),
and only its Listener block is read (times_block: under the "Listener
Crossword" title, between the gutters either side of its ACROSS and DOWN
lists), not the page's other puzzles, a concise or the Times Two.

wanted() is what tools/gale_fetch.py fetches: every puzzle the magazine
printed that is neither filed nor read, from the Listener Team's year index
(listenercrossword.com /Years/Y<year>.html, read for the numbers and dates
only), and the "Report on Crossword No. N" page printing each one's answers
about two issues later, while no saved page holds it. lay_out_fetched puts
each downloaded page in SAVED, named for its issue's date (a report page by
its document alone), and the clue OCR every scan filer shares
(tools/ocr_clues.py's readers, tools/archive_org_listener.py's vote) reads
it.

    python3 tools/gale_listener.py read [--inbox DIR] [--store DIR]   # read every saved page not yet read
    python3 tools/gale_listener.py match FILE...      # which puzzle each file is, and how that was read

A file is matched to its puzzle by the date in its name, else the puzzle
number in its name, else the number its Gale citation's article title
prints ("No. 22—A French Crossword"), else the date the citation prints,
else the number our readers read in its title ("Crossword No. 1,234"); a
date gives the puzzle the index puts on that issue. A page may also print a
past puzzle's solution, "Report on Crossword No. 16" with the filled grid:
the citation or the page's words name it, and the ledger keeps it as the
file's "reports". Each file is read once: STORE/ledger.jsonl is keyed by
the file's sha256 (and VERSION), one row appended a read, so a re-run reads
only files new or changed. The standing pass reads each new page as a unit
of its own (tools/edition_queue.py, plan() and read_unit(): its own
process, time limit and lock), planned every minute, so a page is read
within minutes of landing. With OCR_REMOTE set, a page's read (its match,
clue OCR and grids) runs on the desktop through tools/ocr_remote.py
(read_remote), all but its whole-page Tesseract read; the filing runs
here, and the whole read when the desktop is unset, busy or fails.

What a page gives is its clues: STORE/listener-N.json, the reading
tools/archive_org_listener.py writes (clue text and count by light, the
vote's blanks, the source). A puzzle file needs the grid and answers too,
which a barred grid's clues alone do not give: read_unit then runs
tools/file_gale_listener.py, which joins each reading with its page's grid
(tools/listener_grid.py) and files what passes unsolved; the later
report's letters are kept as a check on the solve, never filed.
"""
import argparse
import collections
import datetime
import difflib
import hashlib
import html
import itertools
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
from pathlib import Path
import archive_org_listener as al
import file_archive_org_puzzles as fa
import gale_inbox as gi
import listener_puzzles as lp
import media_manifest as mm
import clue_text
import downloads
import ocr_clues

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent

HOME = Path(os.path.expanduser("~/.cache/gale_listener"))
#: The saved Listener pages, on the media disk (the Mac's, over its share on the
#: desktop): those Paul downloaded by hand before the fetcher, loose in the
#: folder; those tools/gale_fetch.py keeps as GALE_<doc>.pdf in its FETCHED
#: subfolder (gale_fetch.fetched_dir), and the copy lay_out_fetched names
#: for its date beside them. page_files lists both; one unit per Gale
#: document (plan): each download of a document is stamped anew, so its
#: copies hash apart. (Until 10-23 this was ~/.cache/gale_listener/files on
#: the Mac, which the desktop's queue could not see: it planned no page.)
SAVED = downloads.GALE_CROSSWORDS / "Listener"
FETCHED = "Fetched"
#: The Saturday Times' Listener pages (1991-2014, No 3,090 on), which
#: tools/gale_fetch.py keeps apart from the magazine's (its
#: TIMES_LISTENER_DIR): SAVED/TIMES. page_files lists them with the
#: magazine's; each is a broadsheet page with other puzzles on it, read
#: for the Listener's own block only (times_block).
TIMES = Path("Times") / FETCHED
#: The last year of the Times' run gale_fetch fetches (its TIMES_LISTENER).
TIMES_LAST_YEAR = 2014
OCR_CACHE = HOME / "ocr"
#: The readings and the ledger: derived from Paul's pages, kept beside the
#: series' other source data.
STORE = lp.CACHE / "gale"
YEARS = lp.CACHE / "years"
#: The Listener magazine's last issue; the puzzle moved to The Times after it.
FIRST_YEAR, LAST_ISSUE = 1930, datetime.date(1991, 1, 3)
#: Bumped when the reading changes, so every file is read again.
VERSION = 28
PORTAL = "https://abresearchportal.ca/collections"
DOC_URL = "https://go.gale.com/ps/retrieve.do?docId=GALE%7C{}&prodId=LSNR&userGroupName=alberta_portal"
#: A Times page's citation: '"Listener Crossword No. 3138: Playflare by
#: Apex." Times, 22 Feb. 1992, p. 91', '"The Listener Crossword 3890."
#: Times, 12 Aug. 2006', '"The Listener Crossword." Times, 14 Nov. 1992'.
TIMES_CITED = re.compile(r'^\W*"([^"]*?)\W*"\s*Times\b\W*([0-3]?\d)\s+' + gi.MON + r"\s*(\d{4})", re.IGNORECASE)
#: The number in its article title.
TIMES_NUMBER = re.compile(r"\bcrossword\W{0,3}(?:n[o0]\W{0,3})?(\d[,.]?\d{3})\b", re.IGNORECASE)

DATES = gi.date_patterns(r"19[2-9]\d")
#: A puzzle number in a file name: after "No", "Listener", "Crossword" or
#: "#", or a bare number that is no year of the run.
LABELLED = re.compile(r"(?:\bno|listener|crossword|puzzle|#)\W{0,3}(\d[,.]?\d{0,3})(?![\d,])", re.IGNORECASE)
BARE = re.compile(r"(?<![\d,.])(\d{1,4})(?![\d,])")
#: The citation a Gale PDF prints: "The Listener, vol. 3, no. 64, 2 Apr. 1930, p. 612"
#: (the Times archive's drops the "The": "Times, 3 Jan. 1987, p. 20").
CITED = re.compile(r"(?:The )?Listener\b[^\n]{0,80}?([0-3]?\d)\s+" + gi.MON + r"\s*(19[2-9]\d)(?:,\s*p\.?\s*(\d+))?",
                   re.IGNORECASE)
#: The title our readers read on the page.
TITLE = re.compile(r"crossword\W{0,3}(?:puzzle\W{0,3})?n[o0]\.?\s*(\d[,.]?\d{0,3})(?![\d,])", re.IGNORECASE)
#: The article title a Gale PDF's citation quotes, before "The Listener".
ARTICLE = re.compile(r'^\W*"(.*?)\W*"\s*(?:The )?Listener\b', re.DOTALL)
#: A puzzle's own title: "No. 22—A French Crossword", "Crossword No. 19",
#: "Our Crossword Puzzle No. 1". A "Competition No." is the magazine's own
#: competition count, not the puzzle's.
#: From No 1,000 (1949) the titles print a thousands comma, "Crossword No.
#: 1,001" (FIGURE; Gale's text has "1.403" and "1, 349" too): \d{1,4}\b alone
#: read it as No 1, so ~870 pages from 1949 on were each taken for one of the
#: first nine puzzles. num() reads one.
FIGURE = r"(\d{1,3}[,.] ?\d{3}|\d{1,4})\b"
NUMBERED = re.compile(r"^n[o0]\.?\s*" + FIGURE + r"|crossword\W{0,3}(?:puzzle\W{0,3})?n[o0]\.?\s*" + FIGURE,
                      re.IGNORECASE)
#: The report printing a past puzzle's solution grid and solvers:
#: "Report on Crossword No. 16", "Report on Wireless Crossword No. 38",
#: "Notes on Crossword No. 287". Not a pointer to it on another page, the
#: line going on to a page: No 17's "(The Report on Crossword No. 15 will
#: be found on page 155)" (read "twill be found") held No 15's report
#: saved, so p. 155 was never fetched; No 20's "... No 18 gill be found on
#: the next page" No 18's; No 154's "Report on Crossword No. 15[2] on p.
#: 303." No 15's.
REPORT = re.compile(r"(?:report|notes)\s+on\b[^\n]{0,40}?crossword\W{0,3}n[o0]\.?\s*" + FIGURE
                    + r"(?![^\n]{0,40}\b(?:page\b|on\s+p\.))", re.IGNORECASE)
#: What only a page printing the week's puzzle has: its "CLUES" heading (in
#: capitals: a report's notes head theirs "NOTES", the rules say "Clues are
#: not given") or its "This Week's Crossword" title, the swash C often read
#: "(" ("This Weeks (rossword"; not "This Week's Crossword is printed on page
#: 709", "will be found on page vii"), or its entry form's "Prize: ..., Closing date" (a report's are
#: "Prizewinners").
PUZZLE_HERE = re.compile(r"\bCLUES\b|\bPrize\W{0,2}:|\bClosing\s+date|(?i:week\W{0,2}s?\W{0,5}\S{0,3}rossword(?!\W*(?:is|will|be)\b))")
#: A page saying the week's puzzle is elsewhere ("This week's Crossword will
#: be found on page vii", "... is printed on page 709"), or heading a report
#: ("Report on (rossword No. I42": its number seldom read right).
ELSEWHERE = re.compile(r"week\W{0,2}s?\W{0,5}\S{0,3}rossword\W*(?:is|will|be)\b|\breport\s+on\W+\S{0,3}rossword",
                       re.IGNORECASE)


def title_of(text):
    """TITLE's first match in a page's words `text` that is no report's
    number: No 17's page (1930), its citation unread, was read as No 15 off
    "(The Report on Crossword No. 15 will be found on page 155)"."""
    return next((m for m in TITLE.finditer(text) if not re.search(
        r"(?:report|notes)\s+on\W+\S*\W*$", text[max(0, m.start() - 30):m.start()], re.IGNORECASE)), None)


def puzzle_here(text, number):
    """Whether a page's words `text` print the week's puzzle: PUZZLE_HERE, or
    its own number `number` titled ("No. 147—'Diagonal II'") and not as the
    report's ("Report on Crossword No. 145")."""
    if PUZZLE_HERE.search(text):
        return True
    own = re.compile(rf"\bn[o0][.,]?\s*{number}\b", re.IGNORECASE) if number is not None else None
    return bool(own) and any(not re.search(r"(?:report|notes)\s+on\W+\S*\W*$", text[max(0, m.start() - 30):m.start()],
                                           re.IGNORECASE) for m in own.finditer(text))


#: A browser's copy suffix, "GM2500066057 (1).pdf": no puzzle number.
COPY = re.compile(r"\s*\(\d+\)(?=\.\w+$)")


# ------------------------------------------------------------ the index

def year_page(year, cache=YEARS, fetch=True):
    """The Listener Team's index page for `year`, cached; fetched at their
    1-2 s pace when missing (listenercrossword.com, never Gale)."""
    path = cache / f"Y{year}.html"
    if not path.exists():
        if not fetch:
            return ""
        cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(lp.get(f"{lp.SITE}/Years/Y{year}.html"))
        time.sleep(2)
    return path.read_text(errors="replace")


CELL = re.compile(r'<td class="(num|title|setter|date)">(.*?)</td>', re.DOTALL)


def parse_year(text, year):
    """[{number, title, setter, date}] of one year page's rows."""
    out, row = [], {}
    for cls, raw in CELL.findall(text):
        val = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        if cls == "num":
            row = {"number": int(val)} if val.isdigit() else {}
        elif row:
            row[cls] = val
            if cls == "date":
                try:
                    day, mon = val.split()
                    row["date"] = datetime.date(year, gi.MONTHS[mon[:3].lower()], int(day))
                except (ValueError, KeyError):
                    row = {}
                    continue
                row["setter"] = None if row.get("setter") in ("—", "") else row.get("setter")
                out.append(row)
                row = {}
    return out


#: SSD manifests (tools/media_manifest.py) standing in for what wanted() would
#: otherwise ask the media disk each gale_fetch plan (Paul 2026-10-14: nothing
#: scheduled scans the spinning disk): the year pages' parsed rows, the
#: readings kept (STORE/listener-N.json) and the ledger's number and reports.
YEARS_MANIFEST = "listener-years"
READINGS_MANIFEST = "listener-readings"
LEDGER_MANIFEST = "listener-ledger"


def _year_rows(y, cache, fetch, memo):
    """One year page's rows. A page on the media disk is read once, its rows
    kept in YEARS_MANIFEST (a year page is never rewritten); a cache elsewhere
    (a test's) is read each time."""
    if not mm.on_media(cache):
        return parse_year(year_page(y, cache, fetch), y)
    if y in memo:
        return [{**r, "date": datetime.date.fromisoformat(r["date"])} for r in memo[y]]
    text = year_page(y, cache, fetch)
    rows = parse_year(text, y)
    if text:
        mm.record(YEARS_MANIFEST, cache, year=y, rows=[{**r, "date": r["date"].isoformat()} for r in rows])
    return rows


def index(cache=YEARS, fetch=True, times=False):
    """[{number, title, setter, date}] of every Listener the magazine printed,
    and with `times` those the Saturday Times printed too, to
    TIMES_LAST_YEAR (what a Times page is matched against; wanted() asks
    the magazine's archive for the magazine's alone)."""
    rows = {}
    memo = mm.memo(YEARS_MANIFEST, "year", "rows") if mm.on_media(cache) else {}
    for y in range(FIRST_YEAR, (TIMES_LAST_YEAR if times else LAST_ISSUE.year) + 1):
        for r in _year_rows(y, cache, fetch, memo):
            if times or r["date"] <= LAST_ISSUE:
                rows[r["number"]] = r
    return [rows[n] for n in sorted(rows)]


def printed(row):
    """Whether the index row is a puzzle the magazine printed: the index
    keeps a number for a week with "[No crossword]"."""
    return not row["title"].startswith("[")


def by_date(idx, day):
    """The puzzle printed in the issue of `day` (within its week), or None."""
    near = [r for r in idx if abs((r["date"] - day).days) <= 3 and printed(r)]
    return min(near, key=lambda r: abs((r["date"] - day).days)) if near else None


# ------------------------------------------------------------ matching a file

def name_number(name):
    """The Listener number a file name spells, or None."""
    name = COPY.sub("", gi.DOC_ID.sub(" ", name))
    for rx, m in ((LABELLED, None), (BARE, None)):
        for m in rx.finditer(name):
            n = int(re.sub(r"\D", "", m.group(1)))
            if rx is LABELLED or not 1929 <= n <= 1991:
                return n
    return None


def page_words(img, key):
    """[(x0, y0, x1, y1, text)] the fine-tuned Tesseract reads over the
    whole page at its own size, to find the title and the clue lists; cached."""
    path = OCR_CACHE / f"{key}.page.{ocr_clues.reader_key('times')}.json"
    if path.exists():
        return [tuple(w) for w in json.loads(path.read_text())]
    words = ocr_clues.tesseract_words(img.convert("RGB"), ocr_clues.TESS_MODELS["times"])
    path.parent.mkdir(parents=True, exist_ok=True)
    write_whole(path, json.dumps(words))
    return words


def image_key(img):
    return hashlib.sha256(img.tobytes()).hexdigest()[:20]


def num(figure):
    """The number a FIGURE reads: "1,001", "1.403" and "1, 349" alike."""
    return int(re.sub(r"\D", "", figure))


#: A citation title's number dated further than this from its citation's
#: date is a misprint or a misread ("Crossword No. 57" on 13 Feb. 1941, No
#: 570's day): the date's puzzle is taken.
TITLE_DRIFT = datetime.timedelta(days=21)


def cited(cite):
    """(number, how, reports) a Gale PDF's citation gives: the puzzle its
    article title numbers (None, None when it numbers none; cited_day reads
    the date), and the past puzzles whose report it is."""
    cite = re.sub(r"\s+", " ", cite or "")
    title = (m.group(1) if (m := ARTICLE.search(cite)) else "").strip()
    reports = {num(n) for n in REPORT.findall(title)}
    if not reports and (m := NUMBERED.search(title)):
        return num(m.group(1) or m.group(2)), "PDF citation title", reports
    return None, None, reports


def cited_day(cite):
    m = CITED.search(re.sub(r"\s+", " ", cite or ""))
    return m and datetime.date(int(m.group(3)), gi.MONTHS[m.group(2)[:3].lower()], int(m.group(1)))


def times_cited(cite):
    """(number or None, date) a Times page's citation gives (TIMES_CITED),
    or None when it is no Times citation."""
    m = TIMES_CITED.search(re.sub(r"\s+", " ", cite or ""))
    if not m:
        return None
    n = TIMES_NUMBER.search(m.group(1))
    return n and num(n.group(1)), datetime.date(int(m.group(4)), gi.MONTHS[m.group(3)[:3].lower()], int(m.group(2)))


def is_times(path):
    """Whether the saved page `path` is one of the Saturday Times' (in SAVED/TIMES)."""
    return Path(path).parent.name == TIMES.name and Path(path).parent.parent.name == TIMES.parent.name


def match(path, idx, read_title=True):
    """{"number", "date", "how", "reports", "docId", "pages": [(image, key)]}
    for a saved file: "number" the puzzle whose clues it prints, None (and
    "why") when nothing names one; "reports" the past puzzles whose solution
    grid it prints ("Report on Crossword No. 16"), from the citation, and
    from the page's own words when `read_title`. A page may hold both."""
    name = path.name
    doc = gi.DOC_ID.search(name) or re.match(r"(GM\d{8,12})\b", name)
    out = {"file": name, "docId": doc.group(1).upper() if doc else None, "number": None}
    read = gi.images(path)
    out["pages"] = [(img, image_key(img)) for img, _ in read]
    cite = read[0][1] if read else ""
    by_number = {r["number"]: r for r in idx}
    number, how, reports = cited(cite)
    report_only = bool(reports) and number is None
    pointed = []
    # A Saturday Times page: its citation dates it (and mostly numbers it,
    # "Listener Crossword No. 3138: ..."), its name only the document's.
    if (got := times_cited(cite)) or is_times(path):
        out["times"] = True
    if got:
        n, day = got
        r = by_date(idx, day)
        if n is not None and (r is None or r["number"] == n
                              or n in by_number and abs(by_number[n]["date"] - day) <= TITLE_DRIFT):
            out.update(number=n, how="Times citation title")
        elif r:
            out.update(number=r["number"], how="Times citation date")
    day = None if out["number"] is not None else gi.name_date(name, DATES)
    if day:
        r = by_date(idx, day)
        out.update(number=r and r["number"], how="file name date")
    if out["number"] is None and (n := name_number(name)) is not None:
        out.update(number=n, how="file name number")
    if out["number"] is None and number is not None:
        out.update(number=number, how=how)
        day = cited_day(cite)
        r = day and by_date(idx, day)
        if r and r["number"] != number and (number not in by_number
                                            or abs(by_number[number]["date"] - day) > TITLE_DRIFT):
            out.update(number=r["number"], how="PDF citation date")
    if out["number"] is None and (day := cited_day(cite)):
        r = by_date(idx, day)
        out.update(number=r and r["number"], how="PDF citation date")
    if read_title:
        for img, key in out["pages"]:
            text = ocr_clues.lines_of(page_words(img, key))
            reports |= {num(n) for n in REPORT.findall(text)}
            here = puzzle_here(text, out["number"])
            report_only = report_only and not here
            pointed.append(not here and bool(ELSEWHERE.search(text)))
            if out["number"] is None and (m := title_of(text)):
                out.update(number=int(re.sub(r"\D", "", m.group(1))), how="title read")
        if (report_only or pointed and all(pointed)) and out["number"] is not None and out["pages"]:
            # Gale's article is the report, and the page prints no clue list:
            # the issue's own puzzle is on another page (5 of 7 such 1932
            # pages), so its read would only spend ~17 min to find nothing. So
            # too a page whatever its article that heads a report or points
            # to the week's puzzle on another page, and prints none (No 151's
            # "Beef and Beet in Norfolk", read as 1/39 from its report's notes).
            out.update(number=None, why=f"the report page only: No {out['number']}'s clues are on another page")
    out["reports"] = sorted(n for n in reports if n in by_number and n != out["number"])
    if out["number"] is not None and (out["number"] not in by_number or not printed(by_number[out["number"]])):
        out.update(why=f"No {out['number']} is not in the index of the magazine's puzzles", number=None)
    if out["number"] is None:
        out.setdefault("why", "no date or number in the name, citation or title")
    else:
        out["date"] = by_number[out["number"]]["date"]
    if not out["pages"]:
        out.update(number=None, reports=[], why="no page image in the file")
    return out


# ------------------------------------------------------------ reading a page

#: A gap this wide with no word in it, down the clue lists, parts two columns.
GUTTER = 25
#: A heading centred over its column stands at most this far right of
#: the column's clue numbers.
CENTRED = 500
#: RapidOCR reads at most this tall a band (after ocr_clues.UPSCALE) unshrunk.
BAND = 900


#: A clue's words start within this many of its number's heights right of
#: it (Gale's 1932 scans set them 43 px, under two heights, apart).
BESIDE = 2.5


def words_only(words):
    """The words a column's extent is measured by: a lone number with no
    words beside it (a grid's cell number) is not one."""
    out = []
    for w in words:
        if re.fullmatch(r"\W*\d{1,3}\W*", w[4]) and not any(
                o is not w and not re.fullmatch(r"\W*\d{1,3}\W*", o[4])
                and w[0] < o[0] and o[0] - w[2] <= max(40, BESIDE * (w[3] - w[1]))
                and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < (w[3] - w[1]) for o in words):
            continue
        out.append(w)
    return out


#: A clue's number, or what goes with it in the number column: "16 & 17*.",
#: "21.**", "27. x*", "41 & 38 rev.", "I3." (a 1 read I).
NUMBERISH = re.compile(r"[\W\dIl]*\d[\W\dIl]*(?:rev\b\W*)?[x*\W]*|[\dIl]{1,2}\W+|&|rev\W*|[x*.]+", re.IGNORECASE)
#: Lines whose texts start at one x, this many at least, make a hanging list.
HANGING = 4


def hanging_numbers(words):
    """`words` with the numbers of a list set as a table (No 141, 1932: each
    number right-set in its own column ~125 px left of the clue texts, which
    all start at one x) moved up beside their clue's first word, as the other
    lists print them; words_only and the column finders take a number further
    than BESIDE heights from its words for a grid's. A lone "I" there is 1.
    Unchanged when no HANGING lines share a text edge so far right of their
    numbers."""
    lines = []
    for w in words:
        if not (NUMBERISH.fullmatch(w[4]) and re.search(r"\d", w[4]) or w[4] in ("I", "l")):
            continue
        h, mid = w[3] - w[1], (w[1] + w[3]) / 2
        row = sorted((o for o in words if o[0] >= w[2] - 5
                      and abs((o[1] + o[3]) / 2 - mid) < min(h, o[3] - o[1]) / 2), key=lambda o: o[0])
        group = [w]
        for o in row:
            gap = o[0] - group[-1][2]
            if NUMBERISH.fullmatch(o[4]) and -5 <= gap <= max(40, BESIDE * h):
                group.append(o)
                continue
            if 0 <= gap < 12 * h:
                lines.append((o[0], gap > max(40, BESIDE * h), group))
            break
    far = sorted(x for x, wide, _ in lines if wide)
    edges = [x for x in far if sum(abs(e - x) <= 15 for e in far) >= HANGING]
    out = {id(w): w for w in words}
    for x, _, group in lines:
        if not any(abs(e - x) <= 15 for e in edges) or any(out[id(g)] is not g for g in group):
            continue
        tx = min(e for e in edges if abs(e - x) <= 15)
        shift = tx - 12 - group[-1][2]
        for g in group:
            out[id(g)] = (g[0] + shift, g[1], g[2] + shift, g[3], "1." if g[4] in ("I", "l") else g[4])
    return [out[id(w)] for w in words]


def page_columns(words):
    """[across lines, down lines], each [(y0, y1, x0, x1, text)], for a page
    laid out any way: of headed_columns (both headings read) and
    numbered_columns, the one holding more numbered clue lines, headed_columns
    on a tie. Under a low ACROSS, headed_columns sees only the lists' first
    band (No 3's run on at the top of the next column). One whose lists
    both hold COLUMN_MIN numbered lines goes first: on a paragraph page the
    headings' lines open on a number by chance (No 245, 1934: headed 1
    across and 41 down, its paragraphs 22 and 20)."""
    found = [c for c in (headed_columns(words), numbered_columns(words), paragraph_columns(words),
                         paragraph_columns(words, DOTTED)) if c]

    def numbered(lst):
        return sum(bool(al.LINE_CLUE.match(line[4])) for line in lst)
    best = max(found, key=lambda c: (min(map(numbered, c)) >= COLUMN_MIN, sum(map(numbered, c))), default=None)
    return [rules_cut(lst) for lst in best] if best else best


#: The competition's rules set under the 1930s lists ("(1) Solutions should
#: be addressed to the Editor of The Listener, Broadcasting House ... (7) In
#: all matters connected with the crosswords the Editor's decision is
#: final."): a list's last clue read on into them took them for its words
#: (No 447's 36D, No 503's 32D "See 37 A. disqualify entries for bad
#: handwriting ...").
RULES = re.compile(r"addressed\s+to\s+the\s+Editor|Broadcasting\s+House|disqualify\s+entries|capricious\s+traps"
                   r"|Editor\W{0,3}s\s+decision\s+is|Editor\s+reserves\s+the\s+right|Collaborators\s+may\s+only",
                   re.IGNORECASE)
#: The rules number their items (1) to (7).
RULE_ITEMS = 7
SENTENCE_STOP = re.compile(r"[.?!][\"'’”)]*(?=\s|$)")


def rules_cut(lst):
    """A list's lines (`lst`) without the rules (RULES): the line they open
    in kept to its last sentence's stop before them, when that leaves
    words, and the lines after it left out up to one opening on a clue
    number above the list's last before them and the rules' own items
    (the list run on past the rules; "(5) Subject to" is a rule)."""
    for i, line in enumerate(lst):
        if m := RULES.search(line[4]):
            head = line[4][:m.start()]
            ends = list(SENTENCE_STOP.finditer(head))
            kept = head[:ends[-1].end()] if ends else ""
            last = max([RULE_ITEMS] + [int(n.group(1)) for ln in lst[:i] if (n := al.LINE_CLUE.match(ln[4]))])
            more = next((j for j in range(i + 1, len(lst)) if (n := al.LINE_CLUE.match(lst[j][4]))
                         and int(n.group(1)) > last and not RULES.search(lst[j][4])), len(lst))
            return lst[:i] + ([(*line[:4], kept)] if re.search(r"[A-Za-z]{2}", kept) else []) + rules_cut(lst[more:])
    return lst


#: A clue's number as the 1934-40 lists print it, run on in a paragraph:
#: "(14)*** Labour in vain ... (15) anag. A slave ...", the light's mark
#: after it ("(16B)", "(4U)") and its stars; a reading may lose the opening
#: bracket ("2)*** One who slays"). Lights clued together share one
#: bracket, the clue numbered by the first: "(1, 8, 52) The nightingale.",
#: "(40-22) Thracian torturers." (No 443, 1938); read from its last figure,
#: each was a number lower than the clue's before it, and dropped. An
#: anagram's clue says so in its bracket: "(47 anag.) Shivering", a
#: reversed light's too: "(45 rev.) Better be" (No 242, 1934). A reader
#: may set the clue's capital hard against it: "(26rev.)Muddled" (No 261).
#: A light set reversed inside another is numbered by the first: "(43 rev.
#: in 42) Alleged destroyers" (No 245, 1934). Its stars may come first,
#: inside the bracket: "(**10) Victim", "(*8) Mounted" (No 245).
#: So too one set inside another unreversed, "(12 in 3) Really a kind"
#: (No 242); a plural's, "(8-s) Proverbs", "(3-s)"; and an anagram's
#: opening on it, "(Anag. 28B) With 39A" (No 273, 1935).
PARA_MARK = re.compile(r"(?<![\w(])(?:\([*†‡]*(?:Anag\.\s?)?)?(\d{1,2})([A-Z]?)(?:(?:,\s?|-)\d{1,2}[A-Z]?)*(?:-s)?"
                       r"(?:\s?(?:anag|rev)\.?\s?)?(?:\s?in\s\d{1,2}\s?)?\)([*†‡!¥]*)(?![a-z\d_)])")
#: A clue's number in its bracket with a figure read as a letter: "(Is)"
#: for (15), "(3o)", "(z1)", "(i7)", "(1g rev.)", "(Io rev.)", "(s rev.)"
#: (No 261, 1935: 9 of its 29 numbers so read by one reader or another).
#: Read as figures where a figure is in it, "rev."/"anag." follows it, or
#: it is two letters opening on I or l ("(II)", "(Io)"): "(I)", "(so)" and
#: "(is)" are words. So too the first of lights clued together, a figure
#: following: "(II, 40) Leads 'proof'" (No 254, 1935).
MARK_LIKE = re.compile(r"(?<![\w(])\([*†‡]*([\dIlioOzZsSg]{1,2})(?=[A-Z]?\)|(\s?(?:anag|rev)\b)|(,\s?\d{1,2}[A-Z]?[,)]))")
#: A clue's number whose closing bracket a reading lost, its capital after
#: a space: "(1 Protects the arm", "(33 Dukedom of London" (No 245, 1934);
#: not a light a clue cites by its direction, "(43 Ac.)", "(32 Down)".
UNCLOSED = re.compile(r"(?<![\w(])\((\d{1,2})\s(?!(?:Down|Across|Ac|Dn|Up)\b)(?=[\"'‘“]?[A-Z][a-z])")
#: A later light of a bracket so read: "(2-4oA)" for (2-40A), "(9-IoD)" for
#: (9-10D) (No 273, 1935), which left the clue run on into the one before.
LATER_LIKE = re.compile(r"(?<=\(\d-|\d\d-)(\d[IlioOzZsSg]|[IlioOzZsSg]\d|[Il][IlioOzZsSg])(?=[A-Z]?[)\-,])")
#: A light a clue refers to, "See (31) Down.": no clue's number.
SEE = re.compile(r"\bsee\W*$", re.IGNORECASE)
#: ... or names its direction after it: "Certainly applicable to (33)Down."
#: (Named apart from CITED, the citation's date, which it once shadowed:
#: cited_day read no date from 10-23 to 10-24, so a fetched page cited as
#: "Report on No. 649", 3 Sept. 1942, was matched by its title misread "No.
#: 65" and its No 651 clues replaced No 65's reading.)
SEE_DIRECTION = re.compile(r"\s*(?:Down|Across)\b(?=\s*[.,;:)]|\s*$)")


def figures_read(text):
    """`text` with each MARK_LIKE number read as figures, its length kept
    (paragraph_columns places each clue by its offset), and a full-width
    bracket read as one ("（16)Without", ch on No 400)."""
    text = clue_text.wide_brackets_narrowed(text)

    def fix(m):
        tok = m.group(1)
        if tok.isdigit() or not (re.search(r"\d", tok) or m.group(2) or re.fullmatch(r"[Il][\dIlioOzZsSg]", tok)
                                 or m.group(3) and tok in ("I", "l")):
            return m.group(0)
        return m.group(0)[:m.start(1) - m.start()] + clue_text.figures_like(tok)
    text = LATER_LIKE.sub(lambda m: clue_text.figures_like(m.group(1)),MARK_LIKE.sub(fix, text))
    return UNCLOSED.sub(r"(\1)", text)


#: PARA_MARK opening a clue's words in capitals: what tells a page of
#: paragraph lists from one with counts at clues' ends ("Region (6)").
PARA_OPENS = re.compile(PARA_MARK.pattern + r"(?=[,\s]*\(|\s+[\"'‘“]?[A-Z0-9])")
#: PARA_MARK where a clue's words follow it, on such a page ("(15) anag.
#: A slave"): a count is followed by its clue's stop ("Song (5).").
PARA_SPLIT = re.compile(PARA_MARK.pattern + r"(?=[,\s]*[^\s.,;:)\]])")
#: The 1949-90 lists run on as paragraphs too, each clue opening "N." after
#: the last one's stop or count: "1. Not a sleeping-bag for the soldier (8).
#: 5. Bold widow ..." (No 1069, 1950), "house. 5. To side with" (No 2107,
#: 1970), a reading often running them on with no space, "(7).7.\u2018The".
#: DOTTED: (mark, opens, split) as PARA_MARK's three; its empty groups stand
#: for PARA_MARK's light mark and stars. Its opens follow a count's ")":
#: the 1930s lists print none, and their one-clue lines read across two
#: columns ("1. Clue. 25. Clue") are no paragraph.
DOT_MARK = re.compile(r"(?:^|(?<=[.)\uff09!?'\u2019\"\u201d\u00b7])|(?<=[.)\uff09!?'\u2019\"\u201d\u00b7]\s))(\d{1,2})()()\.")
DOTTED = (DOT_MARK, re.compile(r"(?<=[)\uff09])\.?\s?(\d{1,2})\.(?=\s*[\"'\u2018\u201c(]?[A-Z])"),
          re.compile(DOT_MARK.pattern + r"(?=\s*[^\s.,;:)\]])"))
PARA_MARKS = (PARA_MARK, PARA_OPENS, PARA_SPLIT)
#: A page's lists are paragraphs when at least this many numbers open clues mid-line.
PARA_MIN = 6
#: Numbers only commas part are one clue for those lights: "(51), (32B), (14)! Epsilon".
PARA_GROUP = re.compile(r"^[\s,]*(?:and\s+|&\s*)?$")
#: Two words in capitals: the next heading under the lists ("CROSSWORD RULES.").
PARA_STOP = re.compile(r"\b[A-Z]{3,}[\s.,:—-]+[A-Z]{3,}\b")
#: The last puzzle's report under the lists, its heading run on after the
#: last clue: "please. Report on Crossword No. 252", read "on Crossword" (No 254).
PARA_REPORT = re.compile(r"(?:\bReport\s+)?\bon\s+Crossword\b")
#: ... but for the entry form's "NAME AND ADDRESS" before DOWN's heading: that column's end.
FORM = re.compile(r"\bADDRESS\b")
#: A gap of more than this many of its column's line pitches ends the lists there.
PARA_GAP = 2.5
#: A box this many times a word's height is the grid's or a picture's, no clue's.
PARA_TALL = 2.5


def paragraph_columns(words, marks=PARA_MARKS):
    """[across lines, down lines] for lists printed as running paragraphs
    (1934-40): under the ACROSS heading ("CLUES—ACROSS", read "CLUESACROSS"
    too) and in the columns right of it holding clue numbers, the lines are
    read column by column, top to bottom, the lists running on from one
    column's foot to the next's top, as one text cut at each clue number
    (PARA_MARK) into a line "N. words" (the light's mark and stars after the
    number are not the clue's words). A number no higher than the clue's
    before it is the clue's words ("(5)"), but for a list's restart at 1 or
    2 (DOWN's heading unread). DOWN's heading switches lists; a gap, two
    words in capitals (the rules' heading) or a column with no clue number
    ends them. None unless PARA_MIN numbers open clues mid-line and both
    lists have clues. `marks`: PARA_MARKS, or DOTTED for the 1949-90 lists'
    "N." numbers."""
    mark, opens, split = marks
    heights = sorted(w[3] - w[1] for w in words if WORDY.search(w[4]))
    if not heights:
        return None
    height = heights[len(heights) // 2]
    if para_openers(words, height, opens) < PARA_MIN:
        return None
    # The heading read alone on its line, else a misread one in its
    # capitals ("CLUESAGROSS"), else any word saying across: a clue's "(11)
    # See 37 Across." above it (No 242, 1934) is no heading when one is
    # read, and the preamble's "36 and 45 Across form" just over an
    # unreadable one ("Orie cuss ackoss", No 208) stands for it.
    by_y = sorted(words, key=lambda w: w[1])
    across = (next((w for w in sorted(headings(words), key=lambda w: w[1]) if heading(w[4]) == "ACROSS"), None)
              or next((w for w in by_y if re.search(r"A[CG]R[O0]SS", w[4])), None)
              or next((w for w in by_y if heading(w[4]) == "ACROSS" or re.search(r"A[CG]R[O0]SS", w[4].upper())), None))
    if marks is DOTTED:
        # Their prose above may "come across" (No 1069): the heading itself.
        across = next((w for w in sorted(words, key=lambda w: w[1]) if heading(w[4]) == "ACROSS"), None)
    if across is None:
        return None
    tall = PARA_TALL * height
    blots = [w for w in words if w[3] - w[1] > tall]
    # The 1949-90 lists run on at the top of the next column, level with the
    # puzzle's title over the heading ("Crossword No. 1,069. Plain Sailing"):
    # right of the heading, from there.
    titles = [w[1] for w in words if marks is DOTTED and across[1] - 600 <= w[1] < across[1]
              and re.search(r"crossword\W+(?:n[o0]\W+)?\d", w[4], re.IGNORECASE)]
    top = min(titles, default=across[1]) - 10
    body = [w for w in words if w[3] - w[1] <= tall and (w[1] + w[3]) / 2 >= (top if w[0] > across[2] else across[1] - 10)
            and not any(b[0] <= (w[0] + w[2]) / 2 <= b[2] and b[1] <= (w[1] + w[3]) / 2 <= b[3] for b in blots)]
    spans = para_numbers(para_spans([w for w in body if re.search(r"[A-Za-z]{2}|\(\d", w[4])]), body)
    stream = []
    for x0, x1 in (s for s in spans if s[1] >= across[0]):
        rows = para_rows([w for w in body if x0 <= (w[0] + w[2]) / 2 <= x1], height)
        unread_down = stream and x0 > across[2] and not any(t == "DOWN" and r is None for t, r in stream)
        if unread_down and sum(len(opens.findall(r[4])) for r in rows) < COLUMN_MIN:
            # The heading at a column's foot, the across list run on at the
            # next column's top, above the heading's level, and only a
            # report below it there (No 242, 1934).
            rows = para_above(words, (x0, x1), across, height, tall, mark) or rows
        elif unread_down and any(heading(w[4]) == "DOWN" and x0 <= (w[0] + w[2]) / 2 <= x1 and w[3] < across[1]
                                 for w in headings(words)):
            # The across list run on at the next column's top, above the
            # heading's level, DOWN's heading there too, and the down list
            # running on below that level (No 245, 1934): the column whole.
            above = para_above(words, (x0, x1), across, height, tall, mark)
            rows = above + [r for r in rows if not above or r[0] > above[-1][0]]
        if stream and not any(mark.search(r[4]) for r in rows):
            break  # a column with no clue number: a report, an article
        steps = sorted(b[0] - a[0] for a, b in itertools.pairwise(rows) if b[0] > a[0])
        pitch = steps[len(steps) // 2] if steps else 0
        last, stop = None, False
        for r in rows:
            if not re.search(r"[A-Za-z]{2}|\(", r[4]):
                # A grid's cell numbers under the list ("1 2 3 4 5") or a speck
                # ("!"): no line of it, though it spans a gap as before.
                last = r[0] if last is None or r[0] - last <= PARA_GAP * pitch else last
                continue
            # A heading's own space above it is no gap (No 582's DOWN, 1941),
            # nor is an unread DOWN's: the down list starting again at 1 or 2
            # under it (No 443's "(1) No post-mortem", 1938).
            if (last is not None and pitch and r[0] - last > PARA_GAP * pitch and heading(r[4]) != "DOWN"
                    and not (r[0] - last <= PARA_HEAD_GAP * pitch and para_restart(r[4], mark, stream))):
                break
            last = r[0]
            head = heading(r[4]) or ("ACROSS" if r is rows[0] and re.search(r"A[CG]R[O0]SS", r[4].upper())
                                     and not mark.search(r[4]) else None)
            if head:
                stream.append((head, None))
                continue
            text = r[4]
            form = False
            if cut := min(filter(None, (PARA_STOP.search(text), PARA_REPORT.search(text))),
                          key=lambda c: c.start(), default=None):
                # The entry form's "NAME AND ADDRESS" under a column the across
                # list runs on from ends that column alone (No 245, 1934).
                form = bool(FORM.search(text, cut.start())) and not any(t == "DOWN" and w is None for t, w in stream)
                text, stop = text[:cut.start()], not form
            stream.append((text, r))
            if stop or form:
                break
        if stop:
            break
    lists = {"ACROSS": [], "DOWN": []}
    side, last, joined, boxes = "ACROSS", 0, "", []
    pieces = []  # (side, text, [(offset, row)])

    def flush():
        if joined.strip():
            pieces.append((side, joined, list(boxes)))

    for text, row in stream:
        if row is None:
            flush()
            side, joined, boxes = text, "", []
            if text == "DOWN":
                last = 0
            continue
        boxes.append((len(joined), row))
        joined += text.strip() + " "
    flush()
    # DOWN's heading read: a "(1)" or "(2)" before it is no restart (No 582's
    # "(1)" read for a count, 1941, cut its across list there).
    headed_down = any(text == "DOWN" and row is None for text, row in stream)
    for side, text, boxes in pieces:
        if mark is PARA_MARK:
            text = figures_read(text)
        marks = list(mark.finditer(text))
        last = 0
        clue = None  # [number, start of its words, row]
        for i, m in enumerate(marks):
            n = int(m.group(1))
            if n <= last and (later := [k for k in map(int, re.findall(r"\d+", m.group(0))) if k > last]):
                # A bracket of lights set at a later one's place ("(1, 40)"
                # after 10 across): numbered by it, no restart of the list.
                n = min(later)
            if (i + 1 < len(marks) and not text[m.end():marks[i + 1].start()].strip()
                    and int(marks[i + 1].group(1)) < n and n > last):
                continue  # a count, the next clue's number right after it: "Scotland (7) (5) Puts" (No 582)
            if clue and PARA_GROUP.match(text[marks[i - 1].end():m.start()]) and clue[1] == marks[i - 1].end():
                clue[1] = m.end()  # one more light of the same clue
                if not LETTERED.search(marks[i - 1].group(0) + m.group(0)):
                    clue[3] = clue[3] or int(m.group(1))
                continue
            if mark is PARA_MARK and (SEE.search(text, 0, m.start()) or SEE_DIRECTION.match(text, m.end())):
                continue  # "See (31) Down.", "applicable to (33)Down.": the light a clue refers to
            if mark is PARA_MARK and not m.group(0).startswith("(") and re.match(r"\w", text[m.end():m.end() + 1]):
                continue  # a bracket's tail hard on a word: "(8-27- 36)Reading" (No 400's 8 down)
            if not split.match(text, m.start()) or n <= last and not (
                    n <= 2 and side == "ACROSS" and not lists["DOWN"] and not headed_down):
                continue  # the clue's own words: a count ("Song (5)."), a lower number
            if n > last and para_outlier(text, marks[i + 1:], last, n, split):
                continue  # a number misread high: the clue's words, the next clue's lost
            if clue:
                lists[side].append(para_line(clue, text[clue[1]:m.start()]))
            if n <= last:
                side = "DOWN"  # its heading unread: the down list starts again at 1
            last = n
            row = next(r for off, r in reversed(boxes) if off <= m.start())
            clue = [n, m.end(), row, para_linked(m, side) if n == int(m.group(1)) else None]
        if clue:
            lists[side].append(para_line(clue, text[clue[1]:]))
    if min(len(lists["ACROSS"]), len(lists["DOWN"])) < COLUMN_MIN:
        return None
    return [lists["ACROSS"], lists["DOWN"]]


#: An unread DOWN heading leaves at most this many line pitches over the
#: down list's first line.
PARA_HEAD_GAP = 5


def para_above(words, span, across, height, tall, mark):
    """paragraph_columns' rows of the column `span` above the ACROSS
    heading's level: from the top of the paragraph holding its first clue
    number (the lines over it set at the paragraph's own pitch), so an
    advert or article above it, set off by a gap, is none of it."""
    x0, x1 = span
    rows = para_rows([w for w in words if w[3] - w[1] <= tall and x0 <= (w[0] + w[2]) / 2 <= x1
                      and (w[1] + w[3]) / 2 < across[1]], height)
    first = next((i for i, r in enumerate(rows) if mark.search(r[4])), None)
    if first is None:
        return []
    steps = sorted(b[0] - a[0] for a, b in itertools.pairwise(rows[first:]) if b[0] > a[0])
    pitch = steps[len(steps) // 2] if steps else height
    while first and rows[first][0] - rows[first - 1][0] <= PARA_GAP * pitch:
        first -= 1
    return rows[first:]


def para_restart(text, mark, stream):
    """Whether a paragraph line (`text`) after a gap starts the down list
    whose heading went unread: it opens on clue 1 or 2 (`mark`), the across
    list has clues above it, and no DOWN heading was read."""
    m = mark.match(text.lstrip())
    return bool(m and int(m.group(1)) <= 2 and any(row is not None for _, row in stream)
                and not any(t == "DOWN" and row is None for t, row in stream))


def para_outlier(text, after, last, n, split):
    """Whether clue number `n`, the list's last clue `last`, is misread
    high: the next two numbers opening clues' words in `text` (of `after`,
    the marks following it) both fall between, rising. "(1, 40) Leads"
    read for (11, 40) after (10) numbered it 40, and its list's (15) to
    (38) were all dropped as lower (No 254, 1935)."""
    seen = []
    for m in after:
        if split.match(text, m.start()) and not (SEE.search(text, 0, m.start()) or SEE_DIRECTION.match(text, m.end())):
            seen.append(int(m.group(1)))
            if len(seen) == 2:
                return last < seen[0] < seen[1] < n
    return False


#: paragraph_columns' gutters: PARA_BIN-wide stretches across the lists
#: that fewer than PARA_THIN of the median stretch's words cover (a few
#: words read across No 400's gutter bridge it for a span of words).
PARA_BIN, PARA_THIN = 10, 0.25


#: A clue number's own box as No 582's lists set it: "(11)", "(4U)*".
BOXED_NUMBER = re.compile(r"\(\d{1,2}[A-Z]?\)[*†‡!¥]*")


def para_numbers(spans, words):
    """`spans` with a column holding only clue numbers' own boxes joined to
    the column right of it: No 582's (1941) "(N)"s are set out in a gutter
    of their own left of the clue texts and the ACROSS heading, so read
    apart from it they were lost and its clues read with no numbers."""
    out = []
    for s in spans:
        inside = [w for w in words if s[0] <= (w[0] + w[2]) / 2 <= s[1]]
        if out and out[-1][2]:
            out[-1] = [out[-1][0], s[1], False]
            continue
        out.append([s[0], s[1], len(inside) >= PARA_MIN and all(BOXED_NUMBER.fullmatch(w[4]) for w in inside)])
    return [[x0, x1] for x0, x1, _ in out]


def para_spans(words):
    """[[x0, x1]] the columns of `words`, parted at the gutters."""
    if not words:
        return []
    cover = [0] * (int(max(w[2] for w in words)) // PARA_BIN + 1)
    for w in words:
        for b in range(int(w[0]) // PARA_BIN, int(w[2]) // PARA_BIN + 1):
            cover[b] += 1
    full = sorted(c for c in cover if c)
    thin = PARA_THIN * full[len(full) // 2]
    spans = []
    for b, c in enumerate(cover):
        if c > thin:
            if spans and spans[-1][1] == (b - 1) * PARA_BIN:
                spans[-1][1] = b * PARA_BIN
            else:
                spans.append([b * PARA_BIN, b * PARA_BIN])
    return [[x0, x1 + PARA_BIN] for x0, x1 in spans]


def para_openers(words, height, opens=PARA_OPENS):
    """How many clue numbers open words (`opens`) in the lines of `words`
    ("wretched ones. (17) An"; No 582's "(1) Qualified for")."""
    return sum(len(opens.findall(r[4][1:])) for r in para_rows(words, height))


def para_rows(words, height):
    """[(y0, y1, x0, x1, text)] the printed lines of `words` (each
    (x0, y0, x1, y1, text)): a word is on the line whose centre is under
    half a word's `height` from its own. fa.merge_rows joins boxes that
    touch, and a paragraph's lines, set close, touch."""
    rows = []
    for w in sorted(words, key=lambda w: (w[1] + w[3]) / 2):
        mid = (w[1] + w[3]) / 2
        if rows and mid - rows[-1][0] < height / 2:
            rows[-1][1].append(w)
        else:
            rows.append([mid, [w]])
    return [(min(w[1] for w in ws), max(w[3] for w in ws), min(w[0] for w in ws), max(w[2] for w in ws),
             " ".join(w[4] for w in sorted(ws, key=lambda w: w[0]))) for _, ws in rows]


def para_line(clue, words):
    """paragraph_columns' line for one clue: its first row's box, "N. words",
    or "N, M. words" for a clue of two lights (al.LINKED_PLAIN)."""
    n, _, row, linked = clue
    head = f"{n}, {linked}" if linked else f"{n}"
    return (row[0], row[1], row[2], row[3], f"{head}. {' '.join(words.lstrip(' ,').split())}")


#: The second light of a clue PARA_MARK brackets with its first: "(10, 39)",
#: "(38-45)" (the answer running on); one bracketed apart, "(4) & (28)",
#: paragraph_columns links itself.
PARA_LINK = re.compile(r"^\(?[*†‡]*\d{1,2}([A-Z]?)(?:,\s?|-)(\d{1,2})([A-Z]?)(?!\d)")
#: A light's mark naming its direction or kind ("(37A, 26D)", "(7U and
#: 38U)", No 273): its lights' directions are the print's, not the list's.
LETTERED = re.compile(r"\d[A-Z]")
#: The letters naming a list's own direction: across, or back (reversed);
#: down, or up.
OWN_LETTERS = {"ACROSS": "AB", "DOWN": "DU"}


def para_linked(m, side=None):
    """The second light (an int) of the clue PARA_MARK `m` brackets, or None:
    "(10, 39) The name must fit" clues 39 too (No 254, 1935), filled "See
    10" by al.vote. A third light is left as read. In a LETTERED bracket,
    only lights in the list's own direction (`side`, OWN_LETTERS) link:
    "(29-35U)" and "(25-31, 27A-39)" in the down list clue 35 and 31 down
    too. Its second light lettered the other list's way, "(12-29D)" among
    the across clues (No 471, 1939), links too: the list's own number,
    which the filer (file_gale_listener.linked_across) points at the grid's
    other-direction light, its own direction having none or a clue of its
    own. Only an unlettered first light and the other list's letter
    (ACROSS_DOWN) link so: "(27A-39)" in a down list stays as read."""
    got = PARA_LINK.match(m.group(0))
    if not got:
        return None
    if not LETTERED.search(m.group(0)):
        return int(got.group(2))
    own = OWN_LETTERS.get(side, "")
    if own and all(not c or c in own for c in (got.group(1), got.group(3))):
        return int(got.group(2))
    other = ACROSS_DOWN.get(side)
    return int(got.group(2)) if other and not got.group(1) and got.group(3) == other else None


#: The letter naming the other list's light in a bracket set in each list:
#: "(12-29D)" among the across clues, "(5-9A)" among the down.
ACROSS_DOWN = {"ACROSS": "D", "DOWN": "A"}


#: The word a list's heading may open on, "CLUES—ACROSS" (No 197's),
#: read "CLUF" too: the heading's own, no clue's.
CLUES = re.compile(r"^\W*CLU[A-Z]{0,3}\W*")


def heading(text):
    """fa.heading_of the text, a CLUES word opening it dropped."""
    m = CLUES.match(text)
    return clue_text.heading_of(text[m.end():] if m and m.end() < len(text) else text)


def headings(words):
    """The words that are a list's heading alone on their line (ALONE), but
    for a CLUES word left of it: a report's prose quoting "for 1 Across
    (see notes)" heads no list."""
    return [w for w in words if heading(w[4]) and not any(
        o is not w and not (CLUES.fullmatch(o[4]) and o[2] <= w[0]) and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < (w[3] - w[1]) / 2
        and min(abs(o[0] - w[2]), abs(w[0] - o[2])) < ALONE for o in words)]


def list_heads(words):
    """(ACROSS, DOWN) heading words heading the lists, DOWN under ACROSS or
    in a column right of it; None without both."""
    heads = headings(words)
    # heading(), not al.heading_word: a "CLUES—ACROSS." heads No 141's lists (1932).
    across = next((w for w in sorted(heads, key=lambda w: w[1]) if heading(w[4]) == "ACROSS"), None)
    down = across and next((w for w in sorted(heads, key=lambda w: (w[0] // 200, w[1]))
                            if heading(w[4]) == "DOWN"
                            and (w[1] > across[3] or w[0] > across[2])), None)
    return (across, down) if across and down else None


def lend_heads(words):
    """{reader: words} with a reading that misreads a list heading ("DOW",
    "OWN", "ACIOSS") given the headings another reading reads alone,
    its own words there replaced: a heading is the page's layout, no
    clue's text. A word whose middle is off the heading's line by more than
    a quarter of its height is the next line's: a paragraph list's first
    line set hard under "CLUES-ACROSS" ("monarch's doom.", 1px under it on
    No 254, 1935) is no heading's."""
    lent = next((p for w in words.values() if (p := list_heads(w))), None)
    if not lent:
        return words
    out = {}
    for k, w in words.items():
        if list_heads(w):
            out[k] = w
            continue
        out[k] = [o for o in w if not any(h[0] - 10 <= (o[0] + o[2]) / 2 <= h[2] + 10
                                           and h[1] - (h[3] - h[1]) / 4 <= (o[1] + o[3]) / 2 <= h[3] + (h[3] - h[1]) / 4
                                           for h in lent)]
        out[k] += list(lent)
    return out


def headed_columns(words):
    """[across lines, down lines] cut at the gutters, read left to right
    from the column the ACROSS heading is in (its clue numbers' edge, which
    may be up to CENTRED left of it), each from the lists' top; the lines before
    DOWN are the across clues, those after it the down. None without both
    headings."""
    if not (pair := list_heads(words)):
        return None
    across, down = pair
    if down[2] < across[0] and down[1] > across[3]:
        # DOWN under the left column, ACROSS over the right (No 4's lists
        # either side of a map), each centred over its list's two columns:
        # each list is read from its own heading's column, under it.
        a, d = ([line for side in list_lines(words, h, h, 2 * CENTRED).values() for line in side] for h in pair)
        return [a, d] if a and d else None
    lines = list_lines(words, across, down, CENTRED)
    return [lines["ACROSS"], lines["DOWN"]] if lines["ACROSS"] and lines["DOWN"] else None


def list_lines(words, across, down, reach):
    """{"ACROSS": lines, "DOWN": lines} read from the column the ACROSS
    heading is in, its clue numbers up to reach left of it."""
    # A DOWN level with ACROSS may be read a little above it.
    top = min(across[1], down[1]) - 20
    below = [w for w in words if (w[1] + w[3]) / 2 >= top]
    # A heading may be centred over its column (No 103's), its clue numbers
    # far left of it: the column starts where they line up.
    left = max((x for x in column_lefts(below) if across[0] - reach <= x <= across[0]), default=across[0] - 40)
    body = [w for w in words_only(below) if w[0] >= left]
    spans = []
    # A speck ("|", "-") prints no word: one in the gutter bridges it.
    for x0, _, x1, _, _ in sorted(w for w in body if re.search(r"\w", w[4])):
        if spans and x0 <= spans[-1][1] + GUTTER:
            spans[-1][1] = max(spans[-1][1], x1)
        else:
            spans.append([x0, x1])
    # A gutter a long clue line or a speck bridges (No 88's lists beside the
    # report) still parts two columns where the next one's numbers line up.
    # A word across such a cut is a title over both (No 17's "Points from
    # Letters"), no clue's.
    cuts = [x - GUTTER for x in column_lefts(below) if x > left]
    if down[0] > across[2] and (x := down_left(below, across, down)) and not any(
            abs(c - x) < 2 * GUTTER for c in cuts + [a for a, _ in spans]):
        cuts = sorted(cuts + [x])
    body = [w for w in body if not any(w[0] < x < w[2] - GUTTER for x in cuts)]
    spans = [[max(x0, a), min(x1, b - 1)] for x0, x1 in spans
             for a, b in zip([x0] + cuts, cuts + [x1 + 1]) if max(x0, a) < min(x1, b - 1)]
    lines = {"ACROSS": [], "DOWN": []}
    side = "ACROSS"
    cuts = notice_cuts([fa.merge_rows([(w[1], w[3], w[0], w[2], w[4]) for w in body if x0 <= w[0] <= x1])
                        for x0, x1 in spans])
    for i, (x0, x1) in enumerate(spans):
        col = [(w[1], w[3], w[0], w[2], w[4]) for w in body if x0 <= w[0] <= x1]
        rows = fa.merge_rows(col)
        if i and not any(al.LINE_CLUE.match(r[4]) or heading(r[4]) for r in rows[:2]):
            # A column opening on prose (No 88's report beside its lists)
            # holds no more of them.
            break
        last = None
        notice = cuts[i]
        for line in rows:
            if last is not None and line[0] - last > 2 * fa.GAP or al.END.match(line[4]) or (
                    notice is not None and line[0] >= notice):
                break
            last = line[1]
            head = heading(line[4])
            if head:
                side = head
                continue
            lines[side].append(line)
        if al.END.match(lines[side][-1][4] if lines[side] else ""):
            break
    return lines


#: A report's heading, "Report on Crossword No. 13", "Report on the
#: Crossword of May 14": its prose quotes clue numbers ("solving 38 Down").
REPORT_HEAD = re.compile(r"^\W*report\s+on\b", re.IGNORECASE)
#: The setter's note under a list ("NOTE.--Clue for 3 down is in italics.",
#: read "NorE.-" too): no clue's words.
NOTE_HEAD = re.compile(r"^\W*N[oO0][tTrR][eE]\s*[.:\u2014\u2013-]")
#: Capitals with no small letter, two words or more ("B.B.C. SYMPHONY
#: CONCERT"): an advert's or article's heading below a list.
CAPITALS = re.compile(r"^[^a-z]*[A-Z]{3,}[^a-z]*[A-Z]{3,}[^a-z]*$")
#: The words of a competition, prize or solution notice set under the
#: lists ("Mr. A. R. Morton, c/o Mrs. ..., 68 Essex Road, ... prize of
#: Half-a-Guinea"): notice_top() takes them only in a paragraph set off
#: from the lists, with no clue number in it.
NOTICE = re.compile(r"\b(?:prizes?|guineas?|c/o|competitions?|solvers?|awarded|envelopes?|post-?cards?|"
                    r"solutions?\s+(?:will|must|should|may|to|of|received|sent))\b", re.IGNORECASE)
#: A notice's paragraph is set off from the lists above it by a gap of
#: more than this many of the column's line pitches.
NOTICE_GAP = 1.6
#: A clue number as the 1930s lists print it, "12.": where they line up
#: is a clue column (a bare "12" may be a grid's or a sentence's). A
#: bracket opens a count run on to its own line ("(12, 3 words)"), never one.
OPENS = re.compile(r"^[^\w(]{0,2}\d{1,2}[.,:](?![\d.])")
#: Words this many line heights apart are no one clue line's.
LINE_GAP = 5
#: A clue number alone in its box, and how wide each of its characters
#: prints at most, in the box's height (old-style figures run ~0.6).
BARE_NUMBER = re.compile(r"\W{0,2}\d{1,2}[.,:]")
NUMBER_WIDTH = 0.75
#: Clue numbers this far apart (in x) open different columns; a column is
#: one where at least COLUMN_MIN clues open, and a list has at least as many.
COLUMN_STEP, COLUMN_MIN = 40, 3
#: A clue line's words: a grid's row of cell numbers has none.
WORDY = re.compile(r"[A-Za-z]{3}")
#: A clue's run-on line is indented past its number at least this far;
#: prose beside the lists is not.
RUN_ON = 20
#: A list starting again in a column leaves at least this much space above
#: it (its heading's, read or not); a "2." closer under a clue is a
#: misread "32.".
RESTART = 20
#: A clue runs on to the next line only from a line set at least this
#: much of its column's width: a short one ended its clue ("6. Lenten."),
#: and the line under it is the next clue, its number lost ("park").
FULL = 0.6
#: A line this many times as tall as the clue line over it is set in
#: bigger type: the next article's title ("Points from Letters" under No
#: 15's 22 across), never the clue running on.
TALLER = 1.8
#: A word starting this much of its column's width past where the clue
#: lines end is no clue's: the grid's or the entry form's beside it.
BEYOND = 0.2
#: A report's sentence opening on the light it is about, its number with
#: no stop: "30 Down, the word TANLING meaning ..." (No 172's report beside
#: No 174's lists, 1933). No clue line: chained on as DOWN 30, it left the
#: list's real run-on (26-35 at the next column's top) following none.
CITING = re.compile(r"^\W{0,2}\d{1,2}\s+(?:across|down)\s*,", re.IGNORECASE)
#: A list's footnote, under its last clue: "*One letter missing."
FOOTNOTE = re.compile(r"^\W{0,2}[*\u2020\u2021#]\s*[A-Z]")
#: A line ending its sentence: "Lenten.", "Why did this aspirated this?".
SENTENCE_END = re.compile(r"[.?!][\u2019'\")]?\s*$")
#: A clue's number stands within this of its column's left edge.
NUMBER_EDGE = 60
#: A line's text opening on a word, no figure a misread number could be.
WORD_FIRST = re.compile(r"[A-Za-z][a-z]{2}")
#: A speck read where a clue's number is lost: "+ Why did this".
SPECK = re.compile(r"^[^\w\s*\u2020\u2021'\"\u2018\u201c(]{1,2}\s+(?=[A-Z])")
#: A heading stands alone on its line: no word this near either side
#: ("8 Down should have had an asterisk" is prose). A word is on its line
#: when their centres are under half its height apart: No 97's centred
#: ACROSS overlaps the first clue's line below it by a few pixels.
ALONE = 100


def down_left(words, across, down):
    """Where the DOWN list's column starts when DOWN heads a column right of
    ACROSS: just left of the clue numbers lined up nearest under it (a
    centred heading stands up to CENTRED right of them) and of DOWN itself
    (a number read into its clue's first word starts left of the bare
    ones), else None. A
    narrow gutter a reader's words bridge still parts the lists there."""
    xs = sorted(w[0] for w in words_only(words) if w[1] > down[1] and BARE_NUMBER.fullmatch(w[4] + ".")
                and max(across[2], down[0] - CENTRED) < w[0] <= down[0] + COLUMN_STEP)
    runs = []
    for x in xs:
        if runs and x - runs[-1][-1] <= COLUMN_STEP // 4:
            runs[-1].append(x)
        else:
            runs.append([x])
    runs = [r for r in runs if len(r) >= COLUMN_MIN]
    return min(runs[-1][0], down[0]) - 5 if runs else None


def column_lefts(words):
    """The left edges of the page's clue columns: where clue numbers line up."""
    xs = sorted(w[0] for w in words_only(words) if OPENS.match(w[4]))
    runs = []
    for x in xs:
        if runs and x - runs[-1][-1] <= COLUMN_STEP:
            runs[-1].append(x)
        else:
            runs.append([x])
    return [min(r) - 15 for r in runs if len(r) >= COLUMN_MIN]


def numbered_columns(words):
    """[across lines, down lines] for the 1930s layout, where a list's
    small-capital heading often goes unread and a list runs in bands across
    two columns. Below the first heading read (a word alone on its line),
    and from the top in the columns right of it, each clue column (where
    clue numbers line up) is cut top to bottom into runs: a line opening on
    a number and words is a clue, an indented line just under a line set
    wide (FULL) runs on, a footnote (FOOTNOTE) does not,
    and a heading, a line that is neither, a gap, or a clue numbered below
    the one before it, a heading's space under it, ends the run (No 15's
    DOWN 22 under ACROSS 39; a bracketed pair, "4.} 29.}", does not). A
    report's heading ends the column's lists. The
    runs, in column order, are chained into two lists by their first
    numbers: a run starting at 1 or 2 opens the second list, and any other
    run goes on whichever list's last clue it follows closest (No 97's
    DOWN 9 follows DOWN 3, not ACROSS 46), so a band's
    right half finds its list and prose beside the lists (a report) fits
    none. The first list is the one its
    heading names. None without two lists."""
    lefts = column_lefts(words)
    heads = headings(words)
    if not lefts or not heads:
        return None
    start = min(heads, key=lambda w: (sum(x <= w[0] for x in lefts), w[1]))
    if heading(start[4]) == "DOWN" and not any(heading(w[4]) == "ACROSS" for w in heads):
        start = across_start(words, start, lefts) or start
    runs = []
    # A grid's cell numbers beside a column (No 17's) would run into its
    # lines: a bare number past where the clue numbers stand, with no words
    # beside it, goes.
    kept = set(words_only(words))
    cuts = notice_cuts([fa.merge_rows([(w[1], w[3], w[0], w[2], w[4]) for w in words if x0 <= w[0] < x1])
                        for x0, x1 in zip(lefts, lefts[1:] + [float("inf")])])
    for x0, x1, notice in zip(lefts, lefts[1:] + [float("inf")], cuts):
        col = [(w[1], w[3], w[0], w[2], w[4]) for w in words if x0 <= w[0] < x1 and (
            w in kept or w[0] - x0 < NUMBER_EDGE or not re.fullmatch(r"\d{1,2}", w[4]))]
        run, last_y, last_x, clued = [], None, x0, False
        rows = fa.merge_rows(col)
        # The column's right edge: where its clue lines end, but for one
        # run into the grid or form beside it (No 17's "less'. NAME....").
        ends = sorted(line[3] for line in rows if OPENS.match(line[4]))
        right = ends[int(0.9 * (len(ends) - 1))] if ends else x0
        if ends and any(w[2] > right + BEYOND * (right - x0) for w in col):
            # Words starting well past that edge are the grid's or the
            # form's beside the column ("NAME...."): a box of theirs as
            # tall as two lines joined No 17's "less'." to 34 down's line.
            col = [w for w in col if w[2] <= right + BEYOND * (right - x0)]
            rows = fa.merge_rows(col)
        for line in rows:
            if REPORT_HEAD.match(line[4]) or notice is not None and line[0] >= notice:
                # A report's prose ("solving 38 Down") is no clue list.
                break
            if x0 <= start[2] and line[1] <= start[3]:
                # Above the first heading, in its columns or those left of
                # it: the grid, the preamble, another article.
                continue
            if clued and (NOTE_HEAD.match(line[4]) or CAPITALS.match(line[4]) and not al.LINE_CLUE.match(line[4])
                          ) and not heading(line[4]):
                # Under the lists, the setter's note or an advert's heading
                # (No 97's, under 42 down and 46 across): the column's
                # lists are over. Above them (No 9's radio programmes over
                # DOWN), they are only lines that are no clue.
                break
            m = al.LINE_CLUE.match(line[4])
            if run and (speck := SPECK.match(line[4])) and WORDY.search(line[4]):
                # A speck where the number was ("+ Why did ..."): the words
                # start at the indent.
                line = (line[0], line[1], last_x + RUN_ON + 1, line[3], line[4][speck.end():])
            # A line opening on a word where the numbers stand, under a full
            # line, is a box stretched over a speck: No 3's "Indian servant
            # looks forward to." under 45A, set at the indent.
            under = (run and last_y is not None and line[0] - last_y < fa.GAP / 2
                     and (line[2] > last_x + RUN_ON or WORD_FIRST.match(line[4])
                          and run[-1][1][-1][3] - x0 >= FULL * (right - x0))
                     and not heading(line[4]) and not FOOTNOTE.match(line[4])
                     and line[1] - line[0] <= TALLER * (run[-1][1][-1][1] - run[-1][1][-1][0]))
            if (m and line[2] - x0 < NUMBER_EDGE and WORDY.search(m.group(2)) and not heading(line[4])
                    and not CITING.match(line[4])):
                n = int(m.group(1))
                if run and run[-1][0] and line[0] - last_y <= RESTART and lost_zero(run[-1][0], n):
                    n *= 10
                    line = (*line[:4], f"{line[4][:m.start(1)]}{n}{line[4][m.end(1):]}")
                run = numbered(run, n)
                if run and (line[0] - last_y > fa.GAP / 2 or n < run[-1][0] and line[0] - last_y > RESTART):
                    runs.append(run)
                    run = []
                run.append((n, [line]))
                last_x, last_y, clued = line[2], line[1], True
            elif under and run[-1][1][-1][3] - x0 >= FULL * (right - x0):
                run[-1][1].append(line)
                last_y = line[1]
            elif under and WORDY.search(line[4]):
                # Under a line that ended its clue: the next clue, its
                # number lost (numbered() puts it back or drops it).
                run.append((None, [line]))
                last_y = line[1]
            else:
                if run := numbered(run, None):
                    runs.append(run)
                run, last_y = [], None
        if run := numbered(run, None):
            runs.append(run)
    lists = [[], []]
    for run in runs:
        first = run[0][0]
        if not lists[0]:
            side = 0
        elif not lists[1] and first <= 2:
            side = 1
        else:
            fits = [(first - ls[-1][0], i) for i, ls in enumerate(lists) if ls and first > ls[-1][0]]
            if not fits:
                continue
            side = min(fits)[1]
        lists[side] += run
    if min(map(len, lists)) < COLUMN_MIN:
        return None
    lines = [[line for _, ls in lst for line in ls] for lst in lists]
    return lines if heading(start[4]) == "ACROSS" else lines[::-1]


def across_start(words, down, lefts):
    """An ACROSS heading for numbered_columns to start at when only DOWN's
    was read (No 133's "CLUES—ACROSS" read "¢t 3 ¢«", 1932): just over the
    across list's "1." line, the nearest above DOWN in DOWN's column with
    words beside it; None without one."""
    x0 = max((x for x in lefts if x <= down[0]), default=None)
    if x0 is None:
        return None
    x1 = min((x for x in lefts if x > x0), default=float("inf"))
    ones = [w for w in words if x0 <= w[0] < min(x1, x0 + NUMBER_EDGE) and w[3] < down[1]
            and (m := OPENS.match(w[4])) and int(re.sub(r"\D", "", m.group(0))) == 1
            and any(WORDY.search(o[4]) and 0 <= o[0] - w[2] <= max(40, BESIDE * (w[3] - w[1]))
                    and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < (w[3] - w[1]) / 2 for o in words)]
    if not ones:
        return None
    one = max(ones, key=lambda w: w[1])
    return (one[0], one[1] - 5, one[2], one[1] - 1, "ACROSS")


def notice_top(rows):
    """The top (y) of the first notice in a column's lines (`rows`,
    fa.merge_rows' (y0, y1, x0, x1, text)), or None: a line with NOTICE's
    words, with the lines just above it at the column's own pitch, the
    paragraph starting after a gap of over NOTICE_GAP pitches under a
    list (at least COLUMN_MIN clue lines: the preamble's "No prizes will be
    offered" is above the lists, as is No 8's "Solutions should be
    addressed" under a letter's "23, about scientific experiments") and
    holding no clue number ("68 Essex Road," has no stop; "12. A prize" is
    a clue)."""
    if len(rows) < 3:
        return None
    steps = sorted(b[0] - a[0] for a, b in itertools.pairwise(rows) if b[0] > a[0])
    if not steps:
        return None
    pitch = steps[len(steps) // 2]
    for i, line in enumerate(rows):
        if not NOTICE.search(line[4]):
            continue
        top = i
        while top and rows[top][0] - rows[top - 1][0] <= NOTICE_GAP * pitch:
            top -= 1
        if sum(bool(OPENS.match(r[4])) for r in rows[:top]) >= COLUMN_MIN and not any(OPENS.match(r[4]) for r in rows[top:i + 1]):
            return rows[top][0]
    return None


def notice_cuts(columns):
    """Where each column's lines (`columns`, fa.merge_rows' rows each) end
    for a notice under the lists, or None: its own notice_top(), else,
    its first line reaching below the highest notice's top, when no line
    from there down opens on a clue number and that line stands higher: a
    notice set across the page is one paragraph, whose words one reading
    lost in a column ("68 Essex I" under DOWN 35) or set apart there from
    the line with NOTICE's words ("68 Essex I" over "prize of ...")."""
    own = [notice_top(rows) for rows in columns]
    tops = [t for t in own if t is not None]
    out = []
    for rows, top in zip(columns, own):
        below = [r for r in rows if tops and r[1] > min(tops)]
        if below and not any(OPENS.match(r[4]) for r in below) and (top is None or below[0][0] < top):
            top = below[0][0]
        out.append(top)
    return out


def lost_zero(before, n):
    """Whether clue number `n`, read just under clue `before` in its run,
    is a number ending in an old-style 0 (a small o) that the reading
    dropped: No 3's "6o. A resin." read "6." under 58. One digit, below
    `before`, and ten times it at most ZERO_STEP past `before`: further
    on, a dropped first figure is as likely ("2." under 13 for 32)."""
    return n < 10 <= before < 10 * n <= before + ZERO_STEP


#: How far past the clue before it a clue whose old-style 0 was lost
#: may be numbered (lost_zero).
ZERO_STEP = 3


def numbered(run, n):
    """`run` ([(number or None, lines)]) with the clues whose number the
    reading lost before clue `n` numbered: when as many as the numbers
    between the clue before them and `n` (No 97's DOWN 4-8, under 3 and over
    9, read with no figures), they take those numbers in turn; else (or with
    `n` None, the run's end) they run on from a clue that ended mid-sentence
    (No 97's verse), and are dropped after one that ended its sentence
    ("6. Lenten." over "park")."""
    lost = 0
    while lost < len(run) and run[len(run) - 1 - lost][0] is None:
        lost += 1
    if not lost:
        return run
    kept, gone = run[:len(run) - lost], run[len(run) - lost:]
    if kept and n is not None and n - kept[-1][0] - 1 == lost:
        return kept + [(k, [(*ls[0][:4], f"{k}. {ls[0][4]}"), *ls[1:]])
                       for k, (_, ls) in zip(range(kept[-1][0] + 1, n), gone)]
    if kept and not SENTENCE_END.search(kept[-1][1][-1][4]):
        # Mid-sentence ("His poser guessed by means unfair,"): it runs on.
        return kept[:-1] + [(kept[-1][0], kept[-1][1] + [line for _, ls in gone for line in ls])]
    return kept


#: Two lights' numbers run into the clue's first word ("9,36.Inversely",
#: "16&17*.What", No 127 and No 141, 1932): parted like a single one.
GLUED_GROUP = re.compile(r"^(\d{1,2}(?:\s?[,&]\s?\d{1,2})+\W{0,3}\.)(?=[A-Z(\u2018'\"\u201c])")


def figures(words):
    """The words with a line's opening clue number read as letters put back
    in digits (a number cannot open on 0, so "O." and "Oo." stay words),
    parted from a first word run into it, and a footnote's dagger read as a
    letter put back (clue_text.mend_opening); a speck's box taller than a line goes, and a
    bare number's box too wide for it is cut to its right end."""
    out = []
    tall = 1.5 * sorted(w[3] - w[1] for w in words)[len(words) // 2] if words else 0
    for w in words:
        if re.fullmatch(r"\W{1,2}|\d{3,}\W{0,2}", w[4]) and w[3] - w[1] > tall:
            # A speck's box over several lines, or several lines' numbers
            # read as one (No 97's lost DOWN "4."-"8.", read "+" or "450";
            # no clue number has three figures): merge_rows would take it
            # for one row and drop the lines in it.
            continue
        if BARE_NUMBER.fullmatch(w[4]) and w[2] - w[0] > len(w[4]) * (w[3] - w[1]):
            # A clue number's box wider than its characters can print: specks
            # or the gutter read into it (No 17's "7." from x 784, where the
            # column's numbers start at ~864). The number ends where it does.
            w = (int(w[2] - NUMBER_WIDTH * len(w[4]) * (w[3] - w[1])), *w[1:])
        w = (*w[:4], GLUED_GROUP.sub(r"\1 ", clue_text.tidy_ocr_clues(w[4], scope="piece")))
        out.append(w)
    return out


def bands(box, located):
    """`box` cut into bands BAND tall at most, each cut between printed
    lines (the located words'), so no line is read in two."""
    x0, y0, x1, y1 = box
    out, start = [], y0
    while y1 - start > BAND:
        cut = start + BAND
        while cut > start + BAND // 2 and any(w[1] < cut < w[3] for w in located):
            cut -= 4
        out.append((x0, start, x1, cut))
        start = cut
    out.append((x0, start, x1, y1))
    return out


#: A page that prints a puzzle's clues or diagram elsewhere says where:
#: "(For clues see page 1057)", "Diagram and rules on page 885".
CLUES_ELSEWHERE = re.compile(r"\b(?:clues?|diagram|rules)\b[^.]{0,40}?\bpage\s+(\d{2,4})\b", re.IGNORECASE)


def elsewhere(words):
    """The magazine pages the page's words send its clues or diagram to."""
    return sorted({int(n) for n in CLUES_ELSEWHERE.findall(" ".join(ocr_clues.lines_of(words).split()))})


# ------------------------------------------------------------ a Times page's Listener

#: The Listener's title on a Saturday Times page, "The Listener Crossword
#: 3890" (the word after "Listener" on its line): the tallest such words, as
#: the coupon's "Listener Crossword No 3890," and "Winners of Listener
#: Crossword 3135" are smaller.
TITLE_WORD = re.compile(r"^\W*listener\W*$", re.IGNORECASE)
TITLE_NEXT = re.compile(r"^\W*crossword", re.IGNORECASE)
#: A gutter between a Times page's columns: an x run at least this many
#: line heights wide that no word crosses (they are ~2 wide; a list's
#: numbers hang 0.3-0.7 left of their clues' words)...
TIMES_GUTTER = 1.0
#: ...down the lists' first this many lines (their headings' level on), where
#: the page is in columns: the grid and preamble over them span two.
TIMES_BAND = 15
#: A column right of the DOWN list's is the Listener's while at least this
#: share of its lines open on a number (a list run on), and it has no heading
#: of its own (another puzzle's lists).
TIMES_NUMBERED = 0.35
#: The lists end at a gap this many line heights tall with no word in their
#: columns: under it, the page's note of last week's corrections, or
#: another article.
TIMES_END = 3
#: A column of the lists with this many lines opening like a clue between
#: the title and the headings' level runs a list from under the title (No
#: 3144's 41 Across and 15 Down, a line each over the headings' level). Only
#: an alternative cut, which the filer takes where the grid says so.
TIMES_ABOVE = 1
#: A clue line's opening number, as a Times page's OCR reads it.
LINE_NUMBER = re.compile(r"^\W{0,2}\d{1,2}\b")


def line_height(words):
    """The median height of the words with three letters running."""
    hs = sorted(w[3] - w[1] for w in words if WORDY.search(w[4]))
    return hs[len(hs) // 2] if hs else 40


def times_titles(words):
    """The boxes (x0, y0, x1, y1) of each "Listener Crossword" on a page's
    words, tallest first, each widened to the words running on either side
    of it on its line ("The Listener Crossword 3890")."""
    out = []
    for w in words:
        h = w[3] - w[1]
        if not TITLE_WORD.match(w[4]):
            continue
        mid = (w[1] + w[3]) / 2
        line = [o for o in words if abs((o[1] + o[3]) / 2 - mid) < h / 2 and o[3] - o[1] > h / 2]
        if not any(TITLE_NEXT.match(o[4]) and 0 <= o[0] - w[2] < 2 * h for o in line):
            continue
        x0, x1 = w[0], w[2]
        for o in sorted(line, key=lambda o: o[0]):
            if 0 <= o[0] - x1 < 2 * h:
                x1 = max(x1, o[2])
        for o in sorted(line, key=lambda o: -o[2]):
            if 0 <= x0 - o[2] < 2 * h:
                x0 = min(x0, o[0])
        out.append((x0, w[1], x1, w[3]))
    return sorted(out, key=lambda b: b[1] - b[3])


def times_title(words):
    """The tallest of times_titles, or None."""
    return next(iter(times_titles(words)), None)


#: ACROSS cut short as a Times page's OCR reads it, "ACR" (No 3167's), which
#: heading() does not take: a heading only alone on its line.
TIMES_ACR = re.compile(r"^\W*ACR\W*$")


def times_heading(text):
    """heading(text), or "ACROSS" for a TIMES_ACR word."""
    return heading(text) or ("ACROSS" if TIMES_ACR.match(text) else None)


def times_heads(words, lh):
    """The words heading a Times page's lists: ACROSS or DOWN in capitals
    ("ACROSS:", misread "CROS"), or in title case or cut short ("ACR") with
    no word beside it on its line within two line heights (a clue's "see 5
    Across" has)."""
    out = []
    for w in words:
        if not times_heading(w[4]):
            continue
        if (not heading(w[4]) or not re.sub(r"[^A-Za-z]", "", w[4]).isupper()) and any(
                o is not w and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < (w[3] - w[1]) / 2
                and min(abs(o[0] - w[2]), abs(w[0] - o[2])) < 2 * lh for o in words):
            continue
        out.append(w)
    return out


def gutters(words, y0, y1, width):
    """[(x0, x1)] the runs at least `width` wide, left to right, that no word
    between y0 and y1 crosses (a rule read as "|" aside), the page's left
    margin first and an open run past the last word last."""
    ws = [w for w in words if w[3] > y0 and w[1] < y1 and re.search(r"\w", w[4])]
    if not ws:
        return []
    right = int(max(w[2] for w in ws)) + 1
    cover = [0] * (right + 1)
    for w in ws:
        cover[max(0, int(w[0]))] += 1
        cover[int(w[2])] -= 1
    out, run, start = [], 0, 0
    for x in range(right + 1):
        run += cover[x]
        if run > 0:
            if x - start >= width:
                out.append((start, x))
            start = x + 1
    out.append((start, float("inf")))
    return out


def numbered_share(words, x0, x1, y0, y1):
    """The share of the lines between y0 and y1 of the words in x0..x1
    opening on a clue number (LINE_NUMBER)."""
    ws = sorted((w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1),
                key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines = []
    for w in ws:
        if lines and abs((w[1] + w[3]) / 2 - lines[-1][0]) < (w[3] - w[1]) / 2:
            lines[-1][1].append(w)
        else:
            lines.append([(w[1] + w[3]) / 2, [w]])
    return sum(1 for _, line in lines if LINE_NUMBER.match(min(line)[4])) / len(lines) if lines else 0


def times_box(words):
    """(x0, y0, x1, y1) of the Listener's clue lists on a Saturday Times
    page's words: under its title (times_titles, the tallest with a heading
    pair under it: a "Listener Crossword" box lower on the page may be set
    larger), the ACROSS heading nearest it (times_heads), and the DOWN
    heading nearest that under it or in a column right of it; from the gutter
    left of the ACROSS list to the gutter right of the DOWN list (and the
    columns on that its lists run on into), from the headings down to the
    first gap of TIMES_END lines. The page's other puzzles (the Times
    Two, a concise, a quiz, a bridge or chess column) are left out. None
    when no title or no heading pair is read."""
    got = times_cut(words)
    return got and got[0]


#: A line under the lists in one of their columns opening on one of these
#: words heads the page's other matter there and in the columns right of it,
#: from its line down: last week's "SOLUTIONS:" (its
#: notes numbered "7 ness; 10 Iowa;", which read as clues), "Solution to
#: Crossword 3101", "Winners of Listener Crossword 3135", "ANSWERS".
TIMES_STOP = re.compile(r"^\W*(?:SOLUTIONS?|Solutions?|WINNERS|Winners|ANSWERS)\b\W*$")
#: A line in the lists' columns opening on this heads the prizes, the
#: Listener's address and the entry coupon: blanked to the box's foot in its
#: column alone (the lists do not run on under them).
TIMES_PRIZE = re.compile(r"^\W*(?:PRIZES?|Prizes?)\W*$")


def times_cut(words):
    """(times_box's box, [masks]): each mask a box of the page to blank
    out of it, a column of the lists from a TIMES_STOP line down (or a
    TIMES_PRIZE line to the box's foot); None with no box."""
    return next(iter(times_cuts(words)), None)


def times_cuts(words):
    """[(box, [masks])], times_cut first, then the other cuts its lists
    may need, each read and kept as an alternative the filer may take where
    the first's lights are not the grid's (read_file): the box from the
    title down where a column has clues above the headings' level (No
    3121's and 3175's down lists start there; No 3120's grid and preamble
    over the lists read so lose the lists' headings), and times_cut
    unblanked where it blanks (a SOLUTIONS block's mask may take the clues
    run on beside it). [] with no box."""
    lh = line_height(words)
    every = times_heads(words, lh)
    for title in times_titles(words):
        heads = [w for w in every if w[1] > title[3]]
        if got := _times_box(words, title, heads, lh):
            out = [got]
            if (raised := _times_box(words, title, heads, lh, raised=True)) and raised[0] != got[0]:
                out.append(raised)
            if got[1]:
                out.append((got[0], []))
            return out
    return []


def _times_box(words, title, heads, lh, raised=False):
    """times_cut under the one title `title`, its lists headed by `heads`;
    `raised`, the box from the title down where a column of it has
    TIMES_ABOVE lines opening like a clue above the headings' level, else
    None."""
    def partner(across):
        # DOWN under ACROSS in its column, or in a column right of it at any
        # level (the 1991-92 pages set the across list under the grid and
        # preamble, the down list from the next column's top).
        return min((w for w in heads if heading(w[4]) == "DOWN" and w[0] >= across[0] - 2 * lh
                    and (w[1] > across[3] or w[0] > across[0] + 3 * lh)),
                   key=lambda w: abs(w[0] - across[0]) + abs(w[1] - across[1]), default=None)
    pair = next(((a, d) for a in sorted((w for w in heads if times_heading(w[4]) == "ACROSS"), key=lambda w: max(
        0, title[0] - w[2], w[0] - title[2]) + (w[1] - title[3]) / 4) if (d := partner(a))), None)
    if pair is None:
        return None
    across, down = pair
    top = min(across[1], down[1]) - 2 * lh
    # The columns are measured from the lower heading where DOWN heads a column of its own, else from
    # ACROSS: a DOWN under it in its column may stand near the page's foot, the words under it few.
    lower = max(across[1], down[1]) if down[0] > across[0] + 3 * lh else across[1]
    band = lower + TIMES_BAND * lh
    gs = gutters(words, lower, band, TIMES_GUTTER * lh)
    left = max((g[1] for g in gs if g[1] <= across[0] + lh), default=0)
    after = [g for g in gs if g[0] >= down[2]]
    if not after:
        return None
    right = after[0][0]
    for g, nxt in zip(after, after[1:]):
        col = (g[1], nxt[0])
        if any(col[0] <= (h[0] + h[2]) / 2 <= col[1] and top <= h[1] <= band for h in heads) or numbered_share(
                words, *col, top, band) < TIMES_NUMBERED:
            break
        right = nxt[0]
    # Last week's solutions, the winners and the prizes stand under the headings' level: above it, in
    # the preamble a raised box takes in, the same words are the puzzle's own (No 3144's "ANSWERS to
    # twenty-three normal clues", No 3120's "ENABLE SOLUTION:"), whose masks took the ACROSS heading.
    heads_top = top
    if raised:
        # A list set from under the title, above the headings' level (No 3121's down list, from its
        # 3 Down, beside the preamble): the box from the title down, else those clues are cut off.
        cols = [(a[1], b[0]) for a, b in zip(gs, gs[1:]) if b[0] > left and a[1] < right]
        if not any(sum(opens for _, opens in column_lines(words, max(cl, left), min(cr, right), title[3], top))
                   >= TIMES_ABOVE for cl, cr in cols):
            return None
        top = title[3]
    bottom = top
    for w in sorted((w for w in words if left <= (w[0] + w[2]) / 2 <= right and w[3] > top), key=lambda w: w[1]):
        if w[1] - bottom > TIMES_END * lh and bottom > max(across[3], down[3]):
            break
        bottom = max(bottom, w[3])
    box = (int(max(0, left - lh / 2)), int(max(0, top)), int(right + lh / 4), int(bottom + lh / 2))
    masks = []
    for w in words:
        prize = bool(TIMES_PRIZE.match(w[4]))
        if not ((prize or TIMES_STOP.match(w[4])) and left <= (w[0] + w[2]) / 2 <= right
                and heads_top + 2 * lh < w[1] < bottom):
            continue
        col_left = max((g[1] for g in gs if g[1] <= w[0] + 1), default=box[0])
        if any(o is not w and col_left <= o[0] < w[0] and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < (w[3] - w[1]) / 2
               and re.search(r"\w", o[4]) for o in words):
            continue  # not the line's first word in its column: a clue's
        if prize:
            # The prizes, the address and the entry coupon end their column: its "63 Green Lane"
            # opens like a clue (No 3120's page read it as 63 Down).
            col_right = min((g[0] for g in gs if g[0] >= w[2]), default=box[2])
            masks.append((int(col_left), int(w[1] - lh / 4), int(min(col_right, box[2])), box[3]))
            continue
        # In its column and each right of it, down to the first line there opening like a clue: last
        # week's grid and notes may spill into the next column (No 3104's page), or be a block set in
        # one column with the lists going on under it or beside it (No 3121's).
        # A mask beside the one before it takes the gutter between them too, and the last column's
        # runs to the box's edge: the old grid crosses them (No 3104's page read 28 of 39 so, 50 of 50 not).
        cols = [(a[1], b[0]) for a, b in zip(gs, gs[1:]) if b[0] > col_left and a[1] < box[2]]
        before = None
        for i, (cl, cr) in enumerate(cols or [(col_left, box[2])]):
            cl, cr = max(cl, col_left), (box[2] if i == len(cols) - 1 else min(cr, box[2]))
            end = next((y - lh / 4 for y, opens in column_lines(words, cl, cr, w[1] - lh / 4, box[3]) if opens),
                       box[3])
            if end > w[1]:
                masks.append((int(before if before is not None else cl), int(w[1] - lh / 4), int(cr), int(end)))
            before = cr if end > w[1] else None
    return box, masks


#: A line opening like a clue: its number, then a word in capitals ("16. Syrup's", "3 Was"),
#: as last week's notes ("7 ness;") and grid letters ("1 S O L") do not.
CLUE_OPENS = re.compile(r"^\W{0,2}\d{1,2}[.,]?$")
CLUE_WORD = re.compile(r"^\W{0,2}[A-Z][a-z']{2,}")
#: Last week's notes run on in pairs, a number and its answer ("26 Pele; 27 otto; 37 peeper,"; a rule
#: read as "I" before one, "10 Stook; I 11 Eighteen;"): a line with one after a semicolon, or a line
#: of a number and one word alone ("40 Gaur."), opens no clue, though "26 Pele" opens like one (No 3121's
#: and 3144's pages ended the SOLUTIONS block's mask there, its pairs read as 26, 35 and 40 Down, and
#: the next column's down list then fitted no list).
NOTES_PAIR = re.compile(r"[;:]\s*(?:[^\w\s]{1,2}\s+|[Il|]\s+)?\d{1,2}[A-Z]?\s+[A-Za-z][a-z']*[;:,.]"
                        r"|^\W{0,2}\d{1,2}[.,]?\s+[A-Za-z][a-z']*[.;:,]\W*$")


def column_lines(words, x0, x1, y0, y1):
    """[(top, opens like a clue)] of the lines of the words in x0..x1 between
    y0 and y1, top down."""
    ws = sorted((w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1),
                key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines = []
    for w in ws:
        if lines and abs((w[1] + w[3]) / 2 - lines[-1][0]) < (w[3] - w[1]) / 2:
            lines[-1][1].append(w)
        else:
            lines.append([(w[1] + w[3]) / 2, [w]])
    out = []
    for _, line in lines:
        line.sort()
        first = line[0][4]
        opens = bool(re.match(r"^\W{0,2}\d{1,2}[.,]?\s*[A-Z][a-z']{2,}", first)) or (
            bool(CLUE_OPENS.match(first)) and len(line) > 1 and bool(CLUE_WORD.match(line[1][4])))
        opens = opens and not NOTES_PAIR.search(" ".join(w[4] for w in line))
        out.append((min(o[1] for o in line), opens))
    return out


def times_blocks(img, key):
    """[(image, key)] of each of times_cuts over a Saturday Times page's
    page_words (times_block), times_cut's first; [] when none is found."""
    words = page_words(img, key)
    return [times_block(img, key, cut, words) for cut in times_cuts(words)]


def times_block(img, key, cut=None, words=None):
    """(image, key) of the Listener's clue lists cut from a Saturday Times
    page (`cut`, else times_cut over its page_words), its masks blanked
    white, its own page_words those of the page inside it and out of the
    masks (no second read); None when none is found."""
    from PIL import ImageDraw
    words = page_words(img, key) if words is None else words
    got = cut or times_cut(words)
    if got is None:
        return None
    box, masks = got
    box = (box[0], box[1], min(img.width, box[2]), min(img.height, box[3]))
    x0, y0, x1, y1 = box
    crop = img.crop(box)
    if masks:
        crop = crop.copy()
        draw = ImageDraw.Draw(crop)
        for m in masks:
            draw.rectangle((m[0] - x0, m[1] - y0, m[2] - x0, m[3] - y0), fill="white")
    ck = image_key(crop)
    path = OCR_CACHE / f"{ck}.page.{ocr_clues.reader_key('times')}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_whole(path, json.dumps([(a - x0, b - y0, c - x0, d - y0, t) for a, b, c, d, t in words
                                      if x0 <= a and c <= x1 and y0 <= b and d <= y1 and not any(
                                          m[0] <= (a + c) / 2 <= m[2] and m[1] <= (b + d) / 2 <= m[3] for m in masks)]))
    return crop, ck


def read_page(img, key, lengths=None):
    """(verdict, {light: (text, enumeration, None)} or None) for one page:
    the whole page read by every ocr_clues.READERS reader band by band, each
    reading's lists found by page_columns, and voted on (al.vote). The
    1930s lists run on above their heading in the next column, so no box
    under a heading holds them all. `lengths` ({light: cells}) is the
    page's grid, when the caller has read it (al.vote)."""
    verdict = {}
    located = figures(page_words(img, key))
    if pages := elsewhere(located):
        verdict["seePages"] = pages
    if not any(heading(w[4]) for w in located) and not column_lefts(located):
        verdict["refused"] = "no clue list on the page" + see_pages(pages)
        return verdict, None
    box = (0, 0, img.width, img.height)
    words = {"page": located}
    for which in ocr_clues.READERS:
        path = OCR_CACHE / f"{key}.{'-'.join(map(str, box))}.{ocr_clues.reader_key(which)}.json"
        if path.exists():
            words[which] = figures([tuple(w) for w in json.loads(path.read_text())])
            continue
        got = []
        for b in bands(box, located):
            got += [(x0 + b[0], y0 + b[1], x1 + b[0], y1 + b[1], t)
                    for x0, y0, x1, y1, t in ocr_clues.read_words(img.crop(b), which)]
        path.parent.mkdir(parents=True, exist_ok=True)
        write_whole(path, json.dumps(got))
        words[which] = figures(got)
    # A line any reading numbers is a line every RapidOCR reading reads; a
    # line one reads again alone may number one for the other, so twice.
    rapid = [w for w in ocr_clues.READERS if w not in ocr_clues.TESS_MODELS]
    # Not on the 1949-90 run-on lists (DOTTED): a line opened mid-way on a
    # number, read again from there, comes back over the band's own words
    # for it and the clues read twice ("It is 11. It IS not necessary", No 1069).
    dotted = any(paragraph_columns(words[w], DOTTED) for w in rapid)
    for which in [] if dotted else rapid * 2:
        words[which] = figures(reread_lines(img, key, which, [tuple(w) for w in words[which]],
                                            [located] + [words[o] for o in rapid if o != which]))
    words = lend_heads(words)
    words = {k: hanging_numbers(w) for k, w in words.items()}
    if blanks := page_blanks(img, located):
        verdict["blanks"] = len(blanks)
        words = {k: ocr_clues.with_blanks(w, blanks) for k, w in words.items()}
    verdict, laid = al.vote(words, verdict, cols=page_columns, lengths=lengths, figures=True)
    if laid and not all(t for t, _, _ in laid.values()):
        laid = greek_mended(img, key, words, verdict, laid)
    if laid and (theme := theme_lights(words)):
        verdict["theme"] = theme
    return verdict, laid


#: A theme line names at least this many lights...
THEME_MIN = 3
#: ...each read so by at least this many readings.
THEME_VOTES = 2


def theme_line(words):
    """(title, [light token]) of the page's theme line, or None: the line
    under a title word of capitals alone on its line (headings' ALONE) just
    above the ACROSS heading, over it, as No 447's (1938) "CANVAS / The 26s
    that 28U 7D 7A 5, 35 13, 1A, and a 9 37U 27 6." heads its lists: the
    lights it names are the theme's, which no list clues. A token read with
    a letter for a figure ("IA", "S,") is the figure (clue_text.figures_like)."""
    across = next((w for w in sorted(headings(words), key=lambda w: w[1]) if heading(w[4]) == "ACROSS"), None)
    if across is None:
        return None
    h = across[3] - across[1]
    mid = (across[0] + across[2]) / 2

    def alone(w):
        return not any(o is not w and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < h / 2
                       and min(abs(o[0] - w[2]), abs(w[0] - o[2])) < ALONE for o in words)
    title = next((w for w in sorted(words, key=lambda w: -w[1])
                  if re.fullmatch(r"[A-Z]{4,}", w[4]) and not heading(w[4]) and w[3] <= across[1]
                  and across[1] - w[1] < 4 * h and w[0] < mid < w[2] + (w[2] - w[0]) and alone(w)), None)
    if title is None:
        return None
    # The line between the title and the heading, its words chained from the
    # one nearest the heading's middle while they sit a few heights apart.
    line = sorted((w for w in words if title[3] <= (w[1] + w[3]) / 2 <= across[1]), key=lambda w: w[0])
    if not line:
        return None
    at = min(range(len(line)), key=lambda i: abs((line[i][0] + line[i][2]) / 2 - mid))
    lo = hi = at
    while lo > 0 and line[lo][0] - line[lo - 1][2] < 2 * h:
        lo -= 1
    while hi + 1 < len(line) and line[hi + 1][0] - line[hi][2] < 2 * h:
        hi += 1
    tokens = []
    for w in line[lo:hi + 1]:
        for tok in w[4].split():
            m = THEME_READ.fullmatch(tok.strip(",.;:"))
            # A figure read as a letter stands alone only where no word
            # would: "S," is 5, "I" the word.
            if m and (re.search(r"\d", m.group(1)) or m.group(2) or m.group(1) in ("S", "l")):
                n = clue_text.figures_like(m.group(1)).lstrip("0")
                if n:
                    tokens.append(n + m.group(2).strip("'’s"))
    return title[4], tokens


#: A light theme_line reads: its number (a figure perhaps read as its
#: lookalike letter), then A or B (across, or back), D or U (down, or
#: up), or nothing: "28U", "7A", "35", "IA"; or a plural, "The 26s".
THEME_READ = re.compile(r"([\dIlSO]{1,2})([ABDU]?|(?<=\d)['’]?s)")


def theme_lights(words):
    """{"title", "lights"} of the page's theme line (theme_line) as the
    readings (`words` {reader: words}) vote it: each light token at least
    THEME_VOTES of them read, in the order the most-read reading has them;
    None when fewer than THEME_MIN do. A token one reading alone reads (a
    speck for "5") names no light, so no clue the lists lost is called the
    theme's (file_gale_listener.mended)."""
    read = [got for ws in words.values() if (got := theme_line(ws))]
    if not read:
        return None
    count = collections.Counter(t for _, toks in read for t in set(toks))
    kept = [t for t in max((toks for _, toks in read), key=len) if count[t] >= THEME_VOTES]
    kept += sorted({t for t, c in count.items() if c >= THEME_VOTES} - set(kept))
    if len(kept) < THEME_MIN:
        return None
    title = collections.Counter(t for t, _ in read).most_common(1)[0][0]
    return {"title": title, "lights": kept}


def page_blanks(img, located):
    """The printed blanks ("——") in the page's clue lists
    (ocr_clues.blank_strokes), placed by the lists' lines the page's
    words (`located`) give."""
    lines = [(x0, y0, x1, y1) for col in page_columns(located) or () for y0, y1, x0, x1, _ in col]
    heights = sorted(w[3] - w[1] for w in located if re.fullmatch(r"[A-Za-z]{2,12}\W?", w[4]))
    return ocr_clues.blank_strokes(img, lines, located, heights[len(heights) // 2]) if lines and heights else []


def read_box(img, key, box, which):
    """[(x0, y0, x1, y1, text)] reader `which` reads in `box` of the page,
    in page coordinates; cached in OCR_CACHE by the box."""
    path = OCR_CACHE / f"{key}.{'-'.join(map(str, box))}.{ocr_clues.reader_key(which)}.json"
    if path.exists():
        return [tuple(w) for w in json.loads(path.read_text())]
    got = [(x0 + box[0], y0 + box[1], x1 + box[0], y1 + box[1], t)
           for x0, y0, x1, y1, t in ocr_clues.read_words(img.crop(box), which)]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_whole(path, json.dumps(got))
    return got


def reread_lines(img, key, which, words, anchors):
    """`words` (a RapidOCR reader's, read band by band) with each clue line
    whose number it lost read again alone: where another reading (each of
    `anchors`: the page's words, the other RapidOCR readings) opens a line
    on a clue number and words that this reading has nothing over, the line
    is cropped from its number to its last word and read by itself. Over a
    whole band the detector can keep a line's end and drop its start (No
    15's "8. A park." read as "park") or drop whole lines (No 97's DOWN
    5-8); alone, it reads it whole."""
    out = list(words)
    for located in anchors:
        out = reread_from(img, key, which, out, located)
    return out


def reread_from(img, key, which, out, located):
    """reread_lines for one anchor reading's words (`located`)."""
    for n in located:
        if not OPENS.match(n[4]):
            continue
        h = n[3] - n[1]
        mid = (n[1] + n[3]) / 2
        if any(w[0] < n[2] and n[0] < w[2] and w[1] < mid < w[3] and OPENS.match(w[4]) for w in out):
            continue  # this reading has the number ("DI." for "11." has not)
        row = sorted((w for w in located if abs((w[1] + w[3]) / 2 - mid) < h / 2 and w[0] >= n[0]),
                     key=lambda w: w[0])
        x1 = n[2]
        for w in row:
            if w[0] - x1 > LINE_GAP * h:
                # The next column's words: a number stands up to ~3.7
                # heights from its words (No 97's wide-set "36.").
                break
            x1 = max(x1, w[2])
        if x1 == n[2]:
            continue  # a number with no words beside it: no clue line
        # The number's own rows: lines set tighter than a number's box is
        # tall (No 97's 46A, 21 px apart) put the next line's centre within
        # a quarter height of it, and that line was taken and lost.
        band = (n[1], n[3])
        # A word of this reading the crop would cut is read whole: the
        # anchor can lose a line's end this reading has (No 4's "38. ...
        # to a house'", its page reading ending at "a").
        x1 = max([x1] + [w[2] for w in out if w[0] < x1 < w[2] and band[0] <= (w[1] + w[3]) / 2 <= band[1]])
        # The detector reads nothing in a crop much tighter than the line.
        box = (max(0, n[0] - h), max(0, n[1] - h // 2), min(img.width, x1 + h), min(img.height, n[3] + h // 2))
        # Its number read as letters ("II." for 11) is a number, as figures reads it.
        got = sorted(figures([w for w in read_box(img, key, box, which) if band[0] <= (w[1] + w[3]) / 2 <= band[1]]),
                     key=lambda w: w[0])
        if got and got[0][0] >= n[2] and not re.match(r"\W{0,2}\d", got[0][4]):
            # Its words alone, all right of the anchor's number: the reader
            # loses a thin number again (No 4's "1. Our subject." read
            # ".Our subject.", then "Our subject."), and the anchor's stands.
            got = [n] + got
        if not got or not (OPENS.match(got[0][4]) or re.fullmatch(r"\d{1,2}", got[0][4])):
            continue
        if got[0][4] == re.match(r"\W{0,2}(\d{1,2})", n[4]).group(1):
            # Read alone, a number often loses its stop ("8" for "8.").
            got[0] = (*got[0][:4], got[0][4] + ".")
        out = [w for w in out if not (box[0] <= (w[0] + w[2]) / 2 <= box[2] and band[0] <= (w[1] + w[3]) / 2 <= band[1])]
        out += got
    return out


#: Tesseract's polytonic Greek model, beside the installed eng: it reads
#: the Greek words a 1930s clue quotes (No 10's "φλογὸς μέγαν") letter for
#: letter, at GREEK_UPSCALE (at ocr_clues.UPSCALE it reads "φλογὺς").
GREEK = "grc"
GREEK_UPSCALE = 3
#: A letter of the Greek script, and a Greek word as the Greek model prints
#: one: lowercase letters, accents and breathings, an elision's mark.
GREEK_LETTER = re.compile(r"[Ͱ-Ͽἀ-῿]")
GREEK_WORD = re.compile(r"[Ͱ-Ͽἀ-῿]+['’᾽]?")
#: The fewest Greek letters the RapidOCR readings print on a clue's lines
#: for the line to be read for Greek at all: their dictionaries hold the
#: Greek letters, so a quoted Greek word comes out part Greek ("μéyav").
GREEK_SEEN = 2
#: The Latin letters a Greek one prints as to a reader without Greek
#: ("aletòs" for "αἰετὸς", "xAwpov" for "χλωρὸν"), and how closely a
#: RapidOCR word must match a Greek word so spelt to show it there.
LOOKALIKE = str.maketrans("αβγδεζηικλμνξοπρστυφχψω", "abydezniklmvzonpstuoxyw")
LOOKALIKE_RATIO = 0.6


def lookalike(greek, latin):
    """Whether `latin`, a reader's word, is `greek` printed in Latin
    lookalike letters (LOOKALIKE), accents aside."""
    plain = lambda t: "".join(c for c in unicodedata.normalize("NFD", t.lower())
                              if not unicodedata.combining(c))
    g, l = plain(greek).translate(LOOKALIKE), plain(letters(latin))
    return len(g) >= 3 and difflib.SequenceMatcher(None, g, l).ratio() >= LOOKALIKE_RATIO
DASHES = re.compile(r"[-–—]+")
#: A piece that is only stops: one a dash parted from its word ("ὀξὺ—,").
PARTED_STOP = re.compile(r"[.,;:!?]+")


def greek_model():
    """The Greek model's .traineddata, beside tesseract's installed eng;
    None on a host with no tesseract (it reads on the desktop or not at all)."""
    try:
        tess = ocr_clues.tesseract()
    except RuntimeError:
        return None
    return Path(tess).resolve().parent.parent / "share" / "tessdata" / f"{GREEK}.traineddata"


def greek_box(img, key, box):
    """[(x0, y0, x1, y1, text)] the Greek model reads in `box` of the page,
    one line (psm 7: over a looser crop it reads the neighbouring lines'
    edges as words), in page coordinates; cached in OCR_CACHE by the box."""
    path = OCR_CACHE / f"{key}.{'-'.join(map(str, box))}.{GREEK}.json"
    if path.exists():
        return [tuple(w) for w in json.loads(path.read_text())]
    crop = img.crop(box).convert("RGB")
    crop = crop.resize((crop.width * GREEK_UPSCALE, crop.height * GREEK_UPSCALE))
    got = [(x0 // GREEK_UPSCALE + box[0], y0 // GREEK_UPSCALE + box[1], x1 // GREEK_UPSCALE + box[0],
            y1 // GREEK_UPSCALE + box[1], t) for x0, y0, x1, y1, t in ocr_clues.tesseract_words(crop, greek_model(), psm=7)]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_whole(path, json.dumps(got))
    return got


def clue_lines(img, words, lid):
    """The page boxes of light `lid`'s clue lines, from the first reading
    (`words`, {reader: words}) whose lists (page_columns) number it: its
    numbered line and the lines run on under it, each padded to hold its
    letters whole. [] when none does."""
    n, way = lid.split("-")
    for which in ["page", *ocr_clues.READERS]:
        cols = page_columns(words.get(which) or [])
        lines = cols[way == "down"] if cols else []
        at = next((i for i, ln in enumerate(lines) if (m := al.LINE_CLUE.match(ln[4])) and m.group(1) == n), None)
        if at is None:
            continue
        end = next((j for j in range(at + 1, len(lines)) if al.LINE_CLUE.match(lines[j][4])), len(lines))
        out = []
        for y0, y1, x0, x1, _ in lines[at:end]:
            h = y1 - y0
            out.append((max(0, x0 - h), max(0, y0 - h // 4), min(img.width, x1 + h), min(img.height, y1 + h // 4)))
        return out
    return []


def pieces(ws):
    """[(x0, y0, x1, y1, text, dash_before)]: `ws`'s words cut at their
    dashes ("μέγαν—Aeschylus."), each piece's box its share of the word's
    width by its letters."""
    out = []
    for x0, y0, x1, y1, t in ws:
        parts = DASHES.split(t)
        at, width = 0, max(1, len(t))
        for k, p in enumerate(parts):
            if p:
                out.append((x0 + (x1 - x0) * at / width, y0, x0 + (x1 - x0) * (at + len(p)) / width, y1, p, k > 0))
            at += len(p) + 1
    return out


def letters(t):
    return re.sub(r"\W|\d|_", "", t).lower()


def over(p, w):
    """Whether piece `p`'s centre falls inside box `w`."""
    cx, cy = (p[0] + p[2]) / 2, (p[1] + p[3]) / 2
    return w[0] <= cx <= w[2] and w[1] <= cy <= w[3]


def greek_text(img, key, words, boxes):
    """A clue's text with its Greek words read by the Greek model, or None.
    Each piece of the Greek model's reading (pieces) is Greek when it
    prints as a Greek word (GREEK_WORD, lowercase: that model reads Latin
    capitals as Greek ones, "Ηογηςῖ" for "Homer") and the English readers
    garble it: a RapidOCR reading prints a Greek letter there, or no two
    Tesseract readings agree there on a known word. Any other piece is
    English, taken from a Tesseract reading of it that is a known word or
    that two of them agree on; a piece neither way gives None. The clue
    quotes Greek when its RapidOCR readings print GREEK_SEEN Greek letters
    or a Greek word it takes is printed there in Latin lookalikes
    ("aletòs" for "αἰετὸς") that are no word. A line the Greek model reads
    nothing on over its padded box is read over a tighter one (the pad
    takes in the edges of the lines around it), and failing that is
    English: its pieces are the eng model's."""
    inside = lambda w: any(over(w, b) for b in boxes)
    rapid = [w for which in ocr_clues.READERS if which not in ocr_clues.TESS_MODELS
             for w in words.get(which, ()) if inside(w)]
    seen = sum(len(GREEK_LETTER.findall(w[4])) for w in rapid) >= GREEK_SEEN
    tess = [pieces([w for w in words.get(k, ()) if inside(w)]) for k in ("page", *ocr_clues.TESS_MODELS)]
    tess.append(pieces([w for b in boxes for w in read_box(img, key, b, next(iter(ocr_clues.TESS_MODELS)))]))
    greek = pieces([w for b in boxes for w in greek_box(img, key, b) or greek_box(img, key, tighter(b))
                    or read_box(img, key, b, next(iter(ocr_clues.TESS_MODELS)))])
    out, any_greek, looked = "", False, False
    used = set()
    for p in greek:
        near = [[q for q in t if over(q, p[:4]) or over(p, q[:4])] for t in tess]
        there = [[q[4] for q in t] for t in near]
        # The clue's number; a reading's number stretched over the words
        # after it (No 10 20A's "6" over "αἰετὸς ὀξὺ—,") makes no Greek
        # word or stop one. A lone Greek letter is the number misread ("γ."
        # for "7.").
        word = p[4].rstrip(".,;:")
        kept = GREEK_WORD.fullmatch(word) and word.islower() and len(word) > 1 or PARTED_STOP.fullmatch(p[4])
        if not kept and any(t and all(re.fullmatch(r"\W{0,2}\d{1,2}\W{0,2}", q) for q in t) for t in there):
            continue
        said = [letters(" ".join(t)) for t in there if t]
        agreed = next((s for s in said if said.count(s) > 1 and ocr_clues.known(s)), None)
        hinted = alike = False
        for w in rapid:
            if w[1] <= (p[1] + p[3]) / 2 <= w[3] and w[0] <= (p[0] + p[2]) / 2 <= w[2]:
                at = int(((p[0] + p[2]) / 2 - w[0]) / max(1, w[2] - w[0]) * len(w[4]))
                tok = re.search(r"\S*$", w[4][:at]).group() + re.match(r"\S*", w[4][at:]).group()
                hinted |= bool(GREEK_LETTER.search(tok))
                alike |= lookalike(word, tok) and not ocr_clues.known(letters(tok))
        if PARTED_STOP.fullmatch(p[4]):
            text = p[4]  # a stop the dash before it parted from its word ("ὀξὺ—,")
        elif GREEK_WORD.fullmatch(word) and word.islower() and (hinted or alike or not agreed):
            text, any_greek, looked = p[4], True, looked or alike
        else:
            found = [" ".join(t) for t in there if t]
            pick = next((k for k, f in enumerate(found) if ocr_clues.known(letters(f)) or
                         sum(letters(o) == letters(f) for o in found) > 1), None)
            if pick is None:
                return None
            # Two Greek-model pieces over one English word ("ΑΘΞοΗν 5." for
            # "Aeschylus.") give it once.
            source = {q[:4] for q in [t for t in near if t][pick]}
            if source <= used:
                continue
            used |= source
            text = found[pick]
        out += ("—" if p[5] else (" " if out else "")) + text
    return out.strip() if any_greek and (seen or looked) else None


def tighter(box):
    """`box` with an eighth of its height off its top and its bottom."""
    cut = (box[3] - box[1]) // 8
    return (box[0], box[1] + cut, box[2], box[3] - cut)


def greek_mended(img, key, words, verdict, laid):
    """`laid` with each light the vote left blank whose clue quotes Greek
    (greek_text) read with its Greek words; each noted in the verdict's
    "greek", with the vote's reason for the blank, and its Greek words in
    its "asPrinted"; a line is mended into one light only."""
    taken = []
    for lid, (t, e, g) in list(laid.items()):
        if t or not (boxes := clue_lines(img, words, lid)):
            continue
        # A line another light's mend read is that light's, not this one's.
        if any(over(b, o) or over(o, b) for b in boxes for o in taken):
            continue
        if text := greek_text(img, key, words, boxes):
            taken += boxes
            laid[lid] = (text, e, g)
            verdict.setdefault("greek", {})[lid] = verdict.get("blank", {}).pop(lid, "blank")
            # Its Greek words are as printed: no English lexicon knows them.
            verdict.setdefault("asPrinted", {})[lid] = [w for w in text.split() if GREEK_LETTER.search(w)]
    if not verdict.get("blank"):
        verdict.pop("blank", None)
    verdict["agreed"] = sum(1 for t, _, _ in laid.values() if t)
    return laid


def see_pages(pages):
    """A refusal's note of where the page sends the puzzle's rest."""
    return f" (it sends to p. {', '.join(map(str, pages))})" if pages else ""


def times_read(blocks):
    """(verdict, laid) of a Times page's blocks (times_blocks): the first's
    reading (else the fullest other's), each other reading kept in its
    verdict's "alternatives" ({"cut": its index, "clues", "agreed",
    "laid"}), which the filer tries in turn where the reading's lights are not
    the grid's (file_gale_listener.join)."""
    read = [(i, *read_page(img, key)) for i, (img, key) in enumerate(blocks)]
    got = [r for r in read if r[2]]
    if not got:
        return read[0][1], None
    first = got[0] if got[0][0] == 0 else max(got, key=lambda r: r[1]["agreed"])
    verdict, laid = first[1], first[2]
    if alts := [{"cut": i, "clues": v["clues"], "agreed": v["agreed"], "laid": la}
                for i, v, la in got if i != first[0] and la != laid]:
        verdict = {**verdict, "cut": first[0], "alternatives": alts}
    return verdict, laid


def read_file(m):
    """(verdict, laid) of the fullest page of a matched file; of a Times
    page's Listener block alone (times_block)."""
    best = ({"refused": "no page image"}, None)
    for img, key in m["pages"]:
        if m.get("times"):
            if not (blocks := times_blocks(img, key)):
                if not best[1]:
                    best = ({"refused": "no Listener clue lists found on the Times page"}, None)
                continue
            verdict, laid = times_read(blocks)
        else:
            verdict, laid = read_page(img, key)
        if laid and (not best[1] or verdict["agreed"] > best[0]["agreed"]):
            best = (verdict, laid)
        elif not best[1] and "refused" in verdict:
            best = (verdict, None)
    return best


def model_hash(path):
    """The sha1 of a model file, or None when it is missing."""
    return hashlib.sha1(path.read_bytes()).hexdigest() if path and path.exists() else None


def read_remote(p, h, idx):
    """(match(p, idx), read_file() of it) of the saved file `p` (sha256 `h`)
    read on the desktop (read_there) when tools/ocr_remote.py can, else
    None. The file, the index and the OCR cached for its pages are sent,
    their whole-page Tesseract read (page_words) made here first: over a
    whole page the desktop's build lays out other lines than this host's,
    where over a band or a line it reads the same. The match has no pages;
    the OCR it cached is kept in OCR_CACHE and the page grids it found in
    file_gale_listener's cache, so filing reads none of the page here."""
    import io
    import tarfile

    import ocr_remote
    if ocr_remote.session() is None:  # unset, busy or not answering: nothing to make here for it
        return None
    try:
        pages = gi.images(p)
    except (OSError, ValueError):  # read_one says why, reading it here
        return None
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(p, arcname=f"file/{p.name}")
        for img, _ in pages:
            key = image_key(img)
            page_words(img, key)
            for f in sorted(OCR_CACHE.glob(f"{key}.*")):
                tar.add(f, arcname=f"ocr/{f.name}")
    got = ocr_remote.call("listener_read", p.name, h, [{**r, "date": r["date"].isoformat()} for r in idx],
                          model_hash(greek_model()), data=buf.getvalue())
    if got is None:
        return None
    (got, back) = got
    with tarfile.open(fileobj=io.BytesIO(back)) as t:
        t.extractall(OCR_CACHE, filter="data")
    import file_gale_listener  # it imports this module
    file_gale_listener.GRIDS.mkdir(parents=True, exist_ok=True)
    write_whole(file_gale_listener.GRIDS / f"{h}.json", got["grids"])
    m = got["match"]
    m.update(date=m.get("date") and datetime.date.fromisoformat(m["date"]), pages=[])
    laid = got["laid"] and {lid: tuple(v) for lid, v in got["laid"].items()}
    return m, (got["verdict"], laid)


def read_there(data, name, sha, rows, greek):
    """tools/ocr_remote.py's "listener_read", run on the desktop: ({"match":
    match() of the saved file named `name` without its pages, its date ISO,
    "verdict", "laid": read_file() of it,
    "grids": file_gale_listener.page_grids' cache file for it}, a tar of the
    OCR it cached), the file and its cached OCR in the tar `data`, `rows`
    the index (dates ISO), `greek` the Mac's greek_model() hash; raises when
    the Greek model here is not that one or the read opened a file it was
    not sent."""
    import gc
    import io
    import tarfile
    import tempfile

    import file_gale_listener
    import ocr_remote
    if model_hash(greek_model()) != greek:
        raise ValueError(f"the Greek model here is not the Mac's ({greek_model()})")
    global OCR_CACHE
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(root, filter="data")
        (root / "ocr").mkdir(exist_ok=True)
        sent = {f.name: f.read_bytes() for f in (root / "ocr").iterdir()}
        idx = [{**r, "date": datetime.date.fromisoformat(r["date"])} for r in rows]
        OCR_CACHE, kept = root / "ocr", OCR_CACHE
        ocr_remote._WATCH[:] = [(str(root), str(TOOLS.parent)), []]
        try:
            m = match(root / "file" / name, idx)
            verdict, laid = read_file(m) if m["number"] is not None else ({}, None)
            file_gale_listener.page_grids(root / "file" / name, sha, cache=root / "grids")
        finally:
            missing, ocr_remote._WATCH[:] = ocr_remote._WATCH[1], [None, []]
            OCR_CACHE = kept
        if missing:
            raise FileNotFoundError("opened files it was not sent: " + ", ".join(sorted(set(missing))[:5]))
        m.pop("pages")
        if m.get("date"):
            m["date"] = m["date"].isoformat()
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for f in sorted((root / "ocr").iterdir()):
                if sent.get(f.name) != f.read_bytes():
                    tar.add(f, arcname=f.name)
        grids = (root / "grids" / f"{sha}.json").read_text()
        gc.collect()  # closes the file, which Windows will not delete open
        return {"match": m, "verdict": verdict, "laid": laid, "grids": grids}, buf.getvalue()


def reading(m, row, verdict, laid):
    """The reading written to STORE: archive_org_listener.reading's shape,
    and a Times page's other cuts' readings (times_read) as its
    "alternatives" [{"cut", "agreed", "of", "clues"}], their clues in its
    "clues"' shape."""
    alts = verdict.pop("alternatives", None)
    alike = verdict.get("asPrinted", {})
    suspects = {lid: s for lid, (t, _, _) in laid.items() if t and (s := ocr_clues.suspect(t, printed=alike.get(lid, ())))}
    if suspects:
        verdict["suspect"] = {lid: [tok for tok, _ in s] for lid, s in suspects.items()}
    return {
        **({"alternatives": [{"cut": a["cut"], "agreed": a["agreed"], "of": a["clues"],
                              "clues": {lid: {"text": t, "enumeration": e, **({"group": grp} if grp else {})}
                                        for lid, (t, e, grp) in a["laid"].items()}} for a in alts]}
           if alts else {}),
        "id": f"listener-{row['number']}",
        "number": row["number"],
        "series": lp.SERIES,
        "name": f"Listener crossword No {row['number']:,}: {row['title']}",
        "setter": row.get("setter"),
        "date": row["date"].isoformat(),
        "source": {"publisher": "The Times" if m.get("times") else "The Listener", "retrievedFrom": "gale",
                   "file": m["file"],
                   "url": (gi.DOC_URL if m.get("times") else DOC_URL).format(m["docId"]) if m.get("docId") else PORTAL},
        "unfiled": "clues only: the grid and answers are still to be rebuilt",
        "verdict": verdict,
        "clues": {lid: {"text": t, "enumeration": e, **({"asPrinted": alike[lid]} if lid in alike else {}),
                        **({"group": grp} if grp else {})}
                  for lid, (t, e, grp) in laid.items()},
    }


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_whole(path, text):
    """Write `text` to `path` whole: to a hidden file beside it, then
    renamed over it, so a parallel unit reading it sees the old file or the
    new, never a torn one (over the share a shorter rewrite in place left
    listener-102.json torn, 10-23)."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(text)
        for wait in (0.2, 0.5, 1, 2, None):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                # A share's server may refuse the rename while a reader
                # holds the old file open: a moment later it is closed.
                if wait is None:
                    raise
                time.sleep(wait)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path):
    """json.loads of `path`, or None when it is missing or torn (written in
    place by a writer from before write_whole)."""
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, ValueError):
        return None


#: The ledger: one row a read, appended ({"sha": the file's sha256, ...});
#: the last row a file standing. LEGACY is the whole-file ledger it grew
#: from, read beneath it.
LEDGER = "ledger.jsonl"
LEGACY = "ledger.json"


def load_ledger(store):
    """{file sha256: its last entry}."""
    import scan_queue
    path = store / LEGACY
    out = json.loads(path.read_text()) if path.exists() else {}
    for sha, row in scan_queue.ledger_rows(store / LEDGER, "sha").items():
        out[sha] = {k: v for k, v in row.items() if k != "sha"}
    return out


def disown(p, before, number, store):
    """Drop the reading in `store` the saved file `p` wrote under the number
    its last ledger row `before` gave it, now that it matches `number` (or
    none), or the number a hand repair of the row dropped ("numberDropped":
    {"was"}): that reading is another puzzle's clues (CITE_FIX: No 17's read
    as No 15's). Kept when a page of its own number has since replaced it.
    Returns the dropped reading's name, or None."""
    import scan_queue
    before = before or {}
    for old in (before.get("number"), (before.get("numberDropped") or {}).get("was")):
        if not isinstance(old, int) or old == number:
            continue
        path = store / f"listener-{old}.json"
        with scan_queue.lock(path, wait_for_it=True):
            got = read_json(path)
            if not got or (got.get("source") or {}).get("file") != p.name:
                continue
            path.unlink()
        return path.name
    return None


def read_one(p, h, idx, rows, store, out=sys.stdout, reader=read_file, before=None):
    """Read the saved file `p` (sha256 `h`), write its puzzle's reading to
    `store` when it is the fullest yet, and append its ledger row. Returns
    the entry, or None when the read timed out (not ledgered: read again).
    `before`, the page's last ledger row: a reading it wrote under another
    number than it now matches is dropped (disown)."""
    import scan_queue
    entry = {"file": p.name, "version": VERSION, "readOn": datetime.datetime.now().astimezone().date().isoformat()}
    m = None
    failed = False
    try:
        got = read_remote(p, h, idx) if reader is read_file else None
        if got is not None:
            m, (verdict, laid) = got
        else:
            import ocr_remote
            with ocr_remote.local_slot():
                try:
                    m = match(p, idx)
                except (OSError, ValueError) as e:  # reported in the ledger and the checklist
                    m = {"file": p.name, "number": None, "why": f"unreadable: {type(e).__name__}: {e}", "pages": [],
                         "reports": []}
                verdict, laid = reader(m) if m["number"] is not None else ({}, None)
    except subprocess.TimeoutExpired as e:
        # A loaded host's Tesseract: not the page's fault, so it is not
        # ledgered, and the next run reads it again.
        print(f"{p.name}: OCR timed out after {e.timeout:.0f} s; read again next run", file=out)
        return None
    except Exception as e:  # any raise: one page's failure must not stop the pages after it
        # Ledgered with its error, so the checklist shows it and the
        # pages after it are read; a VERSION bump reads it again.
        print(f"{p.name}: read failed:\n{traceback.format_exc()}", file=out)
        why = f"read failed: {type(e).__name__}: {e}"
        if m is None:
            m = {"file": p.name, "number": None, "why": why, "pages": [], "reports": []}
        verdict, laid = {"refused": why}, None
        failed = True
    if not failed and (dropped := disown(p, before, m["number"], store)):
        entry["disowned"] = dropped
        print(f"{p.name}: dropped {dropped}, which it wrote when matched as that number", file=out)
    entry.update(number=m["number"], how=m.get("how"), why=m.get("why"), reports=m["reports"])
    if m.get("times") or is_times(p):
        entry["timesCut"] = TIMES_CUTS
    if verdict.get("seePages"):
        entry["seePages"] = verdict["seePages"]
    if m["number"] is None and m["reports"]:
        entry["why"] = None
    if m["number"] is not None:
        if laid is None:
            entry["why"] = verdict.get("refused", "no reading")
        else:
            entry.update(clues=verdict["clues"], agreed=verdict["agreed"])
            dest = store / f"listener-{m['number']}.json"
            # Two pages of one puzzle read at once: the fuller wins either way.
            with scan_queue.lock(dest, wait_for_it=True):
                try:
                    old = json.loads(dest.read_text()) if dest.exists() else None
                except ValueError:  # torn by an older writer: this reading replaces it
                    old = None
                # A Times page read again replaces its own reading, fuller or not: its cuts' fix may
                # read fewer clues (No 3120's coupon, read as 63 Down, is blanked) and adds alternatives.
                if (old is None or old["verdict"].get("agreed", 0) <= verdict["agreed"]
                        or m.get("times") and (old.get("source") or {}).get("file") == m["file"]):
                    # Whole or not at all: filing reads every reading while another unit writes one, and
                    # over the share a shorter rewrite in place left listener-102.json torn (10-23).
                    write_whole(dest, json.dumps(reading(m, rows[m["number"]], verdict, laid), indent=1,
                                                 ensure_ascii=False) + "\n")
                    entry["reading"] = dest.name
                    mm.record(READINGS_MANIFEST, dest, number=m["number"])
    scan_queue.append(store / LEDGER, [{"sha": h, **entry}])
    mm.record(LEDGER_MANIFEST, store / LEDGER, sha=h, number=entry.get("number"), reports=entry.get("reports") or [])
    print(f"{p.name}: " + (f"No {m['number']} ({m['how']}), " if m["number"] is not None else "")
          + (f"{entry['agreed']}/{entry['clues']} clues read" if "agreed" in entry else entry["why"] or "a report page")
          + "".join(f", the solution of No {n}" for n in m["reports"]), file=out)
    return entry


def page_files(inbox):
    """The saved pages in `inbox`, its FETCHED subfolder and the Times' (TIMES),
    by name (a name is never in two: the fetcher's are GALE_<doc>, Paul's
    <doc>, and a Times document is no magazine's)."""
    out = []
    for d in (Path(inbox), Path(inbox) / FETCHED, Path(inbox) / TIMES):
        if d.is_dir():
            out += [p for p in d.iterdir() if not p.name.startswith(".") and p.suffix.lower() in gi.PAGES
                    and p.is_file()]
    return sorted(out, key=lambda p: (p.name, p.parent != Path(inbox)))


def page_path(inbox, name):
    """Where the saved page `name` (a ledger row's "file", a unit's "rel")
    is: in `inbox`, else its FETCHED subfolder, else the Times' (TIMES)."""
    p = Path(inbox) / name
    for d in (FETCHED, TIMES):
        if not p.exists() and (Path(inbox) / d / name).exists():
            p = Path(inbox) / d / name
    return p


def doc_of(name):
    """The Gale document a saved page's name carries (GM2500000225), or None."""
    doc = gi.DOC_ID.search(name) or re.search(r"(GM\d{8,12})(?!\d)", name)
    return doc.group(1).upper() if doc else None


_HASHES = {}
#: The hashes kept across processes (the queue re-execs every slice, and each
#: image read every saved page in full on its first plan): "name|size|mtime_ns" -> sha256.
HASH_CACHE = Path(os.environ.get("GALE_HASH_CACHE") or Path.home() / ".cache" / "gale_page_hashes.json")
_LOADED = []


def _hash_key(k):
    name, size, mtime = k.rsplit("|", 2)
    return (name, int(size), int(mtime))


def _load_hashes():
    if not _LOADED:
        _LOADED.append(True)
        try:
            _HASHES.update({_hash_key(k): v for k, v in json.loads(HASH_CACHE.read_text()).items()})
        except (OSError, ValueError):
            pass


def _save_hashes():
    try:
        HASH_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = HASH_CACHE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"|".join(map(str, k)): v for k, v in _HASHES.items()}))
        os.replace(tmp, HASH_CACHE)
    except OSError:
        pass


def hash_of(p):
    """file_hash(p), worked out again only when its size or mtime moved."""
    _load_hashes()
    st = p.stat()
    key = (p.name, st.st_size, st.st_mtime_ns)
    if key not in _HASHES:
        _HASHES[key] = file_hash(p)
        _save_hashes()
    return _HASHES[key]


def run(inbox=SAVED, store=STORE, idx=None, out=sys.stdout, reader=read_file):
    """Read every file in `inbox` the ledger has not read at this VERSION;
    write each puzzle's reading to `store` (a fuller one replaces it).
    Returns the ledger."""
    idx = index(times=True) if idx is None else idx
    rows = {r["number"]: r for r in idx}
    store.mkdir(parents=True, exist_ok=True)
    ledger = load_ledger(store)
    for p in page_files(inbox):
        h = file_hash(p)
        if ledger.get(h, {}).get("version") == VERSION:
            continue
        entry = read_one(p, h, idx, rows, store, out, reader, before=ledger.get(h))
        if entry is not None:
            ledger[h] = entry
    return ledger


def plan(inbox=SAVED, store=STORE):
    """The saved pages not read at this VERSION, one read unit each
    (tools/edition_queue.py), the earliest saved first: one never read is
    rank 0, never read like the Gale Times pages ("never read (Gale fetch)"); one read at an older
    VERSION is a whole-corpus re-read, rank 3 (file_archive_org_puzzles.BLANKET)."""
    ledger = load_ledger(store)
    # A page is known by its Gale document where its name gives one, so a
    # second download of a document read already (the fetcher's copy of one
    # Paul saved by hand: the same page stamped apart) is no unit, and no
    # page need be hashed to plan (3,000 PDFs over the share). The copy
    # named for its date is read first (match() trusts its name's date).
    docs = {}
    for row in ledger.values():
        d = doc_of(row.get("file") or "")
        if d:
            docs[d] = max((docs[d], row) if d in docs else (row,),
                          key=lambda r: (r.get("version") == VERSION, r.get("version") or 0))
    todo, seen = {}, set()
    for p in sorted(page_files(inbox), key=lambda p: (gi.name_date(p.name, DATES) is None, bool(COPY.search(p.name)),
                                                      p.parent != Path(inbox), p.name)):
        d = doc_of(p.name)
        if d is None:
            row = ledger.get(hash_of(p))
        elif d in seen:
            continue
        else:
            seen.add(d)
            row = docs.get(d)
        if not current(p, row):
            todo[p] = row
    # A Times page first in its rank: ~85 modern pages that may file whole, not behind ~2,850 of the
    # magazine's never read (their mtimes all earlier).
    due = sorted(((p, TIMES_REREAD if (row or {}).get("version") == VERSION else due_reason(row))
                  for p, row in todo.items()),
                 key=lambda pr: (rank_of(pr[1]), clues_left(todo[pr[0]], pr[1]), not is_times(pr[0]),
                                 pr[0].stat().st_mtime))
    return [{"rel": p.name, "rank": rank_of(reason), "reason": reason, "needs": []} for p, reason in due]


def clues_left(row, reason):
    """How many clues a page read SHORT last left unagreed: plan reads the
    nearest whole first, as they are the rereads that file (No 254 at 21 of
    27, No 601 at 35 of 44 waited behind ~600 rereads in file order, 10-24).
    Every other page ranks after them in its rank, in file order."""
    if reason == SHORT and row:
        return max(0, (row.get("clues") or 0) - (row.get("agreed") or 0))
    return float("inf")


def rank_of(reason):
    """A plan reason's rank: fa.RANKS', "version changed" a blanket re-read."""
    return fa.BLANKET if reason == "version changed" else fa.RANKS[reason]


#: The VERSION whose page_columns reads the 1934-40 lists printed as
#: paragraphs ("(1) clue. (10) clue."): a page that ended "no reading
#: parses" at an older one is read again for it (evidence, not blanket).
PARAGRAPHS = 13
#: The refusal those pages ended on.
UNPARSED = "no reading parses"
#: The VERSION reading the 1932-33 lists set as a table (hanging_numbers),
#: headed "CLUES—ACROSS.", opening "(mixed)" or "9,36.Inversely", and
#: passing over a page that holds only a report: a page read before it with
#: its clue list short, or none parsed, is read again (evidence: on 40
#: fetched 1930s pages Nos 114, 127, 141, 147, 148 gained 1-26 clues and 5
#: more were seen to be reports alone). 17: the 1941 lists setting each
#: "(N)" in a gutter of its own (para_numbers), a DOWN heading below a gap
#: and a "(1)" misread mid-list no longer ending the across list (No 582:
#: 0 numbered clues on its page read before, 13 across and 12 down after).
#: 18: a report's "30 Down, the word ..." beside the lists no longer chained
#: on as a clue (CITING), so the down list's run-on at the next column's top
#: follows it again (No 174: 15 of its grid's 21 downs read before, 20 after).
#: 19: a list whose one heading was read no longer dropped: an unread DOWN's
#: gap over a paragraph list's "(1)" no longer ends it, a bracket of lights
#: ("(1, 8, 52)", "(40-22)", "(47 anag.)") is numbered by its first, and
#: under a lone DOWN the across list is read up from its "1." (page reads,
#: numbered clues before -> after: No 443 0 -> 52, No 449 0 -> 38, No 133 0 -> 19).
#: 20: the paragraph lists' ACROSS heading is a heading alone on its line,
#: not a clue's "See 37 Across.", and the across list run on at the next
#: column's top above the heading's level is read, as is "(45 rev.)" (No
#: 242, 1934: its page read 7 across before, 22 across and 22 down after).
#: 21: a paragraph list's bracket read with a figure as a letter ("(Is)",
#: "(3o)", "(z1)", "(1g rev.)") or full-width, or with the clue's capital
#: hard on it ("(26rev.)Muddled"), numbers its clue; "See (31) Down." does
#: not (numbered clues before -> after: No 261's ch 6A 7D -> 18A 19D, en5
#: 15A 4D -> 18A 18D; No 254's ch 9A 4D -> 18A 19D). The across list run on
#: above the heading's level with DOWN's heading there, a grid's numbers
#: under a column, and a paragraph page's chance line-numbered headed
#: reading (No 245, 1934: its reading 1 of 9 clues before, 40 of 47 after).
#: 22: a paragraph clue number misread high ("(1, 40)" for (11, 40)) no
#: longer drops the clues after it; stars inside the bracket ("(**10)"),
#: "(43 rev. in 42)" and an unclosed "(1 Protects" number their clues; a
#: bracket of two lights ("(10, 39)", "(38-45)", "(4) & (28)") clues both,
#: the filer finding the second in the other list where its own has none;
#: a lent heading no longer takes the line set under it, nor does the
#: last report's heading run on into the last clue (No 254: 34 -> 39 of 41
#: agreed; No 273: 25 -> 39 of 43; No 245: 40 -> 44 of 51).
#: 23: a run of words one reading lost stays one gap in the vote, and goes
#: in whole when two readings print it (No 254 38A, no longer "One of four
#: One of fierce' who strive"); a quote never opened takes a reading's
#: alike but for its quotes; "of 1 A" ending a clue is no next clue run on
#: (No 601 2D). No 254: 41 -> 42 of 42; No 601: 42 -> 43 of 43.
#: 24: a number a clue cites between its words, which the vote takes for a
#: clue's bound, is put back ("With 15 Down", not "With Is Down"; al.cited)
#: and a zero in a word read "o" ("to0"); "(12 in 3)", "(8-s)", "(Anag.
#: 28B)" and a later light read with a letter for a figure ("(2-4oA)") number
#: their clues; a lettered link in the list's own direction ("(29-35U)")
#: links (No 242: 48 -> 49 of 49, its lights now its clue list's; No 273:
#: 39 -> 44 of 46, 31 and 35 down linked).
#: 25: a clue one reading lays clean and another runs on into the next
#: clue is laid (al.ran_on: No 434's 9D "There's one on the drum.(io) The
#: stone ..."); a clue opening on a light it cites ("25 lacks cohesion",
#: "37's right half.") or "anag." is a clue (al.sound); a quote one reading
#: opens with its mark spaced off ("' Who therein") opens (No 386); a
#: list's last clue read on into the competition's rules ends there
#: (rules_cut: No 447's 36D, No 503's 32D). No 434: 61 -> 62 of 62; No
#: 471: 39 -> 41 of 41; No 447: 31 -> 32 of 32; No 503: 39 -> 40 of 40.
#: 26: a bracket lettering its second light the other list's way ("(12-29D)"
#: among the across clues) links it too, the filer pointing it at that
#: light (No 471: 41 -> 42 of 42, 12A/29D and 34A/28D linked); a theme line
#: over the lists naming lights no list clues (No 447's "CANVAS / The 26s
#: that 28U 7D 7A 5, ...") is kept as the verdict's "theme" (theme_lights).
#: 27: a quotation the vote leaves closed but never opened takes the
#: opening mark a reading prints before the same words, mid-clue or in a
#: run-on line ("E.g., 'Rejoice", "to 'tay and stuff'"; ocr_clues.opened_inside),
#: and a double opening only a single shuts is that single ("'The Club'";
#: single_opened), each when a reading of the clue prints its words:
#: the most common named reason a page reads short by 1-4 clues ("a quotation it
#: never closes", 61 of the stored short pages' blanks). A clue number
#: glued mid-line to the ellipsis its quotation opens on starts its clue
#: (al.ellipsis_heads): No 617 37A no longer cut to "'..." and its 35A no
#: longer voted "Rabbit-headed plant 37.".
CLUES_FIX = 27
SHORT = "refused clues-short before its fix"
#: The VERSION whose match() reads the citation's date again: from
#: PARAGRAPHS to it a clue regex shadowed CITED, so cited_day read none, and
#: a page the citation dates was numbered by its title read or not at all.
#: The 1930-33 pages print the title in a script face no reader reads, and
#: under it "(The Report on Crossword No. 15 will be found on page 155)":
#: No 17's page was read as No 15 (so Nos 16, 19, 23, 24, 27, 31, 49, 58,
#: 103, 114, ... each held the clues of the puzzle two on); a 1942 page
#: cited "Report on No. 649", 3 Sept. 1942, read "Crossword No. 65[1]" and
#: replaced No 65's reading with No 651's clues; and the 1930 pages of Nos
#: 0-16 citing no number were refused "no date or number". A page so
#: matched is read again (MISNUMBERED), and a reading it wrote under a
#: number it no longer matches is dropped (disowned).
CITE_FIX = 28
MISNUMBERED = "refused misnumbered before its fix"


#: The revision of a Times page's cuts (times_cuts) its ledger row's
#: "timesCut" records: 2 cuts "ACR", blanks the prizes and entry coupon, and
#: reads the box from the title and unblanked as alternatives; 3 blanks
#: nothing for a SOLUTIONS, ANSWERS or Prizes word above the headings' level
#: (the preamble's) and runs a SOLUTIONS block's mask past its notes' pairs
#: ("26 Pele; 27 otto;", NOTES_PAIR). A Times page read at VERSION under an
#: older one is read again (TIMES_REREAD), not the magazine's.
TIMES_CUTS = 3
TIMES_REREAD = "Times Listener page read before its cut's fix"


def current(p, row):
    """Whether the saved page `p`, last ledgered `row`, is read at this
    VERSION, and a Times page's under these TIMES_CUTS."""
    return (row or {}).get("version") == VERSION and (not is_times(p) or row.get("timesCut", 1) >= TIMES_CUTS)


def due_reason(row):
    """Why plan reads a page again, given its last ledger row (None: never
    read): "never read (Gale fetch)"; MISNUMBERED for one numbered by its
    title read, or by nothing, while CITED was shadowed (CITE_FIX); fa's "refused no-reading-parses before
    its fix" for one that ended UNPARSED before CLUES_FIX (PARAGRAPHS until
    then), SHORT for one whose clue list came out short before it (reasons
    tools/edition_queue.py plans with blanket rereads off); else the
    blanket "version changed"."""
    if not row:
        return "never read (Gale fetch)"
    if PARAGRAPHS <= (row.get("version") or 0) < CITE_FIX and "how" in row and row["how"] in ("title read", None):
        return MISNUMBERED
    if row.get("why") == UNPARSED and (row.get("version") or 0) < CLUES_FIX:
        return "refused no-reading-parses before its fix"
    if row.get("agreed", 0) < row.get("clues", 0) and (row.get("version") or 0) < CLUES_FIX:
        return SHORT
    return "version changed"


def read_unit(name, inbox=SAVED, store=STORE, reader=read_file, out=sys.stdout, file_it=True):
    """Read one saved page (tools/edition_queue.py's unit), under its own
    lock, its ledger row appended; then file what the readings now give
    (file_gale_listener.run, one at a time).
    Returns "read", "current", "busy" or "failed" (its OCR timed out)."""
    import scan_queue
    p = page_path(inbox, name)
    if not p.exists():
        return "current"
    h = file_hash(p)
    store.mkdir(parents=True, exist_ok=True)
    with scan_queue.source_lock(store / LEDGER, h) as mine:
        if not mine:
            return "busy"
        before = load_ledger(store).get(h)
        if current(p, before):
            return "current"
        idx = index(times=is_times(p))
        entry = read_one(p, h, idx, {r["number"]: r for r in idx}, store, out, reader, before=before)
        if entry is None:
            return "failed"
    # Only the puzzles this page can move are joined again: its own and those
    # it reports on (file_gale_listener.run's numbers), not every reading.
    # A report's heading is rarely read (285 of 471 pages with a filled grid
    # name none), so the REPORT_WITHIN Nos before its own are joined too: the
    # filled grid may be one of theirs, whose answers then file.
    import file_gale_listener  # it imports this module
    own = entry.get("number")
    numbers = {n for n in [own, *(entry.get("reports") or ()),
                           *(own - k for k in range(1, file_gale_listener.REPORT_WITHIN + 1) if isinstance(own, int))]
               if isinstance(n, int) and n > 0}
    if file_it and numbers:
        # The grids of every page the filing joins, this one's first, are found (and cached by its hash,
        # page_grids) before the filing lock: under it they held every other Listener unit waiting (10-24:
        # 72% of units waited, median 110 s, for a median 168 s unit; No 4002's unit held it 1000 s finding
        # No 4000's page, ledgered by its own unit and not yet found). Under the lock only this page is
        # found (its search timed out above, which the run says); another not cached waits for its own unit.
        file_gale_listener.find_grids(store, inbox, numbers, first=p.name)
        with scan_queue.lock(store / "filing", wait_for_it=True):
            file_gale_listener.run(store, inbox, out=out, numbers=numbers,
                                   grids_of=file_gale_listener.filing_grids(p.name, out=out))
    return "read"


# ------------------------------------------------------------ what to fetch

def lay_out_fetched(day, doc, data, report=False, saved=SAVED):
    """Save the page PDF `data` tools/gale_fetch.py downloaded (Gale
    document `doc` of the issue of `day`) in `saved`, where plan() finds it:
    named for its date, which match() gives the issue's puzzle; a report
    page (`report`) by its document alone, its citation naming the puzzle
    it reports on. Written whole or not at all (page_files skips the
    hidden part). Returns its path."""
    name = f"GALE_{doc}.pdf" if report else f"{day.isoformat()} GALE_{doc}.pdf"
    saved.mkdir(parents=True, exist_ok=True)
    tmp = saved / f".{name}.part"
    tmp.write_bytes(data)
    tmp.replace(saved / name)
    return saved / name


def wanted(idx=None, store=STORE, root=ROOT):
    """[(date, number, report)] for tools/gale_fetch.py, earliest first:
    each printed puzzle neither filed nor read into a reading (its page, report
    False), and each saved or still to fetch whose report page no saved
    page holds (report True: "Report on Crossword No. N", found in the
    issues after `date`), a puzzle's page before its report."""
    idx = index() if idx is None else idx
    pages = [(r["date"], 0, r["number"]) for r in to_save(idx, store, root)]
    reports = [(r["date"], 1, r["number"]) for r in report_lookups(idx, store, root)]
    return [(d, n, bool(k)) for d, k, n in sorted(pages + reports)]


def _build_readings(store):
    """List STORE's readings once into READINGS_MANIFEST (a cold memo)."""
    found = [{"number": r["number"], "at": p.stat().st_mtime}
             for p in sorted(store.glob("listener-*.json")) if (r := read_json(p))]
    mm.write(READINGS_MANIFEST, found)
    mm.complete_path(READINGS_MANIFEST).write_text(json.dumps({"at": time.time()}))
    return {r["number"] for r in found}


def _glob_readings(store):
    """reading_numbers for a store not on the media disk (a test's): a glob is fine there."""
    return {r["number"] for p in store.glob("listener-*.json") if (r := read_json(p))}


def reading_numbers(store=STORE):
    """{number} of the readings kept in `store`: from READINGS_MANIFEST (which
    read_one appends to) when it is on the media disk, never a glob of it."""
    if not mm.on_media(store):
        return _glob_readings(store)
    if not mm.complete(READINGS_MANIFEST):
        return _build_readings(store)
    return set(mm.memo(READINGS_MANIFEST, "number", "at"))


def _build_ledger(store):
    """Copy STORE's ledger once into LEDGER_MANIFEST (a cold memo)."""
    found = [{"sha": sha, "number": e.get("number"), "reports": e.get("reports") or []}
             for sha, e in sorted(load_ledger(store).items())]
    mm.write(LEDGER_MANIFEST, found)
    mm.complete_path(LEDGER_MANIFEST).write_text(json.dumps({"at": time.time()}))
    return found


def ledger_numbers(store=STORE):
    """[{"number", "reports"}] of the ledger's entries, last row per file: from
    LEDGER_MANIFEST (which read_one appends to) on the media disk, not the ledger."""
    if not mm.on_media(store):
        return [{"number": e.get("number"), "reports": e.get("reports") or []} for e in load_ledger(store).values()]
    rows = mm.rows(LEDGER_MANIFEST) if mm.complete(LEDGER_MANIFEST) else _build_ledger(store)
    return list({r["sha"]: r for r in rows}.values())


def filed_numbers(root=ROOT):
    return {int(p.stem.split("-")[1]) for p in (root / "puzzles" / lp.SERIES).glob("*/listener-*.json")}


def to_save(idx, store=STORE, root=ROOT):
    """The printed puzzles neither filed nor read into a reading, earliest first
    (a page read with none kept is wanted still; tools/gale_fetch.py passes
    over a document it already got)."""
    held = filed_numbers(root) | reading_numbers(store)
    return [r for r in idx if printed(r) and r["number"] not in held]


def saved_numbers(store=STORE):
    """{number} of the puzzles a saved page was read as, a reading kept or not."""
    return {e["number"] for e in ledger_numbers(store) if e.get("number") is not None} | reading_numbers(store)


def solutions(store=STORE):
    """{number} of the puzzles a saved page reports on."""
    return {n for e in ledger_numbers(store) for n in e["reports"]}


def unsolved(idx, store=STORE):
    """The printed puzzles saved whose report page is not."""
    return [r for r in idx if printed(r) and r["number"] in saved_numbers(store) - solutions(store)]


def report_lookups(idx, store=STORE, root=ROOT):
    """The rows whose report page is wanted, earliest first: every saved
    puzzle and every one still to save whose report page is not saved."""
    saved, solved = saved_numbers(store), solutions(store)  # once: per row it re-read the ledger ~3,000 times
    want = {r["number"] for r in to_save(idx, store, root)} | saved
    return [r for r in idx if printed(r) and r["number"] in want - solved]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rd = sub.add_parser("read", help="read every saved page (or a local folder's) not yet read")
    rd.add_argument("--inbox", type=Path, default=SAVED)
    rd.add_argument("--store", type=Path, default=STORE)
    mt = sub.add_parser("match", help="which puzzle each file is")
    mt.add_argument("files", nargs="+", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "match":
        idx = index(times=True)
        for f in a.files:
            m = match(f, idx)
            print(f"{f.name}: " + (f"No {m['number']}, {m['date']} ({m['how']})" if m["number"] is not None
                                   else f"unmatched ({m['why']})") + f", {len(m['pages'])} page image(s)")
        return 0
    run(a.inbox, a.store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
