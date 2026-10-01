#!/usr/bin/env python3
"""Check our puzzles against another copy of the same puzzle, class by class.

    python3 tools/cross_validate.py telegraph --fetch      # top up the source cache
    python3 tools/cross_validate.py telegraph              # diff from the cache, write the report
    python3 tools/cross_validate.py telegraph --show telegraph-28936
    python3 tools/cross_validate.py guardian --fetch --refile --limit 1500
                                                           # cache 1500 more pages, diff, refile
    python3 tools/cross_validate.py independent --fetch --refile --limit 1500
                                                           # the same against the Independent's feed
    python3 tools/cross_validate.py indyblog               # its answers against fifteensquared's

Most of the corpus came off a blog: the blogger retyped the clues, a parser
read the post, and tools/reconstruct_grid.py rebuilt the grid from the light
list. Where the paper also serves the puzzle itself, that copy is the printed
one, and every difference from ours is either our parser's defect or (rarely)
the paper's own mistake. puzzle_integrity.py can only check a puzzle against
itself; this checks it against a second witness.

A source adapter knows, for each puzzle id it covers, how to produce the
source's puzzle in our own shape (entries with number, direction, position,
length, clue {text, enumeration}, solution, group) from a cache it fills
politely with --fetch. diff() then compares the two and names each mismatch
by class:

  GRID         the white cells differ (a rebuilt grid that is not the printed one)
  NUMBERING    the same light, same length and answer, under another number
  MISSING      a light the source has and we lack
  EXTRA        a light we have and the source lacks
  ANSWER       the same light, another answer
  ENUMERATION  the same light, another printed count
  CLUE         the same light, other words once punctuation, quotes, dashes,
               case and whitespace are normalised away

The report goes to ~/cryptic-setter-data/cross-validate/<source>.jsonl, one
line per puzzle with mismatches, and a tally prints per class.

--refile (the guardian and independent adapters) then rewrites, from the source, each file whose
only differences are CLUE, ENUMERATION or ANSWER, each clean file taken from
somewhere other than the source, and (the Guardian) each file lacking the note
the page prints above the clues; see refile_guardian() and refile_independent().
"""
import argparse
import html
import json
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import groups
from fetch_puzzle import puzzle_files, read_puzzle_file

DATA = Path.home() / "cryptic-setter-data"
REPORTS = DATA / "cross-validate"
CLASSES = ("GRID", "NUMBERING", "MISSING", "EXTRA", "ANSWER", "ENUMERATION", "CLUE")


class Adapter:
    """One outside source. Subclasses set `name` and `series` and implement
    ids(), fetch_one() and puzzle()."""
    name = ""
    series = ()
    #: Seconds each worker waits between requests, and how many workers.
    delay = 0.5
    workers = 4

    @property
    def cache(self):
        return DATA / f"{self.name}-source"

    def ids(self):
        """{puzzle id: key} for every puzzle this source holds."""
        raise NotImplementedError

    def fetch_one(self, key):
        """Fetch one puzzle into the cache; no-op when cached."""
        raise NotImplementedError

    def puzzle(self, key):
        """The cached puzzle in our shape, or None when the source lacks it."""
        raise NotImplementedError

    def covers(self, ours):
        """Whether to compare: a puzzle we took from this source is the source."""
        return True


