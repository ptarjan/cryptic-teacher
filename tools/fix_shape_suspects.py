#!/usr/bin/env python3
"""Repair the shape suspects whose right tree follows mechanically; list the rest for re-annotation.

    python3 tools/fix_shape_suspects.py                 # dry run: counts, 15 before/after examples,
                                                        # writes nothing
    python3 tools/fix_shape_suspects.py --examples 30   # more examples (--seed N to reshuffle)
    python3 tools/fix_shape_suspects.py --apply         # write the repaired puzzles (see below);
                                                        # also updates tools/data/shape_reannotate.json:
                                                        # drops only the rows it fixed, adds its new
                                                        # detector rows, keeps every other row and mark

Reads tools/data/shape_suspects.json (tools/shape_suspects.py --rank) and, for each
suspect clue, the tree as filed NOW (the list may be older than the corpus: each
clue's detectors are run again on its current tree, and one no detector fires on
any more is dropped). A repair is made only where the right tree follows from the
clue, the answer and the existing tree with no reading of the clue:

  ins_split    an unchecked container over one charade (or 3+ parts): the pieces
               before the indicator and the pieces after it, one group a run inside
               the answer and the other round it, are inner and outer.
  del_removed  an unchecked one-part deletion: the letter it removes is the
               difference between the fodder's letters and the node's filed letters,
               at the end its indicator names (an end word: almost, short, endless..;
               a head word: topless, first off, starter..; a middle word: heartless,
               empty, gutted..); one run of 1-3 letters, one reading.
  del_unwrap   an unchecked one-part deletion whose part already gives the node's
               letters (the removal is inside a leaf's letters): the node goes, when
               its own indicators are none or sit inside a leaf's words.
  link_leaf    an unchecked leaf with no letters in a charade of 3+ parts: an
               indicator of the charade, its note kept.
  sel_literal  an unchecked leaf under a selection op, filed with the selection's
               result, where selecting from its own words gives those letters.
  arity_wrap   a unary op (rev, cyc, hid, a selection) with several parts, a 3+ part
               deletion, a 2-part substitution: of the few fixed regroupings, the one
               (exactly one) whose letters are the node's filed letters.
  leaf_trim    an indicator that also sits at the start or end of a leaf under its
               op: the leaf loses those words (its letters kept, or the words' own
               letters when it gave them literally / its select parent still yields).
  ind_trim     an indicator whose edge words are a leaf of its own op: the indicator
               loses them.
  half_cut     a deletion of exactly half a word under "half"/"not half"/"mostly": first/last over the word.
  leaf_check   an unchecked leaf whose letters are its own words, or an abbreviation
               the table holds, is checked; one whose words are a selector plus a
               source (selector_in_block) becomes the selection op over the source.

A repaired clue is kept only when its tree evaluates to the answer
(wordplay.evaluate), no shape detector fires on it that did not before, its
validate_annotations shape findings and unchecked steps do not grow, and the
puzzle's validate_annotations errors (validate_puzzle, check_against_committed,
the backlog ratchet) are no more than before. Everything else is left untouched;
a clue that still has a detector hit is listed, per clue, in
tools/data/shape_reannotate.json as {"id": "<puzzle>#<clue>", "reason": ...}.

How to apply
------------
--apply writes each puzzle with a kept repair in place (a .part renamed over it,
as tools/tidy_wordplay_shapes.py does; a kill loses nothing and a re-run finds
nothing left to repair in what it wrote). It is a mechanical sweep, so it follows
the precedent of 696f876838 ("Join 1117 charades inside charades...") and
f59e109ad6: ONE commit for the whole sweep, not one per puzzle. Only one corpus job
at a time: run it when no other job is rewriting puzzles/. Then:

    python3 tools/fix_shape_suspects.py --apply
    git diff --name-only -- puzzles/ > /tmp/shape_fixed.txt
    python3 tools/validate_annotations.py --deploy $(cat /tmp/shape_fixed.txt)
    python3 tools/tidy_wordplay_shapes.py puzzles/ --write --only /tmp/shape_fixed.txt   # tighten the
                                                        # allowances of THESE puzzles only
    git add -- puzzles/ tools/annotation_backlog.json tools/data/shape_reannotate.json
    git commit -m "Repair N mechanical wordplay shape faults in M puzzles ..."
    git fetch && git rebase origin/master && git push origin HEAD:master

Nothing is un-hinted and nothing becomes due by this sweep; the re-annotation list
is a separate queue decision.

Layout
------
This file is the entry point and the driver: the RULE_REPAIRS / REPAIRS / FOLLOW_ON tables, repair_tree,
the gate, and the --apply / --rule sweeps. The repairs themselves (the r_* functions, each taking
(node, parent, ctx)) live in fix_shape_* modules by family, and every name is re-exported here so
fix_shape_suspects.X still works:
  fix_shape_base        tree helpers every family shares
  fix_shape_leaves      leaf trims, leaf checks and arity regroupings
  fix_shape_indicators  role moves, shared / misplaced / unindicated indicators, hidden links
  fix_shape_container   container, nesting and pool repairs
  fix_shape_cuts        deletion and selection repairs
  fix_shape_ana         anagram repairs
  fix_shape_notes       indicator / block notes, doesNotGive, doubled apostrophes
"""
# The fix_shape_* imports below re-export every moved name, so ruff's unused-import check is off here.
# ruff: noqa: F401
import argparse
import collections
import copy
import hashlib
import itertools
import json
import multiprocessing
import os
import random
import re
import sys
from pathlib import Path

