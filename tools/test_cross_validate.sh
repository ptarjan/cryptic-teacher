#!/bin/bash
# Does tools/cross_validate.py name each way two copies of a puzzle differ?
#
#     bash tools/test_cross_validate.sh
#
# Offline: one healthy puzzle in our shape, and one mutation of it per class.
set -uo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import copy
import sys

sys.path.insert(0, "tools")
import cross_validate as cv

fails = 0


def same(what, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("ok   " if ok else "FAIL ") + what + ("" if ok else f": got {got!r}, want {want!r}"))


def entry(n, d, x, y, sol, text, enum=None):
    clue = {"text": text, "enumeration": enum or str(len(sol))}
    return {"number": n, "direction": d, "position": {"x": x, "y": y},
            "length": len(sol), "clue": clue, "solution": sol}


base = {"id": "telegraph-1", "dimensions": {"cols": 3, "rows": 3}, "entries": [
    entry(1, "across", 0, 0, "CAT", "Tom’s pet"), entry(1, "down", 0, 0, "CAB", "Taxi"),
    entry(2, "down", 2, 0, "TOE", "Digit"), entry(3, "across", 0, 2, "BEE", "Buzzer")]}


def classes(mutate):
    ours = copy.deepcopy(base)
    mutate(ours)
    return sorted(m["class"] for m in cv.diff(ours, base))


same("a copy is clean", classes(lambda p: None), [])
same("quotes, dashes, case and spacing are not a clue difference",
     classes(lambda p: p["entries"][0]["clue"].update(text="TOM'S  pet!")), [])
same("other words are", classes(lambda p: p["entries"][0]["clue"].update(text="Kitty")), ["CLUE"])
same("a count", classes(lambda p: p["entries"][1]["clue"].update(enumeration="1,2")),
     ["ENUMERATION"])
same("an answer", classes(lambda p: p["entries"][3].update(solution="BYE")), ["ANSWER"])
same("a number", classes(lambda p: p["entries"][2].update(number=4)), ["NUMBERING"])
same("another grid", classes(lambda p: p["entries"][3]["position"].update(y=1)), ["GRID"])
row = next(m for m in cv.diff(
    {**base, "entries": [*base["entries"][:3], entry(3, "across", 0, 2, "BEA", "Buzzer")]}, base))
same("an answer says which crossings agree with each side",
     (row["oursCross"], row["theirsCross"]), ((2, 1), (2, 2)))

page = {"id": "crosswords/prize/30074", "number": 30074, "dimensions": {"cols": 3, "rows": 3},
        "entries": [{"number": 1, "direction": "across", "position": {"x": 0, "y": 0}, "length": 3,
                     "clue": "<i>Tom</i>&rsquo;s\u200b  pet (3)", "solution": "cat"},
                    {"number": 2, "direction": "down", "position": {"x": 2, "y": 0}, "length": 3,
                     "clue": "See 1", "solution": "TOE"}]}
got = cv.guardian_shape(page, "https://www.theguardian.com/crosswords/prize/30074")
same("a Guardian page is read without the converter: tags, entities and the count",
     (got["id"], got["entries"][0]["clue"], got["entries"][0]["solution"]),
     ("cryptic-30074", {"text": "Tom’s pet", "enumeration": "3"}, "CAT"))
same("a Guardian pointer has no count", got["entries"][1]["clue"]["enumeration"], None)
same("a source clue with no words is no witness",
     sorted(m["class"] for m in cv.diff(base, {**base, "entries": [
         {**base["entries"][0], "clue": {"text": "", "enumeration": "1,2"}}, *base["entries"][1:]]})),
     [])

import fetch_puzzle as fp
data = {"id": "crosswords/quiptic/1090", "number": 1090, "name": "Quiptic No 1,090",
        "creator": {"name": "Pan"}, "date": 1600000000000, "dimensions": {"cols": 3, "rows": 3},
        "entries": [{"id": "1-across", "number": 1, "direction": "across",
                     "position": {"x": 0, "y": 0}, "length": 3, "group": ["1-across"],
                     "clue": " Tom’s pet (3)", "solution": "CAT"}]}
