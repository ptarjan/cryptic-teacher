#!/usr/bin/env python3
"""Pick a rush run's A/B arm (model, effort) at random, seeded by the puzzle id.

    python3 tools/ab_arm.py sundaytimes-4612      # prints "fable high"

Paul 11-17: "You can use all these spends as ab tests to see if they are worth it."
While the burn rushes, each run is one of ARMS. 11-18: Paul asked "Why opus high effort
and not medium?" and no opus/medium rush run had been logged, so the arms are Opus at both
efforts (the Fable arms lost: fable/high $1.06 a puzzle vs opus/high $0.38). The same id always draws the same arm (reproducible), and
ids spread evenly over arms in the long run. tools/ab_report.py reads the result.

11-19: over a day of rush runs (about 1,080 per arm), opus/medium cost $0.31 a puzzle
against $0.36 for opus/high, and $0.40 against $0.44 per puzzle that passed its first
check, though it passed that check less often (77% vs 81%). Failures are redone inside
the burn, so medium is cheaper per finished puzzle: the burn now runs opus/medium only.
"""
import hashlib
import sys

ARMS = [("opus", "medium")]


def pick(puzzle_id, arms=None):
    arms = arms or ARMS
    h = hashlib.sha256(str(puzzle_id).encode()).digest()
    return arms[int.from_bytes(h[:8], "big") % len(arms)]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: ab_arm.py <puzzle id>")
    print(*pick(sys.argv[1]))
