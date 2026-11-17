#!/usr/bin/env python3
"""The TLS (Times Literary Supplement) crosswords, 1992-2014, read from the
pages tools/gale_fetch.py downloads from Gale's TLS Historical Archive, one
GALE_<docId>.pdf each in <Gale crosswords>/TLS/Fetched (no edition layout,
like the Times Jumbo's Fetched folder, whose reader this one follows).

A page's citation ('"TLS Crossword 1018." Times Literary Supplement, 28 Mar.
2014, p. 31') gives its number and date. The clue lists are cut and read as
tools/gale_jumbo_read.py reads a Jumbo page (its title words swapped for "TLS
Crossword"), the grid is the page's 15x15 patch of ink (trove_grid), and a
light the clues do not reach is filed blank, so only a puzzle with every clue
filed (fa.complete) is written. The file is unsolved; puzzles/tls' held
numbers are never written over.

    python3 tools/gale_tls_read.py read NAME     # read one saved page
    python3 tools/gale_tls_read.py plan          # the pages not yet read

The standing pass plans each unread page as a unit (tools/edition_queue.py,
paper "listener", rel "tls:NAME"), after the Jumbo's pages.
"""
import contextlib
import datetime
import json
import os
import re
import signal
import sys
from pathlib import Path
import clue_text
import downloads
import gale_inbox as gi
import file_archive_org_puzzles as fa
import gale_jumbo_read as jr

TOOLS = Path(__file__).resolve().parent
SERIES = "tls"
TOOL = "tools/gale_tls_read.py"
SAVED = downloads.GALE_CROSSWORDS / "TLS" / "Fetched"
STORE = Path(os.path.expanduser("~/.cache/gale_tls"))
LEDGER = "ledger.jsonl"
#: Bumped when the reading changes, so every page is read again.
VERSION = 24
PREFIX = "tls:"
CITED = re.compile(r'^\W*"([^"]*)"\s*Times\s+Literary\s+Supplement\b\W*([0-3]?\d)\s+' + gi.MON + r"\s*(\d{4})",
                   re.IGNORECASE)
CITED_NUMBER = re.compile(r"t\W?l\W?s\s*cross\s?w[a-z]{0,3}d\W{0,3}(?:n[o0]\W{0,3})?(\d[\d,. ]{0,5})", re.IGNORECASE)
TITLE_WORD = re.compile(r"^\W*t\W?l\W?s\W*$", re.IGNORECASE)
#: The TLS numbers printed 1992-2014 (No 98 on 7 Feb 1992; 1,396 and up are the-tls.com's).
NUMBERS = range(90, 1400)
CITES = "cites2.json"  # r22: the cache holds the citation numbers (Nos 1-89 now kept); cites.json held none of them
SIZES = (15,)
CRASH_LIMIT = jr.CRASH_LIMIT
#: Bumped when a crash is fixed: a failed row of an older fix is due again (once more) whatever its attempts.
CRASH_FIX = 1


CITE_NUMBERS = range(1, 1400)


def figure(text, numbers=NUMBERS):
    n = int(re.sub(r"\D", "", text or "") or 0)
    return n if n in numbers else None


def cite_of(cite):
    """(number or None, date) the page's citation gives, or None."""
    m = CITED.search(re.sub(r"\s+", " ", cite or ""))
    if not m:
        return None
    n = CITED_NUMBER.search(m.group(1))
    day = datetime.date(int(m.group(4)), gi.MONTHS[m.group(3)[:3].lower()], int(m.group(2)))
    # The citation's own number is typed text (no OCR): Nos 1-89 (1982-91) are real, where a number read off the
    # page is held to NUMBERS.
    return (figure(n.group(1), CITE_NUMBERS) if n else None), day


def page_files(saved=SAVED):
    return jr.page_files(saved)


def load_ledger(store=STORE):
    return jr.load_ledger(store)


def append_row(row, store=STORE):
    jr.append_row(row, store)


#: Bumped to read once more the pages a VLM answer may still fill (vlm_due). r13: 335 pages stood unfiled with
#: 1-3 lights blank, 3 in 5 of them "its count (4) is short of the light's 10" (a count's tail lost to the
#: line end) or "no reading laid a clue on it"; read again with the VLM up, 7 of 10 sampled pages left no
#: light blank (the live read had the VLM down or its reply unread: no vlmColumns on 41 of 115).
VLM_FIX = 1
#: Reads a page may take to have a VLM reply (a read whose VLM was not asked is tried again) before it stands.
VLM_TRIES = 3
#: Blank reasons the VLM's column reply can lay a clue for (jr.vlm_laid).
VLM_FILLS = ("its count", "no reading laid a clue", "no clue read for it")
#: Any blank reason is due the VLM once (see vlm_due), a page with vlmFix having had it asked.
VLM_ANY = True


def vlm_due(row):
    """Whether `row` (a verdict of this VERSION) left 1-3 lights blank for a reason the VLM's reading can lay
    (VLM_FILLS) and was not read since VLM_FIX with the VLM asked (vlmFix) or VLM_TRIES times."""
    if row.get("whole") or row.get("vlmFix") == VLM_FIX or row.get("vlmTries", 0) >= VLM_TRIES:
        return False
    blank = row.get("blank") or []
    why = row.get("why") or {}
    # r128: up to jr.VLM_BLANKS (16) lights, the most the VLM is asked for: 45 pages (38 of the 192 unfiled NP3 TLS
    # pages 1995-2014) stood with 4-16 lights blank and no vlmFix, never offered the VLM's column reply again.
    if not 1 <= len(blank) <= jr.VLM_BLANKS:
        return False
    # VLM_ANY: a page never read with the VLM asked (no vlmFix) is read again whatever its blank lights' reason
    # ("a quotation it never closes", "readings differ", "both read ... not a word", "no other reading has"):
    # the VLM's column reply spells those too (2010-03-12's 27-across, 2013-04-19's 7-down, whose Down column
    # the live read never asked). r107: 198 of the 229 NP3 TLS pages 1991-2014 stood with no vlmTries.
    return True if VLM_ANY else any(str(why.get(lid, "")).startswith(VLM_FILLS) for lid in blank)


def read_done(row):
    """Whether a ledger row is a verdict of this VERSION (a crashed attempt under CRASH_LIMIT is not; nor one
    whose blank lights the VLM may still fill, vlm_due)."""
    return bool(row) and row.get("version") == VERSION and not (
        row.get("failed") and (row.get("attempts", 1) < CRASH_LIMIT or row.get("crashFix") != CRASH_FIX)) \
        and not vlm_due(row) and not cite_due(row) and not glue_due(row) and not names_due(row)


#: r22: the 81 pages of Nos 1-89 (1982-10-22..1991-03-01) were refused "no TLS number: no numbered page on both
#: sides": their citation prints the number ("TLS Crossword 88.") but cite_of held numbers to 90 and over, so
#: no anchor stood before No 90. Those refusals are read again once (VERSION is left, not to read every page).
CITE_FIX = 1


def cite_due(row):
    """Whether `row` is a "no TLS number" refusal not read since CITE_FIX."""
    return str(row.get("refused", "")).startswith("no TLS number") and row.get("citeFix") != CITE_FIX


def plan(saved=SAVED, store=STORE):
    """One unit per saved page not read at VERSION (or whose last attempt crashed), newest first; then
    the solution units (plan_solutions)."""
    done = load_ledger(store)
    reason = "never read (Gale fetch)"
    todo = [p for p in page_files(saved) if not read_done(done.get(p.name))]
    todo.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out = [{"rel": PREFIX + p.name, "rank": fa.RANKS[reason], "reason": reason, "needs": []} for p in todo]
    return plan_solutions(store, saved) + out


#: A puzzle's solution is printed as a small grid captioned "SOLUTION TO CROSSWORD n" in the issue
#: of puzzle n + SOLUTION_LAG (the page then held one of the numbers around it, tried nearest first).
SOLUTION_PREFIX = PREFIX + "solution:"
SOLUTION_LAGS = (4, 3, 5)
SOLVED_VERSION = 5
FIT = 0.97


def solution_pages(n, rows):
    """[page file name] of the ledger `rows` ({file: row}) that may print puzzle n's solution."""
    by_number = {}
    for name, r in rows.items():
        # Back-issue rows (tlsback-N, page images in TLS/Backfill) are no Fetched PDF to solve from;
        # their keys come from the-tls.com (tls_pdf_keys / tls_image_keys).
        if r.get("number") and r.get("whole") is not None and not name.startswith("tlsback-"):
            by_number.setdefault(r["number"], []).append(name)
    return [name for lag in SOLUTION_LAGS for name in sorted(by_number.get(n + lag, ()))]


def unsolved(puzzle):
    """Whether a held puzzle has a light with no answer."""
    return any(not e.get("solution") for e in puzzle["entries"])


def plan_solutions(store=STORE, saved=SAVED):
    """One unit per held puzzle with a blank light and a page of its solution's issue read, not tried at
    SOLVED_VERSION (or with another page to try now)."""
    from fetch_puzzle import puzzle_path, read_puzzle_file
    rows = load_ledger(store)
    done = load_solved(store)
    out = []
    for n in sorted({r["number"] for r in rows.values() if r.get("number")}, reverse=True):
        names = solution_pages(n, rows)
        target = puzzle_path(SERIES, n)
        if not names or not target.exists():
            continue
        last = done.get(n) or {}
        if last.get("version") == SOLVED_VERSION and not set(names) - set(last.get("tried") or ()):
            continue
        held = read_puzzle_file(target)
        if held and unsolved(held):
            out.append({"rel": SOLUTION_PREFIX + str(n), "rank": fa.RANKS[fa.JUMBO_SOLUTION],
                        "reason": fa.JUMBO_SOLUTION, "needs": []})
    return out


#: The small solution grid's width on a page, in pixels (556 on a 3,384-px page, ~720 on a 5,509-px one).
SOLUTION_PX = (400, 1500)
#: The grid is fitted and read at twice its size: a 37-px cell's thin rules put the lattice at the wrong
#: pitch (tls-724: 0.73 as it is, 1.0 at 2x).
SOLUTION_SCALE = 2


