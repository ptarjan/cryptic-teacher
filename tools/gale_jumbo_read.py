#!/usr/bin/env python3
"""The Times Jumbo cryptics (1997-2014) read from the Saturday Times pages
tools/gale_fetch.py downloads from Gale's Times Digital Archive, one
GALE_<docId>.pdf each in <Gale crosswords>/TimesJumbo/Fetched (no edition
layout, like the Listener's and the Times' Fetched folders).

A page's citation ('"Jumbo Crossword 392." Times, 9 Mar. 2002, p. 68')
gives its date and mostly its number ("Jumbo Crossword." alone from 2012: the
number is then read off the page's prize text, "sent to: Jumbo 1,033"; gale_jumbo's
date_of is a holiday out at times, so it is never taken). The clue lists are
cut and read as tools/gale_listener.py reads a Saturday Times page's Listener
block (its title words swapped for "Jumbo Crossword"), the grid is read off
the page's largest square patch of ink (trove_grid), and a light the clues
do not reach is filed blank, so only a puzzle with every clue filed (fa.complete).
The file is first unsolved; puzzles/timesjumbo's held numbers are never
written over. The solution is printed in a later issue (a "Solution to Jumbo
477" article to 2003, a grid on an "Answers" page after), fetched into
TimesJumbo/Solutions: once a page is there a filed puzzle is read again
(fa.JUMBO_SOLUTION), the page found by the number in its title or, untitled,
by its date, and the grid on it whose blocks are the puzzle's read; only a
light that fits the grid and its crossings is filled, a blank one only.

    python3 tools/gale_jumbo_read.py read NAME     # read one saved page
    python3 tools/gale_jumbo_read.py plan          # the pages not yet read

The standing pass plans each unread page as a unit (tools/edition_queue.py,
paper "listener", rel "jumbo:NAME"), ahead of the Listener's own pages.
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path
import downloads
import gale_inbox as gi
import file_archive_org_puzzles as fa

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
SERIES = "timesjumbo"
TOOL = "tools/gale_jumbo_read.py"
SAVED = downloads.GALE_CROSSWORDS / "TimesJumbo" / "Fetched"
STORE = Path(os.path.expanduser("~/.cache/gale_jumbo"))
LEDGER = "ledger.jsonl"
#: Bumped when the reading changes, so every page is read again.
VERSION = 7
PREFIX = "jumbo:"
CITED = re.compile(r'^\W*"([^"]*)"\s*Times\b\W*([0-3]?\d)\s+' + gi.MON + r"\s*(\d{4})", re.IGNORECASE)
CITED_NUMBER = re.compile(r"jumbo\s+cross\s?w[a-z]{0,3}d\W{0,3}(?:n[o0]\W{0,3})?(\d[\d,. ]{0,5})", re.IGNORECASE)
ENTRY = re.compile(r"sent\s+to\W+jumbo\s+(?:cross\s?word\s+)?(\d[\d,. ]{0,5})", re.IGNORECASE)
TITLE_WORD = re.compile(r"^\W*j?umbo\W*$", re.IGNORECASE)
#: The Jumbo numbers the Times printed to 2014.
NUMBERS = range(100, 1100)
#: A grid on the page, in the page's pixels: 23x23 or 27x27 cells.
GRID_PX = (600, 3600)
SOLUTIONS = downloads.TIMES_JUMBO_SOLUTIONS
DOCS = Path(os.path.expanduser("~/.cache/gale_inbox/docs.json"))
SOLVED = "solved.jsonl"
#: Bumped when the solution reading changes, so every filed puzzle is tried again.
SOLVED_VERSION = 3
SOLUTION_PREFIX = PREFIX + "solution:"
#: "Solution to Bank Holiday Jumbo 168", "Jumbo Corssword 169": the number after the word Jumbo.
SOLUTION_REF = re.compile(r"\bjumbo\b\D{0,30}?(\d[\d,. ]{0,5})", re.IGNORECASE)
DOC_ID = re.compile(r"[A-Z]{2,6}\d{9,10}")
#: An untitled (Answers) page printing a puzzle's solution is issued within this many days after it.
WINDOW_DAYS = 35
#: The share of a solution grid's cells that must be block or light as the puzzle's grid has them.
FIT = 0.97


def figure(text):
    n = int(re.sub(r"\D", "", text or "") or 0)
    return n if n in NUMBERS else None


def cite_of(cite):
    """(number or None, date) the page's citation gives, or None."""
    m = CITED.search(re.sub(r"\s+", " ", cite or ""))
    if not m:
        return None
    n = CITED_NUMBER.search(m.group(1))
    day = datetime.date(int(m.group(4)), gi.MONTHS[m.group(3)[:3].lower()], int(m.group(2)))
    return (figure(n.group(1)) if n else None), day


