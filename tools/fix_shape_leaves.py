"""Leaf-level repairs of fix_shape_suspects.py: trimming a leaf or its indicator, checking a leaf,
folding a leaf's words, and the arity regroupings. Each r_* takes (node, parent, ctx) and returns a
replacement node or None.
"""
import copy
import itertools
import json
import re

import annotation
import validate_annotations as V
import wordplay as W
from fix_shape_base import (
    UNARY, TAIL, HEAD, MID, walk, leaf, span, vals, gives_ok, checked, charade, clue_text, _eval_swapped,
    unchecked,
)


# ---------- repairs: each takes (node, parent, ctx) and returns a replacement or None ----------

def r_ins_split(node, parent, ctx):
    if node.get("op") != "container" or len(node.get("parts") or []) == 2 or not node.get("unchecked"):
        return None
    parts = node["parts"]
    if len(parts) == 1:
        c = parts[0]
        if c.get("op") != "charade" or c.get("indicators") or c.get("unchecked"):
            return None
        parts = c["parts"]
    want = W.letters(node.get("gives"))
    if len(parts) < 3 or not want:
        return None
    spans = [span(p) for p in parts]
    if any(s is None for s in spans):
        return None
    found = set()
    for ind in node.get("indicators") or []:
        if ind.get("at") is None:
            continue
        a, b = ind["at"], ind["at"] + len(ind["text"])
        side = []
        for s in spans:
            if s[1] <= a:
                side.append("B")
            elif s[0] >= b:
                side.append("A")
            else:
                side = None
                break
        if not side:
            continue
        for g in "AB":
            idx = [i for i, x in enumerate(side) if x == g]
            if idx and idx[0] > 0 and idx[-1] < len(parts) - 1 and idx == list(range(idx[0], idx[-1] + 1)):
                found.add((idx[0], idx[-1]))
    if len(found) > 1 or (not found and len(parts) != 3):
        return None

    def build(i, j):
        inner = charade(copy.deepcopy(parts[i:j + 1]))
        outer = charade(copy.deepcopy(parts[:i] + parts[j + 1:]))
        for arm in (inner, outer):
            seen = [(p.get("words"), p.get("at")) for p in arm.get("parts") or [] if leaf(p) and p.get("words")]
            if len(seen) != len(set(seen)):
                return None     # the same clue words twice in one arm: a container inside it
        new = checked(node, parts=[outer, inner])
        return new if gives_ok(new, want) else None
    if found:
        return build(*found.pop())
    # No indicator position decides it (it sits inside a part's words or the parts are unplaced):
    # a flat 3-part charade is part 2 inside parts 1+3, when no other single part held
    # by the other two also spells the answer.
    if any(not leaf(p) or p.get("unchecked") for p in parts):
        return None
    reads = [build(i, i) for i in range(3)]
    return reads[1] if reads[1] and not reads[0] and not reads[2] else None


def r_del_removed(node, parent, ctx):
    if node.get("op") != "deletion" or len(node.get("parts") or []) != 1 or not node.get("unchecked"):
        return None
    inds = [i.get("text") or "" for i in node.get("indicators") or []]
    if len(inds) != 1:
        return None
    tail, head, mid = bool(TAIL.search(inds[0])), bool(HEAD.search(inds[0])), bool(MID.search(inds[0]))
    if tail + head + mid != 1:
        return None
    want = W.letters(node.get("gives"))
    vs = vals(node["parts"][0])
    if not want or not vs or len(vs) != 1:
        return None
    v = next(iter(vs))
    m = len(v) - len(want)
    if not 1 <= m <= 3:
        return None
    if tail and v.startswith(want):
        gone = v[len(want):]
    elif head and v.endswith(want):
        gone = v[:m]
    elif mid and len(v) > m + 1:
        # A central run: the letters kept either side differ in number by at most one.
        k = (len(v) - m) // 2
        cuts = {j for j in (k, len(v) - m - k) if v[:j] + v[j + m:] == want}
        if len(cuts) != 1:
            return None
        j = cuts.pop()
        gone = v[j:j + m]
    else:
        return None
    new = checked(node, parts=[copy.deepcopy(node["parts"][0]), {"gives": gone}])
    return new if gives_ok(new, want) else None


def _inside_leaf(ind, tree):
    """Whether the indicator's words sit inside a leaf's clue words."""
    t = W.letters(ind.get("text"))
    for n, _ in walk(tree):
        if leaf(n) and n.get("words"):
            if ind.get("at") is not None and n.get("at") is not None:
                if n["at"] <= ind["at"] and ind["at"] + len(ind.get("text") or "") <= n["at"] + len(n["words"]):
                    return True
            elif t and t in [W.letters(w) for w in n["words"].split()] and W.letters(n["words"]) != t:
                return True
    return False


def r_del_unwrap(node, parent, ctx):
    """A one-part deletion whose part already gives the node's letters removes nothing:
    the removal is inside a leaf's letters. The node goes when its own indicators are
    none or sit inside a leaf's words (the leaf already reads them)."""
    if node.get("op") != "deletion" or len(node.get("parts") or []) != 1 or not node.get("unchecked"):
        return None
    want = W.letters(node.get("gives"))
    child = node["parts"][0]
    if not want or not gives_ok(child, want):
        return None
    if not all(_inside_leaf(i, ctx["tree"]) for i in node.get("indicators") or []):
        return None
    return copy.deepcopy(child)


def r_link_leaf(node, parent, ctx):
    """An unchecked leaf filed with no letters (a link or position word) is an
    indicator of its op, its note kept; the op keeps two or more parts."""
    if leaf(node) or node.get("op") != "charade" or node.get("unchecked"):
        return None
    parts = node.get("parts") or []
    k = [i for i, p in enumerate(parts) if leaf(p) and p.get("unchecked") and p.get("words")
         and not W.letters(p.get("gives"))]
    if len(k) != 1 or len(parts) - 1 < 2:
        return None
    p = parts[k[0]]
    ind = {"text": p["words"], **({"at": p["at"]} if "at" in p else {}),
           **({"note": p["note"]} if p.get("note") else {})}
    new = copy.deepcopy(node)
    new["parts"] = [copy.deepcopy(x) for i, x in enumerate(parts) if i != k[0]]
    new["indicators"] = (new.get("indicators") or []) + [ind]
    return new


