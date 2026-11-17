"""Mechanical mend for validate_shape_leaf.trunc_in_leaf ("1 clue(s) missing wordplay.truncInLeaf").

The rule: a leaf like [Nick mostly]SATA gives a word one letter short, so the cut is a deletion with its
own indicator. fix_shape_suspects.r_trunc_leaf (fix_shape_leaves) already rewrites it to
del<mostly>([Nick]SATAN... , N) when the whole word is in the leaf and the tree still gives the answer.
apply_annotations runs it on the stored shape; this runs it on the model's `wp` in annotate_check so the
first check does not spend a model turn on it. A synonym whose whole word is not in the leaf is left to
the model."""
import copy

import fix_shape_suspects as F
import validate_annotations as V
import wordplay


def mend(a, clue, answer):
    """Rewrite model-shape annotation `a`'s `wp` in place; whether it changed."""
    wp = a.get("wp") if isinstance(a, dict) else None
    if not (isinstance(wp, str) and clue and answer):
        return False
    try:
        tree = wordplay.parse(wp, clue)
        before = V.trunc_in_leaf(tree)
        if not before:
            return False
        fixed, used = F.repair_tree(tree, clue, answer, {"truncInLeaf": F.RULE_REPAIRS["truncInLeaf"]})
        if not used:
            return False
        fixed = wordplay.normalize(fixed, clue, answer)[0]
        wordplay.evaluate(copy.deepcopy(fixed), answer)
        if V.trunc_in_leaf(fixed) >= before:
            return False
        new = wordplay.render(fixed)
        wordplay.parse(new, clue)
    except Exception:
        return False
    if new == wp:
        return False
    a["wp"] = new
    return True
