#!/usr/bin/env python3
"""Drop the made-up `gives` of a fodder leaf inside an anagram (shape round 3, 10-17).

    python3 tools/fix_scrambled_gives.py            # dry run: counts and 12 before/after examples
    python3 tools/fix_scrambled_gives.py --apply    # write the repaired puzzles
    python3 tools/fix_scrambled_gives.py --queue    # also list clues left, for shape_reannotate.json (stdout)

A fodder leaf gives its own letters in order; only an anagram op scrambles. The
corpus often wrote the scrambled result on the leaf instead ([Lido]IDOL under
ana, [sip]ISP, [Freed]FERDE): a made-up synonym that shows as an `S` in the
skeleton. The validator's scrambledLeaf rule flags such a leaf under a charade
or container but exempts the direct child of an anagram, so thousands slipped
past it. The meaning is the same without the made-up letters: the leaf becomes
verbatim clue words, and the anagram above it does the scrambling.

The repair applies to a leaf (checked or not) with an anagram anywhere above it
whose gives is a permutation of its words' letters, not equal to them. It is kept
only when the tree still evaluates to the answer, no more nodes are unchecked,
the shape findings do not grow, and the puzzle's validate_annotations errors are
no more than before (the same gate as tools/fix_shape_suspects.py). A leaf under
a reversal or cycling op is left alone: there the permutation may be the op's
input or result, and which it is takes a reading of the clue.

One commit for the whole sweep (a mechanical one, as fix_shape_suspects.py is).
Only one corpus job at a time.
"""
import argparse
import collections
import copy
import json
import multiprocessing
import os
import random
import sys

import fix_shape_suspects as fs
import puzzle_paths
import wordplay as W

MIN_LEN = 2


def scrambled(tree):
    """[(leaf node)] of the repairable leaves in `tree` (see the docstring)."""
    out = []

    def go(node, anagram_above):
        if "op" in node:
            above = anagram_above or node["op"] == "anagram"
            for p in node.get("parts") or []:
                if isinstance(p, dict):
                    go(p, above)
            return
        if not anagram_above or not node.get("words") or not node.get("gives"):
            return
        w, g = W.letters(node["words"]), W.letters(node["gives"])
        if len(g) >= MIN_LEN and g != w and collections.Counter(g) == collections.Counter(w):
            out.append(node)
    if isinstance(tree, dict):
        go(tree, False)
    return out


def repaired(tree):
    new = copy.deepcopy(tree)
    for lf in scrambled(new):
        lf.pop("gives", None)
        lf.pop("unchecked", None)
    return new


def do_puzzle(path):
    """(counts, examples, left) for one puzzle file; the file is rewritten when apply."""
    apply = _APPLY
    stat = collections.Counter()
    examples, left = [], []
    try:
        puzzle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return stat, examples, left
    fixes = []
    for k, e in enumerate(puzzle.get("entries") or []):
        ann = e.get("annotation")
        if not ann or not isinstance(ann.get("wordplay"), dict):
            continue
        todo = scrambled(ann["wordplay"])
        if not todo:
            continue
        stat["clues_flagged"] += 1
        cid = f"{puzzle.get('id') or path.stem}#{fs.eid_of(e)}"
        clue = (e.get("clue") or {}).get("text", "")
        answer = e.get("solution", "")
        new_ann = {**ann, "wordplay": repaired(ann["wordplay"])}
        old = fs.hits(ann, clue, answer)
        try:
            W.evaluate(copy.deepcopy(new_ann["wordplay"]), answer)
            nh = fs.hits(new_ann, clue, answer)
            good = (set(nh) <= set(old) and fs.unchecked(new_ann["wordplay"]) <= fs.unchecked(ann["wordplay"])
                    and not (fs.shape_counts(new_ann) - fs.shape_counts(ann)))
        except (W.WordplayError, IndexError, KeyError, TypeError, ValueError):
            good = False
        if not good:
            stat["rejected_by_clue_gate"] += 1
            left.append({"id": cid, "reason": "scrambledLeaf"})
            continue
        fixes.append((k, new_ann, {"id": cid, "clue": clue, "answer": answer,
                                   "before": fs.cs.compact(ann["wordplay"]),
                                   "after": fs.cs.compact(new_ann["wordplay"])}))
    if not fixes:
        return stat, examples, left
    allowed = _ALLOWED
    base = fs.puzzle_errors(puzzle, path, allowed)

    def ok(group):
        trial = copy.deepcopy(puzzle)
        for k, new_ann, _ in group:
            trial["entries"][k]["annotation"] = new_ann
        return fs.puzzle_errors(trial, path, allowed, committed=puzzle) <= base
    kept = fixes if ok(fixes) else []
    if not kept:
        for f in fixes:
            if ok(kept + [f]):
                kept.append(f)
    for f in fixes:
        if f not in kept:
            stat["rejected_by_validator"] += 1
            left.append({"id": f[2]["id"], "reason": "scrambledLeaf"})
    stat["clues_repaired"] += len(kept)
    examples += [f[2] for f in kept]
    if kept:
        stat["puzzles_repaired"] += 1
        if apply:
            for k, new_ann, _ in kept:
                puzzle["entries"][k]["annotation"] = new_ann
            part = path.parent / f".{path.name}.part"
            part.write_text(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(part, path)
            stat["puzzles_written"] += 1
    return stat, examples, left


_APPLY = False
_ALLOWED = None


def main():
    global _APPLY, _ALLOWED
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--queue", action="store_true", help="print the clues left as shape_reannotate.json rows")
    ap.add_argument("--examples", type=int, default=12)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    _APPLY = a.apply
    _ALLOWED = fs.V.load_backlog() if hasattr(fs.V, "load_backlog") else None
    paths = puzzle_paths.puzzle_files()
    total, examples, left = collections.Counter(), [], []
    with multiprocessing.Pool(a.jobs) as pool:
        for i, (s, ex, lf) in enumerate(pool.imap_unordered(do_puzzle, paths, chunksize=64)):
            total.update(s)
            examples += ex
            left += lf
            if i % 5000 == 0:
                print(f"  {i}/{len(paths)} files", file=sys.stderr)
    print(dict(total))
    random.seed(1)
    for x in random.sample(examples, min(a.examples, len(examples))):
        print(f"\n{x['id']} | {x['clue']} | {x['answer']}\n  before: {x['before']}\n  after:  {x['after']}")
    if a.queue:
        for r in sorted(left, key=lambda r: r["id"]):
            print(json.dumps(r))


if __name__ == "__main__":
    main()
