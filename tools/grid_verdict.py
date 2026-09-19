#!/usr/bin/env python3
"""Decide, with no model in the loop, whether a reconstructed grid is real.

The reconstructor answers "which grids would print this clue list". When the
clue list is intact that set is usually one grid and it is the right one.
When OCR has eaten a clue the set is not empty — it is a dozen grids that are
all wrong in the same way, because a light list missing a light describes a
LOOSER puzzle, and a looser puzzle has more solutions. Telling those apart is
the judgement this module makes, so nobody pays a model to look at a fill and
say "that isn't a crossword".

EVERY THRESHOLD HERE WAS MEASURED, and the measurement is in THRESHOLDS
beside it. The population is the 15,592 15x15 grids in puzzles/ — grids drawn
by other people and published in newspapers — and each rule is quoted with
the share of THOSE it would throw away, which is the only honest way to state
what a reject rule costs. A rule with no such number does not belong here.

THREE PROPOSED RULES WERE MEASURED AND DISCARDED. They are named here because
each is individually plausible, each will be proposed again, and the corpus
says all three are false:

  * "Across and down cell totals must be equal, since every white cell is
    counted once by each direction." FALSE for blocked British grids: it
    holds for only 4,774 of 15,592 (30.6%). A cell that is UNCHECKED lies in
    a light in one direction and in no light at all in the other, so it is
    counted once, not twice. The true identity — across_total + down_total
    = whites + checked_cells — holds for 15,590 of 15,592, but `checked` is
    not knowable from a clue list, so it cannot be used as a pre-filter.
    What survives is the MEASURED RANGE of the total, below.
  * "Checked-cell fraction separates good grids from damaged fills." It does
    not. The damaged fills measured 33%, which is the 32nd percentile of
    real published grids (range 29.3%-49.7%, median 36.1%). Rejecting below
    35% would throw away 32.09% of the corpus. Dropped; still REPORTED as a
    metric, because it describes the grid even though it cannot judge it.
  * "A published puzzle always has a 1-Across." 4,510 of 15,592 (28.93%)
    have none — a grid whose top-left cell starts only a down light is
    ordinary, not impossible. Dropped entirely.

WHAT SURVIVED, with its cost on the corpus:

  BEFORE THE SEARCH (screen_spec), pure arithmetic on the light list, which
  is the cheap place to throw work away:
    * fewer than 24 lights           costs 0.10%   — the OCR-damage gate
    * a length outside 2..15         costs 0
    * total outside 170..256 cells   costs 0.00%   — observed 176..250
    * |across - down| above 24       costs 0.00%   — observed max 24
  and one rule proposed as a reject and MEASURED DOWN to a warning:
    * every length even and <= 10    costs 2.636%  — 411 real published 15x15s
      look exactly like that. It was offered on the grounds that a real clue
      list "always prints a light of 12-15"; the corpus says otherwise 411
      times. It is still a good smell, so it is reported as a warning and the
      search still runs. On the one control puzzle it fires for, the search
      already returns a shortlist rather than a false unique, so rejecting on
      it bought nothing and would have cost 2.6% of the corpus.
  The light-count gate is the one that matters and the one that is cheapest:
  a 15x15 prints at least 24 lights and the known-good set prints 26-32, so
  below 24 whole clues were lost and no amount of clean numbering makes the
  rest reconstructable.

  AFTER THE SEARCH (verdict), three weak signals combined, because each alone
  is too noisy to reject on:
    * more than 88 black squares     costs 0.34%   (observed 54..97)
    * 3+ doubly-unchecked runs       costs 0.38%   (99.9% of grids have 0)
    * |across - down| above 12       (observed median 2)
  ANY TWO of those three costs 0.199% of the corpus — 31 grids in 15,592 —
  and that is the bar for calling a fill damaged rather than plausible.

  Separately, FOUR OR MORE FILLS is damage regardless of how they score. A
  real clue list pins its grid; four answers means the search was solving a
  looser puzzle than the one that was printed, which is precisely what a
  missing clue makes. The fill set's `agreement` is reported with it, since
  a dozen fills agreeing everywhere but one corner is one underconstrained
  corner rather than a dozen puzzles.

So the verdict separates SHORTLIST (two or three real-looking grids, a human
picks one) from DAMAGED-LIGHT-LIST (the OCR ate clues; none of these is
right, do not spend a human on it). Collapsing those into "needs checking"
is what makes acquiring a book expensive.
"""
from __future__ import annotations

