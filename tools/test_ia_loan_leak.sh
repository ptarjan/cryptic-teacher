#!/bin/bash
# Does a killed borrow leak its loan, and does the next run clean it up?
#
#     bash tools/test_ia_loan_leak.sh
#
# tools/fetch_ia_book.py's borrowed() returns the loan from a finally clause,
# and tools/test_ia_borrow.sh case 9 shows that clause covering normal exit,
# an exception and a Ctrl-C. None of that is a signal. A process killed by
# SIGKILL runs no Python at all on the way out, and neither does one killed by
# plain SIGTERM, which is what `timeout N` sends and therefore how a hung book
# in a long acquisition run actually dies. The loan then stays out for its
# full hour with nothing on the machine's side even aware of it.
#
# That is not fixable inside the dying process, so it is fixed in the next
# one: the ledger records the loan before the block runs, and the next
# borrowed() reconciles it away before taking a loan of its own. This file is
# the evidence for both halves, and it gets them by actually doing it — a
# real child process, really killed by a real signal, against a stub
# archive.org that tracks who holds what and would notice a return.
#
# The stub is a local HTTP server, so this costs archive.org nothing and
# needs no credentials. The child stands a ten-line urllib shim in for
# `requests` when it is missing rather than skipping: CI installs no
# third-party packages, and a check that quietly does not run on the only
# machine that runs it on every push is not a check.
set -u
cd "$(dirname "$0")/.."

python3 - <<'PYEOF'
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

TOOLS = os.path.abspath("tools")
failures = []


def fail(msg):
    failures.append(msg)
    print(f"  FAIL {msg}")


def ok(msg):
    print(f"  ok   {msg}")


# --------------------------------------------------------------- the stub
# Tracks which identifiers this account holds, so availability answers
# truthfully and a return that never happened cannot be faked by the test.
on_loan = set()
events = []
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/services/csrf-token"):
            return self._send({"success": True, "value": {"token": "stub"}})
        self._send({"error": "no"}, 404)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.startswith("/services/account/login/"):
            return self._send({"success": True})
        form = urllib.parse.parse_qs(raw.decode())
        action = form.get("action", [""])[0]
        ident = form.get("identifier", [""])[0]
        with lock:
            events.append((action, ident))
            if action == "browse_book":
                on_loan.add(ident)
                return self._send({"success": True})
            if action == "create_token":
                return self._send({"token": "stub-token"})
            if action == "return_loan":
                on_loan.discard(ident)
                return self._send({"success": True})
            if action == "availability":
                return self._send({"status": "OK", "lending_status": {
                    "is_lendable": True, "is_readable": False,
                    "user_has_browsed": ident in on_loan,
                    "user_loan_record": [], "user_loan_count": len(on_loan),
                    "user_at_max_loans": False}})
        self._send({"error": f"unexpected action {action}"}, 400)


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"

scratch = tempfile.mkdtemp(prefix="ia-loan-leak-")
creds = os.path.join(scratch, "creds")
open(creds, "w").write("someone@example.com\nhunter2\n")
ledger = os.path.join(scratch, "ia-loans.json")

CHILD = f'''
import os, sys, time
sys.path.insert(0, {TOOLS!r})
try:
    import requests
except ModuleNotFoundError:
    # Enough of requests for fetch_ia_book: a session with headers, get with
    # params, post with a form dict or a JSON string body, and a response
    # exposing status_code/text/ok/json(). The stub checks no cookies, so
    # none are carried.
    import json as _json, types, urllib.error, urllib.parse, urllib.request

    class _Resp:
        def __init__(self, code, body):
            self.status_code, self.text = code, body
            self.ok = 200 <= code < 300

        def json(self):
            return _json.loads(self.text)

        def raise_for_status(self):
            if not self.ok:
                raise RuntimeError(f"HTTP {{self.status_code}}")

    class _Session:
        def __init__(self):
            self.headers = {{}}

        def _do(self, url, data=None, headers=None, params=None):
            if params:
                url += "?" + urllib.parse.urlencode(params)
            body = None
            if data is not None:
                body = (data.encode() if isinstance(data, str)
                        else urllib.parse.urlencode(data).encode())
            req = urllib.request.Request(
                url, data=body, headers={{**self.headers, **(headers or {{}})}})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return _Resp(r.status, r.read().decode())
            except urllib.error.HTTPError as err:
                return _Resp(err.code, err.read().decode())

        def get(self, url, params=None, timeout=None):
            return self._do(url, params=params)

        def post(self, url, data=None, headers=None, timeout=None):
            return self._do(url, data=data, headers=headers)

    shim = types.ModuleType("requests")
    shim.Session = _Session
    sys.modules["requests"] = shim
import fetch_ia_book as F
F.CSRF_URL = {BASE!r} + "/services/csrf-token"
F.LOGIN_URL = {BASE!r} + "/services/account/login/"
F.LOAN_URL = {BASE!r} + "/services/loans/loan/"
identifier, mode = sys.argv[1], sys.argv[2]
with F.borrowed(identifier):
    print("INSIDE", flush=True)
    if mode == "hang":
        time.sleep(600)
print("DONE", flush=True)
'''

env = dict(os.environ, IA_CREDS=creds, IA_LOAN_LEDGER=ledger)


