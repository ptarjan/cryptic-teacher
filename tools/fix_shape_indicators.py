"""Indicator repairs of fix_shape_suspects.py: a role (which op an indicator belongs to), a shared or
misplaced indicator, an unindicated move or spare, and the hidden-word links. Each r_* takes
(node, parent, ctx) and returns a replacement node or None.
"""
import collections
import copy
import json
import re

import annotation
import validate_annotations as V
import wordplay as W
from fix_shape_base import (
    TAIL, HEAD, walk, leaf, vals, gives_ok, checked, charade, clue_text, _eval_swapped, _diff_gone,
    _flat_leaves,
)


def _role_owner(ind):
    """The op type the corpus files an indicator's words under (at least ROLE_MIN_USES uses, and
    ROLE_SWAP_OWNED of them one type), else None."""
    counts = V._role_counts(V.indicator_role_key(ind.get("text")))
    total = sum(counts.values())
    if total < V.ROLE_MIN_USES:
        return None
    top = max(counts, key=counts.get)
    return top if counts[top] >= V.ROLE_SWAP_OWNED * total else None


def r_role_swap(node, parent, ctx):
    """Indicators filed on the wrong one of two nested ops. The ops swap them when each carries
    a word the corpus files under the other's type (ins<returned>(rev<opened by>(..), ..) is
    ins<opened by>(rev<returned>(..), ..)); an op with no indicator of its own takes the word
    its parent carries for its type (ana<ignoring>(del(..)) is ana(del<ignoring>(..)), a first
    op under ins<head>). Words move whole; the letters are untouched."""
    kind = V._OP_LEXICON.get(node.get("op"))
    if not kind or not parent or node.get("unchecked") or parent.get("unchecked") \
            or id(node) in ctx["under_unchecked"]:
        return None
    pkind = V._OP_LEXICON.get(parent.get("op"))
    if parent.get("op") != "charade" and not pkind:
        return None
    mine, theirs = node.get("indicators") or [], parent.get("indicators") or []
    if pkind and pkind != kind and not V._swap_alike(pkind, kind):
        for a in mine:
            if _role_owner(a) != pkind:
                continue
            for b in theirs:
                if V._swap_alike(_role_owner(b), kind):
                    mine[mine.index(a)], theirs[theirs.index(b)] = b, a
                    return node
    if not mine and kind != pkind:
        for b in theirs:
            if _role_owner(b) == kind:
                theirs.remove(b)
                node["indicators"] = [b]
                if not theirs:
                    parent.pop("indicators", None)
                return node
    return _swap_unknown(node, parent, ctx)


def _gated(ctx, nodes, mutate):
    """Run `mutate` (it edits the indicators of `nodes` in place); keep it only when the validator
    then counts fewer wrong-role indicators in the whole tree, else put the indicators back."""
    before = V.wrong_role_indicators(ctx["tree"])
    saved = [(n, list(n["indicators"]) if "indicators" in n else None) for n in nodes]
    mutate()
    if V.wrong_role_indicators(ctx["tree"]) < before:
        return True
    for n, ind in saved:
        if ind is None:
            n.pop("indicators", None)
        else:
            n["indicators"] = ind
    return False


def _swap_unknown(node, parent, ctx):
    """A child op holding its parent's word while the parent holds a word the corpus has no
    owner for (ana<crossing> inside ins<frenziedly>): the two trade places when that clears the
    flag. A parent word the corpus files under the child's type counts as a match too."""
    kind, pkind = V._OP_LEXICON.get(node.get("op")), V._OP_LEXICON.get(parent.get("op"))
    if not kind or not pkind or kind == pkind:
        return None
    mine, theirs = node.get("indicators") or [], parent.get("indicators") or []
    for a in mine:
        if _role_owner(a) != pkind:
            continue
        for b in theirs:
            if _role_owner(b) not in (None, kind) or _role_owner(b) == pkind:
                continue

            def swap():
                mine[mine.index(a)], theirs[theirs.index(b)] = b, a
            if _gated(ctx, [node, parent], swap):
                return node
    return None


