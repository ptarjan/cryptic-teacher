#!/usr/bin/env python3
# Does tools/vlm_reader.py stay out of the way when the desktop's VLM does
# not answer, cache what it asks, crop each clue column alone, and does
# file_archive_org_puzzles.py fill a blank clue with its reading and re-read
# an edition once it answers?
#
#     python3 tests/test_vlm_reader.py
#
# The VLM is mocked: no network, no scan, nothing written outside a temp dir.
import atexit
import os
os.environ.setdefault("CT_VLM_BLIP_SECONDS", "0")  # no link-blip waits on a fake unreachable VLM

# The desktop the code reaches is a fake one: the real addresses live in an untracked local config.
os.environ.update(CT_LOCAL_CONFIG="/nonexistent", CT_DESKTOP_USER="tester", CT_VLM_PORT="8000",
                  CT_DESKTOP_ADDRESSES="192.0.2.198 192.0.2.180 100.64.0.15", CT_DESKTOP_HOME="C:\\Users\\tester\\ocrw")
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO / "tools")
sys.path.insert(0, str(REPO / "tools"))
tmp = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, tmp, ignore_errors=True)
os.environ['DESKTOP_HOSTS_STATIC'] = '1'
import io
import json
import vlm_reader as vlm
import file_archive_org_puzzles as f

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

T = tmp
vlm.CACHE = T / "vlm"
os.environ["CT_VLM_ASK_LOG"] = str(T / "vlm_asks.log")  # never the host's real log
(T / "slot-tmp").mkdir(exist_ok=True)
tempfile.tempdir = str(T / "slot-tmp")  # the host's real slot locks may be held by live askers
# A fake desktop, never the real one: two LAN leases and a tailnet address
# from the documentation ranges (RFC 5737), whatever the local config
# lists, and no ssh to ask whether it is busy.
vlm.URLS = ["http://192.0.2.198:8000", "http://192.0.2.180:8000", "http://198.51.100.15:8000"]
vlm.desktop_busy.busy = lambda hosts: None

# Nothing listening: not reachable, and asked once.
vlm.URL = ""
check("an empty URL turns it off", False, vlm.reachable())
vlm.URL = "http://127.0.0.1:9"
vlm._UP.clear()
check("a server that does not answer is not reachable", False, vlm.reachable())

# A server that lists another model is not reachable either.
import urllib.request
real = urllib.request.urlopen
calls = []
def fake(req, timeout=None):
    calls.append(req.full_url)
    if req.full_url.endswith("/v1/models"):
        return io.BytesIO(json.dumps({"data": [{"id": "glimmer-30b"}]}).encode())
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": "ACROSS\n1 Clue (5)"}}]}).encode())
urllib.request.urlopen = fake
vlm._UP.clear()
check("a server without the model is not reachable", False, vlm.reachable())
vlm._UP.clear()
vlm.MODEL = "glimmer-30b"
check("a server listing the model is reachable", True, vlm.reachable())

from PIL import Image
img = Image.new("L", (400, 300), 255)
calls.clear()
check("ask returns the reply", "ACROSS\n1 Clue (5)", vlm.ask(img, "read it"))
check("a second ask of the same image is the cache's", ("ACROSS\n1 Clue (5)", 1),
      (vlm.ask(img, "read it"), len(calls)))

# Another model loaded and ready (#local-model's chat model) is not evicted:
# the ask yields as for a game, sends nothing, and is asked again later.
sent = []
running = [[]]
def fake_running(req, timeout=None):
    sent.append(req.full_url)
    if req.full_url.endswith("/running"):
        return io.BytesIO(json.dumps({"running": running[0]}).encode())
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": "R"}}]}).encode())
urllib.request.urlopen = fake_running
img2 = Image.new("L", (400, 300), 0)
def try_ask(loaded):
    running[0] = loaded
    vlm._CHAT[0] = float("-inf")
    sent.clear()
    try:
        vlm.ask(img2, f"p{len(loaded)}{loaded and loaded[0]['model']}{loaded and loaded[0]['state']}")
        return "asked" if any(u.endswith("/chat/completions") for u in sent) else "cache"
    except RuntimeError as e:
        return "yields" if "yields" in str(e) and not any(u.endswith("/chat/completions") for u in sent) else str(e)
check("another model loaded and ready: no ask is sent, the ask yields",
      "yields", try_ask([{"model": "qwen3.8-27b", "state": "ready"}]))
check("the same model loaded, nothing loaded, or the other still starting: the ask is sent",
      ["asked"] * 3, [try_ask([{"model": vlm.MODEL, "state": "ready"}]), try_ask([]),
                      try_ask([{"model": "qwen3.8-27b", "state": "starting"}])])
running[0] = [{"model": "qwen3.8-27b", "state": "ready"}]
vlm._CHAT[0] = float("-inf")
first = vlm.chat_model()
running[0] = []
check("the loaded-model check stands for CHAT_EVERY seconds, then reads again", ("qwen3.8-27b", "qwen3.8-27b", None),
      (first, vlm.chat_model(), (vlm._CHAT.__setitem__(0, float("-inf")), vlm.chat_model())[1]))
urllib.request.urlopen = real

# A 429 (llama-swap's queue full under many concurrent reads) is the server
# busy, not down: the ask waits and asks again, marks nothing missed, and only
# gives up (as a failure) after QUEUE_FULL_TRIES.
import time
import urllib.error
n429 = [2]
def fake_429(req, timeout=None):
    if n429[0] > 0:
        n429[0] -= 1
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": "OK429"}}]}).encode())
urllib.request.urlopen = fake_429
slept = []
real_sleep, vlm.time.sleep = vlm.time.sleep, slept.append
vlm._MISSED[0] = False
vlm._UP[vlm.MODEL] = True
vlm._CHAT[:] = [time.monotonic(), None, True]
vlm._YIELDED[0] = float("-inf")
img3 = Image.new("L", (400, 300), 7)
check("a 429 is waited out and asked again: the reply, two waits, nothing missed, still up",
      ("OK429", 2, False, True), (vlm.ask(img3, "q429"), len(slept), vlm.missed(), vlm._UP[vlm.MODEL]))
n429[0] = 99
slept.clear()
img4 = Image.new("L", (400, 300), 9)
try:
    vlm.ask(img4, "q429b")
    got = "replied"
except RuntimeError:
    got = "failed"
check("a 429 that never clears fails after QUEUE_FULL_TRIES asks", ("failed", vlm.QUEUE_FULL_TRIES - 1),
      (got, len(slept)))
vlm.time.sleep = real_sleep
vlm._MISSED[0] = False
urllib.request.urlopen = real

