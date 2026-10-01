#!/usr/bin/env python3
"""Fetch Telegraph puzzles from the paper's own puzzle data bucket.

    python3 tools/fetch_telegraph.py --holes 200     # up to 200 the bucket has and puzzles/ lacks
    python3 tools/fetch_telegraph.py --holes 0       # list them, fetch nothing
    python3 tools/fetch_telegraph.py SLUG...         # one puzzle, e.g. toughie-crossword-93439

bigdave44.com hints every Telegraph puzzle, but a weekday hints post often
gives only some of the clues, and a grid cannot be rebuilt from part of a light
list, so those numbers stay holes (tools/file_telegraph_puzzles.py). The
Telegraph Puzzles app reads its puzzles from a public bucket, the same JSON
for subscribers and everyone else: grid, clues, enumerations and answers, the
prize puzzles' answers included once entries close.

  https://puzzlesdata.telegraph.co.uk/bundles/web/calendar/<year>.json
      every day's slug and printed number, per variant
  https://puzzlesdata.telegraph.co.uk/puzzles/<variant>/<slug>.json
      one puzzle

The calendars start 2015-03-02 (Cryptic No 27,738) for the daily and the
Saturday prize, 2020-08-11 (No 2,486) for the Toughie, and 2022-07-10 (No 24)
for the Sunday Toughie; a slug below the first calendared one is a 404. The
www.telegraph.co.uk pages answer python's TLS handshake with a 402; this
bucket does not.

Four variants, four series. The cryptic and prize-cryptic variants carry both
papers, and only the print day tells them apart: a Sunday is the Sunday
Telegraph's own sequence (~3,400), any other day the daily's (~31,300). A
calendar number that breaks its variant's running order is not that puzzle:
the Christmas specials are numbered from 100,000, and a few days carry a
reprint under an old number.

Writes puzzles/<series>/<year>/<series>-<number>.json. It never reindexes.
"""
import argparse
import bisect
import datetime
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enumeration  # noqa: E402
from fetch_puzzle import (flatten_clue, puzzle_files, puzzle_path,  # noqa: E402
                          read_puzzle_file, separators, write_puzzle_file)
import series as series_meta  # noqa: E402

TOOL = "tools/fetch_telegraph.py"
BUCKET = "https://puzzlesdata.telegraph.co.uk"
FIRST_YEAR = 2015
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
DELAY = 2.0
#: The bucket's variant -> the series on a weekday and on a Sunday.
VARIANTS = {
    "cryptic-crossword-1": ("telegraph", "sundaytel"),
    "prize-cryptic": ("telegraph", "sundaytel"),
    "toughie-crossword": ("toughie", "toughie"),
    "prize-toughie": ("sundaytough", "sundaytough"),
}
PAPER = {"telegraph": "Telegraph cryptic crossword", "toughie": "Telegraph Toughie",
         "sundaytel": "Sunday Telegraph cryptic crossword",
         "sundaytough": "Sunday Telegraph Toughie"}
#: Where a reader plays it. The app has no per-puzzle address it keeps, so
#: every puzzle credits the same page, as the Independent's do.
PLAY_URL = "https://www.telegraph.co.uk/puzzles/"
TITLE = re.compile(r"\bNo\.?\s*([\d,]+)\s*$")


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def variant_of(slug):
    """"cryptic-crossword-37195" -> "cryptic-crossword-1"; the others are named
    as their slugs are."""
    stem = slug.rsplit("-", 1)[0]
    return next(v for v in VARIANTS if v in (stem, stem + "-1"))


def series_for(variant, day):
    weekday, sunday = VARIANTS[variant]
    return sunday if day.weekday() == 6 else weekday


def calendar(years):
    """[(series, number, date, variant, slug)] over the given years' calendars,
    with each number that breaks its series' running order dropped."""
    rows = []
    for year in years:
        try:
            cal = http_json(f"{BUCKET}/bundles/web/calendar/{year}.json")
        except urllib.error.HTTPError as err:
            if err.code == 404:
                continue
            raise
        rows += calendar_rows(cal)
        time.sleep(DELAY)
    return in_order(rows)