def r_role_move(node, parent, ctx):
    """Indicators filed on ops of another type than the corpus files them under, redealt: each
    word goes to the one checked op of its own type that has no indicator of its own (or only
    misfiled ones), when every misfiled word finds exactly one such op and the whole tree then
    counts fewer wrong-role indicators. Covers a word moved down from an enclosing charade
    (charade<mistakenly>(BUSH, ana<ignoring>(del(..))) is charade(BUSH, ana<mistakenly>(
    del<ignoring>(..)))), a word moved to a sibling, and a three-way rotation. Run once, at the root."""
    if parent is not None:
        return None
    ops = [x for x, _ in walk(node) if (V._OP_LEXICON.get(x.get("op")) or x.get("op") == "charade")
           and not x.get("unchecked") and id(x) not in ctx["under_unchecked"]]
    misfiled = {}   # id(op) -> [(indicator, owner)]
    for x in ops:
        kind = V._OP_LEXICON.get(x.get("op"))
        for b in x.get("indicators") or []:
            owner = _role_owner(b)
            if owner and owner != kind and not (kind and V._swap_alike(owner, kind)):
                misfiled.setdefault(id(x), []).append((b, owner))
    if not misfiled:
        return None
    needy = collections.defaultdict(list)
    for x in ops:
        kind = V._OP_LEXICON.get(x.get("op"))
        if kind and len(x.get("indicators") or []) == len(misfiled.get(id(x), [])):
            needy[kind].append(x)
    moves = collections.defaultdict(list)   # owner -> [(holder, indicator)]
    for x in ops:
        for b, owner in misfiled.get(id(x), []):
            moves[owner].append((x, b))
    plan = []
    for owner, ms in moves.items():
        if len(ms) != 1 or len(needy[owner]) != 1:
            return None
        plan.append((ms[0][0], ms[0][1], needy[owner][0]))
    touched = {id(x): x for h, _, t in plan for x in (h, t)}
    inds = {id(x): [i for i in x.get("indicators") or [] if all(i is not b for h, b, _ in plan if h is x)]
            for x in touched.values()}

    def deal():
        for h, b, t in plan:
            inds[id(t)].append(b)
        for k, x in touched.items():
            if inds[k]:
                x["indicators"] = inds[k]
            else:
                x.pop("indicators", None)
    return node if _gated(ctx, list(touched.values()), deal) else None


def _owns(ind, kind, host):
    """Whether the corpus files an indicator's words mostly (V.ROLE_LOOSE_OWNED) under `kind`,
    and hardly ever (V.ROLE_LOOSE_OWN_MAX) under the type of the op `host` that carries it."""
    counts = V._role_counts(V.indicator_role_key(ind.get("text")))
    total = sum(counts.values())
    return total >= V.ROLE_MIN_USES and counts.get(kind, 0) >= V.ROLE_LOOSE_OWNED * total \
        and counts.get(host, 0) <= V.ROLE_LOOSE_OWN_MAX * total


def _unknown_word(ind):
    return sum(V._role_counts(V.indicator_role_key(ind.get("text"))).values()) < V.ROLE_MIN_USES


def r_ind_trade(node, parent, ctx):
    """Two checked ops anywhere in the tree (nested or siblings) that each carry the word the
    corpus files under the other's type -- rev<first to>(..) beside first<back>(..), ins<mad>(
    ana<about>(..)) -- trade those words; also an op whose word the corpus has never seen
    trading with a word the corpus files under its own type (ins<Awfully>(ana<to have pocketed>
    (..))). Run once, from the root; kept only when the whole tree then counts fewer
    wrong-role indicators. Words move whole; the letters are untouched."""
    if parent is not None:
        return None
    ops = [n for n, _ in walk(node) if V._OP_LEXICON.get(n.get("op")) and not n.get("unchecked")
           and id(n) not in ctx["under_unchecked"] and n.get("indicators")]
    for x in ops:
        kx = V._OP_LEXICON[x["op"]]
        for y in ops:
            ky = V._OP_LEXICON[y["op"]]
            if x is y or kx == ky or V._swap_alike(kx, ky) or V._swap_alike(ky, kx):
                continue
            for a in x["indicators"]:
                for b in y["indicators"]:
                    if not (_owns(b, kx, ky) and (_owns(a, ky, kx) or _unknown_word(a))):
                        continue

                    def swap(a=a, b=b):
                        x["indicators"][x["indicators"].index(a)], y["indicators"][y["indicators"].index(b)] = b, a
                    if _gated(ctx, [x, y], swap):
                        return node
    return None


