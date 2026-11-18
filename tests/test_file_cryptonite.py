#!/usr/bin/env python3
# Does tools/file_cryptonite.py place answers only on the one grid they fit,
# and number a date only when the held neighbours force the number?
#
#     python3 tests/test_file_cryptonite.py
#
# A wrong grid or a guessed number puts a puzzle on the site under a number
# the paper never printed. Fixtures are hand-built; nothing reads the corpus
# or the dataset.
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import file_cryptonite as fc

D = datetime.date

# A 5x5 with blocks at (1,1) (1,3) (3,1) (3,3): 1a 1d 2d 3d 4a 5a.
GRID = (".....", ".#.#.", ".....", ".#.#.", ".....")


def entries(four_across="IJKLM"):
    words = {(1, "across"): "ABCDE", (1, "down"): "AFINQ", (2, "down"): "CGKOS",
             (3, "down"): "EHMPU", (4, "across"): four_across, (5, "across"): "QRSTU"}
    return [{"number": n, "direction": d, "answer": w} for (n, d), w in sorted(words.items())]


def test_place():
    grid, why = fc.place(entries(), size=5)
    assert why is None and tuple(grid) == GRID, (grid, why)
    grid, why = fc.place(entries("IJXLM"), size=5)   # 4a's K crosses 2d's K
    assert grid is None and why, (grid, why)


def test_number_for():
    # Telegraph daily: Mon-Sat, never Christmas Day. Sat 22 Dec 2001 is No 100.
    days = [D(2001, 12, 22) + datetime.timedelta(days=k) for k in range(15)]
    every = {d for d in days if fc.could_print("telegraph", d)}
    # Ten printing days to Sat 5 Jan 2002, ten numbers free: every day forced.
    anchors = [(D(2001, 12, 22), 100), (D(2002, 1, 5), 111)]
    assert fc.number_for("telegraph", D(2001, 12, 27), anchors, {D(2001, 12, 27)}) == (103, None)
    # Nine numbers free: one of the ten days did not print.
    anchors = [(D(2001, 12, 22), 100), (D(2002, 1, 5), 110)]
    got, why = fc.number_for("telegraph", D(2002, 1, 2), anchors, {D(2001, 12, 27), D(2002, 1, 2)})
    assert got is None and "ambiguous" in why, (got, why)
    # ...unless the dataset shows the other nine printed: then New Year's Day did not.
    printed = every - {D(2002, 1, 1)}
    assert fc.number_for("telegraph", D(2002, 1, 2), anchors, printed) == (107, None)
    # Past the last held puzzle there is nothing to count from.
    got, why = fc.number_for("telegraph", D(2002, 1, 8), anchors, printed | {D(2002, 1, 8)})
    assert got is None and "after" in why, (got, why)
    assert fc.number_for("telegraph", D(2002, 1, 5), anchors, printed)[1] == "date already held"


def test_recase():
    caps = {"london": "London"}
    assert fc.recase("i hear london's rotten (5)", caps) == "I hear London's rotten (5)"
    assert fc.recase("odd. it's 'mad' (3)", caps) == "Odd. It's 'mad' (3)"


def test_mend_clue():
    f = "\ufffd"
    assert fc.mend_clue(f"It{f}s not one of the novices that{f}s not running") == "It's not one of the novices that's not running"
    assert fc.mend_clue(f"Brief toss of a coin {f} call!") == "Brief toss of a coin \u2014 call!"
    assert fc.mend_clue(f"{f}metal in the form of a salver{f} does fool you") == '"metal in the form of a salver" does fool you'
    assert fc.mend_clue(f"Distress call made on workers{f} holiday") == "Distress call made on workers' holiday"
    assert fc.mend_clue(f"a steak flamb{f}?") == f"a steak flamb{f}?"   # an accent is not guessed
    assert fc.mend_clue("Supply drug (crack}") == "Supply drug (crack)"


if __name__ == "__main__":
    test_mend_clue()
    test_place()
    test_number_for()
    test_recase()
    print("ok")