MIN_LIGHTS = 24               # a 15x15 prints at least this many
GOOD_LIGHTS = (26, 32)        # what the ten vol-5 controls print
CELL_TOTAL_RANGE = (170, 256)  # across+down; corpus runs 176..250
MAX_TOTAL_SKEW = 24           # |across-down|; corpus max is exactly 24
FLAG_SKEW = 12                # soft flag; corpus median is 2
FLAG_BLACKS = 88              # soft flag; 99th percentile
FLAG_DOUBLY = 3               # soft flag; 99.9th percentile is 0
FLAGS_TO_CONDEMN = 2          # any two of the three: 0.199% of the corpus
MAX_PLAUSIBLE_FILLS = 3       # four or more is an underconstrained search

THRESHOLDS = {
    "MIN_LIGHTS": "corpus 15x15s print 20-46 lights (median 29); below 24 costs 0.10%",
    "CELL_TOTAL_RANGE": "across+down totals run 176-250 over 15,592 grids; 0.00% outside 170-256",
    "MAX_TOTAL_SKEW": "|across-down| never exceeds 24 in the corpus (median 2)",
    "FLAG_BLACKS": "blacks run 54-97, 99th percentile 88; flagging above it costs 0.34%",
    "FLAG_DOUBLY": "99.9% of corpus grids have zero doubly-unchecked runs; 3+ costs 0.38%",
    "FLAGS_TO_CONDEMN": "any two of the three flags together cost 0.199% (31 of 15,592)",
    "MAX_PLAUSIBLE_FILLS": "a clue list that admits 4+ grids is looser than the printed puzzle",
}

DISCARDED = {
    "across == down cell totals": "true for only 30.6% of the corpus; unchecked "
        "cells are counted by one direction, not both",
    "checked-cell fraction": "damaged fills measured 33%, the 32nd percentile of "
        "real grids; a 35% floor would reject 32.09% of the corpus",
    "must have a 1-Across": "28.93% of real published 15x15s have none",
}


# ---------------------------------------------------------------- spec stage

def cell_totals(across, down):
    """(across_total, down_total, complete).

    NOT equal to each other — see the module docstring. Their SUM is what
    carries information, because it equals whites + checked_cells and so is
    tightly bounded for any 15x15 whatever its style.
    """
    a = [lg[1] for lg in across]
    d = [lg[1] for lg in down]
    complete = bool(a) and bool(d) and all(x is not None for x in a + d)
    return sum(x for x in a if x), sum(x for x in d if x), complete


def skew_suspects(across, down, delta):
    """Which enumerations could account for an out-of-range total.

    The delta is exact, so the suspects are exact: a light whose length is
    wrong by the delta would bring the total back into range, and a digit OCR
    turned into another digit is nearly always one of those. Naming them is
    the point — "the totals are off" sends a human to the whole clue list,
    "across 14 reads 7 and lands in range at 4" sends them to one line.
    """
    out = []
    for direction, lights in (("across", across), ("down", down)):
        for lg in lights:
            number, length = lg[0], lg[1]
            if length is None:
                continue
            for fixed in (length - delta, length + delta):
                if 2 <= fixed <= 15 and fixed != length:
                    out.append({"direction": direction, "number": number,
                                "reads": length, "lands_in_range_at": fixed})
    return out


