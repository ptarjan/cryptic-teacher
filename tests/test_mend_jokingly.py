#!/usr/bin/env python3
# annotate_check.mend_jokingly: the hedge "jokingly" is dropped from a model-shape walkthrough.
#
#     python3 tests/test_mend_jokingly.py
import json
import tempfile
from pathlib import Path
from unittest import mock

import _path  # puts tools/ on sys.path
import annotate_check as C

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


def run(walk, clue="Shop relative's pop in"):
    entries = [{"id": "1-across", "number": 1, "direction": "across", "clue": {"text": clue}}]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "pending.json"
        a = {"def": "Shop", "wp": "[pop]POP", "surface": "s", "walkthrough": walk}
        p.write_text(json.dumps({"1-across": a}), encoding="utf-8")
        with mock.patch.object(C, "read_puzzle_file", return_value={"entries": entries}), \
                mock.patch.object(C, "entry_id", side_effect=lambda e: e["id"]):
            changed = C.mend_jokingly(None, p)
        return changed, json.loads(p.read_text(encoding="utf-8"))["1-across"]["walkthrough"]


ch, w = run("The pawnbroker is jokingly called 'uncle'.")
check("mid-sentence word dropped", ch == ["1-across"] and w == "The pawnbroker is called 'uncle'.")
ch, w = run("A plumber jokingly is one who pipes.")
check("adverb before verb dropped", w == "A plumber is one who pipes.")
ch, w = run("Jokingly, a crow is said to nest at sea.")
check("opening word dropped and capital kept", w == "A crow is said to nest at sea.")
ch, w = run("The pawnbroker is called 'jokingly'.")
check("a quoted word is left", ch == [])
ch, w = run("It is jokingly called uncle.", clue="Jokingly called uncle")
check("a clue that prints the word is left", ch == [])
ch, w = run("It is called uncle.")
check("no hedge, no change", ch == [])

raise SystemExit(1 if fails else 0)
