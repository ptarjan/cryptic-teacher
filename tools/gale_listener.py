#!/usr/bin/env python3
"""The Listener crosswords of 1930-91, read from the pages Paul saves BY HAND
from Gale's Listener Historical Archive (through the Alberta Research Portal).

Only tools/gale_docs.py asks Gale anything: each sync looks up the next
puzzles' document ids, so their rows link straight to Gale's Download. This
writes a checklist of the puzzles to save, from the
Listener Team's year index (listenercrossword.com /Years/Y<year>.html, read
for the numbers and dates only), and reads each page Paul saves into his
inbox with the clue OCR every scan filer shares (tools/ocr_clues.py's
readers, tools/archive_org_listener.py's vote).

    python3 tools/gale_listener.py sync               # mirror the Mac's inbox, read new pages, file, publish the checklist
    python3 tools/gale_listener.py read --inbox DIR [--store DIR]   # read a local folder (no Mac)
    python3 tools/gale_listener.py checklist [--out FILE]
    python3 tools/gale_listener.py match FILE...      # which puzzle each file is, and how that was read

The inbox is gi.LISTENER_INBOX on the Mac, mirrored to MIRROR over the ssh hatch
as tools/gale_inbox.py mirrors the Times'. A file is matched to its puzzle
by the date in its name, else the puzzle number in its name, else the
number its Gale citation's article title prints ("No. 22—A French
Crossword"), else the date the citation prints, else the number our
readers read in its title ("Crossword No. 1,234"); a date gives the puzzle
the index puts on that issue. A page may also print a past puzzle's
solution, "Report on Crossword No. 16" with the filled grid, about two
issues later: the citation or the page's words name it, the ledger keeps it
as the file's "reports", and the checklist asks for that page while a
saved puzzle has none. Each file is read once: STORE/ledger.json is keyed
by the file's sha256 (and VERSION), so a re-run reads only files new or
changed. tools/ocr_full_pass.sh runs `sync` at its start and before every
slice, so a page is read within about a slice of landing.

What a page gives is its clues: STORE/listener-N.json, the reading
tools/archive_org_listener.py writes (clue text and count by light, the
vote's blanks, the source). A puzzle file needs the grid and answers too,
which a barred grid's clues alone do not give: `sync` then runs
tools/file_gale_listener.py, which joins each reading with its page's grid
(tools/listener_grid.py) and files what passes unsolved; the later
report's letters are kept as a check on the solve, never filed.
"""
import argparse
import datetime
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import archive_org_listener as al
import file_archive_org_puzzles as fa
import gale_docs
import gale_inbox as gi
import listener_puzzles as lp
import ocr_clues

#: Published to the Gale root beside the Times' checklist.
CHECKLIST_NAME = "Listener checklist.html"
HOME = Path(os.path.expanduser("~/.cache/gale_listener"))
MIRROR = HOME / "files"
CHECKLIST = HOME / CHECKLIST_NAME
#: Each mirrored file's cheap match (name, citation; no OCR), by name, size
#: and mtime: what the every-minute tick ticks off before the full pass reads it.
ARRIVED = HOME / "arrived.json"
OCR_CACHE = HOME / "ocr"
#: The readings and the ledger: derived from Paul's pages, kept beside the
#: series' other source data.
STORE = lp.CACHE / "gale"
YEARS = lp.CACHE / "years"
#: The Listener magazine's last issue; the puzzle moved to The Times after it.
FIRST_YEAR, LAST_ISSUE = 1930, datetime.date(1991, 1, 3)
#: Bumped when the reading changes, so every file is read again.
VERSION = 3
PORTAL = gi.PORTAL
DOC_URL = "https://go.gale.com/ps/retrieve.do?docId=GALE%7C{}&prodId=LSNR&userGroupName=alberta_portal"

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
NUMBERED = re.compile(r"^n[o0]\.?\s*(\d{1,4})\b|crossword\W{0,3}(?:puzzle\W{0,3})?n[o0]\.?\s*(\d{1,4})\b",
                      re.IGNORECASE)
