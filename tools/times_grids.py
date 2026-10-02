#!/usr/bin/env python3
"""Rebuild the grids a paper does not publish, from a blog's clue lists.

tools/parse_timesforthetimes.py turns the Times blog into clue numbers,
directions and answers, and tools/parse_bigdave44.py the Telegraph's; numbering is a function of the black squares, so running it
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

Reads the records the blog's parser writes beside its cache (`--blog`,
timesforthetimes by default); no network, no solving.
"""
import argparse
import collections
import itertools
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import barred_grid as bg
import fetch_wp_blog
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

#: Each series this module rebuilds, and its size. The Club Monthly Special
#: and the TLS crossword are blocked 15x15s; the Mephisto is BARRED (below).
SIZE = {
    "Mephisto": 12,
    "Daily Cryptic": 15,
    "Quick Cryptic": 13,
    "Weekend Cryptic": 15,
    "Jumbo Cryptic": 23,
    "Monthly Club Special": 15,
    "TLS Crossword": 15,
    # fifteensquared's category, for tools/ft_puzzles.py.
    "FT": 15,
    # tools/indy_puzzles.py's series keys, off the same blog.
    "independent": 15,
    "indysunday": 15,
    # tools/parse_bigdave44.py's series keys.
    "telegraph": 15,
    "toughie": 15,
    "sundaytel": 15,
    "sundaytough": 15,
    # tools/file_georgeho_puzzles.py's series keys, the rest of georgeho's.
    "cryptic": 15,
    "everyman": 15,
    "times": 15,
    "timesquick": 13,
    "timesjumbo": 23,
    "sundaytimes": 15,
    "timesclub": 15,
    "tls": 15,
    "mephisto": 12,
}

#: The BARRED series: thick lines between cells and no black squares, so the
#: numbering alone fixes nothing, but every cell holds a letter and the
#: answers pin the bars down (tools/barred_grid.py).
BARRED = {"Mephisto", "mephisto"}


#: A 15x15 holds at most this many lights; a Weekend post with more is the
#: Sunday Times's Christmas Jumbo, printed at the Jumbo's 23x23.
MOST_LIGHTS_15 = 38
#: A 23x23 Jumbo holds at most this many lights (every one filed tops out at
#: 62); a Jumbo with more is a Superjumbo, printed at SUPERJUMBO. Jumbo 1423,
#: 90 clues for the crossword's 90 years, is 27x27 in the Times's own feed.
MOST_LIGHTS_23 = 70
SUPERJUMBO = 27
JUMBOS = {"Jumbo Cryptic", "timesjumbo"}


def size(rec):
    """The grid's side for this record: its series', but a Weekend post with
    more entries than a 15x15 holds is a Jumbo, and a Jumbo with more than a
    23x23 holds is a Superjumbo."""
    if rec["series"] == "Weekend Cryptic" and len(rec["entries"]) > MOST_LIGHTS_15:
        return SIZE["Jumbo Cryptic"]
    if rec["series"] in JUMBOS and len(rec["entries"]) > MOST_LIGHTS_23:
        return SUPERJUMBO
    return SIZE[rec["series"]]


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
        if cells is None:
            return False
        if not e["answer"]:
            continue       # a blank answer, left for the answer fill
        if len(cells) != len(e["answer"]):
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

#: The most blocks a paper puts in a line, across or down, by record label.
#: The Times: 5, over all 4,760 grids this module had rebuilt without the cap
#: (Daily, Weekend, Quick and Jumbo; the Jumbos never pass 3). The FT: 7, over
#: 110 rebuilt without it. Other papers go higher -- the Independent prints 11
#: -- so each is its paper's number, not the solver's. The Guardian's (cryptic,
#: everyman) has never been counted, so it goes uncapped.
MAX_BLACK_RUN = {"FT": 7, "cryptic": 15, "everyman": 15}
TIMES_BLACK_RUN = 5


#: A puzzle's whole budget, in searches of --max-nodes each. solve() runs
#: up to a dozen searches on a list no grid fits (retries, every freed light,
#: every split of a linked answer), and a 23x23 Christmas Jumbo spent ten
#: silent minutes in them; this is the ceiling over all of them together.
PUZZLE_SEARCHES = 4


