#!/usr/bin/env python3
"""The clue-text OCR every scan filer shares: the readers, the vote, the check.

Every filer that reads clues off a picture (tools/file_archive_org_puzzles.py
for The Times, FT and Guardian scans, tools/archive_org_listener.py,
tools/file_trove_puzzles.py for the Canberra Times) reads them the same way:

  - READERS are the voters, each named, each read through read_words(): a
    PIL image in, the words and their boxes out. A new reader (another
    recogniser, a VLM) is one more READERS entry.
  - reconcile() puts each laid clue's text to every other reading: agree()
    settles each word on the spelling the readings share, then on the one
    lexicon spelling (tools/data/lexicon.tsv, with the corpus's own clue
    words), then on the known word every reading's slips point to
    (consensus()), and files the clue blank when nothing wins. relaid()
    lays each blank clue again from each reading that printed it whole
    (two others printing it alike, one of another copy) and puts it to the
    rest. vlm_pick()
    then shows each blank clue's readings to the desktop's VLM
    (tools/vlm_reader.py), when it answers.
  - as_printed() holds every filed clue, voted or picked, to what the
    readings print for its light: the count's shape ("(5-4)", not a lost
    count's "(9)"), and each word's capital, hyphen and known spelling.
  - suspect() is the check a filer runs before it writes: the words of a
    clue no reader could have meant (a digit or a stray mark inside a word,
    a capital after small letters, a word neither the lexicon nor the
    corpus's clues know, a name one OCR slip from a dictionary word). A
    puzzle with a suspect clue is not filed.
"""
import functools
import gzip
import itertools
import math
import os
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import enumeration

#: A "See N" clue, which carries no words of its own.
SEE_RE = re.compile(r"^see\s+(\d+)", re.IGNORECASE)


# ------------------------------------------------------------ the readers

_ENGINES = {}
#: RapidOCR reads the 200dpi print (~17px a line) far better twice the size.
UPSCALE = 2
#: The clue columns' readers: RapidOCR's own multilingual PP-OCRv4
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
#: Each reader's engine: readers of one engine share its slips, so two
#: readings of one engine are no two independent votes. A copy's reader
#: ("canberra:<article>:times") is its reader's engine; "page" is
#: gale_listener's whole-page Tesseract words.
FAMILIES = {"ch": "rapidocr", "en5": "rapidocr", "times": "tesseract", "page": "tesseract"}
#: A tie that splits the readings by engine goes to the spelling whose
#: engine's slip it would take is the likelier on the page (by_family): each
#: engine measured on FAMILY_WORDS settled words at least, and the one slip
#: likelier than the other with posterior odds of FAMILY_SURE at least.
FAMILY_WORDS = 100
FAMILY_SURE = 0.95


def family(name):
    """The engine (FAMILIES) of the reader `name`, None when unknown."""
    return FAMILIES.get((name or "").rsplit(":", 1)[-1])


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
        # Each parallel reader gets its share of the cores, or N workers each
        # take all of them and the host runs at N times its CPU count.
        threads = {"intra_op_num_threads": int(os.environ.get("OCR_THREADS", "-1")), "inter_op_num_threads": 1}
        _ENGINES[which] = RapidOCR(rec_model_path=str(model), **threads) if model else RapidOCR(**threads)
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


