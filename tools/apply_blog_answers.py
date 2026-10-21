#!/usr/bin/env python3
"""Fill a held puzzle's missing answers from the blog that wrote it up.

The Times' Gale scans give us 2006-2014 clues and grid but no answers, and
timesforthetimes.co.uk has a post per puzzle listing every answer. The
fetch/parse tools skip those posts (they want clue text, which the old posts
lack), so the answers were never used. Here the post is read only for its
numbered answers (tools/parse_timesforthetimes.parse_post), matched to the
held puzzle's lights by number, direction and length, and written only when

  * every light of the puzzle gets exactly one answer of exactly its length
  * every crossing cell agrees (apply_solution.check_fill, the same check a
    blind solve passes)
  * no answer already in the file is contradicted (a disagreement is logged
    and the puzzle left alone, never overwritten)

Written answers are marked as the blog's write-up (solutions.blog/url/date),
which is what a write-up keyed grid is everywhere else in the corpus.

Posts are fetched over the web from the blog's WordPress API a month at a time
(about 1 request a second) and cached under ~/.cache/cryptic-teacher/tftt, not
in the repo.

  python3 tools/apply_blog_answers.py --series times --check-only times-24473
  python3 tools/apply_blog_answers.py --series times --from 2006 --to 2014
"""
import argparse
import datetime
import itertools
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import apply_solution
import parse_timesforthetimes as ptt
import provenance
from fetch_puzzle import read_puzzle_file, reindex, write_puzzle_file
from groups import entry_id

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
API = "https://timesforthetimes.co.uk/wp-json/wp/v2/posts"
FIELDS = "id,date,slug,link,title,content,categories"
CACHE = Path.home() / ".cache" / "cryptic-teacher" / "tftt"
PUZZLES = Path(__file__).resolve().parent.parent / "puzzles"
DELAY = 1.0
#: Blog categories (parse_timesforthetimes.SERIES) that hold each series.
CATEGORIES = {"times": (11, 21, 26)}
#: Puzzle numbers a series' posts can carry; anything else is another puzzle.
NUMBER_RANGE = {"times": (20000, 29999)}

_last = [0.0]


def get(url, tries=4):
    """JSON and headers for `url`, at most one request a second."""
    wait = DELAY - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                _last[0] = time.time()
                return json.load(r), r.headers
        except urllib.error.HTTPError as e:
            if e.code == 400:                 # WordPress: page past the end
                return [], {}
            if attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == tries - 1:
                raise
        time.sleep(10 * 2 ** attempt)


def month_posts(cat, year, month):
    """Every post of category `cat` dated in the month, cached on disk."""
    path = CACHE / f"{cat}-{year}-{month:02d}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    after = datetime.date(year, month, 1)
    before = datetime.date(year + (month == 12), month % 12 + 1, 1)
    posts, page = [], 1
    while True:
        url = (f"{API}?categories={cat}&per_page=100&page={page}&orderby=date&order=asc"
               f"&after={after}T00:00:00&before={before}T00:00:00&_fields={FIELDS}")
        batch, headers = get(url)
        posts += batch
        if len(batch) < 100:
            break
        page += 1
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(posts), encoding="utf-8")
    return posts


def blog_records(series, year, month):
    """number -> [parsed post record] for posts dated in or right after the month."""
    lo, hi = NUMBER_RANGE[series]
    found = {}
    for cat in CATEGORIES[series]:
        for post in month_posts(cat, year, month):
            number = ptt.puzzle_number(post)
            if number and lo <= number <= hi:
                rows = (table_lines(post["content"]["rendered"])
                        or break_lines(post["content"]["rendered"]))
                if rows:
                    found.setdefault(number, []).append(
                        {"number": number, "link": post["link"], "date": post["date"][:10],
                         "rows": rows})
    return found


def held(series, year):
    """(path, puzzle) for each file of the series dated `year` with a blank light."""
    for path in sorted((PUZZLES / series / str(year)).glob(f"{series}-*.json")):
        puzzle = read_puzzle_file(path)
        if any(not (e.get("solution") or "").strip() for e in puzzle["entries"]):
            yield path, puzzle


AZED_API = "https://fifteensquared.net/wp-json/wp/v2/posts"


