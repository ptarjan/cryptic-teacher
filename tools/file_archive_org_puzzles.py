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

  - The title is found in djvu.xml's words. The grid is the largest patch of
    ink under it (tools/trove_grid.py reads its blocks); the clues are the
    two columns under the grid, cut where the column's text stops being clues
    ("Solution to Puzzle No", another heading, a gap).
  - The columns are read four ways: archive.org's words, RapidOCR at twice
    the size with two recognisers (multilingual PP-OCRv4 and English
    PP-OCRv5), and Tesseract, whose errors are not RapidOCR's (READERS). Each is parsed as file_trove_puzzles.py parses
    Trove's text, after tidy() undoes the print's commonest slips, and each
    list is repaired from another reading (tools/trove_clue_ocr.py).
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

Resumable: ~/.cache/archive_org_editions/filed.jsonl records each edition's
headings and verdicts against its files and this code's hash.
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
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import enumeration
import file_trove_puzzles as ftp
import puzzle_integrity
import reconstruct_grid as rg
import series as series_meta
import trove_clue_ocr
import trove_grid
import trove_solution_ocr
from file_penguin_puzzle import separators
from groups import entry_id

SERIES = "times"
CACHE = Path(os.path.expanduser("~/.cache/archive_org_editions"))
CROPS = Path(os.path.expanduser("~/.cache/archive_org_crops"))
SOURCE = Path.home() / "cryptic-setter-data" / "archiveorg-source"
TOOL = "tools/file_archive_org_puzzles.py"
ITEM = re.compile(r"NewsUK(19\d\d)UKEnglish$")
PAGE_URL = "https://archive.org/details/{item}/page/n{leaf}/mode/1up"
CODE = [Path(__file__), TOOLS / "file_trove_puzzles.py", TOOLS / "trove_grid.py",
        TOOLS / "trove_solution_ocr.py", TOOLS / "trove_clue_ocr.py", TOOLS / "data" / "clue_compounds.tsv",
        TOOLS / "data" / "lexicon.tsv", TOOLS / "data" / "clue_lm.tsv.gz",
        TOOLS / "data" / "archive_org_tess.traineddata"]

NUMBER = r"(\d{2}[,.\s]?\d{3})"
#: The daily cryptic's title: not the Concise, the Jumbo or Times Two.
TITLE = re.compile(r"^\W*(?:the\s+)?times\s+crossword\s+(?:puzzle\s+)?no\.?\s*" + NUMBER, re.I)
#: The previous puzzle's solution, printed under the clues.
SOLUTION = re.compile(r"^\W*solution\s+(?:to|of)\s+puzzle\s+no\.?\s*" + NUMBER, re.I)
#: A column line that ends the clues.
STOP = re.compile(r"^\W*(solution|crossword|concise|times\s+two|the\s+times\s+crossword"
                  r"|championship|jumbo|\w{0,10}\s+(of|to)\s+puzzle)\b", re.I)
#: The vertical gap, in pixels at the scan's 3296x4672, that ends a column.
GAP = 80


def number_of(text):
    return int(re.sub(r"\D", "", text))


# ------------------------------------------------------------ djvu.xml

def leaf_lines(xml_path, leaves):
    """{leaf: [[(x0, y0, x1, y1, text), ...] per printed line]} for the leaves
    asked for, in one pass over the edition's djvu.xml.gz."""
    out, n = {}, -1
    with gzip.open(xml_path) as f:
        for ev, el in ET.iterparse(f, events=("start", "end")):
            if el.tag != "OBJECT":
                continue
            if ev == "start":
                n += 1
                continue
            if n in leaves:
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
            el.clear()
    return out


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


def grid_box(img, title):
    """Where the grid under a title is on the page: the largest ink below it."""
    x0, y0, x1, y1 = title
    w = x1 - x0
    crop = (max(0, x0 - 120), y1, min(img.width, x1 + 120), min(img.height, y1 + int(1.3 * w) + 80))
    box = ink_box(img.crop(crop))
    if box is None:
        return None
    return (crop[0] + box[0], crop[1] + box[1], crop[0] + box[2], crop[1] + box[3])


def columns(lines, grid):
    """The two clue columns under the grid: [[(y0, y1, x0, x1, text) per line]
    for the left, then the right], each cut where the clues stop."""
    gx0, gy0, gx1, gy1 = grid
    gw = gx1 - gx0
    mid = gx0 + gw / 2 - 10
    bottom = gy1 + 1.8 * gw
    cols = [[], []]
    for ws in lines:
        for side in (0, 1):
            part = [w for w in ws if gx0 - 40 <= w[0] and w[2] <= gx1 + 15 and gy1 - 5 <= w[1] <= bottom
                    and (w[0] < mid) == (side == 0)]
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
            if not kept and not re.match(r"\W*(across|down)\b", line[4], re.I) and last is None:
                # The column's first line is ACROSS, DOWN or a clue: a stray
                # word the grid's numbers left is not.
                if not re.match(r"\W*\d", line[4]):
                    continue
            kept.append(line)
            last = line[1]
        out.append(kept)
    return out


_ENGINES = {}
#: RapidOCR reads the 200dpi print (~17px a line) far better twice the size.
UPSCALE = 2
#: The clue columns' other readers: RapidOCR's own multilingual PP-OCRv4
#: recogniser ("ch") and English PP-OCRv5 mobile ("en5"), the two that
#: misread fewest clue words on hand-checked 1974, 1990 and 1995 crops (22%
#: and 26% of tokens, against English PP-OCRv3's 50% and PP-OCRv4's 56%; the
#: server recognisers cost over 20 times as long), and Tesseract ("times"),
#: a different engine whose misreads are not theirs, its English LSTM
#: fine-tuned on Times clue lines (tools/train_archive_org_tesseract.py).
#: The vote's misread rate on tools/data/archive_org_ocr_gold.json:
#: tools/measure_archive_org_ocr.py.
READERS = {"ch": None,
           "en5": Path(os.path.expanduser("~/.cache/rapidocr/en_PP-OCRv5_rec_mobile_infer.onnx")),
           "times": "tesseract"}
#: The Tesseract readers' models: None is the installed eng.
TESS_MODELS = {"times": TOOLS / "data" / "archive_org_tess.traineddata"}
TESSERACT = Path(os.path.expanduser("~/.local/tess/bin/tesseract"))
MODEL_URL = ("https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.4.0/onnx/PP-OCRv5/rec/"
             "en_PP-OCRv5_rec_mobile_infer.onnx")


