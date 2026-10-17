#!/usr/bin/env python3
"""Which tail puzzles one annotate session takes together: a bag.

    ids | python3 tools/clue_bag.py RUNS_DIR LEADER [RESUME_DIR]

A run pays ~27-30k tokens before its first clue, and a puzzle missing five clues
or fewer (a tail) has ~3.2k of work in it: measured per clue, 28.5k alone and
3.5-4k at 21-32 clues in a session, with the same quality. So the burn
(tools/prereset_backfill.sh pool_launch) asks here, with the queue after LEADER
on stdin, for the puzzles to annotate in LEADER's session. Prints the bag's ids,
LEADER first, one per line; LEADER alone when it is not bagged.

A bag is LEADER plus the next tails in queue order until the clues they have
due add up to BAG_TARGET (the last one added may pass it; there is no hard
cap). Whole puzzles only, so a linked group ("see 5") is never split: a puzzle's
due clues are what annotate_check.to_write lists, groups whole.

A puzzle is bagged only when it is partly hinted (or hinted with a few clues on the shape redo list) with at most MAX_DUE clues due,
keyed (every answer present, every clue readable), and carries no preamble or
theme clue: a preamble describes a device that runs across the clues (misprints,
extra letters, unclued entries), which a session must see whole. A plain barred
grid or a jumbo has none and may be bagged. Not by setter or series. One a
conversation is already paid for (a sid file in RUNS_DIR, a resume note in
RESUME_DIR) or with nothing due is left to the queue.
"""
import sys
from pathlib import Path

BAG_TARGET = 30
MAX_DUE = 5
SCAN = 3000  # queue entries looked at past the leader; tails sit at its head


def due_clues(puzzle):
    """How many clues a run on this puzzle writes, when it is a tail worth
    bagging; None when it is not. Its preamble and theme clue keep it whole."""
    import annotate_check
    if puzzle.get("preamble") or puzzle.get("themeClue") or puzzle.get("cluesUnplaced"):
        return None
    if not all(e.get("solution") for e in puzzle["entries"]):
        return None
    due = annotate_check.to_write(puzzle, None)
    if not due or len(due) > MAX_DUE:
        return None
    return len(due)


# Re-annotation reasons code fixes without the model (tools/fill_spellings.py,
# tools/prefill_hidden.py): they never make a clue due.
CODE_FIXED = ("spelling.unsaid", "hidden")


def redo_due(pid):
    """How many clues of pid are on the shape re-annotation list
    (tools/shape_queue.py: the per-clue redo, what annotate_check.to_write adds
    for a hinted puzzle), not counting reasons code fixes. Cheap: one cached dict."""
    import shape_queue
    return sum(1 for why in shape_queue.pending().get(pid, {}).values()
               if not str(why).startswith(CODE_FIXED))


def row_is_tail(row, redo=True):
    """Whether an index row is a tail by the index alone: 1..MAX_DUE clues due
    (missing an annotation, plus those on the shape redo list), answers present,
    no preamble awaited. The planner puts these at the head of the Annotate
    queue so they are bagged first; the file check in due_clues still decides
    at launch. redo=False counts only the missing ones: the planner's head-of-
    queue stage uses that, so redo tails ride in bags without outranking the
    un-hinted puzzles; they bag from wherever the shape tier interleaves them."""
    if not row:
        return False
    if not 1 <= row.get("unannotated", 0) + (redo_due(row.get("id")) if redo else 0) <= MAX_DUE:
        return False
    return not (row.get("clues") or row.get("awaitsPreamble")) and bool(row.get("hasSolutions"))


def tail_due(pid, row, runs, resume_dir):
    """due_clues for queued id pid, or None when it is not bagged: not a tail
    on the index, a run already holds it, or its file will not read."""
    if not row_is_tail(row):
        return None
    if (runs / f"{pid}.sid").exists() or (resume_dir / f"ct-prereset-{pid}.resume").exists():
        return None
    from fetch_puzzle import read_puzzle_file, resolve_puzzle
    try:
        return due_clues(read_puzzle_file(resolve_puzzle(pid)))
    except (SystemExit, OSError, ValueError, KeyError):
        return None


def bag_of(leader, queue, rows, runs, resume_dir, target=BAG_TARGET, due=tail_due):
    """[leader, *members]: the leader and the tails after it in `queue` (ids),
    `rows` the index rows by id. Just [leader] unless the leader is a tail
    itself, and when too few others are found."""
    total = due(leader, rows.get(leader), runs, resume_dir)
    if total is None:
        return [leader]
    bag, seen = [leader], {leader}
    for pid in queue[:SCAN]:
        if total >= target:
            break
        if pid in seen:
            continue
        seen.add(pid)
        n = due(pid, rows.get(pid), runs, resume_dir)
        if n is not None:
            bag.append(pid)
            total += n
    return bag


def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    import prereset_plan
    rows = {r["id"]: r for r in prereset_plan.index_rows()}
    queue = sys.stdin.read().split()
    resume_dir = Path(argv[2] if len(argv) == 3 else "/tmp")
    print("\n".join(bag_of(argv[1], queue, rows, Path(argv[0]), resume_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
