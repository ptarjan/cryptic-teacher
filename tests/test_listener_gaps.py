#!/usr/bin/env python3
# Does listener_gaps.fill_columns take an unclued light's clue from the VLM's
# transcription of its list's column crop only when its number, count and
# text check, with one ask a column crop?
#
#     python3 tests/test_listener_gaps.py
import _path  # puts tools/ on sys.path
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
import gale_listener as gl
import listener_gaps as lgaps

fails = 0


def check(what, want, got):
    global fails
    print(("ok   " if want == got else "FAIL ") + what + ("" if want == got else f": expected {want}, got {got}"))
    fails += want != got


def entry(n, way, length, text=""):
    return {"number": n, "direction": way, "length": length,
            "clue": {"text": text} if text else {"text": "", "missing": True}}


def line(y, text, x=100):
    return (y, y + 20, x, x + 400, text)


across = [line(100, "1. Dog food (3)"), line(140, "3. Ruined by the gate (4)"), line(180, "5. Another clue (5)")]
down = [line(100, "1. Cat food (4)", 700), line(140, "2. Lost cause (5)", 700)]
gl_page_columns = gl.page_columns
gl.page_columns = lambda words: [across, down] if words else None
asks = []


def read_all(crops):
    asks.append(len(crops))
    return ["ACROSS\n1. Dog food (3)\n2. Fruit seen in flight, on\nthe wing (6)\n3. Ruined by the gate (4)\n"
            "5. Another clue (5)\nDOWN\n1. Cat food (4)"] * len(crops)


img = Image.new("L", (1000, 400), 255)
pages = [(img, {"page": [1]}, {})]
puzzle = {"entries": [entry(1, "across", 3, "Dog food"), entry(2, "across", 6), entry(3, "across", 4),
                      entry(2, "down", 5), entry(1, "down", 4, "Cat food")]}
got = lgaps.fill_columns(puzzle, pages, read_all)
by = {f"{e['number']}-{e['direction']}": e["clue"] for e in puzzle["entries"]}
check("2 across read by number and count, wrapped line joined", "Fruit seen in flight, on the wing", by["2-across"].get("text"))
check("its printed count kept", "6", by["2-across"].get("enumeration"))
check("3 across read though its text equals no clue", "Ruined by the gate", by["3-across"].get("text"))
check("2 down is no line of the transcription's down list: stays blank", "", by["2-down"]["text"])
check("filled lights named", {"2-across": "column", "3-across": "column"}, got)
check("one ask a list column holding a gap", [1, 1], asks)

puzzle = {"entries": [entry(2, "across", 5)]}
asks.clear()
lgaps.fill_columns(puzzle, pages, read_all)
check("a count that is not the light's length: no clue", "", puzzle["entries"][0]["clue"]["text"])

puzzle = {"entries": [entry(3, "across", 4), entry(9, "across", 4, "Ruined by the gate")]}
lgaps.fill_columns(puzzle, pages, read_all)
check("a text a clue already read has: no clue", "", puzzle["entries"][0]["clue"]["text"])

lgaps_read = lgaps.clues_in(["1. A thing (3)", "2. Another (4)", "1. Stray (3)", "3. Late (2)"])
check("an ascent broken by another list's number ends the column", ["1", "2"], sorted(lgaps_read))
check("a number twice ends the column at its first", ["4"], sorted(lgaps.clues_in(["4. First (3)", "4. Again (3)"])))
check("no heading: all lines are the list's", ["1. a (1)"], lgaps.sections("1. a (1)", "down"))
check("only the list's heading's lines", ["2. b (2)"], lgaps.sections("ACROSS\n1. a (1)\nDOWN\n2. b (2)", "down"))
gl.page_columns = gl_page_columns
sys.exit(1 if fails else 0)
