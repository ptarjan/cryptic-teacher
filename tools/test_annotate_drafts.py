#!/usr/bin/env python3
# The annotate run's view carries tools/prefill_hidden.py's drafts.
#
#     python3 tools/test_annotate_drafts.py
#
# A puzzle with a hidden-word clue the run has to write gets that clue's
# mechanical `def`/`wp`/`notes` under `draftAnnotations` in its view, computed
# on the fly; a clue outside `annotateOnly` gets none; a prefill that blows up
# costs the view nothing; the prompt tells the run what to do with a draft.
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))

import json, shutil, tempfile
from pathlib import Path
import annotate_check as AC
import apply_annotations as A
import prefill_hidden
import shape_queue

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

tmp = Path(tempfile.mkdtemp())
A.TOOLS = tmp            # the view and the _ann file, away from the real tools/
shape_queue.PATH = tmp / "none.json"
try:
    path = tmp / "cryptic-22754.json"
    shutil.copy("puzzles/cryptic/2003/cryptic-22754.json", path)
    view = json.loads(AC.write_view(path).read_text())
    drafts = view.get("draftAnnotations") or {}
    check("the hidden clue has a draft", list(drafts) == ["22-down"])
    d = drafts.get("22-down", {})
    check("the draft is the model's shape, with no explanation or features",
          set(d) == {"def", "wp", "notes"} and d["wp"].startswith("hid<Extract from>("))
    check("the draft equals the prefill", d == prefill_hidden.prefill_puzzle(AC.read_puzzle_file(path))["22-down"])

    check("a clue outside annotateOnly gets no draft",
          AC.hidden_drafts(AC.read_puzzle_file(path), ["1-across"]) == {})
    check("a clue inside annotateOnly keeps it",
          list(AC.hidden_drafts(AC.read_puzzle_file(path), ["22-down"])) == ["22-down"])

    def boom(puzzle):
        raise RuntimeError("prefill broke")
    real, prefill_hidden.prefill_puzzle = prefill_hidden.prefill_puzzle, boom
    try:
        broken = json.loads(AC.write_view(path).read_text())
    finally:
        prefill_hidden.prefill_puzzle = real
    check("a failing prefill leaves the view without drafts",
          "draftAnnotations" not in broken and broken.get("entries"))

    prompt = Path("tools/annotate_prompt.md").read_text()
    check("the prompt names draftAnnotations and what the run adds",
          "draftAnnotations" in prompt and "`features`" in prompt)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
