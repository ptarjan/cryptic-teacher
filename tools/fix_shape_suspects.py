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
import puzzle_schema
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


def simplicity(tree):
    """Canonical-form key among letter-equal trees (Paul: the simplest is canonical): the fewest
    ops, then each op acting on the fewest letters (the sum, over ops, of the letters of the
    leaves under it). Lower is simpler."""
    ops, letters = 0, 0
    for n, _ in walk(tree):
        if not leaf(n):
            ops += 1
            letters += sum(len(W.leaf_letters(x)) for x, _ in walk(n) if leaf(x))
    return ops, letters


def _eval_swapped(node, parent, new, ctx):
    """Whether the whole tree still gives the answer with `node` replaced by `new`."""
    answer = ctx.get("answer")
    if not answer:
        return False
    try:
        W.evaluate(_whole(node, parent, new, ctx), answer)
        return True
    except (W.WordplayError, IndexError, KeyError, TypeError, ValueError, W._NeedTarget):
        return False


def _whole(node, parent, new, ctx):
    """A copy of the whole tree with `node` replaced by `new` (a plain charade going into a
    plain charade is joined to it, as repair_tree does)."""
    if parent is None:
        return copy.deepcopy(new)
    i = [id(x) for x in parent["parts"]].index(id(node))
    saved = list(parent["parts"])
    try:
        if _splices(new, parent):
            parent["parts"][i:i + 1] = new["parts"]
        else:
            parent["parts"][i] = new
        return copy.deepcopy(ctx["tree"])
    finally:
        parent["parts"][:] = saved


def _flat_fodder(node):
    """The parts of an anagram, an indicator-free charade among them opened out."""
    out = []
    for p in node.get("parts") or []:
        if p.get("op") == "charade" and not p.get("indicators") and not p.get("unchecked"):
            out += p["parts"]
        else:
            out.append(p)
    return out


def _is_stand_in(p):
    """A leaf that gives other letters than its own words (a synonym), not a doubling."""
    if not leaf(p) or not p.get("words") or p.get("select"):
        return False
    g, w = W.letters(p.get("gives")), W.letters(p["words"])
    return len(g) >= 2 and g != w and not V._doubled(p) and not V._near_literal(p)


def _ana_candidates(node):
    """Rewrites of an anagram whose fodder holds synonyms: the synonyms charaded on, the
    anagram of the clue's own words kept (every order of the pieces); [] if none."""
    if node.get("op") != "anagram":
        return []
    flat = _flat_fodder(node)
    syn = [p for p in flat if _is_stand_in(p)]
    rest = [p for p in flat if not _is_stand_in(p)]
    if not syn or not rest or len(syn) > 3:
        return []
    if any(leaf(p) and p.get("gives") and W.letters(p["gives"]) != W.letters(p.get("words"))
           for p in rest):
        return []       # a part giving other letters that is not a synonym: not mechanical
    core = checked(node, parts=copy.deepcopy(rest))
    out = []
    import itertools
    for perm in itertools.permutations([*copy.deepcopy(syn), core]):
        out.append(charade(list(perm)))
    return out


def _plain_charade(n):
    return bool(n) and n.get("op") == "charade" and not n.get("indicators") and not n.get("unchecked") \
        and "gives" not in n


def _splices(new, parent):
    """1 when `new` is a plain charade going into a plain charade (repair_tree joins them)."""
    return int(_plain_charade(new) and _plain_charade(parent))


def _pick(node, parent, ctx, cands):
    """The simplest of the candidates that keep the answer; None unless it is simpler than
    `node` and the only one of that simplicity."""
    good = [c for c in cands if _eval_swapped(node, parent, c, ctx)]
    if not good:
        return None
    def key(c):      # the whole tree's key, so a joined charade is not counted twice
        return simplicity(_whole(node, parent, c, ctx))
    best = min(key(c) for c in good)
    top = {json.dumps(c, sort_keys=True): c for c in good if key(c) == best}
    if len(top) != 1 or best >= simplicity(ctx["tree"]):
        return None
    return next(iter(top.values()))


def r_ana_synonym(node, parent, ctx):
    """A synonym scrambled with the fodder: only the clue's own words are anagrammed, the
    synonym is charaded on at the end the answer's letters give."""
    return _pick(node, parent, ctx, _ana_candidates(node))


def r_ana_of_container(node, parent, ctx):
    """ana(ins(a, b)): the anagram sits inside the container, over one arm (its synonyms
    charaded beside it); the other arm stays as it was."""
    if node.get("op") != "anagram" or len(node.get("parts") or []) != 1:
        return None
    c = node["parts"][0]
    if c.get("op") != "container" or len(c.get("parts") or []) != 2 or c.get("unchecked"):
        return None
    cands = []
    for i in (0, 1):
        arm = c["parts"][i]
        base = {k: v for k, v in node.items() if k not in ("unchecked", "gives")}
        ana = {**copy.deepcopy(base), "parts": [copy.deepcopy(arm)]}
        for inner in [ana, *_ana_candidates(ana)]:
            parts = copy.deepcopy(c["parts"])
            parts[i] = inner
            cands.append(checked(c, parts=parts))
    return _pick(node, parent, ctx, cands)


