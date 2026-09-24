#!/usr/bin/env python3
"""Cache the Wayback Machine's copies of The Times's crossword listing page,
the one first-party source for which day each Times puzzle number was printed.

    python3 tools/fetch_times_listing.py            # top up the cache
    python3 tools/fetch_times_listing.py --status   # what the cache proves

thetimes.com/puzzles/crossword lists each puzzle of the last week or two as a
card: "Sunday June 2 | No 5114", or since late 2024 "Sunday December 22 |
5143". The live page refuses a script, but the
Wayback Machine has captured it most days since September 2023 (the
thetimes.co.uk host until mid-2024, thetimes.com since), so one capture every
few days covers every number printed since. The card gives weekday, month and
day but no year; the year is the capture's, or the one before when the month
is later than the capture's. The weekday is then a check: a card whose weekday
disagrees with the date that yields is dropped, not trusted. A card saying
"Today" or "Yesterday" is skipped: the next capture, five days on, names
its day.

The prize puzzles (Saturday's Times, the Jumbo, the Sunday Times) are blogged
after entries close, so the blog's post date is not their print date. This is
the fact tools/file_times_puzzles.py dates them from.
"""
import argparse
import datetime
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CACHE = Path.home() / "cryptic-setter-data" / "times-listing"
HOSTS = ("thetimes.co.uk", "thetimes.com")
CDX = ("https://web.archive.org/cdx/search/cdx?url={host}/puzzles/crossword"
       "&output=json&filter=statuscode:200&collapse=timestamp:8")
CAPTURE = "https://web.archive.org/web/{ts}id_/{url}"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

#: Seconds between captures: Wayback throttles a client much faster than this.
PAUSE = 10

#: A capture lists about eight days of Jumbos and two Sundays, so one capture
#: in every five days overlaps the next and misses no number.
EVERY = datetime.timedelta(days=5)

#: The listing's slug for each series this repo dates from it.
SLUGS = {"times-cryptic": "times", "times-cryptic-jumbo": "timesjumbo",
         "sunday-times-cryptic": "sundaytimes", "times-quick-cryptic": "timesquick"}

CARD = re.compile(
    r'href="/puzzles/crossword/([a-z0-9-]+?)-no-(\d+)-[a-z0-9]+"'
    r'.{0,900}?<span[^>]*>([A-Za-z]+)(?: ([A-Za-z]+) (\d{1,2}))?</span>'
    r'<span[^>]*>\s*\|\s*(?:No\s*)?(\d+)</span>', re.DOTALL)
MONTHS = {datetime.date(2000, i, 1).strftime("%B"): i for i in range(1, 13)}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        return gunzip(r.read())


def gunzip(raw):
    """The page as captured. Wayback sends some captures gzipped whatever the
    request said, and urllib does not undo it: the cards are then unreadable
    bytes and the capture proves nothing, silently."""
    return gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw


def captures():
    """[(timestamp, original url)] of every day's capture, oldest first."""
    out = []
    for host in HOSTS:
        rows = json.loads(get(CDX.format(host=host)))[1:]
        out += [(r[1], r[2]) for r in rows]
    return sorted(out)


def wanted(caps, have):
    """The captures to fetch: one every EVERY days, counting the cached ones."""
    picked, last = [], None
    for ts, url in caps:
        day = datetime.date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
        if ts in have or last is None or day - last >= EVERY:
            if ts not in have:
                picked.append((ts, url))
            last = day
    return picked


def cards(ts, page):
    """[(series, number, date)] a capture proves."""
    taken = datetime.date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
    out = []
    for slug, linked, weekday, month, day, number in CARD.findall(page):
        if slug not in SLUGS or month not in MONTHS or linked != number:
            continue
        year = taken.year - (MONTHS[month] > taken.month)
        try:
            date = datetime.date(year, MONTHS[month], int(day))
        except ValueError:
            continue
        if date.strftime("%A") == weekday and date <= taken:
            out.append((SLUGS[slug], int(number), date))
    return out


def paper_dates(cache=CACHE):
    """{(series, number): print date} from every cached capture.

    A number two captures date differently is dropped: the listing is the
    fact, and a fact that contradicts itself proves nothing."""
    seen = {}
    for path in sorted(cache.glob("*.html")):
        page = gunzip(path.read_bytes()).decode("utf-8", errors="replace")
        for series, number, date in cards(path.stem, page):
            seen.setdefault((series, number), set()).add(date)
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true", help="what is cached, then exit")
    args = ap.parse_args(argv)
    CACHE.mkdir(parents=True, exist_ok=True)
    if not args.status:
        have = {p.stem for p in CACHE.glob("*.html")}
        try:
            todo = wanted(captures(), have)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"ERROR: fetch_times_listing: the Wayback index did not answer: {e}",
                  file=sys.stderr)
            return 1
        fetched = 0
        for ts, url in todo:
            try:
                page = get(CAPTURE.format(ts=ts, url=url))
            except (urllib.error.URLError, TimeoutError) as e:
                # Wayback answers a fast client with 429 and then refuses
                # connections for minutes; what is cached stays, and the next
                # run resumes from it.
                print(f"  {ts}: {e}; stopping, {len(todo) - fetched} capture(s) left for the next run")
                break
            (CACHE / f"{ts}.html").write_bytes(page)
            fetched += 1
            time.sleep(PAUSE)
        print(f"fetched {fetched} of {len(todo)} capture(s)")
    dates = paper_dates()
    for series in sorted(set(SLUGS.values())):
        got = sorted((n, d) for (s, n), d in dates.items() if s == series)
        if got:
            print(f"  {series}: {len(got)} number(s), {got[0][0]} ({got[0][1]}) "
                  f"to {got[-1][0]} ({got[-1][1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
