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
inline = lgaps.clues_in(["CLUES ignored", "1. Art Editor introduces a fishy friend (6). 4. Brown dog intervenes to save the",
                         "Light Infantry (8). 10. Sobriquet not for Mrs. Woolf's Orlando (15, three",
                         "words). 11. Prester John's son-in- law (10). 12. Take 3. away (4)."])
check("clues run on in one line are split after a count", ["1", "10", "11", "12", "4"], sorted(inline))
check("an inline clue keeps its own count", (8, "8"), inline["4"][1:])
check("a number in a clue's words does not split it", "Take 3. away", inline["12"][0])
words = lgaps.clues_in(["1. English town (15, hyphens). 2. Sounds a question (7, hyphen). 3. Legal Holiday? (Two words. 7)."
                        " 4. Three words (3, 4, five)"])
check("words printed with a count are no part of it", [(15, "15"), (7, "7"), (7, "7")],
      [words[k][1:] for k in ("1", "2", "3")])
# A clue text that is there but suspect (a digit inside a word) is replaced by the column read's clue of the
# same number when its count is the light's length and the reply names that number once.
def entry_text(n, way, length, text):
    return {"number": n, "direction": way, "length": length, "clue": {"text": text, "enumeration": str(length)}}


puzzle = {"entries": [entry_text(3, "across", 4, "Ruined by the g8te"), entry_text(5, "across", 5, "Another cl1ue"),
                      entry_text(1, "down", 4, "Cat food")]}
check("a suspect text is flagged, a plain one not", [True, True, False], [lgaps.suspect_text(e) for e in puzzle["entries"]])
asks.clear()
got = lgaps.fill_columns(puzzle, pages, read_all)
by = {f"{e['number']}-{e['direction']}": e["clue"] for e in puzzle["entries"]}
check("a suspect text takes the column read's clue of its number and count", "Ruined by the gate", by["3-across"]["text"])
check("both suspect lights replaced, the plain one kept", {"3-across": "column", "5-across": "column"}, got)
check("a plain clue is never replaced", "Cat food", by["1-down"]["text"])

puzzle = {"entries": [entry_text(3, "across", 5, "Ruined by the g8te")]}
lgaps.fill_columns(puzzle, pages, read_all)
check("a suspect text stays when the count is not the light's length", "Ruined by the g8te", puzzle["entries"][0]["clue"]["text"])

puzzle = {"entries": [entry_text(3, "across", 4, "Ruined by the g8te")]}
gl.page_columns = lambda words: [across + [line(220, "9. Spare (3)", 500)], []] if words else None
two = ["ACROSS\n3. Ruined by the gate (4)", "ACROSS\n3. Ruined by a gate (4)"]
lgaps.fill_columns(puzzle, pages, lambda crops: two[:len(crops)])
check("a number the column read gives twice leaves a suspect text", "Ruined by the g8te", puzzle["entries"][0]["clue"]["text"])
gl.page_columns = gl_page_columns
sys.exit(1 if fails else 0)