def http_get(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


class Telegraph(Adapter):
    """puzzlesdata.telegraph.co.uk, the Telegraph Puzzles app's bucket; see
    tools/fetch_telegraph.py, whose parse() turns a bucket puzzle into ours."""
    name = "telegraph"
    series = ("telegraph", "sundaytel", "toughie", "sundaytough")

    @property
    def cache(self):
        import fetch_telegraph as ft
        return ft.CACHE

    def calendar_file(self, year):
        return self.cache / "calendar" / f"{year}.json"

    def ids(self):
        import datetime

        import fetch_telegraph as ft
        import series as series_meta
        rows = []
        for year in range(ft.FIRST_YEAR, datetime.date.today().year + 1):
            path = self.calendar_file(year)
            if not path.exists() or year >= datetime.date.today().year:
                try:
                    body = http_get(f"{ft.BUCKET}/bundles/web/calendar/{year}.json", ft.UA)
                except urllib.error.HTTPError as err:
                    if err.code == 404:
                        continue
                    raise
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
                time.sleep(self.delay)
            rows += ft.calendar_rows(json.loads(path.read_text(encoding="utf-8")))
        return {series_meta.puzzle_id(s, n): (variant, slug)
                for s, n, _day, variant, slug in ft.in_order(rows)}

    def raw_file(self, key):
        variant, slug = key
        return self.cache / "puzzles" / variant / f"{slug}.json"

    def fetch_one(self, key):
        import fetch_telegraph as ft
        path = self.raw_file(key)
        if path.exists() or path.with_suffix(".404").exists():
            return False
        variant, slug = key
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            body = http_get(f"{ft.BUCKET}/puzzles/{variant}/{slug}.json", ft.UA)
        except urllib.error.HTTPError as err:
            if err.code in (403, 404):
                path.with_suffix(".404").write_text(str(err.code))
                return True
            raise
        path.write_bytes(body)
        return True

    def puzzle(self, key):
        import fetch_telegraph as ft
        path = self.raw_file(key)
        if not path.exists():
            return None
        return ft.parse(json.loads(path.read_text(encoding="utf-8")), key[0])

    def covers(self, ours):
        return (ours.get("source") or {}).get("acquiredBy") != "tools/fetch_telegraph.py"


class Guardian(Adapter):
    """theguardian.com's own crossword pages, the CrosswordComponent data
    tools/fetch_puzzle.py reads, for every series published there.

    The page is already where almost all of these came from, so the copy here
    is read independently of fetch_puzzle.convert(): tags stripped, entities
    unescaped, a trailing bracket of counts taken as the enumeration, the
    answer as served. What differs is then what our converter or a later edit
    did to the paper's data, plus the files taken from elsewhere (the Wayback
    Machine, observer.co.uk) for numbers the Guardian also serves.
    """
    name = "guardian"
    series = ("cryptic", "quiptic", "everyman")
    #: More than two at once draws 429s from theguardian.com.
    delay = 0.25
    workers = 2

    def ids(self):
        import fetch_puzzle as fp
        out = {}
        for pid, path in held(self).items():
            series, _, num = pid.rpartition("-")
            num = int(num)
            if series == "cryptic" and num in fp.NUMBER_URL_FIXES:
                out[pid] = fp.NUMBER_URL_FIXES[num][0].format(num=num)
                continue
            url = (read_puzzle_file(path).get("source") or {}).get("url") or ""
            if not url.startswith("https://www.theguardian.com/crosswords/"):
                if series != "everyman" or not fp.EVERYMAN_FLOOR <= num <= 4096:
                    continue
                url = f"https://www.theguardian.com/crosswords/everyman/{num}"
            out[pid] = url
        return out

    def raw_file(self, url):
        return self.cache / (url.split("/crosswords/", 1)[1] + ".json")

    def fetch_one(self, url):
        import fetch_puzzle as fp
        path = self.raw_file(url)
        if path.exists() or path.with_suffix(".404").exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            page = fp.http_get(url)
        except urllib.error.HTTPError as err:
            if err.code in (403, 404, 410):
                path.with_suffix(".404").write_text(str(err.code))
                return True
            raise
        path.write_text(json.dumps(fp.extract_crossword_data(page), ensure_ascii=False),
                        encoding="utf-8")
        return True

    def puzzle(self, url):
        path = self.raw_file(url)
        if not path.exists():
            return None
        return guardian_shape(json.loads(path.read_text(encoding="utf-8")), url)


GUARDIAN_TAIL = re.compile(r"\s*\(\s*(\d(?:[\d\s,.\-–—'’]| and )*(?:words?)?)\s*\)\s*$")


def guardian_shape(data, url):
    """The Guardian's CrosswordComponent data in our shape, read without
    fetch_puzzle's converter."""
    import fetch_puzzle as fp
    series = fp.series_of(data["id"])
    num = int(url.rstrip("/").rsplit("/", 1)[1])
    num = next((want for want, (page, forced) in fp.NUMBER_URL_FIXES.items()
                if forced and page.format(num=want) == url), num)
    entries = []
    for e in data["entries"]:
        s = html.unescape(re.sub(r"<[^>]*>", "", e.get("clue") or ""))
        s = " ".join("".join(c for c in s if unicodedata.category(c) != "Cf").split())
        m = GUARDIAN_TAIL.search(s)
        text, enum = (s[:m.start()], m.group(1)) if m else (s, None)
        entries.append({"number": e["number"], "direction": e["direction"],
                        "position": e["position"], "length": e["length"],
                        "clue": {"text": text, "enumeration": enum},
                        "solution": "".join(c for c in unicodedata.normalize(
                            "NFKD", e.get("solution") or "").upper()
                            if not unicodedata.combining(c)) or None})
    return {"id": f"{series}-{num}" if data.get("number") == num or num in fp.NUMBER_URL_FIXES
            else f"{series}-{data.get('number')}",
            "dimensions": data["dimensions"], "entries": entries}


class Independent(Adapter):
    """The Independent's own Arkadium feed, one Crossword Compiler XML per
    date key, for both series it carries; see tools/fetch_independent.py.

    The XML is read here without fetch_independent.parse()'s converter (only
    the puzzle's id is taken from it, since the number fixes and the two
    series' weekday rule live there): what differs is then what the converter
    or a later edit did to the feed's data. A file rebuilt from fifteensquared
    for a date the feed also serves is compared too, and --refile makes the
    feed its primary source; it never rewrites a file already from the feed.
    The feed starts in June 2015, so every rebuilt file so far predates it."""
    name = "independent"
    series = ("independent", "indysunday")
    #: A CDN: a request a second from each of three workers is polite.
    delay = 1.0
    workers = 3

    def ids(self):
        import fetch_independent as fi
        out = {}
        for pid, path in held(self).items():
            day = read_puzzle_file(path).get("date") or ""
            ymd = day[2:4] + day[5:7] + day[8:10]
            if len(ymd) == 6 and ymd not in fi.REPEATS:
                out[pid] = ymd
        return out

    def raw_file(self, ymd):
        return self.cache / f"c_{ymd}.xml"

    def fetch_one(self, ymd):
        import fetch_independent as fi
        path = self.raw_file(ymd)
        if path.exists() or path.with_suffix(".404").exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            body = fi.http_get(fi.FEED.format(ymd=ymd))
        except urllib.error.HTTPError as err:
            if err.code in (403, 404):
                path.with_suffix(".404").write_text(str(err.code))
                return True
            raise
        path.write_bytes(body)
        return True

    def puzzle(self, ymd):
        path = self.raw_file(ymd)
        if not path.exists():
            return None
        return independent_shape(path.read_bytes(), ymd)


def independent_shape(xml_bytes, ymd):
    """The feed's XML in our shape, its entries read without
    fetch_independent's converter: the grid's white cells and letters, each
    <word>'s runs, each clue's words and its format attribute as printed
    (a period, slash or space in it read as the comma it stands for). A clue
    fetch_independent.CLUE_FIXES proves garbled is read as printed, as
    witness() does for a known wrong answer."""
    import xml.etree.ElementTree as ET

    import fetch_independent as fi
    pid = fi.parse(xml_bytes, ymd)["id"]
    ns = fi.NS
    puz = ET.fromstring(fi.clean_xml_bytes(xml_bytes)).find(f".//{ns}rectangular-puzzle")
    grid = puz.find(f"{ns}crossword/{ns}grid")
    sol = {(int(c.get("x")) - 1, int(c.get("y")) - 1): c.get("solution").upper()
           for c in grid.findall(f"{ns}cell") if c.get("solution")}
    runs = {}
    for word in puz.findall(f"{ns}crossword/{ns}word"):
        runs[word.get("id")] = [(fi.span(s.get("x")), fi.span(s.get("y")))
                                for s in [word, *word.findall(f"{ns}cells")]]
    entries = []
    for clue in puz.iter(f"{ns}clue"):
        if clue.get("is-link"):
            continue
        nums = [int(n.rstrip("ADad")) for n in (clue.get("number") or "").split("/") if n.strip()]
        text = " ".join(html.unescape("".join(clue.itertext())).split())
        text = fi.fixed_clue(ymd, clue.get("word"), text) or text
        enum = re.sub(r",+", ",", re.sub(r"[./\s]", ",", (clue.get("format") or "").strip())) or None
        for i, (num, ((x1, x2), (y1, y2))) in enumerate(zip(nums, runs[clue.get("word")])):
            across = x2 > x1 or y1 == y2
            length = (x2 - x1 if across else y2 - y1) + 1
            e = {"number": num, "direction": "across" if across else "down",
                 "position": {"x": x1 - 1, "y": y1 - 1}, "length": length,
                 "clue": ({"text": text, "enumeration": enum} if i == 0
                          else {"text": f"See {nums[0]}", "enumeration": None})}
            e["solution"] = "".join(sol.get(c, "") for c in cells(e)) or None
            entries.append(e)
    return {"id": pid, "dimensions": {"cols": int(grid.get("width")),
                                      "rows": int(grid.get("height"))},
            "entries": entries}


class IndyBlog(Adapter):
    """fifteensquared's answers for the Independent's two series: the post
    cache tools/fetch_fifteensquared.py fills, then georgeho's scrape of the
    same blog, read through tools/corroborate.py. Offline; --fetch is a no-op.

    A blog prints no grid and retypes the clues, so the source puzzle is ours
    with only each answer the blog prints in full for the light swapped in: it
    witnesses ANSWER alone. Where the feed's key is wrong in one cell, both
    crossing lights differ from ours there and agree with each other."""
    name = "indyblog"
    series = ("independent", "indysunday")

    def ids(self):
        return held(self)

    def fetch_one(self, path):
        return False

    def puzzle(self, path):
        import copy

        import corroborate
        ours = read_puzzle_file(path)
        said = {}
        for rec in corroborate.fifteensquared(ours) + corroborate.georgeho(ours):
            for light, answer in rec.answers.items():
                said.setdefault(light, answer)
        theirs = copy.deepcopy(ours)
        fits = 0
        for e in theirs["entries"]:
            got = said.get((e["number"], e["direction"]))
            e["solution"] = got if got and len(got) == e["length"] else None
            fits += bool(e["solution"])
        return theirs if fits else None

    def covers(self, ours):
        return (ours.get("source") or {}).get("acquiredBy") != "tools/indy_puzzles.py"


ADAPTERS = {a.name: a for a in (Telegraph, Guardian, Independent, IndyBlog)}


def held(adapter):
    """{puzzle id: path} for every puzzle on disk in the adapter's series."""
    out = {}
    for path in puzzle_files():
        if path.parent.parent.name in adapter.series:
            out[path.stem] = path
    return out


def fetch(adapter, todo):
    """Fetch every key in `todo` not yet cached, `workers` at a time, each
    waiting `delay` between requests."""
    lock = threading.Lock()
    done = Counter()

    def one(key):
        for attempt in range(3):
            try:
                got = adapter.fetch_one(key)
                break
            except Exception as err:  # noqa: BLE001 — retried, then reported
                if attempt == 2:
                    with lock:
                        done["failed"] += 1
                        print(f"failed {key}: {err}", flush=True)
                    return
                time.sleep(5 * (attempt + 1))
        with lock:
            done["fetched" if got else "cached"] += 1
            n = sum(done.values())
            if got and n % 100 == 0:
                print(f"{n}/{len(todo)} {dict(done)}", flush=True)
        if got:
            time.sleep(adapter.delay)

    with ThreadPoolExecutor(adapter.workers) as pool:
        list(pool.map(one, todo))
    print(f"fetch done: {dict(done)}", flush=True)


QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "`": "'", "–": "-", "—": "-",
                        "−": "-", "…": "...", " ": " "})
