#!/bin/bash
# Does tools/ocr_remote.py compare every reader model a read can load, send
# back an edition whose read on the desktop opened a file it was not sent,
# give the same grids from a search run there (its answer through JSON) as
# here, and let no more than LOCAL_SLOTS reads run here at once?
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
# en_PP-OCRv3 once did), so each must be in the versions compared.
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