def engine(which):
    """RapidOCR with the recogniser READERS names, the model fetched once."""
    if which not in _ENGINES:
        from rapidocr_onnxruntime import RapidOCR
        model = READERS[which]
        if model is not None and not model.exists():
            import urllib.request
            model.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "cryptic-teacher"})
            try:
                data = urllib.request.urlopen(req, timeout=300).read()
            except OSError as e:
                raise RuntimeError(f"cannot fetch {MODEL_URL} to {model}: {e}") from e
            tmp = model.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(model)
        _ENGINES[which] = RapidOCR(rec_model_path=str(model)) if model else RapidOCR()
    return _ENGINES[which]


def reader_key(which):
    """The cache name of a reader's readings: a TESS_MODELS reader's carries
    its model's hash, so a retrained model never reuses the old one's."""
    if which not in TESS_MODELS:
        return which
    import hashlib
    if which not in _MODEL_HASHES:
        _MODEL_HASHES[which] = hashlib.sha1(TESS_MODELS[which].read_bytes()).hexdigest()[:10]
    return f"{which}-{_MODEL_HASHES[which]}"


_MODEL_HASHES = {}


def tesseract():
    """The tesseract binary: on PATH, else the user-local conda-forge install
    (no sudo on this host), else an error that says how to install it."""
    import shutil
    found = shutil.which("tesseract") or (str(TESSERACT) if TESSERACT.exists() else None)
    if not found:
        raise RuntimeError(f"tesseract is not installed (not on PATH, not {TESSERACT}); install it "
                           f"without sudo: micromamba create -p ~/.local/tess -c conda-forge tesseract")
    return found


def tesseract_words(crop, model=None):
    """[(x0, y0, x1, y1, word)] Tesseract reads in a PIL image, with the
    installed eng model or the .traineddata at `model`."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "crop.png"
        crop.save(path)
        lang = ["--tessdata-dir", str(model.parent), "-l", model.stem] if model else ["-l", "eng"]
        # TSV by parameter, not the "tsv" config file: a model's own
        # tessdata directory has no configs/.
        res = subprocess.run([tesseract(), str(path), "-", "--psm", "4", *lang,
                              "-c", "tessedit_create_tsv=1"],
                             capture_output=True, text=True, timeout=300)
    if res.returncode:
        raise RuntimeError(f"tesseract failed ({res.returncode}): {res.stderr.strip()[-300:]}")
    words = []
    for row in res.stdout.splitlines()[1:]:
        f = row.split("\t")
        if len(f) == 12 and f[0] == "5" and f[11].strip():
            x, y, w, h = map(int, f[6:10])
            words.append((x, y, x + w, y + h, f[11].strip()))
    return words


def rapid_lines(img, grid, which, cache_path):
    """One recogniser's reading of the page under the grid (RapidOCR's, or
    Tesseract's for a TESS_MODELS reader), as djvu-style lines of one word each, in page
    coordinates; cached as JSON."""
    if cache_path.exists():
        return [[tuple(w)] for w in json.loads(cache_path.read_text())]
    import numpy as np
    gx0, gy0, gx1, gy1 = grid
    gw = gx1 - gx0
    box = (max(0, gx0 - 40), gy1, min(img.width, gx1 + 30), min(img.height, int(gy1 + 1.8 * gw)))
    crop = img.crop(box).convert("RGB")
    crop = crop.resize((crop.width * UPSCALE, crop.height * UPSCALE))
    if which in TESS_MODELS:
        res = [(((x0, y0), (x1, y1)), t, None)
               for x0, y0, x1, y1, t in tesseract_words(crop, TESS_MODELS[which])]
    else:
        res, _ = engine(which)(np.asarray(crop), use_cls=False)
    words = []
    for b, t, _ in res or ():
        xs, ys = [p[0] / UPSCALE for p in b], [p[1] / UPSCALE for p in b]
        words.append((int(min(xs)) + box[0], int(min(ys)) + box[1],
                      int(max(xs)) + box[0], int(max(ys)) + box[1], t))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(words))
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
        heading = heading_of(line)
        if heading:
            line = heading
        elif out and re.match(r"(?:across|down)\b", line):
            # A lower-case "down (8)." carries on the line before it: no heading.
            out[-1] += " " + line
            prev = out[-1]
            continue
        line = re.sub(r"^(\d{1,2})(?=[A-Z][a-z])", r"\1 ", line)
        line = re.sub(r"(?<=[a-z])\s?\(?(\d{1,2}(?:[,.\-]\d{1,2})*)[)jJ]$", r" (\1)", line)
        if (re.search(r"\(\s*[\dSIl,.\- ]{1,9}\)\W{0,2}$", prev)
                or re.fullmatch(r"\W*(across|down)\W*", prev, re.I)) and re.match(r"[A-Z][a-z]", line):
            line = "? " + line
        out.append(line)
        prev = line
    return "\n".join(out)


def heading_of(line):
    """"ACROSS" or "DOWN" for a line that is the list's heading alone, read
    however badly ("DOW'N", "DOIN", "AROSS"); else None."""
    letters = re.sub(r"[^A-Za-z]", "", line)
    if len(line) > 9 or not 3 <= len(letters) <= 7 or not letters.isupper():
        return None
    for word in ("ACROSS", "DOWN"):
        if SequenceMatcher(None, letters, word).ratio() >= 0.7:
            return word
    return None


BRACKETS = str.maketrans({"{": "(", "[": "(", "}": ")", "]": ")"})


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


# ------------------------------------------------------------ two readings

def tokens(text):
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)


def similar(a, b):
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


#: What a mark one reading lacks costs in align(), against 1 for a word.
MARK_GAP = 0.5


def align(mine, theirs):
    """[(i, j)] pairing clue words `mine` with words of the other reading
    `theirs` (None for a word the other side lacks, and (None, j) for a word
    of theirs inside the clue that `mine` lacks): the best semi-global
    alignment, where the other reading's words before and after the clue
    cost nothing and a pair costs what its spellings differ."""
    n, m = len(mine), len(theirs)
    gap = 1.0
    inf = float("inf")
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        cost[0][j] = 0.0
    for i in range(1, n + 1):
        cost[i][0] = cost[i - 1][0] + gap
        back[i][0] = "up"
        for j in range(1, m + 1):
            pair = cost[i - 1][j - 1] + (0.0 if mine[i - 1] == theirs[j - 1] else inf
                                         if theirs[j - 1] == BREAK
                                         else 1.2 * (1 - similar(mine[i - 1], theirs[j - 1])))
            # A mark one side lacks (a comma missed) costs less than a word,
            # so a lost mark never outweighs pairing the words after it.
            up = cost[i - 1][j] + (MARK_GAP if mine[i - 1] in MARKS else gap)
            left = cost[i][j - 1] + (MARK_GAP if theirs[j - 1] in MARKS else gap)
            cost[i][j], back[i][j] = min((pair, "pair"), (up, "up"), (left, "left"))
    j = min(range(m + 1), key=lambda k: cost[n][k])
    out, i = [], n
    while i > 0:
        step = back[i][j]
        if step == "pair":
            out.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif step == "up":
            out.append((i - 1, None))
            i -= 1
        else:
            # A word of theirs inside the clue that `mine` lacks: (None, j).
            out.append((None, j - 1))
            j -= 1
    return out[::-1]


_LEXICON = None


def rank(word):
    """A word's frequency rank in tools/data/lexicon.tsv (1 the commonest),
    or None when the lexicon lacks it."""
    global _LEXICON
    if _LEXICON is None:
        _LEXICON = {}
        with open(TOOLS / "data" / "lexicon.tsv", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("#"):
                    w, r = line.split("\t", 2)[:2]
                    _LEXICON.setdefault(w.lower(), int(r))
    return _LEXICON.get(word.lower()) or _LEXICON.get(word.lower().replace("'", ""))


def is_word(word):
    """Whether the committed lexicon has the word (cmudict and WordNet are
    too loose here: they hold "al", "imo" and "chaft")."""
    if word.lower().endswith("'s") and len(word) > 3:
        return is_word(word[:-2])
    return rank(word) is not None or word.lower() in ("a", "i") or word.lower().replace("'", "") in closed()


_LM = None


def clue_lm():
    """(words, pairs, answer words): how often the corpus's clues print each
    word and each two words in a row, and how often its answers hold each
    word (tools/data/clue_lm.tsv.gz, built by tools/build_clue_lm.py)."""
    global _LM
    if _LM is None:
        uni, pair, ans = {}, {}, {}
        with gzip.open(TOOLS / "data" / "clue_lm.tsv.gz", "rt", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                k, n = line.rstrip("\n").split("\t")
                (ans if k[0] == "=" else pair if " " in k else uni)[k.lstrip("=")] = int(n)
        _LM = uni, pair, ans
    return _LM


#: How often the corpus's clues must print a word the lexicon lacks, or its
#: answers hold it, for the word to count as one ("Hornblower", "Illyrian").
CLUE_WORD_FLOOR = 3


def known(word, stem=True):
    """Whether the word is the lexicon's or one the corpus's clues or
    answers use often enough to be real, not a reader's slip."""
    if is_word(word):
        return True
    uni, _, ans = clue_lm()
    low = word.lower()
    return (uni.get(low, 0) >= CLUE_WORD_FLOOR or ans.get(low.replace("'", ""), 0) >= CLUE_WORD_FLOOR
            or (stem and low.endswith("'s") and len(low) > 3 and "'" not in low[:-2]
                and known(low[:-2], stem=False)))


