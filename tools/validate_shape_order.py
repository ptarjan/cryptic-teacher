"""Wordplay-tree shape detectors of validate_annotations.py, part 4: moved letters, traded and double indicators, pool gaps, charade order.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import copy
import itertools
import re
import wordplay

from validate_shape_base import _walk, _OP_LEXICON, indicator_role_key, _role_counts, CUT_WORDS
from validate_shape_folds import ROLE_MIN_USES, _lacks_role
from validate_shape_inside import _DEL_END, _DEL_HEAD

#: The ops a single indicator word signals one of: one indicator per op (Paul, 10-18: "Beginning is
#: one indicator and end is another"). Two indicators on one of these is two ops filed as one.
_ONE_IND_OPS = frozenset({"reversal", "deletion", "hidden"}) | frozenset(wordplay.SELECT)
DELETION_SCOPE_ANSWER = "deletion over a charade whose indicator names an end, but the letters that make the answer are not at it"
DOUBLE_INDICATOR = "one op carries two indicators, or stacks two ops on one"
MOVED_LETTER = "a letter taken out by a deletion and put back by a sibling leaf is a move, not an add-then-delete"


def moved_letters(tree):
    """Deletions whose removed letters a sibling leaf of the same parent gives again (Paul, round 15:
    ALBINO = del<dropping>(ALBION, O) + [ball]O is an error; the tree is move<dropping>(ALBION, O)).
    Counts a deletion once per tree place; a removed part that is a leaf with letters, a sibling that is
    a leaf with the same letters."""
    n = 0
    for parent in _walk(tree):
        kids = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        for d in kids:
            ps = [p for p in d.get("parts") or [] if isinstance(p, dict)]
            if d.get("op") != "deletion" or d.get("unchecked") or len(ps) != 2 or "op" in ps[1]:
                continue
            cut = wordplay.letters(ps[1].get("gives"))
            # A plain truncation beside a leaf of the same letter is a coincidence, as in
            # _sibling_gives (cryptic-30087 11a: [Old]O + ... + del<without finishing>([too]ALSO, O)).
            n += bool(cut) and ((not _plain_cut(d) and any(
                "op" not in k and k is not d and wordplay.letters(k.get("gives")) == cut
                for k in kids)) or bool(_sibling_gives(kids, d, ps[1])))
        n += _leaf_cut_put_back(kids)
    return n


def _plain_cut(d):
    """Whether the deletion `d`'s indicator is a plain truncation (endless, without finishing)."""
    said = " ".join(str(i.get("text") or "") for i in d.get("indicators") or [] if isinstance(i, dict))
    return bool(_DEL_END.search(said) or _DEL_HEAD.search(said)
                or re.search(r"\b(?:losing|largely|mostly|most of|made|less)\b", said, re.I))


def _sibling_gives(kids, d, cut_part):
    """1 when a sibling first/last pick gives the letters the deletion `d` removes (r30 FN SHAH:
    del<advancing>(HASH, S) beside last<finally>(enemies)): the same move, one letter taken out and put back."""
    if _plain_cut(d):
        return 0  # r31 judged: a plain truncation indicator beside a pick of the same letter is a coincidence (9 of 40 fine)
    try:
        cut = wordplay.values(cut_part)
        return int(any(k.get("op") in ("first", "last", "nth") and not k.get("unchecked") and wordplay.values(k) & cut
                       for k in kids if k is not d))
    except Exception:
        return 0


_LEAF_CUT_NOTE = re.compile(r"\b(?:without|minus|losing|lacking|dropping|missing)\b", re.I)


def _leaf_cut_put_back(kids):
    """1 when a leaf's note says its word is a longer one without a letter (EDGE, "LEDGE ... without its front
    letter") and a sibling leaf gives that letter again (L; r30 FN EDGETOOL): a move, not a cut and an add."""
    for a in kids:
        if "op" in a or a.get("unchecked") or not _LEAF_CUT_NOTE.search(str(a.get("note") or "")):
            continue
        g = wordplay.letters(a.get("gives"))
        for w in re.findall(r"\b[A-Z]{3,}\b", str(a.get("note"))):
            gone = [wordplay.letters(b.get("gives")) for b in kids if b is not a and "op" not in b]
            if len(w) == len(g) + 1 and any(len(x) == 1 and sorted(w) == sorted(g + x) for x in gone if x):
                return 1
    return 0


