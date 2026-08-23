#!/usr/bin/env python3
"""How early the pre-reset backfill should start, and how wide it should run.

Unspent weekly quota does not roll over: whatever is left when the window turns
over is gone. tools/prereset_backfill.sh exists to spend it, and for its first
weeks it could not — it started two hours before the reset and ran one
annotation at a time, which is a few puzzles against a remainder measured in
tens of percent.

Both numbers come out of the same arithmetic, so they live here rather than in
the shell, where a float is a fork and none of it can be tested without
spending real inference:

    hours needed = percent left / (rate * cap)      when to start
    width        = (percent left / hours left) / rate    how many at once

`rate` is the only thing that has to be measured: percent-points of the weekly
window that ONE annotation run burns in ONE hour. The job records what it
actually achieved after every wave (--observe), so the estimate is a fact about
this machine and this model rather than a constant fitted once and left to rot.

    tools/prereset_plan.py --window-hours          # start when reset is this close
    tools/prereset_plan.py --width 6.5             # runs to keep in flight
    tools/prereset_plan.py --observe 4.2 1.5 3     # climb, hours, width
    tools/prereset_plan.py --self-test

Reads only, except --observe, which writes .prereset_rate.
"""
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weekly_usage  # noqa: E402

RATE_FILE = Path(__file__).resolve().parent.parent / ".prereset_rate"

# A FLOOR, not a measurement, and deliberately used as one. The two clean runs on
# record (2026-08-12, 2026-08-19) both annotated at ~3.25 puzzles an hour and both
# were pinned at a displayed 100% for most of that hour, so the true cost per
# puzzle is censored from above: it is at least 0.33 points, and could be several
# times that. Under-guessing the rate starts this job earlier and wider than it
# strictly needs, which costs nothing out of a window that was going to evaporate;
# over-guessing wastes the remainder, which is the failure this file exists for.
#
# One ordinary agent has been seen to sustain ~5 points an hour on this machine,
# so CAP runs at this rate is about as hard as it has ever been driven.
SEED_RATE = 1.1

# An ungated hour of inference is defensible in the last hours of a window and
# indefensible in the first, so the arithmetic is clamped at both ends. The
# ceiling is the important one: without it a low rate estimate would have this
# job start on Monday, which is the hard-coded 04:00 bug wearing a new hat.
#
# The ceiling is seven hours. Paul, 2026-08-23: "it should wait until maybe 7
# hours before the weekly limit and then start using all the inference." So the
# job stays out of the week entirely until the last seven hours, however big the
# remainder or however slow the measured rate — and then holds nothing back.
MIN_HOURS = 2.0
MAX_HOURS = float(os.environ.get("PRERESET_MAX_HOURS", 7))

# Waiting until seven hours out is what makes this number big. A remainder that
# needs a day of one-at-a-time has to be spent in a seventh of that, so width is
# the only lever left. These runs are almost entirely waiting on the API, so the
# cost of a spare one is a process, not a core.
CAP = int(os.environ.get("PARALLEL_MAX", 8))

# Planning deliberately assumes we are slower than measured. Guessing high wastes
# quota — the failure this whole file exists to fix — while guessing low costs an
# earlier start inside a window that was going to evaporate anyway.
SAFETY = 0.7


def rate():
    """Percent of the weekly window one annotation run burns per hour."""
    try:
        got = float(RATE_FILE.read_text().split()[0])
        return got if got > 0 else SEED_RATE
    except (OSError, ValueError, IndexError):
        return SEED_RATE


def observe(climb, hours, width):
    """Fold one wave's achieved burn into the estimate.

    Halved with the old value rather than replacing it: a wave that overlapped a
    long interactive session reads as a burn this job cannot reproduce alone, and
    one such wave should not set the plan for the next month.

    Anything else on the machine inflates `climb`, so the error is toward
    thinking we spend faster than we do — which is why planning applies SAFETY
    on the way back out.
    """
    if hours <= 0 or width <= 0 or climb <= 0:
        return rate()
    got = (rate() + climb / (hours * width)) / 2
    RATE_FILE.write_text(f"{got:.3f}\n")
    return got


def window_hours(pct_left, r=None):
    """How close to the reset spending should begin, in hours."""
    r = rate() if r is None else r
    need = pct_left / max(r * SAFETY * CAP, 1e-6)
    return max(MIN_HOURS, min(MAX_HOURS, need))


def width(pct_left, hours_left, r=None):
    """How many annotation runs to keep in flight for the next wave."""
    r = rate() if r is None else r
    if hours_left <= 0 or pct_left <= 0:
        return 1
    return max(1, min(CAP, math.ceil((pct_left / hours_left) / (r * SAFETY))))


def pct_left():
    return max(0.0, 100.0 - weekly_usage.usage_pct("weekly"))


def self_test():
    """The two decisions, at the sizes that actually happen.

    Both were wrong in the same direction before this file existed, so the cases
    that matter are the big remainders: a job that spends everything when 3% is
    left and nothing when 70% is has still wasted the whole point.
    """
    cases = [
        # pct_left, hours_left, rate -> width, and the window it starts in
        (70, 10, 0.5, CAP, MAX_HOURS),    # a wasted week: as wide and early as allowed
        (3, 3, 1.5, 1, MIN_HOURS),        # nearly spent: one run, the old behaviour
        (0, 5, 1.5, 1, MIN_HOURS),        # nothing left: never negative or zero
        (30, 6, 1.5, 5, 3.57),            # the middle, where neither clamp is doing the work
    ]
    bad = 0
    for left, hours, r, want_w, want_h in cases:
        got_w, got_h = width(left, hours, r), window_hours(left, r)
        if got_w != want_w or abs(got_h - want_h) > 0.05:
            print(f"FAIL {left}% in {hours}h at {r}: width {got_w} (want {want_w}), "
                  f"start {got_h:.2f}h (want {want_h})", file=sys.stderr)
            bad += 1
    # Counted, not typed: a hand-written total goes stale the first time a case
    # is added and then reports a shrinking suite as a passing one.
    print(f"prereset plan self-test FAILED: {bad} of {len(cases)}" if bad
          else f"prereset plan self-test: {len(cases)} cases pass")
    return 1 if bad else 0


def main():
    if "--self-test" in sys.argv:
        return self_test()
    if "--observe" in sys.argv:
        at = sys.argv.index("--observe")
        print(f"{observe(*(float(a) for a in sys.argv[at + 1:at + 4])):.3f}")
        return 0
    if "--rate" in sys.argv:
        print(f"{rate():.3f}")
        return 0
    if "--width" in sys.argv:
        hours = float(sys.argv[sys.argv.index("--width") + 1])
        print(width(pct_left(), hours))
        return 0
    if "--window-hours" in sys.argv:
        print(f"{window_hours(pct_left()):.1f}")
        return 0
    print(f"{pct_left():.0f}% of the weekly window is unspent; at {rate():.2f}%/h "
          f"per run it needs {window_hours(pct_left()):.1f}h at width {CAP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
