#!/usr/bin/env python3
"""Check our puzzles against another copy of the same puzzle, class by class.

    python3 tools/cross_validate.py telegraph --fetch      # top up the source cache
    python3 tools/cross_validate.py telegraph              # diff from the cache, write the report
    python3 tools/cross_validate.py telegraph --show telegraph-28936

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


ADAPTERS = {a.name: a for a in (Telegraph,)}


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
        if CONTINUATION.match(tc.get("text") or ""):
            continue
        if norm_enum(oc.get("enumeration")) != norm_enum(tc.get("enumeration")):
            out.append({"class": "ENUMERATION", "light": light,
                        "ours": oc.get("enumeration"), "theirs": tc.get("enumeration")})
        if norm_text(oc.get("text")) != norm_text(tc.get("text")):
            out.append({"class": "CLUE", "light": light,
                        "ours": oc.get("text"), "theirs": tc.get("text")})
    return out


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
        found = diff(ours, theirs)
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", choices=sorted(ADAPTERS))
    ap.add_argument("--fetch", action="store_true", help="top up the cache first")
    ap.add_argument("--show", nargs="+", metavar="ID", help="diff these puzzles and print")
    args = ap.parse_args(argv)
    adapter = ADAPTERS[args.source]()
    if args.fetch:
        keys = adapter.ids()
        disk = held(adapter)
        todo = [keys[p] for p in sorted(disk) if p in keys
                and adapter.covers(read_puzzle_file(disk[p]))]
        print(f"{len(todo)} puzzles held that {adapter.name} also serves", flush=True)
        fetch(adapter, todo)
    if args.show:
        for row in run(adapter, only=args.show):
            print(json.dumps(row, ensure_ascii=False, indent=1))
        return 0
    if not args.fetch:
        run(adapter)
    return 0


if __name__ == "__main__":
    sys.exit(main())
