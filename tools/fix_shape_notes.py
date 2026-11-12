"""Note repairs of fix_shape_suspects.py: indicator and block notes, the doesNotGive edits, the doubled
apostrophe, and note_deletions. Each r_* takes (node, parent, ctx) and returns a replacement node or None.
"""
import collections
import copy
import itertools
import json
import re

import validate_annotations as V
import wordplay as W
from fix_shape_base import walk, leaf


# What each op's indicator does, for an indicator the model filed with no note (indicators.note,
# 6 of 249 sessions 10-27: the link word of `+<after>` and `ins<in>` above all). Every sentence
# says the job and names no letters, so the indicators rung stays clear of the blocks; an op not
# listed (a substitution, a move, a spoonerism...) is the model's to word.
INDICATOR_JOBS = {
    "charade": "this word only joins the neighbouring pieces: it says which one stands next to which in the answer",
    "container": "this word is a container marker: it says one piece is placed inside the other, and the clue words of the pieces show which way round",
    "anagram": "this word means the letters it governs are mixed up, so they are rearranged into a new order",
    "reversal": "this word means the letters it governs are turned round, so they are read backwards",
    "hidden": "this word says the answer sits inside the words it governs, as a run of their own consecutive letters",
    "homophone": "this word says the answer is heard rather than seen: it sounds like the word it governs",
    "deletion": "this word says some letters are taken away from the word it governs",
    "first": "this word picks out the opening letter, or opening letters, of the words it governs",
    "last": "this word picks out the closing letter, or closing letters, of the words it governs",
    "middle": "this word picks out the central letter, or central letters, of the word it governs",
    "outer": "this word picks out the outside letters of the word it governs, leaving its middle",
    "alternate": "this word picks out every other letter of the word it governs",
    "repeat": "this word says the piece it governs is written out more than once"}


def unnoted_indicators(tree):
    """How many of `tree`'s indicators carry no note (the first check's indicators.note)."""
    return sum(1 for n, _ in walk(tree) for i in n.get("indicators") or [] if isinstance(i, dict) and not i.get("note"))


def r_indicator_note(node, parent, ctx):
    """indicatorNote: an operation whose indicator has no note (the first check's indicators.note
    refusal, a charade's `+<after>` or a container's `ins<in>` the commonest) gets the sentence for
    what that operation's indicator does (INDICATOR_JOBS). Ops without a sentence stay refused."""
    job = INDICATOR_JOBS.get(node.get("op"))
    inds = [i for i in node.get("indicators") or [] if isinstance(i, dict)]
    if not job or not any(not i.get("note") for i in inds):
        return None
    new = copy.deepcopy(node)
    for i in new["indicators"]:
        if isinstance(i, dict) and not i.get("note"):
            i["note"] = job
    return new


def _block_note_for(leaf_node, parent, tree, answer):
    """The note a letters-giving leaf with none gets, or None when its shape is the model's to word.
    Four shapes have exactly one right sentence (the possessive: 49 of the 110 unnoted blocks in the 54
    sessions of 11-04, `[Celia's]CELIA`; the annotate audit's earlier 139 'missing blocks.note'
    sessions: palindrome 106 since fill_palindrome_fodder, a repeated clue word's second leaf 48,
    the leaf under sound() 37; the rest, a synonym leaf nobody explained, stays refused):
      - the definition's words under pal<ind>(): the palindrome is the whole answer;
      - a leaf whose words a sibling leaf already explains (`[blokes]AL + [blokes]BERT`: one note is
        keyed by those words, so it lands on the first only): that note;
      - a leaf of a word and 's that gives just the word's letters: the 's adds none;
      - the one leaf under sound(): the words said aloud (the letters only when they are not the answer)."""
    if not leaf(leaf_node) or leaf_node.get("note") or leaf_node.get("unchecked") or not leaf_node.get("words"):
        return None
    words = leaf_node["words"]
    # What the block shows: the spelt of a sound() over this leaf, else the leaf's own letters. The
    # validator needs a note unless the fragment is its own letters (`in` > IN).
    sounded = parent is not None and parent.get("op") == "homophone" and len(parent.get("parts") or []) == 1
    shown = W.letters((parent.get("spelt") if sounded else leaf_node.get("gives")) or "")
    if not shown or shown.lower() == W.letters(words).lower():
        return None
    if parent is not None and parent.get("op") == "palindrome" and len(parent.get("parts") or []) == 1:
        return ("these definition words give the whole answer, and the answer is itself the palindrome: "
                "it reads the same from either end")
    if sounded:
        spelt = shown.upper()
        if answer and spelt != W.letters(answer).upper():
            return f"said aloud, these words sound like {spelt}"
        return "these words are said aloud, and what is heard is the sound this part of the answer needs"
    fold = lambda t: " ".join(re.findall(r"\w+", str(t).lower()))
    twins = {str(n["note"]) for n, _ in walk(tree) if leaf(n) and n is not leaf_node and n.get("note")
             and fold(n.get("words")) == fold(words)}
    if len(twins) == 1:
        return next(iter(twins))
    stem = re.fullmatch(r"(.*\w)['\u2019]s", str(words).strip())
    if stem and W.letters(stem.group(1)).lower() == shown.lower():
        return ("the 's only shows possession or stands for 'is', so it adds no letters: "
                "the word before it gives these letters as it is written")
    return None


