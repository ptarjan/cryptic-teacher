#!/usr/bin/env python3
"""Fill a British blocked cryptic grid with clueable words.

Step one of a setting pipeline: this produces the GRID and its ANSWERS. A human
(or a later stage) writes the clues from the JSON it emits.

Two things make this more than a crossword-shaped constraint solver:

1. The grid conventions are checked, not assumed. `check_*` functions below each
   enforce one British-cryptic rule and say which one, and a template that fails
   any of them is refused rather than filled. The thresholds were calibrated
   against the 30,0xx Guardian grids already in puzzles/ — see tools/AUTHORING.md.

2. The fill is clueability-aware. A word that interlocks perfectly but offers a
   setter no wordplay is a bad answer, so tools/clueability.py scores every
   candidate and the search both ORDERS by that score and REFUSES anything under
   a floor. `fill()` is a generator with a veto hook, so a clue-writing stage
   that fails on an entry can blacklist it and pull the next fill instead of
   starting the whole search again.

Usage:
  python3 tools/grid_fill.py --size 11 [--seed N] [--out grid.json]
  python3 tools/grid_fill.py --size 11 --list-templates
  python3 tools/grid_fill.py --check-only --size 13
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clueability  # noqa: E402  (same directory, no third-party deps)

TOOLS = Path(__file__).resolve().parent
DATA = TOOLS / "data"
BLACKLIST_FILE = DATA / "unclueable.json"

BLOCK = "#"
LIGHT = "."

# --------------------------------------------------------------------------
# Grid templates.
#
# Hand-checked, and re-checked mechanically at load time by check_template().
# Written as text so a human can eyeball the shape: '#' is a block, '.' a light.
# Both follow the Guardian daily idiom — a lattice with blocks at odd row / odd
# column, broken up so that entries stay short enough to be fillable — which is
# why they look like the grids in puzzles/.
# --------------------------------------------------------------------------

TEMPLATES = {
    # 20 entries, lengths 4-10, 37% checked, through-cuts 3/3. Found by
    # searching symmetric patterns over the lattice and keeping only those that
    # pass every check below — the first three shapes drawn by hand all failed,
    # which is the argument for the checks existing.
    11: """
....#......
.#.#.#.#.#.
.....#.....
.#.#.#.#.#.
.........##
.###.#.###.
##.........
.#.#.#.#.#.
.....#.....
.#.#.#.#.#.
......#....
""",
    # 28 entries, lengths 5-7, 40% checked, through-cuts 3/3. Chosen over
    # shapes with full-width 13-letter entries: those are legal but barely
    # fillable, because the pool of clueable 13-letter words is ~200 and two of
    # them have to interlock with 12s (the filler exhausted its budget on one).
    13: """