def page_files(saved=SAVED):
    d = Path(saved)
    return sorted(p for p in d.iterdir() if p.suffix.lower() == ".pdf" and p.is_file()
                  and not p.name.startswith(".")) if d.is_dir() else []


def load_ledger(store=STORE):
    out = {}
    path = Path(store) / LEDGER
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            out[row["file"]] = row
    return out


def append_row(row, store=STORE):
    Path(store).mkdir(parents=True, exist_ok=True)
    with open(Path(store) / LEDGER, "a") as f:
        f.write(json.dumps(row) + "\n")


#: A page whose read crashed this many times is left as refused (a page that always raises).
CRASH_LIMIT = 3


def read_done(row):
    """Whether a ledger row is a verdict of this VERSION: a crashed attempt (a "failed" row, no
    version while under CRASH_LIMIT) is not, so the page comes back as due."""
    return bool(row) and row.get("version") == VERSION and not (
        row.get("failed") and row.get("attempts", 1) < CRASH_LIMIT)


def plan_pages(saved=SAVED, store=STORE):
    """One unit per saved page not read at VERSION (or whose last attempt crashed), newest first."""
    done = load_ledger(store)
    reason = "never read (Gale fetch)"
    todo = [p for p in page_files(saved) if not read_done(done.get(p.name))]
    todo.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"rel": PREFIX + p.name, "rank": fa.RANKS[reason], "reason": reason, "needs": []} for p in todo]


def plan(saved=SAVED, store=STORE, solutions=SOLUTIONS, docs=DOCS):
    """The pages not yet read, then the filed puzzles whose solution page is on disk."""
    return plan_pages(saved, store) + plan_solutions(store, solutions, docs)


# ------------------------------------------------------------ the solution pages

_LISTED = {}


def citation(cite):
    """(title, date) of a Gale citation ('"Answers." Times, 15 Nov. 2014, p. 152'), or None."""
    m = CITED.search(re.sub(r"\s+", " ", cite or ""))
    if not m:
        return None
    return m.group(1).strip(), datetime.date(int(m.group(4)), gi.MONTHS[m.group(3)[:3].lower()], int(m.group(2)))


def title_number(title):
    """The Jumbo number a solution page's title names ("Solution to Bank Holiday Jumbo 168"), or None:
    an "Answers" page's number is only in its text, so it links by date and the grid's blocks."""
    m = SOLUTION_REF.search(title or "")
    return figure(m.group(1)) if m else None


def doc_titles(docs=DOCS):
    """{doc id: (issue date, title)} of docs.json's jumbo-solution rows."""
    out = {}
    try:
        log = json.loads(Path(docs).read_text())
    except (OSError, ValueError):
        return out
    for key, val in log.items():
        if not key.startswith("TTDA/jumbo-solution/") or not isinstance(val, dict) or not val.get("doc"):
            continue
        m = DOC_ID.search(str(val["doc"]).upper())
        try:
            day = datetime.date.fromisoformat(key.rsplit("/", 1)[1])
        except ValueError:
            continue
        if m:
            out[m.group(0)] = (day, val.get("title") or "")
    return out


def solution_files(folder=SOLUTIONS, docs=DOCS):
    """[(name, issue date, title)] of the solution PDFs, by date. The folder is listed once per
    process (again only when its mtime moves: the fetch is still adding files), the date and title
    from docs.json, else the PDF's own citation (read once)."""
    folder = Path(folder)
    try:
        stamp = folder.stat().st_mtime_ns
    except OSError:
        return []
    held = _LISTED.get(str(folder))
    if held is None or held[0] != stamp:
        names = sorted(p.name for p in folder.iterdir() if p.suffix.lower() == ".pdf" and not p.name.startswith("."))
        held = _LISTED[str(folder)] = (stamp, names, {})
    titled = doc_titles(docs)
    out = []
    for name in held[1]:
        if name not in held[2]:
            m = DOC_ID.search(name.upper())
            found = titled.get(m.group(0)) if m else None
            if found is None:
                data = (folder / name).read_bytes()
                cite = citation(gi.pdf_text(data, pages=4))  # the citation sits on a later page of a Gale PDF
                found = (cite[1], cite[0]) if cite else None
            held[2][name] = found
        if held[2][name]:
            out.append((name, *held[2][name]))
    return sorted(out, key=lambda r: (r[1], r[0]))


def load_solved(store=STORE):
    out = {}
    path = Path(store) / SOLVED
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            out[row["number"]] = row
    return out


def append_solved(row, store=STORE):
    Path(store).mkdir(parents=True, exist_ok=True)
    with open(Path(store) / SOLVED, "a") as f:
        f.write(json.dumps(row) + "\n")