def _inside_reading(node, tree, want):
    """(letters, whole) container_inside_component reads `node` on: a container right under
    reversals that are the whole tree is read on the answer turned back (an odd count of flips
    reverses it), whole; any other node is read on the answer, whole only when it is the tree."""
    top, flips = tree, 0
    while top.get("op") == "reversal" and not top.get("unchecked") and len(top.get("parts") or []) == 1 \
            and isinstance(top["parts"][0], dict):
        top, flips = top["parts"][0], flips + 1
    if flips and top is node:
        return (want[::-1] if flips % 2 else want), True
    return want, node is tree


def r_container_inside(node, parent, ctx):
    """ins(charade(a, b, c), x) whose x can only go inside ONE piece (container_inside_component):
    the container moves into that piece, charade(a, ins(b, x), c). Its indicators and note go
    with it (the container is what they signal); the charade's filed letters stay on the
    charade. _pick keeps it only when exactly one piece gives the simplest tree that still
    evaluates to the answer."""
    answer = ctx.get("answer")
    if not answer:
        return None
    want, whole = _inside_reading(node, ctx["tree"], W.letters(answer))
    if not V._container_inside(node, want, whole):
        return None
    holder, ins = node["parts"]
    if holder.get("indicators") or "unchecked" in holder:
        return None
    cands = []
    for k, c in enumerate(holder["parts"]):
        inner = {**{x: y for x, y in node.items() if x not in ("parts", "gives")},
                 "parts": [copy.deepcopy(c), copy.deepcopy(ins)]}
        if not vals(inner):
            continue
        parts = copy.deepcopy(holder["parts"])
        parts[k] = inner
        new = {x: y for x, y in holder.items() if x != "parts"}
        new.update({x: y for x, y in node.items() if x == "gives"})
        new["op"], new["parts"] = "charade", parts
        cands.append(new)
    # not _pick: with one letter beside the piece the two shapes tie on simplicity, yet the wide
    # holder is the one the validator flags; what matters is that exactly one piece takes it
    good = {json.dumps(c, sort_keys=True): c for c in cands if _eval_swapped(node, parent, c, ctx)}
    return next(iter(good.values())) if len(good) == 1 else None


def _holder_nest(outer):
    """(holder, x, y, inner) of outer = ins(inner = ins(holder, x), y), both checked 2-part containers."""
    parts = outer.get("parts") or []
    if outer.get("op") != "container" or outer.get("unchecked") or len(parts) != 2:
        return None
    inner = parts[0]
    ip = inner.get("parts") or []
    if inner.get("op") != "container" or inner.get("unchecked") or len(ip) != 2:
        return None
    return ip[0], ip[1], parts[1], inner


def r_nested_container(node, parent, ctx):
    """ins(ins(H, x), y), a container holding a container: the regroupings that put x and y into
    H together (H holds x+y, or y+x, as one charade; H holds ins(x, y) or ins(y, x)). Of those
    that evaluate to the answer, the simplest is kept: fewest ops, then fewest letters acted on,
    then the charade in clue order (Paul 10-18: "just pick the simplest one as canonical").
    A regrouping that would put two indicators on one op is rejected (one op per indicator)."""
    got = _holder_nest(node)
    answer = ctx.get("answer")
    if not got or not answer or V._separate_insertion(node, got[3]):
        return None
    h, x, y, inner = got
    if inner.get("indicators") and node.get("indicators"):
        return None     # one op per indicator (Paul 10-18): two indicators can't share the one container
    inds = copy.deepcopy((inner.get("indicators") or []) + (node.get("indicators") or []))
    ox, oy = span(x), span(y)
    xfirst = not (ox and oy and oy[0] < ox[0])
    pairs = [(x, y), (y, x)] if xfirst else [(y, x), (x, y)]
    cands = []
    for a, b in pairs:
        cands.append({"op": "container", "indicators": inds,
                      "parts": [copy.deepcopy(h), charade([copy.deepcopy(a), copy.deepcopy(b)])]})
    for a, b in pairs:
        cands.append({"op": "container", "indicators": inds,
                      "parts": [copy.deepcopy(h), {"op": "container", "parts": [copy.deepcopy(a), copy.deepcopy(b)]}]})
    good = []
    for k, c in enumerate(cands):
        if not inds:
            c.pop("indicators")
        try:
            W.evaluate(copy.deepcopy(c), answer)
        except (W.WordplayError, IndexError, KeyError, TypeError, ValueError):
            continue
        good.append(((simplicity(c), k), c))
    if not good:
        return None
    return min(good, key=lambda g: g[0])[1]


