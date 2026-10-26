#!/usr/bin/env python3
"""tools/learn_postproc.py: the classes a rewrite is counted under, and the
scoring of a rule (hits, closer, worse, fixpoint) on old/new pairs.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import learn_postproc as L

failed = []


def check(what, want, got):
    if want != got:
        failed.append(f"{what}: want {want!r}, got {got!r}")


for what, a, b, want in (
        ("a stray stop", ".", "", "stray-token:."),
        ("a middle dot token", "·", "", "stray-token:·"),
        ("a space lost", "fe males", "females", "space:removed"),
        ("a space added", "Teasea", "Tease a", "space:added"),
        ("one character swapped", "tains", "rains", "char:t>r"),
        ("a case change", "in", "In", "case"),
        ("a trailing apostrophe", "Israelites'", "Israelites", "punct:d['>]"),
        ("a number cut", "14", "", "delete-number"),
        ("a word cut", "stab", "", "delete-word"),
        ("a word added", "", "in", "insert-word"),
        ("the same", "x", "x", "same")):
    check(f"classify_edit: {what}", want, L.classify_edit(a, b))

# Edits are word-level: only the words that differ come back.
check("edits", [("Chaidean", "Chaldean")], L.edits("Chaidean trip ?", "Chaldean trip ?"))
check("edits: none", [], L.edits("same words", "same words"))

# A table counts each edit once per class and lists the clues it touched.
pairs = [{"old": "grey . donkey", "new": "grey donkey"},
         {"old": "a . b . c", "new": "a b c"},
         {"old": "fe males", "new": "females"}]
rows = {r[0]: r[1:3] for r in L.table(pairs)}
check("table: stray stop edits and clues", (3, 2), rows.get("stray-token:."))
check("table: space edits", (1, 1), rows.get("space:removed"))

# Scoring: a rule that turns old into new is a hit; one that changes a text a
# reread produced is a fixpoint violation; one that moves away is worse.
pairs = [{"old": "go 2to it", "new": "go to it", "old_enum": "5", "new_enum": "5"},
         {"old": "stay", "new": "stay put", "old_enum": "5", "new_enum": "5"}]


def drop_figure(text, enum):
    return text.replace("2to", "to")


def drop_letter(text, enum):
    return text.replace("stay", "sty")


check("score: a rule that is right", [("r", 1, 0, 0, 0)], L.score(pairs, {"r": drop_figure}))
check("score: a rule that is wrong", [("r", 0, 0, 1, 1)], L.score(pairs, {"r": drop_letter}))

if failed:
    print("\n".join(failed))
    sys.exit(1)
print("ok")