def r_shared_indicator(node, parent, ctx):
    """sharedIndicator, deletion: the indicator's own words are filed again as a leaf giving the
    result (del<not opened>((PROOF + [not opened]ROOF), PROOF)). That leaf goes; the deletion is
    the source minus the one run whose removal leaves the result (an end/head/middle indicator
    word says where the run sits)."""
    if node.get("op") != "deletion" or len(node.get("indicators") or []) != 1:
        return None
    ind = node["indicators"][0]
    t = W.letters(ind.get("text"))
    if not t:
        return None
    flat = _flat_leaves(node.get("parts") or [])
    dup = [p for p in flat if leaf(p) and p.get("words") and W.letters(p["words"]) == t]
    if len(dup) != 1 or not W.letters(dup[0].get("gives")):
        return None
    k = flat.index(dup[0])
    want = W.letters(dup[0]["gives"])
    gone_leaves = [p for p in flat if leaf(p) and not p.get("words")]    # the filed removal, restated below
    pool = [p for p in flat if p is not dup[0] and p not in gone_leaves]
    nb = [p for p in (flat[k - 1:k] if k else []) + flat[k + 1:k + 2] if p in pool]
    if not nb:
        return None
    src = nb[0]       # the part next to the restated result
    sv = vals(src)
    if not sv or len(sv) != 1:
        return None
    gone = _diff_gone(next(iter(sv)), want, ind.get("text"))
    if gone is None:
        return None
    cut = checked(node, parts=[copy.deepcopy(src), {"gives": gone}])
    if not gives_ok(cut, want):
        return None
    around = [copy.deepcopy(p) if p is not src else cut for p in pool]
    if len(pool) == 1:
        return cut
    new = charade(around)
    return new if node.get("gives") is None or gives_ok(new, W.letters(node["gives"])) else None


def _top_role(ind, kind):
    """Whether the corpus files the indicator's words under `kind` more than any other op type."""
    counts = V._role_counts(V.indicator_role_key(ind.get("text")))
    return sum(counts.values()) >= V.ROLE_MIN_USES and max(counts, key=counts.get) == kind


def _anagram_only(ind):
    """Whether the corpus files the indicator's words as an anagram word and (almost) never as a
    container one: wandering yes (153 to 1), split no (15 to 13)."""
    counts = V._role_counts(V.indicator_role_key(ind.get("text")))
    return _top_role(ind, "anagram") and counts.get("anagram", 0) >= 8 * (counts.get("container", 0) + counts.get("insertion", 0))


def _mine_for_op(ind, op):
    """Whether the corpus files indicator `ind` under the type of op node `op` (first/last picks also by
    their own head or tail words)."""
    kind = V._OP_LEXICON.get(op.get("op"))
    text = ind.get("text") or ""
    if not kind or _role_owner(ind) != kind:
        return False
    if op["op"] == "first":
        return bool(HEAD.search(text)) and not TAIL.search(text)
    if op["op"] == "last":
        return bool(TAIL.search(text)) and not HEAD.search(text)
    return True


#: With False, r_unindicated_move reads fits as it first did (corpus-owned words only, one holder word per op).
UNINDICATED_WIDE = True


def _lexicon_owns(ind, op):
    """Whether the indicator lexicon (tools/data/lexicons/indicators.json) lists the indicator's words for
    the type of op node `op` (at least 3 uses, three times as many as under any other type)."""
    kind = V._OP_LEXICON.get(op.get("op"))
    lex = V._indicator_lexicon()
    key = V.indicator_role_key(ind.get("text"))
    mine = (lex.get(kind) or {}).get(key, 0)
    if not kind or mine < 3 or any(mine < 3 * (t.get(key) or 0) for k, t in lex.items() if k != kind):
        return False
    text = ind.get("text") or ""
    if op["op"] == "first":
        return bool(HEAD.search(text)) and not TAIL.search(text)
    if op["op"] == "last":
        return bool(TAIL.search(text)) and not HEAD.search(text)
    return True


def _unindicated_fits(node, op, wide):
    """The (holder, indicator) pairs whose indicator could belong to bare op `op`: filed on a charade, on
    an op of another type, or beside a second indicator of one op."""
    fits, held = [], False
    for h, _ in walk(node):
        if h is op or h.get("unchecked"):
            continue
        hk = V._OP_LEXICON.get(h.get("op"))
        for i in h.get("indicators") or []:
            owned = _role_owner(i) == hk or (wide and hk and _lexicon_owns(i, h))
            if not (h.get("op") == "charade" or (hk and not owned) or len(h["indicators"]) > 1):
                continue
            held = True
            if _mine_for_op(i, op) or (wide and _lexicon_owns(i, op)):
                fits.append((h, i))
    return fits, held


