#!/usr/bin/env python3
"""How far the site has got toward every puzzle: per series and per day, how
many are known to exist, acquired, filed, solved and hinted. /progress/
(tools/build_seo_pages.py) draws it.

tools/progress_record.py writes it; this reads it, and imports nothing that
reads the corpus, since the page build imports it.

The phases, each a count of one series' puzzles on one day:

  known     the coverage ledger's `exist` (tools/coverage.py)
  acquired  the ledger's `filed`, in the ledger's own deduplicated units, so
            known - acquired is exactly what the ledger says is missing
  filed     puzzle files (puzzle_paths.puzzle_files)
  solved    files with every answer (the index's hasSolutions)
  hinted    files with every clue annotated (the index's annotated)

known and acquired are null on a day no ledger was saved, and for a series the
ledger does not count. The site is built from a one-commit checkout, so the
history has to be committed: `progress_record.py record` runs nightly
(tools/daily_update.sh unit_ratings) and reads the ledger tools/coverage.sh
saved that morning.

Its `backfill` dates each file by its source.acquiredOn, its answers by the
later of that and solutions.date, and its hints by its first "Annotate <id>"
commit (else acquiredOn), and takes known/acquired from the saved ledgers. A
day already held is kept as recorded.
"""
import collections
import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "tools" / "data" / "progress.json"
PHASES = ("known", "acquired", "filed", "solved", "hinted")
KNOWN, ACQUIRED, FILED, SOLVED, HINTED = range(len(PHASES))


def load(path=None):
    """{day: {series: [count per PHASES]}}, days in order."""
    path = path or HISTORY
    if not path.exists():
        return {}
    return dict(sorted(json.loads(path.read_text(encoding="utf-8")).items()))


def save(days, path=None):
    """One day a line, so a night's row is a one-line diff."""
    path = path or HISTORY
    lines = [f" {json.dumps(d)}: {json.dumps(days[d], sort_keys=True, separators=(',', ':'))}"
             for d in sorted(days)]
    path.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")


def file_counts(rows):
    """{series: [filed, solved, hinted]} from (series, solved, hinted) rows."""
    out = collections.defaultdict(lambda: [0, 0, 0])
    for series, solved, hinted in rows:
        c = out[series]
        c[0] += 1
        c[1] += bool(solved)
        c[2] += bool(hinted)
    return dict(out)


def day_row(files, ledger):
    """One day's {series: [count per PHASES]}: files is file_counts(), ledger
    is a saved coverage ledger or None."""
    led = (ledger or {}).get("series", {})
    return {s: [led[s]["exist"] if s in led else None,
                led[s]["filed"] if s in led else None,
                *files.get(s, [0, 0, 0])]
            for s in sorted(files.keys() | led.keys())}


# ------------------------------------------------------------ what the page reads

def totals(row):
    """[count per PHASES] summed over a day's series; known and acquired are
    None when no series has them."""
    out = []
    for i in range(len(PHASES)):
        vals = [c[i] for c in row.values() if c[i] is not None]
        out.append(sum(vals) if vals else None)
    return out


def with_today(days, files, today):
    """days with today's file phases replaced by files (file_counts() of the
    index being built), and known/acquired carried from the newest day that
    has them, so the page shows the build's own corpus."""
    days = dict(days)
    carried = {}
    for d in sorted(days):
        if d < today:
            for s, c in days[d].items():
                if c[KNOWN] is not None:
                    carried[s] = c[:2]
    row = {s: list(c) for s, c in days.get(today, {}).items()}
    for s in files.keys() | carried.keys() | row.keys():
        old = row.get(s, carried.get(s, [None, None]) + [0, 0, 0])
        if old[KNOWN] is None and s in carried:
            old = carried[s] + old[2:]
        row[s] = old[:2] + list(files.get(s, [0, 0, 0]))
    days[today] = dict(sorted(row.items()))
    return dict(sorted(days.items()))


def series_of(days, phase):
    """[(day, total)] for one phase over the days that have it."""
    return [(d, t) for d, row in days.items() if (t := totals(row)[phase]) is not None]


def daily(points):
    """[(day, gain since the previous point)] from series_of(); a gap of
    several days counts on the day it closes."""
    return [(d, n - p) for (_, p), (d, n) in zip(points, points[1:])]


def rate(points, window):
    """Mean gain a day over the last `window` days of series_of(), or None
    with fewer than two points in it."""
    if len(points) < 2:
        return None
    end = datetime.date.fromisoformat(points[-1][0])
    start = end - datetime.timedelta(days=window)
    inside = [(d, n) for d, n in points if datetime.date.fromisoformat(d) >= start]
    if len(inside) < 2:
        inside = points[-2:]
    span = (datetime.date.fromisoformat(inside[-1][0])
            - datetime.date.fromisoformat(inside[0][0])).days
    return (inside[-1][1] - inside[0][1]) / span if span else None
