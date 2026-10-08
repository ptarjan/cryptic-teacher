#!/usr/bin/env python3
"""File the daily Times cryptics in archive.org's scans of The Times 1974-99.

    python3 tools/file_archive_org_puzzles.py               # file what is new on disk
    python3 tools/file_archive_org_puzzles.py --dry-run     # count, write nothing
    python3 tools/file_archive_org_puzzles.py --limit 40    # read at most 40 new editions
    python3 tools/file_archive_org_puzzles.py --show NewsUK1990UKEnglish/1990-01-02_63592
    python3 tools/file_archive_org_puzzles.py --check-filed  # list filed puzzles with a clue it refuses now

Reads what tools/fetch_archive_org_editions.py leaves in
downloads.ARCHIVE_ORG/<item>/<date>_<issue>/ (djvu.xml.gz with word
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
    puzzle is filed only when the clues lie on the rebuilt grid. When no
    grid fits the clues the scan's grid stands, the lights no clue lies on
    blank: on the 1970s-80s scans the grid reads true and the clue OCR is
    what fails.
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
    "Solution to Puzzle No N", read by tools/trove_solution_ocr.py's
    read_framed (each cell between its own rules; a numbered or unsure cell
    matched to the grid's own letters, settled by its lights' words): a
    light only when every letter is read and it is a word, and the whole
    solution only when its blocks are the puzzle's.
  - Only a puzzle whose every clue has text goes into puzzles/times: one
    with a blank clue goes to --out (or nowhere without it).
  - A number already held is not written (unless this tool filed it and the
    new reading beats it on clues or answers, improves), but takes the
    reading's answers when this tool filed it (merge_answers: a new answer
    replaces the held one, and a held answer the re-read of its solution
    grid did not read again, or a new one crosses on another letter,
    goes); the reading goes to
    downloads.ARCHIVE_ORG_SOURCE, where tools/cross_validate.py's
    `archiveorg` adapter votes with it. Every reading goes there, filed or not.

A Times run also reads the 1930 Times (TIMES_1930: archive.org's pub_times,
one item an issue, "THE TIMES CROSSWORD PUZZLE No. 27"). Its pages are
scanned 13663px wide, so page() and leaf_lines() shrink them 4x to the
1974-99 scale. A 1-3 digit title number must lie within 3 of the one its
date implies (six a week from No 1 on 1 Feb 1930), else the page's
"SOLUTION OF PUZZLE No. N" gives N+1. The clues are four columns under the
grid (columns_of_four): ACROSS down the first two over the DOWN heading,
DOWN under it and on down the third and fourth. They print no counts, so
each reading gets the scanned grid's (counted()) and is filed without
them; a grid that does not read refuses the title. A count that fits any
text cannot show a clue whose lost number ran it into the one before, so
each reading's clues must name the grid's lights in order: a clue next to
a break (a light skipped, a number repeated, a list ending short) is
dropped from that reading, its lights left to the others or blank. Only RapidOCR's two
recognisers and the VLM (each virtual column read on its own) read them:
archive.org's words and the tuned Tesseract read these pages as junk.

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

--paper gale reads the Times pages Paul saves from Gale's Times Digital
Archive (tools/gale_inbox.py lays each date out as
GaleTimes<year>UKEnglish/<date>; tools/gale_read.sh reads them minutes
after they land), under a ledger of its own (downloads.GALE_LEDGER). A Gale
page has no archive.org text, so READERS read its whole ink for the title
(ocr_headings); each solution heading is read again in its own band
(solution_bands: from each "Solution" word any reader read, and over each
solution-sized grid), where half the readers must read its number. Its
puzzles' source.url is the Gale document's page (pages.json "url"), which
provenance files as an OCR'd newspaper page, so annotation can ask for one
to be read again (tools/scan_queue.py). A Monday prints no solution, and a
Saturday prize's solution prints the next Saturday.

Resumable: downloads.ARCHIVE_ORG/filed.jsonl records each edition's
headings and verdicts against its inputs (its files, the solutions seen,
whether the VLM read it), after each edition. Editions never read go first, then the stale by when they were read
(tools/scan_queue.py), so a capped run (--limit, --seconds) never starts over.
--workers N reads N editions at once (one's VLM wait overlaps another's OCR).
A change to the heading code (scan_key: the code scan() reaches, method by
method and across modules, tools/code_reach.py) makes
each edition's scan stale, so it is scanned again on its next read. Any
other change to this code or the VLM model makes nothing due: whoever makes it
runs the re-read once, `--reread [BEFORE]` (every edition last read before
BEFORE, an ISO time, default now; slices of one re-read share a BEFORE).
--no-scan reads only the due editions whose scans stand, and the scans of the
SOLUTION_DAYS after them (where their solutions print), and scans nothing.

The standing pass does not run this as a batch: tools/edition_queue.py
plans what is due (plan(): the same due_reason, scanning nothing) and runs
each edition as a unit of its own, scan_unit() or read_unit(), each locking
its edition and appending its own ledger row (scan_queue.append), so units
run side by side and a batch run (this CLI, holding the ledger's lock
throughout) holds them off: a unit then ends "held", left for the next plan.
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
import urllib.parse
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import enumeration
import file_trove_puzzles as ftp
import ocr_clues
import reconstruct_grid as rg
import scan_queue
import series as series_meta
import trove_clue_ocr
import trove_grid
import trove_solution_ocr
import vlm_reader as vlm
from file_penguin_puzzle import separators
from groups import entry_id
import downloads
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
CACHE = downloads.ARCHIVE_ORG
CROPS = Path(os.path.expanduser("~/.cache/archive_org_crops"))
SOURCE = downloads.ARCHIVE_ORG_SOURCE
TOOL = "tools/file_archive_org_puzzles.py"
#: archive.org's Times items.
ITEM = re.compile(r"NewsUK(19\d\d)UKEnglish$")
#: The Gale page images tools/gale_inbox.py lays out as Times editions of the
#: same shape (GaleTimes<year>UKEnglish/<date>), read as a paper of their own
#: (GALE).
GALE_ITEM = re.compile(r"GaleTimes(19\d\d)UKEnglish$")
#: {edition} is "<item>/<file base name>", quoted: an item holds a whole year
#: of editions, and archive.org opens one's scan only at the path naming its
#: file ("May 28 1974, The Times, #59100, UK (en)"); the item alone opens
#: whichever edition it chooses.
PAGE_URL = "https://archive.org/details/{edition}/page/n{leaf}/mode/1up"


def edition_of(d, found):
    """The {edition} of PAGE_URL for edition directory `d`: its item, then
    its file's base name (pages.json) unless that is the item itself."""
    name = json.loads((Path(d) / "pages.json").read_text()).get("edition")
    item = found["item"]
    return item if not name or name == item else f"{item}/{urllib.parse.quote(name, safe='')}"


def page_url(d, found, leaf):
    """Where a reader opens leaf `leaf` of edition directory `d`: the
    pages.json "url" of a page that is not archive.org's (a Gale page), else
    archive.org's PAGE_URL."""
    url = json.loads((Path(d) / "pages.json").read_text()).get("url")
    return url or PAGE_URL.format(edition=edition_of(d, found), leaf=leaf)


NUMBER = r"(\d{2}[,.\s]?\d{3})"
#: The daily cryptic's title: not the Concise, the Jumbo, Times Two, the
#: Listener or a solution heading (none of those words before "Crossword").
#: The OCR garbles the words before "Crossword" ("Tfee Th:es", "THETIMES",
#: "I he l imes"), puts a mark before or after it ("Crossword . No."), runs
#: "No" on ("PuzzleNo"), drops "No", splits the number ("1 8,862", "17,1 11"),
#: reads its comma as any mark ("21*065") and its 1 as i ("i.5,543");
#: read_puzzle checks the number against the date.
TITLE = re.compile(r"^\W*(?:(?!(?:sunday|conc\w*|jumbo|two|quick|\w*stener|solutions?|to|of)\b)\S{1,8}\s+){0,4}?"
                   r"\W{0,3}crossword\W{0,3}(?:puzzle\W{0,3})?(?:n[o0]\W{0,3})?\s*"
                   r"([\dTIil][.,]?\s?\d[^\w\s]{0,2}\s?\d\s?\d\s?\d)(?!\d)", re.IGNORECASE)
#: The previous puzzle's solution, printed under the clues ("to" read "tn").
SOLUTION = re.compile(r"^\W*solution\s+(?:t[o0n]|o[fl])\s+puzzle\s+n[o0]\.?\s*" + NUMBER, re.I)
#: A column line that ends the clues.
STOP = re.compile(r"^\W*(solution|crossword|concise|times\s+two|the\s+times\s+crossword|the\s+solution\s+(?:to|of)"
                  r"|championship|jumbo|\w{0,10}\s+(of|to)\s+puzzle|\S{4,9}\s+t[ao]m+or+ow|publ\w+\s+by"
                  r"|\S+\s+cr[o0]s+w[o0u]r?d\W+\w{2,5}\s+\d+)\b", re.I)
#: A line opening on a lowercase word ("championship. possibly (4).") runs
#: on a clue from the line above: a notice opens on a capital.
CONTINUED = re.compile(r"\W*[a-z]{4,}\b")


def stops(text):
    """Whether a column line ends the clues: a STOP line, never a clue's
    run-on line."""
    return bool(STOP.match(text)) and not CONTINUED.match(text)


#: The vertical gap, in pixels at the scan's 3296x4672, that ends a column.
GAP = 80
#: How far, in pixels, a line must start left of the split between two
#: columns and run on right of it to be printed across both (a centred
#: notice); a right-hand clue's outdented number starts a pixel or two left.
ACROSS_GUTTER = 60
#: What a line printed across both columns reads as in columns().
NOTICE = "\x00across the columns"



def number_of(text):
    return int(re.sub(r"\D", "", text))


# ------------------------------------------------------------ djvu.xml

def leaf_lines(xml_path, leaves):
    """{leaf: [[(x0, y0, x1, y1, text), ...] per printed line]} for the leaves
    asked for. Only those leaves' OBJECT elements are parsed: the n-th
    "<OBJECT" in the file is leaf n. {} when there is no such file (a
    Gale page has no archive.org text)."""
    if not Path(xml_path).exists():
        return {}
    with gzip.open(xml_path) as f:
        data = f.read()
    out = {}
    shrink = paper_of(Path(xml_path).parent).shrink
    for n, m in enumerate(OBJECT_TAG.finditer(data)):
        if n not in leaves:
            continue
        end = data.index(b"</OBJECT>", m.start()) + len(b"</OBJECT>")
        el = ET.fromstring(data[m.start():end])
        lines = []
        for line in el.iter("LINE"):
            ws = []
            for w in line.iter("WORD"):
                x0, y1, x1, y0 = (int(v) // shrink for v in w.get("coords").split(",")[:4])
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
            if m and not re.search(r"\w", text[m.end():]):
                box = (min(v[0] for v in ws[:k + 1]), min(v[1] for v in ws[:k + 1]),
                       max(v[2] for v in ws[:k + 1]), max(v[3] for v in ws[:k + 1]))
                found.append((digits(m.group(1)), box))
                break
    return found


# ------------------------------------------------------------ the page

def ink_box(img, close=0):
    """The largest patch of ink in a PIL image, as (x0, y0, x1, y1), or None;
    with `close`, gaps up to that many pixels across closed first (a frame
    the scan broke)."""
    import numpy as np
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    ink = gray < trove_grid.otsu(gray)
    if close:
        import cv2
        ink = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((close, close), np.uint8)) > 0
    return trove_grid.largest_component(ink)


def grid_shaped(box):
    """Whether an ink box is a grid's size and shape at the scans' 3296px
    page width."""
    if box is None:
        return False
    gw, gh = box[2] - box[0], box[3] - box[1]
    return 500 <= gw <= 1100 and 0.85 <= gw / max(gh, 1) <= 1.18


#: The page width grid_shaped() is measured at.
SCAN_WIDTH = 3296


def shaped_on(img, box):
    """grid_shaped() for a box on page `img`: a few pages are scanned at
    twice SCAN_WIDTH, their grid twice as wide."""
    return box is not None and grid_shaped(tuple(v * SCAN_WIDTH / img.width for v in box))


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
        shaped = page_box if shaped_on(img, page_box) else shaped
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
    return page_box if shaped_on(img, page_box) or shaped is None else shaped


#: How far over its title a grid printed over it may end (the 1980s Times'
#: touches it).
ABOVE_GAP = 80


def locate_grid(img, title):
    """(box, side) of the grid a title heads: the largest ink under it, else
    over it (the 1980s Times prints its title under the grid), else left of
    it (the FT's Monday Prize prints it right of the grid's top), else right
    of it (the 1983-86 FT heads the clue column left of the grid's top);
    `side` is "below", "above", "left" or "right". (box, None) when no ink
    there is a grid, the box the ink under the title; (None, None) when
    there is none. A title box may reach past the page's edge (an FT one is
    widened to FT_GRID_SPAN about its middle): the crops are clipped to it."""
    x0, y0, x1, y1 = title
    w = x1 - x0
    span = int(1.3 * w) + 80
    cx = (x0 + x1) / 2
    tries = (("below", (max(0, x0 - 120), y1, min(img.width, x1 + 120), min(img.height, y1 + span)), ("top",)),
             ("above", (max(0, x0 - 120), max(0, y0 - span), min(img.width, x1 + 120), y0), ("bottom",)),
             ("left", (max(0, x0 - span), max(0, y0 - 80), min(img.width, x0), min(img.height, y0 + span)), ()),
             ("right", (max(0, int(cx)), max(0, y0 - 80), min(img.width, int(cx) + span), min(img.height, y0 + span)),
              ()))
    first = None
    for side, crop, fixed in tries:
        if crop[2] - crop[0] < 2 or crop[3] - crop[1] < 2:
            continue
        box = footed(img, ink_in(img, crop, fixed))
        # A grid under its title clears the title's line, one over it ends
        # within ABOVE_GAP of it, one left of it ends short of the title's
        # middle, and one right of it starts past it: other ink is something
        # else's (an article over the 1983 FT's title beside its grid).
        clear = box is not None and (side != "below" or box[1] > crop[1] + 2
                                     or starts_under(img, box, crop[1])) \
            and (side != "above" or box[3] >= y0 - ABOVE_GAP) \
            and (side != "left" or box[2] < cx) and (side != "right" or box[0] > cx)
        if clear and shaped_on(img, box):
            return box, side
        first = first or box
    return first, None


#: The share of a grid box's width a row of ink must cover to be the grid's
#: frame: a line of text, even one touching the grid, has gaps.
FRAME_SHARE = 0.8
#: How far up a grid box (a share of its height) its foot frame may lie:
#: ink under it is a heading or clue line touching the grid.
FOOT_INSET = 0.1
#: How far, in pixels, a grid's top frame may reach up into its title's box.
TITLE_OVERLAP = 12
#: The most of a pixel row's width a fold or speck crossing a clear row inks.
CLEAR_SHARE = 0.05
#: The share of a strip's pixel rows a column of ink must fill to be a
#: rule running down through it.
RULE_SHARE = 0.7
#: The fewest rules crossing a row of cells: a 15x15 grid's has 16, less
#: those its blocks join.
MIN_RULES = 8
#: How deep, in pitches between the rules crossing it, a grid's last row of
#: cells is, with the foot frame under it.
ROW_DEPTH = (0.75, 1.5)
#: The least pitch, as a share of the grid's width: a 27x27 grid's.
MIN_PITCH = 0.03


