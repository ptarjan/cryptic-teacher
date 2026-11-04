#!/usr/bin/env python3
"""How wide the pre-reset backfill runs, and in what order it takes the queue.

The job's goal is the paced meter spent to EXHAUSTED right at its reset (aim_hours):
quota left on a window when it turns over is gone, and quota spent early locks
the owner's rooms out until it turns over. Interactive bridge work comes first, so
the burn takes only what would otherwise be wasted. It keeps in flight the
width that would spend, evenly until the reset, what it has left
after the bridge's own projected spend (paced_need), and no more than the
machine has free once everything else on it is counted: memory over the size
of a run, and idle cores over a run's measured CPU.

The meter paced is the weekly one. The owner may also reset it by hand
MANUAL_RESETS times in any 30 days (the natural reset stays put), so the need's
deadline is not always the natural reset: reset_plan counts the manual resets
in usage-history.csv's trailing 30 days (a fall with resets_at unmoved), the
slots free now and those freeing before the natural reset, and spends one more
window of EXHAUSTED points per slot it uses, the last ending at the natural
reset. Under the staircase "no more than EXHAUSTED before the next slot frees"
it takes the taut string (the lowest top rate), uses the most slots whose top
rate the memory cap can spend, and paces to the first window's fill, moved out
of the owner's predicted night: tools/awake.py learns it from the times of his own
messages (23:00-07:00 Pacific when they are too few), and a message in the last
75 minutes says he is up now. Unless the meter is due full before his bedtime,
the burn is capped (overnight_cap) so that the bridge alone, at 1.5 times its
rate, could not take the meter past EXHAUSTED before he wakes: nothing locks
him out asleep. At RUSH_SPENT with a slot free it wakes the room once (held
until he is up) so he resets. The rates and the bridge's spend are in weekly
points. --rush is flat out.

The queue is backlog(): every un-annotated puzzle, those without all their
answers included (the burn solves them cold, then annotates them), and every
puzzle held as its clues alone (tools/clues_only.py), whose solve derives its
grid in tools/apply_solution.py as the nightly's does. Those rank by the same
rules as an index row: clues_only_rows() gives them one. Its order
is head_of_queue()'s: the puzzles a lockout cut off first, the hand requests,
then the series to finish off (finish_off_series: under FINISH_OFF unhinted
puzzles left, fewest left first; owner 10-22: "Can we finish off series who has
less than 200 unhinted puzzles first?"),
then the recent tier (recent_first: dated within a year of today, never
annotated first, then its redo work, newest first; owner 10-20: "puzzles newer
than a year should go first"), then the partly hinted ones (some clues hinted, some not; fewest clues missing
first; owner 10-15: "Partly hinted puzzles should be first"), then the nearly-done and small series' puzzles (small_series: those at least
NEARLY_DONE hinted whatever their size, then those under SMALL_SERIES known,
then filed; each tier fewest left to hint first, so a set completes soonest),
then the puzzles /showcase/ would pick
once annotated (showcase.wanted), then
each series' first puzzle (series.is_first_issue), then each series'
OLDEST_PER_SERIES oldest puzzles, oldest first, then the puzzles with a notable
tag (tools/puzzle_tags.py), then the indicator cover (tools/indicator_cover.py),
then the rest round-robin across the series, newest first inside each one.
Answered first (owner 10-21: "Should we do the ones with solutions first"): one
stable partition of all those pins, after the lockout cut-offs and hand
requests, which stay at the very front. The puzzles with every answer keep
their order; the cold solves and clues-only ones (cold solves fail about 86%)
leave the head and go behind the whole queue. The round-robin rest gets the
same partition: the final queue is the lockout cut-offs and hand requests, then
every answered puzzle (pins, the indicator cover, then the round-robin rest),
then every cold or clues-only one (the formerly pinned in pin order, then the
rest in round-robin order). The cover and the shape tier never reorder that tail.

    tools/prereset_plan.py [--may-pause] --width [CURRENT]  # runs to keep in flight
    tools/prereset_plan.py --backlog "ANNOTATE_BLOCKED" "SOLVE_BLOCKED"  # the queue
    tools/prereset_plan.py --unsolved ID      # exit 0 when ID lacks any answer
    ids | tools/prereset_plan.py --cover-first "PINNED"   # the queue, cover first
    tools/prereset_plan.py --rush [MINUTES]   # burn flat out until the weekly meter hits 100% or its reset (MINUTES is optional, unused)
    tools/prereset_plan.py --weekly           # pace the weekly meter, a window per manual reset (the default)
    tools/prereset_plan.py --resets           # the manual resets free before the natural one, the plan, and his nights
    tools/prereset_plan.py --natural-only [UNTIL_EPOCH]  # plan no manual resets until then (default: the natural reset)
    tools/prereset_plan.py --self-test
"""
import datetime as dt
import itertools
import json
import os
import re
import sys
import time
from pathlib import Path

import awake
import mem_gate
import series
import weekly_usage

REPO = Path(__file__).resolve().parent.parent

# Running wider than a need only spends its window early, which locks the
# account out until that window's reset, so the needs set the width. Each aims
# at its reset itself, rounded rather than rounded up: re-read at every
# checkpoint, a need corrects for the per-run rate's interval-to-interval noise
# as the reset nears. A reset the meter puts in the past means the window has
# turned over since it was read: the whole of a fresh one is left to spend.
WINDOW_HOURS = 7 * 24.0
# The level the paced meter's need aims at: prereset_backfill.sh stops at it on
# the weekly meter, and exports its own value.
EXHAUSTED = float(os.environ.get("EXHAUSTED") or 99)
# The need aims at the reset itself (owner 2026-10-01: "finish much closer to
# the hour in case I need some"; 10-16: "the burn should aim for being done
# right at the time not so early"). A margin before the reset spent the window
# early; what it guarded is feasibility, which the width already answers: when
# the machine is short width_for runs at the cap from now, and the need keeps
# rising as the hours shrink. Only AIM_MIN_H is kept, so the last checkpoint
# never divides by ~0.
AIM_MIN_H = 0.05
# The bridge's spend until the reset is projected at its mean rate.
# The width when neither the meter nor the last logged width can be read.
DEFAULT_WIDTH = 14
# The ceiling when memory cannot be read: ~7 GB of runs.
DEFAULT_CEILING = 28

# Memory kept free for the bridge and Docker, which share this box, and the size
# of one run when none of the burn's runs is in flight to measure.
MEM_HEADROOM_KB = 4 * 1024 * 1024
RUN_RSS_KB = 250 * 1024

# The CPU the burn may have is the cores everything else leaves idle. The burn
# is the process tree under prereset_backfill.sh, its claude runs at nice 19;
# its CPU is that tree's utime+stime+cutime+cstime, so runs that have exited
# and been reaped still count. Everything else /proc/stat calls busy is other
# load. Measured since the planner's previous call when that is CPU_SPAN_S old
# at most (one pool checkpoint is 300s), else over CPU_SAMPLE_S now.
CPU_SPAN_S = (10, 900)
CPU_SAMPLE_S = 2.0
CPU_STATE = ".prereset.cpu"
# `--rush` (owner 10-26 "burn your whole quota quickly and I can reset
# you", then "fit another seven day reset in before the Wednesday reset"): RUSH
# holds the weekly meter's reset epoch at arming. While it is armed and the
# weekly meter is under RUSH_TARGET the need is the memory cap (flat out, no cpu
# cap: burn runs are API-bound, about 0.1 core each; only a truly high load
# shrinks the pool, via load_cap). After the owner resets (the meter falls under
# RUSH_TARGET) it resumes flat out with nobody re-arming it. It disarms
# (width() deletes the file) only when the weekly reaches RUSH_TARGET or the
# weekly reset passes. The weekly meter reaching RUSH_SPENT wakes our room once
# per window (RUSH_SPENT_STAMP, cleared when the meter falls) so the owner can reset.
# Since 11-03 width() sets both switches itself (auto_rush, owner: "spend any
# resets we have so rush when we have one and don't when we don't"): a manual
# reset free arms RUSH, none free writes NATURAL_ONLY to the natural reset.
RUSH = ".prereset.rush"
NATURAL_ONLY = ".prereset.natural_until"  # epoch: until then plan no manual resets
RUSH_TARGET = 100.0
RUSH_SPENT = 99.0
RUSH_SPENT_STAMP = ".prereset.rush-spent-{}"
RUSH_ROOM = "cryptic-crosswords"
# The manual resets (owner 11-01: "Are we burning at the right rate now to make
# me use all my resets? Did you take into account the natural reset I get
# too?"). The owner may reset the weekly meter MANUAL_RESETS times in any trailing
# RESET_SPAN_S; a manual reset empties it but leaves the natural reset where it
# is. reset_plan paces the meter to EXHAUSTED once per reset free before the
# natural one, the last window ending at it, and RUSH_SPENT wakes our room
# then. No wake while he is asleep (tools/awake.py): fills aim outside his
# nights, and a meter full at night waits for the morning. PLAN_SHARE of the memory cap is the
# width counted on when choosing how many resets the machine can fill.
MANUAL_RESETS = 15
RESET_SPAN_S = 30 * 86400
MANUAL_DROP = 20.0
NATURAL_SLACK_S = 3600  # a drop this near resets_at is the natural reset
PLAN_SHARE = 0.8
# Resets never rushed into (11-03 17:30, the last of 15 left: "we don't want to need
# one"). A rush spends the meter to RUSH_TARGET flat out, at ~12 points an hour 24
# wide in Annotate, so with 11.6h to the natural reset it would lock every room out
# from ~22:00 ABT unless the last reset were spent. The last one is kept for an
# emergency; with only it free the burn paces to EXHAUSTED at the natural reset.
MANUAL_RESERVE = 1
PACIFIC = awake.PACIFIC
# Lockout safety (owner 11-01: "try to know when I'm awake so you don't lock me
# out when I'm sleeping"). Unless the plan fills the meter before his next
# night (tools/awake.py), the burn is capped so that, were it to stop, the
# bridge alone at NIGHT_BRIDGE_FACTOR times its measured rate would leave the
# meter NIGHT_GUARD points under EXHAUSTED when he wakes (or at the reset, if
# sooner): overnight_cap.
NIGHT_BRIDGE_FACTOR = 1.5
NIGHT_GUARD = 1.0
WAKE_SH = "/Users/pt/github/household/tools/wake.sh"

# The bridge's spend until the reset is its rate over the last SPEND_WINDOW_S:
# the weekly meter's rise in usage-history.csv, split between the burn and
# everything else by the tokens their transcripts record in the same span.
# A token is weighted by its list price: per token type relative to uncached
# input, times the model family's input price in $/MTok (an unknown family
# costs as Opus). The burn's own turns are the records whose cwd is this tree.
# Six hours, not one: a one-hour window read a short spike (18-27 points an
# hour) as the rate for the whole rest of the window, so the pacer found the
# bridge alone would reach 99%, gave the burn 0, and the quota went unspent
# (owner 2026-10-17: "Why aren't we burning").
SPEND_WINDOW_S = 6 * 3600
METER_STALE_S = 900
TOKEN_WEIGHT = {"input_tokens": 1.0, "cache_creation_input_tokens": 1.25,
                "cache_read_input_tokens": 0.1, "output_tokens": 5.0}
MODEL_WEIGHT = {"opus": 5.0, "sonnet": 3.0, "haiku": 1.0}
# The burn's per-run rate from the transcripts needs this many run-hours in
# the window, else the log's rate below stands.
RUN_HOURS_MIN = 0.25

# Weekly points one run in flight spends per hour. Measured off the burn's own
# meter lines in .prereset.log (see per_run_rate); this is the fallback when
# too few are readable.
PER_RUN_RATE = 0.3
# The meter line after_wave logs at every pool checkpoint:
#   weekly 33% -> 34% in 0.083h at width 12.40 (pool of 14)
# where the width is the runs in flight on average over the interval, measured.
METER_LINE = re.compile(r"weekly (\d+)% -> (\d+)% in ([\d.]+)h at width (\d+(?:\.\d+)?)")
# The width the burn last ran at: "--- pool of 14: ..." at every checkpoint.
WIDTH_LINE = re.compile(r"^--- pool of (\d+):")
RATE_LINES = 60
RATE_MIN_LINES = 10
# Runs in flight on average under which an interval says nothing about a run's rate.
MIN_RATE_WIDTH = 1.0
# 10-28 undershoot: the transcript split found 1.13 run-hours where the runs
# flew far longer, so it read a per-run rate 3x the meter lines'; the need came
# out 1. The transcript rate may be at most RATE_CAP_FACTOR times the log's
# rate, and width-1 intervals count.
RATE_CAP_FACTOR = 1.0


def ceiling(rushing=False):
    """The level the weekly need aims at and must stay under."""
    return RUSH_TARGET if rushing else EXHAUSTED


def rush_active(stamp, week_pct, now=None):
    """True while a rush is armed (RUSH holds the weekly reset epoch it ends
    at, still ahead) and the weekly meter is under RUSH_TARGET."""
    try:
        until = float(stamp)
    except (TypeError, ValueError):
        return False
    if until <= (time.time() if now is None else now):
        return False
    return week_pct is not None and week_pct < RUSH_TARGET


def rush_disarmed(stamp, week_pct, now):
    """True when an armed rush is over for good: the weekly meter is spent or
    its reset has passed. An unreadable stamp or meter keeps it."""
    try:
        return float(stamp) <= now or (week_pct is not None and week_pct >= RUSH_TARGET)
    except (TypeError, ValueError):
        return False


def rush_notify(home, name, pct, say, now=None, due=True, text=None, sleep=None):
    """Wake our room once per window when meter `name` reaches RUSH_SPENT and
    a reset is `due`; the stamp goes when it falls, so the next window wakes it
    again. While the owner is asleep (`sleep`, tools/awake.py) the wake waits (no
    stamp) for the morning."""
    mark = home / RUSH_SPENT_STAMP.format(name)
    if pct is None:
        return False
    if pct < RUSH_SPENT:
        mark.unlink(missing_ok=True)
        return False
    if not due or mark.exists() or quiet(time.time() if now is None else now, sleep):
        return False
    try:
        mark.write_text(f"{pct:g}\n")
    except OSError:
        return False
    say(text or f"The rush has spent the {name} meter ({pct:g}%): reset it to carry on. "
        f"The burn resumes by itself once it falls.")
    return True


def wake_room(text):
    import subprocess
    try:
        subprocess.run([WAKE_SH, "-q", "-c", RUSH_ROOM, text], timeout=60,
                       capture_output=True)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"rush: room not woken: {exc}", file=sys.stderr)


def per_run_rate(lines, last=RATE_LINES, least=RATE_MIN_LINES, min_width=MIN_RATE_WIDTH):
    """Weekly points per run-hour over the last `last` meter lines logged,
    PER_RUN_RATE under `least` usable ones. An interval whose meter fell crossed
    a reset and says nothing, so it is skipped, as is one with under `min_width`
    runs in flight on average: the rooms' own spend over almost no runs reads as
    an enormous per-run rate (10-23: 38% -> 79% in 3.55h at width 0.01 = 1,150 a
    run-hour, which held the need at 0 for hours with 41,864 puzzles queued)."""
    points = run_hours = 0.0
    meters = [m for m in map(METER_LINE.search, lines) if m][-last:]
    used = 0
    for m in meters:
        before, after, hours, width = int(m[1]), int(m[2]), float(m[3]), float(m[4])
        if after < before or hours <= 0 or width < min_width:
            continue
        points += after - before
        run_hours += hours * width
        used += 1
    if used < least or points <= 0:
        return PER_RUN_RATE
    return points / run_hours


def capped_rate(measured, log_rate):
    """The transcript-split burn rate, held to RATE_CAP_FACTOR times the meter
    lines' rate; the log's rate when there is no transcript one."""
    if not measured:
        return log_rate
    return min(measured, log_rate * RATE_CAP_FACTOR)


def paced_need(pct, hours_left, rate, bridge_rate):
    """Runs that would spend, by the weekly reset, what the meter has left up
    to EXHAUSTED after the bridge's projected spend, 0 when the bridge alone
    spends it. pct and hours_left are the weekly meter's; rate (per run-hour)
    and bridge_rate (an hour) are weekly points. A reset already passed is a
    fresh week, all of it left. The spend is due at the reset (aim_hours); the
    bridge's is projected to the reset at its mean; a need over the machine's
    caps is returned as is, width_for caps it. None when any input is missing
    or unusable."""
    try:
        if pct is not None and hours_left <= 0:
            pct, hours_left = 0, WINDOW_HOURS
        if rate <= 0:
            return None
        hours = aim_hours(hours_left)
        bridge = max(0.0, bridge_rate or 0.0) * max(hours, hours_left)
        left = (EXHAUSTED - pct) - bridge
        return max(0, round(left / (hours * rate)))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def aim_hours(hours_left):
    """Hours until the need's deadline: the reset itself, at least AIM_MIN_H
    so the last checkpoint does not divide by ~0."""
    return max(AIM_MIN_H, hours_left)


def manual_resets(csv_text, since=0.0):
    """Epochs of the manual resets in usage-history.csv at or after `since`:
    a weekly drop of over MANUAL_DROP points unless it lands within
    NATURAL_SLACK_S of the previous row's resets_at (that is the natural reset;
    a manual one can move resets_at too, so the move is no tell)."""
    rows = []
    for line in (csv_text or "").splitlines():
        f = line.split(",")
        try:
            if len(f) >= 4 and f[1] == "seven_day":
                rows.append((float(f[0]), float(f[2]), float(f[3])))
        except ValueError:
            continue
    rows.sort()
    return [b[0] for a, b in itertools.pairwise(rows)
            if b[0] >= since and a[1] - b[1] > MANUAL_DROP
            and abs(b[0] - a[2]) > NATURAL_SLACK_S]


def reset_slots(resets, now, until, allowed=MANUAL_RESETS, span=RESET_SPAN_S):
    """When each manual reset the owner may still use before `until` (the natural
    reset) is free: `now` for each of the `allowed` left in the trailing span,
    then one as each of `resets` turns `span` old."""
    recent = sorted(t for t in resets if now - span < t <= now)
    free = [now] * max(0, allowed - len(recent))
    later = [t + span for t in recent[max(0, len(recent) - allowed):] if t + span < until]
    return free + later


def steepest(start, done, total, corners, until):
    """The fastest rate (points an hour) a schedule must reach to spend
    `total` by `until`, having spent `done` at `start` and at most U by each
    corner (t, U) still ahead: the last leg of the taut string."""
    legs = [(start, done)] + [(t, u) for t, u in corners if start < t < until]
    return max((total - u) / max(AIM_MIN_H, (until - t) / 3600) for t, u in legs)


