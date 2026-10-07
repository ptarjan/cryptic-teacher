#!/usr/bin/env python3
"""File the 1930s Listeners Paul saves from Gale into puzzles/listener.

    python3 tools/file_gale_listener.py              # file what the saved pages give
    python3 tools/file_gale_listener.py --dry-run    # say what each puzzle lacks, write nothing
    python3 tools/file_gale_listener.py --out DIR    # file into DIR, a puzzle with a clue unread too

A puzzle files when two readings of the pages tools/gale_listener.py has
read agree, and is checked against a third:

  - its clues: gale_listener's reading, STORE/listener-N.json (the clue
    vote every scan filer shares, ocr_clues.reconcile);
  - its grid: the unfilled grid on a page of No N, as tools/listener_grid.py
    reads it and fits its unsure sides to the printed cell numbers, used
    only when fit() calls it exact AND its lights are the clue list's:
    every clue number has a light in its direction and every light a clue.
    A fit can be exact with a faint bar missing whose far cell starts a
    light anyway (the numbering is the same), so where the lists disagree
    and exactly one unsure side (listener_grid.UNSURE) flipped makes them
    agree, it is flipped; otherwise the grid is not used;
  - its report's answers, the check: the filled grid of the "Report on
    Crossword No. N" printed about two issues later, found on any saved page as the filled grid whose
    blocks and bars agree with the puzzle's on REPORT_AGREE of the cells
    (the report's own heading is rarely read right), its letters read by
    trove_solution_ocr.read_grid_letters on the puzzle's lights. A cell is
    settled when its reads are sure (sure_letters), or when it is checked
    and the whole-light reads of both its lights that fit their settled
    letters have one letter in common there (crossed()). An entry's answer
    is read as trove_solution_ocr.read_answers accepts one: every cell
    settled, the whole light read as that word, the word known(). The
    1930 lists print no counts, so a clue's enumeration settles nothing
    here; where a reading has one, the light it names must be that long.

The puzzle files with no answers (build() takes none), so the nightly
solve fills its key. Even so read, a report misreads a letter as another
that still makes a word (PERTS for AERTS on No 1, 1 of 12), so its answers
are never filed as published: the puzzle with them goes to REPORTS
(cross_validate.ListenerReport's cache), filed or not, where
tools/cross_validate.py's `listenerreport` adapter votes on answers. A
solve the report disagrees with is a lead there, and the report never
outranks it. A puzzle whose report is not saved files all the same.

The puzzle goes through scan_queue.file_puzzle, so write_puzzle_file's
validators (puzzle_integrity.refuse_bad_write) decide it as for every other
scan filer; only a puzzle whose every clue reads true
(file_archive_org_puzzles.complete) goes to the corpus, and a held file is
replaced only when this reading improves() it (a file another tool wrote,
such as the Listener Team's PDF of No 1, is never replaced).

Each page's grids are read once per version of listener_grid.py (~35 s a
page: find_grids, then the printed numbers of each unfilled grid), each
report's letters once per puzzle grid, cached under GRIDS. STORE/filed.json
records each puzzle's verdict: what it lacks, or that it filed.
tools/gale_listener.py sync runs this after reading the new pages, so a
grid that turns exact files on the next pass.
"""
import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import cross_validate as cv
import file_archive_org_puzzles as fa
import gale_inbox as gi
import gale_listener as gl
import listener_grid as lg
import ocr_clues
import reconstruct_grid as rg
import scan_queue
import series as series_meta
import trove_solution_ocr as ts
from fetch_puzzle import puzzle_path, write_puzzle_file

TOOL = "tools/file_gale_listener.py"
SERIES = gl.lp.SERIES
GRIDS = gl.HOME / "grids"
LEDGER = "filed.json"
#: A filled grid is a puzzle's report when this share of its cells reads the
#: same block and bars as the puzzle's grid (No 1's report agrees on 96 of
#: 100 cells, No 13's page's report with No 12 on 105 of 169).
REPORT_AGREE = 0.9
#: Each report's reading, as the puzzle with its answers in.
REPORTS = cv.ListenerReport().cache


