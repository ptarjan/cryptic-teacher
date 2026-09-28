#!/usr/bin/env python3
"""The closed list of clue types, read from tools/data/clue_types.json.

An annotation's `type` is an array of these names, in the order the devices
are applied. app.js reads the same file (embedded in puzzles/index.js by
tools/fetch_puzzle.py --reindex), so the list exists once.

A `letter_selection` says which letters on the block that keeps them, as
`select`: one of SELECT_WORDS, or an int n for "the nth letter".
"""
import json
from pathlib import Path

PATH = Path(__file__).resolve().parent / "data" / "clue_types.json"
DATA = json.loads(PATH.read_text(encoding="utf-8"))
TYPES = {t["name"]: t for t in DATA["types"]}
NAMES = tuple(TYPES)
FAMILIES = DATA["families"]
SELECT_WORDS = ("first", "last", "middle", "outer", "alternate", "regular", "prime")

# Shown when a type matches no family. The app has the same fallback.
FALLBACK_FAMILY = {"name": None, "label": "Wordplay", "n": 0,
                   "blurb": "The clue has a definition at one end and wordplay at the other."}


def label(name):
    return TYPES[name]["label"]


def labels(types):
    """A type array as a reader would say it: "charade + letter selection"."""
    return " + ".join(label(t) for t in types or ())


def families_of(types):
    """Every family the types use, in FAMILIES' precedence order."""
    used = {TYPES[t]["family"] for t in types or () if t in TYPES}
    return [f for f in FAMILIES if f["name"] in used]


def family_of(types):
    """The dominant family: the first of families_of, or the fallback."""
    return (families_of(types) or [FALLBACK_FAMILY])[0]


def valid_select(v):
    return v in SELECT_WORDS or (isinstance(v, int) and not isinstance(v, bool) and 2 <= v <= 20)


if __name__ == "__main__":
    for f in FAMILIES:
        print(f"{f['label']}: {', '.join(t for t in NAMES if TYPES[t]['family'] == f['name'])}")
