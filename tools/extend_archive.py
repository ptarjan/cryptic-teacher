#!/usr/bin/env python3
"""Keep the annotation queue deeper than a week of burning can drain it.

    python3 tools/extend_archive.py             # top the queue up if it is short
    python3 tools/extend_archive.py --dry-run   # say what it would fetch, fetch nothing
    python3 tools/extend_archive.py --target 80 # override the measured target

The papers publish four or five puzzles a day between them; a good week of the
pre-reset burn annotates far more than that. Left alone the queue therefore
empties, and a burn with nothing to annotate spends the rest of its five-hour
window on nothing at all — the one outcome the whole job exists to avoid. The
archives go back years, so the fix is to walk backwards.

TARGET IS MEASURED, NOT CHOSEN. It is the most puzzles this job has cleared in
any seven-day stretch of the last two months: the queue only has to be deeper
than the best run it has ever had. A number typed in here would be wrong the
first time the burn got faster, and wrong in the expensive direction.

BACKLOG IS COUNTED FROM GIT, NOT FROM index.json. That file's `annotated` flags
are rewritten only by the republish step at the END of a run, so mid-run it
reads high by everything annotated since — and reading the backlog as deeper
than it is means not fetching, which is exactly the failure this guards.
tools/backlog_burndown.py already reconstructs the truth from history.
"""
import argparse
import bisect
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backlog_burndown import events  # noqa: E402

# One call each, round-robin, so a source that has run out of archive costs one
# chunk and not the whole top-up. Ordered by how much the app wants them: the
# Guardian cryptic is the flagship series, the Quiptic is the beginner tier the
# tutorial points at, and the Independent pair are the newest additions.
SOURCES = [
    ("cryptic", ["python3", "tools/fetch_puzzle.py", "--extend", "{n}", "cryptic"]),
    ("quiptic", ["python3", "tools/fetch_puzzle.py", "--extend", "{n}", "quiptic"]),
    ("independent", ["python3", "tools/fetch_independent.py", "--extend", "{n}"]),
    ("indysunday", ["python3", "tools/fetch_independent.py", "--extend-sundays", "{n}"]),
    ("everyman", ["python3", "tools/fetch_observer.py", "--extend", "{n}"]),
]
CHUNK = 20
WINDOW_DAYS = 60


def annotated_ids():
    """Every puzzle id that is already annotated, however it got that way."""
    idx = json.load(open("puzzles/index.json"))["puzzles"]
    live = {p["id"] for p in idx if p.get("hasSolutions")}
    flagged = {p["id"] for p in idx if p["annotated"]}
    _, done = events(live, flagged)
    return done


def backlog(done):
    """Un-annotated puzzles with solutions — what the queue will actually hold.

    Re-read from index.json each round because the fetchers reindex as they go.
    `done` is passed in rather than recomputed: nothing here annotates anything,
    so the set cannot move while we fetch, and walking the git log per round
    would cost more than the fetches.
    """
    idx = json.load(open("puzzles/index.json"))["puzzles"]
    return sum(1 for p in idx if p.get("hasSolutions") and p["id"] not in done)


def capacity(done):
    """The most puzzles annotated in any seven days of the last two months."""
    now = time.time()
    stamps = sorted(t for t in done.values() if now - t <= WINDOW_DAYS * 86400)
    return max((bisect.bisect_right(stamps, t + 7 * 86400) - i
                for i, t in enumerate(stamps)), default=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, help="queue depth to top up to")
    ap.add_argument("--chunk", type=int, default=CHUNK, help="puzzles per source per round")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    done = annotated_ids()
    target = args.target if args.target is not None else capacity(done)
    have = backlog(done)
    if not target:
        print("nothing annotated in the last two months — no measured demand, "
              "not fetching")
        return 0
    print(f"queue {have}, target {target} (best week in the last {WINDOW_DAYS} days)")
    if have >= target:
        return 0
    if args.dry_run:
        print(f"would extend {target - have} deeper across: "
              + ", ".join(s for s, _ in SOURCES))
        return 0

    # A source that returns nothing has hit the end of its archive, so it is
    # dropped for the rest of the run: asking it again would pay the same
    # requests for the same nothing. Not remembered across runs — an archive
    # that 404s today may be a publisher having a bad afternoon.
    alive = list(SOURCES)
    while have < target and alive:
        for source in list(alive):
            name, cmd = source
            print(f"--- extending {name} by {args.chunk}")
            rc = subprocess.run([a.format(n=args.chunk) for a in cmd]).returncode
            got = backlog(done)
            if rc != 0 or got == have:
                print(f"    {name} added nothing — dropping it for this run")
                alive.remove(source)
            have = got
            if have >= target:
                break
    print(f"queue now {have} (target {target})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
