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
"""
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
import wordplay as W

DATA = Path(__file__).resolve().parent / "data"
SUSPECTS = DATA / "shape_suspects.json"
OUT = DATA / "shape_reannotate.json"
UNARY = ("reversal", "cycling", "hidden") + W.SELECT

TAIL = re.compile(r"end|tail|last|final|finish|clos|short|almost|most|nearly|brief|large|main|quite|incomplete|"
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
    # a charade directly under an anagram is flattened into the anagram's own parts (anagramCharade)
    return int(_plain_charade(new) and (_plain_charade(parent) or (parent or {}).get("op") == "anagram"))


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


def _ana_split_candidates(node):
    """Rewrites of an anagram whose fodder holds synonyms: the synonyms charaded on, and ANY
    subset of the other leaves anagrammed (the rest charaded on as their own letters, so
    "In stalked on wrong cue" scrambles only cue), every order of the pieces; [] if none."""
    if node.get("op") != "anagram":
        return []
    flat = _flat_fodder(node)
    syn = [p for p in flat if _is_stand_in(p)]
    rest = [p for p in flat if not _is_stand_in(p)]
    if not syn or not rest or len(syn) + len(rest) > 6:
        return []
    if any(not leaf(p) or p.get("select") for p in rest):
        return []       # a nested op in the fodder: not mechanical
    # a leaf giving other letters (an abbreviation) was never the anagram's: it stays literal
    fixed = [p for p in rest if p.get("gives") and W.letters(p["gives"]) != W.letters(p.get("words"))]
    free = [p for p in rest if p not in fixed]
    if not free:
        return []
    import itertools
    out = []
    for mask in range(1, 2 ** len(free)):
        scr = [p for i, p in enumerate(free) if mask >> i & 1]
        lit = [p for i, p in enumerate(free) if not mask >> i & 1] + fixed
        core = checked(node, parts=copy.deepcopy(scr))
        for perm in itertools.permutations([*copy.deepcopy(syn), *copy.deepcopy(lit), core]):
            out.append(charade(list(perm)))
    return out


def r_ana_synonym_charade(node, parent, ctx):
    """anaSynonym: an anagram scrambling a synonym beside the clue's own words becomes
    charade(synonym, anagram(own words)) in whichever order and split evaluates to the
    answer. Unlike r_ana_synonym it does not need the new tree to be simpler (the old one is
    the flagged shape): it needs the validator's count to fall, and exactly one simplest tree."""
    if node.get("op") != "anagram" or not ctx.get("answer"):
        return None
    cands = _ana_split_candidates(node)
    if not cands:
        return None
    old = V.anagram_synonyms(ctx["tree"])
    good = []
    for c in cands:
        if not _eval_swapped(node, parent, c, ctx):
            continue
        whole = _whole(node, parent, c, ctx)
        if V.anagram_synonyms(whole) < old:
            good.append((simplicity(whole), c))
    if not good:
        return None
    best = min(k for k, _ in good)
    top = {json.dumps(c, sort_keys=True): c for k, c in good if k == best}
    return next(iter(top.values())) if len(top) == 1 else None


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
        ana = {**copy.deepcopy(base), "parts": copy.deepcopy(arm["parts"] if _plain_charade(arm) else [arm])}
        cont = c
        own = [x for x in c.get("indicators") or [] if _owner_any(x) == V._OP_LEXICON.get("anagram")]
        if not own and len(c.get("indicators") or []) == 2:
            # neither word is the corpus's anagram word: with one the corpus files under container,
            # the other (a word nothing files anywhere) is the anagram's
            held = [x for x in c["indicators"] if _owner_any(x) == V._OP_LEXICON.get("container")]
            free = [x for x in c["indicators"] if not _owner_any(x)]
            own = free if len(held) == 1 and len(free) == 1 else []
        if not ana.get("indicators") and len(own) == 1 and len(c["indicators"]) > 1:
            # the anagram carries no word and the container two: the one the corpus files under
            # anagram is the anagram's (one op per indicator)
            ana["indicators"] = [copy.deepcopy(own[0])]
            cont = {**c, "indicators": [x for x in c["indicators"] if x is not own[0]]}
        for inner in [ana, *_ana_candidates(ana)]:
            parts = copy.deepcopy(c["parts"])
            parts[i] = inner
            cands.append(checked(cont, parts=parts))
            # the file lists the arms in clue order: the container takes the holder first
            cands.append(checked(cont, parts=parts[::-1]))
    flat = _literal_pool(node, c)
    if flat is not None:
        cands.append(flat)
    return _pick(node, parent, ctx, cands)


def _literal_pool(node, c):
    """ana(ins(a, b)) whose arms are the clue's own words (no letters of their own, or just the
    words' letters): a plain anagram of the words together. The container's words are links
    unless the anagram has no word of its own, then the one container word the corpus files
    under anagram is its indicator."""
    pieces = []
    for p in c["parts"]:
        for q in (p["parts"] if _plain_charade(p) else [p]):
            if not leaf(q) or not q.get("words") or q.get("select") or q.get("soundsLike") \
                    or (q.get("gives") and W.letters(q["gives"]) != W.letters(q["words"])):
                return None
            pieces.append({k: v for k, v in q.items() if k != "gives"})
    inds = copy.deepcopy(node.get("indicators") or [])
    if not inds:
        own = [i for i in c.get("indicators") or [] if _owner_any(i) == V._OP_LEXICON.get("anagram")]
        if len(own) != 1:
            return None
        inds = [copy.deepcopy(own[0])]
    return {**{k: v for k, v in node.items() if k not in ("unchecked", "gives", "parts", "indicators")},
            "indicators": inds, "parts": pieces}


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
        # the whole tree, not the node alone: the pair may sit under a reversal or inside a charade
        if not _eval_swapped(node, parent, c, ctx):
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


def _owns(ind, kind, host):
    """Whether the corpus files an indicator's words mostly (V.ROLE_LOOSE_OWNED) under `kind`,
    and hardly ever (V.ROLE_LOOSE_OWN_MAX) under the type of the op `host` that carries it."""
    counts = V._role_counts(V.indicator_role_key(ind.get("text")))
    total = sum(counts.values())
    return total >= V.ROLE_MIN_USES and counts.get(kind, 0) >= V.ROLE_LOOSE_OWNED * total \
        and counts.get(host, 0) <= V.ROLE_LOOSE_OWN_MAX * total


def _unknown_word(ind):
    return sum(V._role_counts(V.indicator_role_key(ind.get("text"))).values()) < V.ROLE_MIN_USES


def r_ind_trade(node, parent, ctx):
    """Two checked ops anywhere in the tree (nested or siblings) that each carry the word the
    corpus files under the other's type -- rev<first to>(..) beside first<back>(..), ins<mad>(
    ana<about>(..)) -- trade those words; also an op whose word the corpus has never seen
    trading with a word the corpus files under its own type (ins<Awfully>(ana<to have pocketed>
    (..))). Run once, from the root; kept only when the whole tree then counts fewer
    wrong-role indicators. Words move whole; the letters are untouched."""
    if parent is not None:
        return None
    ops = [n for n, _ in walk(node) if V._OP_LEXICON.get(n.get("op")) and not n.get("unchecked")
           and id(n) not in ctx["under_unchecked"] and n.get("indicators")]
    for x in ops:
        kx = V._OP_LEXICON[x["op"]]
        for y in ops:
            ky = V._OP_LEXICON[y["op"]]
            if x is y or kx == ky or V._swap_alike(kx, ky) or V._swap_alike(ky, kx):
                continue
            for a in x["indicators"]:
                for b in y["indicators"]:
                    if not (_owns(b, kx, ky) and (_owns(a, ky, kx) or _unknown_word(a))):
                        continue

                    def swap(a=a, b=b):
                        x["indicators"][x["indicators"].index(a)], y["indicators"][y["indicators"].index(b)] = b, a
                    if _gated(ctx, [x, y], swap):
                        return node
    return None


BOTH_ENDS = re.compile(r"endless|unlimited|edgeless|boundless|peeled|shelled|skinned|topless and tailless", re.I)


def _cut_options(full, g, ind_text):
    """The letters `ind_text` takes off `full` to leave `g`: [gone] (one run), or [first, last]
    for a both-ends word; empty when the word's end does not fit or no single reading does."""
    m = len(full) - len(g)
    if m < 1:
        return []
    if BOTH_ENDS.search(ind_text):
        return [[full[0], full[-1]]] if m == 2 and full[1:-1] == g else []
    tail, head, mid = bool(TAIL.search(ind_text)), bool(HEAD.search(ind_text)), bool(MID.search(ind_text))
    if tail + head + mid != 1 or m > 3:
        return []
    if tail and full.startswith(g):
        return [[full[len(g):]]]
    if head and full.endswith(g):
        return [[full[:m]]]
    if mid and len(full) > m + 1:
        k = (len(full) - m) // 2
        cuts = {j for j in (k, len(full) - m - k) if full[:j] + full[j + m:] == g}
        return [[full[j:j + m]] for j in cuts] if len(cuts) == 1 else []
    return []


def r_container_cut(node, parent, ctx):
    """A container carrying a cut word (nearly, briefly, endlessly) that the corpus files under
    deletion, beside a leaf whose letters are one clue word (or a word its note spells in capitals)
    with the run that word names cut off: the cut word goes onto a deletion over that leaf, the
    removed run a leaf of its own (ins<endlessly>(LPS, China=HIN) is ins(LPS, del<endlessly>(
    China, C, A))). Kept only when exactly one leaf and one cut fit and the tree still gives
    the answer; a container left with no word of its own is the driver's gate to refuse."""
    if node.get("op") != "container" or node.get("unchecked") or id(node) in ctx["under_unchecked"]:
        return None
    parts = node.get("parts") or []
    found = []
    for d in node.get("indicators") or []:
        if not _owns(d, "deletion", "container"):
            continue
        for k, p in enumerate(parts):
            if not leaf(p) or p.get("unchecked") or not p.get("words") or not p.get("gives"):
                continue
            g = W.letters(p["gives"])
            fulls = [(W.letters(p["words"]), False)] if len(p["words"].split()) == 1 else []
            fulls += [(W.letters(x), True) for x in re.findall(r"\b[A-Z]{3,}\b", p.get("note") or "")]
            for full, from_note in fulls:
                for gone in _cut_options(full, g, d.get("text") or ""):
                    found.append((d, k, full, from_note, gone))
    if len({(id(f[0]), f[1], f[2], tuple(f[4])) for f in found}) != 1:
        return None
    d, k, full, from_note, gone = found[0]
    new = copy.deepcopy(node)
    src = {x: v for x, v in new["parts"][k].items() if x != "gives"}
    if from_note:
        src["gives"] = full
    new["parts"][k] = {"op": "deletion", "indicators": [copy.deepcopy(d)], "parts": [src] + [{"gives": x} for x in gone]}
    new["indicators"] = [i for i in new["indicators"] if i is not d and i != d]
    if not new["indicators"]:
        new.pop("indicators")
    return new if _eval_swapped(node, parent, new, ctx) else None


def r_wrong_role(node, parent, ctx):
    """wrongRole: a leaf that folds a deletion into its words (r_leaf_fold), else indicators on
    the wrong one of two nested ops (r_role_swap), a selection indicator hung on a one-letter word
    (r_sel_one_letter)."""
    return r_leaf_fold(node, parent, ctx) or r_extremes_outer(node, parent, ctx) \
        or r_role_swap(node, parent, ctx) or r_ind_trade(node, parent, ctx) \
        or r_container_cut(node, parent, ctx) or r_role_move(node, parent, ctx) or r_sel_one_letter(node, parent, ctx)


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


def _top_role(ind, kind):
    """Whether the corpus files the indicator's words under `kind` more than any other op type."""
    counts = V._role_counts(V.indicator_role_key(ind.get("text")))
    return sum(counts.values()) >= V.ROLE_MIN_USES and max(counts, key=counts.get) == kind


def _anagram_only(ind):
    """Whether the corpus files the indicator's words as an anagram word and (almost) never as a
    container one: wandering yes (153 to 1), split no (15 to 13)."""
    counts = V._role_counts(V.indicator_role_key(ind.get("text")))
    return _top_role(ind, "anagram") and counts.get("anagram", 0) >= 8 * (counts.get("container", 0) + counts.get("insertion", 0))


def _words_between(clue, a, b):
    """True when only spaces and punctuation lie in clue[a:b]."""
    return not re.search(r"[A-Za-z0-9]", clue[a:b])


