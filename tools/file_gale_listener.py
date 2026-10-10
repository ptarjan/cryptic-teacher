#!/usr/bin/env python3
"""File the 1930s Listeners Paul saves from Gale into puzzles/listener.

    python3 tools/file_gale_listener.py              # file what the saved pages give
    python3 tools/file_gale_listener.py --dry-run    # say what each puzzle lacks, write nothing
    python3 tools/file_gale_listener.py --out DIR    # file into DIR, a puzzle with a clue unread too
    python3 tools/file_gale_listener.py --number 3   # just No 3: its pages and those its report may be on

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
    and one fewest set of unsure sides (listener_grid.UNSURE) flipped makes
    them agree (one side of any, or up to MOST_FLIPS of the NEAR nearest
    the bar width: No 4's four faint bars), it is flipped; otherwise the
    grid is not used. A page numbering its lights as printed (No 4 trades
    3 and 4 and skips 32) has its list read by those numbers. Failing all
    that, the grid as its widths read it is used when, numbered as the page
    prints (a number in a cell starting no light, one skipped: No 3's 27
    and 47), its lights are the clue list's (as_read). Before that the
    list is mended() where the page itself errs: a line read twice, a
    clue number misprinted, a light printed with no clue;
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
such as the Listener Team's PDF of No 1, is never replaced); else each held
clue this reading corrects (file_archive_org_puzzles.corrected_clues: a
reader's fix to its words) takes the new words.

Each page's grids are read once per version of listener_grid.py (~35 s a
page: find_grids, then the printed numbers of each unfilled grid; on the
desktop, SEARCH_SLOTS pages at once, when tools/ocr_remote.py can), each
report's letters once per puzzle grid, cached under GRIDS. STORE/filed.json
records each puzzle's verdict: what it lacks, or that it filed.
tools/gale_listener.py sync runs this after reading the new pages, so a
grid that turns exact files on the next pass.
"""
import argparse
import copy
import hashlib
import itertools
import json
import math
import re
import subprocess
import sys
import threading
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
#: With --number, a page is read for No N's report when it is of No N to
#: No N + REPORT_WITHIN (the report is printed about two issues later).
REPORT_WITHIN = 4
#: A filled grid is a puzzle's report when this share of its cells reads the
#: same block and bars as the puzzle's grid (No 1's report agrees on 96 of
#: 100 cells, No 13's page's report with No 12 on 105 of 169).
REPORT_AGREE = 0.9
#: Each report's reading, as the puzzle with its answers in.
REPORTS = cv.ListenerReport().cache


def code_key(module, *roots):
    """A key that changes when the code `roots` (names in `module`) reach
    does (tools/code_reach.py), not on an edit to the rest of the file."""
    if (module, roots) not in _KEYS:
        import code_reach
        _KEYS[(module, roots)] = code_reach.key(module, set(roots))
    return _KEYS[(module, roots)]


_KEYS = {}


def file_key(module):
    """The key caches were written under before code_key: `module`'s whole
    source. A cache entry under it is taken as current (and re-keyed)."""
    return hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()[:16]


#: What page_grids() runs of listener_grid.
GRID_CODE = ("find_grids", "fit", "printed_numbers")


# ------------------------------------------------------------ the grid

def bars_of(rows):
    """{(r, c, "r"|"b"): True} of the puzzle-format rows' bars."""
    return {(r, c, s): True for r, row in enumerate(rows) for c, ch in enumerate(row)
            for s in "rb" if ch == "+" or ch == s}


def light_ids(rows):
    return {f"{n}-{d}" for n, d in rg.light_cells(rows)}


def misfits(rows, clues):
    """(spare, unclued, long): the light ids of `clues` ({light id: {"text",
    "enumeration"}}) read with words but on no light of `rows`, of the
    lights no clue names, and of the lights whose clue's enumeration is
    not their length. A number the reader laid no words on says nothing of
    the grid: on a light it is a clue unread (complete() refuses it), off
    one a guess."""
    have = {f"{n}-{d}": len(cells) for (n, d), cells in rg.light_cells(rows).items()}
    spare = sorted({lid for lid, c in clues.items() if (c.get("text") or "").strip()} - set(have), key=order)
    unclued = sorted(set(have) - set(clues), key=order)
    long = sorted((lid for lid, c in clues.items() if lid in have and c.get("enumeration")
                   and gl.al.ftp.count(c["enumeration"]) != have[lid]), key=order)
    return spare, unclued, long


