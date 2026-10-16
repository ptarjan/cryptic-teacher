#!/usr/bin/env python3
"""privateeye_wayback.renumber_to_grid: a clue number read one off is put
right against the scan's grid; a bigger slip or a still-unfitting list is left."""
import privateeye_wayback as pw
import reconstruct_grid as rg

grid = ["...#...", ".#.#.#.", ".......", ".#.#.#.", ".......", ".#.#.#.", "..#...."]
lights = rg.lights_from_grid(grid)
def lists():
    a = [[n, s, "plain"] for n, d, s in lights if d == "across"]
    dn = [[n, s, "plain"] for n, d, s in lights if d == "down"]
    return a, dn
a, dn = lists()
a[1][0] += 1  # read one off
assert pw.renumber_to_grid(grid, a, dn), "one-off number not repaired"
assert [x[0] for x in a] == [n for n, d, s in lights if d == "across"]
a, dn = lists(); before = a[1][0]; a[1][0] += 2; a[1][1] += 1
assert not pw.renumber_to_grid(grid, a, dn) and a[1][0] == before + 2
print("ok")
