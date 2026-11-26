"""The one registry of mechanical wordplay repairs, and the drivers that run them.

A rule is a validator (or shape detector) key with two halves: `fix`, a node repair
(node, parent, ctx) -> new node or None that repair_tree runs bottom-up to a fixpoint,
and `count`, the detector that must fire before the fix runs and fire less after it.
The repairs themselves live in the fix_shape_* family modules; this file says which
of them answer which rule, and is the only place a caller gets fixers from:

  RULES          validator-keyed rules. apply_annotations runs every one on each fresh
                 annotation (mend_fresh); fix_shape_suspects --rule sweeps the stored
                 corpus with one; wordplay.translate uses doesNotGive.
  MODEL_MENDS    the rewrites annotate_check makes on the model's `wp` text before the
                 annotation is translated (mend_wp): trees the evaluator refuses outright
                 (an anagram inside a deletion) and a few RULES run on the model's tree.
  REPAIRS        the shape_suspects detector sweep's own repairs (fix_shape_suspects).
  FOLLOW_ON      chained after a rule's repair, on the tree it produced.

A new mechanical fixer is one entry here: a RULES entry runs on every fresh annotation
with no other edit. Each driver declines a repair that raises wordplay.WordplayError
(a fix that breaks its own tree); any other exception is a bug and surfaces.
"""
import copy
import re
from dataclasses import dataclass
from typing import Callable, Optional

import clue_shapes as cs
import shape_queue
import shape_suspects as ss
import validate_annotations as V
import wordplay as W
from fix_shape_base import walk, leaf, unchecked, _splices
from fix_shape_leaves import (
    r_ins_split, r_del_removed, r_del_unwrap, r_link_leaf, r_sel_literal, r_arity_wrap, r_leaf_trim, r_ind_trim,
    r_leaf_check, r_leaf_fold, r_ind_in_leaf, r_own_ind_leaf, r_trunc_leaf, r_link_in_leaf, r_ind_leaf_overlap,
    r_half_cut, r_arity_ins, r_removed_leaf, r_literal_fodder, r_half_leaf, r_arity_other, r_span_overlap,
)
from fix_shape_indicators import (
    r_role_swap, r_role_move, r_ind_trade, r_shared_indicator, r_unindicated_move, r_unindicated_spare,
    r_hidden_link, r_hidden_possessive, r_swapped_pair, r_misplaced_indicator, r_shared_charade,
    r_split_shared_indicator, r_double_indicator,
)
from fix_shape_container import (
    r_container_inside, r_nested_container, r_container_cut, r_extremes_outer, r_extremes_pair, r_pool_gap,
    r_pool_absorb, r_pool_eject, r_container_gap, r_reversal_split, r_nested_same_op, r_del_wraps_charade,
)
from fix_shape_cuts import (
    r_sel_one_letter, r_sel_one_link, r_del_selection, r_deletion_inside, r_del_single, r_halved_deletion,
    r_trim_selection, r_moved_letter, r_cut_note_leaf, r_del_one_piece, r_repeated_selection, r_sel_edge,
    r_leaf_select,
)
from fix_shape_ana import (
    r_ana_synonym_charade, r_ana_stand_in, r_ana_of_container, r_ana_charade, r_ana_pull, r_ana_edge,
    r_ana_select_edge, r_scrambled_swap, r_ana_lone_edge, r_ana_flatten,
)
from fix_shape_notes import (
    unnoted_indicators, r_indicator_note, unnoted_blocks, r_block_note, r_does_not_give, r_doubled_apostrophe,
    note_deletions,
)


# ---------- the detector a rule must clear ----------

def hits(ann, clue, answer):
    """{shape_suspects detector: finding} for annotation `ann`: a repair may not add one."""
    wp = ann.get("wordplay")
    if not wp:
        return {}
    r = {"wp": wp, "andLit": bool(ann.get("andLit")), "defs": ann.get("definitions") or [],
         "sk": cs.analyse(wp)[0], "clue": clue, "sol": answer}
    out = {}
    for k, f in ss.DETECTORS.items():
        try:
            x = f(r)
        except Exception:
            x = None
        if x:
            out[k] = x
    return out


