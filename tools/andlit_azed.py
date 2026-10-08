#!/usr/bin/env python3
"""File the Observer's Azed from the Guardian's printable copies, found
through andlit.org.uk's Azed index.

    python3 tools/andlit_azed.py fetch [--limit N] [--budget-seconds S]   # download the next not yet cached
    python3 tools/andlit_azed.py file [--dry-run] [--numbers A-B] [--scan-seconds S]
    python3 tools/andlit_azed.py nightly [--budget-seconds S] [--scan-seconds S]   # fetch for S seconds, then file what is cached

andlit.org.uk's index (puzzles.php) lists Nos 1734-2757 and 2798-2799, each
behind puzzle_router.php, which redirects to the Guardian's own copy:

  * up to about No 1789, an HTML print page: the clues, and the grid as a
    table whose cells draw a bar as a 2px right or bottom border;
  * after that, a vector PDF: the clues as text, the grid as ruled lines
    (stroked paths up to ~2016, thin filled rectangles since), a bar a line
    several times thicker than the lattice, and the cell numbers as small type.
    The page also prints the previous puzzle's solution grid (smaller) and its
    notes, which are left out.

The grid's numbering must match the cell numbers printed in it and the clue
list light for light, and each enumeration must count its light, or the
puzzle is not filed. The answers are fifteensquared's (tools/azed_puzzles.py
caches its posts): the parsed record's numbered answers, else the answer the
post prints in each clue's place, else the crossings' letters, written into the
grid with every crossing agreeing. With no post, or one that leaves a light
unanswered, a plain puzzle files unsolved for the backfill to solve. A special
(andlit's index names it, or its preamble says more than which Chambers to
use) files only from an HTML page, whose preamble is read, with a post's
answers: a solver reading its clues cold would fill the grid wrongly. A scanned copy
(2006-08's PDFs are one page image) is read by the shared OCR vote and the
barred grid finder (read_scan), to a time budget. Numbers
already filed are left alone. A filing run over every number (no --dry-run or
--numbers) writes held.json, the cause each cached copy is not filed, which
tools/coverage.py reads.
"""
import argparse
import collections
import datetime
import hashlib
import html
import importlib.util
import io
import itertools
import json
import logging
import math
import re
import sys
import time
import urllib.error
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import azed_puzzles
import downloads
import fetch_fifteensquared as fsq
import file_blog_puzzles
import ft_pdf_puzzles as fpp
import listener_puzzles as lp
import reconstruct_grid as rg
from fetch_puzzle import (
    correct_source_answers,
    http_fetch,
    puzzle_path,
    write_puzzle_file,
)
from unit_queue import backlog_left

SERIES = "azed"
CACHE = downloads.ANDLIT_AZED
INDEX_URL = "https://www.andlit.org.uk/azed/puzzles.php"
ROUTER = "https://www.andlit.org.uk/azed/puzzle_router.php?src=L&puzzle_no={}"
GENERATOR = "tools/andlit_azed.py"
#: Seconds between requests: andlit and the Guardian's file servers are
#: fetched one page at a time.
PAUSE = 2.0

#: "<a href="puzzle_router.php?src=L&puzzle_no=2600" ...>2600</a></td><td ...>10 Apr 2022</td><td>Plain</td>"
INDEX_ROW = re.compile(r"puzzle_no=(\d+)\"[^>]*>\d+</a></td><td[^>]*>([^<]*)</td><td[^>]*>([^<]*)</td>")

#: {number: CAUSES key} of every cached copy the last filing run held,
#: which tools/coverage.py reads as the reason each is missing.
HELD = CACHE / "held.json"

#: The kinds of failure assemble() reports, so a run's tally reads as causes.
CAUSES = {
    "not-text": "the Guardian's copy is an image or missing, not text",
    "other-puzzle": "the copy is of another Azed",
    "grid-unread": "no lattice of ruled lines read off the page",
    "numbers-differ": "the grid's numbering differs from the numbers printed in it",
    "clues-differ": "the clue list does not clue the grid's lights",
    "enumeration": "an enumeration does not count its light",
    "special": "a special: its preamble is not read off a PDF, or no fifteensquared answers check it",
    "post-misses": "a special whose fifteensquared post leaves a light unanswered",
    "answers-disagree": "fifteensquared's answers cross wrongly in the printed grid",
    "refused-on-write": "puzzle_integrity refused the write",
    "scan-unread": "a scanned copy the OCR budget or an absent reader left unread this run",
    "ocr-blank": "a scanned copy whose OCR readings leave a clue unagreed",
    "scan-no-clues": "a scanned copy no reader reads a clue list off (the scan may stop short of it)",
}
CHAMBERS = re.compile(r"(?i)(?:special instructions:\s*)?(?:the\s+)?chambers dictionary \(\d{4}\)"
                      r" is recommended\.?")


def get(url):
    """(final url, bytes)."""
    return http_fetch(url, timeout=60)


# ------------------------------------------------------------------ the index