def candidates(row, files):
    """The names of the solution pages that may print the puzzle `row` (a ledger row: number, date):
    those titled with its number, and the untitled ones (an Answers page) issued within WINDOW_DAYS after it."""
    day = datetime.date.fromisoformat(row["date"])
    out = []
    for name, issued, title in files:
        n = title_number(title)
        if n is not None:
            if n == row["number"]:
                out.append(name)
        elif 0 < (issued - day).days <= WINDOW_DAYS:
            out.append(name)
    return out


def filed_rows(store=STORE):
    """The ledger rows of the puzzles filed whole: by this tool (wrote), or by hand (a whole row whose
    puzzle file exists in the puzzles store; one stat per such row)."""
    from fetch_puzzle import puzzle_path
    out = []
    for r in load_ledger(store).values():
        if not (r.get("whole") and r.get("number") and r.get("date")):
            continue
        if r.get("wrote") or puzzle_path(SERIES, r["number"]).exists():
            out.append(r)
    return out


def plan_solutions(store=STORE, solutions=SOLUTIONS, docs=DOCS):
    """One unit per filed puzzle with a solution page on disk that was not tried at SOLVED_VERSION."""
    rows = filed_rows(store)
    if not rows:
        return []
    files = solution_files(solutions, docs)
    if not files:
        return []
    done = load_solved(store)
    out = []
    for r in sorted(rows, key=lambda r: r["date"], reverse=True):
        cands = candidates(r, files)
        last = done.get(r["number"]) or {}
        if cands and (last.get("version") != SOLVED_VERSION or set(cands) - set(last.get("tried") or ())):
            out.append({"rel": SOLUTION_PREFIX + str(r["number"]), "rank": fa.RANKS[fa.JUMBO_SOLUTION],
                        "reason": fa.JUMBO_SOLUTION, "needs": []})
    return out


def grid_candidates(img):
    """[box] of the grid-sized ink on a solution page: page_grids' boxes and every square patch of ink
    (a Times page prints its grid ~38% of the page wide; page_grids keeps the widest *lattice-like* box,
    which can be a photo or a text block, and then never offers the real grid). The block fit judges them."""
    out = [list(b) for b in gi.page_grids(img)]
    for b in fa.grids_on(img, shaped=gi.square):
        b = list(b)
        if not any(max(abs(x - y) for x, y in zip(b, o)) < 0.05 * (b[2] - b[0]) for o in out):
            out.append(b)
    return [b for b in out if GRID_PX[0] <= b[2] - b[0] <= GRID_PX[1]]


def solution_box(path, grid, store=STORE):
    """(block agreement, page index, box) of the grid-sized ink on a solution page whose blocks are the
    puzzle's `grid`'s, or None. The page's grid-shaped boxes are kept in the store."""
    import numpy as np
    import archive_org_jumbo as aj
    import trove_solution_ocr
    cache = Path(store) / "solboxes2" / f"{Path(path).stem}.json"
    pages = gi.images(Path(path))
    if cache.exists():
        boxes = json.loads(cache.read_text())
    else:
        boxes = [[i, b] for i, (img, _) in enumerate(pages) for b in grid_candidates(img)]
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(boxes))
    best = None
    for i, box in boxes:
        gray = np.asarray(pages[i][0].crop(tuple(box)).convert("L"))
        fits = []
        try:
            fits.append(aj.block_fit(gray, grid, trove_solution_ocr.lattice(gray, len(grid), tight=True)))
        except ValueError:
            pass
        # A crop whose frame is no clean rules (a top rule too thin to count: lattice() starts a row
        # low): the reader's own framings, as read_framed matches them, are fitted too.
        try:
            fits += [trove_solution_ocr.block_agreement(g, grid, (ys, xs))
                     for g, ys, xs in trove_solution_ocr.framings(gray, grid)]
        except ValueError:
            pass
        fit = max(fits, default=None)
        if fit is None:
            continue
        if best is None or fit > best[0]:
            best = (fit, i, tuple(box))
    return best


def read_crop(path, index, box, crop, grid):
    """{light id: answer} read off the solution grid at `box` of page `index` of `path`, saved as `crop`."""
    import trove_solution_ocr
    crop.parent.mkdir(parents=True, exist_ok=True)
    gi.images(Path(path))[index][0].crop(tuple(box)).save(crop)
    answers, _ = trove_solution_ocr.read_answers(crop, grid, tight=True)
    return {f"{n}-{d}": w for (n, d), w in answers.items()}


