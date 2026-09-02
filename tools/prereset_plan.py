#!/usr/bin/env python3
"""How early the pre-reset backfill should start, and how wide it should run.

Unspent weekly quota does not roll over: whatever is left when the window turns
over is gone. tools/prereset_backfill.sh exists to spend it, and for its first
weeks it could not — it started two hours before the reset and ran one
annotation at a time, which is a few puzzles against a remainder measured in
tens of percent.

The thing that actually limits how fast the weekly remainder can be spent is the
FIVE-hour window. Saturate it and everything is locked out until it turns over,
however much weekly quota is still sitting there, so the week's remainder can
only be spent a five-hour window at a time. That makes the plan a count rather
than a rate:

    windows = ceil(percent left / yield)     yield = weekly points one full
    start   = windows * 5 hours              five-hour window is worth

This is a trailing edge, not a start time. The backfill re-asks it before every
wave, so spending shrinks the remainder, a smaller remainder needs fewer windows,
and the edge slides back toward the reset until the job is ahead of it and stands
down. Real work spending the same quota moves it the same way. The job therefore
takes only what the week was going to lose, as late as it can still take it.

`yield` is measured, not assumed. Both meters bill the same underlying spend
against different denominators, so the ratio between them is a constant of the
plan and shows up in any stretch where neither meter is pinned — no saturated
window is needed to measure what a saturated window is worth. Pooled over two
weeks of five-minute samples it came to 79 weekly points per 629 session points:

    a full five-hour window = 12.6 weekly points, or 8 such windows in a week

Width is the second question, and it is about filling ONE window rather than the
week: enough runs in flight to reach the session cap inside the five hours, so
that the rest of the window is spent waiting out a lockout that has already
bought everything it could.

    tools/prereset_plan.py --window-hours          # start when reset is this close
    tools/prereset_plan.py --windows               # five-hour windows that implies
    tools/prereset_plan.py --width 6.5             # runs to keep in flight
    tools/prereset_plan.py --observe 4.2 1.5 3     # climb, hours, width
    tools/prereset_plan.py --observe-yield 4.2 33  # weekly climb, session climb
    tools/prereset_plan.py --self-test

Reads only, except the --observe flags, which write .prereset_rate/.prereset_yield.
"""
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weekly_usage  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RATE_FILE = REPO / ".prereset_rate"
YIELD_FILE = REPO / ".prereset_yield"

SESSION_HOURS = 5.0

# Weekly percentage-points that one fully-spent five-hour window is worth.
# Measured from ~7000 paired samples over 2026-08-08..23 (see the docstring), and
# it is a genuine measurement rather than a floor: it comes from stretches where
# neither meter was pinned, so nothing is censored out of it.
SEED_YIELD = 12.6

# Percent of the weekly window ONE annotation run burns per hour. A FLOOR, not a
# measurement, and deliberately used as one. The two clean runs on record
# (2026-08-12, 2026-08-19) both annotated at ~3.25 puzzles an hour and both were
# pinned at a displayed 100% for most of that hour, so the true cost per puzzle is
# censored from above. Under-guessing it only makes a wave wider than it needed to
# be, which saturates the window sooner and naps longer — the same quota either
# way.
SEED_RATE = 1.1

# Session points a wave must move before its ratio is worth believing. Both
# meters are read as whole percentages, so a wave that moved the session meter
# two points and the weekly meter one reports a window worth 50 — four times
# anything ever measured — and _blend gives that half the weight. Two of those
# in a row is how .prereset_yield reached 29.5 by 2026-09-02, which asked for
# two windows where six were needed and left 46% of the week to expire. The
# denominator has to be big enough that a rounding error is not the reading.
MIN_YIELD_SAMPLE = 10

# These runs sit waiting on the API almost the whole time, so a spare one costs a
# process, not a core. The cap is here to bound the fan-out, not to ration.
CAP = int(os.environ.get("PARALLEL_MAX", 8))

