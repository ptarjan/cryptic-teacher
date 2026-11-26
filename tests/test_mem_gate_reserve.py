#!/usr/bin/env python3
# Does the ceiling's step-up hold (tools/mem_gate.py up_reserve / step_up_held) size its reserve from
# measured peaks: old units at their peak -> a small reserve; young units -> a large one; no history
# (or CT_VM_UP_UNITS) -> the old FLOOR + 4 x UNIT?
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

# Old units already at peak: only the new units' expected peak is reserved.
old = [("read", 300 * M)] * 20
res_old, parts = mg.up_reserve(old, 2, peaks)
# 2 new units, each 300 or 800 MB: mean 550, sd 250 -> 2 x 550 + 1.645 x 250 x sqrt(2)
want_old = int(2 * 550 * M + 1.645 * 250 * M * 2 ** 0.5)
check("old units at peak: only 2 new units from the all-kinds mix", want_old, res_old)
check("parts text names mean and sd", True, "growth (mean 1100 + 1.645 sd 353) in 20 running + 2 new" in parts)
check("old units: a 5.2 GB VM is no longer held", None,
      mg.step_up_held(20, 22, 0, None, mg.FLOOR + 2200 * M, (res_old, parts)))

# Young units: still growing toward their peak.
young = [("read", 100 * M)] * 10 + [("scan", 380 * M)] * 10
res_young, _ = mg.up_reserve(young, 2, peaks)
check("young units: identical peaks per kind, so sd only from the 2 new", int((2000 + 4200 + 1100) * M + 1.645 * 250 * M * 2 ** 0.5), res_young)
check("young units: held where old units were not", True,
      mg.step_up_held(20, 22, 0, None, mg.FLOOR + 5000 * M, (res_young, "")) is not None)
check("a unit above its peak adds no negative growth (1 new unit from the 300/800 mix)",
      int(550 * M + 1.645 * 250 * M), mg.up_reserve([("read", 900 * M)], 1, peaks)[0])

# Statistics: 12 units of one kind with spread peaks reserve far less than 12 x p90 growth; one unit, its p90.
spread = hist(w=[(100 + 10 * i) * M for i in range(20)])  # 100..290 MB, p90 = 270 MB
twelve, txt = mg.up_reserve([("w", 0)] * 12, 1, spread)
p90 = mg._high(spread["w"])
check("12 spread units reserve clearly less than 12 x p90 growth", True, twelve < 0.9 * 13 * p90)
check("12 spread units still reserve more than their mean growth", True, twelve > 13 * 195 * M)
one, _ = mg.up_reserve([], 1, spread)
check("a single unit reserves at least its p90 growth", True, one >= p90)
tight = hist(w=[300 * M] * 10)
check("a single unit with equal peaks reserves exactly its p90 growth", 300 * M, mg.up_reserve([], 1, tight)[0])
check("a single running unit reserves its p90 growth left (one running, no new beyond the min 1 is mean-only)",
      True, mg.up_reserve([("w", 100 * M)], 1, tight)[0] == 500 * M)

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
check("small Listener pages leave no growth: reserve is the one new unit's mix draw",
      int(850 * M + 1.645 * 550 * M), mg.up_reserve([("listener", 300 * M)] * 5, 1, fine)[0])

# CT_VM_UP_UNITS restores the old rule.
mg.VM_UP_FIXED = True
check("CT_VM_UP_UNITS set: old rule despite history", mg.VM_UP_UNITS * mg.UNIT, mg.up_reserve(old, 2, peaks)[0])
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

sys.exit(1 if failed else 0)
