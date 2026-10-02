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
      fp.preamble("To see the clues please click here Method: fit them in."),
      fp.preamble("For the printable version of this crossword click here"),
      fp.preamble("Theme: rivers. Annotated solutions are available here."),
      fp.preamble("An annotated guide to solutions can be found by clicking here"),
      fp.preamble("Method: Solve the clue, which can be found here, and fit them in."),
      fp.preamble("x"),
      fp.preamble("A Hogmanay puzzle (see perimeter)For a printable version of this crossword click here")],
     ["Eight solutions are of a kind.", None, "To see the clues please click here Method: fit them in.",
      None, "Theme: rivers.", None, "Method: Solve the clue, which can be found here, and fit them in.",
      None, "A Hogmanay puzzle (see perimeter)"])

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
got = cv.FifteenSquared().puzzle("unused")
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
amuse = {"title": "No 3262", "w": 3, "h": 3,
         # Column-major: box[x][y]. CAT runs across row 0, CAB down column 0.
         "box": [["C", "A", "B"], ["A", " ", "E"], ["T", "O", "E"]],
         "placedWords": [
             {"clueNum": 1, "acrossNotDown": True, "x": 0, "y": 0, "nBoxes": 3,
              "wordLens": [3], "clue": {"clue": "<i>Tom</i>&rsquo;s pet"}},
             {"clueNum": 1, "acrossNotDown": False, "x": 0, "y": 0, "nBoxes": 3,
              "wordLens": [1, 2], "clue": {"clue": "Taxi"}}]}
got = cv.globe_shape(amuse, ("timesquick", "20260518"))
same("the Globe's box is read column-major, its wordLens as the count",
     [(e["solution"], e["clue"]["text"], e["clue"]["enumeration"]) for e in got["entries"]],
     [("CAT", "Tom’s pet", "3"), ("CAB", "Taxi", "1,2")])
same("the Globe's second 'No 3262', on 2026-05-18, is Quick 3263", got["id"], "timesquick-3263")
same("any other day is the number it prints",
     cv.globe_shape(amuse, ("globeandmail", "20260517"))["id"], "globeandmail-3262")
slashed = copy.deepcopy(base)
slashed["entries"][0]["clue"]["text"] = "Tom’s / pet"
same("against the paper's own print a blogger's slash is a clue difference",
     [m["class"] for m in cv.diff(slashed, base, exact=True)], ["CLUE"])
same("while quotes and spacing still are not",
     cv.diff({**base, "entries": [{**base["entries"][0], "clue": {"text": "Tom's  pet",
                                  "enumeration": "3"}}, *base["entries"][1:]]}, base, exact=True), [])
# The FT's PDF, as ft_pdf_puzzles.read_pdf reads it: a 3x3 frame with a
# block in its middle, CAT/TOE across, CAB/TEE down.
pdf = {"number": 13412, "grid": ["...", ".#.", "..."],
       "clues": [{"lights": [(1, "across")], "clue": "Tom’s far-reaching pet (3)", "enumeration": "3"},
                 {"lights": [(3, "across")], "clue": "Digit (3)", "enumeration": "3"},
                 {"lights": [(1, "down")], "clue": "Taxi (3)", "enumeration": "3"},
                 {"lights": [(2, "down")], "clue": "Golf peg (3)", "enumeration": "3"}]}
ft = cv.ft_shape(pdf)
same("the PDF's lights take their cells from its grid, the count off the clue",
     [(e["number"], e["direction"], e["position"], e["length"], e["clue"]["text"]) for e in ft["entries"]],
     [(1, "across", {"x": 0, "y": 0}, 3, "Tom’s far-reaching pet"), (3, "across", {"x": 0, "y": 2}, 3, "Digit"),
      (1, "down", {"x": 0, "y": 0}, 3, "Taxi"), (2, "down", {"x": 2, "y": 0}, 3, "Golf peg")])
ours = {"id": "ftcryptic-13412", "dimensions": {"cols": 3, "rows": 3}, "entries": [
    entry(1, "across", 0, 0, "CAT", "Tom’s farreaching pet"), entry(3, "across", 0, 2, "TOE", "Digit"),
    entry(1, "down", 0, 0, "CAB", "Taxi"), entry(2, "down", 2, 0, "TEE", "Golf peg")]}
same("a blogger's dropped hyphen differs from the print",
     [m["class"] for m in cv.diff(ours, ft, exact=True)], ["CLUE"])
