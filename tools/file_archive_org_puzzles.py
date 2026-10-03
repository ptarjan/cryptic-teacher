#!/usr/bin/env python3
"""File the daily Times cryptics in archive.org's scans of The Times 1974-99.

    python3 tools/file_archive_org_puzzles.py               # file what is new on disk
    python3 tools/file_archive_org_puzzles.py --dry-run     # count, write nothing
    python3 tools/file_archive_org_puzzles.py --limit 40    # read at most 40 new editions
    python3 tools/file_archive_org_puzzles.py --show NewsUK1990UKEnglish/1990-01-02_63592

Reads what tools/fetch_archive_org_editions.py leaves in
~/.cache/archive_org_editions/<item>/<date>_<issue>/ (djvu.xml.gz with word
positions, leaf_NNNN.jpg of each crossword page, pages.json) for the items
NewsUK19xxUKEnglish, and files each "Times Crossword Puzzle No N" as times-N:

  - The title is found in djvu.xml's words; on a crossword page whose words
    hold none, READERS read it over and under each grid-shaped patch of ink
    (ocr_titles), the number most of them read standing. The grid is the
    largest patch of ink under it (tools/trove_grid.py reads its blocks); the
    clues are the two columns under the grid, cut where the column's text
    stops being clues ("Solution to Puzzle No", another heading, a gap).
  - The columns are read four ways: archive.org's words, RapidOCR at twice
    the size with two recognisers (multilingual PP-OCRv4 and English
    PP-OCRv5), and Tesseract, whose errors are not RapidOCR's (READERS). Each is parsed as file_trove_puzzles.py parses
    Trove's text, after tidy() undoes the print's commonest slips, and each
    list is repaired from each other reading in turn (tools/trove_clue_ocr.py).
  - A reading votes only when it has clue words and its clues lie on the
    scanned grid by number and count and read like the others' clues of
    those numbers (screened): one with every clue blank is no reading, and
    one of another part of the page is dropped whole.
  - The grid read off the scan is used when it is symmetric and a list lies
    on it whole, or when at least LOOSE_SHARE of its lights each take a
    clue by that clue's own number and count (lay_loose); the rest are
    misreads, filed blank. Else it is rebuilt from the clue list
    (tools/reconstruct_grid.py), nearest the scan when several fit, and the
    puzzle is filed only when the clues lie on the rebuilt grid.
  - Every clue's words and marks are then put to the other readings
    (agree): each word takes the lexicon spelling most readings share, a
    tie going to the one most like every reading's word; a non-word stands
    only when three read it (or two read it as a name inside the clue); a
    mark no other reading has is dropped, and a word or mark most other
    readings have where this one has none (lost, run together, or before
    the first word or after the last) is put in. The clue
    is filed blank (its count kept) when no spelling wins, when its count
    was lost, or when it holds another clue's number.
  - The answers come from the solution grid a later edition prints under
    "Solution to Puzzle No N", read by tools/trove_solution_ocr.py: a light
    only when every letter is read surely and no crossing disagrees, and the
    whole solution only when its blocks are the puzzle's.
  - Only a puzzle whose every clue has text goes into puzzles/times: one
    with a blank clue goes to --out (or nowhere without it).
  - A number already held is not written (unless this tool filed it and the
    new reading beats it on clues or answers, improves): the reading goes to
    ~/cryptic-setter-data/archiveorg-source/, where tools/cross_validate.py's
    `archiveorg` adapter votes with it. Every reading goes there, filed or not.

--paper ft does the same for the Financial Times (items
FinancialTimes19xxUKEnglish, the same uploader): "CROSSWORD" over "No. 8,650
Set by DANTE", the grid under it and two clue columns under the grid, the
previous puzzle's grid under "Solution 8,649" in the next edition. Its
numbers run on into our ftcryptic series (No 13,232 in Nov 2009), so a
puzzle files as ftcryptic-N, with the setter when the name is one our
ftcryptic files know or a dictionary word.

--paper guardian does the same for the Guardian (items
TheGuardian19xxUKEnglish: 1971, 1984-85, 1995-98): "Guardian Crossword No
20,538" over "Set by Rufus", the grid under it, the previous puzzle's grid
beside it over "CROSSWORD SOLUTION 20,537", and three clue columns, the
third under that solution grid. Its numbers are our cryptic series' (the
feed starts at 21,620), so a puzzle files as cryptic-N.

--paper telegraph does the same for the Daily Telegraph (items
TheDailyTelegraph19xxUKEnglish and SundayTelegraph1971UKEnglish): "No.
18,340 ACROSS" heads the left of two clue columns, DOWN the right, and
the grid is under them (clues_above); the previous puzzle's grid prints
under "SOLUTION No. 18,339". Its numbers run on into our telegraph series
(No 25,846 in Feb 2009), so a puzzle files as telegraph-N.

Resumable: ~/.cache/archive_org_editions/filed.jsonl records each edition's
headings and verdicts against its inputs (its files, the solutions seen,
whether the VLM read it), after each edition. Editions never read go first, then the stale by when they were read
(tools/scan_queue.py), so a capped run (--limit, --seconds) never starts over.
--workers N reads N editions at once (one's VLM wait overlaps another's OCR).
A change to this code or the VLM model makes nothing due: whoever makes it
runs the re-read once, `--reread [BEFORE]` (every edition last read before
BEFORE, an ISO time, default now; slices of one re-read share a BEFORE).
"""
import argparse
import datetime
import gzip
import hashlib
import json
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import enumeration
import file_trove_puzzles as ftp
import ocr_clues
import puzzle_integrity
import reconstruct_grid as rg
import scan_queue
import series as series_meta
import trove_clue_ocr
import trove_grid
import trove_solution_ocr
import vlm_reader as vlm
from file_penguin_puzzle import separators
from groups import entry_id
from ocr_clues import (
    READERS,
    UPSCALE,
    edits,
    engine,
    is_word,
    one_light_each,
    rank,
    read_words,
    reader_key,
    reconcile,
    similar,
    suspect,
)

SERIES = "times"
CACHE = Path(os.path.expanduser("~/.cache/archive_org_editions"))
CROPS = Path(os.path.expanduser("~/.cache/archive_org_crops"))
SOURCE = Path.home() / "cryptic-setter-data" / "archiveorg-source"
TOOL = "tools/file_archive_org_puzzles.py"
ITEM = re.compile(r"NewsUK(19\d\d)UKEnglish$")
PAGE_URL = "https://archive.org/details/{item}/page/n{leaf}/mode/1up"

NUMBER = r"(\d{2}[,.\s]?\d{3})"
#: The daily cryptic's title: not the Concise, the Jumbo or Times Two. The
#: OCR misreads its first word ("Hie"), puts a mark before "Crossword",
#: splits the number ("1 8,862") and reads its comma as any mark ("21*065");
#: read_puzzle checks the number against the date.
TITLE = re.compile(r"^\W*(?:\w{1,3}\s*)?times\W{1,3}crossword\s+(?:puzzle\s+)?n[o0]\W{0,2}\s*"
                   r"(\d\s?\d[^\w\s]?\s?\d{3})", re.I)
#: The previous puzzle's solution, printed under the clues.
SOLUTION = re.compile(r"^\W*solution\s+(?:to|of)\s+puzzle\s+no\.?\s*" + NUMBER, re.I)
#: A column line that ends the clues.
STOP = re.compile(r"^\W*(solution|crossword|concise|times\s+two|the\s+times\s+crossword"
                  r"|championship|jumbo|\w{0,10}\s+(of|to)\s+puzzle|\S{4,9}\s+t[ao]m+or+ow|publ\w+\s+by)\b", re.I)
#: The vertical gap, in pixels at the scan's 3296x4672, that ends a column.
GAP = 80


def number_of(text):
    return int(re.sub(r"\D", "", text))


# ------------------------------------------------------------ djvu.xml

def leaf_lines(xml_path, leaves):
    """{leaf: [[(x0, y0, x1, y1, text), ...] per printed line]} for the leaves
    asked for. Only those leaves' OBJECT elements are parsed: the n-th
    "<OBJECT" in the file is leaf n."""
    with gzip.open(xml_path) as f:
        data = f.read()
    out = {}
    for n, m in enumerate(OBJECT_TAG.finditer(data)):
        if n not in leaves:
            continue
        end = data.index(b"</OBJECT>", m.start()) + len(b"</OBJECT>")
        el = ET.fromstring(data[m.start():end])
        lines = []
        for line in el.iter("LINE"):
            ws = []
            for w in line.iter("WORD"):
                x0, y1, x1, y0 = (int(v) for v in w.get("coords").split(",")[:4])
                t = (w.text or "").strip()
                if t:
                    ws.append((x0, y0, x1, y1, t))
            if ws:
                lines.append(ws)
        out[n] = lines
        if len(out) == len(leaves):
            break
    return out


OBJECT_TAG = re.compile(rb"<OBJECT[\s>]")


def headings(lines, pattern):
    """[(number, (x0, y0, x1, y1))] of each line opening with `pattern`; the
    box spans the words up to the number, not junk the OCR ran on into."""
    found = []
    for ws in lines:
        text = ""
        for k, w in enumerate(ws):
            text = (text + " " + w[4]).strip()
            m = pattern.match(text)
            if m and re.search(r"\d{3}\W*$", text):
                box = (min(v[0] for v in ws[:k + 1]), min(v[1] for v in ws[:k + 1]),
                       max(v[2] for v in ws[:k + 1]), max(v[3] for v in ws[:k + 1]))
                found.append((number_of(m.group(1)), box))
                break
    return found


# ------------------------------------------------------------ the page

def ink_box(img):
    """The largest patch of ink in a PIL image, as (x0, y0, x1, y1), or None."""
    import numpy as np
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    return trove_grid.largest_component(gray < trove_grid.otsu(gray))


def grid_shaped(box):
    """Whether an ink box is a grid's size and shape at the scans' 3296px
    page width."""
    if box is None:
        return False
    gw, gh = box[2] - box[0], box[3] - box[1]
    return 500 <= gw <= 1100 and 0.85 <= gw / max(gh, 1) <= 1.18


#: How far, in pixels, a crop grows on a side its largest ink touches, and
#: how many times, so a grid wider or further from its title than the
#: first crop is read whole.
GROW, GROW_TIMES = 200, 6