def index(refresh=False):
    """{number: (print date, kind)} from andlit's index, cached as index.html."""
    path = CACHE / "index.html"
    if refresh:
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(INDEX_URL)[1])
    if not path.exists():
        return {}
    out = {}
    for n, day, kind in INDEX_ROW.findall(path.read_text(encoding="utf-8", errors="replace")):
        day = html.unescape(day).replace("\xa0", " ").strip()
        try:
            date = datetime.date(*time.strptime(day, "%d %b %Y")[:3])
        except ValueError:
            date = None
        out[int(n)] = (date, html.unescape(kind).strip())
    return out


def cached(n):
    """The cached copy of No n: Path or None."""
    for ext in ("pdf", "html", "other"):
        p = CACHE / "copies" / f"{n}.{ext}"
        if p.exists():
            return p
    return None


def urls():
    path = CACHE / "urls.json"
    return {int(k): v for k, v in json.loads(path.read_text()).items()} if path.exists() else {}


def fetch(limit=None, budget_seconds=None, log=print, clock=time.monotonic):
    """Download the copies not yet cached of numbers not yet filed, oldest first;
    none is started once `budget_seconds` have passed. Returns how many the
    budget left unasked (a number that failed is asked again next run)."""
    nums = [n for n in sorted(index(refresh=True)) if cached(n) is None
            and not puzzle_path(SERIES, n).exists()]
    known, got, start = urls(), 0, clock()
    (CACHE / "copies").mkdir(parents=True, exist_ok=True)
    walk, unasked = nums[:limit], 0
    for i, n in enumerate(walk):
        if budget_seconds is not None and clock() - start >= budget_seconds:
            unasked = len(walk) - i
            break
        try:
            url, data = get(ROUTER.format(n))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                log(f"  No {n}: HTTP {e.code}")
                time.sleep(PAUSE)
                continue
            url, data = f"404 at {e.url}", b""
        except urllib.error.URLError as e:
            # The router sends a few numbers to an address with no host:
            # there is no copy, so the number is not asked for again.
            if "no host given" not in str(e.reason):
                log(f"  No {n}: {e.reason}")
                time.sleep(PAUSE)
                continue
            url, data = "the router redirects to no host", b""
        ext = "pdf" if data[:4] == b"%PDF" else "html" if b"<html" in data[:2000].lower() else "other"
        (CACHE / "copies" / f"{n}.{ext}").write_bytes(data)
        known[n] = url
        (CACHE / "urls.json").write_text(json.dumps({str(k): v for k, v in sorted(known.items())}, indent=0))
        got += 1
        time.sleep(PAUSE)
    log(f"fetched {got} Azed copies; {max(0, len(nums) - got)} still to fetch")
    return unasked


# ------------------------------------------------------------------ the HTML print pages

SQUARE = re.compile(r"<td[^>]*id=square([^>]*)>(.*?)</td>", re.DOTALL | re.IGNORECASE)


def read_html(text):
    """{"number", "preamble", "grid", "printed", "clues"} of a print page."""
    m = re.search(r"Azed Crossword No\.?\s*([\d,]+)", text)
    number = int(m.group(1).replace(",", "")) if m else None
    pre = re.search(r"Special instructions:\s*</B>(.*?)</font>", text, re.DOTALL | re.IGNORECASE)
    preamble = clean(pre.group(1)) if pre else ""
    grid, printed = [], {}
    for row_html in re.findall(r"<tr>(.*?)</tr>", text, re.DOTALL | re.IGNORECASE):
        cells = SQUARE.findall(row_html)
        if not cells:
            continue
        y, row = len(grid), ""
        for x, (attrs, inner) in enumerate(cells):
            right, below = "border-right" in attrs, "border-bottom" in attrs
            row += "+" if right and below else "r" if right else "b" if below else "."
            num = re.sub(r"<[^>]+>|&nbsp;", "", inner).strip()
            if num.isdigit():
                printed[(y, x)] = int(num)
        grid.append(row)
    grid = trim_edges(grid)
    lines = {"across": [], "down": []}
    for way, block in re.findall(r"<B>(Across|Down)</b>(.*?)</table>", text, re.DOTALL | re.IGNORECASE):
        for num, clue in re.findall(r"<B>(\d+)</B>.*?<TD[^>]*>(.*?)</TD>", block, re.DOTALL | re.IGNORECASE):
            lines[way.lower()].append(f"{num} {clean(clue)}")
    return {"number": number, "preamble": preamble, "grid": grid or None,
            "printed": printed, "lines": lines}


def clean(fragment):
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def trim_edges(grid):
    """A bar on the grid's outer edge is the frame, not a bar."""
    if not grid:
        return grid
    rows, cols = len(grid), len(grid[0])
    keep = {"+": ("r", "b"), "r": ("r", ""), "b": ("", "b"), ".": ("", "")}
    out = []
    for y, row in enumerate(grid):
        s = ""
        for x, c in enumerate(row):
            r, b = keep[c]
            r = r if x + 1 < cols else ""
            b = b if y + 1 < rows else ""
            s += "+" if r and b else r or b or "."
        out.append(s)
    return out


# ------------------------------------------------------------------ the PDFs

