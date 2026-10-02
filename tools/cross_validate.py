#!/usr/bin/env python3
"""Check our puzzles against another copy of the same puzzle, class by class.

    python3 tools/cross_validate.py telegraph --fetch      # top up the source cache
    python3 tools/cross_validate.py telegraph              # diff from the cache, write the report
    python3 tools/cross_validate.py telegraph --show telegraph-28936
    python3 tools/cross_validate.py guardian --fetch --refile --limit 1500
                                                           # cache 1500 more pages, diff, refile
    python3 tools/cross_validate.py independent --fetch --refile --limit 1500
                                                           # the same against the Independent's feed
    python3 tools/cross_validate.py fifteensquared         # answers against fifteensquared's
    python3 tools/cross_validate.py globe --fetch --limit 60
    python3 tools/cross_validate.py globe                  # the Times Quick against the Globe's print
    python3 tools/cross_validate.py ft                     # the FT cryptic against the FT's PDFs
    python3 tools/cross_validate.py georgeho               # 17 series against georgeho's blog clues
    python3 tools/cross_validate.py bigdave44              # the Telegraph's app files against the blog
    python3 tools/cross_validate.py timesforthetimes       # the Globe's files against the Times blog
    python3 tools/cross_validate.py archiveorg             # the Times 1974-99 against its print
    python3 tools/cross_validate.py all --apply --limit 10000
                                                           # every copy at once; a majority fixes ours
    python3 tools/cross_validate.py all --apply --new      # the same over tonight's filings

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

`all` puts every copy of a puzzle to a vote at once (majority()): ours is one
vote and each other origin one more. Three or more votes with a value other
than ours holding more than half of them fix our file. Two copies are enough:
where ours and one other origin are the only votes, source authority breaks
the tie. The paper's own print (the guardian, telegraph, independent, globe
and ft adapters, or ours when retrieved from that feed) beats an OCR'd scan
(archiveorg, canberra, a book), which beats a blog's rebuild (fifteensquared,
bigdave44, timesforthetimes, georgeho). Ours' rank is its file's: clues and
counts by source.retrievedFrom, answers a blog's when solutions came from a
write-up (ours_authority()). The nearer copy wins; equal or unknown rank, or
no majority of three, leaves the file and is a lead in
cross-validate/all-leads.jsonl. Each fix is recorded in
tools/data/corroboration_ledger.json and is still refused where it crosses a
letter it does not share or rewrites a clue an annotation quotes. The votes
settle ANSWER, ENUMERATION and CLUE; the structural classes are tallied and
left to the per-source refiles.

Every copy we hold, by series. "own" is the paper's own feed, app or page; an
adapter in brackets reads it; a cell marked with an adapter is compared by
`all`. The nightly runs `all --new` on tonight's filings; a pass over the rest
(`all --apply --limit N`, resuming at a cursor) is run by hand after a change
to an adapter or to majority().

  series                     primary (where ours came from)     other copies we hold
  cryptic quiptic everyman   own page (fetch_puzzle)            own page [guardian], fifteensquared
                                                                [fifteensquared], georgeho
                                                                [georgeho, fifteensquared's origin]
  independent indysunday     own feed from 2015-06, else        own feed [independent], fifteensquared
                             fifteensquared rebuild             [fifteensquared], georgeho
  cyclops                    own .puz (fetch_privateeye)        fifteensquared [fifteensquared], georgeho
  telegraph sundaytel        own app bucket from 2015, else     app bucket [telegraph], bigdave44
  toughie sundaytough        bigdave44 rebuild                  [bigdave44], georgeho (bigdave44's origin)
  times sundaytimes          timesforthetimes rebuild           georgeho (the same blog, to 2023-07: a
  timesjumbo mephisto                                           split is a lead, never a fix); the
  timesclub tls                                                 Times listing's dates (corroborate.py)
  timesquick                 timesforthetimes rebuild to 3105   Globe [globe] for the blog copy from
                                                                3106, georgeho
  globeandmail               own Amuse payload                  own payload [globe], timesforthetimes
                                                                [timesforthetimes]
  ftcryptic                  FT PDF 2006-12, else               FT PDF [ft], the fifteensquared post
                             fifteensquared rebuild             the rebuild came from
  canberra                   Trove scan                         none yet
  book metro listener        the book, the paper, the PDF       none

georgeho is frozen (2023-07-15), so its pair needed one pass, not a nightly
job; it votes in `all` like any copy.

--refile (the guardian, independent and ft adapters) then rewrites, from the source, each file whose
only differences are CLUE, ENUMERATION or ANSWER, each clean file taken from
somewhere other than the source, and (the Guardian) each file lacking the note
the page prints above the clues; see refile_guardian(), refile_independent() and
refile_ft().
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
#: Source authority, best first: the paper's own print (its feed, app, page or
#: PDF), an OCR'd scan of it (archive.org, Trove, a book), a blog's retyping.
PAPER, SCAN, BLOG = 0, 1, 2
#: A file's source.retrievedFrom, as an authority.
RETRIEVED_AUTHORITY = {"publisher": PAPER, "wayback": PAPER, "newspaper": SCAN,
                       "book": SCAN, "blog": BLOG}


class Adapter:
    """One outside source. Subclasses set `name` and `series` and implement
    ids(), fetch_one() and puzzle()."""
    name = ""
    series = ()
    #: Whether the source prints the clues we hold verbatim, so punctuation
    #: counts (diff's `exact`).
    exact_clues = False
    #: Seconds each worker waits between requests, and how many workers.
    delay = 0.5
    workers = 4
    #: Who wrote the copy, for counting votes (corroborate_all): two reads of
    #: one origin are one vote. Defaults to the adapter's name.
    origin = ""
    #: The classes this copy's own words witness. A copy that is ours with
    #: only the blog's answers swapped in votes on answers alone.
    votes = ("ANSWER", "ENUMERATION", "CLUE")
    #: Read only what is cached: no request, not even a calendar refresh.
    offline = False
    #: How far this copy is from the paper's print (PAPER, SCAN or BLOG):
    #: the tie-break when it and ours are the only two votes.
    authority = None

    def origin_of(self, ours):
        return self.origin or self.name

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
    authority = PAPER
    origin = "telegraph-app"
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
            if not path.exists() or (year >= datetime.date.today().year and not self.offline):
                if self.offline:
                    continue
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
    authority = PAPER
    origin = "guardian-page"
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
    authority = PAPER
    origin = "independent-feed"
    series = ("independent", "indysunday")
    #: A CDN: a request a second from each of three workers is polite.
    delay = 1.0
    workers = 3

    def ids(self):
        """Each held puzzle's print date as a key, unless a cached key is
        known to serve it: in 2015 the feed served the Sunday paper a week
        early and, from 2015-07-13 to 08-16, the daily on the Sunday key,
        while our files carry the day each was printed."""
        import fetch_independent as fi
        out = {}
        for pid, path in held(self).items():
            day = read_puzzle_file(path).get("date") or ""
            ymd = day[2:4] + day[5:7] + day[8:10]
            if len(ymd) == 6 and ymd not in fi.REPEATS:
                out[pid] = ymd
        served = self.served()
        out.update({pid: ymd for pid, ymd in served.items() if pid in out})
        return out

    def served(self):
        """{puzzle id: date key} over the 2015 keys cached, read off each
        key's own title (fetch_independent.parse); keys that fail to parse
        hold no puzzle we can name."""
        import fetch_independent as fi
        out = {}
        for path in sorted(self.cache.glob("c_15*.xml")):
            ymd = path.stem[2:]
            try:
                pid = fi.parse(path.read_bytes(), ymd)["id"]
            except Exception:  # noqa: BLE001 — a repeat or staging key names nothing
                continue
            out.setdefault(pid, ymd)
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
    (a period, slash or space in it read as the comma it stands for, a
    trailing comma dropped). A clue or count fetch_independent's CLUE_FIXES
    or FORMAT_FIXES proves wrong is read as printed, as witness() does for a
    known wrong answer."""
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
        enum = re.sub(r",+", ",", re.sub(r"[./\s]", ",", (clue.get("format") or "").strip()))
        enum = fi.FORMAT_FIXES.get((ymd, clue.get("word"), enum), enum).strip(",") or None
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