def solve_puzzle(old, names, solutions=SOLUTIONS, store=STORE, finder=None, reader=None):
    """(verdict, new puzzle or None): `old`, the held puzzle this tool filed, with the answers of the
    solution page among `names` whose grid has its blocks. Only a blank light takes an answer that
    fits (merge_answers keep: blog and hand answers stand); refused when the reading does not fit the
    grid's lights and crossings. `finder` and `reader` stand in for the image work."""
    import copy
    import trove_solution_ocr
    finder, reader = finder or solution_box, reader or read_crop
    verdict = {"tried": list(names)}
    grid = trove_solution_ocr.puzzle_grid(old)
    best = None
    for name in names:
        found = finder(Path(solutions) / name, grid, store)
        if found and (best is None or found[0] > best[0][0]):
            best = (found, name)
    if best is None or best[0][0] < FIT:
        verdict["refused"] = "no solution page has the puzzle's blocks" + (f" (best {best[0][0]:.2f})" if best else "")
        return verdict, None
    (fit, index, box), name = best
    verdict.update(solutionFrom=name, fit=round(fit, 3))
    crop = Path(store) / "solutions" / f"{Path(name).stem}_{old['id']}.png"
    answers = {k: v for k, v in reader(Path(solutions) / name, index, box, crop, grid).items() if v}
    if not answers:
        verdict["refused"] = "no answer read off the solution grid"
        return verdict, None
    if not fa.fits_lights(old["entries"], answers):
        verdict["refused"] = "the reading does not fit the grid's lights and crossings"
        return verdict, None
    reading = copy.deepcopy(old)
    for e in reading["entries"]:
        e["solution"] = answers.get(fa.entry_id(e))
    new = copy.deepcopy(old)
    changed = fa.merge_answers(new, reading, tool=TOOL, keep=True)
    verdict["read"] = len(answers)
    verdict["filled"] = len(changed)
    return verdict, (new if changed else None)


def solve_unit(rel, store=STORE, solutions=SOLUTIONS, docs=DOCS):
    """Take the solution page's answers into the filed puzzle `rel` ("jumbo:solution:N") names; the
    solved ledger row appended. Returns "read" or "current"."""
    from fetch_puzzle import puzzle_path, read_puzzle_file, write_puzzle_file
    import provenance
    import copy
    n = int(rel[len(SOLUTION_PREFIX):])
    row = next((r for r in filed_rows(store) if r["number"] == n), None)
    names = candidates(row, solution_files(solutions, docs)) if row else []
    last = load_solved(store).get(n) or {}
    todo = [x for x in names if x not in (last.get("tried") or ())] if last.get("version") == SOLVED_VERSION else names
    if not todo:
        return "current"
    verdict = {"number": n, "version": SOLVED_VERSION}
    target = puzzle_path(SERIES, n)
    old = read_puzzle_file(target) if target.exists() else None
    if old is None or (old.get("source") or {}).get("acquiredBy") != TOOL:
        verdict.update(tried=names, refused="the puzzle is not held as this tool filed it")
    else:
        try:
            found, new = solve_puzzle(old, todo, solutions, store)
        except Exception as e:  # any raise: a bad page is a verdict
            found, new = {"tried": todo, "refused": f"crashed: {type(e).__name__}: {e}"}, None
            print(found["refused"], file=sys.stderr)
        verdict.update(found)
        verdict["tried"] = sorted(set(found.get("tried") or ()) | set(last.get("tried") or ()))
        if new is not None:
            before = provenance.check(old)
            try:
                stamped = provenance.stamp(copy.deepcopy(new), old["source"]["acquiredBy"])
            except ValueError as e:
                stamped = None
                verdict["refused"] = f"provenance: {e}"
            if stamped is not None:
                faults = [f for f in provenance.check(stamped) if f not in before]
                if faults:
                    verdict["refused"] = f"provenance: {faults[0]}"
                else:
                    try:
                        write_puzzle_file(target, new, generator=TOOL)
                        verdict["wrote"] = True
                    except Exception as e:  # the write gate's refusal: the file stands as held
                        verdict["refused"] = f"write refused: {type(e).__name__}: {e}"
    if str(verdict.get("refused", "")).startswith("crashed"):
        verdict.pop("version")  # a crash is no verdict: the puzzle stays due
    append_solved(verdict, store)
    print(json.dumps(verdict))
    return "read"


def links(files, dated):
    """{page name: [numbers]} of the solution pages `files` that `dated` ({number: puzzle date}) puzzles link to."""
    out = {}
    for name, issued, title in files:
        n = title_number(title)
        out[name] = [k for k, d in sorted(dated.items())
                     if (n == k if n is not None else 0 < (issued - d).days <= WINDOW_DAYS)]
    return out


def grid_boxes(img):
    """The page's grid-shaped patches of ink, largest first."""
    boxes = [b for b in gi.page_grids(img) if GRID_PX[0] <= b[2] - b[0] <= GRID_PX[1]]
    return sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)


def extra_boxes(img, boxes):
    """The page's square patches of ink in GRID_PX that `boxes` do not hold, largest first."""
    squares = [b for b in fa.grids_on(img, shaped=gi.square) if GRID_PX[0] <= b[2] - b[0] <= GRID_PX[1]
               and not any(abs(b[0] - o[0]) < 20 and abs(b[1] - o[1]) < 20 for o in boxes)]
    return sorted(squares, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)