def r_leaf_fold(node, parent, ctx):
    """A leaf of 3+ words with a deletion word whose letters are one of its words with a run cut
    out (gates having lost a -> GTES): the deletion op over that word, the cut a leaf of its own
    when another word of the leaf spells it, else the indicator names the end it comes from
    (r_del_removed). A leaf that gives exactly one of its own words keeps just that word."""
    if not leaf(node) or node.get("unchecked") or not node.get("words") or not node.get("gives") \
            or node.get("at") is None:
        return None
    if id(node) in ctx["under_unchecked"]:
        return _fold_two_cuts(node, ctx)    # its letters are checked on their own, wherever it sits
    toks = node["words"].split()
    if len(toks) < 3 or len(node["gives"]) > 4 or not V._deletion_word_in(node["words"], node["gives"]):
        return None
    g = W.letters(node["gives"])
    clue = ctx["clue"]
    pos, at = [], node["at"]
    for t in toks:
        i = clue.find(t, at)
        if i < 0:
            return None
        pos.append((t, i))
        at = i + len(t)
    plain = lambda t: W.letters(t)
    delw = [k for k, (t, _) in enumerate(pos) if V.DELETION_LEAF_WORD.fullmatch(re.sub(r"\W", "", t))]
    outs = []
    for k, (t, i) in enumerate(pos):
        w = plain(t)
        if k in delw or not w:
            continue
        if w == g:
            outs.append(("lit", k, ""))
            continue
        if len(g) < len(w):
            for j in range(len(w)):
                for m in range(1, len(w) - len(g) + 1):
                    if w[:j] + w[j + m:] == g:
                        outs.append(("cut", k, w[j:j + m]))
    cuts = {(kind, k, gone) for kind, k, gone in outs}
    if len({(k, kind) for kind, k, _ in cuts}) != 1:
        return _fold_two_cuts(node, ctx) if not outs else None
    kind, k, _ = next(iter(cuts))
    wleaf = {"words": pos[k][0], "at": pos[k][1]}
    if kind == "lit":
        return wleaf
    rest = [p for q, p in enumerate(pos) if q != k]
    gones = {gone for kd, kk, gone in cuts}
    for q, (t, i) in enumerate(pos):
        if q != k and q not in delw and (plain(t) in gones or any(
                annotation.is_abbreviation({"words": t, "gives": x}) for x in gones)):
            ind = [p for r, p in enumerate(pos) if r not in (k, q)]
            ind_txt = " ".join(t2 for t2, _ in ind)
            if not ind or not clue[ind[0][1]:ind[-1][1] + len(ind[-1][0])] .replace("  ", " ") == ind_txt:
                return None
            cut = {"words": t, "at": i}
            if plain(t) not in gones:    # a table abbreviation (five -> V): the cut names its letters
                cut["gives"] = next(x for x in sorted(gones) if annotation.is_abbreviation({"words": t, "gives": x}))
            new = {"op": "deletion", "indicators": [{"text": ind_txt, "at": ind[0][1]}], "parts": [wleaf, cut]}
            return new if gives_ok(new, g) or g in (vals(new) or ()) else None
    ind_txt = " ".join(t for t, _ in rest)
    ind = {"text": ind_txt, "at": rest[0][1]}
    if clue[rest[0][1]:rest[-1][1] + len(rest[-1][0])] != ind_txt:
        return None
    probe = {"op": "deletion", "unchecked": True, "gives": g, "indicators": [ind], "parts": [wleaf]}
    return r_del_removed(probe, parent, ctx)


def _fold_two_cuts(node, ctx):
    """A leaf folding two cuts out of one word (Labour's lacking a British -> LOUR): a deletion
    word, a source word, and two words that each spell (or abbreviate, by the table) a run of the
    source; the deletion op over the source and both cuts, when its letters give the leaf's."""
    toks = node["words"].split()
    if len(toks) != 4 or not V._deletion_word_in(node["words"]):
        return None
    clue, g = ctx["clue"], W.letters(node["gives"])
    pos, at = [], node["at"]
    for t in toks:
        i = clue.find(t, at)
        if i < 0:
            return None
        pos.append((t, i))
        at = i + len(t)
    delw = [k for k, (t, _) in enumerate(pos) if V.DELETION_LEAF_WORD.fullmatch(re.sub(r"\W", "", t))]
    if len(delw) != 1:
        return None
    d = delw[0]
    found = []
    for k, (t, i) in enumerate(pos):
        stem = re.sub(r"['’]s$", "", t)
        w = W.letters(stem)
        if k == d or len(w) <= len(g):
            continue
        cutpos = [q for q in range(4) if q not in (d, k)]
        for order in (cutpos, cutpos[::-1]):
            opts = [[x for x in {w[a:b] for a in range(len(w)) for b in range(a + 1, len(w) + 1)}
                     if W.letters(pos[q][0]) == x or annotation.is_abbreviation({"words": pos[q][0], "gives": x})]
                    for q in order]
            for x1 in opts[0]:
                for x2 in opts[1]:
                    if w.replace(x1, "", 1).replace(x2, "", 1) == g and len(x1) + len(x2) == len(w) - len(g):
                        found.append((k, stem, order, x1, x2))
    if len({(f[0], tuple(sorted(zip(f[2], f[3:])))) for f in found}) != 1:
        return None
    k, stem, order, x1, x2 = found[0]
    ind_tok = pos[d]
    # the deletion word and the cuts keep clue order; the indicator is the deletion word alone
    cuts = [{"words": pos[q][0], "at": pos[q][1], "gives": x} for q, x in sorted(zip(order, (x1, x2)))]
    src = {"words": stem, "at": pos[k][1]}
    new = {"op": "deletion", "indicators": [{"text": ind_tok[0], "at": ind_tok[1]}], "parts": [src, *cuts]}
    return new if gives_ok(new, g) else None


