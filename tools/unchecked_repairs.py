#!/usr/bin/env python3
"""Mechanical repairs for an unchecked wordplay tree, so tools/clear_unchecked.py
can clear flags that sit on a sound parse written in the old block conventions.

Each repair is checked by the evaluator against the answer: a repair that does not
make the tree give the answer is dropped, so none can invent a parse.

  drop_wordless   an unchecked leaf with no letters, in a charade or a palindrome, is
                  a word the old blocks carried along (a link, a trailing definition
                  word); stripping its flag turned it into letters, so it goes.
  unscramble      a leaf under an anagram whose `gives` is a permutation of its own clue
                  words holds the answer-order slice; the fodder is the words as written.
  swapped         sub/del/ins filed with the parts in the order the indicator reads
                  ("A for B": new then old; the removed part first) are tried swapped.
  spelt_charade   a homophone filed with several parts and no `spelt` is a charade with
                  the sound-alike inside it.
  unpacked_spoon  spoon() filed as one charade of the two results: the pieces before
                  the swap are the letters with their onsets exchanged.
  selections_over_results
                  first/last/middle/alt/nth over a leaf whose letters are the selection's
                  result: the leaf reads its words and the op picks the letters.
  pushed_reversals
                  a rev() whose child already reads forward in the answer: the reversal
                  goes onto the one leaf under it that makes the tree give the answer.
  composites      ana(del(whole, taken)) is comp(whole, taken): del() wants one run.

    python3 tools/test_unchecked_repairs.py
"""
import collections
import copy
import itertools
import re

import wordplay

#: op -> (index, index) of the two parts that are filed in either order
SWAPS = {"substitution": (1, 2), "deletion": (0, 1), "container": (0, 1)}
MAX_SWAPPED = 2
MAX_SELECTIONS = 4  # selections over a leaf, whose subsets are tried
MAX_PUSHED = 6  # leaves a reversal may be pushed down onto
MAX_READINGS = 12 # readings of a part tried when inferring the missing letters


def walk(node, parent=None):
    yield node, parent
    for p in node.get("parts") or []:
        if isinstance(p, dict):
            yield from walk(p, node)


def _wordless(p):
    return (isinstance(p, dict) and "op" not in p and p.get("unchecked")
            and not wordplay.letters(p.get("gives")))


def drop_wordless(tree):
    """A copy without the unchecked, letterless leaves of charades and palindromes.
    Call it before the flags are stripped: afterwards they cannot be told apart."""
    tree = copy.deepcopy(tree)
    for node, _ in list(walk(tree)):
        if node.get("op") not in ("charade", "palindrome") or not node.get("parts"):
            continue
        keep = [p for p in node["parts"] if not _wordless(p)]
        if len(keep) == len(node["parts"]):
            continue
        if keep:
            node["parts"] = keep
        elif node["op"] == "palindrome":
            node.pop("parts")  # pal() alone: the answer is the wordplay
    return tree


def unscramble(tree):
    """A copy whose fodder leaves read their clue words, not the answer-order slice."""
    tree = copy.deepcopy(tree)
    for node, _ in list(walk(tree)):
        if node.get("op") != "anagram":
            continue
        for leaf, _ in walk(node):
            w, g = wordplay.letters(leaf.get("words")), wordplay.letters(leaf.get("gives"))
            if "op" not in leaf and w and g and g != w and collections.Counter(g) == collections.Counter(w):
                leaf.pop("gives")
    return tree


def _swappable(tree):
    return [i for i, (n, _) in enumerate(walk(tree))
            if n.get("op") in SWAPS and len(n.get("parts") or []) == wordplay.ARITY[n["op"]][0]]


def swapped(tree, picks):
    """A copy with the two parts of each picked node (by walk order) exchanged."""
    tree = copy.deepcopy(tree)
    nodes = [n for n, _ in walk(tree)]
    for i in picks:
        a, b = SWAPS[nodes[i]["op"]]
        parts = nodes[i]["parts"]
        parts[a], parts[b] = parts[b], parts[a]
    return tree


