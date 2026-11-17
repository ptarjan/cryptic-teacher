#!/usr/bin/env python3
"""The Sunday Times Mephisto (2003-) read from the Sunday Times pages tools/gale_fetch.py downloads from
Gale's Sunday Times Historical Archive, one GALE_<docId>.pdf each in <Gale crosswords>/Mephisto/Fetched
(the solution pages in Mephisto/Solutions; both folders keep growing while the fetch walks back, so the
plan lists them afresh each time).

A page is a whole newspaper page: the Mephisto's 12x12 barred grid (bars drawn thick, the cell rules thin and
often broken, so tools/listener_grid's lattice finder, which wants unbroken rules, does not find it) stands
over the two clue columns (Across, Down) under a "Mephisto" title. The grid is found here by its long horizontal
rules (find_lattice), its bars read as tools/ios_barred reads a Beelzebub's (mirror pairs, 180-degree symmetric),
the clue columns cut under the grid and read as the Times' lists are (gale_listener.times_read). The page's
citation ('"Mephisto 2250." Sunday Times, 5 Oct. 2003, p. 382') gives the date and mostly the number; a bare
"Mephisto." has it from the page's text, or from the "Solution to Mephisto 2248" the page prints (two
puzzles back), always checked against the weekly count from No 2250 (2003-10-05). Only a puzzle with every
clue filed is written (fa.complete), unsolved; puzzles/mephisto's held numbers are never written over.

    python3 tools/gale_mephisto_read.py read NAME     # read one saved page
    python3 tools/gale_mephisto_read.py plan          # the pages not yet read

The standing pass plans each unread page as a unit (tools/edition_queue.py, paper "listener", rel
"mephisto:NAME"), ahead of the Listener's own pages.
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path
import downloads
import gale_inbox as gi
import file_archive_org_puzzles as fa

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
SERIES = "mephisto"
TOOL = "tools/gale_mephisto_read.py"
SAVED = downloads.GALE_CROSSWORDS / "Mephisto" / "Fetched"
SOLUTIONS = downloads.GALE_CROSSWORDS / "Mephisto" / "Solutions"
STORE = Path(os.path.expanduser("~/.cache/gale_mephisto"))
LEDGER = "ledger.jsonl"
#: Bumped when the reading changes, so every page is read again.
VERSION = 5
#: Bumped when only the grid finding changes: the pages refused "grid unread" are read again (not every page).
GRID_FIX = 2
#: Bumped when only the numbering changes: the pages refused for want of a number are read again (not every page).
NUMBER_FIX = 2
#: The Gale list of titles, beside the saved pages (downloads.GALE_CROSSWORDS, which the live units set through
#: CT_DOWNLOADS): gale_inbox.MEPHISTO_DOCS follows local.json's media_root, unset on the queue's machine, so the live
#: units read an empty list (0 titles, no anchors) and refused every page before 1995 whatever the offset runs said.
DOCS_PATH = downloads.GALE_CROSSWORDS / "Mephisto" / "docs.json"
#: Bumped when only the lists' foot changes: the pages read with their first Down clues blank are read again.
TAIL_FIX = 1
#: Bumped when only the lists' bare numbers and missing headings change (bare_mended): the pages refused "no clue
#: list on the page" are read again (not every page).
BARE_FIX = 1
PREFIX ="mephisto:"
CITED = re.compile(r'^\W*"([^"]*)"\s*(?:Sunday\s+)?Times\b\W*([0-3]?\d)\s+' + gi.MON + r"\s*(\d{4})", re.IGNORECASE)
TITLE_NUMBER = re.compile(r"mephisto\W{0,3}(\d{4})\b", re.IGNORECASE)
SOLUTION_TO = re.compile(r"solution\s+to\s+mephisto\W{0,3}(\d{4})\b", re.IGNORECASE)
TITLE_WORD = re.compile(r"^\W*mephisto\W*$", re.IGNORECASE)
STOP_WORD = re.compile(r"^\W*(?:solutions?|winners|prizes?|answers)\W*$", re.IGNORECASE)
#: The line heading last week's answers, as the OCR misreads it ("Soklstion to Mephisto 2283:").
STOP_LINE = re.compile(r"^\W*(?:so\w{3,8}[nae]|answers)\s*(?:t[oa]\s+m[a-z]{4,9}\b|\w{1,2}\s+\w{2,10}\s+[12]\d{3}\b)",
                       re.IGNORECASE)
#: The "Bookwise" quiz heading (1995-99) stands under the lists where no solution column's heading reaches the cut.
STOP_BOOKWISE = re.compile(r"^\W*b[o0]{2}kw\w*\W*$", re.IGNORECASE)
#: Bumped when only the lists' cut changes (LISTS_FIX 1: the cut ran on past last week's solution or the lists' foot
#: into the page's articles): pages refused "no reading parses" are read again once.
LISTS_FIX = 1
#: A word box taller than this many lines is a misread, not a clue line; a gap of GAP_LINES lines under the lists
#: (3 before LISTS_FIX 1) ends them.
TALL_BOX, GAP_LINES = 1.8, 2.15
DOC_ID = re.compile(r"[A-Z]{2,6}\d{9,10}")
#: The first Mephisto the Sunday Times numbered No 2250 (2003-10-05); one a week, a number a page's text gives is
#: taken when within this many of the count (a Christmas week with no puzzle moves it by one).
FIRST = (2250, datetime.date(2003, 10, 5))
NEAR = 1
#: Dates whose weekly count is confirmed by the numbers pages gave (offsets 0, with a stray two-off misread).
COUNTED = (datetime.date(1995, 1, 8), datetime.date(2004, 12, 31))
#: Bumped when COUNTED grew: pages 1995-2000 refused for want of a number (every one of the 190 that gave a number,
#: citation or text, sits on the weekly count, offset -189 from 1995-01-08) are read again once.
COUNT_FIX = 1
#: The Mephisto is a 12x12 barred grid.
CELLS = 12
#: The grid's rules run this share of the page's width at least.
RULE_SHARE = 0.12
#: The grid's width over 12 cells' pitch agrees within this.
SQUARE = 0.08
#: A cell's width across may differ from its height by this much (a scan stretched one way), in this many steps.
SQUARE_SKEW = 0.12
SKEW_STEPS = 24


def estimate(day):
    """The number the weekly count gives a Mephisto of `day`."""
    return FIRST[0] + round((day - FIRST[1]).days / 7)


def cite_of(cite):
    """(number or None, date) the page's citation gives, or None."""
    m = CITED.search(re.sub(r"\s+", " ", cite or ""))
    if not m:
        return None
    n = TITLE_NUMBER.search(m.group(1))
    day = datetime.date(int(m.group(4)), gi.MONTHS[m.group(3)[:3].lower()], int(m.group(2)))
    return (int(n.group(1)) if n else None), day


def checked(n, day):
    """`n` when it is a Mephisto number near the weekly count for `day`, else None."""
    return n if n and abs(n - estimate(day)) <= NEAR else None


#: Gale's own title of each Mephisto page ("Mephisto 1435", "Mephisto Crossword No. 152"), by document id, with the
#: date: Mephisto/docs.json. The numbers drift from the weekly count by a skipped week now and then (+79 in 1961-65,
#: +2 in 1985-88, +1 in 1989-94, 0 in 1995-2005, -1 in 2006), so a page's number is read off its titled neighbours.
DOCS_NUMBER = re.compile(r"(?:\bNo\.?\s*|\bMephisto\s+)(\d{1,4})\b", re.IGNORECASE)
#: Before this the Mephisto came out every other Sunday (numbers by issue, not by week).
BIWEEKLY_END = datetime.date(1961, 6, 1)
WEEK_ZERO = datetime.date(1957, 1, 6)
#: Gale's titles run weekly (one offset from the weekly count) from here.
WEEKLY_FROM = datetime.date(1961, 2, 26)
#: A page before 1995 with one printed number is confirmed by a page this many days off with the same offset.
NEAR_DAYS = 56
#: From here the page's own number, checked against the weekly count, is all there is without a titled neighbour.
COUNT_FROM = datetime.date(1995, 1, 1)
_DOCS = {}


def docs_index(path=None):
    """({doc id: date}, [(date, number)] of the titled pages, by date) of Mephisto/docs.json."""
    path = str(path or DOCS_PATH)
    if path not in _DOCS:
        dates, titled = {}, []
        try:
            entries = json.loads(Path(path).read_text()).get("entries", [])
        except (OSError, ValueError):
            entries = []
        for e in entries:
            if e.get("kind") != "mephisto" or not e.get("doc") or not e.get("date"):
                continue
            day = datetime.date.fromisoformat(e["date"])
            dates[e["doc"]] = day
            m = DOCS_NUMBER.search(e.get("title") or "")
            if m:
                titled.append((day, int(m.group(1))))
        _DOCS[path] = (dates, sane_titles(sorted(titled)))
    return _DOCS[path]


def week(day):
    """Whole weeks since the first Mephisto Sunday of 1957."""
    return (day - WEEK_ZERO).days // 7


def sane_titles(titled):
    """`titled` [(date, number)] without the titles Gale's OCR misread (874 for 87, 1601 for 1501, 2330 for 2230 ...):
    the offset (number less the week count) only ever falls, a skipped week at a time, so a title whose offset
    rises by more than one from the last kept title's, or falls under the next title's by more than one, is dropped."""
    out = []
    for day, n in titled:
        if not out or n - week(day) <= out[-1][1] - week(out[-1][0]) + NEAR:
            out.append((day, n))
    return [t for i, t in enumerate(out) if i + 1 == len(out)
            or t[1] - week(t[0]) >= out[i + 1][1] - week(out[i + 1][0]) - NEAR]