def _role_owner(ind):
    """The op type the corpus files an indicator's words under (at least ROLE_MIN_USES uses, and
    ROLE_SWAP_OWNED of them one type), else None."""
    counts = V._role_counts(V.indicator_role_key(ind.get("text")))
    total = sum(counts.values())
    if total < V.ROLE_MIN_USES:
        return None
    top = max(counts, key=counts.get)
    return top if counts[top] >= V.ROLE_SWAP_OWNED * total else None


def r_role_swap(node, parent, ctx):
    """Indicators filed on the wrong one of two nested ops. The ops swap them when each carries
    a word the corpus files under the other's type (ins<returned>(rev<opened by>(..), ..) is
    ins<opened by>(rev<returned>(..), ..)); an op with no indicator of its own takes the word
    its parent carries for its type (ana<ignoring>(del(..)) is ana(del<ignoring>(..)), a first
    op under ins<head>). Words move whole; the letters are untouched."""
    kind = V._OP_LEXICON.get(node.get("op"))
    if not kind or not parent or node.get("unchecked") or parent.get("unchecked") \
            or id(node) in ctx["under_unchecked"]:
        return None
    pkind = V._OP_LEXICON.get(parent.get("op"))
    if parent.get("op") != "charade" and not pkind:
        return None
    mine, theirs = node.get("indicators") or [], parent.get("indicators") or []
    if pkind and pkind != kind and not V._swap_alike(pkind, kind):
        for a in mine:
            if _role_owner(a) != pkind:
                continue
            for b in theirs:
                if V._swap_alike(_role_owner(b), kind):
                    mine[mine.index(a)], theirs[theirs.index(b)] = b, a
                    return node
    if not mine and kind != pkind:
        for b in theirs:
            if _role_owner(b) == kind:
                theirs.remove(b)
                node["indicators"] = [b]
                if not theirs:
                    parent.pop("indicators", None)
                return node
    return _swap_unknown(node, parent, ctx)


def _gated(ctx, nodes, mutate):
    """Run `mutate` (it edits the indicators of `nodes` in place); keep it only when the validator
    then counts fewer wrong-role indicators in the whole tree, else put the indicators back."""
    before = V.wrong_role_indicators(ctx["tree"])
    saved = [(n, list(n["indicators"]) if "indicators" in n else None) for n in nodes]
    mutate()
    if V.wrong_role_indicators(ctx["tree"]) < before:
        return True
    for n, ind in saved:
        if ind is None:
            n.pop("indicators", None)
        else:
            n["indicators"] = ind
    return False


def _swap_unknown(node, parent, ctx):
    """A child op holding its parent's word while the parent holds a word the corpus has no
    owner for (ana<crossing> inside ins<frenziedly>): the two trade places when that clears the
    flag. A parent word the corpus files under the child's type counts as a match too."""
    kind, pkind = V._OP_LEXICON.get(node.get("op")), V._OP_LEXICON.get(parent.get("op"))
    if not kind or not pkind or kind == pkind:
        return None
    mine, theirs = node.get("indicators") or [], parent.get("indicators") or []
    for a in mine:
        if _role_owner(a) != pkind:
            continue
        for b in theirs:
            if _role_owner(b) not in (None, kind) or _role_owner(b) == pkind:
                continue

            def swap():
                mine[mine.index(a)], theirs[theirs.index(b)] = b, a
            if _gated(ctx, [node, parent], swap):
                return node
    return None


