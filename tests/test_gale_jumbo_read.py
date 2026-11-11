#!/usr/bin/env python3
# Do the Times Jumbo solution pages (TimesJumbo/Solutions, fetched by tools/gale_fetch.py)
# reach the puzzles tools/gale_jumbo_read.py filed: is a page linked to its puzzle by the
# number in its title or, untitled, by its date; is each filed puzzle with a page on disk
# planned once (fa.JUMBO_SOLUTION, in the queue's lists) and again only for a new page;
# does a read take only answers that fit the grid and leave a blog's or hand's answers be;
# and does a page whose read crashed come back as due instead of "read"?
#
#     python3 tests/test_gale_jumbo_read.py
#
# A fake HOME and temp folders: no OCR, no ~/.cache, no tools/data, nothing waited on.
import _path  # puzzles tools/ on sys.path
import atexit
import os
import shutil
import sys
import tempfile
tmp = tempfile.mkdtemp()
atexit.register(shutil.rmtree, tmp, True)
os.environ["HOME"] = tmp
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import copy
import datetime
import json
from pathlib import Path
import file_archive_org_puzzles as fa
import gale_jumbo_read as gj

fails = 0


def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")


D = datetime.date
root = Path(tmp)
sols, saved, store = root / "Solutions", root / "Fetched", root / "store"
sols.mkdir()
saved.mkdir()

# --- titles and citations
check("a title's number", 477, gj.title_number("Solution to Jumbo 477"))
check("a holiday title's number", 168, gj.title_number("Solution to Bank Holiday Jumbo 168"))
check("an OCR-typo title's number", 169, gj.title_number("Jumbo Corssword 169"))
check("an Answers page has no number", None, gj.title_number("Answers."))
check("a number out of range is none", None, gj.title_number("Solution to Jumbo 12"))
check("the citation's title and date", ("Answers.", D(2014, 11, 15)),
      gj.citation('"Answers." Times, 15 Nov. 2014, p. 152. The Times Digital Archive'))

# --- the folder, listed from docs.json
docs = root / "docs.json"
docs.write_text(json.dumps({
    "TTDA/jumbo-solution/2014-11-15": {"doc": "GALE|AITKPZ288054937", "title": "Answers.", "kind": "jumbo-solution"},
    "TTDA/jumbo-solution/1998-03-14": {"doc": "BMYQQQ097178141", "title": "Solution to Jumbo 477", "kind": "jumbo-solution"},
    "TTDA/jumbo-solution/1998-03-21": {"why": "no such page"},
}))
for name in ("GALE_AITKPZ288054937.pdf", "GALE_BMYQQQ097178141.pdf", "GALE_ZZGPAS115349261.pdf", ".hidden.pdf"):
    (sols / name).write_bytes(b"not a pdf")
files = gj.solution_files(sols, docs)
check("pages dated from docs.json, an unreadable untitled one left out",
      [("GALE_BMYQQQ097178141.pdf", D(1998, 3, 14), "Solution to Jumbo 477"),
       ("GALE_AITKPZ288054937.pdf", D(2014, 11, 15), "Answers.")], files)
check("the folder is listed once", True, gj._LISTED[str(sols)] is gj._LISTED[str(sols)] and len(gj._LISTED) == 1)

# --- linking
dated = {477: D(1998, 3, 7), 569: D(2014, 11, 1), 500: D(2001, 1, 6)}
check("a numbered page links to its number, an Answers page to the puzzles just before it",
      {"GALE_BMYQQQ097178141.pdf": [477], "GALE_AITKPZ288054937.pdf": [569]}, gj.links(files, dated))
check("a numbered page does not link by date", [], gj.links([files[0]], {478: D(1998, 3, 7)})[files[0][0]])
check("candidates by number", ["GALE_BMYQQQ097178141.pdf"], gj.candidates({"number": 477, "date": "1998-03-07"}, files))
check("candidates by date", ["GALE_AITKPZ288054937.pdf"], gj.candidates({"number": 569, "date": "2014-11-01"}, files))
check("no page before its puzzle", [], gj.candidates({"number": 570, "date": "2014-11-22"}, files))

