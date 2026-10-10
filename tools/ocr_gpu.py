#!/usr/bin/env python3
"""One shared RapidOCR process on the desktop's GPU, beside the CPU sessions.

    python ocr_gpu.py serve      # started by the sessions (ensure()), never by hand

RapidOCR's det+rec is ~90% of the desktop's CPU under tools/ocr_remote.py's
serve sessions. On CUDA it reads the same crop for ~1/6 of the CPU, but a
process holds ~5 GB of VRAM, so only one fits beside the VLM: this server,
on 127.0.0.1:PORT (the bound port is the one-server lock). serve() installs
GpuFirst in each session (install()): an engine call that the server takes
is read there; when the server is absent, busy (QUEUE requests already in
it), refuses, errs or is another version, the session reads on its own CPU
engine at once, so the GPU adds throughput and never holds a read back.

Its words and boxes are byte-identical to the CPU engine's (CUDA: cudnn's
DEFAULT algorithm, no TF32, deterministic compute; rapidocr's own EXHAUSTIVE
search changes words); only the confidence differs, in the 7th digit, and no
reader uses it but rapidocr's own text_score cut. onnxruntime-gpu lives beside the venv in GPU_DIR (its CUDA 13
and cuDNN 9 wheels pip-installed there with --target), first on this
process's sys.path; the sessions keep the venv's CPU onnxruntime.

It yields like the sessions: it never starts, and exits, while a game
(desktop_busy.GAMES) runs or VRAM free is under HEADROOM_MB (before loading,
under HEADROOM_MB + LOAD_MB); either leaves HOLD so no session starts it again
for HOLD_SECONDS. desktop_busy's probe ends it with the sessions (its command
line names "serve") and leaves its CUDA work out of the 3D load. It exits
after IDLE_EXIT seconds unused, freeing the VRAM. Its log: LOG.
"""
import csv
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import ocr_remote

#: The desktop's directory (ocr_remote.HOME); OCR_GPU_HOME in tests.
HOME = Path(os.environ.get("OCR_GPU_HOME") or ocr_remote.HOME)
GPU_DIR = HOME / "gpu"
#: Present: no session asks the server (the CPU engine reads everything).
OFF = HOME / "gpu-off"
#: {"until", "why"}: no session starts the server before `until`.
HOLD = HOME / "gpu-hold.json"
HOLD_SECONDS = 600
#: Touched by the session that starts the server: no other starts one within START_EVERY.
STARTED = HOME / "gpu-start.stamp"
START_EVERY = 60
LOG = HOME / "gpu.log"
#: Each session's engine calls ({"gpu", "cpu", "busy", "absent", "gpu_cpu_s", "cpu_cpu_s"}), by pid.
STATS = HOME / "gpu-stats"
STATS_EVERY = 30
PORT = 47311
#: VRAM kept free for the VLM and the desktop, and what the server's engines take.
HEADROOM_MB = 4096
LOAD_MB = 5500
#: Requests inside the server (reading or waiting) before it answers busy,
#: and how many read at once.
QUEUE = 3
WORKERS = 2
WATCH_EVERY = 10
IDLE_EXIT = 300
#: Seconds a session waits for an answer it was promised (not busy).
ANSWER_TIMEOUT = 120
#: Seconds a session leaves a server that did not connect or failed alone.
DOWN_FOR = 30
#: The CUDA provider's settings that read as the CPU does.
CUDA = {"device_id": 0, "cudnn_conv_algo_search": "DEFAULT", "use_tf32": 0,
        "arena_extend_strategy": "kSameAsRequested", "do_copy_in_default_stream": True}
#: What the server reads: this file's text, so a session talks only to its own version.
VERSION = hashlib.sha1(Path(__file__).read_bytes()).hexdigest()[:12]
#: RapidOCR() keywords GpuFirst stands in for: any other makes a plain engine.
WRAPPED = {"rec_model_path", "intra_op_num_threads", "inter_op_num_threads"}


def log(line):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{os.getpid()}] {line}\n")
    except OSError:
        pass


def held():
    """Why the server may not start now, or None."""
    try:
        got = json.loads(HOLD.read_text())
    except (OSError, ValueError):
        return None
    return got.get("why") if time.time() < got.get("until", 0) else None


def hold(why):
    HOLD.write_text(json.dumps({"until": time.time() + HOLD_SECONDS, "why": why}))


# ------------------------------------------------------------ the session side


