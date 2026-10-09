#!/bin/bash
# Does tools/file_gale_listener.py join a Gale Listener's clue reading and
# its exact grid into an unsolved puzzle the write path's validators pass
# (one with a clue unread only to --out): a faint bar the numbering hides put
# back when exactly one unsure side makes the lights the clue list's; the
# later issue's report found by its bars, a cell left unread by the letter
# reader settled when both its lights' whole reads agree, a cell nothing
# settles leaving its entries unanswered (never guessed), and the report's
# answers kept as cross_validate's listenerreport copy, never filed; a puzzle
# short of a step (inexact grid, a blank clue) said so, and one with no
# report filed all the same?
#
#     bash tools/test_file_gale_listener.sh
#
# Synthetic readings, grids and letters in a temp dir: no OCR, no page image.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
PYTHONPATH="$REPO/tools" python3 - "$tmp" <<'PY'
import io, json, sys
from pathlib import Path
import fetch_puzzle
import file_gale_listener as f

tmp = Path(sys.argv[1])
fails = 0
def check(what, want, got):
    global fails
    print(("ok   " if want == got else "FAIL ") + what + ("" if want == got else f": expected {want!r}, got {got!r}"))
    fails += want != got

SQUARE = ["CARD", "AREA", "REAR", "DART"]
OPEN = ["....", "....", "....", "...."]
lts = f.rg.light_cells(OPEN)

# The one unsure side whose flip gives the clue list's lights.
sides = {(r, c, s): 1.0 for r in range(4) for c in range(4) for s in "rb"
         if (s == "r" and c < 3) or (s == "b" and r < 3)}
sides[(1, 0, "b")] = 1.4   # faint: a bar ending 1 Down that changes no number
sides[(0, 2, "r")] = 1.3   # faint too, but a bar there adds a light no clue has
grid = {"rows": OPEN, "sides": sides, "thin": 1.0}
clues = {f"{n}-{d}": {"text": "x"} for n, d in lts} | {"6-down": {"text": "x"}}
rows, put, *_, why, _ = f.fit_to_clues(grid, {"rows": OPEN}, lambda rows: (clues, {}))
check("a 6 Down clue puts back the faint bar under r1c0", (((1, 0, "b"),), ["....", "b...", "....", "...."]),
      (put, rows))
plain = {k: v for k, v in clues.items() if k != "6-down"}
rows, _, *_, why, _ = f.fit_to_clues(grid, {"rows": OPEN}, lambda rows: ({**plain, "9-across": {"text": "x"}}, {}))
check("no flip mends a clue with no light", (None, "no light for 9-across"),
      (rows, why and why.split(": ", 1)[1]))
check("a count the light does not have is a disagreement", "count disagrees for 1-across",
      f.lights_fit(OPEN, {f"{n}-{d}": {"text": "x", "enumeration": "5" if (n, d) == (1, "across") else None}
                          for n, d in lts}))

# The clue list laid on the lights where the page is wrong or read twice.
lids = sorted(f"{n}-{d}" for n, d in lts)
named = {lid: {"text": "clue " + "abcdefgh"[i]} for i, lid in enumerate(lids)}
twice = {**named, "9-across": {"text": named["5-across"]["text"].upper().replace(" ", "  ")}}
got, notes = f.mended(OPEN, twice)
check("a clue off any light with a lit clue's text was read twice", (named, ["9-across"]), (got, list(notes)))
got, _ = f.mended(OPEN, {**named, "9-across": {"text": "its own words"}})
check("one with its own words stays, and the lists disagree (mirror)", "no light for 9-across", f.lights_fit(OPEN, got))
moved = {k: v for k, v in named.items() if k != "7-across"} | {"8-across": {"text": "x"}}
got, notes = f.mended(OPEN, moved)
check("the one spare clue and the one bare light at its place are one (No 9 prints 35 for 36A)",
      (None, {"7-across": "printed as 8-across"}), (f.lights_fit(OPEN, got), notes))
far = {k: v for k, v in named.items() if k != "1-across"} | {"8-across": {"text": "x"}}
got, notes = f.mended(OPEN, far)
check("not where a clued light lies between them (mirror)", ({}, "no light for 8-across; no clue for 1-across"),
      (notes, f.lights_fit(OPEN, got)))
