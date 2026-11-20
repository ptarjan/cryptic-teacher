#!/usr/bin/env python3
# Does tools/repair_cryptonite.py plan the right edits for a held puzzle?
#
#     python3 tests/test_repair_cryptonite.py
#
# Hand-built 3x3 fixtures; nothing reads the corpus or the dataset.
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import repair_cryptonite as rc

DAY = datetime.date(2001, 9, 23)


def entry(n, d, x, y, length, sol, text):
    e = {"number": n, "direction": d, "position": {"x": x, "y": y}, "length": length,
         "clue": {"text": text, "enumeration": str(length)}}
    if sol is not None:
        e["solution"] = sol
    return e


def puzzle(a="CAT", d="COW", t="TOP"):
    return {"entries": [entry(1, "across", 0, 0, 3, a, "Pet animal"),
                        entry(1, "down", 0, 0, 3, d, "Farm beast"),
                        entry(2, "down", 2, 0, 3, t, "Peak")]}


def rows(a="cat", d="cow", t="top"):
    return [{"number": 1, "orientation": "across", "answer": a, "clue": "pet animal"},
            {"number": 1, "orientation": "down", "answer": d, "clue": "Farm, beast!"},
            {"number": 2, "orientation": "down", "answer": t, "clue": "peak"}]


def plan(p, today, earlier=None):
    groups = {("sundaytimes", DAY): today}
    if earlier:
        groups[("sundaytimes", DAY - datetime.timedelta(days=21))] = earlier
    return rc.plan_puzzle(p, "sundaytimes", DAY, groups)


def test_fill_and_truncated():
    edits, unresolved, _ = plan(puzzle(a="", d="CO"), rows())
    assert {(e["light"], e["class"], e["now"]) for e in edits} == {("1a", "fill", "CAT"), ("1d", "truncated", "COW")}
    assert not unresolved


def test_shifted_takes_this_dates_answer():
    earlier = rows(d="bow")
    edits, unresolved, _ = plan(puzzle(d="BOW"), rows(), earlier)
    (e,) = edits
    assert (e["light"], e["class"], e["was"], e["now"], e["offset"]) == ("1d", "shifted", "BOW", "COW", -21), e
    edits, unresolved, _ = plan(puzzle(d="BOW"), rows())      # no other date explains it
    assert not edits and unresolved[0]["theirs"] == "COW", unresolved


def test_kept_answers():
    # the dataset's cut-off, an anagram of ours, a clue text that is not ours
    assert plan(puzzle(), rows(d="co"))[0] == []
    assert plan(puzzle(), rows(a="act"))[0] == []
    other = rows()
    other[1]["clue"] = "a different clue"
    assert plan(puzzle(d=""), other)[0] == []


def test_crossing_refuses_a_fill():
    # 1a is kept as CAT; a dataset 1d of "DOG" would put D under its C
    edits, _, refused = plan(puzzle(d=""), rows(d="dog"))
    assert edits == [] and refused[0]["light"] == "1d", refused


def test_apply_marks_unsolved_published():
    p = puzzle(a="", d="", t="")
    p["solutions"] = {"origin": "unsolved"}
    edits, _, _ = plan(p, rows())
    rc.apply_edits(p, edits)
    assert p["solutions"]["origin"] == "published" and p["entries"][0]["solution"] == "CAT"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