#: The report printing a past puzzle's solution grid and solvers:
#: "Report on Crossword No. 16", "Report on Wireless Crossword No. 38".
REPORT = re.compile(r"report\s+on\b[^\n]{0,40}?crossword\W{0,3}n[o0]\.?\s*(\d{1,4})\b", re.IGNORECASE)
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


def index(cache=YEARS, fetch=True):
    """[{number, title, setter, date}] of every Listener the magazine printed."""
    rows = {}
    for y in range(FIRST_YEAR, LAST_ISSUE.year + 1):
        for r in parse_year(year_page(y, cache, fetch), y):
            if r["date"] <= LAST_ISSUE:
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
    path.write_text(json.dumps(words))
    return words


def image_key(img):
    return hashlib.sha256(img.tobytes()).hexdigest()[:20]


def cited(cite):
    """(number, how, reports) a Gale PDF's citation gives: the puzzle its
    article title numbers (None, None when it numbers none; cited_day reads
    the date), and the past puzzles whose report it is."""
    cite = re.sub(r"\s+", " ", cite or "")
    title = (m.group(1) if (m := ARTICLE.search(cite)) else "").strip()
    reports = {int(n) for n in REPORT.findall(title)}
    if not reports and (m := NUMBERED.search(title)):
        return int(m.group(1) or m.group(2)), "PDF citation title", reports
    return None, None, reports


def cited_day(cite):
    m = CITED.search(re.sub(r"\s+", " ", cite or ""))
    return m and datetime.date(int(m.group(3)), gi.MONTHS[m.group(2)[:3].lower()], int(m.group(1)))


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
    day = gi.name_date(name, DATES)
    if day:
        r = by_date(idx, day)
        out.update(number=r and r["number"], how="file name date")
    if out["number"] is None and (n := name_number(name)) is not None:
        out.update(number=n, how="file name number")
    if out["number"] is None and number is not None:
        out.update(number=number, how=how)
    if out["number"] is None and (day := cited_day(cite)):
        r = by_date(idx, day)
        out.update(number=r and r["number"], how="PDF citation date")
    if read_title:
        for img, key in out["pages"]:
            text = ocr_clues.lines_of(page_words(img, key))
            reports |= {int(n) for n in REPORT.findall(text)}
            if out["number"] is None and (m := TITLE.search(text)):
                out.update(number=int(re.sub(r"\D", "", m.group(1))), how="title read")
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
                and 0 <= o[0] - w[2] <= max(40, BESIDE * (w[3] - w[1]))
                and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < (w[3] - w[1]) for o in words):
            continue
        out.append(w)
    return out


def page_columns(words):
    """[across lines, down lines], each [(y0, y1, x0, x1, text)], for a page
    laid out any way: headed_columns when both headings are read and give
    two lists, else numbered_columns."""
    return headed_columns(words) or numbered_columns(words)