def ink_in(img, crop, fixed=()):
    """The largest ink in `crop` of `img`, in page coordinates, the crop
    grown on each side (but those named in `fixed`, of "left", "top",
    "right", "bottom") that the ink touches. Ink that grows out of a grid's
    shape (a grid joined to a rule across the page) gives the last
    grid-shaped box instead."""
    crop, shaped = list(crop), None
    for _ in range(GROW_TIMES + 1):
        box = ink_box(img.crop(tuple(crop)))
        if box is None:
            return shaped
        page_box = (crop[0] + box[0], crop[1] + box[1], crop[0] + box[2], crop[1] + box[3])
        shaped = page_box if grid_shaped(page_box) else shaped
        cw, ch = crop[2] - crop[0], crop[3] - crop[1]
        grow = {"left": box[0] <= 2 and crop[0] > 0, "top": box[1] <= 2 and crop[1] > 0,
                "right": box[2] >= cw - 2 and crop[2] < img.width,
                "bottom": box[3] >= ch - 2 and crop[3] < img.height}
        grow = [side for side, on in grow.items() if on and side not in fixed]
        if not grow:
            break
        for side in grow:
            k = ("left", "top", "right", "bottom").index(side)
            crop[k] = max(0, crop[k] - GROW) if k < 2 else min((img.width, img.height)[k - 2], crop[k] + GROW)
    return page_box if grid_shaped(page_box) or shaped is None else shaped


def locate_grid(img, title):
    """(box, side) of the grid a title heads: the largest ink under it, else
    over it (the 1980s Times prints its title under the grid), else left of
    it (the FT's Monday Prize prints it right of the grid's top); `side` is
    "below", "above" or "left". (box, None) when no ink there is a grid,
    the box the ink under the title; (None, None) when there is none."""
    x0, y0, x1, y1 = title
    w = x1 - x0
    span = int(1.3 * w) + 80
    tries = (("below", (max(0, x0 - 120), y1, min(img.width, x1 + 120), min(img.height, y1 + span)), ("top",)),
             ("above", (max(0, x0 - 120), max(0, y0 - span), min(img.width, x1 + 120), y0), ("bottom",)),
             ("left", (max(0, x0 - span), max(0, y0 - 80), x0, min(img.height, y0 + span)), ()))
    first = None
    for side, crop, fixed in tries:
        box = ink_in(img, crop, fixed)
        # A grid under its title clears the title's line, and one left of it
        # ends short of the title's middle: other ink is something else's.
        clear = box is not None and (side != "below" or box[1] > crop[1] + 2) \
            and (side != "left" or box[2] < (x0 + x1) / 2)
        if clear and grid_shaped(box):
            return box, side
        first = first or box
    return first, None


def grid_box(img, title):
    """Where the grid a title heads is on the page; see locate_grid()."""
    return locate_grid(img, title)[0]


def grid_under_clues(img, title):
    """Where the grid is when the clues are printed over it: the largest ink
    in the CLUES_ABOVE_SPAN under the title, which is the left column's
    head."""
    x0, _, _, y1 = title
    crop = (max(0, x0 - 80), y1, min(img.width, x0 + CLUES_ABOVE_SPAN[0]),
            min(img.height, y1 + CLUES_ABOVE_SPAN[1]))
    box = ink_box(img.crop(crop))
    if box is None:
        return None
    return (crop[0] + box[0], crop[1] + box[1], crop[0] + box[2], crop[1] + box[3])


#: How far right of and below the title of a clues-above puzzle its grid
#: may reach (the two columns and the grid under them).
CLUES_ABOVE_SPAN = (800, 1700)
#: How far the right column of a clues-above puzzle may run past the grid
#: (its end is the gap nearest the grid's edge in that span; see gutter()).
OVERHANG = 40


def gutter(lines, grid, top, lo=None, hi=None):
    """The x between two clue columns over the grid: the middle of the
    longest run of x in [lo, hi) (by default the grid's middle half) that
    the fewest words (`lines`, every reading's) from `top` down to the grid
    cross. Near the grid's right edge, it is where the right column ends."""
    gx0, gy0, gx1, _ = grid
    lo = int(gx0 + 0.3 * (gx1 - gx0)) if lo is None else int(lo)
    hi = int(gx0 + 0.75 * (gx1 - gx0)) if hi is None else int(hi)
    cover = [0] * (hi - lo)
    for ws in lines:
        for w in ws:
            if top <= w[1] < gy0:
                for x in range(max(lo, w[0]), min(hi, w[2])):
                    cover[x - lo] += 1
    least = min(cover)
    best, run = (0, lo), None
    for k, c in enumerate(cover + [least + 1]):
        if c == least:
            run = k if run is None else run
        elif run is not None:
            best = max(best, (k - run, lo + (run + k) // 2))
            run = None
    return best[1]


def windows(grid, third=None, margin=40, above=None, left=None):
    """[(x0, x1, right edge, top)] of each clue column: a word whose left edge
    is in [x0, x1), right edge at most the right edge and top at least the
    top is in it. The two columns under the grid, and with `third`, (width,
    top), a column that wide right of the grid from `top` down. The left
    column starts `margin` left of the grid (the Times outdents its numbers).
    With `above`, (top, gutter, right), the two columns are over the grid
    instead, from `top` down, split at the gutter, the right one ending at
    `right` (it may overhang the grid). With `left`, (x0, gutter), they are
    left of the grid from x0, split at the gutter, from LEFT_RISE over the
    grid's top down."""
    gx0, gy0, gx1, gy1 = grid
    if left:
        x0, split = left
        return [(x0, split, split, gy0 - LEFT_RISE), (split, gx0 - 5, gx0 - 5, gy0 - LEFT_RISE)]
    if above:
        top, split, right = above
        return [(gx0 - margin, split, split, top), (split, right, right, top)]
    mid = gx0 + (gx1 - gx0) / 2 - 10
    out = [(gx0 - margin, mid, gx1 + 15, gy1 - 5), (mid, gx1 + 15, gx1 + 15, gy1 - 5)]
    if third:
        out.append((gx1 + 15, gx1 + 15 + third[0], gx1 + 15 + third[0], third[1]))
    return out


def columns(lines, grid, third=None, margin=40, above=None, left=None):
    """The clue columns under the grid (and with `third`, right of it; with
    `above`, over it; with `left`, left of it; see windows()): [[(y0, y1, x0,
    x1, text) per line] per column, left to right], each cut where the clues
    stop."""
    gx0, gy0, gx1, gy1 = grid
    bottom = gy0 - 3 if above else left_bottom(grid) if left else gy1 + 1.8 * (gx1 - gx0)
    wins = windows(grid, third, margin, above, left)
    cols = [[] for _ in wins]
    for ws in lines:
        for side, (x0, x1, right, top) in enumerate(wins):
            part = [w for w in ws if x0 <= w[0] < x1 and w[2] <= right and top <= w[1] <= bottom]
            if part:
                cols[side].append((min(w[1] for w in part), max(w[3] for w in part),
                                   min(w[0] for w in part), max(w[2] for w in part),
                                   " ".join(w[4] for w in part)))
    out = []
    for col in cols:
        col = merge_rows(col)
        kept, last = [], None
        for line in col:
            if kept and (STOP.match(line[4]) or line[0] - last > GAP):
                break
            if not re.search(r"[A-Za-z0-9]", line[4]):
                continue  # specks read as marks: no clue text
            heading = numbered_heading(line[4])
            if heading:
                line = line[:4] + (heading,)
            if not kept and not re.match(r"\W*(across|down)\b", line[4], re.I) and last is None:
                # The column's first line is ACROSS, DOWN or a clue: a stray
                # word the grid's numbers left is not.
                if not re.match(r"\W*\d", line[4]):
                    continue
            kept.append(line)
            last = line[1]
        out.append(kept)
    return out



#: How far over the grid's top, and under its foot as a share of its height,
#: clue columns left of the grid may run.
LEFT_RISE, LEFT_DROP = 80, 0.3


def left_bottom(grid):
    return grid[3] + LEFT_DROP * (grid[3] - grid[1])


def left_columns(lines, grid):
    """(x0, gutter) of the two clue columns left of the grid (the FT's
    Monday Prize): from a grid's width left of it, split where the fewest
    words (`lines`, every reading's) cross."""
    gx0, gy0, gx1, _ = grid
    x0 = max(0, gx0 - (gx1 - gx0) - 60)
    floor = left_bottom(grid)
    lo, hi = x0 + 0.3 * (gx0 - x0), x0 + 0.7 * (gx0 - x0)
    return x0, gutter(lines, (lo, floor, hi, floor), gy0 - LEFT_RISE, lo, hi)


def rapid_lines(img, grid, which, cache_path, third=None, margin=40, above=None, left=None):
    """One recogniser's reading of the page under the grid (RapidOCR's, or
    Tesseract's for a TESS_MODELS reader), as djvu-style lines of one word each, in page
    coordinates; cached as JSON with the crop it read, so a reading of another
    crop is read again (a bare list is a cache from before crops were kept)."""
    gx0, gy0, gx1, gy1 = grid
    gw = gx1 - gx0
    box = (max(0, gx0 - margin), gy1, min(img.width, gx1 + 30), min(img.height, int(gy1 + 1.8 * gw)))
    if third:
        box = (box[0], min(gy1, third[1]), min(img.width, gx1 + 15 + third[0]), box[3])
    if above is not None:
        box = (max(0, gx0 - margin), max(0, int(above)), min(img.width, gx1 + OVERHANG), gy0)
    if left:
        box = (max(0, gx0 - gw - 60), max(0, gy0 - LEFT_RISE), gx0, min(img.height, int(left_bottom(grid))))
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if isinstance(cached, list):
            return [[tuple(w)] for w in cached]
        if tuple(cached["box"]) == box:
            return [[tuple(w)] for w in cached["words"]]
    words = [(x0 + box[0], y0 + box[1], x1 + box[0], y1 + box[1], t)
             for x0, y0, x1, y1, t in read_words(img.crop(box), which)]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"box": box, "words": words}))
    return [[w] for w in words]


def tidy(text):
    """A column text with OCR's commonest slips in the print's shape undone:
    a brace or square bracket read for a round one, a clue number run into
    its first word, and a number lost altogether (a line starting a word
    straight after a line that ended on a count) marked "?", which
    file_trove_puzzles.match places by the grid alone."""
    out, prev = [], ""
    for line in text.splitlines():
        line = line.translate(BRACKETS).strip()
        heading = heading_of(line) or numbered_heading(line)
        if heading:
            line = heading
        elif out and re.match(r"(?:across|down)\b", line):
            # A lower-case "down (8)." carries on the line before it: no heading.
            out[-1] += " " + line
            prev = out[-1]
            continue
        if re.search(r"\(\s*[\dSIl,.\- ]{1,9}\)\W{0,2}$", prev) or heading_of(prev) or not out:
            # A speck or star before a clue's number: ". 1 Miss", ":1 An", "*1 Land".
            line = re.sub(r"^[.,:;*'_•·]{1,2}\s?(?=[\dIl]\d?\s)", "", line)
            # A clue's number 1 read as I or l: "I7 More", "IA fruitful".
            line = re.sub(r"^[Il](?=\d\b|\d\s|[A-Z]\s)", "1", line)
        line = re.sub(r"^(\d{1,2})(?=[A-Z][a-z]|[A-Z]\s)", r"\1 ", line)
        # "15 Adanger out east": a clue's opening "A" run into the next word,
        # unless the whole is a misspelling of a commoner word ("Arived").
        glued = re.match(r"^(\d{1,2}(?:,\s?\d{1,2})*\s+)A([a-z]{3,})\b", line)
        if glued and is_word(glued.group(2)) and not is_word("a" + glued.group(2)) and not any(
                rank(e) and rank(e) < rank(glued.group(2)) for e in edits("a" + glued.group(2))
                if e != glued.group(2)):
            line = f"{glued.group(1)}A {line[glued.end(1) + 1:]}"
        line = re.sub(r"(?<=[a-z])\s?\(?(\d{1,2}(?:[,.\-]\d{1,2})*)[)jJ]$", r" (\1)", line)
        # Specks after a clue's count ("(8)'", "(5).·") end nothing.
        line = re.sub(r"(\(\s*[\dSIl,.\- ]{1,9}\))[^\w(]{1,3}$", r"\1", line)
        if (re.search(r"\(\s*[\dSIl,.\- ]{1,9}\)\W{0,2}$", prev)
                or re.fullmatch(r"\W*(across|down)\W*", prev, re.I)) and re.match(r"[A-Z][a-z]", line):
            line = "? " + line
        out.append(line)
        prev = line
    # A count left open at a list's end ("(5r", "(5-" before DOWN): a speck
    # took its bracket, as nothing follows to carry it on.
    for k, line in enumerate(out):
        if k + 1 == len(out) or heading_of(out[k + 1]):
            out[k] = re.sub(r"\((\d{1,2})[^\d)\s]?$", r"(\1)", line)
    return "\n".join(out)


