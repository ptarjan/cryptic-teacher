#!/bin/bash
# Does the Telegraph bucket parser file each puzzle under the right series and number?
#
#     bash tools/test_fetch_telegraph.sh
#
# The cryptic and prize-cryptic variants carry two papers, and only the print
# day tells them apart: a Sunday is the Sunday Telegraph's sequence, any other
# day the daily's. The calendar also lists Christmas specials numbered from
# 100,000 and a few reprints under old numbers; those must never be filed as
# the puzzle the sequence says is due. Offline: a hand-built 3x3 puzzle in the
# bucket's own shape.
set -uo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import datetime
import sys

sys.path.insert(0, "tools")
import fetch_telegraph as ft

fails = 0


def same(what, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("ok   " if ok else "FAIL ") + what + ("" if ok else f": got {got!r}, want {want!r}"))


def doc(title, date, setter=""):
    return {"json": {"copy": {
        "title": title, "setter": setter, "date-publish": date,
        "gridsize": {"cols": "3", "rows": "3"},
        "words": [{"id": 1, "x": "1-3", "y": "1", "solution": "CAT"},
                  {"id": 2, "x": "1-3", "y": "3", "solution": "BEE"},
                  {"id": 3, "x": "1", "y": "1-3", "solution": "CAB"},
                  {"id": 4, "x": "3", "y": "1-3", "solution": "TOE"}],
        "clues": [{"title": "Across", "clues": [
            {"word": 1, "number": 1, "clue": "Tom&#039;s <i>pet</i>", "format": "1,2", "length": 3},
            {"word": 2, "number": 3, "clue": "Buzzer", "format": "3", "length": 3}]},
                  {"title": "Down", "clues": [
            {"word": 3, "number": 1, "clue": "Taxi", "format": "3", "length": 3},
            {"word": 4, "number": 2, "clue": "Digit", "format": "3", "length": 3}]}]},
        "meta": {"slug": "x"}}}


sun = ft.parse(doc("Prize Cryptic No 3380", "Sunday, 02 August 2026"), "prize-cryptic")
same("a Sunday prize cryptic is the Sunday Telegraph's", sun["id"], "sundaytel-3380")
sat = ft.parse(doc("Prize Cryptic No 31,307", "Saturday, 01 August 2026"), "prize-cryptic")
same("a Saturday prize cryptic is the daily's", sat["id"], "telegraph-31307")
same("its print date", sat["date"], "2026-08-01")
tough = ft.parse(doc("Toughie Crossword No 3733", "Tuesday, 04 August 2026", "Beam"),
                 "toughie-crossword")
same("a Toughie keeps its byline", (tough["id"], tough["setter"]), ("toughie-3733", "Beam"))
same("the daily prints no setter", sat.get("setter"), None)
e = {(x["number"], x["direction"]): x for x in sat["entries"]}
same("four lights", len(sat["entries"]), 4)
same("2 down sits in the last column", (e[(2, "down")]["position"], e[(2, "down")]["solution"]),
     ({"x": 2, "y": 0}, "TOE"))
same("3 across sits in the last row", e[(3, "across")]["position"], {"x": 0, "y": 2})
same("entities unescaped, italics kept beside the text",
     (e[(1, "across")]["clue"]["text"], e[(1, "across")]["clue"].get("italics")),
     ("Tom's pet", [{"at": 6, "length": 3}]))
same("the enumeration's word break", e[(1, "across")]["clue"].get("separators"),
     [{"at": 1, "mark": ","}])

bad = doc("Cryptic Crossword No 1", "Monday, 03 August 2026")
bad["json"]["copy"]["words"][0]["solution"] = "CATS"
try:
    ft.parse(bad, "cryptic-crossword-1")
    same("an answer longer than its light is refused", "parsed", "refused")
except ValueError:
    same("an answer longer than its light is refused", "refused", "refused")

# One clue served on two lights: the bucket lost one, and the parse refuses
# until SOURCE_CLUE_WRONG prints the missing clue, which a re-fetch then keeps.
import fetch_puzzle
dup = doc("Cryptic Crossword No 4", "Monday, 03 August 2026")
dup["json"]["copy"]["clues"][1]["clues"][1]["clue"] = "Taxi"
try:
    ft.parse(dup, "cryptic-crossword-1")
    same("a clue served on two lights is refused", "parsed", "refused")
except ValueError as err:
    same("a clue served on two lights is refused, naming both",
         "1-down and 2-down" in str(err), True)
fetch_puzzle.SOURCE_CLUE_WRONG[("telegraph-4", "2-down")] = ("Taxi", "Digit", "test")
e = {(x["number"], x["direction"]): x for x in ft.parse(dup, "cryptic-crossword-1")["entries"]}
same("SOURCE_CLUE_WRONG puts the printed clue back",
     (e[(1, "down")]["clue"]["text"], e[(2, "down")]["clue"]["text"]), ("Taxi", "Digit"))