gridless = cv.ft_shape({**pdf, "grid": None}, ours)
same("a PDF with no grid is compared on our geometry, for its clues",
     [m["class"] for m in cv.diff(ours, gridless, exact=True)], ["CLUE"])
kept = copy.deepcopy(ours)
kept["entries"][0]["annotation"] = {"definition": "Tom’s farreaching pet"}
notes = cv.reprint_marks(kept, {cv.where(e): e["clue"]["text"] for e in ft["entries"]})
same("a refile puts the printed marks back over ours, the annotation's quotation with them",
     (kept["entries"][0]["clue"]["text"], kept["entries"][0]["annotation"]["definition"], notes),
     ("Tom’s far-reaching pet", "Tom’s far-reaching pet", []))
# A refile from the PDF whose post's answers fail against its clues files the
# PDF unsolved and keeps the held answers, the grid being the same.
import fetch_puzzle, fetch_telegraph, ft_pdf_puzzles as fpp
from pathlib import Path
held = {**copy.deepcopy(ours), "date": "2010-06-15", "source": {"acquiredBy": "tools/ft_puzzles.py"},
        "solutions": {"origin": "writeup"}}
def assemble(number, pdf_, post, date, url, how):
    if post is not None:
        return None, "answers disagree with the grid"
    blank = copy.deepcopy(ours)
    for e in blank["entries"]:
        e["solution"] = None
    return {**blank, "solutions": {"origin": "unsolved"}}, None
fpp.assemble, fpp.read_pdf = assemble, lambda path: pdf
cv.read_puzzle_file = lambda path: copy.deepcopy(held)
written = {}
fetch_puzzle.write_puzzle_file = lambda path, puzzle, **kw: written.update(puzzle=puzzle, **kw)
fetch_puzzle.merge_annotations = lambda new, old: None
fetch_telegraph.refile = lambda new, old: (new, [])
adapter = cv.FT()
adapter.posts, adapter.index = {13412: {"id": 1}}, {}
adapter.raw_file = lambda number: Path("/nonexistent.pdf")
notes = cv.refile_ft(adapter, "ftcryptic-13412", Path("x.json"), 13412, [])
same("a post whose answers fail files the PDF with the held answers",
     ([e["solution"] for e in written["puzzle"]["entries"]], written["puzzle"]["solutions"]["origin"],
      written["generator"]), (["CAT", "TOE", "CAB", "TEE"], "writeup", "tools/ft_pdf_puzzles.py"))
# georgeho: the blog's rows over our own puzzle, every scrape defect no witness.
import corroborate
R = corroborate.Record
post = R("georgeho:bigdave44", "bigdave44", "u1", answers={
    (1, "across"): "CAT", (1, "down"): "CAB", (2, "down"): "TOE", (3, "across"): "BEA",
    (2, "across"): "OWL"}, clues={
    (1, "across"): "a Tom’s pet (3)", (1, "down"): ", taxi (3)", (2, "down"): ", 4. Digit",
    (3, "across"): "Buzzing (3)", (2, "across"): "Hooter (3)"})
mistitled = R("georgeho:bigdave44", "bigdave44", "u2", answers={
    (1, "across"): "DOG", (1, "down"): "DIG", (2, "down"): "GAP", (3, "across"): "PIG"})
corroborate.georgeho = lambda puzzle: [mistitled, post]
gh = cv.GeorgeHo()
theirs = gh.puzzle("telegraph-1", copy.deepcopy(base))
found = {(m["class"], m["light"]): m.get("theirs") for m in cv.diff(copy.deepcopy(base), theirs)}
same("georgeho: the post that agrees with ours, its direction letter and a clue split at "
     "its number no witness, a missing count no witness, a light we lack MISSING",
     found, {("ANSWER", "3-across"): "BEA", ("CLUE", "3-across"): "Buzzing",
             ("MISSING", "2-across"): "OWL"})
same("georgeho: a row the scrape filed under another light witnesses nothing",
     cv.misfiled(("Taxi", "3", "CAB"), base["entries"][0], {"CAT", "CAB"}, set()), True)
same("georgeho: a linked number read as one, or our own lights joined, is not MISSING",
     [cv.unplaceable(1813, "RODSTEWART", base), cv.unplaceable(2, "CATTOE", base),
      cv.unplaceable(2, "OWL", base)], [True, True, False])
same("georgeho: a Mephisto count's words are no clue, and no witness to the split",
     cv.blog_rows(R("g", "o", clues={(1, "across"): "Lite drink (8, two words)",
                                     (2, "down"): "Chest (3-4)"}))
     , {(1, "across"): ("Lite drink", None, None), (2, "down"): ("Chest", "3-4", None)})