def spawn(identifier, mode):
    proc = subprocess.Popen([sys.executable, "-c", CHILD, identifier, mode],
                            stdout=subprocess.PIPE, text=True, env=env)
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line.strip() == "INSIDE":
            return proc
        if not line and proc.poll() is not None:
            raise AssertionError(f"child exited before holding the loan: {proc.returncode}")
    raise AssertionError("child never reported holding the loan")


def read_ledger():
    try:
        return json.load(open(ledger))
    except (OSError, ValueError):
        return {}


def returns_for(identifier):
    with lock:
        return [e for e in events if e == ("return_loan", identifier)]


# ------------------------------------------------------- case 1 and case 2
# The two signals that actually end a stuck acquisition: SIGTERM is what
# `timeout N` sends by default, SIGKILL is what it sends with -k or what an
# out-of-memory kill uses. Neither runs a finally clause.
leaked = []
for signame, sig in (("SIGTERM", signal.SIGTERM), ("SIGKILL", signal.SIGKILL)):
    identifier = f"killed-by-{signame.lower()}"
    print(f"case: a holder killed by {signame}")
    with lock:
        events.clear()
    proc = spawn(identifier, "hang")
    # Starting this child ran a reconcile of its own, so anything the
    # PREVIOUS kill left out should already be back — the fix working
    # incidentally, before any test asks it to.
    for earlier in leaked:
        if returns_for(earlier):
            ok(f"starting this run returned {earlier}, leaked by the last one")
        else:
            fail(f"a new run started without returning {earlier}, still out "
                 f"from the previous kill")
    leaked.append(identifier)
    if identifier not in read_ledger():
        fail(f"{signame}: the loan was not on disk while the block ran, so "
             f"nothing could clean it up afterwards")
    proc.send_signal(sig)
    proc.wait(timeout=30)
    if returns_for(identifier):
        fail(f"{signame}: the loan came back — if this ever passes, the "
             f"finally clause is running on a signal and this whole file is "
             f"testing the wrong thing")
    else:
        ok(f"{signame} leaks the loan: no return_loan reached the service")
    with lock:
        still_held = identifier in on_loan
    if not still_held:
        fail(f"{signame}: the stub does not think the loan is still out")
    else:
        ok(f"{signame}: archive.org still has the loan against this account")
    if read_ledger().get(identifier) is None:
        fail(f"{signame}: the ledger lost the leaked loan, so the next run "
             f"has no way to know it is out")
    else:
        ok(f"{signame}: the ledger survived the kill holding the leaked loan")

# ------------------------------------------------------------------ case 3
# The fix. A fresh run of a DIFFERENT book must give both leaked loans back
# before it takes one of its own — and must do it in that order, because the
# whole point is not to be holding them when the new borrow is judged.
print("case: the next run reconciles them away")
# Whatever is still on the ledger at this instant is what a killed run left
# behind and nothing has cleaned up yet. Asking the ledger rather than naming
# identifiers keeps this honest however the cases above shake out.
outstanding = set(read_ledger())
if not outstanding:
    fail("nothing was left outstanding, so this case would prove nothing")
with lock:
    events.clear()
proc = subprocess.run([sys.executable, "-c", CHILD, "freshbook0000xxxx", "quick"],
                      capture_output=True, text=True, env=env, timeout=60)
if proc.returncode != 0:
    fail(f"the reconciling run failed: {proc.returncode} {proc.stderr[-500:]}")
with lock:
    order = [e for e in events if e[0] in ("return_loan", "browse_book")]
first_browse = next((i for i, e in enumerate(order) if e[0] == "browse_book"),
                    len(order))
reconciled = {ident for action, ident in order[:first_browse]
              if action == "return_loan"}
if reconciled != outstanding:
    fail(f"the startup reconcile returned {sorted(reconciled)}, not the "
         f"outstanding {sorted(outstanding)}")
else:
    ok(f"returned {sorted(outstanding)} — every loan a killed run left out — "
       f"BEFORE taking a new loan")
after = {ident for action, ident in order[first_browse:] if action == "return_loan"}
if after - {"freshbook0000xxxx"}:
    fail(f"reconciled after borrowing instead of before: {order}")
else:
    ok("the only return after the new borrow is that borrow's own")
with lock:
    leftover = sorted(on_loan)
if leftover:
    fail(f"the service still holds loans after a clean run: {leftover}")
else:
    ok("the account holds nothing once the clean run finishes")
if read_ledger():
    fail(f"the ledger is not empty after a clean run: {read_ledger()}")
else:
    ok("the ledger is empty again")

# ------------------------------------------------------------------ case 4
# The book the new run is working on is never reconciled out from under it.
print("case: the in-flight book is left alone")
with lock:
    events.clear()
    on_loan.add("inflight0000xxxx")
json.dump({"inflight0000xxxx": "2026-09-19T14:55:00Z"}, open(ledger, "w"))
proc = subprocess.run([sys.executable, "-c", CHILD, "inflight0000xxxx", "quick"],
                      capture_output=True, text=True, env=env, timeout=60)
with lock:
    seq = [e for e in events if e[0] in ("return_loan", "browse_book")]
if seq and seq[0] == ("return_loan", "inflight0000xxxx"):
    fail("returned the loan for the very book it was about to borrow")
else:
    ok("did not return the book it was about to work on")

server.shutdown()
print()
if failures:
    print(f"FAILED: {len(failures)} problem(s)")
    sys.exit(1)
print("PASSED")
PYEOF