def screen_spec(across, down):
    """Reasons this light list cannot be a published 15x15. Empty means run
    the search."""
    lights = across + down
    lengths = [lg[1] for lg in lights if lg[1] is not None]
    reasons = []

    if len(lights) < MIN_LIGHTS:
        reasons.append(
            f"only {len(lights)} lights recovered; a 15x15 prints at least "
            f"{MIN_LIGHTS} and the known-good set prints {GOOD_LIGHTS[0]}-"
            f"{GOOD_LIGHTS[1]}, so whole clues were lost to OCR and no amount "
            f"of clean numbering makes the rest reconstructable")

    bad = [(lg[0], lg[1]) for lg in lights
           if lg[1] is not None and not 2 <= lg[1] <= 15]
    if bad:
        reasons.append("impossible light length(s) for a 15x15: "
                       + ", ".join(f"{n}->{l}" for n, l in bad))

    a_total, d_total, complete = cell_totals(across, down)
    if complete:
        total = a_total + d_total
        lo, hi = CELL_TOTAL_RANGE
        if not lo <= total <= hi:
            delta = lo - total if total < lo else total - hi
            named = ", ".join(
                f"{s['direction']} {s['number']} reads {s['reads']}, lands in "
                f"range at {s['lands_in_range_at']}"
                for s in skew_suspects(across, down, delta)[:6])
            reasons.append(
                f"across lengths total {a_total} cells and down {d_total}, "
                f"summing to {total}; every 15x15 in the corpus sums to "
                f"176-250, so at least one enumeration is mis-read"
                + (f" — candidates: {named}" if named else ""))
        if abs(a_total - d_total) > MAX_TOTAL_SKEW:
            reasons.append(
                f"across lengths total {a_total} cells and down {d_total}, a "
                f"gap of {abs(a_total - d_total)}; no grid in the corpus "
                f"exceeds {MAX_TOTAL_SKEW}, so one direction's list is "
                f"missing a light or has a mis-read enumeration")
    return reasons


def spec_warnings(across, down):
    """Smells worth printing that are NOT worth rejecting on.

    The line between this and screen_spec is a measured one: a rule earns a
    reject only if throwing away that share of the corpus is worth it, and
    the all-even rule is not — 411 of 15,592 published 15x15s (2.636%) have
    nothing but even light lengths capped at 10. Reported so whoever reads
    the report knows which puzzles to look at first.
    """
    lengths = [lg[1] for lg in across + down if lg[1] is not None]
    out = []
    if lengths and all(l % 2 == 0 for l in lengths) and max(lengths) <= 10:
        out.append(
            f"every light length is even and none exceeds {max(lengths)}, the "
            f"shape a parse artefact makes — though 2.636% of published 15x15s "
            f"look like this too, so it is a reason to look, not to reject")
    return out


# ---------------------------------------------------------------- grid stage

def grid_metrics(grid):
    """Everything the verdict weighs, as numbers, so a report shows the
    measurement beside the judgement instead of only the judgement.

    checked_fraction and has_1_across are measured and reported but NOT
    judged — see DISCARDED. They describe a grid; they cannot condemn one.
    """
    rows, cols = len(grid), len(grid[0])
    white = [[c == "." for c in row] for row in grid]
    cells = [(x, y) for y in range(rows) for x in range(cols) if white[y][x]]
    blacks = rows * cols - len(cells)

    def run_through(x, y, dx, dy):
        n = -1
        for sx, sy in ((dx, dy), (-dx, -dy)):
            cx, cy = x, y
            while 0 <= cx < cols and 0 <= cy < rows and white[cy][cx]:
                n += 1
                cx, cy = cx + sx, cy + sy
        return n + 1

    unchecked = {(x, y) for x, y in cells
                 if run_through(x, y, 1, 0) < 2 or run_through(x, y, 0, 1) < 2}
    doubly = sum(1 for x, y in unchecked
                 if (x + 1, y) in unchecked or (x, y + 1) in unchecked)

    across_total = down_total = 0
    first_across = False
    number = 0
    for y in range(rows):
        for x in range(cols):
            if not white[y][x]:
                continue
            a = (x == 0 or not white[y][x - 1]) and x + 1 < cols and white[y][x + 1]
            d = (y == 0 or not white[y - 1][x]) and y + 1 < rows and white[y + 1][x]
            if not (a or d):
                continue
            number += 1
            if number == 1:
                first_across = a
            if a:
                across_total += run_through(x, y, 1, 0)
            if d:
                down_total += run_through(x, y, 0, 1)
    checked = len(cells) - len(unchecked)
    return {"blacks": blacks,
            "black_fraction": round(blacks / (rows * cols), 3),
            "whites": len(cells),
            "checked_fraction": round(checked / len(cells), 3) if cells else 0.0,
            "doubly_unchecked_runs": doubly,
            "has_1_across": first_across,
            "across_total": across_total,
            "down_total": down_total,
            "skew": abs(across_total - down_total)}


