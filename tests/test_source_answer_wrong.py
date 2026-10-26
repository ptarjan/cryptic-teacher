#!/usr/bin/env python3
# Does the corpus still hold the letters SOURCE_ANSWER_WRONG says it holds, and
# does the table still do anything?
#
#     python3 tests/test_source_answer_wrong.py
#
# fetch_puzzle.SOURCE_ANSWER_WRONG names answers the PAPER got wrong: cell (4,8)
# of cryptic 23,053, where the Guardian's own key holds T in both lights that
# cross there and its clues give R. Nothing else in this repo can notice that —
# the two lights agree with each other, so CROSS is silent, and both hold the
# letters their enumerations count, so LENGTH is silent — which is why the
# correction is a table and not a file edit: carry_recovered_clues carries clue
# text across a re-fetch and nothing carries a solution, so without the table one
# deliberate re-fetch would restore the paper's letter and no check would go red.
#
# Liveness — is the source STILL serving the wrong answer, or has the paper
# fixed it and left a stale key behind? — cannot be asked here. Nothing in this
# repo's tests touches the network (see .github/workflows/tests.yml), so it is
# asked at fetch time instead: correct_source_answers rewrites only an answer
# that arrives as the table's `served` value and prints a STALE warning for
# anything else, including the corrected value itself. That warning is the
# liveness check, and the fourth property below is the test of it. Last confirmed
# live by hand on 2026-09-18: /crosswords/prize/23053 serves GETSTEADY and
# XETOPHILY.
#
# What IS provable offline, and is proved here: every key names a real entry of
# a real puzzle whose stored answer is the corrected one; the table corrects
# something (served != corrected, same length, bare letters both); the
# correction actually happens on a page serving the wrong value; a page serving
# anything else is left alone and named; and — the reason the table exists —
# putting the paper's letters back into the stored puzzle leaves every corpus
# check silent.
import copy
import io
import os
import sys
from contextlib import redirect_stderr
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, str(REPO / "tools"))

import fetch_puzzle as fetcher
import provenance
import puzzle_integrity as pi
import validate_annotations as V
from groups import entry_id

fails = 0


def same(what, got, want):
    global fails
    if got == want:
        print(f"  ok: {what}")
    else:
        print(f"  FAIL: {what}\n    want {want}\n    got  {got}")
        fails += 1


print("every key names a real entry whose stored answer is the corrected one")
table = fetcher.SOURCE_ANSWER_WRONG
bad = []
for (pid, eid), (served, corrected, why) in table.items():
    path = fetcher.puzzle_paths.find(pid)
    if path is None:
        bad.append(f"{pid}: no such puzzle file")
        continue
    entry = {entry_id(e): e for e in fetcher.read_puzzle_file(path)["entries"]}.get(eid)
    if entry is None:
        bad.append(f"{pid} {eid}: no such entry")
        continue
    if entry.get("solution") != corrected:
        bad.append(f"{pid} {eid}: stored {entry.get('solution')!r}, table corrects "
                   f"to {corrected!r}")
    if served == corrected:
        bad.append(f"{pid} {eid}: corrects {served!r} to itself")
    if len(served) != len(corrected) or len(corrected) != entry["length"]:
        bad.append(f"{pid} {eid}: {served}/{corrected} against a light of "
                   f"{entry['length']}")
    if not (fetcher.is_bare_letters(served) and fetcher.is_bare_letters(corrected)):
        bad.append(f"{pid} {eid}: {served}/{corrected} is not bare letters")
    if len(why) < 40:
        bad.append(f"{pid} {eid}: the note is not evidence")
same("the table is not empty", "some" if table else "none", "some")
same("every entry checks out against the file on disk", "; ".join(bad) or "none", "none")

print("the correction happens, and only where the table says")


def entry(eid, solution):
    num, _, d = eid.partition("-")
    return {"number": int(num), "direction": d,
            "position": {"x": 0, "y": 0}, "length": len(solution or "") or 9,
            "clue": {"text": "As the page sends it", "enumeration": "9"}, "solution": solution}


