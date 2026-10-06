#!/usr/bin/env python3
"""How far each newspaper series' archive years are from a full year, and why.

    python3 tools/archive_coverage.py                 # every scanned series, ranked
    python3 tools/archive_coverage.py --series times  # one series
    python3 tools/archive_coverage.py --json out.json # the same, machine-readable
    python3 tools/archive_coverage.py --save          # also keep it for tomorrow's deltas

The goal (docs/ARCHIVE_COVERAGE.md): every archive year holds about as many
puzzles as a modern year, about 300 for a Mon-Sat daily. For each series and
year this counts:

  printed   editions the paper printed (PRINTED below: weekdays, gaps)
  scanned   printed editions archive.org holds a scan of (the cached item
            listings of tools/fetch_archive_org_editions.py)
  filed     printed dates with a puzzle file in puzzles/<series>/

and gives every printed, unfiled edition one reason, read off the filer's
ledger (~/.cache/archive_org_editions/filed.jsonl): no scan, scan not
fetched, not yet read, no grid, no reading parses, blank clues held back, ...
The classes are ranked: recoverable ones (a fetch, a reader fix, a re-read)
first, by size.

--save writes ~/.cache/archive_coverage/latest.json (the previous one becomes
previous.json), from which the per-year deltas are printed.
"""
import argparse
import collections
import datetime
import functools
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import canberra_london_numbers
import fetch_archive_org_editions as fetcher

CACHE = Path(os.path.expanduser("~/.cache/archive_org_editions"))
LEDGER = CACHE / "filed.jsonl"
STATE = Path(os.path.expanduser("~/.cache/archive_coverage"))

#: Which days each series printed: the weekdays (0 = Monday), the first day
#: of its crossword, and the spans it did not appear at all. Christmas Day
#: is never printed. A series is counted only once it has a row here.
PRINTED = {
    "times": {"weekdays": range(6), "first": "1930-02-01",
              # The Times was shut by the lock-out of 1 Dec 1978 to 12 Nov 1979.
              "gaps": [("1978-12-01", "1979-11-12")]},
    "cryptic": {"weekdays": range(6), "first": "1929-01-05", "gaps": []},
    "ftcryptic": {"weekdays": range(6), "first": "1930-01-01", "gaps": []},
    "telegraph": {"weekdays": range(6), "first": "1925-07-30", "gaps": []},
}

