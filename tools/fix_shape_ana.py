"""Anagram repairs of fix_shape_suspects.py: the fodder, the pieces pulled out of it and the edges
standing in for it. Each r_* takes (node, parent, ctx) and returns a replacement node or None.
"""
import copy
import itertools
import json

import validate_annotations as V
import wordplay as W
from fix_shape_base import (
    leaf, vals, checked, charade, simplicity, _eval_swapped, _whole, _flat_fodder, _is_stand_in,
    _plain_charade, _pick,
)
from fix_shape_indicators import _owner_any
from fix_shape_container import _literal_pool


def _ana_candidates(node):
    """Rewrites of an anagram whose fodder holds synonyms: the synonyms charaded on, the
    anagram of the clue's own words kept (every order of the pieces); [] if none."""
    if node.get("op") != "anagram":
        return []
    flat = _flat_fodder(node)
    syn = [p for p in flat if _is_stand_in(p)]
    rest = [p for p in flat if not _is_stand_in(p)]
    if not syn or not rest or len(syn) > 3:
        return []
    if any(leaf(p) and p.get("gives") and W.letters(p["gives"]) != W.letters(p.get("words"))
           for p in rest):
        return []       # a part giving other letters that is not a synonym: not mechanical
    core = checked(node, parts=copy.deepcopy(rest))
    out = []
    import itertools
    for perm in itertools.permutations([*copy.deepcopy(syn), core]):
        out.append(charade(list(perm)))
    return out


def _ana_split_candidates(node):
    """Rewrites of an anagram whose fodder holds synonyms: the synonyms charaded on, and ANY
    subset of the other leaves anagrammed (the rest charaded on as their own letters, so
    "In stalked on wrong cue" scrambles only cue), every order of the pieces; [] if none."""
    if node.get("op") != "anagram":
        return []
    flat = _flat_fodder(node)
    syn = [p for p in flat if _is_stand_in(p)]
    rest = [p for p in flat if not _is_stand_in(p)]
    if not syn or not rest or len(syn) + len(rest) > 6:
        return []
    if any(not leaf(p) or p.get("select") for p in rest):
        return []       # a nested op in the fodder: not mechanical
    # a leaf giving other letters (an abbreviation) was never the anagram's: it stays literal
    fixed = [p for p in rest if p.get("gives") and W.letters(p["gives"]) != W.letters(p.get("words"))]
    free = [p for p in rest if p not in fixed]
    if not free:
        return []
    import itertools
    out = []
    for mask in range(1, 2 ** len(free)):
        scr = [p for i, p in enumerate(free) if mask >> i & 1]
        lit = [p for i, p in enumerate(free) if not mask >> i & 1] + fixed
        core = checked(node, parts=copy.deepcopy(scr))
        for perm in itertools.permutations([*copy.deepcopy(syn), *copy.deepcopy(lit), core]):
            out.append(charade(list(perm)))
    return out


def r_ana_synonym_charade(node, parent, ctx):
    """anaSynonym: an anagram scrambling a synonym beside the clue's own words becomes
    charade(synonym, anagram(own words)) in whichever order and split evaluates to the
    answer. Unlike r_ana_synonym it does not need the new tree to be simpler (the old one is
    the flagged shape): it needs the validator's count to fall, and exactly one simplest tree."""
    if node.get("op") != "anagram" or not ctx.get("answer"):
        return None
    cands = _ana_split_candidates(node)
    if not cands:
        return None
    old = V.anagram_synonyms(ctx["tree"])
    good = []
    for c in cands:
        if not _eval_swapped(node, parent, c, ctx):
            continue
        whole = _whole(node, parent, c, ctx)
        if V.anagram_synonyms(whole) < old:
            good.append((simplicity(whole), c))
    if not good:
        return None
    best = min(k for k, _ in good)
    top = {json.dumps(c, sort_keys=True): c for k, c in good if k == best}
    return next(iter(top.values())) if len(top) == 1 else None


