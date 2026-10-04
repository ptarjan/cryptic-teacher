#!/usr/bin/env python3
"""The archive.org filer's editions, and the clue OCR, read on Paul's desktop over ssh.

    OCR_REMOTE=micro@100.68.145.15,micro@192.168.1.198 python3 tools/file_archive_org_puzzles.py ...
    python3 tools/ocr_remote.py check        # connect, report versions, read one crop both ways

The Mac mini has 4 cores; the desktop has 28. With OCR_REMOTE set, each
process holds one ssh session to `python ocr_remote.py serve` on the first
host that answers. tools/file_archive_org_puzzles.py's read_edition sends it
a whole edition (its leaves, djvu text, the solution leaves it reads, its
cached readings and the series' filed dates, as a tar) and gets back the
verdicts, the puzzles and the crops it cached; any other reader sends one
already-upscaled crop as PNG and gets the words back as JSON. The desktop
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

Desktop layout (C:\\Users\\micro\\ocrw): venv/ (the pinned Python packages),
tess/ (conda-forge tesseract, micromamba), v-<code hash>/tools/ (shipped here);
the reader models outside the code (en_PP-OCRv5_rec_mobile, en_PP-OCRv3_rec)
in C:\\Users\\micro\\.cache\\rapidocr, as here in ~/.cache/rapidocr.
"""
import hashlib
import json
import os
import random
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

#: The desktop's directory.
HOME = r"C:\Users\micro\ocrw"
#: Seconds to wait for a session to say it is ready, for one crop and for
#: one edition.
CONNECT_TIMEOUT = 60
READ_TIMEOUT = 300
EDITION_TIMEOUT = 1800
#: tools/data's directories no reader opens, left off the desktop (160 MB).
UNSHIPPED = ("tools/data/blog_facts/", "tools/data/yt_solvers/")
#: The list of shipped files, in the desktop's directory, written last.
MANIFEST = "tools/shipped.txt"
#: Seconds before a process that lost the desktop tries it again.
RETRY = 600
#: Every OCR_REMOTE host is the desktop, its host key known by its tailnet
#: address (this host's known_hosts is read-only), so its LAN address
#: checks against that.
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=15",
       "-o", "ServerAliveCountMax=4", "-o", "HostKeyAlias=100.68.145.15"]


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


def code_hash():
    """The hash of shipped()'s contents: the desktop directory they live in."""
    h = hashlib.sha1()
    for name, path in sorted(shipped().items()):
        h.update(name.encode() + b"\0" + path.read_bytes())
    return h.hexdigest()[:12]


def code_dir():
    return rf"{HOME}\v-{code_hash()}"


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
    reader model's."""
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
           "libjpeg_turbo": features.version("libjpeg_turbo"), "python": f"{sys.version_info[0]}.{sys.version_info[1]}",
           "code": code_hash()}
    for which, model in models().items():
        out[which] = hashlib.sha1(model.read_bytes()).hexdigest() if model.exists() else None
    return out


# ------------------------------------------------------------ the desktop side


