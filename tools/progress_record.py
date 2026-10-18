#!/usr/bin/env python3
"""Write tools/data/progress.json, the history /progress/ draws (see
tools/progress.py for the phases and the backfill's dating).

    python3 tools/progress_record.py record     # today's row, nightly (the page build
                                                # overlays live filed/solved/hinted)
    python3 tools/progress_record.py backfill   # every day before the first one held
    python3 tools/progress_record.py backfill-queue   # downloaded/queued on days without them,
                                                      # dated off the media disk (edition_backlog.dated)
"""
import collections
import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import annotation
import coverage
import fetch_puzzle
import parallel
import progress
import puzzle_paths
import series as series_meta


#: puzzle_row() per file, kept between runs: {"code": code_digest(), "rows":
#: {path: [size, mtime_ns, row]}}, so a night re-reads only the files that moved.
ROWS_CACHE = Path.home() / ".cache" / "cryptic-progress-rows.json"

#: The modules a row is derived by: a change to any of them re-reads every file.
ROW_CODE = ("progress_record", "fetch_puzzle", "annotation", "wordplay", "groups",
            "series", "puzzle_schema")


def code_digest():
    h = hashlib.sha256()
    here = Path(__file__).resolve().parent
    for name in ROW_CODE:
        h.update((here / f"{name}.py").read_bytes())
    return h.hexdigest()


def puzzle_row(path):
    """(id, series, acquiredOn, solved on or None, hinted) for one puzzle file."""
    p = fetch_puzzle.read_puzzle_file(path)
    # The view drops an annotation whose tree does not give its answer and
    # touches nothing else these read, so a raw file that is unannotated is
    # unannotated as viewed too: only a fully annotated one pays for the view
    # (viewing all ~55k files, serially under nice at load 30, ran past 900s
    # on 2026-10-15). A file with no "number" has no view series: view it
    # anyway, so it fails as it always did.
    if fetch_puzzle.puzzle_is_annotated(p) or "number" not in p:
        p = annotation.view_puzzle(p)
        series = p["series"]
    else:
        series = series_meta.parse_id(p["id"])[0]
    got = p["source"]["acquiredOn"]
    sol = p.get("solutions") or {}
    # The index's own tests (hasSolutions, annotated), so a night's row and the
    # page build's overlay (progress.index_counts) count the same puzzles.
    solved = max(got, sol.get("date") or got) if fetch_puzzle.puzzle_is_solved(p) else None
    return p["id"], series, got, solved, fetch_puzzle.puzzle_is_annotated(p)


def cached_rows(paths, cache=None):
    """puzzle_row() for each of paths that exists, reading again only the
    files whose (size, mtime_ns) moved, or all of them when code_digest()
    did; rewrites the cache with exactly these paths."""
    cache = cache or ROWS_CACHE
    code = code_digest()
    try:
        held = json.loads(cache.read_text())
        held = held["rows"] if held.get("code") == code else {}
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        held = {}
    stamps, out, todo = {}, {}, []
    for path in paths:
        key = str(path)
        try:
            st = os.stat(path)
        except FileNotFoundError:
            continue
        stamps[key] = [st.st_size, st.st_mtime_ns]
        hit = held.get(key)
        if isinstance(hit, list) and hit[:2] == stamps[key]:
            out[key] = tuple(hit[2])
        else:
            todo.append(path)
    for path, row in zip(todo, parallel.pmap(puzzle_row, todo)):
        out[str(path)] = tuple(row)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_name(f"{cache.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"code": code, "rows": {
            k: stamps[k] + [list(out[k])] for k in stamps}}))
        os.replace(tmp, cache)
    except OSError:
        pass
    return [out[k] for k in stamps]


def corpus():
    """puzzle_row() for every listed puzzle file."""
    return [r for r in cached_rows(puzzle_paths.puzzle_files())
            if not series_meta.unlisted(r[1])]


def ledger_on(day):
    try:
        return json.loads((coverage.STATE / f"{day}.json").read_text())
    except (OSError, ValueError):
        return None


def backlog():
    """edition_backlog.counts()'s per series, or None with no media disk (manifests) here."""
    import edition_backlog
    import media_manifest
    # The SSD manifests stand for the media disk (nothing scheduled stats it):
    # a host that never held its editions has no gale-editions manifest.
    if not media_manifest.built(media_manifest.GALE_EDITIONS):
        return None
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
        # "Annotate <id>", or a batch's "Annotate N puzzles: <id> <id> ..."
        if len(words) == 2 and words[0] == "Annotate":
            first.setdefault(words[1], day)
        elif len(words) > 3 and words[0] == "Annotate" and words[2] == "puzzles:":
            for pid in words[3:]:
                first.setdefault(pid, day)
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


def fill_queue(days, hist):
    """days with downloaded/queued filled from hist (edition_backlog.history())
    on a night that never counted them, and over a recorded downloaded of 0
    while scans had landed; any other recorded count is kept (a series a
    counted night left out had none). Returns the days it filled."""
    filled = set()
    for day, counts in hist.items():
        row = days.get(day)
        if row is None:
            continue
        counted = any(c[progress.QUEUED] is not None for c in row.values())
        for s, (got, queued) in counts.items():
            if not got or (counted and (s not in row or row[s][progress.DOWNLOADED] is None)):
                continue
            c = row.setdefault(s, [None, None, 0, 0, 0, None, None])
            if c[progress.DOWNLOADED] is None or c[progress.DOWNLOADED] == 0:
                c[progress.DOWNLOADED:] = [got, queued]
                filled.add(day)
    return sorted(filled)


def backfill_queue():
    """fill_queue() over the history from the media disk's scans; [] with no disk."""
    import downloads
    if not downloads.ROOT.is_dir():
        return []
    import edition_backlog
    days = progress.load()
    filled = fill_queue(days, edition_backlog.history(edition_backlog.dated(), list(days)))
    progress.save(days)
    return filled


def main(argv):
    if argv[1:] == ["record"]:
        print(json.dumps(progress.totals(record())))
    elif argv[1:] == ["backfill"]:
        print(f"{backfill()} day(s) backfilled into {progress.HISTORY.relative_to(progress.ROOT)}")
        print(f"downloaded/queued filled on {len(backfill_queue())} day(s)")
    elif argv[1:] == ["backfill-queue"]:
        filled = backfill_queue()
        print(f"downloaded/queued filled on {len(filled)} day(s): {filled[:1]}..{filled[-1:]}")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