def r_pool_outer(node, parent, ctx):
    """poolGap, a container filed over the anagram alone: rake embraced by whore = ins<embraced by>(ana<dishevelled>(rake,
    SHAG)) for SHAKERAG. One fodder piece is really the other arm of the container, so it leaves the pool
    and goes beside the anagram. Used when exactly one piece and order rebuilds the answer."""
    if node.get("op") not in ("container", "insertion") or len(node.get("parts") or []) != 1:
        return None
    a = node["parts"][0]
    if a.get("op") != "anagram" or "gives" in a or a.get("unchecked") or len(a.get("parts") or []) < 2:
        return None
    flat = _flat_fodder(a)
    if len(flat) < 2 or any(not isinstance(p.get("at"), int) for p in flat):
        return None
    good = {}
    for k, piece in enumerate(flat):
        rest = [copy.deepcopy(p) for j, p in enumerate(flat) if j != k]
        inner = checked(a, parts=rest)
        for order in ((inner, copy.deepcopy(piece)), (copy.deepcopy(piece), inner)):
            new = checked(node, parts=list(order))
            if _eval_swapped(node, parent, new, ctx):
                good[json.dumps(new, sort_keys=True)] = new
    return next(iter(good.values())) if len(good) == 1 else None


def r_pool_gap(node, parent, ctx):
    """poolGap: an insertion/container over an anagram and plain leaf pieces, whose indicator words sit
    between the anagram's fodder (Camels wandering about every second: ins<wandering>(ana<about>(..), S)).
    When the anagram of all the pieces gives the same letters and the container's indicator is
    right beside the anagram's, the two indicators are one anagram indicator over every piece."""
    if node.get("op") not in ("container", "insertion"):
        return None
    if len(node.get("parts") or []) == 1:
        return r_pool_outer(node, parent, ctx)
    if node.get("unchecked"):
        return None
    clue = ctx["clue"]
    ana = [p for p in node.get("parts") or [] if p.get("op") == "anagram"]
    others = [p for p in node.get("parts") or [] if p.get("op") != "anagram"]
    if len(ana) != 1 or not others or not V.pool_gaps(node, clue) or ana[0].get("unchecked"):
        return None
    a = ana[0]
    if any(not leaf(p) or not p.get("words") for p in others) or "gives" in a:
        return None
    inds = [*(a.get("indicators") or []), *(node.get("indicators") or [])]
    if len(inds) < 2 or any(not isinstance(i.get("at"), int) or not i.get("text") for i in inds):
        return None
    if any(not _anagram_only(i) for i in node.get("indicators") or []):
        return None     # "between", "in", "around", "split": container words too (split frightfully is a real insertion)
    inds.sort(key=lambda i: i["at"])
    for x, y in zip(inds, inds[1:]):
        if not _words_between(clue, x["at"] + len(x["text"]), y["at"]):
            return None
    pieces = sorted([*_flat_fodder(a), *others], key=lambda p: p.get("at") if isinstance(p.get("at"), int) else 10**6)
    new = checked(a, parts=copy.deepcopy(pieces), indicators=copy.deepcopy(inds))
    if node.get("gives") is not None:
        new["gives"] = node["gives"]
        if not gives_ok(new, W.letters(node["gives"])):
            return None
    if V.pool_gaps(new, clue):
        return None
    return new


def _has_letters(p):
    """A piece that is checked all the way down and gives letters of its own."""
    if any(n.get("unchecked") for n, _ in walk(p)):
        return False
    v = vals(p)
    return bool(v) and "" not in v


def _eject_candidates(ana):
    """(piece, inner anagram) for each fodder piece taken out of the pool (the rest kept, in order)."""
    flat = _flat_fodder(ana)
    if len(flat) < 2 or any(not isinstance(p, dict) for p in flat):
        return
    for k, piece in enumerate(flat):
        if _has_letters(piece):
            yield copy.deepcopy(piece), checked(ana, parts=[copy.deepcopy(p) for j, p in enumerate(flat) if j != k])


def r_pool_eject(node, parent, ctx):
    """poolGap, a piece in the anagram's pool that is really another op's: it leaves the pool and
    goes beside the anagram (HE + ana(N, thing) -> HE + N + ana(thing)), or into the container
    arm next to it (ins(ana(gold, a), P) -> ins(ana(gold), a+P)). Kept only when exactly one piece,
    place and order gives the answer and the pool gap is gone."""
    clue, answer = ctx["clue"], ctx.get("answer")
    if not answer or not V.pool_gaps(ctx["tree"], clue):
        return None
    cands = []
    if node.get("op") == "anagram":
        if node.get("unchecked") or "gives" in node or not V.pool_gaps(node, clue) and not V.pool_gaps(ctx["tree"], clue):
            return None
        for piece, inner in _eject_candidates(node):
            cands += [charade([inner, piece]), charade([piece, inner])]
    elif node.get("op") in ("container", "insertion") and not node.get("unchecked") and len(node.get("parts") or []) == 2:
        for j, ana in enumerate(node["parts"]):
            if ana.get("op") != "anagram" or ana.get("unchecked") or "gives" in ana:
                continue
            sib = node["parts"][1 - j]
            for piece, inner in _eject_candidates(ana):
                for joined in (charade([piece, copy.deepcopy(sib)]), charade([copy.deepcopy(sib), piece])):
                    ps = [copy.deepcopy(inner), joined] if j == 0 else [joined, copy.deepcopy(inner)]
                    cands.append(checked(node, parts=ps))
    before = V.pool_gaps(ctx["tree"], clue)
    good = {}
    for c in cands:
        if _eval_swapped(node, parent, c, ctx) and V.pool_gaps(_whole(node, parent, c, ctx), clue) < before:
            good[json.dumps(c, sort_keys=True)] = c
    return next(iter(good.values())) if len(good) == 1 else None


def _at_named_end(node, new):
    """Whether the deletion moved into `new`'s charade takes its letters from the end (start) of its
    piece that the indicator names; False when the indicator names no single end."""
    text = " ".join(str(i.get("text") or "") for i in node.get("indicators") or [])
    end, head = bool(V._DEL_END.search(text)), bool(V._DEL_HEAD.search(text))
    if end == head:
        return False
    for c in new.get("parts") or []:
        if c.get("op") == "deletion":
            try:
                whole, cut = vals({"op": "charade", "parts": [c["parts"][0]]}), vals({"op": "charade", "parts": c["parts"][1:]})
            except (W.WordplayError, IndexError, KeyError, TypeError, ValueError):
                return False
            return any((f.endswith(r) if end else f.startswith(r)) for f in whole or () for r in cut or ())
    return False


def r_deletion_inside(node, parent, ctx):
    """deletionInside: del(charade(a, b, c), x) whose x comes out of ONE piece (CON+SIDE+RABBLE less B,
    "half-hearted"): the deletion moves into that piece, charade(a, del(b, x), c), indicators with it
    (the deletion is what they signal); the charade's filed letters stay on the charade and the
    deletion's filed letters ride the charade. Kept only when exactly one piece gives a tree that
    still evaluates to the answer and the validator's rule no longer fires on it."""
    parts = node.get("parts") or []
    if node.get("op") != "deletion" or len(parts) < 2 or node.get("unchecked") or not ctx.get("answer"):
        return None
    if any(not isinstance(p, dict) for p in parts):
        return None
    holder = parts[0]
    if holder.get("op") != "charade" or holder.get("unchecked"):
        return None
    comps = holder.get("parts") or []
    if len(comps) < 2:
        return None
    cands = []
    for k, c in enumerate(comps):
        inner = {x: y for x, y in node.items() if x not in ("parts", "gives")}
        inner["parts"] = [copy.deepcopy(c), *copy.deepcopy(parts[1:])]
        v = vals(inner)
        if not v or "" in v:
            continue    # a piece that goes whole is one the charade added only to remove it: the model's
        pieces = copy.deepcopy(comps)
        pieces[k] = inner
        new = {x: y for x, y in holder.items() if x not in ("parts", "gives")}
        new["op"], new["parts"] = "charade", pieces
        if node.get("gives") is not None:
            new["gives"] = node["gives"]
        cands.append(new)
    good = {json.dumps(c, sort_keys=True): c for c in cands if _eval_swapped(node, parent, c, ctx)}
    if len(good) > 1:
        # an indicator that names an end: only the piece whose own end (start) holds the letters
        good = {k: c for k, c in good.items() if _at_named_end(node, c)}
    if len(good) != 1:
        return None
    new = next(iter(good.values()))
    return new if not V.deletion_inside_component(new, ctx["clue"], ctx["answer"]) else None


def _mine_for_op(ind, op):
    """Whether the corpus files indicator `ind` under the type of op node `op` (first/last picks also by
    their own head or tail words)."""
    kind = V._OP_LEXICON.get(op.get("op"))
    text = ind.get("text") or ""
    if not kind or _role_owner(ind) != kind:
        return False
    if op["op"] == "first":
        return bool(HEAD.search(text)) and not TAIL.search(text)
    if op["op"] == "last":
        return bool(TAIL.search(text)) and not HEAD.search(text)
    return True


#: With False, r_unindicated_move reads fits as it first did (corpus-owned words only, one holder word per op).
UNINDICATED_WIDE = True


def _lexicon_owns(ind, op):
    """Whether the indicator lexicon (tools/data/lexicons/indicators.json) lists the indicator's words for
    the type of op node `op` (at least 3 uses, three times as many as under any other type)."""
    kind = V._OP_LEXICON.get(op.get("op"))
    lex = V._indicator_lexicon()
    key = V.indicator_role_key(ind.get("text"))
    mine = (lex.get(kind) or {}).get(key, 0)
    if not kind or mine < 3 or any(mine < 3 * (t.get(key) or 0) for k, t in lex.items() if k != kind):
        return False
    text = ind.get("text") or ""
    if op["op"] == "first":
        return bool(HEAD.search(text)) and not TAIL.search(text)
    if op["op"] == "last":
        return bool(TAIL.search(text)) and not HEAD.search(text)
    return True


def _unindicated_fits(node, op, wide):
    """The (holder, indicator) pairs whose indicator could belong to bare op `op`: filed on a charade, on
    an op of another type, or beside a second indicator of one op."""
    fits, held = [], False
    for h, _ in walk(node):
        if h is op or h.get("unchecked"):
            continue
        hk = V._OP_LEXICON.get(h.get("op"))
        for i in h.get("indicators") or []:
            owned = _role_owner(i) == hk or (wide and hk and _lexicon_owns(i, h))
            if not (h.get("op") == "charade" or (hk and not owned) or len(h["indicators"]) > 1):
                continue
            held = True
            if _mine_for_op(i, op) or (wide and _lexicon_owns(i, op)):
                fits.append((h, i))
    return fits, held


def _owner_any(ind):
    """The op type the corpus or the indicator lexicon files an indicator's words under, else None."""
    own = _role_owner(ind)
    if own:
        return own
    lex = V._indicator_lexicon()
    key = V.indicator_role_key(ind.get("text"))
    top = max(lex, key=lambda k: (lex[k].get(key) or 0) if k in V._OP_LEXICON.values() else -1, default=None)
    n = (lex.get(top) or {}).get(key, 0)
    rest = max([(t.get(key) or 0) for k, t in lex.items() if k != top] or [0])
    return top if n >= 3 and n >= 3 * rest else None


def _op_spans(op):
    return [(x["at"], x["at"] + len(x["words"])) for x, _ in walk(op) if leaf(x) and x.get("words")
            and isinstance(x.get("at"), int)]


def _unindicated_swap(node, ctx, base, role):
    """A charade's indicator owned by the type of op X, where X carries only a word nothing files under any
    type, and a bare op B stands right beside that word: the charade's word goes to X, X's word to B
    (charade<at the outset>(first<hosted>(g), ins(long, uncle's)) -> first<at the outset>, ins<hosted>).
    Only one X and one B; the validator must then count fewer bare ops."""
    clue = ctx["clue"]
    bare = [op for op, _ in walk(node)
            if not (op.get("unchecked") or id(op) in ctx["under_unchecked"] or op.get("indicators")
                    or op.get("op") not in V.NEEDS_INDICATOR or not V._OP_LEXICON.get(op.get("op")))]
    if not bare:
        return None
    for h, _ in walk(node):
        if h.get("op") != "charade":
            continue
        for i in list(h.get("indicators") or []):
            xs = [x for x, _ in walk(node) if x is not h and not x.get("unchecked") and x.get("indicators")
                  and V._OP_LEXICON.get(x.get("op")) and (_mine_for_op(i, x) or _lexicon_owns(i, x))
                  and all(not _owner_any(j) for j in x["indicators"]) and len(x["indicators"]) == 1]
            if len(xs) != 1:
                continue
            x = xs[0]
            j = x["indicators"][0]
            if not isinstance(j.get("at"), int):
                continue
            beside = [b for b in bare if b is not x and any(
                (not clue[e:j["at"]].strip(" ,;") and e <= j["at"]) or
                (not clue[j["at"] + len(j["text"]):s].strip(" ,;") and s >= j["at"] + len(j["text"]))
                for s, e in _op_spans(b))]
            if len(beside) != 1:
                continue
            b = beside[0]
            h["indicators"].remove(i)
            if not h["indicators"]:
                h.pop("indicators")
            x["indicators"], b["indicators"] = [i], [j]
            if V.unindicated_uncovered(node) < base and V.wrong_role_indicators(node) <= role:
                return node
            b.pop("indicators")
            x["indicators"] = [j]
            h.setdefault("indicators", []).append(i)
    return None