def segments(ops):
    """[(orientation "v"/"h", position, low, high, thickness)] of every
    axis-aligned line the page draws: a stroked path's segments at its line
    width, a filled rectangle thinner than 4pt at its thickness."""
    out = []

    def add_stroke(a, b, w):
        if abs(a[0] - b[0]) < 0.3 and abs(a[1] - b[1]) > 3:
            out.append(("v", a[0], min(a[1], b[1]), max(a[1], b[1]), w))
        elif abs(a[1] - b[1]) < 0.3 and abs(a[0] - b[0]) > 3:
            out.append(("h", a[1], min(a[0], b[0]), max(a[0], b[0]), w))

    def add_rect(x0, y0, x1, y1):
        dx, dy = x1 - x0, y1 - y0
        if dx < 4 and dy > 5:
            out.append(("v", (x0 + x1) / 2, y0, y1, dx))
        elif dy < 4 and dx > 5:
            out.append(("h", (y0 + y1) / 2, x0, x1, dy))

    def walk(ops, ctm):
        width, stack, path = 1.0, [], []

        def at(p):
            return (ctm[0] * p[0] + ctm[2] * p[1] + ctm[4], ctm[1] * p[0] + ctm[3] * p[1] + ctm[5])
        for operands, op in ops:
            if op == b"q":
                stack.append((ctm, width))
            elif op == b"Q" and stack:
                ctm, width = stack.pop()
            elif op == b"cm":
                ctm = fpp._mul([float(v) for v in operands], ctm)
            elif op == b"w":
                width = float(operands[0])
            elif op == b"Do":
                walk(operands[1], fpp._mul(operands[0], ctm))
            elif op == b"m":
                path.append((False, [at((float(operands[0]), float(operands[1])))]))
            elif op == b"l" and path:
                path[-1][1].append(at((float(operands[0]), float(operands[1]))))
            elif op == b"re":
                x, y, w, h = (float(v) for v in operands)
                path.append((True, [at((x, y)), at((x + w, y)), at((x + w, y + h)), at((x, y + h)), at((x, y))]))
            elif op in (b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"n"):
                scale = (abs(ctm[0]) + abs(ctm[3])) / 2
                for is_rect, pts in path:
                    if op in (b"S", b"s", b"B", b"B*", b"b", b"b*"):
                        for a, b in itertools.pairwise(pts):
                            add_stroke(a, b, width * scale)
                    if op in (b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*") and is_rect:
                        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                        add_rect(min(xs), min(ys), max(xs), max(ys))
                path = []
    walk(ops, [1, 0, 0, 1, 0, 0])
    return out


def _even(positions):
    """The positions, if they are a lattice: evenly spaced, 6 or more."""
    if len(positions) < 6:
        return None
    gaps = [b - a for a, b in itertools.pairwise(positions)]
    pitch = sum(gaps) / len(gaps)
    return positions if pitch > 6 and all(abs(g - pitch) < 0.15 * pitch for g in gaps) else None


def lattice(segs):
    """(xs, ys, thickness) of the page's largest grid: the set of full-length
    thin lines, vertical and horizontal, evenly spaced and spanning each other."""
    groups = []     # [orientation, width, low, high, [positions]]
    for o, pos, lo, hi, w in segs:
        if hi - lo <= 60 or w >= 1.0:
            continue
        for g in groups:
            if g[0] == o and abs(g[1] - w) < 0.05 and abs(g[2] - lo) < 3 and abs(g[3] - hi) < 3:
                g[4].append(pos)
                break
        else:
            groups.append([o, w, lo, hi, [pos]])
    best = None
    for o, w, lo, hi, pos in groups:
        xs = _even(lp._cluster(pos, 0.8)) if o == "v" else None
        if not xs:
            continue
        for o2, w2, lo2, hi2, pos2 in groups:
            ys = _even(lp._cluster(pos2, 0.8)) if o2 == "h" else None
            if not ys or abs(lo2 - xs[0]) > 3 or abs(hi2 - xs[-1]) > 3:
                continue
            if abs(lo - ys[0]) > 3 or abs(hi - ys[-1]) > 3:
                continue
            area = (xs[-1] - xs[0]) * (ys[-1] - ys[0])
            if best is None or area > best[0]:
                best = (area, xs, ys, round(min(w, w2), 2))
    return best and best[1:]


def read_bars(segs):
    """(grid rows, xs, ys) of the largest ruled grid, or None. A bar is a line
    on a lattice line at least twice the lattice's thickness, covering the
    middle of the edge between two cells."""
    found = lattice(segs)
    if not found:
        return None
    xs, ys, thin = found
    ys_down = sorted(ys, reverse=True)
    cols, rows = len(xs) - 1, len(ys) - 1
    pitch = (xs[-1] - xs[0]) / cols
    thick = [s for s in segs if s[4] >= 2 * thin and s[4] < pitch / 3]

    def barred(o, pos, mid):
        return any(s[0] == o and abs(s[1] - pos) < pitch / 6 and s[2] < mid < s[3] for s in thick)
    grid = []
    for y in range(rows):
        cy = (ys_down[y] + ys_down[y + 1]) / 2
        row = ""
        for x in range(cols):
            cx = (xs[x] + xs[x + 1]) / 2
            right = x + 1 < cols and barred("v", xs[x + 1], cy)
            below = y + 1 < rows and barred("h", ys_down[y + 1], cx)
            row += "+" if right and below else "r" if right else "b" if below else "."
        grid.append(row)
    return grid, xs, ys_down


def column_lines(runs, size, skip):
    """The page's lines of clue-sized type in reading order: columns left to
    right, each top to bottom. A column starts where a line's left edge sits
    60pt or more right of the last column's. `skip` drops runs by position."""
    runs = [r for r in runs if (abs(r[3] - size) < 0.6 or HEADING.match(r[4].strip()))
            and not skip(r[1], r[2])]
    starts = []
    for x in sorted(r[1] for r in runs):
        if not starts or x - starts[-1][-1] > 60:
            starts.append([x])
        else:
            starts[-1].append(x)
    edges = [s[0] for s in starts]
    cols = collections.defaultdict(lambda: collections.defaultdict(list))
    for _p, x, y, _s, t in runs:
        c = max(i for i, e in enumerate(edges) if e <= x + 0.1)
        cols[c][round(y)].append((x, t))
    out = []
    for c in sorted(cols):
        merged = []
        for y in sorted(cols[c], reverse=True):
            if merged and merged[-1][0] - y <= 1.5:
                merged[-1][1].extend(cols[c][y])
            else:
                merged.append((y, list(cols[c][y])))
        for y, parts in merged:
            out.append((c, y, re.sub(r"\s+", " ", " ".join(t for _x, t in sorted(parts))).strip()))
    return out


def read_pdf(data):
    """{"number", "preamble", "grid", "printed", "lines"} of a printable PDF."""
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    text, ops = fpp.ops_of(data)
    if not text.strip():
        return None     # a scan: the page is one image
    runs = lp.text_runs(data)
    title = next((t for _p, _x, _y, _s, t in runs if re.search(r"Azed\s+No\.?\s*[\d,]+", t)
                  and "solution" not in t.lower()), "")
    m = re.search(r"Azed\s+No\.?\s*(\d{1,2},?\d{3})", title)
    number = int(m.group(1).replace(",", "")) if m else None
    found = read_bars(segments(ops))
    if not found:
        return {"number": number, "preamble": "", "grid": None, "printed": {}, "lines": {}}
    grid, xs, ys = found
    printed = {}
    for _p, x, y, size, t in runs:
        if re.fullmatch(r"\d{1,3}", t.strip()) and xs[0] < x < xs[-1] and ys[-1] < y < ys[0]:
            cx = max(i for i in range(len(xs) - 1) if xs[i] <= x + 1)
            cy = max(i for i in range(len(ys) - 1) if ys[i] >= y - 1)
            printed.setdefault((cy, cx), t.strip())
    # Clue type is the size most of the page's letters are set in.
    sizes = collections.Counter()
    for _p, _x, _y, s, t in runs:
        sizes[round(s, 1)] += len(t.strip())
    size = sizes.most_common(1)[0][0] if sizes else 7.5
    lines = column_lines(runs, size, lambda x, y: xs[0] - 5 < x < xs[-1] + 5 and ys[-1] - 5 < y < ys[0] + 5)
    return {"number": number, "preamble": "", "title": title, "grid": grid,
            "printed": printed, "lines": sections(lines)}


def split_numbers(printed, starts):
    """{cell: number}. Two cell numbers side by side can come out of the
    text as one string ("89" on 8's cell where 9 starts the next): such a
    string is split when the grid's own numbering reads it so and the next
    cell holds no number of its own."""
    out = {}
    for (y, x), t in printed.items():
        a, b = starts.get((y, x)), starts.get((y, x + 1))
        if a is not None and b is not None and t == f"{a}{b}" and (y, x + 1) not in printed:
            out[(y, x)], out[(y, x + 1)] = a, b
        else:
            out[(y, x)] = int(t)
    return out


HEADING = re.compile(r"^(?:A\s*C\s*R\s*O\s*S\s*S|D\s*O\s*W\s*N)$", re.IGNORECASE)


def sections(lines):
    """{"across": [line...], "down": [...]}: each heading's lines, read on
    through the columns until the next heading. The previous puzzle's notes
    print "Across 1, ..." on one line, which is no heading."""
    out, way = {"across": [], "down": []}, None
    for _c, _y, t in lines:
        if HEADING.match(t):
            way = re.sub(r"\s", "", t).lower()
            continue
        if way:
            out[way].append(t)
    return out


# ------------------------------------------------------------------ the clues

CLUE_START = re.compile(r"^\*?(\d{1,2})\s*(?![\d,.;])(\S.*)$")
#: A count read glued to the clue's last word, its bracket unclosed:
#: "centrepiece(10,3words".
GLUED_COUNT = re.compile(r"\s*\((\d+),\s*(\d)\s*words?\)?\s*$")
ENUM_END = re.compile(r"\(([^()]*\d[^()]*)\)\s*$")


def clue_list(lines, wanted):
    """{(number, direction): clue text} read off each section's lines: a line
    opens a clue only when it starts with the next light the grid numbers in
    that direction, and a clue ends at its closing count, so the notes, form
    lines and footers between clues fall away."""
    out = {}
    for way in ("across", "down"):
        expect = sorted(n for n, d in wanted if d == way)
        current = None
        for line in lines.get(way, []):
            m = CLUE_START.match(line)
            if m and expect and int(m.group(1)) == expect[0]:
                current = (expect.pop(0), way)
                out[current] = m.group(2)
            elif current and not ENUM_END.search(out[current]):
                gap = "" if out[current].endswith("-") and not out[current].endswith(" -") else " "
                out[current] = f"{out[current]}{gap}{line}"
            if current and ENUM_END.search(out[current]) and not expect:
                current = None
    return {k: re.sub(r"\s+", " ", v).replace(" ,", ",").strip() for k, v in out.items()}


#: "(5, 2 words or 1)": the count, and its words.
LOOSE_WORDS = re.compile(r"\(\s*(\d{1,2})\s*,\s*\d\s+words?\s+or\s+\d\s*\)\s*$")


def entry_of(key, text, answers):
    """A clue record as tools/azed_puzzles.py's parser writes one."""
    text = LOOSE_WORDS.sub(r"(\1)", text)
    m = azed_puzzles.FIGURE_WORDS.search(text)
    if m and int(m.group(2)) in azed_puzzles.SPELT:
        text = f"{text[:m.start()].rstrip()} ({m.group(1)}, {azed_puzzles.SPELT[int(m.group(2))]} words)"
        enum = m.group(1)
    else:
        e = ENUM_END.search(text)
        enum = re.sub(r"\s", "", e.group(1)) if e else None
        if e and not re.fullmatch(r"\d+(?:[,\-]\d+)*", enum):
            enum = None
    return {"number": key[0], "direction": key[1], "answer": answers.get(key),
            "clue": text, "enumeration": enum}


# ------------------------------------------------------------------ filing

def blog_records():
    """{number: parsed fifteensquared record} for numbers one post claims."""
    path = azed_puzzles.CACHE / "parsed.jsonl"
    if not path.exists():
        return {}
    recs = [json.loads(line) for line in path.open(encoding="utf-8")]
    claims = collections.Counter(r["number"] for r in recs)
    return {r["number"]: r for r in recs if claims[r["number"]] == 1}


# ------------------------------------------------------------------ the scans

#: Voted readings of the scanned copies, one {number}.json each, keyed by the
#: copy's sha and SCAN_VERSION: bump it when the reading below changes.
SCAN_STORE = CACHE / "scans"
SCAN_VERSION = 4
#: The 2006-08 scans are ~750px wide, too small for the readers' detector:
#: upscaled 2x, the vote agrees on 32 of No 1820's 36 clues, not 21.
SCAN_SCALE = 2
#: How alike a clue on a light the grid lacks must be to a grid light's
#: clue to be its copy under a misread number (al.CORROBORATE).
PHANTOM_COPY = 0.7
FOOTER = re.compile(r"(?i)\s*the\s+chambers\s+dictionary\b.*$")


def page_image(path):
    """The copy's page as a PIL image: a scanned PDF's largest image, or the
    copy itself when the router served an image. None when it has neither."""
    from PIL import Image, UnidentifiedImageError
    data = path.read_bytes()
    if data[:4] != b"%PDF":
        try:
            return Image.open(io.BytesIO(data)).convert("RGB")
        except UnidentifiedImageError:
            return None
    import pypdf
    imgs = [i.image for page in pypdf.PdfReader(io.BytesIO(data)).pages[:1] for i in page.images]
    return max(imgs, key=lambda i: i.width * i.height).convert("RGB") if imgs else None


def can_ocr():
    """Whether a clue reader answers here: the desktop (OCR_REMOTE) or a local RapidOCR."""
    import ocr_remote
    return bool(ocr_remote.hosts()) or importlib.util.find_spec("rapidocr") is not None


def read_scan(path, number, ocr=True):
    """The copy dict assemble() takes, read off a scan by the shared clue vote
    (gale_listener.read_page: every ocr_clues reader, voted) and the barred
    grid finder (listener_grid, its bars fitted to the printed numbers), or
    None when the page holds no image, or "scan" when it is not stored and
    not `ocr`. "clues" maps each light to its voted
    text, "" where the readings do not agree; "printed" is the grid's own
    numbering only when every number read agrees with it."""
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    store = SCAN_STORE / f"{number}.json"
    if store.exists():
        got = json.loads(store.read_text())
        if got["sha"] == sha and got["version"] == SCAN_VERSION:
            return scan_copy(got)
    if not ocr:
        return "scan"
    img = page_image(path)
    if img is None:
        return None
    import gale_listener
    import listener_grid
    import numpy as np
    from PIL import Image
    img = img.resize((img.width * SCAN_SCALE, img.height * SCAN_SCALE), Image.LANCZOS)
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    grids = [g for g in listener_grid.find_grids(gray) if g["rows"]]
    # The page's own grid is the biggest; the previous solution's is smaller.
    grid = max(grids, key=lambda g: (g["box"][2] - g["box"][0]) * (g["box"][3] - g["box"][1]), default=None)
    rows, exact = None, False
    if grid:
        fitted = listener_grid.fit(grid, listener_grid.printed_numbers(gray, grid))
        rows, exact = fitted["rows"], fitted["exact"]
    # A grid whose numbers all fit counts each light, so a clue whose count
    # no reader read is voted on, not held.
    verdict, voted = gale_listener.read_page(img, f"azed-{sha[:16]}", lengths=light_lengths(rows) if exact else None)
    got = {"sha": sha, "version": SCAN_VERSION, "verdict": verdict, "rows": rows, "exact": exact,
           "clues": {k: [t, e] for k, (t, e, _g) in (voted or {}).items()}}
    SCAN_STORE.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(got))
    return scan_copy(got)


