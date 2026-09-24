#!/usr/bin/env python3
"""Rebuild the grids The Times does not publish, from the blog's clue lists.

tools/parse_timesforthetimes.py turns the blog into clue numbers, directions
and answers; numbering is a function of the black squares, so running it
backwards recovers the grid. tools/reconstruct_grid.py does that and returns
every grid that would have printed the same light list, which for a few
puzzles is more than one. The answers settle those: a candidate grid is only
right if the answers written into it agree wherever two lights cross, and a
wrong candidate puts different letters in the same square.

A puzzle that reconstructs to nothing is a light list with a hole in it — a
blog post that skipped an entry, or typed one wrong — not a grid that defies
numbering. One wrong light is found when freeing it lands on a single grid;
anything more is counted and named, never guessed at.

Reads the records parse_timesforthetimes.py writes; no network, no solving.
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parse_timesforthetimes as parser
import reconstruct_grid as rg

CACHE = Path.home() / "cryptic-setter-data" / "timesforthetimes"
PARSED = CACHE / "parsed.jsonl"
OUT = CACHE / "grids.jsonl"
#: Every puzzle TRIED, with the budget it was tried at. Resuming off the grids
#: alone re-grinds the failures on every relaunch, and the failures are the
#: expensive ones — a 23x23 Jumbo spends the whole budget and finds nothing, so
#: the puzzles a restart repeats are exactly the ones it can least afford.
ATTEMPTS = CACHE / "attempts.jsonl"

#: Blocked grids only, and their size. Mephisto and the Club Monthly are
#: BARRED puzzles — thick lines between cells, no black squares at all — so
#: numbering is not a function of anything this module can invert.
SIZE = {
    "Daily Cryptic": 15,
    "Quick Cryptic": 13,
    "Weekend Cryptic": 15,
    "Jumbo Cryptic": 23,
}


def printed(rec):
    """The entries in printed order: by number, across before down."""
    order = {"across": 0, "down": 1}
    return sorted(rec["entries"], key=lambda e: (e["number"], order[e["direction"]]))


def triples(rec):
    """The light list a reader of the blog has, in printed order."""
    return [(e["number"], e["direction"], len(e["answer"])) for e in printed(rec)]


def answers_fit(grid, rec):
    """Do this puzzle's answers write into this grid without contradiction?"""
    lights = rg.light_cells(grid)
    seen = {}
    for e in rec["entries"]:
        cells = lights.get((e["number"], e["direction"]))
        if cells is None or len(cells) != len(e["answer"]):
            return False
        for cell, letter in zip(cells, e["answer"]):
            if seen.setdefault(cell, letter) != letter:
                return False
    return True


#: How hard to look before giving up on one puzzle. A search that runs out
#: of nodes is reported as `truncated`, never as `no grid`: the difference is
#: a budget we chose and a light list the blog got wrong, and only one of them
#: is worth re-reading the post over. Measured on a 120-puzzle sample: 400k
#: left 28% truncated, 6M leaves 9% and costs about 17 seconds a puzzle. This
#: is a batch job nobody waits on, so it buys the grids.
DEFAULT_MAX_NODES = 6_000_000

#: The most blocks The Times puts in a line, across or down: 5, over all 4,760
#: grids this module had rebuilt without the cap (Daily, Weekend, Quick and
#: Jumbo; the Jumbos never pass 3). Other papers go higher -- the Independent
#: prints 11 -- so this is the Times' number, not the solver's.
MAX_BLACK_RUN = 5

#: Which search wrote an attempt. A failure logged by an older search is not
#: a failure of this one -- 414 Jumbos this search solves in seconds sat in
#: the log as `truncated` -- so it is tried again. Bump it with the search.
SEARCH = 3