def code_key(*modules):
    """A key that changes when any of `modules`' source does."""
    h = hashlib.sha256()
    for m in modules:
        h.update(Path(m.__file__).read_bytes())
    return h.hexdigest()[:16]


# ------------------------------------------------------------ the grid

def bars_of(rows):
    """{(r, c, "r"|"b"): True} of the puzzle-format rows' bars."""
    return {(r, c, s): True for r, row in enumerate(rows) for c, ch in enumerate(row)
            for s in "rb" if ch == "+" or ch == s}


def flipped(rows, side):
    bars = bars_of(rows)
    bars[side] = not bars.get(side)
    return lg.with_bars(rows, bars)


def light_ids(rows):
    return {f"{n}-{d}" for n, d in rg.light_cells(rows)}


def lights_fit(rows, clues):
    """Why the grid's lights are not the clue list's (`clues` {light id:
    {"text", "enumeration"}}), or None: each clue read needs its light, of
    its enumeration's length where it has one, and each light a number in
    the lists."""
    have = {f"{n}-{d}": len(cells) for (n, d), cells in rg.light_cells(rows).items()}
    # A number the reader laid no words on says nothing of the grid: on a
    # light it is a clue unread (complete() refuses it), off one a guess.
    spare = sorted({lid for lid, c in clues.items() if (c.get("text") or "").strip()} - set(have), key=order)
    unclued = sorted(set(have) - set(clues), key=order)
    long = sorted((lid for lid, c in clues.items() if lid in have and c.get("enumeration")
                   and gl.al.ftp.count(c["enumeration"]) != have[lid]), key=order)
    parts = [f"{what} {', '.join(ids)}" for what, ids in (
        ("no light for", spare), ("no clue for", unclued), ("count disagrees for", long)) if ids]
    return "; ".join(parts) or None


def order(lid):
    n, d = lid.split("-")
    return d != "across", int(n)


def fit_to_clues(grid, fit, clues):
    """(rows, flipped side or None, why): the fitted grid when its lights
    are the clue list's, else the one unsure side whose flip makes them so,
    else (None, None, why)."""
    rows = fit["rows"]
    why = lights_fit(rows, clues)
    if why is None:
        return rows, None, None
    thin = max(grid["thin"], 1.0)
    fixes = [(side, alt) for side, width in grid["sides"].items()
             if lg.UNSURE[0] <= width / thin <= lg.UNSURE[1]
             for alt in [flipped(rows, side)] if lights_fit(alt, clues) is None]
    if len(fixes) == 1:
        return fixes[0][1], fixes[0][0], None
    return None, None, f"the grid's lights are not the clue list's: {why}" + (
        f" ({len(fixes)} unsure sides would each mend it)" if fixes else "")


def agreement(a, b):
    """Share of cells whose block and bars read the same in rows a and b."""
    if len(a) != len(b) or len(a[0]) != len(b[0]):
        return 0.0
    cells = [(x, y) for ra, rb in zip(a, b) for x, y in zip(ra, rb)]
    return sum(x == y for x, y in cells) / len(cells)


# ------------------------------------------------------------ the answers

def crossed(lts, letters, full):
    """{cell: letter}: `letters` (the sure reads) with each checked cell
    added where the whole-light reads (`full`) of both its lights, those
    agreeing with every letter settled in their light, have one letter in
    common there. Repeated while a cell is added, as a settled cell narrows
    its other light."""
    letters = dict(letters)
    through = {}
    for key, cells in lts.items():
        for i, rc in enumerate(cells):
            through.setdefault(rc, []).append((key, i))
    while True:
        added = {}
        for rc, keys in through.items():
            if rc in letters or len(keys) < 2:
                continue
            said = None
            for key, i in keys:
                cells = lts[key]
                fits = {w[i] for w in full.get(key, ()) if len(w) == len(cells)
                        and all(letters.get(c, ch) == ch for c, ch in zip(cells, w))}
                said = fits if said is None else said & fits
            if len(said) == 1:
                added[rc] = said.pop()
        if not added:
            return letters
        letters.update(added)