def _leaf_pair(node):
    """The two letter-giving leaves a one-charade spoon() holds, else None."""
    parts = node.get("parts") or []
    if len(parts) != 1 or parts[0].get("op") != "charade":
        return None
    pair = parts[0].get("parts") or []
    if len(pair) == 2 and all("op" not in p and wordplay.letters(p.get("gives") or p.get("words")) for p in pair):
        return pair
    return None


def unpacked_spoon(tree):
    """Variants of the tree with each filed-as-results spoon() unpacked into its two
    inputs, one variant per way of reading the onset."""
    out = []
    for i, (n, _) in enumerate(walk(tree)):
        if n.get("op") == "spoonerism" and _leaf_pair(n):
            for onset in (wordplay._onset, lambda s: s[:1]):
                t = copy.deepcopy(tree)
                node = [x for x, _ in walk(t)][i]
                a, b = _leaf_pair(node)
                ga, gb = (wordplay.letters(p.get("gives") or p.get("words")) for p in (a, b))
                oa, ob = onset(ga), onset(gb)
                a["gives"], b["gives"] = ob + ga[len(oa):], oa + gb[len(ob):]
                node["parts"] = [a, b]
                out.append(t)
    return out


def _bare(letters):
    return {"gives": letters}


def _readings(node):
    """Every string a node can give without the answer; none when that needs it."""
    try:
        return wordplay.values(node)
    except (wordplay.WordplayError, wordplay._NeedTarget, IndexError, KeyError, TypeError):
        return set()


def _removals(x, want):
    """Where one run of x can come out to leave `want`: [(k, run)], the end first,
    then the start (a "briefly" or a "headless"), then inside."""
    m = len(x) - len(want)
    if m <= 0:
        return []
    hits = [(k, x[k:k + m]) for k in range(len(x) - m + 1) if x[:k] + x[k + m:] == want]
    return sorted(hits, key=lambda h: (h[0] != len(x) - m, h[0] != 0, h[0]))


def inferred_root(tree, answer):
    """Variants of a root del() or sub() filed with only the thing it works on, with
    the removed (or old and new) letters read off the answer as bare letters, the way
    del(x, H) names them. Only when the answer is x with one run taken out (or one run
    changed) and x gives one string."""
    parts = tree.get("parts") or []
    if len(parts) != 1 or tree.get("op") not in ("deletion", "substitution"):
        return []
    want = wordplay.letters(answer)
    out = []
    for x in sorted(_readings(parts[0]))[:MAX_READINGS]:
        if tree["op"] == "deletion":
            for _, run in _removals(x, want)[:2]:
                t = copy.deepcopy(tree)
                t["parts"].append(_bare(run))
                out.append(t)
        elif len(x) == len(want) and x != want:
            diff = [i for i in range(len(x)) if x[i] != want[i]]
            lo, hi = diff[0], diff[-1] + 1
            t = copy.deepcopy(tree)
            t["parts"] += [_bare(x[lo:hi]), _bare(want[lo:hi])]
            out.append(t)
    return out


_DEL_ENDS = {"ends", "bounds", "extremes", "edges", "tailing", "topping", "borders", "outskirts",
             "limits", "peeled", "skinned", "shelled", "unwrapped", "exposed", "bare", "stripped",
             "extremities", "boundaries", "margins", "outside", "topped"}
_DEL_FIRST = {"first", "head", "headless", "beheaded", "top", "topless", "leader", "leaderless", "opening",
              "initially", "start", "starts", "starting", "initial", "front", "heads", "decapitated"}
_DEL_LAST = {"last", "end", "ends", "tail", "tailless", "endless", "finally", "briefly", "almost", "short",
             "shortly", "docked", "curtailed", "cut", "nearly", "most", "mostly", "unfinished", "ultimately",
             "back", "rear", "conclusion", "tails", "bottom", "incomplete"}
