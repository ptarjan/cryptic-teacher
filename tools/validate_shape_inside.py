"""Wordplay-tree shape detectors of validate_annotations.py, part 3: bare initials, deletion and container inside a component, shared indicators.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import functools
import itertools
import re
import wordplay

from validate_shape_base import _walk, _attested, _EXTRA_PAIRS, _known_pair, _POSITION_WORD
from validate_shape_ops import (
    NEEDS_INDICATOR, _repeated_copies, _moved_letter_ops, _self_signed_ops, _self_holding_containers,
    _lone_implicit_op, _lone_bare_sound, _lone_bare_first, _paired_ends, _picks_with_indicator,
    _outer_in_boundary_container, _chained_deletions, _substituting_containers,
)
from validate_shape_folds import _indicator_lexicon

#: Two ways a wrong clue passed every check (a resample of 100 passing clues found 4
#: wrong, 10-18); each is a ratchet field. The evaluator takes a leaf's `gives` as filed
#: and removes a deletion's letters from anywhere, so neither could be seen.
#:   * BARE_INITIAL: a leaf giving the first letter of its word where no abbreviation
#:     says so and no selection op sits above it (ZOCCO's `first` missing);
#:   * DELETION_SCOPE: a deletion over a charade whose indicator names an end and whose
#:     removed letters are not at that end (BORON, BORE+ON less E, "endlessly").
#: Two more were measured over the 506k trees and dropped, under the 80% bar:
#:   * a synonym nothing else attests (URTICARIA, [priest] ICA): 3-4 letter values that
#:     are no lexicon word and no known pair were about 15% wrong-looking (names, rivers
#:     and places are mostly right), with a corpus count of one about 35%: a fake synonym
#:     needs a thesaurus, not a table;
#:   * an indicator word filed as a leaf (MIMICS, [doubly]IM): "doubly" is not in the
#:     indicator lexicon, and short values on lexicon indicators (without EX, around C)
#:     were about 15% wrong; the narrow form, a repetition word valued like the leaf
#:     before it (117 clues), reads right to a solver ([twice]IT after [sex]IT) and a
#:     redo has no other way to write a repeat.
BARE_INITIAL = "leaf gives the first letter of its words with no selection"
DELETION_SCOPE = "deletion whose removed letters are not where its indicator says"
#: Two more, from the second resample (10-18, 7 wrong in 100 passing clues); see
#: wrong_role_indicators and deletion_inside_component. Measured over the 506k trees,
#: 20 random hits each judged by hand: 951 hits, 20/20 (and 20/20 on a second draw
#: before the lone-flag corroboration) for the role rule; 1124 hits, 20/20 and 20/20 for
#: the deletion rule. A third, a leaf giving a non-word (MORECAMBE CAMBE), was dropped:
#: 138k leaves give a letter string the word list lacks, and 17 of 20 sampled were right.
WRONG_ROLE = "indicator filed on an op of another type"
CONTAINER_INSIDE = "container over a charade whose piece goes in inside one piece of it"
DELETION_INSIDE = "deletion over a charade that takes letters from one piece, or a whole piece the charade added"
#: Round 7 (12 of 300 passing clues wrong, 4.0%): five shapes the earlier rules passed. Each hit
#: sample of 20 was judged by hand against the same standard as the rules above.
UNINDICATED_BARE = "op with no indicator of its own (or one indicator shared by several ops)"
SHARED_INDICATOR = "indicator words claimed twice: on two ops, or also as a leaf's clue words"
HALF_LEAF = "leaf giving half of its word with no op carrying the half"
DELETION_SCATTERED = "one 'half' deletion over several words, its letters picked out of all of them"
REVERSE_PHRASE = "reverse reading over a whole phrase of the clue"


def _abbreviation_pair(words, gives):
    """Whether the abbreviation table (not the usage lexicon, which holds letters that were picked
    from the word) or the extra pairs give `words` as the letter `gives`."""
    pairs, _ = _attested()
    key = re.sub(r"[^A-Z]", "", str(words).upper())
    return (key, gives) in pairs or (key, gives) in _EXTRA_PAIRS


def _word_leaves(tree):
    """(leaf, ancestors) for every leaf of clue words with a `gives`, each ancestor an op node."""
    stack = [(tree, ())] if isinstance(tree, dict) else []
    while stack:
        node, anc = stack.pop()
        stack += [(p, anc + (node,)) for p in node.get("parts") or [] if isinstance(p, dict)]
        if "op" not in node and node.get("words") and node.get("gives"):
            yield node, anc


BARE_INITIAL_MIN_LETTERS = 6
_ORDINALS = {w.upper(): chr(65 + i) for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth "
    "fifteenth sixteenth seventeenth eighteenth nineteenth twentieth".split())}


_ACROSTIC_WORD = re.compile(r"\b(primarily|originally|initially|firstly|at first|for starters|first of all|"
                            r"to begin with|at the start|in the beginning|at the outset)\b", re.I)


def _acrostic_run(leaf, anc):
    """Whether `leaf` stands in a charade beside a first-letter pick that carries the indicator
    ("primarily", "originally"): one indicator over the run of initials (round 15, 3 of 8 judged-fine
    bareInitial flags: first<primarily>(Proudly) + impenitent I + artiste A ...)."""
    return any(a.get("op") == "charade" and any(
        isinstance(p, dict) and p.get("op") == "first" and any(
            _ACROSTIC_WORD.search(str(i.get("text") or "")) for i in p.get("indicators") or [])
        for p in a.get("parts") or [])
        and any(p is leaf for p in a.get("parts") or []) for a in anc)


def _position_word_cut(leaf, anc):
    """Whether `leaf` is the cut part of a deletion and its own words name the end ("leader" -> L)."""
    return bool(_POSITION_WORD.search(str(leaf.get("words") or ""))) and any(
        a.get("op") == "deletion" and any(p is leaf for p in (a.get("parts") or [])[1:]) for a in anc)


def _split_word_leaf(leaf, anc):
    """Whether a sibling leaf holds the same word and gives its tail: one word split into its
    first letter and the rest (ins(STRIPED, P) from "pinstriped")."""
    w, g = wordplay.letters(leaf["words"]), wordplay.letters(leaf["gives"])
    return any(a.get("op") for a in anc[-1:]) and any(
        p is not leaf and isinstance(p, dict) and "op" not in p and wordplay.letters(p.get("words")) == w
        and len(wordplay.letters(p.get("gives"))) >= 3 and w.endswith(wordplay.letters(p.get("gives")))
        for p in anc[-1].get("parts") or [])


def bare_initials(tree):
    """Leaves of one clue word of BARE_INITIAL_MIN_LETTERS+ letters that give its first
    letter, where no selection op is above the leaf and the word has no one-letter
    reading in the abbreviation table or the usage lexicon. The initial was picked by a
    clue word elsewhere ("primarily") that no op carries, or by none (ZOCCO).
    Measured 10-18 over 506k trees: with shorter words, or two letters, a third to a
    half of the hits were abbreviations the tables lack (CO company, L little, E Earl's);
    this form was 23 of 25 real."""
    pairs, usage = _attested()
    if not usage:
        return 0  # no usage lexicon here: stand down
    n = 0
    for leaf, anc in _word_leaves(tree):
        gives = wordplay.letters(leaf["gives"])
        words = wordplay.letters(leaf["words"])
        bare = wordplay.letters(re.sub(r"['’]s\b", "", leaf["words"], flags=re.I))  # "volume's" reads as volume
        if len(gives) != 1 or len(leaf["words"].split()) != 1 or len(words) < BARE_INITIAL_MIN_LETTERS \
                or not words.startswith(gives) or leaf.get("select"):
            continue
        if any(a.get("op") in wordplay.SELECT for a in anc):
            continue
        if any(a.get("op") == "deletion" and any(p is leaf for p in (a.get("parts") or [])[1:])
               and any(wordplay.letters(i.get("text")) == words or _POSITION_WORD.search(str(i.get("text") or ""))
                       for i in a.get("indicators") or []) for a in anc):
            continue  # del<Wifeless>(.., [Wifeless]W): the words that cut name what is cut (RIGHTING)
        if words in _ORDINALS and _ORDINALS[words] == gives:
            continue  # twentieth is T, the twentieth letter (FILET)
        if _acrostic_run(leaf, anc) or _position_word_cut(leaf, anc) or _split_word_leaf(leaf, anc):
            continue
        # kilograms -> K as kilos are: the unit's long form is its prefix's word plus "gram(s)"
        forms = {words, bare, re.sub(r"GRAMS?$", "", bare)}
        forms |= {wordplay.letters(h) for h in re.split(r"[-‐-―]", str(leaf["words"]))}  # gravity-force -> G
        if not any(len(k) == 1 for w in forms for k in usage.get(w, {})) and not _known_pair(leaf["words"], gives) \
                and not any((w, gives) in pairs for w in forms):
            n += 1
    return n


_DEL_END = re.compile(
    r"\b(endless(ly)?|unending|curtail\w*|docked|tailless|detailed|unfinished|incomplete|not finished|"
    r"cut short|shortly|shortened|short|abridged|truncated|clipped|almost|nearly|not quite|"
    r"(?:without|losing|dropping|missing|lacking|shedding|abandoning) (?:its |his |her |their |the |an? )?"
    r"(?:end|tail|finish|finishing|ending|last))\b", re.I)
_DEL_HEAD = re.compile(
    r"\b(headless(ly)?|beheaded|topless|decapitated|unopened|leaderless|not starting|"
    r"(?:without|losing|dropping|missing|lacking|shedding|abandoning) (?:its |his |her |their |the |an? )?"
    r"(?:head|top|lead|start|opening|first|beginning))\b", re.I)


#: Indicators that point inside a word, so a deletion by one may take a middle letter.
_DEL_MIDDLE = re.compile(r"\b(heart|centre|center|middle|core|inside|interior|gutted|empty|emptied|hollow|"
                         r"disheartened|heartless|innards|guts|bowels|ends?|edges?|extremities|"
                         r"outsides?|regularly|alternate|odd|even)\w*", re.I)


#: The middle indicators that name the heart of a word, which a deletion may take from
#: one piece of a charade when the letters are not the whole's centre.
_DEL_HEART = re.compile(r"\b(heart|centre|center|middle|core|disheartened|heartless|half-?hearted)\w*", re.I)
_DEL_HALF = re.compile(r"\bhalf\b|\bhalf-", re.I)


#: Bare function words whose letters a deletion over their phrase may take (independent-11544
#: 25a THROW: THE+ROW less E, "saving energy").
FUNCTION_PIECES = frozenset("THE A AN OF TO AND IN".split())
#: How far from the exact middle of the whole a cut may sit and still be "the heart of the whole".
HEART_SLACK = 1


def deletion_inside_component(tree, clue=None, answer=None):
    """Deletions over a charade (indicator anywhere in the clue) that take letters from
    ONE piece, or take whole pieces the charade added. ARCH+IDEA+CON less I,
    "originally dismissed" after "notion" (indysunday-1538 9d): an indicator acts on the
    piece it sits by, so the deletion is del(IDEA, I) inside the charade. Three forms,
    each with every reading of the removed letters:
      - letters strictly inside one piece, touching neither end of the whole, with an
        indicator that names no end, head or middle (a heart word counts when the letters
        are not the whole's own centre; "half" counts when they touch the whole's end);
        CON+SIDE+RABBLE less B, "half-hearted" (sundaytel-2922 3d), DIAL+SECT less S,
        "ignoring singular" (everyman-3750 11a), FAVE+LAGS less GS, "half-cut"
        (sundaytimes-4834 21d), whether the indicator is among the pieces or after them;
      - letters that are exactly whole pieces: a charade adds a piece for the deletion to
        remove (NICE+ICE less NICE; Actor+more+English less EE, telegraph-30860 20a); also
        when one reading is such a piece and another sits inside a different one (A+CHING+I
        less I, ACHING: the I that goes is the piece just added);
      - letters at the whole's own end or start that are wholly inside the last or first
        piece, whatever the indicator (round 6, 4 of 12 resampled false negatives: FAT+ALE
        less E "finished early", RAM+BUNCH less H "mostly", ODO+ROUSE less E "endless"):
        the same cut is del(ALE, E) inside the charade, which is where the indicator sits.
        3699 newly counted over the corpus, 20 of 20 sampled judged wrong.
    With `answer`, a deletion that is the whole tree is also read on only the readings that
    leave the answer (round 7: INSPIRATION, IN+SPIN+RATION less N "before its conclusion":
    the N that makes the answer is SPIN's, but the other Ns made the letters ambiguous).
    Needs the clue text; with none it counts nothing."""
    if not clue:
        return 0
    n = 0
    want_all = wordplay.letters(answer) if answer else None
    fodder = {id(p) for a in _walk(tree) if a.get("op") == "anagram" for p in a.get("parts") or [] if isinstance(p, dict)}
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") != "deletion" or len(parts) < 2 or node.get("unchecked") \
                or not all(isinstance(p, dict) for p in parts) or parts[0].get("op") != "charade":
            continue
        text = " ".join(str(i.get("text") or "") for i in node.get("indicators") or [])
        comps = parts[0].get("parts") or []
        if len(comps) < 2 or not all(isinstance(c, dict) for c in comps):
            continue
        try:
            cvals = [sorted(wordplay.values(c)) for c in comps]
            cuts = [sorted(wordplay.values(p)) for p in parts[1:]]
        except Exception:
            continue
        if any(not v for v in cvals) or any(not v for v in cuts):
            continue
        heart, half = bool(_DEL_HEART.search(text)), bool(_DEL_HALF.search(text))
        named = bool(_DEL_END.search(text) or _DEL_HEAD.search(text) or (_DEL_MIDDLE.search(text) and not heart))
        for want in ((None, want_all) if want_all and node is tree else (None,)):
            seen, in_piece, whole_pieces = 0, True, True
            end_piece, any_piece, seam, in_function, all_centred = True, False, False, True, True
            for combo in itertools.product(*cvals):
                f = "".join(combo)
                bounds = [0]
                for c in combo:
                    bounds.append(bounds[-1] + len(c))
                for rs in itertools.product(*cuts):
                    for r in {"".join(rs), "".join(reversed(rs))}:
                        if not r:
                            continue
                        for m in re.finditer("(?=" + re.escape(r) + ")", f):
                            s, e = m.start(), m.start() + len(r)
                            if want and f[:s] + f[e:] != want:
                                continue
                            seen += 1
                            one = any(a <= s and e <= b for a, b in zip(bounds, bounds[1:]))
                            is_piece = any(a == s and b == e for a, b in zip(bounds, bounds[1:]))
                            # a doubled letter at the end (CAL[L], MIT[T]) leaves the same word cut either way
                            edge = s == 0 or e == len(f) or f[:s] + f[e:] in (f[len(r):], f[:-len(r)])
                            centred = abs(s - (len(f) - len(r)) / 2) <= HEART_SLACK
                            # a letter doubled across a seam (HOPS+SCOTCH less S) is the seam's, not one piece's
                            seam = seam or (e in bounds[1:-1] and f[e:e + len(r)] == r) \
                                or (s in bounds[1:-1] and s >= len(r) and f[s - len(r):s] == r)
                            # letters out of a bare function word ("the" in THE+ROW less E, "saving
                            # energy") are the phrase's: the cut takes them from the whole phrase
                            in_function = in_function and any(
                                a <= s and e <= b and "op" not in c and wordplay.letters(c.get("words")) in FUNCTION_PIECES
                                for (a, b), c in zip(zip(bounds, bounds[1:]), comps))
                            whole_pieces = whole_pieces and s in bounds and e in bounds
                            all_centred = all_centred and centred  # BROOCH+URE less O: one O is off-centre
                            in_piece = in_piece and one and not is_piece and (not edge or half)
                            end_piece = end_piece and one and not is_piece and edge
                            any_piece = any_piece or is_piece
            # anagram fodder whose cut letters sit in one piece only (BORSTAL: Bolts+are less E,
            # "endlessly"; round 9, 5 of 5 sampled fine): the indicator is by that piece and the
            # scramble hides the seam, so the inner deletion would say nothing more; not for "not half": the half
            # is one piece's (azed-2517 31a SEAMANLIKE, round 12)
            # round 18: also when the letters occur in several pieces (TAKE+RECEIPT less E, HEADWAY+SURRENDER
            # less E; 5 of 6 judged fine): a scramble hides every seam, so only a piece the charade added counts
            lone = id(node) in fodder and not half
            if seen and ((not named and in_piece and not seam and not in_function and not (heart and all_centred)
                          and not lone) or whole_pieces or (end_piece and not lone) or any_piece):
                n += 1
                break
    return n


def container_inside_component(tree, answer=None):
    """1 when the whole tree is a container over a charade holder whose piece goes in at gaps
    that all lie inside ONE of the holder's pieces, never at a join (timesjumbo-1490 38d
    LIVINGWAGE: ins(LIV+IN+GAGE, W) is really LIV+IN+G(W)AGE; toughie-3357 17d LASTGASP:
    ins(LAG+ASP, ST) is LA(ST)G+ASP). The indicator acts on the one piece it sits by, so the
    container goes inside the charade: ins(piece, letters). The evaluator lets the piece land
    at any gap, so the wide holder passed. A container under another op (everyman-3751 8d
    ELEANORRIGBY: ins(E+LEAN+ORB, RIG) is OR(RIG)B, in a charade with Y) is read on a result that
    sits inside the answer. Needs the answer; with none it counts nothing."""
    if not answer or not isinstance(tree, dict):
        return 0
    want = wordplay.letters(answer)
    # a container right under reversals that are the whole tree is read on the answer turned back
    # (ftcryptic-17934 3d TRADESMAN: rev(ins(NAMED+ART, S)): the S goes inside NAMED, round 12)
    top, flips = tree, 0
    while top.get("op") == "reversal" and not top.get("unchecked") and len(top.get("parts") or []) == 1 \
            and isinstance(top["parts"][0], dict):
        top, flips = top["parts"][0], flips + 1
    if flips and top.get("op") == "container":
        rest = sum(_container_inside(node, want, False) for node in _walk(top) if node is not top)
        return rest + _container_inside(top, want[::-1] if flips % 2 else want, True)
    return sum(_container_inside(node, want, node is tree) for node in _walk(tree))


def _container_inside(tree, want, whole):
    """1 when container `tree` puts its piece only inside one piece of its charade holder, its
    result being the answer `want` (`whole`) or a stretch of it."""
    if tree.get("op") != "container" or tree.get("unchecked"):
        return 0
    parts = tree.get("parts") or []
    if len(parts) != 2 or not all(isinstance(p, dict) for p in parts) or parts[0].get("op") != "charade" \
            or parts[0].get("unchecked"):
        return 0
    comps = parts[0].get("parts") or []
    if len(comps) < 2 or not all(isinstance(c, dict) for c in comps):
        return 0
    # one selection over several words (last<tips from>(Wills, Kate)) is one letter per word: the
    # join between those words is a join between pieces, where the wide holder is fair
    comps = [x for c in comps for x in (
        [{**c, "parts": [q]} for q in c["parts"]]
        if c.get("op") in wordplay.SELECT and len(c.get("parts") or []) > 1 and not c.get("unchecked")
        and all(isinstance(q, dict) for q in c["parts"]) else [c])]
    try:
        cvals = [sorted(wordplay.values(c)) for c in comps]
        ins = sorted(wordplay.values(parts[1]))
    except Exception:
        return 0
    seen = False
    for combo in itertools.product(*cvals):
        f = "".join(combo)
        bounds = {0}
        for c in combo:
            bounds.add(max(bounds) + len(c))
        for i in ins:
            for k in range(1, len(f)):
                got = f[:k] + i + f[k:]
                if got == want if whole else (len(got) < len(want) and got in want):
                    if k in bounds:
                        return 0  # one reading puts it at a join: the wide holder is fair
                    seen = True
    return int(seen)


def deletion_scope(tree, any_whole=False, answer=None):
    """Deletions over a charade (or, with `any_whole`, over anything) whose indicator
    names one end and where no reading of the removed letters sits at that end of the
    whole. The evaluator removes the letters from anywhere (BORE+ON less E spells BORON
    though "endlessly" takes the N). With `answer`, a deletion that is the whole tree also has
    to leave the answer: (SURE+F+ACE) less E "nearly" leaves SUREFAC at the end of the whole,
    but the E that makes SURFACE is SURE's, so "nearly" acts on SURE alone (timesjumbo-1479
    19d, round 11)."""
    n = 0
    want = wordplay.letters(answer) if answer else None
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") != "deletion" or len(parts) < 2 or not all(isinstance(p, dict) for p in parts):
            continue
        if not any_whole and parts[0].get("op") != "charade":
            continue
        text = " ".join(str(i.get("text") or "") for i in node.get("indicators") or [])
        end, head = bool(_DEL_END.search(text)), bool(_DEL_HEAD.search(text))
        if end == head:
            continue
        try:
            wholes = wordplay.values(parts[0])
            cuts = [sorted(wordplay.values(p)) for p in parts[1:]]
        except Exception:
            continue
        ok = False
        for f in wholes:
            for rs in itertools.product(*cuts):
                for r in {"".join(rs), "".join(reversed(rs))}:
                    hit = f.endswith(r) if end else f.startswith(r)
                    if hit and want and node is tree:
                        hit = (f[:len(f) - len(r)] if end else f[len(r):]) == want
                    ok = ok or hit
        n += not ok
    return n


def deletion_scope_answer(tree, answer):
    """Deletions the plain deletion_scope passes that fail once the answer picks the reading:
    the whole tree is (SURE+F+ACE) less E "nearly", a final E exists (ACE's) so the end reads
    fine, but the E whose loss makes SURFACE is SURE's (timesjumbo-1479 19d, round 11)."""
    return max(0, deletion_scope(tree, answer=answer) - deletion_scope(tree)) if answer else 0


#: Selections that two adjacent words may share one indicator for ("so extend tops" over
#: first(so) + first(extend)) and the sound pair ("doubly" over two homophones): the one
#: shared form a solver is still told the truth by (cyclops-591 7d SPARSE judged fine in
#: round 7). Any other op, or three of these, with one indicator is a lie about the clue.
#: "deletion" joins them (round 14, 10 of 28 sampled false flags): "Reserve volume endlessly", "kings
#: must leave" cut one letter from each of two neighbouring words, the one indicator's plural or
#: position says both; _pair_adjacent holds the two to neighbouring words as for a selection.
_SHARED_OK = frozenset(wordplay.SELECT) | {"homophone", "deletion"}


def unindicated_uncovered(tree):
    """Checked ops that need an indicator and have none, other than the second of an
    adjacent pair of one selection or homophone op whose twin carries the indicator.
    unindicated_ops counts those too; this is the stricter reading (round 7, 12 of 300
    passing clues wrong: VIOLA, mid<essentially> shared by three middles; MARACA, one
    "all names withheld" over three deletions; ETUI, CHATE, the insertion and the hidden
    word nothing signals). Same exclusions as unindicated_ops."""
    spoken = {id(p) for s in _walk(tree) if s.get("op") == "spoonerism"
              for p in s.get("parts") or [] if isinstance(p, dict) and p.get("op") == "homophone"}
    n = 0
    copies = _repeated_copies(tree) | _moved_letter_ops(tree) | _self_signed_ops(tree) \
        | _self_holding_containers(tree) | _chained_deletions(tree) | _substituting_containers(tree) \
        | _lone_implicit_op(tree) | _lone_bare_sound(tree) | _paired_ends(tree) | _picks_with_indicator(tree) \
        | _outer_in_boundary_container(tree) | _lone_bare_first(tree)
    for parent in [{"parts": [tree]}] + list(_walk(tree)):
        groups = {}
        kids = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        for p in kids:
            if p.get("op") in NEEDS_INDICATOR and not p.get("unchecked") \
                    and id(p) not in spoken and id(p) not in copies:
                groups.setdefault(p["op"], []).append(p)
        for op, ns in groups.items():
            bare = [x for x in ns if not x.get("indicators") and not _folded_signal(x, len(ns) == 1)]
            if op == "deletion" and parent.get("op") == "deletion" and parent.get("indicators"):
                # del(del(Variety, five), lines) "taken from": one indicator over both cuts (EAUDEVIE)
                bare = [x for x in bare if x is not kids[0]]
            if bare and (op in wordplay.SELECT or op == "deletion") and len(ns) > 2 and _list_run(kids, ns):
                continue  # initials of a list: the one indicator stands at the run's end (GARB)
            if bare and not (op in _SHARED_OK and len(ns) == 2 and len(bare) == 1 and _pair_adjacent(ns)):
                n += len(bare)
    return n


#: The most clue characters (one short word and its spaces) that may lie between the two words one
#: shared selection or sound indicator serves: "so extend tops", not "Marsh was awash with plants
#: initially" (times-29450 6a SWAMP, round 12).
SHARED_PAIR_GAP = 5


def _pair_adjacent(ns):
    """Whether two same-op nodes stand side by side in the clue, each counted with its indicator (or
    have no places given). Only picks of letters are held to it: a pair of sounds shares its one
    indicator across a longer stretch (cyclops-591 7d, round 7)."""
    if ns[0].get("op") not in wordplay.SELECT and ns[0].get("op") != "deletion":
        return True
    spans = []
    for x in ns:
        items = [(q["at"], q["at"] + len(q["words"])) for q in _walk(x)
                 if "op" not in q and q.get("words") and isinstance(q.get("at"), int)]
        items += [(i["at"], i["at"] + len(str(i.get("text") or ""))) for q in _walk(x)
                  for i in q.get("indicators") or [] if isinstance(i, dict) and isinstance(i.get("at"), int)]
        leaves = [q for q in _walk(x) if "op" not in q and q.get("words")]
        if not items or any(not isinstance(q.get("at"), int) for q in leaves):
            return True
        spans.append((min(a for a, _ in items), max(b for _, b in items)))
    (a0, a1), (b0, b1) = sorted(spans)
    return b0 - a1 <= SHARED_PAIR_GAP


#: Words an op's indicator can be a prefix or suffix of inside one compound clue word
#: (Oversell = over + sell, heartbroken = heart + broken), beside the indicator lexicon's.
_FOLD_AFFIX = {"reversal": ("over", "back", "about", "return", "upset"),
               "anagram": ("broken", "mixed", "wild", "crazy", "drunk"),
               "first": ("top", "head", "leader"),  # mountaintop -> M (nation-3423 19a FARM); redhead, ringleader, knucklehead (round 12)
               "last": ("tail", "foot", "bottom")}
_FOLD_PHRASE = {op: re.compile(r"(?:%s)\s+(?:of|in|from)\s+\w+" % words, re.I) for op, words in (
    ("outer", "extremes|ends|edges|sides|borders|limits|fringes|outskirts|boundaries|extremities|margins"),
    ("first", "first|initial|opening|start|head|top|beginning|front|half|drop"),
    ("last", "final|last|end|close|closing|ending|tail|finish|back|bottom|half"),
    ("nth", "second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth"),
    ("middle", "heart|centre|center|middle|core"))}


_NOPOSS = re.compile(r"(?!)")
#: Compounds that end in an affix word but are not a pick of the other word (a skinhead is a person; round 11).
_NOT_COMPOUND = frozenset()  # round 14: skinhead is S in two judged-fine clues (STALKER, SURFEIT); no longer excluded
#: "champion's top": the leaf's own words end in the pick's word after a possessive (round 12 UNEXCITED).
_FOLD_POSS = {op: re.compile(r"^\S+['\u2019]s?\s+(?:%s)$" % words, re.I) for op, words in (
    ("first", "first|initial|opening|start|head|top|beginning|front"),
    ("last", "final|last|end|close|closing|ending|tail|finish|bottom"),
    ("nth", "second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth"))}


def _folded_signal(node, alone=True):
    """Whether bare op `node` holds one leaf whose single clue word is a compound with the op's
    indicator at an edge and 3+ letters of the other word left (Oversell for a reversal), or a
    pick the leaf's own words name (final of competition, champion's top), or a pick of a word
    whose first letter is a known reading of it (first(President) is P: the leaf could be P), or
    an anagram whose fodder leaf carries the indicator as a prefix or suffix (Outdated -> DATED).
    The known-pair reading is for a pick that stands alone: two picks of one op beside an indicator
    that serves both (Marsh, plants initially) leave the first with none."""
    ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
    if node.get("op") in ("container", "hidden"):
        # roundabout = round + about (FE around RE), Something = some + thing (HINGIS hidden in "thing I s..."):
        # a leaf word that opens or closes with the op's own well-used indicator (round 13)
        kind = "container" if node["op"] == "container" else "hidden_word"
        for p in ps:
            ws = str(p.get("words") or "").split()
            if "op" in p or not ws or (node["op"] == "container" and len(ws) != 1):
                continue
            edges = [wordplay.letters(ws[0]).upper()] + ([wordplay.letters(ws[-1]).upper()] if len(ws) > 1 else [])
            if any(len(w) - len(k) >= 3 and (w.startswith(k) if i == 0 else w.endswith(k))
                   for i, w in enumerate(edges) for k in _compound_indicator_keys(kind)):
                return True
    if node.get("op") == "anagram":
        said = _anagram_indicator_letters()
        for p in ps:
            w, g = wordplay.letters(p.get("words")), wordplay.letters(p.get("gives"))
            if "op" not in p and len(str(p.get("words") or "").split()) == 1 and len(g) >= 2 and w != g and any(
                    len(k) >= 3 and ((w.startswith(k) and w[len(k):] == g) or (w.endswith(k) and w[:-len(k)] == g))
                    for k in said):
                return True
    if len(ps) == 1 and "op" not in ps[0] and node.get("op") in _FOLD_PHRASE:
        # "final of competition" for last(..): the leaf's own opening words name the pick
        # (times-28920 22d ARENA); the words still do one job, so no indicator is filed.
        if _FOLD_PHRASE[node["op"]].match(str(ps[0].get("words") or "")) \
                or _FOLD_POSS.get(node["op"], _NOPOSS).match(str(ps[0].get("words") or "").strip()):
            return True
        lw = wordplay.letters(re.sub(r"['’]s\b", "", str(ps[0].get("words") or ""), flags=re.I))
        if alone and node["op"] in ("first", "last") and len(str(ps[0].get("words") or "").split()) == 1 and lw and _abbreviation_pair(
                lw, lw[0] if node["op"] == "first" else lw[-1]):
            return True
    if len(ps) != 1 or "op" in ps[0] or len(str(ps[0].get("words") or "").split()) != 1:
        return False
    w = wordplay.letters(ps[0]["words"]).lower()
    return w not in _NOT_COMPOUND and any(
        len(w) - len(k) >= 3 and (w.startswith(k) or w.endswith(k)) for k in _FOLD_AFFIX.get(node.get("op"), ()))


def _list_run(kids, ns):
    """Whether the same-op nodes `ns` among `kids` are adjacent, plain-leaf, and exactly one
    carries an indicator, standing first or last in the run ("starts off game, at, rock, bottom")."""
    idx = [i for i, p in enumerate(kids) if any(p is x for x in ns)]
    if idx != list(range(idx[0], idx[0] + len(idx))):
        return False
    ind = [x for x in ns if x.get("indicators")]
    if not (len(ind) == 1 and (ind[0] is ns[0] or ind[0] is ns[-1]) and all(
            x.get("parts") and isinstance(x["parts"][0], dict) and "op" not in x["parts"][0] for x in ns)):
        return False
    # with the clue positions given, the indicator must stand right beside the run (VIOLA: an
    # indicator elsewhere in the clue is a lie about the other words)
    leaves = [x["parts"][0] for x in ns]
    marks = ind[0]["indicators"]
    if all("at" in q and q.get("words") for q in leaves) and all("at" in i for i in marks):
        lo, hi = min(q["at"] for q in leaves), max(q["at"] + len(q["words"]) for q in leaves)
        return any(lo - (i["at"] + len(i["text"])) in range(0, 4) or i["at"] - hi in range(0, 4) for i in marks)
    return True


@functools.lru_cache(maxsize=None)
def _compound_indicator_keys(kind):
    """Lexicon indicators of type `kind` that are one word of 4-8 letters with 100+ uses: the ones that
    can open or close a compound clue word (round, some) without being a stray syllable."""
    return tuple(k for k, n in (_indicator_lexicon().get(kind) or {}).items() if 4 <= len(k) <= 8 and n >= 100)


@functools.lru_cache(maxsize=1)
def _anagram_indicator_letters():
    """The anagram indicator lexicon's keys as bare letters (MIXED), for a leaf that gives one."""
    return frozenset(wordplay.letters(k) for k in _indicator_lexicon().get("anagram") or {})


def shared_indicators(tree, clue=None):
    """Indicator words claimed twice: the same text (at the same `at`, or with none) filed on
    two ops, or an indicator whose words are also a leaf's clue words. toughie-3361 12a
    PRAWNCRACKERS: "possibly" is the anagram indicator and again the leaf that gives
    CRACKERS. Leaves in a cryptic definition are the clue, not claims. A word the clue
    itself says twice ("Ruin, ruin") may be both, so it is let go when `clue` is given."""
    flat = wordplay.letters(clue) if clue else ""
    seen, texts, leaves, cut_words, multiword = {}, [], [], set(), []
    said_ind = _anagram_indicator_letters()
    for node in _walk(tree):
        if node.get("op") == "cryptic":
            continue
        for i in node.get("indicators") or []:
            key = (wordplay.letters(i.get("text")), i.get("at"))
            w = key[0].lower()
            if len(str(i.get("text") or "").split()) == 1 and w not in _NOT_COMPOUND and any(
                    len(w) - len(k) >= 3 and (w.startswith(k) or w.endswith(k)) for k in _FOLD_AFFIX.get(node.get("op"), ())):
                cut_words.add(key[0])  # "fightback" = fight + back: the compound is the leaf (FIGHT -> WAR) and its indicator (round 13 RAW)
            if key[0] and flat.count(key[0]) < 2:
                seen[key] = seen.get(key, 0) + 1
                texts.append((key[0], i.get("at"), str(i.get("text") or "").lower().split()))
        if "op" not in node and node.get("words") and "at" not in node:
            leaves.append(wordplay.letters(node["words"]))
            if len(str(node["words"]).split()) >= 2 and len(wordplay.letters(node["words"])) >= 8:
                multiword.append(str(node["words"]).lower().split())
            if node.get("gives") and wordplay.letters(node["gives"]) in said_ind \
                    and re.search(r"\breverse\b|\banswer's\b", str(node.get("note") or ""), re.I):
                cut_words.add(wordplay.letters(node["words"]))  # reverse clue: the words give the indicator word (MIXED)
        if str(node.get("op")).startswith("pal"):
            # a palindrome is its own clue ("rising and falling" REFER, round 10): the indicator
            # words are the leaf's, the one phrase read both ways
            cut_words |= {wordplay.letters(p.get("words")) for p in node.get("parts") or []
                          if isinstance(p, dict) and "op" not in p}
        if node.get("op") in ("deletion", "container", "substitution"):
            # "topless" over [topless]S names what goes; "onboard" over [onboard]SS is the
            # holder and says it holds: the one word is truthfully both
            # only for a short reading of the indicator word itself (SS, S): a synonym the indicator
            # word also gives ([sleeping]BED under ins<sleeping>) is one word doing two jobs
            cut_words |= {wordplay.letters(p.get("words")) for p in (node.get("parts") or [])[1:]
                          if isinstance(p, dict) and "op" not in p}
            if node["op"] == "container":
                cut_words |= {wordplay.letters(p.get("words")) for p in (node.get("parts") or [])[:1]
                              if isinstance(p, dict) and "op" not in p and len(wordplay.letters(p.get("gives"))) <= 2}
                # Withholding = WITH + holding (round 14): the holder is the word's own opening or ending
                cut_words |= {wordplay.letters(p.get("words")) for p in (node.get("parts") or [])[:1]
                              if isinstance(p, dict) and "op" not in p and len(wordplay.letters(p.get("gives"))) >= 3
                              and len(str(p.get("words")).split()) == 1
                              and wordplay.letters(p.get("words")) != wordplay.letters(p.get("gives"))
                              and wordplay.letters(p.get("words")).startswith(wordplay.letters(p.get("gives")))}
        if node.get("op") in ("anagram", "homophone"):
            # Round 17 (4 of 6 sampled sharedIndicator flags judged fine): outpost = out + POST, Twinkletoes =
            # twinkle + TOES (the leaf's word opens or ends with the anagram indicator), and "See" read as the
            # letter C (the sound of a letter's name is its own word, no other indicator to give)
            for p in node.get("parts") or []:
                if not isinstance(p, dict) or "op" in p:
                    continue
                w, g = wordplay.letters(p.get("words")), wordplay.letters(p.get("gives"))
                if node["op"] == "homophone" and len(wordplay.letters(node.get("spelt"))) == 1 \
                        and len(str(p.get("words") or "").split()) == 1:
                    cut_words.add(w)
                elif node["op"] == "anagram" and g and w != g and len(str(p.get("words") or "").split()) == 1 and (
                        (w.endswith(g) and w[:-len(g)] in said_ind) or (w.startswith(g) and w[len(g):] in said_ind)):
                    cut_words.add(w)
        if node.get("op") == "reversal":
            # Return in transport = BUS round GO reversed (round 14, 3 of 6 sampled sharedIndicator flags judged fine):
            # the leaf's words are the reversal's, "go back" read as one phrase; the tree cannot say it shorter
            cut_words |= {wordplay.letters(p.get("words")) for p in node.get("parts") or []
                          if isinstance(p, dict) and "op" not in p}
    n = sum(c - 1 for c in seen.values() if c > 1)
    n += sum(1 for t, at, _ in texts if at is None and t in leaves and t not in cut_words)
    # a leaf's whole multi-word clue words standing inside a longer indicator (azed-1946 17a TURNTURTLE:
    # leaf "This instruction" and the reversal indicator "This instruction makes")
    n += sum(1 for t, at, raw in texts if at is None and t not in cut_words and any(
        re.search(r"(?:^|\s)%s(?:\s|$)" % re.escape(" ".join(l)), " ".join(raw)) and " ".join(l) != " ".join(raw)
        and wordplay.letters(" ".join(l)) not in cut_words for l in multiword))
    return n


def half_leaves(tree):
    """Leaves of one clue word that give exactly its first or last half, with no selection
    op above and no abbreviation saying so: quiptic-1389 22d LION, "only half of" filed on
    live -> LI and again, unmarked, on ones -> ON (one indicator over two words)."""
    pairs, usage = _attested()
    if not usage or not any(re.search(r"\bhalf\b|\bhalves\b|50\s*%|\bhalf-", str(i.get("text") or ""), re.I)
                            for n in _walk(tree) for i in n.get("indicators") or []):
        return 0  # no half indicator in the tree: a short leaf is an abbreviation (STR strait, DOL dollar)
    n = 0
    for leaf, anc in _word_leaves(tree):
        words, gives = wordplay.letters(leaf["words"]), wordplay.letters(leaf["gives"])
        if len(leaf["words"].split()) != 1 or len(words) < 4 or len(gives) * 2 != len(words) \
                or not (words.startswith(gives) or words.endswith(gives)) or leaf.get("select"):
            continue
        if any(a.get("op") in wordplay.SELECT or a.get("op") == "hidden" for a in anc) \
                or _known_pair(leaf["words"], gives):
            continue
        n += 1
    return n


def deletion_scattered(tree):
    """Deletions over a charade whose removed letters (3+) are in no reading a run of the
    charade's letters: they are picked out of several pieces at once (everyman-3903 6d
    TOLKIEN, "Not half" taking MANLITS across Tolman, Kili and Ents). One "half" acts on
    one piece; the evaluator removes the letters from anywhere, so it passes."""
    n = 0
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") != "deletion" or node.get("unchecked") or len(parts) != 2 \
                or not all(isinstance(p, dict) for p in parts) or parts[0].get("op") != "charade" \
                or len(parts[0].get("parts") or []) < 2:
            continue
        text = " ".join(str(i.get("text") or "") for i in node.get("indicators") or [])
        if parts[1].get("words") and "op" not in parts[1] and len(wordplay.letters(parts[1]["words"])) >= 4 \
                and wordplay.letters(parts[1].get("gives")) == wordplay.letters(parts[1]["words"]) \
                and not parts[1].get("unchecked"):
            # a whole clue word taken out of a charade it is not a run of (azed-2427 7d STANCES:
            # MOST+ANCESTORS less MOTORS "around" is MO(STANCES)TORS, a container, round 12)
            try:
                wholes, cuts = wordplay.values(parts[0]), wordplay.values(parts[1])
            except Exception:
                continue
            n += bool(wholes and cuts and not any(r in f for f in wholes for r in cuts))
            continue
        if parts[1].get("words") or not re.search(r"\bhalf\b|\bhalves\b|50\s*%|\bhalf-", text, re.I):
            continue  # only the "half" form is measured: "lacking leaders" over each word is told true
        try:
            wholes, cuts = wordplay.values(parts[0]), wordplay.values(parts[1])
        except Exception:
            continue
        if wholes and cuts and all(len(r) >= 3 for r in cuts) and not any(r in f for f in wholes for r in cuts):
            n += 1
    return n


def reverse_phrase(tree):
    """A reverse (self-referential) reading over 3+ clue words: the wordplay is the answer
    read as an instruction on the whole phrase, which a solver cannot check or follow
    (sundaytimes-5086 12a ROUGHHEWN, quiptic-1146 20d LINEDUP). A phrase that says "this" points
    at the answer and is the Azed form ("This could make pals" SLAPUP), so it is left."""
    return sum(1 for n in _walk(tree) if n.get("op") == "reverse" and not n.get("unchecked")
               and any(len(str(p.get("words") or "").split()) >= 3 and not re.search(r"\bthis\b", str(p["words"]), re.I)
                       and not _reading_reuses_words(n, p)
                       for p in n.get("parts") or [] if isinstance(p, dict)))


def _reading_reuses_words(node, leaf):
    """Whether a word of the reverse reading (3+ letters) is an anagram of the last 1-4 words of the
    leaf (round 15, 3 of 4 reversePhrase flags judged fine: NATE for "neat", STEP for "pets", POTATOES
    for "to a poet's"): the answer then tells how the clue words were made, which a solver can check."""
    words = re.findall(r"[A-Za-z']+", str(leaf.get("words") or ""))
    runs = {"".join(sorted(wordplay.letters("".join(words[len(words) - k:])))) for k in (1, 2, 3, 4)
            if k <= len(words)}  # the end of the phrase, as in "What makes pets" (ROUGH + HEWN fails on "When")
    return any(len(w) >= 3 and "".join(sorted(w.upper())) in runs
               for w in re.findall(r"[A-Za-z]+", str(node.get("reading") or "")))