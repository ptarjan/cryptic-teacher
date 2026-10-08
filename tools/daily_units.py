#!/usr/bin/env python3
"""The nightly's queue (tools/unit_queue.py): what tools/daily_update.sh does, as units.

    python3 tools/daily_units.py keyed --record   # note the puzzles whose official key this tree just gained
    python3 tools/daily_units.py keyed --recent   # those noted within FRESH_DAYS, for the annotation queue

tools/daily_update.sh with no argument is the tick: it chooses the puzzles to
annotate (its selection blocks, under the usage gates) and hands them here in
DAILY_FRESH / DAILY_PENDING / DAILY_UNSOLVED / DAILY_MISSES; plan() adds the
fetch-and-file phases, each on its own cadence. Each unit runs
`tools/daily_update.sh unit <key> [args]` in one of SLOTS trees and commits
and pushes what it changed itself.

The dependencies, all here:
  * every filing unit (fetch:*, blog:*, bucket:*, ft, azed) cross-checks and
    commits its own filings, so nothing waits for a sibling to file;
  * blog-facts re-reads the blog caches after any blog fetch ended well
    (trigger), and not while one runs (after);
  * a graded miss is diagnosed before any cold solve starts (annotate of an
    unsolved puzzle is `after` every miss:*), so its fix governs the solve;
  * the solutions unit notes the puzzles it gave a key (keyed --record), and
    the tick's annotation queue reads them as new arrivals (keyed --recent).
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from unit_queue import STATE, Unit, main_checkout

LOG = ".update.log"
#: Trees daily_unit-1 .. daily_unit-SLOTS: at most this many units at once.
#: Each start rebuilds its tree's index, one at a time (nightly_worktree.sh).
SLOTS = 3
TREE = "daily_unit"
#: Model runs (annotate, miss, reports) at once.
LIMITS = {"claude": 2}
#: Started from the main checkout, as the scheduler starts the tick:
#: tools/nightly_worktree.sh takes the checkout a script runs from as the one
#: whose state (CT_MAIN_CHECKOUT, the shared files) every tree links to.
SCRIPT = "tools/daily_update.sh"
HOUR = 3600
DAY = 24 * HOUR
FETCHERS = ["fetch_puzzle", "fetch_independent", "fetch_observer", "fetch_privateeye", "fetch_globeandmail",
            "fetch_metro"]


def knob(name):
    """A setting of tools/daily_update.sh: what the tick passed, or, planned
    by hand, the script's own default (one copy of each number)."""
    if os.environ.get(name):
        return int(os.environ[name])
    text = (TOOLS / "daily_update.sh").read_text(encoding="utf-8")
    return int(re.search(rf'^{name}="\$\{{{name}:-(\d+)\}}"', text, re.MULTILINE).group(1))


#: Backlog annotations (cold solves included) a day; new arrivals are not cut.
ANNOTATE_MAX = knob("ANNOTATE_MAX")
#: An annotate unit's whole limit: its run, a resumed retry and a validation
#: fix, each capped at ANNOTATE_MAX_MINUTES inside the unit.
ANNOTATE_SECONDS = 3 * knob("ANNOTATE_MAX_MINUTES") * 60 + 1800
#: After an annotation that failed the way that stopped the old nightly (the
#: CLI's own failure: a login, a limit, a crash), no annotation starts for this
#: long: the next would most likely buy the same failure.
ANNOTATE_PAUSE = 3 * HOUR
#: rc of an annotate unit whose failure says nothing about the puzzle.
STOP_RC = 1
KEYED = STATE / "daily-keyed.jsonl"
FRESH_DAYS = 2

#: (key, every, timeout seconds, trigger) of the phases that run on a cadence.
#: The filers' per-run limits (daily_update.sh) are their old nightly budgets
#: divided by how often they now run.
PHASES = [
    *[(f"fetch:{f}", HOUR, 20 * 60, ()) for f in FETCHERS],
    ("solutions", 3 * HOUR, 40 * 60, ()),
    ("blog:times", 3 * HOUR, 45 * 60, ()),
    ("blog:telegraph", 3 * HOUR, 45 * 60, ()),
    ("bucket:telegraph", DAY, 45 * 60, ()),
    ("ft", 6 * HOUR, 45 * 60, ()),
    ("azed", DAY, 20 * 60, ()),
    ("xval:globe", DAY, 30 * 60, ()),
    ("blog-facts", DAY, 40 * 60, ("blog:times", "blog:telegraph", "bucket:telegraph", "ft")),
    ("ratings", DAY, 40 * 60, ()),
    ("checks", DAY, 20 * 60, ()),
    ("minute", 6 * HOUR, 10 * 60, ()),
    ("reports", 2 * HOUR, 60 * 60, ()),
]


