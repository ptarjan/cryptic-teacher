#!/usr/bin/env python3
# Which daily units get the generated files (puzzles/index.*, the shims,
# abbreviations.js) rebuilt as their tree is set up? tools/daily_units.py
# GENERATED says, per unit kind; daily_update.sh asks it before sourcing
# tools/nightly_worktree.sh. A rebuild is a whole-corpus pass, and nearly
# every start finds HEAD moved, so a unit that reads none of them must not
# pay for it, and one that reads them must not start without them.
#
#     python3 tests/test_daily_units.py
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, "tools")
import daily_units as du

fails = []


def check(what, got, want):
    print(("ok   " if got == want else "FAIL ") + what + ("" if got == want else f": want {want!r}, got {got!r}"))
    if got != want:
        fails.append(what)


class Ledger:
    last_end, last_start = {}, {}
    def started_since(self, *a, **k): return 0
    def running(self, key): return False


# Every unit plan() can emit has a kind GENERATED names.
os.environ.update(DAILY_FRESH="p1", DAILY_PENDING="p2", DAILY_UNSOLVED="p1", DAILY_MISSES="p1 3a")
keys = [u.key for u in du.plan(Ledger(), 0)]
check("plan() emits annotate, miss and every phase", {k.split(":")[0] for k in keys} >= {"annotate", "miss", "fetch", "checks", "reports"}, True)
for k in keys:
    check(f"{k} has a kind in GENERATED", k.split(":", 1)[0] in du.GENERATED, True)

# Every live series is fetched: the slow ones on their own cadence, each a
# tools/<tool>.py whose --latest daily_update.sh's unit_fetch runs.
for f in du.SLOW_FETCHERS:
    check(f"fetch:{f} is planned", f"fetch:{f}" in keys, True)
    check(f"tools/{f}.py exists", os.path.exists(f"tools/{f}.py"), True)
    check(f"tools/{f}.py takes --latest", os.path.exists(f"tools/{f}.py") and "--latest" in open(f"tools/{f}.py").read(), True)
check("fetch:tls_puzzles looks every 6h", [p[1] for p in du.PHASES if p[0] == "fetch:tls_puzzles"], [6 * du.HOUR])
check("slow fetchers stay out of after_tick's FETCHERS", set(du.SLOW_FETCHERS) & set(du.FETCHERS), set())

# ratings records /progress/'s row off today's coverage ledger, so it waits for
# that ledger until LEDGER_WAIT_UNTIL, then records without it.
du.COVERAGE_STATE = Path(tempfile.mkdtemp())


def at(hour):
    return time.mktime((2026, 10, 15, hour, 0, 0, 0, 0, -1))


def plans_ratings(t):
    return "ratings" in [u.key for u in du.plan(Ledger(), t)]


check("ratings waits for today's coverage ledger in the morning", plans_ratings(at(3)), False)
check("the other phases do not wait for it", "checks" in [u.key for u in du.plan(Ledger(), at(3))], True)
check("ratings records without the ledger past LEDGER_WAIT_UNTIL", plans_ratings(at(du.LEDGER_WAIT_UNTIL)), True)
(du.COVERAGE_STATE / "2026-10-15.json").write_text("{}")
check("ratings runs once today's ledger is saved", plans_ratings(at(3)), True)
check("yesterday's ledger is not today's", plans_ratings(time.mktime((2026, 10, 16, 3, 0, 0, 0, 0, -1))), False)

# The choice, read off what each unit runs before its own build step.
for k in [f"fetch:{f}" for f in du.FETCHERS + du.SLOW_FETCHERS] + ["solutions", "blog:times", "blog:telegraph", "bucket:telegraph",
          "xval:globe", "ft", "azed", "blog-facts", "ratings", "minute", "reports", "checks"]:
    check(f"{k} skips the start rebuild", du.reads_generated(k), False)
for k in ["annotate:p1", "miss:p1:3a"]:
    check(f"{k} keeps the start rebuild", du.reads_generated(k), True)

# The CLI daily_update.sh reads: "none" skips, anything else (an unknown kind
# prints nothing) rebuilds.
def generated(kind):
    r = subprocess.run([sys.executable, "tools/daily_units.py", "generated", kind],
                       capture_output=True, text=True)
    return r.stdout.rstrip("\n")


check("generated fetch:fetch_independent", generated("fetch:fetch_independent"), "none")
check("generated annotate:x", generated("annotate:x"), "all")
check("generated of an unknown kind prints nothing", generated("nosuch"), "")
# /progress/'s row is ratings' first step, so the unit's time limit cannot take
# it (it was the last, and lost, on 2026-10-14 and 10-15).
text = (REPO / "tools" / "daily_update.sh").read_text()
block = re.search(r"^unit_ratings\(\) \{.*?^\}", text, re.S | re.M)
first = re.search(r"^  if step [a-z_]+", block.group(0), re.M) if block else None
check("unit_ratings records /progress/'s row first", first.group(0) if first else "", "  if step progress_record")
sys.exit(1 if fails else 0)
