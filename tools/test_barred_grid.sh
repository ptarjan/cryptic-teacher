#!/bin/bash
# Does tools/barred_grid.py rebuild a barred grid's bars from its numbered
# answers, and only when they pin it down?
#
#     bash tools/test_barred_grid.sh
#
# The bars it returns are published as the grid, so the check is a round trip:
# a hand-built 5x5 barred grid, numbered by reconstruct_grid.light_cells (the
# one numbering function), its answers handed to the solver, and the bars that
# come back must be the bars that went in. A wrong answer must find no grid
# rather than some other one.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import barred_grid as bg
import reconstruct_grid as rg

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
print("count", len(found))
rows, bars = bg.layout(entries, found[0], size=5)
print("bars", "|".join(bars) == "|".join(BARS))
print("letters", "|".join(rows) == "|".join(LETTERS))
print("barred", rg.barred(BARS), rg.barred(("..#", "...", "#..")))
wrong = [dict(e, answer=e["answer"][:-1] + "Z") if (e["number"], e["direction"]) == (1, "across")
         else e for e in entries]
print("wrong", len(bg.solve(wrong, size=5)))
print("short", bg.solve(entries + [{"number": 9, "direction": "across", "answer": "A"}], size=5))
PY
)
check "the answers pin down one grid" "count 1" "$(grep '^count' <<<"$out")"
check "its bars are the ones it was numbered from" "bars True" "$(grep '^bars' <<<"$out")"
check "every cell holds its letter" "letters True" "$(grep '^letters' <<<"$out")"
check "a grid with bars is barred, one with blocks is not" "barred True False" "$(grep '^barred' <<<"$out")"
check "a wrong answer fits no grid" "wrong 0" "$(grep '^wrong' <<<"$out")"
check "a one-letter light is refused" "short None" "$(grep '^short' <<<"$out")"
exit $fails