#: Every unfiled-edition class: (key, what it means, the fix, recoverable,
#: the module that owns the fix). tools/coverage.py buckets by these.
#: Recoverable means this pipeline (fetch, OCR, a re-read) can still get it.
CLASSES = [
    ("not-fetched", "archive.org has the scan; tools/fetch_archive_org_editions.py has not fetched it",
     "fetch_archive_org_editions.py --group <paper>", True, "tools/fetch_archive_org_editions.py"),
    ("fetch-failed", "the scan's fetch failed (failures.tsv) and has not been retried",
     "fetch_archive_org_editions.py --group <paper>", True, "tools/fetch_archive_org_editions.py"),
    ("not-read", "fetched, never read by the filer", "the standing full pass (tools/ocr_full_pass.sh)", True, "tools/ocr_full_pass.sh"),
    ("blank-clues", "read; a clue is blank (readings disagree), held back", "re-read: better readers / VLM", True, "tools/file_archive_org_puzzles.py"),
    ("no-grid", "read; no grid found or rebuilt", "grid reader fix, then bump REREAD_BEFORE", True, "tools/file_archive_org_puzzles.py"),
    ("clues-dont-fit", "read; the rebuilt grid disagrees with the clues", "clue reader fix, then bump REREAD_BEFORE", True, "tools/file_archive_org_puzzles.py"),
    ("no-reading-parses", "read; no reading of the clue columns parses", "clue reader fix, then bump REREAD_BEFORE", True, "tools/file_archive_org_puzzles.py"),
    ("not-a-grid", "read; the ink under the title is not a grid", "grid finder fix, then bump REREAD_BEFORE", True, "tools/file_archive_org_puzzles.py"),
    ("crashed", "read; the reader raised on this title", "the traceback in the ledger's refused", True, "tools/file_archive_org_puzzles.py"),
    ("refused-no-cause", "read before refusals filed a cause; the next read stamps one",
     "the standing full pass re-reads it (bump REREAD_BEFORE in tools/ocr_full_pass.sh)", True, "tools/ocr_full_pass.sh"),
    ("write-refused", "read; the write path refused the puzzle", "see the ledger's refusedWrite", True, "tools/file_archive_org_puzzles.py"),
    ("read-not-filed", "read whole, but no file for that date", "look at the ledger row", True, "tools/file_archive_org_puzzles.py"),
    ("no-crossword-found", "fetched; no crossword heading found on any page we hold",
     ("the fetcher holds the wrong pages: titles the OCR garbled and the page densest with clue counts are read "
      "(DETECTOR_VERSION 5); for the rest, look for the grid by image on every leaf of the issue "
      "(only a crosswordless issue leaves the count), then DETECTOR_VERSION"), True, "tools/fetch_archive_org_editions.py"),
    ("filed-other-date", "its puzzle number is filed, under another date", "date the file right", True, "tools/file_archive_org_puzzles.py"),
    ("number-date-mismatch", "the item's date and the puzzle number disagree", "none: archive.org's date is wrong", False, "tools/file_archive_org_puzzles.py"),
    ("no-filer", "archive.org has the scan, in a one-issue-per-item collection the filer does not read",
     ("the fetcher already fetches pub_times; teach the filer its 1930 page (Paper for per_times_the-times_* items): "
      "1-3 digit numbers, a 13663px scan (4x NewsUK's), FOUR clue columns under the grid, the previous solution "
      "printed in letters"), True, "tools/file_archive_org_puzzles.py"),
    ("no-listing", "the year's archive.org item listing is not cached",
     "fetch_archive_org_editions.py --group <paper> --list (one metadata call an item)", True, "tools/fetch_archive_org_editions.py"),
    ("no-ocr", "archive.org holds the edition's PDF but never OCR'd it, so the page finder has no text",
     ("fetch the ~13 MB image-container PDF, take its page JPEGs (pypdf; no jp2 for most), find the grid page "
      "by image (grids_on, no OCR), then read it as a page with no text (ocr_headings); bulk OCR only on the "
      "desktop (tools/ocr_remote.py)"), True,
     "tools/fetch_archive_org_editions.py"),
    ("canberra-reprint", "archive.org holds no scan; a cached Canberra Times article reprints it (tools/canberra_london_numbers.py)",
     "fetch_trove.py zones $(canberra_london_numbers.py --ids scanless), then file_trove_puzzles.py", True, "tools/fetch_trove.py"),
    ("no-scan", "archive.org holds no scan of this edition", "another source (Trove, a book, a blog)", False, "tools/first_issue.py"),
]
CLASS = {c[0]: c for c in CLASSES}

#: fetch_archive_org_editions.py groups holding a paper's issues one item
#: each, which file_archive_org_puzzles.py does not read yet.
ONE_ISSUE_GROUPS = {"times": ["pub_times"]}


def printed_dates(series, until):
    spec = PRINTED[series]
    gaps = [(datetime.date.fromisoformat(a), datetime.date.fromisoformat(b)) for a, b in spec["gaps"]]
    d = datetime.date.fromisoformat(spec["first"])
    while d <= until:
        if d.weekday() in spec["weekdays"] and (d.month, d.day) != (12, 25) and not any(a <= d <= b for a, b in gaps):
            yield d.isoformat()
        d += datetime.timedelta(days=1)


@functools.cache
def corpus(series):
    """{date: puzzle number} and {number: date} of the series' filed puzzles.
    Each file's (date, number) is kept in STATE/corpus-<series>.json against
    its mtime and size, so a run re-reads only the files that changed."""
    cache_path = STATE / f"corpus-{series}.json"
    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        cache = {}
    fresh, by_date, by_number = {}, {}, {}
    for path in sorted((ROOT / "puzzles" / series).glob("*/*.json")):
        try:
            st = path.stat()
        except OSError:
            continue
        rel, stamp = f"{path.parent.name}/{path.name}", [st.st_mtime_ns, st.st_size]
        hit = cache.get(rel)
        if hit and hit[:2] == stamp:
            date, number = hit[2], hit[3]
        else:
            try:
                p = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            date, number = p.get("date"), p.get("number")
        fresh[rel] = stamp + [date, number]
        if date:
            by_date.setdefault(date, number)
            by_number[number] = date
    if fresh != cache:
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(fresh))
            os.replace(tmp, cache_path)
        except OSError:
            pass
    return by_date, by_number