def _ind_adjacent(a, b):
    """Whether two indicators with known places touch in the clue: the two halves of one phrase."""
    if not all(isinstance(i.get("at"), int) for i in (a, b)):
        return False
    lo, hi = sorted((a, b), key=lambda i: i["at"])
    return 0 <= hi["at"] - (lo["at"] + len(str(lo.get("text") or ""))) <= 1


_OWN_DELETION_WORD = re.compile(r"\w+less\b|\b(without|minus|lacking|dropping|losing|missing)\b", re.I)


def _own_word(op, text):
    """Whether indicator `text` is, on its own, a word of `op`'s type: the corpus files it there
    in at least half of 5+ uses, or (a deletion) it says "-less"/"without". The two halves of one
    phrase around the fodder (Bring ... back, Half of ... is forgotten, less ... on top) are not:
    one half is a selection's or a bare verb, so two own words are two ops."""
    counts = _role_counts(indicator_role_key(text))
    total = sum(counts.values())
    if total >= 5:
        return counts.get(_OP_LEXICON[op], 0) >= 0.5 * total
    return op == "deletion" and bool(_OWN_DELETION_WORD.search(str(text or "").lstrip("'\u2019")))


TRADED_INDICATOR = "two ops each carry the other's indicator word, or a hidden word carries a reversal's word"


def traded_indicators(tree):
    """Indicators that trade places (round 19, listed miss REALALES: rev<about>(ins<knocking back>), where
    "about" is 78% container and "knocking back" 91% reversal; ADORE: rev<masks>(hid<up>), "up" being 93%
    reversal and a hidden word's indicator under 1%). Counts the indicators of a checked op whose word the
    corpus files, in 20+ uses, 75%+ under another op's type and at most 20% under this one's, when a second op
    carries the first's type's word the same way; or, for a hidden word
    carrying a near-reversal word (90%+, under 2% hidden), when the tree's reversal has no indicator the
    corpus knows for a reversal."""
    nodes = [n for n in _walk(tree) if _OP_LEXICON.get(n.get("op")) and not n.get("unchecked") and n.get("indicators")]
    found = []  # (node id, own type, other type, strict)
    for node in nodes:
        own = _OP_LEXICON[node["op"]]
        for i in node["indicators"]:
            counts = _role_counts(indicator_role_key(i.get("text")))
            total = sum(counts.values())
            if total < ROLE_MIN_USES:
                continue
            top = max(counts, key=counts.get)
            if top == own:
                continue
            if counts[top] >= 0.75 * total and counts.get(own, 0) <= 0.2 * total:
                found.append((id(node), own, top, False))
            if counts[top] >= 0.9 * total and counts.get(own, 0) <= 0.02 * total:
                found.append((id(node), own, top, True))
    mutual = {a for a in found if any(b[0] != a[0] and b[1] == a[2] and b[2] == a[1] for b in found)}
    hid = {a for a in found if a[3] and a[1] == "hidden_word" and a[2] == "reversal" and any(
        _OP_LEXICON[o["op"]] == "reversal" and _lacks_role(o, "reversal") for o in nodes)}
    return len({(a[0], a[1]) for a in mutual | hid})