def azed_records(number):
    """The fifteensquared write-ups of Azed `number`, cached on disk. Its table
    has No., Clue and Wordplay columns: the answer is read off the wordplay."""
    import html
    path = CACHE / f"azed-{number}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    posts, _ = get(f"{AZED_API}?search=Azed+{number}&per_page=10&_fields={FIELDS}")
    found = []
    for post in posts:
        title = html.unescape(post["title"]["rendered"])
        if not re.search(rf"\bAzed\s+{number}\b", title, re.I):
            continue
        rows = table_lines(post["content"]["rendered"], last_only=True)
        if rows:
            found.append({"number": number, "link": post["link"], "date": post["date"][:10],
                          "rows": rows, "blog": "fifteensquared"})
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(found), encoding="utf-8")
    return found


BIGDAVE_API = "https://bigdave44.com/wp-json/wp/v2/posts"
#: puzzle series -> the blog's post slugs for puzzle number `n`.
BIGDAVE_SLUGS = {
    "telegraph": ("dt-{n}", "dt-cryptic-no-{n}", "dt-{n}-full-review", "dt{n}"),
    "toughie": ("toughie-{n}", "toughie-{n}-full-review", "toughie{n}"),
    "sundaytel": ("st-{n}", "st-{n}-full-review", "st{n}"),
}
HEADING = re.compile(r"\b(across|down)\b", re.I)
CLUE_HEAD = re.compile(r"^\s*(\d{1,2})\s*(?:ac|dn|a|d)?\b", re.I)
#: the further lights of a linked clue head: "9a &amp; 21d", "28, 7".
LINKED_HEAD = re.compile(r"(?:&|and|,|/)\s*(\d{1,2})\s*(ac|dn|a|d)?\b", re.I)
LINKED_LEAD = re.compile(
    r"^\s*\d{1,2}\s*(?:ac|dn|a|d)?\s*((?:(?:&|and|,|/)\s*\d{1,2}\s*(?:ac|dn|a|d)?\b\s*)+)", re.I)
#: The answer between curly brackets, however many <span>s the blogger nested in it.
HIDDEN_ANSWER = re.compile(r"\{(.*?)\}", re.S)
#: A clue's printed enumeration, which ends the clue when no <br> does.
ENUMERATION = re.compile(r"\(\s*\d[\d,\-–\s]*\)")
#: A Sunday post prints the answer in capitals at the head of the line under the clue.
LEAD_CAPS = re.compile(r"^([A-Z][A-Z' \-]*[A-Z])(?=\s*(?:[–—]|-\s|$))")


def bigdave_rows(html_text):
    """[(direction, number, answer)] from a bigdave44 review. A Daily Telegraph or
    Toughie post hides each answer in {curly brackets} under its numbered clue; a
    Sunday post opens the line under the clue with the answer in capitals. A line
    that gives neither keeps an empty answer, so the light is reported unmatched."""
    import html
    direction, rows = None, []
    for para in re.split(r"</p>", ptt.DELETED.sub("", html_text)):
        heading = HEADING.search(para)
        if heading and cell_text(para).lower().strip(": ") in ("across", "down"):
            direction = heading.group(1).lower()
            continue
        if not direction:
            continue
        if "<br" in para:
            head, rest = re.split(r"<br\s*/?>", para, 1)
        else:       # clue and answer run on in one line: "1a Windbag (3-7) LAW ABIDING – ..."
            plain = TAGS.sub("", para)
            end = ENUMERATION.search(plain)
            if not end:
                continue
            head, rest = plain[:end.end()], plain[end.end():]
        m = CLUE_HEAD.match(cell_text(head))
        if not m:
            continue
        lead = LINKED_LEAD.match(cell_text(head))
        also = ",".join(f"{n}{w[:1].lower()}" for n, w in LINKED_HEAD.findall(lead.group(1))) if lead else ""
        hidden = HIDDEN_ANSWER.search(rest)
        if hidden:
            answer = cell_text(hidden.group(1))
        else:
            lead = LEAD_CAPS.match(cell_text(rest))
            answer = lead.group(1) if lead else ""
        rows.append((direction, int(m.group(1)),
                     f"{also}|{html.unescape(answer)}" if also and answer else html.unescape(answer),
                     cell_text(rest)[:500]))
    return rows


