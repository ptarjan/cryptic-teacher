"""Is there memory, and CPU, for one more unit? The queues (tools/edition_queue.py,
tools/unit_queue.py) size their pools in CPU slots, so the pools alone can
outrun the host. A queue asks `room()` before starting a unit and, when it
says no, leaves the unit for its next plan. Running units are never touched.

`available()` already holds what running units use; `room()` charges only
the units begun this pass, which have not grown yet, and the one to start.
`unit_costs()` prices each kind at the largest resident size (process plus
children) of its running units, at least UNIT_MIN; a kind none of whose
units runs is charged UNIT.

`available()` is the kernel's own figure: MemAvailable in /proc/meminfo on
Linux; on macOS the free, speculative, purgeable and file-backed page counts
from sysctl, times the page size. None when neither can be read (then
`room()` allows the start: no figure, no gate).

`cpu_room()` is the same question for CPU: the one-minute load average,
plus the units begun this pass, under LOAD_PER_CORE per core. A unit that
waits on the desktop or the network sleeps and adds no load, so the gate
holds back only CPU-bound starts on a host already oversubscribed.
tools/unit_queue.py, whose units all run at nice 19, reads `foreground_load()`
instead: the run queue less nice-19 work, which yields to anything less nice
and so never oversubscribes the host for the bridge or a shell.

`idle_room()` asks it of a unit whose work runs on this host's CPU (a Trove
article's OCR and grid search, the Listener's Tesseract): whether
`idle_cores()`, the cores /proc/stat found idle over about the last
IDLE_SPAN_S (everything's busy time counted: the burn's, other agents', the
queue's own units'), less one core for each such unit begun this pass,
leaves IDLE_MIN. Such a pool is then as wide as the idle cores, never its
fixed count on a busy host, and the burn, whose quota expires at each reset,
keeps the CPU first. The load average is no measure of that: it counts
processes waiting on disk, and a busy box sits under LOAD_PER_CORE.

`burn_starved()` puts the pre-reset burn first: tools/prereset_plan.py
writes BURN_STATE (its need, memory cap, cpu cap and width) at every plan,
and while its cpu cap holds it below what its need and memory allow, no
unit starts, so the cores the queue would take go to the burn. A state
older than BURN_STALE_S, or none, means no burn is planning: no gate."""
import collections
import functools
import json
import os
import subprocess
import time
from pathlib import Path

#: Memory (bytes) that must stay available after a start, and one unit's share
#: (CT_MEM_FLOOR overrides: tests run ticks on a host whose own memory must
#: not gate them).
FLOOR = int(os.environ.get("CT_MEM_FLOOR") or 3 << 30)
UNIT = 600 << 20
UNIT_MIN = 128 << 20
#: Runnable processes per core past which no unit starts: 2 keeps a 4-core
#: host under load 8, so the bridge and an interactive shell still get a core
#: (CT_LOAD_PER_CORE overrides: tests run ticks on a host whose own load must
#: not gate them).
LOAD_PER_CORE = float(os.environ.get("CT_LOAD_PER_CORE") or 2)

_MAC = ("vm.page_free_count", "vm.page_speculative_count", "vm.page_purgeable_count",
        "vm.page_pageable_external_count")


def _sysctl(key):
    return int(subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, check=True, timeout=5).stdout)


#: Memory pressure (PSI "full" avg10, percent of time every task stalled on
#: memory) past which no unit starts, and the most unit children (every kind
#: but fetches) at once. Env, read at each call: CT_PSI_MAX, CT_UNIT_CEILING;
#: CT_MEMINFO and CT_PSI_PATH move the files read (tests, other hosts).
PSI_MAX = 10.0
#: Ten: a read unit holds 45-100 MB here now that its OCR, grid search and
#: solution-grid reading run on the desktop (ocr_remote.CALLS); the PSI and
#: MemAvailable gates stay the safety.
UNIT_CEILING = 10


def psi_max():
    return float(os.environ.get("CT_PSI_MAX") or PSI_MAX)


#: A file holding one number overrides CT_UNIT_CEILING while the queue runs, so
#: a watcher can move the ceiling (say, by the Windows host's free RAM on the
#: desktop) without a restart; absent or unreadable, the env/default applies.
CEILING_FILE = "~/.cache/corpus_queue/unit_ceiling"


def unit_ceiling():
    try:
        with open(os.path.expanduser(os.environ.get("CT_UNIT_CEILING_FILE") or CEILING_FILE)) as f:
            return max(1, int(f.read().strip()))
    except (OSError, ValueError):
        pass
    return int(os.environ.get("CT_UNIT_CEILING") or UNIT_CEILING)


#: The ceiling controller (Windows host RAM/CPU -> the CEILING_FILE number; was the desktop's
#: ceiling_ctl.sh). Opt-in by env: CT_CEILING_HOST (ssh target; default the first of CT_YIELD_HOSTS;
#: "0" turns it off), CT_CEILING_METRICS (default: the VLM host's /metrics, passed by the caller),
#: CT_CEILING_LO/HI (8/32), CT_CEILING_CPU_HI/LO (90/80), CT_CEILING_EVERY (120 s); the page-cache
#: drop is CT_GAME_DROP_CACHE. The VLM slows ~2x when Windows CPU is pegged (10-21 A/B: 6 scans
#: paused -> CPU 97 -> 67%, asks 3.1 -> 5.8/min), so it steps down above CPU_HI, up only below CPU_LO.
#: It writes the same file unit_ceiling() reads, so a manual pin holds until the next step moves it.
CEILING_EVERY = 120
#: The most the controller steps the ceiling up to (11-14: 24 bound while Windows CPU sat at 34-75%,
#: free RAM 4-7 GB, the VLM at half its asks); the step-down on low free RAM / high CPU is unchanged.
CEILING_HI = 32
#: The VM's page cache refills 0.4-1 GB a minute (buffers/ledgers/page images), so dropping only under
#: 3000 MB free kept Windows at 1.7-2.5 GB and the ceiling at 16-18 (11-14); a drop under DROP_BELOW_MB
#: keeps it near 5 GB, where the ceiling steps up. CT_CEILING_DROP_BELOW / CT_CEILING_SETTLE override.
DROP_BELOW_MB = int(os.environ.get("CT_CEILING_DROP_BELOW") or 4800)
DROP_SETTLE = int(os.environ.get("CT_CEILING_SETTLE") or 40)


