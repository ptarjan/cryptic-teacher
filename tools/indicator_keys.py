"""The one spelling of an indicator phrase, and which indicator types an
annotation's type names.

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

#: How an annotation's type names each indicator type, where not by the type's
#: own name: selection clues are typed "first letter", "alternate letters"...
TYPE_NAMES = {"selection": ("selection", "letter")}


def letters(s):
    """A word's letters and digits: accents folded, punctuation gone, capitals."""
    return "".join(f for f in map(fold, s) if f.isalnum() and f.isascii()).upper()


def indicator_words(s):
    """The phrase as a tuple of its words' letters."""
    return tuple(l for l in (letters(w) for w in WORD.findall(s or "")) if l)


def indicator_key(s):
    """The phrase as indicators.json keys it: each word's letters, space-joined."""
    return " ".join(indicator_words(s))


def names_type(kind, annotation_type):
    """Whether an annotation's (or a blog's) type names indicator type `kind`.
    The type may be one string ("charade + container") or a list of them."""
    if isinstance(annotation_type, (list, tuple)):
        annotation_type = " + ".join(annotation_type)
    kinds = (annotation_type or "").lower()
    return any(n in kinds for n in TYPE_NAMES.get(kind, (kind,)))