def calendar_rows(cal):
    rows = []
    for variant in VARIANTS:
        for month, days in (cal.get("calendar") or {}).get(variant, {}).items():
            numbers = (cal.get("numbers") or {}).get(variant, {}).get(month, {})
            for d, slug in days.items():
                if not str(numbers.get(d) or "").isdigit():
                    continue
                day = datetime.date.fromisoformat(f"{month}-{int(d):02d}")
                rows.append((series_for(variant, day), int(numbers[d]), day, variant, slug))
    return rows


def in_order(rows):
    """Each series' longest run of numbers rising with the date, and nothing
    else: a special numbered from 100,000 or a reprint under an old number is
    never the puzzle the sequence says is due, and dropping the fewest rows
    that break the order is what leaves only those out."""
    by_series = {}
    for row in sorted(rows, key=lambda r: (r[0], r[2])):
        by_series.setdefault(row[0], []).append(row)
    out = []
    for seq in by_series.values():
        tails, back = [], [None] * len(seq)  # tails[k]: index ending the best run of k+1
        for i, row in enumerate(seq):
            k = bisect.bisect_left([seq[t][1] for t in tails], row[1])
            back[i] = tails[k - 1] if k else None
            tails[k:k + 1] = [i]
        i = tails[-1] if tails else None
        while i is not None:
            out.append(seq[i])
            i = back[i]
    return out


def span(text):
    """"3-9" -> (3, 9), "7" -> (7, 7); 1-based, as the bucket writes them."""
    a, _, b = str(text).partition("-")
    return int(a), int(b or a)


def parse(doc, variant):
    """One bucket puzzle -> this app's puzzle dict."""
    j = doc.get("json", doc)
    copy = j["copy"]
    m = TITLE.search(copy.get("title") or "")
    if not m:
        raise ValueError(f"no number in title {copy.get('title')!r}")
    number = int(m.group(1).replace(",", ""))
    day = datetime.datetime.strptime(copy["date-publish"], "%A, %d %B %Y").date()
    series = series_for(variant, day)
    cols, rows = int(copy["gridsize"]["cols"]), int(copy["gridsize"]["rows"])
    words = {w["id"]: w for w in copy["words"]}
    lights, clues = {}, {}
    for group in copy["clues"]:
        direction = group["title"].lower()
        for c in group["clues"]:
            if not str(c["number"]).isdigit():
                raise ValueError(f"clue number {c['number']!r} {direction}: not a number")
            word = words[c["word"]]
            (x1, x2), (y1, y2) = span(word["x"]), span(word["y"])
            cells = ([(x, y1) for x in range(x1, x2 + 1)] if direction == "across"
                     else [(x1, y) for y in range(y1, y2 + 1)])
            solution = re.sub(r"[^A-Z]", "", (word.get("solution") or "").upper())
            if len(solution) != len(cells):
                raise ValueError(f"{c['number']} {direction}: answer {solution!r} "
                                 f"does not fill {len(cells)} cells")
            key = (int(c["number"]), direction)
            lights[key] = {"number": key[0], "direction": direction,
                           "position": {"x": x1 - 1, "y": y1 - 1},
                           "length": len(cells), "solution": solution}
            clues[key] = c
    # A linked answer is printed once, on its first light, whose `links` name
    # the rest; each of those carries "See 1 Across" and no enumeration.
    entries, done = [], set()
    for key, c in clues.items():
        if key in done:
            continue
        members = [key] + [(int(ln["number"]), ln["direction"].lower())
                           for ln in c.get("links") or ()]
        if any(m not in lights for m in members):
            raise ValueError(f"{key[0]} {key[1]}: links a light the grid lacks")
        fmt = re.sub(r"\s+", "", c.get("format") or "") or str(lights[key]["length"])
        seps = separators(fmt, [lights[m]["length"] for m in members])
        text, italics = flatten_clue(html.unescape(c["clue"]).strip())
        group = [f"{n}-{d}" for n, d in members]
        for i, m in enumerate(members):
            entries.append({
                **{k: v for k, v in lights[m].items() if k != "solution"},
                "clue": (enumeration.clue(f"{text} ({fmt})", separators=seps[0], italics=italics)
                         if i == 0 else
                         enumeration.clue(f"See {key[0]}", separators=seps[i])),
                **({"group": group} if len(group) > 1 and i == 0 else {}),
                "solution": lights[m]["solution"],
            })
            done.add(m)
    entries.sort(key=lambda e: (e["position"]["y"], e["position"]["x"], e["direction"]))
    setter = (copy.get("setter") or copy.get("byline") or "").strip() or None
    return {
        "id": series_meta.puzzle_id(series, number),
        "number": number,
        "series": series,
        "name": f"{PAPER[series]} No {number:,}",
        "setter": setter or series_meta.default_setter(series),
        "date": day.isoformat(),
        "dimensions": {"cols": cols, "rows": rows},
        "source": {"url": PLAY_URL},
        "solutions": {"origin": "published"},
        "entries": entries,
    }


