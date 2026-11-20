#!/usr/bin/env python3
# Does fetch_puzzle.reindex_changed() re-read only the puzzle files newer than
# the index, and fall back to the full reindex when there is no index?
#
#     python3 tests/test_reindex_changed.py
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
import _path  # puts tools/ on sys.path

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
    check("no index.js is written", False, (tmp / "index.js").exists())
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# reindex_from_deploy: the repair queue moving is not a reason to drop the
# deploy; only the puzzles whose queue entries differ are re-made.
import row_cache

now = F.QUEUE_FILE.read_bytes()
plain = row_cache.code_for("fetch_puzzle", "index_row", {"index_row_deps"})
check("code_for with the queue as it is: the plain key", plain,
      row_cache.code_for("fetch_puzzle", "index_row", {"index_row_deps"}, as_bytes={F.QUEUE_FILE.name: now}))
check("code_for with another queue: another key", True,
      plain != row_cache.code_for("fetch_puzzle", "index_row", {"index_row_deps"},
                                  as_bytes={F.QUEUE_FILE.name: now + b"\n"}))
old = json.dumps([
    {"id": "a-1#1a", "reason": "x", "tried": True},
    {"id": "a-1#2d", "reason": "y"},
    {"id": "b-2#3a", "reason": "z"},
    {"id": "c-3#1a", "reason": "w"},
]).encode()
new = json.dumps([
    {"id": "a-1#1a", "reason": "x", "tried": True, "tries": 2},  # bookkeeping only
    {"id": "b-2#3a", "reason": "z2"},                            # reason changed
    {"id": "d-4#1a", "reason": "v"},                             # added
]).encode()                                                      # a-1#2d and c-3#1a drained
check("queue by puzzle", {"a-1": {"1a": "x", "2d": "y"}, "b-2": {"3a": "z"}, "c-3": {"1a": "w"}},
      F._queue_by_puzzle(old))
scratch = Path(tempfile.mkdtemp())
try:
    (scratch / "q.json").write_bytes(new)
    keep = (F.QUEUE_FILE, F._queue_at)
    F.QUEUE_FILE, F._queue_at = scratch / "q.json", lambda commit: old
    check("puzzles whose queue entries differ", {"a-1", "b-2", "c-3", "d-4"}, F._queue_moved_ids("x"))
    F._queue_at = lambda commit: new
    check("same queue: none", set(), F._queue_moved_ids("x"))
    F.QUEUE_FILE, F._queue_at = keep
finally:
    shutil.rmtree(scratch, ignore_errors=True)

# The shim record: a shim whose stat is the recorded one is answered from the
# record, current or not, so a deploy that moves every row's `v` reads no shim;
# a copy reads only a sibling shim that sibling's record vouches for.
import hashlib

scratch = Path(tempfile.mkdtemp())
try:
    pz = scratch / "t-1.json"
    pz.write_text("{}")
    shim = puzzle_paths.shim_path(pz)
    shim.write_text("var a = 1;")
    h = hashlib.md5(shim.read_bytes()).hexdigest()[:8]
    check("no record: hashed, current", True, F._shim_current(pz, h, {}, {}))
    check("no record: hashed, stale", False, F._shim_current(pz, "zzzzzzzz", {}, {}))
    rec = {shim.name: ["aaaaaaaa", *F._stat_sig(shim)]}
    seen = {}
    check("recorded stat, another v: stale, unread", False, F._shim_current(pz, h, rec, seen))
    check("recorded stat: its entry kept", rec, seen)
    check("recorded stat, its v: current, unread", True, F._shim_current(pz, "aaaaaaaa", rec, {}))
    shim.write_text("var a = 22;")  # a rewrite moves the stat: read again
    check("stat moved: hashed", False, F._shim_current(pz, "aaaaaaaa", rec, {}))
    sib = scratch / "sib"
    sib.mkdir()
    (sib / shim.name).write_text("var b = 2;")
    h2 = hashlib.md5((sib / shim.name).read_bytes()).hexdigest()[:8]
    shim.unlink()
    check("sibling with no record: not read", None, F._copy_current_shim(pz, h2, sib, {}))
    check("sibling vouching another v: not read", None,
          F._copy_current_shim(pz, h2, sib, {shim.name: ["aaaaaaaa", *F._stat_sig(sib / shim.name)]}))
    vouch = {shim.name: [h2, *F._stat_sig(sib / shim.name)]}
    ino = F._copy_current_shim(pz, h2, sib, vouch)
    check("vouched sibling: copied", ("var b = 2;", shim.stat().st_ino), (shim.read_text(), ino))
    shim.unlink()
    made, left = F._copy_from_siblings([(pz, h2), (pz.with_name("t-2.json"), h2)], [(sib, None), (sib, scratch / "r")])
    check("no record file: nothing copied", ([], 2), (made, len(left)))
    (scratch / "r").write_text(json.dumps(vouch))
    made, left = F._copy_from_siblings([(pz, h2)], [(sib, scratch / "r")])
    check("record file vouches: copied", ([shim], []), ([m[0] for m in made], left))
    seen = {}
    F._record_made(seen, [(shim, h2, made[0][2])])
    check("just made: not recorded (racy)", {}, seen)
    F._record_made(seen, [(shim, h2, made[0][2] + 1)])
    check("another inode: not recorded", {}, seen)
finally:
    shutil.rmtree(scratch, ignore_errors=True)

if fails:
    print(f"{fails} failed")
    sys.exit(1)
print("all reindex_changed checks pass")
