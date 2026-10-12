#!/usr/bin/env python3
"""Write tools/data/progress.json, the history /progress/ draws (see
tools/progress.py for the phases and the backfill's dating).

    python3 tools/progress_record.py record     # today's row, nightly (the page build
                                                # overlays live filed/solved/hinted)
    python3 tools/progress_record.py backfill   # every day before the first one held
"""
import collections
import datetime
import json
import subprocess
import sys

import coverage
import fetch_puzzle
import parallel
import progress
import puzzle_paths
import series as series_meta


def puzzle_row(path):
    """(series, acquiredOn, solved on or None, hinted) for one puzzle file."""
    p = fetch_puzzle.read_puzzle_file(path)
    got = p["source"]["acquiredOn"]
    sol = p.get("solutions") or {}
    # The index's own tests (hasSolutions, annotated), so a night's row and the
    # page build's overlay (progress.index_counts) count the same puzzles.
    solved = max(got, sol.get("date") or got) if fetch_puzzle.puzzle_is_solved(p) else None
    return p["id"], p["series"], got, solved, fetch_puzzle.puzzle_is_annotated(p)


def corpus():
    """puzzle_row() for every listed puzzle file."""
    return [r for r in parallel.pmap(puzzle_row, puzzle_paths.puzzle_files())
            if not series_meta.unlisted(r[1])]


def ledger_on(day):
    try:
        return json.loads((coverage.STATE / f"{day}.json").read_text())
    except (OSError, ValueError):
        return None


def backlog():
    """edition_backlog.counts()'s per series, or None with no media disk here."""
    import downloads
    if not downloads.ROOT.is_dir():
        return None
    import edition_backlog
    return edition_backlog.counts()[0]


def record(today=None):
    today = today or datetime.date.today().isoformat()
    files = progress.file_counts((s, solved, hinted) for _, s, _, solved, hinted in corpus())
    days = progress.load()
    days[today] = progress.day_row(files, ledger_on(today), backlog())
    progress.save(days)
    return days[today]


def annotate_dates():
    """{id: the day of its first "Annotate <id>" commit}."""
    out = subprocess.run(["git", "log", "--reverse", "--date=short", "--format=%ad\t%s"],
                         cwd=progress.ROOT, capture_output=True, text=True, check=True).stdout
    first = {}
    for line in out.splitlines():
        day, _, subject = line.partition("\t")
        words = subject.split()
        if len(words) == 2 and words[0] == "Annotate":
            first.setdefault(words[1], day)
    return first


def backfill_days(rows, annotated, ledgers, until):
    """{day: row} for every day from the first acquiredOn to until, inclusive.
    rows are puzzle_row()s; annotated is annotate_dates(); ledgers maps a day
    to its saved ledger."""
    events = collections.defaultdict(list)  # day -> [(series, phase index)]
    for pid, series, got, solved, hinted in rows:
        events[got].append((series, 0))
        if solved:
            events[solved].append((series, 1))
        if hinted:
            events[max(got, annotated.get(pid, got))].append((series, 2))
    if not events:
        return {}
    day = datetime.date.fromisoformat(min(events))
    end = datetime.date.fromisoformat(until)
    running = collections.defaultdict(lambda: [0, 0, 0])
    out = {}
    while day <= end:
        iso = day.isoformat()
        for series, i in events.get(iso, ()):
            running[series][i] += 1
        out[iso] = progress.day_row({s: list(c) for s, c in running.items()}, ledgers.get(iso))
        day += datetime.timedelta(days=1)
    return out


def backfill():
    days = progress.load()
    rows = corpus()
    until = min(days) if days else datetime.date.today().isoformat()
    until = (datetime.date.fromisoformat(until) - datetime.timedelta(days=1)).isoformat()
    first = min(r[2] for r in rows)
    span = [(datetime.date.fromisoformat(first) + datetime.timedelta(days=i)).isoformat()
            for i in range((datetime.date.fromisoformat(until)
                            - datetime.date.fromisoformat(first)).days + 1)]
    ledgers = {d: led for d in span if (led := ledger_on(d))}
    made = backfill_days(rows, annotate_dates(), ledgers, until)
    progress.save({**made, **days})
    return len(made)


def main(argv):
    if argv[1:] == ["record"]:
        print(json.dumps(progress.totals(record())))
    elif argv[1:] == ["backfill"]:
        print(f"{backfill()} day(s) backfilled into {progress.HISTORY.relative_to(progress.ROOT)}")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