def full_speed():
    """Opt this process out of Windows power throttling (EcoQoS), at below
    normal priority: a
    windowless process started by sshd counts as background, and Windows
    keeps those on the efficiency cores, so 20 sessions shared 12 of the
    28 threads and took six times as long a crop."""
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
    # Below normal (and tesseract with it): the box is Paul's, and whatever
    # he runs comes first.
    k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)


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
    that host's zlib makes."""
    import datetime
    import gc
    import io
    import tarfile

    import file_archive_org_puzzles as fa
    import vlm_reader
    up = [req["vlm"]]

    def ask(img, prompt, max_tokens=1500):
        buf = io.BytesIO()
        img.save(buf, format="PNG", compress_level=1)  # lossless: the Mac decodes these pixels
        got = ask_mac({"ask": prompt, "max_tokens": max_tokens}, buf.getvalue())
        if "error" in got:
            up[0] = False
            raise RuntimeError(got["error"])
        return got["text"]
    vlm_reader.ask, vlm_reader.reachable = ask, lambda: up[0]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            tar.extractall(root, filter="data")
        crops = root / "crops"
        crops.mkdir(exist_ok=True)
        sent = {p: p.read_bytes() for p in crops.rglob("*") if p.is_file()}
        held = {series: {int(n): datetime.date.fromisoformat(day) for n, day in dates.items()}
                for series, dates in req["held"].items()}
        fa.CROPS = crops
        fa.held_dates = held.__getitem__
        fa.set_solutions({int(n): {**sol, "dir": root / "ed" / sol["dir"]} for n, sol in req["solutions"].items()})
        _WATCH[:] = [(str(root), str(TOOLS.parent)), []]
        try:
            results, vlm_ok = fa.read_edition(root / "ed" / req["edition"], req["found"])
        finally:
            missing, _WATCH[:] = _WATCH[1], [None, []]
        gc.collect()  # closes the leaves' files, which Windows will not delete open
        if missing:
            return {"error": "opened files it was not sent: " + ", ".join(sorted(set(missing))[:5])}, b""
        crashed = [v["refused"] for v, _ in results if str(v.get("refused", "")).startswith("crashed")]
        if crashed:
            return {"error": f"a title crashed there: {crashed[0]}"}, b""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for p in sorted(crops.rglob("*")):
                if p.is_file() and sent.get(p) != p.read_bytes():
                    tar.add(p, arcname=p.relative_to(crops).as_posix())
        return {"results": results, "vlm": vlm_ok}, buf.getvalue()


def serve():
    """Read crops and editions on stdin, words and verdicts on stdout: after a
    "ready" line with versions(), each request is a JSON line {"which",
    "bytes"} and that many bytes of PNG, answered by a JSON line {"words"},
    or a line {"edition", ..., "bytes"} and that many bytes of tar
    (Session.edition), answered by a line {"results", "vlm", "bytes"} and
    that many bytes of tar; either can be answered by {"error"}."""
    os.environ["PATH"] = str(Path(HOME) / "tess" / "Library" / "bin") + os.pathsep + os.environ["PATH"]
    full_speed()
    # The full pass's 20 sessions share the 28-thread box: two threads each.
    os.environ.setdefault("OCR_THREADS", "2")
    import io

    from PIL import Image

    import ocr_clues
    inp, out = sys.stdin.buffer, sys.stdout.buffer

    def say(obj):
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


class Unavailable(Exception):
    pass


class Session:
    """One ssh session to a desktop's server, owned by one process."""

    def __init__(self, host):
        self.host = host
        self.err = tempfile.TemporaryFile()  # noqa: SIM115 -- ssh writes to it for the session's life
        serve = rf"{HOME}\venv\Scripts\python.exe {code_dir()}\tools\ocr_remote.py serve"
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
            if not select.select([fd], [], [], left)[0]:
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
        while len(self.buf) < n:
            left = end - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                raise Unavailable(f"no answer in {timeout}s")
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                raise Unavailable("ssh exited mid-answer")
            self.buf += chunk
        data, self.buf = self.buf[:n], self.buf[n:]
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
    """Copy shipped() into the desktop's code_dir(), over ssh as a tar
    stream, MANIFEST last: a cut-off copy has none, so hashes as another
    and is shipped again."""
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
    res = subprocess.run([*SSH, host, f'mkdir "{code_dir()}" 2>nul & cd /d "{code_dir()}" && tar -xf -'],
                         input=buf.getvalue(), capture_output=True, timeout=600, check=False)
    if res.returncode:
        raise Unavailable(f"shipping the code failed ({res.returncode}): {res.stderr.decode(errors='replace')[-300:]}")


_STATE = {"pid": None, "session": None, "retry": 0.0, "local": None}
#: Held while one process ships: the rest wait, then find the code there.
SHIP_LOCK = Path(tempfile.gettempdir()) / "ocr_remote.ship.lock"