def r_unindicated_move(node, parent, ctx):
    """unindicatedBare: a checked op with no indicator while a word the corpus files under its type (or
    the indicator lexicon lists for it) sits on another node that does not need it (a charade, or an op of
    a different type): the word moves to the bare op (charade<guards>(DET, ins(PLUS, C)) is
    charade(DET, ins<guards>(PLUS, C)); ins<final bit of>(CIA, last(..)) gives last<final bit of>).
    One word per bare op. A bare op takes the word only when it is the one op that word fits, or when the
    other bare ops' words, matched one-to-one, leave it that word alone (two bare ops with two misfiled
    words); and only when the validator then counts fewer bare ops and no more wrong-role indicators.
    Run once, at the root; the driver's evaluate gate does the rest. ctx["declines"], when present,
    collects (reason) per bare op left bare: no_holder (no indicator filed on a node that could spare it),
    not_this_type (such words, none fits), ambiguous (several fit, or two ops want one word), validator."""
    if parent is not None:
        return None
    base, role = V.unindicated_uncovered(node), V.wrong_role_indicators(node)
    if not base:
        return None
    log = ctx.get("declines")
    wide = UNINDICATED_WIDE
    bare = [op for op, _ in walk(node)
            if not (op.get("unchecked") or id(op) in ctx["under_unchecked"] or op.get("indicators")
                    or op.get("op") not in V.NEEDS_INDICATOR or not V._OP_LEXICON.get(op.get("op")))]
    fits = {id(op): _unindicated_fits(node, op, wide) for op in bare}
    cand = {id(op): list(f[0]) for op, f in zip(bare, fits.values())}
    taken, pick = set(), {}
    while True:
        moved = False
        for op in bare:
            if id(op) in pick:
                continue
            c = [x for x in cand[id(op)] if id(x[1]) not in taken]
            if len(c) != 1:
                continue
            # two ops each left with this one word: neither is placed
            if any(o2 is not op and id(o2) not in pick and
                   [y for y in cand[id(o2)] if id(y[1]) not in taken] == c for o2 in bare):
                continue
            pick[id(op)] = c[0]
            taken.add(id(c[0][1]))
            moved = True
        if not moved or not wide:
            break
    done = False
    for op in bare:
        if id(op) not in pick:
            if log is not None:
                f, held = fits[id(op)]
                log.append("ambiguous" if f else ("not_this_type" if held else "no_holder"))
            continue
        h, i = pick[id(op)]
        if i not in (h.get("indicators") or []):
            continue
        h["indicators"].remove(i)
        op["indicators"] = [i]
        if not h["indicators"]:
            h.pop("indicators")
        if V.unindicated_uncovered(node) < base and V.wrong_role_indicators(node) <= role:
            base, role, done = V.unindicated_uncovered(node), V.wrong_role_indicators(node), True
            continue
        op.pop("indicators")
        h.setdefault("indicators", []).append(i)
        if log is not None:
            log.append("validator")
    if not done and wide:
        return _unindicated_swap(node, ctx, base, role)
    return node if done else None


def _claimed(tree, clue):
    """Boolean per clue character: whether some leaf's words or indicator's text covers it."""
    cov = [False] * len(clue)
    for n, _ in walk(tree):
        spans = [(n.get("at"), n.get("words"))] if leaf(n) else []
        spans += [(i.get("at"), i.get("text")) for i in n.get("indicators") or []]
        for at, t in spans:
            if t and isinstance(at, int):
                cov[at:at + len(t)] = [True] * len(clue[at:at + len(t)])
    return cov


def r_unindicated_spare(node, parent, ctx):
    """unindicatedBare: a checked op with no indicator while one clue word, unused by any leaf or
    indicator, stands right beside its words and is a word the corpus files under its type (a
    container's "hosting", a reversal's "back"): the word becomes the op's indicator. Only one such
    word for the op and no other bare op of the same type wanting it; the validator must then count
    fewer bare ops (a word in the definition is turned away by the definition rule). Run once, at the root."""
    if parent is not None:
        return None
    clue = ctx["clue"]
    base, role = V.unindicated_uncovered(node), V.wrong_role_indicators(node)
    if not base or any(not isinstance(x.get("at"), int) for x, _ in walk(node) if leaf(x) and x.get("words")):
        return None
    cov = _claimed(node, clue)
    words = [m for m in re.finditer(r"[A-Za-z']+", clue) if not any(cov[m.start():m.end()])]
    bare = [op for op, _ in walk(node) if not op.get("unchecked") and id(op) not in ctx["under_unchecked"]
            and not op.get("indicators") and op.get("op") in V.NEEDS_INDICATOR and V._OP_LEXICON.get(op.get("op"))]
    want = {}
    for op in bare:
        ends = []
        for x, _ in walk(op):
            if leaf(x) and x.get("words"):
                ends.append((x["at"], x["at"] + len(x["words"])))
            ends += [(i["at"], i["at"] + len(i["text"])) for i in x.get("indicators") or [] if isinstance(i.get("at"), int)]
        for m in words:
            counts = V._role_counts(V.indicator_role_key(m.group()))
            total, kind = sum(counts.values()), V._OP_LEXICON[op["op"]]
            if total < 20 or counts.get(kind, 0) < 0.8 * total:
                continue
            if not any(not clue[b:m.start()].strip(" ,;") for _, b in ends if b <= m.start()) \
                    and not any(not clue[m.end():a].strip(" ,;") for a, _ in ends if a >= m.end()):
                continue
            if op["op"] in ("first", "last") and not _mine_for_op({"text": m.group()}, op):
                continue
            want.setdefault(id(op), []).append(m)
    for op in bare:
        ms = want.get(id(op)) or []
        if len(ms) != 1 or sum(ms[0] in v for v in want.values()) != 1:
            continue
        m = ms[0]
        op["indicators"] = [{"text": m.group(), "at": m.start(), "note": "the clue word that signals this step"}]
        if V.unindicated_uncovered(node) < base and V.wrong_role_indicators(node) <= role:
            return node
        op.pop("indicators")
    return None

def _cut_of(full, got, kind):
    """The letters a `kind` ("tail", "head", "mid") cut takes off `full` to leave `got`, or None."""
    m = len(full) - len(got)
    if m != 1:    # one letter: "largely"/"not all" on a longer run is a different cut, the model's
        return None
    if kind == "tail" and full.startswith(got):
        return full[len(got):]
    if kind == "head" and full.endswith(got):
        return full[:m]
    if kind == "mid" and len(full) > m + 1:
        k = (len(full) - m) // 2
        cuts = {j for j in (k, len(full) - m - k) if full[:j] + full[j + m:] == got}
        if len(cuts) == 1:
            j = cuts.pop()
            return full[j:j + m]
    return None


def r_del_single(node, parent, ctx):
    """del_single: a one-part deletion over a composite (a charade, an anagram, a container) whose
    letters come out of ONE leaf the model filed already cut (del<finally going off>(BAS + MA + TI),
    TI = "Tim" less its end): the cut moves onto that leaf, which gives the clue's own word whole,
    del<ind>([Tim]TIM, M), and the deletion node goes. Only a leaf whose clue words are the
    literal word that the cut leaves its letters from; kept only when exactly one leaf gives a tree
    that still evaluates to the answer. A synonym cut short (Short talk > RABBI) takes its whole word
    from the usage table (talk > RABBIT, 3+ uses) or abbreviation table; a leaf left with one letter
    is not a cut word and stays for the model."""
    parts = node.get("parts") or []
    if node.get("op") != "deletion" or len(parts) != 1 or not node.get("unchecked") or not ctx.get("answer"):
        return None
    inds = node.get("indicators") or []
    if len(inds) != 1 or not isinstance(parts[0], dict) or leaf(parts[0]) or not V.del_single(node):
        return None
    text = inds[0].get("text") or ""
    kinds = [k for k, rx in (("tail", TAIL), ("head", HEAD), ("mid", MID)) if rx.search(text)]
    if len(kinds) != 1:
        return None
    good = {}
    for lf, _ in walk(parts[0]):
        if not leaf(lf) or not lf.get("words") or not lf.get("gives"):
            continue
        lit, got = W.letters(lf["words"]), W.letters(lf["gives"])
        if lf.get("unchecked") or W.letters(text) in lit.split() or len(got) < 2:   # one letter left: an abbreviation, not a cut word
            continue
        # the clue's own word, else a whole word the tables attest for those clue words (every > ALL)
        usage = V._attested()[1].get(re.sub(r"[^A-Z]", "", lf["words"].upper()), {})
        fulls = {lit} | {W.letters(a) for a in usage if usage[a] >= 3} | {W.letters(a) for a in _abbreviations(lf["words"])}
        for full in fulls:
            gone = _cut_of(full, got, kinds[0])
            if gone is None:
                continue
            whole = {k: v for k, v in lf.items() if k != "gives"}
            whole["gives"] = full.upper()
            cut = checked(node, parts=[whole, {"gives": gone.upper()}])
            new = copy.deepcopy(parts[0])
            for x, par in walk(new):
                if leaf(x) and x.get("words") == lf["words"] and x.get("gives") == lf["gives"] and par is not None:
                    par["parts"][[id(q) for q in par["parts"]].index(id(x))] = cut
                    break
            else:
                continue
            if _eval_swapped(node, parent, new, ctx):
                good[json.dumps(new, sort_keys=True)] = new
    return next(iter(good.values())) if len(good) == 1 else None


def r_ind_in_leaf(node, parent, ctx):
    """indInLeaf / ind_in_leaf: a leaf took the clue words of an indicator as well as its own
    ([books essentially]BOOKS under mostly/essentially on an op). The indicator's span, located in
    the clue, lies at the start or end of this leaf: the leaf keeps the words that give its letters.
    A synonym leaf keeps its filed letters; a literal one gives its remaining words. Kept only when
    the whole tree still evaluates to the answer. An indicator in the middle of a leaf stays for
    the model."""
    if not leaf(node) or not node.get("words") or node.get("at") is None or not ctx.get("answer"):
        return None
    clue = ctx["clue"]
    if clue[node["at"]:node["at"] + len(node["words"])] != node["words"]:
        return None
    la, lb = node["at"], node["at"] + len(node["words"])
    for n, _ in walk(ctx["tree"]):
        for ind in n.get("indicators") or []:
            if ind.get("at") is None or not ind.get("text") or len(W.letters(ind["text"])) < 3:
                continue
            a, b = ind["at"], ind["at"] + len(ind["text"])
            if not (la <= a and b <= lb) or (a, b) == (la, lb) or (a != la and b != lb):
                continue
            text, at = clue_text(clue, b, lb) if a == la else clue_text(clue, la, a)
            if not W.letters(text):
                continue
            literal = not node.get("gives") or W.letters(node["gives"]) == W.letters(node["words"])
            new = {k: v for k, v in node.items() if k not in ("gives", "unchecked")} if literal else dict(node)
            new.update(words=text, at=at)
            if _eval_swapped(node, parent, new, ctx):
                return new
    return None


def _tokens(words):
    return [(m.start(), m.end(), m.group().lower()) for m in re.finditer(r"[A-Za-z0-9']+", words)]


def r_own_ind_leaf(node, parent, ctx):
    """selectWordInLeaf / ownIndInLeaf: a leaf under an op opens (any op but an anagram) or ends (any op)
    with the op's own indicator words and holds more ("bit of breakfast" under first<bit of>, "French way
    back" under rev<back>): the leaf keeps only the words after (before) them. A literal leaf stays
    literal; a synonym leaf keeps its filed letters. Kept only when the whole tree still evaluates to
    the answer (the validator gate in run_rule then judges the rest)."""
    if not leaf(node) or not node.get("words") or parent is None or "op" not in parent or parent["op"] == "anagram" \
            or parent.get("unchecked") or not ctx.get("answer"):
        return None
    toks = _tokens(node["words"])
    for ind in parent.get("indicators") or []:
        iw = [t for _, _, t in _tokens(str(ind.get("text") or ""))]
        if not iw or len(toks) <= len(iw):
            continue
        at_start = [t for _, _, t in toks[:len(iw)]] == iw
        at_end = [t for _, _, t in toks[-len(iw):]] == iw
        if at_start and parent["op"] not in W.SELECT:
            cut = (toks[len(iw)][0], len(node["words"]))
        elif at_start:
            cut = (toks[len(iw)][0], len(node["words"]))
        elif at_end:
            cut = (0, toks[-len(iw) - 1][1])
        else:
            continue
        words = node["words"][cut[0]:cut[1]]
        text = words.strip(" ,;:.!?—–-\"“”‘(){}[]")
        if not W.letters(text):
            continue
        lead = len(words) - len(words.lstrip(" ,;:.!?—–-\"“”‘(){}[]"))
        literal = not node.get("gives") or W.letters(node["gives"]) == W.letters(node["words"])
        new = {k: v for k, v in node.items() if k not in ("gives", "unchecked")} if literal else dict(node)
        new["words"] = text
        if node.get("at") is not None:
            new["at"] = node["at"] + cut[0] + lead
        if _eval_swapped(node, parent, new, ctx):
            return new
    return None


