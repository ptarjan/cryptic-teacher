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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shape_queue as Q


def stale_ids(rs, load, bugs=None):
    """The set of row ids in `rs` that are stale; `load(pid)` gives the puzzle or None.
    A row whose clue has a length_bug is stale too (reported, never queued for the
    model); with `bugs` a dict, {row id: message} for those is filled in."""
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
            if clue not in entries:
                continue
            if msg := length_bug(entries[clue]):
                out.add(r["id"])
                if bugs is not None:
                    bugs[r["id"]] = msg
            elif Q.settled(entries[clue], r.get("reason", "")):
                out.add(r["id"])
    return out


def length_bug(entry):
    """A data bug the model cannot fix: the solution's letters do not add up to the
    clue's printed enumeration ("7,4" over PARTING), or a "(11, two words)" count's
    total. Returns the message, else None. A linked answer's leader prints the whole
    group's count, so an entry with a `group` is skipped; a clue with no count at
    all is not a bug (the light's own length is the count)."""
    import enumeration
    if entry.get("group"):
        return None
    clue = entry.get("clue") or {}
    have = len(re.sub(r"[^A-Za-z]", "", entry.get("solution") or ""))
    if clue.get("enumeration"):
        want = sum(enumeration.counts(clue["enumeration"]))
    elif w := enumeration.worded(clue.get("text") or ""):
        want = w[0]
    else:
        return None
    if want != have:
        return f"{entry.get('solution')} has {have} letters, the count says {want}"
    return None


def _load(pid):
    from fetch_puzzle import read_puzzle_file, resolve_puzzle
    try:
        return read_puzzle_file(resolve_puzzle(pid))
    except (SystemExit, OSError, ValueError, KeyError):
        return None


AUTO_EVERY_S = 1800   # the planner prunes at most this often: it loads every queued puzzle


def auto(load=_load, stamp=None, every=AUTO_EVERY_S):
    """What the planner runs: drop the stale rows (stale_ids) and the convention-series shape
    rows (never redone, they only hid good walkthroughs) in one locked rewrite. Returns the
    count dropped, or None when it ran less than `every` seconds ago (mtime of `stamp`)."""
    import os
    import time
    stamp = Path(stamp or os.path.join(os.environ.get("TMPDIR", "/tmp"), "ct-prune-shape-queue.stamp"))
    if stamp.exists() and time.time() - stamp.stat().st_mtime < every:
        return None
    stamp.touch()
    with Q.locked():
        rs = json.loads(Q.PATH.read_text())
        gone = stale_ids(rs, load)
        gone |= {r["id"] for r in rs if Q.exempt(r["id"].partition("#")[0]) and Q.shape_reason(r.get("reason", ""))}
        if gone:
            Q.write(Q.dump([r for r in rs if r["id"] not in gone]))
    return len(gone)


def main(argv):
    write = "--write" in argv
    with Q.locked():
        rs = json.loads(Q.PATH.read_text())
        bugs = {}
        gone = stale_ids(rs, _load, bugs)
        for rid, msg in sorted(bugs.items()):
            print(f"data bug {rid}: {msg}")
        per, total = collections.Counter(), collections.Counter()
        for r in rs:
            cls = r.get("reason", "").split(":")[0]
            total[cls] += 1
            per[cls] += r["id"] in gone
        for cls, n in total.most_common():
            print(f"{cls:32} {per[cls]:5} of {n}")
        print(f"stale {len(gone)} of {len(rs)}")
        capped = Q.exhausted()
        print(f"{len(capped)} rows tried {Q.MAX_TRIES} times and still flagged (hidden, not redone): "
              + " ".join(capped[:40]) + (" ..." if len(capped) > 40 else ""))
        if write:
            Q.write(Q.dump([r for r in rs if r["id"] not in gone]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