def headed_columns(words):
    """[across lines, down lines] cut at the gutters, read left to right
    from the column the ACROSS heading is in (its clue numbers' edge, which
    may be up to CENTRED left of it), each from the lists' top; the lines before
    DOWN are the across clues, those after it the down. None without both
    headings."""
    across = al.heading_word(words, "ACROSS")
    down = across and next((w for w in sorted(words, key=lambda w: (w[0] // 200, w[1]))
                            if fa.heading_of(w[4]) == "DOWN"
                            and (w[1] > across[3] or w[0] > across[2])), None)
    if not across or not down:
        return None
    top = across[1] - 20
    below = [w for w in words if (w[1] + w[3]) / 2 >= top]
    # A heading may be centred over its column (No 103's), its clue numbers
    # far left of it: the column starts where they line up.
    left = max((x for x in column_lefts(below) if across[0] - CENTRED <= x <= across[0]), default=across[0] - 40)
    body = [w for w in words_only(below) if w[0] >= left]
    spans = []
    for x0, _, x1, _, _ in sorted(body):
        if spans and x0 <= spans[-1][1] + GUTTER:
            spans[-1][1] = max(spans[-1][1], x1)
        else:
            spans.append([x0, x1])
    lines = {"ACROSS": [], "DOWN": []}
    side = "ACROSS"
    for x0, x1 in spans:
        col = [(w[1], w[3], w[0], w[2], w[4]) for w in body if x0 <= w[0] <= x1]
        last = None
        for line in fa.merge_rows(col):
            if last is not None and line[0] - last > 2 * fa.GAP or al.END.match(line[4]):
                break
            last = line[1]
            head = fa.heading_of(line[4])
            if head:
                side = head
                continue
            lines[side].append(line)
        if al.END.match(lines[side][-1][4] if lines[side] else ""):
            break
    return [lines["ACROSS"], lines["DOWN"]] if lines["ACROSS"] and lines["DOWN"] else None


#: A clue number as the 1930s lists print it, "12.": where they line up
#: is a clue column (a bare "12" may be a grid's or a sentence's).
OPENS = re.compile(r"^\W{0,2}\d{1,2}[.,:](?![\d.])")
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
#: A heading stands alone on its line: no word this near either side
#: ("8 Down should have had an asterisk" is prose). A word is on its line
#: when their centres are under half its height apart: No 97's centred
#: ACROSS overlaps the first clue's line below it by a few pixels.
ALONE = 100


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
    a number and words is a clue, an indented line just under it runs on,
    and a heading, a line that is neither, a gap, or a clue numbered 1 or 2
    after a higher one, below a heading's space, ends the run (a bracketed pair, "4.} 29.}", does not). The
    runs, in column order, are chained into two lists by their first
    numbers: a run starting at 1 or 2 opens the second list, and any other
    run goes on whichever list's last clue it follows closest (No 97's
    DOWN 9 follows DOWN 3, not ACROSS 46), so a band's
    right half finds its list and prose beside the lists (a report) fits
    none. The first list is the one its
    heading names. None without two lists."""
    lefts = column_lefts(words)
    heads = [w for w in words if fa.heading_of(w[4]) and not any(
        o is not w and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < (w[3] - w[1]) / 2
        and min(abs(o[0] - w[2]), abs(w[0] - o[2])) < ALONE for o in words)]
    if not lefts or not heads:
        return None
    start = min(heads, key=lambda w: (sum(x <= w[0] for x in lefts), w[1]))
    runs = []
    for x0, x1 in zip(lefts, lefts[1:] + [float("inf")]):
        col = [(w[1], w[3], w[0], w[2], w[4]) for w in words if x0 <= w[0] < x1]
        run, last_y = [], None
        for line in fa.merge_rows(col):
            if x0 <= start[2] and line[1] <= start[3]:
                # Above the first heading, in its columns or those left of
                # it: the grid, the preamble, another article.
                continue
            m = al.LINE_CLUE.match(line[4])
            if m and line[2] - x0 < 60 and WORDY.search(m.group(2)) and not fa.heading_of(line[4]):
                n = int(m.group(1))
                if run and (line[0] - last_y > fa.GAP / 2 or n <= 2 < run[-1][0] and line[0] - last_y > RESTART):
                    runs.append(run)
                    run = []
                run.append((n, [line]))
                last_x, last_y = line[2], line[1]
            elif (run and last_y is not None and line[0] - last_y < fa.GAP / 2 and line[2] > last_x + RUN_ON
                  and not fa.heading_of(line[4])):
                run[-1][1].append(line)
                last_y = line[1]
            else:
                if run:
                    runs.append(run)
                run, last_y = [], None
        if run:
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
    return lines if fa.heading_of(start[4]) == "ACROSS" else lines[::-1]


#: A clue number in the 1930s' old-style figures, read as letters: "I."
#: for 1, "II." for 11, "Io." for 10, "I3." for 13 (No 97's, No 103's).
FIGURES = re.compile(r"^(\W{0,2})([IlO\d]?[IloO\d])([.,:])(?=\s|[A-Z]|$)")
AS_DIGIT = str.maketrans("IlOo", "1100")


def figures(words):
    """The words with a line's opening clue number read as letters put back
    in digits; a number cannot open on 0, so "O." and "Oo." stay words."""
    out = []
    for w in words:
        m = FIGURES.match(w[4])
        n = m and m.group(2).translate(AS_DIGIT)
        if m and n.isdigit() and n[0] != "0" and not m.group(2).isdigit():
            w = (*w[:4], m.group(1) + n + m.group(3) + w[4][m.end():])
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
ELSEWHERE = re.compile(r"\b(?:clues?|diagram)\b[^.]{0,40}?\bpage\s+(\d{2,4})\b", re.IGNORECASE)


def elsewhere(words):
    """The magazine pages the page's words send its clues or diagram to."""
    return sorted({int(n) for n in ELSEWHERE.findall(" ".join(ocr_clues.lines_of(words).split()))})


def read_page(img, key):
    """(verdict, {light: (text, enumeration, None)} or None) for one page:
    the whole page read by every ocr_clues.READERS reader band by band, each
    reading's lists found by page_columns, and voted on (al.vote). The
    1930s lists run on above their heading in the next column, so no box
    under a heading holds them all."""
    verdict = {}
    located = figures(page_words(img, key))
    if pages := elsewhere(located):
        verdict["seePages"] = pages
    if not any(fa.heading_of(w[4]) for w in located) and not column_lefts(located):
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
        path.write_text(json.dumps(got))
        words[which] = figures(got)
    return al.vote(words, verdict, cols=page_columns)


def see_pages(pages):
    """A refusal's note of where the page sends the puzzle's rest."""
    return f" (it sends to p. {', '.join(map(str, pages))})" if pages else ""


def read_file(m):
    """(verdict, laid) of the fullest page of a matched file."""
    best = ({"refused": "no page image"}, None)
    for img, key in m["pages"]:
        verdict, laid = read_page(img, key)
        if laid and (not best[1] or verdict["agreed"] > best[0]["agreed"]):
            best = (verdict, laid)
        elif not best[1] and "refused" in verdict:
            best = (verdict, None)
    return best


def reading(m, row, verdict, laid):
    """The reading written to STORE: archive_org_listener.reading's shape."""
    suspects = {lid: s for lid, (t, _, _) in laid.items() if t and (s := ocr_clues.suspect(t))}
    if suspects:
        verdict["suspect"] = {lid: [tok for tok, _ in s] for lid, s in suspects.items()}
    return {
        "id": f"listener-{row['number']}",
        "number": row["number"],
        "series": lp.SERIES,
        "name": f"Listener crossword No {row['number']:,}: {row['title']}",
        "setter": row.get("setter"),
        "date": row["date"].isoformat(),
        "source": {"publisher": "The Listener", "retrievedFrom": "gale", "file": m["file"],
                   "url": DOC_URL.format(m["docId"]) if m.get("docId") else PORTAL},
        "unfiled": "clues only: the grid and answers are still to be rebuilt",
        "verdict": verdict,
        "clues": {lid: {"text": t, "enumeration": e} for lid, (t, e, _) in laid.items()},
    }


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_ledger(store):
    path = store / "ledger.json"
    return json.loads(path.read_text()) if path.exists() else {}


def run(inbox=MIRROR, store=STORE, idx=None, out=sys.stdout, reader=read_file):
    """Read every file in `inbox` the ledger has not read at this VERSION;
    write each puzzle's reading to `store` (a fuller one replaces it).
    Returns the ledger."""
    idx = index() if idx is None else idx
    rows = {r["number"]: r for r in idx}
    store.mkdir(parents=True, exist_ok=True)
    ledger = load_ledger(store)
    files = sorted(p for p in Path(inbox).iterdir() if p.is_file() and p.suffix.lower() in gi.PAGES) \
        if Path(inbox).exists() else []
    for p in files:
        h = file_hash(p)
        if ledger.get(h, {}).get("version") == VERSION:
            continue
        entry = {"file": p.name, "version": VERSION, "readOn": datetime.datetime.now().astimezone().date().isoformat()}
        m = None
        try:
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
            continue
        except Exception as e:  # noqa: BLE001 -- one page's failure must not stop the pages after it
            # Ledgered with its error, so the checklist shows it and the
            # pages after it are read; a VERSION bump reads it again.
            print(f"{p.name}: read failed:\n{traceback.format_exc()}", file=out)
            why = f"read failed: {type(e).__name__}: {e}"
            if m is None:
                m = {"file": p.name, "number": None, "why": why, "pages": [], "reports": []}
            verdict, laid = {"refused": why}, None
        entry.update(number=m["number"], how=m.get("how"), why=m.get("why"), reports=m["reports"])
        if m["number"] is None and m["reports"]:
            entry["why"] = None
        if m["number"] is not None:
            if laid is None:
                entry["why"] = verdict.get("refused", "no reading")
            else:
                entry.update(clues=verdict["clues"], agreed=verdict["agreed"])
                dest = store / f"listener-{m['number']}.json"
                old = json.loads(dest.read_text()) if dest.exists() else None
                if old is None or old["verdict"].get("agreed", 0) <= verdict["agreed"]:
                    dest.write_text(json.dumps(reading(m, rows[m["number"]], verdict, laid), indent=1,
                                               ensure_ascii=False) + "\n")
                    entry["reading"] = dest.name
        ledger[h] = entry
        print(f"{p.name}: " + (f"No {m['number']} ({m['how']}), " if m["number"] is not None else "")
              + (f"{entry['agreed']}/{entry['clues']} clues read" if "agreed" in entry else entry["why"] or "")
              + "".join(f", the solution of No {n}" for n in m["reports"]), file=out)
        (store / "ledger.json").write_text(json.dumps(ledger, indent=1, ensure_ascii=False) + "\n")
    return ledger


# ------------------------------------------------------------ the checklist

def arrived(inbox=MIRROR, idx=None, path=ARRIVED):
    """[{"file", "number", "reports", "why"}] of every page file in `inbox`,
    matched by its name or citation only (no OCR: the full pass reads
    titles); a file already matched at its name, size and mtime, at this
    VERSION, is not opened again."""
    idx = index() if idx is None else idx
    known = gi.load(path, {})
    kept = {}
    files = sorted(p for p in Path(inbox).iterdir() if p.is_file() and p.suffix.lower() in gi.PAGES) \
        if Path(inbox).exists() else []
    for p in files:
        st = p.stat()
        k = f"{p.name}\t{st.st_size}\t{int(st.st_mtime)}"
        if known.get(k, {}).get("version") != VERSION:
            try:
                m = match(p, idx, read_title=False)
            except (OSError, ValueError) as e:  # shown on the checklist
                m = {"number": None, "why": f"unreadable: {type(e).__name__}: {e}", "reports": []}
            known[k] = {"file": p.name, "number": m["number"], "reports": m["reports"], "version": VERSION,
                        "why": None if m["number"] is None and m["reports"] else m.get("why")}
        kept[k] = known[k]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kept, indent=0))
    return list(kept.values())


