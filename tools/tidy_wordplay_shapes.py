#!/usr/bin/env python3
"""Rewrite the wordplay shapes that say nothing extra, and record the rest, corpus-wide.

    python3 tools/tidy_wordplay_shapes.py puzzles/              # count, write nothing
    python3 tools/tidy_wordplay_shapes.py puzzles/ --write      # rewrite in place, record the allowances
    python3 tools/tidy_wordplay_shapes.py puzzles/ --commit     # rewrite, then one commit

validate_annotations holds a wordplay tree to a few shape rules
(CHARADE_IN_CHARADE, NO_INDICATOR, CDEF_REPEAT, STORED_ARITY, SPAN_OVERLAP,
IN_DEFINITION, LEAF_FOLD, REPEATED_SELECTION, SINGLE_LEAF, BARE_IN_CHARADE,
ANAGRAM_OF_CONTAINER), each a ratchet field in tools/annotation_backlog.json.
This writes the allowance for each: the clues a puzzle has now, which it may keep
and may not add to.

One shape is rewritten, because it can be without changing what anyone sees: a
charade with no indicator directly inside a charade is the one charade written in
pieces (a + (b + c) is a + b + c), so its parts join the outer one in the same
order. A clue is rewritten only when annotation.view() reads the same before and
after; one whose view would change is left and counted in the allowance. Nothing
else is mechanical: a missing indicator, a cryptic definition's second leaf (it
carries its own note), a span claimed twice, a leaf that folds a selection into
itself each need the clue read again, so they are counted and left. Nothing is
un-hinted and nothing becomes due to be annotated again.

A schema-migration commit, exempt from one commit per puzzle (as f59e109ad6).
Each file is rewritten whole (a .part renamed over it), so a kill loses nothing
and the same command resumes: a flattened file has nothing left to flatten.
"""
import argparse
import collections
import copy
import json
import os
import subprocess
import sys

import annotation
import puzzle_schema
import validate_annotations as V

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: ratchet field -> how many findings one annotation has.
FIELDS = {
    "wordplay.charadeInCharade": lambda ann: V.charade_in_charade(ann.get("wordplay")),
    "wordplay.noIndicator": lambda ann: V.unindicated_ops(ann.get("wordplay")),
    "wordplay.cdefRepeat": lambda ann: V.cdef_repeats(ann.get("wordplay")),
    "wordplay.arity": lambda ann: V.bad_arity(ann.get("wordplay")),
    "wordplay.spanOverlap": lambda ann: V.span_overlaps(ann.get("wordplay")),
    "wordplay.inDefinition": V.in_definition,
    "wordplay.leafFold": lambda ann: V.leaf_folds(ann.get("wordplay")),
    "wordplay.repeatedSelection": lambda ann: V.repeated_selections(ann.get("wordplay")),
    "wordplay.singleLeaf": lambda ann: V.single_leaf(ann.get("wordplay")),
    "wordplay.bareInCharade": lambda ann: V.bare_in_charade(ann.get("wordplay"), ann),
    "wordplay.anagramOfContainer": lambda ann: V.anagram_of_container(ann.get("wordplay")),
    "wordplay.arityIns": lambda ann: V.arity_ins(ann.get("wordplay")),
    "wordplay.arityOther": lambda ann: V.arity_other(ann.get("wordplay")),
    "wordplay.delSingle": lambda ann: V.del_single(ann.get("wordplay")),
    "wordplay.indInLeaf": lambda ann: V.ind_in_leaf(ann.get("wordplay")),
    "wordplay.scrambledLeaf": lambda ann: V.scrambled_leaves(ann.get("wordplay")),
}


def _inner(p):
    return (p.get("op") == "charade" and not p.get("indicators") and not p.get("unchecked")
            and "gives" not in p)


def flatten_tree(node):
    """Join every indicator-less charade inside a checked charade into it, in
    place: how many charades went."""
    if not isinstance(node, dict):
        return 0
    n = 0
    if node.get("op") == "charade" and not node.get("unchecked"):
        new, changed = [], False
        for p in node.get("parts") or []:
            if isinstance(p, dict) and _inner(p):
                n += 1 + flatten_tree(p)
                new += p.get("parts") or []
                changed = True
            else:
                new.append(p)
        if changed:
            node["parts"] = new
    for p in node.get("parts") or []:
        n += flatten_tree(p)
    return n


