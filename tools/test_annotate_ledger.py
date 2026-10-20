#!/usr/bin/env python3
# Does the cost ledger wake the room only when $/clue drifts or a new cause leads?
#
#     python3 tools/test_annotate_ledger.py
#
# Fake ledger rows in, wake / no-wake decisions out (tools/annotate_ledger.py).
import datetime
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "tools")
import annotate_ledger as L

fails = 0
def check(got, want, what):
    global fails
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'}: {what}" + ("" if ok else f"\n    got {got!r}, wanted {want!r}"))
    fails += not ok

T0 = datetime.datetime(2026, 10, 20, 0, 0, tzinfo=datetime.timezone.utc)
def row(i, per_clue, top="rule:a"):
    end = T0 + datetime.timedelta(hours=i)
    return {"start": (end - datetime.timedelta(hours=1)).isoformat(), "end": end.isoformat(),
            "sessions": 10, "clues": 100, "cost": per_clue * 100, "cost_per_clue": per_clue,
            "top_causes": [{"key": top, "label": top, "sessions": 5, "cost_after_check": 1.0}]}
now = T0 + datetime.timedelta(hours=20)
quiet = {"woken": (T0 - datetime.timedelta(hours=30)).isoformat(), "top": "rule:a"}

flat = [row(i, 0.040) for i in range(1, 7)]
check(L.should_wake(flat, None, quiet, now)[0], None, "flat $/clue, same cause: quiet")
check(L.should_wake(flat[:2], None, quiet, now)[0], None, "under 3 rows: quiet")

worse = [row(i, 0.030) for i in range(1, 4)] + [row(i, 0.040) for i in range(4, 7)]
check(L.should_wake(worse, None, quiet, now)[0] is not None, True, "rolling 33% over best: wake")
check(L.should_wake(worse, (T0 + datetime.timedelta(hours=3.5)).isoformat(), quiet, now)[0], None,
      "rows before the last annotate-code commit do not set the best level")

mild = [row(i, 0.040) for i in range(1, 4)] + [row(i, 0.043) for i in range(4, 7)]
check(L.should_wake(mild, None, quiet, now)[0], None, "7.5% over best: quiet")

flip = flat[:5] + [row(6, 0.040, top="rule:b")]
check(L.should_wake(flip, None, quiet, now)[0] is not None, True, "a new #1 cause: wake")
check(L.should_wake(flip, None, {"woken": quiet["woken"], "top": "rule:b"}, now)[0], None,
      "#1 cause the same as at the last wake: quiet")

recent = {"woken": (now - datetime.timedelta(hours=1)).isoformat(), "top": "rule:a"}
check(L.should_wake(worse, None, recent, now)[0], None, "woken an hour ago: cooldown holds")

cheap = [row(i, 0.020) for i in range(1, 4)] + [row(i, 0.021) for i in range(4, 7)]
check(L.should_wake(cheap, None, quiet, now)[0], None, "at the $0.022 target: quiet")

text = L.work_order("why", {"cur": 0.04, "best": 0.03}, worse, ("abc123", "x", "Annotate fix"))
check(all(s in text for s in ("$0.040", "rule:a", "abc123", "ONE Sonnet worker", "$0.022/clue")), True,
      "the work order carries the rows, top cause, last commit and the instruction")

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