CONTINUATION = re.compile(r"^\s*see\b", re.IGNORECASE)


def norm_text(text):
    """Clue words with punctuation, quotes, dashes, case and spacing removed:
    what is left differing is a different word."""
    s = unicodedata.normalize("NFKC", html.unescape(text or "")).translate(QUOTES)
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def norm_enum(enum):
    return re.sub(r"\s+", "", (enum or "").replace(" and ", ",")).replace("-", ",") or None


def cells(entry):
    x, y = entry["position"]["x"], entry["position"]["y"]
    dx, dy = (1, 0) if entry["direction"] == "across" else (0, 1)
    return [(x + dx * i, y + dy * i) for i in range(entry["length"])]


def letters(puzzle):
    """{cell: {letter, ...}} over the entries that carry a solution."""
    out = defaultdict(set)
    for e in puzzle["entries"]:
        sol = e.get("solution") or ""
        if len(sol) == e["length"]:
            for c, ch in zip(cells(e), sol):
                out[c].add(ch)
    return out


def crossings_agree(puzzle, entry, answer):
    """Whether `answer` in `entry`'s cells agrees with every crossing light's
    letter in `puzzle` (a crossing without a solution is no evidence)."""
    across = entry["direction"] == "across"
    mine = {c: ch for c, ch in zip(cells(entry), answer)}
    checked = agree = 0
    for e in puzzle["entries"]:
        if (e["direction"] == "across") == across or len(e.get("solution") or "") != e["length"]:
            continue
        for c, ch in zip(cells(e), e["solution"]):
            if c in mine:
                checked += 1
                agree += mine[c] == ch
    return checked, agree


