#!/usr/bin/env python3
# The pacer projects the bridge's spend to the weekly reset at its mean over a
# week (prereset_plan.bridge_mean), not at the 6-hour rate of a busy morning.
# 2026-11-05: 1.4 pts/h x 140 h exceeded all that was left, so the width was 0.
#
#     python3 tests/test_bridge_mean.py
import _path  # puts tools/ on sys.path
import json
import sys
import tempfile
from pathlib import Path

import prereset_plan as P

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


R = 2.09 / 6.37  # points per run-hour, as in the planner's own cases
peak, mean = 1.4, 0.2
check("the 6h peak over 140h spends it all: need 0", P.paced_need(6, 140, R, peak) == 0)
need = P.paced_need(6, 140, R, mean)
check(f"the weekly mean leaves a real need ({need})", need is not None and need >= 1)

check("the burn's cwd as its records name it", P.same_tree(
    "/Users/pt/.cryptic-teacher/prereset_backfill", "/data/home/.cryptic-teacher/prereset_backfill"))
check("another tree is not the burn", not P.same_tree(
    "/Users/pt/github/cryptic-teacher", "/data/home/.cryptic-teacher/prereset_backfill"))
check("no cwd is not the burn", not P.same_tree(None, "/burn"))

now = 1_000_000.0
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    path = home / P.BRIDGE_MEAN_FILE
    check("no file: the short rate stands", P.bridge_mean(home, now, peak, spawn=False) == peak)
    path.write_text("garbage")
    check("unreadable file: the short rate stands", P.bridge_mean(home, now, peak, spawn=False) == peak)
    path.write_text(json.dumps({"at": now - 3600, "rate": mean}))
    check("fresh file: its mean", P.bridge_mean(home, now, peak, spawn=False) == mean)
    path.write_text(json.dumps({"at": now - 3 * P.BRIDGE_MEAN_TTL_S, "rate": mean}))
    check("stale file still serves", P.bridge_mean(home, now, peak, spawn=False) == mean)
    path.write_text(json.dumps({"at": now + 99, "rate": mean}))
    check("a file from the future is unread", P.bridge_mean(home, now, peak, spawn=False) == peak)

sys.exit(1 if fails else 0)
