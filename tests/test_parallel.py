#!/usr/bin/env python3
# Does tools/parallel.py size its pool to the box? CT_JOBS wins; a process at
# nice 0 (the deploy's build) takes every core; a niced one (the daily units,
# the corpus job) takes only the cores the load leaves idle, down to one, and
# pmap then runs serially with no fork; and pmap's results are the serial
# loop's either way.
#
#     python3 tests/test_parallel.py
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
os.environ.pop("CT_JOBS", None)

import parallel as par

fails = []


def check(name, want, got):
    if want != got:
        fails.append(f"{name}: want {want!r}, got {got!r}")


cores = os.cpu_count() or 1
niced = os.nice(0) > 0
par.LOAD_READER = lambda: 0.0
check("an idle box: every core, niced or not", cores, par.workers())
par.LOAD_READER = lambda: 1e6
check("a loaded box: every core at nice 0, one when niced", 1 if niced else cores, par.workers())
os.environ["CT_JOBS"] = "3"
check("CT_JOBS wins over the load", 3, par.workers())
del os.environ["CT_JOBS"]

if os.fork() == 0:  # the niced half, in a child so this process keeps its niceness
    os.nice(19)
    par.LOAD_READER = lambda: max(0, cores - 2) + 0.5
    want = max(1, cores - max(0, cores - 2) - 1)
    got = par.workers()
    par.LOAD_READER = lambda: 1e6
    serial = par.pmap(abs, range(-300, 0), chunksize=4)
    os._exit(0 if got == want and serial == [abs(x) for x in range(-300, 0)] else 1)
_, status = os.wait()
check("niced: the idle cores (load rounded up), and a serial pmap's results", 0, os.waitstatus_to_exitcode(status))
check("pmap matches the serial loop", [x * x for x in range(500)], par.pmap(abs, [x * x for x in range(500)], chunksize=8))

if fails:
    print("\n".join("FAIL: " + f for f in fails))
    raise SystemExit(1)
print("parallel: ok")
