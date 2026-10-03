#!/bin/bash
# Does tools/fetch_trove.py retry a timed-out or 5xx request within the
# article's time, give up on one article with a line naming it, carry on, and
# stop when every article fails? Offline: the opener is stubbed.
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
# `zones` fetches clue columns only for articles the ledger leaves pending
# without them, at most N a run, and one failure stops nothing.
import io, json, pathlib, contextlib
d = pathlib.Path(tempfile.mkdtemp()); out, zones = d / 'trove', d / 'trove-clues'
for aid in ('1', '2', '3', '4', '5'):
    (out / aid).mkdir(parents=True); (out / aid / 'meta.json').write_text('{}')
(zones / '3').mkdir(parents=True); (zones / '3' / 'zone0.png').write_bytes(b'')
rows = [{'article': '1', 'pending': 'no grid'}, {'article': '2', 'id': 'canberra-1'},
        {'article': '3', 'pending': 'no grid'}, {'article': '4', 'pending': 'no grid'},
        {'article': '5', 'pending': 'no grid'}, {'article': '6', 'pending': 'no grid'}]
(out / 'filed.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
seen = []
def fake(tv_, out_, zones_, aid):
    seen.append(aid)
    if aid == '1':
        raise OSError('HTTP 503')
ft.fetch_zones = fake
want = ft.pending_zones(str(out), str(zones))
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    nfail, stopped = ft.fetch_all_zones(tv, str(out), str(zones), want, 2)
check("zones: only pending articles without zones, capped, past a failure",
      want == ['1', '4', '5'] and (nfail, stopped) == (1, False) and seen == ['1', '4']
      and '503' in buf.getvalue())
# Past its ITEM_SECONDS an article's failed request is not retried.
tv.deadline = 0
script(*[(500, b"boom")] * 4)
try: tv.get("/late"); msg = ""
except ft.Transient as e: msg = str(e)
check("no retry past the article's deadline", "after 1 tries" in msg and len(calls) == 1)
# Articles failing back to back stop the run instead of failing through it.
def down(aid):
    raise ft.Transient("HTTP 503")
with contextlib.redirect_stdout(io.StringIO()) as buf:
    nfail, stopped = ft.each_article(tv, [str(i) for i in range(50)], down, "article")
check("FAILURES_IN_A_ROW failures stop the run",
      (nfail, stopped) == (ft.FAILURES_IN_A_ROW, True) and "Trove looks down" in buf.getvalue())
sys.exit(1 if fails else 0)
PY