def r_ana_stand_in(node, parent, ctx):
    """anaStandIn: an anagram held by a container scrambles an abbreviation or synonym beside the
    clue's own words. The stand-in is spelled into the answer beside the scramble: same rewrite as
    r_ana_synonym_charade (every order and split that evaluates to the answer), kept only when the
    stand-in count falls and exactly one simplest tree remains; an ambiguous one stays refused."""
    if node.get("op") != "anagram" or not ctx.get("answer"):
        return None
    cands = _ana_split_candidates(node)
    if not cands:
        return None
    old = V.ana_stand_in(ctx["tree"])
    good = []
    for c in cands:
        if not _eval_swapped(node, parent, c, ctx):
            continue
        whole = _whole(node, parent, c, ctx)
        if V.ana_stand_in(whole) < old:
            good.append((simplicity(whole), c))
    if not good:
        return None
    best = min(k for k, _ in good)
    top = {json.dumps(c, sort_keys=True): c for k, c in good if k == best}
    return next(iter(top.values())) if len(top) == 1 else None


def r_ana_of_container(node, parent, ctx):
    """ana(ins(a, b)): the anagram sits inside the container, over one arm (its synonyms
    charaded beside it); the other arm stays as it was."""
    if node.get("op") != "anagram" or len(node.get("parts") or []) != 1:
        return None
    c = node["parts"][0]
    if c.get("op") != "container" or len(c.get("parts") or []) != 2 or c.get("unchecked"):
        return None
    cands = []
    for i in (0, 1):
        arm = c["parts"][i]
        base = {k: v for k, v in node.items() if k not in ("unchecked", "gives")}
        ana = {**copy.deepcopy(base), "parts": copy.deepcopy(arm["parts"] if _plain_charade(arm) else [arm])}
        cont = c
        own = [x for x in c.get("indicators") or [] if _owner_any(x) == V._OP_LEXICON.get("anagram")]
        if not own and len(c.get("indicators") or []) == 2:
            # neither word is the corpus's anagram word: with one the corpus files under container,
            # the other (a word nothing files anywhere) is the anagram's
            held = [x for x in c["indicators"] if _owner_any(x) == V._OP_LEXICON.get("container")]
            free = [x for x in c["indicators"] if not _owner_any(x)]
            own = free if len(held) == 1 and len(free) == 1 else []
        if not ana.get("indicators") and len(own) == 1 and len(c["indicators"]) > 1:
            # the anagram carries no word and the container two: the one the corpus files under
            # anagram is the anagram's (one op per indicator)
            ana["indicators"] = [copy.deepcopy(own[0])]
            cont = {**c, "indicators": [x for x in c["indicators"] if x is not own[0]]}
        for inner in [ana, *_ana_candidates(ana)]:
            parts = copy.deepcopy(c["parts"])
            parts[i] = inner
            cands.append(checked(cont, parts=parts))
            # the file lists the arms in clue order: the container takes the holder first
            cands.append(checked(cont, parts=parts[::-1]))
    flat = _literal_pool(node, c)
    if flat is not None:
        cands.append(flat)
    return _pick(node, parent, ctx, cands)


