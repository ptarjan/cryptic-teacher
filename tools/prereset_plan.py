#!/usr/bin/env python3
"""How wide the pre-reset backfill runs, and in what order it takes the queue.

The job's goal is the paced meter spent to EXHAUSTED right at its reset:
quota left on a window when it turns over is gone, and quota spent early locks
Paul's rooms out until it turns over. Interactive bridge work comes first, so
the burn takes only what would otherwise be wasted. It keeps in flight the
width that would spend, evenly until that meter's reset, what it has left
after the bridge's own projected spend (paced_need), and no more than the
machine has free once everything else on it is counted: memory over the size
of a run, and idle cores over a run's measured CPU.

Which meter is paced is the mode. Weekly, the default: the weekly meter, to
the weekly reset; a five-hour lockout is napped through by
prereset_backfill.sh. Five-hour, for when Paul has weekly resets to spend:
each five-hour window to its own reset, with no weekly pacing, since he resets
the week by hand. `--five-hour` writes FIVE_HOUR holding the current weekly
reset, and while that reset stands the mode is five-hour; a reset that moves
(Paul's, or the week's own) retires it, as does `--weekly`.

The queue is backlog(): every un-annotated puzzle, those without all their
answers included (the burn solves them cold, then annotates them), and every
puzzle held as its clues alone (tools/clues_only.py), whose solve derives its
grid in tools/apply_solution.py as the nightly's does. Those rank by the same
rules as an index row: clues_only_rows() gives them one. Its order
is head_of_queue()'s: the puzzles a lockout cut off first,
then the puzzles /showcase/ would pick once annotated (showcase.wanted), then
each series' first puzzle (series.is_first_issue), then each series'
OLDEST_PER_SERIES oldest puzzles, oldest first, then the puzzles with a notable
tag (tools/puzzle_tags.py), then the indicator cover (tools/indicator_cover.py),
then the rest round-robin across the series, newest first inside each one.

    tools/prereset_plan.py [--may-pause] --width [CURRENT]  # runs to keep in flight
    tools/prereset_plan.py --backlog "ANNOTATE_BLOCKED" "SOLVE_BLOCKED"  # the queue
    tools/prereset_plan.py --unsolved ID      # exit 0 when ID lacks any answer
    ids | tools/prereset_plan.py --cover-first "PINNED"   # the queue, cover first
    tools/prereset_plan.py --five-hour        # pace five-hour windows until this week resets
    tools/prereset_plan.py --weekly           # pace the weekly meter (the default)
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

# Running wider than a need only spends its window early, which locks the
# account out until that window's reset, so the needs set the width. Each aims
# at its reset itself, rounded rather than rounded up: re-read at every
# checkpoint, a need corrects for the per-run rate's interval-to-interval noise
# as the reset nears. A reset the meter puts in the past means the window has
# turned over since it was read: the whole of a fresh one is left to spend.
WINDOW_HOURS = {"weekly": 7 * 24.0, "session": 5.0}
# The level the paced meter's need aims at, the same in either mode:
# prereset_backfill.sh stops at it on the weekly meter, and exports its own value.
EXHAUSTED = float(os.environ.get("EXHAUSTED") or 99)
# The rates are measured on the five-hour meter, which moves several points for
# each weekly one. Five-hour points per weekly point is the two meters' rises
# side by side in usage-history.csv over the last RATIO_SPAN_S, skipping any
# interval where either fell (a reset); under RATIO_MIN_POINTS weekly points
# leaves it unknown.
RATIO_SPAN_S = 7 * 86400
RATIO_MIN_POINTS = 10
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
FIVE_HOUR = ".prereset.five-hour"

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
METER_LINE = re.compile(r"five-hour (\d+)% -> (\d+)% in ([\d.]+)h at width (\d+(?:\.\d+)?)")
# The width the burn last ran at: "--- pool of 14: ..." at every checkpoint.
WIDTH_LINE = re.compile(r"^--- pool of (\d+):")
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


def paced_need(meter, pct, hours_left, rate, bridge_rate, ratio):
    """Runs that would spend, by the meter's reset, what it has left up to
    EXHAUSTED after the bridge's projected spend, 0 when the bridge alone spends
    it. meter is "weekly" or "session" (the five-hour window); pct and
    hours_left are its; rate (per run-hour) and bridge_rate (an hour) are
    five-hour points, ratio five-hour points per point of the meter (1 for the
    five-hour one). A reset already passed is a fresh window, all of it left.
    None when any input is missing or unusable."""
    try:
        if pct is not None and hours_left <= 0:
            pct, hours_left = 0, WINDOW_HOURS[meter]
        if rate <= 0 or ratio <= 0:
            return None
        left = (EXHAUSTED - pct) * ratio - max(0.0, bridge_rate or 0.0) * hours_left
        return max(0, round(left / (hours_left * rate)))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def five_per_weekly(csv_text, start, end):
    """Five-hour points per weekly point over the rows in [start, end]: the sum
    of the five-hour meter's rises over the weekly meter's, in the intervals
    where both were read and neither fell. None under RATIO_MIN_POINTS weekly."""
    rows = {}
    for line in (csv_text or "").splitlines():
        f = line.split(",")
        try:
            if len(f) >= 3 and start <= float(f[0]) <= end:
                rows.setdefault(float(f[0]), {})[f[1]] = float(f[2])
        except ValueError:
            continue
    both = [r for _, r in sorted(rows.items()) if "five_hour" in r and "seven_day" in r]
    five = weekly = 0.0
    for a, b in itertools.pairwise(both):
        d5, d7 = b["five_hour"] - a["five_hour"], b["seven_day"] - a["seven_day"]
        if d5 >= 0 and d7 >= 0:
            five, weekly = five + d5, weekly + d7
    return five / weekly if weekly >= RATIO_MIN_POINTS else None


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


def mode(stamp, resets_at):
    """The meter the burn paces: "session" (five-hour) when FIVE_HOUR's stamp
    is this week's reset, else "weekly"."""
    try:
        return "session" if abs(float(stamp) - resets_at) < 3600 else "weekly"
    except (TypeError, ValueError):
        return "weekly"


