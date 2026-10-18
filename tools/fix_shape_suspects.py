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
    python3 tools/tidy_wordplay_shapes.py puzzles/ --write   # tighten the shape allowances
    git add -- puzzles/ tools/annotation_backlog.json tools/data/shape_reannotate.json
    git commit -m "Repair N mechanical wordplay shape faults in M puzzles ..."
    git fetch && git rebase origin/master && git push origin HEAD:master

Nothing is un-hinted and nothing becomes due by this sweep; the re-annotation list
is a separate queue decision.
"""
import argparse
import collections
import copy
import hashlib
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
import shape_suspects as ss
import validate_annotations as V
import wordplay as W

DATA = Path(__file__).resolve().parent / "data"
SUSPECTS = DATA / "shape_suspects.json"
OUT = DATA / "shape_reannotate.json"
UNARY = ("reversal", "cycling", "hidden") + W.SELECT

TAIL = re.compile(r"end|tail|last|finish|clos|short|almost|most|nearly|brief|large|main|quite|incomplete|"
                  r"unfinish|curtail|dock|abridg|truncat|clip|bottom|all but|not all|not entirely|"
                  r"not fully|not completely|partly|practically|virtually|cut off|chopped", re.I)
HEAD = re.compile(r"head|top|first|start|lead|open|initial|front|begin|scalp|decapit|behead|cap", re.I)
MID = re.compile(r"heart|middle|centre|center|core|gut|empt|void|hollow|insides", re.I)


# ---------- tree helpers ----------

def walk(node, parent=None):
    yield node, parent
    for p in node.get("parts") or []:
        yield from walk(p, node)


def leaf(node):
    return "op" not in node


def span(node):
    """(start, end) of the clue words under `node`, or None if any leaf lacks `at`."""
    lo, hi = None, None
    for n, _ in walk(node):
        if leaf(n):
            if "words" not in n:
                continue
            if n.get("at") is None:
                return None
            a, b = n["at"], n["at"] + len(n["words"])
            lo, hi = (a, b) if lo is None else (min(lo, a), max(hi, b))
    return None if lo is None else (lo, hi)


def vals(node):
    """values() or None when it can't be known alone."""
    try:
        v = W.values(node)
    except (W.WordplayError, IndexError, KeyError, TypeError, W._NeedTarget):
        return None
    return v


def gives_ok(node, want):
    try:
        return W.match(copy.deepcopy(node), want) is not None
    except (W.WordplayError, IndexError, KeyError, TypeError, W._NeedTarget):
        return False


def checked(node, **kw):
    """`node` with its unchecked flag and filed letters gone, `kw` set."""
    out = {k: v for k, v in node.items() if k not in ("unchecked", "gives")}
    out.update(kw)
    return out


def charade(parts):
    flat = []
    for p in parts:
        if p.get("op") == "charade" and not p.get("indicators") and not p.get("unchecked") and "gives" not in p:
            flat += p["parts"]
        else:
            flat.append(p)
    # Neighbouring leaves on the same clue words are one leaf.
    out = []
    for p in flat:
        q = out[-1] if out else None
        if q is not None and leaf(p) and leaf(q) and p.get("words") and p.get("words") == q.get("words") \
                and p.get("at") == q.get("at") and not p.get("unchecked") and not q.get("unchecked"):
            out[-1] = {**q, "gives": W.leaf_letters(q) + W.leaf_letters(p)}
        else:
            out.append(p)
    return out[0] if len(out) == 1 else {"op": "charade", "parts": out}


def clue_text(clue, a, b):
    """The clue's words between a and b, trimmed of spaces and edge punctuation; (text, start)."""
    s = clue[a:b]
    lead = len(s) - len(s.lstrip(" ,;:.!?—–-\"“”‘(){}[]"))
    s = s.strip(" ,;:.!?—–-\"“”‘(){}[]")
    return s, a + lead


# ---------- repairs: each takes (node, parent, ctx) and returns a replacement or None ----------

