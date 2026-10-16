#!/usr/bin/env python3
# The crawlable pages are rendered in shards (build_seo_pages.py --shard i/n),
# one workflow step each, so no step passes its budget. A page belongs to one
# shard by a stable hash of its id; the split must be the same in every
# process; sharding must not move the page cache's fingerprint (a warm run
# skips the pages it skips unsharded); and the tail refuses a missing shard.
import os
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "tools")
import build_seo_pages as b
import page_cache

ids = [f"times-{n}" for n in range(1, 2001)] + [f"cryptic-{n}" for n in range(1, 2001)]
for n in (1, 3, 4, 7):
    shards = [[p for p in ids if b.shard_of(p, n) == i] for i in range(n)]
    assert sorted(sum(shards, [])) == sorted(ids), "every page is in exactly one shard"
    if n > 1:
        assert all(len(s) > len(ids) / n * 0.8 for s in shards), "a lopsided split"
out = subprocess.run([sys.executable, "-c",
                      "import sys; sys.path.insert(0, 'tools'); import build_seo_pages as b; "
                      "print(b.shard_of('times-1234', 4), b.shard_of('cryptic-9', 7))"],
                     capture_output=True, text=True, check=True,
                     env={**os.environ, "PYTHONHASHSEED": "123"}).stdout
assert out.split() == [str(b.shard_of("times-1234", 4)), str(b.shard_of("cryptic-9", 7))], \
    "the split depends on the process (hash() leaked in)"

# The sharding code is not on a puzzle page's path: the fingerprint ignores it.
reached = page_cache.reached()
assert not {k for k in reached if k[0] == "build_seo_pages"
            and k[1] in ("shard_of", "shard_file", "read_shards", "outputs", "shard_arg", "main")}, \
    "sharding code is in the page fingerprint: a warm run would re-render every page"

# The tail's exactly-once check.
with tempfile.TemporaryDirectory() as d:
    b.SHARD_DIR = Path(d)
    solved = [(None, {"id": p}) for p in ids[:50]]
    n = 3
    for i in range(n):
        part = {p: (None,) for _, s in solved for p in [s["id"]] if b.shard_of(p, n) == i}
        pickle.dump(part, open(b.shard_file(i, n), "wb"))
    assert len(b.read_shards(n, solved)) == 50
    victim = next(p for p in ids[:50] if b.shard_of(p, n) == 1)
    part = pickle.load(open(b.shard_file(1, n), "rb"))
    del part[victim]
    pickle.dump(part, open(b.shard_file(1, n), "wb"))
    try:
        b.read_shards(n, solved)
    except SystemExit as e:
        assert "rendered by no shard" in str(e)
    else:
        raise AssertionError("a missing page passed")
    part[victim] = (None,)
    part[next(p for p in ids[:50] if b.shard_of(p, n) == 0)] = (None,)   # in the wrong shard
    pickle.dump(part, open(b.shard_file(1, n), "wb"))
    try:
        b.read_shards(n, solved)
    except SystemExit as e:
        assert "belongs to shard 0" in str(e)
    else:
        raise AssertionError("a page in the wrong shard passed")
print("test_build_shards: ok")
