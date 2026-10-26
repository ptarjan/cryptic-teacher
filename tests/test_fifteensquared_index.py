#!/usr/bin/env python3
# Do the fifteensquared readers find a category's posts off the index, without
# opening every cached post, and does tools/ft_puzzles.py's budget count its
# parse?
#
#     python3 tests/test_fifteensquared_index.py
#
# Opening every post over the container's virtiofs mount took ~15 minutes per
# pass, twice per FT run, and ran the ft unit past its limit. Everything here is
# a temp cache; nothing touches the network or the corpus.
import os
import pathlib
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp()
os.environ["CT_DOWNLOADS"] = TMP
sys.path.insert(0, str(REPO / "tools"))

fails = 0


def check(what, expected, got):
    global fails
    if expected == got:
        print(f"ok   {what}")
    else:
        print(f"FAIL {what}: expected [{expected}], got [{got}]")
        fails += 1


try:
    import fetch_fifteensquared as f
    import media_manifest

    def store(post):  # as fetch_posts does: the file, then its manifest row
        f.store(f.POSTS, post["id"], post)
        media_manifest.record_post(f.POSTS, post)

    f.POSTS.mkdir(parents=True)
    opened = []
    real_read = pathlib.Path.read_text

    def spy(self, *a, **k):
        opened.append(self.name)
        return real_read(self, *a, **k)

    pathlib.Path.read_text = spy
    try:
        for i, cats in ((1, [6]), (2, [4]), (3, [6, 4])):
            store({"id": i, "categories": cats})
        first = f"{[p.name for p in f.category_post_files(6)]} {opened}"

        # A post stored later joins off its manifest row; still no post is opened.
        opened.clear()
        store({"id": 5, "categories": [6]})
        topped = f"{[p.name for p in f.category_post_files(6)]} {sorted(opened)}"
    finally:
        pathlib.Path.read_text = real_read
    check("a category's posts read off the manifest, opening no post",
          "['1.json', '3.json'] ['posts-fifteensquared.jsonl']", first)
    check("a post stored later joins off its manifest row",
          "['1.json', '3.json', '5.json'] ['posts-fifteensquared.jsonl']", topped)

    import collections
    import time
    import ft_puzzles as F
    F.parse = lambda: (time.sleep(1.2), ([], []))[1]
    seen = []
    F.grids = lambda limit, nodes, budget: seen.append(budget)
    F.file = lambda write, limit: ([], collections.Counter())
    F.main(["--budget-seconds", "10", "--dry-run"])
    check("ft_puzzles spends its parse out of --budget-seconds", "BUDGET 9", f"BUDGET {round(seen[0])}")
finally:
    shutil.rmtree(TMP, ignore_errors=True)

if fails:
    print(f"{fails} failure(s)")
    sys.exit(1)
print("all ok")