#: The VM's own swap traffic (pswpin+pswpout, MB a minute) over which the ceiling steps down, and
#: over which it never steps up (11-14 #household: 405 MB/min in and out of swap stalled the bridge
#: while Windows free RAM read roomy enough to step up). CT_SWAP_DOWN / CT_SWAP_HOLD override. 11-15: 30/5 let swap sit at 25 MB/min; Paul wants it at zero.
SWAP_DOWN_MB = int(os.environ.get("CT_SWAP_DOWN") or 10)
SWAP_HOLD_MB = int(os.environ.get("CT_SWAP_HOLD") or 2)
#: Windows hard page faults a second (Memory\Pages Input/sec) over which the ceiling steps down,
#: and over which it never steps up (11-14 23:30: 32 units, Windows 218-356 MB free and ~3,500
#: pages/s read back from disk between cache drops, while every post-drop reading looked roomy).
#: CT_FAULTS_DOWN / CT_FAULTS_HOLD override.
FAULTS_DOWN = int(os.environ.get("CT_FAULTS_DOWN") or 1500)
FAULTS_HOLD = int(os.environ.get("CT_FAULTS_HOLD") or 400)


def swap_pages(path="/proc/vmstat"):
    """pswpin + pswpout so far (pages), or None."""
    try:
        with open(path) as f:
            return sum(int(line.split()[1]) for line in f if line.startswith(("pswpin ", "pswpout ")))
    except (OSError, ValueError, IndexError):
        return None


#: Severe memory pressure halves the ceiling toward its floor instead of stepping -2 (11-16 09:52: 32
#: units at once after a paused hour, 6.6/8 GB swap at 2.5-7.4 GB/min, load 65, the OOM killer took the
#: plan child; -2 every 120 s was far too slow). Over SEVERE_SWAP_MB of VM swap a minute, Windows under
#: SEVERE_FREE_MB free, or hard faults over twice FAULTS_DOWN. CT_SEVERE_SWAP / CT_SEVERE_FREE override.
SEVERE_SWAP_MB = int(os.environ.get("CT_SEVERE_SWAP") or 200)
SEVERE_FREE_MB = int(os.environ.get("CT_SEVERE_FREE") or 1000)
#: A relaunched queue ramps up from here, never from the last stored ceiling (CT_CEILING_START).
CEILING_START = int(os.environ.get("CT_CEILING_START") or 12)
#: Running units under the ceiling by more than this: the ceiling is not what binds, so free RAM read on
#: a part-idle queue says nothing about the load the full ceiling would bring, and it does not step up.
IDLE_SLACK = 2


def ceiling_step(ceiling, free_mb, cpu, lo=8, hi=24, cpu_hi=90, cpu_lo=80, swap_mb=None, faults=None,
                 low_mb=None, running=None):
    """The new ceiling: halved (toward lo) under severe pressure (VM swap over SEVERE_SWAP_MB a minute,
    Windows free under SEVERE_FREE_MB, faults over 2 x FAULTS_DOWN); else -2 when Windows has under 2000 MB
    free (free_mb, or low_mb, the reading before a cache drop), CPU is over cpu_hi, the VM swaps over
    SWAP_DOWN_MB a minute or Windows hard-faults over FAULTS_DOWN pages a second; +2 when over 4500 MB
    free, CPU (unknown counts as busy) under cpu_lo, swap still (under SWAP_HOLD_MB a minute) and faults
    under FAULTS_HOLD (unknown counts as still), and the `running` units (None: unknown) are not more than
    IDLE_SLACK under the ceiling; clamped to lo..hi. No RAM figure: unchanged."""
    if free_mb is None:
        return ceiling
    new = ceiling
    swap = swap_mb or 0
    low = free_mb if low_mb is None else min(free_mb, low_mb)
    if low < SEVERE_FREE_MB or swap > SEVERE_SWAP_MB or (faults or 0) > FAULTS_DOWN * 2:
        new = min(ceiling - 2, ceiling // 2)
    elif low < 2000 or (cpu or 0) > cpu_hi or swap > SWAP_DOWN_MB or (faults or 0) > FAULTS_DOWN:
        new = ceiling - 2
    elif free_mb > 4500 and (100 if cpu is None else cpu) < cpu_lo and swap <= SWAP_HOLD_MB \
            and (faults or 0) <= FAULTS_HOLD and (running is None or running >= ceiling - IDLE_SLACK):
        new = ceiling + 2
    return max(lo, min(hi, new))


#: After VM swap steps the ceiling down it does not step up again for SWAP_COOL seconds, and never while
#: the VM's own MemAvailable is under FLOOR + VM_UP_UNITS units (11-21 18:03-18:11: swap 118 MB/min
#: stepped 18 -> 16, swap read 0 for two probes, it climbed 16 -> 22 in six minutes as the new units grew
#: to 700-900 MB each, then 357 MB/min swap halved it to 11). CT_SWAP_COOL / CT_VM_UP_UNITS override.
SWAP_COOL = int(os.environ.get("CT_SWAP_COOL") or 1800)
VM_UP_UNITS = int(os.environ.get("CT_VM_UP_UNITS") or 4)


#: CT_VM_UP_UNITS set: the old fixed reserve (that many units) instead of the measured one.
VM_UP_FIXED = bool(os.environ.get("CT_VM_UP_UNITS"))
#: Peak resident bytes of finished units (the unit's own and its reaped children's: wait4's ru_maxrss),
#: the last PEAK_KEEP per kind (edition_queue.mem_kind: pool, paper and reader/series, e.g. "listener
#: listener jumbo", "read times GaleTimes1935UKEnglish"). Measured history survives restarts: load_peaks()
#: (the queue's `run`) reads them from peaks_path() and from then on record_peak saves them (atomically,
#: at most every PEAKS_SAVE seconds); until it is called (tests, other tools) they stay in memory.
PEAK_KEEP = 50
PEAKS = {}
PEAKS_SAVE = 60
_peaks_saving = False
_peaks_saved = 0.0


def peaks_path():
    """Beside the queue's other state (overruns.json, ask_yield.json); HOME read at call time."""
    return Path(os.environ.get("HOME") or "/tmp") / ".cache" / "corpus_queue" / "mem_peaks.json"


def load_peaks(path=None, peaks=None):
    """Fill `peaks` (PEAKS) from the saved file (missing or bad: nothing) and, for PEAKS, turn saving on."""
    global _peaks_saving
    peaks = PEAKS if peaks is None else peaks
    try:
        data = json.loads(Path(path or peaks_path()).read_text())
        for kind, vals in data.items():
            vals = [int(v) for v in vals if int(v) > 0]
            if vals:
                peaks[str(kind)] = collections.deque(vals, maxlen=PEAK_KEEP)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    if peaks is PEAKS:
        _peaks_saving = True


def save_peaks(path=None, peaks=None):
    """Write `peaks` (PEAKS) as JSON, tmp + replace; False when it could not."""
    path = Path(path or peaks_path())
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({k: list(v) for k, v in (PEAKS if peaks is None else peaks).items()}))
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def record_peak(kind, peak, peaks=None):
    """Remember one finished unit's peak resident bytes under its kind."""
    global _peaks_saved
    if peak and peak > 0:
        (PEAKS if peaks is None else peaks).setdefault(kind, collections.deque(maxlen=PEAK_KEEP)).append(int(peak))
        if peaks is None and _peaks_saving and time.monotonic() - _peaks_saved >= PEAKS_SAVE:
            _peaks_saved = time.monotonic()
            save_peaks()


