#!/usr/bin/env python3
"""The archive.org filer's editions, and the clue OCR, read on Paul's desktop over ssh.

    OCR_REMOTE=micro@100.68.145.15,micro@192.168.1.198 python3 tools/file_archive_org_puzzles.py ...
    python3 tools/ocr_remote.py check        # read one crop both ways

The Mac mini has 4 cores; the desktop has 28. With OCR_REMOTE set, each
process holds one ssh session to `python ocr_remote.py serve` on the first
host that answers. tools/file_archive_org_puzzles.py's read_edition sends it
a whole edition (its leaves, djvu text, the solution leaves it reads, its
cached readings and the series' filed dates, as a tar) and gets back the
verdicts, the puzzles and the crops it cached; any other reader sends one
already-upscaled crop as PNG and gets the words back as JSON. call() runs
one of CALLS there: an image PDF's pages searched for grids
(fetch_archive_org_editions.pdf_pages), a grid search from a clue list
(reconstruct(), the Trove filer's rebuild), an edition's scan for its
headings (scan(), the edition queue's scan units), RapidOCR's text of a
Trove article's clue zones (tools/trove_clue_ocr.py's read_text) and a
saved Gale page's match (tools/gale_inbox.py's match_anywhere), a saved
Listener page's whole read (tools/gale_listener.py's read_remote) and its
grids (tools/file_gale_listener.py's page_grids). The desktop
runs the same code (every tracked file under tools/ but UNSHIPPED, shipped
once into a directory named by their hash, so a running session's files are
never overwritten), the same reader models and the same Python, Pillow,
libjpeg-turbo, numpy, OpenCV, tesseract and onnxruntime builds: the session
is used only when the versions it reports are this host's, so a reading is
the same whichever host made it. An edition whose read there opens a file
that was not shipped, or crashes, is read here instead, the reason logged.

When no host answers, or one stops answering mid-read, the reason is logged
and this process reads locally, trying the desktop again after RETRY
seconds: a desktop that is off slows a run down and never stops or hangs it.
While Paul games on it (tools/desktop_busy.py) no session is opened, an open
one is closed before its next read and one waiting on a read is abandoned
(the probe ends the desktop's side): this process reads locally until the
desktop is idle again, unless it defers (OCR_REMOTE_DEFER set, as the edition
queue sets it for its scan and read units): then the read raises DesktopBusy,
and the unit ends deferred, to be run again once the desktop is idle.

Whatever is read here while OCR_REMOTE is set holds one of LOCAL_SLOTS
host-wide slots (local_slot()): the full pass runs 20 workers for the
desktop, and 20 reading here at once (the desktop off or gaming) put the
4-core host at load 20-40.

Desktop layout (C:\\Users\\micro\\ocrw): venv/ (the pinned Python packages),
tess/ (conda-forge tesseract, micromamba), v-<code hash>/tools/ (shipped here);
the reader models outside the code (en_PP-OCRv5_rec_mobile, en_PP-OCRv3_rec)
in C:\\Users\\micro\\.cache\\rapidocr, as here in ~/.cache/rapidocr.
"""
import contextlib
import hashlib
import json
import os
import random
import select
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import desktop_busy
from desktop_busy import SSH

#: The desktop's directory.
HOME = r"C:\Users\micro\ocrw"
#: Seconds to wait for a session to say it is ready, for one crop and for
#: one edition.
CONNECT_TIMEOUT = 60
READ_TIMEOUT = 300
EDITION_TIMEOUT = 1800
#: A grid search (Session.reconstruct) has no fixed answer time: the node
#: budget bounds it, not the clock, and on a desktop shared with the OCR pass
#: (turbo off) a search the Mac finishes in 140s can run past 300. So serve()
#: says {"searching": true} every SEARCH_HEARTBEAT seconds while one runs, and
#: the Mac calls the desktop lost after SEARCH_SILENCE seconds with no line,
#: not after a total; SEARCH_TIMEOUT is only the ceiling for a search that
#: keeps beating without ending.
SEARCH_HEARTBEAT = 30
SEARCH_SILENCE = 4 * SEARCH_HEARTBEAT
SEARCH_TIMEOUT = EDITION_TIMEOUT
#: tools/data's directories no reader opens, left off the desktop (160 MB).
UNSHIPPED = ("tools/data/blog_facts/", "tools/data/yt_solvers/")
#: The list of shipped files, in the desktop's directory, written last.
MANIFEST = "tools/shipped.txt"
#: Seconds before a process that lost the desktop tries it again.
RETRY = 600
#: Grid searches a job runs on the desktop at once, each thread over its own
#: session (tools/acquire_book.py's books, tools/times_grids.py's posts).
SEARCH_SLOTS = 8
#: Reads made here at once, host-wide, while OCR_REMOTE is set (local_slot):
#: a third of the cores, so a desktop away for hours (a game) leaves the
#: rest to the burn and the host's own work.
LOCAL_SLOTS = int(os.environ.get("OCR_LOCAL_SLOTS") or max(1, (os.cpu_count() or 3) // 3))


def shipped():
    """{repo path: file} of what the desktop needs from this checkout: git's
    tracked files under tools/ but UNSHIPPED, or on the desktop, MANIFEST's."""
    root = TOOLS.parent
    manifest = root / MANIFEST
    if manifest.exists():
        names = manifest.read_text().split("\n")
    else:
        names = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "tools"], capture_output=True,
                               text=True, check=True).stdout.split("\0")
    return {n: root / n for n in sorted(filter(None, names))
            if not n.startswith(UNSHIPPED) and n != MANIFEST and (root / n).is_file()}