def _span_overlaps(tree, clue):
    """V.span_overlaps on a copy of `tree` with its places worked out (the rule reads them)."""
    try:
        return V.span_overlaps(W.locate(copy.deepcopy(tree), clue))
    except W.WordplayError:
        return 0


def _gives_not(tree, answer):
    """1 when `tree` does not give `answer` (the refusal the first check names), else 0."""
    try:
        W.evaluate(copy.deepcopy(tree), answer or "")
        return 0
    except W.WordplayError:
        return 1


def _selectors_in_leaves(tree):
    """How many leaves give a letter while holding its selector word ("[socialist leader]S",
    "[leading Italian]I"): the committed-file check refuses these as a block with its selector
    inside, and r_leaf_select turns each into the selection op."""
    return sum(1 for n, parent in walk(tree)
               if leaf(n) and n.get("gives") and n.get("words") and not n.get("unchecked")
               and (parent or {}).get("op") not in W.SELECT
               and V.selector_in_block({"clueFragment": n["words"], "gives": n["gives"]}))


#: Queue rows that name a shape_suspects detector, not a validator rule: how they are counted.
_DETECTOR_RULES = {"unchecked_leaf": lambda wp, full, clue: "unchecked_leaf" in hits(full, clue, full.get("_answer")),
                   "del_single": lambda wp, full, clue: V.del_single(wp),
                   "arity_ins": lambda wp, full, clue: V.arity_ins(wp),
                   "arity_other": lambda wp, full, clue: V.arity_other(wp),
                   "ind_in_leaf": lambda wp, full, clue: V.ind_in_leaf(wp, clue),
                   "indicatorNote": lambda wp, full, clue: unnoted_indicators(wp),
                   "blockNote": lambda wp, full, clue: unnoted_blocks(wp, full.get("_answer"))}


def _counters():
    """{rule: fn(tree, annotation with _answer, clue) -> hits}: the detectors, then the shape
    queue's validator rules, then the counts the first check reads differently."""
    table = {**_DETECTOR_RULES, **shape_queue._validator_rules()}
    table["unindicatedBare"] = lambda t, a, c: V.unindicated_ops(t)
    table["trimAsSelection"] = lambda t, a, c: V.trims_as_selection(t, a.get("_answer"))
    table["repeatedSelection"] = lambda t, a, c: V.repeated_selections(t)
    table["spanOverlap"] = lambda t, a, c: _span_overlaps(t, c)
    table["doesNotGive"] = lambda t, a, c: _gives_not(t, a.get("_answer"))
    table["selectorInLeaf"] = lambda t, a, c: _selectors_in_leaves(t)
    return table


# ---------- the rules ----------

@dataclass(frozen=True)
class Rule:
    name: str
    fix: Callable              # (node, parent, ctx) -> new node or None
    count: Optional[Callable]  # (tree, annotation with _answer, clue) -> hits; None: nothing fires it


def r_wrong_role(node, parent, ctx):
    """wrongRole: a leaf that folds a deletion into its words (r_leaf_fold), else indicators on
    the wrong one of two nested ops (r_role_swap), a selection indicator hung on a one-letter word
    (r_sel_one_letter)."""
    return r_leaf_fold(node, parent, ctx) or r_extremes_outer(node, parent, ctx) or r_extremes_pair(node, parent, ctx) \
        or r_role_swap(node, parent, ctx) or r_ind_trade(node, parent, ctx) \
        or r_container_cut(node, parent, ctx) or r_role_move(node, parent, ctx) or r_sel_one_letter(node, parent, ctx) \
        or r_sel_one_link(node, parent, ctx)


def _first(*fns):
    """A fix that tries `fns` in turn and takes the first repair."""
    def fix(n, p, c):
        for f in fns:
            new = f(n, p, c)
            if new:
                return new
        return None
    return fix


