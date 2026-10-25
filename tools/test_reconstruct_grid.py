#!/usr/bin/env python3
# Can a grid really be recovered from nothing but its clue list?
#
#     python3 tools/test_reconstruct_grid.py
#     SAMPLE=300 NUMBERLESS_SAMPLE=80 python3 tools/test_reconstruct_grid.py
#
# tools/reconstruct_grid.py claims that the black squares of a blocked
# crossword are a function of the lights printed above the clues, and that the
# function can be run backwards. That claim is worth exactly as much as it
# scores against grids somebody else drew, so this runs it against ours: take a
# published puzzle, throw the grid away, keep only what a reader of the clue
# list has, and see whether what comes back is the grid that was thrown away.
#
# Five outcomes are counted and all are printed, because some are easy to hide.
# EXACT is one grid and it is the published one. AMBIGUOUS is several grids,
# the published one among them — a right answer that cannot be used
# unattended. MISS is the published grid not in the set at all. BUDGET is kept
# apart from MISS on purpose: it means the node cap stopped the search before
# it had an answer, which is a statement about this machine and not about the
# puzzle, and folding it into either hits or misses would be a lie in whichever
# direction happened to flatter the tool. UNCONVENTIONAL is a miss on a
# published grid that itself breaks a convention the search enforces.
#
# Both input shapes are scored, because the weaker one is the one that matters.
# Clue numbers survive in a newspaper and in a blog; they do not survive OCR of
# a printed book, which leaves clue text and enumerations and no numerals. So
# the second pass throws the numbers away and reconstructs from two ordered
# lists of lengths, and is scored separately and on a smaller sample, being
# some five times the search.
#
# The sample is stratified over every series and every grid size in the corpus,
# not drawn uniformly: the Guardian cryptics would otherwise drown the Metro
# puzzles, the 13x13s and the 21x21-and-up grids, and those are
# where a 15x15 assumption would show up. The seed is fixed, so a run that
# changes its numbers is the tool changing, not the draw.
#
# Defaults are sized for CI, which runs every tools/test_* on every push;
# SAMPLE and NUMBERLESS_SAMPLE take it as far as you have patience for.
#
# Before any of that, the conventions the search leans on are re-counted over
# every 40th puzzle (all of them under CT_FULL=1, which the nightly sets).
# Every one of them was measured off this corpus rather than taken from a book
# on crossword construction, and a corpus that grows a series can quietly
# falsify one —
# "no light shorter than three" and "at least half of every light is checked"
# both sound right and are both false here. A convention that has stopped
# holding must fail loudly in this file, not silently as a drop in the hit
# rate, so the counts are asserted against the tool's own strictness.
#
# The three groups of Python checks each run in a fresh interpreter (this file
# re-invoked with the group's name), as the corpus passes are slow and independent.
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, str(REPO / "tools"))


