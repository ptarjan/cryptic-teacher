#!/bin/bash
# Does row_cache.cached_map() parse again exactly the files whose row could
# have changed, and is every data file a cached row reads in its key?
#
#     bash tools/test_row_cache.sh
#
# A scratch corpus of three files is mapped with a parser that counts what it
# reads. A second map parses nothing; an edited file is parsed again and its
# row changes; a changed deps() value re-parses that row alone; a changed code
# key re-parses every file. Then the definitions index_row(), history_row()
# and clue_row() reach may name only the tools/data files their keys cover
# (blog facts, ninas, lexicon, wordnet): a new data input fails here until it
# is keyed. Never reads ~/.cache or the checkout's store: the store is scratch.
set -u
cd "$(dirname "$0")/.." || exit 1

CT_JOBS=1 python3 - <<'EOF'
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "tools")
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
for f in sorted(difficulty.BLOG_FACTS.glob("*.json")):
    with f.open("rb") as fh:
        strays = {pid for line in fh if line.startswith(b'"')
                  and series_meta.parse_id(pid := line[1:line.index(b'"', 1)].decode())[0] != f.stem}
    check(f"ids of another series in {f.name}", sorted(strays)[:3], [])

# Every tools/data path the cached functions reach must be in their keys:
# blog facts and ninas through deps(), the lexicon and wordnet through salt.
KEYED = {("fetch_puzzle", "BLOG_FACTS"), ("puzzle_tags", "NINAS"),
         ("difficulty", "BLOG_FACTS"), ("difficulty", "LEXICON"), ("difficulty", "WORDNET")}
for module, roots in [("fetch_puzzle", {"index_row", "index_row_deps"}),
                      ("difficulty", {"history_row", "history_row_deps"}),
                      ("difficulty", {"clue_row", "clue_row_deps", "_load_clue_inputs"})]:
    for mod, name in code_reach.reach(module, roots):
        obj = getattr(__import__(mod), name, None)
        if isinstance(obj, Path) and obj.is_relative_to(Path("tools/data").resolve()) and (mod, name) not in KEYED:
            fails.append(f"{module} {sorted(roots)} reads {mod}.{name} ({obj}), which no row key covers")

for f in fails:
    print("FAIL", f)
print("ok" if not fails else f"{len(fails)} failed")
sys.exit(1 if fails else 0)
EOF