cite = {k: v for k, v in named.items() if k != "4-down"} | {"2-down": {"text": "Wonderful 4."}}
got, notes = f.mended(OPEN, cite)
check("a light other clues cite is printed with no clue", (None, {"4-down": "printed with no clue: other clues cite it"}),
      (f.lights_fit(OPEN, got), notes))
built = f.build({"number": 103, "name": "n", "date": "1932-03-02", "clues": got, "source": {"url": "u"}}, OPEN)
check("and is filed as a clue the page leaves out", {"missing": True},
      next(e["clue"] for e in built["entries"] if (e["number"], e["direction"]) == (4, "down")))
got, notes = f.mended(OPEN, {k: v for k, v in named.items() if k != "4-down"} | {"2-down": {"text": "See 4 across."}})
check("one cited in the other direction stays unclued (mirror)", ({}, "no clue for 4-down"), (notes, f.lights_fit(OPEN, got)))
# The list running past a light (No 8's 55 to 57 across) skips it: no reading has a line for it.
skip = lambda *gone: {k: v for k, v in named.items() if k not in gone}
got, notes = f.skipped(OPEN, skip("6-across"))
check("the one light no reading has, between two the list prints, is printed with no clue",
      (None, {"6-across": "printed with no clue: the list runs 5 to 7 across"}, {"text": "", "noCluePrinted": True}),
      (got and f.lights_fit(OPEN, got), notes, got and got.get("6-across")))
check("not the first light of a list: nothing printed before it (mirror)", {}, f.skipped(OPEN, skip("1-across"))[1])
check("not when two lights lack a line (mirror)", {}, f.skipped(OPEN, skip("6-across", "3-down"))[1])
check("not when a clue is off any light (mirror)", {},
      f.skipped(OPEN, skip("6-across") | {"9-across": {"text": "its own words"}})[1])
check("a clue read blank has its line, so is no skip (mirror)", {},
      f.skipped(OPEN, skip("6-across") | {"6-across": {"text": ""}})[1])

# A blocked grid whose unnumbered 2-cell runs are barred shut (No 17's):
# its blocks are no bars.
built = f.build({"number": 17, "name": "Listener crossword No 17: Test", "date": "1930-07-23", "clues": {},
                 "source": {"url": "u"}}, ["r.#.", "....", "#...", "...."])
check("a blocked grid's bars hold no block", ["r...", "....", "....", "...."], built.get("bars"))
check("and its blocks are no light's cell (mirror)", False,
      any((e["position"]["y"], e["position"]["x"]) == (0, 2) for e in built["entries"]))

# A misprint the readings agree on files with the clue's asPrinted, so the
# completeness check takes it.
built = f.build({"number": 17, "name": "Listener crossword No 17: Test", "date": "1930-07-23", "source": {"url": "u"},
                 "clues": {"1-across": {"text": "The plant elecampeae.", "asPrinted": ["elecampeae."]}}},
                ["....", "....", "....", "...."])
one = next(e for e in built["entries"] if (e["number"], e["direction"]) == (1, "across"))
check("a clue's asPrinted is filed with it, and the clue is no suspect",
      (["elecampeae."], []), (one["clue"].get("asPrinted"),
                              f.ocr_clues.suspect(one["clue"]["text"], printed=one["clue"]["asPrinted"])))
# A light the page prints with no clue (No 103's theme light 25D) is complete as
# {"missing": true}; a clue unread is not.
words = {lid: {"text": f"Clue {lid}."} for lid in ("1-across", "5-across", "6-across", "7-across",
                                                   "1-down", "2-down", "3-down", "4-down")}
reading = {"number": 103, "name": "Listener crossword No 103: Test", "date": "1931-02-04", "source": {"url": "u"}}
built = f.build({**reading, "clues": {**words, "4-down": {"text": "", "noCluePrinted": True}}}, ["....", "....", "....", "...."])
bare = {f"{e['number']}-{e['direction']}" for e in built["entries"] if e["clue"] == {"missing": True}}
check("a light printed with no clue files complete", ({"4-down"}, True), (bare, f.fa.complete(built, bare)))
built = f.build({**reading, "clues": {**words, "4-down": {"text": ""}}}, ["....", "....", "....", "...."])
check("a clue unread is not complete, whatever it is named (mirror)", False, f.fa.complete(built, {"4-down"}))

# A page numbering its lights otherwise (No 3) cites them so too: the filed
# clue cites the filed number, the verdict keeps the printed text.
notes = {"56-across": "printed as 58-across: the page numbers its lights as printed",
         "41-across": "printed as 42-across: the page numbers [5, 3] 27, a cell starting no light"}
