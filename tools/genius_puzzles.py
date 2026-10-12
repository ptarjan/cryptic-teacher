#!/usr/bin/env python3
"""File the Guardian's Genius from its printable PDFs or article pages and fifteensquared's answers.

    python3 tools/genius_puzzles.py index              # every Genius article and its PDF link
    python3 tools/genius_puzzles.py fetch              # download the PDFs
    python3 tools/genius_puzzles.py file [--dry-run] [--numbers A-B]

The Genius is the Guardian's monthly prize puzzle, and every one carries a
trick its preamble states: answers entered altered, letters dropped from the
clues, enumerations withheld. From No 147 or so (2016) each article page on
theguardian.com/crosswords/series/genius links a printable PDF on
uploads.guim.co.uk. Earlier ones print the preamble and clues as the article's
text, with the grid as a picture on static.guim.co.uk; those are read off the
article (read_article). The PDF is read with
tools/ft_pdf_puzzles.py's reader: the clue list and preamble by pypdf, the
black squares from the page's rectangles, or from its largest image where the
grid is a picture (image_grid).

The answers are fifteensquared's ("Guardian Genius" category). A puzzle is
filed only when the grid's numbering matches the clue list and every answer
writes into the grid with each crossing agreeing. One that fails because its
entries are altered, or the post prints its answers in a layout the reader
misses, gets a second try (assemble_altered): each light may take any word
the post prints for it, or what the preamble's rule (ALTERED_BY) makes of
one, and the grid must take exactly one choice with every crossing agreeing.
An entry that is not its answer carries the answer as `alteration.from`, by
the op the preamble allows. The rest are left, their class counted in the
report.

Three steps, each reading the one before off disk: index.json, then
pdf/<number>.pdf (or article/<number>.html and its images), then puzzles/.
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
import enumeration
import fetch_fifteensquared as fsq
import file_blog_puzzles
import groups
import ft_pdf_puzzles as fpp
import puzzle_integrity
import quotes
import series as series_meta
import downloads
import reconstruct_grid as rg
from fetch_puzzle import correct_source_answers, puzzle_path, write_puzzle_file


SERIES = "genius"
CATEGORY = "Guardian Genius"
CACHE = downloads.GENIUS
INDEX = CACHE / "index.json"
PDFS = CACHE / "pdf"
ARTICLES = CACHE / "article"
GENERATOR = "tools/genius_puzzles.py"
UA = {"User-Agent": "Mozilla/5.0 (cryptic-teacher; github.com/ptarjan/cryptic-teacher)"}
SITE = "https://www.theguardian.com"
LISTING = SITE + "/crosswords/series/genius?page={}"
#: "/crosswords/2025/apr/07/genius-crossword-no-262", "/crosswords/2014/dec/01/genius-crossword-138"
ARTICLE = re.compile(r'href="(?:https://www\.theguardian\.com)?'
                     r'(/crosswords/(\d{4})/([a-z]{3})/(\d{2})/genius-crossword-(?:no-)?(\d+))"')
#: An article's picture, by the path its original keeps on static.guim.co.uk.
STATIC_IMAGE = re.compile(r'https://i\.guim\.co\.uk/img/static/([^"\s?&]+?\.(?:jpe?g|png|gif))', re.IGNORECASE)
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
        if str(n) in old and old[str(n)].get("url") == row["url"] and (
                old[str(n)].get("pdf") or article_path(n).exists()):
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
    """Numbers the listing pages skip."""
    have = {int(k) for k in rows}
    return [n for n in range(1, max(have)) if n not in have]


def guess(n, rows, old, footer):
    """The row of a Genius the listing skips, from its URL: one a month, on
    a Monday early in the month its nearest listed neighbour puts it in."""
    if str(n) in old and (old[str(n)].get("pdf") or article_path(n).exists()):
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


def article_path(number):
    return ARTICLES / f"{number}.html"


def image_paths(number):
    return sorted(ARTICLES.glob(f"{number}-*.img"))


def fetch_article(n, row):
    """article/<n>.html and each picture it shows, as n-<k>.img: the article
    of a Genius with no PDF prints the clues, and its grid is one of these."""
    ARTICLES.mkdir(parents=True, exist_ok=True)
    body = get(row["url"])
    time.sleep(PAUSE)
    for k, path in enumerate(sorted(set(STATIC_IMAGE.findall(body.decode("utf-8", "replace"))))):
        data = get("https://static.guim.co.uk/" + path)
        (ARTICLES / f"{n}-{k}.img").write_bytes(data)
        time.sleep(PAUSE)
    tmp = article_path(n).with_suffix(".tmp")
    tmp.write_bytes(body)
    tmp.replace(article_path(n))


def fetch(numbers=None, log=print):
    idx = json.loads(INDEX.read_text())["puzzles"]
    PDFS.mkdir(parents=True, exist_ok=True)
    got, failed = 0, []
    for n, row in sorted(idx.items(), key=lambda kv: int(kv[0])):
        if numbers and not numbers[0] <= int(n) <= numbers[1]:
            continue
        if not row.get("pdf"):
            if row.get("error") or article_path(n).exists():
                continue
            try:
                fetch_article(n, row)
                got += 1
            except urllib.error.HTTPError as e:
                failed.append((n, e.code))
            continue
        if pdf_path(n).exists():
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
FURNITURE = re.compile(r"(?i)\bset by [A-Za-z]+\b|[A-Z][\w ]{0,30}:\s*_{2,}|click here to register\.?|"
                       r"\bs\s+et\s+by\s+(?:[A-Za-z]\s?){3,12}|(?:\b\d{1,2}\s+){7,}\d{1,2}\b\s*$|"
                       r"^\s*across\b|\bG\s?E\s?N\s?I\s?U\s?S\s+(?:No\.?\s*)?\d+")
#: A preamble that says answers change on their way into the grid: the
#: write-up's answers are then the entries, and the clue's answer differs.
ALTERED = re.compile(r"(?i)before (?:entry|being entered|entering)|(?:entry|entered) in the grid|"
                     r"for entry|must be (?:modified|altered|changed|treated)|too (?:long|short) for|"
                     r"not be entered|non-words|entries are all|required entry|\bmodified\b|\bclash")
#: The competition's small print, which is not the preamble.
SMALL_PRINT = re.compile(r"(?i)register\s*once|\b(?:deadline|closing date|register\s*once|sign\s*(?:in|on)\s*to|"
                         r"online competition|enter the competition|this grid was updated|click here for (?:the )?printable version|valid email address|resubmit your entry|competition (?:closes|not open)|monthly prize|one entry only|alternate winner|privacy policy|terms and conditions|promoter|name or location|eligible|prize draw|entries received|email you|£\d+|(?:one |the )winners?|winners? (?:will|are|must|of the)|personal data|don[’']t respond)\b")
#: A section's heading, as the PDFs case it ("ACross", "DoWN" too).
SECTION_AT = {"across": re.compile(r"\b(?:ACROSS|A[Cc]ross)\b(?=\s*\d)"),
              "down": re.compile(r"\b(?:DOWN|D[Oo][Ww]N|Down)\b(?=\s*\d)")}
#: One clue at the head of the text: its lights ("22,17,3", "20/4", "4 down"),
#: then its words up to the first enumeration (fpp.ENUM_TEXT: "(6;4)",
#: "(4,3) (7)", "(8,4 (5,5))" too), or a stub: "See N" or "[unclued]", which
#: may print its light's count after it ("See 7 (8)"), or a count alone
#: ("1 (6) 2 (6)": a light the puzzle leaves without a clue; one with words
#: after it, "5 (2) What gets...", is a clue opening on a cross-reference).
STUB = (r"(?:See\s+\d{1,2}(?:\s*(?:across|down))?(?![\w(])"
        r"|\[unclued\]|\(See (?:special )?instructions\)|See (?:the )?preamble\b|See (?:the )?(?:special )?instructions\b(?!\s*\())")
CLUE_AT = re.compile(
    r"\s*(?P<head>\d{1,2}(?:\s*(?:across|down))?(?:\s*[,/&]\s*\d{1,2}(?:\s*(?:across|down))?)*)"
    rf"(?P<star>\*)?\s+(?P<text>{STUB}(?:\s*{fpp.ENUM_TEXT})?|{fpp.ENUM_TEXT}(?=\s*(?:\d|Down\b|$))|\S.*?{fpp.ENUM_TEXT})",
    re.IGNORECASE)
#: A stub with its count: the stub alone is what the reader keeps.
STUB_COUNTED = re.compile(rf"({STUB})\s*{fpp.ENUM_TEXT}", re.IGNORECASE)


UNCLUED_MARK = re.compile(r"(?i)\[unclued\]|\(See (?:special )?instructions\)|See (?:the )?(?:special )?(?:preamble|instructions)")


#: The one ligature table (quotes.LIGATURES), which every clue write applies too.
LIGATURES = str.maketrans(quotes.LIGATURES)


def flat(raw, kerned=True):
    """The PDF's text as one line: pypdf's per-word and per-line breaks are
    all spaces, a capital kerned off its word ("T earful") rejoined, and a
    word hyphenated over a line break ("oth- erwise") joined when the join is
    a word (fpp.join_lines).

    The kerning rejoin is for PDF text only (`kerned`), and a letter is
    left standing when its rest is a word and the join is not, since a clue
    can print a letter alone: genius-162's "X and Y appears", genius-246's
    "E recently". A rest that is no word ("T urpin", "T orbay") still joins. genius-8's
    "T going west in form of lottery" and "T with a long T wasting" (a T is
    every theme word's stand-in) were filed "Tgoing" and "Twith ... Twasting"
    when the rejoin ran over article text, which has no kerning — its
    spaces are the page's own. "Ton hill" and "Tin 5" there join to words, so
    no lexicon check can tell them apart: article text is never rejoined."""
    t = re.sub(r"[\u200b\u00ad]", "", raw)
    # A PDF's typeset ligatures ("stu\ufb00", "e\ufb00ervescent": genius-205,
    # 169) are letters: the write gate refuses them in clue text.
    t = t.translate(LIGATURES)
    t = re.sub(r"\s+", " ", t).strip()
    if kerned:
        t = re.sub(r"\b([B-HJ-Z]) ([a-z]{2,})\b",
                   lambda m: m.group(0) if fpp.rank(m.group(2)) is not None
                   and fpp.rank(m.group(1) + m.group(2)) is None else m.group(1) + m.group(2), t)
    return re.sub(r"\b([A-Za-z]+)- ([a-z]+)\b",
                  lambda m: fpp.join_lines(m.group(1) + "-", m.group(2)), t)


#: A clue head inside a run of clues printed without counts: a number after
#: a word's end, before a capital ("... went wrong 9 Outlines ...").
BARE_HEAD = re.compile(r"(?<=[A-Za-z?!'’”)]) (\d{1,2})\*? (?=[A-Z‘“\"'])")


def countless(text, start, end, first, direction):
    """(clues, end) for a run whose clues print no count (No 233's across
    list, its lengths the gimmick's): text[start:end] cut at each bare head
    whose number exceeds the last. The last clue runs to the end of the run,
    or, when prose follows it there ("... instigation of evil All down clues
    are normal."), up to the last capital before the prose's first full stop."""
    run = text[start:end]
    if re.search(fpp.ENUM_TEXT, run):
        return None     # counts printed: a clue the reader misses, not a countless list (No 17's "(*,7)")
    cuts, last = [(0, first)], first
    for m in BARE_HEAD.finditer(run):
        if int(m.group(1)) > last:
            cuts.append((m.start(), int(m.group(1))))
            last = int(m.group(1))
    if len(cuts) < 3:
        return None
    clues = []
    for i, (at, n) in enumerate(cuts):
        to = cuts[i + 1][0] if i + 1 < len(cuts) else len(run)
        body = re.sub(r"^\s*\d{1,2}(\*?)\s*", r"\1", run[at:to]).strip()
        clues.append({"lights": [(n, direction)], "clue": body, "enumeration": None})
    tail, stop = clues[-1]["clue"], len(run)
    full = re.search(r"[.!?](?:\s|$)", tail)
    caps = [m for m in re.finditer(r"\s(?=[A-Z][a-z])", tail[:full.start()])] if full else []
    if caps and len(tail[:caps[-1].start()].split()) >= 2 and len(tail[caps[-1].start():full.start()].split()) >= 3:
        clues[-1]["clue"] = tail[:caps[-1].start()].strip()
        stop = run.rindex(tail) + caps[-1].start()
    return clues, start + stop


def in_order(clues):
    """The clues up to the first whose number does not exceed the one
    before, after mending two misprints that break the order:
    a stray copy of a later clue (No 162 prints 19 down's clue again where
    6 down would be) is dropped, and a number that lost its leading 1 (No
    161's "2" between 8 and 13) is read as the one that fits between its
    neighbours."""
    clues, out, i = list(clues), [], 0
    key = lambda c: (c["lights"][0], c["clue"])
    while i < len(clues):
        c, n = clues[i], clues[i]["lights"][0][0]
        prev = out[-1]["lights"][0][0] if out else 0
        nxt = clues[i + 1]["lights"][0][0] if i + 1 < len(clues) else None
        i += 1
        if c["enumeration"] and nxt is not None and nxt <= n and key(c) in map(key, clues[i:]):
            continue                    # a stray copy: its own place comes later
        if n > prev or (out and n == prev and c["lights"] != out[-1]["lights"]):
            out.append(c)       # "22,17,3 ..." then "22,2,5 ...": No 209's two 22s
        elif n < 10 and nxt is not None and prev < n + 10 < nxt:
            out.append(dict(c, lights=[(n + 10, c["lights"][0][1])] + c["lights"][1:]))
        else:
            break
    return out


def section(text, start, direction):
    """(clues, end) read one after another from text[start:]: clue numbers
    rise (in_order mends a misprint), and the first stretch that is not a
    clue ends the section. A first clue whose words run over more bare clue
    heads ("8 Bit of ... wrong 9 Outlines ...") is a list printed without
    counts, read by countless() up to the next heading."""
    found, pos = [], start
    while True:
        m = CLUE_AT.match(text, pos)
        if not m:
            break
        lights = fpp.heads(m.group("head"), direction)
        if not lights:
            break
        said = m.group("text").strip()
        if not found:
            inner = [int(h.group(1)) for h in BARE_HEAD.finditer(said)]
            rising = [x for i, x in enumerate(inner) if x > lights[0][0] and all(x > y for y in inner[:i])]
            if len(rising) >= 2:
                heading = [h.start() for rx in SECTION_AT.values() for h in rx.finditer(text, m.start("text"))]
                got = countless(text, m.start("head"), min(heading, default=len(text)), lights[0][0], direction)
                if got:
                    return got
        stub = STUB_COUNTED.fullmatch(said)
        body = (m.group("star") or "") + (stub.group(1) if stub else said)
        e = None if stub else fpp.ENUM.search(body)
        found.append(({"lights": lights, "clue": body,
                       "enumeration": e.group(1).strip() if e else None}, m.end()))
        pos = m.end()
        if len(found) > 1 and lights == found[-2][0]["lights"]:
            break
    ends = {id(c): e for c, e in found}
    clues = in_order(c for c, _ in found)
    return clues, (ends[id(clues[-1])] if clues else start)


def parse_text(text):
    """{number, setter, clues, preamble} off the flattened text."""
    m = HEADER.search(text)
    out = {"number": int(m.group(1)) if m else None,
           "setter": m.group(2).title() if m and m.group(2) and (
               m.group(2).isupper() or not m.group(2).istitle()) else (m.group(2) if m else None)}
    if not out["setter"]:
        by = re.search(r"\bSet by ([A-Z][a-z]+)\b", text)
        out["setter"] = by and by.group(1)
    clues, used, ends = [], [], {}
    # Both headings printed together over the clues ("Across Down 1 ..."): the
    # first run is the first heading's, the second the other's (No 202).
    both = re.search(r"\b(ACROSS|A[Cc]ross|DOWN|D[Oo][Ww]N|Down)\s+(ACROSS|A[Cc]ross|DOWN|D[Oo][Ww]N|Down)\b(?=\s*\d)", text)
    if both and both.group(1).lower() != both.group(2).lower():
        first, second = both.group(1).lower(), both.group(2).lower()
        got, end = section(text, both.end(), first)
        more, end2 = section(text, end, second) if got else ([], end)
        if got and more:
            clues, used, ends = got + more, [(both.start(), end2)], {first: end, second: end2}
    paired = bool(ends)
    for direction, rx in SECTION_AT.items():
        if paired:
            break
        for h in rx.finditer(text):
            got, end = section(text, h.end(), direction)
            if got:
                clues += got
                used.append((h.start(), end))
                ends[direction] = end
                break
    # A section whose heading is printed but heads no clue ("Across Down 1
    # ...", or "ACross" above the preamble) is the run that follows the other
    # section, its numbers starting again: No 202 and No 165's layouts.
    for direction, other in (("across", "down"), ("down", "across")):
        if direction not in ends and other in ends and re.search(
                rf"(?i)\b{direction}\b", text):
            got, end = section(text, ends[other], direction)
            if got:
                clues += got
                used.append((ends[other], end))
                ends[direction] = end
    # One heading found and the other's clues stranded elsewhere with no
    # heading the readers know ("across 8 Extremely ..." in small capitals, No
    # 157, or a run that fell into the preamble): the first run of three or
    # more clues outside the spans taken, numbered as the other way, is it.
    if len(ends) == 1:
        missing = "down" if "across" in ends else "across"
        taken = lambda i: any(a <= i < b for a, b in used)
        for m in re.finditer(r"(?<![\d,])\d{1,2}(?:[,/]\d{1,2})* (?=[A-Z\u2018\u201c\"'])", text):
            if taken(m.start()):
                continue
            got, end = section(text, m.start(), missing)
            if len(got) >= 3:
                clues += got
                used.append((m.start(), end))
                ends[missing] = end
                break
    out["clues"] = clues
    rest, at = [], 0
    spans = sorted(used + [(h.start(), h.end()) for h in HEADER.finditer(text)])
    for a, b in spans:
        rest.append(text[at:a])
        at = max(at, b)
    rest.append(text[at:])
    # The labels first, so a heading they hid ("Clues ACross Instructions
    # Eight solutions ...", No 165) is at the start for FURNITURE.
    rest = [re.sub(r"(?i)^\s*Clues\b|\b(?:Instructions|RULES AND REQUESTS|Preamble)\b:?", "", x) for x in rest]
    rest = [FURNITURE.sub("", x) for x in rest]
    sentences = re.split(r"(?<=[.?!])\s+", " ".join(x.strip() for x in rest if x.strip()))
    # Small print run on from an instruction with no full stop between keeps
    # the instruction ("... first letter Competition closes ...").
    cut = [x[:m.start()].strip() if (m := SMALL_PRINT.search(x)) and m.start() > 40 else
           ("" if m else x) for x in sentences]
    keep = [x for x in cut if x and not re.fullmatch(r"(?i)\W*(?:clues|rules and requests)?\W*", x)]
    out["preamble"] = " ".join(keep).strip() or None
    return out


def on_white(image):
    """The image in greys, any transparency laid over white: some PDFs draw
    the grid in the alpha channel of an all-black image."""
    from PIL import Image
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(white, rgba).convert("L")
    return image.convert("L")


def image_grid(pages, clues=()):
    """grid_of_images over every image on the pages."""
    return grid_of_images([im.image for page in pages for im in page.images], clues)


def grid_of_images(images, clues=()):
    """The grid ["..#..", ...] of the largest square image, or None. The
    image is tried cropped to its ink (a margin or frame off the lattice
    shifts every cell) and whole, and the side is the fewest cells n (5 to 27) at which the
    lower-right of every cell, clear of its number, is either white or the
    image's own block shade (black, or the grey some PDFs print); of several
    such sides, the first whose lights are the clue list's, else the one
    whose lights come nearest it."""
    import numpy as np
    best = None
    for im in images:
        a = np.asarray(on_white(im), dtype=np.float32) / 255
        if a.shape[0] < 100 or abs(a.shape[0] - a.shape[1]) > 0.05 * a.shape[0]:
            continue
        if best is None or a.size > best.size:
            best = a
    if best is None:
        return None
    ink = best < 0.9
    ys, xs = np.nonzero(ink.sum(axis=1) > 0.3 * ink.shape[1])[0], np.nonzero(ink.sum(axis=0) > 0.3 * ink.shape[0])[0]
    images = [best[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1]] if len(ys) and len(xs) else []
    listed = {l for c in clues for l in c["lights"]}
    first = None
    for a in images + [best]:
        h, w = a.shape
        for n in range(5, 28):
            ph, pw = h / n, w / n
            means = np.array([[float(a[int(y * ph + ph * 0.45):int(y * ph + ph * 0.85),
                                       int(x * pw + pw * 0.45):int(x * pw + pw * 0.85)].mean())
                               for x in range(n)] for y in range(n)])
            block = means.min()
            if block > 0.75:
                continue
            white = means >= 0.85
            dark = np.abs(means - block) <= 0.12
            if (white | dark).all():
                grid = ["".join("." if c else "#" for c in row) for row in white]
                lights = set(rg.light_cells(grid))
                if lights == listed:
                    return grid
                score = len(lights & listed) - len(lights ^ listed)
                if first is None or score > first[0]:
                    first = (score, grid)
    return first and first[1]


def unstretched(rects):
    """The rectangles with the page's height rescaled until the grid's ruled
    frame is square: some PDFs print the grid stretched (No 157's 285 x 252
    frame, cells 17.6 x 15.6), which read_grid takes for no grid."""
    long = [r for r in rects if min(r[2] - r[0], r[3] - r[1]) < 2 and max(r[2] - r[0], r[3] - r[1]) >= 100]
    wide = [r[2] - r[0] for r in long if r[2] - r[0] > r[3] - r[1]]
    tall = [r[3] - r[1] for r in long if r[3] - r[1] > r[2] - r[0]]
    if len(wide) < 6 or len(tall) < 6:
        return rects
    k = max(wide) / max(tall)
    return [(x0, y0 * k, x1, y1 * k) + tuple(rest) for x0, y0, x1, y1, *rest in rects]


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
    # A light printed "[unclued]" or "(See instructions)" has no clue: it is
    # left out, as an unclued light the clue list skips is.
    out["marked"] = {l for c in out["clues"] if UNCLUED_MARK.fullmatch(c["clue"]) for l in c["lights"]}
    out["clues"] = [c for c in out["clues"] if not UNCLUED_MARK.fullmatch(c["clue"])]
    see_links(out["clues"])
    # No numbered run and the clues all in what is left: an unnumbered list.
    if not out["clues"] and unnumbered(out["preamble"]) >= UNNUMBERED_AT:
        out["unplaced"], out["preamble"] = unplaced_clues(out["preamble"])
    rects = fpp.filled_rects(ops)
    grid = fpp.read_grid(rects) or fpp.read_grid(unstretched(rects))
    out["kind"] = "vector" if grid else None
    if grid is None:
        grid = image_grid(reader.pages, out["clues"])
        out["kind"] = "image" if grid else None
    out["grid"] = grid
    out["text"] = bool(raw.strip())
    out["origin"] = "the Guardian's printable PDF"
    if grid:
        turn_links(out["clues"], set(rg.light_cells(grid)))
    return out


#: Where an article's own text runs: its standfirst, then its body up to
#: the topic links that follow every article.
#: The capture starts past the opening tag's close: from the attribute alone
#: its rest (` class="dcr-47amn7">`) has no "<" for the tag strip to take,
#: and was filed as the preamble of every Genius read off its article page.
ARTICLE_PARTS = re.compile(r'data-gu-name="(?:standfirst|body)"[^>]*>(.*?)(?=<[^<>]*data-gu-name="|Explore more on these topics|</article>)', re.S)


def article_text(body):
    """The article's standfirst and body as one flat line."""
    parts = ARTICLE_PARTS.findall(body)
    t = " ".join(re.sub(r"<script.*?</script>|<style.*?</style>", " ", x, flags=re.S) for x in parts)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"(?i)click here to access the print version|Photograph: \w+", " ", t)
    return flat(t, kerned=False)


def read_article(number):
    """read_pdf's fields off an article page with no PDF: preamble and clues
    from its text, the grid from the largest square picture it shows."""
    from PIL import Image
    body = article_path(number).read_text(encoding="utf-8", errors="replace")
    text = article_text(body)
    out = parse_text(text)
    out["number"] = out["number"] if out["number"] == int(number) else None
    by = re.search(r'"byline":"([^"]+)"', body)
    out["setter"] = out["setter"] or (by and by.group(1))
    out["marked"] = {l for c in out["clues"] if UNCLUED_MARK.fullmatch(c["clue"]) for l in c["lights"]}
    out["clues"] = [c for c in out["clues"] if not UNCLUED_MARK.fullmatch(c["clue"])]
    see_links(out["clues"])
    images = []
    for path in image_paths(number):
        try:
            images.append(Image.open(path))
        except OSError:
            continue
    grid = grid_of_images(images, out["clues"])
    out.update(grid=grid, kind="image" if grid else None, text=bool(text), article=True,
               origin="the Guardian's article page and its grid picture")
    if grid:
        turn_links(out["clues"], set(rg.light_cells(grid)))
    return out


def turn_links(clues, lights):
    """A linked clue's later part the grid has only the other way round, and
    no other clue claims that way, is that way: "22/11/25" with no 11 down."""
    flip = {"across": "down", "down": "across"}
    listed = {l for c in clues for l in c["lights"]}
    for c in clues:
        for i, (n, d) in enumerate(c["lights"][1:], 1):
            if (n, d) not in lights and (n, flip[d]) in lights and (n, flip[d]) not in listed:
                c["lights"][i] = (n, flip[d])
                listed.add((n, flip[d]))


def see_links(clues):
    """A link's later parts take their direction from their own "See N"
    entry: "20/4" heads the Across list, and "4 See 20 Across" in the Down
    list says the 4 is 4 down."""
    seen = {c["lights"][0] for c in clues if c["enumeration"] is None and len(c["lights"]) == 1}
    flip = {"across": "down", "down": "across"}
    # "23 See 26" under a clue headed "26" alone: 26's answer runs on into 23.
    # A number may lead both ways (1 across and 1 down): "13 across See 1"
    # joins the one whose heading already names it, else the one its own
    # way, else the only one; a light another heading already names is
    # taken (No 22's "1,13" and 1 down; No 58's twelve-part 21 across).
    leading = collections.defaultdict(list)
    for c in clues:
        if c["enumeration"]:
            leading[c["lights"][0][0]].append(c)
    linked = {l for c in clues for l in c["lights"][1:]}

    def leader_of(n, stub):
        ways = leading.get(n, [])
        own = [x for x in ways if x["lights"][0][1] == stub[1]]
        return own[0] if len(own) == 1 else (ways[0] if len(ways) == 1 else None)
    for c in clues:
        if c["lights"][0] in linked:
            continue
        m = c["enumeration"] is None and len(c["lights"]) == 1 and re.fullmatch(
            r"See (\d{1,2})(?:\s*(across|down))?", c["clue"], re.IGNORECASE)
        # "See 12 across" names its way: No 162 has a 12 down as well.
        way = m and m.group(2) and m.group(2).lower()
        lead = m and (next((x for x in clues if x["enumeration"] and x["lights"][0] == (int(m.group(1)), way)), None)
                      if way else leader_of(int(m.group(1)), c["lights"][0]))
        # Two clues may start on one light (No 209's 22 across leads
        # "22,17,3" and "22,2,5"): a stub one of them already lists is placed.
        held = bool(m) and any(c["lights"][0][0] in [l[0] for l in x["lights"][1:]] for x in clues
                               if x["enumeration"] and x["lights"][0][0] == int(m.group(1)))
        if lead and not held and c["lights"][0] not in lead["lights"] and not any(
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
    for f in fsq.category_post_files(cat):
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
#: Or the setter, then a dash and the post's own headline: "Guardian Genius
#: 96 / Araucaria – A Masochist's Delight"; or a headline ending ", by Paul".
POST_SETTER_HEADED = re.compile(r"Genius\D{0,12}\d{1,3}\s*[/:]\s*([A-Z][a-z]+)\s+[–—-]\s|,\s+by\s+([A-Z][a-z]+)\s*$")


#: The post's first words naming the setter: "Lavatch is a setter whose".
POST_BODY_SETTER = re.compile(r"([A-Z][a-z]+)\s+is\s+a\s+setter\b")


def post_setter(post):
    title = html.unescape(post.get("title", {}).get("rendered", "")) if post else ""
    m = POST_SETTER.search(title) or POST_SETTER_HEADED.search(title)
    if m:
        return next((g for g in m.groups() if g), None)
    # An untitled-setter post that opens "Lavatch is a setter whose puzzles ...".
    body = re.sub(r"<[^>]+>", " ", post.get("content", {}).get("rendered", "")) if post else ""
    m = POST_BODY_SETTER.match(html.unescape(body).strip()[:200])
    return m and m.group(1)


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

#: Counts in the text left over from the numbered clues that make it an
#: unnumbered clue list: a preamble prints one at most.
UNNUMBERED_AT = 5


def unnumbered(text):
    """How many clues in text end on a count with no clue number before
    their words: numbered ones left there are another misread (No 157)."""
    parts = re.split(fpp.ENUM_TEXT, text or "")[:-1]
    return sum(not re.match(r"\s*\d", x) for x in parts)


#: The instruction run on before an unnumbered clue in the same stretch of
#: text: whole sentences at least this long, ending on a full stop, where no
#: clue's words would run before its own full stop.
INSTRUCTION_AT = 60


def unplaced_clues(text):
    """([(clue, count)] in printed order, preamble or None) off text that
    prints its clues with no numbers (No 280: "Clues are listed in
    alphabetical order of their answers ..."). Each clue ends on its count; an
    instruction printed between two clues is the sentences before the second
    clue's start (INSTRUCTION_AT), and what follows the last count is
    instruction too."""
    clues, said, at = [], [], 0
    for m in re.finditer(fpp.ENUM_TEXT, text or ""):
        words = text[at:m.start()].strip()
        stop = None
        for s in re.finditer(r"[.!](?=\s+[A-Z\u2018\u201c\"'])", words):
            stop = s.end() if s.end() >= INSTRUCTION_AT else stop
        if stop:
            said.append(words[:stop].strip())
            words = words[stop:].strip()
        clues.append((f"{words} {m.group(0)}", fpp.ENUM.search(m.group(0)).group(1)))
        at = m.end()
    said.append((text or "")[at:].strip())
    return clues, " ".join(x for x in said if x) or None


#: Where each clue of a jigsaw goes: light -> the start of its clue as
#: printed in the unnumbered list. The post prints answers by light but not
#: the clues, so the placing is its parses' (No 76: "COATI COAT + 1" is
#: "Carnivore's fur first", "VRAIC RA in VIC" "Boy entertaining one who
#: paints kelp"). Each clue goes once, every unnumbered light takes one, and
#: its count must be its light's length; the post's answers must then cross.
JIGSAW = {
    76: {(5, "across"): "Anti-Shakespearean pig", (9, "across"): "Eat well",
         (10, "across"): "Stout hero", (11, "across"): "Flowers (Latin",
         (13, "across"): "Voice on top", (14, "across"): "Barren function",
         (23, "across"): "Boy entertaining", (25, "across"): "Mother of the nine",
         (26, "across"): "Own up to drug", (27, "across"): "Carnivore",
         (28, "across"): "About this French", (2, "down"): "Radio part",
         (3, "down"): "Land of salts", (5, "down"): "Profit on drinks",
         (6, "down"): "Straight flier", (7, "down"): "Without a bit of feeling",
         (15, "down"): "Little letters", (17, "down"): "Model way",
         (18, "down"): "Cupboard", (19, "down"): "Art in tears",
         (21, "down"): "To wit unknown", (22, "down"): "Draw a distinction",
         (24, "down"): "I hold Communist"},
    # Each entry the post prints fits one light only, against the numbered
    # answers' letters: CAUSATION is the only nine with A second and T sixth.
    250: {(1, "down"): "Sound of shower", (5, "down"): "Heading away from Quantico",
          (6, "down"): "Split smoothed over", (8, "across"): "Lugs around",
          (11, "across"): "Booty call", (12, "across"): "Sanded steel peg",
          (17, "across"): "One announces credit", (20, "across"): "Sacking bishop",
          (21, "down"): "Taunt fool", (23, "down"): "Set within new design",
          (26, "across"): "For ever and ever", (27, "across"): "Branch I"},
}


#: A puzzle the Guardian re-posted years late, so its URL carries the re-post date:
#: the day its article page datePublished gives instead.
DATED = {2: "2003-07-30"}  # url 2016/feb/04/genius-crossword-2; page published 2003-07-30

#: A Genius the schema cannot hold yet, and why: assemble() reports it so
#: rather than as the reader's first complaint about it.
SCHEMA_GAP = {}


def split_shared_leaders(pdf, answers):
    """Take out of pdf["clues"] each clue starting on a light an earlier clue
    starts on (No 209: "22,17,3" and "22,2,5" both start at 22 across), and
    stand its other lights in as one-light clues, so build() files the
    light's first answer as usual. Returns [(clue, its answer or None)] for
    join_shared_leaders. `answers` gains each stand-in light's letters."""
    first, out, keep = set(), [], []
    for c in pdf["clues"]:
        if c["enumeration"] and c["lights"][0] in first:
            out.append(c)
        else:
            keep.append(c)
            if c["enumeration"]:
                first.add(c["lights"][0])
    if not out:
        return []
    lights = rg.light_cells(pdf["grid"])
    taken, shared = {l for c in keep if c["enumeration"] for l in c["lights"]}, []
    for c in out:
        whole, at = (answers or {}).get(("shared", len(shared))), 0
        for light in c["lights"]:
            k = len(lights[light])
            if light not in taken:
                keep = [x for x in keep if x["lights"] != [light]]
                keep.append({"lights": [light], "clue": "-", "enumeration": str(k)})
                if whole and answers is not None:
                    answers[light] = whole[at:at + k]
            at += k
        shared.append((c, whole))
    pdf["clues"] = keep
    return shared


def shared_answers(rendered, clues):
    """blog_answers, where two clues starting on one light would collide on
    its key: each later one is read with the clues before it on that light
    left out, and kept under ("shared", i) for split_shared_leaders."""
    starts, later = [], []
    for c in clues:
        if c["enumeration"] and c["lights"][0] in starts:
            later.append(c)
        elif c["enumeration"]:
            starts.append(c["lights"][0])
    out = blog_answers(rendered, [c for c in clues if not any(c is x for x in later)])
    for i, c in enumerate(later):
        rest = [x for x in clues if x is c or not (x["enumeration"] and x["lights"][0] == c["lights"][0])]
        got = blog_answers(rendered, rest).get(c["lights"][0])
        if got:
            out[("shared", i)] = got
    return out


def printed_order(puzzle, clues):
    """Each linked clue's group in the order its heading prints its lights
    ("22,17,3": IVOR HUGH JEGO), its separators placed again over that order:
    build() groups the "See N" lights by number, 3 down before 17 down."""
    import fetch_puzzle
    by_id = {groups.entry_id(e): e for e in puzzle["entries"]}
    for c in clues:
        ids = [f"{n}-{d}" for n, d in c["lights"]]
        lead = by_id.get(ids[0])
        if (not c["enumeration"] or lead is None or lead.get("group") == ids
                or sorted(lead.get("group") or []) != sorted(ids)):
            continue
        lead["group"] = ids
        for eid, seps in zip(ids, fetch_puzzle.separators(c["enumeration"], [by_id[i]["length"] for i in ids])):
            by_id[eid]["clue"].pop("separators", None)
            if seps:
                by_id[eid]["clue"]["separators"] = seps
    return puzzle


def join_shared_leaders(puzzle, shared):
    """Put each split_shared_leaders clue back as its leader's alsoLeads, its
    stand-in lights back to "See N" continuations."""
    by_id = {groups.entry_id(e): e for e in puzzle["entries"]}
    for c, _ in shared:
        (n, way), ids = c["lights"][0], [f"{x}-{d}" for x, d in c["lights"]]
        lead = by_id[ids[0]]
        lead.setdefault("alsoLeads", []).append(
            {"clue": enumeration.clue(c["clue"]), "group": ids})
        for x, d in c["lights"][1:]:
            e = by_id[f"{x}-{d}"]
            if e["clue"].get("text") == "-":
                e["clue"] = {"text": f"See {n}" if d == way else f"See {n} {way}"}
    return puzzle


def place_jigsaw(number, pdf):
    """None once JIGSAW's placing has moved the unnumbered clues out of the
    preamble onto their lights, else why not."""
    table = JIGSAW.get(number)
    if not table or pdf["grid"] is None:
        return "no placing for its clues"
    pre, lights = pdf["preamble"], rg.light_cells(pdf["grid"])
    starts = {l: pre.find(t) for l, t in table.items()}
    if min(starts.values()) < 0 or len(set(starts.values())) != len(starts):
        return "a placed clue is not in the unnumbered list"
    listed = {l for c in pdf["clues"] for l in c["lights"]}
    if set(table) != set(lights) - listed:
        return "the placing does not cover the unnumbered lights"
    order = sorted(table, key=starts.get)
    ends = [starts[l] for l in order[1:]] + [len(pre)]
    after = ""
    for light, end in zip(order, ends):
        # A clue runs to its count; what follows the last is the preamble's
        # rest (No 250 prints its instructions under the list).
        m = re.search(fpp.ENUM_TEXT, pre[starts[light]:end])
        if not m or (end < len(pre) and pre[starts[light] + m.end():end].strip()):
            return f"{light[0]} {light[1]}'s clue does not end on one count"
        text = pre[starts[light]:starts[light] + m.end()].strip()
        after = pre[starts[light] + m.end():end] if end == len(pre) else after
        count = m.group(0).strip("() ")
        # An answer altered on entry (ALTERED_BY) counts the answer, not the
        # light: assemble_altered's crossings check that one.
        if number not in ALTERED_BY and sum(int(n) for n in re.findall(r"\d+", count)) != len(lights[light]):
            return f"{light[0]} {light[1]}'s count is not its length"
        pdf["clues"].append({"lights": [light], "clue": text, "enumeration": count})
        pdf.setdefault("placed", {})[light] = text
    pdf["preamble"] = " ".join(x for x in (pre[:min(starts.values())].strip(), after.strip()) if x) or None
    pdf["clues"].sort(key=lambda c: (c["lights"][0][1] != "across", c["lights"][0][0]))
    pdf["jigsaw"] = True
    return None


def assemble(number, pdf, post, date, url):
    """(puzzle, None) or (None, (class, why not))."""
    if not pdf["text"]:
        return None, ("PDF has no text", "")
    if pdf["number"] not in (None, number):
        return None, ("PDF is another puzzle", f"PDF says No {pdf['number']}")
    pdf["setter"] = pdf["setter"] or post_setter(post)
    if number in SCHEMA_GAP:
        return None, SCHEMA_GAP[number]
    if not pdf["clues"]:
        if pdf.get("unplaced"):
            return None, (HELD_JIGSAW, f"{len(pdf['unplaced'])} clues printed without numbers")
        return None, ("clue list unread", "")
    # Clues printed with no number (No 76: "Solutions to the remaining clues
    # have their indicated place", then an alphabetical list) fall out of the
    # numbered runs into the preamble. Their lights are the solver's to find,
    # and a post that prints answers only cannot place them.
    if unnumbered(pdf["preamble"]) >= UNNUMBERED_AT:
        why = place_jigsaw(number, pdf)
        if why:
            return None, ("clue list unnumbered (jigsaw)", why)
    if pdf["grid"] is None:
        return None, ("grid unread", "")
    # Clues that print no count and are no "See N" stub (No 233's across
    # clues, whose answers move in the grid) take their light's length for
    # the numbering check and keep no enumeration when filed.
    lights = rg.light_cells(pdf["grid"])
    withheld = [c for c in pdf["clues"] if c["enumeration"] is None and len(c["lights"]) == 1
                and not fpp.SEE.match(c["clue"]) and c["lights"][0] in lights]
    for c in withheld:
        c["enumeration"] = str(len(lights[c["lights"][0]]))
    why = fpp.grid_matches(pdf["grid"], pdf["clues"], misprinted(number))
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
    # An article page (No 135 and before) prints no preamble in its text: what
    # the puzzle says is on the grid picture alone, which is not OCRed. Its
    # clues and grid are read all the same, and it files with no preamble.
    if not pdf["preamble"] and not pdf.get("article"):
        return None, ("preamble unread", "")
    # Only the clues are mandatory: with no post the puzzle files unsolved,
    # its grid and clues as printed, and the nightly backfill solves it
    # (whatever the preamble does to the entries).
    if post is None:
        return unsolved(number, pdf, date, url, withheld)
    if withheld:
        return None, ("enumerations withheld", "answers read by count, and these clues print none")
    if pdf["preamble"] and ALTERED.search(pdf["preamble"]):
        return None, ("preamble alters entries (needs an alteration per answer)", "")
    if post is None:
        return None, ("no fifteensquared post", "")
    answers = shared_answers(post["content"]["rendered"], pdf["clues"])
    shared = split_shared_leaders(pdf, answers)
    entries = fpp.entries_of(pdf, answers, pdf["grid"])
    if entries is None or not all(whole for _, whole in shared):
        missing = [c["lights"][0] for c in pdf["clues"]
                   if c["enumeration"] and c["lights"][0] not in answers]
        missing += [c["lights"][0] for c, whole in shared if not whole]
        return None, ("a light's answer not read off the post", f"{len(missing)} missing, {missing[:3]}")
    rec = {"post_id": f"fifteensquared-{post['id']}", "link": post.get("link"),
           "date": post["date"][:10], "series": CATEGORY, "number": number,
           "setter": pdf["setter"], "entries": entries}
    row = {"grid": pdf["grid"], "number": number, "how": pdf["origin"]}
    puzzle, why = file_blog_puzzles.build(rec, row, SERIES, date, pdf["setter"], pairs=True)
    if why:
        if why == "answers disagree with the grid":
            return None, ("answers cross wrongly (entries altered)", why)
        return None, (why, "")
    printed_order(puzzle, pdf["clues"])
    join_shared_leaders(puzzle, shared)
    if pdf["preamble"]:
        puzzle["preamble"] = pdf["preamble"]
    if pdf.get("jigsaw"):
        puzzle["cluesUnplaced"] = True
    puzzle["source"] = {"url": url, "gridOrigin": "published"}
    puzzle["solutions"]["check"] = (
        f"grid and clues read from {pdf['origin']}, its numbering matching "
        "the clue list; every fifteensquared answer written into it with each crossing agreeing")
    return puzzle, None


#: assemble()'s class for a puzzle that prints every clue without a number:
#: file() holds it clues-only (hold_jigsaw) and the nightly solve answers it.
HELD_JIGSAW = "held clues-only (unnumbered jigsaw)"


def hold_jigsaw(number, pdf, date, url):
    """(clues_only record, problems) for a Genius printing every clue with no
    number (pdf["unplaced"]): the record promote_jigsaw files once solved."""
    import clues_only
    meta = {"id": series_meta.puzzle_id(SERIES, number), "number": number, "series": SERIES,
            "name": f"Guardian genius crossword No {number}", "setter": pdf["setter"],
            "date": date.isoformat(), "source": {"url": url}}
    record, problems = clues_only.from_jigsaw(meta, pdf["unplaced"], pdf["preamble"], GENERATOR)
    if not pdf["grid"]:
        problems.append("no grid read off the PDF: a Genius jigsaw is filed on the grid it prints")
    else:
        record["dimensions"] = {"cols": len(pdf["grid"][0]), "rows": len(pdf["grid"])}
    return record, problems


def promote_jigsaw(record, answers, grid=None):
    """(puzzle, problems): a held Genius jigsaw filed unsolved on the grid
    its PDF prints (`grid`, else read off the PDF again), each light given the
    clue whose answer fills it (jigsaw_fit.fit_grid). puzzle["_parts"] maps
    each entry id to (clue index, letters), as clues_only._jigsaw_build's does."""
    import jigsaw_fit
    number = record["number"]
    if grid is None and pdf_path(number).exists():
        grid = read_pdf(pdf_path(number))["grid"]
    if grid is None:
        return None, [f"no grid read off {pdf_path(number)}"]
    lights, given = record["clues"]["unplaced"], answers.get("unplaced") or []
    if len(given) != len(lights):
        return None, [f"{len(given)} answers for {len(lights)} jigsaw clues"]
    placed, why = jigsaw_fit.fit_grid(given, grid)
    if why:
        return None, [why]
    # An answer taking no light is entered off the grid (the preamble says
    # where), filed only when its length is exactly its clue's count.
    off = [n for n in range(len(given)) if n not in {p[0] for p in placed}]
    wrong = [f"{given[n]} ({lights[n].get('length')})" for n in off
             if len(given[n]) != lights[n].get("length")]
    if wrong:
        return None, [(f"{len(wrong)} answers that take no light of the printed grid do not "
                       f"match their clue's count: {', '.join(wrong)}")]
    starts = sorted({(x, y) for _, x, y, _ in placed}, key=lambda c: (c[1], c[0]))
    numbers = {c: k for k, c in enumerate(starts, 1)}
    clues, parts = [], {}
    for n, x, y, d in placed:
        c = lights[n]["clue"]
        light = (numbers[(x, y)], d)
        clues.append({"lights": [light], "enumeration": c.get("enumeration"),
                      "clue": f"{c['text']} ({c['enumeration']})" if c.get("enumeration") else c["text"]})
        parts[groups.entry_id({"number": light[0], "direction": d})] = (n, given[n])
    clues.sort(key=lambda c: (c["lights"][0][1] != "across", c["lights"][0][0]))
    pdf = {"clues": clues, "grid": grid, "setter": record.get("setter"),
           "preamble": record.get("preamble"), "origin": "the Guardian's printable PDF"}
    puzzle, why = unsolved(number, pdf, datetime.date.fromisoformat(record["date"]),
                           record["source"]["url"])
    if why:
        return None, [f"{why[0]}: {why[1]}"]
    puzzle["cluesUnplaced"] = True
    if off:
        puzzle["offGrid"] = [{"clue": lights[n]["clue"]} for n in off]
        parts.update({cid: (n, given[n]) for (cid, _), n in zip(groups.off_grid(puzzle), off)})
    puzzle["_parts"] = parts
    return puzzle, []


#: Lights whose printed count the paper got short, filed with the count as
#: printed. No 60's article page prints "8, 5 across Rochdale cries ... (6)"
#: and "20, 25 Here's rosy gore, ruining Trigger's saddle (3)": GRACIE FIELDS
#: and ROY ROGERS, each counted only as far as its first light, while its
#: other linked clues (1,27,10 (6,12); 34,15 (6,5)) count them all. Filed,
#: the count fits its own light, which puzzle_integrity.check_length accepts
#: for a linked head, so no PUBLISHED_WRONG row is needed there.
MISPRINTED = {
    60: {(8, "down"): "GRACIE FIELDS (6,6) over 8 down + 5 across, printed (6)",
         (20, "down"): "ROY ROGERS (3,6) over 20 down + 25 down, printed (3)"},
}


def misprinted(number):
    """The lights of `number` whose printed count MISPRINTED says is short."""
    return set(MISPRINTED.get(number, {}))


def unsolved(number, pdf, date, url, withheld=()):
    """(puzzle, None) or (None, why not): the grid and clues with no answers."""
    # No post and a page that names nobody: "no source names a setter" is the
    # recorded state (series.py unbylinedUnsolved), so the puzzle files without one.
    shared = split_shared_leaders(pdf, None)
    entries = fpp.entries_of(pdf, None, pdf["grid"])
    rec = {"post_id": None, "link": url, "date": None, "series": CATEGORY, "number": number,
           "setter": pdf["setter"], "entries": entries}
    row = {"grid": pdf["grid"], "number": number, "how": pdf["origin"]}
    puzzle, why = file_blog_puzzles.build(rec, row, SERIES, date, pdf["setter"])
    if why:
        return None, (why, "unsolved")
    printed_order(puzzle, pdf["clues"])
    join_shared_leaders(puzzle, shared)
    # The stand-in counts of clues that print none come off again.
    held = {c["lights"][0] for c in withheld}
    for e in puzzle["entries"]:
        if (e["number"], e["direction"]) in held:
            e["clue"].pop("enumeration", None)
    if pdf["preamble"]:
        puzzle["preamble"] = pdf["preamble"]
    puzzle["source"] = {"url": url, "gridOrigin": "published"}
    return puzzle, None


# ------------------------------------------------------------------ altered entries

#: What each preamble's rule makes of an answer, applied by code: the
#: entries the answer may go in as besides itself.
RULE_OPS = {
    "reversed": lambda w: {w[::-1]},
    "vowels removed": lambda w: {re.sub("[AEIOU]", "", w)},
    "a letter dropped": lambda w: {w[:i] + w[i + 1:] for i in range(len(w))},
    "a letter dropped or added": lambda w: {w[:i] + w[i + 1:] for i in range(len(w))},
    "a letter dropped wherever it occurs": lambda w: {w.replace(c, "") for c in set(w)},
    "Caesar-shifted": lambda w: {"".join(chr((ord(c) - 65 + k) % 26 + 65) for c in w) for k in range(1, 26)},
}
#: Rules that go both ways: the entry is the answer made by the rule, or
#: the answer is the entry made by it (a letter added is one dropped back).
TWO_WAY = {"a letter dropped or added"}
#: Each Genius whose preamble alters answers in a way code can check: the
#: rule (RULE_OPS) code applies to make entries the post may not print, or
#: None, and the alteration ops its entries may take. An entry differing
#: from its answer any other way, or in a puzzle not listed, files nothing.
ALTERED_BY = {
    154: ("reversed", {"reversal"}),          # "entered in one of two ways"
    181: ("a letter dropped", {"deletion"}),  # "one letter too long for the grid"
    196: ("a letter dropped", {"deletion"}),  # "a letter removed before entry"
    197: ("vowels removed", {"deletion"}),    # "ll vwls hv bn rmvd frm bth cls nd sltns"
    210: ("Caesar-shifted", {"substitution"}),  # the preamble enciphered so; PATH as ALES
    216: (None, {"anagram"}),                 # downs "treated" by the acrosses: letters sorted
    220: (None, {"substitution"}),            # Morse code's dots and dashes swapped
    221: ("a letter dropped or added", {"deletion", "insertion"}),  # 8 a letter long, 8 a letter short
    222: (None, {"substitution"}),            # acrosses entered as homophones
    226: (None, {"substitution"}),            # "one single-letter change"
    239: ("a letter dropped", {"deletion"}),  # "entered without this letter"
    248: (None, {"move"}),                    # acrosses rotated: DEMOTE as EMOTED
    263: ("a letter dropped wherever it occurs", {"deletion"}),
    250: (None, {"insertion"}),                # a pair of letters put in twelve jigsaw answers
}
#: A post naming an entry apart from the answer: "entered as EMOTED".
NAMED_ENTRY = re.compile(r"(?i:entered as|entry(?: is)?:?|enter(?:ing)?|becomes?|giving|gives|"
                         r"→|->|=>|>)\s*[‘'\"(]?([A-Z]+(?:[ '’\-][A-Z]+)*)(?![a-z])")
#: The capitals a post line opens with, its number stripped.
#: A one-letter word carries on only into more capitals: "CATCH A COLD",
#: not "EXTREMISM I think".
HEADLINE = re.compile(r"\s*[‘'\"]?([A-Z]+(?:[ '’\-](?:[A-Z]{2,}|[A-Z](?=[ '’\-][A-Z])))*)(?![a-z])")
#: The same with letters bracketed off, "HOOT(NANNY)", "[BORIS] GODUNOV".
BRACKETED = re.compile(r"\s*((?:[\[(]?[A-Z]+[\])]?)(?:[ '’\-]?[\[(]?[A-Z]+[\])]?)*)(?![a-z])")


def windows(rendered, clues):
    """{first light: [post lines]}: each clue's lines, from the one opening
    with its number to the next clue's, walked as fpp.blog_answers walks them."""
    sections, way = collections.defaultdict(list), None
    for ln in fpp.tftt.lines(rendered):
        h = fpp.ft_puzzles.heading(ln) if ln else None
        if h:
            way = h
        elif way and ln:
            sections[way].append(ln)
    out = {}
    for direction in ("across", "down"):
        sec = sections.get(direction, [])
        mine = [c for c in clues if c["lights"][0][1] == direction and c["enumeration"]]
        starts, pos = [], 0
        for c in mine:
            at = next((i for i in range(pos, len(sec))
                       if (m := fpp.LIGHT_HEAD.match(sec[i])) and int(m.group(1)) == c["lights"][0][0]), None)
            starts.append(at)
            if at is not None:
                pos = at + 1
        for i, (c, at) in enumerate(zip(mine, starts)):
            if at is not None:
                end = next((s for s in starts[i + 1:] if s is not None), len(sec))
                out[c["lights"][0]] = [fpp.STRIP_HEAD.sub("", sec[at])] + sec[at + 1:end]
    return out


def letters(s):
    return re.sub(r"[^A-Z]", "", s.upper())


def sources(lines, answer):
    """The words the post prints for a clue, in order: the answer its
    enumeration reads, the capitals each line opens with (bracketed letters
    kept and dropped), and those it names as an entry."""
    words = [answer] if answer else []
    for ln in lines:
        m = HEADLINE.match(ln)
        if m:
            words.append(letters(m.group(1)))
        b = BRACKETED.match(ln)
        if b and re.search(r"[\[(]", b.group(1)):
            words += [letters(b.group(1)), letters(re.sub(r"[\[(][A-Z]+[\])]", "", b.group(1)))]
        words += [letters(x) for x in NAMED_ENTRY.findall(ln)]
    return list(dict.fromkeys(w for w in words if len(w) > 1))


def candidates(words, rule):
    """Every entry the post's words allow: each word, and what the
    preamble's rule makes of it."""
    out = set(words)
    if rule:
        out |= {v for w in words for v in RULE_OPS[rule](w) if v}
    return out


def unique_fill(slots, limit=2):
    """[{key: word}] of up to `limit` ways to give each slot one of its words
    with every shared square agreeing. slots: {key: (cells, {word})}."""
    found, at = [], {}

    def go(left, chosen):
        if len(found) >= limit:
            return
        if not left:
            found.append(dict(chosen))
            return
        def fits(k):
            cells, words = slots[k]
            return [w for w in words if all(at.get(c, ch) == ch for c, ch in zip(cells, w))]
        k = min(left, key=lambda k: len(fits(k)))
        cells, _ = slots[k]
        for w in fits(k):
            put = list(dict.fromkeys(c for c in cells if c not in at))
            for c, ch in zip(cells, w):
                at.setdefault(c, ch)
            chosen[k] = w
            go(left - {k}, chosen)
            del chosen[k]
            for c in put:
                del at[c]

    go(set(slots), {})
    return found


def steps_for(before, after, allowed):
    """The one alteration step of an op the preamble allows that turns
    `before` into `after`, or None."""
    ops = puzzle_integrity.ALTERATION_OPS
    for op in ("reversal", "move", "anagram", "deletion", "insertion", "substitution"):
        if op in allowed and ops[op](before, after):
            return [{"op": op}]
    return None


def assemble_altered(number, pdf, post, date, url):
    """(puzzle, None) or (None, why not) for a Genius whose entries are not
    all its answers: each light's entry is one the post prints for it or the
    preamble's rule (ALTERED_BY) makes of its answer, and the grid takes exactly one
    choice of them with every crossing agreeing. An entry not its answer
    carries the answer as `alteration.from`."""
    # An article page printing no preamble (assemble) may still take the
    # post's words where its layout hides them from blog_answers, but with no
    # rule to read, every entry must be a word the post prints for it.
    if post is None or not (pdf["preamble"] or pdf.get("article")):
        return None, "no post or no preamble"
    preamble = pdf["preamble"] or ""
    lights = rg.light_cells(pdf["grid"])
    clued = [c for c in pdf["clues"] if c["enumeration"]]
    listed = {l for c in pdf["clues"] for l in c["lights"]}
    if not listed <= set(lights):
        return None, "lights and clue list differ"
    # A numbered light the clue list leaves out is unclued: it takes a word
    # the post prints beside its number, else its crossings' letters.
    unclued = [l for l in lights if l not in listed]
    # The clue list itself may say a light has no clue, printing "See
    # preamble" or "[unclued]" in its place (No 165's eight theme lights):
    # that is the setter's word as much as the preamble's, once the preamble
    # it points to is read. An article page never holds the preamble (No
    # 112's "See special instructions" points to a megaclue printed beside
    # the grid), so there the clue list's marks are the setter's word alone.
    declared = (bool(preamble) or bool(pdf.get("article"))) and set(unclued) <= pdf.get("marked", set())
    if unclued and not declared and not re.search(
            r"(?i)\bunclued|not clued|no clues?\b|without (?:a )?clues?", preamble):
        return None, f"{len(unclued)} lights unclued, and the preamble says none is"
    if len(unclued) > MOST_UNCLUED:
        return None, f"{len(unclued)} lights unclued: more than a preamble leaves, so the clue list is misread"
    clued = sorted(clued + [{"lights": [l], "enumeration": str(len(lights[l])), "clue": None}
                            for l in unclued], key=lambda c: (c["lights"][0][1], c["lights"][0][0]))
    rendered = DASHES.sub("-", re.sub(r"&#(?:820[89]|821[012]|x201[0-4]);", "-", post["content"]["rendered"]))
    answers, wins = blog_answers(rendered, pdf["clues"]), windows(rendered, clued)
    rule, ops = ALTERED_BY.get(number, (None, set()))
    slots, said = {}, {}
    for c in clued:
        first = c["lights"][0]
        cells = [cell for l in c["lights"] for cell in lights[l]]
        said[first] = sources(wins.get(first, []), answers.get(first))
        if first in pdf.get("placed", {}):
            said[first] = placed_words(rendered, pdf["placed"][first]) or said[first]
        words = {w for w in candidates(said[first], rule) if len(w) == len(cells)}
        given = UNCLUED_LETTERS.get(number, {}).get(first)
        if first in unclued and given:
            said[first], words = [given], {given}
            if words:
                slots[first] = (cells, words)
            continue
        if not words:
            return None, f"no entry the post or rule gives fits {first[0]} {first[1]}"
        slots[first] = (cells, words)
    # Of the fills whose crossings all agree, the one taking fewest words
    # the rule made rather than the post printed; a tie files nothing.
    fills = unique_fill(slots, limit=50)
    made = [sum(w not in said[k] for k, w in f.items()) for f in fills]
    best = [f for f, m in zip(fills, made) if m == min(made, default=0)]
    if len(best) != 1 or len(fills) == 50:
        return None, f"{len(best) or 'no'} fills of the post's entries agree at every crossing"
    fill = best[0]
    at = {cell: ch for k, w in fill.items() for cell, ch in zip(slots[k][0], w)}
    for l in unclued:
        if l not in fill:
            if not all(cell in at for cell in lights[l]):
                return None, f"unclued {l[0]} {l[1]}: the post prints no entry and crossings leave a square open"
            fill[l] = "".join(at[cell] for cell in lights[l])
            said[l] = [fill[l]]
    # The answer: where the preamble's rule is code's, the first word the
    # post prints that the rule turns into the entry, else the entry itself;
    # otherwise the first word printed that is the entry or that an op the
    # preamble allows turns into it.
    altered = {}
    for k, w in fill.items():
        if rule:
            frm = next((x for x in said[k] if x != w and steps_for(x, w, ops) and (
                w in RULE_OPS[rule](x) or (rule in TWO_WAY and x in RULE_OPS[rule](w)))),
                w if w in said[k] else None)
        else:
            frm = next((x for x in said[k] if x == w or steps_for(x, w, ops)), None)
        if frm is None:
            return None, f"{k[0]} {k[1]}: no {'/'.join(sorted(ops)) or 'alteration the preamble allows'} turns what the post prints ({', '.join(said[k][:3])}) into {w}"
        if frm != w:
            altered[k] = frm
    if altered and not preamble:
        return None, "an entry is not its answer, and no preamble printed says how"
    if not altered and ALTERED.search(preamble):
        return None, "the post prints entries alone: no answer before its alteration"
    entries = fpp.entries_of(pdf, {k: w for k, w in fill.items() if k not in unclued}, pdf["grid"])
    entries += [{"number": n, "direction": d, "answer": fill[(n, d)], "clue": "Unclued",
                 "enumeration": str(len(fill[(n, d)]))} for n, d in unclued]
    rec = {"post_id": f"fifteensquared-{post['id']}", "link": post.get("link"),
           "date": post["date"][:10], "series": CATEGORY, "number": number,
           "setter": pdf["setter"], "entries": entries}
    row = {"grid": pdf["grid"], "number": number, "how": pdf["origin"]}
    puzzle, why = file_blog_puzzles.build(rec, row, SERIES, date, pdf["setter"], pairs=True)
    if why:
        return None, why
    by = {(e["number"], e["direction"]): e for e in puzzle["entries"]}
    for k in unclued:
        by[k]["clue"] = {"missing": True}
    for k, frm in altered.items():
        if len(next(c for c in clued if c["lights"][0] == k)["lights"]) > 1:
            return None, f"{k[0]} {k[1]} is a linked answer entered altered"
        by[k]["alteration"] = {"from": frm, "steps": steps_for(frm, fill[k], ops)}
        # A count printed for the answer, not the entry (No 250's HALE (4)
        # entered HANDLE), stays as printed: it may count either word.
        printed = next(c for c in clued if c["lights"][0] == k)["enumeration"]
        if printed and printed.isdigit() and int(printed) == len(frm) != len(fill[k]):
            by[k]["clue"]["enumeration"] = printed
            by[k]["clue"].pop("separators", None)
    if preamble:
        puzzle["preamble"] = preamble
    if pdf.get("jigsaw"):
        puzzle["cluesUnplaced"] = True
    puzzle["source"] = {"url": url, "gridOrigin": "published"}
    puzzle["solutions"]["check"] = (
        f"grid and clues read from {pdf['origin']}, its numbering matching the "
        "clue list; each light's entry one fifteensquared prints for it"
        + (f" or the preamble's rule ({rule}) makes of its answer" if rule else "")
        + ", the only choice of them whose crossings all agree; an entry not its answer "
          "carries the answer as its alteration's `from`")
    return puzzle, None


def placed_words(rendered, clue):
    """A jigsaw clue's words off the post row printing it, which numbers no
    light: "SA CAUTION / CAU SA TION Heading away ..." gives the answer
    before the slash and the entry after it, CAUTION and CAUSATION."""
    text = DASHES.sub("-", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", rendered))))
    at = text.find(DASHES.sub("-", clue)[:20])
    if at < 0:
        return []
    row = text[max(text.rfind(" - ", 0, at), at - 80) + 1:at].split("/")
    out = [re.findall(r"[A-Z]{2,}", row[0])[-1:], ["".join(re.findall(r"[A-Z]+", row[-1]))]]
    return [w for ws in out for w in ws if w]


#: The most unclued lights a Genius leaves; more says the clue list was misread.
MOST_UNCLUED = 10
#: Unclued lights whose letters the post gives only as a quotation and the path
#: it takes, written out per light. No 112: Groucho Marx's "I never forget a
#: face, but in your case I'll be glad to make an exception", from square 26
#: clockwise round the edge (up 8, along 1, down 9, back along 26), then up 22.
#: The crossings must still agree with every clued answer.
UNCLUED_LETTERS = {
    112: {(1, "across"): "ACEBUTINYOURC", (8, "down"): "FATEGROFREVEN",
          (9, "down"): "ASEILLBEGLADT", (26, "across"): "IPECXENAEKAMO",
          (22, "down"): "NOITP"},
}
#: The classes assemble() leaves that the altered-entry path may file.
ALTERABLE = {"preamble alters entries (needs an alteration per answer)",
             "answers cross wrongly (entries altered)", "enumeration is not the entry's length",
             "a light's answer not read off the post", "lights left unclued",
             "grid numbering differs from clue list"}
#: The classes left after the grid matched the clue list, when only the
#: post's answers fail to go in (an early post printing them in a layout the
#: reader misses, or entries the preamble alters some way code cannot check).
#: Only the clues are mandatory, so such a puzzle files unsolved, as one with
#: no post does, and the nightly backfill solves it.
UNSOLVED_FALLBACK = {"a light's answer not read off the post",
                     "answers cross wrongly (entries altered)",
                     "preamble alters entries (needs an alteration per answer)"}


def hold(number, pdf, date, url, write):
    """file()'s (class, why) for an unnumbered jigsaw: held clues-only in
    clues_only/ when `write` and its record passes, refused otherwise."""
    import clues_only
    record, problems = hold_jigsaw(number, pdf, date, url)
    if not problems and write:
        try:
            return HELD_JIGSAW, str(clues_only.write(record))
        except puzzle_integrity.RefusedWrite as e:
            problems = [str(e)]
    if problems:
        return "clue list unnumbered (jigsaw), not held", "; ".join(problems)[:200]
    return HELD_JIGSAW, "not written (--dry-run)"


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
        if not pdf_path(n).exists() and not article_path(n).exists():
            blocked["no PDF or article"].append(n)
            continue
        counts["fetched"] += 1
        if puzzle_path(SERIES, n).exists():
            counts["already filed"] += 1
            continue
        try:
            pdf = read_pdf(pdf_path(n)) if pdf_path(n).exists() else read_article(n)
            if pdf["clues"] and pdf["number"] in (None, n):
                counts["parsed"] += 1
            if pdf["grid"] and not fpp.grid_matches(pdf["grid"], pdf["clues"]):
                counts["grid consistent with clues"] += 1
            date = datetime.date.fromisoformat(DATED.get(n, idx[str(n)]["date"]))
            puzzle, why = assemble(n, pdf, posts.get(n), date, idx[str(n)]["url"])
            if why and why[0] == HELD_JIGSAW:
                why = hold(n, pdf, date, idx[str(n)]["url"], write)
            if why and why[0] in ALTERABLE:
                alt, also = assemble_altered(n, pdf, posts.get(n), date, idx[str(n)]["url"])
                puzzle, why = (alt, None) if alt else (None, (why[0], f"{why[1]}; altered: {also}"))
            if why and why[0] in UNSOLVED_FALLBACK:
                # Read afresh: the tries above share leaders and stand in counts.
                fresh = read_pdf(pdf_path(n)) if pdf_path(n).exists() else read_article(n)
                fresh["setter"] = fresh["setter"] or post_setter(posts.get(n))
                bare, also = unsolved(n, fresh, date, idx[str(n)]["url"])
                puzzle, why = (bare, None) if bare else (None, (why[0], f"{why[1]}; unsolved: {also[0]}"))
        except Exception as e:  # any raise: a malformed PDF is one puzzle
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
