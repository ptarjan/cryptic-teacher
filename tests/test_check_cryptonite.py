#!/usr/bin/env python3
# Does tools/check_cryptonite.py classify a held puzzle against dataset rows?
#
#     python3 tests/test_check_cryptonite.py
#
# Hand-built 3x3 fixtures; nothing reads the corpus or the dataset.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_cryptonite as cc


def entry(n, d, x, y, length, sol, text):
    e = {"number": n, "direction": d, "position": {"x": x, "y": y}, "length": length,
         "clue": {"text": text, "enumeration": str(length)}}
    if sol:
        e["solution"] = sol
    return e


def puzzle(sols=("CAT", "COW", "TOP")):
    # 1a across (0,0), 1d down (0,0), 2d down (2,0): crossings C/C and T/T.
    return {"entries": [entry(1, "across", 0, 0, 3, sols[0], "Pet animal"),
                        entry(1, "down", 0, 0, 3, sols[1], "Farm beast"),
                        entry(2, "down", 2, 0, 3, sols[2], "Peak")]}


def rows(a="cat", d="cow", t="top", clue1="pet animal"):
    return [{"number": 1, "orientation": "across", "answer": a, "clue": clue1},
            {"number": 1, "orientation": "down", "answer": d, "clue": "Farm, beast!"},
            {"number": 2, "orientation": "down", "answer": t, "clue": "peak"}]


def test_classes():
    c = cc.compare(puzzle(), rows())
    assert cc.classify(c, None) == "full", c
    c = cc.compare(puzzle(), rows(clue1="a pet"))
    assert cc.classify(c, None) == "text_differs", c
    c = cc.compare(puzzle(sols=("CAT", "", "TOP")), rows())
    assert cc.classify(c, None) == "fillable" and c["fillable"][0]["answer"] == "COW", c
    assert cc.classify(cc.compare(puzzle(), rows()), "x") == "other_date"


def test_answer_disagreement_names_the_side_the_grid_backs():
    # 1d is COW in ours, CAW in theirs; 1a CAT and 2d TOP fix the top-left C and
    # the 3rd cell... only the shared first cell crosses 1a: C.
    c = cc.compare(puzzle(), rows(d="cow"))
    assert not c["answers_differ"]
    c = cc.compare(puzzle(sols=("CAT", "BOW", "TOP")), rows())
    (d,) = c["answers_differ"]
    assert d["key"] == "1d" and d["ours"] == "BOW" and d["theirs"] == "COW", d
    assert d["theirs_cross"] == (1, 1) and d["ours_cross"] == (0, 1), d


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