class FifteenSquared(Adapter):
    """fifteensquared's answers for every series it blogs: the post
    cache tools/fetch_fifteensquared.py fills, then georgeho's scrape of the
    same blog, read through tools/corroborate.py. Offline; --fetch is a no-op.

    A blog prints no grid and retypes the clues, so the source puzzle is ours
    with only each answer the blog prints in full for the light swapped in: it
    witnesses ANSWER alone. Where the feed's key is wrong in one cell, both
    crossing lights differ from ours there and agree with each other."""
    name = "fifteensquared"
    authority = BLOG
    series = ("independent", "indysunday", "cryptic", "quiptic", "everyman", "cyclops")
    votes = ("ANSWER",)

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


class Globe(Adapter):
    """The Globe and Mail's copy of the Times Quick Cryptic: Globe No N is
    Quick No N, printed about seven weeks later from the same grid and clues.
    tools/fetch_globeandmail.py fetches it; this caches each day's decoded
    Amuse payload and reads it without that tool's convert().

    The Globe's archive starts at No 3106, where the Times filer stops filing
    the blog's copy (file_blog_puzzles.reprinted_by), so the blog copies it
    witnesses are mostly never filed. Each is built here as the filer would
    build it, from the same grids.jsonl and parsed.jsonl, and compared under
    its Quick id: a difference is a defect of the converter that built every
    Quick before 3106. A Quick file we do hold is compared as filed, and so
    is each globeandmail file, which checks fetch_globeandmail's converter."""
    name = "globe"
    authority = PAPER
    origin = "globe"
    series = ("timesquick", "globeandmail")
    exact_clues = True
    #: Somebody else's CDN: fetch_globeandmail.REQUEST_GAP, one at a time.
    delay = 1.0
    workers = 1

    def __init__(self):
        self._blog = None

    def ids(self):
        """{puzzle id: (series, date key)}: each globeandmail file's print
        day, for its own id and the Quick id of its number."""
        out = {}
        for pid, path in held_paths(self.series).items():
            series, _, num = pid.rpartition("-")
            if series != "globeandmail":
                continue
            ymd = (read_puzzle_file(path).get("date") or "").replace("-", "")
            if len(ymd) == 8:
                out[pid] = ("globeandmail", ymd)
                out[f"timesquick-{num}"] = ("timesquick", ymd)
        for ymd, num in GLOBE_RENUMBERED.items():
            out[f"timesquick-{num}"] = ("timesquick", ymd)
        return out

    def held(self):
        """The held files, and a blog copy for each Quick the Globe prints
        and we do not hold, as ("blog", number)."""
        disk = dict(held_paths(self.series))
        for pid, (series, _) in self.ids().items():
            if series == "timesquick" and pid not in disk:
                disk[pid] = ("blog", int(pid.rsplit("-", 1)[1]))
        return disk

    def load(self, where):
        if isinstance(where, tuple):
            return self.blog_copy(where[1])
        return read_puzzle_file(where)

    def blog_copy(self, number):
        """Quick No `number` as tools/file_times_puzzles.py would file it from
        the blog, or a {"unfilable": why} stand-in."""
        import file_blog_puzzles as fbp
        import file_times_puzzles as ftp
        import times_grids as tg
        if self._blog is None:
            recs = {}
            for line in tg.PARSED.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                recs[rec["post_id"]] = rec
            rows = defaultdict(list)
            for line in tg.OUT.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row.get("number") and ftp.target(row)[0] == "timesquick":
                    rows[row["number"]].append(row)
            self._blog = (recs, rows, fbp.typed_counts(recs.values()))
        recs, rows, typed = self._blog
        claim = rows.get(number, [])
        if len(claim) != 1:
            return {"unfilable": f"{len(claim)} blog rows"}
        rec = recs[claim[0]["post_id"]]
        puzzle, why = fbp.build(rec, claim[0], "timesquick", None,
                                ftp.setter(rec, "timesquick"), typed)
        return puzzle or {"unfilable": why}

    def raw_file(self, key):
        return self.cache / f"{key[1]}.json"

    def fetch_one(self, key):
        import fetch_globeandmail as fg
        path = self.raw_file(key)
        if path.exists() or path.with_suffix(".404").exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = fg.fetch_raw_json(f"{fg.SET}_{key[1]}")
        except fg.PuzzleNotFound as err:
            path.with_suffix(".404").write_text(str(err))
            return True
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return True

    def puzzle(self, key):
        path = self.raw_file(key)
        if not path.exists():
            return None
        return globe_shape(json.loads(path.read_text(encoding="utf-8")), key)

    def covers(self, ours):
        return "unfilable" not in ours


#: Days the Globe printed under another Quick's number, {date key: the Quick
#: it is}: 2026-05-18 is titled "No 3262" like the day before, but its grid
#: and clues are Quick 3263's.
GLOBE_RENUMBERED = {"20260518": 3263}


