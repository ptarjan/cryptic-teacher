#!/usr/bin/env python3
"""Which tail puzzles one annotate session takes together: a bag.

    ids | python3 tools/clue_bag.py [--due] [--any-listed | --blog | --field] [--spread SLOTS] RUNS_DIR LEADER [RESUME_DIR]

A run pays ~25-30k tokens before its first clue, and a puzzle missing ten clues
or fewer (a tail) has ~3.4k of work in it: measured per clue, 28.5k alone and
3.5-4k at 21-32 clues in a session, with the same quality. So the burn
(tools/prereset_backfill.sh pool_launch) asks here, with the queue after LEADER
on stdin, for the puzzles to annotate in LEADER's session. Prints the bag's ids,
LEADER first, one per line; LEADER alone when it is not bagged. With --due each
line is "<id> <clues due>", for the burn's log line naming the bag's size.

The shape-rule backfills (Backfill wordplay.<rule>) bag the same way: their
puzzles are hinted with a clue or two on the shape redo list, which is a tail,
and a bag of them pays the session's fixed cost once instead of per clue.
With --any-listed the candidates after the queue are every puzzle on the shape
redo list, whatever its rule: a bag's view lists each puzzle's flagged clues of
every rule anyway, and most rules' queues hold too few clues to fill one (11-03:
26 of the 33 rules left under 30 clues; 50 sessions per rule, 29 across them).

The blog re-check ("Re-check against its blog:", tools/prereset_backfill.sh section 3)
bags the same way with --blog: a puzzle's clues due are the ones tools/blog_compare.py
--due flags for it (the `due` of tools/data/blog_compare.json, 1-3 clues a puzzle: 11-03
measured ~7.3k tokens a clue run alone, one session each). Its session is the same bag as
any other: one view (tools/annotate_bag.py, with the blog's warnings and our hints beside
them), one write, one check; a hint that stands is filed under "_keep".

A field backfill ("Backfill indicators.note", explanation.surface, features, blocks.note,
explanation.definitionFit) bags the same way with --field, the field named in CT_BACKFILL_FIELD: a
puzzle's clues due are the ones annotate_check.field_due finds the validator warning lack it. Those
fields were a session per puzzle (a whole puzzle's worth of clues for most, 1-10 for a few); a
puzzle with more than MAX_DUE clues due is its own bag, through the same view, write and check.

A bag is LEADER plus the next tails in queue order until the clues they have
due add up to BAG_TARGET (the last one added may pass it; there is no hard
cap: with MAX_DUE 10 a bag runs 30 to 39 clues). MAX_DUE is 10 because, over the
shape redo queue (34,292 clues in 11,680 puzzles), cutoff 5 costs ~172M tokens
with 1,498 puzzles solo, 10 costs ~147M with 191 solo, 15 only ~145M, and at 10
every bag still mixes at least three puzzles. With --spread SLOTS (the burn's
free runs) the target drops to the tails' clues left over SLOTS, never below
MIN_TARGET, so the last of a list fills the width instead of one slot. Whole puzzles only, so a linked group ("see 5") is never split: a puzzle's
due clues are what annotate_check.to_write lists, groups whole.

A puzzle is bagged only when it is partly hinted (or hinted with a few clues on the shape redo list) with at most MAX_DUE clues due,
keyed (every answer present, every clue readable), and carries no preamble or
theme clue: a preamble describes a device that runs across the clues (misprints,
extra letters, unclued entries), which a session must see whole. A plain barred
grid or a jumbo has none and may be bagged. Not by setter or series. One a
conversation is already paid for (a sid file in RUNS_DIR, a resume note in
RESUME_DIR) or with nothing due is left to the queue.
"""
import json
import sys
from pathlib import Path

BAG_TARGET = 30
MAX_DUE = 10
TOOLS = Path(__file__).resolve().parent
MIN_TARGET = 6  # --spread never shrinks a bag below this many clues
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


def shape_clues(pid):
    """How many clues of pid a shape-rule run would redo: annotate_check.shape_due (none when it
    awaits its preamble, none for a clue with no published text), less the reasons code fixes.
    None when its file will not read."""
    import annotate_check
    import shape_queue
    from fetch_puzzle import read_puzzle_file, resolve_puzzle
    try:
        puzzle = read_puzzle_file(resolve_puzzle(pid))
        flagged = shape_queue.flagged(puzzle)
        return sum(1 for cid in annotate_check.shape_due(puzzle)
                   if not str(flagged.get(cid, "")).startswith(CODE_FIXED))
    except (SystemExit, OSError, ValueError, KeyError):
        return None