_DEL_MIDDLE = {"middle", "heart", "core", "centre", "center", "centrally", "gutted", "hollow", "empty",
               "disheartened", "heartless", "coreless", "inside", "interior", "midriff", "essentially"}


def indicated_dels(tree):
    """Variants of each one-part del() whose indicator names what goes (ends, first or
    last letter, middle or heart): the removed letters are read off the word the del
    works on, as bare letters, like del(x, H). Out of bounds, topping and tailing,
    almost, headless. Only the answer decides which variant stands."""
    out = []
    for at, (node, _) in enumerate(walk(tree)):
        parts = node.get("parts") or []
        if node.get("op") != "deletion" or len(parts) != 1:
            continue
        toks = set(re.findall(r"[a-z]+", " ".join(i.get("text", "") for i in node.get("indicators") or []).lower()))
        for x in sorted(_readings(parts[0]))[:MAX_READINGS]:
            cuts = []
            if toks & _DEL_ENDS and len(x) > 2:
                cuts.append([x[0], x[-1]])
            if toks & _DEL_FIRST and len(x) > 1:
                cuts.append([x[0]])
            if toks & _DEL_LAST and len(x) > 1:
                cuts.append([x[-1]])
            if toks & _DEL_MIDDLE and len(x) > 2:
                h = len(x) // 2
                cuts.append([x[h]] if len(x) % 2 else [x[h - 1:h + 1]])
                cuts.append([x[1:-1]])
            for cut in cuts:
                def make(node, cut=cut):
                    return {**node, "parts": list(node["parts"]) + [_bare(c) for c in cut]}
                out.append(_rebuild(copy.deepcopy(tree), [0], at, make))
    return out


def split_ins(tree):
    """Variants of each ins() filed as one charade of pieces: some pieces are the
    outer (those before and after the inner) and a run of them the inner, the rest
    keep their place in a charade around it. ODDBALL = ins([old]O + [Double
    Diamonds]DD + [bishop]B + [every one]ALL) is ins(O + B, DD) + ALL."""
    def group(pieces):
        return pieces[0] if len(pieces) == 1 else {"op": "charade", "parts": list(pieces)}

    def make(pieces, a, i, j, b):
        def go(node):
            ins = {**node, "parts": [group(pieces[a:i] + pieces[j:b]), group(pieces[i:j])]}
            around = pieces[:a] + [ins] + pieces[b:]
            return ins if len(around) == 1 else {"op": "charade", "parts": around}
        return go

    out = []
    for at, (node, _) in enumerate(walk(tree)):
        parts = node.get("parts") or []
        if node.get("op") != "container" or len(parts) != 1 or parts[0].get("op") != "charade":
            continue
        pieces = parts[0].get("parts") or []
        n = len(pieces)
        if not 3 <= n <= 6:
            continue
        for i in range(n):
            for j in range(i + 1, n):
                for a in range(i + 1):
                    for b in range(j, n + 1):
                        if a < i or j < b:  # the outer needs a piece
                            out.append(_rebuild(copy.deepcopy(tree), [0], at, make(pieces, a, i, j, b)))
    return out


def _backwards(leaf):
    """A copy of the leaf giving its letters reversed."""
    leaf = copy.deepcopy(leaf)
    leaf["gives"] = wordplay.letters(leaf.get("gives") or leaf.get("words"))[::-1]
    return leaf


