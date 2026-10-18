#!/usr/bin/env python3
"""Drop the rows of tools/data/shape_reannotate.json that nothing flags now.

    python3 tools/prune_shape_queue.py            # report per reason class
    python3 tools/prune_shape_queue.py --write    # and rewrite the list

A row is stale when every detector its reason names is known and none fires on
the clue's tree as it stands (shape_queue.settled): another sweep fixed the clue
without dequeueing it, or the detector was tightened after the row was queued.
A stale row costs a model run (~4k tokens a clue) for nothing. Rows with a
reason only the model can settle (model-fixable, walkthrough, ...), clues
with no tree, and rows whose puzzle will not load are kept.
shape_queue.flagged() applies the same test, so a run skips a stale row even
before this prunes it. Loads only the queued puzzles."""
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shape_queue as Q


def stale_ids(rs, load):
    """The set of row ids in `rs` that are stale; `load(pid)` gives the puzzle or None."""
    by_pid = collections.defaultdict(list)
    for r in rs:
        pid, _, clue = r["id"].partition("#")
        by_pid[pid].append((clue, r))
    out = set()
    for pid, items in by_pid.items():
        puzzle = load(pid)
        if not puzzle:
            continue
        entries = {Q.clue_key(e): e for e in puzzle.get("entries") or []}
        for clue, r in items:
            if clue in entries and Q.settled(entries[clue], r.get("reason", "")):
                out.add(r["id"])
    return out


def _load(pid):
    from fetch_puzzle import read_puzzle_file, resolve_puzzle
    try:
        return read_puzzle_file(resolve_puzzle(pid))
    except (SystemExit, OSError, ValueError, KeyError):
        return None


def main(argv):
    write = "--write" in argv
    with Q.locked():
        rs = json.loads(Q.PATH.read_text())
        gone = stale_ids(rs, _load)
        per, total = collections.Counter(), collections.Counter()
        for r in rs:
            cls = r.get("reason", "").split(":")[0]
            total[cls] += 1
            per[cls] += r["id"] in gone
        for cls, n in total.most_common():
            print(f"{cls:32} {per[cls]:5} of {n}")
        print(f"stale {len(gone)} of {len(rs)}")
        if write:
            Q.write(Q.dump([r for r in rs if r["id"] not in gone]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
