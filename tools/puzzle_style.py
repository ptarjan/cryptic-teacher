"""Whether a puzzle is a cryptic at all: style() is "straight" for a puzzle
whose clues are definitions with no wordplay, else None.

Early Listeners and Times puzzles (1930) and a run of 1970 Guardian puzzles
are general-knowledge or definition crosswords: "Quickly" = PRESTO, "Fat" =
LARD, or a punning definition with nothing to take apart. fetch_puzzle's
index row carries `style`; the app notes it above the clues and drops the
indicator, clue-type and blocks rungs; difficulty.py leaves the puzzle
unrated, clue_types' family counts skip it, and the hinting queues
(prereset_plan.py) take it last.

Two tests, the annotation's first:
  - annotated (ANNOTATED_SHARE of its clues): at least PLAIN_SHARE of them are
    a cryptic or double definition with no indicator, and at least
    SHORT_SHARE are SHORT_WORDS words or fewer. The short floor keeps out
    the Azed specials, whose clues carry their wordplay in the special rule
    and so are typed cryptic_definition, at three to nine words each.
  - otherwise, dated before TEXT_BEFORE: at least TEXT_SHORT_SHARE of its
    clues SHORT_WORDS words or fewer. Modern cryptics can be that terse
    (cryptic-28519, 2021: "Guy put off" = STAY), so the clue text alone
    decides only for the early puzzles.
Measured over the corpus on 2026-10-12: no annotated puzzle the first test
passes is a cryptic by eye, and the second agrees with the first on every
annotated puzzle before TEXT_BEFORE.
"""
import re

STRAIGHT = "straight"
PLAIN_TYPES = {"cryptic_definition", "double_definition"}
MIN_CLUES = 8
ANNOTATED_SHARE = 0.8
PLAIN_SHARE = 0.85
SHORT_WORDS = 3
SHORT_SHARE = 0.15
TEXT_BEFORE = "1960"
TEXT_SHORT_SHARE = 0.4

WORD = re.compile(r"[A-Za-z']+")
# "See 9", "See 3 across": a pointer to another clue, short by nature.
SEE = re.compile(r"\s*see\b[^A-Za-z]*\d+\s*(?:across|down|ac|dn)?\.?\s*", re.IGNORECASE)


def clue_texts(puzzle):
    """The clues that say something: no blanks, no "See 9" pointers."""
    texts = ((e.get("clue") or {}).get("text") or "" for e in puzzle.get("entries") or ())
    return [t for t in texts if t.strip() and not SEE.fullmatch(t)]


def is_plain(ann):
    """A clue annotated as a definition with nothing to take apart."""
    types = ann.get("type")
    return isinstance(types, list) and bool(types) and set(types) <= PLAIN_TYPES and not ann.get("indicators")


def style(puzzle):
    # A numerical puzzle (Listener No 111: every answer a number, every clue
    # arithmetic) has no wordplay at all: the hint ladder is the definition, and
    # the hint queue takes it last, as it does every straight puzzle.
    if puzzle.get("numeric") is True:
        return STRAIGHT
    texts = clue_texts(puzzle)
    if len(texts) < MIN_CLUES:
        return None
    short = sum(len(WORD.findall(t)) <= SHORT_WORDS for t in texts) / len(texts)
    # type and indicators are derived: a format v2 file's come from view()
    # (a legacy or already viewed puzzle comes back as it is).
    import annotation
    puzzle = annotation.view_puzzle(puzzle)
    anns = [e["annotation"] for e in puzzle["entries"]
            if isinstance(e.get("annotation"), dict) and isinstance(e["annotation"].get("type"), list)]
    if len(anns) >= ANNOTATED_SHARE * len(texts):
        plain = sum(map(is_plain, anns)) / len(anns)
        return STRAIGHT if plain >= PLAIN_SHARE and short >= SHORT_SHARE else None
    date = puzzle.get("date") or ""
    if date and date < TEXT_BEFORE and short >= TEXT_SHORT_SHARE:
        return STRAIGHT
    return None


def is_straight(puzzle):
    return style(puzzle) == STRAIGHT


if __name__ == "__main__":
    import sys
    from collections import Counter

    import parallel
    from fetch_puzzle import read_puzzle_view
    from puzzle_paths import puzzle_files

    def row(path):
        p = read_puzzle_view(path)
        return p["id"], p.get("series"), p.get("date") or "", style(p)

    hits = [r for r in parallel.pmap(row, puzzle_files()) if r[3]]
    for (series, decade), n in sorted(Counter((s, (d[:3] + "0s") if d else "undated")
                                             for _, s, d, _ in hits).items()):
        print(f"{series:12} {decade:8} {n}")
    if "-v" in sys.argv:
        print(" ".join(sorted(i for i, *_ in hits)))
