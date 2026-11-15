"""Mechanical mend for validate_shape.misplaced_indicators ("1 clue(s) missing wordplay.misplacedIndicator").

The rule: an indicator filed on a charade that the lexicon files only under another op belongs on that op.
fix_shape_suspects.r_misplaced_indicator already moves it (onto the one op of that type inside the charade,
into a swap, into a first/last selection, or folds a link word into its synonym leaf) and only when the
tree still gives the answer and exactly one placement does. apply_annotations runs it on the stored shape;
this runs it on the model's `wp` in annotate_check so the first check does not spend a model turn on it.
Anything ambiguous (several candidate ops, none that keep the answer) is left to the model."""
import copy

import fix_shape_suspects as F
import validate_annotations as V
import wordplay


def mend(a, clue, answer):
    """Rewrite model-shape annotation `a`'s `wp` in place; whether it changed."""
    wp = a.get("wp") if isinstance(a, dict) else None
    if not (isinstance(wp, str) and "+" in wp and clue and answer):
        return False
    try:
        tree = wordplay.parse(wp, clue)
        before = V.misplaced_indicators(tree)
        if not before:
            return False
        fixed, used = F.repair_tree(tree, clue, answer, {"misplacedIndicator": F.RULE_REPAIRS["misplacedIndicator"]})
        if not used:
            return False
        fixed = wordplay.normalize(fixed, clue, answer)[0]
        wordplay.evaluate(copy.deepcopy(fixed), answer)
        if V.misplaced_indicators(fixed) >= before:
            return False
        new = wordplay.render(fixed)
        wordplay.parse(new, clue)
    except Exception:
        return False
    if new == wp:
        return False
    a["wp"] = new
    return True