def r_ins_split(node, parent, ctx):
    if node.get("op") != "container" or len(node.get("parts") or []) == 2 or not node.get("unchecked"):
        return None
    parts = node["parts"]
    if len(parts) == 1:
        c = parts[0]
        if c.get("op") != "charade" or c.get("indicators") or c.get("unchecked"):
            return None
        parts = c["parts"]
    want = W.letters(node.get("gives"))
    if len(parts) < 3 or not want:
        return None
    spans = [span(p) for p in parts]
    if any(s is None for s in spans):
        return None
    found = set()
    for ind in node.get("indicators") or []:
        if ind.get("at") is None:
            continue
        a, b = ind["at"], ind["at"] + len(ind["text"])
        side = []
        for s in spans:
            if s[1] <= a:
                side.append("B")
            elif s[0] >= b:
                side.append("A")
            else:
                side = None
                break
        if not side:
            continue
        for g in "AB":
            idx = [i for i, x in enumerate(side) if x == g]
            if idx and idx[0] > 0 and idx[-1] < len(parts) - 1 and idx == list(range(idx[0], idx[-1] + 1)):
                found.add((idx[0], idx[-1]))
    if len(found) > 1 or (not found and len(parts) != 3):
        return None

    def build(i, j):
        inner = charade(copy.deepcopy(parts[i:j + 1]))
        outer = charade(copy.deepcopy(parts[:i] + parts[j + 1:]))
        for arm in (inner, outer):
            seen = [(p.get("words"), p.get("at")) for p in arm.get("parts") or [] if leaf(p) and p.get("words")]
            if len(seen) != len(set(seen)):
                return None     # the same clue words twice in one arm: a container inside it
        new = checked(node, parts=[outer, inner])
        return new if gives_ok(new, want) else None
    if found:
        return build(*found.pop())
    # No indicator position decides it (it sits inside a part's words or the parts are unplaced):
    # a flat 3-part charade is part 2 inside parts 1+3, when no other single part held
    # by the other two also spells the answer.
    if any(not leaf(p) or p.get("unchecked") for p in parts):
        return None
    reads = [build(i, i) for i in range(3)]
    return reads[1] if reads[1] and not reads[0] and not reads[2] else None


def r_del_removed(node, parent, ctx):
    if node.get("op") != "deletion" or len(node.get("parts") or []) != 1 or not node.get("unchecked"):
        return None
    inds = [i.get("text") or "" for i in node.get("indicators") or []]
    if len(inds) != 1:
        return None
    tail, head, mid = bool(TAIL.search(inds[0])), bool(HEAD.search(inds[0])), bool(MID.search(inds[0]))
    if tail + head + mid != 1:
        return None
    want = W.letters(node.get("gives"))
    vs = vals(node["parts"][0])
    if not want or not vs or len(vs) != 1:
        return None
    v = next(iter(vs))
    m = len(v) - len(want)
    if not 1 <= m <= 3:
        return None
    if tail and v.startswith(want):
        gone = v[len(want):]
    elif head and v.endswith(want):
        gone = v[:m]
    elif mid and len(v) > m + 1:
        # A central run: the letters kept either side differ in number by at most one.
        k = (len(v) - m) // 2
        cuts = {j for j in (k, len(v) - m - k) if v[:j] + v[j + m:] == want}
        if len(cuts) != 1:
            return None
        j = cuts.pop()
        gone = v[j:j + m]
    else:
        return None
    new = checked(node, parts=[copy.deepcopy(node["parts"][0]), {"gives": gone}])
    return new if gives_ok(new, want) else None


def _inside_leaf(ind, tree):
    """Whether the indicator's words sit inside a leaf's clue words."""
    t = W.letters(ind.get("text"))
    for n, _ in walk(tree):
        if leaf(n) and n.get("words"):
            if ind.get("at") is not None and n.get("at") is not None:
                if n["at"] <= ind["at"] and ind["at"] + len(ind.get("text") or "") <= n["at"] + len(n["words"]):
                    return True
            elif t and t in [W.letters(w) for w in n["words"].split()] and W.letters(n["words"]) != t:
                return True
    return False


