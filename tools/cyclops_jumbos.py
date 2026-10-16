"""Cyclops jumbos with a preamble: unclued lights and a perimeter ring.

Two kinds of Cyclops puzzle print a caption the clue list does not carry
(tools/data/cyclops_jumbos.json holds each caption, read off the page image
and checked against the issue's archive.org OCR text):

  "unclued": lights the preamble says have no clue (No 199's
      1/29/40/78/58/60, "See Preamble"). The listed entries leave the clue list
      and their squares, in the order listed, become one `unclued` light.
  "ring": the outer ring of squares, an unclued light running clockwise from
      the top left square (Nos 205, 226, 277). The scan's grid prints the
      ring's four edges as lights the clue list never numbers, so
      ring_masked() turns every ring square no clued light crosses black
      before the grid is matched to the clue list. "keep" names the edges
      that are clued (No 205's top row is 1 across, "see preamble").
"""

import json
from pathlib import Path

DATA = Path(__file__).parent / "data" / "cyclops_jumbos.json"


def config(num):
    """The jumbo's caption data for Cyclops `num`, or None."""
    return json.loads(DATA.read_text()).get(str(num))


def ring_cells(size):
    """The ring's squares clockwise from the top left, (x, y)."""
    last = size - 1
    return ([(x, 0) for x in range(size)] + [(last, y) for y in range(1, size)]
            + [(x, last) for x in range(last - 1, -1, -1)] + [(0, y) for y in range(last - 1, 0, -1)])


def ring_masked(grid, keep=()):
    """`grid` with each ring square black unless a light crosses it at right
    angles to its edge, or it lies on an edge in `keep` ("top", "bottom",
    "left", "right")."""
    size = len(grid)
    last = size - 1
    rows = [list(r) for r in grid]
    white = lambda x, y: 0 <= x < size and 0 <= y < size and grid[y][x] == "."
    kept = set()
    for edge, cells in (("top", [(x, 0) for x in range(size)]), ("bottom", [(x, last) for x in range(size)]),
                        ("left", [(0, y) for y in range(size)]), ("right", [(last, y) for y in range(size)])):
        if edge in keep:
            kept.update(cells)
    for x, y in ring_cells(size):
        if (x, y) in kept or not white(x, y):
            continue
        if y in (0, last) and x not in (0, last):
            crossed = white(x, 1 if y == 0 else last - 1)
        elif x in (0, last) and y not in (0, last):
            crossed = white(1 if x == 0 else last - 1, y)
        else:
            crossed = False
        if not crossed:
            rows[y][x] = "#"
    return ["".join(r) for r in rows]


def cells_of(entry):
    x, y = entry["position"]["x"], entry["position"]["y"]
    dx, dy = (1, 0) if entry["direction"] == "across" else (0, 1)
    return [{"x": x + dx * i, "y": y + dy * i} for i in range(entry["length"])]


def apply(puzzle, cfg):
    """Carry the preamble into `puzzle`, make its unclued light(s), or return
    (None, why)."""
    puzzle["preamble"] = cfg["preamble"]
    unclued = []
    if "unclued" in cfg:
        by_id = {f"{e['number']}-{e['direction']}": e for e in puzzle["entries"]}
        names = cfg["unclued"]["lights"]
        if any(n not in by_id for n in names):
            return None, f"the unclued lights {names} are not all in the grid"
        cells = [c for n in names for c in cells_of(by_id[n])]
        gone = set(names)
        puzzle["entries"] = [e for e in puzzle["entries"] if f"{e['number']}-{e['direction']}" not in gone]
        unclued.append({"cells": cells, "enumeration": cfg["unclued"]["enumeration"]})
    if "ring" in cfg:
        d = puzzle["dimensions"]
        ring = [{"x": x, "y": y} for x, y in ring_cells(d["cols"])]
        light = {"cells": ring}
        enum = cfg["ring"].get("enumeration")
        if enum:
            if sum(int(n) for n in enum.split(",")) != len(ring):
                return None, f"the ring's counts {enum} do not make its {len(ring)} squares"
            light["enumeration"] = enum
        unclued.append(light)
    puzzle["unclued"] = unclued
    return puzzle, None