# The LAN address went stale (DHCP): its connect times out, the tailnet one
# answers, and the VLM is reachable, at that address, probed once.
import socket
lan, tail = vlm.URLS[0], vlm.URLS[-1]
probed = []
def fake_lan_dead(req, timeout=None):
    probed.append((req.full_url, timeout))
    if not req.full_url.startswith(tail):  # every LAN address (both leases) gone
        raise socket.timeout("timed out")
    if req.full_url.endswith("/running"):
        return io.BytesIO(b'{"running": []}')
    return io.BytesIO(json.dumps({"data": [{"id": vlm.MODEL}]}).encode())
urllib.request.urlopen = fake_lan_dead
vlm.URL, vlm._RESOLVED[0] = lan, False
vlm._UP.clear()
vlm._CHAT[0] = float("-inf")
vlm._YIELDED[0] = float("-inf")
check("first URL times out: falls back to the tailnet one", True, vlm.reachable())
check("the address that worked is kept", tail, vlm.URL)
n = len(probed)
vlm.reachable()
check("and cached: no LAN probe again", [], [p for p in probed[n:] if p[0].startswith(lan)])
check("the LAN probe used the short timeout", True, probed[0][1] <= 3)
# The address kept stops answering (the lease moved under a long-running
# queue): up() asks again and every URL is tried, not the dead one alone.
def fake_tail_dead(req, timeout=None):
    if req.full_url.startswith(tail):
        raise ConnectionRefusedError("refused")
    if req.full_url.endswith("/running"):
        return io.BytesIO(b'{"running": []}')
    return io.BytesIO(json.dumps({"data": [{"id": vlm.MODEL}]}).encode())
urllib.request.urlopen = fake_tail_dead
vlm._UP.clear()
check("the kept address refusing: another URL answers, is reachable and kept", (True, lan, True),
      (vlm.reachable(), vlm.URL, vlm._RESOLVED[0]))
# Neither answers: not reachable, and asked again next time.
urllib.request.urlopen = lambda req, timeout=None: (_ for _ in ()).throw(socket.timeout("t"))
vlm.URL, vlm._RESOLVED[0] = lan, False
vlm._UP.clear()
check("no address answers: not reachable", (False, False), (vlm.reachable(), vlm._RESOLVED[0]))
# An override is used alone, with no fallback.
probed.clear()
urllib.request.urlopen = fake_lan_dead
vlm.URL, vlm._RESOLVED[0] = "http://127.0.0.1:9", False
vlm._UP.clear()
vlm.reachable()
check("an override URL never falls back", True, all(p[0].startswith("http://127.0.0.1:9") for p in probed))
# A read already running resolved a LAN address that then goes stale (the
# lease flapped): the ask that times out re-resolves once over the other
# candidates and goes on there, instead of failing (or hanging) the read.
chat_urls = []
def fake_flap(req, timeout=None):
    if req.full_url.endswith("/running"):
        return io.BytesIO(b'{"running": []}')
    if req.full_url.endswith("/v1/models"):
        if req.full_url.startswith(lan):
            raise socket.timeout("timed out")
        return io.BytesIO(json.dumps({"data": [{"id": vlm.MODEL}]}).encode())
    chat_urls.append(req.full_url)
    if req.full_url.startswith(lan):
        raise socket.timeout("timed out")
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": "moved reply"}}]}).encode())
urllib.request.urlopen = fake_flap
vlm.URL, vlm._RESOLVED[0] = lan, True
vlm._UP.clear(); vlm._MISSED[0] = False
got = vlm.ask_png(b"flap-png-1", "flap prompt 1")
check("ask timing out on a stale address: re-resolved, answered elsewhere", ("moved reply", vlm.URLS[1], False),
      (got, vlm.URL, vlm._MISSED[0]))
check("it asked the stale one once, then the new one once", [lan, vlm.URLS[1]], [u.rsplit("/v1", 1)[0] for u in chat_urls])
# Nothing else answers: it still ends as before (down mid-read), after one try.
urllib.request.urlopen = lambda req, timeout=None: (_ for _ in ()).throw(socket.timeout("t"))
vlm.URL, vlm._RESOLVED[0] = lan, True
try:
    vlm.ask_png(b"flap-png-2", "flap prompt 2")
    err = None
except RuntimeError as e:
    err = str(e)
check("no other address answers: the read ends as down mid-read", (True, "timeout"),
      (bool(err) and "failed (timeout)" in err, vlm.cause()))
# An override is never moved.
chat_urls.clear()
urllib.request.urlopen = fake_flap
vlm.URL = "http://127.0.0.1:9"
try:
    vlm.ask_png(b"flap-png-3", "flap prompt 3")
except RuntimeError:
    pass
check("an override URL is not re-resolved", "http://127.0.0.1:9", vlm.URL)
vlm.URL = lan
# Tailnet first: of the others, the tailnet (100.64.0.0/10) URL is asked before a LAN one.
kept_urls = vlm.URLS
vlm.URLS = ["http://192.0.2.198:8000", "http://192.0.2.180:8000", "http://100.64.0.15:8000"]
check("others after the URL: tailnet before LAN", ["http://100.64.0.15:8000", "http://192.0.2.180:8000"],
      sorted([u for u in vlm._candidates() if u != vlm.URLS[0]], key=lambda u: not vlm._on_tailnet(u)))
vlm.URLS = kept_urls
urllib.request.urlopen = real
vlm._RESOLVED[0] = True

# The desktop sends the bytes png() makes here, so the Mac keys its cache
# without decoding or encoding anything.
import random
random.seed(3)
noisy = Image.new("RGB", (300, 200))
noisy.putdata([tuple(random.choice((0, 90, 255)) for _ in range(3)) for _ in range(300 * 200)])
noisy = noisy.resize((600, 400))
check("png_as() makes png()'s bytes for this host's encoder, in every mode it takes",
      [True] * 4, [vlm.png_as(noisy.convert(m), vlm.encoder()) == vlm.png(noisy.convert(m))
                   for m in vlm.FILTERED_MODES])
check("png_as() makes nothing for another encoder or a palette image", (None, None),
      (vlm.png_as(noisy, "0.0.0/1.3.1"), vlm.png_as(noisy.convert("P"), vlm.encoder())))
