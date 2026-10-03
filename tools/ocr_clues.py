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
    words), and files the clue blank when nothing wins. vlm_pick() then
    shows each blank clue's readings to the desktop's VLM
    (tools/vlm_reader.py), when it answers.
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

#: A "See N" clue, which carries no words of its own.
SEE_RE = re.compile(r"^see\s+(\d+)", re.IGNORECASE)


# ------------------------------------------------------------ the readers

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
        # One thread: OpenMP's spinning threads take minutes over one crop
        # on a busy host, where a single thread takes seconds.
        res = subprocess.run([tesseract(), str(path), "-", "--psm", "4", *lang,
                              "-c", "tessedit_create_tsv=1"],
                             capture_output=True, text=True, timeout=300, check=False,
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


def read_words(img, which):
    """[(x0, y0, x1, y1, word)] reader `which` reads in the PIL image `img`,
    read at UPSCALE times its size, in `img`'s own pixels."""
    import numpy as np
    crop = img.convert("RGB")
    crop = crop.resize((crop.width * UPSCALE, crop.height * UPSCALE))
    if which in TESS_MODELS:
        res = [(((x0, y0), (x1, y1)), t, None)
               for x0, y0, x1, y1, t in tesseract_words(crop, TESS_MODELS[which])]
    else:
        res, _ = engine(which)(np.asarray(crop), use_cls=False)
    words = []
    for b, t, _ in res or ():
        xs, ys = [p[0] / UPSCALE for p in b], [p[1] / UPSCALE for p in b]
        words.append((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)), t))
    return words


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
                                             glued and theirs[j - 1] == BREAK) else inf
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
ONE_WAY = (("e", "c"),)


def misread(read, printed):
    """Whether `read` is `printed` with one ONE_WAY letter misread."""
    if len(read) != len(printed):
        return False
    diff = [(p, r) for p, r in zip(printed, read) if p != r]
    return len(diff) == 1 and diff[0] in ONE_WAY


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


def rejoin(theirs, low):
    """Another reading's tokens with a word it split joined again, when this
    clue's words (`low`) hold the joined word and it is a dictionary word: one
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
            if all(t.isalpha() for t in pieces) and apart and joined in low and is_word(joined):
                out.append("".join(pieces))
                k += parts[-1] + 1
                break
        else:
            out.append(theirs[k])
            k += 1
    return out


def agree(clue, others, keep_known=False):
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
    "he")."""
    if others and isinstance(others[0], str):
        others = [others]
    if not tokens(clue):
        return clue, "no words"
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
        if w == BREAK:
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
                    return None, f"readings differ: {w} / {' / '.join(got.values())}"
                else:
                    words_ = fits
        if words_ and keep_known and known(a) and i not in specked and words_[0] != a and not (
                len(got) == len(others) and all(v.lower() == words_[0] for v in got.values())):
            pick = a
        elif words_:
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
        elif len(a) > 2 and votes[a] == 1 and not known(a) and len(got) >= 2 and (
                max(votes.values()) * 2 > len(others) and max(votes, key=votes.get) != a
                and similar(a, max(votes, key=votes.get)) >= 0.7):
            # Most other readings agree on a spelling like this one's, which
            # no dictionary knows: "Jenkyns" where this reading has "Jcnkyns".
            pick = max(votes, key=votes.get)
            how = "settled by the readings"
        elif max(votes.values()) > 1 and votes[a] == 1 and len(a) > 3 and w[0].islower():
            return None, f"two readings agree on a non-word: {w} / {' / '.join(got.values())}"
        else:
            return None, (f"both read {w!r}, not a word" if votes[a] > 1
                          else f"readings differ: {w} / {' / '.join(got.values())}")
        slip = None if keep_known and pick == a else common_slip(pick)
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
        out += speckless(text[k:at]) + (add[0] + " " if add else "") + new
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


def clean(text):
    """A reading without OCR's specks: a not-sign read for the hyphen that
    breaks a word over a line end is the join, an asterisk or bullet beside
    a word is no part of it, and a comma or exclamation mark misread as a
    full stop or an I is put back."""
    text = re.sub(r"\s*[*•|]+(?=\s|$)", "", re.sub(r"(?<=[a-z])¬\s*(?=[a-z])", "", text))
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    # A pound sign in a word is an f the print's worn type turned ("o£").
    text = re.sub(r"\b[A-Za-z]*£[A-Za-z£]*",
                  lambda m: m.group(0).replace("£", "f") if is_word(m.group(0).replace("£", "f").lower())
                  else m.group(0), text)
    # A backslash inside a word is a letter the scan broke ("sal\\ age").
    text = re.sub(r"(?<=[a-z])\\\s?(?=[a-z])", "", text)
    # A clue's sentence never stops before a lower-case word: a full stop
    # there is a comma the print's low ink lost the tail of.
    text = re.sub(r"(?<=[a-z]{2})\.(?=\s+[a-z])", ",", text)
    # A one read as l or I before another digit ("l9th-century").
    text = re.sub(r"\b[lI](?=\d)", "1", text)
    # The space after a question or exclamation mark lost ("Worried?Pulse").
    text = re.sub(r"(?<=[a-z])([?!])(?=[A-Z][a-z])", r"\1 ", text)
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
    is the next clue's specks or start run on."""
    m = re.search(r"\s*\((\d{1,2}(?:\s*[,\-.]\s*\d{1,2})*)\)\W*\S", text or "")
    if m and enum and re.sub(r"\D+", ",", m.group(1)) == re.sub(r"\D+", ",", enum):
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
      - a last token with no word in it and a bracket the clue never opened
        ("0,6)", "S).") or a digit among symbols ("&%S4),").
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
        text = re.sub(rf"^(?:{word}|{word.capitalize()}|{word.upper()})\W+(?=[A-Z][a-z])", "", text)
    text = re.sub(r"\b([A-Za-z]+)-\s+(?=[^\w\s]|\d)[^\w\s]*\d?[^\w\s]*\s*([a-z]+)\b", line_end_hyphen, text)
    while "(" not in text:
        head, _, last = text.rpartition(" ")
        if not head or re.search(r"[A-Za-z]{2}", last) or not (
                ")" in last or (re.search(r"\d", last) and re.search(r"[&#@]", last))):
            break
        text = head.rstrip()
    return text