def _high(values):
    """The 90th percentile of `values` (a peak a unit of the kind mostly stays under), None when empty."""
    v = sorted(values)
    return v[int(0.9 * (len(v) - 1))] if v else None


#: A kind's own peaks count once it has this many; fewer, its pool's (the kind's first word) stand in.
KIND_MIN = 3


def expected_peak(kind, peaks=None):
    """What a unit of `kind` is expected to peak at: its kind's recent peaks (KIND_MIN or more), else the
    higher of its pool's (kinds sharing the first word: "listener jumbo", "listener") and its own
    highest, else every kind's, else UNIT (no history). A pool mixes readers of very different size (Listener pages ~0.3 GB beside
    Jumbo/TLS solution reads over 1 GB), so the finer kind is asked first."""
    peaks = PEAKS if peaks is None else peaks
    own = peaks.get(kind) or ()
    if len(own) >= KIND_MIN:
        return _high(own)
    pool = kind.split(" ", 1)[0]
    near = _high([x for k, d in peaks.items() if k.split(" ", 1)[0] == pool for x in d])
    if near is not None:
        return max(near, max(own, default=0))  # never under a peak this kind already reached
    return _high([x for d in peaks.values() for x in d]) or UNIT


def _peak_list(kind, peaks):
    """The recorded peaks a unit of `kind` is drawn from, same fallback as expected_peak: its own (KIND_MIN
    or more), else its pool's plus its own, else every kind's, else [UNIT] (no history)."""
    own = list(peaks.get(kind) or ())
    if len(own) >= KIND_MIN:
        return own
    pool = kind.split(" ", 1)[0]
    near = [x for k, d in peaks.items() if k.split(" ", 1)[0] == pool for x in d]
    if near:
        return near + own
    return [x for d in peaks.values() for x in d] or [UNIT]


#: The step-up reserve's measurements (up_reserve), both taken by the ceiling controller at each probe:
#: DROPS, how far MemAvailable fell within DROP_SPAN seconds of a probe while the ceiling stood still (bytes,
#: the last DROP_KEEP), and STEADY, {kind: resident bytes of its running units as each probe found them, the
#: last STEADY_KEEP}: a probe meets a unit at a random age, so their mean is what a unit of the kind holds
#: averaged over its life, which is what one more slot costs the pool. Both survive restarts in pool_path()
#: once load_pool() (the queue's `run`) turned saving on.
#: DROP_SPAN is ten minutes: a new unit is grown within ~140 s, and a step that proves wrong is undone only
#: as running units end (most within 10 min). CT_VM_DROP_SPAN overrides.
#: Measured 11-26 over 216 ten-minute windows at a held ceiling of 13-14 units (full_pass.log): the fall was
#: median 623, p90 1880, p95 2196, p99 2765, max 3281 MB (the plan fork alone comes and goes with 2.4 GB),
#: while the reserve then in force (every unit to its peak at once) asked 7404 MB at the median. Until
#: DROP_MIN falls are measured the reserve uses DROP_DEFAULT, just over that p99.
RESERVE_Q = 0.95
DROP_SPAN = int(os.environ.get("CT_VM_DROP_SPAN") or 600)
DROP_KEEP = 500
DROP_MIN = 30
DROP_DEFAULT = 2800 << 20
STEADY_KEEP = 200
DROPS = collections.deque(maxlen=DROP_KEEP)
STEADY = {}
_pool_saving = False
_pool_saved = 0.0


