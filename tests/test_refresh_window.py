#!/usr/bin/env python3
# Does refresh_unsolved ever stop asking for an answer that is never coming?
#
# refresh_unsolved skips puzzles whose source will never publish an answer
# (old Guardian prize puzzles, Cyclops puzzles): still_worth_refreshing in
# tools/fetch_puzzle.py drops a puzzle once it is past REFRESH_WINDOW_DAYS
# since its own date — or since source.acquiredOn, when it has no date —
# for good rather than on any retry schedule.
#
#     python3 tests/test_refresh_window.py
import copy
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime as dt, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
os.chdir(REPO)
import fetch_observer as obs
import fetch_puzzle as fetcher
import series

fails = 0


def same(what, got, want):
    global fails
    if got == want:
        print(f"  ok: {what}")
    else:
        print(f"  FAIL: {what}\n    want {want}\n    got  {got}")
        fails += 1


def git_status():
    return subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                          cwd=REPO).stdout


tree_before = git_status()

NOW = dt(2026, 9, 24, tzinfo=timezone.utc)


def at(days_ago):
    return (NOW - timedelta(days=days_ago)).date().isoformat()


def worth(puzzle):
    return fetcher.still_worth_refreshing(puzzle, now=NOW)


print("a puzzle within its source's publication window is still refreshed")
# A Saturday prize puzzle 10 days old: still well inside the ~2-week window
# the Guardian actually publishes prize solutions in. Keep refreshing it.
same("10-day-old prize puzzle", worth({"date": at(10)}), True)

print("a puzzle no source will ever answer drops out of the nightly queue")
# cryptic-21900: dated 2000-05-18, over 9,600 days ago. Far past the window.
same("9,626-day-old cryptic-21900", worth({"date": at(9626)}), False)

print("the cutoff is exact")
same("90 days is still in", worth({"date": at(90)}), True)
same("91 days is out", worth({"date": at(91)}), False)

print("an undated puzzle falls back to when this repo acquired it")
# An un-backfilled Cyclops carries no `date` at all. Freshly acquired, it has
# no reason to be excluded yet, so it falls back to source.acquiredOn.
same("acquired 6 days ago", worth({"source": {"acquiredOn": "2026-09-18"}}), True)
# Acquired long ago and still dateless: the fallback ages out the same way a
# real date would.
same("acquired years ago", worth({"source": {"acquiredOn": "2020-01-01"}}), False)

print("a puzzle with no date and no source is never refreshed")
# Nothing anchors this puzzle in time, so nothing could ever make it "too old"
# — excluded outright rather than kept forever by default.
same("no anchor at all", worth({}), False)

# A file stores no `series`: refresh_unsolved holds the raw file,
# so it must read the series off the id, not crash with KeyError.
today = datetime.date.today().isoformat()
raw = {"id": "cryptic-99999", "number": 99999, "date": today,
       "entries": [{"solution": None}]}
asked = []
with mock.patch.object(fetcher, "puzzle_files", lambda *series: ["x"]), \
        mock.patch.object(fetcher, "read_puzzle_file", lambda path: raw), \
        mock.patch.object(fetcher, "fetch_number",
                          lambda num, series, **kw: (asked.append((num, series)) or (raw, None))), \
        mock.patch.object(fetcher, "reindex", lambda: None), \
        mock.patch.object(fetcher.time, "sleep", lambda s: None):
    fetcher.refresh_unsolved()
print("a file with no stored series is still refreshed")
same("series read from the id", f"ASKED {asked}", "ASKED [(99999, 'cryptic')]")

# A re-fetch builds the puzzle fresh, naming its series and name, and merges
# the held annotations onto it: the write stores neither. Nor does the write
# of a fresh puzzle with no annotation at all.
src = fetcher.resolve_puzzle("cryptic-30136")
old = fetcher.read_puzzle_file(src)
fresh = copy.deepcopy(old)
for e in fresh["entries"]:
    e.pop("annotation", None)
