"""Is there memory for one more unit? The queues (tools/edition_queue.py,
tools/unit_queue.py) size their pools in CPU slots; each unit process holds
~550 MB, so the pools alone can outrun the host. A queue asks `room()` before
starting a unit and, when it says no, leaves the unit for its next plan.
Running units are never touched.

`available()` is the kernel's own figure: MemAvailable in /proc/meminfo on
Linux; on macOS the free, speculative, purgeable and file-backed page counts
from sysctl, times the page size. None when neither can be read (then
`room()` allows the start: no figure, no gate)."""
import subprocess

#: Memory (bytes) that must stay available after a start, and one unit's share.
FLOOR = 3 << 30
UNIT = 600 << 20

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
