#!/usr/bin/env python3
# Which tail puzzles share one annotate session (tools/clue_bag.py).
#
#     python3 tools/test_clue_bag.py
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

print("the bag is committed per puzzle: the worker's side is in tools/test_puzzle_worker.sh")
print("clue_bag: all checks passed" if not fails else f"clue_bag: {fails} FAILED")
sys.exit(1 if fails else 0)
