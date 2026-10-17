#!/usr/bin/env python3
# Does tools/vlm_reader.py stay out of the way when the desktop's VLM does
# not answer, cache what it asks, crop each clue column alone, and does
# file_archive_org_puzzles.py fill a blank clue with its reading and re-read
# an edition once it answers?
#
#     python3 tools/test_vlm_reader.py
#
# The VLM is mocked: no network, no scan, nothing written outside a temp dir.
import atexit
import os
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
# A fake desktop, never the real one: two LAN leases and a tailnet address
# from the documentation ranges (RFC 5737), whatever tools/desktop_hosts.json
# lists, and no ssh to ask whether it is busy.
vlm.URLS = ["http://192.0.2.198:8090", "http://192.0.2.180:8090", "http://198.51.100.15:8090"]
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
readings = [[[(20, 40, 15, 180, "1 Left clue (5)")], [(30, 60, 210, 380, "2 Right (4)")]]]
check("crop boxes span each column's lines, padded",
      [(5, 10, 190, 50), (200, 20, 390, 70)], vlm.boxes(img, wins, readings))

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
vlm._SLOTS[0] = 2
vlm._MISSED[0] = False
live, peak, lk = [0], [0], threading.Lock()
def fake_slow(req, timeout=None):
    with lk:
        live[0] += 1
        peak[0] = max(peak[0], live[0])
    time.sleep(0.05)
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

if fails:
    print("test_vlm_reader: failed")
    sys.exit(1)
print("test_vlm_reader: all passed")
