#!/usr/bin/env python3
# Is a full local cold rebuild of the puzzle index impossible by accident?
#
#     python3 tools/test_full_reindex_ban.py
#
# Plain --reindex is refused unless CI (GITHUB_ACTIONS), CT_ALLOW_FULL_REINDEX=1
# or --force-full; and reindex() stops when more index rows are missing from the
# row cache than FULL_SCAN_MISSES. A scratch puzzles dir and row cache; the
# checkout is not written and no corpus-wide scoring runs.
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, str(REPO / "tools"))

import fetch_puzzle as F
import puzzle_paths
import row_cache

fails = 0


def check(what, want, got):
    global fails
    if want == got:
        print("ok  ", what)
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")


for var in ("GITHUB_ACTIONS", "CT_ALLOW_FULL_REINDEX", "CT_REINDEX_IDS"):
    os.environ.pop(var, None)

src = sorted(puzzle_paths.PUZZLE_DIR.glob("times/2008/times-*.json"))[:4]
tmp = Path(tempfile.mkdtemp())
try:
    (tmp / "times" / "2008").mkdir(parents=True)
    for f in src:
        shutil.copy(f, tmp / "times" / "2008" / f.name)
    puzzle_paths.PUZZLE_DIR = tmp
    row_cache.STORE = str(tmp / "rows.sqlite")

    check("local, no override: not allowed", False, F.full_reindex_allowed())
    os.environ["GITHUB_ACTIONS"] = "true"
    check("CI is exempt", True, F.full_reindex_allowed())
    del os.environ["GITHUB_ACTIONS"]
    os.environ["CT_ALLOW_FULL_REINDEX"] = "1"
    check("CT_ALLOW_FULL_REINDEX=1 allows", True, F.full_reindex_allowed())
    del os.environ["CT_ALLOW_FULL_REINDEX"]

    # 1. the command line
    ran = []
    real_reindex = F.reindex
    F.reindex = lambda: ran.append(1) or {"puzzles": [], "latest": None}
    check("plain --reindex is refused (exit 2)", 2, F.main(["--reindex"]))
    check("and rebuilt nothing", [], ran)
    os.environ["CT_REINDEX_IDS"] = "x"
    check("a scoped --reindex is cheap and allowed", 0, F.main(["--reindex"]))
    del os.environ["CT_REINDEX_IDS"]
    check("--force-full allows it", 0, F.main(["--reindex", "--force-full"]))
    os.environ.pop("CT_ALLOW_FULL_REINDEX", None)
    os.environ["CT_ALLOW_PLAIN_REINDEX"] = "1"
    check("CT_ALLOW_PLAIN_REINDEX=1 lets the command start", 0, F.main(["--reindex"]))
    check("but is not a full-scan permit", False, F.full_reindex_allowed())
    del os.environ["CT_ALLOW_PLAIN_REINDEX"]

    # 2. the miss guard, on the real reindex() with an empty cache: 4 rows
    # missing against a limit of 3 stops it before anything is made or scored.
    F.reindex = real_reindex
    F.FULL_SCAN_MISSES = 3
    try:
        F.reindex()
        got = "rebuilt"
    except SystemExit as err:
        got = str(err)
    check("cold cache over the threshold: stops", True, "refusing a local full scan" in got)
    check("and names the cheap option", True, "--reindex-from-deploy" in got)
    check("nothing was written", False, (tmp / "index.json").exists())

    # The plain-reindex flag does not skip the guard; the full flag does.
    os.environ["CT_ALLOW_PLAIN_REINDEX"] = "1"
    try:
        F.reindex()
        got = "rebuilt"
    except SystemExit as err:
        got = str(err)
    check("plain flag + cold cache: guard still stops", True, "refusing a local full scan" in got)
    del os.environ["CT_ALLOW_PLAIN_REINDEX"]
    os.environ["CT_ALLOW_FULL_REINDEX"] = "1"
    try:
        rows_full = row_cache.cached_map(
            "fetch_puzzle", F.index_row, F.puzzle_files(), roots={"index_row_deps"},
            deps=F.index_row_deps, max_miss=None if F.full_reindex_allowed() else 3)
        got = len(rows_full)
    except row_cache.TooManyMisses:
        got = "raised"
    check("full flag skips the guard", 4, got)
    del os.environ["CT_ALLOW_FULL_REINDEX"]

    # wait_for_deploy: asks for the plain flag only, and a tripped guard is
    # "unverified" (exit 0, no traceback), not NOT DEPLOYED.
    import io
    import contextlib
    import subprocess
    import wait_for_deploy as W
    seen = []

    class Done:
        def __init__(self, rc, err=""):
            self.returncode, self.stderr, self.stdout = rc, err, ""

    real_run = subprocess.run

    def fake_run(cmd, *a, **kw):
        if cmd[:2] == ["git", "worktree"]:
            return Done(0)
        seen.append(kw.get("env", {}))
        return Done(2, "refusing a local full scan: row cache for x: 9000 rows missing") \
            if "--reindex" in cmd else Done(0)

    real_mkdtemp = W.tempfile.mkdtemp
    W.subprocess.run = fake_run
    W.tempfile.mkdtemp = lambda prefix="": str(tmp)
    try:
        try:
            W.shipped_index_stamp("HEAD")
            got = "stamped"
        except W.ColdRowCache:
            got = "cold"
        check("guard trip under wait_for_deploy: ColdRowCache", "cold", got)
        env = seen[-1]
        check("it asks for the plain flag", "1", env.get("CT_ALLOW_PLAIN_REINDEX"))
        check("and not the full one", None, env.get("CT_ALLOW_FULL_REINDEX"))

        W.shipped_index_stamp = lambda head: (_ for _ in ()).throw(W.ColdRowCache("cold"))
        W.want_stamps = lambda: {}
        sys.argv = ["wait_for_deploy.py", "--check"]
        out, errs = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(errs):
            rc = W.main()
        check("unverified exits cleanly", 0, rc)
        check("says it can't verify", True, "can't verify locally: row cache cold" in out.getvalue())
        check("not reported NOT DEPLOYED", False, "NOT DEPLOYED" in out.getvalue() + errs.getvalue())
    finally:
        W.subprocess.run = real_run
        W.tempfile.mkdtemp = real_mkdtemp

    # Under the threshold the guard stays out of the way.
    F.FULL_SCAN_MISSES = 4
    rows = row_cache.cached_map("fetch_puzzle", F.index_row, F.puzzle_files(),
                                roots={"index_row_deps"}, deps=F.index_row_deps, max_miss=4)
    check("at the threshold: rows made", 4, len(rows))
    try:
        row_cache.cached_map("fetch_puzzle", F.index_row, F.puzzle_files(),
                             roots={"index_row_deps"}, deps=F.index_row_deps, max_miss=0)
        got = "ok"
    except row_cache.TooManyMisses:
        got = "raised"
    check("a warm cache has no misses to trip on", "ok", got)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

sys.exit(1 if fails else 0)