def r_role_move(node, parent, ctx):
    """Indicators filed on ops of another type than the corpus files them under, redealt: each
    word goes to the one checked op of its own type that has no indicator of its own (or only
    misfiled ones), when every misfiled word finds exactly one such op and the whole tree then
    counts fewer wrong-role indicators. Covers a word moved down from an enclosing charade
    (charade<mistakenly>(BUSH, ana<ignoring>(del(..))) is charade(BUSH, ana<mistakenly>(
    del<ignoring>(..)))), a word moved to a sibling, and a three-way rotation. Run once, at the root."""
    if parent is not None:
        return None
    ops = [x for x, _ in walk(node) if (V._OP_LEXICON.get(x.get("op")) or x.get("op") == "charade")
           and not x.get("unchecked") and id(x) not in ctx["under_unchecked"]]
    misfiled = {}   # id(op) -> [(indicator, owner)]
    for x in ops:
        kind = V._OP_LEXICON.get(x.get("op"))
        for b in x.get("indicators") or []:
            owner = _role_owner(b)
            if owner and owner != kind and not (kind and V._swap_alike(owner, kind)):
                misfiled.setdefault(id(x), []).append((b, owner))
    if not misfiled:
        return None
    needy = collections.defaultdict(list)
    for x in ops:
        kind = V._OP_LEXICON.get(x.get("op"))
        if kind and len(x.get("indicators") or []) == len(misfiled.get(id(x), [])):
            needy[kind].append(x)
    moves = collections.defaultdict(list)   # owner -> [(holder, indicator)]
    for x in ops:
        for b, owner in misfiled.get(id(x), []):
            moves[owner].append((x, b))
    plan = []
    for owner, ms in moves.items():
        if len(ms) != 1 or len(needy[owner]) != 1:
            return None
        plan.append((ms[0][0], ms[0][1], needy[owner][0]))
    touched = {id(x): x for h, _, t in plan for x in (h, t)}
    inds = {id(x): [i for i in x.get("indicators") or [] if all(i is not b for h, b, _ in plan if h is x)]
            for x in touched.values()}

    def deal():
        for h, b, t in plan:
            inds[id(t)].append(b)
        for k, x in touched.items():
            if inds[k]:
                x["indicators"] = inds[k]
            else:
                x.pop("indicators", None)
    return node if _gated(ctx, list(touched.values()), deal) else None


def r_sel_one_letter(node, parent, ctx):
    """A selection op over a one-letter word (first<lead from>([a]) in 'a lead from Monica'): the
    indicator was hung on the wrong word. It belongs to the one other leaf of the tree whose words
    sit right beside it in the clue (or hold it at an edge), filed with the letters that selection
    gives: that leaf becomes the selection op over its source, and the one-letter word is a plain
    leaf again. Exactly one such leaf, and the op must give its letters."""
    parts = node.get("parts") or []
    if node.get("op") not in W.SELECT or node.get("unchecked") or len(parts) != 1 or not leaf(parts[0]) \
            or len(node.get("indicators") or []) != 1 or not V.selection_of_one_letter(node):
        return None
    ind = node["indicators"][0]
    it, ia = ind.get("text") or "", ind.get("at")
    clue = ctx["clue"]
    if not it or ia is None or clue[ia:ia + len(it)] != it:
        return None
    ib = ia + len(it)
    inside = {id(x) for x, _ in walk(node)}
    found = []
    for lf, _ in walk(ctx["tree"]):
        if id(lf) in inside or not leaf(lf) or not lf.get("words") or lf.get("at") is None or not lf.get("gives"):
            continue
        words, at = lf["words"], lf["at"]
        g = W.letters(lf["gives"])
        if g == W.letters(words):
            continue
        src = None
        if words.startswith(it + " ") or words.endswith(" " + it):
            rest = words[len(it):].strip(" ,") if words.startswith(it) else words[:-len(it)].strip(" ,")
            ri = words.find(rest)
            src = {"words": rest, "at": at + ri} if rest and ri >= 0 else None
        elif not clue[ib:at].strip(" ,") and at >= ib or not clue[at + len(words):ia].strip(" ,") and at + len(words) <= ia:
            src = {"words": words, "at": at}
        if src is None:
            continue
        new = {"op": node["op"], "indicators": [dict(ind)], "parts": [src]}
        if g in (vals(new) or ()):
            found.append((lf, new))
    if len(found) != 1:
        return None
    lf, new = found[0]
    if lf.get("note"):
        new["parts"][0]["note"] = lf["note"]
    if lf.get("unchecked"):
        new["unchecked"], new["gives"] = True, lf["gives"]
    plain_leaf = copy.deepcopy(parts[0])
    for target, repl in ((node, plain_leaf), (lf, new)):
        target.clear()
        target.update(repl)
    return node


def r_wrong_role(node, parent, ctx):
    """wrongRole: a leaf that folds a deletion into its words (r_leaf_fold), else indicators on
    the wrong one of two nested ops (r_role_swap), a selection indicator hung on a one-letter word
    (r_sel_one_letter)."""
    return r_leaf_fold(node, parent, ctx) or r_extremes_outer(node, parent, ctx) \
        or r_role_swap(node, parent, ctx) or r_role_move(node, parent, ctx) or r_sel_one_letter(node, parent, ctx)


def r_extremes_outer(node, parent, ctx):
    """A first/last op over one source whose indicator names both ends ('extremely', 'extremities',
    'outer', 'edges'): the outer op, which picks the first and the last letter. Kept only when the
    whole tree then evaluates to the answer (the driver's evaluate gate), so a pick that was one
    end by design stays as it is."""
    if node.get("op") not in ("first", "last") or node.get("unchecked") or len(node.get("parts") or []) != 1 \
            or id(node) in ctx["under_unchecked"] or not leaf(node["parts"][0]) \
            or not any(V.EXTREMES_WORD.search(i.get("text") or "") for i in node.get("indicators") or []):
        return None
    new = copy.deepcopy(node)
    new["op"] = "outer"
    if not (vals(new) or ()) or not _eval_swapped(node, parent, new, ctx):
        return None
    return new


