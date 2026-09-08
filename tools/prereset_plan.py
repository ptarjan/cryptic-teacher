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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weekly_usage  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def state_dir():
    """Where the measured constants live: the CHECKOUT, not whichever worktree.

    The burn annotates in a throwaway worktree and measures the yield there, but
    the decision the yield exists for — when to start spending — is taken in the
    checkout, hours earlier, by an hourly fire that never sees the worktree. Kept
    beside the code that read them, the measurements are written where nothing
    reads them and read where nothing wrote them: on 2026-09-08 the worktree had
    measured 8.4 while the start gate ran all week on the seeded 12.6, started a
    third of a week too late, and could not reach 100% however wide it ran.

    A worktree's .git is a FILE naming its gitdir under the checkout's
    .git/worktrees/; the checkout is the path in front of that. Read rather than
    shelled out to: this is called several times a wave.
    """
    dotgit = REPO / ".git"
    try:
        if dotgit.is_file():
            head = dotgit.read_text().strip()
            marker = "/.git/worktrees/"
            if head.startswith("gitdir:") and marker in head:
                return Path(head.split(":", 1)[1].strip().split(marker)[0])
    except OSError:
        pass
    return REPO


STATE = state_dir()
RATE_FILE = STATE / ".prereset_rate"
YIELD_FILE = STATE / ".prereset_yield"
YIELD_LOG = STATE / ".prereset_yield_log"

SESSION_HOURS = 5.0

# Weekly percentage-points that one fully-spent five-hour window is worth.
# Only a seed: a real .prereset_yield in the checkout beats it within one wave.
# It was 12.6, measured from ~7000 paired samples over 2026-08-08..23, and that
# is no longer what a window is worth — four clean saturated windows measured
# 16.0, 15.1 and 15.2 on 2026-09-01 against 9.0 on 2026-09-08, so the number has
# moved and a seed that reads high is the expensive direction: it under-counts
# the windows the remainder needs and starts the burn too late to spend it.
SEED_YIELD = 8.4

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

# Measured yields kept, and how long one stays worth believing. Both are about
# the ACCOUNTING behind the meters, which is not ours to read: what a window is
# worth has moved once already without anything changing on this side, so a
# reading is evidence about the fortnight it was taken in and not about the job.
# Twelve is a burn's worth of waves plus the burn before it.
YIELD_HISTORY = 12
YIELD_STALE_DAYS = 14.0

# These runs sit waiting on the API almost the whole time, so a spare one costs a
# process, not a core. The cap is here to bound the fan-out, not to ration, so it
# has to sit above the widest wave the arithmetic can honestly ask for: a whole
# window's quota pulled through the shortest stub the tiling leaves. At 8 it did
# not. Eight in flight empty a window in 1.7h, the tiling routinely leaves less
# than that, and every point still on a window at its turnover is gone — so the
# bound was rationing the one window whose contents cannot be spent later.
CAP = int(os.environ.get("PARALLEL_MAX", 14))

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


def yield_log():
    """Every measured yield still on file, oldest first, as (unix time, points)."""
    rows = []
    try:
        for line in YIELD_LOG.read_text().splitlines():
            when, sample = line.split()[:2]
            rows.append((float(when), float(sample)))
    except (OSError, ValueError):
        return []
    return rows


def log_yield(sample):
    """Record one measurement, keeping the last YIELD_HISTORY of them.

    The blend alone cannot say whether the last four readings agreed, and that
    is the question planning turns on. Kept as a file rather than a running
    statistic because a spread is only visible in the samples themselves.
    """
    rows = yield_log() + [(time.time(), sample)]
    try:
        YIELD_LOG.write_text(
            "".join(f"{t:.0f} {y:.3f}\n" for t, y in rows[-YIELD_HISTORY:]))
    except OSError:
        pass