import annotation
import clue_shapes as cs
import puzzle_paths
import puzzle_schema
import shape_suspects as ss
import validate_annotations as V
import validate_committed as VC
import wordplay as W
from fix_shape_base import (
    UNARY, TAIL, HEAD, MID, walk, leaf, span, vals, gives_ok, checked, charade, clue_text, simplicity,
    _eval_swapped, _whole, _flat_fodder, _is_stand_in, _plain_charade, _splices, _pick, _diff_gone,
    _flat_leaves, _words_between, unchecked,
)
from fix_shape_leaves import (
    r_ins_split, r_del_removed, _inside_leaf, r_del_unwrap, r_link_leaf, r_sel_literal, r_arity_wrap,
    _trimmed_leaf, r_leaf_trim, r_ind_trim, r_leaf_check, r_leaf_fold, _fold_two_cuts, r_ind_in_leaf, _tokens,
    r_own_ind_leaf, r_trunc_leaf, r_link_in_leaf, r_ind_leaf_overlap, HALF, r_half_cut, r_arity_ins,
    r_removed_leaf, _ABBR, _abbreviations, _letters_back, r_literal_fodder, _HALF, r_half_leaf, _runs,
    _arity_cands, r_arity_other, _STOP, _edge_trim, _move_inner_indicator, r_span_overlap,
)
from fix_shape_indicators import (
    _role_owner, r_role_swap, _gated, _swap_unknown, r_role_move, _owns, _unknown_word, r_ind_trade,
    r_shared_indicator, _top_role, _anagram_only, _mine_for_op, UNINDICATED_WIDE, _lexicon_owns,
    _unindicated_fits, _owner_any, _op_spans, _unindicated_swap, r_unindicated_move, _claimed,
    r_unindicated_spare, HIDDEN_LINKS, r_hidden_link, r_hidden_possessive, r_swapped_pair, _misplaced_keys,
    _lex_types, _fits_charade, r_misplaced_indicator, _fold_link_word, r_shared_charade,
    r_split_shared_indicator,
)
from fix_shape_container import (
    _literal_pool, _inside_reading, r_container_inside, _holder_nest, r_nested_container, BOTH_ENDS,
    _cut_options, r_container_cut, r_extremes_outer, r_pool_outer, r_pool_gap, _has_letters,
    _eject_candidates, r_pool_absorb, r_pool_eject, _GAP_STOP, _span_of, r_container_gap, r_reversal_split,
    r_nested_same_op, r_del_wraps_charade,
)
from fix_shape_cuts import (
    r_sel_one_letter, SEL_FIRST, SEL_LAST, _SEL_PHRASE, _SELW, _SEL_PAIR, _del_selection_pair,
    r_del_selection, _at_named_end, r_deletion_inside, _cut_of, r_del_single, r_halved_deletion,
    r_moved_letter, _CUT_PUNCT, _CUT_LINKS, _cut_note_fulls, r_cut_note_leaf, r_del_one_piece, _single_pick,
    r_repeated_selection, r_sel_edge, r_leaf_select,
)
from fix_shape_ana import (
    _ana_candidates, _ana_split_candidates, r_ana_synonym_charade, r_ana_of_container, r_ana_charade,
    _piece_options, _spells, _stand_in, r_ana_pull, r_ana_edge, r_ana_select_edge, _ana_edge_with, _path, _at,
    r_scrambled_swap, r_ana_lone_edge, r_ana_flatten,
)
from fix_shape_notes import (
    INDICATOR_JOBS, unnoted_indicators, r_indicator_note, _block_note_for, _bound_removed_letter,
    unnoted_blocks, r_block_note, r_does_not_give, _does_not_give_edits, _anagram_fodder_edits, _printed_run,
    _hidden_reaches, _flat_charades, r_doubled_apostrophe, _single_apostrophe, fix_doubled_apostrophes,
    run_doubled_apostrophes, note_deletions,
)