def globe_shape(data, key):
    """A decoded Amuse payload in our shape, read without
    fetch_globeandmail.convert(): box is column-major (box[x][y]), each
    placedWord one light, its wordLens the count, its clue's tags stripped."""
    series, ymd = key
    m = re.search(r"No\.?\s*([\d,]+)\s*$", (data.get("title") or "").strip())
    num = GLOBE_RENUMBERED.get(ymd) or (int(m.group(1).replace(",", "")) if m else None)
    entries = []
    for pw in data["placedWords"]:
        across = bool(pw["acrossNotDown"])
        e = {"number": int(pw["clueNum"]), "direction": "across" if across else "down",
             "position": {"x": pw["x"], "y": pw["y"]}, "length": pw["nBoxes"]}
        text = html.unescape(re.sub(r"<[^>]*>", "", pw["clue"]["clue"]))
        text = " ".join(GUARDIAN_TAIL.sub("", text).split())
        e["clue"] = {"text": text, "enumeration": ",".join(map(str, pw["wordLens"]))}
        e["solution"] = "".join(data["box"][x][y] for x, y in cells(e)).upper() or None
        entries.append(e)
    return {"id": f"{series}-{num}", "dimensions": {"cols": data["w"], "rows": data["h"]},
            "entries": entries}


class FT(Adapter):
    """The FT's own printable PDF of each cryptic, 2006 to 2012, fetched by
    tools/ft_pdf_puzzles.py into ~/cryptic-setter-data/ft-pdf/pdf/<number>.pdf.

    The PDF's clue list and vector grid are read with ft_pdf_puzzles.read_pdf
    and shaped here without file_blog_puzzles.build(), so a file filed from
    the PDF checks that converter, and a file ft_puzzles.py rebuilt from
    fifteensquared checks the blog's parser and the grid reconstructor. The
    PDF prints no answers. A PDF whose grid cannot be read is compared on
    our grid's geometry, by light, for its clues and counts only."""
    name = "ft"
    authority = PAPER
    origin = "ft-pdf"
    series = ("ftcryptic",)
    exact_clues = True
    #: Read once by refile_ft: fifteensquared's posts and the PDF index.
    posts = index = None

    @property
    def cache(self):
        import ft_pdf_puzzles as fpp
        return fpp.PDFS

    def ids(self):
        return {f"ftcryptic-{p.stem}": int(p.stem) for p in self.cache.glob("*.pdf")}

    def raw_file(self, number):
        return self.cache / f"{number}.pdf"

    def fetch_one(self, number):
        raise SystemExit("ft: tools/ft_pdf_puzzles.py fetch fills the PDF cache")

    def puzzle(self, number):
        import ft_pdf_puzzles as fpp
        path = self.raw_file(number)
        if not path.exists():
            return None
        if self._held is None:
            self._held = held_paths(self.series)
        held_at = self._held.get(f"ftcryptic-{number}")
        return ft_shape(fpp.read_pdf(path), held_at and read_puzzle_file(held_at))

    _held = None


def ft_shape(pdf, ours=None):
    """ft_pdf_puzzles.read_pdf's reading in our shape. The light's cells come
    from the PDF's grid when its numbering is the clue list's; otherwise from
    `ours` by number and direction (the grid is then not witnessed, and a
    light we lack is reported MISSING at no cell)."""
    import ft_pdf_puzzles as fpp
    import reconstruct_grid as rg
    grid = pdf.get("grid")
    if grid is not None and fpp.grid_matches(grid, pdf["clues"]) is None:
        lights = rg.light_cells(grid)
        dims = {"cols": len(grid[0]), "rows": len(grid)}
    else:
        lights = {}
        for e in (ours or {}).get("entries", []):
            lights[(e["number"], e["direction"])] = [(y, x) for x, y in cells(e)]
        dims = (ours or {}).get("dimensions")
    entries = []
    for c in pdf["clues"]:
        text = " ".join(fpp.ENUM.sub("", c["clue"]).split())
        for i, light in enumerate(c["lights"]):
            at = lights.get(light)
            e = {"number": light[0], "direction": light[1],
                 "position": {"x": at[0][1], "y": at[0][0]} if at else {"x": -1, "y": -light[0]},
                 "length": len(at) if at else 0,
                 "clue": ({"text": text, "enumeration": c["enumeration"]} if i == 0
                          else {"text": f"See {c['lights'][0][0]}"}),
                 "solution": None}
            entries.append(e)
    return {"id": f"ftcryptic-{pdf['number']}", "dimensions": dims, "entries": entries}


class GeorgeHo(Adapter):
    """georgeho.org's ODbL database of blog clues (fifteensquared,
    times-xwd-times, bigdave44), read through tools/corroborate.py's index of
    our own rows. Offline and frozen (built 2023-07-15); --fetch is a no-op.

    The blog prints no grid, so the source puzzle is ours with each light the
    blog writes up given the blog's answer (where it fills the light), clue
    and count; a light the blog does not write up keeps no clue or answer and
    witnesses nothing. A light the blog numbers that we lack is MISSING. The
    blogger retyped the clue, so CLUE compares words, never punctuation, and
    a blog outranks no file (majority()), so alone it fixes nothing. A blog that
    prints no count witnesses none, and a row the scrape filed under another
    light (misfiled()) witnesses nothing."""
    name = "georgeho"
    authority = BLOG
    series = ("cryptic", "quiptic", "everyman", "independent", "indysunday", "cyclops",
              "times", "timesquick", "timesjumbo", "sundaytimes", "mephisto", "timesclub",
              "tls", "telegraph", "sundaytel", "toughie", "sundaytough")

    def ids(self):
        import corroborate
        db = corroborate._georgeho_index()
        if db is None:
            raise SystemExit(f"no {corroborate.GEORGEHO}: corroborate.py --download")
        return {pid: pid for (pid,) in db.execute("select distinct pid from clue")}

    def fetch_one(self, pid):
        return False

    def puzzle(self, pid, ours=None):
        import copy

        ours = ours or read_puzzle_file(held_paths((pid.rsplit("-", 1)[0],))[pid])
        recs = self.records(ours)
        if not recs:
            return None
        lights = {(e["number"], e["direction"]): e for e in ours["entries"]}

        held_answers = {e.get("solution") for e in ours["entries"]}

        def agree(rec):
            # By answer, not light: the scrape files some posts' downs as acrosses.
            return [got in held_answers for got in rec.answers.values()]
        # Two posts under one title (a blogger's typo for the next number):
        # the copy of ours is the one that agrees with it.
        rec = max(recs, key=lambda r: sum(agree(r)))
        same = agree(rec)
        if len(same) >= 4 and sum(same) * 2 < len(same):
            return dict(ours, id=f"another puzzle: {sum(same)} of {len(same)} answers "
                                 f"held, {rec.url}")
        rows = blog_rows(rec)
        theirs = copy.deepcopy(ours)
        answers = {e.get("solution") for e in ours["entries"]}
        clues = {norm_text((e.get("clue") or {}).get("text")) for e in ours["entries"]}
        for e in theirs["entries"]:
            key = (e["number"], e["direction"])
            got = rows.pop(key, None)
            if got is None or misfiled(got, e, answers, clues):
                e["clue"], e["solution"] = {}, None
                continue
            text, enum, answer = got
            # A blog that prints no count witnesses none: ours stands in, so
            # diff() reports nothing, and corroborate_all counts no vote.
            e["clue"] = ({"text": text, "enumeration": enum} if enum else
                         {"text": text, "enumeration": e["clue"].get("enumeration"), ECHO: True})
            e["solution"] = answer if answer and len(answer) == e["length"] else None
        theirs["unplaced"] = [{"class": "MISSING", "light": groups.entry_id(
                                   {"number": n, "direction": d}), "theirs": got[2]}
                              for (n, d), got in sorted(rows.items())
                              if (n, d) not in lights and not unplaceable(n, got[2], ours)]
        return theirs

    def load(self, where):
        return read_puzzle_file(where)

    def records(self, ours):
        import corroborate
        return corroborate.georgeho(ours)

    def origin_of(self, ours):
        """The blog georgeho scraped for this series."""
        import corroborate
        series = ours["id"].rsplit("-", 1)[0]
        for table, origin in corroborate.GEORGEHO_SOURCES.values():
            if series in {s for _, s in table}:
                return origin
        return self.name


