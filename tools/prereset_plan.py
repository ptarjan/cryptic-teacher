#!/usr/bin/env python3
"""How wide the pre-reset backfill runs, and in what order it takes the queue.

The job's goal is every five-hour window spent to 100%: quota left on a window
when it turns over is gone. The burn keeps in flight the width that would
spend the window's remainder by its reset, at the per-run rate the burn measures off its
own log, capped by what the machine can hold right now: free memory over the
size of a run, and no growth while the CPU is saturated.

The queue order is the round-robin tools/prereset_backfill.sh builds, with the
puzzles a lockout cut off first, then Cracking the Cryptic's puzzles, then the
indicator cover (tools/indicator_cover.py).

    tools/prereset_plan.py --width [CURRENT]              # runs to keep in flight
    ids | tools/prereset_plan.py --cover-first "PINNED"   # the queue, cover first
    tools/prereset_plan.py --self-test
"""
import json
import os
import re
import sys
from pathlib import Path

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

# The runs mostly wait on the API, but their validators spike the CPU. Pressure
# is /proc/pressure/cpu "some avg60" (percent of the last minute some task waited
# for a core), else the one-minute load per core. At FULL the width holds; at
# OVER it shrinks by a quarter.
PSI_FULL, PSI_OVER = 40.0, 70.0
LOAD_FULL, LOAD_OVER = 1.0, 2.0

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


def need(pct, hours_left, rate):
    """Runs that would spend the five-hour window's remainder by its reset, at
    least 1. A reset already passed is a fresh window, all of it
    left. None when any input is missing or unusable."""
    try:
        if pct is not None and hours_left <= 0:
            pct, hours_left = 0, WINDOW_HOURS
        if rate <= 0:
            return None
        return max(1, round((100 - pct) / (hours_left * rate)))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def mem_cap(meminfo, rss_kb):
    """Runs memory can hold: those in flight plus MemAvailable less
    MEM_HEADROOM_KB over their average RSS (RUN_RSS_KB when none runs).
    None when MemAvailable cannot be read."""
    m = re.search(r"^MemAvailable:\s+(\d+) kB", meminfo or "", re.MULTILINE)
    if not m:
        return None
    each = sum(rss_kb) / len(rss_kb) if rss_kb else RUN_RSS_KB
    return len(rss_kb) + max(0, int(m[1]) - MEM_HEADROOM_KB) // max(1, int(each))


def cpu_state(psi, load1, cores):
    """"ok", "full" or "over" from PSI some avg60, else load per core.
    None when neither can be read."""
    m = re.search(r"^some .*\bavg60=([\d.]+)", psi or "", re.MULTILINE)
    if m:
        level, full, over = float(m[1]), PSI_FULL, PSI_OVER
    elif load1 is not None and cores:
        level, full, over = load1 / cores, LOAD_FULL, LOAD_OVER
    else:
        return None
    return "over" if level >= over else "full" if level >= full else "ok"