def _owner_any(ind):
    """The op type the corpus or the indicator lexicon files an indicator's words under, else None."""
    own = _role_owner(ind)
    if own:
        return own
    lex = V._indicator_lexicon()
    key = V.indicator_role_key(ind.get("text"))
    top = max(lex, key=lambda k: (lex[k].get(key) or 0) if k in V._OP_LEXICON.values() else -1, default=None)
    n = (lex.get(top) or {}).get(key, 0)
    rest = max([(t.get(key) or 0) for k, t in lex.items() if k != top] or [0])
    return top if n >= 3 and n >= 3 * rest else None


def _op_spans(op):
    return [(x["at"], x["at"] + len(x["words"])) for x, _ in walk(op) if leaf(x) and x.get("words")
            and isinstance(x.get("at"), int)]


def _unindicated_swap(node, ctx, base, role, count=None):
    """A charade's indicator owned by the type of op X, where X carries only a word nothing files under any
    type, and a bare op B stands right beside that word: the charade's word goes to X, X's word to B
    (charade<at the outset>(first<hosted>(g), ins(long, uncle's)) -> first<at the outset>, ins<hosted>).
    Only one X and one B; the validator must then count fewer bare ops."""
    clue = ctx["clue"]
    bare = [op for op, _ in walk(node)
            if not (op.get("unchecked") or id(op) in ctx["under_unchecked"] or op.get("indicators")
                    or op.get("op") not in V.NEEDS_INDICATOR or not V._OP_LEXICON.get(op.get("op")))]
    if not bare:
        return None
    for h, _ in walk(node):
        if h.get("op") != "charade":
            continue
        for i in list(h.get("indicators") or []):
            xs = [x for x, _ in walk(node) if x is not h and not x.get("unchecked") and x.get("indicators")
                  and V._OP_LEXICON.get(x.get("op")) and (_mine_for_op(i, x) or _lexicon_owns(i, x))
                  and all(not _owner_any(j) for j in x["indicators"]) and len(x["indicators"]) == 1]
            if len(xs) != 1:
                continue
            x = xs[0]
            j = x["indicators"][0]
            if not isinstance(j.get("at"), int):
                continue
            beside = [b for b in bare if b is not x and any(
                (not clue[e:j["at"]].strip(" ,;") and e <= j["at"]) or
                (not clue[j["at"] + len(j["text"]):s].strip(" ,;") and s >= j["at"] + len(j["text"]))
                for s, e in _op_spans(b))]
            if len(beside) != 1:
                continue
            b = beside[0]
            h["indicators"].remove(i)
            if not h["indicators"]:
                h.pop("indicators")
            x["indicators"], b["indicators"] = [i], [j]
            if (count or V.unindicated_uncovered)(node) < base and V.wrong_role_indicators(node) <= role:
                return node
            b.pop("indicators")
            x["indicators"] = [j]
            h.setdefault("indicators", []).append(i)
    return None


