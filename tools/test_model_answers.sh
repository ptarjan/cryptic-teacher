#!/bin/bash
# A model-solved grid's answers can be corrected by the annotator, or sent back
# to be solved again, but never so that a crossing or a printed answer breaks.
#
#     bash tools/test_model_answers.sh
set -uo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import copy, sys
sys.path.insert(0, "tools")
import apply_annotations as A, fetch_puzzle, provenance, reopen_answers as R
from groups import entry_id

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

# times-17379: a model filled around 13 answers the paper printed.
path = fetch_puzzle.resolve_puzzle("times-17379")
base = fetch_puzzle.read_puzzle_file(path)
printed = provenance.printed_answers(base)
check("printed answers read off solutions.printed", printed.get("9-across") == "MISQUOTES")
check("the file as committed passes provenance", not provenance.check(base))

def cells(e):
    x, y = e["position"]["x"], e["position"]["y"]
    return [(x + i, y) if e["direction"] == "across" else (x, y + i) for i in range(e["length"])]
covered = {}
for e in base["entries"]:
    for c in cells(e):
        covered[c] = covered.get(c, 0) + 1
# A model answer with a cell no other light crosses, and one with a checked cell.
model = [e for e in base["entries"] if entry_id(e) not in printed and not e.get("group")]
free = next((e, i) for e in model for i, c in enumerate(cells(e)) if covered[c] == 1)
held = next((e, i) for e in model for i, c in enumerate(cells(e)) if covered[c] > 1)

def swap(word, i):
    return word[:i] + ("Z" if word[i] != "Z" else "Q") + word[i + 1:]

def attempt(puzzle, eid, answer):
    """apply() with every key null but `eid`, the write captured."""
    wrote = {}
    real = A.write_puzzle_file
    A.write_puzzle_file = lambda p, pz: wrote.setdefault("puzzle", pz)
    A.read_puzzle_file = lambda p: copy.deepcopy(puzzle)
    try:
        anns = {entry_id(e): None for e in puzzle["entries"]}
        anns[eid] = {"answer": answer}
        A.apply(path, anns, by="human")
        return wrote.get("puzzle"), None
    except SystemExit as err:
        return None, str(err)
    finally:
        A.write_puzzle_file, A.read_puzzle_file = real, fetch_puzzle.read_puzzle_file

# The model's answer is wrong in its unchecked cell; the annotator gives the right one.
e, i = free
eid, right = entry_id(e), e["solution"]
wrong = copy.deepcopy(base)
next(x for x in wrong["entries"] if entry_id(x) == eid)["solution"] = swap(right, i)
out, err = attempt(wrong, eid, right)
check(f"a correction that keeps every crossing is accepted ({eid})", out is not None and err is None)
if out:
    got = next(x for x in out["entries"] if entry_id(x) == eid)["solution"]
    check("the grid takes the corrected letters", got == right)
    log = out["solutions"].get("corrected") or []
    check("solutions.corrected records it",
          len(log) == 1 and log[0]["entry"] == eid and log[0]["was"] == swap(right, i)
          and log[0]["now"] == right)
    check("the corrected grid passes provenance", not provenance.check(out))

# A correction that changes a checked letter breaks the crossing: refused.
e, i = held
out, err = attempt(base, entry_id(e), swap(e["solution"], i))
check("a correction that breaks a crossing is refused", out is None and "crossing letters disagree" in (err or ""))

# A printed answer is not the model's to correct, even where nothing crosses it.
p_eid = "9-across"
p_entry = next(x for x in base["entries"] if entry_id(x) == p_eid)
out, err = attempt(base, p_eid, swap(p_entry["solution"], 0))
check("a correction of a printed answer is refused", out is None and "the paper printed MISQUOTES" in (err or ""))

# On a grid the paper answered, a differing answer is not a correction.
published = {**base, "solutions": {"origin": "published"}}
check("no corrections off a published grid", A.model_corrections(published, {p_eid: {"answer": "X" * 9}}) == ({}, []))

# The file itself: a grid that overwrote a printed answer, or that logs a
# correction of one, or that lost its printed list, is refused on write.
over = copy.deepcopy(base)
next(x for x in over["entries"] if entry_id(x) == p_eid)["solution"] = "MISQUOTED"
check("provenance refuses a grid over a printed answer",
      any("the paper printed MISQUOTES" in f for f in provenance.check(over)))
logged = copy.deepcopy(base)
logged["solutions"]["corrected"] = [{"entry": p_eid, "was": "MISQUOTES", "now": "MISQUOTED", "date": "2026-10-03"}]
check("provenance refuses a logged correction of a printed answer",
      any("whose answer the paper printed" in f for f in provenance.check(logged)))
lost = copy.deepcopy(base)
del lost["solutions"]["printed"]
check("provenance refuses a partly printed model fill without its printed list",
      any("solutions.printed lists 0" in f for f in provenance.check(lost)))
misprint = copy.deepcopy(base)
fetch_puzzle.SOURCE_ANSWER_WRONG[(base["id"], p_eid)] = ("MISQUOTEZ", "MISQUOTES", "test")
misprint["solutions"]["printed"][p_eid] = "MISQUOTEZ"
check("a key misprint SOURCE_ANSWER_WRONG corrects is not ground truth",
      not provenance.check(misprint) and provenance.printed_answers(misprint)[p_eid] == "MISQUOTES")
del fetch_puzzle.SOURCE_ANSWER_WRONG[(base["id"], p_eid)]
check("without the row the misprint still binds",
      any("the paper printed MISQUOTEZ" in f for f in provenance.check(misprint)))

# Reopening: a model answer left null goes back once; a printed one never.
ran = copy.deepcopy(base)
for x in ran["entries"]:
    if entry_id(x) not in (eid, p_eid):
        x["annotation"] = {"type": ["charade"]}
check("a null model answer is reopenable, a null printed one is not", R.reopenable(ran) == [eid])
again = R.reopen(copy.deepcopy(ran), [eid])
check("reopening blanks it and records what it was",
      "solution" not in next(x for x in again["entries"] if entry_id(x) == eid)
      and again["solutions"]["reopened"] == {eid: right})
# The burn reopens the committed file, the run's annotations discarded.
bare = copy.deepcopy(again)
for x in bare["entries"]:
    x.pop("annotation", None)
check("the reopened grid passes provenance", not provenance.check(bare))
refilled = copy.deepcopy(again)
next(x for x in refilled["entries"] if entry_id(x) == eid)["solution"] = right
check("an entry is reopened once only", R.reopenable(refilled) == [])
try:
    R.reopen(copy.deepcopy(ran), [p_eid])
    check("reopening a printed answer is refused", False)
except SystemExit:
    check("reopening a printed answer is refused", True)
check("nothing reopens on a published grid", R.reopenable({**ran, "solutions": {"origin": "published"}}) == [])
sys.exit(fails)
PY
rc=$?
[ $rc = 0 ] && echo "model_answers: all checks passed" || echo "model_answers: FAILED"
exit $rc
