#!/usr/bin/env python3
# Does tools/ocr_remote.py compare every reader model a read can load, run
# the code it compares against (not a newer checkout's), send
# back an edition whose read on the desktop opened a file it was not sent,
# give the same grids from a search run there (its answer through JSON) as
# here, the same headings and cached readings from a scan run there, the same
# match and pages of a saved Gale page, wait on a search for as long as the desktop says it is still
# searching, let no more than LOCAL_SLOTS reads run here at once, and does
# every module the desktop imports import without fcntl (Windows), and does
# a session read on the shared GPU server only when it takes the read?
#
#     python3 tools/test_ocr_remote.py
#
# No ssh, no OCR: temp dirs only.
import os
import shlex
import shutil
import stat
import sys
import tempfile
import textwrap
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO / "tools")
sys.path.insert(0, str(REPO / "tools"))
os.environ["DESKTOP_HOSTS_STATIC"] = "1"  # desktop_hosts.ranked: the json order, no network probe
tmp = Path(tempfile.mkdtemp())


def run_block(fn, merge=True, **env):
    """Run fn in a forked child, as the old python3 heredoc was its own process.

    Returns (output, exit code); the child's stderr joins its output if merge."""
    with tempfile.TemporaryFile("w+") as cap:
        sys.stdout.flush()
        sys.stderr.flush()
        pid = os.fork()
        if pid == 0:
            code = 0
            try:
                os.environ.update(env)
                sys.stdout = open(cap.fileno(), "w", closefd=False)
                if merge:
                    sys.stderr = sys.stdout
                fn()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
                if isinstance(e.code, str):
                    print(e.code, file=sys.stderr)
            except BaseException:
                traceback.print_exc()
                code = 1
            finally:
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(code)
        _, status = os.waitpid(pid, 0)
        cap.seek(0)
        return cap.read(), os.waitstatus_to_exitcode(status)


