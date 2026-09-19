#!/usr/bin/env python3
"""Recover a crossword's black squares from the clue list alone.

The numbering of a blocked crossword is not decoration, it is a function.
Scan the cells row-major; a cell earns the next number exactly when it starts
an across light (two or more cells, nothing to its left) or starts a down one.
So a black-square pattern *determines* the list of lights printed above the
clues. This module runs that function backwards: given the lights, it finds
every grid that would have produced them.

That matters because the lights survive where the picture does not. A clue
list is text — in the newspaper, in the blog, in an OCR of a book scan —
while the grid is an image we may have no way to read. If the list pins the
grid down, a puzzle we can only read the clues of is still a puzzle.

WHAT IT TAKES IN — the weakest form we can actually get, which is two ordered
lists of lengths and nothing else:

    {"across": [6, 6, 4, 10, ...], "down": [4, 9, 5, ...]}

Clue numbers are optional, because a scan often loses them: OCR of a printed
book keeps the clue text and the enumeration and drops the little numerals.
When the numbers *are* legible, pass triples instead —
``[(1, "across", 6), (1, "down", 4), ...]`` — and they become extra
constraints rather than the thing the search keys on. An unknown length may
be written ``None``, at a steep price in search.

Lengths here are LIGHTS, not enumerations. An enumeration of "(7,5)" is one
twelve-cell light and should be passed as 12. A linked clue — "1,5" with a
single enumeration covering two entries — is two lights, and which half is
which is not recoverable from the enumeration alone; split it yourself, or
pass ``None`` for both and let the search decide. A "See 15" clue is a real
light whose length is one component of 15's enumeration; if you cannot tell
which, ``None`` is the honest answer.

METHOD — row by row, top to bottom, with the lists consumed in step. Within a
row the search walks left to right choosing the next white run's length; each
cell of the run is then matched against the light it would have to be. The
clue list drives the search rather than filtering its output, so a wrong turn
usually dies in the row that made it: a run of two or more cells starts an
across light, and across lights are handed out in row-major order, so the run
can only be as long as the next unspent across length.

180-degree rotational symmetry — which every published grid here has bar
about one in four hundred, counted rather than assumed — is worth more than
halving the grid. Writing a cell writes its twin,
so a down light committed in row 1 lights up row 13 on the spot; and the
lights of the mirrored rows are read off the *ends* of the two lists, so the
search is squeezed from both directions at once and meets in the middle. A
choice in row 0 that no bottom row could ever match fails in row 0.

Beyond the numbering the search enforces these, and only these:

  * a maximal run of white cells is a light of the length the list gives it,
    in both directions;
  * every white cell belongs to some light — a white cell with blocks on all
    four sides is not an unchecked square, it is a hole;
  * the grid is 180-degree symmetric, unless that search finishes empty and
    the caller allows the fallback;
  * every row and every column holds at least two white cells;
  * no two adjacent rows both lack an across light, and no two adjacent
    columns both lack a down light;
  * the white cells are all connected.

The last three are `strict`, and they are here because they hold for every
published grid we have — recounted over the whole corpus every time
tools/test_reconstruct_grid.sh runs, so a series that arrives breaking one
fails that test rather than quietly costing hit rate. They earn their place
on speed as much as on accuracy: an all-black row is numbered perfectly well
and is not a crossword, and without them the search spends its whole budget
under one.

Notably absent: "no light shorter than three", "at least half of every light
is checked", "no two unchecked squares in a row". The first is implied (a
run's length has to equal a length in the list, so a two-cell run needs a
two-cell clue, and one puzzle here has exactly that), and the other two are
simply false of this corpus — thousands of these puzzles have a light under
half checked. The test asserts that those counterexamples are still there, so
the day one of these rules becomes safe to adopt is a day something fails
rather than a day nobody notices. A rule that real crosswords break is a rule
that turns hits into misses.

Ambiguity is reported, never hidden: `reconstruct()` returns *every* grid
consistent with the lists, up to a limit, and says whether the limit bit.

Usage:
    python3 tools/reconstruct_grid.py cryptic-30066          # strip, re-derive
    python3 tools/reconstruct_grid.py cryptic-30066 --numberless
    python3 tools/reconstruct_grid.py --lights lights.json --cols 15 --rows 15
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import read_puzzle_file, resolve_puzzle  # noqa: E402

WHITE, BLACK = True, False

# Nodes are cell decisions. The cap exists so that a list no grid satisfies
# fails in seconds instead of exploring a 15x15 grid's 2**225 patterns. Two
# million is tens of seconds and finishes the large majority of 15x15s when
# the clue numbers are known; without them, reckon on five times the search
# and on most 15x15s not finishing at all.
DEFAULT_MAX_NODES = 2_000_000
DEFAULT_LIMIT = 40


class _Solver:
    def __init__(self, across, down, anum, dnum, cols, rows,
                 limit, symmetry, max_nodes, strict=True):
        self.across, self.down = across, down
        self.anum, self.dnum = anum, dnum
        self.na, self.nd = len(across), len(down)
        self.cols, self.rows = cols, rows
        self.limit, self.symmetry, self.max_nodes = limit, symmetry, max_nodes
        self.strict = strict
        self.prev_across = True     # there is no row above row 0 to pair with
        self.cells = [None] * (cols * rows)
        self.solutions = []
        self.nodes = 0
        self.hit_cap = False

        # Tail cursors: one past the last light the mirrored bottom rows have
        # already claimed. They walk down as the top rows are fixed, and the
        # head cursors (ai, di) must never pass them.
        self.at, self.dt = self.na, self.nd

        # The longest down light not yet spent from the head. One of length M
        # cannot start below row rows-M, so a row that ends with a long down
        # light still unplaced has already lost. An unknown length claims
        # nothing, which is why None reads as 0 here.
        self.deepest = [0] * (self.nd + 1)
        for i in range(self.nd - 1, -1, -1):
            self.deepest[i] = max(down[i] or 0, self.deepest[i + 1])

        # Room left. The across lights between the head and the tail have to
        # fit in the rows between them, and a row of `cols` cells holds only
        # so much: at most `cols` cells of across light, and at most one light
        # per three columns, since each needs two cells and a block after it.
        # Mirror rows only one apart with an across light still unspent is the
        # commonest way a promising top half turns out to be impossible.
        self.apre = [0] * (self.na + 1)
        for i, length in enumerate(across):
            self.apre[i + 1] = self.apre[i] + (length or 2)
        self.per_row = (cols + 1) // 3

    # --- the partial grid -------------------------------------------------
    # Off the board reads as BLACK and refuses to be written white, which is
    # what lets the edge of the grid and a block be the same case everywhere
    # below: a light ending at the border needs no special sentence.

    def get(self, x, y):
        if not (0 <= x < self.cols and 0 <= y < self.rows):
            return BLACK
        return self.cells[y * self.cols + x]

    def put(self, x, y, value, trail):
        if not self.place(x, y, value, trail):
            return False
        if not self.symmetry:
            return True
        return self.place(self.cols - 1 - x, self.rows - 1 - y, value, trail)

    def place(self, x, y, value, trail):
        if not (0 <= x < self.cols and 0 <= y < self.rows):
            return value == BLACK
        i = y * self.cols + x
        was = self.cells[i]
        if was is None:
            self.cells[i] = value
            trail.append(i)
            return True
        return was == value

    def undo(self, trail, mark):
        for i in trail[mark:]:
            self.cells[i] = None
        del trail[mark:]

    # --- the search -------------------------------------------------------

    def run(self):
        self.row(0, 0, 0, 1, [])
        return self.solutions

    def row(self, y, ai, di, n, trail):
        if self.nodes > self.max_nodes or len(self.solutions) >= self.limit:
            return
        if y == self.rows:
            if ai == self.na and di == self.nd and self.whole_grid_ok():
                self.solutions.append(self.snapshot())
            return
        self.column(y, 0, ai, di, n, trail)

    def column(self, y, x, ai, di, n, trail):
        """Decide what occupies column x of row y: a block, or a white run.

        The grid is read straight out of the flat cell list here rather than
        through get(): this is the innermost loop of the whole search, and the
        scan for how far a white run could reach runs on every node.
        """
        self.nodes += 1
        if self.nodes > self.max_nodes:
            self.hit_cap = True
            return
        if len(self.solutions) >= self.limit:
            return
        cols, cells = self.cols, self.cells
        if x >= cols:
            self.close_row(y, ai, di, n, trail)
            return
        base = y * cols
        here = cells[base + x]

        if here != WHITE:
            mark = len(trail)
            if self.put(x, y, BLACK, trail):
                self.column(y, x + 1, ai, di, n, trail)
            self.undo(trail, mark)

        if here == BLACK:
            return
        reach = 0
        while x + reach < cols and cells[base + x + reach] != BLACK:
            reach += 1
        # Only a couple of run lengths are worth trying. Two or more cells
        # start an across light, and across lights are numbered in row-major
        # order, so the run's length is pinned to the next unspent across
        # length. Everything else is a single unchecked cell belonging to the
        # down light through it.
        lengths = [1] if reach >= 1 else []
        if ai < self.na:
            wanted = self.across[ai]
            if wanted is None:
                lengths += list(range(2, reach + 1))
            elif 2 <= wanted <= reach:
                lengths.append(wanted)
        for length in lengths:
            if x + length < cols and cells[base + x + length] == WHITE:
                continue        # the run has to be closed by a block or the edge
            mark = len(trail)
            ok = True
            for i in range(length):
                if not self.put(x + i, y, WHITE, trail):
                    ok = False
                    break
            if ok:
                ok = self.put(x + length, y, BLACK, trail)
            if ok:
                self.in_run(y, x, length, 0, ai, di, n, trail)
            self.undo(trail, mark)

    def in_run(self, y, x0, length, i, ai, di, n, trail):
        """Match cell i of a white run against the light it would have to be.

        The row above is fully decided by the time we are here, so "does a
        down light start in this cell" is only open when the cell above is a
        block — and when clue numbers are known it is not open even then,
        because the number this cell must carry says whether a down light
        shares it.
        """
        if self.nodes > self.max_nodes or len(self.solutions) >= self.limit:
            return
        if i == length:
            self.column(y, x0 + length + 1, ai, di, n, trail)
            return
        x = x0 + i
        top_blocked = y == 0 or self.cells[(y - 1) * self.cols + x] == BLACK

        if i == 0 and length >= 2:
            # An across light starts here; it can only be the next one.
            if ai >= self.na:
                return
            want = self.across[ai]
            if want is not None and want != length:
                return
            if self.anum is not None and self.anum[ai] != n:
                return
            self.branch_down(y, x, length, i, ai + 1, di, n, top_blocked,
                             numbered=True, trail=trail)
            return

        if not top_blocked:
            # Mid-column: inside a down light already committed, so this cell
            # starts nothing and carries no number.
            self.in_run(y, x0, length, i + 1, ai, di, n, trail)
            return

        self.branch_down(y, x, length, i, ai, di, n, True,
                         numbered=False, trail=trail)

    def branch_down(self, y, x, length, i, ai, di, n, top_blocked, numbered,
                    trail):
        """Does a down light start in this cell? Try both answers that survive.

        `numbered` says the cell is already spoken for by an across light, so
        it takes number n either way; otherwise it takes a number only if a
        down light does start here, and if it does not it is an unchecked
        square in the across light it sits in.
        """
        x0 = x - i
        may_start = top_blocked and di < self.nd
        if may_start and self.anum is not None and not numbered \
                and ai < self.na and self.anum[ai] == n:
            may_start = False   # a down-only number is not one the acrosses claim
        if may_start and self.dnum is not None and self.dnum[di] != n:
            may_start = False

        if may_start:
            want = self.down[di]
            spans = [want] if want is not None else range(2, self.rows - y + 1)
            for down_len in spans:
                mark = len(trail)
                if self.commit_down(x, y, down_len, trail):
                    self.in_run(y, x0, length, i + 1, ai, di + 1, n + 1, trail)
                self.undo(trail, mark)

        # The other answer: no down light begins here. Always open, even when
        # the numbers say down light di is numbered n -- n may belong to a
        # cell further along the row.
        if numbered or length >= 2:
            # A one-cell run that starts no down light would be white with
            # blocks on all four sides.
            mark = len(trail)
            ok = self.put(x, y + 1, BLACK, trail) if top_blocked else True
            if ok:
                self.in_run(y, x0, length, i + 1, ai, di,
                            n + 1 if numbered else n, trail)
            self.undo(trail, mark)

    def commit_down(self, x, y, down_len, trail):
        """Paint a whole down light now, and the block that stops it."""
        if y + down_len > self.rows:
            return False
        for k in range(down_len):
            if not self.put(x, y + k, WHITE, trail):
                return False
        return self.put(x, y + down_len, BLACK, trail)

    def close_row(self, y, ai, di, n, trail):
        """Bank the row, and read the mirrored bottom row off the list's tail.

        Row y fixes row rows-1-y. That row's across lights are this row's runs
        in reverse, and the down lights that *start* there are the mirrors of
        the ones that *end* here — both fully known now, and both a suffix of
        their list, since numbering runs row-major. Checking them against the
        tail turns the bottom of the grid from something verified at the end
        of the search into something that constrains its first decision.
        """
        mirror = self.rows - 1 - y
        saved = (self.at, self.dt)
        ok = True
        if self.symmetry and mirror > y:
            for length in self.across_runs(y):
                self.at -= 1
                want = self.across[self.at] if self.at >= ai else False
                if want is not False and (want is None or want == length):
                    continue
                ok = False
                break
            if ok:
                for down_len in self.down_ends(y):
                    self.dt -= 1
                    want = self.down[self.dt] if self.dt >= di else False
                    if want is not False and (want is None or want == down_len):
                        continue
                    ok = False
                    break
        if ok and di < self.nd and self.deepest[di] > self.rows - (y + 1):
            ok = False          # a long down light with no row left to start in
        if ok:
            # Rows still free, and the across lights that must go in them.
            band = (mirror - 1 - y) if (self.symmetry and mirror > y) else (self.rows - 1 - y)
            top = self.at if (self.symmetry and mirror > y) else self.na
            left = top - ai
            if left > band * self.per_row \
                    or (self.apre[top] - self.apre[ai]) > band * self.cols \
                    or self.rows_needed(ai, top) > band:
                ok = False
            elif self.strict and left < band // 2:
                # Across-free rows cannot touch, so at least every other row
                # of the band carries a light, and each carries at least one.
                ok = False
        if ok and mirror > y + 1:
            ok = self.next_row_fits(y, ai, top)
        saved_across = self.prev_across
        if ok and self.strict:
            ok = self.row_ok(y)
        if ok:
            self.row(y + 1, ai, di, n, trail)
        self.prev_across = saved_across
        self.at, self.dt = saved

    def next_row_fits(self, y, lo, hi):
        """Look one row down before banking this one.

        Deciding row y writes every cell of row y+1 that sits under a white
        cell, because a white cell either continues a down light or is
        stopped by a block. So half of the next row is already on the board,
        and a white stretch of it that no remaining across light could ever
        be is a dead end -- found now, rather than after the next row has been
        searched a hundred thousand times. This is the single prune that made
        the hard 15x15s finish.
        """
        lengths = set()
        for i in range(lo, hi):
            if self.across[i] is None:
                return True     # an unknown length forgives any stretch
            lengths.add(self.across[i])
        longest = max(lengths) if lengths else 0
        ny, x = y + 1, 0
        while x < self.cols:
            if self.get(x, ny) != WHITE:
                x += 1
                continue
            start = x
            while x < self.cols and self.get(x, ny) == WHITE:
                x += 1
            length = x - start
            if length < 2:
                continue        # one cell is an unchecked square, always legal
            growable = (start > 0 and self.get(start - 1, ny) is None) \
                or (x < self.cols and self.get(x, ny) is None)
            if growable:
                if longest < length:
                    return False
            elif length not in lengths:
                return False
        return True

    def rows_needed(self, lo, hi):
        """Fewest rows that could hold across lights lo..hi-1, in this order.

        Lights are numbered row-major, so a row takes a contiguous group of
        them, and a group of k lights needs its lengths plus k-1 blocks. Greedy
        is exact for a contiguous partition, and it is the difference between
        "the lengths would fit somewhere" and "they would fit in the rows that
        are left".
        """
        if hi <= lo:
            return 0
        used, need = 0, 1
        for i in range(lo, hi):
            # A light needs its own cells and a block after it, so k lights in
            # one row cost sum(length) + k - 1, which is sum(length + 1) - 1.
            cost = (self.across[i] or 2) + 1
            if used + cost > self.cols + 1:
                need += 1
                used = cost
            else:
                used += cost
        return need

    # --- the conventions the corpus actually obeys ------------------------
    # Each was counted over all 15,931 published grids before it was written
    # down here, and each holds for every one of them. They are what stops the
    # search wandering into grids that are numbered correctly and are not
    # crosswords -- an all-black row is the cheap example, and without these
    # the search spends its whole budget under one.

    def row_ok(self, y):
        """Two rules about a single row, checked the moment it is decided."""
        white = sum(1 for x in range(self.cols) if self.get(x, y) == WHITE)
        if white < 2:
            return False        # no row of any puzzle has fewer than two
        has_across = bool(self.across_runs(y))
        if not has_across and not self.prev_across:
            return False        # no puzzle has two such rows in a row
        self.prev_across = has_across
        return True

    def whole_grid_ok(self):
        """The same rules down the columns, plus one connected grid.

        Columns cannot be judged until the last row is placed, so these do not
        prune -- they cut the answer down, which is what matters when the clue
        numbers are missing and several grids fit. The rules themselves live in
        conventions_broken(), so that what a finished grid is judged against and
        what a miss is explained by cannot drift apart.
        """
        if not self.strict:
            return True
        return not conventions_broken(self.snapshot(), symmetry=False)

    def snapshot(self):
        return tuple(
            "".join("." if self.cells[y * self.cols + x] else "#"
                    for x in range(self.cols))
            for y in range(self.rows))

    def across_runs(self, y):
        """Lengths of row y's across lights, left to right, the row now fixed.

        Left to right here is right to left in the mirrored row, which is why
        the caller walks the tail of the across list backwards as it goes.
        """
        out, run = [], 0
        row = self.cells[y * self.cols:(y + 1) * self.cols]
        for cell in row + [BLACK]:
            if cell == WHITE:
                run += 1
            else:
                if run >= 2:
                    out.append(run)
                run = 0
        return out

    def down_ends(self, y):
        """Lengths of the down lights that finish in row y, left to right."""
        out = []
        for x in range(self.cols):
            if self.get(x, y) != WHITE or self.get(x, y + 1) == WHITE:
                continue
            k = 1
            while self.get(x, y - k) == WHITE:
                k += 1
            if k >= 2:
                out.append(k)
        return out


def lights_from_grid(grid):
    """The forward function: what clue list would this grid print?

    Row-major scan; a cell takes the next number when it starts an across
    light (two or more cells, a block or the edge to its left) or a down one.
    Everything in this module exists to invert exactly this.
    """
    rows, cols = len(grid), len(grid[0])
    white = [[c == "." for c in row] for row in grid]
    lights, number = [], 0
    for y in range(rows):
        for x in range(cols):
            if not white[y][x]:
                continue
            across = (x == 0 or not white[y][x - 1]) \
                and x + 1 < cols and white[y][x + 1]
            down = (y == 0 or not white[y - 1][x]) \
                and y + 1 < rows and white[y + 1][x]
            if not (across or down):
                continue
            number += 1
            if across:
                run = 1
                while x + run < cols and white[y][x + run]:
                    run += 1
                lights.append((number, "across", run))
            if down:
                run = 1
                while y + run < rows and white[y + run][x]:
                    run += 1
                lights.append((number, "down", run))
    return lights


def conventions_broken(grid, symmetry=True):
    """Which of this module's rules a finished grid breaks; empty means none.

    The search enforces these, so a published grid that breaks one is a
    published grid the search cannot return, and this is the sentence that
    says which. It is what tools/test_reconstruct_grid.sh prints beside a
    miss, so a miss never has to be investigated by hand twice.
    """
    rows, cols = len(grid), len(grid[0])
    white = [[c == "." for c in row] for row in grid]
    broken = []
    if symmetry and any(white[y][x] != white[rows - 1 - y][cols - 1 - x]
                        for y in range(rows) for x in range(cols)):
        broken.append("not 180-degree symmetric")

    def scan(lines, what):
        bare = 0
        for line in lines:
            if sum(line) < 2:
                broken.append(f"a {what} has fewer than two white cells")
                return
            longest, run = 0, 0
            for cell in list(line) + [False]:
                run = run + 1 if cell else 0
                longest = max(longest, run)
            bare = bare + 1 if longest < 2 else 0
            if bare >= 2:
                broken.append(f"two adjacent {what}s with no light along them")
                return

    scan(white, "row")
    scan([[white[y][x] for y in range(rows)] for x in range(cols)], "column")

    start = next(((x, y) for y in range(rows) for x in range(cols)
                  if white[y][x]), None)
    if start is not None:
        seen, stack = {start}, [start]
        while stack:
            x, y = stack.pop()
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < cols and 0 <= ny < rows and white[ny][nx] \
                        and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        if len(seen) != sum(row.count(True) for row in white):
            broken.append("white cells cut off from the rest of the grid")
    return broken


def parse_lights(spec):
    """Normalise either input shape to (across, down, across_nums, down_nums).

    Numbers come back as None when the caller had none, which is the common
    case for anything that has been through OCR.
    """
    if isinstance(spec, dict):
        across = [None if v is None else int(v) for v in spec.get("across", [])]
        down = [None if v is None else int(v) for v in spec.get("down", [])]
        anum = spec.get("acrossNumbers")
        dnum = spec.get("downNumbers")
        return across, down, anum, dnum

    seen = {"across": {}, "down": {}}
    for number, direction, length in spec:
        d = str(direction).lower()
        if d not in seen:
            raise ValueError(f"light {number}: unknown direction {direction!r}")
        if int(number) in seen[d]:
            raise ValueError(f"two {d} lights numbered {number}")
        seen[d][int(number)] = None if length is None else int(length)
    anum = sorted(seen["across"])
    dnum = sorted(seen["down"])
    return ([seen["across"][k] for k in anum], [seen["down"][k] for k in dnum],
            anum, dnum)


def reconstruct(spec, cols=15, rows=15, limit=DEFAULT_LIMIT, symmetry=True,
                max_nodes=DEFAULT_MAX_NODES, fallback=False, strict=True):
    """Every grid whose numbering would print these lights.

    Returns (solutions, info). Each solution is a tuple of row strings, '#'
    for a block and '.' for a letter. `info` says how the answer was reached:
    whether symmetry was assumed, how much search it took, and whether a limit
    cut the enumeration short — a caller handed one grid deserves to know
    whether it is the only one or merely the only one we looked for.

    `fallback` re-runs without symmetry, but only when the symmetric pass
    both finished and found nothing — which is the shape an asymmetric grid
    makes, and not the shape a budget running out makes. Spending a second
    full budget on a search that has already proved it cannot finish the
    easier version is the one way this call can waste a minute for nothing.
    About one puzzle in 450 here is asymmetric; on a 13x13 the unconstrained
    search still lands in a tenth of a second, on a 23x23 it does not land.
    """
    across, down, anum, dnum = parse_lights(spec)
    if not across and not down:
        raise ValueError("no lights given")
    solver = _Solver(across, down, anum, dnum, cols, rows,
                     limit, bool(symmetry), max_nodes, strict)
    found = solver.run()
    info = {"symmetric": bool(symmetry), "nodes": solver.nodes,
            "truncated": solver.hit_cap or len(found) >= limit}
    if found or not (symmetry and fallback) or info["truncated"]:
        return found, info
    loose = _Solver(across, down, anum, dnum, cols, rows,
                    limit, False, max_nodes, strict)
    found = loose.run()
    return found, {"symmetric": False, "nodes": solver.nodes + loose.nodes,
                   "truncated": loose.hit_cap or len(found) >= limit}


def lights_of(puzzle, numbered=True):
    """The clue list's own metadata, in printed order: what a reader has."""
    order = {"across": 0, "down": 1}
    entries = sorted(puzzle["entries"],
                     key=lambda e: (e["number"], order[e["direction"]]))
    if numbered:
        return [(e["number"], e["direction"], e["length"]) for e in entries]
    return {d: [e["length"] for e in entries if e["direction"] == d]
            for d in ("across", "down")}


