"""Which backlog puzzles to annotate first so the /indicators/ page can link
every indicator it lists.

The page counts indicators off the solving blogs and our own annotations
(tools/data/lexicons/indicators.json) but links one only to a clue WE
annotated whose type names that indicator type. The blog facts know which
puzzle's clue used each indicator, so the puzzles that would give an unlinked
indicator its first annotated clue are known before anyone annotates them.

The order is a greedy weighted set cover over the queue it is given: take the
puzzle whose clues use the most still-unlinked (type, indicator) pairs, each
weighted by the indicator's clue count so common indicators come first; count
those pairs covered; repeat until no puzzle covers anything. Ties keep queue
order. Everything after the cover keeps the order it arrived in.

Recomputed from the puzzle files on every call, so a pair stops counting the
moment any annotation on disk links it.
"""
import functools
import hashlib
import heapq
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import puzzle_files, read_puzzle_file
from indicator_keys import indicator_key, names_type

ROOT = Path(__file__).resolve().parent.parent
INDICATORS = ROOT / "tools" / "data" / "lexicons" / "indicators.json"
BLOG_FACTS = ROOT / "tools" / "data" / "blog_facts"


key = functools.cache(indicator_key)


@functools.cache
def _named(kinds, annotation_type):
    return [t for t in kinds if names_type(t, annotation_type)]


def entry_pairs(kinds, annotation_type, indicators):
    """The (type, key) pairs one clue's indicators give, for the types in `kinds`
    its type names."""
    if not indicators:
        return set()
    if isinstance(annotation_type, list):
        annotation_type = tuple(annotation_type)
    named = _named(tuple(kinds), annotation_type)
    return {(t, key(i)) for i in indicators for t in named}


def linked_pairs(kinds, skip=frozenset()):
    """Every (type, key) pair one of our annotations already links, reading
    each puzzle file not in `skip` (the queue: nothing there is annotated)."""
    out = set()
    for path in puzzle_files():
        if path.stem in skip:
            continue
        for e in read_puzzle_file(path).get("entries", ()):
            ann = e.get("annotation") or {}
            out |= entry_pairs(kinds, ann.get("type"), ann.get("indicators"))
    return out


#: blog_pairs' scan of every post, which takes seconds the burn pays each wave;
#: reused while the blog facts and the indicator types it was taken under stand.
BLOG_CACHE = (Path(tempfile.gettempdir())
              / f"ct-indicator-cover-blog-{hashlib.sha1(str(ROOT).encode()).hexdigest()[:8]}.json")


def blog_pairs(kinds, wanted):
    """{puzzle id: (type, key) pairs its blog facts give} for the puzzles in `wanted`."""
    stamp = [kinds] + [[p.name, p.stat().st_mtime_ns, p.stat().st_size]
                       for p in sorted(BLOG_FACTS.glob("*.json"))]
    try:
        cached = json.loads(BLOG_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    if cached.get("stamp") != stamp:
        every = {}
        for path in sorted(BLOG_FACTS.glob("*.json")):
            for pid, post in json.loads(path.read_text(encoding="utf-8")).items():
                got = set()
                for facts in (post.get("entries") or {}).values():
                    got |= entry_pairs(kinds, facts.get("type"), facts.get("indicators"))
                if got:
                    every[pid] = sorted(got)
        cached = {"stamp": stamp, "pairs": every}
        tmp = BLOG_CACHE.with_suffix(f".{os.getpid()}")
        tmp.write_text(json.dumps(cached), encoding="utf-8")
        os.replace(tmp, BLOG_CACHE)
    return {pid: {tuple(p) for p in ps} for pid, ps in cached["pairs"].items() if pid in wanted}


def cover(queue, pairs_of, weight):
    """[(puzzle id, pairs it newly covers)] in cover order, and the pairs covered.

    Lazy greedy: a puzzle's score only falls as pairs get covered, so a stale
    score at the top of the heap is rescored and pushed back, never trusted."""
    uncovered = {p for ps in pairs_of.values() for p in ps if p in weight}
    heap = []
    for at, pid in enumerate(queue):
        mine = pairs_of.get(pid, set()) & uncovered
        if mine:
            heap.append((-sum(weight[p] for p in mine), at, pid))
    heapq.heapify(heap)
    picks, covered = [], set()
    while heap:
        neg, at, pid = heapq.heappop(heap)
        mine = pairs_of[pid] & uncovered
        score = sum(weight[p] for p in mine)
        if not mine:
            continue
        if score != -neg:
            heapq.heappush(heap, (-score, at, pid))
            continue
        picks.append((pid, mine))
        covered |= mine
        uncovered -= mine
    return picks, covered


def order(queue, pairs_of, weight, pinned=()):
    """The queue with `pinned` (in queue) first, then the cover, then the rest
    as it came; and the cover's picks."""
    pin = [p for p in dict.fromkeys(pinned) if p in set(queue)]
    rest = [p for p in queue if p not in set(pin)]
    picks, _ = cover(rest, pairs_of, weight)
    first = {pid for pid, _ in picks}
    return pin + [pid for pid, _ in picks] + [p for p in rest if p not in first], picks


def plan(queue, pinned=()):
    """order() against the data on disk. Returns (queue, picks, unlinked weights)."""
    lex = json.loads(INDICATORS.read_text(encoding="utf-8"))
    kinds = list(lex)
    linked = linked_pairs(kinds, skip=set(queue))
    weight = {(t, k): n for t, d in lex.items() for k, n in d.items() if (t, k) not in linked}
    pairs_of = blog_pairs(kinds, set(queue))
    ordered, picks = order(queue, pairs_of, weight, pinned)
    return ordered, picks, weight
