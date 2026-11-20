#!/usr/bin/env python3
"""Fit a jigsaw's answers into the one blocked grid they interlock in.

A jigsaw (`cluesUnplaced`, tools/clues_only.py) prints its clues as one list:
no numbers, no across or down, and here no diagram either (the book page's
grid is not read). Its answers alone place it: this finds every blocked grid
of the given size that

  - is symmetric under a half turn, as every blocked grid in these books is;
  - holds every answer exactly once as a light, across or down, and has no
    other light (every run of two or more white squares is an answer);
  - is connected, and has no white square outside every light.

An answer longer than the grid (book-2025's 23 letters on a 15x15) is a
linked answer: it is split across two lights, its leader reading first.

THE SEARCH IS DETERMINISTIC AND EXHAUSTIVE. It seeds the longest answer across
at every place it fits (on a square grid the transpose, the one symmetry that
keeps answers reading forwards, carries a grid with it down to one with it
across, so nothing is lost). Then it
takes the white square with the fewest ways forward and branches on what runs
through it the other way: nothing (the square is unchecked that way), or an
unused answer at each place its letters agree. Those choices partition what
can follow, so each grid is reached once. A grid and its transpose are one
answer (which way is across is the one thing the answers cannot say); fit()
returns the first found and refuses when two different grids remain.

A jigsaw whose page prints its blank grid (a Guardian Genius) needs no
search for the grid: fit_grid() assigns the answers to that grid's lights.

    python3 tools/jigsaw_fit.py WORD WORD ... [--size 15]
"""
from __future__ import annotations

import sys

MIN_LIGHT = 3        # a split's shorter half: no blocked grid prints a 2-light
DEFAULT_MAX_NODES = 2_000_000

ACROSS, DOWN = 0, 1
DIRS = ("across", "down")


class _Budget(Exception):
    pass


class _State:
    """The partial grid. cell: None undecided, '#' block, '?' white of unknown
    letter, or the letter. cover[d]: None undecided, True in an answer that
    way, False unchecked that way."""
    __slots__ = ("cell", "cover", "units", "placed")

    def copy(self):
        s = _State()
        s.cell = self.cell[:]
        s.cover = [self.cover[0][:], self.cover[1][:]]
        s.units = self.units[:]
        s.placed = self.placed[:]
        return s