.......#.....
.#.#.#.#.#.#.
.....#.......
.#.#.#.#.#.#.
.....#.......
.###.#.###.##
......#......
##.###.#.###.
.......#.....
.#.#.#.#.#.#.
.......#.....
.#.#.#.#.#.#.
.....#.......
""",
}


def parse_pattern(text):
    rows = [r.strip() for r in text.strip().splitlines()]
    return [r for r in rows if r]


# --------------------------------------------------------------------------
# Grid model
# --------------------------------------------------------------------------

MIN_ENTRY = 4          # see check_min_entry_length
MAX_UNCHECKED_RUN = 1  # see check_unchecked_runs — Exet forbids ANY adjacency


class Slot:
    """One entry: a maximal run of lights of length >= MIN_ENTRY."""

    __slots__ = ("index", "direction", "row", "col", "length", "cells", "number")

    def __init__(self, index, direction, row, col, length):
        self.index = index
        self.direction = direction
        self.row, self.col, self.length = row, col, length
        self.cells = [(row, col + i) if direction == "across" else (row + i, col)
                      for i in range(length)]
        self.number = None

    @property
    def label(self):
        return f"{self.number}{'A' if self.direction == 'across' else 'D'}"


class Grid:
    def __init__(self, pattern):
        self.pattern = pattern
        self.rows = len(pattern)
        self.cols = len(pattern[0]) if pattern else 0
        self.slots = self._find_slots()
        self.cell_slots = {}
        for s in self.slots:
            for i, cell in enumerate(s.cells):
                self.cell_slots.setdefault(cell, []).append((s, i))
        self._number()

    # -- geometry ---------------------------------------------------------

    def is_block(self, r, c):
        return self.pattern[r][c] == BLOCK

    def lights(self):
        return [(r, c) for r in range(self.rows) for c in range(self.cols)
                if not self.is_block(r, c)]

    def _runs(self):
        """Every maximal run of lights, in both directions, with its length —
        including the length-1 runs, which are unchecked letters, not entries."""
        out = []
        for r in range(self.rows):
            c = 0
            while c < self.cols:
                if self.is_block(r, c):
                    c += 1
                    continue
                s = c
                while c < self.cols and not self.is_block(r, c):
                    c += 1
                out.append(("across", r, s, c - s))
        for c in range(self.cols):
            r = 0
            while r < self.rows:
                if self.is_block(r, c):
                    r += 1
                    continue
                s = r
                while r < self.rows and not self.is_block(r, c):
                    r += 1
                out.append(("down", s, c, r - s))
        return out

    def _find_slots(self):
        slots = []
        for direction, r, c, length in self._runs():
            if length >= MIN_ENTRY:
                slots.append(Slot(len(slots), direction, r, c, length))
        return slots

    def _number(self):
        """Standard crossword numbering: scan row-major, number a cell if an
        entry starts there. Unchecked single cells are not entries, so they are
        never numbered — that is what makes a British grid look sparse."""
        starts = {}
        for s in self.slots:
            starts.setdefault((s.row, s.col), []).append(s)
        n = 0
        for r in range(self.rows):
            for c in range(self.cols):
                if (r, c) in starts:
                    n += 1
                    for s in starts[(r, c)]:
                        s.number = n

    def checked_cells(self):
        """A cell is checked if two entries cross there — i.e. a second clue can
        confirm the letter."""
        return {cell for cell, uses in self.cell_slots.items() if len(uses) > 1}

    def ascii(self, letters=None):
        out = []
        for r in range(self.rows):
            row = []
            for c in range(self.cols):
                if self.is_block(r, c):
                    row.append(BLOCK)
                else:
                    row.append((letters or {}).get((r, c), LIGHT))
            out.append("".join(row))
        return "\n".join(out)


# --------------------------------------------------------------------------
# Convention checks. Each returns a list of complaints; empty means it passed.
#
# Sources, both cited in tools/AUTHORING.md:
#   * Exet (Viresh Ratnakar), the British-grid editor, whose validator is the
#     strict reading: minimum 4, NO two adjacent unchecked cells anywhere, never
#     more unchecked than checked in an entry (9+ may have one more), 180-degree
#     symmetry, odd side, one connected region.
#   * georgeho.org/counting-cryptics, which measured real published grids and
#     permits two consecutive unches mid-entry but never at an entry's ends.
# The strict reading is the default; --relax-unches selects the looser one.
#
# Everything was then sanity-checked against the twelve 30,0xx Guardian grids in
# puzzles/, which is how the global checked-ratio band got set: folklore says
# "half the letters are checked", but real grids check 31-40% OVERALL while
# keeping every individual ENTRY at least half checked. Both statements are
# "half checked"; only one of them is true of real grids.
# --------------------------------------------------------------------------

def check_shape(grid):
    """Square and odd-sided: British blocked grids are 11x11, 13x13 or 15x15, and
    an odd side is what lets a symmetric grid have a true centre square."""
    bad = []
    if grid.rows != grid.cols:
        bad.append(f"grid is {grid.rows}x{grid.cols}, not square")
    if grid.rows % 2 == 0:
        bad.append(f"grid side {grid.rows} is even; British grids are odd-sided")
    if any(len(r) != grid.cols for r in grid.pattern):
        bad.append("rows are not all the same width")
    return bad


def check_symmetry(grid):
    """180-degree rotational symmetry — universal in British blocked grids, and
    the reason a Guardian grid looks the same upside down."""
    bad = []
    n, m = grid.rows, grid.cols
    for r in range(n):
        for c in range(m):
            if grid.is_block(r, c) != grid.is_block(n - 1 - r, m - 1 - c):
                bad.append(f"block at ({r},{c}) has no partner at ({n-1-r},{m-1-c})")
    return bad[:4]


def check_min_entry_length(grid, minimum=MIN_ENTRY):
    """Every light is at least four letters — Exet's rule, and the one the
    Guardian keeps to in nine of the twelve grids in puzzles/ (the other three
    bottom out at 3, which is why --min-entry 3 exists as an escape hatch rather
    than a default). Two-letter entries are never seen and always refused."""
    bad = []
    for direction, r, c, length in grid._runs():
        if 1 < length < minimum:
            bad.append(f"{direction} run at ({r},{c}) is only {length} long "
                       f"(minimum entry length {minimum})")
    return bad


def check_every_light_is_used(grid):
    """Every light must belong to at least one entry. A light in no entry is a
    square the solver can never fill — the bug this catches is an isolated cell
    left behind by a careless block placement. Note that a light in only ONE
    entry is fine and expected: that is an unchecked letter, which British grids
    have and American ones do not."""
    return [f"light at {cell} belongs to no entry"
            for cell in grid.lights() if cell not in grid.cell_slots]


def check_unchecked_runs(grid, limit=MAX_UNCHECKED_RUN):
    """No two unchecked letters side by side in an entry (limit=1, the default,
    which is Exet's rule and what all twelve measured Guardian grids do). A
    solver who cannot get a run of unches from crossing entries has to guess
    them all at once.

    With --relax-unches (limit=2) the looser published-grid convention applies
    instead: two consecutive unches are tolerated mid-entry but never at either
    end, since an unchecked first or last letter is the hardest square on the
    grid to infer."""
    checked = grid.checked_cells()
    bad = []
    for s in grid.slots:
        run = 0
        for i, cell in enumerate(s.cells):
            run = 0 if cell in checked else run + 1
            if run > limit:
                bad.append(f"{s.label} has {run} unchecked letters in a row")
                break
            if limit > 1 and run == limit and (i == limit - 1 or i == s.length - 1):
                bad.append(f"{s.label} has {run} unchecked letters at an end")
                break
    return bad


def check_entry_checking(grid):
    """No entry has more unchecked letters than checked ones — except entries of
    9 or more, which may have exactly one more unchecked than checked (Exet).
    This is the rule people mean when they say a British grid is 'half checked',
    and it is stricter than 'at least half rounded down': a 5-letter entry needs
    3 checked, not 2."""
    checked = grid.checked_cells()
    bad = []
    for s in grid.slots:
        n = sum(1 for cell in s.cells if cell in checked)
        allowance = 1 if s.length >= 9 else 0
        if s.length - n > n + allowance:
            bad.append(f"{s.label} ({s.length}) has {n} checked, "
                       f"{s.length - n} unchecked")
    return bad


def check_connectivity(grid):
    """All lights form one connected region. A detached corner is a separate
    little crossword, and solvers rightly treat it as a fault."""
    lights = set(grid.lights())
    if not lights:
        return ["grid has no lights"]
    start = next(iter(lights))
    seen, stack = {start}, [start]
    while stack:
        r, c = stack.pop()
        for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if (nr, nc) in lights and (nr, nc) not in seen:
                seen.add((nr, nc))
                stack.append((nr, nc))
    if len(seen) != len(lights):
        return [f"lights are not connected ({len(lights) - len(seen)} cut off)"]
    return []


def check_checked_ratio(grid, lo=0.28, hi=0.52):
    """Roughly a third to a half of all letters checked. Measured over the
    Guardian grids in puzzles/ the figure is 31-40%; the band is widened a little
    so a legitimately chunkier grid is not refused, but a 20%-checked grid (a
    solver's nightmare) or a 60%-checked one (an American grid wearing a British
    hat) is."""
    lights = grid.lights()
    ratio = len(grid.checked_cells()) / len(lights) if lights else 0
    if not lo <= ratio <= hi:
        return [f"only {ratio:.0%} of letters are checked (want {lo:.0%}-{hi:.0%})"]
    return []


def through_cuts(grid):
    """(horizontal, vertical) through-cut sizes.

    A through-cut is the smallest set of lights that, blocked, would split the
    grid in two. Across each row boundary the crossing cells are exactly the
    columns light on both sides, and blocking those cells severs the grid there,
    so the minimum over boundaries is the cut in that direction. Exet wants >= 4
    on a 15x15; the point is solver flow — a solver stuck in one region needs
    several ways to get letters into the next one, and a grid with a cut of 1 is
    really two crosswords in a trenchcoat."""
    horizontal = min(
        sum(1 for c in range(grid.cols)
            if not grid.is_block(r, c) and not grid.is_block(r + 1, c))
        for r in range(grid.rows - 1))
    vertical = min(
        sum(1 for r in range(grid.rows)
            if not grid.is_block(r, c) and not grid.is_block(r, c + 1))
        for c in range(grid.cols - 1))
    return horizontal, vertical


def check_through_cut(grid, minimum=None):
    """Scaled from Exet's >= 4 on a 15x15: the same fraction of the side, so 3
    on an 11x11 and 13x13. Below that the grid pinches, and a solver who stalls
    on one side has no letters to carry across."""
    if minimum is None:
        minimum = max(3, round(4 * grid.rows / 15))
    h, v = through_cuts(grid)
    bad = []
    if h < minimum:
        bad.append(f"horizontal through-cut is {h} (want >= {minimum})")
    if v < minimum:
        bad.append(f"vertical through-cut is {v} (want >= {minimum})")
    return bad


CHECKS = (check_shape, check_symmetry, check_min_entry_length,
          check_every_light_is_used, check_unchecked_runs, check_entry_checking,
          check_connectivity, check_checked_ratio, check_through_cut)


def check_template(grid, minimum=MIN_ENTRY, unch_limit=MAX_UNCHECKED_RUN):
    """Run every convention check. Returns {check name: [complaints]}."""
    args = {check_min_entry_length: minimum, check_unchecked_runs: unch_limit}
    out = {}
    for fn in CHECKS:
        bad = fn(grid, args[fn]) if fn in args else fn(grid)
        if bad:
            out[fn.__name__] = bad
    return out


class IllegalGrid(Exception):
    pass


def load_grid(size=None, path=None, minimum=MIN_ENTRY, strict=True,
              unch_limit=MAX_UNCHECKED_RUN):
    if path:
        pattern = parse_pattern(Path(path).read_text(encoding="utf-8"))
    else:
        if size not in TEMPLATES:
            raise IllegalGrid(f"no built-in template for size {size} "
                              f"(have {sorted(TEMPLATES)})")
        pattern = parse_pattern(TEMPLATES[size])
    grid = Grid(pattern)
    problems = check_template(grid, minimum, unch_limit)
    if problems and strict:
        lines = [f"  {name}: {'; '.join(msgs)}" for name, msgs in problems.items()]
        raise IllegalGrid("template breaks British cryptic conventions:\n"
                          + "\n".join(lines))
    return grid, problems


# --------------------------------------------------------------------------
# Wordlist
# --------------------------------------------------------------------------

def load_words(min_clue, min_familiarity, lengths, rebuild=False):
    """Candidate words by length: {length: [(word, clue_score, familiarity)]},
    best-clued first.

    Falls back to /usr/share/dict/words when the Lufz lexicon has not been
    fetched. That fallback is deliberately loud: the system dictionary has no
    importance data, so the fairness floor cannot be applied at all and the fill
    will contain obscurities. Run tools/fetch_lexicon.sh to fix it properly."""
    table = None
    if clueability.LEXICON.exists():
        table = clueability.scores(rebuild=rebuild)
    if not table:
        print("WARNING: tools/data/lexicon.tsv missing — falling back to "
              "/usr/share/dict/words. It has no importance scores, so there is NO "
              "fairness floor and no clueability ordering: expect obscure fill. "
              "Run: bash tools/fetch_lexicon.sh", file=sys.stderr)
        table = {}
        for p in ("/usr/share/dict/words", "/usr/dict/words"):
            try:
                for line in open(p, encoding="utf-8", errors="ignore"):
                    w = line.strip().upper()
                    if w.isalpha() and w.isascii() and w == line.strip().upper():
                        table[w] = (50, 50, "?")  # unknown hooks, unknown fame
                break
            except OSError:
                continue
        if not table:
            raise IllegalGrid("no wordlist available at all")
        min_clue = min_familiarity = 0

    by_len = {}
    for w, (clue, fam, flags) in table.items():
        if len(w) in lengths and clue >= min_clue and fam >= min_familiarity:
            by_len.setdefault(len(w), []).append((w, clue, fam, flags))
    for L in by_len:
        by_len[L].sort(key=lambda t: (-t[1], -t[2], t[0]))
    return by_len


def load_blacklist():
    """Words a previous clue-writing attempt gave up on, with the reason.

    Persisted so the knowledge accumulates: the same principle STYLE.md applies
    to feedback — encode it once, never rediscover it."""
    if BLACKLIST_FILE.exists():
        doc = json.loads(BLACKLIST_FILE.read_text(encoding="utf-8"))
        return doc.get("unclueable", {})
    return {}


def save_blacklist(entries):
    BLACKLIST_FILE.write_text(json.dumps({
        "_comment": ("Words a clue-writing pass could not clue, and why. "
                     "tools/grid_fill.py refuses them, so a bad answer is never "
                     "rediscovered. Add to this rather than fixing a fill by hand."),
        "unclueable": entries,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# The filler
# --------------------------------------------------------------------------

class Budget(Exception):
    """Raised to unwind the search when the node budget for this restart is
    spent. Backtracking search on a bad random ordering can grind forever; a
    budget plus a fresh restart is far cheaper than a cleverer heuristic."""


class Revoked(Exception):
    """Raised to unwind past an assignment the caller vetoed after seeing it in
    a yielded fill, so the search resumes from the frame that chose that word
    instead of from the deepest one."""

    def __init__(self, word):
        super().__init__(word)
        self.word = word


class Filler:
    def __init__(self, grid, by_len, veto=None, rng=None, max_nodes=120000,
                 time_limit=60.0, jitter=6.0):
        self.grid = grid
        self.rng = rng or random.Random()
        self.veto = veto
        self.max_nodes = max_nodes
        self.time_limit = time_limit
        self.jitter = jitter
        self.words = {}      # length -> [word]
        self.meta = {}       # word -> (clue, familiarity)
        self.index = {}      # length -> {(pos, letter): bitmask}
        self.full = {}       # length -> bitmask of every candidate
        needed = {s.length for s in grid.slots}
        for L in sorted(needed):
            pool = by_len.get(L, [])
            if not pool:
                raise IllegalGrid(f"no candidate words of length {L}")
            self.words[L] = [w for w, _c, _f, _h in pool]
            for w, c, f, h in pool:
                self.meta[w] = (c, f, h)
        self.nodes = 0
        self.deadline = 0.0

    # -- indexing ---------------------------------------------------------

    def reindex(self):
        """Rebuild the letter-position bitmask index, re-sorting each pool by
        clueability plus a random jitter. The jitter is what makes restarts
        explore different fills instead of re-deriving the same one, while the
        score keeps the good words near the front."""
        self.index, self.full = {}, {}
        for L, pool in self.words.items():
            scored = sorted(pool, key=lambda w: -(self.meta[w][0]
                                                  + self.rng.uniform(0, self.jitter)))
            self.words[L] = scored
            idx = {}
            for i, w in enumerate(scored):
                bit = 1 << i
                for pos, ch in enumerate(w):
                    key = (pos, ch)
                    idx[key] = idx.get(key, 0) | bit
            self.index[L] = idx
            self.full[L] = (1 << len(scored)) - 1

    # -- search -----------------------------------------------------------

    def _mask(self, slot, letters):
        m = self.full[slot.length]
        idx = self.index[slot.length]
        for pos, cell in enumerate(slot.cells):
            ch = letters.get(cell)
            if ch:
                m &= idx.get((pos, ch), 0)
                if not m:
                    return 0
        return m

    def _bits(self, m, L):
        words = self.words[L]
        while m:
            low = m & -m
            yield words[low.bit_length() - 1]
            m ^= low

    def _search(self, letters, assigned, used):
        if len(assigned) == len(self.grid.slots):
            yield dict(assigned)
            # Resumed. The caller may have vetoed one of these words while it
            # held the fill — that is the whole point of the veto hook — so
            # unwind to whichever frame owns the newly-banned word and carry on
            # from there. Without this, resuming continues from the DEEPEST
            # frame and happily re-offers the banned word for the rest of the
            # subtree, which is how the first version of this quietly ignored
            # its own blacklist.
            if self.veto:
                for w in assigned.values():
                    if self.veto(w):
                        raise Revoked(w)
            return
        self.nodes += 1
        if self.nodes > self.max_nodes or time.time() > self.deadline:
            raise Budget()

        # Minimum remaining values: the slot with fewest candidates is the one
        # most likely to fail, so failing there costs the least work.
        best, best_mask, best_count = None, 0, None
        for s in self.grid.slots:
            if s.index in assigned:
                continue
            m = self._mask(s, letters)
            n = bin(m).count("1")
            if n == 0:
                return  # dead end: some slot has nothing that fits
            if best_count is None or n < best_count:
                best, best_mask, best_count = s, m, n
                if n == 1:
                    break

        crossers = []
        for cell in best.cells:
            for other, _pos in self.grid.cell_slots[cell]:
                if other.index not in assigned and other.index != best.index:
                    crossers.append(other)

        for word in self._bits(best_mask, best.length):
            if word in used:
                continue
            if self.veto and self.veto(word):
                continue
            for pos, cell in enumerate(best.cells):
                letters[cell] = word[pos]
            assigned[best.index] = word
            used.add(word)
            try:
                # Cheap dead-end check: if this word leaves any crossing slot
                # with no candidates, it is already lost — prune before
                # recursing.
                if all(self._mask(o, letters) for o in crossers):
                    yield from self._search(letters, assigned, used)
            except Revoked as r:
                # Only the frame that placed the banned word absorbs the unwind;
                # everyone else is just on the stack.
                if r.word != word:
                    raise
            finally:
                used.discard(word)
                del assigned[best.index]
                for pos, cell in enumerate(best.cells):
                    if not any(o.index in assigned
                               for o, _ in self.grid.cell_slots[cell]):
                        letters.pop(cell, None)
                    else:
                        # Another assigned entry still owns this letter.
                        for o, p in self.grid.cell_slots[cell]:
                            if o.index in assigned:
                                letters[cell] = assigned[o.index][p]
                                break

    def fills(self, restarts=25):
        """Yield successive complete fills, restarting with a new ordering when
        a restart burns its node budget."""
        for attempt in range(restarts):
            self.reindex()
            self.nodes = 0
            self.deadline = time.time() + self.time_limit
            try:
                for solution in self._search({}, {}, set()):
                    yield {self.grid.slots[i].index: w for i, w in solution.items()}, attempt
            except Budget:
                continue
            except Revoked:
                # The vetoed word was chosen at the very root, so there is
                # nothing above it to backtrack into: start a fresh restart.
                continue


def fill(grid, by_len, veto=None, seed=None, restarts=25, max_nodes=120000,
         time_limit=60.0):
    """Public API: a GENERATOR of fills, with a veto hook.

    `veto(word)` returns a reason string if a word must not be used (and None
    otherwise). A clue-writing stage that cannot clue an entry adds it to the
    blacklist and simply pulls the next fill from this generator, which carries
    on searching rather than starting over."""
    f = Filler(grid, by_len, veto=veto, rng=random.Random(seed),
               max_nodes=max_nodes, time_limit=time_limit)
    return f.fills(restarts=restarts)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def entry_records(grid, solution, meta):
    checked = grid.checked_cells()
    out = []
    for s in sorted(grid.slots, key=lambda s: (s.number, s.direction)):
        word = solution[s.index]
        marks = [cell in checked for cell in s.cells]
        clue, fam, flags = meta.get(word, (0, 0, "?"))
        out.append({
            "id": f"{s.number}-{s.direction}",
            "number": s.number,
            "direction": s.direction,
            "position": {"x": s.col, "y": s.row},
            "length": s.length,
            "solution": word,
            "checkedPattern": "".join(w if m else w.lower()
                                      for w, m in zip(word, marks)),
            "checkedIndices": [i for i, m in enumerate(marks) if m],
            "clueability": clue,
            "familiarity": fam,
            # Which hooks this answer offers the clue writer: A anagram,
            # N near-anagram, C charade, X container, P homophone, R/r reversal,
            # D deletion, H easily hidden. `python3 tools/clueability.py --word X`
            # spells out the actual splits.
            "hooks": flags,
        })
    return out


def report(grid, solution, meta, stream=sys.stdout):
    letters = {}
    for s in grid.slots:
        for pos, cell in enumerate(s.cells):
            letters[cell] = solution[s.index][pos]
    print(grid.ascii(letters), file=stream)
    print(file=stream)
    records = entry_records(grid, solution, meta)
    for direction in ("across", "down"):
        print(direction.upper(), file=stream)
        for r in records:
            if r["direction"] != direction:
                continue
            print(f"  {r['number']:>3}. {r['solution']:<12} ({r['length']})  "
                  f"checked {r['checkedPattern']}  "
                  f"clueability {r['clueability']:>3}  fame {r['familiarity']:>3}  "
                  f"hooks {r['hooks']}",
                  file=stream)
    cs = sorted(r["clueability"] for r in records)
    fs = sorted(r["familiarity"] for r in records)
    mid = len(cs) // 2
    h, v = through_cuts(grid)
    print(f"\n{len(records)} entries · through-cut {h}h/{v}v · clueability min "
          f"{cs[0]} median {cs[mid]} max {cs[-1]} · familiarity min {fs[0]} "
          f"median {fs[mid]}", file=stream)
    print("clueability distribution: "
          + " ".join(f"{lo}-{lo+19}:{sum(1 for c in cs if lo <= c < lo + 20)}"
                     for lo in range(0, 100, 20)), file=stream)
    weak = [r for r in records if r["clueability"] < 35 or r["familiarity"] < 10]
    if weak:
        print("watch list (hardest to clue / least familiar): "
              + ", ".join(f"{r['solution']}({r['clueability']}/{r['familiarity']})"
                          for r in weak), file=stream)
    return records


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", type=int, default=11)
    ap.add_argument("--template", help="path to a grid pattern file (# and .)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", help="write the fill as JSON here")
    ap.add_argument("--min-entry", type=int, default=MIN_ENTRY,
                    help="shortest legal entry (4 is the rule; 3 is an escape hatch)")
    ap.add_argument("--relax-unches", action="store_true",
                    help="allow two consecutive unchecked letters mid-entry "
                         "(published-grid convention) instead of none (Exet)")
    # Defaults tuned by inspecting fills: at 30/18 the grid was legal but the
    # corners filled with PARC and PROTO, which no daily setter would print.
    ap.add_argument("--min-clue", type=int, default=40,
                    help="clueability floor: below this a word is not a legal fill")
    ap.add_argument("--min-familiarity", type=int, default=25,
                    help="solver-fairness floor from lexicon importance")
    ap.add_argument("--restarts", type=int, default=25)
    ap.add_argument("--max-nodes", type=int, default=120000)
    ap.add_argument("--time-limit", type=float, default=30.0,
                    help="seconds per restart")
    ap.add_argument("--fills", type=int, default=25,
                    help="how many distinct fills to generate (best is kept)")
    ap.add_argument("--check-only", action="store_true",
                    help="validate the template and report its statistics")
    ap.add_argument("--list-templates", action="store_true")
    ap.add_argument("--rebuild-scores", action="store_true",
                    help="recompute the clueability cache first")
    args = ap.parse_args(argv)

    if args.list_templates:
        for size, pat in sorted(TEMPLATES.items()):
            print(f"--- {size}x{size} ---\n{parse_pattern(pat) and pat.strip()}")
        return 0

    unch_limit = 2 if args.relax_unches else MAX_UNCHECKED_RUN
    try:
        grid, problems = load_grid(args.size, args.template, args.min_entry,
                                   unch_limit=unch_limit)
    except IllegalGrid as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2

    lengths = sorted({s.length for s in grid.slots})
    if args.check_only:
        print(grid.ascii())
        checked = grid.checked_cells()
        h, v = through_cuts(grid)
        print(f"\n{grid.rows}x{grid.cols}: {len(grid.slots)} entries, "
              f"{len(grid.lights())} lights, {len(checked)} checked "
              f"({len(checked)/len(grid.lights()):.0%})")
        print(f"entry lengths: {lengths}")
        print(f"through-cut: {h} horizontal, {v} vertical")
        print("all convention checks passed" if not problems else problems)
        return 0

    by_len = load_words(args.min_clue, args.min_familiarity, set(lengths),
                        rebuild=args.rebuild_scores)
    for L in lengths:
        print(f"  {len(by_len.get(L, [])):>5} candidates of length {L}", file=sys.stderr)

    blacklist = load_blacklist()
    veto = (lambda w: blacklist.get(w)) if blacklist else None
    if blacklist:
        print(f"  {len(blacklist)} blacklisted word(s) from {BLACKLIST_FILE.name}",
              file=sys.stderr)

    t0 = time.time()
    best = None
    gen = fill(grid, by_len, veto=veto, seed=args.seed, restarts=args.restarts,
               max_nodes=args.max_nodes, time_limit=args.time_limit)
    meta = {}
    for L in by_len:
        for w, c, f, h in by_len[L]:
            meta[w] = (c, f, h)
    for i, (solution, attempt) in enumerate(gen):
        cl = [meta[w][0] for w in solution.values()]
        # Rank fills by their WORST entry first, mean second. A setter does not
        # accept a grid because most of it is nice; one unclueable answer is
        # what sinks it.
        score = (min(cl), sum(cl) / len(cl))
        print(f"  fill {i+1} (restart {attempt}) worst {score[0]} "
              f"mean {score[1]:.1f}", file=sys.stderr)
        if best is None or score > best[0]:
            best = (score, solution)
        if i + 1 >= args.fills:
            break

    if best is None:
        print("no fill found within budget — try another --seed, more "
              "--restarts, or a lower --min-clue", file=sys.stderr)
        return 1

    print(f"filled in {time.time() - t0:.1f}s\n", file=sys.stderr)
    records = report(grid, best[1], meta)

    if args.out:
        doc = {
            "size": grid.rows,
            "pattern": grid.pattern,
            "seed": args.seed,
            "minClueability": args.min_clue,
            "minFamiliarity": args.min_familiarity,
            "worstClueability": best[0][0],
            "meanClueability": round(best[0][1], 1),
            "entries": records,
        }
        Path(args.out).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