def pool_path():
    """Beside mem_peaks.json; HOME read at call time."""
    return Path(os.environ.get("HOME") or "/tmp") / ".cache" / "corpus_queue" / "mem_pool.json"


def load_pool(path=None, drops=None, steady=None):
    """Fill `drops` (DROPS) and `steady` (STEADY) from the saved file (missing or bad: nothing) and, for the
    module's own, turn saving on."""
    global _pool_saving
    own = drops is None and steady is None
    drops = DROPS if drops is None else drops
    steady = STEADY if steady is None else steady
    try:
        data = json.loads(Path(path or pool_path()).read_text())
        drops.extend(int(v) for v in data.get("drops") or () if int(v) >= 0)
        for kind, vals in (data.get("steady") or {}).items():
            vals = [int(v) for v in vals if int(v) > 0]
            if vals:
                steady[str(kind)] = collections.deque(vals, maxlen=STEADY_KEEP)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    if own:
        _pool_saving = True


def save_pool(path=None, drops=None, steady=None):
    """Write `drops` (DROPS) and `steady` (STEADY) as JSON, tmp + replace; False when it could not."""
    path = Path(path or pool_path())
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"drops": list(DROPS if drops is None else drops),
                                   "steady": {k: list(v) for k, v in (STEADY if steady is None else steady).items()}}))
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def note_avail(history, now, avail, ceiling, drops=None, span=None):
    """One probe's MemAvailable (`avail` bytes; None: nothing) at `ceiling`, added to `history` (the
    caller's deque of (time, avail, ceiling)). Each probe now `span` (DROP_SPAN) seconds old leaves history
    and, when every probe within `span` after it ran at its ceiling and they reach at least half the span,
    records in `drops` (DROPS) how far MemAvailable fell under its own reading in that time (0: it never
    did). A window the ceiling moved in says what the step did, not how the pool swings, and is left out."""
    drops = DROPS if drops is None else drops
    span = DROP_SPAN if span is None else span
    if avail is None:
        return
    history.append((now, avail, ceiling))
    while history and now - history[0][0] >= span:
        t0, a0, c0 = history.popleft()
        window = [(t, a, c) for t, a, c in history if t - t0 <= span]
        if window and window[-1][0] - t0 >= span / 2 and all(c == c0 for _, _, c in window):
            drops.append(max(0, a0 - min(a for _, a, _ in window)))


def record_steady(kind, rss, steady=None):
    """Remember what one running unit of `kind` held (resident bytes, it and its children) at a probe; saves
    the pool file (at most every PEAKS_SAVE seconds) once load_pool() turned saving on."""
    global _pool_saved
    if rss and rss > 0:
        (STEADY if steady is None else steady).setdefault(kind, collections.deque(maxlen=STEADY_KEEP)).append(int(rss))
        if steady is None and _pool_saving and time.monotonic() - _pool_saved >= PEAKS_SAVE:
            _pool_saved = time.monotonic()
            save_pool()


def steady_size(kind, steady=None, peaks=None):
    """What a unit of `kind` holds averaged over its life: the mean of its probe readings (KIND_MIN or
    more), else of its pool's (kinds sharing the first word), else of every kind's; with no reading at all,
    the mean of its recorded peaks (_peak_list: over what it holds on average, so the safe side). `kind`
    None: a unit of no known kind (one about to start), every kind's readings as the pool has them."""
    steady = STEADY if steady is None else steady
    own = list(steady.get(kind) or ()) if kind is not None else []
    if len(own) < KIND_MIN:
        pool = kind.split(" ", 1)[0] if kind is not None else None
        own = [x for k, d in steady.items() if k.split(" ", 1)[0] == pool for x in d] \
            or [x for d in steady.values() for x in d]
    if not own:
        own = _peak_list(kind or "", PEAKS if peaks is None else peaks)
    return sum(own) // len(own)