#: The clue key GeorgeHo marks a count copied from ours with.
ECHO = "countIsOurs"


class ParsedBlog(GeorgeHo):
    """A blog's parsed posts (the parser's parsed.jsonl, the file the filer
    reads), laid over our own puzzle as GeorgeHo lays georgeho's rows: each
    light the post writes up given its answer, clue and count. A file the
    blog's own filer built is the source itself and is not compared."""
    parsed = None
    filer = ""

    def __init__(self):
        self._recs = None

    def pids(self, rec):
        """Our ids for one parsed post."""
        raise NotImplementedError

    def ids(self):
        if self._recs is None:
            self._recs = defaultdict(list)
            for line in self.parsed.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                for pid in self.pids(rec):
                    self._recs[pid].append(rec)
        return {pid: pid for pid in self._recs}

    def records(self, ours):
        import corroborate
        if self._recs is None:
            self.ids()
        out = []
        for rec in self._recs.get(ours["id"], ()):
            r = corroborate.Record(self.name, self.name, rec.get("link", ""))
            for e in rec.get("entries", ()):
                key = (e["number"], e["direction"])
                got = corroborate.answer_letters(e.get("answer"))
                if got:
                    r.answers.setdefault(key, got)
                clue = (e.get("clue") or "").strip()
                if clue and e.get("enumeration") and not ENUM_TAIL.search(clue):
                    clue += f" ({e['enumeration']})"
                if clue:
                    r.clues.setdefault(key, clue)
            out.append(r)
        return out

    def covers(self, ours):
        return (ours.get("source") or {}).get("acquiredBy") != self.filer

    def origin_of(self, ours):
        return self.name


class BigDave44(ParsedBlog):
    """bigdave44.com's write-ups of the Telegraph's four series: a witness to
    every file the Telegraph app's bucket filed."""
    name = "bigdave44"
    series = ("telegraph", "sundaytel", "toughie", "sundaytough")
    filer = "tools/file_telegraph_puzzles.py"

    @property
    def parsed(self):
        return DATA / "bigdave44" / "parsed.jsonl"

    def pids(self, rec):
        return [f"{rec['series']}-{rec['number']}"] if rec.get("series") in self.series else []


class TimesBlog(ParsedBlog):
    """timesforthetimes's write-ups of the Times's series: a witness to each
    Globe and Mail file (Globe No N is Quick No N) and to any Times file not
    built from this blog."""
    name = "timesforthetimes"
    series = ("globeandmail", "times", "timesquick", "sundaytimes", "timesjumbo", "mephisto",
              "timesclub", "tls")
    filer = "tools/file_times_puzzles.py"

    @property
    def parsed(self):
        return DATA / "timesforthetimes" / "parsed.jsonl"

    def pids(self, rec):
        import file_times_puzzles as ftp
        try:
            series, _ = ftp.target({**rec, "post_id": rec.get("post_id")})
        except (ValueError, KeyError, TypeError):
            return []
        if not rec.get("number"):
            return []
        out = [f"{series}-{rec['number']}"]
        if series == "timesquick":
            out.append(f"globeandmail-{rec['number']}")
        return out


def misfiled(got, ours, answers, clues):
    """Whether the blog's row for `ours`'s light is some other light's row:
    its answer or its clue is one we hold against another light. The scrape
    shifts rows past a linked clue; that is the scrape's defect, no witness."""
    text, _, answer = got
    if answer and answer != ours.get("solution") and answer in answers:
        return True
    words = norm_text(text)
    return bool(words) and words != norm_text((ours.get("clue") or {}).get("text")) \
        and words in clues


def unplaceable(number, answer, ours):
    """Whether a light the blog names and we lack is the scrape's, not ours to
    miss: a number past our last (a linked clue's "18,13" read as 1813), or an
    answer that is ours already, alone or as lights joined (a linked clue
    filed under its other number)."""
    entries = ours["entries"]
    if number > max(e["number"] for e in entries):
        return True
    if not answer:
        return True
    held = [e.get("solution") or "" for e in entries]
    if answer in held:
        return True
    pieces = [h for h in held if h and h in answer]
    return bool(pieces) and _joined(answer, pieces)


def _joined(answer, pieces):
    """Whether `answer` is some of `pieces` end to end."""
    if not answer:
        return True
    return any(answer.startswith(p) and _joined(answer[len(p):], pieces) for p in pieces)


#: What the scrape leaves before a clue: the rest of a linked clue's number
#: (", 26.", "/18 ") or the light's direction letter ("a Ship retiring").
BLOG_PREFIX = re.compile(r"^(?:\s*[,/&]\s*\d+\s*[ad]?\b\.?)+\s*|^(?:[ad]|ac|dn)\.?\s+(?=[A-Z0-9'‘\"“])")
#: A clue the scrape split at its leading number ("25, left defender?" kept as
#: ", left defender?"): its words are short of ours, no witness.
BLOG_HEADLESS = re.compile(r"^\s*[,;:.]")
#: A clue's count at its tail; a worded one ("(8, two words)", Mephisto's)
#: is the total, no witness to where the words break.
ENUM_TAIL = re.compile(r"\s*\(([\d\s,.\-–'’]+?)(,?\s*(?:\w+\s+)?words?)?\)\s*$")


