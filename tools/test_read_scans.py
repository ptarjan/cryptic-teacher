#!/usr/bin/env python3
# Does read_scans report a number whose issue was already read for the one
# before it by what that reading said, not as "not read"?
#
#     python3 tools/test_read_scans.py
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import privateeye_scans
import privateeye_wayback as W

tmp = Path(tempfile.mkdtemp())
(tmp / "ia").mkdir()
for issue in (42, 43):
    (tmp / "ia" / f"{issue}_djvu.txt").write_text("x")
W.DIR = tmp
W.ISSUE_OFFSET = 1  # No 42 is first tried in issue 43
reads = []


def fake(issue, get):
    reads.append(issue)
    return {42: (42, "p42", None), 43: (43, None, "3 clues the readings do not agree on")}[issue]


privateeye_scans.read = fake
why = W.read_scans([42, 43])
assert why == {43: "3 clues the readings do not agree on"}, why
assert reads.count(43) == 1, reads
why = W.read_scans([43, 42])
assert why == {43: "3 clues the readings do not agree on"}, why
print("ok")
