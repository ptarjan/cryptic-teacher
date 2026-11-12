#!/usr/bin/env python3
"""Validate clue annotations in puzzles/<series>/<year>/*.json.

Checks, for every annotated entry:
  - annotation has type, definitions, answer, blocks
  - `type` is an array of names from tools/data/clue_types.json (check_type)
  - answer letters match the grid solution (group-aware for linked entries)
  - each definition sits at its `at` in the clue (tools/definitions.py), every
    indicator and every linkWord is an exact substring of the clue, and every content word of the clue is claimed by one
    of those or by a block (check_coverage)
  - no link word overlaps an indicator or a definition, so an &lit has none
    (check_link_word_is_clear_of_other_marks)
  - each definition and the answer agree in inflection, unless the definition's
    `note` explains why they don't (check_part_of_speech)
  - assembly: "pieces" concatenate exactly to the answer letters, each of
    "anagrams" is a letter-for-letter anagram of its gives, and each of
    "reversals" reverses correctly
  - hidden answers actually occur in the clue's letters, and an answer that
    runs across a word break in the wordplay, or sits inside one word other
    than at the front, back or middle a deletion or selection keeps, is typed
    hidden_word unless a note calls it a coincidence (check_unmarked_hidden_word)
  - a linked answer's `group` sits on its leader alone, leader first, and its
    other lights carry no annotation (check_groups)

And checks that apply only to puzzles we WROTE (see is_authored):
  - every clue states its scene in explanation.surface, without crossword
    vocabulary or the answer (check_authored_surface)
  - a clue tagged as a pun names its word (check_authored_puns)
  - no block may have an empty `gives`: every word of an authored clue is
    definition, wordplay or joinery, never surface padding (check_two_pieces)
  - the walkthrough stays inside MAX_WALKTHROUGH_WORDS when the blocks already
    spell the answer out (check_walkthrough_budget)
  - every linkWord stands in for an equals sign (check_link_words_are_equivalences)
  - and does not secretly order the wordplay (check_link_word_is_not_an_order)
  - an anagram indicator touches its fodder (check_indicator_adjacency)
  - and is not made of the fodder's own letters (check_indicator_outside_fodder)
  - no indicator runs across a definition's edge (check_indicator_does_not_straddle_a_definition)
  - a reversal indicator points the way the entry runs (check_reversal_direction)

And checks that need the whole puzzle in hand:
  - at most MAX_CRYPTIC_DEFINITIONS clues typed cryptic_definition
  - a definition's words are not also its wordplay's letters
  - the blocks hand over exactly the answer's letters, take it apart the way
    `assembly.pieces` does, and are listed in the order the answer reads
  - a block that claims letters says why it gets them
  - every convention a block leans on is in the solver's glossary

Usage: python3 tools/validate_annotations.py [--unscoped] [--tighten] [puzzle-number ...]
       python3 tools/validate_annotations.py --explain [check-name]
With no arguments, validates every puzzle that has at least one annotation.
`--shard i/n` (the deploy runs 0/4 .. 3/4) does that for the puzzles whose id
hashes to i of n; the ratchet is per puzzle, so each shard enforces its own
slice and the backlog totals it prints are the slice's.
`--unscoped` runs the authored-only checks on published puzzles too — that is
the CALIBRATION harness, not a mode to ship in: a check that flags Araucaria is
a broken check, so every authored-only rule is measured across the annotated
published puzzles before it is trusted. Exits non-zero if any check
fails.
"""

import ast
import collections
import copy
import difflib
import functools
import itertools
import hashlib
import json
import multiprocessing
import os
import re
import subprocess
import sys
import time
import unicodedata
import validate_base  # FORCE_AUTHORED_CHECKS lives there
from pathlib import Path
import clue_types
import definitions  # where each definition sits; tools/definitions.py
import enumeration  # a clue's printed counts; tools/enumeration.py
import groups  # linked answers; tools/groups.py
import lesson_checks  # findings read off a second annotation run; tools/lesson_checks.py
import provenance  # where each puzzle came from; tools/provenance.py
import puzzle_schema  # tools/data/puzzle.schema.json
import wordplay  # tools/wordplay.py
import annotation  # the derived fields: view(), view_puzzle()
from annotation import assembly, explanation, whole_anagram, wordplay_letters
from fetch_puzzle import (  # one reader, one exemption
    blog_facts_for,
    clue_words,
    corrected_clue,
    has_words,
    leaders_named,
    load_source_table,
    read_puzzle_file,
    source_clue,
    SOURCE_CLUE_WRONG,
    withheld_clues,
)
from find_answer_leaks import _run, light_solutions, named, pieces_of, says  # one matcher, shared with the finder
from groups import entry_id
from hidden_messages import block_letters, check_preamble, letter_problems, message_problems
from puzzle_paths import (  # one glob, one id resolver
    puzzle_files,
    resolve_puzzle,
)