def grid_box(img):
    """The page's largest grid-shaped patch of ink, or None."""
    return next(iter(grid_boxes(img)), None)


#: A Jumbo's lattice is 23x23 or 27x27: a 15x15 on the page (the Times' own cryptic) is another puzzle.
JUMBO_SIZES = (23, 27)


def pick_grid(boxes, reader, pads=(6, 0.08)):
    """(box, grid, None) of the first of `boxes` (largest first) whose `reader(box, pad)` ((grid, why)) reads a
    Jumbo-sized lattice, each tried with every pad (pixels, or a share of the box's width: a box cut short of the
    lattice reads "larger than the frame" until it is widened); else (None, None, why of the first refusal)."""
    first = None
    for box in boxes:
        for pad in pads:
            g, why = reader(box, pad if pad >= 1 else int(pad * (box[2] - box[0])))
            if g and len(g) in JUMBO_SIZES:
                return box, g, None
            if first is None:
                first = why if not g else f"the grid on the page is {len(g)}x{len(g)}, not a Jumbo's"
            if g:
                break  # a smaller lattice reads the same at any pad
    return None, None, first


#: The number printed beside the prize text or the banner: "Jumbo 1,033", "Jumbo Crossword 139, The Times"
#: (the words may end a line and the number open the next), "JUMBO CROSSWORD 1.68".
NUMBER_FORMS = (
    ENTRY,
    re.compile(r"\bj[a-z]{1,2}bo\b[^\n]{0,160}\n?[^\n]{0,12}?cross\s?word\s*\(?(\d[\d,.]{0,4})\)?,?\s+The\s+Times", re.IGNORECASE),
    re.compile(r"\bj[a-z]{1,2}bo\s+cross\s?word\s*\(?(\d[\d,.]{0,4})\)?(?!\d)", re.IGNORECASE),
)


def number_in_text(text):
    """The Jumbo number the page's OCR text prints, or None."""
    for form in NUMBER_FORMS:
        for m in form.finditer(text or ""):
            if figure(m.group(1)):
                return figure(m.group(1))
    return None


def number_of(img, key, cited, words):
    import ocr_clues
    if cited and cited[0]:
        return cited[0], "citation"
    n = number_in_text(ocr_clues.lines_of(words))
    return (n, "prize text") if n else (None, None)


def with_fallback_title(titles, width):
    """gale_listener.times_titles' boxes, then a title-less one across the page's top: a page whose title
    is set in a graphic (read "Christmas . Jumbo" or not at all) still has its headings."""
    def wrapped(words):
        return titles(words) + [(0, 0, width, 0)]
    return wrapped


def widest_cuts(cuts, gl):
    """gale_listener.times_cuts as a wrapper: the cuts under each title in turn (the page's own, then the
    title-less one across its top), the widest-boxed cut's list returned. The 1997-98 Jumbo sets its title
    in the preamble beside and below the clue headings, so the headings below the title are only last
    week's solutions (a small box) while the title-less cut holds the Jumbo's own lists."""
    def wrapped(words):
        shown = gl.times_titles(words)
        best = []
        try:
            for title in shown:
                gl.times_titles = lambda _w, t=title: [t]
                got = cuts(words)
                if got and (not best or area(got[0][0]) > area(best[0][0])):
                    best = got
        finally:
            gl.times_titles = shown_titles
        return best
    shown_titles = gl.times_titles
    return wrapped


def area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


#: The VLM is asked for a page's columns when this many lights or fewer are blank (more is a page whose lists are lost).
VLM_BLANKS = 16
#: A number opening a line within this of a blank light's puts its column among those asked.
NEAR_NUMBER = 3
#: The blank-light reason fa.vlm_laid lays a VLM clue on.
UNLAID = "no reading laid a clue on it"


#: A Jumbo clue line opens on its number with no stop ("20 Temporary quarters"): its words follow.
NUMBER_LINE = re.compile(r"^\W{0,2}(\d{1,2})\W{0,2}$")


def numbers_of(located):
    """[word] of the clue numbers in `located` (page words): a figure of one or two digits with a word of letters
    on its line just to its right."""
    out = []
    for w in located:
        if not NUMBER_LINE.match(w[4] or ""):
            continue
        mid = (w[1] + w[3]) / 2
        if any(o is not w and 0 <= o[0] - w[2] <= 60 and o[1] <= mid <= o[3] and re.search(r"[A-Za-z]{2}", o[4])
               for o in located):
            out.append(w)
    return out


def number_lefts(located, step=40, least=3):
    """The left edges of the clue columns: where lines opening on a number line up (gale_listener.column_lefts
    wants a stop after the number, which a Jumbo's lists do not print)."""
    xs = sorted(w[0] for w in numbers_of(located))
    runs = []
    for x in xs:
        if runs and x - runs[-1][-1] <= step:
            runs[-1].append(x)
        else:
            runs.append([x])
    return [min(r) - 15 for r in runs if len(r) >= least]