class Budget:
    """The nodes one puzzle may still spend, over every search solve() runs,
    and a log line per search naming the post, so a slow one shows where it is."""

    def __init__(self, nodes, label="", log=None):
        self.left, self.label = nodes, label
        self.log = log if log is not None else sys.stderr
        self.spent_at = None

    def search(self, stage, spec, max_nodes, quiet=False, **kw):
        """rg.reconstruct, allowed at most what this puzzle has left. A search
        given less than it asked for and running out reads as truncated."""
        allowed = min(max_nodes, self.left)
        if allowed <= 0:
            self.spent_at = self.spent_at or stage
            return [], {"nodes": 0, "truncated": True}
        t = time.monotonic()
        sols, info = rg.reconstruct(spec, max_nodes=allowed, **kw)
        self.left -= info.get("nodes", 0)
        if info.get("truncated") and allowed < max_nodes:
            self.spent_at = self.spent_at or stage
        if not quiet:
            self.note(f"{stage}: {len(sols)} grid(s), {info.get('nodes', 0)} nodes"
                      + (", truncated" if info.get("truncated") else "")
                      + f", {time.monotonic() - t:.1f}s")
        return sols, info

    def note(self, text):
        if self.log:
            print(f"  {self.label} {text}", file=self.log, flush=True)

    def spent(self):
        return self.left <= 0 or self.spent_at is not None


def black_run(rec):
    return MAX_BLACK_RUN.get(rec["series"], TIMES_BLACK_RUN)


def by_enumeration(rec):
    """(lights, words) with each light its clue's enumeration disagrees with
    given the enumeration's length and no letters, or None if none disagree.

    The clue line and the answer line are typed separately, and when they
    disagree either can be the typo: "STYLE – STYE [fashion, without its L]"
    puts the fodder where the answer goes and "(4)" is right, while "(6-3)"
    over RUNNER-UP is the enumeration mistyped. So this is a second try, taken
    only when the answers as blogged fit no grid.

    An answer shorter than a phrase's count, and no shorter than its first
    word, was cut off at a break (georgeho stores WORST for WORST-CASE
    SCENARIO, GET ONE for GET ONE'S KNICKERS IN A TWIST): its letters still
    start the light. Unwritten, a Jumbo's three long lights leave a search
    with too few letters to finish (timesjumbo-1428).
    """
    if not any(e.get("enumeration") for e in rec["entries"]):
        return None
    leaders = parser.leader_numbers(rec["entries"])
    lights, words, changed = [], [], False
    for e in printed(rec):
        length, word = len(e["answer"]), e["answer"]
        if parser.enum_agrees(e, leaders) is False:
            parts = [int(n) for n in re.findall(r"\d+", e["enumeration"])]
            length, changed = sum(parts), True
            cut = len(parts) > 1 and parts[0] <= len(word) < length
            word = word if cut else None
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


def one_light_wrong(lights, words, n, cap=TIMES_BLACK_RUN, budget=None):
    """(grid, why) when freeing exactly one light's length and letters fits
    one grid, whichever light it is freed from; else (None, None).

    One mistyped answer -- STAND-IN for an eight-letter light, PHAROAH across
    a crossing that wants PHARAOH -- is a list no grid fits and one light away
    from the list that fits. Two freed lights that cross at the typo both land
    on the same grid, so agreement is what is asked for, not a single light.
    """
    budget = budget or Budget(len(lights) * LOOSE_NODES, log=False)
    found, freed, t, nodes = set(), [], time.monotonic(), budget.left
    for i, (num, d, _) in enumerate(lights):
        spec, ws = list(lights), list(words)
        spec[i], ws[i] = (num, d, None), None
        sols, info = budget.search("one light freed", spec, LOOSE_NODES, quiet=True,
                                   cols=n, rows=n, limit=2, words=ws,
                                   max_black_run=cap)
        if budget.spent():
            budget.note(f"one light freed: budget spent after {i} of {len(lights)} lights")
            return None, None
        if sols:
            found.update(sols)
            freed.append(f"{num} {d}")
        if len(found) > 1 or (sols and info["truncated"]):
            return None, None
    budget.note(f"one light freed: {len(lights)} searches, {len(found)} grid(s), "
                f"{nodes - budget.left} nodes, {time.monotonic() - t:.1f}s")
    if len(found) == 1:
        return found.pop(), "one light wrong at " + ", ".join(freed)
    return None, None


