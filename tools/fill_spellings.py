#!/usr/bin/env python3
"""Write the `spelling` that tools/lesson_checks.py flags as unsaid (spelling.unsaid),
for the clues where it is unambiguous, so a model is not asked for a field we know.

    python3 tools/fill_spellings.py [--examples N]   # dry run over puzzles/: counts and samples
    python3 tools/fill_spellings.py --write          # write the puzzles and shrink the allowance

A clue is filled when its spelling is single and fits: the lexicon
(tools/data/lexicons/spellings.json) and the annotation's own prose agree (or only one
says anything), and the spelling has as many words as the printed enumeration counts.
Anything else (two different spellings, a word count that does not fit) is left to the
model. A puzzle is written only when tools/validate_annotations.py finds no error it
did not already have; its allowance for spelling.unsaid in tools/annotation_backlog.json
drops to the clues still flagged. What it cannot fill stays a warning: the burn never
queues this field for a model (spelling is display only; the grid holds letters).
"""
import argparse
import json
import multiprocessing
import os
import random
import re
import sys
from pathlib import Path

import lesson_checks as L
import puzzle_schema
import validate_annotations as V

ROOT = Path(__file__).resolve().parent.parent
FIELD = "spelling.unsaid"


def _words(text):
    return [w for w in re.split(r"[\s\-,]+", text) if w]


def fits(said, enumeration):
    """Whether `said` has the words the printed enumeration ("3,7,4", "4-3") counts."""
    if not re.fullmatch(r"[\d,\-\s]+", enumeration or ""):
        return True
    return len(_words(said)) == len(re.findall(r"\d+", enumeration))


def fillable(ann, held):
    """The one spelling to write for a clue the rule flags, or None when there is
    none to write (not flagged) or no single one (ambiguous)."""
    if len(held.get("group") or []) > 1:
        return None
    enumeration = (held.get("clue") or {}).get("enumeration")
    answer = held.get("solution") or ""
    if not L.spelling_unsaid(ann, answer, enumeration):
        return None
    ans = L.letters(answer)
    known = L.known_spellings().get(ans)
    found = L.prose_spellings(ann, answer, enumeration)
    options = {s.replace("’", "'").upper() for s in ([known] if known else []) + found}
    if len(options) != 1:
        return None
    said = options.pop()
    return said if fits(said, enumeration) else None


def fill_puzzle(puzzle):
    """Fill `puzzle`. Returns (the puzzle with the spellings in schema order, [(clue, spelling,
    answer)], clues flagged before, clues flagged after, whether the fill made an error), the
    last three read off the validator."""
    _, errors_before, warnings = V.validate_puzzle(puzzle, corpus=True)
    before = V.count_backlog(warnings)[FIELD]
    if not before:
        return puzzle, [], 0, 0, False
    done = []
    for _, held, ann in puzzle_schema.annotations(puzzle):
        said = fillable(ann, held)
        if said:
            ann["spelling"] = said
            done.append((f"{held.get('number')}{str(held.get('direction') or '')[:1]}", said, held.get("solution")))
    if not done:
        return puzzle, [], before, before, False
    puzzle = puzzle_schema.order(puzzle)
    _, errors_after, warnings = V.validate_puzzle(puzzle, corpus=True)
    return puzzle, done, before, V.count_backlog(warnings)[FIELD], len(errors_after) > len(errors_before)


def _job(args):
    path, write = args
    puzzle = V.read_puzzle_file(Path(path))
    puzzle, done, before, after, broke = fill_puzzle(puzzle)
    if not before:
        return path, [], 0, 0, False
    if broke:
        return path, [], before, before, True
    if done and write:
        part = Path(path).with_name(f".{Path(path).name}.part")
        part.write_text(json.dumps(puzzle, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(part, path)
    return path, done, before, after, False


def files():
    return sorted(p for p in (ROOT / "puzzles").glob("**/*.json") if not p.name.startswith("."))


def flagged_files():
    """The puzzle files the allowance lists for the field."""
    listed = set(json.loads(V.BACKLOG_PATH.read_text()).get(FIELD, {}))
    return [p for p in files() if p.stem in listed]


def run(paths, write):
    with multiprocessing.Pool(int(os.environ.get("CT_JOBS") or 2)) as pool:  # few workers: the host is shared
        return list(pool.imap_unordered(_job, [(str(p), write) for p in paths], 16))


def shrink_allowance(left):
    """left: {puzzle: clues still flagged}. The field's list only ever tightens."""
    data = json.loads(V.BACKLOG_PATH.read_text())
    had = data.get(FIELD, {})
    new = {k: min(n, had.get(k, n)) for k, n in left.items() if n}
    new.update({k: n for k, n in had.items() if k not in left})
    data[FIELD] = dict(sorted(new.items(), key=V._sort_key))
    V.store_backlog(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="write the puzzles and shrink the allowance")
    ap.add_argument("--examples", type=int, default=10)
    a = ap.parse_args()
    results = run(flagged_files(), a.write)
    flagged = sum(r[2] for r in results)
    filled = sum(len(r[1]) for r in results)
    remain = sum(r[3] for r in results)
    broke = [r[0] for r in results if r[4]]
    print(f"{flagged} flagged clues in {sum(1 for r in results if r[2])} puzzles; "
          f"{filled} {'filled' if a.write else 'fillable'} in {sum(1 for r in results if r[1])} puzzles; "
          f"{remain} left for the model in {sum(1 for r in results if r[3])} puzzles; "
          f"{len(broke)} puzzles would gain an error and are left alone")
    rows = [(Path(p).stem, c) for p, d, *_ in results for c in d]
    for pid, (clue, said, answer) in random.Random(1).sample(rows, min(a.examples, len(rows))):
        print(f"  {pid} {clue}: {answer} -> {said}")
    if a.write:
        shrink_allowance({Path(p).stem: after for p, _, _, after, _ in results})
    return 0


if __name__ == "__main__":
    sys.exit(main())