cl = {"57-down": {"text": "A 100 of 58 across."}, "60-down": {"text": "We turn to 42 Across for this."},
      "46-across": {"text": "Part of 7 down."}, "56-across": {"text": "A large number."}}
got, printed = f.recited(cl, notes)
check("a clue citing a renumbered light cites its filed number; the printed text kept",
      (["A 100 of 56 across.", "We turn to 41 Across for this.", "Part of 7 down."],
       {"57-down": "A 100 of 58 across.", "60-down": "We turn to 42 Across for this."}),
      ([got[k]["text"] for k in ("57-down", "60-down", "46-across")], printed))
check("a misprinted clue number (mended's bare note) re-cites nothing (mirror)", (cl, {}),
      f.recited(cl, {"56-across": "printed as 58-across"}))
check("a citation of a light the page numbers as filed, or in the other list, stays (mirror)",
      ("Part of 58 down.", {}), (lambda r: (r[0]["x"]["text"], r[1]))(f.recited({"x": {"text": "Part of 58 down."}}, notes)))
import validate_annotations as va
errs = []
va.check_no_markup({"entries": [{"number": 1, "direction": "across", "clue": {"text": "The plant elecampane.",
                                                                          "asPrinted": ["elecampeae."]}}]}, errs)
check("an asPrinted token the clue text lacks is refused", True, any("asPrinted" in e for e in errs))

# Crossings: r0c0 unread, both its lights read whole as C...; r3c3 nothing settles.
sure = {(r, c): SQUARE[r][c] for r in range(4) for c in range(4) if (r, c) not in {(0, 0), (3, 3)}}
full = {(n, d): {"".join(SQUARE[r][c] for r, c in cells)} for (n, d), cells in lts.items()}
full.update({(1, "across"): {"CARD", "WARD"}, (7, "across"): {"DART", "DARN"}, (4, "down"): {"DART", "DARN"},
             (5, "across"): set()})
settled = f.crossed(lts, sure, full)
check("the letter both lights' fitting whole reads share settles r0c0 (WARD fits 1A, not 1D)", "C", settled.get((0, 0)))
check("two readings in both lights leave r3c3 open", None, settled.get((3, 3)))
words = f.answers(lts, settled, full)
check("the entries through an open cell have no answer", (None, None, "CARD", "REAR"),
      (words["7-across"], words["4-down"], words["1-across"], words["3-down"]))
check("nor does one no recogniser read whole", None, words["5-across"])

# The whole join, through the write path, into an --out folder.
store, inbox, out, printed = tmp / "store", tmp / "inbox", tmp / "out", tmp / "listenerreport-source"
for d in (store, inbox, out):
    d.mkdir()
ledger = {"a" * 64: {"file": "p1.pdf", "number": 1}, "b" * 64: {"file": "p3.pdf", "number": 3},
          "c" * 64: {"file": "p2.pdf", "number": 2}}
for e in ledger.values():
    (inbox / e["file"]).write_bytes(b"")
(store / "ledger.json").write_text(json.dumps(ledger))
TEXT = {"1-across": "Playing piece", "5-across": "Region", "6-across": "Back part", "7-across": "Small arrow",
        "1-down": "Postcard", "2-down": "Zone", "3-down": "At the back", "4-down": "Throw like a missile"}
def reading(n, texts):
    return {"id": f"listener-{n}", "number": n, "series": "listener", "name": f"Listener crossword No {n}: Test",
            "date": "1930-04-02", "source": {"url": f"https://go.gale.com/ps/retrieve.do?docId=GALE%7CGM{n}"},
            "clues": {k: {"text": t, "enumeration": None} for k, t in texts.items()}}
(store / "listener-1.json").write_text(json.dumps(reading(1, TEXT)))
(store / "listener-2.json").write_text(json.dumps(reading(2, TEXT)))
(store / "listener-3.json").write_text(json.dumps(reading(3, {**TEXT, "5-across": "", "2-down": TEXT["4-down"]})))
exact = {"rows": OPEN, "shortest": 2, "exact": True}
pages = {"p1.pdf": [{"grid": grid, "fit": exact}],
         "p2.pdf": [{"grid": grid, "fit": {**exact, "exact": False}}],
         "p3.pdf": [{"grid": grid, "fit": exact},
                    {"grid": {"rows": ["...", "...", "..."]}, "fit": None},
                    {"grid": {"rows": OPEN}, "fit": None}]}