SEL_FIRST = ("beginning", "start", "first", "initial", "opening", "head", "front")
SEL_LAST = ("end", "last", "tail", "finish", "close")
_SEL_PHRASE = re.compile(r"\b(" + "|".join(SEL_FIRST + SEL_LAST) + r")(\s+(?:of|in|at))?\s+([A-Za-z]+)(?:'s)?(?=\W|$)", re.I)


_SELW = "|".join(SEL_FIRST + SEL_LAST)
_SEL_PAIR = [re.compile(r"\b(?P<s1>%s)\s+(?:and|&)\s+(?P<s2>%s)(?P<prep>\s+(?:of|in|at))\s+(?P<w>[A-Za-z]+)(?P<poss>'s)?(?=\W|$)" % (_SELW, _SELW), re.I),
             re.compile(r"\b(?P<w>[A-Za-z]+)(?P<poss>'s)\s+(?P<s1>%s)\s+(?:and|&)\s+(?P<s2>%s)(?=\W|$)" % (_SELW, _SELW), re.I)]


def _del_selection_pair(node, ctx):
    """Two letters taken off one clue word's two ends by one indicator: 'off with Tony's beginning
    and end' with T and Y is del<off with>(x, first<beginning>(Tony's), last<end>(Tony's)).
    The removed letters are two bare leaves, or one bare two-letter leaf; one selector must be a
    first-type word and the other a last-type, in the order the clue gives them."""
    inds = node.get("indicators") or []
    parts = node.get("parts") or []
    if len(inds) != 1 or len(parts) < 2 or node.get("unchecked"):
        return None
    rem = parts[1:]
    if any("op" in r or "words" in r for r in rem) or len(W.letters("".join(r.get("gives") or "" for r in rem))) != 2:
        return None
    ind = inds[0]
    t, base = ind.get("text") or "", ind.get("at")
    if base is None:
        return None
    for rx in _SEL_PAIR:
        m = rx.search(t)
        if not m:
            continue
        s1, s2 = m.group("s1").lower(), m.group("s2").lower()
        if (s1 in SEL_FIRST) == (s2 in SEL_FIRST):
            continue
        word = m.group("w")
        w = W.letters(word)
        if len(w) < 3 or sorted(W.letters("".join(r.get("gives") or "" for r in rem))) != sorted(w[0] + w[-1]):
            continue
        wat = base + m.start("w")
        span = word + (m.group("poss") or "")
        if ctx["clue"][wat:wat + len(span)] != span:
            continue
        pre, post = t[:m.start()].strip(), t[m.end():].strip()
        if bool(pre) == bool(post):
            continue
        s1at, s2at = base + m.start("s1"), base + m.start("s2")
        # a "of/in/at" belongs to the selector next to it
        s2text = m.group("s2") + (m.group("prep") if "prep" in rx.groupindex and m.group("prep") else "")
        picks = []
        for sel, text, at in ((s1, m.group("s1"), s1at), (s2, s2text, s2at)):
            op = "first" if sel in SEL_FIRST else "last"
            picks.append({"op": op, "indicators": [{"text": text, "at": at,
                          "note": f"the {'first' if op == 'first' else 'last'} letter of the word is the one picked"}],
                          "parts": [{"words": span, "at": wat, "gives": word.upper(),
                                     "note": "the clue word, taken as written"}]})
        if pre:
            d_text, d_at = pre, base + t.index(pre)
        else:
            d_text, d_at = post, base + t.index(post, m.end())
        new = copy.deepcopy(node)
        new["indicators"] = [{**ind, "text": d_text, "at": d_at,
                              "note": "takes the picked letters out of the other part"}]
        new["parts"] = [parts[0]] + picks
        old, now = vals(node), vals(new)
        return new if old and now and old <= now else None
    return None