def fit(word, before, after):
    """How well `word` reads between the words `before` and `after` (None at
    a clue's end), by the corpus's clues: the log count of each pair it
    makes, plus a tenth of the log count of the word alone."""
    uni, pair, _ = clue_lm()
    w = word.lower()
    score = 0.1 * math.log1p(uni.get(w, 0))
    for a, b in ((before, w), (w, after)):
        if a and b:
            score += math.log1p(pair.get(f"{a.lower()} {b.lower()}", 0))
    return score


#: How much better one spelling must fit its neighbours than the next to win
#: a tie between readings.
FIT_MARGIN = 1.0


def edits(word):
    """The spellings one letter's change, loss or addition from `word`."""
    w, abc = word.lower(), "abcdefghijklmnopqrstuvwxyz"
    splits = [(w[:k], w[k:]) for k in range(len(w) + 1)]
    return ({a + b[1:] for a, b in splits if b} | {a + c + b[1:] for a, b in splits if b for c in abc}
            | {a + c + b for a, b in splits for c in abc}) - {w}


def within_one(a, b):
    """Whether two spellings are at most one letter's change, loss or addition apart."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    k = 0
    while k < min(len(a), len(b)) and a[k] == b[k]:
        k += 1
    return a[k + 1:] == b[k + 1:] or a[k + 1:] == b[k:] or a[k:] == b[k + 1:]


def mend(read, before, after):
    """The word every reading in `read` (lower case) most likely misspells:
    of the known words one letter from any reading, the one most readings
    lie that close to, then one as long as most readings, a tie going to
    the one that fits its neighbours in the corpus's clues FIT_MARGIN
    better; None when nothing wins."""
    cands = {c for r in set(read) if len(r) > 2 for c in edits(r) if len(c) > 1 and known(c)}
    if not cands:
        return None
    lens = [len(r) for r in read]
    size = max(lens, key=lens.count)
    ranked = sorted((((sum(within_one(c, r) for r in read), len(c) == size), fit(c, before, after), c)
                     for c in cands), reverse=True)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0] and ranked[0][1] - ranked[1][1] < FIT_MARGIN:
        return None
    return ranked[0][2]


#: The letters the print's worn type turns into one another, both ways.
SLIPS = (("c", "e"), ("c", "t"), ("h", "b"), ("n", "u"), ("l", "i"), ("l", "t"), ("f", "t"),
         ("i", "t"), ("rn", "m"), ("li", "h"), ("cl", "d"))
#: How much commoner a slip's word must be than the word read.
SLIP_RATIO = 20
#: Words commoner than this rank are read right too often to doubt ("lie", not "he").
SLIP_FLOOR = 8000


def common_slip(word):
    """A word one SLIPS swap from `word` that the lexicon ranks SLIP_RATIO
    times commoner ("with" for "wich", "on" for "ou"), else None: every
    reader can share that misread, so the reading is not to be trusted."""
    low = word.lower()
    r = rank(low)
    if r is None or r < SLIP_FLOOR:
        return None
    for a, b in SLIPS + tuple((b, a) for a, b in SLIPS):
        at = low.find(a)
        while at >= 0:
            v = low[:at] + b + low[at + len(a):]
            if (rank(v) or 10 ** 9) * SLIP_RATIO < r:
                return v
            at = low.find(a, at + 1)
    return None


#: Punctuation inside a clue that the readings vote on like words.
MARKS = ",;:!?"


#: A number in another reading's text (a clue's number or its count), which
#: bounds the clue: the words between it and the clue's are the clue's too.
BREAK = "#"


def marked(text, breaks=False):
    """The words and the voted punctuation marks of a text, in order; with
    `breaks`, each number too, as BREAK."""
    found = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|[" + MARKS + "]" + (r"|\d+" if breaks else ""), text)
    return [BREAK if t[0].isdigit() else t for t in found]


def ends(pairs, theirs):
    """(lead, trail): the words and marks of `theirs` between the number
    before the aligned clue and its first word, and between its last word and
    the number after; None for an end no number bounds within six tokens."""
    js = [j for i, j in pairs if i is not None and j is not None]
    if not js:
        return None, None
    lead, k = [], min(js) - 1
    while k >= 0 and theirs[k] != BREAK and len(lead) < 6:
        lead.insert(0, theirs[k].lower())
        k -= 1
    lead_ok = k >= 0 and theirs[k] == BREAK
    trail, k = [], max(js) + 1
    while k < len(theirs) and theirs[k] != BREAK and len(trail) < 6:
        trail.append(theirs[k].lower())
        k += 1
    trail_ok = k < len(theirs) and theirs[k] == BREAK
    return tuple(lead) if lead_ok else None, tuple(trail) if trail_ok else None


def rejoin(theirs, low):
    """Another reading's tokens with a word it split at a line end ("taste.
    fully", "subter fuge") joined again, when this clue's words (`low`) hold
    the joined word and it is a dictionary word."""
    out, k = [], 0
    while k < len(theirs):
        for step in (1, 2):
            if k + step < len(theirs) and (step == 1 or theirs[k + 1] in MARKS):
                a, b = theirs[k], theirs[k + step]
                joined = (a + b).lower()
                # Two words with a space between are two words ("of fish"):
                # only a mark, or a half that is no word, says it was split.
                apart = step == 2 or not (is_word(a.lower()) and is_word(b.lower()))
                if a.isalpha() and b.isalpha() and apart and joined in low and is_word(joined):
                    out.append(a + b)
                    k += step + 1
                    break
        else:
            out.append(theirs[k])
            k += 1
    return out


def agree(clue, others):
    """(text or None, how) for one clue against the other readings' words
    and marks (`others`: one list per reading, or one list alone). Each word
    stands when another reading has it too; else it takes the spelling the
    other readings share, else the one spelling of the three that is a
    dictionary word. A mark no other reading has is dropped. A word no
    other reading has, two readings agreeing on a non-word the third does
    not, or several dictionary spellings, is a disagreement."""
    if others and isinstance(others[0], str):
        others = [others]
    mine = marked(clue)
    if not tokens(clue):
        return clue, "no words"
    low = [w.lower() for w in mine]
    seen = [{} for _ in mine]  # i -> {reading k: its word}
    extra = [{} for _ in range(len(mine) + 1)]  # gap before i -> {word: readings}
    leads, trails = [], []
    for k, theirs in enumerate(others):
        theirs = rejoin(theirs, low)
        at = 0
        pairs = align(low, [w.lower() for w in theirs])
        lead, trail = ends(pairs, theirs)
        leads.append(lead)
        trails.append(trail)
        for i, j in pairs:
            if i is None:
                extra[at].setdefault(theirs[j].lower(), set()).add(k)
            else:
                at = i + 1
                if j is not None:
                    seen[i][k] = theirs[j]
    # A word or mark that two other readings have where this one has nothing
    # (a word lost, two run together, a comma missed) is put in.
    # A lone I is put in only when every reading has it: RapidOCR's two
    # recognisers share one detector and read the same speck as a "1".
    adds = {g: [w for w, ks in e.items() if len(ks) >= 2 and len(ks) * 2 > len(others)
                and (w in MARKS or is_word(w)) and (w != "i" or len(ks) == len(others))]
            for g, e in enumerate(extra)}
    # Words other readings have between the clue's number and its first word,
    # or between its last word and its count, were lost from this reading:
    # put in when most readings have the same ones, else no reading wins.
    for side, got_ends in (("start", leads), ("end", trails)):
        # A lone letter after the clue's last word is its count misread ("(s)").
        seen_ends = [e for e in (tuple(t for t in e if (side == "end" or t not in MARKS)
                                       and not (side == "end" and len(t) == 1 and t not in MARKS))
                                 for e in got_ends if e) if e]
        if len(seen_ends) < 2:
            continue
        top = max(seen_ends, key=seen_ends.count)
        words_at = [t for t in top if t not in MARKS]
        if side == "start" and len(words_at) == 1 and len(words_at[0]) == 1:
            # One letter before the clue is a misread clue number ("2I").
            continue
        if (seen_ends.count(top) * 2 > len(others) and all(is_word(t) for t in words_at)):
            g = 0 if side == "start" else len(mine)
            adds[g] = adds.get(g, []) + [" ".join(top)] if top else adds.get(g, [])
        elif words_at or any(t not in MARKS for e in seen_ends for t in e):
            return None, f"the clue's {side} is lost: other readings have {' / '.join(' '.join(e) for e in seen_ends)}"
    fixes, drop, how = {}, set(), "agree"
    for i, w in enumerate(mine):
        a = low[i]
        got = {k: v for k, v in seen[i].items() if v not in MARKS and v != BREAK}
        if w in MARKS:
            if others and w not in seen[i].values():
                drop.add(i)
            continue
        if not got and i == 0 and len(w) == 1 and len(mine) > 1 and mine[1][:1].isupper():
            # A letter before the clue's capital that no other reading has
            # is a speck or a misread clue number.
            drop.add(i)
            continue
        if (i and a == "i" and len(got) * 2 < len(others)
                and all(v.lower() == "i" for v in got.values())):
            # A lone I most readings see nothing at is a speck.
            drop.add(i)
            continue
        before = next((low[k] for k in range(i - 1, -1, -1) if low[k] not in MARKS), None)
        after = next((low[k] for k in range(i + 1, len(low)) if low[k] not in MARKS), None)
        if not got and len(a) > 3 and not known(a) and not (i and w[0].isupper()) and mend([a], before, after):
            # A word only this reading has, a letter from a known one.
            fix = mend([a], before, after)
            fixes[i] = fix.capitalize() if w[:1].isupper() else fix
            continue
        if not got and len(a) == 1 and a not in "ai":
            # A lone letter no other reading has is a speck.
            drop.add(i)
            continue
        if not got:
            return None, f"no other reading has {w!r}"
        if (i == 0 and len(w) == 1 and len(mine) > 1 and mine[1][:1].isupper()
                and len(got) * 2 < len(others)):
            drop.add(i)
            continue
        votes = {a: 1}
        spelt = {a: w}
        for v in got.values():
            votes[v.lower()] = votes.get(v.lower(), 0) + 1
            spelt.setdefault(v.lower(), v)
        if i and w[0].isupper() and any(v[0].islower() for v in got.values() if v.lower() == a):
            # A capital one reader saw inside the clue and another did not.
            spelt[a] = next(v for v in got.values() if v.lower() == a)
            how = "settled by the dictionary"
        # Of the dictionary spellings like this one and about as long (or
        # shared by two readings), the one most readings share stands; a tie goes to the one
        # far more like every reading's word (its support), else no spelling
        # wins.
        read = [a] + [v.lower() for v in got.values()]
        support = {s: sum(similar(s, r) for r in read) for s in votes}
        words_ = sorted((s for s in votes if known(s) and (votes[s] > 1 or (
                            similar(a, s) >= 0.5 and abs(len(s) - len(a)) <= max(1, len(a) // 4)))),
                        key=lambda s: (-votes[s], -support[s]))
        if len(words_) > 1:
            top, nxt = words_[0], words_[1]
            if votes[top] == votes[nxt] and support[top] - support[nxt] < 0.3:
                # A tie the readings cannot break goes to the spelling that
                # fits its neighbours in the corpus's clues far better.
                fits = sorted((c for c in words_ if votes[c] == votes[top]),
                              key=lambda c: -fit(c, before, after))
                if fit(fits[0], before, after) - fit(fits[1], before, after) < FIT_MARGIN:
                    return None, f"readings differ: {w} / {' / '.join(got.values())}"
                words_ = fits
        if words_:
            pick = words_[0]
            if pick != a or votes[a] == 1:
                how = "settled by the dictionary"
        elif not known(a) and not (i and w[0].isupper()) and mend(read, before, after):
            # No reading a known word: the known word they all misspell (a
            # capital inside the clue is a name the corpus may not know).
            pick = mend(read, before, after)
            spelt[pick] = pick.capitalize() if w[:1].isupper() else pick
            how = "settled by the corpus"
        elif len(a) > 2 and (votes[a] >= 3 or (votes[a] > 1 and i and w[0].isupper() and w[1:].islower())):
            # No reading a dictionary word: what three readers saw stands,
            # and a name two saw inside the clue (the first word's capital
            # says nothing).
            pick = a
        elif max(votes.values()) > 1 and votes[a] == 1 and len(a) > 3 and w[0].islower():
            return None, f"two readings agree on a non-word: {w} / {' / '.join(got.values())}"
        else:
            return None, (f"both read {w!r}, not a word" if votes[a] > 1
                          else f"readings differ: {w} / {' / '.join(got.values())}")
        slip = common_slip(pick)
        if slip:
            # Every reader can share the slip: the commoner spelling stands
            # unless the read one fits its neighbours in the corpus's clues
            # far better.
            gap = fit(slip, before, after) - fit(pick, before, after)
            if gap > -FIT_MARGIN:
                spelt[slip] = slip.capitalize() if spelt[pick][:1].isupper() else slip
                pick = slip
                how = "settled by the corpus"
        if spelt[pick] != w:
            fixes[i] = spelt[pick]
    adds = {g: ws for g, ws in adds.items() if len(ws) == 1}
    if not fixes and not drop and not adds:
        return clue, how
    text, k, out = clue, 0, ""
    for i, old in enumerate(mine):
        at = text.find(old, k)
        new = "" if i in drop else fixes.get(i, old)
        if not new and at > 0 and text[at - 1:at].isalpha() and text[at + len(old):at + len(old) + 1].isalpha():
            new = " "  # a dropped mark between two words ("spirit:after") leaves their space
        add = adds.get(i)
        if i == 0 and add and add[0][0].isalpha():
            # Lost opening words take the clue's capital.
            add = [add[0][0].upper() + add[0][1:]]
            if new and not new.isupper() and is_word(new.lower()) and not is_word_only_capital(new, seen[0]):
                new = new[0].lower() + new[1:]
        elif new and i == 0 and old[0].isupper():
            new = new[0].upper() + new[1:]
        out += text[k:at] + (add[0] + " " if add else "") + new
        k = at + len(old)
    out += (" " + adds[len(mine)][0] if adds.get(len(mine)) else "") + text[k:]
    if adds and how == "agree":
        how = "settled by the readings"
    if drop and how == "agree":
        how = "settled by the readings"
    return re.sub(r"\s+([" + MARKS + "])", r"\1", re.sub(r"  +", " ", out)).strip(), how


def is_word_only_capital(word, seen):
    """Whether the other readings print `word` with its capital too."""
    return bool(seen) and all(v[0].isupper() for v in seen.values() if v.lower() == word.lower())


def clean(text):
    """A reading without OCR's specks: a not-sign read for the hyphen that
    breaks a word over a line end is the join, an asterisk or bullet beside
    a word is no part of it, and a comma or exclamation mark misread as a
    full stop or an I is put back."""
    text = re.sub(r"\s*[*•|]+(?=\s|$)", "", re.sub(r"(?<=[a-z])¬\s*(?=[a-z])", "", text))
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    # A backslash inside a word is a letter the scan broke ("sal\\ age").
    text = re.sub(r"(?<=[a-z])\\\s?(?=[a-z])", "", text)
    # A clue's sentence never stops before a lower-case word: a full stop
    # there is a comma the print's low ink lost the tail of.
    text = re.sub(r"(?<=[a-z]{2})\.(?=\s+[a-z])", ",", text)
    # An exclamation mark read as a capital I or a one, last before the count.
    text = re.sub(r"(?<=[a-z]) [I1l](?=\s*(?:\(\s*\d|$))", "!", text)
    text = re.sub(r"(?<![\d(])\b1(?=[a-z]*\b)(?![a-z]*\s+(?:and|or|&)\s+\d)([a-z]*)", one_for_i, text)
    return re.sub(r"\b([A-Za-z]+)-\s+([a-z]+)\b", line_end_hyphen, text)


#: What follows a clue number standing for a light, not a word.
LIGHT_WORD = re.compile(r"(?:across|down|ac|dn|ack|dwn)\b", re.IGNORECASE)


def one_for_i(m):
    """A "1" standing as a word ("in letter 1 posted") or starting one
    ("1t") the capital I it was printed as, when words go on after it and
    the result is a word; a clue number before "across" or "down" stays."""
    rest = m.group(1)
    if not rest:
        after = m.string[m.end():]
        if (re.match(r"\s+[a-z]", after) and not LIGHT_WORD.match(after.lstrip())
                and re.search(r"[A-Za-z][,;:'\"]?\s+$", m.string[:m.start()])):
            return "I"
        return m.group(0)
    return "I" + rest if is_word("i" + rest) else m.group(0)


_COMPOUNDS = None


def compound(a, b):
    """(hyphenated, closed): how many of the corpus's clues print a+b each
    way (tools/data/clue_compounds.tsv), (0, 0) when none do."""
    global _COMPOUNDS
    if _COMPOUNDS is None:
        _COMPOUNDS = {}
        with open(TOOLS / "data" / "clue_compounds.tsv", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("#"):
                    k, h, c = line.rstrip("\n").split("\t")
                    _COMPOUNDS[k] = (int(h), int(c))
    return _COMPOUNDS.get(f"{a.lower()}-{b.lower()}", (0, 0))


_CLOSED = None


def closed():
    """The compounds the corpus's clues print closed more often than
    hyphenated ("backstreet"): words, though the lexicon lacks them."""
    global _CLOSED
    if _CLOSED is None:
        compound("", "")
        _CLOSED = {k.replace("-", "") for k, (h, c) in _COMPOUNDS.items() if c > h}
    return _CLOSED


def line_end_hyphen(m):
    """A word hyphenated over a line end ("Pal- grave", "back- street",
    "short- lived") as the print meant it. The hyphen is the line break's
    when the lexicon has the word whole, when a half is no word ("hav- ing"),
    when the corpus's clues print it closed more often than hyphenated, or
    when it is a name (a capital after a lower-case word, "in Pal- grave");
    else it is the compound's own."""
    a, b = m.group(1), m.group(2)
    if is_word(a + b) or not (is_word(a) and is_word(b)):
        return a + b
    hyphenated, closed = compound(a, b)
    if hyphenated != closed:
        return a + b if closed > hyphenated else f"{a}-{b}"
    name = a[0].isupper() and a[1:].islower() and re.search(r"[a-z][,;:]?\s+$", m.string[:m.start()])
    return a + b if name else f"{a}-{b}"