def lights_fit(rows, clues):
    """Why the grid's lights are not the clue list's (misfits), or None:
    each clue read needs its light, of its enumeration's length where it
    has one, and each light a number in the lists."""
    parts = [f"{what} {', '.join(ids)}" for what, ids in zip(
        ("no light for", "no clue for", "count disagrees for"), misfits(rows, clues)) if ids]
    return "; ".join(parts) or None


def number_of(lid):
    n, d = lid.split("-")
    return int(n), d


def mended(rows, clues):
    """(clues, notes): the clue list (`clues` {light id: {"text", ...}}) laid
    on the grid's lights where the page itself is wrong or read twice;
    `notes` {light id: what was done}. Each mend needs the page's own word:
      - a clue off any light whose text another clue on a light has is one
        line read twice (No 103's 20D, 26D's text), and goes;
      - the one clue off any light in a direction and the one light in it
        with none, at the same place in the list (no clue on a light numbered
        between them), are one: the printer set the number wrong (No 9
        prints "35." for 36A) or the reader misread it;
      - a light no clue names whose number another clue cites ("23. Wonderful
        25.") is printed with no clue (No 103's theme word, 25D): its entry's
        clue is "missing" with no text."""
    have = {f"{n}-{d}": len(cells) for (n, d), cells in rg.light_cells(rows).items()}
    clues, notes = dict(clues), {}
    text = {lid: " ".join((c.get("text") or "").split()).lower() for lid, c in clues.items()}
    for lid in sorted(set(clues) - set(have), key=order):
        twin = next((o for o in sorted(have, key=order) if o in clues and text[lid] and text[o] == text[lid]), None)
        if twin:
            del clues[lid]
            notes[lid] = f"read twice: {twin}'s text"
    for d in ("across", "down"):
        spare = [lid for lid in clues if lid not in have and text.get(lid) and lid.endswith("-" + d)]
        bare = [lid for lid in have if lid not in clues and lid.endswith("-" + d)]
        if len(spare) != 1 or len(bare) != 1:
            continue
        (s, _), (u, _) = number_of(spare[0]), number_of(bare[0])
        between = [lid for lid in clues if lid in have and lid.endswith("-" + d)
                   and min(s, u) < number_of(lid)[0] < max(s, u)]
        enum = clues[spare[0]].get("enumeration")
        if between or (enum and gl.al.ftp.count(enum) != have[bare[0]]):
            continue
        clues[bare[0]] = clues.pop(spare[0])
        notes[bare[0]] = f"printed as {spare[0]}"
    cited = " ".join(" ".join((c.get("text") or "").split()).lower() for lid, c in clues.items() if lid in have)
    for lid in sorted(set(have) - set(clues), key=order):
        n, d = number_of(lid)
        other = "down" if d == "across" else "across"
        if re.search(rf"(?<![\d,.]){n}(?!\d|\s*{other})", cited):
            clues[lid] = {"text": "", "noCluePrinted": True}
            notes[lid] = "printed with no clue: other clues cite it"
    return clues, notes


def skipped(rows, clues):
    """(clues, notes) with the light the clue list skips printed with no
    clue, else (None, {}). It is the grid's one light no reading has a line
    for (pick lays every light any reading numbers), the list printing the
    lights either side of it in its direction, and no clue off any light:
    No 8's list runs 55 to 57 across. join() asks only of a grid no faint
    bar's flip (flips) would mend, so a light the grid has wrong is never
    called unclued."""
    have = {f"{n}-{d}" for n, d in rg.light_cells(rows)}
    bare = sorted(have - set(clues))
    if len(bare) != 1 or any((c.get("text") or "").strip() for lid, c in clues.items() if lid not in have):
        return None, {}
    n, d = number_of(bare[0])
    mine = sorted(number_of(lid)[0] for lid in have if lid.endswith("-" + d))
    below, above = [m for m in mine if m < n], [m for m in mine if m > n]
    if not (below and above and f"{below[-1]}-{d}" in clues and f"{above[0]}-{d}" in clues):
        return None, {}
    return ({**clues, bare[0]: {"text": "", "noCluePrinted": True}},
            {bare[0]: f"printed with no clue: the list runs {below[-1]} to {above[0]} {d}"})


