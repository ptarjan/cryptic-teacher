#!/usr/bin/env python3
# Does row_cache.cached_map() parse again exactly the files whose row could
# have changed, and is every data file a cached row reads in its key?
#
#     python3 tests/test_row_cache.py
#
# A scratch corpus of three files is mapped with a parser that counts what it
# reads. A second map parses nothing; an edited file is parsed again and its
# row changes; a changed deps() value re-parses that row alone; a changed code
# key re-parses every file. Then the definitions index_row(), history_row()
# and clue_row() reach may name only the tools/data files their keys cover
# (blog facts, ninas, lexicon, wordnet): a new data input fails here until it
# is keyed. Never reads ~/.cache or the checkout's store: the store is scratch.
import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["CT_JOBS"] = "1"
os.chdir(Path(__file__).resolve().parent.parent)
sys.path.insert(0, "tools")
import code_reach
import puzzle_paths
import row_cache

fails = []


def check(what, got, want):
    if got != want:
        fails.append(f"{what}: got {got!r}, want {want!r}")


tmp = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, tmp, True)
puzzle_paths.PUZZLE_DIR = tmp / "puzzles"
row_cache.STORE = tmp / "rows.sqlite"
files = []
for i, name in enumerate(["a-1", "b-2", "c-3"]):
    f = puzzle_paths.PUZZLE_DIR / "2020" / "01" / f"{name}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"id": name, "v": i}))
    files.append(f)

parsed, extra = [], {}


def parse(path):
    parsed.append(path.stem)
    return json.loads(path.read_text())


def deps(path, row):
    return extra.get(row["id"])


def run():
    parsed.clear()
    rows = row_cache.cached_map("row_cache", parse, files, deps=deps)
    return [r["v"] for r in rows], sorted(parsed)


check("a cold map parses every file", run(), ([0, 1, 2], ["a-1", "b-2", "c-3"]))
check("a warm map parses none", run(), ([0, 1, 2], []))
files[1].write_text(json.dumps({"id": "b-2", "v": 9}))
check("an edited file alone is parsed, and its row changes", run(), ([0, 9, 2], ["b-2"]))
extra["c-3"] = "new blog facts"
check("a changed deps() value re-parses that row alone", run(), ([0, 9, 2], ["c-3"]))
key = code_reach.key
code_reach.key = lambda *a, **k: "other code"
check("a changed code key re-parses every file", run(), ([0, 9, 2], ["a-1", "b-2", "c-3"]))
code_reach.key = key
check("back on the first code, its rows are still stored", run(), ([0, 9, 2], []))

# Under a unit's deadline (tools/budget.py), a cold map makes a batch, stores
# it and stops cleanly (budget.Stopped, the unit marked "backlog left"); the
# next run reuses that batch and makes the rest. Nothing is killed.
import os as _os
import budget
code_reach.key = lambda *a, **k: "deadline code"
row_cache.BATCH, _os.environ["CT_DEADLINE"] = 2, "0"
more = tmp / "more"
_os.environ["UNIT_MORE"] = str(more)
parsed.clear()
try:
    row_cache.cached_map("row_cache", parse, files, deps=deps)
    stopped = None
except budget.Stopped as e:
    stopped = e.code
check("past the deadline a cold map stops after a batch, rc 0, backlog left",
      (stopped, sorted(parsed), more.exists()), (0, ["a-1", "b-2"], True))
del _os.environ["CT_DEADLINE"]
check("and the next run makes only the rest", run(), ([0, 9, 2], ["c-3"]))
# The batches are paced to the deadline: at 0.5s a row with 0.8s left, the
# first row's pace sizes the next batch to one row, and the map stops after
# two, not after the whole batch (1024 cold views ran ~2 minutes past the
# burn re-plan's deadline, and it was killed).
import time as _time
code_reach.key = lambda *a, **k: "paced code"
row_cache.BATCH, row_cache.FIRST_BATCH = 1024, 1
_os.environ["CT_DEADLINE"] = str(_time.time() + 0.8)
parsed.clear()


def slow(p):
    _time.sleep(0.5)
    return parse(p)


try:
    row_cache.cached_map("row_cache", slow, files, deps=deps)
    stopped = None
except budget.Stopped as e:
    stopped = e.code
check("under a deadline the batches are cut to the time left at the pace measured",
      (stopped, len(parsed)), (0, 2))
check("batch_size: the rows the time left holds, at least one, at most BATCH",
      [row_cache.batch_size(10, 0.5), row_cache.batch_size(-3, 0.5), row_cache.batch_size(1e9, 0.001),
       row_cache.batch_size(5, 0)], [20, 1, 1024, 1024])
del _os.environ["CT_DEADLINE"]
code_reach.key, row_cache.BATCH, row_cache.FIRST_BATCH = key, 1024, 64