def _unindicated_bare(n, p, c):
    return _first(r_unindicated_move, r_unindicated_spare, r_hidden_link, r_container_gap, r_hidden_possessive)(n, p, c) \
        or r_unindicated_move(n, p, c, V.unindicated_ops) or r_unindicated_spare(n, p, c, V.unindicated_ops)


# Order matters: mend_fresh runs the rules in this order on each fresh tree.
_FIXES = (
    ("doubledApostrophe", r_doubled_apostrophe), ("repeatedSelection", r_repeated_selection),
    ("delWrapsCharade", r_del_wraps_charade), ("nestedSameOp", r_nested_same_op), ("delOnePiece", r_del_one_piece),
    ("cutNoteLeaf", r_cut_note_leaf), ("movedLetter", r_moved_letter), ("halvedAsDeletion", r_halved_deletion),
    ("trimAsSelection", r_trim_selection), ("reversalSplit", r_reversal_split),
    ("reversedCharadeOrder", r_reversal_split), ("anaLoneEdge", r_ana_lone_edge),
    ("splitSharedIndicator", r_split_shared_indicator), ("scrambledLeaf", r_scrambled_swap),
    ("anaCharade", _first(r_ana_charade, r_ana_pull, r_ana_edge, r_ana_flatten)), ("anaSelectEdge", r_ana_select_edge),
    ("linkInLeaf", r_link_in_leaf), ("indLeafOverlap", r_ind_leaf_overlap), ("swappedPair", r_swapped_pair),
    ("halfLeaf", r_half_leaf), ("arity_other", _first(r_arity_other, r_arity_ins)),
    ("unchecked_step", r_literal_fodder), ("unchecked_leaf", r_removed_leaf), ("arity_ins", r_arity_ins),
    ("anaSynonym", r_ana_synonym_charade), ("anaStandIn", r_ana_stand_in), ("anagramOfContainer", r_ana_of_container),
    ("containerInside", r_container_inside), ("nestedContainer", r_nested_container),
    ("wrongRole", r_wrong_role), ("delSelection", r_del_selection),
    ("sharedIndicator", _first(r_shared_indicator, r_shared_charade)),
    ("poolGap", _first(r_pool_gap, r_pool_absorb, r_pool_eject)),
    ("misplacedIndicator", r_misplaced_indicator), ("doubleIndicator", r_double_indicator),
    ("deletionInside", r_deletion_inside), ("deletionScope", r_deletion_inside), ("deletionScopeAnswer", r_deletion_inside),
    ("unindicatedBare", _unindicated_bare), ("spanOverlap", r_span_overlap),
    ("del_single", r_del_single), ("indInLeaf", r_ind_in_leaf), ("ind_in_leaf", r_ind_in_leaf),
    ("selectWordInLeaf", r_own_ind_leaf), ("ownIndInLeaf", r_own_ind_leaf), ("truncInLeaf", r_trunc_leaf),
    ("doesNotGive", r_does_not_give), ("indicatorNote", r_indicator_note), ("blockNote", r_block_note),
    ("selectorInLeaf", r_leaf_select),
)
_COUNTS = _counters()
RULES = {name: Rule(name, fix, _COUNTS.get(name)) for name, fix in _FIXES}


def fixers(*names):
    """{name: fix} for repair_tree, from RULES."""
    return {n: RULES[n].fix for n in names}


#: The shape_suspects detector sweep's repairs (fix_shape_suspects without --rule).
REPAIRS = {"ins_split": r_ins_split, "del_removed": r_del_removed, "del_unwrap": r_del_unwrap,
           "arity_wrap": r_arity_wrap, "half_cut": r_half_cut, "leaf_trim": r_leaf_trim, "ind_trim": r_ind_trim,
           "leaf_check": r_leaf_check, "link_leaf": r_link_leaf, "sel_literal": r_sel_literal}