def r_unindicated_move(node, parent, ctx, count=None):
    """unindicatedBare: a checked op with no indicator while a word the corpus files under its type (or
    the indicator lexicon lists for it) sits on another node that does not need it (a charade, or an op of
    a different type): the word moves to the bare op (charade<guards>(DET, ins(PLUS, C)) is
    charade(DET, ins<guards>(PLUS, C)); ins<final bit of>(CIA, last(..)) gives last<final bit of>).
    One word per bare op. A bare op takes the word only when it is the one op that word fits, or when the
    other bare ops' words, matched one-to-one, leave it that word alone (two bare ops with two misfiled
    words); and only when the validator then counts fewer bare ops and no more wrong-role indicators.
    Run once, at the root; the driver's evaluate gate does the rest. ctx["declines"], when present,
    collects (reason) per bare op left bare: no_holder (no indicator filed on a node that could spare it),
    not_this_type (such words, none fits), ambiguous (several fit, or two ops want one word), validator."""
    if parent is not None:
        return None
    base, role = (count or V.unindicated_uncovered)(node), V.wrong_role_indicators(node)
    if not base:
        return None
    log = ctx.get("declines")
    wide = UNINDICATED_WIDE
    bare = [op for op, _ in walk(node)
            if not (op.get("unchecked") or id(op) in ctx["under_unchecked"] or op.get("indicators")
                    or op.get("op") not in V.NEEDS_INDICATOR or not V._OP_LEXICON.get(op.get("op")))]
    fits = {id(op): _unindicated_fits(node, op, wide) for op in bare}
    cand = {id(op): list(f[0]) for op, f in zip(bare, fits.values())}
    taken, pick = set(), {}
    while True:
        moved = False
        for op in bare:
            if id(op) in pick:
                continue
            c = [x for x in cand[id(op)] if id(x[1]) not in taken]
            if len(c) != 1:
                continue
            # two ops each left with this one word: neither is placed
            if any(o2 is not op and id(o2) not in pick and
                   [y for y in cand[id(o2)] if id(y[1]) not in taken] == c for o2 in bare):
                continue
            pick[id(op)] = c[0]
            taken.add(id(c[0][1]))
            moved = True
        if not moved or not wide:
            break
    done = False
    for op in bare:
        if id(op) not in pick:
            if log is not None:
                f, held = fits[id(op)]
                log.append("ambiguous" if f else ("not_this_type" if held else "no_holder"))
            continue
        h, i = pick[id(op)]
        if i not in (h.get("indicators") or []):
            continue
        h["indicators"].remove(i)
        op["indicators"] = [i]
        if not h["indicators"]:
            h.pop("indicators")
        if (count or V.unindicated_uncovered)(node) < base and V.wrong_role_indicators(node) <= role:
            base, role, done = (count or V.unindicated_uncovered)(node), V.wrong_role_indicators(node), True
            continue
        op.pop("indicators")
        h.setdefault("indicators", []).append(i)
        if log is not None:
            log.append("validator")
    if not done and wide:
        return _unindicated_swap(node, ctx, base, role, count)
    return node if done else None


def _claimed(tree, clue):
    """Boolean per clue character: whether some leaf's words or indicator's text covers it."""
    cov = [False] * len(clue)
    for n, _ in walk(tree):
        spans = [(n.get("at"), n.get("words"))] if leaf(n) else []
        spans += [(i.get("at"), i.get("text")) for i in n.get("indicators") or []]
        for at, t in spans:
            if t and isinstance(at, int):
                cov[at:at + len(t)] = [True] * len(clue[at:at + len(t)])
    return cov


def r_unindicated_spare(node, parent, ctx, count=None):
    """unindicatedBare: a checked op with no indicator while one clue word, unused by any leaf or
    indicator, stands right beside its words and is a word the corpus files under its type (a
    container's "hosting", a reversal's "back"): the word becomes the op's indicator. Only one such
    word for the op and no other bare op of the same type wanting it; the validator must then count
    fewer bare ops (a word in the definition is turned away by the definition rule). Run once, at the root."""
    if parent is not None:
        return None
    clue = ctx["clue"]
    base, role = (count or V.unindicated_uncovered)(node), V.wrong_role_indicators(node)
    if not base or any(not isinstance(x.get("at"), int) for x, _ in walk(node) if leaf(x) and x.get("words")):
        return None
    cov = _claimed(node, clue)
    words = [m for m in re.finditer(r"[A-Za-z']+", clue) if not any(cov[m.start():m.end()])]
    bare = [op for op, _ in walk(node) if not op.get("unchecked") and id(op) not in ctx["under_unchecked"]
            and not op.get("indicators") and op.get("op") in V.NEEDS_INDICATOR and V._OP_LEXICON.get(op.get("op"))]
    want = {}
    for op in bare:
        ends = []
        for x, _ in walk(op):
            if leaf(x) and x.get("words"):
                ends.append((x["at"], x["at"] + len(x["words"])))
            ends += [(i["at"], i["at"] + len(i["text"])) for i in x.get("indicators") or [] if isinstance(i.get("at"), int)]
        for m in words:
            counts = V._role_counts(V.indicator_role_key(m.group()))
            total, kind = sum(counts.values()), V._OP_LEXICON[op["op"]]
            if total < 20 or counts.get(kind, 0) < 0.8 * total:
                continue
            if not any(not clue[b:m.start()].strip(" ,;") for _, b in ends if b <= m.start()) \
                    and not any(not clue[m.end():a].strip(" ,;") for a, _ in ends if a >= m.end()):
                continue
            if op["op"] in ("first", "last") and not _mine_for_op({"text": m.group()}, op):
                continue
            want.setdefault(id(op), []).append(m)
    for op in bare:
        ms = want.get(id(op)) or []
        if len(ms) != 1 or sum(ms[0] in v for v in want.values()) != 1:
            continue
        m = ms[0]
        op["indicators"] = [{"text": m.group(), "at": m.start(), "note": "the clue word that signals this step"}]
        if (count or V.unindicated_uncovered)(node) < base and V.wrong_role_indicators(node) <= role:
            return node
        op.pop("indicators")
    return None