def r_sel_literal(node, parent, ctx):
    """An unchecked leaf under a selection op, filed with the selection's result:
    the selection over its own words gives those letters, so it is literal."""
    if leaf(node) or node.get("op") not in W.SELECT or len(node.get("parts") or []) != 1:
        return None
    p = node["parts"][0]
    if not leaf(p) or not p.get("unchecked") or not p.get("words"):
        return None
    want = W.letters(node.get("gives")) if node.get("unchecked") else W.letters(p.get("gives"))
    if not want:
        return None
    lit = {k: v for k, v in p.items() if k not in ("unchecked", "gives")}
    new = checked(node, parts=[lit]) if node.get("unchecked") else {**copy.deepcopy(node), "parts": [lit]}
    return new if vals(new) == {want} else None


def r_arity_wrap(node, parent, ctx):
    op, parts = node.get("op"), node.get("parts") or []
    want = W.letters(node.get("gives"))
    if not node.get("unchecked") or not want:
        return None
    cands = []
    def P():
        return copy.deepcopy(parts)

    if op in UNARY and len(parts) >= 2:
        cands.append(checked(node, parts=[charade(P())]))
        p = P()
        cands.append(charade([checked(node, parts=[p[0]])] + p[1:]))
        p = P()
        cands.append(charade(p[:-1] + [checked(node, parts=[p[-1]])]))
    elif op == "deletion" and len(parts) >= 3:
        p = P()
        cands.append(checked(node, parts=[charade(p[:-1]), p[-1]]))
        p = P()
        cands.append(charade(p[:-2] + [checked(node, parts=p[-2:])]))
    elif op == "substitution" and len(parts) == 2:
        xs, news = vals(parts[0]), vals(parts[1])
        if not xs or not news or len(xs) != 1 or len(news) != 1:
            return None
        x, nw = next(iter(xs)), next(iter(news))
        inds = " ".join(i.get("text") or "" for i in node.get("indicators") or [])
        tail, head = bool(TAIL.search(inds)), bool(HEAD.search(inds))
        if tail == head:
            return None
        for k in range(len(want) - len(nw) + 1):
            if want[k:k + len(nw)] != nw or want[:k] != x[:k]:
                continue
            rest = want[k + len(nw):]
            if len(x) - len(rest) > k and x.endswith(rest):
                old = x[k:len(x) - len(rest)]
                # Only letters the indicator names: one or two at the end it names.
                if len(old) > 2 or not ((head and k == 0) or (tail and not rest)):
                    continue
                p = P()
                cands.append(checked(node, parts=[p[0], {"gives": old}, p[1]]))
    good = [c for c in cands if gives_ok(c, want)]
    uniq = {json.dumps(c, sort_keys=True): c for c in good}
    return next(iter(uniq.values())) if len(uniq) == 1 else None


def _trimmed_leaf(lf, a, b, clue):
    """`lf` without the clue span a..b at its start or end, or None."""
    if lf.get("at") is None or not lf.get("words") or clue[lf["at"]:lf["at"] + len(lf["words"])] != lf["words"]:
        return None
    la, lb = lf["at"], lf["at"] + len(lf["words"])
    if not (la <= a and b <= lb) or (a, b) == (la, lb):
        return None
    if a == la:
        text, at = clue_text(clue, b, lb)
    elif b == lb:
        text, at = clue_text(clue, la, a)
    else:
        return None
    if not W.letters(text):
        return None
    new = {**lf, "words": text, "at": at}
    return new


def r_leaf_trim(node, parent, ctx):
    if leaf(node) or not node.get("indicators") or node.get("unchecked") or id(node) in ctx["under_unchecked"]:
        return None         # only where the evaluator checks the trimmed leaf's letters
    clue = ctx["clue"]
    for ind in node["indicators"]:
        if ind.get("at") is None or not ind.get("text"):
            continue
        a, b = ind["at"], ind["at"] + len(ind["text"])
        for k, p in enumerate(node.get("parts") or []):
            if not leaf(p):
                continue
            new = _trimmed_leaf(p, a, b, clue)
            if new is None:
                continue
            before = vals(node) if not node.get("unchecked") else {W.letters(node.get("gives"))}
            literal = "gives" not in p or W.letters(p["gives"]) == W.letters(p["words"])
            tries = []
            plain = {x: y for x, y in new.items() if x not in ("gives", "unchecked")}
            if literal and node.get("unchecked"):
                continue        # its letters change and nothing above checks them
            if literal:
                tries.append(plain)
            else:
                if node.get("op") in W.SELECT:
                    tries.append(plain)
                tries.append(new)
            for t in tries:
                cand = copy.deepcopy(node)
                cand["parts"][k] = t
                if node.get("unchecked"):
                    if before and gives_ok(cand, next(iter(before))):
                        return cand
                elif before is not None and (vals(cand) or set()) & before:
                    return cand
    return None


def r_ind_trim(node, parent, ctx):
    if leaf(node) or not node.get("indicators"):
        return None
    clue = ctx["clue"]
    for n, ind in enumerate(node["indicators"]):
        if ind.get("at") is None or not ind.get("text"):
            continue
        a, b = ind["at"], ind["at"] + len(ind["text"])
        for p in node.get("parts") or []:
            if not leaf(p) or p.get("at") is None or not p.get("words"):
                continue
            la, lb = p["at"], p["at"] + len(p["words"])
            if not (a <= la and lb <= b) or (la, lb) == (a, b):
                continue
            if la == a:
                text, at = clue_text(clue, lb, b)
            elif lb == b:
                text, at = clue_text(clue, a, la)
            else:
                continue
            if not W.letters(text):
                continue
            cand = copy.deepcopy(node)
            cand["indicators"][n] = {**ind, "text": text, "at": at}
            return cand
    return None


