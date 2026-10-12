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

# A frozen copy of times-17379 as the model first solved it (13 printed answers, one
# reopened): the live file moves with every annotation, correction and re-OCR pass.
from pathlib import Path
path = Path("tools/fixtures/times-17379-model-solved.json")
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
done = base["solutions"].get("reopened") or {}
model = [e for e in base["entries"] if entry_id(e) not in printed and not e.get("group")
         and e.get("solution") and entry_id(e) not in done]
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
      and again["solutions"]["reopened"] == {**done, eid: right})
# The burn reopens the committed file, the run's annotations discarded.
bare = copy.deepcopy(again)
for x in bare["entries"]:
    x.pop("annotation", None)
check("the reopened grid passes provenance", not provenance.check(bare))
refilled = copy.deepcopy(again)
next(x for x in refilled["entries"] if entry_id(x) == eid)["solution"] = right
check("an entry is reopened once only", R.reopenable(refilled) == [])
# Solved and hinted in one run: the committed file has no answers to blank.
unsolved = copy.deepcopy(bare)
for x in unsolved["entries"]:
    x.pop("solution", None)
unsolved["solutions"] = {"origin": "unsolved"}
same = R.reopen(copy.deepcopy(unsolved), [eid], ran=copy.deepcopy(ran))
check("a same-run solve reopens from the run's copy, without its annotations",
      "solution" not in next(x for x in same["entries"] if entry_id(x) == eid)
      and same["solutions"]["reopened"] == {**done, eid: right}
      and not any("annotation" in x for x in same["entries"])
      and not provenance.check(same))
try:
    R.reopen(copy.deepcopy(ran), [p_eid])
    check("reopening a printed answer is refused", False)
except SystemExit:
    check("reopening a printed answer is refused", True)
check("nothing reopens on a published grid", R.reopenable({**ran, "solutions": {"origin": "published"}}) == [])

# --- an answer its own annotation doubts (what the official keys overturned) ---
import validate_annotations as V, puzzle_integrity as PI
def annotated_as(puzzle, eid, walkthrough, fit="A plain sense."):
    out = copy.deepcopy(puzzle)
    for x in out["entries"]:
        if entry_id(x) == eid:
            x["annotation"] = {"type": ["cryptic_definition"], "answer": x["solution"],
                               "definitions": [], "blocks": [],
                               "explanation": {"walkthrough": walkthrough, "definitionFit": fit}}
    return out
d_eid = entry_id(model[0])
# listener-3 40D and 6D, as annotated before the archive's key overturned them.
sla = annotated_as(base, d_eid, "UNRESOLVED: the crossings give S then L, with the last cell "
                   "unchecked. This fill is a placeholder until the published solution corrects it.")
check("an UNRESOLVED placeholder hint marks the model answer doubted", d_eid in V.doubted_model_answers(sla))
word = model[0]["solution"]
twin = word[:-1] + ("Q" if word[-1] != "Q" else "Z")
variant = annotated_as(base, d_eid, f"Usually spelt {twin.title()}; the region is the coastal plain.")
check("a hint naming a one-letter-off usual spelling marks it doubted", d_eid in V.doubted_model_answers(variant))
for prose in ("A traditional story, often historically unverified, is a myth.",
              "Plans undecided are said to be hanging in this unresolved state.",
              "Kiev, now usually spelt Kyiv, is the capital of Ukraine."):
    check(f"a definition about doubt is not doubt: {prose[:30]!r}",
          d_eid not in V.doubted_model_answers(annotated_as(base, d_eid, prose)))
errors, warnings = [], []
V.check_model_answer_doubted(sla, errors, warnings)
check("a doubted model answer is an error in the run's validation", len(errors) == 1 and not warnings)
errors, warnings = [], []
V.check_model_answer_doubted(sla, errors, warnings, corpus=True)
check("and a warning in a corpus run", not errors and len(warnings) == 1)
check("a published grid's hint is never a model doubt",
      V.doubted_model_answers({**sla, "solutions": {"origin": "published"}}) == {})
settled = copy.deepcopy(sla)
settled["solutions"]["graded"] = {d_eid: "test"}
check("a light a key already graded is not doubted again", d_eid not in V.doubted_model_answers(settled))
check("a doubted answer is reopenable, like a null", d_eid in R.reopenable(sla))
back = R.reopen(copy.deepcopy(sla), [d_eid])
light = next(x for x in back["entries"] if entry_id(x) == d_eid)
check("reopening it blanks the answer and drops the hedged hint",
      "solution" not in light and "annotation" not in light and back["solutions"]["reopened"][d_eid] == word)
check("once reopened it is no longer doubted (a second solve's word stands)",
      d_eid not in V.doubted_model_answers({**sla, "solutions": back["solutions"]}))

# --- a key over a cold solve must grade it ---
keyed = copy.deepcopy(sla)
keyed["solutions"] = {"origin": "published", "previousOrigin": "model"}
next(x for x in keyed["entries"] if entry_id(x) == d_eid)["solution"] = twin
real_misses = V.blind_misses
try:
    V.blind_misses = lambda pid: {}
    flags = []
    PI.check_key_grades_model(sla, keyed, flags)
    check("a key overturning a model answer without grading it is refused",
          [f[0] for f in flags] == ["UNGRADED"] and d_eid in flags[0][2])
    recorded = []
    real_record = fetch_puzzle.record_misses
    fetch_puzzle.record_misses = lambda pid, wrong, marked=None: recorded.extend(wrong)
    try:
        fetch_puzzle.grade_model_fill(keyed, provenance.model_answers(sla))
    finally:
        fetch_puzzle.record_misses = real_record
    check("grade_model_fill records the miss and drops the old hint",
          recorded == [(d_eid, word, twin)]
          and "annotation" not in next(x for x in keyed["entries"] if entry_id(x) == d_eid))
    V.blind_misses = lambda pid: {d_eid: word}
    flags = []
    PI.check_key_grades_model(sla, keyed, flags)
    check("once graded the write is let through", flags == [])
    agree = copy.deepcopy(sla)
    agree["solutions"] = {"origin": "published", "previousOrigin": "model"}
    V.blind_misses = lambda pid: {}
    flags = []
    PI.check_key_grades_model(sla, agree, flags)
    check("a key that agrees with the model needs no miss", flags == [])
finally:
    V.blind_misses = real_misses
# --- a jigsaw run's answers go back in printed order (genius-234, 10-12) ---
import puzzle_paths
jig = fetch_puzzle.read_puzzle_file(puzzle_paths.find("genius-250"))
printed_order = list(reversed([{"clue": e["clue"]} for e in jig["entries"]]))
got = R.jigsaw_answers({"clues": {"unplaced": printed_order}}, jig)["unplaced"]
check("a jigsaw's answers are found by clue text, in the printed order",
      got == [e["solution"] for e in reversed(jig["entries"])])
sys.exit(fails)
PY
rc=$?
[ $rc = 0 ] && echo "model_answers: all checks passed" || echo "model_answers: FAILED"
exit $rc
