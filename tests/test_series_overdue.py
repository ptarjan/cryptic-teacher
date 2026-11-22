#!/usr/bin/env python3
# Does the overdue-series alarm learn weekdays, spare recent days, and name a stopped paper (tools/series_overdue.py)?
#
#     python3 tests/test_series_overdue.py
import os
import sys
from datetime import date, timedelta
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # puts tools/ on sys.path
import series_overdue as S

fails = 0


def check(got, want, what):
    global fails
    if got != want:
        fails += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


today = date(2026, 11, 21)  # a Saturday
year = [today - timedelta(n) for n in range(1, 400)]
mon_sat = {d for d in year if d.weekday() < 6}

check(S.expected_weekdays(mon_sat, today), {0, 1, 2, 3, 4, 5}, "daily Mon-Sat paper")
check(S.find_gaps(mon_sat, today, 2), {}, "no gap on a healthy paper")

hole = mon_sat - {today - timedelta(5)}  # Monday 11-16
check(list(S.find_gaps(hole, today, 2)), [":2026-11-16"], "one scattered hole")
check(S.find_gaps(hole - {today - timedelta(1)}, today, 2).keys() == {":2026-11-16"}, True, "day inside grace is spared")

stopped = {d for d in mon_sat if d <= date(2026, 10, 31)}
check(list(S.find_gaps(stopped, today, 2)), ["@2026-10-31"], "stopped paper is one gap keyed by last seen")

dead = {d for d in mon_sat if d <= date(2026, 6, 1)}
check(S.find_gaps(dead, today, 2), {}, "long-dead series ignored")

monthly = {date(2026, m, 1) for m in range(1, 12)}
check(S.find_gaps(monthly, today, 2), {}, "monthly paper on time")
check(list(S.find_gaps(monthly, date(2026, 12, 21), 2)), ["@2026-11-01"], "monthly paper overdue")

# grace is learned from observed lags, never below the default, capped
check(S.grace_for([]), S.DEFAULT_GRACE, "default grace")
check(S.grace_for([5] * 10), 5, "learned grace")
check(S.grace_for([99] * 10), S.MAX_GRACE, "capped grace")

# observe: first run seeds, second records lag
state = {}
S.observe(state, {"x": {today - timedelta(1)}}, today)
check(state["lags"], {}, "first run seeds only")
S.observe(state, {"x": {today - timedelta(1), today - timedelta(4)}}, today)
check(state["lags"], {"x": [4]}, "new date records its lag")

sys.exit(1 if fails else 0)
