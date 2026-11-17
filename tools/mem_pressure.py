"""Memory pressure for the pre-reset burn's width (tools/prereset_plan.py).

Free memory alone misses a box that is thrashing its page cache: rereading
files the kernel keeps dropping does not lower MemAvailable, but it shows in
/proc/pressure/memory ("some avg10", the share of the last 10 s some task
stalled on memory) and, once it swaps, in /proc/vmstat pswpin. The burn read
~950 MB/min of cache with 7.7 GB "free" (11-14).

`cap(state_path, alive, now)` returns (width cap or None, words). Hot: full
avg10 AND avg60 above HOT_PSI (every task stalled at once and
sustained: thrash, not one 10 s burst), or swap-in above HOT_SWAPIN_MB_MIN since the last call. While
hot the cap is 3/4 of itself (of the runs alive when not yet held; never
under 1), lowered at most once per STEP_S. Calm (not hot) for BAND_S: the cap
rises by 1 per BAND_S. Quiet (avg10 under QUIET_PSI, swap-in under
QUIET_SWAPIN) for QUIET_S straight: it rises by RAISE_STEP per STEP_S until
it is dropped. If either file is unreadable the cap is None: the old
free-memory behaviour. State is one JSON line at state_path."""
import json
import re
import sys
import time
from pathlib import Path

#: "full" PSI (all tasks stalled), the same bar as mem_gate.PSI_MAX. Ordinary
#: ambient "some" stall of 4-6% and "full" of ~3% with no swap-in (11-17, other
#: rooms' jobs) held the cap at 1 for hours; a width-1 burn cannot lower it.
HOT_PSI = 10.0
QUIET_PSI = 0.5
HOT_SWAPIN_MB_MIN = 1.0
QUIET_SWAPIN_MB_MIN = 0.25
QUIET_S = 300
#: Calm but not quiet (PSI between quiet and hot), the pressure is usually other
#: rooms' doing and a burn held at the floor cannot lower it; raise anyway, one
#: run per this long, so the cap never sticks at 1 for hours (11-14). One timer
#: since the last hot reading: 11-15 the quiet and band timers reset each other
#: as avg10 wobbled across QUIET_PSI, neither ever ran out, and the cap sat at 1
#: for ~24h with memory room for 8-18 runs.
BAND_S = 600
STEP_S = 120
RAISE_STEP = 2
PAGE = 4096


def read_psi(text, field="avg10", kind="some"):
    """`kind` (some, full) `field` (avg10, avg60) from /proc/pressure/memory text, None if absent."""
    m = re.search(rf"^{kind} .*?\b{field}=([\d.]+)", text or "", re.MULTILINE)
    return float(m[1]) if m else None


def read_pswpin(text):
    m = re.search(r"^pswpin (\d+)", text or "", re.MULTILINE)
    return int(m[1]) if m else None


def _read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def step(state, psi, pswpin, alive, now, psi60=None, full=None, full60=None):
    """(new state, cap or None, words) from the previous state and readings.
    `psi60` (some avg60) defaults to `psi`; `full`/`full60` (full avg10/avg60,
    the hot test) default to `psi`/`psi60`."""
    st = dict(state or {})
    psi60 = psi if psi60 is None else psi60
    full = psi if full is None else full
    full60 = psi60 if full60 is None else full60
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
    hot = (full > HOT_PSI and full60 > HOT_PSI) or swap > HOT_SWAPIN_MB_MIN
    quiet = psi < QUIET_PSI and swap < QUIET_SWAPIN_MB_MIN
    cap = st.get("cap")
    st.pop("band_since", None)  # pre-11-15 state: the calm timer replaced it
    if hot:
        st["quiet_since"] = st["calm_since"] = None
        if cap is None or now - st.get("moved", 0) >= STEP_S:
            # cut the cap itself: the runs alive under a held cap are few
            # (1-2 at width 1), and cutting from them dropped a cap of 6 to 1
            # on one hot reading (11-15)
            base = max(1, alive) if cap is None else cap
            cap = max(1, int(base * 3 / 4))
            st["moved"] = now
    else:
        if st.get("calm_since") is None:
            st["calm_since"] = now
        if not quiet:
            st["quiet_since"] = None
        elif st.get("quiet_since") is None:
            st["quiet_since"] = now
        since = now - st.get("moved", 0)
        if cap is not None:
            if quiet and now - st["quiet_since"] >= QUIET_S and since >= STEP_S:
                cap += RAISE_STEP
                st["moved"] = now
            elif now - st["calm_since"] >= BAND_S and since >= BAND_S:
                cap += 1
                st["moved"] = now
            if st["moved"] == now and cap > max(alive, 1) + RAISE_STEP:
                cap = None
    st["cap"] = cap
    words = f"pressure some avg10 {psi:.2f} avg60 {psi60:.2f}, full avg10 {full:.2f} avg60 {full60:.2f}, swap-in {swap:.2f} MB/min" + (
        f", held to {cap}" if cap is not None else "")
    return st, cap, words