#: Chained after a rule's own repair, on the tree it produced: a role move leaves the selection
#: indicator both on the op and at the edge of its source leaf, and the leaf then loses it.
FOLLOW_ON = {"leaf_trim": r_leaf_trim, "ind_trim": r_ind_trim, "sel_edge": r_sel_edge, "leaf_select": r_leaf_select}


# ---------- the node driver ----------

def repair_tree(tree, clue, answer=None, repairs=None):
    """(new tree, [repair names]) after applying `repairs` (default REPAIRS) to a fixpoint, bottom-up.
    A RULES repair that yields a plain charade under a plain charade is spliced into it."""
    repairs = repairs or REPAIRS
    tree = copy.deepcopy(tree)
    had_at = any("at" in x for n, _ in walk(tree) for x in [n, *(n.get("indicators") or [])])
    try:
        # Stored trees mostly carry no offsets: place every span on a copy, as view() does.
        tree = W.locate(copy.deepcopy(tree), clue)
    except W.WordplayError:
        pass
    used = []
    ctx = {"clue": clue, "answer": answer}
    for _ in range(12):
        ctx["under_unchecked"] = under_unchecked(tree)
        ctx["tree"] = tree
        changed = False
        for n, parent in reversed(list(walk(tree))):
            for name, fn in repairs.items():
                try:
                    new = fn(n, parent, ctx)
                except (W.WordplayError, IndexError, KeyError, TypeError, ValueError):
                    new = None
                if new is None:
                    continue
                if parent is None:
                    tree = new
                else:
                    i = [id(x) for x in parent["parts"]].index(id(n))
                    if name in RULES and _splices(new, parent):
                        parent["parts"][i:i + 1] = new["parts"]
                    else:
                        parent["parts"][i] = new
                used.append(name)
                changed = True
                break
            if changed:
                break
        if not changed:
            break
    if not had_at:
        for n, _ in walk(tree):
            n.pop("at", None)
            for i in n.get("indicators") or []:
                i.pop("at", None)
    return tree, used


def under_unchecked(tree):
    """ids of the nodes with an unchecked node above them."""
    out = set()

    def go(n, below):
        if below:
            out.add(id(n))
        for p in n.get("parts") or []:
            go(p, below or bool(n.get("unchecked")))
    go(tree, False)
    return out


def attempt(name, tree, clue, answer):
    """`tree` with rule `name` repaired and the FOLLOW_ON trims chained after it, or None when the
    rule makes no repair. Not yet normalized or gated: each caller gates it its own way."""
    fixed, used = repair_tree(tree, clue, answer, fixers(name))
    if not used:
        return None
    return note_deletions(repair_tree(fixed, clue, answer, FOLLOW_ON)[0])


def _size(x):
    """How many hits a detector's answer stands for (a count, a list or a bool)."""
    try:
        return len(x)
    except TypeError:
        return int(x or 0)


# ---------- fresh annotations (apply_annotations) ----------

def mend_fresh(new, clue, answer, fired=None):
    """The stored tree of fresh annotation `new` with every rule that fires on it repaired, in RULES
    order; the names of the rules whose repair was kept are appended to the list `fired`, when given. A repair is kept when its rule fires less after it (a poolGap: not at all), it opens no
    poolGap, no shape detector newly fires and no step newly goes unchecked."""
    wp = new["wordplay"]
    for rule in RULES.values():
        count = rule.count
        if count is None or not count(wp, {**new, "wordplay": wp, "_answer": answer}, clue):
            continue
        try:
            fixed = attempt(rule.name, wp, clue, answer)
            if fixed is None:
                continue
            fixed = W.normalize(fixed, clue, answer)[0]
            now = {**new, "wordplay": wp, "_answer": answer}
            after = {**new, "wordplay": fixed, "_answer": answer}
            left = _size(count(fixed, after, clue))
            better = left < _size(count(wp, now, clue))
            if rule.name == "poolGap" and left:
                better = False
            if rule.name != "poolGap" and better:
                # a mend that opens a poolGap (anaLoneEdge pulling F out of "This fine gift") trades one refusal for one the model cannot meet
                if V.pool_gaps(fixed, clue) > V.pool_gaps(wp, clue):
                    better = False
            if better and set(hits(after, clue, answer)) <= set(hits(now, clue, answer)) \
                    and unchecked(fixed) <= unchecked(wp):
                wp = fixed
                if fired is not None:
                    fired.append(rule.name)
        except W.WordplayError:  # a repair that breaks its own tree is declined
            continue
    return wp


