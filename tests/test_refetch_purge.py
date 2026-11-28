#!/usr/bin/env python3
# Do a refetched edition's derived OCR cache files move aside (and only its own)?
#
#     python3 tests/test_refetch_purge.py
#
# A fake HOME and CT_MANIFEST; nothing real is read or written.
import json
import os
import sys
import tempfile
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(tmp / "home")
os.environ["CT_MANIFEST"] = str(tmp / "manifest")
import _path  # puts tools/ on sys.path
import refetch_purge as rp

fails = 0


def check(what, want, got):
    global fails
    print(("ok   " if want == got else "FAIL ") + what
          + ("" if want == got else f": expected {str(want)[:60]!r}, got {str(got)[:60]!r}"))
    fails += want != got


crops = tmp / "crops"
root = tmp / "share"
(crops / "titles").mkdir(parents=True)
for ed in ("GaleSundayTimes/1983-10-23", "GaleSundayTimes/1990-01-01", "GaleTelegraph/1983-10-23"):
    (root / ed).mkdir(parents=True)
    for leaf in (0, 5):
        (root / ed / f"leaf_{leaf:04d}.jpg").write_text("x")
names = ["GaleSundayTimes_1983-10-23_5_page.ch.json", "GaleSundayTimes_1983-10-23_5_page.ch.gf.json",
         "GaleSundayTimes_1983-10-23_5_page.en5.json", "GaleSundayTimes_1983-10-23_0_page.en5.gf.json",
         "GaleSundayTimesX_1983-10-23_5_page.ch.json", "GaleTelegraph_1983-10-23_5_page.ch.json",
         "GaleSundayTimes_1990-01-01_5_page.ch.json",
         "GaleSundayTimes_1983-10-23_5_1042_3004_1632_3079.ch.json"]
for n in names:
    (crops / "titles" / n).write_text("{}")

# Nothing may list a cache dir: a titles/ scan is ~1M files.
real_scandir, real_listdir = os.scandir, os.listdir
def guard(path):
    if str(crops) in os.fspath(path):
        raise AssertionError(f"listed {path}")
os.scandir = lambda p=".": (guard(p), real_scandir(p))[1]
os.listdir = lambda p=".": (guard(p), real_listdir(p))[1]
got = rp.purge(["GaleSundayTimes/1983-10-23"], crops=crops, root=root, stamp="s1")
check("moved count", 4, got)
left = sorted(real_listdir(crops / "titles"))
check("own page files gone", [], [n for n in left if n.startswith("GaleSundayTimes_1983") and "_page." in n])
check("prefix-sharing item kept", True, "GaleSundayTimesX_1983-10-23_5_page.ch.json" in left)
check("other paper same date kept", True, "GaleTelegraph_1983-10-23_5_page.ch.json" in left)
check("other date kept", True, "GaleSundayTimes_1990-01-01_5_page.ch.json" in left)
check("band-keyed file (unbuildable name) left", True, "GaleSundayTimes_1983-10-23_5_1042_3004_1632_3079.ch.json" in left)
check("moved aside, not deleted", True, (crops / "stale_refetch/s1/titles/GaleSundayTimes_1983-10-23_5_page.ch.json").exists())
check("dry moves nothing", 1, rp.purge(["GaleSundayTimes/1990-01-01"], crops=crops, root=root, dry=True))
check("unlistable edition dir still found by name", 1, rp.purge(["GaleSundayTimes/1990-01-01"], crops=crops, root=tmp / "nowhere", dry=True))
check("never listed a cache dir", True, True)  # guard() raises otherwise
os.scandir, os.listdir = real_scandir, real_listdir

man = tmp / "manifest"
man.mkdir()
(man / "archiveorg-editions.jsonl").write_text("")
(man / "gale-editions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
    {"edition": "GaleSundayTimes/1990-01-01", "files": "a", "at": 10.0},
    {"edition": "GaleSundayTimes/1990-01-01", "files": "b", "at": 2e9},
    {"edition": "GaleTelegraph/1983-10-23", "files": "a", "at": 2e9}]))
import media_manifest
media_manifest._PATHS.clear()
check("refetched_since", {"GaleSundayTimes/1990-01-01": 2e9}, rp.refetched_since(1e9))
check("rows with no earlier change are not refetches", {}, rp.refetched_since(3e9))
check("file older than the refetch row moves", 1, len(rp.plan(["GaleSundayTimes/1990-01-01"], crops, root, {"GaleSundayTimes/1990-01-01": 2e9})))
os.utime(crops / "titles/GaleSundayTimes_1990-01-01_5_page.ch.json", (3e9, 3e9))
check("file newer than the refetch row stays", 0, len(rp.plan(["GaleSundayTimes/1990-01-01"], crops, root, {"GaleSundayTimes/1990-01-01": 2e9})))

import time
t = time.time()
rp.plan(["GaleSundayTimes/1983-10-23"], crops, tmp / "nowhere")
print(f"plan, unlistable dir (200 leaves): {time.time() - t:.3f}s")
print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