def _by_slugs(api, slugs):
    query = "&".join(f"slug[]={s}" for s in slugs)
    return get(f"{api}?{query}&per_page=10&_fields={FIELDS}")[0]


def bigdave_records(puzzle):
    """The bigdave44 write-ups of a Telegraph, Toughie or Sunday Telegraph
    puzzle, fetched by slug and cached on disk."""
    series, number = puzzle["id"].rsplit("-", 1)[0], puzzle["number"]
    path = CACHE / "bigdave-2" / f"{series}-{number}.json"
    if path.exists():
        posts = json.loads(path.read_text(encoding="utf-8"))
    else:
        posts = _by_slugs(BIGDAVE_API, [s.format(n=number) for s in BIGDAVE_SLUGS[series]])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(posts), encoding="utf-8")
    found = []
    for post in posts:      # the raw posts are cached, so a parser fix needs no refetch
        rows = bigdave_rows(post["content"]["rendered"])
        if rows:
            found.append({"number": number, "link": post["link"], "date": post["date"][:10],
                          "rows": rows, "blog": "bigdave44"})
    return found


def ft_records(puzzle):
    """The fifteensquared write-ups of a Financial Times cryptic, found by date
    (its search does not match numbers) and read off the bold answers in order."""
    import html
    number = puzzle["number"]
    path = CACHE / "ft" / f"ftcryptic-{number}.json"
    if path.exists():
        posts = json.loads(path.read_text(encoding="utf-8"))
    else:
        day = datetime.date.fromisoformat(puzzle["date"])
        posts, _ = get(f"{AZED_API}?after={day - datetime.timedelta(days=1)}T00:00:00"
                       f"&before={day + datetime.timedelta(days=5)}T00:00:00&per_page=100"
                       f"&_fields={FIELDS}")
        num = r"\s*,?\s*".join(re.escape(c) for c in f"{number:,}".split(",")) if number >= 1000 else str(number)
        posts = [p for p in posts
                 if re.search(rf"Financial\s+Times\s+{num}\b", html.unescape(p["title"]["rendered"]), re.I)]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(posts), encoding="utf-8")
    found = []
    for post in posts:
        rows = [(d, n, text.split(" – ")[0] if text.count(" – ") else "")
                for d, n, text in break_lines(post["content"]["rendered"], linked=True)]
        if rows:
            found.append({"number": number, "link": post["link"], "date": post["date"][:10],
                          "rows": rows, "blog": "fifteensquared"})
    return found


#: series -> the function that finds a held puzzle's write-ups.
SOURCES = {
    "telegraph": bigdave_records, "toughie": bigdave_records, "sundaytel": bigdave_records,
    "ftcryptic": ft_records,
    "azed": lambda puzzle: azed_records(puzzle["number"]),
}

ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
ROW_OR_HEADING = re.compile(
    r"(?P<row><tr\b[^>]*>.*?</tr>)|>\s*(?P<dir>across|down)\s*:?\s*<", re.I | re.S)
CELL = re.compile(r"<t([dh])\b[^>]*>(.*?)</t\1>", re.I | re.S)
TAGS = re.compile(r"<[^>]+>")
#: What the early posts print: a wordplay line whose answer follows the last
#: equals sign, or opens the line ("LIED, heteronymic double definition",
#: "CARD + US for ...", "E[LE]VEN").
AFTER_EQUALS = re.compile(r"=\s*([A-Z][A-Z'’ ,\-]*)")
QUOTED = re.compile(r"[“\"][^”\"]*[”\"]|‘[^’]*’")
DELETION = re.compile(r"\([a-z]+\)")
PIECE = re.compile(r"(?<![A-Za-z'’])[A-Z](?:[A-Z.]*[A-Z])?\.?(?![A-Za-z])")
LOWER_ANSWER = re.compile(r"^((?:[A-Za-z'’]+ ?){1,5}?)\s*(?:[–—]|\s-\s)")
LEADING = re.compile(r"^[\s\[\]()+A-Z'’,\-]+")


def cell_text(raw):
    """A table cell's text with struck-out letters gone."""
    import html
    text = ptt.DELETED.sub("", raw)
    return re.sub(r"\s+", " ", html.unescape(TAGS.sub("", text)).replace("\xa0", " ")).strip()