def r_trunc_leaf(node, parent, ctx):
    """truncInLeaf: a leaf holds a truncation word at its edge (mostly, almost, ...) and gives its word one
    letter short. The whole word is known (the leaf's own clue words, or a one-off capitalised word of the
    right length in its note that the filed letters cut): the leaf becomes del<mostly>([words]WHOLE, C).
    A synonym whose whole word is nowhere in the leaf stays for the model."""
    if not leaf(node) or not node.get("words") or not node.get("gives") or node.get("unchecked") \
            or not ctx.get("answer"):
        return None
    toks = _tokens(node["words"])
    low = " ".join(t for _, _, t in toks)
    ind = None
    for phrase in sorted(V._TRUNC_PHRASES, key=len, reverse=True):
        for a, b in ((0, len(phrase.split())), (len(toks) - len(phrase.split()), len(toks))):
            if len(toks) > b - a and " ".join(t for _, _, t in toks[a:b]) == phrase:
                ind = (a, b)
        if ind:
            break
    if not ind:
        for a, b in ((0, 1), (len(toks) - 1, len(toks))):
            if len(toks) > 1 and toks[a][2] in V._TRUNC_WORDS:
                ind = (a, b)
                break
    if not ind:
        return None
    a, b = ind
    ia, ib = toks[a][0], toks[b - 1][1]
    rest = (node["words"][ib:] if a == 0 else node["words"][:ia])
    rest_tok = [t for _, _, t in _tokens(rest)]
    if not rest_tok or (rest_tok[0] if a == 0 else rest_tok[-1]) in ("with", "the", "end", "its", "his", "her", "a", "an", "of"):
        return None   # "fritter with the end | cut off": the cut phrase is wider than the matched words
    x = rest.strip(" ,;:.!?—–-\"“”‘(){}[]")
    g = W.letters(node["gives"])
    cands = set()
    lit = W.letters(x)
    if len(lit) == len(g) + 1:
        cands.add(lit)
    for m in re.findall(r"[A-Z][A-Za-z]+", str(node.get("note") or "")):
        if len(m) == len(g) + 1:
            cands.add(m.upper())
    kinds = {}
    for c in cands:
        if c.upper().startswith(g.upper()):
            kinds[c.upper()] = c.upper()[len(g):]
        elif c.upper().endswith(g.upper()):
            kinds[c.upper()] = c.upper()[0]
    if len(kinds) != 1:
        return None
    whole, gone = next(iter(kinds.items()))
    xlead = len(rest) - len(rest.lstrip(" ,;:.!?—–-\"“”‘(){}[]"))
    base = node.get("at")
    xat = None if base is None else base + (ib if a == 0 else 0) + xlead
    note = str(node.get("note") or "")
    keep_note = note and not V._CUT_NOTE.search(note) and not V._LETTER_REMOVED.search(note) and not V._BRIEFLY_CUT.search(note)
    held = {"words": x, "gives": whole}
    if xat is not None:
        held["at"] = xat
    held["note"] = note if keep_note else (f"{whole} is the word '{x}' itself" if lit == whole
                                           else f"{whole} is what '{x}' stands for")
    itext = node["words"][ia:ib]
    ind_node = {"text": itext, "note": f"'{itext}' cuts a letter off"}
    if base is not None:
        ind_node["at"] = base + ia
    new = {"op": "deletion", "indicators": [ind_node], "parts": [held, {"gives": gone}]}
    if _eval_swapped(node, parent, new, ctx):
        return new
    return None


def r_link_in_leaf(node, parent, ctx):
    """linkInLeaf (r25): a leaf opening or closing with a link word (in, of, with, by ...) whose other
    words alone give its letters ([in Southwest]SW): the leaf keeps the other words. Kept only when
    the tree still gives the answer and no detector fires that did not."""
    if not leaf(node) or not node.get("words") or not V.link_in_leaf(node):
        return None
    ws = node["words"].split()
    g = W.letters(node["gives"])
    for lead, rest, link in ((True, ws[1:], ws[0]), (False, ws[:-1], ws[-1])):
        if W.letters(link).lower() in V._LEAF_LINKS and not (lead and link.lower() == "to") \
                and V._known_pair(" ".join(rest), g):
            new = dict(node)
            new["words"] = " ".join(rest)
            if lead and isinstance(node.get("at"), int):
                new["at"] = node["at"] + len(ws[0]) + 1
            if _eval_swapped(node, parent, new, ctx):
                return new
    return None


def r_ind_leaf_overlap(node, parent, ctx):
    """indLeafOverlap (r25): a two-word indicator whose word is also a whole leaf's words ("is beaten"
    with a leaf "is"): the indicator keeps its other word. Kept only when the tree still gives the answer
    and no detector fires that did not."""
    inds = node.get("indicators") or []
    leafwords = {W.letters(n["words"]) for n, _ in walk(ctx["tree"]) if leaf(n) and n.get("words") and " " not in n["words"].strip()}
    for k, ind in enumerate(inds):
        ws = str(ind.get("text") or "").split()
        if len(ws) != 2:
            continue
        for keep, drop in ((1, 0), (0, 1)):
            if W.letters(ws[drop]) in leafwords and W.letters(ws[keep]) not in leafwords:
                new = copy.deepcopy(node)
                new["indicators"][k]["text"] = ws[keep]
                if isinstance(ind.get("at"), int):
                    new["indicators"][k]["at"] = ind["at"] + (len(ws[0]) + 1 if keep == 1 else 0)
                if _eval_swapped(node, parent, new, ctx):
                    return new
    return None


def r_swapped_pair(node, parent, ctx):
    """swappedPair (r25): a parent op and its child op of another type carry each other's indicators:
    swap them back. Kept only when the tree still gives the answer and no detector fires that did not."""
    if not V.swapped_pair({"op": node.get("op"), "indicators": node.get("indicators"), "parts": node.get("parts")}):
        return None
    for k, c in enumerate(node.get("parts") or []):
        if not isinstance(c, dict) or "op" not in c:
            continue
        new = copy.deepcopy(node)
        new["indicators"], new["parts"][k]["indicators"] = copy.deepcopy(c.get("indicators")), copy.deepcopy(node.get("indicators"))
        if V.swapped_pair(new) == 0 and _eval_swapped(node, parent, new, ctx):
            return new
    return None


def _misplaced_keys(node):
    """The indicators of charade `node` that V.misplaced_indicators flags, each tried alone."""
    out = []
    for i in node.get("indicators") or []:
        probe = {k: v for k, v in node.items() if k != "indicators"}
        probe["indicators"] = [i]
        if V.misplaced_indicators(probe):
            out.append(i)
    return out


def _lex_types(ind):
    """The lexicon types that file the indicator's words 200+ times (what op it signals)."""
    lex = V._indicator_lexicon()
    key = " ".join(w for w in (W.letters(x) for x in str(ind.get("text") or "").split()) if w)
    return {t for t, d in lex.items() if t != "charade" and d.get(key, 0) >= V.MISPLACED_MIN_USES}


def _fits_charade(ind):
    """Whether the indicator's words are fine on a charade (the lexicon, or an ordering/position word)."""
    lex = V._indicator_lexicon()
    key = " ".join(w for w in (W.letters(x) for x in str(ind.get("text") or "").split()) if w)
    return bool(lex.get("charade", {}).get(key, 0)) or key.lower() in V.ORDERING_INDICATORS \
        or key.lower() in V.POSITION_INDICATORS


def r_misplaced_indicator(node, parent, ctx):
    """misplacedIndicator: a charade carries a word the lexicon files only under another op. When
    exactly one op inside it (its own descendant) is of that type, the word moves there: onto an op
    with no indicator, or in a swap with an op whose word is fine on a charade (visa returned,
    opened by: Smoke rising over fine = rev<rising>(smoke) with 'over' left to the charade). A
    one-letter leaf of the charade that is the first/last letter of its own words is wrapped in
    the selection the word names (Tory leader = first<leader>(Tory)). Kept only when the whole
    tree still gives the answer and exactly one placement does."""
    if node.get("op") != "charade" or node.get("unchecked") or not node.get("indicators"):
        return None
    bad = _misplaced_keys(node)
    if len(bad) != 1 or len(node["indicators"]) != 1:
        return None
    ind = bad[0]
    types = _lex_types(ind)
    if not types:
        return None
    rest = [i for i in node["indicators"] if i is not ind]
    base = {k: v for k, v in node.items() if k != "indicators"}
    if rest:
        base["indicators"] = rest
    good = {}

    def keep(new):
        if not V.misplaced_indicators(new) and _eval_swapped(node, parent, new, ctx):
            good[json.dumps(new, sort_keys=True)] = new
    for d, _ in list(walk(node))[1:]:
        if leaf(d) or V._OP_LEXICON.get(d.get("op")) not in types or d.get("unchecked"):
            continue
        new = copy.deepcopy(base)
        target = next(x for x, _ in walk(new) if x.get("op") == d.get("op") and x.get("parts") == d.get("parts"))
        have = d.get("indicators") or []
        if not have:
            target["indicators"] = [copy.deepcopy(ind)]
            keep(new)
        elif len(have) == 1 and _fits_charade(have[0]) and not rest:
            target["indicators"] = [copy.deepcopy(ind)]
            new["indicators"] = [copy.deepcopy(have[0])]
            keep(new)
    sel = [t for t in types if t == "letter_selection"]
    for k, lf in enumerate(node.get("parts") or []):
        if sel and leaf(lf) and lf.get("words") and lf.get("gives") and not lf.get("unchecked"):
            g, w = W.letters(lf["gives"]), W.letters(lf["words"])
            if len(g) != 1 or not w or ind.get("text") in lf["words"] or annotation.is_abbreviation(lf):
                continue    # an abbreviation (company CO, son S) is a table entry, not a pick
            for op, pick in (("first", w[0]), ("last", w[-1])):
                if g == pick:
                    new = copy.deepcopy(base)
                    inner = {x: y for x, y in lf.items() if x != "gives"}
                    new["parts"][k] = {"op": op, "indicators": [copy.deepcopy(ind)], "parts": [inner]}
                    keep(new)
    if not good:
        return None
    return next(iter(good.values())) if len(good) == 1 else None


def r_shared_charade(node, parent, ctx):
    """sharedIndicator, charade: an indicator filed on a charade whose words are also a leaf's clue
    words in it ([over]RE + [Fell]LAPSED with 'over' on the charade as well). A charade needs no
    indicator, so the word stays with the leaf that gives letters for it and leaves the charade."""
    if node.get("op") != "charade" or node.get("unchecked") or not node.get("indicators"):
        return None
    words = {W.letters(p["words"]) for p in node.get("parts") or []
             if isinstance(p, dict) and leaf(p) and p.get("words") and p.get("gives")}
    keep = [i for i in node["indicators"] if W.letters(i.get("text")) not in words]
    if len(keep) == len(node["indicators"]):
        return None
    new = {k: v for k, v in node.items() if k != "indicators"}
    if keep:
        new["indicators"] = keep
    return new if _eval_swapped(node, parent, new, ctx) else None


HALF = re.compile(r"\bhalf\b|\bhalved\b|\bmostly\b|\bsemi|\bdemi", re.I)


def r_half_cut(node, parent, ctx):
    """half_cut: a deletion that takes exactly half of a word, under an indicator that means half
    ("not half", "half", "mostly"): SIR + del<not half>(DARING, ING) is the first half of DARING.
    The deletion becomes first/last over the leaf, the same indicator kept (Paul, round 15)."""
    parts = node.get("parts") or []
    inds = node.get("indicators") or []
    if node.get("op") != "deletion" or len(parts) != 2 or len(inds) != 1 or not HALF.search(inds[0].get("text") or ""):
        return None
    whole, gone = parts
    if not leaf(whole) or not whole.get("gives") or "op" in gone or not gone.get("gives") or gone.get("words"):
        return None
    full, cut = W.letters(whole["gives"]), W.letters(gone["gives"])
    if len(full) % 2 or len(cut) != len(full) // 2:
        return None
    op = "first" if full.endswith(cut) else "last" if full.startswith(cut) else None
    if op is None:
        return None
    new = {"op": op, "indicators": copy.deepcopy(inds), "parts": [copy.deepcopy(whole)]}
    return new if (full[:len(cut)] if op == "first" else full[len(cut):]) in (vals(new) or ()) else None


REPAIRS = {"ins_split": r_ins_split, "del_removed": r_del_removed, "del_unwrap": r_del_unwrap,
           "arity_wrap": r_arity_wrap, "half_cut": r_half_cut, "leaf_trim": r_leaf_trim, "ind_trim": r_ind_trim,
           "leaf_check": r_leaf_check, "link_leaf": r_link_leaf, "sel_literal": r_sel_literal}