# --- the page plan: a crashed read stays due
for n in ("A.pdf", "B.pdf", "C.pdf", "D.pdf"):
    (saved / n).write_bytes(b"x")
for row in ({"file": "A.pdf", "version": gj.VERSION, "refused": "no grid on the page"},
            {"file": "B.pdf", "failed": "crashed: NameError: x", "attempts": 1, "version": None},
            {"file": "C.pdf", "failed": "crashed: NameError: x", "attempts": gj.CRASH_LIMIT, "version": gj.VERSION}):
    gj.append_row(row, store)
check("a verdict and a page crashed too often are read; a crash and a page with no row are due",
      ["jumbo:B.pdf", "jumbo:D.pdf"], sorted(u["rel"] for u in gj.plan_pages(saved, store)))
check("the pages' reason is a never-read one", {"never read (Gale fetch)"}, {u["reason"] for u in gj.plan_pages(saved, store)})

# --- the number off the page's text
check("the number after the entry address, a line apart", 139,
      gj.number_in_text("Entries should be sent to: Jumbo coming the 3\nCrossword 139, The Times, 1 Pennington Street"))
check("the banner's number", 168, gj.number_in_text("40 SPORT / JUMBO CROSSWORD 1.68\nBedtime bugle"))
check("a typo'd Jumbo word", 145, gj.number_in_text("Entries sent to: Junbo Jim's first\nCrossword 145, The Times 1 Pennington"))
check("the book advert is no number", None, gj.number_in_text("The Times Jumbo Crosswords Book 3 is available"))
check("a prize-text number", 1033, gj.number_in_text("sent to: Jumbo 1,033"))
check("a typo'd citation word", 140, gj.cite_of('"Jumbo Crosswrd 140." Times, 13 Dec. 1997, p. 92.')[0])

# --- the grid: Jumbo-sized lattices only, boxes widened when cut short
calls = []


def fake(box, pad):
    calls.append((box[0], pad))
    if box[0] == 0:
        return ["x" * 15] * 15, None
    return (["x" * 27] * 27, None) if pad > 6 else (None, "a 27x27 lattice at 70px a cell is larger than the frame")


check("the Jumbo-sized box after a bigger 15x15", ((100, 0, 1100, 1000), 27),
      (lambda r: (r[0], len(r[1])))(gj.pick_grid([(0, 0, 1000, 1000), (100, 0, 1100, 1000)], fake)))
check("the narrow pad tried, then the wide", [(0, 6), (100, 6), (100, 80)], calls)
check("only a 15x15 is no Jumbo", (None, None, "the grid on the page is 15x15, not a Jumbo's"),
      gj.pick_grid([(0, 0, 1000, 1000)], fake))
check("a refusal is the first why", "x", gj.pick_grid([(100, 0, 1100, 1000)], lambda b, p: (None, "x"))[2])
check("the title fallback follows the real titles", [(1, 2, 3, 4), (0, 0, 500, 0)],
      gj.with_fallback_title(lambda w: [(1, 2, 3, 4)], 500)([]))
check("VERSION bumped", True, gj.VERSION >= 3)


# --- the clue cut: the widest box over every title, the module's titles put back
class FakeListener:
    times_titles = staticmethod(lambda words: [(5, 5, 9, 9), (0, 0, 500, 0)])


def fake_cuts(words):
    t = FakeListener.times_titles(words)[0]
    return [((0, 0, 10, 10), [])] if t[0] == 5 else [((0, 0, 100, 200), [])]


original = FakeListener.times_titles
check("the title-less cut's wider box wins", [((0, 0, 100, 200), [])], gj.widest_cuts(fake_cuts, FakeListener)([]))
check("the titles are put back", original, FakeListener.times_titles)
check("no cut under any title is none", [], gj.widest_cuts(lambda w: [], FakeListener)([]))
check("a box's area", 200, gj.area((0, 0, 10, 20)))
check("an inverted box has no area", 0, gj.area((5, 5, 1, 1)))