#: A scan's reader runs two words together where the print spaces them
#: ("maybeheard", "sendingback"): a word rarer than the lexicon's
#: RUN_TOGETHER_RANK (or not in it, and printed by the corpus's clues less
#: often than the pair) is two words when the corpus's clues print the pair
#: at least RUN_TOGETHER_PAIRS times; a word the lexicon holds only past
#: RUN_TOGETHER_RARE ("rulering", read for "ruler in") is two when it is
#: two of the lexicon's RUN_TOGETHER_COMMON commonest words and the corpus's
#: clues print that pair at all. A word the corpus's clues print whole
#: RUN_TOGETHER_SEEN times ("inbuilt") and a name the lexicon knows ("Notus")
#: are words. On the corpus's filed Azed clues
#: these trip 77 of 21,478, several of them misreads.
RUN_TOGETHER_RANK = 100_000
RUN_TOGETHER_PAIRS = 3
RUN_TOGETHER_RARE = 200_000
RUN_TOGETHER_COMMON = 10_000
RUN_TOGETHER_SEEN = 2


def run_together(word):
    """The two words ("maybe heard") a scan's reader ran together into
    `word`, else None: a capitalised word the lexicon holds is a name."""
    import ocr_clues
    low = word.lower()
    if len(low) < 4 or not low.isalpha():
        return None
    rank = ocr_clues.rank(low)
    if rank is not None and rank <= RUN_TOGETHER_RANK:
        return None
    if word[0].isupper() and ocr_clues.known(low):
        return None
    uni, pairs, _ = ocr_clues.clue_lm()
    seen = uni.get(low, 0)
    if seen >= RUN_TOGETHER_SEEN:
        return None
    for k in range(1, len(low)):
        a, b = low[:k], low[k:]
        if not (ocr_clues.is_word(a) and ocr_clues.is_word(b)):
            continue
        if pairs.get(f"{a} {b}", 0) >= max(RUN_TOGETHER_PAIRS, seen + 1):
            return f"{a} {b}"
        if (rank or 0) > RUN_TOGETHER_RARE and not seen and min(len(a), len(b)) >= 3 and pairs.get(f"{a} {b}") \
                and max(ocr_clues.rank(a) or math.inf, ocr_clues.rank(b) or math.inf) <= RUN_TOGETHER_COMMON:
            return f"{a} {b}"
    return None