def numbering_faults(lights, words):
    """Indices of the lights whose number the list itself contradicts: two
    lights one direction numbers alike, an across and a down sharing a number
    whose answers start with different letters, and the lights numbered either
    side of a number no light carries."""
    at = collections.defaultdict(list)
    for i, (num, _d, _n) in enumerate(lights):
        at[num].append(i)
    bad = set()
    for ix in at.values():
        dirs = [lights[i][1] for i in ix]
        firsts = {words[i][0] for i in ix if words[i]}
        if len(set(dirs)) < len(dirs) or len(firsts) > 1:
            bad.update(ix)
    for gap in set(range(1, max(at, default=0) + 1)) - set(at):
        bad.update(at.get(gap - 1, []) + at.get(gap + 1, []))
    return sorted(bad)


def one_number_wrong(lights, words, n, cap=TIMES_BLACK_RUN, budget=None):
    """The one grid that fits when exactly one light numbering_faults() names
    has its number freed, whichever of them it is; else None.

    A light printed under the wrong number -- 14-down MALONE under 14-across
    HARPSICHORD, two 52-acrosses and no 53 -- is a list no grid fits, and no
    grid fits it with the light's letters freed either, because the number
    still pins where the light starts. Its length and letters are right, so
    they stay; only the number goes.
    """
    budget = budget or Budget(len(lights) * LOOSE_NODES, log=False)
    found, nodes, t = set(), budget.left, time.monotonic()
    faults = numbering_faults(lights, words)
    for i in faults:
        spec = list(lights)
        spec[i] = (None,) + tuple(lights[i][1:])
        try:
            sols, info = budget.search("one number freed", spec, LOOSE_NODES, quiet=True,
                                       cols=n, rows=n, limit=2, words=words,
                                       max_black_run=cap)
        except ValueError:                   # another light still numbered twice
            continue
        if budget.spent():
            budget.note(f"one number freed: budget spent after {faults.index(i)} of "
                        f"{len(faults)} lights")
            return None
        found.update(sols)
        if len(found) > 1 or (sols and info["truncated"]):
            return None
    budget.note(f"one number freed: {len(faults)} searches, {len(found)} grid(s), "
                f"{nodes - budget.left} nodes, {time.monotonic() - t:.1f}s")
    return found.pop() if len(found) == 1 else None


def _written(grid, entries):
    """Do these answers write into the grid's lights without a clash? An
    answer shorter than its light (georgeho's TAM for TAM-O'-SHANTER) is
    written from the light's first square."""
    lights, seen = rg.light_cells(grid), {}
    for e in entries:
        cells = lights.get((e["number"], e["direction"]))
        if cells is None or len(e["answer"]) > len(cells):
            return False
        for cell, letter in zip(cells, e["answer"]):
            if seen.setdefault(cell, letter) != letter:
                return False
    return True