del fetch_puzzle.SOURCE_CLUE_WRONG[("telegraph-4", "2-down")]

open_prize = doc("Cryptic Crossword No 1", "Monday, 03 August 2026")
open_prize["json"]["copy"]["words"][0]["solution"] = ""
p = ft.parse(open_prize, "cryptic-crossword-1")
same("a puzzle with an answer missing files unsolved, with no half key",
     (p["solutions"], [en for en in p["entries"] if "solution" in en], len(p["entries"])),
     ({"origin": "unsolved"}, [], 4))

linked = doc("Cryptic Crossword No 2", "Monday, 03 August 2026")
across = linked["json"]["copy"]["clues"][0]["clues"]
across[0].update(format="3,3", links=[{"number": 3, "direction": "Across"}])
across[1].update(clue="See 1 Across", format="")
e = {(x["number"], x["direction"]): x for x in ft.parse(linked, "cryptic-crossword-1")["entries"]}
same("a linked answer is one group on its first light",
     (e[(1, "across")].get("group"), e[(1, "across")]["clue"]["enumeration"]),
     (["1-across", "3-across"], "3,3"))
same("its other light says See and carries no enumeration",
     (e[(3, "across")]["clue"], e[(3, "across")]["solution"]), ({"text": "See 1"}, "BEE"))

# The bucket can list a continuation before the light that prints the clue.
first = doc("Cryptic Crossword No 3", "Monday, 03 August 2026")
down = first["json"]["copy"]["clues"][1]["clues"]
down[0].update(clue="See 2", format="")
down[1].update(format="3,3", links=[{"number": 1, "direction": "Down"}])
got = ft.parse(first, "cryptic-crossword-1")["entries"]
same("a continuation listed first is still one entry",
     sorted((x["number"], x["direction"]) for x in got),
     [(1, "across"), (1, "down"), (2, "down"), (3, "across")])
same("and the leader groups it", [x.get("group") for x in got if x["number"] == 2],
     [["2-down", "1-down"]])

dash = doc("Cryptic Crossword No 4", "Monday, 03 August 2026")
dash["json"]["copy"]["clues"][0]["clues"][1]["clue"] = "Buzz \x96 or hum"
same("Windows-1252 punctuation read as latin-1 is decoded",
     [x["clue"]["text"] for x in ft.parse(dash, "cryptic-crossword-1")["entries"]
      if x["number"] == 3], ["Buzz \u2013 or hum"])

acc = doc("Cryptic Crossword No 6", "Monday, 03 August 2026")
acc["json"]["copy"]["words"][0]["solution"] = "C&Agrave;T"
acc["json"]["copy"]["clues"][0]["clues"][0]["format"] = "1'2"
got = {f"{e['number']}-{e['direction']}": e for e in ft.parse(acc, "cryptic-crossword-1")["entries"]}
acc["json"]["copy"]["words"][1]["solution"] = "BEACUTEE"
got = {f"{e['number']}-{e['direction']}": e for e in ft.parse(acc, "cryptic-crossword-1")["entries"]}
same("an accent's entity left without & and ; is dropped", got["3-across"]["solution"], "BEE")
same("an accented answer is its letters, an apostrophe a break",
     (got["1-across"]["solution"], got["1-across"]["clue"]["enumeration"]), ("CAT", "1'2"))

d = datetime.date
rows = [("telegraph", 26895, d(2015, 8, 18), "v", "z"),
        ("telegraph", 26896, d(2015, 8, 19), "v", "a"),
        ("telegraph", 24885, d(2015, 8, 20), "v", "b"),
        ("telegraph", 26898, d(2015, 8, 21), "v", "c"),
        ("telegraph", 100007, d(2015, 12, 25), "v", "d"),
        ("telegraph", 27000, d(2015, 12, 28), "v", "e"),
        ("sundaytel", 2800, d(2015, 8, 23), "v", "f")]
same("reprints and specials leave the running order",
     sorted(r[1] for r in ft.in_order(rows)), [2800, 26895, 26896, 26898, 27000])
# The app's calendar for April 2016 gives 28085-28089 to two weeks running, the
# second week's documents titled with them too: neither copy is that puzzle.
rows = ([("telegraph", 28084, d(2016, 4, 9), "v", "a")]
        + [("telegraph", 28085 + i, d(2016, 4, 11 + i), "v", f"w1{i}") for i in range(5)]
        + [("telegraph", 28085 + i, d(2016, 4, 18 + i), "v", f"w2{i}") for i in range(5)]
        + [("telegraph", 28097, d(2016, 4, 25), "v", "z")])
