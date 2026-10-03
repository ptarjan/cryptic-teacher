#!/usr/bin/env python3
"""Fetch the Times Quick Cryptic from the Times's own puzzle feed and file the
numbers nothing else holds.

    python3 tools/fetch_times_feed.py --walk      # cache every Quick the feed has
    python3 tools/fetch_times_feed.py --gaps      # look again for numbers it skipped
    python3 tools/fetch_times_feed.py --file      # file the cached ones not on disk
    python3 tools/fetch_times_feed.py --first     # fetch and file No 1 alone
    python3 tools/fetch_times_feed.py --dry-run --file

feeds.thetimes.co.uk/puzzles/crossword/<YYYYMMDD>/<id>/data.json is the JSON
the Times's web player reads: clues, enumerations, answers and the grid, as
printed, back to Quick Cryptic No 1 (10 March 2014, id 100). It answers only
when the date is the puzzle's print date and the id is its own, and lists
nothing, so the walk finds each puzzle from the last: the feed numbers a
series' puzzles in batches of consecutive ids, so the next Quick is a few ids
on and a day later, and a week's batch may sit hundreds of ids from the last,
so the search widens outward from the last id, and from the ids the blog's
own links to the feed give for the fortnight ahead, until it finds the next. Only found puzzles are cached, one file per puzzle in
~/cryptic-setter-data/times-feed/.

Filing goes through write_puzzle_file like any fetcher; a number already on
disk (rebuilt from the timesforthetimes blog) is never rewritten, and a number
the Globe and Mail reprints is left to it (series.py `reprints`).
"""
import argparse
import concurrent.futures
import datetime
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

CACHE = Path.home() / "cryptic-setter-data" / "times-feed"
URL = "https://feeds.thetimes.co.uk/puzzles/crossword/{date}/{id}/data.json"
UA = "Mozilla/5.0 (cryptic-teacher; +https://github.com/ptarjan/cryptic-teacher)"
TOOL = "tools/fetch_times_feed.py"

#: Quick Cryptic No 1: the walk's first puzzle.
FIRST = (datetime.date(2014, 3, 10), 100)
#: How far either side of the last id the search for the next reaches, in
#: widening rounds, and over how many printing days.
RADII = (2, 300, 1500, 6000)
#: How many days after the last Quick a blog link's id is taken as a centre.
HINT_DAYS = 14
DAYS_AHEAD = 3
CHUNK = 64
#: How far past its neighbours' ids fill_gaps looks for a skipped number.
GAP_REACH = 60
#: How far from another puzzle's id that week seed() looks for the Quick.
SEED_REACH = 2500
SUNDAY = 6
THREADS = 32
QUICK = "Quick Cryptic"
TITLE_NUMBER = re.compile(r"(?:No\.?|Number)\s*\(?\s*0*(\d+)", re.I)


def fetch(date, pid):
    """The feed's data for (date, id), or None where the pair is not a puzzle."""
    url = URL.format(date=date.strftime("%Y%m%d"), id=pid)
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read())["data"]
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
        except (urllib.error.URLError, TimeoutError, ValueError):
            continue
    return None


def number_of(data):
    m = TITLE_NUMBER.search(data["copy"].get("title") or data.get("headline") or "")
    return int(m.group(1)) if m else None


def cache_path(date, pid):
    return CACHE / f"{date:%Y%m%d}-{pid}.json"


def cached():
    """[(date, id, data)] in id order."""
    out = []
    for p in CACHE.glob("*.json"):
        d, pid = p.stem.split("-")
        out.append((datetime.datetime.strptime(d, "%Y%m%d").date(), int(pid),
                    json.loads(p.read_text(encoding="utf-8"))))
    return sorted(out, key=lambda t: (t[0], t[1]))


def blog_hints():
    """{date: [id, ...]} of every feed link the timesforthetimes posts carry:
    any puzzle's id that week puts the search near that week's batch."""
    import collections
    posts = Path.home() / "cryptic-setter-data" / "timesforthetimes" / "posts"
    link = re.compile(r"feeds\.thetimes\.co\.uk/(?:timescrossword|puzzles/crossword)/(\d{8})/(\d+)")
    out = collections.defaultdict(set)
    for p in posts.glob("*.json"):
        for d, pid in link.findall(p.read_text(encoding="utf-8", errors="replace")):
            try:
                out[datetime.datetime.strptime(d, "%Y%m%d").date()].add(int(pid))
            except ValueError:
                continue
    return {d: sorted(v) for d, v in out.items()}


HINTS = None


def centres(date, pid):
    """`pid`, then the ids the blog links in the fortnight after `date`."""
    global HINTS
    if HINTS is None:
        HINTS = blog_hints()
    near = [i for d, ids in HINTS.items()
            if date < d <= date + datetime.timedelta(days=HINT_DAYS) for i in ids]
    return [pid, *sorted(set(near) - {pid}, key=lambda i: abs(i - pid))]