def where(e):
    return (e["position"]["x"], e["position"]["y"], e["direction"])


def diff(ours, theirs):
    """[{class, ...}] for every way `ours` differs from `theirs`."""
    out = []
    if ours.get("dimensions") != theirs.get("dimensions"):
        out.append({"class": "GRID", "detail": "dimensions",
                    "ours": ours.get("dimensions"), "theirs": theirs.get("dimensions")})
        return out
    mine = {c for e in ours["entries"] for c in cells(e)}
    paper = {c for e in theirs["entries"] for c in cells(e)}
    if mine != paper:
        out.append({"class": "GRID", "detail": f"{len(mine - paper)} cells white only in ours, "
                    f"{len(paper - mine)} only in theirs",
                    "ourAnswers": len({e.get("solution") for e in ours["entries"]}
                                      & {e.get("solution") for e in theirs["entries"]})})
        return out
    a = {where(e): e for e in ours["entries"]}
    b = {where(e): e for e in theirs["entries"]}
    for k in sorted(b.keys() - a.keys()):
        out.append({"class": "MISSING", "light": groups.entry_id(b[k]),
                    "theirs": b[k].get("solution")})
    for k in sorted(a.keys() - b.keys()):
        out.append({"class": "EXTRA", "light": groups.entry_id(a[k]),
                    "ours": a[k].get("solution")})
    for k in sorted(a.keys() & b.keys()):
        o, t = a[k], b[k]
        light = groups.entry_id(t)
        if o["number"] != t["number"] or o["length"] != t["length"]:
            out.append({"class": "NUMBERING", "light": light, "ours": groups.entry_id(o)})
        os_, ts = o.get("solution") or "", t.get("solution") or ""
        if ts and os_ != ts:
            row = {"class": "ANSWER", "light": light, "ours": os_, "theirs": ts}
            if len(os_) == o["length"]:
                row["oursCross"] = crossings_agree(ours, o, os_)
            row["theirsCross"] = crossings_agree(theirs, t, ts)
            out.append(row)
        oc, tc = o.get("clue") or {}, t.get("clue") or {}
        # A pointer, or a source that printed no words, is no witness to ours.
        if CONTINUATION.match(tc.get("text") or "") or not norm_text(tc.get("text")):
            continue
        if norm_enum(oc.get("enumeration")) != norm_enum(tc.get("enumeration")):
            out.append({"class": "ENUMERATION", "light": light,
                        "ours": oc.get("enumeration"), "theirs": tc.get("enumeration")})
        if norm_text(oc.get("text")) != norm_text(tc.get("text")):
            out.append({"class": "CLUE", "light": light,
                        "ours": oc.get("text"), "theirs": tc.get("text")})
    return out


