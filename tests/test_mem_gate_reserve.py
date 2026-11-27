#!/usr/bin/env python3
# Does the ceiling's step-up hold (tools/mem_gate.py up_reserve / step_up_held) size its reserve from
# what was measured: the new units' steady size, how far the running pool is under its steady size, and
# the 95% fall of MemAvailable at a standing ceiling (note_avail); a grown pool -> a small reserve, a
# young one -> a large one; nothing measured (or CT_VM_UP_UNITS) -> the old FLOOR + 4 x UNIT?
#
#     python3 tests/test_mem_gate_reserve.py
#
# Fake data only; no live ~/.cache, no processes.
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
os.environ.pop("CT_VM_UP_UNITS", None)
import mem_gate as mg

M = 1 << 20
failed = 0


def check(name, want, got):
    global failed
    if want != got:
        failed += 1
        print(f"FAIL {name}: want {want!r}, got {got!r}")
    else:
        print(f"ok   {name}")


def hist(**kinds):
    h = {}
    for k, vals in kinds.items():
        h[k] = collections.deque(vals, maxlen=mg.PEAK_KEEP)
    return h


peaks = hist(read=[300 * M] * 10, scan=[800 * M] * 10)

# No history: the old rule exactly.
res, _ = mg.up_reserve([("read", 100 * M)] * 20, 2, {})
check("no history: reserve is VM_UP_UNITS x UNIT", mg.VM_UP_UNITS * mg.UNIT, res)
check("no history: held under FLOOR + 4 UNIT, same as the old rule",
      (True, False),
      (mg.step_up_held(20, 22, 0, None, mg.FLOOR + 3 * mg.UNIT, (res, "")) is not None,
       mg.step_up_held(20, 22, 0, None, mg.FLOOR + 4 * mg.UNIT, (res, "")) is not None))
check("reserve=None keeps the old signature's rule", True,
      mg.step_up_held(20, 22, 0, None, mg.FLOOR + mg.UNIT) is not None)

# The measured rule: reserve = new units x steady size + the pool's shortfall under its steady size
# + the 95% fall of MemAvailable (scaled by the pool's growth).
steady = hist(read=[300 * M] * 10, scan=[700 * M] * 10)  # every reading: mean 500 MB
drops = collections.deque((i * 50 * M for i in range(40)), maxlen=mg.DROP_KEEP)  # 0..1950 MB, p95 = 1900 MB
check("p95 of the falls rounds up to a fall that occurred", 1900 * M, mg._quantile(drops, mg.RESERVE_Q))
check("steady size: the kind's own mean, a new unit's the whole pool's", (300 * M, 700 * M, 500 * M),
      (mg.steady_size("read", steady, peaks), mg.steady_size("scan", steady, peaks), mg.steady_size(None, steady, peaks)))
grown = [("read", 300 * M)] * 10 + [("scan", 700 * M)] * 10
res_old, parts = mg.up_reserve(grown, 2, peaks, drops, steady)
swing = int(1900 * M * min(2.0, 22 / 20))
check("grown pool: 2 new at steady size + the scaled p95 fall, nothing for the running", 1000 * M + swing, res_old)
check("parts text names each term", True,
      "2 new x 500 MB steady + 0 MB the 20 running are under their steady size + 2090 MB p95 fall in "
      f"{mg.DROP_SPAN} s of 40 measured" in parts)
check("grown pool: far under every unit's growth to its peak (the old rule's sum)", True,
      res_old < 10 * 100 * M + 2 * 800 * M + 2000 * M)
check("grown pool: a VM with FLOOR + 3.1 GB is not held, one with FLOOR + 3 GB is", (None, True),
      (mg.step_up_held(20, 22, 0, None, mg.FLOOR + 3100 * M, (res_old, parts)),
       mg.step_up_held(20, 22, 0, None, mg.FLOOR + 3000 * M, (res_old, parts)) is not None))

