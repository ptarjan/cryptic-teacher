#!/bin/bash
# Does tools/ocr_remote.py compare every reader model a read can load, send
# back an edition whose read on the desktop opened a file it was not sent,
# give the same grids from a search run there (its answer through JSON) as
# here, the same headings and cached readings from a scan run there, wait on a search for as long as the desktop says it is still
# searching, let no more than LOCAL_SLOTS reads run here at once, and does
# every module the desktop imports import without fcntl (Windows)?
#
#     bash tools/test_ocr_remote.sh
#
# No ssh, no OCR: temp dirs only.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

out=$(cd "$REPO/tools" && TMP="$tmp" TMPDIR="$tmp" OCR_REMOTE=nohost OCR_LOCAL_SLOTS=2 python3 - <<'PY'
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
    result, back = ocr_remote.CALLS[name](data, *json.loads(json.dumps(args)), **kwargs)
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
def session_on(code):
    s = ocr_remote.Session.__new__(ocr_remote.Session)
    s.host, s.buf = "nohost", b""
    s.proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
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
sys.exit(1 if fails else 0)
PY
)
rc=$?
echo "$out"

# The desktop is Windows: every module its serve path can import (each
# import statement, in a function or not, followed from ocr_remote) must
# import without the POSIX-only modules, or each read there fails and runs
# here instead.
out=$(cd "$REPO/tools" && python3 - <<'PY'
import ast, importlib.abc, sys
from pathlib import Path
POSIX_ONLY = {"fcntl", "termios", "pwd", "grp", "resource"}
reach, todo = set(), ["ocr_remote"]
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
PY
)
rc2=$?
echo "$out"
exit $(( rc || rc2 ))
