"""The one spelling of an indicator phrase, and whether an annotation's type
names an indicator type.

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


def names_type(kind, types):
    """Whether an annotation's (or a blog's) type array names indicator type
    `kind`: indicators.json is keyed by the same clue_types names."""
    return kind in (types or ())