def renumbered(fit, clues):
    """`clues` keyed by the lights' numbers as light_cells gives them for
    `fit`'s rows: a page numbering every square by its place (fit
    "numbering" "position", No 0) prints a light's number as its first
    cell's place, width * row + col + 1. Unchanged when any clue's number
    starts no light, so the lights check says which."""
    if fit.get("numbering") != "position":
        return clues
    width = len(fit["rows"][0])
    to = {f"{width * r + c + 1}-{d}": f"{n}-{d}"
          for (n, d), cells in rg.light_cells(fit["rows"]).items() for r, c in cells[:1]}
    if any(lid not in to for lid in clues):
        return clues
    return {to[lid]: {**c, **({"group": [to.get(x, x) for x in c["group"]]} if c.get("group") else {})}
            for lid, c in clues.items()}


def unstrayed(fit, clues):
    """(clues keyed by the lights' own numbers, notes, why not): a page
    printing a number in a cell that starts no light (fit "stray", No 3's
    61) runs one ahead of its lights from there, and its clue list follows
    the page. None, with why, when a clue bears the stray number: a light
    does start there, so a bar was misread."""
    if not fit.get("stray"):
        return clues, {}, None
    at = tuple(fit["stray"])
    n = 1 + sum(1 for c in lg.starts(fit["rows"]) if c < at)
    if any(number_of(lid)[0] == n for lid in clues):
        return None, {}, f"a clue is numbered {n}, which the grid prints in a cell starting no light {list(at)}"
    out, notes = {}, {}
    for lid, c in clues.items():
        m, d = number_of(lid)
        mine = f"{m - 1 if m > n else m}-{d}"
        out[mine] = c
        if m > n:
            notes[mine] = f"printed as {lid}: the page numbers {list(at)} {n}, a cell starting no light"
    return out, notes, None


def as_page(rows, fit, clues):
    """(clues keyed by `rows`' light numbers, notes), or None: a page
    numbering its lights as printed (fit "numbering" "printed", No 4's 3
    and 4 traded and 32 skipped) has its clue list read by those numbers,
    each clue going to the light whose start the page numbers so. None when
    the printed numbers are no numbering of `rows` (lg.as_printed) or a
    clue's number is on no light. A number the reader laid no words on that
    the page prints nowhere is a reading's guess (No 3's "0." for a 'u'
    opening a line), and goes. Unchanged otherwise."""
    if fit.get("numbering") != "printed":
        return clues, {}
    page = lg.as_printed(rows, {(r, c): n for r, c, n in fit["printed"]})
    if page is None:
        return None
    st = lg.starts(rows)
    to = {n: st[c] for c, n in page.items()}
    out, notes = {}, {}
    for lid, c in clues.items():
        m, d = number_of(lid)
        if m not in to and not (c.get("text") or "").strip():
            continue
        if m not in to:
            return None
        mine = f"{to[m]}-{d}"
        out[mine] = c
        if to[m] != m:
            notes[mine] = f"printed as {lid}: the page numbers its lights as printed"
    return out, notes


#: A light a clue cites: "58 across", "7 down".
CITE = re.compile(r"\b(\d+)(\s*-?\s*)(across|down)\b", re.IGNORECASE)
#: A note (unstrayed, as_page) on a light the page numbers otherwise.
RENUMBERED = re.compile(r"^printed as (\d+-(?:across|down)): the page numbers")


def recited(clues, notes):
    """(clues, {light: its text as printed}) with each light a clue cites by
    its printed number cited by the number it is filed under: a page
    numbering its lights otherwise (`notes`, RENUMBERED: No 3 prints 27 in a
    cell starting no light and skips 47) cites them as it numbers them, so
    "A 100 of 58 across" means the light filed as 56 across. A misprinted
    clue number (mended's bare "printed as") is the list's slip alone, and
    the clues cite that light rightly."""
    to = {}
    for mine, note in notes.items():
        if m := RENUMBERED.match(note):
            to[m.group(1)] = mine
    if not to:
        return clues, {}

    def cite(m):
        lid = to.get(f"{m.group(1)}-{m.group(3).lower()}")
        return f"{number_of(lid)[0]}{m.group(2)}{m.group(3)}" if lid else m.group(0)
    out, printed = {}, {}
    for lid, c in clues.items():
        text = CITE.sub(cite, c.get("text") or "")
        out[lid] = {**c, "text": text} if text != (c.get("text") or "") else c
        if out[lid] is not c:
            printed[lid] = c["text"]
    return out, printed


