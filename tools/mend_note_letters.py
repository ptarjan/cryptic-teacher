"""Mechanical mend for validate_shape_ops.single_leaf ("1 clue(s) missing wordplay.singleLeaf") on the
musical-letters clue: [notes]ACCEDE, [a bunch of keys]DEFACE, [Five keys with one duplicate]FACADE.

The whole wordplay is one leaf whose clue words are "notes" or "keys" and the answer is spelt only with
the letters A-G: the clue is a charade of one note per letter. That reading is not a guess, so it is
written out as `[words]A + [words]C + ...` (the words repeated once per letter, which the validator
accepts) instead of costing a model turn. A leaf whose words do not name notes or keys, or an answer with
a letter outside A-G, is left to the model: it is a synonym or a real mechanism, not this shape.
annotate_check runs it on the model's `wp` in each fresh annotation."""
import copy
import re

import validate_annotations as V
import wordplay

_NOTE_WORDS = re.compile(r"\b(?:notes?|keys?)\b", re.I)


def mend(a, clue, answer):
    """Rewrite model-shape annotation `a`'s `wp` in place; whether it changed."""
    wp = a.get("wp") if isinstance(a, dict) else None
    if not (isinstance(wp, str) and clue and answer):
        return False
    letters = re.sub(r"[^A-Za-z]", "", answer).upper()
    if len(letters) < 3 or re.search(r"[^A-G]", letters):
        return False
    try:
        tree = wordplay.parse(wp, clue)
        if not V.single_leaf(tree):
            return False
        words = tree.get("words") or ""
        if not _NOTE_WORDS.search(words):
            return False
        new = " + ".join(f"[{words}]{c}" for c in letters)
        fixed = wordplay.parse(new, clue)
        wordplay.evaluate(copy.deepcopy(fixed), answer)
        if V.single_leaf(fixed) or V.span_overlaps(fixed):
            return False
    except Exception:
        return False
    a["wp"] = new
    notes = a.get("notes")
    if isinstance(notes, dict) and words not in notes:
        notes[words] = "each letter is a musical note or key"
    return True
