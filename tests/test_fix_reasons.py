#!/usr/bin/env python3
# Are the reread-reason lists derived from tools/fix_reasons.py (and tools/reasons/*.py) exactly
# today's, in order, and does each queued-first reason stay ranked, passed and kept?
#
#     python3 tests/test_fix_reasons.py
#
# The frozen copy is tests/fixtures/fix_reasons_frozen.json: the lists as they stood before the
# registry. Registered reasons may only be appended after them.
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import edition_queue as eq
import file_archive_org_puzzles as fa
import fix_reasons

fails = 0


def check(name, want, got):
    global fails
    ok = want == got
    print(("  ok: " if ok else "  FAIL: ") + name + ("" if ok else f" (want {want!r:.200}, got {got!r:.200})"))
    fails += not ok


with open(os.path.join(ROOT, "tests", "fixtures", "fix_reasons_frozen.json"), encoding="utf-8") as f:
    frozen = json.load(f)
live = {"UNFILED_FIRST": eq.UNFILED_FIRST, "NEWEST_LANDED": eq.NEWEST_LANDED, "FIX_LANDED": eq.FIX_LANDED,
        "BLANKET_PASSES": fa.BLANKET_PASSES, "SOLUTION_FIXES": fa.SOLUTION_FIXES}
flags = {"UNFILED_FIRST": "unfiled_first", "NEWEST_LANDED": "newest_landed", "FIX_LANDED": "fix_landed",
         "BLANKET_PASSES": "blanket", "SOLUTION_FIXES": "solution_fix"}
for name, now in live.items():
    old = tuple(frozen[name])
    check(f"{name} starts with its frozen values, in order", old, tuple(now[:len(old)]))
    check(f"{name} ends with the registered reasons", fix_reasons.of(flags[name]), tuple(now[len(old):]))
old_ranks = [tuple(p) for p in frozen["RANKS"]]
check("RANKS starts with its frozen items, in order", old_ranks, list(fa.RANKS.items())[:len(old_ranks)])
check("RANKS' rest is the registered ranks", fix_reasons.ranks(), dict(list(fa.RANKS.items())[len(old_ranks):]))

for r in eq.UNFILED_FIRST:
    check(f"UNFILED_FIRST {r[:40]!r} is ranked", True, r in fa.RANKS)
    check(f"UNFILED_FIRST {r[:40]!r} is a blanket pass or solution fix", True,
          r in fa.BLANKET_PASSES or r in fa.SOLUTION_FIXES or bool(fa.refusal_passes(r)))
    check(f"UNFILED_FIRST {r[:40]!r} is kept by evidence_reason", True, bool(eq.evidence_reason(r)))

print("FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
