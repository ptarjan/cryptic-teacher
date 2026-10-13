#!/usr/bin/env bash
# Does the schema and validator hold a format v2 file to v2's rules (no field
# that can be derived from others, a tree that gives the answer, no new
# unchecked steps) while every legacy file keeps passing as it is?
#
#     bash tools/test_format_v2.sh
#
# The shape is read off the file (tools/puzzle_schema.py format_problems): an
# annotation with `blocks` is legacy, one without is v2, and a file is wholly
# one shape. The v2 files here are corpus puzzles run through
# tools/convert_v2.py convert_puzzle, in memory; nothing is written.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
import json
import sys
from pathlib import Path

import annotation
import convert_v2
import fetch_puzzle as fp
import puzzle_schema as S
import validate_annotations as V

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else detail)

def refused(puzzle, needle):
    probs = S.validate(puzzle)
    return any(needle in p for p in probs), probs

# Two recent Guardian cryptics that convert whole (a re-annotated puzzle that
# no longer converts is skipped, not failed: the converter has its own test).
pairs = convert_v2.converted_samples(2)
check("found converted puzzles to test", len(pairs) == 2, len(pairs))
old, new, status = pairs[0]

# ---- legacy files keep passing, v2 files pass v2 ----
for o, n, _ in pairs:
    check(f"{o['id']}: the legacy file is legacy and passes", not S.is_v2(o) and S.validate(o) == [],
          S.validate(o)[:3])
    check(f"{o['id']}: its conversion is v2 and passes", S.is_v2(n) and S.validate(n) == [], S.validate(n)[:3])
    check(f"{o['id']}: the v2 file stores no name or series", "name" not in n and "series" not in n)

def first_tree(p, want=lambda node: True):
    """(entry, annotation, node) for the first node in a tree that `want` accepts."""
    for e in p["entries"]:
        a = e.get("annotation")
        stack = [a["wordplay"]] if a and a.get("wordplay") else []
        while stack:
            node = stack.pop(0)
            if want(node):
                return e, a, node
            stack += node.get("parts") or []
    raise SystemExit("no such node in " + p["id"])

# ---- every derived field is refused in a v2 file ----
for key, value in [("name", old["name"]), ("series", old["series"])]:
    p = copy.deepcopy(new)
    p[key] = value
    ok, probs = refused(p, f"key {key!r} is refused")
    check(f"v2 refuses a stored top-level {key}", ok, probs[:3])
for key, value in [("type", ["charade"]), ("answer", "X"), ("linkWords", ["and"]),
                   ("indicators", [{"text": "x", "for": "anagram"}]), ("assembly", {"pieces": ["A", "B"]})]:
    p = copy.deepcopy(new)
    _, a, _ = first_tree(p)
    a[key] = value
    ok, probs = refused(S.order(p), f"key {key!r} is refused: derived")
    check(f"v2 refuses a stored annotation {key}", ok, probs[:3])
p = copy.deepcopy(new)
_, _, node = first_tree(p, lambda n: n.get("indicators"))
node["indicators"][0]["for"] = "anagram"
ok, probs = refused(S.order(p), "key 'for' is refused")
check("v2 refuses an indicator's `for`", ok, probs[:3])
p = copy.deepcopy(new)
_, _, node = first_tree(p, lambda n: "op" in n and not n.get("unchecked"))
node["gives"] = "ABC"
ok, probs = refused(S.order(p), "key 'gives' is refused")
check("v2 refuses `gives` on a checked op (the evaluator works it out)", ok, probs[:3])
p = copy.deepcopy(new)
_, _, node = first_tree(p, lambda n: "words" in n and not n.get("unchecked"))
node["select"] = "first"
ok, probs = refused(S.order(p), "key 'select' is refused")
check("v2 refuses legacy `select` on a checked leaf", ok, probs[:3])
p = copy.deepcopy(new)
e, a, _ = first_tree(p)
a["spelling"] = annotation.display_answer(e, p)
ok, probs = refused(S.order(p), "leave `spelling` out")
check("v2 refuses a `spelling` equal to the derived answer", ok, probs[:3])
a["spelling"] = annotation.display_answer(e, p).lower()
check("and keeps one that differs", not any("spelling" in x for x in S.validate(S.order(p))))