def candidates(text, length):
    """The answers of `length` letters that one write-up line can mean, best first."""
    out = []
    # An answer typed in ordinary case before its dash outranks any capitals in
    # the wordplay after it: "no matter – rOMe in NATTER".
    dashed = LOWER_ANSWER.match(text)
    if (dashed and not dashed.group(1).strip().isupper()
            and not re.search(r"(?i)omi|\bask\b|obvious|anagram|hidden|homophone|reversal",
                              dashed.group(1))):
        letters = re.sub(r"[^A-Z]", "", dashed.group(1).upper())
        if (len(letters) == length and dashed.group(1).strip().lower()
                not in ptt.PROSE_WORDS | ptt.WORDPLAY_WORDS):
            return [letters]
    for m in reversed(list(AFTER_EQUALS.finditer(text))):
        # An answer is followed by prose in lower case: "PERSEVERE or soldier on".
        letters = re.sub(r"[^A-Z]", "", m.group(1))
        words = m.group(1).split()
        for cut in range(len(words), 0, -1):
            letters = re.sub(r"[^A-Z]", "", "".join(words[:cut]))
            if len(letters) == length:
                out.append(letters)
                break
    # Letters dropped in square brackets, "VIC(TOR[y])IOUS", "STAG[e]", are not in it.
    lead = LEADING.match(re.sub(r"\[[a-z]+\]", "", text))
    if lead:
        letters = re.sub(r"[^A-Z]", "", lead.group(0))
        if len(letters) == length:
            out.append(letters)
    # A charade printed piece by piece, "MUZZLE=guard,LOADER=ordeal*": the
    # capitalised pieces in order, bracketed deletions and quoted glosses gone.
    bare = QUOTED.sub(" ", DELETION.sub("", text))
    total, got = 0, ""
    for tok in PIECE.findall(bare):
        letters = re.sub(r"[^A-Z]", "", tok)
        total, got = total + len(letters), got + letters
        if total >= length:
            break
    if total == length and got not in out:
        out.append(got)
    # The answer alone before the first mark: "THISTLE, TH(anagram of LIST)E",
    # "Bali – I thought of party". Capitals, or one word capitalised.
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    head = re.split(r"[,;:=–—]|\s-\s|\.(?:\s|$)", plain, 1)[0].strip()
    # …or one word typed in mixed case to hide itself in the grid: "uNcOuPlE".
    if (head and len(head.split()) <= 3
            and head.lower() not in ptt.PROSE_WORDS | ptt.WORDPLAY_WORDS
            and (head.isupper() or re.fullmatch(r"[A-Z][a-z]+", head)
                 or re.fullmatch(r"(?=.*[A-Z])(?=.*[a-z])[A-Za-z]+", head)
                 or re.fullmatch(r"[A-Z]{2}[A-Za-z()]*", head))):   # "HE(Ra)LD": an insertion
        letters = re.sub(r"[^A-Z]", "", head.upper())
        if len(letters) == length and letters not in out:
            out.append(letters)
    return list(dict.fromkeys(out))


def table_lines(html_text, last_only=False):
    """[(direction, number, text)] from the post's Across/Down tables."""
    direction, rows = None, []
    for token in ROW_OR_HEADING.finditer(html_text):
        if token.group("dir"):               # <p><b>Across</b></p> outside any table
            direction = token.group("dir").lower()
            continue
        cells = [(k.lower(), c) for k, c in CELL.findall(token.group("row"))]
        if len(cells) == 1 or (cells and cells[0][0] == "h"):
            head = cell_text(cells[0][1]).lower()
            if head.startswith("across"):
                direction = "across"
            elif head.startswith("down"):
                direction = "down"
            continue
        if len(cells) >= 2 and direction:
            num = re.fullmatch(r"(\d{1,2})\s*(?:ac|dn|a|d|across|down)?\.?", cell_text(cells[0][1]), re.I)
            if num:
                used = cells[-1:] if last_only else cells[1:]
                rows.append((direction, int(num.group(1)), cell_text(" ".join(c for _k, c in used))))
    return rows