# --- the queue's lists hold the new reason
import edition_queue as eq
check("ranked", True, fa.JUMBO_SOLUTION in fa.RANKS)
check("in UNFILED_FIRST", True, fa.JUMBO_SOLUTION in eq.UNFILED_FIRST)
check("answers-only (CPU_ONLY)", True, fa.JUMBO_SOLUTION in eq.CPU_ONLY)
check("evidence", True, eq.evidence_reason(fa.JUMBO_SOLUTION))

# --- the solution plan
check("nothing filed: no solution unit", [], gj.plan_solutions(store, sols, docs))
gj.append_row({"file": "E.pdf", "number": 477, "date": "1998-03-07", "whole": True, "wrote": True, "version": gj.VERSION}, store)
gj.append_row({"file": "F.pdf", "number": 478, "date": "1998-03-14", "whole": False, "version": gj.VERSION}, store)
units = gj.plan_solutions(store, sols, docs)
check("a filed puzzle with its page on disk is a unit, an unfiled one is not", ["jumbo:solution:477"], [u["rel"] for u in units])
check("the unit's reason", fa.JUMBO_SOLUTION, units[0]["reason"])
check("plan() joins the pages' and the solutions'", {"jumbo:B.pdf", "jumbo:D.pdf", "jumbo:solution:477"},
      {u["rel"] for u in gj.plan(saved, store, sols, docs)})
gj.append_solved({"number": 477, "version": gj.SOLVED_VERSION, "tried": ["GALE_BMYQQQ097178141.pdf"]}, store)
check("tried: not planned again", [], gj.plan_solutions(store, sols, docs))
(sols / "GALE_NEW000000001.pdf").write_bytes(b"x")
docs.write_text(json.dumps({
    "TTDA/jumbo-solution/1998-03-21": {"doc": "NEW000000001", "title": "Solution to Jumbo 477"},
    "TTDA/jumbo-solution/1998-03-14": {"doc": "BMYQQQ097178141", "title": "Solution to Jumbo 477"}}))
check("a new page for it makes it due again", ["jumbo:solution:477"], [u["rel"] for u in gj.plan_solutions(store, sols, docs)])

# --- a puzzle filed by hand (wrote None, whole) counts once its file exists
import fetch_puzzle
gj.append_row({"file": "H.pdf", "number": 479, "date": "1998-03-14", "whole": True, "wrote": None, "version": gj.VERSION}, store)
_pp = fetch_puzzle.puzzle_path
fetch_puzzle.puzzle_path = lambda series, n: Path(store) / f"nofile-{n}.json"
check("by hand, no puzzle file: not filed", [477], sorted(r["number"] for r in gj.filed_rows(store)))
(Path(store) / "nofile-479.json").write_text("{}")
check("by hand, file exists: filed", [477, 479], sorted(r["number"] for r in gj.filed_rows(store)))
fetch_puzzle.puzzle_path = _pp

# --- reading a solution into a puzzle
def puzzle(**over):
    e = lambda d, sol=None: {"number": 1, "direction": d, "length": 3, "position": {"x": 0, "y": 0},
                             "clue": {"text": "c"}, "solution": sol}
    p = {"id": "timesjumbo-477", "dimensions": {"cols": 3, "rows": 3}, "entries": [e("across"), e("down")],
         "source": {"acquiredBy": gj.TOOL}, "solutions": {}}
    p.update(over)
    return p


def reader(answers):
    return lambda path, index, box, crop, grid: dict(answers)


found = lambda fit: (lambda path, grid, store: (fit, 0, (0, 0, 9, 9)))
v, new = gj.solve_puzzle(puzzle(), ["a.pdf"], sols, store, found(0.99), reader({"1-across": "CAT", "1-down": "COT"}))
check("fitting answers fill the blank lights", {"1-across": "CAT", "1-down": "COT"}, v.get("filled") and
      {fa.entry_id(e): e["solution"] for e in new["entries"]})
