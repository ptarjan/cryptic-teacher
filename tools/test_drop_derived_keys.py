#!/usr/bin/env python3
# A clue written with `wp` and a derived key (assembly, type, ...) is applied, not refused.
#
#     python3 tools/test_drop_derived_keys.py
#
# The validator's "Give `assembly.pieces`" warning led runs to write `assembly`
# beside `wp`; annotation.from_model refused the file ("unknown key assembly").
# annotate_check.drop_derived_keys removes those keys, which view() derives.
import json
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import annotate_check as AC

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

with tempfile.TemporaryDirectory() as d:
    f = Path(d) / "_ann_x.json"
    f.write_text(json.dumps({
        "1-across": {"def": "d", "wp": "[a]B", "notes": {}, "assembly": {"pieces": ["B"]}, "type": ["charade"]},
        "2-down": {"def": "d", "wp": "[a]B", "notes": {}},
        "3-down": {"assembly": {"pieces": ["B"]}, "type": ["charade"]},
        "4-down": None,
    }, indent=1))
    check("the ids changed are returned", AC.drop_derived_keys(f) == ["1-across"])
    got = json.loads(f.read_text())
    check("derived keys are gone beside wp", set(got["1-across"]) == {"def", "wp", "notes"})
    check("a clue without wp is left to be refused", "assembly" in got["3-down"])
    check("a clean clue and a null are untouched",
          set(got["2-down"]) == {"def", "wp", "notes"} and got["4-down"] is None)
    check("a second pass changes nothing", AC.drop_derived_keys(f) == [])
    f.write_text(json.dumps({
        "5-down": {"def": "d", "wp": "[a]B", "notes": {}, "noIndicator": True, "andLit": False,
                   "spelling": "BEE"},
        "6-down": {"def": "d", "wp": "[a]B", "notes": {}, "andLit": True},
    }))
    check("noIndicator, andLit false and spelling are mended", AC.drop_derived_keys(f) == ["5-down"])
    got = json.loads(f.read_text())
    check("spelling becomes answer, the rest are gone",
          got["5-down"] == {"def": "d", "wp": "[a]B", "notes": {}, "answer": "BEE"}
          and got["6-down"]["andLit"] is True)
sys.exit(1 if fails else 0)