BOLD = re.compile(r"<(strong|b)\b[^>]*>(.*?)</\1>", re.I | re.S)
NUMBERED_LINE = re.compile(r"^(\d{1,2})\s*(?:ac|dn|a|d|across|down)?\s*[.:)\-–]?\s+(.+)$", re.I)
#: "28,7 FINGAL": one answer spread over the lights numbered 28 and 7.
LINKED_LINE = re.compile(
    r"^(\d{1,2})((?:\s*,\s*\d{1,2})+)\s*(?:ac|dn|a|d|across|down)?\s*[.:)\-–]?\s+(.+)$", re.I)


def break_lines(html_text, linked=False):
    """[(direction, number, text)] from a post of <br>-separated lines:
    "1 <strong>MEALY BUG</strong> *(a blue gym)" under a bold ACROSS / DOWN.
    The bold word leads the text, as the answer."""
    direction, rows = None, []
    for piece in ptt.BREAKS.split(ptt.DELETED.sub("", html_text)):
        plain = cell_text(piece)
        head = plain.lower().rstrip(":")
        if head in ("across", "down"):
            direction = head
            continue
        m = NUMBERED_LINE.match(plain)
        others = ""
        if not m and linked:
            m = LINKED_LINE.match(plain)
            if m:       # the other numbers lead the text: "7|FINGAL – ..."
                others = re.sub(r"\s", "", m.group(2)).lstrip(",") + "|"
                m = re.match(r"(\d+)(.*)", f"{m.group(1)} {m.group(3)}")
        if not (m and direction):
            continue
        bold = BOLD.search(piece)
        answer = cell_text(bold.group(2)) if bold else ""
        rest = m.group(2).strip()
        rows.append((direction, int(m.group(1)),
                     others + (f"{answer} – {rest}" if answer and not answer[:1].isdigit() else rest)))
    return rows


def cross_fill(puzzle, fill):
    """Fill a light the post omitted from the letters its crossing lights give,
    when every one of its cells is crossed by an answered light."""
    cells = {}
    for e in puzzle["entries"]:
        if entry_id(e) in fill:
            x, y = e["position"]["x"], e["position"]["y"]
            for i, ch in enumerate(fill[entry_id(e)]):
                cells.setdefault((x + i, y) if e["direction"] == "across" else (x, y + i), ch)
    for e in puzzle["entries"]:
        if entry_id(e) in fill:
            continue
        x, y = e["position"]["x"], e["position"]["y"]
        spots = [(x + i, y) if e["direction"] == "across" else (x, y + i) for i in range(e["length"])]
        if all(s in cells for s in spots):
            fill[entry_id(e)] = "".join(cells[s] for s in spots)


def entry_key(number, direction):
    return f"{number}-{direction}"


WORDS = re.compile(r"[A-Za-z][A-Za-z'’\-]*")


def prose_fill(puzzle, fill, prose):
    """Fill a light whose answer the post names only in its prose (a typo'd or
    missing answer line, "...the elder which is a BUSH or shrub"). The word, or
    run of up to three words, must have exactly the light's length and agree
    with every letter its answered crossing lights already give, and be the only
    such reading: capitalised words need two crossing letters, any other words
    need at least half the light fixed."""
    for _ in range(len(puzzle["entries"])):
        cells = {}
        for e in puzzle["entries"]:
            if entry_id(e) in fill:
                x, y = e["position"]["x"], e["position"]["y"]
                for i, ch in enumerate(fill[entry_id(e)]):
                    cells.setdefault((x + i, y) if e["direction"] == "across" else (x, y + i), ch)
        progress = False
        for e in puzzle["entries"]:
            eid = entry_id(e)
            text = prose.get(eid)
            if eid in fill or not text:
                continue
            x, y = e["position"]["x"], e["position"]["y"]
            spots = [(x + i, y) if e["direction"] == "across" else (x, y + i) for i in range(e["length"])]
            known = [cells.get(s) for s in spots]
            fixed = sum(k is not None for k in known)
            words = WORDS.findall(text)
            found = {True: set(), False: set()}      # by whether every word is capitalised
            for i in range(len(words)):
                for n in (1, 2, 3):
                    run = words[i:i + n]
                    letters = re.sub(r"[^A-Z]", "", "".join(run).upper())
                    if len(run) == n and len(letters) == e["length"] and all(
                            k is None or k == c for k, c in zip(known, letters)):
                        found[all(w.isupper() and len(w) > 1 for w in run)].add(letters)
            pick = None
            if len(found[True]) == 1 and fixed >= 2:
                pick = next(iter(found[True]))
            elif not found[True] and len(found[False]) == 1 and fixed * 2 >= e["length"]:
                pick = next(iter(found[False]))
            if pick:
                fill[eid] = pick
                progress = True
        if not progress:
            return