def square_lattice(gray, grid):
    """(block agreement, (x0, y0, pitch, pitch)) of the best lattice of square cells on a grid image: the
    pitch the frame's rules give or the image's width or height over the cells, offsets a little round
    the frame's. 11-14: a solution grid's top and bottom rules print thin, so lattice(tight) took a row
    rule for the frame (y0 one row low, pitch 84 for 98) and most refused TLS grids fitted at
    0.6-0.9 with the blocks of the puzzle shifted a row."""
    import trove_solution_ocr as t
    n, m = len(grid), len(grid[0])
    height, width = gray.shape
    try:
        lat = t.lattice(gray, n, tight=True)
    except ValueError:
        lat = (0.0, 0.0, width / m, height / n)
    pitches = {round(p, 1) for p in (lat[2], width / m, height / n)}
    best = (0.0, None)
    # the ink image and its opening depend on the pitch only (the opening's size), not the offsets: 11-15
    # the ~225 offsets tried on a 2,600-px crop each redid both (tls:solution:751: 30+ min, never ended)
    ink = (gray >= t.trove_grid.otsu(gray)).astype("uint8")
    opens = {}

    def agreement(lat_):
        ys, xs = t.even(lat_, n)
        k = max(2, round(min(ys[-1] - ys[0], xs[-1] - xs[0]) / n / 12))
        if k not in opens:
            opens[k] = t.opened(ink, k)
        seen = {}
        for r in range(n):
            for c in range(m):
                a = t.between(opens[k], ys, xs, r, c, 0.15)
                if a.size == 0:
                    return 0.0
                seen[(r, c)] = float(a.mean()) < t.BLOCK_PAPER
        return sum(seen[(r, c)] == (ch == "#") for r, row in enumerate(grid) for c, ch in enumerate(row)) / (n * m)

    def tried(x0, y0, p):
        nonlocal best
        if y0 < -p / 2 or y0 + n * p > height + p / 2 or x0 < -p / 2 or x0 + m * p > width + p / 2:
            return
        fit = agreement((float(x0), float(y0), p, p))
        if fit > best[0]:
            best = (fit, (float(x0), float(y0), p, p))
    # coarse (a cell is ~50 px at 2x, so 6 px steps are well inside one), then fine round the best
    for p in pitches:
        for x0 in {round(base + d) for base in (lat[0], 0) for d in (-6, 0, 6)}:
            for y0 in {round(base + d) for base in (lat[1] - p, lat[1] - 2 * p, lat[1], 0) for d in (-6, 0, 6)}:
                tried(x0, y0, p)
    if best[1] is not None:
        x0, y0, p, _ = best[1]
        for dx in (-4, -2, 0, 2, 4):
            for dy in (-4, -2, 0, 2, 4):
                tried(x0 + dx, y0 + dy, p)
    return best


def solution_box(path, grid, store=STORE):
    """jr.solution_box with the small grid's sizes, and the boxes it kept refitted on a square lattice
    (square_lattice) when that fits better."""
    import numpy as np
    from PIL import Image
    found = jr.solution_box(path, grid, store, px=SOLUTION_PX, scale=SOLUTION_SCALE)
    if found is not None and found[0] >= jr.FIT:
        return found
    cache = Path(store) / "solboxes2" / f"{Path(path).stem}.json"
    if not cache.exists():
        return found
    pages = gi.images(Path(path))
    for i, box in json.loads(cache.read_text()):
        crop = pages[i][0].crop(tuple(box)).convert("L")
        gray = np.asarray(crop.resize((crop.width * SOLUTION_SCALE, crop.height * SOLUTION_SCALE), Image.LANCZOS))
        fit = square_lattice(gray, grid)[0]
        if found is None or fit > found[0]:
            found = (fit, i, tuple(box))
    return found


CAPTION = re.compile(r"SOLUTION\s+TO\s+CROSS\s?WORD\s+(?:No\.?\s*)?(\d[\d,. ]{0,4})", re.IGNORECASE)


def caption_number(path, index, box, store=STORE):
    """[n] the "SOLUTION TO CROSSWORD n" printed under the grid at `box` of page `index` of `path` reads as
    at 2x, 3x and 1x (kept in the store; [] when no caption is read)."""
    import gale_listener as gl
    import ocr_clues
    cache = Path(store) / "captions" / f"{Path(path).stem}_{index}_{round(box[0])}_{round(box[1])}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    img = gi.images(Path(path))[index][0]
    w, h = box[2] - box[0], box[3] - box[1]
    band = img.crop((max(0, round(box[0] - w / 4)), round(box[3]), min(img.width, round(box[2] + w / 4)),
                     min(img.height, round(box[3] + h / 3)))).convert("RGB")
    found = []
    for scale in (2, 3, 1):  # one scale may garble a digit (1023 read 1231 at 2x)
        scaled = band.resize((band.width * scale, band.height * scale))
        text = " ".join(x[4] for x in ocr_clues.tesseract_words(scaled, ocr_clues.TESS_MODELS["times"]))
        m = CAPTION.search(text)
        if m:
            found.append(gl.num(m.group(1)))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(found))
    return found


def says(n, said):
    """Whether a caption read [numbers] may name puzzle n. 11-14: the number's last digit is glued to a
    stray mark in the print (960 read 9601, 990 read 9901, 999 read 9991) or cut (960 read 96), so a
    reading one digit longer with n as its start, or n with a digit cut, names n too."""
    s = str(n)
    return any(x == n or (str(x).startswith(s) and len(str(x)) == len(s) + 1)
               or (len(str(x)) == len(s) - 1 and len(str(x)) >= 2 and s.startswith(str(x))) for x in said)


def captioned(n):
    """A solution_box finder for puzzle n: the page's grid box, unless the caption under it names another puzzle."""
    def find(path, grid, store=STORE):
        found = solution_box(path, grid, store)
        if found is not None and found[0] >= jr.FIT:
            said = caption_number(path, found[1], found[2], store)
            if said and not says(n, said):  # the caption is read, at no scale as this puzzle's number
                return None
        return found
    return find


def read_crop(path, index, box, crop, grid):
    """jr.read_crop with the names rule (trove_solution_ocr.named_reads): a light every cell of which is read
    and the whole light read as the same word, a name or a phrase too."""
    import numpy as np
    import trove_solution_ocr
    crop.parent.mkdir(parents=True, exist_ok=True)
    small = gi.images(Path(path))[index][0].crop(tuple(box))
    big = small.resize((small.width * SOLUTION_SCALE, small.height * SOLUTION_SCALE))
    big.save(crop)
    fit, lat = square_lattice(np.asarray(big.convert("L")), grid)
    # the square lattice is one more framing, only where it is the one that fits the puzzle's blocks
    framing = lat if fit >= jr.FIT else None
    answers, _ = trove_solution_ocr.read_answers(crop, grid, tight=True, named=True, framing=framing)
    return {f"{k[0]}-{k[1]}": w for k, w in answers.items()}


def load_solved(store=STORE):
    return jr.load_solved(store)


#: A solution unit stops itself after this long (the queue kills one at 1,800 s and records nothing).
UNIT_SECONDS = 1200


class UnitTimeout(Exception):
    pass


@contextlib.contextmanager
def deadline(seconds):
    """Raise UnitTimeout in the running code after `seconds` (SIGALRM; no deadline off the main thread)."""
    def fire(signum, frame):
        raise UnitTimeout(f"over {seconds} s")
    try:
        before = signal.signal(signal.SIGALRM, fire)
    except ValueError:  # not the main thread
        yield
        return
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, before)


def solve_unit(rel, store=STORE, saved=SAVED):
    """Take the solution grid printed in a later issue into the held puzzle `rel` ("tls:solution:N") names
    (a blank light only, as jr.solve_puzzle: refused when the grid's blocks are not the puzzle's or the
    reading does not fit its lights). The solved ledger row appended. Returns "read" or "current"."""
    from fetch_puzzle import puzzle_path, read_puzzle_file, write_puzzle_file
    import copy
    import provenance
    n = int(rel[len(SOLUTION_PREFIX):])
    names = solution_pages(n, load_ledger(store))
    last = load_solved(store).get(n) or {}
    todo = [x for x in names if x not in (last.get("tried") or ())] if last.get("version") == SOLVED_VERSION else names
    if not todo:
        return "current"
    verdict = {"number": n, "version": SOLVED_VERSION}
    target = puzzle_path(SERIES, n)
    old = read_puzzle_file(target) if target.exists() else None
    if old is None:
        verdict.update(tried=names, refused="no puzzle held")
    elif not unsolved(old):
        verdict.update(tried=names, refused="every light already answered")
    else:
        try:
            with deadline(UNIT_SECONDS):
                found, new = jr.solve_puzzle(old, todo, saved, store, finder=captioned(n), reader=read_crop,
                                         tool=TOOL)
        except Exception as e:  # any raise (or the deadline): a bad page is a verdict
            found, new = {"tried": todo, "refused": f"crashed: {type(e).__name__}: {e}"}, None
            print(found["refused"], file=sys.stderr)
        found["tool"] = TOOL
        verdict.update(found)
        verdict["tried"] = sorted(set(found.get("tried") or ()) | set(last.get("tried") or ()))
        if new is not None:
            before = provenance.check(old)
            try:
                stamped = provenance.stamp(copy.deepcopy(new), (old.get("source") or {}).get("acquiredBy") or TOOL)
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
                        verdict["whole"] = not unsolved(new)
                    except Exception as e:  # the write gate's refusal: the file stands as held
                        verdict["refused"] = f"write refused: {type(e).__name__}: {e}"
    if str(verdict.get("refused", "")).startswith("crashed"):
        # a crash is no verdict: the puzzle stays due, until CRASH_LIMIT attempts (the queue's 1,800-s
        # kill writes nothing, so the deadline above is what records an attempt)
        verdict["attempts"] = (last.get("attempts") or 0) + 1
        if verdict["attempts"] < CRASH_LIMIT:
            verdict.pop("version")
    jr.append_solved(verdict, store)
    print(json.dumps(verdict))
    return "read"


def cites(saved=SAVED, store=STORE):
    """[(name, date, printed number or None)] of every saved page, in date order, read off the PDFs' own text
    (pypdf alone) and kept in the store: the anchors number_from_anchors dates a numberless page from."""
    path = Path(store) / CITES
    files = page_files(saved)
    if path.exists():
        got = json.loads(path.read_text())
        if len(got) == len(files):
            return [(a, datetime.date.fromisoformat(b), c) for a, b, c in got]
    import pypdf
    rows = []
    for p in files:
        try:
            text = "\n".join(pg.extract_text() or "" for pg in pypdf.PdfReader(str(p)).pages)
        except Exception:  # an unreadable PDF has no anchor; its own read says why
            continue
        c = cite_of(text)
        if c:
            rows.append((p.name, c[1], c[0]))
    rows.sort(key=lambda r: (r[1], r[0]))
    Path(store).mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps([(a, b.isoformat(), c) for a, b, c in rows]))
    os.replace(tmp, path)
    return rows


def anchors_of(rows):
    """The indexes of `rows` whose printed number runs on from the last anchor's (a repeat or misprint is none)."""
    anchors, last = [], 0
    for i, (_, _, n) in enumerate(rows):
        if n and n > last and all(m is None or m > n for _, _, m in rows[i + 1:i + 2]):
            anchors.append(i)
            last = n
    return anchors


def number_from_anchors(name, rows):
    """(number, None) a page `name` is given by the numbered pages either side of it in `rows` (date order),
    else (None, why). An anchor is a page whose printed number runs on from the one before (a repeated or
    misprinted number is none); the pages between two anchors that no anchor numbers must be exactly the
    numbers missing between them, taken in date order, or no page of the gap is numbered (the Times Literary
    Supplement ran monthly in 1992 and weekly later, so a step is never assumed)."""
    anchors = anchors_of(rows)
    at = next((i for i, r in enumerate(rows) if r[0] == name), None)
    if at is None:
        return None, "page not among the saved citations"
    before = max((i for i in anchors if i < at), default=None)
    after = min((i for i in anchors if i > at), default=None)
    if before is None or after is None:
        return None, "no numbered page on both sides"
    between = [i for i in range(before + 1, after) if i not in anchors]
    missing = rows[after][2] - rows[before][2] - 1
    if len(between) != missing:
        return None, f"{len(between)} unnumbered pages but {missing} numbers missing between Nos {rows[before][2]} and {rows[after][2]}"
    return rows[before][2] + 1 + between.index(at), None