def find_next(pool, date, pid, number, until):
    """The next Quick after No `number` (printed `date`, id `pid`): on one of
    the next printing days, at the id nearest `pid`. A week's Quicks take
    consecutive ids, but the next week's batch may sit hundreds of ids either
    side, so the search widens outward from `pid`, nearest first."""
    days, d = [], date
    while len(days) < DAYS_AHEAD:
        d += datetime.timedelta(days=1)
        if d > until:
            break
        if d.weekday() != SUNDAY:
            days.append(d)
    tried = set()
    middles = centres(date, pid)
    for radius in RADII:
        for day in days:
            for mid in middles if radius > RADII[0] else [pid]:
                ids = [mid + k for r in range(radius + 1) for k in ((r, -r) if r else (0,))]
                ids = [i for i in ids if (day, i) not in tried and i > 0]
                for at in range(0, len(ids), CHUNK):
                    chunk = ids[at:at + CHUNK]
                    tried.update((day, i) for i in chunk)
                    got = pool.map(lambda i, day=day: fetch(day, i), chunk)
                    hits = [(day, i, data) for i, data in zip(chunk, got)
                            if data and data["copy"].get("crosswordtype") == QUICK
                            and (number_of(data) or 0) > number]
                    if hits:
                        return min(hits, key=lambda h: (number_of(h[2]), abs(h[1] - pid)))
    return None