def r_ana_charade(node, parent, ctx):
    """anaCharade: an anagram whose fodder pieces already spell the answer ("the fodder already
    reads TAPER": ana<upset>(pates=TAPE + queen=R)). Each piece that gives the scramble of its own
    clue words (pates -> TAPE) is the real fodder, the rest are charade pieces beside it: the
    scrambled pieces (together, when adjacent) go under the anagram as the clue's words, the others
    stay, in order. The indicator words the piece swallowed come off it. Kept only when the whole
    tree gives the answer and exactly one arrangement does."""
    if node.get("op") != "anagram" or not ctx.get("answer"):
        return None
    pieces = _flat_fodder(node)
    if len(pieces) < 2 or any(not leaf(p) or not p.get("words") or p.get("select") for p in pieces):
        return None
    inds = [W.letters(i.get("text")) for i in node.get("indicators") or []]

    def real(p):
        """(words, fodder letters or None) for a leaf whose words, without the anagram's own
        indicator at an edge, scramble to its gives (a possessive s the word carries aside)."""
        g = W.letters(p.get("gives")) or W.letters(p["words"])
        ws = p["words"].split()
        for a in range(len(ws)):
            for b in range(a + 1, len(ws) + 1):
                run, rest = " ".join(ws[a:b]), ws[:a] + ws[b:]
                if (a, b) != (0, len(ws)):
                    if W.letters(run) not in inds or (a and b < len(ws)):
                        continue
                    keep = " ".join(rest)
                else:
                    keep = run
                for k2 in (keep, " ".join(w for w in keep.split() if w.lower() not in ("and", "with", "of", "the", "a", "in", "to"))):
                    lk = W.letters(k2)
                    if not lk:
                        continue
                    if sorted(lk) == sorted(g) and lk != g:
                        return keep, (None if k2 == keep else lk)
                    if lk.endswith("S") and sorted(lk[:-1]) == sorted(g) and lk[:-1] != g:
                        return keep, lk[:-1]
        return None
    scr = [real(p) for p in pieces]
    if not any(scr):
        return None
    good = {}
    for mask in range(1, 2 ** len(pieces)):
        pick = [i for i in range(len(pieces)) if mask >> i & 1 and scr[i]]
        if len(pick) != bin(mask).count("1"):
            continue
        # one pool: the picked pieces must sit side by side
        if pick != list(range(pick[0], pick[-1] + 1)):
            continue
        pool = []
        for i in pick:
            q = {k: v for k, v in pieces[i].items() if k != "gives"}
            keep, lit = scr[i]
            if keep != q["words"]:
                if isinstance(q.get("at"), int):
                    q["at"] += q["words"].find(keep)
                q["words"] = keep
            if lit:
                q["gives"] = lit
            pool.append(q)
        new = {k: v for k, v in node.items() if k not in ("unchecked", "gives", "parts")}
        new["parts"] = copy.deepcopy(pool)
        out = [copy.deepcopy(p) for p in pieces[:pick[0]]] + [new] + [copy.deepcopy(p) for p in pieces[pick[-1] + 1:]]
        cand = charade(out)
        if _eval_swapped(node, parent, cand, ctx):
            good[json.dumps(cand, sort_keys=True)] = cand
    return next(iter(good.values())) if len(good) == 1 else None


def _piece_options(p):
    """The letter strings a fodder piece can contribute (a leaf's filed letters; a sub-operation's
    values, a first-N-letters pick having several), sorted; [] when unknown or too many."""
    if leaf(p):
        g = W.letters(W.leaf_letters(p))
        return [g] if g else []
    vs = vals(p)
    return sorted(v for v in vs if v) if vs and len(vs) <= 8 else []


def _spells(ans, pre, mid, suf):
    """Whether some choice of one option per piece makes ans = pre + (an anagram of mid) + suf."""
    for ch in itertools.product(*pre, *mid, *suf):
        p, m, s = "".join(ch[:len(pre)]), "".join(ch[len(pre):len(pre) + len(mid)]), "".join(ch[len(pre) + len(mid):])
        if len(p) + len(m) + len(s) == len(ans) and ans.startswith(p) and ans.endswith(s) \
                and sorted(ans[len(p):len(ans) - len(s)]) == sorted(m):
            return True
    return False


def _stand_in(p):
    """A piece that is not the clue's own words scrambled: a synonym, abbreviation or sub-operation."""
    if not leaf(p):
        return True
    return bool(p.get("select") or p.get("soundsLike")
                or (p.get("gives") and W.letters(p["gives"]) != W.letters(p.get("words"))))