# ruff: noqa: F401
# The moved checks: every name that used to live here is still validate_annotations.X.
from validate_base import (
    ROOT, TYPE_NAMES, types_of, indicator_texts, check_type, is_authored, _load_words, WORDS, letters,
    _starts, _whole_word, words_of,
)
from validate_walkthrough import (
    MAX_CRYPTIC_DEFINITIONS, MAX_WALKTHROUGH_WORDS, WALKTHROUGH_PREAMBLE, WALKTHROUGH_EMPTY_CLOSER,
    check_two_pieces, check_walkthrough_opener, check_walkthrough_closer, check_walkthrough_budget,
    FILLER_WORDS, HEDGES, MISSING_FIELD_FIX, _QUOTED, walkthrough_hedges, BACKTRACKS, WALKTHROUGH_HARD_MAX,
    SURFACE_MAX, SURFACE_MIN_WORDS, SURFACE_OPTIONAL_TYPES, WORD_RE, check_surface, SURFACE_MECHANISM,
    check_authored_surface, check_authored_puns,
)
from validate_link import (
    CORE_LINKS, JOINTS_FILE, joints, link_vocabulary, check_link_words_are_equivalences, POSITIONAL_JOINERS,
    check_link_word_is_clear_of_other_marks, check_link_word_is_not_inside_a_block, link_adds_nothing,
    link_in_block_hints, place_fragments, check_indicator_does_not_straddle_a_definition,
    check_link_word_is_not_an_order,
)
from validate_anagram import (
    multiset_diff, SETTER_ERROR, SETTER_ERROR_LETTERS, setter_error_problems, check_anagram_has_fodder,
    check_anagram_letters, check_cryptic_definition_cap, blind_misses,
)
from validate_definition import (
    check_answer_matches_separators, DEFINITION_FIT_MAX, DEFINITION_FIT_HOW, check_definition_fit,
    DEFINITION_STOPWORDS, MAX_DEFINITION_REUSE, DEFINITION_REUSE_EXEMPT, LINKING_WORDS,
    _fragment_clear_of_definitions, check_definition_not_fodder,
)
from validate_blog import (
    BLOG_DISAGREE, BLOG_FIELDS, blog_kept, blog_file_hint, check_definition_against_blog,
    check_blocks_against_blog, BLOG_WORDPLAY, check_cryptic_definition_against_blog, TYPE_FAMILIES,
    type_families, check_type_against_blog,
)
from validate_indicator import (
    _letter_offsets, _fodder_spans, check_indicator_adjacency, check_anagram_fodder_from_clue,
    check_indicator_outside_fodder, EARLY_RUNG_FIELDS, clue_words_no_block_covers,
    check_no_answer_in_early_rungs, check_block_notes_dont_name_the_answer, INDICATOR_NOTE_HOW,
    INDICATOR_KEYS, check_indicators,
)
from validate_hidden import (
    HIDDEN_WORD_RE, hidden_runs, inside_runs, POSITIONAL_TYPES, trimmed_pieces, check_unmarked_hidden_word,
    check_reversal_direction,
)
from validate_sound import (
    SOUND_TYPES, _sound_over_step, plain_spoonerism, check_sound_names_its_source,
    check_sound_is_not_a_letter_swap,
)
from validate_features import (
    REFERENCE_RE, ENUMERATION_RE, expand_cross_references, spelled_numbers, check_coverage, is_word, NOT_PLURALS, is_plural,
    INVARIANT_PLURALS, NOT_GERUNDS, is_gerund, JOKE_KINDS, check_features, plain, check_part_of_speech,
)
from validate_answers import (
    DOUBTS, VARIANT_SPELLING, annotation_prose, variant_named, doubted_model_answers,
    check_model_answer_doubted, is_blank_clue, check_every_clue_is_annotated,
    check_cryptic_definition_blocks,
)
from validate_blocks import (
    UNBALANCED_TYPES, UNBALANCED_EXACT_TYPES, blocks_miss_letters, slipped_letters, missing_link_word_fix,
    MAX_SURPLUS_EDITS, surplus_letters_fix, check_blocks_account_for_answer, check_blocks_decompose,
    check_blocks_in_answer_order, BLOCK_NO_NOTE, check_blocks_carry_notes,
)
from validate_committed import (
    MARKUP_RE, CP1252_C1, C1_RE, verbatim_hint, respelt_words, skipped_words, is_pointer_text, check_groups,
    check_no_markup, text_errors, committed_entries, committed_top, check_theme_clue_unchanged,
    check_spelling_kept, OCR_MISREAD_EDITS, edit_distance, ocr_misread_edits, SCAN_READ, clue_row_problems,
    scan_read, check_clue_unchanged, check_clue_rows_held, letters_given_in,
    check_indicator_notes_name_no_block, TWO_END_LETTERS, check_no_two_end_letters, SELECT_NOUNS, SELECT_ADVERBS, _select_groups, SELECTOR_LEADS,
    SELECTOR_TAIL_WORDS, SELECTOR_TAIL, SELECTOR_ALONE, selector_in_block, check_selectors_are_indicators,
)
from validate_shape_base import (
    _walk, _OP_LEXICON, REPEAT_WORDS, ROLE_TYPES, indicator_role_key, _indicator_roles, _role_counts,
    _attested, _EXTRA_PAIRS, _known_pair, _POSITION_WORD, _owner_type, CUT_WORDS, _clue_words,
    CONNECTIVE_WORDS, _accounted_words,
)
from validate_shape_ops import (
    UNCHECKED_STEP, ANAGRAM_CHARADE, _stand_in_piece, _pulled_edges, anagram_edge_pieces, anagram_charades,
    CHARADE_IN_CHARADE, NO_INDICATOR, CDEF_REPEAT, STORED_ARITY, SPAN_OVERLAP, IN_DEFINITION, LEAF_FOLD,
    REPEATED_SELECTION, SINGLE_LEAF, BARE_IN_CHARADE, ANAGRAM_OF_CONTAINER, ARITY_INS, ARITY_OTHER,
    DEL_SINGLE, IND_IN_LEAF, SCRAMBLED_LEAF, NEEDS_INDICATOR, SHAPE_GRACE_UNTIL, SHAPE_GRACE_FIELDS,
    whole_rebus, _stored_arity, charade_in_charade, _bare_shape, _repeated_copies, _BOUNDARY_WORDS,
    _moved_letter_ops, _SUBSTITUTE_WORD, _CONTAINER_WORD, _self_signed_ops, _HOLDER_WORD,
    _self_holding_containers, _lone_implicit_op, _lone_bare_sound, _lone_bare_first, _leaf_words,
    _paired_ends, _indicator_inside_run, _picks_with_indicator, _outer_in_boundary_container,
    _chained_deletions, _substituting_containers, unindicated_ops, cdef_repeats, bad_arity, _claimed,
    span_overlaps, span_overlap_pairs, span_overlap_text, _with_places, in_definition, leaf_folds,
    repeated_selections, single_leaf, DEVICE_NOTE, bare_in_charade, anagram_of_container, _unchecked_ops,
    _spoon_swap_ok, step_verified, _verified_substitution, _verified_leaf, _SELECT_COMPOUND,
    unverified_unchecked, _strip_unchecked, _pool, _recomputes, arity_ins, arity_other, _not_a_rotation,
    _DEL_ALL, _SUB_LINKS, del_single, ind_in_leaf, scrambled_leaves,
)
from validate_shape_folds import (
    IND_FOLDED, FAKE_PARTS, PADDING_LEAF, FOLD_WIDE_WORDS, FOLD_MIN_USES, _indicator_lexicon,
    folded_indicators, fake_parts, padding_leaves, NESTED_CONTAINER, MISPLACED_INDICATOR,
    MISPLACED_MIN_USES, ORDERING_INDICATORS, EXAMPLE_MARKERS, POSITION_INDICATORS, SEPARATE_INSERTION,
    _separate_insertion, _flat_insert_reaches, nested_containers, ANAGRAM_SYNONYM, anagram_synonyms,
    _repeats_sibling, _phrase_letters, COUNT_WORDS, _doubled, _near_literal, MIDWORD_LEAF, _lexicon_letters,
    midword_leaves, _lone_stand_in, _loose_words, _stand_in, ROLE_MIN_USES, ROLE_OWNED, ROLE_OWN_MAX,
    ROLE_WEAK, ROLE_LINKS, _indicators_foreign, wrong_role_indicators, SELECTION_PHRASE,
    selection_phrase_elsewhere, EXTREMES_WORD, DELETION_LEAF_WORD, extremes_as_one_end, AMBIGUOUS_DELETION,
    NOT_BEFORE_DELETION, NOT_AFTER_DELETION, _deletion_word_in, _is_subsequence, _cut_evidence,
    folded_deletion_leaves, selection_of_one_letter, ROLE_SWAP_OWNED, ROLE_LOOSE_OWNED, ROLE_LOOSE_OWN_MAX,
    _swap_alike, reversal_of_anagram, _lacks_role, _positional_charade, misplaced_indicators,
)
from validate_shape_inside import (
    BARE_INITIAL, DELETION_SCOPE, WRONG_ROLE, CONTAINER_INSIDE, DELETION_INSIDE, UNINDICATED_BARE,
    SHARED_INDICATOR, HALF_LEAF, DELETION_SCATTERED, REVERSE_PHRASE, _abbreviation_pair, _word_leaves,
    BARE_INITIAL_MIN_LETTERS, _ORDINALS, _ACROSTIC_WORD, _acrostic_run, _position_word_cut,
    _split_word_leaf, bare_initials, _DEL_END, _DEL_HEAD, _DEL_MIDDLE, _DEL_HEART, _DEL_HALF,
    FUNCTION_PIECES, HEART_SLACK, deletion_inside_component, container_inside_component, _container_inside,
    deletion_scope, deletion_scope_answer, _SHARED_OK, unindicated_uncovered, SHARED_PAIR_GAP,
    _pair_adjacent, _FOLD_AFFIX, _FOLD_PHRASE, _NOPOSS, _NOT_COMPOUND, _FOLD_POSS, _folded_signal,
    _list_run, _compound_indicator_keys, _anagram_indicator_letters, shared_indicators, half_leaves,
    deletion_scattered, reverse_phrase, _reading_reuses_words,
)
from validate_shape_order import (
    _ONE_IND_OPS, DELETION_SCOPE_ANSWER, DOUBLE_INDICATOR, MOVED_LETTER, moved_letters, _plain_cut,
    _sibling_gives, _LEAF_CUT_NOTE, _leaf_cut_put_back, _ind_adjacent, _OWN_DELETION_WORD, _own_word,
    TRADED_INDICATOR, traded_indicators, double_indicators, _subtree_spans, POOL_GAP, pool_gaps, _located,
    _extent, CHARADE_ORDER, ORDER_FLIPPERS, charade_out_of_order, REVERSAL_SPLIT, reversal_split,
    REVERSED_CHARADE_ORDER, reversed_charade_order, CUT_IN_LEAF, CUT_SUFFIXED, _cut_phrase, cut_in_leaf,
)
from validate_shape_leaf import (
    ANA_SELECT_EDGE, NON_WORD_OPERAND, DEL_WIDE, IND_LEAF_OVERLAP, ANA_DOUBLE_IND, DEL_STRADDLE,
    _stand_in_or_select, ana_select_edge, _select_edge_swapped, del_straddle, non_word_operands, del_wide,
    ind_leaf_overlap, SWAPPED_PAIR, LINK_IN_LEAF, _LEAF_LINKS, ANA_STAND_IN, _role_share, swapped_pair,
    link_in_leaf, _initial_abbreviation, ana_stand_in, SELECT_WORD_IN_LEAF, SELECT_PHRASE_IN_LEAF,
    HALVED_AS_DELETION, SPLIT_SHARED_INDICATOR, _NOT_A_HALVING, _HALVING, select_word_in_leaf,
    select_phrase_in_leaf, SELECTOR_AS_CUT, selector_as_cut, halved_as_deletion, TRIM_AS_SELECTION,
    trims_as_selection, split_shared_indicators, TRUNC_IN_LEAF, CUT_NOTE_LEAF, OWN_IND_IN_LEAF,
    _TRUNC_WORDS, _BRIEFLY_CUT, _LETTER_REMOVED, _TRUNC_PHRASES, _CUT_NOTE, _CUT_LETTER, _plain_leaves,
    trunc_in_leaf, own_ind_in_leaf, DOUBLED_APOSTROPHE, DOUBLED_APOSTROPHE_RE, doubled_apostrophe,
    REPEAT_IN_LEAF, REPEAT_FORM, HALF_IN_LEAF, SELECT_IND_ENDS_LEAF, BEHEAD_IN_LEAF, _REPEAT_WORDS,
    _STUTTER_WORDS, _BEHEAD, repeat_in_leaf, _REPEAT_PHRASE, _run_values, _half_of_synonym, half_in_leaf,
    select_ind_ends_leaf, SPLIT_WORD_LEAVES, MOVE_NOTE_LEAF, FIRST_SIBLING_LEAVES, HIDDEN_IND_ABOVE,
    DELETION_NO_CUT, INITIALS_IN_LEAF, _MOVE_NOTE, _INITIAL_NOTE, _HIDDEN_OPENERS, split_word_leaves,
    move_note_leaf, PRE_REVERSED_LEAF, _TURN_NOTE, _LETTER_OPS, pre_reversed_leaf, first_sibling_leaves,
    deletion_no_cut, _POSITION_IND, _INITIALS_SKIP, initials_in_leaf, hidden_ind_above, NESTED_SAME_OP,
    MIDDLE_SIBLING_LEAF, DEL_ONE_PIECE, ANA_IS_MOVE, _MOVE_IND, _NEST_KINDS, nested_same_op, _centre_slice,
    middle_sibling_leaf, del_one_piece, ana_is_move, DEL_AS_MOVE, _MOVE_WORD_IND, _MOVE_AWAY, del_as_move,
    behead_in_leaf, _NOTE_CAPS, _cut_from_note, cut_note_leaf, ANA_LONE_EDGE, ANA_LITERAL_EDGE,
    DEL_WRAPS_CHARADE, _pull_part, _anagrams_with_pulled_part, _one_letter_part, ana_lone_edge,
    ana_literal_edge, del_wraps_charade, ana_double_indicator,
)
from validate_shape_warn import (
    CHARADE_GLUE, _old_roles, forgiven_dropped_words, redo_lost_words, carry_old_indicators,
    redo_keep_words, redo_regressions, lesson_warnings, shape_warnings, TRANSFORMING_OPS, ADJACENT_OPS,
    WALKTHROUGH_GAP, INDICATOR_APART, _stem_match, _PHRASE_FILLER, _FIRST_WORDS, _LAST_WORDS,
    _mentions_phrase, walkthrough_gaps, _span_of, apart_indicators, follow_warnings,
)

