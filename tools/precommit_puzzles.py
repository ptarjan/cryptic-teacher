#!/usr/bin/env python3
"""The pre-commit hook's two checks on the puzzle files a commit stages, run in
one Python process: puzzle_integrity's QUOTE check and validate_annotations
--deploy.

    python3 tools/precommit_puzzles.py FILE...

Prints each QUOTE flag and each ERROR/FAIL line of the deploy check on stderr,
and exits 1 if either check fails. The two used to start Python twice and
import the same modules twice (fetch_puzzle and the rest, most of each run),
on every commit the OCR pass makes; one start does both for about half the
cost. .githooks/pre-commit calls it only when the commit stages a puzzle file.
"""
import contextlib
import io
import sys

import puzzle_integrity
import validate_annotations


def main(paths):
    if not paths:
        return 0
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        quotes = puzzle_integrity.main(["--quotes", *paths])
    sys.stderr.write(out.getvalue())
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        deploy = validate_annotations.main(["--deploy", *paths])
    if deploy:
        sys.stderr.writelines(line for line in out.getvalue().splitlines(True)
                              if "ERROR" in line or "FAIL" in line)
    return 1 if quotes or deploy else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
