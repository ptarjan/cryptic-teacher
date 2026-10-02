#!/usr/bin/env python3
"""File the Financial Times cryptic from the FT's own printable PDFs.

    python3 tools/ft_pdf_puzzles.py index              # list every PDF Wayback knows of
    python3 tools/ft_pdf_puzzles.py orphans            # and the PDFs no page links
    python3 tools/ft_pdf_puzzles.py fetch [--limit N]  # download them
    python3 tools/ft_pdf_puzzles.py file [--limit N] [--dry-run] [--numbers A-B]

From 2006 to 2012 www.ft.com/arts/crossword linked each day's puzzle as a PDF
on media.ft.com ("June 15 2010: Puzzle 13,412"). Wayback holds the page, and
media.ft.com still serves many of the PDFs; where it answers 403, Wayback's own
copy of the PDF is tried. The PDF is text, not a scan: pypdf reads the clue
list, and the grid is vector art (a white square, then one filled rectangle per
black cell) read straight out of the page's content stream, so the black
squares are the FT's own.

The answers are fifteensquared's: its write-ups of these years print the light
number and the answer but seldom the clue. Each light the PDF lists is looked
up under its number in the post, and its answer is the run of capitals the
PDF's enumeration counts word for word. The answers are filed only when every
light has one and every answer writes into the PDF's grid with each crossing
agreeing; otherwise the puzzle files unsolved, because only the clues are
mandatory and the nightly backfill solves it. The grid's own numbering must
match the PDF's clue numbers and enumerations first, which checks the geometry
independently of the blog.

Three steps, each reading the one before off disk, so a run killed anywhere
resumes: index.json, then pdf/<number>.pdf, then puzzles/.
"""
import argparse
import collections
import datetime
import html
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import fetch_fifteensquared as fsq
import file_blog_puzzles
import ft_puzzles
import parse_timesforthetimes as tftt
import puzzle_integrity
import reconstruct_grid as rg
import times_grids as tg
from fetch_puzzle import correct_source_answers, puzzle_path, write_puzzle_file

SERIES = "ftcryptic"
CACHE = Path.home() / "cryptic-setter-data" / "ft-pdf"
INDEX = CACHE / "index.json"
PDFS = CACHE / "pdf"
LEDGER = CACHE / "attempts.jsonl"
GENERATOR = "tools/ft_pdf_puzzles.py"
#: The acquirer a puzzle names when its PDF came from Wayback, not media.ft.com.
GENERATOR_WAYBACK = "tools/ft_pdf_puzzles.py --wayback"
UA = {"User-Agent": "Mozilla/5.0 (cryptic-teacher; github.com/ptarjan/cryptic-teacher)"}
CDX = "https://web.archive.org/cdx/search/cdx"
PAGES = ("ft.com/arts/crossword", "www.ft.com/arts/crossword*")
#: Seconds between Wayback requests; faster than this it starts refusing.
WAYBACK_PAUSE = 2

#: "June 15 2010: Puzzle 13,412". Until 2009 the link is to an article page
#: (/cms/s/2/<id>.html) that carries the PDF's link; from 2010, to the PDF.
#: The Polymath and the weekend specials are their own numbering and are not
#: listed.
LINK = re.compile(r'href="(?:https?://web\.archive\.org/web/\d+/)?((?:https?://[a-z.]*ft\.com(?::80)?)?'
                  r'/cms/[^"]+?\.(?:pdf|html))"[^>]*>\s*([A-Z][a-z]+ \d{1,2},? \d{4})\s*:\s*'
                  r'Puzzle\s+(?:No\.?\s*)?(\d{1,2},?\d{3})\s*<')
PDF_IN_PAGE = re.compile(r'(?:https?://media\.ft\.com)?/cms/[0-9a-f\-]{36}\.pdf')


# ------------------------------------------------------------------ http