def validate_puzzle(puzzle, corpus=False):
    """(annotated, errors, warnings). A light leading more than one linked
    answer (groups.holders) has each alsoLeads answer checked as if it were
    the light's own clue, group and annotation (groups.as_leader); those
    findings name it "<tag> alsoLeads[k]".

    The file is checked through annotation.view_puzzle(): its trees are
    evaluated (one that does not give the answer is an error), and every
    check below reads the fields view() derives (blocks, assembly, type)."""
    schema_errors = [f"schema: {p}" for p in puzzle_schema.validate(puzzle)]
    treed = {_tag_of(puzzle, where) for where, _, ann in puzzle_schema.annotations(puzzle)
             if ann.get("wordplay")}
    held = {entry_id(e) for e in puzzle["entries"] if e.get("annotation")}
    puzzle, tree_errors, tree_warnings = tree_view(puzzle)
    # A tree that does not give its answer is left out of the view, and its
    # `wordplay:` error names the clue; it is not also a blank.
    dropped = {entry_id(e) for e in puzzle["entries"]
               if entry_id(e) in held and not e.get("annotation")}
    annotated, errors, warnings = _validate_puzzle(puzzle, corpus, schema=False,
                                                   dropped=dropped)
    errors[:0] = schema_errors + tree_errors
    warnings[:0] = tree_warnings
    for i, e in enumerate(puzzle["entries"]):
        for k, item in enumerate(e.get("alsoLeads") or []):
            if not item.get("annotation"):
                continue
            tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            n, errs, warns = _validate_puzzle(groups.as_leader(puzzle, i, k), corpus, schema=False)
            mine = (f"{tag}:", f"{entry_id(e)}:")
            annotated += 1
            errors += [f"{tag} alsoLeads[{k}]:{m.split(':', 1)[1]}" for m in errs if m.startswith(mine)]
            warnings += [f"{tag} alsoLeads[{k}]:{m.split(':', 1)[1]}" for m in warns if m.startswith(mine)]
    # A clue entered off the grid (offGrid) is checked on a light of its own
    # (groups.alone); its findings name it "<k>-offgrid".
    for cid, item in groups.off_grid(puzzle):
        if not item.get("annotation"):
            continue
        k = cid.split("-")[0]
        n, errs, warns = _validate_puzzle(groups.alone(puzzle, cid), corpus, schema=False)
        mine = (f"{k}A:", f"{k}-across:")
        annotated += n
        errors += [f"{cid}:{m.split(':', 1)[1]}" for m in errs if m.startswith(mine)]
        warnings += [f"{cid}:{m.split(':', 1)[1]}" for m in warns if m.startswith(mine)]
    # A clue stored as a wordplay tree has nothing to write under `assembly`:
    # the schema refuses the key, and view() derives it. Either the evaluator
    # checked every node against the answer (a tree that fails is an error
    # above, and is left out of the view), or the tree has an unchecked step,
    # which its own warning and ratchet (wordplay.unchecked) already count. A
    # top-level deletion, selection or substitution builds the answer in one
    # chunk, so view() gives it no `pieces`, and "Give `assembly.pieces`" sent
    # runs to write a key apply_annotations then refused.
    warnings = [w for w in warnings if w.split(":", 1)[0] not in treed
                or not any(m in w for m in SUPERSEDED_BY_TREE)]
    return annotated, errors, warnings


SUPERSEDED_BY_TREE = ("typed anagram but no assembly.anagrams", "no machine-checkable assembly")


def _tag_of(puzzle, where):
    """The finding tag for an annotation path from puzzle_schema.annotations."""
    m = re.match(r"\$\.entries\[(\d+)\]\.(?:alsoLeads\[(\d+)\]\.)?annotation$", where)
    if m:
        e = puzzle["entries"][int(m.group(1))]
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        return tag + (f" alsoLeads[{m.group(2)}]" if m.group(2) else "")
    m = re.match(r"\$\.offGrid\[(\d+)\]", where)
    return f"{int(m.group(1)) + 1}-offgrid" if m else where


#: Whether the corpus holds no note that restates the abbreviation table:
#: then every file is held to check_no_abbreviation_notes. Until then only a
#: run's own new notes are (check_no_new_abbreviation_notes), so the files still
#: carrying them keep validating. tools/strip_abbreviation_notes.py --commit
#: sets it True in its migration commit.
ABBREVIATION_NOTES_STRIPPED = False


def _restating(tree):
    """[leaf] of every note in a tree that only restates the table."""
    out, stack = [], [tree] if isinstance(tree, dict) else []
    while stack:
        node = stack.pop()
        if annotation.restates_abbreviation(node):
            out.append(node)
        stack += [p for p in node.get("parts") or [] if isinstance(p, dict)]
    return out


def _abbreviation_error(tag, node):
    return (f"{tag}: leaf {node['words']!r} > {node['gives']!r} stores the note "
            f"{node['note']!r}, which only restates the abbreviation table; leave "
            f"it out (the site shows {annotation.abbreviation_gloss(node)!r} from the table)")


def check_no_new_abbreviation_notes(puzzle, path, errors):
    """check_no_abbreviation_notes for a run's own puzzle, on the notes the
    committed file does not already hold (until ABBREVIATION_NOTES_STRIPPED)."""
    if ABBREVIATION_NOTES_STRIPPED:
        return
    committed = committed_entries(path) or {}
    for e in puzzle["entries"]:
        ann = e.get("annotation") or {}
        was = (committed.get(entry_id(e)) or {}).get("annotation") or {}
        held = {(n["words"], n["gives"], n["note"]) for n in _restating(was.get("wordplay"))}
        for node in _restating(ann.get("wordplay")):
            if (node["words"], node["gives"], node["note"]) not in held:
                errors.append(_abbreviation_error(entry_id(e), node))


def check_no_abbreviation_notes(tag, tree, errors):
    """A leaf stores no note that only restates an abbreviation the table
    holds (annotation.restates_abbreviation): view() derives that gloss from
    tools/build_abbreviations.table(), so the stored note is a derivable field.
    A note that adds anything beyond the pair stays."""
    errors += [_abbreviation_error(tag, node) for node in _restating(tree)]


def _whole_answer(held, puzzle):
    """The answer a held entry's wordplay must build: a linked lead's whole
    joined answer (annotation.display_answer), not its first light's letters;
    None when the entry holds no solution."""
    return annotation.whole_answer(held, puzzle) or None