#: A list heading led by the puzzle's number: the Telegraph's "No. 18,340
#: ACROSS", read "No. T8,338ACROSS", "Ko. 18.339 ACROSS", "No. 18-340ACROM",
#: "No. 18.339ACR0SS".
NUMBERED_HEADING = re.compile(r"^\W*[NK][o0]\W{0,3}\s*[\dTIl]\d?[,.\-\s]?\d{3}\s*([A-Za-z0']{3,8})\W*$")


def numbered_heading(line):
    """"ACROSS" or "DOWN" for a heading led by the puzzle's number; else None."""
    m = NUMBERED_HEADING.match(line)
    return heading_of(m.group(1)) if m else None


def heading_of(line):
    """"ACROSS" or "DOWN" for a line that is the list's heading alone, read
    however badly ("DOW'N", "DOIN", "AROSS"); else None."""
    letters = re.sub(r"[^A-Za-z]", "", line)
    if len(line) <= 9 and letters in ("Across", "Down"):
        # The Guardian's, in title case: read whole, never guessed at.
        return letters.upper()
    if len(line) > 9 or not 3 <= len(letters) <= 7 or not letters.isupper():
        return None
    for word in ("ACROSS", "DOWN"):
        if SequenceMatcher(None, letters, word).ratio() >= 0.7:
            return word
    return None


BRACKETS = str.maketrans({"{": "(", "[": "(", "<": "(", "}": ")", "]": ")"})


def parse(text):
    """({"across": [...], "down": [...]}, None) or (None, why) for a column text."""
    secs = ftp.sections(tidy(text))
    if secs is None:
        return None, "no ACROSS and DOWN lists under the grid"
    parsed = {}
    for direction, t in secs.items():
        parsed[direction], why = ftp.clues(t)
        if why:
            return None, f"{direction} clues do not parse: {why}"
    return parsed, None


def merge_rows(col):
    """One line per printed row: pieces whose middles fall inside each other's
    height (a clue number read apart from its words) joined left to right."""
    rows = []
    for piece in sorted(col, key=lambda l: (l[0] + l[1]) / 2):
        mid = (piece[0] + piece[1]) / 2
        if rows and rows[-1][0][0] <= mid <= rows[-1][0][1]:
            over = [p for p in rows[-1] if min(p[3], piece[3]) - max(p[2], piece[2])
                    > 0.5 * (piece[3] - piece[2])]
            if not over:
                rows[-1].append(piece)
            elif (mid > max(p[1] for p in rows[-1]) - 0.5 * (piece[1] - piece[0])
                  and not any(similar(p[4], piece[4]) > 0.5 or piece[4] in p[4] for p in over)):
                # Under the row, not beside it: a short last line ("turn
                # (6)") whose box the line above overhangs.
                rows.append([piece])
            # Else the OCR's second copy of words it already has: dropped.
        else:
            rows.append([piece])
    out = []
    for r in rows:
        r.sort(key=lambda l: l[2])
        out.append((min(l[0] for l in r), max(l[1] for l in r), r[0][2], max(l[3] for l in r),
                    " ".join(l[4] for l in r)))
    return out


def column_text(cols):
    return "\n".join(line[4] for col in cols for line in col)


#: The share of the scanned grid's lights that clues must lie on, each by its
#: own number and count, for the grid to stand without the rest.
LOOSE_SHARE = 0.8


#: Two clues read as one: a count, or a clue's number and capital, inside the
#: text. Never laid by position, where the count that ends it proves nothing.
RUN_ON = re.compile(r"\(\s*\d|[?!.,;)]\s+\d{1,2}\s+[A-Z]")


def lay_loose(parsed, grid, taken=None):
    """({light: (text, enumeration, group)}, [clues not laid]): each clue laid
    alone on the light its number names in its list's direction, when its
    number reads one way that names a light not yet taken and one of its
    count readings fills that light; a linked clue on the lights its numbers
    name, when one count fills them all. "See" clues are not laid.
    With `taken` (the lights every reading laid by number), clues whose
    numbers were lost or misread also take the lights their laid neighbours
    leave between them, one each in order: the lights outside `taken`, or
    failing that every light this reading left free, when there are as many
    lights as clues and each count fills its light."""
    lights = rg.light_cells(grid)
    out, bad = {}, []
    for direction in ("across", "down"):
        at = {}  # the clue's place in its list -> the light number it took
        for k, clue in enumerate(parsed[direction]):
            if len(clue["tokens"]) > 1 and clue["see"] is None:
                # A linked clue ("9 & 12"): each number names one free light
                # in the list's direction, and one count fills them all.
                # The tails read "See 9", as the paper's own files have it.
                names = [[n for n in tok if (n, direction) in lights and f"{n}-{direction}" not in out]
                         for tok in clue["tokens"]]
                ids = [f"{ns[0]}-{direction}" for ns in names if len(ns) == 1]
                cells = sum(len(lights[(int(i.split("-")[0]), direction)]) for i in ids)
                fits = [e for e in clue["enums"] if ftp.count(e) == cells]
                if len(ids) == len(names) == len(set(ids)) and len(fits) == 1:
                    out[ids[0]] = (clue["text"], fits[0], ids)
                    for tail in ids[1:]:
                        out[tail] = (f"See {ids[0].split('-')[0]}", None, None)
                    at[k] = int(ids[0].split("-")[0])
                else:
                    bad.append(f"{direction} {[sorted(t) for t in clue['tokens']]}")
                continue
            names = [n for n in clue["tokens"][0]
                     if (n, direction) in lights and f"{n}-{direction}" not in out]
            if len(clue["tokens"]) != 1 or clue["see"] is not None or len(names) != 1:
                bad.append(f"{direction} {sorted(clue['tokens'][0])}")
                continue
            lid = f"{names[0]}-{direction}"
            fits = [e for e in clue["enums"] if ftp.count(e) == len(lights[(names[0], direction)])]
            if len(fits) != 1:
                bad.append(lid)
                continue
            out[lid] = (clue["text"], fits[0], None)
            at[k] = names[0]
        # Clues whose numbers were lost or misread ("Made to smile ... (6)"
        # or "74 Made ..." between 1 and 9, or after the list's last laid
        # clue) take the lights their laid neighbours in the list leave free
        # between them, in order, when there are as many of each and every
        # count fills its light.
        clues = parsed[direction]
        if taken is None:
            continue
        laid_at = sorted(at)
        for lo_k, hi_k in zip([-1] + laid_at, laid_at + [len(clues)]):
            between = list(range(lo_k + 1, hi_k))
            if not between or any(len(clues[j]["tokens"]) != 1 or clues[j]["see"] is not None
                                  or RUN_ON.search(clues[j]["text"]) for j in between):
                continue
            lo = at[lo_k] if lo_k >= 0 else 0
            hi = at[hi_k] if hi_k < len(clues) else math.inf
            # The lights no reading laid by number, else every light this
            # reading left free: one clue a light either way.
            free = [sorted(n for (n, d) in lights if d == direction and lo < n < hi
                           and f"{n}-{d}" not in out and (f"{n}-{d}" not in taken or every))
                    for every in (False, True)]
            free = next((f for f in free if len(f) == len(between)), None)
            if free is None:
                continue
            fits = [[e for e in clues[j]["enums"] if ftp.count(e) == len(lights[(n, direction)])]
                    for j, n in zip(between, free)]
            if all(len(f) == 1 for f in fits):
                for j, n, f in zip(between, free, fits):
                    out[f"{n}-{direction}"] = (clues[j]["text"], f[0], None)
    return out, bad


# ------------------------------------------------------------ the puzzle

def build(number, day, grid, how, laid, item, leaf, series=SERIES, name=None):
    lights = rg.light_cells(grid)
    by_id, entries = {}, []
    for (n, d), cells in lights.items():
        e = {"number": n, "direction": d, "position": {"x": cells[0][1], "y": cells[0][0]},
             "length": len(cells)}
        entries.append(e)
        by_id[entry_id(e)] = e
    seps, groups = {}, {}
    for lid, (text, enum, group) in list(laid.items()):
        if enum:
            try:
                seps.update(separators(group or [lid], by_id, enum))
            except SystemExit:
                laid[lid] = (text, None, None)
                continue
            if group:
                groups[lid] = group
    # A linked light with no clue of its own ("1,4 Ancient ..." prints none
    # for 4) reads "See 1", as the paper's own files have it.
    laid = dict(laid)
    for lid, group in groups.items():
        for tail in group[1:]:
            if not (laid.get(tail) or ("",))[0].strip():
                laid[tail] = (f"See {lid.split('-')[0]}", None, None)
    from fetch_puzzle import source_clue
    pid = series_meta.puzzle_id(series, number)
    for e in entries:
        lid = entry_id(e)
        text, enum, _ = laid.get(lid, ("", None, None))
        text = source_clue(pid, lid, text)
        line = f"{text} ({enum})" if enum else text
        e["clue"] = enumeration.clue(line, separators=seps.get(lid), missing=not text.strip())
        if lid in groups:
            e["group"] = groups[lid]
        e["solution"] = None
    return {
        "id": pid,
        "number": number,
        "series": series,
        "name": name or f"Times cryptic crossword No {number:,}",
        "date": day.isoformat(),
        "dimensions": {"cols": len(grid[0]), "rows": len(grid)},
        "source": {"url": PAGE_URL.format(item=item, leaf=leaf),
                   "gridOrigin": "published" if how == "image" else "reconstructed"},
        "entries": entries,
    }


# ------------------------------------------------------------ an edition