# ---------- the model's wp text (annotate_check) ----------

@dataclass(frozen=True)
class Mend:
    name: str
    said: str                   # what annotate_check prints before " in <file>: <ids>"
    guard: tuple                # substrings the wp must hold for the mend to be tried
    transform: Callable         # (parsed tree, clue, answer, annotation) -> new wp text or None


def _rule_mend(name, no_new_pool_gap=False):
    """A RULES rule run on the model's tree: kept when it fires less, the tree gives the answer
    and (`no_new_pool_gap`) no poolGap opens."""
    def transform(tree, clue, answer, a):
        rule = RULES[name]
        before = rule.count(tree, {"_answer": answer}, clue)
        if not before:
            return None
        fixed, used = repair_tree(tree, clue, answer, fixers(name))
        if not used:
            return None
        fixed = W.normalize(fixed, clue, answer)[0]
        W.evaluate(copy.deepcopy(fixed), answer)
        if rule.count(fixed, {"_answer": answer}, clue) >= before:
            return None
        if no_new_pool_gap and V.pool_gaps(fixed, clue) > V.pool_gaps(tree, clue):
            return None
        new = W.render(fixed)
        W.parse(new, clue)
        return new
    return transform


def _literal_pulls(tree, answer, clue):
    """{render: tree} of every tree where one edge part of one anagram is pulled out, the tree still
    gives the answer, no poolGap opens and the literal-edge count drops."""
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
                W.evaluate(copy.deepcopy(t), answer)
            except W.WordplayError:
                continue
            if V.pool_gaps(t, clue) > V.pool_gaps(tree, clue) or V.ana_literal_edge(t, answer, clue) >= base:
                continue
            out[W.render(t)] = t
    return out


def _literal_edge(tree, clue, answer, a):
    """anaLiteralEdge: an anagram's first or last fodder piece is 2+ clue letters taken as written that
    the answer shows unscrambled at its edge (ZERO + ana(TO + CLEANER)); it goes beside the anagram in a
    charade. Up to three pulls, each the one pull that keeps the answer; two readings stop it."""
    wp = None
    for _ in range(3):
        try:
            if not V.ana_literal_edge(tree, answer, clue):
                break
            cands = _literal_pulls(tree, answer, clue)
            if len(cands) != 1:
                break
            wp = next(iter(cands))
            tree = W.parse(wp, clue)
        except W.WordplayError:
            break
    return wp


ANA_DELETION_REFUSED = "sits where its letters have to be known"


def _ana_in_deletion(node):
    """Whether `node` (or anything under it) changed; deletions of an anagram become composites in place."""
    changed = False
    for p in node.get("parts") or []:
        changed |= _ana_in_deletion(p)
    parts = node.get("parts") or []
    if node.get("op") == "deletion" and len(parts) >= 2 and parts[0].get("op") == "anagram" \
            and not parts[0].get("unchecked") and not node.get("unchecked"):
        ana = parts[0]
        cut = parts[1:]
        node["op"] = "composite"
        node["indicators"] = list(node.get("indicators") or []) + list(ana.get("indicators") or [])
        node["parts"] = [W.fodder_pool(ana), cut[0] if len(cut) == 1 else {"op": "charade", "parts": cut}]
        changed = True
    return changed