def _quantile(values, q):
    """The q-quantile of `values`, rounded up to a value that occurred."""
    v = sorted(values)
    return v[min(len(v) - 1, -int(-q * (len(v) - 1) // 1))]


def up_reserve(running, adding, peaks=None, drops=None, steady=None):
    """(reserve bytes, parts text) a step up of `adding` units needs the VM to have free over FLOOR.

    Rule: a pool of units at a fixed ceiling is stationary (as one unit grows another ends and a small one
    starts), so what a step up costs is not every running unit's growth to its peak but three things, each
    measured here and none assumed:
      new     `adding` x steady_size(None): what one more slot holds averaged over a unit's life;
      young   how far the `running` units ([(kind, resident bytes)]) are, together, under the sum of their
              kinds' steady sizes (a pool just started, or stepped up a probe ago, has that growth still to
              come; a grown pool has none);
      swing   the RESERVE_Q (95%) quantile of DROPS, how far MemAvailable really fell within DROP_SPAN of a
              probe at a standing ceiling (everything on the VM: units, the plan fork, page cache), scaled
              by (running + adding) / running, at most 2, as the larger pool swings more; DROP_DEFAULT until
              DROP_MIN falls are measured.
    reserve = new + young + swing. It is a 95% figure on top of FLOOR, not a bound: the ceiling's swap and
    fault step-downs, the severe halving and the swap cool-down (ceiling_step, cool_after) are unchanged
    and catch the rest. With nothing measured at all, or CT_VM_UP_UNITS set, the old VM_UP_UNITS x UNIT."""
    peaks = PEAKS if peaks is None else peaks
    drops = DROPS if drops is None else drops
    steady = STEADY if steady is None else steady
    if VM_UP_FIXED or not (any(peaks.values()) or any(steady.values()) or drops):
        return VM_UP_UNITS * UNIT, f"fixed {VM_UP_UNITS} x {UNIT >> 20} MB units"
    n, n_new = len(running), max(1, adding)
    each = steady_size(None, steady, peaks)
    young = max(0, sum(steady_size(k, steady, peaks) for k, _ in running) - sum(rss for _, rss in running))
    measured = len(drops) >= DROP_MIN
    swing = _quantile(drops, RESERVE_Q) if measured else DROP_DEFAULT
    swing = int(swing * min(2.0, (n + n_new) / n)) if n else swing
    total = n_new * each + young + swing
    return total, (f"{total >> 20} MB reserve: {n_new} new x {each >> 20} MB steady + {young >> 20} MB the {n} running "
                   f"are under their steady size + {swing >> 20} MB "
                   + (f"p{int(RESERVE_Q * 100)} fall in {DROP_SPAN} s of {len(drops)} measured" if measured
                      else f"default fall ({len(drops)} of {DROP_MIN} measured)"))


def step_up_held(cur, new, now, cool_until, vm_avail, reserve=None):
    """Why a step up from `cur` to `new` is held, or None (not a step up, or nothing holds it): a swap
    cool-down still running (now < cool_until), or the VM with under FLOOR + reserve available (vm_avail
    bytes; None: no figure, no hold). `reserve` is (bytes, parts text) from up_reserve; None: the old
    VM_UP_UNITS x UNIT."""
    if new <= cur:
        return None
    if cool_until is not None and now < cool_until:
        return f"swap cool-down, {int(cool_until - now)} s left"
    size, parts = reserve if reserve is not None else (VM_UP_UNITS * UNIT, f"fixed {VM_UP_UNITS} x {UNIT >> 20} MB units")
    if vm_avail is not None and vm_avail < FLOOR + size:
        return f"VM has {vm_avail >> 20} MB available, under {(FLOOR + size) >> 20} MB (floor {FLOOR >> 20} MB + {parts})"
    return None


def hold_step_up(cur, new, now, cool_until, vm_avail, reserve=None):
    """`new` unless it is a step up that step_up_held() holds; then `cur`."""
    return cur if step_up_held(cur, new, now, cool_until, vm_avail, reserve) else new


def cool_after(cur, new, swap_mb, now, cool_until):
    """The swap cool-down's end after a probe: now + SWAP_COOL when VM swap (over SWAP_DOWN_MB a minute)
    actually stepped the ceiling down (new < cur), else `cool_until` unchanged. 11-21 19:41-20:21: the
    ceiling sat at its floor of 8 for 40 min with nothing logged, each probe that read the swap-in of
    pages a past storm had pushed out starting the 30 min again though nothing could step down."""
    if new < cur and (swap_mb or 0) > SWAP_DOWN_MB:
        return now + SWAP_COOL
    return cool_until


def start_ceiling(stored, start, running=0):
    """The ceiling a queue starts at: `stored` (the file's) lowered to `start` (CEILING_START), or to the
    `running` units it took over from the image before it when those are more: they already hold their
    memory, so a ceiling at their count starts a unit only as one of them ends. Never over `stored`.
    11-22 03:10-04:10 UTC: four reloads in an hour each clamped 16-20 running units to a ceiling of 12 and
    the +2 ramp took 6-28 min to come back: 15.3 units on average under a ceiling of 18.
    CT_CEILING_START_KEEP=0 turns the running count off (always `start`)."""
    keep = running if os.environ.get("CT_CEILING_START_KEEP", "1") != "0" else 0
    return min(stored, max(start, keep or 0))


def clamp_ceiling_start(start=None, log=None, running=0):
    """At a queue start: a stored ceiling file over start_ceiling() is lowered to it, so a relaunch with
    nothing running ramps up from `start` (CEILING_START) and a reload keeps what its `running` units
    already are; returns the line to log, or None."""
    start = CEILING_START if start is None else start
    path = os.path.expanduser(os.environ.get("CT_UNIT_CEILING_FILE") or CEILING_FILE)
    try:
        with open(path) as f:
            stored = int(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    new = start_ceiling(stored, start, running)
    if stored <= new:
        return None
    try:
        with open(path, "w") as f:
            f.write(f"{new}\n")
    except OSError:
        return None
    if new > start:
        return f"ceiling: stored {stored} clamped to {new} at start, the {running} units taken over (not {start}: they already run)"
    return f"ceiling: stored {stored} clamped to {start} at start (ramps up from there)"


#: The swap cool-down's end is kept beside the ceiling file (epoch seconds), so a reload or a new slice
#: goes on with it: 11-21 20:23 a slice restart ended a cool-down early and the ceiling left 8 at once.
def cool_path():
    return os.path.expanduser(os.environ.get("CT_UNIT_CEILING_FILE") or CEILING_FILE) + ".cool"


def cool_left(now=None, path=None):
    """Seconds of a stored swap cool-down still to run (0: none, unreadable, or longer than SWAP_COOL)."""
    try:
        with open(path or cool_path()) as f:
            left = float(f.read().split()[0]) - (time.time() if now is None else now)
    except (OSError, ValueError, IndexError):
        return 0
    return left if 0 < left <= SWAP_COOL else 0


def cool_store(seconds, now=None, path=None):
    try:
        with open(path or cool_path(), "w") as f:
            f.write(f"{(time.time() if now is None else now) + seconds:.0f}\n")
    except OSError:
        pass


_SWAP_SEEN = [None]


def swap_rate_now():
    """MB a minute swapped since the last call of this (None on the first)."""
    pages, now, last = swap_pages(), time.monotonic(), _SWAP_SEEN[0]
    _SWAP_SEEN[0] = (pages, now) if pages is not None else None
    if last is None or pages is None or now - last[1] < 1:
        return None
    return int((pages - last[0]) * 4 / 1024 * 60 / (now - last[1]))


PLAN_FORK_MIN = int(os.environ.get("CT_PLAN_FORK_MIN") or 3 << 30)


def vm_short(avail=None, swap_mb=None):
    """True when the VM is short of memory for an in-process plan: MemAvailable under PLAN_FORK_MIN or
    swap traffic over SWAP_DOWN_MB a minute (11-16: the OOM killer took a 2 GB plan child)."""
    avail = available() if avail is None else avail
    swap = swap_rate_now() if swap_mb is None else swap_mb
    return (avail is not None and avail < PLAN_FORK_MIN) or (swap or 0) > SWAP_DOWN_MB


def _win_free(host):
    import re
    try:
        out = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host,
                              'powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1KB)"'],
                             capture_output=True, text=True, timeout=20).stdout
        return int(re.sub(r"\D", "", out))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _win_faults(host):
    """Windows hard page faults a second (Pages Input/sec, one 2 s sample), or None."""
    import re
    try:
        out = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host,
                              "powershell -NoProfile -c \"[int](Get-Counter '\\Memory\\Pages Input/sec' "
                              "-SampleInterval 2).CounterSamples[0].CookedValue\""],
                             capture_output=True, text=True, timeout=30).stdout
        return int(re.sub(r"\D", "", out))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _win_cpu(url):
    import re
    import urllib.request
    try:
        text = urllib.request.urlopen(url, timeout=10).read().decode()
        vals = [float(x) for x in re.findall(r'cpu_util_percent\{core="\d+"\} ([\d.]+)', text)]
        return int(sum(vals) / len(vals)) if vals else None
    except (OSError, ValueError):
        return None