def reset_due(plan, slots, now):
    """True when the plan uses a manual reset, one is free now, and the meter
    is due full now: the moment to wake the owner to reset."""
    return bool(plan and plan[0] and slots and slots[0] <= now and plan[1] <= now + 600)


def quiet(epoch, sleep=None):
    """True when the owner is predicted asleep at `epoch` (tools/awake.py; None:
    the fixed 23:00-07:00 Pacific)."""
    return awake.asleep(epoch, sleep)


def overnight_cap(pct, now, end, rate, bridge):
    """The most runs that, spread until `end` (his predicted wake, or the reset
    if sooner), leave room for the bridge alone at NIGHT_BRIDGE_FACTOR times
    `bridge` to stay NIGHT_GUARD points under EXHAUSTED until then. None when
    an input is missing."""
    try:
        hours = max(AIM_MIN_H, (end - now) / 3600)
        room = (EXHAUSTED - NIGHT_GUARD - pct
                - max(0.0, bridge or 0.0) * NIGHT_BRIDGE_FACTOR * hours)
        return max(0, int(room / (hours * rate)))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def abt(epoch):
    """`epoch` as the owner reads times: Alberta, to the nearest minute, "Wed 04:00 ABT"."""
    from zoneinfo import ZoneInfo
    t = dt.datetime.fromtimestamp(round(epoch / 60) * 60, ZoneInfo("America/Edmonton"))
    return f"{t:%a %H:%M} ABT"


def rush_choice(left, until):
    """(rush, words) for `left` manual resets free now and the natural reset at
    `until` (owner 11-03: "spend any resets we have so rush when we have one and
    don't when we don't"), the last MANUAL_RESERVE kept unspent. Words are the status line's: "rushing, 2 of 15 manual
    resets left" or "pacing to Wed 04:00 ABT reset, 0 of 15 manual resets left"."""
    tally = f"{left} of {MANUAL_RESETS} manual resets left"
    if left > MANUAL_RESERVE:
        return True, f"rushing; {tally}"
    return False, f"pacing to {abt(until)} reset; {tally}"


def auto_rush(home, left, until, now):
    """Arm or disarm the rush from the manual resets free: more than
    MANUAL_RESERVE free arms RUSH (to the natural reset) and clears
    NATURAL_ONLY, so the meter is spent and the room woken to reset; no more
    free removes RUSH and writes NATURAL_ONLY to
    the natural reset, so the burn paces the meter to EXHAUSTED by then. The
    files stay the burn's switches (--rush, --natural-only), now set from the
    count each call instead of by hand. Returns rush_choice's words."""
    rush, words = rush_choice(left, until)
    try:
        if rush:
            if not rush_active(_read(home / RUSH), 0.0, now):
                (home / RUSH).write_text(f"{until:.0f}\n")
            (home / NATURAL_ONLY).unlink(missing_ok=True)
        else:
            (home / RUSH).unlink(missing_ok=True)
            if not natural_only(_read(home / NATURAL_ONLY), now):
                (home / NATURAL_ONLY).write_text(f"{until:.0f}\n")
    except OSError as exc:
        print(f"width: rush switch not written: {exc}", file=sys.stderr)
    return words


def natural_only(text, now):
    """True while the NATURAL_ONLY file's epoch (`text`) is still ahead."""
    try:
        return now < float(text)
    except (TypeError, ValueError):
        return False


def night_guard(pct, now, hours_left, plan, rate, bridge, sleep, natural=False):
    """(overnight_cap's runs, the epoch it guards to) unless the meter is due
    full (the plan's fill, else the reset) by the owner's next bedtime; None then
    or when the meter is unread. `natural`: the target is the natural reset,
    which needs no owner, so nothing holds the meter back for his sleep."""
    if natural or pct is None or hours_left is None or hours_left <= 0 or not rate:
        return None
    until = now + hours_left * 3600
    bed, up = awake.next_sleep(now, sleep)
    if (plan[1] if plan and plan[0] else until) <= bed:
        return None
    end = min(up, until)
    runs = overnight_cap(pct, now, end, rate, bridge)
    return None if runs is None else (runs, end)


def reset_plan(pct, now, until, slots, cap_rate=None, sleep=None):
    """(resets used, epoch the meter should reach EXHAUSTED, rate points an
    hour) for a weekly meter at `pct` with manual resets free at `slots`
    before the natural reset `until`. Each reset buys one more window of
    EXHAUSTED points; the meter can spend at most to EXHAUSTED before the next
    slot frees, so the schedule is the taut string under that staircase. It
    uses the most slots (earliest first) whose steepest leg the machine's
    cap_rate holds (None: no cap). With none used the fill is the natural reset.
    A fill in the owner's predicted night (`sleep`, tools/awake.py) moves to its
    nearer edge the rates allow (his bedtime only while the cap holds it), so
    he is awake to reset."""
    head = max(0.0, EXHAUSTED - pct)
    hours = max(AIM_MIN_H, (until - now) / 3600)
    for k in range(len(slots), -1, -1):
        corners = [(t, head + EXHAUSTED * i) for i, t in enumerate(slots[:k])]
        total = head + EXHAUSTED * k
        top = steepest(now, 0.0, total, corners, until)
        if k == 0 or cap_rate is None or top <= cap_rate:
            break
    if k == 0:
        return 0, until, head / hours
    # The first leg: the shallowest line from now to a corner still ahead or the end.
    first = min([total / hours] + [u / ((t - now) / 3600) for t, u in corners if now < t < until])
    fill = now + head / first * 3600 if first > 0 else now
    if fill > now and quiet(fill, sleep):
        early, late = awake.next_sleep(fill, sleep)
        rest = [(t, u) for t, u in corners if t > late]
        ok_early = early > now and (cap_rate is None or head / ((early - now) / 3600) <= cap_rate)
        ok_late = late < until and (cap_rate is None
                                    or steepest(late, head, total, rest, until) <= cap_rate)
        if ok_early and (fill - early <= late - fill or not ok_late):
            fill = early
        elif ok_late:
            fill = late
    rate = head / max(AIM_MIN_H, (fill - now) / 3600)
    return k, fill, rate


def meter_rise(csv_text, start, end):
    """(points, hours) the weekly meter rose over its rows in [start, end]:
    the sum of its rises, a fall being a reset. None with under two rows, or
    when the newest is more than METER_STALE_S before end."""
    rows = []
    for line in (csv_text or "").splitlines():
        f = line.split(",")
        try:
            if len(f) >= 3 and f[1] == "seven_day" and start <= float(f[0]) <= end:
                rows.append((float(f[0]), float(f[2])))
        except ValueError:
            continue
    rows.sort()
    if len(rows) < 2 or end - rows[-1][0] > METER_STALE_S:
        return None
    points = sum(max(0.0, b[1] - a[1]) for a, b in itertools.pairwise(rows))
    return points, (rows[-1][0] - rows[0][0]) / 3600


def token_weight(model, usage):
    """A message's tokens at list price, relative to an uncached Opus input."""
    family = next((f for f in MODEL_WEIGHT if f in (model or "")), "opus")
    tokens = sum(w * (usage.get(k) or 0) for k, w in TOKEN_WEIGHT.items())
    return tokens * MODEL_WEIGHT[family] / MODEL_WEIGHT["opus"]


TIMESTAMP = re.compile(r'"timestamp":"([^"]+)"')


def _epoch(stamp):
    try:
        return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _tail(path, start, chunk=1 << 18):
    """The lines of a transcript from about start on: read back from the end a
    chunk at a time until a line older than start, since a session file is
    written in time order and the window is its last hour."""
    with open(path, "rb") as fh:
        size = fh.seek(0, 2)
        at = size
        while at > 0:
            at = max(0, at - chunk)
            fh.seek(at)
            head = fh.read(min(chunk, size - at)).split(b"\n", 2)
            line = head[1] if at and len(head) > 1 else head[0]
            m = TIMESTAMP.search(line.decode(errors="replace"))
            if m and (_epoch(m[1]) or 0) < start:
                break
            chunk *= 2
        fh.seek(at)
        return fh.read().decode(errors="replace").splitlines()


def transcript_spend(projects, burn_cwd, start, end):
    """(other, burn, burn run-hours) over [start, end] from every transcript
    under projects: token weights, one per message id, the burn's being the
    records whose cwd is burn_cwd; a run-hour is a burn session's first to last
    record in the span, subagents' records counting as tokens only."""
    spend, spans = {}, {}
    burn_cwd = str(burn_cwd)
    for path in Path(projects).glob("**/*.jsonl"):
        try:
            if path.stat().st_mtime < start:
                continue
            lines = _tail(path, start)
        except OSError:
            continue
        for line in lines:
            if '"usage"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msg = rec.get("message")
            when = _epoch(rec.get("timestamp") or "")
            if (not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict)
                    or when is None or not start <= when <= end):
                continue
            burn = rec.get("cwd") == burn_cwd
            spend[msg.get("id") or rec.get("uuid")] = (
                burn, token_weight(msg.get("model"), msg["usage"]))
            if burn and not rec.get("isSidechain"):
                lo, hi = spans.get(rec.get("sessionId"), (when, when))
                spans[rec.get("sessionId")] = (min(lo, when), max(hi, when))
    other = sum(w for b, w in spend.values() if not b)
    burn = sum(w for b, w in spend.values() if b)
    return other, burn, sum(hi - lo for lo, hi in spans.values()) / 3600


def split_rates(rise, other, burn, burn_hours):
    """(bridge points an hour, burn points per run-hour) from the meter's rise
    (points, hours) and the span's token weights: the points are split in
    proportion to the tokens. The burn's rate is None without RUN_HOURS_MIN
    run-hours to divide by; both are None without a rise to split."""
    if not rise or rise[1] <= 0:
        return None, None
    points, hours = rise
    if other + burn <= 0:
        return points / hours, None
    per_token = points / (other + burn)
    burn_rate = (per_token * burn / burn_hours
                 if burn > 0 and burn_hours >= RUN_HOURS_MIN else None)
    return per_token * other / hours, burn_rate


def mem_cap(meminfo, rss_kb):
    """Runs memory can hold: those in flight plus MemAvailable less
    MEM_HEADROOM_KB over their average RSS (RUN_RSS_KB when none runs).
    None when MemAvailable cannot be read."""
    m = re.search(r"^MemAvailable:\s+(\d+) kB", meminfo or "", re.MULTILINE)
    if not m:
        return None
    each = sum(rss_kb) / len(rss_kb) if rss_kb else RUN_RSS_KB
    return len(rss_kb) + max(0, int(m[1]) - MEM_HEADROOM_KB) // max(1, int(each))


def mem_detail(meminfo, rss_kb):
    """The memory cap's inputs in words, for the width line after its dot: "memory 6.2 GB
    available less 4 GB kept free, 250 MB a run, swap 4.0/4.0 GB used". owner 11-03 ("it says
    memory is the limiter but memory looks fine"): available is MemAvailable (free plus the
    cache the kernel can drop, no swap), and the MEM_HEADROOM_KB kept for the bridge and
    Docker comes off it first, so 6 GB available holds ~8 more runs, not ~24. None unread."""
    def kb(name):
        m = re.search(rf"^{name}:\s+(\d+) kB", meminfo or "", re.MULTILINE)
        return int(m[1]) if m else None
    avail = kb("MemAvailable")
    if avail is None:
        return None
    gb = lambda k: f"{k / 1048576:.1f}"
    each = sum(rss_kb) / len(rss_kb) if rss_kb else RUN_RSS_KB
    out = (f"memory {gb(avail)} GB available less {MEM_HEADROOM_KB / 1048576:g} GB kept free, "
           f"{each / 1024:.0f} MB a run")
    st, sf = kb("SwapTotal"), kb("SwapFree")
    if st and sf is not None:
        out += f", swap {gb(st - sf)}/{gb(st)} GB used"
    return out


def cpu_cap(others, burn, cores, runs):
    """Runs the cores other load leaves idle can hold: (cores - others) over one
    run's share of the burn's CPU (runs being the burn's claude processes now),
    all in cores. None when no run is in flight or the burn used no CPU to
    measure a run by."""
    if not cores or not runs or not burn or burn <= 0 or others is None:
        return None
    return max(0, int((cores - others) / (burn / runs)))


# The pool scales down in proportion once 1-minute load passes LOAD_PER_CORE
# per core. Burn runs are nice 19 and mostly wait on the API (~0.1-0.17 core
# each), so one per core is idle headroom, not a stall; the bridge stalled at
# 5-10x cores (10-25). 4 since 11-03 (owner: "you can push the load limit i
# don't want to underspend"): at 2 the cap held the pool to 4-5 runs at load
# 10-13 with the week at 68% and 5h left; 4 per core stays under the stall.
LOAD_PER_CORE = 4


def read_load1():
    """The 1-minute load average, None when it cannot be read."""
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def load_cap(load1, cores, width):
    """Runs the box's load lets the pool keep: None while load1 is at or under
    LOAD_PER_CORE per core (or unread), else this call's uncapped width scaled
    by that threshold / load1 (never below 1). 2026-10-25 load hit 30-63 on 6
    cores with ~4 annotate runs plus a fetch, stalling the bridge up to 88 s
    despite nice 19; CPU and memory caps both read fine, so load itself is the
    signal. The first version shrank one run at a time, so at a 5-minute
    checkpoint it answered a load of 38 with one fewer run; 11-01 scaled by the
    overshoot instead. That version scaled the PREVIOUS width, a ratchet: once
    at 1, int(1 * 6 / load1) is 0 for any load above 6, so the pool stayed at
    1 until load fell under one per core (11-03: width 1 at load ~6-10 while
    other work used ~3 of 6 cores and each burn run ~0.11-0.17 core, mostly
    waiting on the API). Scaling the width the quota and memory ask for this
    call has no memory of its own past cuts, and one run per core is no stall:
    the bridge stalled at 5-10x cores, so the cap starts at 4x (2x until 11-03)."""
    if load1 is None or not cores:
        return None
    limit = cores * LOAD_PER_CORE
    if load1 <= limit:
        return None
    return max(1, int(max(int(width or 1), 1) * limit / load1))


def cpu_runs(live, span):
    """The runs the burn's CPU over the span is split between: the shell's
    average in flight over it (CT_SPAN_RUNS, after_wave's "at width"), when it
    gives one larger than the claude runs alive now. The shell re-plans before
    it asks for the width, launching nothing meanwhile, so by then most of the
    interval's runs have exited: 2026-10-14 a pool averaging 13.2 runs had 3
    alive, each read as a third of a core, and the cap fell from 25 to 6."""
    try:
        span = float(span or 0)
    except ValueError:
        span = 0.0
    return max(live, span)


def width_for(runs_needed, mem, cpu, current, floor=1):
    """The need (else the current width, else DEFAULT_WIDTH), capped by memory
    (else DEFAULT_CEILING) and by the idle cores (when measured). At least
    floor: 0 for a shell that naps at width 0 (--may-pause), else 1."""
    w = runs_needed if runs_needed is not None else current or DEFAULT_WIDTH
    w = min(w, DEFAULT_CEILING if mem is None else mem)
    if cpu is not None:
        w = min(w, cpu)
    return max(floor, w)


def set_rush(minutes=None):
    """--rush [MINUTES]: flat out until the weekly meter is spent or resets.
    MINUTES is accepted for old callers and unused."""
    home = Path(os.environ.get("CT_MAIN_CHECKOUT") or REPO)
    until = time.time() + weekly_usage.resets_in_hours("weekly")[0] * 3600
    (home / RUSH).write_text(f"{until:.0f}\n")
    (home / RUSH_SPENT_STAMP.format("weekly")).unlink(missing_ok=True)
    print(f"rushing: flat out until the weekly meter is spent or resets at "
          f"{dt.datetime.fromtimestamp(until, dt.timezone.utc).astimezone():%a %H:%M}")
    return 0


def current_width(arg, lines):
    """The width the burn runs now: its argument, else the last one logged."""
    try:
        if int(arg) > 0:
            return int(arg)
    except (TypeError, ValueError):
        pass
    for line in reversed(lines):
        m = WIDTH_LINE.match(line)
        if m and int(m[1]) > 0:
            return int(m[1])
    return None