def number_on_page(words):
    """The TLS number the page's OCR text prints beside its title, or None."""
    import ocr_clues
    m = CITED_NUMBER.search(ocr_clues.lines_of(words))
    return figure(m.group(1)) if m else None


#: The count closing a clue ("(5)", "(3,4)", OCR-cut "(6"), and the lines and counts a column of the lists has.
COUNT_WORD = re.compile(r"\(\d{1,2}(?:[,\-]\d{1,2})*[).]?\W{0,2}$")
HEAD_WORD = re.compile(r"(?i)^\W*(across|down|acr|dow)")
NUMBER_WORD = re.compile(r"^[^\w£$€]{0,2}\d{1,2}[.,]?$")
COLUMN_COUNTS = 3
#: Counts further apart than this many line heights are not one list's.
COUNT_GAP = 12
#: A column's heading or opening number is looked for this many line heights over its first count.
HEAD_REACH = 40


#: A sliver of a column this many line heights wide or less is a column of clue numbers split from its clues
#: by the finer gutter (the number and its text are set a gap apart), not a column of its own.
NUMBER_SLIVER = 3


def joined_numbers(pieces, lh):
    """`pieces` ([(left, right)], left to right) with each sliver of NUMBER_SLIVER line heights or less joined
    to the piece after it, so a list's clue numbers stay in the crop of its clues."""
    out, carry = [], None
    for i, (left, right) in enumerate(pieces):
        if carry is not None:
            left, carry = carry, None
        if right - left <= NUMBER_SLIVER * lh and i + 1 < len(pieces):
            carry = left
            continue
        out.append((left, right))
    return out


def layout_columns(words, grid):
    """[(x0, y0, x1, y1)] the clue lists' columns found by their own shape, left to right, for a page times_cuts
    reads no ACROSS and DOWN pair under a title on (the 1990s pages set the lists beside and under the grid,
    among prose columns, with headings the page OCR often loses): the page's text columns (the gutters no
    word crosses, the grid's words left out) holding COLUMN_COUNTS counts or more are the lists', each from
    its heading, if one stands over it, or its first count's clue to its last count."""
    import gale_listener as gl
    lh = gl.line_height(words)

    def in_grid(w):
        return grid[0] <= (w[0] + w[2]) / 2 <= grid[2] and grid[1] <= (w[1] + w[3]) / 2 <= grid[3]
    rest = [w for w in words if not in_grid(w)]
    counts = [w for w in rest if COUNT_WORD.search(w[4])]
    if len(counts) < 2 * COLUMN_COUNTS:
        return []
    # The band is the longest run of counts with no gap over COUNT_GAP line heights: a count far from the lists
    # (a stray "(5)" in a caption) would stretch it over prose that crosses every gutter.
    ys = sorted(counts, key=lambda w: w[1])
    runs = [[ys[0]]]
    for w in ys[1:]:
        if w[1] - runs[-1][-1][3] > COUNT_GAP * lh:
            runs.append([])
        runs[-1].append(w)
    run = max(runs, key=len)
    y0, y1 = min(w[1] for w in run) - 4 * lh, max(w[3] for w in run) + lh

    def listy(left, right, mine):
        # COLUMN_COUNTS counts, or a count and three lines opening on a clue number (the OCR loses counts)
        return len(mine) >= COLUMN_COUNTS or (bool(mine) and len(line_numbers(
            [w for w in rest if left <= (w[0] + w[2]) / 2 <= right], lh)) >= 3)
    gs = gl.gutters(rest, y0, y1, lh)
    bands = []
    for (_, left), (right, _) in zip(gs, gs[1:]):
        mine = [w for w in counts if left <= (w[0] + w[2]) / 2 <= right]
        if not listy(left, right, mine):
            continue
        # A band may hold a prose column beside the lists (a gutter a headline or a photo crosses): looked at
        # again over the counts' own lines alone, with narrower gutters.
        top, bottom = min(w[1] for w in mine) - lh, max(w[3] for w in mine) + lh
        fine = gl.gutters([w for w in rest if left <= (w[0] + w[2]) / 2 <= right], top, bottom, lh / 2)
        pieces = [(a[1], b[0]) for a, b in zip(fine, fine[1:]) if a[1] >= left - 1 and b[0] <= right + 1]
        bands += joined_numbers(pieces, lh) or [(left, right)]
    cols = []
    for left, right in bands:
        mine = [w for w in counts if left <= (w[0] + w[2]) / 2 <= right]
        if not listy(left, right, mine):
            continue
        first = min(w[1] for w in mine)
        # the heading over the first count, within reach, the highest
        over = [w for w in rest if left <= w[0] <= right and first - HEAD_REACH * lh <= w[1] < first
                and (HEAD_WORD.match(w[4]) and w[3] - w[1] < 3 * lh)]
        top = min([first - 2 * lh, *(w[1] for w in over)])
        if not over:
            # no heading: the first clue's lines stand over its count (its first line is several up when the
            # clue wraps), on up to its number, the first gap of three line heights or eight line heights
            start = top
            for w in sorted((w for w in rest if left <= (w[0] + w[2]) / 2 <= right and w[1] < start),
                            key=lambda w: -w[3]):
                if top - w[3] > 3 * lh or start - w[1] > 8 * lh:
                    break
                top = min(top, w[1])
                if NUMBER_WORD.match(w[4]) and w[0] <= left + 4 * lh:
                    break
        # A list whose opening clues the OCR reads thinly (1993-07-30's across 1-13 stand over a column found
        # from 14): on up through the column's clue numbers that fall (4, 1) within COUNT_GAP line heights.
        inside = [n for n in line_numbers([w for w in rest if left <= w[0] <= right and w[1] >= top], lh)
                  if n[3] <= left + 4 * lh]
        prev = min((n[2] for n in inside[:1]), default=1)
        cur = top
        if prev > 1:
            for ytop, ybottom, n, x in sorted((n for n in line_numbers(
                    [w for w in rest if left <= w[0] <= right and w[1] < top], lh) if n[3] <= left + 4 * lh),
                    key=lambda n: -n[1]):
                if n >= prev or cur - ybottom > COUNT_GAP * lh:
                    break
                top, cur, prev = min(top, ytop - lh), ytop, n
                if n <= 1:
                    break
        # The page OCR loses counts down a column: its lines run on to the first gap of three line heights,
        # layout_block trimming the crop to its last count read there.
        bottom = max(w[3] for w in mine)
        for w in sorted((w for w in rest if left <= (w[0] + w[2]) / 2 <= right and w[1] > bottom),
                        key=lambda w: w[1]):
            if w[1] - bottom > 3 * lh:
                break
            bottom = max(bottom, w[3])
        # ...and on past a gap (an advert, a photo) to the column's next clue numbers within twelve.
        for ytop, ybottom, _, x in line_numbers([w for w in rest if left <= w[0] <= right and w[1] > bottom], lh):
            if left <= x <= left + 4 * lh and ytop - bottom < 12 * lh:
                bottom = ybottom + 4 * lh
        cols.append((int(max(0, left - lh / 2)), int(max(0, top - lh / 2)), int(right + lh / 2),
                     int(bottom + lh / 2)))
    return cols


def pitch_columns(words, grid, cols):
    """[(x0, y0, x1, y1)] candidate columns at the pitch of the lists' own columns, under the grid: a list
    runs on in more columns under it, set at the columns' regular pitch with no gutter the OCR finds among
    the prose there. Each candidate is kept by layout_block only if its re-read crop holds the counts of
    clue lines."""
    import gale_listener as gl
    lh = gl.line_height(words)
    if not cols or not words:
        return []
    below = grid[3] + lh / 2
    # the pitch is that of the widest list column found, a gutter's half-line added
    left, top, right, bottom = max(cols, key=lambda c: c[2] - c[0])
    pitch = right - left + lh / 2
    wide = max(w[2] for w in words)
    out = []
    x0 = left + pitch
    while x0 + pitch / 2 < wide:
        box = (int(x0), int(below), int(x0 + pitch - lh / 2), int(max(below + 10 * lh, bottom + 8 * lh)))
        # a column found already, or one lying beside the grid's height, is not a pitch column; one that only
        # clips a found column's edge (the pitch drifts a few line heights over the columns: 1993-02-26's
        # fourth column, clipping the third's right edge) is set from that column's edge instead
        hit = [c for c in cols if c[0] < box[2] and box[0] < c[2] and c[1] < box[3] and box[1] < c[3]]
        if hit and all(min(box[2], c[2]) - max(box[0], c[0]) < pitch / 4 and c[0] < box[0] for c in hit):
            edge = max(c[2] for c in hit)
            box = (int(edge), box[1], int(edge + pitch - lh / 2), box[3])
            hit = []
        elif hit and all(c[0] >= box[0] and box[2] - c[0] < pitch / 4 for c in hit):
            # the pitch drifts the other way: the box clips the left edge of the next found column (1608's
            # third down column, its fourth found from its counts): set to end where that column starts
            box = (box[0], box[1], int(min(c[0] for c in hit) - lh / 2), box[3])
            hit = []
        if not hit:
            out.append(box)
        x0 = box[2] + lh / 2
    return out


#: A second list's clue numbers stand this many line heights or more in from the crop's left edge...
SIDE_REACH = 8
#: ...at least this many of them, at one x within a line height.
SIDE_NUMBERS = 3


def side_by_side(ws, width, lh):
    """The x of the gutter between two lists a crop holds side by side (1992-06-05's across tail and its first
    down column, the second down column set right of them with no gap the OCR sees: their lines read as one,
    each across line followed by the other list's), or None: where SIDE_NUMBERS clue numbers stand at one x
    SIDE_REACH line heights or more in and no more than one word's box crosses the cut left of them."""
    def opens_clue(n):
        # a clue's number has the clue's words after it on its line (a stray figure in prose has not)
        return any(w[0] >= n[2] and abs((w[1] + w[3]) / 2 - (n[1] + n[3]) / 2) < lh / 2 and re.search(r"[A-Za-z]{2}", w[4])
                   for w in ws)
    nums = [w for w in ws if NUMBER_WORD.match(w[4]) and w[0] > SIDE_REACH * lh and w[0] < width - 4 * lh
            and opens_clue(w)]
    for n in sorted(nums, key=lambda w: w[0]):
        mine = sorted((w for w in nums if abs(w[0] - n[0]) <= lh), key=lambda w: w[1])
        figures = [int(re.sub(r"\D", "", w[4])) for w in mine]
        # a list's numbers run on down the column
        if len(mine) < SIDE_NUMBERS or figures != sorted(set(figures)):
            continue
        x = int(min(w[0] for w in mine) - lh / 2)
        # looked at over the lines of those numbers alone (prose columns run on under the lists)
        near = [w for w in ws if min(m[1] for m in mine) - 3 * lh <= w[1] <= max(m[3] for m in mine) + lh]
        if sum(1 for w in near if w[0] < x < w[2]) <= 1 and sum(1 for w in near if w[2] <= x) >= 12:
            return x
    return None