def docs_number(day, own=None, titled=None):
    """The number of the Mephisto of `day` from its titled neighbours: its own title when it runs on from them (above
    the one before and below the one after, and in the weekly years at the offset of one of them), else the
    weekly count at the offset the neighbours before and after share (a gap of skipped weeks between them gives
    none). None when they say nothing sure."""
    if titled is None:
        titled = docs_index()[1]
    before = [t for t in titled if t[0] < day]
    after = [t for t in titled if t[0] > day]
    prev, nxt = (before[-1] if before else None), (after[0] if after else None)
    offs = [t[1] - week(t[0]) for t in (prev, nxt) if t]
    if own is not None:
        if prev and own <= prev[1] or nxt and own >= nxt[1]:
            return None
        if day < BIWEEKLY_END or own - week(day) in offs or not offs:
            return own
        return None
    if prev and nxt and prev[0] >= WEEKLY_FROM and offs[0] == offs[1]:
        return week(day) + offs[0]
    if prev and nxt and nxt[0] < WEEKLY_FROM and (day - prev[0]).days % 14 == 0 \
            and nxt[1] - prev[1] == (nxt[0] - prev[0]).days // 14 and (nxt[0] - prev[0]).days % 14 == 0:
        # An issue Gale titled wrongly or not at all between two titled ones a fortnight apart each way.
        return prev[1] + (day - prev[0]).days // 14
    return None


def offset_bounds(day, titled=None):
    """(low, high) the offset (number less the weekly count) of a Mephisto of `day` can have: the titled neighbours'
    (it only falls, a skipped week at a time, a one-off glitch aside), or None short of one on either side."""
    if titled is None:
        titled = docs_index()[1]
    prev = [t for t in titled if t[0] < day][-1:]
    nxt = [t for t in titled if t[0] > day][:1]
    if not prev or not nxt:
        return None
    hi, lo = prev[0][1] - week(prev[0][0]), nxt[0][1] - week(nxt[0][0])
    return lo - NEAR, hi + NEAR


#: Bumped when only the offset runs change: pages refused for want of a number inside a run are read again.
RUN_FIX = 1
#: (first date, last date, offset) of the stretches of Sundays 1965-94 whose Mephisto number less the week count is
#: one value throughout. Each run is the first and last of the pages whose own text prints two numbers a week or two
#: apart (own and last week's, or the answers' two back; the higher one is the page's own) and agree on the offset,
#: with the offset falling only (a skipped week at a time): 1965-07, 1985-12 and 1989-01 are also titles of Gale's own
#: list, which agree. A single-date run is one page's own pair. Between runs (the weeks the offset fell in) no page
#: has a number but its own pair. Built from the printed text of the 1,429 refused pages 1965-94 (census r96).
OFFSET_RUNS = (
    ("1965-07-04", "1965-09-26", -110), ("1966-10-09", "1966-12-18", -111), ("1967-01-29", "1969-03-30", -112),
    ("1969-06-08", "1970-12-13", -115), ("1971-01-10", "1971-11-14", -116), ("1972-01-09", "1973-11-25", -117),
    ("1974-02-17", "1974-02-17", -120), ("1974-03-31", "1976-01-25", -121), ("1978-02-26", "1978-02-26", -128),
    ("1980-03-23", "1980-03-23", -180), ("1981-05-17", "1981-06-28", -181), ("1981-08-16", "1982-10-17", -182),
    ("1983-02-06", "1983-10-02", -183), ("1983-12-18", "1983-12-18", -185), ("1984-01-15", "1988-12-18", -187),
    ("1989-01-01", "1994-12-11", -188),
)
#: The offsets a page's printed numbers may differ from its own by: last week's, and the answers' two back.
RUN_NEAR = (0, -1, -2)
RUN_RANGE = (-200, -100)


#: Bumped when only the bridged gaps change: pages refused for want of a number inside RUN_BRIDGES are read again.
BRIDGE_FIX = 1
#: (first date, last date, offset) of the gaps between two anchors (a titled page or an OFFSET_RUNS end) at the SAME
#: offset: the offset only ever falls, a skipped week at a time, so none fell between them and every Sunday in the gap
#: is the weekly count at that offset. 1961-02-26 is Gale's title Mephisto 106 (offset -110, the first of the weekly
#: titles); 1965-07-04 starts the -110 run. A gap between anchors at different offsets is NOT bridged (the fall's week
#: is unknown): 1965-09-26..1966-10-09 (-110/-111), 1969-03-30..06-08 (-112/-115), 1976-01-25..1978-02-26
#: (-121/-128), 1978-02-26..1980-03-23 (-128/-180), 1980-03-23..1981-05-17 (-180/-181), 1981-06-28..08-16,
#: 1982-10-17..1983-02-06, 1983-10-02..12-18 (-183/-185/-187) stay refused, as do the weeks before 1961-02-26 (Mephisto
#: ran fortnightly, the numbers count issues) and 1974-02-17..03-31 (-120/-121 around one page). Each bridged page still
#: needs its printed numbers (any) to sit at the offset or one or two below (run_number).
RUN_BRIDGES = (("1961-02-27", "1965-07-03", -110),)


def run_offset(day):
    """The offset (number less the week count) of OFFSET_RUNS or RUN_BRIDGES holding `day`, else None."""
    iso = day.isoformat()
    return next((o for a, b, o in (*OFFSET_RUNS, *RUN_BRIDGES) if a <= iso <= b), None)


def bridged(day):
    """Whether `day` lies in a RUN_BRIDGES gap (not in an OFFSET_RUNS run of its own)."""
    iso = day.isoformat()
    return any(a <= iso <= b for a, b, _ in RUN_BRIDGES)


def run_number(day, text):
    """The number a Mephisto of `day` has inside an offset run, when the page's printed numbers (any inside
    RUN_RANGE) all sit at the run's offset or the one or two below it, and a single-date run's page prints its own."""
    o = run_offset(day)
    if o is None:
        return None
    seen = {n - week(day) for n in printed_numbers(text)}
    seen = {s for s in seen if RUN_RANGE[0] <= s <= RUN_RANGE[1]}
    if any(s - o not in RUN_NEAR for s in seen):
        return None
    if any(a == b == day.isoformat() for a, b, _ in OFFSET_RUNS) and o not in seen:
        return None
    return week(day) + o


_MEPH = r"m\w{2,5}s[tfl][oe]"
#: What a page before 1995 prints of its own number, as the OCR misreads the title ("Mophisto Crosaword No 826",
#: "SOLUTION TO MEPHISTO 1121" over last week's answers, "solutions to Mophiste 1122" over this week's entry form).
PRINTED_TITLE = re.compile(rf"\b{_MEPH}\W{{1,4}}cr\w{{3,8}}\W{{1,4}}n[o0]\W{{0,3}}(\d{{3,4}})\b", re.IGNORECASE)
PRINTED_SOLUTION = re.compile(rf"\b(so\w{{3,8}})\s+to\s+{_MEPH}\W{{0,3}}(\d{{3,4}})\b", re.IGNORECASE)
PRINTED_PLAIN = re.compile(rf"\b{_MEPH}\W{{0,3}}(\d{{3,4}})\b", re.IGNORECASE)


def printed_numbers(text):
    """[Mephisto numbers the page's text gives for its own puzzle]: the title's, the plain "Mephisto N", one more than
    last week's "Solution to Mephisto N" and the same as the entry form's "Solutions to Mephisto N"."""
    text = re.sub(r"\s+", " ", text or "")
    out, taken = [], []
    for m in PRINTED_SOLUTION.finditer(text):
        taken.append(m.span())
        n = int(m.group(2))
        out.append(n if m.group(1).lower().endswith("s") else n + 1)
    for rx in (PRINTED_TITLE, PRINTED_PLAIN):
        for m in rx.finditer(text):
            if not any(a <= m.start() < b for a, b in taken):
                taken.append(m.span())
                out.append(int(m.group(1)))
    return out


def printed_offset(day, text, titled=None, near=()):
    """(offset, sure) the page's printed numbers give for a Mephisto of `day` before 1995, or None. Only an offset
    inside the titled neighbours' bounds counts; it is sure when two printed numbers agree on it or a page
    within weeks of this one (`near`: their offsets) has it too."""
    bounds = offset_bounds(day, titled)
    if not bounds:
        return None
    seen = {}
    for n in printed_numbers(text):
        o = n - week(day)
        if bounds[0] <= o <= bounds[1]:
            seen[o] = seen.get(o, 0) + 1
    twice = [o for o, k in seen.items() if k >= 2]
    if len(twice) == 1:
        return twice[0], True
    if len(seen) == 1:
        (o,) = seen
        return o, o in near
    return None


def near_offsets(day, rows, own=None):
    """The offsets the ledger rows `rows` (a page's own excluded) of the Mephisto dates within NEAR_DAYS of `day` hold:
    a numbered page's (not from the weekly count), or an unconfirmed page's `seen`."""
    out = set()
    for r in rows:
        if r.get("file") == own or not r.get("date"):
            continue
        d = datetime.date.fromisoformat(r["date"])
        if d == day or abs((d - day).days) > NEAR_DAYS:
            continue
        if r.get("number") and r.get("numberFrom") in ("docs title", "docs neighbours", "page printed", "citation"):
            out.add(r["number"] - week(d))
        elif r.get("seen") is not None:
            out.add(r["seen"])
    return out


def number_of(cited, text, doc=None, near=()):
    """(number, where from) of a page: its titled neighbours' (docs_number, `doc` = (date, title number or None)
    the Gale page list gives), else the citation's, else the page's text ("Mephisto 2250"), else two more
    than the "Solution to Mephisto N" it prints; each checked against the weekly count (from 1995 on: before, the
    count runs two or three off and no number is taken but a titled one)."""
    day = cited[1]
    if doc:
        n = docs_number(doc[0], doc[1])
        if n:
            return n, "docs title" if n == doc[1] else "docs neighbours"
    if day < COUNT_FROM:
        # No titled neighbours agree: the page's own printed number, inside the neighbours' offsets and sure.
        got = printed_offset(day, text, None, near)
        if got and got[1]:
            return week(day) + got[0], "page printed"
        n = run_number(day, text)
        return (n, "offset run") if n else (None, None)
    if checked(cited[0], day):
        return cited[0], "citation"
    for m in TITLE_NUMBER.finditer(text or ""):
        if not SOLUTION_TO.match(text[max(0, m.start() - 12):m.end()].strip()[-40:]) and checked(int(m.group(1)), day) \
                and "solution to" not in text[max(0, m.start() - 14):m.start()].lower():
            return int(m.group(1)), "page text"
    for m in SOLUTION_TO.finditer(text or ""):
        for step in (2, 1):
            if checked(int(m.group(1)) + step, day) and abs(int(m.group(1)) + step - estimate(day)) <= 1:
                return int(m.group(1)) + step, "solution printed"
    # No number printed: the weekly count itself, over the years the ledger's own numbers agree with it to the
    # week (every read page of 2001-2004 that gave a number, but a few misreads two off, has the count's).
    if COUNTED[0] <= day <= COUNTED[1]:
        return estimate(day), "weekly count"
    return None, None