same("a number the calendar gives twice is dropped on both days",
     sorted(r[1] for r in ft.in_order(rows)), [28084, 28097])
reprint = [("telegraph", 29595, d(2021, 2, 10), "v", "a"), ("telegraph", 29596, d(2021, 2, 11), "v", "b"),
           ("telegraph", 29597, d(2021, 2, 12), "v", "c"), ("telegraph", 29596, d(2017, 11, 28), "v", "r"),
           ("telegraph", 28600, d(2017, 11, 27), "v", "p"), ("telegraph", 28602, d(2017, 11, 29), "v", "q")]
same("a reprint under an old number years away doubles nothing",
     sorted(r[1] for r in ft.in_order(reprint)), [28600, 28602, 29595, 29596, 29597])
ft._repeated[:] = [ft.runs(rows)[1]]
same("a repeated number is the blog's to file, its neighbours the bucket's",
     [ft.served("telegraph", 28085), ft.served("telegraph", 28097)], [False, True])
ft._repeated.clear()
same("a slug names its variant",
     [ft.variant_of(s) for s in ("cryptic-crossword-37195", "prize-cryptic-39201",
                                 "toughie-crossword-93439", "prize-toughie-93445")],
     ["cryptic-crossword-1", "prize-cryptic", "toughie-crossword", "prize-toughie"])
same("the calendar's two papers split on the day",
     [ft.series_for("cryptic-crossword-1", d(2020, 2, 16)),
      ft.series_for("cryptic-crossword-1", d(2020, 2, 17))], ["sundaytel", "telegraph"])
# Refiling a blog-built file: the bucket's printed puzzle wins, except a typo
# the blog corrected, a clue the bucket garbles or an enumeration that does
# not count its own answer; an annotation travels only while it still fits.
import copy
new = ft.parse(doc("Cryptic Crossword No 5", "Monday, 03 August 2026"), "cryptic-crossword-1")
old = copy.deepcopy(new)
by = {f"{e['number']}-{e['direction']}": e for e in old["entries"]}
fresh = {f"{e['number']}-{e['direction']}": e for e in new["entries"]}
by["1-across"]["clue"]["text"] = "Tom's pet animal"
by["1-across"]["annotation"] = {"answer": "CAT", "definitions": [{"text": "pet animal"}]}
by["1-down"]["clue"]["text"] = "Car hired by the hour, briefly"
by["1-down"]["annotation"] = {"answer": "CAB", "definitions": [{"text": "Car hired"}]}
fresh["1-down"]["clue"]["text"] = "Car hired by the hour, brCar hired by the hour, brieflyiefly"
by["3-across"]["clue"]["text"] = "Buzzing insect"
fresh["3-across"]["clue"]["text"] = "Buzing insect"
by["3-across"]["clue"]["enumeration"] = "3"
fresh["3-across"]["clue"]["enumeration"] = "4"
got, notes = ft.refile(new, old)
g = {f"{e['number']}-{e['direction']}": e for e in got["entries"]}
same("an annotation whose words left the clue is dropped", "annotation" in g["1-across"], False)
same("a garbled bucket clue keeps ours, and its annotation",
     ("annotation" in g["1-down"], g["1-down"]["clue"]["text"] == by["1-down"]["clue"]["text"]),
     (True, True))
same("a bucket typo keeps our spelling", g["3-across"]["clue"]["text"], "Buzzing insect")
same("an enumeration not counting its answer keeps ours", g["3-across"]["clue"]["enumeration"], "3")
same("each kept or dropped thing is noted", len(notes), 4)
same("a link word that left the clue sinks the annotation, one still there keeps it",
     [ft.annotation_fits({"answer": "TWO", "linkWords": ["seeing"]}, "Couple observing", "TWO"),
      ft.annotation_fits({"answer": "TWO", "linkWords": ["observing"]}, "Couple observing", "TWO")],
     [False, True])
new = ft.parse(doc("Cryptic Crossword No 5", "Monday, 03 August 2026"), "cryptic-crossword-1")
old = copy.deepcopy(new)
for e in new["entries"] + old["entries"]:
    if e["number"] == 1 and e["direction"] == "across":
        e["clue"]["text"] = "See a pet"
        e["annotation"] = {"answer": "CAT", "definitions": [{"text": "a pet"}]}
new["entries"] = [{k: v for k, v in e.items() if k != "annotation"} for e in new["entries"]]
got, _ = ft.refile(new, old)
same("a clue that opens on \"See\" and is not a pointer keeps its annotation",
     ["annotation" in e for e in got["entries"] if e["number"] == 1 and e["direction"] == "across"],
     [True])
same("the bucket's era is its own", [ft.served("telegraph", 27737), ft.served("telegraph", 27738),
                                     ft.served("toughie", 2486), ft.served("times", 30000)],
     [False, True, True, False])
print("FAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
PY