def block1():
    global fails
    import json, os, sys, threading, time
    from pathlib import Path
    import ocr_clues, ocr_remote, trove_solution_ocr

    fails = 0
    def check(what, want, got):
        global fails
        if want == got:
            print(f"ok   {what}")
        else:
            fails += 1
            print(f"FAIL {what}: expected {want!r}, got {got!r}")

    # A missing optional model changes the reading (the solution reader's
    # en_PP-OCRv3 does), so each must be in the versions compared.
    want = {m for m in ocr_clues.READERS.values() if isinstance(m, Path)} | set(trove_solution_ocr.EXTRA_MODELS)
    check("every reader model is compared on connect", want, set(ocr_remote.models().values()))

    # A process whose checkout moved on asks for the code it loaded and compares
    # against: asking for the new code's directory mismatched every session and
    # shipped over a directory others were reading.
    ocr_remote._VERSIONS["local"] = {"code": "0123456789ab"}
    check("a session runs the code this process compares", ocr_remote.HOME + "\\v-0123456789ab", ocr_remote.code_dir())
    del ocr_remote._VERSIONS["local"]

    tmp = Path(os.environ["TMP"])
    (tmp / "here.txt").write_text("x")
    sys.addaudithook(ocr_remote._audit)
    ocr_remote._WATCH[:] = [(str(tmp),), []]
    (tmp / "here.txt").read_text()
    (tmp / "new.txt").write_text("y")
    (tmp / "__pycache__").mkdir()
    for missing in (tmp / "gone.txt", tmp / "__pycache__" / "m.pyc", Path("/nonexistent-outside/x")):
        try:
            missing.read_text()
        except OSError:
            pass
    seen = ocr_remote._WATCH[1]
    ocr_remote._WATCH[:] = [None, []]
    check("only a read of a missing file under the edition's roots is noted", [str(tmp / "gone.txt")], seen)

    import reconstruct_grid
    spec = [(1, "across", 3), (4, "across", 3), (5, "across", 3), (1, "down", 3), (2, "down", 3), (3, "down", 3)]
    kw = {"cols": 3, "rows": 3, "limit": 5}
    def over_json(name, *args, data=b"", **kwargs):  # call() as the desktop answers it
        result, back = ocr_remote.run_call(name, data, json.loads(json.dumps(args)), kwargs)
        return json.loads(json.dumps(result)), back
    ocr_remote.call = over_json
    check("a search run there gives the grids a search here does",
          reconstruct_grid.reconstruct(spec, **kw), ocr_remote.reconstruct(spec, **kw))

    # A desktop read decides what files there (decide_here, the filer's decide()
    # against copies of the Mac's files): a reading of a held number files
    # nothing over it, a new number's is written, and a title that looks up a
    # file the Mac did not say it has or lacks leaves the decision to the Mac.
    import copy, tempfile
    import file_archive_org_puzzles as fa
    held = json.loads((Path("..") / "puzzles/times/1990/times-18184.json").read_text())
    new = {**copy.deepcopy(held), "id": "times-99999", "number": 99999}
    def there(results, asked, files):
        root = Path(tempfile.mkdtemp(dir=tmp))
        for (kind, key), puzzle in files.items():
            (root / kind).mkdir(exist_ok=True)
            (root / kind / f"{key}.json").write_text(json.dumps(puzzle))
        filing = {"series": "times", "puzzles": None, "asked": asked, "held": [18184], "scans": []}
        return ocr_remote.decide_here(json.loads(json.dumps(results)), filing, root)
    got = there([({"number": 18184}, held), ({"number": 99999}, new)], [["held", 18184], ["held", 99999]],
                {("held", 18184): held})
    check("a held number's reading files nothing over it there",
          ({"number": 18184, "id": "times-18184", "skip": "already held: the reading votes in cross_validate.py"},
           [None]), (got[0][0], [w for w, _ in got[0][1]]))
    check("a new number's reading is written there as the Mac writes it",
          ({"number": 99999, "id": "times-99999"}, [None, ["held", 99999]], new),
          (got[1][0], [w and list(w) for w, _ in got[1][1]], got[1][1][1][1]))
    root = Path(tempfile.mkdtemp(dir=tmp))
    (root / "held").mkdir()
    (root / "held" / "18184.json").write_bytes(json.dumps({**held, "title": "a \u2014 b"}, ensure_ascii=False).encode())
    ocr_remote.decide_here([({"number": 18184}, None)], {"series": "times", "puzzles": None, "asked": [], "held": [],
                                                        "scans": []}, root)
    check("the Mac's files are read there as ASCII, whatever the desktop's default encoding (cp1252)",
          True, (root / "held" / "18184.json").read_bytes().isascii())
    check("a title that opens a file the Mac was not asked about is decided on the Mac",
          None, there([({"number": 99999}, new)], [], {}))

    # An edition queue scan runs whole there (ocr_remote.scan): the headings it
    # finds and the title readings it caches are a scan's here. The readers are
    # stubbed: a word per crop, from the crop's size.
    from PIL import Image, ImageDraw
    ed = tmp / "eds" / "GaleTimes1976UKEnglish" / "1976-07-02"
    ed.mkdir(parents=True)
    (ed / "pages.json").write_text(json.dumps({"date": "1976-07-02", "item": "GaleTimes1976UKEnglish",
                                               "crossword_pages": [{"leaf": 0}]}))
    leaf = Image.new("RGB", (1600, 2000), "white")
    ImageDraw.Draw(leaf).rectangle((400, 600, 1100, 1300), fill="black")
    leaf.save(ed / "leaf_0000.jpg")
    fa.read_words = lambda crop, which: [(5, 5, 300, 40, f"Crossword No {14000 + crop.width % 997:,}")]
    def scanned(crops, how):
        fa.CROPS = crops
        found = json.loads(json.dumps(how(ed)))
        return found, {p.relative_to(crops).as_posix(): p.read_bytes() for p in crops.rglob("*") if p.is_file()}
    here = scanned(tmp / "crops-here", fa._scan)
    check("a scan there gives a scan here's headings and cached readings", here,
          scanned(tmp / "crops-mac", ocr_remote.scan))
    check("and finds a title and caches its readings (both are in the comparison)", (True, True),
          (len(here[0]["puzzles"]) > 0, len(here[1]) > 0))

    # Off the desktop an OCR process runs OCR_THREADS threads, or one: cv2's
    # pool ignores OMP_NUM_THREADS, so it is capped beside onnxruntime's, and
    # cv2 is imported only through that cap.
    import ast
    was = os.environ.pop("OCR_THREADS", None)
    cv2 = ocr_clues.capped_cv2()
    check("off the desktop cv2 and onnxruntime run one thread", (1, 1),
          (cv2.getNumThreads(), ocr_clues.engine_threads()["intra_op_num_threads"]))
    os.environ["OCR_THREADS"] = "3"
    check("and OCR_THREADS when it is set", (3, 3),
          (ocr_clues.engine_threads()["intra_op_num_threads"], ocr_clues.capped_cv2().getNumThreads()))
    os.environ.pop("OCR_THREADS")
    if was is not None:
        os.environ["OCR_THREADS"] = was
    def imports_cv2(path):
        return any(isinstance(n, ast.Import) and any(a.name == "cv2" for a in n.names)
                   or isinstance(n, ast.ImportFrom) and n.module == "cv2" for n in ast.walk(ast.parse(path.read_text())))
    # ocr_clues is the cap; ocr_remote only reports cv2's version; qr_check reads no text.
    check("cv2 is imported through ocr_clues.capped_cv2 alone", [],
          sorted(p.name for p in Path(".").glob("*.py")
                 if p.name not in ("ocr_clues.py", "ocr_remote.py", "qr_check.py") and imports_cv2(p)))

    # A search on a busy desktop outlives any fixed answer time while working:
    # the wait is on silence, not on a total. serve() runs here with the search
    # stubbed slow and the heartbeat quick, and a Session reads it over a pipe.
    import subprocess
    desktop = r"""
    import json, sys, time
    import acquire_book, ocr_remote
    ocr_remote.SEARCH_HEARTBEAT = 0.2
    ocr_remote.full_speed = lambda *a: None
    ocr_remote.versions = lambda: {}
    def slow(job):
        time.sleep(job["sleep"])
        return {"book_number": job["book_number"], "status": "exact-unique"}
    acquire_book._reconstruct_one = slow
    ocr_remote.serve()
    """
    desktop = textwrap.dedent(desktop)  # python -c takes no indented first line
    def session_on(code):
        s = ocr_remote.Session.__new__(ocr_remote.Session)
        s.host, s.buf = "nohost", b""
        s.err = tempfile.TemporaryFile()  # so a child that dies says why
        s.proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=s.err)
        s.answer(10)  # the ready line
        return s
    ocr_remote.SEARCH_SILENCE = ocr_remote.READ_TIMEOUT = 1  # a fixed 1s total would lose the 2.5s search
    s = session_on(desktop)
    check("a search running past SEARCH_SILENCE is waited on while it beats",
          "exact-unique", s.reconstruct({"book_number": 7, "sleep": 2.5}).get("status"))
    check("and the session answers the next search", 8,
          s.reconstruct({"book_number": 8, "sleep": 0}).get("book_number"))
    s.close()
    s = session_on("import sys, time; print('{\"ready\": {}}', flush=True); time.sleep(30)")
    try:
        s.reconstruct({"book_number": 9})
        check("a silent desktop is lost after SEARCH_SILENCE", "Unavailable", "an answer")
    except ocr_remote.Unavailable as e:
        check("a silent desktop is lost after SEARCH_SILENCE", "no answer in 1s", str(e))
    s.close()

    at_once, most = [0], [0]
    lock = threading.Lock()
    def read_here():
        with ocr_remote.local_slot():
            with ocr_remote.local_slot():  # a read's crops, inside the read: no second slot
                with lock:
                    at_once[0] += 1
                    most[0] = max(most[0], at_once[0])
                time.sleep(0.3)
                with lock:
                    at_once[0] -= 1
    threads = [threading.Thread(target=read_here) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("no more than LOCAL_SLOTS reads run here at once", 2, most[0])
    # A scan's sessions run above the reads' on the desktop: the serve command
    # names the priority the Mac process asked for, and serve takes it.
    import subprocess
    started = []
    class FakeProc:
        stdout = stdin = None
    real_popen, real_answer = subprocess.Popen, ocr_remote.Session.answer
    subprocess.Popen = lambda argv, **k: started.append(argv[-1]) or FakeProc()
    ocr_remote.Session.answer = lambda self, timeout: {"ready": {}}
    ocr_remote.code_dir = lambda: "C:\\code"
    try:
        for asked in (None, "scan", "bogus"):
            if asked is None:
                os.environ.pop("OCR_REMOTE_PRIORITY", None)
            else:
                os.environ["OCR_REMOTE_PRIORITY"] = asked
            ocr_remote.Session("h")
    finally:
        subprocess.Popen, ocr_remote.Session.answer = real_popen, real_answer
        os.environ.pop("OCR_REMOTE_PRIORITY", None)
    check("serve runs idle unless a scan asks; an unknown ask is idle", ["idle", "scan", "idle"],
          [c.rsplit(" ", 1)[1] for c in started])
    check("idle for reads, below normal (under a game's normal) for scans", {"idle": 0x40, "scan": 0x4000},
          ocr_remote.PRIORITIES)
    # Pruning the desktop's old code: only v-*/part-* directories older than the
    # days, never the current hash's, never one a running process names.
    now = 1_000_000_000
    old, new = now - 30 * 86400, now - 86400
    dirs = {"v-aaa1": old, "v-bbb2": old, "v-cur": old, "v-fresh": new, "part-ccc-1f": old, "part-ddd-2": new,
            "venv": old, "tess": old, "v-run": old}
    dirs = {k.replace("cur", "c0de").replace("fresh", "f00d").replace("run", "ab12"): v for k, v in dirs.items()}
    cmds = [r"C:\Users\micro\ocrw\venv\Scripts\python.exe C:\Users\micro\ocrw\V-AB12\tools\ocr_remote.py serve idle"]
    check("prune picks old unused v-/part- directories, not current, fresh, running or non-code ones",
          ["part-ccc-1f", "v-aaa1", "v-bbb2"], ocr_remote.prunable(dirs, cmds, "v-c0de", now))
    sys.exit(1 if fails else 0)


def block2():
    import ast, importlib.abc, sys
    from pathlib import Path
    POSIX_ONLY = {"fcntl", "termios", "pwd", "grp", "resource"}
    import ocr_remote
    reach, todo = set(), ["ocr_remote"] + [f.split(".")[0] for f in ocr_remote.CALLS.values() if isinstance(f, str)]
    while todo:
        m = todo.pop()
        if m in reach or not Path(f"{m}.py").exists():
            continue
        reach.add(m)
        for node in ast.walk(ast.parse(Path(f"{m}.py").read_text())):
            if isinstance(node, ast.Import):
                todo += [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                todo.append(node.module.split(".")[0])
    class NoPosix(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name in POSIX_ONLY:
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)
    for m in POSIX_ONLY:
        sys.modules.pop(m, None)
    sys.meta_path.insert(0, NoPosix())
    bad = []
    for mod in sorted(reach):
        try:
            __import__(mod)
        except ModuleNotFoundError as e:
            if e.name in POSIX_ONLY:
                bad.append(f"{mod} ({e.name})")
    if bad:
        print(f"FAIL these desktop modules import a POSIX-only module at the top (import it where it is used): {bad}")
    else:
        print(f"ok   the {len(reach)} modules the desktop can import need none of {sorted(POSIX_ONLY)}")
    sys.exit(1 if bad else 0)


def block3():
    global fails
    import os, socket, sys, threading, types
    from pathlib import Path
    Path(os.environ["OCR_GPU_HOME"], "gpu").mkdir(parents=True)
    import numpy as np
    fake = types.ModuleType("rapidocr_onnxruntime")
    class Real:
        def __init__(self, **kw): self.kw = kw
        def __call__(self, img, use_det=None, use_cls=None, use_rec=None, **kw):
            return [[[[0.0, 1.0], [2.5, 1.0], [2.5, 3.0], [0.0, 3.0]], "cpu", 0.75]], [0.1]
    fake.RapidOCR = Real
    sys.modules["rapidocr_onnxruntime"] = fake
    import ocr_gpu
    fails = 0
    def check(what, want, got):
        global fails
        if want == got:
            print(f"ok   {what}")
        else:
            fails += 1
            print(f"FAIL {what}: expected {want!r}, got {got!r}")
    def gpu_engine(model):
        return lambda img, use_cls: ([[[[0.5, 1.25], [9.0, 1.25], [9.0, 4.0], [0.5, 4.0]], f"gpu {model} {int(img.sum())}", 0.9876543210987654]], [0.01, 0.0, 0.02])
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); sock.listen(8)
    ocr_gpu.PORT = sock.getsockname()[1]
    server = ocr_gpu.Server(gpu_engine)
    threading.Thread(target=server.accept, args=(sock,), daemon=True).start()
    ocr_gpu.install()
    import rapidocr_onnxruntime
    check("install() leaves an engine with other settings plain", Real, type(rapidocr_onnxruntime.RapidOCR(det_use_cuda=True)))
    eng = rapidocr_onnxruntime.RapidOCR(rec_model_path=Path("/m/en5.onnx"), intra_op_num_threads=2, inter_op_num_threads=1)
    check("install() makes the readers' engines GPU-first", ocr_gpu.GpuFirst, type(eng))
    img = np.full((4, 5, 3), 2, dtype=np.uint8)
    def fresh():
        ocr_gpu._CLIENT.close(); ocr_gpu._CLIENT.down_until = 0
    check("a plain read is the server's answer, unchanged", gpu_engine("/m/en5.onnx")(img, False), eng(img, use_cls=False))
    check("a read with other options is the CPU engine's", "cpu", eng(img, use_cls=True)[0][0][1])
    server.inside = ocr_gpu.QUEUE
    check("a busy server leaves the read to the CPU at once", "cpu", eng(img, use_cls=False)[0][0][1])
    server.inside = 0
    check("the server reads again once not busy", "gpu /m/en5.onnx 120", eng(img, use_cls=False)[0][0][1])
    server.version = "other"
    check("a server of another version is not used", "cpu", eng(img, use_cls=False)[0][0][1])
    server.version = ocr_gpu.VERSION
    check("nor asked again until DOWN_FOR is over", "cpu", eng(img, use_cls=False)[0][0][1])
    fresh()
    ocr_gpu.OFF.touch()
    check("gpu-off reads on the CPU", "cpu", eng(img, use_cls=False)[0][0][1])
    ocr_gpu.OFF.unlink()
    fresh()
    sock.close()
    spare = socket.socket(); spare.bind(("127.0.0.1", 0)); ocr_gpu.PORT = spare.getsockname()[1]; spare.close()
    ocr_gpu.hold("test: VRAM free 100 MB < 4096 MB")
    check("no server: the CPU reads", "cpu", eng(img, use_cls=False)[0][0][1])
    check("a held server is not started", False, ocr_gpu.STARTED.exists())
    check("the session counts where each read went", (6, 2), (ocr_gpu._STATS["cpu"], ocr_gpu._STATS["gpu"]))
    sys.exit(1 if fails else 0)


def block4():
    global fails
    import os
    from pathlib import Path
    import ocr_remote

    fails = 0
    def check(what, want, got):
        global fails
        if want == got:
            print(f"ok   {what}")
        else:
            fails += 1
            print(f"FAIL {what}: expected {want!r}, got {got!r}")

    def woken():
        p = Path(os.environ["WOKEN"])
        return p.read_text().splitlines() if p.exists() else []

    # The checkout moved on under a running process (a job's worktree reset to
    # a newer master): ship() sends the code the process runs (code_dir()), from
    # its git tree, not the checkout's newer files: those made a v-<new> the
    # session never opened, so every reconnect shipped again and failed.
    import io, subprocess, tarfile
    import tempfile
    repo = Path(tempfile.mkdtemp()) / "moved"
    (repo / "tools").mkdir(parents=True)
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout
    git("init", "-q")
    (repo / "tools" / "a.py").write_text("v1\n")
    (repo / "tools" / "b.py").write_text("same\n")
    git("add", "tools")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one")
    tree1 = git("rev-parse", "HEAD:tools").strip()
    kept_tools, kept_kept, kept_run = ocr_remote.TOOLS, ocr_remote.KEPT, ocr_remote.subprocess.run
    ocr_remote.TOOLS, ocr_remote.KEPT = repo / "tools", repo / "kept"
    h1 = ocr_remote.code_hash()
    (repo / "tools" / "a.py").write_text("v2\n")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "two")
    h2 = ocr_remote.code_hash()
    ocr_remote._VERSIONS["local"] = {"code": h1}
    old_files = ocr_remote.code_files()
    check("a moved checkout: the process's own code, from its git tree", (h1, b"v1\n", b"same\n"),
          (ocr_remote.hash_of(old_files), old_files["tools/a.py"], old_files["tools/b.py"]))
    sent = []
    def run(args, **kw):
        if args[0] != "ssh":
            return kept_run(args, **kw)
        sent.append((args[-1], kw["input"]))
        return subprocess.CompletedProcess(args, 0, b"", b"")
    ocr_remote.subprocess.run = run
    kept_prune, ocr_remote.prune = ocr_remote.prune, lambda host, keep, days=1: None
    ocr_remote.ship("micro@100.68.145.15")
    with tarfile.open(fileobj=io.BytesIO(sent[0][1])) as tar:
        shipped_a = tar.extractfile("tools/a.py").read()
    check("ship() makes the v- directory the session opens, with that code in it", (True, b"v1\n"),
          (rf"\v-{h1}" in sent[0][0], shipped_a))
    # A failed ren with v-<code> not (yet) complete is retried, then says what happened.
    cmd = sent[0][0]
    check("ship_command: a failed ren with no manifest names the rename, not 'remove it'", (True, False),
          (f"{ocr_remote.SHIP_RENAME_FAILED} " in cmd, "remove it" in cmd))
    check("ship_command: always drops the part directory", True, 'rmdir /s /q' in cmd)
    waits, tries = [], []
    kept_sleep, ocr_remote.time.sleep = ocr_remote.time.sleep, waits.append
    def flaky(fail_times):
        def run_flaky(args, **kw):
            if args[0] != "ssh":
                return kept_run(args, **kw)
            tries.append(1)
            if len(tries) <= fail_times:
                return subprocess.CompletedProcess(args, 1, b"", f"{ocr_remote.SHIP_RENAME_FAILED} X is absent".encode())
            return subprocess.CompletedProcess(args, 0, b"", b"")
        return run_flaky
    ocr_remote.subprocess.run = flaky(2)
    ocr_remote.ship("micro@100.68.145.15")
    check("ship(): a transient rename failure is shipped again until it lands", (3, 2), (len(tries), len(waits)))
    del tries[:], waits[:]
    ocr_remote.subprocess.run = flaky(99)
    try:
        ocr_remote.ship("micro@100.68.145.15")
        said = None
    except ocr_remote.Unavailable as e:
        said = str(e)
    check("ship(): a rename failing every try gives up, saying so", (ocr_remote.SHIP_TRIES, True),
          (len(tries), said is not None and ocr_remote.SHIP_RENAME_FAILED in said))
    ocr_remote.time.sleep = kept_sleep
    ocr_remote.subprocess.run = kept_run
    ocr_remote._VERSIONS["local"] = {"code": h2}
    check("mirror: an unmoved checkout ships its own files", h2, ocr_remote.hash_of(ocr_remote.code_files()))
    ocr_remote._VERSIONS["local"] = {"code": "0123456789ab"}
    try:
        ocr_remote.code_files()
        gone = None
    except ocr_remote.Unavailable as e:
        gone = "restart it" in str(e)
    check("code in neither the checkout nor git: Unavailable, nothing shipped", True, gone)
    ocr_remote.TOOLS, ocr_remote.KEPT, ocr_remote.prune = kept_tools, kept_kept, kept_prune

    class S:
        def __init__(self, host): self.host = host
        def close(self): pass

    up = {"micro@100.68.145.15"}
    tried = []
    def opened(host, tries=3, timeout=ocr_remote.CONNECT_TIMEOUT):
        tried.append(host)
        if host not in up:
            raise ocr_remote.Unavailable("Host key verification failed.")
        return S(host)
    ocr_remote.opened = opened
    ocr_remote.matched = lambda s: (s, None)
    ocr_remote.ship = lambda host: (_ for _ in ()).throw(ocr_remote.Unavailable("shipping the code failed (255): ssh: connect to host port 22: Connection timed out"))
    ocr_remote._VERSIONS["local"] = {}
    busy = [None]
    ocr_remote.desktop_busy.busy = lambda hosts: busy[0]

    s = ocr_remote.connect()
    check("a stale LAN address falls back to the tailnet", "micro@100.68.145.15", s and s.host)
    check("a LAN address is tried first", True, tried[0] in ("micro@192.168.1.180", "micro@192.168.1.198"))
    check("every desktop address is tried, not only OCR_REMOTE's", 3, len(set(tried)))
    check("the fallback sends one line", 1, sum("fell back to micro@100.68.145.15" in l for l in woken()))
    ocr_remote.connect()
    check("and only once", 1, sum("fell back" in l for l in woken()))
    check("a LAN that never answered says so", True,
          any("fell back to micro@100.68.145.15 (no LAN address answers)" in l for l in woken()))

    # A LAN host that answers but lacks the code dir (2026-10-15: v-9001...)
    # ships it there and waits out its cold start, no other address tried.
    missing = (r"ssh exited (2): C:\Users\micro\AppData\Local\Programs\Python\Python312\python.exe: can't open file "
               r"'C:\\Users\\micro\\ocrw\\v-9001b5b16ede\\tools\\ocr_remote.py': [Errno 2] No such file or directory")
    check("code_missing reads the hash from python's error", "9001b5b16ede", ocr_remote.code_missing(missing))
    check("an unreachable host is not missing code", None,
          ocr_remote.code_missing("ssh exited (255): ssh: connect to host 192.168.1.180 port 22: Connection refused"))
    lan = "micro@192.168.1.198"
    on_desk, ships, waits = set(), [], []
    def opened_code(host, tries=3, timeout=ocr_remote.CONNECT_TIMEOUT):
        tried.append(host)
        waits.append((host, timeout))
        if host not in up:
            raise ocr_remote.Unavailable("ssh exited (255): ssh: connect to host port 22: Connection refused")
        if "code" not in on_desk:
            raise ocr_remote.Unavailable(missing)
        if timeout < cold_start[0]:
            raise ocr_remote.Unavailable(f"no answer in {timeout}s")
        return S(host)
    def ship_code(host):
        ships.append(host)
        on_desk.add("code")
    ocr_remote.opened, ocr_remote.ship = opened_code, ship_code
    up.clear()
    up.update({lan, "micro@100.68.145.15"})
    cold_start = [90]  # seconds the fresh copy's first serve takes
    del tried[:]
    s = ocr_remote.connect()
    check("a missing code dir on a LAN host is shipped to that host", [lan], ships)
    check("and the session opens there, not on the tailnet", lan, s and s.host)
    check("the open after shipping waits out a cold start", True, (lan, ocr_remote.COLD_TIMEOUT) in waits)
    check("nothing alerts", 1, sum("fell back" in l for l in woken()))

    # When the LAN session still fails after the ship, the alert says what
    # failed: the code dir missing and the slow start, not a dead LAN.
    (ocr_remote.ALERT_STAMPS / "fallback-micro@100.68.145.15").unlink(missing_ok=True)
    on_desk.clear()
    del ships[:], waits[:]
    cold_start = [ocr_remote.COLD_TIMEOUT + 1]
    real_ship = ship_code
    def ship_then_warm(host):  # the tailnet's open, after the LAN's, finds it warm
        real_ship(host)
        if host == "micro@100.68.145.15":
            cold_start[0] = 0
    ocr_remote.ship = ship_then_warm
    s = ocr_remote.connect()
    line = [l for l in woken() if "fell back" in l][-1:]
    check("a LAN session that fails after connecting falls back", "micro@100.68.145.15", s and s.host)
    check("its alert does not say no LAN address works", False, any("no LAN address" in l for l in line))
    check("its alert names the missing code dir and the later failure", True,
          any("after a LAN session failed" in l and "its code dir v-9001b5b16ede was missing" in l
              and f"no answer in {ocr_remote.COLD_TIMEOUT}s" in l for l in line))
    ocr_remote.opened = opened
    ocr_remote.ship = lambda host: (_ for _ in ()).throw(ocr_remote.Unavailable("shipping the code failed (255): ssh: connect to host port 22: Connection timed out"))
    up.clear()
    up.add("micro@100.68.145.15")

    up.clear()
    for _ in range(3):
        check("no host works: no session", None, ocr_remote.connect())
    check("no host works: one alert for the episode, not one per edition", 1,
          sum("no desktop host works" in l for l in woken()))
    up.add("micro@100.68.145.15")
    ocr_remote.connect()
    up.clear()
    ocr_remote.connect()
    check("a session minutes after the alert does not end the episode: the next failure sends none", 1,
          sum("no desktop host works" in l for l in woken()))
    import time
    aged = time.time() - ocr_remote.ALERT_QUIET - 1
    os.utime(ocr_remote.ALERT_STAMPS / "down", (aged, aged))
    up.add("micro@100.68.145.15")
    ocr_remote.connect()
    up.clear()
    ocr_remote.connect()
    check("a session once the alert is ALERT_QUIET old ends it: a new outage alerts again", 2,
          sum("no desktop host works" in l for l in woken()))
    ocr_remote.alert_over("down")
    busy[0] = "playing Wow"
    ocr_remote.connect()
    check("a game-yield sends no alert", 2, sum("no desktop host works" in l for l in woken()))
    busy[0] = None
    ocr_remote.alert_over("down")
    saved = os.environ["OCR_REMOTE"]
    os.environ["OCR_REMOTE"] = "nobody@127.0.0.1"
    ocr_remote.connect()
    os.environ["OCR_REMOTE"] = saved
    check("a loopback desktop (a test's stand-in) sends no alert", 2, sum("no desktop host works" in l for l in woken()))

    pruned = []
    def prune(host, keep, days=1):
        pruned.append(host)
        if host.endswith((".180", ".198")):
            raise ocr_remote.Unavailable("Host key verification failed.")
        return {"deleted": 0, "failed": 0, "bytes": 0}
    ocr_remote.prune = prune
    check("prune falls back to the next host too", {"deleted": 0, "failed": 0, "bytes": 0},
          ocr_remote.prune_any(ocr_remote.hosts(), keep="v-x"))
    check("prune tries hosts in connect()'s order", ["micro@192.168.1.198", "micro@192.168.1.180", "micro@100.68.145.15"], pruned)
    raise SystemExit(1 if fails else 0)