def r_leaf_check(node, parent, ctx):
    if not leaf(node) or not node.get("unchecked") or not node.get("words"):
        return None
    if id(node) in ctx["under_unchecked"]:
        return None         # nothing above it would check the letters it gives
    g = W.letters(node.get("gives"))
    if not g or g == W.letters(node["words"]):
        return {k: v for k, v in node.items() if k not in ("unchecked", "gives")}
    if annotation.is_abbreviation(node):
        return {k: v for k, v in node.items() if k != "unchecked"}
    if parent is not None and parent.get("op") in W.SELECT:
        return None
    found = V.selector_in_block({"clueFragment": node["words"], "gives": g})
    if not found or node.get("at") is None:
        return None
    sel, rest = found
    words = node["words"]
    si, ri = words.find(sel), words.find(rest)
    if si < 0 or ri < 0:
        return None
    src = {"words": rest, "at": node["at"] + ri}
    ops = [op for op in ("first", "last", "middle")
           if g in (vals({"op": op, "parts": [src]}) or set())]
    if len(ops) != 1:
        return None
    return {"op": ops[0], "indicators": [{"text": sel, "at": node["at"] + si}], "parts": [src]}


def r_leaf_fold(node, parent, ctx):
    """A leaf of 3+ words with a deletion word whose letters are one of its words with a run cut
    out (gates having lost a -> GTES): the deletion op over that word, the cut a leaf of its own
    when another word of the leaf spells it, else the indicator names the end it comes from
    (r_del_removed). A leaf that gives exactly one of its own words keeps just that word."""
    if not leaf(node) or node.get("unchecked") or not node.get("words") or not node.get("gives") \
            or node.get("at") is None:
        return None
    if id(node) in ctx["under_unchecked"]:
        return _fold_two_cuts(node, ctx)    # its letters are checked on their own, wherever it sits
    toks = node["words"].split()
    if len(toks) < 3 or len(node["gives"]) > 4 or not V._deletion_word_in(node["words"], node["gives"]):
        return None
    g = W.letters(node["gives"])
    clue = ctx["clue"]
    pos, at = [], node["at"]
    for t in toks:
        i = clue.find(t, at)
        if i < 0:
            return None
        pos.append((t, i))
        at = i + len(t)
    plain = lambda t: W.letters(t)
    delw = [k for k, (t, _) in enumerate(pos) if V.DELETION_LEAF_WORD.fullmatch(re.sub(r"\W", "", t))]
    outs = []
    for k, (t, i) in enumerate(pos):
        w = plain(t)
        if k in delw or not w:
            continue
        if w == g:
            outs.append(("lit", k, ""))
            continue
        if len(g) < len(w):
            for j in range(len(w)):
                for m in range(1, len(w) - len(g) + 1):
                    if w[:j] + w[j + m:] == g:
                        outs.append(("cut", k, w[j:j + m]))
    cuts = {(kind, k, gone) for kind, k, gone in outs}
    if len({(k, kind) for kind, k, _ in cuts}) != 1:
        return _fold_two_cuts(node, ctx) if not outs else None
    kind, k, _ = next(iter(cuts))
    wleaf = {"words": pos[k][0], "at": pos[k][1]}
    if kind == "lit":
        return wleaf
    rest = [p for q, p in enumerate(pos) if q != k]
    gones = {gone for kd, kk, gone in cuts}
    for q, (t, i) in enumerate(pos):
        if q != k and q not in delw and (plain(t) in gones or any(
                annotation.is_abbreviation({"words": t, "gives": x}) for x in gones)):
            ind = [p for r, p in enumerate(pos) if r not in (k, q)]
            ind_txt = " ".join(t2 for t2, _ in ind)
            if not ind or not clue[ind[0][1]:ind[-1][1] + len(ind[-1][0])] .replace("  ", " ") == ind_txt:
                return None
            cut = {"words": t, "at": i}
            if plain(t) not in gones:    # a table abbreviation (five -> V): the cut names its letters
                cut["gives"] = next(x for x in sorted(gones) if annotation.is_abbreviation({"words": t, "gives": x}))
            new = {"op": "deletion", "indicators": [{"text": ind_txt, "at": ind[0][1]}], "parts": [wleaf, cut]}
            return new if gives_ok(new, g) or g in (vals(new) or ()) else None
    ind_txt = " ".join(t for t, _ in rest)
    ind = {"text": ind_txt, "at": rest[0][1]}
    if clue[rest[0][1]:rest[-1][1] + len(rest[-1][0])] != ind_txt:
        return None
    probe = {"op": "deletion", "unchecked": True, "gives": g, "indicators": [ind], "parts": [wleaf]}
    return r_del_removed(probe, parent, ctx)


def _fold_two_cuts(node, ctx):
    """A leaf folding two cuts out of one word (Labour's lacking a British -> LOUR): a deletion
    word, a source word, and two words that each spell (or abbreviate, by the table) a run of the
    source; the deletion op over the source and both cuts, when its letters give the leaf's."""
    toks = node["words"].split()
    if len(toks) != 4 or not V._deletion_word_in(node["words"]):
        return None
    clue, g = ctx["clue"], W.letters(node["gives"])
    pos, at = [], node["at"]
    for t in toks:
        i = clue.find(t, at)
        if i < 0:
            return None
        pos.append((t, i))
        at = i + len(t)
    delw = [k for k, (t, _) in enumerate(pos) if V.DELETION_LEAF_WORD.fullmatch(re.sub(r"\W", "", t))]
    if len(delw) != 1:
        return None
    d = delw[0]
    found = []
    for k, (t, i) in enumerate(pos):
        stem = re.sub(r"['’]s$", "", t)
        w = W.letters(stem)
        if k == d or len(w) <= len(g):
            continue
        cutpos = [q for q in range(4) if q not in (d, k)]
        for order in (cutpos, cutpos[::-1]):
            opts = [[x for x in {w[a:b] for a in range(len(w)) for b in range(a + 1, len(w) + 1)}
                     if W.letters(pos[q][0]) == x or annotation.is_abbreviation({"words": pos[q][0], "gives": x})]
                    for q in order]
            for x1 in opts[0]:
                for x2 in opts[1]:
                    if w.replace(x1, "", 1).replace(x2, "", 1) == g and len(x1) + len(x2) == len(w) - len(g):
                        found.append((k, stem, order, x1, x2))
    if len({(f[0], tuple(sorted(zip(f[2], f[3:])))) for f in found}) != 1:
        return None
    k, stem, order, x1, x2 = found[0]
    ind_tok = pos[d]
    # the deletion word and the cuts keep clue order; the indicator is the deletion word alone
    cuts = [{"words": pos[q][0], "at": pos[q][1], "gives": x} for q, x in sorted(zip(order, (x1, x2)))]
    src = {"words": stem, "at": pos[k][1]}
    new = {"op": "deletion", "indicators": [{"text": ind_tok[0], "at": ind_tok[1]}], "parts": [src, *cuts]}
    return new if gives_ok(new, g) else None


