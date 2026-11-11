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
VERSION = 1
PREFIX = "jumbo:"
CITED = re.compile(r'^\W*"([^"]*)"\s*Times\b\W*([0-3]?\d)\s+' + gi.MON + r"\s*(\d{4})", re.IGNORECASE)
CITED_NUMBER = re.compile(r"jumbo\s+cross\s?word\W{0,3}(?:n[o0]\W{0,3})?(\d[\d,. ]{0,5})", re.IGNORECASE)
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
SOLVED_VERSION = 1
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
    """The ledger rows of the puzzles this tool filed whole."""
    return [r for r in load_ledger(store).values() if r.get("wrote") and r.get("whole") and r.get("number") and r.get("date")]


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


def solution_box(path, grid, store=STORE):
    """(block agreement, page index, box) of the grid-sized ink on a solution page whose blocks are the
    puzzle's `grid`'s, or None. The page's grid-shaped boxes are kept in the store."""
    import numpy as np
    import archive_org_jumbo as aj
    import trove_solution_ocr
    cache = Path(store) / "solboxes" / f"{Path(path).stem}.json"
    pages = gi.images(Path(path))
    if cache.exists():
        boxes = json.loads(cache.read_text())
    else:
        boxes = [[i, list(b)] for i, (img, _) in enumerate(pages) for b in gi.page_grids(img)
                 if GRID_PX[0] <= b[2] - b[0] <= GRID_PX[1]]
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(boxes))
    best = None
    for i, box in boxes:
        gray = np.asarray(pages[i][0].crop(tuple(box)).convert("L"))
        try:
            fit = aj.block_fit(gray, grid, trove_solution_ocr.lattice(gray, len(grid), tight=True))
        except ValueError:
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


def grid_box(img):
    """The page's largest grid-shaped patch of ink, or None."""
    boxes = [b for b in gi.page_grids(img) if GRID_PX[0] <= b[2] - b[0] <= GRID_PX[1]]
    return max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])) if boxes else None


def number_of(img, key, cited, words):
    import ocr_clues
    if cited and cited[0]:
        return cited[0], "citation"
    text = ocr_clues.lines_of(words)
    for m in ENTRY.finditer(text):
        if figure(m.group(1)):
            return figure(m.group(1)), "prize text"
    return None, None


def read_page(path, store=STORE):
    """(verdict, puzzle or None) of one saved page."""
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
    box = grid_box(img)
    if box is None:
        verdict["refused"] = "no grid on the page"
        return verdict, None
    gpath = Path(store) / "grids" / f"{path.stem}.png"
    gpath.parent.mkdir(parents=True, exist_ok=True)
    img.crop((box[0] - 6, box[1] - 6, box[2] + 6, box[3] + 6)).save(gpath)
    g, why = trove_grid.read_grid(gpath)
    if not g:
        verdict["refused"] = f"grid unread: {why}"
        return verdict, None
    old = gl.TITLE_WORD
    gl.TITLE_WORD = TITLE_WORD
    try:
        blocks = gl.times_blocks(img, key)
    finally:
        gl.TITLE_WORD = old
    if not blocks:
        verdict["refused"] = "no Jumbo clue lists found on the page"
        return verdict, None
    read, laid = gl.times_read(blocks)
    verdict.update({k: v for k, v in read.items() if k in ("agreed", "clues", "refused")})
    if laid is None:
        return verdict, None
    laid, blank = aj.lay_on(dict(laid), g)
    verdict["lights"] = len(laid)
    verdict["blank"] = sorted(blank)
    doc = gi.DOC_ID.search(path.name)
    url = f"https://link.gale.com/apps/doc/{doc.group(1).upper()}/TTDA?sid=bookmark-TTDA" if doc else None
    puzzle = fa.build(n, day, g, "image", laid, None, 0, series=SERIES, name=f"Times jumbo cryptic crossword No {n:,}",
                      url=url)
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