def block5():
    global fails
    import os, subprocess, sys
    from pathlib import Path
    import ocr_remote

    fails = 0
    def check(what, want, got):
        global fails
        if want == got:
            print(f"ok   {what}")
        else:
            fails += 1
            print(f"FAIL {what}: expected {want!r}, got {got!r}")

    repo = Path(os.environ["CT_REPO"])
    (repo / "tools" / "data").mkdir(parents=True)
    def git(*a):
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()
    def commit(files, msg):
        for name, text in files.items():
            (repo / name).write_text(text)
        git("add", "-A")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)
    git("init", "-q")
    commit({"tools/a.py": "A1\n", "tools/b.py": "B1\n", "tools/desktop_hosts.json": "[\"h1\"]\n"}, "one")
    ocr_remote.TOOLS = repo / "tools"
    ocr_remote.KEPT = repo.parent / "kept"

    def fresh_process():
        ocr_remote._TREES.clear()
        ocr_remote._VERSIONS.clear()
    def took():
        fresh_process()
        ocr_remote._VERSIONS["local"] = {"code": ocr_remote.code_hash()}
        return ocr_remote._VERSIONS["local"]["code"]
    def shipped_hash():
        return ocr_remote.hash_of(ocr_remote.code_files())

    one = took()
    check("a clean tree's hash is its files'", ocr_remote.hash_of(ocr_remote.shipped()), one)
    commit({"tools/desktop_hosts.json": "[\"h2\", \"h1\"]\n"}, "reorder hosts")
    check("a push moving the checkout on still ships the hash taken", one, shipped_hash())
    ocr_remote._TREES.clear()
    check("and so does another process, from KEPT", one, shipped_hash())

    # Mid-reset: one file new, one old, matching no commit.
    (repo / "tools" / "a.py").write_text("A2\n")
    torn = took()
    commit({"tools/a.py": "A2\n", "tools/b.py": "B2\n"}, "the reset's far side")
    check("a hash taken mid-reset names files no commit holds", True,
          torn not in {one, ocr_remote.hash_of(ocr_remote.shipped())})
    check("and is still shipped once the reset is done", torn, shipped_hash())
    ocr_remote._TREES.clear()
    check("by another process too (its tree kept)", torn, shipped_hash())
    check("the checkout itself was left alone", "", git("status", "--porcelain"))
    fresh_process()
    ocr_remote._VERSIONS["local"] = {"code": "0123456789ab"}
    try:
        ocr_remote.code_files()
        check("a hash nothing holds is refused", "Unavailable", "shipped")
    except ocr_remote.Unavailable:
        check("a hash nothing holds is refused", 1, 1)
    raise SystemExit(1 if fails else 0)

