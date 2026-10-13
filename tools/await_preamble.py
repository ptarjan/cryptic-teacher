#!/usr/bin/env python3
"""Hold back a puzzle that cannot be explained without the preamble we lack.

    python3 tools/await_preamble.py <ID> --which   # the entries a run left to the preamble, one line
    python3 tools/await_preamble.py <ID>           # mark the puzzle awaitsPreamble

A themed puzzle filed from a blog post often lacks the preamble the paper
printed ("five detectives and their creators are undefined"): the post
paraphrases it at most. Its annotator marks those answers definedByPreamble,
or gives a block the letters the preamble supplies with no clue words, and the
validator refuses both on a puzzle with no preamble. Another run fails
the same way, and no change to the clues mends it, so the verdict is kept on
the puzzle: `awaitsPreamble`. puzzle_integrity.awaits_preamble reads it, the
index row carries it, and both annotation pickers leave the puzzle out until a
preamble is filed, when write_puzzle_file drops the flag.

--which reads the file as the run left it, before the burn discards it. It
lists the entries only when the missing preamble is the run's sole failure:
the run's file, given a stand-in preamble, validates. Otherwise it prints
nothing, and the run is parked like any other.
"""
import copy
import sys

import annotation
import puzzle_paths
import puzzle_schema
import validate_annotations
from fetch_puzzle import read_puzzle_file, write_puzzle_file

STAND_IN = "The paper's preamble, which we do not hold."


def left_to_preamble(puzzle):
    """The tags of the entries whose annotation leans on the preamble: it
    defines them, or a block takes letters no clue word gives (Genius 135's
    body parts, which the preamble says the wordplay leaves out). Read off
    annotation.view_puzzle(), which derives the file's blocks."""
    return [f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
            for e in annotation.view_puzzle(puzzle).get("entries") or []
            if (e.get("annotation") or {}).get("definedByPreamble") is True
            or any(b.get("gives") and not b.get("clueFragment")
                   for b in (e.get("annotation") or {}).get("blocks") or [])]


def which(path, puzzle):
    """The entries that make the run's file wait for its preamble, or [] when
    the file fails for anything else too, or has a preamble already."""
    tags = left_to_preamble(puzzle)
    if puzzle.get("preamble") or not tags:
        return []
    given = puzzle_schema.order(dict(copy.deepcopy(puzzle), preamble=STAND_IN))
    return [] if validate_annotations.run_errors(path, given) else tags


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv[:1] in (["-h"], ["--help"]) else 2
    path = puzzle_paths.find(argv[0])
    if path is None:
        print(f"await_preamble: no puzzle file for {argv[0]}", file=sys.stderr)
        return 1
    puzzle = read_puzzle_file(path)
    if argv[1:] == ["--which"]:
        print(" ".join(which(path, puzzle)))
        return 0
    if puzzle.get("preamble"):
        print(f"await_preamble: {argv[0]} holds a preamble already", file=sys.stderr)
        return 1
    puzzle["awaitsPreamble"] = True
    write_puzzle_file(path, puzzle)
    print(f"await_preamble: {argv[0]} awaits its preamble")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