def by_enumeration(rec):
    """(lights, words) with each light its clue's enumeration disagrees with
    given the enumeration's length and no letters, or None if none disagree.

    The clue line and the answer line are typed separately, and when they
    disagree either can be the typo: "STYLE – STYE [fashion, without its L]"
    puts the fodder where the answer goes and "(4)" is right, while "(6-3)"
    over RUNNER-UP is the enumeration mistyped. So this is a second try, taken
    only when the answers as blogged fit no grid.
    """
    if not any(e.get("enumeration") for e in rec["entries"]):
        return None
    leaders = parser.leader_numbers(rec["entries"])
    lights, words, changed = [], [], False
    for e in printed(rec):
        length, word = len(e["answer"]), e["answer"]
        if parser.enum_agrees(e, leaders) is False:
            length = sum(int(n) for n in re.findall(r"\d+", e["enumeration"]))
            word, changed = None, True
        lights.append((e["number"], e["direction"], length))
        words.append(word)
    return (lights, words) if changed else None


def mirrored(grid):
    """Is this grid its own reflection in a diagonal or a centre line?

    The Times' Quick Cryptic prints some grids with no half-turn symmetry at
    all, symmetric instead about a diagonal. A grid with no symmetry of any
    kind is what the search builds round a light the list lost, so an
    asymmetric grid is only taken if it has one of these.
    """
    n = len(grid)
    flips = (lambda y, x: grid[x][y], lambda y, x: grid[n - 1 - x][n - 1 - y],
             lambda y, x: grid[n - 1 - y][x], lambda y, x: grid[y][n - 1 - x])
    return any(all(grid[y][x] == f(y, x) for y in range(n) for x in range(n))
               for f in flips)


#: The search budget for each light one_light_wrong lets go of. Every other
#: light is still held to its answer, so a list with one wrong light finds its
#: grid in a few thousand nodes; this only bounds the lights that are right.
LOOSE_NODES = 200_000


def one_light_wrong(lights, words, n):
    """(grid, why) when freeing exactly one light's length and letters fits
    one grid, whichever light it is freed from; else (None, None).

    One mistyped answer -- STAND-IN for an eight-letter light, PHAROAH across
    a crossing that wants PHARAOH -- is a list no grid fits and one light away
    from the list that fits. Two freed lights that cross at the typo both land
    on the same grid, so agreement is what is asked for, not a single light.
    """
    found, freed = set(), []
    for i, (num, d, _) in enumerate(lights):
        spec, ws = list(lights), list(words)
        spec[i], ws[i] = (num, d, None), None
        sols, info = rg.reconstruct(spec, cols=n, rows=n, limit=2,
                                    max_nodes=LOOSE_NODES, words=ws,
                                    max_black_run=MAX_BLACK_RUN)
        if sols:
            found.update(sols)
            freed.append(f"{num} {d}")
        if len(found) > 1 or (sols and info["truncated"]):
            return None, None
    if len(found) == 1:
        return found.pop(), "one light wrong at " + ", ".join(freed)
    return None, None


