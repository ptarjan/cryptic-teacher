#!/usr/bin/env python3
"""How wide the pre-reset backfill runs, and in what order it takes the queue.

The job's goal is every five-hour window spent to 100%: quota left on a window
when it turns over is gone. Interactive bridge work comes first, so the burn
takes only what would otherwise be wasted. It keeps in flight the width that
would spend, by the reset, what the window has left after the bridge's own
projected spend, and no more than the machine has free once everything else
on it is counted: memory over the size of a run, and idle cores over a run's
measured CPU.

The queue order is the round-robin tools/prereset_backfill.sh builds, with the
puzzles a lockout cut off first, then each series' first puzzle
(series.is_first_issue), then the partly annotated ones, fewest clues
missing first, then Cracking the Cryptic's puzzles, then the puzzles with a
notable tag (tools/puzzle_tags.py), then the indicator cover
(tools/indicator_cover.py).

    tools/prereset_plan.py [--may-pause] --width [CURRENT]  # runs to keep in flight
    ids | tools/prereset_plan.py --cover-first "PINNED"   # the queue, cover first
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

import series

REPO = Path(__file__).resolve().parent.parent

# Running wider than the need only spends the window early, which locks the
# account out until the reset, so the need sets the width. It aims at the reset
# itself, rounded rather than rounded up: re-read at every checkpoint, the need
# corrects for the per-run rate's interval-to-interval noise as the reset nears.
# The five-hour window. A reset the meter puts in the past means the window has
# turned over since it was read: the whole of a fresh one is left to spend.
WINDOW_HOURS = 5.0
# The width when neither the meter nor the last logged width can be read.
DEFAULT_WIDTH = 14
# The ceiling when memory cannot be read: ~6 GB of runs.
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

# The bridge's spend until the reset is its rate over the last SPEND_WINDOW_S:
# the five-hour meter's rise in usage-history.csv, split between the burn and
# everything else by the tokens their transcripts record in the same span.
# A token is weighted by its list price: per token type relative to uncached
# input, times the model family's input price in $/MTok (an unknown family
# costs as Opus). The burn's own turns are the records whose cwd is this tree.
SPEND_WINDOW_S = 3600
METER_STALE_S = 900
TOKEN_WEIGHT = {"input_tokens": 1.0, "cache_creation_input_tokens": 1.25,
                "cache_read_input_tokens": 0.1, "output_tokens": 5.0}
MODEL_WEIGHT = {"opus": 5.0, "sonnet": 3.0, "haiku": 1.0}
# The burn's per-run rate from the transcripts needs this many run-hours in
# the window, else the log's rate below stands.
RUN_HOURS_MIN = 0.25

# Five-hour points one run in flight spends per hour. Measured off the burn's own
# meter lines in .prereset.log (see per_run_rate); this is the fallback when
# too few are readable: 27 points an hour at width 14 over 60 intervals.
PER_RUN_RATE = 1.95
# The meter line after_wave logs at every pool checkpoint:
#   five-hour 68% -> 70% in 0.083h at width 12.40 (pool of 14)
# where the width is the runs in flight on average over the interval, measured.
# A line from the wave scheduler ("at width 14", every run in flight for the
# whole wave) reads the same way.
METER_LINE = re.compile(r"five-hour (\d+)% -> (\d+)% in ([\d.]+)h at width (\d+(?:\.\d+)?)")
# The width the burn last ran at: "--- pool of 14: ..." at every checkpoint,
# or "--- wave of 14: ..." from the wave scheduler.
WIDTH_LINE = re.compile(r"^--- (?:pool|wave) of (\d+):")
RATE_LINES = 60
RATE_MIN_LINES = 10


def per_run_rate(lines):
    """Five-hour points per run-hour over the last RATE_LINES meter lines logged.
    An interval whose meter fell crossed a reset and says nothing, so it is
    skipped."""
    points = run_hours = 0.0
    meters = [m for m in map(METER_LINE.search, lines) if m][-RATE_LINES:]
    used = 0
    for m in meters:
        before, after, hours, width = int(m[1]), int(m[2]), float(m[3]), float(m[4])
        if after < before or hours <= 0 or width <= 0:
            continue
        points += after - before
        run_hours += hours * width
        used += 1
    if used < RATE_MIN_LINES or points <= 0:
        return PER_RUN_RATE
    return points / run_hours


def need(pct, hours_left, rate, bridge_rate=0.0):
    """Runs that would spend, by the reset, what the five-hour window has left
    after the bridge's projected spend (bridge_rate points an hour), 0 when the
    bridge alone spends it. A reset already passed is a fresh window, all of it
    left. None when any input is missing or unusable."""
    try:
        if pct is not None and hours_left <= 0:
            pct, hours_left = 0, WINDOW_HOURS
        if rate <= 0:
            return None
        left = 100 - pct - max(0.0, bridge_rate or 0.0) * hours_left
        return max(0, round(left / (hours_left * rate)))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def meter_rise(csv_text, start, end):
    """(points, hours) the five-hour meter rose over its rows in [start, end]:
    the sum of its rises, a fall being a reset. None with under two rows, or
    when the newest is more than METER_STALE_S before end."""
    rows = []
    for line in (csv_text or "").splitlines():
        f = line.split(",")
        try:
            if len(f) >= 3 and f[1] == "five_hour" and start <= float(f[0]) <= end:
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


def cpu_cap(others, burn, cores, runs):
    """Runs the cores other load leaves idle can hold: (cores - others) over one
    run's share of the burn's CPU (runs being the burn's claude processes now),
    all in cores. None when no run is in flight or the burn used no CPU to
    measure a run by."""
    if not cores or not runs or not burn or burn <= 0 or others is None:
        return None
    return max(0, int((cores - others) / (burn / runs)))


def width_for(runs_needed, mem, cpu, current, floor=1):
    """The need (else the current width, else DEFAULT_WIDTH), capped by memory
    (else DEFAULT_CEILING) and by the idle cores (when measured). At least
    floor: 0 for a shell that naps at width 0 (--may-pause), else 1."""
    w = runs_needed if runs_needed is not None else current or DEFAULT_WIDTH
    w = min(w, DEFAULT_CEILING if mem is None else mem)
    if cpu is not None:
        w = min(w, cpu)
    return max(floor, w)


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
    import weekly_usage
    now = now or time.time()
    rise = meter_rise(_read(weekly_usage.SAMPLE_CSV_PATH), now - SPEND_WINDOW_S, now)
    if not rise:
        return None, None
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return split_rates(rise, *transcript_spend(config / "projects", REPO,
                                               now - rise[1] * 3600, now))


def width(arg=None, floor=1):
    """The width to keep in flight, from the live five-hour meter and reset, the
    bridge's measured spend, the burn's rate and last width, and the machine.
    The inputs go to stderr."""
    home = Path(os.environ.get("CT_MAIN_CHECKOUT") or REPO)
    lines = (_read(home / ".prereset.log") or "").splitlines()
    current = current_width(arg, lines)
    runs_needed = bridge = None
    try:
        import weekly_usage
        pct = weekly_usage.usage_pct("session")
        hours_left, _ = weekly_usage.resets_in_hours("session")
        bridge, rate = bridge_spend()
        rate = rate or per_run_rate(lines)
        runs_needed = need(pct, hours_left, rate, bridge or 0.0)
    except Exception as exc:  # noqa: BLE001 — an unread meter leaves the need unknown
        print(f"width: meter unread: {exc}", file=sys.stderr)
    rss = burn_rss_kb()
    mem = mem_cap(_read("/proc/meminfo"), rss)
    load = cpu_load(home / CPU_STATE)
    cpu = cpu_cap(*load, os.cpu_count(), len(rss)) if load else None
    w = width_for(runs_needed, mem, cpu, current, floor)
    shown = (f"{bridge:.1f} pts/h" if bridge is not None else "unread")
    cores = (f"others {load[0]:.2f} burn {load[1]:.2f} of {os.cpu_count()} cores"
             if load else "cores unread")
    print(f"width {w}: need {runs_needed} (bridge {shown}), memory cap {mem}, "
          f"cpu cap {cpu} ({cores}), current {current}", file=sys.stderr)
    return w


def self_test():
    """The backlog order: a puzzle whose blog names an indicator none of our
    annotations links yet jumps the queue, weighted by that indicator's clues."""
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
    bad = (cover_self_test(covers) + width_self_test() + tag_self_test()
           + first_self_test())
    n = (len(covers) + len(WIDTH_CASES) + len(NEED_CASES) + len(MEM_CASES)
         + len(CPU_CASES) + len(METER_CASES) + 21 + len(TAG_CASES) + 2 + len(FIRST_CASES))
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
    ((0, 40, 40, 14), 1),          # bridge spends the window: one run, for an old shell
    ((0, 40, 40, 14, 0), 0),       # ...and none for one that naps at 0
    ((26, 40, 0, 14, 0), 0),       # no core idle, for one that naps
]
# (pct, hours to reset, per-run rate, bridge points an hour) -> need
NEED_CASES = [
    ((90, 2.0, 1.95, 0), 3),      # 10 points over 3.9 run-hours
    ((60, 1.0, 1.95, 0), 21),     # 40 points in 1h
    ((100, 1.0, 1.95, 0), 0),     # window spent
    ((None, 1.0, 1.95, 0), None),
    ((50, 0.0, 1.95, 0), 10),     # reset passed: a fresh window, 100 points in 5h
    ((100, -0.1, 1.95, 0), 10),   # the meter still shows the window just spent
    ((50, None, 1.95, 0), None),  # reset unread
    # The bridge's projected spend comes off the top: the burn takes the surplus.
    ((60, 1.0, 1.95, 20), 10),    # bridge takes 20 of the 40 points left
    ((40, 4.0, 1.95, 10), 3),     # 60 left, bridge 40 of it by the reset
    ((40, 4.0, 1.95, 15), 0),     # bridge alone spends the window: nothing to take
    ((48, 4.0, 4.4, 38), 0),      # 2026-10-01 08:40: bridge at 38 points an hour
    ((50, 0.0, 1.95, 10), 5),     # fresh window: 100 - 50 over 5h
    ((60, 1.0, 1.95, None), 21),  # bridge unmeasured: nothing subtracted
]
# (csv text, start, end) -> (points, hours) the five-hour meter rose
_ROW = "{},five_hour,{},9999999999\n{},seven_day,50,9999999999\n"
METER_CASES = [
    ("".join(_ROW.format(t, p, t) for t, p in [(0, 10), (1800, 14), (3600, 20)]),
     0, 3600, (10.0, 1.0)),
    # a reset between rows: the fall is skipped, the rise after it counts
    ("".join(_ROW.format(t, p, t) for t, p in [(0, 90), (1800, 2), (3600, 6)]),
     0, 3600, (4.0, 1.0)),
    # newest row too old to say anything about now
    ("".join(_ROW.format(t, p, t) for t, p in [(0, 10), (600, 12)]), 0, 3600, None),
    (_ROW.format(3000, 10, 3000), 0, 3600, None),
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
# (cores other processes use, cores the burn uses, cores, runs) -> cpu cap
CPU_CASES = [
    (0.5, 1.0, 4, 4, 14),     # idle box: 3.5 cores at 0.25 a run
    (3.0, 1.0, 4, 4, 4),      # the bridge busy on 3 cores: the burn shrinks
    (4.0, 1.0, 4, 4, 0),      # nothing idle
    (5.0, 1.0, 4, 4, 0),      # overcommitted
    (0.5, 0.0, 4, 4, None),   # no burn CPU to measure a run by
    (0.5, 1.0, 4, 0, None),   # no run in flight
    (None, 1.0, 4, 4, None),
]


def width_self_test():
    """The cases above, the rate and current width read off the log, and a
    failed read still giving a positive width."""
    bad = 0
    checks = ([(width_for, a, w) for a, w in WIDTH_CASES]
              + [(need, a, w) for a, w in NEED_CASES]
              + [(mem_cap, (m, r), w) for m, r, w in MEM_CASES]
              + [(cpu_cap, (o, b, c, r), w) for o, b, c, r, w in CPU_CASES]
              + [(meter_rise, (t, a, b), w) for t, a, b, w in METER_CASES])
    for fn, args, want in checks:
        if fn(*args) != want:
            print(f"FAIL {fn.__name__}{args} = {fn(*args)} (want {want})", file=sys.stderr)
            bad += 1
    line = "  weekly 1% -> 1%, five-hour {}% -> {}% in 0.1h at width 14"
    logged = [line.format(i, i + 3) for i in range(12)] + [line.format(90, 2)]
    # pool lines: 0.5h at 12.5 in flight on average is 6.25 run-hours
    pool = "  weekly 1% -> 1%, five-hour {}% -> {}% in 0.5h at width 12.50 (pool of 14)"
    pooled = [pool.format(i, i + 5) for i in range(12)]
    # old and new lines together: 12 x 3 + 12 x 5 points over 12 x (1.4 + 6.25)
    mixed = logged[:12] + pooled
    for lines, want in [(logged, 3 / 1.4), (logged[:3], PER_RUN_RATE),
                        (pooled, 5 / 6.25), (mixed, 96 / (12 * 7.65)),
                        # an interval with nothing in flight says nothing
                        (pooled[:9] + [pool.format(5, 9).replace("12.50", "0.00")],
                         PER_RUN_RATE)]:
        if abs(per_run_rate(lines) - want) > 1e-9:
            print(f"FAIL per_run_rate of {len(lines)} lines = {per_run_rate(lines)} "
                  f"(want {want})", file=sys.stderr)
            bad += 1
    waves = ["--- wave of 14: a b ---", "x", "--- wave of 9: c ---", "  weekly ..."]
    pools = waves + ["--- pool of 11: 3 in flight, 40 queued ---", "  [a] started"]
    for arg, lines, want in [("12", waves, 12), (None, waves, 9), ("0", waves, 9),
                             ("x", [], None), (None, ["--- wave of 0: ---"], None),
                             (None, pools, 11), ("7", pools, 7),
                             (None, ["--- pool of 0: ---"], None)]:
        if current_width(arg, lines) != want:
            print(f"FAIL current_width({arg!r}, {lines}) = {current_width(arg, lines)} "
                  f"(want {want})", file=sys.stderr)
            bad += 1
    bad += spend_self_test() + tree_self_test()
    import weekly_usage
    real = weekly_usage.usage_pct
    def unreadable(_group):
        raise RuntimeError("no reading")
    weekly_usage.usage_pct = unreadable
    try:
        got = width("7")
        if not isinstance(got, int) or got < 1:
            print(f"FAIL width() with the meter unread = {got!r} (want a positive int)",
                  file=sys.stderr)
            bad += 1
    finally:
        weekly_usage.usage_pct = real
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
    (["metro-20250403", "globeandmail-1", "book-1001", "book-1"], [], []),
    # pinned once, not twice
    (["listener-1"], ["listener-1"], ["listener-1"]),
]


