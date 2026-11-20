#!/usr/bin/env python3
# Answers a person read by eye (tools/hand_answers.py) are marked solutions.hand, and no reread
# changes or drops them.
#
#     python3 tests/test_hand_answers.py
import os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import copy
import _path  # puts tools/ on sys.path
import file_archive_org_puzzles as archive
import hand_answers as H
import provenance

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


def entry(number, direction, x, y, word, solution):
    return {"number": number, "direction": direction, "position": {"x": x, "y": y}, "length": len(word),
            "clue": {"text": f"clue {number}", "enumeration": str(len(word))}, "solution": solution}


def puzzle():
    # 1A CAT across at (0,0); 1D COW down from (0,0); 2D TEA down from (2,0).
    return {"id": "times-1", "number": 1, "date": "2000-01-01", "dimensions": {"cols": 3, "rows": 3},
            "source": {"publisher": "Times", "retrievedFrom": "newspaper", "acquiredBy": archive.TOOL,
                       "acquiredOn": "2026-01-01", "gridOrigin": "published"},
            "solutions": {"origin": "published"},
            "entries": [entry(1, "across", 0, 0, "CAT", "CAT"), entry(1, "down", 0, 0, "COW", "COW"),
                        entry(2, "down", 2, 0, "TEA", None)]}


rows = H.parse("# note\ntimes-1 2d tea\ntimes-1 1 across CAT\n")
check("parse reads lines", rows == [("times-1", 2, "down", "TEA"), ("times-1", 1, "across", "CAT")])
try:
    H.parse("times-1 nonsense")
    check("parse refuses a bad line", False)
except ValueError:
    check("parse refuses a bad line", True)

p = puzzle()
check("a wrong length is refused", "long" in (H.fill(p, 2, "down", "TE", today="2026-11-06") or ""))
check("a crossing clash is refused", "crossing" in (H.fill(p, 2, "down", "SEA", today="2026-11-06") or ""))
check("nothing written by a refusal", "hand" not in p["solutions"] and p["entries"][2]["solution"] is None)
check("a fit is taken", H.fill(p, 2, "down", "TEA", today="2026-11-06") is None)
check("the light is filled and marked", p["entries"][2]["solution"] == "TEA"
      and p["solutions"]["hand"] == {"2-down": "2026-11-06"})
check("a held answer is not replaced", "already holds" in (H.fill(p, 1, "across", "CUT", today="2026-11-06") or ""))
check("provenance passes", not [f for f in provenance.check(p) if "hand" in f])

bad = copy.deepcopy(p)
bad["solutions"]["hand"]["9-down"] = "2026-11-06"
check("provenance refuses a hand light the file lacks", any("solutions.hand" in f for f in provenance.check(bad)))

# A reread that reads another answer, or none, leaves the hand light as it is.
reading = copy.deepcopy(p)
reading["entries"][2]["solution"] = "TOO"
held = copy.deepcopy(p)
archive.merge_answers(held, reading, reread=True)
check("a reread does not change a hand light", held["entries"][2]["solution"] == "TEA")
reading["entries"][2]["solution"] = None
archive.merge_answers(held, reading, reread=True, drop={"2-down"})
check("a reread does not drop a hand light", held["entries"][2]["solution"] == "TEA")

# A reading's answer that crosses a hand letter on another is not taken.
other = puzzle()
other["entries"][0]["solution"] = None
H.fill(other, 2, "down", "TEA", today="2026-11-06")
reading = puzzle()
reading["entries"][0]["solution"] = "CUR"
archive.merge_answers(other, reading)
check("a reading crossing a hand letter is not taken", other["entries"][0]["solution"] is None)

print("FAILED" if fails else "ok")
raise SystemExit(1 if fails else 0)