def r_ana_pull(node, parent, ctx):
    """anaCharade (Paul 10-19: "if the letter is correctly placed outside, it shouldn't be in the
    anagram"): ana<troubled>(G + FIRE) = GRIEF is charade(G, ana<troubled>(FIRE)). The anagram sits
    over a charade (or loose pieces) of 2+ pieces for the WHOLE answer; the pieces the answer starts
    with (in some order) and/or ends with are pulled out as charade siblings, when the pieces left
    spell the rest of the answer between them. Every stand-in piece (synonym, abbreviation, sub-op)
    must be pulled: only the clue's own words are scrambled. Of the ways that work, the one pulling
    fewest pieces, in their original order, is kept, and only when exactly one tree results. The
    charade's own indicators and notes stay on the new charade; the anagram's stay on the anagram.
    Neither end working leaves the clue flagged for the model."""
    if node.get("op") != "anagram" or node.get("unchecked") or parent is not None or not ctx.get("answer"):
        return None
    parts = node.get("parts") or []
    cs_ = [p for p in parts if p.get("op") == "charade"]
    if len(cs_) != 1 or cs_[0].get("unchecked") or "gives" in cs_[0]:
        return None
    wrap = {k: v for k, v in cs_[0].items() if k != "parts"}
    pieces = []
    for p in parts:
        pieces += cs_[0]["parts"] if p is cs_[0] else [p]
    if not 2 <= len(pieces) <= 7 or any(p.get("op") == "charade" or p.get("unchecked") for p in pieces):
        return None
    ls = [_piece_options(p) for p in pieces]
    ans = W.letters(ctx["answer"])
    if any(not l for l in ls):
        return None
    must = {i for i, p in enumerate(pieces) if _stand_in(p)}
    n = len(pieces)
    if not must and any(sorted("".join(c)) == sorted(ans) for c in itertools.product(*ls)):
        # all the clue's own words and together the whole answer: one pool, the charade was just a join
        if wrap:
            return None
        flat = {k: v for k, v in node.items() if k not in ("parts", "unchecked", "gives")}
        flat["parts"] = copy.deepcopy(pieces)
        return flat if _eval_swapped(node, parent, flat, ctx) else None
    found = {}
    for mask_a in range(1 << n):
        for mask_b in range(1 << n):
            if mask_a & mask_b or not (mask_a | mask_b) or must - {i for i in range(n) if (mask_a | mask_b) >> i & 1}:
                continue
            a = [i for i in range(n) if mask_a >> i & 1]
            b = [i for i in range(n) if mask_b >> i & 1]
            r = [i for i in range(n) if not (mask_a | mask_b) >> i & 1]
            if not r:
                continue
            # the original order is tried first (permutations yields it first), so it wins when it works
            for pre, suf in itertools.product(itertools.permutations(a), itertools.permutations(b)):
                if _spells(ans, [ls[i] for i in pre], [ls[i] for i in r], [ls[i] for i in suf]):
                    found.setdefault((frozenset(a), frozenset(b)), ((pre, suf), r))
    if not found:
        return None
    least = min(len(a) + len(b) for a, b in found)
    best = [v for (a, b), v in found.items() if len(a) + len(b) == least]
    cands = []
    for (pre, suf), r in best:
        ana = {k: v for k, v in node.items() if k not in ("parts", "unchecked", "gives")}
        ana["parts"] = [copy.deepcopy(pieces[i]) for i in r]
        outer = [copy.deepcopy(pieces[i]) for i in pre] + [ana] + [copy.deepcopy(pieces[i]) for i in suf]
        cands.append({**copy.deepcopy(wrap), "op": "charade", "parts": outer})
    good = {json.dumps(c, sort_keys=True): c for c in cands if _eval_swapped(node, parent, c, ctx)}
    if len(good) > 1:
        # both ends work (ARSE + first(effort) = ERASE: E + RASE or ERAS + E): the pieces as filed,
        # the pulled ones keeping their place before / after the scrambled ones
        keep = {json.dumps(c, sort_keys=True): c for ((pre, suf), r), c in zip(best, cands)
                if json.dumps(c, sort_keys=True) in good
                and all(i < min(r) for i in pre) and all(i > max(r) for i in suf)}
        good = keep if len(keep) == 1 else good
    return next(iter(good.values())) if len(good) == 1 else None


def r_ana_edge(node, parent, ctx):
    return _ana_edge_with(node, parent, ctx, V._stand_in_piece)


def r_ana_select_edge(node, parent, ctx):
    """anaSelectEdge: the same pull for a first/last-letter pick at the edge of the fodder, which may
    stand at either end of the answer (G + ana(MALE) for ana(MALE, first(gymnast's)))."""
    return _ana_edge_with(node, parent, ctx, V._stand_in_or_select, True)