def r_ind_in_leaf(node, parent, ctx):
    """indInLeaf / ind_in_leaf: a leaf took the clue words of an indicator as well as its own
    ([books essentially]BOOKS under mostly/essentially on an op). The indicator's span, located in
    the clue, lies at the start or end of this leaf: the leaf keeps the words that give its letters.
    A synonym leaf keeps its filed letters; a literal one gives its remaining words. Kept only when
    the whole tree still evaluates to the answer. An indicator in the middle of a leaf stays for
    the model."""
    if not leaf(node) or not node.get("words") or node.get("at") is None or not ctx.get("answer"):
        return None
    clue = ctx["clue"]
    if clue[node["at"]:node["at"] + len(node["words"])] != node["words"]:
        return None
    la, lb = node["at"], node["at"] + len(node["words"])
    for n, _ in walk(ctx["tree"]):
        for ind in n.get("indicators") or []:
            if ind.get("at") is None or not ind.get("text") or len(W.letters(ind["text"])) < 3:
                continue
            a, b = ind["at"], ind["at"] + len(ind["text"])
            if not (la <= a and b <= lb) or (a, b) == (la, lb) or (a != la and b != lb):
                continue
            text, at = clue_text(clue, b, lb) if a == la else clue_text(clue, la, a)
            if not W.letters(text):
                continue
            literal = not node.get("gives") or W.letters(node["gives"]) == W.letters(node["words"])
            new = {k: v for k, v in node.items() if k not in ("gives", "unchecked")} if literal else dict(node)
            new.update(words=text, at=at)
            if _eval_swapped(node, parent, new, ctx):
                return new
    return None


def _tokens(words):
    return [(m.start(), m.end(), m.group().lower()) for m in re.finditer(r"[A-Za-z0-9']+", words)]


def r_own_ind_leaf(node, parent, ctx):
    """selectWordInLeaf / ownIndInLeaf: a leaf under an op opens (any op but an anagram) or ends (any op)
    with the op's own indicator words and holds more ("bit of breakfast" under first<bit of>, "French way
    back" under rev<back>): the leaf keeps only the words after (before) them. A literal leaf stays
    literal; a synonym leaf keeps its filed letters. Kept only when the whole tree still evaluates to
    the answer (the validator gate in run_rule then judges the rest)."""
    if not leaf(node) or not node.get("words") or parent is None or "op" not in parent or parent["op"] == "anagram" \
            or parent.get("unchecked") or not ctx.get("answer"):
        return None
    toks = _tokens(node["words"])
    for ind in parent.get("indicators") or []:
        iw = [t for _, _, t in _tokens(str(ind.get("text") or ""))]
        if not iw or len(toks) <= len(iw):
            continue
        at_start = [t for _, _, t in toks[:len(iw)]] == iw
        at_end = [t for _, _, t in toks[-len(iw):]] == iw
        if at_start and parent["op"] not in W.SELECT:
            cut = (toks[len(iw)][0], len(node["words"]))
        elif at_start:
            cut = (toks[len(iw)][0], len(node["words"]))
        elif at_end:
            cut = (0, toks[-len(iw) - 1][1])
        else:
            continue
        words = node["words"][cut[0]:cut[1]]
        text = words.strip(" ,;:.!?—–-\"“”‘(){}[]")
        if not W.letters(text):
            continue
        lead = len(words) - len(words.lstrip(" ,;:.!?—–-\"“”‘(){}[]"))
        literal = not node.get("gives") or W.letters(node["gives"]) == W.letters(node["words"])
        new = {k: v for k, v in node.items() if k not in ("gives", "unchecked")} if literal else dict(node)
        new["words"] = text
        if node.get("at") is not None:
            new["at"] = node["at"] + cut[0] + lead
        if _eval_swapped(node, parent, new, ctx):
            return new
    return None


