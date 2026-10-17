"""The hidden words a clue gives away mechanically.

A clue is a near-certain hidden word when every word of it is accounted for as
definition, indicator or fodder, and nothing else could be going on:

    [definition] [link] [indicator] FODDER     "Chief of some peculiar church"
    FODDER [indicator] [link] [definition]     (ARCH hides in "peculiar church")

where FODDER is the run of whole words the answer's letters (forwards, or
backwards under a reversal indicator) spell across, starting and ending inside
a word, and the indicator is a phrase from tools/data/lexicons/indicators.json
under hidden_word (or reversal, for a backwards run).  Measured on the
committed annotations, 99.6% of the clues that parse this way are hidden
words; see CALIBRATION in tools/validate_annotations.py check_mechanical_hidden.
"""
import json
import re
from pathlib import Path

from indicator_keys import indicator_words, letters

LEXICON = Path(__file__).parent / "data" / "lexicons" / "indicators.json"
WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")

#: Words that may join the definition to the rest ("is", "from") or sit
#: between the indicator and the fodder ("in", "of").
LINKS = frozenset("a an and as at by for from give gives giving in is of on showing the to with within yields".split())

MIN_ANSWER = 4

_keys = None


def indicator_keys():
    """{'hidden_word': set of keys, 'reversal': set of keys}, read once."""
    global _keys
    if _keys is None:
        lex = json.load(open(LEXICON))
        _keys = {k: frozenset(lex[k]) for k in ("hidden_word", "reversal")}
    return _keys


def _runs(words, answer):
    """(direction, first word, last word) for each place `answer` spells itself
    across 2+ words, beginning and ending inside a word."""
    text, owner = [], []
    for n, w in enumerate(words):
        for ch in letters(w):
            text.append(ch)
            owner.append(n)
    text = "".join(text)
    out = []
    for direction, target in (("forwards", answer), ("reversed", answer[::-1])):
        if direction == "reversed" and target == answer:
            continue
        i = text.find(target)
        while i >= 0:
            j = i + len(target) - 1
            if owner[i] != owner[j]:
                inside_start = i > 0 and owner[i - 1] == owner[i]
                inside_end = j + 1 < len(text) and owner[j + 1] == owner[j]
                if inside_start or inside_end:
                    out.append((direction, owner[i], owner[j]))
            i = text.find(target, i + 1)
    return out


def _phrase(tokens, keys, base=0):
    """The (first, end) word range of the phrase of `keys` that `tokens` are,
    counted from `base`, with at most one link word at either edge ("in" of
    "hidden in") left out; None when they are not one."""
    for lo in (0, 1):
        for hi in (0, 1):
            core = tokens[lo:len(tokens) - hi]
            if (core and all(w in LINKS for w in tokens[:lo] + tokens[len(tokens) - hi:])
                    and " ".join(core) in keys):
                return base + lo, base + len(tokens) - hi
    return None


def _region(tokens, direction):
    """How `tokens` read as the indicator region beside the fodder, as
    (hidden range, reversal range), either None: forwards a hidden indicator;
    backwards a reversal indicator, with or without a hidden one next to it,
    in either order. None when they are no indicator region."""
    lex = indicator_keys()
    if direction == "forwards":
        hid = _phrase(tokens, lex["hidden_word"])
        return (hid, None) if hid else None
    if (rev := _phrase(tokens, lex["reversal"])):
        return None, rev
    for cut in range(1, len(tokens)):
        for hid_at, rev_at in ((0, cut), (cut, 0)):
            hid = _phrase(tokens[hid_at:hid_at + (cut if hid_at == 0 else len(tokens) - cut)],
                          lex["hidden_word"], hid_at)
            rev = _phrase(tokens[rev_at:rev_at + (cut if rev_at == 0 else len(tokens) - cut)],
                          lex["reversal"], rev_at)
            if hid and rev:
                return hid, rev
    return None


def _regions(seq, direction, at_end):
    """(words in the region, its reading) for each indicator region that is the
    last (or first) words of `seq`."""
    out = []
    for size in range(1, min(len(seq), 6) + 1):
        part = seq[len(seq) - size:] if at_end else seq[:size]
        if (read := _region(part, direction)):
            out.append((size, read))
    return out


def find(clue, answer):
    """The one near-certain hidden-word parse of `clue` for `answer`, or None.

    {"direction", "fodder": the clue's words the answer spells across,
    "hidden": the hidden indicator's words or None, "reversal": the reversal
    indicator's words or None, "definition": the words left over (the clue's
    front or back), "at": the definition's offset in the clue}."""
    answer = letters(answer)
    if len(answer) < MIN_ANSWER:
        return None
    matches = list(WORD.finditer(clue))
    words = [m.group() for m in matches]
    toks = [" ".join(indicator_words(w)) for w in words]
    n = len(words)
    parses = []
    for direction, a, b in _runs(words, answer):
        left, right = toks[:a], toks[b + 1:]
        # (definition's first word and count, indicator region's first word and
        # count, its reading): the definition is a whole end of the clue, the
        # indicator region the words by the fodder.
        layouts = []
        if not right:       # [definition] [indicator] FODDER
            layouts += [(0, a - t, a - t, t, r) for t, r in _regions(left, direction, True) if t < len(left)]
        if not left:        # FODDER [indicator] [definition]
            layouts += [(b + 1 + t, n - b - 1 - t, b + 1, t, r)
                        for t, r in _regions(right, direction, False) if t < len(right)]
        if left and right:
            # [definition] FODDER [indicator]
            layouts += [(0, a, b + 1, t, r) for t, r in _regions(right, direction, True) if t == len(right)]
            # [indicator] FODDER [definition]
            layouts += [(b + 1, len(right), 0, t, r) for t, r in _regions(left, direction, False) if t == len(left)]
        for first, n_def, ind_first, n_ind, (hid, rev) in layouts:
            region = words[ind_first:ind_first + n_ind]
            def phrase(span):
                return " ".join(region[span[0]:span[1]]) if span else None
            parses.append({
                "direction": direction,
                "fodder": clue[matches[a].start():matches[b].end()],
                "region": " ".join(region),
                "hidden": phrase(hid), "reversal": phrase(rev),
                "definition": clue[matches[first].start():matches[first + n_def - 1].end()],
                "at": matches[first].start()})
    if len({(p["fodder"], p["definition"]) for p in parses}) != 1:
        return None
    return parses[0]
