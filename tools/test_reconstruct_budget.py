#!/usr/bin/env python3
"""reconstruct_grid's node budget covers every path, and its pruning is sound.

Run directly: python3 tools/test_reconstruct_budget.py
"""
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

import reconstruct_grid as R
from fetch_puzzle import read_puzzle_file, resolve_puzzle

fails = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f" {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


# 1. A list with many unknown lengths used to nest in_run/branch_down far past
#    the cap, because only column() counted. The cap now bounds every path.
spec = [(None, "across", None)] * 16 + [(None, "down", None)] * 16
t = time.time()
found, info = R.reconstruct(spec, cols=15, rows=15, max_nodes=30_000, min_light=3)
check("budget stops an all-unknown search", info["truncated"] and not found
      and info["steps"] <= 4 * 30_000 + 100
      and info["nodes"] <= 30_001 and time.time() - t < 60,
      f"nodes={info['nodes']} {time.time() - t:.0f}s")

# 2. Linked groups squeeze their unknown members' lengths.
def bounds(across, members, total):
    s = R._Solver(across, [3, 6], None, None, 15, 15, 2, True, 100,
                  groups=[(members, total)], min_light=3)
    return [(s.lmin[i], s.lmax[i]) for i in range(len(across))]


check("a group with one unknown pins it",
      bounds([4, None, 5], [("across", 0), ("across", 1)], 9)[1] == (5, 5))
check("a group of two unknowns is bounded by its total",
      bounds([4, None, None], [("across", 0), ("across", 1), ("across", 2)], 15)[1:] == [(3, 8), (3, 8)])

# 3. The pruning (tail numbering, per-run tail check, length bounds, the
#    Cyclops caps) never throws out the grid a filed puzzle has.
for pid in ("cyclops-278", "cyclops-280"):
    puz = read_puzzle_file(resolve_puzzle(pid))
    want = R.grid_of(puz)
    got, info = R.reconstruct(R.lights_of(puz), cols=15, rows=15, max_nodes=400_000,
                              min_light=3, no_square=True, min_row_white=3,
                              max_black_run=9)
    check(f"{pid} still rebuilds", want in got, f"found {len(got)} truncated={info['truncated']}")

sys.exit(1 if fails else 0)
