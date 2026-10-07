#!/bin/bash
# Does tools/ocr_remote.py compare every reader model a read can load, send
# back an edition whose read on the desktop opened a file it was not sent,
# give the same grids from a search run there (its answer through JSON) as
# here, wait on a search for as long as the desktop says it is still
# searching, and let no more than LOCAL_SLOTS reads run here at once?
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

# A search on a busy desktop outlives any fixed answer time while working:
# the wait is on silence, not on a total. serve() runs here with the search
# stubbed slow and the heartbeat quick, and a Session reads it over a pipe.
import subprocess
desktop = r"""
import json, sys, time
import acquire_book, ocr_remote
ocr_remote.SEARCH_HEARTBEAT = 0.2
ocr_remote.full_speed = lambda: None
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
sys.exit(1 if fails else 0)
PY
)
rc=$?
echo "$out"
exit $rc
