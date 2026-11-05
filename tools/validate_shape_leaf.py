"""Wordplay-tree shape detectors of validate_annotations.py, part 5: what a leaf does wrong (cuts, repeats, halves, stand-ins).

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import collections
import copy
import re
import wordplay

from validate_shape_base import (
    _walk, _OP_LEXICON, indicator_role_key, _role_counts, _known_pair, _owner_type, CUT_WORDS,
)
from validate_shape_ops import _stand_in_piece, anagram_edge_pieces
from validate_shape_folds import _lexicon_letters
from validate_shape_inside import _SHARED_OK, _pair_adjacent
from validate_shape_order import moved_letters, _ind_adjacent, _own_word, _subtree_spans, pool_gaps

ANA_SELECT_EDGE = "anagram holds a first/last-letter pick at the edge of its fodder that the answer shows outside the scramble"
NON_WORD_OPERAND = "deletion, substitution or homophone acts on a leaf that is no word"
DEL_WIDE = "deletion lists several pieces before its indicator, so it cuts one piece, not the whole group"
IND_LEAF_OVERLAP = "indicator phrase takes a word that a leaf also gives"
ANA_DOUBLE_IND = "anagram carries two separate indicators"
DEL_STRADDLE = "deletion over a charade removes letters from across two of its pieces"


def _stand_in_or_select(p):
    """An anagram fodder piece that is a stand-in or a first/last-letter pick."""
    return (p.get("op") in wordplay.SELECT and not p.get("unchecked")) or _stand_in_piece(p)


def ana_select_edge(tree, answer=None):
    """Anagrams whose edge fodder is a letter pick (first(x), last(x)) that stays outside the scramble in the
    answer (r23 FN: GLEAM = G + ana(MALE), BRUSCHETTA = ana(SCHUBERT + T) + A). Counts only what the
    stand-in check (anaCharade) does not already count."""
    base = max(0, anagram_edge_pieces(tree, answer, _stand_in_or_select) - anagram_edge_pieces(tree, answer))
    return base or _select_edge_swapped(tree, answer)


def _select_edge_swapped(tree, answer):
    """1 when an anagram's one letter pick, first or last in the fodder, stands at the OTHER end of the
    answer once taken out (r23 FN GLEAM: ana<breaks>(Male, first<head>(gymnast's)) is G + ana(MALE))."""
    if not answer or not isinstance(tree, dict):
        return 0
    try:
        wordplay.evaluate(copy.deepcopy(tree), answer)
    except Exception:
        return 0
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") != "anagram" or node.get("unchecked") or len(parts) < 2 \
                or not all(isinstance(p, dict) for p in parts):
            continue
        for idx in (0, len(parts) - 1):
            if parts[idx].get("op") not in wordplay.SELECT or parts[idx].get("unchecked") \
                    or any(q.get("op") in wordplay.SELECT for k, q in enumerate(parts) if k != idx):
                continue
            for front in (True, False):
                t = copy.deepcopy(tree)
                for cur in _walk(t):
                    if cur.get("op") == "anagram" and cur.get("parts") == node.get("parts") \
                            and cur.get("indicators") == node.get("indicators"):
                        piece = cur["parts"].pop(idx)
                        mid = {k: v for k, v in cur.items()}
                        cur.clear()
                        cur.update({"op": "charade", "parts": [piece, mid] if front else [mid, piece]})
                        break
                try:
                    wordplay.evaluate(t, answer)
                    return 1
                except Exception:
                    pass
    return 0


def del_straddle(tree):
    """Deletions over a charade of lettered leaves whose removed letters run across a piece boundary at the
    charade's start or end (r23 FN PAPA: del<briefly>(PAPARAZZO + a, RAZZOA); ORKNEY del<Ignore>(W + WORK, WW)):
    the word cuts one piece, so the cut belongs inside the charade."""
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "deletion" or len(ps) != 2 or ps[0].get("op") != "charade" or "op" in ps[1] \
                or ps[1].get("words") or not ps[1].get("gives"):
            continue
        pcs = [p for p in ps[0].get("parts") or [] if isinstance(p, dict)]
        if len(pcs) < 2 or any("op" in p for p in pcs):
            continue
        gs = [wordplay.letters(p.get("gives") if p.get("gives") else p.get("words")) for p in pcs]
        cut, full = wordplay.letters(ps[1]["gives"]), "".join(gs)
        if cut and ((full.endswith(cut) and len(cut) > len(gs[-1]) and full != cut)
                    or (full.startswith(cut) and len(cut) > len(gs[0]) and full != cut)):
            n += 1
    return n


def non_word_operands(tree):
    """Deletions, substitutions and homophones whose operand leaf gives letters that are no word and no
    attested pair (r23 FN: sub(OXCOW), del(DICKEYE), sound(BOYCOT): two synonyms run together in one leaf,
    so the cut or the sound acts on one of them). Needs the lexicon."""
    lex = _lexicon_letters()
    if not lex:
        return 0
    n = 0
    for node in _walk(tree):
        if node.get("op") not in ("deletion", "substitution", "homophone"):
            continue
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        for p in ps[:1] if node["op"] != "homophone" else ps:
            g = wordplay.letters(p.get("gives")).lower()
            if "op" in p or not p.get("words") or p.get("unchecked") or len(g) < 5 or g in lex \
                    or p.get("select") or p.get("soundsLike") or re.search(r"\d", str(p["words"])):
                continue
            if not _known_pair(p["words"], wordplay.letters(p["gives"])):
                n += 1
    return n


def del_wide(tree, clue):
    """Deletions of 3+ parts whose indicator stands in the clue after two or more of their parts: the word
    cuts the one piece next to it, and the earlier pieces are the parent's (r23 FN MOUSETRAP
    ana<Spread>(del<lacking>(out, Parmesan, an)): OUT is no part of the cut)."""
    if not clue:
        return 0
    low = clue.lower()
    try:
        tree = wordplay.locate(copy.deepcopy(tree), clue)
    except Exception:
        pass
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "deletion" or len(ps) < 3:
            continue
        inds = [i for i in node.get("indicators") or [] if isinstance(i, dict) and str(i.get("text") or "")]
        if len(inds) != 1:
            continue
        t = str(inds[0]["text"])
        at = inds[0]["at"] if isinstance(inds[0].get("at"), int) else low.find(t.lower())
        spans = [(min(a for a, _ in s), max(b for _, b in s)) for s in (_subtree_spans(p, clue, low) for p in ps) if s]
        if at >= 0 and len(spans) == len(ps) and sum(b <= at for _, b in spans) >= 2:
            n += 1
    return n


def ind_leaf_overlap(tree, clue=None):
    """A multi-word indicator one of whose words is also a whole leaf (r23 FN STOIC ana<is broken>(cot, is)):
    the clue word serves as fodder and as indicator. Counted by occurrence when the clue is known."""
    nodes = list(_walk(tree))
    leafwords = collections.Counter(w for n in nodes if "op" not in n and n.get("words")
                                    for w in [wordplay.letters(n["words"])] if len(w) >= 2 and " " not in str(n["words"]).strip())
    said = collections.Counter(wordplay.letters(x) for x in (clue or "").split())
    n = 0
    for node in nodes:
        for i in node.get("indicators") or []:
            ws = [wordplay.letters(x) for x in str(i.get("text") or "").split()]
            if len(ws) != 2:
                continue  # longer phrases ("requiring electronic input") leave a gap the leaf may fill: 6 of 10 fine hits
            for w in set(ws):
                if w in leafwords and (not clue or said[w] < 2) and w not in ("a", "an", "the", "of", "to", "in", "it"):
                    n += 1
    return n


SWAPPED_PAIR = "a parent op and its child op carry each other's indicator words"
LINK_IN_LEAF = "leaf opens or closes with a link word and gives what the other words alone give"
_LEAF_LINKS = frozenset("in of to for with and at on by from into".split())
ANA_STAND_IN = "anagram scrambles an abbreviation or synonym beside the clue's own words"


def _role_share(text, op):
    """(share of the corpus's uses of indicator `text` filed under `op`'s type, total uses)."""
    counts = _role_counts(indicator_role_key(text))
    total = sum(counts.values())
    return (counts.get(_OP_LEXICON.get(op), 0) / total if total else 0.0), total


def swapped_pair(tree):
    """A parent op and a direct child op of another type whose indicators are swapped: the parent's word
    is almost never filed under its type but is the child's type's word at least 15% of the time, and the
    child's word is the parent's type's (r23 FN DATIVE ins<twists>(DATE, rev<in>(VI)))."""
    n = 0
    for p in _walk(tree):
        if p.get("op") not in _OP_LEXICON or p.get("unchecked"):
            continue
        for c in p.get("parts") or []:
            if not isinstance(c, dict) or c.get("op") not in _OP_LEXICON or c.get("op") == p["op"] or c.get("unchecked"):
                continue
            pi = [i.get("text") for i in p.get("indicators") or [] if isinstance(i, dict) and i.get("text")]
            ci = [i.get("text") for i in c.get("indicators") or [] if isinstance(i, dict) and i.get("text")]
            if not pi or not ci:
                continue
            ok = all(_role_share(t, p["op"])[0] < 0.05 and _role_share(t, p["op"])[1] >= 10
                     and _role_share(t, c["op"])[0] >= 0.15 for t in pi) \
                and all(_role_share(t, c["op"])[0] < 0.05 and _role_share(t, c["op"])[1] >= 20
                        and _role_share(t, p["op"])[0] >= 0.5 for t in ci)
            n += ok
    return n


def link_in_leaf(tree):
    """Leaves whose first or last clue word is a link word (in, of, to, with ...) when the remaining words
    alone are a known pair for the same letters and the whole phrase is not (r23 FN SWAMI
    [in Southwest]SW): the link word is the clue's join, not part of the leaf."""
    n = 0
    for node in _walk(tree):
        ws = str(node.get("words") or "").split()
        if "op" in node or len(ws) < 2 or not node.get("gives") or node.get("select") or node.get("soundsLike"):
            continue
        g = wordplay.letters(node["gives"])
        if _known_pair(node["words"], g):
            continue
        for lead, rest, link in ((True, ws[1:], ws[0]), (False, ws[:-1], ws[-1])):
            # a leading "to" is the infinitive of a verb leaf ("to shred" RIP, "to throw" SHY): 11 of 12 such hits were fine
            if wordplay.letters(link).lower() in _LEAF_LINKS and not (lead and link.lower() == "to") \
                    and _known_pair(" ".join(rest), g):
                n += 1
                break
    return n


def _initial_abbreviation(p):
    """A leaf giving one or two letters that start its words (R for right, N for new, CC for twice caught):
    the standard abbreviation mid-answer is genuine fodder (r26: 5 of 5 such anaStandIn hits fine, 0 of 4 others)."""
    g = wordplay.letters(p.get("gives"))
    initials = {x[0] for x in re.findall(r"[a-z]+", (p.get("words") or "").lower())}
    # every letter must be an initial: CC for twice caught, but not CH for church (a prefix of one word)
    return bool(g) and len(g) <= 2 and all(ch.lower() in initials for ch in g)


def ana_stand_in(tree):
    """Anagrams whose fodder mixes the clue's own words with a stand-in (abbreviation or synonym) leaf
    (r23 FN POLICYMAKERS ana<broadcast>(K, ER, Olympics)): the stand-in is spelled into the answer, not
    scrambled with the rest."""
    n = 0
    for outer in _walk(tree):
        if outer.get("op") != "container":
            continue  # only the anagram held by a container: judged, 11 of 11 such hits wrong; elsewhere 19 of 29 were fine (a mid-answer letter is fodder)
        for node in (p for p in outer.get("parts") or [] if isinstance(p, dict)):
            parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
            if node.get("op") != "anagram" or node.get("unchecked") or len(parts) < 2:
                continue
            st = [_stand_in_piece(p) and not p.get("select") and not _initial_abbreviation(p) for p in parts]
            n += any(st) and not all(st) and any("op" not in p and not s for p, s in zip(parts, st))
    return n


SELECT_WORD_IN_LEAF = "selection op whose leaf opens with the op's own indicator words"
SELECT_PHRASE_IN_LEAF = "leaf opens with a letter-selection phrase and gives fewer letters than its other words"
HALVED_AS_DELETION ="halving ('half of', '50 per cent', 'bottom half') written as a plain deletion"
SPLIT_SHARED_INDICATOR = "one indicator over two neighbouring same-kind ops, only one of them carrying it"
_NOT_A_HALVING = re.compile(r"hearted|more than half|almost half", re.I)
_HALVING =re.compile(r"\bhalf\b|\bsemi\b|\b\d{1,2}\s*(?:per\s*cent|%|percent)", re.I)  # any percentage: r36 FN "60% of", "about 57%"


def select_word_in_leaf(tree):
    """Selection ops (first, last, outer, middle ...) whose direct leaf opens with the op's own indicator
    words and holds more ("bit of breakfast" under first<bit of>, "end for beggar" under last<end for>,
    r26 FN: 3 misses): the leaf holds only the words that give its letters."""
    n = 0
    for node in _walk(tree):
        if node.get("op") not in wordplay.SELECT or node.get("unchecked"):
            continue
        inds = [re.findall(r"[a-z']+", str(i.get("text") or "").lower()) for i in node.get("indicators") or [] if isinstance(i, dict)]
        for p in (q for q in node.get("parts") or [] if isinstance(q, dict) and "op" not in q):
            words = re.findall(r"[a-z']+", str(p.get("words") or "").lower())
            n += any(iw and len(words) > len(iw) and words[:len(iw)] == iw for iw in inds)
    return n


def select_phrase_in_leaf(tree):
    """Leaves of 2+ words that open with a selection indicator phrase the corpus files under letter
    selection ("borders of scarlet" giving ST, "Heading off trouble" giving OTHER; r26 FN: 3 misses) and give
    fewer letters than the words after it: the selection is an op. cut_in_leaf takes the cut words."""
    n = 0
    for node in _walk(tree):
        if "op" in node or node.get("unchecked") or not node.get("gives") or not node.get("words"):
            continue
        words = re.findall(r"[a-z']+", str(node["words"]).lower())
        gives = len(re.sub(r"[^A-Z]", "", str(node["gives"])))
        for k in (1, 2, 3):
            rest = sum(len(w) for w in words[k:])
            if len(words) > k and gives < rest and _owner_type(" ".join(words[:k])) == "letter_selection" \
                    and words[0] not in CUT_WORDS:
                n += 1
                break
    return n


SELECTOR_AS_CUT = "deletion removes a leaf made of a first/last-letter word (leader, City's first), not a first/last pick"


def selector_as_cut(tree):
    """Deletions whose removed leaf is a selection word alone or closing a longer phrase ("leader" giving P,
    "City's first" giving C; r30 FN: 2 misses): the removed letter is a first/last pick with its own
    indicator, del(PACE, first<leader>(...)) -- the leaf holds only the words that give its letters."""
    n = 0
    for node in _walk(tree):
        if node.get("op") != "deletion" or node.get("unchecked"):
            continue
        for p in (q for q in (node.get("parts") or [])[1:] if isinstance(q, dict) and "op" not in q and q.get("gives")):
            words = re.findall(r"[a-z']+", str(p.get("words") or "").lower())
            gives = len(re.sub(r"[^A-Z]", "", str(p["gives"])))
            if {"second", "initials"} & set(words):
                continue  # r31 judged: "second" is the abbreviation S (6 of 9 fine hits)
            if words and gives <= 2 and (
                    (len(words) == 1 and _owner_type(words[0]) == "letter_selection") or
                    (len(words) > 1 and _owner_type(words[-1]) == "letter_selection"
                     and gives < sum(len(w) for w in words[:-1]))):
                n += 1
    return n


def halved_as_deletion(tree):
    """Deletions whose indicator says half ("half of", "50 per cent", "bottom half removed",
    "half-forgotten"; r26 FN: 5 misses): the word keeps half its letters, a halving selection, not a
    deletion of the other half. Not "half-hearted" (one of a doubled heart letter dropped: SOBBER to SOBER,
    7 of 9 fine r28 hits) nor "more than half" / "almost half" (not an exact half)."""
    return sum(1 for node in _walk(tree) if node.get("op") == "deletion" and not node.get("unchecked")
               and any(_HALVING.search(t) and not _NOT_A_HALVING.search(t)
                       for t in (str(i.get("text") or "") for i in node.get("indicators") or [] if isinstance(i, dict))))


TRIM_AS_SELECTION = ("first/last/middle pick of 2+ letters from a synonym, not the clue's own words, "
                     "written as a selection (a trim of a word the clue does not print is a deletion)")


def trims_as_selection(tree, answer):
    """Selections (first, last, middle) over one leaf whose letters are a synonym rather than the clue's
    own words, keeping 2+ letters but not all (cryptic-30087 17a: middle<without limits>([jumps]BOUNCES)
    for OUNCE). The family rung says a selection's letters sit in the clue, and these do not: the word is
    trimmed, del<without limits>([jumps]BOUNCES, B, S), the way 35k other trims of a synonym are filed.
    Not a halving (halved_as_deletion keeps those as selections), a single-letter pick (the first letter
    of a synonym), nor a pick a deletion takes out (its letters are the cut, not a word kept)."""
    if not tree or not answer:
        return 0
    try:
        got = wordplay.evaluate(tree, answer)
    except wordplay.WordplayError:
        return 0
    n = 0

    def walk(node, cut):
        nonlocal n
        if not isinstance(node, dict):
            return
        parts = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if not cut and node.get("op") in ("first", "last", "middle") and not node.get("unchecked") \
                and len(parts) == 1 and "op" not in parts[0] and parts[0].get("gives") \
                and not parts[0].get("select") and not parts[0].get("unchecked"):
            leaf, said = parts[0], [str(i.get("text") or "") for i in node.get("indicators") or [] if isinstance(i, dict)]
            whole, words = wordplay.letters(leaf["gives"]), str(leaf.get("words") or "")
            pick = got.get(id(node)) or ""
            n += (whole not in (wordplay.letters(words), wordplay.letters(re.sub(r"['’]s\b", "", words)))
                  and 2 <= len(pick) < len(whole)
                  and not any(_HALVING.search(t) and not _NOT_A_HALVING.search(t) for t in said))
        for k, p in enumerate(parts):
            walk(p, cut or (k > 0 and node.get("op") in ("deletion", "substitution", "move")))
    walk(tree, False)
    return n


def split_shared_indicators(tree):
    """Two neighbouring same-kind ops (deletion, homophone, a selection) under one parent where only one
    carries an indicator (r26 FN: "finishes off" over CHAD and BLISS, "leaders must leave" over Told that):
    one indicator, one multi-part op.

    Not counted: two deletions of two parts each (whole word, the letters cut off it) under a charade
    with an indicator of its own (independent-9959 HIPPO "Statesmanship and politics together
    encapsulate", independent-11513 OBELI, indysunday-1338 CYNIC, timesclub-20266 THYMI): the validator
    takes no multi-cut deletion, so there is no one-op form to write (r_split_shared_indicator leaves
    deletions for the model for that reason) and the charade's indicator joins the two cuts."""
    n = 0
    for parent in _walk(tree):
        groups = {}
        for p in (q for q in parent.get("parts") or [] if isinstance(q, dict)):
            if p.get("op") in _SHARED_OK and not p.get("unchecked"):
                groups.setdefault(p["op"], []).append(p)
        for op, ns in groups.items():
            if (op == "deletion" and len(ns) == 2 and parent.get("op") == "charade" and parent.get("indicators")
                    and all(len(x.get("parts") or []) == 2 for x in ns)):
                continue
            n += len(ns) == 2 and sum(bool(x.get("indicators")) for x in ns) == 1 and _pair_adjacent(ns)
            n += len(ns) >= 3 and sum(bool(x.get("indicators")) for x in ns) == 1  # r40 FN NUMEROUNO: one "never-endingly" over four deletions
    return n


TRUNC_IN_LEAF = "leaf holds a truncation word (mostly, almost, cut short) and gives a word one letter short"
CUT_NOTE_LEAF = "leaf gives a non-word that its note says is a real word with letters cut, and no deletion op shows the cut"
OWN_IND_IN_LEAF = "op's own indicator words also sit inside its leaf (at the end, or the start of a non-selection)"
#: "briefly" and "concise" are left out: they are the abbreviation convention (Science briefly = SCI; 6 of 6 judged fine).
_TRUNC_WORDS = frozenset("mostly almost nearly largely curtailed endlessly practically virtually partly "
                         "shortened contracted abbreviated truncated clipped skimmed trimmed docked beheaded "
                         "decapitated topped tailed".split())
#: "briefly" counts only when the leaf's own note says a word was shortened ("RAVE, shortened"), r30 FN.
_BRIEFLY_CUT = re.compile(r"\b(?:shortened|clipped|without|loses|lost|drop\w*|truncated|last letter)\b", re.I)
#: r32 FN: a leaf ULE whose note says "YULE with its first letter removed" is a word, so only the note shows the cut.
_LETTER_REMOVED = re.compile(r"\b(?:letter|first|last|final|end)\b[^.;]{0,20}\bremoved\b", re.I)
_TRUNC_PHRASES = ("cut short", "not quite", "not entirely", "not completely", "not fully", "cut off")
_CUT_NOTE = re.compile(r"\b(?:without|minus|missing|losing|loses|lacking|dropp\w*|drops|clipped|truncated|shortened|"
                       r"lopped|omitting|stops short|loses|cut)\b[^.;]{0,40}\b(?:letter|last|first|final|end|head|"
                       r"initial|tail|front|back|ending|start|beginning)\b", re.I)


_CUT_LETTER = re.compile(r"\b(?:without|minus|losing|lacking|dropping|missing|less|killed|lost|loses)\s+"
                         r"(?:its\s+|the\s+|a\s+)?(?:[a-z]+\s+)?[A-Z]{1,2}\b"
                         r"|\b[A-Z]{1,2}\b[^.;]{0,25}\b(?:killed|removed|dropped|lost|taken off|deleted|lifted out)\b"
                         r"|\bwith\s+(?:its\s+)?[A-Z]{1,2}\b(?:\s*\([^)]{0,12}\))?\s+(?:missing|lifted out|removed)\b")


def _plain_leaves(tree):
    """Checked lettered leaves of two or more clue words, no op on them."""
    for node in _walk(tree):
        if "op" in node or node.get("unchecked") or not node.get("gives") or not node.get("words"):
            continue
        yield node, re.findall(r"[a-z']+", str(node["words"]).lower())


def trunc_in_leaf(tree):
    """Multi-word leaves holding a truncation word anywhere (not just first: "Nick mostly" giving SATA,
    "island almost" giving SAR, "life cut short" giving NELLI; r28 FN: 5 misses) that give a non-word one
    letter short of a word: the cut is a deletion with its own indicator. Not "briefly"/"concise" (the
    abbreviation convention) and no apostrophe. Needs the lexicon."""
    lex = _lexicon_letters()
    if not lex:
        return 0
    n = 0
    for node, words in _plain_leaves(tree):
        text = " ".join(words)
        briefly = "briefly" in words and _BRIEFLY_CUT.search(str(node.get("note") or ""))
        if len(words) < 2 or not (_TRUNC_WORDS & set(words) or any(p in text for p in _TRUNC_PHRASES) or briefly):
            continue
        g = wordplay.letters(node["gives"]).lower()
        note = str(node.get("note") or "")
        if len(g) >= 3 and (g not in lex or _BRIEFLY_CUT.search(note) or _LETTER_REMOVED.search(note)) and "'" not in note + text \
                and any(g + c in lex or c + g in lex for c in "abcdefghijklmnopqrstuvwxyz"):
            n += 1
    return n


def own_ind_in_leaf(tree):
    """Ops whose direct plain leaf opens or ends with the op's own indicator words and holds more
    ("French way back" under rev<back>, "arthropod's shell" under outer<shell>; r28 FN: 3 misses):
    the leaf holds only the words that give its letters. select_word_in_leaf counts the opening case
    for selection ops; this counts the end of the leaf for every op and the opening for the rest."""
    n = 0
    for node in _walk(tree):
        if "op" not in node or node.get("unchecked") or node["op"] == "anagram":
            continue
        inds = [re.findall(r"[a-z']+", str(i.get("text") or "").lower()) for i in node.get("indicators") or [] if isinstance(i, dict)]
        for p in (q for q in node.get("parts") or [] if isinstance(q, dict) and "op" not in q and q.get("gives")):
            words = re.findall(r"[a-z']+", str(p.get("words") or "").lower())
            n += any(iw and len(words) > len(iw) and (words[-len(iw):] == iw or (
                words[:len(iw)] == iw and node["op"] not in wordplay.SELECT)) for iw in inds)
            n += node["op"] == "deletion" and any(iw and words == iw and len(iw) > 1 for iw in inds)  # r30 FN: leaf "not at first" under the indicator "not at first"
    return n


DOUBLED_APOSTROPHE = "a quoted word has a doubled apostrophe inside it (Guardian''s for Guardian's)"
DOUBLED_APOSTROPHE_RE = re.compile(r"(?<=\w)''(?=\w)")


def doubled_apostrophe(tree):
    """Leaf words and indicator texts with two apostrophes between letters (Guardian''s, it''s): the
    scan's single quote read twice. Nobody writes two for one; the clue text says the same word with one
    (genius-58 4d, a solver's "Double quote" report; 214 stored clues had it)."""
    n = 0
    for node in _walk(tree):
        n += bool(DOUBLED_APOSTROPHE_RE.search(str(node.get("words") or "")))
        n += sum(bool(DOUBLED_APOSTROPHE_RE.search(str(i.get("text") or "")))
                 for i in node.get("indicators") or [] if isinstance(i, dict))
    return n


REPEAT_IN_LEAF = "leaf holds a doubling word (twice, double, again) and gives a doubled string"
REPEAT_FORM = "write rep<twice>([boy]AL) for ALAL: the leaf gives one copy, rep() doubles it, the doubling word is rep's indicator"
HALF_IN_LEAF = "leaf holds half and gives half of another of its words, a halving selection folded into the leaf"
SELECT_IND_ENDS_LEAF = "selection op whose letter-less leaf ends with the op's own indicator words"
BEHEAD_IN_LEAF = "leaf holds a losing-head/tail phrase and gives the letters that are left"
_REPEAT_WORDS = frozenset("twice doubled double repeated repeatedly again thrice redoubled doubling doubles "
                          "repeating duplicated duplicating twofold doubly encored encore".split())
_STUTTER_WORDS = frozenset("stuttering stutter stutters stuttered stammering stammer stammers stammered".split())
_BEHEAD = re.compile(r"\b(?:losing|lost|without|minus|lacking|missing|dropping|loses|shedding|ignoring|dismissing|"
                     r"removing|ditching|discarding|dumping)\s+"
                     r"(?:its\s+|the\s+|his\s+|her\s+|their\s+)?(?:head|tail|top|bottom|leader|front|back|"
                     r"first letter|last letter|initial|first|last|foremost|leading|opening|ending|finish|tip|start|beginning)\b"
                     r"|\b(?:headless|tailless)\b", re.I)


def repeat_in_leaf(tree):
    """Plain leaves holding twice, double or again with another word that give a string made of one block
    twice (r34 FN ALFALF: "Boy called twice" giving ALFALF): the repeat is an op with its own indicator.
    r35 judged 0 of 40 fine."""
    n = 0
    for node, words in _plain_leaves(tree):
        g = wordplay.letters(node["gives"])
        h = len(g) // 2
        n += len(words) >= 2 and bool(_REPEAT_WORDS & set(words)) and len(g) >= 2 and len(g) % 2 == 0 and g[:h] == g[h:]
        # r36 FN: "Stuttering" giving LALA, one stutter word whose letters double
        n += len(words) == 1 and words[0] in _STUTTER_WORDS and len(g) >= 4 and len(g) % 2 == 0 and g[:h] == g[h:]
    # r36 FN TUTU: a leaf "two" giving the same letters as the leaf beside it
    for parent in _walk(tree):
        parts = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        for a, b in zip(parts, parts[1:]):
            if any("op" in x or x.get("unchecked") or not x.get("gives") or not x.get("words") for x in (a, b)):
                continue
            wb = set(re.findall(r"[a-z']+", str(b["words"]).lower()))
            n += (len(wordplay.letters(a["gives"])) >= 2 and wordplay.letters(a["gives"]) == wordplay.letters(b["gives"])
                  and bool((_REPEAT_WORDS | {"two"}) & wb) and len(wb) == 1)
    # r40 FN CHOWCHOW: a leaf "Twice" giving the letters the op beside it already gives
    for parent in _walk(tree):
        parts = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        for a, b in zip(parts, parts[1:]):
            for rep, other in ((a, b), (b, a)):
                if "op" in rep or rep.get("unchecked") or other.get("unchecked") or "op" not in other \
                        or not rep.get("gives") or len(str(rep.get("words") or "").split()) != 1 \
                        or str(rep["words"]).lower().strip(" ,.!?") not in _REPEAT_WORDS | {"two"}:
                    continue
                try:
                    n += len(wordplay.letters(rep["gives"])) >= 2 and wordplay.letters(rep["gives"]) in wordplay.values(other)
                except Exception:
                    pass
    # r42 FN AGARAGAR, CHACHA, PRETTYPRETTY: a leaf of "more than once", "repeated", "doubled up" giving the letters
    # the run of pieces beside it already gives
    for parent in _walk(tree):
        parts = [p for p in parent.get("parts") or [] if isinstance(p, dict)]
        for i, rep in enumerate(parts):
            if "op" in rep or rep.get("unchecked") or not rep.get("gives") or not rep.get("words"):
                continue
            ws = re.findall(r"[a-z']+", str(rep["words"]).lower())
            if not ws or not set(ws) <= _REPEAT_PHRASE or not (set(ws) & _REPEAT_WORDS or ws[-3:] == ["more", "than", "once"]
                                                              or ws == ["once", "more"]):
                continue
            g = wordplay.letters(rep["gives"])
            runs = [parts[j:i] for j in range(max(0, i - 4), i)] + [parts[i + 1:k] for k in range(i + 2, min(len(parts), i + 4) + 1)]
            # a one-word leaf beside one piece with letters of its own is the blocks above
            n += len(g) >= 2 and any(g in _run_values(run) for run in runs
                                     if len(run) >= 2 or len(ws) >= 2 or ("op" not in run[0] and not run[0].get("gives")))
    return n


_REPEAT_PHRASE = _REPEAT_WORDS | frozenset("more than once up over times two the same time".split())


def _run_values(run):
    """The strings a run of sibling pieces can spell side by side ({} when a piece is unchecked or has no value)."""
    out = {""}
    for p in run:
        if p.get("unchecked"):
            return set()
        try:
            vals = {wordplay.letters(p.get("gives") or p.get("words"))} if "op" not in p else set(wordplay.values(p))
        except Exception:
            return set()
        if not vals or len(out) * len(vals) > 200:
            return set()
        out = {a + b for a in out for b in vals}
    return out - {""}


def _half_of_synonym(words, g):
    """A leaf of 3+ words with "half of" in it (not "half of the letters", "almost half of", "better half of", a
    half-dozen, "half-hearted") that gives fewer letters than the words beside half: half of a synonym, which no
    substring check can see. Only a non-word (CHOO, IMB, EUS; r42 judged: half of a score, weekend or duo giving TEN, SAT,
    ANT is a fine definitional half, 26 of 51 fine overall, a non-word 1 of 11). Needs the lexicon."""
    if "half" not in words or len(words) < 3 or len(g) < 2:
        return False
    i = words.index("half")
    return (words[i + 1:i + 2] == ["of"] and words[i + 2:i + 3] != ["the"]
            and words[i - 1:i] not in (["almost"], ["left"], ["better"], ["more"], ["than"], ["a"], ["other"], ["and"],
                                       ["first"], ["second"], ["last"])
            and g not in (_lexicon_letters() or {g})
            and not {"dozen", "time", "term", "way", "than"} & set(words) and not any(w.startswith("heart") for w in words)
            and len(g) < sum(len(w) for w in words if w not in ("half", "of")))


def half_in_leaf(tree):
    """Plain leaves holding half (also half-done) beside a clue word whose first or last half they give
    (r34 FN TAMPA: "half-done taco" giving TA): the halving is a selection op with its own indicator.
    r35 judged 0 of 40 fine. r42 FN CHORIZO "half of train" giving CHOO, DEEPEST "Half of capital city" giving PEST,
    IDIOTIC "notion, half rejected" giving ID: also half of a synonym (_half_of_synonym)."""
    n = 0
    for node, words in _plain_leaves(tree):
        g = wordplay.letters(node["gives"]).lower()
        n += (len(words) >= 2 and "half" in words and bool(g) and any(
            w != "half" and len(w) >= 4 and len(g) in (len(w) // 2, (len(w) + 1) // 2) and (w.startswith(g) or w.endswith(g))
            for w in words)) or _half_of_synonym(words, g)
    return n


def select_ind_ends_leaf(tree):
    """Selection ops whose leaf has no letters of its own and ends with the op's indicator words and holds more
    (r34 FN BUTTERUP: first<on top>("cooked on top")): the leaf holds only the words that give its letters.
    own_ind_in_leaf takes the leaves that give letters. r35 judged 2 of 30 fine."""
    n = 0
    for node in _walk(tree):
        if node.get("op") not in wordplay.SELECT or node.get("unchecked"):
            continue
        inds = [re.findall(r"[a-z']+", str(i.get("text") or "").lower()) for i in node.get("indicators") or [] if isinstance(i, dict)]
        for p in (q for q in node.get("parts") or [] if isinstance(q, dict) and "op" not in q and not q.get("gives")):
            words = re.findall(r"[a-z']+", str(p.get("words") or "").lower())
            n += any(iw and len(words) > len(iw) and words[-len(iw):] == iw for iw in inds)
    return n


SPLIT_WORD_LEAVES = "one word split into two leaves over the same clue words, with an insert between"
MOVE_NOTE_LEAF = "leaf gives a non-word its note says has a letter moved, a move written as a leaf"
FIRST_SIBLING_LEAVES = "a first-letters op picks one word while sibling leaves give the other words' initials"
HIDDEN_IND_ABOVE = "hidden op with no indicator under an op whose indicator opens with a hidden-word marker"
DELETION_NO_CUT = "deletion with one leaf part and no cut piece, the leaf a word one letter short"
INITIALS_IN_LEAF = "leaf holds a first-letters word (primarily, initially) and gives the initials of its other words"
_MOVE_NOTE = re.compile(r"\b(?:moved|shifted|transposed|relocated)\b", re.I)
_INITIAL_NOTE = re.compile(r"\b(?:first|initial|opening|leading|head|top|start)\b", re.I)
_HIDDEN_OPENERS = frozenset("having holding contains containing within in some part parts of showing displaying".split())


def split_word_leaves(tree):
    """A leaf and the first leaf of a sibling container/charade piece holding the very same clue words, whose
    letters in tree order spell one word (r38 FN ELGAR: "Listener" giving EA, then R after the insert; the r39
    sample EID, PIPED, NOSE, BEE): one word is split around an insert, so it is the container's outer piece
    (container(EID, N)), not two leaves. Needs the lexicon."""
    lex = _lexicon_letters()
    if not lex:
        return 0
    n = 0
    for node in _walk(tree):
        if node.get("unchecked"):
            continue
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        for i, leaf in enumerate(ps):
            if "op" in leaf or not leaf.get("words") or not leaf.get("gives") or leaf.get("unchecked"):
                continue
            for j, sub in enumerate(ps):
                if j == i or sub.get("op") not in ("container", "charade"):
                    continue
                inner = sub
                while isinstance(inner, dict) and "op" in inner:   # the outermost piece: down the first parts
                    inner = next(iter(inner.get("parts") or []), None)
                if not isinstance(inner, dict) or not inner.get("gives") or wordplay.letters(inner.get("words")) != wordplay.letters(leaf["words"]):
                    continue
                a, b = wordplay.letters(inner["gives"]).lower(), wordplay.letters(leaf["gives"]).lower()
                joined = a + b if j < i else b + a
                n += len(joined) >= 4 and joined in lex and not (a in lex and b in lex and len(a) > 1 and len(b) > 1)
    return n


def move_note_leaf(tree):
    """Plain lettered leaves whose note says a letter was moved or shifted (r38 FN OLYMPIA: "Greasy" giving OLY,
    "OILY, with its I moved down"): a move is move<indicator>(fodder, MOVED), not a leaf."""
    lex = _lexicon_letters()
    return sum(1 for node, words in _plain_leaves(tree) if lex and _MOVE_NOTE.search(str(node.get("note") or ""))
               and len(wordplay.letters(node["gives"])) >= 3 and wordplay.letters(node["gives"]).lower() not in lex)


PRE_REVERSED_LEAF = "leaf under a reversal gives its word already written backwards"
#: A note that says what the reversal makes ("IN plus A, running upward to give ANI") names the turned letters itself.
_TURN_NOTE = re.compile(r"(?i)\b(gives?|giving|revers\w*|backwards?|back|upwards?|turn\w*|runn\w*|reads?|reading|flip\w*)\b")
#: Ops whose leaves are read for their letters, not their meaning: the letters there may run either way.
_LETTER_OPS = frozenset({"hidden", "anagram", "alternate", "deletion", "homophone", "spoonerism"})


def pre_reversed_leaf(tree):
    """Plain leaves under a reversal that give a non-word of 3+ letters whose reverse is what the words mean
    (independent-12387 SURFEIT: "Use a browser" giving FRUS under rev(TIE + FRUS); FICHE, BEAUTYSLEEP):
    reversing the whole charade still spells the answer, so the evaluator passes it, but the page shows the
    solver a synonym backwards and reverses the wrong piece. The reverse must be an attested reading of the
    words or named in the leaf's note. The leaf gives the word forwards; the reversal sits on the piece it turns.
    Needs the lexicon."""
    lex = _lexicon_letters()
    if not lex:
        return 0
    n = 0

    def visit(node, reversed_above):
        nonlocal n
        if not isinstance(node, dict) or node.get("op") in _LETTER_OPS or node.get("op") in wordplay.SELECT:
            return
        if "op" not in node:
            g = wordplay.letters(node.get("gives") or "")
            if not reversed_above or len(g) < 3 or not node.get("words") or node.get("soundsLike"):
                return
            low, back = g.lower(), g[::-1].lower()
            if low in lex or back not in lex or _known_pair(node["words"], g):
                return
            note = str(node.get("note") or "")
            named = (re.search(r"(?i)\b" + back + r"(?:s|es|d|ed|ing|er|ers)?\b", note)
                     and low not in re.sub(r"[^a-z]", "", note.lower()) and not _TURN_NOTE.search(note))
            n += bool(_known_pair(node["words"], g[::-1]) or named)
            return
        for p in node.get("parts") or []:
            visit(p, reversed_above or node.get("op") == "reversal")

    visit(tree, False)
    return n


def first_sibling_leaves(tree):
    """Charades holding a first-letters op over one word beside two or more plain one-word leaves that give
    their own initials (r38 FN CHEF: first<heads>(cooked) + H + E + F, every "heads" word its own leaf): one
    first-letters indicator over the list is one multi-part op."""
    n = 0
    for node in _walk(tree):
        if node.get("op") != "charade" or node.get("unchecked"):
            continue
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        firsts = [p for p in ps if p.get("op") == "first" and len(p.get("parts") or []) == 1 and not p.get("unchecked")]
        bare = [p for p in ps if "op" not in p and p.get("words") and p.get("gives") and len(str(p["words"]).split()) == 1
                and len(wordplay.letters(p["gives"])) == 1 and len(wordplay.letters(p["words"])) >= 3
                and wordplay.letters(p["words"]).startswith(wordplay.letters(p["gives"]))
                and _INITIAL_NOTE.search(str(p.get("note") or ""))]
        n += bool(firsts) and len(bare) >= 2
    return n


def deletion_no_cut(tree):
    """Deletions with one leaf part, no cut piece, whose leaf gives a non-word (r38 FN ROUBLES-type leaves, r39:
    TER under half-term, ROUBLES for TROUBLES): the cut is folded into the leaf and the deletion names nothing;
    write the real word and its cut, or the selection (middle, half) as its own op. r39 judged the unrestricted
    form 7 of 40 fine, all real-word leaves; non-word leaves only here."""
    lex = _lexicon_letters()
    return sum(1 for node in _walk(tree) if lex and node.get("op") == "deletion" and len(node.get("parts") or []) == 1
               and isinstance(node["parts"][0], dict) and "op" not in node["parts"][0]
               and len(wordplay.letters(node["parts"][0].get("gives"))) >= 3
               and wordplay.letters(node["parts"][0].get("gives")).lower() not in lex
               and any(wordplay.letters(node["parts"][0]["gives"]).lower() + c in lex
                       or c + wordplay.letters(node["parts"][0]["gives"]).lower() in lex for c in "abcdefghijklmnopqrstuvwxyz"))


_POSITION_IND = frozenset("primarily initially originally firstly principally heads leaders fronts starts openers".split())
_INITIALS_SKIP = frozenset("and with of the a an".split())


def initials_in_leaf(tree):
    """Plain leaves of 3+ words holding a first-letters word (primarily, initially, starts) beside the words whose
    first letters they give (r38 FN PIZZAZZ: "zip and zing primarily" giving ZZ): the pick is first<primarily>
    over those words, its own op."""
    n = 0
    for node, words in _plain_leaves(tree):
        if len(words) < 3 or not _POSITION_IND & set(words):
            continue
        rest = [w for w in words if w not in _POSITION_IND and w not in _INITIALS_SKIP]
        n += len(rest) >= 2 and wordplay.letters(node["gives"]).lower() == "".join(w[0] for w in rest)
    return n


def hidden_ind_above(tree):
    """Hidden ops with no indicator of their own under an op whose indicator opens with a hidden-word marker
    (r38 FN CINEMA: rev<having returned>(hidden(Blame Nicola))): the marker is the hidden op's indicator."""
    n = 0
    for node in _walk(tree):
        if node.get("op") in (None, "hidden", "charade") or node.get("unchecked"):
            continue
        for ind in node.get("indicators") or []:
            ws = re.findall(r"[a-z']+", str((ind or {}).get("text") or "").lower())
            n += bool(ws) and ws[0] in _HIDDEN_OPENERS and any(
                p.get("op") == "hidden" and not p.get("indicators") for p in node.get("parts") or [] if isinstance(p, dict))
    return n


NESTED_SAME_OP = "an op nested directly in an op of the same kind, only one of the two carrying an indicator"
MIDDLE_SIBLING_LEAF = "a middle op picks one word while a sibling leaf gives the middle letters of its own word"
DEL_ONE_PIECE = "deletion wraps a charade though the cut lies inside one plain piece, so it cuts that piece"
ANA_IS_MOVE = "anagram of one word whose result is the word with a single letter moved, a move written as an anagram"
#: r41 judged: an anagram indicator that is no word of position or motion (shuffled, changed, new) is a real anagram
#: that happens to sit one move from the word (8 of 40 fine); with a movement word in the indicator, 0 of 25 fine.
_MOVE_IND = re.compile(r"\b(?:mov\w*|up|down|forwards?|backwards?|back|rais\w*|lower\w*|later|earlier|advanc\w*|ris\w*|"
                       r"sink\w*|sent|dropp?\w*|promot\w*|relocat\w*|shift\w*|east|west|north|south|tuck\w*|put|place\w*|"
                       r"position\w*|bring\w*|brought|transpos\w*|swap\w*|exchang\w*|jump\w*|go\w*|step\w*|slip\w*|"
                       r"travel\w*|head\w*|climb\w*|fall\w*|lift\w*|pass\w*|row|late|early)\b", re.I)
_NEST_KINDS = frozenset({"deletion", "container", "reversal", "first", "last", "middle", "outer"})


def nested_same_op(tree):
    """Deletions, containers, reversals or picks directly inside an op of the same kind where one of the two has
    no indicator (r40 FN: del<>(del<lacking>(UNRECOGNISABLE, GLOBE), BLE), container<kept in>(container<>(FILE, D+D), D)):
    one indicator is one op, so the two are one multi-part op."""
    n = 0
    for node in _walk(tree):
        if node.get("op") not in _NEST_KINDS or node.get("unchecked"):
            continue
        for p in node.get("parts") or []:
            if isinstance(p, dict) and p.get("op") == node["op"] and not p.get("unchecked") \
                    and bool(p.get("indicators")) != bool(node.get("indicators")):
                n += 1
    return n


def _centre_slice(g, w):
    """Whether g is the centred stretch of w (one or two letters shorter at each end alike)."""
    d = len(w) - len(g)
    return d >= 2 and any(w[a:a + len(g)] == g for a in {d // 2, (d + 1) // 2} if a >= 1)


def middle_sibling_leaf(tree):
    """A middle op beside a plain one-word leaf giving the middle letters of its own word (r40 FN MESSI:
    middle<the very essence of>(primeval) + passion giving SSI): one middle indicator over both words is one
    multi-part op."""
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("unchecked") or not any(p.get("op") == "middle" and not p.get("unchecked") for p in ps):
            continue
        n += any("op" not in p and p.get("words") and p.get("gives") and len(str(p["words"]).split()) == 1
                 and len(wordplay.letters(p["gives"])) >= 2 and _centre_slice(wordplay.letters(p["gives"]).lower(),
                                                                              wordplay.letters(p["words"]).lower())
                 for p in ps)
    return n


def del_one_piece(tree):
    """Deletions of a bare cut piece from a charade of 2+ plain leaves where the cut letters lie inside exactly
    one piece (r40 FN MELODRAMA del<no end>(MELODY + RAM, Y), AGAIN del<not entirely>(A + GANG, G); Paul ruling 1):
    the deletion acts on that piece, del(MELODY, Y), inside the charade."""
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "deletion" or node.get("unchecked") or len(ps) != 2 or ps[0].get("op") != "charade" \
                or "op" in ps[1] or ps[1].get("words") or not ps[1].get("gives"):
            continue
        pcs = [p for p in ps[0].get("parts") or [] if isinstance(p, dict)]
        if len(pcs) < 2 or any("op" in p or p.get("unchecked") for p in pcs):
            continue
        gs = [wordplay.letters(p.get("gives") or p.get("words")) for p in pcs]
        cut = wordplay.letters(ps[1]["gives"])
        hold = [g for g in gs if cut in g and len(g) > len(cut)]
        n += bool(cut) and len(hold) == 1 and sum(cut in g for g in gs) == 1 and not any(set(g) <= set(cut) for g in gs)
    return n


def ana_is_move(tree, answer=None):
    """Anagrams of one plain leaf of 5+ letters whose answer holds the leaf with exactly one letter moved and not
    the leaf itself (r40 FN BRASSERIE ana(BRASSIERE), INTER ana(INERT)): a letter move is move<indicator>(fodder, MOVED)."""
    ans = wordplay.letters(answer).lower() if answer else ""
    if not ans:
        return 0
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "anagram" or node.get("unchecked") or len(ps) != 1 or "op" in ps[0] or not ps[0].get("gives"):
            continue
        f = wordplay.letters(ps[0]["gives"]).lower()
        if len(f) < 5 or f in ans or not any(_MOVE_IND.search(str(i.get("text") or ""))
                                             for i in node.get("indicators") or [] if isinstance(i, dict)):
            continue
        moved = set()
        for i in range(len(f)):
            rest = f[:i] + f[i + 1:]
            moved |= {rest[:j] + f[i] + rest[j:] for j in range(len(f))}
        n += any(m != f and m in ans for m in moved)
    return n


DEL_AS_MOVE = "deletion whose indicator is a movement word (moved, shifting, relocating) and whose cut letters are no clue word, a move written as a deletion"
_MOVE_WORD_IND = re.compile(r"\b(?:mov(?:e|es|ed|ing)|shift\w*|relocat\w*|transpos\w*|migrat\w*|transferr?\w*|repositi\w*|displac\w*)\b", re.I)
_MOVE_AWAY = re.compile(r"\b(?:out|away|off|from|leav\w*|exit\w*|gone|departing|removed)\b", re.I)


def del_as_move(tree):
    """Deletions whose indicator is a movement word and whose cut piece is no clue word (r42 FN INGENUE
    del<being moved to take the lead>(GENUINE, IN), MARLONBRANDO del<relocating>(LONDON, N)): the letters appear from
    nowhere, so they are moved, not removed: move<indicator>(fodder, MOVED). Not "moved out/away/off" (a
    departure), and not a tree movedLetter already counts (a sibling gives the cut letter back). r42 judged 1 of
    20 fine; with the cut in a clue word ("shifting ton") 11 of 20 were fine plain deletions."""
    if moved_letters(tree):
        return 0
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        n += (node.get("op") == "deletion" and len(ps) >= 2 and all("op" not in p and not p.get("words") for p in ps[1:])
              and any(_MOVE_WORD_IND.search(t) and not _MOVE_AWAY.search(t)
                      for t in (str(i.get("text") or "") for i in node.get("indicators") or [] if isinstance(i, dict))))
    return n


def behead_in_leaf(tree):
    """Plain leaves of 2+ words holding "losing head", "without its tail", "headless" and giving letters
    (r34 FN IDLER: "Youngster losing head" giving ID): the cut is a deletion with its own indicator.
    r35 judged 3 of 33 fine."""
    return sum(1 for node, words in _plain_leaves(tree)
               if len(words) >= 2 and _BEHEAD.search(" ".join(words)) and len(wordplay.letters(node["gives"])) >= 2)


_NOTE_CAPS = re.compile(r"\b[A-Z]{3,}\b")


def _cut_from_note(g, note):
    """Whether g (lower case) is the start or end of a capitalised word in the note, one or two letters shorter."""
    return any(0 < len(t) - len(g) <= 2 and (t.lower().startswith(g) or t.lower().endswith(g))
               for t in _NOTE_CAPS.findall(note))


def cut_note_leaf(tree):
    """Leaves giving a non-word of 3+ letters whose note says it is a real word minus some letters
    (GAM "game losing its final E", STE "SITE without I", EARY "WEARY, leading W killed"; r28 FN: 5 misses):
    the leaf must be the real word with a deletion op. Needs the lexicon."""
    lex = _lexicon_letters()
    if not lex:
        return 0
    n = 0
    under_cut = {id(p) for node in _walk(tree) if node.get("op") in ("deletion", "move", "substitution")
                 for p in node.get("parts") or [] if isinstance(p, dict)}
    for node, words in _plain_leaves(tree):
        g = wordplay.letters(node["gives"]).lower()
        note = str(node.get("note") or "")
        if len(words) >= 2 and len(g) >= 2 and g in lex and id(node) not in under_cut and not node.get("select") \
                and "'" not in note + str(node.get("words")) and not node.get("soundsLike") \
                and (_CUT_NOTE.search(note) or _CUT_LETTER.search(note) or "cut short" in note) \
                and _cut_from_note(g, note):
            n += 1  # r36 FN: "Pope dismissing foremost" giving OPE, a word, but the note says POPE without the P
            continue
        if len(g) >= 3 and g not in lex and id(node) not in under_cut and not node.get("select") \
                and "'" not in note + str(node.get("words")) and "apostrophe" not in note.lower() \
                and not node.get("soundsLike") \
                and (_CUT_NOTE.search(note) or _CUT_LETTER.search(note)):
            n += 1
    return n


ANA_LONE_EDGE = "anagram scrambles a single letter that the answer shows at its start or end"
ANA_LITERAL_EDGE = "anagram holds a clue word as written at the edge of its fodder, and the answer shows it unscrambled at its edge"
DEL_WRAPS_CHARADE = "deletion wraps a charade though its indicator stands between the charade's pieces, so it cuts one piece"


def _pull_part(tree, node, idx, front):
    """A copy of `tree` with part `idx` of anagram `node` taken out and set beside it in a charade."""
    t = copy.deepcopy(tree)
    for cur in _walk(t):
        if cur.get("op") == "anagram" and cur.get("parts") == node.get("parts") and cur.get("indicators") == node.get("indicators"):
            piece = cur["parts"].pop(idx)
            mid = dict(cur)
            cur.clear()
            cur.update({"op": "charade", "parts": [piece, mid] if front else [mid, piece]})
            return t
    return None


def _anagrams_with_pulled_part(tree, answer, pick, keep_order=False, clue=None):
    """How many anagrams in `tree` have a part `pick(parts, idx)` accepts that, set outside the anagram at
    the start or the end of a charade, still gives the answer. `keep_order`: a first part may only go to the
    start and a last part to the end (the piece stays where the clue put it). With `clue`, a pull that would
    leave the piece's clue words between the anagram's other pieces is no pull: it trades this rule for
    poolGap, and the two cannot both be met (FISTFIGHT "This fine gift may be exchanged": F is genuine
    fodder from the middle of the pool, so the F-first answer is a coincidence, not a lone edge)."""
    if not answer or not isinstance(tree, dict):
        return 0
    try:
        wordplay.evaluate(copy.deepcopy(tree), answer)
    except Exception:
        return 0
    n = 0
    for node in _walk(tree):
        parts = node.get("parts") or []
        if node.get("op") != "anagram" or node.get("unchecked") or len(parts) < 2 or not all(isinstance(p, dict) for p in parts):
            continue
        done = False
        for idx in (i for i in range(len(parts)) if pick(parts, i)):
            for front in (True, False):
                if keep_order and front != (idx == 0):
                    continue
                t = _pull_part(tree, node, idx, front)
                if clue and t is not None and pool_gaps(t, clue) > pool_gaps(tree, clue):
                    continue
                try:
                    wordplay.evaluate(t, answer)
                    done = True
                    break
                except Exception:
                    pass
            if done:
                break
        n += done
    return n


def _one_letter_part(parts, i):
    """A fodder part that is a single letter: a 1-letter leaf or a first/last pick of one letter."""
    p = parts[i]
    if p.get("unchecked"):
        return False
    if "op" in p:
        if p["op"] not in ("first", "last"):
            return False
        try:
            vals = wordplay.values(p)
        except Exception:
            return False
        return any(len(v) == 1 for v in vals)  # values() lists every reading of the pick: CAR, CA and C
    return len(wordplay.letters(p.get("gives") or p.get("words"))) == 1


def ana_lone_edge(tree, answer=None, clue=None):
    """Anagrams with a single-letter fodder piece (an abbreviation, a first/last pick, a lone word like "a")
    anywhere in the fodder, that the answer shows at its start or end (r32 FN: ESPLANADES E + ana(SEDAN ALPS),
    REAWAKEN ana(A + WEAKER) + N, CYPRIOTS C + ana(...)). Paul 10-19: a lone letter that can sit outside the
    anagram must. A letter that sits mid-answer is genuine fodder (Paul's rule 9) and is not counted."""
    return _anagrams_with_pulled_part(tree, answer, _one_letter_part, clue=clue)


def ana_literal_edge(tree, answer=None, clue=None):
    """Anagrams whose first or last fodder piece is 2+ clue-word letters taken as written, which the answer
    shows unscrambled at its edge (r32 FN: ZEROTOLERANCE ZERO + ana(TO + CLEANER) holds TO). Single letters
    are ana_lone_edge's."""
    def literal_edge(parts, i):
        p = parts[i]
        return i in (0, len(parts) - 1) and "op" not in p and not p.get("unchecked") and not _stand_in_piece(p) \
            and len(wordplay.letters(p.get("gives") or p.get("words"))) >= 2
    return _anagrams_with_pulled_part(tree, answer, literal_edge, keep_order=True, clue=clue)


def del_wraps_charade(tree, clue=None):
    """Deletions over a charade of plain leaves whose indicator stands in the clue between two of the
    charade's pieces (r32 FN: del<getting end away>(TWERP + KING, P), rev(del<short>(AS + LASS, S))): the word
    cuts the one piece next to it, so the deletion belongs on that piece inside the charade."""
    if not clue:
        return 0
    low = clue.lower()
    try:
        tree = wordplay.locate(copy.deepcopy(tree), clue)
    except Exception:
        pass
    n = 0
    for node in _walk(tree):
        ps = [p for p in node.get("parts") or [] if isinstance(p, dict)]
        if node.get("op") != "deletion" or node.get("unchecked") or len(ps) != 2 or ps[0].get("op") != "charade":
            continue
        pcs = [p for p in ps[0].get("parts") or [] if isinstance(p, dict)]
        inds = [i for i in node.get("indicators") or [] if isinstance(i, dict) and str(i.get("text") or "")]
        if len(pcs) < 2 or len(inds) != 1 or any("op" in p or p.get("unchecked") for p in pcs):
            continue
        gs = [wordplay.letters(p.get("gives") or p.get("words")) for p in pcs]
        cut = wordplay.letters(ps[1].get("gives"))
        if not cut or any(set(g) <= set(cut) for g in gs) or not any(len(g) > len(cut) and cut in g for g in gs):
            continue  # the removed letters are a piece of the charade itself (daughter D, then D removed): a group deletion
        t = str(inds[0]["text"])
        at = inds[0]["at"] if isinstance(inds[0].get("at"), int) else low.find(t.lower())
        spans = [(min(a for a, _ in s), max(b for _, b in s)) for s in (_subtree_spans(p, clue, low) for p in pcs) if s]
        if at >= 0 and len(spans) == len(pcs) and any(b <= at for _, b in spans) and any(a >= at + len(t) for a, _ in spans):
            n += 1
    return n


def ana_double_indicator(tree):
    """Anagrams with two indicators that are not touching halves of one phrase and both anagram words of
    their own (r23 FN RUDIMENTAL ana<out><unusually>): one op, one indicator."""
    n = 0
    for node in _walk(tree):
        if node.get("op") != "anagram":
            continue
        ins = [i for i in node.get("indicators") or [] if isinstance(i, dict)]
        if len(ins) >= 2 and not all(_ind_adjacent(ins[k], ins[k + 1]) for k in range(len(ins) - 1)) \
                and sum(_own_word("anagram", i.get("text")) for i in ins) >= 2:
            n += 1
    return n