class CeilingController:
    """poll() never blocks: each EVERY seconds it starts a thread that probes (ssh, http), drops the
    page cache when Windows has under 3000 MB free, steps the ceiling file; poll() returns the log
    lines the thread left (only on a change, or a drop)."""

    def __init__(self, host, metrics, drop_cmd="", every=None):
        self.host, self.metrics, self.drop_cmd = host, metrics, drop_cmd
        self.every = every or int(os.environ.get("CT_CEILING_EVERY") or CEILING_EVERY)
        self.last = None
        self.thread = None
        self.lines = []
        self.swapped = None
        left = cool_left()  # (a cool-down the image before this one started goes on)
        self.cool_until = time.monotonic() + left if left else None  # no step up before this (monotonic) after VM swap stepped down
        self.kinds = {}  # {pid: slot} of the unit children running, given to poll() (their sizes are the reserve's growth)
        self.running = None  # unit children running, given to poll() by the queue (None: unknown)
        self.seen = collections.deque()  # (monotonic, MemAvailable, ceiling) of the probes of the last DROP_SPAN (note_avail)

    def _swap_rate(self):
        """MB a minute swapped in+out since the last probe (None on the first)."""
        pages, now, last = swap_pages(), time.monotonic(), self.swapped
        self.swapped = (pages, now) if pages is not None else None
        if last is None or pages is None or now <= last[1]:
            return None
        return int((pages - last[0]) * 4 / 1024 * 60 / (now - last[1]))

    def _run(self):
        # Every probe measures the reserve's inputs, whether or not it steps: how MemAvailable moves at a
        # standing ceiling, and what each running unit holds now.
        note_avail(self.seen, time.monotonic(), available(), unit_ceiling())
        for p, r in (tree_rss(list(self.kinds)) if self.kinds else {}).items():
            record_steady(self.kinds.get(p, ""), r)
        swap = self._swap_rate()
        free = _win_free(self.host)
        low = free
        faults = _win_faults(self.host)
        cpu = _win_cpu(self.metrics) if self.metrics else None
        if free is not None and free < DROP_BELOW_MB and self.drop_cmd:
            try:
                subprocess.run(["sh", "-c", self.drop_cmd], stdin=subprocess.DEVNULL, capture_output=True, timeout=40)
            except (OSError, subprocess.SubprocessError):
                pass
            # Windows gets the VM's freed pages back over the next ~30-60 s (11-14 07:17: a drop read
            # 770 -> 1900 MB at once, 5-6 GB a minute on), so the step reads the settled figure.
            time.sleep(DROP_SETTLE)
            again = _win_free(self.host)
            self.lines.append(f"ceiling: win free {free} MB -> dropped cache -> {again} MB")
            free = again if again is not None else free
        if free is None:
            return
        env = os.environ.get
        cur = unit_ceiling()
        new = ceiling_step(cur, free, cpu, int(env("CT_CEILING_LO") or 8), int(env("CT_CEILING_HI") or CEILING_HI),
                           int(env("CT_CEILING_CPU_HI") or 90), int(env("CT_CEILING_CPU_LO") or 80), swap,
                           faults, low, self.running)
        now = time.monotonic()
        was = self.cool_until
        self.cool_until = cool_after(cur, new, swap, now, self.cool_until)
        if self.cool_until is not None and self.cool_until != was:
            cool_store(self.cool_until - now)
        avail = available()
        reserve = None
        if new > cur:
            sizes = tree_rss(list(self.kinds)) if self.kinds else {}  # (read again: a cache drop slept DROP_SETTLE)
            reserve = up_reserve([(self.kinds.get(p, ""), r) for p, r in sizes.items()], new - cur)
        held = step_up_held(cur, new, now, self.cool_until, avail, reserve)
        if held is None and new == cur and swap and swap > SWAP_HOLD_MB and ceiling_step(
                cur, free, cpu, int(env("CT_CEILING_LO") or 8), int(env("CT_CEILING_HI") or CEILING_HI),
                int(env("CT_CEILING_CPU_HI") or 90), int(env("CT_CEILING_CPU_LO") or 80), 0, faults, low, self.running) > cur:
            held = f"VM swap traffic {swap} MB/min, over {SWAP_HOLD_MB}"
        if held:
            self.lines.append(f"ceiling: step up from {cur} held: {held} (win free {free} MB, cpu {cpu}%, "
                              f"swap {swap} MB/min, faults {faults}/s)")
        new = hold_step_up(cur, new, now, self.cool_until, avail, reserve)
        if new != cur:
            path = os.path.expanduser(env("CT_UNIT_CEILING_FILE") or CEILING_FILE)
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(f"{new}\n")
            except OSError as e:
                self.lines.append(f"ceiling: cannot write {path}: {e}")
                return
            self.lines.append(f"ceiling: win free {free} MB (low {low}) cpu {cpu}% swap {swap} MB/min "
                              f"faults {faults}/s: {cur} -> {new}")

    def poll(self, now=None, running=None, kinds=None):
        now = time.monotonic() if now is None else now
        self.running = running
        self.kinds = dict(kinds or {})
        if (self.thread is None or not self.thread.is_alive()) and (self.last is None or now - self.last >= self.every):
            import threading
            self.last = now
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        out, self.lines = self.lines, []
        return out