def flatten_puzzle(puzzle):
    """charades joined, in place, in each clue whose view() stays the same."""
    done = 0
    for _, entry, ann in puzzle_schema.annotations(puzzle):
        if not V.charade_in_charade(ann.get("wordplay")):
            continue
        new = copy.deepcopy(ann)
        k = flatten_tree(new["wordplay"])
        try:
            same = annotation.view(ann, entry) == annotation.view(new, entry)
        except Exception:
            same = False
        if k and same:
            ann["wordplay"] = new["wordplay"]
            done += k
    return done


def counts(puzzle):
    """{field: clues with a finding}."""
    out = collections.Counter()
    for _, _, ann in puzzle_schema.annotations(puzzle):
        for f, fn in FIELDS.items():
            out[f] += bool(fn(ann))
    return out


def tidy_file(path, write):
    with open(path, encoding="utf-8") as fh:
        puzzle = json.load(fh)
    done = flatten_puzzle(puzzle)
    if done and write:
        part = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.part")
        with open(part, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n")
        os.replace(part, path)
    return done, counts(puzzle)


def write_allowances(left):
    """left: {field: {puzzle: clues}}. Each field's list is the smaller of it and
    any list already there, so a re-run only ever tightens it."""
    path = V.BACKLOG_PATH
    data = json.loads(path.read_text())
    for f, rows in left.items():
        had = data.get(f)
        data[f] = {k: min(n, had.get(k, n)) if had is not None else n
                   for k, n in sorted(rows.items(), key=V._sort_key) if n}
    order = list(V.BACKLOG_MARKERS)
    out = {k: data[k] for k in order if k in data}
    out.update({k: v for k, v in data.items() if k not in out})
    path.write_text(json.dumps(out, indent=1) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="the puzzles/ folder")
    ap.add_argument("--write", action="store_true", help="rewrite the files in place and record the allowances")
    ap.add_argument("--commit", action="store_true", help="--write, then make the one migration commit")
    a = ap.parse_args()
    write = a.write or a.commit
    files = sorted(os.path.join(d, f) for d, _, fs in os.walk(a.root) for f in fs
                   if f.endswith(".json") and not f.startswith("."))
    done = puzzles = 0
    left = {f: {} for f in FIELDS}
    for i, path in enumerate(files, 1):
        n, c = tidy_file(path, write)
        puzzles += bool(n)
        done += n
        pid = os.path.basename(path)[:-len(".json")]
        for f, k in c.items():
            if k:
                left[f][pid] = k
        if i % 5000 == 0:
            print(f"tidy: {i}/{len(files)} files, {done} charades", file=sys.stderr, flush=True)
    subject = f"Join {done} charades inside charades in {puzzles} puzzles, and count the other wordplay shape faults"
    print(subject)
    for f, rows in left.items():
        print(f"{f}: {sum(rows.values())} clues in {len(rows)} puzzles")
    if write:
        write_allowances(left)
    if not a.commit:
        return
    lines = "\n".join(f"- {f}: {sum(r.values())} clues in {len(r)} puzzles" for f, r in left.items())
    body = (f"{subject}\n\nA charade with no indicator directly inside a charade is the one charade "
            f"written in pieces: tools/tidy_wordplay_shapes.py over {len(files)} files joined its parts "
            f"into the outer one, in order, in every clue whose annotation.view() is identical before "
            f"and after. {done} charades in {puzzles} puzzles. The other shape rules in "
            f"validate_annotations need the clue read again (a missing indicator, a cryptic "
            f"definition's second leaf, a span claimed twice, a leaf that folds a selection into "
            f"itself), so what each puzzle has now is its allowance in tools/annotation_backlog.json, "
            f"which validate_annotations holds every puzzle to from here:\n\n{lines}\n\n"
            f"A schema migration, exempt from one commit per puzzle (as f59e109ad6). Nothing is "
            f"un-hinted or due again. The old text is in this commit's parent.\n")
    trailer = subprocess.run([sys.executable, os.path.join(REPO, "tools", "provenance.py"), "trailer"],
                             capture_output=True, text=True).stdout.strip()
    if trailer:
        body += "\n" + trailer + "\n"
    subprocess.run(["git", "-C", REPO, "add", "--", os.path.relpath(os.path.abspath(a.root), REPO),
                    os.path.relpath(str(V.BACKLOG_PATH), REPO)], check=True)
    subprocess.run(["git", "-C", REPO, "commit", "-q", "-F", "-"], input=body, text=True, check=True)
    print(subprocess.run(["git", "-C", REPO, "log", "-1", "--format=committed: %h %s"],
                         capture_output=True, text=True).stdout.strip())


if __name__ == "__main__":
    main()