def double_indicators(tree):
    """Reversals, deletions, hidden words and selections that file two indicators (cryptic-29317
    6d NEEDIER rev<turned up><elevated>: two reversals; independent-12251 2d IRON
    del<'eadless><without an aitch>: two deletions), and a hidden word over a selection that has no
    indicator of its own (times-16960 6d EARL hid<inside>(mid(pearly)): one word, two ops). Two
    indicators that touch in the clue are one phrase cut in two and are left."""
    n = 0
    for node in _walk(tree):
        op = node.get("op")
        if op not in _ONE_IND_OPS:
            continue
        ins = [i for i in node.get("indicators") or [] if isinstance(i, dict)]
        if len(ins) >= 2 and not all(_ind_adjacent(ins[k], ins[k + 1]) for k in range(len(ins) - 1)) \
                and sum(_own_word(op, i.get("text")) for i in ins) >= 2:
            n += 1
        elif op == "hidden" and not ins:
            continue
        elif op == "hidden" and any(isinstance(p, dict) and p.get("op") in wordplay.SELECT
                                    and not p.get("indicators") for p in node.get("parts") or []):
            n += 1
    return n


def _subtree_spans(node, clue, low):
    """[(start, end)] of every leaf and indicator under `node`, by its `at` or else where its words
    first occur in the clue; a piece the clue does not show is left out."""
    out = []
    for m in _walk(node):
        items = [(m.get("words"), m.get("at"))] if "words" in m else []
        items += [(i.get("text"), i.get("at")) for i in m.get("indicators") or [] if isinstance(i, dict)]
        for text, at in items:
            text = str(text or "")
            if not text:
                continue
            at = at if isinstance(at, int) else low.find(text.lower())
            if at >= 0:
                out.append((at, at + len(text)))
    return out


POOL_GAP = "anagram fodder with another op's words between its pieces"


def pool_gaps(tree, clue):
    """Anagrams of 2+ fodder pieces with a leaf or indicator of some other op sitting in the clue
    between the pieces: the pool is read off words the anagram does not gather (ftcryptic-18053 2d
    AMERICANPIE ana<tangled>(in camera, P): "pressure" is far past "that is opened by", and P goes
    before IE; cryptic-29127 27a, cyclops-409 12a). The anagram's own indicator may stand between."""
    if not clue:
        return 0
    low = clue.lower()
    try:    # stored trees carry no offsets: place every span as view() does, or "a" is found inside "Jars"
        tree = wordplay.locate(copy.deepcopy(tree), clue)
    except Exception:
        pass
    n = 0
    for node in _walk(tree):
        parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "anagram" or len(parts) < 2 or node.get("unchecked"):
            continue
        spans = [_subtree_spans(p, clue, low) for p in parts]
        spans = [(min(a for a, _ in s), max(b for _, b in s)) for s in spans if s]
        if len(spans) < 2:
            continue
        lo, hi = min(a for a, _ in spans), max(b for _, b in spans)
        mine = {id(m) for m in _walk(node)}
        gap = False
        for m in _walk(tree):
            if id(m) in mine:
                continue
            if "op" in m and any(q is node for q in _walk(m)):
                continue  # round 17, kept in 18: an enclosing op's indicator ("keeps ... in", "when framing") may stand between the pieces
            for x, y in _subtree_spans({"words": m["words"], "at": m.get("at")} if "words" in m and "op" not in m
                                       else {"indicators": m.get("indicators")}, clue, low):
                if lo < x and y < hi and not any(a <= x and y <= b for a, b in spans):
                    gap = True
        n += gap
    return n


def _located(tree, clue):
    """`tree` with every span placed in `clue` (a stored tree carries no offsets); as filed on a failure."""
    try:
        return wordplay.locate(copy.deepcopy(tree), clue)
    except Exception:
        return tree


def _extent(node, clue, low):
    """(start, end) of everything under `node` in the clue, or None when the clue shows none of it."""
    spans = _subtree_spans(node, clue, low)
    return (min(a for a, _ in spans), max(b for _, b in spans)) if spans else None


CHARADE_ORDER = "charade whose pieces sit in the clue in another order than it joins them"
#: Words that let a charade's pieces come out in a different order than the clue gives them.
ORDER_FLIPPERS = re.compile(
    r"\b(after|before|behind|following|follows?|followers?|followed|below|beneath|under|above|atop|ahead|preceding|"
    r"precedes|preceded|leading|leads?|leaders?|goes|going|put|puts|coming|comes?|by|in|inside|within|provided|"
    r"to the|at the end|at end|end of|start of|on|over|supporting|heading|heads|tops|capping|beyond|past|"
    r"at the back|at the front|then|next|and then|finally|ending|finishing|starting|opening)\b", re.I)