def grid_flags(grid):
    """The three surviving soft signals. Two of them together condemn a fill;
    one on its own is within what published grids do."""
    m = grid_metrics(grid)
    flags = []
    if m["blacks"] > FLAG_BLACKS:
        flags.append(f"{m['blacks']} black squares; the corpus runs 54-97 with "
                     f"only 0.34% above {FLAG_BLACKS}")
    if m["doubly_unchecked_runs"] >= FLAG_DOUBLY:
        flags.append(f"{m['doubly_unchecked_runs']} doubly-unchecked runs; "
                     f"99.9% of published grids have none")
    if m["skew"] > FLAG_SKEW:
        flags.append(f"across and down totals differ by {m['skew']} cells; the "
                     f"corpus median is 2")
    return flags, m


def agreement(grids):
    """The fraction of cells every fill in the set agrees on."""
    if len(grids) < 2:
        return 1.0
    rows, cols = len(grids[0]), len(grids[0][0])
    same = sum(1 for y in range(rows) for x in range(cols)
               if len({g[y][x] for g in grids}) == 1)
    return same / (rows * cols)


def verdict(grids, truncated=False):
    """(status, detail) for a finished search.

    exact-unique         one fill, and it scores like a published grid
    shortlist-of-N       two or three plausible fills; a human picks
    damaged-light-list   fills exist but the OCR ate clues; none is right
    no-solution          nothing fits the list at all
    budget-exhausted     the search ran out before it knew anything
    """
    if truncated:
        return "budget-exhausted", {"reasons": [
            "the search hit its node or wall-clock budget before finishing, so "
            "this says nothing about the puzzle either way"]}
    if not grids:
        return "no-solution", {"reasons": [
            "no 15x15 prints this light list; at least one enumeration, or the "
            "printed order of the clues, is wrong"]}

    scored = [grid_flags(g) for g in grids]
    detail = {"metrics": [m for _, m in scored],
              "flags": [f for f, _ in scored],
              "agreement": round(agreement(grids), 3)}
    condemned = [f for f, _ in scored if len(f) >= FLAGS_TO_CONDEMN]

    if len(grids) > MAX_PLAUSIBLE_FILLS:
        detail["reasons"] = [
            f"{len(grids)} fills satisfy this light list, agreeing on "
            f"{agreement(grids):.0%} of the grid; a printed clue list pins its "
            f"own grid, so a list this loose is one with clues missing rather "
            f"than a puzzle with {len(grids)} answers"]
        return "damaged-light-list", detail
    if len(condemned) == len(grids):
        detail["reasons"] = sorted({r for f in condemned for r in f})
        return "damaged-light-list", detail
    clean = [g for g, (f, _) in zip(grids, scored) if len(f) < FLAGS_TO_CONDEMN]
    if len(clean) == 1 and len(grids) == 1:
        return "exact-unique", detail
    return f"shortlist-of-{len(clean)}", detail