#: Words that say "the letters sit inside what follows" and nothing else: the one an unindicated
#: hidden word borrows when it stands right before the hidden leaf ("wheels in delivery truck").
HIDDEN_LINKS = ("in", "within", "from", "of", "by", "inside", "among", "amongst", "amid", "found in",
                "seen in", "held by", "held in", "carried by", "kept by", "contained in", "contained by",
                "hiding in", "hidden in", "concealed by", "concealed in", "some of", "part of", "in part of")


def r_hidden_link(node, parent, ctx):
    """unindicatedBare, hidden: a hid() with no indicator over one leaf whose clue words are preceded
    (nothing but spaces or punctuation between) by an unused hidden-word link ("in", "from", "held
    by": HIDDEN_LINKS), usually under a reversal that has its own word (rev<held up>(hid([little ones]
    LEON)) in "Christmas will be held up by little ones"): that link becomes the hid's indicator. One
    candidate only; the validator must then count fewer bare ops. 118 first checks in 24h ended here."""
    if node.get("op") != "hidden" or node.get("unchecked") or node.get("indicators") \
            or id(node) in ctx["under_unchecked"]:
        return None
    kids = [p for p in node.get("parts") or [] if isinstance(p, dict)]
    clue = ctx["clue"]
    if len(kids) != 1 or not leaf(kids[0]) or not kids[0].get("words") or not isinstance(kids[0].get("at"), int):
        return None
    start = kids[0]["at"]
    before = clue[:start].rstrip(" ,;:-—–")
    cov = _claimed(ctx["tree"], clue)
    found = []
    for phrase in HIDDEN_LINKS:
        n = len(phrase)
        at = len(before) - n
        if at < 0 or before[at:].lower() != phrase or (at and before[at - 1].isalpha()):
            continue
        if any(cov[at:at + n]):
            continue
        found.append((at, before[at:]))
    if not found:
        return None
    at, text = min(found)           # the longest phrase that fits
    count = V.unindicated_ops(ctx["tree"])
    node["indicators"] = [{"text": text, "at": at, "note": "the clue word that says the letters sit inside the next words"}]
    if V.unindicated_ops(ctx["tree"]) < count:
        return node
    node.pop("indicators")
    return None


def r_hidden_possessive(node, parent, ctx):
    """unindicatedBare, hidden: a hid() with no indicator over one leaf whose clue words end in 's
    ("Isaac Newton's teenage trouble": ACNE, "The Bronx's river"): the 's is the setter's "has", the
    classic hidden-word signal. The leaf gives up its 's and the 's becomes the indicator, when the
    answer still comes out without those two characters and the validator counts fewer bare ops."""
    if node.get("op") != "hidden" or node.get("unchecked") or node.get("indicators") \
            or id(node) in ctx["under_unchecked"] or not ctx.get("answer"):
        return None
    kids = [p for p in node.get("parts") or [] if isinstance(p, dict)]
    if len(kids) != 1 or not leaf(kids[0]) or not isinstance(kids[0].get("at"), int):
        return None
    words = str(kids[0].get("words") or "")
    if not re.search(r"\w['\u2019]s$", words):
        return None
    count = V.unindicated_ops(ctx["tree"])
    old = dict(kids[0])
    kids[0]["words"] = words[:-2]
    node["indicators"] = [{"text": words[-2:], "at": kids[0]["at"] + len(words) - 2,
                           "note": "'s here means has: the words before it hold the hidden answer"}]
    try:
        W.evaluate(copy.deepcopy(ctx["tree"]), ctx["answer"])
        if V.unindicated_ops(ctx["tree"]) < count:
            return node
    except (W.WordplayError, IndexError, KeyError, TypeError, ValueError):
        pass
    node.pop("indicators")
    kids[0].clear()
    kids[0].update(old)
    return None


def r_swapped_pair(node, parent, ctx):
    """swappedPair (r25): a parent op and its child op of another type carry each other's indicators:
    swap them back. Kept only when the tree still gives the answer and no detector fires that did not."""
    if not V.swapped_pair({"op": node.get("op"), "indicators": node.get("indicators"), "parts": node.get("parts")}):
        return None
    for k, c in enumerate(node.get("parts") or []):
        if not isinstance(c, dict) or "op" not in c:
            continue
        new = copy.deepcopy(node)
        new["indicators"], new["parts"][k]["indicators"] = copy.deepcopy(c.get("indicators")), copy.deepcopy(node.get("indicators"))
        if V.swapped_pair(new) == 0 and _eval_swapped(node, parent, new, ctx):
            return new
    return None


