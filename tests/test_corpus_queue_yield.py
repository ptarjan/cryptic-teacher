#!/usr/bin/env python3
# corpus_queue.yield_collapse: the last 100 scans with under 5 puzzles are a
# collapse; a healthy window, a short one, or other log lines are not.
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import corpus_queue as q

def log(counts):
    out = []
    for i, n in enumerate(counts):
        out.append(f"06:00:{i % 60:02d} scanned GaleTimes1957UKEnglish/1957-01-{i:03d}: {n} puzzle(s)")
        out.append("06:00:00 read x: nothing filed")
    return out

assert q.yield_collapse(log([0] * 100)) == ("GaleTimes1957UKEnglish/1957-01-000", "GaleTimes1957UKEnglish/1957-01-099", 0, 100)
assert q.yield_collapse(log([0] * 99)) is None, "too few scans"
assert q.yield_collapse(log([1] * 4 + [0] * 96))[2] == 4, "4 in 100 is a collapse"
assert q.yield_collapse(log([1] * 5 + [0] * 95)) is None, "5 in 100 is not"
assert q.yield_collapse(log([1] * 50 + [0] * 100))[3] == 100, "only the last 100 count"
assert q.yield_collapse(log([0] * 100) + log([1] * 100)) is None, "recovered"
assert q.yield_collapse(["garbage"]) is None
print("ok")