def as_read(g, clues):
    """The fit of `g` ({"grid", "fit"}) whose rows are each side as its
    width says, numbered as the page prints (lg.as_printed: strays and
    skips), with "laid" (rows, clues, notes), when those lights are the
    clue list's; else None. The fit chases every printed number with the
    unsure sides, so a page printing a number in a cell starting no light
    and skipping another loses a real bar and gains a false one (No 3's
    27|28 bar and a bar over 47-down); the clue list, naming neither
    light, says the widths were right."""
    fit = {**g["fit"], "rows": g["grid"]["rows"], "numbering": "printed", "asRead": True,
           "stray": None, "moved": []}
    if not fit.get("printed"):
        return None
    got = as_page(fit["rows"], fit, clues)
    if got is None:
        return None
    laid, notes = mended(fit["rows"], got[0])
    if lights_fit(fit["rows"], laid) is not None:
        return None
    return {**fit, "laid": (fit["rows"], laid, {**got[1], **notes})}


def order(lid):
    n, d = lid.split("-")
    return d != "across", int(n)


#: The unsure sides, nearest BAR_RATIO first, that a search of more than
#: one flip tries, and the most flips it makes.
NEAR, MOST_FLIPS = 24, 4


def misfit_lines(rows, clues):
    """{(axis, index)}: the rows ("r", y) and columns ("b", x) holding a
    light the clue list and `rows` disagree on, its start where the list
    has a light the grid has not: an across light hangs on the bars of its
    row alone, a down light on those of its column."""
    lts = rg.light_cells(rows)
    at = {n: cells[0] for (n, _), cells in lts.items()}
    out = set()
    for lid in itertools.chain(*misfits(rows, clues)):
        n, d = number_of(lid)
        for y, x in lts.get((n, d)) or ([at[n]] if n in at else []):
            out.add(("r", y) if d == "across" else ("b", x))
    return out


def flips(grid, fit, lay):
    """[(sides, rows, clues, notes)] of each fewest set of `grid`'s unsure
    sides (listener_grid.UNSURE) whose flip in `rows` makes its lights the
    fitted rows the clue list's as lay(rows) ((clues, notes) or None) lays
    it: one flip of any, else, on a page numbering its lights as printed
    (whose numbers tie each clue to a cell, so a light hangs on the bars of
    its own row or column alone), up to MOST_FLIPS bars put in, of the NEAR
    sides nearest the bar width each lying in a row or column holding
    a light they disagree on (misfit_lines). A bar printed faint reads as a rule, so
    several go missing (No 4's four); a rule never reads as several bars,
    and taking one out (No 4's under 19 Down) gives a light no word fills.
    [] when none does."""
    thin = max(grid["thin"], 1.0)
    edge = math.log(lg.BAR_RATIO)
    unsure = sorted((side for side, width in grid["sides"].items() if lg.UNSURE[0] <= width / thin <= lg.UNSURE[1]),
                    key=lambda side: abs(math.log(grid["sides"][side] / thin) - edge))
    rows = fit["rows"]
    got = lay(rows)
    lines = misfit_lines(rows, got[0]) if got and fit.get("numbering") == "printed" else set()
    bars = bars_of(rows)
    near = [side for side in unsure if not bars.get(side)
            and (side[2], side[0] if side[2] == "r" else side[1]) in lines][:NEAR]
    for k in range(1, MOST_FLIPS + 1):
        hits = []
        for sides in itertools.combinations(unsure if k == 1 else near, k):
            alt = lg.with_bars(rows, {**bars, **{side: not bars.get(side) for side in sides}})
            got = lay(alt)
            if got and lights_fit(alt, got[0]) is None:
                hits.append((sides, alt, *got))
        if hits:
            return hits
    return []


