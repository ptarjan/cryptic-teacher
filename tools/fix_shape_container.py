"""Container, nesting and pool repairs of fix_shape_suspects.py: what sits inside what, and the letter
pools around it. Each r_* takes (node, parent, ctx) and returns a replacement node or None.
"""
import copy
import itertools
import json
import re

import validate_annotations as V
import wordplay as W
from fix_shape_base import (
    TAIL, HEAD, MID, walk, leaf, span, vals, gives_ok, checked, charade, simplicity, _eval_swapped, _whole,
    _flat_fodder, _plain_charade, _words_between,
)
from fix_shape_indicators import _owns, _anagram_only, _owner_any, _claimed


def _literal_pool(node, c):
    """ana(ins(a, b)) whose arms are the clue's own words (no letters of their own, or just the
    words' letters): a plain anagram of the words together. The container's words are links
    unless the anagram has no word of its own, then the one container word the corpus files
    under anagram is its indicator."""
    pieces = []
    for p in c["parts"]:
        for q in (p["parts"] if _plain_charade(p) else [p]):
            if not leaf(q) or not q.get("words") or q.get("select") or q.get("soundsLike") \
                    or (q.get("gives") and W.letters(q["gives"]) != W.letters(q["words"])):
                return None
            pieces.append({k: v for k, v in q.items() if k != "gives"})
    inds = copy.deepcopy(node.get("indicators") or [])
    if not inds:
        own = [i for i in c.get("indicators") or [] if _owner_any(i) == V._OP_LEXICON.get("anagram")]
        if len(own) != 1:
            return None
        inds = [copy.deepcopy(own[0])]
    return {**{k: v for k, v in node.items() if k not in ("unchecked", "gives", "parts", "indicators")},
            "indicators": inds, "parts": pieces}


def _inside_reading(node, tree, want):
    """(letters, whole) container_inside_component reads `node` on: a container right under
    reversals that are the whole tree is read on the answer turned back (an odd count of flips
    reverses it), whole; any other node is read on the answer, whole only when it is the tree."""
    top, flips = tree, 0
    while top.get("op") == "reversal" and not top.get("unchecked") and len(top.get("parts") or []) == 1 \
            and isinstance(top["parts"][0], dict):
        top, flips = top["parts"][0], flips + 1
    if flips and top is node:
        return (want[::-1] if flips % 2 else want), True
    return want, node is tree


def r_container_inside(node, parent, ctx):
    """ins(charade(a, b, c), x) whose x can only go inside ONE piece (container_inside_component):
    the container moves into that piece, charade(a, ins(b, x), c). Its indicators and note go
    with it (the container is what they signal); the charade's filed letters stay on the
    charade. _pick keeps it only when exactly one piece gives the simplest tree that still
    evaluates to the answer."""
    answer = ctx.get("answer")
    if not answer:
        return None
    want, whole = _inside_reading(node, ctx["tree"], W.letters(answer))
    if not V._container_inside(node, want, whole):
        return None
    holder, ins = node["parts"]
    if holder.get("indicators") or "unchecked" in holder:
        return None
    cands = []
    for k, c in enumerate(holder["parts"]):
        inner = {**{x: y for x, y in node.items() if x not in ("parts", "gives")},
                 "parts": [copy.deepcopy(c), copy.deepcopy(ins)]}
        if not vals(inner):
            continue
        parts = copy.deepcopy(holder["parts"])
        parts[k] = inner
        new = {x: y for x, y in holder.items() if x != "parts"}
        new.update({x: y for x, y in node.items() if x == "gives"})
        new["op"], new["parts"] = "charade", parts
        cands.append(new)
    # not _pick: with one letter beside the piece the two shapes tie on simplicity, yet the wide
    # holder is the one the validator flags; what matters is that exactly one piece takes it
    good = {json.dumps(c, sort_keys=True): c for c in cands if _eval_swapped(node, parent, c, ctx)}
    return next(iter(good.values())) if len(good) == 1 else None


def _holder_nest(outer):
    """(holder, x, y, inner) of outer = ins(inner = ins(holder, x), y), both checked 2-part containers."""
    parts = outer.get("parts") or []
    if outer.get("op") != "container" or outer.get("unchecked") or len(parts) != 2:
        return None
    inner = parts[0]
    ip = inner.get("parts") or []
    if inner.get("op") != "container" or inner.get("unchecked") or len(ip) != 2:
        return None
    return ip[0], ip[1], parts[1], inner


