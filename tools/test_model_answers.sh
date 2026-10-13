#!/bin/bash
# A model-solved grid's answers can be corrected by the annotator, or sent back
# to be solved again, but never so that a crossing or a printed answer breaks.
#
#     bash tools/test_model_answers.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
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

def attempt(puzzle, eid, answer, parse=None):
    """apply() with every key null but `eid`, whose clue is `parse` (the
    model's `def`, `wp`, `notes`) with `answer`; the write captured."""
    wrote = {}
    real = A.write_puzzle_file
    A.write_puzzle_file = lambda p, pz: wrote.setdefault("puzzle", pz)
    A.read_puzzle_file = lambda p: copy.deepcopy(puzzle)
    try:
        anns = {entry_id(e): None for e in puzzle["entries"]}
        anns[eid] = {**(parse or {}), "answer": answer}
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
# The frozen fixture's free cell is 1-down's: "Ripostes appear to surmount defence" (4-5).
parse = {"1-down": {"def": "Ripostes", "wp": "[appear]COME +<to surmount> [defence]BACKS",
                    "notes": {"appear": "to come is to appear", "to surmount": "in a down clue, to go on top",
                              "defence": "a team's backs are its defence"}}}[eid]
out, err = attempt(wrong, eid, right, parse)
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
def hint(x):
    """A stored annotation for any clue: its first word and the rest as a double definition."""
    t = x["clue"]["text"]
    i = t.index(" ")
    return {"definitions": [{"text": t[:i], "at": 0}, {"text": t[i + 1:], "at": i + 1}]}
ran = copy.deepcopy(base)
for x in ran["entries"]:
    # A clue the scan lost (2-down) has no words to annotate.
    if entry_id(x) not in (eid, p_eid) and not x["clue"].get("missing"):
        x["annotation"] = hint(x)
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
# The run's hints for every other clue go in with the reopen, when they validate.
ran["annotatedBy"] = ["claude-opus-5-5"]
kept = R.with_runs_hints(same, ran, [eid])
check("the run's other hints are kept on the reopened grid, the reopened light's not",
      all(x.get("annotation") == y.get("annotation") for x, y in zip(kept["entries"], ran["entries"])
          if entry_id(x) != eid)
      and "annotation" not in next(x for x in kept["entries"] if entry_id(x) == eid)
      and kept["annotatedBy"] == ["claude-opus-5-5"])
import validate_annotations as V0
real_run_errors = V0.run_errors
try:
    V0.run_errors = lambda path, pz: []
    check("hints that validate are kept", R.hinted_if_valid(path, same, ran, [eid]) is not None)
    V0.run_errors = lambda path, pz: ["7A: something"]
    check("hints that do not validate are all dropped", R.hinted_if_valid(path, same, ran, [eid]) is None)
    # One clue's error costs only that clue's hint (nation-3405, 10-12).
    x = next(e for e in ran["entries"] if entry_id(e) not in (eid, p_eid) and not e.get("group"))
    x_eid, x_tag = entry_id(x), f"{x['number']}{'A' if x['direction'] == 'across' else 'D'}"
    calls = []
    V0.run_errors = lambda path, pz: calls.append(1) or ([f"{x_tag}: bad parse"] if len(calls) == 1 else [])
    one = R.hinted_if_valid(path, same, ran, [eid])
    check("a named clue's error drops its hint and keeps the rest",
          one is not None and "annotation" not in next(e for e in one["entries"] if entry_id(e) == x_eid)
          and sum(1 for e in one["entries"] if e.get("annotation")) == sum(
              1 for e in kept["entries"] if e.get("annotation")) - 1)
    V0.run_errors = lambda path, pz: ["schema: $: keys in the wrong order"]
    check("an error naming no clue still keeps none", R.hinted_if_valid(path, same, ran, [eid]) is None)
finally:
    V0.run_errors = real_run_errors
# The kept file's keys are in the schema's order: annotatedBy added after
# entries failed the real check on key order alone, and every hint went
# (nation-3405, nation-3419, 10-12; the mocks above could not see it).
import puzzle_schema
check("the kept hints are in the schema's key order",
      list(kept) == list(puzzle_schema.order(kept))
      and not [e for e in V0.run_errors(path, kept) if e.startswith("schema: $: keys in the order")])

# Run 1 annotates X and it is committed; run 2 leaves X null. X keeps run 1's
# hint (nation-3405 22D, 10-12) — unless its answer or clue has changed since.
def reannotate(puzzle, committed_puzzle):
    wrote = {}
    real = (A.write_puzzle_file, A.read_puzzle_file, A.committed_entries)
    A.write_puzzle_file = lambda p, pz: wrote.setdefault("puzzle", pz)
    A.read_puzzle_file = lambda p: copy.deepcopy(puzzle)
    A.committed_entries = lambda p: {entry_id(e): copy.deepcopy(e) for e in committed_puzzle["entries"]}
    try:
        A.apply(path, {entry_id(e): None for e in puzzle["entries"]
                       if entry_id(e) not in groups_leader}, by="human")
    finally:
        A.write_puzzle_file, A.read_puzzle_file, A.committed_entries = real
    return {entry_id(e): e.get("annotation") for e in wrote["puzzle"]["entries"]}
import groups
groups_leader = groups.leader_of(kept["entries"])
run1 = copy.deepcopy(kept)
x_hint = next(e for e in run1["entries"] if entry_id(e) == x_eid)["annotation"]
after = reannotate(run1, run1)
check("a re-annotation's null keeps the committed hint", after[x_eid] == x_hint)
moved = copy.deepcopy(run1)
next(e for e in moved["entries"] if entry_id(e) == x_eid)["clue"]["text"] = "a clue since corrected (5)"
after = reannotate(run1, moved)
check("but not one whose clue changed since it was committed", after[x_eid] is None)
uncommitted = copy.deepcopy(run1)
for e in uncommitted["entries"]:
    e.pop("annotation", None)
after = reannotate(run1, uncommitted)
check("and a run may still null its own uncommitted hint", after[x_eid] is None)
# A reopened light without a hint is pending, then answers-only; any other blank still fails.
pending = copy.deepcopy(kept)
p_light = next(x for x in pending["entries"] if entry_id(x) == p_eid)
p_light["annotation"] = hint(p_light)
errs, warns = [], []
V0.check_every_clue_is_annotated(pending["entries"], errs, warns,
                                 reopened=pending["solutions"]["reopened"])
check("a reopened light awaiting its solve is a warning, not an error",
      not errs and any("sent back to be solved again" in w for w in warns))
next(x for x in pending["entries"] if entry_id(x) == eid)["solution"] = right
errs, warns = [], []
V0.check_every_clue_is_annotated(pending["entries"], errs, warns,
                                 reopened=pending["solutions"]["reopened"])
check("solved again and still unparsed, it ships with answers only",
      not errs and any("ships with answers only" in w for w in warns))
other = next(x for x in pending["entries"] if entry_id(x) not in (eid, p_eid)
             and x.get("annotation") and not x.get("group"))
other.pop("annotation")
errs, warns = [], []
V0.check_every_clue_is_annotated(pending["entries"], errs, warns,
                                 reopened=pending["solutions"]["reopened"])
check("a blank on any light not reopened still fails", len(errs) == 1)
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
            t = x["clue"]["text"]
            x["annotation"] = {"definitions": [{"text": t, "at": 0}],
                               "wordplay": {"op": "cryptic", "parts": [{"words": t, "at": 0}]},
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
