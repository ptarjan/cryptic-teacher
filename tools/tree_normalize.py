#!/usr/bin/env python3
"""Rewrite wordplay trees into Paul's canonical forms by code, before any clue goes to a model.

    python3 tools/tree_normalize.py puzzles/times/times-28959.json ...     # dry run: counts, before/after
    python3 tools/tree_normalize.py --write puzzles/times/times-28959.json  # rewrite those files in place
    python3 tools/tree_normalize.py --write --all                           # every puzzle with an annotation

Paul (10-18): "the validators should just do the word math ... if it doesn't then you can usually
write code to convert it to the right format unless the model just totally made it up". A tree whose
letters check but whose shape is not canonical is rewritten here, so it never reaches the model's
re-annotation queue (tools/shape_queue.py); only a tree whose letters fail, and no rewrite fits,
is model-bound. A rewrite is kept only when wordplay.evaluate still gives the answer and the
shape finding it targets is gone, so the letters are what they were.

The forms (all pure functions on a stored tree, each returning the rewrite count):

  sink_deletion    del(a + b, x) -> a + del(b, x)  (letters come off one piece: the indicator
                   acts on that piece alone; SO + del<mostly>(LOW, W), not del<mostly>(SO+LOW, W)).
                   The validator's deletionInside is this.
  hoist_deletion   the reverse, a + del(b, x) -> del(a + b, x), kept so a tree can move either
                   way ("move between each other"); not run by normalize().
  merge_selects    outer<fringes of>(Argive) + outer(Greece) + outer(Anatolian) ->
                   outer<fringes of>(Argive, Greece, Anatolian): one indicator over adjacent
                   same-op first/last/middle/outer/... siblings, one op with a part per word.
  merge_reversals  JA + rev<over>(PAL) + rev(ONE) -> JA + rev<over>(ONE + PAL): adjacent reversal
                   siblings with one indicator are one reversal over a charade of their parts in
                   clue order (the reverse of the answer order they stand in).

normalize(tree, clue, answer) runs them to a fixpoint and returns (tree, [names]) or (tree, []).
fix_shape_suspects.repair_tree calls it first, so the shape sweep applies these too.
"""
import argparse
import copy
import itertools
import json
import re
import os
import sys

import wordplay
import validate_annotations as V


def _walk(node, parent=None):
    yield node, parent
    for p in node.get("parts") or []:
        if isinstance(p, dict):
            yield from _walk(p, node)


def _swap(tree, old, new):
    """`tree` with node `old` (by identity) replaced by `new`; returns the tree (new if old is root)."""
    if tree is old:
        return new
    for n, _ in _walk(tree):
        ps = n.get("parts") or []
        for i, p in enumerate(ps):
            if p is old:
                ps[i] = new
                return tree
    return tree


def _plain(n):
    return isinstance(n, dict) and not n.get("unchecked")


def _plain_charade(n):
    return n.get("op") == "charade" and not n.get("indicators") and not n.get("unchecked") and "gives" not in n


def _sinkable_charade(n):
    """A checked charade, with or without an indicator of its own (del(a + b <after>, x))."""
    return n.get("op") == "charade" and not n.get("unchecked") and "gives" not in n


def _flatten(tree):
    """Join indicator-less charades left inside charades by a rewrite; collapse one-part charades."""
    import tidy_wordplay_shapes as T
    T.flatten_tree(tree)
    for n, _ in list(_walk(tree)):
        if n.get("op") == "charade" and len(n.get("parts") or []) == 1 and not n.get("indicators") \
                and not n.get("unchecked"):
            tree = _swap(tree, n, n["parts"][0])
    return tree


def _gives(tree, answer):
    try:
        wordplay.evaluate(copy.deepcopy(tree), answer)
        return True
    except Exception:
        return False


# ---------- A: deletion over a charade <-> deletion inside one piece ----------

def _cut_candidates(node, comps=None):
    """Indexes of the charade's pieces the node's cut could come off, edge-preferred by the indicator."""
    comps = comps if comps is not None else node["parts"][0]["parts"]
    text = " ".join(str(i.get("text") or "") for i in node.get("indicators") or [])
    order = list(range(len(comps)))
    if V._DEL_END.search(text):
        order.reverse()
    return order


_HEAD_WORD = re.compile(r"\b(open\w*|head\w*|start\w*|begin\w*|first|top\w*|lead\w*|decapitat\w*|behead\w*|"
                        r"unopened|initial\w*|front)\b", re.I)