def _ana_edge_with(node, parent, ctx, stand, either_end=False):
    """anaCharade, any depth (Paul 10-19): an anagram whose first / last fodder parts are
    abbreviation or synonym leaves standing at that edge of the scramble's output (ana<unusual>(N +
    RIP SIGN) inside I + ..., where N opens the scramble) -> those parts come out and sit beside the
    anagram in a charade (joined into a parent charade). The fewest pulled wins; kept only when the
    whole tree still gives the answer and exactly one such tree does, else the clue is left for redo."""
    if node.get("op") != "anagram" or node.get("unchecked") or not ctx.get("answer"):
        return None
    parts = node.get("parts") or []
    if len(parts) < 2 or any(not isinstance(p, dict) or p.get("unchecked") for p in parts):
        return None
    st = [stand(p) for p in parts]
    lead = next((i for i, s in enumerate(st) if not s), len(st))
    trail = next((i for i, s in enumerate(reversed(st)) if not s), len(st))
    if lead >= len(st):
        return None
    good = {}
    for j in range(lead + 1):
        for k in range(trail + 1):
            if not (j + k) or j + k >= len(parts):
                continue
            ana = {key: v for key, v in node.items() if key not in ("parts", "unchecked", "gives")}
            ana["parts"] = copy.deepcopy(parts[j:len(parts) - k])
            pre, suf = copy.deepcopy(parts[:j]), copy.deepcopy(parts[len(parts) - k:])
            for order in [pre + [ana] + suf] + ([suf + [ana] + pre] if either_end and not (pre and suf) else []):
                cand = {"op": "charade", "parts": order}
                if _eval_swapped(node, parent, cand, ctx):
                    good[(j + k, json.dumps(cand, sort_keys=True))] = cand
    if not good:
        return None
    least = min(g[0] for g in good)
    best = [c for (n_, _), c in good.items() if n_ == least]
    return best[0] if len(best) == 1 else None


def _path(root, target):
    """The indexes of `parts` that lead from `root` to the node `target` ([] for root itself)."""
    if root is target:
        return []
    for k, p in enumerate(root.get("parts") or []):
        r = _path(p, target)
        if r is not None:
            return [k] + r
    return None


def _at(root, pth):
    for k in pth:
        root = root["parts"][k]
    return root


def r_scrambled_swap(node, parent, ctx):
    """scrambledLeaf: a leaf giving the scramble of its own words (strife's -> FIRSTES) beside an
    anagram op over one synonym leaf (ana<involved>(Sailor=RAT)): the anagram indicator went on the
    wrong word. The anagram moves onto the scrambled leaf, which becomes verbatim clue words, and
    the synonym stands bare where the anagram was. Done on the whole tree, for one such leaf and one
    such anagram; kept when the tree still gives the answer and the rule no longer fires."""
    if parent is not None or not ctx.get("answer") or not V.scrambled_leaves(node, min_len=3):
        return None
    scr, ana = [], []
    stack = [(node, None, ())]
    while stack:
        n, par, anc = stack.pop()
        stack += [(p, n, anc + (n,)) for p in n.get("parts") or []]
        if leaf(n):
            w, g = W.letters(n.get("words")), W.letters(n.get("gives"))
            if n.get("words") and g and len(g) >= 3 and g != w and sorted(g) == sorted(w) and not n.get("unchecked") \
                    and not any(a.get("op") == "anagram" for a in anc) \
                    and not (par and par.get("op") in ("reversal", "cycling")):
                scr.append(n)
        elif n.get("op") == "anagram" and len(n.get("parts") or []) == 1 and not n.get("unchecked") \
                and leaf(n["parts"][0]) and n["parts"][0].get("words") and n["parts"][0].get("gives") \
                and sorted(W.letters(n["parts"][0]["gives"])) != sorted(W.letters(n["parts"][0]["words"])):
            ana.append(n)
    if len(scr) != 1 or len(ana) != 1:
        return None
    new = copy.deepcopy(node)
    s_new, a_new = _at(new, _path(node, scr[0])), _at(new, _path(node, ana[0]))
    wrap = {k: v for k, v in a_new.items() if k != "parts"}
    wrap["parts"] = [{k: v for k, v in s_new.items() if k != "gives"}]
    sole = a_new["parts"][0]
    sp, ap = _path(new, s_new), _path(new, a_new)
    if not sp or s_new is a_new:
        return None
    _at(new, sp[:-1])["parts"][sp[-1]] = wrap
    if ap:
        _at(new, ap[:-1])["parts"][ap[-1]] = sole
    else:
        return None     # the anagram is the root and the scrambled leaf sits under it: not this shape
    try:
        W.evaluate(copy.deepcopy(new), ctx["answer"])
    except (W.WordplayError, IndexError, KeyError, TypeError, ValueError, W._NeedTarget):
        return None
    return new if V.scrambled_leaves(new, min_len=3) < V.scrambled_leaves(node, min_len=3) else None