class Fitter:
    def __init__(self, words, cols=15, rows=15, max_nodes=DEFAULT_MAX_NODES):
        self.cols, self.rows = cols, rows
        self.words = [w.upper() for w in words]
        self.max_nodes = max_nodes
        self.nodes = 0
        self.longest = max(cols, rows)

    # ------------------------------------------------------------ geometry
    def _i(self, x, y):
        return y * self.cols + x

    def _mirror(self, i):
        return len(self._blank) - 1 - i

    def _step(self, d):
        return (1, 0) if d == ACROSS else (0, 1)

    # --------------------------------------------------------- state edits
    def _white(self, s, i, letter):
        """Make square i white (`letter` or '?'), and its half-turn image
        white too. False on a clash."""
        cur = s.cell[i]
        if cur == "#":
            return False
        if letter != "?":
            if cur not in (None, "?") and cur != letter:
                return False
            s.cell[i] = letter
        elif cur is None:
            s.cell[i] = "?"
        m = self._mirror(i)
        if s.cell[m] == "#":
            return False
        if s.cell[m] is None:
            s.cell[m] = "?"
        return True

    def _black(self, s, i):
        for j in (i, self._mirror(i)):
            if s.cell[j] not in (None, "#"):
                return False
            s.cell[j] = "#"
        return True

    def _neighbours(self, i, d):
        x, y = i % self.cols, i // self.cols
        dx, dy = self._step(d)
        out = []
        for sgn in (-1, 1):
            nx, ny = x + sgn * dx, y + sgn * dy
            if 0 <= nx < self.cols and 0 <= ny < self.rows:
                out.append(self._i(nx, ny))
        return out

    def _unchecked(self, s, i, d):
        """Square i has no light running direction d through it."""
        if s.cover[d][i] is not None:
            return s.cover[d][i] is False
        if s.cover[1 - d][i] is False:      # a white square in no light
            return False
        for j in self._neighbours(i, d):
            if not self._black(s, j):
                return False
        return self._mark_unchecked(s, i, d)

    def _mark_unchecked(self, s, i, d):
        """cover[d][i] = False, refused beside another square unchecked the
        same way in the same light: the books' grids, like grid_fill's
        (MAX_UNCHECKED_RUN), never leave two unchecked squares side by side."""
        s.cover[d][i] = False
        for j in self._neighbours(i, 1 - d):
            if s.cell[j] not in (None, "#") and s.cover[d][j] is False:
                return False
        return True

    def _fits(self, s, word, x, y, d):
        """Cheap test: `word` from (x, y) direction d agrees with the grid."""
        dx, dy = self._step(d)
        n = len(word)
        ex, ey = x + dx * (n - 1), y + dy * (n - 1)
        if x < 0 or y < 0 or ex >= self.cols or ey >= self.rows:
            return False
        for k, ch in enumerate(word):
            i = self._i(x + dx * k, y + dy * k)
            c = s.cell[i]
            if c == "#" or (c not in (None, "?") and c != ch) or s.cover[d][i] is not None:
                return False
        for bx, by in ((x - dx, y - dy), (ex + dx, ey + dy)):
            if 0 <= bx < self.cols and 0 <= by < self.rows:
                c = s.cell[self._i(bx, by)]
                if c not in (None, "#"):
                    return False
        return True

    def _place(self, s, word, x, y, d):
        """Write `word` in; False on a clash (s is then spoiled)."""
        if not self._fits(s, word, x, y, d):
            return False
        dx, dy = self._step(d)
        n = len(word)
        for bx, by in ((x - dx, y - dy), (x + dx * n, y + dy * n)):
            if 0 <= bx < self.cols and 0 <= by < self.rows:
                if not self._black(s, self._i(bx, by)):
                    return False
        for k, ch in enumerate(word):
            i = self._i(x + dx * k, y + dy * k)
            if not self._white(s, i, ch):
                return False
            s.cover[d][i] = True
        return self._settle(s)

    def _settle(self, s):
        """Force what blocks have decided: a white square boxed in one way is
        unchecked that way. False when a white square is boxed in both."""
        changed = True
        while changed:
            changed = False
            for i, c in enumerate(s.cell):
                if c is None or c == "#":
                    continue
                for d in (ACROSS, DOWN):
                    if s.cover[d][i] is None and all(
                            s.cell[j] == "#" for j in self._neighbours(i, d)):
                        if s.cover[1 - d][i] is False or not self._mark_unchecked(s, i, d):
                            return False
                        changed = True
        return True

    # ------------------------------------------------------------ choices
    def _pieces(self, unit):
        """(piece, leftover) for each way unit can go in as one light: whole,
        or (a linked answer) either half of a split."""
        index, word, part = unit
        n = len(word)
        if n <= self.longest and part is None:
            return [((index, 0, word), None)]
        if part is not None:                  # the other half of a split
            return [((index, part, word), None)]
        out = []
        for k in range(max(MIN_LIGHT, n - self.longest), min(self.longest, n - MIN_LIGHT) + 1):
            out.append(((index, 0, word[:k]), (index, word[k:], 1)))
            out.append(((index, 1, word[k:]), (index, word[:k], 0)))
        return out

    def _options(self, s, i, d, stop=None):
        """Every way forward at white square i, direction d: ('none',) or
        ('place', unit position, piece, leftover, x, y)."""
        out = []
        letter = s.cell[i]
        nb = self._neighbours(i, d)
        if s.cover[1 - d][i] is not False and all(s.cell[j] in (None, "#") for j in nb):
            out.append(("none",))
        x0, y0 = i % self.cols, i // self.cols
        dx, dy = self._step(d)
        seen = set()
        for u, unit in enumerate(s.units):
            if unit in seen:          # two identical answers: one branch
                continue
            seen.add(unit)
            for piece, leftover in self._pieces(unit):
                word = piece[2]
                for k, ch in enumerate(word):
                    if letter != "?" and ch != letter:
                        continue
                    x, y = x0 - dx * k, y0 - dy * k
                    if self._fits(s, word, x, y, d):
                        out.append(("place", u, piece, leftover, x, y))
                        if stop is not None and len(out) > stop:
                            return out
        return out

    def _apply(self, s, i, d, opt):
        t = s.copy()
        if opt[0] == "none":
            return t if self._unchecked(t, i, d) and self._settle(t) else None
        _, u, piece, leftover, x, y = opt
        unit = t.units.pop(u)
        if leftover is not None:
            t.units.append(leftover)
        if not self._place(t, piece[2], x, y, d):
            return None
        t.placed.append((piece[0], piece[1], piece[2], x, y, d))
        del unit
        return t

    # ------------------------------------------------------------- search
    def _connected(self, s):
        whites = [i for i, c in enumerate(s.cell) if c not in (None, "#")]
        if not whites:
            return False
        seen, todo = {whites[0]}, [whites[0]]
        while todo:
            i = todo.pop()
            for d in (ACROSS, DOWN):
                for j in self._neighbours(i, d):
                    if j not in seen and s.cell[j] not in (None, "#"):
                        seen.add(j)
                        todo.append(j)
        return len(seen) == len(whites)

    def _rows(self, s):
        return ["".join("#" if c in (None, "#") else c for c in
                        s.cell[y * self.cols:(y + 1) * self.cols]) for y in range(self.rows)]

    def _canonical(self, rows):
        """One key for a grid and its transpose: the only symmetry of the
        square that keeps every answer reading forwards."""
        forms = [rows]
        if self.cols == self.rows:
            forms.append(["".join(r[x] for r in rows) for x in range(self.cols)])
        return min("/".join(f) for f in forms)

    def _search(self, s, found):
        self.nodes += 1
        if self.nodes > self.max_nodes:
            raise _Budget
        # Every undecided way at every white square, fully: the square with
        # the fewest is branched on, and an unused answer that fits at none
        # of them can never go in, so this grid is dead.
        best, reach = None, set()
        for i, c in enumerate(s.cell):
            if c is None or c == "#":
                continue
            for d in (ACROSS, DOWN):
                if s.cover[d][i] is not None:
                    continue
                opts = self._options(s, i, d)
                if not opts:
                    return
                for o in opts:
                    if o[0] == "place":
                        reach.add(s.units[o[1]])
                if best is None or len(opts) < len(best[2]):
                    best = (i, d, opts)
        if best is None:
            if not s.units and self._connected(s):
                rows = self._rows(s)
                key = self._canonical(rows)
                if key not in found:
                    found[key] = (rows, list(s.placed))
            return
        i, d, opts = best
        for opt in opts:
            t = self._apply(s, i, d, opt)
            if t is not None:
                self._search(t, found)
                if len(found) > 1:
                    return

    def run(self):
        """({canonical key: (rows, placed)}, finished). Stops at two grids."""
        self._blank = [None] * (self.cols * self.rows)
        units = [(n, w, None) for n, w in enumerate(self.words)]
        fits = [u for u in units if len(u[1]) <= self.longest]
        if not fits:
            return {}, True
        seed = max(fits, key=lambda u: (len(u[1]), -u[0]))
        rest = [u for u in units if u is not seed]
        found = {}
        n = len(seed[1])
        starts = [(x, y, d)
                  for d in ((ACROSS,) if self.cols == self.rows else (ACROSS, DOWN))
                  for y in range(self.rows) for x in range(self.cols)
                  if (x + n <= self.cols if d == ACROSS else y + n <= self.rows)]
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 4 * len(self.words) * self.cols + 500))
        try:
            for x, y, d in starts:
                s = _State()
                s.cell = self._blank[:]
                s.cover = [self._blank[:], self._blank[:]]
                s.units = rest[:]
                s.placed = []
                if not self._place(s, seed[1], x, y, d):
                    continue
                s.placed.append((seed[0], 0, seed[1], x, y, d))
                self._search(s, found)
                if len(found) > 1:
                    return found, True
        except _Budget:
            return found, False
        return found, True


