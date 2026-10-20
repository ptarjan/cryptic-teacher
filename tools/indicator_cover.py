"""Which backlog puzzles to annotate first so the /indicators/ page can link
every indicator it lists.

The page counts indicators off the solving blogs and our own annotations
(tools/data/lexicons/indicators.json) but links one only to a clue WE
annotated whose indicator is credited to that type (its own `for`). The blog facts know which
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
import hashlib
import heapq
import json
import os
import tempfile
from pathlib import Path

import blog_store
import indicator_keys
import puzzle_schema
from annotation import OP_TYPE, _walk, definition_indicator_type
from fetch_puzzle import puzzle_files, read_puzzle_file
from indicator_keys import clue_pairs

ROOT = Path(__file__).resolve().parent.parent
INDICATORS = ROOT / "tools" / "data" / "lexicons" / "indicators.json"


def entry_pairs(lex, indicators):
    """The (type, key) pairs one clue's indicators give: the pairs the
    /indicators/ page links it under (indicator_keys.clue_pairs)."""
    return set(clue_pairs(lex, indicators))


#: The lexicon _file_pairs() reads, set by linked_pairs() before its workers fork.
_LEX = {}


def stored_indicators(ann):
    """A stored annotation's indicators, each with the `for` its op gives:
    what annotation.view() derives as `indicators`, read off the tree with
    no wordplay evaluation. view() also drops an annotation whose tree does
    not give its answer, which the validator keeps out of the corpus; this
    keeps it, so at worst such a clue's indicator reads as linked."""
    tree = ann.get("wordplay")
    nodes = [n for n, _ in _walk(tree)] if isinstance(tree, dict) else []
    dtype = definition_indicator_type(ann)
    return ([{"text": i["text"], "for": OP_TYPE.get(n.get("op"))}
             for n in nodes for i in n.get("indicators") or []]
            + [{"text": i["text"], "for": dtype}
               for d in ann.get("definitions") or [] for i in d.get("indicators") or []])


def _file_pairs(path):
    """The (type, key) pairs one puzzle file's annotations link under _LEX.
    The raw file, not read_puzzle_view(): the view evaluates every tree, and
    its code reach (the whole wordplay engine) changes most days, which made
    each re-plan after a code change read the corpus cold, past the burn's
    POOL_PLAN_SECS. This reach is the tree walk alone."""
    out = set()
    for _, _, ann in puzzle_schema.annotations(read_puzzle_file(path)):
        out |= entry_pairs(_LEX, stored_indicators(ann))
    return out


def linked_pairs(lex, skip=frozenset()):
    """Every (type, key) pair one of our annotations already links, reading
    each puzzle file not in `skip` (the queue: nothing there is annotated).
    Each file's pairs are reused while the file, the code and the lexicon
    stand (tools/row_cache.py)."""
    import row_cache
    global _LEX
    _LEX = lex
    salt = hashlib.sha1(json.dumps(lex, sort_keys=True).encode()).hexdigest()[:16]
    try:
        rows = row_cache.cached_map("indicator_cover", _file_pairs,
                                    [p for p in puzzle_files() if p.stem not in skip], salt=salt)
    finally:
        _LEX = {}
    return set().union(*rows)


#: blog_pairs' scan of every post, which takes seconds the burn pays each wave;
#: reused while the blog facts, the lexicon and the matching code it was taken under stand.
BLOG_CACHE = (Path(tempfile.gettempdir())
              / f"ct-indicator-cover-blog-{hashlib.sha1(str(ROOT).encode()).hexdigest()[:8]}.json")


def blog_pairs(lex, wanted):
    """{puzzle id: (type, key) pairs its blog facts give} for the puzzles in `wanted`."""
    stamp = [hashlib.sha1(json.dumps(lex, sort_keys=True).encode()
                          + Path(indicator_keys.__file__).read_bytes()).hexdigest()] \
        + [hashlib.sha1(repr([[n, p.stat().st_mtime_ns, p.stat().st_size]
                              for n, p in blog_store.files().items()]).encode()).hexdigest()]
    try:
        cached = json.loads(BLOG_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    if cached.get("stamp") != stamp:
        every = {}
        for pid, post in blog_store.rows():
            got = set()
            for facts in (post.get("entries") or {}).values():
                got |= entry_pairs(lex, facts.get("indicators"))
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
    queued = set(queue)
    pin = [p for p in dict.fromkeys(pinned) if p in queued]
    pinset = set(pin)
    rest = [p for p in queue if p not in pinset]
    picks, _ = cover(rest, pairs_of, weight)
    first = {pid for pid, _ in picks}
    return pin + [pid for pid, _ in picks] + [p for p in rest if p not in first], picks


def plan(queue, pinned=()):
    """order() against the data on disk. Returns (queue, picks, unlinked weights)."""
    lex = json.loads(INDICATORS.read_text(encoding="utf-8"))
    linked = linked_pairs(lex, skip=set(queue))
    weight = {(t, k): n for t, d in lex.items() for k, n in d.items() if (t, k) not in linked}
    pairs_of = blog_pairs(lex, set(queue))
    ordered, picks = order(queue, pairs_of, weight, pinned)
    return ordered, picks, weight