def page_files(saved=SAVED):
    d = Path(saved)
    return sorted(p for p in d.iterdir() if p.suffix.lower() == ".pdf" and p.is_file()
                  and not p.name.startswith(".")) if d.is_dir() else []


def load_ledger(store=STORE):
    out = {}
    path = Path(store) / LEDGER
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            out[row["file"]] = row
    return out


def append_row(row, store=STORE):
    Path(store).mkdir(parents=True, exist_ok=True)
    with open(Path(store) / LEDGER, "a") as f:
        f.write(json.dumps(row) + "\n")


#: A page whose read crashed this many times is left as refused (a page that always raises).
CRASH_LIMIT = 3


#: What a page with no number the Gale list, its neighbours or its text give is refused with (from the docs-number
#: reading on) and what the 1,364 pages refused before it were (read again once, with the docs list).
UNNUMBERED = "no Mephisto number: no titled neighbours of the Gale list agree on it, none printed on the page"
#: A page whose one printed number sits inside its neighbours' offsets but no second reading agrees (yet).
UNCONFIRMED = "Mephisto number unconfirmed: the one number printed on the page agrees with no second reading"
STALE_UNNUMBERED = "no Mephisto number in the citation or the page text"


def now_titled(row):
    """Whether the Gale list's titles (docs_number) give the page of ledger row `row` a number now."""
    m = DOC_ID.search(str(row.get("file") or "").upper())
    dates, titled = docs_index()
    when = dates.get(m.group(0)) if m else None
    if not when or when >= COUNT_FROM:
        return False
    return docs_number(when, next((n for d, n in titled if d == when), None), titled) is not None


def read_done(row, done=None):
    """Whether a ledger row is a verdict of this VERSION: a crashed attempt is not, so the page stays due. A page
    refused for want of a number before the Gale list's titles set it (STALE_UNNUMBERED) is read again once, and
    again at NUMBER_FIX (the titles grew, a misread title no longer breaks its neighbours, the page's printed
    number counts); a page whose one printed number (UNCONFIRMED) a page near it in `done` (the ledger) now
    holds too is read again."""
    if row and row.get("refused") == STALE_UNNUMBERED:
        return False
    if row and row.get("refused") == UNNUMBERED and row.get("numberFix", 0) < NUMBER_FIX:
        return False
    if row and str(row.get("refused") or "").startswith("no Mephisto number"):
        if now_titled(row):
            # Refused before the Gale list (docs.json, which grows) titled the page or its neighbours: it does now.
            return False
        if row.get("runFix", 0) < RUN_FIX and row.get("date") and run_offset(datetime.date.fromisoformat(row["date"])) is not None:
            # Refused before the offset runs (OFFSET_RUNS) numbered the pages inside them: read again once.
            return False
        if row.get("countFix", 0) < COUNT_FIX and COUNTED[0].isoformat() <= (row.get("date") or "") <= COUNTED[1].isoformat():
            # Refused before the weekly count was taken for 1995-2000 as it is for 2001-04 (COUNTED).
            return False
        if row.get("bridgeFix", 0) < BRIDGE_FIX and row.get("date") and bridged(datetime.date.fromisoformat(row["date"])):
            # Refused before the gap between two anchors at one offset (RUN_BRIDGES) was numbered: read again once.
            return False
    if row and row.get("refused") == UNCONFIRMED and done is not None and row.get("seen") is not None \
            and row.get("date") and row["seen"] in near_offsets(datetime.date.fromisoformat(row["date"]),
                                                                 done.values(), row.get("file")):
        return False
    if row and row.get("numberFrom") in ("solution printed", "page text") and (row.get("date") or "9") < COUNT_FROM.isoformat():
        # A number read off the page before 1995 ran one or two off Gale's own titles (1988-02-07 is 1435, read 1434).
        return False
    if row and str(row.get("refused") or "").startswith("grid unread") and row.get("gridFix", 0) < GRID_FIX:
        # Refused before the comb search (comb_lattices) found grids printed with dotted thin rules: read again once.
        return False
    if row and str(row.get("refused") or "").startswith("no clue list") and row.get("bareFix", 0) < BARE_FIX:
        # Refused before the lists' bare clue numbers (1995-99 print "5 Cry echoed", no stop) and unread headings
        # were put in the form the Listener's readers open on (bare_mended).
        return False
    if row and row.get("refused") == "no reading parses" and row.get("listsFix", 0) < LISTS_FIX:
        # Refused before the lists' cut stopped at the Solution heading, the Bookwise heading or the gap under the
        # lists (lists_cut): the cut ran on into the page's articles.
        return False
    if row and not row.get("whole") and "1-down" in (row.get("blank") or ()) and row.get("tailFix", 0) < TAIL_FIX:
        # Read before the Down clues at the left column's foot, under no heading the OCR read, were found (headless_tail).
        return False
    if row and not row.get("whole") and row.get("blank") and row.get("columnFix", 0) < COLUMN_FIX \
            and row.get("version") == VERSION and not row.get("refused"):
        # Read with the clue columns cut at numbers inside a clue's lines (column_lefts): the VLM saw a fragment.
        return False
    return bool(row) and row.get("version") == VERSION and not (
        row.get("failed") and row.get("attempts", 1) < CRASH_LIMIT)


def plan(saved=SAVED, store=STORE):
    """One unit per saved page not read at VERSION (or whose last attempt crashed), newest first. The folder is
    listed each call: the fetch is still adding pages."""
    done = load_ledger(store)
    reason = "never read (Gale fetch)"
    todo = [p for p in page_files(saved) if not read_done(done.get(p.name), done)]
    todo.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"rel": PREFIX + p.name, "rank": fa.RANKS[reason], "reason": reason, "needs": []} for p in todo]


# ------------------------------------------------------------ the grid

def long_rules(ink, share=RULE_SHARE):
    """[(y, x0, x1)] of the long horizontal rules of `ink` (a boolean page): each run of rows (a rule's, a
    bar's thickness) holding a horizontal run of `share` of the width at least, its centre row and the run's ends."""
    import numpy as np
    import listener_grid as lg
    h, w = ink.shape
    long = lg.runs_at_least(ink, max(45, int(share * w)), 1)
    rows = np.flatnonzero(long.any(1))
    out, group = [], []
    for y in list(rows) + [None]:
        if group and (y is None or y - group[-1] > 3):
            ends = []
            for r in group:
                at = np.flatnonzero(long[r])
                # the longest unbroken stretch of the row
                cut = np.flatnonzero(np.diff(at) > 1)
                starts = np.r_[at[0], at[cut + 1]]
                stops = np.r_[at[cut], at[-1]]
                k = int(np.argmax(stops - starts))
                ends.append((int(starts[k]), int(stops[k])))
            out.append(((group[0] + group[-1]) / 2, int(np.median([e[0] for e in ends])),
                        int(np.median([e[1] for e in ends]))))
            group = []
        if y is not None:
            group.append(int(y))
    return out


#: A cell side is a bar when its ink is this share of the pitch wide.
BAR_WIDTH = 0.1
#: The lights a Mephisto's grid has (the clue counts read run 32-36).
LIGHTS = (24, 46)
#: Lines of a lattice that must be found of its 13 (the thin rules are printed broken).
MATCHED = 11
#: Lines wanted when too few rules are unbroken for MATCHED, and the share of the width then taken for a rule.
FEW_MATCHED = 8
SHORT_RULE_SHARE = 0.07
#: A cell's pitch is within these many pixels (a page scans at ~97 px a cell; the later pages are smaller).
PITCH = (24, 400)


def lattice_1d(pos, lo=PITCH[0], hi=PITCH[1], need=MATCHED):
    """(positions, count) of 13 evenly spaced lines among `pos` (centres of rules found along one axis): the
    pair of them 12 pitches apart (a pitch in lo..hi) that the most others lie within 15% of a pitch of the
    lattice between; the lattice refitted to the ones matched. None when fewer than `need` are matched."""
    got = lattices_1d(pos, lo, hi, need, limit=1)
    return (got[0], len(pos)) if got else None


def lattices_1d(pos, lo=PITCH[0], hi=PITCH[1], need=MATCHED, limit=6):
    """[positions] of up to `limit` different lattices of 13 evenly spaced lines among `pos`, best first (see
    lattice_1d for one): the same lattice (its first line within a pitch and its pitch within 10%) is kept once."""
    import numpy as np
    pos = sorted(pos)
    found = []
    for i, a in enumerate(pos):
        for b in pos[i + 1:]:
            p = (b - a) / CELLS
            if p < lo:
                continue
            if p > hi:
                break
            hits = []
            for k in range(CELLS + 1):
                at = a + k * p
                near = min(pos, key=lambda v: abs(v - at))
                if abs(near - at) <= 0.15 * p:
                    hits.append((k, near))
            # The widest pitch wins a near tie: a page's text lines are evenly spaced too, but closer than a cell.
            score = len(hits) + min(p, 150) / 40
            if len(hits) >= need:
                found.append((score, hits))
    out = []
    for score, hits in sorted(found, key=lambda f: -f[0]):
        slope, icept = np.polyfit([k for k, _ in hits], [v for _, v in hits], 1)
        if any(abs(icept - o[0]) < abs(o[1]) and abs(slope / o[1] - 1) < 0.1 for o in out):
            continue
        out.append((icept, slope))
        if len(out) >= limit:
            break
    return [[icept + slope * k for k in range(CELLS + 1)] for icept, slope in out]