def tesseract_words(crop, model=None, psm=4):
    """[(x0, y0, x1, y1, word)] Tesseract reads in a PIL image, with the
    installed eng model or the .traineddata at `model`, in page
    segmentation mode `psm` (7: the image is one line)."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "crop.png"
        crop.save(path)
        lang = ["--tessdata-dir", str(model.parent), "-l", model.stem] if model else ["-l", "eng"]
        # TSV by parameter, not the "tsv" config file: a model's own
        # tessdata directory has no configs/.
        # Tesseract writes UTF-8 whatever the host's locale (the desktop's
        # is cp1252).
        # One thread: OpenMP's spinning threads take minutes over one crop
        # on a busy host, where a single thread takes seconds.
        res = subprocess.run([tesseract(), str(path), "-", "--psm", str(psm), *lang,
                              "-c", "tessedit_create_tsv=1"],
                             capture_output=True, encoding="utf-8", timeout=300, check=False,
                             env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    if res.returncode:
        raise RuntimeError(f"tesseract failed ({res.returncode}): {res.stderr.strip()[-300:]}")
    words = []
    for row in res.stdout.splitlines()[1:]:
        f = row.split("\t")
        if len(f) == 12 and f[0] == "5" and f[11].strip():
            x, y, w, h = map(int, f[6:10])
            words.append((x, y, x + w, y + h, f[11].strip()))
    return words


#: RapidOCR scales an image's longer side down to RAPID_MAX_SIDE (its
#: max_side_len), then each side to the nearest multiple of 32: a side under
#: RAPID_MIN_SIDE after that rounds to no pixels and raises ResizeImgError.
#: A crop that thin (a sliver under a page's last band) holds no line.
RAPID_MAX_SIDE = 2000
RAPID_MIN_SIDE = 16


def too_thin(width, height, which):
    """Whether RapidOCR reader `which` cannot read a width x height image."""
    if which in TESS_MODELS:
        return False
    return min(width, height) * min(1.0, RAPID_MAX_SIDE / max(width, height)) < RAPID_MIN_SIDE


def raw_words(crop, which):
    """[(x0, y0, x1, y1, word)] reader `which` reads in the PIL image `crop`,
    in its pixels as the reader gives them (RapidOCR's floats): none in a
    crop too thin for it (too_thin)."""
    if which in TESS_MODELS:
        return tesseract_words(crop, TESS_MODELS[which])
    if too_thin(crop.width, crop.height, which):
        return []
    import numpy as np
    res, _ = engine(which)(np.asarray(crop), use_cls=False)
    words = []
    for b, t, _ in res or ():
        xs, ys = [p[0] for p in b], [p[1] for p in b]
        words.append((min(xs), min(ys), max(xs), max(ys), t))
    return words


def read_words(img, which):
    """[(x0, y0, x1, y1, word)] reader `which` reads in the PIL image `img`,
    read at UPSCALE times its size, in `img`'s own pixels: none in an image
    with no pixels or too thin for the reader (too_thin). Read on the desktop when tools/ocr_remote.py can, the
    same reading as here."""
    import ocr_remote
    crop = img.convert("RGB")
    if not crop.width or not crop.height:
        return []
    crop = crop.resize((crop.width * UPSCALE, crop.height * UPSCALE))
    if too_thin(crop.width, crop.height, which):
        return []
    words = ocr_remote.words(crop, which)
    if words is None:
        with ocr_remote.local_slot():
            words = raw_words(crop, which)
    return [(int(x0 / UPSCALE), int(y0 / UPSCALE), int(x1 / UPSCALE), int(y1 / UPSCALE), t)
            for x0, y0, x1, y1, t in words]


#: A printed blank ("——", the word a quotation leaves out) is a thin rule
#: at mid-letter height, often fainter than the type (No 15's 30 across is
#: grey 130-170): its ink is anything darker than BLANK_INK. It is
#: BLANK_LONG times a word's height long at least (a hyphen is shorter),
#: BLANK_LONGEST at most (a rule under a heading or across a column is
#: longer), BLANK_THICK of a word's height thick at most, with nothing
#: above or below it, and stands in a clue line or alone on the line
#: under one.
BLANK_INK = 175
BLANK_LONG = 1.1
BLANK_LONGEST = 5
BLANK_THICK = 0.2
#: A gap in a blank's rule (the space between the dashes of "——") at most,
#: in a word's height.
BLANK_GAP = 0.4
#: How far after a blank its closing quote stands at most, in a word's
#: height (the stop after it stands further).
BLANK_QUOTE = 0.4
#: The space either side of a blank at least, and a grid wall's height,
#: in a word's height.
BLANK_APART = 0.2
BLANK_WALL = 1.8
#: A rule run into a word after it (No 4 9D's "'——and"), or before and
#: after it, is a blank this long at least, in a word's height: two ems,
#: where a dash is one. One run into the word before it and ending its
#: line (No 4 15D's "no——" over "could draw") needs only BLANK_LONG.
BLANK_RUN_IN = 1.8
BLANK = "——"
DASHES = re.compile(r"\s*[-‐-―_~=]+\s*")


def blank_strokes(img, lines, words, h):
    """[(x0, y0, x1, y1, text)] each printed blank in the clue `lines`
    ([(x0, y0, x1, y1)], the lists' printed lines) of the page `img`, a
    word "——" ("——'" when a closing quote follows it); `h` is a word's
    height. A blank is a thin rule within a line, or alone just under one
    and within its span (No 15's 23 down, "Give me a" over "——'"). No
    reader sees a faint one, and each reads a dark one its own way
    ("the-is", " - "). `words` ([(x0, y0, x1, y1, text)]) are the page's:
    a rule under or through one is a mark on it, no blank."""
    import numpy as np
    words = [w for w in words if not DASHES.fullmatch(w[4])]
    ink = np.asarray(img.convert("L")) < BLANK_INK
    found, seen = [], set()
    for y in np.flatnonzero(ink.sum(axis=1) >= 0.75 * BLANK_LONG * h):
        y = int(y)
        if y in seen:
            continue
        xs = np.flatnonzero(ink[y])
        for run in np.split(xs, np.flatnonzero(np.diff(xs) > BLANK_GAP * h) + 1):
            x0, x1 = int(run[0]), int(run[-1]) + 1
            before = after = False
            if len(run) < 0.75 * (x1 - x0):
                # The run's longest unbroken stretch is the rule, the words
                # touching it on either side.
                solid = max(np.split(run, np.flatnonzero(np.diff(run) > 1) + 1), key=len)
                before, after = int(solid[0]) > x0, int(solid[-1]) + 1 < x1
                x0, x1 = int(solid[0]), int(solid[-1]) + 1
                if not BLANK_LONG * h <= x1 - x0 <= BLANK_LONGEST * h:
                    continue
                if x1 - x0 < BLANK_RUN_IN * h and (after or not line_end(x1, y, lines, h)):
                    continue
            elif not BLANK_LONG * h <= x1 - x0 <= BLANK_LONGEST * h:
                continue
            run_in = before or after
            span = ink[:, x0:x1].mean(axis=1)
            y0, y1 = y, y + 1
            while y0 > 0 and span[y0 - 1] >= 0.3:
                y0 -= 1
            while y1 < len(span) and span[y1] >= 0.3:
                y1 += 1
            if y1 - y0 > max(3, BLANK_THICK * h) or span[max(0, y0 - 3):max(0, y0 - 1)].max(initial=0) > 0.15 \
                    or span[y1 + 1:y1 + 3].max(initial=0) > 0.15:
                continue
            seen.update(range(y0, y1))
            if apart(ink, x0, y0, x1, y1, h, before, after) and placed((x0, (y0 + y1) / 2, x1), lines, h) \
                    and not any(w[1] - 0.2 * h <= y <= w[3] + 0.2 * h and min(w[2], x1) - max(w[0], x0) > 0.3 * (x1 - x0)
                                # A rule run into a word is no underline: a
                                # word over it, or one running on past it on
                                # the side it touches, is one whose box took
                                # it in.
                                and not (run_in and not w[1] + 0.25 * (w[3] - w[1]) <= y <= w[3] - 0.25 * (w[3] - w[1]))
                                and not (before and w[0] < x0 - 0.3 * h) and not (after and w[2] > x1 + 0.3 * h)
                                for w in words):
                found.append((x0, y0, x1, y1, ("'" if after and not before and opened(ink, x0, y0, y1, h) else "")
                              + BLANK + ("'" if quoted(ink, x1, y0, y1, h) else "")))
    return found


def apart(ink, x0, y0, x1, y1, h, before=False, after=False):
    """Whether a rule stands apart as a blank does: a space before it at any
    height (a dash after a mark, "NOTE.\u2014Clues", "competitors:\u2014",
    is punctuation; a colon's dots miss the rule's own rows), a space after
    it at its height (a stop, comma or closing quote may follow), and no
    stroke taller than BLANK_WALL words near it (a grid's line or bar
    between its walls). A rule run into the word `before` it or `after` it
    (blank_strokes) needs no space on that side; one run into the word
    after it alone has the space before it from its own rows down: an
    opening quote stands above them ("'——and")."""
    gap = max(3, int(BLANK_APART * h))
    space = ink[max(0, int(y0 - (1 if after else 0.45 * h))):int(y1 + 0.45 * h), max(0, x0 - 1 - gap):max(0, x0 - 1)]
    if not before and space.any() or not after and ink[y0:y1, x1 + 1:x1 + 1 + 2 * gap].any():
        return False
    near = ink[max(0, int(y0 - 2 * h)):int(y1 + 2 * h), max(0, int(x0 - h)):int(x1 + h)]
    for col in near.T:
        run = 0
        for v in col:
            run = run + 1 if v else 0
            if run >= BLANK_WALL * h:
                return False
    return True


def line_end(x1, y, lines, h):
    """Whether a rule ending at x1 at height y ends one of the clue `lines`."""
    return any(l[1] <= y <= l[3] and abs(l[2] - x1) <= 0.3 * h for l in lines)


def placed(stroke, lines, h):
    """Whether a rule (x0, y, x1) stands in one of the clue `lines`, at the
    middle of its height and within its span, or alone on the line under
    one, under its words: not a line's underline, which runs just under
    its letters, nor a rule outside the lists."""
    x0, y, x1 = stroke
    if any(l[1] + 0.25 * (l[3] - l[1]) <= y <= l[3] - 0.15 * (l[3] - l[1]) and l[0] - h <= x0 <= l[2] + 3 * h
           for l in lines):
        return True
    if any(l[1] - 0.3 * h <= y <= l[3] + 0.3 * h and min(l[2], x1) > max(l[0], x0) for l in lines):
        return False
    return any(0.3 * h <= y - l[3] <= 1.2 * h and l[0] <= x0 < l[2] for l in lines)


def opened(ink, x0, y0, y1, h):
    """Whether an opening quote stands just before a rule starting at x0:
    ink within BLANK_QUOTE of a word's height to its left, over the rule,
    and none beside it (No 4 9D's "'——and")."""
    left = ink[:, max(0, int(x0 - BLANK_QUOTE * h)):max(0, x0 - 1)]
    return bool(left[max(0, int(y0 - BLANK_QUOTE * h)):max(0, y0 - 1)].any()) and not left[max(0, y0 - 1):y1 + 1].any()


def quoted(ink, x1, y0, y1, h):
    """Whether a closing quote stands just after a rule ending at x1: within
    BLANK_QUOTE of a word's height to its right, ink over the rule (below
    the line above's descenders) and none beside it, where a letter's
    would cross (a stop below it is no matter)."""
    right = ink[:, x1 + 1:int(x1 + BLANK_QUOTE * h)]
    return bool(right[max(0, int(y0 - BLANK_QUOTE * h)):y0 - 1].any()) and not right[y0 - 1:y1 + 1].any()


def with_blanks(words, blanks):
    """A reading's `words` with each printed blank (blank_strokes) put in:
    the dash a box reads where the blank stands made the blank, else the
    blank set in at its place in the box's text, else a word of its own.
    Every reading then votes the same blank."""
    out = list(words)
    for b in blanks:
        mid = (b[1] + b[3]) / 2
        over = [i for i, w in enumerate(out) if w[1] <= mid <= w[3]
                and min(w[2], b[2]) - max(w[0], b[0]) >= 0.5 * (b[2] - b[0])]
        if not over:
            out.append(b)
            continue
        i = over[0]
        w = out[i]
        text = w[4]
        at = round(((b[0] + b[2]) / 2 - w[0]) / max(1, w[2] - w[0]) * len(text))
        near = min(DASHES.finditer(text), key=lambda m: abs((m.start() + m.end()) / 2 - at), default=None)
        if near and abs((near.start() + near.end()) / 2 - at) <= max(3, 0.15 * len(text)):
            a, z = near.span()
        else:
            # No dash read there: the blank goes in at the nearest space.
            spaces = [m.start() for m in re.finditer(r"\s|$", text)] + [0]
            a = z = min(spaces, key=lambda k: abs(k - at))
        head, tail = text[:a].rstrip(), text[z:].lstrip()
        out[i] = (*w[:4], " ".join(p for p in (head, b[4] if not tail.startswith("'") else BLANK, tail) if p))
    return out


def lines_of(words):
    """The words as printed rows, one a line: a word starts a new row when its
    top is below half the row's first word's height."""
    lines, row, top, height = [], [], None, 0
    for x0, y0, x1, y1, t in sorted(words, key=lambda w: (w[1], w[0])):
        if row and y0 > top + height / 2:
            lines.append(" ".join(t for _, t in sorted(row)))
            row = []
        if not row:
            top, height = y0, y1 - y0
        row.append((x0, t))
    if row:
        lines.append(" ".join(t for _, t in sorted(row)))
    return "\n".join(lines)


# ------------------------------------------------------------ the vote


def tokens(text):
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)


@functools.lru_cache(maxsize=1 << 18)
def similar(a, b):
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


#: What a mark one reading lacks costs in align(), against 1 for a word.
MARK_GAP = 0.5
#: Pairing a digit glued to a word with another reading's mark there.
DIGIT_MARK = 0.4
#: Pairing a word with a number another reading reads in its place (No 3's
#: ch reads "in" as "111"): just under a word lost on each side, so the
#: words after it pair rather than the clue ending there.
WORD_FIGURE = 1.9


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
            glued = mine[i - 1].isdigit()  # a number glued to a word ("WW2", "know7")
            pair = cost[i - 1][j - 1] + (0.0 if mine[i - 1] == theirs[j - 1] or (
                                             glued and theirs[j - 1] == BREAK) else
                                         WORD_FIGURE if theirs[j - 1] == BREAK and mine[i - 1].isalpha() else inf
                                         if theirs[j - 1] == BREAK
                                         # A mark misread as a digit ("know7"), dearer
                                         # than a number but less than a mark lost.
                                         else DIGIT_MARK if glued and theirs[j - 1] in MARKS
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
    low = word.lower()
    if low.endswith("'s") and len(low) > 3 and low[:-2] in _LEXICON:
        return _LEXICON[low[:-2]]  # "that's" is as common as "that"
    return _LEXICON.get(low) or _LEXICON.get(low.replace("'", ""))


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


def closed_compound(word):
    """Whether a word no lexicon knows is two known words of 3+ letters
    closed up ("spongecake")."""
    return any(is_word(word[:k]) and is_word(word[k:]) for k in range(3, len(word) - 2))


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
    """The spellings one letter's change, loss or addition from `word`, or
    one "rn" read as "m" or back ("camivore")."""
    w, abc = word.lower(), "abcdefghijklmnopqrstuvwxyz"
    splits = [(w[:k], w[k:]) for k in range(len(w) + 1)]
    rn = {w[:k] + new + w[k + len(old):] for old, new in (("m", "rn"), ("rn", "m"))
          for k in range(len(w)) if w.startswith(old, k)}
    return ({a + b[1:] for a, b in splits if b} | {a + c + b[1:] for a, b in splits if b for c in abc}
            | {a + c + b for a, b in splits for c in abc} | rn) - {w}


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


#: The misreadings worn newsprint makes one way only: (printed, read).
ONE_WAY = (("e", "c"), ("o", "c"))


def misread(read, printed):
    """Whether `read` is `printed` with one ONE_WAY letter misread."""
    if len(read) != len(printed):
        return False
    diff = [(p, r) for p, r in zip(printed, read) if p != r]
    return len(diff) == 1 and diff[0] in ONE_WAY


def worn(word):
    """The known word `word` (a non-word) is with one ONE_WAY letter worn,
    SLIP_RATIO times commoner than any other it could be ("of" for No 3's
    "cf"), else None."""
    low = word.lower()
    cands = sorted({v for i, ch in enumerate(low) for p, r in ONE_WAY if ch == r
                    and known(v := low[:i] + p + low[i + 1:])}, key=lambda v: rank(v) or 10 ** 9)
    if not cands or (len(cands) > 1 and (rank(cands[0]) or 10 ** 9) * SLIP_RATIO >= (rank(cands[1]) or 10 ** 9)):
        return None
    return cands[0]


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


#: Letters a reader takes for one another one at a time, both ways: the
#: print's worn type (SLIPS) and the shapes the readers confuse ("fudge"
#: for "judge", "ear" for "eat", "ad" for "an").
CONFUSED = tuple(p for p in SLIPS if len(p[0]) == len(p[1]) == 1) + (
    ("f", "j"), ("r", "t"), ("d", "n"), ("n", "h"))
#: How much better a word one CONFUSED letter from the voted one must fit
#: its neighbours in the corpus's clues to replace it ("single element", not
#: "single clement"; "for an entertainer", not "for ad entertainer").
CONFUSED_FIT = 3.5


def confused(word):
    """The spellings one CONFUSED letter from `word` (lower case)."""
    low, out = word.lower(), set()
    for a, b in CONFUSED + tuple((b, a) for a, b in CONFUSED):
        at = low.find(a)
        while at >= 0:
            out.add(low[:at] + b + low[at + 1:])
            at = low.find(a, at + 1)
    return out


def likelier(word, before, after, read=None):
    """The lexicon word one CONFUSED letter from the voted `word` that the
    lexicon ranks commoner and that fits its neighbours in the corpus's
    clues CONFUSED_FIT better than it, else None. A lexicon word gives way
    only to a spelling one of the readings `read` has there ("element" for
    "clement"): the corpus's fit alone would turn "if" into "it" and
    "tight" into "right"."""
    r = rank(word)
    own = fit(word, before, after)
    best = max(((fit(c, before, after), c) for c in confused(word)
                if (rank(c) or 10 ** 9) < (r or 10 ** 9) and (r is None or c in (read or ()))),
               default=None)
    return best[1] if best and best[0] - own >= CONFUSED_FIT else None


def swappable(text, at, word):
    """Whether `word`, at `at` in `text`, is one likelier() may respell:
    not an abbreviation or numeral in capitals ("MC", "II"), a light's
    "ac", half of a hyphened word ("co-opted", "Heigh-ho") or a word that
    drops its first letter after an apostrophe ("'ot")."""
    return not (any(c.isupper() for c in word[1:]) or re.fullmatch(LIGHT_WORD, word)
                or text[at + len(word):at + len(word) + 1] == "-"
                or (at and text[at - 1] in "-'\u2019"))


#: What a slip costs in slips(): a letter worn type or the readers turn into
#: another (CONFUSED, or one of SLIPS' pairs of letters); any other letter
#: changed, lost or put in costs 1.
SLIP_COST = 0.5
#: An apostrophe the print has and the reader lost costs this: readers drop
#: one far more often than they make one up ("cant" for "can't").
LOST_MARK = 0.25
_SLIP_PAIRS = frozenset(CONFUSED) | frozenset((b, a) for a, b in CONFUSED)
_SLIP_RUNS = tuple(p for p in SLIPS if len(p[0]) != len(p[1]))
_SLIP_RUNS += tuple((b, a) for a, b in _SLIP_RUNS)


@functools.lru_cache(maxsize=1 << 16)
def slips(a, b):
    """What it costs a reader to read `b` where `a` is printed, case aside:
    the edit distance with SLIP_COST for a likely slip ("tbar's" for "that's"
    is 1, two slips)."""
    a, b = a.lower(), b.lower()
    n, m = len(a), len(b)
    d = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = d[i - 1][0] + (LOST_MARK if a[i - 1] == "'" else 1)
    for j in range(1, m + 1):
        d[0][j] = d[0][j - 1] + 1
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            x, y = a[i - 1], b[j - 1]
            sub = 0 if x == y else SLIP_COST if (x, y) in _SLIP_PAIRS else 1
            best = min(d[i - 1][j - 1] + sub, d[i - 1][j] + (LOST_MARK if x == "'" else 1), d[i][j - 1] + 1)
            for p, q in _SLIP_RUNS:
                if i >= len(p) and j >= len(q) and a[i - len(p):i] == p and b[j - len(q):j] == q:
                    best = min(best, d[i - len(p)][j - len(q)] + SLIP_COST)
            d[i][j] = best
    return d[n][m]


def near_words(word):
    """The known words a reader may have misread as `word` (lower case): up
    to two CONFUSED letters off, or one CONFUSED letter and one other change."""
    w = word.lower()
    out = set()
    for v in {w} | confused(w):
        out |= {c for c in {v} | confused(v) | edits(v) if len(c) > 1 and known(c)}
    return out


#: The shortest word the lexicon's consensus settles: "Sbc" may be "She",
#: "Abe" or "Sac", where no reading's slips say which.
CONSENSUS_MIN = 4
#: What one reading's slips may add to a spelling's cost at most: a reading
#: of another word (aligned off by one) says nothing of this one.
CONSENSUS_CAP = 3.0
#: What a tenfold rarer word costs, against SLIP_COST a slip: the readers'
#: "thar's" is a slip from "that's" far likelier than a goat.
RARITY_COST = 0.25
#: The rank a known word the lexicon lacks counts as (a name the corpus's
#: clues use).
UNRANKED = 100000
#: How much cheaper the consensus must be than the next spelling.
CONSENSUS_MARGIN = 0.5


def consensus(read, before=None, after=None):
    """The known word the readings `read` (each reading's word at one place,
    any case) most likely all misread, or None (when the readings' middle
    length is under CONSENSUS_MIN): of the known words near any
    reading and within a letter of their middle length and of the first
    reading's (the clue's own, which it replaces), the one whose slips from every reading (slips(), each capped at
    CONSENSUS_CAP) plus its rarity cost least, CONSENSUS_MARGIN under the
    next, a tie going to the one that fits its neighbours in the corpus's
    clues FIT_MARGIN better. At least two readings must lie within one
    change (or a quarter of its letters' changes) of it, and a spelling
    most readings share gives way only to a word one slip from it, and
    never when it is a word formed() knows ("Ciry" is "City"; "Jenkyns"
    stays a name, "unscared" a word). Nor does it settle anything when one
    reading's spelling lies more than one change nearer all the readings
    than it does: they read a word the lexicon lacks."""
    read = [r.lower() for r in read if r and re.fullmatch(r"[A-Za-z]+(?:'[A-Za-z]+)?", r)]
    size = sorted(map(len, read))[len(read) // 2] if read else 0
    if len(read) < 2 or size < CONSENSUS_MIN:
        return None
    cands = set().union(*(near_words(r) for r in set(read)))
    if not cands:
        return None
    # A spelling most readings share is theirs, not a slip, unless the
    # word is one slip from it ("Jaques" stays; "Ciry" is "City").
    shared = max(read, key=read.count)
    held = read.count(shared) * 2 > len(read)

    def cost(c):
        return (sum(min(slips(c, r), CONSENSUS_CAP) for r in read)
                + RARITY_COST * math.log10(rank(c) or UNRANKED))
    ranked = sorted((cost(c), c) for c in cands)
    best = ranked[0][1]
    if len(best) < CONSENSUS_MIN or max(abs(len(best) - size), abs(len(best) - len(read[0]))) > 1 or sum(slips(best, r) <= max(1.0, len(best) / 4) for r in read) < 2:
        return None
    if held and (slips(best, shared) > SLIP_COST or formed(shared)):
        return None
    # Readings nearer one another than the word is to them read a word the
    # lexicon lacks ("cameelious", not "cancellous").
    medoid = min(sum(min(slips(r, o), CONSENSUS_CAP) for o in read) for r in set(read))
    if sum(min(slips(best, r), CONSENSUS_CAP) for r in read) > medoid + 1:
        return None
    rivals = [c for k, c in ranked[1:] if k - ranked[0][0] < CONSENSUS_MARGIN]
    if rivals and all(fit(best, before, after) - fit(c, before, after) < FIT_MARGIN for c in rivals):
        return None
    return best


#: The letters a digit standing alone may be a reader's misread of.
DIGIT_LETTERS = {"0": "o", "1": "ilt", "3": "a", "5": "s"}


def digit_word(number, read):
    """Whether the number `number` is the word `read` misread, letter by
    letter ("10" for "to", "3" for "a")."""
    return len(number) == len(read) and all(d in DIGIT_LETTERS and c in DIGIT_LETTERS[d]
                                            for d, c in zip(number, read.lower()))


#: Punctuation inside a clue that the readings vote on like words.
MARKS = ",;:!?"


#: A number in another reading's text (a clue's number or its count), which
#: bounds the clue: the words between it and the clue's are the clue's too.
BREAK = "#"


def marked(text, breaks=False):
    """The words and the voted punctuation marks of a text, in order; with
    `breaks`, each number too, as BREAK."""
    # A number naming a light ("2 down") is the clue's own text, not a bound.
    text = re.sub(r"\d+(?=\s*(?:across|down|ac|dn)\b)", " ", text, flags=re.IGNORECASE)
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


#: How alike a word of another reading must be to one of the clue's for
#: that reading to print it there (prints).
PRINTS_SIMILAR = 0.8


def prints(pairs, low, theirs):
    """Whether the other reading `theirs` prints the clue `low` where align
    put it: words alike, or run into the next ("eatsjunkets"), or the
    clue's own run together (No 4 21D's "featureofEngland'snationai" holding
    "feature"), hold more than half the clue's letters. One that lost the clue still aligns it somewhere ("stop" on
    "supposed"), and its words there are another clue's: no vote on this
    one's words or ends."""
    letters = sum(len(w) for w in low if w not in MARKS and w != BREAK)
    hit = 0
    for i, j in pairs:
        if i is not None and j is not None and low[i] not in MARKS and low[i] != BREAK:
            theirs_j = theirs[j].lower()
            if similar(low[i], theirs_j) >= PRINTS_SIMILAR or len(low[i]) > 2 and low[i] in theirs_j:
                hit += len(low[i])
            elif len(theirs_j) > 2 and theirs_j in low[i]:
                hit += len(theirs_j)
    return hit * 2 > letters


def another_clue(pairs, low, theirs, clues):
    """Whether the words align put the clue `low` on in the other reading
    `theirs` differ from it and are word for word another laid clue's
    (`clues`, each its lower-case words): No 3's times reading, which lost
    44D's "Hindustani for 'red'", aligns it on 14D's "Hindustani for
    'cupboard'"."""
    hit = [(i, j) for i, j in pairs if i is not None and j is not None]
    if not hit or all(similar(low[i], theirs[j].lower()) >= PRINTS_SIMILAR for i, j in hit):
        return False
    span = [w.lower() for w in theirs[hit[0][1]:hit[-1][1] + 1] if w not in MARKS and w != BREAK]
    return any(len(c) == len(span) and all(similar(a, b) >= PRINTS_SIMILAR for a, b in zip(c, span)) for c in clues)


def parted(clue, others):
    """`clue` with a non-word in it that another reading prints as two or
    more words ("theplant", "favouriteVictorian", a whole clue
    "Paintedbrownrestaurantred...", and "fora" for "for a",
    whose two words the corpus's clues print far more) parted as they are, and
    two words it ran together over a stop ("to.poison", "Anag.of") parted."""
    # Words run together over a stop are one run here: "walls.from" is
    # longer than any word of No 17 16D.
    runs = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)*", re.sub(r"(?<=[A-Za-z])\.(?=[a-z]{2})", "", clue))
    longest = max((len(w) for w in runs), default=0)
    apart = {}
    for theirs in others:
        for i in range(len(theirs)):
            joined, sizes = "", []
            for w in theirs[i:]:
                if not w.replace("'", "").isalpha() or len(joined) + len(w) > longest:
                    break
                joined += w.lower()
                sizes.append(len(w))
                if len(sizes) > 1:
                    apart.setdefault(joined, list(sizes))
    marked_apart = {(a + c).lower() for theirs in others for a, b, c in zip(theirs, theirs[1:], theirs[2:])
                    if a.isalpha() and b in MARKS and c.isalpha()}

    words, pairs, _ = clue_lm()

    def part(m):
        w = m.group()
        sizes = apart.get(w.lower())
        if not sizes:
            # Three words or more run together with a letter misread in
            # them (No 4 21D's "featureofEngland'snationai" for "feature of
            # England's national") part as another reading prints them.
            near = [z for j, z in apart.items() if len(z) >= 3 and len(j) == len(w)
                    and sum(a != b for a, b in zip(j, w.lower())) == 1]
            sizes = near[0] if len(near) == 1 else None
        if not sizes:
            return w
        if is_word(w.lower()):
            # A dictionary word stays whole ("hairstyle", which a reading
            # broke over a line end), unless the corpus's clues print the
            # two words far more than it: "fora" for "for a".
            k = sizes[0]
            if len(sizes) != 2 or pairs.get(f"{w[:k].lower()} {w[k:].lower()}", 0) <= words.get(w.lower(), 0):
                return w
        out, k = [], 0
        for size in sizes:
            out.append(w[k:k + size])
            k += size
        return " ".join(out)

    def stop(m):
        # A stop between two words another reading prints side by side:
        # after a word, a speck ("to.poison"); after no word, an
        # abbreviation's ("Anag.of").
        a, b = m.group(1), m.group(2)
        if (a + b).lower() not in apart and (a + b).lower() not in marked_apart:
            return m.group()
        return f"{a} {b}" if a.islower() and is_word(a) else f"{a}. {b}"
    def quote(m):
        # An apostrophe between two words another reading prints apart: a
        # plural's possessive after an s ("soldiers' tea"), else a quotation
        # opening ("say,'Give"); a known contraction ("they're") stays.
        a, b = m.group(1), m.group(2)
        if (a + b).lower() not in apart or known(m.group().lower()):
            return m.group()
        return f"{a}' {b}" if a[-1] in "sS" else f"{a} '{b}"
    clue = re.sub(r"\b([A-Za-z]+)\.([a-z]{2,})\b", stop, clue)
    clue = re.sub(r"\b([A-Za-z]{2,})'([A-Za-z]{2,})\b", quote, clue)
    return re.sub(r"[A-Za-z]+(?:'[A-Za-z]+)*", lambda m: part(m) if len(m.group()) >= 4 else m.group(), clue)


def unglued(theirs, low):
    """Another reading's tokens with two to four of this clue's words it
    ran together ("eatsjunkets", "laidyoursoul") parted again, or over
    the quote that opens the second (No 3's "for'red" for "for 'red'"); an
    apostrophe before a contraction's ending ("that's") opens no quote. A
    run of three or four words is parted too with one letter misread
    (No 3's "theMoghulEmpirefoi" for "the Moghul Empire fot")."""
    runs = {"".join(low[i:i + n]): low[i:i + n] for n in (2, 3, 4) for i in range(len(low) - n + 1)
            if all(w.isalpha() for w in low[i:i + n])}
    out = []
    for t in theirs:
        if (m := re.fullmatch(r"([A-Za-z]+)['‘’]([A-Za-z]+)", t)) and m[0].lower() not in low \
                and not CONTRACTED.fullmatch(m[2]) and runs.get((m[1] + m[2]).lower()) == [m[1].lower(), m[2].lower()]:
            out += [m[1], m[2]]
            continue
        run = runs.get(t.lower())
        if run is None and t.isalpha():
            near = [r for j, r in runs.items() if len(r) > 2 and len(j) == len(t)
                    and sum(a != b for a, b in zip(j, t.lower())) == 1]
            run = near[0] if len(near) == 1 else None
        k = 0
        for w in run or [t]:
            out.append(t[k:k + len(w)])
            k += len(w)
    return out


def rejoin(theirs, low):
    """Another reading's tokens with a word it split joined again, when this
    clue's words (`low`) hold the joined word, or one a letter from it, and
    it is a dictionary word: one
    split at a line end ("taste. fully", "subter fuge") or spaced out letter
    by letter ("w a lk")."""
    out, k = [], 0
    while k < len(theirs):
        for parts in ([1, 2, 3], [1, 2], [1], [2]):
            if k + parts[-1] >= len(theirs) or (parts == [2] and theirs[k + 1] not in MARKS):
                continue
            pieces = [theirs[k]] + [theirs[k + p] for p in parts]
            joined = "".join(pieces).lower()
            # Words with a space between are words ("of fish"): only a mark,
            # or a piece that is no word, says one was split.
            apart = parts == [2] or not all(is_word(t.lower()) for t in pieces)
            # The clue may misread the joined word by a letter ("obviousJy").
            here = joined in low or (len(joined) > 4 and any(within_one(joined, w) for w in low))
            if all(t.isalpha() for t in pieces) and apart and here and is_word(joined):
                out.append("".join(pieces))
                k += parts[-1] + 1
                break
        else:
            out.append(theirs[k])
            k += 1
    return out


def ends_joined(theirs, low):
    """Another reading's tokens with the clue's first or last word joined
    again where it split it over a line end ("hair. Style" before the
    count, for this clue's "hairstyle"): two words next to the number that
    bounds the clue, which together spell this clue's word at that end."""
    if not low:
        return theirs
    out = list(theirs)
    for k in range(len(out) - 2, -1, -1):
        a, b = out[k], out[k + 1]
        if not (a.isalpha() and b.isalpha()):
            continue
        joined = (a + b).lower()
        last = joined == low[-1] and (k + 2 == len(out) or out[k + 2] == BREAK)
        first = joined == low[0] and (k == 0 or out[k - 1] == BREAK)
        if last or first:
            out[k:k + 2] = [a + b.lower()]
    return out


#: The most letters of a word only one reading has that the corpus may put
#: in (lone_word_fits), and how many times more often the corpus's clues
#: must print it beside each neighbour than the neighbours side by side.
LONE_WORD_LETTERS = 3
LONE_WORD_RATIO = 2


def lone_word_fits(word, before, after):
    """Whether a short known `word` one reading has and the others dropped
    belongs between `before` and `after`: the corpus's clues print each
    pair it makes LONE_WORD_RATIO times as often as the two neighbours
    together ("come to see": 350 and 1,757 against "come see"'s 0; not
    "in a car": 201 against 327). At a clue's end it is not decided."""
    if len(word) > LONE_WORD_LETTERS or not is_word(word) or not before or not after:
        return False
    _, pairs, _ = clue_lm()
    w, b, a = word.lower(), before.lower(), after.lower()
    return min(pairs.get(f"{b} {w}", 0), pairs.get(f"{w} {a}", 0)) > LONE_WORD_RATIO * pairs.get(f"{b} {a}", 0)


#: The fewest letters a word all readings print alike needs to stand
#: against a commoner slip (agree).
UNANIMOUS_LETTERS = 4


def surer(k1, n1, k2, n2, steps=2000):
    """P(p1 > p2) for two slip rates seen k1 times in n1 words and k2 in n2,
    each rate's posterior Beta(k + 1, n - k + 1) (a flat prior)."""
    def density(x, k, n):
        return math.exp(k * math.log(x) + (n - k) * math.log1p(-x)
                        + math.lgamma(n + 2) - math.lgamma(k + 1) - math.lgamma(n - k + 1)) / steps
    below = total = 0.0
    for i in range(steps):
        x = (i + 0.5) / steps
        total += density(x, k1, n1) * below
        below += density(x, k2, n2)
    return total


def dropped(short, long):
    """Whether `short` is `long` with letters dropped."""
    it = iter(long)
    return len(short) < len(long) and all(c in it for c in short)


def by_family(spellers, rates):
    """The spelling one engine's readers print and the other's do not, when
    the slip the other spelling would take is far likelier on the page:
    `rates` ({engine: {"seen", "wrong", "lost", "added"}}, family_rates)
    counts each engine's words misread, read with letters lost, and read
    with letters added. A spelling that is the other with letters dropped
    asks whether its engine lost them or the other engine added them (No
    103 14D, "tipper" against the printed "tripper"); any other pair asks
    which engine misreads more. Else None. `spellers` is {spelling: [engine
    of each reading printing it]}: two readings of one engine tied against
    two of another are one vote against one, which only the engines'
    measured slips can break."""
    if len(spellers) != 2:
        return None
    sides = {s: set(fs) for s, fs in spellers.items()}
    if any(len(fs) != 1 or None in fs for fs in sides.values()):
        return None
    (a, (ea,)), (b, (eb,)) = sides.items()
    if ea == eb or ea not in rates or eb not in rates:
        return None
    ra, rb = rates[ea], rates[eb]
    if min(ra["seen"], rb["seen"]) < FAMILY_WORDS:
        return None
    for (x, ex, rx), (y, ey, ry) in (((a, ea, ra), (b, eb, rb)), ((b, eb, rb), (a, ea, ra))):
        # x's engine slipped, or y's: is x's slip the far likelier?
        if dropped(x, y):
            slip_x, slip_y = "lost", "added"
        elif dropped(y, x):
            slip_x, slip_y = "added", "lost"
        else:
            slip_x = slip_y = "wrong"
        if surer(rx[slip_x], rx["seen"], ry[slip_y], ry["seen"]) >= FAMILY_SURE:
            return y
    return None


#: How many letters run_on() needs after the stop: two short words ("of
#: the") are in many clues.
RUN_ON_LETTERS = 10


def run_on(text, lid, laid):
    """`text` (light `lid`'s clue) cut before another clue it runs on into,
    that clue's number lost (No 103 9D "A pole was the sign of this house,
    legend test of fidelity,", the line "12. In legend wonderful test of
    fidelity." read without "12. In"): after a stop (".", "?", "!", or the
    "," or ";" Tesseract reads one as), words that print most of another
    laid clue (`laid`, {light: (text, ...)}) and it them, and no other
    figures (No 4's "St. George's Day, 1564." is no 5D "St. George's Day,
    1918." run on). Else `text` as it is."""
    for m in re.finditer(r"[.?!,;](?=\s+\S)", text or ""):
        tail = [w.lower() for w in marked(clean(text[m.end():])) if w not in MARKS]
        if len(tail) < 2 or sum(map(len, tail)) < RUN_ON_LETTERS:
            continue
        figures = re.findall(r"\d+", text[m.end():])
        for k, (t, _, _) in laid.items():
            if figures and re.findall(r"\d+", t or "") != figures:
                continue
            theirs = [w for w in marked(clean(t or "")) if w not in MARKS]
            low = [w.lower() for w in theirs]
            # Both ways: a tag many clues end on ("Two letters missing.") or
            # a few shared words ("wonder") are no whole clue run on.
            if k != lid and theirs and prints(align(tail, low), tail, theirs) \
                    and prints(align(low, tail), low, tail):
                return text[:m.start() + 1]
    return text


def elsewhere_run(end, side, clues):
    """Whether `end` (a reading's words past a clue's end, `side` "end", or
    before its start, "start") opens (or closes) on RUN_ON_LETTERS letters
    of words another laid clue (`clues`, each a list of its lower-case
    words) prints in a row: the reading lost the number between (No 4's
    22A "The name of an eagle." running on into 23A's "english of
    islands"), and no word of this clue is lost there."""
    words = [t for t in end if t not in MARKS]
    if side == "start":
        words = words[::-1]
    for n in range(2, len(words) + 1):
        run = words[:n] if side == "end" else words[:n][::-1]
        if sum(map(len, run)) < RUN_ON_LETTERS:
            continue
        return any(all(similar(a, b) >= PRINTS_SIMILAR for a, b in zip(run, c[i:i + n]))
                   for c in clues for i in range(len(c) - n + 1))
    return False


def agree(clue, others, keep_known=False, families=None, rates=None, clues=()):
    """(text or None, how) for one clue against the other readings' words
    and marks (`others`: one list per reading, or one list alone). Each word
    stands when another reading has it too; else it takes the spelling the
    other readings share, else the one spelling of the three that is a
    dictionary word. A mark no other reading has is dropped. A word no
    other reading has, two readings agreeing on a non-word the third does
    not, or several dictionary spellings, is a disagreement. With
    `keep_known` this reading's dictionary words are an engine's own and
    give way only to a word every other reading has (Trove's text, whose
    real words its readers' shared misreads must not outvote: "lie", not
    "he").
    `families` names the engine of this reading and of each other reading
    in turn, and `rates` each engine's slips on the page (family_rates): a
    tie the readings split by engine goes to the far better one (by_family).
    `clues` holds the other laid clues' lower-case words: a reading's end
    that runs on into one of them is no end lost (elsewhere_run)."""
    if others and isinstance(others[0], str):
        others = [others]
    if not tokens(clue):
        return clue, "no words"
    clue = parted(clue, others)
    mine, spans = [], []  # spans: each token's (start, text) in the clue
    k = 0
    for t in marked(clue, breaks=True):
        if t == BREAK:
            num = re.compile(r"\d+").search(clue, k)
            at, t = num.start(), num.group()
            # A number glued to a word's end ("know7") is a mark misread,
            # voted on as itself; one standing alone ("Map 10 E") is the
            # clue's text and pairs with the number other readings have.
            if not (at and clue[at - 1].isalpha()):
                mine.append(BREAK)
                spans.append((at, t))
                k = at + len(t)
                continue
        else:
            at = clue.find(t, k)
        mine.append(t)
        spans.append((at, t))
        k = at + len(t)
    while mine and mine[0] == BREAK:
        mine, spans = mine[1:], spans[1:]
    while mine and mine[-1] == BREAK:
        mine, spans = mine[:-1], spans[:-1]
    # A word with a speck against it ("i»" for "is") is no sure reading.
    specked = {i for i, (at, t) in enumerate(spans)
               if JUNK_MARK.match(clue[at + len(t):at + len(t) + 1] or " ")
               or (at and JUNK_MARK.match(clue[at - 1]))}
    low = [w.lower() for w in mine]
    seen = [{} for _ in mine]  # i -> {reading k: its word}
    extra = [{} for _ in range(len(mine) + 1)]  # gap before i -> {word: readings}
    leads, trails = [], []
    for k, theirs in enumerate(others):
        theirs = ends_joined(rejoin(unglued(theirs, low), low), low)
        at = 0
        pairs = align(low, [w.lower() for w in theirs])
        if not prints(pairs, low, theirs) or another_clue(pairs, low, theirs, clues):
            # This reading lost the clue: its words where align put it are
            # another clue's, no vote on this one's.
            leads.append(None)
            trails.append(None)
            continue
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
    # (a word lost, two run together, a comma missed) is put in; a word they
    # share that is no word goes in as the known word a letter from it
    # ("umsigned"), when one wins (mend).
    # A lone I is put in only when every reading has it: RapidOCR's two
    # recognisers share one detector and read the same speck as a "1".
    def put_in(w, g):
        if w in MARKS or is_word(w):
            return w
        return mend([w], low[g - 1] if g else None, low[g] if g < len(low) else None) if len(w) > 3 else None
    adds = {g: [p for w, ks in e.items() if len(ks) >= 2 and len(ks) * 2 > len(others)
                and (w != "i" or len(ks) == len(others)) and (p := put_in(w, g))]
            for g, e in enumerate(extra)}
    # Words other readings have between the clue's number and its first word,
    # or between its last word and its count, were lost from this reading:
    # put in when most readings have the same ones, else no reading wins.
    for side, got_ends in (("start", leads), ("end", trails)):
        got_ends = [None if e and elsewhere_run(e, side, clues) else e for e in got_ends]
        # A lone letter after the clue's last word is its count misread ("(s)").
        seen_ends = [e for e in (tuple(t for t in e if (side == "end" or t not in MARKS)
                                       and not (side == "end" and len(t) == 1 and t not in MARKS))
                                 for e in got_ends if e) if e]
        if len(seen_ends) < 2:
            continue
        top = max(seen_ends, key=seen_ends.count)
        worded = [e for e in seen_ends if any(t not in MARKS for t in e)]
        if seen_ends.count(top) < 2 and len(worded) * 2 < len(others):
            # Specks a few of many readings each see apart (a second copy's
            # readings vote too): no end is lost unless half the readings
            # see words there (a mark alone is none: "privilege," against
            # "privilege."), or two see the same ones.
            continue
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
        if w == BREAK:
            # A number standing in the clue is a word misread when more
            # other readings have a word it looks like there than a number.
            num = spans[i][1]
            like = [v.lower() for v in got.values() if digit_word(num, v) and is_word(v) and v.lower() != "i"]
            if like and len(like) > sum(v == BREAK for v in seen[i].values()):
                before = next((low[k] for k in range(i - 1, -1, -1) if low[k] not in MARKS + BREAK), None)
                after = next((low[k] for k in range(i + 1, len(low)) if low[k] not in MARKS + BREAK), None)
                fixes[i] = max(sorted(set(like)), key=lambda v: (like.count(v), fit(v, before, after)))
                how = "settled by the readings"
            elif (len(num) == 1 and clue[spans[i][0] + 1:spans[i][0] + 2].isalpha()
                  and len(got) < len(others) and BREAK not in seen[i].values()
                  and all(v.lower() in ("i", "l") for v in got.values())):
                # A figure run onto a word's start ("1uncle"), where another
                # reading sees nothing and none a number, is a speck: a
                # printed "I" stands apart from the next word.
                drop.add(i)
            continue
        if w.isdigit():
            marks = [v for v in seen[i].values() if v in MARKS]
            top = max(marks, key=marks.count) if marks else None
            if top and marks.count(top) * 2 > len(others):
                fixes[i] = top
                how = "settled by the readings"
            continue
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
        before = next((low[k] for k in range(i - 1, -1, -1) if low[k] not in MARKS + BREAK), None)
        after = next((low[k] for k in range(i + 1, len(low)) if low[k] not in MARKS + BREAK), None)
        if not got and len(a) > 3 and not known(a) and not (i and w[0].isupper()) and mend([a], before, after):
            # A word only this reading has, a letter from a known one.
            fix = mend([a], before, after)
            fixes[i] = fix.capitalize() if w[:1].isupper() else fix
            continue
        if not got and len(a) == 1 and a not in "ai":
            # A lone letter no other reading has is a speck.
            drop.add(i)
            continue
        if not got and len(a) <= 2 and is_word(a) and any(
                seen[i].get(k) == BREAK or (k not in seen[i] and k in extra[i].get(BREAK, set()) | extra[i + 1].get(BREAK, set()))
                for k in range(len(others))):
            # A short word another reading reads as a figure in its place
            # (No 8's worn old-style "a" read "2") is seen by that reading.
            continue
        if not got and lone_word_fits(a, before, after):
            # A short word only this reading saw ("come to see", the others
            # read "come see"): the corpus's clues decide.
            how = "settled by the corpus"
            continue
        if not got:
            return None, f"no other reading has {w!r}"
        if (i == 0 and len(w) == 1 and len(mine) > 1 and mine[1][:1].isupper()
                and len(got) * 2 < len(others)):
            drop.add(i)
            continue
        votes = {a: 1}
        forms = {a: [w]}
        for v in got.values():
            votes[v.lower()] = votes.get(v.lower(), 0) + 1
            forms.setdefault(v.lower(), []).append(v)
        # The clue's first word takes a capital when half its readings print
        # one (a reading that lost the capital, "involve", outvotes none);
        # else, and inside the clue, the first reading's case stands (a
        # reader's "In" for "in" is as common as a capital lost).
        spelt = {s: fs[0][:1].upper() + fs[0][1:]
                 if i == 0 and 2 * sum(f[:1].isupper() for f in fs) >= len(fs) else fs[0]
                 for s, fs in forms.items()}
        plainer = [v for v in got.values() if v.lower() == a and not CAPS_IN_WORD.search(v)]
        if CAPS_IN_WORD.search(w) and plainer:
            # A capital inside the word that another reader did not see ("bacK").
            spelt[a] = plainer[0]
            how = "settled by the readings"
        elif i and w[0].isupper() and any(v[0].islower() for v in got.values() if v.lower() == a):
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
                common = sorted(fits, key=lambda c: rank(c) or 10 ** 9)
                printed = [c for c in fits if any(misread(o, c) for o in fits)]
                if (rank(common[0]) or 10 ** 9) * SLIP_RATIO < (rank(common[1]) or 10 ** 9):
                    # Else the far commoner word: "lower", not "ower".
                    words_ = common
                elif len(printed) == 1:
                    # Else the spelling another is a known misreading of:
                    # "eh", which worn type prints as "ch".
                    words_ = printed + [c for c in fits if c != printed[0]]
                elif fit(fits[0], before, after) - fit(fits[1], before, after) < FIT_MARGIN:
                    # Else the known word every reading's slips point to.
                    settled = consensus(read, before, after)
                    if not settled and families and rates:
                        # Else the spelling of the engine that misreads far
                        # less on this page, when the engines split the tie.
                        spellers = {}
                        for k, v in [(-1, a)] + list(got.items()):
                            spellers.setdefault(v.lower(), []).append(families[k + 1])
                        settled = by_family(spellers, rates)
                        how = "settled by the engines" if settled else how
                    if not settled:
                        return None, f"readings differ: {w} / {' / '.join(got.values())}"
                    words_ = [settled]
                    spelt.setdefault(settled, settled.capitalize() if w[:1].isupper() else settled)
                else:
                    words_ = fits
        if len(words_) > 1 and votes[words_[0]] == votes[words_[1]] and (
                (settled := consensus(read, before, after)) and settled != words_[0]
                and (rank(settled) or 10 ** 9) * SLIP_RATIO < (rank(words_[0]) or 10 ** 9)):
            # A tie in votes, settled on a rare word, goes to the far commoner
            # known word every reading's slips point to ("that's", not the
            # "thar's" one reader saw).
            words_ = [settled]
            spelt.setdefault(settled, settled.capitalize() if w[:1].isupper() else settled)
        if words_ and keep_known and known(a) and i not in specked and words_[0] != a and not (
                len(got) == len(others) and all(v.lower() == words_[0] for v in got.values())):
            pick = a
        elif words_:
            pick = words_[0]
            if pick != a or votes[a] == 1:
                how = "settled by the dictionary"
        elif len(votes) == 1 and votes[a] >= 3 and len(a) > 2 and i not in specked:
            # Three readings or more, every one, print the same non-word:
            # the print's own (No 4 15D's Elizabethan "busie", not "susie").
            pick = a
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
        elif len(a) > 2 and votes[a] == 1 and not known(a) and len(got) >= 2 and (
                max(votes.values()) * 2 > len(others) and max(votes, key=votes.get) != a
                and similar(a, max(votes, key=votes.get)) >= 0.7):
            # Most other readings agree on a spelling like this one's, which
            # no dictionary knows: "Jenkyns" where this reading has "Jcnkyns".
            pick = max(votes, key=votes.get)
            how = "settled by the readings"
        elif settled := consensus(read, before, after):
            # No spelling wins the vote: the known word every reading's
            # slips point to ("another" for "anoibcr / anotacr / auotber").
            pick = settled
            spelt.setdefault(pick, pick.capitalize() if w[:1].isupper() else pick)
            how = "settled by the lexicon"
        elif max(votes.values()) > 1 and votes[a] == 1 and len(a) > 3 and w[0].islower():
            return None, f"two readings agree on a non-word: {w} / {' / '.join(got.values())}"
        elif len(a) > 3 and votes[a] > 1 and i not in specked and (
                len(votes) == 1 or (votes[a] * 2 > sum(votes.values()) and closed_compound(a)
                                    and not any(map(known, set(votes) - {a})))):
            # Every reading that sees a word here spells it alike, letter
            # for letter, or most do, it is two known words closed up, and
            # the rest spell no word ("spongecake" against "spongecalke"),
            # and no known word mends it: the print's own
            # spelling (No 17's misprinted "elecampeae", "anatomatical"),
            # filed as printed: printed_alike() records it as the clue's
            # asPrinted, which suspect() then takes.
            pick = a
            how = "as printed"
        elif len(votes) == 1 and votes[a] > 1 and not known(a) and (pick := worn(a)):
            # Every reading prints the same non-word, a worn letter from a
            # known word far commoner than any other it could be (No 3's
            # "initials cf a telegraph").
            spelt[pick] = pick.capitalize() if w[:1].isupper() else pick
            how = "settled by the type's wear"
        else:
            return None, (f"both read {w!r}, not a word" if votes[a] > 1
                          else f"readings differ: {w} / {' / '.join(got.values())}")
        # A dictionary word at least three readings print alike, with none
        # dissenting, stands: no slip or corpus fit outvotes them (No 17's
        # "starling", not "starting"). Not a short one: readers share the
        # slip of a two-letter word ("ot" for "of", "ou" for "on").
        unanimous = (pick == a and len(a) >= UNANIMOUS_LETTERS and is_word(a) and len(got) >= 2
                     and all(v.lower() == a for v in got.values()))
        slip = None if (keep_known and pick == a) or unanimous else common_slip(pick)
        if slip:
            # Every reader can share the slip: the commoner spelling stands
            # unless the read one fits its neighbours in the corpus's clues
            # far better.
            gap = fit(slip, before, after) - fit(pick, before, after)
            # A word most readings and at least three share gives way only to
            # one that fits better.
            shared = votes.get(pick, 0)
            if gap > (FIT_MARGIN if shared >= 3 and shared * 2 > len(read) else -FIT_MARGIN):
                spelt[slip] = slip.capitalize() if spelt[pick][:1].isupper() else slip
                pick = slip
                how = "settled by the corpus"
        alt = None if (keep_known and pick == a) or unanimous else likelier(pick, before, after, read)
        if alt and not (i and spelt[pick][:1].isupper()) and swappable(clue, spans[i][0], w):
            spelt[alt] = alt.capitalize() if spelt[pick][:1].isupper() else alt
            pick = alt
            how = "settled by the corpus"
        if spelt[pick] != w:
            fixes[i] = spelt[pick]
    adds = {g: ws for g, ws in adds.items() if len(ws) == 1}
    if not fixes and not drop and not adds and not (others and JUNK_MARK.search(clue)):
        return clue, how
    # Specks between the words go: the other readings saw nothing there.
    speckless = (lambda gap: JUNK_MARK.sub("", gap)) if others else (lambda gap: gap)
    text, k, out = clue, 0, ""
    for i, (at, old) in enumerate(spans):
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
        gap = speckless(text[k:at])
        if i == 1 and 0 in drop:
            # A misread clue number dropped takes its stop ("A. Frontier", No 3's 52D).
            gap = gap.lstrip(".,;: ")
        if add and add[0] in MARKS and gap.strip() == ".":
            # A speck read as a full stop where the other readings have a mark.
            gap = " " if gap[-1:].isspace() else ""
        out += gap + (add[0] + " " if add else "") + new
        k = at + len(old)
    out += (" " + adds[len(mine)][0] if adds.get(len(mine)) else "") + speckless(text[k:])
    if adds and how == "agree":
        how = "settled by the readings"
    if drop and how == "agree":
        how = "settled by the readings"
    return re.sub(r"\s+([" + MARKS + "])", r"\1", re.sub(r"  +", " ", out)).strip(), how


def is_word_only_capital(word, seen):
    """Whether the other readings print `word` with its capital too."""
    return bool(seen) and all(v[0].isupper() for v in seen.values() if v.lower() == word.lower())


FULL_WIDTH = {c: c - 0xfee0 for c in range(0xff01, 0xff5f)}
LIGATURES = str.maketrans({"\u00e6": "ae", "\u00c6": "Ae", "\u0153": "oe", "\u0152": "Oe"})
#: A ligature as readers without it print it: its two letters, or the last.
LIGATURE_E = str.maketrans({"\u00e6": "e", "\u00c6": "E", "\u0153": "e", "\u0152": "E"})


def ligatured(text, readings):
    """`text` (a clue voted on folded words, clean()) with each word a
    reading prints with a ligature put back as printed: the filed word that
    is that word folded to two letters or to its "e" ("mediæval", which No
    9's other readers print "medieval"). A reader does not invent a
    ligature it never saw."""
    for raw in readings:
        for w in set(re.findall(r"[A-Za-z\u00e6\u00c6\u0153\u0152]+", raw or "")):
            if w == w.translate(LIGATURES) or len(w) < 3:
                continue
            for folded in {w.translate(LIGATURES), w.translate(LIGATURE_E)}:
                text = re.sub(rf"\b{folded}\b", lambda m, w=w: (w[0].upper() if m.group()[0].isupper() else w[0].lower()) + w[1:],
                              text, flags=re.IGNORECASE)
    return text
#: Abbreviations a clue prints with a stop before a lower-case word (the
#: 1930s Listener's "Anag. of", "20 rev."), each a lookbehind of its own
#: width.
ABBREVIATED = ("[Aa]nag", "[Rr]ev", "[Aa]bbr", "[Aa]bbrev", "[Oo]bs", "[Ee]sp", "[Cc]f", "[Vv]iz", "[Ii]nit")
#: A lone underscore touching a word or a mark: a speck our readers read as
#: one ("love,_emperor", "during_a", "fine_"). A run of them is a printed
#: blank ("Freedom and _____"), and so may a lone one between spaces be ("And
#: with no _ but a cry").
SPECK_UNDERSCORE = re.compile(r"(?<=[^_\s])_(?!_)|(?<!_)_(?=[^_\s])")


def unspecked(text):
    """`text` without SPECK_UNDERSCORE: a space where it parts two words, else
    nothing."""
    def gone(m):
        s, a, b = m.string, m.start(), m.end()
        return " " if 0 < a and b < len(s) and not s[a - 1].isspace() and not s[b].isspace() else ""
    return re.sub(r"  +", " ", SPECK_UNDERSCORE.sub(gone, text)).strip()


#: The words clues hyphen to a lone "A" or "to": the rest is a speck.
HYPHENED_A_TO = ("day", "morrow", "night", "do", "bomb", "level", "levels", "list", "lister", "road", "side",
                 "team", "frame", "line", "plus")


def clean(text):
    """A reading without OCR's specks: a not-sign read for the hyphen that
    breaks a word over a line end is the join, an asterisk or bullet beside
    a word is no part of it, and a comma or exclamation mark misread as a
    full stop or an I is put back."""
    text = re.sub(r"\s*[*•|]+(?=\s|$)", "", re.sub(r"(?<=[a-z])¬\s*(?=[a-z])", "", text))
    # An opening quote glued to the word before it opens the next word
    # ("this\u2018enamelled'"): kept as the straight quote below, it would close.
    text = re.sub(r"(?<=[a-z]{2})[\u2018\u201c](?=[A-Za-z])", lambda m: " " + m.group(0), text)
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    # A ligature is its two letters, as readers that lack it read it ("medi\u00e6val").
    text = text.translate(LIGATURES)
    text = unspecked(text)
    # A recogniser's full-width mark is the ASCII one ("\uff1f" for "?").
    text = text.translate(FULL_WIDTH)
    # A pound sign in a word is an f the print's worn type turned ("o£").
    text = re.sub(r"\b[A-Za-z]*£[A-Za-z£]*",
                  lambda m: m.group(0).replace("£", "f") if is_word(m.group(0).replace("£", "f").lower())
                  else m.group(0), text)
    # A backslash inside a word is a letter the scan broke ("sal\\ age").
    text = re.sub(r"(?<=[a-z])\\\s?(?=[a-z])", "", text)
    # A clue's sentence never stops before a lower-case word: a full stop
    # there is a comma the print's low ink lost the tail of.
    # An abbreviation's stop stands: "Anag. of", "rev. and".
    text = re.sub(r"(?<=[a-z]{2})" + "".join(rf"(?<!\b{a})" for a in ABBREVIATED) + r"\.(?=\s+[a-z])", ",", text)
    # A stop read twice after a word ends no clue: "1857..", not an ellipsis.
    text = re.sub(r"(?<=\w)\.\.(?!\.)", ".", text)
    # A speck read as a hyphen after a lone "A" or "to" ("A-town", "to-part");
    # HYPHENED_A_TO and "a-" before an -ing word ("a-hunting") stand.
    text = re.sub(r"\b([Aa]|[Tt]o)-(?!(?:" + "|".join(HYPHENED_A_TO) + r"|[a-z]+ing)\b)(?=[a-z]{2,}\b)",
                  r"\1 ", text)
    # A one read as l or I before another digit ("l9th-century").
    text = re.sub(r"\b[lI](?=\d)", "1", text)
    # The space before a bracket opening on a word lost ("slang(from").
    text = re.sub(r"(?<=[a-z]{2})\((?=[a-z]{3})", " (", text)
    # The space after a question or exclamation mark lost ("Worried?Pulse").
    text = re.sub(r"(?<=[a-z])([?!])(?=[A-Z][a-z])", r"\1 ", text)
    # A dash between words is the corpus's spaced em dash, however the scan
    # set it ("time—a", "play--change", "now -- then").
    text = re.sub(r"(?<=[a-z])[ \t]*(?:—|--)[ \t]*(?=[A-Za-z])", " — ", text)
    # So is any dash after a colon ("Charade:—components", read ": -components").
    text = re.sub(r"(?<=[a-z]:)[ \t]*(?:—|--?|–)[ \t]*(?=[A-Za-z])", " — ", text)
    # The space after a comma, semicolon or colon between two words lost
    # ("rum,as", "usage:acceptable", "knot,I'm", "a T:an"), or before a quotation ("say,'Give").
    text = re.sub(r"(?:(?<=[a-z]{2})|(?<=\b[A-Z]))([,;:])(?=[a-z]{2}|[A-Z][a-z']|['\u2018\"\u201c][A-Z])", r"\1 ", text)
    # An exclamation mark read as a capital I or a one, last before the count.
    text = re.sub(r"(?<=[a-z]) [I1l](?=\s*(?:\(\s*\d|$))", "!", text)
    text = re.sub(r"(?<![\d(])\b1(?=[a-z]*\b)(?![a-z]*\s+(?:and|or|&)\s+\d)([a-z]*)", one_for_i, text)
    return rejoined(re.sub(r"\b([A-Za-z]+)-\s+([a-z]+)\b", line_end_hyphen, text))


#: A word the lexicon ranks rarer than this, said again as the end of the
#: word before it, is that word's line-end half read twice.
TAIL_RARE = 20000


def rejoined(text):
    """`text` with a word a reading broke mended: two non-words that spell a
    word ("Engl ishman"); a rare word that ends the word before it and the
    corpus never prints after it, its line-end half read twice
    ("development ment"); an apostrophe after a lone capital, where the
    word without it is one and the corpus never prints it with it
    ("T'his"; "O'er" and "I'm" stand); and the space after a short
    abbreviation's stop before a name ("St.George's")."""
    uni, pairs, _ = clue_lm()

    def join(m):
        a, b = m.group(1), m.group(2)
        return a + b if not known(a) and not known(b) and known(a + b) else m.group()

    def twice(m):
        a, b = m.group(1), m.group(2)
        rare = (rank(b) or UNRANKED) > TAIL_RARE
        if len(a) >= len(b) + 3 and a.lower().endswith(b.lower()) and rare and not pairs.get(f"{a} {b}".lower()):
            return a
        return m.group()

    def capital(m):
        a, b = m.group(1), m.group(2)
        if not uni.get(f"{a}'{b}".lower()) and uni.get((a + b).lower(), 0) >= CLUE_WORD_FLOOR:
            return a + b
        return m.group()

    text = re.sub(r"\b([A-Za-z]{2,})\s+([a-z]{2,})\b", join, text)
    text = re.sub(r"\b([A-Za-z]{5,}) ([a-z]{3,})\b", twice, text)
    text = re.sub(r"(?<![\w'])([A-Z])'([a-z]{2,})\b", capital, text)
    return re.sub(r"\b([A-Z][a-z]{0,2})\.(?=[A-Z][a-z]{2})", r"\1. ", text)


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


def unhyphen(text):
    """A reading returned unbroken (the VLM's: it runs a clue's printed lines
    together) with each hyphen that broke a word over a line end joined
    ("pre-decessor", "ob-vious"). "A-B" is "AB" when AB is a word and the
    corpus's clues never print it hyphenated (tools/data/clue_compounds.tsv).
    A form they do print ("back-street", "sea-bird", "co-operate") stands as
    read: the scans' older print hyphenates compounds today's clues close.
    Not for a reading that keeps the print's lines: there a hyphen inside a
    line is the print's own ("counter-charges"), and clean() joins the line
    ends."""
    def join(m):
        a, b = m.group(1), m.group(2)
        return a + b if is_word(a + b) and not compound(a, b)[0] else m.group(0)
    return re.sub(r"(?<![\w-])([A-Za-z]+)-([a-z]+)(?![\w-])", join, text)


HEADING = re.compile(r"^\W*(?:clues\s+)?(?:across|down)\W*$", re.IGNORECASE | re.MULTILINE)


def numbers_joined(clue, streams):
    """The clue with a cross-reference read apart ("with 1 5's") made one
    number where most other readings (`streams`, raw texts or {light: text})
    print it whole after the same word ("with 15's"); "5 3 3 on the watch"
    stands where they print it apart."""
    texts = [s if isinstance(s, str) else " ".join(v for v in s.values() if v) for s in streams]

    def one(m):
        word, number = m[1], m[2] + m[3]
        whole = re.compile(rf"(?<!\w){re.escape(word)}\s+{number}(?!\d)")
        return f"{word} {number}" if texts and sum(bool(whole.search(t)) for t in texts) * 2 > len(texts) else m[0]
    return re.sub(r"(?<!\S)([A-Za-z]+,?) (\d) (\d)(?![\d(])", one, clue)


def join_split(clue, others):
    """The clue with two of its words run together where most other readings
    have them as one lexicon word: a word the print broke over a line end
    whose hyphen this reading lost ("par simony" for "parsimony")."""
    if not others:
        return clue
    held = [{w.lower() for w in t} for t in others]
    k = 0
    while True:
        m = re.compile(r"\b([A-Za-z]+) ([a-z]+)\b").search(clue, k)
        if not m:
            return clue
        whole = (m.group(1) + m.group(2)).lower()
        if sum(whole in h for h in held) * 2 > len(others) and is_word(whole):
            clue = clue[:m.start()] + m.group(1) + m.group(2) + clue[m.end():]
            k = m.start()
        else:
            k = m.start(2)


def cut_at_count(text, enum):
    """A clue's text cut at its own count (`enum`) inside it: what follows
    is the next clue's specks or start, or the page's text, run on. The
    count's bracket may read as a full stop or be lost ("spotty (6. The
    solution", "outs (5 _ Concise")."""
    for m in re.finditer(r"\s*\((\d{1,2}(?:\s*[,\-.]\s*\d{1,2})*)(?:\)|\.|(?=\s))\W*\S", text or ""):
        if enum and re.sub(r"\D+", ",", m.group(1)) == re.sub(r"\D+", ",", enum):
            return text[:m.start()].rstrip()
    return text


#: A count: "(15)", "(5,4)", "(3-2)".
COUNT_IN = r"\(\d{1,2}(?:\s*[,\-.]\s*\d{1,2})*\)"
#: A clue number opening a capitalised clue, not a cross-reference ("1
#: Down", "No. 1 Court", "e.g. 10 Downing Street").
NEXT_CLUE = r"\s+\d{1,2}\.?\s+(?!(?:Down|Across|Ac|Dn)\b)[A-Z\"'][a-z]"
#: That number after a count or a question or exclamation mark ("backed
#: (15) 2 Master", "floor? 2 Seek"), or two counts in one text.
RUN_TOGETHER = re.compile(rf"(?:{COUNT_IN}|[?!])\W*{NEXT_CLUE}|{COUNT_IN}.*{COUNT_IN}")


def merged(text):
    """Why a voted clue `text` is two clues run together, or None: a clue
    number opening a capitalised clue after a count or a question or
    exclamation mark ("Where everybody goes in to sweep around the floor? 2
    Seek fresh increases"), or two counts."""
    return "two clues run together" if RUN_TOGETHER.search(text or "") else None


#: A clue number opening a capitalised clue anywhere in a filed clue's
#: text: another clue, or the page's text, read into this one ("Poles 22
#: Affected by", "Saturday 26 The point is"). A cross-reference names its
#: list ("9 Across", "17 Down") and a date its month ("5 November").
NUMBERED_IN = re.compile(
    r"(?:^|\s)\d{1,2}\.?\s+(?!(?:Down|Across|Ac|Dn|Up|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[a-z]*\b)(?:[A-Z][a-z]|[\"'\u201c\u2018][A-Z])")


#: The page's own words read into a clue: a pointer to another page's
#: puzzle ("Concise crossword, page 22"), a notice of a solution ("The
#: solution to the Collins Competition", "Prize Puzzle No 18,178"), or a
#: count with text after it ("(41. Times Two", "(5 _ Concise"), not an
#: aside the clue closes ("(2 Hen. IV)").
PAGE_TEXT = re.compile(r"\bcr\w{4,8}d\W{1,3}(?:page|p)\W{0,2}\d"
                       r"|\bpuzzle\s+no\W{0,2}\s*\d"
                       r"|\bsolution\s+(?:to|of)\s+(?:\S+\s+){0,4}(?:puzzle|competition)\b"
                       r"|(?-i:\(\s*\d{1,2}(?:[,.\-]\s?\d{1,2})*[).]?\s+(?:_|[A-Z])(?![^()]*\)))", re.IGNORECASE)


#: A list's heading read into a clue: "ACROSS" or "DOWN" in capitals,
#: which no clue prints, or either opening the text before the first
#: clue's number ("Down i Beginning", "ACROSS 1 Fish").
HEADING_IN = re.compile(r"(?<![\w'])(?:ACROSS|DOWN)(?![\w'])"
                        r"|^\W*(?i:across|down)\W*\s+(?:\d{1,2}|[iIl|!])\W?\s+(?=[A-Z\"'])")

#: The brackets a clue pairs.
PAIRS = {")": "(", "]": "["}


def unpaired(text):
    """The index of the first bracket `text` never closes or never opened
    ("is (this", "for ) record", "[9)"), or None."""
    stack = []
    for i, c in enumerate(text or ""):
        if c in "([":
            stack.append((c, i))
        elif c in PAIRS:
            if not stack or stack[-1][0] != PAIRS[c]:
                return i
            stack.pop()
    return stack[0][1] if stack else None


def bled(text, printed=()):
    """Why a clue OCR read holds text that is not its own, or None: a clue
    number opening a capitalised clue (NUMBERED_IN), another clue run in,
    the page's own words (PAGE_TEXT), a list's heading (HEADING_IN), a
    bracket it never closes or opened (unpaired: a speck, or a count torn
    off) unless `printed` (the clue's asPrinted) keeps it, or a square
    bracket or brace (a misread count or speck). No OCR filer writes such a
    clue (scan_queue.file_puzzle)."""
    text = text or ""
    m = NUMBERED_IN.search(text)
    if m:
        return f"holds a clue number and text: {text[m.start():m.end() + 12].strip()!r}"
    m = PAGE_TEXT.search(text)
    if m:
        return f"holds the page's text: {text[max(0, m.start() - 8):m.end() + 8].strip()!r}"
    m = HEADING_IN.search(text)
    if m:
        return f"holds a list's heading: {text[max(0, m.start() - 12):m.end() + 12].strip()!r}"
    k = unpaired(text)
    if k is not None and holding(text, k) not in printed:
        return f"holds a bracket it never pairs: {text[max(0, k - 12):k + 12].strip()!r}"
    m = re.search(r"[\[\]{}]", text)
    if m:
        return f"holds a square bracket or brace, which no clue prints: {text[max(0, m.start() - 12):m.end() + 12].strip()!r}"
    return None


def fault(text, enum, cells, printed=()):
    """Why a clue OCR read is not fit to file, or None: `text` is the word
    None (a lost text printed), holds text not its own (bled()), or its
    count `enum`, or a count left on its words, does not fill its `cells`
    (the light's, or its linked lights' together)."""
    text = text or ""
    if text.strip() == "None":
        return "the text is the word None: a lost text printed"
    why = bled(text, printed)
    if why:
        return why
    if enum and cells and sum(int(n) for n in re.findall(r"\d+", enum)) != cells:
        return f"its count ({enum}) does not fill its {cells} squares"
    # A count left on the words with marks after it, read off the same print
    # as `enum` but not the same: "(7.8) ' -" over a voted "(7,6)".
    clue = {"text": text, **({"enumeration": enum} if enum else {})}
    if cells and (printed := enumeration.disagrees(clue, {cells})):
        return f"its words end in a count ({printed}) that does not fill its {cells} squares"
    return None


def trimmed(text, lid, voted=True):
    """A filed clue's text without what the page put around it:
      - other text run in ahead of the clue's own number, when that text
        holds a number or a count ("... Puzzle No 18,178 will appear next
        Saturday 26 The point is ..." in 26 across);
      - its list's heading read onto 1 across or 1 down ("Down Poet's way");
      - a lone small "i" between two words ("system i uniting"), a speck:
        the pronoun is "I", and the newspaper i is quoted or ends a clue;
      - a line end's hyphen with specks between the halves ("buy- 4 ing",
        "like- .wise"), joined as clean() joins a bare one;
      - a list's heading in capitals anywhere ("on the DOWN board");
      - a last token with no word in it and a bracket the clue never opened
        ("0,6)", "S).", "writer 1 7).") or a digit among symbols ("&%S4),");
      - a count torn open at its end ("hair-dresser (6", "(5.41.", "( 8 .")
        and a speck read as a bracket before its first word (") The man").
    The lone i goes only from a `voted` text: before the vote, the other
    readings may have the word it is a remnant of ("raised i sharp" for
    "raised in sharp")."""
    if not text:
        return text
    own = lid.split("-")[0]
    runs = [m for m in re.finditer(rf"\s{own}\.?\s+(?=[A-Z\"'])", text)]
    if runs and re.search(r"\d", text[:runs[-1].start()]):
        text = text[runs[-1].end():]
    if voted:
        text = re.sub(r"(?<=[A-Za-z,;:] )i (?=[A-Za-z])", "", text)
    if own == "1":
        word = lid.split("-")[1]
        text = re.sub(rf"^(?:{word}|{word.capitalize()}|{word.upper()})(?:\W+|\W*\s+[1iIl|!]\W?\s+)(?=[A-Z][a-z])",
                      "", text)
    text = re.sub(r"\s*(?<![\w'])(?:ACROSS|DOWN)(?![\w'])\W*?(?=\s|$)", "", text).strip()
    text = re.sub(r"\b([A-Za-z]+)-\s+(?=[^\w\s]|\d)[^\w\s]*\d?[^\w\s]*\s*([a-z]+)\b", line_end_hyphen, text)
    while "(" not in text or ((k := unpaired(text)) is not None and text[k] in ")]"):
        head, _, last = text.rpartition(" ")
        if not head or re.search(r"[A-Za-z]{2}", last) or not (
                ")" in last or (re.search(r"\d", last) and re.search(r"[&#@]", last))):
            break
        text = head.rstrip()
        if re.fullmatch(r"[1l]", text.rpartition(" ")[2]) and re.search(r"\d", last):
            text = text.rpartition(" ")[0].rstrip()  # "currency 1 7).": the count's "(" read as 1
    text = re.sub(r"\s*\[\s*\d{1,2}(?:\s*[,\-]\s*\d{1,2})*\s*[\])][^\w(\[]*$", "", text)
    k = unpaired(text)
    if k is not None and text[k] in "([" and re.fullmatch(r"[(\[]\s*[\dSIl$]{0,2}(?:\s*[,.\-]\s*[\dSIl]{0,2})*[^\w(\[]*",
                                                         text[k:]):
        text = text[:k].rstrip()
    k = unpaired(text)
    if k is not None and not text[:k].strip():
        text = text[k + 1:].lstrip()
    return text


def opening_printed(text, own, streams):
    """The first word another reading prints straight after the clue's
    number, when its first two words read as the clue's do, whatever their
    case and slips ("13 under twenty-one", "5 3 3 on the watch", "24 Fish
    enjoyed" for "fish enjqycd"): an opening the print has, and no line lost
    before it; else None."""
    head = text.replace("\u2019", "'").split()[:2]
    if not head:
        return None
    mine = " ".join(head).lower()
    starts = []
    for s in streams:
        if isinstance(s, str):
            starts += [m.group(1) for m in re.finditer(rf"(?m)^\W{{0,2}}{own}\W?\s+(.*)$", s)]
        else:
            starts += [s.get(f"{own}-{way}") or "" for way in ("across", "down")]
    for line in starts:
        theirs = line.replace("\u2019", "'").split()[:len(head)]
        if len(theirs) == len(head) and similar(mine, " ".join(theirs).lower()) >= OPENING_SIMILAR:
            return theirs[0]
    return None


#: How like the clue's first two words another reading's two after the
#: clue's number must read for the print to have them there: "fish enjqycd"
#: against "Fish enjoyed" is 0.83, "in judgment" against "When Cleopatra" 0.4.
OPENING_SIMILAR = 0.75


#: How far past a clue's own number numbered_at() reads a reading: the
#: clue's length again plus this many characters, room for words the
#: reading has that the clue lost and the next clue's number.
NUMBERED_SLACK = 80


def numbered_at(stream, own, text):
    """`stream` (a reading's whole text) as marked() tokens, cut to the
    stretches that open on the number `own`, each as long as `text` (the
    clue) twice plus NUMBERED_SLACK characters: a short clue ("Wonderful
    25.") put to a whole page aligns with whatever other clue holds its
    words ("a wonderful 25"), whose opening then reads as words this clue
    lost. A reading whose stretches do not print the clue (its number
    misread, or the number another clue's) is put whole."""
    whole = marked(stream, breaks=True)
    span = len(text or "") * 2 + NUMBERED_SLACK
    cuts = [stream[m.start():m.start() + span]
            for m in re.finditer(rf"(?<![\w,.]){own}(?!\d)(?!\s*(?:across|down|ac|dn)\b)", stream, re.IGNORECASE)]
    if not cuts:
        return whole
    near = marked("\n".join(cuts), breaks=True)
    low = [w.lower() for w in marked(text or "", breaks=True)]
    return near if prints(align(low, [w.lower() for w in near]), low, near) else whole


def family_rates(out, heard, whose, mine, order):
    """{engine: {"seen", "wrong", "lost", "added"}}: how many of the page's
    settled words each engine's readings were put to, misread, read with
    letters lost, and read with letters added (by_family). A settled word is one a filed clue (`out`,
    {light: (text, ...)}) holds that readings of two engines or more print
    alike; each reading put to it (`heard`, {light: [its tokens, or None]}:
    the laid clue's, from reader `whose[light]` or `mine`, then one per
    reader of `order`) misreads it when its word there differs. A laid clue
    whose reader is unknown is left out, so no reading counts twice."""
    rates = {}
    for lid, (text, _, _) in out.items():
        if not text or lid not in heard:
            continue
        laid_by = whose.get(lid, mine if isinstance(mine, str) else None)
        engines = [family(laid_by)] + [family(n) if n != laid_by else None for n in order]
        low = [w.lower() for w in marked(text, breaks=True)]
        at = [{} for _ in low]  # word i -> {reading: its word}
        for r, theirs in enumerate(heard[lid]):
            if not theirs or not engines[r]:
                continue
            pairs = align(low, [w.lower() for w in theirs])
            if not prints(pairs, low, theirs):
                continue
            for i, j in pairs:
                if i is not None and j is not None:
                    at[i][r] = theirs[j].lower()
        for i, w in enumerate(low):
            if not w.isalpha():
                continue
            if len({engines[r] for r, v in at[i].items() if v == w}) < 2:
                continue
            for r, v in at[i].items():
                if not v.isalpha():
                    # A mark or a quote's "'s" set against a word: a token
                    # parted otherwise, no letter misread.
                    continue
                got = rates.setdefault(engines[r], dict.fromkeys(("seen", "wrong", "lost", "added"), 0))
                got["seen"] += 1
                got["wrong"] += v != w
                got["lost"] += dropped(v, w)
                got["added"] += dropped(w, v)
    return rates


def reconcile(laid, streams, lengths=None, keep_known=False, uncounted=False, names=None, mine=None,
              rates=None):
    """The laid clues with each clue's text put to every reading; returns
    (laid, {light: why}) naming each clue filed blank. `streams` holds each
    other reading's text, or {light: that reading's text} where the lights
    were laid from different readings; one text or dict alone is one reading.
    `lengths` ({light: cells}, from the grid) gives a clue whose count was
    lost its light's length as the count. `uncounted`: the lists print no
    counts (the 1930s Listener's), so a clue without one is read whole.
    `names` names the reader of each stream and `mine` ({light: reader}, or
    one reader for all) the reading each laid clue is from: a clue a tie of engines held is voted again with each
    engine's slips on the other clues (family_rates, agree)."""
    if isinstance(streams, (str, dict)):
        streams = [streams]
    names = list(names) if names else [None] * len(streams)
    whose = mine if isinstance(mine, dict) else {}
    # A list's heading bounds the clues either side like a number: "DOWN"
    # over "1 Unusual ..." is no word lost from 1 down.
    whole = [clean(HEADING.sub("0", s)) for s in streams if isinstance(s, str)]
    per = [{k: marked(clean(v), breaks=True) for k, v in s.items()} for s in streams if isinstance(s, dict)]
    order = ([n for s, n in zip(streams, names) if isinstance(s, str)]
             + [n for s, n in zip(streams, names) if isinstance(s, dict)])
    out, blank, heard = {}, {}, {}
    words_of = {lid: [w.lower() for w in marked(clean(t or "")) if w not in MARKS] for lid, (t, _, _) in laid.items()}
    for lid, (text, enum, group) in laid.items():
        own = int(re.match(r"\d+", lid).group())
        put = [numbered_at(s, own, text) for s in whole] + [p.get(lid, []) for p in per]
        other = [o for o in put if o]
        engines = [family(whose.get(lid, mine if isinstance(mine, str) else None))]
        engines += [family(n) for n, o in zip(order, put) if o]
        heard[lid] = [marked(clean(text), breaks=True) if text else None] + put
        if SEE_RE.match(text or ""):
            out[lid] = (text, enum, group)
            continue
        text = trimmed(text, lid, voted=False)
        # Voted whole, the other clue's words in the other readings confirm it.
        text = run_on(text, lid, laid)
        # A list counts up, so only a number above this clue's own can be
        # the next clue run on, and with the grid known, only one naming a
        # light: "Map 10 E" in 24 across is the clue's text.
        # It is the list's next clue, or the one after when that was lost:
        # "Removal of 25 I notice" in 16 down is a reference.
        way = lid.split("-")[1]
        later = sorted(int(k.split("-")[0]) for k in lengths or () if k.endswith("-" + way)
                       and int(k.split("-")[0]) > own)[:2]
        inside = next((m for m in re.finditer(r"\s(\d{1,2})\s+[A-Z]", text or "")
                       if int(m.group(1)) > own and (not lengths or int(m.group(1)) in later)), None)
        if inside and lengths:
            # The next clue run on after this one's count: cut it off, and
            # the count with it, which the grid gives.
            text = re.sub(r"\s*\([^)]*$", "", text[:inside.start()]).rstrip()
            # A count still inside ends the clue, and is its count when it
            # fills the light (all the linked lights): the one read after
            # the run-on was the next clue's.
            cells = sum(lengths.get(k, 0) for k in (group or [lid]))
            kept = re.search(r"\((\d{1,2}(?:\s*[,\-.]\s*\d{1,2})*)\)", text)
            if kept and sum(map(int, re.findall(r"\d+", kept.group(1)))) == cells:
                text = text[:kept.start()].rstrip()
                enum = re.sub(r"\s+", "", kept.group(1)).replace(".", ",")
            enum = enum or (str(lengths[lid]) if (lengths or {}).get(lid) else None)
            inside = None
        if inside:
            blank[lid] = "another clue's number inside it"
            out[lid] = ("", enum, group)
            continue
        text = cut_at_count(text, enum)
        if text:
            # "1 hear" opens "I hear"; were the opening lost, the vote finds it.
            text = re.sub(r"^1(?=\s+[a-z])", "I", text)
        # A clue may open on another light's number ("19, we hear, in the
        # crew", "25 in voice"): that is no lost opening.
        ref = re.match(r"(\d{1,2})(?:,| (?:across|down|ac|dn)\b)?\s+[a-z]", text or "")
        opens_on_light = bool(ref and lengths and int(ref.group(1)) != own
                              and any(k.startswith(ref.group(1) + "-") for k in lengths))
        if not opens_on_light and re.match(r"[^A-Za-z\"'(.]*\s*[a-z]", text or ""):
            printed = opening_printed(text, own, streams)
            if printed is None:
                # Lower case first: the clue's opening ("23s about") was lost.
                blank[lid] = "starts mid-clue"
                out[lid] = ("", enum, group)
                continue
            if printed[0].isupper():
                # The print's capital, misread small ("ln school", "fish").
                at = re.search(r"[a-z]", text).start()
                text = text[:at] + text[at].upper() + text[at + 1:]
        if enum is None and (lengths or {}).get(lid):
            # The other readings vote on the words, so a cut-short end shows.
            enum = str(lengths[lid])
        if enum is None and not uncounted:
            # The count lost with the clue's end: the words may be cut short.
            blank[lid] = "no count read"
            out[lid] = ("", enum, group)
            continue
        text = clean(text)
        # The clue's own number read twice ("21 21 The woman", "1 11 Money").
        lead = re.match(r"(\d{1,2})\.? (?=[A-Z\"'])", text)
        if lead and lead.group(1) in lid.split("-")[0]:
            text = text[lead.end():]
        text = join_split(numbers_joined(text, streams), other)
        got, how = agree(text, other, keep_known, engines, rates, [w for k, w in words_of.items() if k != lid])
        got = trimmed(cut_at_count(got, enum), lid)
        if got is not None and merged(got):
            got, how = None, merged(got)
        if got is None:
            blank[lid] = how
            out[lid] = ("", enum, group)
        else:
            out[lid] = (got, enum, group)
    if rates is None and blank and any(map(family, order)) and (got := family_rates(out, heard, whose, mine, order)):
        again, _ = reconcile({lid: laid[lid] for lid in blank}, streams, lengths, keep_known,
                             uncounted, names, mine, got)
        for lid, (text, enum, group) in again.items():
            if text:
                out[lid] = (text, enum, group)
                blank.pop(lid)
    return out, blank


#: How many other readings must print a clue for the light at least
#: RELAID_SIMILAR like a reading's for relaid() to lay it, one of them a
#: reading of another copy (copy_of). Measured on Times editions with a
#: Canberra reprint: one copy's readings alone re-laid 17 of 43 clues wrong.
RELAID_READINGS = 2
RELAID_SIMILAR = 0.8


def split_added(before, after):
    """[(word, word)] each pair of words side by side in `after` (a clue
    the vote put words into) where one repeats the other or is its start or
    end ("bur burlesque", "plodding ding", "requirement requirement") and
    `before` has no such pair: a half of a word one copy split at its line
    end and another did not, put in beside the whole word."""
    def pairs(text):
        ws = [w.lower() for w in re.findall(r"[A-Za-z]+", text or "")]
        return {(a, b) for a, b in itertools.pairwise(ws) if len(a) >= 2 and len(b) >= 2
                and (a == b or b.startswith(a) or a.endswith(b))}
    return sorted(pairs(after) - pairs(before))


def copy_of(name):
    """The printed copy a reading named `name` read: "canberra:<article>"
    for "canberra:<article>:<reader>", "" for the scan's own readers."""
    return name.rsplit(":", 1)[0] if ":" in name else ""


def relaid(texts, laid, blank, parse, lengths, keep_known=False):
    """(laid, blank) with each clue the vote filed blank laid again from
    each reading in `texts` ({name: text}) in turn: that reading's own clue
    for the light, when its printed count fills the light and
    RELAID_READINGS other readings print a like clue there, one of them of
    another copy of the print (a reprint), put to every other reading
    (reconcile, which alone proves nothing: it judges only the words it can
    align). The first that wins the vote, and that fault() and suspect()
    pass, is filed. A light laid from a reading that lost the clue's start
    or end, or none, is filled by a reading that printed it whole. Linked
    lights are left as they are."""
    laid, blank = dict(laid), dict(blank)
    parsed = {k: (parse(t)[0] if t.strip() else None) for k, t in texts.items()}
    for lid in sorted(blank):
        group = (laid.get(lid) or ("", None, None))[2]
        if group or not lengths.get(lid):
            continue
        n, direction = lid.split("-")
        cells = lengths[lid]
        for k, p in parsed.items():
            clue = next((c for c in (p or {}).get(direction, ()) if c["tokens"] and int(n) in c["tokens"][0]
                         and len(c["tokens"]) == 1 and c["see"] is None), None)
            if clue is None or not tokens(clue["text"]):
                continue
            fill = sorted(shape(e) for e in clue.get("enums") or () if sum(map(int, re.findall(r"\d+", e))) == cells)
            if not fill:
                continue
            # Borne out: other readings print a like clue for the light, one
            # of them a reading of another copy of the print.
            alike = {j for j, q in parsed.items() if j != k and any(
                c["tokens"] and int(n) in c["tokens"][0] and similar(c["text"].lower(), clue["text"].lower())
                >= RELAID_SIMILAR for c in (q or {}).get(direction, ()))}
            if len(alike) < RELAID_READINGS or all(copy_of(j) == copy_of(k) for j in alike):
                continue
            others = [t for j, t in texts.items() if j != k and t.strip()]
            got, why = reconcile({lid: (clean(clue["text"]), fill[0], None)}, others, lengths, keep_known)
            text, count, _ = got[lid]
            if lid in why or not text or fault(text, count, cells) or suspect(text) or \
                    split_added(clean(clue["text"]), text):
                continue
            laid[lid] = (text, count, None)
            del blank[lid]
            break
    return laid, blank


# ------------------------------------------------------------ the check

#: A digit inside a word ("know7", "Hunts7", "wo2rd"), not a count or a
#: cross-reference ("1st", "10cc", "17ac", "WW2", "G7").
DIGIT_IN_WORD = re.compile(r"[A-Za-z]\d+[A-Za-z]|[a-z]{2}\d+$")
#: A cross-reference or a count with its unit, which may run digits into letters.
COUNTED = re.compile(r"\d+(?:st|nd|rd|th|s|d|p|cc|pm|am|k|m|ac|dn|a|d|x\d+)", re.IGNORECASE)
#: A mark inside a word that no clue prints there ("Wi'.h", "wor,d").
MARK_IN_WORD = re.compile(r"[^\W\d_][^\w\s'\u2019\-&/.]+[^\W\d_]|[^\W\d_]['\u2019.\-]{2,}[^\W\d_]")
#: A capital after small letters, the word's last letter or inside a word
#: no dictionary knows ("bacK", "RcbufT", "ofTer"); not "McX" or "O'X".
CAPS_IN_WORD = re.compile(r"[a-z][A-Z]")
#: OCR's commonest letter slips, both ways, for the misread-name test.
NAME_SLIPS = SLIPS + (("v", "y"),)
#: Characters stripped off a token's ends before it is judged.
EDGE = "\"'()[]{}.,;:!?\u2014\u2013-\u2026\u2018\u2019\u201c\u201d*"


def plain(word):
    """The word without its accents ("rosé" is "rose" to the lexicon)."""
    return "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.combining(c))


#: How common (by lexicon rank) a word one slip from a name must be for the
#: name to count as its misreading: "Plaved" for played, not "Ara" for "Ana".
NAME_RANK = 20000


def slipped(word):
    """Whether one SLIPS swap turns the capitalised `word` into a common
    lexicon word (rank within NAME_RANK)."""
    low = word.lower()
    for a, b in NAME_SLIPS + tuple((b, a) for a, b in NAME_SLIPS):
        at = low.find(a)
        while at >= 0:
            v = low[:at] + b + low[at + len(a):]
            if len(v) > 2 and (rank(v) or NAME_RANK + 1) <= NAME_RANK:
                return True
            at = low.find(a, at + 1)
    return False


#: Endings and beginnings that make a known word another ("ceasefires",
#: "redubbed", "antifeminist"); "-er" is left out, since "scater" is "scat".
SUFFIXES = (("ies", "y"), ("es", ""), ("s", ""), ("ed", ""), ("ed", "e"), ("d", ""), ("ing", ""),
            ("ing", "e"), ("ers", ""), ("ers", "e"), ("ly", ""), ("ness", ""))
PREFIXES = ("un", "re", "anti", "non", "over", "under", "pre", "dis", "mis", "out", "counter")


def formed(word):
    """Whether `word` (lower case) is a known word with a common ending or
    beginning, two lexicon words run together ("nighttime", "penpal"), or a
    dropped letter marked by an apostrophe ("'eap", "overtakin'")."""
    if word.startswith("'") and known("h" + word[1:]):
        return True
    if word.endswith("'") and known(word[:-1] + "g"):
        return True
    word = word.strip("'")
    for end, put in SUFFIXES:
        if word.endswith(end) and len(word) - len(end) >= 3 and known(word[:-len(end)] + put):
            return True
    for pre in PREFIXES:
        if word.startswith(pre) and len(word) - len(pre) >= 4 and known(word[len(pre):]):
            return True
    return any(is_word(word[:k]) and is_word(word[k:]) for k in range(3, len(word) - 2))


#: Print specks OCR reads as symbols no clue prints, alone or on a word
#: ("is»", "of£", "■").
JUNK_MARK = re.compile(r"[■»«•|^~¬§¤©®°±¶¦]")
#: A character no English clue prints: JUNK_MARK, a pound or dollar sign
#: against a letter, or one from outside the Latin script (a recogniser's
#: Chinese reading of a speck, "王4").
JUNK = re.compile(JUNK_MARK.pattern + r"|(?<=[a-z])[£$]|[£$](?=[a-z])|[^\x00-\u024f\u2010-\u203a\u20ac]")


def doubled(text):
    """[(pair, why)] for a word printed again as the start of the next
    ("him himself", "re return"), the mark of one reading's word voted in
    beside another's. Clues print such pairs too ("in India"), so it judges
    only what a vote added."""
    ws = re.findall(r"[A-Za-z]+", text or "")
    return [(f"{a} {b}", "a word doubled into the next") for a, b in itertools.pairwise(ws)
            if len(a) >= 2 and len(b) - len(a) >= 3 and b.lower().startswith(a.lower())]


#: How often the corpus's clues must print a word twice in a row for the
#: pair to be English ("in in", "very very", "old old"), not a reading's
#: word voted in beside another's ("composer composer").
DOUBLE_FLOOR = 5
#: A token ending in one of these marks the next word as a sentence's start,
#: a quotation's or an aside's, where a capital is the print's.
OPENS_NEXT = tuple(".?!:;\"'()\u2014\u2013-\u201c\u201d\u2018\u2019\u2026&")
#: The lone small letters a clue prints: the article, and "v" for versus.
LONE_LETTER_OK = {"a", "v"}
#: Two lone small letters that are e.g. or i.e. with their stops lost.
LETTER_PAIRS = {("e", "g"), ("i", "e")}
#: The words before a lone small letter that make it a letter the clue
#: names ("with a c", "the letter n").
NAMES_LETTER = {"a", "an", "the", "letter", "letters"}


def strays(text):
    """[(k, why)] for each whitespace token `text.split()[k]` of a voted clue
    that no print has there:
      - a word printed again straight after itself with nothing between
        ("composer composer"; k is the second), unless the corpus's clues
        print that pair DOUBLE_FLOOR times ("in in", "very very");
      - a capitalised word inside a sentence repeating an earlier word of
        the clue, where it breaks the phrase: the corpus's clues never print
        it before the next word and do print the words either side of it
        together ("Plan is to Plan destroy", a reading's line start voted
        in again; not "Doctor and Doctor", "the art of The Times");
      - a lone small letter, not LONE_LETTER_OK, an apostrophe's ("'e",
        "'s"), a quoted or dashed one ("--s"), e.g. / i.e. or a letter the
        clue names ("with a c"): "round t the heart", "new t". A capital
        letter alone is the setter's ("S Africa", "Brand X");
      - a lone underscore touching a word or mark (SPECK_UNDERSCORE:
        "love,_emperor"), which unstrayed() takes out.
    Clues print none of these: each is one reading's speck or doubled line
    the vote left in."""
    raw = (text or "").split()
    _, pair, _ = clue_lm()
    bare = [r.strip(EDGE) for r in raw]
    out = []
    for k in range(1, len(raw)):
        a, b = bare[k - 1], bare[k]
        if a.isalpha() and len(a) > 1 and a.lower() == b.lower() and raw[k - 1] == a and raw[k].startswith(b) \
                and pair.get(f"{a.lower()} {a.lower()}", 0) < DOUBLE_FLOOR:
            out.append((k, "a word doubled"))
    seen = set()
    for k, w in enumerate(bare):
        heads = tokens(raw[k + 1]) if k + 1 < len(raw) else []
        if k and w.isalpha() and len(w) > 1 and w[0].isupper() and w[1:].islower() and w.lower() in seen \
                and raw[k] == w and not raw[k - 1].endswith(OPENS_NEXT) and bare[k - 1].isalpha() \
                and heads and raw[k + 1][0].islower():
            before, after = bare[k - 1].lower(), heads[0].lower()
            if not pair.get(f"{w.lower()} {after}") and pair.get(f"{before} {after}"):
                out.append((k, "an earlier word repeated inside the clue"))
        seen.update(t.lower() for t in tokens(raw[k]))
    for k, s in enumerate(bare):
        if len(s) != 1 or not s.islower() or s in LONE_LETTER_OK \
                or re.search("['\u2019\u2018\"\u201c\u201d\\-\u2014\u2013]", raw[k]):
            continue
        prev = bare[k - 1].lower() if k else ""
        nxt = bare[k + 1].lower() if k + 1 < len(raw) else ""
        if (s, nxt) in LETTER_PAIRS or (prev, s) in LETTER_PAIRS or prev in NAMES_LETTER:
            continue
        out.append((k, "a stray letter"))
    out += [(k, "a speck read as an underscore") for k, r in enumerate(raw) if SPECK_UNDERSCORE.search(r)]
    return sorted(out)


def stray(text):
    """[(token, why)] for each token strays() flags."""
    raw = (text or "").split()
    return [(raw[k], why) for k, why in strays(text)]


def unstrayed(text, theirs):
    """`text` with each token strays() flags mended from the readings
    `theirs` (each one's text for the clue): taken out where a reading
    prints the words either side of it together, or set in capitals where
    one prints it so ("Brand X"); a flag no reading mends stands, for the
    caller to file the clue blank."""
    text = unspecked(text or "")
    seqs = [[w.lower() for w in tokens(t)] for t in theirs]
    caps = [tokens(t) for t in theirs]

    def printed(left, mid, right, case=False):
        want = [w for w in (left, *mid, right) if w is not None]
        for ws, cs in zip(seqs, caps):
            for i in range(len(ws) - len(want) + 1):
                if ws[i:i + len(want)] == [w.lower() for w in want] and (left is not None or i == 0) and (
                        right is not None or i + len(want) == len(ws)) and (
                        not case or all(c in cs[i:i + len(want)] for c in mid)):
                    return True
        return False
    for _ in range(len((text or "").split())):
        flags = strays(text)
        if not flags:
            break
        raw = text.split()
        mended = None
        for k, why in flags:
            left = (tokens(" ".join(raw[:k])) or [None])[-1]
            right = (tokens(" ".join(raw[k + 1:])) or [None])[0]
            word = raw[k].strip(EDGE)
            if printed(left, [], right):
                mended = raw[:k] + raw[k + 1:]
                # A stop after the dropped letter ends the word before it: "new t." is "new.".
                tail = raw[k][raw[k].index(word) + len(word):]
                if k and re.fullmatch(r"[.,;:?!]+", tail) and not raw[k - 1].endswith(tuple(tail)):
                    mended[k - 1] += tail
                break
            if why == "a stray letter" and printed(left, [word.upper()], right, case=True):
                mended = raw[:k] + [raw[k].replace(word, word.upper(), 1)] + raw[k + 1:]
                break
        if mended is None:
            break
        text = " ".join(mended)
    return text


#: The letters OCR reads as an apostrophe: a thin upright stroke.
APOSTROPHE_FOR = "il"
#: What follows a contraction's apostrophe ("I'll" is no "Ill").
CONTRACTED = re.compile(r"(?:s|t|d|m|ll|re|ve)", re.IGNORECASE)


def letter_lost(word):
    """Is the one apostrophe inside `word` a letter OCR read as a stroke? It
    is when the word is no word as it stands, no contraction, and an i or l
    in its place makes one ("He r'ddled" for "riddled", No 97 6D). A poet
    elides an e ("wand'ring", "heav'n"), and a setter's dialect drops a
    letter near the end (Em'ly, Rob'n, Li'l), so those stand: the corpus's
    clues hold no such word with three letters after the mark."""
    head, _, tail = word.partition("'")
    if not head.isalpha() or not tail.isalpha() or len(tail) < 3 or CONTRACTED.fullmatch(tail):
        return False
    flat = plain(word).lower()
    return not known(flat) and any(known(flat.replace("'", c)) for c in APOSTROPHE_FOR)


def letter_put_back(text):
    """`text` with each word letter_lost() finds mended: the apostrophe made
    the one letter of APOSTROPHE_FOR that gives a known word ("r'ddled" is
    "riddled"). A word two letters would mend stays as read."""
    def mend_one(m):
        w = m.group()
        if not letter_lost(w):
            return w
        got = [c for c in APOSTROPHE_FOR if known(plain(w).lower().replace("'", c))]
        return w.replace("'", got[0]) if len(got) == 1 else w
    return re.sub(r"[A-Za-z]+'[A-Za-z]+", mend_one, text or "")


def suspect(text, vouched=(), printed=()):
    """[(token, why)] for each word of a clue's text that OCR, not the setter,
    wrote. `vouched` holds lower-case words every reading spelt alike, which
    stand though the lexicon lacks them (a rare word, a name); `printed`
    holds tokens of the text the clue's `asPrinted` keeps (printed_alike)."""
    out = []
    for raw in (text or "").split():
        s = raw.strip(EDGE)
        if not s or raw in printed:
            continue
        if DIGIT_IN_WORD.search(s) and not COUNTED.fullmatch(s.lstrip("£$")):
            out.append((raw, "a digit inside a word"))
            continue
        if MARK_IN_WORD.search(s) or JUNK.search(raw) or re.search(r"[a-z]{2}\.[a-z]{2}", s):
            out.append((raw, "a stray mark inside a word"))
            continue
        if any(re.search(r"[A-Za-z]", p) and re.search(r"\d", p) and not (
                COUNTED.fullmatch(p.lstrip("£$")) or re.fullmatch(r"[A-Z]+\d+[A-Z]*|\d+[A-Za-z]{1,2}", p))
               for p in re.split(r"[-/.'\u2019,]", s)):
            out.append((raw, "a digit inside a word"))
            continue
        for p in re.split(r"[-./&]", s.replace("\u2018", "'").replace("\u2019", "'")):
            bare = p.strip("'")
            if letter_lost(bare):
                out.append((raw, "an apostrophe for a letter"))
                break
            if not bare.isalpha() or len(bare) < 2:
                continue
            flat = plain(bare)
            m = CAPS_IN_WORD.search(flat)
            if m and not re.match(r"(?:Mc|Mac|O'|D')", flat) and (
                    m.end() == len(flat) or not known(flat.lower())):
                out.append((raw, "a capital inside a word"))
                break
            if flat.lower() in vouched:
                continue
            if known(flat) or formed(plain(p).lower()) or any(
                    known(f) for f in {flat.translate(LIGATURES), flat.translate(LIGATURE_E)} - {flat}):
                continue  # a ligature is its word's ("mediæval")
            if flat.isupper() and len(flat) <= 4:
                continue  # an abbreviation: "RN", "TUC"
            if flat[0].islower():
                out.append((raw, "not a word"))
                break
            if slipped(flat):
                out.append((raw, "a word misread as a name"))
                break
    # A bracket the clue never closes, or never opened, is a letter or a
    # count misread ("is (this", "for ) record").
    k = unpaired(text)
    if k is not None and holding(text, k) not in printed:
        out.append((holding(text, k), "a bracket never closed or opened"))
    return out + stray(text)


#: A quotation opening: a quote mark at the clue's start or after a space
#: or a mark, before a capital ("'Resting weary", "say, 'Give") or an
#: elided start ("'. . . is a monster"); not an elision ("'Tis", "'Twas").
QUOTE_OPEN = re.compile(r"(?:^|(?<=[\s,;:(\u2014*\u2020\u2021]))(['\u2018\"\u201c])(?!T(?:is|was|were|would|will)\b)"
                        r"(?=[A-Z]|\.\s*\.|\u2014\u2014)")


#: A single quote that closes: one no letter follows (an apostrophe inside
#: a word is none), or one after a stop before a possessive's s
#: ("a wonder . . .'s.").
CLOSE_SINGLE = r"['\u2019](?![A-Za-z])|(?<=[.!?,;:])['\u2019](?=s\b)"
#: An elided word a quote mark opens: "'Tis", "'Twas".
ELISION = r"T(?:is|was|were|would|will)\b"


def paired(text):
    """`text` with each double quote mark that pairs with nothing made the
    single quote readers misread it for: one opening an elision ('"Tis
    said' for "'Tis said"), and a quotation's opening that only a single
    quote closes ('"That's ... wonder . . .'s.'). A double quote a double
    closes stays."""
    if not text:
        return text
    doubles = [m for m in re.finditer(r"[\"“”]", text)]
    if len(doubles) % 2 and (m := re.search(r"(?:^|(?<=[\s,;:(]))[\"“](?=" + ELISION + ")", text)):
        return paired(text[:m.start()] + "'" + text[m.end():])
    for m in QUOTE_OPEN.finditer(text):
        rest = text[m.end():]
        if m.group(1) in "\"“" and not re.search(r"[\"”]", rest) \
                and re.search(r"(?<![A-Za-z\s])['\u2019]", rest):
            return text[:m.start()] + "'" + rest
    return text


def reclosed(text, readings):
    """`text`, a clue whose quotation opens and never closes, with the
    closing a reading (`readings`, each reading's text, whole or for the
    light) prints after the clue's last three words put back: a run of
    stops (an ellipsis, written ". . .") and a closing single quote, with
    a possessive's s and a stop ("wonder .. 's." where the vote kept
    "wonder. .."); else a closing quote a reading prints between two of
    the clue's words side by side (No 4 8A's "'London's lasting shame,'
    but", the vote keeping "shame, but"). None when no reading prints one,
    or it leaves the clue unclosed."""
    last = re.findall(r"[A-Za-z]+", text or "")[-3:]
    if len(last) < 3:
        return None
    find = re.compile(r"\b" + r"\W+".join(last) + r"((?:\s*\.){0,3}\s*['\u2019](?:s\b)?[.,;:!?]?)(?=\s|$)")
    for r in readings:
        if not r or not (m := find.search(r)):
            continue
        tail = re.sub(r"\s+(?=['\u2019])", "", re.sub(r"^(?:\s*\.){2,3}", " . . .", m.group(1)))
        at = text.rfind(last[-1]) + len(last[-1])
        got = paired(text[:at] + tail)
        if unclosed_quote(got) is None:
            return got
    words = list(re.finditer(r"[A-Za-z]+", text))
    for r in readings:
        for a, b, c in zip(words, words[1:], words[2:]):
            m = re.search(rf"\b{a.group()}\W+{b.group()}([.,;:!?]?['\u2019][.,;:!?]?)\s+{c.group()}\b", r or "")
            if m and "'" not in text[b.end():c.start()] and "\u2019" not in text[b.end():c.start()]:
                got = paired(text[:b.end()] + m.group(1) + " " + text[c.start():])
                if unclosed_quote(got) is None:
                    return got
    return None


def unclosed_quote(text):
    """The index of a quotation `text` opens and never closes, or closes
    and never opened, or None: its end, a blank the readers cannot see
    ("beds of \u2014\u2014'." read as "beds of"), or its start is lost. A single quote closes at a quote mark not followed
    by a letter (an apostrophe inside a word is none), a double at a
    double."""
    for m in QUOTE_OPEN.finditer(text or ""):
        rest = text[m.end():]
        shut = r"[\"\u201d]" if m.group(1) in "\"\u201c" else CLOSE_SINGLE
        if not re.search(shut, rest):
            return m.start()
    # A single quote shut after a word not ending in s (no plural's
    # apostrophe: "the lyre'.") that nothing opened: its start is lost.
    m = re.search(r"(?<=[A-Za-z][a-rt-zA-RT-Z])['\u2019](?![A-Za-z])", text or "")
    if m and not re.search(r"(?:^|(?<=[\s,;:(\u2014*\u2020\u2021]))['\"\u201c](?=[A-Za-z]|\.\s*\.|\u2014\u2014)|\u2018", text[:m.start()]):
        return m.start()
    return None


#: A quotation whose start is elided, its opening mark and most of the
#: stops lost: "rev. . is a monster" for "rev. \u2018. . . is a monster".
ELIDED = re.compile(r"^((?:rev[.,]\s+)?)\.(?:\s*\.)*\s+(?=\w)", re.IGNORECASE)


def reopened(text, readings):
    """`text`, a clue whose quotation closes and never opens, with the
    opening mark put back that a reading of it (`readings`) prints before
    the same first word ("\u2018And the ..." where the vote kept "And the
    ... lyre'."); a reader drops a faint mark far oftener than it makes one.
    A stop standing alone before the first word (ELIDED) is what is left of
    an elided start, so the quotation opens there ("'. . . is a monster").
    None when neither puts the mark back, or it leaves the clue unclosed."""
    first = (text or "").split(None, 1)[:1]
    if not first or text[0] in "'\u2018\"\u201c":
        return None
    if (m := ELIDED.match(text)) and unclosed_quote(got := m.group(1) + "'. . . " + text[m.end():]) is None:
        return got
    for r in readings:
        m = re.match(r"\s*(['\u2018\"\u201c])(\S+)", r or "")
        if m and m.group(2).strip(EDGE) == first[0].strip(EDGE):
            got = ("'" if m.group(1) in "'\u2018" else '"') + text
            if unclosed_quote(got) is None:
                return got
    return None


def unquoted_speck(text, readings):
    """`text` without the single quote it opens with and never closes,
    when the clue ends a whole sentence (a quotation whose end is lost
    leaves its last word bare: "'Resting ... on beds of") and a reading of
    it (`readings`) prints its first word with no mark before it: a speck
    by the clue's number read as a quote (No 10 41A "'This word might be put
    into the mouth of Death."). None otherwise."""
    if not text or text[0] not in "'‘" or unclosed_quote(text) != 0 or not re.search(r"\w[.?!]$", text):
        return None
    first = text[1:].split(None, 1)[:1]
    if first and any(re.match(r"\s*" + re.escape(first[0]) + r"(?:\s|$)", r or "") for r in readings):
        return text[1:]
    return None


def holding(text, k):
    """The whitespace-parted token of `text` holding its character `k`."""
    return text[:k].rsplit(None, 1)[-1] + text[k:].split(None, 1)[0] if text[:k] and not text[k - 1].isspace() \
        else text[k:].split(None, 1)[0]


def printed_alike(text, readings):
    """The tokens of a voted clue `text` that suspect() would refuse, which
    the print itself spells so: each word suspect() flags as no word that at
    least two of `readings` (each reading's own text for the light, None
    where it has none) hold letter for letter, and a bracket the clue never
    pairs that at least two hold before the same word and none closes (No
    15's 22 down, "slang (from Hollywood meaning ...", its bracket never
    shut). The clue's `asPrinted`: what a misprint looks like to the vote.
    A reading that lost the words votes neither way."""
    own = [r for r in readings if r]
    if len(own) < 2:
        return []
    low = [" ".join(r.lower().split()) for r in own]
    out = []
    for raw, why in suspect(text):
        word = raw.strip(EDGE).lower()
        if why == "not a word" and sum(bool(re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", r))
                                       for r in low) >= 2:
            out.append(raw)
    k = unpaired(text)
    if k is not None and text[k] in "([":
        after = re.match(r"\s*([A-Za-z]+)", text[k + 1:])
        if after:
            opened = re.compile(re.escape(text[k]) + r"\s*" + re.escape(after.group(1).lower()) + r"(?![a-z])")
            holds = [r for r in low if opened.search(r)]
            closed = [r for r in holds if unpaired(r) is None]
            if len(holds) >= 2 and not closed:
                out.append(holding(text, k))
    return out


# ------------------------------------------------------------ the VLM's pick

#: A count at a clue's end, which the VLM's pick may carry.
COUNT_END = re.compile(r"\s*\(([\d\s,.\-]+)\)\W*$")


def candidates(texts, lid, parse):
    """Each reading's text for one light ("N-across"), with its count;
    `parse` turns a reading into {"across": clues, "down": clues} (or None)
    and why, as file_trove_puzzles.clues() reads them."""
    n, direction = lid.split("-")
    out = []
    for t in texts.values():
        parsed, _ = parse(t) if t.strip() else (None, None)
        for c in (parsed or {}).get(direction, []):
            if c["tokens"] and int(n) in c["tokens"][0]:
                enum = min(c["enums"]) if c.get("enums") else None
                out.append(c["text"].strip() + (f" ({enum})" if enum else ""))
                break
    return out


def held(text, cands):
    """The VLM's pick `text` held to the readings `cands` (each one's text
    for the clue) word by word, or "" when it cannot be: a word suspect()
    flags takes the known word most readings have there ("linner" where
    one reads "linnet"), and with none the pick fails; a word no reading
    has, where every reading has one known word a letter from it, takes
    that word ("gain" where all read "gait"). A pick most of whose words
    no reading has within a letter is another clue's, and fails."""
    words = list(re.finditer(r"[A-Za-z]+(?:'[A-Za-z]+)?", text or ""))
    if not words:
        return text or ""
    low = [m.group().lower() for m in words]
    there = [[] for _ in words]
    theirs = [tokens(COUNT_END.sub("", c)) for c in cands]
    for ws in theirs:
        for i, j in align(low, [w.lower() for w in ws]):
            if i is not None and j is not None:
                there[i].append(ws[j].lower())
    if theirs and 2 * sum(any(within_one(a, v) for v in there[i]) for i, a in enumerate(low)) < len(low):
        return ""
    out, k = "", 0
    for i, m in enumerate(words):
        a, w = low[i], m.group()
        new = a
        if suspect(w):
            got = [v for v in there[i] if known(v)]
            if not got:
                return ""
            new = max(got, key=lambda v: (got.count(v), similar(v, a)))
        elif theirs and a not in there[i] and len(there[i]) == len(theirs) \
                and len(set(there[i])) == 1 and known(there[i][0]) and within_one(a, there[i][0]):
            new = there[i][0]
        if new != a:
            new = new.capitalize() if w[:1].isupper() else new
            out += text[k:m.start()] + new
            k = m.end()
    return out + text[k:]


def vlm_pick(texts, laid, blank, parse, pick):
    """(laid, blank) with each clue reconcile() filed blank read by the VLM
    (tools/vlm_reader.py): `pick(light, candidates)` is its text for the
    clue, shown every reading's text for it (the VLM's own column reading
    among them), or None."""
    laid, blank = dict(laid), dict(blank)
    for lid in list(blank):
        cands = candidates(texts, lid, parse)
        if not cands:
            continue
        got = trimmed(held(clean(COUNT_END.sub("", pick(lid, cands) or "")), cands), lid)
        if not tokens(got) or merged(got):
            continue
        laid[lid] = (got, laid[lid][1], laid[lid][2])
        del blank[lid]
    return laid, blank


# ------------------------------------------------------------ as the readings print it

def readings_for(texts, lid, parse):
    """[(text, {count, ...})] each reading's clue for one light ("N-across")."""
    n, direction = lid.split("-")
    out = []
    for t in texts.values():
        parsed, _ = parse(t) if t.strip() else (None, None)
        for c in (parsed or {}).get(direction, []):
            if c["tokens"] and int(n) in c["tokens"][0]:
                out.append((clean(c["text"]), c.get("enums") or set()))
                break
    return out


def shape(enum):
    """A count as the print sets it: "5-4", "3,6", "9"."""
    return re.sub(r"\s+", "", enum or "").replace(".", ",")


def printed_count(enum, counts, cells):
    """(count, why): the count most readings print that fills the clue's
    `cells` (`counts`: each reading's {counts}), against the laid `enum`.
    A reader loses a hyphen or a comma far more often than it makes one,
    so a tie goes to the count with more parts, then to `enum`; two
    counts no rule parts are no count (None, why)."""
    fill = [next((shape(e) for e in sorted(es) if sum(map(int, re.findall(r"\d+", e))) == cells), None)
            for es in counts]
    fill = [f for f in fill if f]
    if not fill or not cells:
        return enum, None
    top = max(fill.count(f) for f in fill)
    best = {f for f in fill if fill.count(f) == top}
    parts = max(len(re.findall(r"\d+", f)) for f in best)
    best = {f for f in best if len(re.findall(r"\d+", f)) == parts}
    if shape(enum) in best or len(best) == 1:
        return (enum if shape(enum) in best else best.pop()), None
    return None, f"readings print counts {' / '.join(sorted(best))}"


WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
COMPOUND = re.compile(r"\b([A-Za-z]+)-([A-Za-z]+)\b")


def printed_words(text, theirs, broken=()):
    """`text` with each word as the readings `theirs` (each one's clue text)
    print it: the clue's first word takes the capital a reading prints
    ("Involve", not "involve"), a word loses a capital inside it most
    readings lack ("bacK"); a word no lexicon knows where most readings that have a word
    there have one known word takes it; two words most readings join with a
    hyphen ("re-forms") are joined so, and only those. A word in `broken`
    (lower case, hyphened only at a line end in the readings' columns) is
    left as clean() joined it: a line end breaks "en-closed" and
    "horse-race" alike."""
    words = list(WORD.finditer(text))
    if not words or not theirs:
        return text
    low = [m.group().lower() for m in words]
    there = [[] for _ in words]
    for t in theirs:
        ws = WORD.findall(t)
        for i, j in align(low, [v.lower() for v in ws]):
            if i is not None and j is not None:
                there[i].append(ws[j])
    out, k = "", 0
    for i, m in enumerate(words):
        w, a = m.group(), low[i]
        new = w
        same = [v for v in there[i] if v.lower() == a]
        if same:
            top = max(same, key=same.count)
            if i == 0 and w[0].islower() and any(v[0].isupper() for v in same):
                new = w[0].upper() + w[1:]
            elif CAPS_IN_WORD.search(w) and not CAPS_IN_WORD.search(top) and same.count(top) * 2 > len(there[i]):
                new = top  # a capital inside the word most readings do not see ("bacK")
        elif not known(a) and not formed(a):
            got = [v for v in there[i] if known(v)]
            top = max(got, key=lambda v: (got.count(v), similar(v.lower(), a)), default=None)
            if top and got.count(top) * 2 > len(there[i]) and similar(top.lower(), a) >= 0.5:
                new = top if top[0].isupper() == w[0].isupper() else (
                    top.capitalize() if w[0].isupper() else top.lower())
        out += text[k:m.start()] + new
        k = m.end()
    out += text[k:]
    # Hyphens: each compound some reading prints, put where most readings
    # with those letters print it so and taken out where none does.
    hyphened, joined = {}, {}
    for t in theirs:
        for m in COMPOUND.finditer(t):
            key = (m.group(1) + m.group(2)).lower()
            hyphened.setdefault(key, set()).add(m.group(1).lower())
        for w in WORD.findall(t):
            joined[w.lower()] = joined.get(w.lower(), 0) + 1
    for key, heads in hyphened.items():
        for head in heads:
            if key in broken:
                continue
            n = sum(1 for t in theirs if re.search(rf"\b{head}-{key[len(head):]}\b", t, re.IGNORECASE))
            # The halves apart round a dash ("in - cosmetician's"): a dash, not a hyphen.
            apart = sum(1 for t in theirs if re.search(rf"\b{head}\s+[-\u2013\u2014]\s+{key[len(head):]}\b", t, re.IGNORECASE))
            if apart > n:
                out = re.sub(rf"\b({head})-({key[len(head):]})\b", r"\1 - \2", out, flags=re.IGNORECASE)
                continue
            if n >= joined.get(key, 0):
                out = re.sub(rf"\b({head})({key[len(head):]})\b", r"\1-\2", out, flags=re.IGNORECASE)
    # A word split at a line end, the hyphen read as a mark ("Words, worth"):
    # joined where a reading prints it whole, another prints a mark between
    # its halves, and none prints them with only a space between.
    for a, b in itertools.pairwise(list(WORD.finditer(out))[::-1]):
        x, y = b.group(), a.group()
        whole = (x + y).lower()
        if not (out[b.end():a.start()].isspace() and known(whole) and whole in joined):
            continue
        if any(re.search(rf"\b{x}[,.:;]\s*{y}\b", t, re.IGNORECASE) for t in theirs) and not any(
                re.search(rf"\b{x}\s+{y}\b", t, re.IGNORECASE) for t in theirs):
            out = out[:b.end()] + out[a.start():]
    for m in list(COMPOUND.finditer(out))[::-1]:
        key = (m.group(1) + m.group(2)).lower()
        if key not in broken and key not in hyphened and joined.get(key, 0) * 2 > len(theirs):
            out = out[:m.start()] + m.group(1) + m.group(2) + out[m.end():]
    return out


def as_printed(texts, laid, blank, parse, lengths, uncounted=False):
    """(laid, blank) with every filed clue held to what the readings `texts`
    print for its light: its count takes the shape most of them print
    (printed_count; "(5-4)", not the "(9)" a lost count left), and its
    words their capitals, hyphens and known spellings (printed_words). A
    count no reading settles files the clue blank. The last check before
    filing, after the vote and the VLM's pick alike. `uncounted`: the lists
    print no counts, so a clue none of the readings counts keeps none."""
    laid, blank = dict(laid), dict(blank)
    # A hyphen the columns print only at a line end says nothing of the word.
    ends = {(m.group(1) + m.group(2)).lower() for t in texts.values()
            for m in re.finditer(r"([A-Za-z]+)-[ \t]*\n\s*([A-Za-z]+)", t)}
    inside = {(m.group(1) + m.group(2)).lower() for t in texts.values()
              for m in re.finditer(r"([A-Za-z]+)-([A-Za-z]+)", t)}
    broken = ends - inside
    for lid, (text, enum, group) in list(laid.items()):
        if not text or lid in blank or SEE_RE.match(text):
            continue
        theirs = readings_for(texts, lid, parse)
        cells = sum(lengths.get(k, 0) for k in (group or [lid]))
        enum, why = (None, None) if uncounted and enum is None and not any(es for _, es in theirs) \
            else printed_count(enum, [es for _, es in theirs], cells)
        if why:
            laid[lid], blank[lid] = ("", None, group), why
            continue
        text = printed_words(text, [t for t, _ in theirs], broken)
        laid[lid] = (unstrayed(text, [t for t, _ in theirs]), enum, group)
    return laid, blank


def one_light_each(laid, blank, fits=()):
    """(laid, blank) with no clue on two lights. One printed clue read onto
    two lights (a reading's misread number, a lost one filled by position)
    has lost the other light's clue: it stays on the one light in `fits`
    (the lights whose printed count fills them) when exactly one of them is,
    and every other light it sits on is filed blank, to be read again. The
    same words in both lists are two printed clues (duplicated_clues'
    `one_list`)."""
    from fetch_puzzle import duplicated_clues
    laid, blank = dict(laid), dict(blank)
    entries = [{"number": int(lid.split("-")[0]), "direction": lid.split("-")[1], "clue": {"text": t}}
               for lid, (t, _, _) in laid.items() if t]
    for ids in duplicated_clues(entries, one_list=True):
        keep = [lid for lid in ids if lid in fits]
        keep = keep[0] if len(keep) == 1 else None
        for lid in ids:
            if lid != keep:
                laid[lid] = ("", None, None)
                blank[lid] = "the same clue as " + ", ".join(i for i in ids if i != lid)
    return laid, blank