def fit(words, cols=15, rows=15, max_nodes=DEFAULT_MAX_NODES):
    """(rows, placements, None) when the answers interlock in one grid (up to
    the square's symmetries), else (None, None, why). `placements` lists
    (answer index, part, letters, x, y, "across"|"down"), part 0 for an answer
    in one light or a linked answer's leader, 1 for its continuation."""
    words = ["".join(ch for ch in w.upper() if ch.isalpha()) for w in words]
    if not words or not all(words):
        return None, None, "an answer is missing"
    longest = max(cols, rows)
    if any(len(w) > 2 * longest for w in words):
        return None, None, "an answer is too long for two lights of this grid"
    fitter = Fitter(words, cols, rows, max_nodes)
    found, finished = fitter.run()
    if len(found) > 1:
        return None, None, f"{len(found)} different grids hold these answers"
    if not finished:
        return None, None, (f"the search ran out of budget ({max_nodes} nodes)"
                            + (" after one grid" if found else ""))
    if not found:
        return None, None, "no grid holds these answers"
    rows_, placed = next(iter(found.values()))
    return rows_, [(n, part, w, x, y, DIRS[d]) for n, part, w, x, y, d in placed], None


def slots(grid):
    """[(x, y, length, "across"|"down")] of a printed blocked grid's lights
    ("#" a block), in reading order."""
    rows, cols = len(grid), len(grid[0])
    white = lambda x, y: 0 <= x < cols and 0 <= y < rows and grid[y][x] != "#"
    out = []
    for y in range(rows):
        for x in range(cols):
            for d, (dx, dy) in enumerate(((1, 0), (0, 1))):
                if white(x, y) and not white(x - dx, y - dy) and white(x + dx, y + dy):
                    run = 1
                    while white(x + dx * run, y + dy * run):
                        run += 1
                    out.append((x, y, run, DIRS[d]))
    return out