_END_WORD = re.compile(r"\b(mostly|most of|tail\w*|end(?:s|ing|less\w*)?|last|final\w*|finish\w*|"
                       r"unending)\b", re.I)
_EDGE_WORD = re.compile(r"\b(edges?|outsides?|extremities|boundar\w*|borders?|both ends|ends|outer)\b", re.I)


def _letters(s):
    return "".join(c for c in str(s).upper() if c.isalpha())


def _kind(text):
    """How the indicator places the cut: 'edges', 'head', 'end', 'both' (head and end named, either
    edge may do), 'mid' (heart words), or None for an indicator that names no place."""
    if _EDGE_WORD.search(text) and not re.search(r"\b(end|ending|endless\w*)\b", text, re.I):
        return "edges"
    h = bool(_HEAD_WORD.search(text) or V._DEL_HEAD.search(text))
    e = bool(_END_WORD.search(text) or V._DEL_END.search(text))
    if h and e:
        return "both"
    if h:
        return "head"
    if e:
        return "end"
    if V._DEL_HEART.search(text) or V._DEL_HALF.search(text):
        return "mid"
    return None


def _cut_sits(kind, piece, cut):
    """Whether `cut` (letters) sit in `piece` where the indicator kind says."""
    if not cut or cut not in piece and kind != "edges":
        return False
    if kind == "head":
        return piece.startswith(cut)
    if kind == "end":
        return piece.endswith(cut)
    if kind == "both":
        return piece.startswith(cut) or piece.endswith(cut)
    if kind == "edges":
        return (piece[:1] + piece[-1:] == cut) or piece.startswith(cut) or piece.endswith(cut)
    if kind == "mid":
        return cut in piece[1:-1]
    return cut in piece


def _placed(node, comps, cuts):
    """Indexes of the pieces the cut may sit on, per the indicator's own place word; empty when the
    letters sit nowhere right, or (no place named) when more than one piece could take them."""
    text = " ".join(str(i.get("text") or "") for i in node.get("indicators") or [])
    kind = _kind(text)
    try:
        cut_vals = [_letters("".join(v)) for v in itertools.product(*[wordplay.values(c) for c in cuts])]
    except Exception:
        return []
    ok = []
    for i in _cut_candidates(node, comps):
        try:
            vals = [_letters(v) for v in wordplay.values(comps[i])]
        except Exception:
            continue
        if any(_cut_sits(kind, v, c) for v in vals for c in cut_vals):
            ok.append(i)
    if kind is None and len(ok) != 1:
        return []
    return ok


def sink_deletion(tree, clue, answer):
    """del(a + b, x) -> a + del(b, x), in place where the tree is not itself replaced: (tree, count)."""
    done = 0
    for _ in range(20):
        step = _sink_once(tree, clue, answer)
        if step is None:
            break
        tree, done = step, done + 1
    return tree, done


def _sink_once(tree, clue, answer):
    """The tree with one flagged deletion sunk into a piece, or None when none can be."""
    for node, _parent in list(_walk(tree)):
        parts = node.get("parts") or []
        if node.get("op") != "deletion" or node.get("unchecked") or len(parts) < 2 \
                or not all(isinstance(p, dict) for p in parts) or not _sinkable_charade(parts[0]):
            continue
        comps, cuts = parts[0]["parts"], parts[1:]
        before = V.deletion_inside_component(tree, clue, answer)
        if not before:
            return None
        for i in _placed(node, comps, cuts):
            piece = comps[i]
            if piece.get("unchecked"):
                continue
            inner = {"op": "deletion", "indicators": copy.deepcopy(node.get("indicators")),
                     "parts": [copy.deepcopy(piece), *copy.deepcopy(cuts)]}
            if not inner["indicators"]:
                del inner["indicators"]
            try:
                got = wordplay.values(inner)
            except Exception:
                continue
            if not got or "" in got:
                continue
            # the charade keeps its own indicator ("after", ...) and any other keys it carried
            new = {**{k: copy.deepcopy(v) for k, v in parts[0].items() if k != "parts"},
                   "parts": [*copy.deepcopy(comps[:i]), inner, *copy.deepcopy(comps[i + 1:])]}
            trial = copy.deepcopy(tree)
            trial = _flatten(_swap(trial, _match(tree, trial, node), new))
            if _gives(trial, answer) and V.deletion_inside_component(trial, clue, answer) < before:
                return trial
    return None


def _match(orig, copy_tree, node):
    """The node of `copy_tree` standing where `node` stands in `orig` (same walk position)."""
    for (a, _), (b, _) in zip(_walk(orig), _walk(copy_tree)):
        if a is node:
            return b
    raise KeyError("node not in tree")