def numbered_by(rec, grid):
    """rec, or rec with the one light it misnumbers given the number the grid
    gives it (one_number_wrong's grid)."""
    lights = rg.light_cells(grid)
    named = collections.Counter((e["number"], e["direction"]) for e in rec["entries"])
    unnamed = [k for k in lights if k not in named]
    if len(unnamed) != 1 or len(rec["entries"]) != len(lights):
        return rec
    (num, way), = unnamed
    fits = []
    for i, e in enumerate(rec["entries"]):
        if e["direction"] == way:
            entries = list(rec["entries"])
            entries[i] = dict(e, number=num)
            if _written(grid, entries):
                fits.append(entries)
    return {**rec, "entries": fits[0]} if len(fits) == 1 else rec


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
    when it does not. Only real words that match the enumeration count; a
    phrase is real when each of its words is. An enumeration that counts the
    blogged answer, not the light, was typed over the same slip and says
    nothing.

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
        pool = set(vocab.get(n, ()))
        # One letter dropped: the lexicon has no phrases, so TAKES STOCK under
        # TAKESTOCK is built from the blogged letters, not looked up.
        if n == len(blogged) + 1:
            pool |= {blogged[:i] + c + blogged[i:] for i in range(n)
                     for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    # A count typed over the same short answer -- THEOREM (7) in an
    # eight-letter light -- is the blogger's slip twice, not the paper's count.
    enum = entry.get("enumeration") or ""
    trust_enum = not (len(blogged) != n
                      and sum(int(d) for d in re.findall(r"\d+", enum)) == len(blogged))
    out = set()
    for w in pool:
        if len(w) != n or any(w[i] != c for i, c in fixed.items()):
            continue
        if len(blogged) != n and not _subsequence(
                [w[i] for i in range(n) if i not in fixed], blogged):
            continue
        if not _real(w, _word_count(entry), vocab):
            continue
        if not trust_enum or parser.enum_agrees(dict(entry, answer=w),
                                                leaders) is not False:
            out.add(w)
    return out


def _word_count(entry):
    """How many words the blog wrote the answer as: its spacing, else its count."""
    spaced = entry.get("answer_spaced")
    if spaced:
        return len(re.findall(r"[A-Z']+", spaced.upper()))
    return max(1, len(re.findall(r"\d+", entry.get("enumeration") or "")))


def _real(w, words, vocab):
    """Is `w` a real word, or a phrase of `words` real words (TAKES STOCK)?
    The lexicon holds no phrases, so a phrase is read word by word."""
    if w in vocab.get(len(w), ()):
        return True
    if words < 2:
        return False

    def split(rest, k):
        if k == 1:
            return rest in vocab.get(len(rest), ())
        return any(rest[:i] in vocab.get(i, ()) and split(rest[i:], k - 1)
                   for i in range(2, len(rest) - 1))
    return split(w, words)


def settle(grid, rec, vocab):
    """(corrections, None) when the answers as blogged fit this grid, or can be
    made to by correcting the fewest answers in exactly one way; else
    (None, why).

    A grid is taken despite an answer that disagrees with it -- PHAROAH across
    a crossing that wants PHARAOH, STAND-IN in an eight-letter light -- and
    the answer is still the blogger's typo. A correction is only made when it
    is determined: each letter is a correct crossing's or the blogger's own,
    and the result is a real word of the light's enumeration. An answer the
    grid's light is a different length from is wrong whatever it should be,
    so when no single word corrects it, it is corrected to blank ("") for the
    answer fill, and the puzzle stands. Any other answer that two corrections
    fit, or none, refuses the puzzle. A blank answer is no answer: it is never
    corrected. Each correction is {"number", "direction", "blogged", "answer"}.
    """
    lights = rg.light_cells(grid)
    entries = {(e["number"], e["direction"]): e for e in rec["entries"]}
    if set(entries) != set(lights):
        odd = sorted(set(entries) ^ set(lights))
        return None, LIGHTS_DIFFER + ", ".join(map(_key, odd))
    forced = {k for k, e in entries.items()
              if e["answer"] and len(e["answer"]) != len(lights[k])}
    at = collections.defaultdict(list)
    for k, cells in lights.items():
        if k not in forced and entries[k]["answer"]:
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
                     if k not in wrong and entries[k]["answer"]
                     for i, c in enumerate(cells)}
            fix = {}
            for k in sorted(wrong):
                ws = _fixes(lights[k], known, entries[k]["answer"], entries[k],
                            leaders, vocab)
                if len(ws) != 1 and k in forced:
                    fix[k] = ""
                    continue
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


def solve_barred(rec, n):
    """solve() for a barred grid: its bars, as the grid rows light_cells reads."""
    placements = bg.solve(rec["entries"], size=n)
    if placements is None:
        return [], "rejected: a light shorter than two letters, or numbered twice"
    if not placements:
        return [], "no grid"
    if len(placements) > 1:
        return [], "2 grids fit the answers"
    return [tuple(bg.layout(rec["entries"], placements[0], size=n)[1])], "unique"


