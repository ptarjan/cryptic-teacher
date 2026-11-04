"""Wordplay-tree shape detectors of validate_annotations.py, part 2: folded indicators, nested containers, anagram synonyms, role errors.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import collections
import functools
import itertools
import json
import os
import re
import wordplay

from validate_base import ROOT
from validate_link import link_vocabulary
from validate_shape_base import (
    _walk, _OP_LEXICON, REPEAT_WORDS, indicator_role_key, _role_counts, _known_pair, _owner_type, CUT_WORDS,
    _clue_words, CONNECTIVE_WORDS, _accounted_words,
)
from validate_shape_ops import _not_a_rotation

#: Three more shapes a re-parse can pass the gates above with (audit of the burn's
#: redos, 10-17). Each is a ratchet field like the rest.
#:   * IND_FOLDED: the indicator words moved into a leaf that has a `gives`
#:     (everyman-4162 25a: "Principally, Everyman, more than once" one leaf giving ES),
#:     so ind_in_leaf (which needs the indicator listed on an op) sees nothing;
#:   * FAKE_PARTS: a substitution padded to its three parts with wordless nodes
#:     whose `gives` the clue never says (tls-1146 16a: sub(sub(non-fiction, R, L), AL, AR));
#:   * PADDING_LEAF: a leaf of clue words that is `unchecked` with no `gives`: it claims
#:     the words without saying what they contribute (mephisto-3436 18d, "no shock").
#: Not counted: a spoonerism's sound leaves and the selection ops' leaves (another
#: worker's job), a leaf whose note says it was dropped.
IND_FOLDED = "indicator words folded into a leaf"
FAKE_PARTS = "substitution padded with wordless parts that are not in the clue"
PADDING_LEAF = "unchecked clue-word leaf with no letters given"
#: Leaf this wide (words) giving at most half as many letters is not one synonym.
FOLD_WIDE_WORDS = 5
FOLD_MIN_USES = 50


@functools.lru_cache(maxsize=1)
def _indicator_lexicon():
    """{lexicon type: {key: clues}} from tools/data/lexicons/indicators.json."""
    path = ROOT / "tools" / "data" / "lexicons" / "indicators.json"
    return json.loads(path.read_text()) if path.exists() else {}


def folded_indicators(tree):
    """Multi-word leaves that carry a `gives` and also hold an indicator.

    Only a leaf giving 1-2 letters (a selection's or a homophone's result is
    short; a synonym's is not). Flagged when the words at either edge of the leaf
    are a multi-word known indicator (lexicon, 6+ letters, FOLD_MIN_USES+ uses)
    for an op this tree uses; or the leaf is FOLD_WIDE_WORDS+ words and has such
    an edge for any op (everyman-4162 25a uses only a homophone, yet its leaf
    opens with a selection's "Principally"). One-word edges ("perhaps", "without")
    are ordinary leaf words (100s of definitions), so they are not counted
    unless the leaf is wide."""
    nodes = list(_walk(tree))
    used = {_OP_LEXICON[n["op"]] for n in nodes if n.get("op") in _OP_LEXICON}
    lex = _indicator_lexicon()
    n = 0
    for node in nodes:
        if "op" in node or not node.get("words") or not node.get("gives") or node.get("unchecked"):
            continue
        ws = [w for w in (wordplay.letters(x) for x in node["words"].split()) if w]
        if len(ws) < 2:
            continue
        gives = wordplay.letters(node["gives"])
        if len(gives) > 2:
            continue
        runs = [" ".join(r) for k in range(1, len(ws)) for r in (ws[:k], ws[-k:])]

        def known(types, runs=runs):
            return any(lex.get(t, {}).get(key, 0) >= FOLD_MIN_USES and len(key.replace(" ", "")) >= 6
                       for t in types for key in runs if " " in key or len(ws) >= FOLD_WIDE_WORDS)
        n += known(used) or (len(ws) >= FOLD_WIDE_WORDS and known(lex))
    return n


def fake_parts(tree):
    """Substitutions whose replaced and replacement parts are wordless `gives`
    of 2+ letters directly after a substitution: the swap was made up to fill
    the three parts, not read from the clue. Also an unchecked `cycling` that is
    no rotation of its part: the step was named for what it is not."""
    n = 0
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") == "substitution" and not node.get("unchecked") and len(parts) == 3 \
                and isinstance(parts[0], dict) and parts[0].get("op") == "substitution":
            n += all(isinstance(p, dict) and "op" not in p and "words" not in p
                     and len(p.get("gives") or "") >= 2 for p in parts[1:])
        # an unchecked cycling that is no rotation (HEARS -> RHEAS moves one letter, times-28709 22d, round 13)
        n += bool(node.get("op") == "cycling" and node.get("unchecked") and len(parts) == 1
                  and isinstance(parts[0], dict) and _not_a_rotation(node))
    return n


def padding_leaves(tree):
    """Unchecked leaves of clue words with no `gives`, under a charade or another
    op that joins pieces. Not under a spoonerism or a selection op, and not one
    whose note says it was dropped."""
    n, stack = 0, [(tree, None)] if isinstance(tree, dict) else []
    while stack:
        node, parent = stack.pop()
        stack += [(p, node) for p in node.get("parts") or [] if isinstance(p, dict)]
        if "op" in node or not node.get("unchecked") or not node.get("words") or node.get("gives"):
            continue
        if parent and (parent.get("op") in ("spoonerism", "palindrome") or parent.get("op") in wordplay.SELECT):
            continue
        n += "dropped" not in (node.get("note") or "")
    return n


#: Why checked trees that cannot be what the setter wrote still evaluate to the answer
#: (times-29420 24a ABUSE, timesjumbo-1707 48d BISCAY, azed-2333 24d SLIMY): the letter
#: evaluator lets an inserted piece land at ANY gap, including inside a container's own
#: result, so ins(ins(ABE, U), S) spells ABUSE (really AB(U+S)E) and nothing objects.
#: A container nested as the HOLDER of another is almost always the wrong nesting: what
#: goes in two pieces together is a charade of them (ins(ABE, U+S)), and a piece in a
#: piece in a third is ins(third, ins(second, first)). measured 20/20 real (10-18).
NESTED_CONTAINER = "container whose holder is itself a container"
#: An indicator is filed on the op it acts on. One the indicator lexicon knows only for
#: another op (times-29420 16d: "End of", a letter selection's, on the charade) is on
#: the wrong op. Needs a 50-use lexicon entry for the other op and none for this one.
MISPLACED_INDICATOR = "indicator filed on an op it does not signal"
#: The lexicon is rebuilt nightly, so a word can cross this and flag puzzles that were clean;
#: tools/requeue_drift.py (run by the rebuild, and by hand after editing any rule) queues
#: those clues and raises their allowance so the deploy does not go red.
MISPLACED_MIN_USES = 200
#: Plain ordering / juxtaposition words that setters put on a charade as often as on
#: the op the lexicon knows them for ("at first", "opening", "off", "taking",
#: "backing": 5 of 10 sampled flags were correct charades, 10-18). Not flagged; the
#: rule keeps container, reversal and anagram verbs ("eating", "to secure", "around").
ORDERING_INDICATORS = frozenset(
    "at first|opening|off|taking|backing|after|before|following|behind|ahead of|beside|next to|"
    "by|with|and|then|leading|heading|first|starting|beginning|at the start|at the front|"
    "in front of|going before|preceding|followed by|supporting|on|to|for|from|getting|"
    "having|bringing|giving|making|showing|catching|joining|meeting|alongside|against|"
    "early|late|last|finally|at last|at the end|in the end|"
    "to follow|coming after|going after|in pursuit of|pursuing|close to|near|adjacent to|"
    "touching|joined to|attached to|to begin with|wanting".split("|"))
#: Position words, read "A initially B" = A first, "A covers B" = A above B in a down clue, that
#: pass as a charade once the letters concatenate (ANGELUS, TELESCOPE, OUTDO, PLEAD; fix round 3):
#: a container misfiled this way would not spell the answer in order. Still flagged when a
#: selection op in the charade has no indicator of its own (quiptic-170 1a ADAMANT first(talk)),
#: the sign the word belongs to that op. Cleared rows judged 16/20 before that guard.
#: Words that mark a leaf's clue words as an example of the thing they give ("commercial vehicle,
#: perhaps" = VAN); on a charade of plain leaves they are the setter's hedge, not an anagram.
EXAMPLE_MARKERS = frozenset("perhaps|say|maybe|for example|for instance|for one|as an example|possibly".split("|"))
#: Round 18: "originally", "primarily", "firstly" read as "initially" does (UPRIGHTS, WASTED: A primarily B = A first).
POSITION_INDICATORS = frozenset("initially|originally|primarily|firstly|covers|covering|covered by|to cover".split("|"))


#: An inner container whose indicator says its piece goes in apart from the other
#: ("separately", "in two places"): the two pieces land at different points of one
#: holder, which no charade of them can say (WILBERFORCE, UNDERTHEWEATHER).
SEPARATE_INSERTION = re.compile(r"separate|apart|two places|different|both|each|respective|twice", re.I)


def _separate_insertion(outer, inner):
    """True when `outer` = ins(inner = ins(holder, x), y) puts x and y in at different
    points on purpose: the inner indicator says so, or x and y are the same letters
    (a letter put in twice, MALAYAN) since a charade of the two is not a fair parse
    of a repeated piece named once."""
    if any(SEPARATE_INSERTION.search(str(i.get("text") or "")) for i in inner.get("indicators") or []):
        return True
    x = (inner.get("parts") or [None, None])[1:2]
    y = (outer.get("parts") or [None, None])[1:2]
    same = lambda p: wordplay.letters(p.get("gives") or p.get("words")) if isinstance(p, dict) and "op" not in p else None
    return bool(x and y and same(x[0]) and same(x[0]) == same(y[0]))


def _flat_insert_reaches(outer, inner, answer):
    """Whether the two pieces `outer` and `inner` put into one holder can be joined into one
    charade, in either order, that goes into the holder at a single gap and spells `answer`.
    False when they must go in at two gaps (independent-10817 7d BIOMEDICINE: I into BONE after
    B, then MEDICI after BIO, two insertions with an indicator each): the nesting is the
    only parse. Unreadable pieces count as reaching, so the flag stays."""
    try:
        xs, ys = wordplay.values(inner["parts"][1]), wordplay.values(outer["parts"][1])
        target = wordplay.letters(answer)
        try:
            holder = wordplay.values(inner["parts"][0])
        except wordplay._NeedTarget:
            # An anagram holds the first piece (PRERAPHAELITES: RA and ELITE into PERHAPS*): its order is the
            # answer's own, so what must hold is that the answer less one joined piece is the holder's letters.
            bags = wordplay._bag(inner["parts"][0])
            return any(target[:i] + target[i + len(a + b):] for a in xs for b in ys for xy in (a + b, b + a)
                       for i in range(1, len(target) - len(xy))
                       if target[i:i + len(xy)] == xy
                       and "".join(sorted(target[:i] + target[i + len(xy):])) in bags)
        if target not in wordplay.values(outer):
            return True  # the nesting does not even give the answer: a wrong tree, not a double gap
        return any(o[:k] + a + b + o[k:] == target for o in holder for x in xs for y in ys
                   for a, b in ((x, y), (y, x)) for k in range(1, len(o)))
    except Exception:  # an anagram in the pieces needs the target: leave the flag
        return True


def nested_containers(tree, answer=None):
    """How many checked containers hold, as their first part, another checked container
    (less the ones that put two pieces into one holder at different points on purpose, and,
    with the `answer` for a nesting that is the whole tree, the ones no single insertion of
    both pieces can spell: the two gaps are the setter's)."""
    return sum(1 for n in _walk(tree) if n.get("op") == "container" and not n.get("unchecked")
               for p in (n.get("parts") or [])[:1]
               if isinstance(p, dict) and p.get("op") == "container" and not p.get("unchecked")
               and not _separate_insertion(n, p)
               and not (answer and n is tree and len(n["parts"]) == 2 and len(p.get("parts") or []) == 2
                        and not _flat_insert_reaches(n, p, answer)))


#: An anagram scrambles the clue's own letters. A leaf in its fodder that gives a
#: synonym (toughie-3430 3d WISCONSIN: ana<Wild>(cows in + [wrong]SIN); the answer is
#: ana(cows in) + SIN) has a stand-in word scrambled, which the clue cannot mean.
#: One-letter gives are abbreviations (S for southern), which clues do scramble.
ANAGRAM_SYNONYM = "synonym scrambled inside an anagram"


def anagram_synonyms(tree, ann=None, clue=None):
    """How many leaves of 2+ letters, giving other letters than their own words, sit in a
    charade directly under an anagram beside a leaf that gives its own words (the mix
    of fodder and stand-in), or directly under the anagram beside such a leaf (azed-2671
    16a BAROCCOS: ana(crab, [lettuce]COS)). A lone synonym scrambled is not counted
    unless, with the annotation and clue given, a content word of the clue is claimed by
    nothing (independent-12261 8d DIEHARD: ana(caught = HEARD), "heroin" left over): the
    unclaimed word is the letter the real parse moves or drops. A leaf that gives its words
    twice over (IT -> ITIT) is a literal doubling, not a synonym."""
    n = 0
    # Round 22c: with the answer known only a synonym at its edge counts (G + ana(FIRE)); a piece mid-answer
    # scrambled with the rest is fodder (14 of 40 judged hits fine, all mid-answer; 10 of 10 edge hits errors).
    ans = wordplay.letters((ann or {}).get("_answer") or "")
    for node in _walk(tree):
        if node.get("op") != "anagram":
            continue  # unchecked steps count: toughie-3430 3d files its stand-in unchecked
        pools = [node] + [p for p in node.get("parts") or [] if isinstance(p, dict) and p.get("op") == "charade"]
        for p in pools:  # a lone synonym scrambled is an indirect anagram, which setters do write
            pool = [q for q in p.get("parts") or [] if isinstance(q, dict) and "op" not in q
                    and q.get("words")]
            same = [q for q in pool if not q.get("gives") or wordplay.letters(q["gives"]) == wordplay.letters(q["words"])]
            n += bool(same) and sum(1 for q in pool if len(wordplay.letters(q.get("gives"))) >= 2
                                    and wordplay.letters(q["gives"]) != wordplay.letters(q["words"])
                                    and not _doubled(q) and not _near_literal(q) and not _phrase_letters(q)
                                    and not _repeats_sibling(q, pool)
                                    and not q.get("select")
                                    and (not ans or ans.startswith(wordplay.letters(q["gives"]))
                                         or ans.endswith(wordplay.letters(q["gives"])))
                                    and (p is not node or _stand_in(q)))
        n += bool(clue) and _lone_stand_in(node) and bool(_loose_words(ann, clue))
    return n


def _repeats_sibling(leaf, pool):
    """Whether `leaf` is a lone repeat word ("again", "twice") giving the letters another fodder leaf of
    the pool already holds: ana<torment>(set, [again]SET) is SET twice, not a synonym (round 17 TSETSE)."""
    ws = re.findall(r"[A-Za-z]+", str(leaf.get("words") or ""))
    if len(ws) != 1 or ws[0].lower() not in REPEAT_WORDS:
        return False
    gives = wordplay.letters(leaf.get("gives"))
    return any(q is not leaf and gives in (wordplay.letters(q.get("words")), wordplay.letters(q.get("gives")))
               for q in pool)


def _phrase_letters(leaf):
    """Whether a leaf of 2+ clue words gives 3+ letters that all come from those words, each as often as
    they stand there (twice or three times with a repeat or count word: "double-headed besom's" BBESOM,
    "trio of women" WWW, "tunes lacking essential character" TUES). Round 15, 4 of 5 judged-fine
    anaSynonym flags: the words are cut or repeated by their own instruction, not swapped for a synonym."""
    words = str(leaf.get("words") or "")
    gives = collections.Counter(wordplay.letters(leaf.get("gives")))
    have = collections.Counter(wordplay.letters(words))
    times = 3 if {w.lower() for w in re.findall(r"[A-Za-z]+", words)} & (REPEAT_WORDS | COUNT_WORDS | {"trio", "pair", "couple", "duo"}) else 1
    return len(words.split()) >= 2 and sum(gives.values()) >= 3 and gives != have and all(have[c] * times >= n for c, n in gives.items())
#: Count words that say how often the next word's letters come: "three daughters" is DDD,
#: "two ends" ENDEND (quiptic-1168 12a, independent-10551 10a, azed-1886 2d).
COUNT_WORDS = frozenset("two three four five six seven eight nine ten triple treble thrice".split())


def _doubled(leaf):
    """Whether a leaf gives its own words repeated (IT -> ITIT, DO -> DODO), or one letter
    repeated as many times as the clue counts (three eggs -> OOO, three daughters -> DDD): the
    clue's letters again and again, which an anagram may scramble. A count word and a plural S
    on the repeated word are the count's, not letters of it."""
    gives = wordplay.letters(leaf.get("gives"))
    if len(gives) >= 2 and len(set(gives)) == 1 and any(
            w.lower() in COUNT_WORDS for w in re.findall(r"[A-Za-z]+", str(leaf.get("words") or ""))):
        return True  # a letter said several times over
    kept = [w for w in re.findall(r"[A-Za-z]+", str(leaf.get("words") or ""))
            if w.lower() not in REPEAT_WORDS | COUNT_WORDS]
    words = wordplay.letters("".join(kept))
    for base in {words, words[:-1] if words.endswith("S") else words}:
        if base and len(gives) > len(base) and len(gives) % len(base) == 0 and gives == base * (len(gives) // len(base)):
            return True
    return False


def _near_literal(leaf):
    """Whether a leaf's `gives` is its own words with at most one letter off: a typo (eve -> EYE)
    or a number word read as its numeral (anyone -> ANYI, one -> I) inside fodder."""
    w, g = wordplay.letters(str(leaf["words"]).replace("&", " and ")), wordplay.letters(leaf["gives"])
    if len(w) == len(g):
        return sum(a != b for a, b in zip(w, g)) <= 1
    pre = len(os.path.commonprefix([w, g]))
    suf = len(os.path.commonprefix([w[::-1], g[::-1]]))
    return len(g) >= 3 and max(pre, suf) >= len(g) - 1 and max(pre, suf) >= 3


MIDWORD_LEAF = "leaf gives a stretch of its clue words that starts or ends inside a word, with no op for the cut"


@functools.lru_cache(maxsize=1)
def _lexicon_letters():
    """The words of tools/data/lexicon.tsv as lower-case letter strings; empty when it is absent."""
    path = ROOT / "tools" / "data" / "lexicon.tsv"
    if not path.exists():
        return frozenset()
    with path.open(encoding="utf-8", errors="ignore") as f:
        return frozenset(re.sub(r"[^a-z]", "", line.split("\t", 1)[0].lower()) for line in f if line[:1] != "#")


def midword_leaves(tree, clue=None):
    """Leaves of several clue words giving 4+ letters that are a stretch of their own letters
    starting or ending inside a word and are no word of the lexicon or attested pair: a cut
    folded into the leaf, with no op to say it (toughie-3428 4d THEMED: [the day]THED is THE + D;
    sundaytough-211 3d ASPARAGUS: [Taking lid off, burps]URPS is BURPS less B). A wholly made-up
    leaf (RRAUQ, AXIM) was measured too and dropped: 15,336 hits, mostly names, constellations
    and hidden stretches. Needs the lexicon; with none it counts nothing."""
    lex = _lexicon_letters()
    if not lex:
        return 0
    n = 0
    stack = [(tree, ())] if isinstance(tree, dict) else []
    while stack:
        node, anc = stack.pop()
        stack += [(p, anc + (node,)) for p in node.get("parts") or [] if isinstance(p, dict)]
        if "op" in node or not node.get("words") or not node.get("gives") or node.get("select") \
                or node.get("soundsLike") or any(a.get("op") in ("cryptic", "homophone", "spoonerism", "rebus", "reverse",
                                                                 "hidden", "cycling", "reversal") for a in anc):
            continue
        said = re.sub(r"['’]s\b", "", str(node["words"]), flags=re.I)  # a dropped 's is the clue's, not a cut
        g, w = wordplay.letters(node["gives"]).lower(), wordplay.letters(said).lower()
        ends = list(itertools.accumulate(len(wordplay.letters(x)) for x in said.split()))
        if len(ends) < 2 or len(g) < 4 or g in lex or g not in w or re.search(r"\d", str(node["words"])):
            continue
        edges = {0, *ends}  # a stretch is a piece of whole words only if it starts and ends on word edges
        if any(s in edges and s + len(g) in edges for s in range(len(w) - len(g) + 1) if w[s:s + len(g)] == g):
            continue
        # r28+r30 judged: every hit with a cut word in the leaf (half, stripped, limits, skinned, deposing leader) was
        # wrong; the three fine ones (INCR "one in credit", CAPT "captain, briefly", SINGULARP) joined an abbreviation
        cutters = [x for x in re.findall(r"[a-z']+", str(node["words"]).lower()) if x != "briefly"]
        if not any(x in CUT_WORDS or _owner_type(x) in ("deletion", "letter_selection") for x in cutters):
            continue
        if not _known_pair(node["words"], wordplay.letters(node["gives"])):
            n += 1
    return n


def _lone_stand_in(node):
    """Whether anagram `node` scrambles one leaf and that leaf is a plain stand-in word."""
    ps = node.get("parts") or []
    return len(ps) == 1 and isinstance(ps[0], dict) and "op" not in ps[0] and bool(ps[0].get("words")) \
        and bool(ps[0].get("gives")) and not ps[0].get("select") and _stand_in(ps[0])


def _loose_words(ann, clue):
    """Content words of `clue` that no leaf, indicator, definition or link word of annotation
    `ann` claims, less connectives and link-word vocabulary."""
    ann = ann or {}
    return _clue_words(clue) - _accounted_words(ann) - CONNECTIVE_WORDS - link_vocabulary()


def _stand_in(leaf, min_len=2):
    """Whether a leaf directly under an anagram plainly gives a different word for its words: 2+
    letters (round 21: 4 of 4 two-letter hits in 1,254 clean clues were real: ER, EG, CA, RR UP), no digit (a cross-reference gives the other answer, whose letters are the fodder),
    and not a piece of its own letters (BIN -> BI is a cut the leaf did inline). Measured 10-18:
    without these, 10 of 20 sampled direct-leaf hits were right. A well-known pair (lettuce
    -> COS) is not exempt: scrambling it is the fault."""
    words, gives = wordplay.letters(leaf["words"]), wordplay.letters(leaf["gives"])
    return len(gives) >= min_len and not re.search(r"\d", str(leaf["words"])) \
        and not (words.startswith(gives) or words.endswith(gives) or gives in words)


#: Indicator roles swapped between ops that pass every evaluator check (timesjumbo-1682
#: 5d PERSUADE "to limit" on the reversal; independent-12339 13a HAPPY outer<about>,
#: ins<Extremely>; times-29467 9a CATSUIT hid<returned>, rev<from>; cryptic-29995 6d
#: HANGOUT): an indicator the corpus files under ONE other op type nearly always and under
#: this one almost never (tools/data/indicator_roles.json, counted by
#: tools/build_indicator_roles.py over the annotations: the uses of each owned word under
#: each op). Words that serve several ops (about, over, out, round, in) fail the ownership
#: bar and are never flagged. The charade is no owner: its words are plain juxtaposition
#: ("after") that setters put on other ops too.
ROLE_MIN_USES = 20
ROLE_OWNED = 0.95
ROLE_OWN_MAX = 0.02
#: The corroboration a lone flag needs (a swap of two ops flags both): the tree holds an op
#: of the owner type with no indicator or one the corpus files there at most this often.
#: Without it a lone "flipping" on an anagram (BIRTHDATE) or "coming back" on a homophone
#: was a legitimate setter's use in 3 of 20 sampled hits.
ROLE_WEAK = 0.05
#: Words that are a link between fodder and result as much as an indicator: "tie, poles INTO
#: small diagram" is an anagram (INSET, RUIN: 2 of 3 sampled "into" hits were right).
ROLE_LINKS = frozenset({"INTO"})


def _indicators_foreign(op, kind):
    """Whether every indicator of `op` is a well-used word (ROLE_MIN_USES+) that the corpus files under
    `kind` at most ROLE_LOOSE_OWN_MAX of the time."""
    for i in op.get("indicators") or []:
        counts = _role_counts(indicator_role_key(i.get("text")))
        total = sum(counts.values())
        if total < ROLE_MIN_USES or counts.get(kind, 0) > ROLE_LOOSE_OWN_MAX * total:
            return False
    return True


def wrong_role_indicators(tree):
    """How many indicators on a checked op of a type (anagram, reversal, container,
    deletion, hidden, homophone, selection) whose lexicon word is owned by another type:
    at least ROLE_MIN_USES uses there making up ROLE_OWNED of its uses, and at most
    ROLE_OWN_MAX of them under this op's own type."""
    nodes = [n for n in _walk(tree) if _OP_LEXICON.get(n.get("op")) and not n.get("unchecked")]
    loose = []  # (id, own, top) of words a looser bar calls the other op's; flagged only as a mutual pair
    misfiled = []  # (id, own, counts, total) of words their op's type hardly ever carries (round 12 trade)
    flagged, swappable = set(), []  # flagged: (node, indicator) ids; swappable: (id, node type, owner type)
    for node in nodes:
        own = _OP_LEXICON[node["op"]]
        for at, i in enumerate(node.get("indicators") or []):
            key = indicator_role_key(i.get("text"))
            counts = _role_counts(key)
            total = sum(counts.values())
            if total < ROLE_MIN_USES or key in ROLE_LINKS or {own, max(counts, key=counts.get)} == {"hidden_word", "letter_selection"}:
                continue
            top = max(counts, key=counts.get)
            if counts.get(own, 0) <= ROLE_LOOSE_OWN_MAX * total:
                misfiled.append(((id(node), at), own, counts, total))
            if top != own and "hidden_word" not in (own, top) and counts[top] >= ROLE_LOOSE_OWNED * total \
                    and counts.get(own, 0) <= ROLE_LOOSE_OWN_MAX * total:
                loose.append(((id(node), at), own, top))
            if top == own or counts.get(own, 0) > ROLE_OWN_MAX * total:
                continue
            if counts[top] >= ROLE_SWAP_OWNED * total:
                swappable.append(((id(node), at), own, top))
            if (own == "hidden_word" and top == "container") or counts[top] < ROLE_OWNED * total:
                continue  # a hidden word is signalled by container words ("to welcome", "holding")
                #           and by selection words ("essentially", "somewhat"); see ROLE_LINKS
            if any(_OP_LEXICON[o["op"]] == top and _lacks_role(o, top) for o in nodes) \
                    or (top == "deletion" and own == "container" and not any(o.get("op") == "deletion" for o in _walk(tree))):
                # ... or a cut word where the tree has no deletion at all: the cut was folded into a leaf
                # (timesjumbo-1750 27d RHODESIA ins<almost>(late -> DEA, ..)). A lone reversal word
                # ("returned") is let go: the leaf may hold the reversed letters
                
                flagged.add((id(node), at))
    # a charade carrying a word of another op ("elevated" 94% reversal) beside an op carrying a word the
    # corpus files elsewhere is the same swap (timesjumbo-1787 12d NOSY: rev<at the end>, charade<elevated>)
    charade_tops = set()
    for node in _walk(tree):
        if node.get("op") == "charade" and not node.get("unchecked"):
            for i in node.get("indicators") or []:
                counts = _role_counts(indicator_role_key(i.get("text")))
                total = sum(counts.values())
                if total >= ROLE_MIN_USES and counts[max(counts, key=counts.get)] >= 0.9 * total:
                    charade_tops.add(max(counts, key=counts.get))
    # the other direction (times-29578 26a UNSPORTSMANLIKE: charade<poorly>(ana<by>(..), IKE)): a charade
    # carrying a word that is all one op's ("poorly" 97% anagram) while a checked op of that type in the tree
    # has only indicators the corpus files under it under 10% ("by" is 6% anagram) -- the words trade places
    for node in _walk(tree):
        if node.get("op") != "charade" or node.get("unchecked"):
            continue
        for at, i in enumerate(node.get("indicators") or []):
            counts = _role_counts(indicator_role_key(i.get("text")))
            total = sum(counts.values())
            if total < ROLE_MIN_USES:
                continue
            top = max(counts, key=counts.get)
            if counts[top] >= 0.9 * total and top in ("anagram", "reversal") and any(
                    _OP_LEXICON.get(o.get("op")) == top and o.get("indicators") and not o.get("unchecked")
                    and _indicators_foreign(o, top) for o in nodes):
                flagged.add((id(node), at))
    for a, own_a, top_a in swappable:
        if own_a in charade_tops and top_a not in charade_tops:
            flagged.add(a)
    for a, own_a, top_a in swappable:  # a is (node id, indicator index); a mutual swap is its own corroboration (EGRET)
        if any(b[0][0] != a[0] and b[1] == top_a and _swap_alike(b[2], own_a) for b in swappable):
            flagged.add(a)
    # a trade where one word is the other op's and the second is shared between several types, none of them its
    # op's (cryptic-29932 7d EMAIL rev<of some>, hid<upset>: "of some" is 90% hidden, "upset" is reversal or
    # anagram and 0.3% hidden): the first must be mostly the other's type, the second at least a third of this one's
    for x, own_x, cx, tx in misfiled:
        for y, own_y, cy, ty in misfiled:
            if x[0] != y[0] and own_x != own_y and cx.get(own_y, 0) >= 0.5 * tx and cy.get(own_x, 0) >= 0.3 * ty:
                flagged.add(x)
                flagged.add(y)
    for a, own_a, top_a in loose:  # two ops that each carry the other's word: the indicators trade places
        if any(b[0][0] != a[0] and b[1] == top_a and b[2] == own_a for b in loose):
            flagged.add(a)
    return len(flagged) + reversal_of_anagram(tree) + selection_of_one_letter(tree) \
        + extremes_as_one_end(tree) + folded_deletion_leaves(tree) + selection_phrase_elsewhere(tree)


#: A selection phrase ("Last couple in", "first three") filed as the indicator of an anagram, reversal,
#: container or homophone: it names letters to pick, which that op does not do (cryptic-29924 20d BRAVERY
#: ana<Last couple in><re-ordered>(bar), round 12).
SELECTION_PHRASE = re.compile(r"^(?:the\s+)?(?:first|last|final|opening|closing|initial)\s+(?:couple|two|three|four|few|pair|letters?)\b", re.I)


def selection_phrase_elsewhere(tree):
    return sum(1 for node in _walk(tree) if node.get("op") in ("anagram", "reversal", "container", "homophone")
               and not node.get("unchecked")
               for i in node.get("indicators") or [] if SELECTION_PHRASE.match(str(i.get("text") or "").strip()))


#: Both-ends words only: the singular "edge of", "extreme of", "in the extreme" name one end (round 13: RUNES,
#: THOUGHT, OPTICAL, RASP were flagged for last<edge of>, first<edge of>, last<the other extreme of>).
EXTREMES_WORD = re.compile(r"\b(?:extremely|extremities|outer|edges)\b", re.I)
DELETION_LEAF_WORD = re.compile(
    r"\b(?:dropping|drops?|dropped|losing|loses?|lost|leaving|leaves|left|without|missing|shedding|"
    r"sheds?|removing|removed|ejecting|abandoning|dumping|skipping|omitting|lacking)\b", re.I)


def extremes_as_one_end(tree):
    """A first/last op whose indicator says both ends ("extremely", "extremities", "outer",
    "edges"): it picks one letter, so the op should be outer."""
    return sum(1 for node in _walk(tree)
               if node.get("op") in ("first", "last") and not node.get("unchecked")
               and any(EXTREMES_WORD.search(i.get("text") or "") for i in node.get("indicators") or []))


#: Deletion words that are also plain words ("Get left behind" = LAG, "leaf on left" = VO,
#: "tea leaves"): read as a deletion only with a source before and a thing taken after, and
#: not after a verb of being/getting or a preposition/article, nor before a particle.
AMBIGUOUS_DELETION = frozenset("left leaves leaving lost leave".split())
NOT_BEFORE_DELETION = frozenset(
    "whats thats whos get gets got getting be is are was were been being on to the a an of at from in by turn turned "
    "turns and or for with it its his her their our my your tea".split())
NOT_AFTER_DELETION = frozenset("behind over out alone off there here on in up back and or".split())


def _deletion_word_in(words, gives=""):
    """Whether `words` use a deletion word as a deletion: it has a source word before it and
    a removed word after it; an ambiguous one (left, leaves) also needs a clear context."""
    ws = str(words).split()
    for i, w in enumerate(ws):
        bare = re.sub(r"\W", "", w).lower()
        if not DELETION_LEAF_WORD.fullmatch(bare):
            continue
        nxt = re.sub(r"\W", "", ws[i + 1]).lower() if i + 1 < len(ws) else ""
        if bare in ("lacking", "lacks") and (not nxt or nxt in ("in", "of")):
            continue  # nothing follows to be taken out ("Sun quite lacking" = DARK), or "lacking in" = without (WILD): round 13
        if (bare in ("drop", "drops") and nxt == "of" and len(gives) > 1) or (bare in ("shed", "sheds", "shedding") and nxt == "light") \
                or (bare in ("lacking", "lacks") and nxt in ("sense", "brains", "wit")) \
                or (bare in AMBIGUOUS_DELETION and nxt in ("wing", "hand", "side", "bank", "field", "back", "luggage")):
            continue  # idioms and nouns: a drop of water, shed light on, one lacking sense (a NIT), left wing
        if bare in AMBIGUOUS_DELETION:
            if i == 0 or i == len(ws) - 1 or re.sub(r"\W", "", ws[i - 1]).lower() in NOT_BEFORE_DELETION \
                    or re.sub(r"\W", "", ws[i + 1]).lower() in NOT_AFTER_DELETION:
                continue
        return True
    return False


def _is_subsequence(small, big):
    it = iter(big)
    return all(c in it for c in small)


def _cut_evidence(node):
    """Whether a leaf folds a cut into its words rather than meaning a short word. It does only when its
    letters run in order through one of its own clue words (pupils -> PUP). Round 18: a deletion verb among the
    words ("sweetheart removing old", "couple losing millions" = ITE) and a longer word its note names (ITEM less
    M) no longer count: 12 of 13 sampled flags of those shapes were judged fine, a phrase read as one synonym."""
    g = wordplay.letters(node["gives"])
    for t in str(node["words"]).split():
        bare = re.sub(r"\W", "", t)
        w = wordplay.letters(bare)
        if DELETION_LEAF_WORD.fullmatch(bare):
            continue  # round 18: "lacking good manners" = RUDE, "losing millions" = ITE read as one phrase (8 of 9 judged fine)
        if len(w) > len(g) and _is_subsequence(g, w):
            return True
    return False  # round 18: a note naming a longer word (ITEM less M, UNION less O) is a synonym phrase, 12 of 13 judged fine


def folded_deletion_leaves(tree):
    """A leaf of 3+ words holding a deletion word (dropping, losing, ...) that gives only a few
    letters cut from one of its words: the deletion is an op, not folded into the leaf (stylish
    man dropping dead -> UDE)."""
    return sum(1 for node in _walk(tree)
               if "words" in node and "gives" in node and "op" not in node and not node.get("unchecked")
               and len(str(node["words"]).split()) >= 3 and len(node["gives"]) <= 4
               and _deletion_word_in(node["words"], node["gives"]) and _cut_evidence(node))


def selection_of_one_letter(tree):
    """A selection with an indicator over a one-letter word (reg<not until the fourth>([a])
    in everyman-4155 15d MEAN): choosing letters of "a" changes nothing, so the indicator was
    hung on the wrong word (it belongs to "round"). Cross-references ("22's", "K2") are not
    one-letter words."""
    n = 0
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") in wordplay.SELECT and node.get("indicators") and not node.get("unchecked") \
                and len(parts) == 1 and isinstance(parts[0], dict) and "op" not in parts[0] \
                and not re.search(r"\d", str(parts[0].get("words") or "")):
            n += len(wordplay.letters(parts[0].get("words"))) == 1
    return n


#: Owner share a word needs when the swap with another op is the corroboration: sundaytimes-5202
#: 22a EGRET files rev<stuffing>(hid<back>(..)): "back" is 92% reversal (the rest selections),
#: "stuffing" 82% container, neither at ROLE_OWNED.
ROLE_SWAP_OWNED = 0.8
#: The looser bar for a mutual swap of two ops (timesjumbo-1807 4d ACKNOWLEDGEMENT: ins<bent>(
#: ana<in possession of>(..), L); sundaytimes-5214 21a DWELLINGS: ins<rebuilt>(ana<around>(..), LL)):
#: each carries a word the corpus files mostly under the other's type, which both ops carrying
#: the other's word at once makes certain. "around" is 79% container and 8% anagram.
ROLE_LOOSE_OWNED = 0.7
ROLE_LOOSE_OWN_MAX = 0.10


def _swap_alike(top, own):
    """Whether an op of type `own` may carry a word whose owner is `top`: the same type, or a
    container word on a hidden word (the exemption above)."""
    return top == own or {top, own} == {"container", "hidden_word"}


def reversal_of_anagram(tree):
    """A reversal with an indicator that wraps an anagram directly while another reversal in the
    tree has none: the reversal indicator ("back") was hung on the anagram, whose own indicator
    already scrambles it, and the real reversal was left bare (mephisto-3148 18a STRESSOR:
    rev<back>(ana<troubled>(rest)) + rev(ROSS))."""
    nodes = [n for n in _walk(tree) if n.get("op") == "reversal" and not n.get("unchecked")]
    bare = any(not n.get("indicators") for n in nodes)
    return sum(1 for n in nodes if bare and n.get("indicators") and any(
        isinstance(p, dict) and p.get("op") == "anagram" for p in n.get("parts") or []))


def _lacks_role(op, kind):
    """Whether op node `op`, of type `kind`, has no indicator, or only ones the corpus never
    files under `kind` (at most ROLE_WEAK of the uses of a word of ROLE_MIN_USES+, or a word
    rarer than that)."""
    for i in op.get("indicators") or []:
        counts = _role_counts(indicator_role_key(i.get("text")))
        total = sum(counts.values())
        if total >= ROLE_MIN_USES and counts.get(kind, 0) > ROLE_WEAK * total:
            return False  # a word the corpus knows for this type; a rarer one ("an anagram of") is no known one
    return True


def _positional_charade(node, key):
    """Whether a POSITION_INDICATORS word on charade `node` plausibly says order. Not when a
    selection op among its pieces has no indicator of its own (quiptic-170 1a ADAMANT
    first(talk): the word belongs to that op), nor "initially" over a run of one-letter pieces
    (cryptic-29255 SCAM: it picks the initials), nor a cover word beside a container or outer
    op (cryptic-29703 HIJACK: "covering" is the container's)."""
    parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
    if any(p.get("op") in wordplay.SELECT and not p.get("indicators") for p in parts):
        return False
    if key in ("initially", "originally", "primarily", "firstly"):
        return not (len(parts) >= 3 and all("op" not in p and len(wordplay.letters(p.get("gives"))) == 1 for p in parts))
    return not any(p.get("op") in ("container", "outer") for p in parts)


def misplaced_indicators(tree):
    """How many indicators on a checked op that the lexicon files only under another op.

    A checked charade of pieces that are bare leaves or in-place anagram / alternate-letters results,
    not held by a container, gets the same leaf-only allowance: its pieces concatenate to its letters, so
    a container word on it is the clue's link (everyman-3776 9d UPBEAT "pub receives penalty regularly":
    anagram(pub) + alternate(penalty))."""
    lex = _indicator_lexicon()
    if not lex:
        return 0
    n = 0
    under_container = {id(p) for c in _walk(tree) if c.get("op") == "container"
                       for p in c.get("parts") or [] if isinstance(p, dict)}
    for node in _walk(tree):
        op = node.get("op")
        if op != "charade" or node.get("unchecked"):
            continue  # the other ops share their words too widely for the lexicon to say
        own = "charade"
        # A charade of bare leaves, not held by a container, whose pieces concatenate to its
        # letters cannot hide a container: a container word on it ("carrying", "accepts",
        # "in") is a link between the pieces (telegraph-31202 6d DIVAN, cryptic-21866 8d DOSH).
        leaf_only = id(node) not in under_container and not any(
            "op" in p for p in node.get("parts") or [] if isinstance(p, dict))
        in_place = id(node) not in under_container and all(
            p.get("op") in (None, "anagram", "alternate") and not p.get("unchecked")
            for p in node.get("parts") or [] if isinstance(p, dict))
        for i in node.get("indicators") or []:
            key = " ".join(w for w in (wordplay.letters(x) for x in str(i.get("text") or "").split()) if w)
            if not key or lex.get(own, {}).get(key, 0) or key.lower() in ORDERING_INDICATORS:
                continue
            if (leaf_only or in_place) and not any(c >= MISPLACED_MIN_USES for t, d in lex.items()
                                     if t not in (own, "container") for c in [d.get(key, 0)]):
                continue
            if key.lower() in POSITION_INDICATORS and _positional_charade(node, key.lower()):
                continue
            if leaf_only and key.lower() in EXAMPLE_MARKERS:
                continue  # "perhaps" marks a leaf as an example of its clue words (times-26889 15d VAN)
            n += any(c >= MISPLACED_MIN_USES for t, d in lex.items() if t != own
                     for c in [d.get(key, 0)])
    return n