def render(idx=None, out=sys.stdout):
    """Match what arrived and publish the checklist to the Mac."""
    idx = index() if idx is None else idx
    CHECKLIST.parent.mkdir(parents=True, exist_ok=True)
    status = {}
    CHECKLIST.write_text(checklist(idx, arrivals=arrived(MIRROR, idx), status=status))
    gi.publish(CHECKLIST, host_inbox=gi.GALE_ROOT)
    gi.publish_status(CHECKLIST, status)
    print(f"checklist published to {gi.GALE_ROOT}/{CHECKLIST.name}", file=out)


def tick(out=sys.stdout, force=False, ask=True):
    """The every-minute part (gale_inbox.sync calls it): mirror the Listener
    inbox and, when it moved (or gi.RENDER_EVERY passed), re-render the
    checklist; publish its status file either way. Gale is asked for links
    only when `ask` (gale_inbox.gale_due). The clue reading stays in the
    full pass."""
    changed = gi.mirror(out, host_inbox=gi.LISTENER_INBOX, into=MIRROR)
    idx = index()
    linked = ask and gale_docs.resolve("LSNR", [(r["date"], r["number"]) for r in to_save(idx)], out,
                                       reports=[(r["date"], r["number"]) for r in unsolved(idx)])
    last = CHECKLIST.stat().st_mtime if CHECKLIST.exists() else 0
    if force or changed or linked or time.time() - last > gi.RENDER_EVERY:
        render(idx, out=out)
    else:
        gi.publish_status(CHECKLIST)