# Keys sort by their code, so a map reads its rows in one range scan; a row
# stored under the bare sha1 key of before 2026-10-15 is still reused, and
# written under its new key.
import sqlite3 as _sq
with _sq.connect(row_cache.STORE) as db:
    db.execute("UPDATE rows SET key = substr(key, instr(key, ':') + 1) WHERE key LIKE '%:%'")
check("rows under legacy keys are reused, not parsed", run(), ([0, 9, 2], []))
with _sq.connect(row_cache.STORE) as db:
    prefixed = db.execute("SELECT count(*) FROM rows WHERE key LIKE '%:%'").fetchone()[0]
check("and are written under their new keys", prefixed, 3)
check("which the next map reads by range", run(), ([0, 9, 2], []))

# A caller holding puzzle_integrity.listing() (its own whole-corpus run) hands
# it in, and the map keys its rows off it without listing the corpus again.
import puzzle_integrity
listing = puzzle_integrity.listing
held = listing()
calls = []
puzzle_integrity.listing = lambda: calls.append(1) or listing()
parsed.clear()
got = [r["v"] for r in row_cache.cached_map("row_cache", parse, files, deps=deps, listed=held)]
check("a map handed the listing reads its rows without listing again", (got, sorted(parsed), calls), ([0, 9, 2], [], []))
puzzle_integrity.listing = listing