def hoist_deletion(tree, answer=None):
    """a + del(b, x) -> del(a + b, x): the reverse of sink_deletion, for a charade with exactly one
    checked deletion piece over a plain (non-charade) part. (tree, count)."""
    done = 0
    for node, _ in list(_walk(tree)):
        parts = node.get("parts") or []
        dels = [p for p in parts if isinstance(p, dict) and p.get("op") == "deletion" and _plain(p)]
        if node.get("op") != "charade" or node.get("indicators") or node.get("unchecked") or len(dels) != 1 \
                or len(dels[0].get("parts") or []) < 2 or dels[0]["parts"][0].get("op") == "charade":
            continue
        d = dels[0]
        pieces = [d["parts"][0] if p is d else p for p in parts]
        new = {"op": "deletion", "indicators": copy.deepcopy(d.get("indicators")),
               "parts": [{"op": "charade", "parts": copy.deepcopy(pieces)}, *copy.deepcopy(d["parts"][1:])]}
        if not new["indicators"]:
            del new["indicators"]
        trial = copy.deepcopy(tree)
        trial = _swap(trial, _match(tree, trial, node), new)
        if answer is None or _gives(trial, answer):
            return trial, done + 1
    return tree, done


# ---------- B1: a list of selections under one indicator ----------

def merge_selects(tree, answer):
    """Adjacent same-op selections, one carrying the indicator, become one op over several parts."""
    done = 0
    for node, _ in list(_walk(tree)):
        parts = node.get("parts") or []
        if node.get("op") != "charade" or node.get("unchecked") or len(parts) < 2:
            continue
        i = 0
        while i < len(parts):
            p = parts[i]
            if not (isinstance(p, dict) and p.get("op") in wordplay.SELECT and _plain(p) and len(p.get("parts") or []) == 1
                    and "op" not in p["parts"][0]):
                i += 1
                continue
            j = i + 1
            while j < len(parts) and isinstance(parts[j], dict) and parts[j].get("op") == p["op"] and _plain(parts[j]) \
                    and parts[j].get("n") == p.get("n") and len(parts[j].get("parts") or []) == 1 \
                    and "op" not in parts[j]["parts"][0]:
                j += 1
            run = parts[i:j]
            carriers = [r for r in run if r.get("indicators")]
            if len(run) >= 2 and len(carriers) == 1:
                merged = {k: copy.deepcopy(v) for k, v in carriers[0].items() if k != "parts"}
                merged["parts"] = [copy.deepcopy(r["parts"][0]) for r in run]
                trial = copy.deepcopy(tree)
                tnode = _match(tree, trial, node)
                tnode["parts"][i:j] = [merged]
                trial = _flatten(trial)
                if _gives(trial, answer):
                    tree, done = trial, done + 1
                    return merge_selects_more(tree, answer, done)
            i = j
    return tree, done


def merge_selects_more(tree, answer, done):
    t, n = merge_selects(tree, answer)
    return t, done + n


# ---------- B2: adjacent reversals with one indicator ----------

def merge_reversals(tree, answer):
    """rev<ind>(PAL) + rev(ONE) -> rev<ind>(ONE + PAL): (tree, count)."""
    done = 0
    for node, _ in list(_walk(tree)):
        parts = node.get("parts") or []
        if node.get("op") != "charade" or node.get("unchecked") or len(parts) < 2:
            continue
        i = 0
        while i < len(parts):
            def rev(p):
                return isinstance(p, dict) and p.get("op") == "reversal" and _plain(p) and len(p.get("parts") or []) == 1
            if not rev(parts[i]):
                i += 1
                continue
            j = i + 1
            while j < len(parts) and rev(parts[j]):
                j += 1
            run = parts[i:j]
            carriers = [r for r in run if r.get("indicators")]
            if len(run) >= 2 and len(carriers) == 1:
                inner = [copy.deepcopy(r["parts"][0]) for r in reversed(run)]
                merged = {k: copy.deepcopy(v) for k, v in carriers[0].items() if k != "parts"}
                merged["parts"] = [{"op": "charade", "parts": inner}]
                trial = copy.deepcopy(tree)
                tnode = _match(tree, trial, node)
                tnode["parts"][i:j] = [merged]
                trial = _flatten(trial)
                if _gives(trial, answer):
                    tree, done = trial, done + 1
                    t, n = merge_reversals(tree, answer)
                    return t, done + n
            i = j
    return tree, done


