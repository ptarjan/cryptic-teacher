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
had), anagram and deletion, using the kinds the stored `type` names. A
palindrome wraps what it checks (the whole wordplay, or the part that reads
both ways). Two definitions are a double definition, wordplay or not.
Double-definition and &lit indicators steer the definitions, not the
letters, so they hang on the nearest definition, not on an op.

Policy for stored annotations that contradict themselves (the plan's section
"Bad data", /data/home/.cryptic-teacher/design/puzzle_format_v2.md): nothing
good is thrown away, and one bad clue costs only itself.

  * Salvage, nothing flagged: an answer whose letters match but whose spacing
    contradicts the printed enumeration (the enumeration and separators win,
    the stored spacing is dropped unless it is the enumeration's own and the
    entry has no separators); a preamble step stored as a clue type on a
    double definition (reversal, substitution), which has no letters to check
    and is dropped from the type; a double definition's pun-step indicators,
    which hang on its definitions; an annotation whose entry has no key
    keeps its answer as `spelling`.
  * Redo, that clue only (`migrate_puzzle` drops the entry's `annotation`):
    a double definition with one definition, or with a block that is none of
    its definitions, and every other failure `check` reports. A clue with no
    annotation is what the burn already picks up: the index calls the puzzle
    un-annotated (prereset_plan.backlog) and annotate_check.to_write hands the
    run those clues only, every other annotation as fixed context. No new
    queue: re-adding the annotation is the only thing that clears it.
  * The source key can be wrong, so where the answer's letters differ from the
    entry's solution the clue is redone, not the annotation trusted.

`puzzle_names(puzzle)` gives the facts a puzzle's `name` holds beyond
series.display_name() (`prize`, `title`, `label`).

    python3 tools/convert_v2.py puzzles/ --report design/converter_dryrun.txt

reads every puzzle and writes nothing but the report.

    python3 tools/convert_v2.py puzzles/ --migrate [--commit]

is the step 8 rewrite (`migrate`): every file in place, whole or not at all,
each through `migrate_puzzle` and kept only if puzzle_integrity's write check
finds nothing new on it; the converted puzzles' `wordplay.unchecked` allowance
is written into annotation_backlog.json, and --commit makes the one migration
commit, listing the redone clues by kind. A kill loses nothing: the same
command resumes from the ledger beside puzzles/. tools/test_migrate_v2.sh
proves it on a sample.
"""
import argparse
import collections
import copy
import functools
import itertools
import json
import os
import re
import sys
import unicodedata

import annotation
import enumeration
import wordplay as W

L = W.letters
# Stored type -> the op that does it, for a type no block names.
TYPE_OP = {"anagram": "anagram", "reversal": "reversal", "container": "container",
           "deletion": "deletion", "hidden_word": "hidden", "homophone": "homophone",
           "spoonerism": "spoonerism", "substitution": "substitution", "cycling": "cycling",
           "letter_selection": "first", "charade": "charade", "cryptic_definition": "cryptic",
           "palindrome": "palindrome"}
# Types that steer how the definitions read, not the letters: their
# indicators hang on a definition (annotation.definition_indicator_type).
DEF_TYPES = ("double_definition", "and_lit")
SEARCH = ("charade", "reversal", "container", "anagram", "deletion")
# Diffs accepted by design (the brief's decisions, and derived fields recomputed).
ACCEPTED = {"container outer first", "type order", "indicator for filled", "linkWords recomputed",
            "assembly recomputed", "gives before the op", "soundsLike as letters",
            "double definition meaning kept apart", "block order", "double definition gives the answer",
            "double definition step indicators on the definitions", "answer respaced to the enumeration",
            "setter's slip taken as printed"}


def _slipped(ann):
    """Whether a legacy annotation declares a setter's slip: an assembly
    anagram whose fodder does not hold the letters it gives."""
    return any(isinstance(a, dict) and L(a.get("fodder")) and _bag(L(a.get("fodder"))) != _bag(L(a.get("gives")))
               for a in (ann.get("assembly") or {}).get("anagrams") or [])


class Unconvertible(Exception):
    """A stored annotation that contradicts its own entry; `kind` names how."""

    def __init__(self, kind, detail=""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind


def _is_definition(block, def_texts):
    """Whether a block's words are a definition's (by their letters), give or
    take punctuation or a word or two the one has and the other leaves out."""
    f = L(block.get("clueFragment"))
    return bool(f) and any(f in t or t in f for t in def_texts)


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


def _selected(block, sel, sel_inds):
    """The letters a selection block gives when it files none (the letter
    removed or kept, named only by the selection): what the selection makes
    of its words, the words less an indicator inside them first; '' unless
    that is one reading."""
    words = block["clueFragment"]
    op = "nth" if isinstance(sel, int) else sel
    if op not in W.SELECT:
        return ""
    trims = [L(words.replace(t, " ", 1)) for t in sel_inds if t in words] + [None]
    for gv in trims:
        node = {"op": op, "parts": [_leaf(block, gv, gv is not None)]}
        if op == "nth":
            node["n"] = sel
        try:
            vals = W.values(node)
        except W.WordplayError:
            continue
        if len(vals) == 1 and "" not in vals:
            return next(iter(vals))
    return ""


def _unit(block, sel_inds, hidden, homophone=True, all_inds=()):
    """(node, letters, types) for one block: a leaf, or a selection, homophone
    or hidden word of one leaf."""
    words, g = block.get("clueFragment"), L(block.get("gives"))
    sel, snd = block.get("select"), block.get("soundsLike")
    if not g and sel is not None and snd is None and words:
        g = _selected(block, sel, list(sel_inds) + [t for t in all_inds if t not in sel_inds])
    if not g:
        # (A selection or sound the block gives no letters for stays on the leaf.)
        keep = {k: block[k] for k in ("select", "soundsLike") if block.get(k) is not None}
        return {**_leaf(block), **keep, "gives": "", "unchecked": True}, "", set()
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
            # A reading that gives only g first: "Egyptian leader" with its
            # selector inside reads E or EL, and view() would take EL, so the
            # words less the indicator ("Egyptian": E) win (cyclops-438 9D).
            for unique in (True, False):
                for gv in trims:
                    node = {"op": op, "parts": [_leaf(block, gv, gv is not None)]}
                    if op == "nth":
                        node["n"] = sel
                    try:
                        vals = W.values(node)
                    except W.WordplayError:
                        continue
                    if unique and vals == {g}:
                        return node, g, {"letter_selection"}
                    if not unique and g in vals:
                        # One reading of several ("in opera house" last: E or
                        # NAE): the answer steers it under a checked step, but
                        # nothing does under an unchecked one, so the filed
                        # form rides along for _pin_selections.
                        node["_filed"] = _filed_selection(block, sel, g)
                        return node, g, {"letter_selection"}
    if sel is not None and snd is None:
        # A selection the clue words don't give (from a synonym, or
        # `prime`): an unchecked selection round the leaf as filed.
        return _filed_selection(block, sel, g), g, {"letter_selection"}
    if sel is not None or snd is not None:
        leaf = {**_leaf(block, g, True), "unchecked": True}
        if sel is not None:
            leaf["select"] = sel
        if snd is not None:
            leaf["soundsLike"] = snd
        return leaf, g, {"homophone"} if snd is not None else set()
    if hidden and words:
        text = L(words)
        if g != text and g in text:
            return {"op": "hidden", "parts": [_leaf(block, g, True)]}, g, {"hidden_word"}
        if g != text and g[::-1] in text and len(g) > 1:
            return ({"op": "hidden", "parts": [_leaf(block, g[::-1], True)]}, g[::-1],
                    {"hidden_word", "+pre-op"})
    return _leaf(block, g), g, set()


def _filed_selection(block, sel, g):
    """A selection block as filed: an unchecked selection op giving `g` round
    an unchecked leaf with its words, `g` and `select`."""
    leaf = {**_leaf(block, g, True), "unchecked": True, "select": sel}
    op = "nth" if isinstance(sel, int) else sel if sel in W.SELECT else "first"
    node = {"op": op, "unchecked": True, "gives": g, "parts": [leaf]}
    if op == "nth":
        node["n"] = sel
    return node


def _pin_selections(node, loose=False):
    """A checked selection with several readings under an unchecked step is
    steered by nothing (view() would show its first reading, not the letters
    filed), so it takes its filed form: an unchecked op carrying them."""
    filed = node.pop("_filed", None)
    if filed is not None and loose:
        keep = {k: node[k] for k in ("indicators",) if k in node}
        node.clear()
        node.update({**filed, **keep})
        return
    for p in node.get("parts") or []:
        _pin_selections(p, loose or bool(node.get("unchecked")))


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
            # The letters agree; only the spacing or the hyphens differ from what
            # the entry derives. The printed enumeration and separators win: the
            # stored spacing is kept as `spelling` only where it is the
            # enumeration's own and the entry has no separators to say it.
            words = [len(L(w)) for w in re.split(r"[ \-'’]", stored) if L(w)]
            if words == _printed_counts(entry, puzzle) \
                    and not _separated(entry, puzzle):
                out["spelling"] = stored
            else:
                notes.add("answer respaced to the enumeration")
        else:
            out["spelling"] = stored
    if display is None and stored:
        # The source has no key for this light: the annotation's answer is the
        # only one there is, so it is kept as the spelling.
        out["spelling"] = stored
    if defs is not None:
        out["definitions"] = defs
    blocks = [b for b in ann.get("blocks") or [] if isinstance(b, dict)]
    inds = [i for i in ann.get("indicators") or [] if isinstance(i, dict)]
    def_inds = [i for i in inds if i.get("for") in DEF_TYPES]
    inds = [i for i in inds if i.get("for") not in DEF_TYPES]
    if def_inds:
        _attach_to_definitions(out.get("definitions"), def_inds, (entry.get("clue") or {}).get("text") or "")
    tset = set(types)
    want = annotation.wordplay_letters(ann, entry)
    def_texts = {L(d.get("text")) for d in defs or []}
    if "double_definition" in tset and len(defs or []) > 1 and any(b.get("gives") for b in blocks) and all(
            L(b.get("gives")) == want and b.get("soundsLike") is None and b.get("select") is None
            for b in blocks if b.get("gives")):
        if not all(_is_definition(b, def_texts) for b in blocks):
            raise Unconvertible("double definition block that is no definition")
        # Each definition filed as a block giving the whole answer: they are
        # the definitions, and give nothing a definition doesn't.
        notes.add("double definition gives the answer")
        blocks = [{k: v for k, v in b.items() if k != "gives"} for b in blocks]
    if "double_definition" in tset and not any(b.get("gives") for b in blocks) and \
            not tset & {"cryptic_definition"}:
        # A double definition is its definitions: a v2 file has nowhere else
        # to keep a block, so one definition, or a block that is none of
        # them, is a stored annotation to redo.
        if not defs or len(defs) < 2:
            raise Unconvertible("double definition with one definition")
        tree = None
        spare = list(blocks)
        for d in defs:
            fits = [b for b in spare if _is_definition(b, {L(d["text"])})]
            b = fits and next((x for x in fits if L(x.get("clueFragment")) == L(d["text"])), fits[0])
            if b:
                spare.remove(b)
            # A definition's block note is its `meaning` (the blocks rung);
            # its `note` stays on the definitions rung. No meaning, no block
            # note: a definition note is never moved up a rung (times-29410
            # 26A's "read as FLY BY NIGHT" named the answer there).
            if b and b.get("note"):
                if d.get("note") and b["note"] != d["note"]:
                    notes.add("double definition meaning kept apart")
                d["meaning"] = b["note"]
        if spare:
            raise Unconvertible("double definition block that is no definition")
    elif "cryptic_definition" in tset and not any(b.get("gives") for b in blocks):
        tree = {"op": "cryptic", "parts": [_leaf(b) for b in blocks]} if blocks else None
    else:
        tree = _tree(blocks, inds, tset, annotation.wordplay_letters(ann, entry), ann, notes)
    if "palindrome" in tset and not any(n.get("op") == "palindrome" for n in _walk(tree or {})):
        tree = _palindrome(tree, want, [i for i in inds if i.get("for") == "palindrome"],
                           (entry.get("clue") or {}).get("text") or "")
    if tree is not None:
        want = annotation.wordplay_letters(ann, entry)
        _attach(tree, inds, tset, want, types)
        # A stored type no op of the tree does (a step done inside one block,
        # with no indicator) is kept as an unchecked op of that type round it.
        have = {annotation.OP_TYPE[n["op"]] for n in _walk(tree) if "op" in n}
        for t in types:
            if t not in have and t in TYPE_OP and t != "charade":
                tree = {"op": TYPE_OP[t], "unchecked": True, "gives": want, "parts": [tree]}
                have.add(t)
        _pin_selections(tree)
        out["wordplay"] = tree
    elif inds:
        if "double_definition" not in tset or not out.get("definitions"):
            raise Unconvertible("indicators with no wordplay")
        # A double definition's pun step (a dropped letter, a reversal) has no
        # letters to check: its indicators hang on the definitions.
        _attach_to_definitions(out["definitions"], inds, (entry.get("clue") or {}).get("text") or "")
        notes.add("double definition step indicators on the definitions")
    for key in ("explanation", "features", "definedByPreamble", "hiddenLetter"):
        if key in ann:
            out[key] = ann[key]
    if "and_lit" in tset:
        out["andLit"] = True
    order = ("definitions", "definedByPreamble", "wordplay", "spelling", "andLit", "hiddenLetter",
             "explanation", "features")
    return {k: out[k] for k in order if k in out}, notes


LETTER_COUNT_ONLY = annotation.LETTER_COUNT_ONLY


def _lights(entry, puzzle):
    """The lights of the answer, in order. The holder entry stands for its own
    light, as in annotation.display_answer: an alsoLeads item is seen as its
    leader with the item's clue, and the leader's stored clue belongs to its
    other group (genius-209 22A leads IVOR HUGH JEGO, separators at 4, and
    also IVOR SORE BEACH BUM, "4,4,5,3", no separators). Read from the
    puzzle, that leader's marks and count made the group look separated, so
    the stored spacing was dropped and view() gave IVORSOREBEACHBUM."""
    by_id = {annotation.entry_id(e): e for e in (puzzle or {}).get("entries") or []}
    if entry.get("number") is not None and entry.get("direction"):
        by_id[annotation.entry_id(entry)] = entry
    return [by_id.get(i, {}) for i in entry.get("group") or []] or [entry]


def _printed_counts(entry, puzzle):
    """The word lengths the enumerations print for the answer: each light's,
    in order, for a linked answer."""
    return [n for x in _lights(entry, puzzle) for n in enumeration.counts((x.get("clue") or {}).get("enumeration"))]


def _separated(entry, puzzle):
    """Whether any light of the answer has separators (the marks between its words)."""
    return any((x.get("clue") or {}).get("separators") for x in _lights(entry, puzzle))


def _enumerated(entry, puzzle):
    """Whether any light of the answer prints an enumeration or separators
    that could space it."""
    if str((puzzle or {}).get("id", "")).rsplit("-", 1)[0] in LETTER_COUNT_ONLY:
        return False
    return any((x.get("clue") or {}).get("enumeration") or (x.get("clue") or {}).get("separators") for x in _lights(entry, puzzle))


def _letterless(unit):
    """A unit as an unchecked leaf that gives no letters: its clue words,
    note and selection kept (a legacy block that is only a comment)."""
    leaf = next((n for n in _walk(unit) if n.get("words")), {})
    out = {k: leaf[k] for k in ("words", "note", "select", "soundsLike") if k in leaf}
    op = unit.get("op")
    if "select" not in out and op in W.SELECT:
        out["select"] = unit["n"] if op == "nth" else op
    return {**out, "unchecked": True}


def _slips(units, vals, ann, tset, want):
    """(units, vals, made any) with each setter's slip made one unit. A slip is a legacy
    `assembly.anagrams` row whose fodder does not hold the letters it gives
    (tools/data/setter_error.json says which clues may have one, and the
    validator holds the row to it). No search can rebuild such an anagram,
    and an unchecked op of the clue's first missing type round all the blocks
    loses which letters are shuffled (azed-1751 21D: an unchecked deletion
    giving TRILENE inside an unchecked anagram giving TRILENE). So the run of
    blocks that spells the fodder becomes one unchecked anagram giving the
    stated letters, the rest of the wordplay is rebuilt round it as usual,
    and view() lists it as the anagram the row names.

    A block may have hidden the slip by respelling its words (quiptic-32 13D:
    "Elf oil" filed as giving ELFOIF, while the assembly kept the printed
    SKISELFOIL), which made a fully checked tree out of a leaf's untrue
    `gives`. The fodder is matched against each block's gives or its words as
    printed, and a leaf whose printed words are what fit is taken as printed."""
    made = False
    for a in (ann.get("assembly") or {}).get("anagrams") or []:
        if not isinstance(a, dict):
            continue
        f, g = L(a.get("fodder")), L(a.get("gives"))
        if not f or not g or _bag(f) == _bag(g):
            continue

        def readings(k):
            u = units[k]
            out = [vals[k]] if vals[k] else []
            if "op" not in u and u.get("words") and not u.get("unchecked") and L(u["words"]) not in out:
                out.append(L(u["words"]))
            return out
        real = [k for k in range(len(units)) if readings(k)]
        pick = None
        for i in range(len(real)):
            for j in range(i + 1, len(real) + 1):
                ks = real[i:j]
                if len(ks) > 8 or pick:
                    break
                for combo in itertools.product(*(readings(k) for k in ks)):
                    if _bag("".join(combo)) == _bag(f):
                        pick = list(zip(ks, combo))
                        break
        if pick is None:
            continue
        for k, got in pick:
            if got != vals[k]:
                units[k] = {x: v for x, v in units[k].items() if x != "gives"}
        # The run as filed: a block between fodder words that gives nothing
        # (sundaytel-3008 15D's "with") stays inside it, in its place.
        pick = list(range(pick[0][0], pick[-1][0] + 1))
        inner = [units[k] for k in pick]
        node = {"op": "anagram", "unchecked": True, "gives": g,
                "parts": inner if len(inner) == 1 else [{"op": "charade", "parts": inner}]}
        keep = [k for k in range(len(units)) if k not in pick[1:]]
        units = [node if k == pick[0] else units[k] for k in keep]
        vals = [g if k == pick[0] else vals[k] for k in keep]
        rest = [k for k, v in enumerate(vals) if v and units[k] is not node]
        if _bag(g) == _bag(want) and rest and "deletion" not in tset:
            # The slip gives the whole answer and other blocks still give
            # letters. Where they give exactly what the slip lacks, they are
            # the annotator saying where the missing letter would have come
            # from (times-19660 6D: REPAPER for REAPPEAR, and "available"
            # giving A, "though no word tells the solver to take it";
            # ftcryptic-18035 21A: "Large" filed as N). They ride along as
            # notes, words and select kept, letters dropped: the row is the
            # parse. Anything else contradicts the row: redo the clue.
            lack = collections.Counter(g) - collections.Counter(f)
            if collections.Counter("".join(vals[k] for k in rest)) != lack:
                raise Unconvertible("setter's slip and blocks disagree", f"{f} gives {g}")
            for k in rest:
                units[k], vals[k] = _letterless(units[k]), ""
        made = True
    return units, vals, made


def _tree(blocks, inds, tset, want, ann, notes):
    sel_inds = [i["text"] for i in inds if i.get("for") == "letter_selection" and i.get("text")]
    units, vals, fixed = [], [], set()
    for b in blocks:
        node, v, ts = _unit(b, sel_inds, "hidden_word" in tset, "homophone" in tset,
                              [i["text"] for i in inds if i.get("text")])
        if "+pre-op" in ts:
            notes.add("gives before the op")
            ts = ts - {"+pre-op"}
        units.append(node)
        vals.append(v)
        fixed |= ts
    if not units:
        return None
    units, vals, slipped = _slips(units, vals, ann, tset, want)
    if slipped:
        # The slip is the clue's anagram: the search is not to look for another.
        fixed.add("anagram")
    # Blocks that give nothing (an indicator filed as a block) ride along unchecked.
    real = [k for k, v in enumerate(vals) if v]
    if not real and "palindrome" in tset:
        # The answer reads both ways and that is the wordplay; the blocks are notes.
        return {"op": "palindrome", "parts": units}
    hl = ann.get("hiddenLetter")
    if isinstance(hl, dict) and hl.get("kind") in ("extra", "omitted"):
        return {"op": "charade", "unchecked": True, "gives": want, "parts": units}
    kinds = tuple(k for k in SEARCH if k in tset and not (slipped and k == "anagram"))
    found = build(tuple(units[k] for k in real), tuple(vals[k] for k in real), want, kinds) if real else {}
    tree = None
    if found:
        goal = (tset & set(SEARCH)) - (fixed & {"anagram"})
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


def _palindrome(tree, want, inds, clue):
    """A palindrome checks the letters of what it governs: the whole
    wordplay (or the answer alone, when that is all there is) when the
    answer reads both ways, else the part that does (EVE in S + I + EVE),
    the one nearest its indicator."""
    if not tree:
        return {"op": "palindrome", "parts": []}
    if want != want[::-1]:
        try:
            got = W.evaluate(tree, want)
        except W.WordplayError:
            got = {}
        cands = [n for n in _walk(tree) if len(got.get(id(n), "")) > 1 and got[id(n)] == got[id(n)][::-1]]
        if cands:
            at = W.find_at(clue, inds[0].get("text") or "") if inds else None

            def dist(n):
                spots = [W.find_at(clue, x["words"]) for x in _walk(n) if x.get("words")]
                spots = [x for x in spots if x is not None]
                return min((abs(x - at) for x in spots), default=len(clue)) if at is not None else 0
            node = min(cands, key=lambda n: (dist(n), -len(got[id(n)])))
            inner = dict(node)
            node.clear()
            node.update({"op": "palindrome", "parts": [inner]})
            return tree
    return {"op": "palindrome", "parts": [tree]}


def _attach_to_definitions(defs, inds, clue):
    """Hang each double-definition or &lit indicator on the definition
    nearest it in the clue (the first, when it can't be placed)."""
    if not defs:
        raise Unconvertible("definition indicator with no definition")
    for ind in inds:
        at = W.find_at(clue, ind.get("text") or "")
        d = defs[0] if at is None else min(
            defs, key=lambda d: abs(d.get("at", 0) + len(d.get("text", "")) / 2 - at - len(ind["text"]) / 2))
        new = {"text": ind.get("text")}
        if ind.get("note"):
            new["note"] = ind["note"]
        d.setdefault("indicators", []).append(new)


def _attach(tree, inds, tset, want, order=()):
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
        if not nodes and not t:
            # A blank `for` on a tree with no op to take it (one leaf filed with
            # a selection and a sound): the next stored type no op has yet.
            have = {annotation.OP_TYPE[n["op"]] for n in _walk(tree) if "op" in n}
            t = next((x for x in order if x in TYPE_OP and x != "charade" and x not in have), None)
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


def _dd_blocks_match(old, new):
    """Whether each stored block of a double definition is one of the view's
    (a definition, by its letters: the stored fragment may differ from the
    definition only in punctuation, and a definition may have no block)."""
    rest = list(new)
    for b in old:
        for k, v in enumerate(rest):
            if _is_definition(b, {L(v.get("clueFragment"))}) and (
                    not b.get("note") or b.get("note") == v.get("note")):
                del rest[k]
                break
        else:
            return False
    return True


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
            elif t == "double_definition" and len(old.get("definitions") or []) < 2:
                bad.add("double definition with one definition")
            elif "double_definition" in ot and not new.get("wordplay") and len(old.get("definitions") or []) > 1:
                # A pun step of a double definition (a preamble reversal, a
                # dropped letter) has no letters to check, so no op and no
                # type: its indicators ride on the definitions.
                acc.add("double definition step type dropped")
            else:
                bad.add(f"type lost: {t}")
        for t in sorted(set(vt) - set(ot)):
            # Two definitions are a double definition, whatever the list said.
            if t in checked or (t == "double_definition" and len(old.get("definitions") or []) > 1) or (
                    t == "charade" and not any(n.get("op") == "charade" and not n.get("unchecked")
                                               for n in _walk(new.get("wordplay") or {}))):
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
        if of != vf and not ("double_definition" in ot and not new.get("wordplay")):
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
        elif _slipped(old) and len(nob) == len(nvb) and all(
                {k: v for k, v in o.items() if k != "gives"} == {k: v for k, v in n.items() if k != "gives"}
                and (o.get("gives") == n.get("gives") or n.get("gives") in (None, L(n.get("clueFragment"))))
                for o, n in zip(nob, nvb)):
            # _slips: a block that respelt its words to hide a setter's slip is
            # taken as printed, and one filed as the letter the slip lacks
            # gives none.
            acc.add("setter's slip taken as printed")
        elif [{k: v for k, v in b.items() if k != "gives"} for b in nob] == \
                [{k: v for k, v in b.items() if k != "gives"} for b in nvb]:
            acc.add("gives before the op")
        elif ("double_definition" in ot or "and_lit" in ot) and _dd_blocks_match(nob, nvb):
            acc.add("double definition blocks recomputed")
        else:
            bad.add("blocks differ")
    oa, va = old.get("assembly") or {}, view.get("assembly") or {}
    fod = lambda a: [(L(x.get("fodder")) and _bag(L(x.get("fodder"))), L(x.get("gives")))
                     for x in a.get("anagrams") or [] if isinstance(x, dict)]
    pcs = lambda a: [L(p) for p in a.get("pieces") or []] if len(a.get("pieces") or []) > 1 else []
    if pcs(oa) != pcs(va) or fod(oa) != fod(va) or _plain(oa.get("reversals")) != _plain(va.get("reversals")):
        acc.add("assembly recomputed")
    if new.get("definitions") and any("meaning" in d and d.get("note") and d["meaning"] != d["note"]
                                      for d in new["definitions"]):
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
    if "double definition gives the answer" in notes and "gives before the op" in acc:
        acc.discard("gives before the op")
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


# ---------- the rewrite: the policy applied ----------

def _clue_id(puzzle, where, held):
    m = re.match(r"\$\.offGrid\[(\d+)\]", where)
    if m:
        return f"{puzzle.get('id')}/{int(m.group(1)) + 1}-offgrid"
    return f"{puzzle.get('id')}/{held.get('number')}-{held.get('direction')}"


def migrate_puzzle(puzzle):
    """(the puzzle as a whole format v2 file, {clue id: kinds} redone).

    An annotation that converts takes its v2 form. One that does not (a
    `check` failure: the module docstring's policy) is dropped and nothing
    else: the burn's own queue re-annotates exactly the clues without one,
    and every other clue keeps its work. Every annotation is visited (each
    entry's, each alsoLeads item's, each offGrid clue's), and the file loses
    `name`/`series` for the facts display_name needs (`puzzle_names`), so
    the result is v2 even when nothing in it was annotated. A file that is
    already v2 comes back as it is. The input is not changed."""
    import puzzle_schema
    if puzzle_schema.is_v2(puzzle):
        return copy.deepcopy(puzzle), {}
    names, _ = puzzle_names(puzzle) if puzzle.get("id") else ({}, None)
    out = copy.deepcopy({k: v for k, v in puzzle.items() if k not in ("name", "series")})
    out.update(names)
    redo = {}
    for where, held, ann in list(puzzle_schema.annotations(puzzle)):
        status, kinds, new = check(ann, held, puzzle)
        node = out
        for part in re.findall(r"\.(\w+)|\[(\d+)\]", where.split("$", 1)[1])[:-1]:
            node = node[part[0]] if part[0] else node[int(part[1])]
        if status == "failed":
            redo[_clue_id(puzzle, where, held)] = sorted(kinds)
            del node["annotation"]
        else:
            node["annotation"] = new
    return puzzle_schema.order(puzzle_schema.prune(out)), redo


def tree_counts(puzzle):
    """(annotations whose tree is all checked, annotations with an unchecked
    step) in a v2 puzzle. The second is the puzzle's `wordplay.unchecked`
    allowance: validate_annotations.v2_view warns once per such annotation and
    count_backlog counts the clues it names."""
    import puzzle_schema
    full = opaque = 0
    for _, _, ann in puzzle_schema.annotations(puzzle):
        if ann.get("wordplay") and any(n.get("unchecked") for n in _walk(ann["wordplay"])):
            opaque += 1
        else:
            full += 1
    return full, opaque


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


def convert_puzzle(puzzle):
    """(the puzzle as a format v2 file, {annotation path: 'exact' | 'normalised'}):
    no `name` or `series`, the facts display_name needs instead, and every
    annotation converted. Raises Unconvertible naming the first annotation
    that fails, since a file is wholly one shape."""
    import puzzle_schema
    names, _ = puzzle_names(puzzle)
    out = {k: v for k, v in puzzle.items() if k not in ("name", "series")}
    out.update(names)
    out = copy.deepcopy(out)
    status = {}
    for where, held, ann in list(puzzle_schema.annotations(puzzle)):
        st, kinds, new = check(ann, held, puzzle)
        if st == "failed":
            raise Unconvertible(f"{where}: {', '.join(sorted(kinds))}")
        status[where] = st
        # Put the converted annotation where the path says.
        node = out
        for part in re.findall(r"\.(\w+)|\[(\d+)\]", where.split("$", 1)[1])[:-1]:
            node = node[part[0]] if part[0] else node[int(part[1])]
        node["annotation"] = new
    return puzzle_schema.order(puzzle_schema.prune(out)), status


def converted_samples(n=2, series="cryptic", look=20):
    """[(legacy puzzle, its v2 conversion, status)] for the newest `n` annotated
    puzzles of `series`, among the newest `look`, that convert whole: the
    fixtures tools/test_format_v2.sh, test_shim_format.sh and smoke_test.js
    hold the two shapes to each other on, in memory."""
    from pathlib import Path

    import fetch_puzzle
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "puzzles", series)
    files = sorted((os.path.join(dp, f) for dp, _, fs in os.walk(root) for f in fs
                    if f.endswith(".json")), key=lambda f: int(re.sub(r"\D", "", os.path.basename(f)) or 0),
                   reverse=True)[:look]
    out = []
    for f in files:
        old = fetch_puzzle.read_puzzle_file(Path(f))
        if not any(e.get("annotation") for e in old["entries"]):
            continue
        try:
            new, status = convert_puzzle(old)
        except Unconvertible:
            continue
        out.append((old, new, status))
        if len(out) == n:
            break
    return out


# ---------- dry run ----------

# Failures listed with the answer against the solution, for re-annotation.
CONTRADICT = {"answer contradicts enumeration", "answer letters differ from the solution"}

def dry_run(root, report, limit=None):
    counts = collections.Counter()
    kinds = {"normalised": collections.Counter(), "failed": collections.Counter()}
    examples = collections.defaultdict(list)
    names = collections.Counter()
    name_ex = collections.defaultdict(list)
    contradict = []
    failed_ids = collections.defaultdict(list)
    seen = 0
    def write(done):
        total = sum(counts.values())
        pct = lambda n: f"{100 * n / total:.1f}%" if total else "-"
        full = counts["exact"] + counts["normalised"] - kinds["normalised"]["unchecked step kept"]
        lines = [f"Format v2 converter dry run over {root}: {seen} puzzles, {total} annotations, read-only"
                 + ("." if done else " (PARTIAL: still running)."), "",
                 f"exact       {counts['exact']:7d}  {pct(counts['exact'])}",
                 f"normalised  {counts['normalised']:7d}  {pct(counts['normalised'])}",
                 f"failed      {counts['failed']:7d}  {pct(counts['failed'])}"
                 "  (redo: migrate_puzzle drops that clue's annotation, the burn re-annotates it)",
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
        rest = [k for k, _ in kinds["failed"].most_common() if k not in CONTRADICT]
        if rest:
            lines += ["", "Every other failure, by kind (stored annotations to redo):"]
            for k in rest:
                lines.append(f"  {k} ({len(failed_ids[k])}):")
                ids = failed_ids[k]
                lines += ["    " + ", ".join(ids[n:n + 6]) for n in range(0, len(ids), 6)]
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
                        if status == "failed":
                            failed_ids[k].append(eid)
                        if len(examples[(status, k)]) < 3:
                            examples[(status, k)].append(eid)
                if status == "failed" and ks & CONTRADICT:
                    contradict.append(f"{eid} ({e['annotation'].get('answer')!r} vs {e.get('solution')!r}, "
                                      f"{e['clue'].get('enumeration', '')})")
            if limit and seen >= limit:
                break
        if limit and seen >= limit:
            break
    return write(True)


# ---------- the migration (plan step 8): every file rewritten in place ----------

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LEDGER = ".convert_v2_migrate.jsonl"


def _findings(puzzle, old):
    import puzzle_integrity
    try:
        puzzle_integrity.refuse_bad_write(puzzle, old)
        return set()
    except puzzle_integrity.RefusedWrite as e:
        return {(flag, what) for flag, _, what in e.flags}


def _validate_regressions(old, new):
    """What validate_annotations (the deploy's corpus rules, as --tighten and
    the pre-commit hook run them) finds on the v2 file and not on the legacy
    one: each new ERROR, and each backlog ratchet whose count grew (that
    would fail the ratchet). `wordplay.unchecked` is left out: the migration
    writes that allowance itself. The step 8 attempt of 10-13 converted 79
    files the tighten then refused, which blocked the whole commit; a file
    like that is held legacy instead, and the commit message names why."""
    import validate_annotations as V

    def seen(p):
        _, errors, warnings = V.validate_puzzle(copy.deepcopy(p), corpus=True)
        counts = V.count_backlog(warnings)
        counts.pop("wordplay.unchecked", None)
        return errors, counts
    e_old, c_old = seen(old)
    e_new, c_new = seen(new)
    out = [f"validate {e[:240]}" for e in e_new if e not in e_old]
    out += [f"validate ratchet {f}: {c_old.get(f, 0)} -> {n} clue(s)"
            for f, n in c_new.items() if n > c_old.get(f, 0)]
    return out


def _committed(path):
    """The file as HEAD has it (the legacy copy of one an interrupted run already rewrote)."""
    import subprocess
    try:
        rel = os.path.relpath(os.path.realpath(path), os.path.realpath(REPO))
        out = subprocess.run(["git", "-C", REPO, "show", f"HEAD:{rel}"], capture_output=True, check=True)
        return json.loads(out.stdout)
    except (subprocess.CalledProcessError, ValueError):
        return None


def migrate_file(path, write=True):
    """One file of the migration: {id, path, full, opaque, redo, held?}.

    The file is rewritten whole or not at all (a .part renamed over it, as
    fetch_puzzle.write_puzzle_file writes), and only when puzzle_integrity's
    write check, and validate_annotations (_validate_regressions), find
    nothing on the v2 file that they did not already find on the legacy
    one; otherwise it is left legacy and `held` names the new
    findings (a file is wholly one shape, so a held file is still valid). A
    file already v2 (an interrupted run's) is recounted from HEAD's copy."""
    import puzzle_schema
    with open(path, encoding="utf-8") as fh:
        cur = json.load(fh)
    rec = {"id": cur.get("id"), "path": path}
    if puzzle_schema.is_v2(cur):
        old = _committed(path)
        _, redo = migrate_puzzle(old) if old is not None and not puzzle_schema.is_v2(old) else (None, {})
        rec.update(zip(("full", "opaque"), tree_counts(cur)), redo=redo, already=True)
        return rec
    new, redo = migrate_puzzle(cur)
    extra = sorted(f"{f} {w}" for f, w in _findings(new, cur) - _findings(cur, cur))
    if not extra:
        extra = _validate_regressions(cur, new)
    if extra:
        rec.update(full=0, opaque=0, redo={}, held=extra[:5])
        return rec
    rec.update(zip(("full", "opaque"), tree_counts(new)), redo=redo)
    if write:
        part = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.part")
        with open(part, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(new, indent=1, ensure_ascii=False) + "\n")
        os.replace(part, path)
    return rec


def _migrate_one(args):
    path, write = args
    try:
        return migrate_file(path, write)
    except Exception as x:  # a converter bug: the file stays legacy, the run goes on
        return {"id": os.path.basename(path)[:-5], "path": path, "full": 0, "opaque": 0, "redo": {},
                "held": [f"crashed: {type(x).__name__}: {x}"[:300]]}


def write_allowance(records, backlog):
    """Set each migrated puzzle's `wordplay.unchecked` allowance (its clues with an
    unchecked step) in annotation_backlog.json; every other field as it was."""
    import validate_annotations as V
    with open(backlog) as fh:
        data = json.load(fh)
    allow = dict(data.get("wordplay.unchecked") or {})
    for r in records:
        if r.get("held"):
            continue
        if r["opaque"]:
            allow[r["id"]] = r["opaque"]
        else:
            allow.pop(r["id"], None)
    data["wordplay.unchecked"] = dict(sorted(allow.items(), key=V._sort_key))
    with open(backlog, "w") as fh:
        fh.write(json.dumps(data, indent=1) + "\n")
    return sum(allow.values()), len(allow)


def commit_message(records):
    full = sum(r["full"] for r in records)
    opaque = sum(r["opaque"] for r in records)
    redo = {k: v for r in records for k, v in r["redo"].items()}
    held = [r for r in records if r.get("held")]
    by_kind = collections.defaultdict(list)
    for cid, kinds in redo.items():
        by_kind[kinds[0] if len(kinds) == 1 else ", ".join(kinds)].append(cid)
    lines = [f"Migrate puzzles to format v2: {full} trees, {opaque} opaque", "",
             f"tools/convert_v2.py --migrate over {len(records)} puzzle files: {full} annotations with",
             f"a fully checked tree, {opaque} with an unchecked step (allowed per puzzle under",
             f"wordplay.unchecked in tools/annotation_backlog.json), {len(redo)} redone: the clue's",
             "annotation dropped for the burn to re-annotate (plan section 5). The old text is in",
             "this commit's parent.", ""]
    if held:
        lines += [f"Left legacy ({len(held)}; puzzle_integrity or validate_annotations found something new on the v2 file):"]
        lines += [f"  {r['id']}: {'; '.join(r['held'])}" for r in held] + [""]
    lines += ["Redone, by kind:"]
    for k, ids in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"  {k} ({len(ids)}):")
        lines += ["    " + ", ".join(ids[n:n + 6]) for n in range(0, len(ids), 6)]
    return "\n".join(lines) + "\n"


def migrate(root, backlog, jobs=4, commit=False, limit=None):
    """Rewrite every puzzle under `root` as format v2, in place; see main()."""
    import multiprocessing
    import subprocess
    root = os.path.abspath(root)
    ledger = os.path.join(os.path.dirname(root), LEDGER)
    done = {}
    if os.path.exists(ledger):
        with open(ledger) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue  # a line cut by a kill
                done[r["path"]] = r
    files = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(root) for f in fs
                   if f.endswith(".json") and not f.startswith("."))
    if limit:
        files = files[:limit]
    todo = [f for f in files if f not in done or done[f].get("held")]
    print(f"migrate: {len(files)} files, {len(files) - len(todo)} done by an earlier run, "
          f"{len(todo)} to go; ledger {ledger}", file=sys.stderr, flush=True)
    with open(ledger, "a") as out, multiprocessing.Pool(jobs) as pool:
        for n, r in enumerate(pool.imap_unordered(_migrate_one, [(f, True) for f in todo], chunksize=8), 1):
            done[r["path"]] = r
            out.write(json.dumps(r) + "\n")
            out.flush()
            if n % 1000 == 0:
                print(f"migrate: {n}/{len(todo)}", file=sys.stderr, flush=True)
    records = [done[f] for f in files if f in done]
    total, puzzles = write_allowance(records, backlog)
    msg = commit_message(records)
    held = sum(1 for r in records if r.get("held"))
    print(msg.split("\n\n")[0])
    print(f"{len(records)} files, {held} left legacy; wordplay.unchecked allowance {total} clues in "
          f"{puzzles} puzzles; redone {sum(len(r['redo']) for r in records)} clues")
    msg_path = os.path.join(os.path.dirname(root), ".convert_v2_migrate.msg")
    with open(msg_path, "w") as fh:
        fh.write(msg)
    if commit:
        trailer = subprocess.run([sys.executable, os.path.join(REPO, "tools", "provenance.py"), "trailer"],
                                 capture_output=True, text=True).stdout.strip()
        if trailer:
            with open(msg_path, "a") as fh:
                fh.write("\n" + trailer + "\n")
        subprocess.run(["git", "-C", REPO, "add", "--", os.path.relpath(root, REPO),
                        os.path.relpath(backlog, REPO)], check=True)
        subprocess.run(["git", "-C", REPO, "commit", "-q", "-F", msg_path], check=True)
        os.remove(ledger)
        os.remove(msg_path)
        print(f"committed: {subprocess.run(['git', '-C', REPO, 'log', '-1', '--format=%h %s'], capture_output=True, text=True).stdout.strip()}")
    else:
        print(f"not committed; message in {msg_path}")
    return records


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root", help="puzzles/ (or a subfolder); read only unless --migrate")
    ap.add_argument("--report", help="write the dry-run report here")
    ap.add_argument("--limit", type=int, help="stop after this many annotated puzzles (--migrate: files)")
    ap.add_argument("--migrate", action="store_true",
                    help="rewrite every file under root as format v2 in place (plan step 8), write "
                         "the wordplay.unchecked allowance into --backlog, and with --commit make "
                         "the one migration commit. Resumable: a killed run picks up from "
                         f"<root>/../{LEDGER} when started again the same way.")
    ap.add_argument("--backlog", default=os.path.join(REPO, "tools", "annotation_backlog.json"))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--commit", action="store_true", help="--migrate: commit the result (root in this repo)")
    a = ap.parse_args()
    if a.migrate:
        recs = migrate(a.root, a.backlog, a.jobs, a.commit, a.limit)
        raise SystemExit(1 if any(r.get("held") for r in recs) and not a.commit else 0)
    text = dry_run(a.root, a.report, a.limit)
    print(text if len(text) < 6000 else text[:6000] + "\n…")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
