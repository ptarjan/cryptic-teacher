#!/usr/bin/env python3
"""Read a Canberra Times puzzle's answers off the paper's printed solution grid.

    python3 tools/trove_solution_ocr.py --show <article id>   # one puzzle's reads
    python3 tools/trove_solution_ocr.py --fill                # canberra files on disk

The paper prints each puzzle's answers as a filled grid in a "Solution"
article, ~24px a cell in the page scan (tools/fetch_trove.py caches it as
<id>/grid.jpg; the scan has no larger level). Its answers are the
publisher's, so a light read here is filed as published, and only when the
read leaves no doubt:

  1. The solution article is paired with the puzzle by what it says ("the
     crossword published today", "... on Saturday", else any puzzle from the
     nine days before) and then by its black squares: the puzzle's grid must
     match the solution image's blocks better than any other candidate's.
  2. The lattice is fitted to the image's rules (paper never lies on a rule).
  3. Each light's cells are cut out and laid side by side as one word image,
     in several renderings, read by RapidOCR's recogniser (and an English
     one when present) with the alphabet cut to A-Z.
  4. A light's answer is accepted only when every letter is read surely
     (read_answers), no crossing read disagrees, and a recogniser read the
     whole light as that word. Everything else stays None for the nightly
     solve.

A solution image that is the grid itself (read_answers(tight=True), the
crop tools/file_archive_org_puzzles.py and tools/archive_org_jumbo.py take
of a page) is read by read_framed instead:

  1. The grid is straightened() (a scan's rows shear against its columns)
     and each rule found where it lies (rules(): a printed pitch is uneven);
     even lattice()s are read too, the one reading most cells surely first.
  2. The recogniser reads each light as above; a cell's sure letter counts
     unless the cell holds a clue number (run into a D or an O it reads B).
  3. Every other cell is matched to the mean glyph of each letter read
     surely in this grid, its number's corner left out, and the likeliest
     letters that make its light a known() word, by MATCH_MARGIN over any
     other, are taken (matched_letters). The match must agree with the
     recogniser: a letter some full-length read gave the cell (as printed,
     or with its number's corner blanked), and no other letter read there
     surely (in a numbered cell, read with the corner blanked: with it a T
     reads as a sure Y); a letter that leaves a crossing light neither a
     word nor a whole read is not taken.
  4. A light is accepted when every cell is read and its word is answer():
     one known() word, or words of 3+ letters run together and read whole;
     or when every cell is read surely and a recogniser read it whole as a
     sure_word(), which takes the British cryptic lexicon, names and the
     corpus's own typed answers too. A sure whole read one CONFUSABLE
     letter from the one listed() word a letter's change makes, with no
     crossing saying otherwise, is that word (swapped_reads: PIRSTREFUSAL).
     In a light half whose crossings are accepted, so is a sure read whose
     one listed() word a letter away changes a numbered cell (numbered_swaps:
     BVEREAT) or any cell (plain_swaps: BEEIZEBUB), and a sure read that is
     a listed word no other letter in its numbered cells makes another of
     (listed_reads: MOWGLI, not BINNER).
  5. On a Times print (classify), a cell classifier trained on Times
     solution grids reads every cell again, independently of the
     recogniser: an accepted light it surely reads otherwise is dropped
     (vetoed), and each light left is the listed() word its cells make
     likeliest by CLASS_MARGIN, the accepted crossings' letters held
     (classified_reads: STONECROP, read by the recogniser as STONECBAD).

read_grid_letters reads a Listener report's filled grid the same way, on
the lattice listener_grid finds and the lights of the puzzle's own grid.

RapidOCR (pip install rapidocr-onnxruntime) is optional: without it every
light stays unsolved and available() says why.
"""
import argparse
import datetime
import time
import gzip
import hashlib
import itertools
import json
import os
import pickle
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
import downloads
import media_manifest
import trove_grid

TOOLS = Path(__file__).resolve().parent

CACHE = downloads.TROVE
#: Every letter of an accepted answer is read at least this surely.
MIN_PROB = 0.9
#: ...by at least this many of the reads (renderings x recognisers x the
#: two directions); one sure read alone misreads about one light in fifty.
SURE_READS = 2
#: The puzzle's blocks must match the solution image's on this share of cells,
#: and beat the next candidate grid by PAIR_MARGIN.
PAIR_MIN, PAIR_MARGIN = 0.75, 0.05
#: How far into a cell the cut starts, as a share of the pitch: clear of the rules.
CELL_MARGIN = 0.12
AZ = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

#: An English-trained recogniser beside the bundled one reads more of these
#: letters surely; it is used when present. Fetch it once with
#:   curl -L -o ~/.cache/rapidocr/en_PP-OCRv3_rec_infer.onnx \\
#:     https://huggingface.co/SWHL/RapidOCR/resolve/main/PP-OCRv3/en_PP-OCRv3_rec_infer.onnx
EXTRA_MODELS = [Path(os.path.expanduser("~/.cache/rapidocr/en_PP-OCRv3_rec_infer.onnx"))]

_REC = None


def available():
    """None when a recogniser loads, else why not."""
    try:
        recognisers()
    except ImportError as e:
        return f"rapidocr-onnxruntime is not installed ({e})"
    return None


def recognisers():
    """[(onnx session, the vocabulary indices of blank + A-Z)], one a model."""
    global _REC
    if _REC is None:
        import onnxruntime as ort
        import rapidocr_onnxruntime
        models = [Path(rapidocr_onnxruntime.__file__).parent / "models" / "ch_PP-OCRv4_rec_infer.onnx"]
        models += [m for m in EXTRA_MODELS if m.exists()]
        import ocr_clues
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        for k, v in ocr_clues.engine_threads().items():
            setattr(opts, k, v)
        _REC = []
        for model in models:
            sess = ort.InferenceSession(str(model), opts, providers=["CPUExecutionProvider"])
            vocab = [""] + sess.get_modelmeta().custom_metadata_map["character"].splitlines() + [" "]
            _REC.append((sess, np.array([0] + [vocab.index(c) for c in AZ])))
    return _REC


def read_word(img, rec):
    """(letters, [probability of each]) for a gray word image: CTC greedy
    decoding over blank + A-Z only."""
    sess, keep = rec
    im = Image.fromarray(img).convert("RGB")
    im = im.resize((max(16, round(im.width * 48 / im.height)), 48), Image.BILINEAR)
    x = (np.asarray(im, dtype=np.float32).transpose(2, 0, 1) / 255 - 0.5) / 0.5
    p = sess.run(None, {sess.get_inputs()[0].name: x[None]})[0][0][:, keep]
    p = p / p.sum(1, keepdims=True)
    best, letters, probs, prev = p.argmax(1), [], [], 0
    for t, k in enumerate(best.tolist()):
        if k and k != prev:
            letters.append(AZ[k - 1])
            probs.append(float(p[t, k]))
        elif k and k == prev:
            probs[-1] = max(probs[-1], float(p[t, k]))
        prev = k
    return "".join(letters), probs


# ------------------------------------------------------------ geometry

def lights(grid):
    """{(number, direction): [(row, col), ...]} in the usual numbering."""
    n_rows, n_cols = len(grid), len(grid[0])
    out, number = {}, 0
    for r in range(n_rows):
        for c in range(n_cols):
            if grid[r][c] == "#":
                continue
            starts = []
            for d, (dr, dc) in (("across", (0, 1)), ("down", (1, 0))):
                before = (r - dr, c - dc)
                after = (r + dr, c + dc)
                open_before = 0 <= before[0] and 0 <= before[1] and grid[before[0]][before[1]] != "#"
                open_after = after[0] < n_rows and after[1] < n_cols and grid[after[0]][after[1]] != "#"
                if not open_before and open_after:
                    starts.append((d, dr, dc))
            if starts:
                number += 1
            for d, dr, dc in starts:
                cells, rr, cc = [], r, c
                while rr < n_rows and cc < n_cols and grid[rr][cc] != "#":
                    cells.append((rr, cc))
                    rr, cc = rr + dr, cc + dc
                out[(number, d)] = cells
    return out


def _fit_axis(paper, n):
    """(offset, pitch) putting the n+1 rules where there is least paper and
    the cell middles where there is most."""
    size, best = len(paper), None
    k = np.arange(n + 1)
    for pitch in np.arange(size / n * 0.9, size / n * 1.04, 0.05):
        offs = np.arange(-2, size - n * pitch + 2, 0.25)
        if not len(offs):
            continue
        rules = np.round(offs[:, None] + k[None, :] * pitch).astype(int)
        valid = (rules.min(1) >= 0) & (rules.max(1) < size)
        rules = np.clip(rules, 0, size - 1)
        score = -(paper[rules].sum(1) + 0.5 * paper[np.clip(rules - 1, 0, size - 1)].sum(1)
                  + 0.5 * paper[np.clip(rules + 1, 0, size - 1)].sum(1))
        mids = np.clip(np.round(offs[:, None] + (k[None, :-1] + 0.5) * pitch).astype(int), 0, size - 1)
        score = np.where(valid, score + 0.3 * paper[mids].sum(1), -1e9)
        i = int(score.argmax())
        if best is None or score[i] > best[0]:
            best = (score[i], offs[i], pitch)
    return best[1], best[2]


def lattice(gray, n, tight=False):
    """(x0, y0, pitch_x, pitch_y) of an n x n grid in the image: fitted
    within its largest patch of ink, or with `tight` (the image is the grid),
    between the frame's outer rules."""
    ink = gray < trove_grid.otsu(gray)
    if tight:
        # The frame's outer rules are the first and last lines mostly ink;
        # heavy letters mislead the rule fit over 27 cells.
        out = []
        for prof in (ink.mean(0), ink.mean(1)):
            rules = np.nonzero(prof > 0.5)[0]
            if len(rules) < 2 or rules[-1] - rules[0] < n * 5:
                raise ValueError("no frame in the image")
            out.append((float(rules[0]), (rules[-1] - rules[0]) / n))
        return out[0][0], out[1][0], out[0][1], out[1][1]
    box = trove_grid.largest_component(ink)
    if box is None:
        raise ValueError("no ink in the image")
    x0, y0, x1, y1 = box
    paper = ~ink[y0:y1, x0:x1]
    ox, pw = _fit_axis(paper.mean(0), n)
    oy, ph = _fit_axis(paper.mean(1), n)
    return x0 + ox, y0 + oy, pw, ph


#: The steepest shear (pixels across per pixel along) straightened() undoes.
MAX_SHEAR, SHEAR_STEP = 0.04, 0.002
#: How far from its even place (a share of the pitch) a rule is looked for.
RULE_REACH = 0.2


def sheared(img, sx, sy):
    """`img` with each row shifted sx pixels a row and each column sy a
    column, about its middle; paper fills the edges."""
    w, h = img.size
    return img.transform(img.size, Image.AFFINE, (1, sx, -sx * h / 2, sy, 1, -sy * w / 2),
                         resample=Image.BILINEAR, fillcolor=255)


def straightened(img):
    """A gray grid image with its rules square to its edges: a scan's rows
    and columns tilt apart (a curled page shears, it does not turn), so each
    axis takes the shear that sharpens its rules' ink profile most."""
    def sharpness(g, axis):
        prof = (np.asarray(g) < 128).mean(axis)
        return float((np.diff(prof) ** 2).sum())
    steps = np.arange(-MAX_SHEAR, MAX_SHEAR + SHEAR_STEP / 2, SHEAR_STEP)
    sy = max(steps, key=lambda s: sharpness(sheared(img, 0, s), 1))
    sx = max(steps, key=lambda s: sharpness(sheared(img, s, 0), 0))
    return sheared(img, sx, sy)


def rules(gray, grid):
    """(ys, xs): the centre of each of an image's n+1 row and column rules,
    for an image that is the grid (frame to frame, straightened()). A
    printed lattice's pitch is uneven, so each inner rule is found on its
    own, near its even place, where ink runs along every pair of lights it
    parts (a letter's stroke runs along few of them). The frame's middle
    lies between its outer edge and where the ink along the edge's lights
    stops (along a block, or a heavy letter, the whole line stays ink)."""
    n = len(grid)
    ink = gray < trove_grid.otsu(gray)
    x0, y0, pw, ph = lattice(gray, n, tight=True)

    def axis(start, pitch, across, both, edge, along):
        def span(j):
            return int(across[0] + (j + 0.2) * across[1]), int(across[0] + (j + 0.8) * across[1])
        out = [start]
        for k in range(1, n):
            guess = start + k * pitch
            lo, hi = round(guess - RULE_REACH * pitch), round(guess + RULE_REACH * pitch)
            segs = [along(lo, hi, *span(j)) for j in range(n) if both(k, j)]
            if not segs:
                out.append(guess)
                continue
            seg = np.median(segs, 0)
            top, at = seg.max(), int(seg.argmax())
            a = b = at
            while a > 0 and seg[a - 1] >= top - 0.05:
                a -= 1
            while b < len(seg) - 1 and seg[b + 1] >= top - 0.05:
                b += 1
            out.append(lo + (a + b) / 2)
        size = ink.shape[0] if along is rows else ink.shape[1]

        def inner(outer, k, step):
            lit = [span(j) for j in range(n) if edge(k, j)] or [span(j) for j in range(n)]
            at, reach = outer, round(RULE_REACH * pitch)
            while 0 <= at + step < size and abs(at + step - outer) <= reach and \
                    np.mean([along(at + step, at + step, a, b)[0] for a, b in lit]) > 0.5:
                at += step
            return at
        first, last = int(start), min(int(start + n * pitch), size - 1)
        return [(first + inner(first, 0, 1)) / 2] + out[1:] + [(last + inner(last, n - 1, -1)) / 2]

    def rows(lo, hi, a, b):
        return ink[lo:hi + 1, a:b].mean(1)

    def cols(lo, hi, a, b):
        return ink[a:b, lo:hi + 1].mean(0)
    ys = axis(y0, ph, (x0, pw), lambda k, j: grid[k - 1][j] != "#" and grid[k][j] != "#",
              lambda k, j: grid[k][j] != "#", rows)
    xs = axis(x0, pw, (y0, ph), lambda k, j: grid[j][k - 1] != "#" and grid[j][k] != "#",
              lambda k, j: grid[j][k] != "#", cols)
    return ys, xs