def tree_view(puzzle):
    """(the puzzle as annotation.view_puzzle shows it, errors, warnings). A
    tree that does not give the answer is an error, and its annotation is
    left out of the view. An `unchecked` node (a step filed before trees were
    checked, which the expression cannot write) warns, and the ratchet (wordplay.unchecked) lets a puzzle keep only the
    ones annotation_backlog.json allows it: new annotations may add none."""
    problems = []
    viewed = annotation.view_puzzle(puzzle, problems)
    errors = [f"{_tag_of(puzzle, where)}: wordplay: {msg}" for where, msg in problems]
    warnings = []
    for where, held, ann in puzzle_schema.annotations(puzzle):
        whole = _whole_answer(held, puzzle)  # a linked lead's wordplay builds the joined answer
        n = len(unverified_unchecked(ann.get("wordplay"), whole))  # steps computable from their leaf are not unchecked
        if ABBREVIATION_NOTES_STRIPPED:
            check_no_abbreviation_notes(_tag_of(puzzle, where), ann.get("wordplay"), errors)
        if n:
            warnings.append(f"{_tag_of(puzzle, where)}: {n} {UNCHECKED_STEP}(s), taken as filed "
                            f"from the old blocks; write the step as an expression the "
                            f"evaluator checks (tools/wordplay.py)")
        if k := anagram_charades(ann.get("wordplay"), whole):
            warnings.append(f"{_tag_of(puzzle, where)}: {k} {ANAGRAM_CHARADE}: an anagram's "
                            f"fodder is one pool of letters, so its pieces are its own parts "
                            f"(ana(x + y)); a word that only joins them is a link word, and an "
                            f"anagram indicator goes on ana<...>; a letter piece at the answer's edge "
                            f"belongs outside it (I + N + ana(RIP SIGN)), not scrambled in")
        warnings += shape_warnings(_tag_of(puzzle, where), ann, (held.get("clue") or {}).get("text"), whole)
        warnings += lesson_warnings(_tag_of(puzzle, where), ann, held)
        warnings += follow_warnings(_tag_of(puzzle, where), ann, held, puzzle)
    return viewed, errors, warnings


def theme_source(puzzle):
    """What supplies a themed puzzle's letters that no clue word gives: its
    preamble, else the clue its `themeClue` names ("30-across"), else None."""
    if puzzle.get("preamble"):
        return "the preamble"
    if puzzle.get("themeClue"):
        return puzzle["themeClue"]
    return None


def _validate_puzzle(puzzle, corpus=False, schema=True, dropped=()):
    errors, warnings = [], []
    # The file's shape first: tools/fetch_puzzle.write_puzzle_file refuses to
    # write anything that breaks it, and this catches a file written any other way.
    if schema:
        errors.extend(f"schema: {p}" for p in puzzle_schema.validate(puzzle))
    check_no_markup(puzzle, errors)
    check_groups(puzzle, errors)
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    annotated = 0
    authored = is_authored(puzzle)

    for e in puzzle["entries"]:
        ann = e.get("annotation")
        tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
        if ann is None:
            continue        # check_every_clue_is_annotated reports these
        annotated += 1

        clue = e["clue"].get("text", "")
        for key in ("type", "definitions", "answer", "blocks"):
            if key == "definitions" and (ann.get("definedByPreamble") is True
                                         or whole_rebus(ann, clue)):
                continue
            if not ann.get(key):
                errors.append(f"{tag}: missing annotation field '{key}'{MISSING_FIELD_FIX.get(key, '')}")
        # A themed answer the puzzle's preamble defines ("the unclued answers
        # are birds") has no definition in its clue. Only a puzzle that prints
        # a preamble can say so, and the flag replaces the definition rather
        # than sitting beside one.
        if "definedByPreamble" in ann:
            if ann["definedByPreamble"] is not True:
                errors.append(f"{tag}: definedByPreamble is true or absent, "
                              f"never {ann['definedByPreamble']!r}")
            elif not puzzle.get("preamble"):
                errors.append(f"{tag}: definedByPreamble, but the puzzle has no "
                              f"preamble to define it. Write the clue's definition as "
                              f"`def` and drop the flag; if no clue word defines it, the "
                              f"file lacks its preamble: keep the flag, never withdraw")
            elif ann.get("definitions"):
                errors.append(f"{tag}: definedByPreamble and a definition "
                              f"{' / '.join(definitions.texts(ann))!r} — the clue defines it or the "
                              f"preamble does, not both")

        check_type(tag, ann, errors)

        # What letters must the wordplay produce?
        if e.get("group"):
            target_letters = "".join(letters((by_id.get(gid) or {}).get("solution") or "")
                                     for gid in e["group"])
        else:
            target_letters = letters(e.get("solution"))
        ans_letters = letters(ann.get("answer"))
        if target_letters and ans_letters != target_letters:
            errors.append(f"{tag}: answer '{ann.get('answer')}' != grid solution {target_letters}")

        # Definitions and indicators must appear verbatim in the clue, and each
        # definition's `at` must point at its text.
        for d in ann.get("definitions") or []:
            text = d.get("text") or ""
            if text not in clue:
                errors.append(f"{tag}: definition {text!r} not found in clue {clue!r}"
                              + verbatim_hint(text, clue))
            elif not definitions.span_ok(d, clue):
                errors.append(f"{tag}: definition {text!r} is not at {d.get('at')!r} in "
                              f"{clue!r}; it occurs at "
                              f"{', '.join(map(str, definitions.candidates(text, clue)))}. "
                              f"`at` is the offset in code points, filled in when "
                              f"the puzzle is written, if the text occurs once")
        for ind in indicator_texts(ann):
            if ind not in clue:
                errors.append(f"{tag}: indicator {ind!r} not found in clue {clue!r}"
                              + verbatim_hint(ind, clue))
        # Link words ("to locate", "indicating") join definition to wordplay and
        # carry no letters of their own — they must still be named, not ignored.
        for lw in ann.get("linkWords", []):
            if lw not in clue:
                errors.append(f"{tag}: linkWord {lw!r} not found in clue {clue!r}"
                              + verbatim_hint(lw, clue))
        for b in ann.get("blocks", []):
            frag = b.get("clueFragment")
            if frag and frag not in clue:
                errors.append(f"{tag}: block fragment {frag!r} not found in clue {clue!r}"
                              + verbatim_hint(frag, clue))
            # No clue words: letters the puzzle's preamble supplies, or the
            # clue that states its theme (`themeClue`, filed by hand, when the
            # paper prints the gimmick in a clue: nation-3337's 30-across).
            if not frag and not (b.get("gives") and theme_source(puzzle)):
                what = f" giving {b['gives']!r}" if b.get("gives") else ""
                left = clue_words_no_block_covers(ann, clue)
                what += (f" (clue words nothing covers yet: {', '.join(map(repr, left))}; "
                         f"one of them gives these letters)" if left else
                         " (every clue word is already covered, so these letters come from "
                         "words another block quotes: quote them again, "
                         "[Two bitters]COLD + [Two bitters#2]RAW)")
                errors.append(f"{tag}: a block with no clueFragment{what} is for letters the "
                              f"preamble supplies, and needs `gives` and a puzzle with a "
                              f"preamble (or a filed themeClue); otherwise quote the "
                              f"clue words it parses: in `wp` write that piece as "
                              f"[clue words]LETTERS rather than bare LETTERS. Letters "
                              f"a del() took out and an ins() puts back are still the "
                              f"letters of a clue word, so quote that word")

        # Letter mechanics.
        build = assembly(ann)
        check_anagram_letters(puzzle.get("id"), entry_id(e), tag, ann, errors)
        row = SETTER_ERROR.get((puzzle.get("id"), entry_id(e)))
        if row:
            errors += [f"{tag}: tools/data/setter_error.json's row: {p}"
                       for p in setter_error_problems(puzzle, entry_id(e), row, ann)]
        check_anagram_has_fodder(tag, ann, warnings)
        for r in build.get("reversals", []):
            if letters(r["from"])[::-1] != letters(r["to"]):
                errors.append(f"{tag}: reversal {r['from']} reversed != {r['to']}")
        # The wordplay builds the clue's own word; an alteration then turns it
        # into the entry, and the write gate checks that step.
        built = wordplay_letters(ann, e)
        if build.get("pieces"):
            joined = letters("".join(build["pieces"]))
            if joined != built:
                errors.append(f"{tag}: pieces {build['pieces']} join to {joined}, expected {built}")
        # A hidden word that is one part of a charade or container hides that
        # part's letters (TRI in "Triumphant", ALG in "sociAL Group"), not the
        # whole answer: the tree checks each hidden leaf against its own words.
        # Only a wordplay made of the hidden word (under a reversal or a
        # homophone) has to find the whole answer in the clue.
        if "hidden_word" in types_of(ann) and set(types_of(ann)) <= {"hidden_word", "reversal", "homophone"}:
            # A reversed hidden word sits in the clue back to front (30045 26A
            # hides LEND across "commanD NELson"), so when the type also declares
            # the reversal, the mirror image counts as found.
            clue_letters = letters(expand_cross_references(clue, puzzle["entries"]))
            reversed_ok = ("reversal" in types_of(ann)
                           and built[::-1] in clue_letters)
            # A hidden homophone hides the sound, not the spelling: APHID from
            # s(AFE ID)iomatically, so the block's soundsLike is what is found.
            sound_ok = ("homophone" in types_of(ann)
                        and any(letters(b.get("soundsLike")) in clue_letters
                                for b in ann.get("blocks") or [] if b.get("soundsLike")))
            spelled_ok = any(built in w for w in spelled_numbers(ann))
            # A setter's slip in the printed run (tools/data/setter_error.json
            # names the light): the corrected run is a slip away from one.
            slip_ok = bool(row) and any(wordplay.run_slip(clue_letters, w)
                                        for w in (built, built[::-1] if "reversal" in types_of(ann) else built))
            if built not in clue_letters and not reversed_ok and not sound_ok and not spelled_ok and not slip_ok:
                errors.append(f"{tag}: hidden answer {built} not found inside clue letters")
        # apply_annotations derives the assembly wherever the blocks rebuild the
        # answer, so one still missing is a step the blocks cannot show, or blocks
        # that miss the answer's letters, which check_blocks_account_for_answer
        # already reports.
        if not (build.get("pieces") or whole_anagram(ann, e) or {"hidden_word", "double_definition", "cryptic_definition",
                    "homophone"} & set(types_of(ann)) or blocks_miss_letters(ann, e)):
            warnings.append(f"{tag}: no machine-checkable assembly, and the blocks do not "
                            f"rebuild the answer by joining them with the reversals, "
                            f"insertions and anagrams `type` names. Give `assembly.pieces` "
                            f"(the final chunks in answer order), and `assembly.anagrams` / "
                            f"`assembly.reversals` for each such step the blocks cannot show")

        # A definition's note silences the part-of-speech check, so it has to say
        # something: a one-word "fine" would turn the check into an off switch.
        for note in [d["note"] for d in ann.get("definitions") or [] if "note" in d]:
            if len(str(note).strip()) < 25:
                errors.append(f"{tag}: definition note {note!r} is too thin — it exists only "
                              f"where the definition disagrees with the answer in number or "
                              f"part of speech, and it must say in a real sentence why the "
                              f"setter is allowed that (\"Lousy payment\" = PEANUTS: a "
                              f"mass noun defining a plural, fair because peanuts is itself "
                              f"used as a mass noun for a pittance). Explain it or drop it")

        errors.extend(f"{tag}: {p}" for p in letter_problems(ann, e))
        check_definition_fit(tag, ann, errors, warnings)
        check_answer_matches_separators(tag, ann, e, errors)
        check_sound_names_its_source(tag, ann, errors, warnings)
        check_sound_is_not_a_letter_swap(tag, ann, errors, warnings)
        check_indicators(tag, ann, clue, errors, warnings)
        check_unmarked_hidden_word(tag, ann, clue, errors)
        check_no_answer_in_early_rungs(tag, ann, clue, errors, warnings)
        check_block_notes_dont_name_the_answer(tag, ann, errors, warnings,
                                               light_solutions(e, by_id))
        check_indicator_notes_name_no_block(tag, ann, errors)
        check_no_two_end_letters(tag, ann, errors)
        check_cryptic_definition_blocks(tag, ann, errors, warnings)

        check_coverage(tag, ann, clue, warnings)
        check_part_of_speech(tag, ann, warnings)
        check_features(tag, ann, clue, errors, warnings)
        check_surface(tag, ann, clue, warnings)
        # Not under `authored`. is_authored means WE wrote the clue; the
        # walkthrough is ours either way, and the faults these two find occur on
        # published grids. Gated, they would never fire.
        check_walkthrough_opener(tag, ann, warnings)
        check_walkthrough_closer(tag, ann, warnings)
        # Not under `authored` either, and for the same reason: the fault is in
        # OUR parse of a published clue, on somebody else's grid.
        check_link_word_is_not_an_order(tag, ann, clue, warnings)
        check_link_word_is_clear_of_other_marks(tag, ann, clue, errors)
        # 895 published clues predate it: a corpus sweep warns, a run writing a
        # puzzle must fix it.
        check_link_word_is_not_inside_a_block(tag, ann, clue, warnings if corpus else errors)
        check_indicator_does_not_straddle_a_definition(tag, ann, clue, errors)
        check_anagram_fodder_from_clue(tag, ann, clue, authored, errors, warnings)
        if authored:
            check_authored_surface(tag, ann, clue, errors)
            check_two_pieces(tag, ann, errors)
            check_walkthrough_budget(tag, ann, warnings)
            check_link_words_are_equivalences(tag, ann, errors)
            check_indicator_adjacency(tag, ann, clue, errors, warnings)
            check_indicator_outside_fodder(tag, ann, clue, errors)
            check_reversal_direction(tag, ann, e["direction"], errors)
        walk = explanation(ann).get("walkthrough") or ""
        for h in walkthrough_hedges(walk, clue):
            errors.append(f"{tag}: walkthrough hedges with {h!r} — parse the chunk "
                          f"properly instead of excusing it (docs/STYLE.md); a clue word is quoted "
                          f"('{h}' is fine in quotes only if the clue prints it), else say what "
                          f"the word does (the pun, the indicator) without the hedge")
        if len(walk.split()) > WALKTHROUGH_HARD_MAX:
            errors.append(f"{tag}: walkthrough is {len(walk.split())} words "
                          f"(max {WALKTHROUGH_HARD_MAX}) — that length is working-out, "
                          f"not an explanation; the blocks already did the mechanics")
        # Published under "What it seems to say" on the walkthrough rung, so it is held to the
        # length it was specified at rather than to the walkthrough's: it is one
        # sentence of picture, and a paragraph there pushes the trick off the screen.
        surface = explanation(ann).get("surface") or ""
        if len(surface.split()) > SURFACE_MAX:
            warnings.append(f"{tag}: surface is {len(surface.split())} words "
                            f"(max {SURFACE_MAX}) — it is the picture the clue paints, "
                            f"one sentence; the mechanics belong in walkthrough")
        # Same words in both fields means one of them is a heading with nothing
        # under it, and the rung prints them one after the other.
        if surface and surface.strip().lower() in walk.strip().lower():
            errors.append(f"{tag}: surface {surface!r} is repeated inside walkthrough — "
                          f"they are printed as two paragraphs, so say the picture once "
                          f"in surface and spend walkthrough on what the clue is doing")
        # Notes and definitionFit are published too, so they get the same check.
        for field, text in ([("walkthrough", walk), ("surface", surface),
                             ("definitionFit", explanation(ann).get("definitionFit") or "")]
                            + [("block note", b.get("note") or "")
                               for b in ann.get("blocks", [])]):
            for marker in BACKTRACKS:
                if marker in text.lower():
                    errors.append(f"{tag}: {field} contains {marker!r} — that is "
                                  f"working-out, not an explanation. Settle the parse "
                                  f"first, then write the finished sentence")


    errors.extend(message_problems(puzzle))
    warnings.extend(check_preamble(puzzle))
    # A puzzle whose clues are all withheld has no hint, and is still the run's
    # to answer for: the check says it is too much to ship round.
    withheld = withheld_clues(puzzle)
    if annotated or withheld:
        check_every_clue_is_annotated(puzzle["entries"], errors, warnings,
                                      blind_misses(puzzle["id"]), corpus=corpus,
                                      reopened=(puzzle.get("solutions") or {}).get("reopened") or {},
                                      dropped=dropped, withheld=withheld)
        check_model_answer_doubted(puzzle, errors, warnings, corpus=corpus)
        check_cryptic_definition_cap(puzzle["entries"], errors, warnings,
                                     authored=authored)
        if authored:
            check_authored_puns(puzzle["entries"], errors)
        check_definition_not_fodder(puzzle["entries"], errors, warnings)
        if not corpus:
            check_definition_against_blog(puzzle, warnings)
            check_blocks_against_blog(puzzle, warnings)
            check_cryptic_definition_against_blog(puzzle, warnings)
            check_type_against_blog(puzzle, warnings)
        check_blocks_account_for_answer(puzzle["entries"], errors, warnings)
        check_blocks_decompose(puzzle["entries"], errors, warnings)
        check_blocks_in_answer_order(puzzle["entries"], errors, warnings)
        check_blocks_carry_notes(puzzle["entries"], warnings)

    return annotated, errors, warnings