def get(url, timeout=60, tries=3):
    """The bytes at url; raises the last error. Wayback rate-limits with 429
    and drops connections, so both are retried after a pause."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                        timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if i == tries - 1:
                raise
        # Wayback refuses connections outright for a while once pressed.
        time.sleep(30 * (i + 1))
    raise AssertionError("unreachable")


# ------------------------------------------------------------------ index

def page_links(page_html):
    """[(number, print date ISO, pdf url)] linked from one crossword page."""
    out = []
    for url, day, number in LINK.findall(page_html):
        try:
            d = datetime.datetime.strptime(day.replace(",", ""), "%B %d %Y").date()
        except ValueError:
            continue
        url = url.replace(":80/", "/")
        if url.startswith("/"):
            url = "http://www.ft.com" + url
        out.append((int(number.replace(",", "")), d.isoformat(), url))
    return out


def captures():
    """Every distinct Wayback capture of the crossword page: [(timestamp, url)]."""
    seen, out = set(), []
    for page in PAGES:
        rows = json.loads(get(f"{CDX}?url={page}&output=json&filter=statuscode:200"
                              f"&collapse=digest&limit=20000", timeout=180) or b"[]")
        for ts, orig in ((r[1], r[2]) for r in rows[1:]):
            if (ts, orig) not in seen:
                seen.add((ts, orig))
                out.append((ts, orig))
    return sorted(out)


def index(log=print):
    """Read every capture into index.json: {number: {date, url}}. Captures
    already read are skipped on a rerun."""
    CACHE.mkdir(parents=True, exist_ok=True)
    idx = json.loads(INDEX.read_text()) if INDEX.exists() else {"puzzles": {}, "read": []}
    done = set(idx["read"])
    caps = captures()
    log(f"{len(caps)} capture(s) of the crossword page, {len(done)} already read")
    for ts, orig in caps:
        key = f"{ts} {orig}"
        if key in done:
            continue
        try:
            page = get(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=90).decode("utf-8", "replace")
        except Exception as e:                    # one dead capture is one capture
            log(f"  {ts}: {type(e).__name__}: {e}")
            continue
        time.sleep(WAYBACK_PAUSE)
        for number, day, url in page_links(page):
            idx["puzzles"].setdefault(str(number), {"date": day, "url": url})
        idx["read"].append(key)
        INDEX.write_text(json.dumps(idx, indent=0, sort_keys=True))
    log(f"index: {len(idx['puzzles'])} puzzle PDF(s)")
    return idx


# ------------------------------------------------------------------ orphans

def media_pdfs():
    """[(timestamp, url)] of every pre-2013 media.ft.com PDF Wayback holds at a
    crossword's size (20 to 300 kB). The CDX reply can be cut short, so it is
    read line by line, one year at a time."""
    out = {}
    for year in range(2006, 2013):
        try:
            text = get(f"{CDX}?url=media.ft.com/cms/*&output=json&filter=mimetype:application/pdf"
                       f"&filter=statuscode:200&collapse=urlkey&from={year}&to={year}&limit=20000",
                       timeout=300).decode("utf-8", "replace")
        except Exception as e:
            print(f"  CDX {year}: {type(e).__name__}: {e}")
            continue
        for ln in text.splitlines():
            try:
                r = json.loads(ln.strip().rstrip(","))
            except ValueError:
                continue
            if isinstance(r, list) and len(r) > 6 and r[0] != "urlkey" and r[6].isdigit() \
                    and 20_000 < int(r[6]) < 300_000:
                out.setdefault(r[2].replace(":80/", "/"), r[1])
        time.sleep(WAYBACK_PAUSE)
    return sorted((ts, u) for u, ts in out.items())


def orphans(log=print):
    """Fetch the PDFs no indexed crossword page links (2007-09, whose pages
    linked article pages Wayback mostly lacks) and index each under the number
    its own header prints, undated."""
    idx = json.loads(INDEX.read_text())
    known = {v["url"] for v in idx["puzzles"].values()}
    seen_file = CACHE / "orphans_seen.json"
    seen = set(json.loads(seen_file.read_text())) if seen_file.exists() else set()
    rows = [r for r in media_pdfs() if r[1] not in known and r[1] not in seen]
    log(f"orphans: {len(rows)} unindexed media.ft.com PDF(s) to open")
    PDFS.mkdir(parents=True, exist_ok=True)
    got = 0
    for ts, url in rows:
        try:
            data = get(f"https://web.archive.org/web/{ts}id_/{url}", timeout=60, tries=2)
            number = parse_clues(ops_of(data)[0])["number"] if data[:5] == b"%PDF-" else None
        except Exception as e:
            log(f"  {url}: {type(e).__name__}")
            continue
        finally:
            time.sleep(WAYBACK_PAUSE)
        seen.add(url)
        seen_file.write_text(json.dumps(sorted(seen)))
        held = idx["puzzles"].get(str(number))
        # An entry pointing at an article page Wayback lacks takes the PDF,
        # keeping the day the crossword page printed beside it.
        if not number or pdf_path(number).exists() or (held and not held["url"].endswith(".html")):
            continue
        pdf_path(number).write_bytes(data)
        (PDFS / f"{number}.how").write_text("wayback")
        idx["puzzles"][str(number)] = {"date": held and held.get("date"), "url": url}
        INDEX.write_text(json.dumps(idx, indent=0, sort_keys=True))
        got += 1
        log(f"  {number}: {url}")
    log(f"orphans: {got} new puzzle PDF(s)")
    return got


def neighbour_date(n, idx):
    """An undated number's print day, when the dated numbers either side of it
    are so close that the printing days between them are exactly the numbers
    between them; else None."""
    dated = {int(k): datetime.date.fromisoformat(v["date"]) for k, v in idx.items() if v.get("date")}
    lo = max((k for k in dated if k < n), default=None)
    hi = min((k for k in dated if k > n), default=None)
    if lo is None or hi is None or hi - lo > 12:
        return None
    days, d = [], dated[lo] + datetime.timedelta(days=1)
    while d < dated[hi]:
        if ft_puzzles.printing_day(d):
            days.append(d)
        d += datetime.timedelta(days=1)
    return days[n - lo - 1] if len(days) == hi - lo - 1 else None


# ------------------------------------------------------------------ fetch

def pdf_path(number):
    return PDFS / f"{number}.pdf"


def pdf_of_page(page):
    """(media.ft.com PDF url, None) linked from an article page, or (None, why)."""
    try:
        text = get(f"https://web.archive.org/web/2012id_/{page}", timeout=60, tries=2).decode("utf-8", "replace")
    except Exception as e:
        return None, f"article page: {getattr(e, 'code', type(e).__name__)}"
    m = PDF_IN_PAGE.search(text)
    if not m:
        return None, "article page links no PDF"
    u = m.group(0)
    return (u if u.startswith("http") else "http://media.ft.com" + u), None


def fetch_one(number, url):
    """(path or None, how): media.ft.com first, then Wayback's copy."""
    PDFS.mkdir(parents=True, exist_ok=True)
    if url.endswith(".html"):
        url, why = pdf_of_page(url)
        if url is None:
            return None, why
    tries = [("live", url), ("wayback", f"https://web.archive.org/web/2012id_/{url}")]
    why = []
    for how, u in tries:
        try:
            data = get(u, timeout=60, tries=2)
        except Exception as e:
            why.append(f"{how}: {getattr(e, 'code', type(e).__name__)}")
            continue
        if data[:5] != b"%PDF-":
            why.append(f"{how}: not a PDF")
            continue
        pdf_path(number).write_bytes(data)
        (PDFS / f"{number}.how").write_text(how)
        return pdf_path(number), how
    return None, "; ".join(why)