import ocr_remote
asked = []
kept = vlm.ask, vlm.ask_png
vlm.ask_png = lambda data, prompt, n: asked.append(data) or "png reply"
vlm.ask = lambda im, prompt, n: asked.append(im.size) or "image reply"
data = vlm.png(img)
class Pipe:
    """A desktop asking twice, the first in this host's PNG, then answering."""
    def __init__(self):
        self.answers = [{"ask": "p", "max_tokens": 9, "png": True, "bytes": len(data)},
                        {"ask": "p", "max_tokens": 9, "bytes": len(data)}, {"results": []}]
        self.payloads, self.replies = [data, data, b""], []
        self.proc = self
        self.stdin = self
    def send(self, head, data):
        pass
    def answer(self, timeout):
        return self.answers.pop(0)
    def payload(self, n, timeout):
        return self.payloads.pop(0)
    def write(self, line):
        self.replies.append(json.loads(line)["text"])
    def flush(self):
        pass
pipe = Pipe()
ocr_remote.Session.edition(pipe, {}, b"")
vlm.ask, vlm.ask_png = kept
check("an ask in this host's PNG is answered from its bytes, any other from the decoded image",
      ([data, (400, 300)], ["png reply", "image reply"]), (asked, pipe.replies))

# Each column cropped to its own lines, not the window's shared right edge.
wins = [(10, 200, 390, 0), (200, 390, 390, 0)]
readings = [[[(20, 80, 15, 180, "1 Left clue (5)")], [(30, 100, 210, 380, "2 Right (4)")]]]
check("crop boxes span each column's lines, padded",
      [(5, 10, 190, 90), (200, 20, 390, 110)], vlm.boxes(img, wins, readings))
# A two-line column (the 1945 Times' strip over the grid, 327x70) is a clue column; a stray line's 33x36 is not.
check("a two-line strip column is boxed, a stray line's speck is not",
      [(5, 10, 345, 80), None],
      vlm.boxes(img, [(10, 200, 390, 0), (200, 390, 390, 0)],
                [[[(20, 70, 15, 335, "21 Foreign currency (5)")], [(30, 56, 210, 223, "x")]]]))

# A column another crop window re-cuts a few pixels apart is not read twice (FT 1980-10-25).
read_kept, crop_kept = vlm.read, vlm.crop
read_log = []
vlm.crop = lambda im, box: tuple(box)
vlm.read = lambda c: read_log.append(c) or f"text{len(read_log)}"
got = vlm.read_columns("p#1", None, [(100, 50, 846, 2052), (900, 50, 1644, 1216)])
got2 = vlm.read_columns("p#1", None, [(102, 52, 856, 2068), (900, 50, 1644, 1216), (900, 50, 1830, 1350)])
check("a near-identical column takes the reading already made, a different one is read",
      (["text1", "text2"], ["text1", "text2", "text3"], 3), (got, got2, len(read_log)))
check("another page's columns are never reused", ["text4"],
      vlm.read_columns("p#2", None, [(100, 50, 846, 2052)]))
vlm.read, vlm.crop = read_kept, crop_kept

# The pick fills a blank with the reply's words, its count cut off; a reply
# of no words, or none, leaves it blank.
texts = {"ch": "ACROSS\n1 Stop thief (4)\nDOWN\n2 Kettle (3)", "en5": "ACROSS\n1 Stop chief (4)\nDOWN\n2 Kettle (3)"}
laid = {"1-across": ("", "4", None)}
shown = []
for reply, want in (("Stop thief (4)", "Stop thief"), ("(4)", ""), (None, "")):
    def fake_pick(img, wins, readings, lid, cands, r=reply):
        shown.append(cands)
        return r
    vlm.pick = fake_pick
    got, blank = f.vlm_pick(img, wins, readings, texts, laid, {"1-across": "readings differ"})
    check(f"pick of {reply!r}", (want, not want), (got["1-across"][0], "1-across" in blank))
check("the pick is shown every reading's text for the light", ["Stop thief (4)", "Stop chief (4)"], shown[0])

# run(): an edition read without the VLM is read again once it answers;
# one read with it is not read again while it is down.
ed = T / "cache" / "NewsUK1990UKEnglish" / "1990-01-01_1"
ed.mkdir(parents=True)
(ed / "pages.json").write_text("{}")
reads = []
saved = (f.scan, f.read_puzzle, vlm.reachable, vlm.version)
f.scan = lambda d: {"date": "1990-01-01", "item": "NewsUK1990UKEnglish", "solutions": [],
                    "puzzles": [{"number": 18180, "leaf": 1, "box": None}]}
f.read_puzzle = lambda d, found, hit, sol: (reads.append(vlm.reachable()), ({"number": 18180}, None))[1]
vlm.version = lambda: "v1"
ledger = T / "ledger.jsonl"
def go(up):
    vlm.reachable = lambda: up
    f.run(cache=T / "cache", ledger=ledger, source=T / "src", out=open(os.devnull, "w"))
go(False); go(False)
check("without the VLM an edition is read once", [False], reads)
go(True); go(True)
check("the VLM answering reads it again, once", [False, True], reads)
go(False)
check("the VLM down again leaves its reading standing", [False, True], reads)
vlm.version = lambda: "v2"
go(True)
check("a new VLM model reads the edition again, at the whole-corpus rank", [False, True, True], reads)
# The VLM gone during an edition: that edition is filed as read without it.
state = {"up": True}
def dies(d, found, hit, sol):
    reads.append("dies")
    state["up"] = False
    return {"number": 18180}, None
f.read_puzzle = dies
vlm.reachable = lambda: state["up"]
import scan_queue
f.run(cache=T / "cache", ledger=ledger, source=T / "src", out=open(os.devnull, "w"),
      reread=scan_queue.when("now"))
row = json.loads(ledger.read_text().splitlines()[-1])
check("an edition the VLM died during is filed as read without it", ("dies", None),
      (reads[-1], row.get("vlm")))
f.read_puzzle = lambda d, found, hit, sol: (reads.append(vlm.reachable()), ({"number": 18180}, None))[1]
go(True)
check("so it is read again once the VLM answers", True, reads[-1])
f.scan, f.read_puzzle, vlm.reachable, vlm.version = saved

# A read the queue started (DEFER_ENV) never reads on without the VLM (Paul
# 10-13): wanted() raises Down when it is down, an ask lost mid-read makes
# the next puzzle write or ledger row raise it, and nothing is written.
saved = vlm.reachable, vlm.URL, vlm._MISSED[0]
vlm.URL = "http://127.0.0.1:9"
vlm.reachable = lambda: False
vlm._MISSED[0] = False
check("outside a queue's read wanted() is reachable() and raises nothing", False, vlm.wanted())
vlm._MISSED[0] = False
os.environ[vlm.DEFER_ENV] = "1"
try:
    vlm.wanted()
    got = "read on"
except vlm.Down:
    got = "deferred"
check("in a queue's read the VLM down raises Down at the first ask", ("deferred", True), (got, vlm.missed()))
check("Down is a RuntimeError, so a reader's own except still lets the write guard catch it",
      True, issubclass(vlm.Down, RuntimeError))
