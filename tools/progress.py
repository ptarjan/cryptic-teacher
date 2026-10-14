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
  downloaded  scans on the media disk a read queue reads: archive.org and
            Gale editions (file_archive_org_puzzles' papers), Gale Listener
            pages, Trove articles
  queued    of those, the ones never read (no ledger row holding a read)

A file counts as hinted only when it is also solved, so hinted <= solved <=
filed. nested() puts every series in one chain, known >= downloaded >= filed
>= solved >= hinted, where downloaded is filed plus queued: the scans on disk
include editions already read and filed, so the raw downloaded is not a layer
above filed. The funnel and the by-series bars draw that chain.

downloaded and queued count puzzles: one per newspaper print date (each
edition prints one cryptic; a date on disk from both Gale and archive.org, or
twice in one item, is one puzzle, read once any copy is) or Listener page,
and a Trove article times the share of read
articles that filed a puzzle (tools/edition_backlog.py). The queue's daily
inflow is downloaded's gain, its outflow that gain less queued's. Nights
before progress_record.py first counted them are backfilled
(`progress_record.py backfill-queue`): a scan dated by its file's mtime on
the media disk, its read by its ledger row's first readAt; null before any
scan landed.

known and acquired are null on a day no ledger was saved, and for a series the
ledger does not count. The site is built from a one-commit checkout, so the
history has to be committed: `progress_record.py record` runs nightly
(tools/daily_update.sh unit_ratings) and reads the ledger tools/coverage.sh
saved that morning.

Filed, solved and hinted are live, though: every site deploy builds the index
from the puzzle files and with_today() lays index_counts() of it over today's
row, so the page moves with each push. Known/acquired and downloaded/queued
need the ledger and the media disk, which the deploy has not got, so they are
the newest recorded night's. Recording more often would only reach the page as
a commit an hour; it is left nightly.

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
PHASES = ("known", "acquired", "filed", "solved", "hinted", "downloaded", "queued")
KNOWN, ACQUIRED, FILED, SOLVED, HINTED, DOWNLOADED, QUEUED = range(len(PHASES))


def load(path=None):
    """{day: {series: [count per PHASES]}}, days in order; a row saved
    before a phase existed reads None for it."""
    path = path or HISTORY
    if not path.exists():
        return {}
    days = json.loads(path.read_text(encoding="utf-8"))
    return {d: {s: c + [None] * (len(PHASES) - len(c)) for s, c in days[d].items()} for d in sorted(days)}


def _trimmed(c):
    while c and c[-1] is None:
        c = c[:-1]
    return c


def save(days, path=None):
    """One day a line, so a night's row is a one-line diff; trailing nulls
    are left off (load() puts them back)."""
    path = path or HISTORY
    lines = [f" {json.dumps(d)}: "
             f"{json.dumps({s: _trimmed(c) for s, c in days[d].items()}, sort_keys=True, separators=(',', ':'))}"
             for d in sorted(days)]
    path.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")


def file_counts(rows):
    """{series: [filed, solved, hinted]} from (series, solved, hinted) rows."""
    out = collections.defaultdict(lambda: [0, 0, 0])
    for series, solved, hinted in rows:
        c = out[series]
        c[0] += 1
        c[1] += bool(solved)
        c[2] += bool(solved and hinted)
    return dict(out)


def index_counts(puzzles):
    """file_counts() of index rows (puzzles/index.json's "puzzles"), whose
    hasSolutions and annotated are the same tests progress_record.puzzle_row()
    applies to the files (fetch_puzzle.puzzle_is_solved / puzzle_is_annotated)."""
    return file_counts((p["series"], p.get("hasSolutions"), p.get("annotated")) for p in puzzles)


def day_row(files, ledger, backlog=None):
    """One day's {series: [count per PHASES]}: files is file_counts(), ledger
    is a saved coverage ledger or None, backlog edition_backlog.counts()'s
    {series: [downloaded, queued]} or None."""
    led = (ledger or {}).get("series", {})
    backlog = backlog or {}
    return {s: [led[s]["exist"] if s in led else None,
                led[s]["filed"] if s in led else None,
                *files.get(s, [0, 0, 0]),
                *backlog.get(s, [None, None])]
            for s in sorted(files.keys() | led.keys() | backlog.keys())}


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
    index being built), and known/acquired and downloaded/queued each carried
    from the newest day that has them, so the page shows the build's own corpus."""
    days = dict(days)
    carried, queue = {}, {}
    for d in sorted(days):
        if d < today:
            for s, c in days[d].items():
                if c[KNOWN] is not None:
                    carried[s] = c[:2]
                if c[QUEUED] is not None:
                    queue[s] = c[DOWNLOADED:]
    row = {s: list(c) for s, c in days.get(today, {}).items()}
    for s in files.keys() | carried.keys() | queue.keys() | row.keys():
        old = row.get(s, [None] * len(PHASES))
        head = old[:2] if old[KNOWN] is not None else carried.get(s, [None, None])
        tail = old[DOWNLOADED:] if old[QUEUED] is not None else queue.get(s, [None, None])
        row[s] = head + list(files.get(s, [0, 0, 0])) + tail
    days[today] = dict(sorted(row.items()))
    return dict(sorted(days.items()))


FUNNEL = ("known", "downloaded", "filed", "solved", "hinted")


def nested(c):
    """[known, downloaded, filed, solved, hinted] for one series' row c, each
    at most the one before. Downloaded is filed plus the unread scans, the
    unread capped at what is known and not yet filed (a scan may hold a puzzle
    already filed from another source). A series the ledger does not count has
    no known, so its whole is its downloaded; known is never below it."""
    known, _, filed, solved, hinted, _, queued = c
    solved = min(solved, filed)
    hinted = min(hinted, solved)
    unread = queued or 0
    if known is not None:
        unread = min(unread, max(known - filed, 0))
    downloaded = filed + unread
    return [max(known or 0, downloaded), downloaded, filed, solved, hinted]


def nested_totals(row):
    """nested() summed over a day's series."""
    return [sum(col) for col in zip(*(nested(c) for c in row.values()))]


def funnel_series(days, stage):
    """[(day, nested_totals()[stage])] over the days that counted the stage:
    known from the first ledger, downloaded from the first night the queue was
    counted (before it, downloaded would read as just filed and its pace would
    jump the night counting began), filed, solved and hinted every day. The
    /progress/ bars and table both read this, so their numbers are one source."""
    need = {0: KNOWN, 1: QUEUED}.get(stage)
    return [(d, nested_totals(row)[stage]) for d, row in days.items()
            if need is None or any(c[need] is not None for c in row.values())]


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