def cap(state_path, alive, now=None, psi_text=None, vmstat_text=None):
    """(cap or None, words or None); None, None when either file is missing."""
    now = time.time() if now is None else now
    psi_text = _read("/proc/pressure/memory") if psi_text is None else psi_text
    psi, psi60 = read_psi(psi_text), read_psi(psi_text, "avg60")
    pin = read_pswpin(_read("/proc/vmstat") if vmstat_text is None else vmstat_text)
    if psi is None or pin is None:
        return None, None
    try:
        state = json.loads(Path(state_path).read_text())
    except (OSError, ValueError):
        state = None
    full, full60 = read_psi(psi_text, kind="full"), read_psi(psi_text, "avg60", "full")
    state, held, words = step(state, psi, pin, alive, now, psi60, full, full60)
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
    s, c, _ = step(s, 12.0, 0, 20, 1060)
    check("hot lowers", c, 15)
    s, c, _ = step(s, 12.0, 0, 15, 1100)
    check("hot rate-limited", c, 15)
    s, c, _ = step(s, 12.0, 0, 15, 1200)
    check("hot again", c, 11)
    s, c, _ = step(s, 0.6, 0, 11, 1300)
    check("band holds", c, 11)
    s, c, _ = step(s, 0.1, 0, 11, 1400)
    s, c, _ = step(s, 0.1, 0, 11, 1600)
    check("quiet not yet sustained", c, 11)
    s, c, _ = step(s, 0.1, 0, 11, 1750)
    check("quiet raises", c, 13)
    s, c, _ = step(s, 0.1, 0, 13, 1900)
    check("raises stepwise", c, 15)
    check("avg60", read_psi("some avg10=2.50 avg60=1.25 avg300=0.10 total=5", "avg60"), 1.25)
    # 11-15: a 10 s burst (avg10 hot, avg60 calm) is another room's blip, not a cut
    s, c, _ = step({"t": 0, "pswpin": 0, "cap": 6, "moved": 0}, 15.0, 0, 1, 1000, psi60=0.4)
    check("avg10 spike alone holds", c, 6)
    # 11-15: hot under a held cap cuts the cap, not the 1 run alive (was 6 -> 1)
    s, c, _ = step({"t": 0, "pswpin": 0, "cap": 6, "moved": 0}, 15.0, 0, 1, 1000, psi60=12.0)
    check("hot cuts the cap, not alive", c, 4)
    # 11-15: avg10 wobbling across QUIET_PSI still accrues calm time and climbs
    s = {"t": 0, "pswpin": 0, "cap": 1, "moved": 0}
    for i in range(12):
        s, c, _ = step(s, 0.3 if i % 2 else 0.7, 0, 1, 60 * (i + 1))
    check("wobble climbs", c, 2)
    # 11-17: ambient some 5 / full 3 with no swap-in is not hot
    s, c, _ = step({"t": 0, "pswpin": 0, "cap": 6, "moved": 0}, 5.0, 0, 1, 1000, 4.0, 3.0, 3.0)
    check("ambient stall holds", c, 6)
    s, c, _ = step({"t": 0, "pswpin": 0, "cap": 6, "moved": 0}, 5.0, 0, 1, 1000, 4.0, 12.0, 11.0)
    check("full stall cuts", c, 4)
    check("full", read_psi("some avg10=1 avg60=2\nfull avg10=3.5 avg60=1", kind="full"), 3.5)
    # swap-in: 4096 pages = 16 MB over a minute is hot with psi calm
    s, c, _ = step({"t": 0, "pswpin": 0, "cap": None}, 0.0, 4096, 8, 60)
    check("swap-in hot", c, 6)
    s, c, _ = step({"t": 0, "pswpin": 0, "cap": None}, 0.0, 100, 8, 60)
    check("swap-in small", c, None)
    # band with swap-in quiet: holds, then creeps up after BAND_S
    s, c, _ = step({"t": 0, "pswpin": 0, "cap": 1, "moved": 0}, 0.5, 0, 1, 60)
    check("band floor holds", c, 1)
    s, c, _ = step(s, 0.5, 0, 1, 60 + BAND_S)
    check("band creeps up", c, 2)
    s, c, _ = step(s, 0.5, 0, 2, 120 + BAND_S)
    check("band creep rate-limited", c, 2)
    return bad


if __name__ == "__main__":
    sys.exit(1 if self_test() else 0)