def ceiling_controller(metrics=None):
    """A CeilingController from the env, or None (off: the Mac). `metrics` is the default URL."""
    host = os.environ.get("CT_CEILING_HOST")
    if host is None:
        host = (os.environ.get("CT_YIELD_HOSTS", "").split() or [""])[0]
    if host.strip() in ("", "0"):
        return None
    return CeilingController(host.strip(), os.environ.get("CT_CEILING_METRICS") or metrics,
                             os.environ.get("CT_GAME_DROP_CACHE", "").strip())


def pressure():
    """The memory PSI's full avg10, or None when it cannot be read (macOS)."""
    try:
        with open(os.environ.get("CT_PSI_PATH") or "/proc/pressure/memory") as f:
            for line in f:
                if line.startswith("full "):
                    return float(dict(p.split("=") for p in line.split()[1:])["avg10"])
    except (OSError, ValueError, KeyError):
        pass
    return None


def calm(reader=None):
    """True unless the memory pressure is over psi_max(); no figure, no gate."""
    now = (reader or pressure)()
    return now is None or now <= psi_max()


def available():
    try:
        with open(os.environ.get("CT_MEMINFO") or "/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    try:
        return sum(_sysctl(k) for k in _MAC) * _sysctl("hw.pagesize")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def room(charged=0, reader=None, floor=FLOOR, unit=UNIT):
    """True if one more unit fits: what is available, less `charged` bytes
    for the units begun in this pass, stays above the floor with this
    one's `unit`, and (when `reader` is not injected) the memory pressure
    is under psi_max()."""
    avail = (reader or available)()
    if reader is None and not calm():
        return False
    return avail is None or avail - charged >= floor + unit


def short(base=0, avail=None, rss=None):
    """Why a long build should stop here, or None: what is available has
    fallen under FLOOR plus how far this process (and its children) has grown
    past `base` resident bytes, the size when it began. A build that goes on
    past that swaps, and the container's OOM killer takes it (rc 137, 11-03
    01:57: the lexicon chunks, 488s wall for 114s CPU) with its work half
    done; stopping clean lets a retry resume. No figure, no reason."""
    avail = available() if avail is None else avail
    if avail is None:
        return None
    if rss is None:
        rss = tree_rss([os.getpid()]).get(os.getpid(), base)
    need = FLOOR + max(0, rss - base)
    if avail < need:
        return f"{avail >> 20} MB available, under the {need >> 20} MB floor plus growth"
    return None


def tree_rss(pids, table=None):
    """{pid: resident bytes of it and its descendants} for each of `pids`
    found in `table` ([(pid, ppid, rss KiB)], else this host's ps)."""
    if table is None:
        try:
            out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True, text=True,
                                 check=True, timeout=10).stdout
            table = [tuple(int(f) for f in line.split()) for line in out.splitlines() if line.strip()]
        except (OSError, ValueError, subprocess.SubprocessError):
            return {}
    kids, rss = {}, {}
    for pid, ppid, kb in table:
        kids.setdefault(ppid, []).append(pid)
        rss[pid] = kb << 10
    out = {}
    for root in pids:
        if root not in rss:
            continue
        total, stack, seen = 0, [root], set()
        while stack:
            p = stack.pop()
            if p not in seen:
                seen.add(p)
                total += rss.get(p, 0)
                stack += kids.get(p, [])
        out[root] = total
    return out


def unit_costs(kinds, table=None):
    """{kind: bytes one more unit of it is charged}, from `kinds` ({pid:
    kind} of the running units): the largest measured, at least UNIT_MIN.
    A kind absent from the result is charged UNIT."""
    costs = {}
    for pid, size in tree_rss(list(kinds), table).items():
        costs[kinds[pid]] = max(costs.get(kinds[pid], UNIT_MIN), size)
    return costs


def load():
    try:
        return os.getloadavg()[0]
    except OSError:
        return None


#: The niceness of background work (the corpus job, the OCR, the burn, every
#: unit_queue unit: tools/unit_queue.py UNIT_NICE). Its threads take a core
#: only when nothing less nice wants it, so they cost the bridge and a shell
#: nothing, and foreground_load() leaves them out.
BACKGROUND_NICE = 19
#: foreground_load's samples of the run queue, and the gap between them.
FG_SAMPLES = 4
FG_GAP_S = 0.25


def runnable_by_nice(proc="/proc", skip=()):
    """{nice: threads runnable now} across `proc`, leaving out the threads of
    the pids in `skip`; None when it cannot be read (no /proc: macOS)."""
    counts = {}
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit() and int(p) not in skip]
    except OSError:
        return None
    for pid in pids:
        try:
            tids = os.listdir(f"{proc}/{pid}/task")
        except OSError:
            continue
        for tid in tids:
            try:
                with open(f"{proc}/{pid}/task/{tid}/stat") as f:
                    stat = f.read()
            except OSError:
                continue
            fields = stat[stat.rfind(")") + 2:].split()
            try:
                if fields[0] == "R":
                    nice = int(fields[16])
                    counts[nice] = counts.get(nice, 0) + 1
            except (IndexError, ValueError):
                continue
    return counts