def log(line):
    print(f"{time.strftime('%H:%M:%S')} desktop OCR [{os.getpid()}]: {line}", file=sys.stderr, flush=True)


def matched(s):
    """`s` when its versions are this host's, else None and why (closed)."""
    differ = sorted(k for k in set(s.ready) | set(_STATE["local"]) if s.ready.get(k) != _STATE["local"].get(k))
    if not differ:
        return s, None
    s.close()
    return None, f"{s.host}: not this host's readers: " + ", ".join(
        f"{k} {s.ready.get(k)} here {_STATE['local'].get(k)}" for k in differ)


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
    if _STATE["local"] is None:
        _STATE["local"] = versions()
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


def session():
    """This process's ready session, or None when OCR_REMOTE is not set or
    no host answers (then not tried again for RETRY seconds)."""
    if not os.environ.get("OCR_REMOTE"):
        return None
    if _STATE["pid"] != os.getpid():  # a forked worker: the parent's session is not its own
        _STATE.update(pid=os.getpid(), session=None, retry=0.0)
    if _STATE["session"] is None:
        if time.monotonic() < _STATE["retry"]:
            return None
        _STATE["session"] = connect()
        if _STATE["session"] is None:
            _STATE["retry"] = time.monotonic() + RETRY
            return None
        log(f"reading on {_STATE['session'].host}")
    return _STATE["session"]


def lost(e):
    log(f"lost {_STATE['session'].host} ({e}), reading here; trying again in {RETRY}s")
    _STATE["session"].close()
    _STATE.update(session=None, retry=time.monotonic() + RETRY)


def edition_request(d, found, solutions):
    """(header, tar) asking the desktop for read_edition(d, found): the
    edition's text and leaves, each title's solution leaf and cached
    solution crop, the edition's cached readings, and its series' filed
    dates."""
    import io
    import tarfile

    import file_archive_org_puzzles as fa
    import vlm_reader
    rel = f"{d.parent.name}/{d.name}"
    files = {f"ed/{rel}/{name}": d / name for name in ("pages.json", "djvu.xml.gz") if (d / name).exists()}
    sols = {}
    for hit in found["puzzles"]:
        files[f"ed/{rel}/leaf_{hit['leaf']:04d}.jpg"] = d / f"leaf_{hit['leaf']:04d}.jpg"
        n, _, why = fa.filed_number(d, found, hit)
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
    series = fa.paper_of(d).series
    held = {str(n): day.isoformat() for n, day in fa.held_dates(series).items()}
    return ({"edition": rel, "found": found, "solutions": sols, "held": {series: held}, "vlm": vlm_reader.reachable()},
            buf.getvalue())


def edition(d, found, solutions):
    """read_edition(d, found) with `solutions` read on the desktop, the crops
    it cached written under CROPS as a read here writes them; or None when
    OCR_REMOTE is not set, the desktop is not answering or the read there
    failed: then the caller reads it here."""
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
    return [tuple(r) for r in got["results"]], got["vlm"]


def words(crop, which):
    """raw_words(crop, which) read on the desktop, or None when it is not
    set (no OCR_REMOTE) or not answering: then the caller reads it here."""
    if session() is None:
        return None
    import io
    buf = io.BytesIO()
    crop.save(buf, format="PNG", compress_level=1)
    try:
        got = _STATE["session"].read(buf.getvalue(), which)
    except Unavailable as e:
        lost(e)
        return None
    if "error" in got:
        log(f"{which} failed there ({got['error']}), reading this crop here")
        return None
    return [tuple(w) for w in got["words"]]


def check():
    """Connect, print both hosts' versions, read one synthetic crop both
    ways and say whether the readings are the same."""
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
        serve()
    elif cmd == "check":
        sys.exit(check())
    else:
        sys.exit(f"unknown command {cmd!r}: serve or check")
