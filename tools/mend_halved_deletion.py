"""Mechanical mend for validate_shape_leaf.halved_as_deletion ("1 clue(s) missing wordplay.halvedAsDeletion").

The rule: a deletion whose indicator says half ("half of", "50 per cent") keeps half the word, so it is
a first/last selection, not a deletion. fix_shape_suspects.r_halved_deletion already rewrites it when the
cut is exactly one end half of the word and the tree still gives the answer. apply_annotations runs it on
the stored shape; this runs it on the model's `wp` in annotate_check so the first check does not spend a
model turn on it. Anything ambiguous is left to the model."""
import copy

import fix_shape_suspects as F
import validate_annotations as V
import wordplay


def mend(a, clue, answer):
    """Rewrite model-shape annotation `a`'s `wp` in place; whether it changed."""
    wp = a.get("wp") if isinstance(a, dict) else None
    if not (isinstance(wp, str) and "del" in wp and clue and answer):
        return False
    try:
        tree = wordplay.parse(wp, clue)
        before = V.halved_as_deletion(tree)
        if not before:
            return False
        fixed, used = F.repair_tree(tree, clue, answer, {"halvedAsDeletion": F.RULE_REPAIRS["halvedAsDeletion"]})
        if not used:
            return False
        fixed = wordplay.normalize(fixed, clue, answer)[0]
        wordplay.evaluate(copy.deepcopy(fixed), answer)
        if V.halved_as_deletion(fixed) >= before:
            return False
        new = wordplay.render(fixed)
        wordplay.parse(new, clue)
    except Exception:
        return False
    if new == wp:
        return False
    a["wp"] = new
    return True