#: A cell's glyph is matched as a GLYPH x GLYPH image, slid up to
#: GLYPH_SHIFT pixels each way over the letter it is matched to.
GLYPH, GLYPH_SHIFT = 32, 3
#: How far into a cell its glyph is cut: wider than CELL_MARGIN, since the
#: slide keeps the rules off it.
GLYPH_MARGIN = 0.08
#: The top-left corner a printed clue number takes, as shares of the glyph:
#: wide by the number's digits, high.
NUMBER_WIDE, NUMBER_HIGH = {1: 0.45, 2: 0.62}, 0.42


def glyph(gray, ys, xs, r, c):
    """Cell (r, c)'s ink (0 paper, 1 ink) at (GLYPH + 2 GLYPH_SHIFT) square."""
    a = between(gray, ys, xs, r, c, GLYPH_MARGIN)
    side = GLYPH + 2 * GLYPH_SHIFT
    if a.size == 0:
        return np.zeros((side, side), np.float32)
    return 1 - np.asarray(Image.fromarray(a).resize((side, side), Image.BILINEAR), np.float32) / 255


def slides(g):
    """Every GLYPH-square window of a glyph(), as rows."""
    win = np.lib.stride_tricks.sliding_window_view(g, (GLYPH, GLYPH))
    return win.reshape(-1, GLYPH * GLYPH)


def middle(g):
    return g[GLYPH_SHIFT:GLYPH_SHIFT + GLYPH, GLYPH_SHIFT:GLYPH_SHIFT + GLYPH].ravel()


#: How much more of a numbered cell's corner (NUMBER_HIGH by one digit's
#: NUMBER_WIDE) must be ink than a plain light cell's, on average, for the
#: grid to print its clue numbers. Times solutions from the mid-1980s print
#: none: there the two match within 0.03; with numbers the gap is 0.2-0.6.
NUMBER_INK = 0.1


def numbers_printed(gray, ys, xs, numbers, cells):
    """Whether the grid prints the clue `numbers` ({cell: number}): their
    corners hold more ink than those of the other light `cells`."""
    def ink(rc):
        a = between(gray, ys, xs, *rc)
        h, w = a.shape
        return (a[:round(NUMBER_HIGH * h), :round(NUMBER_WIDE[1] * w)] < 128).mean() if a.size else 0.0
    plain = [ink(rc) for rc in cells if rc not in numbers]
    return not plain or np.mean([ink(rc) for rc in numbers]) - np.mean(plain) > NUMBER_INK


def unnumbered(number):
    """The glyph pixels clear of a printed clue `number` (all for None)."""
    keep = np.ones((GLYPH, GLYPH), bool)
    if number is not None:
        keep[:round(NUMBER_HIGH * GLYPH), :round(NUMBER_WIDE[min(len(str(number)), 2)] * GLYPH)] = False
    return keep.ravel()


def likeness(rows, flat, keep):
    """The best normalised correlation of any of `rows` with `flat`, on the
    pixels `keep`."""
    a, b = rows[:, keep], flat[keep]
    a = a - a.mean(1, keepdims=True)
    b = b - b.mean()
    return float(((a @ b) / (np.sqrt((a * a).sum(1) * (b * b).sum()) + 1e-6)).max())


def letter_models(glyphs, letters):
    """{letter: (its mean glyph, how many cells made it)} from the glyphs of
    the cells whose letter is known: each laid where it best fits the first."""
    out = {}
    for ch in set(letters.values()):
        cells = sorted(rc for rc, v in letters.items() if v == ch)
        first = middle(glyphs[cells[0]])
        laid = []
        for rc in cells:
            rows = slides(glyphs[rc])
            a = rows - rows.mean(1, keepdims=True)
            b = first - first.mean()
            laid.append(rows[int((a @ b).argmax())])
        out[ch] = (np.mean(laid, 0), len(cells))
    return out


def ranked(g, models, keep):
    """[(letter, likeness)] of a glyph to each letter model, best first."""
    rows = slides(g)
    return sorted(((ch, likeness(rows, m, keep)) for ch, (m, _) in models.items()), key=lambda t: -t[1])


def even(lat, n):
    """(ys, xs): the rules of lattice `lat`, evenly apart."""
    x0, y0, pw, ph = lat
    return [y0 + k * ph for k in range(n + 1)], [x0 + k * pw for k in range(n + 1)]


def between(gray, ys, xs, r, c, m=CELL_MARGIN):
    """Cell (r, c) between its rules, `m` of its size in from each."""
    h, w = ys[r + 1] - ys[r], xs[c + 1] - xs[c]
    return gray[max(0, int(ys[r] + m * h)):max(0, int(ys[r + 1] - m * h)),
                max(0, int(xs[c] + m * w)):max(0, int(xs[c + 1] - m * w))]


def cell(gray, lat, r, c, m=CELL_MARGIN):
    x0, y0, pw, ph = lat
    return gray[int(y0 + (r + m) * ph):int(y0 + (r + 1 - m) * ph),
                int(x0 + (c + m) * pw):int(x0 + (c + 1 - m) * pw)]