def pessimistic_yield(samples, blended, now):
    """What to PLAN with, given every recent measurement and the blend.

    Pure, so the self-test can hand it a history instead of a filesystem.

    The blend is what a window most likely returns; this is what it might. They
    differ because the accounting behind the meters is not ours to read and has
    moved without notice: three saturated windows on 2026-09-01 measured 15-16
    weekly points each, the same job on 2026-09-08 measured 9, and nothing on
    this side changed. Planning on the likely number cost a third of a week.

    Which way to be wrong is not symmetric. Starting too early costs nothing —
    the gate stands down whenever it is ahead of the edge, and the windows it
    opened were going to expire unspent — while starting too late cannot be
    recovered at any width, because a five-hour window cannot be made worth more
    than one five-hour window. So plan on the worst recent reading rather than
    the average of them, and never above the blend.

    A reading nobody has refreshed in YIELD_STALE_DAYS is not evidence about
    this week. With none left there is nothing to be pessimistic WITH, so fall
    back to the lower of the blend and the seed.
    """
    fresh = [y for when, y in samples if now - when <= YIELD_STALE_DAYS * 86400]
    return min(min(fresh), blended) if fresh else min(blended, SEED_YIELD)


def planning_yield():
    """The yield every start decision uses. See pessimistic_yield."""
    return pessimistic_yield(yield_log(), session_yield(), time.time())


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
    sample = 100.0 * weekly_climb / session_climb
    log_yield(sample)
    return _blend(session_yield(), sample, YIELD_FILE)


def stub_worth(hours, y, cap=None):
    """What a part-window of `hours` returns: a WHOLE window if it can be drained.

    A five-hour window is a quota, not a schedule. At full width the quota goes
    in 100 / (CAP * SESSION_PTS_PER_RUN_HOUR) hours, so any stub longer than
    that is worth the whole window and a shorter one is worth what full width
    can pull through it. Pro-rating a stub by hours/5 is what makes the last
    piece of a week look worthless.
    """
    cap = CAP if cap is None else cap
    return min(100.0, max(0.0, hours) * cap * SESSION_PTS_PER_RUN_HOUR) / 100.0 * y