def rule_runs(ink):
    """[(x0, x1)] of each run of columns of a strip of ink that fill
    RULE_SHARE of its rows: the vertical rules (and blocks) crossing it."""
    import numpy as np
    full = np.concatenate(([False], ink.mean(axis=0) >= RULE_SHARE, [False]))
    edges = np.flatnonzero(full[1:] != full[:-1])
    return list(zip(edges[::2].tolist(), edges[1::2].tolist()))


def cells_under(ink, foot):
    """Whether the strip of `ink` under row `foot` is a row of cells:
    MIN_RULES rules cross it, and it is as deep as the pitch between them.
    A clue line touching the grid has no rules crossing it, or is shallower."""
    import numpy as np
    runs = rule_runs(ink[foot + 1:])
    if len(runs) < MIN_RULES:
        return False
    gaps = [g for g in np.diff([a for a, _ in runs]) if g >= MIN_PITCH * ink.shape[1]]
    if not gaps:
        return False
    pitch = float(np.median(gaps))
    return ROW_DEPTH[0] * pitch <= ink.shape[0] - foot - 1 <= ROW_DEPTH[1] * pitch


def footed(img, box):
    """`box` ending at the grid's foot frame, the lowest row in its bottom
    FOOT_INSET that ink covers FRAME_SHARE of: "ACROSS" printed touching the
    grid joins its ink, and the box would end under the first clue line,
    which every clue crop then loses. Unchanged when no row is a frame, or
    the strip under it is the grid's last row of cells (its own foot frame
    too faint or turned to fill FRAME_SHARE of any one row)."""
    import numpy as np
    if box is None:
        return None
    gray = np.asarray(img.crop(box).convert("L"), dtype=np.uint8)
    ink = gray < trove_grid.otsu(gray)
    rows = ink.mean(axis=1)
    reach = int(FOOT_INSET * len(rows))
    foot = next((k for k in range(len(rows) - 1, len(rows) - 1 - reach, -1) if rows[k] >= FRAME_SHARE), None)
    if foot is None or foot == len(rows) - 1 or cells_under(ink, foot):
        return box
    trimmed = (box[0], box[1], box[2], box[1] + foot + 1)
    return trimmed if shaped_on(img, trimmed) else box


def starts_under(img, box, top):
    """Whether the ink of `box`, cut at `top` (its title's foot), starts
    within TITLE_OVERLAP over it: the grid's top frame reaching into the
    title's box, not ink running down through the title. A row within
    TITLE_OVERLAP either side of `top` that only a fold or a speck crosses
    (CLEAR_SHARE of it inked), with a row as wide as a frame (FRAME_SHARE)
    under it there, parts the title from the grid whatever runs down
    through both (a fold in the paper, No 54 of 1930-04-04; a title's
    descender over a frame 2px under its foot, Gale's 1987-01-07)."""
    import numpy as np
    if box[1] > top + 2:
        return True
    band = (box[0], max(0, top - TITLE_OVERLAP), box[2], top + 1)
    above = ink_box(img.crop(band))
    if above is None or above[1] > 0:
        return True
    gray = np.asarray(img.crop((band[0], band[1], box[2], box[3])).convert("L"), dtype=np.uint8)
    rows = (gray < trove_grid.otsu(gray))[: top + TITLE_OVERLAP + 1 - band[1]].mean(axis=1)
    return any(rows[k] <= CLEAR_SHARE and rows[k + 1:].max() >= FRAME_SHARE / 2 for k in range(len(rows) - 1))


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


#: How far right of the grid a clue line under it may end when it starts
#: well inside the grid's width (a skewed page's long line overhangs the
#: grid): the reach of the crop the RapidOCR readers read (rapid_lines()).
#: A word starting nearer the grid's edge than ACROSS_GUTTER is held to the
#: window's right edge, so a speck in the margin beside it joins no clue.
RIGHT_REACH = 30


def windows(grid, third=None, margin=40, above=None, left=None, split=None, lead=None):
    """[(x0, x1, right edge, top)] of each clue column: a word whose left edge
    is in [x0, x1), right edge at most the right edge and top at least the
    top is in it. The two columns under the grid, and with `third`, (width,
    top), a column that wide right of the grid from `top` down. With `lead`,
    (x0, top, split), a column of the words starting from x0 to `split` (by
    the grid's left edge) and ending by the grid's edge, from `top` (its
    title's foot) down, comes first, and the column under the grid starts at
    `split` (lead_column(): the 1983-86 FT). The left
    column starts `margin` left of the grid (the Times outdents its numbers).
    With `above`, (top, gutter, right), the two columns are over the grid
    instead, from `top` down, split at the gutter, the right one ending at
    `right` (it may overhang the grid). With `left`, (x0, gutter), they are
    left of the grid from x0, split at the gutter, from LEFT_RISE over the
    grid's top down. Under the grid, the columns split at `split`
    (under_gutter()), by default the grid's middle."""
    gx0, gy0, gx1, gy1 = grid
    if left:
        x0, split = left
        return [(x0, split, split, gy0 - LEFT_RISE), (split, gx0 - 5, gx0 - 5, gy0 - LEFT_RISE)]
    if above:
        top, split, right = above
        return [(gx0 - margin, split, split, top), (split, right, right, top)]
    mid = gx0 + (gx1 - gx0) / 2 - 10 if split is None else split
    out = [(gx0 - margin, mid, gx1 + 15, gy1 - 5), (mid, gx1 + 15, gx1 + 15, gy1 - 5)]
    if lead:
        x0, top, edge = lead
        out = [(x0, edge, max(edge, gx0 - 5), top), (edge,) + out[0][1:]] + out[1:]
    if third:
        out.append((gx1 + 15, gx1 + 15 + third[0], gx1 + 15 + third[0], third[1]))
    return out


#: Where a clue starts inside a recogniser's line: its number ("12", "l4",
#: "I6", "18:") and a capital.
NEXT_CLUE = re.compile(r"(?<=\s)(?:\d{1,2}|[IlJ|!]\d|\d[IlsSoO])\W{0,2}\s*[A-Z\"'\u2018\u201c]")
#: How far, in pixels, from a gutter a clue's number in a line read across
#: it may be placed by its share of the line's characters.
SPLIT_SLACK = 80


def split_across(ws, gutters, height=None):
    """`ws` with each word read across a gutter (RapidOCR reads two
    columns' rows as one line where the gutter is narrow: "11 Scandinavian
    has no right to 12 Sympathetic type") cut at the clue number placed
    nearest that gutter, the halves either side of it. A line with no clue
    number near the gutter (a notice printed across both) stays whole. A
    word taller than `height` (a line's) spans two rows set at different
    heights: each half is given that height about its middle, so the line
    printed under either half is not read as a second copy of it."""
    out = []
    for w in ws:
        if height and w[3] - w[1] > height:
            mid = (w[1] + w[3]) / 2
            tall = (w[0], mid - height / 2, w[2], mid + height / 2, w[4])
        else:
            tall = w
        for x in gutters:
            if not (w[0] < x and w[2] > x + ACROSS_GUTTER):
                continue
            text, width = w[4], w[2] - w[0]
            at = [(abs(w[0] + width * m.start() / len(text) - x), m.start()) for m in NEXT_CLUE.finditer(text)]
            near = min((a for a in at if a[0] <= SPLIT_SLACK), default=None)
            if near is None:
                if x - w[0] <= ACROSS_GUTTER and w[2] - x > x - w[0]:
                    # Starting just left of the gutter and lying mostly right
                    # of it: a skewed page's right-column line, its left edge
                    # drifted over the straight gutter.
                    w, tall = (x,) + w[1:], (x,) + tall[1:]
                continue
            out.append((w[0], tall[1], x - 1, tall[3], text[:near[1]].rstrip()))
            w = tall = (x, tall[1], w[2], tall[3], text[near[1]:])
        out.append(w)
    return out


