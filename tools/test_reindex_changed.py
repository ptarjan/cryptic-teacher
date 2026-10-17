#!/usr/bin/env python3
# Does fetch_puzzle.reindex_changed() re-read only the puzzle files newer than
# the index, and fall back to the full reindex when there is no index?
#
#     python3 tools/test_reindex_changed.py
#
# A scratch puzzles dir of a handful of copied files (CT_REINDEX_IDS scopes the
# baseline index so no corpus-wide scoring runs); the checkout is not written.
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, str(REPO / "tools"))

import fetch_puzzle as F
import puzzle_paths

fails = 0


def check(what, want, got):
    global fails
    if want == got:
        print("ok  ", what)
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")


src = sorted(puzzle_paths.PUZZLE_DIR.glob("times/2008/times-*.json"))[:6]
tmp = Path(tempfile.mkdtemp())
try:
    (tmp / "times" / "2008").mkdir(parents=True)
    held = src[:5]
    for f in held:
        shutil.copy(f, tmp / "times" / "2008" / f.name)
    puzzle_paths.PUZZLE_DIR = tmp
    os.environ["CT_REINDEX_IDS"] = ",".join(f.stem for f in src)
    index = tmp / "index.json"

    check("no index: falls back to the full reindex", None, F.reindex_changed())
    check("and writes it", 5, len(json.loads(index.read_text())["puzzles"]))

    check("nothing newer than the index: nothing re-read", 0, F.reindex_changed())

    before = {r["id"]: r for r in json.loads(index.read_text())["puzzles"]}
    time.sleep(0.05)
    touched = tmp / "times" / "2008" / held[0].name
    touched.write_bytes(touched.read_bytes())
    new = tmp / "times" / "2008" / src[5].name
    shutil.copy(src[5], new)
    start = time.time()
    check("one touched file and one new: two re-read", 2, F.reindex_changed())
    print(f"     ({time.time() - start:.2f}s)")
    after = json.loads(index.read_text())
    rows = {r["id"]: r for r in after["puzzles"]}
    check("the new puzzle is in the index", True, src[5].stem in rows)
    check("the rest are as they were", True,
          all(rows[i] == before[i] for i in before if i != held[0].stem))
    check("the touched row is the file's", before[held[0].stem], rows[held[0].stem])
    check("index.js matches index.json", True,
          (tmp / "index.js").read_text().endswith(json.dumps(after, ensure_ascii=False, separators=F.COMPACT) + ";\n"))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if fails:
    print(f"{fails} failed")
    sys.exit(1)
print("all reindex_changed checks pass")
