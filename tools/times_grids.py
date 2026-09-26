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

A grid taken although one of the blog's answers disagrees with it carries the
corrected answer in its row, and read through answers() that is what gets
published. A typo nothing determines refuses the puzzle instead.

Reads the records parse_timesforthetimes.py writes; no network, no solving.
"""
import argparse
import collections
import hashlib
import itertools
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


LEXICON = Path(__file__).resolve().parent / "data" / "lexicon.tsv"
#: Answers settled by reading the wordplay, where the grid allowed several
#: fixes or none the word lists knew.
ANSWERS = Path(__file__).resolve().parent / "data" / "times_answers.json"


def settled_answers():
    """{post_id: {(number, direction): answer}} from ANSWERS."""
    raw = json.loads(ANSWERS.read_text(encoding="utf-8")) if ANSWERS.exists() else {}
    out = {}
    for pid, lights in raw.items():
        if pid.startswith("_"):
            continue
        out[int(pid)] = {(int(k.split()[0]), k.split()[1]): v["answer"]
                         for k, v in lights.items() if not k.startswith("_")}
    return out


def amend(rec, settled):
    """(rec with its settled answers in, the corrections that makes)."""
    fix = settled.get(rec["post_id"])
    if not fix:
        return rec, []
    entries, made = [], []
    for e in rec["entries"]:
        k = (e["number"], e["direction"])
        if k in fix and fix[k] != e["answer"]:
            made.append({"number": k[0], "direction": k[1],
                         "blogged": e["answer"], "answer": fix[k]})
            e = dict(e, answer=fix[k])
        entries.append(e)
    return dict(rec, entries=entries), made


def vocabulary(recs):
    """Every word a correction may be, by length: the lexicon's, and every
    answer the blog gave anywhere. The lexicon has no phrases (URSA MINOR) and
    few proper nouns (PHARAOH); the blog has both."""
    words = set()
    if LEXICON.exists():
        for line in LEXICON.open(encoding="utf-8"):
            if not line.startswith("#"):
                words.add(line.split("\t", 1)[0])
    for r in recs:
        words.update(e["answer"] for e in r["entries"])
    by_len = collections.defaultdict(set)
    for w in words:
        by_len[len(w)].add(w)
    return by_len


LIGHTS_DIFFER = "refused: lights differ from the grid at "

#: More wrong answers than this in one grid is a wrong grid, not typos.
MAX_WRONG = 3


def _key(k):
    return f"{k[0]} {k[1]}"


def _subsequence(short, long):
    it = iter(long)
    return all(c in it for c in short)


def _fixes(cells, known, blogged, entry, leaders, vocab):
    """The words one wrong light can be. `known` holds the letters its correct
    crossings put in it; every other letter is the blogger's own -- at the same
    place when the blogged answer has the light's length, and in the same order
    when it does not. Only real words that match the enumeration count.

    The one other correction taken is two adjacent letters typed the wrong way
    round (PHAROAH, GYLPH), and only as the blogger typed every letter: the
    crossing letter that exposes a swap cannot also stand in for the letter
    beside it."""
    n = len(cells)
    fixed = {i: known[c] for i, c in enumerate(cells) if c in known}
    if len(blogged) == n:
        pool = ["".join(fixed.get(i, blogged[i]) for i in range(n))] + [
            blogged[:i] + blogged[i + 1] + blogged[i] + blogged[i + 2:]
            for i in range(n - 1)]
    else:
        pool = vocab.get(n, ())
    out = set()
    for w in pool:
        if len(w) != n or any(w[i] != c for i, c in fixed.items()):
            continue
        if len(blogged) != n and not _subsequence(
                [w[i] for i in range(n) if i not in fixed], blogged):
            continue
        if w in vocab.get(n, ()) and parser.enum_agrees(dict(entry, answer=w),
                                                       leaders) is not False:
            out.add(w)
    return out


def settle(grid, rec, vocab):
    """(corrections, None) when the answers as blogged fit this grid, or can be
    made to by correcting the fewest answers in exactly one way; else
    (None, why).

    A grid is taken despite an answer that disagrees with it -- PHAROAH across
    a crossing that wants PHARAOH, STAND-IN in an eight-letter light -- and
    the answer is still the blogger's typo. A correction is only made when it
    is determined: each letter is a correct crossing's or the blogger's own,
    and the result is a real word of the light's enumeration. When two ways
    of correcting it both give words, or none does, the puzzle is refused.
    Each correction is {"number", "direction", "blogged", "answer"}.
    """
    lights = rg.light_cells(grid)
    entries = {(e["number"], e["direction"]): e for e in rec["entries"]}
    if set(entries) != set(lights):
        odd = sorted(set(entries) ^ set(lights))
        return None, LIGHTS_DIFFER + ", ".join(map(_key, odd))
    forced = {k for k, e in entries.items() if len(e["answer"]) != len(lights[k])}
    at = collections.defaultdict(list)
    for k, cells in lights.items():
        if k not in forced:
            for c, letter in zip(cells, entries[k]["answer"]):
                at[c].append((k, letter))
    edges = {frozenset(k for k, _ in v) for v in at.values()
             if len(v) == 2 and v[0][1] != v[1][1]}
    if not forced and not edges:
        return [], None
    suspects = sorted({k for e in edges for k in e})
    leaders = parser.leader_numbers(rec["entries"])
    for size in range(0, MAX_WRONG - len(forced) + 1):
        covers = [set(c) for c in itertools.combinations(suspects, size)
                  if all(e & set(c) for e in edges)]
        if not covers:
            continue
        outcomes, why, maybe = set(), [], []
        for cover in covers:
            wrong = forced | cover
            known = {c: entries[k]["answer"][i] for k, cells in lights.items()
                     if k not in wrong for i, c in enumerate(cells)}
            fix = {}
            for k in sorted(wrong):
                ws = _fixes(lights[k], known, entries[k]["answer"], entries[k],
                            leaders, vocab)
                if len(ws) > 1:
                    maybe.append(f"{_key(k)} {' or '.join(sorted(ws)[:4])}")
                    break
                if not ws:
                    why.append(f"{_key(k)} {entries[k]['answer']} fits no word")
                    break
                fix[k] = ws.pop()
            else:
                fixed = {"entries": [dict(e, answer=fix.get(k, e["answer"]))
                                     for k, e in entries.items()]}
                if answers_fit(grid, fixed):
                    outcomes.add(tuple(sorted(fix.items())))
                else:
                    why.append("corrected " + ", ".join(map(_key, sorted(wrong)))
                               + " still clash")
        if len(outcomes) == 1 and not maybe:
            return [{"number": k[0], "direction": k[1],
                     "blogged": entries[k]["answer"], "answer": w}
                    for k, w in outcomes.pop()], None
        if outcomes or maybe:
            return None, "refused: answers correct " + " or ".join(sorted(
                ["/".join(f"{_key(k)} {w}" for k, w in o) for o in outcomes] + maybe))
        return None, "refused: " + "; ".join(why)
    return None, f"refused: more than {MAX_WRONG} answers disagree with the grid"


#: Answers the blog misspells in a letter no crossing checks, so the grid
#: cannot prove them wrong; the clue's own wordplay does. Keyed by post id.
MISSPELT = {
    (49822, 33, "down"): "IDEOLOGICAL",   # Jumbo 1756: (Iago cold lie)*, blogged IDEALOGICAL
    (56106, 5, "down"): "ANTEMERIDIEM",   # Jumbo 1798: (entered Miami)*, blogged MERIDIEN
}


def answers(rec, row):
    """This puzzle's entries with the grid row's corrections applied: the
    answers to publish, which are not always the blog's."""
    fix = {(n, d): a for (post, n, d), a in MISSPELT.items() if post == rec["post_id"]}
    fix.update({(c["number"], c["direction"]): c["answer"] for c in row.get("corrections", ())})
    return [dict(e, answer=fix.get((e["number"], e["direction"]), e["answer"]))
            for e in rec["entries"]]


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