HEADING = re.compile(r"^\W*(?:clues\s+)?(?:across|down)\W*$", re.IGNORECASE | re.MULTILINE)


def reconcile(laid, streams, lengths=None):
    """The laid clues with each clue's text put to every reading; returns
    (laid, {light: why}) naming each clue filed blank. `streams` holds each
    other reading's text, or {light: that reading's text} where the lights
    were laid from different readings; one text or dict alone is one reading.
    `lengths` ({light: cells}, from the grid) gives a clue whose count was
    lost its light's length as the count."""
    if isinstance(streams, (str, dict)):
        streams = [streams]
    # A list's heading bounds the clues either side like a number: "DOWN"
    # over "1 Unusual ..." is no word lost from 1 down.
    whole = [marked(clean(HEADING.sub("0", s)), breaks=True) for s in streams if isinstance(s, str)]
    per = [{k: marked(clean(v), breaks=True) for k, v in s.items()} for s in streams if isinstance(s, dict)]
    out, blank = {}, {}
    for lid, (text, enum, group) in laid.items():
        other = [o for o in whole + [p.get(lid, []) for p in per] if o]
        if ftp.SEE_RE.match(text or ""):
            out[lid] = (text, enum, group)
            continue
        inside = re.search(r"\s(\d{1,2})\s+[A-Z]", text or "")
        own = int(re.match(r"\d+", lid).group())
        if (inside and int(inside.group(1)) > own and any(
                k.startswith(inside.group(1) + "-") for k in (lengths or {}))):
            # The next clue run on after this one's count: cut it off, and
            # the count with it, which the grid gives.
            text = re.sub(r"\s*\([^)]*$", "", text[:inside.start()]).rstrip()
            enum = enum or (str(lengths[lid]) if (lengths or {}).get(lid) else None)
            inside = None
        if inside:
            blank[lid] = "another clue's number inside it"
            out[lid] = ("", enum, group)
            continue
        if re.match(r"[^A-Za-z\"'(.]*\s*[a-z]", text or ""):
            # Lower case first: the clue's opening ("23s about") was lost.
            blank[lid] = "starts mid-clue"
            out[lid] = ("", enum, group)
            continue
        if enum is None and (lengths or {}).get(lid):
            # The other readings vote on the words, so a cut-short end shows.
            enum = str(lengths[lid])
        if enum is None:
            # The count lost with the clue's end: the words may be cut short.
            blank[lid] = "no count read"
            out[lid] = ("", enum, group)
            continue
        text = clean(text)
        # The clue's own number read twice ("21 21 The woman", "1 11 Money").
        lead = re.match(r"(\d{1,2}) (?=[A-Z\"'])", text)
        if lead and lead.group(1) in lid.split("-")[0]:
            text = text[lead.end():]
        got, how = agree(text, other)
        if got is None:
            blank[lid] = how
            out[lid] = ("", enum, group)
        else:
            out[lid] = (got, enum, group)
    return out, blank