def blog_setters():
    """{(series, number): setter} off bigdave44.com's parsed posts, for the
    older Toughies the bucket leaves unbylined; empty when the cache is absent."""
    import parse_bigdave44
    out = {}
    if parse_bigdave44.OUT.exists():
        for line in parse_bigdave44.OUT.open(encoding="utf-8"):
            rec = json.loads(line)
            if rec.get("setter"):
                out[(rec["series"], rec["number"])] = rec["setter"]
    return out


def fetch(variant, slug, expect=None, setters=None):
    puzzle = parse(http_json(f"{BUCKET}/puzzles/{variant}/{slug}.json"), variant)
    if not puzzle.get("setter") and setters:
        puzzle["setter"] = setters.get((puzzle["series"], puzzle["number"]))
    if expect and (puzzle["series"], puzzle["number"]) != expect:
        raise ValueError(f"{slug} is {puzzle['id']}, the calendar says {expect[0]}-{expect[1]}")
    path = puzzle_path(puzzle["series"], puzzle["number"])
    if path.exists():
        print(f"held {puzzle['id']}: left alone")
        return None
    write_puzzle_file(path, puzzle, generator=TOOL)
    print(f"fetched {puzzle['id']} ({puzzle['date']})")
    return puzzle


def holes(rows):
    have = {p["id"] for p in (read_puzzle_file(f) for f in puzzle_files())
            if p.get("series") in PAPER}
    return [r for r in rows if series_meta.puzzle_id(r[0], r[1]) not in have]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--holes", type=int, metavar="N",
                    help="fetch up to N puzzles the bucket has and puzzles/ lacks, oldest first")
    ap.add_argument("slugs", nargs="*", help="bucket slugs, e.g. cryptic-crossword-37195")
    args = ap.parse_args(argv)
    if args.slugs:
        for slug in args.slugs:
            variant = variant_of(slug)
            fetch(variant, slug)
            time.sleep(DELAY)
        return 0
    if args.holes is None:
        ap.error("give --holes N or slugs")
    todo = holes(calendar(range(FIRST_YEAR, datetime.date.today().year + 1)))
    todo.sort(key=lambda r: r[2])
    by = {}
    for r in todo:
        by[r[0]] = by.get(r[0], 0) + 1
    print(f"bucket holds {len(todo)} puzzles not on disk: "
          + ", ".join(f"{s} {n}" for s, n in sorted(by.items())))
    done = failed = 0
    setters = blog_setters()
    for series, number, day, variant, slug in todo[:args.holes]:
        try:
            if fetch(variant, slug, expect=(series, number), setters=setters):
                done += 1
        except Exception as err:  # noqa: BLE001 — one bad puzzle must not stop the walk
            failed += 1
            print(f"failed: {series}-{number} {slug}: {err}")
        time.sleep(DELAY)
    print(f"done: {done} fetched, {failed} failed")
    return 1 if failed and not done else 0


if __name__ == "__main__":
    sys.exit(main())