def r_trunc_leaf(node, parent, ctx):
    """truncInLeaf: a leaf holds a truncation word at its edge (mostly, almost, ...) and gives its word one
    letter short. The whole word is known (the leaf's own clue words, or a one-off capitalised word of the
    right length in its note that the filed letters cut): the leaf becomes del<mostly>([words]WHOLE, C).
    A synonym whose whole word is nowhere in the leaf stays for the model."""
    if not leaf(node) or not node.get("words") or not node.get("gives") or node.get("unchecked") \
            or not ctx.get("answer"):
        return None
    toks = _tokens(node["words"])
    low = " ".join(t for _, _, t in toks)
    ind = None
    for phrase in sorted(V._TRUNC_PHRASES, key=len, reverse=True):
        for a, b in ((0, len(phrase.split())), (len(toks) - len(phrase.split()), len(toks))):
            if len(toks) > b - a and " ".join(t for _, _, t in toks[a:b]) == phrase:
                ind = (a, b)
        if ind:
            break
    if not ind:
        for a, b in ((0, 1), (len(toks) - 1, len(toks))):
            if len(toks) > 1 and toks[a][2] in V._TRUNC_WORDS:
                ind = (a, b)
                break
    if not ind:
        return None
    a, b = ind
    ia, ib = toks[a][0], toks[b - 1][1]
    rest = (node["words"][ib:] if a == 0 else node["words"][:ia])
    rest_tok = [t for _, _, t in _tokens(rest)]
    if not rest_tok or (rest_tok[0] if a == 0 else rest_tok[-1]) in ("with", "the", "end", "its", "his", "her", "a", "an", "of"):
        return None   # "fritter with the end | cut off": the cut phrase is wider than the matched words
    x = rest.strip(" ,;:.!?—–-\"“”‘(){}[]")
    g = W.letters(node["gives"])
    cands = set()
    lit = W.letters(x)
    if len(lit) == len(g) + 1:
        cands.add(lit)
    for m in re.findall(r"[A-Z][A-Za-z]+", str(node.get("note") or "")):
        if len(m) == len(g) + 1:
            cands.add(m.upper())
    kinds = {}
    for c in cands:
        if c.upper().startswith(g.upper()):
            kinds[c.upper()] = c.upper()[len(g):]
        elif c.upper().endswith(g.upper()):
            kinds[c.upper()] = c.upper()[0]
    if len(kinds) != 1:
        return None
    whole, gone = next(iter(kinds.items()))
    xlead = len(rest) - len(rest.lstrip(" ,;:.!?—–-\"“”‘(){}[]"))
    base = node.get("at")
    xat = None if base is None else base + (ib if a == 0 else 0) + xlead
    note = str(node.get("note") or "")
    keep_note = note and not V._CUT_NOTE.search(note) and not V._LETTER_REMOVED.search(note) and not V._BRIEFLY_CUT.search(note)
    held = {"words": x, "gives": whole}
    if xat is not None:
        held["at"] = xat
    held["note"] = note if keep_note else (f"{whole} is the word '{x}' itself" if lit == whole
                                           else f"{whole} is what '{x}' stands for")
    itext = node["words"][ia:ib]
    ind_node = {"text": itext, "note": f"'{itext}' cuts a letter off"}
    if base is not None:
        ind_node["at"] = base + ia
    new = {"op": "deletion", "indicators": [ind_node], "parts": [held, {"gives": gone}]}
    if _eval_swapped(node, parent, new, ctx):
        return new
    return None


def r_link_in_leaf(node, parent, ctx):
    """linkInLeaf (r25): a leaf opening or closing with a link word (in, of, with, by ...) whose other
    words alone give its letters ([in Southwest]SW): the leaf keeps the other words. Kept only when
    the tree still gives the answer and no detector fires that did not."""
    if not leaf(node) or not node.get("words") or not V.link_in_leaf(node):
        return None
    ws = node["words"].split()
    g = W.letters(node["gives"])
    for lead, rest, link in ((True, ws[1:], ws[0]), (False, ws[:-1], ws[-1])):
        if W.letters(link).lower() in V._LEAF_LINKS and not (lead and link.lower() == "to") \
                and V._known_pair(" ".join(rest), g):
            new = dict(node)
            new["words"] = " ".join(rest)
            if lead and isinstance(node.get("at"), int):
                new["at"] = node["at"] + len(ws[0]) + 1
            if _eval_swapped(node, parent, new, ctx):
                return new
    return None


def r_ind_leaf_overlap(node, parent, ctx):
    """indLeafOverlap (r25): a two-word indicator whose word is also a whole leaf's words ("is beaten"
    with a leaf "is"): the indicator keeps its other word. Kept only when the tree still gives the answer
    and no detector fires that did not."""
    inds = node.get("indicators") or []
    leafwords = {W.letters(n["words"]) for n, _ in walk(ctx["tree"]) if leaf(n) and n.get("words") and " " not in n["words"].strip()}
    for k, ind in enumerate(inds):
        ws = str(ind.get("text") or "").split()
        if len(ws) != 2:
            continue
        for keep, drop in ((1, 0), (0, 1)):
            if W.letters(ws[drop]) in leafwords and W.letters(ws[keep]) not in leafwords:
                new = copy.deepcopy(node)
                new["indicators"][k]["text"] = ws[keep]
                if isinstance(ind.get("at"), int):
                    new["indicators"][k]["at"] = ind["at"] + (len(ws[0]) + 1 if keep == 1 else 0)
                if _eval_swapped(node, parent, new, ctx):
                    return new
    return None


HALF = re.compile(r"\bhalf\b|\bhalved\b|\bmostly\b|\bsemi|\bdemi", re.I)


def r_half_cut(node, parent, ctx):
    """half_cut: a deletion that takes exactly half of a word, under an indicator that means half
    ("not half", "half", "mostly"): SIR + del<not half>(DARING, ING) is the first half of DARING.
    The deletion becomes first/last over the leaf, the same indicator kept (Paul, round 15)."""
    parts = node.get("parts") or []
    inds = node.get("indicators") or []
    if node.get("op") != "deletion" or len(parts) != 2 or len(inds) != 1 or not HALF.search(inds[0].get("text") or ""):
        return None
    whole, gone = parts
    if not leaf(whole) or not whole.get("gives") or "op" in gone or not gone.get("gives") or gone.get("words"):
        return None
    full, cut = W.letters(whole["gives"]), W.letters(gone["gives"])
    if len(full) % 2 or len(cut) != len(full) // 2:
        return None
    op = "first" if full.endswith(cut) else "last" if full.startswith(cut) else None
    if op is None:
        return None
    new = {"op": op, "indicators": copy.deepcopy(inds), "parts": [copy.deepcopy(whole)]}
    return new if (full[:len(cut)] if op == "first" else full[len(cut):]) in (vals(new) or ()) else None


