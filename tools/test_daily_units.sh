#!/bin/bash
# Which daily units get the generated files (puzzles/index.*, the shims,
# abbreviations.js) rebuilt as their tree is set up? tools/daily_units.py
# GENERATED says, per unit kind; daily_update.sh asks it before sourcing
# tools/nightly_worktree.sh. A rebuild is a whole-corpus pass, and nearly
# every start finds HEAD moved, so a unit that reads none of them must not
# pay for it, and one that reads them must not start without them.
#
#     bash tools/test_daily_units.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
python3 - <<'PY'
import os
import sys
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

# The choice, read off what each unit runs before its own build step.
for k in [f"fetch:{f}" for f in du.FETCHERS + du.SLOW_FETCHERS] + ["solutions", "blog:times", "blog:telegraph", "bucket:telegraph",
          "xval:globe", "ft", "azed", "blog-facts", "ratings", "minute", "reports"]:
    check(f"{k} skips the start rebuild", du.reads_generated(k), False)
for k in ["checks", "annotate:p1", "miss:p1:3a"]:
    check(f"{k} keeps the start rebuild", du.reads_generated(k), True)
sys.exit(1 if fails else 0)
PY
rc=$?
# The CLI daily_update.sh reads: "none" skips, anything else (an unknown kind
# prints nothing) rebuilds.
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: want $3, got $2"; fails=1; fi; }
check "generated fetch:fetch_independent" "$(python3 tools/daily_units.py generated fetch:fetch_independent)" none
check "generated annotate:x" "$(python3 tools/daily_units.py generated annotate:x)" all
check "generated of an unknown kind prints nothing" "$(python3 tools/daily_units.py generated nosuch 2>/dev/null)" ""
[ "$rc" = 0 ] && [ "$fails" = 0 ]
