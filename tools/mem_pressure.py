"""Memory pressure for the pre-reset burn's width (tools/prereset_plan.py).

Free memory alone misses a box that is thrashing its page cache: rereading
files the kernel keeps dropping does not lower MemAvailable, but it shows in
/proc/pressure/memory ("some avg10", the share of the last 10 s some task
stalled on memory) and, once it swaps, in /proc/vmstat pswpin. The burn read
~950 MB/min of cache with 7.7 GB "free" (11-14).

`cap(state_path, alive, now)` returns (width cap or None, words). Hot: some
avg10 above HOT_PSI, or swap-in above HOT_SWAPIN_MB_MIN since the last call.
While hot the cap is 3/4 of the runs alive (never under 1), lowered at most
once per STEP_S. Quiet: avg10 under QUIET_PSI and swap-in under QUIET_SWAPIN
for QUIET_S straight; then the cap rises by RAISE_STEP per STEP_S until it
is dropped. In between (the hysteresis band) the cap holds. If either file
is unreadable the cap is None: the old free-memory behaviour. State is one
JSON line at state_path."""
import json
import re
import sys
import time
from pathlib import Path

HOT_PSI = 1.0
QUIET_PSI = 0.3
HOT_SWAPIN_MB_MIN = 1.0
QUIET_SWAPIN_MB_MIN = 0.25
QUIET_S = 600
STEP_S = 120
RAISE_STEP = 2
PAGE = 4096


def read_psi(text):
    """some avg10 from /proc/pressure/memory text, None if absent."""
    m = re.search(r"^some .*?\bavg10=([\d.]+)", text or "", re.MULTILINE)
    return float(m[1]) if m else None


def read_pswpin(text):
    m = re.search(r"^pswpin (\d+)", text or "", re.MULTILINE)
    return int(m[1]) if m else None


def _read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def step(state, psi, pswpin, alive, now):
    """(new state, cap or None, words) from the previous state and readings."""
    st = dict(state or {})
    rate = None
    if st.get("t") is not None and st.get("pswpin") is not None and now > st["t"]:
        rate = max(0, pswpin - st["pswpin"]) * PAGE / 1048576 / ((now - st["t"]) / 60)
    # a window shorter than 20 s is too short to call a rate
    if rate is not None and now - st["t"] < 20:
        rate = None
        keep_t, keep_p = st["t"], st["pswpin"]
    else:
        keep_t, keep_p = now, pswpin
    st["t"], st["pswpin"] = keep_t, keep_p
    swap = rate if rate is not None else st.get("rate", 0.0)
    st["rate"] = swap
    hot = psi > HOT_PSI or swap > HOT_SWAPIN_MB_MIN
    quiet = psi < QUIET_PSI and swap < QUIET_SWAPIN_MB_MIN
    cap = st.get("cap")
    if hot:
        st["quiet_since"] = None
        if cap is None or now - st.get("moved", 0) >= STEP_S:
            base = alive if cap is None else min(cap, alive)
            cap = max(1, int(base * 3 / 4))
            st["moved"] = now
    elif quiet:
        if st.get("quiet_since") is None:
            st["quiet_since"] = now
        if cap is not None and now - st["quiet_since"] >= QUIET_S and now - st.get("moved", 0) >= STEP_S:
            cap += RAISE_STEP
            st["moved"] = now
            if cap > max(alive, 1) + RAISE_STEP:
                cap = None
    else:
        st["quiet_since"] = None
    st["cap"] = cap
    words = f"pressure some avg10 {psi:.2f}, swap-in {swap:.2f} MB/min" + (
        f", held to {cap}" if cap is not None else "")
    return st, cap, words


def cap(state_path, alive, now=None, psi_text=None, vmstat_text=None):
    """(cap or None, words or None); None, None when either file is missing."""
    now = time.time() if now is None else now
    psi = read_psi(_read("/proc/pressure/memory") if psi_text is None else psi_text)
    pin = read_pswpin(_read("/proc/vmstat") if vmstat_text is None else vmstat_text)
    if psi is None or pin is None:
        return None, None
    try:
        state = json.loads(Path(state_path).read_text())
    except (OSError, ValueError):
        state = None
    state, held, words = step(state, psi, pin, alive, now)
    try:
        Path(state_path).write_text(json.dumps(state) + "\n")
    except OSError:
        pass
    return held, words


def self_test():
    bad = 0

    def check(label, got, want):
        nonlocal bad
        if got != want:
            print(f"FAIL mem_pressure {label}: {got} (want {want})", file=sys.stderr)
            bad += 1
    check("psi", read_psi("some avg10=2.50 avg60=1.00 avg300=0.10 total=5\nfull avg10=0.00"), 2.5)
    check("psi missing", read_psi(""), None)
    check("pswpin", read_pswpin("pgpgin 5\npswpin 77\n"), 77)
    s, c, _ = step(None, 0.1, 0, 20, 1000)
    check("first quiet", c, None)
    s, c, _ = step(s, 2.0, 0, 20, 1060)
    check("hot lowers", c, 15)
    s, c, _ = step(s, 2.0, 0, 15, 1100)
    check("hot rate-limited", c, 15)
    s, c, _ = step(s, 2.0, 0, 15, 1200)
    check("hot again", c, 11)
    s, c, _ = step(s, 0.6, 0, 11, 1300)
    check("band holds", c, 11)
    s, c, _ = step(s, 0.1, 0, 11, 1400)
    s, c, _ = step(s, 0.1, 0, 11, 1900)
    check("quiet not yet sustained", c, 11)
    s, c, _ = step(s, 0.1, 0, 11, 2050)
    check("quiet raises", c, 13)
    s, c, _ = step(s, 0.1, 0, 13, 2200)
    check("raises stepwise", c, 15)
    # swap-in: 4096 pages = 16 MB over a minute is hot with psi calm
    s, c, _ = step({"t": 0, "pswpin": 0, "cap": None}, 0.0, 4096, 8, 60)
    check("swap-in hot", c, 6)
    s, c, _ = step({"t": 0, "pswpin": 0, "cap": None}, 0.0, 100, 8, 60)
    check("swap-in small", c, None)
    return bad


if __name__ == "__main__":
    sys.exit(1 if self_test() else 0)