def vlm_strips(blocks, numbers, gl):
    """[(image, box)] of the clue columns of `blocks` ((image, key)) holding a line that opens on a number
    within NEAR_NUMBER of one of `numbers` (the blank lights'): the columns cut at gale_listener.column_lefts."""
    out = []
    for bimg, bkey in blocks:
        located = gl.figures(gl.page_words(bimg, bkey))
        lefts = number_lefts(located)
        if not lefts:
            continue
        edges = lefts + [bimg.width]
        for i, x0 in enumerate(lefts):
            x1 = edges[i + 1]
            for w in numbers_of(located):
                m = NUMBER_LINE.match(w[4])
                if x0 <= w[0] < x1 and any(abs(int(m.group(1)) - n) <= NEAR_NUMBER for n in numbers):
                    out.append((bimg, (max(0, int(x0)), 0, min(bimg.width, int(x1)), bimg.height)))
                    break
    return out


def vlm_mended(blocks, laid, blank, lengths, gl, reader=None, voted=None):
    """(laid, blank) with each blank light the VLM's reading of the clue columns holding it lays
    (fa.vlm_laid: the one clue under its number whose count fills the light, its words spelt in
    the page's own readings). The VLM is asked the columns holding a blank light only, and only
    when VLM_BLANKS lights or fewer are blank. `reader` (img, box) -> text stands in for the VLM."""
    # A laid clue ocr_clues refuses (a stray letter, a digit in a word) is asked after too: the VLM may spell it.
    weak = {lid for lid, (text, enum, group) in laid.items() if text and lid in lengths and (
        fa.ocr_clues.suspect(text) or fa.ocr_clues.fault(text, enum, sum(lengths.get(i, 0) for i in group or [lid])))}
    if not (blank or weak) or len(blank) > VLM_BLANKS:
        return laid, blank, 0
    if reader is None:
        if not (fa.vlm.wanted()):
            return laid, blank, 0
        def reader(im, box):
            return fa.vlm.read(fa.vlm.crop(im, box))
    strips = vlm_strips(blocks, sorted({int(k.split("-")[0]) for k in [*blank, *weak]}), gl)
    if not strips:
        return laid, blank, 0
    parts = []
    try:
        for im, box in strips:
            parts.append(reader(im, box))
    except RuntimeError:
        return laid, blank, len(parts)  # the VLM gone or spooled: the page is read as without it
    texts = {"vlm": "\n".join(p for p in parts if p)}
    for bimg, bkey in blocks:
        located = gl.figures(gl.page_words(bimg, bkey))
        texts[f"page{len(texts)}"] = " ".join(w[4] for w in located)
    got, left = vlm_laid(texts, laid, blank, lengths, voted or {})
    got = vlm_spelt(texts, got, weak - set(blank), lengths)
    return got, left, len(strips)


def vlm_spelt(texts, laid, weak, lengths):
    """`laid` with each clue of `weak` (laid, but with a word ocr_clues refuses) put as the VLM's reply spells it
    when that clue is the page's own but for its spelling (ALIKE) and the only one under the light's number
    (told apart from its rival by vlm_direction) that is itself unrefused, its count the light's."""
    clues = fa.vlm_clues(texts.get("vlm") or "")
    laid = dict(laid)
    for lid in sorted(weak):
        text, enum, group = laid[lid]
        number, way = lid.split("-")
        cells = sum(lengths.get(i, 0) for i in group or [lid])
        rival = any(o != lid and o.split("-")[0] == number and lengths.get(o) == lengths.get(lid) for o in lengths)
        found = []
        for k, (m, words, count) in enumerate(clues):
            if str(m) != number or (rival and vlm_direction(clues, k, number, lengths) != way):
                continue
            words = fa.ocr_clues.trimmed(fa.ocr_clues.clean(words), lid)
            if fa.ocr_clues.similar(words.lower(), text.lower()) >= ALIKE and fa.ftp.count(count) == cells \
                    and not fa.ocr_clues.unfit(words, fa.ocr_clues.shape(count), cells):
                found.append((words, fa.ocr_clues.shape(count)))
        if len(found) == 1:
            laid[lid] = (found[0][0], found[0][1], group)
    return laid


#: A VLM clue's words and the page's own for the same light are the one clue at this similarity or more.
ALIKE = 0.85


