#!/bin/bash
# Does tools/times_grids.py rebuild the right grid, and admit it when it cannot?
#
#     bash tools/test_times_grids.sh
#
# This module turns a blog post into a GRID that gets published as if The Times
# had printed it, and a wrong grid is not obviously wrong to anyone looking at
# it. Two ways to get that wrong quietly: narrowing a shortlist with the
# answers and keeping a candidate whose crossings disagree, and reporting a
# search that ran out of budget as a puzzle no grid fits — the first ships a
# lie, the second sends someone back to re-read a blog post that was fine.
#
# The fixture is a hand-built 5x5 with a made-up series, so nothing here
# depends on the corpus, on the cache, or on how long a real search takes.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

out=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import reconstruct_grid as rg
import times_grids as T
import parse_timesforthetimes as P

TINY = ("..#..",
        ".....",
        "#...#",
        ".....",
        "..#..")
T.SIZE["Test"] = 5

# Letters that actually constrain each other: every white cell gets its own,
# so two lights that cross agree on one square and on no other.
letter = lambda y, x: chr(ord("A") + (y * 5 + x) % 26)
cells = rg.light_cells(TINY)
rec = {"series": "Test", "entries": [
    {"number": n, "direction": d, "answer": "".join(letter(*c) for c in cs)}
    for (n, d), cs in cells.items()]}

# The light list this module feeds the solver must BE the one the grid would
# print, in printed order. A different order is a different puzzle.
print("PRINTED_ORDER", T.triples(rec) == rg.lights_from_grid(TINY))

grids, how = T.solve(rec)
print("SOLVED_HOW", how)
print("SOLVED_IS_IT", len(grids) == 1 and grids[0] == TINY)

print("FIT_TRUE", T.answers_fit(TINY, rec))
clash = {"series": "Test", "entries": [dict(e) for e in rec["entries"]]}
clash["entries"][0]["answer"] = "Z" * len(clash["entries"][0]["answer"])
print("FIT_CLASH", T.answers_fit(TINY, clash))

# Out of budget is not the same fact as no grid fits, and the caller acts on
# the difference: one is a knob, the other is a blog post to go and re-read.
print("BUDGET", T.solve(rec, max_nodes=1)[1])

# A light list no grid of this size can print is a light list, not a budget:
# it must read as "no grid" even though the search also finished, because the
# only fix for it is to go back to the blog post.
toolong = {"series": "Test", "entries": [
    {"number": 1, "direction": "across", "answer": "A" * 9}]}
print("TOOLONG", T.solve(toolong)[1])

# A run over the whole corpus is tens of hours and gets killed. The next one
# has to keep what the last one solved: read back the ids it wrote, tolerate
# the torn last line a kill leaves, and append rather than truncate.
import json, pathlib, tempfile
tmp = pathlib.Path(tempfile.mkdtemp()) / "grids.jsonl"
tmp.write_text(json.dumps({"post_id": 111}) + "\n" + '{"post_id": 222, "gri')
T.OUT = tmp
print("RESUME", sorted(T.solved_already()))
T.open_out(False).close()
print("KEPT", tmp.read_text().startswith('{"post_id": 111}'))
T.open_out(True).close()
print("FRESH", tmp.read_text())

# A relaunch must skip what it already TRIED, not just what it solved: the
# failures are the expensive ones — a Jumbo spends the whole budget and finds
# nothing — so resuming off the grids alone re-grinds them every time. Raising
# the budget is still how a truncated puzzle gets another go, so a smaller
# recorded budget must not skip it.
T.ATTEMPTS = tmp.parent / "attempts.jsonl"
T.ATTEMPTS.write_text(
    json.dumps({"post_id": 1, "how": "no grid", "max_nodes": 6000000}) + "\n"
    + json.dumps({"post_id": 2, "how": "truncated", "max_nodes": 400000}) + "\n")
print("TRIED", sorted(T.attempted(6000000)))
print("BIGGER", sorted(T.attempted(400000)))

# Answers that refute EVERY candidate are the opposite of an ambiguous grid:
# the right grid is not in the list, so the light list or an answer is wrong.
# This said "crossings ruled out none", which reads as the exact opposite, and
# the one puzzle it fired on got quoted as a grid the crossings could not
# settle. Two candidates, neither of which the answers fit.
real = rg.reconstruct
rg.reconstruct = lambda *a, **k: ([TINY, (".#...", ".....", "#...#", ".....", "...#.")],
                                  {"truncated": False})
print("REFUTED", T.solve(clash)[1])
rg.reconstruct = real

# Barred puzzles have no black squares, so numbering inverts to nothing. They
# are parsed and then deliberately not sized here; a typo in the name would
# look identical, so check both halves.
print("BARRED", sorted(s for s in P.SERIES.values() if s not in T.SIZE))
e = {"number": 1, "direction": "across", "answer": "AB"}
print("CLUES", T.has_clues({"entries": [dict(e, clue="Clue (2)")] * 10}),
      T.has_clues({"entries": [dict(e, clue="")] * 10}))
PY
)
echo "$out"
field() { awk -v k="$1" '$1==k {$1=""; sub(/^ /,""); print}' <<<"$out"; }

check "the solver is fed the light list the grid would print" True "$(field PRINTED_ORDER)"
check "a complete light list pins one grid down" unique "$(field SOLVED_HOW)"
check "and it is the grid the lights came from" True "$(field SOLVED_IS_IT)"
check "answers that agree at every crossing fit" True "$(field FIT_TRUE)"
check "one answer that disagrees at a crossing does not" False "$(field FIT_CLASH)"
check "a search that ran out of budget says so" truncated "$(field BUDGET)"
check "a light no grid could hold reads as no grid, not as truncated" \
      "no grid" "$(field TOOLONG)"
check "a killed run reads back what it already solved" "[111]" "$(field RESUME)"
check "and appends to it rather than truncating" True "$(field KEPT)"
check "only --fresh starts the file over" "" "$(field FRESH)"
check "a failure is not re-ground on the next run" "[1]" "$(field TRIED)"
check "but a bigger budget retries what it truncated" "[1, 2]" "$(field BIGGER)"
check "answers refuting every candidate does not read as an unsettled tie" \
      "answers fit none of 2" "$(field REFUTED)"
check "barred series are excluded, by their parsed names" \
      "['Mephisto', 'Monthly Club Special', 'Other Crosswords']" "$(field BARRED)"
check "a post that gives only the answers is not searched" "True False" "$(field CLUES)"

if [ "$fails" -gt 0 ]; then echo "$fails FAILURE(S)"; exit 1; fi
echo "times_grids: all checks passed"
