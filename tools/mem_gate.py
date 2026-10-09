"""Is there memory, and CPU, for one more unit? The queues (tools/edition_queue.py,
tools/unit_queue.py) size their pools in CPU slots; each unit process holds
~550 MB, so the pools alone can outrun the host. A queue asks `room()` before
starting a unit and, when it says no, leaves the unit for its next plan.
Running units are never touched.

`available()` is the kernel's own figure: MemAvailable in /proc/meminfo on
Linux; on macOS the free, speculative, purgeable and file-backed page counts
from sysctl, times the page size. None when neither can be read (then
`room()` allows the start: no figure, no gate).

`cpu_room()` is the same question for CPU: the one-minute load average,
plus the units begun this pass, under LOAD_PER_CORE per core. A unit that
waits on the desktop or the network sleeps and adds no load, so the gate
holds back only CPU-bound starts on a host already oversubscribed.

`burn_starved()` puts the pre-reset burn first: tools/prereset_plan.py
writes BURN_STATE (its need, memory cap, cpu cap and width) at every plan,
and while its cpu cap holds it below what its need and memory allow, no
unit starts, so the cores the queue would take go to the burn. A state
older than BURN_STALE_S, or none, means no burn is planning: no gate."""
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
#: Runnable processes per core past which no unit starts: 2 keeps a 4-core
#: host under load 8, so the bridge and an interactive shell still get a core
#: (CT_LOAD_PER_CORE overrides: tests run ticks on a host whose own load must
#: not gate them).
LOAD_PER_CORE = float(os.environ.get("CT_LOAD_PER_CORE") or 2)

_MAC = ("vm.page_free_count", "vm.page_speculative_count", "vm.page_purgeable_count",
        "vm.page_pageable_external_count")


def _sysctl(key):
    return int(subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, check=True, timeout=5).stdout)


def available():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    try:
        return sum(_sysctl(k) for k in _MAC) * _sysctl("hw.pagesize")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def room(started=0, reader=None, floor=FLOOR, unit=UNIT):
    """True if one more unit fits: what is available, less `started` units
    begun in this pass (they have not grown yet), stays above the floor
    with this one's share."""
    avail = (reader or available)()
    return avail is None or avail - started * unit >= floor + unit


def load():
    try:
        return os.getloadavg()[0]
    except OSError:
        return None


def cpu_room(started=0, reader=None, cores=None, per_core=LOAD_PER_CORE):
    """True if the load average (reader's, else this host's), plus `started`
    units begun this pass, is under per_core x cores."""
    now = (reader or load)()
    cores = cores or os.cpu_count()
    return now is None or not cores or now + started < per_core * cores


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
