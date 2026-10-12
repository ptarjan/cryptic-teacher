#!/usr/bin/env python3
"""Recover a barred crossword's bars from its numbered answers.

A barred grid has no black squares: every cell holds a letter, and thick
bars between cells end the lights. Numbering still runs row-major over the
cells where a light starts, so the numbers and the answers pin the layout
down: number k sits on the k-th light start, its across answer runs right
from there and its down answer runs down, and wherever an across and a down
light share a cell they must write the same letter.

The search places the numbers in order. Every later light starts at a later
cell and only covers cells at or after its start, so a cell before the next
number that no light covers yet can never be covered. Every cell of a
Mephisto holds a letter, so that cell is a dead end, and the search almost
never branches.

Once the lights are placed the bars follow: two neighbouring cells have a bar
between them exactly when no one light runs through both. A solution is the
`bars` list of the puzzle format: one string per row, a character per cell,
"r" for a bar on its right, "b" for a bar below it, "+" for both, "." for none.
The grid's outer edge is never written.
"""
import re
from collections import defaultdict

SIZE = 12


def shape(size):
    """(cols, rows) for a size: a side for a square grid, or (cols, rows)."""
    return (size, size) if isinstance(size, int) else tuple(size)


def letters(answer):
    return re.sub(r"[^A-Z]", "", (answer or "").upper())


def lights_by_number(entries):
    """{number: {"across": word, "down": word}}, or None when the list is unusable."""
    out = candidates_by_number(entries)
    if out is None or any(len(c) > 1 for slot in out.values() for c in slot.values()):
        return None
    return {n: {d: c[0] for d, c in slot.items()} for n, slot in out.items()}


def candidates_by_number(entries):
    """{number: {"across": [word, ...], "down": [...]}}: an entry's `answer`, or
    its `answers` where what goes in the grid is one of several (a Listener
    whose preamble moves a letter somewhere in the answer). None when unusable."""
    out = {}
    for e in entries:
        words = [letters(w) for w in (e["answers"] if "answers" in e else [e.get("answer")])]
        words = list(dict.fromkeys(words))
        if not words or any(len(w) < 2 or len(w) != len(words[0]) for w in words):
            return None
        slot = out.setdefault(e["number"], {})
        if e["direction"] in slot:
            return None
        slot[e["direction"]] = words
    return out


def solve(entries, size=SIZE, cap=2):
    """Every layout (up to `cap`) as {number: cell index}; None when unusable."""
    found = solve_words(entries, size, cap)
    return None if found is None else [place for place, _ in found]


def solve_words(entries, size=SIZE, cap=2):
    """Every fill (up to `cap`) as ({number: cell index}, {(number, direction):
    word}), each light's word one of its candidates; None when unusable."""
    by_number = candidates_by_number(entries)
    if not by_number:
        return None
    numbers = sorted(by_number)
    cols, rows = shape(size)
    n = cols * rows
    grid = [None] * n
    across = [False] * n
    down = [False] * n
    found = []
    place = {}
    words = {}

    def covered(c):
        return across[c] or down[c]

    def put(p, word, step):
        """Write word from p in steps of `step`; the cells it newly filled, or None."""
        wrote = []
        for i, ch in enumerate(word):
            c = p + i * step
            if grid[c] is None:
                grid[c] = ch
                wrote.append(c)
            elif grid[c] != ch:
                for w in wrote:
                    grid[w] = None
                return None
        return wrote

    def go(k, prev):
        if len(found) >= cap:
            return
        if k == len(numbers):
            if all(covered(c) for c in range(prev + 1, n)):
                found.append((dict(place), dict(words)))
            return
        num = numbers[k]
        cands_a = by_number[num].get("across") or [None]
        cands_d = by_number[num].get("down") or [None]
        a, d = cands_a[0], cands_d[0]
        for p in range(prev + 1, n):
            if p > prev + 1 and not covered(p - 1):
                return
            r, col = divmod(p, cols)
            if a and (col + len(a) > cols or any(across[p + i] for i in range(len(a)))):
                continue
            if d and (r + len(d) > rows or any(down[p + i * cols] for i in range(len(d)))):
                continue
            for a_word in cands_a:
                for d_word in cands_d:
                    place_words(k, p, num, a_word, d_word)
                    if len(found) >= cap:
                        return

    def place_words(k, p, num, a, d):
        """Write light k's words at p and search on from there."""
        wa = put(p, a, 1) if a else []
        if wa is None:
            return
        wd = put(p, d, cols) if d else []
        if wd is None:
            for w in wa:
                grid[w] = None
            return
        if a:
            for i in range(len(a)):
                across[p + i] = True
        if d:
            for i in range(len(d)):
                down[p + i * cols] = True
        place[num] = p
        if a:
            words[(num, "across")] = a
        if d:
            words[(num, "down")] = d
        go(k + 1, p)
        del place[num]
        words.pop((num, "across"), None)
        words.pop((num, "down"), None)
        if a:
            for i in range(len(a)):
                across[p + i] = False
        if d:
            for i in range(len(d)):
                down[p + i * cols] = False
        for w in wa + wd:
            grid[w] = None

    go(0, -1)
    return found