vlm._MISSED[0] = False
vlm.reachable = lambda: True
check("the VLM up: wanted() is True and nothing is guarded", (True, None), (vlm.wanted(), vlm.guard("x")))
led = T / "guarded.jsonl"
vlm._MISSED[0] = True  # an ask failed mid-edition
try:
    scan_queue.append(led, [{"edition": "e"}])
    got = "written"
except vlm.Down:
    got = "deferred"
check("a read that lost the VLM mid-edition writes no ledger row", ("deferred", False), (got, led.exists()))
try:
    scan_queue.file_puzzle(lambda *a, **k: calls.append("wrote"), "t", T / "p.json", {"id": "p", "entries": []}, {})
    got = "written"
except vlm.Down:
    got = "deferred"
check("nor any puzzle", "deferred", got)
check("scan_queue.parallel lets Down through, not logged as one bad source", True, scan_queue.vlm_down(vlm.Down("x")))
del os.environ[vlm.DEFER_ENV]
scan_queue.append(led, [{"edition": "e"}])
check("mirror: outside a queue's read the same row is written", True, led.exists())

# 10-21: a host whose config lost its VLM address ran every read OCR-only, unlogged. An empty URL
# nobody asked for is "VLM down" (a queue's read defers, nothing recorded); an explicitly empty
# VLM_READER_URL stays the OCR-only opt-out.
saved_env = os.environ.pop("VLM_READER_URL", None)
vlm.URL, vlm._MISSED[0], vlm._CAUSE[0] = "", False, ""
vlm.reachable = lambda: False
check("no URL and no VLM_READER_URL: unconfigured, its cause says so", (True, vlm.UNCONFIGURED), (vlm.unconfigured(), vlm.cause()))
check("unconfigured, outside a queue's read: wanted() is False and the miss is noted", (False, True), (vlm.wanted(), vlm.missed()))
vlm._MISSED[0] = False
os.environ[vlm.DEFER_ENV] = "1"
try:
    vlm.wanted()
    got = "read on"
except vlm.Down as e:
    got = ("deferred", "not configured" in str(e))
check("unconfigured, in a queue's read: Down, like a VLM down", ("deferred", True), got)
vlm._MISSED[0] = True
vlm._CAUSE[0] = vlm.UNCONFIGURED
try:
    vlm.guard("x")
    got = "written"
except vlm.Down as e:
    got = ("deferred", "not configured" in str(e))
check("unconfigured: a write after the miss is guarded", ("deferred", True), got)
import edition_queue as eq
saved_gate, eq.vlm_gate_reader = eq.vlm_gate_reader, None
check("the queue counts an unconfigured VLM as down", False, eq.vlm_up())
notes = []
eq._plan([], T / "cache", None, notes)
check("each plan says so loudly", True, any("VLM NOT CONFIGURED" in n for n in notes))
os.environ["VLM_READER_URL"] = ""
vlm._MISSED[0] = False
vlm._CAUSE[0] = ""
check("an explicitly empty VLM_READER_URL is not unconfigured", (False, ""), (vlm.unconfigured(), vlm.cause()))
check("... wanted() raises nothing and notes no miss, as before", (False, False), (vlm.wanted(), vlm.missed()))
check("... the queue goes on without the VLM", True, eq.vlm_up())
notes = []
eq._plan([], T / "cache", None, notes)
check("... and its plans say nothing", False, any("VLM NOT CONFIGURED" in n for n in notes))
eq.vlm_gate_reader = saved_gate
del os.environ["VLM_READER_URL"]
if saved_env is not None:
    os.environ["VLM_READER_URL"] = saved_env
del os.environ[vlm.DEFER_ENV]
vlm._MISSED[0] = False
vlm._CAUSE[0] = ""

# A row written with no VLM address carries the mark, and is due again once the VLM answers.
import edition_commit
os.environ.pop("VLM_READER_URL", None)
vlm.URL = ""
mark = edition_commit.row("i/e", "h", {"puzzles": []}, "h", "k", [], [], None)
check("a row read with the VLM unconfigured is marked", True, mark.get("vlmUnset"))
os.environ["VLM_READER_URL"] = ""
check("a row read under the explicit opt-out is not", None, edition_commit.row("i/e", "h", {"puzzles": []}, "h", "k", [], [], None).get("vlmUnset"))
del os.environ["VLM_READER_URL"]
base_row = {"inputs": "h", "scan": {"puzzles": []}, "solutionsSeen": [], "verdicts": []}
why = lambda row, up="v1": f.due_reason(row, "h", [], up)
check("a marked row is due 'read while the VLM was unconfigured' once the VLM answers",
      f.UNCONFIGURED_READ, why({**base_row, "vlmUnset": True, "readAt": "2026-11-01T00:00:00+00:00"}))
check("... not while it is down", None, why({**base_row, "vlmUnset": True}, None))
check("a row with no VLM version read within the 10-21 outage is due it", f.UNCONFIGURED_READ,
      why({**base_row, "readAt": "2026-10-21T07:12:19+00:00"}))
check("... one read with the VLM then is not", None, why({**base_row, "vlm": "v1", "readAt": "2026-10-21T07:12:19+00:00"}))
check("... nor one read before it (not planned as a blanket reread, but 'read without the VLM')",
      "read without the VLM", why({**base_row, "readAt": "2026-10-21T06:00:00+00:00"}))
check("the reason is ranked with never-read work", f.RANKS["never read"], f.RANKS[f.UNCONFIGURED_READ])
check("the queue plans it without CT_BLANKET_REREADS", True, eq.evidence_reason(f.UNCONFIGURED_READ))
check("and it is no refusal reread, so hold_refusal_rereads keeps it", False, eq.refusal_reread(f.UNCONFIGURED_READ))
kept = [(1, 0, 0, {"reason": f.UNCONFIGURED_READ, "paper": "ft"}), (0, 0, 1, {"reason": "never read", "paper": "ft"})]
check("... even while never-read work waits", 2, len(eq.hold_refusal_rereads([], kept)[1]))
# up(): asked afresh at most every UP_EVERY seconds.
asked = []
vlm.reachable = lambda: (asked.append(1), len(asked) > 1)[1]
vlm._UP_AT[:] = [float("-inf"), False]
first = vlm.up()
check("up() is asked once within UP_EVERY", (False, False, 1), (first, vlm.up(), len(asked)))
vlm._UP_AT[0] -= vlm.UP_EVERY
check("and again after it", (True, 2), (vlm.up(), len(asked)))
# A server that was up and misses one ask is asked again before up() says down.
def run(answers, was):
    global seq
    seq = iter(answers)
    slept.clear()
    vlm._UP_AT[:] = [float("-inf"), was]
    return vlm.up(), len(slept)
