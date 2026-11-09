#!/usr/bin/env python3
# Is an edition dir another host laid out again (the Mac re-fetching a Gale
# edition: rmtree, then a rename of a fresh dir in) noticed by the queue's
# planner, with no hand step? media_manifest.notice_refetched records it, so
# input_hash moves and the plan rescans it.
#
#     python3 tests/test_refetch_noticed.py
#
# A fake HOME and a temp media root; nothing outside them is touched.
import json
import os
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
os.chdir(TOOLS)
import _path  # noqa: F401 (puts tools/ on sys.path)
tmp = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(tmp / "home")
os.environ["CT_DOWNLOADS"] = str(tmp / "media")
os.environ.pop("CT_MANIFEST", None)

import downloads
import media_manifest as mm

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

root = downloads.ARCHIVE_ORG
root.mkdir(parents=True)

def lay(item, day, src, at):
    d = root / item / day
    d.mkdir(parents=True)
    (d / "pages.json").write_text("{}")
    (d / f"sources-{src}.json").write_text(json.dumps([{"file": src}]))
    os.utime(d, (at, at))
    return d

import time
old = time.time() - 86400
g = lay("GaleTimes1999UKEnglish", "1999-01-02", "aaaa", old)
a = lay("SomeItem", "1999-01-02", "aaaa", old)
mm.record_edition(a)
mm.record(mm.GALE_EDITIONS, g, edition="GaleTimes1999UKEnglish/1999-01-02", files=mm.edition_files(g), at=old, sources=[1])
before = mm.edition_rows()["GaleTimes1999UKEnglish/1999-01-02"]["files"]

check("first call only notes mtimes", [], mm.notice_refetched())
check("nothing changed", [], mm.notice_refetched())

# The Mac's re-fetch: a fresh dir renamed over the old one.
import shutil
shutil.rmtree(g)
g2 = lay("GaleTimes1999UKEnglish", "1999-01-02", "bbbb", time.time())
(g2 / "leaf_0000.jpg").write_bytes(b"x")
# A new dir beside it in an unmoved-looking item is found too.
b = lay("SomeItem", "1999-01-03", "cccc", time.time())

check("refetched and new dirs noticed", ["GaleTimes1999UKEnglish/1999-01-02", "SomeItem/1999-01-03"],
      sorted(mm.notice_refetched()))
rows = mm.edition_rows()
check("files hash moved", True, rows["GaleTimes1999UKEnglish/1999-01-02"]["files"] != before)
check("files hash is the dir's", mm.edition_files(g2), rows["GaleTimes1999UKEnglish/1999-01-02"]["files"])
check("new dir has a row", mm.edition_files(b), rows["SomeItem/1999-01-03"]["files"])
check("sources carried", [{"file": "bbbb"}], mm.latest(mm.GALE_EDITIONS, "edition")["GaleTimes1999UKEnglish/1999-01-02"]["sources"])
check("untouched dir left alone", mm.edition_files(a), rows["SomeItem/1999-01-02"]["files"])
check("noticed once", [], mm.notice_refetched())

# A touched dir whose files are the same is not re-recorded.
os.utime(a, None)
os.utime(root / "SomeItem", None)
rows_before = mm.path(mm.ARCHIVE_EDITIONS).read_text()
check("same hash, nothing recorded", [], mm.notice_refetched())
check("no row appended", rows_before, mm.path(mm.ARCHIVE_EDITIONS).read_text())

# The cap leaves the rest for the next call.
for day in ("1999-02-01", "1999-02-02", "1999-02-03"):
    lay("SomeItem", day, "dddd", time.time())
first = mm.notice_refetched(cap=2)
check("cap holds", 2, len(first))
second = mm.notice_refetched(cap=2)
check("the rest next call", 1, len(second))
check("all three found", 3, len({*first, *second}))

sys.exit(1 if fails else 0)
