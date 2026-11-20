#!/usr/bin/env python3
# Does the daily burn review read the burn log, rank width loss against retry loss, and trip only on a real change?
#
#     python3 tests/test_burn_review.py
#
# A fake burn log and fake rows in, segments / ranked list / wake reasons out (tools/burn_review.py).
import datetime
import json
import os
import pathlib
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # puts tools/ on sys.path
import burn_review as B

fails = 0


def check(got, want, what):
    global fails
    if got != want:
        fails += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


LOG = """23:50 ── 1 at once (held by pressure) · 20 done/h · 0 no-change/h (0%) · 100 queued · rushing, 9 of 25 manual resets left
23:51 ✓ x-1 wrote 30 hints
00:10 ── 10 at once (memory: 3 GB free · rushing) · 100 done/h · 0 no-change/h (0%) · 100 queued · rushing, 8 of 25 manual resets left
00:20 ── waiting: nothing may start right now · usage pace
00:30 ── idle: nothing queued
"""
mtime = datetime.datetime(2026, 11, 20, 0, 31, tzinfo=B.ABT)
lines = B.dated_lines(LOG, mtime)
check([ts.date().isoformat() for ts, _ in lines], ["2026-11-19", "2026-11-19", "2026-11-20", "2026-11-20", "2026-11-20"],
      "a clock that wraps past midnight is the next day")
start = datetime.datetime(2026, 11, 19, 12, 0, tzinfo=B.ABT)
end = datetime.datetime(2026, 11, 20, 1, 0, tzinfo=B.ABT)
segs = B.segments(lines, start, end)
check([(s["width"], s["cap"]) for s in segs], [(1, "pressure"), (10, "memory"), (0, "quota"), (0, "idle")], "width and cap per status line")
check(round(segs[0]["hours"], 3), round(20 / 60, 3), "a status line holds until the next one")
check(round(segs[3]["hours"], 3), round(B.GAP_CAP_MIN / 60, 3), "a status line holds at most GAP_CAP_MIN")
check(B.last_resets(lines, start), 8, "resets left from the last status line")
log = B.summarise_log(segs)
check(log["width_hours"]["1"], round(20 / 60, 2), "hours at width 1")
check(log["width1_cap_hours"], {"pressure": round(20 / 60, 2)}, "width-1 hours split by cap")

fake = {"width1_cap_hours": {"memory": 2.0, "pressure": 1.0}, "free_rate": 100.0, "width1_rate": 20.0}
w = B.width_losses(fake)
check([(i["key"], i["puzzles_lost"]) for i in w], [("width1:memory", 160.0), ("width1:pressure", 80.0)], "width loss = hours x rate gap")
causes = [{"key": "rule:a", "label": "a", "sessions": 5, "post_fail_usd": 8.0},
          {"key": "rule:muted", "label": "m", "sessions": 9, "post_fail_usd": 50.0}]
items, dropped = B.retry_losses(causes, 0.4, {"rule:muted": {}})
check([(i["key"], i["puzzles_lost"]) for i in items], [("rule:a", 20.0)], "retry loss = post-fail $ / $ per puzzle")
check(dropped, ["rule:muted"], "a no-lever cause is dropped from the actionable list")
check([i["key"] for i in B.rank(w + items)], ["width1:memory", "width1:pressure", "rule:a"], "one ranked list")

ok = {"status": "ok", "top_key": "width1:memory", "usd_per_clue": 0.010, "width1_hours": 2.0}
check(B.trips(dict(ok), dict(ok)), [], "an unchanged day is quiet")
check(len(B.trips(dict(ok, top_key="rule:a"), ok)), 1, "a new top item trips")
check(len(B.trips(dict(ok, usd_per_clue=0.0126), ok)), 1, "$/clue up over 25% trips")
check(B.trips(dict(ok, usd_per_clue=0.0124), ok), [], "$/clue up 24% does not")
check(len(B.trips(dict(ok, width1_hours=6.5), ok)), 1, "over 6h at width 1 trips")
check(len(B.trips({"status": "no-work"}, ok)), 1, "no-work trips")
check(len(B.trips({"status": "error", "error": "boom"}, None)), 1, "error trips with no previous row")
check(B.trips(dict(ok, top_key="rule:a"), None), [], "the first row has nothing to diff against")
d = B.digest(dict(ok, date="2026-11-20", puzzles=10, clues=300, usd=3.0, ranked=[{"label": "L", "puzzles_lost": 5}]), ["new top item"])
check("L = 5 puzzles lost/day" in d, True, "the digest names the top ranked item")

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