young = [("read", 100 * M)] * 10 + [("scan", 380 * M)] * 10
res_young, _ = mg.up_reserve(young, 2, peaks, drops, steady)
check("young pool: its shortfall under steady size is reserved too", (1000 + 2000 + 3200) * M + swing, res_young)
check("young pool: held where the grown one was not", True,
      mg.step_up_held(20, 22, 0, None, mg.FLOOR + 5000 * M, (res_young, "")) is not None)
check("the pool is summed: a unit over its steady size offsets one under it", 500 * M + int(1900 * M * min(2.0, 3 / 2)),
      mg.up_reserve([("read", 500 * M), ("read", 100 * M)], 1, peaks, drops, steady)[0])
check("a pool over its steady size adds no negative growth", 500 * M + 1900 * M * 2,
      mg.up_reserve([("read", 900 * M)], 1, peaks, drops, steady)[0])
check("the fall's scaling stops at 2 (1 running + 3 new)", 1500 * M + 1900 * M * 2,
      mg.up_reserve([("read", 300 * M)], 3, peaks, drops, steady)[0])
check("nothing running: the fall unscaled", 500 * M + 1900 * M, mg.up_reserve([], 1, peaks, drops, steady)[0])

# Too few falls measured: DROP_DEFAULT stands in. No probe readings: the mean of the recorded peaks.
few_drops = collections.deque([10 * M] * (mg.DROP_MIN - 1))
res_few, parts_few = mg.up_reserve(grown, 2, peaks, few_drops, steady)
check("under DROP_MIN falls: the default fall", 1000 * M + int(mg.DROP_DEFAULT * min(2.0, 22 / 20)), res_few)
check("under DROP_MIN falls: the text says so", True, f"default fall ({mg.DROP_MIN - 1} of {mg.DROP_MIN} measured)" in parts_few)
check("no probe readings: a unit's steady size is the mean of its kind's peaks, a new unit's of all peaks",
      (300 * M, 800 * M, 550 * M), (mg.steady_size("read", {}, peaks), mg.steady_size("scan", {}, peaks), mg.steady_size(None, {}, peaks)))
check("peaks only: 2 new x 550 + units under their mean peak + default fall",
      1100 * M + 10 * 420 * M + int(mg.DROP_DEFAULT * min(2.0, 22 / 20)),
      mg.up_reserve([("read", 300 * M)] * 10 + [("scan", 380 * M)] * 10, 2, peaks, collections.deque(), {})[0])
check("a kind with no readings takes its pool's, else every kind's", (700 * M, 500 * M),
      (mg.steady_size("scan ft", hist(**{"scan times": [700 * M] * 3, "read x": [300 * M] * 3}), peaks),
       mg.steady_size("trove", steady, peaks)))

# note_avail: a probe DROP_SPAN old records how far MemAvailable fell under it while the ceiling stood.
seen, got = collections.deque(), []
for i, a in enumerate([7000, 6500, 7200, 5000, 6000, 6800, 6900, 7100, 7000, 7300, 7400]):
    mg.note_avail(seen, i * 120, a * M, 14, got, 600)
# probe 0 (7000) saw a low of 5000 in the next 600 s; probe 1 (6500) too; 2 (7200) too; 3 (5000) never fell;
# 4 (6000) never fell; 5 (6800): its window (to t=1200) is complete at the last probe, low 6900 -> 0.
check("falls at a standing ceiling", [2000 * M, 1500 * M, 2200 * M, 0, 0, 0], got)
check("history keeps only the last span of probes", 5, len(seen))
seen, got = collections.deque(), []
for i, (a, c) in enumerate([(7000, 14), (6500, 14), (6000, 16), (5000, 16), (5500, 16), (5400, 16), (5300, 16), (5200, 16)]):
    mg.note_avail(seen, i * 120, a * M, c, got, 600)
check("a window the ceiling moved in is left out (only the probe at 16 throughout counts)", [1000 * M], got)
seen, got = collections.deque(), []
for t, a in [(0, 7000), (120, 6000), (900, 5000), (1800, 4000)]:
    mg.note_avail(seen, t, a * M, 14, got, 600)
