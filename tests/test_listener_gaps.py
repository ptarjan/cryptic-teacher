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
# A spooled (unanswered) ask leaves the result pending, so its caller stamps nothing done; answered, it does not.
import vlm_reader as vlm
puzzle = {"entries": [entry(3, "across", 4)]}
gl.page_columns = lambda words: [across, []] if words else None


def spooling(crops):
    raise vlm.Spooled("spooled", ["k1", "k2"])


got = lgaps.fill(puzzle, pages, spooling)
check("spooled column asks: pending, with the asks' keys", (True, ["k1", "k2"]), (got.pending, got.keys))
check("spooled: nothing filled", {}, dict(got))
puzzle = {"entries": [entry(3, "across", 4)]}
got = lgaps.fill(puzzle, pages, read_all)
check("answered asks: not pending", (False, {"3-across": "column"}), (got.pending, dict(got)))
check("a puzzle with nothing to fill is not pending", False, lgaps.fill({"entries": [entry(1, "across", 3, "Dog food")]}, pages, read_all).pending)
gl.page_columns = gl_page_columns
import file_gale_listener as fgl
check("a verdict with no pending asks is due", True, fgl.asks_answered(None))
check("an unanswered ask holds the number", False, fgl.asks_answered(["no-such-key-xyz"]))
# A transcription that dropped every clue number (verse clues) takes the OCR lines' numbers, line for line.
verse_ocr = [line(100, "1. Tom in despair has hid"), line(140, "Four words in letters two"), line(180, "3. Enjoy or else engage"),
             line(220, "Its heart to cheer is said")]
verse = ["Tom in despair has hid", "Four words in letters two", "Enjoy or else engage", "Its heart to cheer is said"]
check("number-less transcription takes the OCR numbers", [["1. " + verse[0], verse[1], "3. " + verse[2], verse[3]]],
      lgaps.numbered_by_ocr([verse[:2], verse[2:]], verse_ocr))
check("a line count that differs leaves it alone", [verse[:3]], lgaps.numbered_by_ocr([verse[:3]], verse_ocr))
check("lines that disagree with the OCR leave it alone", [["x" * 20] * 4], lgaps.numbered_by_ocr([["x" * 20] * 4], verse_ocr))
check("an already numbered transcription is unchanged", [["1. A b", "2. C d"]], lgaps.numbered_by_ocr([["1. A b", "2. C d"]], verse_ocr[:2]))
# A list's last clues lie under its last line read: the crop runs down to the page's measured clue block, and as far
# as the clues missing there need (the column's average clue height), stopping at a line under it.
L = lambda y0, y1, x0, x1, t: (y0, y1, x0, x1, t)
acol = [L(100, 130, 50, 400, "1. One"), L(140, 170, 50, 400, "2. Two"), L(180, 210, 50, 400, "3. Three (4)")]
bcol = [L(100, 130, 500, 900, "1. Uno"), L(140, 170, 500, 900, "2. Dos"), L(180, 210, 500, 900, "3. Tres"),
        L(220, 250, 500, 900, "4. Cuatro"), L(260, 290, 500, 900, "5. Cinco")]
check("missing_after counts the lights past the last numbered line", [2], lgaps.missing_after([acol], [1, 2, 3, 4, 5]))
check("missing_after stops at the next column's first number", [1, 0], lgaps.missing_after([acol, [L(100, 130, 500, 900, "5. Five")]], [1, 3, 4, 5]))
check("a column level with its sibling's block reaches the sibling's bottom", 290, lgaps.reach(acol, acol + bcol))
check("two clues missing under a column no other line is under reach their pitch each", 283, lgaps.reach(acol, acol, 2))
check("a line under the column stops the reach at its top", 230, lgaps.reach(acol, acol + [L(230, 260, 60, 390, "DOWN")], 5))
check("no page lines, no extension", 210, lgaps.reach(acol, acol, 0))
img = Image.new("RGB", (1000, 600), "white")
check("column_boxes without page lines keeps the pad", lgaps.column_boxes(img, acol), lgaps.column_boxes(img, acol, ()))
check("column_boxes runs the short column down to its sibling's bottom", True, lgaps.column_boxes(img, acol, acol + bcol, [1, 2, 3])[0][3] > lgaps.column_boxes(img, acol)[0][3])
# ENUM_FIX: build() splits a clue's own count (equal to the light's length) off its words; another bracket stays.
_b = fgl.build({"number": 1, "name": "x", "date": "2020-01-01", "source": {"url": "u"},
                "clues": {"1-across": {"text": "Its leaves yield a drink! (4)", "enumeration": None}}}, ["....", "...."])
_c = {f"{e['number']}-{e['direction']}": e["clue"] for e in _b["entries"]}
check("enum split off words", ("Its leaves yield a drink!", "4"), (_c["1-across"]["text"], _c["1-across"].get("enumeration")))
# OWN_FIX: in a list that prints no counts a blank light takes the clue the page's own OCR line for its number spells out,
# though its words are ones the OCR misread (accents) and though it repeats another clue's ("Square."); a neighbour's
# run-on text, a clue another number opens on and a clue that differs in its figures are not that line.
own_lines = [line(100, "1. Square."), line(140, "2. Square."), line(180, "3. Fruit seen in flght, on"), line(220, "the wing"),
             line(260, "4. See 13 Down."), line(300, "5. Fruit seen in flight, on the wing 6. Next clue")]
gl.page_columns = lambda words: [own_lines, []] if words else None
own_words = {"page": [(0, 0, 0, 0, "Square."), (0, 0, 0, 0, "flght,")]}
own_reply = lambda crops: ["1. Square.\n2. Square.\n3. Fruit seen in flight, on\nthe wing\n4. See 13 Down.\n5. Fruit seen in flight, on the wing"] * len(crops)
puzzle = {"entries": [entry(1, "across", 6), entry(2, "across", 6), entry(3, "across", 8), entry(4, "across", 4),
                      entry(5, "across", 4), entry(9, "across", 6, "Square."), entry(8, "across", 4, "See 25 Down.")]}
got = lgaps.fill_columns(puzzle, [(img, own_words, {})], own_reply)
check("a repeated clue its own OCR line spells is taken (1, 2); words the OCR misread (3); figures that agree (4)",
      {"1-across", "2-across", "3-across", "4-across"}, set(got))
check("an uncounted clue whose OCR line is longer stays out", False, "5-across" in got)
check("own_line: a run-on text is not the line", False, lgaps.own_line("Fruit seen in flight, on the wing and the next clue's words", own_words, "3", "across"))
check("own_line: a text opening on another number is not the line", False, lgaps.own_line("2. Square.", own_words, "1", "across"))
check("own_line: other figures are not the line", False, lgaps.own_line("See 31 Down.", own_words, "4", "across"))
gl.page_columns = gl_page_columns
sys.exit(1 if fails else 0)