def filed_numbers(root=ROOT):
    return {int(p.stem.split("-")[1]) for p in (root / "puzzles" / lp.SERIES).glob("*/listener-*.json")}


def to_save(idx, store=STORE, root=ROOT, arrivals=None):
    """The printed puzzles not filed, read or arrived, earliest first."""
    arrivals = list(gi.load(ARRIVED, {}).values()) if arrivals is None else arrivals
    held = filed_numbers(root) | {json.loads(p.read_text())["number"] for p in store.glob("listener-*.json")} | {
        a["number"] for a in arrivals if a.get("number") is not None}
    return [r for r in idx if printed(r) and r["number"] not in held]


def solutions(store=STORE, arrivals=None):
    """{number} of the puzzles a saved page reports on, and whether a saved
    file still waits to be read."""
    arrivals = list(gi.load(ARRIVED, {}).values()) if arrivals is None else arrivals
    ledger = load_ledger(store)
    read = {e["file"] for e in ledger.values()}
    return ({n for e in [*ledger.values(), *arrivals] for n in e.get("reports") or ()},
            any(a["file"] not in read for a in arrivals))


def unsolved(idx, store=STORE, arrivals=None):
    """The printed puzzles saved whose report page is still to save; none while a saved file waits to be read (a report is often found
    by the page's words, not its citation)."""
    solved, waiting = solutions(store, arrivals)
    if waiting:
        return []
    saved = {e["number"] for e in load_ledger(store).values() if e.get("number") is not None} | {
        json.loads(p.read_text())["number"] for p in store.glob("listener-*.json")}
    return [r for r in idx if printed(r) and r["number"] in saved - solved]


