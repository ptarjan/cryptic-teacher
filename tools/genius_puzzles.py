#!/usr/bin/env python3
"""File the Guardian's Genius from its printable PDFs and fifteensquared's answers.

    python3 tools/genius_puzzles.py index              # every Genius article and its PDF link
    python3 tools/genius_puzzles.py fetch              # download the PDFs
    python3 tools/genius_puzzles.py file [--dry-run] [--numbers A-B]

The Genius is the Guardian's monthly prize puzzle, and every one carries a
trick its preamble states: answers entered altered, letters dropped from the
clues, enumerations withheld. From No 147 or so (2016) each article page on
theguardian.com/crosswords/series/genius links a printable PDF on
uploads.guim.co.uk; earlier ones link none. The PDF is text with a vector
grid, read by tools/ft_pdf_puzzles.py's reader: the clue list and preamble by
pypdf, the black squares from the page's rectangles.

The answers are fifteensquared's ("Guardian Genius" category). A puzzle is
filed only when the grid's numbering matches the clue list and every answer
writes into the grid with each crossing agreeing; a trick that alters entries
or withholds enumerations fails one of those checks and is left for its own
handling, its class counted in the report.

Three steps, each reading the one before off disk: index.json, then
pdf/<number>.pdf, then puzzles/.
"""
import argparse
import collections
import datetime
import html
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
import ft_pdf_puzzles as fpp
import puzzle_integrity
import reconstruct_grid as rg
from fetch_puzzle import correct_source_answers, puzzle_path, write_puzzle_file

SERIES = "genius"
CATEGORY = "Guardian Genius"
CACHE = Path.home() / "cryptic-setter-data" / "genius"
INDEX = CACHE / "index.json"
PDFS = CACHE / "pdf"
GENERATOR = "tools/genius_puzzles.py"
UA = {"User-Agent": "Mozilla/5.0 (cryptic-teacher; github.com/ptarjan/cryptic-teacher)"}
SITE = "https://www.theguardian.com"
LISTING = SITE + "/crosswords/series/genius?page={}"
#: "/crosswords/2025/apr/07/genius-crossword-no-262", "/crosswords/2014/dec/01/genius-crossword-138"
ARTICLE = re.compile(r'href="(?:https://www\.theguardian\.com)?'
                     r'(/crosswords/(\d{4})/([a-z]{3})/(\d{2})/genius-crossword-(?:no-)?(\d+))"')
PDF = re.compile(r'https?://(?:uploads|static)\.guim\.co\.uk/[^"\\\s<>&]+?\.pdf', re.IGNORECASE)
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
#: Seconds between requests to the Guardian.
PAUSE = 1


def get(url, timeout=60, tries=3):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                        timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                raise
            if k == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if k == tries - 1:
                raise
        time.sleep(5 * (k + 1))


# ------------------------------------------------------------------ index

