#!/usr/bin/env python3
# Does tools/ocr_retry.py settle a weak clue only from lines two variants of different
# preprocessing print alike, only when a scan reader prints the whole too, and does it
# find the clue's lines and keep one corpus row per os.write?
#
#     python3 tests/test_ocr_retry.py
#
# Offline: no Tesseract runs (read_line is stubbed).
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
os.environ["CT_OCR_RETRY"] = "1"

import ocr_retry as R

fails = 0


def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        print(f"FAIL {what}: want [{want}] got [{got}]")
        fails += 1


os.environ.pop("CT_OCR_RETRY")
check("off unless asked for", False, R.enabled())
os.environ["CT_OCR_RETRY"] = "1"

# One line: two variants alike settle it; a lone variant does not.
check("two variants agree", "Road sign needs lighting",
      R.vote_line({"a": "Road sign needs lighting", "b": "Road sign needs lighting.", "c": "Road sign peeds lighting"}))
check("one variant is no vote", None, R.vote_line({"a": "Road sign needs lighting", "b": "Road sign peeds lighting"}))
check("the number is not compared", "8 Road sign needs",
      R.vote_line({"a": "8 Road sign needs", "b": "Road sign needs"}, first=True))
check("the count is not compared", "have a go! (2,5)",
      R.vote_line({"a": "have a go! (2,5)", "b": "have a go!"}, last=True))

# A clue: every line voted.
lines = [{"a": "8 Road sign needs", "b": "8 Road sign needs", "c": "x"}, {"a": "lighting up (2,5)", "b": "lighting up (2,5)"}]
check("every line voted", "Road sign needs lighting up", R.voted(lines))
check("a line without a vote sinks the clue", None, R.voted([lines[0], {"a": "lighting up", "b": "lightinq up"}]))
check("too short", None, R.voted([{"a": "8 Go", "b": "8 Go"}]))

# Accepted only with a reader that prints it too.
check("a reader prints it", "Road sign needs lighting up",
      R.accept(lines, ["Road sign needs lighting up"]))
check("no reader prints it", None, R.accept(lines, ["Road sign peeds lighting up", "Road sign needs"]))
check("no readers at all", None, R.accept(lines, []))

# The clue's lines: its number to the count, in the right direction, not the next clue's.
col = [(0, 10, 0, 100, "ACROSS"), (11, 20, 0, 100, "8 Road sign needs"), (21, 30, 0, 100, "lighting up (2,5)"),
       (31, 40, 0, 100, "9 Next clue (3)"), (41, 50, 0, 100, "DOWN"), (51, 60, 0, 100, "8 Another one"),
       (61, 70, 0, 100, "goes here (4)")]
got, reader = R.clue_lines({"ch": [col]}, "8-across")
check("across lines", ["8 Road sign needs", "lighting up (2,5)"], [l[4] for l in got])
got, _ = R.clue_lines({"ch": [col]}, "8-down")
check("down lines", ["8 Another one", "goes here (4)"], [l[4] for l in got])
check("no such clue", ([], None), R.clue_lines({"ch": [col]}, "12-across"))
check("falls to the next reader", "en5", R.clue_lines({"ch": [], "en5": [col]}, "8-across")[1])

# retry(): cached per page, reads each line once, honours the off switch.
reads = []


def fake(page, line):
    text = {l[0]: l[4] for l in col}[int(line[0])]
    reads.append(text)
    return {"a": text, "b": text}


R.read_line = fake
with tempfile.TemporaryDirectory() as tmp:
    R.RETRY_CACHE = Path(tmp)
    cols = {"ch": [col]}
    got = R.retry(None, "pg", cols, {"8-across"}, {"8-across": ["Road sign needs lighting up"]})
    check("retry fills", {"8-across": "Road sign needs lighting up"}, got)
    n = len(reads)
    R.retry(None, "pg", cols, {"8-across"}, {"8-across": ["Road sign needs lighting up"]})
    check("the second read reads nothing", n, len(reads))
    check("no reader, no fill", {}, R.retry(None, "pg2", cols, {"8-down"}, {"8-down": ["Different words entirely"]}))
    os.environ["CT_OCR_RETRY"] = "0"
    check("off switch", {}, R.retry(None, "pg3", cols, {"8-across"}, {"8-across": ["Road sign needs lighting up"]}))
    os.environ["CT_OCR_RETRY"] = "1"

# The corpus: one row a call, appended.
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "sub" / "c.jsonl"
    R.record("ed_1", "8-across", [1, 2, 3, 4], {"ch": "x"}, "y", [], path=path)
    R.record("ed_1", "9-down", None, {}, "z", ["ch"], path=path)
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    check("two rows", ["8-across", "9-down"], [r["clue"] for r in rows])
    check("row fields", ["page", "clue", "box", "ocr", "vlm", "matched"], list(rows[0]))

sys.exit(1 if fails else 0)