#: Repairs for validator rules (the queue's anaSynonym / anagramOfContainer rows), run by --rule.
def r_arity_ins(node, parent, ctx):
    """arity_ins: an unchecked container that holds one charade (or one anagram / reversal /
    cycling / deletion) of several parts, or 3+ parts. The parts are the held and the holder
    run together: split them into a contiguous run (inner) and the rest (outer), the unary op
    (if any) wrapping one group. Kept only when the whole tree gives the answer and exactly one
    reading does; a charade's own indicators move to the container (one op per indicator)."""
    if node.get("op") != "container" or not node.get("unchecked") or len(node.get("parts") or []) == 2:
        return None
    parts = node["parts"]
    if len(parts) > 1 and len(parts) >= 3:
        unary = None
        items = parts
    elif len(parts) == 1 and parts[0].get("op") and not parts[0].get("unchecked") \
            and (parts[0]["op"] == "charade" or parts[0]["op"] in ("anagram", "reversal", "cycling", "deletion")):
        unary = None if parts[0]["op"] == "charade" else parts[0]
        items = parts[0]["parts"]
    else:
        return None
    if len(items) < 2 or any(x.get("unchecked") for it in items for x, _ in walk(it)):
        return None     # an unchecked piece has no letters: the answer cannot vouch for where it sits
    base = {k: v for k, v in node.items() if k not in ("unchecked", "gives", "parts")}
    if len(parts) == 1 and unary is None and parts[0].get("indicators"):
        base["indicators"] = (base.get("indicators") or []) + copy.deepcopy(parts[0]["indicators"])
    good = {}

    def group(sub, wrap):
        if wrap:
            return {**copy.deepcopy(unary), "parts": copy.deepcopy(sub)}
        return charade(copy.deepcopy(sub))
    n = len(items)
    for i in range(n):
        for j in range(i, n):
            inner_i, outer_i = items[i:j + 1], items[:i] + items[j + 1:]
            if not outer_i:
                continue
            for wrap in ((None,) if unary is None else ("inner", "outer")):
                inner = group(inner_i, wrap == "inner")
                outer = group(outer_i, wrap == "outer")
                new = {**base, "parts": [outer, inner]}
                if _eval_swapped(node, parent, new, ctx):
                    good[json.dumps(new, sort_keys=True)] = new
    return next(iter(good.values())) if len(good) == 1 else None


def r_removed_leaf(node, parent, ctx):
    """unchecked_leaf: a one-part deletion over a charade holding a letterless unchecked leaf
    (DEPORTMENT: del(charade(DEPORT, MEN, T?)) with "billions" never given letters). The leaf is
    the removed part, not a charade piece: it leaves the charade and becomes the deletion's second
    part, its `gives` the letters the rest of the charade has beyond the target (the deletion's own
    `gives`, or the answer at the root). Kept only when those letters are one string and the whole
    tree gives the answer."""
    if node.get("op") != "deletion" or len(node.get("parts") or []) != 1:
        return None
    inner = node["parts"][0]
    if inner.get("op") != "charade" or inner.get("unchecked") or "gives" in inner:
        return None
    gone = [p for p in inner.get("parts") or []
            if leaf(p) and p.get("unchecked") and p.get("words") and not W.letters(p.get("gives"))]
    if len(gone) != 1:
        return None
    lf = gone[0]
    want = W.letters(node.get("gives")) or (W.letters(ctx.get("answer")) if parent is None else "")
    rest = charade([copy.deepcopy(p) for p in inner["parts"] if p is not lf])
    vs = vals(rest)
    if not want or not vs or len(vs) != 1:
        return None
    v = next(iter(vs))
    m = len(v) - len(want)
    if m == 0 and v == want:
        return _letters_back(node, parent, ctx, inner, lf)
    if not 1 <= m <= 4:
        return None
    cuts = {v[j:j + m] for j in range(len(v) - m + 1) if v[:j] + v[j + m:] == want}
    if len(cuts) != 1:
        return None
    new_leaf = {k: x for k, x in lf.items() if k != "unchecked"}
    new_leaf["gives"] = cuts.pop()
    return checked(node, parts=[rest, new_leaf])


_ABBR = {}


def _abbreviations(words):
    """The letters the abbreviation tables read `words` as (king K, billions B, unknown X/Y/Z)."""
    if not _ABBR:
        pairs, _ = V._attested()
        for k, g in pairs | set(V._EXTRA_PAIRS):
            _ABBR.setdefault(k, set()).add(g)
    key = re.sub(r"[^A-Z]", "", str(words).upper())
    # a one-letter word ("I", "A") stands for itself
    return _ABBR.get(key, set()) | ({key} if len(key) == 1 else set())


def _letters_back(node, parent, ctx, inner, lf):
    """The removed leaf's letters were never filed because the charade's leaf already shows the word
    cut (Rant -> TRADE, with I removed from TIRADE): put the abbreviation's letters back into one
    other leaf of the charade, where the result is a word of the lexicon, and let the deletion take
    them out again. Kept only when exactly one leaf, place and reading does it."""
    lex = V._lexicon_letters()
    if not lex:
        return None
    found = {}
    for q, _ in walk(inner):
        if not leaf(q) or q is lf or not q.get("words") or not W.letters(q.get("gives")) or q.get("unchecked"):
            continue
        g = W.letters(q["gives"])
        for x in _abbreviations(lf["words"]):
            for i in range(len(g) + 1):
                cand = g[:i] + x + g[i:]
                if cand == g or cand.lower() not in lex or len(cand) < 4:
                    continue
                new_inner = copy.deepcopy(inner)
                for nq, _ in walk(new_inner):
                    if leaf(nq) and nq == q:
                        nq["gives"] = cand
                        nq["note"] = f"{nq['words']} gives {cand}, before the {x} goes"
                        break
                ps = [p for p in new_inner["parts"] if not (leaf(p) and p == lf)]
                rest = charade(ps) if len(ps) != 1 else ps[0]
                new_leaf = {k: v for k, v in lf.items() if k != "unchecked"}
                new_leaf["gives"] = x
                new = checked(node, parts=[rest, new_leaf])
                if _eval_swapped(node, parent, new, ctx):
                    found[json.dumps(new, sort_keys=True)] = (new, cand)
    if len(found) > 1:
        # several lexicon words fit (TIRADE, TRADIE): the one the annotation's own notes name
        text = json.dumps(ctx["tree"]).lower()
        named = {k: v for k, v in found.items() if re.search(r"\b%s\b" % v[1].lower(), text)}
        found = named
    return next(iter(found.values()))[0] if len(found) == 1 else None


def r_literal_fodder(node, parent, ctx):
    """unchecked_step: an anagram filed with its fodder's results (ana([Verdun + CU]) with `gives`
    on its leaves, the letters already in answer order) so the evaluator calls it "already the
    answer" and the step stays unchecked. The fodder is the clue words themselves: the leaves under
    an anagram lose their filed `gives`, every flag goes, and the evaluator scrambles the real
    words. Kept only when the whole tree then gives the answer."""
    if parent is not None or not ctx.get("answer") or not unchecked(node):
        return None
    if not any(n.get("op") == "anagram" and n.get("unchecked") for n, _ in walk(node)):
        return None
    new = copy.deepcopy(node)
    for n, _ in walk(new):
        for key in ("unchecked", "select", "soundsLike"):   # fields the schema allows on unchecked leaves only
            n.pop(key, None)
        if "op" in n:
            n.pop("gives", None)
        if n.get("op") == "anagram":
            for q, _ in walk(n):
                if leaf(q) and q.get("words"):
                    q.pop("gives", None)
    return new if _eval_swapped(node, None, new, ctx) else None


def r_ana_charade(node, parent, ctx):
    """anaCharade: an anagram whose fodder pieces already spell the answer ("the fodder already
    reads TAPER": ana<upset>(pates=TAPE + queen=R)). Each piece that gives the scramble of its own
    clue words (pates -> TAPE) is the real fodder, the rest are charade pieces beside it: the
    scrambled pieces (together, when adjacent) go under the anagram as the clue's words, the others
    stay, in order. The indicator words the piece swallowed come off it. Kept only when the whole
    tree gives the answer and exactly one arrangement does."""
    if node.get("op") != "anagram" or not ctx.get("answer"):
        return None
    pieces = _flat_fodder(node)
    if len(pieces) < 2 or any(not leaf(p) or not p.get("words") or p.get("select") for p in pieces):
        return None
    inds = [W.letters(i.get("text")) for i in node.get("indicators") or []]

    def real(p):
        """(words, fodder letters or None) for a leaf whose words, without the anagram's own
        indicator at an edge, scramble to its gives (a possessive s the word carries aside)."""
        g = W.letters(p.get("gives")) or W.letters(p["words"])
        ws = p["words"].split()
        for a in range(len(ws)):
            for b in range(a + 1, len(ws) + 1):
                run, rest = " ".join(ws[a:b]), ws[:a] + ws[b:]
                if (a, b) != (0, len(ws)):
                    if W.letters(run) not in inds or (a and b < len(ws)):
                        continue
                    keep = " ".join(rest)
                else:
                    keep = run
                for k2 in (keep, " ".join(w for w in keep.split() if w.lower() not in ("and", "with", "of", "the", "a", "in", "to"))):
                    lk = W.letters(k2)
                    if not lk:
                        continue
                    if sorted(lk) == sorted(g) and lk != g:
                        return keep, (None if k2 == keep else lk)
                    if lk.endswith("S") and sorted(lk[:-1]) == sorted(g) and lk[:-1] != g:
                        return keep, lk[:-1]
        return None
    scr = [real(p) for p in pieces]
    if not any(scr):
        return None
    good = {}
    for mask in range(1, 2 ** len(pieces)):
        pick = [i for i in range(len(pieces)) if mask >> i & 1 and scr[i]]
        if len(pick) != bin(mask).count("1"):
            continue
        # one pool: the picked pieces must sit side by side
        if pick != list(range(pick[0], pick[-1] + 1)):
            continue
        pool = []
        for i in pick:
            q = {k: v for k, v in pieces[i].items() if k != "gives"}
            keep, lit = scr[i]
            if keep != q["words"]:
                if isinstance(q.get("at"), int):
                    q["at"] += q["words"].find(keep)
                q["words"] = keep
            if lit:
                q["gives"] = lit
            pool.append(q)
        new = {k: v for k, v in node.items() if k not in ("unchecked", "gives", "parts")}
        new["parts"] = copy.deepcopy(pool)
        out = [copy.deepcopy(p) for p in pieces[:pick[0]]] + [new] + [copy.deepcopy(p) for p in pieces[pick[-1] + 1:]]
        cand = charade(out)
        if _eval_swapped(node, parent, cand, ctx):
            good[json.dumps(cand, sort_keys=True)] = cand
    return next(iter(good.values())) if len(good) == 1 else None


def _piece_options(p):
    """The letter strings a fodder piece can contribute (a leaf's filed letters; a sub-operation's
    values, a first-N-letters pick having several), sorted; [] when unknown or too many."""
    if leaf(p):
        g = W.letters(W.leaf_letters(p))
        return [g] if g else []
    vs = vals(p)
    return sorted(v for v in vs if v) if vs and len(vs) <= 8 else []


def _spells(ans, pre, mid, suf):
    """Whether some choice of one option per piece makes ans = pre + (an anagram of mid) + suf."""
    for ch in itertools.product(*pre, *mid, *suf):
        p, m, s = "".join(ch[:len(pre)]), "".join(ch[len(pre):len(pre) + len(mid)]), "".join(ch[len(pre) + len(mid):])
        if len(p) + len(m) + len(s) == len(ans) and ans.startswith(p) and ans.endswith(s) \
                and sorted(ans[len(p):len(ans) - len(s)]) == sorted(m):
            return True
    return False


def _stand_in(p):
    """A piece that is not the clue's own words scrambled: a synonym, abbreviation or sub-operation."""
    if not leaf(p):
        return True
    return bool(p.get("select") or p.get("soundsLike")
                or (p.get("gives") and W.letters(p["gives"]) != W.letters(p.get("words"))))