# --- the ratchet -------------------------------------------------------------
#
# A rule added after many puzzles were already annotated cannot fail the corpus
# on day one, and a REQUIRE_X flag flipped by hand once a backfill drained the
# backlog would leave the rule optional for exactly the puzzles it was invented
# for — the next ones — for as long as anyone forgets.
#
# So the allowance is per puzzle and written down. A puzzle may carry as many
# unannotated clues as annotation_backlog.json records for it and not one more;
# a puzzle not in the file — every puzzle fetched since the field was
# added — is allowed none. The backlog can only ever shrink: a full run rewrites the file
# with what it observed, so draining a puzzle tightens the rule on it forever.
# Adding a new grandfathered field means adding it to BACKLOG_MARKERS and
# running --tighten once; nothing has to be remembered afterwards.
# The two shapes a line of this tool's output can take, named so a caller can
# count them without matching on prose that is free to change.
WARN_PREFIX = "  warn: "
ERROR_PREFIX = "  ERROR: "

BACKLOG_PATH = ROOT / "tools" / "annotation_backlog.json"
# Each field is the dotted path of the key it counts. The file lists them in
# this order, and tools/prereset_backfill.sh drains them in the file's order.
BACKLOG_MARKERS = {
    "explanation.definitionFit": ("no explanation.definitionFit",),
    "indicators.note": ("no indicator notes", "has no note"),
    "blocks.note": (BLOCK_NO_NOTE,),
    "indicators.for": ("lack `for`",),
    "features": ("no features",),
    "explanation.surface": ("no explanation.surface",),
    "assembly.anagrams": ("no assembly.anagrams",),
    "messages": ("names a hidden-letter device",),
    "wordplay.unchecked": (UNCHECKED_STEP,),
    "wordplay.anagramCharade": (ANAGRAM_CHARADE,),
    "wordplay.charadeInCharade": (CHARADE_IN_CHARADE,),
    "wordplay.noIndicator": (NO_INDICATOR,),
    "wordplay.cdefRepeat": (CDEF_REPEAT,),
    "wordplay.arity": (STORED_ARITY,),
    "wordplay.spanOverlap": (SPAN_OVERLAP,),
    "wordplay.inDefinition": (IN_DEFINITION,),
    "wordplay.indFolded": (IND_FOLDED,),
    "wordplay.bareInitial": (BARE_INITIAL,),
    "wordplay.leafFold": (LEAF_FOLD,),
    "wordplay.repeatedSelection": (REPEATED_SELECTION,),
    "wordplay.singleLeaf": (SINGLE_LEAF,),
    "wordplay.bareInCharade": (BARE_IN_CHARADE,),
    "wordplay.anagramOfContainer": (ANAGRAM_OF_CONTAINER,),
    "wordplay.arityIns": (ARITY_INS,),
    "wordplay.arityOther": (ARITY_OTHER,),
    "wordplay.delSingle": (DEL_SINGLE,),
    "wordplay.indInLeaf": (IND_IN_LEAF,),
    "wordplay.scrambledLeaf": (SCRAMBLED_LEAF,),
    "wordplay.fakeParts": (FAKE_PARTS,),
    "wordplay.paddingLeaf": (PADDING_LEAF,),
    "wordplay.nestedContainer": (NESTED_CONTAINER,),
    "wordplay.anagramSynonym": (ANAGRAM_SYNONYM,),
    "wordplay.misplacedIndicator": (MISPLACED_INDICATOR,),
    "wordplay.deletionScope": (DELETION_SCOPE,),
    "wordplay.wrongRole": (WRONG_ROLE,),
    "wordplay.deletionInside": (DELETION_INSIDE,),
    "wordplay.containerInside": (CONTAINER_INSIDE,),
    "wordplay.sharedIndicator": (SHARED_INDICATOR,),
    "wordplay.halfLeaf": (HALF_LEAF,),
    "wordplay.deletionScattered": (DELETION_SCATTERED,),
    "wordplay.reversePhrase": (REVERSE_PHRASE,),
    "wordplay.midWordLeaf": (MIDWORD_LEAF,),
    "wordplay.deletionScopeAnswer": (DELETION_SCOPE_ANSWER,),
    "wordplay.doubleIndicator": (DOUBLE_INDICATOR,),
    "wordplay.movedLetter": (MOVED_LETTER,),
    "wordplay.poolGap": (POOL_GAP,),
    "wordplay.tradedIndicator": (TRADED_INDICATOR,),
    "wordplay.reversalSplit": (REVERSAL_SPLIT,),
    "wordplay.reversedCharadeOrder": (REVERSED_CHARADE_ORDER,),
    "wordplay.anaSelectEdge": (ANA_SELECT_EDGE,),
    "wordplay.delWide": (DEL_WIDE,),
    "wordplay.indLeafOverlap": (IND_LEAF_OVERLAP,),
    "wordplay.anaDoubleInd": (ANA_DOUBLE_IND,),
    "wordplay.delStraddle": (DEL_STRADDLE,),
    "wordplay.swappedPair": (SWAPPED_PAIR,),
    "wordplay.linkInLeaf": (LINK_IN_LEAF,),
    "wordplay.anaStandIn": (ANA_STAND_IN,),
    "wordplay.selectWordInLeaf": (SELECT_WORD_IN_LEAF,),
    "wordplay.halvedAsDeletion": (HALVED_AS_DELETION,),
    "wordplay.trimAsSelection": (TRIM_AS_SELECTION,),
    "wordplay.splitSharedIndicator": (SPLIT_SHARED_INDICATOR,),
    "wordplay.truncInLeaf": (TRUNC_IN_LEAF,),
    "wordplay.cutNoteLeaf": (CUT_NOTE_LEAF,),
    "wordplay.ownIndInLeaf": (OWN_IND_IN_LEAF,),
    "wordplay.preReversedLeaf": (PRE_REVERSED_LEAF,),
    "wordplay.repeatInLeaf": (REPEAT_IN_LEAF,),
    "wordplay.doubledApostrophe": (DOUBLED_APOSTROPHE,),
    "wordplay.splitWordLeaves": (SPLIT_WORD_LEAVES,),
    "wordplay.moveNoteLeaf": (MOVE_NOTE_LEAF,),
    "wordplay.firstSiblingLeaves": (FIRST_SIBLING_LEAVES,),
    "wordplay.hiddenIndAbove": (HIDDEN_IND_ABOVE,),
    "wordplay.deletionNoCut": (DELETION_NO_CUT,),
    "wordplay.initialsInLeaf": (INITIALS_IN_LEAF,),
    "wordplay.halfInLeaf": (HALF_IN_LEAF,),
    "wordplay.selectIndEndsLeaf": (SELECT_IND_ENDS_LEAF,),
    "wordplay.nestedSameOp": (NESTED_SAME_OP,),
    "wordplay.middleSiblingLeaf": (MIDDLE_SIBLING_LEAF,),
    "wordplay.delOnePiece": (DEL_ONE_PIECE,),
    "wordplay.anaIsMove": (ANA_IS_MOVE,),
    "wordplay.delAsMove": (DEL_AS_MOVE,),
    "wordplay.beheadInLeaf": (BEHEAD_IN_LEAF,),
    "wordplay.selectorAsCut": (SELECTOR_AS_CUT,),
    "wordplay.anaLoneEdge": (ANA_LONE_EDGE,),
    "wordplay.anaLiteralEdge": (ANA_LITERAL_EDGE,),
    "wordplay.delWrapsCharade": (DEL_WRAPS_CHARADE,),
    "wordplay.ddMissesWordplay": (lesson_checks.DD_MISSES_WORDPLAY,),
    "spelling.unsaid": (lesson_checks.SPELLING_UNSAID,),
}


