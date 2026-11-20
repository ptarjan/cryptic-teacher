"""The tree helpers and the gate-free pieces every fix_shape_* module shares: walking a tree, the
end/head/middle indicator words, and the evaluate-the-swap helpers the repairs build on.
"""
import copy
import json
import re

import validate_annotations as V
import wordplay as W


UNARY = ("reversal", "cycling", "hidden") + W.SELECT

TAIL = re.compile(r"end|tail|last|final|finish|clos|short|almost|most|nearly|brief|large|main|quite|incomplete|"
                  r"unfinish|curtail|dock|abridg|truncat|clip|bottom|all but|not all|not entirely|"
                  r"not fully|not completely|partly|practically|virtually|cut off|chopped", re.I)

HEAD = re.compile(r"head|top|first|start|lead|open|initial|front|begin|scalp|decapit|behead|cap", re.I)

MID = re.compile(r"heart|middle|centre|center|core|gut|empt|void|hollow|insides", re.I)


# ---------- tree helpers ----------

def walk(node, parent=None):
    yield node, parent
    for p in node.get("parts") or []:
        yield from walk(p, node)


def leaf(node):
    return "op" not in node


def span(node):
    """(start, end) of the clue words under `node`, or None if any leaf lacks `at`."""
    lo, hi = None, None
    for n, _ in walk(node):
        if leaf(n):
            if "words" not in n:
                continue
            if n.get("at") is None:
                return None
            a, b = n["at"], n["at"] + len(n["words"])
            lo, hi = (a, b) if lo is None else (min(lo, a), max(hi, b))
    return None if lo is None else (lo, hi)


def vals(node):
    """values() or None when it can't be known alone."""
    try:
        v = W.values(node)
    except (W.WordplayError, IndexError, KeyError, TypeError, W._NeedTarget):
        return None
    return v


def gives_ok(node, want):
    try:
        return W.match(copy.deepcopy(node), want) is not None
    except (W.WordplayError, IndexError, KeyError, TypeError, W._NeedTarget):
        return False


def checked(node, **kw):
    """`node` with its unchecked flag and filed letters gone, `kw` set."""
    out = {k: v for k, v in node.items() if k not in ("unchecked", "gives")}
    out.update(kw)
    return out


def charade(parts):
    flat = []
    for p in parts:
        if p.get("op") == "charade" and not p.get("indicators") and not p.get("unchecked") and "gives" not in p:
            flat += p["parts"]
        else:
            flat.append(p)
    # Neighbouring leaves on the same clue words are one leaf.
    out = []
    for p in flat:
        q = out[-1] if out else None
        if q is not None and leaf(p) and leaf(q) and p.get("words") and p.get("words") == q.get("words") \
                and p.get("at") == q.get("at") and not p.get("unchecked") and not q.get("unchecked"):
            out[-1] = {**q, "gives": W.leaf_letters(q) + W.leaf_letters(p)}
        else:
            out.append(p)
    return out[0] if len(out) == 1 else {"op": "charade", "parts": out}


def clue_text(clue, a, b):
    """The clue's words between a and b, trimmed of spaces and edge punctuation; (text, start)."""
    s = clue[a:b]
    lead = len(s) - len(s.lstrip(" ,;:.!?—–-\"“”‘(){}[]"))
    s = s.strip(" ,;:.!?—–-\"“”‘(){}[]")
    return s, a + lead


def simplicity(tree):
    """Canonical-form key among letter-equal trees (Paul: the simplest is canonical): the fewest
    ops, then each op acting on the fewest letters (the sum, over ops, of the letters of the
    leaves under it). Lower is simpler."""
    ops, letters = 0, 0
    for n, _ in walk(tree):
        if not leaf(n):
            ops += 1
            letters += sum(len(W.leaf_letters(x)) for x, _ in walk(n) if leaf(x))
    return ops, letters


