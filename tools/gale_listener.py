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
saved puzzle has none. Each file is read once: STORE/ledger.jsonl is keyed
by the file's sha256 (and VERSION), one row appended a read, so a re-run
reads only files new or changed. The standing pass reads each new page as
a unit of its own (tools/edition_queue.py, plan() and read_unit(): its own
process, time limit and lock), planned every minute from the mirror the
every-3-minute gale_inbox tick keeps, so a page is read within minutes of
landing; `sync` does the same as one batch.

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
import itertools
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
VERSION = 11
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
                and w[0] < o[0] and o[0] - w[2] <= max(40, BESIDE * (w[3] - w[1]))
                and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < (w[3] - w[1]) for o in words):
            continue
        out.append(w)
    return out


def page_columns(words):
    """[across lines, down lines], each [(y0, y1, x0, x1, text)], for a page
    laid out any way: of headed_columns (both headings read) and
    numbered_columns, the one holding more numbered clue lines, headed_columns
    on a tie. Under a low ACROSS, headed_columns sees only the lists' first
    band (No 3's run on at the top of the next column)."""
    found = [c for c in (headed_columns(words), numbered_columns(words)) if c]
    return max(found, key=lambda c: sum(bool(al.LINE_CLUE.match(line[4])) for lst in c for line in lst), default=None)


def headings(words):
    """The words that are a list's heading alone on their line (ALONE): a
    report's prose quoting "for 1 Across (see notes)" heads no list."""
    return [w for w in words if fa.heading_of(w[4]) and not any(
        o is not w and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < (w[3] - w[1]) / 2
        and min(abs(o[0] - w[2]), abs(w[0] - o[2])) < ALONE for o in words)]