def r_del_selection(node, parent, ctx):
    """A deletion whose one indicator also names the letters it removes: 'not beginning in
    Hull' with a bare H. Each indicator is its own op: del<not>(x, first<beginning in>(Hull)).
    Only where the removed part is one bare letter, the selection phrase is
    'SELECTOR [of|in|at] WORD' naming a clue word that gives that letter, and exactly
    one side of the phrase (before or after) is left over for the deletion."""
    inds = node.get("indicators") or []
    parts = node.get("parts") or []
    if node.get("op") == "deletion" and len(parts) in (2, 3) and _del_selection_pair(node, ctx):
        return _del_selection_pair(node, ctx)
    if node.get("op") != "deletion" or len(inds) != 1 or len(parts) != 2 or node.get("unchecked"):
        return None
    rem = parts[1]
    if "op" in rem or "words" in rem or len(W.letters(rem.get("gives"))) != 1:
        return None
    ind = inds[0]
    t, base = ind.get("text") or "", ind.get("at")
    m = _SEL_PHRASE.search(t)
    if not m or not m.group(2) or base is None:  # a source word needs its "of/in/at"
        return None
    sel, word = m.group(1).lower(), m.group(3)
    pre, post = t[:m.start()].strip(), t[m.end():].strip()
    if bool(pre) == bool(post):
        return None
    letter = W.letters(rem["gives"])
    w = W.letters(word)
    if len(w) < 3 or letter != (w[0] if sel in SEL_FIRST else w[-1]):
        return None
    op = "first" if sel in SEL_FIRST else "last"
    wat = base + m.start(3)
    if ctx["clue"][wat:wat + len(word)] != word:
        return None
    sel_text = t[m.start():m.start(3)].strip()
    if pre:
        d_text, d_at = pre, base + t.index(pre)
    else:
        d_text, d_at = post, base + t.index(post, m.end())
    src = {"words": word, "at": wat}
    pick = {"op": op, "indicators": [{"text": sel_text, "at": base + m.start(),
            "note": f"the {'first' if op == 'first' else 'last'} letter of the word is the one picked"}],
            "parts": [src]}
    new = copy.deepcopy(node)
    new["indicators"] = [{**ind, "text": d_text, "at": d_at,
                          "note": "takes the picked letter out of the other part"}]
    new["parts"] = [parts[0], pick]
    old, now = vals(node), vals(new)  # the node keeps the letters it gave
    return new if old and now and old <= now else None


def _diff_gone(v, want, ind=None):
    """The one run of letters whose removal from v leaves want (None unless exactly one such string);
    an end/head/middle word in the indicator narrows where the run may sit."""
    m = len(v) - len(want)
    if m < 1:
        return None
    tail, head = bool(ind and TAIL.search(ind)), bool(ind and HEAD.search(ind))
    mid = bool(ind and MID.search(ind))
    if tail + head + mid > 1:
        return None
    runs = set()
    for j in range(len(v) - m + 1):
        if v[:j] + v[j + m:] != want:
            continue
        if (tail and j + m != len(v)) or (head and j != 0) or (mid and (j == 0 or j + m == len(v))):
            continue
        runs.add(v[j:j + m])
    if not runs and not (tail or head or mid) and m == 2 and v[1:-1] == want:
        return v[0] + v[-1]     # unlimited / without clothing: both ends go
    return runs.pop() if len(runs) == 1 else None


def _flat_leaves(parts):
    """Parts with plain charades opened out."""
    out = []
    for p in parts:
        if p.get("op") == "charade" and not p.get("indicators") and "gives" not in p:
            out += _flat_leaves(p.get("parts") or [])
        else:
            out.append(p)
    return out


def r_shared_indicator(node, parent, ctx):
    """sharedIndicator, deletion: the indicator's own words are filed again as a leaf giving the
    result (del<not opened>((PROOF + [not opened]ROOF), PROOF)). That leaf goes; the deletion is
    the source minus the one run whose removal leaves the result (an end/head/middle indicator
    word says where the run sits)."""
    if node.get("op") != "deletion" or len(node.get("indicators") or []) != 1:
        return None
    ind = node["indicators"][0]
    t = W.letters(ind.get("text"))
    if not t:
        return None
    flat = _flat_leaves(node.get("parts") or [])
    dup = [p for p in flat if leaf(p) and p.get("words") and W.letters(p["words"]) == t]
    if len(dup) != 1 or not W.letters(dup[0].get("gives")):
        return None
    k = flat.index(dup[0])
    want = W.letters(dup[0]["gives"])
    gone_leaves = [p for p in flat if leaf(p) and not p.get("words")]    # the filed removal, restated below
    pool = [p for p in flat if p is not dup[0] and p not in gone_leaves]
    nb = [p for p in (flat[k - 1:k] if k else []) + flat[k + 1:k + 2] if p in pool]
    if not nb:
        return None
    src = nb[0]       # the part next to the restated result
    sv = vals(src)
    if not sv or len(sv) != 1:
        return None
    gone = _diff_gone(next(iter(sv)), want, ind.get("text"))
    if gone is None:
        return None
    cut = checked(node, parts=[copy.deepcopy(src), {"gives": gone}])
    if not gives_ok(cut, want):
        return None
    around = [copy.deepcopy(p) if p is not src else cut for p in pool]
    if len(pool) == 1:
        return cut
    new = charade(around)
    return new if node.get("gives") is None or gives_ok(new, W.letters(node["gives"])) else None


REPAIRS = {"ins_split": r_ins_split, "del_removed": r_del_removed, "del_unwrap": r_del_unwrap,
           "arity_wrap": r_arity_wrap, "leaf_trim": r_leaf_trim, "ind_trim": r_ind_trim,
           "leaf_check": r_leaf_check, "link_leaf": r_link_leaf, "sel_literal": r_sel_literal}
