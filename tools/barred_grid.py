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
    n = size * size
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
            r, col = divmod(p, size)
            if a and (col + len(a) > size or any(across[p + i] for i in range(len(a)))):
                continue
            if d and (r + len(d) > size or any(down[p + i * size] for i in range(len(d)))):
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
        wd = put(p, d, size) if d else []
        if wd is None:
            for w in wa:
                grid[w] = None
            return
        if a:
            for i in range(len(a)):
                across[p + i] = True
        if d:
            for i in range(len(d)):
                down[p + i * size] = True
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
                down[p + i * size] = False
        for w in wa + wd:
            grid[w] = None

    go(0, -1)
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
    n = size * size
    grid = [None] * n
    a_id = [None] * n
    d_id = [None] * n
    for num, p in placement.items():
        for direction, step, ids in (("across", 1, a_id), ("down", size, d_id)):
            word = by_number[num].get(direction)
            for i, ch in enumerate(word or ""):
                grid[p + i * step] = ch
                ids[p + i * step] = num
    rows = ["".join(grid[r * size:(r + 1) * size]) for r in range(size)]
    bars = []
    for r in range(size):
        line = []
        for c in range(size):
            i = r * size + c
            right = c + 1 < size and (a_id[i] is None or a_id[i] != a_id[i + 1])
            below = r + 1 < size and (d_id[i] is None or d_id[i] != d_id[i + size])
            line.append("+" if right and below else "r" if right else "b" if below else ".")
        bars.append("".join(line))
    return rows, bars