def reachable(hours_until_reset, s_pct=None, s_hours=None, y=None, cap=None):
    """Weekly points still reachable before the WEEKLY reset, at this phase.

    The five-hour windows do not divide the hours until the weekly reset,
    because they do not line up with it. They tile forward from whenever the
    OPEN one turns over, and the weekly reset lands wherever it lands — on
    2026-09-08 it landed 1.0h into a window, so the hours-until-reset divided by
    five claimed 2.7 windows where the tiling offered two whole ones and a stub.
    Which way that lands is worth up to a whole window either way, so it is
    counted rather than assumed:

      - what is left on the OPEN window, as much of it as full width can pull
        through the hours before it turns over;
      - one whole window for each that fits entirely before the reset;
      - the trailing stub, at stub_worth().
    """
    y = planning_yield() if y is None else y
    cap = CAP if cap is None else cap
    if s_pct is None:
        s_pct = weekly_usage.usage_pct("session")
    if s_hours is None:
        # (hours, estimated?) — an estimated turnover still tiles correctly; it
        # only shifts where the boundaries fall by minutes.
        s_hours = weekly_usage.resets_in_hours("session")[0]
    # No reading, no window open, or one that claims more than five hours left:
    # assume a whole one, which is what a job that has been idle actually gets.
    s_hours = SESSION_HOURS if not s_hours else min(float(s_hours), SESSION_HOURS)
    s_pct = 0.0 if s_pct is None else float(s_pct)

    left = max(0.0, hours_until_reset)
    open_hours = min(s_hours, left)
    room = max(0.0, 100.0 - s_pct)
    got = min(room, open_hours * cap * SESSION_PTS_PER_RUN_HOUR) / 100.0 * y
    rest = left - open_hours
    whole = int(rest // SESSION_HOURS)
    got += whole * y + stub_worth(rest - whole * SESSION_HOURS, y, cap)
    return min(got, 100.0)


def windows(pct_left, y=None):
    """Five-hour windows needed to spend what is left of the week.

    Counted at the PLANNING yield, not the blended one: this number is only ever
    asked in order to decide when to start, and the cost of asking for a window
    that turns out not to have been needed is that it stands down. Everything
    that sizes a wave rather than starting one stays on the blend, where reading
    low would narrow the wave and leave the window short.
    """
    y = planning_yield() if y is None else y
    return max(0, min(MAX_WINDOWS, math.ceil(pct_left / max(y, 1e-6))))


def window_hours(pct_left, y=None):
    """How close to the reset spending should begin, in hours.

    Zero when nothing is left, which is the right answer: the gate compares the
    hours until reset against this, and no positive number of hours is ever
    within zero, so a spent week never opens it.
    """
    return windows(pct_left, y) * SESSION_HOURS


def start_hours(pct_left, reserve_pct=0.0, y=None):
    """How close to the reset spending must begin, given what each window keeps.

    window_hours() assumes every window it opens is spent to the last point.
    That is only true once the reserve has been dropped: while it is held each
    window delivers (100 - reserve)% of what it is worth, so the same remainder
    needs proportionally more windows and the job has to start proportionally
    earlier. A reserve is affordable exactly when it was paid for in windows up
    front — held from a start time that did not budget for it, it is not a
    courtesy, it is the week landing short by whatever was held back.
    """
    keep = max(0.05, 1.0 - reserve_pct / 100.0)
    return window_hours(pct_left / keep, y)


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


# Points of the five-hour meter that one run in flight burns per hour, measured
# off that meter directly. Not derived from .prereset_rate and .prereset_yield:
# those are blended estimates in WEEKLY points, and a rate that reads high sizes
# every wave down, which is the one direction a job that exists to spend the
# remainder must never fail in.
SESSION_PTS_PER_RUN_HOUR = 7.5


def fill_width(s_pct=None, s_hours=None, weekly_hours=None, cap=None):
    """Runs in flight needed to empty the CURRENT five-hour window in time.

    In time for WHICHEVER COMES FIRST, its own turnover or the weekly reset. The
    two are not the same deadline and the last window of a burn is always the
    one where they differ: on 2026-09-08 the final window opened 1.0h before the
    weekly reset, and pacing its quota over the five hours it nominally had
    would have spent a fifth of it and let the rest expire with the week.

    width() paces the WEEK: it gives each window one window's worth of weekly
    yield and lets the clock take five hours over it. That is right while more
    windows remain than the remainder needs. It is wrong the moment fewer do,
    because a five-hour window that turns over with room on it is gone for
    nothing, and then the only question is whether this one empties in time.
    """
    if s_pct is None:
        s_pct = weekly_usage.usage_pct("session")
    if s_hours is None:
        # (hours, estimated?) — the estimate is fine here: it only ever sizes a
        # wave, and a wave sized against a slightly wrong turnover is still spent.
        s_hours = weekly_usage.resets_in_hours("session")[0]
    if weekly_hours is not None and s_hours is not None:
        s_hours = min(s_hours, weekly_hours)
    cap = CAP if cap is None else cap
    room = 100.0 - s_pct
    if room <= 0 or s_hours is None or s_hours <= 0:
        return 1
    return max(1, min(cap, math.ceil(room / (s_hours * SESSION_PTS_PER_RUN_HOUR))))


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


def behind(hours_until_reset, pct, y=None, reserve_pct=0.0, s_pct=None,
           s_hours=None, cap=None):
    """Is this the last moment at which the remainder is still reachable?

    Two answers, and spending starts on either. start_hours() counts in whole
    five-hour windows and never asks where their edges fall; reachable() counts
    the tiling in front of us, which can be worth up to a window less than the
    division claimed. Taking the earlier of the two is the only safe way to
    combine them: a start that was not needed stands down again on the next
    fire, and a start that came late cannot be recovered at any width.
    """
    keep = max(0.05, 1.0 - reserve_pct / 100.0)
    if hours_until_reset <= start_hours(pct, reserve_pct, y):
        return True
    return reachable(hours_until_reset, s_pct, s_hours, y, cap) * keep <= pct


def pct_left():
    return max(0.0, 100.0 - weekly_usage.usage_pct("weekly"))


def self_test():
    """The two decisions, at the sizes that actually happen.

    Both were wrong in the same direction before this file existed, so the cases
    that matter are the big remainders: a job that spends everything when 3% is
    left and nothing when 70% is has still wasted the whole point.
    """
    # Fixture values, not the seeds: every expectation below is hand-computed
    # against these, so re-measuring a seed must not silently rewrite what the
    # tables assert. Change one of these and you owe the whole column again.
    Y, R = 12.6, 1.1
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
    reserves = [
        # hours until reset, pct_left, reserve pct -> should we be spending?
        # The reserve buys its own windows: 69% at 75% of each window needs
        # eight of them where 69% at all of it needs six.
        (68, 69, 25, False),    # Monday, either way: eight windows still fit
        (40, 69, 25, True),     # the reserve edge — start here or it is unpaid
        (35, 69, 0, False),     # the full-spend edge is still five hours off...
        (30, 69, 0, True),      # ...and here it is: from now the window goes whole
        (4, 1, 25, True),       # the last window; no reserve can change that
    ]
    # The tiling tables are threaded a cap of 8 rather than reading CAP: what
    # they check is that a stub is priced as a quota and not as a schedule, and
    # that answer must not change the next time the fan-out bound moves.
    stubs = [
        # hours of stub -> weekly points it can still return, at Y and 8 wide
        (0.0, 0.0),         # no time at all
        (1.0, 0.6 * Y),     # full width pulls 60 session points through an hour
        (2.0, Y),           # past the drain time a stub is a whole window...
        (5.0, Y),           # ...and never more than one, however long it runs
    ]
    tilings = [
        # hours to the weekly reset, session % spent, hours to its turnover
        #   -> weekly points still reachable, at Y
        (13.6, 38, 2.57, 40.80),  # 2026-09-08: two whole windows and a 1.0h stub
        (13.6, 0, 5.0, 3 * Y),    # the same hours, edges aligned: three windows
        (30, 0, 5.0, 6 * Y),      # six windows, every edge landing square
        (1.0, 100, 0.5, 3.78),    # this window spent, the next one half alive
    ]
    phases = [
        # hours to reset, pct left, session % spent, hours to turnover -> spend?
        # Same hour, same remainder, and the answer turns on where the edges
        # fall: aligned it still fits in five windows, misaligned the last one
        # is a 1.1h stub and this is the last hour the week is reachable at all.
        (26, 63, 100, 4.9, True),
        (26, 63, 0, 5.0, False),
    ]
    plans = [
        # (days ago, measured yield)..., blend -> what to plan with
        # The 2026-09-08 shift: three windows agreeing at 15-16 do not outvote
        # one recent 9, because being early is free and being late is the week.
        ([(0.5, 9.0), (7, 15.1), (7, 16.0)], 12.0, 9.0),
        ([(0.5, 15.0)], 9.0, 9.0),          # never above the blend
        ([(30, 15.0)], 12.0, SEED_YIELD),   # every reading stale: back to the seed
        ([], 12.0, SEED_YIELD),             # nothing measured yet
        ([], 6.0, 6.0),                     # a blend under the seed is still the cap
    ]
    fills = [
        # five-hour meter %, hours left in the window -> runs needed to empty it
        (14, 3.3, 4),       # the 2026-09-08 shape: paced width said 1 all window
        (0, 5.0, 3),        # a fresh window, filled from the start
        (90, 2.0, 1),       # nearly full already: one at a time finishes it
        (100, 1.0, 1),      # no room left: never widen for a window that is done
        (50, 0.0, 1),       # the turnover is here; a wider wave cannot land
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
    for s_pct, s_hours, want in fills:
        got = fill_width(s_pct, s_hours)
        if got != want:
            print(f"FAIL fill {s_pct}% five-hour with {s_hours}h left: "
                  f"{got} (want {want})", file=sys.stderr)
            bad += 1
    for hours, pct, res, want in reserves:
        got = behind(hours, pct, Y, res, s_pct=0.0, s_hours=SESSION_HOURS)
        if got != want:
            print(f"FAIL behind at {hours}h, {pct}% left, {res}% reserved: "
                  f"{got} (want {want})", file=sys.stderr)
            bad += 1
    for hours, want in stubs:
        got = stub_worth(hours, Y, cap=8)
        if abs(got - want) > 1e-9:
            print(f"FAIL stub of {hours}h: {got:.2f} (want {want:.2f})", file=sys.stderr)
            bad += 1
    for left, s_pct, s_hours, want in tilings:
        got = reachable(left, s_pct, s_hours, Y, cap=8)
        if abs(got - want) > 0.01:
            print(f"FAIL reachable in {left}h at session {s_pct}% "
                  f"turning over in {s_hours}h: {got:.2f} (want {want})", file=sys.stderr)
            bad += 1
    for hours, pct, s_pct, s_hours, want in phases:
        got = behind(hours, pct, Y, s_pct=s_pct, s_hours=s_hours, cap=8)
        if got != want:
            print(f"FAIL behind at {hours}h, {pct}% left, session {s_pct}% "
                  f"turning over in {s_hours}h: {got} (want {want})", file=sys.stderr)
            bad += 1
    now = time.time()
    for samples, blended, want in plans:
        aged = [(now - days * 86400, y) for days, y in samples]
        got = pessimistic_yield(aged, blended, now)
        if abs(got - want) > 1e-9:
            print(f"FAIL planning yield from {samples} blended {blended}: "
                  f"{got} (want {want})", file=sys.stderr)
            bad += 1
    for weekly, session, want in yields:
        got = yield_sample_ok(weekly, session)
        if got != want:
            print(f"FAIL yield sample weekly +{weekly} session +{session}: "
                  f"{'believed' if got else 'refused'}", file=sys.stderr)
            bad += 1
    for hours, left, want in schedule:
        got = behind(hours, left, Y, s_pct=0.0, s_hours=SESSION_HOURS)
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
    n = (len(starts) + len(widths) + len(schedule) + len(endgames) + len(fills)
         + len(reserves) + len(plans) + len(stubs) + len(tilings) + len(phases))
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
    if "--state-dir" in sys.argv:
        print(STATE)
        return 0
    if "--rate" in sys.argv:
        print(f"{rate():.3f}")
        return 0
    if "--yield" in sys.argv:
        print(f"{session_yield():.3f}")
        return 0
    if "--planning-yield" in sys.argv:
        print(f"{planning_yield():.3f}")
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
        paced = width(pct_left(), hours)
        # A floor, never a ceiling. Pacing may ask for more runs than filling the
        # window needs; it may not ask for a window to turn over with room on it
        # once the windows themselves are the scarce thing.
        if behind(hours, pct_left()):
            paced = max(paced, fill_width(weekly_hours=hours))
        print(paced)
        return 0
    if "--behind" in sys.argv:
        # "yes"/"no" on stdout rather than an exit status: a traceback also exits
        # non-zero, and the caller must not read a crash as "stop spending" on the
        # one night the remainder exists to be spent.
        at = sys.argv.index("--behind")
        args = sys.argv[at + 1:at + 3]
        hours = float(args[0])
        res = float(args[1]) if len(args) > 1 and not args[1].startswith("-") else 0.0
        print("yes" if behind(hours, pct_left(), reserve_pct=res) else "no")
        return 0
    if "--windows" in sys.argv:
        print(windows(pct_left()))
        return 0
    if "--window-hours" in sys.argv:
        at = sys.argv.index("--window-hours")
        args = sys.argv[at + 1:at + 2]
        res = float(args[0]) if args and not args[0].startswith("-") else 0.0
        print(f"{start_hours(pct_left(), res):.1f}")
        return 0
    left = pct_left()
    seen = len(yield_log())
    print(f"{left:.0f}% of the weekly window is unspent; measured at "
          f"{session_yield():.1f} points per five-hour window and planned at "
          f"{planning_yield():.1f} (worst of {seen} reading(s)), that needs "
          f"{windows(left)} of them, so start {window_hours(left):.0f}h out "
          f"at width {width(left, window_hours(left))}. "
          f"From here the windows in front of the weekly reset are worth "
          f"{reachable(weekly_usage.resets_in_hours('weekly')[0]):.0f} points")
    return 0


if __name__ == "__main__":
    sys.exit(main())
