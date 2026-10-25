#!/usr/bin/env python3
"""Flatten the charades filed under anagrams into the anagram's parts, corpus-wide.

    python3 tools/flatten_anagram_fodder.py puzzles/              # count, write nothing
    python3 tools/flatten_anagram_fodder.py puzzles/ --write      # rewrite in place
    python3 tools/flatten_anagram_fodder.py puzzles/ --commit     # rewrite, then one commit

An anagram's fodder is one pool of letters, so its pieces are the anagram's
own parts: `ana<Dreadfully>([slay] + [a] + [cut])` stores slay, a and cut
under the anagram. Before an anagram could hold several parts, every
multi-piece fodder was filed as one charade under it, which labels a pool as
pieces joined in order (sundaytel-2671 1A, CASUALTY). This rewrites each such
charade as the anagram's parts, nested ones too, in clue order (a piece with
no clue words keeps the order filed). It changes no letters, no block and no
type: annotation.view() reads the same fodder either way (the tiles are dealt
in clue order already), so nothing is due to be annotated again.

A charade under an anagram is left as it stands when it has an indicator of its
own (a word the annotator read as ordering the pieces, or an indicator that
belongs on another node: a reading for each clue, not a mechanical one), or
when it or the anagram is unchecked (a step taken as filed: an unchecked
anagram over one charade is how a setter's slip lists its fodder, and one over
several parts lists none, annotation._assembly). Those are written to
tools/annotation_backlog.json as the wordplay.anagramCharade allowance, which
validate_annotations holds every puzzle to from then on, so no new one can be
filed. A schema-migration commit, exempt from one commit per puzzle (as
f59e109ad6). Each file is rewritten whole (a .part renamed over it) in the
shape it was read, so a kill loses nothing and the same command resumes: a
flattened file has nothing left to flatten.
"""
import argparse
import collections
import json
import os
import subprocess
import sys

import puzzle_schema
import validate_annotations

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIELD = "wordplay.anagramCharade"


def flattenable(node):
    """A charade under an anagram that is only fodder in pieces: checked, with
    no indicator of its own and no letters taken as filed."""
    return (isinstance(node, dict) and node.get("op") == "charade" and not node.get("unchecked")
            and not node.get("indicators") and "gives" not in node)


def _pieces(node):
    return [q for p in node.get("parts") or [] for q in (_pieces(p) if flattenable(p) else [p])]


def _first_at(node):
    ats, stack = [], [node]
    while stack:
        n = stack.pop()
        if "at" in n:
            ats.append(n["at"])
        stack += [p for p in n.get("parts") or [] if isinstance(p, dict)]
    return min(ats) if ats else None


def flatten_tree(node):
    """Flatten every charade-only fodder under an anagram in `node`, in place:
    how many charades went."""
    if not isinstance(node, dict):
        return 0
    n = 0
    parts = node.get("parts") or []
    if node.get("op") == "anagram" and not node.get("unchecked") and any(flattenable(p) for p in parts):
        n += sum(_count(p) for p in parts if flattenable(p))
        new = [q for p in parts for q in (_pieces(p) if flattenable(p) else [p])]
        ats = [_first_at(p) for p in new]
        if None not in ats:
            new = [p for _, p in sorted(zip(ats, new), key=lambda it: it[0])]
        node["parts"] = new
    for p in node.get("parts") or []:
        n += flatten_tree(p)
    return n


def _count(charade):
    """The charade itself and the flattenable ones nested in it."""
    return 1 + sum(_count(p) for p in charade.get("parts") or [] if flattenable(p))


def flatten_puzzle(puzzle):
    """(charades flattened, charades left under an anagram), in place."""
    done = left = 0
    for _, _, ann in puzzle_schema.annotations(puzzle):
        done += flatten_tree(ann.get("wordplay"))
        left += validate_annotations.anagram_charades(ann.get("wordplay"))
    return done, left


def flatten_file(path, write):
    with open(path, encoding="utf-8") as fh:
        puzzle = json.load(fh)
    done, left = flatten_puzzle(puzzle)
    if done and write:
        part = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.part")
        with open(part, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n")
        os.replace(part, path)
    return done, left


def write_allowance(left):
    """Record `left` ({puzzle: charades still under an anagram}) as the
    FIELD allowance: the smaller of it and any allowance already there, so a
    re-run only ever tightens it. Every other field is left as it is."""
    path = validate_annotations.BACKLOG_PATH
    data = json.loads(path.read_text())
    had = data.get(FIELD)
    rows = {k: min(n, had.get(k, 0)) if had is not None else n for k, n in left.items()}
    out = {}
    for k, v in data.items():
        if k != FIELD:
            out[k] = v
        if k == "wordplay.unchecked":
            out[FIELD] = None
    out[FIELD] = {k: n for k, n in sorted(rows.items(), key=validate_annotations._sort_key) if n}
    validate_annotations.store_backlog(out, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="the puzzles/ folder")
    ap.add_argument("--write", action="store_true",
                    help="rewrite the files in place and record the allowance")
    ap.add_argument("--commit", action="store_true", help="--write, then make the one migration commit")
    a = ap.parse_args()
    write = a.write or a.commit
    files = sorted(os.path.join(d, f) for d, _, fs in os.walk(a.root) for f in fs
                   if f.endswith(".json") and not f.startswith("."))
    done = puzzles = 0
    left = collections.Counter()
    for i, path in enumerate(files, 1):
        n, k = flatten_file(path, write)
        if n:
            puzzles += 1
            done += n
        if k:
            left[os.path.basename(path)[:-len(".json")]] = k
        if i % 5000 == 0:
            print(f"flatten: {i}/{len(files)} files, {done} charades", file=sys.stderr, flush=True)
    subject = f"Flatten anagram fodder: {done} charades under anagrams in {puzzles} puzzles"
    print(subject)
    print(f"left under an anagram (an indicator of their own, or an unchecked step): "
          f"{sum(left.values())} in {len(left)} puzzles")
    if write:
        write_allowance(left)
    if not a.commit or not done:
        return
    body = (f"{subject}\n\nAn anagram's fodder is one pool of letters, so its pieces are the "
            f"anagram's own parts, in clue order: tools/flatten_anagram_fodder.py over "
            f"{len(files)} files rewrote each indicator-less, checked charade filed under an "
            f"anagram as the anagram's parts. No letters, blocks or types change. "
            f"{sum(left.values())} charades in {len(left)} puzzles stay as they are (an indicator "
            f"of their own, or under an unchecked step) and are the {FIELD} allowance in "
            f"tools/annotation_backlog.json, which validate_annotations now holds every puzzle "
            f"to. A schema migration, exempt from one commit per puzzle (as f59e109ad6). The old "
            f"text is in this commit's parent.\n")
    trailer = subprocess.run([sys.executable, os.path.join(REPO, "tools", "provenance.py"), "trailer"],
                             capture_output=True, text=True).stdout.strip()
    if trailer:
        body += "\n" + trailer + "\n"
    subprocess.run(["git", "-C", REPO, "add", "--", os.path.relpath(os.path.abspath(a.root), REPO),
                    os.path.relpath(str(validate_annotations.BACKLOG_PATH), REPO)], check=True)
    subprocess.run(["git", "-C", REPO, "commit", "-q", "-F", "-"], input=body, text=True, check=True)
    print(subprocess.run(["git", "-C", REPO, "log", "-1", "--format=committed: %h %s"],
                         capture_output=True, text=True).stdout.strip())


if __name__ == "__main__":
    main()