def load_backlog():
    """{field: {puzzle: allowance}}. A field the file has no list for yet is left
    out, and is not enforced until the --tighten that writes its list."""
    if not BACKLOG_PATH.exists():
        return {f: {} for f in BACKLOG_MARKERS}
    data = json.loads(BACKLOG_PATH.read_text())
    return {f: data[f] for f in BACKLOG_MARKERS if f in data}


def count_backlog(warnings):
    """Clues, not warnings: a clue missing two indicator notes warns twice, and
    noting one of them must not make the puzzle count more than before."""
    return {f: len({w.split(":", 1)[0] for w in warnings if any(m in w for m in ms)})
            for f, ms in BACKLOG_MARKERS.items()}


def _sort_key(kv):
    """Series, then number, for a namespaced id ("cryptic-30041"). An id whose
    tail is not a number sorts first in its series rather than raising."""
    series, _, num = kv[0].rpartition("-")
    return (series, int(num) if num.isdigit() else 0, kv[0])


def write_backlog(observed, allowed):
    """`observed` is {number: {field: count}} from a run over every puzzle.

    Writes the SMALLER of what was observed and what was already allowed, per
    puzzle per field, so "may only shrink" is enforced here rather than by a
    comment: recording whatever was seen would let a run that lost annotations
    raise the ceiling to fit them, and every run after it would agree the
    puzzle was fine."""
    ratchet = {f: {num: min(c[f], allowed.get(f, {}).get(num, c[f]))
                   for num, c in observed.items()} for f in BACKLOG_MARKERS}
    data = {"_why": "Per-puzzle allowance of clues predating a required annotation "
                    "field. Written by tools/validate_annotations.py; may only "
                    "shrink. A puzzle absent from a field's list must have none.",
            **{f: {num: n for num, n in sorted(ratchet[f].items(), key=_sort_key)
                   if n} for f in BACKLOG_MARKERS}}
    store_backlog(data)


def store_backlog(data, path=None):
    """Write the backlog in the layout git stores (the json-keys clean filter's:
    one line per top-level key). Every writer goes through here: a layout the
    filter would change shows as a code edit in the pre-reset backfill, which
    publishes with plumbing that skips the filter."""
    import json_merge
    (path or BACKLOG_PATH).write_text(json_merge.dump_lines(data))


