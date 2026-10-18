#!/usr/bin/env python3
# The bag's one view and one annotations file (tools/annotate_bag.py).
#
#     python3 tools/test_annotate_bag.py
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import annotate_bag
import annotate_check

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


view = {
    "name": "Test No 1", "setter": "Z", "annotateOnly": ["3-across", "5-down"],
    "entries": ["1-across | - | ALPHA | hinted already (5)",
                "3-across | 3-across+9-across | BETA | due, leader (4)",
                "5-down | - | GAMMA | due (5)",
                "7-down | - | DELTA | hinted, crosses nothing needed (5)",
                "9-across | in 3-across | ETA | continuation (3)"],
    "flagged": {"5-down": "the hint on file has a wrongly shaped wordplay tree (del has 4 parts): "
                          "parse the clue again and write a new `wp`; the check refuses it"},
    "annotationsFile": "no file", "dimensions": {"rows": 5, "cols": 5},
}
block = annotate_bag.puzzle_block("t-1", view)
check("header names the puzzle", block.startswith("== t-1 | Test No 1 | Z"))
check("due clues and their linked light are kept", all(s in block for s in ("BETA", "GAMMA", "ETA")))
check("hinted clues the run leaves alone are dropped", "ALPHA" not in block and "DELTA" not in block)
check("flagged keeps the fault, not the boilerplate",
      "del has 4 parts" in block and "parse the clue again" not in block)
check("fields a clue never needs are dropped", "dimensions" not in block and "annotationsFile" not in block)
check("a view with no annotateOnly lists every entry",
      len(annotate_bag.due_lines({"entries": view["entries"]})) == 5)

# check(): one file split per puzzle, clean ones one line, failing ones reported, clean not re-run
calls = []
outs = {"a": ("annotate_check a: clean, index refreshed — done", 0),
        "b": ("boom\nannotate_check b: 1 ERROR", 1)}


def fake_main(argv):
    calls.append(argv[0])
    print(outs[argv[0]][0])
    return outs[argv[0]][1]


annotate_check.main = fake_main
annotate_bag.TOOLS = annotate_bag.Path(__import__("tempfile").mkdtemp())
f = annotate_bag.TOOLS / "_ann_bag_a.json"
f.write_text('{"a": {"1-across": null}, "b": {"2-down": null}}')
import io
import contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = annotate_bag.check(f)
text = buf.getvalue()
check("a failing puzzle makes the exit non-zero", rc == 1)
check("clean puzzle is one line", "a: clean\n" in text and "--- a" not in text)
check("failing puzzle is reported in full", "--- b\nboom" in text)
check("each part is split to its own _ann file",
      (annotate_bag.TOOLS / "_ann_b.json").read_text().count("2-down") == 1)
outs["b"] = ("annotate_check b: clean, index refreshed — done", 0)
with contextlib.redirect_stdout(io.StringIO()) as buf2:
    rc = annotate_bag.check(f)
check("the second run re-checks only the failing puzzle", calls == ["a", "b", "b"])
check("all clean ends the run", rc == 0 and "all 2 puzzles checked" in buf2.getvalue())

print("annotate_bag: all checks passed" if not fails else f"annotate_bag: {fails} FAILED")
sys.exit(1 if fails else 0)