def _eval_swapped(node, parent, new, ctx):
    """Whether the whole tree still gives the answer with `node` replaced by `new`."""
    answer = ctx.get("answer")
    if not answer:
        return False
    try:
        W.evaluate(_whole(node, parent, new, ctx), answer)
        return True
    except (W.WordplayError, IndexError, KeyError, TypeError, ValueError, W._NeedTarget):
        return False


def _whole(node, parent, new, ctx):
    """A copy of the whole tree with `node` replaced by `new` (a plain charade going into a
    plain charade is joined to it, as repair_tree does)."""
    if parent is None:
        return copy.deepcopy(new)
    i = [id(x) for x in parent["parts"]].index(id(node))
    saved = list(parent["parts"])
    try:
        if _splices(new, parent):
            parent["parts"][i:i + 1] = new["parts"]
        else:
            parent["parts"][i] = new
        return copy.deepcopy(ctx["tree"])
    finally:
        parent["parts"][:] = saved


def _flat_fodder(node):
    """The parts of an anagram, an indicator-free charade among them opened out."""
    out = []
    for p in node.get("parts") or []:
        if p.get("op") == "charade" and not p.get("indicators") and not p.get("unchecked"):
            out += p["parts"]
        else:
            out.append(p)
    return out


def _is_stand_in(p):
    """A leaf that gives other letters than its own words (a synonym), not a doubling."""
    if not leaf(p) or not p.get("words") or p.get("select"):
        return False
    g, w = W.letters(p.get("gives")), W.letters(p["words"])
    return len(g) >= 2 and g != w and not V._doubled(p) and not V._near_literal(p)


def _plain_charade(n):
    return bool(n) and n.get("op") == "charade" and not n.get("indicators") and not n.get("unchecked") \
        and "gives" not in n


def _splices(new, parent):
    """1 when `new` is a plain charade going into a plain charade (repair_tree joins them)."""
    # a charade directly under an anagram is flattened into the anagram's own parts (anagramCharade)
    return int(_plain_charade(new) and (_plain_charade(parent) or (parent or {}).get("op") == "anagram"))


def _pick(node, parent, ctx, cands):
    """The simplest of the candidates that keep the answer; None unless it is simpler than
    `node` and the only one of that simplicity."""
    good = [c for c in cands if _eval_swapped(node, parent, c, ctx)]
    if not good:
        return None
    def key(c):      # the whole tree's key, so a joined charade is not counted twice
        return simplicity(_whole(node, parent, c, ctx))
    best = min(key(c) for c in good)
    top = {json.dumps(c, sort_keys=True): c for c in good if key(c) == best}
    if len(top) != 1 or best >= simplicity(ctx["tree"]):
        return None
    return next(iter(top.values()))


def _diff_gone(v, want, ind=None):
    """The one run of letters whose removal from v leaves want (None unless exactly one such string);
    an end/head/middle word in the indicator narrows where the run may sit."""
    m = len(v) - len(want)
    if m < 1:
        return None
    tail, head = bool(ind and TAIL.search(ind)), bool(ind and HEAD.search(ind))
    mid = bool(ind and MID.search(ind))
    if tail + head + mid > 1:
        return None
    runs = set()
    for j in range(len(v) - m + 1):
        if v[:j] + v[j + m:] != want:
            continue
        if (tail and j + m != len(v)) or (head and j != 0) or (mid and (j == 0 or j + m == len(v))):
            continue
        runs.add(v[j:j + m])
    if not runs and not (tail or head or mid) and m == 2 and v[1:-1] == want:
        return v[0] + v[-1]     # unlimited / without clothing: both ends go
    return runs.pop() if len(runs) == 1 else None


def _flat_leaves(parts):
    """Parts with plain charades opened out."""
    out = []
    for p in parts:
        if p.get("op") == "charade" and not p.get("indicators") and "gives" not in p:
            out += _flat_leaves(p.get("parts") or [])
        else:
            out.append(p)
    return out


def _words_between(clue, a, b):
    """True when only spaces and punctuation lie in clue[a:b]."""
    return not re.search(r"[A-Za-z0-9]", clue[a:b])


def unchecked(tree):
    return sum(bool(n.get("unchecked")) for n, _ in walk(tree))
