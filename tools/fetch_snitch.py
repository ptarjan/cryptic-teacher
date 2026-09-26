#!/usr/bin/env python3
"""Fetch the SNITCH's ratings of The Times and Sunday Times cryptics into
tools/data/snitch.json, keyed by our puzzle id.

    python3 tools/fetch_snitch.py            # fetch and merge
    python3 tools/fetch_snitch.py --status   # what the file holds

The SNITCH (times.xwdsnitch.link) rates each Times cryptic by its NITCH: about
a hundred reference solvers' times on the puzzle, each divided by that solver's
own six-month average, so 100 is a normal day and 150 took half as long again.
Its archive page, /crosswords/all, is one table of every week since September
2015: a row per week, then Monday to Sunday, each day a puzzle-number link and
the NITCH beside it. Monday to Saturday are the Times daily (Saturday is the
prize, rated unofficially), Sunday is the Sunday Times. So one request is the
whole history and there is nothing to crawl; the homepage, which lists the last
year in the same table, is the fallback when the archive fails.

The site refuses the default urllib User-Agent and answers a browser's.

A NITCH below MIN_NITCH is a placeholder rather than a rating: the table writes
0 for a weekend puzzle nobody timed, and a few cells carry a stray digit. A
number that does not follow on from its neighbours in the same series is not
that series' puzzle and is dropped too: 27015 appears once as 230365, and the
Sunday column carries the odd Christmas special numbered by its year. Tonight's rating replaces an old
one, because a NITCH settles over the day the puzzle is published as reference
solvers finish.
"""
import argparse
import datetime
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "data" / "snitch.json"
SITE = "https://times.xwdsnitch.link"
PAGES = (SITE + "/crosswords/all", SITE + "/")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
#: Seconds between requests to the site.
PAUSE = 5
MIN_NITCH = 20
#: Our series for each day column, Monday first.
DAY_SERIES = ["times"] * 6 + ["sundaytimes"]
#: How far a number may stray from the one its neighbour predicts. The Times
#: skips a number for a day it does not print (Christmas, strikes).
SLACK = 3

ROW = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
LINK = re.compile(r'<a href="/crosswords/(\d+)">\s*(\d+)\s*</a>')


def parse(html):
    """{puzzle id: {"nitch", "date", "snitch"}} from a page's week table."""
    out = {}
    body = html[html.find("<tbody"):]
    for row in ROW.findall(body):
        cells = CELL.findall(row)
        # Week NITCH, week-beginning date, then (link, NITCH) for each day.
        if len(cells) != 2 + 2 * len(DAY_SERIES):
            continue
        try:
            monday = datetime.date.fromisoformat(cells[1].strip())
        except ValueError:
            continue
        for day, series in enumerate(DAY_SERIES):
            link = LINK.search(cells[2 + 2 * day])
            nitch = cells[3 + 2 * day].strip()
            if not link or not nitch.isdigit() or int(nitch) < MIN_NITCH:
                continue
            out[f"{series}-{int(link.group(2))}"] = {
                "nitch": int(nitch),
                "date": (monday + datetime.timedelta(days=day)).isoformat(),
                "snitch": int(link.group(1)),
            }
    return {k: out[k] for k in in_sequence(out)}


def issues_between(series, a, b):
    """How many puzzles of `series` are printed after date a, up to date b."""
    days = (b - a).days
    if series == "sundaytimes":
        return days // 7
    return sum(1 for i in range(1, days + 1) if (a + datetime.timedelta(days=i)).weekday() < 6)


def in_sequence(ratings):
    """The ids whose number follows on from a date-neighbour's in its series."""
    keep = []
    by = {}
    for pid, v in ratings.items():
        series, _, number = pid.rpartition("-")
        by.setdefault(series, []).append((datetime.date.fromisoformat(v["date"]), int(number), pid))
    for series, rows in by.items():
        rows.sort()
        for i, (date, number, pid) in enumerate(rows):
            for j in (i - 1, i + 1):
                if 0 <= j < len(rows):
                    d2, n2, _ = rows[j]
                    step = issues_between(series, min(date, d2), max(date, d2))
                    if abs(abs(number - n2) - step) <= SLACK and (number > n2) == (date > d2):
                        keep.append(pid)
                        break
    return keep


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8")


def load():
    return json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}


def save(data):
    """One puzzle per line, so a night's diff is the puzzles that changed."""
    def key(pid):
        series, _, number = pid.rpartition("-")
        return series, int(number)
    lines = [f"{json.dumps(pid)}: {json.dumps(data[pid], sort_keys=True)}"
             for pid in sorted(data, key=key)]
    OUT.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")


def status(data):
    for series in sorted(set(DAY_SERIES)):
        rows = [v for k, v in data.items() if k.rpartition("-")[0] == series]
        if rows:
            dates = sorted(v["date"] for v in rows)
            print(f"{series:<12} {len(rows):>5} rated, {dates[0]} to {dates[-1]}")
        else:
            print(f"{series:<12}     0 rated")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    data = load()
    if args.status:
        status(data)
        return 0
    got, errors = {}, []
    for i, url in enumerate(PAGES):
        if i:
            time.sleep(PAUSE)
        try:
            got = parse(fetch(url))
        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as err:
            errors.append(f"{url}: {err}")
            continue
        if got:
            break
        errors.append(f"{url}: no ratings in the page (has the table changed?)")
    if not got:
        print("SNITCH fetch failed: " + "; ".join(errors), file=sys.stderr)
        return 1
    changed = sum(1 for k, v in got.items() if data.get(k) != v)
    data.update(got)
    save(data)
    print(f"SNITCH: {len(got)} ratings read, {changed} new or changed, "
          f"{len(data)} held")
    status(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
