#!/usr/bin/env python3
# A blank light on a puzzle whose answer key is a blog's write-up is never
# offered for a solve.
#
#     python3 tests/test_writeup_keyed.py
#
# apply_solution.check_writeup refuses any model fill there, so a queued solve
# could only fail and alert. The index row says so (writeupKeyed) and
# fetch_puzzle.cold_solvable, which the daily solve queue and the burn's
# backlog share, reads it.
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONPATH"] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")

import copy, shutil, sys, tempfile
from pathlib import Path
import apply_solution
import fetch_puzzle as F
import provenance
import solve_packet
from groups import entry_id

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

def blog(p):
    return (p.get("source") or {}).get("retrievedFrom") == "blog"

tmp = Path(tempfile.mkdtemp())
try:
    src = next(f for f in F.puzzle_files()
               if blog(p := F.read_puzzle_file(f)) and all(e.get("solution") for e in p["entries"]))
    path = tmp / src.name
    shutil.copy(src, path)
    row = F.index_row(path)
    check("a blog puzzle with every light answered is not marked", "writeupKeyed" not in row)
    check("and may be queued", F.cold_solvable(row))

    blank = F.read_puzzle_file(path)
    blank["entries"][0]["solution"] = None
    F.write_puzzle_file(path, blank)
    row = F.index_row(path)
    check("a blank light on a blog puzzle marks the row", row.get("writeupKeyed") is True)
    check("so no solve queue offers it", not F.cold_solvable(row))
    check("the solve gate asks the same question", apply_solution.check_writeup(blank) != [])

    # A partial key: the blog left the blank light out on purpose and says so.
    eid = entry_id(blank["entries"][0])
    partial = copy.deepcopy(blank)
    partial["solutions"]["partial"] = [eid]
    check("a partial key naming the blank light is not writeup-keyed", not provenance.writeup_keyed(partial))
    check("the solve gate lets a fill through", apply_solution.check_writeup(partial) == [])
    check("the provenance check accepts the marker", not [f for f in provenance.check(partial) if "partial" in f])
    F.write_puzzle_file(path, partial)
    row = F.index_row(path)
    check("the row is not marked writeupKeyed", "writeupKeyed" not in row)
    check("the row says how many lights are open", row.get("partial") == 1)
    check("so a solve queue offers it", F.cold_solvable(row))
    import prereset_plan
    check("and the plan does not treat it as cold", not prereset_plan.cold_row(row))
    check("while an unmarked blank still is", prereset_plan.cold_row({**row, "partial": None}))

    # A listed light the file already answers is done, not open.
    filled = copy.deepcopy(blank)
    filled["entries"][0]["solution"] = p["entries"][0]["solution"]
    filled["solutions"]["partial"] = [eid]
    check("a listed light already answered is not open", provenance.partial_lights(filled) == [])
    check("and the provenance check accepts it", not [f for f in provenance.check(filled) if "partial" in f])

    wrong = copy.deepcopy(partial)
    wrong["solutions"]["partial"] = []
    check("a marker that does not list the blank light does not unlock it", provenance.writeup_keyed(wrong))
    check("and the provenance check names it", any("partial" in f for f in provenance.check(wrong)))
    extra = copy.deepcopy(partial)
    extra["entries"][1]["solution"] = None
    check("a second blank the marker omits keeps it keyed", provenance.writeup_keyed(extra))

    # The fill may not change a blog answer: check_printed refuses it.
    fill = {entry_id(e): e["solution"] for e in partial["entries"] if e.get("solution")}
    fill[eid] = "X" * partial["entries"][0]["length"]
    other = entry_id(partial["entries"][1])
    fill[other] = "Q" * partial["entries"][1]["length"]
    check("a fill that changes a blog answer is refused", apply_solution.check_printed(partial, fill) != [])
    check("the packet tells the solver which lights are open",
          f"left 1 light(s) out on purpose ({eid})" in solve_packet.packet(F.read_puzzle_view(path)))

    cyclops = copy.deepcopy(blank)
    cyclops["source"]["retrievedFrom"] = "publisher"
    check("answers from a write-up are keyed though the grid came from the paper",
          provenance.writeup_keyed(cyclops))
    del cyclops["solutions"]["blog"]
    check("a publisher's puzzle with no write-up is not", not provenance.writeup_keyed(cyclops))
finally:
    shutil.rmtree(tmp)
print("writeup_keyed: all checks passed" if not fails else "writeup_keyed: FAILED")
raise SystemExit(1 if fails else 0)