# A guard against a corrupted yield, not a policy. The policy is the window count
# itself: at the measured yield a completely unspent week asks for eight windows,
# forty hours, and never more — so this only binds if .prereset_yield goes wrong.
MAX_WINDOWS = int(float(os.environ.get("PRERESET_MAX_HOURS", 7 * 24)) / SESSION_HOURS)

# Planning deliberately assumes we are slower than measured. Guessing high wastes
# quota — the failure this whole file exists to fix — while guessing low costs an
# earlier start inside a window that was going to evaporate anyway.
SAFETY = 0.7
# Margin on the computed endgame start, and the guards either side of it. The
# measurement is good to about one wave, so the margin is one wave's worth. The
# ceiling is a sanity guard on a corrupt rate, not a policy — no reserve is
# worth taking half a window off somebody to spend.
ENDGAME_SLACK = 1.25
ENDGAME_FLOOR, ENDGAME_CEIL = 25, 120


def _read(path, seed):
    try:
        got = float(path.read_text().split()[0])
        return got if got > 0 else seed
    except (OSError, ValueError, IndexError):
        return seed


def rate():
    """Percent of the weekly window one annotation run burns per hour."""
    return _read(RATE_FILE, SEED_RATE)


def session_yield():
    """Weekly percentage-points one fully-spent five-hour window is worth."""
    return _read(YIELD_FILE, SEED_YIELD)


def _blend(old, new, path):
    """Halve toward the new reading rather than replacing.

    A wave that overlapped a long interactive session reads as a burn this job
    cannot reproduce alone, and one such wave should not set the plan for the
    next month.
    """
    got = (old + new) / 2
    path.write_text(f"{got:.3f}\n")
    return got


def observe(climb, hours, width_):
    """Fold one wave's achieved burn into the per-run hourly rate."""
    if hours <= 0 or width_ <= 0 or climb <= 0:
        return rate()
    return _blend(rate(), climb / (hours * width_), RATE_FILE)


def yield_sample_ok(weekly_climb, session_climb):
    """Is this wave's pair of climbs worth dividing? Pure, so self_test can ask."""
    return weekly_climb > 0 and session_climb >= MIN_YIELD_SAMPLE


def observe_yield(weekly_climb, session_climb):
    """Fold one wave's two meters into the per-window yield.

    Skipped unless both meters moved: a pinned session meter reads as no climb
    while weekly keeps rising, which would report a window as worth far more
    than it is, and a session window that reset mid-wave reads as a fall.
    Skipped too when the session meter barely moved, because dividing by a
    number that is mostly rounding error is not a measurement — see
    MIN_YIELD_SAMPLE. What is left is the unpinned stretches with a real
    denominator, which is exactly where the ratio is honest.
    """
    if not yield_sample_ok(weekly_climb, session_climb):
        return session_yield()
    return _blend(session_yield(), 100.0 * weekly_climb / session_climb, YIELD_FILE)


def windows(pct_left, y=None):
    """Five-hour windows needed to spend what is left of the week."""
    y = session_yield() if y is None else y
    return max(0, min(MAX_WINDOWS, math.ceil(pct_left / max(y, 1e-6))))


def window_hours(pct_left, y=None):
    """How close to the reset spending should begin, in hours.

    Zero when nothing is left, which is the right answer: the gate compares the
    hours until reset against this, and no positive number of hours is ever
    within zero, so a spent week never opens it.
    """
    return windows(pct_left, y) * SESSION_HOURS


def width(pct_left, hours_left, r=None, y=None):
    """How many annotation runs to keep in flight for the next wave.

    Sized to fill the CURRENT five-hour window, not the whole remainder: past
    the session cap nothing else can be bought at any width, and the runs that
    would have bought it fail instead.
    """
    r = rate() if r is None else r
    # Threaded, not read from the file: a self-test whose answer depends on what
    # last night's waves happened to measure is not a test of anything.
    y = session_yield() if y is None else y
    goal = min(y, pct_left)
    hours = min(SESSION_HOURS, hours_left)
    if hours <= 0 or goal <= 0:
        return 1
    return max(1, min(CAP, math.ceil(goal / (hours * r * SAFETY))))