#: The most splits of a record's linked answers solve() tries. Each is one
#: search with every other answer written in, which fails in a fraction of a
#: second, so this is cheap; 16 refused 41 bigdave44 posts.
MAX_SPLITS = 64


def splits(group):
    """Every way to share a linked answer's words out among its lights, in
    order and at word breaks: [[(light, letters), ...], ...]. The words are
    the printed answer's, or where the parser kept only its letters, the
    enumeration's counts cut from them."""
    if group.get("answer_printed"):
        words = parser.answer_words(group["answer_printed"])
    else:
        counts = [int(n) for n in re.findall(r"\d+", group.get("enumeration") or "")]
        letters = group.get("answer") or ""
        if sum(counts) != len(letters):
            return []
        words, at = [], 0
        for n in counts:
            words.append(letters[at:at + n])
            at += n
    lights = [tuple(x) for x in group["lights"]]
    out = []
    for cuts in itertools.combinations(range(1, len(words)), len(lights) - 1):
        bounds = (0, *cuts, len(words))
        out.append([(light, "".join(words[a:b]))
                    for light, a, b in zip(lights, bounds, bounds[1:])])
    return out


def with_split(rec, choice):
    """rec with one split of each linked answer the blog left unsplit, and
    no longer unsplit."""
    entries = list(rec["entries"])
    numbers = collections.Counter(e["number"] for e in entries)
    numbers.update(n for pieces in choice for (n, _d), _l in pieces)
    for group, pieces in zip(rec["unsplit"], choice):
        (leader, way), _ = pieces[0]
        # The pointer names the direction where the number has both
        # (toughie-641's 1-down SICK, beside 1-across), and the leader keeps
        # the answer as printed, whose word breaks are the group's count
        # (toughie-1067's FIRST-DEGREE MURDER typed (5-6)).
        see = f"See {leader}" + (f" {way}" if numbers[leader] > 1 else "")
        for i, ((n, d), letters) in enumerate(pieces):
            entries.append({"number": n, "direction": d, "answer": letters,
                            "clue": group.get("clue") if i == 0 else see,
                            "enumeration": group["enumeration"] if i == 0 else None,
                            **({"answer_spaced": group["answer_printed"]}
                               if i == 0 and group.get("answer_printed") else {})})
    return {**{k: v for k, v in rec.items() if k != "unsplit"}, "entries": entries}


def split_by(rec, grid):
    """rec with its linked answers shared out as the grid's lights have them;
    rec as it is when no split fits the grid."""
    if not rec.get("unsplit"):
        return rec
    for choice in itertools.product(*(splits(g) for g in rec["unsplit"])):
        whole = with_split(rec, choice)
        if answers_fit(grid, whole):
            return whole
    return rec


def as_headed(rec):
    """rec with each light whose suffix contradicts its heading (the parser's
    `heading`) turned to the heading's direction, or None if it has none."""
    if not any(e.get("heading") for e in rec["entries"]):
        return None
    return {**rec, "entries": [
        {**{k: v for k, v in e.items() if k != "heading"},
         "direction": e.get("heading") or e["direction"]} for e in rec["entries"]]}


def headed_by(rec, grid):
    """rec, or as_headed(rec) when only that names the grid's lights."""
    flipped = as_headed(rec)
    if flipped is None:
        return rec
    lights = set(rg.light_cells(grid))
    named = lambda r: {(e["number"], e["direction"]) for e in r["entries"]}
    return flipped if named(rec) != lights and named(flipped) == lights else rec


