"""Mechanical mend for an anagram inside a deletion, del(ana(F), D): the evaluator refuses it ("sits where its
letters have to be known in order") because the cut needs the anagram's letters in order, and the clue gives none.

The reading is unambiguous: the letters are F's minus D's, rearranged, and the answer gives the order, exactly
the composite anagram comp(F, D) (x's letters are the answer plus y's). This rewrites the deletion as that,
keeping both indicators (the deletion's first) and every note. Only a rewrite that makes the tree give the
answer is kept. Anagrams inside sub, a selection or a homophone stay refused: where the cut or pick falls in
the rearranged letters is not the clue's to say, so no one reading is right. annotate_check runs this on the
model's `wp` so the first check does not spend a model turn on it."""
import copy

import wordplay

REFUSED = "sits where its letters have to be known"


def _rewrite(node):
    """Whether `node` (or anything under it) changed; deletions of an anagram become composites in place."""
    changed = False
    for p in node.get("parts") or []:
        changed |= _rewrite(p)
    parts = node.get("parts") or []
    if node.get("op") == "deletion" and len(parts) >= 2 and parts[0].get("op") == "anagram" \
            and not parts[0].get("unchecked") and not node.get("unchecked"):
        ana = parts[0]
        cut = parts[1:]
        node["op"] = "composite"
        node["indicators"] = list(node.get("indicators") or []) + list(ana.get("indicators") or [])
        node["parts"] = [wordplay.fodder_pool(ana), cut[0] if len(cut) == 1 else {"op": "charade", "parts": cut}]
        changed = True
    return changed


def mend(a, clue, answer):
    """Rewrite model-shape annotation `a`'s `wp` in place; whether it changed."""
    wp = a.get("wp") if isinstance(a, dict) else None
    if not (isinstance(wp, str) and "del" in wp and "ana" in wp and clue and answer):
        return False
    try:
        tree = wordplay.parse(wp, clue)
        try:
            wordplay.evaluate(copy.deepcopy(tree), answer)
            return False  # it already gives the answer: nothing to mend
        except wordplay.WordplayError as e:
            if REFUSED not in str(e):
                return False
        fixed = copy.deepcopy(tree)
        if not _rewrite(fixed):
            return False
        wordplay.evaluate(copy.deepcopy(fixed), answer)
        new = wordplay.render(fixed)
        wordplay.parse(new, clue)
    except Exception:
        return False
    if new == wp:
        return False
    a["wp"] = new
    return True