#: Where code_hash() and versions() are kept for each clean commit of the
#: tree (kept()): hashing the shipped files reads 45 MB, and versions()
#: loads the readers' packages, in every process that opens a session.
KEPT = Path.home() / ".cache" / "ocr_remote"


def tree_commit():
    """The commit the shipped files are, or None: on the desktop (MANIFEST,
    no git) or with a file under tools/ changed from it."""
    root = TOOLS.parent
    if (root / MANIFEST).exists():
        return None
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
        clean = subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--", "tools"],
                               capture_output=True, check=False).returncode == 0
    except (OSError, subprocess.CalledProcessError):
        return None
    return head if clean else None


def kept(name, key_of, compute):
    """compute(), kept under KEPT by key_of() (None: made afresh, kept
    nowhere); kept only when key_of() still gives that key after it, so a
    tree that moved meanwhile keeps nothing under the old commit."""
    key = key_of()
    if key is None:
        return compute()
    path = KEPT / f"{name}-{key}.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    value = compute()
    if key_of() == key:
        KEPT.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.part")
        tmp.write_text(json.dumps(value))
        tmp.replace(path)
    return value


def hash_of(files):
    """The hash of `files` ({repo path: file}): the desktop directory they live in."""
    h = hashlib.sha1()
    for name, path in sorted(files.items()):
        h.update(name.encode() + b"\0" + path.read_bytes())
    return h.hexdigest()[:12]


def code_hash():
    """hash_of(shipped())."""
    return kept("code", tree_commit, lambda: hash_of(shipped()))


def code_dir():
    """The desktop directory of the code this process compares (versions()'s
    "code", once connect() read it): a process whose checkout moved on keeps
    to the code it loaded, rather than asking a newer one."""
    return rf"{HOME}\v-{_VERSIONS.get('local', {}).get('code') or code_hash()}"


def models():
    """{name: file} of each reader model outside the shipped code: a reader
    skips one that is missing, so a host without it reads otherwise."""
    import ocr_clues
    import trove_solution_ocr
    out = {which: model for which, model in ocr_clues.READERS.items() if isinstance(model, Path)}
    out.update((f"solution {m.name}", m) for m in trove_solution_ocr.EXTRA_MODELS)
    return out


def versions():
    """What decides a reading here: Python's minor version, the image and
    reader packages, tesseract's build, the shipped code's hash and each
    reader model's. Kept (kept()) by the tree's commit and what else they
    are read from: the package directories', tesseract's and each model's
    file stamps."""
    return kept("versions", versions_key, read_versions)


def versions_key():
    """versions()'s key, or None (made afresh): the tree's commit
    (tree_commit) with this Python, its package directories' mtimes (an
    install or upgrade adds or renames an entry), tesseract's and each
    model's stamp."""
    head = tree_commit()
    if head is None:
        return None
    import shutil

    import ocr_clues

    def stamp(path):
        try:
            st = os.stat(path)
        except (OSError, TypeError):
            return None
        return [str(path), st.st_size, st.st_mtime_ns]
    parts = [head, sys.version, sys.executable]
    parts += [stamp(p) for p in sys.path if p.endswith("-packages")]
    parts.append(stamp(shutil.which("tesseract") or ocr_clues.TESSERACT))
    parts += [stamp(m) for _, m in sorted(models().items())]
    return hashlib.sha1(json.dumps(parts).encode()).hexdigest()[:16]


def read_versions():
    """versions() read afresh."""
    from importlib.metadata import version

    import cv2
    import numpy
    import onnxruntime
    import PIL
    from PIL import features

    import ocr_clues
    tess = subprocess.run([ocr_clues.tesseract(), "--version"], capture_output=True, text=True, check=False)
    out = {"tesseract": (tess.stdout or tess.stderr).splitlines()[0].strip(),
           "onnxruntime": onnxruntime.__version__, "rapidocr": version("rapidocr_onnxruntime"),
           "numpy": numpy.__version__, "cv2": cv2.__version__, "pillow": PIL.__version__,
           "libjpeg_turbo": features.version("libjpeg_turbo"), "pypdf": version("pypdf"), "python": f"{sys.version_info[0]}.{sys.version_info[1]}",
           "code": code_hash()}
    for which, model in models().items():
        out[which] = hashlib.sha1(model.read_bytes()).hexdigest() if model.exists() else None
    return out


# ------------------------------------------------------------ the desktop side


#: The Windows priority class a session's server runs at, by the
#: OCR_REMOTE_PRIORITY its Mac process sets: idle for reads, below normal
#: (still under a game's normal) for the edition queue's scans, so a
#: scan's title OCR is not starved by the 20 reads beside it.
PRIORITIES = {"idle": 0x40, "scan": 0x4000}