def settled_digest(fix):
    """A short hash of one post's settled answers, "" when it has none."""
    if not fix:
        return ""
    lights = sorted((f"{n} {d}", a) for (n, d), a in fix.items())
    return hashlib.sha256(json.dumps(lights).encode()).hexdigest()[:12]


def attempted(max_nodes, settled=None):
    """post_id of every puzzle this search already tried, at this budget or more,
    with the settled answers it has now.

    Tried at a SMALLER budget is not skipped: raising --max-nodes is how a
    `truncated` puzzle gets another go, and that has to still work. Nor is one
    an older SEARCH tried, or one tried before its settled answers last changed.
    """
    settled = settled or {}
    ids = set()
    if ATTEMPTS.exists():
        for line in ATTEMPTS.open(encoding="utf-8"):
            try:
                a = json.loads(line)
            except ValueError:
                continue       # the last line of a killed run, half written
            if (a.get("search") == SEARCH and a.get("max_nodes", 0) >= max_nodes
                    and a.get("settled", "") == settled_digest(settled.get(a["post_id"]))):
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


def row(rec, grid, how, fixes):
    """One line of grids.jsonl. `corrections` is only there when the blog got
    an answer wrong; read the answers through answers(), never off the post."""
    r = {"post_id": rec["post_id"], "series": rec["series"],
         "number": rec["number"], "date": rec["date"], "grid": list(grid),
         "how": how}
    if fixes:
        r["corrections"] = fixes
    return r