def grid_of(puzzle):
    """The published black squares, as reconstruct() would render them."""
    cols, rows = puzzle["dimensions"]["cols"], puzzle["dimensions"]["rows"]
    white = [[False] * cols for _ in range(rows)]
    for e in puzzle["entries"]:
        x, y = e["position"]["x"], e["position"]["y"]
        for i in range(e["length"]):
            cx, cy = (x + i, y) if e["direction"] == "across" else (x, y + i)
            if 0 <= cx < cols and 0 <= cy < rows:
                white[cy][cx] = True
    return tuple("".join("." if c else "#" for c in row) for row in white)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("puzzle", nargs="?", help="puzzle id to strip and re-derive")
    ap.add_argument("--lights", help='JSON file: {"across": [...], "down": [...]}'
                                     ' or [[number, direction, length], ...]')
    ap.add_argument("--numberless", action="store_true",
                    help="throw the clue numbers away before reconstructing")
    ap.add_argument("--cols", type=int, default=15)
    ap.add_argument("--rows", type=int, default=15)
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--no-symmetry", action="store_true")
    ap.add_argument("--fallback", action="store_true",
                    help="retry without symmetry if the symmetric pass is empty")
    ap.add_argument("--max-nodes", type=int, default=DEFAULT_MAX_NODES)
    args = ap.parse_args(argv)

    if bool(args.puzzle) == bool(args.lights):
        ap.error("give either a puzzle id or --lights, not both")

    published = None
    if args.puzzle:
        puzzle = read_puzzle_file(resolve_puzzle(args.puzzle))
        spec = lights_of(puzzle, numbered=not args.numberless)
        published = grid_of(puzzle)
        cols, rows = puzzle["dimensions"]["cols"], puzzle["dimensions"]["rows"]
    else:
        spec = json.loads(Path(args.lights).read_text(encoding="utf-8"))
        cols, rows = args.cols, args.rows

    found, info = reconstruct(spec, cols=cols, rows=rows, limit=args.limit,
                              symmetry=not args.no_symmetry,
                              fallback=args.fallback, max_nodes=args.max_nodes)

    print(f"{cols}x{rows}: {len(found)} grid(s), {info['nodes']} nodes"
          + ("" if info.get("symmetric") else ", symmetry not assumed")
          + (", search truncated" if info.get("truncated") else ""))
    for i, grid in enumerate(found, 1):
        mark = "  <- published" if published is not None and grid == published else ""
        print(f"\n  grid {i}{mark}")
        for row in grid:
            print("    " + " ".join(row))
    if published is None:
        return 0
    print()
    if not found:
        print("MISS: no grid found")
    elif published not in found:
        print("MISS: the published grid is not among them")
    elif len(found) == 1:
        print("exact: the published grid, uniquely")
    else:
        print(f"ambiguous: the published grid is 1 of {len(found)}")
    return 0 if published in found else 1


if __name__ == "__main__":
    sys.exit(main())