class Client:
    """One session's connection to the server (one per thread: a reply is read in turn)."""

    def __init__(self):
        self.local = threading.local()
        self.down_until = 0.0

    def ask(self, img, model):
        """(res, elapse) of the server's read of `img`, or (None, why not)."""
        if OFF.exists():
            return None, "off"
        if time.monotonic() < self.down_until:
            return None, "absent"
        conn = getattr(self.local, "conn", None)
        if conn is None:
            try:
                conn = socket.create_connection(("127.0.0.1", PORT), timeout=1)
            except OSError:
                self.down(DOWN_FOR)
                ensure()
                return None, "absent"
            conn.settimeout(ANSWER_TIMEOUT)
            self.local.conn, self.local.f = conn, conn.makefile("rb")
        data = img.tobytes()
        head = {"v": VERSION, "model": model, "shape": list(img.shape), "bytes": len(data)}
        try:
            conn.sendall(json.dumps(head).encode() + b"\n" + data)
            line = self.local.f.readline()
            got = json.loads(line) if line else {"error": "server closed the connection"}
        except (OSError, ValueError) as e:
            got = {"error": f"{type(e).__name__}: {e}"}
        if "res" in got:
            return (got["res"], got["elapse"]), None
        if "busy" in got:
            return None, "busy"
        self.close()
        self.down(DOWN_FOR)
        return None, "absent"

    def down(self, seconds):
        self.down_until = time.monotonic() + seconds

    def close(self):
        conn = getattr(self.local, "conn", None)
        self.local.conn = self.local.f = None
        if conn is not None:
            conn.close()


_CLIENT = Client()
_STATS = {"gpu": 0, "cpu": 0, "busy": 0, "absent": 0, "off": 0, "gpu_cpu_s": 0.0, "cpu_cpu_s": 0.0}
_STATS_AT = [0.0]


def count(**kw):
    for k, v in kw.items():
        _STATS[k] += v
    if time.monotonic() - _STATS_AT[0] > STATS_EVERY:
        _STATS_AT[0] = time.monotonic()
        try:
            STATS.mkdir(exist_ok=True)
            (STATS / f"{os.getpid()}.json").write_text(json.dumps({**_STATS, "t": time.time()}))
        except OSError:
            pass


class GpuFirst:
    """A RapidOCR engine whose plain reads (an image array, use_cls=False,
    nothing else) the GPU server makes when it takes them, the rest made by
    the CPU engine `make()` gives (made when first needed)."""

    def __init__(self, make, model):
        self._make, self._cpu, self.model = make, None, model

    def cpu(self):
        if self._cpu is None:
            self._cpu = self._make()
        return self._cpu

    def __getattr__(self, name):
        return getattr(self.cpu(), name)

    def __call__(self, img, use_det=None, use_cls=None, use_rec=None, **kw):
        import numpy as np
        plain = (use_det is None and use_rec is None and use_cls is False and not kw
                 and isinstance(img, np.ndarray) and img.dtype == np.uint8 and img.ndim == 3)
        if plain:
            t = time.process_time()
            got, why = _CLIENT.ask(np.ascontiguousarray(img), self.model)
            if got is not None:
                count(gpu=1, gpu_cpu_s=time.process_time() - t)
                return got
            count(**{why: 1})
        t = time.process_time()
        got = self.cpu()(img, use_det=use_det, use_cls=use_cls, use_rec=use_rec, **kw)
        count(cpu=1, cpu_cpu_s=time.process_time() - t)
        return got


def install():
    """Make every RapidOCR engine this process creates a GpuFirst, when
    GPU_DIR is installed: tools/ocr_remote.py's serve() calls it."""
    if not GPU_DIR.is_dir():
        return
    import rapidocr_onnxruntime
    real = rapidocr_onnxruntime.RapidOCR
    if getattr(real, "gpu_first", False):
        return

    def make(*args, **kw):
        if args or set(kw) - WRAPPED:
            return real(*args, **kw)
        model = kw.get("rec_model_path")
        return GpuFirst(lambda: real(**kw), None if model is None else str(model))
    make.gpu_first = True
    rapidocr_onnxruntime.RapidOCR = make