def line_numbers(words, lh):
    """[(top, bottom, number, left)] of the lines of `words` opening on a clue's number and a word."""
    ws = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines = []
    for w in ws:
        if lines and abs((w[1] + w[3]) / 2 - lines[-1][0]) < lh / 2:
            lines[-1][1].append(w)
        else:
            lines.append([(w[1] + w[3]) / 2, [w]])
    out = []
    for _, line in lines:
        line.sort()
        # (a back issue's clue may open on the word "A" or "I": 1607's "2 A music producer")
        if NUMBER_WORD.match(line[0][4]) and len(line) > 1 and (
                re.search(r"[A-Za-z]{2}", line[1][4])
                or (BACK_STRICT[0] and len(line) > 2 and line[1][4] in ("A", "I") and re.search(r"[a-z]{2}", line[2][4]))):
            out.append((min(w[1] for w in line), max(w[3] for w in line), int(re.sub(r"\D", "", line[0][4])), line[0][0]))
    return out


#: A blank run between a column's lines (an advert's or the grid's place, the lists' own break) is squeezed to
#: this many line heights, once it is over SQUEEZE_OVER: the lists' reader ends a list at a gap.
SQUEEZE_TO, SQUEEZE_OVER = 1.5, 3


def squeezed(crop, ws, y0, y1, lh):
    """The rows y0 to y1 of `crop` with each blank run between the lines of `ws` (its words) over SQUEEZE_OVER
    line heights squeezed to SQUEEZE_TO of them, and the blank above the first line and under the last
    trimmed to half a line height."""
    from PIL import Image
    spans = sorted((max(y0, int(w[1])), min(y1, int(w[3]))) for w in ws if w[3] > y0 and w[1] < y1)
    keep = []  # [top, bottom] of each run of lines
    for a, b in spans:
        if keep and a - keep[-1][1] <= SQUEEZE_OVER * lh:
            keep[-1][1] = max(keep[-1][1], b)
        else:
            keep.append([a, b])
    if not keep:
        return crop.crop((0, y0, crop.width, max(y1, y0 + 1)))
    pad = int(lh / 2)
    runs = [[max(y0, a - pad), min(y1, b + pad)] for a, b in keep]
    gap = int(SQUEEZE_TO * lh)
    out = Image.new("RGB", (crop.width, sum(b - a for a, b in runs) + gap * (len(runs) - 1)), "white")
    y = 0
    for i, (a, b) in enumerate(runs):
        out.paste(crop.crop((0, a, crop.width, b)).convert("RGB"), (0, y))
        y += b - a + gap
    return out


#: A crop whose quarter-darkest grey is under TINTED has a screened (grey) ground the OCR loses lines in
#: (1993-07-30's across 5-12); ink is told from the ground at CLEAR_AT. The crop is thresholded, and kept so
#: only where its OCR then reads CLEAR_GAIN times the words.
TINTED, CLEAR_AT, CLEAR_GAIN, CLEAR_BAND = 200, 100, 1.2, 60


def cleared(crop, ws, ocr):
    """(crop, words) with `crop` thresholded to black on white where its ground is tinted and that makes the OCR
    read CLEAR_GAIN times the words or more, else as given."""
    import numpy as np
    from PIL import Image
    grey = np.asarray(crop.convert("L"))
    out, tinted = np.array(crop.convert("RGB")), False
    # band by band: the screen covers some rows of a column (1993-07-30's top), the rest is left as it is
    for y in range(0, grey.shape[0], CLEAR_BAND):
        band = grey[y:y + CLEAR_BAND]
        if band.size and np.percentile(band, 25) < TINTED:
            out[y:y + CLEAR_BAND] = ((band > CLEAR_AT) * 255).astype("uint8")[:, :, None]
            tinted = True
    if not tinted:
        return crop, ws
    clean = Image.fromarray(out)
    more = ocr(clean)
    if len(more) >= CLEAR_GAIN * max(1, len(ws)):
        return clean, more
    return crop, ws


#: Lines opening on a figure over a list's clue 1 that are prose's, not the list's (more are its earlier clues).
STRAY_FIGURES = 2


def prose_over(nums, lh):
    """The y a list's crop is trimmed to (over its clue 1's line), or None: only where at most STRAY_FIGURES lines
    open on a figure over the 1 (a run of numbers over it is across's tail, with down's 1 standing under it:
    1993-09-03's across 8-26 over down 1)."""
    ones = [y0 for y0, _, n, _ in nums if n == 1]
    if ones and nums[0][2] > 1 and ones[0] > lh and sum(1 for n in nums if n[0] < ones[0]) <= STRAY_FIGURES:
        return int(ones[0] - lh / 2)
    return None


def open_clue_under(ws, last, lh):
    """Whether the words of a list column `ws` under its last count's line (`last`, the line's bottom) open on
    a clue number at the column's left, within OPEN_CLUE_REACH line heights: a clue whose count stands in the
    next column. Prose under the lists opens on no number."""
    under = [w for w in ws if w[1] >= last - 2]
    if not under:
        return False
    left = min(w[0] for w in ws)
    first = min(under, key=lambda w: (w[1], w[0]))
    row = [w for w in under if abs(w[1] - first[1]) < lh / 2]
    return (any(NUMBER_WORD.match(w[4]) and w[0] <= left + 4 * lh for w in row)
            and first[1] - last <= OPEN_CLUE_REACH * lh)


#: The first line of a clue run on into the next column stands within this many line heights of the last count.
OPEN_CLUE_REACH = 2
#: Such a clue runs to this many rows; a word of this many capitals or more (a solution grid's letters) ends it.
OPEN_CLUE_ROWS = 3
SHOUT = 4


#: Set while a back issue is read: a row under a clue's first line is its words only where it reads like clue
#: text (a solution grid's letters set under the lists, 1607's "MOR EAU", do not).
BACK_STRICT = [False]


def clue_row(row):
    """Whether a row of words reads as a clue's line: under two all-capital words, and a lowercase word of three
    letters or more."""
    caps = [w for w in row if re.fullmatch(r"[A-Z]{2,}\W*", w[4])]
    return len(caps) < 2 and any(re.fullmatch(r"\W*[A-Za-z]*[a-z][A-Za-z]{2,}\W*", w[4]) for w in row)


def open_clue_rows(ws, last, lh):
    """The rows (lists of words) of the clue open_clue_under finds: from the row under `last`, on while the next
    row stands within two line heights and holds no word of SHOUT capitals, to OPEN_CLUE_ROWS rows."""
    under = sorted((w for w in ws if w[1] >= last - 2), key=lambda w: w[1])
    rows = []
    for w in under:
        if rows and abs(w[1] - rows[-1][0][1]) < lh / 2:
            rows[-1].append(w)
        else:
            rows.append([w])
    out = []
    for row in rows[:OPEN_CLUE_ROWS]:
        if out and (row[0][1] - out[-1][0][3] > 2 * lh
                    or any(re.fullmatch(r"[A-Z]{%d,}\W*" % SHOUT, w[4]) for w in row)
                    or (BACK_STRICT[0] and not clue_row(row))):
            break
        out.append(row)
    return out


#: The height a layout_block image is scaled down to where it is taller.
LAYOUT_MAX_HEIGHT = 4000
#: A foot's column index is past every column's.
FOOT = 1000
#: A foot's clue numbers stand this many line heights in from the column's own.
FOOT_INSET = 0.75


