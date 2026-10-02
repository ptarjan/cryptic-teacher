"""What is unusual about each puzzle (pangram, barred grid, special rules…), read off its file.

fetch_puzzle.reindex() writes each puzzle's tags into the index, and the app
badges them and filters the picker by them.

Every tag is a fact the file states, never a judgement: a pangram is 26 letters
counted in the grid, not a guess that the setter meant one. A feature with no
such fact behind it gets no tag. A nina (a message hidden along the edge or a
diagonal) is the usual case: any edge spells something if you look for words in
it, and the puzzles that announce one already say so in a preamble, which tags
them "special rules".
"""

import re
import string

# A grid where every letter appears at least n times is an n-fold pangram,
# tagged with the word for n. Past the last word the tag says the last word,
# which is still true: "at least". independent-9740 (Maize) is a quintuple.
MULTIPLES = [("double", "two"), ("triple", "three"), ("quadruple", "four"),
             ("quintuple", "five"), ("sextuple", "six"), ("septuple", "seven"),
             ("octuple", "eight")]


def pangram_key(times):
    """The tag for a grid whose rarest letter appears `times` (>= 1) times."""
    if times < 2:
        return "pangram"
    return MULTIPLES[min(times, len(MULTIPLES) + 1) - 2][0] + "-pangram"


# Label and blurb per tag, in the order the app shows them. `implies` names a
# weaker tag this one includes, so filtering by "pangram" finds the doubles too
# while a double carries one badge, not two.
TAGS = {
    "special-rules": {
        "label": "special rules",
        "blurb": "The note above the clues changes how the puzzle works: some "
                 "answers share a theme and have no definition, or go into the "
                 "grid altered or jigsaw-wise.",
    },
    "unclued": {
        "label": "unclued answers",
        "blurb": "Some answers have no clue of their own. The theme, the note "
                 "above the clues or the crossing letters give them.",
    },
    "alphabetical": {
        "label": "alphabetical",
        "blurb": "Every letter of the alphabet starts at least one answer.",
    },
    **{f"{word}-pangram": {
        "label": f"{word} pangram",
        "blurb": f"Every letter of the alphabet appears at least {n} times in "
                 "the completed grid.",
        "implies": "pangram",
    } for word, n in reversed(MULTIPLES)},
    "pangram": {
        "label": "pangram",
        "blurb": "Every letter of the alphabet appears somewhere in the completed "
                 "grid. When Q, X or Z is still missing, the answer you are stuck "
                 "on may hold it.",
    },
    "barred": {
        "label": "barred grid",
        "blurb": "Bars between squares end the answers instead of black squares, "
                 "so almost every letter is crossed by a second answer.",
    },
    "asymmetric": {
        "label": "asymmetric grid",
        "blurb": "The black squares do not repeat when the grid is turned upside "
                 "down, as they do in nearly every published grid.",
    },
    "big-grid": {
        "label": "big grid",
        "blurb": "A bigger grid than its series usually prints.",
    },
    "letters-given": {
        "label": "letters given",
        "blurb": "Some letters are printed in the grid before you start.",
    },
}

# A preamble that sets a rule, as opposed to one that corrects a clue, thanks a
# sponsor or links a PDF. Phrases only a rule-setting note uses: every one of
# the corpus's preambles that matches was read and sets a rule. A rule-setting
# note in other words goes untagged, which is the safe side.
RULE_PHRASES = re.compile(
    r"not (?:further |otherwise )?defined|(?:are|is) undefined|undefined in"
    r"|of a kind|of a set|(?:no|lacks?(?: a| any)?|without(?: a| any)?) (?:further )?definition"
    r"|have no definition|similarly defined|unclued|jigsaw|perimeter|shaded squares"
    r"|round the edge|in the diagonals|before (?:being )?entered|before entry|be entered"
    r"|thematic|themed|are linked|share a connection|something in common",
    re.IGNORECASE)

# More answers than this and covering every initial stops being a feature. The
# corpus splits cleanly: no puzzle of 40 answers or fewer covers 22 to 24
# initials, and every one that covers 26 is an alphabet puzzle.
ALPHABETICAL_MAX_ANSWERS = 40

# The share of a series its commonest grid size must hold to be its usual one.
USUAL_SHARE = 0.8


def entry_id(e):
    return f"{e['number']}-{e['direction']}"


def continuations(entries):
    """The lights a linked answer continues onto: they are part of their
    leader's answer, not answers of their own."""
    return {gid for e in entries for gid in e.get("group", [])[1:]}


def entry_cells(e):
    x, y = e["position"]["x"], e["position"]["y"]
    across = e["direction"] == "across"
    return [(x + i, y) if across else (x, y + i) for i in range(e["length"])]