def _bound_removed_letter(leaf_node, parent):
    """True for the letters a deletion, substitution or move names, filed with a clue word and no
    note: the 30-odd 'missing blocks.note' sessions of 10-29 (`del<topless>([beefcake]HUNK, H)` with
    H bound to the spare word 'showing'). Those letters are no block, and a word that merely links
    is not their source; so the word is dropped and the letters stay bare."""
    if parent is None or parent.get("op") not in W.REMOVED_LETTER_OPS or not leaf(leaf_node):
        return False
    parts = parent.get("parts") or []
    if not any(p is leaf_node for p in parts[1:]):
        return False
    return bool(leaf_node.get("words") and str(leaf_node.get("gives") or "").isalpha()
                and not leaf_node.get("note") and not leaf_node.get("unchecked") and not leaf_node.get("select")
                and W.letters(leaf_node["words"]).lower() != W.letters(leaf_node["gives"]).lower())


def unnoted_blocks(tree, answer=None):
    """How many leaves `r_block_note` could mend (the first check's blocks.note, mendable shapes)."""
    return sum(1 for node, parent in walk(tree)
               if leaf(node) and (_bound_removed_letter(node, parent) or _block_note_for(node, parent, tree, answer)))


def r_block_note(node, parent, ctx):
    """blockNote: a leaf that gives letters and has no note (the first check's blocks.note refusal)
    takes the one sentence its shape fixes (_block_note_for); a removed letter (del/sub/move's later
    piece) bound to a spare clue word loses that word; any other leaf stays refused."""
    tree = ctx.get("tree")
    if tree is None:
        return None
    if _bound_removed_letter(node, parent):
        return {k: v for k, v in node.items() if k not in ("words", "at")}
    note = _block_note_for(node, parent, tree, ctx.get("answer"))
    return {**node, "note": note} if note else None