def fit_to_clues(grid, fit, lay):
    """(rows, flipped sides, clues, notes, why, mends): the fitted grid when
    its lights are the clue list's as lay(rows) lays it, else the one
    fewest set of unsure sides whose flip makes them so (flips), else
    (None, None, None, None, why, how many fewest sets would)."""
    rows = fit["rows"]
    got = lay(rows)
    why = lights_fit(rows, got[0]) if got else "the printed numbers number none of its starts"
    if why is None:
        return rows, [], *got, None, 0
    fixes = flips(grid, fit, lay)
    if len(fixes) == 1:
        return fixes[0][1], fixes[0][0], *fixes[0][2:], None, 1
    return None, None, None, None, f"the grid's lights are not the clue list's: {why}" + (
        f" ({len(fixes)} sets of {len(fixes[0][0])} unsure sides would each mend it)" if fixes else ""), len(fixes)


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
             "clue": {"text": text, **({"enumeration": clue["enumeration"]} if clue.get("enumeration") else {}),
                      **({"asPrinted": clue["asPrinted"]} if clue.get("asPrinted") else {})}
             if text else {"missing": True} if clue.get("noCluePrinted") else {"text": "", "missing": True},
             "solution": None}
        if clue.get("group") and text:
            e["group"] = clue["group"]
        entries.append(e)
    puzzle = {"id": series_meta.puzzle_id(SERIES, reading["number"]), "number": reading["number"],
              "series": SERIES, "name": reading["name"]}
    if reading.get("setter"):
        puzzle["setter"] = reading["setter"]
    puzzle["date"] = reading["date"]
    puzzle["dimensions"] = {"cols": len(rows[0]), "rows": len(rows)}
    # A block is no light's cell (the entries say so); "bars" holds bars only.
    bars = [r.replace("#", ".") for r in rows]
    if any(set(r) - {"."} for r in bars):
        puzzle["bars"] = bars
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
        verdict["lacks"] = "grid: no unfilled grid read on its pages" + gl.see_pages(
            reading.get("verdict", {}).get("seePages"))
        return None, verdict, None
    exact = [g for g in grids if g["fit"]["exact"]]
    if not exact:
        verdict["lacks"] = "grid: no exact fit to the printed numbers"
        return None, verdict, None
    whys = []
    for g in exact:
        fit = g["fit"]
        page, shifted, why = unstrayed(g["fit"], renumbered(g["fit"], clues))
        rows = sides = None
        if page is not None:
            def lay(rows, fit=g["fit"], page=page, shifted=shifted):
                # The page's own errors are mended on the fitted grid: a faint
                # bar flipped must fit the list as mended there. A page
                # numbering its lights as printed is read again on each grid.
                got = as_page(rows if fit.get("numbering") == "printed" else fit["rows"], fit, page)
                if got is None:
                    return None
                laid, notes = mended(rows if fit.get("numbering") == "printed" else fit["rows"], got[0])
                return laid, {**shifted, **got[1], **notes}

            rows, sides, laid, notes, why, mends = fit_to_clues(g["grid"], g["fit"], lay)
            if not rows and not mends and (got := lay(g["fit"]["rows"])):
                skip, note = skipped(g["fit"]["rows"], got[0])
                if skip and lights_fit(g["fit"]["rows"], skip) is None:
                    rows, sides, laid, notes = g["fit"]["rows"], [], skip, {**got[1], **note}
        if not rows and (got := as_read(g, clues)):
            fit, (rows, laid, notes), sides = got, got["laid"], []
        if rows:
            clues = laid
            reading = {**reading, "clues": laid}
            break
        whys.append(why)
    else:
        verdict["lacks"] = "grid: " + "; ".join(whys)
        return None, verdict, None
    if sides:
        verdict["flipped"] = [list(side) for side in sides]
    if notes:
        verdict["mended"] = notes
    # The filed clue cites the numbers the solver sees; the reading in the
    # store and this verdict keep the text as printed.
    clues, cites = recited(clues, notes)
    if cites:
        verdict["cites"] = cites
        reading = {**reading, "clues": clues}
    if fit.get("moved"):
        verdict["numberMoved"] = [list(c) for c in fit["moved"]]
    if fit.get("stray"):
        verdict["strayNumber"] = fit["stray"]
    if fit.get("asRead"):
        verdict["asRead"] = True
    if fit.get("numbering") == "printed":
        verdict["numbering"] = "printed"
    # One clue read onto two lights has lost the other's: both go blank
    # unless one light's count picks it (ocr_clues.one_light_each).
    lengths = {f"{n}-{d}": len(c) for (n, d), c in rg.light_cells(rows).items()}
    laid = {lid: (c.get("text") or "", c.get("enumeration"), None) for lid, c in clues.items()}
    laid, blank = ocr_clues.one_light_each(laid, {}, {
        lid for lid, (_, e, _) in laid.items() if e and gl.al.ftp.count(e) == lengths.get(lid)})
    if blank:
        verdict["blanked"] = blank
        reading = {**reading, "clues": {lid: {**clues[lid], "text": t, "enumeration": e} for lid, (t, e, _) in laid.items()}}
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
    (the unfilled ones fitted to their printed numbers), as read back from
    the cache. Found on the desktop when tools/ocr_remote.py can (grids_there),
    else here, one page at a time a process."""
    import ocr_remote
    key = code_key(lg, *GRID_CODE)
    dest = cache / f"{sha}.json"
    if dest.exists():
        got = json.loads(dest.read_text())
        if got.get("code") == file_key(lg):
            got["code"] = key
            dest.write_text(json.dumps(got))
        if got.get("code") == key:
            return loaded_grids(got["grids"])
    got = ocr_remote.call("listener_grids", path.name, data=path.read_bytes())
    if got is None:
        with _HERE, ocr_remote.local_slot():
            grids = grids_here(path)
    else:
        grids = got[0]
    cache.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"code": key, "grids": grids}))
    return loaded_grids(json.loads(json.dumps(grids)))


#: Held while this process finds a page's grids here (~600 MB a page).
_HERE = threading.Lock()


def loaded_grids(grids):
    """page_grids' result from its cache's "grids"."""
    return [{"grid": {**g["grid"], "sides": {tuple(json.loads(k)): v for k, v in g["grid"]["sides"].items()}},
             "fit": g["fit"]} for g in grids]


def grids_here(path):
    """The cache's "grids" of the saved file `path`, found here."""
    import numpy as np
    out = []
    for i, (img, _) in enumerate(gi.images(path)):
        gray = np.asarray(img.convert("L"), dtype=np.uint8)
        for g in lg.find_grids(gray):
            if not g["rows"] or g["why"]:
                continue
            fit = lg.fit(g, lg.printed_numbers(gray, g)) if g["filled"] <= 0.5 else None
            out.append({"grid": {"page": i, "box": list(g["box"]), "rows": g["rows"],
                                 "sides": {json.dumps(list(k)): v for k, v in g["sides"].items()},
                                 "thin": g["thin"], "lattice": [list(map(float, a)) for a in g["lattice"]],
                                 "filled": g["filled"]}, "fit": fit})
    return out