def _ana_deletion(tree, clue, answer, a):
    """del(ana(F), D), which the evaluator refuses (the cut needs the anagram's letters in order), is the
    composite anagram comp(F, D): the letters are F's minus D's and the answer gives the order. Both
    indicators are kept (the deletion's first). Anagrams inside sub, a selection or a homophone stay
    refused: where the cut falls in the rearranged letters is not the clue's to say."""
    try:
        W.evaluate(copy.deepcopy(tree), answer)
        return None  # it already gives the answer: nothing to mend
    except W.WordplayError as e:
        if ANA_DELETION_REFUSED not in str(e):
            return None
    fixed = copy.deepcopy(tree)
    if not _ana_in_deletion(fixed):
        return None
    W.evaluate(copy.deepcopy(fixed), answer)
    new = W.render(fixed)
    W.parse(new, clue)
    return new


_NOTE_WORDS = re.compile(r"\b(?:notes?|keys?)\b", re.I)


def _note_letters(tree, clue, answer, a):
    """singleLeaf on the musical-letters clue ([notes]ACCEDE, [a bunch of keys]DEFACE): the whole wordplay
    is one leaf of "notes"/"keys" words and the answer is spelt only with A-G, so it is a charade of one
    note per letter, written `[words]A + [words]C + ...` with a note saying so. A leaf naming no notes,
    or an answer with a letter outside A-G, is a synonym or a real mechanism: left."""
    letters = re.sub(r"[^A-Za-z]", "", answer).upper()
    if len(letters) < 3 or re.search(r"[^A-G]", letters):
        return None
    if not V.single_leaf(tree):
        return None
    words = tree.get("words") or ""
    if not _NOTE_WORDS.search(words):
        return None
    new = " + ".join(f"[{words}]{c}" for c in letters)
    fixed = W.parse(new, clue)
    W.evaluate(copy.deepcopy(fixed), answer)
    if V.single_leaf(fixed) or V.span_overlaps(fixed):
        return None
    notes = a.get("notes")
    if isinstance(notes, dict) and words not in notes:
        notes[words] = "each letter is a musical note or key"
    return new


# In the order annotate_check runs them.
MODEL_MENDS = (
    Mend("anaLiteralEdge", "anagrams holding a clue word as written at their edge, the word set beside the "
         "anagram in a charade", ("ana",), _literal_edge),
    Mend("anaLoneEdge", "anagrams holding a lone letter the answer shows at its edge, the letter set beside the "
         "anagram in a charade", ("ana",), _rule_mend("anaLoneEdge", no_new_pool_gap=True)),
    Mend("anaInDeletion", "anagrams inside a deletion, rewritten as the composite anagram they read as",
         ("del", "ana"), _ana_deletion),
    Mend("halvedAsDeletion", "deletions whose indicator says half, rewritten as the first/last selection they are",
         ("del",), _rule_mend("halvedAsDeletion")),
    Mend("truncInLeaf", "leaves giving a word one letter short of the word they hold, rewritten as a deletion",
         (), _rule_mend("truncInLeaf")),
    Mend("noteLetters", "a lone leaf of notes/keys over an A-G answer, spelt out one note per letter",
         (), _note_letters),
    Mend("misplacedIndicator", "indicators filed on a charade that signal another op, moved onto that op",
         ("+",), _rule_mend("misplacedIndicator")),
    Mend("doubleIndicator", "reversals, deletions, hidden words and selections with two separate indicators, "
         "cut to the one the corpus files under the op", ("><",), _rule_mend("doubleIndicator")),
)


def mend_wp(a, clue, answer, only=None):
    """Rewrite model-shape annotation `a`'s `wp` in place with each MODEL_MENDS mend (or those named in
    `only`) in turn; the names of the mends that changed it."""
    done = []
    for m in MODEL_MENDS:
        if only is not None and m.name not in only:
            continue
        wp = a.get("wp") if isinstance(a, dict) else None
        if not (isinstance(wp, str) and clue and answer and all(g in wp for g in m.guard)):
            continue
        try:
            new = m.transform(W.parse(wp, clue), clue, answer, a)
        except W.WordplayError:
            continue
        if new is None or new == wp:
            continue
        a["wp"] = new
        done.append(m.name)
    return done
