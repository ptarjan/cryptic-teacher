#!/usr/bin/env python3
"""Queue every clue that still carries an `unchecked` wordplay step for the burn's redo.

    python3 tools/queue_unchecked.py            # dry run: counts per op
    python3 tools/queue_unchecked.py --write    # add the rows to tools/data/shape_reannotate.json

Run after tools/clear_unchecked.py --write: what that sweep could not verify (the step
does not evaluate to its answer without the flag) is only the model's to redo. Each clue
not already listed gets {"id": "<puzzle>#<clue>", "reason": "unchecked_step: <op>"}, <op>
the first unchecked node's op (leaf for a bare leaf). shape_queue.settled() reads the
reason: the row stays while any node carries the flag and goes stale when the flag is gone.
"""
import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import clear_unchecked as C
import puzzle_schema
import shape_queue as Q
import validate_annotations as V

REASON = "unchecked_step"


def first_unchecked(tree):
    return next((n.get("op") or "leaf" for n in V._walk(tree) if n.get("unchecked")), None)


def rows_for(path, listed):
    """[(row, op)] for the puzzle's flagged clues not yet listed."""
    puzzle = V.read_puzzle_file(path)
    out = []
    for _, held, ann in puzzle_schema.annotations(puzzle):
        wp = ann.get("wordplay")
        if not isinstance(wp, dict) or not C.flagged(wp):
            continue
        cid = f"{puzzle['id']}#{Q.clue_key(held)}"
        if cid not in listed:
            op = first_unchecked(wp)
            out.append(({"id": cid, "reason": f"{REASON}: {op}"}, op))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    listed = {r["id"] for r in Q.rows()}
    added, per_op = [], collections.Counter()
    for path in C.files():
        if '"unchecked"' not in path.read_text(encoding="utf-8"):
            continue
        for row, op in rows_for(path, listed):
            added.append(row)
            per_op[op] += 1
    print(f"{len(added)} clues to queue: {dict(per_op.most_common())}")
    if a.write and added:
        with Q.locked():
            Q.write(Q.dump(json.loads(Q.PATH.read_text()) + added))
    return 0


if __name__ == "__main__":
    sys.exit(main())