def list_heads(words):
    """(ACROSS, DOWN) heading words heading the lists, DOWN under ACROSS or
    in a column right of it; None without both."""
    heads = headings(words)
    across = al.heading_word(heads, "ACROSS")
    down = across and next((w for w in sorted(heads, key=lambda w: (w[0] // 200, w[1]))
                            if fa.heading_of(w[4]) == "DOWN"
                            and (w[1] > across[3] or w[0] > across[2])), None)
    return (across, down) if across and down else None


def lend_heads(words):
    """{reader: words} with a reading that misreads a list heading ("DOW",
    "OWN", "ACIOSS") given the headings another reading reads alone,
    its own words there replaced: a heading is the page's layout, no
    clue's text."""
    lent = next((p for w in words.values() if (p := list_heads(w))), None)
    if not lent:
        return words
    out = {}
    for k, w in words.items():
        if list_heads(w):
            out[k] = w
            continue
        out[k] = [o for o in w if not any(h[0] - 10 <= (o[0] + o[2]) / 2 <= h[2] + 10
                                           and h[1] - 10 <= (o[1] + o[3]) / 2 <= h[3] + 10 for h in lent)]
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
    # A DOWN level with ACROSS may be read a little above it.
    top = min(across[1], down[1]) - 20
    below = [w for w in words if (w[1] + w[3]) / 2 >= top]
    # A heading may be centred over its column (No 103's), its clue numbers
    # far left of it: the column starts where they line up.
    left = max((x for x in column_lefts(below) if across[0] - CENTRED <= x <= across[0]), default=across[0] - 40)
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
        if i and not any(al.LINE_CLUE.match(r[4]) or fa.heading_of(r[4]) for r in rows[:2]):
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
            head = fa.heading_of(line[4])
            if head:
                side = head
                continue
            lines[side].append(line)
        if al.END.match(lines[side][-1][4] if lines[side] else ""):
            break
    return [lines["ACROSS"], lines["DOWN"]] if lines["ACROSS"] and lines["DOWN"] else None


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
#: A list's footnote, under its last clue: "*One letter missing."
FOOTNOTE = re.compile(r"^\W{0,2}[*\u2020\u2021#]\s*[A-Z]")
#: A line ending its sentence: "Lenten.", "Why did this aspirated this?".
SENTENCE_END = re.compile(r"[.?!][\u2019'\")]?\s*$")
#: A clue's number stands within this of its column's left edge.
NUMBER_EDGE = 60
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
                          ) and not fa.heading_of(line[4]):
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
            under = (run and last_y is not None and line[0] - last_y < fa.GAP / 2 and line[2] > last_x + RUN_ON
                     and not fa.heading_of(line[4]) and not FOOTNOTE.match(line[4])
                     and line[1] - line[0] <= TALLER * (run[-1][1][-1][1] - run[-1][1][-1][0]))
            if m and line[2] - x0 < NUMBER_EDGE and WORDY.search(m.group(2)) and not fa.heading_of(line[4]):
                n = int(m.group(1))
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
    return lines if fa.heading_of(start[4]) == "ACROSS" else lines[::-1]


def notice_top(rows):
    """The top (y) of the first notice in a column's lines (`rows`,
    fa.merge_rows' (y0, y1, x0, x1, text)), or None: a line with NOTICE's
    words, with the lines just above it at the column's own pitch, the
    paragraph starting after a gap of over NOTICE_GAP pitches under a clue
    line (the preamble's "No prizes will be offered" is above the lists)
    and holding no clue number ("68 Essex Road," has no stop; "12. A
    prize" is a clue)."""
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
        if any(OPENS.match(r[4]) for r in rows[:top]) and not any(OPENS.match(r[4]) for r in rows[top:i + 1]):
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


#: A clue number in the 1930s' old-style figures, read as letters: "I."
#: for 1, "II." for 11, "Io." for 10, "I3." for 13 (No 97's, No 103's).
FIGURES = re.compile(r"^(\W{0,2})([IlO\d]?[IloO\d])([.,:])(?=\s|[A-Z]|$)")
AS_DIGIT = str.maketrans("IlOo", "1100")


#: A clue number run into its first word, as the "ch" reader drops the
#: space: "1.An African bird", or its stop and a dagger lost too: "29A town".
GLUED = re.compile(r"^(\W{0,2}\d{1,2}[.,:])(?=[A-Za-z*\u2020\u2021'\"\u2018\u201c])"
                   r"|^(\W{0,2}\d{1,2})(?=[A-Z][a-z]|[AI]\s)")
#: A footnote's dagger opening a clue ("28.\u2020Not far from 13"), read as
#: a small t or f run into the clue's capital ("tNot", "fA famous"), or
#: run into its number ("29tA town").
DAGGER = re.compile(r"^(\W{0,2}\d{1,2}[.,:]? ?)?[tf\u2020](?=[A-Z](?:[a-z]|\s|$))")


#: A clue number glued to "rev." (and to a linked light's number).
REV_GLUED = re.compile(r"^(\W{0,2}\d{1,2})\s*rev\.\s*(?:,\s*(\d{1,2})\.)?\s*")


def figures(words):
    """The words with a line's opening clue number read as letters put back
    in digits (a number cannot open on 0, so "O." and "Oo." stay words),
    parted from a first word run into it, and a footnote's dagger read as a
    letter (DAGGER) put back; a speck's box taller than a line goes, and a
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
        m = FIGURES.match(w[4])
        n = m and m.group(2).translate(AS_DIGIT)
        if m and n.isdigit() and n[0] != "0" and not m.group(2).isdigit():
            w = (*w[:4], m.group(1) + n + m.group(3) + w[4][m.end():])
        # A reversed light's number run into "rev." and its linked light's
        # ("20rev.,24.Charade:" for "20 rev., 24. Charade:").
        w = (*w[:4], REV_GLUED.sub(lambda m: f"{m.group(1)} rev." + (f", {m.group(2)}." if m.group(2) else "") + " ",
                                   w[4]).rstrip())
        w = (*w[:4], DAGGER.sub(lambda m: (m.group(1) or "").rstrip() + (" " if m.group(1) else "") + "\u2020",
                                GLUED.sub(lambda m: (m.group(1) or m.group(2)) + " ", w[4])))
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
ELSEWHERE = re.compile(r"\b(?:clues?|diagram|rules)\b[^.]{0,40}?\bpage\s+(\d{2,4})\b", re.IGNORECASE)


def elsewhere(words):
    """The magazine pages the page's words send its clues or diagram to."""
    return sorted({int(n) for n in ELSEWHERE.findall(" ".join(ocr_clues.lines_of(words).split()))})


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
    # A line any reading numbers is a line every RapidOCR reading reads; a
    # line one reads again alone may number one for the other, so twice.
    rapid = [w for w in ocr_clues.READERS if w not in ocr_clues.TESS_MODELS]
    for which in rapid * 2:
        words[which] = figures(reread_lines(img, key, which, [tuple(w) for w in words[which]],
                                            [located] + [words[o] for o in rapid if o != which]))
    words = lend_heads(words)
    if blanks := page_blanks(img, located):
        verdict["blanks"] = len(blanks)
        words = {k: ocr_clues.with_blanks(w, blanks) for k, w in words.items()}
    return al.vote(words, verdict, cols=page_columns, lengths=lengths)


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
    path.write_text(json.dumps(got))
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
        # The detector reads nothing in a crop much tighter than the line.
        box = (max(0, n[0] - h), max(0, n[1] - h // 2), min(img.width, x1 + h), min(img.height, n[3] + h // 2))
        # The number's own rows: lines set tighter than a number's box is
        # tall (No 97's 46A, 21 px apart) put the next line's centre within
        # a quarter height of it, and that line was taken and lost.
        band = (n[1], n[3])
        # Its number read as letters ("II." for 11) is a number, as figures reads it.
        got = sorted(figures([w for w in read_box(img, key, box, which) if band[0] <= (w[1] + w[3]) / 2 <= band[1]]),
                     key=lambda w: w[0])
        if not got or not (OPENS.match(got[0][4]) or re.fullmatch(r"\d{1,2}", got[0][4])):
            continue
        if got[0][4] == re.match(r"\W{0,2}(\d{1,2})", n[4]).group(1):
            # Read alone, a number often loses its stop ("8" for "8.").
            got[0] = (*got[0][:4], got[0][4] + ".")
        out = [w for w in out if not (box[0] <= (w[0] + w[2]) / 2 <= box[2] and band[0] <= (w[1] + w[3]) / 2 <= band[1])]
        out += got
    return out


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
    alike = verdict.get("asPrinted", {})
    suspects = {lid: s for lid, (t, _, _) in laid.items() if t and (s := ocr_clues.suspect(t, printed=alike.get(lid, ())))}
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
        "clues": {lid: {"text": t, "enumeration": e, **({"asPrinted": alike[lid]} if lid in alike else {}),
                        **({"group": grp} if grp else {})}
                  for lid, (t, e, grp) in laid.items()},
    }


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def read_one(p, h, idx, rows, store, out=sys.stdout, reader=read_file):
    """Read the saved file `p` (sha256 `h`), write its puzzle's reading to
    `store` when it is the fullest yet, and append its ledger row. Returns
    the entry, or None when the read timed out (not ledgered: read again)."""
    import scan_queue
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
        return None
    except Exception as e:  # noqa: BLE001 -- one page's failure must not stop the pages after it
        # Ledgered with its error, so the checklist shows it and the
        # pages after it are read; a VERSION bump reads it again.
        print(f"{p.name}: read failed:\n{traceback.format_exc()}", file=out)
        why = f"read failed: {type(e).__name__}: {e}"
        if m is None:
            m = {"file": p.name, "number": None, "why": why, "pages": [], "reports": []}
        verdict, laid = {"refused": why}, None
    entry.update(number=m["number"], how=m.get("how"), why=m.get("why"), reports=m["reports"])
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
                old = json.loads(dest.read_text()) if dest.exists() else None
                if old is None or old["verdict"].get("agreed", 0) <= verdict["agreed"]:
                    dest.write_text(json.dumps(reading(m, rows[m["number"]], verdict, laid), indent=1,
                                               ensure_ascii=False) + "\n")
                    entry["reading"] = dest.name
    scan_queue.append(store / LEDGER, [{"sha": h, **entry}])
    print(f"{p.name}: " + (f"No {m['number']} ({m['how']}), " if m["number"] is not None else "")
          + (f"{entry['agreed']}/{entry['clues']} clues read" if "agreed" in entry else entry["why"] or "")
          + "".join(f", the solution of No {n}" for n in m["reports"]), file=out)
    return entry


def page_files(inbox):
    return sorted(p for p in Path(inbox).iterdir() if p.is_file() and p.suffix.lower() in gi.PAGES) \
        if Path(inbox).exists() else []


_HASHES = {}


def hash_of(p):
    """file_hash(p), worked out again only when its size or mtime moved."""
    st = p.stat()
    key = (p.name, st.st_size, st.st_mtime_ns)
    if key not in _HASHES:
        _HASHES[key] = file_hash(p)
    return _HASHES[key]


def run(inbox=MIRROR, store=STORE, idx=None, out=sys.stdout, reader=read_file):
    """Read every file in `inbox` the ledger has not read at this VERSION;
    write each puzzle's reading to `store` (a fuller one replaces it).
    Returns the ledger."""
    idx = index() if idx is None else idx
    rows = {r["number"]: r for r in idx}
    store.mkdir(parents=True, exist_ok=True)
    ledger = load_ledger(store)
    for p in page_files(inbox):
        h = file_hash(p)
        if ledger.get(h, {}).get("version") == VERSION:
            continue
        entry = read_one(p, h, idx, rows, store, out, reader)
        if entry is not None:
            ledger[h] = entry
    return ledger


def plan(inbox=MIRROR, store=STORE):
    """The saved pages not read at this VERSION, one read unit each
    (tools/edition_queue.py), the earliest saved first: rank 0, saved by
    hand like the Gale Times pages."""
    ledger = load_ledger(store)
    todo = [p for p in page_files(inbox) if ledger.get(hash_of(p), {}).get("version") != VERSION]
    return [{"rel": p.name, "rank": 0, "reason": "saved by hand", "needs": []}
            for p in sorted(todo, key=lambda p: p.stat().st_mtime)]


def read_unit(name, inbox=MIRROR, store=STORE, reader=read_file, out=sys.stdout, file_it=True):
    """Read one saved page (tools/edition_queue.py's unit), under its own
    lock, its ledger row appended; then file what the readings now give
    (file_gale_listener.run, one at a time) and publish the checklist.
    Returns "read", "current", "busy" or "failed" (its OCR timed out)."""
    import scan_queue
    p = Path(inbox) / name
    if not p.exists():
        return "current"
    h = file_hash(p)
    store.mkdir(parents=True, exist_ok=True)
    with scan_queue.source_lock(store / LEDGER, h) as mine:
        if not mine:
            return "busy"
        if load_ledger(store).get(h, {}).get("version") == VERSION:
            return "current"
        idx = index()
        if read_one(p, h, idx, {r["number"]: r for r in idx}, store, out, reader) is None:
            return "failed"
    if file_it:
        import file_gale_listener  # it imports this module
        with scan_queue.lock(store / "filing", wait_for_it=True):
            file_gale_listener.run(store, inbox, out=out)
            render(idx, out=out)
    return "read"


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


def arrivals(out=sys.stdout):
    """Mirror the Listener inbox and publish its status file; whether it
    moved. gale_inbox.sync runs this before any Gale lookup, so an open
    page hears of an arrival without waiting on them."""
    changed = gi.mirror(out, host_inbox=gi.LISTENER_INBOX, into=MIRROR)
    gi.publish_status(CHECKLIST)
    return changed


def tick(out=sys.stdout, force=False, ask=True, until=None, changed=False):
    """The every-minute part (gale_inbox.sync calls it, after arrivals,
    whose `changed` it passes): when the inbox moved (or gi.RENDER_EVERY
    passed), re-render the checklist; publish its status file either way.
    Gale is asked for links only when `ask` (gale_inbox.gale_due), none
    started after the monotonic time `until`. The clue reading stays in the
    full pass."""
    idx = index()
    linked = ask and gale_docs.resolve("LSNR", [(r["date"], r["number"]) for r in to_save(idx)], out,
                                       reports=[(r["date"], r["number"]) for r in report_lookups(idx)],
                                       until=until)
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
    """{number} of the puzzles a page in the inbox, read or not, or a saved
    page reports on."""
    arrivals = list(gi.load(ARRIVED, {}).values()) if arrivals is None else arrivals
    return {n for e in [*load_ledger(store).values(), *arrivals] for n in e.get("reports") or ()}


def unsolved(idx, store=STORE, arrivals=None):
    """The printed puzzles saved whose report page has not arrived."""
    solved = solutions(store, arrivals)
    saved = {e["number"] for e in load_ledger(store).values() if e.get("number") is not None} | {
        json.loads(p.read_text())["number"] for p in store.glob("listener-*.json")}
    return [r for r in idx if printed(r) and r["number"] in saved - solved]


def report_lookups(idx, store=STORE, root=ROOT, arrivals=None):
    """The rows whose report link Gale is asked for, earliest first: every
    saved puzzle and every one still to save (the rows that get a Download
    link) whose report page has not arrived."""
    arrivals = list(gi.load(ARRIVED, {}).values()) if arrivals is None else arrivals
    want = {r["number"] for r in [*unsolved(idx, store, arrivals), *to_save(idx, store, root, arrivals)]}
    want -= solutions(store, arrivals)  # once: per row it re-read the ledger ~3,000 times (55 s)
    return [r for r in idx if printed(r) and r["number"] in want]


def elsewhere_wanted(ledger, got, arrivals, filed):
    """{number: [page]} of the puzzles not filed whose one saved page sends
    its clues or diagram to another page of the issue ("For clues see page
    1057"), the ledger's or reading's seePages: no puzzle files without
    both. A second file of the puzzle saved is taken for that page."""
    pages, files = {}, {}
    for e in [*ledger.values(), *arrivals]:
        if e.get("number") is not None:
            files.setdefault(e["number"], set()).add(e["file"])
    for n, see in [*((e.get("number"), e.get("seePages")) for e in ledger.values()),
                   *((n, v.get("seePages")) for n, v in got.items())]:
        if n is not None and see:
            pages.setdefault(n, set()).update(see)
    return {n: sorted(ps) for n, ps in pages.items() if n not in filed and len(files.get(n, ())) < 2}


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
#: What the checklist says of a file whose puzzle the tick could not name.
UNKNOWN = ("arrived, puzzle not yet known: the name and citation name no puzzle, and the full pass reads the title"
           " at its next slice")


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
    solved = solutions(store, arrivals)
    got = {}
    for p in store.glob("listener-*.json"):
        r = json.loads(p.read_text())
        got[r["number"]] = r["verdict"]
    idx = [r for r in idx if printed(r)]
    todo = to_save(idx, store, root, arrivals)
    read = {e_["file"] for e_ in ledger.values()}
    asks = {r["number"] for r in unsolved(idx, store, arrivals)}
    sends = elsewhere_wanted(ledger, got, arrivals, filed)

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
        if n in sends:
            pages = ", ".join(map(str, sends[n]))
            status.append((f"save p. {pages} of this issue too: the page sends its clues or diagram there", "bad"))
        if n in solved:
            status.append(("solution saved", "got"))
        elif n in asks:
            about = r["date"] + datetime.timedelta(days=14)
            status.append((f"save its solution too: “Report on Crossword No. {n}”, about {about:%d %b %Y}", "bad"))
        out = {"date": r["date"], "search": gale_docs.permalink("LSNR", r["date"], docs) or gi.search_url(r["date"], "LSNR"),
               "status": status,
               "cells": [str(n), r["title"], r.get("setter") or ""]}
        if n in sends:
            # The other page is a document of its own: the issue's search finds it.
            out.update(key=f"e{n}", dl=None)
        elif n in asks:
            out.update(key=f"r{n}", dl=gale_docs.report_link("LSNR", n, docs), label="Download solution")
        elif n not in filed and n not in got:
            report = None if n in solved else gale_docs.report_link("LSNR", n, docs)
            out.update(key=f"p{n}", dl=gale_docs.link("LSNR", r["date"], docs), arrived=n in came or n in tried,
                       more=[("Download solution", report)] if report else [])
        return out

    want = asks | set(sends) | {r["number"] for r in todo}
    held = filed | set(got) | came
    years = {}
    for r in idx:
        years.setdefault(r["date"].year, []).append(r)
    return gi.page(
        paper="Listener", prod="LSNR", name=CHECKLIST_NAME, store="listenerCopied", done=len(arrivals),
        total=len(arrivals) + len(todo), done_word="files downloaded", folder=gi.SHARE + "\\Listener",
        notes=[(a["file"], UNKNOWN) for a in unnamed if a["file"] not in read]
              + [(m["file"], f"matched no puzzle ({m.get('why') or ''}); left in the inbox") for m in lost],
        steps=STEPS,
        order=ORDER, what="pages", next_rows=[row(r) for r in idx if r["number"] in want],
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
        import scan_queue
        with scan_queue.lock(STORE / "filing", wait_for_it=True):
            file_gale_listener.run()
            render()
    return 0


if __name__ == "__main__":
    sys.exit(main())
