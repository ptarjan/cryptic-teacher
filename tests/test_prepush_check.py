#!/usr/bin/env python3
# Does the pre-push gate (tools/prepush_check.py) refuse what a bad merge leaves: conflict
# markers, a module that does not parse, a name assigned twice, a reason queued first that is
# unranked or dropped by evidence_reason, a key that moved, a new ruff finding?
#
#     python3 tests/test_prepush_check.py
#
# Fake text only; no OCR, no network, no git.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import prepush_check as P

fails = 0


def check(name, want, got):
    global fails
    ok = want == got
    print(("  ok: " if ok else "  FAIL: ") + name + ("" if ok else f" (want {want!r}, got {got!r})"))
    fails += not ok


good = "A = 1\nB = (A, 2)\n"
check("clean module has no problems", [], P.parse_problems("m.py", good))
conflicted = "A = 1\n<<<<<<< HEAD\nA = 2\n=======\nA = 3\n>>>>>>> other\n"
check("three conflict markers found", [2, 4, 6], [n for n, _ in P.conflict_markers(conflicted)])
check("indented marker text is not a marker", [], P.conflict_markers("x = '''\n    <<<<<<< a\n'''\n"))
check("a conflicted module is reported (markers and syntax)", True, len(P.parse_problems("m.py", conflicted)) >= 4)
check("syntax error reported with its line", True, any("m.py:1" in p for p in P.parse_problems("m.py", "def (:\n")))

dup = "NEWEST_LANDED = (1,)\nX = 2\nNEWEST_LANDED = (2,)\nNEWEST_LANDED = (3,)\n"
found = P.duplicate_assignments("tools/edition_queue.py", dup)
check("triple assignment is one problem naming the lines", True,
      len(found) == 1 and "NEWEST_LANDED" in found[0] and "1, 3, 4" in found[0])
check("a single assignment and an if-branch rebinding pass", [],
      P.duplicate_assignments("m.py", "A = 1\nif A:\n    B = 1\nelse:\n    B = 2\nA += 1\n"))
check("known duplicate is tolerated", [],
      P.duplicate_assignments("tools/file_archive_org_puzzles.py", "CLUE_OPENING = 1\nCLUE_OPENING = 2\n"))

kept = {"a", "b"}.__contains__
check("ranked, passed, kept reasons pass", [],
      P.registry_problems(("a",), ("b",), {"a": 1, "b": 1}, ("a",), ("b",), kept))
bad = P.registry_problems(("a", "z"), ("y",), {"a": 1}, ("a",), (), kept)
check("unranked reasons are named", True, any("'z'" in p and "RANKS" in p for p in bad) and any("'y'" in p and "RANKS" in p for p in bad))
check("an unkept UNFILED_FIRST reason is named", True, any("'z'" in p and "evidence_reason" in p for p in bad))
check("a refused-before-its-fix style reason kept by evidence_reason needs no pass", [],
      P.registry_problems((), ("c",), {"c": 1}, (), (), lambda r: True))

keys = {"solution": "aa", "scan": {"times": "bb", "ft": "cc"}}
check("same keys pass", [], P.key_problems(keys, keys))
moved = P.key_problems(keys, {"solution": "dd", "scan": {"times": "bb", "ft": "cc", "new": "ee"}})
check("a moved solution key and a new paper are both named", 2, len(moved))
check("the message says what to do", True,
      "key solution moved aa -> dd: pin it (*_FIX table) or rerun --write-keys if intended" in moved)

check("ruff-new findings are the multiset difference", [("F811", "b")],
      P.new_findings([("F401", "a")], [("F401", "a"), ("F811", "b")]))
check("a repeated old finding is not new", [], P.new_findings([("F811", "b")], [("F811", "b")]))

print("FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