def _misplaced_keys(node):
    """The indicators of charade `node` that V.misplaced_indicators flags, each tried alone."""
    out = []
    for i in node.get("indicators") or []:
        probe = {k: v for k, v in node.items() if k != "indicators"}
        probe["indicators"] = [i]
        if V.misplaced_indicators(probe):
            out.append(i)
    return out


def _lex_types(ind):
    """The lexicon types that file the indicator's words 200+ times (what op it signals)."""
    lex = V._indicator_lexicon()
    key = " ".join(w for w in (W.letters(x) for x in str(ind.get("text") or "").split()) if w)
    return {t for t, d in lex.items() if t != "charade" and d.get(key, 0) >= V.MISPLACED_MIN_USES}


def _fits_charade(ind):
    """Whether the indicator's words are fine on a charade (the lexicon, or an ordering/position word)."""
    lex = V._indicator_lexicon()
    key = " ".join(w for w in (W.letters(x) for x in str(ind.get("text") or "").split()) if w)
    return bool(lex.get("charade", {}).get(key, 0)) or key.lower() in V.ORDERING_INDICATORS \
        or key.lower() in V.POSITION_INDICATORS


def r_misplaced_indicator(node, parent, ctx):
    """misplacedIndicator: a charade carries a word the lexicon files only under another op. When
    exactly one op inside it (its own descendant) is of that type, the word moves there: onto an op
    with no indicator, or in a swap with an op whose word is fine on a charade (visa returned,
    opened by: Smoke rising over fine = rev<rising>(smoke) with 'over' left to the charade). A
    one-letter leaf of the charade that is the first/last letter of its own words is wrapped in
    the selection the word names (Tory leader = first<leader>(Tory)). Kept only when the whole
    tree still gives the answer and exactly one placement does."""
    if node.get("op") != "charade" or node.get("unchecked") or not node.get("indicators"):
        return None
    bad = _misplaced_keys(node)
    if len(bad) != 1:
        return None     # a second, sound indicator stays on the charade (rest, below)
    ind = bad[0]
    types = _lex_types(ind)
    if not types:
        return None
    rest = [i for i in node["indicators"] if i is not ind]
    base = {k: v for k, v in node.items() if k != "indicators"}
    if rest:
        base["indicators"] = rest
    good = {}

    def keep(new):
        if not V.misplaced_indicators(new) and _eval_swapped(node, parent, new, ctx):
            good[json.dumps(new, sort_keys=True)] = new
    for d, _ in list(walk(node))[1:]:
        if leaf(d) or V._OP_LEXICON.get(d.get("op")) not in types or d.get("unchecked"):
            continue
        new = copy.deepcopy(base)
        target = next(x for x, _ in walk(new) if x.get("op") == d.get("op") and x.get("parts") == d.get("parts"))
        have = d.get("indicators") or []
        if not have:
            target["indicators"] = [copy.deepcopy(ind)]
            keep(new)
        elif len(have) == 1 and _fits_charade(have[0]) and not rest:
            target["indicators"] = [copy.deepcopy(ind)]
            new["indicators"] = [copy.deepcopy(have[0])]
            keep(new)
    sel = [t for t in types if t == "letter_selection"]
    for k, lf in enumerate(node.get("parts") or []):
        if sel and leaf(lf) and lf.get("words") and lf.get("gives") and not lf.get("unchecked"):
            g, w = W.letters(lf["gives"]), W.letters(lf["words"])
            if len(g) != 1 or not w or ind.get("text") in lf["words"] or annotation.is_abbreviation(lf):
                continue    # an abbreviation (company CO, son S) is a table entry, not a pick
            for op, pick in (("first", w[0]), ("last", w[-1])):
                if g == pick:
                    new = copy.deepcopy(base)
                    inner = {x: y for x, y in lf.items() if x != "gives"}
                    new["parts"][k] = {"op": op, "indicators": [copy.deepcopy(ind)], "parts": [inner]}
                    keep(new)
    if not good and not sel and not any(
            not leaf(d) and V._OP_LEXICON.get(d.get("op")) in types for d, _ in list(walk(node))[1:]):
        return _fold_link_word(node, base, ind, parent, ctx)
    if not good:
        return None
    return next(iter(good.values())) if len(good) == 1 else None