def fetch(limit=None, numbers=None, log=print):
    idx = json.loads(INDEX.read_text())["puzzles"]
    todo = sorted((int(n) for n in idx), reverse=True)
    if numbers:
        todo = [n for n in todo if numbers[0] <= n <= numbers[1]]
    failed = json.loads((CACHE / "fetch_failed.json").read_text()) \
        if (CACHE / "fetch_failed.json").exists() else {}
    got = 0
    for n in todo:
        if pdf_path(n).exists() or str(n) in failed:
            continue
        if limit is not None and got >= limit:
            break
        path, how = fetch_one(n, idx[str(n)]["url"])
        if path:
            got += 1
        else:
            failed[str(n)] = how
            (CACHE / "fetch_failed.json").write_text(json.dumps(failed, indent=0))
        log(f"  {n}: {how}")
    log(f"fetched {got}; {len(failed)} unreachable")
    return got


# ------------------------------------------------------------------ the PDF

def ops_of(path_or_bytes):
    """(text, [(operands, operator)]) of a one-page PDF, Form XObjects inlined
    as ("Do", matrix, ops) so the grid reader sees their rectangles too."""
    import pypdf
    from pypdf.generic import ContentStream
    data = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
    reader = pypdf.PdfReader(io.BytesIO(data))
    page = reader.pages[0]

    def flatten(stream, resources, depth=0):
        out = []
        xobjects = (resources or {}).get("/XObject") or {}
        spaces = (resources or {}).get("/ColorSpace") or {}
        for operands, op in ContentStream(stream, reader).operations:
            if op == b"cs" and operands:
                out.append(([ink_space(spaces, operands[0])], b"cs"))
                continue
            if op == b"Do" and depth < 3 and operands and operands[0] in xobjects:
                xo = xobjects[operands[0]].get_object()
                if xo.get("/Subtype") == "/Form":
                    m = [float(v) for v in xo.get("/Matrix", [1, 0, 0, 1, 0, 0])]
                    out.append(([m, flatten(xo, xo.get("/Resources") or resources, depth + 1)],
                                b"Do"))
                continue
            out.append((operands, op))
        return out
    contents = page.get_contents()
    ops = flatten(contents, page.get("/Resources"), 0) if contents is not None else []
    return page.extract_text() or "", ops