def edition_dirs(cache=CACHE, paper=None):
    """Every cached edition of `paper` (the Times by default), the years taken in turn (each year's first
    edition, then each year's second, ...), so a capped run reaches every
    decade the fetch has."""
    if not cache.exists():
        return []
    years = [sorted(d for d in item.iterdir() if (d / "pages.json").exists())
             for item in sorted(cache.iterdir()) if (paper or TIMES).item.match(item.name)]
    out = []
    for k in range(max(map(len, years), default=0)):
        out += [y[k] for y in years if k < len(y)]
    return out


def scan(d):
    """{"puzzles": [...], "solutions": [...]} for one edition directory: each
    heading's number, leaf and box."""
    pages = json.loads((d / "pages.json").read_text())
    leaves = {p["leaf"] for p in pages.get("crossword_pages", ())
              if (d / f"leaf_{p['leaf']:04d}.jpg").exists()}
    found = {"date": pages["date"], "item": pages["item"], "puzzles": [], "solutions": []}
    if not leaves or not (d / "djvu.xml.gz").exists():
        return found
    paper = paper_of(d)
    text = leaf_lines(d / "djvu.xml.gz", leaves)
    for leaf in sorted(leaves):
        titles, sols = paper.headings(text.get(leaf, []))
        titles = [(n, box, setter, None) for n, box, setter in titles] or \
            ocr_titles(page(d, leaf), paper, datetime.date.fromisoformat(pages["date"]), f"{d.name}_{leaf}")
        for n, box, setter, readers in titles:
            found["puzzles"].append({"number": n, "leaf": leaf, "box": box,
                                     **({"setterRead": setter} if setter else {}),
                                     **({"titleReadBy": readers} if readers else {})})
        for n, box in sols:
            found["solutions"].append({"number": n, "leaf": leaf, "box": box})
    return found


#: The least share of its box a grid's ink fills: a frame round a panel
#: (3%) is not a grid; grids fill 35-45%.
GRID_FILL = 0.2
#: How far over and under a grid its title is looked for when archive.org's
#: text has none: the 1995 Times prints it 250px over the grid.
TITLE_REACH = 300


def grids_on(img, step=2):
    """[box] of each grid-shaped patch of ink on a page (grid_shaped, at
    least GRID_FILL of its box inked), found on a 1/step subsample."""
    import cv2
    import numpy as np
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    ink = (gray < trove_grid.otsu(gray))[::step, ::step].astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=4)
    out = []
    for x, y, w, h, area in stats[1:].tolist():
        box = (x * step, y * step, (x + w) * step, (y + h) * step)
        if grid_shaped(box) and area >= GRID_FILL * w * h:
            out.append(box)
    return out


def title_bands(img, grid):
    """The crops over and under a grid that its title is read in: TITLE_REACH
    deep, half the grid's width wider each side (the Guardian's title runs
    left of its grid)."""
    x0, y0, x1, y1 = grid
    xa, xb = max(0, x0 - (x1 - x0) // 2), min(img.width, x1 + (x1 - x0) // 2)
    return ((xa, max(0, y0 - TITLE_REACH), xb, y0), (xa, y1, xb, min(img.height, y1 + TITLE_REACH)))


def printed_lines(words):
    """djvu-style lines of OCR words, (x0, y0, x1, y1, text) each: words
    each of whose middles lies within the other's height share a row (a
    column rule read as one tall word joins none), left to right, a row
    split where a gap wider than three heights parts two columns."""
    def mid(w):
        return (w[1] + w[3]) / 2
    rows = []
    for w in sorted(words, key=mid):
        row = next((r for r in rows if r[0][1] <= mid(w) <= r[0][3] and w[1] <= mid(r[0]) <= w[3]), None)
        if row:
            row.append(w)
        else:
            rows.append([w])
    lines = []
    for row in rows:
        row.sort()
        line = [row[0]]
        for w in row[1:]:
            if w[0] - line[-1][2] > 3 * (w[3] - w[1]):
                lines.append(line)
                line = []
            line.append(w)
        lines.append(line)
    return lines


def band_words(img, band, which, cache_path):
    """Reader `which`'s words in a band of the page, in page coordinates;
    cached as JSON with the band it read."""
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if tuple(cached["box"]) == tuple(band):
            return [tuple(w) for w in cached["words"]]
    words = [(x0 + band[0], y0 + band[1], x1 + band[0], y1 + band[1], t)
             for x0, y0, x1, y1, t in read_words(img.crop(band), which)]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"box": list(band), "words": words}))
    return words


def ocr_titles(img, paper, day, key):
    """[(number, box, setter, readers)] of the titles our own readers
    (READERS) find over or under each grid on a page whose archive.org text
    has none: per band, the number most readers read (a tie to the one
    nearest the date's), with the box and setter of the first reader that
    read it. read_puzzle still holds the number to the date."""
    found = []
    for g in grids_on(img):
        for band in title_bands(img, g):
            reads = {}
            for which in READERS:
                path = CROPS / "titles" / f"{key}_{'_'.join(map(str, band))}.{reader_key(which)}.json"
                titles = paper.headings(printed_lines(band_words(img, band, which, path)))[0]
                if titles:
                    reads[which] = titles[0]
            if reads:
                votes = {}
                for which, (n, _, _) in reads.items():
                    votes.setdefault(n, []).append(which)
                n = min(votes, key=lambda n: (-len(votes[n]), abs(n - paper.expected(day))))
                _, box, setter = reads[votes[n][0]]
                found.append((n, box, setter, votes[n]))
                break
    return found


def page(d, leaf):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    return Image.open(d / f"leaf_{leaf:04d}.jpg")


#: A dated Times cryptic either side of the 1978-79 shutdown, and the run
#: of six a week (none on Sunday) from it.
ANCHORS = ((datetime.date(1974, 5, 1), 13676), (datetime.date(1990, 1, 2), 18180))
RESUMED = datetime.date(1979, 11, 13)
#: How far a number may stray from that run before the edition's date is
#: distrusted.
NUMBER_SLACK = 300


def expected_number(day):
    start, number = ANCHORS[day >= RESUMED]
    return number + round((day - start).days * 6 / 7)


#: Dated FT cryptics read off the scans and our own first ftcryptic file:
#: the number between two is interpolated, outside them run on six a week.
FT_ANCHORS = ((datetime.date(1975, 5, 1), 2766), (datetime.date(1995, 1, 3), 8650),
              (datetime.date(2009, 11, 12), 13232))


def anchored(pts, day):
    """The number a date implies from dated (day, number) anchors in order:
    interpolated between two, run on six a week outside them."""
    if day <= pts[0][0] or day >= pts[-1][0]:
        start, number = pts[0] if day <= pts[0][0] else pts[-1]
        return number + round((day - start).days * 6 / 7)
    (d0, n0), (d1, n1) = next((a, b) for a, b in zip(pts, pts[1:]) if day <= b[0])
    return n0 + round((n1 - n0) * (day - d0).days / (d1 - d0).days)


def ft_expected_number(day):
    return anchored(FT_ANCHORS, day)


#: Dated Guardian cryptics: our own 1970, 1982 and first 1999 files, and
#: 20,538 read off the 2 January 1996 scan.
GUARDIAN_ANCHORS = ((datetime.date(1970, 8, 25), 12575), (datetime.date(1982, 1, 27), 16176),
                    (datetime.date(1996, 1, 2), 20538), (datetime.date(1999, 6, 24), 21620))


def guardian_expected_number(day):
    return anchored(GUARDIAN_ANCHORS, day)


#: The FT's title: "CROSSWORD" (or "MONDAY PRIZE CROSSWORD") over
#: "No. 8,650 Set by DANTE" in the 1990s, "CROSSWORD PUZZLE No. 2,766" on
#: one line in the 1970s.
FT_TITLE = re.compile(r"^\W*(?:[a-z.]+\s+){0,2}cross\s?word(?:\s+puzzle)?\b\W*(.*)$", re.IGNORECASE)
FT_NUMBER = re.compile(r"^\W*no\W{0,2}\s*(\d[,.]?\d{3})\b(.*)$", re.IGNORECASE)
FT_SETTER = re.compile(r"set\s+by\s+([A-Za-z][A-Za-z'-]+)", re.IGNORECASE)
#: The previous puzzle's solution grid: "Solution 8,650", or in the 1970s
#: "SOLUTION TO PUZZLE" over "No. 2,765".
FT_SOLUTION = re.compile(r"^\W*solution\s+(?:(?:to|of)\s+)?(?:puzzle\b)?\W*(.*)$", re.IGNORECASE)
#: The width of the grid and of the solution grid under an FT heading,
#: which is narrower than either: the box grid_box and read_solution crop
#: around is this wide, centred on the heading.
FT_GRID_SPAN = 960
FT_SOLUTION_SPAN = 360


def box_of(ws):
    return (min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws), max(w[3] for w in ws))


