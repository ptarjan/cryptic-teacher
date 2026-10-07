#!/bin/bash
# Does tools/file_gale_listener.py join a Gale Listener's clue reading, its
# exact grid and the later issue's report into a puzzle the write path's
# validators pass (one with a clue unread only to --out): a faint bar the numbering hides put back when exactly one
# unsure side makes the lights the clue list's, the report found by its bars,
# a cell left unread by the letter reader settled when both its lights'
# whole reads agree, a cell nothing settles leaving its entries unanswered
# (never guessed), and a puzzle short of a step (inexact grid, no report,
# a blank clue) said so?
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
rows, side, why = f.fit_to_clues(grid, {"rows": OPEN}, clues)
check("a 6 Down clue puts back the faint bar under r1c0", ((1, 0, "b"), ["....", "b...", "....", "...."]),
      (side, rows))
plain = {k: v for k, v in clues.items() if k != "6-down"}
rows, side, why = f.fit_to_clues(grid, {"rows": OPEN}, {**plain, "9-across": {"text": "x"}})
check("no single flip mends a clue with no light", (None, "no light for 9-across"),
      (rows, why and why.split(": ", 1)[1]))
check("a count the light does not have is a disagreement", "count disagrees for 1-across",
      f.lights_fit(OPEN, {f"{n}-{d}": {"text": "x", "enumeration": "5" if (n, d) == (1, "across") else None}
                          for n, d in lts}))

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
store, inbox, out = tmp / "store", tmp / "inbox", tmp / "out"
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
got = f.run(store, inbox, out, out=log, grids_of=lambda p, sha: pages[p.name], read_letters=read_letters)
filed = json.loads((out / "listener-1.json").read_text()) if (out / "listener-1.json").exists() else {}
check("No 1 files", True, got[1].get("wrote"))
check("its report is the filled grid with its bars", {"page": "p3.pdf", "agrees": 1.0}, got[1].get("report"))
check("the crossed cell and the open one are said", ([[0, 0]], [[3, 3]]),
      (got[1]["cells"]["crossed"], got[1]["cells"]["unread"]))
check("answers on disk: none on an entry with an open cell", {"1-across": "CARD", "7-across": None, "4-down": None},
      {k: e.get("solution") for e in filed.get("entries", ())
       for k in [f"{e['number']}-{e['direction']}"] if k in ("1-across", "7-across", "4-down")})
check("its provenance is the Gale filer's, answers the paper's", ("tools/file_gale_listener.py", "newspaper", "published"),
      (filed.get("source", {}).get("acquiredBy"), filed.get("source", {}).get("retrievedFrom"),
       filed.get("solutions", {}).get("origin")))
check("No 2's inexact grid is what it lacks", "grid: no exact fit to the printed numbers", got[2].get("lacks"))
check("No 3's blank clue, and the clue read onto two lights, are what it lacks; it goes to --out alone",
      ("clues: 5-across, 2-down, 4-down", True), (got[3].get("lacks"), (out / "listener-3.json").exists()))
check("the verdicts are kept", {"1", "2", "3"}, set(json.loads((store / f.LEDGER).read_text())))
again = f.run(store, inbox, out, out=io.StringIO(), grids_of=lambda p, sha: pages[p.name], read_letters=read_letters)
check("a second run holds No 1 as it is", "already held", again[1].get("skip"))
del pages["p3.pdf"][1:]
check("with no report saved, No 1 lacks it", "report: no saved filled grid has its blocks and bars",
      f.run(store, inbox, out, write=False, out=io.StringIO(), grids_of=lambda p, sha: pages[p.name],
            read_letters=read_letters)[1].get("lacks"))
sys.exit(1 if fails else 0)
PY
