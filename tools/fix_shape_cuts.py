"""Deletion and selection repairs of fix_shape_suspects.py: the letters an op removes or keeps, and the
indicator words that name them. Each r_* takes (node, parent, ctx) and returns a replacement node or None.
"""
import copy
import json
import re

import annotation
import validate_annotations as V
import wordplay as W
from fix_shape_base import TAIL, HEAD, MID, walk, leaf, vals, checked, _eval_swapped
from fix_shape_leaves import _tokens, _abbreviations
from fix_shape_indicators import _mine_for_op, _lexicon_owns


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
