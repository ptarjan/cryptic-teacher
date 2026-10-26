"""The solution-grid reader's recogniser outputs, kept on disk by what they are of.

trove_solution_ocr.read_lights runs RapidOCR's word recogniser ~500 times a lattice (each light
in each rendering by each model): ~65 of the ~95 CPU-s of a Times solution grid's read, and the
ONNX sessions' load is ~5 s more. file_archive_org_puzzles.solved() keeps whole readings by the
reader's code (_SOLVED_CODE), so each reader fix pushed (several a day) read every grid again:
the same 1970-05-28 edition's answers-only reread took 15 s on 10-25 and 137 s on 10-26.

Here each recogniser call's (word, probabilities) is kept by its input: the light's raw cell crops
(their bytes, shapes and dtypes), the rendering (VARIANTS index) and the model (index), under an
engine version (version(): the model files' sha256, onnxruntime's version, and the code of
read_word, word_image and VARIANTS). A reader fix that cuts the same cells reads them off disk;
one that cuts others reads only those. The decision logic above (sure letters, matching, the
rules, the classifier) runs on every read, so no reading changes: the same input gives the same
recogniser output, kept exactly (its probabilities are float32 values, kept as float32).

The outputs one crop read needs are kept in one file, CROP_CACHE/<sha256 of the crop file>.json.z
(crop_scope), written atomically (a part file renamed over it): many units read at once.
A transport of results, not a reader: code_reach leaves this module out of every key
(code_reach.TRANSPORT), so solution_key() and _SOLVED_CODE do not move for an edit here."""
import base64
import hashlib
import json
import os
import threading
import zlib
from contextlib import contextmanager
from pathlib import Path

import numpy as np

#: Where the per-crop files are kept (under the crops file_archive_org_puzzles.CROPS names).
CROP_CACHE = Path(os.path.expanduser("~/.cache/archive_org_crops")) / "grid_ocr"
#: A crop's file keeps the outputs read before alongside this read's up to this many; past it,
#: only this read's (a reader that cuts the cells otherwise leaves the old ones unused).
KEPT_MAX = 8000

#: {key: (word, (probability, ...))}: every output read or loaded this process, by its input.
_MEMO = {}
#: {tuple(model paths): version()}.
_VERSIONS = {}
_LOCAL = threading.local()
#: Lookups this process (hits, misses), for the stage log.
COUNTS = {"hit": 0, "miss": 0}


def version(models):
    """A hash of what a recogniser output depends on beyond its input: the model files `models`
    (their sha256), onnxruntime's version, and trove_solution_ocr's read_word, word_image and
    VARIANTS (code_reach)."""
    k = tuple(os.fspath(m) for m in models)
    got = _VERSIONS.get(k)
    if got is None:
        import importlib.metadata
        import code_reach
        try:
            ort = importlib.metadata.version("onnxruntime")
        except importlib.metadata.PackageNotFoundError:
            ort = None
        code = code_reach.key("trove_solution_ocr", {"read_word", "word_image", "VARIANTS"})
        sums = [[Path(m).name, hashlib.sha256(Path(m).read_bytes()).hexdigest()] for m in models]
        got = _VERSIONS[k] = hashlib.sha256(json.dumps([code, ort, sums]).encode()).hexdigest()[:16]
    return got


def recognised(crops, variant, model, models, read):
    """(word, [probabilities]) of recogniser `model` (index into `models`, the model files) on
    rendering `variant` (index) of the light whose cell images are `crops`: kept, else read()."""
    h = hashlib.blake2b(digest_size=16)
    h.update(f"{version(models)}:{variant}:{model}".encode())
    for x in crops:
        a = np.ascontiguousarray(x)
        h.update(f"|{a.dtype.str}{a.shape}".encode())
        h.update(a.tobytes())
    k = h.hexdigest()
    got = _MEMO.get(k)
    if got is None:
        word, probs = read()
        got = (word, tuple(probs))
        _MEMO[k] = got
        COUNTS["miss"] += 1
    else:
        COUNTS["hit"] += 1
    touched = getattr(_LOCAL, "touched", None)
    if touched is not None:
        touched[k] = got
    return got[0], list(got[1])


def _pack(got):
    word, probs = got
    a = np.asarray(probs, dtype=np.float32)
    # Kept only where float32 holds each probability exactly (read_word's are float32 values).
    if any(float(x) != p for x, p in zip(a, probs)):
        return None
    return [word, base64.b64encode(a.tobytes()).decode()]


def _unpack(v):
    word, b = v
    return word, tuple(float(x) for x in np.frombuffer(base64.b64decode(b), dtype=np.float32))


def _load(path):
    try:
        return json.loads(zlib.decompress(path.read_bytes()))
    except (OSError, ValueError, zlib.error):
        return {}


@contextmanager
def crop_scope(image):
    """Within it, the recogniser outputs read off solution-grid crop file `image` are loaded
    from, and the new ones written to, its file under CROP_CACHE. A nested scope (read_answers
    around read_framed) is the outer one's; an image that is no file is read with no file."""
    if getattr(_LOCAL, "touched", None) is not None or not isinstance(image, (str, os.PathLike)):
        yield
        return
    try:
        name = hashlib.sha256(Path(image).read_bytes()).hexdigest()[:32]
    except OSError:
        yield
        return
    path = CROP_CACHE / f"{name}.json.z"
    kept = _load(path)
    for k, v in kept.items():
        if k not in _MEMO:
            try:
                _MEMO[k] = _unpack(v)
            except (ValueError, TypeError):
                continue
    _LOCAL.touched = touched = {}
    try:
        yield
    finally:
        _LOCAL.touched = None
        new = {k: p for k, got in touched.items() if k not in kept and (p := _pack(got)) is not None}
        if new:
            out = {**kept, **new} if len(kept) + len(new) <= KEPT_MAX else \
                {k: p for k, got in touched.items() if (p := _pack(got)) is not None}
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.part")
                tmp.write_bytes(zlib.compress(json.dumps(out, separators=(",", ":")).encode(), 6))
                tmp.replace(path)
            except OSError:
                pass
