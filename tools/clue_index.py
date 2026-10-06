#!/usr/bin/env python3
"""Which puzzle files share clues: normalised clue text -> puzzle ids.

A page that copies another puzzle under a new id (a Guardian URL that serves a
different puzzle's clues) is caught by looking its clues up here, whatever the
other puzzle's series or number. Used by puzzle_integrity.py (whole corpus) and
fetch_puzzle.py (before filing). No pairwise comparison: each clue is looked up
once and the hits are counted per puzzle.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import puzzle_paths  # noqa: E402

#: A pair sharing at least this fraction of the smaller puzzle's clues is one
#: puzzle filed twice.
THRESHOLD = 0.8
#: Fewer clues than this say nothing (a stub shares its three clues with anyone).
MIN_CLUES = 6

#: Pairs of puzzle ids that legitimately share clues, each with the reason.
#: Exempted by id, not by raising THRESHOLD: a threshold loose enough to pass
#: these would pass a copy filed under the wrong number. Each pair here is a
#: setter re-running an old puzzle with a few clues reworded; both files come
#: from their own dated publication (own Guardian/Independent page or own blog
#: post), so neither is a mis-filed copy of the other.
REPRINTS = {
    frozenset(pair): why for pair, why in (
        (("book-19005", "book-23185"), "Telegraph Book 28 No 5, reprinted as Big Book of Brain Sharpener vol 1 No 185"),
        (("book-19012", "book-23191"), "Telegraph Book 28 No 12, reprinted as Big Book of Brain Sharpener vol 1 No 191"),
        (("canberra-720523", "canberra-720926"), "the Canberra Times printed one Times puzzle twice, 1972-05 and 1972-09"),
        (("cryptic-25328", "cryptic-26328"), "Pasquale prize, rerun 2011 -> 2014"),
        (("ftcryptic-13761", "ftcryptic-14223"), "Jason rerun, one clue reworded"),
        (("ftcryptic-14853", "ftcryptic-14947"), "Aardvark rerun, one clue reworded"),
        (("ftcryptic-15011", "ftcryptic-15128"), "Dante rerun, one clue reworded"),
        (("ftcryptic-16776", "ftcryptic-16806"), "Basilisk rerun, one clue reworded"),
        (("ftcryptic-16016", "ftcryptic-18479"), "Orense memorial rerun after his death in 2026-08"),
        (("independent-8933", "independent-9036"), "Quixote rerun, one clue reworded"),
        (("independent-9623", "independent-9802"), "Punk rerun, three clues reworded"),
        (("telegraph-26049", "telegraph-26216"), "rerun, one clue reworded"),
        (("times-27331", "times-29539"), "Times rerun, five clues reworded"),
    )
}
# Series that bought another paper's puzzles and printed them weeks later:
# their copies are the same puzzle by design, not a page under a wrong id.
SYNDICATED = {
    frozenset(pair): why for pair, why in (
        (("canberra", "times"), "the Canberra Times reprinted the Times's cryptic in the 1970s"),
    )
}


def known_copy(a, b):
    """Whether ids `a` and `b` are a listed rerun or a syndicated reprint."""
    series = frozenset(pid.rsplit("-", 1)[0] for pid in (a, b))
    return frozenset((a, b)) in REPRINTS or series in SYNDICATED


def norm(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def clue_keys(puzzle):
    """The set of normalised clue texts of a puzzle (empty clues dropped)."""
    keys = set()
    for e in puzzle.get("entries") or []:
        c = e.get("clue")
        text = c.get("text") if isinstance(c, dict) else c
        if isinstance(text, str) and (k := norm(text)):
            keys.add(k)
    return keys


class ClueIndex:
    def __init__(self):
        self.by_clue = defaultdict(set)   # clue key -> ids
        self.size = {}                    # id -> number of clue keys

        self.keys = {}                    # id -> its clue keys

    def add(self, pid, puzzle):
        self.add_keys(pid, clue_keys(puzzle))

    def add_keys(self, pid, keys):
        self.size[pid] = len(keys)
        self.keys[pid] = keys
        for k in keys:
            self.by_clue[k].add(pid)

    @classmethod
    def build(cls, paths=None):
        idx = cls()
        for path in (puzzle_paths.puzzle_files() if paths is None else paths):
            try:
                puzzle = json.loads(Path(path).read_text(encoding="utf-8"))
                idx.add(puzzle.get("id") or Path(path).stem, puzzle)
            except (OSError, ValueError, AttributeError):
                continue
        return idx

    def matches(self, pid, keys):
        """[(other id, shared, mine, theirs)] for every other puzzle sharing at
        least THRESHOLD of the smaller one's clues, best first."""
        hits = Counter()
        for k in keys:
            for other in self.by_clue.get(k, ()):
                if other != pid:
                    hits[other] += 1
        out = []
        for other, shared in hits.items():
            small = min(len(keys), self.size[other])
            if (small >= MIN_CLUES and shared >= THRESHOLD * small
                    and not known_copy(pid, other)):
                out.append((other, shared, len(keys), self.size[other]))
        return sorted(out, key=lambda m: -m[1])

    def pairs(self):
        """Every near-duplicate pair (a, b, shared, na, nb) with a < b.

        A pair passes only when the smaller puzzle shares at least `need` of
        its clues, so any (size - need + 1) of its clues hold at least one
        shared one. Each puzzle therefore looks up only that many of its
        rarest clues, against partners no smaller than itself, and counts the
        overlap exactly for each partner found. A clue every puzzle carries
        ("See 1") is never what pairs two puzzles up."""
        found = set()
        for a, keys in self.keys.items():
            size = len(keys)
            if size < MIN_CLUES:
                continue
            need = _need(size)
            rarest = sorted(keys, key=lambda k: (len(self.by_clue[k]), k))
            for k in rarest[:size - need + 1]:
                for b in self.by_clue[k]:
                    if b != a and self.size[b] >= size:
                        found.add((a, b) if a < b else (b, a))
        out = []
        for a, b in sorted(found):
            shared = len(self.keys[a] & self.keys[b])
            small = min(self.size[a], self.size[b])
            if (small >= MIN_CLUES and shared >= THRESHOLD * small
                    and not known_copy(a, b)):
                out.append((a, b, shared, self.size[a], self.size[b]))
        return out


def _need(size):
    """The fewest shared clues that pass THRESHOLD for a puzzle of `size`."""
    need = int(THRESHOLD * size)
    return need if need >= THRESHOLD * size else need + 1

if __name__ == "__main__":
    for a, b, k, na, nb in ClueIndex.build().pairs():
        print(f"{a} {b} {k} of {na}/{nb}")