def r_nested_container(node, parent, ctx):
    """ins(ins(H, x), y), a container holding a container: the regroupings that put x and y into
    H together (H holds x+y, or y+x, as one charade; H holds ins(x, y) or ins(y, x)). Of those
    that evaluate to the answer, the simplest is kept: fewest ops, then fewest letters acted on,
    then the charade in clue order (Paul 10-18: "just pick the simplest one as canonical").
    A regrouping that would put two indicators on one op is rejected (one op per indicator)."""
    got = _holder_nest(node)
    answer = ctx.get("answer")
    if not got or not answer or V._separate_insertion(node, got[3]):
        return None
    h, x, y, inner = got
    if inner.get("indicators") and node.get("indicators"):
        return None     # one op per indicator (Paul 10-18): two indicators can't share the one container
    inds = copy.deepcopy((inner.get("indicators") or []) + (node.get("indicators") or []))
    ox, oy = span(x), span(y)
    xfirst = not (ox and oy and oy[0] < ox[0])
    pairs = [(x, y), (y, x)] if xfirst else [(y, x), (x, y)]
    cands = []
    for a, b in pairs:
        cands.append({"op": "container", "indicators": inds,
                      "parts": [copy.deepcopy(h), charade([copy.deepcopy(a), copy.deepcopy(b)])]})
    for a, b in pairs:
        cands.append({"op": "container", "indicators": inds,
                      "parts": [copy.deepcopy(h), {"op": "container", "parts": [copy.deepcopy(a), copy.deepcopy(b)]}]})
    good = []
    for k, c in enumerate(cands):
        if not inds:
            c.pop("indicators")
        # the whole tree, not the node alone: the pair may sit under a reversal or inside a charade
        if not _eval_swapped(node, parent, c, ctx):
            continue
        good.append(((simplicity(c), k), c))
    if not good:
        return None
    return min(good, key=lambda g: g[0])[1]


BOTH_ENDS = re.compile(r"endless|unlimited|edgeless|boundless|peeled|shelled|skinned|topless and tailless", re.I)


def _cut_options(full, g, ind_text):
    """The letters `ind_text` takes off `full` to leave `g`: [gone] (one run), or [first, last]
    for a both-ends word; empty when the word's end does not fit or no single reading does."""
    m = len(full) - len(g)
    if m < 1:
        return []
    if BOTH_ENDS.search(ind_text):
        return [[full[0], full[-1]]] if m == 2 and full[1:-1] == g else []
    tail, head, mid = bool(TAIL.search(ind_text)), bool(HEAD.search(ind_text)), bool(MID.search(ind_text))
    if tail + head + mid != 1 or m > 3:
        return []
    if tail and full.startswith(g):
        return [[full[len(g):]]]
    if head and full.endswith(g):
        return [[full[:m]]]
    if mid and len(full) > m + 1:
        k = (len(full) - m) // 2
        cuts = {j for j in (k, len(full) - m - k) if full[:j] + full[j + m:] == g}
        return [[full[j:j + m]] for j in cuts] if len(cuts) == 1 else []
    return []


def r_container_cut(node, parent, ctx):
    """A container carrying a cut word (nearly, briefly, endlessly) that the corpus files under
    deletion, beside a leaf whose letters are one clue word (or a word its note spells in capitals)
    with the run that word names cut off: the cut word goes onto a deletion over that leaf, the
    removed run a leaf of its own (ins<endlessly>(LPS, China=HIN) is ins(LPS, del<endlessly>(
    China, C, A))). Kept only when exactly one leaf and one cut fit and the tree still gives
    the answer; a container left with no word of its own is the driver's gate to refuse."""
    if node.get("op") != "container" or node.get("unchecked") or id(node) in ctx["under_unchecked"]:
        return None
    parts = node.get("parts") or []
    found = []
    for d in node.get("indicators") or []:
        if not _owns(d, "deletion", "container"):
            continue
        for k, p in enumerate(parts):
            if not leaf(p) or p.get("unchecked") or not p.get("words") or not p.get("gives"):
                continue
            g = W.letters(p["gives"])
            fulls = [(W.letters(p["words"]), False)] if len(p["words"].split()) == 1 else []
            fulls += [(W.letters(x), True) for x in re.findall(r"\b[A-Z]{3,}\b", p.get("note") or "")]
            for full, from_note in fulls:
                for gone in _cut_options(full, g, d.get("text") or ""):
                    found.append((d, k, full, from_note, gone))
    if len({(id(f[0]), f[1], f[2], tuple(f[4])) for f in found}) != 1:
        return None
    d, k, full, from_note, gone = found[0]
    new = copy.deepcopy(node)
    src = {x: v for x, v in new["parts"][k].items() if x != "gives"}
    if from_note:
        src["gives"] = full
    new["parts"][k] = {"op": "deletion", "indicators": [copy.deepcopy(d)], "parts": [src] + [{"gives": x} for x in gone]}
    new["indicators"] = [i for i in new["indicators"] if i is not d and i != d]
    if not new["indicators"]:
        new.pop("indicators")
    return new if _eval_swapped(node, parent, new, ctx) else None


