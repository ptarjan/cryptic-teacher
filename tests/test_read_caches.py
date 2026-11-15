#!/usr/bin/env python3
# The stat-keyed caches that keep the burn's re-plan from re-reading files:
# held_rows_cached (clues-only rows) and failed_inputs.skipped_all.
#
#     python3 tests/test_read_caches.py
import os

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import sys
import tempfile
from pathlib import Path

import _path  # puts tools/ on sys.path
import failed_inputs
import prereset_plan

fails = []


def check(what, got, want):
    if got != want:
        fails.append(what)
        print(f"FAIL {what}: got {got!r}, want {want!r}", file=sys.stderr)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    # --- held rows: reread only on a stat change
    root, cache = tmp / "clues_only", tmp / "held.json"
    (root / "book").mkdir(parents=True)
    f = root / "book" / "book-1.json"
    f.write_text(json.dumps({"id": "book-1", "series": "book", "year": 1990}))
    built = []
    real = prereset_plan._held_row
    prereset_plan._held_row = lambda r: (built.append(r["id"]), {"id": r["id"], "year": r["year"]})[1]
    try:
        check("first call reads", prereset_plan.held_rows_cached(root, cache), [{"id": "book-1", "year": 1990}])
        check("first call parsed once", built, ["book-1"])
        prereset_plan.held_rows_cached(root, cache)
        check("unchanged file is not parsed again", built, ["book-1"])
        f.write_text(json.dumps({"id": "book-1", "series": "book", "year": 1991}))
        check("changed file is read again", prereset_plan.held_rows_cached(root, cache),
              [{"id": "book-1", "year": 1991}])
        check("and parsed again", built, ["book-1", "book-1"])
        f.unlink()
        check("a removed file drops out", prereset_plan.held_rows_cached(root, cache), [])
        # a code change re-reads everything
        f.write_text(json.dumps({"id": "book-1", "series": "book", "year": 1991}))
        prereset_plan.held_rows_cached(root, cache)
        n = len(built)
        saved = json.loads(cache.read_text())
        saved["code"] = [0, 0]
        cache.write_text(json.dumps(saved))
        prereset_plan.held_rows_cached(root, cache)
        check("a clues_only.py change re-reads", len(built), n + 1)
    finally:
        prereset_plan._held_row = real

    # --- skipped: cached until the ledger, a puzzle, or the clock moves
    failed_inputs.LEDGER = tmp / "ledger.json"
    failed_inputs.puzzle_paths.PUZZLE_DIR = tmp / "puzzles"
    pf = tmp / "puzzles" / "ct" / "undated" / "ct-1.json"
    pf.parent.mkdir(parents=True)
    pf.write_text(json.dumps({"id": "ct-1", "entries": []}))
    failed_inputs.save({"annotate": {"ct-1": {"puzzle": failed_inputs.input_hash("ct-1"), "reason": "x",
                                                "code": failed_inputs.code_version("annotate", "ct-1", "x")}},
                        "solve": {}})
    sc = tmp / "skipped.json"
    calls = []
    real_due = failed_inputs.due
    failed_inputs.due = lambda *a: (calls.append(a), real_due(*a))[1]
    try:
        got = failed_inputs.skipped_all(failed_inputs.load(), now=1000, cache=sc)
        check("skipped on unchanged inputs", got, {"annotate": ["ct-1"], "solve": []})
        n = len(calls)
        failed_inputs.skipped_all(failed_inputs.load(), now=1001, cache=sc)
        check("second call is answered from the cache", len(calls), n)
        failed_inputs.skipped_all(failed_inputs.load(), now=1000 + failed_inputs.SKIPPED_TTL_S + 1, cache=sc)
        check("an old answer is recomputed", len(calls) > n, True)
        n = len(calls)
        pf.write_text(json.dumps({"id": "ct-1", "entries": [{"number": 1, "direction": "across", "clue": "Pet (3)", "solution": "CAT"}]}))
        got = failed_inputs.skipped_all(failed_inputs.load(), now=1002, cache=sc)
        check("a changed puzzle is released at once", got, {"annotate": [], "solve": []})
        check("by recomputing", len(calls) > n, True)
    finally:
        failed_inputs.due = real_due

sys.exit(1 if fails else 0)