def full_speed(priority="idle"):
    """Opt this process out of Windows power throttling (EcoQoS), at
    `priority` (PRIORITIES): a windowless process started by sshd counts as
    background, and Windows
    keeps those on the efficiency cores."""
    import ctypes

    class State(ctypes.Structure):
        _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]
    # PROCESS_POWER_THROTTLING_CURRENT_VERSION, _EXECUTION_SPEED on, state
    # off: ProcessPowerThrottling (4).
    state = State(1, 1, 0)
    k32 = ctypes.windll.kernel32
    # A HANDLE is 64 bits: ctypes' default int return truncates it.
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    if not k32.SetProcessInformation(k32.GetCurrentProcess(), 4, ctypes.byref(state), ctypes.sizeof(state)):
        print(f"SetProcessInformation failed: {ctypes.GetLastError()}", file=sys.stderr, flush=True)
    # Idle or below normal, which tesseract inherits: the box is Paul's, and a game
    # on it must keep its frames.
    k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    if not k32.SetPriorityClass(k32.GetCurrentProcess(), PRIORITIES.get(priority, PRIORITIES["idle"])):
        print(f"SetPriorityClass failed: {ctypes.GetLastError()}", file=sys.stderr, flush=True)


#: While an edition is read: (the roots whose files it must have been
#: sent, [each such file it opened that is not there]).
_WATCH = [None, []]


def _audit(event, args):
    """Notes each read of a missing file under _WATCH's roots."""
    if event != "open" or _WATCH[0] is None or not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    mode, flags = args[1], args[2] or 0
    if (mode and any(c in mode for c in "wax+")) or (mode is None and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)):
        return
    path = os.path.abspath(os.fsdecode(args[0]))
    if path.startswith(_WATCH[0]) and "__pycache__" not in path and not os.path.exists(path):
        _WATCH[1].append(path)


def read_edition_here(req, blob, ask_mac):
    """({"results", "vlm"}, tar of the crops it wrote) of the edition `req`
    describes, its files in the tar `blob`, read by read_edition; or
    ({"error"}, b"") when the read opened a file it was not sent or a title
    crashed, so the Mac reads it itself. The VLM is the Mac's, asked through
    `ask_mac(head, png)`: its answers are cached there, keyed by the PNG
    that host makes (vlm_reader.png), so this one sends those bytes when it
    can make them (vlm_reader.png_as, "png" in the ask) and the Mac does no
    image work, else a PNG the Mac re-encodes."""
    import datetime
    import gc
    import io
    import tarfile

    import file_archive_org_puzzles as fa
    import vlm_reader
    up = [req["vlm"]]

    def ask(img, prompt, max_tokens=1500):
        data = vlm_reader.png_as(img, req.get("png"))
        theirs = data is not None
        if not theirs:
            buf = io.BytesIO()
            img.save(buf, format="PNG", compress_level=1)  # lossless: the Mac decodes these pixels
            data = buf.getvalue()
        got = ask_mac({"ask": prompt, "max_tokens": max_tokens, "png": theirs}, data)
        if "error" in got:
            up[0] = False
            raise RuntimeError(got["error"])
        return got["text"]
    vlm_reader.ask, vlm_reader.reachable = ask, lambda: up[0]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            tar.extractall(root, filter="data")
        crops, sent = sent_crops(root)
        held = {series: fa.Held({int(n): datetime.date.fromisoformat(day) for n, day in dates.items()})
                for series, dates in req["held"].items()}
        fa.CROPS = crops
        fa.held_dates = held.__getitem__
        reprints = req.get("reprints") or {}
        fa.reprint_readings = lambda number, series=None: reprints.get(str(number), {})
        fa.set_solutions({int(n): {**sol, "dir": root / "ed" / sol["dir"]} for n, sol in req["solutions"].items()})
        filing = req.get("filing")
        if filing:
            scans = {}
            for url, day, numbers in filing["scans"]:
                scans[(url, day)] = numbers
            fa.held_scans = lambda series: scans
        _WATCH[:] = [(str(root), str(TOOLS.parent)), []]
        try:
            results, vlm_ok = fa.read_edition(root / "ed" / req["edition"], req["found"])
            decided = decide_here(results, filing, root / "filing") if filing else None
        finally:
            missing, _WATCH[:] = _WATCH[1], [None, []]
        gc.collect()  # closes the leaves' files, which Windows will not delete open
        if missing:
            return {"error": "opened files it was not sent: " + ", ".join(sorted(set(missing))[:5])}, b""
        crashed = [v["refused"] for v, _ in results if str(v.get("refused", "")).startswith("crashed")]
        if crashed:
            return {"error": f"a title crashed there: {crashed[0]}"}, b""
        return {"results": results, "vlm": vlm_ok, "decided": decided}, changed(crops, sent)


def sent_crops(root):
    """(the crops directory under `root`, {file: bytes} of those the Mac sent)."""
    crops = root / "crops"
    crops.mkdir(exist_ok=True)
    return crops, {p: p.read_bytes() for p in crops.rglob("*") if p.is_file()}


def changed(crops, sent):
    """A tar of the files under `crops` written since `sent`, for the Mac to
    extract under its CROPS."""
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for p in sorted(crops.rglob("*")):
            if p.is_file() and sent.get(p) != p.read_bytes():
                tar.add(p, arcname=p.relative_to(crops).as_posix())
    return buf.getvalue()


def _scan_there(data, rel):
    """(file_archive_org_puzzles._scan of edition `rel`, a tar of the title
    readings it cached), its files and cached readings in the tar `data`
    (scan_request); raises when it opened a file it was not sent."""
    import gc
    import io
    import tarfile

    import file_archive_org_puzzles as fa
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(root, filter="data")
        crops, sent = sent_crops(root)
        fa.CROPS = crops
        _WATCH[:] = [(str(root), str(TOOLS.parent)), []]
        try:
            found = fa._scan(root / "ed" / rel)
        finally:
            missing, _WATCH[:] = _WATCH[1], [None, []]
        gc.collect()  # closes the leaves' files, which Windows will not delete open
        if missing:
            raise FileNotFoundError("opened files it was not sent: " + ", ".join(sorted(set(missing))[:5]))
        return found, changed(crops, sent)