#: Repairs for validator rules (the queue's anaSynonym / anagramOfContainer rows), run by --rule.
def r_arity_ins(node, parent, ctx):
    """arity_ins: an unchecked container that holds one charade (or one anagram / reversal /
    cycling / deletion) of several parts, or 3+ parts. The parts are the held and the holder
    run together: split them into a contiguous run (inner) and the rest (outer), the unary op
    (if any) wrapping one group. Kept only when the whole tree gives the answer and exactly one
    reading does; a charade's own indicators move to the container (one op per indicator)."""
    if node.get("op") != "container" or not node.get("unchecked") or len(node.get("parts") or []) == 2:
        return None
    parts = node["parts"]
    if len(parts) > 1 and len(parts) >= 3:
        unary = None
        items = parts
    elif len(parts) == 1 and parts[0].get("op") and not parts[0].get("unchecked") \
            and (parts[0]["op"] == "charade" or parts[0]["op"] in ("anagram", "reversal", "cycling", "deletion")):
        unary = None if parts[0]["op"] == "charade" else parts[0]
        items = parts[0]["parts"]
    else:
        return None
    if len(items) < 2 or any(x.get("unchecked") for it in items for x, _ in walk(it)):
        return None     # an unchecked piece has no letters: the answer cannot vouch for where it sits
    base = {k: v for k, v in node.items() if k not in ("unchecked", "gives", "parts")}
    if len(parts) == 1 and unary is None and parts[0].get("indicators"):
        base["indicators"] = (base.get("indicators") or []) + copy.deepcopy(parts[0]["indicators"])
    good = {}

    def group(sub, wrap):
        if wrap:
            return {**copy.deepcopy(unary), "parts": copy.deepcopy(sub)}
        return charade(copy.deepcopy(sub))
    n = len(items)
    for i in range(n):
        for j in range(i, n):
            inner_i, outer_i = items[i:j + 1], items[:i] + items[j + 1:]
            if not outer_i:
                continue
            for wrap in ((None,) if unary is None else ("inner", "outer")):
                inner = group(inner_i, wrap == "inner")
                outer = group(outer_i, wrap == "outer")
                new = {**base, "parts": [outer, inner]}
                if _eval_swapped(node, parent, new, ctx):
                    good[json.dumps(new, sort_keys=True)] = new
    return next(iter(good.values())) if len(good) == 1 else None


def r_removed_leaf(node, parent, ctx):
    """unchecked_leaf: a one-part deletion over a charade holding a letterless unchecked leaf
    (DEPORTMENT: del(charade(DEPORT, MEN, T?)) with "billions" never given letters). The leaf is
    the removed part, not a charade piece: it leaves the charade and becomes the deletion's second
    part, its `gives` the letters the rest of the charade has beyond the target (the deletion's own
    `gives`, or the answer at the root). Kept only when those letters are one string and the whole
    tree gives the answer."""
    if node.get("op") != "deletion" or len(node.get("parts") or []) != 1:
        return None
    inner = node["parts"][0]
    if inner.get("op") != "charade" or inner.get("unchecked") or "gives" in inner:
        return None
    gone = [p for p in inner.get("parts") or []
            if leaf(p) and p.get("unchecked") and p.get("words") and not W.letters(p.get("gives"))]
    if len(gone) != 1:
        return None
    lf = gone[0]
    want = W.letters(node.get("gives")) or (W.letters(ctx.get("answer")) if parent is None else "")
    rest = charade([copy.deepcopy(p) for p in inner["parts"] if p is not lf])
    vs = vals(rest)
    if not want or not vs or len(vs) != 1:
        return None
    v = next(iter(vs))
    m = len(v) - len(want)
    if m == 0 and v == want:
        return _letters_back(node, parent, ctx, inner, lf)
    if not 1 <= m <= 4:
        return None
    cuts = {v[j:j + m] for j in range(len(v) - m + 1) if v[:j] + v[j + m:] == want}
    if len(cuts) != 1:
        return None
    new_leaf = {k: x for k, x in lf.items() if k != "unchecked"}
    new_leaf["gives"] = cuts.pop()
    return checked(node, parts=[rest, new_leaf])


_ABBR = {}


def _abbreviations(words):
    """The letters the abbreviation tables read `words` as (king K, billions B, unknown X/Y/Z)."""
    if not _ABBR:
        pairs, _ = V._attested()
        for k, g in pairs | set(V._EXTRA_PAIRS):
            _ABBR.setdefault(k, set()).add(g)
    key = re.sub(r"[^A-Z]", "", str(words).upper())
    # a one-letter word ("I", "A") stands for itself
    return _ABBR.get(key, set()) | ({key} if len(key) == 1 else set())


def _letters_back(node, parent, ctx, inner, lf):
    """The removed leaf's letters were never filed because the charade's leaf already shows the word
    cut (Rant -> TRADE, with I removed from TIRADE): put the abbreviation's letters back into one
    other leaf of the charade, where the result is a word of the lexicon, and let the deletion take
    them out again. Kept only when exactly one leaf, place and reading does it."""
    lex = V._lexicon_letters()
    if not lex:
        return None
    found = {}
    for q, _ in walk(inner):
        if not leaf(q) or q is lf or not q.get("words") or not W.letters(q.get("gives")) or q.get("unchecked"):
            continue
        g = W.letters(q["gives"])
        for x in _abbreviations(lf["words"]):
            for i in range(len(g) + 1):
                cand = g[:i] + x + g[i:]
                if cand == g or cand.lower() not in lex or len(cand) < 4:
                    continue
                new_inner = copy.deepcopy(inner)
                for nq, _ in walk(new_inner):
                    if leaf(nq) and nq == q:
                        nq["gives"] = cand
                        nq["note"] = f"{nq['words']} gives {cand}, before the {x} goes"
                        break
                ps = [p for p in new_inner["parts"] if not (leaf(p) and p == lf)]
                rest = charade(ps) if len(ps) != 1 else ps[0]
                new_leaf = {k: v for k, v in lf.items() if k != "unchecked"}
                new_leaf["gives"] = x
                new = checked(node, parts=[rest, new_leaf])
                if _eval_swapped(node, parent, new, ctx):
                    found[json.dumps(new, sort_keys=True)] = (new, cand)
    if len(found) > 1:
        # several lexicon words fit (TIRADE, TRADIE): the one the annotation's own notes name
        text = json.dumps(ctx["tree"]).lower()
        named = {k: v for k, v in found.items() if re.search(r"\b%s\b" % v[1].lower(), text)}
        found = named
    return next(iter(found.values()))[0] if len(found) == 1 else None