_LEXICON = []


def lexicon():
    """The British-cryptic word list as upper-case letter runs: what tells a
    misprint's repair from a string of letters that is no word."""
    if not _LEXICON:
        path = Path(__file__).resolve().parent / "data" / "lexicon.tsv"
        _LEXICON.append({re.sub(r"[^A-Z]", "", line.split("\t", 1)[0].upper())
                         for line in path.open(encoding="utf-8") if not line.startswith("#")})
    return _LEXICON[0]


def repair_fill(puzzle, fill, typed):
    """Mend a light whose printed answer is a letter or two off ("ARENA" for AREA,
    "PUCK" for PUCKER, a letter dropped or added when the blogger typed it). The
    mended word must be in the lexicon, agree with every crossing letter already
    answered (letters it adds must be fixed by crossings), have at least half
    its cells fixed, and be the only such mend."""
    for _ in range(len(puzzle["entries"])):
        cells = {}
        for e in puzzle["entries"]:
            if entry_id(e) in fill:
                x, y = e["position"]["x"], e["position"]["y"]
                for i, ch in enumerate(fill[entry_id(e)]):
                    cells.setdefault((x + i, y) if e["direction"] == "across" else (x, y + i), ch)
        progress = False
        for e in puzzle["entries"]:
            eid = entry_id(e)
            if eid in fill or not typed.get(eid):
                continue
            x, y = e["position"]["x"], e["position"]["y"]
            spots = [(x + i, y) if e["direction"] == "across" else (x, y + i) for i in range(e["length"])]
            known = [cells.get(s) for s in spots]
            word, size = typed[eid], e["length"]
            if not 1 <= abs(len(word) - size) <= 2 or sum(k is not None for k in known) * 2 < size:
                continue
            made = set()
            if len(word) > size:                      # letters dropped, anywhere
                for cut in itertools.combinations(range(len(word)), len(word) - size):
                    made.add("".join(c for i, c in enumerate(word) if i not in cut))
            else:                                     # letters added where crossings give them
                for put in itertools.combinations(range(size), size - len(word)):
                    if all(known[i] for i in put):
                        rest = iter(word)
                        made.add("".join(known[i] if i in put else next(rest) for i in range(size)))
            made = {m for m in made if all(k is None or k == c for k, c in zip(known, m))
                    and m in lexicon()}
            if len(made) == 1:
                fill[eid] = made.pop()
                progress = True
        if not progress:
            return