def answers(lts, letters, full):
    """{light id: word or None}: a light's word as read_answers accepts one
    off a printed solution: every cell settled, a recogniser read the whole
    light as that word, and the word is known() (on No 1's report the
    settled letters alone gave 7 wrong answers of 29, B read for D and P
    for A; with the whole read and known() 1 of 12)."""
    out = {}
    for (n, d), cells in lts.items():
        word = "".join(letters[c] for c in cells) if all(c in letters for c in cells) else None
        out[f"{n}-{d}"] = word if word and word in full.get((n, d), ()) and ts.known(word) else None
    return out


# ------------------------------------------------------------ the puzzle

def build(reading, rows):
    """The puzzle for a reading's clues and the grid's rows, unsolved."""
    entries = []
    for (n, d), cells in sorted(rg.light_cells(rows).items(), key=lambda kv: order(f"{kv[0][0]}-{kv[0][1]}")):
        lid = f"{n}-{d}"
        clue = reading["clues"].get(lid) or {}
        text = (clue.get("text") or "").strip()
        e = {"number": n, "direction": d, "position": {"x": cells[0][1], "y": cells[0][0]},
             "length": len(cells),
             "clue": {"text": text, **({"enumeration": clue["enumeration"]} if clue.get("enumeration") else {})}
             if text else {"text": "", "missing": True},
             "solution": None}
        entries.append(e)
    puzzle = {"id": series_meta.puzzle_id(SERIES, reading["number"]), "number": reading["number"],
              "series": SERIES, "name": reading["name"]}
    if reading.get("setter"):
        puzzle["setter"] = reading["setter"]
    puzzle["date"] = reading["date"]
    puzzle["dimensions"] = {"cols": len(rows[0]), "rows": len(rows)}
    if any(set(r) - {"."} for r in rows):
        puzzle["bars"] = rows
    # provenance.stamp() derives the rest of source and solutions on write.
    puzzle["source"] = {"url": reading["source"]["url"], "gridOrigin": "published"}
    puzzle["entries"] = entries
    return puzzle


def report_copy(puzzle, words):
    """`puzzle` as its report prints it: the answers `words` read off the
    report's grid in. A vote for cross_validate.py, never a file."""
    out = copy.deepcopy(puzzle)
    for e in out["entries"]:
        e["solution"] = words.get(f"{e['number']}-{e['direction']}")
    return out


