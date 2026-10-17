#!/usr/bin/env python3
# A puzzle that has hints and lacks some is annotated only where it lacks them.
#
#     python3 tools/test_annotate_partial.py
#
# A data fix clears the annotation on just the entries whose clue or answer
# changed. The run's copy of the puzzle (annotate_check.py --view) then lists
# those ids as `annotateOnly`, apply_annotations.py needs keys for them alone
# and refuses to change any other annotation, and a run that started on the
# whole puzzle stays on the whole puzzle.
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))

import copy, json, shutil, sys, tempfile
from pathlib import Path
import apply_annotations as A
import annotate_check as AC
import fetch_puzzle as F
import groups

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

tmp = Path(tempfile.mkdtemp())
A.TOOLS = tmp            # the view and the _ann file, away from the real tools/
import shape_queue; shape_queue.PATH = tmp / "none.json"   # not the live re-annotation list
try:
    for src in F.puzzle_files():
        puzzle = F.read_puzzle_file(src)
        cont = groups.leader_of(puzzle["entries"])
        clues = [e for e in puzzle["entries"] if groups.entry_id(e) not in cont]
        if len(clues) >= 6 and F.puzzle_is_annotated(puzzle) and all(e.get("annotation") for e in clues):
            break
    path = tmp / src.name
    shutil.copy(src, path)
    full = {groups.entry_id(e): e["annotation"] for e in clues}
    check("a fully annotated puzzle has no count", "unannotated" not in F.index_row(path))
    a, b, c = (groups.entry_id(e) for e in clues[:3])

    # A data fix cleared a and b.
    p = F.read_puzzle_file(path)
    for e in p["entries"]:
        if groups.entry_id(e) in (a, b):
            del e["annotation"]
    F.write_puzzle_file(path, p)
    before = {groups.entry_id(e): json.dumps(e.get("annotation"), sort_keys=True)
              for e in F.read_puzzle_file(path)["entries"]}

    row = F.index_row(path)
    check("index counts the missing clues", row.get("unannotated") == 2 and not row["annotated"])

    view = json.loads(AC.write_view(path).read_text())
    check("view names only the missing entries", view.get("annotateOnly") == [a, b])
    check("view drops the unlinked others' annotations", "existingAnnotations" not in view)
    check("view is a line per entry", len(view["entries"]) == len(F.read_puzzle_file(path)["entries"])
          and all(l.count(" | ") >= 3 for l in view["entries"]))
    check("view says no _ann file yet", view["annotationsFile"].startswith("no "))

    pending = A.default_input(path)
    pending.write_text(json.dumps({a: full[a]}))
    check("only the listed ids are filled in", AC.fill_missing(path, pending) == [b])
    A.apply(path, json.loads(pending.read_text()), by="human")
    after = {groups.entry_id(e): json.dumps(e.get("annotation"), sort_keys=True)
             for e in F.read_puzzle_file(path)["entries"]}
    check("the missing entry is written", json.loads(after[a]) == full[a])
    check("every other annotation is byte-identical",
          all(after[k] == before[k] for k in before if k != a))

    # The run's own work stays its to fix after the check rewrites the view.
    AC.write_view(path)
    check("the list survives the rewrite", json.loads(AC.view_path(path).read_text())["annotateOnly"] == [a, b])
    redo = copy.deepcopy(full[a]); redo["explanation"] = {**redo.get("explanation", {}), "walkthrough": "again"}
    A.apply(path, {a: redo, b: None}, by="human")
    check("a written entry can be rewritten", next(e for e in F.read_puzzle_file(path)["entries"]
                                                   if groups.entry_id(e) == a)["annotation"] == redo)

    changed = copy.deepcopy(full[c]); changed["explanation"] = {"walkthrough": "rewritten"}
    try:
        A.apply(path, {a: redo, b: None, c: changed}, by="human")
        check("changing a kept annotation is refused", False)
    except SystemExit as err:
        check("changing a kept annotation is refused", c in str(err) and "stay as they are" in str(err))
    A.apply(path, {a: redo, b: None, c: full[c]}, by="human")
    check("a kept annotation copied unchanged is accepted", True)

    # Another fix clears c mid-run: it joins the list rather than being frozen out.
    p = F.read_puzzle_file(path)
    del next(e for e in p["entries"] if groups.entry_id(e) == c)["annotation"]
    F.write_puzzle_file(path, p)
    AC.write_view(path)
    check("a newly cleared entry joins the list",
          json.loads(AC.view_path(path).read_text())["annotateOnly"] == [a, b, c])

    # A run that started on an unannotated puzzle stays on the whole puzzle.
    AC.view_path(path).unlink()
    p = F.read_puzzle_file(path)
    for e in p["entries"]:
        e.pop("annotation", None)
    F.write_puzzle_file(path, p)
    AC.write_view(path)
    check("a puzzle with no hints is annotated whole", "annotateOnly" not in json.loads(AC.view_path(path).read_text()))
    A.apply(path, {k: (full[k] if k == a else None) for k in full}, by="human")
    AC.write_view(path)
    check("and stays whole once it has some", "annotateOnly" not in json.loads(AC.view_path(path).read_text()))
    try:
        A.apply(path, {a: full[a]}, by="human")
        check("whole mode still needs every key", False)
    except SystemExit as err:
        check("whole mode still needs every key", "every entry needs a key" in str(err))
    # A clue OCR lost is the run's on an OCR'd puzzle: its scan may print
    # it, and a "" served row restores it; elsewhere a blank clue is the setter's.
    def entry(n, text, ann=None):
        e = {"number": n, "direction": "across", "length": 5, "position": {"x": 0, "y": n},
             "clue": {"text": text, "enumeration": "5"}}
        if ann:
            e["annotation"] = ann
        return e
    ents = [entry(1, "Fine words", {"x": 1}), entry(3, ""), entry(5, "Late ones")]
    check("an OCR'd puzzle's blank clue is written by the run",
          AC.to_write({"source": {"retrievedFrom": "newspaper"}, "entries": copy.deepcopy(ents)}, [])
          == ["3-across", "5-across"])
    check("a fetched puzzle's blank clue is not",
          AC.to_write({"source": {"retrievedFrom": "api"}, "entries": copy.deepcopy(ents)}, []) == ["5-across"])
    # The burn must not rewrite a fully hinted puzzle with nothing due (azed-2573,
    # b5320ba868): to_write says None (whole) for it, nothing_due says skip.
    done = [entry(1, "Fine words", {"x": 1}), entry(5, "Late ones", {"x": 2})]
    api = {"source": {"retrievedFrom": "api"}}
    check("a fully hinted puzzle with nothing listed has nothing due",
          AC.nothing_due({**api, "entries": copy.deepcopy(done)}))
    check("a puzzle missing a hint has work",
          not AC.nothing_due({**api, "entries": copy.deepcopy(done) + [entry(7, "More")]}))
    check("a puzzle with no hints at all has work",
          not AC.nothing_due({**api, "entries": [entry(1, "Fine words"), entry(5, "Late ones")]}))
    real_flagged, AC.shape_queue.flagged = AC.shape_queue.flagged, lambda p: {"5-across": "why"}
    check("a clue on the shape list is due",
          not AC.nothing_due({**api, "entries": copy.deepcopy(done)}))
    AC.shape_queue.flagged = real_flagged
    pid = "times-1"
    F.SOURCE_CLUE_WRONG[(pid, "3-across")] = ("","Restored from the scan", "Scan reads: Restored from the scan (5)")
    check("a blank clue takes a row whose served text is empty",
          F.source_clue(pid, "3-across", "") == "Restored from the scan")
    check("and a served clue keeps its text against that row",
          F.source_clue(pid, "3-across", "Something served") == "Something served")
    F.SOURCE_CLUE_WRONG[(pid, "3-across")] = ("Somethin", "Something else", "OCR misread: test")
    check("a served opening still corrects", F.source_clue(pid, "3-across", "Something served") == "Something else")
    check("and a blank clue is not mistaken for that opening", F.source_clue(pid, "3-across", "") == "")
    del F.SOURCE_CLUE_WRONG[(pid, "3-across")]

    # A write that changes an annotated clue's text (an OCR re-read, a
    # corroborated reading) keeps the annotation only on the same words, every
    # phrase it quotes still there. The case: ftcryptic-8476 7 down with page
    # debris "Jotter Pad" in its clue and a block quoting it. (Not the page's
    # "Jotter Pad 7": a clue number and text run in is refused at the write,
    # puzzle_integrity.check_new_bleed, and so is a run of spaces.)
    ft = tmp / "ftcryptic-8476.json"
    shutil.copy(F.puzzle_paths.find("ftcryptic-8476"), ft)
    def seven_down(p):
        return next(e for e in p["entries"] if groups.entry_id(e) == "7-down")
    held = F.read_puzzle_file(ft)
    debris = copy.deepcopy(seven_down(held))
    debris["clue"]["text"] = "Jotter Pad " + debris["clue"]["text"]
    plain = copy.deepcopy(debris["annotation"])
    debris["annotation"]["wordplay"] = {"op": "charade", "parts": [
        {"words": "Jotter Pad", "note": "page debris", "unchecked": True}, plain["wordplay"]]}
    held["entries"] = [debris if groups.entry_id(e) == "7-down" else e for e in held["entries"]]
    def rewrite(text, ann=None):
        ft.write_text(json.dumps(held, indent=1))
        p = F.read_puzzle_file(ft)
        seven_down(p)["clue"]["text"] = text
        if ann is not None:
            seven_down(p)["annotation"] = ann
        F.write_puzzle_file(ft, p)
        return F.read_puzzle_file(ft)
    clean = "Bring a well qualified person in with all speed"
    out = rewrite(clean)
    check("a carried annotation quoting words the new clue lacks is dropped",
          "annotation" not in seven_down(out))
    check("and only that entry's", sum("annotation" in e for e in out["entries"])
          == sum("annotation" in e for e in held["entries"]) - 1)
    out = rewrite("Jotter Pad Bring a well qualified person in, with all speed")
    check("a typography-only change that keeps every quoted phrase keeps it",
          seven_down(out).get("annotation", {}).get("wordplay") == debris["annotation"]["wordplay"])
    check("and its definition is placed again", seven_down(out)["annotation"]["definitions"][0]["at"] == 45)
    fresh = plain
    out = rewrite(clean, fresh)
    check("an annotation written for the new clue is kept",
          seven_down(out).get("annotation", {}).get("wordplay") == fresh["wordplay"])
finally:
    shutil.rmtree(tmp)
print("annotate_partial: all checks passed" if not fails else "annotate_partial: FAILED")
raise SystemExit(1 if fails else 0)
