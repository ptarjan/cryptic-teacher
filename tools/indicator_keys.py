"""The one spelling of an indicator phrase, and the (type, key) pairs a
clue's indicators give.

tools/data/lexicons/indicators.json is keyed by indicator_key(); anything that
looks a phrase up in it — the /indicators/ page, the burn's indicator cover —
must key it the same way, or "upside-down" is counted as UPSIDEDOWN and looked
up as UPSIDE DOWN and never matches.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blog_facts import fold
from difficulty import FUNCTION_WORDS

#: A clue word: hyphens and apostrophes stay inside it, so "upside-down" is one word.
WORD = re.compile(r"[\w'’\-]+")

def letters(s):
    """A word's letters and digits: accents folded, punctuation gone, capitals."""
    return "".join(f for f in map(fold, s) if f.isalnum() and f.isascii()).upper()


def indicator_words(s):
    """The phrase as a tuple of its words' letters."""
    return tuple(l for l in (letters(w) for w in WORD.findall(s or "")) if l)


def indicator_key(s):
    """The phrase as indicators.json keys it: each word's letters, space-joined."""
    return " ".join(indicator_words(s))


def lexicon_key(words, keys):
    """(key, exact) for the indicators.json key among `keys` that a phrase's
    words (indicator_words) stand for, or None: the whole phrase, else the
    longest run of its whole words that is a key, so "variety of" is VARIETY.
    A run of nothing but link words ("of", "in the") is never a match."""
    for n in range(len(words), 0, -1):
        for i in range(len(words) - n + 1):
            run = words[i:i + n]
            if (key := " ".join(run)) in keys and (
                    n == len(words) or not {w.lower() for w in run} <= FUNCTION_WORDS):
                return key, n == len(words)
    return None


def clue_pairs(lex, indicators):
    """{(type, key): exact} for one clue: each indicator object against
    indicators.json `lex` under its own `for`, where `lex` has that type. An
    indicator without `for` gives nothing: which mechanism it signals is unknown.

    A phrase that is not itself a key matches the longest key inside it
    (lexicon_key): "variety of" is anagram VARIETY. That is safe exactly
    because the type is the phrase's own `for`, so a charade's "touched on"
    is only ever looked up among charade keys, never as anagram TOUCHED."""
    out = {}
    for ind in indicators or ():
        t = ind.get("for")
        if t not in lex:
            continue
        hit = lexicon_key(indicator_words(ind["text"]), lex[t])
        if hit and not out.get((t, hit[0])):
            out[(t, hit[0])] = hit[1]
    return out