def ensure():
    """Start the server, detached, unless it is held (HOLD) or another
    session started one within START_EVERY: it checks the rest itself."""
    if held():
        return
    try:
        if time.time() - STARTED.stat().st_mtime < START_EVERY:
            return
    except OSError:
        pass
    try:
        STARTED.touch()
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP
        cmd = [sys.executable, str(Path(__file__).resolve()), "serve"]
        try:
            subprocess.Popen(cmd, creationflags=flags | 0x01000000, stdin=subprocess.DEVNULL,  # BREAKAWAY_FROM_JOB
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        except OSError:
            subprocess.Popen(cmd, creationflags=flags, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except (OSError, ValueError) as e:
        log(f"cannot start the server: {type(e).__name__}: {e}")


# ------------------------------------------------------------ the server


def games():
    """The desktop_busy.GAMES processes running here."""
    import desktop_busy
    want = {g.lower() for g in desktop_busy.GAMES}
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, check=False,
                         creationflags=0x08000000).stdout  # CREATE_NO_WINDOW
    return sorted({row[0] for row in csv.reader(io.StringIO(out))
                   if row and row[0].lower().removesuffix(".exe") in want})


def vram_free():
    """The GPU's free memory in MB (nvidia-smi), or None when unreadable."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=30, check=False,
                             creationflags=0x08000000).stdout
        return int(out.split()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def unfit(need):
    """Why the server may not run (a game, VRAM free under `need` MB), or None."""
    g = games()
    if g:
        return "playing " + ", ".join(g)
    free = vram_free()
    if free is None:
        return "nvidia-smi gives no free VRAM"
    if free < need:
        return f"VRAM free {free} MB < {need} MB"
    return None


def stop(why, keep_away=True):
    log(f"exiting: {why}")
    if keep_away:
        hold(why)
    os._exit(0)


def cuda_engines():
    """{model: RapidOCR on CUDA} made on first use, rapidocr's sessions given CUDA's settings."""
    sys.path.insert(0, str(GPU_DIR))
    import onnxruntime
    if not str(Path(onnxruntime.__file__)).startswith(str(GPU_DIR)):
        raise RuntimeError(f"onnxruntime {onnxruntime.__file__} is not {GPU_DIR}'s")
    onnxruntime.preload_dlls(directory="")
    from rapidocr_onnxruntime import RapidOCR
    from rapidocr_onnxruntime.utils import infer_engine

    def eps(self):
        self.use_cuda, self.use_directml = True, False
        return [("CUDAExecutionProvider", CUDA), ("CPUExecutionProvider", {"arena_extend_strategy": "kSameAsRequested"})]
    opts = infer_engine.OrtInferSession._init_sess_opts

    def sess_opts(config):
        o = opts(config)
        o.use_deterministic_compute = True
        return o
    infer_engine.OrtInferSession._get_ep_list = eps
    infer_engine.OrtInferSession._init_sess_opts = staticmethod(sess_opts)
    made, lock = {}, threading.Lock()

    def engine(model):
        with lock:
            if model not in made:
                kw = {"intra_op_num_threads": 2, "inter_op_num_threads": 1}
                made[model] = RapidOCR(rec_model_path=model, **kw) if model else RapidOCR(**kw)
                log(f"loaded {model or 'the default recogniser'}; VRAM free {vram_free()} MB")
            return made[model]
    return engine


class Server:
    """The requests of every session's Client, read by `engine(model)` (cuda_engines)."""

    def __init__(self, engine, version=VERSION):
        self.engine, self.version = engine, version
        self.lock, self.workers = threading.Lock(), threading.Semaphore(WORKERS)
        self.inside, self.used, self.reads = 0, time.monotonic(), 0

    def reply(self, head, data):
        """The answer to one request: {"res", "elapse"}, {"busy"} with QUEUE
        requests inside already, or {"error"}."""
        import numpy as np
        if head.get("v") != self.version:
            return {"error": f"version {self.version}, not {head.get('v')}"}
        with self.lock:
            if self.inside >= QUEUE:
                return {"busy": True}
            self.inside += 1
        try:
            with self.workers:
                img = np.frombuffer(data, dtype=np.uint8).reshape(head["shape"])
                res, elapse = self.engine(head["model"])(img, use_cls=False)
            return {"res": res, "elapse": elapse}
        except Exception as e:  # noqa: BLE001 -- the session reads it on its CPU and the log says why
            log(f"read failed: {type(e).__name__}: {e}")
            return {"error": f"{type(e).__name__}: {e}"}
        finally:
            with self.lock:
                self.inside -= 1
                self.used = time.monotonic()
                self.reads += 1

    def handle(self, conn):
        f = conn.makefile("rb")
        with conn:
            while True:
                line = f.readline()
                if not line:
                    return
                head = json.loads(line)
                conn.sendall(json.dumps(self.reply(head, f.read(head["bytes"]))).encode() + b"\n")

    def accept(self, sock):
        while True:
            conn, _ = sock.accept()
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def idle(self):
        with self.lock:
            return not self.inside and time.monotonic() - self.used > IDLE_EXIT


def serve():
    why = held() or unfit(HEADROOM_MB + LOAD_MB)
    if why:
        log(f"not starting: {why}")
        return
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", PORT))
    except OSError:
        return  # another server holds the port
    sock.listen(64)
    ocr_remote.full_speed("scan")  # below normal: above the CPU sessions, below a game
    os.environ["OCR_THREADS"] = "2"
    import ocr_clues
    ocr_clues.engine_threads()
    server = Server(cuda_engines())
    log(f"serving on {PORT}, version {VERSION}; VRAM free {vram_free()} MB")
    threading.Thread(target=server.accept, args=(sock,), daemon=True).start()
    while True:
        time.sleep(WATCH_EVERY)
        g = games()
        if g:
            stop("playing " + ", ".join(g))
        free = vram_free()
        if free is not None and free < HEADROOM_MB:
            stop(f"VRAM free {free} MB < {HEADROOM_MB} MB")
        if server.idle():
            stop(f"idle {IDLE_EXIT}s after {server.reads} reads", keep_away=False)


if __name__ == "__main__":
    if sys.argv[1:] == ["serve"]:
        try:
            serve()
        except Exception as e:  # the log is all a detached process has; re-raised
            log(f"crashed: {type(e).__name__}: {e}")
            raise
    else:
        sys.exit("usage: ocr_gpu.py serve")
