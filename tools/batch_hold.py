#!/usr/bin/env python3
"""The batch hold: one file that tells every scheduled batch job to start nothing.

    python3 tools/batch_hold.py path    # where the file is (what tools/prereset_backfill.sh reads)

    touch ~/.cryptic-teacher/prereset.pause     # hold
    rm ~/.cryptic-teacher/prereset.pause        # release

While the file exists the pre-reset burn (tools/prereset_backfill.sh) and the
nightly's heavy units (tools/unit_queue.py tick, the classes a queue lists in
HOLD_CLS: tools/daily_units.py) start no new run. Runs in flight finish and
land. The file's name is the one the machine's owner already uses; the burn
and the tick both get its path from here, so there is one place to change it.
CT_PRERESET_PAUSE overrides the path, CT_WORKTREE_ROOT the folder (tests).
"""
import os
import sys
import time
from pathlib import Path


def path():
    return Path(os.environ.get("CT_PRERESET_PAUSE")
                or Path(os.environ.get("CT_WORKTREE_ROOT") or Path.home() / ".cryptic-teacher") / "prereset.pause")


def held():
    return path().exists()


def say_once(who):
    """True the first time `who` sees this hold (a hold touched again counts as a new one):
    its marker is <file>.<who>.said beside it, so the burn's own .said stays the burn's."""
    hold = path()
    marker = hold.with_name(f"{hold.name}.{who}.said")
    try:
        if marker.exists() and marker.stat().st_mtime >= hold.stat().st_mtime:
            return False
        marker.touch()
    except OSError:
        return False
    return True


def since(fmt="%F %H:%M"):
    return time.strftime(fmt, time.localtime(path().stat().st_mtime))


if __name__ == "__main__":
    if sys.argv[1:] == ["path"]:
        print(path())
    else:
        sys.exit(__doc__)