def split_run(word):
    """`word` spaced where every reader ran two words together ("thesound",
    "Jackmaybe"), else None: only a token no lexicon holds and the corpus's
    clues never print, with one split alone into two words commoner than
    RUN_TOGETHER_COMMON the corpus prints as a pair RUN_TOGETHER_PAIRS
    times. A dropped g ("climbin", "Seein") is no pair."""
    import ocr_clues
    low = word.lower()
    if len(low) < 4 or not low.isalpha() or ocr_clues.known(low) or ocr_clues.clue_lm()[0].get(low) \
            or low.endswith("in") and ocr_clues.known(low + "g"):
        return None
    pairs = ocr_clues.clue_lm()[1]

    def common(w):
        return (ocr_clues.rank(w) or math.inf) <= RUN_TOGETHER_COMMON
    cuts = [k for k in range(1, len(low)) if common(low[:k]) and common(low[k:])
            and pairs.get(f"{low[:k]} {low[k:]}", 0) >= RUN_TOGETHER_PAIRS]
    return f"{word[:cuts[0]]} {word[cuts[0]:]}" if len(cuts) == 1 else None


def light_lengths(rows):
    """{"<n>-<across|down>": cells} of each light of `rows`, as the vote keys them."""
    return {f"{n}-{d}": len(cells) for (n, d), cells in rg.light_cells(rows).items()}