def group0():
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
    # book scans are in. everyman-3082 is an ordinary 15x15; timesquick-3146 is
    # a 13x13 its setter drew without symmetry, so it only comes back at all
    # through the fallback, and it is here to keep that path alive.
    for name, pid, loose in (("EVERYMAN", "everyman-3082", False), ("TIMESQUICK", "timesquick-3146", True)):
        puz = read_puzzle_file(resolve_puzzle(pid))
        found, info = R.reconstruct(
            R.lights_of(puz, numbered=False),
            cols=puz["dimensions"]["cols"], rows=puz["dimensions"]["rows"],
            fallback=loose)
        print(f"REAL_{name}",
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


def group1():
    import os
    import reconstruct_grid as R
    from fetch_puzzle import read_puzzle_file, puzzle_files

    total = sym = min2_row = min1_col = min2_col = gap_row = gap_col = 0
    thin = short = 0
    for path in list(puzzle_files())[::int(os.environ["STEP"])]:
        puzzle = read_puzzle_file(path)
        # An unclued light's cells are in no entry, so the entries do not describe
        # its grid; these conventions are about grids the entries draw whole. A
        # barred grid has no black squares, so the blocked-grid conventions say
        # nothing about it.
        if puzzle.get("unclued") or puzzle.get("bars"):
            continue
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
        if min(sum(col) for col in columns) >= 1:
            min1_col += 1
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
    print("ASYMMETRIC", total - sym)
    # The floor is 99.5% symmetric. Over the whole corpus that is a count; over a
    # sample it is the most asymmetric grids a corpus exactly at the floor yields
    # but for one draw in a million (binomial upper tail), so only a sample that
    # proves the corpus below the floor fails.
    p, step = 0.005, int(os.environ["STEP"])
    if step == 1:
        allowed = int(total * p)
    else:
        pmf, below, allowed = (1 - p) ** total, 0.0, 0
        while True:
            below += pmf
            if 1 - below < 1e-6:
                break
            pmf *= (total - allowed) / (allowed + 1) * p / (1 - p)
            allowed += 1
    print("ASYMMETRIC_ALLOWED", allowed)
    print("ROWS_AT_LEAST_TWO_WHITE", min2_row)
    print("COLS_AT_LEAST_ONE_WHITE", min1_col)
    print("COLS_AT_LEAST_TWO_WHITE", min2_col)
    # The grid that lowered the column rule from two to one, named so the rule
    # cannot creep back up without this line failing: Genius 209 has a column
    # whose only white cell is inside 20-across.
    genius = next(p for p in puzzle_files() if p.name == "genius-209.json")
    print("GENIUS_209_BROKEN", repr(R.conventions_broken(R.grid_of(read_puzzle_file(genius)))))
    print("NO_TWO_BARE_ROWS", gap_row)
    print("NO_TWO_BARE_COLS", gap_col)
    print("HAS_A_TWO_CELL_LIGHT", short)
    print("HAS_A_LIGHT_UNDER_HALF_CHECKED", thin)


if len(sys.argv) > 1 and sys.argv[1] == "2":  # module level: its worker pool pickles functions by name
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
            # A disagreement is never left as a number, and the reason decides
            # which of the two it is. Where the PUBLISHED grid breaks a convention
            # the search enforces -- an asymmetric grid, a clue list that is not
            # what that grid prints -- the corpus is the odd one and the search was
            # right to disagree; scoring that against the search measures the
            # corpus. Only "no rule broken" is the search being wrong.
            why = ";".join(R.conventions_broken(published)) or (
                "clue list is not what this grid prints"
                if sorted(R.lights_from_grid(published)) != sorted(R.lights_of(puzzle))
                else "no rule broken: the search is wrong")
            verdict = "miss" if why.startswith("no rule broken") else "unconventional"
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
        tally = {"exact": 0, "ambiguous": 0, "miss": 0, "unconventional": 0,
                 "budget": 0}
        for _, verdict, _, _, _, _ in results:
            tally[verdict] += 1
        times = sorted(r[4] for r in results)
        ambiguity = sorted(r[2] for r in results if r[1] == "ambiguous")
        print(tag, "n", len(results),
              "exact", tally["exact"], "ambiguous", tally["ambiguous"],
              "miss", tally["miss"], "unconventional", tally["unconventional"],
              "budget", tally["budget"],
              "median_s", times[len(times) // 2],
              "worst_s", times[-1],
              "mean_s", round(sum(times) / len(times), 2),
              "amb_median", ambiguity[len(ambiguity) // 2] if ambiguity else 0,
              "amb_worst", ambiguity[-1] if ambiguity else 0)
        for name, verdict, count, nodes, elapsed, why in sorted(results):
            if verdict in ("miss", "unconventional", "budget"):
                print(f"{verdict.upper()}_{tag} {name} grids={count} "
                      f"nodes={nodes} seconds={elapsed}"
                      + (f" why={why}" if why else ""))
        return results


    def report(tag, paths, fn, mode, budget):
        return summarize(tag, run_jobs(fn, [(p, mode, budget) for p in paths]))


    # By file name, so the fixed-seed sample does not move with the folder layout.
    files = sorted(puzzle_files(), key=lambda path: path.name)
    sample, n_groups = stratify(files, int(os.environ["SAMPLE"]))
    print("GROUPS", n_groups)
    print("SAMPLED", len(sample))
    report("NUMBERED", sample, attempt, True, int(os.environ["MAX_NODES"]))
    smaller = sample[:int(os.environ["NUMBERLESS_SAMPLE"])]
    report("NUMBERLESS", smaller, attempt, False, int(os.environ["NUMBERLESS_MAX_NODES"]))

    # Many OCR'd book puzzles have SOME clue numbers but not all. Full numbering
    # (NUMBERED above) and none at all (NUMBERLESS above) are the two ends of one
    # curve; this sweeps the middle of it on a small, fixed-seed sample.
    # PARTIAL_SAMPLE and PARTIAL_MAX_NODES take it further, the same way SAMPLE and
    # MAX_NODES do for the fully-numbered pass. All four levels run as one batch of
    # jobs in one pool, not four reports back to back, since forking workers four
    # separate times for two puzzles each is mostly overhead.
    #
    # Named puzzles, not a draw: about 65% of ordinary grids resolve at 10%
    # blanked inside this budget, so a two-puzzle draw that reshuffles whenever
    # the corpus grows fails the 10% check below on roughly one night in eight.
    # Two ordinary grids that resolve keep it a regression check. PARTIAL_SAMPLE
    # above 2 adds draws from past the first n_groups of `sample`, which skips the
    # 21x21-and-up outliers no numbering level finishes.
    PINNED = ("cryptic-26530.json", "timesquick-2166.json")
    smallest = [p for p in files if p.name in PINNED]
    smallest += [p for p in sample[n_groups:] if p.name not in PINNED][
        :max(0, int(os.environ["PARTIAL_SAMPLE"]) - len(smallest))]
    partial_budget = int(os.environ["PARTIAL_MAX_NODES"])
    levels = (10, 25, 50, 75)
    jobs = [(p, pct / 100, partial_budget) for pct in levels for p in smallest]
    all_results = run_jobs(attempt_partial, jobs)
    per_level = len(smallest)
    for i, pct in enumerate(levels):
        summarize(f"PARTIAL_{pct}", all_results[i * per_level:(i + 1) * per_level])


GROUPS = {"0": group0, "1": group1, "2": lambda: None}
if len(sys.argv) > 1:
    GROUPS[sys.argv[1]]()
    sys.exit(0)

fails = 0


def check(blob, want, name):
    global fails
    if want in blob:
        print(f"  ok: {name}")
    else:
        print(f"  FAIL: {name}\n    wanted to find: {want}\n    in: {blob}")
        fails += 1


def same(name, got, want):
    global fails
    if str(got) == str(want):
        print(f"  ok: {name}")
    else:
        print(f"  FAIL: {name}\n    want {want}\n    got  {got}")
        fails += 1


def least(name, got, want):
    global fails
    if int(got) >= int(want):
        print(f"  ok: {name} ({got} >= {want})")
    else:
        print(f"  FAIL: {name}\n    want at least {want}\n    got  {got}")
        fails += 1


def most(name, got, want):
    global fails
    if int(got) <= int(want):
        print(f"  ok: {name} ({got} <= {want})")
    else:
        print(f"  FAIL: {name}\n    want at most {want}\n    got  {got}")
        fails += 1


def field(key, blob):
    return "\n".join(ln.split()[1] for ln in blob.splitlines()
                     if len(ln.split()) > 1 and ln.split()[0] == key)


def run(group, **env):
    r = subprocess.run([sys.executable, __file__, group], capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(REPO / "tools"), **env})
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
    return r.stdout.rstrip("\n")


def tally(blob, tag):
    """The numbers of a 'TAG _ n _ ex _ amb _ miss _ unc _ bud _' line, as ints."""
    for ln in blob.splitlines():
        if ln.startswith(tag):
            w = ln.split()
            return [int(w[i]) for i in (2, 4, 6, 8, 10, 12)]
    return [0] * 6


print("the numbering is a function: a grid re-derives its own clue list, and a hand-built 5x5 comes back")
out0 = run("0")
same("scanning cryptic-30066 row-major reprints its own clue list", field("NUMBERING_MATCHES", out0), "True")
same("the 5x5 has exactly one reconstruction", field("TINY_FOUND", out0), "1")
same("and it is the grid it was built from", field("TINY_IS_IT", out0), "True")
same("which the number-less form also finds", field("TINY_NUMBERLESS", out0), "True")
same("a clue list no grid could print yields no grid", field("IMPOSSIBLE", out0), "0")
same("a real 15x15 comes back uniquely from lengths alone, no clue numbers", field("REAL_EVERYMAN", out0), "True")
same("and so does a 13x13 its setter drew without symmetry", field("REAL_TIMESQUICK", out0), "True")
same("any one length left unknown still recovers the 5x5", field("BLANK_ONE_LENGTH", out0), "True")
check(out0, "NAMES_ASYMMETRY ['not 180-degree symmetric']", "a miss on an asymmetric grid says so")
same("and a puzzle whose printed numbering is not its grid's is told apart from it", field("SPOTS_BAD_LIST", out0), "True")

# Every STEP-th puzzle on disk, in file order, which is a fixed and evenly
# spread draw. CT_FULL=1 (the nightly job) takes all of them: the recount over
# the whole corpus is most of this script's runtime, and a convention that a
# fortieth of the corpus satisfies and the rest breaks is found by the night.
if os.environ.get("CT_FULL"):
    STEP = 1
else:
    STEP = int(os.environ.get("RECONSTRUCT_STEP", "40"))
print(f"the conventions, re-counted over every {STEP}th puzzle on disk (all of them when CT_FULL is set)")
out1 = run("1", STEP=str(STEP))
n_total = int(field("TOTAL", out1))
print(f"  (corpus: {n_total} puzzles)")
# The strict rules are enforced with no exception at all, so anything short of
# every puzzle here is the tool refusing to find a grid somebody published.
same("every puzzle has two or more white cells in every row", field("ROWS_AT_LEAST_TWO_WHITE", out1), n_total)
same("and one or more in every column", field("COLS_AT_LEAST_ONE_WHITE", out1), n_total)
check(out1, "GENIUS_209_BROKEN []", "Genius 209, with a one-cell column, breaks none of the tool's rules")
same("no puzzle has two adjacent rows without an across light", field("NO_TWO_BARE_ROWS", out1), n_total)
same("nor two adjacent columns without a down light", field("NO_TWO_BARE_COLS", out1), n_total)
# Symmetry is the one assumption known to have exceptions, so it is asserted as
# a floor rather than as all of them: some puzzles are not symmetric and the
# default pass cannot reconstruct them.
most("at least 99.5% of grids are 180-degree symmetric (asymmetric within what that allows)",
     field("ASYMMETRIC", out1), field("ASYMMETRIC_ALLOWED", out1))
# The mirror image of the rules above: rules the tool deliberately does
# not enforce, held out of it because this corpus breaks them. The day the
# corpus stops breaking them is the day that sentence needs rewriting.
# A two-cell light is rare enough that a sample can hold none, so it is the
# full pass that says one exists; the under-half count scales with the draw.
least("some puzzle still has a two-cell light, so no minimum length may be imposed",
      field("HAS_A_TWO_CELL_LIGHT", out1), 1 if STEP == 1 else 0)
least("thousands still have a light under half checked, so no checking rule may be imposed",
      field("HAS_A_LIGHT_UNDER_HALF_CHECKED", out1), 1000 // STEP)
# Genius 209 is one puzzle, so a sample usually misses it; the full pass is
# what says a published column still holds a single white cell.
least("some puzzle still has a column with one white cell, so columns may not be held to two",
      n_total - int(field("COLS_AT_LEAST_TWO_WHITE", out1)), 1 if STEP == 1 else 0)

print("reconstruction against the corpus, sampled across every series and size")
out2 = run("2",
           SAMPLE=os.environ.get("SAMPLE", "26"),
           NUMBERLESS_SAMPLE=os.environ.get("NUMBERLESS_SAMPLE", "4"),
           MAX_NODES=os.environ.get("MAX_NODES", "1000000"),
           NUMBERLESS_MAX_NODES=os.environ.get("NUMBERLESS_MAX_NODES", "2000000"),
           PARTIAL_SAMPLE=os.environ.get("PARTIAL_SAMPLE", "2"),
           PARTIAL_MAX_NODES=os.environ.get("PARTIAL_MAX_NODES", "250000"))
for ln in out2.splitlines():
    if ln.startswith(("NUMBERED", "NUMBERLESS", "MISS_", "UNCONVENTIONAL_", "BUDGET_")) or \
            __import__("re").match(r"PARTIAL_[0-9]+ ", ln):
        print("  " + ln)

n_num, ex_num, amb_num, miss_num, unc_num, bud_num = tally(out2, "NUMBERED ")
n_bare, ex_bare, amb_bare, miss_bare, unc_bare, bud_bare = tally(out2, "NUMBERLESS ")
# One (series, size) bucket per line of the corpus, counted by hand and written
# here as a number rather than computed: a sample that stops covering a series
# is exactly what this file exists to catch, and a count derived from the same
# files it is checking would agree with itself whatever arrived. A new series
# fails here and is meant to — read the number off `puzzles/*/*/*.json` (index.json
# is not a puzzle) and update it. 48 = cryptic at six sizes, listener at thirteen
# (10x10, 10x11, 10x12, 11x12, 12x12, 13x10, 13x11, 13x13, 14x14, 15x15, 15x19, 17x17, 18x22),
# azed at three (12x12, 13x11, 13x13), canberra (15x15, 13x13), cyclops, sundaytimes and timesjumbo at two, and book, everyman, ftcryptic,
# genius, independent, indysunday, mephisto, metro, nation, quiptic, sundaytel, sundaytough, telegraph,
# times, timesclub, timesquick, tls and toughie at one each. Every scanned printed book is the one `book` series, so
# another book does not move this number.
# Updated 44 -> 48 after nightly-smoke run 40147551416: listener gained four sizes.
same("every series and size was drawn from", field("GROUPS", out2), "48")
same("every attempt lands in exactly one of the five buckets",
     ex_num + amb_num + miss_num + unc_num + bud_num, n_num)
# Everything below is stated against the attempts that finished AND whose
# published grid obeys the conventions the search enforces. Running out of
# nodes says nothing about the puzzle -- and it is bounded in nodes rather than
# seconds, so these hold on a slow machine too. An unconventional grid says
# nothing about the search either: it is named on its own line above, and a
# count of them belongs to whoever is auditing the corpus. Scoring either
# against the search makes these percentages a fact about the draw.
done_num = n_num - bud_num - unc_num
least("with numbers: at least 60% of the sample finishes inside the node cap",
      (n_num - bud_num) * 100 // n_num, 60)
least("with numbers: the published grid is among the answers for 95% of those",
      (ex_num + amb_num) * 100 // done_num, 95)
least("with numbers: over half of those are a single grid, not a shortlist",
      ex_num * 100 // done_num, 55)
most("with numbers: at most 3% of those are wrong rather than unfinished",
     miss_num * 100 // done_num, 3)
# Without numbers the honest claim is much weaker and is asserted as such: it
# is allowed to give up, it is allowed to hand back a shortlist, and it is not
# allowed to hand back the wrong grid and call it finished.
most("without numbers: nothing that finishes comes back with the wrong grid", miss_bare, 0)

# Partial numbering: the actual prize, since many book puzzles sit somewhere on
# this curve and none of them are usable without it. Each level
# gets the one invariant that has to hold everywhere on the curve -- a miss
# is a correctness bug regardless of how much numbering was left -- rather
# than a percentage threshold, because PARTIAL_SAMPLE is small enough by
# design that a percentage of it is not a stable number to assert against.
# What the levels are actually worth is the tally line itself, printed above;
# reading that curve is how the partially-numbered book puzzles get
# triaged into "worth running" and "not yet", not a pass/fail here.
for pct in (10, 25, 50, 75):
    n_p, ex_p, amb_p, miss_p, unc_p, bud_p = tally(out2, f"PARTIAL_{pct} ")
    same(f"partial numbering at {pct}%: every attempt lands in exactly one bucket",
         ex_p + amb_p + miss_p + unc_p + bud_p, n_p)
    most(f"partial numbering at {pct}%: nothing that finishes comes back with the wrong grid", miss_p, 0)
# The lightest damage level is the one book puzzles at 80-99% coverage look
# like, so it is held to more than "did not crash": most of a small,
# fixed-seed sample should still resolve to the published grid or a
# shortlist containing it.
n_10, ex_10, amb_10, miss_10, unc_10, bud_10 = tally(out2, "PARTIAL_10 ")
least("partial numbering at 10% blanked: most of the sample still resolves",
      (ex_10 + amb_10) * 100 // n_10 if n_10 else 0, 50)

# no_square and min_light are the caller's options, off by default: a lone
# 2x2 of lights fits the clue list until the caller says no white square, and
# a free length of two fits until the caller says no light under three.
import reconstruct_grid as _R
_sq = [(1, "across", 2), (3, "across", 2), (1, "down", 2), (2, "down", 2)]
same("a 2x2 white square is found by default", len(_R.reconstruct(_sq, cols=2, rows=2, strict=False)[0]), 1)
same("no_square refuses it", len(_R.reconstruct(_sq, cols=2, rows=2, strict=False, no_square=True)[0]), 0)
_free = [(1, "across", None)]
same("a free length may be two cells", len(_R.reconstruct(_free, cols=2, rows=1, strict=False)[0]), 1)
same("min_light=3 refuses a two-cell free light", len(_R.reconstruct(_free, cols=2, rows=1, strict=False, min_light=3)[0]), 0)

# A linked group whose enumeration has a number per light has no split to
# search: Cyclops 63 ("11,1" = 6,7) and 73 ("12,7,27" = 5,10,10).
import privateeye_wayback as _PW
_acr = [[11, None, "linked", {"enumeration": "6,7"}]]
_dwn = [[1, None, "linked", {}]]
_left = _PW.pin_word_lengths([([("across", 0), ("down", 0)], 13)], _acr, _dwn)
same("one number per light pins both lengths", (_acr[0][1], _dwn[0][1], _left), (6, 7, []))
_acr = [[5, None, "linked", {"enumeration": "5,3,3,5"}]]
_dwn = [[1, None, "linked", {}]]
_left = _PW.pin_word_lengths([([("across", 0), ("down", 0)], 16)], _acr, _dwn)
same("more words than lights leaves the group open", (_acr[0][1], _dwn[0][1], len(_left)), (None, None, 1))

# The printed solutions (issues 909, 919) the OCR garbled: "DOWN: I (see 11)"
# opens with a see-row, "-3" is a speck before 3, and the page's next item
# ("MONDAY, MARCH 3, 44 BC") runs on after the last answer.
_sol = "ACROSS: 5 Vampire 8 Pep pill DOWN: I (see 11) 2 Belgrano -3 Oppo 4 Fatah"
_split = _PW.split_dirs(_sol)
same("a see-row after DOWN opens the list", _split is not None, True)
same("a speck before a number does not hide the answer before it",
     _PW.answer_rows(_split[1], "down"), [("2", "down", "BELGRANO"), ("3", "down", "OPPO"), ("4", "down", "FATAH")])
same("junk after the last answer adds no keys",
     _PW.answer_rows("1 Copper 22 Nation 23 Blair. MONDAY, MARCH 3, 44 BC INSIDE MELVYNUS", "down"),
     [("1", "down", "COPPER"), ("22", "down", "NATION"), ("23", "down", "BLAIR")])

# Printed solutions of Nos 61 and 27: speckle read from the picture beside an
# answer ("Minors JA, : yy, ee"), a number run into its answer ("12Ethelred"),
# and a linked answer whose column broke ("12/14 Feel-good ... factor").
same("speckle after an answer is not part of it",
     _PW.answer_rows("20SAS 21 Minors JA, : yy, ee 23 Sing Sing 25 The Lords", "across"),
     [("20", "across", "SAS"), ("21", "across", "MINORS"), ("23", "across", "SINGSING"), ("25", "across", "THELORDS")])
same("a linked answer takes the tail its column broke off",
     _PW.answer_rows("11 Nye 12/14 Feel-good 24 Santa 25 Iran 28See. factor 14 (See 12) 16 Bob Geldof", "across"),
     [("11", "across", "NYE"), ("12/14", "across", "FEELGOODFACTOR"), ("24", "across", "SANTA"),
      ("25", "across", "IRAN"), ("28", "across", "SEE"), ("16", "across", "BOBGELDOF")])

# Printed solution of No 20: "6/20d" with a direction letter, "18Hess_20" with
# an underscore for the space, "22.Panorama", "8S and M".
same("a scan's one-letter start, stop, underscore and link letter still read",
     _PW.answer_rows("6/20d Kenneth Clarke 17 Bust 18Hess_20 Clever dick 22.Panorama 23 On heat", "across"),
     [("6/20", "across", "KENNETHCLARKE"), ("17", "across", "BUST"), ("18", "across", "HESS"),
      ("20", "across", "CLEVERDICK"), ("22", "across", "PANORAMA"), ("23", "across", "ONHEAT")])
same("a number run into a one-letter answer start",
     _PW.answer_rows("7 Home Secretary 8S and M 14 The Hague", "down"),
     [("7", "down", "HOMESECRETARY"), ("8", "down", "SANDM"), ("14", "down", "THEHAGUE")])

if fails:
    print(f"reconstruct_grid: {fails} FAILED")
else:
    print("reconstruct_grid: all checks passed")
sys.exit(1 if fails else 0)