def foot_cut(ws, lh):
    """The y a column's foot is cut at, or None: the last lines of a column opening on a clue number set in from
    the others' (FOOT_INSET line heights), at least two of them, running up, after at least four lines of the
    column's own."""
    lines = sorted(line_numbers(ws, lh))
    if len(lines) < 6:
        return None
    base = sorted(n[3] for n in lines)[len(lines) // 2]
    tail = []
    for n in reversed(lines):
        if n[3] <= base + FOOT_INSET * lh:
            break
        tail.insert(0, n)
    if len(tail) < 2 or len(lines) - len(tail) < 4 or [n[2] for n in tail] != sorted({n[2] for n in tail}):
        return None
    return int(tail[0][0] - lh / 3)


def layout_pick(img, words, grid, lengths, gl):
    """layout_block's image, or its side-by-side set where it is over LAYOUT_MAX_HEIGHT and the readers lay
    no clue on some light of the tall one (1592's; 1341's tall one reads whole and stays)."""
    block = layout_block(img, words, grid)
    if block and block[0].height > LAYOUT_MAX_HEIGHT:
        _, laid = lending(gl.times_read, [block], lengths)
        if laid is None or set(lengths) - set(laid):
            return layout_block(img, words, grid, wide=True) or block
    return block


def layout_block(img, words, grid, ocr=None, wide=False):
    """(image, key) of the lists `layout_columns` finds, set one under another in a single column with
    "ACROSS" and "DOWN" headings drawn clean over them: across is read from the first column to the line the
    clue numbers start again on (a number of 3 or under after higher ones), down from there on. The grid
    and the headings the page already reads in the columns are blanked. None where no column or no restart
    of the numbers is found (so the page's lists stay unread, not misread)."""
    from PIL import Image, ImageDraw, ImageFont
    import gale_listener as gl
    ocr = ocr or (lambda im: gl.page_words(im, gl.image_key(im)))
    lh = gl.line_height(words)
    pieces = []  # (column index, crop, its words)
    found = layout_columns(words, grid)
    boxes = found + pitch_columns(words, grid, found)
    # a box holding two lists side by side (no gutter the page's words show) is cut where the second's numbers start
    cut = []
    for k, box in enumerate(boxes):
        probe = img.crop(box).copy()
        ImageDraw.Draw(probe).rectangle((grid[0] - box[0], grid[1] - box[1], grid[2] - box[0], grid[3] - box[1]),
                                        fill="white")
        x = side_by_side(ocr(probe), probe.width, lh)
        cut += [(k, (box[0], box[1], box[0] + x, box[3])), (k, (box[0] + x, box[1], box[2], box[3]))] if x else [(k, box)]
    # a column index per piece: a pitch column's is past the found ones, a box's halves keep its own
    order = [(k, box) for k, box in cut]
    for i, (k, box) in enumerate(order):
        crop = img.crop(box).copy()
        draw = ImageDraw.Draw(crop)
        draw.rectangle((grid[0] - box[0], grid[1] - box[1], grid[2] - box[0], grid[3] - box[1]), fill="white")
        ws = ocr(crop)
        crop, ws = cleared(crop, ws, ocr)
        if i == 0:
            # the first list opens on its clue 1: the prose over it (1993-01-22's competition rules, read into
            # 1-across's clue) is not the list's
            dy = prose_over(line_numbers(ws, lh), lh)
            if dy:
                crop = crop.crop((0, dy, crop.width, crop.height))
                ws = [(w[0], w[1] - dy, w[2], w[3] - dy, *w[4:]) for w in ws if w[1] >= dy]
        ends = [w[3] for w in ws if COUNT_WORD.search(w[4])]
        # (a pitch column is last in the order but stands left of the short column set under the grid: 1606's
        # 20-down opens under its last count and runs on there)
        runs_right = i + 1 < len(order) or any(o[1][0] > box[0] for o in order)
        if ends and runs_right and open_clue_under(ws, max(ends), lh):
            # a clue that opens under the column's last count and runs on in the next column (1600's 13-across,
            # its count in the second column) is the list's: the crop keeps its lines, not the matter under them
            # (the last puzzle's solution grid, its prize notice): rows of words with no capitals run, a few
            keep = max(ends)
            for row in open_clue_rows(ws, max(ends), lh):
                keep = max(keep, max(w[3] for w in row))
            crop = crop.crop((0, 0, crop.width, int(keep + lh / 2)))
            ws = [w for w in ws if w[3] <= crop.height]
        elif ends and max(ends) + lh < crop.height:
            # the column's matter under its last count (prose, a notice) is not the lists'
            crop = crop.crop((0, 0, crop.width, int(max(ends) + lh / 2)))
            ws = [w for w in ws if w[3] <= crop.height]
        if k >= len(found):
            # a pitch column is kept only where its clue numbers run on from the last column kept
            nums = [n for _, _, n, _ in line_numbers(ws, lh)]
            # (the column it runs on from is the last kept to its left: 1606's pitch column of 16-21 down stands
            # between the column ending on 15 and a short one of 22, 23 set under the grid)
            left = [p for p in pieces if order[p[0]][1][0] < box[0]] or pieces
            before = [n for _, _, n, _ in line_numbers(left[-1][2], lh)]
            # (the last column of a landscape page holds across's tail and down's first clues: its biggest number
            # is across's 27, the numbers that run on are down's, from its last line: 1608's 17, 20, 22 down)
            runs_on = bool(before) and bool(nums) and any(b < nums[0] <= b + 5 for b in (max(before), before[-1]))
            if not nums or not runs_on or len([w for w in ws if COUNT_WORD.search(w[4])]) < 1:
                continue
        at = len(pieces)
        if k >= len(found):
            # a pitch column stands in x between the columns it runs on from and into
            at = next((j for j, p in enumerate(pieces) if order[p[0]][1][0] > box[0]), len(pieces))
        pieces.insert(at, (i, crop, ws))
    if not pieces:
        return None
    # a foot set in from the column's left (1592's down 17, 19, 21 and 22, 23, 25 under the columns) is cut off
    # each piece and read after the others, left to right: the list runs on there
    feet = []
    for n, (i, crop, ws) in enumerate(list(pieces)):
        cut = foot_cut(ws, lh)
        if cut is not None and cut < crop.height:
            pieces[n] = (i, crop.crop((0, 0, crop.width, cut)), [w for w in ws if w[3] <= cut])
            feet.append((order[i][1][0], crop.crop((0, cut, crop.width, crop.height)),
                         [(w[0], w[1] - cut, w[2], w[3] - cut, *w[4:]) for w in ws if w[1] >= cut]))
    pieces += [(FOOT + j, crop, ws) for j, (_, crop, ws) in enumerate(sorted(feet, key=lambda f: f[0]))]
    # the headings the OCR read in a column are blanked, so the ones drawn are the only ones
    for _, crop, ws in pieces:
        draw = ImageDraw.Draw(crop)
        for w in ws:
            if HEAD_WORD.match(w[4]) and len(re.sub(r"\W", "", w[4])) <= 8:
                draw.rectangle((w[0] - 4, w[1] - 4, w[2] + 4, w[3] + 4), fill="white")
    # the restart is the biggest fall of the numbers to 3 or under (a stray figure in prose over the lists,
    # 1993-01-22's "5", is a small fall the lists' own run up to 27 beats)
    top, peak, drop = None, 0, 3
    for k, crop, ws in pieces:
        for y0, y1, n, _ in line_numbers(ws, lh):
            if peak and 1 <= n <= 3 and peak - n > drop and (top is None or drop < 10):
                top, drop = (k, y0), peak - n
            peak = max(peak, n)
    if top is None:
        return None
    across, down = [], []
    for k, crop, ws in pieces:
        if k < top[0]:
            across.append(squeezed(crop, ws, 0, crop.height, lh))
        elif k > top[0]:
            down.append(squeezed(crop, ws, 0, crop.height, lh))
        else:
            cut = max(1, int(top[1] - lh / 3))
            across.append(squeezed(crop, ws, 0, cut, lh))
            down.append(squeezed(crop, ws, cut, crop.height, lh))
    font = ImageFont.load_default(size=46)
    width = max(c.width for c in across + down) + 40
    parts = []
    for title, group in (("ACROSS", across), ("DOWN", down)):
        head = Image.new("RGB", (width, 60), "white")
        ImageDraw.Draw(head).text((20, 8), title, fill="black", font=font)
        parts += [head, *group]
    out = Image.new("RGB", (width, sum(p.height for p in parts)), "white")
    y = 0
    for p in parts:
        out.paste(p, (20, y))
        y += p.height
    if wide:
        # a set of big columns (1592's, 37-pixel lines) stood one under another is over what the readers take
        # in (none reads a word of it): they are set side by side as the page has them, each heading over
        # the first column of its list
        items = []
        for title, group in (("ACROSS", across), ("DOWN", down)):
            head = Image.new("RGB", (width, 60), "white")
            ImageDraw.Draw(head).text((20, 8), title, fill="black", font=font)
            for j, p in enumerate(group):
                if j:
                    items.append(p)
                else:
                    item = Image.new("RGB", (width, 60 + p.height), "white")
                    item.paste(head, (0, 0))
                    item.paste(p, (20, 60))
                    items.append(item)
        gap = 80
        out = Image.new("RGB", (sum(p.width for p in items) + gap * len(items), max(p.height for p in items) + 40),
                        "white")
        x = gap // 2
        for p in items:
            out.paste(p, (x, 20))
            x += p.width + gap
    return out, gl.image_key(out)


#: Figures a scan's OCR reads for each other (a 9's loop open, an 8's closed up): a count read with one of them
#: for the light's own length is the light's count misread, the clue's text and number being the voted ones.
LOOKALIKES = {frozenset(p) for p in ("17", "38", "56", "59", "68", "89", "79", "06", "08", "78", "25", "57", "67", "45")}
#: A page whose lights fit their counts less often than this has a grid no count may be mended by.
MEND_FIT = 0.7


def mended_counts(laid, lengths):
    """`laid` with each clue whose count is short of its light (the grid's cells in `lengths`) by figures the OCR
    mistakes for each other (LOOKALIKES: 1992-10-02's "(5)" for a 9-letter 7-down's "(9)", "(8)" for 3-down's),
    its count put as the light's, only on a page whose other lights mostly fit their counts (the grid read is
    then right, not the clue's count). A group of a linked count is mended alone, the others standing."""
    import file_trove_puzzles as ftp
    fits = [lid for lid, (text, enum, _) in laid.items() if lid in lengths and text and enum
            and ftp.count(enum) == lengths[lid]]
    counted = [lid for lid, (text, enum, _) in laid.items() if lid in lengths and text and enum]
    if not counted or len(fits) < MEND_FIT * len(counted):
        return laid
    out = dict(laid)
    for lid, (text, enum, group) in laid.items():
        if lid not in lengths or not text or not enum or ftp.count(enum) >= lengths[lid]:
            continue
        parts = re.split(r"(\d+)", enum)
        figures = [i for i, p in enumerate(parts) if p.isdigit()]
        fixed = []
        for i in figures:
            for new in sorted(c for c in "0123456789" if frozenset(parts[i] + c) in LOOKALIKES and len(parts[i]) == 1):
                mended = parts[:i] + [new] + parts[i + 1:]
                if ftp.count("".join(mended)) == lengths[lid]:
                    fixed.append("".join(mended))
        if len(set(fixed)) == 1:
            out[lid] = (text, fixed[0], group)
    return out


MAC_NAME = re.compile(r"^(\W*M(?:a?c))([a-z])([a-z]{3,}\W*)$")


def mended_tokens(laid, lengths):
    """`laid` with each token ocr_clues.suspect doubts mended where the mend is no longer doubted: a Mac/Mc name
    read with its second capital small ("Rob Roy Macgregor", 1996-11-22's 14-across, whole on the reread)
    capitalised."""
    import ocr_clues
    out = dict(laid)
    for lid, (text, enum, group) in laid.items():
        if not text:
            continue
        flagged = {tok for tok, _ in ocr_clues.suspect(text)}
        if not flagged:
            continue
        words = text.split(" ")
        for i, w in enumerate(words):
            if w not in flagged:
                continue
            if m := MAC_NAME.match(w):
                words[i] = m.group(1) + m.group(2).upper() + m.group(3)
        new = " ".join(words)
        if new != text and len(ocr_clues.suspect(new)) < len(flagged):
            out[lid] = (new, enum, group)
    return out


#: A run of this many lines' worth of lone capitals (a neighbouring solution grid's letters, read into a clue's
#: lines: 1597's 13-across) is no clue's words.
LETTER_RUN = 8
#: A surname set with its particle's capital small ("DeLillo", "DiCaprio", "LeCarre") is no OCR slip.
CAMEL_NAME = re.compile(r"^\W*(?:De|Di|Da|La|Le|Du|Van|Von|Ap|Fitz)[A-Z][a-z]{2,}(?:'s)?\W*$")


#: A bracketed count of figures, commas and hyphens that ends a clue's words.
STRAY_COUNT = re.compile(r"\s*\(\s*\d+\s*(?:[,\-]\s*(?:\d+\s*)?)*\)\s*$")


def spaced_quotes(text):
    """`text` with a space where a straight double quote is glued to the word outside it: an opening one after a
    word ('Colonel"Chalky"') and a closing one before a bracket ('seminary"(W S Gilbert)')."""
    out, k = [], 0
    for i, ch in enumerate(text):
        if ch == '"':
            k += 1
            if k % 2 and i and text[i - 1].isalnum():
                out.append(" ")
            out.append(ch)
            if not k % 2 and i + 1 < len(text) and (text[i + 1].isalnum() or text[i + 1] == "("):
                out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


#: A cross-reference number glued to the word before ("purveyed by10") or after it ("aka 23Anthony").
XREF_AFTER = re.compile(r"(?<=[a-z]{2})(\d{1,2})(?=[\s,.;:?!)\"]|$)")
XREF_BEFORE = re.compile(r"(?<![\w-])(\d{1,2})(?=[A-Z][a-z]{2,})")


def spaced_xref(text):
    """`text` with a space where a light's number is glued to the word beside it, kept only when that leaves
    fewer words ocr_clues.suspect flags ("a digit inside a word"); no letter is added or cut."""
    new = XREF_BEFORE.sub(r"\1 ", XREF_AFTER.sub(r" \1", text))
    return new if new != text and len(fa.suspect(new)) < len(fa.suspect(text)) else text


#: Where a space was lost in the print's line (r62: 1-3 clues short, 26 of 125 suspect clues): a word glued to an
#: initial ("fromE. L. Doctorow"), a figure ("dated1876", "Camus's28", "251musically", "I...made") or a bracket,
#: quote or the word after a stop ("fingers,"has", "saint)recalls", "political(Thomas").
GLUED = (
    # an initial only where a capitalised word follows it, so a stray grid letter ("tableT.") is not made one
    (re.compile(r"(?<=[a-z]{2})(?=[A-Z]\.\s+[A-Z])"), ""),
    (re.compile(r"(?<=[a-z])([1-9]\d{0,3})(?=['’]s\b|[\s,.;:?!)\"”’]|$)"), r" \1"),
    (re.compile(r"(?<=[a-z])([1-9]\d{0,2})(?=[A-Z][a-z]{2,})"), r" \1 "),
    (re.compile(r"(?<![\w-])([1-9]\d{0,2})(?=[a-z]{4,})"), r"\1 "),
    (re.compile(r"(?<=[a-z]{2})(?=\([A-Za-z]{2})"), ""),
    (re.compile(r"(?<=[a-z]\))(?=[a-z]{2})"), ""),
    (re.compile(r"(?<=[a-z][,;:?!])(?=[A-Za-z“‘(])"), ""),
    (re.compile(r"(?<=[”\"])(?=\([A-Za-z])"), ""),
    (re.compile(r"(?<=\.\.\.)(?=[A-Za-z])"), ""),
)


def spaced_glue(text):
    """`text` with a space where a lost one is glued (GLUED), kept only when that leaves fewer words
    ocr_clues.suspect flags; no letter is added or cut, so no word stands that the readers did not agree on."""
    new = text
    for pat, rep in GLUED:
        new = pat.sub(rep or " ", new)
    new = re.sub(r"  +", " ", new)
    return new if new != text and len(fa.suspect(new)) < len(fa.suspect(text)) else text


#: Bumped to read once more the pages whose suspect clue a lost space glues (glue_due). r62.
GLUE_FIX = 1


def glue_due(row):
    """Whether `row` (a verdict of this VERSION) is not whole and holds a suspect clue spaced_glue mends, and was
    not read since GLUE_FIX."""
    if row.get("whole") or row.get("glueFix") == GLUE_FIX:
        return False
    return any(spaced_glue(t) != t for t in ((row.get("unfit") or {}).get("suspect") or {}).values())


#: r91: a page whose readings all agreed (agreed == clues) stood unfiled for a clue's real name or repeated word
#: that fa.suspect doubts ("Jim Crace" 'a word misread as a name', "Greek ... Greek"; 13 of 142 suspect-only pages
#: of 506 unfit TLS pages). Those flags, on such a page, are the print's own (names_printed), so the page is read
#: once more (names_due).
NAMES_FIX = 1
NAMES_WHY = ("a word misread as a name", "a letter lost from a name", "an earlier word repeated inside the clue")


def names_flagged(text):
    """[token] fa.suspect flags in `text` for a reason only a real name or repeated word explains (NAMES_WHY), or
    None when it flags anything else."""
    flags = fa.suspect(text)
    if not flags or any(why not in NAMES_WHY for _, why in flags):
        return None
    return [tok for tok, _ in flags]


def names_due(row):
    """Whether `row` (a verdict of this VERSION) is not whole, agreed on every clue, holds a suspect clue only a real
    name explains (names_flagged), and was not read since NAMES_FIX."""
    if row.get("whole") or row.get("namesFix") == NAMES_FIX or not row.get("clues") or row.get("agreed") != row.get("clues"):
        return False
    return any(names_flagged(t) for t in ((row.get("unfit") or {}).get("suspect") or {}).values())


def names_printed(puzzle, verdict):
    """`puzzle` with the real-name tokens (names_flagged) of each clue kept as printed, when every reading agreed
    on the page's clues (verdict agreed == clues)."""
    if not verdict.get("clues") or verdict.get("agreed") != verdict.get("clues"):
        return
    for e in puzzle["entries"]:
        clue = e.get("clue") or {}
        flagged = names_flagged(clue.get("text") or "")
        if flagged:
            clue["asPrinted"] = sorted({*(clue.get("asPrinted") or ()), *flagged})


def mended_text(laid, printed):
    """(laid, printed) with each clue's text set to rights where the page's print is plain: the lone capitals of a
    neighbour's solution grid cut out of it, a bracket an ellipsis closes ("...)") given its opening, a quote
    spaced from the words glued to it; a camel-cased surname kept as printed. A word is only cut or spaced,
    never added, so no word stands that the readers did not agree on."""
    out, printed = dict(laid), dict(printed or {})
    for lid, (text, enum, group) in laid.items():
        if not text:
            continue
        words = text.split()
        run, keep = [], []
        for w in words + [None]:
            if w is not None and re.fullmatch(r"[A-Za-z]{1,2}", w) and (w.isupper() or len(w) == 1):
                run.append(w)
                continue
            if len(run) < LETTER_RUN or sum(1 for r in run if r.isupper()) < LETTER_RUN - 2:
                keep += run
            run = []
            if w is not None:
                keep.append(w)
        new = " ".join(keep)
        new = clue_text.open_ellipsis_bracket(new)
        if enum:
            # A count the clue's own enumeration already holds is not left in its words (1387's 12-across "(5, )").
            new = STRAY_COUNT.sub("", new)
        new = spaced_quotes(new)
        new = spaced_xref(new)
        new = spaced_glue(new)
        if new != text:
            out[lid] = (new, enum, group)
        names = [w for w in new.split() if CAMEL_NAME.match(w)]
        if names:
            printed[lid] = [*printed.get(lid, ()), *names]
    return out, printed


def no_lists_why(words):
    """Why a page with a TLS citation and a grid-shaped patch has no clue lists: a page that prints no ACROSS
    and DOWN headings and under COLUMN_COUNTS clue counts (1992-04-17's, a correction notice and the grid of
    No 100 reprinted, its clues on the page before) holds no puzzle; any other is a list the readers lost."""
    import ocr_clues
    counts = len([w for w in words if COUNT_WORD.search(w[4])])
    heads = len([w for w in words if re.fullmatch(r"(ACROSS|DOWN)\W*", w[4])])
    if counts >= COLUMN_COUNTS or heads:
        return "no TLS clue lists found on the page"
    notice = re.search(r"(?i)apologi[sz]e|in error|errors in|given correctly", ocr_clues.lines_of(words))
    return ("no puzzle on the page: a correction notice and a grid with no clue lists (" if notice
            else "no puzzle on the page: no clue lists (") + f"{counts} clue counts, no ACROSS or DOWN)"


def pick_grid(boxes, reader, pads=(6, 0.08)):
    """(box, grid, None) of the first of `boxes` whose `reader(box, pad)` reads a 15x15 lattice, else
    (None, None, why of the first refusal)."""
    first = None
    for box in boxes:
        for pad in pads:
            g, why = reader(box, pad if pad >= 1 else int(pad * (box[2] - box[0])))
            if g and len(g) in SIZES:
                return box, g, None
            if first is None:
                first = why if not g else f"the grid on the page is {len(g)}x{len(g)}, not a TLS's"
            if g:
                break
    return None, None, first


#: The widths (pixels, inside the patch's edge) of the rule drawn on a grid patch's edge, thinnest first.
FRAME_RULES = (4, 12, 20)


def framed_crop(crop, box, width=FRAME_RULES[0]):
    """`crop` with a black rule `width` thick drawn round `box` (x0, y0, x1, y1 in the crop's own pixels), the
    grid's frame closed where a faint rule left it open."""
    from PIL import ImageDraw
    out = crop.convert("RGB")
    x0, y0, x1, y1 = box
    ImageDraw.Draw(out).rectangle((x0, y0, x1 - 1, y1 - 1), outline="black", width=width)
    return out


def lending(read, *args):
    """read(*args) with gale_listener's LEND_NUMBERS set: a clue number the Tesseract reading reads and a
    RapidOCR reading drops is lent to it (1996-03-22's 4 and 5 down, "no reading laid a clue on it")."""
    import gale_listener as gl
    old, gl.LEND_NUMBERS = gl.LEND_NUMBERS, True
    names, gl.al.NAMES_ALIKE = gl.al.NAMES_ALIKE, True
    try:
        return read(*args)
    finally:
        gl.LEND_NUMBERS = old
        gl.al.NAMES_ALIKE = names


def read_page(path, store=STORE, asker=None, known=None):
    """(verdict, puzzle or None) of one saved page. `asker` stands in for the VLM (jr.vlm_mended).
    `known` is (number, date) for a page that prints no Gale citation (a tlsback: image, whose number
    is its folder's and whose date is the footer's, else the csv's)."""
    import gale_listener as gl
    import archive_org_jumbo as aj
    import trove_grid
    img, cite = gi.images(path)[0]
    verdict = {"file": path.name}
    if known:
        img = scaled_up(img)
    key = gl.image_key(img)
    if known:
        # the footer's date wins over the csv's; the byline gives the setter
        words = gl.page_words(img, key)
        day, setter = footer_and_setter(words, img.height)
        verdict["setter"] = setter
        if day:
            verdict["footerDate"] = day.isoformat()
        cited = (known[0], day or known[1])
    else:
        cited = cite_of(cite)
    if not cited:
        verdict["refused"] = "no TLS citation on the page"
        return verdict, None
    day = cited[1]
    n, how = cited[0], "citation"
    if known:
        n, how = known[0], "issue"
    elif n is not None:
        rows = cites()
        # A printed number that does not run on from its neighbours' (a misprint, a repeat) is no anchor.
        if not any(rows[i][0] == path.name for i in anchors_of(rows)):
            n = None
    if n is None:
        rows = cites()
        n, why = number_from_anchors(path.name, rows)
        how = "anchors"
        if n is None:
            verdict["refused"] = f"no TLS number: {why}"
            return verdict, None
        seen = number_on_page(gl.page_words(img, key))
        if seen is not None and seen != n:
            verdict["refused"] = f"the page prints No {seen}, the anchors give No {n}"
            return verdict, None
    verdict.update(number=n, numberFrom=how, date=day.isoformat())
    boxes = jr.grid_boxes(img)
    if not boxes:
        # The page's ink patches the lists' gutter-shaped test passes may all be small (1992-05-01's real grid
        # is the largest square of ink, its "grid" patch the little solution of the last puzzle beside it).
        boxes = jr.extra_boxes(img, [])
    if not boxes:
        verdict["refused"] = "no grid on the page"
        return verdict, None
    gpath = Path(store) / "grids" / f"{path.stem}.png"
    gpath.parent.mkdir(parents=True, exist_ok=True)

    def reader(box, pad):
        crop = img.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(img.width, box[2] + pad),
                         min(img.height, box[3] + pad)))
        crop.save(gpath)
        g, why = trove_grid.read_grid(gpath)
        if not g and (why or "").startswith("the white cells span"):
            # A frame rule the scan has faint on a side lets that edge row's cells run out into the margin
            # (1366's bottom row: 14 rows read, the 15th lost): the patch's edge drawn in, the grid read again.
            # (1405's bottom rule stands a few pixels under its last row's cells, so a thin rule drawn on the
            # patch's edge leaves a corridor between them: thicker rules are tried after.)
            for width in FRAME_RULES:
                framed = framed_crop(crop, (min(pad, box[0]), min(pad, box[1]), min(pad, box[0]) + box[2] - box[0],
                                            min(pad, box[1]) + box[3] - box[1]), width)
                framed.save(gpath)
                again, _ = trove_grid.read_grid(gpath)
                if again:
                    return again, None
        return g, why

    box, g, why = pick_grid(boxes, reader)
    if g:
        # The patch found may be the last puzzle's little solution grid (1428's) with the puzzle's own grid, the
        # larger, among the patches only the wider search finds: that one is read if it is twice the area.
        area = (box[2] - box[0]) * (box[3] - box[1])
        larger = [b for b in jr.extra_boxes(img, boxes) if (b[2] - b[0]) * (b[3] - b[1]) >= 2 * area]
        if larger:
            box2, g2, _ = pick_grid(larger, reader)
            if g2:
                box, g = box2, g2
    if not g:
        box, g, again = pick_grid(jr.extra_boxes(img, boxes), reader)
        why = again or why
    if not g:
        verdict["refused"] = f"grid unread: {why}"
        return verdict, None
    lengths = {f"{k[0]}-{k[1]}": len(cells) for k, cells in aj.rg.light_cells(g).items()}
    old, old_titles, old_cuts = gl.TITLE_WORD, gl.times_titles, gl.times_cuts
    gl.TITLE_WORD = TITLE_WORD
    gl.times_titles = jr.with_fallback_title(old_titles, img.width)
    gl.times_cuts = jr.reaching_cuts(jr.widest_cuts(old_cuts, gl), gl, box)
    try:
        blocks = gl.times_blocks(img, key)
    finally:
        gl.TITLE_WORD, gl.times_titles, gl.times_cuts = old, old_titles, old_cuts
    if not blocks:
        # No ACROSS and DOWN pair read under a title: the lists found by their own shape beside the grid.
        words = gl.page_words(img, key)
        block = layout_pick(img, words, box, lengths, gl)
        blocks = [block] if block else []
        if blocks:
            verdict["cut"] = "layout"
    if not blocks:
        verdict["refused"] = no_lists_why(gl.page_words(img, key))
        return verdict, None
    read, laid = lending(gl.times_read, blocks, lengths)
    if (laid is None or set(lengths) - set(laid)) and verdict.get("cut") != "layout":
        # The title's cut left a light unread (its lists lie beside the grid or run on in columns under it, in a
        # shape the page's headings do not frame): the lists found by their own shape (layout_block), kept
        # where they read more.
        block = layout_pick(img, gl.page_words(img, key), box, lengths, gl)
        if block:
            again, laid2 = lending(gl.times_read, [block], lengths)
            if laid2 is not None and (laid is None or again.get("agreed", 0) > read.get("agreed", 0)):
                read, laid, laid2 = again, laid2, laid
                verdict["cut"] = "layout"
            if laid2 is not None and laid is not None:
                # a light only the other reading laid is taken from it (1992-10-02's 24-down stands in a
                # column the title's cut stops short of, 1993-06-25's 2-down in one the layout does)
                laid = {**{k: v for k, v in laid2.items() if k in lengths}, **laid}
    verdict.update({k: v for k, v in read.items() if k in ("agreed", "clues", "refused", "unparsed")})
    if laid is None:
        return verdict, None
    voted = dict(laid)
    laid = mended_tokens(mended_counts(laid, lengths), lengths)
    laid, printed = mended_text(laid, read.get("asPrinted"))
    laid, blank = aj.lay_on(dict(laid), g)
    verdict["lights"] = len(laid)
    blank = {**(read.get("blank") or {}), **blank}
    tails = {t for _, _, group in laid.values() for t in (group or [])[1:]}
    for lid, (text, _, _) in laid.items():
        if lid not in tails and not (text or "").strip():
            blank.setdefault(lid, jr.UNLAID)
    laid, blank, asked = jr.vlm_mended(blocks, laid, blank, lengths, gl, asker, voted)
    if asked:
        verdict["vlmColumns"] = asked
    verdict["lights"] = len(laid)
    verdict["blank"] = sorted(blank)
    verdict["why"] = {k: str(v)[:80] for k, v in sorted(blank.items())}
    doc = jr.DOC_ID.search(path.name.upper())
    url = f"https://link.gale.com/apps/doc/{doc.group(0)}/TLSH?sid=bookmark-TLSH" if doc else None
    if known:
        url = known[2]
    puzzle = fa.build(n, day, g, "image", laid, None, 0, series=SERIES, name=f"TLS crossword No {n:,}",
                      url=url, printed=printed)
    if known and verdict.get("setter"):
        puzzle["setter"] = verdict["setter"]
    names_printed(puzzle, verdict)
    verdict["whole"] = bool(fa.complete(puzzle))
    if not verdict["whole"]:
        verdict["unfit"] = unfit_why(puzzle)
    return verdict, puzzle


