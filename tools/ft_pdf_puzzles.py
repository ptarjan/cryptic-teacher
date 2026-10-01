#!/usr/bin/env python3
"""File the Financial Times cryptic from the FT's own printable PDFs.

    python3 tools/ft_pdf_puzzles.py index              # list every PDF Wayback knows of
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
PDF's enumeration counts word for word. A puzzle is filed only when every light
has an answer and every answer writes into the PDF's grid with each crossing
agreeing; the grid's own numbering must match the PDF's clue numbers and
enumerations first, which checks the geometry independently of the blog.

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
from fetch_puzzle import puzzle_path, write_puzzle_file

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
        for operands, op in ContentStream(stream, reader).operations:
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

    def walk(ops, ctm):
        fill, stack, path = 0.0, [], []
        for operands, op in ops:
            if op == b"q":
                stack.append((ctm, fill))
            elif op == b"Q" and stack:
                ctm, fill = stack.pop()
            elif op == b"cm":
                ctm = _mul([float(v) for v in operands], ctm)
            elif op in (b"g", b"k", b"rg", b"sc", b"scn"):
                b = _brightness(operands)
                fill = fill if b is None else b
            elif op == b"re":
                x, y, w, h = (float(v) for v in operands)
                pts = [(x, y), (x + w, y + h)]
                pts = [(ctm[0] * px + ctm[2] * py + ctm[4], ctm[1] * px + ctm[3] * py + ctm[5])
                       for px, py in pts]
                path.append((min(p[0] for p in pts), min(p[1] for p in pts),
                             max(p[0] for p in pts), max(p[1] for p in pts)))
            elif op in (b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"):
                out.extend((*r, fill < 0.5) for r in path)
                path = []
            elif op in (b"n", b"S", b"s"):
                path = []
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


def read_grid(rects):
    """The grid ["..#..", ...] the rectangles draw, or None.

    The frame is the largest square; its cells are the dark squares inside it
    of one common size, and the side in cells is lattice()'s. A grid drawn
    twice on the page (some PDFs carry a second, hidden copy) is one grid:
    cells are a set."""
    squares = [r for r in rects if (r[2] - r[0]) > 1 and abs((r[2] - r[0]) - (r[3] - r[1])) < 0.02 * (r[2] - r[0])]
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
    ("bad-" "tempered") or hyphenated one word to fit ("for-" "tunate",
    "govern-" "ment"): it is one word when the join is a word commoner than
    the rarer of its halves, and the hyphen goes."""
    m, n = re.search(r"([A-Za-z]+)-$", a), re.match(r"([A-Za-z]+)", b)
    if not m:
        return f"{a} {b}"
    if n:
        joined = rank(m.group(1) + n.group(1))
        halves = [rank(m.group(1)), rank(n.group(1))]
        rarer = None if None in halves else max(halves)
        if joined is not None and (rarer is None or joined < rarer):
            return a[:-1] + b
    return a + b


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
        if re.fullmatch(r"(?i)across|down", ln):
            direction, last, current = ln.lower(), 0, None
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
    the grid's light lengths. None when a light has no answer."""
    lights = rg.light_cells(grid)
    out = []
    for c in pdf["clues"]:
        if c["enumeration"] is None:
            continue      # "See N": its light takes its letters from the leader
        whole = answers.get(c["lights"][0])
        if whole is None or len(whole) != sum(len(lights[l]) for l in c["lights"]):
            return None
        at = 0
        for i, light in enumerate(c["lights"]):
            k = len(lights[light])
            leader = c["lights"][0][0]
            out.append({"number": light[0], "direction": light[1], "answer": whole[at:at + k],
                        "clue": c["clue"] if i == 0 else f"See {leader}",
                        "enumeration": c["enumeration"] if i == 0 else None})
            at += k
    return out


def assemble(number, pdf, post, date, pdf_url, how):
    """(puzzle, None) or (None, why not)."""
    if pdf["number"] != number:
        return None, f"PDF says No {pdf['number']}"
    grid = pdf["grid"]
    if grid is None:
        return None, "PDF has no vector grid"
    why = grid_matches(grid, pdf["clues"])
    if why:
        return None, why
    if post is None:
        return None, "no fifteensquared write-up"
    answers = blog_answers(post["content"]["rendered"], pdf["clues"])
    entries = entries_of(pdf, answers, grid)
    if entries is None:
        missing = [f"{c['lights'][0][0]}{c['lights'][0][1][0]}" for c in pdf["clues"]
                   if c["enumeration"] and c["lights"][0] not in answers]
        return None, f"blog answers missing: {' '.join(missing[:6]) or 'a linked split'}"
    rec = {"post_id": f"fifteensquared-{post['id']}", "link": post.get("link"),
           "date": post["date"][:10], "series": ft_puzzles.CATEGORY, "number": number,
           "setter": pdf["setter"], "entries": entries}
    row = {"grid": grid, "number": number, "how": "the FT's PDF"}
    puzzle, why = file_blog_puzzles.build(rec, row, SERIES, date, pdf["setter"])
    if why:
        return None, why
    puzzle["source"] = {"url": pdf_url}
    puzzle["solutions"]["check"] = (
        "grid and clues read from the FT's printable PDF, its numbering matching "
        "the clue list; every fifteensquared answer written into it with each "
        "crossing agreeing")
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
        date = datetime.date.fromisoformat(entry["date"]) if entry.get("date") else None
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
    ap.add_argument("step", choices=("index", "fetch", "file", "all"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--numbers", help="A-B: only puzzle numbers in this range")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    numbers = tuple(int(x) for x in a.numbers.split("-")) if a.numbers else None
    if a.step in ("index", "all"):
        index()
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