def reconcile(laid, streams, lengths=None, keep_known=False):
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
        if SEE_RE.match(text or ""):
            out[lid] = (text, enum, group)
            continue
        own = int(re.match(r"\d+", lid).group())
        text = trimmed(text, lid, voted=False)
        # A list counts up, so only a number above this clue's own can be
        # the next clue run on, and with the grid known, only one naming a
        # light: "Map 10 E" in 24 across is the clue's text.
        inside = next((m for m in re.finditer(r"\s(\d{1,2})\s+[A-Z]", text or "")
                       if int(m.group(1)) > own and (not lengths or any(
                           k.startswith(m.group(1) + "-") for k in lengths))), None)
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
        lead = re.match(r"(\d{1,2})\.? (?=[A-Z\"'])", text)
        if lead and lead.group(1) in lid.split("-")[0]:
            text = text[lead.end():]
        text = join_split(text, other)
        got, how = agree(text, other, keep_known)
        got = trimmed(cut_at_count(got, enum), lid)
        if got is not None and merged(got):
            got, how = None, merged(got)
        if got is None:
            blank[lid] = how
            out[lid] = ("", enum, group)
        else:
            out[lid] = (got, enum, group)
    return out, blank


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
JUNK = re.compile(JUNK_MARK.pattern + r"|(?<=[a-z])[£$]|[£$](?=[a-z])")


def doubled(text):
    """[(pair, why)] for a word printed again as the start of the next
    ("him himself", "re return"), the mark of one reading's word voted in
    beside another's. Clues print such pairs too ("in India"), so it judges
    only what a vote added."""
    ws = re.findall(r"[A-Za-z]+", text or "")
    return [(f"{a} {b}", "a word doubled into the next") for a, b in itertools.pairwise(ws)
            if len(a) >= 2 and len(b) - len(a) >= 3 and b.lower().startswith(a.lower())]


def suspect(text, vouched=()):
    """[(token, why)] for each word of a clue's text that OCR, not the setter,
    wrote. `vouched` holds lower-case words every reading spelt alike, which
    stand though the lexicon lacks them (a rare word, a name)."""
    out = []
    for raw in (text or "").split():
        s = raw.strip(EDGE)
        if not s:
            continue
        if DIGIT_IN_WORD.search(s) and not COUNTED.fullmatch(s.lstrip("£$")):
            out.append((raw, "a digit inside a word"))
            continue
        if MARK_IN_WORD.search(s) or JUNK.search(raw):
            out.append((raw, "a stray mark inside a word"))
            continue
        if any(re.search(r"[A-Za-z]", p) and re.search(r"\d", p) and not (
                COUNTED.fullmatch(p.lstrip("£$")) or re.fullmatch(r"[A-Z]+\d+[A-Z]*|\d+[A-Za-z]{1,2}", p))
               for p in re.split(r"[-/.'\u2019,]", s)):
            out.append((raw, "a digit inside a word"))
            continue
        for p in re.split(r"[-./&]", s.replace("\u2018", "'").replace("\u2019", "'")):
            bare = p.strip("'")
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
            if known(flat) or formed(plain(p).lower()):
                continue
            if flat.isupper() and len(flat) <= 4:
                continue  # an abbreviation: "RN", "TUC"
            if flat[0].islower():
                out.append((raw, "not a word"))
                break
            if slipped(flat):
                out.append((raw, "a word misread as a name"))
                break
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


def one_light_each(laid, blank, fits=()):
    """(laid, blank) with no clue on two lights. One printed clue read onto
    two lights (a reading's misread number, a lost one filled by position)
    has lost the other light's clue: it stays on the one light in `fits`
    (the lights whose printed count fills them) when exactly one of them is,
    and every other light it sits on is filed blank, to be read again."""
    from fetch_puzzle import duplicated_clues
    laid, blank = dict(laid), dict(blank)
    entries = [{"number": int(lid.split("-")[0]), "direction": lid.split("-")[1], "clue": {"text": t}}
               for lid, (t, _, _) in laid.items() if t]
    for ids in duplicated_clues(entries):
        keep = [lid for lid in ids if lid in fits]
        keep = keep[0] if len(keep) == 1 else None
        for lid in ids:
            if lid != keep:
                laid[lid] = ("", None, None)
                blank[lid] = "the same clue as " + ", ".join(i for i in ids if i != lid)
    return laid, blank