def charade_out_of_order(tree, clue):
    """Charades with no indicator whose pieces are joined in another order than the clue gives them,
    and no word between them to say so (ftcryptic DODGE "Duke flipped for one party": DO + D + EG
    reversed, where the clue's order is D, EG, DO; SPIRE, PARADIDDLE). Round 22: 6 of 38 judged misses."""
    if not clue:
        return 0
    low = clue.lower()
    tree = _located(tree, clue)
    n = 0
    for node in _walk(tree):
        if node.get("op") != "charade" or node.get("indicators"):
            continue
        spans = [s for p in node.get("parts") or [] if isinstance(p, dict) and (s := _extent(p, clue, low))]
        if len(spans) < 2 or all(spans[i + 1][0] >= spans[i][0] for i in range(len(spans) - 1)):
            continue
        if not ORDER_FLIPPERS.search(clue[min(a for a, _ in spans):max(b for _, b in spans)]):
            n += 1
    return n


_ORDER_NEXT = re.compile(r"\s+(?:before|after|behind|following|ahead of)\b")
REVERSAL_SPLIT = "reversal whose indicator sits between two of the pieces it reverses"


def _whole_reversal_needed(node):
    """True when the reversal turns a run of pieces together and no other tree can give its letters: the
    answer is the whole run backwards (CRANIAL = rev<back>(LAIN + ARC)), and reversing just one piece, the
    others kept forwards in any order, spells something else. Then the one indicator rightly turns every
    piece, wherever it stands among them. Undecidable (a piece without letters) counts as not needed."""
    kids = [p for p in node.get("parts") or [] if isinstance(p, dict)]
    if len(kids) == 1 and kids[0].get("op") == "charade" and not kids[0].get("indicators"):
        kids = [p for p in kids[0].get("parts") or [] if isinstance(p, dict)]
    pieces = [wordplay.letters(p.get("gives")) for p in kids]
    if len(pieces) < 2 or len(pieces) > 5 or not all(pieces):
        return False
    target = "".join(pieces)[::-1]
    for i in range(len(pieces)):
        for order in itertools.permutations(range(len(pieces))):
            if "".join(pieces[k][::-1] if k == i else pieces[k] for k in order) == target:
                return False
    return True


def reversal_split(tree, clue):
    """Reversals over several pieces with their indicator word standing between those pieces in the clue:
    the indicator acts on the piece beside it (mephisto DEGAS "editor repelled with flatulence" reverses
    ED alone; LILAC, NOTHALF, ELAPSES). Round 22: 5 of 38 judged misses.

    Not counted: a reversal over a two-leaf charade (no op, no indicator) whose indicator is followed at
    once by an order word ("We will be rising before four", everyman-3872 4d VIEW: rev(WE + IV)): the
    word after "rising" orders the two pieces, so the indicator turns the pair, and turning one piece
    cannot give the answer (EW+IV, WE+VI)."""
    if not clue:
        return 0
    low = clue.lower()
    tree = _located(tree, clue)
    n = 0
    for node in _walk(tree):
        if node.get("op") != "reversal" or node.get("unchecked"):
            continue
        if any(m.get("op") in ("hidden", "alternate", "deletion") for m in _walk(node) if m is not node):
            continue  # round 22c: 12 of 14 judged-fine hits reversed a hidden, alternate-letters or deletion result, one stretch of the clue
        if _whole_reversal_needed(node):
            continue  # the one indicator turns every piece: no single-piece reversal gives the answer
        kids = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if len(kids) == 1 and (kids[0].get("op") in wordplay.SELECT or kids[0].get("op") == "substitution"):
            continue  # r42 judged: a reversal of one pick or substitution (rev<up>(middle<>(Bottoms))) is one piece, 2 of 4 fine, 0 of 38 errors
        spans = [s for p in node.get("parts") or [] if isinstance(p, dict) and (s := _extent(p, clue, low))]
        if not spans:
            continue
        lo, hi = min(a for a, _ in spans), max(b for _, b in spans)
        pair = len(kids) == 1 and kids[0].get("op") == "charade" and not kids[0].get("indicators") \
            and len(kids[0].get("parts") or []) == 2 and not any("op" in q for q in kids[0]["parts"] if isinstance(q, dict))
        for ind in node.get("indicators") or []:
            text = str(ind.get("text") or "") if isinstance(ind, dict) else ""
            at = ind.get("at") if isinstance(ind.get("at"), int) else low.find(text.lower())
            if pair and text and at >= 0 and _ORDER_NEXT.match(low[at + len(text):]):
                continue
            if text and at >= 0 and lo < at and at + len(text) < hi:
                n += 1
                break
    return n


