"""Wordplay-tree shape detectors of validate_annotations.py, part 1: unindicated ops, arity, span overlap, unchecked steps, leaf checks.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import collections
import copy
import json
import re
import wordplay
import annotation

from validate_shape_base import _walk, _OP_LEXICON, REPEAT_WORDS, _POSITION_WORD, _owner_type

UNCHECKED_STEP = "unchecked wordplay step"
#: The finding for a charade filed directly under an anagram. An anagram's
#: fodder is one pool of letters, so its pieces are the anagram's own parts
#: (`ana(x + y)` stores x and y there): nothing under it is joined in order, and
#: a charade label there says something that is not happening. wordplay.parse
#: cannot write one; the ratchet (wordplay.anagramCharade) lets a puzzle keep
#: the ones tools/flatten_anagram_fodder.py could not flatten as they stand
#: (a join with an indicator of its own, or an unchecked one), and no more.
ANAGRAM_CHARADE = "charade directly under an anagram"


def _stand_in_piece(p):
    """A fodder piece that is not the clue's own words scrambled: an abbreviation or synonym
    leaf (a selection like first(x) is a common legitimate fodder letter, so not one)."""
    if "op" in p:
        return False
    g, w = wordplay.letters(p.get("gives")), wordplay.letters(p.get("words"))
    return bool(p.get("select") or p.get("soundsLike") or (g and g != w and sorted(g) != sorted(w)))


def _pulled_edges(tree, node, j, k):
    """A copy of `tree` with the first j and last k parts of anagram `node` taken out of it and
    set beside it in a charade (the answer's edge letters standing outside the scramble)."""
    t = copy.deepcopy(tree)
    stack = [(t, None, 0)]
    while stack:
        cur, par, i = stack.pop()
        if cur.get("op") == "anagram" and cur.get("parts") == node.get("parts") and cur.get("indicators") == node.get("indicators"):
            mid = {key: v for key, v in cur.items() if key != "parts"}
            mid["parts"] = cur["parts"][j:len(cur["parts"]) - k]
            new = {"op": "charade", "parts": cur["parts"][:j] + [mid] + cur["parts"][len(cur["parts"]) - k:]}
            if par is None:
                return new
            par["parts"][i] = new
            return t
        stack += [(p, cur, x) for x, p in enumerate(cur.get("parts") or []) if isinstance(p, dict)]
    return None


def anagram_edge_pieces(tree, answer, stand=_stand_in_piece):
    """How many anagrams in `tree` hold, at the edge of their own fodder (first or last parts, in
    clue order), abbreviation / synonym / sub-operation pieces whose letters stand at that edge of
    the scramble's output: the tree still gives the answer with those pieces taken out of the
    anagram and set beside it. (Paul 10-19: a letter correctly placed outside the anagram should
    not be in it.) Needs the answer."""
    if not answer or not isinstance(tree, dict):
        return 0
    try:
        wordplay.evaluate(copy.deepcopy(tree), answer)
    except Exception:
        return 0
    found, stack = 0, [tree]
    while stack:
        node = stack.pop()
        parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        stack += parts
        if node.get("op") != "anagram" or node.get("unchecked") or len(parts) < 2 or len(parts) != len(node.get("parts")):
            continue
        st = [stand(p) for p in parts]
        lead = next((i for i, s in enumerate(st) if not s), len(st))
        trail = next((i for i, s in enumerate(reversed(st)) if not s), len(st))
        if lead >= len(st):
            continue
        done = False
        for j in range(lead + 1):
            for k in range(trail + 1):
                if j + k and j + k < len(parts) and not done:
                    cand = _pulled_edges(tree, node, j, k)
                    try:
                        wordplay.evaluate(cand, answer)
                        done = True
                    except Exception:
                        pass
        found += done
    return found


def anagram_charades(tree, answer=None):
    """How many charades sit directly under an anagram anywhere in `tree`, plus (given the
    answer) how many anagrams fold an edge piece of the answer into their fodder."""
    n, stack = 0, [tree] if isinstance(tree, dict) else []
    while stack:
        node = stack.pop()
        parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") == "anagram":
            n += sum(p.get("op") == "charade" for p in parts)
        stack += parts
    return n + anagram_edge_pieces(tree, answer)
#: Wordplay tree shapes that parse() cannot write or that say something the clue
#: does not. Each is a finding with its own ratchet field (below): a puzzle keeps
#: the clues it already has (tools/tidy_wordplay_shapes.py rewrote every one that
#: could be rewritten without changing view(), and recorded the rest), and no more.
CHARADE_IN_CHARADE = "charade directly inside a charade"
NO_INDICATOR = "operation with no indicator"
CDEF_REPEAT = "cryptic definition with more than one leaf"
STORED_ARITY = "operation with the wrong number of parts"
SPAN_OVERLAP = "clue words claimed twice"
IN_DEFINITION = "wordplay words inside the definition"
LEAF_FOLD = "leaf gives a stretch of its own words"
REPEATED_SELECTION = "same letter selection repeated word by word"
SINGLE_LEAF = "wordplay that is one leaf"
BARE_IN_CHARADE = "answer letters with no clue words in a charade"
ANAGRAM_OF_CONTAINER = "anagram wrapped around a container"
#: The tools/shape_suspects.py detectors that were hand-measured precise (a sample of
#: 20 each was wrong in every case), now rules. They count what the checked rules above
#: skip: an `unchecked` step (filed before trees were checked) can hold any part count,
#: and a leaf may swallow its own indicator word. Each has its ratchet field.
ARITY_INS = "container with other than two parts"
ARITY_OTHER = "deletion, substitution, homophone or one-armed op with the wrong part count"
DEL_SINGLE = "deletion with one part, so what it removes is not stated"
IND_IN_LEAF = "indicator word also inside a leaf"
SCRAMBLED_LEAF = "leaf gives its clue words' letters out of order"
#: Ops that are signalled by an indicator word. A charade, a cryptic definition,
#: a rebus, a reverse clue and a palindrome of the whole answer are not.
NEEDS_INDICATOR = frozenset(wordplay.ARITY) - {"cryptic", "rebus", "reverse", "palindrome"}


#: Until this time (epoch seconds) a push and CI let through a puzzle's shape
#: findings that have no allowance yet, because a pusher on code from before the
#: rules writes them without seeing the rule, and cannot sync onto the new code
#: while its commits are refused. A run's own `annotate_check` still reports every
#: one as an error. Before it passes, `tools/tidy_wordplay_shapes.py <puzzles>
#: --write` records what the grace let in as allowances (it adds puzzles the
#: list lacks), and the same commit sets this to 0.
SHAPE_GRACE_UNTIL = 0
SHAPE_GRACE_FIELDS = ("wordplay.anagramCharade", "wordplay.charadeInCharade", "wordplay.noIndicator",
                      "wordplay.cdefRepeat", "wordplay.arity", "wordplay.spanOverlap",
                      "wordplay.inDefinition", "wordplay.leafFold", "wordplay.repeatedSelection",
                      "wordplay.singleLeaf", "wordplay.bareInCharade", "wordplay.anagramOfContainer",
                      "wordplay.arityIns", "wordplay.arityOther", "wordplay.delSingle", "wordplay.indInLeaf", "wordplay.scrambledLeaf",
                      "wordplay.indFolded", "wordplay.fakeParts", "wordplay.paddingLeaf",
                      "wordplay.ddMissesWordplay", "spelling.unsaid")


def whole_rebus(ann, clue):
    """True when a viewed annotation is a rebus of the whole clue (every
    letter and figure in it), which leaves no words to define the answer."""
    blocks = ann.get("blocks") or []
    return (ann.get("type") == ["rebus"] and len(blocks) == 1
            and wordplay._alnum(blocks[0].get("clueFragment")) == wordplay._alnum(clue))


def _stored_arity(op):
    """(fewest, most) parts a checked `op` node stores: a homophone or spoonerism
    keeps its spelling in `spelt` and a rebus or reverse clue its `reading`, not as a part,
    and an anagram's parts are its pool."""
    lo, hi = wordplay.ARITY.get(op, (2, 99))
    if op in ("homophone", "spoonerism", "rebus", "reverse"):
        lo, hi = lo - 1, hi - 1
    return (lo, 99) if op == "anagram" else (lo, hi)


def charade_in_charade(tree):
    """How many charades with no indicator sit directly inside another charade:
    a join of a join, which is the one charade written in pieces. Not under a
    charade with an indicator of its own ("A after B"): the order is stated
    there and each side is a group (independent-11509 19a, PF + ENIG after)."""
    n = 0
    for node in _walk(tree):
        if node.get("op") == "charade" and not node.get("unchecked") and not node.get("indicators"):
            n += sum(p.get("op") == "charade" and not p.get("indicators") and not p.get("unchecked")
                     and "gives" not in p for p in node.get("parts") or [] if isinstance(p, dict))
    return n


def _bare_shape(node):
    """`node` without its indicators and notes, all the way down: what makes two ops the same."""
    return {k: ([_bare_shape(p) if isinstance(p, dict) else p for p in v] if k == "parts" else v)
            for k, v in node.items() if k not in ("indicators", "note", "at")}


def _repeated_copies(tree):
    """ids of ops that repeat an earlier sibling exactly under a parent whose indicator is a
    repeat word (mephisto-3095 30a GRISGRIS: (ins<protected by>(GIS, R) + ins(GIS, R))<repeatedly>).
    The one indicator on the parent says the copy is made, so the copy needs none."""
    out = set()
    for parent in _walk(tree):
        if not any(set(re.findall(r"[a-z]+", str(i.get("text") or "").lower())) & REPEAT_WORDS
                   for i in parent.get("indicators") or []):
            continue
        seen = []
        for p in parent.get("parts") or []:
            if not isinstance(p, dict) or "op" not in p:
                continue
            shape = json.dumps(_bare_shape(p), sort_keys=True, default=str)
            if shape in seen:
                out.add(id(p))
            seen.append(shape)
    return out


_BOUNDARY_WORDS = re.compile(r"boundar|edge|border|extrem|outer|outside|limit|ends? of|fring|margin|perimeter", re.I)


def _moved_letter_ops(tree):
    """ids of ops one word of an indicator already covers (round 14 unindicatedBare flags): the
    substitution whose replacement is the replaced letters turned (UNITE, IT -> rev<turn>(IT)),
    and the first and last of one word as the two boundary letters ("to enter the boundaries of")."""
    out = set()
    for parent in _walk(tree):
        kids = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        # A letter taken out by a deletion and put back by the container (NERVE) is NOT accepted:
        # Paul ruled it an error, round 15 (a real move op is coming); it is flagged again.
        if parent.get("op") == "deletion" and any(_POSITION_WORD.search(str(i.get("text") or ""))
                                                  for i in parent.get("indicators") or []):
            # del<initially removed>(BALDER, first(bark)): the deletion's own words name the end it takes
            out.update(id(p) for p in kids[1:] if p.get("op") in ("first", "last") and not p.get("indicators"))
        if parent.get("op") == "container" and parent.get("indicators"):
            if any(_BOUNDARY_WORDS.search(str(i.get("text") or "")) for i in parent["indicators"]):
                for c in kids:
                    cs = [p for p in c.get("parts") or [] if isinstance(p, dict)]
                    if c.get("op") == "charade" and len(cs) == 2 and {p.get("op") for p in cs} == {"first", "last"} \
                            and len({json.dumps([(q.get("words"), q.get("at")) for q in p.get("parts") or []
                                                 if isinstance(q, dict)], default=str) for p in cs}) == 1:
                        out.update(id(p) for p in cs)
        if parent.get("op") == "substitution" and not parent.get("indicators") and len(kids) == 3:
            rep = kids[2]
            leaf = [p for p in rep.get("parts") or [] if isinstance(p, dict) and "op" not in p]
            if "op" in rep and rep.get("indicators") and len(leaf) == 1 and sorted(
                    wordplay.letters(leaf[0].get("gives"))) == sorted(wordplay.letters(kids[1].get("gives"))) != []:
                out.add(id(parent))
    return out


_SUBSTITUTE_WORD = re.compile(r"\b(usurp\w*|replac\w*|substitut\w*|supplant\w*|swap\w*|instead|displac\w*|ousting|"
                              r"ousts?|for|replaced by|exchang\w*)\b", re.I)
_CONTAINER_WORD = re.compile(r"\b(in|inside|within|case|around|about|round|holding|housing|boxing|framing|"
                             r"covering|wrapping|outside)\b", re.I)


def _self_signed_ops(tree):
    """ids of bare ops that a neighbour's words already sign (round 15, 8 of 12 judged-fine
    unindicatedBare flags): a deletion whose leaf marks the dropped letter with an apostrophe ('irsute,
    'orse), a deletion under a container whose indicator says one letter replaces another (ins<usurps>
    (del(ATTEST, S), MP)), an inner container that repeats the outer's letters under its one indicator
    (ins<bathing in>(ins(MIGHT, R), R)), and a container whose picked part carries "in case of"."""
    out = set()
    for parent in _walk(tree):
        kids = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        if parent.get("op") == "deletion" and kids and "op" not in kids[0] \
                and re.search(r"(?:^|\s)['’](?![sS]\b)\w", str(kids[0].get("words") or "")):
            out.add(id(parent))
        if parent.get("op") == "container" and kids:
            inds = " ".join(str(i.get("text") or "") for i in parent.get("indicators") or [])
            if kids[0].get("op") == "deletion" and _SUBSTITUTE_WORD.search(inds):
                out.add(id(kids[0]))
            if kids[0].get("op") == "container" and inds and len(kids) == 2 and "op" not in kids[1]:
                inner = [p for p in kids[0].get("parts") or [] if isinstance(p, dict)]
                if len(inner) == 2 and "op" not in inner[1] and wordplay.letters(inner[1].get("gives")) \
                        == wordplay.letters(kids[1].get("gives")) != "":
                    out.add(id(kids[0]))
            if not parent.get("indicators") and any(
                    k.get("op") in wordplay.SELECT and _CONTAINER_WORD.search(
                        " ".join(str(i.get("text") or "") for i in k.get("indicators") or [])) for k in kids):
                out.add(id(parent))
    return out


#: Letters of a holder's words that already say "holds / is held in": onboard, interpolar, inside, within.
_HOLDER_WORD = re.compile(r"^(?:onboard|inter|inside|within|inner)|(?:board|hold|holder)$")


def _self_holding_containers(tree):
    """ids of bare containers whose holder leaf says it holds (round 17, 14 of 97 sampled unindicatedBare
    flags judged fine): [Onboard]SS, [interpolar]SN (a holder of one or two letters from a short phrase),
    [Indeed]DEED (the holder's word is the indicator word plus the holder). The same word-is-both
    reading shared_indicators allows."""
    out = set()
    for node in _walk(tree):
        kids = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "container" or node.get("indicators") or len(kids) != 2 or "op" in kids[0]:
            continue
        w, g = wordplay.letters(kids[0].get("words")), wordplay.letters(kids[0].get("gives"))
        if not w or not g or w == g:
            continue
        nwords = len(str(kids[0].get("words") or "").split())
        rest = w[:len(w) - len(g)] if w.endswith(g) else (w[len(g):] if w.startswith(g) else "")
        w = w.lower()
        edge = bool(_HOLDER_WORD.search(w))
        if (len(g) <= 2 and nwords <= 2 and edge) or (nwords == 1 and rest and _CONTAINER_WORD.fullmatch(rest.lower())):
            out.add(id(node))
    return out


def _lone_implicit_op(tree):
    """ids of the only op in a tree that needs an indicator when no node of the tree carries one (round 17,
    35 of 51 sampled flags of this shape judged fine, 12 more unclear, 3 real): a bare homophone, hidden word,
    anagram or container whose clue states its signal inside a leaf's words or not at all (HEAR, IOTA,
    COARSEN, REMAINS). With other ops in the tree the same flag stays: there an indicator is misfiled or
    swapped (16 of 16 real). A lone bare deletion or pick stays flagged (the tests hold it)."""
    nodes = list(_walk(tree))
    ops = [n for n in nodes if n.get("op") in NEEDS_INDICATOR and not n.get("unchecked")]
    if len(ops) == 1 and ops[0].get("op") in ("homophone", "hidden", "anagram", "container") \
            and not any(n.get("indicators") for n in nodes):
        return {id(ops[0])}
    return set()


def _lone_bare_sound(tree):
    """ids of a bare homophone or hidden word that is the only bare op of its tree (round 17, 12 of 13 sampled
    flags of this shape judged fine, none of the real ones): the other ops carry their indicators, so no
    word of the clue is misfiled, and a sound or a hidden run is often left unsigned by the setter."""
    nodes = list(_walk(tree))
    bare = [n for n in nodes if n.get("op") in NEEDS_INDICATOR and not n.get("unchecked") and not n.get("indicators")]
    if len(bare) == 1 and bare[0].get("op") in ("homophone", "hidden") \
            and sum(1 for n in nodes if n.get("op") == bare[0]["op"]) == 1:  # a hidden word split in two stays flagged (TENOR)
        return {id(bare[0])}
    return set()


def _lone_bare_first(tree):
    """ids of the only bare op of a tree when it is a first-letter pick of one clue word that no other leaf uses
    (round 18, 218 DIRGE "includes Grangemouth", 269 OCEANUS "Upstart", 279 HER "Halpern": 3 of 3 judged fine, the
    two real ones had a word used twice or a phrase): the setter leaves a lone initial unsigned."""
    nodes = list(_walk(tree))
    bare = [n for n in nodes if n.get("op") in NEEDS_INDICATOR and not n.get("unchecked") and not n.get("indicators")]
    if len(bare) != 1 or bare[0].get("op") != "first" or any(n.get("op") == "charade" and n.get("indicators") for n in nodes) \
            or any(n is not bare[0] and n.get("op") in wordplay.SELECT for n in nodes):
        return set()  # an indicator filed on the charade, or a twin pick, is the swap or share the other rules look for
    words = _leaf_words(bare[0])
    if len(words) != 1 or len(str(next(q for q in _walk(bare[0]) if q.get("words")).get("words")).split()) != 1:
        return set()
    return {id(bare[0])} if sum(1 for q in nodes if "op" not in q and wordplay.letters(q.get("words")) == words[0]) == 1 else set()


def _leaf_words(node):
    return tuple(wordplay.letters(q.get("words")) for q in _walk(node) if "op" not in q and q.get("words"))


def _paired_ends(tree):
    """ids of a bare first/last/outer whose twin on the same words carries the indicator (round 18, 4 of 4
    sampled: "Either end of terrific" first<end of>/last, "either side of duff"): one phrase names both ends."""
    out = set()
    for parent in _walk(tree):
        group = {}
        for p in parent.get("parts") or []:
            if isinstance(p, dict) and p.get("op") in ("first", "last", "outer") and not p.get("unchecked"):
                group.setdefault(_leaf_words(p), []).append(p)
        for twins in group.values():
            both = any(_BOUNDARY_WORDS.search(str(i.get("text") or "")) or re.search(r"\bsides?\b", str(i.get("text") or ""))
                       for t in twins for i in t.get("indicators") or [])  # "start" / "outskirts" of two words is a swap (WASHBOWL)
            if len(twins) == 2 and both and sum(1 for t in twins if t.get("indicators")) == 1 and twins[0]["op"] != twins[1]["op"]:
                out.update(id(t) for t in twins if not t.get("indicators"))
    return out


def _indicator_inside_run(picks):
    """Whether every indicator of the picks stands between the first and last word of their leaves, as far as
    places are known (an indicator before the run, far from it, is VIOLA's: it signs the first pick alone)."""
    words = [q["at"] for p in picks for q in _walk(p) if "op" not in q and q.get("words") and isinstance(q.get("at"), int)]
    inds = [i["at"] for p in picks for i in p.get("indicators") or [] if isinstance(i.get("at"), int)]
    return not words or not inds or all(min(words) <= a <= max(words) for a in inds)


def _picks_with_indicator(tree):
    """ids of bare picks in a run of 3+ picks under one parent when one of them carries an indicator (round 18,
    "initially ... heading for" over five initials, "in successive locations" over nth letters): one phrase
    signs the whole run."""
    out = set()
    for parent in _walk(tree):
        picks = [p for p in parent.get("parts") or [] if isinstance(p, dict) and p.get("op") in wordplay.SELECT
                 and not p.get("unchecked")]
        if len(picks) >= 3 and any(p.get("indicators") for p in picks) and _indicator_inside_run(picks):
            out.update(id(p) for p in picks if not p.get("indicators"))
        sounds = [p for p in parent.get("parts") or [] if isinstance(p, dict) and p.get("op") == "homophone"
                  and not p.get("unchecked")]  # TWO BY FOUR: three sounds, one "Trumpet"
        if len(sounds) >= 3 and any(p.get("indicators") for p in sounds):
            out.update(id(p) for p in sounds if not p.get("indicators"))
    return out


def _outer_in_boundary_container(tree):
    """ids of a bare outer/first/last under a container whose indicator names the edges ("between fringes of"):
    the container's words pick the ends (round 18 SPADES)."""
    return {id(k) for n in _walk(tree) if n.get("op") == "container" and any(
        _BOUNDARY_WORDS.search(str(i.get("text") or "")) for i in n.get("indicators") or [])
        for k in n.get("parts") or [] if isinstance(k, dict) and k.get("op") in ("outer", "first", "last")
        and not k.get("indicators")}


def _chained_deletions(tree):
    """ids of bare deletions on the first-part chain under a deletion that has an indicator (round 17
    OPAL): del<Piss taken out of>(del(del(Pop Sails, P), I), S) - one indicator for the run of cuts."""
    out = set()
    for node in _walk(tree):
        if node.get("op") != "deletion" or not node.get("indicators"):
            continue
        cur = node
        while True:
            kids = [p for p in cur.get("parts") or [] if isinstance(p, dict)]
            if not kids or kids[0].get("op") != "deletion" or kids[0].get("indicators"):
                break
            out.add(id(kids[0]))
            cur = kids[0]
    return out


def _substituting_containers(tree):
    """ids of bare containers whose first part is a deletion signed with a swap word (round 17 BLUFFS:
    ins(del<ousting>(BLUES, E), FF)): the one "ousting" says the cut letter is replaced by the rest."""
    return {id(n) for n in _walk(tree) if n.get("op") == "container" and not n.get("indicators")
            for kids in [[p for p in n.get("parts") or [] if isinstance(p, dict)]]
            if kids and kids[0].get("op") == "deletion"
            and _SUBSTITUTE_WORD.search(" ".join(str(i.get("text") or "") for i in kids[0].get("indicators") or []))}


def unindicated_ops(tree):
    """How many checked ops that need an indicator word have none.

    Not a sound under a Spoonerism: an older tree may still file
    spoon<Spooner's>(sound([word]HEARD, SPELT), b) (the prompt now teaches
    spoon<Spooner's>([marry]MARRY, [fan]FAN, FERRYMAN)), and a clue's one
    indicator ("Spooner's ...") is the Spoonerism's, so a sound under it has no
    word of its own to name. Counting it made indysunday-1910 16A and cryptic-30133 17A
    (both Spoonerisms with a flagged hint) impossible to clear: no tree passed
    both this rule and the one that wants the sound written (10-17)."""
    spoken = {id(p) for s in _walk(tree) if s.get("op") == "spoonerism"
              for p in s.get("parts") or [] if isinstance(p, dict) and p.get("op") == "homophone"}
    copies = _repeated_copies(tree)
    return sum(1 for n in _walk(tree) if n.get("op") in NEEDS_INDICATOR
               and not n.get("unchecked") and not n.get("indicators") and id(n) not in spoken
               and id(n) not in copies)


def cdef_repeats(tree):
    """Extra leaves under a cryptic definition: the clue words once is the whole of it."""
    return sum(max(0, len(n.get("parts") or []) - 1) for n in _walk(tree)
               if n.get("op") == "cryptic" and not n.get("unchecked"))


def bad_arity(tree):
    """How many checked ops store a part count their op cannot take."""
    n = 0
    for node in _walk(tree):
        op = node.get("op")
        if op and op != "charade" and not node.get("unchecked"):
            lo, hi = _stored_arity(op)
            n += not lo <= len(node.get("parts") or []) <= hi
        elif op == "charade" and not node.get("unchecked"):
            n += len(node.get("parts") or []) < 2
    return n


def _claimed(tree):
    """(kind, start, end, text) for each indicator and clue-word leaf with an `at`,
    leaving out whatever is under a cryptic definition (its leaves are the clue)."""
    out, stack = [], [tree] if isinstance(tree, dict) else []
    while stack:
        node = stack.pop()
        if node.get("op") == "cryptic":
            continue
        for i in node.get("indicators") or []:
            if "at" in i:
                out.append(("indicator", i["at"], i["at"] + len(i["text"]), i["text"]))
        if "words" in node and "at" in node:
            out.append(("leaf", node["at"], node["at"] + len(node["words"]), node["words"]))
        stack += [p for p in node.get("parts") or [] if isinstance(p, dict)]
    return out


def span_overlaps(tree):
    """Pairs of indicator/leaf spans that share clue words.

    Not a pair: two leaves on the very same span. One clue word doing two jobs
    ("seen twice" -> first(seen) + first(seen); "Pieces" -> BIT + PART; "record"
    -> first half + second half; "Ocean's" picked three times by nth) can only
    be written as the same words in two leaves, so a model asked to fix it had
    nothing honest to change (read off 8 of the 27 span_overlap rows of
    tools/data/shape_reannotate.json, 10-17). A leaf that merely overlaps
    another, or an indicator over a leaf, is still counted."""
    return len(span_overlap_pairs(tree))


def span_overlap_pairs(tree):
    """The (a, b) pairs span_overlaps counts, each a (kind, start, end, text) from _claimed."""
    sp = _claimed(tree)
    return [(a, b) for i, a in enumerate(sp) for b in sp[i + 1:]
            if a[1] < b[2] and b[1] < a[2]
            and not (a[0] == b[0] == "leaf" and a[1] == b[1] and a[2] == b[2])]


def span_overlap_text(tree):
    """Each overlap named by its words, so the model sees which clue words are claimed twice:
    "indicator 'parties' and leaf 'parties' both claim 'parties'"."""
    return "; ".join(
        f"{a[0]} '{a[3]}' and {b[0]} '{b[3]}' both claim '{a[3][max(b[1] - a[1], 0):min(b[2], a[2]) - a[1]]}'"
        for a, b in span_overlap_pairs(tree))


def _with_places(ann, clue):
    """`ann` with an `at` filled in on every definition, indicator and leaf that has none and whose
    text stands once in `clue` (whole words): round 14 found annotations filed without places
    (ETNA, NATANT) that the place rules cannot see, two of 20 missed errors in 600 passing clues."""
    flat = str(clue or "")

    def find(text):
        hits = [m.start() for m in re.finditer(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(str(text)), flat, re.I)]
        return hits[0] if len(hits) == 1 else None

    def fill(item, key):
        if isinstance(item, dict) and "at" not in item and item.get(key):
            at = find(item[key])
            return {**item, "at": at} if at is not None else item
        return item

    def walk(node):
        node = {**node}
        if "words" in node and "op" not in node:
            node = fill(node, "words")
        if node.get("indicators"):
            node["indicators"] = [fill(i, "text") for i in node["indicators"]]
        if node.get("parts"):
            node["parts"] = [walk(p) if isinstance(p, dict) else p for p in node["parts"]]
        return node
    out = {**ann, "definitions": [fill(d, "text") for d in ann.get("definitions") or []]}
    if isinstance(ann.get("wordplay"), dict):
        out["wordplay"] = walk(ann["wordplay"])
    return out


def in_definition(ann, clue=None):
    """Wordplay spans inside a definition of a clue that is not &lit. With `clue`, spans filed
    without places are located in it first (_with_places).

    Two shapes are the setter's, not a fault, and are not counted (read off the
    45 grandfathered rows, 10-17):
      * the definition is the fodder: a palindrome or reversal over one leaf on
        exactly the definition's words ("Bread, either way" NAAN, "Touch, one way
        or the other" TAP), the clue's two halves being the same words;
      * a word split in two: the leaf takes the whole word and the definition
        only the end or start of it ("Woollen hat found lying under stopcock"
        BANTAM: STOP gives BAN, definition "cock"; "Guard's company" SCREW,
        S from "Guard's", definition "Guard"). The page can only mark whole
        leaves, so the definition is the part and the leaf the word."""
    if ann.get("andLit"):
        return 0
    if clue:
        # a definition on the whole clue is an &lit the file did not mark (round 14: 7 of 11 new hits)
        if any(isinstance(d, dict) and wordplay.letters(d.get("text")) == wordplay.letters(clue)
               for d in ann.get("definitions") or []):
            return 0
        ann = _with_places(ann, clue)
    ds = [(d["at"], d["at"] + len(d["text"]), d["text"]) for d in ann.get("definitions") or []
          if isinstance(d, dict) and "at" in d and d.get("text")]
    n, stack = 0, [(ann.get("wordplay"), None)] if isinstance(ann.get("wordplay"), dict) else []
    while stack:
        node, parent = stack.pop()
        if node.get("op") == "cryptic":
            continue
        spans = [("indicator", i["at"], i["at"] + len(i["text"]), i["text"])
                 for i in node.get("indicators") or [] if "at" in i]
        if "words" in node and "at" in node:
            spans.append(("leaf", node["at"], node["at"] + len(node["words"]), node["words"]))
        for kind, s0, s1, text in spans:
            for a, b, dtext in ds:
                if not (s0 < b and a < s1):
                    continue
                if kind == "leaf" and (s0, s1) == (a, b) and parent and parent.get("op") in ("palindrome", "reversal"):
                    continue
                lo, dl = text.lower(), dtext.lower()
                if kind == "leaf" and len(lo) > len(dl) and s0 <= a and b <= s1 and (
                        (lo.endswith(dl) and lo[-len(dl) - 1].isalpha())
                        or (lo.startswith(dl) and not lo[len(dl)].isspace())):
                    continue
                n += 1
                break
        stack += [(p, node) for p in node.get("parts") or [] if isinstance(p, dict)]
    return n


def leaf_folds(tree):
    """Leaves that give a stretch (3+ letters) of their own words and say nothing
    else: the stretch is a selection, a deletion or a hidden word, written as a leaf.

    Not folds: a leaf the abbreviation table holds (engineering/ENG), a leaf directly under a hidden-word op (the prompt's own form,
    hid([say no before]YNOBE): the op is there and the leaf names what it finds)
    and a leaf that only drops a possessive or plural S ([Mike's]MIKE)."""
    n = 0
    stack = [(tree, None)] if isinstance(tree, dict) else []
    while stack:
        node, parent = stack.pop()
        stack += [(p, node) for p in node.get("parts") or [] if isinstance(p, dict)]
        if "words" in node and "gives" in node and not node.get("unchecked") and not node.get("note"):
            if parent and parent.get("op") == "hidden":
                continue
            w, g = wordplay.letters(node["words"]), node["gives"]
            if annotation.is_abbreviation(node):
                continue  # a standard abbreviation that happens to open the word (ENG, DEM)
            n += len(g) >= 3 and g != w and g in w and w != g + "S"
    return n


def repeated_selections(tree):
    """Charades holding two or more of the same letter selection, each over one
    leaf (an acrostic written word by word): one selection over a multi-word leaf
    is the same pick. Picks each signalled by their own different indicator are separate
    picks, not one acrostic (GRAPH: first<first>([Group's]) + RAP + first<top of>([hip-hop]);
    PULSE: first<opening>([poet's]) ... first<at first>([enthusiasts])): one indicator
    covering several words is what a multi-word leaf says."""
    n = 0
    for node in _walk(tree):
        if node.get("op") == "charade" and not node.get("unchecked"):
            picks = collections.Counter(
                (p["op"], p.get("n"), tuple(sorted(
                    str(i.get("text") if isinstance(i, dict) else i).lower() for i in p.get("indicators") or []))) for p in node.get("parts") or []
                if isinstance(p, dict) and p.get("op") in wordplay.SELECT and not p.get("unchecked")
                and len(p.get("parts") or []) == 1 and "words" in p["parts"][0])
            n += sum(k > 1 for k in picks.values())
    return n


def single_leaf(tree):
    """1 when the whole wordplay is one leaf: a synonym for the answer, no mechanism."""
    return int(isinstance(tree, dict) and "op" not in tree and not tree.get("unchecked"))


# A bare leaf's note that says the puzzle, not a clue word, supplies the letters
# (Genius/Azed/themed puzzles: "the letter the preamble says the wordplay omits").
DEVICE_NOTE = re.compile(
    r"preamble|theme|unclued|ignored|omit|leaves? out|left out|missing|collid|grid.s edge|"
    r"(?:left|right|top|bottom) edge|doubled|instruction|restores?", re.I)


def bare_in_charade(tree, ann=None):
    """Pieces of a checked charade that are bare letters with no clue words.

    A bare leaf whose note says where the letters come from (DEVICE_NOTE: the
    preamble, the theme, an omitted or ignored letter) counts as a device leaf.

    Two kinds of bare letters are no fault. A clue with a `hiddenLetter` (the
    puzzle's extra/omitted/misprint device) has its letter in the answer or
    wordplay from no clue word. A leaf marked `"device": true` is letters the
    preamble or theme supplies (a Genius edge letter, an Azed collision's
    shared letters); the marker is the annotator's claim, so it stays in the
    stored tree where a reader can see it."""
    if isinstance(ann, dict) and ann.get("hiddenLetter"):
        return 0
    return sum(1 for node in _walk(tree) if node.get("op") == "charade" and not node.get("unchecked")
               for p in node.get("parts") or []
               if isinstance(p, dict) and "op" not in p and "words" not in p and not p.get("unchecked")
               and not p.get("device") and not DEVICE_NOTE.search(p.get("note") or ""))


def anagram_of_container(tree):
    """Anagrams whose fodder is a container's result: the container is the
    outer step in nearly every such clue, with the anagram its inner arm."""
    return sum(1 for node in _walk(tree) if node.get("op") == "anagram"
               and any(isinstance(p, dict) and p.get("op") == "container" for p in node.get("parts") or []))


def _unchecked_ops(tree):
    return [n for n in _walk(tree) if n.get("op") and n.get("unchecked")]


def _spoon_swap_ok(sounds, gives, originals=()):
    """Whether `gives` is the spoonerism the leaf's `soundsLike` says. `originals` are the
    two words the setter swaps when the tree files them as parts (TWO, BEAKS): the sound
    reading then opens with the second one's letter and the first one's follows, and the
    answer is spelt from it. Else two sound words are the swap of each other's openings
    (by letters, or by the frame when the spelling shifts with the sound), and one word is
    a sound-alike whose letters the swap rearranges, so the answer uses nearly the same."""
    ws = [wordplay.letters(w) for w in str(sounds or "").split()]
    if not gives or not ws or not all(ws):
        return False
    if len(originals) == 2 and len(ws) == 2 and all(originals) and ws == list(originals):
        # soundsLike names the two words as they stand (FULL APACE, BOG LOOK): the swap
        # trades their opening sounds, so the answer is the same letters rearranged
        # (PULLAFACE, LOGBOOK), changed at the start, and not the two words run together
        joined = ws[0] + ws[1]
        return len(gives) >= 4 and sorted(gives) == sorted(joined) and gives != joined and gives[0] != joined[0]
    if len(originals) == 2 and len(ws) == 2 and all(originals):
        (a, b), (x, y) = originals, ws
        return x[0] == b[0] and y[0] == a[0] and gives[0] == x[0] and gives[-1] == y[-1] and len(gives) >= 4
    if len(ws) == 2:
        a, b = ws
        swapped = {wordplay._onset(b) + a[len(wordplay._onset(a)):] + wordplay._onset(a) + b[len(wordplay._onset(b)):],
                   b[:1] + a[1:] + a[:1] + b[1:]}
        return gives in swapped or wordplay._spoon_sound(sounds, gives)
    if len(ws) == 1 and len(ws[0]) >= 4 and gives != ws[0] and len(gives) >= 3 and gives[0] != ws[0][0]:
        c, d = collections.Counter(ws[0]), collections.Counter(gives)
        return sum(((c - d) + (d - c)).values()) <= 2
    return False


def step_verified(node):
    """Whether an `unchecked` op step is one whose letters can be computed from its leaf, so
    the flag only records a precaution (fix round 4, 14 of 20 sampled unchecked_step rows
    were right): first / last / middle / outer pick `gives` from the clue words of the one
    leaf under them, and a spoonerism's `gives` is the swap of the leaf's `soundsLike`. A
    step whose leaf and `gives` disagree, or whose pick the words cannot make, stays unchecked."""
    return _verified_leaf(node) is not None


def _verified_substitution(node, parts):
    """The first part of an unchecked two-part substitution whose result the pieces compute,
    else None. Two forms the evaluator's centre swap does not take, both with the result the
    node gives: a pair of letters that trade places through the other piece (SW in SELLNEWS
    -> WELLNESS, cryptic-29499 8d), and one letter that takes the place of the other piece's
    first or last (G for the leader of RULES -> GULES, timesjumbo-1354 52d)."""
    want = wordplay.letters(node.get("gives"))
    if len(parts) == 3 and want:  # whole, the piece that goes, the piece that replaces it (OMEGA, G, RT -> OMERTA)
        try:
            for whole in wordplay.values(parts[0]):
                for old in wordplay.values(parts[1]):
                    for new in wordplay.values(parts[2]):
                        if old and whole.count(old) == 1 and whole.replace(old, new) == want and new != old:
                            return parts[0]
        except (wordplay.WordplayError, KeyError, TypeError, ValueError, IndexError):
            return None
        return None
    if len(parts) == 1 and want and "op" not in parts[0] and not parts[0].get("gives") and parts[0].get("words"):
        # one word and a swap its indicator names ("Russia/EU trade": U out, E in), the result
        # then anagrammed (ARISES): the result is the word's letters with exactly that swap
        have, left = collections.Counter(wordplay.letters(parts[0]["words"])), collections.Counter(want)
        out_, in_ = have - left, left - have
        said = wordplay.letters(" ".join(str(i.get("text") or "") for i in node.get("indicators") or []))
        if len(want) == len(wordplay.letters(parts[0]["words"])) and sum(out_.values()) == 1 == sum(in_.values()) \
                and set(out_) | set(in_) <= set(said):
            return parts[0]
        return None
    if len(parts) != 2 or not want:
        return None
    try:
        for new_part, old_part in ((parts[0], parts[1]), (parts[1], parts[0])):
            for new in wordplay.values(new_part):
                for old in wordplay.values(old_part):
                    if len(new) == 2 and new[0] != new[1] and len(old) == len(want) and any(
                            {old[i], old[j]} == set(new) and old[:i] + old[j] + old[i + 1:j] + old[i] + old[j + 1:] == want
                            for i in range(len(old)) for j in range(len(old)) if i < j):
                        return parts[0]
                    if len(new) == 1 and len(old) == len(want) >= 3 and old != want \
                            and want in (new + old[1:], old[:-1] + new):  # not the piece itself back
                        return parts[0]
                    if len(new) == 1 and len(old) == len(want) >= 5 and new_part is parts[1] \
                            and sum(a != b for a, b in zip(old, want)) == 1 \
                            and any(o != w and w == new for o, w in zip(old, want)):
                        return parts[0]  # one letter inside swapped for the piece (COCKATOO -> COCKAPOO)
    except (wordplay.WordplayError, KeyError, TypeError, ValueError, IndexError):
        return None
    return None


def _verified_leaf(node):
    """The leaf step_verified checked the unchecked step `node` against, else None."""
    op, parts = node.get("op"), [p for p in node.get("parts") or [] if isinstance(p, dict)]
    if not node.get("unchecked"):
        return None
    if op == "spoonerism":  # the swapped words may ride along as parts; the leaf with soundsLike is the claim
        two = [p for p in _walk(node) if p.get("soundsLike") and "op" not in p]
        if len(two) == 2 and all(p.get("gives") for p in two):
            # two sound-alikes trade their opening sounds, each leaf giving its own word's new
            # spelling (stake/hock + birdhouse/coop -> COCK + HOOP, cryptic-29218 7d)
            (ga, gb), (sa, sb) = [[wordplay.letters(p[k]).lower() for p in two] for k in ("gives", "soundsLike")]
            oa, ob = wordplay._onset(sa), wordplay._onset(sb)
            if sa and sb and oa != ob and ga.startswith(ob[:1]) and gb.startswith(oa[:1]) \
                    and ga[len(ob):] == sa[len(oa):] and gb[len(oa):] == sb[len(ob):]:
                return two[0]
        sound = [p for p in parts if p.get("soundsLike") and "op" not in p]
        want = wordplay.letters(node.get("gives"))
        others = [wordplay.letters(p.get("gives")) for p in parts if p is not sound[0] and "op" not in p] if sound else []
        if len(sound) == 1 and want and wordplay.letters(sound[0].get("gives")) == want \
                and _spoon_swap_ok(sound[0]["soundsLike"], want, others):
            return sound[0]
        return None
    if op == "substitution":
        return _verified_substitution(node, parts)
    if op == "anagram" and len(parts) == 1 and parts[0].get("op") and _verified_leaf(parts[0]) is not None \
            and sorted(wordplay.letters(node.get("gives"))) == sorted(wordplay.letters(parts[0].get("gives"))) \
            and node.get("gives"):
        return parts[0]  # a scramble of a step already computed (ARISES: Russia, U for E, then scrambled)
    if len(parts) == 1 and op == "hidden" and parts[0].get("op") in wordplay.SELECT and parts[0].get("unchecked") \
            and wordplay.letters(node.get("gives")) == wordplay.letters(parts[0].get("gives")) and node.get("gives"):
        return _verified_leaf(parts[0])  # a hidden word over a selection already computed (INCA, mid of skincare)
    if len(parts) != 1 or "op" in parts[0]:
        return None
    leaf = parts[0]
    if op == "charade" and len(wordplay.letters(leaf.get("gives"))) >= 3 and set(wordplay.letters(leaf.get("gives"))) <= set("NSEW") \
            and wordplay.letters(leaf.get("gives")) == wordplay.letters(node.get("gives")) \
            and re.search(r"\b(?:directions?|points?|compass|quarters?)\b", str(leaf.get("words")), re.I):
        return leaf  # "directions" = SEWN: each letter is a compass point, in the order the indicator names (round 13)
    given = {wordplay.letters(x.get("gives")) for x in (node, leaf) if x.get("gives")}
    if len(given) != 1 or not (want := next(iter(given))):
        return None
    if op not in wordplay.SELECT or op == "nth" or not leaf.get("words"):
        return None
    try:
        got = wordplay.values({"op": op, "parts": [{"words": leaf["words"], "select": op}]})
    except wordplay.WordplayError:
        return None
    if want in got:
        return leaf
    word = wordplay.letters(leaf["words"]).lower()
    if len(str(leaf["words"]).split()) == 1:
        # sweetheart = the heart of sweet (WOOED), mountaintop = top of mountain: the compound names the pick
        # and the rest is the source word (round 13)
        for k in _SELECT_COMPOUND.get(op, ()):
            for rest in ((word[:-len(k)] if word.endswith(k) else None), (word[len(k):] if word.startswith(k) else None)):
                if rest and len(rest) >= 3:
                    try:
                        if want in wordplay.values({"op": op, "parts": [{"words": rest, "select": op}]}):
                            return leaf
                    except wordplay.WordplayError:
                        pass
    return None


_SELECT_COMPOUND = {"middle": ("heart", "centre", "center", "core", "middle"),
                    "first": ("top", "head", "leader", "front"), "last": ("tail", "foot", "bottom")}


def unverified_unchecked(tree, answer=None):
    """The nodes still carrying the `unchecked` flag once the steps step_verified can
    compute are set aside (each with the one leaf under it). With the clue's `answer`,
    a verified step counts only in a tree that gives the answer: a right pick in a tree
    that is wrong elsewhere (cryptic-28632 23d, cryptic-26974 53a) is still the redo's."""
    done = set()
    if not any(n.get("unchecked") for n in _walk(tree)):
        return []  # most trees: no flag, nothing to evaluate
    if answer is not None:
        try:
            wordplay.evaluate(tree, answer)
        except (wordplay.WordplayError, KeyError, TypeError, ValueError, IndexError):
            return [n for n in _walk(tree) if n.get("unchecked")]
    for n in _walk(tree):
        leaf = _verified_leaf(n) if n.get("op") else None
        if leaf is not None:
            done |= {id(n), id(leaf)}
            if n.get("op") == "spoonerism":
                done |= {id(q) for q in _walk(n)}
    for n in _walk(tree):
        if n.get("op") and n.get("unchecked") and id(n) not in done and _recomputes(n):
            done |= {id(q) for q in _walk(n)}
    return [n for n in _walk(tree) if n.get("unchecked") and id(n) not in done]


def _strip_unchecked(node):
    if not isinstance(node, dict):
        return node
    return {k: ([_strip_unchecked(p) for p in v] if k == "parts" else v) for k, v in node.items() if k != "unchecked"}


def _pool(node):
    """The letters (sorted) a fodder piece contributes to an anagram: a leaf's `gives` or words, a deletion's first
    piece less the rest, any other op's `gives`; None when they cannot be told."""
    parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
    if "op" not in node:
        return collections.Counter(wordplay.letters(node.get("gives") or node.get("words")))
    if node["op"] == "deletion" and len(parts) >= 2 and all(_pool(p) is not None for p in parts):
        left = _pool(parts[0])
        for p in parts[1:]:
            left = left - _pool(p)
        return left if sum(_pool(parts[0]).values()) - sum(left.values()) == sum(sum(_pool(p).values()) for p in parts[1:]) else None
    return collections.Counter(wordplay.letters(node["gives"])) if node.get("gives") else None


def _recomputes(node):
    """Whether an unchecked op step is computed by its pieces (round 18, 9 of 11 sampled unchecked_step flags
    judged fine): the flag only records a precaution when the evaluator, with the flag lifted, gives the stated
    letters; when an anagram's fodder (a deletion's remainder included) has exactly its stated letters; or when a
    hidden or middle pick states a run of its leaf's own letters."""
    live = _strip_unchecked(node)
    want = wordplay.letters(node.get("gives"))
    try:
        if node["op"] == "anagram" and want:
            pools = [_pool(p) for p in live.get("parts") or [] if isinstance(p, dict)]
            if pools and all(p is not None for p in pools) and sum(pools, collections.Counter()) == collections.Counter(want):
                return True
        if node["op"] in ("hidden", "middle") and want:
            run = "".join(wordplay.letters(q.get("words")) for q in _walk(live) if "op" not in q and q.get("words"))
            if want in run and len(want) < len(run):
                return True
        if want:
            wordplay.evaluate(live, want)
            return True
        return bool(wordplay.values(live))
    except Exception:  # any failure to compute leaves the step flagged
        return False


def arity_ins(tree):
    """Unchecked containers that do not hold exactly two parts (the held and the holder)."""
    return sum(len(n.get("parts") or []) != 2 for n in _unchecked_ops(tree) if n["op"] == "container")


def arity_other(tree):
    """Unchecked ops with more parts than their evaluator takes: a deletion of 3+, a
    substitution not of 3, a homophone of 3+, a reversal, hidden word, cycling or
    letter selection not of 1."""
    n = 0
    for node in _unchecked_ops(tree):
        op, k = node["op"], len(node.get("parts") or [])
        if op == "substitution" and k > 3:  # a bare link word among 4+ parts is not one of the three
            k -= sum(1 for p in node.get("parts") or [] if isinstance(p, dict) and "op" not in p
                     and not p.get("gives") and wordplay.letters(p.get("words")) in _SUB_LINKS)
        n += ((op == "deletion" and k > 9) or (op == "substitution" and k != 3)
              or (op == "homophone" and k >= 3)
              or (op in ("reversal", "hidden", "cycling") + wordplay.SELECT and k != 1))
    return n


def _not_a_rotation(node):
    """An unchecked `cycling` step whose result is not its one part's letters rotated: a letter moved
    to the front (HEARS -> RHEAS, times-28709 22d) is not cycling, and "unchecked" hid it (round 13)."""
    part = node["parts"][0]
    have, want = wordplay.letters(part.get("gives")), wordplay.letters(node.get("gives"))
    return bool(isinstance(part, dict) and have and want and len(have) == len(want) and have != want
                and want not in {have[k:] + have[:k] for k in range(len(have))})


_DEL_ALL = re.compile(r"\b(both|each|every|cases|ends|edges|tops|heads|tails|boundar(?:y|ies)|borders|"
                      r"limits|margins|fringes|outskirts|extremities)\b", re.I)
#: Link words a substitution may list among its parts beside the three it takes
#: ("changing book to IF": [by] is the clue's link, not a part), round 10 (JUSTIFY).
_SUB_LINKS = frozenset("BY FOR WITH TO IN OF AND FROM".split())


def del_single(tree):
    """Unchecked deletions with one part: the letters taken out are not stated.

    Not counted: a deletion whose only part is a single leaf and which carries an
    indicator ("lifting both ends of" barbells > WEIGHTS > EIGHT, "short" leg >
    STAGE > STAG): the indicator says what comes off the leaf's `gives`, a
    correct parse (sample of 13, 5 of them this shape). A composite part (a
    charade wrapped as one deletion, cryptic-22711 31d GON+AD) is still counted:
    the indicator applies to one piece, not to the joined result."""
    def lone_leaf(n):
        parts = n.get("parts") or []
        return (n.get("indicators") and isinstance(parts[0], dict) and "op" not in parts[0]
                and parts[0].get("gives") and parts[0].get("words"))
    # Also not counted (fix round 4, ftcryptic-17845 18d KINETIC, times-29330 5d ENCHANTER,
    # telegraph-31189 11a ENHANCE): a lone leaf cut and then scrambled (the anagram comes
    # after the cut), and a deletion over a charade of 2+ pieces whose indicator speaks of
    # every piece ("both topless", "after losing cases") and so covers all of them.
    fodder = {id(p) for a in _walk(tree) if a.get("op") == "anagram"
              for p in a.get("parts") or [] if isinstance(p, dict)}

    def cut_then_scrambled(n):
        p = (n.get("parts") or [{}])[0]
        return id(n) in fodder and n.get("indicators") and isinstance(p, dict) and "op" not in p and p.get("words")

    def covers_all(n):
        p = (n.get("parts") or [{}])[0]
        if not (isinstance(p, dict) and p.get("op") == "charade" and len(p.get("parts") or []) >= 2
                and not any("op" in q for q in p["parts"] if isinstance(q, dict))):
            return False
        return any(_DEL_ALL.search(str(i.get("text") or "")) for i in n.get("indicators") or [])
    return sum(len(n.get("parts") or []) == 1 and not lone_leaf(n) and not cut_then_scrambled(n)
               and not covers_all(n)
               for n in _unchecked_ops(tree) if n["op"] == "deletion")


def ind_in_leaf(tree, clue=None):
    """Indicators (3+ letters) that also sit, as a whole word, inside a longer leaf of
    clue words: the leaf took the indicator's word as well as its own.

    With the `clue` the count is by occurrence: a word the clue says twice
    ("Jog without clothes, without much money") can be an indicator once and
    inside a leaf once, so it is flagged only when the leaves and indicators
    use it more times than the clue has it. Without the clue any repeat fires."""
    nodes = list(_walk(tree))
    leaves = [n for n in nodes if "op" not in n and n.get("words")]
    leaf_words = [[wordplay.letters(x) for x in n["words"].split()] for n in leaves]
    said = collections.Counter(wordplay.letters(x) for x in (clue or "").split())
    used = collections.Counter(wordplay.letters(i.get("text")) for node in nodes
                               for i in node.get("indicators") or [])
    n = 0
    for node in nodes:
        # The repeat is cosmetic when the leaf is the op's own direct part and the op
        # evaluates (checked: azed-1928 8d) or is a selection (its leaf names the word
        # it picks from: times-29067 1d). A leaf under another op is a misfiled
        # indicator (timesjumbo-1742 10d, times-29198 24a) and still counts.
        own = node.get("op") in wordplay.SELECT or not node.get("unchecked")
        direct = {id(p) for p in node.get("parts") or [] if isinstance(p, dict)} if own else set()
        mine = [ws for ws, leaf in zip(leaf_words, leaves) if id(leaf) not in direct and len(ws) > 1]
        every = [ws for ws in leaf_words if len(ws) > 1]
        for i in node.get("indicators") or []:
            t = wordplay.letters(i.get("text"))
            iw = [w for w in (wordplay.letters(x) for x in str(i.get("text") or "").split()) if w]
            # an indicator the corpus gives to another op ("retreating" on a container, 156 of 167 uses a
            # reversal) is not the cosmetic repeat of a leaf's own word: it is the other op's, folded in
            # the leaf as well (times-29174 22d FORCE, round 12)
            owner = _owner_type(i.get("text"))
            mine_i = every if owner and owner != _OP_LEXICON.get(node.get("op")) else mine
            if len(iw) > 1 and len(t) >= 3 and any(
                    ws != iw and any(ws[k:k + len(iw)] == iw for k in range(len(ws) - len(iw) + 1)) for ws in mine_i):
                # a phrase indicator ("Half of") whose words open a leaf of more words (times-29100 9a URN)
                n += not (clue and wordplay.letters(clue).count(t) > 1)
                continue
            if len(t) >= 3 and any(t in ws and ws != [t] for ws in mine_i):
                if clue and said[t] >= used[t] + sum(ws.count(t) for ws in leaf_words):
                    continue  # the clue says the word often enough for each use
                n += 1
    return n


def scrambled_leaves(tree, min_len=4):
    """Leaves (checked or not) whose `gives` is a permutation of their own clue
    letters, not equal to them.

    A fodder leaf gives its own letters in order; only an anagram op scrambles, so
    a leaf that arrives scrambled hides a bad tree (CULTIVATE =
    ana(ins([clever]CUTE, [vital]LTIVA)), [gaunt]GUTAN). Under an anagram the
    fodder is verbatim: [Lido]IDOL under ana is a made-up synonym (shape round 3,
    10-17: 4,654 such clues repaired by tools/fix_scrambled_gives.py, the rule now
    covers them). Not flagged: a leaf directly under a reversal or cycling op (the
    corpus writes the op's input or result there), 3 or fewer letters, and any `gives` with other
    letters (a synonym or abbreviation). A same-first-letter sub-multiset out of
    order was measured too and is mostly a coincident synonym (summer clothes >
    SHORTS), so it is not a rule."""
    n = 0
    stack = [(tree, None)] if isinstance(tree, dict) else []
    while stack:
        node, parent = stack.pop()
        stack += [(p, node) for p in node.get("parts") or [] if isinstance(p, dict)]
        if "op" in node or not node.get("words") or not node.get("gives"):
            continue
        if parent and parent.get("op") in ("reversal", "cycling"):
            continue
        w, g = wordplay.letters(node["words"]), wordplay.letters(node["gives"])
        n += len(g) >= min_len and g != w and collections.Counter(g) == collections.Counter(w)
    return n