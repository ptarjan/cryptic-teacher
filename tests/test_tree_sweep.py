#!/usr/bin/env python3
# Are job worktrees kept while the disk has room, and swept only when it is
# short? tools/tree_sweep.py sweep()/sweep_idle() ask disk_low() (shutil
# .disk_usage on the filesystem holding the root) before removing anything:
# a re-cut tree reads the whole corpus, so a tree is reused unless space runs out.
#
#     python3 tests/test_tree_sweep.py
import os
import shutil
import subprocess
import sys
import tempfile
from collections import namedtuple
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
import _path  # puts tools/ on sys.path
import tree_sweep as ts

fails = []


def check(what, got, want):
    print(("ok   " if got == want else "FAIL ") + what + ("" if got == want else f": want {want!r}, got {got!r}"))
    if got != want:
        fails.append(what)


Usage = namedtuple("Usage", "total used free")
GB = 1024 ** 3


def disk(total_gb, free_gb):
    return lambda _path: Usage(total_gb * GB, (total_gb - free_gb) * GB, free_gb * GB)


def low(total_gb, free_gb):
    ts.shutil.disk_usage = disk(total_gb, free_gb)
    return ts.disk_low("/")


real_usage, real_removable, real_run = shutil.disk_usage, ts.removable, subprocess.run

check("plentiful disk is not low", low(450, 206), False)
check("under the byte floor is low", low(450, 30), True)
check("under the fraction is low", low(2000, 250), True)
check("a small disk with free space over both is not low", low(100, 50), False)

with tempfile.TemporaryDirectory() as t:
    main, root = Path(t) / "main", Path(t) / "trees"
    main.mkdir()
    removed = []

    def fake_run(argv, **kw):
        if "remove" in argv:
            removed.append(Path(argv[-1]).name)
            shutil.rmtree(argv[-1])
        return subprocess.CompletedProcess(argv, 0, "", "")

    ts.removable = lambda tree: None  # every tree is clean and idle
    ts.subprocess.run = fake_run
    logs = []
    names = ["daily_unit-1", "daily_unit-2"]

    def fresh():
        removed.clear()
        for n in names:
            (root / n).mkdir(parents=True, exist_ok=True)
            (root / n / ".git").write_text("gitdir: /nonexistent\n")

    fresh()
    ts.shutil.disk_usage = disk(450, 206)
    check("sweep keeps idle trees when the disk has room", ts.sweep(main, root, names, log=logs.append), [])
    check("sweep_idle keeps old trees when the disk has room",
          ts.sweep_idle(main, root, hours=0, log=logs.append, now=2e10), [])
    check("nothing was removed with room to spare", (removed, sorted(p.name for p in root.iterdir())), ([], names))
    ts.shutil.disk_usage = disk(450, 20)
    check("sweep removes idle trees when the disk is low", ts.sweep(main, root, names, log=logs.append), names)
    fresh()
    check("sweep_idle removes old trees when the disk is low",
          ts.sweep_idle(main, root, hours=0, log=logs.append, now=2e10), names)
    fresh()
    ts.shutil.disk_usage = disk(450, 206)
    check("force sweeps despite room", ts.sweep(main, root, names, log=logs.append, force=True), names)

ts.shutil.disk_usage, ts.removable, ts.subprocess.run = real_usage, real_removable, real_run
print("TREE SWEEP PASSED" if not fails else f"{len(fails)} check(s) failed")
sys.exit(1 if fails else 0)
