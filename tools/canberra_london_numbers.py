#!/usr/bin/env python3
"""The London Times number of each cached Canberra Times reprint.

    python3 tools/canberra_london_numbers.py                  # write the map, print per-year counts
    python3 tools/canberra_london_numbers.py --ids scanless   # article ids whose London edition has no scan
    python3 tools/canberra_london_numbers.py --ids all        # every numbered article id

The Canberra Times reprinted the London Times cryptic from the 1970s until
January 1982, one to three months late, with stretches of older puzzles
re-run out of order. The article text never carries the London number, so
it is found two ways:

  matched    the article's clue word triples hit one archive.org Times
             reading (downloads.ARCHIVE_ORG_SOURCE, puzzles/times)
             far better than any other, the reading printed first
  bracketed  the article sits between two matched Canberra days whose London
             numbers differ by exactly the number of Canberra cryptic days
             between them, so each day in between is the next number

Run-edge extrapolation was measured and refused: going on from a run of
consecutive numbers past its last matched day is right 36% of the time
within 10 days and ~0% past 30, because Canberra skips and re-runs.

A bracketed number has a London date only when the printed London days
between the two anchors' dates (archive_coverage.PRINTED) count the same
as the numbers between them; otherwise "londonDate" is null.

Writes {article id: {"date", "number", "how", "londonDate"}} to
downloads.TROVE/london_numbers.json. tools/file_trove_puzzles.py stamps
source.reprintOf from it, and tools/archive_coverage.py counts a no-scan
London edition the map covers as recoverable from Trove.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path
import downloads

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

CACHE = downloads.TROVE
OUT = CACHE / "london_numbers.json"
SOURCE = downloads.ARCHIVE_ORG_SOURCE
TIMES = ROOT / "puzzles" / "times"

#: The last Canberra date that reprinted London: from February 1982 none of
#: ~1,100 Canberra cryptics shares clues with any Times or Guardian scan.
LAST_REPRINT = "1982-01-31"
#: The first London number a reading may name (1970s editions sit near 13,000).
FIRST_NUMBER, LAST_NUMBER = 12000, 16500
#: A Canberra cryptic prints at least this many enumerations in its OCR.
MIN_COUNTS = 18
#: Share of the reading's clue word triples the article must hold, and how
#: far the best reading must lead the runner-up.
MATCH_SHARE = 0.25
MATCH_LEAD = 2.0
#: The most Canberra days two anchors may bracket.
MAX_SPAN = 80

MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
COUNT = re.compile(r"\(\d[\d,\-]*\)")


def triples(text):
    w = re.findall(r"[a-z]+", text.lower())
    return {" ".join(w[k:k + 3]) for k in range(len(w) - 2)}


def article_date(title):
    """'01 Jan 1972 - CRYPTIC CROSSWORD - Trove' -> ('1972-01-01', 'CRYPTIC CROSSWORD')."""
    m = re.match(r"(\d\d) (\w{3}) (\d{4}) - (.*?) - Trove", title or "")
    if not m or m.group(2) not in MONTHS:
        return None, None
    return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{m.group(1)}", m.group(4)


def articles(cache=CACHE, last=LAST_REPRINT):
    """[(id, date, ocr text)] of every cached cryptic article up to `last`."""
    out = []
    for meta in sorted(Path(cache).glob("*/meta.json")):
        try:
            m = json.loads(meta.read_text())
            text = (meta.parent / "ocr.txt").read_text(errors="replace")
        except (OSError, ValueError):
            continue
        date, title = article_date(m.get("title"))
        if not date or date > last or "QUICK" in title.upper() or len(COUNT.findall(text)) < MIN_COUNTS:
            continue
        out.append((str(m.get("id") or meta.parent.name), date, text))
    return out


def readings(dirs=(SOURCE, TIMES)):
    """{number: (date, clue word triples)} of the Times readings and files."""
    out = {}
    for d in dirs:
        for path in sorted(Path(d).glob("**/times-*.json")):
            try:
                p = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            n = p.get("number")
            if not isinstance(n, int) or not FIRST_NUMBER <= n <= LAST_NUMBER or n in out:
                continue
            sh = set()
            for e in p.get("entries", ()):
                sh |= triples((e.get("clue") or {}).get("text") or "")
            if len(sh) >= 20:
                out[n] = (p.get("date"), sh)
    return out


def match(arts, reads):
    """{article id: number} of the articles one reading claims."""
    index = {}
    for n, (_, sh) in reads.items():
        for t in sh:
            index.setdefault(t, []).append(n)
    found = {}
    for aid, date, text in arts:
        hits = {}
        for t in triples(text):
            for n in index.get(t, ()):
                hits[n] = hits.get(n, 0) + 1
        ranked = sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))
        if not ranked:
            continue
        n, k = ranked[0]
        rdate, sh = reads[n]
        if k / len(sh) < MATCH_SHARE or (len(ranked) > 1 and k < MATCH_LEAD * ranked[1][1]):
            continue
        if rdate and rdate > date:
            continue
        found[aid] = n
    return found


def printed_between(d1, d2):
    """The London printed dates strictly between ISO dates d1 and d2."""
    import archive_coverage
    spec = archive_coverage.PRINTED["times"]
    gaps = [(datetime.date.fromisoformat(x), datetime.date.fromisoformat(y)) for x, y in spec["gaps"]]
    a, b = datetime.date.fromisoformat(d1), datetime.date.fromisoformat(d2)
    out = []
    d = a + datetime.timedelta(days=1)
    while d < b:
        if d.weekday() in spec["weekdays"] and (d.month, d.day) != (12, 25) and not any(x <= d <= y for x, y in gaps):
            out.append(d.isoformat())
        d += datetime.timedelta(days=1)
    return out


def number(arts, found, reads, max_span=MAX_SPAN):
    """{article id: {date, number, how, londonDate}} for matched and bracketed articles."""
    # One article a Canberra day: the matched one, else the one with most counts.
    day = {}
    for aid, date, text in arts:
        key = (aid in found, len(COUNT.findall(text)))
        if date not in day or key > day[date][0]:
            day[date] = (key, aid)
    days = sorted(day)
    out = {}
    anchors = []
    for i, d in enumerate(days):
        aid = day[d][1]
        if aid in found:
            n = found[aid]
            out[aid] = {"date": d, "number": n, "how": "matched", "londonDate": reads[n][0]}
            anchors.append((i, n))
    for (i1, n1), (i2, n2) in zip(anchors, anchors[1:]):
        if not (1 < i2 - i1 <= max_span and n2 - n1 == i2 - i1):
            continue
        l1, l2 = reads[n1][0], reads[n2][0]
        between = printed_between(l1, l2) if l1 and l2 else []
        dated = len(between) == n2 - n1 - 1
        for k in range(1, i2 - i1):
            aid = day[days[i1 + k]][1]
            out[aid] = {"date": days[i1 + k], "number": n1 + k, "how": "bracketed",
                        "londonDate": between[k - 1] if dated else None}
    return out


def load(path=OUT):
    """The map tools/file_trove_puzzles.py and archive_coverage.py read; {} if never built."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--source", type=Path, action="append", help="reading dirs (default archiveorg-source + puzzles/times)")
    ap.add_argument("--out", type=Path, default=None, help="default <cache>/london_numbers.json")
    ap.add_argument("--ids", choices=["scanless", "all"], help="print article ids, one a line, and write nothing")
    args = ap.parse_args(argv)
    reads = readings(args.source or (SOURCE, TIMES))
    arts = articles(args.cache)
    found = match(arts, reads)
    nums = number(arts, found, reads)
    if args.ids:
        for aid, r in sorted(nums.items(), key=lambda kv: kv[1]["date"]):
            if args.ids == "all" or r["number"] not in reads:
                print(aid)
        return 0
    out = args.out or args.cache / "london_numbers.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(nums, indent=1, sort_keys=True))
    tmp.replace(out)
    per = {}
    for r in nums.values():
        y = (r["londonDate"] or "????")[:4]
        c = per.setdefault(y, [0, 0, 0])
        c[0 if r["how"] == "matched" else 1] += 1
        c[2] += r["number"] not in reads
    print(f"{len(arts)} Canberra cryptics to {LAST_REPRINT}, {len(reads)} Times readings, "
          f"{sum(1 for r in nums.values() if r['how'] == 'matched')} matched, "
          f"{sum(1 for r in nums.values() if r['how'] == 'bracketed')} bracketed -> {out}")
    print("London year  matched  bracketed  no-scan-reading")
    for y in sorted(per):
        print(f"{y:>11}  {per[y][0]:>7}  {per[y][1]:>9}  {per[y][2]:>15}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