def centred(box, span):
    cx = (box[0] + box[2]) // 2
    return (cx - span // 2, box[1], cx + span // 2, box[3])


_SETTERS = {}


def setters(series):
    """The setters our files of `series` name."""
    if series not in _SETTERS:
        _SETTERS[series] = {json.loads(p.read_text()).get("setter")
                            for p in (ROOT / "puzzles" / series).glob("*/*.json")}
    return _SETTERS[series]


def ft_headings(lines):
    """([(number, box, setter)], [(number, box)]): each FT crossword title,
    its number on its own line or the line just under it, and each
    "Solution N" heading; boxes widened to the grid's span."""
    def numbered(ws, rest):
        """(the "No. N" match, the line it is on): on this line, else
        on a line just under it."""
        num = FT_NUMBER.match(rest)
        if num or re.search(r"\d", rest):
            return num, ws
        box = box_of(ws)
        cx = (box[0] + box[2]) / 2
        for v in lines:
            if v is not ws and box[3] - 5 <= box_of(v)[1] <= box[3] + 80 \
                    and box_of(v)[0] - 150 <= cx <= box_of(v)[2] + 150:
                num = FT_NUMBER.match(" ".join(w[4] for w in v))
                if num:
                    return num, v
        return None, ws

    puzzles, solutions = [], []
    for ws in lines:
        text = " ".join(w[4] for w in ws)
        m = FT_SOLUTION.match(text)
        if m:
            rest = m.group(1)
            num, under = numbered(ws, rest if re.match(r"\W*no\b", rest, re.IGNORECASE) else "no " + rest)
            if num and not num.group(2).strip(" .'"):
                solutions.append((number_of(num.group(1)), centred(box_of(ws + under), FT_SOLUTION_SPAN)))
            continue
        m = FT_TITLE.match(text)
        if not m:
            continue
        num, under = numbered(ws, m.group(1))
        if not num:
            continue
        box, whole = box_of(ws), box_of(ws + under)
        setter = FT_SETTER.search(num.group(2))
        puzzles.append((number_of(num.group(1)), centred((box[0], whole[1], box[2], whole[3]), FT_GRID_SPAN),
                        setter.group(1).title() if setter else None))
    return puzzles, solutions


#: The Guardian's title, "Guardian Crossword No 20,538" over "Set by
#: Rufus" ("CROSSWORD 17,101" in the 1980s), and the previous puzzle's solution grid, over its label
#: "CROSSWORD SOLUTION 20,537". archive.org reads a comma as "^" at times.
G_NUMBER = r"(\d{2}[,.\s^']?\d{3})"
GUARDIAN_TITLE = re.compile(r"^\W*(?:the\s+)?(?:guardian\s+)?(?:prize\s+)?crossword\s+(?:puzzle\s+)?(?:no\W{0,2}\s*)?"
                            + G_NUMBER + r"\b(.*)$", re.IGNORECASE)
GUARDIAN_SOLUTION = re.compile(r"^\W*(?:guardian\s+)?(?:prize\s+)?crossword\s+\w?o[l1]ut[il1]on\b\W*(.*)$",
                               re.IGNORECASE)
#: The Guardian's third clue column, right of the grid under the solution
#: grid: this wide, from its left edge.
GUARDIAN_THIRD = 360


def guardian_headings(lines):
    """([(number, box, setter)], [(number, box)]): each Guardian crossword
    title with the setter on it or the line under it, and each solution
    label (the solution grid is above it). A label whose number is misread
    ("20^39") is the previous puzzle's, beside the page's one title."""
    puzzles, solutions = [], []
    for ws in lines:
        text = " ".join(w[4] for w in ws)
        m = GUARDIAN_SOLUTION.match(text)
        if m:
            num = re.fullmatch(G_NUMBER + r"\W*", m.group(1))
            solutions.append((number_of(num.group(1)) if num else None, box_of(ws)))
            continue
        m = GUARDIAN_TITLE.match(text)
        if not m:
            continue
        box = box_of(ws)
        setter = FT_SETTER.search(m.group(2))
        if not setter:
            for v in lines:
                b = box_of(v)
                if v is not ws and box[3] - 5 <= b[1] <= box[3] + 80 and abs(b[0] - box[0]) <= 150:
                    setter = FT_SETTER.search(" ".join(w[4] for w in v)) or setter
        puzzles.append((number_of(m.group(1)), box, setter.group(1).title() if setter else None))
    solutions = [(n if n is not None else puzzles[0][0] - 1, box) for n, box in solutions
                 if n is not None or len(puzzles) == 1]
    return puzzles, solutions


#: Dated Telegraph cryptics: 18,340 read off the 4 January 1985 scan, and
#: our first telegraph file.
TELEGRAPH_ANCHORS = ((datetime.date(1985, 1, 4), 18340), (datetime.date(2009, 2, 7), 25846))


def telegraph_expected_number(day):
    return anchored(TELEGRAPH_ANCHORS, day)


#: The previous Telegraph puzzle's solution grid, under "SOLUTION No.
#: 18,339", which is narrower than the grid: the box read_solution crops
#: around is this wide, centred on the heading.
TELEGRAPH_SOLUTION = re.compile(r"^\W*s\w?[l1]ut[il1]on\s+n[o0]\W{0,3}\s*([\dTIl]\d?[,.\-\s]?\d{3})\W*$",
                                re.IGNORECASE)
TELEGRAPH_SOLUTION_SPAN = 380


def digits(text):
    """A number as OCR reads it, its leading 1 read as T, I or l mended."""
    return number_of(re.sub(r"^[TIl]", "1", text.strip()))


def telegraph_headings(lines):
    """([(number, box, None)], [(number, box)]): each Telegraph cryptic's
    title, "No. 18,340 ACROSS" over the left clue column, and each
    "SOLUTION No. 18,339" heading, its box widened to the solution grid's."""
    puzzles, solutions = [], []
    for ws in lines:
        text = " ".join(w[4] for w in ws)
        m = TELEGRAPH_SOLUTION.match(text)
        if m:
            solutions.append((digits(m.group(1)), centred(box_of(ws), TELEGRAPH_SOLUTION_SPAN)))
            continue
        m = NUMBERED_HEADING.match(text)
        if m and heading_of(m.group(1)) == "ACROSS":
            num = re.search(r"[\dTIl]\d?[,.\-\s]?\d{3}", text)
            puzzles.append((digits(num.group(0)), box_of(ws), None))
    return puzzles, solutions


class Paper:
    """One newspaper's run of archive.org items: where its editions are, how
    its titles and solution headings read, the number its date implies, and
    the series its puzzles file as."""

    def __init__(self, key, series, item, name, expected, third=0, solution_above=False, margin=40,
                 clues_above=False):
        self.key, self.series, self.item, self.name, self.expected = key, series, item, name, expected
        #: The width of a clue column right of the grid (0: none), whether
        #: the solution grid is printed above its heading, how far left
        #: of the grid the clue numbers may start, and whether the clues are
        #: printed over the grid, the title heading the left column.
        self.third, self.solution_above, self.margin = third, solution_above, margin
        self.clues_above = clues_above

    def headings(self, lines):
        if self.key == "ft":
            return ft_headings(lines)
        if self.key == "guardian":
            return guardian_headings(lines)
        if self.key == "telegraph":
            return telegraph_headings(lines)
        return ([(n, box, None) for n, box in headings(lines, TITLE)], headings(lines, SOLUTION))


TIMES = Paper("times", SERIES, ITEM, "Times cryptic crossword No {:,}", expected_number)
FT = Paper("ft", "ftcryptic", re.compile(r"FinancialTimes(19\d\d)UKEnglish$"),
           "Financial Times cryptic crossword No {:,}", ft_expected_number)
GUARDIAN = Paper("guardian", "cryptic", re.compile(r"TheGuardian(19\d\d)UKEnglish$"),
                 "Cryptic crossword No {:,}", guardian_expected_number, third=GUARDIAN_THIRD, solution_above=True,
                 margin=15)
TELEGRAPH = Paper("telegraph", "telegraph", re.compile(r"(?:TheDaily|Sunday)Telegraph(19\d\d)UKEnglish$"),
                  "Telegraph cryptic crossword No {:,}", telegraph_expected_number, margin=15, clues_above=True)
PAPERS = {p.key: p for p in (TIMES, FT, GUARDIAN, TELEGRAPH)}


def paper_of(d):
    """The Paper an edition directory's item belongs to."""
    return next((p for p in PAPERS.values() if p.item.match(Path(d).parent.name)), TIMES)


#: The Times of the 1970s-80s prints its blocks grey (67-82% ink in the
#: scans), not solid; the grid must still be symmetric to stand.
BLOCK_ABOVE = 0.6


def issues_between(a, b):
    """How many issues (six a week, none on Sunday) follow day `a` up to and
    including the later day `b`."""
    weeks, rest = divmod((b - a).days, 7)
    return weeks * 6 + sum((a + datetime.timedelta(days=i)).weekday() != 6 for i in range(1, rest + 1))


def held_dates(series):
    """{number: date} of every dated puzzle filed in a series."""
    out = {}
    for p in (ROOT / "puzzles" / series).glob("*/*.json"):
        date = json.loads(p.read_text()).get("date")
        if date:
            out[int(p.stem.split("-")[1])] = datetime.date.fromisoformat(date[:10])
    return out


def placed(n, day, held):
    """(number, None) that an edition of `day` read as No `n` files as, or
    (None, why) it cannot file. The edition's date is trusted over a number
    OCR read: when the nearest filed puzzles either side run unbroken, one
    number an issue, the date fixes the number; otherwise No `n` must sit in
    date order among them and not be filed for another day."""
    before = max(((d, m) for m, d in held.items() if d < day), default=None)
    after = min(((d, m) for m, d in held.items() if d > day), default=None)
    if before and after and after[1] - before[1] == issues_between(before[0], after[0]):
        return before[1] + issues_between(before[0], day), None
    if n in held and held[n] != day:
        return None, f"No {n} is already filed for {held[n]}, not {day}"
    if before and n <= before[1] or after and n >= after[1]:
        return None, (f"No {n} on {day} is out of date order with "
                      f"{' and '.join(f'No {m} on {d}' for d, m in (before, after) if d)}")
    return n, None


def issue_day(day, n, numbers):
    """The date of No `n` in an edition dated `day` holding `numbers`: an item
    can bind the next days' papers too, so each number above the lowest is one
    issue later (six a week, none on Sunday)."""
    for _ in range(n - min(numbers) if n - min(numbers) <= 6 else 0):
        day += datetime.timedelta(days=1 + (day.weekday() == 5))
    return day


def read_puzzle(d, found, hit, solutions):
    """(verdict, puzzle or None) for one title on one page."""
    n, leaf = hit["number"], hit["leaf"]
    verdict = {"number": n, "leaf": leaf}
    paper = paper_of(d)
    day = issue_day(datetime.date.fromisoformat(found["date"]), n, [h["number"] for h in found["puzzles"]])
    if abs(n - paper.expected(day)) > NUMBER_SLACK:
        verdict["refused"] = (f"No {n} is not near the {paper.expected(day)} the date "
                              f"{day} implies: the item's date is wrong")
        return verdict, None
    number, why = placed(n, day, held_dates(paper.series))
    if why:
        verdict["refused"] = why
        return verdict, None
    if number != n:
        verdict["read_as"], n = n, number
        verdict["number"] = n
    img = page(d, leaf)
    lines = leaf_lines(d / "djvu.xml.gz", {leaf})[leaf]
    gbox, side = (grid_under_clues(img, hit["box"]), "below") if paper.clues_above else locate_grid(img, hit["box"])
    if gbox is None:
        verdict["refused"] = "no ink under the title"
        return verdict, None
    gw, gh = gbox[2] - gbox[0], gbox[3] - gbox[1]
    if side is None or not grid_shaped(gbox):
        verdict["refused"] = f"the ink under the title is {gw}x{gh}, not a grid"
        return verdict, None
    key = f"{d.name}_{n}"
    third = (paper.third, third_top(img, gbox, paper.third)) if paper.third else None
    m = paper.margin
    # Clues over the grid: from the title line down, split where the fewest
    # words of any reading cross.
    top = hit["box"][1] - 10 if paper.clues_above else None
    beside = side == "left"
    rapid = {which: rapid_lines(img, gbox, which, CROPS / "rapid" / f"{key}.{reader_key(which)}.json", third, m, top,
                                beside) for which in READERS}
    above = left = None
    every = lines + [ws for r in rapid.values() for ws in r]
    if top is not None:
        above = (top, gutter(every, gbox, top), gutter(every, gbox, top, gbox[2] - OVERHANG, gbox[2] + OVERHANG))
    if beside:
        left = left_columns(every, gbox)
    cols = {"djvu": columns(lines, gbox, third, m, above, left)}
    for which in READERS:
        cols[which] = columns(rapid[which], gbox, third, m, above, left)
    texts = {k: column_text(c) for k, c in cols.items()}
    wins = windows(gbox, third, m, above, left)
    # The desktop's VLM, when it answers, is one more reading.
    if vlm.reachable():
        try:
            texts["vlm"] = "\n".join(numbered_heading(t) or t for t in
                                     vlm.column_text(img, wins, list(cols.values())).splitlines())
        except RuntimeError:
            pass  # gone mid-run: read as without it; run() files it to be read again
    # archive.org's words and RapidOCR's are the two readings; where
    # archive.org's OCR has no words for the columns, RapidOCR's two
    # recognisers are.
    gpath = CROPS / "grids" / f"{key}.png"
    gpath.parent.mkdir(parents=True, exist_ok=True)
    # Cut afresh on every read, so the crop is always of this grid box.
    img.crop((gbox[0] - 6, gbox[1] - 6, gbox[2] + 6, gbox[3] + 6)).save(gpath)
    image, why = trove_grid.read_grid(gpath, block_above=BLOCK_ABOVE)
    g = image
    if g and not trove_grid.symmetric(g):
        g, why = None, "not 180-degree symmetric"
    if not g:
        verdict["imageUnread"] = why
    texts, dropped = screened(texts, g)
    if dropped:
        verdict["dropped"] = dropped
    # Each reading in turn is the list, repaired from the other: archive.org's
    # against RapidOCR's, and where archive.org has no words for the columns,
    # RapidOCR's two recognisers against each other. The first list that
    # lies on the scanned grid wins; failing all, the most complete list is
    # rebuilt.
    pairs = ([("djvu", "ch"), ("ch", "djvu"), ("djvu", "en5"), ("en5", "djvu")]
             if texts.get("djvu", "").strip() else [("ch", "en5"), ("en5", "ch")])
    # A reading the screen dropped is in no pair; the readings no pair names
    # (Tesseract's, the VLM's) lead when none of those parses.
    pairs = [o for o in pairs if all(k in texts for k in o)]
    named = {k for o in pairs for k in o}
    rest = [(k, next((o for o in texts if o != k), k)) for k in texts if k not in named]
    tried = []
    for order in pairs + rest:
        if order in rest and tried:
            break
        parsed, why = parse(texts[order[0]])
        if parsed is None:
            verdict.setdefault("unparsed", {})[order[0]] = why
            continue
        # A clue this list lost is taken from each other reading in turn.
        for other in [order[1]] + [k for k in texts if k not in order]:
            if trove_clue_ocr.complete(parsed):
                break
            parsed, _ = trove_clue_ocr.repair(parsed, texts[other])
        laid, why = ftp.match(parsed, g) if g else (None, None)
        tried.append((laid is not None, trove_clue_ocr.complete(parsed),
                      sum(len(v) for v in parsed.values()), -len(tried), order, parsed, laid, why))
        if laid is not None:
            break
    if not tried:
        verdict["refused"] = "no reading parses"
        return verdict, None
    ok, done, count, _, order, parsed, laid, why = max(tried, key=lambda t: t[:4])
    verdict["readings"] = list(order)
    verdict["clues"] = count
    verdict["complete"] = done
    # Every other reading votes on the list's words.
    stream = [t for k, t in texts.items() if k != order[0] and t.strip()]
    grid, how = (g, "image") if ok else (None, None)
    if g and not ok:
        verdict["imageDisagrees"] = why
        # The scan's grid stands when nearly every clue lies on it: the few
        # that do not are misreads, filed blank, never forced to fit.
        # Each light takes the first reading whose clue lies on it, and is
        # checked against another reading than its own.
        # The readings no pair tried (the VLM's, Tesseract's) come last.
        lists = [(o, p) for _, _, _, _, o, p, _, _ in tried]
        for k in texts:
            if k not in {o[0] for o, _ in lists} and texts[k].strip():
                p, _ = parse(texts[k])
                if p is not None:
                    lists.append(((k,), p))
        loose, src = {}, {}
        for o, p in lists:
            for lid, v in lay_loose(p, g)[0].items():
                if lid not in loose:
                    loose[lid], src[lid] = v, o
        # Then the clues whose number was lost, into the lights no reading
        # laid by number.
        by_number = set(loose)
        for o, p in lists:
            for lid, v in lay_loose(p, g, by_number)[0].items():
                if lid not in loose:
                    loose[lid], src[lid] = v, o
        verdict["looseLaid"] = len(loose)
        if len(loose) >= LOOSE_SHARE * len(rg.light_cells(g)):
            grid, how, laid = g, "image", loose
            verdict["readings"] = sorted({o[0] for o in src.values()})
            stream = [{lid: t for lid, o in src.items() if k != o[0]}
                      for k, t in texts.items() if t.strip()]
    if grid is None:
        g, why = ftp.rebuild(parsed, image)
        if g is None:
            verdict["pending"] = f"no grid: {why}"
            return verdict, None
        laid, why = ftp.match(parsed, g)
        if laid is None:
            verdict["pending"] = f"rebuilt grid disagrees: {why}"
            return verdict, None
        grid, how = g, "rebuilt"
    verdict["grid"] = how
    lengths = {f"{n_}-{d_}": len(cells) for (n_, d_), cells in rg.light_cells(grid).items()}
    fits = {lid for lid, (_, enum, group) in laid.items()
            if enum and not group and ftp.count(enum) == lengths.get(lid)}
    laid, blank = reconcile(laid, stream, lengths)
    if blank and "vlm" in texts and vlm.reachable():
        try:
            laid, blank = vlm_pick(img, wins, list(cols.values()), texts, laid, blank)
        except RuntimeError:
            pass
    laid, blank = one_light_each(laid, blank, fits)
    verdict["lights"] = len(rg.light_cells(grid))
    verdict["agreed"] = sum(1 for t, _, _ in laid.values() if t)
    if blank:
        verdict["blank"] = blank
    puzzle = build(n, day, grid, how, laid, found["item"], leaf, series=paper.series,
                   name=paper.name.format(n))
    setter = byline(img, hit, paper.series)
    if setter:
        puzzle["setter"] = setter
    sol = solutions.get(n)
    if sol:
        answers, info = read_solution(sol, grid, above=paper_of(sol["dir"]).solution_above)
        verdict["solutionFrom"] = f"{sol['dir'].name} leaf {sol['leaf']}"
        verdict["solution"] = info
        verdict["answers"] = trove_solution_ocr.fill(puzzle, answers)
    return verdict, puzzle


#: The share of a reading's clues that must lie on the scanned grid by their
#: own number and count, and agree with the other readings' clue of that
#: number, for the reading to vote at all.
FIT_SHARE = 0.5
#: How like the other readings' clue of its number a clue must read to agree.
AGREE_SIMILAR = 0.5
#: How many numbered clues a reading needs before its share is judged.
FIT_MIN = 4


def numbered(parsed):
    """{(number, direction): (text, enums)} of each clue that names one light."""
    return {(next(iter(c["tokens"][0])), d): (c["text"], c["enums"])
            for d in ("across", "down") for c in parsed[d]
            if len(c["tokens"]) == 1 and len(c["tokens"][0]) == 1 and c["see"] is None}


def screened(texts, grid):
    """({reader: text} that vote, {reader: why} dropped): a reading with no
    clue words (every clue blank, or nothing but headings) is no reading,
    and one whose clues mostly name no light of the scanned grid with
    their count, or mostly disagree with what the other readings print
    under the same numbers, read another part of the page."""
    clues = {}
    for k, t in texts.items():
        p = parse(t)[0] if t.strip() else None
        clues[k] = numbered(p) if p else None
    lights = rg.light_cells(grid) if grid else None
    keep, dropped = {}, {}
    for k, t in texts.items():
        if not t.strip():
            continue
        cs = clues[k]
        if not ocr_clues.tokens(re.sub(r"\b(?:ACROSS|DOWN)\b", "", t)) or (
                cs and not any(ocr_clues.tokens(text) for text, _ in cs.values())):
            dropped[k] = "no clue words"
            continue
        if not cs or len(cs) < FIT_MIN:
            keep[k] = t
            continue
        # A clue whose count was lost says nothing of where it was read, and
        # a reading that lost most counts is judged by its text alone.
        counted = {key: enums for key, (_, enums) in cs.items() if enums}
        if lights and len(counted) >= max(FIT_MIN, len(cs) / 2):
            fit = sum(1 for (n, d), enums in counted.items()
                      if (n, d) in lights and any(ftp.count(e) == len(lights[(n, d)]) for e in enums))
            if fit < FIT_SHARE * len(counted):
                dropped[k] = f"{fit} of {len(counted)} counted clues lie on the grid"
                continue
        shared = []
        for key, (text, _) in cs.items():
            others = [clues[j][key][0] for j in texts if j != k and clues[j] and key in clues[j]]
            if others:
                shared.append(max(similar(text.lower(), o.lower()) for o in others))
        agree = sum(1 for v in shared if v >= AGREE_SIMILAR)
        if len(shared) >= FIT_MIN and agree < FIT_SHARE * len(shared):
            dropped[k] = f"{agree} of {len(shared)} clues agree with the other readings"
            continue
        keep[k] = t
    return keep, dropped


def vlm_pick(img, wins, readings, texts, laid, blank):
    """ocr_clues.vlm_pick for a scan page: the VLM shown the clue columns
    (`wins`, boxed by every reading's lines)."""
    return ocr_clues.vlm_pick(texts, laid, blank, parse,
                              lambda lid, cands: vlm.pick(img, wins, readings, lid, cands))


def third_top(img, grid, width):
    """Where the clue column right of the grid starts: under the solution
    grid printed beside the grid and its label ("CROSSWORD SOLUTION
    20,539", whose top lies within LABEL_DROP of the grid's foot), or level
    with the grid when none is there."""
    gx0, gy0, gx1, gy1 = grid
    crop = (gx1 + 15, max(0, gy0 - 60), min(img.width, gx1 + 15 + width), gy1)
    box = ink_box(img.crop(crop))
    if box is None:
        return gy0 - 5
    bw, bh = box[2] - box[0], box[3] - box[1]
    if not (0.4 * width <= bw <= width and 0.85 <= bw / max(bh, 1) <= 1.18):
        return gy0 - 5
    return crop[1] + box[3] + LABEL_DROP


#: How far under the solution grid its label's top may lie.
LABEL_DROP = 25


def byline(img, hit, series=FT.series):
    """The setter archive.org's words name under the title ("Set by DANTE"),
    when it is one the series' files name, a dictionary word, or what
    RapidOCR reads there too: archive.org alone misreads ("Grifftn")."""
    read = hit.get("setterRead")
    if not read or read in setters(series) or is_word(read.lower()):
        return read
    import numpy as np
    x0, y0, x1, y1 = hit["box"]
    crop = img.crop((x0, y0 - 10, x1, y1 + 10)).convert("RGB")
    crop = crop.resize((crop.width * UPSCALE, crop.height * UPSCALE))
    for which in ("en5", "ch"):
        res, _ = engine(which)(np.asarray(crop), use_cls=False)
        m = FT_SETTER.search(" ".join(t for _, t, _ in res or ()))
        if m and m.group(1).title() == read:
            return read
    return None


#: The share of a solution grid's cells that must be block or light exactly
#: where the puzzle's grid has them, for its letters to count.
SOLUTION_BLOCKS = 0.97


def read_solution(sol, grid, above=False):
    """({light: answer}, stats) read off the solution grid under a "Solution
    to Puzzle No N" heading, or with `above`, over it (the Guardian's)."""
    d, leaf = sol["dir"], sol["leaf"]
    x0, y0, x1, y1 = sol["box"]
    from PIL import Image
    img = page(d, leaf)
    w = x1 - x0
    crop = (max(0, x0 - 80), y1, min(img.width, x1 + 140), min(img.height, y1 + int(1.4 * w) + 60))
    if above:
        crop = (max(0, x0 - 80), max(0, y0 - int(1.4 * w) - 60), min(img.width, x1 + 140), y0)
    box = ink_box(img.crop(crop))
    if box is None:
        return {}, {"refused": "no ink under the heading"}
    bw, bh = box[2] - box[0], box[3] - box[1]
    if not (200 <= bw <= 700 and 0.85 <= bw / max(bh, 1) <= 1.18):
        return {}, {"refused": f"the ink under the heading is {bw}x{bh}"}
    path = CROPS / "solutions" / f"{d.name}_{sol['number']}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        sol = img.crop((crop[0] + box[0], crop[1] + box[1], crop[0] + box[2], crop[1] + box[3]))
        # The recogniser reads the ~23px cells far surer at three times the size.
        sol.resize((sol.width * 3, sol.height * 3), Image.BICUBIC).save(path)
    answers, stats = trove_solution_ocr.read_answers(path, grid)
    if stats["blocks"] < SOLUTION_BLOCKS:
        return {}, {**stats, "refused": "its blocks are not the puzzle's"}
    return {f"{n}-{d}": w for (n, d), w in answers.items()}, stats


# ------------------------------------------------------------ the run

#: Editions read at once: the desktop VLM serves one request at a time, so a
#: second one's OCR fills the first one's wait; more contend for the host's
#: four cores.
WORKERS = 2


def scan_key():
    """A hash of this file's code that finds an edition's titles and solution
    headings (SCAN_CODE, read from the file): a scan made by other code is
    made again."""
    if not _SCAN_KEY:
        import ast
        text = Path(__file__).read_text()
        h = hashlib.sha256()
        for node in ast.parse(text).body:
            names = ([node.name] if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else
                     [t.id for t in node.targets if isinstance(t, ast.Name)] if isinstance(node, ast.Assign) else [])
            if set(names) & SCAN_CODE:
                h.update(ast.get_source_segment(text, node).encode())
        _SCAN_KEY.append(h.hexdigest()[:16])
    return _SCAN_KEY[0]


#: The names whose code scan() runs.
SCAN_CODE = {"leaf_lines", "headings", "scan", "ft_headings", "guardian_headings", "telegraph_headings", "Paper",
             "numbered_heading", "heading_of", "digits", "box_of", "centred", "number_of", "NUMBER", "TITLE",
             "SOLUTION", "FT_TITLE", "FT_NUMBER", "FT_SETTER", "FT_SOLUTION", "G_NUMBER", "GUARDIAN_TITLE",
             "GUARDIAN_SOLUTION", "TELEGRAPH_SOLUTION", "NUMBERED_HEADING", "FT_GRID_SPAN", "FT_SOLUTION_SPAN",
             "TELEGRAPH_SOLUTION_SPAN", "OBJECT_TAG", "GRID_FILL", "TITLE_REACH", "grids_on", "title_bands",
             "printed_lines", "band_words", "ocr_titles", "grid_shaped"}
_SCAN_KEY = []


def input_hash(d):
    """The edition's files by name and size."""
    h = hashlib.sha256()
    for p in sorted(d.iterdir()):
        st = p.stat()
        h.update(f"{p.name}:{st.st_size}".encode())
    return h.hexdigest()[:16]


def held_numbers(series=SERIES):
    return {int(p.stem.split("-")[1]) for p in (ROOT / "puzzles" / series).glob("*/*.json")}


def destination(puzzles, complete=True):
    """Where a puzzle files: None for the corpus, the `puzzles` dir, or False
    for nowhere. Only a `complete` puzzle (every clue has text) goes to the
    corpus, whatever the paper or year: a solver cannot work one with a blank
    clue, so that one goes to `puzzles` (--out) when given, else nowhere."""
    if complete:
        return None
    return puzzles or False


def complete(puzzle):
    """Whether every clue of a puzzle has text, none with a word OCR made
    up (ocr_clues.suspect)."""
    return filled(puzzle)[0] == len(puzzle["entries"]) and not any(
        suspect((e.get("clue") or {}).get("text", "")) for e in puzzle["entries"])


def progress(line):
    """One line per source as it is read, to stderr, so a long run's log moves."""
    print(f"{time.strftime('%H:%M:%S')} {line}", file=sys.stderr, flush=True)


def run(cache=CACHE, write=True, ledger=None, out=sys.stdout, puzzles=None, limit=None,
        source=SOURCE, paper=None, seconds=None, workers=1, wait=False, reread=None, editions=None):
    """File what is new under `cache`: complete puzzles into the corpus, ones
    with a blank clue into `puzzles` when given. At most `limit` editions are
    read, none started after `seconds`, `workers` at once (scan_queue).
    `reread` (a datetime) reads again every edition last read before it;
    `editions` ("ITEM/EDITION" names) reads those again and no other.
    Returns the ledger rows; [] when another run holds the ledger and `wait`
    is not set."""
    deadline = None if seconds is None else time.monotonic() + seconds
    ledger = Path(ledger or cache / "filed.jsonl")
    with scan_queue.lock(ledger, wait) as mine:
        if not mine:
            print(f"another run holds {ledger.with_suffix('.lock')}: nothing read", file=out)
            return []
        return _run(cache, write, ledger, out, puzzles, limit, source, paper or TIMES, deadline, workers, reread,
                    editions)


def due_reason(row, inputs, sol_seen, vlm_up, reread=None):
    """Why an edition's ledger `row` is read again, or None: never read, its
    files (input_hash) or the solutions it can see moved, its titles moved
    since its verdicts (a scan by new code, see scan_key), read without the
    VLM that now answers, or last read before `reread` (a datetime: the
    explicit --reread)."""
    if "inputs" not in row:
        return "never read"
    if row["inputs"] != inputs or row.get("solutionsSeen") != sol_seen:
        return "inputs changed"
    if sorted(p["number"] for p in row["scan"]["puzzles"]) != sorted(v["number"] for v in row.get("verdicts", ())):
        return "titles changed"
    if vlm_up and not row.get("vlm"):
        return "read without the VLM"
    if reread and scan_queue.read_before(row, reread):
        return "--reread"
    return None


def _run(cache, write, ledger, out, puzzles, limit, source, paper, deadline, workers, reread, editions=None):
    from fetch_puzzle import puzzle_path, write_puzzle_file
    known = {}
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            row = json.loads(line)
            if "hash" in row and "inputs" not in row:
                # A row keyed by code and files together: its read stands
                # for the files it was read with.
                row.pop("hash")
                row["inputs"] = row.get("filesHash")
            known[row["edition"]] = row
    # The VLM's readings are an input: an edition read without it is read
    # again once it answers, and one read with it stands while it is down.
    seen_by = vlm.version() if vlm.reachable() else None
    dirs = edition_dirs(cache, paper)
    rels = {d: f"{d.parent.name}/{d.name}" for d in dirs}
    # Every heading first: a puzzle's solution is in a later edition.
    scans, unscanned = {}, {}
    for d in dirs:
        row = known.get(rels[d])
        fh = input_hash(d)
        if row and row.get("filesHash") == fh and row.get("scanKey") == scan_key() and "scan" in row:
            scans[rels[d]] = row["scan"]
        else:
            unscanned[d] = fh
    for (d,), found in scan_queue.parallel([(d,) for d in unscanned], scan, workers):
        scans[rels[d]] = found
        progress(f"scanned {rels[d]}: {len(found['puzzles'])} puzzle(s)")
        known[rels[d]] = {**known.get(rels[d], {}), "edition": rels[d], "scan": found, "filesHash": unscanned[d],
                          "scanKey": scan_key()}
    if unscanned and write:
        save(ledger, known)
    solutions = {}
    for d in dirs:
        for s in scans[rels[d]]["solutions"]:
            solutions.setdefault(s["number"], {**s, "dir": d})
    held = held_numbers(paper.series)
    due = {}
    for d in dirs:
        rel = rels[d]
        h = known[rel]["filesHash"]
        sol_seen = sorted(n for n in (p["number"] for p in scans[rel]["puzzles"]) if n in solutions)
        if (rel in editions) if editions else due_reason(known[rel], h, sol_seen, seen_by, reread):
            due[d] = (h, sol_seen)
    queue = scan_queue.order(list(due), {d: known[rels[d]] for d in due}, lambda row: "inputs" not in row)
    if limit is not None:
        queue = queue[:limit]
    fresh = 0
    for (d, found), (results, vlm_ok) in scan_queue.parallel(
            [(d, scans[rels[d]]) for d in queue], read_edition, workers, deadline,
            init=set_solutions, initargs=(solutions,)):
        rel = rels[d]
        h, sol_seen = due[d]
        fresh += 1
        verdicts = []
        for verdict, puzzle in results:
            hit_number = verdict["number"]
            if puzzle is not None:
                verdict["id"] = puzzle["id"]
                if write:
                    source.mkdir(parents=True, exist_ok=True)
                    (source / f"{puzzle['id']}.json").write_text(json.dumps(puzzle, indent=1))
                held_path = puzzle_path(paper.series, puzzle["number"])
                mended = mend_duplicates(puzzle, held_path) if held_path.exists() else None
                if mended is not None:
                    verdict["mended"] = mended[1]
                    if write:
                        try:
                            write_puzzle_file(held_path, mended[0], generator=TOOL)
                        except puzzle_integrity.RefusedWrite as e:
                            verdict["refusedWrite"] = str(e)
                        else:
                            verdict["wrote"] = True
                    verdicts.append(verdict)
                    continue
                dest = destination(puzzles, complete(puzzle))
                if dest is False:
                    verdict["skip"] = "a clue is blank: only a puzzle with every clue goes to the corpus"
                    verdicts.append(verdict)
                    continue
                path = (Path(dest) / f"{puzzle['id']}.json" if dest
                        else puzzle_path(paper.series, puzzle["number"]))
                better = path.exists() and improves(puzzle, path)
                if hit_number in held and not dest and not better:
                    verdict["skip"] = "already held: the reading votes in cross_validate.py"
                elif write and (better or not path.exists()):
                    try:
                        write_puzzle_file(path, puzzle, generator=TOOL)
                    except puzzle_integrity.RefusedWrite as e:
                        verdict["refusedWrite"] = str(e)
                    else:
                        verdict["wrote"] = True
                        held.add(hit_number)
            verdicts.append(verdict)
        known[rel] = {"edition": rel, "inputs": h, "scan": found, "filesHash": h, "scanKey": scan_key(),
                      "solutionsSeen": sol_seen, "verdicts": verdicts, "readAt": scan_queue.now()}
        if seen_by and vlm_ok:
            known[rel]["vlm"] = seen_by
        if write:
            save(ledger, known)
        progress(f"read {rel}: " + ("; ".join(
            f"{v['number']} " + ("wrote " + v["id"] if v.get("wrote") else
                                 v.get("skip") or v.get("refused") or v.get("refusedWrite") or v.get("id") or "read")[:60]
            for v in verdicts) or "nothing filed"))
    if write:
        save(ledger, known)
    tally = report(known[rels[d]] for d in dirs)
    if len(due) > fresh:
        tally["left for the next run"] = len(due) - fresh
    print(f"{len(dirs)} {paper.key} editions in {cache}; {fresh} read this run", file=out)
    for k in sorted(tally):
        print(f"  {tally[k]:5d}  {k}", file=out)
    return list(known.values())


_SOLUTIONS = {}


def set_solutions(solutions):
    """Each process's {number: solution heading} (read_edition's)."""
    _SOLUTIONS.clear()
    _SOLUTIONS.update(solutions)


def read_edition(d, found):
    """([(verdict, puzzle or None)] for each title in an edition, whether the
    VLM still answers after it)."""
    results = []
    for hit in found["puzzles"]:
        try:
            verdict, puzzle = read_puzzle(d, found, hit, _SOLUTIONS)
        except Exception as e:  # noqa: BLE001 -- one bad page is a verdict, not a crash
            verdict, puzzle = {"number": hit["number"], "refused":
                               f"crashed: {type(e).__name__}: {e}"}, None
        results.append((verdict, puzzle))
    return results, vlm.reachable()


def filled(puzzle):
    """(clues with text, answers) of a puzzle."""
    es = puzzle["entries"]
    return (sum(1 for e in es if ((e.get("clue") or {}).get("text") or "").strip()),
            sum(1 for e in es if e.get("solution")))


def improves(puzzle, path):
    """Whether `puzzle` should replace the file at `path`: one this tool
    filed, on the same grid, that the new reading beats on clues or answers
    and loses on neither."""
    old = json.loads(path.read_text())
    if (old.get("source") or {}).get("acquiredBy") != TOOL \
            or trove_solution_ocr.puzzle_grid(old) != trove_solution_ocr.puzzle_grid(puzzle):
        return False
    def have(p, field):
        return {entry_id(e) for e in p["entries"]
                if field == "clue" and ((e.get("clue") or {}).get("text") or "").strip()
                or field == "solution" and e.get("solution")}
    # Nothing the file has may go blank: only a reading that keeps every
    # clue and answer and adds some replaces it.
    if not all(have(old, f) <= have(puzzle, f) for f in ("clue", "solution")):
        return False
    return filled(puzzle) != filled(old)


def mend_duplicates(puzzle, path):
    """(the held file at `path` mended, {light: its clue now}), or None: each
    light the file gives a clue it gives another light too
    (fetch_puzzle.duplicated_clues) takes this reading's clue for it, which
    one_light_each left on one light at most, else blank, for the blank-clue
    re-read. None when the file holds no such clue, is not this tool's, or
    lies on another grid than this reading. With no reading (`puzzle`
    None: its scan now reads as another number), every such light is blank."""
    from fetch_puzzle import duplicated_clues
    old = json.loads(path.read_text())
    puzzle = puzzle or {"entries": []}
    if (old.get("source") or {}).get("acquiredBy") != TOOL \
            or puzzle["entries"] and trove_solution_ocr.puzzle_grid(old) != trove_solution_ocr.puzzle_grid(puzzle):
        return None
    lost = {i for ids in duplicated_clues(old["entries"]) for i in ids}
    if not lost:
        return None
    now = {entry_id(e): e["clue"] for e in puzzle["entries"]}
    blank = enumeration.clue("", missing=True)
    for e in old["entries"]:
        if entry_id(e) in lost:
            e["clue"] = now.get(entry_id(e)) or blank
    # This reading's clue for a lost light may be one the file keeps on
    # another: that light's then goes blank too.
    for ids in duplicated_clues(old["entries"]):
        for e in old["entries"]:
            if entry_id(e) in ids and entry_id(e) in lost:
                e["clue"] = blank
    return old, {entry_id(e): e["clue"].get("text") or "" for e in old["entries"] if entry_id(e) in lost}


def save(ledger, known):
    ledger.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in known.values()))
    tmp.replace(ledger)


