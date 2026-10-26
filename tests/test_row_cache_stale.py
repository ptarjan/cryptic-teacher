#!/usr/bin/env python3
"""row_cache.cached_map(stale_ok=True): a code change does not throw away the
rows of unchanged files, and a deadline mid-build keeps what was made.

2026-10-16: puzzle_integrity's validator moves most days, every move made all
55k rows missing, and a build that needs ~30 minutes never finished inside a
unit's deadline ("0 were stored" at each start). Here a scratch corpus of
four files is mapped under code A; under code B with a deadline already past,
the map returns every row (A's rows for unchanged files), re-makes none, and
marks the unit as having backlog; the next run with time re-makes them; a
new file is made before any stale row is refreshed.

    python3 tests/test_row_cache_stale.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import budget
import code_reach
import puzzle_paths
import row_cache

fails = []


def check(what, got, want):
    if got != want:
        fails.append(f"{what}: got {got!r}, want {want!r}")


tmp = Path(tempfile.mkdtemp())
puzzle_paths.PUZZLE_DIR = tmp / "puzzles"
row_cache.STORE = tmp / "rows.sqlite"
row_cache._blobs = lambda paths, listed=None: {p: p.read_text() for p in paths}
row_cache._blob_sha = lambda p: p.read_text()
more = tmp / "more"
os.environ["UNIT_MORE"] = str(more)
files = []


def add(name):
    f = puzzle_paths.PUZZLE_DIR / "2020" / f"{name}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(name)
    files.append(f)


for n in ["a-1", "b-2", "c-3", "d-4"]:
    add(n)
made, version = [], ["A"]


def parse(path):
    made.append(path.stem)
    return (path.stem, version[0])


def run(code, deadline=None):
    made.clear()
    version[0] = code
    code_reach.key = lambda *a, **k: code
    if deadline is None:
        os.environ.pop("CT_DEADLINE", None)
    else:
        os.environ["CT_DEADLINE"] = deadline
    return row_cache.cached_map("row_cache", parse, files, stale_ok=True)


check("code A builds every row", run("A"), [(f.stem, "A") for f in files])
check("code B, deadline past: complete answer from A's rows",
      run("B", "0"), [(f.stem, "A") for f in files])
check("and re-made none (all four had an older row)", made, [])
check("and the unit is marked as having backlog", more.exists(), True)
add("e-5")
more.unlink()
check("a new file is made before stale ones, then the deadline ends the run",
      (run("B", "0"), made), ([(f.stem, "A") for f in files[:4]] + [("e-5", "B")], ["e-5"]))
check("backlog marked again", more.exists(), True)
check("a run with time refreshes the four stale rows only (e-5 is stored)",
      (run("B"), sorted(made)), ([(f.stem, "B") for f in files], ["a-1", "b-2", "c-3", "d-4"]))
check("then nothing is made", (run("B"), made), ([(f.stem, "B") for f in files], []))
files[0].write_text("a-1 edited")
check("an edited file is made afresh even past the deadline (no older row of its content)",
      (run("C", "0"), made), ([("a-1", "C")] + [(f.stem, "B") for f in files[1:]], ["a-1"]))
os.environ.pop("CT_DEADLINE", None)
# A stale row's findings are judged again by the current forgiveness tables.
def _stale_forgiven():
    import puzzle_integrity as pi
    key = next(iter(pi.PUBLISHED_WRONG))
    flag = ("LENGTH", key[0], key[1])
    real = row_cache.cached_map
    old_min = pi.ROW_CACHE_MIN
    row_cache.cached_map = lambda *a, **k: [([flag, ("LENGTH", "x-1", "other")], ("row",), None)]
    pi.ROW_CACHE_MIN = 1
    try:
        got = pi._judge(["p"])
    finally:
        row_cache.cached_map, pi.ROW_CACHE_MIN = real, old_min
    return got


check("stale row: finding the current table forgives is not reported",
      [f for f in _stale_forgiven()[0][0]], [("LENGTH", "x-1", "other")])
if fails:
    print("\n".join(fails))
    sys.exit(1)
print("ok")
