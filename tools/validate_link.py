"""Link-word checks of validate_annotations.py: link words are equivalences, clear of other marks, and where app.js places them.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import collections
import functools
import json
import re
from pathlib import Path

from validate_base import indicator_texts, letters, _starts, words_of

# A link word stands in for an equals sign. CORE_LINKS states the rule: it may
# assert equivalence (is, are, 's), derivation (gives, makes, becomes, yields,
# leads to, means, indicates, to locate), plain prepositional joining (for,
# from, of, in, with, by, as, after) or be grammatical glue holding those
# together. Anything else is a content word doing surface work, i.e. padding
# wearing a link word's coat, and it makes the clue a THREE-piece clue.
#
# What real setters use beyond the core is measured, not typed:
# tools/build_clue_joints.py adds every word published clues declare as a link
# word often enough (tools/data/clue_joints.json), and the nightly keeps it current.
CORE_LINKS = frozenset({
    # equivalence
    "is", "are", "was", "were", "be", "been", "being", "am", "s",
    # derivation: the wordplay turns into / hands you the answer
    "gives", "give", "given", "giving", "makes", "make", "made", "making",
    "becomes", "become", "became", "becoming", "yields", "yield", "yielding",
    "produces", "produce", "producing", "provides", "provide", "providing",
    "has", "have", "had", "having", "shows", "show", "showing", "brings",
    "bring", "bringing", "gets", "get", "getting", "got", "leads", "lead",
    "leading", "means", "meaning", "meant", "spells", "spelling", "needs",
    "need", "reveals", "reveal", "revealing", "finds", "find", "finding",
    "locate", "locates", "locating", "indicates", "indicate", "indicating",
    "denotes", "denote", "denoting",
    # prepositional joining
    "for", "from", "in", "of", "with", "to", "into", "as", "by", "at", "on",
    "after", "and", "or",
    # grammatical glue: articles, determiners, pronouns, relatives
    "a", "an", "the", "another", "this", "that", "these", "those", "one",
    "his", "her", "its", "their", "our", "your", "my",
    "what", "who", "whom", "which", "where", "when", "there", "here",
    "it", "he", "she", "they", "you", "we", "i", "not", "no", "all",
})

JOINTS_FILE = Path(__file__).resolve().parent / "data" / "clue_joints.json"


@functools.cache
def joints():
    """tools/data/clue_joints.json, read on first use so its builder can import this."""
    return json.loads(JOINTS_FILE.read_text())


def link_vocabulary():
    """Every word that may stand for an equals sign: the core plus measured use."""
    return CORE_LINKS | set(joints()["linkWords"])


def check_link_words_are_equivalences(tag, ann, errors):
    """A link word has to stand in for an equals sign.

    "lives on" does not. It joins nothing and asserts nothing; it is surface
    padding wearing a link word's coat, and declaring it in `linkWords` makes
    the annotation look sound while the clue is quietly in three pieces —
    wordplay, PADDING, definition. That is the same fault check_two_pieces
    catches when the annotator is honest enough to file it as a block with an
    empty `gives`; this check closes the other door.

    CALIBRATION (unscoped, 74,474 annotated published clues):
    published annotations declare 24,755 link-word phrases. The core plus the
    measured words from tools/build_clue_joints.py cover 96.1% of their tokens;
    the rest is a long tail, no word in it used more than nine times.

    The rule bites on our own clues, where it caught three of twenty: `would be
    better spent` (THERE), `mistake it for` (LEADERSHIP), `lives on` (STOREY).
    None of `lives`, `mistake`, `spent` or `better` is ever declared a link word
    in a published clue. A word published setters do use gets in by measurement,
    not by hand."""
    for lw in ann.get("linkWords", []):
        vocab = link_vocabulary()
        bad = [t for t in words_of(lw) if t not in vocab]
        if bad:
            errors.append(
                f"{tag}: linkWord {lw!r} is not a link word — {', '.join(bad)} asserts no "
                f"equivalence between wordplay and definition. A link word stands in for an "
                f"equals sign (is/gives/makes/for/from/'s); anything else is padding, and a "
                f"clue with padding is in three pieces, not two (AUTHORING.md, 'Link words "
                f"are an equals sign'). Rewrite the clue; tools/build_clue_joints.py adds a word once "
                f"published setters use it")


POSITIONAL_JOINERS = {"on", "after", "behind", "below", "beneath", "under",
                      "following", "supporting"}


def check_link_word_is_clear_of_other_marks(tag, ann, clue, errors):
    """A link word needs a copy of its own in the clue, clear of every indicator
    and every definition.

    app.js claims link words after indicators and definitions, so a connective
    the clue uses twice ("in" inside the indicator and "in" linking) lands on
    the free copy. With no free copy it lands on the other mark, wholly or in
    part. On an indicator it takes words off a hint the solver has paid for:
    times-29616 6D filed "of" inside "on top of", everyman-3925 4D filed "'s
    written" across "written about". Inside a definition it breaks the band and
    the hint calls a word of the definition "just a link": azed-2718 1A, an
    &lit whose whole clue is the definition, filed "with" as a link. A link
    joins wordplay to definition, so it cannot sit inside either; an &lit has
    none. tools/smoke_test.js rejects the render; this rejects the annotation
    before it is committed.
    """
    clue = clue or ""
    placed = place_fragments(ann, clue)
    for kind, lw, i in placed:
        if kind != "link":
            continue
        for other, name in (("ind", "an indicator"), ("def", "the definition")):
            if any(o == other and i < j + len(t) and j < i + len(lw) for o, t, j in placed):
                errors.append(
                    f"{tag}: linkWord {lw!r} has no copy in the clue clear of {name}, "
                    f"so marking it as a link takes words off {name}. Each clue word "
                    f"is one of definition, indicator or link; drop it from one list "
                    f"(an &lit's whole clue is its definition, so it has no link words)")


def check_link_word_is_not_inside_a_block(tag, ann, clue, errors):
    """A link word may not be a word a block parses.

    A link adds no letters, so a word in both lists is counted twice: the page
    marks it a link, and the block's fragment is then never what the clue has
    left. cyclops-491 20A filed "when" as a link and "when that's" as the
    anagram fodder, and the building-blocks rung asked for fodder that took
    back a word the definition rung had called a link. Refused when no choice
    of copies puts every link word on words no block fragment uses.
    """
    clue = clue or ""
    links = [t for t in ann.get("linkWords") or [] if isinstance(t, str) and t]
    frags = [b.get("clueFragment") for b in ann.get("blocks") or [] if isinstance(b, dict)]
    frags = [f for f in frags if isinstance(f, str) and f]
    hits = lambda t: [(i, i + len(t)) for i in _starts(t, clue)]
    link_hits, frag_hits = [hits(t) for t in links], [hits(f) for f in frags]
    if not links or not frags or not all(link_hits + frag_hits):
        return              # a fragment not in the clue is reported elsewhere
    clear = lambda s, taken: not any(s[0] < d and c < s[1] for c, d in taken)

    # Links take words of their own; blocks may share words with each other (a
    # container's outer piece holds its inner one), so given the links' copies
    # each block needs only one copy clear of them.
    def fits(k, taken):
        if k == len(links):
            return all(any(clear(s, taken) for s in fh) for fh in frag_hits)
        return any(fits(k + 1, taken + [s]) for s in link_hits[k] if clear(s, taken))

    if not fits(0, []):
        fix = "; ".join(link_in_block_hints(ann, links)) or "drop it from one list"
        errors.append(
            f"{tag}: linkWords {links} have no copy in the clue clear of the block "
            f"fragments {frags}, so a word is counted twice: once as a "
            f"link adding no letters, once as wordplay. Each clue word is either link "
            f"or wordplay: {fix}")


def link_adds_nothing(frag, lw, gives):
    """True when a block's `gives` is drawn from its fragment's own letters
    (anagram, hidden or selected fodder) and the fragment without `lw` still
    holds every one of them: the link word gives the block nothing ("met with
    fatal" giving METFATAL), so it is no fodder."""
    want, have = collections.Counter(letters(gives)), collections.Counter(letters(frag))
    if not want or want - have:
        return False
    return not want - collections.Counter(letters(frag.replace(lw, " ", 1)))


def link_in_block_hints(ann, links):
    """The edit to make for each link word sitting inside a block fragment, said
    in the clue's own words, so the fix takes one turn and not a guess."""
    out = []
    for lw in links:
        for b in ann.get("blocks") or []:
            frag = b.get("clueFragment") if isinstance(b, dict) else None
            if not isinstance(frag, str) or lw not in frag:
                continue
            gives = b.get("gives")
            if frag == lw:
                out.append(f"the block {frag!r} is the link word itself: if it gives "
                           f"{letters(gives) or 'no letters'}, take {lw!r} out of linkWords, "
                           f"else drop the block")
            elif link_adds_nothing(frag, lw, gives):
                left, _, right = frag.partition(lw)
                parts = [x.strip(" ,;:") for x in (left, right) if x.strip(" ,;:")]
                out.append(f"{lw!r} gives none of {letters(gives)}, so it is not fodder: "
                           + (f"cut the block {frag!r} to {parts[0]!r}" if len(parts) == 1 else
                              f"split the block {frag!r} into {' and '.join(map(repr, parts))}"))
            elif frag.startswith(lw) or frag.endswith(lw):
                rest = (frag[len(lw):] if frag.startswith(lw) else frag[:-len(lw)]).strip(" ,;:")
                out.append(f"if {lw!r} only links, the block is {rest!r}; if the block "
                           f"uses its letters, take {lw!r} out of linkWords")
            else:
                out.append(f"{lw!r} is inside the block {frag!r}: if the block uses its "
                           f"letters, take it out of linkWords")
    return out


def place_fragments(ann, clue):
    """Where app.js placedFragments() puts each fragment: (kind, text, index).

    A copy of the app's rule, because the check above is only true if it agrees
    with the render. Definitions claim their stored `at`; the rest take the best
    occurrence still free, longest first, link words last. Ranking is whole word
    and free, then whole word, then free, earliest on a tie. An edge binds only
    where it is a letter, so "'s" may weld to the word before it.
    """
    is_letter = lambda c: c.isascii() and c.isalpha()
    frags = [("def", d.get("text"), d.get("at")) for d in ann.get("definitions") or []
             if isinstance(d, dict)]
    frags += [("ind", t, None) for t in indicator_texts(ann)]
    frags += [("link", t, None) for t in ann.get("linkWords") or [] if isinstance(t, str)]
    frags = [(k, t, at, n) for n, (k, t, at) in enumerate(frags) if t]
    taken, placed = [], []
    free = lambda i, n: not any(i < j + m and j < i + n for j, m in taken)
    for k, t, at, _ in frags:
        if at is None:
            continue
        if isinstance(at, int) and at >= 0 and clue[at:at + len(t)] == t:
            taken.append((at, len(t)))
            placed.append((k, t, at))

    def best(t):
        n, best_i, best_r = len(t), -1, 9
        i = clue.find(t)
        while i >= 0:
            edge = lambda x, y: x < len(clue) and y >= 0 and is_letter(clue[x]) and is_letter(clue[y])
            b = not edge(i, i - 1) and not edge(i + n, i + n - 1)
            f = free(i, n)
            r = 0 if b and f else 2 if b else 3 if f else 4
            if r < best_r:
                best_i, best_r = i, r
            i = clue.find(t, i + 1)
        return best_i

    rest = sorted((f for f in frags if f[2] is None),
                  key=lambda f: (f[0] == "link", -len(f[1]), f[3]))
    for k, t, _, _ in rest:
        i = best(t)
        if i >= 0:
            taken.append((i, len(t)))
            placed.append((k, t, i))
    return placed


def check_indicator_does_not_straddle_a_definition(tag, ann, clue, errors):
    """An indicator may not straddle a definition's edge.

    Inside a definition is an &lit, and app.js nests the marks. Across its edge
    the marks collide, one of them cannot be shown, and a hint the solver bought
    leaves the screen: independent-12233 3D filed "in the
    middle of" as the indicator and "of the sea" as the definition.
    tools/smoke_test.js rejects the render; this rejects the annotation first.
    """
    spans = []
    for d in ann.get("definitions") or []:
        t = d.get("text") or ""
        at = d.get("at", clue.find(t))
        if t and at is not None and at >= 0:
            spans.append((at, at + len(t)))
    for ind in indicator_texts(ann):
        hits = list(_starts(ind, clue)) if ind else []
        if hits and all(any(i < e and i + len(ind) > s and not s <= i < i + len(ind) <= e
                                for s, e in spans) for i in hits):
            errors.append(
                f"{tag}: indicator {ind!r} runs across the edge of the definition, so the "
                f"two cannot both be marked. Take the shared words off one of them")


def check_link_word_is_not_an_order(tag, ann, clue, warnings):
    """A link word that put the pieces in that order is an indicator.

    In 30,099 25A, "Post on half of wage when things are developing", `on` is
    why the post ends up at the BACK of the answer: across the grid, one thing
    written on another has been reached after it. The word carries the only
    instruction in the clue, so filing it under linkWords makes the page say it
    "contributes no letters of its own" and never says why the post comes second.

    Flagged only where the joiner is demonstrably the thing that did the
    reordering: two blocks listed in the opposite order from the clue, the
    joiner sitting between them, and no declared indicator between them to take
    the blame instead. A container or reversal that shuffles the blocks past
    each other therefore clears the joiner, which is the point — `model in
    Channel Islands on ecstasy` (everyman-4093 9A) is reordered by `in`, and
    `on` there really is joinery.

    CALIBRATION (the whole corpus): 65 entries declare a positional
    joiner as a link word and 12 of them list blocks out of clue order, but only
    3 survive the two conditions above — 30,099 25A and indysunday-1885 14A and
    25A. All three are real, and the two Filbert ones are the proof: their
    walkthroughs SAY "in an across clue one thing 'on' another sits after it"
    and file `on` as a link word in the same breath. A warning, because three
    is a thin sample for an error."""
    joiners = [w for w in ann.get("linkWords", [])
               if w.strip().lower() in POSITIONAL_JOINERS]
    if not joiners:
        return
    blocks = [b for b in ann.get("blocks", []) if b.get("gives") and b.get("clueFragment")]
    pos = [clue.find(b["clueFragment"]) for b in blocks]
    if len(pos) < 2 or any(p < 0 for p in pos):
        return
    ind_at = [clue.find(i) for i in indicator_texts(ann)]
    for a in range(len(pos) - 1):
        if pos[a] <= pos[a + 1]:
            continue
        lo, hi = pos[a + 1], pos[a]
        if any(lo < p < hi for p in ind_at):
            continue
        for w in joiners:
            m = re.search(r"\b%s\b" % re.escape(w.strip()), clue, re.I)
            if not m or not lo < m.start() < hi:
                continue
            warnings.append(
                f"{tag}: the clue reads {blocks[a + 1]['clueFragment']!r} then "
                f"{blocks[a]['clueFragment']!r} and the answer takes them the other "
                f"way round, with linkWord {w!r} standing between them and no "
                f"indicator that could have done it — so {w!r} is what reversed them, "
                f"and a word that orders the wordplay is an indicator, not an equals "
                f"sign. Move it to `indicators` as {{\"text\": {w!r}, \"for\": ..., \"note\": ...}} "
                f"with a note saying which piece it sends second")
            return