v, new = gj.solve_puzzle(puzzle(), ["a.pdf"], sols, store, found(0.99), reader({"1-across": "CAT", "1-down": "DOG"}))
check("answers crossing on another letter are refused", (None, True), (new, "fit" in v["refused"]))
v, new = gj.solve_puzzle(puzzle(), ["a.pdf"], sols, store, found(0.99), reader({"1-across": "CATS"}))
check("an answer of the wrong length is refused", None, new)
v, new = gj.solve_puzzle(puzzle(), ["a.pdf"], sols, store, found(0.80), reader({"1-across": "CAT"}))
check("a page whose blocks are not the puzzle's is refused", (None, True), (new, "blocks" in v["refused"]))
v, new = gj.solve_puzzle(puzzle(), ["a.pdf"], sols, store, lambda *a: None, reader({"1-across": "CAT"}))
check("no grid on any page is refused", None, new)
check("the solved version moved for the square-patch grid search", True, gj.SOLVED_VERSION >= 3)
# A Times page's grid is ~38% of its width: page_grids may offer only a photo or text block (both
# "lattices"); the square patches of ink are offered too, and the block fit judges them.
_pg, _gs = gj.gi.page_grids, gj.fa.grids_on
gj.gi.page_grids = lambda img: [[10, 10, 1210, 1210]]
gj.fa.grids_on = lambda img, shaped=None: [(12, 12, 1208, 1208), (2000, 3000, 3800, 4800), (0, 0, 100, 100)]
check("square patches join page_grids' boxes, near duplicates and tiny ones dropped",
      [[10, 10, 1210, 1210], [2000, 3000, 3800, 4800]], gj.grid_candidates(object()))
gj.gi.page_grids, gj.fa.grids_on = _pg, _gs
held = puzzle()
held["entries"][0]["solution"] = "COT"
v, new = gj.solve_puzzle(held, ["a.pdf"], sols, store, found(0.99), reader({"1-across": "CAT", "1-down": "TOT"}))
check("a held answer is not overwritten", "COT", (new or held)["entries"][0]["solution"])
blog = puzzle(solutions={"blog": {"url": "x"}})
blog["entries"][0]["solution"] = "COT"
before = copy.deepcopy(blog)
v, new = gj.solve_puzzle(blog, ["a.pdf"], sols, store, found(0.99), reader({"1-across": "CAT", "1-down": "COT"}))
check("a blog's answers stand: nothing but a blank light is taken", ("COT", "COT"),
      tuple((new or blog)["entries"][i]["solution"] for i in (0, 1)))
check("the held puzzle itself is untouched", before, blog)
other = puzzle(source={"acquiredBy": "tools/archive_org_jumbo.py"})
v, new = gj.solve_puzzle(other, ["a.pdf"], sols, store, found(0.99), reader({"1-across": "CAT", "1-down": "COT"}))
check("another tool's file is never filled", None, new)

# --- a crashed page read comes back as due, and writes nothing
def boom(path, store):
    raise NameError("scan_queue")


gj.read_page, real = boom, gj.read_page
check("a crash is a failed unit", "failed", gj.read_unit("jumbo:D.pdf", saved, store))
check("the page is still due", True, "jumbo:D.pdf" in [u["rel"] for u in gj.plan_pages(saved, store)])
check("no puzzle file written", [], sorted(p.name for p in (root / "puzzles").rglob("*.json")) if (root / "puzzles").exists() else [])
gj.read_unit("jumbo:D.pdf", saved, store)
gj.read_unit("jumbo:D.pdf", saved, store)
check("settled as refused after CRASH_LIMIT crashes", False, "jumbo:D.pdf" in [u["rel"] for u in gj.plan_pages(saved, store)])
gj.read_page = real

print("FAILED" if fails else "all ok")
sys.exit(1 if fails else 0)