DATA = Path(__file__).resolve().parent / "data"
SUSPECTS = DATA / "shape_suspects.json"
OUT = DATA / "shape_reannotate.json"


def r_wrong_role(node, parent, ctx):
    """wrongRole: a leaf that folds a deletion into its words (r_leaf_fold), else indicators on
    the wrong one of two nested ops (r_role_swap), a selection indicator hung on a one-letter word
    (r_sel_one_letter)."""
    return r_leaf_fold(node, parent, ctx) or r_extremes_outer(node, parent, ctx) \
        or r_role_swap(node, parent, ctx) or r_ind_trade(node, parent, ctx) \
        or r_container_cut(node, parent, ctx) or r_role_move(node, parent, ctx) or r_sel_one_letter(node, parent, ctx)


REPAIRS = {"ins_split": r_ins_split, "del_removed": r_del_removed, "del_unwrap": r_del_unwrap,
           "arity_wrap": r_arity_wrap, "half_cut": r_half_cut, "leaf_trim": r_leaf_trim, "ind_trim": r_ind_trim,
           "leaf_check": r_leaf_check, "link_leaf": r_link_leaf, "sel_literal": r_sel_literal}


RULE_REPAIRS = {"doubledApostrophe": r_doubled_apostrophe, "repeatedSelection": r_repeated_selection, "delWrapsCharade": r_del_wraps_charade,"nestedSameOp": r_nested_same_op, "delOnePiece": r_del_one_piece,"cutNoteLeaf": r_cut_note_leaf, "movedLetter": r_moved_letter, "halvedAsDeletion": r_halved_deletion, "reversalSplit": r_reversal_split, "reversedCharadeOrder": r_reversal_split,"anaLoneEdge": r_ana_lone_edge,"splitSharedIndicator": r_split_shared_indicator,
                "scrambledLeaf": r_scrambled_swap,"anaCharade": lambda n, p, c: r_ana_charade(n, p, c) or r_ana_pull(n, p, c) or r_ana_edge(n, p, c) or r_ana_flatten(n, p, c), "anaSelectEdge": r_ana_select_edge,
                "linkInLeaf": r_link_in_leaf, "indLeafOverlap": r_ind_leaf_overlap, "swappedPair": r_swapped_pair, "halfLeaf": r_half_leaf, "arity_other": lambda n, p, c: r_arity_other(n, p, c) or r_arity_ins(n, p, c),
                "unchecked_step": r_literal_fodder, "unchecked_leaf": r_removed_leaf, "arity_ins": r_arity_ins, "anaSynonym": r_ana_synonym_charade, "anagramOfContainer": r_ana_of_container,
                "containerInside": r_container_inside, "nestedContainer": r_nested_container,
                "wrongRole": r_wrong_role, "delSelection": r_del_selection,
                "sharedIndicator": lambda n, p, c: r_shared_indicator(n, p, c) or r_shared_charade(n, p, c), "poolGap": lambda n, p, c: r_pool_gap(n, p, c) or r_pool_absorb(n, p, c) or r_pool_eject(n, p, c),
                "misplacedIndicator": r_misplaced_indicator,
                "deletionInside": r_deletion_inside, "deletionScope": r_deletion_inside, "deletionScopeAnswer": r_deletion_inside,
                "unindicatedBare": lambda n, p, c: r_unindicated_move(n, p, c) or r_unindicated_spare(n, p, c) or r_hidden_link(n, p, c)
                or r_container_gap(n, p, c) or r_hidden_possessive(n, p, c) or r_unindicated_move(n, p, c, V.unindicated_ops) or r_unindicated_spare(n, p, c, V.unindicated_ops), "spanOverlap": r_span_overlap,
                "del_single": r_del_single, "indInLeaf": r_ind_in_leaf, "ind_in_leaf": r_ind_in_leaf,
                "selectWordInLeaf": r_own_ind_leaf, "ownIndInLeaf": r_own_ind_leaf, "truncInLeaf": r_trunc_leaf, "doesNotGive": r_does_not_give,
                "indicatorNote": r_indicator_note, "blockNote": r_block_note, "selectorInLeaf": r_leaf_select}


