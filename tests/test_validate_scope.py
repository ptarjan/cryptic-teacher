#!/usr/bin/env python3
# The deploy's validate job checks only what a push could have changed
# (tools/validate_scope.py): a puzzle edit, or a tools/ edit nothing the check
# reaches calls, stays incremental; a change to a rule, a table it reads, the
# authored puzzle's inputs or the workflow is a full check. And the full check
# spread across cores prints exactly what the serial one does.
#
#     python3 tests/test_validate_scope.py
import difflib
import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, "tools")
import validate_scope as v

src = open("tools/validate_annotations.py", encoding="utf-8").read()


def decide(changes, new_src=None):
    return v.decide(changes, lambda p: new_src if new_src is not None else src)


def expect(label, got, mode, text=""):
    if got[0] != mode or (text and text not in str(got[1])):
        sys.exit(f"test_validate_scope: {label}: wanted {mode} {text!r}, got {got}")


P = "puzzles/times/2002/times-21965.json"
expect("puzzle edits", decide([("A", P), ("M", "puzzles/nation/2013/nation-3270.json"),
                               ("D", "clues_only/nation/nation-3269.json"), ("D", "puzzles/x/2001/x-1.json")]),
       "files")
expect("the puzzles are named", v.decide([("A", P), ("M", "docs/NIGHTLY.md")]), "files")
assert v.decide([("A", P), ("M", "docs/NIGHTLY.md")])[1] == [P]
expect("a rename-looking status", v.decide([("R", P)]), "full", "R " + P)
expect("a fetcher nothing reaches", v.decide([("M", "tools/fetch_telegraph.py")]), "files")
expect("a test and the budgets", v.decide([("M", "tests/test_step_budgets.sh"),
                                            ("M", "tools/data/deploy_budgets.json"),
                                            ("M", "README.md")]), "files")
expect("the burn's queue state", v.decide([("A", P), ("M", "tools/data/shape_reannotate.json")]), "files")
expect("the annotator's prompts", v.decide([("M", "tools/annotate_prompt.md"),
                                             ("M", "tools/annotate_bag_prompt.md")]), "files")
expect("a rule table", v.decide([("M", "tools/data/clue_types.json")]), "full", "clue_types.json")
expect("the backlog", v.decide([("M", "tools/annotation_backlog.json")]), "full", "annotation_backlog.json")
OLD = '{"_why": "x", "indicators.note": {"times-21965": 3, "times-1": 2}}'
B = "tools/annotation_backlog.json"


PATHS = {"times-21965": P, "times-1": "puzzles/times/2001/times-1.json", "times-9": "puzzles/times/2001/times-9.json"}


def where(stems):
    return {s: PATHS[s] for s in stems if s in PATHS}


def backlog(old, new, extra=(), resolve=where):
    return v.decide([("M", B), *extra], lambda p: old, lambda p: new, resolve)


tight = '{"_why": "y", "indicators.note": {"times-21965": 1, "times-1": 2}}'
gone = '{"_why": "x", "indicators.note": {"times-1": 2}}'
expect("a tightened backlog with its puzzle", backlog(OLD, tight, [("M", P)]), "files")
expect("a dropped entry with its puzzle", backlog(OLD, gone, [("M", P)]), "files")
expect("a tightened backlog, puzzle unchanged", backlog(OLD, tight), "files")
assert backlog(OLD, tight)[1] == [P]
raised = backlog(OLD, OLD.replace('"times-1": 2', '"times-1": 5'), [("M", P)])
expect("a raised allowance", raised, "files")
assert raised[1] == [P, PATHS["times-1"]], raised
expect("a new entry", backlog(OLD, OLD.replace('"times-1": 2', '"times-1": 2, "times-9": 1')), "files")
expect("an allowance for a puzzle with no file", backlog(OLD, tight, resolve=lambda s: {}), "full", "times-21965")
expect("a new field", backlog(OLD, OLD[:-1] + ', "other": {}}', [("M", P)]), "full", "annotation_backlog.json")
expect("a backlog that is not json", backlog(OLD, "{", [("M", P)]), "full", "annotation_backlog.json")
T = "tools/data/blog_disagree.json"
ROWS = '{"times-21965/1-across": ["type", "a"], "times-1/2-down": ["type", "b"]}'


def rows(new, extra=()):
    return v.decide([("M", T), *extra], lambda p: ROWS, lambda p: new, where)


more = ROWS[:-1] + ', "times-21965/3-down": ["definition", "c"]}'
expect("an added row with its puzzle", rows(more, [("M", P)]), "files")
expect("an added row, puzzle unchanged", rows(more), "files")
assert rows(more)[1] == [P]
expect("a row removed", rows('{"times-1/2-down": ["type", "b"]}', [("M", P)]), "full", "blog_disagree.json")
expect("a table that is not json", rows("{", [("M", P)]), "full", "blog_disagree.json")
expect("the authored clues",v.decide([("M", "tools/data/authored_A001_clues.json")]), "full", "authored_A001_clues.json")
expect("the workflow", v.decide([("M", ".github/workflows/pages.yml")]), "full", "pages.yml")
expect("a reached module with no old text", v.decide([("M", "tools/validate_annotations.py")]), "full", "old text")
expect("a comment in the validator", decide([("M", "tools/validate_annotations.py")], src + "\n# a comment\n"), "files")
expect("a new rule", decide([("M", "tools/validate_annotations.py")], src.replace("POOL_MIN = 200", "POOL_MIN = 7")),
       "full", "POOL_MIN")
expect("an added reached module", v.decide([("A", "tools/validate_annotations.py")]), "full")
print("test_validate_scope: scope ok")

# The pool prints what the serial run prints: 500 puzzles is past POOL_MIN.
tmp = Path(tempfile.mkdtemp())
try:
    files = sorted(glob.glob("puzzles/times/*/*.json"))[:500]
    if len(files) < 300:
        sys.exit("test_validate_scope: too few puzzles to reach the pool")
    listing = "\n".join(files) + "\n"

    def run(jobs):
        r = subprocess.run(["xargs", "python3", "tools/validate_annotations.py", "--deploy"],
                           input=listing, capture_output=True, text=True,
                           env={**os.environ, "VALIDATE_JOBS": jobs})
        return r.stdout + r.stderr

    serial, pool = run("1"), run("2")
    if serial != pool:
        print("test_validate_scope: pool output differs from serial")
        print("\n".join(list(difflib.unified_diff(serial.splitlines(), pool.splitlines(),
                                                  "serial", "pool", lineterm=""))[:10]))
        sys.exit(1)
    if not serial:
        sys.exit("test_validate_scope: no output")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("test_validate_scope: all passed")
