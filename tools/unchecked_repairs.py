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

    python3 tests/test_unchecked_repairs.py
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
        if len(keep) == 1 and node["op"] == "charade" and not node.get("indicators") and isinstance(keep[0], dict):
            # a join of one piece is that piece: what is left after the letterless words go
            node.clear()
            node.update(keep[0])
        elif keep:
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
            if n.get("op") in SWAPS and len(n.get("parts") or []) == wordplay.ARITY[n["op"]][n["op"] == "substitution"]]  # sub's full form: 3 parts


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


_ONES = ("ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE THIRTEEN FOURTEEN "
         "FIFTEEN SIXTEEN SEVENTEEN EIGHTEEN NINETEEN").split()
_TENS = "X X TWENTY THIRTY FORTY FIFTY SIXTY SEVENTY EIGHTY NINETY".split()


def number_word(text):
    """A figure written as a word (50 -> FIFTY, 101 -> HUNDREDONE is not attempted), for 0-99; else None."""
    t = (text or "").strip()
    if not t.isdigit() or int(t) > 99:
        return None
    n = int(t)
    return _ONES[n] if n < 20 else _TENS[n // 10] + (_ONES[n % 10] if n % 10 else "")


def _candidates(node, leaf):
    """Words a selection's leaf may stand for: a figure written out, then each word of
    the notes (the annotator named the synonym there: 'the middle of sinners')."""
    out = []
    num = number_word(leaf.get("words"))
    if num:
        out.append(num)
    text = " ".join([leaf.get("note") or ""] + [i.get("note") or "" for i in node.get("indicators") or []])
    for w in re.findall(r"[A-Za-z]+", text):
        w = w.upper()
        if len(w) >= 3 and w not in out:
            out.append(w)
    return out


def synonym_selections(tree):
    """Variants of each selection (first, middle, alt ...) over one plain leaf whose letters
    are the selection's result, but not a pick from its own clue words (funds -> OFFER, the
    middle of COFFERS): the leaf gives the longer word the note names, if the selection
    of that word gives the result. The evaluator then checks the whole against the answer."""
    nodes = [i for i, (n, _) in enumerate(walk(tree))
             if n.get("op") in wordplay.SELECT and len(n.get("parts") or []) == 1 and _plain_leaf(n["parts"][0])]
    for i in nodes[:MAX_SELECTIONS]:
        node = [n for n, _ in walk(tree)][i]
        leaf = node["parts"][0]
        want = wordplay.letters(leaf.get("gives"))
        for cand in _candidates(node, leaf):
            if len(cand) > len(want) and want in wordplay._select(node["op"], node.get("n"), cand, [cand]):
                t = copy.deepcopy(tree)
                [n for n, _ in walk(t)][i]["parts"][0]["gives"] = cand
                yield t


def split_spoon(tree):
    """A copy where each spoonerism filed as one leaf with a two-word `soundsLike` (RATTLE BAG
    from BATTLE RAG) is two leaves, one per word of the sound, taking the leaf's clue words
    in order (a leading 'the' or 'a' aside): spoon() then swaps the onsets itself, so the
    letters are checked. Only a leaf of exactly two content words splits."""
    tree = copy.deepcopy(tree)
    for node, _ in walk(tree):
        parts = node.get("parts") or []
        if node.get("op") != "spoonerism" or len(parts) != 1 or "op" in parts[0]:
            continue
        leaf = parts[0]
        sounds = (leaf.get("soundsLike") or "").split()
        words = [w for w in (leaf.get("words") or "").split()]
        content = [w for w in words if w.lower() not in ("the", "a", "an", "of", "to", "for")]
        if len(sounds) != 2 or len(content) != 2:
            continue
        node["parts"] = [{"words": w, "gives": s, **({"unchecked": True} if leaf.get("unchecked") else {}),
                          **({"note": leaf["note"]} if leaf.get("note") else {})}
                         for k, (w, s) in enumerate(zip(content, sounds))]
    return tree


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
    yield from synonym_selections(tree)
    yield from pushed_reversals(tree, answer)
    yield from composites(tree)


def _bare_select(n):
    """A selection op with no indicator over one plain leaf."""
    return (n.get("op") in wordplay.SELECT and not n.get("indicators") and len(n.get("parts") or []) == 1
            and isinstance(n["parts"][0], dict) and "op" not in n["parts"][0])


def merged_outer(tree):
    """A copy where first(L) + last(L) side by side in a charade, over the same clue words,
    is the one outer(L): the first and last letters of the same word."""
    tree = copy.deepcopy(tree)
    for node, _ in walk(tree):
        parts = node.get("parts") or []
        for i in range(len(parts) - 1):
            a, b = parts[i], parts[i + 1]
            if (node.get("op") == "charade" and _bare_select(a) and _bare_select(b)
                    and (a["op"], b["op"]) == ("first", "last")
                    and wordplay.letters(a["parts"][0].get("words")) == wordplay.letters(b["parts"][0].get("words"))
                    and a["parts"][0].get("words")):
                leaf = {k: v for k, v in a["parts"][0].items() if k != "gives"}
                notes = [x["parts"][0]["note"] for x in (a, b) if x["parts"][0].get("note")]
                if notes:
                    leaf["note"] = " and ".join(notes)
                parts[i:i + 2] = [{"op": "outer", "parts": [leaf]}]
                if len(parts) == 1:
                    node.pop("parts")
                    node.update(parts[0])
                break
    return tree


def merged_selects(tree, answer):
    """A copy where two like selections side by side in a charade (alt<odd characters>(Plug) +
    alt(50)) are the one selection over a multi-word leaf, the way the validator wants it.
    The leaf reads its words, or, when a piece stands for a longer word (50 -> FIFTY), the
    letters the pieces stand for in a row. The first reading that still gives `answer` stays."""
    for node, _ in walk(tree):
        parts = node.get("parts") or []
        for i in range(len(parts) - 1):
            a, b = parts[i], parts[i + 1]
            if (node.get("op") == "charade" and isinstance(a, dict) and isinstance(b, dict)
                    and a.get("op") in wordplay.SELECT and a.get("op") == b.get("op") != "nth"
                    and len(a.get("parts") or []) == len(b.get("parts") or []) == 1
                    and all(isinstance(x["parts"][0], dict) and "op" not in x["parts"][0] for x in (a, b))
                    and (not a.get("indicators") or not b.get("indicators")
                         or [x["text"] for x in a["indicators"]] == [x["text"] for x in b["indicators"]])):
                la, lb = a["parts"][0], b["parts"][0]
                inds = a.get("indicators") or b.get("indicators")
                words = (la.get("words") or "") + " " + (lb.get("words") or "")
                stands = "".join(wordplay.letters(l.get("gives") or l.get("words")) for l in (la, lb))
                for gives in (None, stands):
                    t = copy.deepcopy(tree)
                    tn = [n for n, _ in walk(t)][[n for n, _ in walk(tree)].index(node)]
                    leaf = {"words": words.strip(), **({"gives": gives} if gives else {})}
                    notes = [x["note"] for x in (la, lb) if x.get("note")]
                    if notes:
                        leaf["note"] = "; ".join(notes)
                    merged = {"op": a["op"], **({"indicators": copy.deepcopy(inds)} if inds else {}), "parts": [leaf]}
                    tn["parts"][i:i + 2] = [merged]
                    if len(tn["parts"]) == 1:
                        tn.pop("parts")
                        tn.update(merged)
                    if _gives(t, answer):
                        return t
                break
    return tree


def shared_indicators(tree):
    """A copy where a selection with no indicator, beside the same selection in its charade
    that has one (alt<odd characters>(Plug) + alt(50)), reads the same indicator words."""
    tree = copy.deepcopy(tree)
    for node, _ in walk(tree):
        if node.get("op") != "charade":
            continue
        for p in node.get("parts") or []:
            if _bare_select(p):
                for q in node["parts"]:
                    if q is not p and q.get("op") == p["op"] and q.get("indicators"):
                        p["indicators"] = copy.deepcopy(q["indicators"])
                        break
    return tree


def peeled_indicators(tree, answer):
    """A copy where a selection with no indicator over a multi-word leaf takes its leading
    words as the indicator ('outer parts of' ankle), as many as still leave a pick that
    gives the answer. The words were already in the leaf."""
    tree = copy.deepcopy(tree)
    for node, _ in walk(tree):
        if not _bare_select(node):
            continue
        leaf = node["parts"][0]
        words = (leaf.get("words") or "").split()
        for k in range(len(words) - 1, 0, -1):
            trial = copy.deepcopy(tree)
            hit = [n for n, _ in walk(trial)][[n for n, _ in walk(tree)].index(node)]
            hit["parts"][0]["words"] = " ".join(words[k:])
            hit["indicators"] = [{"text": " ".join(words[:k]),
                                  "note": "these words say which letters are picked from the word"}]
            if _gives(trial, answer):
                node["parts"][0]["words"] = " ".join(words[k:])
                node["indicators"] = hit["indicators"]
                break
    return tree


def picked_from_words(tree, answer):
    """A copy where each selection over a leaf that holds the pick's own result (first([Cats]CA))
    reads the clue words instead, wherever the tree still gives `answer` that way: the op
    then really makes the pick, and the evaluator checks it. A leaf standing for a longer
    word (penury -> POVERTY) fails that way and keeps its letters."""
    tree = copy.deepcopy(tree)
    for node, _ in list(walk(tree)):
        if node.get("op") in wordplay.SELECT and len(node.get("parts") or []) == 1 and _plain_leaf(node["parts"][0]):
            leaf = node["parts"][0]
            kept = leaf.pop("gives")
            if not _gives(tree, answer):
                leaf["gives"] = kept
    return tree


def shaped(tree, answer):
    """The tree with the shape repairs that keep it giving `answer` (picked_from_words,
    merged_outer, merged_selects, shared_indicators, peeled_indicators)."""
    for fix in (lambda t: picked_from_words(t, answer), merged_outer, lambda t: merged_selects(t, answer), shared_indicators,
                lambda t: peeled_indicators(t, answer)):
        t = fix(tree)
        if _gives(t, answer):
            tree = t
    return tree


def repaired(tree, answer):
    """The first variant of `tree` that gives `answer`, else None. `tree` is
    already stripped, and has been through drop_wordless and unscramble."""
    for v in variants(tree, answer):
        if _gives(v, answer):
            return v
    return None