def r_del_unwrap(node, parent, ctx):
    """A one-part deletion whose part already gives the node's letters removes nothing:
    the removal is inside a leaf's letters. The node goes when its own indicators are
    none or sit inside a leaf's words (the leaf already reads them)."""
    if node.get("op") != "deletion" or len(node.get("parts") or []) != 1 or not node.get("unchecked"):
        return None
    want = W.letters(node.get("gives"))
    child = node["parts"][0]
    if not want or not gives_ok(child, want):
        return None
    if not all(_inside_leaf(i, ctx["tree"]) for i in node.get("indicators") or []):
        return None
    return copy.deepcopy(child)


def r_link_leaf(node, parent, ctx):
    """An unchecked leaf filed with no letters (a link or position word) is an
    indicator of its op, its note kept; the op keeps two or more parts."""
    if leaf(node) or node.get("op") != "charade" or node.get("unchecked"):
        return None
    parts = node.get("parts") or []
    k = [i for i, p in enumerate(parts) if leaf(p) and p.get("unchecked") and p.get("words")
         and not W.letters(p.get("gives"))]
    if len(k) != 1 or len(parts) - 1 < 2:
        return None
    p = parts[k[0]]
    ind = {"text": p["words"], **({"at": p["at"]} if "at" in p else {}),
           **({"note": p["note"]} if p.get("note") else {})}
    new = copy.deepcopy(node)
    new["parts"] = [copy.deepcopy(x) for i, x in enumerate(parts) if i != k[0]]
    new["indicators"] = (new.get("indicators") or []) + [ind]
    return new


def r_sel_literal(node, parent, ctx):
    """An unchecked leaf under a selection op, filed with the selection's result:
    the selection over its own words gives those letters, so it is literal."""
    if leaf(node) or node.get("op") not in W.SELECT or len(node.get("parts") or []) != 1:
        return None
    p = node["parts"][0]
    if not leaf(p) or not p.get("unchecked") or not p.get("words"):
        return None
    want = W.letters(node.get("gives")) if node.get("unchecked") else W.letters(p.get("gives"))
    if not want:
        return None
    lit = {k: v for k, v in p.items() if k not in ("unchecked", "gives")}
    new = checked(node, parts=[lit]) if node.get("unchecked") else {**copy.deepcopy(node), "parts": [lit]}
    return new if vals(new) == {want} else None


def r_arity_wrap(node, parent, ctx):
    op, parts = node.get("op"), node.get("parts") or []
    want = W.letters(node.get("gives"))
    if not node.get("unchecked") or not want:
        return None
    cands = []
    def P():
        return copy.deepcopy(parts)

    if op in UNARY and len(parts) >= 2:
        cands.append(checked(node, parts=[charade(P())]))
        p = P()
        cands.append(charade([checked(node, parts=[p[0]])] + p[1:]))
        p = P()
        cands.append(charade(p[:-1] + [checked(node, parts=[p[-1]])]))
    elif op == "deletion" and len(parts) >= 3:
        p = P()
        cands.append(checked(node, parts=[charade(p[:-1]), p[-1]]))
        p = P()
        cands.append(charade(p[:-2] + [checked(node, parts=p[-2:])]))
    elif op == "substitution" and len(parts) == 2:
        xs, news = vals(parts[0]), vals(parts[1])
        if not xs or not news or len(xs) != 1 or len(news) != 1:
            return None
        x, nw = next(iter(xs)), next(iter(news))
        inds = " ".join(i.get("text") or "" for i in node.get("indicators") or [])
        tail, head = bool(TAIL.search(inds)), bool(HEAD.search(inds))
        if tail == head:
            return None
        for k in range(len(want) - len(nw) + 1):
            if want[k:k + len(nw)] != nw or want[:k] != x[:k]:
                continue
            rest = want[k + len(nw):]
            if len(x) - len(rest) > k and x.endswith(rest):
                old = x[k:len(x) - len(rest)]
                # Only letters the indicator names: one or two at the end it names.
                if len(old) > 2 or not ((head and k == 0) or (tail and not rest)):
                    continue
                p = P()
                cands.append(checked(node, parts=[p[0], {"gives": old}, p[1]]))
    good = [c for c in cands if gives_ok(c, want)]
    uniq = {json.dumps(c, sort_keys=True): c for c in good}
    return next(iter(uniq.values())) if len(uniq) == 1 else None