# The page as the Guardian serves it today, plus two lights the table says
# nothing about: one in another puzzle under a name the table DOES hold, one
# in this puzzle under a name it does not.
served = [entry("18-across", "GETSTEADY"), entry("15-down", "XETOPHILY"),
          entry("1-across", "GETSTEADY")]
quiet = io.StringIO()
with redirect_stderr(quiet):
    fetcher.correct_source_answers("cryptic-23053", served)
    by = {entry_id(e): e["solution"] for e in served}

    other = [entry("18-across", "GETSTEADY")]
    fetcher.correct_source_answers("cryptic-30000", other)

    # A prize puzzle published without its key: nothing to correct and nothing to
    # complain about either.
    unsolved = [entry("18-across", None), entry("15-down", None)]
    fetcher.correct_source_answers("cryptic-23053", unsolved)
same("the wrong across answer is corrected", by["18-across"], "GETSREADY")
same("the wrong down answer is corrected", by["15-down"], "XEROPHILY")
same("a light the table does not name keeps the paper's answer", by["1-across"], "GETSTEADY")
same("another puzzle's same-named light is untouched", other[0]["solution"], "GETSTEADY")
same("an unpublished key is neither corrected nor complained about",
     f"{unsolved[0]['solution']} {unsolved[1]['solution']}", "None None")
same("and correcting a page the table describes says nothing on stderr",
     len(quiet.getvalue().splitlines()), 0)

print("staleness: a source that no longer serves the wrong answer is named, not overwritten")
stale_err = io.StringIO()
with redirect_stderr(stale_err):
    # The day the Guardian fixes its own key, the table has stopped describing the
    # source and must stop acting on it: overriding an answer nobody disputes is how
    # a correction outlives the error it was written for.
    fixed = [{"number": 18, "direction": "across", "length": 9, "solution": "GETSREADY"},
             {"number": 15, "direction": "down", "length": 9, "solution": "XEROPHILY"}]
    fetcher.correct_source_answers("cryptic-23053", fixed)

    # Or the page changes under the table some other way.
    changed = [{"number": 18, "direction": "across", "length": 9, "solution": "SOMETHING"},
               {"number": 15, "direction": "down", "length": 9, "solution": "SOMEOTHER"}]
    fetcher.correct_source_answers("cryptic-23053", changed)

    # Or the light the key names stops being in the puzzle at all.
    fetcher.correct_source_answers("cryptic-23053", [])
stale = stale_err.getvalue().splitlines()
same("the paper's own fix is kept as published", f"{fixed[0]['solution']} {fixed[1]['solution']}",
     "GETSREADY XEROPHILY")
same("an answer that changed some other way is kept too", changed[0]["solution"], "SOMETHING")
same("every stale case warns", sum("SOURCE_ANSWER_WRONG" in x for x in stale), 6)
same("and says which key to delete",
     sum(("delete the key" in x or "delete it" in x) for x in stale), 6)
same("a vanished entry is named too", sum("no such entry" in x for x in stale), 2)

print("why the table exists: the paper's letters break no corpus check at all")
today = datetime.now(timezone.utc).date()
puzzle = copy.deepcopy(pi.read_puzzle_file(pi.puzzle_paths.find("cryptic-23053")))
by_id = {entry_id(e): e for e in puzzle["entries"]}
for (pid, eid), (srv, corrected, _) in fetcher.SOURCE_ANSWER_WRONG.items():
    if pid == puzzle["id"]:
        assert by_id[eid]["solution"] == corrected, "fixture assumption broken"
        by_id[eid]["solution"] = srv

flags = []
checkable = pi.check_shape(puzzle, today, flags)
pi.check_length(puzzle, checkable, flags)
pi.check_grid(puzzle, flags)
pi.check_cross(puzzle, checkable, flags)
same("reverting to the served answers leaves every check silent", len(flags), 0)
# The two wrong lights cross at one cell and agree about it, which is exactly
# why no check can speak: it is the paper that is wrong, not the data.
same("because the two wrong lights agree about the cell they share",
     f"{by_id['18-across']['solution'][4]} {by_id['15-down']['solution'][2]}", "T T")

