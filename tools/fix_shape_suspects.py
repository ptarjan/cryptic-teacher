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


def r_container_inside(node, parent, ctx):
    """ins(charade(a, b, c), x) whose x can only go inside ONE piece (container_inside_component):
    the container moves into that piece, charade(a, ins(b, x), c). Its indicators and note go
    with it (the container is what they signal); the charade's filed letters stay on the
    charade. _pick keeps it only when exactly one piece gives the simplest tree that still
    evaluates to the answer."""
    answer = ctx.get("answer")
    if not answer or not V._container_inside(node, W.letters(answer), node is ctx["tree"]):
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
    return _pick(node, parent, ctx, cands)


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
            or node.get("at") is None or id(node) in ctx["under_unchecked"]:
        return None
    toks = node["words"].split()
    if len(toks) < 3 or len(node["gives"]) > 4 or not V._deletion_word_in(node["words"]):
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
        return None
    kind, k, _ = next(iter(cuts))
    wleaf = {"words": pos[k][0], "at": pos[k][1]}
    if kind == "lit":
        return wleaf
    rest = [p for q, p in enumerate(pos) if q != k]
    gones = {gone for kd, kk, gone in cuts}
    for q, (t, i) in enumerate(pos):
        if q != k and plain(t) in gones and q not in delw:
            ind = [p for r, p in enumerate(pos) if r not in (k, q)]
            ind_txt = " ".join(t2 for t2, _ in ind)
            if not ind or not clue[ind[0][1]:ind[-1][1] + len(ind[-1][0])] .replace("  ", " ") == ind_txt:
                return None
            new = {"op": "deletion", "indicators": [{"text": ind_txt, "at": ind[0][1]}],
                   "parts": [wleaf, {"words": t, "at": i}]}
            return new if gives_ok(new, g) or g in (vals(new) or ()) else None
    ind_txt = " ".join(t for t, _ in rest)
    ind = {"text": ind_txt, "at": rest[0][1]}
    if clue[rest[0][1]:rest[-1][1] + len(rest[-1][0])] != ind_txt:
        return None
    probe = {"op": "deletion", "unchecked": True, "gives": g, "indicators": [ind], "parts": [wleaf]}
    return r_del_removed(probe, parent, ctx)


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
    return None


def r_wrong_role(node, parent, ctx):
    """wrongRole: a leaf that folds a deletion into its words (r_leaf_fold), else indicators on
    the wrong one of two nested ops (r_role_swap)."""
    return r_leaf_fold(node, parent, ctx) or r_role_swap(node, parent, ctx)


REPAIRS = {"ins_split": r_ins_split, "del_removed": r_del_removed, "del_unwrap": r_del_unwrap,
           "arity_wrap": r_arity_wrap, "leaf_trim": r_leaf_trim, "ind_trim": r_ind_trim,
           "leaf_check": r_leaf_check, "link_leaf": r_link_leaf, "sel_literal": r_sel_literal}
#: Repairs for validator rules (the queue's anaSynonym / anagramOfContainer rows), run by --rule.
RULE_REPAIRS = {"anaSynonym": r_ana_synonym, "anagramOfContainer": r_ana_of_container,
                "containerInside": r_container_inside, "nestedContainer": r_nested_container,
                "wrongRole": r_wrong_role}


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
    count = shape_queue._validator_rules()[rule]
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
        if not count(wp, full, clue):
            stat["already_clear"] += 1
            continue
        try:
            new_tree, used = repair_tree(wp, clue, answer, {rule: RULE_REPAIRS[rule]})
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
        new_ann = {**ann, "wordplay": new_tree}
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


def run_rule(rule, apply, n_examples, seed, limit, jobs):
    """Repair the queued rows of a validator rule (shape_reannotate.json rows naming `rule`)."""
    global _JOB
    import shape_queue
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
    ap.add_argument("--container-inside", action="store_true",
                    help="repair only the queued containerInside rows (--limit N samples; --apply writes puzzles)")
    a = ap.parse_args()
    if a.container_inside:
        return run_container(a.apply, a.limit, a.seed, a.examples, a.jobs)
    if a.rule:
        run_rule(a.rule, a.apply, a.examples, a.seed, a.limit, a.jobs)
        return
    run(a.apply, a.examples, a.seed, a.limit, a.jobs, a.ledger, a.only)


if __name__ == "__main__":
    main()
