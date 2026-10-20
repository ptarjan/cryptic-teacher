#!/usr/bin/env python3
"""A weak clue read again on spare CPU before the VLM is asked about it.

The desktop's VLM answers about 450 asks an hour, one at a time, while the CPU
sits idle. A clue the scan's readers leave blank or do not settle (file_archive_
org_puzzles.weak_lights) costs an ask. Before one is spent, this module reads
each such clue's printed lines again, line by line, with Tesseract run over
several preprocessings (scale, Otsu or adaptive binarisation, the tuned Times
model and the stock English one), and lets the variants vote:

  - a line is settled by the reading two variants of different preprocessing or
    model print alike (the 2-reader rule, OCR_CONFIRM, for one line);
  - a clue is settled when every line is, and the whole agrees with a reader the
    scan already has (`agrees_with_a_reader`), or one variant of each engine
    family (>= 2 models) printed every line alike.

The accepted text then goes through the same checks as the VLM's pick
(ocr_clues.held, trimmed): it fills the clue, and the ask is not made.
Each reading is cached under ~/.cache/archive_org_crops/retry, so the VLM
pass of the same page reads nothing twice. record() appends one row for every
clue the VLM answered to ~/.cache/corpus_queue/vlm_corpus.jsonl: the OCR's
readings next to the VLM's, the corpus this module's variants are measured on.
"""
import collections
import hashlib
import json
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ocr_clues

#: (name, Tesseract model, psm for a one-line crop, scale, binarisation). A crop
#: of a merged row (taller than TALL px) is read in psm 6.
VARIANTS = (("times7.s2.none", "times", 7, 2, "none"),
            ("times7.s2.otsu", "times", 7, 2, "otsu"),
            ("times7.s2.adapt", "times", 7, 2, "adapt"),
            ("eng7.s2.none", "eng", 7, 2, "none"),
            ("eng7.s2.otsu", "eng", 7, 2, "otsu"),
            ("eng7.s2.adapt", "eng", 7, 2, "adapt"),
            ("times7.s3.none", "times", 7, 3, "none"))
TALL = 36
#: Extra white round a line before it is read, and the page pixels kept either
#: side of a line's own box.
BORDER = 12
PAD_X, PAD_Y = 4, 2
#: The clue's lines at most: a longer run is the next clue's lines run in.
MAX_LINES = 4
#: Lines, sources that must print a line alike, and the fewest letters a clue has.
AGREE = 2
MIN_LETTERS = 6
THREADS = 2
CACHE_VERSION = hashlib.sha1(repr(VARIANTS).encode()).hexdigest()[:8]
CORPUS = Path(os.path.expanduser("~/.cache/corpus_queue/vlm_corpus.jsonl"))
RETRY_CACHE = Path(os.path.expanduser("~/.cache/archive_org_crops/retry"))


def enabled():
    """Whether the retry runs: opt-in (env CT_OCR_RETRY=1). Measured on 4 FT/Gale pages (40 asks) it
    filled 11 of 59 weak clues, every one as the VLM read it, but cleared no page's whole set of weak
    clues, so it spared no ask and only cost CPU; the corpus record() is on regardless."""
    return os.environ.get("CT_OCR_RETRY", "0") not in ("", "0")