def vlm_direction(clues, k, number, lengths):
    """"across" or "down": the list the VLM clue `k` ((number, words, count) in `clues`' order) stands in, from its
    neighbours in the reply (the clue before it numbered the same-direction light just under it, or the one after the
    light just over it); None when both lists fit or neither."""
    n, fits = int(number), []
    for way in ("across", "down"):
        if f"{number}-{way}" not in lengths:
            continue
        same = sorted(int(o.split("-")[0]) for o in lengths if o.endswith("-" + way))
        below, above = [x for x in same if x < n], [x for x in same if x > n]
        if (k > 0 and below and clues[k - 1][0] == below[-1]) or (
                k + 1 < len(clues) and above and clues[k + 1][0] == above[0]):
            fits.append(way)
    return fits[0] if len(fits) == 1 else None


def vlm_laid(texts, laid, blank, lengths, voted):
    """(laid, blank) with each blank light the VLM's reply lays a clue on: fa.vlm_laid's rule (the one clue under
    the light's number whose count fills it, two words or more, fit to file, its words of four letters or more
    mostly spelt in the page's own readings) with two more ways in. A number the grid gives two lights of one
    length is told apart by the reply's lists (vlm_direction). A light whose own reading (`voted`) printed a count
    short of the light (a count's tail lost to the line end: "(9" for "(9,4)", or one digit off) takes the VLM's
    words when they are those of its own reading (ALIKE) and the only such clue under the number: two readings
    agree on the clue, the light's length gives the count (a grid count, marked so)."""
    text = texts.get("vlm") or ""
    clues = fa.vlm_clues(text)
    bag = {w for k, t in texts.items() if k != "vlm" for w in re.findall(r"[a-z]{4,}", t.lower())}
    laid, left = dict(laid), dict(blank)

    def fit(words, enum, cells, lid, agreed=False):
        words = fa.ocr_clues.trimmed(fa.ocr_clues.clean(words), lid)
        spelt = re.findall(r"[a-z]{4,}", words.lower())
        # `agreed`: the page's own reading prints the same clue, which is the second reading the bag stands for.
        if len(fa.ocr_clues.tokens(words)) < 2 or not spelt or fa.ocr_clues.merged(words) \
                or (not agreed and (sum(1 for w in spelt if w not in bag) > fa.VLM_LAID_MISS * len(spelt)
                                    or not any(w in bag for w in spelt))) or fa.ocr_clues.unfit(words, enum, cells):
            return None
        return words

    for lid, why in blank.items():
        cells = lengths.get(lid)
        number, way = lid.split("-")
        if not cells:
            continue
        here = [(k, w, c) for k, (m, w, c) in enumerate(clues) if str(m) == number]
        rival = any(o != lid and o.split("-")[0] == number and lengths.get(o) == cells for o in lengths)
        whole = [x for x in here if fa.ftp.count(x[2]) == cells]
        if rival:
            whole = [x for x in whole if vlm_direction(clues, x[0], number, lengths) == way]
        if len(whole) == 1:
            enum = fa.ocr_clues.shape(whole[0][2])
            if words := fit(whole[0][1], enum, cells, lid):
                laid[lid], _ = (words, enum, None), left.pop(lid)
                continue
        own = (voted.get(lid) or ("",))[0]
        if not own or not why.startswith("its count"):
            continue
        agree = []
        for k, w, c in here:
            cut = re.split(r"\s\(\s*\d", w)[0].strip()
            if cut and fa.ocr_clues.similar(cut.lower(), own.lower()[:len(cut) + 6]) >= ALIKE:
                agree.append(cut)
        if len(agree) == 1:
            enum = fa.ocr_clues.GridCount(cells)
            if words := fit(agree[0], enum, cells, lid, agreed=True):
                laid[lid], _ = (words, enum, None), left.pop(lid)
    return laid, left