def solve_linked(rec, limit, max_nodes, budget):
    """solve() for a record holding a linked answer the post prints whole:
    every split at a word break is rebuilt, and one split landing on exactly
    one grid is the split. The chosen split is written into rec's entries,
    which is what the grid row and the filer read."""
    choices = list(itertools.islice(
        itertools.product(*(splits(g) for g in rec["unsplit"])), MAX_SPLITS + 1))
    if len(choices) > MAX_SPLITS:
        return [], "rejected: too many ways to split its linked answers"
    found = []
    for choice in choices:
        grids, why = solve(with_split(rec, choice), limit=limit, max_nodes=max_nodes,
                           thorough=False, budget=budget)
        if budget.spent():
            return [], f"truncated: puzzle budget spent at {budget.spent_at or 'a split'}"
        if grids:
            found.append((choice, grids, why))
    if len(found) != 1 or len(found[0][1]) != 1:
        return [], ("no grid fits any split of its linked answers" if not found
                    else f"shortlist: {len(found)} splits of its linked answers fit")
    choice, grids, why = found[0]
    rec["entries"] = with_split(rec, choice)["entries"]
    return grids, why + ", linked answer split by the grid"


def renumbered(rec, lights, words, n, budget):
    """(grids, how) for a list numbering_faults() faults, as one_number_wrong
    rebuilds it, as blogged and then at its enumeration's lengths; the grid's
    number is written into rec's entries. ([], why) when neither does."""
    for spec, ws in [(lights, words)] + [x for x in [by_enumeration(rec)] if x]:
        grid = one_number_wrong(spec, ws, n, black_run(rec), budget)
        if budget.spent():
            return [], f"truncated: puzzle budget spent at {budget.spent_at or 'one number freed'}"
        fixed = numbered_by(rec, grid) if grid else rec
        if fixed is not rec:
            moved = [f"{e['number']} {e['direction']} to {f['number']}"
                     for e, f in zip(rec["entries"], fixed["entries"]) if e != f]
            rec["entries"] = fixed["entries"]
            return [grid], "unique, number freed: " + ", ".join(moved)
    return [], "no grid"


