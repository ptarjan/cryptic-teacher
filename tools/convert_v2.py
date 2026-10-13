#!/usr/bin/env python3
"""Today's annotations as format v2: a wordplay tree plus the facts it can't derive.

`convert(ann, entry, puzzle)` turns one stored annotation (type, answer,
blocks, indicators, assembly, ...) into a v2 one (definitions, wordplay,
explanation, features, spelling, andLit, ...), and `compare` lists by kind
what `annotation.view()` of the result says differently from the stored
fields. Nothing is lost: every block becomes a leaf with its words, letters
and note, every indicator hangs on an op of the type its `for` names, and
where the blocks can't be rebuilt step by step (a deletion of scattered
letters, a selection from a synonym) the step stays an `"unchecked": true`
node carrying the letters as filed: today's level of checking, and a form
the expression can't write, so new annotations can't add one.

The tree is found by a search over the blocks in their filed order:
charade, reversal, container (stored outer first, whatever order the blocks
had), anagram and deletion, using the kinds the stored `type` names.

`puzzle_names(puzzle)` gives the facts a puzzle's `name` holds beyond
series.display_name() (`prize`, `title`, `label`).

    python3 tools/convert_v2.py puzzles/ --report design/converter_dryrun.txt

reads every puzzle and writes nothing but the report.
"""
import argparse
import collections
import copy
import functools
import json
import os
import re
import sys
import unicodedata

import annotation
import wordplay as W

L = W.letters
# Stored type -> the op that does it, for a type no block names.
TYPE_OP = {"anagram": "anagram", "reversal": "reversal", "container": "container",
           "deletion": "deletion", "hidden_word": "hidden", "homophone": "homophone",
           "spoonerism": "spoonerism", "substitution": "substitution", "cycling": "cycling",
           "letter_selection": "first", "charade": "charade", "cryptic_definition": "cryptic"}
SEARCH = ("charade", "reversal", "container", "anagram", "deletion")
# Diffs accepted by design (the brief's decisions, and derived fields recomputed).
ACCEPTED = {"container outer first", "type order", "indicator for filled", "linkWords recomputed",
            "assembly recomputed", "gives before the op", "soundsLike as letters",
            "double definition meaning kept apart", "block order"}