#: How the Listener's next up orders, said on the page.
ORDER = ("Order: earliest issue first, a puzzle's page and its solution page alike; a row leaves the list "
         "once its file arrives. Numbers, titles and dates are the Listener Team's index (listenercrossword.com).")


#: The Listener's own items of the checklist's how-to (gi.page).
STEPS = (
    ("A row with no Download button yet: click <b>Open in Gale</b> (Gale's results for that issue's crossword"
     " pages). If they are empty, use <i>Browse &rarr; Browse By Date</i>, pick the date, page through it to"
     " the crossword (a grid with ACROSS and DOWN clue lists) and press <i>Download</i> (PDF or image, either"
     " works). Any file name works; one with the date (e.g. <code>1930-04-09</code>) is the surest match."
     " When the grid and the clues are on different pages (&ldquo;For Clues see page 340&rdquo;), save both."),
    ("Its answers are printed about two issues later, as &ldquo;Report on Crossword No. N&rdquo; with the"
     " filled grid: save that page too. Once the pages saved are read, a row whose solution page is still"
     " missing offers <b>Download solution</b>."),
    ("Once the full pass has read a page (at its next slice, within about an hour), its status says how"
     " many clues read."),
)
RENAME = "Rename it with its issue date (e.g. 1930-04-09)."
#: What the checklist says of a file whose puzzle the tick could not name.
UNKNOWN = ("arrived, puzzle not yet known: the name and citation name no puzzle, and the full pass reads the title"
           f" at its next slice. To be sure now: {RENAME}")