def scan_copy(got):
    """read_scan's stored reading as the copy dict assemble() takes."""
    rows = got["rows"]
    printed = {}
    if rows and got["exact"]:
        printed = {cells[0]: str(n) for (n, _d), cells in rg.light_cells(rows).items()}
    import ocr_clues
    lengths = {k: len(c) for k, c in rg.light_cells(rows).items()} if rows else {}
    clues = {}
    own = {k: (t or "").lower() for k, (t, _e) in got["clues"].items()
           if (int(k.split("-")[0]), k.split("-")[1]) in lengths}
    for key, (text, enum) in got["clues"].items():
        n, way = key.split("-")
        light = (int(n), way)
        if printed and light not in lengths and (not text or any(
                t and ocr_clues.similar(text.lower(), t) >= PHANTOM_COPY for t in own.values())):
            # A number the grid, whose numbers all fit, has no light for: a
            # misread one ("1" or "83" for 11 or 8). With no words, or the
            # words another light's clue has, it holds nothing back.
            continue
        text = FOOTER.sub("", text or "").strip()
        text = re.sub(r"[A-Za-z]+", lambda m: split_run(m.group(0)) or m.group(0), text)
        if enum and (m := GLUED_COUNT.search(text)) and m.group(1) == enum:
            # The voted count's words-tail run onto the clue's last word,
            # its bracket lost ("centrepiece(10,3words").
            text = f"{text[:m.start()].rstrip()} ({enum}, {m.group(2)} words)"
        if ENUM_END.search(text):
            enum = None     # the count stayed in the text
        elif not enum and light in lengths:
            enum = str(lengths[light])  # a lost count is the light's length
        ok = text and not ocr_clues.suspect(text) and not any(
            run_together(w) for w in re.findall(r"[A-Za-z'\u2019]+", text))
        clues[light] = f"{text} ({enum})" if ok and enum else text if ok else ""
    return {"number": None, "preamble": "", "title": "", "grid": rows, "printed": printed,
            "clues": clues}