def width_for(runs_needed, mem, cpu, current):
    """The need (else the current width, else DEFAULT_WIDTH), capped by memory
    (else DEFAULT_CEILING); while the CPU is full it may not pass the current
    width, and while over it shrinks to three quarters of it. At least 1."""
    w = runs_needed or current or DEFAULT_WIDTH
    w = min(w, DEFAULT_CEILING if mem is None else mem)
    if current and cpu == "full":
        w = min(w, current)
    elif current and cpu == "over":
        w = min(w, current * 3 // 4)
    return max(1, w)


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


def width(arg=None):
    """The width to keep in flight, from the live five-hour meter and reset, the
    log's rate and last width, and the machine. The inputs go to stderr."""
    log = Path(os.environ.get("CT_MAIN_CHECKOUT") or REPO) / ".prereset.log"
    lines = (_read(log) or "").splitlines()
    current = current_width(arg, lines)
    runs_needed = None
    try:
        import weekly_usage
        pct = weekly_usage.usage_pct("session")
        hours_left, _ = weekly_usage.resets_in_hours("session")
        runs_needed = need(pct, hours_left, per_run_rate(lines))
    except Exception as exc:  # noqa: BLE001 — an unread meter leaves the need unknown
        print(f"width: meter unread: {exc}", file=sys.stderr)
    try:
        load1 = os.getloadavg()[0]
    except OSError:
        load1 = None
    mem = mem_cap(_read("/proc/meminfo"), burn_rss_kb())
    cpu = cpu_state(_read("/proc/pressure/cpu"), load1, os.cpu_count())
    w = width_for(runs_needed, mem, cpu, current)
    print(f"width {w}: need {runs_needed}, memory cap {mem}, cpu {cpu}, "
          f"current {current}", file=sys.stderr)
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
    bad = cover_self_test(covers) + width_self_test()
    n = (len(covers) + len(WIDTH_CASES) + len(NEED_CASES) + len(MEM_CASES)
         + len(CPU_CASES) + 14)
    print(f"prereset plan self-test FAILED: {bad} of {n}" if bad
          else f"prereset plan self-test: {n} cases pass")
    return 1 if bad else 0


# (need, memory cap, cpu state, current width) -> width
WIDTH_CASES = [
    ((4, 40, "ok", 14), 4),        # on track: the need, however small
    ((26, 40, "ok", 14), 26),      # behind: wider than now
    ((26, 8, "ok", 14), 8),        # memory holds 8
    ((26, 40, "full", 14), 14),    # CPU saturated: no growth
    ((4, 40, "full", 14), 4),      # ...but shrinking to the need is fine
    ((26, 40, "over", 14), 10),    # CPU badly saturated: a quarter off
    ((26, 40, "full", None), 26),  # no current width to hold to
    ((None, None, None, None), DEFAULT_WIDTH),  # nothing readable
    ((None, 40, "ok", 9), 9),      # meter unread: keep the current width
    ((60, None, "ok", 14), DEFAULT_CEILING),    # memory unread
    ((26, 0, "ok", 14), 1),        # no memory free: still one run
]
# (pct, hours to reset, per-run rate) -> need
NEED_CASES = [
    ((90, 2.0, 1.95), 3),     # 10 points over 3.9 run-hours
    ((60, 1.0, 1.95), 21),    # 40 points in 1h
    ((100, 1.0, 1.95), 1),    # window spent
    ((None, 1.0, 1.95), None),
    ((50, 0.0, 1.95), 10),    # reset passed: a fresh window, 100 points in 5h
    ((100, -0.1, 1.95), 10),  # the meter still shows the window just spent
    ((50, None, 1.95), None), # reset unread
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
PSI = "some avg10=1.00 avg60={} avg300=1.00 total=1\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
# (psi, load1, cores) -> cpu state
CPU_CASES = [
    (PSI.format("4.76"), 15.0, 4, "ok"),   # PSI wins over load
    (PSI.format("55.0"), 0.0, 4, "full"),
    (PSI.format("85.0"), 0.0, 4, "over"),
    (None, 2.0, 4, "ok"),
    (None, 5.0, 4, "full"),
    (None, 15.0, 4, "over"),
    (None, None, 4, None),
    ("garbage", None, None, None),
]


def width_self_test():
    """The cases above, the rate and current width read off the log, and a
    failed read still giving a positive width."""
    bad = 0
    checks = ([(width_for, a, w) for a, w in WIDTH_CASES]
              + [(need, a, w) for a, w in NEED_CASES]
              + [(mem_cap, (m, r), w) for m, r, w in MEM_CASES]
              + [(cpu_state, (p, l, c), w) for p, l, c, w in CPU_CASES])
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


def cover_first(pinned):
    """The ids on stdin, reordered: pinned first, then Cracking the Cryptic's
    puzzles, then the indicator cover, then the rest as they came. The summary
    goes to stderr, which is the burn's log."""
    import indicator_cover
    queue = sys.stdin.read().split()
    ctc = ctc_puzzles()
    pinned = pinned + [pid for pid in queue if pid in ctc and pid not in pinned]
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
        print(width(sys.argv[at + 1] if at + 1 < len(sys.argv) else None))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