def r_literal_fodder(node, parent, ctx):
    """unchecked_step: an anagram filed with its fodder's results (ana([Verdun + CU]) with `gives`
    on its leaves, the letters already in answer order) so the evaluator calls it "already the
    answer" and the step stays unchecked. The fodder is the clue words themselves: the leaves under
    an anagram lose their filed `gives`, every flag goes, and the evaluator scrambles the real
    words. Kept only when the whole tree then gives the answer."""
    if parent is not None or not ctx.get("answer") or not unchecked(node):
        return None
    if not any(n.get("op") == "anagram" and n.get("unchecked") for n, _ in walk(node)):
        return None
    new = copy.deepcopy(node)
    for n, _ in walk(new):
        for key in ("unchecked", "select", "soundsLike"):   # fields the schema allows on unchecked leaves only
            n.pop(key, None)
        if "op" in n:
            n.pop("gives", None)
        if n.get("op") == "anagram":
            for q, _ in walk(n):
                if leaf(q) and q.get("words"):
                    q.pop("gives", None)
    return new if _eval_swapped(node, None, new, ctx) else None


_HALF = re.compile(r"\bhalf\b|\bhalves\b|50\s*%|\bhalf-", re.I)


def r_half_leaf(node, parent, ctx):
    """halfLeaf: a leaf giving half of its one word (STR from street) with the clue's "half" word
    sitting on some other op (the del<half>(..) that was never a deletion of anything, the ins's
    second word, a charade's trailing "half-cut"). The word moves onto a first/last op over that
    leaf, which is what picks the half; a one-part deletion left with nothing else goes. Done on
    the whole tree, for the one half leaf and the one half word only; kept when the tree still
    gives the answer and the rule no longer fires."""
    if parent is not None or not ctx.get("answer"):
        return None
    seen = []
    stack = [(node, ())]
    while stack:
        n, anc = stack.pop()
        stack += [(p, anc + (n,)) for p in n.get("parts") or []]
        if leaf(n) and n.get("words") and n.get("gives") and not n.get("select") and not n.get("unchecked"):
            seen.append((n, anc))
    halves = []
    for lf, anc in seen:
        w, g = W.letters(lf["words"]), W.letters(lf["gives"])
        if len(lf["words"].split()) == 1 and len(w) >= 4 and len(g) * 2 == len(w) and (w.startswith(g) != w.endswith(g)) \
                and not any(a.get("op") in W.SELECT or a.get("op") == "hidden" for a in anc) \
                and not V._known_pair(lf["words"], g):
            halves.append((lf, anc, "first" if w.startswith(g) else "last"))
    owners = [(n, i) for n, _ in walk(node) for i in n.get("indicators") or [] if _HALF.search(i.get("text") or "")]
    if len(halves) != 1 or len(owners) != 1 or not V.half_leaves(node):
        return None
    lf, anc, op = halves[0]
    holder, ind = owners[0]
    if not anc:
        return None
    new = copy.deepcopy(node)
    # find the same nodes in the copy by their path from the root
    def path(root, target):
        if root is target:
            return []
        for k, p in enumerate(root.get("parts") or []):
            r = path(p, target)
            if r is not None:
                return [k] + r
        return None

    def at(root, pth):
        for k in pth:
            root = root["parts"][k]
        return root
    lf_new, holder_new = at(new, path(node, lf)), at(new, path(node, holder))
    ind_new = next(i for i in holder_new["indicators"] if i.get("text") == ind.get("text"))
    holder_new["indicators"] = [i for i in holder_new["indicators"] if i is not ind_new]
    pick = {"op": op, "indicators": [{**ind_new, "note": f"keeps the {op} half of the word"}],
            "parts": [{k: v for k, v in lf_new.items() if k != "gives"}]}
    pth = path(node, lf)
    if pth:
        at(new, pth[:-1])["parts"][pth[-1]] = pick
    if not holder_new["indicators"]:
        holder_new.pop("indicators")
        if holder_new.get("op") == "deletion" and len(holder_new.get("parts") or []) == 1:
            hp = path(new, holder_new)
            sole = holder_new["parts"][0]
            if hp:
                at(new, hp[:-1])["parts"][hp[-1]] = sole
            else:
                new = sole
        elif holder_new.get("op") in V.NEEDS_INDICATOR:
            return None
    try:
        W.evaluate(copy.deepcopy(new), ctx["answer"])
    except (W.WordplayError, IndexError, KeyError, TypeError, ValueError, W._NeedTarget):
        return None
    return new if not V.half_leaves(new) else None


def _runs(n, k):
    """Every way to cut range(n) into k contiguous non-empty runs, as lists of (lo, hi)."""
    if k == 1:
        yield [(0, n)]
        return
    for c in range(1, n - k + 2):
        for rest in _runs(n - c, k - 1):
            yield [(0, c)] + [(a + c, b + c) for a, b in rest]


def _arity_cands(node):
    """Rewrites of an unchecked unary op or substitution that holds too many parts: each a list
    of charade pieces, the op acting on one run of the parts (or three runs, for a substitution)."""
    op, parts = node.get("op"), node.get("parts") or []
    if not node.get("unchecked") or len(parts) < 2 or any(x.get("unchecked") for p in parts for x, _ in walk(p)):
        return
    base = {k: v for k, v in node.items() if k not in ("unchecked", "gives", "parts")}

    def group(run):
        return copy.deepcopy(run[0]) if len(run) == 1 else charade(copy.deepcopy(run))
    n = len(parts)
    if op in UNARY:
        for i in range(n):
            for j in range(i, n):
                yield copy.deepcopy(parts[:i]) + [{**base, "parts": [group(parts[i:j + 1])]}] + copy.deepcopy(parts[j + 1:])
    elif op == "substitution" and n >= 4:
        for a in range(n - 2):
            for b in range(a + 3, n + 1):
                for cuts in _runs(b - a, 3):
                    runs = [parts[a + lo:a + hi] for lo, hi in cuts]
                    for order in itertools.permutations(range(3)):
                        sub = {**base, "parts": [group(runs[o]) for o in order]}
                        yield copy.deepcopy(parts[:a]) + [sub] + copy.deepcopy(parts[b:])