#: Repairs for validator rules (the queue's anaSynonym / anagramOfContainer rows), run by --rule.
RULE_REPAIRS = {"anaSynonym": r_ana_synonym, "anagramOfContainer": r_ana_of_container,
                "containerInside": r_container_inside, "nestedContainer": r_nested_container,
                "wrongRole": r_wrong_role, "delSelection": r_del_selection,
                "sharedIndicator": r_shared_indicator}


def note_deletions(tree):
    """A deletion indicator a repair made new (the leaf fold's) has no note, and every annotation
    needs one: say what the word does (so does a selection's, made new by sel_edge/leaf_select)."""
    for n, _ in walk(tree):
        say = "takes the cut letters out of the word" if n.get("op") == "deletion" \
            else f"the {n['op']} letter of the word it picks from" if n.get("op") in ("first", "last", "middle") else None
        for i in (n.get("indicators") or []) if say else []:
            i.setdefault("note", say)
    return tree


def r_sel_edge(node, parent, ctx):
    """A first/last/middle op over one leaf whose words are the selector plus the source ('end of
    bayou' under last, 'Conservative leader' under first) and whose letters are that selection:
    the selector is the op's indicator (it is, already, or the op had none: a role move took its
    word off) and the leaf keeps the source alone. Checked or not, the letters stay."""
    parts = node.get("parts") or []
    if node.get("op") not in ("first", "last", "middle") or len(parts) != 1 or not leaf(parts[0]):
        return None
    lf = parts[0]
    if not lf.get("words") or lf.get("at") is None or len(node.get("indicators") or []) > 1:
        return None
    g = lf.get("gives") or node.get("gives")
    if g and W.letters(g) == W.letters(lf["words"]):
        g = node.get("gives")       # filed with its own words, not the pick
    if g:
        cands = [g]
    else:   # a checked leaf names no letters: the op's own pick from each word
        e = -1 if node["op"] == "last" else 0
        cands = sorted({W.letters(w)[e] for w in lf["words"].split() if W.letters(w)})
    founds = [(c, V.selector_in_block({"clueFragment": lf["words"], "gives": c})) for c in cands]
    founds = [(c, f) for c, f in founds if f]
    if len(founds) != 1:
        return None
    g, found = founds[0]
    sel, rest = found
    words = lf["words"]
    si, ri = words.find(sel), words.find(rest)
    if si < 0 or ri < 0:
        return None
    have = [i.get("text") for i in node.get("indicators") or []]
    if have and W.letters(have[0]) != W.letters(sel):
        return None
    new = copy.deepcopy(node)
    src = {**{k: v for k, v in lf.items() if k not in ("words", "at")}, "words": rest, "at": lf["at"] + ri}
    if not lf.get("unchecked"):
        src.pop("gives", None)
    new["parts"] = [src]
    if not have:
        new["indicators"] = [{"text": sel, "at": lf["at"] + si}]
    if not node.get("unchecked") and g not in (vals(new) or ()):
        return None
    return new


def r_leaf_select(node, parent, ctx):
    """A leaf that is filed with letters yet is a selector plus its source ('toilet's entrance'
    gives T): the selection op over the source (r_leaf_check's selector case, for a leaf not
    marked unchecked)."""
    if not leaf(node) or node.get("unchecked") or not node.get("gives") or not node.get("words") \
            or node.get("at") is None or (parent or {}).get("op") in W.SELECT:
        return None
    g = W.letters(node["gives"])
    words = node["words"]
    for pattern in [*V.SELECTOR_LEADS, V.SELECTOR_TAIL]:
        m = pattern.match(words)
        if not m or not V.selector_in_block({"clueFragment": words, "gives": g}):
            continue
        op = next(k for k in V.SELECT_NOUNS if m.group(k))
        sel, rest = m.group("sel"), m.group("rest").strip(" ,")
        si, ri = words.find(sel), words.find(rest)
        src = {"words": rest, "at": node["at"] + ri}
        if si < 0 or ri < 0 or g not in (vals({"op": op, "parts": [src]}) or ()):
            continue
        if node.get("note"):
            src["note"] = node["note"]
        return {"op": op, "indicators": [{"text": sel.strip(" ,"), "at": node["at"] + si}], "parts": [src]}
    return None


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
    count = shape_queue._validator_rules().get(rule) or (lambda wp, full, clue: False)
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
    ap.add_argument("--container-inside", action="store_true",
                    help="repair only the queued containerInside rows (--limit N samples; --apply writes puzzles)")
    a = ap.parse_args()
    if a.container_inside:
        run_rule("containerInside", a.apply, a.examples, a.seed, a.limit, a.jobs)
        return
    if a.rule:
        run_rule(a.rule, a.apply, a.examples, a.seed, a.limit, a.jobs, a.ids)
        return
    run(a.apply, a.examples, a.seed, a.limit, a.jobs, a.ledger, a.only)


if __name__ == "__main__":
    main()