def join(reading, grids, reports, read_letters):
    """(puzzle or None, verdict, the report's copy or None) for one reading: `grids` the unfilled
    grids read on its pages ({"grid", "fit"}), `reports` every filled grid
    on any saved page ({"grid", "page"}), read_letters(report, lts) its
    letters ({"letters", "full"}, read_grid_letters' shape)."""
    verdict = {"number": reading["number"]}
    clues = reading["clues"]
    if not grids:
        verdict["lacks"] = "grid: no unfilled grid read on its pages"
        return None, verdict, None
    exact = [g for g in grids if g["fit"]["exact"] and g["fit"]["shortest"] == 2]
    if not exact:
        verdict["lacks"] = "grid: no exact fit to the printed numbers" + (
            " (a 2-cell run left unnumbered)" if any(g["fit"]["exact"] for g in grids) else "")
        return None, verdict, None
    whys = []
    for g in exact:
        rows, side, why = fit_to_clues(g["grid"], g["fit"], clues)
        if rows:
            break
        whys.append(why)
    else:
        verdict["lacks"] = "grid: " + "; ".join(whys)
        return None, verdict, None
    if side:
        verdict["flipped"] = list(side)
    # One clue read onto two lights has lost the other's: both go blank
    # unless one light's count picks it (ocr_clues.one_light_each).
    lengths = {f"{n}-{d}": len(c) for (n, d), c in rg.light_cells(rows).items()}
    laid = {lid: (c.get("text") or "", c.get("enumeration"), None) for lid, c in clues.items()}
    laid, blank = ocr_clues.one_light_each(laid, {}, {
        lid for lid, (_, e, _) in laid.items() if e and gl.al.ftp.count(e) == lengths.get(lid)})
    if blank:
        verdict["blanked"] = blank
        reading = {**reading, "clues": {lid: {"text": t, "enumeration": e} for lid, (t, e, _) in laid.items()}}
    puzzle = build(reading, rows)
    scored = sorted(((agreement(rows, r["grid"]["rows"]), i) for i, r in enumerate(reports)), reverse=True)
    if not scored or scored[0][0] < REPORT_AGREE:
        verdict["noReport"] = "no saved filled grid has its blocks and bars" + (
            f" (best {scored[0][0]:.2f})" if scored else "")
        return puzzle, verdict, None
    report = reports[scored[0][1]]
    verdict["report"] = {"page": report["page"], "agrees": round(scored[0][0], 3)}
    lts = rg.light_cells(rows)
    read = read_letters(report, lts)
    sure = read["letters"]
    settled = crossed(lts, sure, read["full"])
    words = answers(lts, settled, read["full"])
    cells = {c for cs in lts.values() for c in cs}
    verdict["cells"] = {"sure": len(sure), "crossed": sorted([list(c) for c in set(settled) - set(sure)]),
                        "unread": sorted([list(c) for c in cells - set(settled)]), "of": len(cells)}
    verdict["reportAnswers"] = sum(1 for w in words.values() if w)
    return puzzle, verdict, report_copy(puzzle, words)


# ------------------------------------------------------------ the pages

def page_grids(path, sha, cache=GRIDS):
    """Every grid on the saved file's page images, cached by its hash and
    listener_grid's code: [{"grid": find_grids' dict, "fit": fit() or None}]
    (the unfilled ones fitted to their printed numbers)."""
    import numpy as np
    key = code_key(lg)
    dest = cache / f"{sha}.json"
    if dest.exists():
        got = json.loads(dest.read_text())
        if got.get("code") == key:
            return [{"grid": {**g["grid"], "sides": {tuple(json.loads(k)): v for k, v in g["grid"]["sides"].items()}},
                     "fit": g["fit"]} for g in got["grids"]]
    out = []
    for i, (img, _) in enumerate(gi.images(path)):
        gray = np.asarray(img.convert("L"), dtype=np.uint8)
        for g in lg.find_grids(gray):
            if not g["rows"] or g["why"]:
                continue
            fit = lg.fit(g, lg.printed_numbers(gray, g)) if g["filled"] <= 0.5 else None
            out.append({"grid": {"page": i, "box": list(g["box"]), "rows": g["rows"], "sides": g["sides"],
                                 "thin": g["thin"], "lattice": [list(map(float, a)) for a in g["lattice"]],
                                 "filled": g["filled"]}, "fit": fit})
    cache.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"code": key, "grids": [
        {"grid": {**g["grid"], "sides": {json.dumps(list(k)): v for k, v in g["grid"]["sides"].items()}},
         "fit": g["fit"]} for g in out]}))
    return out


def letters_reader(inbox=gl.MIRROR, cache=GRIDS):
    """read_letters for join(): read_grid_letters on the report's page,
    cached by the report, its lights and the readers' code."""
    import numpy as np

    def read(report, lts):
        key = hashlib.sha256(json.dumps([report["page"], report["grid"]["box"], code_key(ts),
                                         sorted((f"{n}-{d}", c) for (n, d), c in lts.items())]).encode()).hexdigest()[:20]
        dest = cache / f"letters-{key}.json"
        if not dest.exists():
            img, _ = gi.images(inbox / report["page"])[report["grid"]["page"]]
            gray = np.asarray(img.convert("L"), dtype=np.uint8)
            got = ts.read_grid_letters(gray, *report["grid"]["lattice"], lts)
            cache.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps({"letters": [[r, c, ch] for (r, c), ch in got["letters"].items()],
                                        "full": [[n, d, sorted(ws)] for (n, d), ws in got["full"].items()]}))
        got = json.loads(dest.read_text())
        return {"letters": {(r, c): ch for r, c, ch in got["letters"]},
                "full": {(n, d): set(ws) for n, d, ws in got["full"]}}
    return read