# ------------------------------------------------------------ the Canberra reprints

def shingles(puzzle):
    """The word triples of a puzzle's clues: what two OCR'd copies of one
    clue list share even where each misreads a word or two."""
    out = set()
    for e in puzzle["entries"]:
        w = re.findall(r"[a-z]+", ((e.get("clue") or {}).get("text") or "").lower())
        out |= {" ".join(w[k:k + 3]) for k in range(len(w) - 2)}
    return out


#: The share of the smaller copy's word triples the two must share, and how
#: far the best match must lead the next.
MATCH_SHARE = 0.3
MATCH_LEAD = 2.0


def match_canberra(source=SOURCE, write=True, out=sys.stdout, canberra=ROOT / "puzzles" / "canberra"):
    """Name the Times puzzle each canberra file reprints: the archive.org
    reading sharing the most clue word triples, when it shares at least
    MATCH_SHARE of them, leads the runner-up MATCH_LEAD times over, was
    printed in London first, and the grids are the same. Returns
    {canberra id: times id}."""
    from fetch_puzzle import read_puzzle_file, write_puzzle_file
    readings, index = {}, {}
    for p in sorted(source.glob("times-*.json")):
        r = json.loads(p.read_text())
        readings[r["id"]] = r
        for sh in shingles(r):
            index.setdefault(sh, set()).add(r["id"])
    found = {}
    for path in sorted(canberra.glob("*/*.json")):
        c = read_puzzle_file(path)
        mine = shingles(c)
        if len(mine) < 20:
            continue
        hits = {}
        for sh in mine:
            for tid in index.get(sh, ()):
                hits[tid] = hits.get(tid, 0) + 1
        ranked = sorted(hits.items(), key=lambda kv: -kv[1])
        if not ranked:
            continue
        tid, n = ranked[0]
        r = readings[tid]
        share = n / min(len(mine), len(shingles(r)) or 1)
        lead = n / ranked[1][1] if len(ranked) > 1 else float("inf")
        same_grid = trove_solution_ocr.puzzle_grid(c) == trove_solution_ocr.puzzle_grid(r)
        if share < MATCH_SHARE or lead < MATCH_LEAD or r["date"] > c["date"] or not same_grid:
            continue
        found[c["id"]] = tid
        print(f"{c['id']} reprints {tid}: {n} clue word triples shared ({share:.0%})", file=out)
        if write and (c.get("source") or {}).get("reprintOf") != tid:
            c["source"] = {**c["source"], "reprintOf": tid}
            write_puzzle_file(path, c)
    print(f"{len(found)} canberra files matched to a Times reading", file=out)
    return found