def unfit_why(puzzle):
    """Why fa.complete refuses a puzzle: {"blank": clues with no text, "suspect": {entry: text} OCR made
    up, "faults": {entry: why} ocr_clues refuses}, each key only when it holds something."""
    out = {}
    entries = puzzle["entries"]
    empty = [f"{e.get('number')}-{e.get('direction')}" for e in entries
             if not ((e.get("clue") or {}).get("text") or "").strip()]
    if empty:
        out["blank"] = empty
    bad = {}
    for e in entries:
        clue = e.get("clue") or {}
        if fa.suspect(clue.get("text", ""), printed=clue.get("asPrinted") or ()):
            bad[f"{e.get('number')}-{e.get('direction')}"] = str(clue.get("text"))[:80]
    if bad:
        out["suspect"] = bad
    found = fa.faults(puzzle)
    if found:
        out["faults"] = {k: str(v)[:80] for k, v in found.items()}
    return out


def read_unit(rel, saved=SAVED, store=STORE):
    """Read one saved page (a unit's rel, "tls:NAME" or NAME), file its puzzle when whole and no file holds
    the number; the ledger row appended. Returns "read", "current" or "failed"."""
    import scan_queue
    from fetch_puzzle import puzzle_path, write_puzzle_file
    if rel.startswith(SOLUTION_PREFIX):
        return solve_unit(rel, store, saved)
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
        append_row({**verdict, "crashFix": CRASH_FIX, "version": VERSION if attempts >= CRASH_LIMIT else None}, store)
        return "failed"
    if puzzle is not None and verdict.get("whole"):
        target = puzzle_path(SERIES, verdict["number"])
        if target.exists():
            verdict["skip"] = "already held"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            scan_queue.file_puzzle(write_puzzle_file, TOOL, target, puzzle, verdict)
    tries = (before or {}).get("vlmTries", 0) + 1
    # a read that asked the VLM (or left nothing for it to lay) is the page's retry; else it is due again
    asked = bool(verdict.get("vlmColumns")) or not verdict.get("blank")
    append_row({**verdict, "version": VERSION, "citeFix": CITE_FIX, "glueFix": GLUE_FIX, "namesFix": NAMES_FIX, "vlmTries": tries,**({"vlmFix": VLM_FIX} if asked else {})}, store)
    print(json.dumps(verdict))
    return "read"


