#!/bin/bash
# Does desktop work yield while Paul games on the desktop, and resume after?
# tools/desktop_busy.py's verdict and its shared, once-a-minute probe; the
# OCR session it closes and abandons (tools/ocr_remote.py); the VLM it turns
# off (tools/vlm_reader.py).
#
#     bash tools/test_desktop_busy.sh
#
# The probe is stubbed: no ssh, no network, nothing written outside a temp dir.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

out=$(cd "$REPO/tools" && TMP="$tmp" python3 - <<'PY'
import fcntl, json, os, subprocess, sys, time
from pathlib import Path
import desktop_busy as db
import ocr_remote, vlm_reader

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

def reading(games=(), gpu3d=0.0, serving=()):
    return {"games": list(games), "gpu3d": gpu3d, "serving": list(serving)}

check("an idle desktop is not busy", None, db.verdict(reading(gpu3d=3.0)))
check("a desktop that does not answer is not busy", None, db.verdict(None))
check("a game running makes it busy", True, bool(db.verdict(reading(games=["Wow"]))))
check("3D at the threshold is not busy", None, db.verdict(reading(gpu3d=db.GPU_3D)))
check("3D over the threshold is busy", True, bool(db.verdict(reading(gpu3d=db.GPU_3D + 1))))

# The probe leaves the VLM's own 3D load out: it names VLM_SERVERS to the script.
import base64, types
sent = []
real_run = db.subprocess.run
db.subprocess.run = lambda cmd, **kw: (sent.append(cmd), types.SimpleNamespace(stdout=b'{"gpu3d": 0}'))[1]
db.probe("micro@100.68.145.15")
db.subprocess.run = real_run
script = base64.b64decode(sent[0][-1].rsplit(" ", 1)[1]).decode("utf-16-le")
check("the probe script is told the VLM's process names", True,
      "$Vlm = 'llama-server', 'llama-swap'" in script and "-Name $Vlm" in script)

T = Path(os.environ["TMP"])
db.STATE = T
now = [1000.0]
db.clock = lambda: now[0]
probes, stopped, logs = [], [], []
answer = [reading()]
def probe(host):
    probes.append(host)
    return answer[0]
db.probe = probe
# Each session ended, with the verdict its process reads when it finds it
# ended: busy, so it waits for idle rather than ocr_remote.RETRY.
db.stop_sessions = lambda host, pids: stopped.append(
    (list(pids), bool(json.loads((T / "desktop_busy.json").read_text())["why"])))
db.log = logs.append
DESK = "micro@100.68.145.15"

check("a host that is not the desktop is never probed", (None, 0), (db.busy(["nobody@127.0.0.1"]), len(probes)))
check("idle: not busy, one probe, nothing logged", (None, 1, 0), (db.busy([DESK]), len(probes), len(logs)))
answer[0] = reading(games=["Wow"], serving=[7, 8])
now[0] += db.PROBE_EVERY - 1
check("within a minute the last probe's verdict stands", (None, 1), (db.busy([DESK]), len(probes)))
now[0] += 2
check("a minute on, a game makes it busy", (True, 2), (bool(db.busy([DESK])), len(probes)))
check("yielding logs one line and ends the desktop's OCR sessions, the busy verdict saved first",
      (1, [([7, 8], True)]), (len(logs), stopped))
check("the verdict is shared through the state file", True, bool(json.loads((T / "desktop_busy.json").read_text())["why"]))
now[0] += db.PROBE_EVERY + 1
answer[0] = reading(games=["Wow"])
check("still busy: no second yield line, nothing more to end", (True, 1, 1), (bool(db.busy([DESK])), len(logs), len(stopped)))
now[0] += db.PROBE_EVERY + 1
with open(T / "desktop_busy.lock", "w") as held:
    fcntl.flock(held, fcntl.LOCK_EX)
    out = subprocess.run([sys.executable, "-c", f"""
import sys; sys.path.insert(0, {os.getcwd()!r})
from pathlib import Path
import desktop_busy as db
db.STATE = Path({str(T)!r}); db.clock = lambda: {now[0]!r}
db.probe = lambda host: sys.exit("probed")
print(bool(db.busy([{DESK!r}])))"""], capture_output=True, text=True)
    check("while another process probes, its last verdict stands", ("True", 0), (out.stdout.strip(), out.returncode))
answer[0] = reading(gpu3d=1.0)
check("idle again: resumes, logging one line", (None, 2), (db.busy([DESK]), len(logs)))
now[0] += db.PROBE_EVERY + 1
answer[0] = None
check("a desktop that stops answering is not busy, and is no new transition", (None, 2), (db.busy([DESK]), len(logs)))
check("mirror: one that does not answer has no free memory to tell", None, db.free_mb([DESK]))
now[0] += db.PROBE_EVERY + 1
answer[0] = {**reading(), "freeMB": 6000}
check("its free memory is the probe's, with when it was read", (now[0], 6000), db.free_mb([DESK]))
check("mirror: a host that is not the desktop has none", None, db.free_mb(["nobody@127.0.0.1"]))

# ocr_remote: a busy desktop closes the session before its next read and
# abandons one waiting on a read; it is tried again once idle, not in RETRY.
why = [None]
ocr_remote.desktop_busy.busy = lambda hosts: why[0]
os.environ["OCR_REMOTE"] = DESK
class Fake:
    host = DESK
    closed = 0
    def close(self):
        Fake.closed += 1
ocr_remote._state().update(pid=os.getpid(), session=Fake(), retry=0.0)
check("idle: the open session is kept", True, isinstance(ocr_remote.session(), Fake))
why[0] = "playing Wow"
check("busy: no session, the open one closed", (None, 1, None),
      (ocr_remote.session(), Fake.closed, ocr_remote._state()["session"]))
ocr_remote._state()["session"] = Fake()
ocr_remote.lost(ocr_remote.Unavailable("ended"))
check("a session ended for a game is tried again when idle, not after RETRY", True,
      ocr_remote._state()["retry"] <= time.monotonic())

s = ocr_remote.Session.__new__(ocr_remote.Session)
s.host, s.buf = DESK, b""
s.proc = subprocess.Popen(["sleep", "30"], stdout=subprocess.PIPE)
ocr_remote.desktop_busy.PROBE_EVERY = 0.2
start = time.monotonic()
try:
    s.answer(30)
    got = "answered"
except ocr_remote.Unavailable:
    got = "abandoned"
s.proc.kill()
check("a read waiting on a busy desktop is abandoned within a probe", ("abandoned", True),
      (got, time.monotonic() - start < 5))

# vlm_reader: a busy desktop is an unreachable VLM, asked again once idle.
import io, urllib.request
from PIL import Image
calls = []
def fake(req, timeout=None):
    calls.append(req.full_url)
    if req.full_url.endswith("/v1/models"):
        return io.BytesIO(json.dumps({"data": [{"id": vlm_reader.MODEL}]}).encode())
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": "1 Clue (5)"}}]}).encode())
urllib.request.urlopen = fake
vlm_reader.URL = "http://100.68.145.15:8090"
vlm_reader.CACHE = T / "vlm"
vlm_reader.desktop_busy.busy = lambda hosts: why[0]
vlm_reader._UP.clear()
check("busy: the VLM is not reachable, its server not asked", (False, 0), (vlm_reader.reachable(), len(calls)))
try:
    vlm_reader.ask(Image.new("L", (40, 30), 255), "read it")
    got = "answered"
except RuntimeError:
    got = "raised"
check("busy: ask raises as when the server is down, asking nothing", ("raised", 0), (got, len(calls)))
why[0] = None
check("just after a yield it stays unreachable", False, vlm_reader.reachable())
vlm_reader._YIELDED[0] -= 1
check("idle a probe later: reachable again", True, vlm_reader.reachable())
sys.exit(1 if fails else 0)
PY
)
rc=$?
echo "$out"
exit $rc