#: The share of the scanned grid's lights that clues must lie on, each by its
#: own number and count, for the grid to stand without the rest.
LOOSE_SHARE = 0.8


def lay_loose(parsed, grid, taken=None):
    """({light: (text, enumeration, None)}, [clues not laid]): each clue laid
    alone on the light its number names in its list's direction, when its
    number reads one way that names a light not yet taken and one of its
    count readings fills that light. Linked and "See" clues are not laid.
    With `taken` (the lights every reading laid by number), a clue whose
    number was lost also takes the one light outside `taken` that its laid
    neighbours leave between them."""
    lights = rg.light_cells(grid)
    out, bad = {}, []
    for direction in ("across", "down"):
        at = {}  # the clue's place in its list -> the light number it took
        for k, clue in enumerate(parsed[direction]):
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
        # Clues whose numbers were lost ("Made to smile ... (6)" between 1
        # and 9) take the lights their laid neighbours in the list leave
        # free between them, in order, when there are as many of each and
        # every count fills its light.
        clues = parsed[direction]
        if taken is None:
            continue
        laid_at = sorted(at)
        for lo_k, hi_k in zip([-1] + laid_at, laid_at + [len(clues)]):
            between = list(range(lo_k + 1, hi_k))
            if not between or hi_k == len(clues) or any(
                    clues[j]["tokens"] != [set()] or clues[j]["see"] is not None for j in between):
                continue
            lo = at[lo_k] if lo_k >= 0 else 0
            free = sorted(n for (n, d) in lights if d == direction and lo < n < at[hi_k]
                          and f"{n}-{d}" not in out and f"{n}-{d}" not in taken)
            if len(free) != len(between):
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
    for e in entries:
        lid = entry_id(e)
        text, enum, _ = laid.get(lid, ("", None, None))
        line = f"{text} ({enum})" if enum else text
        e["clue"] = enumeration.clue(line, separators=seps.get(lid), missing=not text.strip())
        if lid in groups:
            e["group"] = groups[lid]
        e["solution"] = None
    return {
        "id": series_meta.puzzle_id(series, number),
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
    for leaf, lines in leaf_lines(d / "djvu.xml.gz", leaves).items():
        titles, sols = paper.headings(lines)
        for n, box, setter in titles:
            found["puzzles"].append({"number": n, "leaf": leaf, "box": box, **({"setter": setter} if setter else {})})
        for n, box in sols:
            found["solutions"].append({"number": n, "leaf": leaf, "box": box})
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


def ft_expected_number(day):
    pts = FT_ANCHORS
    k = 0 if day < pts[1][0] else 1
    (d0, n0), (d1, n1) = pts[k], pts[k + 1]
    if day < d0 or day > d1:
        start, number = (d0, n0) if day < d0 else (d1, n1)
        return number + round((day - start).days * 6 / 7)
    return n0 + round((n1 - n0) * (day - d0).days / (d1 - d0).days)


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


_FT_SETTERS = None


def ft_setters():
    """The setters our ftcryptic files name: a pseudonym read off a scan
    ("Grifftn") stands only when it is one of them or a dictionary word."""
    global _FT_SETTERS
    if _FT_SETTERS is None:
        _FT_SETTERS = {json.loads(p.read_text()).get("setter")
                       for p in (ROOT / "puzzles" / FT.series).glob("*/*.json")}
    return _FT_SETTERS


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
        setter = setter and setter.group(1).title()
        puzzles.append((number_of(num.group(1)), centred((box[0], whole[1], box[2], whole[3]), FT_GRID_SPAN),
                        setter if setter and (setter in ft_setters() or is_word(setter.lower())) else None))
    return puzzles, solutions


class Paper:
    """One newspaper's run of archive.org items: where its editions are, how
    its titles and solution headings read, the number its date implies, and
    the series its puzzles file as."""

    def __init__(self, key, series, item, name, expected):
        self.key, self.series, self.item, self.name, self.expected = key, series, item, name, expected

    def headings(self, lines):
        if self.key == "ft":
            return ft_headings(lines)
        return ([(n, box, None) for n, box in headings(lines, TITLE)], headings(lines, SOLUTION))


TIMES = Paper("times", SERIES, ITEM, "Times cryptic crossword No {:,}", expected_number)
FT = Paper("ft", "ftcryptic", re.compile(r"FinancialTimes(19\d\d)UKEnglish$"),
           "Financial Times cryptic crossword No {:,}", ft_expected_number)
PAPERS = {p.key: p for p in (TIMES, FT)}


def paper_of(d):
    """The Paper an edition directory's item belongs to."""
    return next((p for p in PAPERS.values() if p.item.match(Path(d).parent.name)), TIMES)


#: The Times of the 1970s-80s prints its blocks grey (67-82% ink in the
#: scans), not solid; the grid must still be symmetric to stand.
BLOCK_ABOVE = 0.6


def read_puzzle(d, found, hit, solutions):
    """(verdict, puzzle or None) for one title on one page."""
    n, leaf = hit["number"], hit["leaf"]
    verdict = {"number": n, "leaf": leaf}
    paper = paper_of(d)
    day = datetime.date.fromisoformat(found["date"])
    if abs(n - paper.expected(day)) > NUMBER_SLACK:
        verdict["refused"] = (f"No {n} is not near the {paper.expected(day)} the date "
                              f"{day} implies: the item's date is wrong")
        return verdict, None
    img = page(d, leaf)
    lines = leaf_lines(d / "djvu.xml.gz", {leaf})[leaf]
    gbox = grid_box(img, hit["box"])
    if gbox is None:
        verdict["refused"] = "no ink under the title"
        return verdict, None
    gw, gh = gbox[2] - gbox[0], gbox[3] - gbox[1]
    if not (500 <= gw <= 1100 and 0.85 <= gw / max(gh, 1) <= 1.18):
        verdict["refused"] = f"the ink under the title is {gw}x{gh}, not a grid"
        return verdict, None
    key = f"{d.name}_{n}"
    texts = {"djvu": column_text(columns(lines, gbox))}
    for which in READERS:
        texts[which] = column_text(columns(
            rapid_lines(img, gbox, which, CROPS / "rapid" / f"{key}.{reader_key(which)}.json"), gbox))
    # archive.org's words and RapidOCR's are the two readings; where
    # archive.org's OCR has no words for the columns, RapidOCR's two
    # recognisers are.
    gpath = CROPS / "grids" / f"{key}.png"
    gpath.parent.mkdir(parents=True, exist_ok=True)
    if not gpath.exists():
        img.crop((gbox[0] - 6, gbox[1] - 6, gbox[2] + 6, gbox[3] + 6)).save(gpath)
    image, why = trove_grid.read_grid(gpath, block_above=BLOCK_ABOVE)
    g = image
    if g and not trove_grid.symmetric(g):
        g, why = None, "not 180-degree symmetric"
    if not g:
        verdict["imageUnread"] = why
    # Each reading in turn is the list, repaired from the other: archive.org's
    # against RapidOCR's, and where archive.org has no words for the columns,
    # RapidOCR's two recognisers against each other. The first list that
    # lies on the scanned grid wins; failing all, the most complete list is
    # rebuilt.
    pairs = ([("djvu", "ch"), ("ch", "djvu"), ("djvu", "en5"), ("en5", "djvu")]
             if texts["djvu"].strip() else [("ch", "en5"), ("en5", "ch")])
    tried = []
    for order in pairs:
        parsed, why = parse(texts[order[0]])
        if parsed is None:
            verdict.setdefault("unparsed", {})[order[0]] = why
            continue
        if not trove_clue_ocr.complete(parsed):
            parsed, _ = trove_clue_ocr.repair(parsed, texts[order[1]])
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
        loose, src = {}, {}
        for _, _, _, _, o, p, _, _ in tried:
            for lid, v in lay_loose(p, g)[0].items():
                if lid not in loose:
                    loose[lid], src[lid] = v, o
        # Then the clues whose number was lost, into the lights no reading
        # laid by number.
        by_number = set(loose)
        for _, _, _, _, o, p, _, _ in tried:
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
    laid, blank = reconcile(laid, stream, {f"{n_}-{d_}": len(cells) for (n_, d_), cells
                                           in rg.light_cells(grid).items()})
    verdict["lights"] = len(rg.light_cells(grid))
    verdict["agreed"] = sum(1 for t, _, _ in laid.values() if t)
    if blank:
        verdict["blank"] = blank
    puzzle = build(n, day, grid, how, laid, found["item"], leaf, series=paper.series,
                   name=paper.name.format(n))
    if hit.get("setter"):
        puzzle["setter"] = hit["setter"]
    sol = solutions.get(n)
    if sol:
        answers, info = read_solution(sol, grid)
        verdict["solutionFrom"] = f"{sol['dir'].name} leaf {sol['leaf']}"
        verdict["solution"] = info
        verdict["answers"] = trove_solution_ocr.fill(puzzle, answers)
    return verdict, puzzle


#: The share of a solution grid's cells that must be block or light exactly
#: where the puzzle's grid has them, for its letters to count.
SOLUTION_BLOCKS = 0.97


def read_solution(sol, grid):
    """({light: answer}, stats) read off the solution grid under a "Solution
    to Puzzle No N" heading."""
    d, leaf = sol["dir"], sol["leaf"]
    x0, y0, x1, y1 = sol["box"]
    from PIL import Image
    img = page(d, leaf)
    w = x1 - x0
    crop = (max(0, x0 - 80), y1, min(img.width, x1 + 140), min(img.height, y1 + int(1.4 * w) + 60))
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

def code_hash():
    h = hashlib.sha256()
    for p in CODE:
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def input_hash(d, code):
    h = hashlib.sha256(code.encode())
    for p in sorted(d.iterdir()):
        st = p.stat()
        h.update(f"{p.name}:{st.st_size}".encode())
    return h.hexdigest()[:16]


def held_numbers(series=SERIES):
    return {int(p.stem.split("-")[1]) for p in (ROOT / "puzzles" / series).glob("*/*.json")}


def destination(puzzles, file_from, date, complete=True):
    """Where an edition dated `date` (YYYY-MM-DD) files its puzzle: the
    `puzzles` dir, None for the corpus, or False for nowhere. With
    `file_from`, editions of that year or later go to the corpus even when
    `puzzles` is set. A puzzle with a blank clue (not `complete`) never goes
    to the corpus: a solver cannot work it."""
    if not complete:
        return puzzles or False
    if puzzles and file_from and int((date or "0")[:4]) >= file_from:
        return None
    return puzzles


def complete(puzzle):
    """Whether every clue of a puzzle has text."""
    return filled(puzzle)[0] == len(puzzle["entries"])


def run(cache=CACHE, write=True, ledger=None, out=sys.stdout, puzzles=None, limit=None,
        source=SOURCE, file_from=None, paper=None):
    """File what is new under `cache`; `puzzles` writes there instead of the
    corpus (tests, and editions before `file_from`). Returns the ledger rows."""
    from fetch_puzzle import puzzle_path, write_puzzle_file
    ledger = Path(ledger or cache / "filed.jsonl")
    known = {}
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            row = json.loads(line)
            known[row["edition"]] = row
    code = code_hash()
    paper = paper or TIMES
    dirs = edition_dirs(cache, paper)
    # Every heading first: a puzzle's solution is in a later edition.
    scans = {}
    for d in dirs:
        rel = f"{d.parent.name}/{d.name}"
        row = known.get(rel)
        # The headings depend on the files alone: a change of code does not
        # make every edition's djvu.xml worth parsing again.
        fh = input_hash(d, "")
        if row and row.get("filesHash") == fh and "scan" in row:
            scans[rel] = row["scan"]
        else:
            scans[rel] = scan(d)
            known[rel] = {"edition": rel, "scan": scans[rel], "filesHash": fh}
    solutions = {}
    for d in dirs:
        for s in scans[f"{d.parent.name}/{d.name}"]["solutions"]:
            solutions.setdefault(s["number"], {**s, "dir": d})
    held = held_numbers(paper.series)
    fresh = 0
    for d in dirs:
        rel = f"{d.parent.name}/{d.name}"
        h = input_hash(d, code)
        row = known[rel]
        sol_seen = sorted(n for n in (p["number"] for p in scans[rel]["puzzles"]) if n in solutions)
        if row.get("hash") == h and row.get("solutionsSeen") == sol_seen:
            continue
        if limit is not None and fresh >= limit:
            continue
        fresh += 1
        verdicts = []
        for hit in scans[rel]["puzzles"]:
            try:
                verdict, puzzle = read_puzzle(d, scans[rel], hit, solutions)
            except Exception as e:  # noqa: BLE001 -- one bad page is a verdict, not a crash
                verdict, puzzle = {"number": hit["number"], "refused":
                                   f"crashed: {type(e).__name__}: {e}"}, None
            if puzzle is not None:
                verdict["id"] = puzzle["id"]
                if write:
                    source.mkdir(parents=True, exist_ok=True)
                    (source / f"{puzzle['id']}.json").write_text(json.dumps(puzzle, indent=1))
                dest = destination(puzzles, file_from, scans[rel].get("date"), complete(puzzle))
                if dest is False:
                    verdict["skip"] = "a clue is blank: only a puzzle with every clue goes to the corpus"
                    verdicts.append(verdict)
                    continue
                path = (Path(dest) / f"{puzzle['id']}.json" if dest
                        else puzzle_path(paper.series, puzzle["number"]))
                better = path.exists() and improves(puzzle, path)
                if hit["number"] in held and not dest and not better:
                    verdict["skip"] = "already held: the reading votes in cross_validate.py"
                elif write and (better or not path.exists()):
                    try:
                        write_puzzle_file(path, puzzle, generator=TOOL)
                    except puzzle_integrity.RefusedWrite as e:
                        verdict["refusedWrite"] = str(e)
                    else:
                        verdict["wrote"] = True
                        held.add(hit["number"])
            verdicts.append(verdict)
        known[rel] = {"edition": rel, "hash": h, "scan": scans[rel], "filesHash": input_hash(d, ""),
                      "solutionsSeen": sol_seen, "verdicts": verdicts}
        if write:
            save(ledger, known)
    if write:
        save(ledger, known)
    tally = report(known[f"{d.parent.name}/{d.name}"] for d in dirs)
    print(f"{len(dirs)} {paper.key} editions in {cache}; {fresh} read this run", file=out)
    for k in sorted(tally):
        print(f"  {tally[k]:5d}  {k}", file=out)
    return list(known.values())


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
    ap.add_argument("--out", type=Path, help="write puzzles here, not into puzzles/")
    ap.add_argument("--file-from", type=int, metavar="YEAR",
                    help="with --out, complete puzzles of YEAR or later still go into puzzles/")
    ap.add_argument("--source", type=Path, default=SOURCE,
                    help="where every reading goes for cross_validate.py")
    ap.add_argument("--limit", type=int, help="read at most N new or changed editions")
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    ap.add_argument("--show", metavar="ITEM/EDITION", help="one edition's verdicts")
    ap.add_argument("--paper", choices=sorted(PAPERS), default="times",
                    help="whose editions to file: the Times (times-N) or the FT (ftcryptic-N)")
    ap.add_argument("--match-canberra", action="store_true",
                    help="only name the Times puzzle each canberra file reprints")
    args = ap.parse_args(argv)
    if args.match_canberra:
        match_canberra(args.source, write=not args.dry_run)
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
        limit=args.limit, source=args.source, file_from=args.file_from, paper=PAPERS[args.paper])
    if not args.out and args.paper == "times":
        match_canberra(args.source, write=not args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