def resettle():
    """Correct or refuse every grid already written, against the parsed
    records as they are now. A grid rebuilt before settle() existed carries
    its typos, and a resumed run never looks at it again.

    Rewrites grids.jsonl, dropping each refused grid, and records the refusal
    as that puzzle's attempt so a resumed run does not rebuild it."""
    every = {r["post_id"]: r for r in map(json.loads, PARSED.open(encoding="utf-8"))}
    vocab = vocabulary(every.values())
    settled = settled_answers()
    kept, refused, fixed = [], {}, 0
    for line in OUT.open(encoding="utf-8"):
        try:
            g = json.loads(line)
        except ValueError:
            continue           # the last line of a killed run, half written
        rec = every.get(g["post_id"])
        if rec is None:
            refused[g["post_id"]] = "refused: no parsed record"
            continue
        rec, made = amend(rec, settled)
        fixes, why = settle(g["grid"], rec, vocab)
        if why and why.startswith(LIGHTS_DIFFER):
            continue           # the post parses differently now: rebuild it
        if why:
            refused[g["post_id"]] = why
            continue
        fixes = made + fixes
        fixed += len(fixes)
        kept.append(row(rec, g["grid"], g["how"], fixes))
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept),
                   encoding="utf-8")
    tmp.replace(OUT)
    if refused:
        with ATTEMPTS.open("a", encoding="utf-8") as log:
            for pid, why in refused.items():
                log.write(json.dumps({"post_id": pid, "how": why,
                                      "max_nodes": DEFAULT_MAX_NODES,
                                      "search": SEARCH,
                                      "settled": settled_digest(settled.get(pid))}) + "\n")
    return {"kept": len(kept), "fixed": fixed, "refused": refused}


def run(limit_puzzles=None, series=None, write=True, seed=None,
        max_nodes=DEFAULT_MAX_NODES, fresh=False):
    if not PARSED.exists():
        print(f"no records at {PARSED} — run tools/parse_timesforthetimes.py")
        return None
    every = [json.loads(line) for line in PARSED.open(encoding="utf-8")]
    recs = [r for r in every if r["series"] in SIZE
            and (series is None or r["series"] == series) and has_clues(r)]
    vocab = vocabulary(every)
    settled = settled_answers()
    del every
    # Newest first: recent posts write out their clues, and recent puzzles are
    # the ones people look for.
    recs.sort(key=lambda r: (r.get("date") or "", r["post_id"]), reverse=True)
    if seed is not None:
        import random
        random.Random(seed).shuffle(recs)
    # A changed settled answer is a reason to try its puzzle again; an
    # unchanged one is not.
    done = set() if (fresh or not write) else (
        solved_already() | attempted(max_nodes, settled))
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
        rec, made = amend(rec, settled)
        grids, why = solve(rec, max_nodes=max_nodes)
        fixes = []
        if len(grids) == 1:
            fixes, refused = settle(grids[0], rec, vocab)
            if refused:
                grids, why = [], refused
        # A bucket is a category, not a sentence: the two outcomes that carry
        # a count in their text would otherwise each be their own bucket.
        key = why if why.startswith(("unique", "no grid", "truncated")) else "shortlist"
        for prefix in ("rejected", "answers fit none", "refused"):
            key = prefix if why.startswith(prefix) else key
        how[key] += 1
        if log:
            log.write(json.dumps({"post_id": rec["post_id"], "how": why,
                                  "max_nodes": max_nodes,
                                  "search": SEARCH,
                                  "settled": settled_digest(settled.get(rec["post_id"]))}) + "\n")
            log.flush()
        by_series[rec["series"]][key] += 1
        if not grids:
            holes.append((rec["series"], rec["slug"], len(rec["entries"])))
        elif out and len(grids) == 1:
            out.write(json.dumps(row(rec, grids[0], why, made + fixes),
                                 ensure_ascii=False) + "\n")
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
    for k in ("unique", "shortlist", "no grid", "truncated", "rejected",
              "answers fit none", "refused"):
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
    ap.add_argument("--resettle", action="store_true",
                    help="correct or refuse the grids already written, "
                         "against the parsed records as they are now")
    a = ap.parse_args()
    if a.resettle:
        r = resettle()
        for pid, why in sorted(r["refused"].items()):
            print(f"  {pid:>6}  {why}")
        print(f"{r['kept']} grid(s) kept, {r['fixed']} answer(s) corrected, "
              f"{len(r['refused'])} refused; wrote {OUT}")
        return 0
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
