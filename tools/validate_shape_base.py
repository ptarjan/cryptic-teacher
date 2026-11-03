"""Shared small tables and helpers of the validate_shape_* detectors of validate_annotations.py.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import functools
import json
import re
import wordplay

from validate_base import ROOT

def _walk(tree):
    stack = [tree] if isinstance(tree, dict) else []
    while stack:
        node = stack.pop()
        yield node
        stack += [p for p in node.get("parts") or [] if isinstance(p, dict)]
_OP_LEXICON = {"anagram": "anagram", "reversal": "reversal", "container": "container",
               "deletion": "deletion", "hidden": "hidden_word", "homophone": "homophone",
               "spoonerism": "spoonerism", **{s: "letter_selection" for s in wordplay.SELECT}}


REPEAT_WORDS = frozenset("twice double doubly doubled again repeatedly repeated two both".split())
ROLE_TYPES = frozenset(_OP_LEXICON.values())


def indicator_role_key(text):
    """An indicator phrase as indicator_roles.json keys it: each word's letters, space-joined."""
    return " ".join(w for w in (wordplay.letters(x) for x in str(text or "").split()) if w)


@functools.lru_cache(maxsize=1)
def _indicator_roles():
    """{indicator: {op type: uses}} from tools/data/indicator_roles.json; {} when absent."""
    path = ROOT / "tools" / "data" / "indicator_roles.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _role_counts(key):
    """{op type: uses} of an indicator key from indicator_roles.json, the types a vote counts
    for (a charade, substitution or composite is none)."""
    return {t: c for t, c in (_indicator_roles().get(key) or {}).items() if t in ROLE_TYPES}


@functools.lru_cache(maxsize=1)
def _attested():
    """(abbreviation pairs {(WORD, LETTERS)}, usage lexicon {WORD: {LETTERS: n}}): what
    clue words are known to give. Empty when a table is missing, so a rule stands down."""
    try:
        import build_abbreviations as ba
        pairs = {(ba.letters_of(w), k) for k, ws in ba.table().items() for w in ws}
        usage = json.loads((ROOT / "tools" / "data" / "lexicons" / "blocks.json").read_text())
    except (OSError, ValueError, ImportError):
        return set(), {}
    return pairs, {ba.letters_of(w): v for w, v in usage.items()}


#: Standard one-letter readings the tables lack (round 10: PRMAN "Played" P, EYING "electronically" E-).
_EXTRA_PAIRS = frozenset({("PLAYED", "P"), ("ELECTRONICALLY", "E"), ("ELECTRONIC", "E"),
                          ("KOSHER", "K"), ("LITTLE", "L"), ("QUALITY", "Q"),  # round 11
                          ("FAILING", "F"),  # round 12 (a grade)
                          ("ROUBLE", "R"), ("ROUBLES", "R"),  # round 13 (cryptic-22221 ARGENT)
                          ("VIOLET", "V"), ("LICENTIATE", "L"), ("ACROSS", "A"),  # round 14 (judged standard)
                          ("WESTERLY", "W"), ("EASTERLY", "E"), ("NORTHERLY", "N"), ("SOUTHERLY", "S"),  # round 17:
                          ("UNITED", "U"), ("WITHOUT", "W"),
                          ("METERS", "M"), ("METRES", "M"), ("INSTITUTE", "I")})  # round 18 (judged fine)  # compass adjectives, "united" and "without" (w/o), judged fine


def _known_pair(words, gives):
    """Whether (clue words, letters) is an abbreviation the table holds or a reading the
    usage lexicon has seen 3+ times (blocks.json keeps no rarer ones)."""
    pairs, usage = _attested()
    if (re.sub(r"[^A-Z]", "", str(words).upper()), gives) in _EXTRA_PAIRS:
        return True
    # "volume's" (V) and "uranium's" (U): the possessive is the clue's, not part of the word
    bare = re.sub(r"['’]s\b", "", str(words), flags=re.I)
    for text in (str(words), bare):
        key = re.sub(r"[^A-Z0-9]", "", text.upper())
        if (key, gives) in pairs or usage.get(key, {}).get(gives, 0) > 0:
            return True
    return False


#: A deletion indicator that names the end it takes ("opening ... ignored by", hoaxer less the D
#: of Dalloway's): the cut leaf's letter is picked by that word (timesjumbo-1690 29a).
_POSITION_WORD = re.compile(r"\b(opening|first|initial\w*|start\w*|head|top|lead\w*|beginning|last|final\w*|"
                            r"end|tail|finish\w*|closing|hint|touch|trace)\b", re.I)


def _owner_type(text):
    """The op type the corpus files indicator `text` under in 80%+ of 5+ uses, else None."""
    counts = _role_counts(indicator_role_key(text))
    total = sum(counts.values())
    top = max(counts, key=counts.get) if counts else None
    return top if total >= 5 and counts[top] >= 0.8 * total else None
CUT_WORDS = frozenset("short shorter shortly half briefly brief first last lower upper heart centre initially ends "
                      "endless headless topless beheaded curtailed cut clipped docked reduced".split())


def _clue_words(text):
    """Lower-case word set of clue text, markup and parentheticals removed."""
    return set(re.findall(r"[a-z]+", re.sub(r"<[^>]*>|\([^)]*\)", " ", (text or "").lower())))


# Connectives a stripped-down leaf may swallow ("with", "and", "'s"); the fix for
# an unchecked leaf of one is to take it out, so it is no loss when the redo does.
CONNECTIVE_WORDS = frozenset(
    "a an and as at be but by for from has having in is it of on or s that the this to when with".split())


def _accounted_words(ann, leaves=True):
    """The clue words an annotation accounts for: wordplay leaves (when `leaves`;
    "real" skips junk leaves, unchecked with no `gives`), indicators on any op or definition, definitions, and declared link words."""
    got = set()
    for n in _walk(ann.get("wordplay")):
        if leaves and "op" not in n and (leaves != "real" or n.get("gives") or not n.get("unchecked")):
            got |= _clue_words(n.get("words"))
        for i in n.get("indicators") or []:
            got |= _clue_words(i.get("text") if isinstance(i, dict) else i)
    for d in ann.get("definitions") or []:
        got |= _clue_words(d.get("text"))
        for i in d.get("indicators") or []:
            got |= _clue_words(i.get("text") if isinstance(i, dict) else i)
    for lw in ann.get("linkWords") or []:
        got |= _clue_words(lw)
    return got