#: The 60 modern back issues (2020-26) tools/tls_puzzles.py's reader could not read (no ruled square
#: grid, no clues, or unreadable cells), saved one image each, <BACKFILL>/<issue>/<issue>.png or .jpg.
#: Their dates are the print Fridays (the page's own footer, when it reads one, wins).
BACK_PREFIX = "tlsback:"
BACK_DIR = "Backfill"
BACK_VERSION = 8
BACK_REASON = "never read (Gale fetch)"
BACK_DATES = dict(
    (int(a), b) for a, b in (p.split(":") for p in (
        "1337:2020-07-31 1341:2020-09-04 1366:2021-03-05 1367:2021-03-12 1386:2021-07-23 1387:2021-07-30 "
        "1404:2021-12-03 1405:2021-12-10 1410:2022-01-21 1418:2022-03-18 1428:2022-05-27 1430:2022-06-10 "
        "1432:2022-06-24 1434:2022-07-08 1446:2022-10-07 1456:2022-12-16 1460:2023-01-20 1466:2023-03-03 "
        "1470:2023-03-31 1482:2023-06-23 1490:2023-08-18 1502:2023-11-17 1506:2023-12-15 1507:2023-12-22 "
        "1514:2024-02-16 1525:2024-05-03 1526:2024-05-10 1530:2024-06-07 1531:2024-06-14 1537:2024-07-26 "
        "1545:2024-09-27 1554:2024-11-29 1557:2024-12-20 1558:2025-01-03 1559:2025-01-10 1577:2025-05-16 "
        "1581:2025-06-13 1583:2025-06-27 1586:2025-07-18 1591:2025-08-22 1592:2025-09-05 1593:2025-09-19 "
        "1594:2025-10-03 1595:2025-10-17 1596:2025-10-31 1597:2025-11-14 1598:2025-11-28 1599:2025-12-12 "
        "1600:2026-01-02 1601:2026-01-09 1602:2026-01-23 1603:2026-02-06 1604:2026-02-20 1605:2026-03-06 "
        "1606:2026-03-20 1607:2026-04-03 1608:2026-04-17 1609:2026-05-01 1610:2026-05-15 1612:2026-06-12"
    ).split()))
MODERN_FOOTER = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)"
                           r"\s+(\d{1,2}),?\s+(\d{4})")
MODERN_BYLINE = re.compile(r"Crossword\s*\d{3,5}\b[^\n]{0,60}?\s*\n?\s*\bby\s*([A-Z][A-Za-z]+)", re.IGNORECASE)
#: The footer is the page's last line: words in this fraction of its height at the bottom.
FOOTER_BAND = 0.04
#: The byline stands in the top of the page, this fraction of its height.
BYLINE_BAND = 0.25


def back_root():
    return downloads.GALE_CROSSWORDS / "TLS" / BACK_DIR


def back_image(issue, root=None):
    """The saved image of back issue `issue`, or None: <root>/<issue>/<issue>.png or .jpg (two stats)."""
    for ext in (".png", ".jpg"):
        p = Path(root or back_root()) / str(issue) / f"{issue}{ext}"
        if p.exists():
            return p
    return None