def blog_rows(rec):
    """{(number, direction): (clue words, enumeration or None, answer)} of one
    corroborate.Record, the enumeration taken off the clue's tail."""
    out = {}
    for key, clue in rec.clues.items():
        m = ENUM_TAIL.search(clue)
        text, enum = (clue[:m.start()], m.group(1)) if m else (clue, None)
        text = "" if BLOG_HEADLESS.match(BLOG_PREFIX.sub("", text)) else BLOG_PREFIX.sub("", text)
        if m and m.group(2):
            enum = None
        out[key] = (text.strip(), enum and re.sub(r"[\s.’']", "", enum).replace("–", "-"),
                    rec.answers.get(key))
    for key, answer in rec.answers.items():
        out.setdefault(key, ("", None, answer))
    return out


class ArchiveOrg(Adapter):
    """The Times, FT and Guardian as printed, 1971-99:
    tools/file_archive_org_puzzles.py's reading of each daily cryptic in
    archive.org's scans, kept in ~/cryptic-setter-data/archiveorg-source/
    (times-<No>.json, ftcryptic-<No>.json, cryptic-<No>.json) whether or not
    it was filed. It votes on the file of that id another source gave us, and on
    each canberra file whose source names it as the Times puzzle it reprints
    (reprintOf). A file the archive.org filer wrote is that reading, and is
    not compared with itself. Offline: the filer fills the cache."""
    name = "archiveorg"
    authority = SCAN
    series = ("times", "canberra", "ftcryptic", "cryptic")
    offline = True
    filer = "tools/file_archive_org_puzzles.py"

    @property
    def cache(self):
        return DATA / "archiveorg-source"

    def ids(self):
        out = {p.stem: (p.stem, p) for s in ("times", "ftcryptic", "cryptic")
               for p in sorted(self.cache.glob(f"{s}-*.json"))}
        for pid, times_id in reprints().items():
            if times_id in out:
                out[pid] = (pid, out[times_id][1])
        return out

    def fetch_one(self, key):
        return False

    def puzzle(self, key):
        pid, path = key
        return dict(json.loads(path.read_text(encoding="utf-8")), id=pid)

    def covers(self, ours):
        return (ours.get("source") or {}).get("acquiredBy") != self.filer


class CanberraReprint(Adapter):
    """The Canberra Times's reprint of a London Times cryptic (Trove's scans,
    tools/file_trove_puzzles.py) as a copy of the times-<No> it reprints:
    the canberra file's source names it (reprintOf, matched by clue set in
    tools/file_archive_org_puzzles.py --match-canberra)."""
    name = "canberra"
    authority = SCAN
    series = ("times",)
    offline = True

    def ids(self):
        paths = held_paths(("canberra",))
        return {times_id: (times_id, paths[pid]) for pid, times_id in reprints().items()
                if pid in paths}

    def fetch_one(self, key):
        return False

    def puzzle(self, key):
        times_id, path = key
        return dict(read_puzzle_file(path), id=times_id)


def reprints():
    """{canberra id: the times id it reprints}, from the canberra files."""
    out = {}
    for pid, path in held_paths(("canberra",)).items():
        times_id = (json.loads(path.read_text(encoding="utf-8")).get("source") or {}).get("reprintOf")
        if times_id:
            out[pid] = times_id
    return out


ADAPTERS = {a.name: a for a in (Telegraph, Guardian, Independent, FifteenSquared, Globe, FT,
                                 GeorgeHo, BigDave44, TimesBlog, ArchiveOrg, CanberraReprint)}


def held(adapter):
    """{puzzle id: where} for every puzzle the adapter compares: by default
    each file on disk in its series, read by adapter.load()."""
    if hasattr(adapter, "held"):
        return adapter.held()
    return held_paths(adapter.series)


def held_paths(series):
    """{puzzle id: path} for every puzzle on disk in `series`."""
    out = {}
    for path in puzzle_files():
        if path.parent.parent.name in series:
            out[path.stem] = path
    return out


def load(adapter, where):
    return adapter.load(where) if hasattr(adapter, "load") else read_puzzle_file(where)


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


def norm_words(text):
    """Clue words as printed, only quotes, dashes and spacing made one: for a
    source that is the paper's own print of the same clue, where a slash, a
    bracket or a space before a comma is a defect of ours."""
    s = unicodedata.normalize("NFKC", html.unescape(text or "")).translate(QUOTES)
    return " ".join(s.split())


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