def _fold_link_word(node, base, ind, parent, ctx):
    """misplacedIndicator, link word: no op inside the charade is of the type the word signals
    (CO + ana<various>(menus) carrying 'introducing'), so it is a plain link word between pieces.
    A charade needs no indicator, and the validator wants every clue word in a leaf, an indicator
    or the definition: the word joins the one synonym leaf it touches in the clue (Company
    introducing = CO). Two touching leaves stay for the model (either could hold it)."""
    clue = ctx["clue"]
    a = ind.get("at")
    if a is None or not ind.get("text") or clue[a:a + len(ind["text"])] != ind["text"]:
        return None
    b = a + len(ind["text"])
    near = []
    for k, lf in enumerate(base.get("parts") or []):
        if not (isinstance(lf, dict) and leaf(lf) and lf.get("words") and lf.get("gives")) or lf.get("unchecked") \
                or lf.get("at") is None or W.letters(lf["gives"]) == W.letters(lf["words"]):
            continue
        la, lb = lf["at"], lf["at"] + len(lf["words"])
        if clue[la:lb] != lf["words"]:
            continue
        if lb <= a and not W.letters(clue[lb:a]):
            near.append((k, la, b))
        elif b <= la and not W.letters(clue[b:la]):
            near.append((k, a, lb))
    if len(near) != 1:
        return None
    k, x, y = near[0]
    text, at = clue_text(clue, x, y)
    new = copy.deepcopy(base)
    new["parts"][k] = {**new["parts"][k], "words": text, "at": at}
    if V.misplaced_indicators(new) or V.folded_indicators(new) or not _eval_swapped(node, parent, new, ctx):
        return None
    return new


def r_shared_charade(node, parent, ctx):
    """sharedIndicator, charade: an indicator filed on a charade whose words are also a leaf's clue
    words in it ([over]RE + [Fell]LAPSED with 'over' on the charade as well). A charade needs no
    indicator, so the word stays with the leaf that gives letters for it and leaves the charade."""
    if node.get("op") != "charade" or node.get("unchecked") or not node.get("indicators"):
        return None
    words = {W.letters(p["words"]) for p in node.get("parts") or []
             if isinstance(p, dict) and leaf(p) and p.get("words") and p.get("gives")}
    keep = [i for i in node["indicators"] if W.letters(i.get("text")) not in words]
    if len(keep) == len(node["indicators"]):
        return None
    new = {k: v for k, v in node.items() if k != "indicators"}
    if keep:
        new["indicators"] = keep
    return new if _eval_swapped(node, parent, new, ctx) else None


def r_split_shared_indicator(node, parent, ctx):
    """splitSharedIndicator: two (or more) neighbouring same-kind ops (selection, homophone, deletion)
    under one parent, only one carrying the indicator: one multi-part op with that indicator over all
    their parts, set where the first stood. Kept only when the whole tree still gives the answer."""
    kids = [q for q in node.get("parts") or [] if isinstance(q, dict)]
    out = None
    for op in V._SHARED_OK:
        ns = [q for q in kids if q.get("op") == op and not q.get("unchecked")]
        if len(ns) < 2 or sum(bool(x.get("indicators")) for x in ns) != 1:
            continue
        if len(ns) == 2 and not V._pair_adjacent(ns):
            continue
        if out is not None:
            return None
        carrier = next(x for x in ns if x.get("indicators"))
        notes = list(dict.fromkeys(x["note"] for x in ns if x.get("note")))
        merged = {k: v for k, v in carrier.items() if k not in ("parts", "gives", "note")}
        merged["parts"] = [copy.deepcopy(p) for x in ns for p in x["parts"]]
        if op in ("homophone", "deletion"):
            # the validator takes neither a multi-part homophone, a joined-spelling leaf nor a multi-cut
            # deletion (wrong number of parts / leaf that is no word): left for the model
            return None
        if notes:
            merged["note"] = " ".join(notes)
        out = (ns, merged)
    if out is None:
        return None
    ns, merged = out
    new = copy.deepcopy(node)
    at = [id(q) for q in node["parts"]].index(id(ns[0]))
    new["parts"] = [copy.deepcopy(q) for q in node["parts"] if not any(q is x for x in ns)]
    new["parts"].insert(at, merged)
    return new if _eval_swapped(node, parent, new, ctx) else None