def solve(rec, limit=50, max_nodes=DEFAULT_MAX_NODES, thorough=True, budget=None):
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
    module rebuilt was built round a light the parser had not read. Not
    `thorough`, the enumeration's lengths are the only second try: the two
    unsymmetric searches and the freed lights are each a whole budget, which
    solve_linked() would spend once per split.

    Every search draws on one `budget`, PUZZLE_SEARCHES searches of
    `max_nodes` by default; a puzzle that spends it is `truncated`.
    """
    if budget is None:
        budget = Budget(PUZZLE_SEARCHES * max_nodes,
                        f"post {rec.get('post_id', '?')}")
    if rec.get("unsplit"):
        return solve_linked(rec, limit, max_nodes, budget)
    n = size(rec)
    if rec["series"] in BARRED:
        return solve_barred(rec, n)
    lights = triples(rec)
    words = [e["answer"] for e in printed(rec)]
    try:
        sols, info = budget.search("answers in", lights, max_nodes, cols=n, rows=n,
                                   limit=limit, words=words,
                                   max_black_run=black_run(rec))
        refused = None
    except Exception as e:                       # a light longer than the grid
        sols, info, refused = [], {"truncated": False}, f"rejected: {e}"
    if not sols and not info["truncated"] and numbering_faults(lights, words):
        grids, why = renumbered(rec, lights, words, n, budget)
        if grids or budget.spent():
            return grids, why
    if refused:
        return [], refused
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
    tries = [(alt, True, "enumeration length")] if alt else []
    if thorough:
        tries.append(((lights, words), False, "mirror symmetry"))
    if alt and thorough:
        tries.append((alt, False, "enumeration length, mirror symmetry"))
    for (spec, ws), symmetric, why in tries:
        sols, info = budget.search(why, spec, max_nodes, cols=n, rows=n,
                                   limit=limit, words=ws, symmetry=symmetric,
                                   max_black_run=black_run(rec))
        if budget.spent():
            return [], f"truncated: puzzle budget spent at {budget.spent_at}"
        if (len(sols) == 1 and not info["truncated"]
                and (symmetric or mirrored(sols[0]))):
            return list(sols), "unique, " + why
    flipped = as_headed(rec)
    if flipped:
        grids, why = solve(flipped, limit=limit, max_nodes=max_nodes, thorough=False,
                           budget=budget)
        if budget.spent():
            return [], f"truncated: puzzle budget spent at {budget.spent_at}"
        if len(grids) == 1 and why.startswith("unique"):
            rec["entries"] = flipped["entries"]
            return grids, why + ", directions as headed"
    if not thorough:
        return [], "no grid"
    grid, why = one_light_wrong(lights, words, n, black_run(rec), budget)
    if grid:
        return [grid], "unique, " + why
    if budget.spent():
        return [], f"truncated: puzzle budget spent at {budget.spent_at or 'one light freed'}"
    sols, info = budget.search("numbering only", lights, max_nodes, cols=n, rows=n,
                               limit=limit)
    if budget.spent():
        return [], f"truncated: puzzle budget spent at {budget.spent_at}"
    if not sols:
        return [], "no grid" if not info["truncated"] else "no grid fits the answers"
    if len(sols) == 1 and not info["truncated"]:
        return list(sols), "unique, answers clash"
    # Every candidate contradicts the answers, which is the opposite of an
    # ambiguous grid: the right grid is not in the list at all, so the light
    # list or one of the answers is wrong.
    return list(sols), f"answers fit none of {len(sols)}"


def solved_already(out=None):
    """post_id of every grid already written.

    A pass over the whole corpus is tens of hours and will be killed before it
    ends. Opening the output with "w" threw away everything the last one found,
    so a relaunch starts where the kill landed instead.
    """
    out = out or OUT
    ids = set()
    if out.exists():
        for line in out.open(encoding="utf-8"):
            try:
                ids.add(json.loads(line)["post_id"])
            except ValueError:
                pass           # the last line of a killed run, half written
    return ids


def attempted(attempts=None, retry=None):
    """post_id of every puzzle with an attempt on record.

    A run tries only posts that have none: a change to the search, settle(),
    the budget or the settled answers never re-tries old posts by itself; it
    is retried once, by hand, with `retry`. That is a tuple of `how`
    prefixes ("refused", "truncated", "no grid", ...), and a post whose latest
    attempt starts with one of them is left out of the set, so it is tried
    again; an empty tuple leaves out every one.
    """
    attempts = attempts or ATTEMPTS
    last = {}
    if attempts.exists():
        for line in attempts.open(encoding="utf-8"):
            try:
                a = json.loads(line)
            except ValueError:
                continue       # the last line of a killed run, half written
            last[a["post_id"]] = a.get("how", "")
    if retry is None:
        return set(last)
    return {pid for pid, how in last.items()
            if retry and not how.startswith(tuple(retry))}


def open_out(fresh, out=None):
    """The output handle. Appends, unless asked to start the file over."""
    return (out or OUT).open("w" if fresh else "a", encoding="utf-8")


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
                                      "max_nodes": DEFAULT_MAX_NODES}) + "\n")
    return {"kept": len(kept), "fixed": fixed, "refused": refused}


def run(limit_puzzles=None, series=None, write=True, seed=None,
        max_nodes=DEFAULT_MAX_NODES, fresh=False, where=None, solver=None,
        retry=None):
    """Rebuild every parsed puzzle not yet tried, newest first, plus, with
    `retry`, the failures attempted() lets back in.

    `where` is another blog's cache directory, holding its own parsed.jsonl,
    grids.jsonl and attempts.jsonl; the answers settled for this blog's posts
    are not applied there. `solver` stands in for solve()."""
    parsed, out_path, attempts = ((where / "parsed.jsonl", where / "grids.jsonl",
                                   where / "attempts.jsonl") if where
                                  else (PARSED, OUT, ATTEMPTS))
    solver = solver or solve
    if not parsed.exists():
        print(f"no records at {parsed} — run its parser first")
        return None
    every = [json.loads(line) for line in parsed.open(encoding="utf-8")]
    recs = [r for r in every if r["series"] in SIZE
            and (series is None or r["series"] == series) and has_clues(r)]
    vocab = vocabulary(every)
    settled = {} if where else settled_answers()
    del every
    # Newest first: recent posts write out their clues, and recent puzzles are
    # the ones people look for.
    recs.sort(key=lambda r: (r.get("date") or "", r["post_id"]), reverse=True)
    if seed is not None:
        import random
        random.Random(seed).shuffle(recs)
    done = set() if (fresh or not write) else (
        solved_already(out_path) | attempted(attempts, retry))
    if done:
        recs = [r for r in recs if r["post_id"] not in done]
        print(f"resuming: {len(done)} puzzle(s) already tried, per {attempts.name}")
    if limit_puzzles:
        recs = recs[:limit_puzzles]

    how = collections.Counter()
    by_series = collections.defaultdict(collections.Counter)
    holes = []
    out = open_out(fresh, out_path) if write else None
    log = attempts.open("w" if fresh else "a", encoding="utf-8") if write else None
    for i, rec in enumerate(recs, 1):
        rec, made = amend(rec, settled)
        print(f"[{i}/{len(recs)}] post {rec['post_id']} {rec['series']} "
              f"{rec.get('number')}: {len(rec['entries'])} lights",
              file=sys.stderr, flush=True)
        t = time.monotonic()
        grids, why = solver(rec, max_nodes=max_nodes)
        print(f"  post {rec['post_id']} {why}, {time.monotonic() - t:.1f}s",
              file=sys.stderr, flush=True)
        fixes = []
        if len(grids) == 1:
            fixes, refused = settle(grids[0], rec, vocab)
            if refused:
                grids, why = [], refused
        # A bucket is a category, not a sentence: the two outcomes that carry
        # a count in their text would otherwise each be their own bucket.
        key = why if why.startswith(("unique", "no grid", "truncated")) else "shortlist"
        key = "unique, second try" if key.startswith("unique,") else key
        key = "truncated" if key.startswith("truncated") else key
        key = ("light missing" if key.startswith("no grid: no light") else
               "no grid" if key.startswith("no grid") else key)
        for prefix in ("rejected", "answers fit none", "refused"):
            key = prefix if why.startswith(prefix) else key
        how[key] += 1
        if log:
            log.write(json.dumps({"post_id": rec["post_id"], "how": why,
                                  "max_nodes": max_nodes}) + "\n")
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
    for k in ("unique", "unique, second try", "shortlist", "light missing", "no grid",
              "truncated",
              "rejected", "answers fit none", "refused"):
        if r["how"][k]:
            print(f"  {r['how'][k]:>6}  {pct(k):>6}  {k}")
    print("\nBY SERIES")
    for s, c in sorted(r["by_series"].items(), key=lambda kv: -sum(kv[1].values())):
        tot = sum(c.values())
        got = c["unique"] + c["unique, second try"]
        print(f"  {s:<18} {got:>5} of {tot:>5} pinned to one grid "
              f"({100.0 * got / tot:.0f}%)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--blog", choices=sorted(fetch_wp_blog.BLOGS), default="timesforthetimes")
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
    ap.add_argument("--retry-failed", nargs="*", metavar="HOW",
                    help="also try again the puzzles with no grid whose last "
                         "attempt's outcome starts with a HOW (refused, "
                         "truncated, 'no grid', ...), or every one if none is "
                         "given. A run never retries by itself: a change that "
                         "could fix old failures runs this once")
    ap.add_argument("--resettle", action="store_true",
                    help="correct or refuse the grids already written, "
                         "against the parsed records as they are now")
    a = ap.parse_args()
    where = None if a.blog == "timesforthetimes" else fetch_wp_blog.BLOGS[a.blog].cache
    if a.resettle and where:
        ap.error("--resettle reads the Times blog's records only")
    if a.resettle:
        r = resettle()
        for pid, why in sorted(r["refused"].items()):
            print(f"  {pid:>6}  {why}")
        print(f"{r['kept']} grid(s) kept, {r['fixed']} answer(s) corrected, "
              f"{len(r['refused'])} refused; wrote {OUT}")
        return 0
    r = run(a.limit, a.series, write=not a.status, seed=a.seed,
            max_nodes=a.max_nodes, fresh=a.fresh, where=where, retry=a.retry_failed)
    if r is None:
        return 1
    report(r)
    if a.holes:
        print("\nLIGHT LIST INCOMPLETE — the blog post skipped an entry")
        for s, slug, n in r["holes"][:60]:
            print(f"  {n:>3} entries  {s:<18} {slug}")
    if not a.status:
        print(f"\nwrote {(where / 'grids.jsonl') if where else OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