def r_arity_other(node, parent, ctx):
    """arity_other: an unchecked unary op (reversal, cycling, hidden, a letter pick) or a
    substitution filed with more parts than it takes. The op acts on one run of its parts and
    the rest are charade pieces beside it (rev(A, LIFE) -> A + rev(LIFE); a 4-part sub -> the
    three it takes, in whichever order, with the leftover parts before or after). A container
    holding one such op (ins(cyc(CALYPSO, APE))) splits the pieces into outer and inner as well.
    Kept only when the whole tree gives the answer and exactly one reading does."""
    good = {}
    if node.get("op") == "container" and node.get("unchecked") and len(node.get("parts") or []) == 1:
        base = {k: v for k, v in node.items() if k not in ("unchecked", "gives", "parts")}
        for items in _arity_cands(node["parts"][0]):
            for i in range(len(items)):
                for j in range(i, len(items)):
                    outer = items[:i] + items[j + 1:]
                    if not outer:
                        continue
                    new = {**base, "parts": [charade(copy.deepcopy(outer)), charade(copy.deepcopy(items[i:j + 1]))]}
                    if _eval_swapped(node, parent, new, ctx):
                        good[json.dumps(new, sort_keys=True)] = new
    else:
        for items in _arity_cands(node):
            new = charade(items)
            if _eval_swapped(node, parent, new, ctx):
                good[json.dumps(new, sort_keys=True)] = new
    return next(iter(good.values())) if len(good) == 1 else None


_STOP = frozenset("a an and as at by for from in into is of on or the to with".split())


def _edge_trim(a, b, clue):
    """For two overlapping clue spans a=(s, e), b=(s, e): (which, (s, e)) when the one that may give
    way can be cut back to whole words at its own edge, else None. `which` is 0 or 1."""
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    outer, inner = (a, b) if a[0] <= b[0] and b[1] <= a[1] else (b, a) if b[0] <= a[0] and a[1] <= b[1] else (None, None)
    word = lambda s, e: (s == 0 or not clue[s - 1].isalnum()) and (e >= len(clue) or not clue[e].isalnum())
    if outer is not None:
        if inner[0] > outer[0] and inner[1] < outer[1]:
            return None
        s, e = (inner[1], outer[1]) if inner[0] == outer[0] else (outer[0], inner[0])
        text = clue[s:e]
        s += len(text) - len(text.lstrip(" ,;"))
        e -= len(text) - len(text.rstrip(" ,;"))
        return (0 if outer is a else 1, (s, e)) if s < e and word(s, e) and word(*inner) else None
    return None


def _move_inner_indicator(a, b, sa, sb, clue, items):
    """An indicator printed inside a leaf's words that the clue prints again outside every claimed
    span ("in#2" in hid<in>([competition in Japan]) of "expert in competition in Japan"): move it to
    the one free occurrence. True when moved."""
    ind, lf = (a, b) if a[0] == "indicator" else (b, a)
    si, sl = (sa, sb) if ind is a else (sb, sa)
    if not (sl[0] <= si[0] and si[1] <= sl[1]):
        return False
    taken = [(x[1]["at"], x[1]["at"] + len(x[2])) for x in items if x is not ind]
    free = [m.start() for m in re.finditer(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(ind[2]), clue, re.I)
            if not any(m.start() < t[1] and t[0] < m.end() for t in taken)]
    if len(free) != 1:
        return False
    ind[1]["at"] = free[0]
    return True


def r_span_overlap(node, parent, ctx):
    """spanOverlap: an indicator and a leaf claim the same clue words. Only the unambiguous cuts: a
    leaf lying at the edge of an indicator (the indicator "is captivated by" over the leaf "is" gives
    "captivated by" back its own words; leaf and indicator are both kept), or an indicator lying at
    the edge of a leaf that has a `gives` (the leaf keeps its letters, loses the indicator's words).
    Whole words only, nothing left empty, the tree still gives the answer. Run once, at the root."""
    clue, answer = ctx["clue"], ctx.get("answer")
    if parent is not None or not answer:
        return None
    new = copy.deepcopy(node)
    try:
        before = V.span_overlaps(W.locate(copy.deepcopy(new), clue))
    except W.WordplayError:
        return None
    if not before:
        return None
    done = 0
    for _ in range(6):
        items = []
        for n, _p in walk(new):
            if n.get("op") == "cryptic":
                continue
            items += [("indicator", i, i.get("text"), n) for i in n.get("indicators") or [] if isinstance(i.get("at"), int)]
            if leaf(n) and n.get("words") and isinstance(n.get("at"), int):
                items.append(("leaf", n, n["words"], n))
        step = False
        for x, a in enumerate(items):
            for b in items[x + 1:]:
                sa, sb = (a[1]["at"], a[1]["at"] + len(a[2])), (b[1]["at"], b[1]["at"] + len(b[2]))
                if not (sa[0] < sb[1] and sb[0] < sa[1]) or sa == sb:
                    continue
                got = _edge_trim(sa, sb, clue)
                if not got:
                    if a[0] != b[0]:
                        step = _move_inner_indicator(a, b, sa, sb, clue, items)
                    if step:
                        break
                    continue
                which, (s, e) = got
                outer = (a, b)[which]
                key = "text" if outer[0] == "indicator" else "words"
                if a[0] == b[0] == "leaf":
                    # two leaves: the outer one gives way at its edge, only when it carries its letters
                    # (`gives`) and the pieces still stand in the tree's order (TENORDRUM: "a few pound"
                    # over "pound" would put XX before LB)
                    inner = (b, a)[which]
                    if "gives" not in outer[1] or (which == 0) != (s < inner[1]["at"]):
                        continue
                elif outer[0] == "leaf" and "gives" not in outer[1]:
                    continue
                outer[1][key], outer[1]["at"] = clue[s:e], s
                step = True
                break
            if step:
                break
        if not step:
            break
        done += 1
    if not done:
        return None
    try:
        if V.span_overlaps(W.locate(copy.deepcopy(new), clue)) >= before:
            return None
        W.evaluate(copy.deepcopy(new), answer)
    except (W.WordplayError, IndexError, KeyError, TypeError, ValueError, W._NeedTarget):
        return None
    return new