def r_extremes_outer(node, parent, ctx):
    """A first/last op over one source whose indicator names both ends ('extremely', 'extremities',
    'outer', 'edges'): the outer op, which picks the first and the last letter. Kept only when the
    whole tree then evaluates to the answer (the driver's evaluate gate), so a pick that was one
    end by design stays as it is."""
    if node.get("op") not in ("first", "last") or node.get("unchecked") or len(node.get("parts") or []) != 1 \
            or id(node) in ctx["under_unchecked"] or not leaf(node["parts"][0]) \
            or not any(V.EXTREMES_WORD.search(i.get("text") or "") for i in node.get("indicators") or []):
        return None
    new = copy.deepcopy(node)
    new["op"] = "outer"
    if not (vals(new) or ()) or not _eval_swapped(node, parent, new, ctx):
        return None
    return new


def r_pool_outer(node, parent, ctx):
    """poolGap, a container filed over the anagram alone: rake embraced by whore = ins<embraced by>(ana<dishevelled>(rake,
    SHAG)) for SHAKERAG. One fodder piece is really the other arm of the container, so it leaves the pool
    and goes beside the anagram. Used when exactly one piece and order rebuilds the answer."""
    if node.get("op") not in ("container", "insertion") or len(node.get("parts") or []) != 1:
        return None
    a = node["parts"][0]
    if a.get("op") != "anagram" or "gives" in a or a.get("unchecked") or len(a.get("parts") or []) < 2:
        return None
    flat = _flat_fodder(a)
    if len(flat) < 2 or any(not isinstance(p.get("at"), int) for p in flat):
        return None
    good = {}
    for k, piece in enumerate(flat):
        rest = [copy.deepcopy(p) for j, p in enumerate(flat) if j != k]
        inner = checked(a, parts=rest)
        for order in ((inner, copy.deepcopy(piece)), (copy.deepcopy(piece), inner)):
            new = checked(node, parts=list(order))
            if _eval_swapped(node, parent, new, ctx):
                good[json.dumps(new, sort_keys=True)] = new
    return next(iter(good.values())) if len(good) == 1 else None


def r_pool_gap(node, parent, ctx):
    """poolGap: an insertion/container over an anagram and plain leaf pieces, whose indicator words sit
    between the anagram's fodder (Camels wandering about every second: ins<wandering>(ana<about>(..), S)).
    When the anagram of all the pieces gives the same letters and the container's indicator is
    right beside the anagram's, the two indicators are one anagram indicator over every piece."""
    if node.get("op") not in ("container", "insertion"):
        return None
    if len(node.get("parts") or []) == 1:
        return r_pool_outer(node, parent, ctx)
    if node.get("unchecked"):
        return None
    clue = ctx["clue"]
    ana = [p for p in node.get("parts") or [] if p.get("op") == "anagram"]
    others = [p for p in node.get("parts") or [] if p.get("op") != "anagram"]
    if len(ana) != 1 or not others or not V.pool_gaps(node, clue) or ana[0].get("unchecked"):
        return None
    a = ana[0]
    if any(not leaf(p) or not p.get("words") for p in others) or "gives" in a:
        return None
    inds = [*(a.get("indicators") or []), *(node.get("indicators") or [])]
    if len(inds) < 2 or any(not isinstance(i.get("at"), int) or not i.get("text") for i in inds):
        return None
    if any(not _anagram_only(i) for i in node.get("indicators") or []):
        return None     # "between", "in", "around", "split": container words too (split frightfully is a real insertion)
    inds.sort(key=lambda i: i["at"])
    for x, y in zip(inds, inds[1:]):
        if not _words_between(clue, x["at"] + len(x["text"]), y["at"]):
            return None
    pieces = sorted([*_flat_fodder(a), *others], key=lambda p: p.get("at") if isinstance(p.get("at"), int) else 10**6)
    new = checked(a, parts=copy.deepcopy(pieces), indicators=copy.deepcopy(inds))
    if node.get("gives") is not None:
        new["gives"] = node["gives"]
        if not gives_ok(new, W.letters(node["gives"])):
            return None
    if V.pool_gaps(new, clue):
        return None
    return new