def report(rows):
    tally = {}

    def add(k, n=1):
        tally[k] = tally.get(k, 0) + n
    for row in rows:
        for v in row.get("verdicts", ()):
            add("puzzles found")
            if v.get("complete"):
                add("clue lists complete")
            if v.get("grid"):
                add(f"grid {v['grid']}")
            if v.get("id"):
                add("puzzles read")
                add("answers read", v.get("answers", 0))
                add("clues blank (readings disagree)", len(v.get("blank", {})))
            if v.get("wrote"):
                add("written")
            for k in ("refused", "pending"):
                if v.get(k):
                    add(f"{k}: {v[k].split(':')[0][:50]}")
    return tally


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--ledger", type=Path, help="default <cache>/filed.jsonl")
    ap.add_argument("--out", type=Path,
                    help="write puzzles with a blank clue here; complete ones still go into puzzles/")
    ap.add_argument("--source", type=Path, default=SOURCE,
                    help="where every reading goes for cross_validate.py")
    ap.add_argument("--limit", type=int, help="read at most N new or changed editions")
    ap.add_argument("--seconds", type=float,
                    help="start no edition after N seconds; the rest wait for the next run")
    ap.add_argument("--workers", type=int, default=WORKERS,
                    help=f"editions read at once (default {WORKERS}): one's VLM wait overlaps another's OCR")
    ap.add_argument("--wait", action="store_true",
                    help="wait for another run's hold on the ledger instead of reading nothing")
    ap.add_argument("--reread", nargs="?", const="now", metavar="BEFORE",
                    help="read again every edition last read before BEFORE (an ISO time; default now): "
                         "the one-off after a change to this code or the VLM model, which alone makes nothing due")
    ap.add_argument("--edition", action="append", metavar="ITEM/EDITION",
                    help="read this edition again, and no other (repeatable)")
    ap.add_argument("--mend-held", nargs="+", metavar="ID",
                    help="blank each clue these held filings give two lights, with no reading")
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    ap.add_argument("--show", metavar="ITEM/EDITION", help="one edition's verdicts")
    ap.add_argument("--paper", choices=sorted(PAPERS), default="times",
                    help="whose editions to file: the Times (times-N), the FT (ftcryptic-N), the Guardian "
                         "(cryptic-N) or the Telegraph (telegraph-N)")
    ap.add_argument("--match-canberra", action="store_true",
                    help="only name the Times puzzle each canberra file reprints")
    args = ap.parse_args(argv)
    if args.match_canberra:
        match_canberra(args.source, write=not args.dry_run)
        return 0
    if args.mend_held:
        from fetch_puzzle import puzzle_paths, write_puzzle_file
        for pid in args.mend_held:
            path = puzzle_paths.find(pid)
            mended = path and mend_duplicates(None, path)
            print(pid, mended[1] if mended else "nothing to mend")
            if mended and not args.dry_run:
                write_puzzle_file(path, mended[0], generator=TOOL)
        return 0
    if args.show:
        d = args.cache / args.show
        found = scan(d)
        sols = {}
        for e in edition_dirs(args.cache, paper_of(d)):
            for s in scan(e)["solutions"] if e.parent == d.parent else ():
                sols.setdefault(s["number"], {**s, "dir": e})
        for hit in found["puzzles"]:
            verdict, puzzle = read_puzzle(d, found, hit, sols)
            print(json.dumps(verdict, indent=1))
            if puzzle:
                for e in puzzle["entries"]:
                    print(f"  {e['number']:2d}{e['direction'][0]} {e.get('solution') or '-':15s} "
                          f"{(e['clue'] or {}).get('text', '')} ({(e['clue'] or {}).get('enumeration')})")
        return 0
    run(args.cache, write=not args.dry_run, ledger=args.ledger, puzzles=args.out,
        limit=args.limit, source=args.source, paper=PAPERS[args.paper], seconds=args.seconds,
        workers=args.workers, wait=args.wait, reread=scan_queue.when(args.reread), editions=args.edition)
    if args.paper == "times":
        match_canberra(args.source, write=not args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