def decide_here(results, filing, root):
    """[(verdict, writes [(where, puzzle)])] of each title decided
    (file_archive_org_puzzles.decide) against the Mac's files `filing` sent
    under `root`, each write assumed to land; or None when a title looked up
    a file the Mac did not say it has or lacks, so the Mac decides itself.
    Decided on copies: `results` stays the readings."""
    import copy

    import file_archive_org_puzzles as fa
    # The files are read with the host's default encoding (cp1252 on
    # Windows): as \u escapes they read the same as the Mac's UTF-8.
    for f in root.rglob("*.json"):
        f.write_text(json.dumps(json.loads(f.read_bytes().decode("utf-8")), indent=1))
    asked = {tuple(w) for w in filing["asked"]}
    looked = set()

    def path(where, series, puzzles):
        looked.add(tuple(where))
        return fa.filer_path(where, series, puzzles, root)
    out = []
    for verdict, puzzle in copy.deepcopy(results):
        writes = []

        def record(where, puzzle, verdict, writes=writes):
            writes.append((where, json.loads(json.dumps(puzzle))))
            if where is not None:
                target = path(where, None, None)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(puzzle))
            return True
        fa.decide(verdict, puzzle, filing["series"], filing["puzzles"], set(filing["held"]), record, path)
        out.append((verdict, writes))
    return out if looked <= asked else None


def _reconstruct_there(data, spec, **kw):
    import reconstruct_grid
    return reconstruct_grid.reconstruct([tuple(t) for t in spec], **kw), b""


def _pdf_pages_there(data):
    import fetch_archive_org_editions
    return fetch_archive_org_editions.pdf_pages(data)


def _trove_text_there(data, sizes):
    """tools/trove_clue_ocr.py's read_text of the zone PNGs `data` holds, one after another, `sizes` long."""
    import io

    import trove_clue_ocr
    images, at = [], 0
    for n in sizes:
        images.append(io.BytesIO(data[at:at + n]))
        at += n
    return trove_clue_ocr.read_here(images), b""


#: What call() may run there: name -> f(payload bytes, *args, **kwargs)
#: giving (a JSON-able result, bytes sent back after it), or "module.f",
#: imported there when it runs: a module the page build need not import.
CALLS = {"reconstruct": _reconstruct_there, "pdf_pages": _pdf_pages_there, "scan": _scan_there,
         "trove_text": _trove_text_there, "gale_match": "gale_inbox.match_there",
         "listener_read": "gale_listener.read_there", "listener_grids": "file_gale_listener.grids_there"}


def run_call(name, data, args, kwargs):
    """CALLS[name](data, *args, **kwargs)."""
    f = CALLS[name]
    if isinstance(f, str):
        import importlib
        module, attr = f.rsplit(".", 1)
        f = getattr(importlib.import_module(module), attr)
    return f(data, *args, **kwargs)


def serve(priority="idle"):
    """Read crops and editions on stdin, words and verdicts on stdout: after a
    "ready" line with versions(), each request is a JSON line {"which",
    "bytes"} and that many bytes of PNG, answered by a JSON line {"words"},
    or a line {"edition", ..., "bytes"} and that many bytes of tar
    (Session.edition), answered by a line {"results", "vlm", "bytes"} and
    that many bytes of tar, or a line {"reconstruct": job, "bytes": 0}
    answered by tools/acquire_book.py's _reconstruct_one(job) as a line, or
    a line {"call", "args", "kwargs", "bytes"} and that many bytes, answered
    by a line {"result", "bytes"} and that many bytes (CALLS); any can be
    answered by {"error"}."""
    os.environ["PATH"] = str(Path(HOME) / "tess" / "Library" / "bin") + os.pathsep + os.environ["PATH"]
    full_speed(priority)
    # The full pass's 20 sessions share the 28-thread box: two threads each.
    os.environ.setdefault("OCR_THREADS", "2")
    import io

    from PIL import Image

    import ocr_clues
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    said = threading.Lock()  # a search's heartbeat thread says lines too

    def say(obj):
        with said:
            out.write(json.dumps(obj).encode() + b"\n")
            out.flush()
    def ask_mac(head, data):
        out.write(json.dumps({**head, "bytes": len(data)}).encode() + b"\n" + data)
        out.flush()
        return json.loads(inp.readline())
    say({"ready": versions()})
    sys.addaudithook(_audit)
    while True:
        line = inp.readline()
        if not line:
            return
        req = json.loads(line)
        data = inp.read(req["bytes"])
        if "reconstruct" in req:
            done = threading.Event()

            def beat():
                while not done.wait(SEARCH_HEARTBEAT):
                    say({"searching": True})
            beating = threading.Thread(target=beat, daemon=True)
            beating.start()
            try:
                import acquire_book
                got = acquire_book._reconstruct_one(req["reconstruct"])
            except Exception as e:  # noqa: BLE001 -- the Mac searches this one itself and says why
                got = {"error": f"{type(e).__name__}: {e}"}
            done.set()
            beating.join()
            say(got)
            continue
        if "call" in req:
            try:
                result, back = run_call(req["call"], data, req["args"], req["kwargs"])
                head = {"result": result}
            except Exception as e:  # noqa: BLE001 -- the Mac runs this one itself and says why
                head, back = {"error": f"{type(e).__name__}: {e}"}, b""
            out.write(json.dumps({**head, "bytes": len(back)}).encode() + b"\n" + back)
            out.flush()
            continue
        if "edition" in req:
            try:
                head, back = read_edition_here(req, data, ask_mac)
            except Exception as e:  # noqa: BLE001 -- the Mac reads this edition itself and says why
                head, back = {"error": f"{type(e).__name__}: {e}"}, b""
            out.write(json.dumps({**head, "bytes": len(back)}).encode() + b"\n" + back)
            out.flush()
            continue
        try:
            words = ocr_clues.raw_words(Image.open(io.BytesIO(data)), req["which"])
            say({"words": [[float(x0), float(y0), float(x1), float(y1), t] for x0, y0, x1, y1, t in words]})
        except Exception as e:  # noqa: BLE001 -- the Mac reads this crop itself and says why
            say({"error": f"{type(e).__name__}: {e}"})