def footer_and_setter(words, height):
    """(date or None, setter or None) the page's own words give: a Friday dated in the last line, and the
    byline of the title ("TLS Crossword 1620 by Agenor") in the top of the page."""
    import ocr_clues
    foot = [w for w in words if w[1] >= height * (1 - FOOTER_BAND)]
    day = None
    for m in MODERN_FOOTER.finditer(ocr_clues.lines_of(foot)):
        try:
            d = datetime.date(int(m.group(3)), gi.MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
        except (ValueError, KeyError):
            continue
        if d.weekday() == 4:
            day = d
    top = [w for w in words if w[3] <= height * BYLINE_BAND]
    m = MODERN_BYLINE.search(ocr_clues.lines_of(top))
    return day, (m.group(1).capitalize() if m else None)


#: The saved back-issue images are small (640-1000 wide, 1900 high): set up to the width of the-tls.com's own
#: page images (tls_puzzles.PAGE_WIDTH), the scale the lists' cuts and the grid reader are tuned for.
BACK_WIDTH = 2166


def scaled_up(img, width=BACK_WIDTH):
    """`img` resized (Lanczos) to `width` when it is narrower, else as it is."""
    from PIL import Image
    if img.width >= width:
        return img
    return img.convert("RGB").resize((width, round(img.height * width / img.width)), Image.LANCZOS)


def back_done(row):
    """Whether a ledger row is a verdict of this BACK_VERSION (a crash under CRASH_LIMIT is not)."""
    return bool(row) and row.get("version") == BACK_VERSION and not (
        row.get("failed") and (row.get("attempts", 1) < CRASH_LIMIT or row.get("crashFix") != CRASH_FIX))


def back_key(issue):
    return f"tlsback-{issue}"


def plan_back(store=STORE):
    """One unit per back issue not read at BACK_VERSION, oldest number first. No directory is globbed: the
    issues are BACK_DATES' and the ledger is the one file."""
    done = load_ledger(store)
    return [{"rel": f"{BACK_PREFIX}{n}", "rank": fa.RANKS[BACK_REASON], "reason": BACK_REASON, "needs": []}
            for n in sorted(BACK_DATES) if not back_done(done.get(back_key(n)))]


def back_url(n):
    return f"https://www.the-tls.com/regular-features/crossword-quiz/crossword-{n}"


#: Two-letter initialisms the modern clues print ("HD", "HB" pencils, "AG", "EB" White): words to the back
#: issues' vote and suspect() while a back issue is read (ocr_clues itself, and so every paper's scan key, is
#: left as it is). The vote still wants two readers to print the same letters.
BACK_INITIALISMS = frozenset({"hd", "hb", "ag", "eb", "tt", "ttt"})


#: A word the OCR reads for a name the lexicon lacks, to the print's: 1456's "Köchel" loses its K.
BACK_SPELLINGS = {"Köchel": "Kochel", "öchel": "Kochel"}
#: ...and the spelling put back on the clue the readers agreed on (the umlaut a reader sees and the others drop).
BACK_PRINTED = {"Kochel": "Köchel"}
#: Names the back issues print that the lexicon lacks (1607's Beauvoir characters), kept as printed.
BACK_NAMES = frozenset({"Dubreuilhs"})


def respelt(text):
    """`text` with each BACK_SPELLINGS word set to the print's."""
    for bad, good in BACK_SPELLINGS.items():
        text = re.sub(rf"(?<![A-Za-z]){bad}(?![A-Za-z])", good, text)
    return text


def stray_number(words):
    """`words` with the clue number a clue's own number is followed by dropped: "5 6 Yankee girls" (1581's
    5-down) for "5 Yankee girls", the 6 being the next line's own number (a line of its own further down).
    Words are (x0, y0, x1, y1, text), a reading's whole lines or its single tokens."""
    starts = [(int(m.group(1)), w[1]) for w in words if (m := re.match(r"(\d{1,2})\b", w[4]))]

    def later(n, y):
        return any(k == n and y0 > y + 5 for k, y0 in starts)

    out = []
    for i, w in enumerate(words):
        m = re.match(r"(\d{1,2}) (\d{1,2}) (?=\D)", w[4])
        if m and int(m.group(2)) == int(m.group(1)) + 1 and later(int(m.group(2)), w[1]):
            out.append((*w[:4], w[4][:m.start(2)] + w[4][m.end(2) + 1:], *w[5:]))
            continue
        prev = words[i - 1] if i else None
        if (w[4].isdigit() and prev and prev[4].isdigit() and int(w[4]) == int(prev[4]) + 1
                and abs(prev[1] - w[1]) < (w[3] - w[1]) / 2 and w[0] > prev[2] and later(int(w[4]), w[1])):
            continue
        out.append(w)
    return out


#: A clue's count closing a token or line ("5)", "... clues (4, 5)").
COUNT_END = re.compile(r"\d\s*\)[.,]?$")
#: How far under a clue's last line (in line heights) and across its column the page's strays are looked for.
STRAY_LINES = 8
STRAY_COLUMN = 500


def strays_after_count(words):
    """`words` without the specks under a clue's count in its own column and before the next clue's number:
    a column's list that ends above the page's little solution grid (1604's left column: clue 14, then the
    last puzzle's solution letters, "TTT", "MIAN") reads as the clue's own words, and no other reading has
    them. Words are (x0, y0, x1, y1, text), a reading's lines or tokens."""
    nums = [w for w in words if re.match(r"\d{1,2}\b", w[4]) and not COUNT_END.search(w[4])]
    gone = set()
    for c in words:
        if not COUNT_END.search(c[4].strip()):
            continue
        above = [n for n in nums if n is not c and n[1] <= c[1] + 5 and 0 <= c[0] - n[0] < STRAY_COLUMN + 20
                 and n[0] <= c[0] + 5]
        if not above:
            continue
        n = max(above, key=lambda w: (w[1], w[0]))
        lh = max(c[3] - c[1], 1)
        lo, hi = c[3] + 3, c[3] + STRAY_LINES * lh
        for m in nums:
            if m is not n and abs(m[0] - n[0]) < 25 and m[1] > c[3]:
                hi = min(hi, m[1] - 1)
        # only specks: no lowercase letter in them, or one or two characters (a clue's words have lowercase)
        gone.update(i for i, t in enumerate(words)
                    if lo <= t[1] < hi and n[0] - 20 <= t[0] <= n[0] + STRAY_COLUMN
                    and not re.search(r"[a-z]", t[4]) and not t[4].strip()[:1].isdigit()
                    and not re.fullmatch(r"(?i)across|down", t[4].strip()))
    return [t for i, t in enumerate(words) if i not in gone]


#: Letters short enough to be a solution grid's specks (not a clue's words) in a chain.
SPECK_LEN = 3
#: The most a clue number may stand from the word it numbers.
NUMBER_GAP = 80


def specks_before_number(words):
    """`words` without the chain of two or more short letter-only specks that run up to a clue's number on its
    own row (1604's 5-down: "C HW D All T In S I O Hn O 5 Four novels", the last puzzle's solution grid beside
    the list), which hides the number from a reading that cuts the page by rows. A chain stops at any
    token with a digit, a mark or a word over SPECK_LEN letters (the line before's own ending count)."""
    gone = set()
    for i, n in enumerate(words):
        if not re.fullmatch(r"\d{1,2}", n[4].strip()):
            continue
        after = [w for w in words if w[0] > n[2] and w[0] - n[2] < NUMBER_GAP and abs(w[1] - n[1]) < (n[3] - n[1])
                 and re.match(r"[A-Za-z]{2}", w[4])]
        if not after:
            continue
        row = sorted((j for j, w in enumerate(words) if w[2] <= n[0] + 2 and abs(w[3] - n[3]) < (n[3] - n[1])),
                     key=lambda j: -words[j][0])
        chain = []
        for j in row:
            if not re.fullmatch(rf"[A-Za-z]{{1,{SPECK_LEN}}}", words[j][4].strip()):
                break
            chain.append(j)
        if len(chain) >= 2:
            gone.update(chain)
    return [t for i, t in enumerate(words) if i not in gone]


#: How far left of its column's numbers a clue number may stand and still be that column's (pixels).
NUMBER_DRIFT = 40
#: Clue numbers at one x it takes to make a column.
NUMBER_COLUMN = 3


def aligned_numbers(words):
    """`words` with a lone clue number that stands left of its column (1604's 5-down: "5" at x492 where the
    column's other numbers stand at 516, a solution grid's specks beside it) set to the column's x, so a
    reading that cuts by the numbers' column takes it. Only a number whose next word starts as the column's
    words do is moved. Words are (x0, y0, x1, y1, text, ...) tokens."""
    lone = [w for w in words if re.fullmatch(r"\d{1,2}", w[4].strip())]
    starts = [w[0] for w in words if re.match(r"\d{1,2}\s*$|\d{1,2}\s+[A-Za-z]", w[4].strip())]
    out = []
    for w in words:
        if w in lone:
            cols = sorted({round(x) for x in starts if 0 < x - w[0] <= NUMBER_DRIFT
                           and sum(abs(y - x) <= 3 for y in starts) >= NUMBER_COLUMN})
            nxt = [v for v in words if v[0] > w[2] and v[0] - w[2] < NUMBER_GAP and abs(v[1] - w[1]) < (w[3] - w[1])
                   and re.match(r"[A-Za-z]", v[4])]
            if cols and nxt and nxt[0][0] > cols[0] + 5 and nxt[0][0] - cols[0] < NUMBER_DRIFT + 30:
                shift = cols[0] - w[0]
                w = (w[0] + shift, w[1], w[2] + shift, w[3], *w[4:])
        out.append(w)
    return out


@contextlib.contextmanager
def initialisms_known():
    import ocr_clues
    import gale_listener as gl
    old = ocr_clues.is_word
    old_vote = gl.al.vote

    def is_word(word):
        return word.lower() in BACK_INITIALISMS or word in BACK_NAMES or old(word)

    def vote(words, *args, **kwargs):
        spelt = {k: [(*t[:4], respelt(t[4]), *t[5:]) for t in stray_number(aligned_numbers(specks_before_number(strays_after_count(w))))] for k, w in words.items()}
        return old_vote(spelt, *args, **kwargs)

    ocr_clues.is_word = is_word
    gl.al.vote = vote
    BACK_STRICT[0] = True
    try:
        yield
    finally:
        BACK_STRICT[0] = False
        ocr_clues.is_word = old
        gl.al.vote = old_vote


def read_back(n, root=None, store=STORE, asker=None):
    """(verdict, puzzle or None) of back issue `n`'s image, read as a Gale page is, its number the issue's."""
    path = back_image(n, root)
    if path is None:
        return {"file": back_key(n), "failed": "no image saved", "attempts": CRASH_LIMIT}, None
    with initialisms_known():
        verdict, puzzle = read_page(path, store, asker,
                                    known=(n, datetime.date.fromisoformat(BACK_DATES[n]), back_url(n)))
    verdict["file"] = back_key(n)
    if puzzle is not None:
        for e in puzzle["entries"]:
            text = (e.get("clue") or {}).get("text")
            for bare, printed in BACK_PRINTED.items():
                if text and re.search(rf"(?<![A-Za-z]){bare}(?![A-Za-z])", text):
                    e["clue"]["text"] = text = re.sub(rf"(?<![A-Za-z]){bare}(?![A-Za-z])", printed, text)
            names = [w for w in BACK_NAMES if text and re.search(rf"(?<![A-Za-z]){w}(?![A-Za-z])", text)]
            if names:
                e["clue"]["asPrinted"] = sorted({*(e["clue"].get("asPrinted") or ()), *names})
        if verdict.get("whole") is not None:
            verdict["whole"] = bool(fa.complete(puzzle))
    return verdict, puzzle


def read_back_unit(rel, root=None, store=STORE):
    """Read one back issue (a unit's rel, "tlsback:N"), file its puzzle when whole and no file holds the
    number; the ledger row appended. Returns "read", "current" or "failed"."""
    import scan_queue
    from fetch_puzzle import puzzle_path, write_puzzle_file
    n = int(rel[len(BACK_PREFIX):] if rel.startswith(BACK_PREFIX) else rel)
    before = load_ledger(store).get(back_key(n))
    if n not in BACK_DATES or back_done(before):
        return "current"
    try:
        verdict, puzzle = read_back(n, root, store)
    except Exception as e:  # any raise: the issue stays due (back_done) until CRASH_LIMIT attempts
        attempts = (before or {}).get("attempts", 0) + 1
        verdict = {"file": back_key(n), "failed": f"crashed: {type(e).__name__}: {e}", "attempts": attempts}
        print(verdict["failed"], file=sys.stderr)
        append_row({**verdict, "crashFix": CRASH_FIX, "version": BACK_VERSION if attempts >= CRASH_LIMIT else None},
                   store)
        return "failed"
    if verdict.get("failed"):
        append_row({**verdict, "crashFix": CRASH_FIX, "version": BACK_VERSION}, store)
        return "failed"
    if puzzle is not None and verdict.get("whole"):
        target = puzzle_path(SERIES, n)
        if target.exists():
            verdict["skip"] = "already held"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            scan_queue.file_puzzle(write_puzzle_file, TOOL, target, puzzle, verdict)
    append_row({**verdict, "version": BACK_VERSION}, store)
    print(json.dumps(verdict))
    return "read"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["plan"]:
        print(len(plan()), len(plan_back()))
        return 0
    if argv[:1] == ["readback"] and len(argv) > 1:
        print(read_back_unit(argv[1]))
        return 0
    if argv[:1] == ["dryback"] and len(argv) > 1:
        # read one back issue and print the verdict: nothing written, no ledger row
        verdict, puzzle = read_back(int(argv[1]))
        print(json.dumps(verdict))
        return 0
    if argv[:1] == ["read"] and len(argv) > 1:
        print(read_unit(argv[1]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
