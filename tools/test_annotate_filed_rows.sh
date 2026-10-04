#!/bin/bash
# annotate_check files a run's source corrections from the _ann file itself.
#
#     bash tools/test_annotate_filed_rows.sh
#
# An entry's `printedClue` becomes its tools/data/source_clue_wrong.json row and
# `setterError` its tools/data/setter_error.json row, each in key order, one row
# per line, and both leave the entry. A malformed one stops the check with the
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
    for name in ("source_clue_wrong", "setter_error"):
        shutil.copy(AC.DATA / f"{name}.json", data / f"{name}.json")
    src = F.puzzle_paths.find("times-18749")
    path = tmp / src.name
    shutil.copy(src, path)
    puzzle = F.read_puzzle_file(path)
    a, b = (entry_id(e) for e in puzzle["entries"][:2])
    shown = puzzle["entries"][0]["clue"]["text"]
    pending = A.default_input(path)
    pending.write_text(json.dumps({
        a: {"answer": "X", "printedClue": ["Printed words", "OCR misread: test"]},
        b: {"answer": "Y", "blocks": [{"clueFragment": "Father", "gives": "FR"},
                                      {"clueFragment": "like Uriah", "gives": "UMBLE"}],
            "setterError": ["FR UMBLE", "FUMBLER", "test"]}}))
    filed, err = AC.file_rows(path, pending, data)
    check("both fields are filed", err is None and sorted(filed) == sorted(
        [f"printedClue {a}", f"setterError {b}"]))
    clue_rows = json.loads((data / "source_clue_wrong.json").read_text())
    check("printedClue's row opens with the clue as shown",
          clue_rows[f"times-18749/{a}"] == [shown, "Printed words", "OCR misread: test"])
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
    ann[a]["printedClue"] = ["Printed words again", "OCR misread: test"]
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
finally:
    shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if fails else 0)
PY