def _has_letters(p):
    """A piece that is checked all the way down and gives letters of its own."""
    if any(n.get("unchecked") for n, _ in walk(p)):
        return False
    v = vals(p)
    return bool(v) and "" not in v


def _eject_candidates(ana):
    """(piece, inner anagram) for each fodder piece taken out of the pool (the rest kept, in order)."""
    flat = _flat_fodder(ana)
    if len(flat) < 2 or any(not isinstance(p, dict) for p in flat):
        return
    for k, piece in enumerate(flat):
        if _has_letters(piece):
            yield copy.deepcopy(piece), checked(ana, parts=[copy.deepcopy(p) for j, p in enumerate(flat) if j != k])


def r_pool_absorb(node, parent, ctx):
    """poolGap, the mirror of r_pool_eject: a charade of an anagram and a plain one-piece neighbour
    (a leaf, a first/last pick) whose clue words stand between the anagram's fodder pieces, ana(goes, at, us) + R
    for "goes right at us, surprisingly". The model pulled the letter out to satisfy anaLoneEdge (the answer
    ends in R), but the clue gathers it into the pool: the piece joins the pool in clue order. Kept only
    when exactly one reading still gives the answer and the pool gap is gone."""
    clue, answer = ctx["clue"], ctx.get("answer")
    parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
    before = V.pool_gaps(ctx["tree"], clue) if clue else 0
    if node.get("op") != "charade" or node.get("unchecked") or "gives" in node or not answer or not before:
        return None
    if len(parts) != len(node.get("parts") or []) or len(parts) < 2:
        return None
    low = clue.lower()
    good = {}
    for i, a in enumerate(parts):
        if a.get("op") != "anagram" or a.get("unchecked") or "gives" in a or len(a.get("parts") or []) < 2:
            continue
        for j in (i - 1, i + 1):
            if not 0 <= j < len(parts):
                continue
            s = parts[j]
            if s.get("unchecked") or not (leaf(s) or s.get("op") in ("first", "last")) or not _has_letters(s):
                continue
            pool = [*_flat_fodder(a), s]
            ext = [V._extent(p, clue, low) for p in pool]
            if any(e is None for e in ext):
                continue
            pool = [copy.deepcopy(pool[k]) for _, k in sorted((e[0], k) for k, e in enumerate(ext))]
            merged = checked(a, parts=pool)
            kept = [merged if k == i else p for k, p in enumerate(parts) if k != j]
            new = kept[0] if len(kept) == 1 else charade(copy.deepcopy(kept))
            if len(kept) == 1:
                new = copy.deepcopy(new)
            if _eval_swapped(node, parent, new, ctx) and V.pool_gaps(_whole(node, parent, new, ctx), clue) < before:
                good[json.dumps(new, sort_keys=True)] = new
    return next(iter(good.values())) if len(good) == 1 else None


def r_pool_eject(node, parent, ctx):
    """poolGap, a piece in the anagram's pool that is really another op's: it leaves the pool and
    goes beside the anagram (HE + ana(N, thing) -> HE + N + ana(thing)), or into the container
    arm next to it (ins(ana(gold, a), P) -> ins(ana(gold), a+P)). Kept only when exactly one piece,
    place and order gives the answer and the pool gap is gone."""
    clue, answer = ctx["clue"], ctx.get("answer")
    if not answer or not V.pool_gaps(ctx["tree"], clue):
        return None
    cands = []
    if node.get("op") == "anagram":
        if node.get("unchecked") or "gives" in node or not V.pool_gaps(node, clue) and not V.pool_gaps(ctx["tree"], clue):
            return None
        for piece, inner in _eject_candidates(node):
            cands += [charade([inner, piece]), charade([piece, inner])]
    elif node.get("op") in ("container", "insertion") and not node.get("unchecked") and len(node.get("parts") or []) == 2:
        for j, ana in enumerate(node["parts"]):
            if ana.get("op") != "anagram" or ana.get("unchecked") or "gives" in ana:
                continue
            sib = node["parts"][1 - j]
            for piece, inner in _eject_candidates(ana):
                for joined in (charade([piece, copy.deepcopy(sib)]), charade([copy.deepcopy(sib), piece])):
                    ps = [copy.deepcopy(inner), joined] if j == 0 else [joined, copy.deepcopy(inner)]
                    cands.append(checked(node, parts=ps))
    before = V.pool_gaps(ctx["tree"], clue)
    good = {}
    for c in cands:
        if _eval_swapped(node, parent, c, ctx) and V.pool_gaps(_whole(node, parent, c, ctx), clue) < before:
            good[json.dumps(c, sort_keys=True)] = c
    return next(iter(good.values())) if len(good) == 1 else None