def grid_letters(puzzle):
    """{(x, y): letter} for every white square, or None while any answer is
    unknown. Each square once, however many lights cross it."""
    grid = {}
    for e in puzzle["entries"]:
        if not e.get("solution"):
            return None
        grid.update(zip(entry_cells(e), e["solution"]))
    for light in puzzle.get("unclued", []):
        if "solution" not in light:
            return None
        grid.update(zip(((c["x"], c["y"]) for c in light["cells"]), light["solution"]))
    return grid


def trusted_answers(puzzle):
    """Letters a tag may count. A model's solve is crossing-checked but can
    still hold a wrong letter, and one wrong Z is a false pangram."""
    return puzzle.get("solutions", {}).get("origin") not in ("model", "unsolved")


def pangram_tag(puzzle):
    grid = grid_letters(puzzle) if trusted_answers(puzzle) else None
    if not grid:
        return None
    letters = list(grid.values())
    least = min(letters.count(c) for c in string.ascii_uppercase)
    return pangram_key(least) if least else None


def is_alphabetical(puzzle):
    cont = continuations(puzzle["entries"])
    answers = [e for e in puzzle["entries"] if entry_id(e) not in cont]
    if len(answers) > ALPHABETICAL_MAX_ANSWERS or not all(e.get("solution") for e in answers):
        return False
    return len({e["solution"][0] for e in answers}) == 26


def has_unclued(puzzle):
    """Unclued lights, or answers the paper printed a count for and no words.
    A count with no words for a few answers is the setter's choice. Most of a
    puzzle's clues blank is a feed that lost them (cryptic-22917 prints its
    clues in a PDF), which says nothing about the puzzle."""
    if "unclued" in puzzle:
        return True
    cont = continuations(puzzle["entries"])
    answers = [e for e in puzzle["entries"] if entry_id(e) not in cont]
    blank = [e for e in answers if e["clue"].get("missing")]
    return (any("enumeration" in e["clue"] for e in blank)
            and 2 * len(blank) < len(answers))


def grid_consistent(puzzle, white):
    """Every run of two or more white squares is exactly one stored light. A
    grid that fails has lost or misplaced a light, and its shape proves
    nothing. Every light lies on the board: no writer can store one that does
    not (puzzle_integrity.check_grid)."""
    lights = {(e["direction"], e["position"]["x"], e["position"]["y"], e["length"])
              for e in puzzle["entries"]}
    runs = set()
    for direction, (dx, dy) in (("across", (1, 0)), ("down", (0, 1))):
        for x, y in white:
            if (x - dx, y - dy) in white:
                continue
            n = 1
            while (x + n * dx, y + n * dy) in white:
                n += 1
            if n > 1:
                runs.add((direction, x, y, n))
    return runs == lights


def is_asymmetric(puzzle):
    """A blocked grid as the paper printed it that a half turn does not map
    onto itself. A grid rebuilt here from a blog's clue list is the rebuild's
    shape, not the paper's, so only a published one counts."""
    if "bars" in puzzle or "unclued" in puzzle:
        return False
    if puzzle.get("source", {}).get("gridOrigin") != "published":
        return False
    white = {c for e in puzzle["entries"] for c in entry_cells(e)}
    if not grid_consistent(puzzle, white):
        return False
    rows, cols = puzzle["dimensions"]["rows"], puzzle["dimensions"]["cols"]
    return any((cols - 1 - x, rows - 1 - y) not in white for x, y in white)


def tags(puzzle):
    """The puzzle's tags, in TAGS order, all but big-grid: that one compares a
    puzzle with the rest of its series, so reindex() adds it (big_grids)."""
    found = {
        "special-rules": bool(RULE_PHRASES.search(puzzle.get("preamble", ""))),
        "unclued": has_unclued(puzzle),
        "alphabetical": is_alphabetical(puzzle),
        "barred": "bars" in puzzle,
        "asymmetric": is_asymmetric(puzzle),
        "letters-given": "printed" in puzzle,
    }
    pangram = pangram_tag(puzzle)
    if pangram:
        found[pangram] = True
    return [k for k in TAGS if found.get(k)]


def grid_area(puzzle):
    return puzzle["dimensions"]["rows"] * puzzle["dimensions"]["cols"]


def big_grids(areas):
    """The ids of the puzzles whose grid is bigger than their series' usual
    size. `areas` is [(id, series, rows * cols)] over the corpus. A series
    whose commonest size holds less than USUAL_SHARE of it has no usual size
    (the Listener changes shape every week), so none of it is tagged."""
    by_series = {}
    for _, series, area in areas:
        counts = by_series.setdefault(series, {})
        counts[area] = counts.get(area, 0) + 1
    usual = {}
    for series, counts in by_series.items():
        area = max(counts, key=lambda a: (counts[a], -a))
        if counts[area] >= USUAL_SHARE * sum(counts.values()):
            usual[series] = area
    return {pid for pid, series, area in areas
            if series in usual and area > usual[series]}
