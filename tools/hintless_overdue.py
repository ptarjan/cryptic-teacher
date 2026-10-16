#!/usr/bin/env python3
"""A newly filed puzzle that is still hintless long after it should have been annotated.

    python3 tools/hintless_overdue.py          # list them; exit 1 if any

Every other failure of the annotate step announces itself: a run that errors or
times out alerts (tools/daily_update.sh), a fetch that fails alerts, a series
that goes quiet alerts (coverage_report.py --stale-only). What none of them
catches is the silent one: a puzzle is filed, solved, and annotation simply
never reaches it -- no error, no timeout, the queue just did not pick it. The
site then shows the newest puzzle with answers and no hints, and nobody is told.

What counts as overdue, all of:
  - filed (its file first added to git) more than OVERDUE_HOURS ago;
  - dated within the last FRESH_DAYS, so a backfilled old puzzle waiting its turn
    in the capped backlog (ANNOTATE_MAX a day, by design) is not a fault;
  - a puzzle annotation can work on: every answer held (fetch_puzzle.puzzle_is_solved),
    not awaiting a preamble, not held back by a recorded failure for these exact
    inputs (tools/failed_inputs.py -- those already alerted when they failed);
  - some clue still lacks its annotation (fetch_puzzle.puzzle_is_annotated).

A puzzle held back by the weekly/five-hour usage gate is indistinguishable from
a silent miss at this point, so the message names the gate as a likely reason
instead of staying quiet: the gate skipping for a day and a half running is
itself something to look at.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import series as series_meta

ROOT = Path(__file__).resolve().parent.parent

# A puzzle dated today is annotated by that night's run (`fresh` in
# daily_update.sh is uncapped), so by the next night's run -- about 24h later --
# it has had two chances. 36h is that plus half a night's slack for a late tick
# or a unit deadline putting one run off, so a single bad night does not fire
# but two missed nights always do.
OVERDUE_HOURS = 36
# daily_update.sh's `fresh` queue is "dated within the last two days"; a week is
# wide enough to catch one that fell out of it, narrow enough to leave backfills
# to the capped backlog.
FRESH_DAYS = 7


def filed_times(root=ROOT, now=None, days=FRESH_DAYS + 2):
    """{puzzle id: (epoch seconds its file was first added, its path)}, for files added in
    the last `days` days. One git call; --no-renames so a file moved between year
    folders reads as new rather than lost, and the earliest add wins."""
    since = (now or time.time()) - days * 86400
    out = subprocess.run(
        ["git", "-C", str(root), "log", f"--since=@{int(since)}", "--no-renames", "--diff-filter=A",
         "--name-only", "--format=@%ct", "--", "puzzles/*/*/*.json"],
        capture_output=True, text=True, check=True).stdout
    filed, when = {}, None
    for line in out.splitlines():
        if line.startswith("@"):
            when = int(line[1:])
        elif line.endswith(".json") and when is not None:
            pid = Path(line).stem
            filed[pid] = (min(when, filed[pid][0]) if pid in filed else when, line)
    return filed


def overdue(filed, read, now, blocked=(), today=None):
    """[(id, hours since filed)], oldest first. `read(path)` returns the puzzle dict
    (None if gone); `blocked` is the ids with a recorded annotate failure."""
    import fetch_puzzle as F
    today = today or time.gmtime(now)
    import datetime
    today = datetime.date(today.tm_year, today.tm_mon, today.tm_mday) if not isinstance(today, datetime.date) else today
    late = []
    for pid, (when, path) in filed.items():
        hours = (now - when) / 3600
        if hours <= OVERDUE_HOURS or pid in blocked:
            continue
        p = read(path)
        if not p or p.get("awaitsPreamble"):
            continue
        day = series_meta.puzzle_day(p)
        if day is None or (today - day).days > FRESH_DAYS:
            continue
        if F.puzzle_is_solved(p) and not F.puzzle_is_annotated(p):
            late.append((pid, hours))
    return sorted(late, key=lambda t: -t[1])


def main():
    import failed_inputs
    now = time.time()

    def read(path):
        try:
            return json.loads((ROOT / path).read_text(encoding="utf-8"))
        except OSError:   # filed, then moved or removed since
            return None

    late = overdue(filed_times(now=now), read, now, set(failed_inputs.skipped(failed_inputs.load(), "annotate")))
    if not late:
        return 0
    print(f"{len(late)} puzzle(s) filed more than {OVERDUE_HOURS}h ago still have no hints, and no annotate "
          "failure is recorded for them. Either annotation never reached them or the usage gate has been "
          "skipping it (see the 'weekly usage' lines in .update.log):")
    for pid, hours in late:
        print(f"  {pid}  filed {hours:.0f}h ago")
    return 1


if __name__ == "__main__":
    sys.exit(main())
