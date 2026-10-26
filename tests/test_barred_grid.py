#!/usr/bin/env python3
# Does tools/barred_grid.py rebuild a barred grid's bars from its numbered
# answers, and only when they pin it down?
#
#     python3 tests/test_barred_grid.py
#
# The bars it returns are published as the grid, so the check is a round trip:
# a hand-built 5x5 barred grid, numbered by reconstruct_grid.light_cells (the
# one numbering function), its answers handed to the solver, and the bars that
# come back must be the bars that went in. A wrong answer must find no grid
# rather than some other one.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import barred_grid as bg
import reconstruct_grid as rg

fails = 0


def check(what, got, want):
    global fails
    if got == want:
        print(f"ok   {what}")
    else:
        print(f"FAIL {what}: expected [{want}], got [{got}]")
        fails += 1


LETTERS = ("ABCDE", "FGHIJ", "KLMNO", "PQRST", "UVWXY")
BARS = ("..r..",
        "b...b",
        ".r.r.",
        "b...b",
        "..r..")
lights = rg.light_cells(BARS)
entries = [{"number": n, "direction": d,
            "answer": "".join(LETTERS[y][x] for y, x in cells)}
           for (n, d), cells in lights.items()]
found = bg.solve(entries, size=5)
rows, bars = bg.layout(entries, found[0], size=5)
wrong = [dict(e, answer=e["answer"][:-1] + "Z") if (e["number"], e["direction"]) == (1, "across")
         else e for e in entries]
# Candidates: 1 across could be its letters or two wrong spellings; the
# crossings keep the right one. Spellings of different lengths are refused.
cand = [dict(e, answers=[e["answer"][::-1], e["answer"], e["answer"][:-1] + "Z"])
        if (e["number"], e["direction"]) == (1, "across") else e for e in entries]
fills = bg.solve_words(cand, size=5)
mixed = [dict(e, answers=[e["answer"], e["answer"] + "Z"]) if e is entries[0] else e for e in entries]
# A grid wider than it is deep (Azed's 13x11): (cols, rows) round-trips, and
# the square that holds as many cells finds nothing.
WIDE = ("ABCDEF", "GHIJKL", "MNOPQR", "STUVWX")
WBARS = ("..r...", "b....b", "...r..", "......")
wide = [{"number": n, "direction": d, "answer": "".join(WIDE[y][x] for y, x in cells)}
        for (n, d), cells in rg.light_cells(WBARS).items()]
wfound = bg.solve(wide, size=(6, 4))
# An unclued, unnumbered light (Listener No 3985's thematic entries): one
# light leaves the list for the pool, the rest renumber in order of their
# start squares, and the search puts it back where it was.
cells = rg.light_cells(WBARS)
starts = {}
for (n, d), cs in cells.items():
    starts.setdefault(cs[0], []).append((n, d))
alone = next(k for k, cs in sorted(cells.items()) if len(starts[cs[0]]) == 1
             and any(c[0] != cs[0][0] or c[1] != cs[0][1] for c in cs))
renum = {n: i + 1 for i, n in enumerate(sorted({n for (n, d) in cells if (n, d) != alone}))}
clued = [dict(e, number=renum[e["number"]]) for e in wide
         if (e["number"], e["direction"]) != alone]
word = next(e["answer"] for e in wide if (e["number"], e["direction"]) == alone)
ufound = bg.solve_unclued(clued, [word], size=(6, 4), cap=3)
y, x = cells[alone][0]

check("the answers pin down one grid", len(found), 1)
check("its bars are the ones it was numbered from", "|".join(bars), "|".join(BARS))
check("every cell holds its letter", "|".join(rows), "|".join(LETTERS))
check("a grid with bars is barred, one with blocks is not",
      (rg.barred(BARS), rg.barred(("..#", "...", "#.."))), (True, False))
check("a wrong answer fits no grid", len(bg.solve(wrong, size=5)), 0)
check("a one-letter light is refused",
      bg.solve(entries + [{"number": 9, "direction": "across", "answer": "A"}], size=5), None)
check("a (cols, rows) grid round-trips, and its transpose fits nothing",
      (len(wfound), "|".join(bg.layout(wide, wfound[0], size=(6, 4))[1]) == "|".join(WBARS),
       len(bg.solve(wide, size=(4, 6)))), (1, True, 0))
check("a light's candidates: the crossings keep the one that fits",
      (len(fills), fills[0][1][(1, "across")] == entries[0]["answer"] if fills else None),
      (1, True))
check("candidates of different lengths are refused", bg.solve_words(mixed, size=5), None)
check("an unnumbered unclued light goes back where it was",
      (len(ufound), ufound[0][2] == [(word, y * 6 + x, alone[1])]), (1, True))
sys.exit(fails)