def words_of(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def head_off(text):
    """A line's text without the clue number its first line opens on."""
    return re.sub(r"^[\dIlJ!|oO]{1,3}[.,:]?\s+", "", (text or "").strip())


def norm(text):
    return words_of(ocr_clues.clean(ocr_clues.strip_count(head_off(text))))


def clue_lines(cols, lid):
    """([(y0, y1, x0, x1, text)] printed lines of clue `lid` ("N-across"), reader) from the
    first reader of `cols` ({reader: [column: [line]]}) that has the clue's number, else
    ([], None). The clue runs from its number's line to the line that ends in a count or
    before the next number or heading."""
    n, direction = lid.split("-")
    for reader in ("ch", "en5", "times", "djvu"):
        columns = cols.get(reader)
        if not columns:
            continue
        seen = None
        for col in columns:
            got = []
            for line in col:
                m = re.match(r"\W*(across|down)\b", line[4], re.I)
                if m:
                    seen = m.group(1).lower()
                if not got:
                    if seen == direction and re.match(rf"\W*0?{n}\b", line[4]):
                        got.append(line)
                        if re.search(r"\)\W*$", line[4]):
                            break
                    continue
                if m or re.match(r"\W*\d{1,2}\b", line[4]) or len(got) >= MAX_LINES:
                    break
                got.append(line)
                if re.search(r"\)\W*$", line[4]):
                    break
            if got:
                return got, reader
    return [], None


def prepared(crop, scale, binar):
    import numpy as np
    from PIL import Image
    cv2 = ocr_clues.capped_cv2()
    g = crop.convert("L")
    g = g.resize((g.width * scale, g.height * scale), Image.LANCZOS)
    a = np.asarray(g)
    if binar == "otsu":
        _, a = cv2.threshold(a, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif binar == "adapt":
        a = cv2.adaptiveThreshold(a, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)
    out = Image.new("RGB", (a.shape[1] + 2 * BORDER, a.shape[0] + 2 * BORDER), "white")
    out.paste(Image.fromarray(a).convert("RGB"), (BORDER, BORDER))
    return out


def tesseract_text(img, psm, model):
    """What Tesseract reads in `img`, whitespace joined; the installed English model for
    "eng", the tuned Times one (ocr_clues.TESS_MODELS) for "times"."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "line.png"
        img.save(path)
        weights = ocr_clues.TESS_MODELS["times"] if model == "times" else None
        lang = ["--tessdata-dir", str(weights.parent), "-l", weights.stem] if weights else ["-l", "eng"]
        res = subprocess.run([ocr_clues.tesseract(), str(path), "-", "--psm", str(psm), *lang],
                             capture_output=True, encoding="utf-8", timeout=120, check=False,
                             env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    return " ".join(res.stdout.split()) if not res.returncode else ""


def read_line(page, line):
    """{variant name: text} of one printed line `line` (y0, y1, x0, x1, text) of the page image."""
    crop = page.crop((max(0, int(line[2]) - PAD_X), max(0, int(line[0]) - PAD_Y),
                      int(line[3]) + PAD_X, int(line[1]) + PAD_Y))
    tall = crop.height > TALL
    out = {}
    for name, model, psm, scale, binar in VARIANTS:
        try:
            out[name] = tesseract_text(prepared(crop, scale, binar), 6 if tall else psm, model)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            out[name] = ""
    return out


def vote_line(outs, first=False, last=False):
    """The text of one line that at least AGREE variants print alike (their letters and digits),
    the commonest spelling of it, or None. `first`: the clue's number leads it (dropped from
    the comparison); `last`: its count ends it."""
    seen = collections.defaultdict(list)
    for name, text in outs.items():
        t = head_off(text) if first else text
        key = words_of(ocr_clues.strip_count(t) if last else t)
        if key:
            seen[key].append(text)
    best = max(seen.values(), key=len, default=[])
    if len(best) < AGREE:
        return None
    return collections.Counter(best).most_common(1)[0][0]


def voted(lines_outs):
    """The clue the lines' variants settle, or None: `lines_outs` is [{variant: text}] per line."""
    parts = []
    for i, outs in enumerate(lines_outs):
        t = vote_line(outs, first=i == 0, last=i == len(lines_outs) - 1)
        if t is None:
            return None
        parts.append(t)
    text = ocr_clues.clean(ocr_clues.strip_count(head_off(" ".join(parts))))
    return text if len(words_of(text)) >= MIN_LETTERS else None


def agrees_with_a_reader(text, readings, mend=lambda t: t):
    """Whether `text` is, in its letters, a reading the scan's own readers print for the clue."""
    mine = words_of(mend(text))
    return bool(mine) and any(words_of(mend(ocr_clues.strip_count(r))) == mine for r in readings)


def accept(lines_outs, readings, mend=lambda t: t):
    """The clue to fill, or None: the lines' variants settle it (voted()), and a reader the
    scan has prints it too."""
    text = voted(lines_outs)
    if text is None or not agrees_with_a_reader(text, readings, mend):
        return None
    return text


def _cache_path(key):
    return RETRY_CACHE / f"{key}.{CACHE_VERSION}.json"


def _load(key):
    try:
        return json.loads(_cache_path(key).read_text())
    except (OSError, ValueError):
        return {}


def _save(key, data):
    path = _cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def retry(page, key, cols, lids, readings, mend=lambda t, lid: t):
    """{lid: text} each weak light of `lids` the variants settle. `page` is the page image,
    `key` the page's name for the cache, `cols` {reader: columns()}, `readings` {lid: [the
    scan readers' clue text]}; `mend(text, lid)` puts a reading as filed clues are."""
    if not enabled():
        return {}
    cached = _load(key)
    out, fresh = {}, False
    todo = []
    for lid in sorted(lids):
        if lid not in cached:
            lines, _ = clue_lines(cols, lid)
            cached[lid] = {"lines": [list(map(float, l[:4])) for l in lines], "outs": None}
            fresh = True
        todo.append(lid)
    jobs = [(lid, i, line) for lid in todo if cached[lid]["outs"] is None
            for i, line in enumerate(cached[lid]["lines"])]
    if jobs:
        with ThreadPoolExecutor(THREADS) as pool:
            got = list(pool.map(lambda j: read_line(page, j[2]), jobs))
        for lid in {j[0] for j in jobs}:
            cached[lid]["outs"] = [g for (l, _, _), g in zip(jobs, got) if l == lid]
        fresh = True
    if fresh:
        _save(key, cached)
    for lid in todo:
        outs = cached[lid]["outs"]
        if not outs:
            continue
        text = accept(outs, readings.get(lid, ()), lambda t, lid=lid: mend(t, lid))
        if text:
            out[lid] = text
    return out


def record(key, lid, box, readings, vlm, matched, path=None):
    """Append one corpus row ({page, clue, box, ocr readings, vlm answer, readers that matched})
    to the VLM corpus: one os.write, so concurrent queue children never interleave a row."""
    path = Path(path or CORPUS)
    row = json.dumps({"page": key, "clue": lid, "box": box, "ocr": readings, "vlm": vlm, "matched": matched},
                     ensure_ascii=False) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, row.encode())
        finally:
            os.close(fd)
    except OSError:
        pass
