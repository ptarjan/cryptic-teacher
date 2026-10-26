#!/usr/bin/env python3
# Does tools/clue_repair.fill_missing_sizes give a plain light whose
# count the OCR lost the length of the answer the next issue printed, and leave
# a linked light's length to its group? (Cyclops No 164's 17ac.)
#
#     python3 tests/test_privateeye_missing_size.py
#
# Offline.
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import clue_repair as pw

across = [[1, 5, "plain"], [17, None, "plain"], [11, None, "linked"], [20, None, "plain"]]
down = [[17, None, "plain"], [2, 4, "plain"]]
given = {("17", "across"): "TUTSI", ("11", "across"): "SUMMER", ("2", "down"): "ABCDEFG"}
pw.fill_missing_sizes(across, down, given)
out = f"ACROSS {[x[1] for x in across]}\nDOWN {[x[1] for x in down]}"
want = "ACROSS [5, 5, None, None]\nDOWN [None, 4]"
what = "a plain light's lost count takes the answer's length; linked, unanswered and counted lights keep theirs"
if out == want:
    print(f"ok   {what}")
    print("all ok")
else:
    print(f"FAIL {what}: want [{want}] got [{out}]")
    sys.exit(1)