read_from = []
def read_letters(report, lts):
    read_from.append(report["page"])
    return {"letters": sure, "full": full}
log = io.StringIO()
run = lambda **kw: f.run(store, inbox, out, grids_of=lambda p, sha: pages[p.name], read_letters=read_letters,
                         reports_to=printed, **kw)
got = run(out=log)
filed = json.loads((out / "listener-1.json").read_text()) if (out / "listener-1.json").exists() else {}
copy = json.loads((printed / "listener-1.json").read_text()) if (printed / "listener-1.json").exists() else {}
check("No 1 files", True, got[1].get("wrote"))
check("its report is the filled grid with its bars", {"page": "p3.pdf", "agrees": 1.0}, got[1].get("report"))
check("the crossed cell and the open one are said", ([[0, 0]], [[3, 3]]),
      (got[1]["cells"]["crossed"], got[1]["cells"]["unread"]))
check("the report's copy: none on an entry with an open cell", {"1-across": "CARD", "7-across": None, "4-down": None},
      {k: e.get("solution") for e in copy.get("entries", ())
       for k in [f"{e['number']}-{e['direction']}"] if k in ("1-across", "7-across", "4-down")})
check("the filed puzzle has no answer the report read, and is not published-solved", ([], False),
      ([e["solution"] for e in filed.get("entries", ()) if e.get("solution")],
       filed.get("solutions", {}).get("origin") == "published"))
check("its provenance is the Gale filer's", ("tools/file_gale_listener.py", "newspaper"),
      (filed.get("source", {}).get("acquiredBy"), filed.get("source", {}).get("retrievedFrom")))
shape = lambda p: [(e["number"], e["direction"], e["position"], e["length"]) for e in p.get("entries", ())]
check("each report's copy, filed or not, is listenerreport's, on the filed grid", (["listener-1", "listener-3"], True),
      (sorted(type("A", (f.cv.ListenerReport,), {"cache": printed})().ids()), shape(copy) == shape(filed) != []))
check("No 2's inexact grid is what it lacks", "grid: no exact fit to the printed numbers", got[2].get("lacks"))
check("No 3's blank clue, and the clue read onto two lights, are what it lacks; it goes to --out alone",
      ("clues: 5-across, 2-down, 4-down", True), (got[3].get("lacks"), (out / "listener-3.json").exists()))
check("the verdicts are kept", {"1", "2", "3"}, set(json.loads((store / f.LEDGER).read_text())))
again = run(out=io.StringIO())
check("a second run holds No 1 as it is", "already held", again[1].get("skip"))
seen = []
def grids_seen(p, sha):
    seen.append(p.name)
    return pages[p.name]
one = f.run(store, inbox, out, grids_of=grids_seen, read_letters=read_letters, reports_to=printed,
            out=io.StringIO(), numbers={1})
check("--number 1 files No 1 alone, reading its pages and later ones only", ([1], ["p1.pdf", "p2.pdf", "p3.pdf"]),
      (sorted(one), sorted(seen)))
check("and keeps the other verdicts in the ledger", {"1", "2", "3"}, set(json.loads((store / f.LEDGER).read_text())))
seen.clear()
f.run(store, inbox, out, grids_of=grids_seen, read_letters=read_letters, reports_to=printed,
      out=io.StringIO(), numbers={3}, write=False)
check("a page of an earlier No is not read for --number 3 (mirror)", ["p3.pdf"], seen)
del pages["p3.pdf"][1:]
(out / "listener-1.json").unlink()
bare = run(out=io.StringIO())[1]
check("with no report saved, No 1 files all the same, unsolved", (True, None, "no saved filled grid has its blocks and bars"),
      (bare.get("wrote"), bare.get("lacks"), bare.get("noReport")))

# A page with no grid on it says where the diagram is: the verdict passes it on.
_, v, _ = f.join({**reading(9, TEXT), "verdict": {"seePages": [885]}}, [], [], read_letters)
check("no grid on its pages, and the page it sends to", "grid: no unfilled grid read on its pages (it sends to p. 885)",
      v.get("lacks"))