def solve_unclued(entries, pool, size=SIZE, cap=2):
    """solve_words() for a grid that also holds unclued, unnumbered lights:
    every fill (up to `cap`) as ({number: cell index}, {(number, direction):
    word}, [(word, cell index, direction)]). `pool` is the unclued words, each
    used once (Listener No 3985's eleven thematic entries: the paper numbers
    only the clued lights, so they start on any square, numbered or not).

    The squares are visited in order. Each may take the next number's lights
    and may start a pool word in a direction nothing else starts or runs
    through; after that it must be covered, since no later light reaches
    back to it. None when the clued entries are unusable."""
    by_number = candidates_by_number(entries)
    if not by_number:
        return None
    numbers = sorted(by_number)
    cols, rows = shape(size)
    n = cols * rows
    grid = [None] * n
    runs = {"across": [False] * n, "down": [False] * n}
    step = {"across": 1, "down": cols}
    left = defaultdict(int)
    for w in pool:
        left[letters(w)] += 1
    found, place, words, unclued = [], {}, {}, []
    # Every square is covered once or twice, so the lights' letters fix how
    # many are covered once: a square's cover is final once the walk passes
    # it, and a fill past that many is dead.
    total = sum(len(slot[d][0]) for slot in by_number.values() for d in slot) + \
        sum(len(letters(w)) for w in pool)
    unchecked_left = [2 * n - total]
    if not 0 <= unchecked_left[0] <= n:
        return []

    def fits(c, direction, word):
        r, col = divmod(c, cols)
        if (col + len(word) > cols) if direction == "across" else (r + len(word) > rows):
            return False
        return not any(runs[direction][c + i * step[direction]] for i in range(len(word)))

    def put(c, direction, word):
        """Write word from c; the cells it newly filled, or None on a clash."""
        wrote = []
        for i, ch in enumerate(word):
            q = c + i * step[direction]
            if grid[q] is None:
                grid[q] = ch
                wrote.append(q)
            elif grid[q] != ch:
                for w in wrote:
                    grid[w] = None
                return None
        for i in range(len(word)):
            runs[direction][c + i * step[direction]] = True
        return wrote

    def take(c, direction, word, wrote):
        for i in range(len(word)):
            runs[direction][c + i * step[direction]] = False
        for w in wrote:
            grid[w] = None

    def starts(c, k):
        """[(number or None, {direction: word}, pooled directions)] that may start at c."""
        out = []
        clued = [({}, None)]
        if k < len(numbers):
            num = numbers[k]
            slot = by_number[num]
            for a in slot.get("across") or [None]:
                for d in slot.get("down") or [None]:
                    lights = {dn: w for dn, w in (("across", a), ("down", d)) if w}
                    if all(fits(c, dn, w) for dn, w in lights.items()):
                        clued.insert(len(clued) - 1, (lights, num))
        for lights, num in clued:
            free = [dn for dn in ("across", "down") if dn not in lights]
            options = {dn: [None] + [w for w, k2 in left.items() if k2 and fits(c, dn, w)]
                       for dn in free}
            for a in options.get("across", [None]):
                for d in options.get("down", [None]):
                    if a and d and a == d and left[a] < 2:
                        continue
                    pooled = {dn: w for dn, w in (("across", a), ("down", d)) if w}
                    out.append((num, {**lights, **pooled}, set(pooled)))
        return out

    def go(c, k):
        if len(found) >= cap:
            return
        if c == n:
            if k == len(numbers) and not any(left.values()):
                found.append((dict(place), dict(words), list(unclued)))
            return
        for num, lights, pooled in starts(c, k):
            done = []
            for dn, w in lights.items():
                wrote = put(c, dn, w)
                if wrote is None:
                    break
                done.append((dn, w, wrote))
            else:
                once = runs["across"][c] != runs["down"][c]
                if (runs["across"][c] or runs["down"][c]) and unchecked_left[0] >= once:
                    unchecked_left[0] -= once
                    if num is not None:
                        place[num] = c
                    for dn, w in lights.items():
                        if dn in pooled:
                            left[w] -= 1
                            unclued.append((w, c, dn))
                        else:
                            words[(num, dn)] = w
                    go(c + 1, k + (num is not None))
                    if num is not None:
                        del place[num]
                    for dn, w in lights.items():
                        if dn in pooled:
                            left[w] += 1
                            unclued.pop()
                        else:
                            del words[(num, dn)]
                    unchecked_left[0] += once
            for dn, w, wrote in reversed(done):
                take(c, dn, w, wrote)
            if len(found) >= cap:
                return

    go(0, 0)
    return found


def layout(entries, placement, size=SIZE, words=None):
    """(rows of letters, bars) for one placement from solve(), or from
    solve_words() with the words it chose."""
    if words is None:
        by_number = lights_by_number(entries)
    else:
        by_number = defaultdict(dict)
        for (num, direction), word in words.items():
            by_number[num][direction] = word
    cols, nrows = shape(size)
    n = cols * nrows
    grid = [None] * n
    a_id = [None] * n
    d_id = [None] * n
    for num, p in placement.items():
        for direction, step, ids in (("across", 1, a_id), ("down", cols, d_id)):
            word = by_number[num].get(direction)
            for i, ch in enumerate(word or ""):
                grid[p + i * step] = ch
                ids[p + i * step] = num
    rows = ["".join(grid[r * cols:(r + 1) * cols]) for r in range(nrows)]
    bars = []
    for r in range(nrows):
        line = []
        for c in range(cols):
            i = r * cols + c
            right = c + 1 < cols and (a_id[i] is None or a_id[i] != a_id[i + 1])
            below = r + 1 < nrows and (d_id[i] is None or d_id[i] != d_id[i + cols])
            line.append("+" if right and below else "r" if right else "b" if below else ".")
        bars.append("".join(line))
    return rows, bars
