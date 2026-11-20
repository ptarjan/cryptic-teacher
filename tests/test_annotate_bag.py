#!/usr/bin/env python3
# The bag's one view and one annotations file (tools/annotate_bag.py).
#
#     python3 tests/test_annotate_bag.py
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # puts tools/ on sys.path

import annotate_bag
import annotate_check
import apply_annotations

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

kblock = annotate_bag.puzzle_block("t-1", {**view, "keepWords": {"5-down": "mixed rhubarb"}})
check("redo keep-words line is shown", "keep these words in the new tree unless wrong: 5-down: mixed rhubarb" in kblock)
check("no keepWords, no line", "keep these words" not in block)

old = {"definitions": [{"text": "dish"}],
       "wordplay": {"op": "anagram", "indicators": [{"text": "mixed"}],
                    "parts": [{"words": "rhubarb", "gives": "RHUBARB"}]}}
keep = annotate_check.validate_annotations.redo_keep_words(old, "Mixed rhubarb and dish (5)")
check("keep words are the gate's lost words, in clue order", "mixed" in keep and "rhubarb" in keep)
new = {"definitions": [{"text": "dish"}],
       "wordplay": {"op": "anagram", "indicators": [{"text": "mixed"}],
                    "parts": [{"words": "rhubarb", "gives": "RHUBARB"}]}}
check("keeping them passes the gate",
      not annotate_check.validate_annotations.redo_lost_words(old, new, "Mixed rhubarb and dish (5)"))

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

f.write_text('{"a": {"1-across": {"wp": "x", "notes": {"p": "q"}}}, "b": {"2-down": {"wp": "y"}}}')
pf = annotate_bag.TOOLS / "fix.json"
pf.write_text('{"a": {"1-across": {"wp": "z", "notes": {"r": "s"}}}}')
err = annotate_bag.patch_bag(f, pf)
got = __import__("json").loads(f.read_text())
check("a bag patch merges fields without matching bytes",
      err is None and got["a"]["1-across"] == {"wp": "z", "notes": {"p": "q", "r": "s"}}
      and got["b"]["2-down"] == {"wp": "y"} and not pf.exists())
pf.write_text('{"zz": {}}')
check("a patch naming an unknown puzzle is refused", "lacks: zz" in (annotate_bag.patch_bag(f, pf) or ""))

# 10-25 audit: a model asking `annotate_bag.py --help` got exit 2 (a wasted Bash error)
with contextlib.redirect_stdout(io.StringIO()) as helpbuf:
    help_rc = annotate_bag.main(["--help"])
check("--help prints the usage and exits 0", help_rc == 0 and "annotate_bag.py view" in helpbuf.getvalue())

# the redo gate runs in check: a listed clue whose new tree is still flagged fails
import shape_queue
wp_old = {"op": "anagram", "parts": [{"words": "x", "gives": "X"}]}
gpuz = {"id": "g-1", "entries": [{"number": 5, "direction": "down", "annotation": {"wordplay": wp_old},
                                  "clue": {"text": "x"}}]}
saved = (shape_queue.listed, shape_queue.findings, shape_queue.regressions, apply_annotations.landed)
shape_queue.listed = lambda p: {"5-down": "scrambledLeaf: x"}
shape_queue.findings = lambda e, n: ["scrambledLeaf: still"]
shape_queue.regressions = lambda e, n: []
apply_annotations.landed = lambda ann, e, es, eid, errs, puzzle=None: {"wordplay": ann["wordplay"]}
got = annotate_bag.redo_gate(gpuz, {"5-down": {"wordplay": wp_old}})
check("redo gate names the entry and the same-tree fault",
      len(got) == 1 and "redo gate 5-down" in got[0] and "same tree" in got[0] and "scrambledLeaf: still" in got[0])
shape_queue.findings = lambda e, n: []
check("a tree that clears the rule passes the redo gate", not annotate_bag.redo_gate(gpuz, {"5-down": {"wordplay": wp_old}}))
shape_queue.regressions = lambda e, n: ["dropped 'mixed'"]
check("a redo losing words fails the gate", "dropped 'mixed'" in annotate_bag.redo_gate(gpuz, {"5-down": {"wordplay": wp_old}})[0])
shape_queue.listed, shape_queue.findings, shape_queue.regressions, apply_annotations.landed = saved

import bag_turns
check("a bag's turn limit is 20 plus a turn a clue, never under 40",
      [bag_turns.turns(n) for n in (0, 5, 30, 39)] == [40, 40, 50, 59])

blogview = dict(view, blogFlagged={"3-across": "definition: the blog underlines 'x'"},
                ourAnnotations={"3-across": {"def": "old"}})
block = annotate_bag.puzzle_block("p-1", blogview)
check("a blog bag's block carries the blog's warning and our hint beside it",
      "blog disagrees" in block and "3-across: definition: the blog underlines" in block
      and 'ourAnnotations: {"3-across":{"def":"old"}}' in block)

fieldview = dict(view, fieldMissing={"3-across": "no indicator notes — give every indicator a `note`"},
                 ourAnnotations={"3-across": {"def": "x"}})
fblock = annotate_bag.puzzle_block("p-1", fieldview)
check("a field backfill bag's block names what each clue lacks and carries our hint beside it",
      "lacks a field" in fblock and "3-across: no indicator notes" in fblock and "ourAnnotations" in fblock)
os.environ.pop("CT_BACKFILL_FIELD", None)
check("field_left is empty outside a field backfill pool", annotate_bag.field_left("p-1") == "")
check("field_due is empty outside a field backfill pool", annotate_check.field_due({"entries": []}) == {})
import apply_annotations
old = {"wordplay": "x"}
check("a redo that only adds a field is reverted outside a field backfill", apply_annotations.redo_adds_nothing(old, dict(old)))
os.environ["CT_BACKFILL_FIELD"] = "indicators.note"
check("... and kept inside one", not apply_annotations.redo_adds_nothing(old, dict(old)))
del os.environ["CT_BACKFILL_FIELD"]

import blog_compare
filed = []
blog_compare.keep_ours = lambda pid, eid, fields, why: filed.append((pid, eid, fields, why)) or None
check("a _keep row is filed through blog_compare.keep_ours",
      annotate_bag.file_keeps("p-1", {"3-across": ["definition", "ours is the surface reading"]}) == []
      and filed == [("p-1", "3-across", "definition", "ours is the surface reading")])
check("a malformed _keep row is reported, not filed",
      len(annotate_bag.file_keeps("p-1", {"5-down": "because"})) == 1 and len(filed) == 1)

print("annotate_bag: all checks passed" if not fails else f"annotate_bag: {fails} FAILED")
sys.exit(1 if fails else 0)