def _read(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return None


def burn_rss_kb():
    """RSS of the `claude -p` runs working in this checkout."""
    rss = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            args = (proc / "cmdline").read_bytes().split(b"\0")
            if os.path.basename(args[0]) != b"claude" or b"-p" not in args:
                continue
            if Path(os.readlink(proc / "cwd")).resolve() != REPO:
                continue
            m = re.search(r"^VmRSS:\s+(\d+) kB", (proc / "status").read_text(), re.MULTILINE)
            if m:
                rss.append(int(m[1]))
        except (OSError, IndexError):
            continue
    return rss


def _procs():
    """{pid: (ppid, cmdline, CPU ticks with reaped children's)} from /proc."""
    table = {}
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            stat = (proc / "stat").read_text()
            f = stat[stat.rindex(")") + 2:].split()
            table[int(proc.name)] = (int(f[1]), (proc / "cmdline").read_bytes(),
                                     sum(int(x) for x in f[11:15]))
        except (OSError, ValueError, IndexError):
            continue
    return table


def burn_ticks(table):
    """CPU ticks of every process tree rooted at a prereset_backfill.sh whose
    parent is not one, so a re-exec or a subshell is counted once."""
    mark = b"prereset_backfill.sh"
    kids = {}
    for pid, (ppid, _, _) in table.items():
        kids.setdefault(ppid, []).append(pid)
    todo = [pid for pid, (ppid, cmd, _) in table.items()
            if mark in cmd and mark not in table.get(ppid, (0, b"", 0))[1]]
    total = 0
    while todo:
        pid = todo.pop()
        total += table[pid][2]
        todo += kids.get(pid, [])
    return total


def busy_ticks(stat):
    """Non-idle ticks since boot from /proc/stat's cpu line."""
    f = [int(x) for x in (stat or "").split("\n", 1)[0].split()[1:9]]
    return sum(f) - f[3] - f[4]


def cpu_load(state_path):
    """(others, burn) in cores since the previous call's sample at state_path,
    when CPU_SPAN_S allows, else over CPU_SAMPLE_S now. None if unread."""
    def sample():
        return time.time(), busy_ticks(_read("/proc/stat")), burn_ticks(_procs())
    try:
        now = sample()
        try:
            then = tuple(float(x) for x in Path(state_path).read_text().split())
        except (OSError, ValueError):
            then = None
        if (not then or len(then) != 3 or not CPU_SPAN_S[0] <= now[0] - then[0] <= CPU_SPAN_S[1]
                or now[2] < then[2]):
            then = now
            time.sleep(CPU_SAMPLE_S)
            now = sample()
        try:
            Path(state_path).write_text(" ".join(str(x) for x in now))
        except OSError:
            pass
    except (OSError, ValueError, IndexError):
        return None
    ticks = (now[0] - then[0]) * os.sysconf("SC_CLK_TCK")
    busy, burn = now[1] - then[1], now[2] - then[2]
    return max(0, busy - burn) / ticks, burn / ticks


def bridge_spend(now=None):
    """(bridge points an hour, burn points per run-hour or None) measured over
    the last SPEND_WINDOW_S; (None, None) when the meter is unread."""
    now = now or time.time()
    rise = meter_rise(_read(weekly_usage.SAMPLE_CSV_PATH), now - SPEND_WINDOW_S, now)
    if not rise:
        return None, None
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return split_rates(rise, *transcript_spend(config / "projects", REPO,
                                               now - rise[1] * 3600, now))


def capacity_rate(mem, rate, bridge):
    """Weekly points an hour the machine can spend: PLAN_SHARE of the memory
    cap's runs at the per-run rate, plus the bridge's own. None unread."""
    if not rate or rate <= 0:
        return None
    runs = DEFAULT_CEILING if mem is None else mem
    return PLAN_SHARE * runs * rate + max(0.0, bridge or 0.0)


def show_resets():
    """--resets: the manual resets free before the natural one and the plan."""
    now = time.time()
    hours_left, _ = weekly_usage.resets_in_hours("weekly")
    pct = weekly_usage.usage_pct("weekly")
    until = now + hours_left * 3600
    used = manual_resets(_read(weekly_usage.SAMPLE_CSV_PATH), now - RESET_SPAN_S)
    home = Path(os.environ.get("CT_MAIN_CHECKOUT") or REPO)
    natural = natural_only(_read(home / NATURAL_ONLY), now)
    slots = [] if natural else reset_slots(used, now, until)
    bridge, rate = bridge_spend()
    rate = capped_rate(rate, per_run_rate((_read(home / ".prereset.debug.log") or "").splitlines()))
    cap = capacity_rate(mem_cap(_read("/proc/meminfo"), burn_rss_kb()), rate, bridge)
    sleep = awake.load(home, now)
    k, fill, need_rate = reset_plan(pct, now, until, slots, cap, sleep)
    night = night_guard(pct, now, hours_left, (k, fill, need_rate), rate, bridge, sleep,
                        natural and k == 0)
    def at(t):
        return f"{dt.datetime.fromtimestamp(t, PACIFIC):%a %m-%d %H:%M} Pacific"
    print(f"weekly {pct:g}%, natural reset {at(until)}; {len(used)} of {MANUAL_RESETS} "
          f"manual resets used in 30 days; free before it: {', '.join(map(at, slots)) or 'none'}")
    if natural:
        print(f"natural-only until {at(float(_read(home / NATURAL_ONLY)))}: no manual resets "
              f"planned, the meter fills to {EXHAUSTED:g}% at the natural reset, no night guard")
    print(f"plan: {k} manual resets, meter to {EXHAUSTED:g}% by {at(fill)} at "
          f"{need_rate:.2f} pts/h (capacity {cap if cap is None else round(cap, 2)} pts/h, "
          f"bridge {bridge if bridge is None else round(bridge, 2)} pts/h)")
    runs = paced_need(pct, max(AIM_MIN_H, (fill - now) / 3600), rate, bridge or 0.0)
    if night is not None and runs is not None:
        runs = min(runs, night[0])
    print(f"next fill: {at(fill)}, burn width now {runs} runs"
          + (f" at {rate:.2f} pts per run-hour" if rate else ""))
    print("overnight: the meter is due full before his bedtime" if night is None else
          f"overnight: at most {night[0]} runs until {at(night[1])}, so the bridge alone at "
          f"{NIGHT_BRIDGE_FACTOR:g}x stays under {EXHAUSTED - NIGHT_GUARD:g}%")
    print("\n".join(awake.describe(sleep, now)))
    return 0


def set_natural_only(arg):
    """--natural-only [UNTIL_EPOCH]: write NATURAL_ONLY so the burn plans no
    manual resets until then (default: the current natural reset)."""
    now = time.time()
    try:
        until = float(arg) if arg else now + weekly_usage.resets_in_hours("weekly")[0] * 3600
    except (TypeError, ValueError, *weekly_usage.READ_ERRORS) as exc:
        print(f"natural-only: no end time: {exc}", file=sys.stderr)
        return 1
    home = Path(os.environ.get("CT_MAIN_CHECKOUT") or REPO)
    (home / NATURAL_ONLY).write_text(f"{until:.0f}\n")
    print(f"natural-only until {dt.datetime.fromtimestamp(until, PACIFIC):%a %m-%d %H:%M} "
          f"Pacific ({until:.0f}) in {home / NATURAL_ONLY}")
    return 0


def publish(path, need, mem, cpu, w):
    """The plan for the OCR queues' burn-first gate (mem_gate.burn_starved),
    replaced whole so a reader never sees half of it."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps({"need": need, "mem": mem, "cpu": cpu, "width": w}) + "\n")
        tmp.replace(path)
    except OSError as exc:
        print(f"width: {path} not written: {exc}", file=sys.stderr)


def width(arg=None, floor=1):
    """The width to keep in flight, from the live weekly meter and reset, the
    bridge's measured spend, the burn's rate and last width, and the machine.
    The inputs go to stderr."""
    home = Path(os.environ.get("CT_MAIN_CHECKOUT") or REPO)
    lines = (_read(home / ".prereset.debug.log") or "").splitlines()
    current = current_width(arg, lines)
    runs_needed = bridge = pct = hours_left = plan = night = None
    slots = []
    rushing = natural = False
    choice = None
    rss = burn_rss_kb()
    meminfo = _read("/proc/meminfo")
    mem = mem_cap(meminfo, rss)
    try:
        now = time.time()
        bridge, rate = bridge_spend()
        rate = capped_rate(rate, per_run_rate(lines))
        pct = weekly_usage.usage_pct("weekly")
        hours_left, _ = weekly_usage.resets_in_hours("weekly")
        if hours_left is not None and hours_left > 0 and pct is not None:
            used = manual_resets(_read(weekly_usage.SAMPLE_CSV_PATH), now - RESET_SPAN_S)
            left = max(0, MANUAL_RESETS - len(used))
            choice = auto_rush(home, left, now + hours_left * 3600, now)
        stamp = _read(home / RUSH)
        armed = stamp is not None
        if armed:
            if rush_disarmed(stamp, pct, now):
                (home / RUSH).unlink(missing_ok=True)
            else:
                rushing = rush_active(stamp, pct, now)
        aim_h = hours_left
        sleep = awake.load(home, now)
        if hours_left is not None and hours_left > 0 and pct is not None:
            until = now + hours_left * 3600
            used = manual_resets(_read(weekly_usage.SAMPLE_CSV_PATH), now - RESET_SPAN_S)
            natural = natural_only(_read(home / NATURAL_ONLY), now)
            slots = [] if natural else reset_slots(used, now, until)
            plan = reset_plan(pct, now, until, slots, capacity_rate(mem, rate, bridge), sleep)
            if plan[0]:
                aim_h = max(AIM_MIN_H, (plan[1] - now) / 3600)
        due = armed or reset_due(plan, slots, now)
        rush_notify(home, "weekly", pct, wake_room, now, due,
                    None if armed else
                    f"The burn has spent the weekly meter ({pct:g}%) and a reset is free: "
                    f"reset it now ({plan[0] if plan else 0} planned before the natural reset). "
                    f"The burn resumes by itself once it falls.", sleep)
        runs_needed = paced_need(pct, aim_h, rate, bridge or 0.0)
        night = night_guard(pct, now, hours_left, plan, rate, bridge, sleep, natural)
        if night is not None and runs_needed is not None and night[0] < runs_needed:
            runs_needed = night[0]
    except weekly_usage.READ_ERRORS as exc:  # an unread meter leaves the need unknown
        print(f"width: meter unread: {type(exc).__name__}: {exc}", file=sys.stderr)
    load = cpu_load(home / CPU_STATE)
    runs = cpu_runs(len(rss), os.environ.get("CT_SPAN_RUNS"))
    cpu = cpu_cap(*load, os.cpu_count(), runs) if load else None
    if rushing:  # flat out: memory is the only cap
        runs_needed = DEFAULT_CEILING if mem is None else mem
        cpu = None
    w = width_for(runs_needed, mem, cpu, current, floor)
    busy = load_cap(read_load1(), os.cpu_count(), w)
    if busy is not None and w > busy:
        w = busy
    publish(home / mem_gate.BURN_STATE, runs_needed, mem, cpu, w)
    shown = (f"{bridge:.1f} pts/h" if bridge is not None else "unread")
    cores = (f"others {load[0]:.2f} burn {load[1]:.2f} over {runs:g} runs of {os.cpu_count()} cores"
             if load else "cores unread")
    at = (f"{pct:g}% now, {hours_left:.1f}h to its reset"
          if pct is not None and hours_left is not None else "meter unread")
    aim = (f", aiming {aim_hours(hours_left):.2f}h out"
           if hours_left is not None and hours_left > 0 else "")
    if plan and plan[0]:
        aim = (f", {plan[0]} manual resets planned, next fill "
               f"{dt.datetime.fromtimestamp(plan[1], PACIFIC):%a %H:%M} Pacific at {plan[2]:.1f} pts/h")
    if night is not None:
        aim += (f", overnight cap {night[0]} to his wake "
                f"{dt.datetime.fromtimestamp(night[1], PACIFIC):%a %H:%M} Pacific")
    dash = lambda v: "—" if v is None else v
    # "width W (cap: ...)" is the part that says how wide and why; what follows the dot
    # changes every call, so the burn prints this line only when the part before it does.
    # Rushing, the need IS the memory cap (flat out), so it is shown as "rush", not as a pace
    # that always ties memory (11-03: "memory 15 ... quota pace 15" on every line, and the log
    # said memory binds while the meter, not the machine, was the reason to go that wide).
    pace = "rush" if rushing else runs_needed
    # The rush decision rides in the caps (";" inside, so the ", " split there
    # keeps it whole), so a change prints the line again and burn_log.py says it.
    plan_words = f", reset plan {choice}" if choice else ""
    detail = mem_detail(meminfo, rss)
    print(f"width {w} (cap: memory {dash(mem)}, cpu {dash(cpu)}, load {dash(busy)}, "
          f"quota pace {pace}{plan_words}) · weekly {at}{aim}; bridge {shown}; {cores}; "
          f"{detail + '; ' if detail else ''}was {current}", file=sys.stderr)
    return w


def self_test():
    """The backlog order: a puzzle whose blog names an indicator none of our
    annotations links yet jumps the queue, weighted by that indicator's clues."""
    # The cases name their own rows: the live re-annotation list is not theirs.
    import shape_queue
    shape_queue.PATH = Path(os.devnull).parent / "no-such-shape-list.json"
    # queue, {puzzle: pairs its blog gives}, {unlinked pair: clues}, pinned -> order
    A, B = ("anagram", "UPSIDEDOWN"), ("reversal", "UP")
    covers = [
        # a puzzle covering an unlinked indicator jumps the queue
        (["new", "mid", "old"], {"old": {A}}, {A: 5}, (), ["old", "new", "mid"]),
        # once annotated the pair is linked, so it no longer counts: nothing jumps
        (["new", "mid", "old2"], {"old2": {A}}, {}, (), ["new", "mid", "old2"]),
        # one common indicator beats two rare ones
        (["a", "b", "c"], {"b": {A}, "c": {B, ("hidden_word", "IN")}},
         {A: 10, B: 1, ("hidden_word", "IN"): 1}, (), ["b", "c", "a"]),
        # a pair counts once: the second puzzle giving only it stays in place
        (["a", "b", "c"], {"b": {A}, "c": {A}}, {A: 5}, (), ["b", "a", "c"]),
        # ties keep queue order (newest first)
        (["a", "b", "c"], {"b": {A}, "c": {B}}, {A: 3, B: 3}, (), ["b", "c", "a"]),
        # puzzles a lockout cut off still resume first
        (["r", "a", "b"], {"b": {A}}, {A: 5}, ("r", "gone"), ["r", "b", "a"]),
    ]
    global TODAY
    TODAY = dt.date(1950, 1, 1)
    bad = (cover_self_test(covers) + width_self_test() + tag_self_test()
           + first_self_test() + backlog_self_test() + small_self_test() + fresh_self_test()
           + reannotate_self_test() + interleave_self_test() + best_effort_self_test())
    n = (len(covers) + len(WIDTH_CASES) + len(NEED_CASES) + len(MEM_CASES) + len(MEM_DETAIL_CASES)
         + len(CPU_CASES) + len(LOAD_CASES) + len(METER_CASES) + len(REPLAY_CASES) + 21 + len(TAG_CASES) + 2 + len(FIRST_CASES) + 3 + 4
         + len(BACKLOG_CASES) + 4 + 4 + 3 + len(RUSH_CASES) + len(RUSH_OFF_CASES) + 3 + 6
         + 4 + 5 + len(PLAN_CASES) + 5 + 4 + 4
         + len(SLEEP_PLAN_CASES) + len(OVERNIGHT_CASES) + len(GUARD_CASES) + 2)
    print(f"prereset plan self-test FAILED: {bad} of {n}" if bad
          else f"prereset plan self-test: {n} cases pass")
    return 1 if bad else 0


# (need, memory cap, cpu cap, current width) -> width
WIDTH_CASES = [
    ((4, 40, 40, 14), 4),          # on track: the need, however small
    ((26, 40, 40, 14), 26),        # behind: wider than now
    ((26, 8, 40, 14), 8),          # memory holds 8
    ((26, 40, 6, 14), 6),          # the idle cores hold 6
    ((26, 40, None, 14), 26),      # CPU unmeasured: no cap
    ((None, None, None, None), DEFAULT_WIDTH),  # nothing readable
    ((None, 40, 40, 9), 9),        # meter unread: keep the current width
    ((60, None, 40, 14), DEFAULT_CEILING),      # memory unread
    ((26, 0, 40, 14), 1),          # no memory free: still one run
    ((26, 40, 0, 14), 1),          # no core idle: still one run
    ((0, 40, 40, 14), 1),          # bridge spends the window: one run without --may-pause
    ((0, 40, 40, 14, 0), 0),       # ...and none for one that naps at 0
    ((26, 40, 0, 14, 0), 0),       # no core idle, for one that naps
]
# (weekly pct, hours to its reset, per-run rate and bridge points an hour in
#  weekly points) -> need; EXHAUSTED is 99. Every need is due at the reset
# (aim_hours), less only AIM_MIN_H.
R = 6.0
NEED_CASES = [(a, w) for a, w in [
    ((89, 10.0, 2.0 / R, 0), 3),     # 10 weekly over 10h at a third a run-hour
    ((59, 10.0, 2.0 / R, 0), 12),    # 40 weekly over 3.33 run-hours a run
    ((99, 10.0, 2.0 / R, 0), 0),     # week spent to EXHAUSTED
    ((100, 10.0, 2.0 / R, 0), 0),    # past it
    ((None, 10.0, 2.0 / R, 0), None),
    ((50, None, 2.0 / R, 0), None),  # reset unread
    ((50, 10.0, 0, 0), None),        # no rate
    # reset passed: a fresh week, 99 points over 168h at a third a run-hour
    ((50, 0.0, 2.0 / R, 0), 2),
    ((100, -0.1, 2.0 / R, 0), 2),    # the meter still shows the week just spent
    # The bridge's projected spend comes off the top: the burn takes the surplus.
    ((59, 10.0, 2.0 / R, 12 / R), 6),    # bridge 20 of the 40, projected to the reset
    ((59, 10.0, 2.0 / R, 35 / R), 0),    # bridge alone spends the week by the reset
    ((59, 10.0, 2.0 / R, None), 12),     # bridge unmeasured: nothing subtracted
    # weekly 10% with 58h to go, bridge 4 an hour, 1.95 a run, 6.5
    ((10, 58.0, 1.95 / 6.5, 4 / 6.5), 3),
    # 2026-10-13 23:00: 73% with 10.5h left, bridge 7.4 an hour from one busy
    # hour, needed 4 aimed at the reset, and the week ended at 90%
    ((73, 10.5, 2.09 / 6.37, 7.4 / 6.37), 4),
    # capacity short: 11% weekly left with 2h to go in 4 run-hours, 16 runs:
    # more than a cpu cap of 3-10 holds, so width_for runs at the cap from now
    # and the need rises as the hours shrink
    ((88, 2.0, 2.0 / R, 0), 16),
    ((88, 1.0, 2.0 / R, 0), 33),
    ((88, 0.05, 2.0 / R, 0), 660),   # the floor: the last checkpoint is finite
]]
# Replays of a week paced every 5 minutes, where the bridge spends less than
# projected and a cap holds the width: (its pct, hours left, per-run rate,
# bridge projected, bridge real, width cap, share of the width really running)
# -> must reach EXHAUSTED (within REPLAY_SLACK) at the reset. This is
# 2026-10-13's night (it ended at 90%).
REPLAY_SLACK = 1.5  # aimed at the reset with no margin: a point or so short is a hit
REPLAY_CASES = [
    (60, 16.0, 2.09 / 6.37, 5.0 / 6.37, 2.5 / 6.37, 8, 0.95),
]


def replay(pct, hours, rate, bridge_proj, bridge_real, cap, share, step=1 / 12):
    """The meter's level at the reset; it is read in whole points, as
    weekly_usage gives it, and spent in steps of five minutes."""
    while hours > 0:
        need = paced_need(int(pct), hours, rate, bridge_proj) or 0
        pct += (min(need, cap) * share * rate + bridge_real) * step
        hours -= step
    return pct
# (csv text, start, end) -> (points, hours) the weekly meter rose
_ROW = "{},seven_day,{},9999999999\n"
METER_CASES = [
    ("".join(_ROW.format(t, p) for t, p in [(0, 10), (1800, 14), (3600, 20)]),
     0, 3600, (10.0, 1.0)),
    # a reset between rows: the fall is skipped, the rise after it counts
    ("".join(_ROW.format(t, p) for t, p in [(0, 90), (1800, 2), (3600, 6)]),
     0, 3600, (4.0, 1.0)),
    # newest row too old to say anything about now
    ("".join(_ROW.format(t, p) for t, p in [(0, 10), (600, 12)]), 0, 3600, None),
    (_ROW.format(3000, 10), 0, 3600, None),
    ("garbage", 0, 3600, None),
    (None, 0, 3600, None),
]
GB = 1024 * 1024
# (meminfo, RSS of runs in flight) -> memory cap
MEM_CASES = [
    (f"MemTotal: 1 kB\nMemAvailable: {6 * GB} kB\n", [], 2 * GB // RUN_RSS_KB),
    (f"MemAvailable: {6 * GB} kB\n", [512000, 512000], 2 + 2 * GB // 512000),
    (f"MemAvailable: {3 * GB} kB\n", [], 0),
    ("garbage", [], None),
    (None, [], None),
]
# (meminfo, RSS of runs in flight) -> the memory cap's inputs in words (mem_detail)
MEM_DETAIL_CASES = [
    (f"MemAvailable: {6 * GB} kB\nSwapTotal: {4 * GB} kB\nSwapFree: 0 kB\n", [],
     "memory 6.0 GB available less 4 GB kept free, 250 MB a run, swap 4.0/4.0 GB used"),
    (f"MemAvailable: {6 * GB} kB\n", [512000], "memory 6.0 GB available less 4 GB kept free, 500 MB a run"),
    ("garbage", [], None),
]
# (cores other processes use, cores the burn uses, cores, runs) -> cpu cap
CPU_CASES = [
    (0.5, 1.0, 4, 4, 14),     # idle box: 3.5 cores at 0.25 a run
    (3.0, 1.0, 4, 4, 4),      # the bridge busy on 3 cores: the burn shrinks
    (4.0, 1.0, 4, 4, 0),      # nothing idle
    (5.0, 1.0, 4, 4, 0),      # overcommitted
    (0.5, 0.0, 4, 4, None),   # no burn CPU to measure a run by
    (0.5, 1.0, 4, 0, None),   # no run in flight
    (None, 1.0, 4, 4, None),
    (2.13, 0.98, 6, 13.22, 52),  # the span's average, not the 3 alive at the plan (cap 11)
]
# (RUSH's stamp, weekly pct, now) -> rush active
RUSH_CASES = [
    ("2000000\n", 71, 1000000, True),
    ("2000000\n", 99, 1000000, True),
    ("2000000\n", 100, 1000000, False),   # weekly spent
    ("2000000\n", 71, 2000000, False),    # the weekly reset passed
    (None, 71, 1000000, False),
    ("garbage", 71, 1000000, False),
    ("2000000\n", None, 1000000, False),
]
# (RUSH's stamp, weekly pct, now) -> disarmed
RUSH_OFF_CASES = [
    ("2000000\n", 71, 1000000, False), ("2000000\n", 100, 1000000, True),
    ("2000000\n", 71, 2000001, True), ("2000000\n", None, 1000000, False),
    ("garbage", 100, 1000000, False),
]
# (1-minute load, cores, uncapped width) -> load cap
LOAD_CASES = [
    (3.0, 6, 10, None),    # calm: no cap, quota use untouched
    (12.0, 6, 10, None),   # two per core: under
    (9.6, 6, 16, None),    # 2026-11-03: runs idle on the API, not a stall
    (24.0, 6, 10, None),   # exactly four per core: not above
    (26.0, 6, 10, 9),
    (30.0, 6, 16, 12),     # 11-03 ratchet: the uncapped width, not the last one
    (26.0, 6, 1, 1),       # never below 1
    (26.0, 6, 0, 1),
    (60.0, 6, 10, 4),      # swamped: two fifths
    (38.0, 6, 7, 4),       # 2026-11-01: load 38 with 7 runs
    (63.0, 6, 3, 1),
    (None, 6, 10, None),   # unread: no cap
    (30.0, 0, 10, None),
]
# (claude runs alive now, CT_SPAN_RUNS) -> runs the burn's CPU is split between
CPU_RUNS_CASES = [
    (3, "13.22", 13.22),  # the pool drained during the re-plan
    (9, "4.5", 9),        # more alive than the span averaged: those
    (5, "", 5),           # the first interval, or after a nap
    (5, None, 5),
    (5, "junk", 5),
]


def width_self_test():
    """The cases above, the rate and current width read off the log, and a
    failed read still giving a positive width."""
    bad = 0
    checks = ([(width_for, a, w) for a, w in WIDTH_CASES]
              + [(paced_need, a, w) for a, w in NEED_CASES]
              + [(mem_cap, (m, r), w) for m, r, w in MEM_CASES]
              + [(mem_detail, (m, r), w) for m, r, w in MEM_DETAIL_CASES]
              + [(cpu_cap, (o, b, c, r), w) for o, b, c, r, w in CPU_CASES]
              + [(load_cap, (l, c, w), x) for l, c, w, x in LOAD_CASES]
              + [(cpu_runs, (n, s), w) for n, s, w in CPU_RUNS_CASES]
              + [(rush_active, (st, h, n), w) for st, h, n, w in RUSH_CASES]
              + [(rush_disarmed, (st, h, n), w) for st, h, n, w in RUSH_OFF_CASES]
              + [(ceiling, (r,), w) for r, w in [(True, 100.0), (False, EXHAUSTED)]]
              + [(meter_rise, (t, a, b), w) for t, a, b, w in METER_CASES])
    for fn, args, want in checks:
        if fn(*args) != want:
            print(f"FAIL {fn.__name__}{args} = {fn(*args)} (want {want})", file=sys.stderr)
            bad += 1
    if capped_rate(None, 0.9) != 0.9 or capped_rate(0.5, 0.9) != 0.5 or capped_rate(2.9, 0.9) != 0.9:
        print("FAIL capped_rate", file=sys.stderr)
        bad += 1
    for args in REPLAY_CASES:
        if replay(*args) < ceiling() - REPLAY_SLACK:
            print(f"FAIL replay{args}: short of {ceiling():g}% at the reset", file=sys.stderr)
            bad += 1
    line = "  weekly {}% -> {}% in 0.1h at width 14"
    logged = [line.format(i, i + 3) for i in range(12)] + [line.format(90, 2)]
    # pool lines: 0.5h at 12.5 in flight on average is 6.25 run-hours
    pool = "  weekly {}% -> {}% in 0.5h at width 12.50 (pool of 14)"
    pooled = [pool.format(i, i + 5) for i in range(12)]
    # lines with and without the pool suffix: 12 x 3 + 12 x 5 points over 12 x (1.4 + 6.25)
    mixed = logged[:12] + pooled
    for lines, want in [(logged, 3 / 1.4), (logged[:3], PER_RUN_RATE),
                        (pooled, 5 / 6.25), (mixed, 96 / (12 * 7.65)),
                        # an interval with nothing in flight says nothing
                        (pooled[:9] + [pool.format(5, 9).replace("12.50", "0.00")],
                         PER_RUN_RATE),
                        # 10-23: the rooms' 41 points over 3.5h at width 0.01 are not a run's rate
                        (pooled + [pool.format(38, 79).replace("0.5h at width 12.50", "3.55h at width 0.01")],
                         5 / 6.25)]:
        if abs(per_run_rate(lines) - want) > 1e-9:
            print(f"FAIL per_run_rate of {len(lines)} lines = {per_run_rate(lines)} "
                  f"(want {want})", file=sys.stderr)
            bad += 1
    pools = ["--- pool of 14: a b ---", "x", "--- pool of 9: c ---", "  weekly ...",
             "--- pool of 11: 3 in flight, 40 queued ---", "  [a] started"]
    for arg, lines, want in [("12", pools, 12), (None, pools, 11), ("0", pools, 11),
                             ("x", [], None), ("7", pools, 7),
                             (None, ["--- pool of 0: ---"], None)]:
        if current_width(arg, lines) != want:
            print(f"FAIL current_width({arg!r}, {lines}) = {current_width(arg, lines)} "
                  f"(want {want})", file=sys.stderr)
            bad += 1
    bad += spend_self_test() + tree_self_test() + reset_self_test() + sleep_self_test()
    # The hour is tzdata's (Alberta's offset is the zone file's call); 10:59:40 rounds up a minute.
    when = _utc(2026, 11, 4, 10, 59, 40)
    if not re.fullmatch(r"Wed \d\d:00 ABT", abt(when)):
        print(f"FAIL abt() = {abt(when)!r}, want 'Wed HH:00 ABT'", file=sys.stderr)
        bad += 1
    for left, want in [(0, (False, f"pacing to {abt(when)} reset; 0 of 15 manual resets left")),
                       (1, (False, f"pacing to {abt(when)} reset; 1 of 15 manual resets left")),
                       (2, (True, "rushing; 2 of 15 manual resets left"))]:
        got = rush_choice(left, when)
        if got != want:
            print(f"FAIL rush_choice({left}) = {got!r}, want {want!r}", file=sys.stderr)
            bad += 1
    real = weekly_usage.usage_pct
    def unreadable(_group):
        raise RuntimeError("no reading")
    weekly_usage.usage_pct = unreadable
    import tempfile
    saved = os.environ.get("CT_MAIN_CHECKOUT")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["CT_MAIN_CHECKOUT"] = tmp  # the live checkout's state stays the burn's
        try:
            got = width("7")
            if not isinstance(got, int) or got < 1:
                print(f"FAIL width() with the meter unread = {got!r} (want a positive int)",
                      file=sys.stderr)
                bad += 1
            plan = json.loads((Path(tmp) / mem_gate.BURN_STATE).read_text())
            if plan.get("width") != got or "cpu" not in plan or plan.get("need") is not None:
                print(f"FAIL width() published {plan} (want width {got}, need None)", file=sys.stderr)
                bad += 1
        finally:
            weekly_usage.usage_pct = real
            if saved is None:
                os.environ.pop("CT_MAIN_CHECKOUT", None)
            else:
                os.environ["CT_MAIN_CHECKOUT"] = saved
    # rush_notify: once per window, again after the meter falls
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        said = []
        seq = [("weekly", 98, 0), ("weekly", 99, 1), ("weekly", 100, 0), ("weekly", 40, 0),
               ("weekly", 99, 1), ("weekly", None, 0)]
        noon = 1793563200  # 2026-11-01 12:00 Pacific: outside the night
        for name, pct, sent in seq:
            before = len(said)
            rush_notify(Path(tmp), name, pct, said.append, noon)
            if len(said) - before != sent:
                print(f"FAIL rush_notify({name}, {pct}) sent {len(said) - before} (want {sent})",
                      file=sys.stderr)
                bad += 1
    return bad


def _utc(*when):
    return dt.datetime(*when, tzinfo=dt.UTC).timestamp()


# 2026-11-01 14:01:53 UTC: weekly 43%, natural reset Wed 11-04 11:00 UTC, and
# the 14 manual resets of the trailing 30 days (10-01 23:10 just aged out).
NOW = _utc(2026, 11, 1, 14, 1, 53)
NATURAL = _utc(2026, 11, 4, 11)
USED = [_utc(2026, 10, d, h, m) for d, h, m in [
    (3, 13, 29), (4, 21, 33), (9, 21, 48), (11, 4, 0), (12, 12, 0), (16, 5, 34), (17, 17, 44),
    (19, 1, 3), (22, 22, 27), (24, 9, 44), (25, 18, 10), (26, 23, 37), (30, 4, 56), (31, 15, 14)]]
SLOTS = [NOW, USED[0] + RESET_SPAN_S, USED[1] + RESET_SPAN_S]  # free now, Mon 13:29, Tue 21:33 UTC
MON22 = _utc(2026, 11, 3, 6)  # Mon 22:00 Pacific
# (pct, now, natural reset, slots, capacity) -> (resets, hours to the fill, pts/h); fills within a minute
PLAN_CASES = [
    # today at the machine's 3.7 pts/h: the Tue slot's last window would need
    # 7.4 pts/h, so two resets; one window of 254 points over 69h, evenly
    ((43, NOW, NATURAL, SLOTS, 3.7), (2, 15.206, 3.683)),
    # no cap: all three, the first leg aimed at the Tue slot's corner
    ((43, NOW, NATURAL, SLOTS, None), (3, 12.240, 4.575)),
    # a machine too slow for any reset: 56 points to the natural reset
    ((43, NOW, NATURAL, SLOTS, 1.0), (0, 68.969, 0.812)),
    ((43, NOW, NATURAL, [], None), (0, 68.969, 0.812)),
    # spent with a reset free: fill now
    ((99, NOW, NATURAL, SLOTS, 3.7), (2, 0.0, 0.0)),
    # the night: a 06:00 fill waits for 07:00, 23:30 and 02:00 move back to 23:00
    ((90, MON22, MON22 + 96 * 3600, [MON22], None), (1, 9.0, 1.0)),
    ((90, MON22, MON22 + 18 * 3600, [MON22], 20.0), (1, 1.0, 9.0)),
    ((90, MON22, MON22 + 48 * 3600, [MON22], None), (1, 1.0, 9.0)),
    # ...unless 23:00 is too steep for the machine: then 07:00
    ((90, MON22, MON22 + 48 * 3600, [MON22], 8.0), (1, 9.0, 1.0)),
    # one window of 108 points in 18h is beyond 5 pts/h: no reset
    ((90, MON22, MON22 + 18 * 3600, [MON22], 5.0), (0, 18.0, 0.5)),
]

# A learned night of 22:30-06:30 Pacific (tools/awake.py's span), then the
# same with a message from the owner at 22:00 (awake now: his night starts 23:15).
LEARNED = {"span": (22.5, 30.5), "last": None}
UP_LATE = dict(LEARNED, last=MON22)
# (pct, now, natural reset, slots, capacity, sleep) -> as PLAN_CASES
SLEEP_PLAN_CASES = [
    # a 02:00 fill moves back to his 22:30 bedtime...
    ((90, MON22, MON22 + 48 * 3600, [MON22], None, LEARNED), (1, 0.5, 18.0)),
    # ...or, too steep for the machine, on to 06:30 when he is up
    ((90, MON22, MON22 + 48 * 3600, [MON22], 8.0, LEARNED), (1, 8.5, 9 / 8.5)),
    # up late: 23:15 is within the machine's reach
    ((90, MON22, MON22 + 48 * 3600, [MON22], 8.0, UP_LATE), (1, 1.25, 7.2)),
    # a fill in the afternoon stays put
    ((43, NOW, NATURAL, SLOTS, 3.7, LEARNED), (2, 15.206, 3.683)),
]
# (pct, now, end, per-run rate, bridge) -> runs
OVERNIGHT_CASES = [
    ((90, MON22, MON22 + 8 * 3600, 0.5, 1.0), 0),    # 90 + 1.5 x 8 is past 98: none
    ((60, MON22, MON22 + 8 * 3600, 0.5, 1.0), 6),    # 26 points of room over 8h at 0.5
    ((60, MON22, MON22 + 8 * 3600, 0.5, 0.0), 9),    # no bridge: 38 points
    ((60, MON22, MON22 + 8 * 3600, None, 1.0), None),
]
# (pct, now, hours to the reset, plan, rate, bridge, sleep) -> night_guard
NOON = MON22 - 10 * 3600
GUARD_CASES = [
    # the plan fills at 21:00, before his 22:30 bedtime: no guard
    ((60, NOON, 60, (1, MON22 - 3600, 4.0), 0.5, 1.0, LEARNED), None),
    # it fills at 07:00 tomorrow: 18.5h to his 06:30 wake, 38 - 1.5 x 18.5 = 10.25 points, 1 run
    ((60, NOON, 60, (1, MON22 + 9 * 3600, 4.0), 0.5, 1.0, LEARNED), (1, MON22 + 8.5 * 3600)),
    # no reset planned and the natural one at 03:00: guarded to the reset, 38 - 22.5 points
    ((60, NOON, 15, (0, NOON + 15 * 3600, 2.0), 0.5, 1.0, LEARNED), (2, NOON + 15 * 3600)),
    ((None, NOON, 15, None, 0.5, 1.0, LEARNED), None),
]


def sleep_self_test():
    """The plan around a learned night, the overnight cap and its guard."""
    bad = 0
    for args, (k, hours, rate) in SLEEP_PLAN_CASES:
        got = reset_plan(*args)
        if (got[0] != k or abs((got[1] - args[1]) / 3600 - hours) > 1 / 60
                or abs(got[2] - rate) > 0.01):
            print(f"FAIL reset_plan{args[0], args[4], args[5]} = ({got[0]}, "
                  f"{(got[1] - args[1]) / 3600:.3f}h, {got[2]:.3f}) (want ({k}, {hours}h, {rate}))",
                  file=sys.stderr)
            bad += 1
    for fn, cases in [(overnight_cap, OVERNIGHT_CASES), (night_guard, GUARD_CASES)]:
        for args, want in cases:
            if fn(*args) != want:
                print(f"FAIL {fn.__name__}{args} = {fn(*args)} (want {want})", file=sys.stderr)
                bad += 1
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:  # the 99% wake waits for his learned morning
        said = []
        for now, sent in [(MON22 + 3600, 0), (MON22 + 8.6 * 3600, 1)]:
            before = len(said)
            rush_notify(Path(tmp), "weekly", 99, said.append, now, True, sleep=LEARNED)
            if len(said) - before != sent:
                print(f"FAIL rush_notify at {now} sent {len(said) - before} (want {sent})",
                      file=sys.stderr)
                bad += 1
    return bad


def reset_self_test():
    """Manual resets read off the CSV, the slots they leave, the plan, the
    night, and the 99% wake held for the morning."""
    bad = 0
    def fail(what):
        nonlocal bad
        print(f"FAIL {what}", file=sys.stderr)
        bad += 1
    row = "{:.0f},seven_day,{},{:.0f}\n"
    week = 7 * 86400
    csv = "".join(row.format(*r) for r in [
        (0, 98, 200), (300, 0, 2 * week),            # natural: the drop lands on resets_at
        (600, 100, 2 * week), (900, 0, 2 * week),    # manual
        (1200, 40, 2 * week), (1500, 25, 2 * week),  # a 15-point dip is no reset
        (1800, 100, 2 * week), (2100, 0, 3 * week)])  # manual, resets_at moved
    for args, want in [((csv,), [900.0, 2100.0]), ((csv, 1000), [2100.0]),
                       (("garbage",), []), ((None,), [])]:
        if manual_resets(*args) != want:
            fail(f"manual_resets{args[1:]} = {manual_resets(*args)} (want {want})")
    for text, want in [("2000", True), ("1000", False), ("", False), (None, False), ("x", False)]:
        if natural_only(text, 1500.0) != want:
            fail(f"natural_only({text!r}) = {not want} (want {want})")
    a_night = (50.0, 1000.0, 20.0, (0, 1000.0 + 20 * 3600, 2.0), 1.0, 1.0, None)
    if night_guard(*a_night, natural=True) is not None:
        fail("night_guard holds the meter when the target is the natural reset")
    for args, want in [((USED, NOW, NATURAL), SLOTS),
                       ((USED[2:], NOW, NATURAL), [NOW] * 3),   # 12 used: 3 free now
                       ((USED + [NOW - 60], NOW, NATURAL), SLOTS[1:]),  # 15 used: none now
                       ((USED, NOW, SLOTS[2]), SLOTS[:2]),       # a slot past the natural reset
                       (([], NOW, NATURAL, 2), [NOW, NOW])]:
        if reset_slots(*args) != want:
            fail(f"reset_slots of {len(args[0])} = {reset_slots(*args)} (want {want})")
    for args, (k, hours, rate) in PLAN_CASES:
        got = reset_plan(*args)
        if (got[0] != k or abs((got[1] - args[1]) / 3600 - hours) > 1 / 60
                or abs(got[2] - rate) > 0.01):
            fail(f"reset_plan{args[0], args[4]} = ({got[0]}, {(got[1] - args[1]) / 3600:.3f}h, "
                 f"{got[2]:.3f}) (want ({k}, {hours}h, {rate}))")
    for args, want in [(((2, NOW, 0), SLOTS, NOW), True),
                       (((2, NOW + 3600, 1), SLOTS, NOW), False),  # not full yet
                       (((0, NOW, 0), SLOTS, NOW), False),         # no reset planned
                       (((1, NOW, 0), SLOTS[1:], NOW), False),     # none free now
                       ((None, [], NOW), False)]:
        if reset_due(*args) != want:
            fail(f"reset_due{args} = {reset_due(*args)} (want {want})")
    for when, want in [(_utc(2026, 11, 3, 6, 59), False), (_utc(2026, 11, 3, 7), True),
                       (_utc(2026, 11, 3, 14, 59), True), (_utc(2026, 11, 3, 15), False)]:
        if quiet(when) != want:
            fail(f"quiet({when}) = {quiet(when)} (want {want})")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        said = []
        night, morning = _utc(2026, 11, 3, 10), _utc(2026, 11, 3, 15, 5)
        for pct, now, due, sent in [(99, morning, False, 0),  # no reset free: no wake
                                    (99, night, True, 0),     # 02:00 Pacific: held
                                    (99, morning, True, 1),   # 07:05: woken
                                    (99, morning, True, 0)]:  # once
            before = len(said)
            rush_notify(Path(tmp), "weekly", pct, said.append, now, due)
            if len(said) - before != sent:
                fail(f"rush_notify({pct}, {now}, due={due}) sent {len(said) - before} (want {sent})")
    return bad


def spend_self_test():
    """The bridge's spend out of a synthetic hour: transcripts read back from
    their tails, a streamed message counted once, the burn picked out by cwd,
    and the meter's rise split between the two by token weight."""
    import tempfile
    bad = 0
    end = float(int(time.time()))
    start = end - 3600

    def rec(t, cwd, mid, out, session="s", model="claude-opus-5-5", side=False):
        stamp = dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat().replace("+00:00", "Z")
        return json.dumps({"type": "assistant", "timestamp": stamp, "cwd": cwd,
                           "sessionId": session, "isSidechain": side,
                           "message": {"id": mid, "model": model,
                                       "usage": {"output_tokens": out}}})
    with tempfile.TemporaryDirectory() as tmp:
        bridge, burn = Path(tmp, "-bridge"), Path(tmp, "-burn")
        (burn / "s1" / "subagents").mkdir(parents=True)
        bridge.mkdir()
        old = [rec(start - 600 - i, "/home", f"old{i}", 1000) for i in range(3000)]
        (bridge / "a.jsonl").write_text("\n".join(old + [
            rec(start + 60, "/home", "b1", 100), rec(start + 61, "/home", "b1", 100),
            rec(start + 900, "/home", "b2", 200),
            rec(start + 1000, "/home", "h1", 500, model="claude-haiku-4-5")]) + "\n")
        (burn / "s1.jsonl").write_text("\n".join([
            rec(start + 600, "/burn", "r1", 100, "s1"),
            rec(start + 600 + 1800, "/burn", "r2", 100, "s1")]) + "\n")
        (burn / "s1" / "subagents" / "x.jsonl").write_text(
            rec(start + 3000, "/burn", "r3", 200, "s1", side=True) + "\n")
        other, mine, hours = transcript_spend(tmp, "/burn", start, end)
        # bridge: (100 + 200 + 500 haiku at a fifth) x 5; burn: 400 x 5 over 0.5h
        want = (400 * 5.0, 400 * 5.0, 0.5)
        if any(abs(a - b) > 1e-9 for a, b in zip((other, mine, hours), want)):
            print(f"FAIL transcript_spend = {(other, mine, hours)} (want {want})", file=sys.stderr)
            bad += 1
        # 12 points in the hour: 6 the bridge's, 6 the burn's over 0.5 run-hours
        got = split_rates((12.0, 1.0), other, mine, hours)
        if got != (6.0, 12.0):
            print(f"FAIL split_rates = {got} (want (6.0, 12.0))", file=sys.stderr)
            bad += 1
    for args, want in [(((12.0, 1.0), 0, 0, 0), (12.0, None)),  # no tokens: all the bridge's
                       (((12.0, 1.0), 10, 10, 0.1), (6.0, None)),  # too few run-hours
                       ((None, 1, 1, 1), (None, None))]:
        if split_rates(*args) != want:
            print(f"FAIL split_rates{args} = {split_rates(*args)} (want {want})", file=sys.stderr)
            bad += 1
    return bad


# (queue, pinned) -> pinned after first_issues()
FIRST_CASES = [
    # a series' No 1 goes ahead of newer puzzles, behind a cut-off resume
    (["cryptic-30000", "everyman-1", "quiptic-2"], ["r"], ["r", "everyman-1"]),
    # the declared first issue counts, a 1 under a renumbering does not
    (["timesclub-1", "timesclub-20000"], [], ["timesclub-20000"]),
    # no first issue where the number is a date, a reprint or a book position
    (["metro-9516", "globeandmail-1", "book-1001", "book-1"], [], []),
    # pinned once, not twice
    (["listener-1"], ["listener-1"], ["listener-1"]),
]


def _dated(pid, day, annotated=False):
    return {"id": pid, "series": pid.rsplit("-", 1)[0], "date": day,
            "annotated": annotated, "hasSolutions": True}


def first_self_test():
    bad = 0
    # each series' 10 oldest go first, oldest first behind pinned, so 1967
    # outranks 2026; the 11th oldest keeps its queue place, as does the undated
    rows = [_dated(f"times-{i}", f"1974-01-{i:02}") for i in range(1, 12)]
    rows += [_dated("canberra-3", "1967-02-01"), _dated("cryptic-30000", "2026-09-01")]
    queue = ["cryptic-30000", "nodate-1"] + [f"times-{i}" for i in range(11, 0, -1)] + ["canberra-3"]
    got = oldest_per_series(queue, ["r"], rows)
    want = ["r", "canberra-3"] + [f"times-{i}" for i in range(1, 11)] + ["cryptic-30000"]
    if got != want:
        print(f"FAIL oldest_per_series = {got} (want {want})", file=sys.stderr)
        bad += 1
    # The 10 are the series' oldest on file, not the oldest left in the queue:
    # annotating times-1..3 must not pull times-11 up, else the burn walks
    # every series oldest-first, 10 at a time.
    done = [dict(r, annotated=r["id"] in ("times-1", "times-2", "times-3")) for r in rows]
    got = oldest_per_series([q for q in queue if q not in ("times-1", "times-2", "times-3")],
                            [], done)
    want = ["canberra-3"] + [f"times-{i}" for i in range(4, 11)] + ["cryptic-30000"]
    if got != want:
        print(f"FAIL oldest_per_series slides as the oldest are annotated: {got} (want {want})",
              file=sys.stderr)
        bad += 1
    # a row the burn cannot take (no answers, clues unreadable) is not among the n
    blank = [dict(r, hasSolutions=False, clues={"present": 1, "total": 30})
             if r["id"] == "times-1" else r for r in rows]
    if "times-11" not in oldest_per_series(queue, [], blank):
        print("FAIL oldest_per_series counts an untakeable puzzle among the n", file=sys.stderr)
        bad += 1
    bad += head_self_test()
    for queue, pinned, want in FIRST_CASES:
        got = first_issues(queue, list(pinned))
        if got != want:
            print(f"FAIL first_issues({queue}, {pinned}) = {got} (want {want})", file=sys.stderr)
            bad += 1
    return bad


# cut-offs, showcase, No 1, 10 oldest, notable tags, then
# the rest round-robin newest first, whatever order the queue came in.
_HEAD_ROWS = ([_dated(f"cryptic-{22640 + i}", f"2002-{1 + i // 28:02}-{1 + i % 28:02}")
               for i in range(40)]
              + [_dated(f"times-{28780 + i}", f"2024-01-{1 + i:02}") for i in range(5)]
              + [_dated("quiptic-1", "1999-01-01"), _dated("cryptic-30128", "2026-09-30"),
                 _dated("everyman-4000", "2026-09-28")])


def requests_self_test():
    """The hand-request list: its queued ids go first, after a lockout's pins; an id
    drops once its puzzle is fully annotated, one partly hinted stays."""
    import tempfile
    bad = 0
    rows = [_row("cryptic-1", "2026-01-01"), _row("cryptic-2", "2026-01-02"),
            _row("cryptic-3", "2026-01-03"), _row("cryptic-4", "2026-01-04", annotated=True),
            _row("cryptic-5", "2026-01-05", annotated=True, unannotated=2)]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "burn_requests.json"
        path.write_text('["cryptic-1", "cryptic-4", "cryptic-5", "cryptic-9"]')
        want = requested(rows, path)
        if want != ["cryptic-1", "cryptic-5", "cryptic-9"]:
            print(f"FAIL requested = {want} (a fully annotated id drops, an unknown stays)", file=sys.stderr)
            bad += 1
        queue = ["cryptic-1", "cryptic-2", "cryptic-3", "cryptic-5"]
        _, pinned, stages = head_of_queue(queue, ["cryptic-3"], rows, asked=want)
        if pinned[:3] != ["cryptic-3", "cryptic-1", "cryptic-5"] or stages[5] != 2:
            print(f"FAIL head_of_queue with requests pins {pinned} at {stages} "
                  "(want lockout pin, then the requests in list order)", file=sys.stderr)
            bad += 1
        path.write_text("not json")
        if requested(rows, path):
            print("FAIL an unreadable request list is not empty", file=sys.stderr)
            bad += 1
    return bad


def recent_self_test():
    today = dt.date(2026, 10, 20)
    rows = [_dated("a-1", "2026-10-01", True), _dated("a-2", "2026-09-01"),
            _dated("a-3", "2026-10-10"), _dated("a-4", "2025-10-19"),
            _dated("a-5", "2025-10-21", True), _dated("a-6", "2026-10-15"), _dated("a-7", "2026-11-30")]
    queue = ["a-1", "a-3", "a-2", "a-5", "a-6", "a-4", "a-7"]
    got = recent_first(queue, ["a-6"], rows, today)
    want = (["a-6", "a-3", "a-2", "a-1", "a-5"], 2, 2)
    if got != want:
        print(f"FAIL recent_first = {got} (want {want})", file=sys.stderr)
        return 1
    return 0


def head_self_test():
    bad = requests_self_test() + recent_self_test()
    # the queue as a re-plan hands it over: ascending, newly eligible at the back
    queue = sorted((r["id"] for r in _HEAD_ROWS), key=lambda i: int(i.rsplit("-", 1)[1]))
    queue.remove("cryptic-30128")
    queue.append("cryptic-30128")
    ordered, pinned, _ = head_of_queue(queue, ["cryptic-22700"], _HEAD_ROWS,
                                       {"times-28782"}, {"cryptic-22670": ["unclued"]})
    oldest = [f"cryptic-{22640 + i}" for i in range(10)]
    want_pins = (["cryptic-22700", "times-28782", "quiptic-1"] + oldest
                 + [f"times-{28780 + i}" for i in (0, 1, 3, 4)] + ["everyman-4000", "cryptic-22670"])
    # oldest first across series: the cryptic's 2002 ten, the Times' 2024 four,
    # the everyman's only one
    if pinned != want_pins:
        print(f"FAIL head_of_queue pins {pinned} (want {want_pins})", file=sys.stderr)
        bad += 1
    rest = [i for i in ordered if i not in pinned]
    if rest[:3] != ["cryptic-30128", "cryptic-22679", "cryptic-22678"]:
        print(f"FAIL head_of_queue's rest is not newest first: {rest[:3]}", file=sys.stderr)
        bad += 1
    if sorted(ordered) != sorted(queue):
        print("FAIL head_of_queue lost or added ids", file=sys.stderr)
        bad += 1
    # an id the index lacks keeps its place at the back; a duplicate is kept
    got = newest_first(["zz-1", "cryptic-22640", "cryptic-22641", "cryptic-22640"], _HEAD_ROWS)
    if got != ["cryptic-22641", "cryptic-22640", "cryptic-22640", "zz-1"]:
        print(f"FAIL newest_first = {got}", file=sys.stderr)
        bad += 1
    return bad


# known, acquired, filed, solved, hinted; an older day that must not be read
_SMALL_DAYS = {
    "2026-10-10": {"times": [10, 10, 10, 10, 0]},
    "2026-10-11": {"genius": [279, 40, 40, 40, 40],        # nothing left to hint
                   "timesclub": [280, 98, 131, 126, 130],  # nearly done, fewest left
                   "quiptic": [1403, 1600, 1600, 1600, 1500],  # nearly done though big
                   "nation": [3529, 429, 257, 190, 167],   # small, fewer left, not near
                   "dimmy": [300, 50, 50, 50, 10],         # known under 500
                   "tls": [1183, 48, 48, 40, 45],
                   "book": [4181, 2737, 1100, 225, 215],
                   "everyman": [4173, 1207, 1207, 1206, 1065],
                   "metro": [None, None, 76, 76, 70],      # no ledger: filed decides
                   "canberra": [4454, 458, 458, 213, 204],  # LAST stays last
                   "toughie": [3772, 3606, 3606, 3567, 651],
                   "times": [29893, 8760, 9714, 4463, 2261]},
}


def small_self_test():
    bad = 0
    want = ["timesclub", "tls", "metro", "quiptic", "everyman", "dimmy", "nation", "book"]
    if small_series(_SMALL_DAYS) != want:
        print(f"FAIL small_series = {small_series(_SMALL_DAYS)} (want {want})", file=sys.stderr)
        bad += 1
    if small_series({}) != []:
        print("FAIL small_series with no history is not empty", file=sys.stderr)
        bad += 1
    # finish-off (owner 10-22): under FINISH_OFF unhinted, fewest first; none
    # left, LAST and the big ones stay out
    want = ["timesclub", "tls", "metro", "dimmy", "nation", "quiptic", "everyman"]
    if finish_off_series(_SMALL_DAYS) != want or finish_off_series({}) != []:
        print(f"FAIL finish_off_series = {finish_off_series(_SMALL_DAYS)} (want {want})",
              file=sys.stderr)
        bad += 1
    # those series lead the recent tier: after the lockout pin and a hand
    # request, before a recent cryptic, and counted in stages[9]
    frows = [_dated("cryptic-1", "2026-10-01"), _dated("tls-5", "2020-01-01"),
             _dated("tls-6", "2021-01-01"), _dated("book-7", "1990-01-01")]
    _, pinned, stages = head_of_queue(["cryptic-1", "tls-5", "tls-6", "book-7"], ["r"], frows,
                                      asked=["book-7"], finish=["tls"])
    want = ["r", "book-7", "tls-6", "tls-5", "cryptic-1"]
    if pinned != want or stages[9] != 2:
        print(f"FAIL head_of_queue finish off pins {pinned} at {stages} (want {want})",
              file=sys.stderr)
        bad += 1
    # owner 10-22: a finish-off puzzle on the failure ledger (tls-6) or without
    # answers (tls-4) is not lifted; it stays where the normal ordering puts it
    xf = frows + [_dated("tls-4", "2019-01-01")]
    xf[-1]["hasSolutions"] = False
    _, pinned, stages = head_of_queue(["cryptic-1", "tls-5", "tls-6", "book-7", "tls-4"], [], xf,
                                      finish=["tls"], tried={"tls-6"})
    if pinned[:1] != ["tls-5"] or stages[9] != 1 or "tls-4" in pinned[:1] or "tls-6" in pinned[:1]:
        print(f"FAIL head_of_queue finish off lifts {pinned} at {stages} (want tls-5 only)",
              file=sys.stderr)
        bad += 1
    # the small series go right behind the cut-offs, ahead of showcase and the
    # 10 oldest, series by series, newest first inside each
    rows = [_dated("cryptic-1", "2026-01-01"), _dated("cryptic-2", "2026-01-02"),
            _dated("tls-5", "2020-01-01"), _dated("tls-6", "2021-01-01"),
            _dated("book-7", "1990-01-01")]
    _, pinned, stages = head_of_queue(["cryptic-1", "cryptic-2", "tls-5", "tls-6", "book-7"], ["r"], rows,
                                      {"cryptic-2"}, small=["tls", "book"])
    want = ["r", "tls-6", "tls-5", "book-7", "cryptic-2", "cryptic-1"]
    if pinned != want or stages[0] != 4:
        print(f"FAIL head_of_queue with small series pins {pinned} at {stages} (want {want})",
              file=sys.stderr)
        bad += 1
    # partly hinted puzzles go right behind the cut-offs, ahead of the small
    # series, fewest clues missing first (owner 10-15)
    prows = [dict(r, unannotated={"cryptic-1": 5, "book-7": 2}.get(r["id"], 0)) for r in rows]
    _, pinned, stages = head_of_queue(["cryptic-1", "cryptic-2", "tls-5", "tls-6", "book-7"], ["r"], prows,
                                      {"cryptic-2"}, small=["tls", "book"])
    want = ["r", "book-7", "cryptic-1", "tls-6", "tls-5", "cryptic-2"]
    if pinned != want or stages[4] != 0 or stages[6] != 2:  # both are tails: counted there
        print(f"FAIL head_of_queue with partly hinted pins {pinned} at {stages} (want {want})",
              file=sys.stderr)
        bad += 1
    # tails (a bag leader and its members) lead the partly hinted: a 1-missing
    # puzzle awaiting a preamble and an 11-missing one (past clue_bag.MAX_DUE) are not tails, so they
    # follow the 5-, 4- and 3-missing tails (in queue order); a pin stays ahead of all
    miss = {"cryptic-1": 11, "cryptic-2": 1, "tls-5": 5, "tls-6": 4, "book-7": 3}
    trows = [dict(r, unannotated=miss[r["id"]], awaitsPreamble=r["id"] == "cryptic-2")
             for r in rows]
    _, pinned, stages = head_of_queue(["cryptic-1", "cryptic-2", "tls-5", "tls-6", "book-7"], ["r"],
                                      trows)
    want = ["r", "book-7", "tls-6", "tls-5", "cryptic-2", "cryptic-1"]
    if pinned != want or stages[6] != 3:
        print(f"FAIL head_of_queue tails first pins {pinned} (want {want})", file=sys.stderr)
        bad += 1
    # answered first (owner 10-21): a cold solve in the pinned head drops behind
    # the whole queue; the lockout pin and a hand request stay in front
    arows = [dict(r, hasSolutions=r["id"] not in ("tls-6", "cryptic-1", "cryptic-2")) for r in rows]
    ordered, pinned, _ = head_of_queue(["cryptic-1", "cryptic-2", "tls-5", "tls-6", "book-7"], ["tls-6"],
                                       arows, small=["tls", "book"], asked=["cryptic-1"])
    if pinned[:2] != ["tls-6", "cryptic-1"] or "cryptic-2" in pinned or ordered[-1] != "cryptic-2":
        print(f"FAIL head_of_queue answered first pins {pinned}, queue {ordered}", file=sys.stderr)
        bad += 1
    # the round-robin rest too: an unpinned cold solve drops behind every
    # answered puzzle
    xrows = arows + [_dated("extra-1", "2025-01-01"), dict(_dated("extra-2", "2025-01-02"), hasSolutions=False)]
    ordered, _, _ = head_of_queue(["cryptic-1", "cryptic-2", "tls-5", "tls-6", "book-7", "extra-1", "extra-2"],
                                  ["tls-6"], xrows, small=["tls", "book"], asked=["cryptic-1"])
    cold_ids = {"cryptic-2", "extra-2"}
    if set(ordered[-2:]) != cold_ids or cold_ids & set(ordered[:-2]) or len(ordered) != 7:
        print(f"FAIL head_of_queue cold rest last: {ordered}", file=sys.stderr)
        bad += 1
    return bad


def _row(pid, day, solved=True, annotated=False, **extra):
    return {"id": pid, "series": pid.rsplit("-", 1)[0], "date": day,
            "annotated": annotated, "hasSolutions": solved, **extra}


_HELD = {"id": "book-6039", "series": "book", "year": 2004,
         "annotated": False, "hasSolutions": False}
_SCAN = [_row("times-21042", "1999-03-01", solved=False),       # an OCR scan, no answers
         _row("canberra-500", "2001-01-01", solved=False),      # a whole series filed bare
         _row("times-29600", "2026-09-01"),
         _row("times-29601", "2026-09-02", annotated=True),
         _row("times-21000", "1999-01-01", solved=False,        # mostly blank clues
              clues={"present": 10, "total": 30}),
         _row("times-20994", "1998-12-01", solved=False,        # a few answers, a few gaps
              clues={"present": 27, "total": 28})]
# (rows, annotate ledger, solve ledger, series) -> queue ids
BACKLOG_CASES = [
    # answerless puzzles a model can read are queued, round-robin, newest first,
    # a LAST lane (canberra) behind every other
    (_SCAN, (), (), (), ["times-29600", "times-21042", "times-20994", "canberra-500"]),
    # a solve that failed on these inputs stays out; an annotate failure keeps one out too
    (_SCAN, ("times-29600",), ("times-21042",), (), ["times-20994", "canberra-500"]),
    # $CT_SERIES narrows it
    (_SCAN, (), (), ("canberra",), ["canberra-500"]),
    (_SCAN[2:4], (), (), (), ["times-29600"]),
    # a puzzle whose clue says "see preamble" with no preamble is never queued
    ([_row("times-29600", "2026-09-01"), _row("times-29602", "2026-09-03", awaitsPreamble=True)],
     (), (), (), ["times-29600"]),
    # a blank light on a puzzle whose answer key is a blog's write-up is a parser
    # miss, never a solve (apply_solution.check_writeup refuses it): not queued
    ([_row("times-29600", "2026-09-01"),
      _row("times-29345", "2025-09-26", solved=False, writeupKeyed=True)],
     (), (), (), ["times-29600"]),
    # a clues-only puzzle (clues_only_rows) is queued in its series' lane, here
    # book's ahead of times' (neither is in BY_DEMAND); a failed solve holds it
    # out like any other
    (_SCAN[2:4] + [_HELD], (), (), (), ["book-6039", "times-29600"]),
    (_SCAN[2:4] + [_HELD], (), ("book-6039",), (), ["times-29600"]),
]


def reannotate_self_test():
    """The shape re-annotation tier stays LAST in backlog(), behind un-hinted
    puzzles; head_of_queue pins its redo tails (a few clues due) at the head."""
    import tempfile
    import shape_queue
    bad = 0
    real = shape_queue.PATH
    rows = [_row("times-100", "2026-09-30", annotated=True),     # listed, newest of all
            _row("times-90", "2026-09-01"),
            _row("quiptic-5", "2026-08-01", annotated=True),     # listed
            _row("azed-7", "2020-01-01"),
            _row("times-95", "2026-09-15", annotated=True),      # hinted, not listed
            _row("times-99", "2026-09-29", annotated=True, unannotated=2)]
    rows[-1]["annotated"] = False                                # partly hinted
    with tempfile.TemporaryDirectory() as tmp:
        shape_queue.PATH = Path(tmp) / "shape_reannotate.json"
        shape_queue.PATH.write_text(json.dumps([
            {"id": "times-100#1a", "reason": "x"}, {"id": "quiptic-5#2d", "reason": "y"},
            {"id": "quiptic-5#3d", "reason": "z", "tried": True}]))
        try:
            got = [p["id"] for p in backlog(rows)]
            if set(got[-2:]) != {"times-100", "quiptic-5"} or set(got[:-2]) != {"times-90", "azed-7", "times-99"}:
                print(f"FAIL backlog tier = {got} (want the listed puzzles last)", file=sys.stderr)
                bad += 1
            if "times-95" in got:
                print("FAIL backlog queued a hinted puzzle that is not listed", file=sys.stderr)
                bad += 1
            shuffled = ["quiptic-5", "times-100", "azed-7", "times-90", "times-99"]
            got, pinned, _ = head_of_queue(shuffled, [], rows, tagged=["times-100"], small=["quiptic"])
            # owner 10-17: a listed puzzle with a few clues due is a redo tail, so it
            # is pinned at the head (bagged); backlog() above still queues it last.
            if sorted(got) != sorted(shuffled) or not {"times-100", "quiptic-5"} <= set(pinned):
                print(f"FAIL head_of_queue tier = {got}, pinned {pinned} (the listed redo tails are pinned)",
                      file=sys.stderr)
                bad += 1
            if pinned[:1] != ["times-99"]:
                print(f"FAIL partly hinted not first: {pinned}", file=sys.stderr)
                bad += 1
            # a lockout's pin still resumes first
            if head_of_queue(shuffled, ["times-100"], rows)[1][:1] != ["times-100"]:
                print("FAIL a lockout-pinned listed puzzle did not resume first", file=sys.stderr)
                bad += 1
        finally:
            shape_queue.PATH = real
    return bad


def interleave_self_test():
    """interleave_shape: one shape-tier puzzle per SHAPE_EVERY slots after the
    head, every id once, and the tail's order kept."""
    import shape_queue
    real = shape_queue.PATH
    import tempfile
    bad = 0
    rows = ([_row(f"n-{i}", "2026-01-01") for i in range(12)]
            + [_row(f"s-{i}", "2026-01-01", annotated=True) for i in range(3)])
    ordered = ["h-1"] + [f"n-{i}" for i in range(12)] + [f"s-{i}" for i in range(3)]
    with tempfile.TemporaryDirectory() as tmp:
        shape_queue.PATH = Path(tmp) / "shape_reannotate.json"
        shape_queue.PATH.write_text(json.dumps([{"id": f"s-{i}#1a", "reason": "x"} for i in range(3)]))
        try:
            got = interleave_shape(ordered, 1, rows)
            want = (["h-1", "n-0", "n-1", "n-2", "s-0", "n-3", "n-4", "n-5", "s-1",
                     "n-6", "n-7", "n-8", "s-2", "n-9", "n-10", "n-11"])
            if got != want:
                print(f"FAIL interleave_shape = {got}", file=sys.stderr)
                bad += 1
            if SHAPE_EVERY != 4 or sorted(interleave_shape(ordered, 0, rows)) != sorted(ordered):
                print("FAIL interleave_shape lost or added ids", file=sys.stderr)
                bad += 1
            few = interleave_shape(["n-0", "s-0", "s-1"], 0, rows)
            if few != ["n-0", "s-0", "s-1"]:
                print(f"FAIL interleave_shape with a short rest = {few}", file=sys.stderr)
                bad += 1
        finally:
            shape_queue.PATH = real
    return bad


def backlog_self_test():
    bad = clues_only_self_test()
    for rows, annotate, solve, only, want in BACKLOG_CASES:
        got = [p["id"] for p in backlog(rows, annotate, solve, only)]
        if got != want:
            print(f"FAIL backlog(ledgers {annotate}, {solve}, series {only}) = {got} "
                  f"(want {want})", file=sys.stderr)
            bad += 1
    return bad


def clues_only_self_test():
    """A file in clues_only/ a builder can promote is a queue row, unsolved,
    and sorts by its year among its series' indexed puzzles rather than at the
    back. One whose grid kind has no builder (a Listener book's barred grid) is
    no row at all: its solve could never be promoted."""
    import tempfile

    global INDEX
    bad = 0
    real = INDEX
    with tempfile.TemporaryDirectory() as tmp:
        INDEX = Path(tmp) / "puzzles" / "index.json"
        try:
            (Path(tmp) / "clues_only" / "book").mkdir(parents=True)
            for pid, year in (("book-6039", 2004), ("book-31039", 2002)):
                (Path(tmp) / "clues_only" / "book" / f"{pid}.json").write_text(json.dumps(
                    {"id": pid, "number": int(pid.split("-")[1]), "series": "book",
                     "year": year, "source": {"acquiredBy": "tools/acquire_book.py"},
                     "clues": {"across": [], "down": []}}))
            if clues_only_rows() != [_HELD]:
                print(f"FAIL clues_only_rows = {clues_only_rows()} (want [{_HELD}]: "
                      f"the barred book-31039 has no builder and stays out)",
                      file=sys.stderr)
                bad += 1
            if clues_only_rows({"book-6039"}):
                print(f"FAIL clues_only_rows(filed=book-6039) = {clues_only_rows({'book-6039'})}: a "
                      "puzzle both filed and held would be queued twice (10-16: 40 nation ids), "
                      "and the burn's re-plan discarded", file=sys.stderr)
                bad += 1
            if not unsolved("book-6039"):
                print("FAIL unsolved(a clues-only id) is False: the burn would annotate "
                      "a puzzle with no grid", file=sys.stderr)
                bad += 1
            rows = [_row("book-1001", None, year=1990)] + clues_only_rows()
            got = newest_first(["book-1001", "book-6039"], rows)
            if got != ["book-6039", "book-1001"]:
                print(f"FAIL newest_first with a clues-only row = {got}", file=sys.stderr)
                bad += 1
        finally:
            INDEX = real
    return bad


# (queue, pinned, {id: notable tags}) -> pinned after promote()
TAG_CASES = [
    (["a", "b", "c"], [], {"c": ["special-rules"]}, ["c"]),
    # queue order among the tagged, behind what was already pinned
    (["a", "b", "c", "d"], ["r"], {"d": ["unclued"], "b": ["triple-pangram"]}, ["r", "b", "d"]),
    # pinned once, not twice
    (["a", "b"], ["b"], {"b": ["alphabetical"]}, ["b"]),
    # a tagged puzzle not in the queue (already annotated) is not queued
    (["a"], [], {"z": ["asymmetric"]}, []),
]


def best_effort_self_test():
    """best_effort(): a cold cache's stop gives `empty`, fn runs under its
    share of the time left, and CT_DEADLINE is the caller's again after."""
    import budget
    bad = 0
    saved = os.environ.get("CT_DEADLINE")
    os.environ["CT_DEADLINE"] = str(time.time() + 100)
    try:
        def cold():
            raise budget.Stopped(0)
        if best_effort("t", cold, "empty", 0.5) != "empty":
            print("FAIL best_effort: a stopped fn did not give `empty`; a cold cache "
                  "would sink the whole re-plan", file=sys.stderr)
            bad += 1
        whole = os.environ["CT_DEADLINE"]
        got = best_effort("t", budget.left, None, 0.5)
        if not (got is not None and 40 < got <= 50 and os.environ["CT_DEADLINE"] == whole):
            print(f"FAIL best_effort: fn saw {got}s left (want ~50 of 100) or CT_DEADLINE "
                  f"was not restored ({os.environ['CT_DEADLINE']} vs {whole})", file=sys.stderr)
            bad += 1
    finally:
        if saved is None:
            os.environ.pop("CT_DEADLINE", None)
        else:
            os.environ["CT_DEADLINE"] = saved
    return bad


def tag_self_test():
    """promote()'s cases, and tagged_puzzles() reading tags off an index:
    common tags dropped, unlisted rows read, a missing index read as none."""
    import tempfile
    bad = 0
    for queue, pinned, tagged, want in TAG_CASES:
        got = promote(queue, list(pinned), tagged)
        if got != want:
            print(f"FAIL promote({queue}, {pinned}, {tagged}) = {got} (want {want})", file=sys.stderr)
            bad += 1
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "index.json")
        path.write_text(json.dumps({"puzzles": [
            {"id": "p", "tags": ["pangram"]}, {"id": "b", "tags": ["barred"]},
            {"id": "d", "tags": ["double-pangram", "barred"]}, {"id": "n"}],
            "unlisted": [{"id": "u", "tags": ["unclued"]}]}))
        got = tagged_puzzles(path)
        want = {"d": ["double-pangram"], "u": ["unclued"]}
        if got != want:
            print(f"FAIL tagged_puzzles = {got} (want {want})", file=sys.stderr)
            bad += 1
        if tagged_puzzles(Path(tmp, "missing.json")) != {}:
            print("FAIL tagged_puzzles of a missing index is not empty", file=sys.stderr)
            bad += 1
    return bad


def tree_self_test():
    """The burn's CPU is every process under the topmost prereset_backfill.sh,
    and only those; busy ticks leave out idle and iowait."""
    bad = 0
    sh = b"/bin/bash\0tools/prereset_backfill.sh\0"
    table = {1: (0, b"init", 1000), 10: (1, b"plugin-run.py", 5),
             11: (10, sh, 100), 12: (11, sh, 20),            # a subshell of it
             13: (12, b"claude\0-p\0", 300), 14: (13, b"node", 7),
             20: (1, b"claude\0--output-format\0", 900)}   # the bridge
    if burn_ticks(table) != 427:
        print(f"FAIL burn_ticks = {burn_ticks(table)} (want 427)", file=sys.stderr)
        bad += 1
    if busy_ticks("cpu  10 20 30 400 50 6 7 8 0 0\ncpu0 1\n") != 81:
        print(f"FAIL busy_ticks = {busy_ticks('cpu  10 20 30 400 50 6 7 8')} (want 81)",
              file=sys.stderr)
        bad += 1
    return bad


def cover_self_test(covers):
    """covers' cases, and the key both sides of the match are spelled in."""
    import indicator_cover
    from indicator_keys import indicator_key
    bad = 0
    for queue, pairs_of, weight, pinned, want in covers:
        got, _ = indicator_cover.order(queue, pairs_of, weight, pinned)
        if got != want:
            print(f"FAIL cover {queue} with {pairs_of}: {got} (want {want})", file=sys.stderr)
            bad += 1
    # indicators.json keys "upside-down" as one word; so must the lookup
    for phrase, want in [("upside-down", "UPSIDEDOWN"), ("So-called", "SOCALLED"),
                         ("it’s off", "ITS OFF")]:
        if indicator_key(phrase) != want:
            print(f"FAIL indicator_key({phrase!r}) = {indicator_key(phrase)!r} (want {want!r})",
                  file=sys.stderr)
            bad += 1
    return bad


# Tags too common to jump the queue on. A plain pangram is about one puzzle in
# thirty and "barred" is every Mephisto: promoting either would have the burn do
# little else. Every other tag is rare, and its puzzles are the ones a
# solver goes looking for.
COMMON_TAGS = {"pangram", "barred"}
INDEX = REPO / "puzzles" / "index.json"


_INDEXES = {}


def read_index(index_path=INDEX):
    """The index at index_path, read once a process; {} when there is none."""
    key = str(index_path)
    if key not in _INDEXES:
        try:
            _INDEXES[key] = json.loads(Path(index_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _INDEXES[key] = {}
    return _INDEXES[key]


def index_rows(index_path=INDEX):
    index = read_index(index_path)
    return index.get("puzzles", []) + index.get("unlisted", [])


def tagged_puzzles(index_path=INDEX):
    """{id: its tags outside COMMON_TAGS} from the index, which the burn
    rebuilds as it starts, so a puzzle tagged since is promoted on the next run.
    Empty when there is no index to read."""
    out = {}
    for row in index_rows(index_path):
        notable = [t for t in row.get("tags", ()) if t not in COMMON_TAGS]
        if notable:
            out[row["id"]] = notable
    return out


def showcase_wanted(index_path=INDEX):
    """The unannotated puzzles /showcase/ would pick (tools/showcase.py), which
    shows only annotated ones: a reader opens a pick to solve it with hints.
    Empty when there is no index to read."""
    index = read_index(index_path)
    if not index:
        return set()
    import showcase
    return set(showcase.wanted(showcase.corpus_facts(index)))


def first_issues(queue, pinned):
    """pinned, then the queue's series-first puzzles in queue order: a
    series' No 1 is a special puzzle."""
    taken = set(pinned)
    return pinned + [pid for pid in queue if series.is_first_issue(pid) and pid not in taken]


def promote(queue, pinned, tagged):
    """pinned, then the queue's tagged puzzles in queue order: the new pinned."""
    taken = set(pinned)
    return pinned + [pid for pid in queue if pid in tagged and pid not in taken]


# How many of each series' oldest puzzles go ahead of the rest of the queue.
# Old puzzles are
# interesting; a few per series reach every paper's oldest without the burn
# doing little else.
OLDEST_PER_SERIES = 10


def oldest_per_series(queue, pinned, rows, n=OLDEST_PER_SERIES):
    """pinned, then the queued ones among each series' n oldest puzzles the
    burn can take (rows annotated, answered or cold-solvable, dated by
    series.puzzle_day), oldest first. The n are picked from the whole index,
    annotated rows included, so annotating them does not pull the next oldest
    up: a set picked from the queue alone slides, and walks every series
    oldest-first."""
    from fetch_puzzle import cold_solvable
    lanes = {}
    for r in rows:
        day = series.puzzle_day(r)
        if day and (r.get("annotated") or r.get("hasSolutions") or cold_solvable(r)):
            lanes.setdefault(r["series"], []).append((day, r["id"]))
    oldest = sorted(x for lane in lanes.values() for x in sorted(lane)[:n])
    queued = set(queue)
    taken = set(pinned)
    return pinned + [pid for _, pid in oldest if pid in queued and pid not in taken]


# Series order within a round, so a window cut short by a lockout has spent
# itself on the papers people search for most. This ranks SERIES, never
# puzzles: every entry in a round is already its own lane's newest gap. A series
# missing from this list still runs; it just goes at the back of each cycle.
BY_DEMAND = ["everyman", "indysunday", "quiptic", "cryptic", "independent"]
# Lanes run after every other lane is empty, not in the round-robin. Canberra's
# 1967-85 puzzles are London Times reprints whose originals Gale is filing (a
# match renames the reprint to times-N), so solving the reprint first buys the
# puzzle twice. Its 1986-95 Guardian reprints go last with it (owner 10-11).
LAST = ["canberra"]


def backlog(rows, annotate_blocked=(), solve_blocked=(), only=()):
    """The burn's queue: every un-annotated row, round-robin across the series,
    newest first inside each one.

    A row without all its answers is in it too, when a model can read enough
    of its clues to solve it cold (fetch_puzzle.cold_solvable) and that solve
    has not failed on these inputs: the burn solves it, then annotates it. The
    clues are the only thing a puzzle must come with; its answers are derived.
    A row that awaits its preamble (puzzle_integrity.awaits_preamble) is left
    out: its "see preamble" clue cannot be explained without one.
    A row the solve or annotate ledger (tools/failed_inputs.py) holds out is
    left out: selection is by date, so a puzzle that fails is otherwise the
    newest gap again at every checkpoint, bought from scratch each time.

    Newest first, and nothing else, inside a lane. Recency is the only property
    of a puzzle that predicts whether anyone will look for it: 79% of the site's
    search impressions land on the two most recent publication months. Measured
    demand must NOT be a key: impressions accumulate with age, so sorting by it
    walks the queue backwards. Not by number either: each paper numbers from its
    own 1, so a number sort is a series sort in disguise.

    Round-robin, not one flat date sort, because a flat sort runs the whole of
    the deepest paper's recent archive before the shallowest paper's newest gap.
    This way every series' newest gap is reached within the pool's first round.

    A book puzzle holds a `year` rather than a `date`, and a cyclops puzzle not
    yet dated off its neighbours holds neither, so puzzle_day() makes the key a
    day; undated sorts last inside its lane and never raises. only, when given,
    narrows the queue to those series keys."""
    from fetch_puzzle import cold_solvable
    annotate_blocked, solve_blocked, only = set(annotate_blocked), set(solve_blocked), set(only)
    todo = [p for p in rows
            if not p["annotated"] and p["id"] not in annotate_blocked
            and not p.get("awaitsPreamble")
            and (p.get("hasSolutions") or (cold_solvable(p) and p["id"] not in solve_blocked))
            and (not only or p["series"] in only)]
    return round_robin(todo) + reannotate_tier(rows, annotate_blocked, only, {p["id"] for p in todo})


def reannotate_tier(rows, annotate_blocked=(), only=(), taken=()):
    """The LAST tier of the queue: the hinted puzzles holding a clue on the shape
    re-annotation list (tools/shape_queue.py), round-robin like the rest. They
    already show a hint, so every un-hinted puzzle and every partly hinted one
    goes ahead of them; newest_first keeps them behind, whatever order they
    come in."""
    import shape_queue
    ids = shape_queue.puzzle_ids()
    return round_robin([p for p in rows if p["id"] in ids and p["annotated"] and p["id"] not in taken
                        and p["id"] not in annotate_blocked and not p.get("style")
                        and (not only or p["series"] in only)])


def round_robin(rows):
    """rows round-robin across their series, BY_DEMAND's first, newest first
    inside each series; undated last in its lane; LAST's lanes after all of it,
    and after those the puzzles that are not cryptics (`style`,
    tools/puzzle_style.py), newest first: the ladder has least to teach there."""
    from datetime import date
    straight = sorted((p for p in rows if p.get("style")),
                      key=lambda p: series.puzzle_day(p) or date.min, reverse=True)
    lanes = {}
    for p in rows:
        if p.get("style"):
            continue
        lanes.setdefault(p["series"], []).append(p)
    for lane in lanes.values():
        lane.sort(key=lambda p: series.puzzle_day(p) or date.min, reverse=True)
    cycle = sorted((s for s in lanes if s not in LAST),
                   key=lambda s: (BY_DEMAND.index(s) if s in BY_DEMAND else len(BY_DEMAND), s))
    return [lanes[s][i]
            for i in range(max((len(lanes[s]) for s in cycle), default=0))
            for s in cycle if i < len(lanes[s])] + [p for s in LAST for p in lanes.get(s, [])] + straight


def held_dir():
    """The clues_only/ of the tree INDEX belongs to: the queue reads one corpus."""
    return INDEX.parent.parent / "clues_only"


def clues_only_rows(filed=()):
    """An index-shaped row for each puzzle held as its clues alone that a
    builder can promote (clues_only.solvable): unannotated, no answers, every
    clue readable, dated by its `year` or `date`. The index lists puzzles/
    alone, so without these the queue never sees them. An id in `filed` (the
    rows already read from puzzles/) is skipped: its puzzle file is the row,
    and a second row would queue it twice."""
    import clues_only
    filed = set(filed)
    rows = []
    for record in clues_only.solvable(held_dir()):
        if record["id"] in filed:
            continue
        row = {"id": record["id"], "series": record["series"],
               "annotated": False, "hasSolutions": False}
        row.update({k: record[k] for k in ("year", "date") if k in record})
        rows.append(row)
    return rows


PUZZLE_NAME = re.compile(r"-[0-9].*\.json\Z")


def corpus_mtimes(tree):
    """(stem, path, mtime) for every puzzle file one year folder under each
    series folder of tree: the files puzzle_paths.puzzle_files() globs
    (*/*/*-[0-9]*.json), in one os.scandir walk. The re-plan stats all ~56k
    of them every hour; through pathlib's glob and a Path per file that was
    ~50 of its ~100 CPU seconds, and at nice 19 on a loaded host the whole
    re-plan ran past POOL_PLAN_SECS and was killed every hour (10-15: 610s,
    659s, 1110s), so the queue was never re-read."""
    out = []

    def dirs(path):
        try:
            with os.scandir(path) as it:
                return [e.path for e in it if e.is_dir()]
        except OSError:
            return []

    for year in (y for s in dirs(tree) for y in dirs(s)):
        try:
            with os.scandir(year) as it:
                for e in it:
                    if PUZZLE_NAME.search(e.name):
                        try:
                            out.append((e.name[:-5], e.path, e.stat().st_mtime))
                        except OSError:
                            continue
        except OSError:
            continue
    return sorted(out, key=lambda t: t[1])


FULL_WALK_SECS = int(os.environ.get("CT_PLAN_FULL_WALK_SECS", 6 * 3600))


def _git(tree, *args):
    """Stdout of git run in tree, or None when it fails."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def plan_state_path(index_path):
    import hashlib
    import tempfile
    key = hashlib.sha1(str(Path(index_path).resolve()).encode()).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"ct-plan-rows-{key}.json"


def changed_since(tree, old_head):
    """Puzzle files git says changed between old_head and HEAD, as paths; None
    when git cannot say. The burn commits every puzzle it touches, and a sync
    brings the others' in as commits, so this is the incremental feed for
    fresh_rows: no walk of the corpus."""
    out = _git(tree, "diff", "--name-only", "-z", "--relative", f"{old_head}..HEAD", "--", ".")
    if out is None:
        return None
    names = [n for n in out.decode("utf-8", "replace").split("\0") if PUZZLE_NAME.search(n)]
    return [Path(tree) / n for n in names if (Path(tree) / n).exists()]


def fresh_rows(rows, index_path=None, files=None, row_of=None, state_path=None):
    """The index's rows, each puzzle file written since the index was rebuilt
    read again (fetch_puzzle.index_row), and a file the index lacks added.

    The burn rebuilds the index once, as it starts, and a run lasts days. Its
    re-plan reads the backlog again so that what was filed or repaired since
    joins the queue, but off that index it saw neither: 10-14 sundaytough-2,
    filed five hours into a run, was not in it, and quiptic-71/166/230/321,
    repaired after the run's annotations failed on them, still read as the
    rows that failed. Every puzzle the run annotated read as un-annotated
    too, so the re-plan could not re-admit any id it had held. A stat of the
    corpus is under a second; only the files newer than the index are read.
    The corpus is the tree the index belongs to, as held_dir()'s is: INDEX
    read at call time, so a test that points it at a scratch index does not
    re-read the whole live corpus (CI 10-15 hung on it, cold row cache).
    files and row_of are for the self-test."""
    index_path = Path(INDEX if index_path is None else index_path)
    try:
        built = Path(index_path).stat().st_mtime
    except OSError:
        return rows
    known = {r["id"] for r in rows}
    saved_rows, state, walked_at = {}, None, time.time()
    if files is None:
        # Incremental: the rows read at the last re-plan, and the commit they
        # were read at. Only what git says changed since is read again; the
        # corpus is walked (57k stats, 100s on a loaded host) at the first
        # re-plan and then every FULL_WALK_SECS, to catch what no commit shows.
        tree = index_path.parent
        state = Path(state_path) if state_path else plan_state_path(index_path)
        head = (_git(tree, "rev-parse", "HEAD") or b"").decode().strip()
        stale = None
        try:
            saved = json.loads(state.read_text(encoding="utf-8"))
            if (saved["built"] == built and head and time.time() - saved["walked_at"] < FULL_WALK_SECS):
                stale = changed_since(tree, saved["head"])
                if stale is not None:
                    saved_rows, walked_at = saved["rows"], saved["walked_at"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if stale is None:
            stale = [Path(path) for stem, path, mtime in corpus_mtimes(tree)
                     if stem not in known or mtime > built]
    else:
        stale = []
        for f in files:
            try:
                if Path(f).stem not in known or Path(f).stat().st_mtime > built:
                    stale.append(f)
            except OSError:
                continue
    if not stale and not saved_rows:
        return rows
    if not stale:
        fresh = []
    elif row_of is None:
        import fetch_puzzle
        import row_cache
        fresh = row_cache.cached_map("fetch_puzzle", fetch_puzzle.index_row, stale,
                                     roots={"index_row_deps"}, deps=fetch_puzzle.index_row_deps)
    else:
        fresh = [row_of(f) for f in stale]
    by_id = dict(saved_rows)
    by_id.update({r["id"]: r for r in fresh if not series.unlisted(r["series"])})
    if state is not None and (stale or not saved_rows) and head:
        try:
            tmp = state.with_name(state.name + f".{os.getpid()}")
            tmp.write_text(json.dumps({"built": built, "head": head, "walked_at": walked_at,
                                       "rows": by_id}), encoding="utf-8")
            os.replace(tmp, state)
        except OSError:
            pass
    out = [by_id.pop(r["id"], r) for r in rows]
    return out + list(by_id.values())


def fresh_self_test():
    import tempfile
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        old, new, added = d / "quiptic-71.json", d / "quiptic-72.json", d / "sundaytough-2.json"
        for f in (old, new, added):
            f.write_text("{}")
        index = d / "index.json"
        index.write_text("{}")
        os.utime(old, (1000, 1000))
        os.utime(index, (2000, 2000))
        os.utime(new, (3000, 3000))
        os.utime(added, (3000, 3000))
        rows = [_row("quiptic-71", "2001-03-26"), _row("quiptic-72", "2001-04-02")]
        reread = []

        def row_of(f):
            reread.append(Path(f).stem)
            return _row(Path(f).stem, "2022-01-01", annotated=Path(f).stem == "quiptic-72")
        got = fresh_rows(rows, index, [old, new, added], row_of)
        want = [("quiptic-71", False), ("quiptic-72", True), ("sundaytough-2", False)]
        if [(r["id"], r["annotated"]) for r in got] != want or sorted(reread) != ["quiptic-72", "sundaytough-2"]:
            print(f"FAIL fresh_rows: {[(r['id'], r['annotated']) for r in got]}, re-read {reread} "
                  f"(want {want}, re-read the two newer than the index)", file=sys.stderr)
            bad += 1
        if fresh_rows(rows, d / "missing.json", [old, new, added], row_of) is not rows:
            print("FAIL fresh_rows without an index should return the rows as they are", file=sys.stderr)
            bad += 1
    return bad + incremental_self_test()


def incremental_self_test():
    """A re-plan after the first reads only what git says changed: no corpus
    walk and no re-read of the rest."""
    import subprocess
    import tempfile
    bad = 0
    walks, reread = [], []
    real_walk = globals()["corpus_mtimes"]

    def counting_walk(tree):
        walks.append(tree)
        return real_walk(tree)

    def row_of(f):
        reread.append(Path(f).stem)
        return _row(Path(f).stem, "2022-01-01", annotated=True)

    def git(d, *a):
        subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                       check=True, capture_output=True)

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        tree = d / "puzzles"
        (tree / "quiptic" / "2001").mkdir(parents=True)
        for n in (71, 72, 73):
            (tree / "quiptic" / "2001" / f"quiptic-{n}.json").write_text("{}")
        index = tree / "index.json"
        index.write_text("{}")
        os.utime(index, (1000, 1000))
        git(d, "init", "-q")
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "one")
        state = d / "state.json"
        rows = [_row("quiptic-71", "2001-03-26")]
        globals()["corpus_mtimes"] = counting_walk
        try:
            fresh_rows(rows, index, None, row_of, state)
            first = (len(walks), sorted(reread))
            walks.clear(), reread.clear()
            got = fresh_rows(rows, index, None, row_of, state)
            idle = (len(walks), sorted(reread), len(got))
            (tree / "quiptic" / "2001" / "quiptic-72.json").write_text('{"a": 1}')
            git(d, "commit", "-q", "-am", "annotate 72")
            walks.clear(), reread.clear()
            got = fresh_rows(rows, index, None, row_of, state)
            after = (len(walks), sorted(reread), [r["id"] for r in got if r["annotated"]])
        finally:
            globals()["corpus_mtimes"] = real_walk
    want = [(1, ["quiptic-71", "quiptic-72", "quiptic-73"]), (0, [], 3),
            (0, ["quiptic-72"], ["quiptic-71", "quiptic-72", "quiptic-73"])]
    if [first, idle, after] != want:
        print(f"FAIL incremental fresh_rows: {[first, idle, after]} (want {want}: one walk the "
              "first time, then only the committed change read, no walk)", file=sys.stderr)
        bad += 1
    return bad


def prune_redo_list():
    """Ghost rows (already fixed, or a convention series) neither block tails nor hide hints.
    Run by --backlog (once per burn launch) and by every --cover-first re-plan, so the 30-minute
    stamp is honoured during a long burn."""
    try:
        import prune_shape_queue
        if (n := prune_shape_queue.auto()) is not None:
            print(f"  shape redo list: pruned {n} settled rows", file=sys.stderr)
    except Exception as e:
        print(f"  shape redo list prune failed: {e}", file=sys.stderr)


CUT_SHORT_LOG = Path(os.environ.get("CT_CUT_SHORT_LOG") or Path.home() / ".cache" / "cut_short_clues.jsonl")


def print_backlog(annotate_blocked, solve_blocked):
    """The queue's ids on stdout, from the index (fresh_rows: each file written
    since it was built read again); its head and how many of it
    are to be solved first on stderr, which is the burn's log. A puzzle whose
    scan is queued for an OCR re-read (scan_queue.open_requests) is left out
    like an annotate-blocked one: its clue may be misread, and the re-read
    decides. $CT_SERIES, a space-separated list of series keys, narrows it to
    those papers. Clues-only puzzles join it as clues_only_rows()."""
    import clue_cutoff
    import scan_queue
    prune_redo_list()
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    rereads ={r["id"] for r in scan_queue.open_requests()}
    if rereads:
        print(f"  {len(rereads)} OCR'd puzzles wait on a re-read of their scan, left out until it lands",
              file=sys.stderr)
    rows = fresh_rows(index["puzzles"])
    held = clues_only_rows({r["id"] for r in rows})
    todo = backlog(rows + held, annotate_blocked.split() + sorted(rereads), solve_blocked.split(),
                   os.environ.get("CT_SERIES", "").split())
    for p in todo[:5]:
        when = (f"{p['year']:<10}" if "year" in p
                else f"{p['date']:<10}" if "date" in p else "  undated  ")
        print(f"  {when}  {p['id']}", file=sys.stderr)
    if len(todo) > 5:
        print(f"  ... and {len(todo) - 5} older", file=sys.stderr)
    print(f"  {sum(1 for p in todo if not p.get('hasSolutions'))} of them lack answers "
          "and are solved cold first", file=sys.stderr)
    queued = {p["id"] for p in todo}
    cut = clue_cutoff.gate(sorted(queued), log=CUT_SHORT_LOG)
    if cut:
        todo = [p for p in todo if p["id"] not in cut]
        queued -= set(cut)
        print(f"  {len(cut)} puzzles hold a clue cut short or garbled (tools/clue_cutoff.py), left out until "
              f"their source is read again: {' '.join(sorted(cut)[:5])}", file=sys.stderr)
    print(f"  {sum(1 for r in held if r['id'] in queued)} of those are held clues-only; "
          "their solve derives the grid", file=sys.stderr)
    print(" ".join(p["id"] for p in todo))
    return 0


def unsolved(pid):
    """Whether the puzzle's file lacks an answer to any entry: the burn solves
    it cold before annotating it. A puzzle held clues-only has no answer yet."""
    import clues_only
    if clues_only.find(pid, held_dir()):
        return True
    from fetch_puzzle import read_puzzle_file
    from puzzle_paths import resolve_puzzle
    return not all(e.get("solution") for e in read_puzzle_file(resolve_puzzle(pid))["entries"])


def newest_first(queue, rows):
    """The queue's ids round-robin newest first (round_robin), whatever order
    they came in; ids the index lacks keep their order at the back."""
    import shape_queue
    by_id = {r["id"]: r for r in rows}
    relist = shape_queue.puzzle_ids()
    # The re-annotation tier stays behind everything un-hinted, whatever the
    # dates: it is sorted apart and appended, never mixed into the round-robin.
    # A puzzle with a hint missing is un-hinted first, wherever it is listed.
    last = [i for i in queue if i in relist and i in by_id and by_id[i]["annotated"]]
    held = set(last)
    return ([r["id"] for r in round_robin([by_id[i] for i in queue if i in by_id and i not in held])]
            + [r["id"] for r in round_robin([by_id[i] for i in last])]
            + [i for i in queue if i not in by_id])


# A series is small, and hinting finishes it before the big dailies, when the
# coverage ledger knows of fewer than "known" of its puzzles, or failing that
# when fewer than "filed" of them are on file (owner 10-12: "Finishing some of
# the smaller puzzles fully might be more useful than getting all the times").
SMALL_SERIES = {"known": 500, "filed": 1500}
# A series this much hinted (hinted / filed) is nearly done, and goes ahead of
# the small ones whatever its size (owner 10-13: "Like the quiptic says 90%
# hinted maybe that's a better set to complete", nation at 65% having taken
# all day).
NEARLY_DONE = 0.85


def small_series(days=None):
    """The nearly-done and small series with puzzles left to hint, in the
    order hinting finishes them: those at least NEARLY_DONE hinted first, then
    those under SMALL_SERIES["known"], then those under SMALL_SERIES["filed"],
    each tier by fewest unhinted (filed - hinted) first.
    Counted off the newest day of tools/data/progress.json (days, else read).
    LAST's lanes stay last: their reasons hold whatever a series' size."""
    import progress
    days = progress.load() if days is None else days
    row = days[max(days)] if days else {}
    ranked = []
    for name, counts in row.items():
        known, filed, left = counts[progress.KNOWN], counts[progress.FILED], \
            counts[progress.FILED] - counts[progress.HINTED]
        tier = (0 if filed and counts[progress.HINTED] >= NEARLY_DONE * filed
                else 1 if known is not None and known < SMALL_SERIES["known"]
                else 2 if filed < SMALL_SERIES["filed"] else None)
        if tier is not None and left > 0 and name not in LAST:
            ranked.append((tier, left, name))
    return [name for *_, name in sorted(ranked)]


# A series with fewer unhinted puzzles than this (and at least one) is finished
# off ahead of everything but the lockout cut-offs and hand requests (owner
# 10-22: "Can we finish off series who has less than 200 unhinted puzzles
# first?").
FINISH_OFF = 200


def finish_off_series(days=None):
    """The series with 0 < unhinted (filed - hinted) < FINISH_OFF on the newest
    day of tools/data/progress.json (days, else read), fewest left first, name
    breaking ties. LAST's lanes stay out, as in small_series."""
    import progress
    days = progress.load() if days is None else days
    row = days[max(days)] if days else {}
    ranked = sorted((counts[progress.FILED] - counts[progress.HINTED], name)
                    for name, counts in row.items() if name not in LAST)
    return [name for left, name in ranked if 0 < left < FINISH_OFF]


def tried_before():
    """Ids the annotate or solve ledger (tools/failed_inputs.py, the one backlog()
    is given) holds out on the puzzle as it is now."""
    import failed_inputs
    data = failed_inputs.load()
    return set(failed_inputs.skipped(data, "annotate")) | set(failed_inputs.skipped(data, "solve"))


def small_first(queue, pinned, rows, small):
    """pinned, then the queue's puzzles in the series of small (small_series),
    series by series in that order, queue order inside each."""
    series_of = {r["id"]: r["series"] for r in rows}
    taken = set(pinned)
    return pinned + [pid for name in small for pid in queue
                     if series_of.get(pid) == name and pid not in taken]


REQUESTS = REPO / "tools" / "data" / "burn_requests.json"


def requested(rows, path=None):
    """The hand-request list (tools/data/burn_requests.json, puzzle ids the owner wants
    hinted first, e.g. rebus puzzles) minus the puzzles now fully annotated: an id
    drops out once the index shows its puzzle annotated with no clue missing."""
    try:
        ids = json.loads(Path(path or REQUESTS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    by_id = {r["id"]: r for r in rows}
    return [i for i in dict.fromkeys(ids)
            if not (by_id.get(i, {}).get("annotated") and not by_id[i].get("unannotated"))]


def requested_first(queue, pinned, want):
    """pinned, then the queue's puzzles named in want (the request list), in the
    list's order."""
    taken, inq = set(pinned), set(queue)
    return pinned + [i for i in want if i in inq and i not in taken]


RECENT_DAYS = 365
# Pinned only by the self-test, so its older fixtures (dated 2026 against a real
# clock) are not all "recent"; None means the real date.
TODAY = None


def recent_first(queue, pinned, rows, today=None):
    """pinned, then the queue's puzzles dated within RECENT_DAYS of today
    (owner 10-20: "puzzles newer than a year should go first"): never-annotated
    ones first, then the tier's redo/backlog work, each newest first. queue is
    already newest first. Returns (order, never annotated count, redo count)."""
    today = today or TODAY or dt.date.today()
    by_id = {r["id"]: r for r in rows}
    taken = set(pinned)
    new, redo = [], []
    for pid in queue:
        row = by_id.get(pid)
        if pid in taken or row is None:
            continue
        day = series.puzzle_day(row)
        if day is None or not 0 <= (today - day).days <= RECENT_DAYS:
            continue
        (redo if row.get("annotated") else new).append(pid)
    return pinned + new + redo, len(new), len(redo)


def partly_hinted(rows):
    """{id: clues it lacks} for the puzzles that have hints and lack some (the
    index's `unannotated`). A run annotates only those clues, so each costs a
    fraction of a puzzle. Dropped 10-04 (fddc75119c), back at the front 10-15."""
    return {r["id"]: r["unannotated"] for r in rows if r.get("unannotated")}


def partly_first(queue, pinned, rows):
    """pinned, then the queue's partly hinted puzzles, fewest clues missing
    first, queue order among equals."""
    missing = partly_hinted(rows)
    taken = set(pinned)
    return pinned + sorted((pid for pid in queue if pid in missing and pid not in taken),
                           key=lambda pid: missing[pid])


def tails_first(queue, pinned, rows):
    """pinned, then the queue's bag-eligible tails (clue_bag.row_is_tail, the
    flagged-clue redo count included) in queue order, ahead of the partly
    hinted and the nearly-done/small-series stages. A bag forms only when its leader is a tail, so tails at the
    head are bagged and run together instead of each paying a session's fixed
    cost; resumes, lockout cut-offs and hand requests stay ahead in `pinned`."""
    import clue_bag
    by_id = {r["id"]: r for r in rows}
    taken = set(pinned)
    return pinned + [pid for pid in queue
                     if pid not in taken and clue_bag.row_is_tail(by_id.get(pid))]


def cold_row(row, kept=False):
    """True when `row` is an index row lacking solutions (a cold solve or a
    clues-only puzzle) and not `kept` at the front by a lockout or request.
    A partial blog key (`partial`, provenance.partial_lights) is not cold: all
    but a light or two are answered, and the solve fills only those."""
    return bool(row) and not kept and not row.get("hasSolutions") and not row.get("partial")


def head_of_queue(queue, pinned, rows, wanted=(), tagged=(), small=(), asked=(), finish=(), tried=()):
    """(the queue newest first, the ids that go ahead of it in order): pinned
    (cut off by a lockout), then the hand requests (asked, requested()), then
    the series to finish off (finish, finish_off_series(); owner 10-22: "Can we
    finish off series who has less than 200 unhinted puzzles first?"), then the
    recent tier (recent_first), then the bag-eligible tails incl. redo ones (tails_first), then the partly hinted (partly_first), then the nearly-done and small series' puzzles
    (small_first), then
    /showcase/'s wanted, then each series' No 1,
    then each series' oldest few, then the notable-tagged; each set in queue
    order but the oldest, which go oldest first. The whole queue is re-sorted,
    so ids the caller appended (puzzles made eligible mid-run) take their
    date's place rather than the back. A puzzle that is not a cryptic
    (`style`) is pinned only by a lockout: round_robin keeps it last."""
    queue = newest_first(queue, rows)
    straight = {r["id"] for r in rows if r.get("style")}
    # The re-annotation tier is pinned by nothing but a lockout: promote(),
    # first_issues() and oldest_per_series() choose from `cryptic` only.
    import shape_queue
    relist = shape_queue.puzzle_ids()
    by_id = {r["id"]: r for r in rows}
    cryptic = [pid for pid in queue if pid not in straight
               and not (pid in relist and by_id.get(pid, {}).get("annotated"))]
    front = list(pinned)
    pinned = requested_first(queue, list(pinned), list(asked))
    asked_n = len(pinned) - len(set(pinned) - set(asked)) if asked else 0
    asked_end = len(pinned)
    # owner 10-22: "don't add the ones that we tried before or see unlikely to
    # work": only an answered puzzle with no annotate or solve failure on record
    # is lifted; the rest stay where the ordering below puts them.
    liftable = [pid for pid in cryptic if pid not in tried
                and by_id.get(pid, {}).get("hasSolutions")]
    pinned = small_first(liftable, pinned, rows, finish)
    base = len(pinned)
    pinned, recent_new, recent_redo = recent_first(
        [pid for pid in queue if pid not in straight], pinned, rows)
    recent = recent_new + recent_redo
    cut = len(pinned)
    # The flagged-clue redo tails are the re-annotation tier (hinted, on the
    # relist), which `cryptic` leaves out: tails are taken from every cryptic.
    pinned = tails_first([pid for pid in queue if pid not in straight], pinned, rows)
    tails = len(pinned) - cut
    pinned = partly_first(cryptic, pinned, rows)
    partly = len(pinned) - cut - tails
    pinned = small_first(cryptic, pinned, rows, small)
    marks = [len(pinned)]
    pinned = promote(cryptic, pinned, wanted)
    marks.append(len(pinned))
    pinned = first_issues(cryptic, pinned)
    pinned = oldest_per_series(cryptic, pinned, rows)
    marks.append(len(pinned))
    pinned = promote(cryptic, pinned, tagged)
    marks.append(len(pinned))
    # Answered puzzles first (owner 10-21: "Should we do the ones with
    # solutions first"): one stable partition of the pins. Cold solves and
    # clues-only ones (cold solves fail ~86%) leave the head for the back of
    # the whole queue; lockout cut-offs and hand requests stay at the front.
    keep = set(front) | set(asked)
    cold = {pid for pid in pinned if pid not in keep and pid in by_id
            and not by_id[pid].get("hasSolutions") and not by_id[pid].get("partial")}
    kept = lambda n: sum(1 for pid in pinned[:n] if pid not in cold)
    stages = [kept(m) for m in marks]
    tails_k = kept(cut + tails) - kept(cut)
    partly_k = kept(cut + tails + partly) - kept(cut + tails)
    new_k = sum(1 for pid in pinned[base:base + recent_new] if pid not in cold)
    redo_k = sum(1 for pid in pinned[base + recent_new:base + recent] if pid not in cold)
    finish_k = sum(1 for pid in pinned[asked_end:base] if pid not in cold)
    deferred = [pid for pid in pinned if pid in cold]
    pinned = [pid for pid in pinned if pid not in cold]
    # The round-robin rest gets the same partition: every cold or clues-only
    # puzzle goes behind every answered one, the formerly pinned ones first
    # (in pin order), then the rest in round-robin order.
    cold_rest = [pid for pid in queue if cold_row(by_id.get(pid), pid in keep) and pid not in cold]
    gone = cold | set(cold_rest)
    queue = [pid for pid in queue if pid not in gone] + deferred + cold_rest
    stages += [partly_k, asked_n, tails_k, new_k, redo_k, finish_k]
    return queue, pinned, stages


# One queue slot in SHAPE_EVERY after the pinned head goes to the shape
# re-annotation tier (owner: reannotate until clean, but keep the hinting slope
# of new puzzles steepest), so the tier drains instead of waiting behind all.
SHAPE_EVERY = 4


def interleave_shape(ordered, head, rows, every=SHAPE_EVERY):
    """`ordered` with the shape-tier puzzles (hinted, on the re-annotation
    list) past its first `head` ids spread one per `every` slots, the rest of
    the order kept; the same ids, each once. Fewer shape puzzles than slots
    leave the others in order; the tier runs out and the rest follow."""
    import shape_queue
    relist = shape_queue.puzzle_ids()
    by_id = {r["id"]: r for r in rows}
    tail = ordered[head:]
    shape = [i for i in tail if i in relist and by_id.get(i, {}).get("annotated")]
    if not shape:
        return list(ordered)
    sset = set(shape)
    rest = iter(i for i in tail if i not in sset)
    shape = iter(shape)
    out, done = [], False
    while not done:
        for slot in range(every):
            nxt = next(shape, None) if slot == every - 1 else None
            if nxt is None:
                nxt = next(rest, None)
                if nxt is None:
                    nxt = next(shape, None)
            if nxt is None:
                done = True
                break
            out.append(nxt)
    return list(ordered[:head]) + out


def best_effort(what, fn, empty, share):
    """fn(), or `empty` when its row cache is too cold to fill within `share`
    of the time left to CT_DEADLINE (tools/budget.py): the re-plan then goes
    without it, and the rows made are stored, so a later re-plan has them.
    The head of the queue (lockout pins, the partly hinted, the small series)
    is read off the index alone, so a cold cache never holds it back."""
    import budget
    whole, left = os.environ.get("CT_DEADLINE"), budget.left()
    if left is not None:
        os.environ["CT_DEADLINE"] = str(time.time() + max(left, 0) * share)
    try:
        return fn()
    except budget.Stopped:
        print(f"{what}: its row cache is cold, so this re-plan goes without it; "
              "the rows made are kept for the next", file=sys.stderr)
        return empty
    finally:
        if whole is not None:
            os.environ["CT_DEADLINE"] = whole


def cover_first(pinned):
    """The ids on stdin, each once, in head_of_queue()'s order with the
    indicator cover behind its pins: exactly the ids given, which is what
    pool_replan checks before taking the order. /showcase/'s wanted and the
    cover are best_effort(): each gets a share of the time to CT_DEADLINE.
    The summary goes to stderr, which is the burn's log."""
    import indicator_cover
    prune_redo_list()
    small, cut, finish = small_series(), len(pinned), finish_off_series()
    # fresh_rows, as --backlog's: off the run-start index a puzzle that gained
    # answers since reads as cold and is deferred
    rows = fresh_rows(index_rows())
    rows = rows + clues_only_rows({r["id"] for r in rows})
    wanted = best_effort("showcase", showcase_wanted, set(), 0.4)
    queue, pinned, n = head_of_queue(list(dict.fromkeys(sys.stdin.read().split())), pinned, rows,
                                     wanted, tagged_puzzles(), small, requested(rows), finish,
                                     tried_before())
    print(f"requested: {n[5]} queued puzzles on tools/data/burn_requests.json go first"
          + (f" ({', '.join(pinned[cut:cut + n[5]])})" if n[5] else ""), file=sys.stderr)
    print(f"finish off: {n[9]} queued puzzles of {', '.join(finish) or 'none'} (under {FINISH_OFF} "
          f"unhinted each) go first", file=sys.stderr)
    print(f"recent: {n[7] + n[8]} queued puzzles dated in the last year go first "
          f"({n[7]} never annotated)", file=sys.stderr)
    cut += n[7] + n[8] + n[9]
    print(f"tails: {n[6]} queued puzzles with a few clues due go first (bagged)",
          file=sys.stderr)
    print(f"partly hinted: {n[4]} queued puzzles with some clues hinted go first",
          file=sys.stderr)
    print(f"nearly-done and small series: {n[0] - cut - n[6] - n[4]} queued puzzles of {', '.join(small) or 'none'} go first",
          file=sys.stderr)
    print(f"showcase: {n[1] - n[0]} queued puzzles /showcase/ wants go first",
          file=sys.stderr)
    print(f"tagged: {n[3] - n[2]} queued puzzles with a notable tag go first",
          file=sys.stderr)
    # Cold solves stay behind every answered puzzle: the cover and the shape
    # tier reorder only the answered part, the cold tail is appended as is.
    by_id, held = {r["id"]: r for r in rows}, set(pinned)
    cold_tail = [p for p in queue if cold_row(by_id.get(p), p in held)]
    gone = set(cold_tail)
    queue = [p for p in queue if p not in gone]
    print(f"answered first: {len(cold_tail)} cold or clues-only puzzles go behind "
          f"the other {len(queue)}", file=sys.stderr)
    ordered, picks, weight = best_effort(
        "indicator cover", lambda: indicator_cover.plan(queue, pinned),
        (indicator_cover.order(queue, {}, {}, pinned)[0], [], {}), 1.0)
    reached = set().union(*(m for _, m in picks))
    head = ", ".join(f"{pid} ({len(m)})" for pid, m in picks[:4])
    print(f"indicator cover: {len(picks)} puzzles reach {len(reached)} of {len(weight)} "
          f"unlinked indicators" + (f"; next {head}" if picks else ""), file=sys.stderr)
    ordered = interleave_shape(ordered, len(pinned), rows) + cold_tail
    print("\n".join(ordered))
    return 0


def main():
    if "--cover-first" in sys.argv:
        at = sys.argv.index("--cover-first")
        return cover_first(" ".join(sys.argv[at + 1:]).split())
    if "--rush" in sys.argv:
        rest = sys.argv[sys.argv.index("--rush") + 1:]
        return set_rush(rest[0] if rest and not rest[0].startswith("-") else None)
    if "--resets" in sys.argv:
        return show_resets()
    if "--natural-only" in sys.argv:
        rest = sys.argv[sys.argv.index("--natural-only") + 1:]
        return set_natural_only(rest[0] if rest and not rest[0].startswith("-") else None)
    if "--weekly" in sys.argv:  # the only mode now; kept for old callers
        return 0
    if "--self-test" in sys.argv:
        return self_test()
    if "--backlog" in sys.argv:
        at = sys.argv.index("--backlog")
        args = sys.argv[at + 1:] + ["", ""]
        return print_backlog(args[0], args[1])
    if "--unsolved" in sys.argv:
        return 0 if unsolved(sys.argv[sys.argv.index("--unsolved") + 1]) else 1
    if "--width" in sys.argv:
        at = sys.argv.index("--width")
        print(width(sys.argv[at + 1] if at + 1 < len(sys.argv) else None,
                    0 if "--may-pause" in sys.argv else 1))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
