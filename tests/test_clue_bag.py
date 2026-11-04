#!/usr/bin/env python3
# Which tail puzzles share one annotate session (tools/clue_bag.py).
#
#     python3 tests/test_clue_bag.py
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # puts tools/ on sys.path

import copy
import tempfile
from pathlib import Path

import clue_bag
import fetch_puzzle as F
import groups
import shape_queue

shape_queue.PATH = Path(tempfile.mkdtemp()) / "none.json"  # not the live re-annotation list
fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


print("a bag is the leader and the next tails, to about 30 clues")
runs, resume = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
tails = {f"t{i}": 4 for i in range(20)}   # four clues due each
rows = {pid: {"id": pid, "unannotated": 4, "hasSolutions": True} for pid in tails}
rows["big"] = {"id": "big", "unannotated": 40, "hasSolutions": True}
queue = ["big", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "t10"]


def due(pid, row, runs, resume):
    return tails.get(pid)


bag = clue_bag.bag_of("t0", queue, rows, runs, resume, due=due)
check("the leader is first and the bag stops once 30 clues are in it (8 puzzles of 4)",
      bag == ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7"])
check("a puzzle that is not a tail is passed over, not in the bag", "big" not in bag)
check("a leader that is not a tail goes alone",
      clue_bag.bag_of("big", queue, rows, runs, resume, due=due) == ["big"])
check("a short queue gives a short bag",
      clue_bag.bag_of("t0", ["t1"], rows, runs, resume, due=due) == ["t0", "t1"])
check("an id twice in the queue is bagged once",
      clue_bag.bag_of("t0", ["t1", "t1", "t0"], rows, runs, resume, due=due) == ["t0", "t1"])
check("--any-listed: the queue first, then the listed puzzles it lacks, in id order",
      clue_bag.with_listed(["t2", "t1"], {"t1", "z9", "a1"}) == ["t2", "t1", "a1", "z9"])
heldrun = Path(tempfile.mkdtemp())
(heldrun / "lead.bag").write_text("lead\nz9\n")
check("--any-listed never takes a puzzle a bag in flight holds",
      clue_bag.with_listed(["t2"], {"z9", "a1"}, clue_bag.held_in_bags(heldrun)) == ["t2", "a1"])
counts = {}
clue_bag.bag_of("t0", ["big", "t1", "t2"], rows, runs, resume, due=due, counts=counts)
check("counts holds each bagged puzzle's clues due, for the burn's log line (--due)",
      counts == {"t0": 4, "t1": 4, "t2": 4})

print("what a bag will not take")
(runs / "t1.sid").write_text("sid-1")
(resume / "ct-prereset-t2.resume").write_text("note")
row = {"id": "x", "unannotated": 2, "hasSolutions": True}
check("a puzzle with a conversation already under way",
      clue_bag.tail_due("t1", rows["t1"], runs, resume) is None)
check("a puzzle with a resume note", clue_bag.tail_due("t2", rows["t2"], runs, resume) is None)
check("a puzzle with no hints at all (no count on its row)",
      clue_bag.tail_due("x", {"id": "x", "hasSolutions": True}, runs, resume) is None)
check("a puzzle more than ten clues short",
      clue_bag.tail_due("x", dict(row, unannotated=11), runs, resume) is None)
check("a puzzle with an unreadable clue", clue_bag.tail_due("x", dict(row, clues={"present": 1, "total": 2}), runs, resume) is None)
check("a puzzle without all its answers", clue_bag.tail_due("x", dict(row, hasSolutions=False), runs, resume) is None)
check("a puzzle awaiting its preamble", clue_bag.tail_due("x", dict(row, awaitsPreamble=True), runs, resume) is None)

print("a puzzle file decides on its preamble and the clues due")
for src in F.puzzle_files():
    puzzle = F.read_puzzle_file(src)
    cont = groups.leader_of(puzzle["entries"])
    clues = [e for e in puzzle["entries"] if groups.entry_id(e) not in cont]
    if (len(clues) >= 12 and all(e.get("annotation") for e in clues) and not puzzle.get("preamble")
            and not puzzle.get("themeClue") and not puzzle.get("cluesUnplaced")
            and all(e.get("solution") for e in puzzle["entries"])):
        break
else:
    sys.exit("no fully annotated plain puzzle in the corpus")


def stripped(n):
    p = copy.deepcopy(puzzle)
    gone = {groups.entry_id(e) for e in clues[:n]}
    for e in p["entries"]:
        if groups.entry_id(e) in gone:
            e.pop("annotation", None)
    return p


check("two clues missing: two due", clue_bag.due_clues(stripped(2)) == 2)
check("none missing: nothing to bag", clue_bag.due_clues(stripped(0)) is None)
check("eleven missing: more than a tail", clue_bag.due_clues(stripped(11)) is None)
p = stripped(2)
p["preamble"] = "Eight clues have a misprint in the definition; the misprints spell a message."
check("a preamble keeps the puzzle whole", clue_bag.due_clues(p) is None)
p = stripped(2)
p["themeClue"] = "see preamble"
check("a theme clue keeps the puzzle whole", clue_bag.due_clues(p) is None)
p = stripped(2)
p["entries"][0]["solution"] = ""
check("an unsolved entry keeps it out", clue_bag.due_clues(p) is None)

print("a hinted puzzle with a few clues on the shape redo list is a tail; code-fixed reasons do not count")
import json
sl = Path(tempfile.mkdtemp()) / "shape.json"
sl.write_text(json.dumps([
    {"id": "r1#1a", "reason": "del_single: x"}, {"id": "r1#2d", "reason": "arity_ins: y"},
    {"id": "r2#1a", "reason": "spelling.unsaid: z"}, {"id": "r3#1a", "reason": "hidden: h"},
    {"id": "r4#1a", "reason": "del_single: x", "tried": True, "tries": shape_queue.MAX_TRIES}]
    + [{"id": "r5#%da" % i, "reason": "del_single: x"} for i in range(1, 12)]))
shape_queue.PATH = sl
base = {"hasSolutions": True, "unannotated": 0}
check("two redo clues: a tail", clue_bag.row_is_tail({**base, "id": "r1"}))
check("redo=False counts only missing clues (the planner uses the default, redo included)", not clue_bag.row_is_tail({**base, "id": "r1"}, redo=False))
check("spelling.unsaid is code's: not due", not clue_bag.row_is_tail({**base, "id": "r2"}))
check("a hidden-word parse is code's: not due", not clue_bag.row_is_tail({**base, "id": "r3"}))
check("a tried row is not due", not clue_bag.row_is_tail({**base, "id": "r4"}))
check("eleven redo clues: more than a tail", not clue_bag.row_is_tail({**base, "id": "r5"}))
check("missing plus redo add up", clue_bag.row_is_tail({**base, "id": "r1", "unannotated": 8})
      and not clue_bag.row_is_tail({**base, "id": "r1", "unannotated": 9}))
check("a preamble-awaiting redo row stays whole", not clue_bag.row_is_tail({**base, "id": "r1", "awaitsPreamble": True}))

print("the blog re-check bags the puzzles blog_compare.py --due flags, 1..MAX_DUE clues each")
table = {"b1": ["1-across", "2-down"], "b2": ["3-down"], "b3": ["4-across"] * 1, "big": [f"{i}-across" for i in range(11)]}
blogdue = lambda pid, row, runs, resume: clue_bag.blog_tail_due(pid, row, runs, resume, table)
counts = {}
bag = clue_bag.bag_of("b1", ["big", "b2", "none", "b3"], {}, Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()),
                      due=blogdue, counts=counts)
