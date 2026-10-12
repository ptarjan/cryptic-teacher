#!/bin/bash
# Does a jigsaw held as its clues alone become a filed puzzle once answered?
#
#     bash tools/test_jigsaw_fit.sh
#
# A small synthetic jigsaw: a 7x7 blocked grid of random letters (four rows,
# four columns), its eight lights' answers given as one unnumbered list, two of
# them read as one linked 14-letter answer so it must split across two lights.
# tools/jigsaw_fit.py must find that grid and no other; the clues-only record
# (cluesUnplaced, a preamble, clues.unplaced) must be queued by solvable(); its
# packet must show the preamble and the flat list; tools/apply_solution.py must
# refuse a wrong answer and file the right ones, in a scratch tree, as a
# puzzle with positions, numbered, `cluesUnplaced` kept, the linked answer a
# leader and its "See N", and the clues-only copy gone.
set -u
cd "$(dirname "$0")/.." || exit 1

python3 - <<'EOF'
import contextlib
import io
import json
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "tools")
import apply_solution
import clues_only
import jigsaw_fit
import puzzle_paths
import solve_packet

fails = []
rng = random.Random(7)
N = 7
letters = [[rng.choice("ABCDEFGHIJKLMNOPRSTUVWY") if y % 2 == 0 or x % 2 == 0 else "#"
            for x in range(N)] for y in range(N)]
truth = ["".join(r) for r in letters]
rows_ = [truth[y] for y in range(0, N, 2)]
cols_ = ["".join(truth[y][x] for y in range(N)) for x in range(0, N, 2)]
# rows 0 and 6 read as one linked answer
linked = rows_[0] + rows_[3]
answers = [cols_[2], linked, rows_[1], cols_[0], rows_[2], cols_[3], cols_[1]]

# 1. The fitter: the one grid, up to its transpose.
grid, placed, why = jigsaw_fit.fit(answers, N, N)
transposed = ["".join(r[x] for r in truth) for x in range(N)]
if grid not in (truth, transposed):
    fails.append(f"fit found {grid} ({why}), want\n" + "\n".join(truth))
parts = sorted(p[1] for p in placed or [] if p[0] == 1)
if parts != [0, 1]:
    fails.append(f"the linked answer went in as parts {parts}, want a leader and a continuation")
# A wrong answer fits nowhere.
if jigsaw_fit.fit(["Q" * N] + answers[1:], N, N)[0] is not None:
    fails.append("a wrong answer fitted a grid")
# Too few answers for a grid with two of every light: no grid.
if jigsaw_fit.fit(answers[:-1], N, N)[0] is not None:
    fails.append("a list one answer short fitted a grid")

record = {"id": "book-8060", "number": 8060, "series": "book", "name": "Penguin book 8 No 60", "year": 1990,
          "preamble": "Solve the clues and fit the solutions into the diagram jigsaw-wise, "
                      "wherever they will go.",
          "cluesUnplaced": True, "dimensions": {"cols": N, "rows": N},
          "source": {"url": "https://archive.org/details/example",
                     "acquiredBy": "tools/acquire_book.py", "acquiredOn": "2026-10-12"},
          "clues": {"unplaced": [
              {"clue": {"text": f"Synthetic clue number {i}",
                        "enumeration": "7,7" if len(a) == 14 else str(len(a))},
               "length": len(a)} for i, a in enumerate(answers, 1)]}}


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
    held = clues_only.write(record)

    # 2. Queued, and its packet is the jigsaw's.
    if [r["id"] for r in clues_only.solvable()] != ["book-8060"]:
        fails.append(f"solvable() = {[r['id'] for r in clues_only.solvable()]}, want the jigsaw")
    packet = solve_packet.clues_only_packet(clues_only.read("book-8060"))
    if "JIGSAW" not in packet or "jigsaw-wise" not in packet or '"unplaced"' not in packet:
        fails.append(f"the packet is not the jigsaw's:\n{packet}")

    fill = {"unplaced": [{"answer": a, "definition": "Synthetic"} for a in answers]}
    # 3. The across/down shape, and a wrong answer: refused, nothing written.
    code, said = apply("book-8060", {"across": fill["unplaced"], "down": []}, scratch)
    if code == 0 or "unplaced" not in said:
        fails.append(f"an across/down fill for a jigsaw was not refused: {said}")
    wrong = json.loads(json.dumps(fill))
    wrong["unplaced"][0]["answer"] = "Q" * N
    code, said = apply("book-8060", wrong, scratch)
    if code == 0 or not held.exists() or any(puzzle_paths.PUZZLE_DIR.rglob("*.json")):
        fails.append(f"a wrong jigsaw fill was applied: {said}")

    # 4. Filed: positions, cluesUnplaced, the linked group, clues-only gone.
    code, said = apply("book-8060", fill, scratch)
    filed = list(puzzle_paths.PUZZLE_DIR.rglob("book-8060.json"))
    if code != 0 or not filed:
        fails.append(f"the jigsaw was not filed: {said}")
    else:
        puzzle = json.loads(filed[0].read_text())
        if not puzzle.get("cluesUnplaced") or not puzzle.get("preamble"):
            fails.append("the filed jigsaw lost cluesUnplaced or its preamble")
        if len(puzzle["entries"]) != 8 or not all("position" in e for e in puzzle["entries"]):
            fails.append(f"the filed jigsaw has {len(puzzle['entries'])} entries, want 8 placed")
        groups = [e["group"] for e in puzzle["entries"] if e.get("group")]
        if len(groups) != 1 or len(groups[0]) != 2:
            fails.append(f"the linked answer filed as groups {groups}, want one pair")
        if any(e.get("solution") in (None, "") for e in puzzle["entries"]):
            fails.append("the filed jigsaw has an unanswered light")
        if held.exists():
            fails.append("the clues-only copy was not removed")
        if "_parts" in puzzle:
            fails.append("the builder's part map leaked into the puzzle file")

for f in fails:
    print("FAIL", f)
print(f"test_jigsaw_fit: {len(fails)} failure(s)")
sys.exit(1 if fails else 0)
EOF
