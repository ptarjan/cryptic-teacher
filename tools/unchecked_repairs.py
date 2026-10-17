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
  unpacked_spoon  spoon() filed as one charade of the two results: the pieces before
                  the swap are the letters with their onsets exchanged.

    python3 tools/test_unchecked_repairs.py
"""
import collections
import copy
import itertools

import wordplay

#: op -> (index, index) of the two parts that are filed in either order
SWAPS = {"substitution": (1, 2), "deletion": (0, 1), "container": (0, 1)}
MAX_SWAPPED = 2
MAX_READINGS = 12  # readings of a part tried when inferring the missing letters


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


def variants(tree, answer):
    """The repaired trees worth trying, cheapest first."""
    yield tree
    idx = _swappable(tree)
    for k in range(1, MAX_SWAPPED + 1):
        for picks in itertools.combinations(idx, k):
            yield swapped(tree, picks)
    yield from unpacked_spoon(tree)
    yield from inferred_root(tree, answer)
    yield from split_ins(tree)
    yield from reversed_runs(tree)


def repaired(tree, answer):
    """The first variant of `tree` that gives `answer`, else None. `tree` is
    already stripped, and has been through drop_wordless and unscramble."""
    for v in variants(tree, answer):
        if _gives(v, answer):
            return v
    return None