def bar_fit(band, pitch, rules):
    """The 13 x lines of the grid in `band` (the ink between its first and last rule), or None: the thick vertical
    bars (columns with ink over a fifth of the band's height, 8-40 px wide: not the frame's 5 px or a thin rule)
    give the lattice's phase at `pitch` (circular mean of their centres), and the horizontal rules' right end
    which of its pitch-steps is the grid's own (the thick frame stands a little outside the lattice)."""
    import math
    import numpy as np
    prof = band.sum(0)
    on = np.flatnonzero(prof >= 0.2 * band.shape[0])
    centres, start, prev = [], None, 0
    for x in list(on) + [None]:
        if start is not None and (x is None or x - prev > 2):
            if 8 <= prev - start + 1 <= 40:
                centres.append((start + prev) / 2)
            start = None
        if x is not None:
            if start is None:
                start = x
            prev = x
    if len(centres) < 4 or not rules:
        return None
    # A page scanned a little wider than tall has a cell wider than it is tall (78 px by 75): the pitch across is
    # the one (within SQUARE_SKEW of the pitch down) the bars' centres lie most evenly on.
    best = None
    for k in range(-SKEW_STEPS, SKEW_STEPS + 1):
        p = pitch * (1 + SQUARE_SKEW * k / SKEW_STEPS)
        ang = [2 * math.pi * c / p for c in centres]
        r = math.hypot(sum(math.sin(a) for a in ang), sum(math.cos(a) for a in ang)) - 0.02 * abs(k)
        if best is None or r > best[0]:
            best = (r, p)
    pitch = best[1]
    ang = [2 * math.pi * c / pitch for c in centres]
    phase = math.atan2(sum(math.sin(a) for a in ang), sum(math.cos(a) for a in ang)) * pitch / (2 * math.pi)
    # The grid's left edge: the left end three or more rules share (a rule's right end is often lost to a break).
    starts = sorted(r[1] for r in rules)
    left = next((s for s in starts if sum(1 for t in starts if abs(t - s) <= 8) >= 3), starts[0])
    m = round((left - phase) / pitch)
    x0 = phase + m * pitch
    return [x0 + pitch * i for i in range(CELLS + 1)]


def find_lattice(ink, share=RULE_SHARE):
    """(ys, xs) of the 13 rules each way of the 12x12 grid on `ink`, or None: the horizontal rules lie on 13
    evenly spaced lines (lattice_1d); the vertical ones, long runs of ink between the first and the last, on
    13 more at the same pitch, else (the thin verticals too broken to find) the horizontal rules' own ends."""
    return next(iter(find_lattices(ink, share, limit=1)), None)


def find_lattices(ink, share=RULE_SHARE, limit=6):
    """[(ys, xs)] of the candidate 12x12 lattices on `ink`, the best set of evenly spaced rules first (a page's text
    lines and a diagram's rules make some too: the grid read tells them apart)."""
    out = []
    # A page whose thin rules are mostly broken shows too few of the 13 (11 wanted): fewer are taken (the bars'
    # symmetry and a Mephisto's lights still decide), and shorter rules counted, before the page is given up.
    for use, need in ((share, MATCHED), (share, FEW_MATCHED), (SHORT_RULE_SHARE, FEW_MATCHED)):
        rules = long_rules(ink, use)
        for ys in lattices_1d([r[0] for r in rules], limit=limit, need=need):
            xs = x_lines(ink, ys, rules)
            if xs:
                out.append((ys, xs))
        if out:
            break
    return out


def x_lines(ink, ys, rules):
    """The 13 x lines of the grid whose y lines are `ys`, or None (bar_fit, else the verticals' own, else the ink's)."""
    import numpy as np
    import listener_grid as lg
    pitch = (ys[-1] - ys[0]) / CELLS
    band = ink[max(0, int(ys[0] - pitch / 4)):int(ys[-1] + pitch / 4)]
    fitted = bar_fit(band, pitch, [r for r in rules if ys[0] - pitch / 2 <= r[0] <= ys[-1] + pitch / 2])
    if fitted:
        return fitted
    # The thin verticals are broken, so the lattice is fitted to the columns' ink: the x0 and pitch (2% either way)
    # whose 13 lines lie on the most ink (each column's ink spread 3 px either way, the grid's height over it).
    down = lg.runs_at_least(band, max(45, int(0.6 * pitch)), 0)
    cols = np.flatnonzero(down.sum(0) >= 0.4 * band.shape[0])
    centres, start, prev = [], None, 0
    for x in list(cols) + [None]:
        if start is not None and (x is None or x - prev > 3):
            centres.append((start + prev) / 2)
            start = None
        if x is not None:
            if start is None:
                start = x
            prev = x
    across = lattice_1d(centres, 0.92 * pitch, 1.08 * pitch, need=9)
    if across:
        return across[0]
    prof = np.minimum(band.sum(0).astype(float), 0.4 * band.shape[0])
    spread = np.maximum.reduce([np.roll(prof, s) for s in range(-12, 13)])
    best = None
    for scale in (0.98, 0.99, 1.0, 1.01, 1.02):
        p = pitch * scale
        offs = np.round(np.arange(CELLS + 1) * p).astype(int)
        width = len(prof) - int(offs[-1])
        if width <= 0:
            continue
        starts = np.arange(width)
        score = spread[starts[:, None] + offs[None, :]].sum(1)
        i = int(np.argmax(score))
        if best is None or score[i] > best[0]:
            best = (float(score[i]), i, p)
    if best is None or best[0] < 0.12 * (CELLS + 1) * band.shape[0]:
        return None
    return [best[1] + best[2] * i for i in range(CELLS + 1)]


#: Clues with a count the lists must give for the clue-fitted bars to stand, the lights the lists may leave
#: unlisted (a clue the OCR lost), and the pairs thick enough on one side to be tried as a bar.
FIT_CLUES = 20
FIT_UNLISTED = 3
FIT_TRY = 0.8
FIT_ROUNDS = 60


#: [clues missed, lights unlisted, clues counted] of the last mirror_fit's best bars (for a reader's report).
LAST_FIT = []


def wanted_of(laid):
    """[(numbers, direction, length)] of the clues `laid` ({"12-across": (text, enum, group)}) reads whose count
    gives the light's length: the clue list's own account of the grid, which fit_rows scores a bar set against."""
    out = []
    for lid, (_, enum, group) in laid.items():
        number, _, direction = lid.partition("-")
        counts = [int(x) for x in re.findall(r"\d+", enum or "")]
        if group or not number.isdigit() or not counts:
            continue
        out.append((frozenset({int(number)}), direction, sum(counts)))
    return out


def fits(rows, wanted):
    """(clues whose light is not on the grid at their count, lights no clue is listed for) of `rows`."""
    import reconstruct_grid as rg
    lights = rg.light_cells(rows)
    missed = sum(1 for numbers, d, length in wanted
                 if not any(dd == d and n in numbers and len(c) == length for (n, dd), c in lights.items()))
    unlisted = sum(1 for (n, d) in lights if not any(dd == d and n in nn for nn, dd, _ in wanted))
    return missed, unlisted


def mirror_fit(found, wanted):
    """The rows of listener_grid grid `found` whose bars are mirror pairs (180-degree symmetric, as a Mephisto's
    are, ios_barred's way) set so every light lies on a listed clue's number, direction and count, or None: the
    pairs read thick on one side at least are flipped one at a time from the pairs thick on both (and from those
    thick on average) while the lights agree better with the lists; the lists are the reader of the bars, so the
    bars' own symmetry threshold is not asked. Not taken for under FIT_CLUES counted clues, a clue off the grid, or
    more than FIT_UNLISTED lights no clue is listed for."""
    import ios_barred as ib
    import listener_grid as lg
    import reconstruct_grid as rg
    if len(wanted) < FIT_CLUES:
        return None
    pairs = ib.pair_ratios(found)
    n = len(found["rows"])
    free = [p for p, (_, high) in pairs.items() if high >= FIT_TRY]

    def lay(chosen):
        return ib.rows_of({s for p in chosen for s in (p, ib.mirror_of(p, n))}, n)

    best = None
    for start in ({p for p, (low, _) in pairs.items() if low >= lg.BAR_RATIO},
                  {p for p, (low, high) in pairs.items() if (low + high) / 2 >= lg.BAR_RATIO}):
        bars = set(start)
        score = ib.agreement(lay(bars), wanted)
        for _ in range(FIT_ROUNDS):
            tries = [(ib.agreement(lay(bars ^ {p}), wanted), -abs(sum(pairs[p]) / 2 - lg.BAR_RATIO), p) for p in free]
            top = max(tries, default=None)
            if top is None or top[0] <= score + 1e-9:
                break
            score = top[0]
            bars ^= {top[2]}
        if best is None or score > best[0]:
            best = (score, bars)
    rows = lay(best[1])
    missed, unlisted = fits(rows, wanted)
    LAST_FIT[:] = [missed, unlisted, len(wanted)]
    lights = len(rg.light_cells(rows))
    if missed or unlisted > FIT_UNLISTED or not LIGHTS[0] <= lights <= LIGHTS[1]:
        return None
    return rows



def window_shifts(ink, ys, xs, reach=14, top=6):
    """[dx] (cells, nearest zero first among equals) of the shifts of the lattice (ys, xs) along the page whose 13
    rule rows hold the most ink: a lattice found from a rule broken in the middle takes its left end from the
    break, half a grid off; the grid itself is the window the rules fill."""
    import numpy as np
    px = (xs[-1] - xs[0]) / CELLS
    rule = np.zeros(ink.shape[1], dtype=float)
    for y in ys:
        y = int(y)
        rule += ink[max(0, y - 2):y + 3].any(0)
    cum = np.r_[0.0, np.cumsum(rule)]
    scored = []
    for dx in range(-reach, reach + 1):
        a, b = int(xs[0] + dx * px), int(xs[-1] + dx * px)
        if dx and 0 <= a and b < ink.shape[1]:
            scored.append(((cum[b] - cum[a]) / (13 * (b - a)), dx))
    return [dx for _, dx in sorted(scored, key=lambda s: (-s[0], abs(s[1])))[:top]]


#: The comb search (comb_lattices) pools the page so a cell is about this many pooled pixels, tries pitches (in page
#: pixels) in COMB_PITCH, and keeps this many different peaks.
COMB_POOL = 1300
COMB_PITCH = (60, 150)
COMB_KEEP = 4
_COMB = {}