#: Words that join a container's indicator phrase without saying "contains" themselves.
_GAP_STOP = frozenset({"to", "a", "the", "of", "is", "be", "and", "will", "can", "that", "by", "has", "was"})


def _span_of(node):
    """(start, end) of the clue characters under `node` (leaf words and indicators), or None when one has no place."""
    lo, hi = None, 0
    for x, _ in walk(node):
        for at, t in ([(x.get("at"), x.get("words"))] if leaf(x) else []) + [(i.get("at"), i.get("text")) for i in x.get("indicators") or []]:
            if not t:
                continue
            if not isinstance(at, int):
                return None
            lo, hi = at if lo is None else min(lo, at), max(hi, at + len(t))
    return None if lo is None else (lo, hi)


def r_container_gap(node, parent, ctx, count=None):
    """unindicatedBare, container: a bare two-part container whose argument spans are apart in the clue by
    one to three words no leaf or indicator uses, one of them a container word the corpus files that way
    (share 0.7, 20+ uses): the gap is the indicator, whole ("put around", "embraced by", "cutting"). The
    one-word spare fixer takes "put" or "embraced" alone; the gap says all of it. Kept only when the
    validator then counts fewer bare ops."""
    count = count or V.unindicated_ops
    if node.get("op") != "container" or node.get("unchecked") or node.get("indicators") \
            or id(node) in ctx["under_unchecked"]:
        return None
    kids = [p for p in node.get("parts") or [] if isinstance(p, dict)]
    spans = [_span_of(k) for k in kids]
    if len(kids) != 2 or None in spans:
        return None
    (a0, a1), (b0, b1) = sorted(spans)
    clue = ctx["clue"]
    gap = clue[a1:b0]
    cov = _claimed(ctx["tree"], clue)
    words = re.findall(r"[A-Za-z']+", gap)
    if not 1 <= len(words) <= 3 or re.search(r"[^A-Za-z' ]", gap.strip(" ,;")):
        return None
    if any(c for c, ch in zip(cov[a1:b0], gap) if c and ch != " "):
        return None
    anchor = False
    for w in words:
        counts = V._role_counts(V.indicator_role_key(w))
        total = sum(counts.values())
        if total >= 20 and counts.get("container", 0) >= 0.7 * total:
            anchor = True
        elif w.lower() not in _GAP_STOP and total >= 20 and counts.get("container", 0) < 0.3 * total:
            return None
    if not anchor:
        return None
    text = gap.strip(" ,;")
    at = a1 + gap.index(text)
    base = count(ctx["tree"])
    node["indicators"] = [{"text": text, "at": at, "note": "the clue words that say one part holds the other"}]
    if count(ctx["tree"]) < base:
        return node
    node.pop("indicators")
    return None


def r_reversal_split(node, parent, ctx):
    """reversalSplit: a multi-part reversal whose indicator sits between its pieces in the clue reverses
    only the piece beside it. One piece takes the reversal (its own indicator), the others join it in a
    charade, in whichever order gives the answer. Kept only when exactly one tree does."""
    if node.get("op") != "reversal" or node.get("unchecked") or not ctx.get("answer"):
        return None
    parts = node.get("parts") or []
    inner = None            # the reversal sits over one charade/container: its pieces are the ones
    if len(parts) == 1 and isinstance(parts[0], dict) and parts[0].get("op") in ("charade", "container"):
        inner = parts[0]
        parts = inner.get("parts") or []
    if len(parts) < 2 or len(parts) > 4 or any(not isinstance(p, dict) or p.get("unchecked") for p in parts):
        return None
    if inner is not None and (inner.get("unchecked") or inner.get("indicators") and inner["op"] == "charade"):
        return None
    base_op = inner["op"] if inner is not None else "charade"
    orders = [tuple(range(len(parts)))] if base_op == "container" else list(itertools.permutations(range(len(parts))))
    good = {}
    for i in range(len(parts)):
        rev = {key: v for key, v in node.items() if key not in ("parts", "unchecked", "gives")}
        rev["parts"] = [copy.deepcopy(parts[i])]
        rest = [copy.deepcopy(p) for j, p in enumerate(parts) if j != i]
        for order in orders:
            seq = [rev if k == i else rest[k - (k > i)] for k in order]
            cand = {key: v for key, v in (inner or {}).items() if key not in ("parts", "gives")}
            cand.update({"op": base_op, "parts": copy.deepcopy(seq)})
            if _eval_swapped(node, parent, cand, ctx):
                good[json.dumps(cand, sort_keys=True)] = cand
    return next(iter(good.values())) if len(good) == 1 else None


