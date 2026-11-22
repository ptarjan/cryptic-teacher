#!/usr/bin/env python3
# The puzzle fast path's time is spent where nothing can be skipped without
# changing the site, so the parts that were skipped have to be exact: the
# orphan scan finds what the Path-based walk it replaced found, the page store
# is left unwritten only when the workflow will not pack it either, and a shim
# is read for its .gz only when the .gz can be stale.
import gzip
import os
import sys
import tempfile
from pathlib import Path
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # puts tools/ on sys.path
import build_seo_pages as b
import page_cache
import puzzle_paths
import stage_site

# --- orphans(): a tree with every shape the rule names.
with tempfile.TemporaryDirectory() as d:
    root = Path(d) / "puzzles"

    def mk(rel, text):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    live = mk("times-1/index.html", "x")           # written this run
    mk("times-2/index.html", "x")                  # dead: only an index.html
    mk("times-3/index.html", "x")                  # unexpected: more than that
    mk("times-3/extra.txt", "x")
    mk("idx/a.json", "x")                          # unexpected, not dead
    mk("cryptic/2020/cryptic-1.json", "{}")        # a source folder
    mk("times-1.js", "x")                          # a file, never a candidate
    mk("series/times/2020/index.html", "x")        # dead listing
    mk("series/cryptic/2021/index.html", "x")      # written this run
    mk("series/index.html", "x")
    kept = {live, root / "series/cryptic/2021/index.html", root / "series/index.html"}
    saved = puzzle_paths.PUZZLE_DIR, puzzle_paths.puzzle_files
    puzzle_paths.PUZZLE_DIR = root
    puzzle_paths.puzzle_files = lambda *a: [root / "cryptic/2020/cryptic-1.json"]
    try:
        dead, unexpected = b.orphans(kept)
    finally:
        puzzle_paths.PUZZLE_DIR, puzzle_paths.puzzle_files = saved
    assert dead == sorted([root / "times-2", root / "series/times/2020"]), dead
    assert unexpected == sorted([root / "times-3", root / "idx"]), unexpected

# --- may_skip_save(): the workflow's Pack condition, inverted.
fp = "a" * 64
matched = f"seo-pages-{fp}-{'b' * 40}"
env = {"PAGE_STORE_MATCHED": matched, "PAGE_STORE_SKIP_UP_TO": "800"}
skip = page_cache.may_skip_save
assert skip(0, fp, env) and skip(800, fp, env), "a small render on a matching store need not save"
assert not skip(801, fp, env), "over the bar the workflow packs, so the store is written"
assert not skip(5, "c" * 64, env), "a store of another fingerprint is packed, so written"
assert not skip(5, None, env), "no fingerprint: the store is off, nothing to say"
assert not skip(5, fp, {}), "a local build always writes"
assert not skip(5, fp, {**env, "PAGE_STORE_MATCHED": ""}), "no restored store: written"
assert not skip(5, fp, {**env, "PAGE_STORE_SKIP_UP_TO": ""}), "no bar named: written"

# --- gzip_shim(): reads only a shim newer than its .gz.
with tempfile.TemporaryDirectory() as d:
    src = Path(d)
    (src / "puzzles").mkdir()
    rel = "puzzles/a-1.js"
    js, gz = src / rel, src / (rel + ".gz")
    js.write_text("one")
    manifest = {}
    stage_site._GZ = src, manifest
    _, digest = stage_site.gzip_shim(rel)                         # no .gz: made
    assert gzip.decompress(gz.read_bytes()) == b"one"
    manifest[rel] = digest
    os.utime(js, (1000, 1000))
    os.utime(gz, (2000, 2000))
    js.write_text("two")
    os.utime(js, (1000, 1000))                                    # bytes moved, mtime did not
    assert stage_site.gzip_shim(rel) == (rel, digest), "a shim older than its .gz is taken as unchanged"
    assert gzip.decompress(gz.read_bytes()) == b"one"
    os.utime(js, (3000, 3000))                                    # a shim written after the .gz
    _, new = stage_site.gzip_shim(rel)
    assert new != digest and gzip.decompress(gz.read_bytes()) == b"two", "a newer shim is gzipped again"
    gz.unlink()
    manifest[rel] = new
    stage_site.gzip_shim(rel)
    assert gz.is_file(), "a missing .gz is made whatever the manifest says"
    stage_site._GZ = None
print("test_fast_path_speed: all passed")
