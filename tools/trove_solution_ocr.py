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

RapidOCR (pip install rapidocr-onnxruntime) is optional: without it every
light stays unsolved and available() says why.
"""
import argparse
import datetime
import gzip
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

CACHE = Path(os.path.expanduser("~/.cache/trove"))
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
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
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
    """{(row, col): True where the solution image has a block} for n x n."""
    paper = (gray >= trove_grid.otsu(gray)).astype(np.uint8)
    paper = opened(paper, max(2, round(min(lat[2], lat[3]) / 12)))
    out = {}
    for r in range(n):
        for c in range(n):
            a = cell(paper, lat, r, c, 0.15)
            out[(r, c)] = None if a.size == 0 else float(a.mean()) < BLOCK_PAPER
    return out


def block_agreement(gray, grid, lat):
    """Share of cells that are blocks in the image exactly where the grid has one."""
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
def read_answers(image, grid, tight=False):
    """({(number, direction): answer} accepted, stats) for a solution image
    and the puzzle's grid (rows of "#" and ".").

    Every light is read in every rendering by every recogniser; a read counts only at the
    light's full length. A cell's letter is read when SURE_READS counted
    reads, across or down, give it at least MIN_PROB and no counted read
    gives another letter that surely (so a crossing that disagrees unreads both).
    A light is accepted when every one of its cells is read, some
    recogniser read the light itself as exactly that word, and the word is
    known()."""
    gray = np.asarray(Image.open(image).convert("L"))
    lat = lattice(gray, len(grid), tight)
    lts = lights(grid)
    sure = {}      # cell -> {letter: [directions that read it surely]}
    full = {}      # light -> every full-length word read for it
    for key, cells in lts.items():
        crops = [cell(gray, lat, r, c) for r, c in cells]
        for (vi, render), (ri, rec) in itertools.product(enumerate(VARIANTS.values()),
                                                         enumerate(recognisers())):
            word, probs = read_word(word_image([render(x) for x in crops]), rec)
            if len(word) != len(cells):
                continue
            full.setdefault(key, set()).add(word)
            for rc, ch, p in zip(cells, word, probs):
                if p >= MIN_PROB:
                    sure.setdefault(rc, {}).setdefault(ch, set()).add((key[1], vi, ri))
    read = {rc: next(iter(v)) for rc, v in sure.items()
            if len(v) == 1 and len(next(iter(v.values()))) >= SURE_READS}
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
            _WORDS.update(w + end for end in ("s", "es", "ed", "d", "ing", "er", "est", "r", "st"))
            if w.endswith("e"):
                _WORDS.update((w[:-1] + "ing", w[:-1] + "ed"))
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


def _articles(cache):
    """[(print day, article dir, is a solution)] for every cached article with
    a grid image, read once a process."""
    if cache in _ARTICLES:
        return _ARTICLES[cache]
    out = _ARTICLES[cache] = []
    for d in sorted(cache.iterdir()) if cache.exists() else ():
        if not (d / "grid.jpg").exists() or not (d / "ocr.txt").exists():
            continue
        try:
            title = json.loads((d / "meta.json").read_text()).get("title", "")
        except (OSError, ValueError):
            continue
        first = (d / "ocr.txt").read_text(encoding="utf-8", errors="replace")[:400]
        day = _day(first.splitlines()[0] if first else "")
        if day:
            out.append((day, d, "solution" in title.lower().split(" - trove")[0]))
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
                write_puzzle_file(path, p)
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
