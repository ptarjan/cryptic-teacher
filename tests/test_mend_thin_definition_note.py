#!/usr/bin/env python3
# annotate_check.mend_thin_definition_notes: a under-25-character note on the lone def is dropped.
#
#     python3 tests/test_mend_thin_definition_note.py
import json
import tempfile
from pathlib import Path

import _path  # puts tools/ on sys.path
import annotate_check as C

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


def run(a):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "pending.json"
        p.write_text(json.dumps({"1-across": a}), encoding="utf-8")
        changed = C.mend_thin_definition_notes(None, p)
        return changed, json.loads(p.read_text(encoding="utf-8"))["1-across"]


base = {"def": "Lousy payment", "wp": "[pea]PEA + [nuts]NUTS", "surface": "s", "walkthrough": "w"}
ch, a = run({**base, "notes": {"Lousy payment": "plural fine", "pea": "a pea"}})
check("thin def note dropped, other notes kept", ch == ["1-across"] and a["notes"] == {"pea": "a pea"})
long = "a mass noun defining a plural, fair as peanuts is a mass noun"
ch, a = run({**base, "notes": {"Lousy payment": long}})
check("a real sentence is kept", ch == [] and a["notes"] == {"Lousy payment": long})
ch, a = run({**base, "def": "pea", "notes": {"pea": "a pea"}})
check("a def word also in wp is not touched", ch == [] and a["notes"] == {"pea": "a pea"})

raise SystemExit(1 if fails else 0)
