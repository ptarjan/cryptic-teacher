#!/bin/bash
# A puzzle that has hints and lacks some is annotated only where it lacks them.
#
#     bash tools/test_annotate_partial.sh
#
# A data fix clears the annotation on just the entries whose clue or answer
# changed. The run's copy of the puzzle (annotate_check.py --view) then lists
# those ids as `annotateOnly`, apply_annotations.py needs keys for them alone
# and refuses to change any other annotation, and a run that started on the
# whole puzzle stays on the whole puzzle.
set -uo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools python3 - <<'PY'
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
    check("view keeps the others' annotations as context",
          view["existingAnnotations"][c] == full[c])
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
    pid = "times-1"
    F.SOURCE_CLUE_WRONG[(pid, "3-across")] = ("", "Restored from the scan", "Scan reads: Restored from the scan (5)")
    check("a blank clue takes a row whose served text is empty",
          F.source_clue(pid, "3-across", "") == "Restored from the scan")
    check("and a served clue keeps its text against that row",
          F.source_clue(pid, "3-across", "Something served") == "Something served")
    F.SOURCE_CLUE_WRONG[(pid, "3-across")] = ("Somethin", "Something else", "OCR misread: test")
    check("a served opening still corrects", F.source_clue(pid, "3-across", "Something served") == "Something else")
    check("and a blank clue is not mistaken for that opening", F.source_clue(pid, "3-across", "") == "")
    del F.SOURCE_CLUE_WRONG[(pid, "3-across")]
finally:
    shutil.rmtree(tmp)
sys.exit(fails)
PY
rc=$?
[ $rc = 0 ] && echo "annotate_partial: all checks passed" || echo "annotate_partial: FAILED"
exit $rc