def first_self_test():
    bad = 0
    for queue, pinned, want in FIRST_CASES:
        got = first_issues(queue, list(pinned))
        if got != want:
            print(f"FAIL first_issues({queue}, {pinned}) = {got} (want {want})", file=sys.stderr)
            bad += 1
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


def ctc_puzzles():
    """Puzzles Cracking the Cryptic solved on video (tools/ctc_transcripts.py).
    Their praise is our only human signal of what makes a clue good, and a
    praised clue teaches the setting prompt nothing until it is annotated."""
    path = REPO / "tools/data/ctc_moments.json"
    if not path.exists():
        return set()
    return {v["puzzle"] for v in json.loads(path.read_text())["videos"] if v["puzzle"]}


# Tags too common to jump the queue on. A plain pangram is about one puzzle in
# thirty and "barred" is every Mephisto: promoting either would have the burn do
# little else, which is what queue-jumping the SNITCH-rated Times did (be5b581,
# reverted 4d49a1b). Every other tag is rare, and its puzzles are the ones a
# solver goes looking for.
COMMON_TAGS = {"pangram", "barred"}
INDEX = REPO / "puzzles" / "index.json"


def tagged_puzzles(index_path=INDEX):
    """{id: its tags outside COMMON_TAGS} from the index, which the burn
    rebuilds as it starts, so a puzzle tagged since is promoted on the next run.
    Empty when there is no index to read."""
    try:
        index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for row in index.get("puzzles", []) + index.get("unlisted", []):
        notable = [t for t in row.get("tags", ()) if t not in COMMON_TAGS]
        if notable:
            out[row["id"]] = notable
    return out