def reversed_runs(tree):
    """Variants of each rev() over leaves that hold the letters as the answer has them
    (the reversal already done): a run of the pieces, in clue order, is what rev()
    works on, each giving its letters before the reversal. rev([kept]DAH + [trouble]LIA)
    is rev([trouble]AIL + [kept]HAD); in rev([American]AM + [energy]E + [oil]LIO +
    [price]RATE) only [oil] is reversed. Also takes a rev() filed with several parts."""
    def make(i, j):
        def go(node):
            parts = node["parts"]
            ch = parts[0] if len(parts) == 1 else {"parts": parts}
            pieces = ch["parts"]
            seg = [_backwards(p) for p in reversed(pieces[i:j])]
            rev = {**node, "parts": [seg[0] if len(seg) == 1 else {"op": "charade", "parts": seg}]}
            around = pieces[:i] + [rev] + pieces[j:]
            if len(around) > 1:
                return {"op": "charade", "parts": around, **({"indicators": ch["indicators"]} if ch.get("indicators") else {})}
            inds = (node.get("indicators") or []) + (ch.get("indicators") or [])
            return {**rev, **({"indicators": inds} if inds else {})}
        return go

    out = []
    for at, (node, _) in enumerate(walk(tree)):
        parts = node.get("parts") or []
        if node.get("op") != "reversal" or not parts:
            continue
        ch = parts[0] if len(parts) == 1 and parts[0].get("op") == "charade" else None
        pieces = (ch or {}).get("parts") or (parts if len(parts) > 1 else [])
        if not 2 <= len(pieces) <= 8 or any("op" in p for p in pieces):
            continue
        runs = [(i, j) for i in range(len(pieces)) for j in range(i + 1, len(pieces) + 1)]

        def literal(run):  # every piece is its own clue words backwards: oil -> LIO
            return all(wordplay.letters(p.get("words")) == wordplay.letters(p.get("gives") or p.get("words"))[::-1]
                       for p in pieces[run[0]:run[1]])
        # a run of literal reversals first, then the longest run: the letters alone cannot say which
        # synonym was reversed, so the nearest to the filed shape wins
        for i, j in sorted(runs, key=lambda r: (not literal(r), r[0] - r[1], r[0])):
            out.append(_rebuild(copy.deepcopy(tree), [0], at, make(i, j)))
    return out


def _plain_leaf(n):
    return isinstance(n, dict) and "op" not in n and "gives" in n and n.get("words")


def selections_over_results(tree):
    """Variants of the tree with `gives` dropped from the leaf under a selection
    (first, last, middle, nth, alt ...) that holds the selection's result, not its
    own letters: first([Leaders of Accord left incensed by inane]ALIBI) is the
    first letters of the words, so the leaf reads its words. Every non-empty set of
    such selections, the whole set first."""
    nodes = [i for i, (n, _) in enumerate(walk(tree))
             if n.get("op") in wordplay.SELECT and len(n.get("parts") or []) == 1 and _plain_leaf(n["parts"][0])]
    nodes = nodes[:MAX_SELECTIONS]
    for k in range(len(nodes), 0, -1):
        for picks in itertools.combinations(nodes, k):
            t = copy.deepcopy(tree)
            flat = [n for n, _ in walk(t)]
            for i in picks:
                flat[i]["parts"][0].pop("gives")
            yield t


def pushed_reversals(tree, answer):
    """Variants of each rev() whose child already reads forward in the answer: the
    reversal belongs on one leaf under it, which then gives its letters before the
    reversal. rev(ins([passage]TNEV, [press]URGE)) is ins(rev([passage]VENT), [press]URGE);
    rev([Look]KEEP) is rev([Look]PEEK). The rev's own indicators go with the leaf."""
    out = []
    for at, (node, _) in enumerate(walk(tree)):
        parts = node.get("parts") or []
        if node.get("op") != "reversal" or len(parts) != 1:
            continue
        child = parts[0]
        leaves = [(i, n) for i, (n, _) in enumerate(walk(child)) if _plain_leaf(n)]
        # A leaf whose clue words include an indicator of the reversal ("bloke picked up")
        # is the one the old block meant; with one, no other leaf is a candidate.
        named = [(i, n) for i, n in leaves if wordplay.letters(n.get("words")) and any(
            wordplay.letters(ind.get("text")) and wordplay.letters(ind.get("text")) in wordplay.letters(n.get("words"))
            for ind in node.get("indicators") or [])]
        cands = []
        for j, _ in (named or leaves)[:MAX_PUSHED]:
            def make(node, j=j):
                child = copy.deepcopy(node["parts"][0])
                flat = [n for n, _ in walk(child)]
                target = flat[j]
                if target is child:  # the leaf itself: rev() stays, the leaf reads before it
                    return {**node, "parts": [_backwards(child)]}
                inner = {"op": "reversal", "parts": [_backwards(target)]}
                if node.get("indicators"):
                    inner["indicators"] = node["indicators"]
                target.clear()
                target.update(inner)
                return child
            cands.append(_rebuild(copy.deepcopy(tree), [0], at, make))
        # the letters cannot say which synonym was reversed: only an unambiguous leaf is taken
        works = [c for c in cands if _gives(c, answer)]
        if len(works) == 1:
            out.append(works[0])
    return out


