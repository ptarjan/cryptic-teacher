#!/bin/bash
# annotate_check files a run's source corrections from the _ann file itself.
#
#     bash tools/test_annotate_filed_rows.sh
#
# An entry's `printedClue` becomes its tools/data/source_clue_wrong.json row and
# `setterError` its tools/data/setter_error.json row, each in key order, one row
# per line, and both leave the entry. `answerTypo` files a
# tools/data/source_answer_wrong.json row and puts its letters in the grid,
# refused when it is the wrong length, rewrites more than a slip, changes a cell
# a crossing answer contradicts, or names a model's fill. A malformed one stops the check with the
# shape to write. The run's view of an OCR'd, model-solved puzzle carries
# `source.retrievedFrom` and the grid, so neither is read off the puzzle file.
set -uo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools python3 - <<'PY'
import json, shutil, sys, tempfile
from pathlib import Path
import apply_annotations as A
import annotate_check as AC
import fetch_puzzle as F
import validate_annotations as V
from groups import entry_id

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

tmp = Path(tempfile.mkdtemp())
A.TOOLS = tmp
data = tmp / "data"
data.mkdir()
try:
    for name in ("source_clue_wrong", "setter_error", "source_answer_wrong"):
        shutil.copy(AC.DATA / f"{name}.json", data / f"{name}.json")
    src = F.puzzle_paths.find("times-18749")
    path = tmp / src.name
    shutil.copy(src, path)
    puzzle = F.read_puzzle_file(path)
    a, b = (entry_id(e) for e in puzzle["entries"][:2])
    shown = puzzle["entries"][0]["clue"]["text"]
    pending = A.default_input(path)
    pending.write_text(json.dumps({
        a: {"answer": "X", "printedClue": ["Printed words", "OCR misread: the OCR read test words"]},
        b: {"answer": "Y", "blocks": [{"clueFragment": "Father", "gives": "FR"},
                                      {"clueFragment": "like Uriah", "gives": "UMBLE"}],
            "setterError": ["FR UMBLE", "FUMBLER", "test"]}}))
    filed, err = AC.file_rows(path, pending, data)
    check("both fields are filed", err is None and sorted(filed) == sorted(
        [f"printedClue {a}", f"setterError {b}"]))
    clue_rows = json.loads((data / "source_clue_wrong.json").read_text())
    check("printedClue's row opens with the clue as shown",
          clue_rows[f"times-18749/{a}"] == [shown, "Printed words", "OCR misread: the OCR read test words"])
    check("setterError's row is as given",
          json.loads((data / "setter_error.json").read_text())[f"times-18749/{b}"]
          == ["FR UMBLE", "FUMBLER", "test"])
    text = (data / "source_clue_wrong.json").read_text()
    keys = [l.split('"')[1] for l in text.splitlines()[1:-1]]
    check("the table stays one sorted row per line", keys == sorted(keys) and len(keys) == len(clue_rows))
    ann = json.loads(pending.read_text())
    check("the fields leave the entries", "printedClue" not in ann[a] and "setterError" not in ann[b])
    check("this process sees the rows", F.corrected_clue("times-18749", a) == "Printed words"
          and V.SETTER_ERROR[("times-18749", b)][1] == "FUMBLER")

    # A re-run keeps what the source served, not the mended text.
    ann[a]["printedClue"] = ["Printed words again", "OCR misread: the OCR read test words"]
    pending.write_text(json.dumps(ann))
    AC.file_rows(path, pending, data)
    check("a re-filed row keeps the clue as shown",
          json.loads((data / "source_clue_wrong.json").read_text())[f"times-18749/{a}"][0] == shown)

    ann = json.loads(pending.read_text())
    ann[a]["printedClue"] = "Printed words"
    pending.write_text(json.dumps(ann))
    filed, err = AC.file_rows(path, pending, data)
    check("a bare string stops with the shape to write",
          not filed and err and "printedClue must be" in err and "<evidence>" in err)

    ann = json.loads(pending.read_text())
    ann[a].pop("printedClue", None)
    ann[b]["setterError"] = ["taunt", "UNANT", "test"]
    pending.write_text(json.dumps(ann))
    before = (data / "setter_error.json").read_text()
    filed, err = AC.file_rows(path, pending, data)
    check("a setterError no shape fits stops with what to write, and files nothing",
          not filed and err and "neither words the clue" in err and "FUMBLER" in err
          and (data / "setter_error.json").read_text() == before)
    del ann[b]["setterError"]
    pending.write_text(json.dumps(ann))

    view = json.loads(AC.write_view(path).read_text())
    check("the view says where the clues came from",
          view.get("source") == {"retrievedFrom": puzzle["source"]["retrievedFrom"]})
    grid = AC.grid_rows(puzzle)
    across = next(e for e in puzzle["entries"] if e["direction"] == "across")
    x, y = across["position"]["x"], across["position"]["y"]
    check("the grid holds the answers where they sit",
          grid[y][x:x + across["length"]] == across["solution"].replace(" ", "").replace("-", "").upper()
          and len(grid) == puzzle["dimensions"]["rows"])

    # The key's misprint: cryptic-22049 15D printed MINISCULE for MINUSCULE,
    # its fourth cell unchecked. Unfiled here, so the file is as the paper served it.
    rows = json.loads((data / "source_answer_wrong.json").read_text())
    rows.pop("cryptic-22049/15-down", None)
    (data / "source_answer_wrong.json").write_text(AC.dump_lines(rows))
    F.SOURCE_ANSWER_WRONG.pop(("cryptic-22049", "15-down"), None)
    src = F.puzzle_paths.find("cryptic-22049")
    path = tmp / src.name
    puzzle = F.read_puzzle_file(src)
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    by_id["15-down"]["solution"] = "MINISCULE"
    F.write_puzzle_file(path, puzzle)
    pending = A.default_input(path)
    crossing = by_id["14-across"]["solution"]
    def typo(letters):
        pending.write_text(json.dumps({"15-down": {"answer": "MINUSCULE",
                                                   "answerTypo": [letters, "the wordplay"]}}))
        before = (data / "source_answer_wrong.json").read_text()
        filed, err = AC.file_rows(path, pending, data)
        return filed, err, (data / "source_answer_wrong.json").read_text() == before
    filed, err, same = typo("MINUSCULES")
    check("an answerTypo of another length is refused", not filed and same and "letters" in err)
    filed, err, same = typo("MANASCALE")
    check("an answerTypo rewriting more than a slip is refused",
          not filed and same and "at most 2" in err)
    wrong = "AINISCULE" if crossing[0] != "A" else "BINISCULE"
    filed, err, same = typo(wrong)
    check("an answerTypo a crossing contradicts is refused",
          not filed and same and "crossing 14-across" in err)
    filed, err, same = typo("minuscule")
    check("an answerTypo is filed", err is None and filed == ["answerTypo 15-down"])
    check("its row is [printed, corrected, evidence]",
          json.loads((data / "source_answer_wrong.json").read_text())["cryptic-22049/15-down"]
          == ["MINISCULE", "MINUSCULE", "the wordplay"]
          and F.SOURCE_ANSWER_WRONG[("cryptic-22049", "15-down")][:2] == ("MINISCULE", "MINUSCULE"))
    check("the grid carries the corrected letters, and the field leaves the entry",
          {entry_id(e): e for e in F.read_puzzle_file(path)["entries"]}["15-down"]["solution"]
          == "MINUSCULE" and "answerTypo" not in json.loads(pending.read_text())["15-down"])
    filed, err, _ = typo("MINUSCULE")
    check("a re-filed answerTypo keeps what the paper printed", err is None and json.loads(
        (data / "source_answer_wrong.json").read_text())["cryptic-22049/15-down"][0] == "MINISCULE")

    # times-18749's grid is a model's solve: no answer in it is the paper's.
    path = tmp / "times-18749.json"
    pending = A.default_input(path)
    pending.write_text(json.dumps({"1-down": {"answerTypo": ["FUMBLES", "test"]}}))
    filed, err = AC.file_rows(path, pending, data)
    check("an answerTypo on a model's fill is refused", not filed and "never printed" in err)

    # A filed row its OCR'd file does not hold fails validation, so a write
    # that never mended the clue (hints that did not land) cannot commit.
    F.SOURCE_CLUE_WRONG[("times-18749", a)] = (shown, "Printed words", "test")
    held = F.read_puzzle_file(F.puzzle_paths.find("times-18749"))
    errs = []
    V.check_clue_rows_held(held, errs)
    check("a row the file does not hold is an error", len(errs) == 1 and errs[0].startswith(f"{a}:"))
    A.mend_clues(held)
    errs = []
    V.check_clue_rows_held(held, errs)
    check("and holding it is clean", errs == [])

    # A row that gives a blank OCR'd clue its words takes its missing mark off.
    blank = {"id": "times-18749", "entries": [
        {"number": 1, "direction": "down", "clue": {"text": "", "missing": True, "missingNote": "n"}}]}
    F.SOURCE_CLUE_WRONG[("times-18749", "1-down")] = ("", "Restored words", "test")
    A.mend_clues(blank)
    check("a restored blank clue is no longer missing",
          blank["entries"][0]["clue"] == {"text": "Restored words"})
finally:
    shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if fails else 0)
PY