def read(path, number=None, scans=True):
    """The copy dict of a cached copy. A scan not read before is read only
    when `scans` (else "scan" is returned, for the caller to hold)."""
    data = path.read_bytes()
    if path.suffix == ".html":
        return read_html(data.decode("utf-8", "replace"))
    if path.suffix == ".pdf":
        copy = read_pdf(data)
        if copy is not None:
            return copy
    if not data:
        return None
    return read_scan(path, number, ocr=scans)


def special(kind, copy):
    """Whether No n is a special: andlit's index names it ("‘Playfair’"),
    its PDF's title quotes a name, or its preamble says more than which
    Chambers to use."""
    return (kind not in ("", "Plain") or "‘" in copy.get("title", "")
            or bool(CHAMBERS.sub("", copy["preamble"] or "").strip(" .\n")))


def post_answers(post, entries, lights):
    """{light: answer} off the fifteensquared post: its parsed record's
    numbered answers where one fits its light, else the answer the post prints
    in that clue's place (ft_pdf_puzzles.blog_answers, walked with this copy's
    own clue list, so a light the parser misnumbered is still found)."""
    fits = {}
    for e in post["entries"]:
        key, word = (e["number"], e["direction"]), re.sub(r"[^A-Z]", "", (e.get("answer") or "").upper())
        if key in lights and len(word) == len(lights[key]):
            fits[key] = word
    if len(fits) < len(lights):
        raw = fsq.POSTS / f"{post['post_id'].removeprefix('fifteensquared-')}.json"
        if raw.exists():
            rendered = json.loads(raw.read_text(encoding="utf-8"))["content"]["rendered"]
            clues = [{"lights": [(e["number"], e["direction"])], "enumeration": e["enumeration"],
                      "clue": e["clue"]} for e in entries if e["enumeration"]]
            for key, word in fpp.blog_answers(rendered, clues).items():
                if key not in fits and len(word) == len(lights[key]):
                    fits[key] = word
    return fits


def fill_from_crossings(grid, entries):
    """Entries with each unanswered light written from its crossings, where
    the answered lights cover every one of its cells; None if the answered
    lights disagree at a cell or a light stays unfilled."""
    lights = rg.light_cells(grid)
    letters = {}
    for e in entries:
        if not e["answer"]:
            continue
        cells = lights[(e["number"], e["direction"])]
        word = re.sub(r"[^A-Z]", "", e["answer"].upper())
        if len(word) != len(cells):
            return None
        for c, ch in zip(cells, word):
            if letters.setdefault(c, ch) != ch:
                return None
    out = []
    for e in entries:
        if not e["answer"]:
            cells = lights[(e["number"], e["direction"])]
            if not all(c in letters for c in cells):
                return None
            e = dict(e, answer="".join(letters[c] for c in cells))
        out.append(e)
    return out


