#!/usr/bin/env python3
"""Shout when an annotation run leaves clues it could not solve.

A run that meets a clue it cannot parse does not fail. Validation nulls the
wrong annotation (fetch_puzzle.merge_annotations) and everything downstream
carries on: the puzzle commits, the index marks it `annotated: false`, the site
badges those clues "auto hints", and the only evidence is a ratio buried in a
log nobody opens. That is indistinguishable from a run that solved everything —
which means a model too weak to solve the puzzle looks exactly like a good
night, and the first person to notice is a learner who opened a clue with no
teaching ladder in it.

So the ratio gets checked by something that can shout. Give it the puzzles a run
tried to annotate; it exits non-zero and names the clues if any came back short,
and says which of the two reasons it is: a clue the model could not solve, or a
clue the paper published with no words in it, which is nobody's model failing.

    python3 tools/check_annotation_loss.py 30094 12429
    python3 tools/check_annotation_loss.py            # whatever the tree changed

With no arguments it reads the puzzles modified against HEAD, so a run that
forgets to pass its own ids still gets checked on what it wrote.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_puzzle import ROOT, has_words, read_puzzle_file, resolve_puzzle  # noqa: E402


def changed_puzzles():
    out = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", "puzzles/"],
                         cwd=ROOT, capture_output=True, text=True).stdout
    return [ROOT / line for line in out.split() if line.endswith(".js")
            and not line.endswith("index.js")]


def unannotated(puzzle):
    return [e for e in puzzle["entries"] if e.get("annotation") is None]


def main(argv):
    paths = [resolve_puzzle(a) for a in argv] if argv else changed_puzzles()
    short = []
    for path in paths:
        if not path.exists():
            continue
        puzzle = read_puzzle_file(path)
        missing = unannotated(puzzle)
        total = len(puzzle["entries"])
        # A file with nothing in it was never attempted — that is the backlog,
        # not a loss. A file with SOME annotations is a run that tried and came
        # up short, and that is the case worth waking someone for.
        if missing and len(missing) < total:
            short.append((puzzle["id"], total - len(missing), total, missing))
    for pid, done, total, missing in short:
        # Two very different failures land in the same gap, and treating them
        # alike sent someone to grade a model that had been handed a clue with
        # no words in it. Name which one this is.
        unsolved = [e["id"] for e in missing if has_words(e["clue"])]
        wordless = [e["id"] for e in missing if not has_words(e["clue"])]
        why = []
        if unsolved:
            why.append(f"could not solve {', '.join(unsolved)} — if that keeps "
                       f"happening the model is failing to solve the puzzle, "
                       f"which is a quality problem, not a spend one")
        if wordless:
            why.append(f"{', '.join(wordless)} published with no clue text, so "
                       f"there is nothing to solve — re-fetch, or get the clue "
                       f"from the paper by hand")
        print(f"{pid}: {done}/{total} annotated — {'; '.join(why)}")
    if not short:
        print(f"annotation loss check: {len(paths)} puzzle(s), none left short")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