def witness(theirs):
    """The source's copy with the answers fetch_puzzle.SOURCE_ANSWER_WRONG
    proves the paper got wrong put right, as every write to the corpus puts
    them right: a known error in the source's key is not a finding."""
    import corroborate
    return corroborate.known_wrong(theirs)


def run(adapter, only=None):
    keys = adapter.ids()
    disk = held(adapter)
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = REPORTS / f"{adapter.name}.jsonl"
    tally, puzzles, skipped = Counter(), Counter(), Counter()
    rows = []
    for pid in sorted(only or disk):
        if pid not in disk:
            skipped["not held"] += 1
            continue
        ours = read_puzzle_file(disk[pid])
        if pid not in keys:
            skipped["source lacks"] += 1
            continue
        if not adapter.covers(ours):
            skipped["taken from this source"] += 1
            continue
        try:
            theirs = adapter.puzzle(keys[pid])
        except Exception as err:  # noqa: BLE001 — a source page we cannot read is reported
            skipped["source unreadable"] += 1
            rows.append({"id": pid, "unreadable": str(err)})
            continue
        if theirs is None:
            skipped["not cached"] += 1
            continue
        if theirs["id"] != pid:
            skipped["source is another puzzle"] += 1
            rows.append({"id": pid, "unreadable": f"source holds {theirs['id']}"})
            continue
        found = diff(ours, witness(theirs))
        tally["compared"] += 1
        if found:
            rows.append({"id": pid, "path": str(disk[pid].relative_to(disk[pid].parents[3])),
                         "gridOrigin": (ours.get("source") or {}).get("gridOrigin"),
                         "mismatches": found})
            for cls in {m["class"] for m in found}:
                puzzles[cls] += 1
            tally.update(m["class"] for m in found)
    if not only:
        report.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                          encoding="utf-8")
        print(f"report: {report}")
    print(f"compared {tally.pop('compared', 0)}; skipped {dict(skipped)}")
    for cls in CLASSES:
        print(f"  {cls:12} {tally[cls]:6} in {puzzles[cls]:5} puzzles")
    return rows


