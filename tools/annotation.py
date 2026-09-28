"""An annotation's two groups, read the same way by every tool.

`explanation` is the prose the last hint rung prints (walkthrough, surface,
definitionFit); `assembly` rebuilds the answer for a machine to check (pieces,
anagrams, reversals). tools/data/puzzle.schema.json says what each key means.
"""
import re
import unicodedata


def explanation(ann):
    """The annotation's prose: walkthrough, surface, definitionFit."""
    x = ann.get("explanation")
    return x if isinstance(x, dict) else {}


def assembly(ann):
    """The annotation's machine-checkable rebuild: pieces, anagrams, reversals."""
    x = ann.get("assembly")
    return x if isinstance(x, dict) else {}


def _letters(s):
    """A-Z letters, accents folded (É is E), as validate_annotations.letters."""
    return re.sub(r"[^A-Z]", "", unicodedata.normalize("NFD", str(s or "")).upper())


def whole_anagram(ann):
    """The fodder of the anagram whose gives is the whole answer, or None."""
    want = _letters(ann.get("answer"))
    for a in assembly(ann).get("anagrams") or []:
        if want and isinstance(a, dict) and _letters(a.get("gives")) == want:
            return a.get("fodder")
    return None
