"""Make a nice-19 process's whole session yield, not just the process.

With sched_autogroup_enabled=1 the CPU is split between sessions by the
session's autogroup nice, and a process's own nice only ranks it inside its
group. The annotate burn runs at nice 19 in an autogroup at nice 19, but what
its `claude -p` runs start through their Bash tool (annotate_check.py,
apply_annotations.py, failed_inputs.py), push_puzzle_commit.sh --flush and the
daily_unit-N resets each begin a NEW session whose autogroup is nice 0, so
their nice 19 did nothing against the bridge.

One rule, here: a process whose own nice is >= 19 while its autogroup is lower
raises the autogroup to 19 (lowering priority is always allowed). A group shared
with pid 1 is the bridge's and is never touched. Where there is no
/proc/self/autogroup nothing happens.

    import yield_cpu; yield_cpu.yield_autogroup()   # first import of an entry point
    python3 tools/yield_cpu.py        # from a shell: . tools/yield_cpu.sh
"""
import os
import time

LIMIT = 19


def _read(path):
    try:
        with open(path) as f:
            return f.read().split()
    except OSError:
        return None


def yield_autogroup():
    """Raise this session's autogroup nice to 19 if the process is at 19."""
    try:
        if os.nice(0) < LIMIT:
            return False
    except OSError:
        return False
    own, init = _read("/proc/self/autogroup"), _read("/proc/1/autogroup")
    if not own or len(own) < 3 or (init and init[0] == own[0]):
        return False
    if int(own[2]) >= LIMIT:
        return False
    # The kernel refuses a write within 100 ms of any previous one with EAGAIN.
    for _ in range(60):
        try:
            with open("/proc/self/autogroup", "w") as f:
                f.write(str(LIMIT))
            return True
        except OSError:
            time.sleep(0.05)
    return False


yield_autogroup()