#: The classes a refile from the Guardian's page settles. A grid, numbering or
#: light the page disagrees about is the page's own defect as often as ours
#: (everyman-3792's page numbers its 18-across 16), so those are reported only.
REFILED = {"CLUE", "ENUMERATION", "ANSWER"}


def refile_guardian(adapter, pid, path, url, found):
    """Refile one puzzle from the Guardian's page through fetch_puzzle.convert().
    Returns notes, or None when the puzzle is left alone.

    The page wins as fetch_telegraph.refile() lets the Telegraph bucket win: its
    clue unless it misspells or garbles ours, its count unless it fails to count
    its own answer, and an annotation only while its answer and words still fit.
    An answer is the page's only where the crossing letters back it and not
    ours, because the Guardian's key can be wrong (cryptic-23053)."""
    import fetch_puzzle as fp
    import fetch_telegraph as ft
    classes = {m["class"] for m in found}
    old = read_puzzle_file(path)
    data = json.loads(adapter.raw_file(url).read_text(encoding="utf-8"))
    from_page = (old.get("source") or {}).get("acquiredBy") == "tools/fetch_puzzle.py"
    # Files fetched before puzzles kept a preamble lack the page's note.
    lacks_note = not old.get("preamble") and fp.preamble(data.get("instructions"))
    if classes - REFILED or (from_page and not classes and not lacks_note):
        return None
    if (old.get("solutions") or {}).get("origin") != "published":
        return None
    data["number"] = int(pid.rsplit("-", 1)[1])
    new = fp.convert(data)
    if new["id"] != pid or not all(e.get("solution") for e in new["entries"]):
        return None
    fp.carry_recovered_clues(new, old)
    notes = keep_backed_answers(old, new)
    notes_by = {groups.entry_id(e): e["clue"].get("missingNote") for e in old["entries"]}
    for e in new["entries"]:
        if notes_by.get(groups.entry_id(e)):
            e["clue"]["missingNote"] = notes_by[groups.entry_id(e)]
    if old.get("preamble"):
        new["preamble"] = old["preamble"]
    elif lacks_note:
        notes.append(f"the page's note: {new['preamble'][:60]!r}")
    new, more = ft.refile(new, old)
    fp.write_puzzle_file(path, new, generator="tools/fetch_puzzle.py")
    return notes + more


def keep_backed_answers(old, new):
    """Put our answer back over `new`'s wherever the crossing letters do not
    back the source's against ours, since a paper's key can be wrong
    (cryptic-23053). Returns notes."""
    notes = []
    held_at = {where(e): e for e in old["entries"]}
    for row in diff(old, new):
        if row["class"] != "ANSWER":
            continue
        checked, agree = row["theirsCross"]
        ours_checked, ours_agree = row.get("oursCross") or (0, 0)
        if checked and agree == checked and ours_agree < ours_checked:
            notes.append(f"{row['light']}: the source's {row['theirs']} over our "
                         f"{row['ours']}, the crossings agree")
            continue
        for e in new["entries"]:
            if groups.entry_id(e) == row["light"]:
                e["solution"] = held_at[where(e)]["solution"]
        notes.append(f"{row['light']}: kept our {row['ours']} over the source's "
                     f"{row['theirs']}, the crossings do not back it")
    return notes


