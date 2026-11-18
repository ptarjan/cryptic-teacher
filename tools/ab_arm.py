#!/usr/bin/env python3
"""Pick a rush run's A/B arm (model, effort) at random, seeded by the puzzle id.

    python3 tools/ab_arm.py sundaytimes-4612      # prints "fable high"

Paul 11-17: "You can use all these spends as ab tests to see if they are worth it."
While the burn rushes, each run is one of ARMS; opus/medium is the paced baseline
and is not an arm here. The same id always draws the same arm (reproducible), and
ids spread evenly over arms in the long run. tools/ab_report.py reads the result.
"""
import hashlib
import sys

ARMS = [("fable", "medium"), ("fable", "high"), ("fable", "max"), ("opus", "high")]


def pick(puzzle_id, arms=None):
    arms = arms or ARMS
    h = hashlib.sha256(str(puzzle_id).encode()).digest()
    return arms[int.from_bytes(h[:8], "big") % len(arms)]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: ab_arm.py <puzzle id>")
    print(*pick(sys.argv[1]))