def foreground_load(sampler=None, samples=None, gap=None, sleep=time.sleep):
    """The run queue less background work: the mean, over FG_SAMPLES looks
    FG_GAP_S apart, of runnable threads niced under BACKGROUND_NICE (this
    process's own left out). None when the run queue cannot be read.

    This, not the load average, is what a nice-19 unit's start must answer
    to. The load average counts the nice-19 corpus job, OCR and burn too, so
    while they run it sits over any ceiling and a gate on it never opens
    (2026-10-13..15: the daily ratings, checks, minute and reports units went
    days without a slot at load 20-25 on 6 cores, of which nice 0 was ~3)."""
    sampler = sampler or (lambda: runnable_by_nice(skip=(os.getpid(),)))
    samples = FG_SAMPLES if samples is None else samples
    gap = FG_GAP_S if gap is None else gap
    seen = []
    for i in range(samples):
        if i:
            sleep(gap)
        counts = sampler()
        if counts is None:
            return None
        seen.append(sum(n for nice, n in counts.items() if nice < BACKGROUND_NICE))
    return sum(seen) / len(seen) if seen else None


def cpu_room(started=0, reader=None, cores=None, per_core=LOAD_PER_CORE):
    """True if the load average (reader's, else this host's), plus `started`
    units begun this pass, is under per_core x cores."""
    now = (reader or load)()
    cores = cores or os.cpu_count()
    return now is None or not cores or now + started < per_core * cores


#: idle_cores' window: it measures from the newest sample at least
#: IDLE_SPAN_S old (or, before there is one, the oldest at least IDLE_FIRST_S
#: old, sampling that long once when there is none), keeping IDLE_KEEP_S.
IDLE_SPAN_S = 10
IDLE_FIRST_S = 0.5
IDLE_KEEP_S = 60
#: Idle cores that must be left after a local unit starts (CT_IDLE_MIN overrides).
IDLE_MIN = float(os.environ.get("CT_IDLE_MIN") or 1)
_IDLE = collections.deque()  # (monotonic time, busy ticks, all ticks)


def stat_ticks(stat):
    """(busy, all) ticks since boot from /proc/stat's cpu line; busy leaves
    out idle and iowait."""
    f = [int(x) for x in stat.split("\n", 1)[0].split()[1:9]]
    return sum(f) - f[3] - f[4], sum(f)


def _read_stat():
    with open("/proc/stat") as fh:
        return fh.readline()


def idle_cores(reader=None, cores=None, clock=time.monotonic, samples=None, sleep=time.sleep):
    """Cores this host left idle over about the last IDLE_SPAN_S, from
    /proc/stat (reader: its first line), or None when it cannot be read."""
    samples = _IDLE if samples is None else samples
    cores = cores or os.cpu_count()
    try:
        def sample():
            return (clock(), *stat_ticks((reader or _read_stat)()))
        now = sample()
        while samples and now[0] - samples[0][0] > IDLE_KEEP_S:
            samples.popleft()
        if not any(now[0] - t >= IDLE_FIRST_S for t, _, _ in samples):
            samples.append(now)
            sleep(IDLE_FIRST_S)
            now = sample()
        old = [s for s in samples if now[0] - s[0] >= IDLE_SPAN_S]
        then = old[-1] if old else next(s for s in samples if now[0] - s[0] >= IDLE_FIRST_S)
        samples.append(now)
    except (OSError, ValueError, IndexError, StopIteration):
        return None
    total = now[2] - then[2]
    if total <= 0 or not cores:
        return None
    return cores * (1 - (now[1] - then[1]) / total)


def idle_room(started=0, reader=None, need=None):
    """True if the idle cores (reader's, else idle_cores()), less one for
    each local unit `started` this pass, still hold `need` (IDLE_MIN) for
    one more to start on. An unread figure gates nothing."""
    idle = (reader or idle_cores)()
    return idle is None or idle - started >= (IDLE_MIN if need is None else need)


#: The burn's plan, in the main checkout (CT_BURN_STATE overrides: tests run
#: ticks on a host whose own burn must not gate them), and the age past which
#: it is no burn's: the planner re-plans at every 300s pool checkpoint.
BURN_STATE = ".prereset.width"
BURN_STALE_S = 900


@functools.lru_cache(maxsize=1)
def main_checkout():
    if os.environ.get("CT_MAIN_CHECKOUT"):
        return Path(os.environ["CT_MAIN_CHECKOUT"])
    common = subprocess.run(["git", "-C", str(Path(__file__).resolve().parent), "rev-parse",
                             "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    return Path(common).parent


def burn_state(path=None, now=None):
    """The burn's last plan as a dict, or None when there is none, it cannot
    be read, or it is older than BURN_STALE_S."""
    try:
        path = Path(path or os.environ.get("CT_BURN_STATE") or main_checkout() / BURN_STATE)
        if (now or time.time()) - path.stat().st_mtime > BURN_STALE_S:
            return None
        state = json.loads(path.read_text())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return state if isinstance(state, dict) else None


def burn_starved(reader=None):
    """The burn's plan (reader's, else burn_state's) when its cpu cap holds it
    below its need and its memory cap, else None."""
    state = (reader or burn_state)()
    if not state:
        return None
    need, mem, cpu = state.get("need"), state.get("mem"), state.get("cpu")
    if not isinstance(need, (int, float)) or not isinstance(cpu, (int, float)):
        return None
    allowed = need if not isinstance(mem, (int, float)) else min(need, mem)
    return state if cpu < allowed else None


def burn_line(state):
    """Why a gated queue starts nothing, from burn_starved's plan."""
    return (f"burn-first: the burn's cpu cap is {state['cpu']} runs, below the {state['need']} it needs; "
            "no unit starts until it has its width")
