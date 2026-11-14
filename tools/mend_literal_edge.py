"""Mechanical mend for validate_shape_leaf.ana_literal_edge ("1 clue(s) missing wordplay.anaLiteralEdge").

The rule is not a missing field: an anagram's first or last fodder piece is 2+ clue-word letters taken
as written, and the answer shows them unscrambled at its edge (ZERO + ana(TO + CLEANER) holding TO).
The right tree sets that piece beside the anagram in a charade. Where exactly one such pull keeps
the whole tree giving the answer (and opens no poolGap), `mend` writes it into the model's `wp`, so the
first check does not spend a model turn on it. Anything with two readings is left to the model."""
import copy

import validate_annotations as V
import wordplay


def _pulls(tree, answer, clue):
    """Renderings of every tree where one edge part of one anagram is pulled out and the literal-edge
    count drops; (set of renders, {render: tree})."""
    base = V.ana_literal_edge(tree, answer, clue)
    out = {}
    for node in V._walk(tree):
        parts = node.get("parts") or []
        if node.get("op") != "anagram" or node.get("unchecked") or len(parts) < 2:
            continue
        for idx in (0, len(parts) - 1):
            t = V._pull_part(tree, node, idx, idx == 0)
            if t is None:
                continue
            try:
                wordplay.evaluate(copy.deepcopy(t), answer)
            except Exception:
                continue
            if V.pool_gaps(t, clue) > V.pool_gaps(tree, clue) or V.ana_literal_edge(t, answer, clue) >= base:
                continue
            out[wordplay.render(t)] = t
    return out


def mend(a, clue, answer):
    """Rewrite model-shape annotation `a`'s `wp` in place; whether it changed."""
    wp = a.get("wp") if isinstance(a, dict) else None
    if not (isinstance(wp, str) and "ana" in wp and clue and answer):
        return False
    changed = False
    for _ in range(3):
        try:
            tree = wordplay.parse(wp, clue)
            if not V.ana_literal_edge(tree, answer, clue):
                break
            cands = _pulls(tree, answer, clue)
        except Exception:
            break
        if len(cands) != 1:
            break
        wp = next(iter(cands))
        changed = True
    if changed:
        a["wp"] = wp
    return changed