def word_image(cells, gap=4):
    h = max(a.shape[0] for a in cells)
    parts = [np.full((h, 2 * gap), 255, np.uint8)]
    for a in cells:
        b = np.full((h, a.shape[1]), 255, np.uint8)
        b[:a.shape[0]] = a
        parts += [b, np.full((h, gap), 255, np.uint8)]
    parts.append(np.full((h, 2 * gap), 255, np.uint8))
    return np.pad(np.concatenate(parts, 1), ((h // 3, h // 3), (0, 0)), constant_values=255)


#: A cell is a block when less than this share of its middle is paper in
#: patches wider than a speck: heavy print leaves white flecks in a block
#: and fat letters in a light, but only a light has open paper.
BLOCK_PAPER = 0.22


def opened(a, k):
    """Morphological opening of a 0/1 image by a k x k square: erase every
    patch of 1s narrower than k, keep the rest at its own size."""
    win = np.lib.stride_tricks.sliding_window_view
    p, q = k // 2, k - 1 - k // 2
    eroded = win(np.pad(a, ((p, q), (p, q)), constant_values=1), (k, k)).min((2, 3))
    return win(np.pad(eroded, ((p, q), (p, q)), constant_values=0), (k, k)).max((2, 3))


def blocks_read(gray, lat, n):
    """{(row, col): True where the solution image has a block} for n x n,
    on lattice `lat` (x0, y0, pitch_x, pitch_y) or rules (ys, xs)."""
    ys, xs = lat if len(lat) == 2 else even(lat, n)
    paper = (gray >= trove_grid.otsu(gray)).astype(np.uint8)
    paper = opened(paper, max(2, round(min(ys[-1] - ys[0], xs[-1] - xs[0]) / n / 12)))
    out = {}
    for r in range(n):
        for c in range(n):
            a = between(paper, ys, xs, r, c, 0.15)
            out[(r, c)] = None if a.size == 0 else float(a.mean()) < BLOCK_PAPER
    return out


def block_agreement(gray, grid, lat):
    """Share of cells that are blocks in the image exactly where the grid
    has one, on lattice `lat` or rules (ys, xs)."""
    seen = blocks_read(gray, lat, len(grid))
    if None in seen.values():
        return 0.0
    ok = sum(seen[(r, c)] == (ch == "#") for r, row in enumerate(grid) for c, ch in enumerate(row))
    return ok / (len(grid) * len(grid[0]))


#: A framing that reads every block of the grid a block, and at most this many of its light cells
#: as blocks too, is the puzzle's though its block_agreement is under SURE_BLOCKS: a heavy print's
#: inked letters (Times 1940s-90s), not a lattice off the grid (that misses blocks). 10-25: of the
#: Times grids read 6+ lights short, ~1 in 4 fit so at 0.94-0.969, the classifier never run on them.
HEAVY_EXTRA = 12
#: The light cells read as blocks blocks_sure lets a framing that finds every grid block have since
#: 10-25 evening: 1970s-80s Times prints ink 13-24 letters so (times-16372 13, 16549 17, 16598 20),
#: every block found, no cell classified. A lattice off the grid misses blocks (a half cell off, each
#: block cell is half paper); one that reads everything a block is far past this.
VERY_HEAVY_EXTRA = 24


def blocks_sure(gray, grid, lat, agreement=None):
    """Whether lattice `lat` of `gray` is surely `grid`'s: its block_agreement (`agreement`, when
    known) at SURE_BLOCKS, or every grid block read a block and at most VERY_HEAVY_EXTRA light cells
    read as blocks (a heavy print)."""
    if agreement is not None and agreement >= SURE_BLOCKS:
        return True
    seen = blocks_read(gray, lat, len(grid))
    if None in seen.values():
        return False
    cells = [(seen[(r, c)], ch == "#") for r, row in enumerate(grid) for c, ch in enumerate(row)]
    if sum(s == b for s, b in cells) >= SURE_BLOCKS * len(cells):
        return True
    return all(s for s, b in cells if b) and sum(1 for s, b in cells if s and not b) <= VERY_HEAVY_EXTRA


def sure_framing(framed, grid, fits):
    """The index of the framing of `framed` ([(gray, ys, xs)], framings()) whose cells the classifier
    reads: the best-fitting one by `fits` (each one's block_agreement) when blocks_sure, else the
    best-fitting other one that is; None when none is. A few pixels apart, two framings of a heavy
    print read alike (0.969 each, times-20419): the first missed one block, the other none (10-25: 1
    of 152 short Times grids with no cell classified)."""
    for i in sorted(range(len(framed)), key=lambda i: -fits[i]):
        g, ys, xs = framed[i]
        if blocks_sure(g, grid, (ys, xs), fits[i]):
            return i
    return None


# ------------------------------------------------------------ reading

#: Each light is read from these renderings of its cells; a print that is
#: too heavy for one is often clean in another.
VARIANTS = {
    "raw": lambda a: a,
    "lighter": lambda a: (255 * (a / 255.0) ** 0.6).astype(np.uint8),
    "larger": lambda a: np.asarray(Image.fromarray(a).resize((a.shape[1] * 2, a.shape[0] * 2), Image.BICUBIC)),
    "thinner": lambda a: np.asarray(Image.fromarray(a).resize((a.shape[1] * 3, a.shape[0] * 3), Image.BICUBIC)
                                    .filter(ImageFilter.MaxFilter(3))),
}


def read_lights(lts, crop):
    """(sure, full) for lights {key: [(row, col), ...]} whose cells crop(r, c)
    cuts out of the image: every light read in every rendering by every
    recogniser, a read counting only at the light's full length. sure is
    {cell: {letter: {(direction, rendering, recogniser)}}} for letters read at
    MIN_PROB; full is {light: every full-length word read for it}."""
    sure, full = {}, {}
    for key, cells in lts.items():
        crops = [crop(r, c) for r, c in cells]
        if any(x.size == 0 for x in crops):
            continue
        for (vi, render), (ri, rec) in itertools.product(enumerate(VARIANTS.values()),
                                                         enumerate(recognisers())):
            word, probs = read_word(word_image([render(x) for x in crops]), rec)
            if len(word) != len(cells):
                continue
            full.setdefault(key, set()).add(word)
            for rc, ch, p in zip(cells, word, probs):
                if p >= MIN_PROB:
                    sure.setdefault(rc, {}).setdefault(ch, set()).add((key[1], vi, ri))
    return sure, full


def sure_letters(sure):
    """{cell: letter} where SURE_READS reads give one letter surely and no read
    surely gives another (so a crossing that disagrees unreads the cell)."""
    return {rc: next(iter(v)) for rc, v in sure.items()
            if len(v) == 1 and len(next(iter(v.values()))) >= SURE_READS}


def read_grid_letters(gray, ys, xs, lts, margin=CELL_MARGIN):
    """{"letters": {cell: letter}, "grid": rows ("?" unread, "#" in no light),
    "lights": {key: word or None}, "known": [keys whose word is known()],
    "full": {key: every full-length read}} for a filled solution grid whose
    rules lie at ys and xs (a pitch of its own per cell, as listener_grid
    finds them) and whose lights are lts (reconstruct_grid.light_cells of the
    puzzle's grid). A light's word is set when every cell is read surely."""
    def crop(r, c):
        h, w = ys[r + 1] - ys[r], xs[c + 1] - xs[c]
        return gray[int(ys[r] + margin * h):int(ys[r + 1] - margin * h),
                    int(xs[c] + margin * w):int(xs[c + 1] - margin * w)]
    sure, full = read_lights(lts, crop)
    letters = sure_letters(sure)
    words = {k: "".join(letters[rc] for rc in cells) if all(rc in letters for rc in cells) else None
             for k, cells in lts.items()}
    used = {rc for cells in lts.values() for rc in cells}
    grid = ["".join(letters.get((r, c), "?") if (r, c) in used else "#" for c in range(len(xs) - 1))
            for r in range(len(ys) - 1)]
    return {"letters": letters, "grid": grid, "lights": words, "full": full,
            "known": sorted(k for k, w in words.items() if w and known(w))}


#: A glyph-matched letter must be this much likelier (in likeness, summed
#: over a light's matched cells) than the next reading that makes a word.
MATCH_MARGIN = 0.05
#: A cell's letters tried are those within MATCH_SPREAD of its best, at most
#: MATCH_TRIES of them; a light is matched with at most MATCH_CELLS unread.
MATCH_SPREAD, MATCH_TRIES, MATCH_CELLS = 0.15, 4, 3


def matched_letters(read, glyphs, numbers, lts, allowed=None, printed=None, models=None):
    """{cell: letter} for the cells `read` ({cell: letter}, the recogniser's
    sure letters of the cells with no clue number) leaves unread, by glyph:
    each is matched to the mean glyph of each letter read (letter_models),
    its clue number's corner left out (the recogniser reads a number run
    into a D or an O as a B). Only the letters `allowed` ({cell: letters}:
    the recogniser's evidence, see read_framed) are tried, and a cell whose
    best match is not allowed is left unread: the glyph and the recogniser
    must agree. A light with up to MATCH_CELLS cells unread takes the
    likeliest letters that make it an answer(), by MATCH_MARGIN over any other
    such reading; each settled letter then counts in its crossing light,
    until none settles. A crossing it fills must be known() too, or a word
    a recogniser read that light as whole (`printed`: {light key: reads};
    a name such as OTRANTO is no known() word)."""
    models = models or letter_models(glyphs, read)
    tries = {}
    for rc in glyphs:
        if rc not in read:
            rank = ranked(glyphs[rc], models, unnumbered(numbers.get(rc)))
            ok = AZ if allowed is None else allowed.get(rc, "")
            if rank and rank[0][0] in ok:
                tries[rc] = [(ch, s) for ch, s in rank[:MATCH_TRIES]
                             if s >= rank[0][1] - MATCH_SPREAD and ch in ok]
    letters, out = dict(read), {}
    through = {}
    for cells in lts.values():
        for rc in cells:
            through.setdefault(rc, []).append(cells)

    reads = {tuple(cells): (printed or {}).get(key, ()) for key, cells in lts.items()}

    def fits(cells, have):
        """Whether the light can still be a known() or printed word: with
        one cell open, some letter there makes one; with more, it may."""
        open_ = [rc for rc in cells if rc not in have]
        if len(open_) > 1:
            return True
        return any(known(w) or w in reads[tuple(cells)]
                   for w in ("".join(have.get(rc) or ch for rc in cells) for ch in (AZ if open_ else "-")))

    settled = True
    while settled:
        settled = False
        for cells in lts.values():
            open_ = [rc for rc in cells if rc not in letters]
            if not open_ or len(open_) > MATCH_CELLS or any(rc not in tries for rc in open_):
                continue
            words = []
            for combo in itertools.product(*(tries[rc] for rc in open_)):
                got = dict(zip(open_, (ch for ch, _ in combo)))
                word = "".join(letters.get(rc) or got[rc] for rc in cells)
                have = {**letters, **got}
                if answer(word, reads[tuple(cells)]) and all(fits(other, have) for rc in open_
                                                             for other in through[rc] if other is not cells):
                    words.append((sum(s for _, s in combo), got))
            words.sort(key=lambda t: -t[0])
            if words and (len(words) == 1 or words[0][0] - words[1][0] >= MATCH_MARGIN * len(open_)):
                letters.update(words[0][1])
                out.update(words[0][1])
                settled = True
    return out


def unnumbered_reads(plain, bare, glyphs, read, numbers):
    """{cell: letter} for the numbered cells of a grid that prints no clue
    numbers, read like any other cell: where the plain and corner-blanked
    reads (`plain`, `bare`: sure_letters) give one letter and it is the
    whole glyph's best match to the letters `read` elsewhere. The recogniser
    reads a light's first I as a sure T; the glyph tells them apart."""
    models = letter_models(glyphs, read)
    return {rc: ch for rc, ch in plain.items() if rc in numbers and bare.get(rc) == ch
            and best_match(glyphs[rc], models, None, ch)}


def best_match(g, models, number, ch):
    """Whether glyph `g` (its clue `number`'s corner left out) matches no
    letter model better than `ch`'s. A letter no plain cell was read as has
    no model, so no glyph can speak against it: a G printed only at the
    start of lights (GERFALCON, GATECRASH) would otherwise never be read."""
    return ch not in models or [m for m, _ in ranked(g, models, unnumbered(number))[:1]] == [ch]


def numbered_letters(lts, letters, numbers, allowed, printed):
    """{cell: letter} for the numbered cells of a grid that prints its clue
    numbers, where the number spoils the glyph match: a light whose one
    unread cell is numbered takes the one letter `allowed` there that makes
    a known() word, when that word is one word, not a run-together (an H
    read as N makes NARD + COURT), a recogniser read the light whole as it
    (`printed`) and each crossing light through the cell, read in full, is
    an answer() with it. Each settled letter counts in its crossing lights,
    until none settles."""
    letters, out = dict(letters), {}
    through = {}
    for key, cells in lts.items():
        for rc in cells:
            through.setdefault(rc, []).append(key)
    settled = True
    while settled:
        settled = False
        for key, cells in lts.items():
            open_ = [rc for rc in cells if rc not in letters]
            if len(open_) != 1 or open_[0] not in numbers:
                continue
            rc = open_[0]
            words = {ch: "".join(letters.get(x) or ch for x in cells) for ch in sorted(allowed.get(rc, ()))}
            fit = [ch for ch, w in words.items() if known(w)]
            if len(fit) != 1 or words[fit[0]] not in printed.get(key, ()) or words[fit[0]].lower() not in wordnet():
                continue
            ch = fit[0]
            if all(answer("".join(letters.get(x) or ch for x in lts[k]), printed.get(k, ()))
                   for k in through[rc] if k != key and all(x in letters or x == rc for x in lts[k])):
                letters[rc] = out[rc] = ch
                settled = True
    return out


def whole_reads(lts, letters, allowed, printed, numbered, glyphs, models):
    """{cell: letter} for lights a recogniser read whole as exactly one
    WordNet word of 4+ letters that agrees with every letter read or settled
    (`letters`) and `allowed` there. A heavy print's letters are rarely each
    read surely, yet its lights are read whole. A `numbered` cell ({cell:
    number}, a grid printing them) left open must have a letter model and
    match it best (the number makes a D a B: DROWN read as BROWN), or a
    crossing light's every read that is an answer() of 4+ letters agreeing
    with `letters` must give it that letter: the word, not the glyph, is
    the evidence, so a crossing read of the same spoilt glyph as no word
    says nothing. Each settled letter counts in its crossing lights, until
    none settles."""
    letters, out = dict(letters), {}
    through = {}
    for key, cells in lts.items():
        for rc in cells:
            through.setdefault(rc, []).append(key)

    def agree(key, w):
        return all(letters.get(rc, ch) == ch and ch in allowed.get(rc, ()) for rc, ch in zip(lts[key], w))

    def words(key):
        return {w for w in printed.get(key, ()) if len(w) >= 4 and w.lower() in wordnet() and agree(key, w)}

    whole = {}

    def crossed(key, rc, ch):
        for k in through[rc]:
            if k not in whole:
                whole[k] = {w for w in printed.get(k, ()) if len(w) >= 4 and answer(w, printed[k])}
        return any({w[lts[k].index(rc)] for w in whole[k] if agree(k, w)} == {ch} for k in through[rc] if k != key)

    settled = True
    while settled:
        settled = False
        for key, cells in lts.items():
            if all(rc in letters for rc in cells):
                continue
            fit = {w for w in words(key)
                   if all(ch in models and best_match(glyphs[rc], models, numbered[rc], ch) or crossed(key, rc, ch)
                          for rc, ch in zip(cells, w) if rc in numbered and rc not in letters)}
            if len(fit) == 1:
                w = fit.pop()
                for rc, ch in zip(cells, w):
                    if rc not in letters:
                        letters[rc] = out[rc] = ch
                settled = True
    return out


def framings(gray, grid):
    """[(gray, ys, xs)]: the lattices a grid image may lie on: its largest
    patch of ink straightened() and ruled by rules(), and (a crop that is no
    clean frame: a column cut off, a caption touching) that patch's
    lattice() between its outer rules or fitted in it, evenly apart."""
    n = len(grid)
    box = trove_grid.largest_component(gray < trove_grid.otsu(gray))
    if box is None:
        raise ValueError("no ink in the image")
    tried = []
    patch = np.asarray(straightened(Image.fromarray(gray[box[1]:box[3] + 1, box[0]:box[2] + 1])))
    try:
        ys, xs = rules(patch, grid)
        steps = np.concatenate([np.diff(ys), np.diff(xs)])
        if steps.min() > 0.5 * np.median(steps):
            tried.append((patch, ys, xs))
    except ValueError:
        pass
    for tight in (True, False):
        try:
            tried.append((gray, *even(lattice(gray, n, tight), n)))
        except ValueError:
            pass
    if not tried:
        raise ValueError("no lattice in the image")
    return tried


def read_framed(image, grid, bounded=False, classify=False, lean=False, enums=None):
    """read_answers for an image that is the grid, read on each of its
    framings(). The lattice reading the most cells surely fits best (blocks
    read alike on a lattice half a cell off; letters do not): its accepted
    lights stand, and another lattice's stand too where every cell agrees
    with the letters read so far, its sure letters first (a few pixels
    apart, two lattices cut a heavy print's letters differently, and each
    reads lights the other misses). Its "blocks" is the best framing's
    block_agreement. With `bounded`, a grid whose blocks read below
    SURE_BLOCKS keeps only its bounded() lights. With `classify` (a Times
    print, which the cell classifier was trained on) and blocks read at
    SURE_BLOCKS, or a heavy print's every block found (blocks_sure), the classifier checks every accepted light (vetoed()) and
    decodes the rest (classified_reads())."""
    gray = np.asarray(Image.open(image).convert("L"))
    framed = framings(gray, grid)
    if lean:
        # Each lattice read costs ~480 recogniser runs (~25 s of CPU). The lattice whose blocks
        # fit best is read first, and when it accepts every light the others can add none (take()
        # and the rules only fill lights not accepted): they are not read.
        fits = [round(block_agreement(g, grid, (ys, xs)), 3) for g, ys, xs in framed]
        done, nlights = {}, len(lights(grid))
        for i in sorted(range(len(framed)), key=lambda i: -fits[i]):
            done[i] = read_lattice(*framed[i], grid)
            if len(done[i][0]) == nlights:
                break
        reads = [done[i] for i in sorted(done)]
        best = max(range(len(framed)), key=lambda i: fits[i])
        blocks, lat = fits[best], framed[best]
    else:
        reads = [read_lattice(g, ys, xs, grid) for g, ys, xs in framed]
        fits = [r[1]["blocks"] for r in reads]
        best = max(range(len(reads)), key=lambda i: reads[i][1]["blocks"])
        blocks, lat = reads[best][1]["blocks"], framed[best]
    # The classifier reads a heavy print's grid too (blocks_sure): every block found, a few
    # inked letters read as blocks; on the best-fitting framing that is so (sure_framing), the
    # best one when it is.
    at = sure_framing(framed, grid, fits)
    sure = at is not None
    clat = framed[at] if sure else lat
    reads.sort(key=lambda r: -r[1]["cellsSure"])
    lts = lights(grid)
    accepted, stats, every, _ = reads[0]
    accepted = dict(accepted)
    taken = {rc: ch for key, w in accepted.items() for rc, ch in zip(lts[key], w)}

    def take(key, word):
        cells = lts[key]
        if key not in accepted and not unsettled(word, [every.get(rc) for rc in cells]) and all(
                taken.get(rc, ch) == ch for rc, ch in zip(cells, word)):
            accepted[key] = word
            taken.update(zip(cells, word))
    for more, _, _, _ in reads[1:]:
        for key, word in more.items():
            take(key, word)
    for key, word in agreed_reads(lts, reads).items():
        take(key, word)
    everys, printeds = [r[2] for r in reads], [r[3] for r in reads]
    # Each light taken settles letters for its crossings: the rules run
    # again until none takes a light.
    while True:
        before = len(accepted)
        accepted.update(crossed_reads(lts, accepted, every))
        accepted.update(numbered_swaps(lts, accepted, everys))
        accepted.update(listed_reads(lts, accepted, everys))
        accepted.update(plain_swaps(lts, accepted, everys))
        accepted.update(whole_listed(lts, accepted, printeds))
        mended = mended_reads(lts, accepted, printeds)
        accepted.update(mended)
        if len(accepted) == before and not mended:
            break
    if bounded and blocks < SURE_BLOCKS:
        seen = blocks_read(lat[0], lat[1:], len(grid))
        accepted = {key: w for key, w in accepted.items()
                    if bounded_light(lts[key], key[1], seen, w, [p.get(key, ()) for p in printeds])}
    more, probs = {}, None
    if classify and sure:
        # The classifier reads the best-fitting sure lattice's cells: an accepted
        # light it surely reads otherwise is dropped, and the lights left are
        # decoded from its letters.
        g, ys, xs = clat
        probs = classified({rc: glyph(g, ys, xs, *rc) for cells in lts.values() for rc in cells})
        dropped = vetoed(lts, accepted, probs)
        accepted = {k: w for k, w in accepted.items() if k not in dropped}
        more = classified_reads(lts, accepted, probs)
        accepted.update(more)
        stats = {**stats, "vetoed": len(dropped), "classified": len(more)}
        if blocks < SURE_BLOCKS:
            stats["heavy"] = True
        if at != best:
            stats["sureFraming"] = at
        if enums is not None:
            fit = fitted_reads(lts, accepted, probs, enums)
            accepted.update(fit)
            stats["fitted"] = len(fit)
            # A name or run-together no word list holds, read twice over: every crossing accepted.
            named = unlisted_reads(lts, accepted, probs, enums)
            accepted.update(named)
            stats["unlisted"] = len(named)
    stats = {**stats, "blocks": blocks, "accepted": len(accepted), "lattices": len(reads)}
    short = [key for key in lts if key not in accepted]
    if enums is not None and classify and sure and 0 < len(short) <= STRIP_MAX:
        g, ys, xs = clat
        strips = {k: light_strip(g, ys, xs, lts[k]) for k in short}
        # With each cell's classifier probabilities: a word the VLM gives stands only where the
        # classifier finds each of its letters possible (VLM_FLOOR).
        stats["strips"] = {f"{k[0]}-{k[1]}": {"png": png, "p": [[round(float(x), 5) for x in probs[rc]] for rc in lts[k]]}
                           for k, png in strips.items() if png}
    return accepted, stats


#: A grid read but for at most this many lights (2: on 19 partial puzzles 5 cost 21 VLM asks
#: for one completion) keeps each one's strip of cells
#: (light_strip) in its stats, for the VLM to be asked the word of.
STRIP_MAX = 2
#: The share of a cell kept in from its rule in a strip (CELL_MARGIN's 12% cuts the
#: number's corner and the stroke of a letter the print crowds to the edge).
STRIP_MARGIN = 0.04
#: The height of a strip's cells, pixels.
STRIP_HIGH = 96


def light_strip(gray, ys, xs, cells):
    """The PNG (base64 text) of light `cells` on the rules (ys, xs) of `gray`: its cells in a
    row, in order, each STRIP_HIGH pixels high, a gap between them."""
    import base64
    import io
    parts = []
    for r, c in cells:
        a = between(gray, ys, xs, r, c, STRIP_MARGIN)
        if a.size == 0:
            return None
        w = max(1, round(a.shape[1] * STRIP_HIGH / a.shape[0]))
        parts.append(np.asarray(Image.fromarray(a).resize((w, STRIP_HIGH), Image.BICUBIC)))
        parts.append(np.full((STRIP_HIGH, 12), 255, np.uint8))
    row = np.pad(np.concatenate(parts[:-1], 1), ((12, 12), (12, 12)), constant_values=255)
    buf = io.BytesIO()
    Image.fromarray(row).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


#: A grid whose blocks read on some framing at this share of cells is the
#: puzzle's: every light read off it stands.
SURE_BLOCKS = 0.97


def cell_probs(image, grid):
    """{cell: 26 letter probabilities} of the cell classifier over every light's cell of
    solution-grid `image` (the crop read_framed reads), on the framing sure_framing picks:
    the probabilities read_framed's classify step reads (its `lean` lattice). None when no
    framing's blocks are sure (blocks_sure: read_framed classifies nothing then) or no lattice
    lies on the image. Outside read_framed (solution_key stays the reader's): the uncrossed
    check of file_archive_org_puzzles asks it only of the lights it would leave out."""
    try:
        gray = np.asarray(Image.open(image).convert("L"))
        framed = framings(gray, grid)
    except (OSError, ValueError):
        return None
    if not framed:
        return None
    fits = [round(block_agreement(g, grid, (ys, xs)), 3) for g, ys, xs in framed]
    at = sure_framing(framed, grid, fits)
    if at is None:
        return None
    g, ys, xs = framed[at]
    return classified({rc: glyph(g, ys, xs, *rc) for cells in lights(grid).values() for rc in cells})


def crop_strips(image, grid, keys):
    """{"12-across": {"png", "p"}} of lights `keys` ((number, direction)) of solution-grid `image`
    (the crop read_framed reads): read_framed's stats["strips"] for them (light_strip on the
    framing sure_framing picks, with each cell's classifier probabilities), cut after the
    reading. {} when read_framed would classify nothing (no framing's blocks_sure) or no lattice
    lies on the image. Outside read_framed (solution_key stays the reader's): answers_only asks it
    of the last lights its held file and reading leave blank whose strip read_framed did not cut
    (the reading was 3+ short, or its word was dropped after: misread_word, uncrossed)."""
    try:
        gray = np.asarray(Image.open(image).convert("L"))
        framed = framings(gray, grid)
    except (OSError, ValueError):
        return {}
    if not framed:
        return {}
    fits = [round(block_agreement(g, grid, (ys, xs)), 3) for g, ys, xs in framed]
    at = sure_framing(framed, grid, fits)
    if at is None:
        return {}
    g, ys, xs = framed[at]
    lts = lights(grid)
    keys = [k for k in keys if k in lts]
    probs = classified({rc: glyph(g, ys, xs, *rc) for k in keys for rc in lts[k]})
    out = {}
    for k in keys:
        png = light_strip(g, ys, xs, lts[k])
        if png:
            out[f"{k[0]}-{k[1]}"] = {"png": png, "p": [[round(float(x), 5) for x in probs[rc]] for rc in lts[k]]}
    return out


def bounded_light(cells, direction, seen, word, wholes):
    """Whether a light read off a grid whose blocks read unsure stands: the
    cells either side of it read as blocks (or are off the grid), so the
    image has a light of its length there (another puzzle's grid ends its
    lights elsewhere; a heavy letter reading as a block inside one does
    not matter), and no lattice read the whole light as another listed word
    (a noisy print's B read as P: PASTILLE beside BASTILLE)."""
    dr, dc = (0, 1) if direction == "across" else (1, 0)
    (r0, c0), (r1, c1) = cells[0], cells[-1]
    ends = [(r0 - dr, c0 - dc), (r1 + dr, c1 + dc)]
    if not all(seen.get(rc, True) for rc in ends):
        return False
    return not any(w != word and listed(w) for read in wholes for w in read)


def agreed_reads(lts, reads):
    """{key: word} for lights two or more lattices (`reads`: read_lattice's)
    read surely in every cell as one word, the one listed() word among
    every lattice's whole reads of the light. A numbered cell's glyph match
    refuses REPINED, EGGDANCE, BASSANIO; a rival whole read that is a word
    (DOUR beside BOUR: with its number a D reads as a sure B) leaves the
    light unread."""
    out = {}
    for key, cells in lts.items():
        spelt = ["".join(every.get(rc, "?") for rc in cells) for _, _, every, _ in reads]
        words = {w for _, _, _, printed in reads for w in printed.get(key, ()) if listed(w)}
        if len(words) == 1 and spelt.count(next(iter(words))) >= 2:
            out[key] = words.pop()
    return out


def unsettled(word, sure):
    """Whether the lead lattice's `sure` letters (one per cell, None where
    unsure) leave another lattice's accepted `word` in doubt: they differ
    from it and, laid in place of its letters, still spell a listed() word
    (NONET read as NONER). Lead letters that spell no word (PB?VISO for
    PROVISO, NEWL?QK for NEWLOOK) are misreads that lattice's own cut made."""
    mine = "".join(ch or w for ch, w in zip(sure, word))
    return mine != word and bool(listed(mine))


def crossed_reads(lts, accepted, every):
    """{key: word} for lights not `accepted` whose every cell is read: the
    letter of an accepted light crossing it, else a sure letter (`every`)
    in a cell no light starts in, the two agreeing where both are read,
    and the word one listed() word. A numbered cell's own sure read is no
    letter (with its number a D reads as a sure B: DUCKINGSTOOL's D gave
    BUCKINGSTOOL), but an accepted crossing settles it (?MADEUS, ?LEANOR,
    TOI?E). Each light taken counts for its crossings, until none is
    taken."""
    numbered = {cells[0] for cells in lts.values()}
    have, out = dict(accepted), {}
    settled = True
    while settled:
        settled = False
        crossing = {rc: ch for key, w in have.items() for rc, ch in zip(lts[key], w)}
        for key, cells in lts.items():
            if key in have:
                continue
            word = ""
            for rc in cells:
                sure = every.get(rc) if rc not in numbered else None
                ch = crossing.get(rc, sure)
                if ch is None or (sure and sure != ch):
                    break
                word += ch
            else:
                if listed(word):
                    have[key] = out[key] = word
                    settled = True
                    break
    return out


def settled_reads(lts, accepted, everys, pick):
    """{key: word} for lights not `accepted` that a lattice read surely in
    every cell (`everys`, one {cell: letter} per lattice, surest first),
    where pick(word, cells, held) (held: the letters accepted lights lay)
    gives a word. The word must agree with every accepted light it
    crosses, and half or more of the lights crossing it must be accepted:
    a crop of another day's grid, or one cut a row off, reads few lights,
    and its sure letters a change from some word (TSQUARE, ACTIN). Each
    light taken counts for its crossings, until none is taken."""
    crossing = {key: [k for k, cs in lts.items() if k != key and set(cs) & set(cells)]
                for key, cells in lts.items()}
    have, out = dict(accepted), {}
    settled = True
    while settled:
        settled = False
        held = {rc: ch for key, w in have.items() for rc, ch in zip(lts[key], w)}
        for key, cells in lts.items():
            if key in have or 2 * sum(k in have for k in crossing[key]) < len(crossing[key]):
                continue
            for every in everys:
                if not all(rc in every for rc in cells):
                    continue
                word = pick("".join(every[rc] for rc in cells), cells, held)
                if word and all(held.get(rc, ch) == ch for rc, ch in zip(cells, word)):
                    have[key] = out[key] = word
                    settled = True
                    break
            if settled:
                break
    return out


def one_change(word):
    """[(i, word)]: the listed() words one letter's change in `word` makes."""
    return [(i, word[:i] + new + word[i + 1:]) for i, ch in enumerate(word) for new in AZ
            if new != ch and listed(word[:i] + new + word[i + 1:])]


def numbered_swaps(lts, accepted, everys):
    """settled_reads where a sure read is no listed() word and the one
    listed word any single letter's change makes changes a numbered cell:
    its clue number makes the sure read a misread (OVEREAT read as
    BVEREAT, IMPLORE as YMPLORE, STADDLESTONE as STABDLESTONE)."""
    numbered = {cells[0] for cells in lts.values()}

    def pick(word, cells, held):
        near = one_change(word)
        if len(near) == 1 and not listed(word) and cells[near[0][0]] in numbered:
            return near[0][1]
    return settled_reads(lts, accepted, everys, pick)


def listed_reads(lts, accepted, everys):
    """settled_reads where a sure read is a listed() word and no other
    letter in a numbered cell no accepted light crosses makes one: with
    its number a D reads as a sure B, so read_lattice's glyph match vetoes
    a numbered cell's sure letter (BINNER for DINNER, BOUR for DOUR, TRON
    for IRON), but a letter no rival word could take there stands (MOWGLI,
    REALLY, MUDINYOUREYE)."""
    numbered = {cells[0] for cells in lts.values()}

    def pick(word, cells, held):
        if listed(word) and not any(cells[i] in numbered and cells[i] not in held
                                    for i, _ in one_change(word)):
            return word
    return settled_reads(lts, accepted, everys, pick)


def plain_swaps(lts, accepted, everys):
    """settled_reads where a sure read is no listed() word and one letter's
    change, in any cell, makes exactly one listed word: a heavy print's
    sure misread (BEEIZEBUB, EVERYRODY, AOVENTURE)."""
    def pick(word, cells, held):
        near = one_change(word)
        if len(near) == 1 and not listed(word):
            return near[0][1]
    return settled_reads(lts, accepted, everys, pick)


def whole_listed(lts, accepted, printeds):
    """{key: word} for lights not `accepted` that a recogniser read whole,
    on any lattice (`printeds`: read_lattice's whole reads), as exactly one
    listed() word agreeing with every accepted light it crosses, where every
    letter change making another listed word lands in a cell an accepted
    crossing holds, and half or more of its crossings are accepted. A heavy
    print's cells are rarely each read surely, yet its lights are read
    whole (PATRONISE, PITCHER), and the crossings settle the letters a
    misread could change (HESTER for TESTER). Each light taken counts for
    its crossings, until none is taken."""
    crossing = {key: [k for k, cs in lts.items() if k != key and set(cs) & set(cells)]
                for key, cells in lts.items()}
    have, out = dict(accepted), {}
    settled = True
    while settled:
        settled = False
        held = {rc: ch for key, w in have.items() for rc, ch in zip(lts[key], w)}
        for key, cells in lts.items():
            if key in have or 2 * sum(k in have for k in crossing[key]) < len(crossing[key]):
                continue
            words = {w for p in printeds for w in p.get(key, ()) if listed(w)
                     and all(held.get(rc, ch) == ch for rc, ch in zip(cells, w))}
            if len(words) != 1:
                continue
            word = words.pop()
            if all(cells[i] in held for i, _ in one_change(word)):
                have[key] = out[key] = word
                settled = True
                break
    return out


def mended_reads(lts, accepted, printeds):
    """{key: word} for `accepted` lights whole_listed() reads otherwise with
    the light left out: its crossings, accepted, settle every letter a change
    could make another word of, and a recogniser read the light whole as
    that word. A light accepted by a run-together or a crossing's letters
    (BRAYADO, CHEAPTACK, FETAL beside PINUP) is a misread there."""
    out = {}
    for key, word in accepted.items():
        rest = {k: w for k, w in accepted.items() if k != key}
        mine = whole_listed(lts, rest, printeds).get(key)
        if mine and mine != word:
            out[key] = mine
    return out


def read_lattice(gray, ys, xs, grid):
    """(accepted, stats, sure letters, {key: whole reads}) for a grid image
    whose rules lie at ys and xs: each light accepted when every cell is read (the
    recogniser's sure letter, or for a cell with a clue number or no sure
    read, matched_letters, whole_reads, and in a grid printing its numbers
    numbered_letters) and the word is known()."""
    lts = lights(grid)
    numbers = {cells[0]: n for (n, _), cells in lts.items()}
    marked = numbers_printed(gray, ys, xs, numbers, {rc for c in lts.values() for rc in c})

    def unmarked(r, c):
        a = between(gray, ys, xs, r, c).copy()
        if (r, c) in numbers:
            h, w = a.shape
            a[:round(NUMBER_HIGH * h), :round(NUMBER_WIDE[min(len(str(numbers[(r, c)])), 2)] * w)] = 255
        return a
    sure, full = read_lights(lts, lambda r, c: between(gray, ys, xs, r, c))
    read = {rc: ch for rc, ch in sure_letters(sure).items() if rc not in numbers}
    # A cell's letter must be one some full-length read gave it, plain or
    # with its number's corner blanked, and no letter read surely there may
    # be another: either way in a plain cell, blanked in a numbered one
    # (with its number a T reads as a sure Y, a D as a sure B). Where the
    # grid prints no numbers (numbers_printed) the blanked read only adds
    # letters: blanking a bare corner makes a D a sure J, an A a sure K.
    blanked, blanked_full = read_lights(lts, unmarked)
    glyphs = {rc: glyph(gray, ys, xs, *rc) for cells in lts.values() for rc in cells}
    # Letter models come from the plain cells alone: a numbered cell's
    # glyph, laid first, shifts every model of its letter.
    models = letter_models(glyphs, read)
    if not marked:
        read.update(unnumbered_reads(sure_letters(sure), sure_letters(blanked), glyphs, read, numbers))
    allowed = {}
    for words in (full, blanked_full):
        for key, ws in words.items():
            for w in ws:
                for rc, ch in zip(lts[key], w):
                    allowed.setdefault(rc, set()).add(ch)
    for reads in (read, sure_letters(blanked) if marked else {}):
        for rc, ch in reads.items():
            allowed[rc] = allowed.get(rc, set()) & {ch}
    printed = {k: full.get(k, set()) | blanked_full.get(k, set()) for k in lts}
    matched = matched_letters(read, glyphs, numbers, lts, allowed, printed, models)
    letters = {**read, **matched}
    if marked:
        letters.update(numbered_letters(lts, letters, numbers, allowed, printed))
    letters.update(whole_reads(lts, letters, allowed, printed, numbers if marked else {}, glyphs, models))
    if marked:
        letters.update(numbered_letters(lts, letters, numbers, allowed, printed))
    # A light read_answers' plain reading accepts (every cell sure, the whole
    # word read) stands too where each numbered cell's sure letter is its
    # glyph's best match and no letter above says otherwise.
    every = sure_letters(sure)
    accepted = {}
    for key, cells in lts.items():
        if all(rc in letters for rc in cells):
            word = "".join(letters[rc] for rc in cells)
            if answer(word, printed[key]):
                accepted[key] = word
        if key not in accepted and all(rc in every for rc in cells):
            word = "".join(every[rc] for rc in cells)
            if word in full.get(key, ()) and sure_word(word) and all(
                    letters.get(rc, ch) == ch for rc, ch in zip(cells, word)) and all(
                    best_match(glyphs[rc], models, numbers[rc], ch) for rc, ch in zip(cells, word) if rc in numbers):
                accepted[key] = word
    accepted.update(swapped_reads(lts, every, full, accepted, letters))
    stats = {"lights": len(lts), "fullReads": len(full), "accepted": len(accepted),
             "cellsRead": len(read), "cellsMatched": len(matched), "cells": len(glyphs),
             "cellsSure": len(every), "blocks": round(block_agreement(gray, grid, (ys, xs)), 3)}
    return accepted, stats, every, printed


#: The letters a heavy print's sure read gives for one another: the
#: recogniser reads FIRSTREFUSAL's F as a sure P, KIDNAPPER's K as an R,
#: and on 1990s Times prints ESCRITOIRE's R as an A.
CONFUSABLE = {"F": "PE", "P": "F", "E": "F", "K": "R", "R": "K", "D": "B", "B": "D",
              "I": "T", "T": "I", "C": "G", "G": "C", "A": "R"}


def swapped_reads(lts, every, full, accepted, letters):
    """{key: word} for lights read surely in every cell (`every`) and whole
    as no sure_word(), where the one listed() word any single letter's
    change makes is a CONFUSABLE swap: PIRSTREFUSAL is FIRSTREFUSAL,
    AGREETNG is AGREEING. A second word one letter away (BADDOCK: PADDOCK,
    HADDOCK, DADDOCK) leaves the light unread: the true letter need not be
    a confusable one. Each other cell must agree with `letters`, every
    light `accepted` through the changed cell must hold the new letter
    there, and one not accepted, read surely in full, must be no word with
    the old. Each light taken counts for its crossings, until none is
    taken."""
    through = {}
    for key, cells in lts.items():
        for i, rc in enumerate(cells):
            through.setdefault(rc, []).append((key, i))
    have, out = dict(accepted), {}

    def crossed(key):
        """Whether a crossing light read surely in full is a word as read."""
        return all(rc in every for rc in lts[key]) and sure_word("".join(every[rc] for rc in lts[key]))

    settled = True
    while settled:
        settled = False
        for key, cells in lts.items():
            if key in have or not all(rc in every for rc in cells):
                continue
            word = "".join(every[rc] for rc in cells)
            if word not in full.get(key, ()) or sure_word(word) or any(
                    letters.get(rc, ch) != ch for rc, ch in zip(cells, word)):
                continue
            near = [(i, new) for i, ch in enumerate(word) for new in AZ
                    if new != ch and listed(word[:i] + new + word[i + 1:])]
            if len(near) != 1:
                continue
            i, new = near[0]
            if new in CONFUSABLE.get(word[i], "") and all(
                    have[k][j] == new if k in have else not crossed(k) for k, j in through[cells[i]] if k != key):
                have[key] = out[key] = word[:i] + new + word[i + 1:]
                settled = True
    return out


# ------------------------------------------------------------ the cell classifier

#: A second reader of a printed Times solution grid's cells, independent of
#: RapidOCR's word recogniser: a small network trained on ~125k cells of
#: Times solution grids (1940s-90s, Gale and archive.org scans), each cell's
#: glyph() labelled by the answers read_framed accepted around it. The
#: recogniser reads a heavy print's glyphs as their neighbours (STONECROP as
#: STONECBAD, BREATHINGSPACE as BDEATHINGSPXCE), and each cell once, so no
#: crossing catches it; the classifier, trained on these prints, reads them.
CELL_MODEL = TOOLS / "data" / "solution_cells.npz"
#: The model's sha256, so a retrained model is another solution_key().
CELL_MODEL_SHA = "41c734a2d238f615f3853405c8dc4aa3ee58a620488f91f11aef16c496efbe8f"
_CELLS = []


def cell_model():
    """The classifier's weights {name: float32 array}, checked against CELL_MODEL_SHA."""
    if not _CELLS:
        data = CELL_MODEL.read_bytes()
        if hashlib.sha256(data).hexdigest() != CELL_MODEL_SHA:
            raise ValueError(f"{CELL_MODEL.name} is not the model CELL_MODEL_SHA names")
        import io
        with np.load(io.BytesIO(data)) as z:
            _CELLS.append({k: z[k].astype(np.float32) for k in z.files})
    return _CELLS[0]


def classified(glyphs):
    """{cell: 26 letter probabilities} for {cell: glyph()}: the mean of the
    network's softmax over the nine GLYPH crops within a pixel of the middle."""
    if not glyphs:
        return {}
    m = cell_model()
    keys = list(glyphs)
    # Cut to a byte first, as the training glyphs were stored.
    g = (np.stack([glyphs[k] for k in keys]) * 255).astype(np.uint8).astype(np.float32) / 255
    out = 0
    for dy in (GLYPH_SHIFT - 1, GLYPH_SHIFT, GLYPH_SHIFT + 1):
        for dx in (GLYPH_SHIFT - 1, GLYPH_SHIFT, GLYPH_SHIFT + 1):
            x = g[:, dy:dy + GLYPH, dx:dx + GLYPH].reshape(len(keys), -1) - 0.25
            h = np.maximum(0, x @ m["w1"] + m["b1"])
            h = np.maximum(0, h @ m["w2"] + m["b2"])
            z = h @ m["w3"] + m["b3"]
            z = np.exp(z - z.max(1, keepdims=True))
            out = out + z / z.sum(1, keepdims=True)
    return dict(zip(keys, out / 9))


_BY_LENGTH = {}


def listed_of(n):
    """(words, letter-index array) of the listed() words of `n` letters."""
    if not _BY_LENGTH:
        listed("A")
        words = {w.upper() for w in wordnet()} | _LISTED | set(corpus_words())
        by = {}
        for w in words:
            if w.isascii() and w.isalpha():
                by.setdefault(len(w), []).append(w)
        for k, ws in by.items():
            ws.sort()
            # A-Z as 0-25 off the words' bytes (a letter a str.index each took 11 s of CPU).
            letters = np.frombuffer("".join(ws).upper().encode("ascii"), np.uint8).reshape(len(ws), k)
            _BY_LENGTH[k] = (ws, (letters.astype(np.int16) - ord("A")).astype(np.int8))
    return _BY_LENGTH.get(n, ([], np.zeros((0, n), np.int8)))


#: A light is decoded as the listed() word its cells' probabilities make
#: likeliest only by CLASS_MARGIN (log odds) over every other listed word
#: the accepted crossings leave, each of its letters at least CLASS_FLOOR
#: likely in its cell. The margin was 1000 to 1, which took none of the lights the recogniser
#: left on 13 Times prints of 1974-81 whose answers Trove prints (EPSOM, OTTER, TATTOOED,
#: FROTHING, STARCH...): at 50 to 1 the 9 it takes are all right, and with each accepted light
#: removed in turn the classifier decodes 13 of the 14 it takes between 50 and 1000 to 1 as
#: accepted (the other, CLOTHING, is a light Trove's answer and the print dispute); at under 7 to 1 it
#: is wrong 5 times in 15.
CLASS_MARGIN, CLASS_FLOOR = np.log(50), 0.01


def decoded(cells, probs, held):
    """(word, margin) of the light on `cells` as decoded(): the likeliest
    listed() word agreeing with `held` ({cell: letter}), and its log-odds
    margin over the next; (None, 0) when no word agrees."""
    ws, arr = listed_of(len(cells))
    ok = np.ones(len(ws), bool)
    score = np.zeros(len(ws))
    for i, rc in enumerate(cells):
        if rc in held:
            ok &= arr[:, i] == AZ.index(held[rc])
        else:
            score += np.log(np.maximum(probs[rc][arr[:, i]], 1e-12))
    idx = np.nonzero(ok)[0]
    if not len(idx):
        return None, 0.0
    sc = score[idx]
    order = np.argsort(-sc)
    second = sc[order[1]] if len(order) > 1 else -np.inf
    return ws[idx[order[0]]], float(sc[order[0]] - second)


def classified_reads(lts, accepted, probs):
    """{key: word} for lights not `accepted` the classifier's `probs`
    ({cell: 26 probabilities}) decode by CLASS_MARGIN, each letter at least
    CLASS_FLOOR likely: the light with the widest margin is taken first and
    its letters hold for its crossings, until none decodes."""
    have, out, memo = dict(accepted), {}, {}
    while True:
        held = {rc: ch for k, w in have.items() for rc, ch in zip(lts[k], w)}
        best = None
        for key, cells in lts.items():
            if key in have or any(rc not in probs for rc in cells) or all(rc in held for rc in cells):
                continue
            pattern = tuple(held.get(rc) for rc in cells)
            if memo.get(key, (None,))[0] != pattern:
                memo[key] = (pattern, decoded(cells, probs, held))
            word, margin = memo[key][1]
            if word is None or margin < CLASS_MARGIN:
                continue
            # Every letter, a held crossing's too: an accepted light the
            # recogniser misread (TIRINGS for TIDINGS) pins no new light
            # (PREFERRER for PREFERRED) through a cell the classifier reads
            # otherwise.
            if any(probs[rc][AZ.index(ch)] < CLASS_FLOOR for rc, ch in zip(cells, word)):
                continue
            # A surname cmudict alone lists (TROEGER for TRIGGER) is no word to win a margin.
            if name_only(word) and not cells_sure(word, cells, probs, held):
                continue
            if best is None or margin > best[0]:
                best = (margin, key, word)
        if best is None:
            return out
        have[best[1]] = out[best[1]] = best[2]


#: fitted_reads takes a light the crossings and the classifier leave one fit:
#: each cell no accepted crossing holds is read by the classifier as one letter
#: at least FIT_TOP likely, the pieces of the light's enumeration are listed
#: words, and no other listed word of a piece's length agrees with the held
#: letters while each of its other letters is at least FIT_RIVAL likely in its
#: cell. (classified_reads wants a 1000-to-1 margin over every rival and no
#: phrase: a light of "4,4,3,3" is no listed word, and a rival one letter
#: off at 5% is a margin of 20 to 1 however sure the rest.)
FIT_TOP, FIT_RIVAL = 0.6, 0.05


def pieces_of(enum, n):
    """The lengths of the words of enumeration `enum` ("4,4,3,3", "5-4", "3,2-4")
    when they are two or more and add up to `n`, else [n]."""
    parts = [int(x) for x in re.findall(r"\d+", enum or "")]
    return parts if len(parts) > 1 and sum(parts) == n else [n]


def piece_listed(word, multi):
    """Whether `word`, a piece of a light, is a word: listed(), and for a short piece of a
    phrase (the junk of cmudict: AW, EL) one of SHORT_WORDS or WordNet's three-letter lemmas."""
    if not multi or len(word) > 3:
        return listed(word)
    w = word.lower()
    return w in SHORT_WORDS or (len(w) == 3 and w in wordnet())


def fit_rivals(word, cells, probs, held):
    """The listed() words of `word`'s length other than it that agree with `held` and are at
    least FIT_RIVAL likely in each cell held does not hold."""
    ws, arr = listed_of(len(word))
    ok = np.ones(len(ws), bool)
    for i, rc in enumerate(cells):
        if rc in held:
            ok &= arr[:, i] == AZ.index(held[rc])
        else:
            ok &= probs[rc][arr[:, i]] >= FIT_RIVAL
    return [ws[i] for i in np.nonzero(ok)[0] if ws[i] != word]


def fitted(cells, probs, held, enum):
    """(word, least top probability) of the light on `cells` as fitted_reads takes it, or None."""
    if any(rc not in probs for rc in cells):
        return None
    if any(rc in held and probs[rc][AZ.index(held[rc])] < CLASS_FLOOR for rc in cells):
        return None
    unheld = [rc for rc in cells if rc not in held]
    top = {rc: int(np.argmax(probs[rc])) for rc in unheld}
    if any(probs[rc][top[rc]] < FIT_TOP for rc in unheld):
        return None
    if not unheld and any(probs[rc][AZ.index(held[rc])] < FIT_RIVAL for rc in cells):
        return None
    word = "".join(held[rc] if rc in held else AZ[top[rc]] for rc in cells)
    sizes = pieces_of(enum, len(cells))
    multi = len(sizes) > 1
    at = 0
    for size in sizes:
        piece, span = word[at:at + size], cells[at:at + size]
        at += size
        if not piece_listed(piece, multi):
            return None
        if name_only(piece) and not cells_sure(piece, span, probs, held):
            return None
        if any(rc not in held for rc in span) and fit_rivals(piece, span, probs, held):
            return None
    return word, min([float(probs[rc][top[rc]]) for rc in unheld], default=1.0)


def fitted_reads(lts, accepted, probs, enums=None):
    """{key: word} for lights not `accepted` that fitted() takes, the surest first; its letters
    hold for its crossings, until none is taken. `enums` is {key: enumeration text}."""
    have, out = dict(accepted), {}
    enums = enums or {}
    while True:
        held = {rc: ch for k, w in have.items() for rc, ch in zip(lts[k], w)}
        best = None
        for key, cells in lts.items():
            if key in have:
                continue
            got = fitted(cells, probs, held, enums.get(key))
            if got and (best is None or got[1] > best[0]):
                best = (got[1], key, got[0])
        if best is None:
            return out
        have[best[1]] = out[best[1]] = best[2]


#: unlisted_reads takes a light no listed() word fills (a name, a phrase run together: ARCOT,
#: INVERESK, ST SWITHINS DAY) only where every letter is read twice over: each cell the classifier
#: reads as the light's letter at least UNLISTED_TOP likely, every cell another light crosses held
#: by an accepted crossing (so only unchecked cells stand on the classifier alone, and there no other
#: letter is even CLASS_FLOOR likely: RUSIIC for RUSTIC, T at 0.014, on a 2007 print), its length the
#: enumeration's, and no listed word (of the light, or of a piece of its enumeration) one unchecked
#: letter away from it: BALINITY, which a 1973 print's recogniser and VLM both read for SALINITY.
UNLISTED_TOP = 0.9


def one_away(word, cells, held):
    """Whether a listed() word of `word`'s length agrees with `held` ({cell: letter}) and differs
    from `word` in exactly one cell `held` does not hold."""
    ws, arr = listed_of(len(word))
    if not len(ws):
        return False
    mine = np.array([AZ.index(ch) for ch in word], np.int8)
    ok = np.ones(len(ws), bool)
    diff = np.zeros(len(ws), np.int16)
    for i, rc in enumerate(cells):
        if rc in held:
            ok &= arr[:, i] == mine[i]
        else:
            diff += arr[:, i] != mine[i]
    return bool((ok & (diff == 1)).any())


def unlisted(cells, probs, held, enum, crossed):
    """The word unlisted_reads takes on `cells`, or None. `crossed` is the cells another light
    crosses, `held` the accepted lights' letters."""
    if any(rc not in probs for rc in cells) or any(rc in crossed and rc not in held for rc in cells):
        return None
    parts = [int(x) for x in re.findall(r"\d+", enum or "")]
    if not parts or sum(parts) != len(cells):
        return None
    top = [int(np.argmax(probs[rc])) for rc in cells]
    if any(probs[rc][t] < UNLISTED_TOP for rc, t in zip(cells, top)):
        return None
    # An unchecked cell stands on the classifier alone: no other letter even CLASS_FLOOR likely there.
    if any(rc not in held and np.sort(probs[rc])[-2] >= CLASS_FLOOR for rc in cells):
        return None
    word = "".join(AZ[t] for t in top)
    if any(held.get(rc, ch) != ch for rc, ch in zip(cells, word)):
        return None
    if all(rc in held for rc in cells) or one_away(word, cells, held):
        return None
    at = 0
    for size in (parts if len(parts) > 1 else ()):
        span = cells[at:at + size]
        if one_away(word[at:at + size], span, held):
            return None
        at += size
    return word


def unlisted_reads(lts, accepted, probs, enums):
    """{key: word} for lights not `accepted` that unlisted() takes, each against the accepted
    lights alone (a light it takes holds no cell for another). `enums` is {key: enumeration}."""
    held = {rc: ch for k, w in accepted.items() for rc, ch in zip(lts[k], w)}
    count = {}
    for cells in lts.values():
        for rc in cells:
            count[rc] = count.get(rc, 0) + 1
    out = {}
    for key, cells in lts.items():
        if key in accepted:
            continue
        word = unlisted(cells, probs, held, (enums or {}).get(key), {rc for rc in cells if count[rc] > 1})
        if word:
            out[key] = word
    return out


#: The log odds by which the classifier must read an accepted light's cells
#: as another listed() word, or (for a word not listed: a run-together)
#: as its own likeliest letters, and by which a crossing light not accepted
#: must decode (decoded(), the other accepted lights held) to a letter
#: contradicting it, for the light to be dropped (vetoed). Either alone drops
#: correct lights (a light's own cells: UNION, SINAI, RECOUNTS on a 1974
#: print, up to e^38; a crossing alone: up to a sole fit), both together
#: none of 993 on 44 model-solved prints (5 of the recogniser's 25 misreads
#: dropped), each puzzle scored by a model that never saw it.
VETO_MARGIN = np.log(100)


def likelihood(cells, probs, word):
    """The log likelihood of `word` in `cells` by the classifier's `probs`."""
    return float(sum(np.log(max(probs[rc][AZ.index(ch)], 1e-12)) for rc, ch in zip(cells, word)))


def vetoed(lts, accepted, probs):
    """The keys of `accepted` lights the classifier reads otherwise, each on
    its own cells, by VETO_MARGIN: as another listed() word (a 1970s Gale
    print's recogniser accepted BISHER for FISHER, BLIP for CLIP, HOWLER for
    BOWLER), or, for a word not listed (a run-together: A + TILTS for STILTS,
    BASSING + BUT for PASSINGOUT), as its likeliest letter in each cell; and
    some crossing light not accepted decodes, the other accepted lights held,
    by VETO_MARGIN to a letter in a shared cell other than the light's."""
    out = set()
    where = {}
    for key, cells in lts.items():
        for i, rc in enumerate(cells):
            where.setdefault(rc, []).append((key, i))
    for key, word in accepted.items():
        cells = lts[key]
        if any(rc not in probs for rc in cells):
            continue
        own = likelihood(cells, probs, word)
        if listed(word):
            rival, _ = decoded(cells, probs, {})
            if not rival or rival == word or likelihood(cells, probs, rival) - own < VETO_MARGIN:
                continue
        elif sum(float(np.log(max(probs[rc].max(), 1e-12))) for rc in cells) - own < VETO_MARGIN:
            continue
        held = {rc: ch for k, w in accepted.items() if k != key for rc, ch in zip(lts[k], w)}
        for i, rc in enumerate(cells):
            crossed = [(k, j) for k, j in where[rc] if k != key and k not in accepted
                       and all(c in probs for c in lts[k])]
            if any(w2 and w2[j] != word[i] and mg >= VETO_MARGIN
                   for (k, j) in crossed for w2, mg in [decoded(lts[k], probs, held)]):
                out.add(key)
                break
    return out


def read_answers(image, grid, tight=False, bounded=False, classify=False, lean=False, enums=None):
    """({(number, direction): answer} accepted, stats) for a solution image
    and the puzzle's grid (rows of "#" and ".").

    With `tight` (the image is the grid, frame to frame) it is read_framed
    (`bounded` and `classify` passed on).
    Else cells are read by read_lights and sure_letters. A light is accepted when every one of its cells is read, some
    recogniser read the light itself as exactly that word, and the word is
    known()."""
    if tight:
        return read_framed(image, grid, bounded, classify, lean, enums)
    gray = np.asarray(Image.open(image).convert("L"))
    lat = lattice(gray, len(grid), tight)
    lts = lights(grid)
    sure, full = read_lights(lts, lambda r, c: cell(gray, lat, r, c))
    read = sure_letters(sure)
    accepted = {}
    for key, cells in lts.items():
        if all(rc in read for rc in cells):
            word = "".join(read[rc] for rc in cells)
            if word in full.get(key, ()) and sure_word(word):
                accepted[key] = word
    stats = {"lights": len(lts), "fullReads": len(full), "accepted": len(accepted),
             "cellsRead": len(read), "cells": len({rc for c in lts.values() for rc in c}),
             # Cells read surely from both directions, and how many of them clash.
             "sureCrossings": sum(1 for v in sure.values()
                                  if {"across", "down"} <= {r[0] for rs in v.values() for r in rs}),
             "sureClashes": sum(1 for v in sure.values() if len(v) > 1),
             "blocks": round(block_agreement(gray, grid, lat), 3)}
    return accepted, stats


_WORDS = None
#: The only words under four letters a run-together answer may contain:
#: WordNet's others are mostly abbreviations (RU + GE would pass RUGE).
SHORT_WORDS = {"a", "i", "am", "an", "as", "at", "be", "by", "do", "go", "he", "if",
               "in", "is", "it", "me", "my", "no", "of", "on", "or", "so", "to", "up",
               "us", "we", "all", "and", "any", "are", "but", "can", "for", "get", "had",
               "has", "her", "him", "his", "how", "man", "men", "new", "not", "now",
               "old", "one", "out", "own", "pen", "put", "red", "run", "say", "see",
               "set", "she", "the", "too", "two", "way", "who", "why", "you"}


#: The regular inflections known() adds to every lemma.
ENDINGS = ("s", "ed", "ing", "er", "est")
#: The endings that inflect only a lemma ending in e (wise: wised, wiser,
#: wisest). On any other lemma they make a misread a word: WOOF + R passed
#: WOOER read as WOOFR.
E_ENDINGS = ("d", "r", "st")
#: The endings after which a plural takes -es (box, bush, church, potato).
ES_AFTER = ("s", "x", "z", "ch", "sh", "o")


def answer(word, reads):
    """Whether a light's letters may be filed: one known() word, or words of
    three letters or more run together that a recogniser read the light as
    whole (`reads`). A misread letter leaves junk run-togethers: HALLEY
    read as A + ALLEY, ADDISON as A + DO + IS + ON."""
    if not known(word):
        return False
    w = word.lower()
    if w in wordnet():
        return True
    ends = {0}
    for i in range(3, len(w) + 1):
        if any(j in ends and w[j:i] in wordnet() for j in range(i - 2)):
            ends.add(i)
    return word in reads and len(w) in ends


def wordnet():
    """The words known() builds on: WordNet's lemmas, their regular
    inflections and SHORT_WORDS, loaded on first use."""
    global _WORDS
    if _WORDS is None:
        with gzip.open(TOOLS / "data" / "wordnet.json.gz", "rt", encoding="utf-8") as f:
            lemmas = {re.sub(r"[^a-z]", "", w.lower()) for w in json.load(f)["words"]}
        _WORDS = lemmas | SHORT_WORDS
        for w in (w for w in lemmas if len(w) > 2):
            _WORDS.update(w + end for end in ENDINGS)
            if w.endswith("e"):
                _WORDS.update(w + end for end in E_ENDINGS)
                _WORDS.update((w[:-1] + "ing", w[:-1] + "ed"))
            if w.endswith(ES_AFTER):
                _WORDS.add(w + "es")
            if w.endswith("y"):
                _WORDS.update((w[:-1] + "ies", w[:-1] + "ied"))
    return _WORDS


def known(word):
    """Whether an answer is WordNet's (a lemma or a regular inflection of one),
    or up to four such words run together, each of four letters or more
    unless it is one of SHORT_WORDS. A misread letter rarely leaves a
    word: RUSE read as RUGE is caught here."""
    words = wordnet()
    w = word.lower()
    parts = {0: 0}   # prefix length -> fewest words that spell it
    for i in range(1, len(w) + 1):
        best = min((parts[j] + 1 for j in parts if j < i and w[j:i] in words
                    and (i - j > 3 or w[j:i] in SHORT_WORDS or (j, i) == (0, len(w)))),
                   default=None)
        if best is not None and best <= 4:
            parts[i] = best
    return len(w) in parts


_LISTED = None


def sure_word(word):
    """Whether a light read surely in every cell and whole as `word` may be
    filed: a known() word, or one of tools/data/lexicon.tsv's (UKACD, the
    British cryptic word list: REDINGOTE, OLOROSO, WHODUNNIT are no
    WordNet words), cmudict's (names: HILARY, GLADYS, OSRIC) or
    corpus_words()' (phrases: HOLIERTHANTHOU, LEFTOFF, GOBETWEEN). A letter
    misread surely still leaves no word there (PIRSTREFUSAL, AGREETNG). Glyph-matched letters stay with known(): a
    wider list gives a guessed letter more words to land on."""
    return known(word) or listed(word)


def listed(word):
    """Whether `word` is one listed word, no run-together: WordNet's (a lemma
    or a regular inflection), tools/data/lexicon.tsv's, cmudict's or
    corpus_words()'."""
    global _LISTED, _LEXICON
    if _LISTED is None:
        with open(TOOLS / "data" / "lexicon.tsv", encoding="utf-8") as f:
            _LEXICON = {line.split("\t", 1)[0] for line in f if not line.startswith("#")}
        with gzip.open(TOOLS / "data" / "cmudict.txt.gz", "rt", encoding="utf-8") as f:
            _LISTED = _LEXICON | {line.split("\t", 1)[0].upper() for line in f if not line.startswith("#")}
    known("A")
    return word.lower() in wordnet() or word.upper() in _LISTED or word.upper() in corpus_words()


_LEXICON = None


def name_only(word):
    """Whether `word` is listed() by cmudict alone, no dictionary's word: ~60,000 of its 122,000
    are surnames and spellings of names (TROEGER, which the classifier decoded at 50 to 1 for a
    1974 print's TRIGGER, its I and G misread). Such a word stands on the evidence a word no list
    holds needs (unlisted_reads'), not on a margin over listed rivals."""
    listed("A")
    w = word.upper()
    return w in _LISTED and w not in (_LEXICON or ()) and word.lower() not in wordnet() and w not in corpus_words()


def cells_sure(word, cells, probs, held):
    """Whether each cell of `cells` that `held` ({cell: letter}) does not hold reads its letter of
    `word` at least UNLISTED_TOP likely."""
    return all(rc in held or probs[rc][AZ.index(ch)] >= UNLISTED_TOP for rc, ch in zip(cells, word))


#: clue_reads (a clue-constrained read of a Times grid 6+ lights short): a light is taken as the
#: likeliest candidate (fit_candidates) by CLUE_MARGIN log odds over the next, each cell no taken
#: crossing holds at least CLUE_FLOOR likely, none the classifier reads as another letter at CLUE_SURE.
#: Candidates are the listed words of each piece of the light's enumeration within CLUE_TOL of the
#: best piece, CLUE_CAP of them at most. 10-25, held out 5-fold on the known lights of 192 Times
#: puzzles 6+ short: 2,460 taken, 0 wrong by their clues (12 differ from the held file: its OCR's
#: MEACURE, BANDORA, BUM for RUM...).
CLUE_MARGIN, CLUE_FLOOR, CLUE_SURE = np.log(1000), 0.05, 0.9
CLUE_TOL, CLUE_CAP = np.log(1e4), 400


def _piece_candidates(cells, probs, held, multi):
    """[(word, log score)] of listed words for the piece on `cells`, agreeing with `held`, within
    CLUE_TOL of the best, best first (a short piece of a phrase: piece_listed's words only)."""
    ws, arr = listed_of(len(cells))
    if not len(ws):
        return []
    if multi and len(cells) <= 3:
        ok = np.array([piece_listed(w, True) for w in ws], bool)
    else:
        ok = np.ones(len(ws), bool)
    score = np.zeros(len(ws))
    for i, rc in enumerate(cells):
        if rc in held:
            ok &= arr[:, i] == AZ.index(held[rc])
        else:
            score += np.log(np.maximum(probs[rc][arr[:, i]], 1e-12))
    idx = np.nonzero(ok)[0]
    if not len(idx):
        return []
    sc = score[idx]
    keep = idx[sc >= sc.max() - CLUE_TOL]
    keep = keep[np.argsort(-score[keep], kind="stable")][:CLUE_CAP]
    return [(ws[i], float(score[i])) for i in keep]


def fit_candidates(cells, probs, held, enum):
    """[(word, log score)] of the light on `cells`: its enumeration's pieces' candidates
    (_piece_candidates) run together, within CLUE_TOL of the best, best first, CLUE_CAP at most."""
    sizes = pieces_of(enum, len(cells))
    multi = len(sizes) > 1
    out, at = [("", 0.0)], 0
    for s in sizes:
        span = cells[at:at + s]
        at += s
        if all(rc in held for rc in span):
            pl = [("".join(held[rc] for rc in span), 0.0)]
        else:
            pl = _piece_candidates(span, probs, held, multi)
        if not pl:
            return []
        nxt = [(a + w, x + y) for a, x in out for w, y in pl]
        best = max(x for _, x in nxt)
        out = sorted([c for c in nxt if c[1] >= best - CLUE_TOL], key=lambda c: -c[1])[:CLUE_CAP]
    return out


def clue_fit_ok(word, cells, probs, held, enum):
    """Whether `word` may stand on `cells`: each cell `held` does not hold at least CLUE_FLOOR
    likely and read as no other letter at CLUE_SURE, and a piece only a name list holds read
    surely (cells_sure)."""
    for rc, ch in zip(cells, word):
        if rc in held:
            continue
        p = probs[rc]
        if p[AZ.index(ch)] < CLUE_FLOOR or (p.max() >= CLUE_SURE and int(np.argmax(p)) != AZ.index(ch)):
            return False
    at = 0
    for size in pieces_of(enum, len(cells)):
        if name_only(word[at:at + size]) and not cells_sure(word[at:at + size], cells[at:at + size], probs, held):
            return False
        at += size
    return True


def clue_reads(lts, accepted, probs, enums):
    """({key: word} taken, {key: candidates} of each light left open) of grid lights `lts` past the
    `accepted` ones ({key: word}), by the classifier's `probs` and the clues' enumerations `enums`
    ({key: text}). Each open light's candidates (fit_candidates, on the taken letters) are pruned by
    its open crossings' (a letter no candidate of the crossing has there goes, unless the two share
    none: then a truth lies outside a list); the light whose best candidate leads by CLUE_MARGIN
    and fits (clue_fit_ok) is taken, the widest margin first, its letters held, until none is."""
    have, out = dict(accepted), {}
    while True:
        held = {rc: ch for k, w in have.items() for rc, ch in zip(lts[k], w)}
        C = {}
        for key, cells in lts.items():
            if key in have or any(rc not in probs for rc in cells):
                continue
            if any(rc in held and probs[rc][AZ.index(held[rc])] < CLASS_FLOOR for rc in cells):
                continue
            C[key] = fit_candidates(cells, probs, held, enums.get(key))
        where = {}
        for key in C:
            for i, rc in enumerate(lts[key]):
                where.setdefault(rc, []).append((key, i))
        changed = True
        while changed:
            changed = False
            for occ in where.values():
                if len(occ) < 2:
                    continue
                (a, i), (b, j) = occ[0], occ[1]
                if not C[a] or not C[b]:
                    continue
                both = {w[i] for w, _ in C[a]} & {w[j] for w, _ in C[b]}
                if not both:
                    continue
                na = [c for c in C[a] if c[0][i] in both]
                nb = [c for c in C[b] if c[0][j] in both]
                if len(na) < len(C[a]) or len(nb) < len(C[b]):
                    C[a], C[b] = na, nb
                    changed = True
        best = None
        for key, cs in C.items():
            if not cs:
                continue
            w, s = cs[0]
            m = s - cs[1][1] if len(cs) > 1 else np.inf
            if m < CLUE_MARGIN or not clue_fit_ok(w, lts[key], probs, held, enums.get(key)):
                continue
            if best is None or m > best[0]:
                best = (m, key, w)
        if best is None:
            return out, C
        have[best[1]] = out[best[1]] = best[2]


#: The repo whose committed puzzles/ corpus_words() reads (tests point it at
#: a scratch git tree), and the channels and solution origins it trusts: a
#: person typed these answers. An OCR read of a page (newspaper, book) or a
#: model's solve is left out, so a misread filed once never vouches for
#: itself. Clue words are left out too: a typo in a clue (the Guardian's
#: "Ecstacy" in cryptic-23537) vouched for a misread ECSTASY.
CORPUS_ROOT = TOOLS.parent
CORPUS_CHANNELS = ("publisher", "wayback", "blog", "authored")
CORPUS_ORIGINS = ("published", "writeup", "authored")
_CORPUS = {}
_PUZZLE_FILE = re.compile(r"puzzles/[^/]+/[^/]+/[^/]+-[0-9]+\.json")


def _corpus_answers(body):
    """The answers, space-separated, a puzzle file's bytes give
    corpus_words()."""
    pz = json.loads(body)
    if ((pz.get("source") or {}).get("retrievedFrom") not in CORPUS_CHANNELS
            or (pz.get("solutions") or {}).get("origin") not in CORPUS_ORIGINS):
        return ""
    return " ".join(sorted({re.sub(r"[^A-Z]", "", e["solution"].upper())
                            for e in pz.get("entries") or [] if e.get("solution")} - {""}))


def corpus_words():
    """The answers of CORPUS_ROOT's committed puzzle files from a CORPUS_CHANNELS source with a
    CORPUS_ORIGINS solution, upper case. Each file's words are cached by its
    git blob in the git common dir, so a run parses only the files changed
    since the last, and the set itself by the blobs it was made of; outside
    a git checkout the set is empty."""
    key = str(CORPUS_ROOT)
    if key in _CORPUS:
        return _CORPUS[key]
    git = ["git", "-C", str(CORPUS_ROOT)]
    listed = subprocess.run(git + ["ls-files", "-s", "-z", "--", "puzzles"], capture_output=True, text=True,
                            check=False)
    common = subprocess.run(git + ["rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=False)
    if listed.returncode or common.returncode:
        _CORPUS[key] = frozenset()
        return _CORPUS[key]
    blobs = {rec.split("\t", 1)[0].split()[1] for rec in listed.stdout.split("\0")
             if "\t" in rec and _PUZZLE_FILE.fullmatch(rec.split("\t", 1)[1])}
    store = Path(common.stdout.strip()) / "ct-corpus-answers.pickle"
    merged = store.with_name("ct-corpus-answers.txt")
    digest = hashlib.sha1(" ".join(sorted(blobs)).encode()).hexdigest()
    try:
        with open(merged, encoding="utf-8") as f:
            if f.readline().strip() == digest:
                _CORPUS[key] = frozenset(f.read().split())
                return _CORPUS[key]
    except OSError:
        pass
    try:
        with open(store, "rb") as f:
            cached = pickle.load(f)
    except (OSError, EOFError, pickle.UnpicklingError):
        cached = {}
    fresh = sorted(blobs - cached.keys())
    if fresh:
        out = subprocess.run(git + ["cat-file", "--batch"], input="\n".join(fresh).encode() + b"\n",
                             capture_output=True, check=True).stdout
        pos = 0
        while pos < len(out):
            nl = out.index(b"\n", pos)
            sha, _, size = out[pos:nl].split()
            cached[sha.decode()] = _corpus_answers(out[nl + 1:nl + 1 + int(size)])
            pos = nl + 2 + int(size)
    if fresh or cached.keys() - blobs:
        cached = {b: cached[b] for b in blobs}
        with tempfile.NamedTemporaryFile("wb", dir=store.parent, delete=False) as f:
            pickle.dump(cached, f)
        os.replace(f.name, store)
    _CORPUS[key] = frozenset(" ".join(cached[b] for b in blobs).split())
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=store.parent, delete=False) as f:
        f.write(digest + "\n" + "\n".join(sorted(_CORPUS[key])))
    os.replace(f.name, merged)
    return _CORPUS[key]


# ------------------------------------------------------------ pairing

def _day(text):
    m = re.search(r"\w+day (\d{1,2} \w+ \d{4})", text)
    try:
        return datetime.date(*time.strptime(m.group(1), "%d %B %Y")[:3]) if m else None
    except ValueError:
        return None


_ARTICLES = {}


def _read_article(d):
    """(print day or None, is a solution) read from an article dir, or None
    when meta.json is unreadable."""
    try:
        title = json.loads((d / "meta.json").read_text()).get("title", "")
    except (OSError, ValueError):
        return None
    first = (d / "ocr.txt").read_text(encoding="utf-8", errors="replace")[:400]
    day = _day(first.splitlines()[0] if first else "")
    return day, "solution" in title.lower().split(" - trove")[0]


def _articles_index_path(cache):
    key = hashlib.sha1(str(cache).encode()).hexdigest()[:10]
    return Path.home() / ".cache" / "cryptic-teacher" / f"trove-articles-{key}.json"


def _listed(cache):
    """[(article dir, index key, solution or None)] for each cached article
    with a grid image. On the media disk, once trove-titles is complete,
    from the SSD memos (titles; trove-inputs' files string holds the grid's
    presence and every file's size and mtime): nothing on the disk is
    listed or statted, bar an article trove-inputs lacks, taken off the
    disk once and appended (file_trove_puzzles._inputs_off_disk). Else the
    cache is listed and statted."""
    if media_manifest.on_media(cache) and media_manifest.complete(media_manifest.TROVE_TITLES):
        import file_trove_puzzles
        titles = media_manifest.memo(media_manifest.TROVE_TITLES, "article", "title")
        inputs = file_trove_puzzles.trove_inputs()
        for name in sorted(a for a in titles if a):
            held = inputs.get(name, {})
            if "files" not in held:
                held = file_trove_puzzles._inputs_off_disk(cache / name, held)
            if "grid.jpg:-" not in held["files"]:
                yield cache / name, held["files"], "solution" in (titles[name] or "").lower().split(" - trove")[0]
        return
    for d in sorted(cache.iterdir()) if cache.exists() else ():
        try:
            if not (d / "grid.jpg").exists():
                continue
            key = [(d / "meta.json").stat().st_mtime_ns, (d / "ocr.txt").stat().st_mtime_ns]
        except OSError:
            continue
        yield d, key, None


def _articles(cache):
    """[(print day, article dir, is a solution)] for every cached article with
    a grid image, read once a process. What each dir held is kept in a file
    keyed by its files (_listed), so a process reads only the new or changed
    ones."""
    if cache in _ARTICLES:
        return _ARTICLES[cache]
    out = _ARTICLES[cache] = []
    index_path = _articles_index_path(cache)
    try:
        old = json.loads(index_path.read_text())
    except (OSError, ValueError):
        old = {}
    new = {}
    for d, key, solution in _listed(cache):
        got = old.get(d.name)
        if got and len(got) == 3 and got[0] == key:
            read = (datetime.date.fromisoformat(got[1]) if got[1] else None, got[2])
        else:
            read = _read_article(d)
            if read is None:
                continue
        if solution is not None:
            read = (read[0], solution)
        new[d.name] = [key, read[0].isoformat() if read[0] else None, read[1]]
        if read[0]:
            out.append((read[0], d, read[1]))
    if new != old:
        try:
            index_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = index_path.with_name(f"{index_path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(new))
            os.replace(tmp, index_path)
        except OSError:
            pass
    return out


def lag_allowed(ocr_head, lag, puzzle_day):
    """Whether a solution article's own words allow a puzzle `lag` days earlier."""
    low = re.sub(r"\s+", " ", ocr_head.lower())
    if "published today" in low:
        return lag == 0
    m = re.search(r"published on\W*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", low)
    if m:
        return 0 < lag <= 7 and puzzle_day.strftime("%A").lower() == m.group(1)
    return 0 <= lag <= 9


def fits(gray, grid, rivals):
    """(how well the solution image `gray` fits `grid` (block_agreement), [how
    well it fits each rival puzzle image's grid]), or None when no lattice
    fits the image. `rivals` are the images (paths or files) of the other
    puzzles printed in the solution's window."""
    try:
        lat = lattice(gray, len(grid))
    except ValueError:
        return None
    mine = block_agreement(gray, grid, lat)
    rival = []
    for image in rivals:
        g, _ = trove_grid.read_grid(image)
        if g and len(g) == len(grid) and g != list(grid):
            rival.append(block_agreement(gray, g, lat))
    return mine, rival


def fits_anywhere(solution, grid, rivals):
    """fits() of the solution image file and the rival image files, run on the
    desktop when tools/ocr_remote.py can (the lattice search and each
    rival's grid read are ~1-10 s of numpy and pure Python a solution
    candidate, and the images are the only thing sent), else here in a
    local_slot()."""
    import ocr_remote
    blobs = [Path(p).read_bytes() for p in (solution, *rivals)]
    got = ocr_remote.call("solution_fits", [list(r) if not isinstance(r, str) else r for r in grid],
                          [len(b) for b in blobs], data=b"".join(blobs))
    if got is None or "fit" not in got[0]:
        with ocr_remote.local_slot():
            return fits(np.asarray(Image.open(solution).convert("L")), grid, rivals)
    fit = got[0]["fit"]
    return None if fit is None else (fit[0], list(fit[1]))


def fits_there(data, grid, sizes):
    """({"fit": fits() or None}, b"") of the solution image and rival images
    packed in `data` (their `sizes` in order), run on the desktop (CALLS)."""
    import io
    images, at = [], 0
    for size in sizes:
        images.append(io.BytesIO(data[at:at + size]))
        at += size
    gray = np.asarray(Image.open(images[0]).convert("L"))
    return {"fit": fits(gray, grid, images[1:])}, b""


def find_solution(puzzle_dir, grid, day, cache=CACHE, articles=None):
    """(solution article dir, None) for a puzzle article, or (None, why)."""
    articles = articles if articles is not None else _articles(cache)
    tried = []
    for sday, d, is_solution in articles:
        lag = (sday - day).days
        if not is_solution or not 0 <= lag <= 9:
            continue
        head = (d / "ocr.txt").read_text(encoding="utf-8", errors="replace")[:600]
        if not lag_allowed(head, lag, day):
            continue
        # The solution must fit this puzzle's grid better than every other
        # puzzle printed in its window.
        window = [p / "grid.jpg" for pday, p, p_sol in articles
                  if not (p_sol or p == puzzle_dir or not 0 <= (sday - pday).days <= 9
                          or not lag_allowed(head, (sday - pday).days, pday))]
        fit = fits_anywhere(d / "grid.jpg", grid, window)
        if fit is None:
            continue
        mine, rivals = fit
        tried.append((mine, d))
        if mine >= PAIR_MIN and all(mine - r >= PAIR_MARGIN for r in rivals):
            return d, None
    if not tried:
        return None, "no solution article in the cache for it"
    return None, f"no solution grid matches its blocks (best {max(tried, key=lambda t: t[0])[0]:.2f})"


def answers_for(puzzle_dir, grid, day, cache=CACHE, articles=None):
    """({"<n>-<direction>": answer}, info) for a puzzle article: the accepted
    reads of its paired solution grid. Empty when anything is missing."""
    why = installed()
    if why:
        return {}, {"ocr": why}
    sol, why = find_solution(Path(puzzle_dir), grid, day, cache, articles)
    if sol is None:
        return {}, {"ocr": why}
    accepted, stats = read_answers_anywhere(sol / "grid.jpg", grid)
    return ({f"{n}-{d}": a for (n, d), a in accepted.items()},
            {"ocr": f"solution article {sol.name}", **stats})


def installed():
    """None when the recogniser's packages are here, else why not: available()
    without loading the models (the desktop may read the answers)."""
    import importlib.util
    for name in ("onnxruntime", "rapidocr_onnxruntime"):
        if importlib.util.find_spec(name) is None:
            return f"rapidocr-onnxruntime is not installed (No module named '{name}')"
    return None


def read_answers_anywhere(image, grid):
    """read_answers(image, grid) run on the desktop when tools/ocr_remote.py can
    (the models' sessions and the cells' reads cost this host 300 MB and
    ~10 s of CPU an article; the same code and models read the same
    answers), else here in a local_slot()."""
    import ocr_remote
    data = Path(image).read_bytes()
    corpus = "\n".join(sorted(corpus_words()))
    key = hashlib.sha1(corpus.encode()).hexdigest()
    rows = ["".join(r) for r in grid]
    got = ocr_remote.call("solution_answers", rows, key, data=data)
    if got is not None and got[0].get("need"):
        got = ocr_remote.call("solution_answers", rows, key, corpus, data=data)
    if got is None or "accepted" not in got[0]:
        with ocr_remote.local_slot():
            why = available()
            if why:
                raise RuntimeError(why)
            return read_answers(image, grid)
    found, stats = got[0]["accepted"], got[0]["stats"]
    return {(n, d): a for n, d, a in found}, stats


#: The corpus_words() set the desktop's process holds, and its key.
_REMOTE_CORPUS = None


def answers_there(data, grid, key, corpus=None):
    """({"accepted": [[number, direction, word]], "stats"}, b"") of
    read_answers(the image in `data`, grid) run on the desktop (CALLS), where
    there is no git checkout of the corpus: the client's corpus_words()
    (`corpus`, its words a line each, sent once a process, then held by its
    sha1 `key`) stands in. {"need": True} when this process holds none."""
    global _REMOTE_CORPUS
    import io
    if corpus is not None:
        _CORPUS[str(CORPUS_ROOT)] = frozenset(corpus.split())
        _REMOTE_CORPUS = key
    if _REMOTE_CORPUS != key:
        return {"need": True}, b""
    accepted, stats = read_answers(io.BytesIO(data), grid)
    return {"accepted": [[n, d, a] for (n, d), a in accepted.items()], "stats": stats}, b""


# ------------------------------------------------------------ the corpus

def fill(puzzle, answers):
    """Write the accepted answers into a puzzle's empty entries; returns how many."""
    done = 0
    for e in puzzle["entries"]:
        a = answers.get(f"{e['number']}-{e['direction']}")
        if a and not e.get("solution") and len(a) == e["length"]:
            e["solution"] = a
            done += 1
    return done


def puzzle_grid(puzzle):
    cols, rows = puzzle["dimensions"]["cols"], puzzle["dimensions"]["rows"]
    g = [["#"] * cols for _ in range(rows)]
    for e in puzzle["entries"]:
        x, y = e["position"]["x"], e["position"]["y"]
        for _ in range(e["length"]):
            g[y][x] = "."
            x, y = x + (e["direction"] == "across"), y + (e["direction"] == "down")
    return ["".join(r) for r in g]


def fill_corpus(cache=CACHE, write=True, ledger=None):
    """Fill the held canberra puzzles' empty answers from their solution grids.
    The ledger (<cache>/ocr_answers.jsonl) names the solution article each
    puzzle was read from, so a puzzle is read once; one still unpaired is
    tried again, since its solution may arrive with a later fetch."""
    import puzzle_integrity  # it imports the write path, so not at the top
    from fetch_puzzle import read_puzzle_file, write_puzzle_file
    ledger = Path(ledger or cache / "ocr_answers.jsonl")
    done = {}
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            row = json.loads(line)
            done[row["id"]] = row
    articles = _articles(cache)
    total = 0
    for path in sorted((TOOLS.parent / "puzzles" / "canberra").glob("*/*.json")):
        p = read_puzzle_file(path)
        if p["id"] in done or all(e.get("solution") for e in p["entries"]):
            continue
        aid = p["source"]["url"].rstrip("/").split("/")[-1]
        day = datetime.date.fromisoformat(p["date"])
        answers, info = answers_for(cache / aid, puzzle_grid(p), day, cache, articles)
        n = fill(p, answers)
        print(f"{p['id']}: {n} answers read; {json.dumps(info)}")
        if write:
            if n:
                try:
                    write_puzzle_file(path, p)
                except puzzle_integrity.RefusedWrite as e:
                    print(f"{p['id']}: skipped, {e}")
                    continue
            if info.get("ocr", "").startswith("solution article"):
                done[p["id"]] = {"id": p["id"], "filled": n, **info}
        total += n
    if write:
        ledger.write_text("".join(json.dumps(r) + "\n" for r in done.values()))
    print(f"{total} answers read off solution grids")
    return total


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--show", metavar="ID", help="a puzzle article: print its accepted reads")
    ap.add_argument("--fill", action="store_true", help="fill the canberra files' empty answers")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.show:
        d = a.cache / a.show
        g, why = trove_grid.read_grid(d / "grid.jpg")
        if not g:
            print(f"cannot read the puzzle grid: {why}")
            return 1
        day = _day((d / "ocr.txt").read_text(encoding="utf-8", errors="replace").splitlines()[0])
        answers, info = answers_for(d, g, day, a.cache)
        print(json.dumps(info))
        for k, v in answers.items():
            print(f"  {k}: {v}")
        return 0
    if a.fill:
        fill_corpus(a.cache, write=not a.dry_run)
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