def unread_collections(paper):
    """{date: item} of `paper`'s issues in its ONE_ISSUE_GROUPS."""
    out = {}
    for group in ONE_ISSUE_GROUPS.get(paper.key, ()):
        try:
            items = json.loads((CACHE / "items" / f"_group_{group}.json").read_text())
        except (OSError, ValueError):
            continue
        for i in items:
            if i.get("date"):
                out.setdefault(i["date"][:10], i["identifier"])
    return out


def scans(paper):
    """({date: "<item>/<slug>"} of every edition archive.org lists for
    `paper`, {year: listing cached}, {date: "<item>/<slug>"} of the editions
    it holds as a PDF only, with no OCR) from the cached item metadata."""
    out, listed, unread = {}, {}, {}
    group = {"times": "times", "ft": "ft", "guardian": "guardian", "telegraph": "telegraph"}[paper.key]
    try:
        items = [i["identifier"] for i in json.loads((CACHE / "items" / f"_group_{group}.json").read_text())]
    except (OSError, ValueError):
        items = []
    for item in items:
        m = paper.item.match(item)
        if not m:
            continue
        path = CACHE / "items" / f"{item}.json"
        listed[int(m.group(1))] = path.exists()
        if not path.exists():
            continue
        meta = json.loads(path.read_text())
        for names, into in ((fetcher.editions_of(meta), out), (fetcher.unread_scans(meta), unread)):
            for name in names:
                date = fetcher.edition_date(name)
                if date:
                    into.setdefault(date, f"{item}/{fetcher.slug_of(item, name)}")
    return out, listed, unread


def failed_fetches():
    """The "<item>/<slug>" of every edition failures.tsv logs, less those done.tsv has."""
    def rows(name):
        try:
            return [ln.split("\t") for ln in (CACHE / name).read_text(encoding="utf-8").splitlines()]
        except OSError:
            return []
    done = {f"{r[0]}/{fetcher.slug_of(r[0], r[1])}" for r in rows("done.tsv") if len(r) >= 2}
    return {f"{r[1]}/{fetcher.slug_of(r[1], r[2])}" for r in rows("failures.tsv") if len(r) >= 3} - done


def ledger():
    rows = {}
    try:
        text = LEDGER.read_text(encoding="utf-8")
    except OSError:
        return rows
    for ln in text.splitlines():
        if ln.strip():
            r = json.loads(ln)
            rows[r["edition"]] = r
    return rows


def verdict_class(row, by_number):
    """The class of an unfiled edition the filer has read: `row` is its
    ledger row. Read off the verdict's fields, never its prose: a refusal
    files its `cause` (file_archive_org_puzzles.REFUSALS), and one read
    before that field existed is "refused-no-cause" until it is read again."""
    vs = row.get("verdicts") or []
    if not vs:
        return "no-crossword-found"
    v = next((v for v in vs if v.get("id")), vs[0])
    if v.get("number") in by_number:
        return "filed-other-date"
    if v.get("refused"):
        return v.get("cause") or "refused-no-cause"
    if v.get("pending"):
        return "clues-dont-fit" if "grid" in v else "no-grid"
    if v.get("refusedWrite") or v.get("writeFailed"):
        return "write-refused"
    if v.get("blank"):
        return "blank-clues"
    return "read-not-filed"


def unfiled(paper, today):
    """(date, class, edition, elsewhere) of each printed date of `paper`
    through `today`, in date order: class None for a filed date, else its
    CLASSES key; edition the archive.org "<item>/<slug>" or None; elsewhere
    whether a one-issue collection holds it."""
    series = paper.series
    by_date, by_number = corpus(series)
    listing, listed, unread = scans(paper)
    rows, failed = ledger(), failed_fetches()
    elsewhere = unread_collections(paper)
    reprinted = {r["londonDate"] for r in canberra_london_numbers.load().values()
                 if r.get("londonDate")} if series == "times" else set()
    for date in printed_dates(series, today):
        y = int(date[:4])
        ed = listing.get(date)
        if date in by_date:
            cls = None
        elif not ed and date in elsewhere:
            cls = "no-filer"
        elif not ed and date in unread:
            cls, ed = "no-ocr", unread[date]
        elif not ed:
            cls = ("canberra-reprint" if date in reprinted else "no-scan") if listed.get(y, True) else "no-listing"
        elif ed in rows:
            cls = verdict_class(rows[ed], by_number)
        elif ed in failed:
            cls = "fetch-failed"
        elif (CACHE / ed / "pages.json").exists():
            cls = "not-read"
        else:
            cls = "not-fetched"
        yield date, cls, ed, date in elsewhere