def checklist(idx=None, store=STORE, root=ROOT, arrivals=None, docs=None, status=None):
    """The Listener checklist (gi.page): every Listener the magazine
    printed, earliest first, with what the inbox (`arrivals`, else
    ARRIVED's last) and the corpus hold of each."""
    idx = index() if idx is None else idx
    docs = gale_docs.load() if docs is None else docs
    arrivals = list(gi.load(ARRIVED, {}).values()) if arrivals is None else arrivals
    came = {a["number"] for a in arrivals if a.get("number") is not None}
    unnamed = [a for a in arrivals if a.get("number") is None and not a.get("reports")]
    filed = filed_numbers(root)
    ledger = load_ledger(store)
    tried = {}
    for e in ledger.values():
        if e.get("number") is not None:
            tried.setdefault(e["number"], []).append(e)
    lost = [e for e in ledger.values() if e.get("number") is None and not e.get("reports")]
    solved, _ = solutions(store, arrivals)
    got = {}
    for p in store.glob("listener-*.json"):
        r = json.loads(p.read_text())
        got[r["number"]] = r["verdict"]
    idx = [r for r in idx if printed(r)]
    todo = to_save(idx, store, root, arrivals)
    read = {e_["file"] for e_ in ledger.values()}
    asks = {r["number"] for r in unsolved(idx, store, arrivals)}

    def row(r):
        n = r["number"]
        if n in filed:
            status = [("filed", "got")]
        elif n in got:
            status = [(f'saved: {got[n].get("agreed", 0)} of {got[n].get("clues", 0)} clues read', "got")]
        elif n in tried:
            status = [(f'saved, not read: {tried[n][-1].get("why") or ""}', "bad")]
        elif n in came:
            status = [("arrived: the full pass reads it at its next slice", "got")]
        else:
            status = []
        if n in solved:
            status.append(("solution saved", "got"))
        elif n in asks:
            about = r["date"] + datetime.timedelta(days=14)
            status.append((f"save its solution too: “Report on Crossword No. {n}”, about {about:%d %b %Y}", "bad"))
        out = {"date": r["date"], "search": gi.search_url(r["date"], "LSNR"), "status": status,
               "cells": [str(n), r["title"], r.get("setter") or ""]}
        if n in asks:
            out.update(key=f"r{n}", dl=gale_docs.report_link("LSNR", n, docs), label="Download solution")
        elif n not in filed and n not in got:
            out.update(key=f"p{n}", dl=gale_docs.link("LSNR", r["date"], docs), arrived=n in came or n in tried)
        return out

    want = asks | {r["number"] for r in todo}
    held = filed | set(got) | came
    years = {}
    for r in idx:
        years.setdefault(r["date"].year, []).append(r)
    return gi.page(
        paper="Listener", prod="LSNR", name=CHECKLIST_NAME, store="listenerCopied", done=len(idx) - len(todo),
        total=len(idx), done_word="saved or filed", folder=gi.SHARE + "\\Listener",
        redo=[(a["file"], UNKNOWN) for a in unnamed if a["file"] not in read]
             + [(m["file"], f"matched no puzzle ({m.get('why') or ''}). {RENAME}") for m in lost],
        steps=STEPS,
        order=ORDER, what="pages", next_rows=[row(r) for r in idx if r["number"] in want][:gi.POOL],
        years_note="Earliest first.",
        years=[(y, f"{sum(1 for r in rs if r['number'] not in held)} of {len(rs)} to save",
                [row(r) for r in rs]) for y, rs in sorted(years.items())],
        columns=["No", "Title", "Setter"], status=status)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="mirror the Mac inbox, read new pages, file what they give, publish the checklist there")
    rd = sub.add_parser("read", help="read a local folder of pages")
    rd.add_argument("--inbox", type=Path, default=MIRROR)
    rd.add_argument("--store", type=Path, default=STORE)
    cl = sub.add_parser("checklist", help="write the checklist")
    cl.add_argument("--out", type=Path, default=CHECKLIST)
    cl.add_argument("--store", type=Path, default=STORE)
    mt = sub.add_parser("match", help="which puzzle each file is")
    mt.add_argument("files", nargs="+", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "match":
        idx = index()
        for f in a.files:
            m = match(f, idx)
            print(f"{f.name}: " + (f"No {m['number']}, {m['date']} ({m['how']})" if m["number"] is not None
                                   else f"unmatched ({m['why']})") + f", {len(m['pages'])} page image(s)")
        return 0
    if a.cmd == "checklist":
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(checklist(store=a.store))
        print(f"wrote {a.out}")
        return 0
    if a.cmd == "sync":
        with gi.locked():
            gi.mirror(host_inbox=gi.LISTENER_INBOX, into=MIRROR)
    run(a.inbox if a.cmd == "read" else MIRROR, a.store if a.cmd == "read" else STORE)
    if a.cmd == "sync":
        import file_gale_listener  # it imports this module
        file_gale_listener.run()
        render()
    return 0


if __name__ == "__main__":
    sys.exit(main())