def blog_fill(puzzle, rec):
    """(fill by entry id, reasons it cannot be) from one parsed post."""
    by_key, prose = {}, {}
    length = {(e["number"], e["direction"]): e["length"] for e in puzzle["entries"]}
    for direction, number, text, *line in rec.get("rows", []):
        if line:
            prose[entry_key(number, direction)] = line[0]
        linked = re.match(r"(\d+[ad]?(?:,\d+[ad]?)*)\|(.*)", text, re.S)
        if linked:
            # One answer over several lights ("28,7 FINGAL", "9a & 21d"): split in
            # numbered order when its letters exactly fill them. A trailing a/d
            # names the light's direction. Else the first light alone may take it.
            keys = [(number, direction)]
            for tok in linked.group(1).split(","):
                way = {"a": "across", "d": "down"}.get(tok[-1], direction)
                keys.append((int(tok.rstrip("ad")), way))
            letters = re.sub(r"[^A-Z]", "", linked.group(2).split(" – ")[0])
            if all(k in length for k in keys) and len(letters) == sum(length[k] for k in keys):
                for key in keys:
                    by_key.setdefault(key, []).append(letters[:length[key]])
                    letters = letters[length[key]:]
            elif keys[0] in length and len(letters) == length[keys[0]]:
                by_key.setdefault(keys[0], []).append(letters)
            continue
        by_key.setdefault((number, direction), []).append(text)
    fill, why, alts, typed = {}, [], {}, {}
    for entry in puzzle["entries"]:
        texts = by_key.get((entry["number"], entry["direction"]), [])
        options = list(dict.fromkeys(c for t in texts for c in candidates(t, entry["length"])))
        if options:
            fill[entry_id(entry)] = options[0]
            alts[entry_id(entry)] = options
        elif texts:
            if rec.get("blog") in ("bigdave44", "fifteensquared"):    # the text is the printed answer
                typed[entry_id(entry)] = re.sub(r"[^A-Z]", "", texts[0].split(" – ")[0])
            why.append(f"{entry_id(entry)}: no answer of {entry['length']} letters in the post's line")
        else:
            why.append(f"{entry_id(entry)}: the post gives no line")
    settle(puzzle, fill, alts)
    given = set(fill)
    # What the post does not print outright is worked out, and kept only when it
    # is a word: a crossing-derived string that is no word shows the grid or the
    # post is wrong at that light ("DISORDERDD").
    strict = rec.get("blog") in ("bigdave44", "fifteensquared")
    for derive in (lambda: prose_fill(puzzle, fill, prose),
                   lambda: repair_fill(puzzle, fill, typed),
                   lambda: cross_fill(puzzle, fill)):
        derive()
        if strict:
            for eid in [e for e in fill if e not in given and fill[e] not in lexicon()]:
                word = fill.pop(eid)
                note = f"{eid}: worked out {word}, which is no word"
                if note not in why:
                    why.append(note)
    return fill, [w for w in why if w.split(":")[0] not in fill]


DISAGREE = re.compile(r"((?:\d+)-(?:across|down))=")


def clashes(puzzle, fill):
    """The ids of the lights in each crossing cell where the fill disagrees."""
    return [DISAGREE.findall(p) for p in apply_solution.check_fill(puzzle, fill)[2]
            if "disagree" in p]


def settle(puzzle, fill, alts):
    """Where a post's line can be read two ways ("MAYOR = MAJOR with a change
    of middle letter"), take the reading that makes the crossings agree: swap a
    clashing light to another reading while that lowers the clashes."""
    for _ in range(25):
        now = clashes(puzzle, fill)
        if not now:
            return
        best = None
        for eid in {i for pair in now for i in pair}:
            for option in alts.get(eid, []):
                if option != fill[eid]:
                    trial = {**fill, eid: option}
                    score = len(clashes(puzzle, trial))
                    if score < len(now) and (best is None or score < best[0]):
                        best = (score, eid, option)
        if best is None:
            return
        fill[best[1]] = best[2]


#: --partial writes a puzzle the post leaves at most this many lights out of
#: (Times for the Times leaves out one or two on purpose).
MAX_OMITTED = 3


def judge(puzzle, rec, partial=False):
    """(fill, problems): the blog's answers and why they must not be written.
    With `partial`, a post that gives no line for a few lights is accepted:
    the lights missing from the fill are the ones to mark as left out."""
    fill, problems = blog_fill(puzzle, rec)
    # The omitted lights are the ones whose line carries no answer of the
    # right length (the blog blanks it) or that have no line at all.
    if problems and not (partial and len(problems) <= MAX_OMITTED
                         and len(fill) * 2 > len(puzzle["entries"])):
        return fill, ["unmatched " + problems[0].split(":", 1)[1].strip()
                      + f" ({len(problems)} lights)"]
    for entry in puzzle["entries"]:
        old = (entry.get("solution") or "").strip()
        # A light the post leaves out (blank in the fill) cannot disagree.
        if old and fill.get(entry_id(entry)) and old != fill[entry_id(entry)]:
            return fill, [f"disagrees with the file's {entry_id(entry)} "
                          f"({old} vs {fill.get(entry_id(entry))})"]
    _cells, crossings, bad = apply_solution.check_fill(puzzle, fill)
    bad = [b for b in bad if not (b.endswith("no answer given") and b.split(":")[0] not in fill)]
    bad += apply_solution.check_off_grid(puzzle, fill)
    if bad:
        return fill, [f"{len(bad)} crossing/length problem(s), first: {bad[0]}"]
    if not crossings:
        return fill, ["no crossing cells to check against"]
    return fill, []