def r_does_not_give(node, parent, ctx):
    """doesNotGive: a tree that does not give the answer (the first check's commonest refusal), mended
    only when ONE edit makes it give it and no other single edit does: a container whose two arguments
    are the wrong way round (`ins<worn by>(ALL, COW)` for CALLOW: the outer is the second argument), or a
    charade whose pieces stand in the wrong order (a charade with no indicator of its own, up to four
    pieces; a container that is really a charade, a piece that belongs outside it, a leaf filed reversed under rev()
    and a charade with its own indicator in the wrong order: _does_not_give_edits). Two edits that both work, or none,
    stay refused. Run once, at the root, on the unevaluated tree."""
    answer = ctx.get("answer")
    if parent is not None or not answer or node.get("unchecked"):
        return None
    try:
        W.evaluate(copy.deepcopy(node), answer)
        return None
    except W.WordplayError:
        pass
    except (W._NeedTarget, IndexError, KeyError, TypeError, ValueError):
        return None
    found, seen = [], set()
    for late in (False, True):
        # the end cut of a leaf is the last resort: beside the plural-S / surplus-leaf edits it only adds a
        # second way (HIFT for SHIFT) to a tree that has one right edit already
        if late and (found or not _one_trim_candidate(node, answer)):
            break
        for k in range(len(list(walk(node)))):
            for new in _does_not_give_edits(node, k, ctx.get("clue"), late):
                try:
                    W.evaluate(copy.deepcopy(new), answer)
                except (W.WordplayError, W._NeedTarget, IndexError, KeyError, TypeError, ValueError):
                    continue
                key = json.dumps(new, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    found.append(new)
    return found[0] if len(found) == 1 else None


def _one_trim_candidate(node, answer):
    """True when exactly one (leaf, shorter letters) pair, the letter dropped at an end OR inside ([cube]DICE ->
    DIE, [pet]CAT -> AT), makes the tree give the answer: with two, only the clue words' meanings say which
    leaf is wrong, so the end cut is a guess ([pet]AT for INDICATE) and stays refused."""
    cands = set()
    for k, (n, _) in enumerate(walk(node)):
        g = str(n.get("gives") or "")
        if n.get("op") is not None or len(g) < 2 or not g.isalpha():
            continue
        for i in range(len(g)):
            new = copy.deepcopy(node)
            list(walk(new))[k][0]["gives"] = g[:i] + g[i + 1:]
            try:
                W.evaluate(new, answer)
            except (W.WordplayError, W._NeedTarget, IndexError, KeyError, TypeError, ValueError):
                continue
            cands.add((k, g[:i] + g[i + 1:]))
    return len({k for k, _ in cands}) == 1


def _does_not_give_edits(node, k, clue=None, late=False):
    """Every single-edit copy of `node` the doesNotGive mend tries at its k-th node: a container's
    arguments swapped, or a container written as the charade of its two arguments (either order: ADRIFT
    is AD + RIFT, 'in' only linking them); a charade's pieces in another order (an indicator of its own,
    like 'to support', stays); a container argument that is a charade whose end pieces sit outside the
    container (MALBEC is ME round ALB, then C); a reversal over a leaf whose letters are already reversed."""
    out = []
    def fresh():
        new = copy.deepcopy(node)
        return new, list(walk(new))[k][0]
    n = list(walk(node))[k][0]
    parts = n.get("parts") or []
    if late:
        # the last-resort tier of r_does_not_give: only the one-letter end cut of a leaf
        if leaf(n) and n.get("words") and str(n.get("gives") or "").isalpha() and len(n["gives"]) >= 3:
            for cut in (n["gives"][1:], n["gives"][:-1]):
                new, t = fresh()
                t["gives"] = cut
                out.append(new)
        return [_flat_charades(new) for new in out]
    if n.get("op") == "container" and len(parts) == 2:
        for order in ([1, 0], ):
            new, t = fresh()
            t["parts"] = [t["parts"][i] for i in order]
            out.append(new)
        for order in ([0, 1], [1, 0]):
            new, t = fresh()
            t["op"] = "charade"
            t["parts"] = [t["parts"][i] for i in order]
            t.pop("indicators", None)   # a container word between two plain pieces is a link, not a charade's
            out.append(new)
        for j in (0, 1):
            arg = parts[j]
            sub = arg.get("parts") or []
            if arg.get("op") != "charade" or arg.get("indicators") or len(sub) < 2 or len(sub) > 4:
                continue
            for a in range(len(sub)):
                for b in range(a + 1, len(sub) + 1):
                    if b - a == len(sub):
                        continue
                    new, t = fresh()
                    mid = t["parts"][j]["parts"][a:b]
                    t["parts"][j] = mid[0] if len(mid) == 1 else dict(t["parts"][j], parts=mid)
                    inner = dict(t)
                    pre, post = parts[j]["parts"][:a], parts[j]["parts"][b:]
                    pre, post = copy.deepcopy(pre), copy.deepcopy(post)
                    inner_node = {key: v for key, v in inner.items()}
                    t.clear()
                    t.update({"op": "charade", "parts": [*pre, inner_node, *post]})
                    out.append(new)
    elif n.get("op") == "charade" and 2 <= len(parts) <= (4 if not n.get("indicators") else 3):
        for o in itertools.permutations(range(len(parts))):
            if list(o) != list(range(len(parts))):
                new, t = fresh()
                t["parts"] = [t["parts"][i] for i in o]
                out.append(new)
    if n.get("op") == "charade" and len(parts) >= 2:
        # a link word filed as a bare leaf ('[to]' in [Man]HE + [to] + [run out]RO) is read as its own
        # letters (HETORO): dropped, the charade is the answer. Bare = no gives, no op, one word. A
        # two-piece charade ('[a] + [way]LANE' for PLANET: the article is no letter of the answer) is
        # left holding the one piece, which stands in its place.
        for i, p in enumerate(parts):
            if "op" not in p and not p.get("gives") and len(str(p.get("words") or "").split()) == 1:
                new, t = fresh()
                del t["parts"][i]
                if len(t["parts"]) == 1:
                    only = t["parts"][0]
                    t.clear()
                    t.update(only)
                out.append(new)
    elif n.get("op") == "reversal" and len(parts) == 1 and leaf(parts[0]) and parts[0].get("gives"):
        new, t = fresh()
        t["parts"][0]["gives"] = t["parts"][0]["gives"][::-1]
        out.append(new)
    if n.get("op") == "reversal" and len(parts) == 1 and leaf(parts[0]) and n.get("indicators") \
            and str(parts[0].get("gives") or "").isalpha():
        # rev(FELT) for LEFT: only a stretch of the leaf is turned round (FEL to LEF), which rev() cannot
        # say and sub(leaf, FEL, LEF) can, keeping the reversal's indicator. Every stretch of 2+ letters
        # is tried; the caller keeps the mend only when exactly one edit in the whole tree gives the answer.
        word = parts[0]["gives"]
        for a in range(len(word)):
            for b in range(a + 2, len(word) + 1):
                seg = word[a:b]
                if seg != seg[::-1] and (a, b) != (0, len(word)):
                    new, t = fresh()
                    t.clear()
                    t.update({"op": "substitution", "indicators": n["indicators"],
                              "parts": [copy.deepcopy(parts[0]), {"gives": seg}, {"gives": seg[::-1]}]})
                    out.append(new)
    elif n.get("op") in ("first", "last"):
        # the wrong end of the word: 'side of grass' for SWORDPLAY takes the last letter, not the first
        new, t = fresh()
        t["op"] = "last" if n["op"] == "first" else "first"
        out.append(new)
    elif n.get("op") == "hidden" and len(parts) == 1 and leaf(parts[0]) and clue:
        out += _hidden_reaches(fresh, parts[0], clue)
    elif n.get("op") == "hidden" and len(parts) == 1 and parts[0].get("op") == "charade":
        # hid() takes one leaf: a hidden word across words is the `+` list's leaves as one leaf
        merged = W.merge_hidden_leaves(parts[0].get("parts") or [])
        if merged and (not clue or _printed_run(merged["words"], clue)):
            new, t = fresh()
            t["parts"] = [merged]
            out.append(new)
    if n.get("op") == "hidden" and len(parts) == 1 and parts[0].get("op") == "reversal":
        # a word hidden backwards: hid() takes the leaf, the reversal goes round the hidden word
        # (hid(rev(words)) -> rev(hid(words)), each op keeping its own indicator)
        new, t = fresh()
        rv = t["parts"][0]
        kids = rv.get("parts") or []
        if len(kids) == 1 and kids[0].get("op") == "charade" and not kids[0].get("indicators"):
            kids = kids[0].get("parts") or []
        kid = W.merge_hidden_leaves(kids) if len(kids) > 1 else (kids[0] if kids else None)
        if kid and "op" not in kid and "gives" not in kid:
            t.clear()
            t.update({**rv, "parts": [{**n, "parts": [kid]}]})
            out.append(new)
    if n.get("op") == "anagram" and clue:
        out += _anagram_fodder_edits(fresh, n, clue)
    if n.get("op") == "charade" and len(parts) >= 2 and len(n.get("indicators") or []) == 1:
        # '[Fine]F +<across> [beer]ALE + [the south]S' for FALSE: the charade's own indicator is the
        # container word of two neighbours, one inside the other (either way round)
        for i in range(len(parts) - 1):
            for outer, inner in ((i, i + 1), (i + 1, i)):
                new, t = fresh()
                box = {"op": "container", "indicators": t.pop("indicators"),
                       "parts": [t["parts"][outer], t["parts"][inner]]}
                t["parts"][i:i + 2] = [box]
                if len(t["parts"]) == 1:
                    only = t["parts"][0]
                    t.clear()
                    t.update(only)
                out.append(new)
    if n.get("op") == "charade" and len(parts) >= 2 and not n.get("indicators") and clue:
        # a charade that is really a container, no indicator of its own (UGLY = U[G]LY: 'U + LY' with 'grabbing'
        # left over): one neighbouring pair written as a container, the indicator the ONE clue word no leaf or
        # indicator claims that the table lists as a container word. evaluate() then keeps it only when exactly
        # one arrangement of the pieces gives the answer.
        word = _lone_container_word(node, clue)
        if word:
            for i in range(len(parts) - 1):
                for outer, inner in ((i, i + 1), (i + 1, i)):
                    new, t = fresh()
                    box = {"op": "container", "indicators": [{"text": word, "note": f"'{word}' puts one piece inside the other"}],
                           "parts": [t["parts"][outer], t["parts"][inner]]}
                    t["parts"][i:i + 2] = [box]
                    if len(t["parts"]) == 1:
                        only = t["parts"][0]
                        t.clear()
                        t.update(only)
                    out.append(new)
    if leaf(n) and re.search(r"['’]s$", str(n.get("words") or "")) and str(n.get("gives") or "").isalpha() \
            and len(n["gives"]) > 3 and n["gives"].upper().endswith("S"):
        # the possessive spelt out ('hostel's' is INN, not INNS)
        new, t = fresh()
        t["gives"] = t["gives"][:-1]
        out.append(new)
    if leaf(n) and re.search(r"['’]s$", str(n.get("words") or "")) and str(n.get("gives") or "").isalpha() \
            and not n["gives"].upper().endswith("S"):
        # the possessive's S as a letter ('Revolutionary's' is CHES, not CHE): the S the join is missing
        new, t = fresh()
        t["gives"] = t["gives"] + "S"
        out.append(new)
    if leaf(n) and str(n.get("gives") or "").isalpha() and len(n["gives"]) > 3 and n["gives"].upper().endswith("S") \
            and not re.search(r"['’]s$", str(n.get("words") or "")):
        # a plural S the answer does not have at a join (YARDS + SHIFT for GRAVEYARDSHIFT, OVERS + SEE for
        # OVERSEE): the leaf's trailing S cut; evaluate() keeps it only when no other edit gives the answer
        new, t = fresh()
        t["gives"] = t["gives"][:-1]
        out.append(new)
    if n.get("op") == "charade" and len(parts) >= 2:
        # a piece the answer does not need ([dense]D after LARD in DULLARD: the definition word filed as a
        # leaf): a plain leaf cut, its clue word left to the definition or as a link word
        for i, p in enumerate(parts):
            if "op" in p or not p.get("words") or (k == 0 and len(parts) == 2 and "op" not in parts[1 - i]):
                continue
            new, t = fresh()
            del t["parts"][i]
            if len(t["parts"]) == 1:
                only = t["parts"][0]
                t.clear()
                t.update(only)
            out.append(new)
    return [_flat_charades(new) for new in out]


def _lone_container_word(node, clue):
    """The one clue word that no leaf or indicator of the tree claims and the indicator table lists as a
    container word (at least 20 uses, 70% of them container); None when there is none or more than one."""
    toks = lambda t: re.findall(r"[\w']+", str(t).lower().replace("’", "'"))
    claimed = collections.Counter()
    for x, _ in walk(node):
        claimed.update(toks(x.get("words") or ""))
        for i in x.get("indicators") or []:
            claimed.update(toks(i.get("text") or ""))
    left = []
    for w in toks(clue):
        if claimed[w] > 0:
            claimed[w] -= 1
        else:
            left.append(w)
    hits = []
    for w in left:
        counts = V._role_counts(V.indicator_role_key(w))
        total = sum(counts.values())
        if total >= 20 and counts.get("container", 0) >= 0.7 * total:
            hits.append(w)
    return hits[0] if len(hits) == 1 else None


def _anagram_fodder_edits(fresh, n, clue):
    """Single edits to an anagram whose fodder letters are off by whole clue words (the evaluator says the
    fodder 'has ADN to spare' or 'lacks IS'): a link word inside a fodder leaf ('gale and waves') cut out,
    leaving two leaves; the first or last word of the indicator ('is affected' after 'A poet') read as
    fodder, the leaf growing by it; a possessive 's ('Croatian's') spelt out. evaluate() then keeps only the edit
    that gives the answer, and only when no other does."""
    out = []
    parts = n.get("parts") or []
    for j, lf in enumerate(parts):
        if "op" in lf or lf.get("gives") or not lf.get("words"):
            continue
        ws = str(lf["words"]).split()
        for i in range(len(ws)):
            if len(ws) >= 3 and 0 < i < len(ws) - 1:
                new, t = fresh()
                a, b = dict(t["parts"][j], words=" ".join(ws[:i])), dict(t["parts"][j], words=" ".join(ws[i + 1:]))
                t["parts"][j:j + 1] = [a, b]
                out.append(new)
        if re.search(r"['’]s$", str(lf["words"])):
            letters = re.sub(r"[^A-Za-z]", "", re.sub(r"['’]s$", "", str(lf["words"]))).upper()
            if letters:
                new, t = fresh()
                t["parts"][j]["gives"] = letters
                out.append(new)
    for ind_i, ind in enumerate(n.get("indicators") or []):
        iw = str(ind.get("text") or "").split()
        if len(iw) < 2:
            continue
        for j, lf in enumerate(parts):
            if "op" in lf or lf.get("gives") or not lf.get("words"):
                continue
            for take, grown, rest in (
                    (iw[0], f"{lf['words']} {iw[0]}", " ".join(iw[1:])),
                    (iw[-1], f"{iw[-1]} {lf['words']}", " ".join(iw[:-1]))):
                if _printed_run(grown, clue):
                    new, t = fresh()
                    t["parts"][j]["words"] = grown
                    t["indicators"][ind_i]["text"] = rest
                    out.append(new)
    return out


def _printed_run(words, clue):
    """True when the clue prints `words` as one run (case and punctuation aside)."""
    norm = lambda t: " ".join(re.findall(r"[\w']+", str(t).lower().replace("’", "'")))
    return f" {norm(words)} " in f" {norm(clue)} "


def _hidden_reaches(fresh, lf, clue):
    """A hidden word whose fodder stops short of the clue word it starts in ('In print as Sordello'
    hides TASSO in print + as + Sordello): the leaf reaches one clue word further left or right, and the
    indicator gives that word up."""
    out = []
    at = lf.get("at")
    if at is None:
        return out
    words = [(m.start(), m.end()) for m in re.finditer(r"[\w'’]+", clue)]
    for side in ("left", "right"):
        new, t = fresh()
        h = next(x for x, _ in walk(new) if x.get("op") == "hidden")
        l = h["parts"][0]
        if side == "left":
            prev = [w for w in words if w[1] <= at]
            if not prev:
                continue
            a, b = prev[-1][0], at + len(l["words"])
            hit = [i for i in h.get("indicators") or [] if clue[a:prev[-1][1]].lower() == str(i.get("text", "")).split()[-1:][0].lower()]
        else:
            nxt = [w for w in words if w[0] >= at + len(l["words"])]
            if not nxt:
                continue
            a, b = at, nxt[0][1]
            hit = [i for i in h.get("indicators") or [] if clue[nxt[0][0]:nxt[0][1]].lower() == str(i.get("text", "")).split()[0].lower()]
        if len(hit) != 1 or len(str(hit[0]["text"]).split()) < 2:
            continue
        ind = hit[0]
        ind["text"] = " ".join(str(ind["text"]).split()[:-1] if side == "left" else str(ind["text"]).split()[1:])
        if side == "right" and "at" in ind:
            ind["at"] = ind["at"] + len(clue[ind["at"]:].split()[0]) + 1
        l["words"], l["at"] = clue[a:b], a
        l.pop("gives", None)
        out.append(new)
    return out


def _flat_charades(tree):
    """A charade with no indicator inside another with none is spliced into it (a + (b + c) is a + b + c)."""
    for n, _p in reversed(list(walk(tree))):
        if n.get("op") == "charade" and not n.get("indicators"):
            kids = []
            for p in n.get("parts") or []:
                same = isinstance(p, dict) and p.get("op") == "charade" and not p.get("indicators")
                kids += p["parts"] if same else [p]
            n["parts"] = kids
    return tree


def r_doubled_apostrophe(node, parent, ctx):
    """doubledApostrophe: Guardian''s in a leaf's words or an indicator's text becomes Guardian's. Whole tree
    only, and only when the clue itself holds the single apostrophe form (a clue still doubled is mended with
    its annotation by fix_doubled_apostrophes, so the words keep matching it)."""
    if parent is not None or not V.doubled_apostrophe(node) or V.DOUBLED_APOSTROPHE_RE.search(ctx.get("clue") or ""):
        return None
    new = copy.deepcopy(node)
    fix = lambda t: V.DOUBLED_APOSTROPHE_RE.sub("'", t)
    for n in V._walk(new):
        if isinstance(n.get("words"), str):
            n["words"] = fix(n["words"])
        for i in n.get("indicators") or []:
            if isinstance(i, dict) and isinstance(i.get("text"), str):
                i["text"] = fix(i["text"])
    return new


def _single_apostrophe(text):
    """rewrite_entry mapper: every apostrophe pair between letters becomes one, offsets kept on their letters."""
    out, at, i = [], [], 0
    while i < len(text):
        at.append(len(out))
        if text.startswith("''", i) and i and text[i - 1].isalnum() and i + 2 < len(text) and text[i + 2].isalnum():
            at.append(len(out))
            out.append("'")
            i += 2
            continue
        out.append(text[i])
        i += 1
    at.append(len(out))
    return "".join(out), at


def fix_doubled_apostrophes(entry):
    """Mend one entry in place: the clue text through enumeration.rewrite_entry (which carries the definition
    offsets and the quoted annotation strings with it), then the tree's leftovers. Whether anything changed."""
    import enumeration
    changed = enumeration.rewrite_entry(entry, _single_apostrophe)
    wp = (entry.get("annotation") or {}).get("wordplay")
    if isinstance(wp, dict) and V.doubled_apostrophe(wp):
        entry["annotation"]["wordplay"] = r_doubled_apostrophe(wp, None, {"clue": (entry.get("clue") or {}).get("text")})
        changed = True
    return changed


def run_doubled_apostrophes(apply, root="puzzles"):
    """The corpus sweep (--doubled-apostrophes): every puzzle file with `''` between letters in a clue, written
    through a .part rename when `apply`. Prints the clues and puzzles mended."""
    import pathlib
    clues = files = 0
    for p in sorted(pathlib.Path(root).glob("*/*/*.json")):
        raw = p.read_text()
        if "''" not in raw:
            continue
        puzzle = json.loads(raw)
        n = sum(fix_doubled_apostrophes(e) for e in puzzle.get("entries", []))
        if not n:
            continue
        clues, files = clues + n, files + 1
        if apply:
            part = p.with_name(f".{p.name}.part")
            part.write_text(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n")
            part.replace(p)
    print(f"{'mended' if apply else 'would mend'} {clues} clues in {files} puzzles")


def note_deletions(tree):
    """A deletion indicator a repair made new (the leaf fold's) has no note, and every annotation
    needs one: say what the word does (so does a selection's, made new by sel_edge/leaf_select)."""
    for n, _ in walk(tree):
        say = "takes the cut letters out of the word" if n.get("op") == "deletion" \
            else f"the {n['op']} letter of the word it picks from" if n.get("op") in ("first", "last", "middle") else None
        for i in (n.get("indicators") or []) if say else []:
            i.setdefault("note", say)
    return tree