seq = iter(())
def flaky():
    ok = next(seq)
    vlm._UNREACHED[0] = not ok
    return ok
vlm.reachable = flaky
slept = []
vlm.time.sleep = slept.append
check("one silent ask of a server that was up is not down", (True, 2), run([False, False, True], True))
check("three silent asks are", (False, 2), run([False] * 3, True))
check("a server that was already down is asked once", (False, 0), run([False], False))
vlm.reachable, vlm.URL, vlm._MISSED[0] = saved

# Host-wide cap: no more than slots() asks in flight at once across threads,
# waiting for a slot is not "down" (nothing missed), and the cause is logged.
import threading
import tempfile as _tempfile
_tempfile.tempdir = str(T)  # own lock files: a live queue on this host may hold the real ones
vlm._SLOTS[0] = 2
vlm.PIPELINE = 0
vlm._MISSED[0] = False
live, peak, lk, DELAY = [0], [0], threading.Lock(), [0.05]
def fake_slow(req, timeout=None):
    with lk:
        live[0] += 1
        peak[0] = max(peak[0], live[0])
    real_sleep(DELAY[0])
    with lk:
        live[0] -= 1
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": "OKc"}}]}).encode())
urllib.request.urlopen = fake_slow
vlm._UP[vlm.MODEL] = True
vlm._CHAT[:] = [time.monotonic() + 1e6, None, True]
vlm._YIELDED[0] = float("-inf")
ths = [threading.Thread(target=vlm.ask, args=(Image.new("L", (400, 300), 20 + i), "qcap")) for i in range(8)]
[t.start() for t in ths]
[t.join() for t in ths]
check("8 concurrent asks on 2 slots: never more than 2 in flight, nothing missed", (True, False),
      (1 <= peak[0] <= 2, vlm.missed()))
# Pipelining: slots()+PIPELINE in flight (the extra one queues on the server), and
# the request timeout covers the wait behind it.
vlm.PIPELINE = 0
vlm._SLOTS[0] = 1
seen_timeouts = []
def fake_slow_t(req, timeout=None):
    seen_timeouts.append(timeout)
    return fake_slow(req, timeout)
urllib.request.urlopen = fake_slow_t
peak[0] = 0
DELAY[0] = 0.4
vlm.PIPELINE = 1
ths = [threading.Thread(target=vlm.ask, args=(Image.new("L", (400, 300), 120 + i), "qpipe")) for i in range(6)]
[t.start() for t in ths]
[t.join() for t in ths]
check("pipeline 1 on 1 slot: two in flight, nothing missed", (2, False), (peak[0], vlm.missed()))
check("a queued ask's timeout is one request's worth longer", True,
      all(t >= 2 * vlm.REQUEST_TIMEOUT for t in seen_timeouts))
vlm.PIPELINE = 0
DELAY[0] = 0.05
vlm._SLOTS[0] = 2
def fake_500(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 500, "x", {}, None)
urllib.request.urlopen = fake_500
try:
    vlm.ask(Image.new("L", (400, 300), 99), "qcause")
except RuntimeError:
    pass
check("a failed ask logs its cause", "HTTP 500", vlm.cause())
vlm._SLOTS[0] = None
urllib.request.urlopen = real
vlm._MISSED[0] = False

# Each edition's log line says what it asked: real calls by kind, cache hits, "vlm 0" for none.
urllib.request.urlopen = fake
vlm.spent()
check("an edition that asked nothing says vlm 0", "vlm 0", vlm.vlm_note())
box = Image.new("L", (400, 300), 7)
vlm.read(box)
vlm.read(box)
vlm.pick_in(box, "3-across", ["a", "b"])
check("asks count by kind, a repeat as cached", "vlm 1 reads, 1 picks, 1 cached", vlm.vlm_note())
check("the count starts over after a line", "vlm 0", vlm.vlm_note())
urllib.request.urlopen = real

# Processes with an ask under way are counted (waiting_now); a dead pid's mark is ignored and removed.
check("no ask under way: nobody waits", 0, vlm.waiting_now())
with vlm.asking():
    (vlm._waiting_dir() / "999999999").touch()  # a pid that does not exist
    check("an ask under way counts, a stale pid does not", 1, vlm.waiting_now())
check("the stale mark is removed", False, (vlm._waiting_dir() / "999999999").exists())
check("the mark ends with the ask", 0, vlm.waiting_now())

# The spool: under CT_VLM_SPOOL an ask not cached is queued (png + json) and raises Spooled, every column of a
# read_all at once; drain_one asks the server for the oldest and caches it; the read then hits the cache.
vlm._SLOTS[0] = 1
vlm.PIPELINE = 0
vlm._MISSED[0] = False
vlm._YIELDED[0] = float("-inf")
asked = []
def fake_ok(req, timeout=None):
    asked.append(1)
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": "spoolt"}}]}).encode())
urllib.request.urlopen = fake_ok
os.environ[vlm.SPOOL_WAIT_ENV] = "0"  # no drainer runs here: the reads defer at once (the wait's own cases are below)
os.environ[vlm.SPOOL_ENV] = "1"
cols = [Image.new("L", (400, 300), 31 + i) for i in range(3)]
try:
    vlm.read_all(cols)
    raised = False
except vlm.Spooled:
    raised = True
check("a spooling read asks nothing and spools every uncached column", (True, 0, 3, True),
      (raised, len(asked), len(vlm.spooled()), vlm.missed()))
check("the spooled asks are the asking pid's and pending", (3, True),
      (len(vlm.spooled_by(os.getpid())), all(vlm.pending(k) for k in vlm.spooled())))
try:
    vlm.read_all(cols)
except vlm.Spooled:
    pass
check("spooling the same asks again does not queue them twice", 3, len(vlm.spooled()))
os.environ.pop(vlm.SPOOL_ENV)
first = vlm.spooled()[0]
check("the drainer asks the oldest and caches it", (first, 1, 2), (vlm.drain_one(), len(asked), len(vlm.spooled())))
while vlm.drain_one():
    pass
