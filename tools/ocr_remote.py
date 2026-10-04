#!/usr/bin/env python3
"""The clue OCR (tools/ocr_clues.py raw_words) run on Paul's desktop over ssh.

    OCR_REMOTE=micro@100.68.145.15,micro@192.168.1.198 python3 tools/file_archive_org_puzzles.py ...
    python3 tools/ocr_remote.py check        # connect, report versions, read one crop both ways

The Mac mini has 4 cores; the desktop has 28. With OCR_REMOTE set, each
process holds one ssh session to `python ocr_remote.py serve` on the first
host that answers, sends it the already-upscaled crop as PNG and gets the
words back as JSON. The desktop runs the same code (this file, ocr_clues.py
and the Tesseract model, shipped once into a directory named by their hash,
so a running session's files are never overwritten), the same reader models
and the same tesseract and onnxruntime builds: the session is used only
when the versions it reports are this host's, so a reading is the same
whichever host made it.

When no host answers, or one stops answering mid-read, the reason is logged
and this process reads locally, trying the desktop again after RETRY
seconds: a desktop that is off slows a run down and never stops or hangs it.

Desktop layout (C:\\Users\\micro\\ocrw): venv/ (the pinned Python packages),
tess/ (conda-forge tesseract, micromamba), v-<code hash>/tools/ (shipped here).
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
#: Seconds to wait for a session to say it is ready, and for one crop.
CONNECT_TIMEOUT = 60
READ_TIMEOUT = 300
#: Seconds before a process that lost the desktop tries it again.
RETRY = 600
#: Every OCR_REMOTE host is the desktop, its host key known by its tailnet
#: address (this host's known_hosts is read-only), so its LAN address
#: checks against that.
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=15",
       "-o", "ServerAliveCountMax=4", "-o", "HostKeyAlias=100.68.145.15"]


def shipped():
    """{repo path: file} of what the desktop needs from this checkout."""
    import ocr_clues
    files = {"tools/ocr_remote.py": TOOLS / "ocr_remote.py", "tools/ocr_clues.py": TOOLS / "ocr_clues.py"}
    for model in ocr_clues.TESS_MODELS.values():
        files[f"tools/{model.relative_to(TOOLS).as_posix()}"] = model
    return files


def code_hash():
    """The hash of shipped()'s contents: the desktop directory they live in."""
    h = hashlib.sha1()
    for name, path in sorted(shipped().items()):
        h.update(name.encode() + b"\0" + path.read_bytes())
    return h.hexdigest()[:12]


def code_dir():
    return rf"{HOME}\v-{code_hash()}"


def versions():
    """What decides a reading here: the reader packages, tesseract's build
    and the hash of every shipped file and reader model."""
    from importlib.metadata import version

    import cv2
    import numpy
    import ocr_clues
    import onnxruntime
    tess = subprocess.run([ocr_clues.tesseract(), "--version"], capture_output=True, text=True, check=False)
    out = {"tesseract": (tess.stdout or tess.stderr).splitlines()[0].strip(),
           "onnxruntime": onnxruntime.__version__, "rapidocr": version("rapidocr_onnxruntime"),
           "numpy": numpy.__version__, "cv2": cv2.__version__}
    for name, path in shipped().items():
        out[name] = hashlib.sha1(path.read_bytes()).hexdigest()
    for which, model in ocr_clues.READERS.items():
        if isinstance(model, Path):
            out[which] = hashlib.sha1(model.read_bytes()).hexdigest() if model.exists() else None
    return out


# ------------------------------------------------------------ the desktop side


def full_speed():
    """Opt this process out of Windows power throttling (EcoQoS): a
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
    if not k32.SetProcessInformation(k32.GetCurrentProcess(), 4, ctypes.byref(state), ctypes.sizeof(state)):
        print(f"SetProcessInformation failed: {ctypes.GetLastError()}", file=sys.stderr, flush=True)


def serve():
    """Read crops on stdin, words on stdout: after a "ready" line with
    versions(), each request is a JSON line {"which", "bytes"} and that many
    bytes of PNG; each answer a JSON line {"words"} or {"error"}."""
    os.environ["PATH"] = str(Path(HOME) / "tess" / "Library" / "bin") + os.pathsep + os.environ["PATH"]
    full_speed()
    # The full pass's 20 sessions share the 28-thread box: two threads each.
    os.environ.setdefault("OCR_THREADS", "2")
    import io

    import ocr_clues
    from PIL import Image
    inp, out = sys.stdin.buffer, sys.stdout.buffer

    def say(obj):
        out.write(json.dumps(obj).encode() + b"\n")
        out.flush()
    say({"ready": versions()})
    while True:
        line = inp.readline()
        if not line:
            return
        req = json.loads(line)
        data = inp.read(req["bytes"])
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

    def read(self, png, which):
        try:
            self.proc.stdin.write(json.dumps({"which": which, "bytes": len(png)}).encode() + b"\n" + png)
            self.proc.stdin.flush()
        except OSError as e:
            raise Unavailable(f"cannot send: {e}") from e
        return self.answer(READ_TIMEOUT)

    def close(self):
        try:
            self.proc.kill()
            self.proc.wait(5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def ship(host):
    """Copy shipped() into the desktop's code_dir(), over ssh as a tar
    stream."""
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, path in shipped().items():
            tar.add(path, arcname=name)
    res = subprocess.run([*SSH, host, f'mkdir "{code_dir()}" 2>nul & cd /d "{code_dir()}" && tar -xf -'],
                         input=buf.getvalue(), capture_output=True, timeout=120, check=False)
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


def words(crop, which):
    """raw_words(crop, which) read on the desktop, or None when it is not
    set (no OCR_REMOTE) or not answering: then the caller reads it here."""
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
    import io
    buf = io.BytesIO()
    crop.save(buf, format="PNG", compress_level=1)
    try:
        got = _STATE["session"].read(buf.getvalue(), which)
    except Unavailable as e:
        log(f"lost {_STATE['session'].host} ({e}), reading here; trying again in {RETRY}s")
        _STATE["session"].close()
        _STATE.update(session=None, retry=time.monotonic() + RETRY)
        return None
    if "error" in got:
        log(f"{which} failed there ({got['error']}), reading this crop here")
        return None
    return [tuple(w) for w in got["words"]]


def check():
    """Connect, print both hosts' versions, read one synthetic crop both
    ways and say whether the readings are the same."""
    import ocr_clues
    from PIL import Image, ImageDraw
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
