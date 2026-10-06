#!/bin/bash
# Does a puzzle held as its clues alone become a grid puzzle once answered,
# and can nothing in between be written?
#
#     bash tools/test_clues_only.sh
#
# A solved book puzzle from the corpus (book-8001) is stripped to its clues in
# printed order (no numbers, no positions, no answers) and written to a scratch
# clues_only/. tools/apply_solution.py is then given its answers in clue order:
# the grid it derives must be the published one, numbered the same, filed in
# the scratch puzzles/, and the clues-only copy gone. The refusals: a light
# carrying a number, position or answer; an unknown filer; an id already held
# with its grid; a fill that no grid holds.
set -u
cd "$(dirname "$0")/.." || exit 1

python3 - <<'EOF'
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "tools")
import apply_solution
import clues_only
import puzzle_integrity
import puzzle_paths
from groups import entry_id
from reconstruct_grid import grid_of

fails = []
source = json.loads(puzzle_paths.find("book-8001").read_text())


def stripped(puzzle):
    lights = {}
    for d in clues_only.DIRECTIONS:
        es = sorted((e for e in puzzle["entries"] if e["direction"] == d),
                    key=lambda e: e["number"])
        lights[d] = [{"clue": e["clue"], "length": e["length"]} for e in es]
    return {"id": puzzle["id"], "number": puzzle["number"], "series": puzzle["series"],
            "name": puzzle["name"], "year": puzzle["year"],
            "dimensions": puzzle["dimensions"],
            "source": {"url": puzzle["source"]["url"],
                       "acquiredBy": "tools/acquire_book.py", "acquiredOn": "2026-10-06"},
            "clues": lights}


def answers(puzzle):
    """The published answers as a solver's fill: in clue order, each with a
    definition (the annotation's, else the clue's first word)."""
    def one(e):
        defs = (e.get("annotation") or {}).get("definitions") or []
        word = defs[0]["text"] if defs else e["clue"]["text"].split()[0].strip(",.;:!?")
        return {"answer": e["solution"], "definition": word}
    return {d: [one(e) for e in sorted(
        (e for e in puzzle["entries"] if e["direction"] == d), key=lambda e: e["number"])]
        for d in clues_only.DIRECTIONS}


def refused(record, why):
    try:
        clues_only.write(record)
    except puzzle_integrity.RefusedWrite:
        return
    fails.append(f"a clues-only record with {why} was written")


def apply(pid, fill, scratch, check_only=False):
    path = Path(scratch) / "fill.json"
    path.write_text(json.dumps(fill))
    sys.argv = ["apply_solution.py", pid, "--fill", str(path), "--model", "test",
                "--no-reindex"] + (["--check-only"] if check_only else [])
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            apply_solution.main()
    except SystemExit as err:
        return err.code or 0, out.getvalue()
    return 0, out.getvalue()


with tempfile.TemporaryDirectory() as scratch:
    puzzle_paths.PUZZLE_DIR = Path(scratch) / "puzzles"
    clues_only.DIR = Path(scratch) / "clues_only"
    record = stripped(source)
    path = clues_only.write(record)

    # The half states the schema has no room for.
    for key, value in (("number", 1), ("position", {"x": 0, "y": 0}), ("solution", "X")):
        bad = json.loads(json.dumps(record))
        bad["clues"]["across"][0][key] = value
        refused(bad, f"a light's {key}")
    refused({**record, "entries": [{"number": 1}]}, "an entries list")
    refused({**record, "source": {**record["source"], "acquiredBy": "tools/fetch_puzzle.py"}},
            "a filer with no builder")

    # A wrong answer: no grid holds it, nothing is written.
    wrong = answers(source)
    wrong["across"][0] = {"answer": "Q" * len(wrong["across"][0]["answer"]),
                      "definition": wrong["across"][0]["definition"]}
    code, said = apply("book-8001", wrong, scratch)
    if code == 0 or not path.exists() or any(puzzle_paths.PUZZLE_DIR.rglob("*.json")):
        fails.append(f"a fill no grid holds was applied: {said}")

    code, said = apply("book-8001", answers(source), scratch)
    if code != 0:
        fails.append(f"the right answers were refused: {said}")
    else:
        filed = puzzle_paths.find("book-8001")
        got = json.loads(filed.read_text()) if filed else None
        if got is None:
            fails.append("nothing filed in puzzles/")
        else:
            if grid_of(got) != grid_of(source):
                fails.append("the derived grid is not the published one")
            want = {entry_id(e): e["solution"] for e in source["entries"]}
            have = {entry_id(e): e.get("solution") for e in got["entries"]}
            if have != want:
                fails.append("numbering or answers differ from the published puzzle")
            if got["source"].get("gridOrigin") != "reconstructed":
                fails.append(f"gridOrigin is {got['source'].get('gridOrigin')}")
        if path.exists():
            fails.append("the clues-only copy outlived its grid puzzle")
        # One id, one state.
        refused(record, "an id already filed with its grid")

if fails:
    print("FAIL test_clues_only:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok test_clues_only: clues-only book-8001 promoted to its published grid; "
      "half states refused")
EOF