def set_mode(meter):
    """--five-hour stamps FIVE_HOUR with this week's reset; --weekly removes it."""
    home = Path(os.environ.get("CT_MAIN_CHECKOUT") or REPO)
    if meter == "weekly":
        (home / FIVE_HOUR).unlink(missing_ok=True)
        print("pacing the weekly meter to the weekly reset")
        return 0
    import weekly_usage
    hours_left, _ = weekly_usage.resets_in_hours("weekly")
    resets_at = time.time() + hours_left * 3600
    (home / FIVE_HOUR).write_text(f"{resets_at:.0f}\n")
    print(f"pacing each five-hour window to its reset until the weekly reset at "
          f"{dt.datetime.fromtimestamp(resets_at, dt.timezone.utc).astimezone():%Y-%m-%d %H:%M} "
          "moves or arrives")
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
    import weekly_usage
    now = now or time.time()
    rise = meter_rise(_read(weekly_usage.SAMPLE_CSV_PATH), now - SPEND_WINDOW_S, now)
    if not rise:
        return None, None
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return split_rates(rise, *transcript_spend(config / "projects", REPO,
                                               now - rise[1] * 3600, now))


def width(arg=None, floor=1):
    """The width to keep in flight, from the live weekly meter and reset, the
    bridge's measured spend, the burn's rate and last width, the five-hour to
    weekly ratio, and the machine. The inputs go to stderr."""
    home = Path(os.environ.get("CT_MAIN_CHECKOUT") or REPO)
    lines = (_read(home / ".prereset.log") or "").splitlines()
    current = current_width(arg, lines)
    runs_needed = bridge = ratio = pct = hours_left = None
    meter = "weekly"
    try:
        import weekly_usage
        now = time.time()
        meter = mode(_read(home / FIVE_HOUR),
                     now + weekly_usage.resets_in_hours("weekly")[0] * 3600)
        bridge, rate = bridge_spend()
        rate = rate or per_run_rate(lines)
        ratio = (1.0 if meter == "session" else
                 five_per_weekly(_read(weekly_usage.SAMPLE_CSV_PATH), now - RATIO_SPAN_S, now))
        pct = weekly_usage.usage_pct(meter)
        hours_left, _ = weekly_usage.resets_in_hours(meter)
        runs_needed = paced_need(meter, pct, hours_left, rate, bridge or 0.0, ratio)
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
    per = (f", {ratio:.2f} five-hour pts per weekly" if ratio else ", ratio unread"
           ) if meter == "weekly" else ""
    name = "five-hour" if meter == "session" else "weekly"
    at = (f"{pct:g}% now, {hours_left:.1f}h to its reset"
          if pct is not None and hours_left is not None else "meter unread")
    print(f"width {w}: need {runs_needed} for {name} {EXHAUSTED:g}% at its reset ({at}; "
          f"bridge {shown}{per}), memory cap {mem}, "
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
           + first_self_test() + backlog_self_test())
    n = (len(covers) + len(WIDTH_CASES) + len(NEED_CASES) + len(MODE_CASES) + len(MEM_CASES)
         + len(CPU_CASES) + len(METER_CASES) + len(RATIO_CASES) + 21 + len(TAG_CASES) + 2 + len(FIRST_CASES) + 3 + 4
         + len(BACKLOG_CASES) + 3)
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
# (meter, its pct, hours to its reset, per-run rate and bridge points an hour
#  in five-hour points, five-hour points per meter point) -> need; EXHAUSTED is 99
NEED_CASES = [(("weekly",) + a, w) for a, w in [
    ((89, 10.0, 2.0, 0, 6.0), 3),     # 10 weekly = 60 five-hour over 10h at 2 a run
    ((59, 10.0, 2.0, 0, 6.0), 12),    # 40 weekly = 240 over 20 run-hours a run
    ((99, 10.0, 2.0, 0, 6.0), 0),     # week spent to EXHAUSTED
    ((100, 10.0, 2.0, 0, 6.0), 0),    # past it
    ((None, 10.0, 2.0, 0, 6.0), None),
    ((50, None, 2.0, 0, 6.0), None),  # reset unread
    ((50, 10.0, 2.0, 0, None), None),  # ratio unread
    ((50, 10.0, 0, 0, 6.0), None),    # no rate
    # reset passed: a fresh week, 99 x 6 points over 168h at 2 a run-hour
    ((50, 0.0, 2.0, 0, 6.0), 2),
    ((100, -0.1, 2.0, 0, 6.0), 2),    # the meter still shows the week just spent
    # The bridge's projected spend comes off the top: the burn takes the surplus.
    ((59, 10.0, 2.0, 12, 6.0), 6),    # bridge 120 of the 240 left by the reset
    ((59, 10.0, 2.0, 24, 6.0), 0),    # bridge alone spends the week
    ((59, 10.0, 2.0, None, 6.0), 12),  # bridge unmeasured: nothing subtracted
    # weekly 10% with 58h to go, bridge 4 an hour, 1.95 a run, 6.5
    ((10, 58.0, 1.95, 4, 6.5), 3),
]] + [(("session",) + a, w) for a, w in [
    # five-hour mode: 71 points left over 4h, bridge 10 an hour, 2 a run-hour
    ((28, 4.0, 2.0, 10, 1.0), 4),
    ((28, 4.0, 2.0, 0, 1.0), 9),      # a quiet bridge leaves the burn more
    ((28, 4.0, 2.0, 18, 1.0), 0),     # the rooms alone spend the window
    # near its reset: 9 points in the last 0.25h, wide but only to land at 99
    ((90, 0.25, 2.0, 0, 1.0), 18),
    ((99, 0.25, 2.0, 0, 1.0), 0),     # at EXHAUSTED: none, never on into a lockout
    # reset passed: a fresh 5h window, 99 over 5h at 2 a run-hour
    ((97, -0.05, 2.0, 0, 1.0), 10),
]]
# (FIVE_HOUR's stamp, this week's reset) -> the meter paced
MODE_CASES = [
    ("1000000\n", 1000000.0, "session"),
    ("1000000\n", 1001800.0, "session"),   # the reset read a little differently
    ("1000000\n", 1000000.0 + 7 * 86400, "weekly"),  # the week has reset: retired
    (None, 1000000.0, "weekly"),             # no marker: the default
    ("garbage", 1000000.0, "weekly"),
]
# (csv text, start, end) -> five-hour points per weekly point
_PAIR = "{0},five_hour,{1},9999999999\n{0},seven_day,{2},9999999999\n"
RATIO_CASES = [
    ("".join(_PAIR.format(t, f, w) for t, f, w in [(0, 0, 10), (1, 60, 20)]),
     0, 9, 6.0),
    # a five-hour reset: that interval says nothing, the next one counts
    ("".join(_PAIR.format(t, f, w) for t, f, w in
             [(0, 0, 10), (1, 60, 20), (2, 5, 21), (3, 65, 31)]), 0, 9, 6.0),
    # a weekly reset likewise
    ("".join(_PAIR.format(t, f, w) for t, f, w in
             [(0, 0, 90), (1, 60, 2), (2, 120, 12)]), 0, 9, 6.0),
    # rows outside the span are left out: too few weekly points then
    ("".join(_PAIR.format(t, f, w) for t, f, w in [(0, 0, 10), (5, 60, 20)]),
     1, 9, None),
    ("garbage", 0, 9, None),
    (None, 0, 9, None),
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
              + [(paced_need, a, w) for a, w in NEED_CASES]
              + [(mode, (st, r), w) for st, r, w in MODE_CASES]
              + [(mem_cap, (m, r), w) for m, r, w in MEM_CASES]
              + [(cpu_cap, (o, b, c, r), w) for o, b, c, r, w in CPU_CASES]
              + [(meter_rise, (t, a, b), w) for t, a, b, w in METER_CASES]
              + [(five_per_weekly, (t, a, b), w) for t, a, b, w in RATIO_CASES])
    for fn, args, want in checks:
        if fn(*args) != want:
            print(f"FAIL {fn.__name__}{args} = {fn(*args)} (want {want})", file=sys.stderr)
            bad += 1
    line = "  weekly 1% -> 1%, five-hour {}% -> {}% in 0.1h at width 14"
    logged = [line.format(i, i + 3) for i in range(12)] + [line.format(90, 2)]
    # pool lines: 0.5h at 12.5 in flight on average is 6.25 run-hours
    pool = "  weekly 1% -> 1%, five-hour {}% -> {}% in 0.5h at width 12.50 (pool of 14)"
    pooled = [pool.format(i, i + 5) for i in range(12)]
    # lines with and without the pool suffix: 12 x 3 + 12 x 5 points over 12 x (1.4 + 6.25)
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
    pools = ["--- pool of 14: a b ---", "x", "--- pool of 9: c ---", "  weekly ...",
             "--- pool of 11: 3 in flight, 40 queued ---", "  [a] started"]
    for arg, lines, want in [("12", pools, 12), (None, pools, 11), ("0", pools, 11),
                             ("x", [], None), ("7", pools, 7),
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


def head_self_test():
    bad = 0
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
    # answerless puzzles a model can read are queued, round-robin, newest first
    (_SCAN, (), (), (), ["canberra-500", "times-29600", "times-21042", "times-20994"]),
    # a solve that failed on these inputs stays out; an annotate failure keeps one out too
    (_SCAN, ("times-29600",), ("times-21042",), (), ["canberra-500", "times-20994"]),
    # $CT_SERIES narrows it
    (_SCAN, (), (), ("canberra",), ["canberra-500"]),
    (_SCAN[2:4], (), (), (), ["times-29600"]),
    # a clues-only puzzle (clues_only_rows) is queued in its series' lane, here
    # book's ahead of times' (neither is in BY_DEMAND); a failed solve holds it
    # out like any other
    (_SCAN[2:4] + [_HELD], (), (), (), ["book-6039", "times-29600"]),
    (_SCAN[2:4] + [_HELD], (), ("book-6039",), (), ["times-29600"]),
]


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
    return pinned + [pid for pid in queue if series.is_first_issue(pid) and pid not in pinned]