def fit_grid(words, grid, max_nodes=DEFAULT_MAX_NODES):
    """(placements, None) when the answers fill the printed grid's lights one
    way only, else (None, why). Every light takes one answer, crossings
    agreeing, no answer twice; an answer may take no light (a preamble can
    send one below the grid). `placements` lists (answer index, x, y,
    direction) per light, in slots() order."""
    words = ["".join(ch for ch in w.upper() if ch.isalpha()) for w in words]
    if not words or not all(words):
        return None, "an answer is missing"
    lights = slots(grid)
    cells = [[(x + (d == "across") * i, y + (d == "down") * i) for i in range(n)]
             for x, y, n, d in lights]
    letter, used, chosen, found, nodes = {}, set(), [None] * len(lights), [], [0]

    def fits(k, w):
        return len(w) == len(cells[k]) and all(letter.get(c, ch) == ch for c, ch in zip(cells[k], w))

    def walk():
        nodes[0] += 1
        if len(found) > 1 or nodes[0] > max_nodes:
            return
        open_ = [k for k in range(len(lights)) if chosen[k] is None]
        if not open_:
            found.append(list(chosen))
            return
        best = None
        for k in open_:
            ways = [n for n, w in enumerate(words) if n not in used and fits(k, w)]
            if best is None or len(ways) < len(best[1]):
                best = (k, ways)
            if not ways:
                return
        k, ways = best
        for n in ways:
            set_ = [c for c, ch in zip(cells[k], words[n]) if c not in letter]
            for c, ch in zip(cells[k], words[n]):
                letter.setdefault(c, ch)
            used.add(n)
            chosen[k] = n
            walk()
            chosen[k] = None
            used.discard(n)
            for c in set_:
                del letter[c]

    walk()
    if len(found) > 1:
        return None, "the answers fill the printed grid more than one way"
    if nodes[0] > max_nodes:
        return None, f"the search ran out of budget ({max_nodes} nodes)"
    if not found:
        return None, "the answers fill no way of the printed grid's lights"
    return [(n, x, y, d) for n, (x, y, _, d) in zip(found[0], lights)], None


def main(argv):
    size = 15
    if "--size" in argv:
        at = argv.index("--size")
        size = int(argv[at + 1])
        argv = argv[:at] + argv[at + 2:]
    rows, placed, why = fit(argv, size, size)
    if rows is None:
        print(why, file=sys.stderr)
        return 1
    print("\n".join(rows))
    for p in sorted(placed):
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