def first_issues(queue, pinned):
    """pinned, then the queue's series-first puzzles in queue order. Paul,
    2026-10-02: "Puzzle 1 is a special puzzle ... our solver should
    prioritize them"."""
    return pinned + [pid for pid in queue if series.is_first_issue(pid) and pid not in pinned]


def promote(queue, pinned, tagged):
    """pinned, then the queue's tagged puzzles in queue order: the new pinned."""
    return pinned + [pid for pid in queue if pid in tagged and pid not in pinned]


def partly_annotated(index_path=INDEX):
    """{id: clues it lacks} for the puzzles that have hints and lack some (the
    index's `unannotated`). A run annotates only those clues, so each costs a
    fraction of a puzzle. Empty when there is no index to read."""
    try:
        index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {r["id"]: r["unannotated"]
            for r in index.get("puzzles", []) + index.get("unlisted", [])
            if r.get("unannotated")}


def cover_first(pinned):
    """The ids on stdin, reordered: pinned first, then each series' first
    puzzle, then the partly annotated
    puzzles, then Cracking the Cryptic's puzzles, then the puzzles with a
    notable tag, then the indicator cover, then the rest as they came. The
    summary goes to stderr, which is the burn's log."""
    import indicator_cover
    queue = sys.stdin.read().split()
    ctc = ctc_puzzles()
    partial = partly_annotated()
    pinned = first_issues(queue, pinned)
    pinned = pinned + sorted((pid for pid in queue if pid in partial and pid not in pinned),
                             key=partial.get)
    pinned = pinned + [pid for pid in queue if pid in ctc and pid not in pinned]
    tagged = tagged_puzzles()
    before = len(pinned)
    pinned = promote(queue, pinned, tagged)
    print(f"tagged: {len(pinned) - before} queued puzzles with a notable tag go first",
          file=sys.stderr)
    ordered, picks, weight = indicator_cover.plan(queue, pinned)
    reached = set().union(*(m for _, m in picks))
    head = ", ".join(f"{pid} ({len(m)})" for pid, m in picks[:4])
    print(f"indicator cover: {len(picks)} puzzles reach {len(reached)} of {len(weight)} "
          f"unlinked indicators" + (f"; next {head}" if picks else ""), file=sys.stderr)
    print("\n".join(ordered))
    return 0


def main():
    if "--cover-first" in sys.argv:
        at = sys.argv.index("--cover-first")
        return cover_first(" ".join(sys.argv[at + 1:]).split())
    if "--self-test" in sys.argv:
        return self_test()
    if "--width" in sys.argv:
        at = sys.argv.index("--width")
        print(width(sys.argv[at + 1] if at + 1 < len(sys.argv) else None,
                    0 if "--may-pause" in sys.argv else 1))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