def r_ana_pull(node, parent, ctx):
    """anaCharade (Paul 10-19: "if the letter is correctly placed outside, it shouldn't be in the
    anagram"): ana<troubled>(G + FIRE) = GRIEF is charade(G, ana<troubled>(FIRE)). The anagram sits
    over a charade (or loose pieces) of 2+ pieces for the WHOLE answer; the pieces the answer starts
    with (in some order) and/or ends with are pulled out as charade siblings, when the pieces left
    spell the rest of the answer between them. Every stand-in piece (synonym, abbreviation, sub-op)
    must be pulled: only the clue's own words are scrambled. Of the ways that work, the one pulling
    fewest pieces, in their original order, is kept, and only when exactly one tree results. The
    charade's own indicators and notes stay on the new charade; the anagram's stay on the anagram.
    Neither end working leaves the clue flagged for the model."""
    if node.get("op") != "anagram" or node.get("unchecked") or parent is not None or not ctx.get("answer"):
        return None
    parts = node.get("parts") or []
    cs_ = [p for p in parts if p.get("op") == "charade"]
    if len(cs_) != 1 or cs_[0].get("unchecked") or "gives" in cs_[0]:
        return None
    wrap = {k: v for k, v in cs_[0].items() if k != "parts"}
    pieces = []
    for p in parts:
        pieces += cs_[0]["parts"] if p is cs_[0] else [p]
    if not 2 <= len(pieces) <= 7 or any(p.get("op") == "charade" or p.get("unchecked") for p in pieces):
        return None
    ls = [_piece_options(p) for p in pieces]
    ans = W.letters(ctx["answer"])
    if any(not l for l in ls):
        return None
    must = {i for i, p in enumerate(pieces) if _stand_in(p)}
    n = len(pieces)
    if not must and any(sorted("".join(c)) == sorted(ans) for c in itertools.product(*ls)):
        # all the clue's own words and together the whole answer: one pool, the charade was just a join
        if wrap:
            return None
        flat = {k: v for k, v in node.items() if k not in ("parts", "unchecked", "gives")}
        flat["parts"] = copy.deepcopy(pieces)
        return flat if _eval_swapped(node, parent, flat, ctx) else None
    found = {}
    for mask_a in range(1 << n):
        for mask_b in range(1 << n):
            if mask_a & mask_b or not (mask_a | mask_b) or must - {i for i in range(n) if (mask_a | mask_b) >> i & 1}:
                continue
            a = [i for i in range(n) if mask_a >> i & 1]
            b = [i for i in range(n) if mask_b >> i & 1]
            r = [i for i in range(n) if not (mask_a | mask_b) >> i & 1]
            if not r:
                continue
            # the original order is tried first (permutations yields it first), so it wins when it works
            for pre, suf in itertools.product(itertools.permutations(a), itertools.permutations(b)):
                if _spells(ans, [ls[i] for i in pre], [ls[i] for i in r], [ls[i] for i in suf]):
                    found.setdefault((frozenset(a), frozenset(b)), ((pre, suf), r))
    if not found:
        return None
    least = min(len(a) + len(b) for a, b in found)
    best = [v for (a, b), v in found.items() if len(a) + len(b) == least]
    cands = []
    for (pre, suf), r in best:
        ana = {k: v for k, v in node.items() if k not in ("parts", "unchecked", "gives")}
        ana["parts"] = [copy.deepcopy(pieces[i]) for i in r]
        outer = [copy.deepcopy(pieces[i]) for i in pre] + [ana] + [copy.deepcopy(pieces[i]) for i in suf]
        cands.append({**copy.deepcopy(wrap), "op": "charade", "parts": outer})
    good = {json.dumps(c, sort_keys=True): c for c in cands if _eval_swapped(node, parent, c, ctx)}
    if len(good) > 1:
        # both ends work (ARSE + first(effort) = ERASE: E + RASE or ERAS + E): the pieces as filed,
        # the pulled ones keeping their place before / after the scrambled ones
        keep = {json.dumps(c, sort_keys=True): c for ((pre, suf), r), c in zip(best, cands)
                if json.dumps(c, sort_keys=True) in good
                and all(i < min(r) for i in pre) and all(i > max(r) for i in suf)}
        good = keep if len(keep) == 1 else good
    return next(iter(good.values())) if len(good) == 1 else None


def r_ana_edge(node, parent, ctx):
    return _ana_edge_with(node, parent, ctx, V._stand_in_piece)


def r_ana_select_edge(node, parent, ctx):
    """anaSelectEdge: the same pull for a first/last-letter pick at the edge of the fodder, which may
    stand at either end of the answer (G + ana(MALE) for ana(MALE, first(gymnast's)))."""
    return _ana_edge_with(node, parent, ctx, V._stand_in_or_select, True)


def _ana_edge_with(node, parent, ctx, stand, either_end=False):
    """anaCharade, any depth (Paul 10-19): an anagram whose first / last fodder parts are
    abbreviation or synonym leaves standing at that edge of the scramble's output (ana<unusual>(N +
    RIP SIGN) inside I + ..., where N opens the scramble) -> those parts come out and sit beside the
    anagram in a charade (joined into a parent charade). The fewest pulled wins; kept only when the
    whole tree still gives the answer and exactly one such tree does, else the clue is left for redo."""
    if node.get("op") != "anagram" or node.get("unchecked") or not ctx.get("answer"):
        return None
    parts = node.get("parts") or []
    if len(parts) < 2 or any(not isinstance(p, dict) or p.get("unchecked") for p in parts):
        return None
    st = [stand(p) for p in parts]
    lead = next((i for i, s in enumerate(st) if not s), len(st))
    trail = next((i for i, s in enumerate(reversed(st)) if not s), len(st))
    if lead >= len(st):
        return None
    good = {}
    for j in range(lead + 1):
        for k in range(trail + 1):
            if not (j + k) or j + k >= len(parts):
                continue
            ana = {key: v for key, v in node.items() if key not in ("parts", "unchecked", "gives")}
            ana["parts"] = copy.deepcopy(parts[j:len(parts) - k])
            pre, suf = copy.deepcopy(parts[:j]), copy.deepcopy(parts[len(parts) - k:])
            for order in [pre + [ana] + suf] + ([suf + [ana] + pre] if either_end and not (pre and suf) else []):
                cand = {"op": "charade", "parts": order}
                if _eval_swapped(node, parent, cand, ctx):
                    good[(j + k, json.dumps(cand, sort_keys=True))] = cand
    if not good:
        return None
    least = min(g[0] for g in good)
    best = [c for (n_, _), c in good.items() if n_ == least]
    return best[0] if len(best) == 1 else None


def _path(root, target):
    """The indexes of `parts` that lead from `root` to the node `target` ([] for root itself)."""
    if root is target:
        return []
    for k, p in enumerate(root.get("parts") or []):
        r = _path(p, target)
        if r is not None:
            return [k] + r
    return None


def _at(root, pth):
    for k in pth:
        root = root["parts"][k]
    return root


def r_scrambled_swap(node, parent, ctx):
    """scrambledLeaf: a leaf giving the scramble of its own words (strife's -> FIRSTES) beside an
    anagram op over one synonym leaf (ana<involved>(Sailor=RAT)): the anagram indicator went on the
    wrong word. The anagram moves onto the scrambled leaf, which becomes verbatim clue words, and
    the synonym stands bare where the anagram was. Done on the whole tree, for one such leaf and one
    such anagram; kept when the tree still gives the answer and the rule no longer fires."""
    if parent is not None or not ctx.get("answer") or not V.scrambled_leaves(node, min_len=3):
        return None
    scr, ana = [], []
    stack = [(node, None, ())]
    while stack:
        n, par, anc = stack.pop()
        stack += [(p, n, anc + (n,)) for p in n.get("parts") or []]
        if leaf(n):
            w, g = W.letters(n.get("words")), W.letters(n.get("gives"))
            if n.get("words") and g and len(g) >= 3 and g != w and sorted(g) == sorted(w) and not n.get("unchecked") \
                    and not any(a.get("op") == "anagram" for a in anc) \
                    and not (par and par.get("op") in ("reversal", "cycling")):
                scr.append(n)
        elif n.get("op") == "anagram" and len(n.get("parts") or []) == 1 and not n.get("unchecked") \
                and leaf(n["parts"][0]) and n["parts"][0].get("words") and n["parts"][0].get("gives") \
                and sorted(W.letters(n["parts"][0]["gives"])) != sorted(W.letters(n["parts"][0]["words"])):
            ana.append(n)
    if len(scr) != 1 or len(ana) != 1:
        return None
    new = copy.deepcopy(node)
    s_new, a_new = _at(new, _path(node, scr[0])), _at(new, _path(node, ana[0]))
    wrap = {k: v for k, v in a_new.items() if k != "parts"}
    wrap["parts"] = [{k: v for k, v in s_new.items() if k != "gives"}]
    sole = a_new["parts"][0]
    sp, ap = _path(new, s_new), _path(new, a_new)
    if not sp or s_new is a_new:
        return None
    _at(new, sp[:-1])["parts"][sp[-1]] = wrap
    if ap:
        _at(new, ap[:-1])["parts"][ap[-1]] = sole
    else:
        return None     # the anagram is the root and the scrambled leaf sits under it: not this shape
    try:
        W.evaluate(copy.deepcopy(new), ctx["answer"])
    except (W.WordplayError, IndexError, KeyError, TypeError, ValueError, W._NeedTarget):
        return None
    return new if V.scrambled_leaves(new, min_len=3) < V.scrambled_leaves(node, min_len=3) else None


_HALF = re.compile(r"\bhalf\b|\bhalves\b|50\s*%|\bhalf-", re.I)


def r_half_leaf(node, parent, ctx):
    """halfLeaf: a leaf giving half of its one word (STR from street) with the clue's "half" word
    sitting on some other op (the del<half>(..) that was never a deletion of anything, the ins's
    second word, a charade's trailing "half-cut"). The word moves onto a first/last op over that
    leaf, which is what picks the half; a one-part deletion left with nothing else goes. Done on
    the whole tree, for the one half leaf and the one half word only; kept when the tree still
    gives the answer and the rule no longer fires."""
    if parent is not None or not ctx.get("answer"):
        return None
    seen = []
    stack = [(node, ())]
    while stack:
        n, anc = stack.pop()
        stack += [(p, anc + (n,)) for p in n.get("parts") or []]
        if leaf(n) and n.get("words") and n.get("gives") and not n.get("select") and not n.get("unchecked"):
            seen.append((n, anc))
    halves = []
    for lf, anc in seen:
        w, g = W.letters(lf["words"]), W.letters(lf["gives"])
        if len(lf["words"].split()) == 1 and len(w) >= 4 and len(g) * 2 == len(w) and (w.startswith(g) != w.endswith(g)) \
                and not any(a.get("op") in W.SELECT or a.get("op") == "hidden" for a in anc) \
                and not V._known_pair(lf["words"], g):
            halves.append((lf, anc, "first" if w.startswith(g) else "last"))
    owners = [(n, i) for n, _ in walk(node) for i in n.get("indicators") or [] if _HALF.search(i.get("text") or "")]
    if len(halves) != 1 or len(owners) != 1 or not V.half_leaves(node):
        return None
    lf, anc, op = halves[0]
    holder, ind = owners[0]
    if not anc:
        return None
    new = copy.deepcopy(node)
    # find the same nodes in the copy by their path from the root
    def path(root, target):
        if root is target:
            return []
        for k, p in enumerate(root.get("parts") or []):
            r = path(p, target)
            if r is not None:
                return [k] + r
        return None

    def at(root, pth):
        for k in pth:
            root = root["parts"][k]
        return root
    lf_new, holder_new = at(new, path(node, lf)), at(new, path(node, holder))
    ind_new = next(i for i in holder_new["indicators"] if i.get("text") == ind.get("text"))
    holder_new["indicators"] = [i for i in holder_new["indicators"] if i is not ind_new]
    pick = {"op": op, "indicators": [{**ind_new, "note": f"keeps the {op} half of the word"}],
            "parts": [{k: v for k, v in lf_new.items() if k != "gives"}]}
    pth = path(node, lf)
    if pth:
        at(new, pth[:-1])["parts"][pth[-1]] = pick
    if not holder_new["indicators"]:
        holder_new.pop("indicators")
        if holder_new.get("op") == "deletion" and len(holder_new.get("parts") or []) == 1:
            hp = path(new, holder_new)
            sole = holder_new["parts"][0]
            if hp:
                at(new, hp[:-1])["parts"][hp[-1]] = sole
            else:
                new = sole
        elif holder_new.get("op") in V.NEEDS_INDICATOR:
            return None
    try:
        W.evaluate(copy.deepcopy(new), ctx["answer"])
    except (W.WordplayError, IndexError, KeyError, TypeError, ValueError, W._NeedTarget):
        return None
    return new if not V.half_leaves(new) else None


def _runs(n, k):
    """Every way to cut range(n) into k contiguous non-empty runs, as lists of (lo, hi)."""
    if k == 1:
        yield [(0, n)]
        return
    for c in range(1, n - k + 2):
        for rest in _runs(n - c, k - 1):
            yield [(0, c)] + [(a + c, b + c) for a, b in rest]