corroborate.georgeho = lambda puzzle: [mistitled]
same("georgeho: a post holding none of our answers is another puzzle",
     gh.puzzle("telegraph-1", copy.deepcopy(base))["id"].split(":")[0], "another puzzle")
# corroborate_all: a majority of three or more copies settles a light; of
# two, the one nearer the paper's print; anything else leaves ours, a lead.
class Fake(cv.Adapter):
    def __init__(self, name, origin=None, votes=cv.VOTED, exact=False, authority=None):
        self.name, self.origin, self.votes, self.exact_clues = name, origin or name, votes, exact
        self.authority = authority


#: Our file's provenance: (source.retrievedFrom, solutions.origin).
FILED = {"blog": ("blog", "writeup"), "paper": ("publisher", "published"),
         "scan": ("newspaper", "published"), "paper, blog answers": ("publisher", "writeup")}


def bee(sol="BEE", text="Buzzer", enum=None, ann=None, filed=None):
    p = copy.deepcopy(base)
    if filed:
        p["source"] = {"retrievedFrom": FILED[filed][0]}
        p["solutions"] = {"origin": FILED[filed][1]}
    e = p["entries"][3]
    e["solution"], e["clue"]["text"] = sol, text
    if enum:
        e["clue"]["enumeration"] = enum
    if ann:
        e["annotation"] = ann
    return p


def verdict(ours, *held, write=True):
    vs, _ = cv.majority(ours, list(held))
    new = cv.apply_majority(ours, vs) if write else ours
    return [(v["class"], v["light"], v["fixed"]) for v in vs], new


# 3-across's middle cell is checked by no down light, so BYE crosses nothing.
vs, new = verdict(bee("BYE"), (Fake("a"), bee()), (Fake("b"), bee()))
same("majority: two other origins against ours, ours is fixed",
     (vs, new["entries"][3]["solution"]), ([("ANSWER", "3-across", True)], "BEE"))
vs, new = verdict(bee("BYE"), (Fake("a"), bee()))
same("majority: two copies that disagree change nothing and are a lead",
     (vs, new["entries"][3]["solution"]), ([("ANSWER", "3-across", False)], "BYE"))
vs, new = verdict(bee("BYE"), (Fake("a", "blog"), bee()), (Fake("b", "blog"), bee()))
same("majority: two reads of one origin are one vote",
     (vs, new["entries"][3]["solution"]), ([("ANSWER", "3-across", False)], "BYE"))
vs, _ = verdict(bee("BYE"), (Fake("a", "blog"), bee()), (Fake("b", "blog"), bee("BOE")),
                (Fake("c"), bee()))
same("majority: two reads of one origin that disagree abstain", vs,
     [("ANSWER", "3-across", False)])
vs, _ = verdict(bee("BYE"), (Fake("a"), bee("BOE")), (Fake("b"), bee()))
same("majority: three copies, three answers, is a lead", vs, [("ANSWER", "3-across", False)])
vs, _ = verdict(bee(text="Hummer"), (Fake("a", votes=("ANSWER",)), bee()),
                (Fake("b", votes=("ANSWER",)), bee()))
same("majority: a copy of ours with only answers swapped votes on no clue", vs, [])
vs, new = verdict(bee(text="Hummer"), (Fake("a"), bee(text="Buzzer!")),
                  (Fake("b", exact=True), bee(text="Buzzer.")))
same("majority: a clue is fixed from the paper's own print",
     (vs, new["entries"][3]["clue"]["text"]), ([("CLUE", "3-across", True)], "Buzzer."))
vs, new = verdict(bee(text="Hummer", ann="Hummer: a car"), (Fake("a"), bee()), (Fake("b"), bee()))
same("majority: a clue an annotation quotes stays ours",
     (vs, new["entries"][3]["clue"]["text"]), ([("CLUE", "3-across", False)], "Hummer"))
vs, new = verdict(bee("BYE", ann={"answer": "BYE", "definitions": []}),
                  (Fake("a"), bee()), (Fake("b"), bee()))
same("majority: a fixed answer drops the annotation written for the old one",
     (new["entries"][3]["solution"], "annotation" in new["entries"][3]), ("BEE", False))
vs, new = verdict(bee("BYE", ann={"answer": "BYE", "definitions": []}), (Fake("a"), bee()))
same("majority: an answer left standing keeps its annotation",
     new["entries"][3].get("annotation"), {"answer": "BYE", "definitions": []})