def assemble(number, copy, url, date, post, kind=""):
    """(puzzle, None) or (None, CAUSES key, detail)."""
    if copy is None:
        return None, "not-text", ""
    if copy["number"] not in (None, number):
        return None, "other-puzzle", f"it says No {copy['number']}"
    grid = copy["grid"]
    if not grid:
        return None, "grid-unread", ""
    lights = rg.light_cells(grid)
    starts = {cells[0]: n for (n, _d), cells in lights.items()}
    printed = split_numbers({k: str(v) for k, v in copy["printed"].items()}, starts)
    if printed != starts:
        return None, "numbers-differ", f"{len(set(printed.items()) ^ set(starts.items()))} cells"
    if "clues" in copy and not copy["clues"]:
        return None, "scan-no-clues", ""
    clues = copy["clues"] if "clues" in copy else clue_list(copy["lines"], set(lights))
    if blank := sorted(k for k in lights if k in clues and not clues[k]):
        return None, "ocr-blank", f"{len(blank)} clues, e.g. {blank[:3]}"
    if set(clues) != set(lights):
        return None, "clues-differ", f"unread {sorted(set(lights) - set(clues))[:3]}"
    if special(kind, copy) and not (post and copy["preamble"]):
        return None, "special", kind or copy.get("title", "")
    entries = [entry_of(k, clues[k], {}) for k in lights]
    if post:
        answers = post_answers(post, entries, lights)
        entries = [dict(e, answer=answers.get((e["number"], e["direction"]))) for e in entries]
    if post and any(not e["answer"] for e in entries):
        filled = fill_from_crossings(grid, entries)
        if filled is None and copy["preamble"]:
            return None, "post-misses", ""
        # Only the clues are mandatory: a plain puzzle whose post leaves
        # lights unanswered files unsolved, for the backfill to solve.
        entries = filled or [dict(e, answer=None) for e in entries]
        post = post if filled else None
    for e in entries:
        if e["enumeration"] is None or int(re.sub(r"\D.*", "", e["enumeration"]) or 0) and \
                sum(int(n) for n in re.findall(r"\d+", e["enumeration"])) != len(lights[(e["number"], e["direction"])]):
            return None, "enumeration", f"{e['number']} {e['direction']}"
    rec = {"post_id": post["post_id"] if post else f"andlit-{number}",
           "link": post["link"] if post else url, "date": post["date"] if post else None,
           "series": azed_puzzles.CATEGORY, "number": number, "setter": azed_puzzles.SETTER,
           "entries": entries}
    row = {"grid": grid, "number": number, "how": "andlit"}
    puzzle, why = file_blog_puzzles.build(rec, row, SERIES, date, azed_puzzles.SETTER)
    if why:
        return None, ("answers-disagree" if "disagree" in why else "clues-differ"), why
    pre = CHAMBERS.sub("", copy["preamble"] or "").strip()
    if pre:
        puzzle["preamble"] = pre
    puzzle["source"] = {"url": url, "gridOrigin": "published"}
    if post:
        puzzle["solutions"]["check"] = (
            "grid and clues read from the Guardian's printable copy, its numbering matching the "
            "numbers printed in it and the clue list; every fifteensquared answer written into "
            "it with each crossing agreeing")
    return puzzle, None, ""


def file(write=True, numbers=None, log=print, scan_seconds=None, clock=time.monotonic):
    """File every cached copy not yet in puzzles/; (filed, Counter of causes).
    A scan not yet read is read (read_scan) only while `scan_seconds` have
    not passed and a reader answers; one left unread calls backlog_left(),
    so the next tick reads on."""
    idx, where, posts = index(), urls(), blog_records()
    filed, held, why = [], collections.Counter(), {}
    start, ocr = clock(), can_ocr()
    for n in sorted(idx):
        if numbers and n not in numbers:
            continue
        path = cached(n)
        if path is None or puzzle_path(SERIES, n).exists():
            continue
        copy = read(path, n, scans=ocr and (scan_seconds is None or clock() - start < scan_seconds))
        if copy == "scan":
            held["scan-unread"] += 1
            why[n] = "scan-unread"
            continue
        puzzle, cause, detail = assemble(n, copy, where.get(n, ROUTER.format(n)), idx[n][0],
                                         posts.get(n), idx[n][1])
        if puzzle is None:
            held[cause] += 1
            why[n] = cause
            log(f"  No {n}: {CAUSES[cause]}{': ' + detail if detail else ''}")
            continue
        if write:
            try:
                if puzzle["solutions"].get("origin") != "unsolved":
                    correct_source_answers(puzzle["id"], puzzle["entries"])
                write_puzzle_file(puzzle_path(SERIES, n), puzzle, generator=GENERATOR)
            except ValueError as e:     # puzzle_integrity's write check
                held["refused-on-write"] += 1
                why[n] = "refused-on-write"
                log(f"  No {n}: refused on write: {str(e)[:160]}")
                continue
        filed.append(puzzle["id"])
    if held["scan-unread"] and ocr:
        backlog_left()
    if write and not numbers:
        HELD.write_text(json.dumps({str(k): v for k, v in sorted(why.items())}, indent=0))
    return filed, held


def number_range(text):
    a, _, b = text.partition("-")
    return set(range(int(a), int(b or a) + 1))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--limit", type=int)
    f.add_argument("--budget-seconds", type=float)
    g = sub.add_parser("file")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--numbers", type=number_range)
    h = sub.add_parser("nightly")
    h.add_argument("--budget-seconds", type=float)
    for p in (g, h):
        p.add_argument("--scan-seconds", type=float, help="stop reading new scans after this long")
    a = ap.parse_args(argv)
    if a.cmd in ("fetch", "nightly") and fetch(getattr(a, "limit", None), a.budget_seconds):
        backlog_left()
    if a.cmd in ("file", "nightly"):
        filed, held = file(write=not getattr(a, "dry_run", False), numbers=getattr(a, "numbers", None),
                           scan_seconds=a.scan_seconds)
        print(f"{'would file' if getattr(a, 'dry_run', False) else 'filed'} {len(filed)} Azed: "
              + " ".join(filed[:20]) + (" ..." if len(filed) > 20 else ""))
        for cause, k in held.most_common():
            print(f"  held {k}: {CAUSES.get(cause, cause)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