# The prune (a full scan of a gigabytes store) runs once a day: a row unused
# for PRUNE_DAYS survives a map on a day the prune already ran, and the first
# map of a new day drops it and marks the day.
import sqlite3
import time
today = int(time.time() // 86400)


def stale_rows(mark):
    with sqlite3.connect(row_cache.STORE) as db:
        db.execute("INSERT OR REPLACE INTO rows VALUES('stale', x'', x'', 0)")
        db.execute(f"PRAGMA user_version={mark}")
    run()
    with sqlite3.connect(row_cache.STORE) as db:
        return (db.execute("SELECT count(*) FROM rows WHERE key='stale'").fetchone()[0],
                db.execute("PRAGMA user_version").fetchone()[0])


check("a map on a day already pruned leaves the stale row", stale_rows(today), (1, today))
check("the first map of a day prunes it and marks the day", stale_rows(today - 1), (0, today))

# A row's key names its file as Path.resolve() would, though the names are
# built from each folder resolved once: through a linked folder, a linked
# file, a missing file, a `..`, and a file outside the root.
import os
linked = tmp / "linked"
os.symlink(puzzle_paths.PUZZLE_DIR / "2020", linked)
os.symlink(files[0], files[0].with_name("z-9.json"))
for p in [files[0], linked / "01" / "a-1.json", files[0].with_name("z-9.json"), linked / "01" / "missing-1.json",
          linked / "01" / ".." / "01" / "b-2.json", Path("tools/row_cache.py"), tmp]:
    check(f"real({p})", puzzle_paths.real(p), str(p.resolve()))
    for root in (puzzle_paths.PUZZLE_DIR, tmp / "linked", Path("/")):
        try:
            want = p.resolve().relative_to(root).as_posix()
        except ValueError:
            want = None
        check(f"relative({p}, {root})", puzzle_paths.relative(p, root), want)
check("a file through a linked folder is in the corpus", puzzle_paths.in_corpus(linked / "01" / "a-1.json"), True)
check("a file beside the corpus is not", puzzle_paths.in_corpus(tmp / "rows.sqlite"), False)

# difficulty.puzzle_blog_definitions reads only the puzzle's series' file of
# blog facts, so every id in a file must be of that file's series.
import difficulty
import series as series_meta
import blog_store
strays = [pid for pid, f in blog_store.files().items()
          if series_meta.parse_id(pid)[0] != f.parent.parent.name]
check("sidecars in another series' folder", sorted(strays)[:3], [])

# Every tools/data path the cached functions reach must be in their keys:
# blog facts and ninas (folders) through deps(); every file (books, lexicon,
# wordnet...) is hashed into the key by row_cache.data_files() itself.
KEYED = {("puzzle_tags", "NINAS")}
for module, roots in [("fetch_puzzle", {"index_row", "index_row_deps"}),
                      ("difficulty", {"history_row", "history_row_deps"}),
                      ("difficulty", {"clue_row", "clue_row_deps", "_load_clue_inputs"}),
                      ("difficulty", {"check_row", "check_row_deps", "_load_clue_inputs"})]:
    past, _ = row_cache.reach_past_derived(module, roots)
    for mod, name in code_reach.reach(module, roots):
        if (mod, name) not in past:  # read only through a DERIVED definition, whose output is keyed
            continue
        obj = getattr(__import__(mod), name, None)
        if isinstance(obj, Path) and obj.is_relative_to(Path("tools/data").resolve()) and (mod, name) not in KEYED \
                and obj not in row_cache.data_files(module, roots):
            fails.append(f"{module} {sorted(roots)} reads {mod}.{name} ({obj}), which no row key covers")

LEX = difficulty.LEXICON.name
check("books.json is keyed for fetch_puzzle rows",
      any(p.name == "books.json" for p in row_cache.data_files("fetch_puzzle", {"index_row", "index_row_deps"})), True)
check("lexicon is keyed for clue rows",
      any(p.name == LEX for p in row_cache.data_files("difficulty", {"clue_row", "_load_clue_inputs"})), True)

# blocks.json, which every blog-facts run rewrites, reaches these rows only
# through build_abbreviations.table(): the table they read keys them, not the
# file's bytes, so new clue counts that leave the table alone re-key nothing.
import build_abbreviations
IDX = ("fetch_puzzle", {"index_row", "index_row_deps"})
files, derived = row_cache.keyed_inputs(*IDX)
check("index rows are keyed on the abbreviation table", derived, ["build_abbreviations.table"])
check("and not on blocks.json's bytes", [p.name for p in files if p.name == "blocks.json"], [])
row_cache._DATA_FILES.clear()
salt = row_cache._data_salt(*IDX)
real_lexicon, real_table = build_abbreviations.LEXICON, build_abbreviations.table
counts = json.loads(real_lexicon.read_text())
word = next(iter(counts))
counts[word] = {k: n + 1 for k, n in counts[word].items()}
bumped = tmp / "blocks.json"
bumped.write_text(json.dumps(counts))
build_abbreviations.TABLE_CACHE = tmp / "abbreviations-table.json"  # never the user's cache
build_abbreviations.LEXICON, build_abbreviations._USAGE, build_abbreviations._TABLE = bumped, None, None
check("a blocks.json with new counts but the same table keeps the key", row_cache._data_salt(*IDX), salt)
check("(the table was built again from it)", build_abbreviations._TABLE is not None and
      build_abbreviations._inputs_key() == json.loads(build_abbreviations.TABLE_CACHE.read_text())["key"], True)
build_abbreviations.LEXICON, build_abbreviations._USAGE, build_abbreviations._TABLE = real_lexicon, None, None
built = real_table()
build_abbreviations.table = lambda: {**built, "zzzq": ["new sense"]}
check("a changed table changes the key", row_cache._data_salt(*IDX) != salt, True)
build_abbreviations.table = real_table
check("the real table again, the key again", row_cache._data_salt(*IDX), salt)

# Rows through the cache are the rows the functions make, cold and warm.
import fetch_puzzle
import blog_facts
real_all = sorted(Path("puzzles").resolve().glob("*/*/*-[0-9]*.json"))
few = real_all[::max(1, len(real_all) // 40)]
for module, fn, kw in [("fetch_puzzle", fetch_puzzle.index_row, {"roots": {"index_row_deps"}, "deps": fetch_puzzle.index_row_deps}),
                       ("blog_facts", blog_facts.puzzle_row, {})]:
    want = [fn(p) for p in few]
    for when in ("cold", "warm"):
        check(f"{module}.{fn.__name__} rows through the cache, {when}", row_cache.cached_map(module, fn, few, **kw), want)

# difficulty.checked(), the rows tools/difficulty_check.py and
# tools/snitch_report.py read, rates a file as score() and raw() rate it,
# cold and warm, and carries the fields those reports read off the file.
from types import SimpleNamespace
from fetch_puzzle import puzzle_is_annotated, read_puzzle_view
real = sorted(Path("puzzles").resolve().glob("*/*/*-[0-9]*.json"))
sample = real[::max(1, len(real) // 60)]
ctx = SimpleNamespace(rank=difficulty.ranks(), base=difficulty.load_baseline(),
                      history={f.stem: {"answer_novelty": 1.5, "pairing_novelty": 0.25} for f in sample[::2]})
want = []
for f in sample:
    puz = read_puzzle_view(f)
    want.append((puz["id"], puz.get("series"), series_meta.puzzle_day(puz), puzzle_is_annotated(puz),
                 difficulty.score(puz, ctx), difficulty.raw(puz, ctx)))
check("the sample holds a rated puzzle", any(w[4] for w in want), True)
for when in ("cold", "warm"):
    got = [(r["pid"], r["series"], r["date"], r["annotated"], difficulty.checked_score(r, ctx),
            difficulty.checked_raw(r, ctx)) for r in difficulty.checked(sample)]
    check(f"checked() rows rate as score() and raw(), {when}", got, want)

for f in fails:
    print("FAIL", f)
print("ok" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