# Greek is clue words: two clues alike only in their Latin letters (No 10's
# 20A and 3D, "... Homer.") are two clues, and keep their asPrinted Greek
# while a pair alike in every script is blanked.
greek = {"1-across": "αἰετὸς ὀξὺ—, Homer.", "1-down": "ψυχὴ δ᾽ ἐκ—πταμένη, Homer."}
r = reading(8, {**TEXT, **greek, "4-down": TEXT["2-down"]})
r["clues"]["1-across"]["asPrinted"] = ["αἰετὸς", "ὀξὺ—,"]
puzzle, v, _ = f.join(r, [{"grid": grid, "fit": exact}], [], read_letters)
clue = lambda lid: next(e["clue"] for e in puzzle["entries"] if f"{e['number']}-{e['direction']}" == lid)
check("Greek clues alike in their Latin letters are not blanked; a true duplicate is (mirror)",
      ({"2-down": "the same clue as 4-down", "4-down": "the same clue as 2-down"}, greek["1-down"], ["αἰετὸς", "ὀξὺ—,"]),
      (v.get("blanked"), clue("1-down").get("text"), clue("1-across").get("asPrinted")))
check("alike in their Greek letters too is the same clue", [["1-across", "1-down"]],
      fetch_puzzle.duplicated_clues([{"number": 1, "direction": d, "clue": {"text": greek["1-across"]}}
                                     for d in ("across", "down")]))

# join() files the skipped light unclued, but flips a faint stray bar first.
puzzle, v, _ = f.join(reading(8, {k: t for k, t in TEXT.items() if k != "6-across"}), [{"grid": grid, "fit": exact}],
                      [], read_letters)
check("a light the list skips files as a clue the page leaves out",
      ({"6-across": "printed with no clue: the list runs 5 to 7 across"}, {"missing": True}, None),
      (v.get("mended"), next(e["clue"] for e in puzzle["entries"] if (e["number"], e["direction"]) == (6, "across")),
       v.get("lacks")))
# A stray bar r0c1 splits 1A, its far half a light no clue has: never filed unclued.
stray = [".r..", "....", "....", "...."]
one = {**sides, (0, 1, "r"): 1.5, (0, 2, "r"): 0.5}
puzzle, v, _ = f.join(reading(8, TEXT), [{"grid": {**grid, "sides": one}, "fit": {**exact, "rows": stray}}],
                      [], read_letters)
check("the one faint bar whose flip mends it is flipped (mirror)",
      ([[0, 1, "r"]], None, 8), (v.get("flipped"), v.get("mended"), puzzle and len(puzzle["entries"])))
_, v, _ = f.join(reading(8, TEXT), [{"grid": {**grid, "sides": {**one, (0, 2, "r"): 1.3}}, "fit": {**exact, "rows": stray}}],
                 [], read_letters)
check("two flips that would each mend it leave the grid unused, no light called skipped (mirror)", (None, True),
      (v.get("mended"), v.get("lacks", "").startswith("grid: ")))

# The report's copy against a solve: the misread word is a lead, never a fix.
solved = json.loads(json.dumps(filed))
for e in solved["entries"]:
    e["solution"] = {"1-across": "CARD", "5-across": "AREA"}.get(f"{e['number']}-{e['direction']}")
solved["solutions"] = {"origin": "model"}
report = json.loads(json.dumps(solved))
report["entries"][[f"{e['number']}-{e['direction']}" for e in report["entries"]].index("5-across")]["solution"] = "PREA"
verdicts, _ = f.cv.majority(solved, [(f.cv.ListenerReport(), report)])
check("a report disagreeing with a model's solve is a split, not applied", [("ANSWER", "split", False)],
      [(v["class"], v["kind"], v["fixed"]) for v in verdicts])
# A page numbering a cell that starts no light (fit "stray") is read by its
# own numbers; a clue bearing the stray number means a light starts there,
# a bar we misread, and is refused.
STRAY = ["....", "....", "#..#"]
fit = {"rows": STRAY, "exact": True, "stray": [1, 2]}
listed = {k: {"text": k} for k in ("1-across", "5-across", "7-across", "1-down", "2-down", "3-down", "4-down")}
laid, notes, why = f.unstrayed(fit, listed)
check("a stray number's tail is read one back", (set(f.light_ids(STRAY)), None, {"6-across": "printed as 7-across: the page numbers [1, 2] 6, a cell starting no light"}),
      (set(laid), why, notes))