def _arity_cands(node):
    """Rewrites of an unchecked unary op or substitution that holds too many parts: each a list
    of charade pieces, the op acting on one run of the parts (or three runs, for a substitution)."""
    op, parts = node.get("op"), node.get("parts") or []
    if not node.get("unchecked") or len(parts) < 2 or any(x.get("unchecked") for p in parts for x, _ in walk(p)):
        return
    base = {k: v for k, v in node.items() if k not in ("unchecked", "gives", "parts")}

    def group(run):
        return copy.deepcopy(run[0]) if len(run) == 1 else charade(copy.deepcopy(run))
    n = len(parts)
    if op in UNARY:
        for i in range(n):
            for j in range(i, n):
                yield copy.deepcopy(parts[:i]) + [{**base, "parts": [group(parts[i:j + 1])]}] + copy.deepcopy(parts[j + 1:])
    elif op == "substitution" and n >= 4:
        for a in range(n - 2):
            for b in range(a + 3, n + 1):
                for cuts in _runs(b - a, 3):
                    runs = [parts[a + lo:a + hi] for lo, hi in cuts]
                    for order in itertools.permutations(range(3)):
                        sub = {**base, "parts": [group(runs[o]) for o in order]}
                        yield copy.deepcopy(parts[:a]) + [sub] + copy.deepcopy(parts[b:])


def r_arity_other(node, parent, ctx):
    """arity_other: an unchecked unary op (reversal, cycling, hidden, a letter pick) or a
    substitution filed with more parts than it takes. The op acts on one run of its parts and
    the rest are charade pieces beside it (rev(A, LIFE) -> A + rev(LIFE); a 4-part sub -> the
    three it takes, in whichever order, with the leftover parts before or after). A container
    holding one such op (ins(cyc(CALYPSO, APE))) splits the pieces into outer and inner as well.
    Kept only when the whole tree gives the answer and exactly one reading does."""
    good = {}
    if node.get("op") == "container" and node.get("unchecked") and len(node.get("parts") or []) == 1:
        base = {k: v for k, v in node.items() if k not in ("unchecked", "gives", "parts")}
        for items in _arity_cands(node["parts"][0]):
            for i in range(len(items)):
                for j in range(i, len(items)):
                    outer = items[:i] + items[j + 1:]
                    if not outer:
                        continue
                    new = {**base, "parts": [charade(copy.deepcopy(outer)), charade(copy.deepcopy(items[i:j + 1]))]}
                    if _eval_swapped(node, parent, new, ctx):
                        good[json.dumps(new, sort_keys=True)] = new
    else:
        for items in _arity_cands(node):
            new = charade(items)
            if _eval_swapped(node, parent, new, ctx):
                good[json.dumps(new, sort_keys=True)] = new
    return next(iter(good.values())) if len(good) == 1 else None


def r_ana_lone_edge(node, parent, ctx):
    """anaLoneEdge (Paul 10-19: a lone letter that can sit outside the anagram must): an anagram with
    a one-letter fodder part (abbreviation, first/last pick, a lone word) anywhere in its fodder. The
    letter(s) come out and sit in a charade before or after the anagram, in whichever place the whole
    tree still gives the answer. The fewest letters pulled wins; kept only when exactly one tree does."""
    if node.get("op") != "anagram" or node.get("unchecked") or not ctx.get("answer"):
        return None
    parts = node.get("parts") or []
    if len(parts) < 2 or any(not isinstance(p, dict) or p.get("unchecked") for p in parts):
        return None
    lone = [i for i in range(len(parts)) if V._one_letter_part(parts, i)]
    if not lone or len(lone) >= len(parts):
        return None
    good = {}
    same = {}
    for size in (1, 2):
        for pick in itertools.combinations(lone, size):
            rest = [p for i, p in enumerate(parts) if i not in pick]
            ana = {key: v for key, v in node.items() if key not in ("parts", "unchecked", "gives")}
            ana["parts"] = copy.deepcopy(rest)
            out = [copy.deepcopy(parts[i]) for i in pick]
            for k in range(size + 1):       # k pieces in front, the rest behind
                for order in set(itertools.permutations(range(size))):
                    pieces = [out[i] for i in order]
                    cand = {"op": "charade", "parts": pieces[:k] + [ana] + pieces[k:]}
                    if _eval_swapped(node, parent, cand, ctx):
                        good[json.dumps(cand, sort_keys=True)] = cand
                        # two lone C's (caught, cold) pulled alike are one reading, not two
                        key = (k, "".join(str(p.get("gives") or p.get("words") or "").upper() for p in pieces))
                        same.setdefault(key, cand)
        if good:
            break
    if len(good) == 1:
        return next(iter(good.values()))
    return next(iter(same.values())) if good and len(same) == 1 else None


def r_split_shared_indicator(node, parent, ctx):
    """splitSharedIndicator: two (or more) neighbouring same-kind ops (selection, homophone, deletion)
    under one parent, only one carrying the indicator: one multi-part op with that indicator over all
    their parts, set where the first stood. Kept only when the whole tree still gives the answer."""
    kids = [q for q in node.get("parts") or [] if isinstance(q, dict)]
    out = None
    for op in V._SHARED_OK:
        ns = [q for q in kids if q.get("op") == op and not q.get("unchecked")]
        if len(ns) < 2 or sum(bool(x.get("indicators")) for x in ns) != 1:
            continue
        if len(ns) == 2 and not V._pair_adjacent(ns):
            continue
        if out is not None:
            return None
        carrier = next(x for x in ns if x.get("indicators"))
        notes = list(dict.fromkeys(x["note"] for x in ns if x.get("note")))
        merged = {k: v for k, v in carrier.items() if k not in ("parts", "gives", "note")}
        merged["parts"] = [copy.deepcopy(p) for x in ns for p in x["parts"]]
        if op in ("homophone", "deletion"):
            # the validator takes neither a multi-part homophone, a joined-spelling leaf nor a multi-cut
            # deletion (wrong number of parts / leaf that is no word): left for the model
            return None
        if notes:
            merged["note"] = " ".join(notes)
        out = (ns, merged)
    if out is None:
        return None
    ns, merged = out
    new = copy.deepcopy(node)
    at = [id(q) for q in node["parts"]].index(id(ns[0]))
    new["parts"] = [copy.deepcopy(q) for q in node["parts"] if not any(q is x for x in ns)]
    new["parts"].insert(at, merged)
    return new if _eval_swapped(node, parent, new, ctx) else None


def r_halved_deletion(node, parent, ctx):
    """halvedAsDeletion: del<half of>(WORD, HALF) where the cut is exactly one end half of the word: it
    becomes first/last<same indicator>(WORD), the half that is kept. Kept only when the tree still
    gives the answer (_eval_swapped)."""
    parts = node.get("parts") or []
    inds = node.get("indicators") or []
    if node.get("op") != "deletion" or node.get("unchecked") or len(parts) != 2 or len(inds) != 1:
        return None
    text = str(inds[0].get("text") or "")
    if not V._HALVING.search(text) or V._NOT_A_HALVING.search(text):
        return None
    whole, gone = parts
    if not leaf(whole) or "op" in gone or gone.get("words") or not gone.get("gives"):
        return None
    full = W.letters(whole.get("gives") or whole.get("words") or "")
    cut = W.letters(gone["gives"])
    if not full or len(full) % 2 or len(cut) != len(full) // 2:
        return None
    ops = [op for op, ok in (("first", full.endswith(cut)), ("last", full.startswith(cut))) if ok]
    if len(ops) != 1:
        return None
    new = {"op": ops[0], "indicators": copy.deepcopy(inds), "parts": [copy.deepcopy(whole)]}
    return new if _eval_swapped(node, parent, new, ctx) else None



def r_reversal_split(node, parent, ctx):
    """reversalSplit: a multi-part reversal whose indicator sits between its pieces in the clue reverses
    only the piece beside it. One piece takes the reversal (its own indicator), the others join it in a
    charade, in whichever order gives the answer. Kept only when exactly one tree does."""
    if node.get("op") != "reversal" or node.get("unchecked") or not ctx.get("answer"):
        return None
    parts = node.get("parts") or []
    inner = None            # the reversal sits over one charade/container: its pieces are the ones
    if len(parts) == 1 and isinstance(parts[0], dict) and parts[0].get("op") in ("charade", "container"):
        inner = parts[0]
        parts = inner.get("parts") or []
    if len(parts) < 2 or len(parts) > 4 or any(not isinstance(p, dict) or p.get("unchecked") for p in parts):
        return None
    if inner is not None and (inner.get("unchecked") or inner.get("indicators") and inner["op"] == "charade"):
        return None
    base_op = inner["op"] if inner is not None else "charade"
    orders = [tuple(range(len(parts)))] if base_op == "container" else list(itertools.permutations(range(len(parts))))
    good = {}
    for i in range(len(parts)):
        rev = {key: v for key, v in node.items() if key not in ("parts", "unchecked", "gives")}
        rev["parts"] = [copy.deepcopy(parts[i])]
        rest = [copy.deepcopy(p) for j, p in enumerate(parts) if j != i]
        for order in orders:
            seq = [rev if k == i else rest[k - (k > i)] for k in order]
            cand = {key: v for key, v in (inner or {}).items() if key not in ("parts", "gives")}
            cand.update({"op": base_op, "parts": copy.deepcopy(seq)})
            if _eval_swapped(node, parent, cand, ctx):
                good[json.dumps(cand, sort_keys=True)] = cand
    return next(iter(good.values())) if len(good) == 1 else None



def r_moved_letter(node, parent, ctx):
    """movedLetter: a charade/container holds del(WORD, X) and a sibling leaf that gives X again: the
    letter was taken out and put back, which is one move<ind>(WORD, X) (Paul: delete-then-re-add is a
    move error). The deletion and the sibling leaf become one move; the indicators of the deletion and
    of a container parent go on it. Kept only when the whole tree still gives the answer."""
    if node.get("op") not in ("charade", "container") or node.get("unchecked") or not ctx.get("answer"):
        return None
    if node["op"] == "charade" and node.get("indicators"):
        return None
    kids = node.get("parts") or []
    found = []
    for d in kids:
        ps = d.get("parts") or []
        if d.get("op") != "deletion" or d.get("unchecked") or len(ps) != 2 or "op" in ps[1] or "op" in ps[0]:
            continue
        cut = W.letters(ps[1].get("gives"))
        if not cut or len(d.get("indicators") or []) > 1:
            continue
        for k in kids:
            if k is not d and "op" not in k and not k.get("unchecked") and W.letters(k.get("gives")) == cut:
                found.append((d, k))
    if len(found) != 1:
        return None
    d, k = found[0]
    inds = copy.deepcopy((d.get("indicators") or []) + (node.get("indicators") or []))
    if not inds:
        return None
    inds.sort(key=lambda i: i.get("at") if isinstance(i.get("at"), int) else 10 ** 6)
    mv = {"op": "move", "indicators": inds, "parts": [copy.deepcopy(d["parts"][0]), copy.deepcopy(k)]}
    rest = [mv if p is d else copy.deepcopy(p) for p in kids if p is not k]
    if len(rest) == 1:
        new = mv
    else:
        new = {key: copy.deepcopy(v) for key, v in node.items() if key not in ("parts", "gives")}
        new["indicators"] = []
        new["parts"] = rest
        if node["op"] == "container":
            new["indicators"] = copy.deepcopy(node.get("indicators") or [])
            mv["indicators"] = copy.deepcopy(d.get("indicators") or [])
            if not mv["indicators"]:
                return None
        else:
            new.pop("indicators", None)
    return new if _eval_swapped(node, parent, new, ctx) else None


_CUT_PUNCT = " ,;:.!?—–-\"“”‘’()[]{}"


_CUT_LINKS = frozenset("a an the of its his her their and or but after before by with in on for to from is are at as "
                       "not given less minus without being gets get has have having".split())


def _cut_note_fulls(note, g):
    """{whole: (kind, gone)}: capitalised words of the note one letter longer than g that g is the head
    ("tail" cut) or tail ("head" cut) of."""
    out = {}
    for m in re.findall(r"\b[A-Z]{3,}\b", note):
        if len(m) != len(g) + 1:
            continue
        if m.lower().startswith(g.lower()):
            out[m.upper()] = ("tail", m[-1].upper())
        elif m.lower().endswith(g.lower()):
            out[m.upper()] = ("head", m[0].upper())
    return out