same("a clue the page prints with a space in front converts without it",
     fp.convert(data)["entries"][0]["clue"]["text"], "Tom’s pet")
data["entries"][0]["clue"] = "\u2002\u2002\u2002\u2002\u2002 9 (5)"
same("a typeset gap in front is the setter's and stays (cryptic-30059 14-down, SPACE)",
     fp.convert(data)["entries"][0]["clue"]["text"], "\u2002\u2002\u2002\u2002\u2002 9")
import json, puzzle_schema
held = json.load(open("puzzles/cryptic/2026/cryptic-30059.json", encoding="utf-8"))
gap = [e for e in held["entries"] if (e["number"], e["direction"]) == (14, "down")][0]
same("the schema takes the typeset gap", puzzle_schema.validate(held), [])
gap["clue"]["text"] = " 9"
same("and refuses a stray plain space", len(puzzle_schema.validate(held)), 1)
same("a note's sentences that are only a link are not kept",
     [fp.preamble("Eight solutions are of a kind.Click here for annotated solutions."),
      fp.preamble("For a printable version of this crossword, click here."),
      fp.preamble("To see the clues please click here Method: fit them in.")],
     ["Eight solutions are of a kind.", None, "To see the clues please click here Method: fit them in."])

INDY = b"""<?xml version="1.0" encoding="UTF-8"?>
<crossword-compiler xmlns="http://crossword.info/xml/crossword-compiler">
<rectangular-puzzle xmlns="http://crossword.info/xml/rectangular-puzzle">
<metadata><title>No. 12,001 by Tester</title><creator>Tester</creator></metadata>
<crossword><grid width="3" height="3">
<cell x="1" y="1" solution="C"/><cell x="2" y="1" solution="A"/><cell x="3" y="1" solution="T"/>
<cell x="1" y="2" solution="A"/><cell x="2" y="2" type="block"/><cell x="3" y="2" solution="O"/>
<cell x="1" y="3" solution="B"/><cell x="2" y="3" solution="E"/><cell x="3" y="3" solution="E"/>
</grid>
<word id="1" x="1-3" y="1"/><word id="2" x="1" y="1-3"/>
<word id="3" x="3" y="1-3"><cells x="1-3" y="3"/></word>
<clues><title>Across</title>
<clue word="1" number="1" format="3"><i>Tom</i>&#8217;s pet</clue>
<clue word="3" number="3" is-link="1">See 2</clue></clues>
<clues><title>Down</title>
<clue word="2" number="1" format="3">Taxi</clue>
<clue word="3" number="2/3" format="3.3">Digit and buzzer</clue></clues>
</crossword></rectangular-puzzle></crossword-compiler>"""
import fetch_independent as fi
indy = cv.independent_shape(INDY, "260105")
same("the feed's XML is read without the converter: id, linked runs, a See stub, the count",
     (indy["id"], [(e["number"], e["direction"], e["solution"], e["clue"]["enumeration"])
                   for e in indy["entries"]]),
     ("independent-12001", [(1, "across", "CAT", "3"), (1, "down", "CAB", "3"),
                            (2, "down", "TOE", "3,3"), (3, "across", "BEE", None)]))
same("the converter and the separate reader agree on a clean feed day",
     cv.diff(fi.parse(INDY, "260105"), indy), [])

import corroborate
same("georgeho's missing-answer cell is no answer (it voted NAN)",
     [corroborate.georgeho_answer(a) for a in ("nan", "NAN", "Gets-ready")],
     [None, "NAN", "GETSREADY"])

blog = corroborate.Record("fifteensquared", "fifteensquared",
                          answers={(1, "across"): "CAT", (3, "across"): "BEEF"})
saved = (corroborate.fifteensquared, corroborate.georgeho, cv.read_puzzle_file)
corroborate.fifteensquared, corroborate.georgeho = (lambda p: [blog]), (lambda p: [])
cv.read_puzzle_file = lambda path: copy.deepcopy(base)
got = cv.IndyBlog().puzzle("unused")
corroborate.fifteensquared, corroborate.georgeho, cv.read_puzzle_file = saved
same("the blog witnesses only an answer that fills the light, and nothing else",
     ([e["solution"] for e in got["entries"]], cv.diff(base, got)),
     (["CAT", None, None, None], []))

