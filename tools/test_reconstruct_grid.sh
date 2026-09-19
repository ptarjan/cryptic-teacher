#!/bin/bash
# Can a grid really be recovered from nothing but its clue list?
#
#     bash tools/test_reconstruct_grid.sh
#     SAMPLE=300 NUMBERLESS_SAMPLE=80 bash tools/test_reconstruct_grid.sh
#
# tools/reconstruct_grid.py claims that the black squares of a blocked
# crossword are a function of the lights printed above the clues, and that the
# function can be run backwards. That claim is worth exactly as much as it
# scores against grids somebody else drew, so this runs it against ours: take a
# published puzzle, throw the grid away, keep only what a reader of the clue
# list has, and see whether what comes back is the grid that was thrown away.
#
# Three outcomes are counted and all three are printed, because two of them are
# easy to hide. EXACT is one grid and it is the published one. AMBIGUOUS is
# several grids, the published one among them — a right answer that cannot be
# used unattended. MISS is the published grid not in the set at all. A fourth,
# BUDGET, is kept apart from MISS on purpose: it means the node cap stopped the
# search before it had an answer, which is a statement about this machine and
# not about the puzzle, and folding it into either hits or misses would be a
# lie in whichever direction happened to flatter the tool.
#
# Both input shapes are scored, because the weaker one is the one that matters.
# Clue numbers survive in a newspaper and in a blog; they do not survive OCR of
# a printed book, which leaves clue text and enumerations and no numerals. So
# the second pass throws the numbers away and reconstructs from two ordered
# lists of lengths, and is scored separately and on a smaller sample, being
# some five times the search.
#
# The sample is stratified over every series and every grid size in the corpus,
# not drawn uniformly: 8,393 Guardian cryptics would otherwise drown the 52
# Metro puzzles, the 13x13s and the four 21x21-and-up grids, and those are
# where a 15x15 assumption would show up. The seed is fixed, so a run that
# changes its numbers is the tool changing, not the draw.
#
# Defaults are sized for CI, which runs every tools/test_*.sh on every push;
# SAMPLE and NUMBERLESS_SAMPLE take it as far as you have patience for.
#
# Before any of that, the conventions the search leans on are re-counted over
# all 15,931 puzzles. Every one of them was measured off this corpus rather
# than taken from a book on crossword construction, and a corpus that has
# grown a series since is a corpus that can have quietly falsified one —
# "no light shorter than three" and "at least half of every light is checked"
# both sound right and are both false here. A convention that has stopped
# holding must fail loudly in this file, not silently as a drop in the hit
# rate, so the counts are asserted against the tool's own strictness.
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
fails=0
check() { if grep -qF -- "$2" <<<"$1"; then echo "  ok: $3"; else
  echo "  FAIL: $3"$'\n'"    wanted to find: $2"$'\n'"    in: $1"; fails=$((fails + 1)); fi; }
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }
least() { if [ "$2" -ge "$3" ] 2>/dev/null; then echo "  ok: $1 ($2 >= $3)"; else
  echo "  FAIL: $1"$'\n'"    want at least $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }
most() { if [ "$2" -le "$3" ] 2>/dev/null; then echo "  ok: $1 ($2 <= $3)"; else
  echo "  FAIL: $1"$'\n'"    want at most $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }
field() { awk -v k="$1" '$1==k {print $2}' <<<"$2"; }

echo "the numbering is a function: a grid re-derives its own clue list, and a hand-built 5x5 comes back"
out0=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import reconstruct_grid as R
from fetch_puzzle import read_puzzle_file, resolve_puzzle

# Forwards first. If scanning a grid row-major did not reproduce the numbers
# the publisher printed, nothing downstream of it could mean anything.
puz = read_puzzle_file(resolve_puzzle("cryptic-30066"))
print("NUMBERING_MATCHES",
      sorted(R.lights_from_grid(R.grid_of(puz))) == sorted(R.lights_of(puz)))

# Backwards, on a grid small enough to read: a 5x5 with a block in each corner
# pair. Nothing about it comes from the corpus, so a corpus that changed shape
# cannot make this pass or fail. Its lights are two and three cells long,
# which is the case a minimum-light-length rule would wrongly throw out.
tiny = ("..#..",
        ".....",
        "#...#",
        ".....",
        "..#..")
lights = R.lights_from_grid(tiny)
found, _ = R.reconstruct(lights, cols=5, rows=5, strict=False)
print("TINY_FOUND", len(found))
print("TINY_IS_IT", tiny in found)
bare = {"across": [n for _, d, n in lights if d == "across"],
        "down": [n for _, d, n in lights if d == "down"]}
found, _ = R.reconstruct(bare, cols=5, rows=5, strict=False)
print("TINY_NUMBERLESS", tiny in found)

# A clue list no grid can print must come back empty rather than come back
# wrong: 1-across of 15 with nothing else is not a crossword.
found, _ = R.reconstruct([(1, "across", 15)], cols=15, rows=15)
print("IMPOSSIBLE", len(found))

# An unknown length, written None, is what a "See 15" clue leaves behind: a
# real light with no enumeration of its own. Blanking any one length in turn
# must still land on the same grid, or the book puzzles that have several of
# them are out of reach.
survives = True
for direction in ("across", "down"):
    for i in range(len(bare[direction])):
        blanked = {d: list(v) for d, v in bare.items()}
        blanked[direction][i] = None
        found, _ = R.reconstruct(blanked, cols=5, rows=5, strict=False)
        survives = survives and tiny in found
print("BLANK_ONE_LENGTH", survives)

# Two real grids recovered from the number-less form, which is the form the
# book scans are in. everyman-3082 is an ordinary 15x15; globeandmail-3146 is
# a 13x13 its setter drew without symmetry, so it only comes back at all
# through the fallback, and it is here to keep that path alive.
for pid, loose in (("everyman-3082", False), ("globeandmail-3146", True)):
    puz = read_puzzle_file(resolve_puzzle(pid))
    found, info = R.reconstruct(
        R.lights_of(puz, numbered=False),
        cols=puz["dimensions"]["cols"], rows=puz["dimensions"]["rows"],
        fallback=loose)
    print(f"REAL_{pid.split('-')[0].upper()}",
          len(found) == 1 and found[0] == R.grid_of(puz))

# And the sentence a miss is explained by has to name a real fault. These two
# are why the tool cannot have them: one grid the publisher drew asymmetric,
# one whose printed numbering is not what its own grid prints.
crooked = R.grid_of(read_puzzle_file(resolve_puzzle("cyclops-300")))
print("NAMES_ASYMMETRY", R.conventions_broken(crooked))
# A puzzle on disk that fails this is a corpus defect, not a fixture -- once
# found, tools/puzzle_integrity.py's NUMBER check gets it fixed, which would
# make a fixture that names one by id fail the moment the corpus is clean.
# So this mislabels a real, currently-correct puzzle in memory instead: one
# entry's stored number is bumped far past every number the grid would ever
# hand out, which changes nothing about the black squares (grid_of reads
# position and length, never number) but guarantees the stored and
# grid-derived lists disagree.
mislabelled = read_puzzle_file(resolve_puzzle("everyman-3082"))
mislabelled["entries"][0]["number"] += 1000
print("SPOTS_BAD_LIST",
      R.conventions_broken(R.grid_of(mislabelled)) == []
      and sorted(R.lights_from_grid(R.grid_of(mislabelled)))
      != sorted(R.lights_of(mislabelled)))
PY
)
same "scanning cryptic-30066 row-major reprints its own clue list" \
  "$(field NUMBERING_MATCHES "$out0")" "True"
same "the 5x5 has exactly one reconstruction" "$(field TINY_FOUND "$out0")" "1"
same "and it is the grid it was built from" "$(field TINY_IS_IT "$out0")" "True"
same "which the number-less form also finds" "$(field TINY_NUMBERLESS "$out0")" "True"
same "a clue list no grid could print yields no grid" "$(field IMPOSSIBLE "$out0")" "0"
same "a real 15x15 comes back uniquely from lengths alone, no clue numbers" \
  "$(field REAL_EVERYMAN "$out0")" "True"
same "and so does a 13x13 its setter drew without symmetry" \
  "$(field REAL_GLOBEANDMAIL "$out0")" "True"
same "any one length left unknown still recovers the 5x5" \
  "$(field BLANK_ONE_LENGTH "$out0")" "True"
check "$out0" "NAMES_ASYMMETRY ['not 180-degree symmetric']" \
  "a miss on an asymmetric grid says so"
same "and a puzzle whose printed numbering is not its grid's is told apart from it" \
  "$(field SPOTS_BAD_LIST "$out0")" "True"

echo "the conventions, re-counted over every puzzle on disk"
out1=$(PYTHONPATH="$REPO/tools" python3 - <<'PY'
import reconstruct_grid as R
from fetch_puzzle import read_puzzle_file, puzzle_files

total = sym = min2_row = min2_col = gap_row = gap_col = 0
thin = short = 0
for path in puzzle_files():
    puzzle = read_puzzle_file(path)
    grid = R.grid_of(puzzle)
    rows, cols = len(grid), len(grid[0])
    total += 1
    # The two rules this tool refuses to adopt, counted rather than argued
    # about. If either of these ever reaches zero the exclusion has become
    # free, and the docstring saying real crosswords break them is wrong.
    runs = {}
    for entry in puzzle["entries"]:
        spot, step = entry["position"], entry["direction"] == "across"
        runs[(entry["number"], entry["direction"])] = [
            (spot["x"] + i, spot["y"]) if step else (spot["x"], spot["y"] + i)
            for i in range(entry["length"])]
    if any(len(cells) == 2 for cells in runs.values()):
        short += 1
    seen = {}
    for (_, direction), cells in runs.items():
        for cell in cells:
            seen.setdefault(cell, set()).add(direction)
    crossed = {cell for cell, ways in seen.items() if len(ways) == 2}
    if any(sum(1 for c in cells if c in crossed) * 2 < len(cells)
           for cells in runs.values()):
        thin += 1
    if all(grid[y][x] == grid[rows - 1 - y][cols - 1 - x]
           for y in range(rows) for x in range(cols)):
        sym += 1

    def runs(cells):
        out, run = [], 0
        for c in list(cells) + [False]:
            if c:
                run += 1
            else:
                if run:
                    out.append(run)
                run = 0
        return out

    lines = [[c == "." for c in row] for row in grid]
    columns = [[lines[y][x] for y in range(rows)] for x in range(cols)]
    if min(sum(line) for line in lines) >= 2:
        min2_row += 1
    if min(sum(col) for col in columns) >= 2:
        min2_col += 1

    def no_two_bare(groups):
        bare = 0
        for group in groups:
            bare = bare + 1 if not any(r >= 2 for r in runs(group)) else 0
            if bare >= 2:
                return False
        return True

    gap_row += no_two_bare(lines)
    gap_col += no_two_bare(columns)
print("TOTAL", total)
print("SYMMETRIC", sym)
print("ROWS_AT_LEAST_TWO_WHITE", min2_row)
print("COLS_AT_LEAST_TWO_WHITE", min2_col)
print("NO_TWO_BARE_ROWS", gap_row)
print("NO_TWO_BARE_COLS", gap_col)
print("HAS_A_TWO_CELL_LIGHT", short)
print("HAS_A_LIGHT_UNDER_HALF_CHECKED", thin)
PY
)
n_total=$(field TOTAL "$out1")
echo "  (corpus: $n_total puzzles)"
# The strict rules are enforced with no exception at all, so anything short of
# every puzzle here is the tool refusing to find a grid somebody published.
same "every puzzle has two or more white cells in every row" \
  "$(field ROWS_AT_LEAST_TWO_WHITE "$out1")" "$n_total"
same "and in every column" "$(field COLS_AT_LEAST_TWO_WHITE "$out1")" "$n_total"
same "no puzzle has two adjacent rows without an across light" \
  "$(field NO_TWO_BARE_ROWS "$out1")" "$n_total"
same "nor two adjacent columns without a down light" \
  "$(field NO_TWO_BARE_COLS "$out1")" "$n_total"
# Symmetry is the one assumption known to have exceptions, so it is asserted as
# a floor rather than as all of them: 35 puzzles are not symmetric and the
# default pass cannot reconstruct them.
least "at least 99.5% of grids are 180-degree symmetric" \
  "$(( $(field SYMMETRIC "$out1") * 1000 / n_total ))" "995"
# The mirror image of the rules above: two rules the tool deliberately does
# not enforce, held out of it because this corpus breaks them. The day the
# corpus stops breaking them is the day that sentence needs rewriting.
least "some puzzle still has a two-cell light, so no minimum length may be imposed" \
  "$(field HAS_A_TWO_CELL_LIGHT "$out1")" "1"
least "thousands still have a light under half checked, so no checking rule may be imposed" \
  "$(field HAS_A_LIGHT_UNDER_HALF_CHECKED "$out1")" "1000"

echo "reconstruction against the corpus, sampled across every series and size"
out2=$(SAMPLE="${SAMPLE:-26}" NUMBERLESS_SAMPLE="${NUMBERLESS_SAMPLE:-4}" \
  MAX_NODES="${MAX_NODES:-1000000}" \
  NUMBERLESS_MAX_NODES="${NUMBERLESS_MAX_NODES:-2000000}" \
  PARTIAL_SAMPLE="${PARTIAL_SAMPLE:-2}" \
  PARTIAL_MAX_NODES="${PARTIAL_MAX_NODES:-250000}" \
  PYTHONPATH="$REPO/tools" python3 - <<'PY'
import os
import random
import re
import time
from multiprocessing import Pool
from pathlib import Path

import reconstruct_grid as R
from fetch_puzzle import read_puzzle_file, puzzle_files

COLS = re.compile(r'"cols":\s*(\d+)')
ROWS = re.compile(r'"rows":\s*(\d+)')


def stratify(paths, want):
    """One draw per (series, size), then proportional, then the remainder.

    Reading the head of each file is enough for the size and costs a fraction
    of parsing the whole corpus, which this test does not otherwise need to do.
    """
    groups = {}
    for path in paths:
        head = path.read_bytes()[:3000].decode("utf-8", "replace")
        wide, tall = COLS.search(head), ROWS.search(head)
        size = (int(wide.group(1)), int(tall.group(1))) if wide and tall else (0, 0)
        groups.setdefault((path.name.rsplit("-", 1)[0], size), []).append(path)
    rng = random.Random(20260918)
    keys = sorted(groups)
    for key in keys:
        rng.shuffle(groups[key])
    picked = [groups[key][0] for key in keys]
    spare, room = [], max(0, want - len(picked))
    pool_size = sum(len(groups[key]) - 1 for key in keys) or 1
    for key in keys:
        rest = groups[key][1:]
        share = room * len(rest) // pool_size
        picked += rest[:share]
        spare += rest[share:]
    rng.shuffle(spare)
    picked += spare[:max(0, want - len(picked))]
    return picked, len(keys)


def classify(puzzle, spec, cols, rows, budget):
    """Run one reconstruction and sort it into the same four buckets everywhere.

    Shared by the fully-numbered, fully-numberless and partially-numbered
    attempts below, so a miss means the same thing -- the search finished and
    disagreed with the paper -- regardless of which of the three produced it.
    """
    published = R.grid_of(puzzle)
    started = time.time()
    found, info = R.reconstruct(spec, cols=cols, rows=rows, limit=40,
                                max_nodes=budget)
    elapsed = time.time() - started
    why = ""
    if published in found:
        verdict = "exact" if len(found) == 1 else "ambiguous"
    elif info["truncated"]:
        verdict = "budget"
    else:
        verdict = "miss"
        # A miss is never left as a number. Either the published grid breaks a
        # rule the search enforces, or the published clue list is not the one
        # that grid prints -- in which case the puzzle file is wrong and the
        # reconstruction was right to disagree with it.
        why = ";".join(R.conventions_broken(published)) or (
            "clue list is not what this grid prints"
            if sorted(R.lights_from_grid(published)) != sorted(R.lights_of(puzzle))
            else "no rule broken: the search is wrong")
    return verdict, len(found), info["nodes"], round(elapsed, 2), why


def attempt(job):
    path, numbered, budget = job
    puzzle = read_puzzle_file(path)
    cols, rows = puzzle["dimensions"]["cols"], puzzle["dimensions"]["rows"]
    spec = R.lights_of(puzzle, numbered=numbered)
    return (path.name,) + classify(puzzle, spec, cols, rows, budget)


def attempt_partial(job):
    """Same as attempt(), but a controlled fraction of numbers are erased --
    the shape a partially-OCR'd book puzzle is actually in. The seed is
    derived from the puzzle's own filename and the fraction, not from a
    counter, so it is stable no matter what order jobs run in or how many
    other levels are being swept in the same invocation.
    """
    path, fraction, budget = job
    puzzle = read_puzzle_file(path)
    cols, rows = puzzle["dimensions"]["cols"], puzzle["dimensions"]["rows"]
    seed = f"reconstruct_grid partial sweep:{path.name}:{fraction}"
    spec = R.blank_numbers(R.lights_of(puzzle, numbered=True), fraction,
                           random.Random(seed))
    return (path.name,) + classify(puzzle, spec, cols, rows, budget)


def run_jobs(fn, jobs):
    """One pool for however many jobs there are -- forking workers is not
    free on every machine this runs on, and paying it once for a batch of
    jobs beats paying it once per report() call."""
    with Pool(min(4, os.cpu_count() or 1)) as pool:
        return pool.map(fn, jobs, chunksize=1)


def summarize(tag, results):
    tally = {"exact": 0, "ambiguous": 0, "miss": 0, "budget": 0}
    for _, verdict, _, _, _, _ in results:
        tally[verdict] += 1
    times = sorted(r[4] for r in results)
    ambiguity = sorted(r[2] for r in results if r[1] == "ambiguous")
    print(tag, "n", len(results),
          "exact", tally["exact"], "ambiguous", tally["ambiguous"],
          "miss", tally["miss"], "budget", tally["budget"],
          "median_s", times[len(times) // 2],
          "worst_s", times[-1],
          "mean_s", round(sum(times) / len(times), 2),
          "amb_median", ambiguity[len(ambiguity) // 2] if ambiguity else 0,
          "amb_worst", ambiguity[-1] if ambiguity else 0)
    for name, verdict, count, nodes, elapsed, why in sorted(results):
        if verdict in ("miss", "budget"):
            print(f"{verdict.upper()}_{tag} {name} grids={count} "
                  f"nodes={nodes} seconds={elapsed}"
                  + (f" why={why}" if why else ""))
    return results


def report(tag, paths, fn, mode, budget):
    return summarize(tag, run_jobs(fn, [(p, mode, budget) for p in paths]))


files = sorted(puzzle_files())
sample, n_groups = stratify(files, int(os.environ["SAMPLE"]))
print("GROUPS", n_groups)
print("SAMPLED", len(sample))
report("NUMBERED", sample, attempt, True, int(os.environ["MAX_NODES"]))
smaller = sample[:int(os.environ["NUMBERLESS_SAMPLE"])]
report("NUMBERLESS", smaller, attempt, False, int(os.environ["NUMBERLESS_MAX_NODES"]))

# The point of this module: 175 of our 398 OCR'd book puzzles have SOME clue
# numbers but not all. Full numbering (NUMBERED above) and none at all
# (NUMBERLESS above) are the two ends of one curve; this sweeps the middle of
# it on a small, fixed-seed sample, small enough to keep this file's runtime
# close to what it was before partial numbering existed. PARTIAL_SAMPLE and
# PARTIAL_MAX_NODES take it further, the same way SAMPLE and MAX_NODES do for
# the fully-numbered pass. All four levels run as one batch of jobs in one
# pool, not four reports back to back -- forking workers four separate times
# for two puzzles each was most of what this section used to cost.
#
# Drawn from past the first n_groups of `sample`, deliberately: those first
# picks are one per (series, size) and include the 21x21-and-up outliers that
# are already the slowest thing NUMBERED runs above, at NUMBERED's much
# larger node budget. That is the right sample for proving every size is
# covered; it is the wrong sample for a curve that is supposed to show
# partial numbering *helping*, since a grid too big to finish at any
# numbering level tells this sweep nothing a smaller one would not.
smallest = sample[n_groups:n_groups + int(os.environ["PARTIAL_SAMPLE"])]
partial_budget = int(os.environ["PARTIAL_MAX_NODES"])
levels = (10, 25, 50, 75)
jobs = [(p, pct / 100, partial_budget) for pct in levels for p in smallest]
all_results = run_jobs(attempt_partial, jobs)
per_level = len(smallest)
for i, pct in enumerate(levels):
    summarize(f"PARTIAL_{pct}", all_results[i * per_level:(i + 1) * per_level])
PY
)
echo "$out2" | grep -E "^(NUMBERED|NUMBERLESS|PARTIAL_[0-9]+ |MISS_|BUDGET_)" | sed 's/^/  /'

read -r _ _ n_num _ ex_num _ amb_num _ miss_num _ bud_num _ <<<"$(grep '^NUMBERED ' <<<"$out2")"
read -r _ _ n_bare _ ex_bare _ amb_bare _ miss_bare _ bud_bare _ <<<"$(grep '^NUMBERLESS ' <<<"$out2")"
same "every series and size was drawn from" "$(field GROUPS "$out2")" "13"
same "every attempt lands in exactly one of the four buckets" \
  "$(( ex_num + amb_num + miss_num + bud_num ))" "$n_num"
# Everything below is stated against the attempts that finished, because
# running out of nodes says nothing about the puzzle -- and it is bounded in
# nodes rather than seconds, so these hold on a slow machine too.
done_num=$(( n_num - bud_num ))
least "with numbers: at least 60% of the sample finishes inside the node cap" \
  "$(( done_num * 100 / n_num ))" "60"
least "with numbers: the published grid is among the answers for 95% of those" \
  "$(( (ex_num + amb_num) * 100 / done_num ))" "95"
least "with numbers: over half of those are a single grid, not a shortlist" \
  "$(( ex_num * 100 / done_num ))" "55"
most "with numbers: at most 3% of those are wrong rather than unfinished" \
  "$(( miss_num * 100 / done_num ))" "3"
# Without numbers the honest claim is much weaker and is asserted as such: it
# is allowed to give up, it is allowed to hand back a shortlist, and it is not
# allowed to hand back the wrong grid and call it finished.
most "without numbers: nothing that finishes comes back with the wrong grid" \
  "$miss_bare" "0"

# Partial numbering: the actual prize, since 175 of our 398 book puzzles sit
# somewhere on this curve and none of them are usable without it. Each level
# gets the one invariant that has to hold everywhere on the curve -- a miss
# is a correctness bug regardless of how much numbering was left -- rather
# than a percentage threshold, because PARTIAL_SAMPLE is small enough by
# design that a percentage of it is not a stable number to assert against.
# What the levels are actually worth is the tally line itself, printed above;
# reading that curve is how the 175 partially-numbered book puzzles get
# triaged into "worth running" and "not yet", not a pass/fail here.
for pct in 10 25 50 75; do
  read -r _ _ n_p _ ex_p _ amb_p _ miss_p _ bud_p _ <<<"$(grep "^PARTIAL_$pct " <<<"$out2")"
  same "partial numbering at ${pct}%: every attempt lands in exactly one bucket" \
    "$(( ex_p + amb_p + miss_p + bud_p ))" "$n_p"
  most "partial numbering at ${pct}%: nothing that finishes comes back with the wrong grid" \
    "$miss_p" "0"
done
# The lightest damage level is the one book puzzles at 80-99% coverage look
# like, so it is held to more than "did not crash": most of a small,
# fixed-seed sample should still resolve to the published grid or a
# shortlist containing it.
read -r _ _ n_10 _ ex_10 _ amb_10 _ miss_10 _ bud_10 _ <<<"$(grep '^PARTIAL_10 ' <<<"$out2")"
least "partial numbering at 10% blanked: most of the sample still resolves" \
  "$(( (ex_10 + amb_10) * 100 / n_10 ))" "50"

[ "$fails" = 0 ] && echo "reconstruct_grid: all checks passed" || echo "reconstruct_grid: $fails FAILED"
exit $((fails > 0))