def ink_space(spaces, name):
    """Whether colour space `name` paints ink, a tint of 1 the darkest: a
    /Separation or /DeviceN space ("/Black", No 13,909 on). The device spaces
    and the rest paint light, 1 the lightest."""
    try:
        space = spaces[name].get_object() if name in spaces else name
        family = space[0] if isinstance(space, list) else space
    except Exception:  # noqa: BLE001 — an unreadable space is not ink
        return False
    return family in ("/Separation", "/DeviceN")


def _mul(a, b):
    """The affine product a·b, PDF order [a b c d e f]."""
    return [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]]


def _brightness(operands):
    v = [float(x) for x in operands if isinstance(x, (int, float)) or hasattr(x, "as_numeric")]
    if len(v) == 1:
        return v[0]
    if len(v) == 3:
        return sum(v) / 3
    if len(v) == 4:
        return (1 - v[3]) * (1 - sum(v[:3]) / 3)
    return None


def filled_rects(ops):
    """[(x0, y0, x1, y1, dark)] of every filled rectangle, in page space."""
    out = []

    def box(pts, ctm):
        pts = [(ctm[0] * px + ctm[2] * py + ctm[4], ctm[1] * px + ctm[3] * py + ctm[5])
               for px, py in pts]
        return (min(p[0] for p in pts), min(p[1] for p in pts),
                max(p[0] for p in pts), max(p[1] for p in pts))

    def walk(ops, ctm):
        fill, ink, stack, path, poly = 0.0, False, [], [], []
        for operands, op in ops:
            if op == b"q":
                stack.append((ctm, fill, ink))
            elif op == b"Q" and stack:
                ctm, fill, ink = stack.pop()
            elif op == b"cm":
                ctm = _mul([float(v) for v in operands], ctm)
            elif op == b"cs":
                ink = bool(operands and operands[0] is True)
            elif op in (b"g", b"k", b"rg"):
                ink = False
                b = _brightness(operands)
                fill = fill if b is None else b
            elif op in (b"sc", b"scn"):
                b = _brightness(operands)
                if b is not None:
                    fill = 1 - b if ink and len(operands) == 1 else b
            elif op == b"re":
                x, y, w, h = (float(v) for v in operands)
                path.append(box([(x, y), (x + w, y + h)], ctm))
            elif op == b"m":
                poly = [tuple(float(v) for v in operands)]
            elif op == b"l" and poly:
                poly.append(tuple(float(v) for v in operands))
            elif op in (b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"):
                # A closed four-cornered path whose sides run along the axes
                # is a rectangle drawn with lines: some PDFs draw blocks so.
                if len(poly) == 4 and all(
                        a[0] == b[0] or a[1] == b[1]
                        for a, b in zip(poly, poly[1:] + poly[:1])):
                    path.append(box(poly, ctm))
                out.extend((*r, fill < 0.5) for r in path)
                path, poly = [], []
            elif op in (b"n", b"S", b"s"):
                path, poly = [], []
            elif op == b"Do":
                m, inner = operands
                walk(inner, _mul(m, ctm))
    walk(ops, [1, 0, 0, 1, 0, 0])
    return out


def lattice(frame, size, cells, tol=1.0):
    """The side in cells: the largest n from 5 to 27 whose lattice holds every
    block inside one of its cells. A finer lattice splits a block across two;
    a coarser one that also fits is the same grid at a multiple, not finer."""
    side = frame[2] - frame[0]
    for n in range(27, 4, -1):
        pitch = side / n
        if size > pitch * 1.02:
            continue
        if all((r[0] - frame[0] + tol) // pitch == (r[2] - frame[0] - tol) // pitch
               and (frame[3] - r[3] + tol) // pitch == (frame[3] - r[1] - tol) // pitch
               for r in cells):
            return n
    return None


def ruled_frame(rects):
    """The square the grid's ruled lines enclose, as a white frame, when the
    PDF draws the grid as thin filled bars and no square behind it (No
    13,909 on): the bounding box of the long bars, if it is square."""
    bars = [r for r in rects if min(r[2] - r[0], r[3] - r[1]) < 2
            and max(r[2] - r[0], r[3] - r[1]) >= 100]
    across = [r for r in bars if r[2] - r[0] > r[3] - r[1]]
    down = [r for r in bars if r[3] - r[1] > r[2] - r[0]]
    if len(across) < 6 or len(down) < 6:
        return None
    x0, x1 = min(r[0] for r in down), max(r[2] for r in down)
    y0, y1 = min(r[1] for r in across), max(r[3] for r in across)
    if abs((x1 - x0) - (y1 - y0)) > 0.02 * (x1 - x0):
        return None
    return (x0, y0, x1, y1, False)


def read_grid(rects):
    """The grid ["..#..", ...] the rectangles draw, or None.

    The frame is the largest square; its cells are the dark squares inside it
    of one common size, and the side in cells is lattice()'s. A grid drawn
    twice on the page (some PDFs carry a second, hidden copy) is one grid:
    cells are a set."""
    squares = [r for r in rects if (r[2] - r[0]) > 1 and abs((r[2] - r[0]) - (r[3] - r[1])) < 0.02 * (r[2] - r[0])]
    frame = ruled_frame(rects)
    if frame:
        squares.append(frame)
    if not squares:
        return None
    frame = max(squares, key=lambda r: r[2] - r[0])
    side = frame[2] - frame[0]
    if side < 100:
        return None
    inside = [r for r in squares if r is not frame and r[0] >= frame[0] - 0.5 and r[2] <= frame[2] + 0.5
              and r[1] >= frame[1] - 0.5 and r[3] <= frame[3] + 0.5 and (r[2] - r[0]) < side / 4]
    dark = [r for r in inside if r[4]] if not frame[4] else [r for r in inside if not r[4]]
    if not dark:
        return None
    size = collections.Counter(round(r[2] - r[0], 1) for r in dark).most_common(1)[0][0]
    cells = [r for r in dark if abs((r[2] - r[0]) - size) < 0.5]
    n = lattice(frame, size, cells)
    if n is None:
        return None
    pitch = side / n
    marked = set()
    for r in cells:
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        marked.add((int((frame[3] - cy) // pitch), int((cx - frame[0]) // pitch)))
    if frame[4]:   # white lights drawn on a black square
        return ["".join("." if (y, x) in marked else "#" for x in range(n)) for y in range(n)]
    return ["".join("#" if (y, x) in marked else "." for x in range(n)) for y in range(n)]


#: "No. 13,412 Set by CRUX", "Crossword 13,422 Set by Mudd"
HEADER = re.compile(r"(?:No\.?|Crossword)\s*(\d{1,2},?\d{3})\s*(?:Set by|by)\s+(.+)", re.I)
WAY = r"(?:across|down|ac|dn|a|d)"
#: The PDF spells a light's direction out ("4, 15 down") or leaves it to the
#: section; "2 A manner people..." is 2 in the section's direction, never 2a.
FULL_WAY = r"(?:across|down)"
CLUE_HEAD = re.compile(rf"^(\d{{1,2}}(?:\s*{FULL_WAY}\b)?(?:\s*[,/&]\s*\d{{1,2}}(?:\s*{FULL_WAY}\b)?)*)\s+(\S.*)$", re.I)
ENUM = re.compile(r"\(\s*(\d{1,2}(?:\s*[,\-–.'’\s]\s*\d{1,2})*(?:\s*words?)?)\s*\)\s*$")
SEE = re.compile(r"^See\s+\d+", re.I)


def heads(spec, direction):
    """'21,23' or '4 down, 15' -> [(21, 'across'), (23, 'across')]."""
    out = []
    for m in tftt.LINK_PART.finditer(spec):
        way = m.group(2)
        out.append((int(m.group(1)), tftt.DIRECTION_OF[way.lower()] if way else direction))
    return out


LEXICON = TOOLS / "data" / "lexicon.tsv"
_RANK = {}


def rank(word):
    """The Lufz lexicon's frequency rank of word (1 commonest), or None."""
    if not _RANK and LEXICON.exists():
        for ln in LEXICON.open(encoding="utf-8"):
            if not ln.startswith("#"):
                w, r = ln.split("\t", 2)[:2]
                _RANK.setdefault(w, int(r))
    return _RANK.get(word.upper())


def join_lines(a, b):
    """A clue broken over lines. At a hyphen the PDF either broke a compound
    ("far-" "reaching") or hyphenated one word to fit ("shad-" "owed",
    "unac-" "ceptably"): it is one word when the join is a word, or when
    either half is not one; a compound of two words that is not itself a word
    keeps its hyphen. A word's frequency against its halves' says nothing:
    SHADOWED is rarer than SHAD."""
    m, n = re.search(r"([A-Za-z]+)-$", a), re.match(r"([A-Za-z]+)", b)
    if not m:
        return f"{a} {b}"
    if n:
        joined = rank(m.group(1) + n.group(1))
        if joined is not None or rank(m.group(1)) is None or rank(n.group(1)) is None:
            return a[:-1] + b
    return a + b


#: A section heading. The FT has set "D0WN" with a zero (No 13,767), and a
#: heading the reader misses ends the clue list there.
SECTION = re.compile(r"(?i)(acr[o0]ss|d[o0]wn)")


def parse_clues(text):
    """{number, setter, clues: [{lights, clue, enumeration}]} off the PDF's text.

    A line opening with a number opens a clue only once the clue before it is
    finished (ends in its enumeration, or is a "See N"), and only with a
    number above the one before it; otherwise it is the clue's next line. The
    first unfinished-free line that opens nothing ends the list (the footer).
    """
    lines = [ln.strip() for ln in text.splitlines()]
    m = next((HEADER.search(ln) for ln in lines if HEADER.search(ln)), None)
    number = int(m.group(1).replace(",", "")) if m else None
    setter = m and m.group(2).strip()
    setter = setter.title() if setter and setter.isupper() else setter
    clues, direction, last, current = [], None, 0, None

    def finished(c):
        return c is None or ENUM.search(c["clue"]) or SEE.match(c["clue"])
    for ln in lines:
        if not ln:
            continue
        if SECTION.fullmatch(ln):
            direction, last, current = ln.lower().replace("0", "o"), 0, None
            continue
        if direction is None:
            continue
        h = CLUE_HEAD.match(ln)
        lights = heads(h.group(1), direction) if h else None
        if lights and finished(current) and lights[0][0] > last:
            current = {"lights": lights, "clue": h.group(2)}
            clues.append(current)
            last = lights[0][0]
        elif current is not None and not finished(current):
            current["clue"] = join_lines(current["clue"], ln)
        else:
            direction = None        # the footer
    for c in clues:
        e = ENUM.search(c["clue"])
        c["enumeration"] = e.group(1).strip() if e else None
    return {"number": number, "setter": setter, "clues": clues}


def read_pdf(path_or_bytes):
    """parse_clues of the PDF, with "grid" read from its vector art (or None)."""
    text, ops = ops_of(path_or_bytes)
    out = parse_clues(text)
    out["grid"] = read_grid(filled_rects(ops))
    return out


def grid_matches(grid, clues):
    """None when the grid's numbering is the clue list's, lights and lengths;
    else why not. A linked clue's enumeration counts all its lights."""
    lights = rg.light_cells(grid)
    # "29 See 1" names a light "1, 29" already listed.
    listed = {l for c in clues for l in c["lights"]}
    if listed != set(lights):
        missing = sorted(set(lights) - set(listed))[:3]
        extra = sorted(set(listed) - set(lights))[:3]
        return f"grid numbering differs from the clue list (unlisted {missing}, not in grid {extra})"
    for c in clues:
        if c["enumeration"] is None:
            if not SEE.match(c["clue"]):
                return f"{c['lights'][0][0]} {c['lights'][0][1]} has no enumeration"
            continue
        want = sum(int(n) for n in re.findall(r"\d+", c["enumeration"]))
        if want != sum(len(lights[l]) for l in c["lights"]):
            return f"{c['lights'][0][0]} {c['lights'][0][1]}'s enumeration disagrees with the grid"
    return None


# ------------------------------------------------------------------ the blog

LIGHT_HEAD = re.compile(r"^\s*\**\s*(\d{1,2})(?!\d)")
STRIP_HEAD = re.compile(rf"^\s*\**\s*\d{{1,2}}(?:\s*{WAY}\b\.?)?(?:\s*[,/&]\s*\d{{1,2}}(?:\s*{WAY}\b\.?)?)*[\s.:)\-–]*")


def blog_answers(rendered, clues):
    """{(number, direction): answer letters} for each clue whose first light
    the post answers, read by that clue's enumeration.

    Each direction's section is walked in step with the PDF's clues: a clue's
    window runs from the first line at or after the last one that opens with
    its number, to the line that opens the next clue. The answer is the first
    line in the window (its number stripped) whose leading capitals the
    enumeration counts word for word (tftt.answer_by_enum)."""
    lines = tftt.lines(rendered)
    sections, way = collections.defaultdict(list), None
    for ln in lines:
        h = ft_puzzles.heading(ln) if ln else None
        if h:
            way = h
            continue
        if way and ln:
            sections[way].append(ln)
    out = {}
    for direction in ("across", "down"):
        sec = sections.get(direction, [])
        mine = [c for c in clues if c["lights"][0][1] == direction and c["enumeration"]]
        pos = 0
        starts = []
        for c in mine:
            n = c["lights"][0][0]
            at = next((i for i in range(pos, len(sec))
                       if (m := LIGHT_HEAD.match(sec[i])) and int(m.group(1)) == n), None)
            starts.append(at)
            if at is not None:
                pos = at + 1
        for i, (c, at) in enumerate(zip(mine, starts)):
            if at is None:
                continue
            end = next((s for s in starts[i + 1:] if s is not None), len(sec))
            for j in range(at, end):
                ln = STRIP_HEAD.sub("", sec[j]) if j == at else sec[j]
                a = tftt.answer_by_enum(ln, c["enumeration"])
                if a:
                    out[c["lights"][0]] = re.sub(r"[^A-Z]", "", a.upper())
                    break
    return out


def blog_posts():
    """{number: post} of every cached weekday-FT write-up; a number two posts
    claim is left out, since nothing says which is the puzzle."""
    cat = fsq.cached_categories()[ft_puzzles.CATEGORY]
    by, claims = {}, collections.Counter()
    for f in fsq.POSTS.glob("*.json"):
        post = json.loads(f.read_text(encoding="utf-8"))
        if cat not in post.get("categories", []):
            continue
        title = html.unescape(post.get("title", {}).get("rendered", ""))
        if ft_puzzles.OTHER_PUZZLE.search(title):
            continue
        n = ft_puzzles.post_number(title)
        if n:
            claims[n] += 1
            by[n] = post
    return {n: p for n, p in by.items() if claims[n] == 1}


# ------------------------------------------------------------------ join

def entries_of(pdf, answers, grid):
    """build()'s entries: one per light, a linked clue's answer shared out by
    the grid's light lengths. None when a light has no answer; answers=None
    gives every light no answer, for a puzzle filed unsolved."""
    lights = rg.light_cells(grid)
    out = []
    for c in pdf["clues"]:
        if c["enumeration"] is None:
            continue      # "See N": its light takes its letters from the leader
        whole = "?" * sum(len(lights[l]) for l in c["lights"])
        if answers is not None:
            whole = answers.get(c["lights"][0])
        if whole is None or len(whole) != sum(len(lights[l]) for l in c["lights"]):
            return None
        at = 0
        for i, light in enumerate(c["lights"]):
            k = len(lights[light])
            leader = c["lights"][0][0]
            out.append({"number": light[0], "direction": light[1],
                        "answer": whole[at:at + k] if answers is not None else None,
                        "clue": c["clue"] if i == 0 else f"See {leader}",
                        "enumeration": c["enumeration"] if i == 0 else None})
            at += k
    return out


def backsolve(clues, answers):
    """(grid, None) when the clue list's numbers and counts fit exactly one
    grid (reconstruct_grid.unique_grid), else (None, why not). A linked
    clue's lights, and a "See N" one, go in with no length: the enumeration
    counts their sum, not each. The write-up's answers go in where they fit
    their light, so a grid they cross wrongly in is not one of the fits."""
    linked = {l for c in clues if len(c["lights"]) > 1 for l in c["lights"]}
    spec, words = {}, {}
    for c in clues:
        for light in c["lights"]:
            spec.setdefault(tuple(light), None)
        light = tuple(c["lights"][0])
        if c["enumeration"] is None or light in linked:
            continue
        spec[light] = sum(int(n) for n in re.findall(r"\d+", c["enumeration"]))
        word = (answers or {}).get(light)
        if word and len(word) == spec[light]:
            words[light] = word
    order = sorted(spec, key=lambda l: (l[0], l[1] != "across"))
    side = tg.SIZE[ft_puzzles.CATEGORY]
    return rg.unique_grid([(n, d, spec[(n, d)]) for n, d in order], cols=side, rows=side,
                          words=[words.get(l) for l in order],
                          max_black_run=tg.MAX_BLACK_RUN[ft_puzzles.CATEGORY],
                          max_nodes=tg.DEFAULT_MAX_NODES)


def assemble(number, pdf, post, date, pdf_url, how):
    """(puzzle, None) or (None, why not)."""
    if pdf["number"] != number:
        return None, f"PDF says No {pdf['number']}"
    # Only the clues are mandatory: with no write-up, or one missing an
    # answer, the puzzle files unsolved and the nightly backfill solves it.
    answers = blog_answers(post["content"]["rendered"], pdf["clues"]) if post else {}
    grid, backsolved = pdf["grid"], None
    why = "PDF has no vector grid" if grid is None else grid_matches(grid, pdf["clues"])
    if why:
        # The vector art is missing or misread: the clue list's numbers and
        # counts rebuild the grid, filed only when exactly one fits.
        grid, rebuilt = backsolve(pdf["clues"], answers)
        if grid is None:
            return None, f"{why}; backsolving the clue list: {rebuilt}"
        backsolved = why
        why = grid_matches(grid, pdf["clues"])
        if why:
            return None, why
    entries = entries_of(pdf, answers, grid) or entries_of(pdf, None, grid)
    unsolved = not entries[0].get("answer")
    rec = {"post_id": f"fifteensquared-{post['id']}" if post else None,
           "link": post.get("link") if post else pdf_url,
           "date": post["date"][:10] if post else None,
           "series": ft_puzzles.CATEGORY, "number": number,
           "setter": pdf["setter"], "entries": entries}
    row = {"grid": grid, "number": number, "how": "the FT's PDF"}
    puzzle, why = file_blog_puzzles.build(rec, row, SERIES, date, pdf["setter"])
    if why:
        return None, why
    puzzle["source"] = {"url": pdf_url,
                        "gridOrigin": "reconstructed" if backsolved else "published"}
    if unsolved:
        return puzzle, None
    puzzle["solutions"]["check"] = (
        (f"clues read from the FT's printable PDF ({backsolved}), the grid "
         f"backsolved from their numbering, the one grid that fits"
         if backsolved else
         "grid and clues read from the FT's printable PDF, its numbering matching "
         "the clue list")
        + "; every fifteensquared answer written into it with each crossing agreeing")
    return puzzle, None


def file(write=True, limit=None, numbers=None, log=print):
    """File every fetched PDF not yet in puzzles/, newest first. (filed, skipped)."""
    idx = json.loads(INDEX.read_text())["puzzles"]
    posts = blog_posts()
    todo = sorted((int(p.stem) for p in PDFS.glob("*.pdf")), reverse=True)
    if numbers:
        todo = [n for n in todo if numbers[0] <= n <= numbers[1]]
    filed, skipped = [], collections.Counter()
    on_disk = None
    ledger = LEDGER.open("a") if write else None
    for n in todo:
        if puzzle_path(SERIES, n).exists():
            skipped["already filed"] += 1
            continue
        if limit is not None and len(filed) >= limit:
            break
        how = (PDFS / f"{n}.how").read_text().strip() if (PDFS / f"{n}.how").exists() else "live"
        entry = idx.get(str(n), {})
        # The FT's own crossword page printed the day beside the link.
        date = (datetime.date.fromisoformat(entry["date"]) if entry.get("date")
                else neighbour_date(n, idx))
        try:
            pdf = read_pdf(pdf_path(n))
            puzzle, why = assemble(n, pdf, posts.get(n), date, entry.get("url"), how)
        except Exception as e:                        # a malformed PDF is one puzzle
            puzzle, why = None, f"unreadable: {type(e).__name__}: {e}"[:160]
        if puzzle is not None:
            if on_disk is None:
                on_disk = ft_puzzles.held_by_content()
            key = puzzle_integrity.content_hash(puzzle)
            if key in on_disk:
                puzzle, why = None, f"reprint of {on_disk[key]}"
        if puzzle is not None and write:
            try:
                correct_source_answers(puzzle["id"], puzzle["entries"])
                write_puzzle_file(puzzle_path(SERIES, n), puzzle,
                                  generator=GENERATOR if how == "live" else GENERATOR_WAYBACK)
            except ValueError as e:
                puzzle, why = None, f"refused on write: {str(e).split(': ', 1)[-1][:120]}"
        if puzzle is not None:
            on_disk[key] = puzzle["id"]
            filed.append(puzzle["id"])
            log(f"  filed {puzzle['id']}")
        else:
            skipped[re.sub(r"\d+[ad]\b.*|\(.*", "", why).strip()] += 1
            log(f"  {n}: {why}")
        if ledger:
            ledger.write(json.dumps({"number": n, "filed": puzzle is not None, "why": why}) + "\n")
    return filed, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=("index", "orphans", "fetch", "file", "all"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--numbers", help="A-B: only puzzle numbers in this range")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    numbers = tuple(int(x) for x in a.numbers.split("-")) if a.numbers else None
    if a.step in ("index", "all"):
        index()
    if a.step in ("orphans", "all"):
        orphans()
    if a.step in ("fetch", "all"):
        fetch(a.limit, numbers)
    if a.step in ("file", "all"):
        filed, skipped = file(write=not a.dry_run, limit=a.limit, numbers=numbers)
        print(f"{'would file' if a.dry_run else 'filed'} {len(filed)}")
        for why, k in skipped.most_common():
            print(f"  skipped {k}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