known = {"id": "independent-10038", "entries": [
    {"number": 1, "direction": "down", "solution": "CAMEUPTOSCRATCH"}]}
same("a known error in the source's key is put right before the diff (SOURCE_ANSWER_WRONG)",
     cv.witness(known)["entries"][0]["solution"], "COMEUPTOSCRATCH")
same("a feed title with a comma after the number names its setter (independent-11078)",
     [fi.metadata_title(t) for t in ("No. 11078, by Phi", "No. 11,079 by Serpent", "1388 - Hypnos")],
     [("Phi", "11078"), ("Serpent", "11,079"), ("Hypnos", "1388")])
same("a space in the feed's format is the comma it stands for (independent-12317)",
     cv.independent_shape(INDY.replace(b'format="3.3"', b'format="3 3"'), "260105")
     ["entries"][2]["clue"]["enumeration"], "3,3")
fi.CLUE_FIXES[("260105", "2")] = ("Tax", "Cab")
same("a clue the feed garbles is read as printed, by the converter and the reader alike",
     [[e["clue"]["text"] for e in got["entries"] if (e["number"], e["direction"]) == (1, "down")]
      for got in (fi.parse(INDY, "260105"), cv.independent_shape(INDY, "260105"))],
     [["Cab"], ["Cab"]])
same("and a feed that prints something else is taken as it is",
     fi.fixed_clue("260105", "2", "Hackney carriage"), None)
del fi.CLUE_FIXES[("260105", "2")]
held = json.load(open("puzzles/independent/2026/independent-12407.json", encoding="utf-8"))
same("independent-12407 4-down keeps its printed clue across a re-fetch (the feed garbles it)",
     ([e["clue"]["text"] for e in held["entries"] if (e["number"], e["direction"]) == (4, "down")],
      fi.fixed_clue("260714", "17", "a well-mannered fellow, extremely ideal, being "
                    "\u201cgood breeding\u201d as they once said -")),
     (["developed there at noon to foreshadow"], "developed there at noon to foreshadow"))
saved = cv.read_puzzle_file
cv.read_puzzle_file = lambda path: {"source": {"acquiredBy": "tools/fetch_independent.py"}}
same("a refile never rewrites a file already taken from the feed",
     cv.refile_independent(cv.Independent(), "independent-12407", "unused", "260714",
                           [{"class": "CLUE"}]), None)
cv.read_puzzle_file = saved
same("the feed's CHOCOLOHICS is a known wrong answer (indysunday-1902 7-down)",
     cv.witness({"id": "indysunday-1902", "entries": [
         {"number": 7, "direction": "down", "solution": "CHOCOLOHICS"}]})["entries"][0]["solution"],
     "CHOCOHOLICS")
fi.FORMAT_FIXES[("260105", "3", "3,3")] = "6"
same("a count FORMAT_FIXES puts right is read as printed, and a trailing comma is no count",
     [cv.independent_shape(INDY, "260105")["entries"][2]["clue"]["enumeration"],
      cv.independent_shape(INDY.replace(b'format="3"', b'format="3,"'), "260105")
      ["entries"][0]["clue"]["enumeration"]],
     ["6", "3"])
del fi.FORMAT_FIXES[("260105", "3", "3,3")]
import pathlib, tempfile
cache = pathlib.Path(tempfile.mkdtemp())
(cache / "c_150607.xml").write_bytes(INDY.replace(b"No. 12,001 by Tester", b"No. 1,320 by Tester"))
class Cached(cv.Independent):
    cache = cache
saved = (cv.held, cv.read_puzzle_file)
cv.held = lambda adapter: {"indysunday-1320": "a", "independent-12001": "b"}
cv.read_puzzle_file = lambda path: {"date": {"a": "2015-06-14", "b": "2026-01-05"}[path]}
same("a puzzle is compared with the key that serves it, not its print date (2015's early Sundays)",
     Cached().ids(), {"indysunday-1320": "150607", "independent-12001": "260105"})
cv.held, cv.read_puzzle_file = saved
print("FAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
PY
