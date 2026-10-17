#!/usr/bin/env python3
"""Blank just the clues whose annotations fail validation, so the rest ship.

    python3 tools/drop_failed_clues.py ID

The burn used to throw out a whole puzzle's hints when one clue still failed
after its fix run (tools/puzzle_worker.sh _worker_finish). Here every error
that leads with its clues ("15A: ...", "3D,5A: ...", see
reopen_answers.named_clues) costs those clues their annotation and nothing
else; the file is then checked again, up to three rounds, since a hint can fail
only once its neighbour is gone. A clue left without a hint is due again
(annotate_check.to_write), so the planner sends it later as a scoped tail.

Writes the file only when what is left holds a hint and every remaining error
is a clue left blank (the deploy's rules queue those, worker_only_blanks); on
any other failure (an error that names no clue, a puzzle-level one) the file
is untouched and the exit is 1. Prints the ids dropped; exit 0.
"""
import re
import sys

import provenance
import puzzle_integrity
import validate_annotations
from fetch_puzzle import read_puzzle_file, resolve_puzzle, write_puzzle_file
from reopen_answers import hint_holders, named_clues
import puzzle_schema

BLANK = re.compile(r"[0-9]+[AD](,[0-9]+[AD])*: no annotation\.")
ROUNDS = 3


def drop(puzzle, named):
    """Remove the annotation from each clue in `named` (a light's group and its
    alsoLeads and off-grid clues go with it), in place."""
    for cid, item in hint_holders(puzzle):
        if cid.split("/")[0] in named:
            item.pop("annotation", None)


def dropped_clues(path, puzzle):
    """(puzzle, ids) with the failing clues blanked, or None when the errors
    are not all clues' own or nothing would be left to ship."""
    out, gone = puzzle_schema.order(puzzle), set()
    for _ in range(ROUNDS):
        errors = validate_annotations.run_errors(path, out)
        failing = [e for e in errors if not BLANK.match(e)]
        if not failing:
            return (out, gone) if gone and provenance.has_hints(out) else None
        named = named_clues(failing, out)
        if not named or not provenance.has_hints(out):
            return None
        drop(out, named)
        gone |= named
    return None


def main(argv):
    if len(argv) != 1:
        print(__doc__.strip())
        return 2
    path = resolve_puzzle(argv[0])
    got = dropped_clues(path, read_puzzle_file(path))
    if got is None:
        return 1
    puzzle, gone = got
    try:
        write_puzzle_file(path, puzzle)
    except puzzle_integrity.RefusedWrite:
        return 1
    print(" ".join(sorted(gone)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