def solve(rec, limit=50, max_nodes=DEFAULT_MAX_NODES):
    """(grids, how) for one puzzle. `how` is why it ended where it did.

    The answers and the Times' longest line of blocks go into the search, not
    after it. On the numbering alone a 23x23 spends its budget in its first
    six rows, under a top row of sixteen blocks no Times grid has; with them
    it finishes in seconds. When that search finds nothing it is run again
    without either, because one mistyped answer on the blog is not a missing
    grid, and the cap is a count, not a law.

    When the list fits nothing, three second tries, each taken only if it
    lands on one grid: lights at their enumeration's length, a grid symmetric
    about a diagonal or a centre line instead of a half turn, and one light
    freed. A grid with no symmetry at all is never taken: every one this
    module rebuilt was built round a light the parser had not read.
    """
    n = SIZE[rec["series"]]
    lights = triples(rec)
    words = [e["answer"] for e in printed(rec)]
    try:
        sols, info = rg.reconstruct(lights, cols=n, rows=n, limit=limit,
                                    max_nodes=max_nodes, words=words,
                                    max_black_run=MAX_BLACK_RUN)
    except Exception as e:                       # a light longer than the grid
        return [], f"rejected: {e}"
    if info.get("gaps"):
        return [], "no grid: no light numbered " + ", ".join(map(str, info["gaps"]))
    if sols:
        if info["truncated"]:
            return list(sols), f"{len(sols)} found, search truncated"
        if len(sols) == 1:
            return list(sols), "unique"
        return list(sols), f"{len(sols)} grids fit the answers"
    if info["truncated"]:
        return [], "truncated"
    # Two ways the list can be right and still fit no grid with a half-turn
    # symmetry: an answer blogged at the wrong length under an enumeration
    # that has it right, and a grid symmetric some other way.
    alt = by_enumeration(rec)
    tries = ([(alt, True, "enumeration length")] if alt else []) + [
        ((lights, words), False, "mirror symmetry")]
    if alt:
        tries.append((alt, False, "enumeration length, mirror symmetry"))
    for (spec, ws), symmetric, why in tries:
        sols, info = rg.reconstruct(spec, cols=n, rows=n, limit=limit,
                                    max_nodes=max_nodes, words=ws,
                                    symmetry=symmetric,
                                    max_black_run=MAX_BLACK_RUN)
        if (len(sols) == 1 and not info["truncated"]
                and (symmetric or mirrored(sols[0]))):
            return list(sols), "unique, " + why
    grid, why = one_light_wrong(lights, words, n)
    if grid:
        return [grid], "unique, " + why
    sols, info = rg.reconstruct(lights, cols=n, rows=n, limit=limit,
                                max_nodes=max_nodes)
    if not sols:
        return [], "no grid" if not info["truncated"] else "no grid fits the answers"
    if len(sols) == 1 and not info["truncated"]:
        return list(sols), "unique, answers clash"
    # Every candidate contradicts the answers, which is the opposite of an
    # ambiguous grid: the right grid is not in the list at all, so the light
    # list or one of the answers is wrong.
    return list(sols), f"answers fit none of {len(sols)}"


def solved_already():
    """post_id of every grid already written.

    A pass over the whole corpus is tens of hours and will be killed before it
    ends. Opening the output with "w" threw away everything the last one found,
    so a relaunch starts where the kill landed instead.
    """
    ids = set()
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try:
                ids.add(json.loads(line)["post_id"])
            except ValueError:
                pass           # the last line of a killed run, half written
    return ids


def attempted(max_nodes):
    """post_id of every puzzle this search already tried, at this budget or more.

    Tried at a SMALLER budget is not skipped: raising --max-nodes is how a
    `truncated` puzzle gets another go, and that has to still work. Nor is one
    an older SEARCH tried.
    """
    ids = set()
    if ATTEMPTS.exists():
        for line in ATTEMPTS.open(encoding="utf-8"):
            try:
                a = json.loads(line)
            except ValueError:
                continue       # the last line of a killed run, half written
            if a.get("search") == SEARCH and a.get("max_nodes", 0) >= max_nodes:
                ids.add(a["post_id"])
    return ids


def open_out(fresh):
    """The output handle. Appends, unless asked to start the file over."""
    return OUT.open("w" if fresh else "a", encoding="utf-8")


def has_clues(rec):
    """Did the blogger write out the clues, not just the answers?

    Until about 2016 most posts gave answers and wordplay only. A grid with no
    clues in it is not a puzzle anyone can solve, so it is not worth hours of
    search.
    """
    es = rec["entries"]
    return bool(es) and sum(bool(e.get("clue")) for e in es) >= 0.9 * len(es)