#: Chained after a rule's own repair, on the tree it produced: a role move leaves the selection
#: indicator both on the op and at the edge of its source leaf, and the leaf then loses it.
FOLLOW_ON = {"leaf_trim": r_leaf_trim, "ind_trim": r_ind_trim, "sel_edge": r_sel_edge, "leaf_select": r_leaf_select}


def repair_tree(tree, clue, answer=None, repairs=None):
    """(new tree, [repair names]) after applying repairs to a fixpoint (bottom-up)."""
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
                    if name in RULE_REPAIRS and _splices(new, parent):
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


# ---------- gate ----------

def hits(ann, clue, answer):
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


def shape_counts(ann):
    return collections.Counter(w.split(": ", 1)[1].split(":")[0] for w in V.shape_warnings("X", ann))


def clue_gate(old_ann, new_ann, clue, answer, old_hits):
    try:
        W.evaluate(copy.deepcopy(new_ann["wordplay"]), answer)
    except (W.WordplayError, IndexError, KeyError, TypeError):
        return None
    nh = hits(new_ann, clue, answer)
    if not set(nh) < set(old_hits):
        return None
    if unchecked(new_ann["wordplay"]) > unchecked(old_ann["wordplay"]):
        return None
    if shape_counts(new_ann) - shape_counts(old_ann):
        return None
    return nh


def puzzle_errors(puzzle, path, allowed, committed=None):
    """validate_annotations' errors for `puzzle`: validate_puzzle, the backlog
    ratchet and, given the file as committed, the selector check a changed
    annotation gets (check_against_committed's other checks look at the clue
    text and notes, which no repair touches; --deploy runs them all after --apply)."""
    _, errors, warnings = V.validate_puzzle(copy.deepcopy(puzzle))
    if committed is not None:
        real = VC.committed_entries
        VC.committed_entries = lambda _path: {V.entry_id(e): e for e in committed.get("entries", [])}
        try:
            V.check_selectors_are_indicators(copy.deepcopy(puzzle), path, errors)
        finally:
            VC.committed_entries = real
    return set(errors + V.backlog_errors(path.stem, warnings, allowed))


# ---------- driver ----------

def eid_of(e):
    return f"{e.get('number')}{(e.get('direction') or '?')[:1]}"


_JOB = None