def columns(lines, grid, third=None, margin=40, above=None, left=None, split=None, lead=None):
    """The clue columns under the grid (and with `third`, right of it; with
    `above`, over it; with `left`, left of it; with `lead`, first one left of
    it; see windows()): [[(y0, y1, x0,
    x1, text) per line] per column, left to right], each cut where the clues
    stop."""
    gx0, gy0, gx1, gy1 = grid
    bottom = gy0 - 3 if above else left_bottom(grid) if left else gy1 + 1.8 * (gx1 - gx0)
    wins = windows(grid, third, margin, above, left, split, lead)
    reach = gx1 + RIGHT_REACH if above is None and not left else None
    cols = [[] for _ in wins]
    heights = sorted(w[3] - w[1] for ws in lines for w in ws)
    height = heights[len(heights) // 2] if heights else None
    for ws in lines:
        ws = split_across(ws, [w[1] for w in wins[:-1]], height)
        for side, (x0, x1, right, top) in enumerate(wins):
            # The lead column's right edge is the next column's left: no
            # overhang.
            over = reach if side or not lead else None
            part = [w for w in ws if x0 <= w[0] < x1 and top <= w[1] <= bottom and (
                w[2] <= right or over and w[2] <= over and w[0] < gx1 - ACROSS_GUTTER)]
            if part:
                text = " ".join(w[4] for w in part)
                if side + 1 < len(wins) and min(w[0] for w in part) < x1 - ACROSS_GUTTER \
                        and max(w[2] for w in part) > x1 + ACROSS_GUTTER:
                    # A line printed across both columns, not a clue's ("Prize
                    # Crossword in The Times tomorrow", "The solution to the
                    # Collins Competition ..."): it ends the column like STOP.
                    text = NOTICE
                cols[side].append((min(w[1] for w in part), max(w[3] for w in part),
                                   min(w[0] for w in part), max(w[2] for w in part), text))
    out = []
    for side, col in enumerate(cols):
        col = merge_rows(col)
        kept, last = [], None
        for line in col:
            if kept and (stops(line[4]) or line[4] == NOTICE or line[0] - last > GAP):
                break
            if line[4] == NOTICE:
                continue
            if not re.search(r"[A-Za-z0-9]", line[4]):
                continue  # specks read as marks: no clue text
            heading = numbered_heading(line[4])
            if heading:
                line = line[:4] + (heading,)
            if not kept and not re.match(r"\W*(across|down)\b", line[4], re.I) and last is None:
                # The column's first line is ACROSS, DOWN or a clue: a stray
                # word the grid's numbers left is not. A column under the
                # grid after the first may open on a clue whose number was
                # lost ("Peer inside the pearly gates").
                carried = side and above is None and not left and (
                    re.match(r"[A-Z][a-z]", line[4]) and len(re.findall(r"[A-Za-z]{2,}", line[4])) >= 3
                    # The rest of the clue the last column ended in, its
                    # count not yet printed ("6 Chewing nuts with tea may"
                    # over "cause lock-jaw (7)").
                    or out and out[-1] and not COUNT_END.search(out[-1][-1][4])
                    and re.match(r"[a-z]", line[4]))
                # A clue's number 1 read as I, l, J, ! or | (tidy() reads it
                # back): "I Very late at night".
                if not re.match(r"\W*(?:\d|[IlJ!|]\s?(?=[A-Z][a-z]))", line[4]) and not carried:
                    continue
            kept.append(line)
            last = line[1]
        out.append(kept)
    return out



#: How far either side of each quarter of the grid's width, as a share of
#: it, a gutter between the 1930 Times' four clue columns may lie.
FOUR_SPAN = 0.06
#: How far under the grid, as a share of its height, the 1930 clues run.
FOUR_DEPTH = 1.2
#: The note under the 1930 clues: "The twenty-eighth crossword puzzle in
#: this series, together with the solution of puzzle No. 27, will appear".
FOUR_STOP = re.compile(r"in\s*this\s*series|will\s*appear|crossword\s*puzzle\s*in\b|solution\s*(?:of|to)\b|puzzle\s*n[o0]\b",
                       re.IGNORECASE)


#: The readers of the 1930 clues: archive.org's words and Tesseract's (tuned
#: on the 1974-99 print) read these columns as junk that outvotes the rest.
FOUR_READERS = ("ch", "en5")


def four_gutters(lines, grid):
    """The three x's between the four clue columns under a 1930 grid: where
    the fewest words (`lines`, every reading's) cross near each quarter."""
    gx0, _, gx1, gy1 = grid
    w = gx1 - gx0
    bottom = gy1 + FOUR_DEPTH * (grid[3] - grid[1])
    return [gutter(lines, (gx0, bottom, gx1, bottom), gy1, gx0 + q * w / 4 - FOUR_SPAN * w,
                   gx0 + q * w / 4 + FOUR_SPAN * w) for q in (1, 2, 3)]


def down_at(lines, grid, gutters):
    """The y of the DOWN heading over the 1930 Times' first two columns,
    the median of every reading's, or None when none read it."""
    gx0, _, _, gy1 = grid
    ys = sorted(w[1] for ws in lines for w in ws
                if gx0 - 40 <= w[0] < gutters[1] and w[1] > gy1 and heading_of(w[4]) == "DOWN")
    return ys[len(ys) // 2] if ys else None


def columns_of_four(lines, grid, gutters, down):
    """The 1930 Times' clues under its grid, as columns() returns them but
    in reading order: ACROSS runs down the first column and on down the
    second over the DOWN heading (printed across both), then DOWN under it
    in the same two columns and on down the third and fourth, which end at
    the previous solution's heading."""
    gx0, gy0, gx1, gy1 = grid
    edges = [gx0 - 40] + list(gutters) + [gx1 + RIGHT_REACH]
    bottom = gy1 + FOUR_DEPTH * (gy1 - gy0)
    heights = sorted(w[3] - w[1] for ws in lines for w in ws)
    height = heights[len(heights) // 2] if heights else None
    cols = [[] for _ in range(4)]
    # Each column ends at the first line over it that FOUR_STOP matches,
    # read whole before any cut at a gutter.
    stops = [bottom] * 4
    for ws in lines:
        if FOUR_STOP.search(" ".join(w[4] for w in ws)):
            x0, x1, y0 = min(w[0] for w in ws), max(w[2] for w in ws), min(w[1] for w in ws)
            for side in range(4):
                if x0 < edges[side + 1] and x1 > edges[side] and y0 > gy1 + 20:
                    stops[side] = min(stops[side], y0 - 2)
    for ws in lines:
        ws = cut_at_gutters(split_across(ruled_apart(ws), gutters, height), gutters)
        for side in range(4):
            part = [w for w in ws if edges[side] <= w[0] < edges[side + 1] and gy1 - 5 <= w[1] <= stops[side]]
            if part:
                cols[side].append((min(w[1] for w in part), max(w[3] for w in part),
                                   min(w[0] for w in part), max(w[2] for w in part), " ".join(w[4] for w in part)))
    kept = []
    for col in cols:
        out, last = [], None
        for line in merge_rows(col):
            if FOUR_STOP.search(line[4]) or (out and line[0] - last > GAP):
                if out:
                    break
                continue
            if heading_of(line[4]) or not re.search(r"[A-Za-z0-9]", line[4]):
                continue
            out.append(line)
            last = line[1]
        kept.append(out)
    def headed(heading, col):
        # The heading on the column's first line's box, so a box drawn
        # round the column's lines (vlm_reader.boxes) is the column's.
        return [col[0][:4] + (heading,)] + col if col else [(gx0, gy1, gx0, gy1, heading)]
    if down is None:
        return [headed("ACROSS", kept[0]), kept[1]]
    over = [[ln for ln in c if ln[0] + ln[1] < 2 * down] for c in kept[:2]]
    under = [[ln for ln in c if ln[0] + ln[1] > 2 * down] for c in kept[:2]]
    return [headed("ACROSS", over[0]), over[1], headed("DOWN", under[0]), under[1], kept[2], kept[3]]


def vlm_four(img, cols):
    """The VLM's reading of the 1930 clues: each of columns_of_four()'s
    columns (`cols`, every reading's) read on its own, in that order, the
    list headings put back where they open the first and third."""
    wins = [None] * max(len(c) for c in cols)
    parts = []
    for k, box in enumerate(vlm.boxes(img, wins, cols)):
        if k in (0, 2) and k < len(wins):
            parts.append(("ACROSS", "DOWN")[k // 2])
        if box:
            parts.append(vlm.read(vlm.crop(img, box)))
    return "\n".join(p for p in parts if p)


def cut_at_gutters(ws, gutters):
    """`ws` with each word still read across a gutter (two columns' rows
    run into one, "1WinneroftheoGanymedetothe") cut there, at the space
    nearest its share of the characters, or at that share: no notice is
    printed across the 1930 columns but the one under them (FOUR_STOP)."""
    out = []
    for w in ws:
        for x in gutters:
            if not (w[0] < x - ACROSS_GUTTER and w[2] > x + ACROSS_GUTTER) or heading_of(w[4]):
                continue
            at = round(len(w[4]) * (x - w[0]) / (w[2] - w[0]))
            spaces = [m.start() for m in re.finditer(r"\s", w[4]) if abs(m.start() - at) <= 3]
            at = min(spaces, key=lambda k: abs(k - at)) if spaces else at
            out.append((w[0], w[1], x - 1, w[3], w[4][:at].strip()))
            w = (x, w[1], w[2], w[3], w[4][at:].strip())
        out.append(w)
    return out


def ruled_apart(ws):
    """`ws` with each word read across a column rule ("22Thedesert'sone|32
    Split thisaim and") cut at the "|" the rule reads as, each piece's
    x placed by its share of the characters."""
    out = []
    for w in ws:
        parts = re.split(r"\s*\|\s*", w[4])
        if len(parts) < 2:
            out.append(w)
            continue
        width = w[2] - w[0]
        for m in re.finditer(r"[^|]+", w[4]):
            if m[0].strip():
                x0 = w[0] + width * (m.start() + len(m[0]) - len(m[0].lstrip())) / len(w[4])
                out.append((round(x0), w[1], round(w[0] + width * m.end() / len(w[4])), w[3], m[0].strip()))
    return out


#: The rarest two-letter word word_split() cuts out: "me" and "no", never
#: "ut" ("entertainmeut" is a misread, not "entertain me ut").
SHORT_RANK = 1000


def word_split(word):
    """The fewest lexicon words, commonest first on a tie, that `word` is
    run together from ("hadelevenofthese" is "had eleven of these"), or
    None. A lone letter is a word only as "a" or "I", two letters only
    within SHORT_RANK."""
    low, best = word.lower(), [None] * (len(word) + 1)
    best[0] = (0, 0.0, [])
    for i in range(1, len(word) + 1):
        for j in range(max(0, i - 20), i):
            piece = low[j:i]
            if best[j] is None or (len(piece) == 1 and piece not in "ai") or not is_word(piece) \
                    or (len(piece) == 2 and (rank(piece) or SHORT_RANK + 1) > SHORT_RANK):
                continue
            c = (best[j][0] + 1, best[j][1] + math.log(rank(piece) or 10 ** 6), best[j][2] + [word[j:i]])
            if best[i] is None or c[:2] < best[i][:2]:
                best[i] = c
    return best[-1][2] if best[-1] else None


def spaced(text):
    """A reading with the words RapidOCR ran together on the small 1930
    print ("Thesepeopleare", "isno") put apart: a run of letters the
    lexicon lacks that splits whole into its words."""
    def one(m):
        word = m[0]
        if len(word) < 4 or ocr_clues.known(word):
            return word
        parts = word_split(word)
        return " ".join(parts) if parts else word
    # A clue's number run into its first word ("25Holdsan") parts first.
    text = re.sub(r"(?m)^(\W{0,2}\d{1,2}[.,]?)(?=[A-Za-z])", r"\1 ", text)
    # A speck between two words ("flat.and", "for.misdeed"), and a quote or
    # bracket run onto the word before it ("in“The", "sire?(anag.)").
    text = re.sub(r"(?<=[a-z]{2})[.,·](?=[a-z]{2})", " ", text)
    text = re.sub(r"(?<=[A-Za-z?!])(?=[“‘(])", " ", text)
    # Half a word broken over a line end ("esta-", "blished") is no run.
    return re.sub(r"(?<![\w\-])[A-Za-z]+(?:'[a-z]+)?(?![\w\-])", lambda m: m[0] if text[:m.start()].endswith(("-\n", "- ")) else one(m), text)


def counted(text, grid):
    """A 1930 column text with each clue's count put after it from the
    scanned grid, as later papers print it, for the parse that ends a clue
    at its count: a clue starts at a line opening on a number that names a
    light of its list above the last clue's; other lines carry it on.

    A clue whose number was lost runs into the clue before it, and the
    count, being the grid's, cannot show it. So the list must name the
    grid's lights in order: a clue followed by one of a later light than
    the next (a light skipped), or by one of its own or an earlier light,
    or ending its list before the list's last light, may hold another's
    text and is dropped, its light and the skipped ones left to the other
    readings or blank. The grid's light list says where a lost number
    was: a line opening on a capital after a clue's full stop, or on a
    misread number holding the next light's ("151 Meta-" for 15), starts
    the next light's clue."""
    lights = {(n, d): len(cells) for (n, d), cells in rg.light_cells(grid).items()}
    sections = []  # [heading, [[number, lines, guessed, dropped]]]
    for line in text.splitlines():
        heading = heading_of(line)
        if heading:
            sections.append([heading, []])
            continue
        if not sections:
            continue
        section, clues = sections[-1][0].lower(), sections[-1][1]
        last = clues[-1][0] if clues else 0
        nxt = min((n for n, d in lights if d == section and n > last), default=None)
        # The number, maybe run into its first word: "25Recipient", "21.Measures".
        m = re.match(r"^\W{0,2}([\dIl|]{1,2}?)(?:[.,:;\-]\s*|\s+|(?=[A-Z\"'\u2018\u201c]))(?=\S)", line)
        m = m if m and re.search(r"\d", m[1]) else None
        read = [n for n in (ftp.readings(m[1]) if m else ()) if (n, section) in lights]
        nums = sorted(n for n in read if n > last)
        # A number read with a speck ("151", "128") holding the next light's.
        speck = re.match(r"^\W{0,2}(\d{3})\W{0,2}\s*(?=[A-Z\"'\u2018\u201c])", line)
        if nums:
            clues.append([nums[0], [line[m.end():]], False, False])
        elif read and clues:
            # A number at or before the last clue's: this list is out of
            # step with the grid here. When it is the last clue's guessed
            # number, the guess split one clue in two and this is its own.
            clues[-1][3] = True
            if clues[-1][2] and last in read:
                clues.append([last, [line[m.end():]], False, False])
            else:
                clues[-1][1].append(line)
        elif speck and nxt and str(nxt) in speck[1]:
            clues.append([nxt, [line[speck.end():]], False, False])
        elif re.match(r"\W{0,2}[A-Z]", line) and nxt and (
                re.search(r"[.!?][\"'\u2019\u201d)]?$", clues[-1][1][-1]) if clues else True):
            # A capital after a clue's full stop, or opening the list,
            # starts the next clue, its number lost ("light.. /
            # Slender-waisted."): the next light's.
            clues.append([nxt, [line.strip()], True, False])
        elif clues:
            clues[-1][1].append(line)
    out = []
    for heading, clues in sections:
        out.append(heading)
        order = sorted(n for n, d in lights if d == heading.lower())
        for k, (n, _, _, _) in enumerate(clues):
            after = [x for x in order if x > n]
            follows = clues[k + 1][0] if k + 1 < len(clues) else None
            if after[:1] != [follows] if follows else after:
                clues[k][3] = True
        # A guessed number counts on from the clue before, so a break after
        # it may lie anywhere back to the last number read: the clues
        # between are dropped with it.
        for k in range(len(clues) - 1, 0, -1):
            if clues[k][3] and clues[k][2]:
                clues[k - 1][3] = True
        out += [f"{n} " + "\n".join(lines) + f" ({lights[(n, heading.lower())]})"
                for n, lines, _, bad in clues if not bad]
    return "\n".join(out)


#: How far either side of the grid's middle, as a share of its width, the
#: gutter between the two clue columns under the grid may lie.
UNDER_SPAN = 0.1


def under_gutter(lines, grid):
    """The x between the two clue columns under the grid: where the fewest
    words (`lines`, every reading's) cross near the grid's middle. A paper's
    columns need not split at the grid's middle, and a right-hand clue
    whose number starts left of it is read into the left column's row."""
    gx0, _, gx1, gy1 = grid
    mid, span = gx0 + (gx1 - gx0) / 2 - 10, UNDER_SPAN * (gx1 - gx0)
    bottom = gy1 + 1.8 * (gx1 - gx0)
    return gutter(lines, (gx0, bottom, gx1, bottom), gy1, mid - span, mid + span)


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


def lead_column(title, grid, margin=40):
    """(x0, top) of the clue column under a title printed left of its grid
    (the 1983-86 FT: ACROSS and the first DOWN clues there, the rest in the
    two columns under the grid): the column is centred under the title and
    ends at the grid's left edge, so it starts as far left of the title's
    middle, less `margin`."""
    cx = (title[0] + title[2]) / 2
    return max(0, int(2 * cx - grid[0]) - margin), title[3]


def lead_split(lines, grid, lead, margin=40):
    """`lead` (lead_column()) with the x between it and the column under the
    grid: where the fewest words (`lines`, every reading's) under the grid
    cross, from `margin` left of the grid's edge (where that column's numbers
    start, outdented) to just inside it."""
    gx0, _, gx1, gy1 = grid
    bottom = gy1 + 1.8 * (gx1 - gx0)
    return lead + (gutter(lines, (gx0, bottom, gx1, bottom), gy1, gx0 - margin, gx0 + 10),)


def rapid_lines(img, grid, which, cache_path, third=None, margin=40, above=None, left=None, lead=None):
    """One recogniser's reading of the page under the grid (RapidOCR's, or
    Tesseract's for a TESS_MODELS reader), as djvu-style lines of one word each, in page
    coordinates; cached as JSON with the crop it read, so a reading of another
    crop is read again (a bare list kept no crop and is used as it stands)."""
    gx0, gy0, gx1, gy1 = grid
    gw = gx1 - gx0
    box = (max(0, gx0 - margin), gy1, min(img.width, gx1 + RIGHT_REACH), min(img.height, int(gy1 + 1.8 * gw)))
    if third:
        box = (box[0], min(gy1, third[1]), min(img.width, gx1 + 15 + third[0]), box[3])
    if above is not None:
        box = (max(0, gx0 - margin), max(0, int(above)), min(img.width, gx1 + OVERHANG), gy0)
    if left:
        box = (max(0, gx0 - gw - 60), max(0, gy0 - LEFT_RISE), gx0, min(img.height, int(left_bottom(grid))))
    if lead:
        box = (max(0, int(lead[0])), max(0, int(lead[1])), box[2], box[3])
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if isinstance(cached, list):
            return [[tuple(w)] for w in cached]
        if tuple(cached["box"]) == box:
            return [[tuple(w)] for w in cached["words"]]
    crop = img.crop(box)
    if lead:
        # The grid inside the crop is blanked: its numbers are no clue's.
        crop.paste("white", (gx0 - box[0], gy0 - box[1], gx1 - box[0], gy1 - box[1]))
    words = [(x0 + box[0], y0 + box[1], x1 + box[0], y1 + box[1], t)
             for x0, y0, x1, y1, t in read_words(crop, which)]
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
    lines = []
    for line in text.splitlines():
        # A heading read onto the line of its first clue ("Down i Beginning",
        # "ACROSS 1 Fish"), or after the last clue of the list before
        # ("chance (5) DOWN"), is a line of its own; one inside a line,
        # another column's read across ("on the DOWN board"), is no word.
        m = HEADING_LEAD.match(line)
        if m:
            lines += [m[1].upper(), (m[2] if m[2].isdigit() else "1") + " " + line[m.end():]]
            continue
        m = HEADING_TAIL.search(line)
        tail = [m[1]] if m else []
        line = line[:m.start()] if m else line
        lines += [re.sub(r"(?<=\S)\s+(?:ACROSS|DOWN)(?=\s+\S)", "", line)] + tail
    for line in lines:
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
            # A clue's number with a speck run into its first word: "1'In the",
            # "1.Associate's", "l^Finished", ". 1. Maltreat", "-1--He said".
            line = re.sub(r"^(?:[^\w\s(]|_){1,3}\s?(?=[Il]?\d{1,2}(?:[^\w\s(]|_){0,3}\s?[A-Z\"'])", "", line)
            line = re.sub(r"^[Il]?(\d{1,2})(?:[^\w\s(]|_){1,3}\s?(?=[A-Z\"'])", r"\1 ", line)
            line = re.sub(r"^[Il](\d)?(?:[^\w\s(]|_){1,3}\s?(?=[A-Z][a-z])", lambda m: f"1{m[1] or ''} ", line)
            # A 1 read as I, J, ! or | run into a capitalised word: "IPheasant",
            # "JTool", "!What makes".
            line = re.sub(r"^[IlJ!|](?=[A-Z][a-z])", "1 ", line)
            # A number read as specks alone: ") With", "• £■ So"; the grid
            # places the clue ("?" below).
            line = re.sub(r"^(?:[^\w\s(\"'][^\w\s(]{0,2}\s?){1,3}(?=[A-Z][a-z])", "", line)
        line = re.sub(r"^(\d{1,2})(?=[A-Z][a-z]|[A-Z]\s)", r"\1 ", line)
        # "15 Adanger out east": a clue's opening "A" run into the next word,
        # unless the whole is a misspelling of a commoner word ("Arived").
        # A word the lexicon lacks (is_word's closed list: "whore", "togo")
        # has no rank, and ranks below every word it has.
        glued = re.match(r"^(\d{1,2}(?:,\s?\d{1,2})*\s+)A([a-z]{3,})\b", line)
        word = glued and glued.group(2)
        if glued and is_word(word) and not is_word("a" + word) and not any(
                (rank(e) or 10 ** 9) < (rank(word) or 10 ** 9) for e in edits("a" + word) if e != word):
            line = f"{glued.group(1)}A {line[glued.end(1) + 1:]}"
        line = re.sub(r"(?<=[a-z])\s?\(?(\d{1,2}(?:[,.\-]\d{1,2})*)[)jJ]$", r" (\1)", line)
        # Specks after a clue's count ("(8)'", "(5).·", "(5). _") end nothing.
        line = re.sub(r"(\(\s*[\dSIl,.\- ]{1,9}\))(?:[^\w(]|_){1,3}$", r"\1", line)
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
    return "\n".join(uncounted_dropped(counts_mended(out)))


#: A list's heading opening a line before its first clue's number, a 1
#: read as i, I, l or |: "Down i Beginning", "ACROSS 1 Fish".
HEADING_LEAD = re.compile(r"^\W*(ACROSS|DOWN|Across|Down)\W*\s+(\d{1,2}|[iIl|!])\W?\s+(?=[A-Z\"'])")
#: A heading in capitals closing a line after a clue's count: "(5) DOWN".
HEADING_TAIL = re.compile(r"(?<=\))\W{0,2}\s+(ACROSS|DOWN)\W*$")


#: A count torn at a clue's end: "(" read as 1, I or l ("17).", "IS).") or
#: lost, ")" read as a letter or lost ("(5X", "(8k", "(8"); both torn: "("
#: read as T, t, f or j and ")" lost ("T10"), or a lone digit between
#: "(" read as 1, I or l and ")" as j, J, l or I ("16j", "I6l").
TORN_COUNT = re.compile(r"(?<=\S)\s*(?:\(([\dS]{1,2})[A-Za-z]?|(?<=\s)[1Il]([\dS]{1,2})\)"
                        r"|(?<=\s)[Ttfj]([\dS]{1,2})\)?|(?<=\s)([1Il][\dS])[jJlI])\W{0,2}$")


def counts_mended(lines):
    """`lines` with the torn count that ends a clue (its next line a clue's
    number, a heading or the column's end) read as a count: "writer 17)."
    is "writer (7)", for a count of 17 could not go in a 15-square grid,
    and "(8" before "4 American city" is (8). A whole count is left alone."""
    out = list(lines)
    for k, line in enumerate(out):
        nxt = out[k + 1] if k + 1 < len(out) else None
        if nxt is not None and not (re.match(r"\d{1,2}\s+\S", nxt) or heading_of(nxt)):
            continue
        if re.search(r"\(\s*[\dSIl,.\- ]{1,9}\)\W{0,2}$", line):
            continue
        m = TORN_COUNT.search(line)
        if not m:
            if re.fullmatch(r"\W{0,2}(?:[A-Za-z]?\d{1,2}|\d[A-Za-z])\)\W{0,2}", line) and not (
                    k and out[k - 1].count("(") > out[k - 1].count(")")):
                # A line of nothing but a bracket and a digit or so ("U0).")
                # is the clue's count, unread: the grid gives it; after a
                # count left open ("(5-"), it is that count's end.
                out[k] = "(?)"
            continue
        if m[2] and m[2].isdigit() and int("1" + m[2]) <= 15:
            continue  # "12)": a count of 12 lost its bracket, or of 2 its "(": unsure
        if m[4] and m[4].isdigit() and int(m[4]) <= 15:
            continue  # "12l": a count of 12 or of 2: unsure
        out[k] = line[:m.start()] + f" ({m[1] or m[2] or m[3] or m[4][1:]})"
    return out


#: A count closing a line, its bracket maybe torn: "(8)", "(8", "(3,7)".
COUNT_END = re.compile(r"\(\s*[\dSIl,.\- ]{1,9}\)?\W{0,2}$")


def uncounted_dropped(lines):
    """`lines` (tidy()'s) without text that is no clue: after a count, lines
    with no count of their own that run into the next clue's number, a
    heading or the column's end ("Prize Crossword in The Times tomorrow",
    a notice printed across the columns). A clue whose number was lost
    ("? Holds fast (5)") still ends on its count."""
    out, k = [], 0
    while k < len(lines):
        if not lines[k].startswith("? "):
            out.append(lines[k])
            k += 1
            continue
        end = k
        while end < len(lines) and not COUNT_END.search(lines[end]) and (
                end == k or not (re.match(r"\d{1,2}\b", lines[end]) or heading_of(lines[end])
                                 or lines[end].startswith("? "))):
            end += 1
        if end < len(lines) and COUNT_END.search(lines[end]) and not (
                end > k and (re.match(r"\d{1,2}\b", lines[end]) or heading_of(lines[end]))):
            out.extend(lines[k:end + 1])
            k = end + 1
        else:
            k = end
    return out


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
        # The row's band is all its pieces': "Am-" read apart from
        # "understood" and both above "1 Historian" are one printed row.
        if rows and min(p[0] for p in rows[-1]) <= mid <= max(p[1] for p in rows[-1]):
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

def build(number, day, grid, how, laid, edition, leaf, series=SERIES, name=None, url=None):
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
        "source": {"url": url or PAGE_URL.format(edition=edition, leaf=leaf),
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
             for item in sorted(cache.iterdir())
             if any(p.item.match(item.name) for p in (paper or TIMES, *(paper or TIMES).also))]
    out = []
    for k in range(max(map(len, years), default=0)):
        out += [y[k] for y in years if k < len(y)]
    return out


def scan(d):
    """{"puzzles": [...], "solutions": [...]} for one edition directory: each
    heading's number, leaf and box. Read here, in one of
    tools/ocr_remote.py's local slots (its title OCR on the desktop)."""
    import ocr_remote
    with ocr_remote.local_slot():
        return _scan(d)


def _scan(d):
    pages = json.loads((d / "pages.json").read_text())
    leaves = {p["leaf"] for p in pages.get("crossword_pages", ())
              if (d / f"leaf_{p['leaf']:04d}.jpg").exists()}
    found = {"date": pages["date"], "item": pages["item"], "puzzles": [], "solutions": []}
    if not leaves:
        return found
    paper = paper_of(d)
    text = leaf_lines(d / "djvu.xml.gz", leaves)
    for leaf in sorted(leaves):
        if leaf not in text:
            titles, sols = ocr_headings(page(d, leaf), paper, f"{d.parent.name}_{d.name}_{leaf}")
        else:
            titles, sols = paper.headings(text[leaf])
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
#: (3%) is not a grid; grids fill 35-45%, but one with stippled grey blocks
#: thresholds to specks and fills 13% (the 1980 Times, 15,200).
GRID_FILL = 0.1
#: How far over and under a grid its title is looked for when archive.org's
#: text has none: the 1995 Times prints it 250px over the grid.
TITLE_REACH = 300


def grids_on(img, step=2, shaped=grid_shaped):
    """[box] of each grid-shaped patch of ink on a page (`shaped`, at least
    GRID_FILL of its box inked), found on a 1/step subsample."""
    import cv2
    import numpy as np
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    ink = (gray < trove_grid.otsu(gray))[::step, ::step].astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=4)
    out = []
    for x, y, w, h, area in stats[1:].tolist():
        box = (x * step, y * step, (x + w) * step, (y + h) * step)
        if shaped(box) and area >= GRID_FILL * w * h:
            out.append(box)
    return out


def title_bands(img, grid):
    """The crops a grid's title is read in, in turn: over and under it,
    TITLE_REACH deep, half the grid's width wider each side (the Guardian's
    title runs left of its grid); then a grid's width left of it, from its
    top down TITLE_REACH (the 1983-86 FT's "F.T. CROSSWORD" over "PUZZLE
    No. 5,607" heads the clue column beside the grid)."""
    x0, y0, x1, y1 = grid
    xa, xb = max(0, x0 - (x1 - x0) // 2), min(img.width, x1 + (x1 - x0) // 2)
    return ((xa, max(0, y0 - TITLE_REACH), xb, y0), (xa, y1, xb, min(img.height, y1 + TITLE_REACH)),
            (max(0, x0 - (x1 - x0)), y0, x0, min(img.height, y0 + TITLE_REACH)))


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


#: Heading words as our readers misread them on a Gale page ("Cressword",
#: "Solotion"), read as the word.
OCR_MISREADS = ((re.compile(r"cr[eo0]s{1,2}w[o0]rd", re.IGNORECASE), "Crossword"),
                (re.compile(r"s[o0]l[uo0]ti[o0]n", re.IGNORECASE), "Solution"))
#: A word (RapidOCR's: a phrase) a heading opens on: a line our readers ran a clue column into
#: ("27 Order observed in 16 con- Solution to Puzzle No 17,246") is read
#: from each.
HEADING_START = re.compile(r"\W*(?:the|solution)\b", re.IGNORECASE)


def mend_misreads(text):
    for pattern, word in OCR_MISREADS:
        text = pattern.sub(word, text)
    return text


#: A word our readers read where a solution heading starts ("Solution", or a
#: RapidOCR phrase holding it: "grass Solution to Puzzle No 17,245").
SOLUTION_WORD = re.compile(r"\bsolution\b", re.IGNORECASE)
#: A solution heading's band, re-read whole by every reader: from just left of
#: its "Solution" word (or its grid's left edge) this far right, and this far
#: over and under the word (over the grid, this far up from its top), in
#: pixels at SCAN_WIDTH. The heading is set over its own solution grid, the
#: clue column left of it (a whole-page read runs the two together, or reads
#: neither), the next column past it; two side by side (a Saturday's) are
#: read apart, each from its own word or grid.
SOLUTION_BAND = (30, 420, 25, 70)
#: The width of a solution grid at SCAN_WIDTH (the puzzle's own is 680-770).
SOLUTION_GRID = (200, 480)


def solution_shaped(img):
    """grids_on's `shaped` for a solution grid on page `img`."""
    k = SCAN_WIDTH / img.width

    def shaped(box):
        w, h = (box[2] - box[0]) * k, (box[3] - box[1]) * k
        return SOLUTION_GRID[0] <= w <= SOLUTION_GRID[1] and 0.85 <= w / max(h, 1) <= 1.18
    return shaped


def solution_bands(img, words):
    """The bands (x0, y0, x1, y1) a page's solution headings are re-read in:
    one per "Solution" word any reader read (SOLUTION_WORD), and one over
    each solution grid's top (grids_on), where no reader's whole-page pass
    read the heading at all (Gale's 1987-01-17); those of one heading once."""
    k = img.width / SCAN_WIDTH
    left, right, pad, over = (int(v * k) for v in SOLUTION_BAND)
    starts = []
    for x0, y0, x1, y1, text in words:
        m = SOLUTION_WORD.search(text)
        if m:
            starts.append((x0 + (x1 - x0) * m.start() // max(len(text), 1), y0 - pad, y1 + pad))
    starts += [(g[0], g[1] - over, g[1] + pad // 5) for g in grids_on(img, shaped=solution_shaped(img))]
    bands = []
    for x, top, foot in starts:
        band = (max(0, x - left), max(0, top), min(img.width, x + right), min(img.height, foot))
        if not any(abs(band[0] - b[0]) < 2 * left and min(band[3], b[3]) > max(band[1], b[1]) for b in bands):
            bands.append(band)
    return bands


def row_lines(words):
    """printed_lines() with each row's lines joined: a heading read with a
    wide gap between its words ("Solution tn Puzzle" ... "No 17,245") is one
    line."""
    rows = []
    for ln in printed_lines(words):
        row = next((r for r in rows if r[0][1] <= (ln[0][1] + ln[0][3]) / 2 <= r[0][3]), None)
        if row is None:
            rows.append(list(ln))
        else:
            row.extend(ln)
            row.sort()
    return rows


def ocr_headings(img, paper, key):
    """([(number, box, setter, readers)], [(number, box)]) of the titles and
    solution headings on a page archive.org has no text for (a Gale page:
    one article, so its whole ink is read): each title's number at least
    half our readers read on the page, with the box and setter of the
    first; a title fewer read stands when it is the number after a solution
    heading read on the page (the day before's, printed under the clues).
    A solution heading is read again in its own band (solution_bands) by
    every reader, and stands where at least half read its number there: a
    whole-page read misses its small type or runs it into the clue column."""
    box = img.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()
    if box is None:
        return [], []
    titles, page_words = {}, []
    for which in READERS:
        path = CROPS / "titles" / f"{key}_page.{reader_key(which)}.json"
        words = [(*w[:4], mend_misreads(w[4])) for w in band_words(img, box, which, path)]
        page_words += words
        lines = printed_lines(words)
        lines += [ln[k:] for ln in lines for k in range(1, len(ln)) if HEADING_START.match(ln[k][4])]
        for n, b, setter in paper.headings(lines)[0]:
            if which not in (r[0] for r in titles.get(n, ())):
                titles.setdefault(n, []).append((which, b, setter))
    sols = {}
    for band in solution_bands(img, page_words):
        for which in READERS:
            path = CROPS / "titles" / f"{key}_{'_'.join(map(str, band))}.{reader_key(which)}.json"
            words = [(*w[:4], mend_misreads(w[4])) for w in band_words(img, band, which, path)]
            lines = row_lines(words)
            lines += [ln[k:] for ln in lines for k in range(1, len(ln)) if HEADING_START.match(ln[k][4])]
            for n, b in {n: b for n, b in reversed(paper.headings(lines)[1])}.items():
                if which not in (r[0] for r in sols.get(n, ())):
                    sols.setdefault(n, []).append((which, b))
    least = len(READERS) / 2
    sols = {n: reads for n, reads in sols.items() if len(reads) >= least}
    return ([(n, reads[0][1], reads[0][2], [r[0] for r in reads]) for n, reads in titles.items()
             if len(reads) >= least or n - 1 in sols],
            [(n, reads[0][1]) for n, reads in sols.items()])


def page(d, leaf):
    """Leaf `leaf`'s scan, shrunk by its paper's `shrink` (the JPEG decoded
    at that scale, so a 13663px 1930 page costs what a 3296px one does)."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    img = Image.open(d / f"leaf_{leaf:04d}.jpg")
    shrink = paper_of(d).shrink
    if shrink > 1:
        img.draft(img.mode, (img.width // shrink, img.height // shrink))
        img = img.convert("L")
    return img


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
#: "No. 8,650 Set by DANTE" in the 1990s, "F.T. CROSSWORD" over "PUZZLE
#: No. 5,613" in the 1980s, "CROSSWORD PUZZLE No. 2,766" on one line in
#: the 1970s.
FT_TITLE = re.compile(r"^\W*(?:[a-z.]+\s+){0,2}cross\s?word(?:\s+puzzle)?\b\W*(.*)$", re.IGNORECASE)
FT_NUMBER = re.compile(r"^\W*(?:puzzle\s+)?no\W{0,2}\s*(\d[,.?^]?\d{3})\b(.*)$", re.IGNORECASE)
#: How many leading words of a line ft_headings drops to find a numbered
#: title: the OCR runs the next column's last word into the title's line
#: ("~nTupblfih“parkCtT- CROSSWORD PUZZLE NO. 1,652").
FT_LEAD_JUNK = 2
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
        # The whole line, else (numbered only) the line less its first
        # FT_LEAD_JUNK words.
        for k in range(min(FT_LEAD_JUNK, len(ws) - 1) + 1):
            line = ws[k:] if k else ws
            m = FT_TITLE.match(" ".join(w[4] for w in line))
            # Words after "CROSSWORD" and no number: prose ("No crossword
            # appears in today's edition"), not a title over its number.
            prose = m and re.search(r"[a-z]", m.group(1), re.IGNORECASE) and not re.search(r"\d", m.group(1))
            num, under = numbered(line, m.group(1)) if m and not prose else (None, line)
            if num:
                ws = line
                break
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
    """A number as OCR reads it, its leading 1 read as T, I, i or l mended."""
    return number_of(re.sub(r"^[TIil]", "1", text.strip()))


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


#: The Times crossword's first day, No 1 (a Saturday); it ran six days a
#: week, none on a day the paper was not printed.
TIMES_1930_FIRST = datetime.date(1930, 2, 1)
TIMES_1930_CLOSED = {datetime.date(1930, 4, 18)}  # Good Friday
#: How far a 1930 title's 1-3 digit number may stray from its date's: a
#: misread digit ("200" for 209) lands further off.
TIMES_1930_SLACK = 3


def times1930_expected_number(day):
    n, d = 1, TIMES_1930_FIRST
    while d < day:
        d += datetime.timedelta(days=1)
        n += d.weekday() != 6 and d not in TIMES_1930_CLOSED and (d.month, d.day) != (12, 25)
    return n


#: "THE TIMES CROSSWORD PUZZLE No. 27"; the OCR often reads the number apart
#: from the words, or not at all.
TITLE_1930 = re.compile(r"^\W*(?:\S{1,8}\s+){0,3}?crossword\W{0,3}\s*puzzle\W{0,3}\s*n[o0]\W{0,3}\s*(\d{1,3})(?!\d)",
                        re.IGNORECASE)
TITLE_1930_BARE = re.compile(r"^\W*(?:\S{1,8}\s+){0,3}?crossword\W{0,3}\s*puzzle\W{0,3}\s*(?:n[o0]\W{0,3})?\s*\S{0,4}$",
                             re.IGNORECASE)
#: "SOLUTION OF PUZZLE No. 26", under the clues.
SOLUTION_1930 = re.compile(r"^\W*(?:\S{1,2}\s+)?solution\s+(?:of|to)\s+puzzle\s+n[o0]\W{0,3}\s*(\d{1,3})(?!\d)", re.IGNORECASE)


def times1930_headings(lines):
    """([(number, box, None)], [(number, box)]) of the 1930 titles and
    solution headings in `lines`. A title whose number was not read takes
    the number after the page's solution heading's; with none, the page
    has no title read here (ocr_titles() reads it)."""
    titles, sols, bare = [], [], []
    for ws in lines:
        text = " ".join(w[4] for w in ws)
        m = SOLUTION_1930.match(text)
        if m:
            sols.append((int(m[1]), box_of(ws)))
            continue
        m = TITLE_1930.match(text)
        if m:
            titles.append((int(m[1]), box_of(ws), None))
        elif TITLE_1930_BARE.match(text):
            bare.append(box_of(ws))
    if not titles and bare and len(sols) == 1:
        titles = [(sols[0][0] + 1, bare[0], None)]
    return titles, sols


class Paper:
    """One newspaper's run of archive.org items: where its editions are, how
    its titles and solution headings read, the number its date implies, and
    the series its puzzles file as."""

    def __init__(self, key, series, item, name, expected, third=0, solution_above=False, margin=40,
                 clues_above=False, shrink=1, slack=None, four=False, also=()):
        self.key, self.series, self.item, self.name, self.expected = key, series, item, name, expected
        #: The width of a clue column right of the grid (0: none), whether
        #: the solution grid is printed above its heading, how far left
        #: of the grid the clue numbers may start, and whether the clues are
        #: printed over the grid, the title heading the left column.
        self.third, self.solution_above, self.margin = third, solution_above, margin
        self.clues_above = clues_above
        #: How many times the scans' SCAN_WIDTH its pages are scanned at
        #: (page() and leaf_lines() shrink them to it), and how far a
        #: title's number may stray from the one its date implies.
        self.shrink, self.slack = shrink, NUMBER_SLACK if slack is None else slack
        #: Four clue columns under the grid and no counts printed (the 1930
        #: Times): columns_of_four() reads them, the grid gives the counts.
        self.four = four
        #: Papers of the same series in other items, whose editions a run of
        #: this one reads too.
        self.also = also

    def headings(self, lines):
        if self.key == "times1930":
            return times1930_headings(lines)
        if self.key == "ft":
            return ft_headings(lines)
        if self.key == "guardian":
            return guardian_headings(lines)
        if self.key == "telegraph":
            return telegraph_headings(lines)
        return ([(n, box, None) for n, box in headings(lines, TITLE)], headings(lines, SOLUTION))


#: The 1930 Times: archive.org's pub_times, one item an issue
#: ("per_times_the-times_1930-03-04_45452"), each page scanned 13663px wide.
TIMES_1930 = Paper("times1930", SERIES, re.compile(r"per_times_the-times_(19\d\d)-\d\d-\d\d_\d+$"),
                   "Times crossword puzzle No {:,}", times1930_expected_number, margin=15, shrink=4,
                   slack=TIMES_1930_SLACK, four=True)
TIMES = Paper("times", SERIES, ITEM, "Times cryptic crossword No {:,}", expected_number, also=(TIMES_1930,))
FT = Paper("ft", "ftcryptic", re.compile(r"FinancialTimes(19\d\d)UKEnglish$"),
           "Financial Times cryptic crossword No {:,}", ft_expected_number)
GUARDIAN = Paper("guardian", "cryptic", re.compile(r"TheGuardian(19\d\d)UKEnglish$"),
                 "Cryptic crossword No {:,}", guardian_expected_number, third=GUARDIAN_THIRD, solution_above=True,
                 margin=15)
TELEGRAPH = Paper("telegraph", "telegraph", re.compile(r"(?:TheDaily|Sunday)Telegraph(19\d\d)UKEnglish$"),
                  "Telegraph cryptic crossword No {:,}", telegraph_expected_number, margin=15, clues_above=True)
#: The Times pages Paul saves from Gale (tools/gale_inbox.py), under a ledger
#: of their own: a run of them, minutes after a page lands, never waits on the
#: full pass holding filed.jsonl for an hour-long slice, and the full pass's
#: Times runs never read them.
GALE = Paper("gale", SERIES, GALE_ITEM, "Times cryptic crossword No {:,}", expected_number)
#: The archive.org papers (coverage counts each series once, off these).
PAPERS = {p.key: p for p in (TIMES, FT, GUARDIAN, TELEGRAPH)}
#: Every --paper a run can read: each ledger's editions.
FILERS = {**PAPERS, GALE.key: GALE}
#: Each run's ledger in the cache, filed.jsonl unless named here. Kept off
#: Paper, whose code is in the scan key (scan_key).
LEDGER_NAMES = {GALE.key: downloads.GALE_LEDGER.name}
#: The runs whose never-read editions are read latest laid out first (pages
#: saved by hand, whose saver waits to see them filed), not a year at a time.
NEWEST_FIRST = {GALE.key}


def paper_of(d):
    """The Paper an edition directory's item belongs to."""
    return next((p for p in (*FILERS.values(), TIMES_1930) if p.item.match(Path(d).parent.name)), TIMES)


def filer_of(rel):
    """The FILERS paper whose run reads edition `rel` ("<item>/<edition>"),
    or None."""
    item = rel.split("/")[0]
    return next((p for p in FILERS.values() if any(q.item.match(item) for q in (p, *p.also))), None)


def issues_between(a, b):
    """How many issues (six a week, none on Sunday) follow day `a` up to and
    including the later day `b`."""
    weeks, rest = divmod((b - a).days, 7)
    return weeks * 6 + sum((a + datetime.timedelta(days=i)).weekday() != 6 for i in range(1, rest + 1))


#: {path: ((mtime_ns, size), date or None)} of each puzzle file held_dates
#: has read: a file is read again only when its stat moves, so a worker's
#: every title costs a stat of the series, not a parse of it.
_DATES = {}


def held_dates(series):
    """{number: date} of every dated puzzle filed in a series."""
    out = {}
    for p in (ROOT / "puzzles" / series).glob("*/*.json"):
        st = p.stat()
        stamp = (st.st_mtime_ns, st.st_size)
        seen = _DATES.get(p)
        if seen is None or seen[0] != stamp:
            date = json.loads(p.read_text()).get("date")
            seen = _DATES[p] = (stamp, date and datetime.date.fromisoformat(date[:10]))
        if seen[1]:
            out[int(p.stem.split("-")[1])] = seen[1]
    return out


#: Where the Canberra Times reprints of London Times puzzles are cached:
#: Trove's text of each article (tools/fetch_trove.py), our readers' text of
#: its clue columns beside the zones (tools/file_trove_puzzles.page_readings),
#: and the London number of each (tools/canberra_london_numbers.py).
TROVE = ftp.CACHE
#: The series a Canberra reprint is a copy of.
REPRINTED = "times"
#: {London number: [article dirs]}, read once a process.
_REPRINTS = {}


def reprint_files(number, trove=None):
    """[Path] each cached text of the Canberra reprints of London Times
    `number`: Trove's article text and each reader's of its clue columns.
    Only what is cached: nothing is read or fetched here."""
    trove = Path(trove or TROVE)
    if trove not in _REPRINTS:
        import canberra_london_numbers
        by = {}
        for aid, row in canberra_london_numbers.load(trove / "london_numbers.json").items():
            if row.get("number"):
                by.setdefault(int(row["number"]), []).append(trove / aid)
        _REPRINTS[trove] = by
    out = []
    for d in sorted(_REPRINTS[trove].get(int(number), ())):
        out += [p for p in [d / "ocr.txt"] + sorted((ftp.clue_zones(d) / d.name).glob("read.*.txt")) if p.is_file()]
    return out


def reprint_text(text):
    """A reprint reading as a column reading sets it out: its two lists
    alone (the article's page text, solution note and next puzzle cut off),
    one clue a line as "<number> <text> (<count>)", each number as its list's
    order reads it ("I They're" is clue 1, no lost word "I") and a line-end
    hyphen kept at a line end. A list that does not parse is kept cut to
    its lists; None when there are none."""
    parsed, _ = parse(text)
    if parsed is None:
        secs = ftp.sections(tidy(text))
        return None if secs is None else f"ACROSS\n{secs['across']}\nDOWN\n{secs['down']}\n"
    parsed, _ = ftp.renumber(parsed)
    out = []
    for direction in ("across", "down"):
        out.append(direction.upper())
        for c in parsed[direction]:
            head = ", ".join(str(min(t)) for t in c["tokens"] if t) if c["tokens"] and c["tokens"][0] else ""
            words = re.sub(r"(?<=[A-Za-z])- (?=[A-Za-z])", "-\n", c["text"].strip())
            count = f" ({next(iter(c['enums']))})" if len(c.get("enums") or ()) == 1 else ""
            out.append(f"{head} {words}{count}".strip())
    return "\n".join(out) + "\n"


def book_reprint_files(number, series, root=None):
    """[Path] each book leaf's reading of `series`-`number`: a page of an
    anthology (a Times crossword book) that reprints it, kept by
    tools/acquire_book.py in place of a book-N copy (book_queue.save_reprint)."""
    import book_queue
    return book_queue.reprint_readings(series_meta.puzzle_id(series, number), root)


def reprint_readings(number, series=REPRINTED):
    """{reading name: text} of the reprints of `number` in `series`
    (reprint_text): the Canberra Times's of a Times puzzle and any book's.
    Each is one more copy of the same print, its readings voters beside the
    scan's own (the London scan and the Canberra one misread apart). {} for
    a number no reprint is held of."""
    out = {}
    for p in reprint_files(number) if series == REPRINTED else ():
        text = reprint_text(p.read_text(encoding="utf-8", errors="replace"))
        if text:
            out[f"canberra:{p.parent.name}:{p.stem}"] = text
    for p in book_reprint_files(number, series):
        text = reprint_text(p.read_text(encoding="utf-8", errors="replace"))
        if text:
            out[f"book:{p.stem}"] = text
    return out


def reprint_key(numbers, series=REPRINTED):
    """What the reprints of an edition's `numbers` hold (the Canberra Times's
    and the books'), by file name and size: part of the edition's inputs, so
    a reprint downloaded or read after the edition was makes it due. ""
    when there is none."""
    files = [p for n in sorted(set(numbers))
             for p in (reprint_files(n) if series == REPRINTED else []) + book_reprint_files(n, series)]
    if not files:
        return ""
    h = hashlib.sha256()
    for p in files:
        h.update(f"{p.parent.name}/{p.name}:{p.stat().st_size}".encode())
    return h.hexdigest()[:16]


#: {path: ((mtime_ns, size), (url, date))} of each puzzle file held_scans has read.
_SCANS = {}


def held_scans(series):
    """{(source.url, date): [numbers]} of every filed puzzle in a series that
    names a scan page: one page on one day is one puzzle."""
    out = {}
    for p in (ROOT / "puzzles" / series).glob("*/*.json"):
        st = p.stat()
        stamp = (st.st_mtime_ns, st.st_size)
        seen = _SCANS.get(p)
        if seen is None or seen[0] != stamp:
            d = json.loads(p.read_text())
            seen = _SCANS[p] = (stamp, ((d.get("source") or {}).get("url"), (d.get("date") or "")[:10]))
        if seen[1][0]:
            out.setdefault(seen[1], []).append(int(p.stem.split("-")[1]))
    return out


def same_scan(number, url, day, series):
    """Why `number` cannot file (None if it can): another number in the series
    already holds this scan page `url` for `day`, so the OCR misread one
    number."""
    others = [m for m in held_scans(series).get((url, day.isoformat()), ()) if m != number]
    if others:
        return f"No {number} is the scan page No {others[0]} already holds ({url}, {day})"
    return None


def neighbours(day, held):
    """(before, after): the nearest filed (date, number) either side of
    `day` in `held` ({number: date}), each None when there is none."""
    return (max(((d, m) for m, d in held.items() if d < day), default=None),
            min(((d, m) for m, d in held.items() if d > day), default=None))


def implied(day, held):
    """The number `day`'s puzzle has when its nearest filed neighbours
    either side run unbroken, one number an issue; else None."""
    before, after = neighbours(day, held)
    if before and after and after[1] - before[1] == issues_between(before[0], after[0]):
        return before[1] + issues_between(before[0], day)
    return None


#: How near the number its date implies a title's number, one digit worth
#: 100 or more mended, must lie (mended_digit): those digits' variants lie
#: 100 apart, so at most one is this near.
DIGIT_SLACK = 10


def mended_digit(n, day, expected, held):
    """The number a title read as `n`, far from the `expected` its date
    implies, names with one digit misread (the 1983 FT's "5,401" for 5,101):
    the one its filed neighbours imply (implied) when that differs from `n`
    in one digit, else, with no such neighbours, the one a digit worth 100
    or more mended puts within DIGIT_SLACK of `expected`; None when neither."""
    text = str(n)
    fixed = implied(day, held)
    if fixed is not None:
        other = str(fixed)
        return fixed if len(other) == len(text) and sum(a != b for a, b in zip(text, other)) == 1 else None
    for k in range(len(text) - 2):
        for digit in "0123456789":
            m = int(text[:k] + digit + text[k + 1:])
            if digit != text[k] and abs(m - expected) <= DIGIT_SLACK:
                return m
    return None


def placed(n, day, held):
    """(number, None) that an edition of `day` read as No `n` files as, or
    (None, why) it cannot file. The edition's date is trusted over a number
    OCR read: when the nearest filed puzzles either side run unbroken, one
    number an issue, the date fixes the number (implied); otherwise No `n`
    must sit in date order among them and not be filed for another day."""
    before, after = neighbours(day, held)
    fixed = implied(day, held)
    if fixed is not None:
        return fixed, None
    if n in held and held[n] != day:
        return None, f"No {n} is already filed for {held[n]}, not {day}"
    if before and n <= before[1] or after and n >= after[1]:
        return None, (f"No {n} on {day} is out of date order with "
                      f"{' and '.join(f'No {m} on {d}' for d, m in (before, after) if d)}")
    return n, None


def issue_day(day, n, numbers):
    """The date of No `n` in an edition dated `day` holding `numbers`: an item
    can bind the next days' papers too, so each number above the lowest is one
    issue later (six a week, none on Sunday), but only while `numbers` run
    unbroken from the lowest up to `n`. Across a gap the lowest is a stray read
    (a solution heading, a misread), not an earlier issue, and No `n` keeps
    the edition's date."""
    low = min(numbers)
    if n - low > 6 or not set(range(low, n + 1)) <= set(numbers):
        return day
    for _ in range(n - low):
        day += datetime.timedelta(days=1 + (day.weekday() == 5))
    return day


def filed_number(d, found, hit):
    """(number, day, None) that a title files as, or (None, day, why) it is
    refused."""
    n = hit["number"]
    paper = paper_of(d)
    day = issue_day(datetime.date.fromisoformat(found["date"]), n, [h["number"] for h in found["puzzles"]])
    if paper in (TIMES, GALE) and day.weekday() == 6:
        return None, day, f"{day} is a Sunday and the Times prints no daily cryptic on it: a Sunday paper's puzzle"
    if abs(n - paper.expected(day)) > paper.slack:
        # A short number misread ("200" for 209): the page's solution
        # heading names the day before's.
        sols = [s["number"] + 1 for s in found["solutions"] if s["leaf"] == hit["leaf"]]
        n = next((m for m in sols if abs(m - paper.expected(day)) <= paper.slack), n)
    held = held_dates(paper.series)
    if abs(n - paper.expected(day)) > paper.slack:
        n = mended_digit(n, day, paper.expected(day), held) or n
    if abs(n - paper.expected(day)) > paper.slack:
        return None, day, (f"No {n} is not near the {paper.expected(day)} the date "
                           f"{day} implies: the item's date is wrong")
    number, why = placed(n, day, held)
    if number is not None:
        why = same_scan(number, page_url(d, found, hit["leaf"]), day, paper.series)
    return number, day, why


#: Why a title was refused: the verdict's `cause`, which tools/coverage.py
#: buckets by. `refused` keeps the detail for a person.
REFUSALS = ("number-date-mismatch", "not-a-grid", "no-reading-parses", "crashed")


def refuse(verdict, cause, why):
    """`verdict` refused for `cause` (one of REFUSALS), `why` the detail."""
    if cause not in REFUSALS:
        raise ValueError(f"refusal cause {cause!r} is not one of {REFUSALS}")
    verdict["refused"], verdict["cause"] = why, cause
    return verdict


def read_puzzle(d, found, hit, solutions):
    """(verdict, puzzle or None) for one title on one page."""
    n, leaf = hit["number"], hit["leaf"]
    verdict = {"number": n, "leaf": leaf}
    paper = paper_of(d)
    number, day, why = filed_number(d, found, hit)
    if why:
        return refuse(verdict, "number-date-mismatch", why), None
    if number != n:
        verdict["read_as"], n = n, number
        verdict["number"] = n
    img = page(d, leaf)
    lines = leaf_lines(d / "djvu.xml.gz", {leaf}).get(leaf, [])
    gbox, side = (grid_under_clues(img, hit["box"]), "below") if paper.clues_above else locate_grid(img, hit["box"])
    if gbox is None:
        return refuse(verdict, "not-a-grid", "no ink under the title"), None
    gw, gh = gbox[2] - gbox[0], gbox[3] - gbox[1]
    if side is None or not shaped_on(img, gbox):
        return refuse(verdict, "not-a-grid", f"the ink under the title is {gw}x{gh}, not a grid"), None
    key = f"{d.name}_{n}"
    third = (paper.third, third_top(img, gbox, paper.third)) if paper.third else None
    m = paper.margin
    # Clues over the grid: from the title line down, split where the fewest
    # words of any reading cross.
    top = hit["box"][1] - 10 if paper.clues_above else None
    beside = side == "left"
    lead = lead_column(hit["box"], gbox, m) if side == "right" else None
    rapid = {which: rapid_lines(img, gbox, which, CROPS / "rapid" / f"{key}.{reader_key(which)}.json", third, m, top,
                                beside, lead) for which in READERS}
    # The scan's grid, read before the clues: the 1930 Times prints no
    # counts, so its clues take theirs from it.
    gpath = CROPS / "grids" / f"{key}.png"
    gpath.parent.mkdir(parents=True, exist_ok=True)
    # Cut afresh on every read, so the crop is always of this grid box.
    img.crop((gbox[0] - 6, gbox[1] - 6, gbox[2] + 6, gbox[3] + 6)).save(gpath)
    image, why = trove_grid.read_grid(gpath)
    g = image
    if not g:
        verdict["imageUnread"] = why
    above = left = None
    every = lines + [ws for r in rapid.values() for ws in r]
    if paper.four:
        if not g:
            return refuse(verdict, "not-a-grid", f"the grid gives the clues' counts, and it is unread: {why}"), None
        gutters = four_gutters(every, gbox)
        down = down_at(every, gbox, gutters)
        cols = {which: columns_of_four(rapid[which], gbox, gutters, down) for which in FOUR_READERS}
        texts = {k: column_text(c) for k, c in cols.items()}
        wins = [None] * max(len(c) for c in cols.values())
        if vlm.reachable():
            try:
                texts["vlm"] = vlm_four(img, list(cols.values()))
            except RuntimeError:
                pass
        texts = {k: counted(spaced(t), g) for k, t in texts.items()}
    elif top is not None:
        above = (top, gutter(every, gbox, top), gutter(every, gbox, top, gbox[2] - OVERHANG, gbox[2] + OVERHANG))
    if beside:
        left = left_columns(every, gbox)
    if lead:
        lead = lead_split(every, gbox, lead, m)
    if not paper.four:
        split = under_gutter(every, gbox) if above is None and left is None else None
        cols = {"djvu": columns(lines, gbox, third, m, above, left, split, lead)}
        for which in READERS:
            cols[which] = columns(rapid[which], gbox, third, m, above, left, split, lead)
        texts = {k: column_text(c) for k, c in cols.items()}
        wins = windows(gbox, third, m, above, left, split, lead)
    # The desktop's VLM, when it answers, is one more reading (the 1930
    # page's, vlm_four's above).
    if vlm.reachable() and not paper.four:
        try:
            texts["vlm"] = "\n".join(numbered_heading(t) or t for t in
                                     vlm.column_text(img, wins, list(cols.values())).splitlines())
        except RuntimeError:
            pass  # gone mid-run: read as without it; run() files it to be read again
    # The Canberra Times reprint of the same puzzle is another copy of the
    # print, its readings voters like the scan's own.
    texts.update(reprint_readings(n, paper.series))
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
        # A number its list's order refuses ("12" after 19) is left for the
        # grid to place, never handed to the rebuild as read.
        parsed, _ = ftp.renumber(parsed)
        laid, why = ftp.match(parsed, g) if g else (None, None)
        tried.append((laid is not None, trove_clue_ocr.complete(parsed),
                      sum(len(v) for v in parsed.values()), -len(tried), order, parsed, laid, why))
        if laid is not None:
            break
    if not tried:
        return refuse(verdict, "no-reading-parses", "no reading parses"), None
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
                    lists.append(((k,), ftp.renumber(p)[0]))
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
        if g is None and image:
            # No grid fits the clues, so the misreads are the clues': the
            # scan's grid stands, its unlaid lights blank for the clue
            # re-read.
            grid, how, laid = image, "image", loose
        elif g is None:
            verdict["pending"] = f"no grid: {why}"
            return verdict, None
        else:
            laid, why = ftp.match(parsed, g)
            if laid is None:
                verdict["pending"] = f"rebuilt grid disagrees: {why}"
                return verdict, None
            grid, how = g, "rebuilt"
    verdict["grid"] = how
    lengths = {f"{n_}-{d_}": len(cells) for (n_, d_), cells in rg.light_cells(grid).items()}
    fits = {lid for lid, (_, enum, group) in laid.items()
            if enum and not group and ftp.count(enum) == lengths.get(lid)}
    laid, blank = unfit_blanked(*reconcile(laid, stream, lengths), lengths)
    # A clue the vote left blank, laid again from each reading that printed
    # it whole (the reprint's among them) and put to the rest.
    laid, blank = ocr_clues.relaid({k: t for k, t in texts.items() if t.strip()}, laid, blank, parse, lengths)
    if blank and "vlm" in texts and vlm.reachable():
        try:
            laid, blank = vlm_pick(img, wins, list(cols.values()), texts, laid, blank)
        except RuntimeError:
            pass
    # Each filed clue as the readings print it: its count's shape, each word's
    # capital, hyphen and spelling.
    laid, blank = ocr_clues.as_printed(texts, laid, blank, parse, lengths)
    laid, blank = one_light_each(laid, blank, fits)
    laid, blank = unfit_blanked(laid, blank, lengths)
    if paper.four:
        # The counts were the grid's, not the paper's: filed without.
        laid = {lid: (t, None, None) for lid, (t, _, _) in laid.items()}
    verdict["lights"] = len(rg.light_cells(grid))
    verdict["agreed"] = sum(1 for t, _, _ in laid.values() if t)
    if blank:
        verdict["blank"] = blank
    puzzle = build(n, day, grid, how, laid, edition_of(d, found), leaf, series=paper.series,
                   name=paper.name.format(n), url=page_url(d, found, leaf))
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
#: The gap, in pixels, closed across a solution grid's ink before its box is
#: taken: a frame the scan broke leaves a part of the grid the largest ink
#: (Gale's 1987-01-15, 248px of its 340).
SOLUTION_CLOSE = 3


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
    box = ink_box(img.crop(crop), SOLUTION_CLOSE)
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
    # The crop is the grid, frame to frame: read on its own rules.
    answers, stats = trove_solution_ocr.read_answers(path, grid, tight=True)
    if stats["blocks"] < SOLUTION_BLOCKS:
        return {}, {**stats, "refused": "its blocks are not the puzzle's"}
    return {f"{n}-{d}": w for (n, d), w in answers.items()}, stats


# ------------------------------------------------------------ the run

#: Editions read at once: the desktop VLM serves one request at a time, so a
#: second one's OCR fills the first one's wait; more contend for the host's
#: four cores.
WORKERS = 2
#: How often (seconds) the scan phase saves the ledger.
SAVE_EVERY = 300


def scan_key():
    """A hash of the code that finds an edition's titles and solution
    headings: what scan() reaches, here and in this repo's other modules
    (tools/code_reach.py: a method only when called, comments and
    docstrings left out), past the desktop transport. A scan made by other code is
    made again; an edit to code scan() never runs changes nothing."""
    if not _SCAN_KEY:
        import code_reach
        _SCAN_KEY.append(code_reach.key("file_archive_org_puzzles", SCAN_ROOTS))
    return _SCAN_KEY[0]


def whole_name_scan_key(text=None):
    """The scan key ledger rows were written under before scan_key(): every
    whole definition of this file scan()'s names reach. A row under the
    one this file gives now is re-keyed to scan_key() (rekey_scans), not
    scanned again."""
    import ast
    text = text if text is not None else Path(__file__).read_text()
    tree = ast.parse(text)
    defs = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defs.setdefault(node.name, []).append(node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    defs.setdefault(t.id, []).append(node)
    seen, todo = set(), list(SCAN_ROOTS)
    while todo:
        name = todo.pop()
        if name in seen or name not in defs:
            continue
        seen.add(name)
        todo += [n.id for node in defs[name] for n in ast.walk(node) if isinstance(n, ast.Name)]
    h = hashlib.sha256()
    for node in tree.body:
        names = ([node.name] if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else
                 [t.id for t in node.targets if isinstance(t, ast.Name)] if isinstance(node, ast.Assign) else [])
        if set(names) & seen:
            h.update(ast.get_source_segment(text, node).encode())
    return h.hexdigest()[:16]


def rekey_scans(ledger):
    """Re-key the rows of `ledger` scanned under whole_name_scan_key() to
    scan_key(), unless a run holds it; how many."""
    import fcntl
    old, new = whole_name_scan_key(), scan_key()
    if old == new or not ledger.exists():
        return 0
    with open(ledger.with_suffix(".lock"), "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        rows = scan_queue.jsonl_rows(ledger)
        n = sum(r.get("scanKey") == old for r in rows)
        if n:
            tmp = ledger.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps({**r, "scanKey": new} if r.get("scanKey") == old else r) + "\n"
                                   for r in rows), encoding="utf-8")
            tmp.replace(ledger)
        return n


#: Where scan_key() starts.
SCAN_ROOTS = {"scan"}
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
    up (ocr_clues.suspect; a token its `asPrinted` keeps is the print's) or
    unfit to file (faults)."""
    return filled(puzzle)[0] == len(puzzle["entries"]) and not any(
        suspect((e.get("clue") or {}).get("text", ""), printed=(e.get("clue") or {}).get("asPrinted") or ())
        for e in puzzle["entries"]) and not faults(puzzle)


def unfit_blanked(laid, blank, lengths):
    """(laid, blank) with each clue complete() would refuse filed blank and
    why in `blank`, so a puzzle with an empty `blank` is complete: a clue
    ocr_clues.fault refuses (its count kept when it fills the light), one
    with a word ocr_clues.suspect flags, and each light of `lengths` with
    no text that is no linked clue's tail ("See 1")."""
    laid, blank = dict(laid), dict(blank)
    tails = {t for _, _, group in laid.values() for t in (group or [])[1:]}
    for lid in lengths:
        if lid not in tails and not (laid.get(lid) or ("",))[0].strip():
            laid[lid] = laid.get(lid) or ("", None, None)
            blank.setdefault(lid, "no reading laid a clue on it")
    for lid, (text, enum, group) in list(laid.items()):
        why = ocr_clues.fault(text, enum, sum(lengths.get(i, 0) for i in group or [lid]))
        if why:
            laid[lid] = ("", None if why.startswith("its count") else enum, group)
            blank[lid] = why
            continue
        odd = suspect(text)
        if odd:
            laid[lid] = ("", enum, group)
            blank[lid] = f"{odd[0][0]!r}: {odd[0][1]}"
    return laid, blank


def faults(puzzle):
    """{entry id: why} of each clue of a filed puzzle ocr_clues.fault refuses."""
    def lid(e):
        return f"{e.get('number')}-{e.get('direction')}"
    length = {lid(e): e.get("length") for e in puzzle["entries"]}
    out = {}
    for e in puzzle["entries"]:
        clue = e.get("clue") or {}
        cells = sum(length.get(i) or 0 for i in e.get("group") or [lid(e)])
        why = ocr_clues.fault(clue.get("text"), clue.get("enumeration"), cells, clue.get("asPrinted") or ())
        if why:
            out[lid(e)] = why
    return out


def check_filed(out=sys.stdout):
    """List every puzzle this tool filed whose clues faults() refuses, by
    class; returns the count of failing puzzles."""
    from fetch_puzzle import read_puzzle_file
    bad, classes = 0, {}
    for path in sorted((ROOT / "puzzles").glob("*/*/*.json")):
        try:
            puzzle = read_puzzle_file(path)
        except (OSError, ValueError):
            continue
        if (puzzle.get("source") or {}).get("acquiredBy") != TOOL:
            continue
        found = faults(puzzle)
        if not found:
            continue
        bad += 1
        for lid, why in found.items():
            kind = why.split(":")[0].split(" (")[0]
            classes.setdefault(kind, set()).add(puzzle["id"])
            print(f"{puzzle['id']} {lid}: {why}", file=out)
    for kind, ids in sorted(classes.items()):
        print(f"{len(ids)} puzzles: {kind}", file=out)
    print(f"{bad} puzzles filed by {TOOL} fail the clue check", file=out)
    return bad


def progress(line):
    """One line per source as it is read, to stderr, so a long run's log moves."""
    print(f"{time.strftime('%H:%M:%S')} {line}", file=sys.stderr, flush=True)


def ledger_of(cache=CACHE, paper=None, ledger=None):
    """The ledger a run of `paper` keeps under `cache` (LEDGER_NAMES), or `ledger`."""
    return Path(ledger or cache / LEDGER_NAMES.get((paper or TIMES).key, "filed.jsonl"))


def load_known(ledger):
    """{edition: row} of a ledger, the last row of each standing."""
    known = scan_queue.ledger_rows(ledger, "edition")
    for row in known.values():
        if "hash" in row and "inputs" not in row:
            # A row keyed by code and files together: its read stands
            # for the files it was read with.
            row.pop("hash")
            row["inputs"] = row.get("filesHash")
    return known


def run(cache=CACHE, write=True, ledger=None, out=sys.stdout, puzzles=None, limit=None,
        source=SOURCE, paper=None, seconds=None, workers=1, wait=False, reread=None, editions=None, scan_new=True,
        newer=None):
    """File what is new under `cache`: complete puzzles into the corpus, ones
    with a blank clue into `puzzles` when given. At most `limit` editions are
    read, none started after `seconds`, `workers` at once (scan_queue).
    `reread` (a datetime) reads again every edition last read before it;
    `editions` ("ITEM/EDITION" names) reads those again and no other.
    Without `scan_new`, nothing is scanned and only the editions whose read
    waits on no scan are read (unsettled). `newer` (a time.time()) reads
    only the due editions laid out since then (staged_at).
    Returns the ledger rows; [] when another run holds the ledger and `wait`
    is not set."""
    deadline = None if seconds is None else time.monotonic() + seconds
    paper = paper or TIMES
    ledger = ledger_of(cache, paper, ledger)
    with scan_queue.lock(ledger, wait) as mine:
        if not mine:
            print(f"another run holds {ledger.with_suffix('.lock')}: nothing read", file=out)
            return []
        return _run(cache, write, ledger, out, puzzles, limit, source, paper, deadline, workers, reread,
                    editions, scan_new, newer)


def inputs_of(files_hash, found, series):
    """An edition's inputs: its files (input_hash), for a puzzle the
    Canberra Times reprinted the reprint's cached texts (reprint_key), and
    whether a puzzle of it filed by this tool holds a clue ocr_clues.stray
    flags, which a read mends or blanks (mend_held). _run keys the ledger
    by the inputs after its write, so an edition is read once for it: a
    clue the read could not mend (a reading on another grid) stays as it
    is until the edition's other inputs move."""
    extra = reprint_key([p["number"] for p in found["puzzles"]], series)
    numbers = [p["number"] for p in found["puzzles"]]
    if any(strayed(json.loads(path.read_text())) for path in held_paths(series, numbers)):
        extra = (extra or "") + "+strayed"
    return f"{files_hash}+{extra}" if extra else files_hash


def held_paths(series, numbers):
    """The corpus files this tool filed for puzzles `numbers` of `series`."""
    from fetch_puzzle import puzzle_path
    out = []
    for n in numbers:
        path = puzzle_path(series, n)
        if path.exists() and (json.loads(path.read_text()).get("source") or {}).get("acquiredBy") == TOOL:
            out.append(path)
    return out


def strayed(puzzle):
    """The lights of a puzzle whose clue ocr_clues.stray flags (a doubled
    word, a stray letter)."""
    return {entry_id(e) for e in puzzle.get("entries") or ()
            if ocr_clues.stray((e.get("clue") or {}).get("text") or "")}


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


#: Days after an edition whose scans a run limited to it reads afresh: the
#: next day's paper prints its solution, after a Sunday or a holiday later.
SOLUTION_DAYS = 7


def edition_date(d):
    """The date in an edition dir's name, or None."""
    m = re.search(r"\d{4}-\d{2}-\d{2}", d.name)
    return datetime.date.fromisoformat(m.group()) if m else None


def unsettled(dirs, unscanned):
    """The `dirs` whose read waits on a scan in `unscanned`: those and each
    dated within SOLUTION_DAYS before one (its solution may print there);
    every dir when an unscanned one, or the dir itself, has no date."""
    if not unscanned:
        return set()
    import bisect
    pending = [edition_date(d) for d in unscanned]
    if None in pending:
        return set(dirs)
    pending.sort()
    out = set(unscanned)
    for d in dirs:
        day = edition_date(d)
        k = len(pending) if day is None else bisect.bisect_left(pending, day)
        if day is None or k < len(pending) and (pending[k] - day).days <= SOLUTION_DAYS:
            out.add(d)
    return out


def scan_near(dirs, rels, editions):
    """The edition dirs a run limited to `editions` scans: each named one and
    those of its item dated within SOLUTION_DAYS after it."""
    named = [d for d in dirs if rels[d] in editions]
    out = set(named)
    for n in named:
        start = edition_date(n)
        out |= {d for d in dirs if d.parent == n.parent and start and edition_date(d)
                and 0 < (edition_date(d) - start).days <= SOLUTION_DAYS}
    return out


def staged_at(d):
    """When edition dir `d` was laid out: its pages.json's mtime (written last)."""
    return (d / "pages.json").stat().st_mtime


# ------------------------------------------------------------ the per-edition queue

#: How urgent each reason to read an edition is (tools/edition_queue.py
#: takes the lowest first): pages Paul saved by hand, then any never-read
#: edition and the re-reads annotation asked for, then an edition whose
#: inputs moved, then the re-reads REREAD_BEFORE makes due.
RANKS = {"saved by hand": 0, "never read": 1, "annotation asked": 1, "inputs changed": 2, "titles changed": 2,
         "read without the VLM": 2, "scan stale": 2, "--reread": 3}


def scan_current(row, fh):
    """Whether ledger `row` holds a scan of files `fh` by this scan code."""
    return bool(row) and row.get("filesHash") == fh and row.get("scanKey") == scan_key() and "scan" in row


def plan(paper, cache=CACHE, ledger=None, reread=None, asked=(), dirs=None):
    """What a run of `paper` has to do, scanning nothing: ([scan unit],
    [read unit]), each a dict with "rel", "rank" (RANKS), "reason"; a read
    unit's "needs" are the editions whose scans it waits on (its own and
    those dated SOLUTION_DAYS after it: its solution prints there), a scan
    unit's rank the most urgent read needing it. `asked` are the editions
    annotation asked to have read again (read whatever their row says);
    `dirs` limits the plan to those editions. Each list is in the order a
    run reads them (scan_queue.order; NEWEST_FIRST papers by staged_at)."""
    import bisect
    ledger = ledger_of(cache, paper, ledger)
    known = load_known(ledger)
    every = _PLANNED_DIRS[(str(cache), paper.key)] = edition_dirs(cache, paper)
    held_dates(paper.series)  # cached here, so each unit forked after this reads only what changed
    dirs = every if dirs is None else [d for d in every if d in set(dirs)]
    rels = {d: f"{d.parent.name}/{d.name}" for d in every}
    seen_by = vlm.version() if vlm.reachable() else None
    stale = [d for d in dirs if not scan_current(known.get(rels[d]), input_hash(d))]
    stale_set = set(stale)
    scans = {rels[d]: (known.get(rels[d]) or {}).get("scan") or {"puzzles": [], "solutions": []} for d in every}
    solutions = {s["number"] for d in every for s in scans[rels[d]]["solutions"]}
    asked = set(asked)
    reads = {}
    for d in dirs:
        rel, row = rels[d], known.get(rels[d]) or {}
        if d in stale_set:
            why = "scan stale" if "inputs" in row else "never read"
        else:
            sol_seen = sorted(n for n in (p["number"] for p in scans[rel]["puzzles"]) if n in solutions)
            why = due_reason(row, inputs_of(row["filesHash"], scans[rel], paper.series), sol_seen, seen_by, reread)
        if not why and rel in asked:
            why = "annotation asked"
        if why == "never read" and paper.key in NEWEST_FIRST:
            why = "saved by hand"
        if why:
            reads[d] = why
    # Which stale scans each read waits on: its own and the SOLUTION_DAYS after it.
    dated = sorted((edition_date(d), rels[d]) for d in stale if edition_date(d))
    undated = [rels[d] for d in stale if not edition_date(d)]
    days = [day for day, _ in dated]

    def needs(d):
        day = edition_date(d)
        if day is None:
            return [rels[s] for s in stale]
        lo = bisect.bisect_left(days, day)
        hi = bisect.bisect_right(days, day + datetime.timedelta(days=SOLUTION_DAYS))
        return [rel for _, rel in dated[lo:hi]] + undated
    keys = sorted(reads, key=staged_at, reverse=True) if paper.key in NEWEST_FIRST else list(reads)
    queue = scan_queue.order(keys, {d: known.get(rels[d]) or {} for d in reads}, lambda row: "inputs" not in row)
    read_units = [{"kind": "read", "paper": paper.key, "rel": rels[d], "reason": reads[d], "rank": RANKS[reads[d]],
                   "needs": needs(d), "force": reads[d] == "annotation asked"} for d in queue]
    rank_of = {}
    for u in read_units:
        for rel in u["needs"]:
            rank_of[rel] = min(rank_of.get(rel, 9), u["rank"])
    scan_units = [{"kind": "scan", "paper": paper.key, "rel": rels[d], "rank": rank_of.get(rels[d], RANKS["scan stale"]),
                   "reason": "scan stale" if "scan" in (known.get(rels[d]) or {}) else "never scanned"}
                  for d in (sorted(stale, key=staged_at, reverse=True) if paper.key in NEWEST_FIRST else stale)]
    return scan_units, read_units


#: {(cache, paper key): edition dirs} as the last plan() listed them: a unit
#: forked after it starts from this list (its own edition added), not a
#: listing of every item of its own (seconds each on a loaded host).
_PLANNED_DIRS = {}


def scan_unit(paper, rel, cache=CACHE, ledger=None):
    """Scan one edition and add its row to the ledger (scan_queue.append),
    unless another unit holds it or its scan stands: "scanned", "busy",
    "current" or "held" (a run holds the ledger throughout)."""
    ledger = ledger_of(cache, paper, ledger)
    if scan_queue.held(ledger):
        return "held"
    d = Path(cache) / rel
    with scan_queue.source_lock(ledger, rel) as mine:
        if not mine:
            return "busy"
        fh = input_hash(d)
        row = load_known(ledger).get(rel) or {}
        if scan_current(row, fh):
            return "current"
        try:
            found = scan(d)
        except Exception as e:  # noqa: BLE001 -- as _run: a scan that raises stands as one with no headings
            found = {"puzzles": [], "solutions": [], "failed": scan_queue.failure((rel,), e)}
        progress(f"scanned {rel}: " + (f"failed: {found['failed']}" if "failed" in found
                                       else f"{len(found['puzzles'])} puzzle(s)"))
        scan_queue.append(ledger, [{**row, "edition": rel, "scan": found, "filesHash": fh, "scanKey": scan_key()}])
        return "scanned"


def read_unit(paper, rel, cache=CACHE, ledger=None, puzzles=None, source=SOURCE, reread=None, force=False,
              out=sys.stdout):
    """Read one edition (its own scan made first if it is stale) and file
    what it holds, adding its row to the ledger, unless another unit holds
    it or it is no longer due (`force`: read it anyway): "read", "busy" or
    "held" (a run holds the ledger throughout)."""
    ledger = ledger_of(cache, paper, ledger)
    if scan_queue.held(ledger):
        return "held"
    with scan_queue.source_lock(ledger, rel) as mine:
        if not mine:
            return "busy"
        dirs = _PLANNED_DIRS.get((str(cache), paper.key))
        if dirs is not None and Path(cache) / rel not in dirs:
            dirs = [*dirs, Path(cache) / rel]
        _run(cache, True, ledger, out, puzzles, None, source, paper, None, 1, reread, editions=[rel],
             unit={"force": force, "dirs": dirs})
        return "read"


def _run(cache, write, ledger, out, puzzles, limit, source, paper, deadline, workers, reread, editions=None,
         scan_new=True, newer=None, unit=None):
    from fetch_puzzle import puzzle_path, write_puzzle_file
    known = load_known(ledger)
    # A unit (read_unit) adds the rows it changed to the ledger; a run
    # holding the ledger's lock throughout rewrites it whole.
    changed = set()

    def flush():
        if not write:
            return
        if unit is not None:
            scan_queue.append(ledger, [known[k] for k in sorted(changed)])
        else:
            save(ledger, known)
        changed.clear()
    # The VLM's readings are an input: an edition read without it is read
    # again once it answers, and one read with it stands while it is down.
    seen_by = vlm.version() if vlm.reachable() else None
    dirs = (unit or {}).get("dirs") or edition_dirs(cache, paper)
    rels = {d: f"{d.parent.name}/{d.name}" for d in dirs}
    # With `newer`, only the editions laid out since then are read, and only
    # they and the days after them scanned.
    fresh = None if newer is None else {rels[d] for d in dirs if staged_at(d) >= newer}
    # Every heading first: a puzzle's solution is in a later edition.
    # With `editions`, only those and the days after them (where their
    # solutions print) are scanned afresh; every other edition's last scan
    # stands, stale or not, and one never scanned offers no solution.
    # A unit scans its own edition alone: the queue scans the others (scan_unit).
    near = ({d for d in dirs if rels[d] in editions} if unit is not None else
            scan_near(dirs, rels, editions or fresh) if editions or fresh is not None else None)
    scans, unscanned = {}, {}
    for d in dirs:
        row = known.get(rels[d])
        if near is not None and d not in near:
            scans[rels[d]] = (row or {}).get("scan") or {"puzzles": [], "solutions": []}
            continue
        fh = input_hash(d)
        if row and row.get("filesHash") == fh and row.get("scanKey") == scan_key() and "scan" in row:
            scans[rels[d]] = row["scan"]
        else:
            unscanned[d] = fh
    # Without scan_new, an edition whose read waits on a scan is left for
    # the run that scans; every other edition's last scan stands.
    held_back = set()
    if not scan_new:
        held_back = unsettled(dirs, unscanned)
        for d in unscanned:
            scans[rels[d]] = (known.get(rels[d]) or {}).get("scan") or {"puzzles": [], "solutions": []}
        unscanned = {}
    # A scan that raises stands as one with no headings, kept under this
    # scan_key, so it is not made again until the scan code changes.
    saved = time.monotonic()
    for (d,), found in scan_queue.parallel([(d,) for d in unscanned], scan, workers,
                                           failed=lambda item, error: {"puzzles": [], "solutions": [],
                                                                       "failed": error}):
        scans[rels[d]] = found
        progress(f"scanned {rels[d]}: " + (f"failed: {found['failed']}" if "failed" in found
                                           else f"{len(found['puzzles'])} puzzle(s)"))
        known[rels[d]] = {**known.get(rels[d], {}), "edition": rels[d], "scan": found, "filesHash": unscanned[d],
                          "scanKey": scan_key()}
        changed.add(rels[d])
        # Saved as it goes: the scans of a whole paper take hours, and a kill
        # then loses at most SAVE_EVERY seconds of them.
        if time.monotonic() - saved >= SAVE_EVERY:
            flush()
            saved = time.monotonic()
    if unscanned:
        flush()
    solutions = {}
    for d in dirs:
        for s in scans[rels[d]]["solutions"]:
            solutions.setdefault(s["number"], {**s, "dir": d})
    due = {}
    for d in dirs:
        rel = rels[d]
        if editions and rel not in editions or d in held_back or fresh is not None and rel not in fresh:
            continue
        fh = known[rel]["filesHash"]
        h = inputs_of(fh, scans[rel], paper.series)
        sol_seen = sorted(n for n in (p["number"] for p in scans[rel]["puzzles"]) if n in solutions)
        why = due_reason(known[rel], h, sol_seen, seen_by, reread)
        if why or editions and (unit is None or unit.get("force")):
            due[d] = (h, sol_seen, fh)
        elif unit is not None:
            progress(f"not due {rel}: its scan stands as read, or it was read since it was queued")
    # Read only when something is due: a unit that finds nothing due ends here.
    held = held_numbers(paper.series) if due else set()
    if due:
        held_dates(paper.series)  # read once here: the forked workers start with it
    keys = sorted(due, key=staged_at, reverse=True) if paper.key in NEWEST_FIRST else list(due)
    queue = scan_queue.order(keys, {d: known[rels[d]] for d in due}, lambda row: "inputs" not in row)
    if limit is not None:
        queue = queue[:limit]
    fresh = 0
    for (d, found), (results, vlm_ok) in scan_queue.parallel(
            [(d, scans[rels[d]]) for d in queue], read_edition, workers, deadline,
            init=set_solutions, initargs=(solutions,), failed=edition_failed):
        rel = rels[d]
        h, sol_seen, fh = due[d]
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
                mended = mend_held(puzzle, held_path) if held_path.exists() else None
                if mended is not None:
                    verdict["mended"] = mended[1]
                    answered = merge_answers(mended[0], puzzle, reread=solution_read(verdict))
                    if answered:
                        verdict["answered"] = answered
                    if write:
                        scan_queue.file_puzzle(write_puzzle_file, TOOL, held_path, mended[0], verdict)
                    verdicts.append(verdict)
                    continue
                dest = destination(puzzles, complete(puzzle))
                if dest is False:
                    verdict["skip"] = "a clue is blank: only a puzzle with every clue goes to the corpus"
                    old = json.loads(held_path.read_text()) if held_path.exists() else None
                    answered = old is not None and merge_answers(old, puzzle, reread=solution_read(verdict))
                    if answered:
                        verdict["answered"] = answered
                        if write:
                            scan_queue.file_puzzle(write_puzzle_file, TOOL, held_path, old, verdict)
                    verdicts.append(verdict)
                    continue
                path = (Path(dest) / f"{puzzle['id']}.json" if dest
                        else puzzle_path(paper.series, puzzle["number"]))
                better = path.exists() and improves(puzzle, path)
                old = json.loads(path.read_text()) if path.exists() and not better else None
                answered = old is not None and merge_answers(old, puzzle, reread=solution_read(verdict))
                if answered:
                    verdict["answered"] = answered
                    if write:
                        scan_queue.file_puzzle(write_puzzle_file, TOOL, path, old, verdict)
                elif hit_number in held and not dest and not better:
                    verdict["skip"] = "already held: the reading votes in cross_validate.py"
                elif write and (better or not path.exists()) and scan_queue.file_puzzle(
                        write_puzzle_file, TOOL, path, puzzle, verdict):
                    held.add(hit_number)
            verdicts.append(verdict)
        # Keyed by the inputs after this read's writes: a stray clue it
        # mended no longer makes the edition due.
        h = inputs_of(fh, found, paper.series)
        known[rel] = {"edition": rel, "inputs": h, "scan": found, "filesHash": fh, "scanKey": scan_key(),
                      "solutionsSeen": sol_seen, "verdicts": verdicts, "readAt": scan_queue.now()}
        if seen_by and vlm_ok:
            known[rel]["vlm"] = seen_by
        changed.add(rel)
        flush()
        progress(f"read {rel}: " + ("; ".join(
            f"{v['number']} " + ("wrote " + v["id"] if v.get("wrote") else
                                 v.get("skip") or v.get("refused") or v.get("refusedWrite")
                                 or ("write failed: " + v["writeFailed"] if v.get("writeFailed") else None)
                                 or v.get("id") or "read")[:60]
            for v in verdicts) or "nothing filed"))
    flush()
    tally = report(known[rels[d]] for d in dirs if rels[d] in known)
    if len(due) > fresh:
        tally["left for the next run"] = len(due) - fresh
    print(f"{len(dirs)} {paper.key} editions in {cache}; {fresh} read this run"
          + (f"; {len(held_back)} wait on a scan" if held_back else ""), file=out)
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
    VLM still answers after it): read on the desktop when tools/ocr_remote.py
    can, the same reading as here."""
    import ocr_remote
    got = ocr_remote.edition(d, found, _SOLUTIONS)
    if got is not None:
        return got
    results = []
    with ocr_remote.local_slot():
        for hit in found["puzzles"]:
            try:
                verdict, puzzle = read_puzzle(d, found, hit, _SOLUTIONS)
            except Exception as e:  # noqa: BLE001 -- one bad page is a verdict, not a crash
                verdict, puzzle = refuse({"number": hit["number"]}, "crashed",
                                         f"crashed: {type(e).__name__}: {e}"), None
            results.append((verdict, puzzle))
    return results, vlm.reachable()


def edition_failed(item, error):
    """read_edition's result for an edition whose read raised: each title
    refused, as read_edition refuses a title whose read raises."""
    _, found = item
    return [(refuse({"number": hit["number"]}, "crashed", f"crashed: {error}"), None)
            for hit in found["puzzles"]], False


def filled(puzzle):
    """(clues with text, answers) of a puzzle."""
    es = puzzle["entries"]
    return (sum(1 for e in es if ((e.get("clue") or {}).get("text") or "").strip()),
            sum(1 for e in es if e.get("solution")))


def improves(puzzle, path, tool=TOOL):
    """Whether `puzzle` should replace the file at `path`: one `tool`
    filed, on the same grid, that the new reading beats on clues or answers
    and loses on neither."""
    old = json.loads(path.read_text())
    if (old.get("source") or {}).get("acquiredBy") != tool \
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


def mend_held(puzzle, path, tool=TOOL):
    """(the held file at `path` mended, {light: its clue now}), or None: each
    light the file gives a clue it gives another light too
    (fetch_puzzle.duplicated_clues), or a clue faults() refuses, takes this
    reading's clue for it, which one_light_each left on one light at most
    and unfit_blanked let stand. With none, a light on a shared clue or one
    holding another clue's or the page's text (ocr_clues.bled, which no
    write may keep) goes blank for the blank-clue re-read, and another
    refused clue stands: its words are all the corpus has of it
    (puzzle_integrity.check_rewrite). A light
    whose clue changes loses its annotation, written against the old words.
    A clue with a doubled word or a stray letter (strayed) is never kept:
    it takes this reading's clue, or goes blank.
    None when no clue changes, the file is not `tool`'s, or it lies on
    another grid than this reading. With no reading (`puzzle` None: its
    scan now reads as another number), only the shared clues go."""
    from fetch_puzzle import duplicated_clues
    old = json.loads(path.read_text())
    puzzle = puzzle or {"entries": []}
    if (old.get("source") or {}).get("acquiredBy") != tool \
            or puzzle["entries"] and trove_solution_ocr.puzzle_grid(old) != trove_solution_ocr.puzzle_grid(puzzle):
        return None
    shared = {i for ids in duplicated_clues(old["entries"]) for i in ids}
    stray = strayed(old)
    lost = shared | stray | set(faults(old))
    if not lost:
        return None
    now = {entry_id(e): e["clue"] for e in puzzle["entries"] if (e["clue"] or {}).get("text")}
    was = {entry_id(e): e.get("clue") for e in old["entries"]}
    blank = enumeration.clue("", missing=True)

    def fallback(lid):
        return blank if lid in shared | stray or ocr_clues.bled((was[lid] or {}).get("text")) else was[lid]
    for e in old["entries"]:
        if entry_id(e) in lost:
            e["clue"] = now.get(entry_id(e)) or fallback(entry_id(e))
    # This reading's clue for a lost light may be one the file keeps on
    # another: that light's falls back too.
    for ids in duplicated_clues(old["entries"]):
        for e in old["entries"]:
            if entry_id(e) in ids and entry_id(e) in lost:
                e["clue"] = fallback(entry_id(e))
    text = lambda clue: (clue or {}).get("text") or ""
    changed = {entry_id(e) for e in old["entries"]
               if entry_id(e) in lost and text(e["clue"]) != text(was[entry_id(e)])}
    if not changed:
        return None
    for e in old["entries"]:
        if entry_id(e) in changed:
            e.pop("annotation", None)
    return old, {entry_id(e): text(e["clue"]) for e in old["entries"] if entry_id(e) in lost}


def merge_answers(old, puzzle, tool=TOOL, reread=False):
    """{light: its answer now (None: dropped)} after taking `puzzle`'s
    answers into the held filing `old` (in place): each light this reading
    answers takes its answer, and a held answer a new one crosses on
    another letter is dropped; with `reread` (this reading read the
    solution grid) so is every held answer it did not read again, the
    older reader's sure reads having filed wrong ones (BAYED for DATED).
    A light whose answer changes loses its
    annotation, written against the old answer. {} when `old` is not
    `tool`'s or lies on another grid."""
    if (old.get("source") or {}).get("acquiredBy") != tool \
            or trove_solution_ocr.puzzle_grid(old) != trove_solution_ocr.puzzle_grid(puzzle):
        return {}
    def cells(e):
        x, y, across = e["position"]["x"], e["position"]["y"], e["direction"] == "across"
        return [(x + i * across, y + i * (not across)) for i in range(e["length"])]
    new = {entry_id(e): e["solution"] for e in puzzle["entries"] if e.get("solution")}
    letters = {rc: ch for e in puzzle["entries"] if e.get("solution") for rc, ch in zip(cells(e), e["solution"])}
    changed = {}
    for e in old["entries"]:
        lid, was = entry_id(e), e.get("solution")
        now = new.get(lid, was)
        if lid not in new and was and (reread or any(letters.get(rc, ch) != ch for rc, ch in zip(cells(e), was))):
            now = None
        if now != was:
            e["solution"] = now
            e.pop("annotation", None)
            changed[lid] = now
    return changed


def solution_read(verdict):
    """Whether a title's read took its answers off its solution grid."""
    return "solution" in verdict and "refused" not in verdict["solution"]


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
            if v.get("refusedWrite"):
                add("write refused")
            if v.get("writeFailed"):
                add(f"write failed: {v['writeFailed'].split(':')[0][:50]}")
            for k in ("refused", "pending"):
                if v.get(k):
                    add(f"{k}: {v[k].split(':')[0][:50]}")
    return tally


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--ledger", type=Path, help="default <cache>/filed.jsonl (--paper gale: filed-gale.jsonl)")
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
    ap.add_argument("--newer-than", type=float, metavar="SECONDS",
                    help="read only the due editions laid out in the last SECONDS (a Gale page just saved)")
    ap.add_argument("--no-scan", action="store_true",
                    help="scan nothing; read only the due editions whose scans, and those of the days after "
                         "them, stand")
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    ap.add_argument("--show", metavar="ITEM/EDITION", help="one edition's verdicts")
    ap.add_argument("--paper", choices=sorted(FILERS), default="times",
                    help="whose editions to file: the Times (times-N), the FT (ftcryptic-N), the Guardian "
                         "(cryptic-N), the Telegraph (telegraph-N) or the Times pages saved from Gale (gale)")
    ap.add_argument("--check-filed", action="store_true",
                    help="list every puzzle this tool filed with a clue it would refuse now; write nothing")
    ap.add_argument("--match-canberra", action="store_true",
                    help="only name the Times puzzle each canberra file reprints")
    args = ap.parse_args(argv)
    if args.check_filed:
        return 1 if check_filed() else 0
    if args.match_canberra:
        match_canberra(args.source, write=not args.dry_run)
        return 0
    if args.mend_held:
        from fetch_puzzle import puzzle_paths, write_puzzle_file
        for pid in args.mend_held:
            path = puzzle_paths.find(pid)
            mended = path and mend_held(None, path)
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
        limit=args.limit, source=args.source, paper=FILERS[args.paper], seconds=args.seconds,
        workers=args.workers, wait=args.wait, reread=scan_queue.when(args.reread), editions=args.edition,
        scan_new=not args.no_scan, newer=None if args.newer_than is None else time.time() - args.newer_than)
    if FILERS[args.paper].series == SERIES:
        match_canberra(args.source, write=not args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