def write(path, puzzle, rec, fill):
    omitted = [entry_id(e) for e in puzzle["entries"] if entry_id(e) not in fill]
    for entry in puzzle["entries"]:
        if entry_id(entry) in fill:
            entry["solution"] = fill[entry_id(entry)]
    crossings = apply_solution.check_fill(puzzle, fill)[1]
    given = len(puzzle["entries"]) - len(omitted)
    detail = {"blog": rec.get("blog", "timesforthetimes"), "url": rec["link"], "date": rec["date"],
              "check": (f"{given} of {len(puzzle['entries'])} entries" if omitted
                        else f"{len(puzzle['entries'])} entries")
                       + f", {crossings} crossings, 0 conflicts; "
                       "answers matched to the grid by number, direction and length"}
    if omitted:
        # The lights the blog left out: a model may fill these and no others
        # (provenance.partial_lights, apply_solution.check_writeup).
        detail["partial"] = omitted
    puzzle = provenance.with_solution_detail(puzzle, detail)
    write_puzzle_file(path, puzzle)


def process(series, year, only, check_only, log, partial=False):
    """Counts of outcomes for one year."""
    out = Counter()
    todo = {path: puzzle for path, puzzle in held(series, year)
            if (not only or puzzle["id"] in only)
            and not (puzzle.get("solutions") or {}).get("partial")}
    if not todo:
        return out
    recs = {}
    if series in CATEGORIES:
        months = sorted({(date.year, date.month) for puzzle in todo.values()
                         for date in [datetime.date.fromisoformat(puzzle["date"])]})
        for y, m in months:
            # A write-up is posted the day of the puzzle or soon after.
            for yy, mm in {(y, m), (y + (m == 12), m % 12 + 1)}:
                for number, items in blog_records(series, yy, mm).items():
                    recs.setdefault(number, []).extend(items)
    for path, puzzle in todo.items():
        pid = puzzle["id"]
        options = (recs.get(puzzle["number"], []) if series in CATEGORIES
                   else SOURCES[series](puzzle))
        if not options:
            out["no post"] += 1
            log(f"{pid}: REFUSED no post")
            continue
        verdicts = [(judge(puzzle, rec, partial), rec) for rec in options]
        good = [(fill, rec) for (fill, problems), rec in verdicts if not problems]
        if not good:
            reason = verdicts[0][0][1][0]
            out[re.sub(r"[A-Z0-9]+[-\w]*", "N", reason.split("(")[0])[:60]] += 1
            log(f"{pid}: REFUSED {reason} <{verdicts[0][1]['link']}>")
            continue
        fill, rec = good[0]
        if any(f != fill for f, _ in good):
            out["posts disagree"] += 1
            log(f"{pid}: REFUSED two posts give different answers")
            continue
        if check_only:
            out["would answer"] += 1
            log(f"{pid}: OK {rec['link']}")
            continue
        try:
            write(path, puzzle, rec, fill)
        except (Exception, SystemExit) as e:
            out["write refused"] += 1
            log(f"{pid}: REFUSED on write: {str(e)[:200]}")
            continue
        out["answered"] += 1
        log(f"{pid}: ANSWERED {rec['link']}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="only these puzzle ids")
    ap.add_argument("--series", default="times", choices=sorted(set(CATEGORIES) | set(SOURCES)))
    ap.add_argument("--from", dest="first", type=int, default=2006)  # the series have none earlier
    ap.add_argument("--to", dest="last", type=int, default=2014)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--partial", action="store_true",
                    help=f"also write a puzzle the post leaves up to {MAX_OMITTED} lights out of "
                         "(it gives no line for them): the checked answers plus solutions.partial "
                         "naming the blanks, which a model may then fill and no other light")
    ap.add_argument("--no-reindex", action="store_true",
                    help="leave puzzles/index.json for the caller to rebuild")
    args = ap.parse_args()

    def log(line):
        print(line, flush=True)

    total = Counter()
    for year in range(args.first, args.last + 1):
        counts = process(args.series, year, set(args.ids), args.check_only, log, args.partial)
        total += counts
        log(f"== {year}: {dict(counts)}")
    log(f"== total: {dict(total)}")
    if not args.check_only and not args.no_reindex and total["answered"]:
        reindex()


if __name__ == "__main__":
    sys.exit(main())