def run(limit_puzzles=None, series=None, write=True, seed=None,
        max_nodes=DEFAULT_MAX_NODES, fresh=False):
    if not PARSED.exists():
        print(f"no records at {PARSED} — run tools/parse_timesforthetimes.py")
        return None
    recs = []
    for line in PARSED.open(encoding="utf-8"):
        r = json.loads(line)
        if (r["series"] in SIZE and (series is None or r["series"] == series)
                and has_clues(r)):
            recs.append(r)
    # Newest first: recent posts write out their clues, and recent puzzles are
    # the ones people look for.
    recs.sort(key=lambda r: (r.get("date") or "", r["post_id"]), reverse=True)
    if seed is not None:
        import random
        random.Random(seed).shuffle(recs)
    done = set() if (fresh or not write) else (solved_already()
                                               | attempted(max_nodes))
    if done:
        recs = [r for r in recs if r["post_id"] not in done]
        print(f"resuming: {len(done)} grid(s) already in {OUT.name}")
    if limit_puzzles:
        recs = recs[:limit_puzzles]

    how = collections.Counter()
    by_series = collections.defaultdict(collections.Counter)
    holes = []
    out = open_out(fresh) if write else None
    log = ATTEMPTS.open("w" if fresh else "a", encoding="utf-8") if write else None
    for rec in recs:
        grids, why = solve(rec, max_nodes=max_nodes)
        # A bucket is a category, not a sentence: the two outcomes that carry
        # a count in their text would otherwise each be their own bucket.
        key = why if why.startswith(("unique", "no grid", "truncated")) else "shortlist"
        for prefix in ("rejected", "answers fit none"):
            key = prefix if why.startswith(prefix) else key
        how[key] += 1
        if log:
            log.write(json.dumps({"post_id": rec["post_id"], "how": why,
                                  "max_nodes": max_nodes,
                                  "search": SEARCH}) + "\n")
            log.flush()
        by_series[rec["series"]][key] += 1
        if not grids:
            holes.append((rec["series"], rec["slug"], len(rec["entries"])))
        elif out and len(grids) == 1:
            out.write(json.dumps({
                "post_id": rec["post_id"], "series": rec["series"],
                "number": rec["number"], "date": rec["date"],
                "grid": list(grids[0]), "how": why}, ensure_ascii=False) + "\n")
            out.flush()   # hours per run; a killed one keeps what it solved
    if out:
        out.close()
    if log:
        log.close()
    return {"n": len(recs), "how": how, "by_series": by_series, "holes": holes}


def report(r):
    n = r["n"]
    pct = lambda k: f"{100.0 * r['how'][k] / n:.1f}%" if n else "-"
    print(f"{n} puzzle(s) tried")
    for k in ("unique", "shortlist", "no grid",
              "truncated", "rejected", "answers fit none"):
        if r["how"][k]:
            print(f"  {r['how'][k]:>6}  {pct(k):>6}  {k}")
    print("\nBY SERIES")
    for s, c in sorted(r["by_series"].items(), key=lambda kv: -sum(kv[1].values())):
        tot = sum(c.values())
        got = c["unique"]
        print(f"  {s:<18} {got:>5} of {tot:>5} pinned down "
              f"({100.0 * got / tot:.0f}%)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, help="try only N puzzles")
    ap.add_argument("--series", choices=sorted(SIZE), help="one series only")
    ap.add_argument("--seed", type=int, help="sample at random with this seed")
    ap.add_argument("--status", action="store_true",
                    help="measure without writing the grids")
    ap.add_argument("--max-nodes", type=int, default=DEFAULT_MAX_NODES,
                    help="search budget per puzzle; a `truncated` count that "
                         "falls when this rises was never a missing grid")
    ap.add_argument("--fresh", action="store_true",
                    help="start the output file over; the default adds to it")
    ap.add_argument("--holes", action="store_true",
                    help="name the puzzles whose light list has a hole in it")
    a = ap.parse_args()
    r = run(a.limit, a.series, write=not a.status, seed=a.seed,
            max_nodes=a.max_nodes, fresh=a.fresh)
    if r is None:
        return 1
    report(r)
    if a.holes:
        print("\nLIGHT LIST INCOMPLETE — the blog post skipped an entry")
        for s, slug, n in r["holes"][:60]:
            print(f"  {n:>3} entries  {s:<18} {slug}")
    if not a.status:
        print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
