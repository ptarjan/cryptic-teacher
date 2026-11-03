"""The validator's shared ground: the type vocabulary, the word list and letter readers, the authored-puzzle switch.

Moved out of validate_annotations.py unchanged; that module re-exports every name here.
"""

import functools
import re
import unicodedata
from pathlib import Path
import clue_types

ROOT = Path(__file__).resolve().parent.parent

# The controlled vocabulary for `type`: an array of names from
# tools/data/clue_types.json, naming EVERY mechanism the wordplay uses in the
# order it is applied (see docs/STYLE.md — "honest types"). A letter_selection says
# which letters on the block that keeps them, as `select`.
TYPE_NAMES = clue_types.NAMES


def types_of(ann):
    """The annotation's type array; check_type reports anything else."""
    t = ann.get("type")
    return t if isinstance(t, list) else []


def indicator_texts(ann, kind=None):
    """The clue words of each indicator object; check_indicators reports bad shapes.

    With `kind`, only the indicators whose `for` is that type, plus those with
    no `for`, which could signal any of the clue's types."""
    return [i["text"] for i in ann.get("indicators") or []
            if isinstance(i, dict) and isinstance(i.get("text"), str)
            and (kind is None or i.get("for") in (None, kind))]


def check_type(tag, ann, errors):
    """`type` is a non-empty array of distinct names from clue_types.json, and a
    letter_selection has at least one block saying which letters (`select`)."""
    t = ann.get("type")
    if not isinstance(t, list) or not t:
        errors.append(
            f"{tag}: type must be a non-empty array of names from tools/data/"
            f"clue_types.json, e.g. [\"charade\", \"reversal\"]; got {t!r}")
        return
    for name in t:
        if name not in TYPE_NAMES:
            errors.append(
                f"{tag}: type {name!r} is not in the controlled vocabulary "
                f"({', '.join(TYPE_NAMES)}). The list is closed and this run "
                f"cannot extend it, so if no name fits, the parse is wrong: find "
                f"the mechanism the list does name")
    if len(set(t)) != len(t):
        errors.append(f"{tag}: type {t!r} names a mechanism twice; list each once")
    selects = [b["select"] for b in ann.get("blocks") or [] if "select" in b]
    for v in selects:
        if not clue_types.valid_select(v):
            errors.append(
                f"{tag}: block select {v!r} is not one of "
                f"{', '.join(clue_types.SELECT_WORDS)} or a letter position 2..20")
    if "letter_selection" in t and not selects:
        errors.append(
            f"{tag}: type has letter_selection but no block says which letters. "
            f"Put `select` on the block that keeps them: "
            f"{', '.join(clue_types.SELECT_WORDS)}, or n for the nth letter")
    if selects and "letter_selection" not in t:
        errors.append(f"{tag}: a block has `select` but type {t!r} has no "
                      f"letter_selection — add it or drop the field")


# Set by --unscoped: run the authored-only checks on published puzzles as well.
# This exists so the calibration in every authored check's docstring can be
# reproduced in one command instead of a throwaway script.
FORCE_AUTHORED_CHECKS = False


def is_authored(puzzle):
    """Did we write this puzzle, or is it a published Guardian grid?

    Ours carry series "authored" (tools/series.py). The field decides, never the
    spelling of the id. The distinction matters because
    the checks below are AUTHORING rules, not annotation rules: real setters
    pad their surfaces and write long clues, and an annotation of a published
    grid has to be able to record that faithfully."""
    return FORCE_AUTHORED_CHECKS or puzzle.get("series") == "authored"


# A real English wordlist, used to tell a genuine inflection from a coincidence:
# MARAUDING is a gerund (MARAUD is a word) but VIKING is not (VIK is not), and
# EARPHONES is a plural (EARPHONE is a word). Without it the part-of-speech
# checks fire on every answer that merely happens to end in -S or -ING.
def _load_words():
    for p in ("/usr/share/dict/words", "/usr/dict/words"):
        try:
            return {w.strip().lower() for w in open(p, encoding="utf-8", errors="ignore")}
        except OSError:
            continue
    return set()  # no dictionary here: the inflection checks quietly stand down


WORDS = _load_words()


def letters(s):
    """The A-Z letters of a string, with accents folded rather than dropped.

    A hidden word is checked against the clue's own letters, so a clue that
    spells the answer across an accented word must keep the accented letter:
    12422 23A hides PESTO in "canapés today", and dropping the É would put the
    answer outside the clue. The Independent and the Guardian both
    print accents (canapés, café, née), and a solver reads them as the plain
    letter — so the validator has to as well. NFD splits É into E plus a
    combining acute; the character class then keeps the E and drops the mark."""
    s = unicodedata.normalize("NFD", (s or "").upper())
    return re.sub(r"[^A-Z]", "", s)


def _starts(needle, text):
    """Where `needle` (non-empty) occurs in `text`, not overlapping: re.finditer
    over re.escape(needle) without compiling a pattern per needle, which at
    ~1 per link word and fragment per clue overran the re cache and was
    ~1/3 of the full check's time."""
    i = text.find(needle)
    while i >= 0:
        yield i
        i = text.find(needle, i + len(needle))


@functools.lru_cache(maxsize=None)
def _whole_word(word):
    return re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)")


def words_of(s):
    """Lowercase word list, with markup, the (8) enumeration and punctuation dropped.

    Guardian clue text sometimes carries literal HTML — 30046 19A and 30072 27A
    both italicise a word — and a tag name such as 'span' is not a word of the
    clue, so nothing could honestly claim it in the coverage check.
    """
    s = re.sub(r"<[^>]*>", " ", s or "")
    return re.findall(r"[a-z]+", re.sub(r"\([^)]*\)", " ", s.lower()))