vs, new = verdict(bee(enum="1,2"), (Fake("a"), bee()), (Fake("b"), bee()))
same("majority: a count is fixed", new["entries"][3]["clue"]["enumeration"], "3")
vs, new = verdict(bee(), (Fake("a"), bee("TEE")), (Fake("b"), bee("TEE")))
same("majority: an answer that would cross a letter it does not share stays ours",
     (vs, new["entries"][3]["solution"]), ([("ANSWER", "3-across", False)], "BEE"))
vs, _ = verdict(bee(), (Fake("a"), bee(text="Buzzer (3)")), (Fake("b"), bee(text="Buzzer (3) (3)")))
same("majority: a count left at a copy's clue tail is no other word", vs, [])


def kinds(ours, *held):
    vs, _ = cv.majority(ours, list(held))
    new = cv.apply_majority(ours, vs)
    return [(v["class"], v["kind"], v["fixed"]) for v in vs], new["entries"][3]


paper = lambda name="guardian-page": Fake(name, authority=cv.PAPER)
scan = lambda name="archiveorg": Fake(name, authority=cv.SCAN)
blog = lambda name="fifteensquared": Fake(name, authority=cv.BLOG)
vs, e = kinds(bee("BYE", "Hummer", filed="blog"), (paper(), bee()))
same("authority: of two copies, the paper's print fixes a blog-built ours",
     (vs, e["solution"], e["clue"]["text"]),
     ([("ANSWER", "outranked", True), ("CLUE", "outranked", True)], "BEE", "Buzzer"))
vs, e = kinds(bee(filed="paper"), (blog(), bee("BYE", "Hummer")))
same("authority: of two copies, a blog's leaves a paper-built ours standing",
     (vs, e["solution"]), ([("ANSWER", "upheld", False), ("CLUE", "upheld", False)], "BEE"))
vs, e = kinds(bee("BYE", filed="blog"), (scan(), bee()))
same("authority: an OCR'd scan fixes a blog-built ours", (vs, e["solution"]),
     ([("ANSWER", "outranked", True)], "BEE"))
vs, e = kinds(bee(filed="scan"), (paper(), bee("BYE")))
same("authority: the paper's print fixes a scan-built ours", (vs, e["solution"]),
     ([("ANSWER", "outranked", True)], "BYE"))
vs, e = kinds(bee("BYE", filed="blog"), (blog("bigdave44"), bee()))
same("authority: two blogs are equal rank and a lead", (vs, e["solution"]),
     ([("ANSWER", "split", False)], "BYE"))
vs, e = kinds(bee("BYE", filed="paper"), (paper("telegraph-app"), bee()))
same("authority: two paper prints are equal rank and a lead", (vs, e["solution"]),
     ([("ANSWER", "split", False)], "BYE"))
vs, e = kinds(bee("BYE"), (paper(), bee()))
same("authority: a file that names no source is a lead", vs, [("ANSWER", "split", False)])
vs, e = kinds(bee("BYE", "Hummer", filed="paper, blog answers"), (blog(), bee()),)
same("authority: a blog's answer is no better than a write-up's, its clue no match for the "
     "paper's", vs, [("ANSWER", "split", False), ("CLUE", "upheld", False)])
vs, e = kinds(bee("BYE", "Hummer", filed="paper, blog answers"), (paper(), bee()))
same("authority: the paper's print fixes answers ours took from a write-up",
     (vs, e["solution"]), ([("ANSWER", "outranked", True), ("CLUE", "split", False)], "BEE"))
vs, e = kinds(bee("BYE", filed="blog"), (Fake("a", "guardian-page", authority=cv.PAPER), bee()),
              (Fake("b", "guardian-page", authority=cv.PAPER), bee()))
same("authority: two reads of the paper's one print are one copy, and fix ours",
     (vs, e["solution"]), ([("ANSWER", "outranked", True)], "BEE"))
vs, e = kinds(bee(filed="blog"), (paper(), bee("TEE")))
same("authority: an answer that would cross a letter it does not share stays ours",
     (vs, e["solution"]), ([("ANSWER", "split", False)], "BEE"))
vs, e = kinds(bee(text="Hummer", ann="Hummer: a car", filed="blog"), (paper(), bee()))
same("authority: a clue an annotation quotes stays ours", (vs, e["clue"]["text"]),
     ([("CLUE", "split", False)], "Hummer"))
vs, e = kinds(bee("BYE", filed="blog"), (paper(), bee("BOE")), (blog(), bee()))
same("authority: three votes and no majority is a lead, whoever prints them",
     vs, [("ANSWER", "split", False)])
print("FAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
PY