def seed(date, near, reach=SEED_REACH):
    """(id, data) of the Quick printed on `date`, searched outward from id
    `near` (another puzzle's id that week), or None."""
    with concurrent.futures.ThreadPoolExecutor(THREADS) as pool:
        deltas = [k for r in range(reach + 1) for k in ((r, -r) if r else (0,))]
        for at in range(0, len(deltas), CHUNK):
            chunk = [k for k in deltas[at:at + CHUNK] if near + k > 0]
            for k, data in zip(chunk, pool.map(lambda k: fetch(date, near + k), chunk)):
                if data and data["copy"].get("crosswordtype") == QUICK:
                    cache_path(date, near + k).write_text(
                        json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    return near + k, data
    return None


def walk(until=None, below=None, log=print, start=None):
    """Cache every Quick from the highest-numbered cached one (or No 1, or
    `start`, a (date, id) cached already) to `until`, or to No `below`."""
    CACHE.mkdir(parents=True, exist_ok=True)
    until = until or datetime.date.today()
    have = cached()
    if start:
        date, pid = start
        data = json.loads(cache_path(date, pid).read_text(encoding="utf-8"))
    elif have:
        date, pid, data = max(have, key=lambda t: number_of(t[2]) or 0)
    else:
        date, pid = FIRST
        data = fetch(date, pid)
        cache_path(date, pid).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    number = number_of(data)
    with concurrent.futures.ThreadPoolExecutor(THREADS) as pool:
        while below is None or number < below - 1:
            hit = find_next(pool, date, pid, number, until)
            if hit is None:
                log(f"no Quick after No {number} ({date}, id {pid}) within reach; stopped")
                return
            date, pid, data = hit
            number = number_of(data)
            cache_path(date, pid).write_text(json.dumps(data, ensure_ascii=False),
                                             encoding="utf-8")
            log(f"{date} id {pid}: No {number}")


def fill_gaps(log=print):
    """Look again for each number the walk stepped over (it takes the lowest
    number it finds next): its id lies near its cached neighbours' and its
    day between theirs."""
    found = {}
    for date, pid, data in cached():
        n = number_of(data)
        if n and data["copy"].get("crosswordtype") == QUICK:
            found.setdefault(n, (date, pid))
    order = sorted(found)
    with concurrent.futures.ThreadPoolExecutor(THREADS) as pool:
        for a, b in zip(order, order[1:]):
            if b - a < 2:
                continue
            (da, ia), (db, ib) = found[a], found[b]
            days = [da + datetime.timedelta(days=k) for k in range((db - da).days + 1)]
            days = [d for d in days if d.weekday() != SUNDAY]
            lo, hi = min(ia, ib), max(ia, ib)
            ids = (range(lo - GAP_REACH, hi + GAP_REACH + 1) if hi - lo <= 4 * GAP_REACH else
                   [*range(lo - GAP_REACH, lo + GAP_REACH + 1),
                    *range(hi - GAP_REACH, hi + GAP_REACH + 1)])
            jobs = [(d, i) for d in days for i in ids if i > 0]
            hits = 0
            for (d, i), data in zip(jobs, pool.map(lambda j: fetch(*j), jobs)):
                if (data and data["copy"].get("crosswordtype") == QUICK
                        and a < (number_of(data) or 0) < b):
                    cache_path(d, i).write_text(json.dumps(data, ensure_ascii=False),
                                                encoding="utf-8")
                    hits += 1
            log(f"between No {a} and No {b}: {hits} found")


def grid_of(data):
    """The grid as rows of '#' (block) and '.' (light), from the solution."""
    copy = data["copy"]
    cols, rows = int(copy["gridsize"]["cols"]), int(copy["gridsize"]["rows"])
    sol = copy["settings"]["solution"]
    if len(sol) != cols * rows:
        raise ValueError(f"solution holds {len(sol)} cells, not {cols}x{rows}")
    return ["".join("#" if c == " " else "." for c in sol[r * cols:(r + 1) * cols])
            for r in range(rows)]


def convert(data, date):
    """(puzzle, None) or (None, why it cannot be filed)."""
    import enumeration
    import reconstruct_grid as rg
    import series as series_meta

    number = number_of(data)
    if not number:
        return None, "no number in the title"
    grid = grid_of(data)
    lights = rg.light_cells(grid)
    entries = []
    for block in data["copy"]["clues"]:
        direction = block["title"].strip().lower()
        for c in block["clues"]:
            key = (int(c["number"]), direction)
            if key not in lights:
                return None, f"{key[0]} {direction} is no light in the grid"
            cells = lights[key]
            text = re.sub(r"\s+", " ", c.get("clue") or "").strip()
            if not text:
                return None, f"{key[0]} {direction} has no clue"
            fmt = (c.get("format") or "").strip()
            answer = re.sub(r"[^A-Z]", "", (c.get("answer") or "").upper())
            entry = {
                "number": key[0], "direction": direction,
                "position": {"x": cells[0][1], "y": cells[0][0]},
                "length": len(cells),
                "clue": enumeration.clue(f"{text} ({fmt})" if fmt else text),
            }
            if len(answer) == len(cells):
                entry["solution"] = answer
            entries.append(entry)
    if {(e["number"], e["direction"]) for e in entries} != set(lights):
        return None, "the clues do not cover the grid's lights"
    entries.sort(key=lambda e: (e["direction"] != "across", e["number"]))
    pub, kind = series_meta.publisher("timesquick"), series_meta.kind("timesquick").lower()
    setter = (data["copy"].get("setter") or data["copy"].get("byline") or "").strip()
    return {
        "id": series_meta.puzzle_id("timesquick", number),
        "number": number,
        "series": "timesquick",
        "name": f"{pub} {kind} crossword No {number:,}",
        "setter": setter or series_meta.default_setter("timesquick"),
        "date": date.isoformat(),
        "dimensions": {"cols": len(grid[0]), "rows": len(grid)},
        "source": {"url": URL.format(date=f"{date:%Y%m%d}", id=data["copy"]["id"])
                   .removesuffix("data.json")},
        "solutions": {"origin": "published"},
        "entries": entries,
    }, None


def file_all(write=True, log=print, only=None):
    import file_blog_puzzles
    from fetch_puzzle import puzzle_path, write_puzzle_file

    reprints = file_blog_puzzles.reprinted_from()
    filed, held, skipped = 0, 0, {}
    for date, _, data in cached():
        if data["copy"].get("crosswordtype") != QUICK:
            continue
        number = number_of(data)
        if only is not None and number != only:
            continue
        by = number and file_blog_puzzles.reprinted_by(reprints, "timesquick", number)
        if by:
            skipped[f"{by} reprints it"] = skipped.get(f"{by} reprints it", 0) + 1
            continue
        if number and puzzle_path("timesquick", number).exists():
            held += 1
            continue
        puzzle, why = convert(data, date)
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            log(f"  {date} No {number}: {why}")
            continue
        try:
            if write:
                write_puzzle_file(puzzle_path("timesquick", number), puzzle, generator=TOOL)
        except ValueError as e:
            skipped["refused by the write path"] = skipped.get("refused by the write path", 0) + 1
            log(f"  {puzzle['id']}: {e}")
            continue
        filed += 1
    log(f"{'filed' if write else 'would file'} {filed}; already held {held}")
    for why, n in sorted(skipped.items(), key=lambda kv: -kv[1]):
        log(f"  skipped {n}: {why}")
    return filed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--walk", action="store_true", help="cache every Quick the feed has")
    ap.add_argument("--first", action="store_true", help="fetch and file No 1 alone")
    ap.add_argument("--until", type=datetime.date.fromisoformat, help="walk no further")
    ap.add_argument("--below", type=int, help="walk no further than this number")
    ap.add_argument("--gaps", action="store_true", help="look again for numbers the walk skipped")
    ap.add_argument("--file", action="store_true", help="file the cached Quicks not on disk")
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    a = ap.parse_args(argv)
    if a.first:
        CACHE.mkdir(parents=True, exist_ok=True)
        data = fetch(*FIRST)
        if not data:
            print(f"Quick Cryptic No 1: {URL.format(date=f'{FIRST[0]:%Y%m%d}', id=FIRST[1])} "
                  "answered nothing", file=sys.stderr)
            return 1
        cache_path(*FIRST).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        file_all(only=1)
        import fetch_puzzle
        fetch_puzzle.reindex()
        return 0
    if a.walk:
        walk(a.until, a.below, log=lambda s: print(s, flush=True))
    if a.gaps:
        fill_gaps(log=lambda s: print(s, flush=True))
    if a.file:
        file_all(write=not a.dry_run)
        if not a.dry_run:
            import fetch_puzzle
            fetch_puzzle.reindex()
    return 0


if __name__ == "__main__":
    sys.exit(main())
