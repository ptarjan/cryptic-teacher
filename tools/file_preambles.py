#!/usr/bin/env python3
"""File the setter's instructions a puzzle was filed without.

    python3 tools/file_preambles.py [--dry-run] [ID ...]

tools/data/preambles.json holds, per puzzle id, the `preamble` (and/or the
`themeClue`) to put on its file, with the `source` it was read from. A themed
puzzle filed from a blog post or a page that left the paper's note off cannot
be explained by an annotator, which withdraws it (tools/failed_inputs.py
triage annotate). The note is in the blog's quotation of it
("The preamble told us that ..."), in the paper's printable copy, or in the
puzzle's own theme clue.

The wording is the setter's, as the source prints it: only the source's own
interpolations (a blogger's bracketed gloss, an overprint's doubled word) are
dropped, and `source` says where. A preamble already on the file is replaced
only by a different one here, since this table is the corrected reading.
Writing goes through write_puzzle_file, which drops `awaitsPreamble` once a
preamble is filed and clears the stale annotations of any changed clue text;
a `themeClue` ends the wait the same way (below).

tools/failed_inputs.py releases a withdrawn puzzle when its inputs change, and
`preamble` and `themeClue` are among them, so filing either releases it.
"""
import argparse
import json
import sys

import puzzle_paths
from fetch_puzzle import read_puzzle_file, write_puzzle_file

DATA = puzzle_paths.ROOT / "tools" / "data" / "preambles.json"


def apply(puzzle, row):
    """`puzzle` with `row`'s preamble and themeClue on it, and whether it changed."""
    out = dict(puzzle)
    for key in ("preamble", "themeClue"):
        if row.get(key):
            out[key] = row[key]
    if out.get("preamble") or out.get("themeClue"):
        out.pop("awaitsPreamble", None)
    return out, out != puzzle


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ids", nargs="*", help="only these puzzles (default: every row)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    changed, same, missing = [], [], []
    for pid in args.ids or rows:
        path = puzzle_paths.find(pid)
        if path is None:
            missing.append(pid)
            continue
        puzzle, moved = apply(read_puzzle_file(path), rows[pid])
        if not moved:
            same.append(pid)
            continue
        if not args.dry_run:
            write_puzzle_file(path, puzzle)
        changed.append(pid)
    print(f"{'would change' if args.dry_run else 'changed'} {len(changed)}: {' '.join(changed)}")
    if same:
        print(f"already as filed {len(same)}: {' '.join(same)}")
    if missing:
        print(f"no puzzle file here {len(missing)}: {' '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