def r_ana_lone_edge(node, parent, ctx):
    """anaLoneEdge (Paul 10-19: a lone letter that can sit outside the anagram must): an anagram with
    a one-letter fodder part (abbreviation, first/last pick, a lone word) anywhere in its fodder. The
    letter(s) come out and sit in a charade before or after the anagram, in whichever place the whole
    tree still gives the answer. The fewest letters pulled wins; kept only when exactly one tree does."""
    if node.get("op") != "anagram" or node.get("unchecked") or not ctx.get("answer"):
        return None
    parts = node.get("parts") or []
    if len(parts) < 2 or any(not isinstance(p, dict) or p.get("unchecked") for p in parts):
        return None
    lone = [i for i in range(len(parts)) if V._one_letter_part(parts, i)]
    if not lone or len(lone) >= len(parts):
        return None
    good = {}
    same = {}
    for size in (1, 2):
        for pick in itertools.combinations(lone, size):
            rest = [p for i, p in enumerate(parts) if i not in pick]
            ana = {key: v for key, v in node.items() if key not in ("parts", "unchecked", "gives")}
            ana["parts"] = copy.deepcopy(rest)
            out = [copy.deepcopy(parts[i]) for i in pick]
            for k in range(size + 1):       # k pieces in front, the rest behind
                for order in set(itertools.permutations(range(size))):
                    pieces = [out[i] for i in order]
                    cand = {"op": "charade", "parts": pieces[:k] + [ana] + pieces[k:]}
                    if ctx.get("clue") and V.pool_gaps(_whole(node, parent, cand, ctx), ctx["clue"]) > V.pool_gaps(ctx["tree"], ctx["clue"]):
                        continue    # the letter sits among the pool's words in the clue: pulling it out is a poolGap
                    if _eval_swapped(node, parent, cand, ctx):
                        good[json.dumps(cand, sort_keys=True)] = cand
                        # two lone C's (caught, cold) pulled alike are one reading, not two
                        key = (k, "".join(str(p.get("gives") or p.get("words") or "").upper() for p in pieces))
                        same.setdefault(key, cand)
        if good:
            break
    if len(good) == 1:
        return next(iter(good.values()))
    return next(iter(same.values())) if good and len(same) == 1 else None


def r_ana_flatten(node, parent, ctx):
    """anaCharade: an anagram whose fodder is a charade of the clue's own words, no indicator on it, no
    letters of its own and no abbreviation or synonym among its pieces (ana<fighting>(charade(Gran is,
    a)) -> ana<fighting>(Gran is, a)): the pieces are the anagram's own parts, in clue order."""
    if node.get("op") != "anagram" or node.get("unchecked") or not ctx.get("answer"):
        return None
    kids = [p for p in node.get("parts") or [] if isinstance(p, dict)]
    if not any(p.get("op") == "charade" for p in kids):
        return None
    new = copy.deepcopy(node)
    import flatten_anagram_fodder as FL
    if not FL.flatten_tree(new):
        return None
    if any(V._stand_in_piece(p) for p in new["parts"] if isinstance(p, dict)):
        return None
    if not _eval_swapped(node, parent, new, ctx) or V.anagram_charades(new, ctx["answer"]) >= V.anagram_charades(node, ctx["answer"]):
        return None
    return new
