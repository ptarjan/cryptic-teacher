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
    and 47), its lights are the clue list's (as_read), or, its runs of two
    shut but up to MOST_KEPT, every number read on its start (No 447's
    themed 7 across and 37 down: closed_as_read). Before that the
    list is mended() where the page itself errs: a line read twice, a
    clue number misprinted, a light printed with no clue (one other clues
    cite, or the page's theme line names: No 447's CANVAS);
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

Even so read, a report misreads a letter as another that still makes a
word (PERTS for AERTS on No 1, 1 of 12), so only the answers
published_answers() takes file, as published: those whose every letter a
second reader bears out, the Times' cell classifier
(trove_solution_ocr.classified on report_glyph()) or the crossing light
read whole the other way (No 1: 7 of 38, none wrong), or the VLM, asked
the light's squares, reads the word a recogniser read it whole as
(vlm_answers; No 1: 9 of 38, none wrong). The rest stay blank for the
nightly solve; a held file of this tool's takes them too (with_report),
joined on its own grid when its reading no longer builds one
(held_report). A report's filled grid reads its bars poorly, so one on a
page a few issues on is taken at REPORT_NEAR where its letters read as
words (report_join). Every answer read goes to REPORTS
(cross_validate.ListenerReport's cache), filed or not, where
tools/cross_validate.py's `listenerreport` adapter votes on answers. A
puzzle whose report is not saved files all the same, unsolved.

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
gale_listener.read_unit runs this after reading each new page, so a
grid that turns exact files on the next read.
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
import cross_validate as cv
import file_archive_org_puzzles as fa
import gale_inbox as gi
import gale_listener as gl
import media_manifest
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
    one a guess. A linked clue's enumeration counts every light of its
    "group" (No 601's "3-down"/"22-down" clue prints (9): 3 cells and 6)."""
    have = {f"{n}-{d}": len(cells) for (n, d), cells in rg.light_cells(rows).items()}
    spare = sorted({lid for lid, c in clues.items() if (c.get("text") or "").strip()} - set(have), key=order)
    unclued = sorted(set(have) - set(clues), key=order)

    def cells(lid, c):
        return sum(have.get(g, 0) for g in dict.fromkeys([lid, *(c.get("group") or ())]))
    # Nor does a count it laid no words with (No 580's 20 Down, its words
    # lost and 21 Down's "(3)" left on it).
    long = sorted((lid for lid, c in clues.items() if lid in have and c.get("enumeration")
                   and (c.get("text") or "").strip()
                   and gl.al.ftp.count(c["enumeration"]) != cells(lid, c)), key=order)
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


def mended(rows, clues, theme=None):
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
        clue is "missing" with no text;
      - so is a light no clue names that the page's theme line (`theme`,
        the reading's verdict "theme": themed) names, No 447's CANVAS
        lights, which the theme line clues and no list does."""
    have = {f"{n}-{d}": len(cells) for (n, d), cells in rg.light_cells(rows).items()}
    clues, notes = linked_across(have, dict(clues))
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
    # A linked clue's tail ("See 30", No 261's 19 across of "(30) & (19
    # rev.)") cites its own head, not a light of that number the other way.
    tails = {t for c in clues.values() for t in (c.get("group") or ())[1:]}
    cited = " ".join(" ".join((c.get("text") or "").split()).lower() for lid, c in clues.items()
                     if lid in have and lid not in tails)
    for lid in sorted(set(have) - set(clues), key=order):
        n, d = number_of(lid)
        other = "down" if d == "across" else "across"
        if re.search(rf"(?<![\d,.]){n}(?!\d|\s*{other})", cited):
            clues[lid] = {"text": "", "noCluePrinted": True}
            notes[lid] = "printed with no clue: other clues cite it"
        elif themed(lid, theme):
            clues[lid] = {"text": "", "noCluePrinted": True}
            notes[lid] = f"printed with no clue: the {theme['title']} line names it"
    return clues, notes


#: A theme light's letter (gale_listener.theme_line): its direction.
THEME_WAY = {"A": "across", "B": "across", "D": "down", "U": "down"}


def themed(lid, theme):
    """Whether the page's theme line (the reading's verdict "theme", No
    447's "CANVAS / The 26s that 28U 7D 7A 5, ...") names the light `lid`:
    its number, lettered its way or not lettered."""
    n, d = number_of(lid)
    return any(re.fullmatch(rf"{n}([ABDU]?)", t) and THEME_WAY.get(t[-1], d) == d
               for t in (theme or {}).get("lights") or ())


def linked_across(have, clues):
    """(clues, notes): a clue of two lights whose second (its "group" tail)
    the list sets in its own direction where the grid has no such light, or
    one with a clue of its own, re-pointed at the other direction's light of
    that number when that one has no clue but "See" the first. The 1934-40
    paragraph lists link across them: "(33, 29) To find a low mean man" is
    among the across clues, 29 a down light only (No 254, 1935). `have`
    {light id: cells}; notes {light id: what was done}.
    The other light may be one more clue's tail already, its answer the
    end of both: No 471 (1939) prints "(29-8)" among the across clues and
    "(3-8)" among the down, UNI and ORA each run on into 8 down's TED."""
    clues, notes = dict(clues), {}
    tails = {t: h for h, c in clues.items() for t in (c.get("group") or ())[1:]}

    def cites(lid, head):
        t = (clues.get(lid) or {}).get("text") or ""
        # "See 37A." (No 273) cites 37 across as "See 37" does.
        return not t.strip() or bool(re.match(rf"see\W*{number_of(head)[0]}(?!\d)", t.strip(), re.IGNORECASE))

    def shared(lid, head):
        # A tail of a clue the other way, "See" that clue's head.
        other = tails.get(lid)
        return bool(other and other != head and number_of(other)[1] == number_of(lid)[1] and cites(lid, other))

    for head, c in list(clues.items()):
        group = list(c.get("group") or ())
        for k, tail in enumerate(group[1:], 1):
            if tail in have and cites(tail, head):
                continue
            n, d = number_of(tail)
            flip = f"{n}-{'down' if d == 'across' else 'across'}"
            if flip not in have or not (cites(flip, head) or shared(flip, head)):
                continue
            group[k] = flip
            if cites(tail, head) and tail not in have:
                clues.pop(tail, None)
            if not (clues.get(flip) or {}).get("text"):
                clues[flip] = {"text": f"See {number_of(head)[0]} {number_of(head)[1].capitalize()}"}
            notes[flip] = f"linked to {head} from the other list"
        if group != list(c.get("group") or ()):
            clues[head] = {**c, "group": group}
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


def as_read(g, clues, theme=None):
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
    laid, notes = mended(fit["rows"], got[0], theme)
    if lights_fit(fit["rows"], laid) is not None:
        return None
    return {**fit, "laid": (fit["rows"], laid, {**got[1], **notes})}


def closed_as_read(g, clues, theme=None):
    """as_read for a page leaving its 2-cell runs unnumbered but a few
    (reclosed: up to MOST_KEPT kept): `g`'s rows each side as its width
    says, every printed number read on the start it numbers, the clue list
    (mended) their lights; else None, and None when more than one set kept
    fits. No 447 (1938) numbers its themed runs of two, 7 across and 37
    down, and no other; its fit, five numbers unread, chased the rest with
    bars the page has not (36 across cut up for a 37 across). A light the
    theme line names with its way ("7A", "37U") is one: kept, of 447's
    runs of two its unlettered "5" or "9" could name too."""
    if not g["fit"].get("printed") or g["fit"].get("numbering") or g["fit"].get("stray"):
        return None
    printed = {(r, c): n for r, c, n in g["fit"]["printed"]}
    named = {f"{t[:-1]}-{THEME_WAY[t[-1]]}" for t in (theme or {}).get("lights") or () if t[-1] in THEME_WAY}
    hits = []
    for alt in reclosed(g["grid"]["rows"]):
        st = lg.starts(alt)
        if any(st.get(c) != n for c, n in printed.items()) or named - light_ids(alt):
            continue
        laid, notes = mended(alt, clues, theme)
        if lights_fit(alt, laid) is None:
            hits.append((alt, laid, notes))
    if len(hits) != 1:
        return None
    alt, laid, notes = hits[0]
    return {**g["fit"], "rows": alt, "asRead": True, "laid": (alt, laid, notes)}


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
    A fit leaving its 2-cell runs unnumbered is flipped with them open and
    closed again (reclosed), none flipped first: No 261 numbers one, 30
    across. A flip must keep the page's own word (unmoved): its read
    numbers on their starts, no cell left in no light. [] when none does."""
    thin = max(grid["thin"], 1.0)
    edge = math.log(lg.BAR_RATIO)
    unsure = sorted((side for side, width in grid["sides"].items() if lg.UNSURE[0] <= width / thin <= lg.UNSURE[1]),
                    key=lambda side: abs(math.log(grid["sides"][side] / thin) - edge))
    rows = fit["rows"]
    got = lay(rows)
    lines = misfit_lines(rows, got[0]) if got and fit.get("numbering") == "printed" else set()
    # A fit leaving 2-cell runs unnumbered has them barred shut (lg.closed):
    # its sides are flipped on the grid with them open, which is closed again
    # (reclosed) as the page may number them.
    shut = fit.get("shortest") == 3
    base = opened(rows) if shut else rows
    bars = bars_of(base)
    near = [side for side in unsure if not bars.get(side)
            and (side[2], side[0] if side[2] == "r" else side[1]) in lines][:NEAR]
    for k in range(0 if shut else 1, MOST_FLIPS + 1):
        hits, seen = [], {tuple(rows)}
        for sides in itertools.combinations(unsure if k <= 1 else near, k):
            flipped = lg.with_bars(base, {**bars, **{side: not bars.get(side) for side in sides}})
            for alt in (reclosed(flipped) if shut else [flipped]):
                if tuple(alt) in seen:
                    continue
                seen.add(tuple(alt))
                if not unmoved(fit, rows, alt):
                    continue
                got = lay(alt)
                if got and lights_fit(alt, got[0]) is None:
                    hits.append((sides, alt, *got))
        if hits:
            return hits
    return []


def unlit(rows):
    """The open cells of `rows` in no light."""
    lit = {c for cells in rg.light_cells(rows).values() for c in cells}
    return {(r, c) for r, row in enumerate(rows) for c, ch in enumerate(row) if ch != "#"} - lit


def unmoved(fit, rows, alt):
    """Whether `alt`, the fitted `rows` with sides flipped, keeps the page's
    own word on them: no number both readers read (fit "printed") that
    starts `rows`' light of that number starts none in `alt`, and no cell
    left in no light that is in one in `rows`. No 261's four single flips
    each give the clue list's lights; one moves 29 off its start, one
    leaves a cell unlit, one does both. A page numbering otherwise (fit
    "numbering", "stray") is held to the second alone."""
    if unlit(alt) - unlit(rows):
        return False
    if fit.get("numbering") or fit.get("stray"):
        return True
    was, now = lg.starts(rows), lg.starts(alt)
    return all(now.get((y, x)) == n for y, x, n in fit.get("printed") or () if was.get((y, x)) == n)


#: reclosed() keeps at most this many of a grid's 2-cell runs numbered.
MOST_KEPT = 2


def opened(rows):
    """`rows` without the bars lg.closed() shuts a 2-cell run with: a bar
    between two cells that would be a run of two alone, walled (edge,
    block or a bar not itself such) on its far sides. No 608's row 3 tail
    of two, shut beside a misread bar, is open again."""
    h, w = len(rows), len(rows[0])
    bars = bars_of(rows)

    def wall(y, x, s):
        # Whether the side `s` ("r" right, "b" below) of cell (y, x) ends a run.
        if y < 0 or x < 0 or (s == "r" and x >= w - 1) or (s == "b" and y >= h - 1):
            return True
        if rows[y][x] == "#":
            return True
        nxt = rows[y][x + 1] if s == "r" else rows[y + 1][x]
        return nxt == "#" or bool(bars.get((y, x, s)))

    def shuts(y, x, s):
        if not bars.get((y, x, s)) or rows[y][x] == "#":
            return False
        if s == "r":
            return x + 1 < w and rows[y][x + 1] != "#" and wall(y, x - 1, "r") and wall(y, x + 1, "r")
        return y + 1 < h and rows[y + 1][x] != "#" and wall(y - 1, x, "b") and wall(y + 1, x, "b")
    cand = {side for side in bars if shuts(*side)}

    def outer(y, x, s):
        # The far walls of the pair a candidate side splits.
        return {(y, x - 1, s), (y, x + 1, s)} if s == "r" else {(y - 1, x, s), (y + 1, x, s)}
    # Three cells barred apart are no run of two: their bars stay.
    drop = {side for side in cand if not outer(*side) & cand}
    return lg.with_bars(rows, {side: True for side in bars if side not in drop})


def reclosed(rows):
    """`rows` (2-cell runs open) closed (lg.closed) as a page leaving its
    2-cell runs unnumbered may number some: none kept, then each set of up
    to MOST_KEPT kept (No 261 numbers its run of two at 30 across, "(30) &
    (19 rev.) A skeleton", and leaves three others bare)."""
    twos = sorted({cells[0] for cells in rg.light_cells(rows).values() if len(cells) == 2})
    return [lg.closed(rows, 3, set(keep)) for k in range(min(MOST_KEPT, len(twos)) + 1)
            for keep in itertools.combinations(twos, k)]


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


def published_answers(lts, read, probs):
    """{light id: word} of the report's answers that file as published: those
    answers() takes (every cell settled, the whole light read as the word,
    known()) whose every letter a second reading bears out: the cell
    classifier (trove_solution_ocr.classified, the Times solution grids'
    second reader, on report_glyph(); `probs` {cell: 26 probabilities}) reads
    it likeliest there, or the crossing light, read whole the other way,
    answers() takes with it too. On No 1's report answers() took PERTS for
    AERTS, its P a letter the classifier gives under 1% and whose crossing
    was not read: blank; DALE's L (1%, crossed by TSARSULTAN read whole)
    files. Any light in doubt stays blank: partial answers file, and the
    nightly solve fills the rest. With no `probs` (a cell cut off the page)
    nothing files."""
    if not probs:
        return {}
    settled = crossed(lts, read["letters"], read["full"])
    taken = {key: w for key, w in ((k, answers({k: c}, settled, read["full"])[f"{k[0]}-{k[1]}"])
                                   for k, c in lts.items()) if w}
    by = {}
    for key, w in taken.items():
        for rc, ch in zip(lts[key], w):
            by.setdefault(rc, {})[key] = ch
    out = {}
    for (n, d), w in taken.items():
        if all(rc in probs and (ts.AZ[int(probs[rc].argmax())] == ch
                                or any(k != (n, d) for k in by[rc]))
               and set(by[rc].values()) == {ch}
               for rc, ch in zip(lts[(n, d)], w)):
            out[f"{n}-{d}"] = w
    return out


#: The VLM is asked at most this many lights a report (vlm_answers), once
#: each (vlm_reader caches the reply), the VLM's slot being the queue's:
#: No 95's report read 25 lights whole, 4 of which published_answers took.
REPORT_ASKS = 12
#: The prompt of that ask: the light's squares in a row, the letters already
#: filed in them given.
REPORT_PROMPT = Path(__file__).resolve().parent / "vlm_report_prompt.md"


def vlm_answers(lts, read, filed, strip_of, ask):
    """{light id: word} published_answers() left blank that the VLM bears
    out: it is asked the light's squares (strip_of(cells), a PNG's base64,
    or None) with only the letters `filed` holds in them, and its reply
    stands where it is the light's length, a word a recogniser read the
    whole light as (read["full"]), agrees with every letter `filed` and the
    words taken before it hold, and is known(): two readers, the page's and
    the VLM's, on the whole word. Those answers() took (every cell settled)
    are asked first, at most REPORT_ASKS; an ask not answered (spooled, the
    server down: ask raises RuntimeError) leaves its light blank, asked
    again next run."""
    held = {rc: ch for (n, d), cells in lts.items() for rc, ch in zip(cells, filed.get(f"{n}-{d}") or ())}
    settled = crossed(lts, read["letters"], read["full"])
    took = answers(lts, settled, read["full"])
    wanted = [key for key in lts if f"{key[0]}-{key[1]}" not in filed and any(
        len(w) == len(lts[key]) for w in read["full"].get(key, ()))]
    wanted.sort(key=lambda k: (took.get(f"{k[0]}-{k[1]}") is None, order(f"{k[0]}-{k[1]}")))
    prompt = REPORT_PROMPT.read_text()
    out = {}
    for key in wanted[:REPORT_ASKS]:
        cells = lts[key]
        pattern = "".join(held.get(rc, "?") for rc in cells)
        if "?" not in pattern:
            continue
        png = strip_of(cells)
        if not png:
            continue
        known = f" The letters already known, ? for the others: {pattern}." if set(pattern) != {"?"} else ""
        try:
            reply = ask(png, prompt.format(count=len(cells), known=known))
        except RuntimeError:
            continue
        word = re.sub(r"[^A-Z]", "", ((reply or "").strip().splitlines() or [""])[0].upper())
        if (len(word) == len(cells) and word in read["full"].get(key, ())
                and all(p in ("?", ch) for p, ch in zip(pattern, word)) and ts.known(word)):
            out[f"{key[0]}-{key[1]}"] = word
            held.update(zip(cells, word))
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


def held_rows(puzzle):
    """build()'s rows back off a filed puzzle: its "bars" (or open rows), a
    cell in no entry a block."""
    R, C = puzzle["dimensions"]["rows"], puzzle["dimensions"]["cols"]
    bars = puzzle.get("bars") or ["." * C] * R
    used = set()
    for e in puzzle["entries"]:
        x, y = e["position"]["x"], e["position"]["y"]
        used.update((y, x + i) if e["direction"] == "across" else (y + i, x) for i in range(e["length"]))
    return ["".join(bars[r][c] if (r, c) in used else "#" for c in range(C)) for r in range(R)]


def with_report(old, puzzle):
    """The held file `old` (this tool's, on `puzzle`'s grid) with the answers
    `puzzle` files as published (published_answers) laid in, or None when it
    gains none: (the file, [light ids laid]). A light another source already
    answers is never changed (the Listener Team's key, a report laid
    before); a model's answer gives way, the report's going into
    solutions.printed (provenance.printed_answers) and a guess whose letters
    cross it otherwise going blank, its hint with it, for the solve to fill
    again."""
    words = {f"{e['number']}-{e['direction']}": e["solution"] for e in puzzle["entries"] if e.get("solution")}
    out = copy.deepcopy(old)
    detail = out.get("solutions") or {}
    model = "model" in detail
    printed = dict(detail.get("printed") or {})
    letters, laid = {}, []
    for e in out["entries"]:
        lid = f"{e['number']}-{e['direction']}"
        w = words.get(lid)
        if not w or len(w) != e["length"] or lid in printed or e.get("solution") and not model:
            continue
        if e.get("solution") != w:
            e.pop("annotation", None)
            e["solution"] = w
        if model:
            printed[lid] = w
        laid.append(lid)
        letters.update(zip(cells_of(e), w))
    if not laid:
        return None
    for e in out["entries"]:
        if model and e.get("solution") and f"{e['number']}-{e['direction']}" not in printed and any(
                letters.get(rc, ch) != ch for rc, ch in zip(cells_of(e), e["solution"])):
            e["solution"] = None
            e.pop("annotation", None)
    if model:
        out["solutions"] = {**detail, "printed": printed}
    return out, laid


def held_report(n, puzzles, verdict, reports, readers, write):
    """A held file of this tool's for No `n` (in `puzzles`, else the
    corpus) joined with its report on its own grid (held_rows): its
    answers laid in by with_report() and filed. For a puzzle whose
    reading no longer builds a grid (Nos 1, 8, 10, 29, 121 on 10-24) or
    did not reach its report (No 95's at 0.72). `readers`: report_join's
    (read_letters, read_probs, read_strips, ask); `verdict` takes
    "heldReport" (report_join's items) and "answered"."""
    path = Path(puzzles) / f"{series_meta.puzzle_id(SERIES, n)}.json" if puzzles else puzzle_path(SERIES, n)
    if not path.exists():
        return
    old = json.loads(path.read_text())
    if (old.get("source") or {}).get("acquiredBy") != TOOL:
        return
    rows = held_rows(old)
    found, _, filed = report_join(rows, reports, readers[0], readers[1], n, *readers[2:])
    if "report" not in found:
        return
    verdict["heldReport"] = {k: v for k, v in found.items() if k != "cells"}
    if not filed:
        return
    mine = copy.deepcopy(old)
    for e in mine["entries"]:
        e["solution"] = filed.get(f"{e['number']}-{e['direction']}")
    answered = with_report(old, mine)
    if not answered:
        return
    verdict["answered"] = answered[1]
    if write:
        scan_queue.file_puzzle(write_puzzle_file, TOOL, path, answered[0], verdict)


def cells_of(e):
    """The (y, x) cells of entry `e`, in order."""
    x, y = e["position"]["x"], e["position"]["y"]
    return [(y, x + i) if e["direction"] == "across" else (y + i, x) for i in range(e["length"])]


def report_copy(puzzle, words):
    """`puzzle` as its report prints it: the answers `words` read off the
    report's grid in. A vote for cross_validate.py, never a file."""
    out = copy.deepcopy(puzzle)
    for e in out["entries"]:
        e["solution"] = words.get(f"{e['number']}-{e['direction']}")
    return out


def join(reading, grids, reports, read_letters, read_probs=None, read_strips=None, ask=None):
    """join_one of the reading's clues, else of the first of its
    "alternatives" (a Times page's other cuts, gale_listener.times_read)
    whose lights are the grid's, its verdict's "alternative" naming that
    cut; else of the reading with the lights it leaves unclued taken from
    them ("alternative": {light id: cut}). No 3121's down list set above its
    headings reads its top only from the title down, No 3120's lists read
    only from the headings."""
    got = join_one(reading, grids, reports, read_letters, read_probs, read_strips, ask)
    alts = reading.get("alternatives") or () if got[0] is None else ()
    for alt in alts:
        tried = join_one({**reading, "clues": alt["clues"]}, grids, reports, read_letters, read_probs, read_strips,
                         ask)
        if tried[0] is not None:
            tried[1]["alternative"] = alt["cut"]
            return tried
    # Else the cuts' readings together on each exact grid: a light the reading leaves unclued takes the
    # first alternative's words for it (No 3121's 3-8 Down read only from the title down, its 29-34 Down
    # only from the headings). A light no grid has takes none.
    for g in (g for g in grids if alts and g["fit"]["exact"]):
        clues, took = dict(reading["clues"]), {}
        for lid in sorted(light_ids(g["fit"]["rows"]) - {k for k, c in clues.items() if (c.get("text") or "").strip()},
                          key=order):
            if alt := next((a for a in alts if ((a["clues"].get(lid) or {}).get("text") or "").strip()), None):
                clues[lid], took[lid] = alt["clues"][lid], alt["cut"]
        if took and (tried := join_one({**reading, "clues": clues}, [g], reports, read_letters, read_probs,
                                       read_strips, ask))[0] is not None:
            tried[1]["alternative"] = took
            return tried
    return got


def join_one(reading, grids, reports, read_letters, read_probs=None, read_strips=None, ask=None):
    """(puzzle or None, verdict, the report's copy or None) for one reading: `grids` the unfilled
    grids read on its pages ({"grid", "fit"}), `reports` every filled grid
    on any saved page ({"grid", "page"}), read_letters(report, lts) its
    letters ({"letters", "full"}, read_grid_letters' shape), and
    read_probs(report, lts) its cells' classifier probabilities (probs_reader):
    with them the puzzle has the report's published_answers() in, and with
    read_strips and ask the VLM's (report_join)."""
    verdict = {"number": reading["number"]}
    clues = reading["clues"]
    theme = reading.get("verdict", {}).get("theme")
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
                laid, notes = mended(rows if fit.get("numbering") == "printed" else fit["rows"], got[0], theme)
                return laid, {**shifted, **got[1], **notes}

            rows, sides, laid, notes, why, mends = fit_to_clues(g["grid"], g["fit"], lay)
            if not rows and not mends and (got := lay(g["fit"]["rows"])):
                skip, note = skipped(g["fit"]["rows"], got[0])
                if skip and lights_fit(g["fit"]["rows"], skip) is None:
                    rows, sides, laid, notes = g["fit"]["rows"], [], skip, {**got[1], **note}
        if not rows and (got := as_read(g, clues, theme) or closed_as_read(g, clues, theme)):
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
    found, words, filed = report_join(rows, reports, read_letters, read_probs, reading["number"], read_strips, ask)
    verdict.update(found)
    if words is None:
        return puzzle, verdict, None
    copied = report_copy(puzzle, words)
    if filed is not None:
        for e in puzzle["entries"]:
            e["solution"] = filed.get(f"{e['number']}-{e['direction']}")
    return puzzle, verdict, copied


#: A filled grid on a page of No n + 1 to n + REPORT_WITHIN (the issues
#: No n's report may be in) is its report at REPORT_NEAR agreement, not
#: REPORT_AGREE, where REPORT_WORDS of the lights read off it as words
#: (answers()). A filled grid's bars read poorly, a letter's stroke taken
#: for one and a faint bar missed: No 95's report agrees 0.72, No 121's
#: 0.75, every light they read the word its clue asks (25 of 45, 14 of 32).
#: The grid on No 18's page agrees 0.76 with No 15 and is not its report:
#: 3 of 44 lights read, BODES for "Spoken in Switzerland".
REPORT_NEAR, REPORT_WORDS = 0.7, 0.25


def report_join(rows, reports, read_letters, read_probs=None, number=None, read_strips=None, ask=None):
    """(verdict items, {light id: word or None} read off the report or None,
    {light id: word} of those filing as published or None) for the grid
    `rows` of No `number` against `reports` (join()'s, each with its page's
    "number"): the filled grid agreeing best with its blocks and bars, at
    least REPORT_AGREE, or REPORT_NEAR on a page REPORT_WITHIN issues on
    whose letters read REPORT_WORDS of the lights as words; read by
    read_letters and, with read_probs, published_answers(), and with
    read_strips(report) (a light's cells to its strip) and `ask` the
    VLM's word for the rest (vlm_answers). join() runs it on the grid it
    builds; run() on a held file's own grid (held_rows) too, so a report
    files its answers into a held puzzle whose reading no longer builds."""
    verdict = {}
    lts = rg.light_cells(rows)
    scored = sorted(((agreement(rows, r["grid"]["rows"]), i) for i, r in enumerate(reports)), reverse=True)
    near = [(a, i) for a, i in scored if REPORT_NEAR <= a < REPORT_AGREE and isinstance(number, int)
            and isinstance(reports[i].get("number"), int) and 1 <= reports[i]["number"] - number <= REPORT_WITHIN]
    found = None
    if scored and scored[0][0] >= REPORT_AGREE:
        found = scored[0], read_letters(reports[scored[0][1]], lts)
    for a, i in near if found is None else ():
        read = read_letters(reports[i], lts)
        took = answers(lts, crossed(lts, read["letters"], read["full"]), read["full"])
        if sum(1 for w in took.values() if w) >= REPORT_WORDS * len(lts):
            found = (a, i), read
            break
    if found is None:
        verdict["noReport"] = "no saved filled grid has its blocks and bars" + (
            f" (best {scored[0][0]:.2f})" if scored else "") + (
            f"; {len(near)} near it {REPORT_WITHIN} issues on read too few words" if near else "")
        return verdict, None, None
    (agrees, i), read = found
    report = reports[i]
    verdict["report"] = {"page": report["page"], "agrees": round(agrees, 3)}
    sure = read["letters"]
    settled = crossed(lts, sure, read["full"])
    words = answers(lts, settled, read["full"])
    cells = {c for cs in lts.values() for c in cs}
    verdict["cells"] = {"sure": len(sure), "crossed": sorted([list(c) for c in set(settled) - set(sure)]),
                        "unread": sorted([list(c) for c in cells - set(settled)]), "of": len(cells)}
    verdict["reportAnswers"] = sum(1 for w in words.values() if w)
    if read_probs is None:
        return verdict, words, None
    filed = published_answers(lts, read, read_probs(report, lts))
    if read_strips is not None and ask is not None and filed:
        seen = vlm_answers(lts, read, filed, read_strips(report), ask)
        filed.update(seen)
        verdict["vlmAnswers"] = len(seen)
    verdict["published"] = len(filed)
    return verdict, words, filed


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
    got = gl.read_json(dest)
    if got is not None:
        if got.get("code") == file_key(lg):
            got["code"] = key
            gl.write_whole(dest, json.dumps(got))
        if got.get("code") == key:
            return loaded_grids(got["grids"])
    got = ocr_remote.call("listener_grids", path.name, data=path.read_bytes())
    if got is None:
        with _HERE, ocr_remote.local_slot():
            grids = grids_here(path)
    else:
        grids = got[0]
    cache.mkdir(parents=True, exist_ok=True)
    gl.write_whole(dest, json.dumps({"code": key, "grids": grids}))
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
        for found in lg.find_grids(gray):
            if not found["rows"] or found["why"]:
                continue
            # A grid with cells drawn in is also read with them for blocks
            # (No 471's footballers), after the plain reading: join() takes
            # the first whose fit is exact and lights the clue list's.
            for g in [found] + ([{**found, **found["figured"]}] if found.get("figured") else []):
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


def letters_reader(inbox=gl.SAVED, cache=GRIDS):
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
        got = gl.read_json(dest)
        if got is None:
            img, _ = gi.images(gl.page_path(inbox, report["page"]))[report["grid"]["page"]]
            gray = np.asarray(img.convert("L"), dtype=np.uint8)
            got = ts.read_grid_letters(gray, *report["grid"]["lattice"], lts)
            cache.mkdir(parents=True, exist_ok=True)
            got = {"letters": [[r, c, ch] for (r, c), ch in got["letters"].items()],
                   "full": [[n, d, sorted(ws)] for (n, d), ws in got["full"].items()]}
            gl.write_whole(dest, json.dumps(got))
        return {"letters": {(r, c): ch for r, c, ch in got["letters"]},
                "full": {(n, d): set(ws) for n, d, ws in got["full"]}}
    return read


#: report_glyph's cut: a square LETTER_SPAN of the cell wide about the
#: letter's ink (that outside the number's corner, trove_solution_ocr's
#: NUMBER_HIGH by half the cell), ink where darker than LETTER_INK, thickened
#: LETTER_THICK pixels at the glyph's scale. The report's letters are a
#: typewriter's, a third of the cell high and a pixel thin at glyph() size,
#: which the classifier, trained on the Times' heavy type, reads as I (7 of
#: No 1's 100 cells right by glyph(); 73 so cut).
LETTER_SPAN, LETTER_INK, LETTER_THICK = 0.5, 140, 3


def report_glyph(gray, ys, xs, r, c):
    """Cell (r, c) of a report's filled grid as trove_solution_ocr.glyph()
    cuts a Times cell for the classifier, but by the LETTER_SPAN cut."""
    import numpy as np
    from PIL import Image
    side = ts.GLYPH + 2 * ts.GLYPH_SHIFT
    h, w = ys[r + 1] - ys[r], xs[c + 1] - xs[c]
    a = gray[int(ys[r] + ts.GLYPH_MARGIN * h):int(ys[r + 1] - ts.GLYPH_MARGIN * h),
             int(xs[c] + ts.GLYPH_MARGIN * w):int(xs[c + 1] - ts.GLYPH_MARGIN * w)]
    if a.size == 0:
        return np.zeros((side, side), np.float32)
    ink = a < LETTER_INK
    letter = ink.copy()
    letter[:int(ts.NUMBER_HIGH * ink.shape[0]), :ink.shape[1] // 2] = False
    ys_, xs_ = np.nonzero(letter)
    cy, cx = (np.median(ys_), np.median(xs_)) if len(ys_) else (ink.shape[0] / 2, ink.shape[1] / 2)
    half = LETTER_SPAN * max(ink.shape) / 2
    cut = ink[max(0, int(cy - half)):int(cy + half), max(0, int(cx - half)):int(cx + half)]
    if cut.size == 0:
        return np.zeros((side, side), np.float32)
    g = np.asarray(Image.fromarray(cut.astype(np.uint8) * 255).resize((side, side), Image.BILINEAR),
                   np.float32) / 255
    k = LETTER_THICK
    p = np.pad(g, k)
    return np.max([p[k + dy:k + dy + side, k + dx:k + dx + side]
                   for dy in range(-(k // 2), k - k // 2) for dx in range(-(k // 2), k - k // 2)], 0)


def probs_reader(inbox=gl.SAVED, cache=GRIDS):
    """read_probs for join(): {cell: 26 letter probabilities} of the
    classifier (trove_solution_ocr.classified) on each cell of the report's
    lights, cut by report_glyph() on the report's own rules, cached by the
    report, its lights, the cut and the model (CELL_MODEL_SHA); {} when a
    cell is off the lattice."""
    import numpy as np

    def read(report, lts):
        ys, xs = report["grid"]["lattice"]
        cells = sorted({rc for cs in lts.values() for rc in cs})
        if any(r + 1 >= len(ys) or c + 1 >= len(xs) for r, c in cells):
            return {}
        key = hashlib.sha256(json.dumps([report["page"], report["grid"]["box"], ts.CELL_MODEL_SHA,
                                         code_key(sys.modules[__name__], "report_glyph"),
                                         [list(rc) for rc in cells]]).encode()).hexdigest()[:20]
        dest = cache / f"probs-{key}.json"
        got = gl.read_json(dest)
        if got is None:
            img, _ = gi.images(gl.page_path(inbox, report["page"]))[report["grid"]["page"]]
            gray = np.asarray(img.convert("L"), dtype=np.uint8)
            probs = ts.classified({rc: report_glyph(gray, ys, xs, *rc) for rc in cells})
            got = [[r, c, [round(float(p), 6) for p in probs[(r, c)]]] for r, c in cells]
            cache.mkdir(parents=True, exist_ok=True)
            gl.write_whole(dest, json.dumps(got))
        return {(r, c): np.asarray(p) for r, c, p in got}
    return read


def strips_reader(inbox=gl.SAVED):
    """read_strips for report_join(): for a report, strip_of(cells), the
    light's squares in a row off its page (trove_solution_ocr.light_strip),
    the page read once a report and only when a light is asked."""
    import numpy as np

    def read(report):
        page = []

        def strip_of(cells):
            ys, xs = report["grid"]["lattice"]
            if any(r + 1 >= len(ys) or c + 1 >= len(xs) for r, c in cells):
                return None
            if not page:
                img, _ = gi.images(gl.page_path(inbox, report["page"]))[report["grid"]["page"]]
                page.append(np.asarray(img.convert("L"), dtype=np.uint8))
            return ts.light_strip(page[0], ys, xs, cells)
        return strip_of
    return read


def report_ask(png, prompt):
    """vlm_answers' ask: the VLM's reply about the strip `png` (base64),
    cached by vlm_reader; RuntimeError when spooled or the server is down."""
    import base64

    import vlm_reader as vlm
    with vlm.because("listener-report"):
        return vlm.ask_png(base64.b64decode(png), prompt, max_tokens=40)


def run(store=gl.STORE, inbox=gl.SAVED, puzzles=None, write=True, out=sys.stdout,
        grids_of=page_grids, read_letters=None, reports_to=REPORTS, numbers=None, read_probs=None,
        read_strips=None, ask=None):
    """Join every reading in `store` (or just those of `numbers`) with its
    grid and report; file those that pass, and keep each report's copy in
    `reports_to`. Returns {number: verdict}, also merged into store/LEDGER.
    The VLM is asked about a report's lights (read_strips, ask) only with
    the page's own readers: a caller's read_probs goes without, unless it
    gives them too."""
    if read_probs is None:
        read_strips, ask = read_strips or strips_reader(Path(inbox)), ask or report_ask
    read_letters = read_letters or letters_reader(Path(inbox))
    read_probs = read_probs or probs_reader(Path(inbox))
    ledger = gl.load_ledger(store)
    # The saved pages, listed once (the folder and its Fetched subfolder; on the desktop over the share).
    where = {p.name: p for p in gl.page_files(inbox)}
    files = [(sha, e) for sha, e in ledger.items() if e["file"] in where]
    readings = {}
    # With `numbers`, only their readings are opened: each read unit files its own puzzles while others write theirs.
    paths = (sorted(store.glob("listener-*.json")) if numbers is None
             else [store / f"listener-{n}.json" for n in sorted(numbers) if (store / f"listener-{n}.json").exists()])
    for p in paths:
        try:
            r = json.loads(p.read_text())
        except ValueError as e:  # one torn reading must not stop the filing of every other
            print(f"{p.name}: unreadable ({e}); not filed this run", file=out)
            continue
        if numbers is None or r["number"] in numbers:
            readings[r["number"]] = r
    if numbers is not None:
        files = [(sha, e) for sha, e in files if any(
            isinstance(e.get("number"), int) and 0 <= e["number"] - n <= REPORT_WITHIN for n in numbers)]
    def page(f):
        sha, e = f
        try:
            return grids_of(where[e["file"]], sha)
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
    number_of_page = {e["file"]: e.get("number") for _, e in files}
    reports = [{"grid": g["grid"], "page": f, "number": number_of_page.get(f)}
               for f, gs in grids.items() for g in gs if g["fit"] is None]
    verdicts = {}
    for n, reading in sorted(readings.items()):
        mine = [g for sha, e in files if e.get("number") == n for g in grids.get(e["file"], ()) if g["fit"]]
        puzzle, verdict, printed = join(reading, mine, reports, read_letters, read_probs, read_strips, ask)
        if printed and write:
            Path(reports_to).mkdir(parents=True, exist_ok=True)
            (Path(reports_to) / f"{printed['id']}.json").write_text(json.dumps(printed, indent=1) + "\n")
            # cross_validate.ListenerReport.ids reads this, not a listing of the media disk.
            media_manifest.record_file("listenerreport-source", Path(reports_to) / f"{printed['id']}.json")
        if puzzle is not None and "lacks" not in verdict:
            # build() files a light the page prints with no clue as just
            # {"missing": true}; a clue unread keeps its empty text.
            unclued = {f"{e['number']}-{e['direction']}" for e in puzzle["entries"] if e["clue"] == {"missing": True}}
            whole = fa.complete(puzzle, unclued)
            if not whole:
                # A clue fa.faults refuses is named too, with why: No 2's 5 down
                # "1 Denotes the origin of a person." (a line's stray figure) was
                # only "a clue is unfit to file".
                faulted = fa.faults(puzzle)
                verdict["lacks"] = "clues: " + (", ".join(sorted(
                    (f"{e['number']}-{e['direction']}" for e in puzzle["entries"]
                     if not e["clue"].get("text") and f"{e['number']}-{e['direction']}" not in unclued
                     or ocr_clues.suspect(e["clue"].get("text", ""), printed=e["clue"].get("asPrinted") or ())
                     and f"{e['number']}-{e['direction']}" not in faulted), key=order)
                    + [f"{lid} {why}" for lid, why in sorted(faulted.items(), key=lambda kv: order(kv[0]))])
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
                    # And the report's answers it lacks (with_report).
                    answered = same and with_report(old, puzzle)
                    if answered:
                        old = answered[0]
                        verdict["answered"] = answered[1]
                    if not fixed and not answered:
                        verdict["skip"] = "already held"
                    else:
                        if fixed:
                            verdict["corrected"] = fixed
                        if write:
                            scan_queue.file_puzzle(write_puzzle_file, TOOL, path, old, verdict)
                elif write:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    scan_queue.file_puzzle(write_puzzle_file, TOOL, path, puzzle, verdict)
        if "report" not in verdict:
            # No report joined on this reading's grid (or none built): a held
            # file of this tool's is joined on its own.
            held_report(n, puzzles, verdict, reports, (read_letters, read_probs, read_strips, ask), write)
        verdicts[n] = verdict
        print(f"No {n}: " + "; ".join(v for v in (
            verdict.get("lacks"), verdict.get("skip"), verdict.get("refusedWrite"), verdict.get("writeFailed"),
            "written" + (f" (corrected {', '.join(sorted(verdict['corrected'], key=order))})"
                         if verdict.get("corrected") else "") if verdict.get("wrote") else None,
            f"report: {verdict['noReport']}" if "noReport" in verdict else None) if v)
              + (f", {verdict['reportAnswers']}/{len(puzzle['entries'])} answers read off the report"
                 + f", {verdict.get('published', 0)} sure enough to file as published"
                 if "reportAnswers" in verdict else "")
              + (f", answered {', '.join(verdict['answered'])}" if verdict.get("answered") else ""), file=out)
    if write:
        # Read, merged and written whole under its lock: units filing at once
        # (tools/edition_queue.py runs several) keep each other's verdicts.
        with scan_queue.lock(store / LEDGER, wait_for_it=True):
            kept = {}
            if numbers is not None:
                kept = {int(k): v for k, v in (gl.read_json(store / LEDGER) or {}).items()}
            merged = {**kept, **verdicts}
            gl.write_whole(store / LEDGER, json.dumps({n: merged[n] for n in sorted(merged)}, indent=1) + "\n")
    return verdicts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="say what each puzzle lacks, write nothing")
    ap.add_argument("--out", type=Path, help="file into this folder instead of the corpus")
    ap.add_argument("--store", type=Path, default=gl.STORE)
    ap.add_argument("--inbox", type=Path, default=gl.SAVED)
    ap.add_argument("--number", type=int, action="append",
                    help="just this No (repeatable): its pages and those its report may be on")
    a = ap.parse_args(argv)
    run(a.store, a.inbox, a.out, write=not a.dry_run, numbers=set(a.number) if a.number else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
