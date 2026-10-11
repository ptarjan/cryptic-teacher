#!/bin/bash
# A blank light on a puzzle whose answer key is a blog's write-up is never
# offered for a solve.
#
#     bash tools/test_writeup_keyed.sh
#
# apply_solution.check_writeup refuses any model fill there, so a queued solve
# could only fail and alert. The index row says so (writeupKeyed) and
# fetch_puzzle.cold_solvable, which the daily solve queue and the burn's
# backlog share, reads it.
set -uo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools python3 - <<'PY'
import copy, shutil, sys, tempfile
from pathlib import Path
import apply_solution
import fetch_puzzle as F
import provenance

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

    cyclops = copy.deepcopy(blank)
    cyclops["source"]["retrievedFrom"] = "publisher"
    check("answers from a write-up are keyed though the grid came from the paper",
          provenance.writeup_keyed(cyclops))
    del cyclops["solutions"]["blog"]
    check("a publisher's puzzle with no write-up is not", not provenance.writeup_keyed(cyclops))
finally:
    shutil.rmtree(tmp)
sys.exit(fails)
PY
rc=$?
[ $rc = 0 ] && echo "writeup_keyed: all checks passed" || echo "writeup_keyed: FAILED"
exit $rc