def unit(key, *args, **kw):
    return Unit(key=key, argv=["bash", str(main_checkout() / SCRIPT), "unit", key, *args], **kw)


def annotate_paused(ledger, now):
    """Whether an annotation ended in STOP_RC within ANNOTATE_PAUSE."""
    return any(k.startswith("annotate:") and e.get("rc") == STOP_RC and now - e["at"] < ANNOTATE_PAUSE
               for k, e in ledger.last_end.items())


def plan(ledger, now):
    out = []
    fresh = os.environ.get("DAILY_FRESH", "").split()
    pending = os.environ.get("DAILY_PENDING", "").split()
    unsolved = set(os.environ.get("DAILY_UNSOLVED", "").split())
    misses = [line.split() for line in os.environ.get("DAILY_MISSES", "").splitlines() if line.strip()]
    miss_keys = tuple(f"miss:{pid}:{eid}" for pid, eid in misses)
    if not annotate_paused(ledger, now):
        for i in fresh:
            out.append(unit(f"annotate:{i}", *(["solve"] if i in unsolved else []), timeout=ANNOTATE_SECONDS,
                            cls="claude", tag="fresh", why="a new arrival",
                            after=miss_keys if i in unsolved else ()))
        for pid, eid in misses:
            out.append(unit(f"miss:{pid}:{eid}", pid, eid, timeout=45 * 60, cls="claude", why="a graded miss"))
        room = ANNOTATE_MAX - ledger.started_since("annotate:", now - DAY, tag="backlog")
        for i in pending:
            if room <= 0:
                break
            u = unit(f"annotate:{i}", *(["solve"] if i in unsolved else []), timeout=ANNOTATE_SECONDS,
                     cls="claude", tag="backlog", why="the backlog", after=miss_keys if i in unsolved else ())
            if not ledger.running(u.key) and u.key not in ledger.last_start:
                room -= 1
            out.append(u)
    for key, every, timeout, trigger in PHASES:
        out.append(unit(key, timeout=timeout, every=every, trigger=trigger, after=trigger,
                        cls="claude" if key == "reports" else ""))
    return out


def after_tick(ledger, now):
    """One fetcher down is weather; every one of them failing at once is us
    (a changed user agent, no network, a python that no longer starts), and
    looks exactly like a quiet day from the site."""
    ends = [ledger.last_end.get(f"fetch:{f}") for f in FETCHERS]
    if all(e is not None and e.get("rc") != 0 for e in ends):
        from unit_queue import alert
        alert(f"every fetcher's last run failed ({' '.join(FETCHERS)}), so no new puzzle can arrive from any paper "
              "until this is fixed. Their lines are in .update.log, `[fetch:...]`.")


def keyed(text):
    """True when a puzzle file's text carries the paper's complete key."""
    import provenance
    puzzle = json.loads(text)
    return not provenance.solution_detail(puzzle) and all(e.get("solution") for e in puzzle.get("entries", []))


def git(*args):
    run = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return run.stdout if run.returncode == 0 else ""


def record_keyed():
    """Note each puzzle this tree gave a complete key since HEAD."""
    rows = []
    for path in git("diff", "--name-only", "HEAD", "--", "puzzles/").split():
        try:
            if not keyed(git("show", f"HEAD:{path}") or "{}") and keyed(Path(path).read_text()):
                rows.append({"id": path.rsplit("/", 1)[-1].removesuffix(".json"), "at": time.time()})
        except (OSError, ValueError):
            continue  # deleted or half-written; the validator reports those
    if rows:
        KEYED.parent.mkdir(parents=True, exist_ok=True)
        with open(KEYED, "a") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows))
        print("keyed: " + " ".join(r["id"] for r in rows))


def recent_keyed():
    cut = time.time() - FRESH_DAYS * DAY
    try:
        lines = KEYED.read_text().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r["at"] >= cut and r["id"] not in out:
            out.append(r["id"])
    return out


def main(argv):
    if argv[:2] == ["keyed", "--record"]:
        record_keyed()
        return 0
    if argv[:2] == ["keyed", "--recent"]:
        print(" ".join(recent_keyed()))
        return 0
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