def grids_there(data, name):
    """tools/ocr_remote.py's "listener_grids", run on the desktop:
    (grids_here() of the saved file named `name`, its bytes `data`, b"")."""
    import tempfile
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / name
        path.write_bytes(data)
        return grids_here(path), b""


def letters_reader(inbox=gl.MIRROR, cache=GRIDS):
    """read_letters for join(): read_grid_letters on the report's page,
    cached by the report, its lights and the readers' code."""
    import numpy as np

    def read(report, lts):
        def keyed(code):
            return hashlib.sha256(json.dumps([report["page"], report["grid"]["box"], code,
                                              sorted((f"{n}-{d}", c) for (n, d), c in lts.items())]).encode()).hexdigest()[:20]
        dest = cache / f"letters-{keyed(code_key(ts, 'read_grid_letters'))}.json"
        old = cache / f"letters-{keyed(file_key(ts))}.json"
        if not dest.exists() and old.exists():
            old.replace(dest)
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
        grids_of=page_grids, read_letters=None, reports_to=REPORTS, numbers=None):
    """Join every reading in `store` (or just those of `numbers`) with its
    grid and report; file those that pass, and keep each report's copy in
    `reports_to`. Returns {number: verdict}, also merged into store/LEDGER."""
    read_letters = read_letters or letters_reader(Path(inbox))
    ledger = gl.load_ledger(store)
    files = [(sha, e) for sha, e in ledger.items() if (Path(inbox) / e["file"]).exists()]
    readings = {}
    for p in sorted(store.glob("listener-*.json")):
        r = json.loads(p.read_text())
        if numbers is None or r["number"] in numbers:
            readings[r["number"]] = r
    if numbers is not None:
        files = [(sha, e) for sha, e in files if any(
            isinstance(e.get("number"), int) and 0 <= e["number"] - n <= REPORT_WITHIN for n in numbers)]
    def page(f):
        sha, e = f
        try:
            return grids_of(Path(inbox) / e["file"], sha)
        except subprocess.TimeoutExpired as err:
            # A loaded host's OCR: the page is read again next run.
            print(f"{e['file']}: OCR timed out after {err.timeout:.0f} s; its grids are read next run", file=out)
            return None
    from concurrent.futures import ThreadPoolExecutor

    import ocr_remote
    ordered = sorted(files, key=lambda f: (f[1].get("number") not in readings, f[1]["file"]))
    # With the desktop named, SEARCH_SLOTS pages' grids are found there at once.
    with ThreadPoolExecutor(ocr_remote.SEARCH_SLOTS if ocr_remote.hosts() else 1) as pool:
        grids = {e["file"]: gs for (_, e), gs in zip(ordered, pool.map(page, ordered)) if gs is not None}
    reports = [{"grid": g["grid"], "page": f} for f, gs in grids.items() for g in gs if g["fit"] is None]
    verdicts = {}
    for n, reading in sorted(readings.items()):
        mine = [g for sha, e in files if e.get("number") == n for g in grids.get(e["file"], ()) if g["fit"]]
        puzzle, verdict, printed = join(reading, mine, reports, read_letters)
        if printed and write:
            Path(reports_to).mkdir(parents=True, exist_ok=True)
            (Path(reports_to) / f"{printed['id']}.json").write_text(json.dumps(printed, indent=1) + "\n")
        if puzzle is not None and "lacks" not in verdict:
            # build() files a light the page prints with no clue as just
            # {"missing": true}; a clue unread keeps its empty text.
            unclued = {f"{e['number']}-{e['direction']}" for e in puzzle["entries"] if e["clue"] == {"missing": True}}
            whole = fa.complete(puzzle, unclued)
            if not whole:
                verdict["lacks"] = "clues: " + (", ".join(sorted(
                    (f"{e['number']}-{e['direction']}" for e in puzzle["entries"]
                     if not e["clue"].get("text") and f"{e['number']}-{e['direction']}" not in unclued
                     or ocr_clues.suspect(e["clue"].get("text", ""), printed=e["clue"].get("asPrinted") or ())), key=order))
                    or "a clue is unfit to file")
            # Only a puzzle whose every clue reads true goes to the corpus;
            # --out takes every puzzle, one short of that too.
            if puzzles or whole:
                path = Path(puzzles) / f"{puzzle['id']}.json" if puzzles else puzzle_path(SERIES, n)
                held = path.exists() and not fa.improves(puzzle, path, tool=TOOL)
                if held:
                    # A held file this reading does not replace takes its
                    # corrected clue words (fa.corrected_clues).
                    old = json.loads(path.read_text())
                    same = ((old.get("source") or {}).get("acquiredBy") == TOOL
                            and fa.trove_solution_ocr.puzzle_grid(old) == fa.trove_solution_ocr.puzzle_grid(puzzle))
                    fixed = same and fa.corrected_clues(puzzle, old)
                    if not fixed:
                        verdict["skip"] = "already held"
                    else:
                        verdict["corrected"] = fixed
                        if write:
                            scan_queue.file_puzzle(write_puzzle_file, TOOL, path, old, verdict)
                elif write:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    scan_queue.file_puzzle(write_puzzle_file, TOOL, path, puzzle, verdict)
        verdicts[n] = verdict
        print(f"No {n}: " + "; ".join(v for v in (
            verdict.get("lacks"), verdict.get("skip"), verdict.get("refusedWrite"), verdict.get("writeFailed"),
            "written" + (f" (corrected {', '.join(sorted(verdict['corrected'], key=order))})"
                         if verdict.get("corrected") else "") if verdict.get("wrote") else None,
            f"report: {verdict['noReport']}" if "noReport" in verdict else None) if v)
              + (f", {verdict['reportAnswers']}/{len(puzzle['entries'])} answers read off the report"
                 if "reportAnswers" in verdict else ""), file=out)
    if write:
        kept = {}
        if numbers is not None and (store / LEDGER).exists():
            kept = {int(k): v for k, v in json.loads((store / LEDGER).read_text()).items()}
        merged = {**kept, **verdicts}
        (store / LEDGER).write_text(json.dumps({n: merged[n] for n in sorted(merged)}, indent=1) + "\n")
    return verdicts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="say what each puzzle lacks, write nothing")
    ap.add_argument("--out", type=Path, help="file into this folder instead of the corpus")
    ap.add_argument("--store", type=Path, default=gl.STORE)
    ap.add_argument("--inbox", type=Path, default=gl.MIRROR)
    ap.add_argument("--number", type=int, action="append",
                    help="just this No (repeatable): its pages and those its report may be on")
    a = ap.parse_args(argv)
    run(a.store, a.inbox, a.out, write=not a.dry_run, numbers=set(a.number) if a.number else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