def _trimmed_leaf(lf, a, b, clue):
    """`lf` without the clue span a..b at its start or end, or None."""
    if lf.get("at") is None or not lf.get("words") or clue[lf["at"]:lf["at"] + len(lf["words"])] != lf["words"]:
        return None
    la, lb = lf["at"], lf["at"] + len(lf["words"])
    if not (la <= a and b <= lb) or (a, b) == (la, lb):
        return None
    if a == la:
        text, at = clue_text(clue, b, lb)
    elif b == lb:
        text, at = clue_text(clue, la, a)
    else:
        return None
    if not W.letters(text):
        return None
    new = {**lf, "words": text, "at": at}
    return new


def r_leaf_trim(node, parent, ctx):
    if leaf(node) or not node.get("indicators") or node.get("unchecked") or id(node) in ctx["under_unchecked"]:
        return None         # only where the evaluator checks the trimmed leaf's letters
    clue = ctx["clue"]
    for ind in node["indicators"]:
        if ind.get("at") is None or not ind.get("text"):
            continue
        a, b = ind["at"], ind["at"] + len(ind["text"])
        for k, p in enumerate(node.get("parts") or []):
            if not leaf(p):
                continue
            new = _trimmed_leaf(p, a, b, clue)
            if new is None:
                continue
            before = vals(node) if not node.get("unchecked") else {W.letters(node.get("gives"))}
            literal = "gives" not in p or W.letters(p["gives"]) == W.letters(p["words"])
            tries = []
            plain = {x: y for x, y in new.items() if x not in ("gives", "unchecked")}
            if literal and node.get("unchecked"):
                continue        # its letters change and nothing above checks them
            if literal:
                tries.append(plain)
            else:
                if node.get("op") in W.SELECT:
                    tries.append(plain)
                tries.append(new)
            for t in tries:
                cand = copy.deepcopy(node)
                cand["parts"][k] = t
                if node.get("unchecked"):
                    if before and gives_ok(cand, next(iter(before))):
                        return cand
                elif before is not None and (vals(cand) or set()) & before:
                    return cand
    return None


def r_ind_trim(node, parent, ctx):
    if leaf(node) or not node.get("indicators"):
        return None
    clue = ctx["clue"]
    for n, ind in enumerate(node["indicators"]):
        if ind.get("at") is None or not ind.get("text"):
            continue
        a, b = ind["at"], ind["at"] + len(ind["text"])
        for p in node.get("parts") or []:
            if not leaf(p) or p.get("at") is None or not p.get("words"):
                continue
            la, lb = p["at"], p["at"] + len(p["words"])
            if not (a <= la and lb <= b) or (la, lb) == (a, b):
                continue
            if la == a:
                text, at = clue_text(clue, lb, b)
            elif lb == b:
                text, at = clue_text(clue, a, la)
            else:
                continue
            if not W.letters(text):
                continue
            cand = copy.deepcopy(node)
            cand["indicators"][n] = {**ind, "text": text, "at": at}
            return cand
    return None


