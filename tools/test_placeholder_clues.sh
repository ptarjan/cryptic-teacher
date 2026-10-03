#!/bin/bash
# A puzzle whose clues are pointers at clues printed elsewhere has no clues.
#
#     bash tools/test_placeholder_clues.sh
#
# The Guardian's 2000-02 alphabetical jigsaws print "See special instructions"
# (or "See clues page") on every light. Read as clues, each one queued its
# puzzle for an annotation run that could only end in "produced no change".
# placeholder_clues() reads them as missing, puzzle-wide; one such pointer among
# real clues (cryptic-26741's 5-down, defined by the preamble) stays a clue.
set -uo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools python3 - <<'PY'
import sys
import enumeration
import fetch_puzzle as F
from groups import entry_id

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

def entry(eid, clue, **kw):
    num, _, d = eid.partition("-")
    text = enumeration.split(clue)[0]
    e = {"number": int(num), "direction": d, "position": {"x": 0, "y": 0},
         "length": 5, "solution": "ABCDE",
         "clue": enumeration.clue(clue, missing=not F.has_words(text))}
    e.update(kw)
    return e

pointers = {"id": "cryptic-22529", "entries": [
    entry("1-across", "See special instructions (5)"),
    entry("2-down", "See clues page (5)"),
    entry("3-down", "Follow the link below to see today's clues (5)"),
    entry("4-across", " (5)"),
]}
check("every pointer in an all-pointer puzzle is a placeholder",
      F.placeholder_clues(pointers["entries"]) == {"1-across", "2-down", "3-down"})
check("an all-pointer puzzle has nothing to annotate, so is never queued",
      F.unannotated_clues(pointers) == [] and F.puzzle_is_annotated(pointers))
check("its coverage counts no clues", F.clue_coverage(pointers) == {"present": 0, "total": 4})

# The mirror: the same pointer beside real clues is a light the preamble
# defines, and still wants annotating.
preamble = {"id": "cryptic-26741", "entries": [
    entry("1-across", "Force a writer to absorb Republican material (5)"),
    entry("5-down", "(See special instructions) (5)"),
]}
check("a pointer beside real clues is not a placeholder",
      F.placeholder_clues(preamble["entries"]) == set())
check("and is still queued for annotation",
      [entry_id(e) for e in F.unannotated_clues(preamble)] == ["1-across", "5-down"])
check("and counts as a clue", F.clue_coverage(preamble) == {"present": 2, "total": 2})
check("a clue that opens like a pointer is wordplay",
      not F.ELSEWHERE.match("See instruction confused medical expert"))

# A re-fetch: the fetcher stores placeholders as missing, and a stored
# placeholder is not "recovered" text to carry over a blank.
fetched = {"id": "cryptic-22529", "entries": [entry("1-across", " (5)"), entry("2-down", " (5)")]}
stored = {"id": "cryptic-22529", "entries": [
    entry("1-across", "See special instructions (5)"), entry("2-down", "See clues page (5)")]}
F.carry_recovered_clues(fetched, stored)
check("a stored placeholder is not carried over a re-fetch",
      all(e["clue"].get("missing") and "text" not in e["clue"] for e in fetched["entries"]))
stored["entries"][0] = entry("1-across", "Recovered from the clue page (5)")
F.carry_recovered_clues(fetched, stored)
check("a recovered clue still is",
      fetched["entries"][0]["clue"].get("text") == "Recovered from the clue page")

# The write guard protects a clue's words, and a placeholder has none to lose.
import puzzle_integrity
blank = {"id": "cryptic-22529", "entries": [entry("1-across", " (5)"), entry("2-down", " (5)")]}
was = {"id": "cryptic-22529", "entries": [
    entry("1-across", "See special instructions (5)"), entry("2-down", "See clues page (5)")]}
flags = []
puzzle_integrity.check_rewrite(was, blank, flags)
check("blanking a placeholder is not losing a clue", flags == [])
flags = []
puzzle_integrity.check_rewrite(preamble, {"id": "cryptic-26741", "entries": [
    entry("1-across", " (5)"), entry("5-down", " (5)")]}, flags)
check("blanking a real clue, preamble pointer included, still is", len(flags) == 2)

sys.exit(1 if fails else 0)
PY
status=$?
[ "$status" -eq 0 ] && echo "placeholder_clues: all checks passed" || echo "placeholder_clues: FAILED"
exit "$status"
