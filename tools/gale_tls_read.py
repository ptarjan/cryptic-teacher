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
import datetime
import json
import os
import re
import sys
from pathlib import Path
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
VERSION = 8
PREFIX = "tls:"
CITED = re.compile(r'^\W*"([^"]*)"\s*Times\s+Literary\s+Supplement\b\W*([0-3]?\d)\s+' + gi.MON + r"\s*(\d{4})",
                   re.IGNORECASE)
CITED_NUMBER = re.compile(r"t\W?l\W?s\s*cross\s?w[a-z]{0,3}d\W{0,3}(?:n[o0]\W{0,3})?(\d[\d,. ]{0,5})", re.IGNORECASE)
TITLE_WORD = re.compile(r"^\W*t\W?l\W?s\W*$", re.IGNORECASE)
#: The TLS numbers printed 1992-2014 (No 98 on 7 Feb 1992; 1,396 and up are the-tls.com's).
NUMBERS = range(90, 1400)
CITES = "cites.json"
SIZES = (15,)
CRASH_LIMIT = jr.CRASH_LIMIT


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
    return jr.page_files(saved)


def load_ledger(store=STORE):
    return jr.load_ledger(store)


def append_row(row, store=STORE):
    jr.append_row(row, store)


def read_done(row):
    """Whether a ledger row is a verdict of this VERSION (a crashed attempt under CRASH_LIMIT is not)."""
    return bool(row) and row.get("version") == VERSION and not (
        row.get("failed") and row.get("attempts", 1) < CRASH_LIMIT)


def plan(saved=SAVED, store=STORE):
    """One unit per saved page not read at VERSION (or whose last attempt crashed), newest first."""
    done = load_ledger(store)
    reason = "never read (Gale fetch)"
    todo = [p for p in page_files(saved) if not read_done(done.get(p.name))]
    todo.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"rel": PREFIX + p.name, "rank": fa.RANKS[reason], "reason": reason, "needs": []} for p in todo]


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
NUMBER_WORD = re.compile(r"^\W{0,2}\d{1,2}[.,]?$")
COLUMN_COUNTS = 3
#: Counts further apart than this many line heights are not one list's.
COUNT_GAP = 12
#: A column's heading or opening number is looked for this many line heights over its first count.
HEAD_REACH = 40


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
        bands += [(a[1], b[0]) for a, b in zip(fine, fine[1:]) if a[1] >= left - 1 and b[0] <= right + 1] or [(left, right)]
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
    k = 1
    while left + k * pitch + pitch / 2 < wide:
        x0 = left + k * pitch
        box = (int(x0), int(below), int(x0 + pitch - lh / 2), int(max(below + 10 * lh, bottom + 8 * lh)))
        # a column found already, or one lying beside the grid's height, is not a pitch column
        if not any(c[0] < box[2] and box[0] < c[2] and c[1] < box[3] and box[1] < c[3] for c in cols):
            out.append(box)
        k += 1
    return out


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
        if NUMBER_WORD.match(line[0][4]) and len(line) > 1 and re.search(r"[A-Za-z]{2}", line[1][4]):
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


def layout_block(img, words, grid, ocr=None):
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
    for k, box in enumerate(boxes):
        crop = img.crop(box).copy()
        draw = ImageDraw.Draw(crop)
        draw.rectangle((grid[0] - box[0], grid[1] - box[1], grid[2] - box[0], grid[3] - box[1]), fill="white")
        ws = ocr(crop)
        ends = [w[3] for w in ws if COUNT_WORD.search(w[4])]
        if ends and max(ends) + lh < crop.height:
            # the column's matter under its last count (prose, a notice) is not the lists'
            crop = crop.crop((0, 0, crop.width, int(max(ends) + lh / 2)))
            ws = [w for w in ws if w[3] <= crop.height]
        if k >= len(found):
            # a pitch column is kept only where its clue numbers run on from the last column kept
            nums = [n for _, _, n, _ in line_numbers(ws, lh)]
            before = [n for _, _, n, _ in line_numbers(pieces[-1][2], lh)]
            if not nums or not before or not before[-1] < nums[0] <= before[-1] + 5 or \
                    len([w for w in ws if COUNT_WORD.search(w[4])]) < 2:
                continue
        pieces.append((k, crop, ws))
    if not pieces:
        return None
    # the headings the OCR read in a column are blanked, so the ones drawn are the only ones
    for _, crop, ws in pieces:
        draw = ImageDraw.Draw(crop)
        for w in ws:
            if HEAD_WORD.match(w[4]) and len(re.sub(r"\W", "", w[4])) <= 8:
                draw.rectangle((w[0] - 4, w[1] - 4, w[2] + 4, w[3] + 4), fill="white")
    top, peak = None, 0
    for k, crop, ws in pieces:
        for y0, y1, n, _ in line_numbers(ws, lh):
            if top is None and peak and n <= 3 and n < peak - 3:
                top = (k, y0)
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
    return out, gl.image_key(out)


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


def read_page(path, store=STORE, asker=None):
    """(verdict, puzzle or None) of one saved page. `asker` stands in for the VLM (jr.vlm_mended)."""
    import gale_listener as gl
    import archive_org_jumbo as aj
    import trove_grid
    img, cite = gi.images(path)[0]
    verdict = {"file": path.name}
    cited = cite_of(cite)
    if not cited:
        verdict["refused"] = "no TLS citation on the page"
        return verdict, None
    day = cited[1]
    key = gl.image_key(img)
    n, how = cited[0], "citation"
    if n is not None:
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
        box, g, again = pick_grid(jr.extra_boxes(img, boxes), reader)
        why = again or why
    if not g:
        verdict["refused"] = f"grid unread: {why}"
        return verdict, None
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
        block = layout_block(img, words, box)
        blocks = [block] if block else []
        if blocks:
            verdict["cut"] = "layout"
    if not blocks:
        verdict["refused"] = "no TLS clue lists found on the page"
        return verdict, None
    lengths = {f"{k[0]}-{k[1]}": len(cells) for k, cells in aj.rg.light_cells(g).items()}
    read, laid = gl.times_read(blocks, lengths)
    if (laid is None or read.get("agreed", 0) * 2 < len(lengths)) and verdict.get("cut") != "layout":
        # The title's cut read little (its lists lie beside the grid, in a shape the page's headings do not
        # frame): the lists found by their own shape (layout_block), kept where they read more.
        block = layout_block(img, gl.page_words(img, key), box)
        if block:
            again, laid2 = gl.times_read([block], lengths)
            if laid2 is not None and (laid is None or again.get("agreed", 0) > read.get("agreed", 0)):
                read, laid = again, laid2
                verdict["cut"] = "layout"
    verdict.update({k: v for k, v in read.items() if k in ("agreed", "clues", "refused", "unparsed")})
    if laid is None:
        return verdict, None
    voted = dict(laid)
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
    puzzle = fa.build(n, day, g, "image", laid, None, 0, series=SERIES, name=f"TLS crossword No {n:,}",
                      url=url, printed=read.get("asPrinted"))
    verdict["whole"] = bool(fa.complete(puzzle))
    return verdict, puzzle


def read_unit(rel, saved=SAVED, store=STORE):
    """Read one saved page (a unit's rel, "tls:NAME" or NAME), file its puzzle when whole and no file holds
    the number; the ledger row appended. Returns "read", "current" or "failed"."""
    import scan_queue
    from fetch_puzzle import puzzle_path, write_puzzle_file
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
    if argv[:1] == ["read"] and len(argv) > 1:
        print(read_unit(argv[1]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
