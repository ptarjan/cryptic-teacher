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
# carrying a number, position or answer; an unknown filer; a grid kind with no
# builder (a Listener book's barred grid), which no solve queue takes either;
# an id already held with its grid; a fill that no grid holds.
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
import fetch_puzzle
import puzzle_integrity
import puzzle_paths
from groups import entry_id
from reconstruct_grid import grid_of

fails = []
source = fetch_puzzle.read_puzzle_view(puzzle_paths.find("book-8001"))


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
    # A Listener book's grid is barred, and no builder places bars: refused
    # when filed, and no solve queue takes one already held.
    barred = {**record, "id": "book-31039", "number": 31039}
    refused(barred, "a barred grid kind")
    held = clues_only.path_for("book-31039")
    held.write_text(json.dumps(barred))
    if [r["id"] for r in clues_only.solvable()] != ["book-8001"]:
        fails.append(f"solvable() = {[r['id'] for r in clues_only.solvable()]}, "
                     f"want only book-8001: a barred record would be queued")
    held.unlink()

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

# A book jigsaw: one clue list under "Method:", no numbers, no across or
# down. The parser keeps the instruction as its preamble, acquire_book holds
# it clues-only as `unplaced` with `cluesUnplaced`, and the solve queue takes it.
import acquire_book
import parse_penguin_book
import puzzle_schema
leaf = ("17\n\nMethod: Solve the clues and fit the solutions into the diagram jigsaw-\n"
        "wise, wherever they will go.\n\n"
        + "".join(f"Clue number {w} for the jigsaw here ({n})\n\n" for w, n in
                  zip("one two three four five six seven eight nine ten eleven twelve "
                      "thirteen".split(), [5, 7, 4, 6, 8, 5, 3, 9, 6, 7, 4, 5, 6])))
jig = parse_penguin_book.build_puzzle(28, 0, [], [leaf])
want = "Solve the clues and fit the solutions into the diagram jigsaw-wise, wherever they will go."
if jig.get("mode") != "jigsaw" or jig.get("preamble") != want or len(jig.get("clues") or []) != 13:
    fails.append(f"the Method: leaf parsed as {jig.get('mode')}, preamble "
                 f"{jig.get('preamble')!r}, {len(jig.get('clues') or [])} clues")
if not acquire_book.is_jigsaw(jig) or acquire_book.is_jigsaw({**jig, "preamble": None}):
    fails.append("is_jigsaw: a Method: list is one, a guessed list without the line is not")
with tempfile.TemporaryDirectory() as scratch:
    root = Path(scratch)
    row = acquire_book.file_jigsaw(jig, "isbn_9780140277500", root)
    held = clues_only.files(root)
    rec = json.loads(held[0].read_text()) if held else {}
    if row.get("status") != "held-clues-only-jigsaw" or len(held) != 1:
        fails.append(f"the jigsaw was not held clues-only: {row}")
    elif not (rec.get("cluesUnplaced") is True and rec.get("preamble") == want
              and len(rec["clues"].get("unplaced", [])) == 13 and "across" not in rec["clues"]
              and rec["clues"]["unplaced"][0] == {"clue": {"text": "Clue number one for the jigsaw here",
                                                            "enumeration": "5"}, "length": 5}):
        fails.append(f"the held jigsaw is shaped {json.dumps(rec)[:300]}")
    if rec and (puzzle_schema.validate_clues_only(rec)
                or clues_only.builder(rec) is not clues_only._jigsaw_build
                or [r["id"] for r in clues_only.solvable(root)] != [rec["id"]]):
        fails.append("a held jigsaw breaks the schema, or the jigsaw builder or queue "
                     "does not take it (tools/test_jigsaw.sh files one)")
    bad = {**jig, "clues": jig["clues"][:-1] + [{"number": None, "clue": "Wqxzt brlk", "enumeration": "5"}]}
    row = acquire_book.file_jigsaw(bad, "isbn_9780140277500", Path(scratch) / "other")
    if row.get("status") != "rejected-before-search" or clues_only.files(Path(scratch) / "other"):
        fails.append(f"a jigsaw with a clue unfit to file was held: {row}")
# Before a cold solve is paid for: a clue list no symmetric grid can hold.
def lights(across, down):
    return {"clues": {"across": [{"length": n} for n in across],
                      "down": [{"length": n} for n in down]}}
for across, down, bad, what in (
        ([6, 8, 11, 8, 6], [8, 3, 7, 7, 3, 8, 5], False, "a symmetric list"),
        ([6, 8, 11, 7, 6], [8, 3, 3, 8], True, "across lengths out of mirror"),
        ([6, 8, 6], [8, 3, 7, 3, 8, 14], True, "a down light with no partner"),
        ([6, None, 6], [8, 3, 7, 3, 8, None, 14], False, "an unknown length partners it"),
        ([6, 6], [8, 8, 4, 4, 7, 7], False, "pairs only")):
    if bool(clues_only.implausible(lights(across, down))) != bad:
        fails.append(f"implausible() misjudged {what}: {clues_only.implausible(lights(across, down))}")
if clues_only.implausible({"clues": {"unplaced": [{"length": 5}]}, "cluesUnplaced": True}) is not None:
    fails.append("implausible() judged a jigsaw, which has no grid to argue from")

if fails:
    print("FAIL test_clues_only:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok test_clues_only: clues-only book-8001 promoted to its published grid; "
      "half states and a barred grid refused")
EOF
