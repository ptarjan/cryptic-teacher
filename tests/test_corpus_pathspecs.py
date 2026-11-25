#!/usr/bin/env python3
# Does the untracked walk over puzzles/ skip the ~57k generated page folders
# (and the ~80k .js shims) while still finding a stray or a filed puzzle, and
# do the fetchers bring the index up to date incrementally rather than in full?
#
#     python3 tests/test_corpus_pathspecs.py
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
import _path  # puts tools/ on sys.path

import puzzle_integrity
import puzzle_paths

fails = 0


def check(what, want, got):
    global fails
    if want == got:
        print("ok  ", what)
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")


for name, shim in [("cryptic-30085", True), ("12345", True), ("cryptic", False), ("times", False),
                   ("idx", False), ("a-b-7", True), ("independent-8608.js", False)]:
    check(f"is_shim_folder({name!r})", shim, puzzle_paths.is_shim_folder(name))

tmp = Path(tempfile.mkdtemp())
try:
    git = lambda *a: subprocess.run(["git", "-C", str(tmp), *a], check=True, capture_output=True)
    git("init", "-q")
    pz = tmp / "puzzles"
    for d in ("times/2020", "indysunday/2021", "cryptic-30085", "123", "idx"):
        (pz / d).mkdir(parents=True)
    (pz / "cryptic-30085" / "index.html").write_text("x")
    (pz / "123" / "index.html").write_text("x")
    (pz / "times-1.js").write_text("shim")
    (pz / "times" / "2020" / "times-1.json").write_text("{}")
    (pz / "indysunday" / "2021" / "indysunday-2.json").write_text("{}")
    (pz / "cryptic-5.json").write_text("{}")        # a stray flat file
    (pz / "index.json").write_text("{}")
    puzzle_paths.PUZZLE_DIR = pz
    specs = puzzle_paths.corpus_pathspecs()
    check("shim folders and .js shims are not asked about",
          [":(literal)puzzles/" + n for n in ("cryptic-5.json", "idx", "index.json", "indysunday", "times")], specs)
    # git agrees, and so does listing(): the filed puzzles and the stray are all found
    found = git("ls-files", "-o", "-z", "--", *specs).stdout.decode().split("\0")
    check("git finds the filed puzzles and the stray", sorted([
        "puzzles/cryptic-5.json", "puzzles/index.json", "puzzles/indysunday/2021/indysunday-2.json",
        "puzzles/times/2020/times-1.json"]), sorted(f for f in found if f))
    check("listing() names the same json files", sorted([
        "puzzles/cryptic-5.json", "puzzles/index.json", "puzzles/indysunday/2021/indysunday-2.json",
        "puzzles/times/2020/times-1.json"]), sorted(puzzle_integrity.listing()))
    # a new series folder is picked up without being registered anywhere
    (pz / "newpaper" / "2022").mkdir(parents=True)
    (pz / "newpaper" / "2022" / "newpaper-9.json").write_text("{}")
    check("a new series folder is walked", True, "puzzles/newpaper/2022/newpaper-9.json" in puzzle_integrity.listing())
    puzzle_paths.PUZZLE_DIR = tmp / "absent"
    check("no puzzles folder: no pathspecs (never the whole repo)", [], puzzle_paths.corpus_pathspecs())
finally:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

# Every fetcher that reindexes after filing does it incrementally.
for f in ("independent", "telegraph", "globeandmail", "observer", "wayback"):
    src = (REPO / "tools" / f"fetch_{f}.py").read_text(encoding="utf-8")
    import re
    check(f"fetch_{f} never calls the full reindex()", [], re.findall(r"^[ \t]+reindex\(\)", src, re.M))

sys.exit(1 if fails else 0)