def ledger_skipped():
    """Ids the annotate ledger (tools/failed_inputs.py) holds out on the puzzle as it is now.
    A bag's members come from a queue cut hours or days before (the leader's own stdin) and from
    the shape list, which never read the ledger: a puzzle that failed since, or was never cut
    against it, was bagged again for nothing (11-05: cryptic-22081, unchanged since 10-19, failed
    and was bagged again). It leaves the bag when its record holds, and returns when the puzzle changes."""
    import failed_inputs
    return set(failed_inputs.skipped(failed_inputs.load(), "annotate"))


def pickable_ids(rows=None):
    """shape_queue.puzzle_ids() less the puzzles the index marks awaitsPreamble and those the
    annotate ledger holds out: the shape-rule pickers' list, as the annotate picker
    (prereset_plan.backlog) leaves those out."""
    import shape_queue
    if rows is None:
        import prereset_plan
        rows = {r["id"]: r for r in prereset_plan.index_rows()}
    held = ledger_skipped()
    return {pid for pid in shape_queue.puzzle_ids()
            if pid not in held and not (rows.get(pid) or {}).get("awaitsPreamble")}


def row_is_tail(row, redo=True):
    """Whether an index row is a tail by the index alone: 1..MAX_DUE clues due
    (missing an annotation, plus those on the shape redo list), answers present,
    no preamble awaited. The planner puts these at the head of the Annotate
    queue so they are bagged first; the file check in due_clues still decides
    at launch. The planner's tails stage uses the default (redo=True), so
    flagged-clue redo tails go ahead of the nearly-done/small-series stage.
    redo=False counts only the missing ones."""
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


def bag_of(leader, queue, rows, runs, resume_dir, target=BAG_TARGET, due=tail_due, counts=None):
    """[leader, *members]: the leader and the tails after it in `queue` (ids),
    `rows` the index rows by id. Just [leader] unless the leader is a tail
    itself, and when too few others are found. `counts`, a dict, is filled with
    each bagged id's clues due."""
    counts = {} if counts is None else counts
    total = due(leader, rows.get(leader), runs, resume_dir)
    if total is None:
        return [leader]
    counts[leader] = total
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
            counts[pid] = n
            total += n
    return bag


def with_listed(queue, listed, held=()):
    """`queue`, then the ids of `listed` it lacks, in id order (--any-listed), less
    `held`: the puzzles already in a bag in flight. Those left the queue when their
    bag formed, but the list still holds them until their run is committed."""
    seen = set(queue) | set(held)
    return list(queue) + sorted(p for p in listed if p not in seen)


def held_in_bags(runs):
    """Every id the bag files in RUNS_DIR name: the bags in flight."""
    return {line.strip() for b in Path(runs).glob("*.bag") for line in b.read_text().splitlines() if line.strip()}


def est_due(pid, row):
    """The clues a candidate has due by the index and the shape list alone (no
    file read), 0 when it is no tail: what spread_target adds up."""
    if not row_is_tail(row):
        return 0
    return row.get("unannotated", 0) + redo_due(pid)