check("the drained asks are answered and gone", (0, 3), (len(vlm.spooled()), len(asked)))
os.environ[vlm.SPOOL_ENV] = "1"
check("the read that spooled them now hits the cache", (["spoolt"] * 3, 3), (vlm.read_all(cols), len(asked)))
os.environ.pop(vlm.SPOOL_ENV)
# A page with 3 blank clues spools all 3 picks in one read (not one per rerun), then defers once.
import ocr_clues
os.environ[vlm.SPOOL_ENV] = "1"
vlm._MISSED[0] = False
page = Image.new("L", (400, 300), 77)
pk_texts = {"a": "ACROSS\n1 Stop thief (4)\n4 Odd one (3)\nDOWN\n2 Kettle (3)", "b": "ACROSS\n1 Stop chief (4)\n4 Odd won (3)\nDOWN\n2 Kettlo (3)"}
pk_blank = {"1-across": "readings differ", "4-across": "readings differ", "2-down": "readings differ"}
pk_laid = {k: ("", "3", None) for k in pk_blank}
before_n = len(vlm.spooled())
try:
    ocr_clues.vlm_pick(pk_texts, pk_laid, pk_blank, f.parse, lambda lid, cands: vlm.pick_in(page, lid, cands))
    pk_raised = False
except vlm.Spooled:
    pk_raised = True
check("three blank clues spool three picks in one read, which then defers", (True, 3, True),
      (pk_raised, len(vlm.spooled()) - before_n, vlm.missed()))
while vlm.drain_one():
    pass
os.environ.pop(vlm.SPOOL_ENV)
vlm._MISSED[0] = False
urllib.request.urlopen = fake_500
vlm.put_spool("k" * 40, b"x", "p", 10)
check("a failed drain leaves the ask queued", (None, True), (vlm.drain_one(), vlm.pending("k" * 40)))
urllib.request.urlopen = real
vlm._MISSED[0] = False
vlm._SLOTS[0] = None

# The drainer claims after it holds a slot: with every slot taken the ask stays .json (never a waiting .json.work);
# once a slot frees it is asked and answered.
vlm.time.sleep = real_sleep  # line ~409's stub was never undone: waits below need real time
import fcntl
import threading
urllib.request.urlopen = fake_ok
vlm.drain_one()  # the failed drain's leftover
check("the spool is empty before the slot test", [], vlm.spooled())
vlm.put_spool("w" * 40, b"wx", "p", 10)
_held = open(Path(tempfile.gettempdir()) / "vlm_reader.slot.0.lock", "w")
fcntl.flock(_held, fcntl.LOCK_EX)
_got = []
_t = threading.Thread(target=lambda: _got.append(vlm.drain_one()), daemon=True)
_t.start()
_mark = vlm._draining_dir() / str(os.getpid())
for _ in range(100):  # real sleeps: the earlier sleep stubs are not restored
    if _mark.exists():
        break
    real_sleep(0.05)
real_sleep(0.5)  # and let it settle: still waiting, nothing claimed
check("a drainer waiting for a slot has claimed nothing", (True, False, True),
      (_t.is_alive(), (vlm.spool_dir() / ("w" * 40 + vlm.CLAIMED)).exists(), (vlm.spool_dir() / ("w" * 40 + ".json")).exists()))
check("... and is marked as waiting, to other processes' eyes only", True,
      (vlm._draining_dir() / str(os.getpid())).exists())
fcntl.flock(_held, fcntl.LOCK_UN)
_held.close()
_t.join(10)
check("the freed slot lets it ask and answer", (["w" * 40], False), (_got, vlm.pending("w" * 40)))
check("the waiting mark ends with the wait", False, (vlm._draining_dir() / str(os.getpid())).exists())

# Direct askers hold off while another live process's drainer waits (a stale pid's mark is removed).
vlm._draining_dir().mkdir(parents=True, exist_ok=True)
(vlm._draining_dir() / "999999999").touch()
check("a dead drainer's mark does not hold anyone off", (False, False), (vlm.drainer_waiting(), (vlm._draining_dir() / "999999999").exists()))
(vlm._draining_dir() / str(os.getppid())).touch()
check("a live other process's waiting drainer is seen", True, vlm.drainer_waiting())
_slept = []
_real_sleep = vlm.time.sleep
def _fake_sleep(sec):
    _slept.append(sec)
    (vlm._draining_dir() / str(os.getppid())).unlink(missing_ok=True)  # the drainer got its slot
vlm.time.sleep = _fake_sleep
with vlm.slot():
    pass
vlm.time.sleep = _real_sleep
check("a direct ask backs off once, then takes the slot", (1, True), (len(_slept), 1.0 <= _slept[0] <= 3.0))
with vlm.slot(priority=True):
    check("the drainer does not wait on its own mark", False, vlm.drainer_waiting())

# A stale claim of a dead drainer is queued again at the next drainer's start.
vlm.put_spool("s" * 40, b"sx", "p", 10)
(vlm.spool_dir() / ("s" * 40 + ".json")).rename(vlm.spool_dir() / ("s" * 40 + vlm.CLAIMED))
vlm.requeue_claimed()
check("a dead drainer's claim is queued again", (True, False), ((vlm.spool_dir() / ("s" * 40 + ".json")).exists(), (vlm.spool_dir() / ("s" * 40 + vlm.CLAIMED)).exists()))
(vlm.spool_dir() / ("s" * 40 + ".json")).unlink()
# A claim names its claimer: one a live other process asks is left; a dead one's, or this pid's
# that this image does not hold (a re-exec ended its threads mid-ask), is queued again.
def _claim(k, by):
    vlm.put_spool(k * 40, b"x" + k.encode(), "p", 10)
    j = vlm.spool_dir() / (k * 40 + ".json")
    if by is not None:
        j.write_text(json.dumps({"prompt": "p", "max_tokens": 10, "claimed_by": by}))
    j.rename(vlm.spool_dir() / (k * 40 + vlm.CLAIMED))
    return vlm.spool_dir() / (k * 40 + vlm.CLAIMED)
_live, _dead, _own, _old = _claim("g", os.getppid()), _claim("h", 999999999), _claim("i", os.getpid()), _claim("j", None)
_mine = _claim("k", os.getpid())
vlm._MINE.add(_mine)
check("a sweep takes back the dead's and a past image's claims only", (2, True, False, False, True, True),
      (vlm.requeue_claimed(start=False), _live.exists(), _dead.exists(), _own.exists(), _old.exists(), _mine.exists()))
check("... a start takes a pid-less claim too, never a live other's", (1, True, False), (vlm.requeue_claimed(), _live.exists(), _old.exists()))
check("release_claims queues this image's own claims again", (1, False, True),
      (vlm.release_claims(), _mine.exists(), (vlm.spool_dir() / ("k" * 40 + ".json")).exists()))
_live.unlink()
for _k in "ghijk":
    (vlm.spool_dir() / (_k * 40 + ".json")).unlink(missing_ok=True)
    (vlm.spool_dir() / (_k * 40 + ".png")).unlink(missing_ok=True)