# ---------- the pass ----------

def normalize(tree, clue, answer):
    """(tree, [rewrite names]) with every canonical rewrite applied; the tree unchanged when its
    letters do not give the answer to begin with (that one is the model's, or another repair's)."""
    if not isinstance(tree, dict) or not _gives(tree, answer):
        return tree, []
    tree = copy.deepcopy(tree)
    used = []
    for name, fn in (("sink_deletion", lambda t: sink_deletion(t, clue, answer)),
                     ("merge_selects", lambda t: merge_selects(t, answer)),
                     ("merge_reversals", lambda t: merge_reversals(t, answer))):
        new, n = fn(copy.deepcopy(tree))
        if n and simplicity(new) < simplicity(tree) and indicators_kept(tree, new):
            tree, used = new, used + [name] * n
    return tree, used


def _indicator_texts(tree):
    return sorted(str(i.get("text") or "").lower() for n, _ in _walk(tree) for i in n.get("indicators") or []
                  if isinstance(i, dict))


def _op_count(tree):
    return sum(1 for n, _ in _walk(tree) if n.get("op") not in (None, "charade"))


def indicators_kept(before, after):
    """Paul (10-18): the tree matches the clue's wordplay, one op per indicator. A rewrite keeps
    exactly the indicators it started with (never folds ops carrying different indicator words into
    one, never drops or adds one) and never adds an op; so one indicator's several ops may merge
    into one, and a cut may sink, but nothing else changes how many ops the indicators justify."""
    return _indicator_texts(before) == _indicator_texts(after) and _op_count(after) <= _op_count(before)


def simplicity(tree):
    """Paul (10-18): "just pick the simplest one as canonical". Among trees giving the same letters
    the canonical one has the lowest key: (fewest ops, then fewest letters the ops act on). An op
    acts on the letters of its parts (a charade is no op, just pieces side by side), so
    SO + del(LOW, W) (4 letters) beats del(SO + LOW, W) (6), and one rev(ONE + PAL) beats two
    revs. A rewrite is kept only if it lowers this."""
    ops = letters = 0

    def size(n):
        nonlocal ops, letters
        if not isinstance(n, dict):
            return 0
        kids = n.get("parts") or []
        if "op" not in n:
            try:
                return max(map(len, wordplay.values(n)), default=0)
            except Exception:
                return len(str(n.get("gives") or n.get("words") or ""))
        sizes = [size(p) for p in kids]
        if n["op"] != "charade":            # a charade is only the pieces side by side: no op
            ops += 1
            letters += sum(sizes)
        try:
            return max(map(len, wordplay.values(n)), default=0)
        except Exception:
            return sum(sizes)
    size(tree)
    return ops, letters


def normalize_puzzle(puzzle):
    """Rewrite in place; [(entry id, names, before, after)] for the clues changed."""
    import clue_shapes as cs
    out = []
    for e in puzzle.get("entries") or []:
        ann = e.get("annotation")
        if not ann or not isinstance(ann.get("wordplay"), dict):
            continue
        clue = (e.get("clue") or {}).get("text", "")
        new, used = normalize(ann["wordplay"], clue, e.get("solution", ""))
        if used:
            out.append((f"{e.get('number')}{(e.get('direction') or '?')[:1]}", used,
                        cs.compact(ann["wordplay"]), cs.compact(new)))
            ann["wordplay"] = new
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="puzzle json files")
    ap.add_argument("--write", action="store_true", help="rewrite the files in place (a .part renamed over each)")
    ap.add_argument("--all", action="store_true", help="every file under puzzles/ (a full-corpus sweep: only when no other corpus job runs)")
    a = ap.parse_args()
    files = list(a.files)
    if a.all:
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "puzzles")
        files += sorted(os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs
                        if f.endswith(".json") and not f.startswith("."))
    clues = puzzles = 0
    for path in files:
        with open(path, encoding="utf-8") as fh:
            puzzle = json.load(fh)
        got = normalize_puzzle(puzzle)
        if not got:
            continue
        puzzles += 1
        clues += len(got)
        for eid, used, b, c in got:
            print(f"{os.path.basename(path)[:-5]}#{eid} [{', '.join(dict.fromkeys(used))}]\n  before: {b}\n  after:  {c}")
        if a.write:
            part = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.part")
            with open(part, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n")
            os.replace(part, path)
    print(f"{clues} clues in {puzzles} puzzles{' rewritten' if a.write else ' would change'}", file=sys.stderr)


if __name__ == "__main__":
    main()