def do_puzzle(pid):
    """One puzzle's results: (stat, det_hit, det_cleared, rep_used, examples, left)."""
    by_pid, paths, allowed, apply = _JOB
    stat, det_hit, det_cleared, rep_used = (collections.Counter() for _ in range(4))
    examples, left, fixed = [], [], []
    out = (stat, det_hit, det_cleared, rep_used, examples, left, fixed)
    path = paths.get(pid)
    if path is None:
        for s in by_pid[pid].values():
            left.append({"id": s["id"], "reason": "puzzle file not found; " + s["reason"]})
        stat["no_file"] += len(by_pid[pid])
        return out
    puzzle = json.loads(path.read_text(encoding="utf-8"))
    fixes, rows, normalized = [], {}, {}
    for k, e in enumerate(puzzle.get("entries") or []):
        s = by_pid[pid].get(eid_of(e))
        ann = e.get("annotation")
        if s is None or not ann:
            continue
        clue = (e.get("clue") or {}).get("text", "")
        answer = e.get("solution", "")
        # Letters that check in a non-canonical shape are rewritten by code first (tree_normalize),
        # never queued for the model; the rest go on to the repairs below.
        norm, used_norm = W.normalize(ann["wordplay"], clue, answer) if isinstance(ann.get("wordplay"), dict) else (None, [])
        if used_norm:
            ann = {**ann, "wordplay": norm}
            normalized[k] = ann
            stat["normalized"] += 1
        old = hits(ann, clue, answer)
        rows[eid_of(e)] = (s, old)
        if not old:
            continue
        for d in old:
            det_hit[d] += 1
        try:
            new_tree, used = repair_tree(ann["wordplay"], clue)
        except (W.WordplayError, IndexError, KeyError, TypeError, ValueError, RecursionError):
            continue
        if not used:
            continue
        new_ann = {**ann, "wordplay": new_tree}
        nh = clue_gate(ann, new_ann, clue, answer, old)
        if nh is None:
            stat["rejected_by_clue_gate"] += 1
            continue
        fixes.append((k, new_ann, {"id": s["id"], "clue": clue, "answer": answer, "old": old, "new": nh,
                                   "used": used, "before": cs.compact(ann["wordplay"]),
                                   "after": cs.compact(new_tree)}))
    stat["gone"] += len(by_pid[pid]) - sum(1 for s, old in rows.values() if old)
    kept = []
    if fixes:
        base = puzzle_errors(puzzle, path, allowed)

        def ok(fs, why=None):
            trial = copy.deepcopy(puzzle)
            for k, new_ann, _ in fs:
                trial["entries"][k]["annotation"] = new_ann
            errs = puzzle_errors(trial, path, allowed, committed=puzzle)
            if why is not None:
                why.extend(sorted(errs - base))
            return errs <= base
        if ok(fixes):
            kept = fixes
        else:
            for f in fixes:
                why = []
                if ok(kept + [f], why):
                    kept.append(f)
                else:
                    examples.append({**f[2], "rejected": why})
        stat["rejected_by_validator"] += len(fixes) - len(kept)
    kept_by_id = {f[2]["id"]: f for f in kept}
    for s, old in rows.values():
        if not old:
            continue
        f = kept_by_id.get(s["id"])
        remaining = f[2]["new"] if f else old
        for d in set(old) - set(remaining):
            det_cleared[d] += 1
        if f:
            stat["clues_repaired"] += 1
            for u in set(f[2]["used"]):
                rep_used[u] += 1
            examples.append(f[2])
        if remaining:
            left.append({"id": s["id"], "reason": "; ".join(f"{d}: {w}" for d, w in remaining.items())})
        else:
            stat["clues_clean"] += 1
            if f:
                fixed.append(s["id"])
    if kept or normalized:
        stat["puzzles_repaired"] += 1
        if apply:
            for k, new_ann in normalized.items():
                puzzle["entries"][k]["annotation"] = new_ann
            for k, new_ann, _ in kept:
                puzzle["entries"][k]["annotation"] = new_ann
            part = path.parent / f".{path.name}.part"
            part.write_text(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(part, path)
            stat["puzzles_written"] += 1
    return out


def merge_rows(left, fixed_ids, path=None):
    """Update the re-annotation list in place on --apply: drop only the rows of clues this
    run fixed outright, add the still-flagged clues it has no row for, and leave every
    other row (other sources', "tried" marks) exactly as filed."""
    import shape_queue
    path = Path(path or OUT)
    with shape_queue.locked():   # the burn's done() rewrites the same file
        have = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        keep = [r for r in have if r["id"] not in fixed_ids]
        seen = {r["id"] for r in have}
        keep += [r for r in left if r["id"] not in seen]
        shape_queue.write(shape_queue.dump(keep), path)


def load_ledger(ledger, key):
    """Finished puzzles from an earlier (killed) --apply run: {pid: result}. The ledger is
    only trusted for the same suspects file; a puzzle is logged after its file was written."""
    done = {}
    if ledger and Path(ledger).exists():
        for line in Path(ledger).read_text().splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue  # torn last line from a kill
            if d.get("key") == key:
                r = d["r"]
                done[d["pid"]] = tuple(collections.Counter(x) for x in r[:4]) + (r[4], r[5], r[6] if len(r) > 6 else [])
    return done


def run(apply, n_examples, seed, limit=None, jobs=4, ledger=None, only=None):
    global _JOB
    suspects = json.loads(SUSPECTS.read_text())["suspects"]
    if only:    # just the suspects whose reason names this detector
        suspects = [s for s in suspects if only in s["reason"].split("; ")[0].split(":")[0]]
    if limit:
        random.seed(seed)
        suspects = random.sample(suspects, limit)
    by_pid = collections.defaultdict(dict)
    for s in suspects:
        pid, eid = s["id"].split("#", 1)
        by_pid[pid][eid] = s
    paths = puzzle_paths.find_many(sorted(by_pid))
    _JOB = (by_pid, paths, V.load_backlog(), apply)
    stat, det_hit, det_cleared, rep_used = (collections.Counter() for _ in range(4))
    examples, left, fixed_ids = [], [], set()
    pids = sorted(by_pid)
    key = f"{hashlib.sha1(SUSPECTS.read_bytes()).hexdigest()}:{apply}:{limit}:{seed}"
    done = load_ledger(ledger, key)
    todo = [p for p in pids if p not in done]
    if done:
        print(f"  resuming: {len(done)} puzzles already done in {ledger}", file=sys.stderr, flush=True)
    if jobs > 1:
        pool = multiprocessing.get_context("fork").Pool(jobs)
        fresh = pool.imap(do_puzzle, todo, 8)
    else:
        fresh = map(do_puzzle, todo)

    def results():
        for p in pids:
            if p in done:
                yield done[p]
            else:
                r = next(fresh)
                if ledger:
                    with open(ledger, "a") as f:
                        f.write(json.dumps({"key": key, "pid": p, "r": [dict(x) for x in r[:4]] + list(r[4:])},
                                           ensure_ascii=False) + "\n")
                        f.flush()
                yield r
    for pi, r in enumerate(results()):
        if pi % 500 == 0:
            print(f"  {pi}/{len(pids)} puzzles", file=sys.stderr, flush=True)
        for a, b in zip((stat, det_hit, det_cleared, rep_used), r[:4]):
            a.update(b)
        examples += r[4]
        left += r[5]
        fixed_ids.update(r[6])
    left.sort(key=lambda r: r["id"])
    if apply:
        merge_rows(left, fixed_ids)
    print(f"suspects {len(suspects)} in {len(by_pid)} puzzles; " + ", ".join(f"{k} {v}" for k, v in sorted(stat.items())))
    print("detector       hits_now  cleared")
    for d in ss.DETECTORS:
        print(f"  {d:14} {det_hit[d]:7}  {det_cleared[d]:7}")
    print("repairs used (clues):", dict(rep_used))
    print(f"needs re-annotation: {len(left)} clues in {len({r['id'].split('#')[0] for r in left})} puzzles -> {OUT}")
    random.seed(seed)
    for x in random.sample(examples, min(n_examples, len(examples))):
        print(f"\n{x['id']} | {x['clue']} | {x['answer']}  [{', '.join(dict.fromkeys(x['used']))}]")
        print(f"  before: {x['before']}")
        print(f"  after:  {x['after']}")
        print(f"  cleared: {', '.join(sorted(set(x['old']) - set(x['new'])))}"
              + (f"; still: {', '.join(x['new'])}" if x["new"] else ""))


def do_rule_puzzle(pid):
    """--rule: one puzzle's queued rows of the rule; (stat, examples)."""
    by_pid, paths, allowed, apply, rule = _JOB
    stat, examples = collections.Counter(), []
    path = paths.get(pid)
    if path is None:
        stat["no_file"] += len(by_pid[pid])
        return stat, examples
    import shape_queue
    puzzle = json.loads(path.read_text(encoding="utf-8"))
    # delSelection is no validator rule: its rows come from --ids, every one is tried
    count = shape_queue._validator_rules().get(rule) or _DETECTOR_RULES.get(rule) or (lambda wp, full, clue: False)
    fixes = []
    for k, e in enumerate(puzzle.get("entries") or []):
        if shape_queue.clue_key(e) not in by_pid[pid]:
            continue
        ann = e.get("annotation")
        if not ann or not isinstance(ann.get("wordplay"), dict):
            continue
        stat["rows"] += 1
        clue = (e.get("clue") or {}).get("text", "")
        answer = shape_queue._answer(e)
        wp = ann["wordplay"]
        full = {**ann, "_answer": answer}
        if rule != "delSelection" and not count(wp, full, clue):
            stat["already_clear"] += 1
            continue
        try:
            new_tree, used = repair_tree(wp, clue, answer, {rule: RULE_REPAIRS[rule]})
            if used:
                new_tree = note_deletions(repair_tree(new_tree, clue, answer, FOLLOW_ON)[0])
        except (W.WordplayError, IndexError, KeyError, TypeError, ValueError, RecursionError):
            stat["error"] += 1
            continue
        if not used:
            stat["no_repair"] += 1
            continue
        try:
            W.evaluate(copy.deepcopy(new_tree), answer)
            norm, _ = W.normalize(new_tree, clue, answer)
            new_tree = norm
        except (W.WordplayError, IndexError, KeyError, TypeError, ValueError):
            stat["rejected_evaluate"] += 1
            continue
        new_ann = puzzle_schema.order({"entries": [{"annotation": {**ann, "wordplay": new_tree}}]})["entries"][0]["annotation"]
        new_tree = new_ann["wordplay"]
        old_h, new_h = hits(ann, clue, answer), hits(new_ann, clue, answer)
        if not set(new_h) <= set(old_h) or unchecked(new_tree) > unchecked(wp) \
                or shape_counts(new_ann) - shape_counts(ann):
            stat["rejected_gate"] += 1
            if os.environ.get("GATE_DEBUG"):
                print("GATE", pid, answer, sorted(set(new_h) - set(old_h)), unchecked(new_tree) - unchecked(wp),
                      dict(shape_counts(new_ann) - shape_counts(ann)), cs.compact(new_tree), file=sys.stderr)
            continue
        left = bool(count(new_tree, {**new_ann, "_answer": answer}, clue))
        fixes.append((k, new_ann, {"id": f"{pid}#{shape_queue.clue_key(e)}", "clue": clue, "answer": answer,
                                   "before": cs.compact(wp), "after": cs.compact(new_tree), "left": left}))
    kept = []
    if fixes:
        base = puzzle_errors(puzzle, path, allowed)

        def ok(fs, why=None):
            trial = copy.deepcopy(puzzle)
            for k, new_ann, _ in fs:
                trial["entries"][k]["annotation"] = new_ann
            errs = puzzle_errors(trial, path, allowed, committed=puzzle)
            if why is not None:
                why.extend(sorted(errs - base))
            return errs <= base
        if ok(fixes):
            kept = fixes
        else:
            for f in fixes:
                why = []
                if ok(kept + [f], why):
                    kept.append(f)
                else:
                    examples.append({**f[2], "rejected": why})
        stat["rejected_validator"] += len(fixes) - len(kept)
    for _, _, x in kept:
        stat["fixed_still_flagged" if x["left"] else "fixed_clear"] += 1
        examples.append(x)
    if kept and apply:
        for k, new_ann, _ in kept:
            puzzle["entries"][k]["annotation"] = new_ann
        part = path.parent / f".{path.name}.part"
        part.write_text(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(part, path)
        stat["puzzles_written"] += 1
    return stat, examples


#: Queue rows that name a shape_suspects detector, not a validator rule: how --rule counts them.
_DETECTOR_RULES = {"unchecked_leaf": lambda wp, full, clue: "unchecked_leaf" in hits(full, clue, full.get("_answer")),
                   "del_single": lambda wp, full, clue: V.del_single(wp),
                   "arity_ins": lambda wp, full, clue: V.arity_ins(wp),
                   "arity_other": lambda wp, full, clue: V.arity_other(wp),
                   "ind_in_leaf": lambda wp, full, clue: V.ind_in_leaf(wp, clue),
                   "indicatorNote": lambda wp, full, clue: unnoted_indicators(wp),
                   "blockNote": lambda wp, full, clue: unnoted_blocks(wp, full.get("_answer"))}


def run_rule(rule, apply, n_examples, seed, limit, jobs, ids=None):
    """Repair the queued rows of a validator rule (shape_reannotate.json rows naming `rule`)."""
    global _JOB
    import shape_queue
    if ids:
        rows = [{"id": x.strip()} for x in open(ids) if "#" in x]
    else:
        rows = [r for r in json.loads(shape_queue.PATH.read_text()) if rule in r.get("reason", "")]
    if limit:
        random.seed(seed)
        rows = random.sample(rows, limit)
    by_pid = collections.defaultdict(set)
    for r in rows:
        pid, _, clue = r["id"].partition("#")
        by_pid[pid].add(clue)
    paths = puzzle_paths.find_many(sorted(by_pid))
    _JOB = (by_pid, paths, V.load_backlog(), apply, rule)
    pids = sorted(by_pid)
    stat, examples = collections.Counter(), []
    pool = multiprocessing.get_context("fork").Pool(jobs) if jobs > 1 else None
    for s, ex in (pool.imap(do_rule_puzzle, pids, 8) if pool else map(do_rule_puzzle, pids)):
        stat.update(s)
        examples += ex
    print(f"{rule}: {len(rows)} queued rows in {len(pids)} puzzles; "
          + ", ".join(f"{k} {v}" for k, v in sorted(stat.items())))
    random.seed(seed)
    rejected = [x for x in examples if "rejected" in x]
    examples = [x for x in examples if "rejected" not in x]
    if rejected:   # why the validator turned a repair down: the errors the repaired puzzle gained
        kinds = collections.Counter(e[:90] for x in rejected for e in x["rejected"])
        print("rejected by validator, new errors:", dict(kinds.most_common(12)))
        for x in random.sample(rejected, min(n_examples, len(rejected))):
            print(f"\nREJECTED {x['id']} | {x['clue']} | {x['answer']}\n  before: {x['before']}\n  after:  {x['after']}")
            for e in x["rejected"]:
                print(f"  new error: {e[:300]}")
    for x in random.sample(examples, min(n_examples, len(examples))):
        print(f"\n{x['id']} | {x['clue']} | {x['answer']}" + ("  [still flagged]" if x["left"] else ""))
        print(f"  before: {x['before']}")
        print(f"  after:  {x['after']}")


def commit_batches(rule, per=500):
    """--commit: git-commit the puzzle files this run changed, `per` puzzles to a commit."""
    import subprocess
    root = Path(__file__).resolve().parent.parent
    files = subprocess.run(["git", "diff", "--name-only", "--", "puzzles"], cwd=root, capture_output=True,
                           text=True, check=True).stdout.split()
    for i in range(0, len(files), per):
        chunk = files[i:i + per]
        subprocess.run(["git", "add", "--", *chunk], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", f"Repair {rule}: {len(chunk)} puzzles mechanically\n\n"
                        "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"], cwd=root, check=True)
    print(f"committed {len(files)} puzzles in {-(-len(files) // per)} commits")


def main():
    ap =argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the repaired puzzles (see How to apply)")
    ap.add_argument("--examples", type=int, default=15)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--limit", type=int, help="a random sample of this many suspects (testing)")
    ap.add_argument("--jobs", type=int, default=4, help="worker processes (default 4)")
    ap.add_argument("--ledger", help="jsonl of finished puzzles: a re-run with the same suspects file resumes after them")
    ap.add_argument("--only", help="only suspects whose first detector is this one (e.g. arity_ins)")
    ap.add_argument("--rule", choices=sorted(RULE_REPAIRS),
                    help="repair the queued rows of this validator rule instead of the suspects "
                         "(tools/data/shape_reannotate.json is not touched: run prune_shape_queue.py --write after)")
    ap.add_argument("--ids", help="with --rule delSelection: file of '<puzzle>#<clue>' ids to try (e.g. 5d, 30a)")
    ap.add_argument("--commit", action="store_true", help="with --rule --apply: commit the changed puzzles, 500 to a commit")
    ap.add_argument("--container-inside", action="store_true",
                    help="repair only the queued containerInside rows (--limit N samples; --apply writes puzzles)")
    ap.add_argument("--doubled-apostrophes", action="store_true",
                    help="mend Guardian''s -> Guardian's in every clue and annotation (--apply writes)")
    a = ap.parse_args()
    if a.doubled_apostrophes:
        run_doubled_apostrophes(a.apply)
        return
    if a.container_inside:
        run_rule("containerInside", a.apply, a.examples, a.seed, a.limit, a.jobs)
        return
    if a.rule:
        run_rule(a.rule, a.apply, a.examples, a.seed, a.limit, a.jobs, a.ids)
        if a.commit:
            commit_batches(a.rule)
        return
    run(a.apply, a.examples, a.seed, a.limit, a.jobs, a.ledger, a.only)


if __name__ == "__main__":
    main()
