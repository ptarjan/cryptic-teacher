#!/usr/bin/env python3
# Can /difficulty/ describe a rating other than the one the badges show?
# It must refuse to build when its prose and difficulty.WEIGHTS name different
# components, quote the scorecard only while it matches today's weights, and
# leave no {{placeholder}} unfilled.
#
#     python3 tests/test_difficulty_page.py
#
# A synthetic index and scorecard, so nothing here reads the corpus or writes
# to the tree.
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build_seo_pages as B
import difficulty as D
import difficulty_check as C

tmp = Path(tempfile.mkdtemp())
got = {}
try:
    idx = {"puzzles": [{"difficulty": {"band": b}} for b in ("Gentle", "Tough", "Tough")],
           "snitchRanges": {"times": {"Tough": {"q1": 80, "q3": 110, "rated": 12}}}}
    check = {**C.fingerprint(), "snitch_newest": "2026-01-01",
             "heldout": {k: {"thirds": [0.4, 0.5, 0.6], "mean": 0.5, "n": 100} for k in C.SETS},
             "blended": {k: {"thirds": [0.6, 0.7, 0.8], "mean": 0.7, "n": 100, "puzzles_blended": 90}
                         for k in C.SETS},
             "components": {k: {"thirds": [0, 0, 0], "mean": 0.123, "n": 100} for k in D.WEIGHTS},
             "gentle_margin": {"margin": 0.321, "floor": D.MARGIN_FLOOR, "gentle_n": 5,
                               "other_n": 50, "series": sorted(D.GENTLE_SERIES)}}
    C.OUT = tmp / "check.json"
    C.OUT.write_text(json.dumps(check))
    page = B.difficulty_page(idx)
    got["LIVE"] = "+0.12" in page and "0.32 standard deviations" in page and "+0.70" in page
    got["FILLED"] = "{{" not in page
    got["EVERY"] = all(f'id="{k}"' in page for k in D.WEIGHTS)
    got["NITCH"] = "80&ndash;110" in page

    C.OUT.write_text(json.dumps({**check, "weights": {**D.WEIGHTS, "checking": 9}}))
    page = B.difficulty_page(idx)
    got["STALE"] = "+0.12" not in page and "0.32" not in page and "re-measured" in page

    tpl = B.DIFFICULTY_TEMPLATE.read_text(encoding="utf-8")
    B.DIFFICULTY_TEMPLATE = tmp / "page.html"
    B.DIFFICULTY_TEMPLATE.write_text(re.sub(r"<!-- component: clue_count .*", "", tpl, flags=re.S))
    try:
        B.difficulty_page(idx)
        got["MISSING"] = False
    except SystemExit as e:
        got["MISSING"] = "clue_count" in str(e)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

fail = False
for key in ("LIVE", "FILLED", "EVERY", "NITCH", "STALE", "MISSING"):
    if got.get(key) is not True:
        print(f"FAIL: expected '{key} True'")
        fail = True
if fail:
    print(got)
    sys.exit(1)
print("difficulty page: ok")