def refile_independent(adapter, pid, path, ymd, found):
    """Refile one puzzle rebuilt from fifteensquared from the Independent's
    feed, through fetch_independent.parse(), whatever differs: the feed is
    the printed puzzle, so it becomes the primary source. Returns notes, or
    None when left alone.

    A file already from the feed is never refiled. Its differences from the
    feed are edits made after the fetch, and the ones found so far are the
    feed's own errors put right (CLUE_FIXES, SOURCE_ANSWER_WRONG); a refile
    would write the error back. They are reported, for the tables.

    The converter's output must match the feed as read here; where it does
    not, refiling would write the converter's defect again, so the puzzle is
    named and left alone."""
    import fetch_independent as fi
    import fetch_puzzle as fp
    import fetch_telegraph as ft
    classes = {m["class"] for m in found}
    old = read_puzzle_file(path)
    if (old.get("source") or {}).get("acquiredBy") == "tools/fetch_independent.py":
        return None
    xml = adapter.raw_file(ymd).read_bytes()
    new = fi.parse(xml, ymd)
    if new["id"] != pid:
        return None
    defect = diff(new, independent_shape(xml, ymd))
    if defect:
        raise ValueError("fetch_independent.parse() differs from the feed: "
                         + "; ".join(f"{m['class']} {m.get('light', m.get('detail'))}"
                                     for m in defect[:3]))
    notes = [] if "GRID" in classes else keep_backed_answers(old, new)
    notes.append(f"the feed's printed puzzle over the file {old['source'].get('acquiredBy')} "
                 f"built ({', '.join(sorted(classes)) or 'no differences'})")
    fp.merge_annotations(new, old)
    if old.get("preamble") and not new.get("preamble"):
        new["preamble"] = old["preamble"]
    new, more = ft.refile(new, old)
    fp.write_puzzle_file(path, new, generator="tools/fetch_independent.py")
    return notes + more


def refile(adapter, limit=None):
    """Refile every puzzle the last report names whose differences refile
    settles, and every clean copy taken from elsewhere, up to `limit`."""
    one = {"guardian": refile_guardian, "independent": refile_independent}.get(adapter.name)
    if one is None:
        raise SystemExit("--refile: the guardian and independent adapters refile here; the "
                         "Telegraph's is tools/fetch_telegraph.py --holes")
    keys = adapter.ids()
    disk = held(adapter)
    report = REPORTS / f"{adapter.name}.jsonl"
    found = {r["id"]: r.get("mismatches") for r in map(json.loads, report.open(encoding="utf-8"))}
    done = Counter()
    for pid in sorted(keys):
        if limit is not None and done["refiled"] >= limit:
            break
        if not adapter.raw_file(keys[pid]).exists() or found.get(pid, []) is None:
            continue
        try:
            notes = one(adapter, pid, disk[pid], keys[pid], found.get(pid, []))
        except Exception as err:  # noqa: BLE001 — one refused write, named, not the run
            print(f"{pid}: not refiled: {err}")
            done["refused"] += 1
            continue
        if notes is None:
            continue
        done["refiled"] += 1
        print(f"refiled {pid}" + "".join(f"\n  {n}" for n in notes))
    print(f"refile: {dict(done)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", choices=sorted(ADAPTERS))
    ap.add_argument("--fetch", action="store_true", help="top up the cache first")
    ap.add_argument("--limit", type=int, help="fetch or refile at most this many")
    ap.add_argument("--refile", action="store_true",
                    help="refile from the source what the last report found (guardian, independent)")
    ap.add_argument("--show", nargs="+", metavar="ID", help="diff these puzzles and print")
    args = ap.parse_args(argv)
    adapter = ADAPTERS[args.source]()
    if args.fetch:
        keys = adapter.ids()
        disk = held(adapter)
        todo = [keys[p] for p in sorted(disk) if p in keys
                and adapter.covers(read_puzzle_file(disk[p]))]
        print(f"{len(todo)} puzzles held that {adapter.name} also serves", flush=True)
        if args.limit is not None and hasattr(adapter, "raw_file"):
            todo = [k for k in todo if not adapter.raw_file(k).exists()
                    and not adapter.raw_file(k).with_suffix(".404").exists()][:args.limit]
        fetch(adapter, todo)
    if args.show:
        for row in run(adapter, only=args.show):
            print(json.dumps(row, ensure_ascii=False, indent=1))
        return 0
    if not args.fetch or args.refile:
        run(adapter)
    if args.refile:
        refile(adapter, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