def diff(ours, theirs, exact=False):
    """[{class, ...}] for every way `ours` differs from `theirs`; `exact`
    compares clue words as printed (norm_words), not just the words."""
    same_words = norm_words if exact else norm_text
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
        if same_words(oc.get("text")) != same_words(tc.get("text")):
            out.append({"class": "CLUE", "light": light,
                        "ours": oc.get("text"), "theirs": tc.get("text")})
    out.extend(theirs.get("unplaced", ()))
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
        ours = load(adapter, disk[pid])
        if pid not in keys:
            skipped["source lacks"] += 1
            continue
        if not adapter.covers(ours):
            skipped[ours.get("unfilable") or "taken from this source"] += 1
            continue
        try:
            theirs = (adapter.puzzle(keys[pid], ours) if isinstance(adapter, GeorgeHo)
                      else adapter.puzzle(keys[pid]))
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
        found = diff(ours, witness(theirs), exact=adapter.exact_clues)
        tally["compared"] += 1
        if found:
            path = disk[pid]
            rows.append({"id": pid, "path": (str(path.relative_to(path.parents[3]))
                                             if isinstance(path, Path) else "blog copy"),
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
    # Files fetched before puzzles kept a preamble lack the page's note. A
    # note that is only errata converts to none (tools/errata.py): nothing lacks.
    number = int(pid.rsplit("-", 1)[1])
    lacks_note = (not old.get("preamble") and fp.preamble(data.get("instructions"))
                  and "preamble" in fp.convert({**data, "number": number}))
    if classes - REFILED or (from_page and not classes and not lacks_note):
        return None
    if (old.get("solutions") or {}).get("origin") != "published":
        return None
    data["number"] = number
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


def refile_ft(adapter, pid, path, number, found):
    """Refile one FT puzzle from its PDF through ft_pdf_puzzles.assemble(),
    the filer's own path: a file ft_puzzles.py rebuilt from fifteensquared
    whatever differs, since the PDF is the printed grid and clues and becomes
    the primary source; a file already from the PDF only where the PDF now
    reads otherwise (a reader fix). Returns notes, or None when left alone.

    The answers stay fifteensquared's, read off the post by the PDF's clues;
    where the post yields none for a light, a held answer is kept only when
    the PDF's grid is ours, so no answer is written into a cell it was not
    solved for."""
    import fetch_puzzle as fp
    import fetch_telegraph as ft
    import ft_pdf_puzzles as fpp
    old = read_puzzle_file(path)
    from_pdf = (old.get("source") or {}).get("acquiredBy", "").startswith(fpp.GENERATOR)
    if from_pdf and not found:
        return None
    if adapter.posts is None:
        adapter.posts = fpp.blog_posts()
        adapter.index = json.loads(fpp.INDEX.read_text())["puzzles"]
    entry = adapter.index.get(str(number), {})
    how_file = fpp.PDFS / f"{number}.how"
    how = how_file.read_text().strip() if how_file.exists() else "live"
    import datetime
    date = (datetime.date.fromisoformat(entry["date"]) if entry.get("date")
            else fpp.neighbour_date(number, adapter.index)
            or (datetime.date.fromisoformat(old["date"]) if old.get("date") else None))
    pdf = fpp.read_pdf(adapter.raw_file(number))
    post = adapter.posts.get(number)
    new, why = fpp.assemble(number, pdf, post, date, entry.get("url"), how)
    notes = []
    if why and post is not None:
        # The post's answers read against the PDF's clues can fail where the
        # held file's, read by ft_puzzles, do not: file the PDF unsolved and
        # keep the held answers below when its grid is ours.
        new, unsolved_why = fpp.assemble(number, pdf, None, date, entry.get("url"), how)
        if unsolved_why is None:
            notes.append(f"the post's answers refused ({why})")
            why = None
    if why:
        raise ValueError(f"ft_pdf_puzzles.assemble: {why}")
    solved = all(e.get("solution") for e in new["entries"])
    if not solved and all(e.get("solution") for e in old["entries"]):
        mine = {c for e in old["entries"] for c in cells(e)}
        if mine == {c for e in new["entries"] for c in cells(e)}:
            at = {where(e): e["solution"] for e in old["entries"]}
            for e in new["entries"]:
                e["solution"] = at[where(e)]
            new["solutions"] = old["solutions"]
            notes.append("kept the held answers: the PDF's grid is theirs")
    if solved or new["solutions"] is old["solutions"]:
        notes += keep_backed_answers(old, new)
    elif all(e.get("solution") for e in old["entries"]):
        notes.append("filed unsolved: the PDF's grid is not the one the held answers were solved in")
    classes = sorted({m["class"] for m in found})
    notes.append(f"the FT's PDF over the file {old['source'].get('acquiredBy')} built "
                 f"({', '.join(classes) or 'no differences'})")
    printed = {where(e): e["clue"].get("text") for e in new["entries"]}
    fp.merge_annotations(new, old)
    new, more = ft.refile(new, old)
    notes += reprint_marks(new, printed)
    fp.write_puzzle_file(path, new, generator=fpp.GENERATOR if how == "live" else fpp.GENERATOR_WAYBACK)
    return notes + more


def reprint_marks(puzzle, printed):
    """Put the printed clue back where fetch_telegraph.refile() kept ours for
    having the same words: its hyphens and marks are the paper's ("far-
    reaching", where the blogger typed "farreaching"). The annotation's
    quotations are moved to the printed text; a clue whose annotation quotes
    words the printed text spells otherwise keeps ours. Returns notes."""
    import file_blog_puzzles as fbp
    notes = []
    for i, e in enumerate(puzzle["entries"]):
        text, want = e["clue"].get("text"), printed.get(where(e))
        if not want or not text or text == want or norm_text(text) != norm_text(want):
            continue
        try:
            ann = fbp.requote(e.get("annotation"), lambda q, want=want: same_words_in(q, want),
                              text, want)
        except ValueError as err:
            notes.append(f"{groups.entry_id(e)}: kept our clue, the annotation quotes it: {err}")
            continue
        clue = {k: v for k, v in e["clue"].items() if k != "italics"}
        e = {**e, "clue": {**clue, "text": want}}
        if ann is not None:
            e["annotation"] = ann
        puzzle["entries"][i] = e
    return notes


def same_words_in(quote, text):
    """The span of `text` that spells `quote`'s words (norm_text), or None."""
    want = norm_text(quote)
    if not want:
        return None
    for a in range(len(text)):
        if not text[a].isalnum() or (a and text[a - 1].isalnum()):
            continue
        for b in range(a + 1, len(text) + 1):
            got = norm_text(text[a:b])
            if got == want and (b == len(text) or not text[b].isalnum()):
                return text[a:b]
            if len(got) > len(want) or not want.startswith(got):
                break
    return None


def refile(adapter, limit=None):
    """Refile every puzzle the last report names whose differences refile
    settles, and every clean copy taken from elsewhere, up to `limit`."""
    one = {"guardian": refile_guardian, "independent": refile_independent,
           "ft": refile_ft}.get(adapter.name)
    if one is None:
        raise SystemExit("--refile: the guardian, independent and ft adapters refile here; the "
                         "Telegraph's is tools/fetch_telegraph.py --holes, and the Globe's "
                         "numbers are filed as globeandmail already")
    keys = adapter.ids()
    disk = held(adapter)
    report = REPORTS / f"{adapter.name}.jsonl"
    found = {r["id"]: r.get("mismatches") for r in map(json.loads, report.open(encoding="utf-8"))}
    done = Counter()
    for pid in sorted(keys):
        if limit is not None and done["refiled"] >= limit:
            break
        if (pid not in disk or not adapter.raw_file(keys[pid]).exists()
                or found.get(pid, []) is None):
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


# ------------------------------------------------------- every copy at once

#: The classes a majority of copies settles in our file. A grid, numbering or
#: light the copies dispute is refiled from one source or not at all, so those
#: are tallied and left to the per-source refiles.
VOTED = ("ANSWER", "ENUMERATION", "CLUE")
LEADS = REPORTS / "all-leads.jsonl"
CURSOR = REPORTS / "all-cursor.json"


#: Counts left at a clue's tail: a page that prints the count twice
#: (cryptic-27852's "(6) (6)") leaves one after the reader strips the other.
TRAILING_COUNTS = re.compile(r"(?:\s*\([\d\s,.\-–—'’]+\))+\s*$")


def ballot(entry, cls):
    """What one copy's light says for `cls`, normalised as diff() compares
    it, or None when it says nothing: no answer that fills the light, a
    pointer, no words, or a count copied from ours."""
    if cls == "ANSWER":
        sol = entry.get("solution")
        return sol if sol and len(sol) == entry["length"] else None
    clue = entry.get("clue") or {}
    text = clue.get("text")
    if CONTINUATION.match(text or "") or not norm_text(text):
        return None
    if cls == "ENUMERATION":
        return None if clue.get(ECHO) else norm_enum(clue.get("enumeration"))
    return norm_text(TRAILING_COUNTS.sub("", text))


def copies(pid, ours, adapters, keys):
    """[(adapter, its copy)] for every adapter holding this puzzle, each copy
    with the paper's known wrong answers put right."""
    out = []
    for a in adapters:
        key = keys.get(a.name, {}).get(pid)
        if key is None or not a.covers(ours):
            continue
        try:
            theirs = a.puzzle(key, ours) if isinstance(a, GeorgeHo) else a.puzzle(key)
        except Exception as err:  # noqa: BLE001 — an unreadable copy is no vote, named
            print(f"{pid}: {a.name}'s copy unreadable: {err}")
            continue
        if theirs is not None and theirs.get("id") == pid:
            out.append((a, witness(theirs)))
    return out


def ours_authority(ours, cls):
    """How far our file's value for `cls` is from the paper's print, or None
    when the file does not say: its clues and counts are where the file was
    retrieved from, its answers that too when published, a blog's when taken
    from a write-up, and unranked when a model solved them."""
    rest = RETRIEVED_AUTHORITY.get((ours.get("source") or {}).get("retrievedFrom"))
    if cls != "ANSWER":
        return rest
    origin = (ours.get("solutions") or {}).get("origin")
    return BLOG if origin == "writeup" else rest if origin in (None, "published") else None


def majority(ours, held_copies):
    """(verdicts, per-copy mismatches) over every copy of one puzzle.

    Each light's value in each VOTED class is put to a vote: ours is one
    vote, and every other origin one more, two reads of one origin (georgeho's
    scrape of bigdave44 and our parse of it) counting once and abstaining when
    they disagree. A copy whose grid is not ours votes on nothing. Where three
    or more votes are cast and a value other than ours holds more than half of
    them, it wins (`fixed`, "outvoted"). Where ours and one other origin are
    the only votes, source authority settles it: a copy nearer the paper's
    print than ours (Adapter.authority against ours_authority()) wins
    ("outranked"), one further from it leaves ours ("upheld"). Any other
    disagreement (equal or unknown authority, or three votes with no
    majority) is a lead and our file stands."""
    mine = {where(e): e for e in ours["entries"]}
    reads, found = defaultdict(list), []
    for a, theirs in held_copies:
        rows = diff(ours, theirs, exact=a.exact_clues)
        found.append((a, rows))
        if not any(m["class"] == "GRID" for m in rows):
            reads[a.origin_of(ours)].append((a, {where(e): e for e in theirs["entries"]}))
    verdicts = []
    for k, o in mine.items():
        for cls in VOTED:
            own = ballot(o, cls)
            if own is None:
                continue
            votes, shown, ranks = {"ours": own}, defaultdict(list), {}
            for origin, said in reads.items():
                got = {}
                for a, at in said:
                    if cls in a.votes and k in at and ballot(at[k], cls) is not None:
                        got.setdefault(ballot(at[k], cls), []).append((a, at[k]))
                if len(got) == 1:
                    value, by = next(iter(got.items()))
                    votes[origin] = value
                    shown[value] += by
                    ranks[origin] = min((a.authority for a, _ in by if a.authority is not None),
                                        default=None)
            tally = Counter(votes.values())
            if len(tally) == 1:
                continue
            top, n = tally.most_common(1)[0]
            settled = len(votes) >= 3 and n * 2 > len(votes)
            kind = "outvoted" if settled and top != own else "backed" if settled else "split"
            if len(votes) == 2:
                (them, top), = ((g, v) for g, v in votes.items() if g != "ours")
                mine_rank, their_rank = ours_authority(ours, cls), ranks[them]
                if None not in (mine_rank, their_rank) and mine_rank != their_rank:
                    kind = "outranked" if their_rank < mine_rank else "upheld"
            fixed = kind in ("outvoted", "outranked")
            verdicts.append({"class": cls, "light": groups.entry_id(o), "at": k,
                             "ours": own, "votes": votes, "fixed": fixed,
                             # backed: the majority is ours, the dissent is that
                             # copy's defect; upheld: ours outranks the one copy
                             # against it; split: neither, a lead for us.
                             "kind": kind,
                             "winner": top if fixed else own,
                             # The words written are the paper's own print where one votes.
                             "entry": (min(shown[top], key=lambda r: not r[0].exact_clues)[1]
                                       if fixed else None)})
    return verdicts, found


def conflicts(puzzle):
    """Cells two lights fill with different letters."""
    return {c for c, got in letters(puzzle).items() if len(got) > 1}


def apply_majority(ours, verdicts):
    """`ours` with every fixed verdict written in, or a verdict turned back
    into a lead (`why`) where writing it would cross a letter it does not
    share or rewrite a clue an annotation quotes."""
    import copy
    new = copy.deepcopy(ours)
    at = {where(e): e for e in new["entries"]}
    for v in verdicts:
        if not v["fixed"]:
            continue
        e, src = at[v["at"]], v["entry"]
        if v["class"] == "ANSWER":
            e["solution"] = v["winner"]
        elif v["class"] == "ENUMERATION":
            e["clue"]["enumeration"] = src["clue"]["enumeration"]
        elif e.get("annotation"):
            v.update(fixed=False, winner=v["ours"], kind="split",
                     why="the annotation quotes our clue")
        else:
            e["clue"]["text"] = src["clue"]["text"]
    if conflicts(new) - conflicts(ours):
        for v in verdicts:
            if v["fixed"] and v["class"] == "ANSWER":
                at[v["at"]]["solution"] = next(e["solution"] for e in ours["entries"]
                                               if where(e) == v["at"])
                v.update(fixed=False, winner=v["ours"], kind="split",
                         why="crossings disagree with it")
    drop_stale_annotations(ours, new)
    return new


def group_answer(puzzle, e):
    """The answer `e` leads: its own, or its group's lights end to end."""
    by_id = {groups.entry_id(x): x for x in puzzle["entries"]}
    return "".join(by_id[m].get("solution") or "" for m in e.get("group") or
                   [groups.entry_id(e)] if m in by_id)


def drop_stale_annotations(old, puzzle):
    """Drop, in place, each annotation of `puzzle` whose light's answer
    differs from `old`'s and no longer matches the annotation's, so the light
    is annotated again rather than explained as the answer it replaced."""
    was = {where(e): group_answer(old, e) for e in old["entries"]}
    for e in puzzle["entries"]:
        ann = e.get("annotation")
        answer = group_answer(puzzle, e)
        if not isinstance(ann, dict) or not ann.get("answer") or was.get(where(e)) == answer:
            continue
        if re.sub(r"[^A-Z]", "", ann["answer"].upper()) != answer.upper():
            del e["annotation"]
    if puzzle.get("annotatedBy") and not any(e.get("annotation") for e in puzzle["entries"]):
        del puzzle["annotatedBy"]


def ledger_majority(pid, verdicts):
    """Record each fix and its votes in corroborate's ledger."""
    import corroborate
    disputes = []
    for v in verdicts:
        if not v["fixed"]:
            continue
        cands = defaultdict(dict)
        for origin, value in v["votes"].items():
            cands[value][origin] = origin
        disputes.append(corroborate.Dispute(v["class"].lower(), v["light"], v["ours"],
                                            dict(cands), v["winner"],
                                            "authority" if v["kind"] == "outranked" else "majority"))
    if disputes:
        corroborate.record(pid, disputes)


def changed_files():
    """Puzzle files git sees as new or changed: tonight's filings, before
    the nightly commits them."""
    import subprocess
    root = Path(__file__).resolve().parent.parent
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", "puzzles"],
                         cwd=root, capture_output=True, text=True, check=True).stdout
    return {Path(line[3:].strip()).stem for line in out.splitlines()
            if line[3:].strip().endswith(".json")}


def corroborate_all(series=None, limit=None, only=None, new=False, write=False, start=None):
    """Every copy of each selected puzzle against ours at once (majority()),
    fixing what a majority settles when `write`. The selection is `only`, the
    files `new` names, or the next `limit` held puzzles after the cursor,
    wrapping, so bounded runs walk the whole corpus in turn (the
    cursor moves only when `write`, so a report-only run leaves it)."""
    adapters = [cls() for cls in ADAPTERS.values()
                if series is None or set(cls.series) & set(series)]
    for a in adapters:
        a.offline = True
    wanted = set(series) if series else {s for a in adapters for s in a.series}
    disk = held_paths(wanted)
    if only:
        todo = [p for p in only if p in disk]
    elif new:
        todo = sorted(changed_files() & disk.keys())
    else:
        order = sorted(disk)
        if start is None:
            start = json.loads(CURSOR.read_text()).get("after", "") if CURSOR.exists() else ""
        todo = [p for p in order if p > start] + [p for p in order if p <= start]
        todo = todo[:limit] if limit else todo
    if not todo:
        print("nothing to corroborate")
        return 0
    keys = {}
    for a in adapters:
        try:
            keys[a.name] = a.ids()
        except (Exception, SystemExit) as err:  # noqa: BLE001 — a source we lack is no vote
            print(f"{a.name}: no copies ({err})")
    pair, verdict_tally, leads, fixed_files = Counter(), Counter(), {}, 0
    copies_seen = Counter()
    for pid in todo:
        ours = read_puzzle_file(disk[pid])
        held_copies = copies(pid, ours, adapters, keys)
        copies_seen[len(held_copies)] += 1
        if not held_copies:
            continue
        verdicts, found = majority(ours, held_copies)
        for a, rows in found:
            pair[(a.name, "compared")] += 1
            pair.update((a.name, m["class"]) for m in rows)
        if write and any(v["fixed"] for v in verdicts):
            new_puzzle = apply_majority(ours, verdicts)
            if new_puzzle != ours:
                import fetch_puzzle
                ledger_majority(pid, verdicts)
                fetch_puzzle.write_puzzle_file(disk[pid], new_puzzle)
                fixed_files += 1
                print(f"fixed {pid}: " + "; ".join(
                    f"{v['light']} {v['class']} {v['ours']!r} -> {v['winner']!r} "
                    f"({', '.join(o for o, x in v['votes'].items() if x == v['winner'])})"
                    for v in verdicts if v["fixed"]))
        for v in verdicts:
            verdict_tally[(v["class"], "fixed" if v["fixed"] and write else v["kind"])] += 1
        lead = [{k: v[k] for k in ("class", "light", "kind", "votes", "why") if k in v}
                for v in verdicts if not (v["fixed"] and write)]
        leads[pid] = lead
        if only:
            print(json.dumps({"id": pid, "copies": [a.name for a, _ in held_copies],
                              "verdicts": [{k: v[k] for k in v if k not in ("at", "entry")}
                                           for v in verdicts]}, ensure_ascii=False, indent=1))
    if not only:
        REPORTS.mkdir(parents=True, exist_ok=True)
        kept = {}
        if LEADS.exists():
            for line in LEADS.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                kept[row["id"]] = row["leads"]
        kept.update(leads)
        LEADS.write_text("".join(json.dumps({"id": p, "leads": r}, ensure_ascii=False) + "\n"
                                 for p, r in sorted(kept.items()) if r), encoding="utf-8")
        if write and not new and todo:
            CURSOR.write_text(json.dumps({"after": todo[-1]}))
    print(f"visited {len(todo)}; copies per puzzle {dict(sorted(copies_seen.items()))}")
    print("mismatches by pair (ours against each copy):")
    names = sorted({n for n, _ in pair})
    for n in names:
        print(f"  {n:18} compared {pair[(n, 'compared')]:5}  " + "  ".join(
            f"{cls} {pair[(n, cls)]}" for cls in CLASSES if pair[(n, cls)]))
    print("verdicts (fixed; outvoted: a majority against ours, not applied; outranked: the "
          "one other copy is nearer the print, not applied; backed: a majority with ours "
          "against a copy; upheld: ours is nearer the print than the one copy against it; "
          "split: neither, a lead):")
    for cls in VOTED:
        print(f"  {cls:12} " + "  ".join(f"{k} {verdict_tally[(cls, k)]}" for k in
                                         ("fixed", "outvoted", "outranked", "backed", "upheld",
                                          "split")))
    print(f"files fixed: {fixed_files}; leads in {LEADS}")
    return fixed_files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", choices=sorted(ADAPTERS) + ["all"],
                    help="one source against ours, or `all`: every copy at once, majority rules")
    ap.add_argument("--series", nargs="+", help="all: only these series")
    ap.add_argument("--new", action="store_true",
                    help="all: only the puzzle files git sees as new or changed")
    ap.add_argument("--apply", action="store_true", help="all: write what a majority settles")
    ap.add_argument("--start", metavar="ID", help="all: begin after this id, not the cursor")
    ap.add_argument("--fetch", action="store_true", help="top up the cache first")
    ap.add_argument("--limit", type=int, help="fetch or refile at most this many")
    ap.add_argument("--refile", action="store_true",
                    help="refile from the source what the last report found (guardian, independent, ft)")
    ap.add_argument("--show", nargs="+", metavar="ID", help="diff these puzzles and print")
    args = ap.parse_args(argv)
    if args.source == "all":
        corroborate_all(args.series, args.limit, args.show, args.new, args.apply, args.start)
        return 0
    adapter = ADAPTERS[args.source]()
    if args.fetch:
        keys = adapter.ids()
        disk = held(adapter)
        todo = list(dict.fromkeys(keys[p] for p in sorted(disk) if p in keys
                                  and adapter.covers(load(adapter, disk[p]))))
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