def session_rate(width_=1, r=None, y=None):
    """Five-hour meter points burned per hour at this width.

    `rate` is measured against the WEEKLY meter and `session_yield` is what a
    whole five-hour window is worth on that same meter, so their ratio converts
    one to the other without a second measurement.
    """
    r = rate() if r is None else r
    y = session_yield() if y is None else y
    return r * width_ * 100.0 / max(y, 1e-6)


def endgame_min(reserve_pct, width_=1, r=None, y=None):
    """Minutes before the reset at which the held-back reserve starts spending.

    Sized so the reserve runs out AS the window turns over. Both ways of being
    wrong cost something real and they are not symmetric in kind: too late
    strands quota on a window that is about to expire, too early hands the job
    a window Paul is still trying to use. Paul would rather overspend than
    strand any, hence the slack — but only a slack, because a fixed 90 minutes
    ran a window to 100% a full hour before its reset and that hour was his.
    """
    per_h = session_rate(width_, r, y)
    if per_h <= 0:
        return ENDGAME_CEIL
    mins = math.ceil(reserve_pct / per_h * 60 * ENDGAME_SLACK)
    return int(max(ENDGAME_FLOOR, min(ENDGAME_CEIL, mins)))


def behind(hours_until_reset, pct, y=None):
    """Is the remainder too big to still fit in the windows that are left?

    The whole no-pre-spend rule is this one comparison, so it lives here with the
    rest of the arithmetic and gets self-tested, rather than being an awk line in
    the shell that nobody can exercise without spending a night of inference.
    """
    return hours_until_reset <= window_hours(pct, y)


def pct_left():
    return max(0.0, 100.0 - weekly_usage.usage_pct("weekly"))


def self_test():
    """The two decisions, at the sizes that actually happen.

    Both were wrong in the same direction before this file existed, so the cases
    that matter are the big remainders: a job that spends everything when 3% is
    left and nothing when 70% is has still wasted the whole point.
    """
    Y, R = SEED_YIELD, SEED_RATE
    starts = [
        # pct_left, yield -> hours before the reset to start
        (69, Y, 30.0),      # the live remainder: six windows
        (100, Y, 40.0),     # a wholly wasted week, and the most this can ever ask
        (3, Y, 5.0),        # a sliver still gets a whole window to spend it in
        (0, Y, 0.0),        # nothing left: the gate never opens
        (69, 0.01, MAX_WINDOWS * SESSION_HOURS),   # corrupt yield hits the guard
    ]
    widths = [
        # pct_left, hours_left -> runs in flight
        (69, 30, 4),        # plenty of room: fill one window, no more
        (3, 5, 1),          # nearly spent: one run, the old behaviour
        (12, 1, CAP),       # last hour with points left: as wide as allowed
        (0, 5, 1),          # nothing left: never zero or negative
    ]
    schedule = [
        # hours until reset, pct_left -> should we be spending right now?
        (68, 69, False),    # Monday, most of the week unspent: six windows fit, wait
        (30, 69, True),     # the trailing edge of those six windows
        (28, 57, False),    # a wave has been spent, five windows now fit: stand down
        (25, 57, True),     # ...and its edge arrives three hours later
        (4, 1, True),       # the last window, whatever is left in it
        (4, 0, False),      # nothing left: never spend, however close the reset
    ]
    endgames = [
        # reserve pct, width -> minutes before the reset to start spending it
        (25, 4, 54),        # the live shape: a reserve that needs most of an hour
        (25, 8, 27),        # wide enough to drain it fast, so start late
        (25, 1, 120),       # one at a time cannot drain 25 points; guard, not plan
        (0, 4, 25),         # no reserve to hand back: never zero, never negative
    ]
    yields = [
        # weekly climb, session climb -> is the wave worth dividing?
        (3, 38, True),      # a real wave, the shape every honest reading has
        (1, 2, False),      # a ratio of two rounding errors, and it reads as 50
        (3, 0, False),      # session pinned at 100 while weekly kept climbing
        (3, -20, False),    # the session window turned over mid-wave
        (0, 38, False),     # weekly did not move: nothing to attribute
    ]
    bad = 0
    for weekly, session, want in yields:
        got = yield_sample_ok(weekly, session)
        if got != want:
            print(f"FAIL yield sample weekly +{weekly} session +{session}: "
                  f"{'believed' if got else 'refused'}", file=sys.stderr)
            bad += 1
    for hours, left, want in schedule:
        got = behind(hours, left, Y)
        if got != want:
            print(f"FAIL schedule {left}% with {hours}h to go: "
                  f"{'spend' if got else 'wait'} (want {'spend' if want else 'wait'})",
                  file=sys.stderr)
            bad += 1
    for left, y, want in starts:
        got = window_hours(left, y)
        if abs(got - want) > 0.05:
            print(f"FAIL start {left}% at yield {y}: {got:.2f}h (want {want})", file=sys.stderr)
            bad += 1
    for left, hours, want in widths:
        got = width(left, hours, R, Y)
        if got != want:
            print(f"FAIL width {left}% in {hours}h: {got} (want {want})", file=sys.stderr)
            bad += 1
    for reserve, wide, want in endgames:
        got = endgame_min(reserve, wide, R, Y)
        if got != want:
            print(f"FAIL endgame {reserve}% at width {wide}: {got}m (want {want})",
                  file=sys.stderr)
            bad += 1
    # Counted, not typed: a hand-written total goes stale the first time a case
    # is added and then reports a shrinking suite as a passing one.
    n = len(starts) + len(widths) + len(schedule) + len(endgames)
    print(f"prereset plan self-test FAILED: {bad} of {n}" if bad
          else f"prereset plan self-test: {n} cases pass")
    return 1 if bad else 0


