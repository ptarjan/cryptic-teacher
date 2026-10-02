#!/bin/bash
# Does tools/fetch_trove.py retry a timed-out or 5xx request, give up on one
# article with a line naming it, and carry on? Offline: the opener is stubbed.
#
#     bash tools/test_fetch_trove.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$REPO/tools" <<'PY'
import sys, socket, urllib.error
sys.path.insert(0, sys.argv[1])
import fetch_trove as ft
ft.BACKOFF = 0
import tempfile
tv = ft.Trove(tempfile.mkdtemp(), 0, 600)
calls = []
def script(*steps):
    it = iter(steps); calls.clear()
    def op(url, headers):
        calls.append(url); s = next(it)
        if isinstance(s, Exception): raise s
        return s
    tv._open = op
fails = 0
def check(what, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + what); fails += not ok
script(socket.timeout("timed out"), (500, b"x"), (200, b"fine"))
check("timeout then 500 then ok", tv.get("/a")[1] == b"fine" and len(calls) == 3)
script(*[(500, b"boom")] * 4)
try: tv.get("/tile/9"); msg = ""
except ft.Transient as e: msg = str(e)
check("persistent 500 raises Transient naming url and status", "HTTP 500" in msg and "/tile/9" in msg)
script(urllib.error.URLError("timed out"), (403, b"no"))
try: tv.get("/b"); msg = ""
except ft.Transient: msg = "transient"
except RuntimeError as e: msg = str(e)
check("4xx is not retried and stays loud", "HTTP 403" in msg and len(calls) == 2)
sys.exit(1 if fails else 0)
PY
