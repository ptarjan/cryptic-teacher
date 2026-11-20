"""Single edits of the doesNotGive mend (fix_shape_notes.r_does_not_give) for a clue word the tree left out.

Each function returns copies of the tree with ONE edit; r_does_not_give keeps an edit only when it gives the
answer and no other single edit does:
  - an article ('a') the clue prints beside a leaf and no leaf claims is read as the letter A, joined to that
    leaf (RAMMING: `ins(RING, [couple of thousand]MM)` is RING round A + MM, 'a' printed before 'couple');
  - an anagram's fodder that stops one clue word short of a neighbour no leaf or indicator claims (JETTISON:
    `ana<flying>([It's])` is the anagram of 'It's on');
  - a deletion whose removed letters sit in the base in another order than written is one deletion per letter
    (INFERNAL: FINAL less IF is del(del(FINAL, F), I)).
"""
import collections
import copy
import re

from fix_shape_base import leaf, walk

_ARTICLES = ("a", "an")


def _toks(text):
    return re.findall(r"[\w']+", str(text).lower().replace("’", "'"))


def uncovered_words(node, clue):
    """The clue's word tokens (in order) that no leaf or indicator of the tree claims."""
    claimed = collections.Counter()
    for x, _ in walk(node):
        claimed.update(_toks(x.get("words") or ""))
        for i in x.get("indicators") or []:
            claimed.update(_toks(i.get("text") or ""))
    left = []
    for w in _toks(clue):
        if claimed[w] > 0:
            claimed[w] -= 1
        else:
            left.append(w)
    return left


def _printed(words, clue):
    return f" {' '.join(_toks(words))} " in f" {' '.join(_toks(clue))} "


def gap_edits(fresh, n, node, clue):
    """The copies of `node` with one gap closed at its node `n` (`fresh()` gives a copy and its node)."""
    out = []
    parts = n.get("parts") or []
    if clue and leaf(n) and n.get("words"):
        left = uncovered_words(node, clue)
        for art in _ARTICLES:
            for before in (True, False):
                if art in left and _printed(f"{art} {n['words']}" if before else f"{n['words']} {art}", clue):
                    new, t = fresh()
                    mine = copy.deepcopy(t)
                    t.clear()
                    t.update({"op": "charade", "parts": [{"words": art}, mine] if before else [mine, {"words": art}]})
                    out.append(new)
    if clue and n.get("op") == "anagram":
        left = set(uncovered_words(node, clue))
        for j, lf in enumerate(parts):
            if "op" in lf or lf.get("gives") or not lf.get("words"):
                continue
            for w in sorted(left):
                for grown in (f"{lf['words']} {w}", f"{w} {lf['words']}"):
                    if _printed(grown, clue):
                        new, t = fresh()
                        t["parts"][j]["words"] = grown
                        t["parts"][j].pop("at", None)
                        out.append(new)
    if n.get("op") == "deletion" and len(parts) == 2 and leaf(parts[0]) and leaf(parts[1]):
        out += _split_deletion(fresh, parts)
    return out


def _letters(lf):
    return re.sub(r"[^A-Za-z]", "", str(lf.get("gives") or lf.get("words") or "")).upper()


def _split_deletion(fresh, parts):
    """del(base, XY) where X and Y sit in the base in the other order (or apart): one del per letter, each taken
    at its leftmost spot still left (the order does not change the result). The words stay on the first removed letter (a later blockNote drops them)."""
    base, gone = _letters(parts[0]), _letters(parts[1])
    if not 2 <= len(gone) <= 4 or not base or base.find(gone) >= 0:
        return []
    rest, order = base, []
    for ch in gone:
        if ch not in rest:
            return []
        order.append((rest.index(ch), ch))
        rest = rest.replace(ch, "", 1)
    new, t = fresh()
    pieces = [{"gives": ch} for _, ch in order]
    if parts[1].get("words"):
        pieces[0]["words"] = parts[1]["words"]
    inner = t["parts"][0]
    for p in pieces[:-1]:
        inner = {"op": "deletion", "parts": [inner, p]}
    t["parts"] = [inner, pieces[-1]]
    return [new]
