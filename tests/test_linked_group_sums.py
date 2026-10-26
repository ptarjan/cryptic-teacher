#!/usr/bin/env python3
# Does the grid search use a linked answer's printed total?
#
#     python3 tests/test_linked_group_sums.py
#
# A linked clue ("8 and 1 down (5,6,3,5,1,3,5)") counts words, not lights, so
# each light's length is unknown but their sum (28) is printed, and the "See 8"
# continuations name the lights. reconstruct_grid takes that as `groups`: a
# grid whose group lights add to the total is found, one that cannot is
# refused, and the group prunes grids the free lengths alone would allow.
# Then tools/fetch_nation.py's linked_groups on The Nation No 1249 (when its
# page is held): 8-down and 1-down, 28 letters, a grid found only with the sum.
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sys
sys.path.insert(0, "tools")
import reconstruct_grid as rg

fails = []
grid = ("....#....",
        ".#.#.#.#.",
        ".........",
        ".#.#.#.#.",
        "....#....",
        ".#.#.#.#.",
        ".........",
        ".#.#.#.#.",
        "....#....")
lights = rg.lights_from_grid(list(grid))
spec = [(n, d, length) for n, d, length in lights]
assert rg.unique_grid(spec, cols=9, rows=9)[0] == list(grid), "the plain spec rebuilds"
# Free two across lights' lengths, the first and the last of the list.
across = [i for i, (_, d, _) in enumerate(spec) if d == "across"]
a0, a1 = across[0], across[-1]
total = spec[a0][2] + spec[a1][2]
free = [(n, d, None if i in (a0, a1) else length) for i, (n, d, length) in enumerate(spec)]
idx = (0, len(across) - 1)
groups = [([("across", idx[0]), ("across", idx[1])], total)]

found, info = rg.reconstruct(free, cols=9, rows=9, limit=50, groups=groups)
if [list(g) for g in found] != [list(grid)]:
    fails.append(f"with the group total {total}: {len(found)} grids, wanted the one")
found, info = rg.reconstruct(free, cols=9, rows=9, limit=50,
                             groups=[(groups[0][0], total + 1)])
if found:
    fails.append(f"a total no grid can make ({total + 1}) still found {len(found)} grids")
if info["truncated"]:
    fails.append("the impossible total ran out of budget instead of finishing")
loose, _ = rg.reconstruct(free, cols=9, rows=9, limit=50)
tight, _ = rg.reconstruct(free, cols=9, rows=9, limit=50, groups=groups)
if not set(tight) <= set(loose):
    fails.append("the group let in a grid the free lengths did not")
try:
    rg.reconstruct(free, cols=9, rows=9, groups=groups + groups)
    fails.append("a light in two groups was accepted")
except ValueError:
    pass

import fetch_nation as f
import light_spec
pages = [p for p in f.PAGES.glob("*.html") if f.meta(p.read_text())["number"] == 1249] \
    if f.PAGES.is_dir() else []
if pages:
    page = pages[0].read_text()
    read, why = f.read_page(page, f.original_dates())
    m, _, a, d, got = read
    want = [([("down", 7), ("down", 0)], 28)]
    if got != want:
        fails.append(f"1249's groups read {got}, wanted {want}")
    puzzle, why = f.build(page, "https://example.invalid/1249", f.original_dates())
    if puzzle is None:
        fails.append(f"1249 did not rebuild with its group sum: {why}")
    else:
        e = {(x["number"], x["direction"]): x for x in puzzle["entries"]}
        if e[(8, "down")]["length"] + e[(1, "down")]["length"] != 28:
            fails.append("1249's 8-down and 1-down do not add to 28")
else:
    print("skip: The Nation No 1249's page is not held here")

for fail in fails:
    print("FAIL:", fail)
print("ok" if not fails else f"{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
