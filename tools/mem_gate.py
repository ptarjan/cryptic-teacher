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
holds back only CPU-bound starts on a host already oversubscribed."""
import os
import subprocess

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