# ---- one shape a file ----
p = copy.deepcopy(new)
i = next(i for i, e in enumerate(old["entries"]) if e.get("annotation"))
p["entries"][i]["annotation"] = old["entries"][i]["annotation"]
ok, probs = refused(p, "a legacy annotation (it has `blocks`) in a format v2 file")
check("a legacy annotation in a v2 file is refused", ok, probs[:3])
p = copy.deepcopy(old)
p["entries"][i]["annotation"] = copy.deepcopy(p["entries"][i]["annotation"])
p["entries"][i]["annotation"]["andLit"] = True
ok, probs = refused(S.order(p), "key 'andLit' is refused: a format v2 key")
check("a v2 key on a legacy annotation is refused", ok, probs[:3])
p = copy.deepcopy(old)
p["prize"] = True
ok, probs = refused(S.order(p), "key 'prize' is format v2's")
check("a legacy file may not carry v2's `prize`", ok, probs[:3])
p = copy.deepcopy(old)
del p["series"]
for e in p["entries"]:
    e.pop("annotation", None)
ok, probs = refused(p, "key 'name' is refused")
check("a file without series is read as v2, so its stored name is refused", ok, probs[:3])
p = copy.deepcopy(old)
del p["name"]
ok, probs = refused(p, "missing required key 'name'")
check("a legacy file still needs its name", ok, probs[:3])

# ---- the validator reads view(): same findings, and the tree is checked ----
for o, n, st in pairs:
    _, errs_old, _ = V.validate_puzzle(o, corpus=True)
    _, errs_new, warns_new = V.validate_puzzle(n, corpus=True)
    exact = [w for w, s in st.items() if s == "exact"]
    tags = {V._tag_of(o, w) for w in exact}
    pick = lambda errs: sorted(x for x in errs if x.split(":", 1)[0] in tags)
    check(f"{o['id']}: exact-converted clues get the same errors from either shape",
          pick(errs_old) == pick(errs_new), (pick(errs_old)[:3], pick(errs_new)[:3]))
    check(f"{o['id']}: no wordplay or schema error on the converted file",
          not [x for x in errs_new if "wordplay:" in x or x.startswith("schema:")], errs_new[:3])
p = copy.deepcopy(new)
e, a, node = first_tree(p, lambda n: "words" in n and n.get("gives") and not n.get("unchecked"))
node["gives"] = node["gives"] + "Q"
_, errs, _ = V.validate_puzzle(p, corpus=True)
tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
check("a tree that does not give the answer is a validator error",
      any(x.startswith(f"{tag}: wordplay: ") for x in errs), errs[:3])

# An unchecked step: a warning the ratchet counts, and an allowance of none.
p = copy.deepcopy(new)
e, a, _ = first_tree(p)
a["wordplay"] = {"op": "deletion", "unchecked": True, "gives": V.letters(e["solution"]),
                 "parts": [a["wordplay"]]}
_, errs, warns = V.validate_puzzle(S.order(p), corpus=True)
check("an unchecked step warns with the ratchet's marker",
      any(V.UNCHECKED_STEP in w for w in warns), warns[:3])
counts = V.count_backlog(warns)
check("and the ratchet counts its clue", counts["wordplay.unchecked"] >= 1, counts)
check("a puzzle the backlog allows none gets an error",
      bool(V.backlog_errors(p["id"], warns, {"wordplay.unchecked": {}})))

# What the site sees of a v2 file (browser_puzzle reads view()) is
# tools/test_shim_format.sh's and tools/smoke_test.js's to check.

print("PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
PY