REVERSED_CHARADE_ORDER = "reversal over a charade whose pieces sit in the clue in another order than it joins them"


def reversed_charade_order(tree, clue):
    """A reversal over a charade (no indicators of its own) whose pieces stand in the clue in another
    order than the charade lists them, with no word between them to say so: the parse reversed the whole
    to put the answer right, so a piece sits backwards in the walkthrough (independent-12387 SURFEIT
    "Use a browser link, looking up" filed as rev(TIE + FRUS), when SURF stays and only TIE turns).
    The indicator turns the piece beside it; the others stay forwards, in the clue's order."""
    if not clue:
        return 0
    low = clue.lower()
    tree = _located(tree, clue)
    n = 0
    for node in _walk(tree):
        kids = node.get("parts") or []
        if node.get("op") != "reversal" or node.get("unchecked") or len(kids) != 1:
            continue
        ch = kids[0]
        if not isinstance(ch, dict) or ch.get("op") != "charade" or ch.get("indicators") or ch.get("unchecked"):
            continue
        pieces = [p for p in ch.get("parts") or [] if isinstance(p, dict)]
        spans = [_extent(p, clue, low) for p in pieces]
        if len(pieces) < 2 or not all(spans):
            continue
        if all(spans[i + 1][0] >= spans[i][0] for i in range(len(spans) - 1)):
            continue
        if not ORDER_FLIPPERS.search(clue[min(a for a, _ in spans):max(b for _, b in spans)]):
            n += 1
    return n


CUT_IN_LEAF = "leaf opens with a cut word (short, half, first) and gives fewer letters than its other words"


CUT_SUFFIXED = frozenset("endless headless topless beheaded curtailed cut clipped docked reduced".split())


def _cut_phrase(words):
    """Whether a leaf's opening words say a cut rather than name a thing: a cut word followed by "of"
    ("half of", "first part of"), a "-less"/clipped word, or "half" that is no half-dozen."""
    for i, w in enumerate(words[:2]):
        if w not in CUT_WORDS:
            continue
        if w in CUT_SUFFIXED or "of" in words[i + 1:i + 4]:
            return True
        if w == "half" and "dozen" not in words and words[i + 1:i + 2] != ["a"]:
            return True
    return False


def cut_in_leaf(tree, clue=None):
    """Leaves whose first words are a cut indicator ("short contract" giving DEA, "your lower half" giving UR,
    "First of branches" giving BRANCHES) that give fewer letters than the words after it: the cut is an op.
    Round 22: 3 of 38 judged misses."""
    n = 0
    for node in _walk(tree):
        if "words" not in node or "op" in node or node.get("unchecked") or not node.get("gives"):
            continue
        words = re.findall(r"[a-z']+", str(node["words"]).lower())
        if len(words) < 2 or words[0] not in CUT_WORDS | {"your", "a", "the"} or not any(w in CUT_WORDS for w in words[:2]):
            continue
        if not _cut_phrase(words):
            continue  # round 22c: "short film", "last month", "half-dozen" are synonyms (14 of 40 judged hits fine); "half of", "endless", "first part of" are cuts
        if len(re.sub(r"[^A-Z]", "", str(node["gives"]))) < sum(len(w) for w in words[1:]):
            n += 1
    return n