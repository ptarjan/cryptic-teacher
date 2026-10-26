#!/usr/bin/env python3
# Does tools/fetch_trove.py retry a timed-out or 5xx request within the
# article's time, give up on one article with a line naming it, carry on, and
# stop when every article fails? Offline: the opener is stubbed.
#
#     python3 tests/test_fetch_trove.py
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

TOOLS = str(Path(__file__).resolve().parent.parent / "tools")
sys.path.insert(0, TOOLS)
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
import http.cookiejar
def cookie(name):
    return http.cookiejar.Cookie(0, name, "x", None, False, "trove.nla.gov.au", False, False,
                                 "/", True, False, None, False, None, None, {})
tv.jar.set_cookie(cookie("app_affinity")); tv.jar.set_cookie(cookie("JSESSIONID"))
script((503, b"down"), (200, b"fine"))
tv.get("/c")
check("a 5xx drops only the backend-affinity cookie",
      [c.name for c in tv.jar] == ["JSESSIONID"])
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
# `fetch` with no ids reads every cached listing, skips cached articles before
# any request, and --seconds starts none past its end.
tout = pathlib.Path(tempfile.mkdtemp())
(tout / "index").mkdir()
(tout / "index" / "1980.jsonl").write_text('{"id": "7"}\n{"id": "8"}\n')
(tout / "index" / "1981.jsonl").write_text('{"id": "9"}\n{"id": "8"}\n')
(tout / "7").mkdir(); (tout / "7" / "meta.json").write_text("{}")
def trove(*args):
    r = subprocess.run([sys.executable, str(pathlib.Path(TOOLS) / "fetch_trove.py"), *args, "--out", str(tout)],
                       capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr
rc, log = trove("fetch", "--seconds", "1e-9")
check("fetch: every listing, cached skipped, --seconds leaves the rest",
      rc == 0 and "2 article(s) to fetch" in log and "2 article(s) left for the next run" in log
      and "0 requests" in log)
for a in ("8", "9"):
    (tout / a).mkdir(); (tout / a / "meta.json").write_text("{}")
rc, log = trove("fetch")
check("fetch: nothing new costs no request", rc == 0 and "0 article(s) to fetch" in log and "0 requests" in log)
if fails:
    sys.exit(1)

# The fetch plan and the filer's article list list the Trove dirs only until
# the trove-dates / trove-titles / trove-zones manifests are complete; then
# they ask the manifests alone.
t = Path(tempfile.mkdtemp())
try:
    (t / "trove" / "index").mkdir(parents=True)
    (t / "trove" / "7").mkdir()
    (t / ".manifest").mkdir()
    (t / "trove" / "index" / "1980.jsonl").write_text('{"id": "7"}\n{"id": "8"}\n')
    (t / "trove" / "7" / "meta.json").write_text("{}\n")
    (t / "trove" / "filed.jsonl").write_text('{"article": "7", "pending": "x"}\n{"article": "8", "pending": "x"}\n')
    (t / ".manifest" / "trove-dates.jsonl").write_text('{"article": "8"}\n{"article": "9"}\n{"article": "10"}\n')
    (t / ".manifest" / "trove-titles.jsonl").write_text(
        '{"article": "7", "title": "a"}\n{"article": "9", "title": "b"}\n')
    (t / ".manifest" / "trove-zones.jsonl").write_text('{"article": "7", "readings": true}\n')
    q = """import fetch_trove as ft, file_trove_puzzles as t, downloads
print([u["rel"] for u in ft.plan()], [d.name for d in t.article_dirs(downloads.TROVE)])"""

    def plans():
        r = subprocess.run(["python3", "-c", q], cwd=TOOLS, capture_output=True, text=True,
                           env={**os.environ, "CT_DOWNLOADS": str(t)})
        return r.stdout.rstrip("\n")

    before = plans()
    for m in ("trove-dates", "trove-titles", "trove-zones"):
        (t / ".manifest" / f"{m}.complete").write_text("{}\n")
    after = plans()
    if before != "['zones/7', 'article/8'] ['7']":
        print(f"FAIL Trove plans listed: {before}")
        sys.exit(1)
    if after != "['article/8', 'article/10'] ['7', '9']":
        print(f"FAIL Trove plans off the manifests: {after}")
        sys.exit(1)
    print("ok   Trove plans off the manifests once complete")
finally:
    shutil.rmtree(t, ignore_errors=True)