def run(store=gl.STORE, inbox=gl.MIRROR, puzzles=None, write=True, out=sys.stdout,
        grids_of=page_grids, read_letters=None, reports_to=REPORTS):
    """Join every reading in `store` with its grid and report; file those
    that pass, and keep each report's copy in `reports_to`. Returns
    {number: verdict}, also written to store/LEDGER."""
    read_letters = read_letters or letters_reader(Path(inbox))
    ledger = gl.load_ledger(store)
    files = [(sha, e) for sha, e in ledger.items() if (Path(inbox) / e["file"]).exists()]
    readings = {}
    for p in sorted(store.glob("listener-*.json")):
        r = json.loads(p.read_text())
        readings[r["number"]] = r
    grids = {}
    for sha, e in sorted(files, key=lambda f: (f[1].get("number") not in readings, f[1]["file"])):
        try:
            grids[e["file"]] = grids_of(Path(inbox) / e["file"], sha)
        except subprocess.TimeoutExpired as err:
            # A loaded host's OCR: the page is read again next run.
            print(f"{e['file']}: OCR timed out after {err.timeout:.0f} s; its grids are read next run", file=out)
    reports = [{"grid": g["grid"], "page": f} for f, gs in grids.items() for g in gs if g["fit"] is None]
    verdicts = {}
    for n, reading in sorted(readings.items()):
        mine = [g for sha, e in files if e.get("number") == n for g in grids.get(e["file"], ()) if g["fit"]]
        puzzle, verdict, printed = join(reading, mine, reports, read_letters)
        if printed and write:
            Path(reports_to).mkdir(parents=True, exist_ok=True)
            (Path(reports_to) / f"{printed['id']}.json").write_text(json.dumps(printed, indent=1) + "\n")
        if puzzle is not None and "lacks" not in verdict:
            whole = fa.complete(puzzle)
            if not whole:
                verdict["lacks"] = "clues: " + (", ".join(sorted(
                    (f"{e['number']}-{e['direction']}" for e in puzzle["entries"]
                     if not e["clue"].get("text") or ocr_clues.suspect(e["clue"]["text"])), key=order))
                    or "a clue is unfit to file")
            # Only a puzzle whose every clue reads true goes to the corpus;
            # --out takes every puzzle, one short of that too.
            if puzzles or whole:
                path = Path(puzzles) / f"{puzzle['id']}.json" if puzzles else puzzle_path(SERIES, n)
                if path.exists() and not fa.improves(puzzle, path, tool=TOOL):
                    verdict["skip"] = "already held"
                elif write:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    scan_queue.file_puzzle(write_puzzle_file, TOOL, path, puzzle, verdict)
        verdicts[n] = verdict
        print(f"No {n}: " + "; ".join(v for v in (
            verdict.get("lacks"), verdict.get("skip"), verdict.get("refusedWrite"), verdict.get("writeFailed"),
            "written" if verdict.get("wrote") else None,
            f"report: {verdict['noReport']}" if "noReport" in verdict else None) if v)
              + (f", {verdict['reportAnswers']}/{len(puzzle['entries'])} answers read off the report"
                 if "reportAnswers" in verdict else ""), file=out)
    if write:
        (store / LEDGER).write_text(json.dumps(verdicts, indent=1) + "\n")
    return verdicts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="say what each puzzle lacks, write nothing")
    ap.add_argument("--out", type=Path, help="file into this folder instead of the corpus")
    ap.add_argument("--store", type=Path, default=gl.STORE)
    ap.add_argument("--inbox", type=Path, default=gl.MIRROR)
    a = ap.parse_args(argv)
    run(a.store, a.inbox, a.out, write=not a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