check("blog bag skips a puzzle over MAX_DUE and one with nothing due", bag == ["b1", "b2", "b3"] and counts == {"b1": 2, "b2": 1, "b3": 1})
check("a blog leader with too many clues runs alone", clue_bag.bag_of("big", ["b1"], {}, Path("/nonexistent"), Path("/nonexistent"), due=blogdue) == ["big"])

print("a field backfill (CT_BACKFILL_FIELD) bags the puzzles short of the field, 1..MAX_DUE clues each")
fieldn = {"f1": 2, "f2": 1, "big": 25, "none": 0}
clue_bag.field_clues = lambda pid: fieldn.get(pid, 0)
counts = {}
bag = clue_bag.bag_of("f1", ["big", "none", "f2"], {}, Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()),
                      due=clue_bag.field_tail_due, counts=counts)
check("field bag skips a puzzle over MAX_DUE and one with nothing due", bag == ["f1", "f2"] and counts == {"f1": 2, "f2": 1})
check("a field leader with a whole puzzle's clues runs alone, through the same path",
      clue_bag.bag_of("big", ["f1"], {}, Path("/nonexistent"), Path("/nonexistent"), due=clue_bag.field_tail_due) == ["big"])
held = Path(tempfile.mkdtemp())
(held / "f2.sid").write_text("x")
check("a field puzzle a conversation holds is left alone",
      clue_bag.bag_of("f1", ["f2"], {}, held, Path(tempfile.mkdtemp()), due=clue_bag.field_tail_due) == ["f1"])

print("shape-rule pickers: no clue on a puzzle awaiting its preamble, none with no published text, and a zero count is real")
import annotate_check
ents = [{"number": n, "direction": "across", "solution": "ABC", "length": 3,
         "clue": {"text": txt}, "annotation": {"x": 1}} for n, txt in ((15, ""), (21, ""), (1, "A clue here (3)"))]
sp = {"id": "zz-1", "entries": ents}
shape_queue.flagged = lambda puzzle: {"15-across": "delSingle", "21-across": "delSingle", "1-across": "delSingle"}
check("shape_due leaves out the clues published with no text", annotate_check.shape_due(sp) == ["1-across"])
check("shape_due is empty for a puzzle awaiting its preamble",
      annotate_check.shape_due(dict(sp, awaitsPreamble=True)) == [])
only_blank = dict(sp, entries=ents[:2])
check("a puzzle whose listed clues all lack text has nothing due", annotate_check.shape_due(only_blank) == [])
F.resolve_puzzle = lambda pid: pid
F.read_puzzle_file = lambda path: {"zz-1": sp, "zz-2": dict(sp, awaitsPreamble=True), "zz-3": only_blank}[path]
check("shape_clues counts the clues a shape run would redo", clue_bag.shape_clues("zz-1") == 1)
check("shape_clues is 0 for the awaiting puzzle and the wordless one",
      clue_bag.shape_clues("zz-2") == 0 and clue_bag.shape_clues("zz-3") == 0)
check("shape_clues is None for a file that will not read", clue_bag.shape_clues("zz-9") is None)
shape_queue.puzzle_ids = lambda: {"a", "b", "c"}
check("pickable_ids drops the index rows that await their preamble",
      clue_bag.pickable_ids({"a": {"awaitsPreamble": True}, "b": {}}) == {"b", "c"})

print("the bag is committed per puzzle: the worker's side is in tests/test_puzzle_worker.sh")
print("clue_bag: all checks passed" if not fails else f"clue_bag: {fails} FAILED")
sys.exit(1 if fails else 0)