check("a probe followed by under half a span of probes records nothing", [], got)
mg.note_avail(seen, 0, None, 14, got, 600)
check("no MemAvailable figure: nothing noted", [], got)
h = {}
mg.record_steady("read", 0, h)
mg.record_steady("read", 5 * M, h)
check("record_steady keeps positive readings only", [5 * M], list(h["read"]))

# Fallbacks: kind without history uses all kinds; record_peak keeps the last PEAK_KEEP.
check("unknown kind falls back to all kinds", 800 * M, mg.expected_peak("trove", peaks))
check("no history at all falls back to UNIT", mg.UNIT, mg.expected_peak("read", {}))
h = {}
for i in range(mg.PEAK_KEEP + 10):
    mg.record_peak("read", (i + 1) * M, h)
check("history keeps the last PEAK_KEEP", (mg.PEAK_KEEP, 11 * M), (len(h["read"]), h["read"][0]))
mg.record_peak("read", 0, h)
check("a zero peak is not recorded", mg.PEAK_KEEP, len(h["read"]))

# Finer kinds: a kind with KIND_MIN peaks uses its own; fewer, its pool's (first word); a small
# Listener page reader is not charged the Jumbo solution reads' peak.
fine = hist(**{"listener": [300 * M] * 5, "listener jumbo": [1400 * M] * 5})
check("fine kind with history uses its own peaks", 300 * M, mg.expected_peak("listener", fine))
check("fine kind with history uses its own peaks (jumbo)", 1400 * M, mg.expected_peak("listener jumbo", fine))
check("new fine kind falls back to its pool", 1400 * M, mg.expected_peak("listener tls", fine))
few = hist(**{"read times GaleTimes1935UKEnglish": [1100 * M], "read ft GaleFT1975UKEnglish": [600 * M] * 4})
check("fine kind under KIND_MIN uses its pool", 1100 * M, mg.expected_peak("read times GaleTimes1935UKEnglish", few))
check("small Listener pages at their steady size leave no growth: one new unit + the fall",
      850 * M + int(1900 * M * min(2.0, 6 / 5)), mg.up_reserve([("listener", 300 * M)] * 5, 1, fine, drops, fine)[0])

# CT_VM_UP_UNITS restores the old rule.
mg.VM_UP_FIXED = True
check("CT_VM_UP_UNITS set: old rule despite history", mg.VM_UP_UNITS * mg.UNIT,
      mg.up_reserve(grown, 2, peaks, drops, steady)[0])
mg.VM_UP_FIXED = False

# Peaks survive a restart: save, load into a fresh dict, equal; bad file = empty. Temp HOME only.
import tempfile
with tempfile.TemporaryDirectory() as home:
    os.environ["HOME"] = home
    check("peaks path under HOME", home, str(mg.peaks_path())[:len(home)])
    saved = hist(**{"listener": [300 * M, 310 * M], "read times X": [1100 * M] * 3})
    check("save ok", True, mg.save_peaks(peaks=saved))
    back = {}
    mg.load_peaks(peaks=back)
    check("reloaded peaks equal", {k: list(v) for k, v in saved.items()}, {k: list(v) for k, v in back.items()})
    check("loading into a private dict leaves saving off", False, mg._peaks_saving)
    mg.peaks_path().write_text("{not json")
    empty = {}
    mg.load_peaks(peaks=empty)
    check("bad file = empty", {}, empty)

    check("pool path under HOME", home, str(mg.pool_path())[:len(home)])
    check("pool save ok", True, mg.save_pool(drops=drops, steady=steady))
    d2, s2 = collections.deque(maxlen=mg.DROP_KEEP), {}
    mg.load_pool(drops=d2, steady=s2)
    check("reloaded falls and steady sizes equal", (list(drops), {k: list(v) for k, v in steady.items()}),
          (list(d2), {k: list(v) for k, v in s2.items()}))
    check("loading into private stores leaves saving off", False, mg._pool_saving)
    mg.pool_path().write_text("[1, 2")
    d3, s3 = collections.deque(), {}
    mg.load_pool(drops=d3, steady=s3)
    check("bad pool file = empty", ([], {}), (list(d3), s3))

sys.exit(1 if failed else 0)
