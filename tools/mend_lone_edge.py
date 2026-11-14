"""Mechanical mend for validate_shape_leaf.ana_lone_edge ("1 clue(s) missing wordplay.anaLoneEdge").

The rule: an anagram holds a one-letter fodder piece (an abbreviation, a first/last pick, a lone word
like "a") that the answer shows at its start or end; that letter belongs beside the anagram in a charade.
fix_shape_suspects.r_ana_lone_edge already finds the pull (fewest letters, kept only when exactly one tree
still gives the answer). apply_annotations runs it on the stored shape; this runs it on the model's `wp`
in annotate_check so the first check does not spend a model turn on it. A pull that opens a poolGap, or
that has two readings, is left to the model."""
import copy

import fix_shape_suspects as F
import validate_annotations as V
import wordplay


def mend(a, clue, answer):
    """Rewrite model-shape annotation `a`'s `wp` in place; whether it changed."""
    wp = a.get("wp") if isinstance(a, dict) else None
    if not (isinstance(wp, str) and "ana" in wp and clue and answer):
        return False
    try:
        tree = wordplay.parse(wp, clue)
        before = V.ana_lone_edge(tree, answer, clue)
        if not before:
            return False
        fixed, used = F.repair_tree(tree, clue, answer, {"anaLoneEdge": F.RULE_REPAIRS["anaLoneEdge"]})
        if not used:
            return False
        fixed = wordplay.normalize(fixed, clue, answer)[0]
        wordplay.evaluate(copy.deepcopy(fixed), answer)
        if V.ana_lone_edge(fixed, answer, clue) >= before or V.pool_gaps(fixed, clue) > V.pool_gaps(tree, clue):
            return False
        new = wordplay.render(fixed)
        wordplay.parse(new, clue)
    except Exception:
        return False
    if new == wp:
        return False
    a["wp"] = new
    return True