def explain(name=None):
    """Print what a check actually does, read out of the validator's own source
    (this file and the validate_* modules it re-exports).

    Annotation runs would otherwise page through this whole file to find one
    function, and every grep/sed call is a turn. The answer is the source, so
    this hands over the source: the definition asked for and the comment block
    above it, which is where the reason lives.

    Generated by reading the AST rather than by keeping a table of
    explanations, because a table is a second copy of the truth and would be
    wrong within a month.
    """
    # The checks live in the validate_* modules this file re-exports; read them as one text.
    here = Path(__file__)
    src = "\n".join(f.read_text() for f in [here] + sorted(
        f for f in here.parent.glob("validate_*.py") if f.name not in (here.name, "validate_scope.py")))
    lines = src.splitlines()
    tree = ast.parse(src)
    named = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            named[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    named[t.id] = node

    if not name:
        print("Every check this file runs. `--explain <name>` prints one in full;\n"
              "constants and helpers (MARKUP_RE, TYPE_NAMES)\n"
              "work as names too.\n")
        for key, node in named.items():
            if not key.startswith("check_"):
                continue
            doc = ast.get_docstring(node) or ""
            print(f"  {key}\n      {doc.split(chr(10))[0] or '(no docstring)'}")
        return 0

    found = explain_matches(name, named, lines)
    if not found:
        # A run passes the words of a message it saw, and a message is built
        # inside a larger function, so show the lines that print it.
        words = [w.lower() for w in re.split(r"[_\W]+", name) if w and w.lower() != "check"]
        hits = [i for i, ln in enumerate(lines) if words and all(w in ln.lower() for w in words)]
        if not hits and len(words) > 1:
            hits = [i for i, ln in enumerate(lines)
                    if sum(w in ln.lower() for w in words) >= max(2, len(words) - 1)]
        if hits:
            print(f"# `{name}` is not a check; the source lines that mention it:\n")
            for i in hits[:2]:
                print("\n".join(lines[max(0, i - 6):i + 8]) + "\n")
            return 0
        print(f"no `{name}` in {Path(__file__).name}. Run --explain with no name for the list.")
        return 1
    if len(found) > EXPLAIN_AT_MOST:
        print(f"`{name}` is not a check's name; {len(found)} checks use it: "
              f"{', '.join(found)}. `--explain <one of these>` prints it.")
        return 0
    if found != [name]:
        print(f"# `{name}` is not a name here; the closest: {', '.join(found)}\n")
    for key in found:
        node = named[key]
        # The comment block immediately above a definition is this file's habit
        # for saying why it exists, so it is part of the answer.
        start = node.lineno - 1
        while start and lines[start - 1].lstrip().startswith("#"):
            start -= 1
        print("\n".join(lines[start:node.end_lineno]) + "\n")
    return 0


EXPLAIN_AT_MOST = 3


def explain_matches(name, named, lines):
    """The definitions `--explain name` means, best first.

    Runs pass what they saw, not a function name: a message's words
    (`definition-overlap`), a field (`definitionFit`), a type
    (`double_definition`). A refusal costs them a turn, so the name is taken
    as exact, then as part of a name, then as words every one of which the
    check's source contains."""
    name = name.strip().split(".")[-1]      # a ratchet field, `wordplay.cdefRepeat`, names its constant
    key = re.sub(r"[-\s]+", "_", re.sub(r"([a-z])([A-Z])", r"\1_\2", name)).strip("_")
    for exact in (name, key, f"check_{key}", f"check_{key.lower()}"):
        if exact in named:
            return [exact]
    folded = {k.lower(): k for k in named}      # cdefRepeat -> CDEF_REPEAT
    for exact in (key.lower(), f"check_{key.lower()}"):
        if exact in folded:
            return [folded[exact]]
    checks = [k for k in named if k.startswith("check_")]
    part = [k for k in checks if key.lower() in k.lower()]
    if part:
        return sorted(part, key=len)
    words = [w.lower().rstrip("s") for w in re.split(r"[_\W]+", key) if w]
    words = [w for w in words if w != "check"]
    if not words:
        return []
    source = {k: "\n".join(lines[named[k].lineno - 1:named[k].end_lineno]).lower() for k in checks}
    return sorted((k for k in checks if all(w in source[k] for w in words)),
                  key=lambda k: -sum(source[k].count(w) for w in words))


def _convention_exempt(stem, field):
    """True when `field` is a wordplay shape rule and the puzzle is Azed or Genius: their conventions
    make the judges accept the tree, so the rule stays a warning and the ratchet does not count it."""
    import shape_queue
    return (shape_queue.exempt(stem) and field.startswith("wordplay.")
            and field not in ("wordplay.unchecked", "wordplay.ddMissesWordplay"))


def _warning_only(field):
    """True when `field` ("wordplay.bareInitial") is a rule shape_queue.WARN_ONLY lists: it never fails a puzzle."""
    import shape_queue
    return field.startswith("wordplay.") and field.split(".", 1)[1] in shape_queue.WARN_ONLY


def _block_note_hint(frag, gives):
    """What the one sentence a block with no note needs must say, for the block's own shape: letters cut
    from the words, a short abbreviation, or a synonym (the possessive 's is mended by code, not asked)."""
    f, g = wordplay.letters(frag).upper(), wordplay.letters(gives).upper()
    if len(g) < len(f) and g in f:
        return f"say which letters of {frag!r} are kept to make {g}"
    if len(g) <= 2:
        return f"say the convention that makes {frag!r} stand for {g}"
    return f"say what links them, e.g. '{g.lower()} is another word for {frag.lower()}'"


def _block_note_example(warnings):
    """The sentence's last clause: the first unnoted block quoted as the `notes` entry to write.
    (Palindrome, repeated-word, sound() and possessive leaves are noted by code before the check; what
    is left is a leaf whose words nobody explained, and only the model can say why they give those
    letters.) The example is worded for the block's own shape (_block_note_hint)."""
    for w in warnings:
        m = re.search(r"(\d+[AD]): block (.+?) > '(\w+)' " + re.escape(BLOCK_NO_NOTE), w)
        if m:
            try:
                raw = ast.literal_eval(m.group(2))
                frag = json.dumps(raw, ensure_ascii=False)
            except (ValueError, SyntaxError):
                raw, frag = m.group(2), m.group(2)
            return (f" For {m.group(1)} write `\"notes\": {{{frag}: \"<{_block_note_hint(raw, m.group(3))}>\"}}` "
                    f"inside that clue's annotation, one such entry per block named.")
    return ""


def backlog_errors(stem, warnings, allowed=None):
    """The ratchet's ERRORs for one puzzle: it may be short exactly as many
    notes as the backlog file records for it, and a puzzle absent from the file
    (anything annotated from now on, and every authored puzzle) is allowed 0."""
    allowed = load_backlog() if allowed is None else allowed
    errors = []
    for field, n in count_backlog(warnings).items():
        if field not in allowed or _convention_exempt(stem, field) or _warning_only(field):
            continue
        cap = allowed[field].get(stem, 0)
        if n > cap:
            ms = BACKLOG_MARKERS[field]
            named = [w.split(": ", 1)[1].split(". ", 1)[0] for w in warnings
                     if any(m in w for m in ms) and ": " in w][:4]
            errors.append(
                f"{n} clue(s) missing {field}, and this puzzle is allowed {cap} — "
                f"{field} is required on everything annotated since it was added. "
                f"The warnings above name them and say what to write."
                + (f" Missing: {'; '.join(named)}." if field in ("blocks.note", "wordplay.noIndicator") else "")
                + (_block_note_example(warnings) if field == "blocks.note" else ""))
    return errors


def check_against_committed(puzzle, path, errors):
    """The checks a run's own puzzle gets against the file as committed."""
    check_clue_unchanged(puzzle, path, errors)
    check_theme_clue_unchanged(puzzle, path, errors)
    check_spelling_kept(puzzle, path, errors)
    check_clue_rows_held(puzzle, errors)
    check_selectors_are_indicators(puzzle, path, errors)
    check_no_new_abbreviation_notes(puzzle, path, errors)


def run_errors(path, puzzle):
    """Every error `validate_annotations.py <id>` reports for `puzzle`, the
    run's copy of the file at `path`."""
    _, errors, warnings = validate_puzzle(puzzle)
    check_against_committed(puzzle, path, errors)
    return errors + backlog_errors(path.stem, warnings, load_backlog())


def flagged_clues(warnings, fields):
    """{field: sorted clue keys ("22a")} the warnings flag under each backlog field of `fields`."""
    return {f: sorted({w.split(":", 1)[0].lower() for w in warnings if any(m in w for m in BACKLOG_MARKERS[f])})
            for f in fields}


def check_one(path, corpus, allowed, requeue=()):
    """One puzzle's report: (its printed text, (stem, backlog counts) or None,
    whether it failed). Prints nothing itself, so a pool of workers can run it
    and the parent can print the reports in the order of the paths.

    `requeue` (the backlog fields tools/requeue_drift.py queues): a puzzle past its
    allowance in one of them is not an error here; the clues it flags come back as
    a third item of `seen`, {field: clue keys}, for the CI step that raises the
    allowance and queues them (requeue_drift.py --publish)."""
    out = []
    if not path.exists():
        return f"MISSING {path}\n", None, True
    puzzle = read_puzzle_file(path)
    annotated, errors, warnings = validate_puzzle(puzzle, corpus=corpus)
    if not corpus:          # a run's own puzzles; the corpus is HEAD already
        check_against_committed(puzzle, path, errors)
    total = len(puzzle["entries"])
    if annotated == 0 and corpus:
        # Nothing to check about annotations that do not exist yet — but
        # the checks that walk the whole file (markup) do apply, and
        # dropping them here would exempt exactly the puzzles nobody has
        # looked at.
        out.append(f"{puzzle['id']}: unannotated ({total} clues) — skipped\n")
        out += [f"{ERROR_PREFIX}{err}\n" for err in errors]
        return "".join(out), None, bool(errors)
    seen = (path.stem, count_backlog(warnings))
    if requeue:
        flagged = flagged_clues(warnings, requeue)
        over = {f: keys for f, keys in flagged.items() if f in allowed and len(keys) > allowed[f].get(path.stem, 0)}
        if over:
            seen += (over,)
            allowed = {**allowed, **{f: {**allowed[f], path.stem: len(keys)} for f, keys in over.items()}}
    errors += backlog_errors(path.stem, warnings, allowed)
    status = "OK" if not errors else "FAIL"
    by = f" ({puzzle['setter']})" if puzzle.get("setter") else ""
    out.append(f"{puzzle['id']}{by}: {annotated}/{total} annotated — {status}\n")
    out += [f"{WARN_PREFIX}{w}\n" for w in warnings if annotated]
    out += [f"{ERROR_PREFIX}{err}\n" for err in errors]
    return "".join(out), seen, bool(errors)


#: What a pool worker reads: set before the fork, so each inherits it.
_POOL_JOB = None
#: Puzzles a worker takes at a time: big enough that the pipe is not the cost.
POOL_CHUNK = 16
#: Fewer paths than this are checked in-process: forking costs more.
POOL_MIN = 200


def _pool_one(path):
    corpus, allowed, requeue = _POOL_JOB
    return check_one(path, corpus, allowed, requeue)


def check_all(paths, corpus, allowed, requeue=()):
    """check_one for each path, in the order of `paths`: spread across the
    cores when there are many (the full check, ~1,000s of puzzles, and every
    puzzle is independent), serial otherwise. The reports are identical either
    way, and so is the order they come back in. VALIDATE_JOBS=1 forces serial.
    Two workers by default, not cpu_count(): this runs on a shared host beside the
    burn and the bridge, and a full fan-out starved them (10-22). VALIDATE_JOBS
    overrides."""
    global _POOL_JOB
    jobs = int(os.environ.get("VALIDATE_JOBS") or 2)
    if jobs < 2 or len(paths) < POOL_MIN or "fork" not in multiprocessing.get_all_start_methods():
        for path in paths:
            yield check_one(path, corpus, allowed, requeue)
        return
    _POOL_JOB = (corpus, allowed, requeue)
    with multiprocessing.get_context("fork").Pool(jobs) as pool:
        yield from pool.imap(_pool_one, paths, POOL_CHUNK)


def shard_of(stem, n):
    """Which of n shards checks puzzle `stem`: a stable hash of the id (not
    Python's per-process hash()), so every step of the deploy agrees on the
    split. The same rule as tools/build_seo_pages.py's page shards."""
    return int.from_bytes(hashlib.sha256(stem.encode("utf-8")).digest()[:8], "big") % n


def shard_slice(paths, shard):
    """The paths of `paths` that belong to shard (i, n)."""
    i, n = shard
    return [p for p in paths if shard_of(p.stem, n) == i]


def take_shard_arg(argv):
    """(argv without `--shard i/n`, (i, n) or None)."""
    if "--shard" not in argv:
        return argv, None
    at = argv.index("--shard")
    try:
        i, n = map(int, argv[at + 1].split("/"))
    except (IndexError, ValueError):
        raise SystemExit("--shard takes i/n, e.g. --shard 0/4")
    if not 0 <= i < n:
        raise SystemExit(f"--shard {i}/{n}: i must be from 0 to n-1")
    return argv[:at] + argv[at + 2:], (i, n)


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    argv, shard = take_shard_arg(argv)
    # --drift-out FILE (the deploy's full check): a puzzle past its allowance in a rule
    # tools/requeue_drift.py queues is no failure; its flagged clues go to FILE for
    # `requeue_drift.py --publish`, which raises the allowance and queues them.
    drift_out = None
    if "--drift-out" in argv:
        at = argv.index("--drift-out")
        drift_out, argv = argv[at + 1], argv[:at] + argv[at + 2:]
    if shard and "--tighten" in argv:
        raise SystemExit("--shard cannot --tighten: only an unsharded run has seen every puzzle")
    if shard and [a for a in argv if a != "--unscoped"]:
        raise SystemExit("--shard splits the full check: it takes no puzzle ids or files")
    if "--explain" in argv:
        rest = argv[argv.index("--explain") + 1:]
        return explain(rest[0] if rest else None)
    if "--unscoped" in argv:
        validate_base.FORCE_AUTHORED_CHECKS = True
        argv = [a for a in argv if a != "--unscoped"]
        print("--unscoped: authoring rules applied to published puzzles too. This is "
              "CALIBRATION — every hit is either a broken check or a rare setter's "
              "liberty, and the default reading is the former.")
    tighten = "--tighten" in argv
    # --deploy FILE...: the deploy's corpus rules (a dropped annotation is
    # queued, an unannotated puzzle skipped) on just these files, for the
    # hooks (.githooks/pre-commit, tools/pre_push.py) to refuse what would
    # turn the deploy red, and nothing the deploy lets through.
    deploy = "--deploy" in argv
    argv = [a for a in argv if a not in ("--tighten", "--deploy")]
    if argv:
        paths = [resolve_puzzle(a) for a in argv]
    else:
        paths = puzzle_files()
    full_run = not argv
    corpus = full_run or deploy
    allowed = load_backlog()
    if shard:
        # The ratchet is per puzzle, so a shard enforces exactly its slice of
        # it; the totals below are the slice's, and the shards' sum is the
        # whole corpus's. A failure in any shard fails its step, so the deploy.
        paths = shard_slice(paths, shard)
        print(f"shard {shard[0] + 1} of {shard[1]}: {len(paths)} puzzle(s)")
    if (deploy or full_run) and not tighten and time.time() < SHAPE_GRACE_UNTIL:
        # The hooks and CI, not a run's own annotate_check, wait for the pushers
        # still on code from before the shape rules (a pre-reset backfill cannot
        # sync until its commits push): see SHAPE_GRACE_UNTIL.
        allowed = {f: v for f, v in allowed.items() if f not in SHAPE_GRACE_FIELDS}
    observed = {}
    failed = False
    requeue, drift = (), {}
    if drift_out:
        import requeue_drift  # lazy: it imports this module
        requeue = tuple(requeue_drift.rule_fields())
    for text, seen, bad in check_all(paths, corpus, allowed, requeue):
        sys.stdout.write(text)
        if seen is not None:
            observed[seen[0]] = seen[1]
            for field, keys in (seen[2] if len(seen) > 2 else {}).items():
                drift.setdefault(field, {})[seen[0]] = keys
                print(f"{WARN_PREFIX}{seen[0]}: {len(keys)} {field} clue(s) past the allowance: queued for the burn")
        failed = failed or bad
    if drift_out:
        Path(drift_out).write_text(json.dumps(drift, indent=1) + "\n")
    # Printed as one number rather than 400 warning lines' worth of noise, and
    # printed even when everything passes: a backlog nobody sees is a backlog
    # nobody drains. Only a FULL run can total it — a single-puzzle run counts
    # only its own clues.
    if full_run:
        for field in BACKLOG_MARKERS:
            total = sum(c[field] for c in observed.values())
            print(f"\n{field} backlog: {total} clue(s) in {sum(1 for c in observed.values() if c[field])} "
                  f"puzzle(s)." if total else f"\n{field} backlog is EMPTY — every puzzle now carries it.")
        # Only a full run has visited every puzzle, so only a full run may
        # rewrite the file — and only when asked, because widening the
        # allowance is how a regression would get itself forgiven.
        moved = {f: sum(n for stem, n in allowed.get(f, {}).items()
                        if not shard or shard_of(stem, shard[1]) == shard[0])
                 - sum(c[f] for c in observed.values())
                 for f in BACKLOG_MARKERS}
        if tighten and failed:
            # A failing run is the one run that must never record its own state:
            # what it saw includes whatever it is failing about, and recording
            # that is how a regression gets itself forgiven forever.
            print("NOT tightening: this run failed, so what it observed is not a "
                  "ceiling worth keeping. Fix the errors above and re-run.")
        elif tighten:
            write_backlog(observed, allowed)
            print("wrote tools/annotation_backlog.json: "
                  + ", ".join(f"{f} recorded" if f not in allowed else f"{f} -{n}" if n >= 0
                              else f"{f} unchanged (observed {abs(n)} more, kept the tighter cap)"
                              for f, n in moved.items()))
        elif any(v > 0 for v in moved.values()):
            # Not a failure: a shrink is the burn working. The nightly
            # tools/prereset_backfill.sh is the one writer of the file.
            print("backlog shrank (" + ", ".join(f"{f} -{n}" for f, n in moved.items() if n > 0)
                  + ") — not a failure; tools/prereset_backfill.sh records it tonight "
                    "with `python3 tools/validate_annotations.py --tighten`.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