def composites(tree):
    """Variants of each ana() over a del(): the answer is an anagram of the whole with
    the letters taken out, which is comp(whole, taken) -- del() wants one run. Both
    orders of the parts (an indicator may read "taken out of")."""
    out = []
    for at, (node, _) in enumerate(walk(tree)):
        parts = node.get("parts") or []
        if node.get("op") != "anagram" or len(parts) != 1 or parts[0].get("op") != "deletion":
            continue
        dele = parts[0]
        if len(dele.get("parts") or []) != 2:
            continue
        for order in ((0, 1), (1, 0)):
            def make(node, order=order):
                d = node["parts"][0]
                inds = (node.get("indicators") or []) + (d.get("indicators") or [])
                return {"op": "composite", "parts": [d["parts"][order[0]], d["parts"][order[1]]],
                        **({"indicators": inds} if inds else {})}
            out.append(_rebuild(copy.deepcopy(tree), [0], at, make))
    return out


def _rebuild(node, count, target, make):
    """The tree with the node at preorder position `target` replaced by make(node)."""
    here = count[0]
    count[0] += 1
    if here == target:
        return make(node)
    if node.get("parts"):
        node["parts"] = [_rebuild(p, count, target, make) if isinstance(p, dict) else p
                         for p in node["parts"]]
    return node


def _gives(tree, answer):
    try:
        wordplay.evaluate(tree, answer)
    except (wordplay.WordplayError, IndexError, KeyError, TypeError):
        return False
    return True


def spelt_charade(tree):
    """Variants of each homophone filed with several parts and no `spelt`: it is the
    charade of those parts with the sound-alike inside (sound<we hear>(DIAL, sound(EIGHT,
    ATE)) is DIAL + the homophone ATE). The outer indicators move onto the one inner
    homophone that has none, so every homophone still names its indicator."""
    out = []
    for at, (node, _) in enumerate(walk(tree)):
        parts = node.get("parts") or []
        if node.get("op") != "homophone" or "spelt" in node or len(parts) < 2:
            continue

        def make(node):
            new = {k: v for k, v in node.items() if k != "indicators"}
            new["op"] = "charade"
            inds = node.get("indicators")
            bare = [p for p in new["parts"] if p.get("op") == "homophone" and not p.get("indicators")]
            if inds and len(bare) == 1:
                bare[0]["indicators"] = inds
            elif inds:
                new["indicators"] = inds
            return new
        out.append(_rebuild(copy.deepcopy(tree), [0], at, make))
    return out


def variants(tree, answer):
    """The repaired trees worth trying, cheapest first."""
    yield tree
    yield from spelt_charade(tree)
    idx = _swappable(tree)
    for k in range(1, MAX_SWAPPED + 1):
        for picks in itertools.combinations(idx, k):
            yield swapped(tree, picks)
    yield from unpacked_spoon(tree)
    yield from inferred_root(tree, answer)
    yield from indicated_dels(tree)
    yield from split_ins(tree)
    yield from reversed_runs(tree)
    yield from selections_over_results(tree)
    yield from pushed_reversals(tree, answer)
    yield from composites(tree)


def repaired(tree, answer):
    """The first variant of `tree` that gives `answer`, else None. `tree` is
    already stripped, and has been through drop_wordless and unscramble."""
    for v in variants(tree, answer):
        if _gives(v, answer):
            return v
    return None