def comb_lattices(ink, keep=COMB_KEEP):
    """[(ys, xs)] of up to `keep` lattices of a 12x12 grid whose rules are too broken for long_rules (the later
    pages print the thin rules dotted): the window (pitch, left, top) whose 13 rule rows and 13 rule columns hold
    more ink than the rows and columns half a cell between them, on the page pooled to ~COMB_POOL px wide. The
    lines are then set to the ink peaks beside them at the page's full size. Memoised on the page."""
    import numpy as np
    tag = (ink.shape, hash(ink[::53, ::53].tobytes()), keep)
    if tag in _COMB:
        return _COMB[tag]
    h, w = ink.shape
    f = max(1, w // COMB_POOL)
    ph, pw = h // f, w // f
    pooled = ink[:ph * f, :pw * f].reshape(ph, f, pw, f).mean((1, 3)).astype(np.float32)
    cx = np.zeros((ph, pw + 1), np.float32)
    np.cumsum(pooled, 1, out=cx[:, 1:])
    cy = np.zeros((ph + 1, pw), np.float32)
    np.cumsum(pooled, 0, out=cy[1:])
    found = []
    for p in np.arange(COMB_PITCH[0] / f, COMB_PITCH[1] / f + 0.01, 1.0):
        side = int(round(12 * p))
        if side + 4 >= min(ph, pw):
            continue
        tops = np.arange(0, ph - side - 2)
        for x0 in range(0, pw - side - 2, 2):
            x1 = x0 + side
            on = np.zeros(len(tops), np.float32)
            off = np.zeros(len(tops), np.float32)
            for k in range(13):
                r = np.clip(np.round(tops + k * p).astype(int), 0, ph - 1)
                on += cx[r, x1] - cx[r, x0]
                if k < 12:
                    r = np.clip(np.round(tops + (k + 0.5) * p).astype(int), 0, ph - 1)
                    off += cx[r, x1] - cx[r, x0]
            bot = tops + side
            von = np.zeros(len(tops), np.float32)
            voff = np.zeros(len(tops), np.float32)
            for k in range(13):
                c = min(pw - 1, int(round(x0 + k * p)))
                von += cy[bot, c] - cy[tops, c]
                if k < 12:
                    c = min(pw - 1, int(round(x0 + (k + 0.5) * p)))
                    voff += cy[bot, c] - cy[tops, c]
            score = (on / 13 - off / 12 + von / 13 - voff / 12) / side
            i = int(np.argmax(score))
            found.append((float(score[i]), float(p), x0, int(tops[i])))
    found.sort(reverse=True)
    out, kept = [], []
    for score, p, x0, y0 in found:
        if any(abs(x0 - a) < 6 * p and abs(y0 - b) < 6 * p for _, _, a, b in kept):
            continue
        kept.append((score, p, x0, y0))
        lat = _comb_refine(ink, p * f, x0 * f, y0 * f)
        if lat:
            out.append(lat)
        if len(kept) >= keep:
            break
    _COMB.clear()
    _COMB[tag] = out
    return out


def _comb_refine(ink, p, x0, y0):
    """(ys, xs) of the comb window set to the ink peaks within a quarter cell of each of its lines, or None."""
    import numpy as np
    h, w = ink.shape
    side = int(round(12 * p))
    if y0 + side >= h or x0 + side >= w:
        return None
    # The window is searched again at the page's full size: pitch within 6%, corner within 0.4 cell.
    m = int(0.4 * p) + 2
    ya, xa = max(0, y0 - m), max(0, x0 - m)
    crop = ink[ya:min(h, y0 + side + 2 * m), xa:min(w, x0 + side + 2 * m)]
    cx = np.zeros((crop.shape[0], crop.shape[1] + 1), np.int32)
    np.cumsum(crop, 1, out=cx[:, 1:])
    cy = np.zeros((crop.shape[0] + 1, crop.shape[1]), np.int32)
    np.cumsum(crop, 0, out=cy[1:])
    ch, cw = crop.shape
    best = None
    step = max(2, int(p / 30))
    for q in np.arange(0.94 * p, 1.0601 * p, max(1.0, p / 50)):
        span = int(round(12 * q))
        tops = np.arange(0, ch - span - 3, step)
        if not len(tops):
            continue
        for l0 in range(0, cw - span - 3, step):
            l1 = l0 + span
            on = np.zeros(len(tops), np.float32)
            off = np.zeros(len(tops), np.float32)
            for k in range(13):
                for d in (-1, 0, 1):
                    r = np.clip(np.round(tops + k * q).astype(int) + d, 0, ch - 1)
                    on += cx[r, l1] - cx[r, l0]
                if k < 12:
                    for d in (-1, 0, 1):
                        r = np.clip(np.round(tops + (k + 0.5) * q).astype(int) + d, 0, ch - 1)
                        off += cx[r, l1] - cx[r, l0]
            von = np.zeros(len(tops), np.float32)
            voff = np.zeros(len(tops), np.float32)
            bot = np.clip(tops + span, 0, ch)
            for k in range(13):
                for d in (-1, 0, 1):
                    c = int(np.clip(round(l0 + k * q) + d, 0, cw - 1))
                    von += cy[bot, c] - cy[tops, c]
                if k < 12:
                    for d in (-1, 0, 1):
                        c = int(np.clip(round(l0 + (k + 0.5) * q) + d, 0, cw - 1))
                        voff += cy[bot, c] - cy[tops, c]
            score = (on / 13 - off / 12 + von / 13 - voff / 12)
            i = int(np.argmax(score))
            if best is None or score[i] > best[0]:
                best = (float(score[i]), q, l0, int(tops[i]))
    if best is None:
        return None
    _, q, l0, t0 = best
    return ([float(ya + t0 + k * q) for k in range(13)], [float(xa + l0 + k * q) for k in range(13)])


def read_barred(gray, lattice=None, wanted=None):
    """(rows, found, None) or (None, None, why) of the barred grid on `gray` (a page, uint8): the lattice found, its
    cell sides measured by listener_grid.read_box, the bars set as ios_barred.read_found sets them."""
    import numpy as np
    import listener_grid as lg
    binary = len(np.unique(gray[::7, ::7])) <= 2
    ink = gray < (128 if binary else max(lg.trove_grid.otsu(gray), 1))
    cands = [lattice] if lattice else find_lattices(ink)
    first = None
    for ys, xs in cands:
        rows, found, why = read_lattice(gray, ink, ys, xs, wanted)
        if rows is not None:
            return rows, found, None
        first = first or (found, why)
    if not lattice:
        # No long rule found sets the grid (a page printing its thin rules dotted, a blocked grid of another puzzle
        # beside it): the window whose rule rows and columns hold the most ink is tried (comb_lattices).
        for ys, xs in comb_lattices(ink):
            rows, found, why = read_lattice(gray, ink, ys, xs, wanted)
            if rows is not None:
                return rows, found, None
            first = first or (found, why)
    if not lattice:
        # The lattice's phase is a guess (the rules' broken left ends, a text line's rules): the same lattice a
        # cell or two along either way is tried, the symmetric bars and a Mephisto's lights saying which is the grid.
        shifts = sorted(((dx, dy) for dx in range(-5, 6) for dy in range(-2, 3) if dx or dy),
                        key=lambda s: (abs(s[0]) + abs(s[1]), abs(s[1])))
        for ys, xs in cands[:2]:
            px, py = (xs[-1] - xs[0]) / CELLS, (ys[-1] - ys[0]) / CELLS
            # first the shifts that put the grid where the rules' ink is (a lattice taken from a broken rule's far end)
            near = [(dx, 0) for dx in window_shifts(ink, ys, xs)]
            for dx, dy in near + [s for s in shifts if s not in near]:
                y2, x2 = [y + dy * py for y in ys], [x + dx * px for x in xs]
                if y2[0] < 0 or x2[0] < 0 or y2[-1] >= ink.shape[0] or x2[-1] >= ink.shape[1]:
                    continue
                rows, found, why = read_lattice(gray, ink, y2, x2, wanted)
                if rows is not None:
                    return rows, found, None
    if not lattice:
        # The rules found sit on a lattice a few per cent off across (a scan stretched one way, the long rules broken
        # short): the lattice is fitted again to the ink's own line profiles, and its half-cell shifts tried.
        for ys, xs in cands[:3]:
            for y2, x2 in refit_lattices(ink, ys, xs):
                rows, found, why = read_lattice(gray, ink, y2, x2, wanted)
                if rows is not None:
                    return rows, found, None
    if first is None:
        return None, None, "no 12x12 lattice of rules on the page"
    return None, first[0], first[1]


def _comb_axis(prof, a0, pitch, span=1.5, pitches=(0.9, 1.1), keep=2):
    """[(score, start, pitch)] of the best combs of 13 lines on `prof` (the ink's share along one axis, smoothed 3 px
    either way): the line start within `span` pitches of `a0` and the pitch within `pitches` of `pitch` whose 13
    lines hold more ink than the 12 halfway between, `keep` of them that differ."""
    import numpy as np
    n = len(prof)
    k = 3
    sm = np.convolve(prof, np.ones(2 * k + 1) / (2 * k + 1), mode="same")
    out = []
    for p in np.arange(pitch * pitches[0], pitch * pitches[1] + 1e-9, pitch * 0.004):
        starts = np.arange(int(a0 - span * pitch), int(a0 + span * pitch) + 1)
        starts = starts[(starts >= 0) & (starts + 12 * p < n - 1)]
        if not len(starts):
            continue
        on = np.zeros(len(starts))
        off = np.zeros(len(starts))
        for i in range(13):
            on += sm[np.round(starts + i * p).astype(int)]
            if i < 12:
                off += sm[np.round(starts + (i + 0.5) * p).astype(int)]
        score = on / 13 - off / 12
        j = int(np.argmax(score))
        out.append((float(score[j]), float(starts[j]), float(p)))
    out.sort(reverse=True)
    kept = []
    for s, a, p in out:
        if all(abs(a - b) > 0.3 * pitch or abs(p - q) > 0.03 * pitch for _, b, q in kept):
            kept.append((s, a, p))
        if len(kept) >= keep:
            break
    return kept


#: Half-cell shifts (across, down) of a refitted lattice tried after it: its left end and top may sit on a rule
#: beside the grid's own (the frame, a caption's rule).
REFIT_SHIFTS = ((-0.5, 0), (0.5, 0), (-0.5, -0.5), (-0.5, 0.5), (0.5, -0.5), (0.5, 0.5), (0, 0.5), (0, -0.5))


def refit_lattices(ink, ys, xs, keep=2):
    """[(ys, xs)] of the lattice (ys, xs) fitted again to the ink's line profiles (the columns' ink in the grid's band
    sets x0 and the pitch across, then the rows' ink in that width the same down), then the half-cell shifts."""
    h, w = ink.shape
    px, py = (xs[-1] - xs[0]) / CELLS, (ys[-1] - ys[0]) / CELLS
    out = []
    band = ink[int(max(0, ys[0])):int(min(h, ys[-1]))]
    for _, x0, p in _comb_axis(band.mean(0), xs[0], px, keep=keep):
        xx = [x0 + i * p for i in range(CELLS + 1)]
        rp = ink[:, int(max(0, xx[0])):int(min(w, xx[-1]))].mean(1)
        for _, y0, q in _comb_axis(rp, ys[0], py, keep=1):
            out.append(([y0 + i * q for i in range(CELLS + 1)], xx))
    for yy, xx in list(out):
        qx, qy = (xx[-1] - xx[0]) / CELLS, (yy[-1] - yy[0]) / CELLS
        for dx, dy in REFIT_SHIFTS:
            y2, x2 = [y + dy * qy for y in yy], [x + dx * qx for x in xx]
            if y2[0] >= 0 and x2[0] >= 0 and y2[-1] < h and x2[-1] < w:
                out.append((y2, x2))
    return out


def read_lattice(gray, ink, ys, xs, wanted=None):
    """(rows, found, None) or (None, found, why) of the grid on the lattice (ys, xs): bars by their widths, the
    reading standing when ios_barred's checks hold (symmetric bars) and its lights number a Mephisto's (24-46)."""
    import listener_grid as lg
    import ios_barred as ib
    import reconstruct_grid as rg
    pad = 6
    y0, x0 = max(0, int(ys[0]) - pad), max(0, int(xs[0]) - pad)
    sub = ink[y0:int(ys[-1]) + pad, x0:int(xs[-1]) + pad]
    dark = lg.darkness(gray[y0:int(ys[-1]) + pad, x0:int(xs[-1]) + pad])
    sys_, sxs = [y - y0 for y in ys], [x - x0 for x in xs]
    rows, sides, thin = lg.read_box(sub, dark, sys_, sxs)
    # The thin rules here are broken (their width reads ~nothing, so any ink beside one passes for a bar): a side
    # is a bar when it is BAR_WIDTH of a pitch wide (the bars are ~20 px at ~97), and the thin width stands at
    # the bar line's own ratio.
    pitch = (xs[-1] - xs[0]) / CELLS
    rows = ib.rows_of({k for k, v in sides.items() if v >= BAR_WIDTH * pitch})
    thin = BAR_WIDTH * pitch / lg.BAR_RATIO
    found = {"rows": rows, "sides": sides, "thin": thin, "lattice": (list(ys), list(xs)),
             "box": (int(xs[0]), int(ys[0]), int(xs[-1]), int(ys[-1]))}
    fitted, why = ib.read_found(found, wanted)
    if fitted is None and wanted:
        fitted = mirror_fit(found, wanted)
        why = why if fitted is None else None
    if fitted is None:
        return None, found, why
    lights = len(rg.light_cells(fitted))
    if not LIGHTS[0] <= lights <= LIGHTS[1]:
        return None, found, f"the grid has {lights} lights, not a Mephisto's"
    return fitted, found, None


# ------------------------------------------------------------ the clue lists

def lists_cut(words, box):
    """(box, masks) of the clue lists under the grid at `box` (x0, y0, x1, y1) on a page's `words`: from the
    Mephisto title under the grid (else a little under the grid) down to the first stop word ("Solution to
    Mephisto N", "Winners", "Prizes") or gap of three lines in the grid's columns."""
    import gale_listener as gl
    lh = gl.line_height(words)
    left, right = box[0] - lh, box[2] + lh
    inside = [w for w in words if left <= (w[0] + w[2]) / 2 <= right and w[1] > box[3]]
    titles = [w for w in inside if TITLE_WORD.match(w[4]) and w[1] - box[3] < 40 * lh]
    top = (min(titles, key=lambda w: w[1])[1] - lh) if titles else box[3] + lh
    bottom = top
    # LISTS_FIX: a box taller than TALL_BOX lines is a misread (the OCR merged a column's lines or the solution's grid
    # of letters into one box): its foot no longer pushes the cut's bottom past the solution's heading below it.
    for w in sorted((w for w in inside if w[3] > top), key=lambda w: w[1]):
        # The stop is the heading of last week's answers ("Solution to Mephisto 2283:"), not the word "solutions"
        # in a note beside the lists ("the reference for all solutions except proper nouns").
        rest = " ".join(o[4] for o in sorted(inside, key=lambda o: o[0])
                        if o[0] >= w[0] - 1 and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < (w[3] - w[1]) / 2)
        if w[1] > top + 6 * lh and (STOP_LINE.match(rest) or STOP_BOOKWISE.match(w[4]) or (
                STOP_WORD.match(w[4]) and not w[4].rstrip().endswith("?") and not re.search(r"\(\s*\d", rest)
                and not re.match(
                    r"(?i)(solutions?|answers)\s+(except|for|of|to the)\b", rest) and not rest.lower().startswith(
                        ("solutions", "solution ", "answers")))):
            # The cut stops above the heading, whatever a taller box before it reached.
            bottom = min(bottom, w[1])
            break
        if w[3] - w[1] > TALL_BOX * lh:
            continue
        if w[1] - bottom > GAP_LINES * lh and bottom > top + 6 * lh:
            break
        bottom = max(bottom, w[3])
    return (int(left), int(top), int(right), int(bottom + lh / 2)), []


def beside_cut(words, box):
    """(box, masks) of the clue lists printed to the right of the grid at `box` (the later pages set the grid at the
    page's left, the Across and Down columns beside it from the grid's top), or None: the Across heading right of the
    grid near its top and the Down heading beside it give the two columns' width; the lists run down to the first
    stop word or gap of three lines."""
    import gale_listener as gl
    lh = gl.line_height(words)
    heads = [w for w in words if gl.heading(w[4]) and box[1] - 6 * lh <= w[1] <= box[3] - 6 * lh and w[0] >= box[2] - lh
             and w[0] - box[2] < 4 * (box[2] - box[0])]
    across = [w for w in heads if gl.heading(w[4]) == "ACROSS"]
    if not across:
        return None
    a = min(across, key=lambda w: (abs(w[1] - box[1]), w[0]))
    downs = [w for w in heads if gl.heading(w[4]) == "DOWN" and w[0] > a[0] + 3 * lh and abs(w[1] - a[1]) < 3 * lh]
    if not downs:
        return None
    d = min(downs, key=lambda w: w[0])
    left, right = a[0] - lh / 2, d[0] + (d[0] - a[0]) - lh / 2
    top = a[1] - lh / 2
    inside = [w for w in words if left <= (w[0] + w[2]) / 2 <= right and w[3] > top]
    bottom = top
    for w in sorted(inside, key=lambda w: w[1]):
        rest = " ".join(o[4] for o in sorted(inside, key=lambda o: o[0])
                        if o[0] >= w[0] - 1 and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < (w[3] - w[1]) / 2)
        if w[1] > top + 6 * lh and STOP_LINE.match(rest):
            break
        if w[1] - bottom > 3 * lh and bottom > top + 6 * lh:
            break
        bottom = max(bottom, w[3])
    return (int(left), int(top), int(right), int(bottom + lh / 2)), []


#: A clue number as the OCR reads it opening a line.
NUMBER_WORD = re.compile(r"^\d{1,2}[.,]?$")


#: A clue number printed bare (1995-99 print "5 Cry echoed", no stop after it).
BARE_NUMBER = re.compile(r"^\d{1,2}$")
#: Bare numbers standing within this of each other's left edge, at least BARE_RUN of them, are a clue column's.
BARE_STEP, BARE_RUN = 12, 4


def bare_stops(words):
    """`words` put in the form the Listener's readers open on when no clue column is found in them
    (gale_listener.column_lefts needs a stop after a number): the bare numbers lined up at a column's left edge
    (BARE_RUN or more) are given their stop, and an Across heading is put over the leftmost column's first number
    when none is read (the 1995-99 lists print no heading over the left column, or the OCR reads it as a word):
    "no clue list on the page". `words` itself (the same list) when its columns are found already or no bare column
    stands in it. This is gale_listener.WORD_FIX while a Mephisto is read; nothing is written to the OCR cache
    (down_headed's rewrite apart)."""
    import statistics
    import gale_listener as gl
    if gl.column_lefts(words):
        return words
    nums = [w for w in words if BARE_NUMBER.match(w[4])]
    aligned = [w for w in nums if sum(abs(o[0] - w[0]) <= BARE_STEP for o in nums) >= BARE_RUN]
    if len(aligned) < 2 * BARE_RUN:
        return words
    mark = {id(w) for w in aligned}
    out = [(*w[:4], w[4] + ".") if id(w) in mark else w for w in words]
    if not any(gl.heading(w[4]) == "ACROSS" for w in gl.headings(words)):
        left = min(w[0] for w in aligned)
        col = [w for w in aligned if w[0] - left <= BARE_STEP]
        first = min(col, key=lambda w: w[1])
        h = max(10, int(statistics.median(w[3] - w[1] for w in aligned)))
        head = (int(left), max(0, int(first[1]) - h - 4), int(left) + 4 * h, max(1, int(first[1]) - 4), "Across")
        # The heading's own letters read as a word ("cross") lie under it: they go, as lend_heads drops them.
        out = [w for w in out if not (head[0] - 10 <= (w[0] + w[2]) / 2 <= head[2] + 10
                                      and head[1] - 4 <= (w[1] + w[3]) / 2 <= head[3] + 4)]
        out.append(head)
    return out


def down_headed(block, gl):
    """`block` (image, key) of the clue lists with its page words given a "Down" heading word when the Across
    heading is read and no Down one is (the right-hand column is printed under no heading: the lists then read as
    one, "no reading parses"): the heading is put over the right column's first line, at its left edge. The cached
    words of the block are rewritten (the other readers take the heading from them, gale_listener.lend_heads)."""
    import statistics
    img, key = block
    words = bare_stops(gl.page_words(img, key))
    heads = gl.headings(words)
    across = next((w for w in sorted(heads, key=lambda w: w[1]) if gl.heading(w[4]) == "ACROSS"), None)
    if across is None or any(gl.heading(w[4]) == "DOWN" for w in heads):
        return block
    nums = [w for w in words if NUMBER_WORD.match(w[4]) and w[0] > across[0] + 0.3 * img.width]
    if len(nums) < 5:
        return block
    edge = statistics.median(w[0] for w in nums)
    col = [w for w in words if edge - 15 <= w[0] and w[1] >= 0 and re.search(r"\w", w[4])
           and abs(w[0] - edge) < 0.3 * img.width]
    top = min(w[1] for w in col)
    h = max(10, int(statistics.median(w[3] - w[1] for w in nums)))
    head = (int(edge), max(0, int(top) - h - 4), int(edge) + 4 * h, max(1, int(top) - 4), "Down")
    path = gl.OCR_CACHE / f"{key}.page.{gl.ocr_clues.reader_key('times')}.json"
    gl.write_whole(path, json.dumps([list(w) for w in words] + [list(head)]))
    return block


def right_edge(words, width, across_x):
    """The left edge of the clue lists' right-hand column on `words` (the median left end of the clue numbers
    right of the Across column), or None."""
    import statistics
    nums = [w for w in words if NUMBER_WORD.match(w[4]) and w[0] > across_x + 0.3 * width]
    return statistics.median(w[0] for w in nums) if len(nums) >= 5 else None


def tail_strip(words, cut, edge, gl):
    """(x0, y0, x1, y1) in page coordinates of the Down list's head, or None: the Mephisto prints the "Down" heading
    and the first Down clues (1, 2) at the foot of the left column, under the Across list (the list goes on at the
    top of the right column), beside last week's solution; the lists' cut stops at that solution's heading. The
    strip runs from the "Down" heading at the left edge down its clue lines to the gap before the note."""
    left, _, right, bottom = cut[0]
    x_cut = left + edge - 10
    heads = [w for w in words if gl.heading(w[4]) == "DOWN" and left <= w[0] <= left + 0.2 * (right - left)
             and bottom - 100 <= w[1] <= bottom + 400]
    if not heads:
        return headless_tail(words, cut, edge, gl)
    head = min(heads, key=lambda w: w[1])
    return tail_lines(words, left, x_cut, head[1], gl)


#: A line opening a note under the lists, not a clue.
NOTE_LINE = re.compile(r"^\W*(?:the\s+editor|winners|prizes?|solutions?\b|answers\b)", re.IGNORECASE)


def headless_tail(words, cut, edge, gl):
    """tail_strip's strip when the OCR read no "Down" heading at the left column's foot (the first Down clues stand
    under the Across list's last clue, No 2055's 1-down to 3-down): the Down list opens at the first clue-number line
    of the left column whose number falls back to 3 or less after the Across numbers had reached 10. The strip is
    marked headless (a 5th element) so lists_block gives the stitched block its Down heading. None when no line
    does."""
    left, top, right, _ = cut[0]
    x_cut = left + edge - 10
    lines = {}
    for w in words:
        if left <= w[0] < x_cut and w[1] >= top and re.search(r"\w", w[4]):
            lines.setdefault(round((w[1] + w[3]) / 2 / 8), []).append(w)
    seen = 0
    for _, ws in sorted(lines.items()):
        first = min(ws, key=lambda w: w[0])
        if not (NUMBER_WORD.match(first[4]) and first[0] <= left + 0.1 * (right - left)):
            continue
        n = int(first[4].strip(".,"))
        if seen >= 10 and n <= 3:
            strip = tail_lines(words, left, x_cut, first[1], gl, note=True)
            return strip + (True,) if strip else None
        seen = max(seen, n)
    return None


def tail_lines(words, left, x_cut, head_y, gl, note=False):
    """The strip (x0, y0, x1, y1) of the left column's lines from y `head_y` down to the gap before the note."""
    head = (0, head_y)
    lines = {}
    for w in words:
        if left <= w[0] < x_cut and w[1] >= head[1] - 4 and re.search(r"\w", w[4]):
            lines.setdefault(round((w[1] + w[3]) / 2 / 8), []).append(w)
    if note:
        for k, ws in sorted(lines.items()):
            if NOTE_LINE.match(" ".join(w[4] for w in sorted(ws))):
                lines = {j: v for j, v in lines.items() if j < k}
                break
        if not lines:
            return None
    mids = sorted(sum((w[1] + w[3]) / 2 for w in ws) / len(ws) for ws in lines.values())
    steps = sorted(b - a for a, b in zip(mids, mids[1:]) if b - a > 12)
    step = steps[len(steps) // 2] if steps else 40
    last = mids[0]
    for m in mids[1:]:
        if m - last > 1.7 * step:
            break
        last = m
    if last <= mids[0]:
        return None
    ws = [w for ws in lines.values() for w in ws if (w[1] + w[3]) / 2 <= last + 4]
    return (int(min(w[0] for w in ws)) - 6, int(head[1]) - 6, int(x_cut), int(max(w[3] for w in ws)) + 6)


def lists_block(img, key, words, cut, gl):
    """The clue lists' block (image, key) for `cut`, the lists' foot read as the Mephisto prints it: when the Down
    heading and the first Down clues stand at the left column's foot (tail_strip), they are stitched over the right
    column (the block shifted down for them), so the list reads in order; else a block with no Down heading is
    given one (down_headed). None when no block is found."""
    from PIL import Image
    block = gl.times_block(img, key, cut, words)
    if not block:
        return None
    bimg, bkey = block
    bwords = bare_stops(gl.page_words(bimg, bkey))
    across = next((w for w in gl.headings(bwords) if gl.heading(w[4]) == "ACROSS"), None)
    if across is None:
        return block
    edge = right_edge(bwords, bimg.width, across[0])
    strip = edge and tail_strip(words, cut, edge, gl)
    if not strip:
        return down_headed(block, gl)
    headless = len(strip) > 4
    strip = strip[:4]
    if headless and strip[1] < cut[0][3] - 4:
        # The cut ran on over the Down clues (the solution's heading was garbled): it stops above them.
        again = gl.times_block(img, key, ((cut[0][0], cut[0][1], cut[0][2], strip[1] - 4), []), words)
        if again:
            bimg, bkey = block = again
    piece = img.crop(strip)
    pad = 4 + (36 if headless else 0)
    shift = piece.height + 12 + (36 if headless else 0)
    # The Across list's last clues may stand under the solution's heading too, above the Down heading: they go
    # on under the left column's foot, where the list runs on.
    lead = None if headless else lead_strip(words, cut, strip, gl)
    lead_img = img.crop(lead) if lead else None
    foot = lead_img.height + 8 if lead_img else 0
    canvas = Image.new(bimg.mode, (max(bimg.width, int(edge) + piece.width + 4), bimg.height + shift + foot), "white")
    canvas.paste(bimg, (0, shift))
    canvas.paste(piece, (int(edge), pad))
    if lead_img:
        canvas.paste(lead_img, (max(0, lead[0] - cut[0][0]), shift + bimg.height + 4))
    stitched = canvas, gl.image_key(canvas)
    # No Down heading was read over the strip: the stitched block is given one, over the strip's first line.
    return down_headed(stitched, gl)


def lead_strip(words, cut, strip, gl):
    """(x0, y0, x1, y1) of the clue lines between the lists' cut (stopped at the solution's heading) and the Down
    heading's strip, in the left column, opening on a clue number (the Across list's last clue, 34-across of No
    2113), or None."""
    left, _, _, bottom = cut[0]
    lines = {}
    for w in words:
        if left <= w[0] < strip[2] and bottom <= w[1] and w[3] <= strip[1] + 2 and re.search(r"\w", w[4]):
            lines.setdefault(round((w[1] + w[3]) / 2 / 8), []).append(w)
    firsts = [min(ws, key=lambda w: w[0]) for _, ws in sorted(lines.items())]
    opening = next((w for w in firsts if NUMBER_WORD.match(w[4]) and w[0] <= left + 0.1 * (strip[2] - left)), None)
    if opening is None:
        return None
    ws = [w for ws in lines.values() for w in ws if w[1] >= opening[1] - 3]
    return (int(min(w[0] for w in ws)) - 6, int(opening[1]) - 3, strip[2], strip[1] - 2)


#: Pixels above a clue's number and below its last line kept in the tight crop.
TIGHT_PAD = 6
#: A clue's number stands within this of its column's left edge.
TIGHT_LEFT = 30
WORDS_COUNT = re.compile(r"\(\s*(\d{1,2})\s*,\s*(?:two|three|four|five|six)\s+words?\s*\)", re.IGNORECASE)


#: Bumped when only the clue columns' cut changes: the pages read with a blank light are read again (not every page).
COLUMN_FIX = 1
#: A Mephisto clue column is wider than this share of the block (two or three columns hold the lists).
MIN_COLUMN = 0.2


def column_lefts(located, width, step=40, least=3):
    """The left edges of the clue columns (gale_jumbo_read.number_lefts), a run of numbers standing within MIN_COLUMN
    of the block's width of a longer run dropped: numbers inside a clue's own lines (a count, a year, a figure
    opening a wrapped line) lined up as a column and cut the real column to the strip of its number and first word,
    so the VLM and the tight crops were asked a fragment."""
    import gale_jumbo_read as gj
    xs = sorted(w[0] for w in gj.numbers_of(located))
    runs = []
    for x in xs:
        if runs and x - runs[-1][-1] <= step:
            runs[-1].append(x)
        else:
            runs.append([x])
    runs = [r for r in runs if len(r) >= least]
    kept = [r for r in runs if not any(o is not r and len(o) > len(r) and abs(min(o) - min(r)) < MIN_COLUMN * width
                                       for o in runs)]
    return [min(r) - 15 for r in kept]


def tight_crops(block, number, gl, gj):
    """[image] of each clue standing under `number` in the clue block ((image, key)): the column's strip from the
    number's line to the next clue's number (one clue, so the reader has nothing else to mistake it for)."""
    bimg, bkey = block
    located = gl.figures(gl.page_words(bimg, bkey))
    lefts = column_lefts(located, bimg.width)
    if not lefts:
        return []
    edges = lefts + [bimg.width]
    nums = gj.numbers_of(located)
    out = []
    for i, x0 in enumerate(lefts):
        # Only a figure opening its line (a count "(11," standing inside the clue is no number).
        col = sorted((w for w in nums if x0 - 8 <= w[0] < x0 + TIGHT_LEFT), key=lambda w: w[1])
        for k, w in enumerate(col):
            m = gj.NUMBER_LINE.match(w[4])
            if not m or int(m.group(1)) != number:
                continue
            top = max(0, int(w[1]) - TIGHT_PAD)
            bottom = int(col[k + 1][1]) - 2 if k + 1 < len(col) else bimg.height
            if bottom - top < 10:
                continue
            out.append(bimg.crop((max(0, int(x0) - 4), top, min(bimg.width, int(edges[i + 1])), min(bimg.height, bottom + 2))))
    return out


def tight_mended(block, laid, blank, lengths, gl, asker=None):
    """(laid, blank, asked) with each blank light a tight per-clue crop lays: the crop read by the page OCR and by
    the VLM, the clue laid only when both spell it (gale_jumbo_read.vlm_laid: the VLM's words mostly in the OCR's
    bag, its count the light's). A number two lights share by length is left blank (the crop has no neighbours to
    tell the lists apart)."""
    import gale_jumbo_read as gj
    todo = {}
    for lid, why in blank.items():
        number = int(lid.split("-")[0])
        if lid not in lengths:
            continue
        if any(o != lid and o.split("-")[0] == lid.split("-")[0] and lengths.get(o) == lengths.get(lid) for o in lengths):
            continue
        todo[lid] = (number, why)
    if not todo:
        return laid, blank, 0
    reader = asker
    if reader is None:
        if not fa.vlm.wanted():
            return laid, blank, 0
        def reader(im, box):
            return fa.vlm.read(fa.vlm.crop(im, box))
    asked = 0
    laid, left = dict(laid), dict(blank)
    for lid, (number, why) in sorted(todo.items()):
        for crop in tight_crops(block, number, gl, gj):
            try:
                reply = reader(crop, (0, 0, crop.width, crop.height))
            except RuntimeError:
                return laid, left, asked
            asked += 1
            # "(11, three words)": the count's own words, which fa's count reads as a stray number; the light's cells
            # give the count, so it is put as "(11)".
            reply = WORDS_COUNT.sub(r"(\1)", reply or "")
            ocr = " ".join(w[4] for w in gl.figures(gl.page_words(crop, gl.image_key(crop))))
            page = " ".join(w[4] for w in gl.figures(gl.page_words(*block)))
            got, still = gj.vlm_laid({"vlm": reply or "", "tight": ocr, "page": page}, laid, {lid: why}, lengths, {})
            if lid not in still:
                laid, left = got, {k: v for k, v in left.items() if k != lid}
                break
    return laid, left, asked


def listed(img, key, words, found, gl):
    """wanted_of the clue lists under the grid at `found`, read without the grid's lengths ([] when none read)."""
    block = lists_block(img, key, words, beside_cut(words, found["box"]) or lists_cut(words, found["box"]), gl)
    if not block:
        return []
    _, laid = gl.times_read([block], None)
    return wanted_of(laid or {})


def read_page(path, store=STORE, asker=None):
    """(verdict, puzzle or None) of one saved page (page_read), the Listener's readers given bare_stops for the
    pages' bare clue numbers while it is read."""
    import gale_listener as gl
    was, gl.WORD_FIX = gl.WORD_FIX, bare_stops
    try:
        return page_read(path, store, asker)
    finally:
        gl.WORD_FIX = was


def page_read(path, store=STORE, asker=None):
    """(verdict, puzzle or None) of one saved page. `asker` stands in for the VLM (gale_jumbo_read.vlm_mended)."""
    import numpy as np
    import gale_listener as gl
    import gale_jumbo_read as gj
    import archive_org_jumbo as aj
    import ocr_clues
    img, cite = gi.images(path)[0]
    verdict = {"file": path.name}
    cited = cite_of(cite)
    if not cited:
        verdict["refused"] = "no Sunday Times citation on the page"
        return verdict, None
    day = cited[1]
    docid = DOC_ID.search(path.name.upper())
    dates, titled = docs_index()
    when = dates.get(docid.group(0)) if docid else None
    own = next((n for d, n in titled if d == when), None) if when else None
    doc = (when, own) if when else None
    if day < COUNT_FROM and not (doc and docs_number(*doc, titled)) and not offset_bounds(day, titled):
        # Before 1995 a titled neighbour sets the number, or the page's own printed one inside the neighbours'
        # offsets: with no titled page on one side there is nothing to check a printed number against.
        verdict.update(refused=UNNUMBERED, date=day.isoformat())
        return verdict, None
    key = gl.image_key(img)
    words = gl.page_words(img, key)
    text = ocr_clues.lines_of(words)
    near = near_offsets(day, load_ledger(store).values(), path.name) if day < COUNT_FROM else ()
    n, how = number_of(cited, text, doc, near)
    if n is None:
        verdict["refused"] = UNNUMBERED
        verdict["date"] = day.isoformat()
        got = printed_offset(day, text, titled) if day < COUNT_FROM else None
        if got:
            verdict.update(refused=UNCONFIRMED, seen=got[0])
        return verdict, None
    verdict.update(number=n, numberFrom=how, date=day.isoformat())
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    rows, found, why = read_barred(gray)
    fitted = False
    if rows is None and found:
        # The bars alone do not read: the clue lists' counts, read without the grid, set them (mirror_fit).
        rows, found2, why2 = read_barred(gray, wanted=listed(img, key, words, found, gl))
        if rows is not None:
            found, fitted = found2, True
        else:
            why = why2 or why
    if rows is None:
        verdict["refused"] = f"grid unread: {why}"
        return verdict, None
    g = rows
    gpath = Path(store) / "grids" / f"{path.stem}.png"
    gpath.parent.mkdir(parents=True, exist_ok=True)
    img.crop(found["box"]).save(gpath)
    cut = beside_cut(words, found["box"]) or lists_cut(words, found["box"])
    block = lists_block(img, key, words, cut, gl)
    if not block:
        verdict["refused"] = "no Mephisto clue lists found on the page"
        return verdict, None
    blocks = [block]
    lengths = {f"{k}-{d}": len(cells) for (k, d), cells in aj.rg.light_cells(g).items()}
    read, laid = gl.times_read(blocks, lengths)
    if laid is None and not fitted:
        # The bars read symmetric but the lights do not fit the lists: the lists' counts set the bars again.
        again, found2, _ = read_barred(gray, wanted=listed(img, key, words, found, gl))
        if again is not None and again != g:
            g, found, fitted = again, found2, True
            lengths = {f"{k}-{d}": len(cells) for (k, d), cells in aj.rg.light_cells(g).items()}
            read, laid = gl.times_read(blocks, lengths)
    if fitted:
        verdict["barsFitted"] = True
    verdict.update({k: v for k, v in read.items() if k in ("agreed", "clues", "refused")})
    if laid is None:
        return verdict, None
    voted = dict(laid)
    laid, blank = aj.lay_on(dict(laid), g)
    blank = {**(read.get("blank") or {}), **blank}
    tails = {t for _, _, group in laid.values() for t in (group or [])[1:]}
    for lid, (text, _, _) in laid.items():
        if lid not in tails and not (text or "").strip():
            blank.setdefault(lid, gj.UNLAID)
    laid, blank, asked = gj.vlm_mended(blocks, laid, blank, lengths, gl, asker, voted, lefts_of=column_lefts)
    if asked:
        verdict["vlmColumns"] = asked
    if blank:
        laid, blank, tight = tight_mended(block, laid, blank, lengths, gl, asker)
        if tight:
            verdict["tightClues"] = tight
    verdict["lights"] = len(laid)
    verdict["blank"] = sorted(blank)
    verdict["why"] = {k: str(v)[:80] for k, v in sorted(blank.items())}
    doc = DOC_ID.search(path.name.upper())
    url = f"https://link.gale.com/apps/doc/{doc.group(0)}/STHA?sid=bookmark-STHA" if doc else None
    puzzle = fa.build(n, day, g, "image", laid, None, 0, series=SERIES, name=f"Sunday Times Mephisto No {n}",
                      url=url, printed=read.get("asPrinted"))
    verdict["whole"] = bool(fa.complete(puzzle))
    if not verdict["whole"] and not blank:
        # Every clue has text, so what keeps the page from whole is a clue complete() refuses (a bracket it never
        # pairs, a word the OCR made up): named, so a "not whole, no blanks" row says which clues.
        verdict["unfit"] = sorted({f"{k}": str(v)[:60] for k, v in (fa.faults(puzzle) or {}).items()}.items()) + [
            f"{e['number']}-{e['direction']}: suspect" for e in puzzle["entries"]
            if fa.suspect((e.get("clue") or {}).get("text", ""), printed=(e.get("clue") or {}).get("asPrinted") or ())]
    return verdict, puzzle


def read_unit(rel, saved=SAVED, store=STORE):
    """Read one saved page (a unit's rel, "mephisto:NAME" or NAME), file its puzzle when whole and no file holds
    the number; the ledger row appended. Returns "read", "current" or "failed"."""
    import scan_queue
    from fetch_puzzle import puzzle_path, write_puzzle_file
    name = rel[len(PREFIX):] if rel.startswith(PREFIX) else rel
    path = Path(saved) / name
    ledger = load_ledger(store)
    before = ledger.get(name)
    if not path.exists() or read_done(before, ledger):
        return "current"
    try:
        verdict, puzzle = read_page(path, store)
    except Exception as e:  # any raise: the page stays due (read_done) until CRASH_LIMIT attempts
        attempts = (before or {}).get("attempts", 0) + 1
        verdict = {"file": name, "failed": f"crashed: {type(e).__name__}: {e}", "attempts": attempts}
        print(verdict["failed"], file=sys.stderr)
        append_row({**verdict, "version": VERSION if attempts >= CRASH_LIMIT else None}, store)
        return "failed"
    if puzzle is not None and verdict.get("whole"):
        target = puzzle_path(SERIES, verdict["number"])
        if target.exists():
            verdict["skip"] = "already held"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            scan_queue.file_puzzle(write_puzzle_file, TOOL, target, puzzle, verdict)
    append_row({**verdict, "version": VERSION, "gridFix": GRID_FIX, "numberFix": NUMBER_FIX,
                "tailFix": TAIL_FIX, "runFix": RUN_FIX, "countFix": COUNT_FIX, "bridgeFix": BRIDGE_FIX, "columnFix": COLUMN_FIX,
                "bareFix": BARE_FIX, "listsFix": LISTS_FIX}, store)
    print(json.dumps(verdict))
    return "read"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["plan"]:
        print(len(plan()))
        return 0
    if argv[:1] == ["read"] and len(argv) > 1:
        print(read_unit(argv[1]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