def show(out):
    print(out, end="" if out.endswith("\n") or not out else "\n")


try:
    out, rc = run_block(block1, merge=False, TMP=str(tmp), TMPDIR=str(tmp), OCR_REMOTE="nohost", OCR_LOCAL_SLOTS="2")
    show(out)

    # The desktop is Windows: every module its serve path can import (each
    # import statement, in a function or not, followed from ocr_remote and the
    # modules its CALLS name) must
    # import without the POSIX-only modules, or each read there fails and runs
    # here instead.
    out, rc2 = run_block(block2, merge=False)
    show(out)

    # The shared GPU server (tools/ocr_gpu.py): a session's plain RapidOCR read
    # is the server's answer, unchanged through JSON; anything else, a busy or
    # other-version server, none at all, or gpu-off, is read on the session's
    # own CPU engine at once, and a held server is not started.
    out, rc3 = run_block(block3, merge=False, OCR_GPU_HOME=str(tmp / "gpuhome"))
    show(out)

    # A stale LAN address falls back to the next host (the tailnet), prune does
    # the same, and a desktop no host reaches alerts once an episode through
    # alert.sh (its wake.sh stubbed to a file), never while yielding to a game.
    (tmp / "hh" / "tools").mkdir(parents=True)
    wake = tmp / "hh" / "tools" / "wake.sh"
    wake.write_text(f'#!/bin/bash\necho "$*" >> {shlex.quote(str(tmp / "woken"))}\n')
    wake.chmod(wake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    out, rc4 = run_block(block4, merge=False, TMPDIR=str(tmp), ALERT_ENV_FILE=str(tmp / "hh" / ".env"),
                         ALERT_STATE_DIR=str(tmp / "as"), HOUSEHOLD_LIVE_CHECKOUT="",
                         OCR_REMOTE="micro@100.68.145.15,micro@192.168.1.180", WOKEN=str(tmp / "woken"))
    show(out)

    # The code a process took its hash of can always be shipped, however its
    # checkout moved since: on 2026-10-14 the full pass's tree was caught
    # mid-reset (half old files, half new), every unit hashed files no commit
    # holds, kept nowhere, and each ship failed "no longer in the checkout ...
    # restart it", the reads falling back to the 4-core host. A throwaway repo.
    out, rc5 = run_block(block5, merge=False, CT_REPO=str(tmp / "coderepo"))
    show(out)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if (rc or rc2 or rc3 or rc4 or rc5) else 0)