def promote(queue, pinned, tagged):
    """pinned, then the queue's tagged puzzles in queue order: the new pinned."""
    return pinned + [pid for pid in queue if pid in tagged and pid not in pinned]


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
    return pinned + [pid for _, pid in oldest if pid in queued and pid not in pinned]


# Series order within a round, so a window cut short by a lockout has spent
# itself on the papers people search for most. This ranks SERIES, never
# puzzles: every entry in a round is already its own lane's newest gap. A series
# missing from this list still runs; it just goes at the back of each cycle.
BY_DEMAND = ["everyman", "indysunday", "quiptic", "cryptic", "independent"]


def backlog(rows, annotate_blocked=(), solve_blocked=(), only=()):
    """The burn's queue: every un-annotated row, round-robin across the series,
    newest first inside each one.

    A row without all its answers is in it too, when a model can read enough
    of its clues to solve it cold (fetch_puzzle.cold_solvable) and that solve
    has not failed on these inputs: the burn solves it, then annotates it. The
    clues are the only thing a puzzle must come with; its answers are derived.
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
            and (p.get("hasSolutions") or (cold_solvable(p) and p["id"] not in solve_blocked))
            and (not only or p["series"] in only)]
    return round_robin(todo)


def round_robin(rows):
    """rows round-robin across their series, BY_DEMAND's first, newest first
    inside each series; undated last in its lane."""
    from datetime import date
    lanes = {}
    for p in rows:
        lanes.setdefault(p["series"], []).append(p)
    for lane in lanes.values():
        lane.sort(key=lambda p: series.puzzle_day(p) or date.min, reverse=True)
    cycle = sorted(lanes, key=lambda s: (BY_DEMAND.index(s) if s in BY_DEMAND
                                         else len(BY_DEMAND), s))
    return [lanes[s][i]
            for i in range(max((len(lane) for lane in lanes.values()), default=0))
            for s in cycle if i < len(lanes[s])]


def held_dir():
    """The clues_only/ of the tree INDEX belongs to: the queue reads one corpus."""
    return INDEX.parent.parent / "clues_only"


def clues_only_rows():
    """An index-shaped row for each puzzle held as its clues alone that a
    builder can promote (clues_only.solvable): unannotated, no answers, every
    clue readable, dated by its `year` or `date`. The index lists puzzles/
    alone, so without these the queue never sees them."""
    import clues_only
    rows = []
    for record in clues_only.solvable(held_dir()):
        row = {"id": record["id"], "series": record["series"],
               "annotated": False, "hasSolutions": False}
        row.update({k: record[k] for k in ("year", "date") if k in record})
        rows.append(row)
    return rows


def print_backlog(annotate_blocked, solve_blocked):
    """The queue's ids on stdout, from the index; its head and how many of it
    are to be solved first on stderr, which is the burn's log. A puzzle whose
    scan is queued for an OCR re-read (scan_queue.open_requests) is left out
    like an annotate-blocked one: its clue may be misread, and the re-read
    decides. $CT_SERIES, a space-separated list of series keys, narrows it to
    those papers. Clues-only puzzles join it as clues_only_rows()."""
    import scan_queue
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    rereads = {r["id"] for r in scan_queue.open_requests()}
    if rereads:
        print(f"  {len(rereads)} OCR'd puzzles wait on a re-read of their scan, left out until it lands",
              file=sys.stderr)
    held = clues_only_rows()
    todo = backlog(index["puzzles"] + held, annotate_blocked.split() + sorted(rereads), solve_blocked.split(),
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
    by_id = {r["id"]: r for r in rows}
    return ([r["id"] for r in round_robin([by_id[i] for i in queue if i in by_id])]
            + [i for i in queue if i not in by_id])


def head_of_queue(queue, pinned, rows, wanted=(), tagged=()):
    """(the queue newest first, the ids that go ahead of it in order): pinned
    (cut off by a lockout), then /showcase/'s wanted, then each series' No 1,
    then each series' oldest few, then the notable-tagged; each set in queue
    order but the oldest, which go oldest first. The whole queue is re-sorted,
    so ids the caller appended (puzzles made eligible mid-run) take their
    date's place rather than the back."""
    queue = newest_first(queue, rows)
    stages = [len(pinned)]
    pinned = promote(queue, list(pinned), wanted)
    stages.append(len(pinned))
    pinned = first_issues(queue, pinned)
    pinned = oldest_per_series(queue, pinned, rows)
    stages.append(len(pinned))
    pinned = promote(queue, pinned, tagged)
    stages.append(len(pinned))
    return queue, pinned, stages


def cover_first(pinned):
    """The ids on stdin, in head_of_queue()'s order with the indicator cover
    behind its pins. The summary goes to stderr, which is the burn's log."""
    import indicator_cover
    queue, pinned, n = head_of_queue(sys.stdin.read().split(), pinned, index_rows() + clues_only_rows(),
                                     showcase_wanted(), tagged_puzzles())
    print(f"showcase: {n[1] - n[0]} queued puzzles /showcase/ wants go first",
          file=sys.stderr)
    print(f"tagged: {n[3] - n[2]} queued puzzles with a notable tag go first",
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
    if "--five-hour" in sys.argv:
        return set_mode("session")
    if "--weekly" in sys.argv:
        return set_mode("weekly")
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