def index(log=print):
    """index.json: {number: {url, date, pdf}} of every listed Genius. The
    PDF is the article's uploads.guim.co.uk link that the listing page does
    not also carry (the site footer links a PDF of its own on every page)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    old = json.loads(INDEX.read_text())["puzzles"] if INDEX.exists() else {}
    arts, footer, page = {}, None, 1
    while True:
        body = get(LISTING.format(page)).decode("utf-8", "replace")
        if footer is None:
            footer = set(PDF.findall(body))
        found = {int(m.group(5)): m for m in ARTICLE.finditer(body)}
        new = {n: m for n, m in found.items() if n not in arts}
        if not new:
            break
        arts.update(new)
        page += 1
        time.sleep(PAUSE)
    out = {}
    for n, m in sorted(arts.items()):
        date = datetime.date(int(m.group(2)), MONTHS[m.group(3)], int(m.group(4))).isoformat()
        row = {"url": SITE + m.group(1), "date": date}
        if str(n) in old and old[str(n)].get("url") == row["url"] and old[str(n)].get("pdf"):
            out[str(n)] = old[str(n)]
            continue
        try:
            body = get(row["url"]).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            row["error"] = e.code
            out[str(n)] = row
            continue
        row.update(pdf_of(n, body, footer))
        out[str(n)] = row
        time.sleep(PAUSE)
    for n in unlisted(out):
        row = guess(n, out, old, footer)
        if row:
            out[str(n)] = row
    INDEX.write_text(json.dumps({"puzzles": out}, indent=1))
    log(f"indexed {len(out)} Genius articles; {sum(bool(r.get('pdf')) for r in out.values())} link a PDF")
    return out


def pdf_of(n, body, footer):
    """{"pdf": url} of the article's own PDF: its one link, or of several
    the ones naming the number, the last of those ("Genius175v2" over
    "Genius175"); {"pdfs": [...]} when that leaves no choice."""
    pdfs = sorted(set(PDF.findall(body)) - footer)
    named = [u for u in pdfs if re.search(rf"(?<!\d){n}(?!\d)", u.rsplit("/", 1)[-1])]
    if len(pdfs) == 1:
        return {"pdf": pdfs[0]}
    if named:
        return {"pdf": named[-1], "pdfs": pdfs}
    return {"pdf": None, "pdfs": pdfs} if pdfs else {"pdf": None}


def unlisted(rows):
    """Numbers in the PDF era the listing pages skip."""
    have = {int(k) for k in rows}
    return [n for n in range(FIRST_PDF_ERA, max(have)) if n not in have]


#: The first number whose article could link a PDF (No 150's links a grid).
FIRST_PDF_ERA = 144


def guess(n, rows, old, footer):
    """The row of a Genius the listing skips, from its URL: one a month, on
    a Monday early in the month its nearest listed neighbour puts it in."""
    if str(n) in old and old[str(n)].get("pdf"):
        return old[str(n)]
    m = min((int(k) for k in rows), key=lambda k: abs(k - n))
    d = datetime.date.fromisoformat(rows[str(m)]["date"])
    k = d.year * 12 + d.month - 1 + (n - m)
    year, month = divmod(k, 12)
    first = datetime.date(year, month + 1, 1)
    monday = first + datetime.timedelta(days=(7 - first.weekday()) % 7)
    for day in (monday, monday + datetime.timedelta(days=7), monday - datetime.timedelta(days=7)):
        mon = day.strftime("%b").lower()
        for slug in (f"genius-crossword-no-{n}", f"genius-crossword-{n}"):
            url = f"{SITE}/crosswords/{day.year}/{mon}/{day.day:02d}/{slug}"
            try:
                body = get(url).decode("utf-8", "replace")
            except urllib.error.HTTPError:
                continue
            finally:
                time.sleep(PAUSE)
            return dict({"url": url, "date": day.isoformat(), "guessed": True},
                        **pdf_of(n, body, footer))
    return None


# ------------------------------------------------------------------ fetch

def pdf_path(number):
    return PDFS / f"{number}.pdf"


def fetch(numbers=None, log=print):
    idx = json.loads(INDEX.read_text())["puzzles"]
    PDFS.mkdir(parents=True, exist_ok=True)
    got, failed = 0, []
    for n, row in sorted(idx.items(), key=lambda kv: int(kv[0])):
        if not row.get("pdf") or pdf_path(n).exists():
            continue
        if numbers and not numbers[0] <= int(n) <= numbers[1]:
            continue
        try:
            data = get(row["pdf"])
        except urllib.error.HTTPError as e:
            failed.append((n, e.code))
            continue
        if not data.startswith(b"%PDF"):
            failed.append((n, "not a PDF"))
            continue
        tmp = pdf_path(n).with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(pdf_path(n))
        got += 1
        time.sleep(PAUSE)
    log(f"fetched {got}; {len(failed)} unreachable {failed[:10]}")
    return got


# ------------------------------------------------------------------ the PDF

#: "Genius No 262 Set by Enigmatist", "Genius   no. 176 seT BY PAuL".
HEADER = re.compile(r"Genius\W{0,4}(?:crossword\W{0,4})?No\s*\.?\s*(\d{1,3})(?:\W{0,6}(?:Set\s+)?by\s+([A-Za-z]+))?", re.IGNORECASE)
#: What the entry form and page furniture leave in the preamble: a byline
#: printed apart from the header, a form's "Traced letter: ___", a link.
FURNITURE = re.compile(r"(?i)\bset by [A-Za-z]+\b|[A-Z][\w ]{0,30}:\s*_{2,}|click here to register\.?")
#: A preamble that says answers change on their way into the grid: the
#: write-up's answers are then the entries, and the clue's answer differs.
ALTERED = re.compile(r"(?i)before (?:entry|being entered|entering)|(?:entry|entered) in the grid|"
                     r"for entry|must be (?:modified|altered|changed|treated)|too (?:long|short) for|"
                     r"not be entered|non-words|entries are all|required entry|\bmodified\b|\bclash")
#: The competition's small print, which is not the preamble.
SMALL_PRINT = re.compile(r"(?i)\b(?:deadline|closing date|register once|sign (?:in|on) to|"
                         r"online competition|competition closes|monthly prize|£\d+|the winner)\b")
SECTION_AT = {"across": re.compile(r"\b(?:ACROSS|Across)\b(?=\s*\d)"),
              "down": re.compile(r"\b(?:DOWN|Down)\b(?=\s*\d)")}
#: One clue at the head of the text: its lights ("22,17,3", "20/4", "4 down"),
#: then its words up to the first enumeration, "See N" or "[unclued]".
CLUE_AT = re.compile(
    r"\s*(?P<head>\d{1,2}(?:\s*(?:across|down))?(?:\s*[,/&]\s*\d{1,2}(?:\s*(?:across|down))?)*)"
    r"(?P<star>\*)?\s+(?P<text>(?:See\s+\d{1,2}(?:\s*(?:across|down))?(?![\w(])"
    r"|\[unclued\]"
    r"|\S.*?\(\s*\d{1,2}(?:\s*[,\-–.'’\s]\s*\d{1,2})*(?:\s*words?)?\s*\)))",
    re.IGNORECASE)


def flat(raw):
    """The PDF's text as one line: pypdf's per-word and per-line breaks are
    all spaces, a capital kerned off its word ("T earful") rejoined, and a
    word hyphenated over a line break ("oth- erwise") joined when the join is
    a word (fpp.join_lines)."""
    t = re.sub(r"[\u200b\u00ad]", "", raw)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\b([B-HJ-Z]) (?=[a-z]{2})", r"\1", t)
    return re.sub(r"\b([A-Za-z]+)- ([a-z]+)\b",
                  lambda m: fpp.join_lines(m.group(1) + "-", m.group(2)), t)


def section(text, start, direction):
    """(clues, end) read one after another from text[start:]: a clue's first
    number must exceed the one before, and the first stretch that is not a
    clue ends the section."""
    clues, last, pos = [], 0, start
    while True:
        m = CLUE_AT.match(text, pos)
        if not m:
            break
        lights = fpp.heads(m.group("head"), direction)
        if not lights or lights[0][0] < last or (lights[0][0] == last and lights == clues[-1]["lights"]):
            break
        body = (m.group("star") or "") + m.group("text").strip()
        e = fpp.ENUM.search(body)
        clues.append({"lights": lights, "clue": body,
                      "enumeration": e.group(1).strip() if e else None})
        last, pos = lights[0][0], m.end()
    return clues, pos


def parse_text(text):
    """{number, setter, clues, preamble} off the flattened text."""
    m = HEADER.search(text)
    out = {"number": int(m.group(1)) if m else None,
           "setter": m.group(2).title() if m and m.group(2) and (
               m.group(2).isupper() or not m.group(2).istitle()) else (m.group(2) if m else None)}
    if not out["setter"]:
        by = re.search(r"\bSet by ([A-Z][a-z]+)\b", text)
        out["setter"] = by and by.group(1)
    clues, used = [], []
    for direction, rx in SECTION_AT.items():
        for h in rx.finditer(text):
            got, end = section(text, h.end(), direction)
            if got:
                clues += got
                used.append((h.start(), end))
                break
    out["clues"] = clues
    rest, at = [], 0
    spans = sorted(used + [(h.start(), h.end()) for h in HEADER.finditer(text)])
    for a, b in spans:
        rest.append(text[at:a])
        at = max(at, b)
    rest.append(text[at:])
    rest = [FURNITURE.sub("", x) for x in rest]
    rest = [re.sub(r"(?i)^\s*Clues\b|\b(?:Instructions|RULES AND REQUESTS|Preamble)\b:?", "", x) for x in rest]
    sentences = re.split(r"(?<=[.?!])\s+", " ".join(x.strip() for x in rest if x.strip()))
    keep = [x for x in sentences if x and not SMALL_PRINT.search(x)
            and not re.fullmatch(r"(?i)\W*(?:clues|rules and requests)?\W*", x)]
    out["preamble"] = " ".join(keep).strip() or None
    return out


def image_grid(pages):
    """The grid ["..#..", ...] of the page's largest image, or None: the side
    is the fewest cells n (5 to 27) at which the lower-right of every cell,
    clear of its number, is one colour throughout."""
    import numpy as np
    best = None
    for im in (im for page in pages for im in page.images):
        a = np.asarray(im.image.convert("L"), dtype=np.float32) / 255
        if a.shape[0] < 100 or abs(a.shape[0] - a.shape[1]) > 0.02 * a.shape[0]:
            continue
        if best is None or a.size > best.size:
            best = a
    if best is None:
        return None
    h, w = best.shape
    for n in range(5, 28):
        ph, pw = h / n, w / n
        rows, ok = [], True
        for y in range(n):
            row = ""
            for x in range(n):
                cell = best[int(y * ph + ph * 0.45):int(y * ph + ph * 0.85),
                            int(x * pw + pw * 0.45):int(x * pw + pw * 0.85)]
                m = float(cell.mean())
                if 0.2 < m < 0.8:
                    ok = False
                    break
                row += "." if m >= 0.5 else "#"
            if not ok:
                break
            rows.append(row)
        if ok:
            return rows
    return None


def read_pdf(path):
    """{number, setter, preamble, clues, grid, kind, text} off a Genius PDF.
    `kind` says where the grid came from: "vector", "image" or None."""
    import logging

    import pypdf
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = pypdf.PdfReader(str(path))
    raw, ops = fpp.ops_of(Path(path).read_bytes())
    raw += "\n" + "\n".join(pg.extract_text() or "" for pg in reader.pages[1:])
    out = parse_text(flat(raw))
    see_links(out["clues"])
    grid = fpp.read_grid(fpp.filled_rects(ops))
    out["kind"] = "vector" if grid else None
    if grid is None:
        grid = image_grid(reader.pages)
        out["kind"] = "image" if grid else None
    out["grid"] = grid
    out["text"] = bool(raw.strip())
    return out


def see_links(clues):
    """A link's later parts take their direction from their own "See N"
    entry: "20/4" heads the Across list, and "4 See 20 Across" in the Down
    list says the 4 is 4 down."""
    seen = {c["lights"][0] for c in clues if c["enumeration"] is None and len(c["lights"]) == 1}
    flip = {"across": "down", "down": "across"}
    # "23 See 26" under a clue headed "26" alone: 26's answer runs on into 23.
    leaders = {c["lights"][0][0]: c for c in clues if c["enumeration"]}
    for c in clues:
        m = c["enumeration"] is None and len(c["lights"]) == 1 and re.fullmatch(
            r"See (\d{1,2})(?:\s*(across|down))?", c["clue"], re.IGNORECASE)
        lead = m and leaders.get(int(m.group(1)))
        if lead and c["lights"][0] not in lead["lights"] and not any(
                l[0] == c["lights"][0][0] for l in lead["lights"][1:]):
            lead["lights"].append(c["lights"][0])
    for c in clues:
        for i, (n, d) in enumerate(c["lights"][1:], 1):
            if (n, d) not in seen and (n, flip[d]) in seen:
                c["lights"][i] = (n, flip[d])


# ------------------------------------------------------------------ the blog

NUMBER = re.compile(r"\bGenius\b\D{0,12}?(\d{1,3})\b", re.IGNORECASE)


def blog_posts():
    """{number: post} of every cached Genius write-up a single post claims."""
    cat = fsq.cached_categories()[CATEGORY]
    by, claims = {}, collections.Counter()
    for f in fsq.POSTS.glob("*.json"):
        post = json.loads(f.read_text(encoding="utf-8"))
        if cat not in post.get("categories", []):
            continue
        m = NUMBER.search(html.unescape(post.get("title", {}).get("rendered", "")))
        if m:
            n = int(m.group(1))
            claims[n] += 1
            by[n] = post
    return {n: p for n, p in by.items() if claims[n] == 1}


#: "Guardian Genius 156 / Pasquale", "Genius 81 by Paul", "Guardian Genius 188 – Enigmatist".
POST_SETTER = re.compile(r"Genius\D{0,12}\d{1,3}\s*(?:by|/|–|-|:)\s*([A-Z][A-Za-z]+)\s*$")


def post_setter(post):
    m = post and POST_SETTER.search(html.unescape(post.get("title", {}).get("rendered", "")))
    return m.group(1) if m else None


#: The hyphens and dashes a post writes an answer's hyphen with.
DASHES = re.compile("[\u2010\u2011\u2012\u2013\u2014]")
#: An answer as a post prints it: capitals, spaces, hyphens, apostrophes.
CAPS = re.compile(r"[A-Z][A-Z '’\-]*[A-Z]")


def blog_answers(rendered, clues):
    """fpp.blog_answers, with any light it misses taken from the first line
    within three of the line opening with its number that is all capitals
    and has as many letters as the enumeration counts ("A PRIORI" for a
    (7))."""
    rendered = DASHES.sub("-", re.sub(r"&#(?:820[89]|821[012]|x201[0-4]);", "-", rendered))
    out = fpp.blog_answers(rendered, clues)
    sections, way = collections.defaultdict(list), None
    for ln in fpp.tftt.lines(rendered):
        h = fpp.ft_puzzles.heading(ln) if ln else None
        if h:
            way = h
        elif way and ln:
            sections[way].append(ln)
    for c in clues:
        light = c["lights"][0]
        if light in out or not c["enumeration"]:
            continue
        want = sum(int(x) for x in re.findall(r"\d+", c["enumeration"]))
        sec = sections.get(light[1], [])
        for i, ln in enumerate(sec):
            m = fpp.LIGHT_HEAD.match(ln)
            if not (m and int(m.group(1)) == light[0]):
                continue
            for cand in [fpp.STRIP_HEAD.sub("", ln)] + sec[i + 1:i + 4]:
                cand = cand.strip()
                if CAPS.fullmatch(cand) and len(re.sub(r"[^A-Z]", "", cand)) == want:
                    out[light] = re.sub(r"[^A-Z]", "", cand)
                    break
            if light in out:
                break
    return out


# ------------------------------------------------------------------ join

def assemble(number, pdf, post, date, url):
    """(puzzle, None) or (None, (class, why not))."""
    if not pdf["text"]:
        return None, ("PDF has no text", "")
    if pdf["number"] not in (None, number):
        return None, ("PDF is another puzzle", f"PDF says No {pdf['number']}")
    pdf["setter"] = pdf["setter"] or post_setter(post)
    if not pdf["clues"]:
        return None, ("clue list unread", "")
    if pdf["grid"] is None:
        return None, ("grid unread", "")
    why = fpp.grid_matches(pdf["grid"], pdf["clues"])
    if why:
        if "no enumeration" in why:
            return None, ("enumerations withheld", why)
        if "enumeration disagrees" in why:
            return None, ("enumeration is not the entry's length", why)
        lights = set(rg.light_cells(pdf["grid"]))
        listed = {l for c in pdf["clues"] for l in c["lights"]}
        if listed < lights:
            return None, ("lights left unclued", why)
        return None, ("grid numbering differs from clue list", why)
    if not pdf["preamble"]:
        return None, ("preamble unread", "")
    if ALTERED.search(pdf["preamble"]):
        return None, ("preamble alters entries (needs an alteration per answer)", "")
    if post is None:
        return None, ("no fifteensquared post", "")
    answers = blog_answers(post["content"]["rendered"], pdf["clues"])
    entries = fpp.entries_of(pdf, answers, pdf["grid"])
    if entries is None:
        missing = [c["lights"][0] for c in pdf["clues"]
                   if c["enumeration"] and c["lights"][0] not in answers]
        return None, ("a light's answer not read off the post", f"{len(missing)} missing, {missing[:3]}")
    rec = {"post_id": f"fifteensquared-{post['id']}", "link": post.get("link"),
           "date": post["date"][:10], "series": CATEGORY, "number": number,
           "setter": pdf["setter"], "entries": entries}
    row = {"grid": pdf["grid"], "number": number, "how": "the Guardian's PDF"}
    puzzle, why = file_blog_puzzles.build(rec, row, SERIES, date, pdf["setter"])
    if why:
        if why == "answers disagree with the grid":
            return None, ("answers cross wrongly (entries altered)", why)
        return None, (why, "")
    if pdf["preamble"]:
        puzzle["preamble"] = pdf["preamble"]
    puzzle["source"] = {"url": url, "gridOrigin": "published"}
    puzzle["solutions"]["check"] = (
        "grid and clues read from the Guardian's printable PDF, its numbering matching "
        "the clue list; every fifteensquared answer written into it with each crossing agreeing")
    return puzzle, None


def file(write=True, numbers=None, log=print):
    """File every fetched PDF not yet in puzzles/, newest first.
    Returns (filed, {class: [numbers]}, counts)."""
    idx = json.loads(INDEX.read_text())["puzzles"]
    posts = blog_posts()
    filed, blocked = [], collections.defaultdict(list)
    counts = collections.Counter(indexed=len(idx), pdf_linked=sum(bool(r.get("pdf")) for r in idx.values()),
                                 posts=len(posts))
    on_disk = None
    for n in sorted((int(k) for k in idx), reverse=True):
        if numbers and not numbers[0] <= n <= numbers[1]:
            continue
        if not pdf_path(n).exists():
            blocked["no PDF"].append(n)
            continue
        counts["fetched"] += 1
        if puzzle_path(SERIES, n).exists():
            counts["already filed"] += 1
            continue
        try:
            pdf = read_pdf(pdf_path(n))
            if pdf["clues"] and pdf["number"] in (None, n):
                counts["parsed"] += 1
            if pdf["grid"] and not fpp.grid_matches(pdf["grid"], pdf["clues"]):
                counts["grid consistent with clues"] += 1
            puzzle, why = assemble(n, pdf, posts.get(n), datetime.date.fromisoformat(idx[str(n)]["date"]),
                                   idx[str(n)]["url"])
        except Exception as e:  # noqa: BLE001 — a malformed PDF is one puzzle
            puzzle, why = None, ("unreadable", f"{type(e).__name__}: {e}"[:160])
        if puzzle is not None:
            if on_disk is None:
                on_disk = fpp.ft_puzzles.held_by_content(SERIES)
            key = puzzle_integrity.content_hash(puzzle)
            if key in on_disk:
                puzzle, why = None, ("reprint", on_disk[key])
        if puzzle is not None and write:
            try:
                correct_source_answers(puzzle["id"], puzzle["entries"])
                write_puzzle_file(puzzle_path(SERIES, n), puzzle, generator=GENERATOR)
            except ValueError as e:
                puzzle, why = None, ("refused on write", str(e).split(": ", 1)[-1][:160])
        if puzzle is not None:
            on_disk[key] = puzzle["id"]
            filed.append(puzzle["id"])
            log(f"  filed {puzzle['id']}")
        else:
            blocked[why[0]].append(n)
            log(f"  {n}: {why[0]}: {why[1]}")
    return filed, blocked, counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=("index", "fetch", "file", "all"))
    ap.add_argument("--numbers", help="A-B: only puzzle numbers in this range")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    numbers = tuple(int(x) for x in a.numbers.split("-")) if a.numbers else None
    if a.step in ("index", "all"):
        index()
    if a.step in ("fetch", "all"):
        fetch(numbers)
    if a.step in ("file", "all"):
        filed, blocked, counts = file(write=not a.dry_run, numbers=numbers)
        print(" ".join(f"{k}={v}" for k, v in counts.items()))
        print(f"{'would file' if a.dry_run else 'filed'} {len(filed)}")
        for why, ns in sorted(blocked.items(), key=lambda kv: -len(kv[1])):
            print(f"  blocked {len(ns)}: {why}  e.g. {ns[:6]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