def spread_target(leader, queue, rows, slots, target=BAG_TARGET, least=MIN_TARGET):
    """The bag target with `slots` free runs to fill: the tails' clues left
    (leader and queue[:SCAN]) shared over the slots, between `least` and `target`.
    A full bag is cheapest per clue, but one bag of the last 30 clues holds one
    slot of 14 while the rest idle; with the week's quota to spend, width wins."""
    if slots <= 1:
        return target
    total = est_due(leader, rows.get(leader)) + sum(est_due(p, rows.get(p)) for p in queue[:SCAN])
    return max(least, min(target, -(-total // slots)))


def blog_due():
    """{puzzle id: [entry id, ...]} the blog re-check has due (blog_compare.py --due's
    puzzles): the clues whose definition, type or blocks disagree with the blog and
    that nobody has filed as kept. Read from the report the phase began with."""
    try:  # not blog_compare.OUT: importing it loads the validator and the corpus code
        held = json.loads((TOOLS.parent / "tools" / "data" / "blog_compare.json").read_text(encoding="utf-8")).get("due") or {}
    except (OSError, ValueError):
        return {}
    return {pid: sorted({row[0] for row in rows}) for pid, rows in held.items()}


def blog_tail_due(pid, row, runs, resume_dir, table=None):
    """The clues a blog re-check run has due on pid, when it is worth bagging: 1..MAX_DUE
    of them and no conversation already holds it. None otherwise (it runs alone). `row`
    is unused (the index knows nothing of the blogs); `table` is blog_due()."""
    n = len((table if table is not None else blog_due()).get(pid) or ())
    if not 1 <= n <= MAX_DUE:
        return None
    if (runs / f"{pid}.sid").exists() or (resume_dir / f"ct-prereset-{pid}.resume").exists():
        return None
    return n


def blog_spread_target(leader, queue, table, slots, target=BAG_TARGET, least=MIN_TARGET):
    """spread_target for the blog re-check: the clues due on the leader and queue[:SCAN]."""
    if slots <= 1:
        return target
    total = sum(len(table.get(p) or ()) for p in [leader, *queue[:SCAN]])
    return max(least, min(target, -(-total // slots)))


def field_clues(pid):
    """How many clues of pid a field backfill run (CT_BACKFILL_FIELD, the pool's field) has
    due, by its file; 0 when it will not read."""
    import annotate_check
    from fetch_puzzle import read_puzzle_file, resolve_puzzle
    try:
        return len(annotate_check.field_due(read_puzzle_file(resolve_puzzle(pid))))
    except (SystemExit, OSError, ValueError, KeyError):
        return 0


def field_tail_due(pid, row, runs, resume_dir):
    """The clues a field backfill run has due on pid, when it is worth bagging (1..MAX_DUE and
    no conversation already holds it); None otherwise. Read from the file: the index knows no field."""
    if (runs / f"{pid}.sid").exists() or (resume_dir / f"ct-prereset-{pid}.resume").exists():
        return None
    n = field_clues(pid)
    return n if 1 <= n <= MAX_DUE else None


def field_spread_target(leader, queue, slots, target=BAG_TARGET, least=MIN_TARGET):
    """spread_target for a field backfill: the clues the field's allowance
    (tools/annotation_backlog.json, the clues a puzzle lacks it on) holds for the leader and queue[:SCAN]."""
    import os
    if slots <= 1:
        return target
    try:
        held = json.loads((TOOLS / "annotation_backlog.json").read_text(encoding="utf-8")).get(os.environ.get("CT_BACKFILL_FIELD", ""), {})
    except (OSError, ValueError):
        return target
    total = sum(min(MAX_DUE, held.get(p, 0)) for p in [leader, *queue[:SCAN]])
    return max(least, min(target, -(-total // slots)))


def main(argv):
    with_due = "--due" in argv
    any_listed = "--any-listed" in argv
    slots = 1
    if "--spread" in argv:
        i = argv.index("--spread")
        slots = int(argv[i + 1])
        del argv[i:i + 2]
    blog = "--blog" in argv
    field = "--field" in argv
    argv = [a for a in argv if a not in ("--due", "--any-listed", "--blog", "--field")]
    if len(argv) not in (2, 3):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    held = ledger_skipped()
    queue = [p for p in sys.stdin.read().split() if p not in held]
    if blog:
        table = blog_due()
        resume_dir = Path(argv[2] if len(argv) == 3 else "/tmp")
        counts = {}
        bag = bag_of(argv[1], queue, {}, Path(argv[0]), resume_dir,
                     target=blog_spread_target(argv[1], queue, table, slots), counts=counts,
                     due=lambda pid, row, runs, resume: blog_tail_due(pid, row, runs, resume, table))
        counts.setdefault(argv[1], len(table.get(argv[1]) or ()))  # a leader too big to bag still counts its clues
        print("\n".join(f"{pid} {counts.get(pid, 0)}" if with_due else pid for pid in bag))
        return 0
    if field:
        resume_dir = Path(argv[2] if len(argv) == 3 else "/tmp")
        counts = {}
        bag = bag_of(argv[1], queue, {}, Path(argv[0]), resume_dir,
                     target=field_spread_target(argv[1], queue, slots), counts=counts, due=field_tail_due)
        if not counts.get(argv[1]):
            counts[argv[1]] = field_clues(argv[1])
        print("\n".join(f"{pid} {counts.get(pid, 0)}" if with_due else pid for pid in bag))
        return 0
    import prereset_plan
    rows = {r["id"]: r for r in prereset_plan.index_rows()}
    if any_listed:
        queue = with_listed(queue, pickable_ids(rows), held_in_bags(argv[0]))
    resume_dir = Path(argv[2] if len(argv) == 3 else "/tmp")
    counts = {}
    target = spread_target(argv[1], queue, rows, slots)
    bag = bag_of(argv[1], queue, rows, Path(argv[0]), resume_dir, target=target, counts=counts)
    if any_listed and argv[1] not in counts:
        # A leader that is no tail still has a count: 0 here is real (it awaits its preamble, or
        # its listed clues have no text), and the burn drops a bag with none due.
        counts[argv[1]] = shape_clues(argv[1]) or 0
    print("\n".join(f"{pid} {counts.get(pid, 0)}" if with_due else pid for pid in bag))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