check("the lights then fit the list", None, f.lights_fit(STRAY, laid))
laid, _, why = f.unstrayed(fit, {**listed, "6-down": {"text": "a clue at the stray number"}})
check("a clue numbered at the stray cell refuses it: a misread bar (mirror)", (None, True), (laid, bool(why)))
# A page numbering its lights as printed (fit "printed", No 4's 3 and 4
# traded) has its clue list read by those numbers: each clue to its light.
OPEN = ["...", "...", "..."]
printed = {"rows": OPEN, "exact": True, "numbering": "printed", "printed": [[0, 1, 3], [0, 2, 2], [1, 0, 4]]}
listed = {k: {"text": k} for k in ("1-across", "4-across", "5-across", "1-down", "2-down", "3-down")}
laid, notes = f.as_page(OPEN, printed, listed)
check("a traded pair's clues trade lights", ("3-down", "2-down", "1-across", ["2-down", "3-down"]),
      (laid["2-down"]["text"], laid["3-down"]["text"], laid["1-across"]["text"], sorted(notes)))
check("a page numbered as the lights are leaves the list as printed (mirror)", (listed, {}),
      f.as_page(OPEN, {"rows": OPEN, "exact": True}, listed))
check("a clue numbered on no light refuses the numbering (mirror)", None,
      f.as_page(OPEN, printed, {**listed, "7-across": {"text": "x"}}))
check("a number the page prints nowhere, laid no words, is a guess and goes", f.as_page(OPEN, printed, listed),
      f.as_page(OPEN, printed, {**listed, "0-down": {"text": ""}}))
check("a number the page prints nowhere, laid words, still refuses the numbering (mirror)", None,
      f.as_page(OPEN, printed, {**listed, "0-down": {"text": "and you get"}}))
check("a number in a cell starting no light, out of reading order, refuses the numbering (mirror)", None,
      f.as_page(OPEN, {**printed, "printed": [[0, 1, 5], [1, 1, 2]]}, {}))
# No 3 prints 27 in a cell starting no light and skips 47: the fit chases
# both numbers with the unsure sides, losing a real bar and adding a false
# one. The grid as its widths read it, numbered as printed, is the clue
# list's, so it is taken.
FITTED = ["...", "r..", "..."]   # a false bar starts 5 Across at (1, 1)
page = [[0, 0, 1], [0, 1, 2], [0, 2, 3], [1, 0, 4], [1, 1, 5], [2, 0, 7]]
g = {"grid": {"rows": OPEN}, "fit": {"rows": FITTED, "exact": True, "stray": None, "printed": page}}
listed = {k: {"text": k} for k in ("1-across", "4-across", "7-across", "1-down", "2-down", "3-down")}
got = f.as_read(g, listed)
check("a stray and a skipped number: the grid as read, the list by the page's numbers",
      (OPEN, None, {"5-across": "printed as 7-across: the page numbers its lights as printed"}),
      got and (got["rows"], f.lights_fit(OPEN, got["laid"][1]), got["laid"][2]))
check("a clue at the stray number refuses the grid as read (mirror)", None,
      f.as_read(g, {**listed, "5-across": {"text": "x"}}))
# On a page numbered as printed, the flips the clue list asks for come
# from the unsure sides alone, on the lines of the lights it disagrees on.
BARRED = ["....", "....", "....", "...."]
wide = {(r, c, s): 1.0 for r in range(4) for c in range(4) for s in "rb"
        if (s == "r" and c < 3) or (s == "b" and r < 3)}
wide[(2, 2, "b")], wide[(2, 3, "b")] = 1.45, 1.42   # 3 Down and 4 Down are three long
three = {f"{n}-{d}": {"text": "x", "enumeration": "3" if (n, d) in ((3, "down"), (4, "down")) else None}
         for n, d in f.rg.light_cells(BARRED)}
page = {"rows": BARRED, "numbering": "printed"}
rows, put, *_, why, _ = f.fit_to_clues({"rows": BARRED, "sides": wide, "thin": 1.0}, page, lambda rows: (three, {}))
check("two faint bars the list needs are both put in", ({(2, 2, "b"), (2, 3, "b")}, None), (set(put or ()), why))
far = {**wide, (2, 3, "b"): 0.9}
rows, *_ = f.fit_to_clues({"rows": BARRED, "sides": far, "thin": 1.0}, page, lambda rows: (three, {}))
check("a side read surely a rule is never flipped (mirror)", None, rows)
rows, *_ = f.fit_to_clues({"rows": BARRED, "sides": wide, "thin": 1.0}, {"rows": BARRED}, lambda rows: (three, {}))
check("a page numbered as its lights are tries one flip alone (mirror)", None, rows)
sys.exit(1 if fails else 0)
PY