def r_cut_note_leaf(node, parent, ctx):
    """cutNoteLeaf: a leaf holds a cut word's clue words AND the cut's indicator, and gives the word one
    letter short, its note naming the whole (BROKEN without its first letter). Becomes
    del<ind>([words]WHOLE, cut): the cut is either the end letter the indicator names (positional) or a
    word of the leaf that abbreviates it (LUNCH ignoring large: del<ignoring>(LUNCH, L)). Kept only when
    the note names exactly one whole, exactly one split reads, the indicator is a deletion word, and the
    tree still gives the answer."""
    if not leaf(node) or node.get("unchecked") or not node.get("words") or not node.get("gives") \
            or not ctx.get("answer") or parent is None or parent.get("op") in ("deletion", "move", "substitution"):
        return None
    if not V.cut_note_leaf(node):
        return None
    note = str(node.get("note") or "")
    g = W.letters(node["gives"]).upper()
    fulls = _cut_note_fulls(note, g)
    if len(fulls) != 1:
        return None
    whole, (kind, gone) = next(iter(fulls.items()))
    words = node["words"]
    toks = _tokens(words)
    n = len(toks)
    if n < 2:
        return None
    text = lambda a, b: words[toks[a][0]:toks[b - 1][1]]
    base = node.get("at")
    at = lambda i: None if base is None else base + i
    delop = {"op": "deletion"}
    cands = {}

    def build(src, ind, letter):
        s_txt, i_txt = text(*src), text(*ind)
        if not W.letters(s_txt) or not W.letters(i_txt):
            return
        edge = (toks[src[0]][2], toks[src[1] - 1][2])
        near = toks[src[1] - 1][2] if src[1] == ind[0] else toks[src[0]][2]    # the source word beside the indicator
        if src[1] - src[0] > 3 or (near.endswith("ly") and len(near) >= 7):
            return          # a long source is a leaf that swallowed link words; "slightly | short" is one indicator
        if re.search(r"(?:ed|ing)$", near) or near in ("off", "out", "away", "up", "down", "back", "over"):
            return          # a verb or particle there is likely the front of a wider indicator (forced | to leave)
        if any(t in _CUT_LINKS for t in edge) or V.DELETION_LEAF_WORD.search(s_txt) \
                or any(TAIL.search(t) or HEAD.search(t) for t in edge if t not in whole.lower()) and letter is None:
            return
        itok = {"text": i_txt, "note": f"'{i_txt}' cuts a letter off"}
        if base is not None:
            itok["at"] = at(toks[ind[0]][0])
        if letter is None:
            if not ((kind == "tail" and TAIL.search(i_txt) and not HEAD.search(i_txt)) or
                    (kind == "head" and HEAD.search(i_txt) and not TAIL.search(i_txt))):
                return
            if not (_lexicon_owns(itok, delop) or _mine_for_op(itok, {"op": "last" if kind == "tail" else "first"})):
                return
            cut = {"gives": gone}
        else:
            l_txt = text(*letter)
            if letter[1] - letter[0] != 1 or not (W.letters(l_txt).upper() == gone or
                                                  annotation.is_abbreviation({"words": l_txt, "gives": gone})):
                return
            if not _lexicon_owns(itok, delop):
                return
            cut = {"words": l_txt, "gives": gone}
            if base is not None:
                cut["at"] = at(toks[letter[0]][0])
        held = {"words": s_txt, "gives": whole,
                "note": f"{whole} is what '{s_txt}' stands for"}
        if W.letters(s_txt).upper() == whole:
            held["note"] = f"{whole} is the word '{s_txt}' itself"
        if base is not None:
            held["at"] = at(toks[src[0]][0])
        new = {"op": "deletion", "indicators": [itok], "parts": [held, cut]}
        if _eval_swapped(node, parent, new, ctx):
            cands[json.dumps(new, sort_keys=True)] = new

    for ia in range(n):                      # positional: indicator is one whole edge
        for ib in range(ia + 1, n + 1):
            if (ia == 0) != (ib == n) and ib - ia <= 3:
                build((ib, n) if ia == 0 else (0, ia), (ia, ib), None)
    for i1 in range(n):                      # source | indicator | letter, and letter | indicator | source
        for i2 in range(i1 + 1, n):
            if i2 - i1 > 3:
                break
            build((0, i1), (i1, i2), (i2, n)) if i1 > 0 and i2 == n - 1 else None
            build((i2, n), (i1, i2), (0, i1)) if i1 == 1 and i2 < n else None
    return next(iter(cands.values())) if len(cands) == 1 else None


def r_del_one_piece(node, parent, ctx):
    """delOnePiece: del(charade(a, b, ...), X) of plain leaves where X lies inside exactly one piece (MELODY + RAM
    less Y): the deletion moves onto that piece, charade(del(MELODY, Y), RAM), indicators with it. Kept only
    when the tree still gives the answer and the validator's rule no longer fires."""
    parts = node.get("parts") or []
    if V.del_one_piece(node) != 1 or not ctx.get("answer") or any(not isinstance(p, dict) for p in parts):
        return None
    comps = parts[0].get("parts") or []
    cut = W.letters(parts[1]["gives"])
    hold = [k for k, c in enumerate(comps) if cut in W.letters(c.get("gives") or c.get("words"))]
    if len(hold) != 1:
        return None
    k = hold[0]
    inner = {x: y for x, y in node.items() if x not in ("parts", "gives")}
    inner["parts"] = [copy.deepcopy(comps[k]), copy.deepcopy(parts[1])]
    pieces = copy.deepcopy(comps)
    pieces[k] = inner
    new = {x: y for x, y in parts[0].items() if x not in ("parts", "gives")}
    new["op"], new["parts"] = "charade", pieces
    if node.get("gives") is not None:
        new["gives"] = node["gives"]
    if not _eval_swapped(node, parent, new, ctx) or V.del_one_piece(new):
        return None
    return new


def r_nested_same_op(node, parent, ctx):
    """nestedSameOp: del(del(X, a), b) where only one of the two deletions carries an indicator: one indicator is
    one op, and a deletion takes several cuts, so it becomes del<ind>(X, a, b). Only deletions (a container takes
    two parts, a reversal one, so those have no unique flat form). Kept only when the tree still gives the answer
    and the validator's rule no longer fires."""
    parts = node.get("parts") or []
    if node.get("op") != "deletion" or node.get("unchecked") or not ctx.get("answer") or len(parts) < 2 \
            or any(not isinstance(p, dict) for p in parts):
        return None
    inner = parts[0]
    if inner.get("op") != "deletion" or inner.get("unchecked") or bool(inner.get("indicators")) == bool(node.get("indicators")):
        return None
    if any(p.get("op") for p in parts[1:]) or any(p.get("op") for p in (inner.get("parts") or [])[1:]):
        return None
    new = {x: copy.deepcopy(y) for x, y in node.items() if x not in ("parts", "gives", "indicators")}
    inds = node.get("indicators") or inner.get("indicators")
    new["indicators"] = copy.deepcopy(inds)
    new["parts"] = copy.deepcopy(inner["parts"]) + copy.deepcopy(parts[1:])
    if node.get("gives") is not None:
        new["gives"] = node["gives"]
    if len(new["parts"]) > 9 or not _eval_swapped(node, parent, new, ctx) or V.nested_same_op(new) > V.nested_same_op(node) - 1:
        return None
    return new


def r_del_wraps_charade(node, parent, ctx):
    """delWrapsCharade: del<ind>(charade(a, b, ...), X) of plain leaves whose indicator stands in the clue between
    two pieces: it cuts the piece touching it (PUSS 'Manx' cat: rev(RATS + RE + del<Manx>(PUSS, S))). The piece is
    the one holding X whose clue words sit right against the indicator (only blanks or punctuation between); kept
    only when exactly one such piece exists, the whole tree still gives the answer and the rule no longer fires."""
    clue = ctx.get("clue") or ""
    if V.del_wraps_charade(node, clue) != 1 or node.get("op") != "deletion" or not ctx.get("answer"):
        return None
    parts = node["parts"]
    comps = parts[0]["parts"]
    cut = W.letters(parts[1]["gives"])
    ind = node["indicators"][0]
    low = clue.lower()
    t = str(ind["text"])
    a0 = ind["at"] if isinstance(ind.get("at"), int) else low.find(t.lower())
    b0 = a0 + len(t)
    near = []
    for k, c in enumerate(comps):
        g = W.letters(c.get("gives") or c.get("words"))
        if not (len(g) > len(cut) and cut in g):
            continue
        sp = V._subtree_spans(c, clue, low)
        if not sp:
            continue
        lo, hi = min(a for a, _ in sp), max(b for _, b in sp)
        gap = clue[hi:a0] if hi <= a0 else clue[b0:lo] if lo >= b0 else None
        if gap is not None and not W.letters(gap):
            near.append(k)
    if len(near) != 1:
        return None
    k = near[0]
    inner = {x: y for x, y in node.items() if x not in ("parts", "gives")}
    inner["parts"] = [copy.deepcopy(comps[k]), copy.deepcopy(parts[1])]
    pieces = copy.deepcopy(comps)
    pieces[k] = inner
    new = {x: y for x, y in parts[0].items() if x not in ("parts", "gives")}
    new["op"], new["parts"] = "charade", pieces
    if node.get("gives") is not None:
        new["gives"] = node["gives"]
    if not _eval_swapped(node, parent, new, ctx) or V.del_wraps_charade(new, clue):
        return None
    return new


def _single_pick(p):
    """(op, n, indicator text) of a selection over one plain leaf, else None."""
    if not isinstance(p, dict) or p.get("op") not in W.SELECT or p.get("unchecked") or "gives" in p:
        return None
    sub = p.get("parts") or []
    if len(sub) != 1 or "words" not in sub[0] or "op" in sub[0] or sub[0].get("unchecked") or not isinstance(sub[0].get("at"), int):
        return None
    return p["op"], p.get("n"), tuple(str(i.get("text")).lower() for i in p.get("indicators") or [])


def r_repeated_selection(node, parent, ctx):
    """repeatedSelection: charade(first<ind>([a]), first<ind>([b]), ...) of the same pick, each over one word
    (an acrostic written word by word) is one pick, first<ind>([a b ...]) over the words together. Only runs of
    neighbouring parts whose words follow each other in the clue with only blanks between; kept only when the
    tree still gives the answer and the rule counts fewer."""
    clue = ctx.get("clue") or ""
    parts = node.get("parts") or []
    if node.get("op") != "charade" or node.get("unchecked") or not ctx.get("answer") or not V.repeated_selections(node):
        return None
    out, i, merged = [], 0, False
    while i < len(parts):
        key = _single_pick(parts[i])
        j = i + 1
        while key and j < len(parts) and _single_pick(parts[j]) == key:
            a, b = parts[j - 1]["parts"][0], parts[j]["parts"][0]
            if W.letters(clue[a["at"] + len(a["words"]):b["at"]]) or b["at"] < a["at"]:
                break
            j += 1
        if key and j - i > 1:
            first, last = parts[i]["parts"][0], parts[j - 1]["parts"][0]
            new = copy.deepcopy(parts[i])
            new["parts"] = [{"words": clue[first["at"]:last["at"] + len(last["words"])], "at": first["at"]}]
            out.append(new)
            merged = True
        else:
            out += parts[i:j]
        i = j
    if not merged:
        return None
    new = {x: copy.deepcopy(y) for x, y in node.items() if x not in ("parts", "gives")}
    new["parts"] = out
    if len(out) == 1:
        new = out[0]
    if node.get("gives") is not None and "op" in new and new["op"] == "charade":
        new["gives"] = node["gives"]
    if not _eval_swapped(node, parent, new, ctx) or V.repeated_selections(new) >= V.repeated_selections(node):
        return None
    return new


RULE_REPAIRS = {"repeatedSelection": r_repeated_selection, "delWrapsCharade": r_del_wraps_charade,"nestedSameOp": r_nested_same_op, "delOnePiece": r_del_one_piece,"cutNoteLeaf": r_cut_note_leaf, "movedLetter": r_moved_letter, "halvedAsDeletion": r_halved_deletion, "reversalSplit": r_reversal_split,"anaLoneEdge": r_ana_lone_edge,"splitSharedIndicator": r_split_shared_indicator,
                "scrambledLeaf": r_scrambled_swap,"anaCharade": lambda n, p, c: r_ana_charade(n, p, c) or r_ana_pull(n, p, c) or r_ana_edge(n, p, c), "anaSelectEdge": r_ana_select_edge,
                "linkInLeaf": r_link_in_leaf, "indLeafOverlap": r_ind_leaf_overlap, "swappedPair": r_swapped_pair, "halfLeaf": r_half_leaf, "arity_other": lambda n, p, c: r_arity_other(n, p, c) or r_arity_ins(n, p, c),
                "unchecked_step": r_literal_fodder, "unchecked_leaf": r_removed_leaf, "arity_ins": r_arity_ins, "anaSynonym": r_ana_synonym_charade, "anagramOfContainer": r_ana_of_container,
                "containerInside": r_container_inside, "nestedContainer": r_nested_container,
                "wrongRole": r_wrong_role, "delSelection": r_del_selection,
                "sharedIndicator": lambda n, p, c: r_shared_indicator(n, p, c) or r_shared_charade(n, p, c), "poolGap": lambda n, p, c: r_pool_gap(n, p, c) or r_pool_eject(n, p, c),
                "misplacedIndicator": r_misplaced_indicator,
                "deletionInside": r_deletion_inside, "deletionScope": r_deletion_inside, "deletionScopeAnswer": r_deletion_inside,
                "unindicatedBare": lambda n, p, c: r_unindicated_move(n, p, c) or r_unindicated_spare(n, p, c),
                "del_single": r_del_single, "indInLeaf": r_ind_in_leaf, "ind_in_leaf": r_ind_in_leaf,
                "selectWordInLeaf": r_own_ind_leaf, "ownIndInLeaf": r_own_ind_leaf, "truncInLeaf": r_trunc_leaf}


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
                   "ind_in_leaf": lambda wp, full, clue: V.ind_in_leaf(wp, clue)}


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
    a = ap.parse_args()
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
