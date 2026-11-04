#!/usr/bin/env python3
# A clue the run cannot annotate honestly costs that clue, not the puzzle.
#
#     python3 tests/test_annotate_withheld.py
#
# Until 11-04 the only way past check_every_clue_is_annotated for a clue cut
# short in the copy held, or one whose only parse has a word doing two jobs,
# was to withdraw the whole puzzle (46 that day, nearly all over one or two
# clues). Now the run writes {"withheld": "<why>"} for that clue: it lands as
# null with the reason on the entry, the rest of the puzzle ships, the queue
# does not retry the same text every night, and only a puzzle more than half
# withheld still fails.
import _path  # puts tools/ on sys.path
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import copy
import shutil
import tempfile
from pathlib import Path
import apply_annotations as A
import annotate_check as AC
import fetch_puzzle as F
import groups
import puzzle_schema
import shape_queue
import validate_annotations as V

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


def entry(eid, clue="Some words here (4)", sol="ABCD", **kw):
    num, _, d = eid.partition("-")
    return {"number": int(num), "direction": d, "clue": {"text": clue}, "solution": sol, **kw}


def stored():
    return {"definitions": [{"text": "Some", "at": 0}],
            "wordplay": {"words": "words here", "gives": "ABCD", "at": 5}}


def by_id(p):
    return {groups.entry_id(e): e for e in p["entries"]}


WHY = "15-down 'Stood before (9)' is cut short: no source gives the rest"

# The validator, on its own: one withheld clue is a warning naming it.
ids = [f"{n}-across" for n in range(1, 11)]
def puzzle_of(n_withheld):
    return [entry(eid) if i < n_withheld else entry(eid, annotation=stored())
            for i, eid in enumerate(ids)]
held = {eid: WHY for eid in ids}

errs, warns = [], []
V.check_every_clue_is_annotated(puzzle_of(1), errs, warns, withheld={ids[0]: WHY})
check("one withheld clue ships", not errs)
check("and is named with its reason", any(w.startswith("1A: withheld") and WHY in w for w in warns))

errs, warns = [], []
V.check_every_clue_is_annotated(puzzle_of(5), errs, warns, withheld=dict(list(held.items())[:5]))
check("half the puzzle withheld still ships", not errs)

errs, warns = [], []
V.check_every_clue_is_annotated(puzzle_of(6), errs, warns, withheld=dict(list(held.items())[:6]))
check("more than half withheld fails the puzzle",
      len(errs) == 1 and "withheld, 6 of 10" in errs[0] and "--withdraw" in errs[0])

errs, warns = [], []
V.check_every_clue_is_annotated(puzzle_of(6), errs, warns, withheld=dict(list(held.items())[:6]),
                                corpus=True)
check("the committed corpus is quiet about it", not errs and not any("withheld" in w for w in warns))

errs, warns = [], []
V.check_every_clue_is_annotated(puzzle_of(1), errs, warns)
check("a null without a reason is still the blank error",
      len(errs) == 1 and errs[0].startswith("1A: no annotation"))
check("which points at withholding the clue, not withdrawing the puzzle",
      '{"withheld"' in errs[0] and "--withdraw" not in errs[0])

# The prompt says the same thing the check does.
prompt = Path("tools/annotate_prompt.md").read_text(encoding="utf-8")
check("the prompt documents withheld", '{"withheld": "<the clue as held' in prompt)
check("the prompt withdraws only a puzzle more than half withheld",
      "more than half its clues\n  withheld" in prompt)

# End to end, on a copy of a real fully annotated puzzle.
tmp = Path(tempfile.mkdtemp())
A.TOOLS = tmp            # the view and the _ann file, away from the real tools/
shape_queue.PATH = tmp / "none.json"   # not the live re-annotation list
try:
    for src in F.puzzle_files():
        puzzle = F.read_puzzle_file(src)
        cont = groups.leader_of(puzzle["entries"])
        clues = [e for e in puzzle["entries"] if groups.entry_id(e) not in cont]
        if (len(clues) >= 6 and F.puzzle_is_annotated(puzzle) and all(e.get("annotation") for e in clues)
                and not groups.also_clues(puzzle["entries"]) and not groups.off_grid(puzzle)):
            break
    path = tmp / src.name
    shutil.copy(src, path)
    full = {groups.entry_id(e): e["annotation"] for e in clues}
    a = groups.entry_id(clues[0])

    try:
        A.apply(path, {**copy.deepcopy(full), a: {"withheld": "  "}}, by="human")
        check("a withheld clue needs its reason", False)
    except SystemExit as err:
        check("a withheld clue needs its reason", a in str(err) and "reason" in str(err))

    A.apply(path, {**copy.deepcopy(full), a: {"withheld": WHY}}, by="human")
    p = F.read_puzzle_file(path)
    e = by_id(p)[a]
    check("the withheld clue lands with no annotation", "annotation" not in e)
    check("and its reason and the clue it read on the entry",
          e.get(F.WITHHELD) == {"why": WHY, "clue": e["clue"]["text"]})
    check("the file still fits the schema", not puzzle_schema.validate(p))
    check("every other clue ships its hint",
          all(by_id(p)[k].get("annotation") == v for k, v in full.items() if k != a))
    check("the puzzle counts as annotated", F.puzzle_is_annotated(p) and F.withheld_clues(p) == {a: WHY})
    check("the queue does not retry it", a not in (AC.to_write(p, None) or []))
    check("a run that withheld it keeps it its own", a in AC.to_write(p, [a]))
    _, errs, warns = V.validate_puzzle(p)
    tag = f"{e['number']}{'A' if e['direction'] == 'across' else 'D'}"
    check("the validator does not call it blank", not any(x.startswith(f"{tag}: no annotation") for x in errs))
    check("it warns with the reason", any(w.startswith(f"{tag}: withheld") for w in warns))

    # A --patch onto a written clue withholds it too: the withheld field wins.
    A.apply(path, {**copy.deepcopy(full), a: {**copy.deepcopy(full[a]), "withheld": WHY}}, by="human")
    check("withheld beside other fields still withholds",
          "annotation" not in by_id(F.read_puzzle_file(path))[a])

    # The clue mended (a re-read, a source_clue_wrong row): the record lapses.
    p = F.read_puzzle_file(path)
    by_id(p)[a]["clue"]["text"] += " mended"
    check("a mended clue is due again", not F.withheld_stands(by_id(p)[a])
          and a in [groups.entry_id(x) for x in F.unannotated_clues(p)] and not F.withheld_clues(p))

    # Annotated later: the record goes.
    A.apply(path, copy.deepcopy(full), by="human")
    e = by_id(F.read_puzzle_file(path))[a]
    check("annotating it drops the record", e.get("annotation") == full[a] and F.WITHHELD not in e)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

sys.exit(1 if fails else 0)