# Head of line: an entry already answered or without its png is dropped, a failing one goes to the back.
vlm.CACHE.mkdir(parents=True, exist_ok=True)
for _k in vlm.spooled():
    vlm.drain_one()
vlm.put_spool("a" * 40, b"ax", "p", 10)
os.utime(vlm.spool_dir() / ("a" * 40 + ".json"), (1, 1))
(vlm.spool_dir() / ("a" * 40 + ".png")).unlink()  # orphan json, oldest
vlm.put_spool("b" * 40, b"bx", "p", 10)
os.utime(vlm.spool_dir() / ("b" * 40 + ".json"), (2, 2))
(vlm.CACHE / ("b" * 40 + ".txt")).write_text("done")  # answered already
vlm.put_spool("c" * 40, b"cx", "p", 10)
check("orphan and answered entries do not block the next", "c" * 40, vlm.drain_one())
check("... and both are dropped", [], vlm.spooled())
# A torn entry (0-byte .json and .png, a crash before their writes synced) is dropped, not requeued
# ahead of the rest: it never answers, and drain_one returning None for it stalled the drainer.
vlm.put_spool("t" * 40, b"tx", "p", 10)
(vlm.spool_dir() / ("t" * 40 + ".json")).write_text("")
(vlm.spool_dir() / ("t" * 40 + ".png")).write_bytes(b"")
os.utime(vlm.spool_dir() / ("t" * 40 + ".json"), (1, 1))
vlm.put_spool("u" * 40, b"ux", "p", 10)
check("a torn entry does not block the next", "u" * 40, vlm.drain_one())
check("... and is dropped with its png", ([], False), (vlm.spooled(), (vlm.spool_dir() / ("t" * 40 + ".png")).exists()))
vlm.put_spool("b" * 40, b"bx", "p", 10)
check("a cached key is not spooled", [], vlm.spooled())
vlm.put_spool("d" * 40, b"dx", "p", 10)
os.utime(vlm.spool_dir() / ("d" * 40 + ".json"), (1, 1))
vlm.put_spool("e" * 40, b"ex", "p", 10)
(vlm.spool_dir() / ("e" * 40 + ".json")).rename(vlm.spool_dir() / ("e" * 40 + vlm.CLAIMED))
vlm.put_spool("e" * 40, b"ex", "p", 10)
check("a claimed key is not spooled again", False, (vlm.spool_dir() / ("e" * 40 + ".json")).exists())
(vlm.spool_dir() / ("e" * 40 + vlm.CLAIMED)).unlink()
urllib.request.urlopen = fake_500
vlm.drain_one()
check("a failed ask goes to the back", True, (vlm.spool_dir() / ("d" * 40 + ".json")).stat().st_mtime > 100)
urllib.request.urlopen = fake_ok

# Draining finishes the oldest read's asks before the next read's, though they were spooled interleaved.
for _k in vlm.spooled():
    vlm.drain_one()
for _i, (_k, _pid) in enumerate([("1" * 40, 11), ("2" * 40, 22), ("3" * 40, 11), ("4" * 40, 22)]):
    vlm.put_spool(_k, b"g%d" % _i, "p", 10)
    _j = vlm.spool_dir() / (_k + ".json")
    _j.write_text(json.dumps({"prompt": "p", "max_tokens": 10, "pid": _pid, "at": 0}))
    os.utime(_j, (10 + _i, 10 + _i))
check("the oldest read's asks drain together", ["1" * 40, "3" * 40, "2" * 40, "4" * 40], [vlm.drain_one() for _ in range(4)])

# A read whose ask another read spooled first waits on it: spooled_by finds it (the queue sees "spooled", not "VLM down").
vlm.put_spool("m" * 40, b"mx", "p", 10)
_j = vlm.spool_dir() / ("m" * 40 + ".json")
_j.write_text(json.dumps({"prompt": "p", "max_tokens": 10, "pid": 424242, "at": 0}))
vlm.put_spool("m" * 40, b"mx", "p", 10)
check("a second read of a spooled ask waits on it", (["m" * 40], ["m" * 40]), (vlm.spooled_by(os.getpid()), vlm.spooled_by(424242)))
vlm.drain_one()
check("... and the wait ends with the answer", (0, 0), (len(vlm.spooled()), len(list(vlm.spool_dir().glob("m" * 40 + ".wait.*")))))

# A full spool (spooled() at vlm_spool_max()): a new ask is not spooled, the read defers with cause "spool full"
# and leaves its mark; an ask already pending still counts as spooled.
os.environ["CT_VLM_SPOOL_MAX_FILE"] = "/nonexistent/vlm_spool_max"
os.environ["CT_VLM_SPOOL_MAX"] = "1"
vlm._MISSED[0] = False
vlm.put_spool("p" * 40, b"px", "p", 10)
_full_data = b"full-ask-png"
_before = (len(vlm.spooled()), len(asked))
try:
    vlm.ask_png(_full_data, "p", 10, spool=True)
    _full_raised = False
except vlm.Spooled as e:
    _full_raised = "spool full" in str(e)
check("a full spool: the new ask is neither spooled nor asked, and the cause says so",
      (True, _before, "spool full", True, True),
      (_full_raised, (len(vlm.spooled()), len(asked)), vlm.cause(), vlm.missed(), vlm.full_mark(os.getpid()).exists()))
check("... and its png is not kept", False, (vlm.spool_dir() / (vlm.ask_key(_full_data, "p") + ".png")).exists())
vlm.full_mark(os.getpid()).unlink()
vlm._MISSED[0] = False
os.environ["CT_VLM_SPOOL_MAX"] = "5"
try:
    vlm.ask_png(_full_data, "p", 10, spool=True)
except vlm.Spooled:
    pass
check("below the cap the ask is spooled again", True, vlm.pending(vlm.ask_key(_full_data, "p")))
for _k in vlm.spooled():
    vlm.drain_one()
vlm.full_mark(os.getpid()).unlink(missing_ok=True)
os.environ.pop("CT_VLM_SPOOL_MAX")
os.environ.pop("CT_VLM_SPOOL_MAX_FILE")
vlm._MISSED[0] = False
vlm._CAUSE[0] = ""

# A shallow spool (others' asks below feed_target): a read that spools asks waits here for the drainer's
# answers and reads on, no deferral, its miss state untouched (10-24: FT reads deferred for 1-3 asks an idle
# drainer answered in seconds, then redid their OCR after a 120 s+ backoff). A deep spool still defers at once.
for _k in vlm.spooled():
    vlm.drain_one()
