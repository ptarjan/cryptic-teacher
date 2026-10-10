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
     an even lattice() stands in when it reads the blocks better.
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
     one known() word, or words of 3+ letters run together and read whole.

read_grid_letters reads a Listener report's filled grid the same way, on
the lattice listener_grid finds and the lights of the puzzle's own grid.

RapidOCR (pip install rapidocr-onnxruntime) is optional: without it every
light stays unsolved and available() says why.
"""
import argparse
import datetime
import gzip
import hashlib
import itertools
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import trove_grid
import downloads

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
            and [m for m, _ in ranked(glyphs[rc], models, unnumbered(None))[:1]] == [ch]}


def framed_rules(gray, grid):
    """(gray, ys, xs): the grid image and its rules that read its blocks
    as the grid's best, of: its largest patch of ink straightened() and
    ruled by rules(), else (a crop that is no clean frame: a column cut
    off, a caption touching) that patch's lattice() between its outer
    rules or fitted in it, evenly apart. Ties go to rules()."""
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
    return max(tried, key=lambda g: block_agreement(g[0], grid, (g[1], g[2])))


def read_framed(image, grid):
    """read_answers for an image that is the grid: read on its own rules
    (framed_rules), each light accepted when every cell is read (the
    recogniser's sure letter, or for a cell with a clue number or no sure
    read, matched_letters) and the word is known()."""
    gray, ys, xs = framed_rules(np.asarray(Image.open(image).convert("L")), grid)
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
            if word in full.get(key, ()) and known(word) and all(
                    letters.get(rc, ch) == ch for rc, ch in zip(cells, word)) and all(
                    [m for m, _ in ranked(glyphs[rc], models, unnumbered(numbers[rc]))[:1]] == [ch]
                    for rc, ch in zip(cells, word) if rc in numbers):
                accepted[key] = word
    stats = {"lights": len(lts), "fullReads": len(full), "accepted": len(accepted),
             "cellsRead": len(read), "cellsMatched": len(matched), "cells": len(glyphs),
             "blocks": round(block_agreement(gray, grid, (ys, xs)), 3)}
    return accepted, stats


def read_answers(image, grid, tight=False):
    """({(number, direction): answer} accepted, stats) for a solution image
    and the puzzle's grid (rows of "#" and ".").

    With `tight` (the image is the grid, frame to frame) it is read_framed.
    Else cells are read by read_lights and sure_letters. A light is accepted when every one of its cells is read, some
    recogniser read the light itself as exactly that word, and the word is
    known()."""
    if tight:
        return read_framed(image, grid)
    gray = np.asarray(Image.open(image).convert("L"))
    lat = lattice(gray, len(grid), tight)
    lts = lights(grid)
    sure, full = read_lights(lts, lambda r, c: cell(gray, lat, r, c))
    read = sure_letters(sure)
    accepted = {}
    for key, cells in lts.items():
        if all(rc in read for rc in cells):
            word = "".join(read[rc] for rc in cells)
            if word in full.get(key, ()) and known(word):
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
    if w in _WORDS:
        return True
    ends = {0}
    for i in range(3, len(w) + 1):
        if any(j in ends and w[j:i] in _WORDS for j in range(i - 2)):
            ends.add(i)
    return word in reads and len(w) in ends


def known(word):
    """Whether an answer is WordNet's (a lemma or a regular inflection of one),
    or up to four such words run together, each of four letters or more
    unless it is one of SHORT_WORDS. A misread letter rarely leaves a
    word: RUSE read as RUGE is caught here."""
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
    w = word.lower()
    parts = {0: 0}   # prefix length -> fewest words that spell it
    for i in range(1, len(w) + 1):
        best = min((parts[j] + 1 for j in parts if j < i and w[j:i] in _WORDS
                    and (i - j > 3 or w[j:i] in SHORT_WORDS or (j, i) == (0, len(w)))),
                   default=None)
        if best is not None and best <= 4:
            parts[i] = best
    return len(w) in parts


# ------------------------------------------------------------ pairing

def _day(text):
    m = re.search(r"\w+day (\d{1,2} \w+ \d{4})", text)
    try:
        return datetime.datetime.strptime(m.group(1), "%d %B %Y").date() if m else None  # noqa: DTZ007 -- a print day
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


def _articles(cache):
    """[(print day, article dir, is a solution)] for every cached article with
    a grid image, read once a process. What each dir held is kept in a file
    keyed by the mtimes of its meta.json and ocr.txt, so a process stats the
    dirs and reads only the new or changed ones."""
    if cache in _ARTICLES:
        return _ARTICLES[cache]
    out = _ARTICLES[cache] = []
    index_path = _articles_index_path(cache)
    try:
        old = json.loads(index_path.read_text())
    except (OSError, ValueError):
        old = {}
    new = {}
    for d in sorted(cache.iterdir()) if cache.exists() else ():
        try:
            if not (d / "grid.jpg").exists():
                continue
            key = [(d / "meta.json").stat().st_mtime_ns, (d / "ocr.txt").stat().st_mtime_ns]
        except OSError:
            continue
        got = old.get(d.name)
        if got and got[:2] == key:
            read = (datetime.date.fromisoformat(got[2]) if got[2] else None, got[3])
        else:
            read = _read_article(d)
            if read is None:
                continue
        new[d.name] = key + [read[0].isoformat() if read[0] else None, read[1]]
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
        gray = np.asarray(Image.open(d / "grid.jpg").convert("L"))
        try:
            lat = lattice(gray, len(grid))
        except ValueError:
            continue
        mine = block_agreement(gray, grid, lat)
        # The solution must fit this puzzle's grid better than every other
        # puzzle printed in its window.
        rivals = []
        for pday, p, p_sol in articles:
            if p_sol or p == puzzle_dir or not 0 <= (sday - pday).days <= 9 \
                    or not lag_allowed(head, (sday - pday).days, pday):
                continue
            g, _ = trove_grid.read_grid(p / "grid.jpg")
            if g and len(g) == len(grid) and g != list(grid):
                rivals.append(block_agreement(gray, g, lat))
        tried.append((mine, d))
        if mine >= PAIR_MIN and all(mine - r >= PAIR_MARGIN for r in rivals):
            return d, None
    if not tried:
        return None, "no solution article in the cache for it"
    return None, f"no solution grid matches its blocks (best {max(tried, key=lambda t: t[0])[0]:.2f})"


def answers_for(puzzle_dir, grid, day, cache=CACHE, articles=None):
    """({"<n>-<direction>": answer}, info) for a puzzle article: the accepted
    reads of its paired solution grid. Empty when anything is missing."""
    why = available()
    if why:
        return {}, {"ocr": why}
    sol, why = find_solution(Path(puzzle_dir), grid, day, cache, articles)
    if sol is None:
        return {}, {"ocr": why}
    accepted, stats = read_answers(sol / "grid.jpg", grid)
    return ({f"{n}-{d}": a for (n, d), a in accepted.items()},
            {"ocr": f"solution article {sol.name}", **stats})


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