def cover(paper, today):
    series = paper.series
    years = collections.defaultdict(lambda: collections.Counter())
    classes = collections.defaultdict(lambda: {"editions": 0, "years": collections.Counter(),
                                               "sample": []})
    for date, cls, ed, elsewhere in unfiled(paper, today):
        y = int(date[:4])
        ys = years[y]
        ys["printed"] += 1
        if ed or elsewhere:
            ys["scanned"] += 1
        if cls is None:
            ys["filed"] += 1
            continue
        c = classes[cls]
        c["editions"] += 1
        c["years"][y] += 1
        if ed and len(c["sample"]) < 3:
            c["sample"].append(ed)
    # Only the years a scan or a filed puzzle reaches: the rest is a source we lack.
    shown = {y: dict(c) for y, c in sorted(years.items()) if c["scanned"] or c["filed"]}
    modern = sorted(c["filed"] for y, c in years.items() if y >= today.year - 8 and y < today.year)
    ranked = sorted(classes.items(), key=lambda kv: (not CLASS[kv[0]][3], -kv[1]["editions"]))
    return {
        "series": series, "paper": paper.key,
        "modernYear": modern[len(modern) // 2] if modern else None,
        "years": shown,
        "classes": [{"class": k, "means": CLASS[k][1], "fix": CLASS[k][2], "recoverable": CLASS[k][3],
                     "editions": v["editions"],
                     "years": dict(sorted(v["years"].items())), "sample": v["sample"]}
                    for k, v in ranked],
    }


def report(cov, previous=None, top=8):
    """The ranked text table of one series' coverage; `previous` is the
    same series out of the last --save, for the per-year deltas."""
    out = [(f"== {cov['series']} (archive.org paper {cov['paper']}); a modern year files "
            f"{cov['modernYear']} =="), "Unfiled editions by class, recoverable first:"]
    for c in cov["classes"][:top]:
        span = list(c["years"])
        out.append(f"  {c['editions']:6,} {c['class']:<22}  "
                   f"{'' if c['recoverable'] else '(not recoverable here) '}{span[0]}-{span[-1]}  fix: {c['fix']}")
    prev = (previous or {}).get("years", {})
    out.append("year  printed scanned  filed  gap   (delta filed since last save)")
    for y, c in cov["years"].items():
        p = prev.get(str(y), prev.get(y, {})).get("filed")
        delta = "" if p is None or p == c.get("filed", 0) else f"  {c.get('filed', 0) - p:+d}"
        out.append(f"{y}  {c.get('printed', 0):7} {c.get('scanned', 0):7} {c.get('filed', 0):6} "
                   f"{c.get('printed', 0) - c.get('filed', 0):4}{delta}")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--series", action="append", help="times, cryptic, ftcryptic, telegraph (default: all)")
    ap.add_argument("--json", type=Path, help="write the coverage here as JSON")
    ap.add_argument("--save", action="store_true", help="keep it as latest.json for the next run's deltas")
    ap.add_argument("--top", type=int, default=8, help="classes listed per series")
    args = ap.parse_args(argv)
    import file_archive_org_puzzles as filer  # slow (the OCR stack), so only once asked
    today = datetime.datetime.now().astimezone().date()
    papers = [p for p in filer.PAPERS.values() if p.series in PRINTED and (not args.series or p.series in args.series)]
    try:
        previous = json.loads((STATE / "latest.json").read_text())
    except (OSError, ValueError):
        previous = {}
    result = {"at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
              "series": {p.series: cover(p, today) for p in papers}}
    for s, cov in result["series"].items():
        print(report(cov, previous.get("series", {}).get(s), args.top))
        print()
    if args.json:
        args.json.write_text(json.dumps(result, indent=1))
    if args.save:
        STATE.mkdir(parents=True, exist_ok=True)
        if (STATE / "latest.json").exists():
            os.replace(STATE / "latest.json", STATE / "previous.json")
        (STATE / "latest.json").write_text(json.dumps(result, indent=1))
    return result


if __name__ == "__main__":
    main()
