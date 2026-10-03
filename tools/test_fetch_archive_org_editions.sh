#!/bin/bash
# Does tools/fetch_archive_org_editions.py retry a 5xx only within the
# edition's ITEM_SECONDS, then raise so the run moves on? Offline: urlopen is
# stubbed.
#
#     bash tools/test_fetch_archive_org_editions.sh
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$REPO/tools" <<'PY'
import contextlib, io, sys, tempfile, time, urllib.error
sys.path.insert(0, sys.argv[1])
import fetch_archive_org_editions as fa
fa.RETRY_WAITS = (0, 0, 0)
calls = []
def script(*steps):
    it = iter(steps); calls.clear()
    def urlopen(req, timeout):
        calls.append(req.full_url); s = next(it)
        if isinstance(s, Exception): raise s
        return contextlib.nullcontext(io.BytesIO(s))
    fa.urllib.request.urlopen = urlopen
def e500():
    return urllib.error.HTTPError("u", 500, "boom", {}, None)
fails = 0
def check(what, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + what, file=sys.stderr); fails += not ok
fx = fa.Fetcher(tempfile.mkdtemp(), 0)
with contextlib.redirect_stdout(io.StringIO()):
    script(e500(), e500(), b"fine")
    check("500s retried within the edition's time", fx.get("https://x/a", "a") == b"fine" and len(calls) == 3)
    fx.deadline = time.monotonic() - 1
    script(e500(), b"never")
    try: fx.get("https://x/b", "b"); code = None
    except urllib.error.HTTPError as e: code = e.code
    check("no retry past the edition's deadline", code == 500 and len(calls) == 1)
    script(urllib.error.URLError("refused"), b"never")
    try: fx.get("https://x/c", "c"); msg = ""
    except urllib.error.URLError as e: msg = str(e)
    check("network error past the deadline raises too", "refused" in msg and len(calls) == 1)
sys.exit(1 if fails else 0)
PY