fresh.update(series="cryptic", name=series.display_name(old))
fetcher.merge_annotations(fresh, old)
with tempfile.TemporaryDirectory() as d:
    path = Path(d) / src.name
    fetcher.write_puzzle_file(path, fresh)
    back = json.loads(path.read_text())
    bare = copy.deepcopy(fresh)
    for e in bare["entries"]:
        e.pop("annotation", None)
    path.unlink()
    fetcher.write_puzzle_file(path, bare)
    plain = json.loads(path.read_text())
held = sum(1 for e in old["entries"] if e.get("annotation"))
kept = sum(1 for e in back["entries"] if e.get("annotation"))
print("a re-fetch is written in the format, its annotations kept; so is a fresh puzzle")
same("refetch written", ("series" in back, "name" in back, kept == held > 0), (False, False, True))
same("fresh puzzle written", ("series" in plain, "name" in plain), (False, False))

# A reindex is a whole-corpus pass. A still-withheld puzzle whose re-fetch
# writes back the same bytes moves nothing in the index, so the refresh must
# not reindex for it, nor let fetch_number reindex per puzzle; a re-fetch that
# changes the file reindexes exactly once, after the lot.
d = Path(tempfile.mkdtemp())
try:
    raws = {n: {"id": f"cryptic-{n}", "number": n, "date": today,
                "entries": [{"solution": None}]} for n in (99998, 99999)}
    for n in raws:
        (d / f"cryptic-{n}.json").write_text("held")
    reindexed, flags = [], []

    def refetch(changes):
        def fetch_number(num, series, reindexed=True):
            flags.append(reindexed)
            if num in changes:
                (d / f"{series}-{num}.json").write_text("new answers")
            else:
                (d / f"{series}-{num}.json").write_text("held")  # same bytes rewritten
            return raws[num], False
        return fetch_number

    with mock.patch.object(fetcher, "puzzle_files", lambda *series: sorted(raws)), \
            mock.patch.object(fetcher, "read_puzzle_file", lambda path: raws[path]), \
            mock.patch.object(fetcher, "puzzle_path", lambda series, num: d / f"{series}-{num}.json"), \
            mock.patch.object(fetcher.time, "sleep", lambda s: None), \
            mock.patch.object(fetcher, "reindex", lambda: reindexed.append(1)):
        with mock.patch.object(fetcher, "fetch_number", refetch(set())):
            fetcher.refresh_unsolved()
        unchanged = f"UNCHANGED {len(reindexed)} {flags}"
        reindexed.clear()
        flags.clear()
        with mock.patch.object(fetcher, "fetch_number", refetch({99998})):
            fetcher.refresh_unsolved()
        changed = f"CHANGED {len(reindexed)} {flags}"

    obs_reindexed = []
    with mock.patch.object(obs, "puzzle_files", lambda *series: ["x"]), \
            mock.patch.object(obs, "read_puzzle_view",
                              lambda path: {"series": "everyman", "number": 4173, "date": today,
                                            "entries": [{"solution": None}]}), \
            mock.patch.object(obs, "article_uuid", lambda num: "u"), \
            mock.patch.object(obs, "puzzle_manifest", lambda uuid: {}), \
            mock.patch.object(obs, "puzzle_data", lambda m: {"copy": {"settings": {"solution": None}}}), \
            mock.patch.object(obs.time, "sleep", lambda s: None), \
            mock.patch.object(obs, "reindex", lambda: obs_reindexed.append(1)):
        obs.refresh_unsolved()
finally:
    shutil.rmtree(d, ignore_errors=True)

print("a refresh reindexes once, and only when a re-fetch changed a file")
same("same bytes back: no reindex, none per puzzle", unchanged, "UNCHANGED 0 [False, False]")
same("one file changed: one reindex after the lot", changed, "CHANGED 1 [False, False]")
same("an Everyman still in its window: no reindex", f"OBSERVER_WITHHELD {len(obs_reindexed)}",
     "OBSERVER_WITHHELD 0")

print("the working tree is untouched")
same("git status unchanged", git_status(), tree_before)

if fails:
    print(f"refresh_window: {fails} check(s) failed")
    sys.exit(1)
print("refresh_window: all checks passed")
