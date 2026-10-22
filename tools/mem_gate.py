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
#: CT_CEILING_LO/HI (8/24), CT_CEILING_CPU_HI/LO (90/80), CT_CEILING_EVERY (120 s); the page-cache
#: drop is CT_GAME_DROP_CACHE. The VLM slows ~2x when Windows CPU is pegged (10-21 A/B: 6 scans
#: paused -> CPU 97 -> 67%, asks 3.1 -> 5.8/min), so it steps down above CPU_HI, up only below CPU_LO.
#: It writes the same file unit_ceiling() reads, so a manual pin holds until the next step moves it.
CEILING_EVERY = 120


def ceiling_step(ceiling, free_mb, cpu, lo=8, hi=24, cpu_hi=90, cpu_lo=80):
    """The new ceiling: -2 when Windows has under 2000 MB free or CPU is over cpu_hi, +2 when over
    4500 MB free and CPU (unknown counts as busy) under cpu_lo; clamped to lo..hi. No RAM figure: unchanged."""
    if free_mb is None:
        return ceiling
    new = ceiling
    if free_mb < 2000 or (cpu or 0) > cpu_hi:
        new = ceiling - 2
    elif free_mb > 4500 and (100 if cpu is None else cpu) < cpu_lo:
        new = ceiling + 2
    return max(lo, min(hi, new))


def _win_free(host):
    import re
    try:
        out = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host,
                              'powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1KB)"'],
                             capture_output=True, text=True, timeout=20).stdout
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

    def _run(self):
        free = _win_free(self.host)
        cpu = _win_cpu(self.metrics) if self.metrics else None
        if free is not None and free < 3000 and self.drop_cmd:
            try:
                subprocess.run(["sh", "-c", self.drop_cmd], stdin=subprocess.DEVNULL, capture_output=True, timeout=40)
            except (OSError, subprocess.SubprocessError):
                pass
            again = _win_free(self.host)
            self.lines.append(f"ceiling: win free {free} MB -> dropped cache -> {again} MB")
            free = again if again is not None else free
        if free is None:
            return
        env = os.environ.get
        cur = unit_ceiling()
        new = ceiling_step(cur, free, cpu, int(env("CT_CEILING_LO") or 8), int(env("CT_CEILING_HI") or 24),
                           int(env("CT_CEILING_CPU_HI") or 90), int(env("CT_CEILING_CPU_LO") or 80))
        if new != cur:
            path = os.path.expanduser(env("CT_UNIT_CEILING_FILE") or CEILING_FILE)
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(f"{new}\n")
            except OSError as e:
                self.lines.append(f"ceiling: cannot write {path}: {e}")
                return
            self.lines.append(f"ceiling: win free {free} MB cpu {cpu}%: {cur} -> {new}")

    def poll(self, now=None):
        now = time.monotonic() if now is None else now
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