class Unconvertible(Exception):
    """A stored annotation that contradicts its own entry; `kind` names how."""

    def __init__(self, kind, detail=""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind


def _bag(s):
    return "".join(sorted(s))


# ---------- blocks -> units ----------

def _leaf(block, gives=None, force=False):
    words = block.get("clueFragment")
    n = {"words": words} if words else {}
    if gives is not None and (force or not words or L(words) != gives):
        n["gives"] = gives
    if block.get("note"):
        n["note"] = block["note"]
    return n


def _unit(block, sel_inds, hidden, homophone=True):
    """(node, letters, types) for one block: a leaf, or a selection, homophone
    or hidden word of one leaf."""
    words, g = block.get("clueFragment"), L(block.get("gives"))
    sel, snd = block.get("select"), block.get("soundsLike")
    if not g:
        return {**_leaf(block), "gives": "", "unchecked": True}, "", set()
    if snd is not None and sel is None and homophone:
        return ({"op": "homophone", "spelt": g, "parts": [_leaf(block, L(snd), True)]}, g, {"homophone"})
    if sel is not None and snd is None and words:
        op = "nth" if isinstance(sel, int) else sel
        if op in W.SELECT:
            trims = [None]
            for t in sel_inds:
                if t in words:
                    trims.append(L(words.replace(t, " ", 1)))
            if re.search(r"['’]s\b", words):
                trims.append(L(re.sub(r"['’]s\b", "", words)))
                trims += [L(re.sub(r"['’]s\b", "", words.replace(t, " ", 1))) for t in sel_inds if t in words]
            for gv in trims:
                node = {"op": op, "parts": [_leaf(block, gv, gv is not None)]}
                if op == "nth":
                    node["n"] = sel
                try:
                    if g in W.values(node):
                        return node, g, {"letter_selection"}
                except W.WordplayError:
                    pass
    if sel is not None or snd is not None:
        leaf = {**_leaf(block, g, True), "unchecked": True}
        if sel is not None:
            leaf["select"] = sel
        if snd is not None:
            leaf["soundsLike"] = snd
        if sel is not None and snd is None:
            # A selection the clue words don't give (from a synonym, or
            # `prime`): an unchecked selection round the leaf as filed.
            op = "nth" if isinstance(sel, int) else sel if sel in W.SELECT else "first"
            node = {"op": op, "unchecked": True, "gives": g, "parts": [leaf]}
            if op == "nth":
                node["n"] = sel
            return node, g, {"letter_selection"}
        return leaf, g, {"homophone"} if snd is not None else set()
    if hidden and words:
        text = L(words)
        if g != text and g in text:
            return {"op": "hidden", "parts": [_leaf(block, g, True)]}, g, {"hidden_word"}
        if g != text and g[::-1] in text and len(g) > 1:
            return ({"op": "hidden", "parts": [_leaf(block, g[::-1], True)]}, g[::-1],
                    {"hidden_word", "+pre-op"})
    return _leaf(block, g), g, set()


# ---------- the search ----------

def _charade(nodes):
    return nodes[0] if len(nodes) == 1 else {"op": "charade", "parts": list(nodes)}


def build(units, vals, want, kinds):
    """{frozenset(types used): (cost, tree)} building `want` from `units`
    (fixed letters `vals`) in order, with the ops in `kinds`."""
    n = len(vals)
    starts = [0]
    for v in vals:
        starts.append(starts[-1] + len(v))
    size = lambda i, j: starts[j] - starts[i]
    cat = lambda i, j: "".join(vals[i:j])
    dele = "deletion" in kinds

    def add(found, used, cost, tree):
        if used not in found or cost < found[used][0]:
            found[used] = (cost, tree)

    @functools.lru_cache(maxsize=None)
    def best(i, j, t, may_rev=True):
        found = {}
        # Every run of blocks gives something: a deletion never leaves nothing.
        if not t or len(t) > size(i, j) or (not dele and len(t) != size(i, j)):
            return found
        if not dele and _bag(cat(i, j)) != _bag(t):
            return found
        if j - i == 1 and vals[i] == t:
            add(found, frozenset(), 0, units[i])
        if cat(i, j) == t and j - i > 1:
            add(found, frozenset({"charade"}), 0.1, _charade(units[i:j]))
        for k in range(i + 1, j):
            ps = range(len(t) + 1) if dele else [size(i, k)]
            for p in ps:
                if p > size(i, k) or len(t) - p > size(k, j):
                    continue
                a, b = best(i, k, t[:p], may_rev), best(k, j, t[p:], may_rev)
                for ua, (ca, ta) in a.items():
                    for ub, (cb, tb) in b.items():
                        parts = (ta["parts"] if ta.get("op") == "charade" and not ta.get("_closed") else [ta]) + \
                                (tb["parts"] if tb.get("op") == "charade" and not tb.get("_closed") else [tb])
                        add(found, ua | ub | {"charade"}, ca + cb + 0.1, {"op": "charade", "parts": parts})
        if "reversal" in kinds and may_rev and t != t[::-1]:
            for u, (c, sub) in best(i, j, t[::-1], False).items():
                add(found, u | {"reversal"}, c + 1, {"op": "reversal", "parts": [_close(sub)]})
        if "anagram" in kinds:
            fod = cat(i, j)
            if _bag(fod) == _bag(t) and fod != t:
                add(found, frozenset({"anagram"}), 1 + 0.01 * (j - i),
                    {"op": "anagram", "parts": [_charade(units[i:j])]})
            elif dele and len(fod) > len(t):
                d = len(fod) - len(t)
                # A deletion inside the fodder: a trailing block, or letters in a row.
                f, r = cat(i, j - 1), vals[j - 1]
                if j - i > 1 and r and any(f.startswith(r, k) and _bag(f[:k] + f[k + len(r):]) == _bag(t)
                                           and f[:k] + f[k + len(r):] != t for k in range(len(f))):
                    add(found, frozenset({"anagram", "deletion"}), 2.5,
                        {"op": "anagram", "parts": [{"op": "deletion", "parts": [
                            _close(_charade(units[i:j - 1])), units[j - 1]]}]})
                for p in range(len(fod) - d + 1):
                    rest = fod[:p] + fod[p + d:]
                    if _bag(rest) == _bag(t) and rest != t:
                        add(found, frozenset({"anagram", "deletion"}), 2 + 0.01 * d,
                            {"op": "anagram", "parts": [{"op": "deletion", "parts": [
                                _charade(units[i:j]), {"gives": fod[p:p + d]}]}]})
                        break
        if "container" in kinds:
            for k in range(i + 1, j):
                for (oi, oj), (ii, ij), extra in (((i, k), (k, j), 0), ((k, j), (i, k), 0.5)):
                    ns = range(1, size(ii, ij) + 1) if dele else [size(ii, ij)]
                    for m in ns:
                        for at in range(1, len(t) - m):
                            outer = best(oi, oj, t[:at] + t[at + m:], may_rev)
                            if not outer:
                                continue
                            inner = best(ii, ij, t[at:at + m], may_rev)
                            for uo, (co, to) in outer.items():
                                for ui, (ci, ti) in inner.items():
                                    tree = {"op": "container", "parts": [_close(to), _close(ti)]}
                                    if extra:
                                        tree["_swapped"] = True
                                    add(found, uo | ui | {"container"}, co + ci + 1 + extra, tree)
        if dele:
            fod = cat(i, j)
            d = len(fod) - len(t)
            if d > 0:
                # Letters in a row taken out of these blocks as filed: at an
                # end (beheaded, mostly), or one or two from inside.
                for p in sorted(range(len(fod) - d + 1), key=lambda p: (p not in (0, len(fod) - d), p)):
                    if p not in (0, len(fod) - d) and d > 2:
                        continue
                    if fod[:p] + fod[p + d:] == t:
                        add(found, frozenset({"deletion"} | ({"charade"} if j - i > 1 else set())),
                            1.2, {"op": "deletion", "parts": [_charade(units[i:j]), {"gives": fod[p:p + d]}]})
                        break
            # A following (or leading) run of blocks taken out.
            for k in range(i + 1, j):
                for (fi, fj), (ri, rj), extra in (((i, k), (k, j), 0), ((k, j), (i, k), 0.5)):
                    r = cat(ri, rj)
                    for p in range(len(t) + 1):
                        f = t[:p] + r + t[p:]
                        if len(f) > size(fi, fj):
                            break
                        for u, (c, sub) in best(fi, fj, f, may_rev).items():
                            tree = {"op": "deletion", "parts": [_close(sub), _charade(units[ri:rj])]}
                            if extra:
                                tree["_swapped"] = True
                            add(found, u | {"deletion"}, c + 1 + extra, tree)
        return found

    if not vals or n > 9:
        return {}
    try:
        return best(0, n, want)
    finally:
        best.cache_clear()


def _close(node):
    """A charade made a part of something else is not flattened into its parent."""
    if node.get("op") == "charade":
        return {**node, "_closed": True}
    return node


def _clean(node):
    """Drop the search's private marks; note a swapped container or deletion."""
    swapped = bool(node.pop("_swapped", False))
    node.pop("_closed", None)
    for p in node.get("parts") or []:
        swapped |= _clean(p)
    return swapped


# ---------- one annotation ----------

def _types(ann):
    return [t for t in ann.get("type") or [] if isinstance(t, str)]


def _walk(node):
    yield node
    for p in node.get("parts") or []:
        yield from _walk(p)


def convert(ann, entry, puzzle=None):
    """(v2 annotation, notes) for a stored one. `notes` names the accepted
    normalisations the conversion made; raises Unconvertible where the
    stored annotation contradicts its entry."""
    ann = copy.deepcopy(ann)
    notes = set()
    types = _types(ann)
    out = {}
    defs = copy.deepcopy(ann.get("definitions"))
    display = annotation.display_answer(entry, puzzle) if entry.get("solution") else None
    stored = ann.get("answer") or ""
    alt = entry.get("alteration")
    if display is not None and stored != display:
        fold = lambda s: unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().replace("'", "").replace("’", "")
        if L(stored) != L(display) and not (isinstance(alt, dict) and alt.get("from")):
            raise Unconvertible("answer letters differ from the solution", f"{stored} vs {display}")
        if fold(stored).upper() == fold(display).upper() or (L(stored) == L(display) and re.search(r"[’'À-ÿ!?.&]", stored)
                                                             and re.sub(r"[^A-Z ]", "", fold(stored).upper()).split() == re.sub(r"[^A-Z ]", "", fold(display).upper()).replace("-", " ").split()):
            out["spelling"] = stored
        elif L(stored) == L(display) and not _enumerated(entry, puzzle):
            # No enumeration to space it by (a Listener's): the spacing is a fact.
            out["spelling"] = stored
        elif L(stored) == L(display):
            raise Unconvertible("answer contradicts enumeration", f"{stored} vs {display}")
        else:
            out["spelling"] = stored
    if defs is not None:
        out["definitions"] = defs
    blocks = [b for b in ann.get("blocks") or [] if isinstance(b, dict)]
    inds = [i for i in ann.get("indicators") or [] if isinstance(i, dict)]
    tset = set(types)
    if "double_definition" in tset and not any(b.get("gives") for b in blocks) and defs and len(defs) > 1:
        tree = None
        by_text = collections.defaultdict(list)
        for b in blocks:
            by_text[b.get("clueFragment")].append(b)
        for d in defs:
            b = by_text.get(d["text"]) and by_text[d["text"]].pop(0)
            if b and b.get("note") and b["note"] != d.get("note"):
                if d.get("note"):
                    notes.add("double definition meaning kept apart")
                d["meaning"] = b["note"]
            elif b and not b.get("note") and d.get("note"):
                d["meaning"] = ""
    elif "cryptic_definition" in tset and not any(b.get("gives") for b in blocks):
        tree = {"op": "cryptic", "parts": [_leaf(b) for b in blocks]} if blocks else None
    else:
        tree = _tree(blocks, inds, tset, annotation.wordplay_letters(ann, entry), ann, notes)
    if tree is not None:
        _attach(tree, inds, tset, annotation.wordplay_letters(ann, entry))
        out["wordplay"] = tree
    elif inds:
        raise Unconvertible("indicators with no wordplay")
    for key in ("explanation", "features", "definedByPreamble", "hiddenLetter"):
        if key in ann:
            out[key] = ann[key]
    if "and_lit" in tset:
        out["andLit"] = True
    order = ("definitions", "definedByPreamble", "wordplay", "spelling", "andLit", "hiddenLetter",
             "explanation", "features")
    return {k: out[k] for k in order if k in out}, notes


# Series whose printed enumerations count letters only (Azed marks a word
# break in 23 of 19,690, the Listener in none): their answers' spacing is a
# fact the enumeration can't give, kept as `spelling`.
LETTER_COUNT_ONLY = {"azed", "listener"}


def _enumerated(entry, puzzle):
    """Whether any light of the answer prints an enumeration or separators
    that could space it."""
    if str((puzzle or {}).get("id", "")).rsplit("-", 1)[0] in LETTER_COUNT_ONLY:
        return False
    by_id = {annotation.entry_id(e): e for e in (puzzle or {}).get("entries") or []}
    lights = [by_id.get(i, {}) for i in entry.get("group") or []] or [entry]
    return any((x.get("clue") or {}).get("enumeration") or (x.get("clue") or {}).get("separators") for x in lights)


def _tree(blocks, inds, tset, want, ann, notes):
    sel_inds = [i["text"] for i in inds if i.get("for") == "letter_selection" and i.get("text")]
    units, vals, fixed = [], [], set()
    for b in blocks:
        node, v, ts = _unit(b, sel_inds, "hidden_word" in tset, "homophone" in tset)
        if "+pre-op" in ts:
            notes.add("gives before the op")
            ts = ts - {"+pre-op"}
        units.append(node)
        vals.append(v)
        fixed |= ts
    if not units:
        return None
    # Blocks that give nothing (an indicator filed as a block) ride along unchecked.
    real = [k for k, v in enumerate(vals) if v]
    hl = ann.get("hiddenLetter")
    if isinstance(hl, dict) and hl.get("kind") in ("extra", "omitted"):
        return {"op": "charade", "unchecked": True, "gives": want, "parts": units}
    kinds = tuple(k for k in SEARCH if k in tset)
    found = build(tuple(units[k] for k in real), tuple(vals[k] for k in real), want, kinds) if real else {}
    tree = None
    if found:
        goal = tset & set(SEARCH)
        # The closest to the stored type first; the evaluator has the last word.
        for _, (_, cand) in sorted(found.items(), key=lambda it: (len(goal ^ (it[0] - fixed)), it[1][0])):
            cand = copy.deepcopy(cand)
            swapped = _clean(cand)
            try:
                W.evaluate(copy.deepcopy(cand), want)
            except W.WordplayError:
                continue
            tree = cand
            if swapped:
                notes.add("container outer first")
            break
    if tree is None:
        missing = [t for t in ("deletion", "substitution", "spoonerism", "cycling", "container", "anagram",
                               "reversal", "letter_selection", "homophone", "hidden_word", "charade")
                   if t in tset]
        op = TYPE_OP[missing[0]] if missing else "charade"
        tree = {"op": op, "unchecked": True, "gives": want, "parts": [units[k] for k in real] or list(units)}
        if not real:
            return tree
    if len(real) < len(units):
        # Put the empty blocks back where they were filed: inside a plain
        # charade of the other blocks, or before and after the tree.
        if tree.get("op") == "charade" and [id(x) for x in tree["parts"]] == [id(units[k]) for k in real]:
            tree["parts"] = list(units)
        else:
            before = [units[k] for k in range(real[0])]
            after = [units[k] for k in range(real[0] + 1, len(units)) if k not in real]
            tree = {"op": "charade", "parts": before + [tree] + after}
    return tree


def _attach(tree, inds, tset, want):
    """Hang each indicator on an op of the type its `for` names; one with no
    such op wraps the tree in an unchecked op of that type."""
    for ind in inds:
        t = ind.get("for")
        nodes = [n for n in _walk(tree) if "op" in n and annotation.OP_TYPE.get(n["op"]) == t] if t else []
        if not t:
            ops = [n for n in _walk(tree) if "op" in n]
            free = [n for n in ops if not n.get("indicators")]
            nodes = free or ops
        if not nodes:
            # An unchecked leaf filed with a select or soundsLike takes the
            # indicator of its own kind on an unchecked op round it alone.
            key = {"letter_selection": "select", "homophone": "soundsLike"}.get(t)
            loose = [n for n in _walk(tree) if key and "op" not in n and key in n and not n.get("_wrapped")]
            if loose:
                leaf = loose[0]
                inner = {**leaf, "_wrapped": True}
                op = leaf["select"] if key == "select" and leaf["select"] in W.SELECT else TYPE_OP[t]
                leaf.clear()
                leaf.update({"op": op, "unchecked": True, "gives": inner.get("gives", ""), "parts": [inner]})
                if op == "nth":
                    leaf["n"] = inner["select"]
                nodes = [leaf]
        if not nodes:
            if t not in TYPE_OP:
                raise Unconvertible("indicator for a type with no op", t)
            wrap = {"op": TYPE_OP[t], "unchecked": True, "gives": want, "parts": [copy.copy(tree)]}
            tree.clear()
            tree.update(wrap)
            nodes = [tree]
        node = min(nodes, key=lambda n: len(n.get("indicators") or []))
        new = {"text": ind.get("text")}
        if ind.get("note"):
            new["note"] = ind["note"]
        node.setdefault("indicators", []).append(new)
    for n in _walk(tree):
        n.pop("_wrapped", None)


# ---------- comparing with the stored fields ----------

def _plain(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def compare(old, new, view):
    """Kinds of difference between the stored annotation and view() of the
    converted one: (accepted, failed)."""
    acc, bad = set(), set()
    ot, vt = _types(old), view.get("type") or []
    if set(ot) != set(vt):
        # `type` is derived: a stored list missing a step the tree has, or
        # naming a charade the tree has no join for, is recomputed.
        checked = {annotation.OP_TYPE[n["op"]] for n in _walk(new.get("wordplay") or {})
                   if "op" in n and not n.get("unchecked")}
        for t in sorted(set(ot) - set(vt)):
            if t == "charade":
                acc.add("type recomputed (charade dropped)")
            else:
                bad.add(f"type lost: {t}")
        for t in sorted(set(vt) - set(ot)):
            if t in checked:
                acc.add(f"type recomputed (+{t})")
            else:
                bad.add(f"type added: {t}")
    elif ot != vt:
        acc.add("type order")
    od = old.get("definitions")
    vd = [{k: v for k, v in d.items() if k != "meaning"} for d in view.get("definitions") or []] if od is not None else None
    if od is not None and _plain(od) != _plain(vd):
        bad.add("definitions")
    oi = sorted(_plain({k: v for k, v in i.items() if k != "for"}) for i in old.get("indicators") or [])
    vi = sorted(_plain({k: v for k, v in i.items() if k != "for"}) for i in view.get("indicators") or [])
    if oi != vi:
        bad.add("indicators lost")
    else:
        of = sorted(_plain(i) for i in old.get("indicators") or [] if i.get("for"))
        vf = sorted(_plain(i) for i in view.get("indicators") or []
                    if any(o.get("text") == i["text"] and o.get("for") for o in old.get("indicators") or []))
        if any(not i.get("for") for i in old.get("indicators") or []):
            acc.add("indicator for filled")
        if of != vf:
            bad.add("indicator for changed")
    if (old.get("linkWords") or []) != (view.get("linkWords") or []):
        acc.add("linkWords recomputed")
    ob = [dict(b) for b in old.get("blocks") or []]
    vb = view.get("blocks") or []
    if ob != vb:
        norm = lambda bs: [{**b, **({"soundsLike": L(b["soundsLike"])} if "soundsLike" in b else {}),
                            **({"gives": L(b["gives"])} if "gives" in b else {})} for b in bs]
        nob, nvb = norm(ob), norm(vb)
        if nob == nvb:
            acc.add("soundsLike as letters")
        elif sorted(map(_plain, nob)) == sorted(map(_plain, nvb)):
            acc.add("block order")
        elif [{k: v for k, v in b.items() if k != "gives"} for b in nob] == \
                [{k: v for k, v in b.items() if k != "gives"} for b in nvb]:
            acc.add("gives before the op")
        else:
            bad.add("blocks differ")
    oa, va = old.get("assembly") or {}, view.get("assembly") or {}
    fod = lambda a: [(L(x.get("fodder")) and _bag(L(x.get("fodder"))), L(x.get("gives")))
                     for x in a.get("anagrams") or [] if isinstance(x, dict)]
    pcs = lambda a: [L(p) for p in a.get("pieces") or []] if len(a.get("pieces") or []) > 1 else []
    if pcs(oa) != pcs(va) or fod(oa) != fod(va) or _plain(oa.get("reversals")) != _plain(va.get("reversals")):
        acc.add("assembly recomputed")
    if new.get("definitions") and any("meaning" in d for d in new["definitions"]):
        acc.add("double definition meaning kept apart")
    return acc, bad


def check(ann, entry, puzzle=None):
    """('exact'|'normalised'|'failed', kinds, v2 annotation or None)."""
    try:
        new, notes = convert(ann, entry, puzzle)
    except Unconvertible as e:
        return "failed", {e.kind}, None
    try:
        v = annotation.view(new, entry, puzzle)
    except W.WordplayError as e:
        msg = str(e)
        kind = ("span not in the clue" if "is not in the clue" in msg else
                "tree does not give the answer" if "does not give" in msg else
                "anagram or reversal does nothing" if "no anagram" in msg or "reads the same" in msg else
                "wordplay error")
        return "failed", {kind}, new
    except (KeyError, TypeError, ValueError, StopIteration) as e:
        return "failed", {f"view crashed: {type(e).__name__}"}, new
    acc, bad = compare(ann, new, v)
    if "container outer first" in notes and "block order" in acc:
        acc.discard("block order")
        acc.add("container outer first")
    acc |= notes & ACCEPTED
    if bad:
        return "failed", bad, new
    unchecked = any(n.get("unchecked") for n in _walk(new["wordplay"])) if new.get("wordplay") else False
    if unchecked:
        acc.add("unchecked step kept")
    return ("normalised" if acc else "exact"), acc, new


# ---------- puzzle names ----------

def puzzle_names(puzzle):
    """({prize|title|label: value}, kind) where kind is None when the stored
    name is what display_name derives (with those facts), else
    'name normalised (<series>)'."""
    import series
    name = puzzle.get("name") or ""
    base = {k: puzzle[k] for k in ("prize", "title", "label") if k in puzzle}
    if series.display_name({**puzzle, **base}) == name:
        return base, None
    tries = []
    if name.startswith("Prize crossword"):
        tries.append({"prize": True})
    m = re.search(r": (.+)$", name)
    if m:
        tries.append({"title": m.group(1)})
    m = re.search(r" \(([^()]+)\)$", name)
    if m:
        tries.append({"label": m.group(1)})
    for extra in tries:
        if series.display_name({**puzzle, **extra}) == name:
            return {**base, **extra}, None
    sid = series.parse_id(puzzle["id"])[0]
    return base, f"name normalised ({sid})"


# ---------- dry run ----------

def dry_run(root, report, limit=None):
    counts = collections.Counter()
    kinds = {"normalised": collections.Counter(), "failed": collections.Counter()}
    examples = collections.defaultdict(list)
    names = collections.Counter()
    name_ex = collections.defaultdict(list)
    contradict = []
    seen = 0
    def write(done):
        total = sum(counts.values())
        pct = lambda n: f"{100 * n / total:.1f}%" if total else "-"
        full = counts["exact"] + counts["normalised"] - kinds["normalised"]["unchecked step kept"]
        lines = [f"Format v2 converter dry run over {root}: {seen} puzzles, {total} annotations, read-only"
                 + ("." if done else " (PARTIAL: still running)."), "",
                 f"exact       {counts['exact']:7d}  {pct(counts['exact'])}",
                 f"normalised  {counts['normalised']:7d}  {pct(counts['normalised'])}",
                 f"failed      {counts['failed']:7d}  {pct(counts['failed'])}",
                 f"full tree   {full:7d}  {pct(full)}  (converted with no unchecked step)", "",
                 "Accepted normalisations (an annotation can have several):"]
        for k, n in kinds["normalised"].most_common():
            lines.append(f"  {n:7d}  {k}  e.g. {', '.join(examples[('normalised', k)])}")
        lines += ["", "Failures by kind (an annotation can have several):"]
        for k, n in kinds["failed"].most_common():
            lines.append(f"  {n:7d}  {k}  e.g. {', '.join(examples[('failed', k)])}")
        lines += ["", "Puzzle names display_name does not reproduce (normalised to its form):"]
        for k, n in names.most_common():
            lines.append(f"  {n:7d}  {k}  e.g. {'; '.join(name_ex[k])}")
        lines += ["", f"Answers that contradict their entry ({len(contradict)}; source or annotation bugs, "
                  f"for re-annotation):"]
        lines += [f"  {c}" for c in contradict]
        text = "\n".join(lines) + "\n"
        if report:
            with open(report, "w") as fh:
                fh.write(text)
        return text

    for dp, dn, fn in sorted(os.walk(root)):
        dn.sort()
        for f in sorted(fn):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(dp, f)) as fh:
                    p = json.load(fh)
            except (OSError, ValueError):
                continue
            if not isinstance(p, dict) or "entries" not in p:
                continue
            anns = [e for e in p["entries"] if isinstance(e, dict) and e.get("annotation")]
            if not anns:
                continue
            seen += 1
            if seen % 1000 == 0:
                print(f"{seen} puzzles: {dict(counts)}", file=sys.stderr, flush=True)
                write(False)
            _, nk = puzzle_names(p)
            if nk:
                names[nk] += 1
                if len(name_ex[nk]) < 3:
                    name_ex[nk].append(f"{p['id']}: {p.get('name')!r} -> {__import__('series').display_name(p)!r}")
            for e in anns:
                eid = f"{p['id']}/{e.get('number')}-{e.get('direction')}"
                try:
                    status, ks, _ = check(e["annotation"], e, p)
                except Exception as x:  # a converter bug: count it, keep going
                    status, ks = "failed", {f"converter crashed: {type(x).__name__}"}
                counts[status] += 1
                if status != "exact":
                    for k in ks:
                        kinds[status][k] += 1
                        if len(examples[(status, k)]) < 3:
                            examples[(status, k)].append(eid)
                if status == "failed" and ks & {"answer contradicts enumeration", "answer letters differ from the solution"}:
                    contradict.append(f"{eid} ({e['annotation'].get('answer')!r} vs {e.get('solution')!r}, "
                                      f"{e['clue'].get('enumeration', '')})")
            if limit and seen >= limit:
                break
        if limit and seen >= limit:
            break
    return write(True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root", help="puzzles/ (or a subfolder); read only")
    ap.add_argument("--report", help="write the dry-run report here")
    ap.add_argument("--limit", type=int, help="stop after this many annotated puzzles")
    a = ap.parse_args()
    text = dry_run(a.root, a.report, a.limit)
    print(text if len(text) < 6000 else text[:6000] + "\n…")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