def read_page(path, store=STORE, asker=None):
    """(verdict, puzzle or None) of one saved page. `asker` stands in for the VLM (vlm_mended)."""
    import gale_listener as gl
    import archive_org_jumbo as aj
    import trove_grid
    img, cite = gi.images(path)[0]
    verdict = {"file": path.name}
    cited = cite_of(cite)
    if not cited:
        verdict["refused"] = "no Times citation on the page"
        return verdict, None
    day = cited[1]
    key = gl.image_key(img)
    words = gl.page_words(img, key)
    n, how = number_of(img, key, cited, words)
    if n is None:
        verdict["refused"] = "no Jumbo number in the citation or the prize text"
        return verdict, None
    verdict.update(number=n, numberFrom=how, date=day.isoformat())
    boxes = grid_boxes(img)
    if not boxes:
        verdict["refused"] = "no grid on the page"
        return verdict, None
    gpath = Path(store) / "grids" / f"{path.stem}.png"
    gpath.parent.mkdir(parents=True, exist_ok=True)

    def reader(box, pad):
        img.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(img.width, box[2] + pad),
                  min(img.height, box[3] + pad))).save(gpath)
        return trove_grid.read_grid(gpath)

    box, g, why = pick_grid(boxes, reader)
    if not g:
        # page_grids answers with the shaped boxes alone when the widest is a lattice (a Quick's 13x13): the
        # Jumbo's own grid, set beside it, is among the page's square patches of ink.
        more = extra_boxes(img, boxes)
        box, g, again = pick_grid(more, reader)
        why = again or why
    if not g:
        verdict["refused"] = f"grid unread: {why}"
        return verdict, None
    old, old_titles, old_cuts = gl.TITLE_WORD, gl.times_titles, gl.times_cuts
    gl.TITLE_WORD = TITLE_WORD
    gl.times_titles = with_fallback_title(old_titles, img.width)
    gl.times_cuts = widest_cuts(old_cuts, gl)
    try:
        blocks = gl.times_blocks(img, key)
    finally:
        gl.TITLE_WORD, gl.times_titles, gl.times_cuts = old, old_titles, old_cuts
    if not blocks:
        verdict["refused"] = "no Jumbo clue lists found on the page"
        return verdict, None
    # The grid's light lengths give the vote a count for a clue whose own the OCR lost.
    lengths = {f"{n}-{d}": len(cells) for (n, d), cells in aj.rg.light_cells(g).items()}
    read, laid = gl.times_read(blocks, lengths)
    verdict.update({k: v for k, v in read.items() if k in ("agreed", "clues", "refused")})
    if laid is None:
        return verdict, None
    voted = dict(laid)
    laid, blank = aj.lay_on(dict(laid), g)
    verdict["lights"] = len(laid)
    # The vote's own blanks (a clue it laid empty: unfit, a suspect word) are blank lights too.
    blank = {**(read.get("blank") or {}), **blank}
    # A light laid with no words that no linked clue covers is blank as well (the vote's grid-counted empty).
    tails = {t for _, _, group in laid.values() for t in (group or [])[1:]}
    for lid, (text, _, _) in laid.items():
        if lid not in tails and not (text or "").strip():
            blank.setdefault(lid, UNLAID)
    laid, blank, asked = vlm_mended(blocks, laid, blank, lengths, gl, asker, voted)
    if asked:
        verdict["vlmColumns"] = asked
    verdict["lights"] = len(laid)
    verdict["blank"] = sorted(blank)
    verdict["why"] = {k: str(v)[:80] for k, v in sorted(blank.items())}
    doc = DOC_ID.search(path.name.upper())  # a 2010s document id has six letters, gale_inbox's only two
    url = f"https://link.gale.com/apps/doc/{doc.group(0)}/TTDA?sid=bookmark-TTDA" if doc else None
    puzzle = fa.build(n, day, g, "image", laid, None, 0, series=SERIES, name=f"Times jumbo cryptic crossword No {n:,}",
                      url=url, printed=read.get("asPrinted"))
    verdict["whole"] = bool(fa.complete(puzzle))
    return verdict, puzzle


def read_unit(rel, saved=SAVED, store=STORE):
    """Read one saved page (a unit's rel, "jumbo:NAME" or NAME), file its
    puzzle when whole and no file holds the number; the ledger row appended.
    Returns "read", "current" or "failed"."""
    import scan_queue
    from fetch_puzzle import puzzle_path, write_puzzle_file
    if rel.startswith(SOLUTION_PREFIX):
        return solve_unit(rel, store)
    name = rel[len(PREFIX):] if rel.startswith(PREFIX) else rel
    path = Path(saved) / name
    before = load_ledger(store).get(name)
    if not path.exists() or read_done(before):
        return "current"
    try:
        verdict, puzzle = read_page(path, store)
    except Exception as e:  # any raise: the page stays due (read_done) until CRASH_LIMIT attempts
        attempts = (before or {}).get("attempts", 0) + 1
        verdict, puzzle = {"file": name, "failed": f"crashed: {type(e).__name__}: {e}", "attempts": attempts}, None
        print(verdict["failed"], file=sys.stderr)
        append_row({**verdict, "version": VERSION if attempts >= CRASH_LIMIT else None}, store)
        return "failed"
    if puzzle is not None and verdict.get("whole"):
        target = puzzle_path(SERIES, verdict["number"])
        if target.exists():
            verdict["skip"] = "already held"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            scan_queue.file_puzzle(write_puzzle_file, TOOL, target, puzzle, verdict)
    append_row({**verdict, "version": VERSION}, store)
    print(json.dumps(verdict))
    return "read"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["plan"]:
        print(len(plan()))
        return 0
    if argv[:1] == ["link"]:
        files = solution_files()
        dated = {r["number"]: datetime.date.fromisoformat(r["date"]) for r in load_ledger().values()
                 if r.get("number") and r.get("date")}
        linked = links(files, dated)
        print(f"{sum(1 for v in linked.values() if v)} of {len(files)} solution pages link to a puzzle")
        return 0
    if argv[:1] == ["read"] and len(argv) > 1:
        print(read_unit(argv[1]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