print("SOURCE_LIGHT_WRONG: the corpus holds every corrected light, and the served one is refused")
slw_err = io.StringIO()
table = fetcher.SOURCE_LIGHT_WRONG
bad, refused = [], 0
for pid in sorted({pid for pid, _ in table}):
    held = pi.read_puzzle_file(pi.puzzle_paths.find(pid))
    by_id = {entry_id(e): e for e in held["entries"]}
    srv = copy.deepcopy(held)
    served_by = {entry_id(e): e for e in srv["entries"]}
    for (tpid, eid), (was, now, why) in table.items():
        if tpid != pid:
            continue
        if eid not in by_id:
            bad.append(f"{pid} {eid}: no such entry")
            continue
        if {f: fetcher._light_field(by_id[eid], f) for f in now} != now:
            bad.append(f"{pid} {eid}: the file does not hold {now}")
        if set(was) != set(now) or was == now or len(why) < 40:
            bad.append(f"{pid} {eid}: corrects nothing, or says no why")
        for field, value in was.items():
            if field == "enumeration":
                served_by[eid]["clue"]["enumeration"] = value
            else:
                served_by[eid][field] = value
    # The page as served, corrected again, is the file on disk.
    again = copy.deepcopy(srv)
    with redirect_stderr(slw_err):
        fetcher.correct_source_lights(pid, again["entries"])
    if again["entries"] != held["entries"]:
        bad.append(f"{pid}: correcting the served page does not give the file")
    try:
        pi.refuse_bad_write(srv)
    except pi.RefusedWrite:
        refused += 1

# A page since fixed is named, not rewritten.
fixed = [{"number": 11, "direction": "across", "position": {"x": 0, "y": 3},
          "length": 7, "clue": {}, "solution": "HANDLED"}]
with redirect_stderr(slw_err):
    fetcher.correct_source_lights("cryptic-21730", fixed)
same("every key holds on disk and corrects something", "; ".join(bad) or "none", "none")
same("the page as served is refused by the writer, every puzzle",
     refused == len({pid for pid, _ in table}), True)
same("a page that fixed itself is kept as published", fixed[0]["position"]["y"], 3)
same("and named as stale",
     sum("SOURCE_LIGHT_WRONG cryptic-21730 11-across is STALE" in x
         for x in slw_err.getvalue().splitlines()), 1)

print("every SOURCE_CLUE_WRONG key holds its printed clue on disk")
bad = []
for (pid, eid), (served_clue, printed, why) in fetcher.SOURCE_CLUE_WRONG.items():
    path = fetcher.puzzle_paths.find(pid)
    ent = path and {entry_id(e): e for e in fetcher.read_puzzle_file(path)["entries"]}.get(eid)
    if not ent:
        bad.append(f"{pid} {eid}: no such entry")
    elif fetcher.clue_words(ent["clue"].get("text")) != fetcher.clue_words(printed):
        bad.append(f"{pid} {eid}: stored {ent['clue'].get('text')!r}, table prints {printed!r}")
    # Compared as text: a stray full stop OCR put in a clue is worth mending.
    # One rule with the filer: the text changes, and the note is evidence.
    for problem in V.clue_row_problems(served_clue, printed, why):
        bad.append(f"{pid} {eid}: {problem}")
    # An OCR'd clue's correction mends a misread, never rewords the clue,
    # unless it was read off the scan.
    puz = path and fetcher.read_puzzle_file(path)
    if puz and puz["source"].get("retrievedFrom") in provenance.OCR_CHANNELS and \
            not why.startswith(V.SCAN_READ) and \
            V.ocr_misread_edits(served_clue, printed) > V.OCR_MISREAD_EDITS:
        bad.append(f"{pid} {eid}: an OCR clue reworded, not a misread mended")
same("every clue key holds on disk and corrects something", "; ".join(bad) or "none", "none")

print("source_answer_wrong: all checks passed" if not fails
      else f"source_answer_wrong: {fails} FAILED")
sys.exit(1 if fails else 0)