# ------------------------------------------------------------ the Mac side


def priority():
    """This process's sessions' priority on the desktop (PRIORITIES)."""
    p = os.environ.get("OCR_REMOTE_PRIORITY") or "idle"
    return p if p in PRIORITIES else "idle"


class Unavailable(Exception):
    pass


#: Set (to anything) in a process whose desktop reads are not made here
#: while the desktop is busy: it raises DesktopBusy instead.
DEFER = "OCR_REMOTE_DEFER"


class DesktopBusy(BaseException):
    """The desktop is busy (why) and this process defers (DEFER). Not an
    Exception, so no `except Exception` on its way out records it as the
    read's failure."""


def defer_when_busy():
    """Raise DesktopBusy, in this process and those it starts, rather than
    read here while the desktop is busy."""
    os.environ[DEFER] = "1"


def _busy_here(why):
    """Raise DesktopBusy(why) when the desktop is busy and this process defers."""
    if why and os.environ.get(DEFER):
        raise DesktopBusy(why)


class Session:
    """One ssh session to a desktop's server, owned by one process."""

    def __init__(self, host):
        self.host = host
        self.err = tempfile.TemporaryFile()  # noqa: SIM115 -- ssh writes to it for the session's life
        serve = rf"{HOME}\venv\Scripts\python.exe {code_dir()}\tools\ocr_remote.py serve {priority()}"
        self.proc = subprocess.Popen([*SSH, host, serve], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.err)
        self.buf = b""
        try:
            self.ready = self.answer(CONNECT_TIMEOUT).get("ready")
        except Unavailable:
            self.close()
            raise
        if self.ready is None:
            self.close()
            raise Unavailable("no ready line")

    def answer(self, timeout):
        end = time.monotonic() + timeout
        fd = self.proc.stdout.fileno()
        while b"\n" not in self.buf:
            left = end - time.monotonic()
            if left <= 0:
                raise Unavailable(f"no answer in {timeout}s")
            if not select.select([fd], [], [], min(left, desktop_busy.PROBE_EVERY))[0]:
                why = desktop_busy.busy([self.host])
                if why:
                    raise Unavailable(f"desktop busy: {why}")
                continue
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                self.err.seek(0)
                try:
                    rc = self.proc.wait(5)
                except subprocess.TimeoutExpired:
                    rc = None
                raise Unavailable(f"ssh exited ({rc}): "
                                  f"{self.err.read().decode(errors='replace').strip()[-300:]}")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line)

    def payload(self, n, timeout):
        """The `n` bytes that follow an answer line."""
        end = time.monotonic() + timeout
        fd = self.proc.stdout.fileno()
        got = bytearray(self.buf)  # grown in place: a pipe read is ~64 KB, a page's PNG MBs
        while len(got) < n:
            left = end - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                raise Unavailable(f"no answer in {timeout}s")
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                raise Unavailable("ssh exited mid-answer")
            got += chunk
        data, self.buf = bytes(got[:n]), bytes(got[n:])
        return data

    def send(self, head, data):
        try:
            self.proc.stdin.write(json.dumps({**head, "bytes": len(data)}).encode() + b"\n" + data)
            self.proc.stdin.flush()
        except OSError as e:
            raise Unavailable(f"cannot send: {e}") from e

    def read(self, png, which):
        self.send({"which": which}, png)
        return self.answer(READ_TIMEOUT)

    def reconstruct(self, job):
        """tools/acquire_book.py's _reconstruct_one(job), run there, waited on
        for as long as the desktop says it is still searching (SEARCH_SILENCE)
        and is not busy."""
        self.send({"reconstruct": job}, b"")
        end = time.monotonic() + SEARCH_TIMEOUT
        while True:
            left = int(end - time.monotonic())
            if left <= 0:
                raise Unavailable(f"still searching after {SEARCH_TIMEOUT}s")
            got = self.answer(min(SEARCH_SILENCE, left))
            if not got.get("searching"):
                return got
            why = desktop_busy.busy([self.host])
            if why:
                raise Unavailable(f"desktop busy: {why}")

    def call(self, name, args, kwargs, data):
        """(answer, the bytes after it) of CALLS[name] run there."""
        self.send({"call": name, "args": args, "kwargs": kwargs}, data)
        got = self.answer(EDITION_TIMEOUT)
        return got, self.payload(got.get("bytes", 0), EDITION_TIMEOUT)

    def edition(self, head, tar):
        """(answer, tar of crops) for an edition (read_edition_here), asking
        this host's VLM what the desktop asks it meanwhile."""
        import io

        from PIL import Image

        import vlm_reader
        self.send(head, tar)
        while True:
            got = self.answer(EDITION_TIMEOUT)
            data = self.payload(got.get("bytes", 0), EDITION_TIMEOUT)
            if "ask" not in got:
                return got, data
            try:
                if got.get("png"):  # this host's png() bytes: no image work here
                    reply = {"text": vlm_reader.ask_png(data, got["ask"], got["max_tokens"])}
                else:
                    reply = {"text": vlm_reader.ask(Image.open(io.BytesIO(data)), got["ask"], got["max_tokens"])}
            except RuntimeError as e:
                reply = {"error": str(e)}
            try:
                self.proc.stdin.write(json.dumps(reply).encode() + b"\n")
                self.proc.stdin.flush()
            except OSError as e:
                raise Unavailable(f"cannot send: {e}") from e

    def close(self):
        try:
            self.proc.kill()
            self.proc.wait(5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def ship(host):
    """Copy shipped() to the desktop, over ssh as a tar stream, into a fresh
    directory renamed to v-<its hash> once whole: a session reads only a
    complete copy, and none is ever written over (Windows refuses opening a
    file another process is replacing). A name already there is kept and
    the new copy dropped."""
    import io
    import tarfile
    files = shipped()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, path in files.items():
            tar.add(path, arcname=name)
        listing = "\n".join(files).encode()
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(listing)
        tar.addfile(info, io.BytesIO(listing))
    res = subprocess.run([*SSH, host, ship_command(hash_of(files), f"{os.getpid()}-{random.randrange(1 << 32):x}")],
                         input=buf.getvalue(), capture_output=True, timeout=600, check=False)
    if res.returncode:
        raise Unavailable(f"shipping the code failed ({res.returncode}): {res.stderr.decode(errors='replace')[-300:]}")


def ship_command(code, nonce):
    """The cmd line that extracts a tar on stdin into HOME's v-`code`: into
    part-`code`-`nonce` first, renamed once whole (ren refuses a name that
    exists, so a copy in use is never replaced); exit 0 when v-`code` is
    then complete (MANIFEST in it), whoever made it."""
    part, final = rf"{HOME}\part-{code}-{nonce}", rf"{HOME}\v-{code}"
    drop = f'cd /d "{HOME}" & rmdir /s /q "{part}"'
    return (f'mkdir "{part}" && cd /d "{part}" && (tar -xf - || ({drop} & exit 1)) && cd /d "{HOME}" && '
            f'(ren "{part}" "v-{code}" 2>nul || ({drop} & if exist "{final}\\{MANIFEST.replace("/", chr(92))}" '
            f'(exit 0) else (echo {final} has no {MANIFEST}: remove it 1>&2 & exit 1)))')


#: This host's versions(), read once a process.
_VERSIONS = {}
#: Each thread's session: the fetcher reads PDFs on several threads at once,
#: and one ssh session answers one request at a time.
_THREAD = threading.local()


def _state():
    """This thread's {"session", "retry"}, fresh in a forked worker (the
    parent's session is not its own)."""
    st = getattr(_THREAD, "st", None)
    if st is None or st["pid"] != os.getpid():
        st = _THREAD.st = {"pid": os.getpid(), "session": None, "retry": 0.0}
    return st
#: Held while one process ships: the rest wait, then find the code there.
SHIP_LOCK = Path(tempfile.gettempdir()) / "ocr_remote.ship.lock"


def log(line):
    print(f"{time.strftime('%H:%M:%S')} desktop OCR [{os.getpid()}]: {line}", file=sys.stderr, flush=True)


def matched(s):
    """`s` when its versions are this host's, else None and why (closed)."""
    local = _VERSIONS["local"]
    differ = sorted(k for k in set(s.ready) | set(local) if s.ready.get(k) != local.get(k))
    if not differ:
        return s, None
    s.close()
    return None, f"{s.host}: not this host's readers: " + ", ".join(
        f"{k} {s.ready.get(k)} here {local.get(k)}" for k in differ)


def opened(host, tries=3):
    """A Session on `host`, tried `tries` times a few seconds apart (the
    desktop's sshd turns away a burst of new connections)."""
    for attempt in range(tries):
        try:
            return Session(host)
        except Unavailable:
            if attempt == tries - 1:
                raise
            time.sleep(random.uniform(2, 8))
    raise AssertionError("unreachable")


def connect():
    """A ready session whose versions are this host's, on the first of
    OCR_REMOTE's hosts that gives one, the code shipped there first when it
    is missing; else None, the reasons logged."""
    import fcntl
    if "local" not in _VERSIONS:
        _VERSIONS["local"] = versions()
    reasons = []
    for host in filter(None, os.environ.get("OCR_REMOTE", "").split(",")):
        try:
            s, why = matched(opened(host))
        except Unavailable as e:
            s, why = None, f"{host}: {e}"
        if s:
            return s
        with open(SHIP_LOCK, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                s, why = matched(opened(host, 1))
            except Unavailable:
                s = None
            if s:
                return s
            try:
                ship(host)
                s, why = matched(opened(host, 1))
            except (Unavailable, OSError, subprocess.TimeoutExpired) as e:
                s, why = None, f"{why}; then {host}: {e}"
            if s:
                return s
        reasons.append(why)
    log("unavailable (" + "; ".join(reasons or ["OCR_REMOTE names no host"])
        + f"), reading here; trying again in {RETRY}s")
    return None


def hosts():
    return [h for h in os.environ.get("OCR_REMOTE", "").split(",") if h]


def session():
    """This process's ready session, or None when OCR_REMOTE is not set, the
    desktop is busy (closing the session; DesktopBusy when this process
    defers) or no host answers (then not tried again for RETRY seconds)."""
    if not hosts():
        return None
    st = _state()
    why = desktop_busy.busy(hosts())
    if why:
        if st["session"] is not None:
            st["session"].close()
            st["session"] = None
        _busy_here(why)
        return None
    if st["session"] is None:
        if time.monotonic() < st["retry"]:
            return None
        st["session"] = connect()
        if st["session"] is None:
            st["retry"] = time.monotonic() + RETRY
            return None
        log(f"reading on {st['session'].host}")
    return st["session"]


def lost(e):
    """Close a session that stopped answering: tried again after RETRY
    seconds, or once the desktop is idle when it was ended for a game
    (DesktopBusy when this process defers)."""
    st = _state()
    why = desktop_busy.busy(hosts())
    wait = 0 if why else RETRY
    deferred = bool(why and os.environ.get(DEFER))
    log(f"lost {st['session'].host} ({e}), {'deferring' if deferred else 'reading here'}; trying again "
        + (f"in {RETRY}s" if wait else "when the desktop is idle"))
    st["session"].close()
    st.update(session=None, retry=time.monotonic() + wait)
    _busy_here(why)


def edition_request(d, found, solutions):
    """(header, tar) asking the desktop for read_edition(d, found): the
    edition's text and leaves, each title's solution leaf and cached
    solution crop, the edition's cached readings, the readings of each
    title's Canberra Times reprint, and its series' filed dates."""
    import io
    import tarfile

    import file_archive_org_puzzles as fa
    import series as series_meta
    import vlm_reader
    rel = f"{d.parent.name}/{d.name}"
    files = {f"ed/{rel}/{name}": d / name for name in ("pages.json", "djvu.xml.gz") if (d / name).exists()}
    sols, reprints, asked = {}, {}, set()
    series = fa.paper_of(d).series
    for hit in found["puzzles"]:
        files[f"ed/{rel}/leaf_{hit['leaf']:04d}.jpg"] = d / f"leaf_{hit['leaf']:04d}.jpg"
        n, _, why = fa.filed_number(d, found, hit)
        if why is None:
            reprints[str(n)] = fa.reprint_readings(n, series)
            # What decide() opens to file it: the held file, and --out's copy.
            for where in [("held", n)] + [("out", series_meta.puzzle_id(series, n))] * bool(fa._FILING["puzzles"]):
                asked.add(where)
                path = fa.filer_path(where, series, fa._FILING["puzzles"])
                files[f"filing/{where[0]}/{where[1]}.json"] = path
        sol = solutions.get(n) if why is None else None
        if sol:
            sd = sol["dir"]
            sols[str(n)] = {**sol, "dir": f"{sd.parent.name}/{sd.name}"}
            files[f"ed/{sd.parent.name}/{sd.name}/leaf_{sol['leaf']:04d}.jpg"] = sd / f"leaf_{sol['leaf']:04d}.jpg"
            files[f"crops/solutions/{sd.name}_{n}.png"] = fa.CROPS / "solutions" / f"{sd.name}_{n}.png"
    rapid = fa.CROPS / "rapid"
    for name in os.listdir(rapid) if rapid.is_dir() else ():
        if name.startswith(f"{d.name}_"):
            files[f"crops/rapid/{name}"] = rapid / name
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for arc, path in files.items():
            if path.exists():
                tar.add(path, arcname=arc)
    held = {str(n): day.isoformat() for n, day in fa.held_dates(series).items()}
    urls = {fa.page_url(d, found, hit["leaf"]) for hit in found["puzzles"]}
    filing = {"series": series, "puzzles": fa._FILING["puzzles"], "asked": sorted(asked),
              "held": sorted(fa.held_numbers(series)),
              "scans": [[url, day, ns] for (url, day), ns in fa.held_scans(series).items() if url in urls]}
    return ({"edition": rel, "found": found, "solutions": sols, "held": {series: held}, "reprints": reprints,
             "vlm": vlm_reader.reachable(), "png": vlm_reader.encoder(), "filing": filing},
            buf.getvalue())


def edition(d, found, solutions):
    """read_edition(d, found) with `solutions` read on the desktop, the crops
    it cached written under CROPS as a read here writes them; or None when
    OCR_REMOTE is not set, the desktop is not answering or the read there
    failed: then the caller reads it here. The desktop's answer that
    tools/edition_commit.py's unit got and left to this one to decide
    (CT_EDITION_ANSWER, its crops written) is taken as read there."""
    answer = os.environ.pop("CT_EDITION_ANSWER", None)
    if answer:
        got = json.loads(Path(answer).read_text())
        Path(answer).unlink()
        if got["edition"] == f"{d.parent.name}/{d.name}":
            return [tuple(r) for r in got["results"]], got["vlm"], None
    s = session()
    if s is None:
        return None
    import io
    import tarfile

    import file_archive_org_puzzles as fa
    head, tar = edition_request(d, found, solutions)
    try:
        got, back = s.edition(head, tar)
    except Unavailable as e:
        lost(e)
        return None
    if "error" in got:
        log(f"{head['edition']} failed there ({got['error']}), reading it here")
        return None
    with tarfile.open(fileobj=io.BytesIO(back)) as t:
        t.extractall(fa.CROPS, filter="data")
    if got.get("decided") is None:
        log(f"{head['edition']}: a title there looked up a file it was not sent, so its filing is decided here")
    return [tuple(r) for r in got["results"]], got["vlm"], got.get("decided")


def scan_request(d):
    """A tar of what file_archive_org_puzzles._scan(d) reads: the edition's
    pages.json, djvu text and crossword leaves, and the title readings
    cached for it (its keys: "<item>_<date>_<leaf>" and "<date>_<leaf>")."""
    import io
    import tarfile

    import file_archive_org_puzzles as fa
    rel = f"{d.parent.name}/{d.name}"
    files = {f"ed/{rel}/{name}": d / name for name in ("pages.json", "djvu.xml.gz")}
    pages = json.loads((d / "pages.json").read_text())
    for p in pages.get("crossword_pages", ()):
        files[f"ed/{rel}/leaf_{p['leaf']:04d}.jpg"] = d / f"leaf_{p['leaf']:04d}.jpg"
    titles = fa.CROPS / "titles"
    keys = (f"{d.parent.name}_{d.name}_", f"{d.name}_")
    for name in os.listdir(titles) if titles.is_dir() else ():
        if name.startswith(keys):
            files[f"crops/titles/{name}"] = titles / name
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for arc, path in files.items():
            if path.exists():
                tar.add(path, arcname=arc)
    return buf.getvalue()


def scan(d):
    """file_archive_org_puzzles._scan(d) run on the desktop (the page
    decoding, grid search and title OCR), the title readings it cached
    written under CROPS as a scan here writes them; or None when call()
    cannot run it there: then the caller scans here."""
    if not hosts():
        return None
    import io
    import tarfile

    import file_archive_org_puzzles as fa
    crops = fa.CROPS
    got = call("scan", f"{d.parent.name}/{d.name}", data=scan_request(d))
    if got is None:
        return None
    found, back = got
    with tarfile.open(fileobj=io.BytesIO(back)) as t:
        t.extractall(crops, filter="data")
    return found


def words(crop, which):
    """raw_words(crop, which) read on the desktop, or None when it is not
    set (no OCR_REMOTE) or not answering: then the caller reads it here."""
    s = session()
    if s is None:
        return None
    import io
    buf = io.BytesIO()
    crop.save(buf, format="PNG", compress_level=1)
    try:
        got = s.read(buf.getvalue(), which)
    except Unavailable as e:
        lost(e)
        return None
    if "error" in got:
        log(f"{which} failed there ({got['error']}), reading this crop here")
        return None
    return [tuple(w) for w in got["words"]]


def call(name, *args, data=b"", **kwargs):
    """(result, bytes) of CALLS[name](data, *args, **kwargs) run on the
    desktop, or None when OCR_REMOTE is not set, the desktop is not
    answering or the call failed there: then the caller runs it here, in
    local_slot()."""
    s = session()
    if s is None:
        return None
    try:
        got, back = s.call(name, list(args), kwargs, data)
    except Unavailable as e:
        lost(e)
        return None
    if "error" in got:
        log(f"{name} failed there ({got['error']}), running it here")
        return None
    return got["result"], back


def reconstruct(spec, **kwargs):
    """reconstruct_grid.reconstruct(spec, **kwargs), run on the desktop when
    call() can: the same search, the same grids."""
    import reconstruct_grid
    got = call("reconstruct", [list(t) for t in spec], **kwargs)
    if got is None:
        with local_slot():
            return reconstruct_grid.reconstruct(spec, **kwargs)
    found, info = got[0]
    return [tuple(g) for g in found], info


_HELD = threading.local()


@contextlib.contextmanager
def local_slot():
    """Hold one of LOCAL_SLOTS slots, shared by every process on this host
    (a lock file each), while reading here what OCR_REMOTE would read on the
    desktop; nothing to hold without OCR_REMOTE. A thread already holding
    one (a local edition read, then its crops' OCR) holds it on."""
    if not hosts() or getattr(_HELD, "depth", 0):
        _HELD.depth = getattr(_HELD, "depth", 0) + 1
        try:
            yield
        finally:
            _HELD.depth -= 1
        return
    import fcntl
    while True:
        for i in range(LOCAL_SLOTS):
            f = open(Path(tempfile.gettempdir()) / f"ocr_remote.local.{i}.lock", "w")  # noqa: SIM115 -- held while the slot is
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                f.close()
                continue
            _HELD.depth = 1
            try:
                yield
            finally:
                _HELD.depth = 0
                f.close()
            return
        time.sleep(random.uniform(0.2, 1.0))


def check():
    """Read one synthetic crop with each reader both ways and say whether
    the readings are the same."""
    from PIL import Image, ImageDraw

    import ocr_clues
    img = Image.new("RGB", (900, 60), "white")
    ImageDraw.Draw(img).text((10, 20), "1 Bird of prey seen over the river (6)", fill="black")
    crop = img.resize((img.width * ocr_clues.UPSCALE, img.height * ocr_clues.UPSCALE))
    same = True
    for which in ocr_clues.READERS:
        there = words(crop, which)
        here = ocr_clues.raw_words(crop, which)
        print(f"{which}: {'same' if there == here else 'DIFFERENT'}: here {here} there {there}")
        same &= there == here
    return 0 if same else 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "serve":
        serve(sys.argv[2] if len(sys.argv) > 2 else "idle")
    elif cmd == "check":
        sys.exit(check())
    else:
        sys.exit(f"unknown command {cmd!r}: serve or check")
