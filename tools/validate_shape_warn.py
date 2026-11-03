"""Shape warnings of validate_annotations.py: redo regressions, lesson and shape warnings, walkthrough gaps.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import copy
import os
import re
import lesson_checks
import wordplay
import annotation

from validate_base import letters, words_of
from validate_link import link_vocabulary
from validate_shape_base import _walk, _clue_words, CONNECTIVE_WORDS, _accounted_words
from validate_shape_ops import (
    CHARADE_IN_CHARADE, NO_INDICATOR, CDEF_REPEAT, STORED_ARITY, SPAN_OVERLAP, IN_DEFINITION, LEAF_FOLD,
    REPEATED_SELECTION, SINGLE_LEAF, BARE_IN_CHARADE, ANAGRAM_OF_CONTAINER, ARITY_INS, ARITY_OTHER,
    DEL_SINGLE, IND_IN_LEAF, SCRAMBLED_LEAF, NEEDS_INDICATOR, charade_in_charade, unindicated_ops,
    cdef_repeats, bad_arity, span_overlaps, span_overlap_text, in_definition, leaf_folds,
    repeated_selections, single_leaf, bare_in_charade, anagram_of_container, arity_ins, arity_other,
    del_single, ind_in_leaf, scrambled_leaves,
)
from validate_shape_folds import (
    IND_FOLDED, FAKE_PARTS, PADDING_LEAF, folded_indicators, fake_parts, padding_leaves, NESTED_CONTAINER,
    MISPLACED_INDICATOR, nested_containers, ANAGRAM_SYNONYM, anagram_synonyms, MIDWORD_LEAF, midword_leaves,
    wrong_role_indicators, misplaced_indicators,
)
from validate_shape_inside import (
    BARE_INITIAL, DELETION_SCOPE, WRONG_ROLE, CONTAINER_INSIDE, DELETION_INSIDE, UNINDICATED_BARE,
    SHARED_INDICATOR, HALF_LEAF, DELETION_SCATTERED, REVERSE_PHRASE, bare_initials,
    deletion_inside_component, container_inside_component, deletion_scope, deletion_scope_answer,
    unindicated_uncovered, shared_indicators, half_leaves, deletion_scattered, reverse_phrase,
)
from validate_shape_order import (
    DELETION_SCOPE_ANSWER, DOUBLE_INDICATOR, MOVED_LETTER, moved_letters, TRADED_INDICATOR,
    traded_indicators, double_indicators, POOL_GAP, pool_gaps, CHARADE_ORDER, charade_out_of_order,
    REVERSAL_SPLIT, reversal_split, REVERSED_CHARADE_ORDER, reversed_charade_order, CUT_IN_LEAF,
    cut_in_leaf,
)
from validate_shape_leaf import (
    ANA_SELECT_EDGE, NON_WORD_OPERAND, DEL_WIDE, IND_LEAF_OVERLAP, ANA_DOUBLE_IND, DEL_STRADDLE,
    ana_select_edge, del_straddle, non_word_operands, del_wide, ind_leaf_overlap, SWAPPED_PAIR,
    LINK_IN_LEAF, ANA_STAND_IN, swapped_pair, link_in_leaf, ana_stand_in, SELECT_WORD_IN_LEAF,
    SELECT_PHRASE_IN_LEAF, HALVED_AS_DELETION, SPLIT_SHARED_INDICATOR, select_word_in_leaf,
    select_phrase_in_leaf, SELECTOR_AS_CUT, selector_as_cut, halved_as_deletion, TRIM_AS_SELECTION,
    trims_as_selection, split_shared_indicators, TRUNC_IN_LEAF, CUT_NOTE_LEAF, OWN_IND_IN_LEAF,
    trunc_in_leaf, own_ind_in_leaf, DOUBLED_APOSTROPHE, doubled_apostrophe, REPEAT_IN_LEAF, REPEAT_FORM,
    HALF_IN_LEAF, SELECT_IND_ENDS_LEAF, BEHEAD_IN_LEAF, repeat_in_leaf, half_in_leaf, select_ind_ends_leaf,
    SPLIT_WORD_LEAVES, MOVE_NOTE_LEAF, FIRST_SIBLING_LEAVES, HIDDEN_IND_ABOVE, DELETION_NO_CUT,
    INITIALS_IN_LEAF, split_word_leaves, move_note_leaf, PRE_REVERSED_LEAF, pre_reversed_leaf,
    first_sibling_leaves, deletion_no_cut, initials_in_leaf, hidden_ind_above, NESTED_SAME_OP,
    MIDDLE_SIBLING_LEAF, DEL_ONE_PIECE, ANA_IS_MOVE, nested_same_op, middle_sibling_leaf, del_one_piece,
    ana_is_move, DEL_AS_MOVE, del_as_move, behead_in_leaf, cut_note_leaf, ANA_LONE_EDGE, ANA_LITERAL_EDGE,
    DEL_WRAPS_CHARADE, ana_lone_edge, ana_literal_edge, del_wraps_charade, ana_double_indicator,
)

# Words that join the pieces of a charade and do nothing else.
CHARADE_GLUE = frozenset("then after next before following plus beside alongside by over on".split())


def _old_roles(old, words):
    """For each word in `words`, how the annotation `old` used it, as a phrase for
    the dropped_words message: "leaf 'x y'", "indicator on charade", "definition"."""
    roles = {w: [] for w in words}
    for n in _walk((old or {}).get("wordplay")):
        if "op" not in n:
            for w in words & _clue_words(n.get("words")):
                roles[w].append(f"in leaf [{n.get('words')}]")
        for i in n.get("indicators") or []:
            text = i.get("text") if isinstance(i, dict) else i
            for w in words & _clue_words(text):
                roles[w].append(f"in the {n.get('op')} indicator '{text}'")
    for d in (old or {}).get("definitions") or []:
        for w in words & _clue_words(d.get("text")):
            roles[w].append("in the definition")
    return {w: "; ".join(dict.fromkeys(r)) or "in the old wordplay" for w, r in roles.items()}


def forgiven_dropped_words(old, new, clue):
    """The clue words a redo `new` of the annotated clue `old` may leave out of every
    leaf, indicator and definition: link words, which the stored annotation never
    carries (annotation.view() derives them as the clue's uncovered gaps, and the
    schema refuses a stored `linkWords`). They are the connectives ("for", "to", "and")
    and any other measured link word that only an old LEAF held ("use", "one", "once":
    the new tree gives the same letters without it). A word the old tree used as an
    indicator ("displayed") is not forgiven unless it is a connective.
    dropped_words refused ~1,200 redo lines in 48h (576 sessions), and the earlier fix,
    adding the word to the new `linkWords`, was itself refused by the schema (284
    sessions; the model's own `linkWords` is stripped as derived)."""
    lost = (_accounted_words(old) - _accounted_words(new)) & _clue_words(clue)
    # Words the old tree made an op work with (any indicator but a charade's, which is glue:
    # "then", "after", "carrying"; or a definition's indicator) stay refused. A leaf word,
    # a charade's glue word or a word of the old definition that the new tree narrowed away
    # is a link word now, when it can stand for an equals sign (audit 10-20: 31 of 171
    # dropped words after the earlier fix were charade glue or a narrowed definition).
    hard = set()
    for n in _walk(old.get("wordplay")):
        for i in n.get("indicators") or []:
            words = _clue_words(i.get("text") if isinstance(i, dict) else i)
            hard |= words - CHARADE_GLUE if n.get("op") == "charade" else words
    for d in old.get("definitions") or []:
        for i in d.get("indicators") or []:
            hard |= _clue_words(i.get("text") if isinstance(i, dict) else i)
    return lost & (CONNECTIVE_WORDS | (_accounted_words(old) - hard)) & link_vocabulary()


def redo_lost_words(old, new, clue):
    """The clue words the dropped_words gate refuses a redo `new` of `old` for losing."""
    lost = (_accounted_words(old) - _accounted_words(new)) & _clue_words(clue)
    # A connective only a leaf of the old tree held (an unchecked "with" leaf
    # the re-annotation exists to remove) may go; as an indicator, definition
    # or link word it still has to stay.
    lost -= CONNECTIVE_WORDS - _accounted_words(old, leaves="real")
    lost -= forgiven_dropped_words(old, new, clue)
    return lost


def carry_old_indicators(old, new, clue):
    """`new` with each indicator the redo cut short given back its full text from `old`.
    Audit 10-21: most dropped_words refusals were a model trimming a multi-word indicator
    to its head ("after leaving" -> "leaving", "worn by" -> "worn", "Nameless" -> "less")
    and the gate then refusing the words trimmed off. When a new indicator's span sits
    inside an old indicator's span (same clue text, no other span of the new tree in the
    way) and that old indicator holds a word the redo would lose, the new indicator takes
    the old one's text and position. The gate still judges the result, so nothing a redo
    really drops is carried. `new` back as it was when nothing applies."""
    lost = redo_lost_words(old or {}, new or {}, clue)
    wp = (new or {}).get("wordplay")
    if not lost or not isinstance(wp, dict) or not (old or {}).get("wordplay"):
        return new
    olds = [i for n in _walk(old["wordplay"]) for i in n.get("indicators") or []
            if isinstance(i, dict) and isinstance(i.get("at"), int) and i.get("text")
            and clue[i["at"]:i["at"] + len(i["text"])].lower() == i["text"].lower()
            and lost & _clue_words(i["text"])]
    if not olds:
        return new
    wp = copy.deepcopy(wp)

    def spans(skip):
        out = [(d["at"], d["at"] + len(d["text"])) for d in (new.get("definitions") or [])
               if isinstance(d.get("at"), int) and d.get("text")]
        for n in _walk(wp):
            for s in [n] if "op" not in n else n.get("indicators") or []:
                text = s.get("words") if "op" not in n else s.get("text")
                if isinstance(s, dict) and s is not skip and isinstance(s.get("at"), int) and text:
                    out.append((s["at"], s["at"] + len(text)))
        return out

    changed = False
    for n in _walk(wp):
        for ind in n.get("indicators") or []:
            if not (isinstance(ind, dict) and isinstance(ind.get("at"), int) and ind.get("text")):
                continue
            a, b = ind["at"], ind["at"] + len(ind["text"])
            for o in olds:
                oa, ob = o["at"], o["at"] + len(o["text"])
                if oa <= a and b <= ob and (oa, ob) != (a, b) \
                        and not any(s < ob and oa < e for s, e in spans(ind)):
                    ind["text"], ind["at"] = clue[oa:ob], oa
                    changed = True
                    break
    return {**new, "wordplay": wp} if changed else new


def redo_keep_words(old, clue):
    """The words a redo of `old` must keep, in clue order: what the gate refuses
    when the new annotation holds none of them. Shown to the redo up front."""
    lost = redo_lost_words(old or {}, {}, clue)
    seen = []
    for w in re.findall(r"[a-z]+", re.sub(r"<[^>]*>|\([^)]*\)", " ", (clue or "").lower())):
        if w in lost and w not in seen:
            seen.append(w)
    return seen


def redo_regressions(old, new, clue):
    """Ways a redo `new` of an already-annotated clue gives up what the annotation
    `old` on file had, as "kind: what" strings; [] when it gives up nothing. The
    shape rules only judge the new tree, so a rewrite that cut the problem leaf,
    nulled the wordplay, flattened it or dropped Spooner would pass them
    (timesjumbo-1784 6d, 10-17: the redo dropped "displayed, in"):
      - no_tree: a tree where there was one is not replaced by none (a double
        definition covering every clue word is not a loss);
      - lost_spoonerism: a Spooner clue keeps its spoonerism;
      - dropped_words: a clue word in a leaf or indicator of the old tree stays in
        a leaf, indicator, definition or link word of the new one;
      - downgraded: a real tree is not replaced by a bare `cryptic` op."""
    old, new = old or {}, new or {}
    out = []
    wp = new.get("wordplay")
    if not wp or not (wp.get("op") or wp.get("words")):
        if old.get("wordplay"):
            defs = new.get("definitions") or []
            if not (len(defs) >= 2 and _clue_words(clue) <= _accounted_words(new)):
                out.append("no_tree: the new annotation has no wordplay tree where the old one had one")
            return out
    elif "spooner" in (clue or "").lower() and not any(n.get("op") == "spoonerism" for n in _walk(wp)):
        out.append("lost_spoonerism: the clue names Spooner and the tree has no spoonerism op")
    if old.get("wordplay"):
        lost = redo_lost_words(old, new, clue)
        if lost:
            roles = _old_roles(old, lost)
            out.append("dropped_words: " + ", ".join(f"{w} ({roles[w]})" for w in sorted(lost))
                       + " are in no leaf, indicator or definition of the new annotation. Write each back "
                       "where it did work: inside a leaf `[words]` of `wp`, as the `<indicator>` of an op, "
                       "or in `def`. Do not add `linkWords`: it is worked out from `wp` and is dropped "
                       "before the check, so it changes nothing here")
        old_wp = old["wordplay"]
        if wp and wp.get("op") == "cryptic" and old_wp.get("op") not in (None, "cryptic"):
            out.append("downgraded: the old wordplay was a real tree and the new one is a bare cryptic op")
    return out


def lesson_warnings(tag, ann, held):
    """The findings tools/lesson_checks.py reads off a clue and its answer."""
    clue = ((held.get("clue") or {}).get("text")) or ""
    answer = held.get("solution") or ""
    out = []
    if len(held.get("group") or []) > 1:
        return out
    if how := lesson_checks.dd_misses_wordplay(ann, clue, answer):
        out.append(f"{tag}: {lesson_checks.DD_MISSES_WORDPLAY} ({how}): parse it, or keep one "
                   f"definition and the wordplay")
    if said := lesson_checks.spelling_unsaid(ann, answer, (held.get("clue") or {}).get("enumeration")):
        out.append(f"{tag}: {lesson_checks.SPELLING_UNSAID}: set `spelling` to {said!r}")
    return out


def shape_warnings(tag, ann, clue=None, answer=None):
    """The findings for one annotation's tree shape, each a ratchet marker."""
    tree = ann.get("wordplay")
    out = []
    if k := charade_in_charade(tree):
        out.append(f"{tag}: {k} {CHARADE_IN_CHARADE}: join the pieces in one charade")
    if k := unindicated_ops(tree):
        bare = sorted({n.get("op") for n in _walk(tree) if n.get("op") in NEEDS_INDICATOR
                       and not n.get("unchecked") and not n.get("indicators")})
        out.append(f"{tag}: {k} {NO_INDICATOR}(s) ({', '.join(bare)}): name the indicator word on the op, "
                   f"or the op is not in the clue")
    if k := cdef_repeats(tree):
        out.append(f"{tag}: {k} extra leaf(s): {CDEF_REPEAT}; write wp as ONE leaf, "
                   f"cd([the clue words once]), with one note on it")
    if k := bad_arity(tree):
        out.append(f"{tag}: {k} {STORED_ARITY}")
    if k := span_overlaps(tree):
        out.append(f"{tag}: {k} {SPAN_OVERLAP}: {span_overlap_text(tree)}. A clue word does one job: write it in only "
                   f"one of the two, and take the other's letters or instruction from other clue words")
    if k := in_definition(ann):
        out.append(f"{tag}: {k} {IN_DEFINITION}: the definition and the wordplay do not share words "
                   f"unless the clue is &lit. Often the definition is drawn too wide: an "
                   f"article (\"a\", \"the\") or link word the wordplay uses belongs outside it "
                   f"(def \"little instrument\", not \"a little instrument\"). If one clue word "
                   f"is split (\"stopcock\": STOP = BAN in the wordplay, \"cock\" the definition) "
                   f"keep the leaf on the whole word and put the definition on only its "
                   f"part, \"at\" pointing inside the word")
    if k := leaf_folds(tree):
        out.append(f"{tag}: {k} {LEAF_FOLD}: a selection, deletion or hidden word is an op, "
                   f"not a leaf")
    if k := repeated_selections(tree):
        out.append(f"{tag}: {k} {REPEATED_SELECTION}: one selection over a multi-word leaf")
    if single_leaf(tree):
        out.append(f"{tag}: {SINGLE_LEAF}: a synonym for the answer is no wordplay; parse it, "
                   f"or it is a cryptic or double definition. Write exactly one: (1) a mechanism: the clue words that "
                   f"are not the definition split into pieces (charade/ins/ana/hid/rev...), each piece "
                   f"a leaf with its own clue words; (2) a double definition: two `def`s covering "
                   f"the whole clue and NO `wp`; (3) a cryptic definition: one `def` over the whole "
                   f"clue and NO `wp`")
    if k := bare_in_charade(tree, ann):
        out.append(f"{tag}: {k} {BARE_IN_CHARADE}: put the clue word that supplies them in a leaf")
    if k := anagram_of_container(tree):
        out.append(f"{tag}: {k} {ANAGRAM_OF_CONTAINER}: ins(outer, ana(...)) puts the anagram inside")
    if k := arity_ins(tree):
        out.append(f"{tag}: {k} {ARITY_INS}: ins(outer, inner) holds one in the other")
    if k := arity_other(tree):
        out.append(f"{tag}: {k} {ARITY_OTHER}: write the step as an expression the evaluator takes")
    if k := del_single(tree):
        out.append(f"{tag}: {k} {DEL_SINGLE}: del(whole, removed)")
    if k := ind_in_leaf(tree, clue):
        out.append(f"{tag}: {k} {IND_IN_LEAF}: the leaf holds only the words that give its letters")
    if k := scrambled_leaves(tree):
        out.append(f"{tag}: {k} {SCRAMBLED_LEAF}: a leaf gives its own letters in order; "
                   f"only an anagram op scrambles")
    if k := folded_indicators(tree):
        out.append(f"{tag}: {k} {IND_FOLDED}: an indicator belongs on its op, and the leaf holds "
                   f"only the words that give its letters")
    if k := fake_parts(tree):
        out.append(f"{tag}: {k} {FAKE_PARTS}: a substitution swaps letters the clue names; "
                   f"do not invent pieces to reach three parts")
    if k := padding_leaves(tree):
        out.append(f"{tag}: {k} {PADDING_LEAF}: say what the words give, or take them out of the "
                   f"wordplay")
    if k := nested_containers(tree, answer):
        out.append(f"{tag}: {k} {NESTED_CONTAINER}: pieces that go in the same holder together are a "
                   f"charade (ins(AB E, U + S)); a piece in a piece in a third is "
                   f"ins(third, ins(second, first))")
    if k := anagram_synonyms(tree, {**(ann or {}), "_answer": answer}, clue):
        out.append(f"{tag}: {k} {ANAGRAM_SYNONYM}: only the clue's own words are scrambled; "
                   f"the synonym joins the anagram's result in a charade")
    if k := misplaced_indicators(tree):
        out.append(f"{tag}: {k} {MISPLACED_INDICATOR}: file each indicator on the op it acts on "
                   f"(a reversal's on rev<...>, a selection's on first/last<...>), not on the charade. "
                   f"If no op in the clue does what the word says, it is only a link: write it inside "
                   f"the [words] of the leaf it touches ([Company introducing]CO), and if it really "
                   f"inserts, build ins<word>(held, holder) around the pieces it joins")
    if k := bare_initials(tree):
        out.append(f"{tag}: {k} {BARE_INITIAL}: a first letter is picked by an op (first<...>(word)), "
                   f"not given by a leaf")
    if k := deletion_scope(tree):
        out.append(f"{tag}: {k} {DELETION_SCOPE}: an end-cutting indicator acts on the one piece it "
                   f"follows, del(piece, letters) inside the charade")
    if k := wrong_role_indicators(tree):
        out.append(f"{tag}: {k} {WRONG_ROLE}: put each indicator on the op it signals (a reversal "
                   f"word on rev<...>, a container word on ins<...>, an anagram word on ana<...>)")
    if k := deletion_inside_component(tree, clue, answer):
        out.append(f"{tag}: {k} {DELETION_INSIDE}: the indicator acts on the one piece it sits by, "
                   f"del(piece, letters) inside the charade; add no piece only to remove it")
    if k := container_inside_component(tree, answer):
        out.append(f"{tag}: {k} {CONTAINER_INSIDE}: the indicator acts on the one piece it sits by, "
                   f"ins(piece, letters) inside the charade, not ins over the whole charade")
    if k := unindicated_uncovered(tree):
        out.append(f"{tag}: {k} {UNINDICATED_BARE}: give each op its own indicator word from the clue; "
                   f"one indicator covers one op (a pair of first/last/middle picks may share one)")
    if k := shared_indicators(tree, clue):
        out.append(f"{tag}: {k} {SHARED_INDICATOR}: a clue word does one job; name the indicator "
                   f"once and the leaf's letters from other words")
    if k := half_leaves(tree):
        out.append(f"{tag}: {k} {HALF_LEAF}: a half of a word is picked by an op "
                   f"(first/last of its letters), once per word")
    if k := deletion_scattered(tree):
        out.append(f"{tag}: {k} {DELETION_SCATTERED}: 'half' acts on one word; write a deletion "
                   f"per word, del(word, its half)")
    if k := reverse_phrase(tree):
        out.append(f"{tag}: {k} {REVERSE_PHRASE}: say what the words do (an anagram, a hidden "
                   f"word, a charade), not a reading of the whole phrase; keep reverse([...], \"reading\") "
                   f"only when the reading has a word that is the clue's last words rearranged "
                   f"(\"What makes pets\" -> STEP); if nothing in the phrase builds the answer, "
                   f"write cd([words]) with no reverse")
    if k := deletion_scope_answer(tree, answer):
        out.append(f"{tag}: {k} {DELETION_SCOPE_ANSWER}: the indicator acts on the one piece it sits "
                   f"by, so delete inside the charade, del(piece, letters)")
    if k := double_indicators(tree):
        out.append(f"{tag}: {k} {DOUBLE_INDICATOR}: one op per indicator; write two ops "
                   f"(two reversals, two deletions), and a hidden word needs no selection under it")
    if k := moved_letters(tree):
        out.append(f"{tag}: {k} {MOVED_LETTER}: write move<indicator>(fodder, MOVED), e.g. "
                   f"move<dropping>([England]ALBION, [ball]O)")
    if k := pool_gaps(tree, clue):
        out.append(f"{tag}: {k} {POOL_GAP}: the fodder is the words together under the indicator; "
                   f"a piece the clue places elsewhere belongs to the charade or insertion, not the pool; "
                   f"a piece whose words sit between the fodder words is fodder: list the pieces in clue order inside the one ana()")
    if k := midword_leaves(tree, clue):
        out.append(f"{tag}: {k} {MIDWORD_LEAF}: a cut is an op (del/first/last), not a leaf that "
                   f"gives part of a word")
    if k := traded_indicators(tree):
        out.append(f"{tag}: {k} {TRADED_INDICATOR}: file each indicator word on the op of its own kind")
    if k := charade_out_of_order(tree, clue):
        out.append(f"{tag}: {k} {CHARADE_ORDER}: keep the clue's order, or reverse the piece that moves")
    if k := reversal_split(tree, clue):
        out.append(f"{tag}: {k} {REVERSAL_SPLIT}: it reverses the one piece it sits by")
    if k := reversed_charade_order(tree, clue):
        out.append(f"{tag}: {k} {REVERSED_CHARADE_ORDER}: keep the clue's order and reverse only the piece the indicator sits by")
    if k := cut_in_leaf(tree):
        out.append(f"{tag}: {k} {CUT_IN_LEAF}: the cut word is an op's indicator, the leaf holds the rest")
    for fn, label, hint in (
            (lambda: ana_select_edge(tree, answer), ANA_SELECT_EDGE, "set the pick beside the anagram in a charade"),
            (lambda: non_word_operands(tree), NON_WORD_OPERAND, "give the op one word's letters; join the synonyms in a charade"),
            (lambda: del_wide(tree, clue), DEL_WIDE, "the piece before the indicator is the one cut; the others belong to the parent"),
            (lambda: ind_leaf_overlap(tree, clue), IND_LEAF_OVERLAP, "a clue word does one job"),
            (lambda: ana_double_indicator(tree), ANA_DOUBLE_IND, "one op, one indicator"),
            (lambda: del_straddle(tree), DEL_STRADDLE, "cut inside the one piece the word acts on"),
            (lambda: swapped_pair(tree), SWAPPED_PAIR, "file each indicator on the op of its own kind"),
            (lambda: link_in_leaf(tree), LINK_IN_LEAF, "the link word is the clue's join, not the leaf's"),
            (lambda: ana_stand_in(tree), ANA_STAND_IN, "spell the stand-in beside the anagram"),
            (lambda: select_word_in_leaf(tree), SELECT_WORD_IN_LEAF, "the leaf holds only the words that give its letters"),
            (lambda: select_phrase_in_leaf(tree), SELECT_PHRASE_IN_LEAF, "the selection is an op with its own indicator"),
            (lambda: halved_as_deletion(tree), HALVED_AS_DELETION, "keep half the word with a halving selection"),
            (lambda: trims_as_selection(tree, answer), TRIM_AS_SELECTION,
             "cut the synonym with a deletion, del<without limits>([jumps]BOUNCES, B, S)"),
            (lambda: split_shared_indicators(tree), SPLIT_SHARED_INDICATOR, "one indicator, one multi-part op"),
            (lambda: trunc_in_leaf(tree), TRUNC_IN_LEAF, "the truncation word is a deletion's indicator"),
            (lambda: cut_note_leaf(tree), CUT_NOTE_LEAF, "give the real word and cut it with a deletion op"),
            (lambda: selector_as_cut(tree), SELECTOR_AS_CUT, "the removed letter is a first/last pick with its own indicator"),
            (lambda: ana_lone_edge(tree, answer, clue), ANA_LONE_EDGE, "set the letter beside the anagram in a charade"),
            (lambda: ana_literal_edge(tree, answer, clue), ANA_LITERAL_EDGE, "set the word beside the anagram in a charade"),
            (lambda: del_wraps_charade(tree, clue), DEL_WRAPS_CHARADE, "cut inside the one piece the word acts on"),
            (lambda: repeat_in_leaf(tree), REPEAT_IN_LEAF, REPEAT_FORM),
            (lambda: split_word_leaves(tree), SPLIT_WORD_LEAVES, "the word is the container's outer piece, one leaf"),
            (lambda: move_note_leaf(tree), MOVE_NOTE_LEAF, "write move<indicator>(fodder, MOVED)"),
            (lambda: first_sibling_leaves(tree), FIRST_SIBLING_LEAVES, "one first-letters indicator over the list is one multi-part op"),
            (lambda: hidden_ind_above(tree), HIDDEN_IND_ABOVE, "the opening marker is the hidden op's indicator"),
            (lambda: deletion_no_cut(tree), DELETION_NO_CUT, "give the whole word and cut it with a deletion"),
            (lambda: initials_in_leaf(tree), INITIALS_IN_LEAF, "the pick is first<indicator> over those words"),
            (lambda: half_in_leaf(tree), HALF_IN_LEAF, "keep half the word with a halving selection"),
            (lambda: select_ind_ends_leaf(tree), SELECT_IND_ENDS_LEAF, "the leaf holds only the words that give its letters"),
            (lambda: nested_same_op(tree), NESTED_SAME_OP, "one indicator, one multi-part op"),
            (lambda: middle_sibling_leaf(tree), MIDDLE_SIBLING_LEAF, "one middle indicator over the list is one multi-part op"),
            (lambda: del_one_piece(tree), DEL_ONE_PIECE, "put the deletion on the piece it cuts, inside the charade"),
            (lambda: ana_is_move(tree, answer), ANA_IS_MOVE, "write move<indicator>(fodder, MOVED)"),
            (lambda: del_as_move(tree), DEL_AS_MOVE, "write move<indicator>(fodder, MOVED)"),
            (lambda: behead_in_leaf(tree), BEHEAD_IN_LEAF, "the cut is a deletion with its own indicator"),
            (lambda: doubled_apostrophe(tree), DOUBLED_APOSTROPHE, "write the word with the one apostrophe the clue has"),
            (lambda: own_ind_in_leaf(tree), OWN_IND_IN_LEAF, "the leaf holds only the words that give its letters"),
            (lambda: pre_reversed_leaf(tree), PRE_REVERSED_LEAF,
             "give the word forwards and put the reversal on the piece it turns, SURF + rev<looking up>([link]TIE)")):
        if k := fn():
            out.append(f"{tag}: {k} {label}: {hint}")
    return out


#: Ops that rearrange, cut or reshape letters, so the letters they give are a step
#: a solver cannot see from the leaves alone. A charade only joins.
TRANSFORMING_OPS = frozenset({"anagram", "reversal", "container", "deletion", "substitution",
                              "cycling", "move", "hidden", "homophone", "spoonerism", "composite",
                              "palindrome", *wordplay.SELECT})
#: Indicators that must stand against what they work on.
ADJACENT_OPS = ("anagram", "reversal", "hidden")
WALKTHROUGH_GAP = "walkthrough does not follow the wordplay"
INDICATOR_APART = "indicator not next to its fodder"


def _stem_match(a, b):
    """True when two lower-case words are one word inflected (wild/wildly, get/getting)."""
    if a == b:
        return True
    p = len(os.path.commonprefix([a, b]))
    return p >= 3 and p >= min(len(a), len(b)) - 1 and abs(len(a) - len(b)) <= 4


_PHRASE_FILLER = frozenset({"of", "the", "a", "an", "in", "from", "to", "at", "by", "for", "one"})
_FIRST_WORDS = frozenset({"first", "initial", "initially", "opening", "opener", "leader", "leading",
                          "lead", "head", "start", "starts", "beginning", "top"})
_LAST_WORDS = frozenset({"last", "final", "finally", "closing", "ending", "end", "ends", "tail",
                         "bottom", "finish", "terminal"})


def _mentions_phrase(walk_words, phrase, op=None):
    """The phrase's words, inflections allowed, appear in order and adjacent in the walkthrough.

    Two paraphrases are no gap: little words dropped from either side ("first of"
    read as "the first L": the indicator's filler "of" is not what the walkthrough
    must repeat), and for a first/last selection a walkthrough that says its
    position in other words (leader / first / initial / opening, or last / final /
    closing / end) than the indicator's own."""
    want = words_of(phrase)
    n = len(want)
    if not n:
        return False
    if any(all(_stem_match(v, w) for v, w in zip(walk_words[i:i + n], want))
           for i in range(len(walk_words) - n + 1)):
        return True
    core = [w for w in want if w not in _PHRASE_FILLER]
    walk = [w for w in walk_words if w not in _PHRASE_FILLER]
    m = len(core)
    if m and m < n and any(all(_stem_match(v, w) for v, w in zip(walk[i:i + m], core))
                           for i in range(len(walk) - m + 1)):
        return True
    for group in (_FIRST_WORDS, _LAST_WORDS):
        if op in ("first", "last") and set(core) & group and group & set(walk_words):
            return True
    return False


def walkthrough_gaps(tree, answer, walkthrough):
    """What the walkthrough leaves out of the wordplay tree: the text of each
    indicator it never names, and the letters each transforming op gives (bar
    the answer itself, and a single letter) that it never shows. `tree` must
    give `answer` (wordplay.evaluate). Returns [(kind, text)], kind "indicator"
    or "gives"."""
    got = wordplay.evaluate(tree, answer)
    walk_words = words_of(walkthrough)
    # Letters as the walkthrough writes them: a word, or a run of capitals and
    # hyphens or spaces ("I-N-A-T"), with the separators dropped.
    shown = {w.upper() for w in re.findall(r"[^\W\d_]+", walkthrough or "")}
    shown |= {letters(w) for w in re.findall(r"[A-Z](?:[- ][A-Z])+", walkthrough or "")}
    whole = letters(answer)
    out = []
    for node in _walk(tree):
        if node.get("unchecked"):
            continue
        for ind in node.get("indicators") or []:
            if not _mentions_phrase(walk_words, ind["text"], node.get("op")):
                out.append(("indicator", ind["text"]))
        g = got.get(id(node))
        if node.get("op") in TRANSFORMING_OPS and g and len(g) > 1 and g != whole:
            if g not in {letters(w) for w in shown}:
                out.append(("gives", g))
    return out


def _span_of(node):
    """(start, end) in the clue of every located leaf and indicator under `node`, or None."""
    spans = []
    for n in _walk(node):
        if "words" in n and "at" in n:
            spans.append((n["at"], n["at"] + len(n["words"])))
        spans += [(i["at"], i["at"] + len(i["text"])) for i in n.get("indicators") or [] if "at" in i]
    return (min(s for s, _ in spans), max(e for _, e in spans)) if spans else None


def apart_indicators(tree, clue):
    """[(indicator text, content words in the gap)] for each anagram, reversal or
    hidden indicator with a word between it and what it works on that is not a
    link word. The fodder is the located leaves under the op; an indicator among
    them is touching."""
    allowed = link_vocabulary()
    out = []
    for node in _walk(tree):
        if node.get("op") not in ADJACENT_OPS or node.get("unchecked"):
            continue
        fodder = [_span_of(p) for p in node.get("parts") or []]
        fodder = [f for f in fodder if f]
        if not fodder:
            continue
        fs, fe = min(s for s, _ in fodder), max(e for _, e in fodder)
        for ind in node.get("indicators") or []:
            if "at" not in ind:
                continue
            i0, i1 = ind["at"], ind["at"] + len(ind["text"])
            gap = clue[fe:i0] if i0 >= fe else clue[i1:fs] if i1 <= fs else ""
            bad = [w for w in words_of(gap) if w not in allowed]
            if bad:
                out.append((ind["text"], bad))
    return out


def follow_warnings(tag, ann, held, puzzle):
    """Findings a solver would hit following the hint: a walkthrough that never
    names an indicator or an intermediate result (WALKTHROUGH_GAP), and an
    anagram, reversal or hidden indicator with content words between it and its
    fodder (INDICATOR_APART). Findings only: no ratchet field counts them."""
    tree = ann.get("wordplay")
    clue = ((held.get("clue") or {}).get("text")) or ""
    if not tree or not clue:
        return []
    out = []
    for ind, bad in apart_indicators(tree, clue):
        out.append(f"{tag}: {INDICATOR_APART}: {ind!r} is separated from what it works on by "
                   f"{', '.join(bad)}; an indicator operates on what it touches")
    walk = (ann.get("explanation") or {}).get("walkthrough")
    # The walkthrough rung lists every op of the tree itself (app.js wordplaySteps:
    # each indicator marked, each intermediate result derived), so its prose need not
    # repeat them. Only a blog-derived ladder shows no such list, and there the prose is all
    # the solver has.
    if walk and ann.get("fromBlog"):
        alt = held.get("alteration")
        try:
            gaps = walkthrough_gaps(tree, alt["from"] if isinstance(alt, dict) and alt.get("from")
                                    else annotation.display_answer(held, puzzle), walk)
        except (wordplay.WordplayError, KeyError, TypeError, ValueError):
            gaps = []   # a tree that does not give its answer is already an error
        if gaps:
            inds = [t for k, t in gaps if k == "indicator"]
            mids = [t for k, t in gaps if k == "gives"]
            said = ([f"names the indicator{'s' if len(inds) > 1 else ''} " + ", ".join(map(repr, inds))]
                    if inds else []) + (["shows the intermediate letters " + ", ".join(mids)] if mids else [])
            out.append(f"{tag}: {WALKTHROUGH_GAP}: it never " + " or ".join(said)
                       + ". A solver must be able to follow every step from the walkthrough")
    return out