def main():
    if "--self-test" in sys.argv:
        return self_test()
    if "--observe" in sys.argv:
        at = sys.argv.index("--observe")
        print(f"{observe(*(float(a) for a in sys.argv[at + 1:at + 4])):.3f}")
        return 0
    if "--observe-yield" in sys.argv:
        at = sys.argv.index("--observe-yield")
        print(f"{observe_yield(*(float(a) for a in sys.argv[at + 1:at + 3])):.3f}")
        return 0
    if "--rate" in sys.argv:
        print(f"{rate():.3f}")
        return 0
    if "--yield" in sys.argv:
        print(f"{session_yield():.3f}")
        return 0
    if "--endgame-min" in sys.argv:
        at = sys.argv.index("--endgame-min")
        args = sys.argv[at + 1:at + 3]
        reserve = float(args[0])
        wide = float(args[1]) if len(args) > 1 and not args[1].startswith("-") else 1
        print(endgame_min(reserve, wide))
        return 0
    if "--width" in sys.argv:
        hours = float(sys.argv[sys.argv.index("--width") + 1])
        print(width(pct_left(), hours))
        return 0
    if "--behind" in sys.argv:
        # "yes"/"no" on stdout rather than an exit status: a traceback also exits
        # non-zero, and the caller must not read a crash as "stop spending" on the
        # one night the remainder exists to be spent.
        hours = float(sys.argv[sys.argv.index("--behind") + 1])
        print("yes" if behind(hours, pct_left()) else "no")
        return 0
    if "--windows" in sys.argv:
        print(windows(pct_left()))
        return 0
    if "--window-hours" in sys.argv:
        print(f"{window_hours(pct_left()):.1f}")
        return 0
    left = pct_left()
    print(f"{left:.0f}% of the weekly window is unspent; at {session_yield():.1f} points "
          f"per five-hour window that needs {windows(left)} of them, so start "
          f"{window_hours(left):.0f}h out at width {width(left, window_hours(left))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
