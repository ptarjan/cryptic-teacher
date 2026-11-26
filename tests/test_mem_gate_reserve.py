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
check("old units at peak: no growth left, 2 new x 800 MB (all-kind p90)", 2 * 800 * M, res_old)
check("parts text names the growth", True, "0 MB growth" in parts)
check("old units: a 5.2 GB VM is no longer held", None,
      mg.step_up_held(20, 22, 0, None, mg.FLOOR + 2200 * M, (res_old, parts)))

# Young units: still growing toward their peak.
young = [("read", 100 * M)] * 10 + [("scan", 380 * M)] * 10
res_young, _ = mg.up_reserve(young, 2, peaks)
check("young units: growth 10 x 200 + 10 x 420 MB + 2 new x 800", (2000 + 4200 + 1600) * M, res_young)
check("young units: held where old units were not", True,
      mg.step_up_held(20, 22, 0, None, mg.FLOOR + 5000 * M, (res_young, "")) is not None)
check("a unit above its peak adds no negative growth", 800 * M, mg.up_reserve([("read", 900 * M)], 1, peaks)[0])

# Fallbacks: kind without history uses all kinds; record_peak keeps the last PEAK_KEEP.
check("unknown kind falls back to all kinds", 800 * M, mg.expected_peak("trove", peaks))
check("no history at all falls back to UNIT", mg.UNIT, mg.expected_peak("read", {}))
h = {}
for i in range(mg.PEAK_KEEP + 10):
    mg.record_peak("read", (i + 1) * M, h)
check("history keeps the last PEAK_KEEP", (mg.PEAK_KEEP, 11 * M), (len(h["read"]), h["read"][0]))
mg.record_peak("read", 0, h)
check("a zero peak is not recorded", mg.PEAK_KEEP, len(h["read"]))

# CT_VM_UP_UNITS restores the old rule.
mg.VM_UP_FIXED = True
check("CT_VM_UP_UNITS set: old rule despite history", mg.VM_UP_UNITS * mg.UNIT, mg.up_reserve(old, 2, peaks)[0])
mg.VM_UP_FIXED = False

sys.exit(1 if failed else 0)
