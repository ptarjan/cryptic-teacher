#!/usr/bin/env python3
"""Pins the two fixes for burn waste found in the 10-16 audit of .prereset.log.

1. A transient failure (drop_failed) and a cut-off validation-fix run keep their
   conversation, so the next start resumes it instead of buying it fresh.
2. The field and blog backfill prompts carry the shape exception, so the run
   rewrites the clues the view lists as `flagged` and the shape tier does not
   redo the puzzle.

    python3 tests/test_resume_not_redo.py
"""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import re
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
burn = (TOOLS / "prereset_backfill.sh").read_text()
worker = (TOOLS / "puzzle_worker.sh").read_text()


def fn(text, name):
    m = re.search(rf"^{name}\(\) \{{.*?^\}}", text, re.S | re.M)
    assert m, name
    return m.group(0)


drop = fn(burn, "drop_failed")
# A transient record (exit 3) keeps the session: the forget comes after the continue.
assert "-eq 3" in drop and drop.index("-eq 3") < drop.index("worker_forget"), drop
assert drop.index("continue") < drop.index("worker_forget")

commit = fn(burn, "commit_puzzle")
assert "WORKER_KEEP_CUTOFF_FIX=1 worker_finish" in commit
assert "3)" in commit and "WAVE_FAILED_IDS+=" in commit

fin = fn(worker, "worker_finish")
assert fin.index("-eq 3") < fin.index("worker_forget") < fin.index("worker_clean")

# Every "change nothing else" backfill prompt carries the shape exception.
exc = re.search(r'^SHAPE_EXCEPTION="(.*)"$', burn, re.M)
assert exc and "flagged" in exc.group(1) and "annotate_check.py --view" in exc.group(1)
for marker in ("This is ADDITIVE", "has clues whose definition, type or building blocks disagree"):
    line = next(l for l in burn.splitlines() if marker in l)
    assert "$SHAPE_EXCEPTION" in line, marker
print("resume not redo: all checks passed")