os.environ[vlm.SPOOL_WAIT_ENV] = "10"
os.environ[vlm.SPOOL_ENV] = "1"
vlm._SLOTS[0] = 1
vlm.PIPELINE = 0
vlm._WAITED[0] = 0.0
_real_poll = vlm.SPOOL_POLL
vlm.SPOOL_POLL = 0.02
urllib.request.urlopen = fake_ok
_stop = threading.Event()
def _drainer():
    while not _stop.is_set():
        if not vlm.drain_one():
            real_sleep(0.02)
_dt = threading.Thread(target=_drainer, daemon=True)
_dt.start()
_n0, _u0 = len(asked), vlm.unanswered()
check("a shallow spool: one ask waits for the drainer's answer", ("spoolt", False, _u0),
      (vlm.ask_png(b"wait-one", "p", 10), vlm.missed(), vlm.unanswered()))
_wcols = [Image.new("L", (400, 300), 141 + i) for i in range(3)]
check("... a read_all spools all its columns, waits once and reads on", (["spoolt"] * 3, False, _u0, 4),
      (vlm.read_all(_wcols), vlm.missed(), vlm.unanswered(), len(asked) - _n0))
_wpage = Image.new("L", (400, 300), 151)
check("... read_columns too, in the boxes' order", (["spoolt"] * 2, False),
      (vlm.read_columns("wait-page", _wpage, [(0, 0, 100, 100), (200, 0, 300, 100)]), vlm.missed()))
_wpk = ocr_clues.vlm_pick(pk_texts, pk_laid, pk_blank, f.parse, lambda lid, cands: vlm.pick_in(_wpage, lid, cands))
check("... and vlm_pick's picks, without deferring", (False, _u0), (vlm.missed(), vlm.unanswered()))
_stop.set()
_dt.join(10)
# No drainer: the wait ends at its bound and the read defers as before.
os.environ[vlm.SPOOL_WAIT_ENV] = "0.2"
_t0 = time.monotonic()
try:
    vlm.read_all([Image.new("L", (400, 300), 161)])
    _wraised = None
except vlm.Spooled as e:
    _wraised = len(e.keys)
check("no answer within the bound: the read defers, its asks named", (1, True, "spooled", True),
      (_wraised, vlm.missed(), vlm.cause(), time.monotonic() - _t0 < 5))
for _k in vlm.spooled():
    vlm.drain_one()
vlm._MISSED[0] = False
vlm._CAUSE[0] = ""
# A deep spool (others' asks at feed_target): no wait at all.
os.environ[vlm.SPOOL_WAIT_ENV] = "10"
for _i in range(vlm.feed_target()):
    _dk = f"deep{_i}".ljust(40, "z")  # not a key answered above
    vlm.put_spool(_dk, b"deep%d" % _i, "p", 10)
    (vlm.spool_dir() / (_dk + ".json")).write_text(json.dumps({"prompt": "p", "max_tokens": 10, "pid": 424242, "at": 0}))
_t0 = time.monotonic()
try:
    vlm.ask_png(b"deep-mine", "p", 10)
    _draised = False
except vlm.Spooled as e:
    _draised = e.keys == [vlm.ask_key(b"deep-mine", "p")]
check("a deep spool: the ask defers at once, as before", (True, True, True),
      (_draised, vlm.missed(), time.monotonic() - _t0 < 1))
for _k in vlm.spooled():
    vlm.drain_one()
vlm.SPOOL_POLL = _real_poll
os.environ.pop(vlm.SPOOL_WAIT_ENV)
os.environ.pop(vlm.SPOOL_ENV)
vlm._MISSED[0] = False
vlm._CAUSE[0] = ""

# A spooled read's guard says so, not "went down".
vlm._MISSED[0] = True
vlm._CAUSE[0] = "spooled"
os.environ[vlm.DEFER_ENV] = "1"
try:
    vlm.guard("a row")
    _msg = ""
except vlm.Down as e:
    _msg = str(e)
check("a spooled guard names the spool", (True, False), ("spooled" in _msg, "went down" in _msg))
os.environ.pop(vlm.DEFER_ENV)
vlm._MISSED[0] = False
vlm._CAUSE[0] = ""

# CT_VLM_DRYRUN: a cached ask answers, an uncached one is counted, not sent or spooled.
_img = f.Image.new("RGB", (30, 20), "white") if hasattr(f, "Image") else __import__("PIL.Image").Image.new("RGB", (30, 20), "white")
_data = vlm.png(_img)
_hit = vlm.ask_key(_data, "p1")
vlm.CACHE.mkdir(parents=True, exist_ok=True)
(vlm.CACHE / f"{_hit}.txt").write_text("cached answer")
_spool_before = vlm.spooled()
os.environ[vlm.DRYRUN_ENV] = "1"
try:
    _got = (vlm.ask_png(_data, "p1"), vlm.ask_png(_data, "p2"), vlm.ask_png(_data, "p2"), vlm.reachable())
finally:
    os.environ.pop(vlm.DRYRUN_ENV)
_t = vlm.dryrun_tally()
check("dry run: cached answers, uncached is empty and True reachable", ("cached answer", "", "", True), _got)
check("dry run: one uncached ask noted once with its size", (1, [30, 20], vlm.spooled()), (len(_t["asks"]), _t["asks"][0]["size"], _spool_before))
check("dry run: nothing cached for the uncached ask", False, (vlm.CACHE / f"{vlm.ask_key(_data, 'p2')}.txt").exists())
check("dry run off by default", False, vlm.dryrun())

# vlm_asks.log: a trailing why=<trigger> from vlm.because, in the spool entry only (the key is the same).
_log = Path(tempfile.mkdtemp()) / "asks.log"
os.environ["CT_VLM_ASK_LOG"] = str(_log)
_key_before = vlm.ask_key(b"why-img", "why-prompt")
vlm._log_ask("a" * 40, {"unit": "p/i/e", "prompt": "why-prompt"})
with vlm.because("weak:12a(blank),5d(unsettled)"):
    _key_in = vlm.ask_key(b"why-img", "why-prompt")
    vlm._log_ask("b" * 40, {"unit": "p/i/e", "prompt": "why-prompt", "why": vlm._WHY.get()})
check("ask log: no why= when no reason", False, "why=" in _log.read_text().splitlines()[0])
check("ask log: why= is the last field, space-free", "weak:12a(blank),5d(unsettled)",
      _log.read_text().splitlines()[1].split()[-1][len("why="):])
check("ask log: the reason does not change the cache key", _key_before, _key_in)
check("ask log: the reason is reset after the block", "", vlm._WHY.get())
os.environ.pop("CT_VLM_ASK_LOG")

if fails:
    print("test_vlm_reader: failed")
    sys.exit(1)
print("test_vlm_reader: all passed")
