#!/usr/bin/env python3
# A `printedClue` equal to the clue as shown is dropped, not refused.
#
#     python3 tests/test_drop_noop_printed_clue.py
#
# file_rows refused it ("corrects nothing: the clue as printed is the clue as
# shown"), the top first-check failure in annotation sessions. Removing it
# loses nothing, so annotate_check.drop_noop_printed_clue does that first.
import json
import tempfile
from pathlib import Path
import _path  # puts tools/ on sys.path
import annotate_check as AC
import puzzle_paths
import fetch_puzzle as fp

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

path = puzzle_paths.find("quiptic-619")
puzzle = fp.read_puzzle_file(path)
e0, e1 = puzzle["entries"][0], puzzle["entries"][1]
id0, id1 = AC.entry_id(e0), AC.entry_id(e1)
shown = e0["clue"]["text"]
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    (d / "source_clue_wrong.json").write_text("{}")
    f = d / "_ann_x.json"
    f.write_text(json.dumps({
        id0: {"printedClue": [shown + " ", "evidence that is long enough to be argued here"], "def": "d"},
        id1: {"printedClue": ["A different clue", "evidence that is long enough to be argued here"]},
    }))
    check("the no-op is dropped", AC.drop_noop_printed_clue(path, f, d) == [id0])
    left = json.loads(f.read_text())
    check("its other keys stay", left[id0] == {"def": "d"})
    check("a real correction stays", "printedClue" in left[id1])
    check("a second pass changes nothing", AC.drop_noop_printed_clue(path, f, d) == [])
raise SystemExit(1 if fails else 0)