def r_nested_same_op(node, parent, ctx):
    """nestedSameOp: del(del(X, a), b) where only one of the two deletions carries an indicator: one indicator is
    one op, and a deletion takes several cuts, so it becomes del<ind>(X, a, b). Only deletions (a container takes
    two parts, a reversal one, so those have no unique flat form). Kept only when the tree still gives the answer
    and the validator's rule no longer fires."""
    parts = node.get("parts") or []
    if node.get("op") != "deletion" or node.get("unchecked") or not ctx.get("answer") or len(parts) < 2 \
            or any(not isinstance(p, dict) for p in parts):
        return None
    inner = parts[0]
    if inner.get("op") != "deletion" or inner.get("unchecked") or bool(inner.get("indicators")) == bool(node.get("indicators")):
        return None
    if any(p.get("op") for p in parts[1:]) or any(p.get("op") for p in (inner.get("parts") or [])[1:]):
        return None
    new = {x: copy.deepcopy(y) for x, y in node.items() if x not in ("parts", "gives", "indicators")}
    inds = node.get("indicators") or inner.get("indicators")
    new["indicators"] = copy.deepcopy(inds)
    new["parts"] = copy.deepcopy(inner["parts"]) + copy.deepcopy(parts[1:])
    if node.get("gives") is not None:
        new["gives"] = node["gives"]
    if len(new["parts"]) > 9 or not _eval_swapped(node, parent, new, ctx) or V.nested_same_op(new) > V.nested_same_op(node) - 1:
        return None
    return new


def r_del_wraps_charade(node, parent, ctx):
    """delWrapsCharade: del<ind>(charade(a, b, ...), X) of plain leaves whose indicator stands in the clue between
    two pieces: it cuts the piece touching it (PUSS 'Manx' cat: rev(RATS + RE + del<Manx>(PUSS, S))). The piece is
    the one holding X whose clue words sit right against the indicator (only blanks or punctuation between); kept
    only when exactly one such piece exists, the whole tree still gives the answer and the rule no longer fires."""
    clue = ctx.get("clue") or ""
    if V.del_wraps_charade(node, clue) != 1 or node.get("op") != "deletion" or not ctx.get("answer"):
        return None
    parts = node["parts"]
    comps = parts[0]["parts"]
    cut = W.letters(parts[1]["gives"])
    ind = node["indicators"][0]
    low = clue.lower()
    t = str(ind["text"])
    a0 = ind["at"] if isinstance(ind.get("at"), int) else low.find(t.lower())
    b0 = a0 + len(t)
    near = []
    for k, c in enumerate(comps):
        g = W.letters(c.get("gives") or c.get("words"))
        if not (len(g) > len(cut) and cut in g):
            continue
        sp = V._subtree_spans(c, clue, low)
        if not sp:
            continue
        lo, hi = min(a for a, _ in sp), max(b for _, b in sp)
        gap = clue[hi:a0] if hi <= a0 else clue[b0:lo] if lo >= b0 else None
        if gap is not None and not W.letters(gap):
            near.append(k)
    if len(near) != 1:
        return None
    k = near[0]
    inner = {x: y for x, y in node.items() if x not in ("parts", "gives")}
    inner["parts"] = [copy.deepcopy(comps[k]), copy.deepcopy(parts[1])]
    pieces = copy.deepcopy(comps)
    pieces[k] = inner
    new = {x: y for x, y in parts[0].items() if x not in ("parts", "gives")}
    new["op"], new["parts"] = "charade", pieces
    if node.get("gives") is not None:
        new["gives"] = node["gives"]
    if not _eval_swapped(node, parent, new, ctx) or V.del_wraps_charade(new, clue):
        return None
    return new