def r_leaf_check(node, parent, ctx):
    if not leaf(node) or not node.get("unchecked") or not node.get("words"):
        return None
    if id(node) in ctx["under_unchecked"]:
        return None         # nothing above it would check the letters it gives
    g = W.letters(node.get("gives"))
    if not g or g == W.letters(node["words"]):
        return {k: v for k, v in node.items() if k not in ("unchecked", "gives")}
    if annotation.is_abbreviation(node):
        return {k: v for k, v in node.items() if k != "unchecked"}
    if parent is not None and parent.get("op") in W.SELECT:
        return None
    found = V.selector_in_block({"clueFragment": node["words"], "gives": g})
    if not found or node.get("at") is None:
        return None
    sel, rest = found
    words = node["words"]
    si, ri = words.find(sel), words.find(rest)
    if si < 0 or ri < 0:
        return None
    src = {"words": rest, "at": node["at"] + ri}
    ops = [op for op in ("first", "last", "middle")
           if g in (vals({"op": op, "parts": [src]}) or set())]
    if len(ops) != 1:
        return None
    return {"op": ops[0], "indicators": [{"text": sel, "at": node["at"] + si}], "parts": [src]}


REPAIRS = {"ins_split": r_ins_split, "del_removed": r_del_removed, "del_unwrap": r_del_unwrap,
           "arity_wrap": r_arity_wrap, "leaf_trim": r_leaf_trim, "ind_trim": r_ind_trim,
           "leaf_check": r_leaf_check, "link_leaf": r_link_leaf, "sel_literal": r_sel_literal}


def repair_tree(tree, clue):
    """(new tree, [repair names]) after applying repairs to a fixpoint (bottom-up)."""
    tree = copy.deepcopy(tree)
    had_at = any("at" in x for n, _ in walk(tree) for x in [n, *(n.get("indicators") or [])])
    try:
        # Stored trees mostly carry no offsets: place every span on a copy, as view() does.
        tree = W.locate(copy.deepcopy(tree), clue)
    except W.WordplayError:
        pass
    used = []
    ctx = {"clue": clue}
    for _ in range(12):
        ctx["under_unchecked"] = under_unchecked(tree)
        ctx["tree"] = tree
        changed = False
        for n, parent in reversed(list(walk(tree))):
            for name, fn in REPAIRS.items():
                try:
                    new = fn(n, parent, ctx)
                except (W.WordplayError, IndexError, KeyError, TypeError, ValueError):
                    new = None
                if new is None:
                    continue
                if parent is None:
                    tree = new
                else:
                    parent["parts"][[id(x) for x in parent["parts"]].index(id(n))] = new
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


def unchecked(tree):
    return sum(bool(n.get("unchecked")) for n, _ in walk(tree))


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
        real = V.committed_entries
        V.committed_entries = lambda _path: {V.entry_id(e): e for e in committed.get("entries", [])}
        try:
            V.check_selectors_are_indicators(copy.deepcopy(puzzle), path, errors)
        finally:
            V.committed_entries = real
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
    fixes, rows = [], {}
    for k, e in enumerate(puzzle.get("entries") or []):
        s = by_pid[pid].get(eid_of(e))
        ann = e.get("annotation")
        if s is None or not ann:
            continue
        clue = (e.get("clue") or {}).get("text", "")
        answer = e.get("solution", "")
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

        def ok(fs):
            trial = copy.deepcopy(puzzle)
            for k, new_ann, _ in fs:
                trial["entries"][k]["annotation"] = new_ann
            return puzzle_errors(trial, path, allowed, committed=puzzle) <= base
        if ok(fixes):
            kept = fixes
        else:
            for f in fixes:
                if ok(kept + [f]):
                    kept.append(f)
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
    if kept:
        stat["puzzles_repaired"] += 1
        if apply:
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the repaired puzzles (see How to apply)")
    ap.add_argument("--examples", type=int, default=15)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--limit", type=int, help="a random sample of this many suspects (testing)")
    ap.add_argument("--jobs", type=int, default=4, help="worker processes (default 4)")
    ap.add_argument("--ledger", help="jsonl of finished puzzles: a re-run with the same suspects file resumes after them")
    ap.add_argument("--only", help="only suspects whose first detector is this one (e.g. arity_ins)")
    a = ap.parse_args()
    run(a.apply, a.examples, a.seed, a.limit, a.jobs, a.ledger, a.only)


if __name__ == "__main__":
    main()
