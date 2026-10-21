#!/usr/bin/env python3
# Does tools/desktop_hosts.py find the desktop's live address itself (its LAN
# lease flaps), probing every address at once, keeping the order a TTL,
# probing afresh after forget(), and do ocr_remote.by_path and
# vlm_reader.resolve use it, so one dead LAN address stalls nothing?
#
#     python3 tools/test_desktop_hosts.py
#
# Fake desktops on loopback addresses: no network, nothing written outside a temp dir.
import atexit
import os

# The desktop the code reaches is a fake one: the real addresses live in an untracked local config.
os.environ.update(CT_LOCAL_CONFIG="/nonexistent", CT_DESKTOP_USER="tester", CT_VLM_PORT="8000",
                  CT_DESKTOP_ADDRESSES="192.0.2.198 192.0.2.180 100.64.0.15", CT_DESKTOP_HOME="C:\\Users\\tester\\ocrw")
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
tmp = tempfile.mkdtemp()
atexit.register(shutil.rmtree, tmp, True)
os.environ["TMPDIR"] = tmp
os.environ["OCR_REMOTE"] = ""
tempfile.tempdir = None
os.chdir(TOOLS)
sys.path.insert(0, str(TOOLS))
import desktop_hosts as dh

fails = 0
def check(what, want, got):
    global fails
    if want == got:
        print(f"ok   {what}")
    else:
        fails += 1
        print(f"FAIL {what}: expected {want!r}, got {got!r}")

def server(addr, banner):
    """A listener on addr: says `banner` to each connection (None: says nothing)."""
    s = socket.socket()
    s.bind((addr, 0))
    s.listen(16)
    def loop():
        while True:
            try:
                c, _ = s.accept()
            except OSError:
                return
            if banner:
                c.sendall(banner)
            threading.Timer(10, c.close).start()
    threading.Thread(target=loop, daemon=True).start()
    return s, s.getsockname()[1]

# One port for all: the live sshd on 127.0.0.2, a silent one (a stale lease
# that takes the connect and says nothing) on 127.0.0.3, nothing on 127.0.0.4.
live, port = server("127.0.0.2", b"SSH-2.0-OpenSSH_for_Windows_9.5\r\n")
silent = socket.socket(); silent.bind(("127.0.0.3", port)); silent.listen(4)
dh.ADDRESSES = ("127.0.0.3", "127.0.0.4", "127.0.0.2")
dh.SSH_PORT = port
dh.PROBE_TIMEOUT = 1.0
dh.learn = lambda via, timeout=30: []
t = time.monotonic()
check("the answering address ranks first, the silent and dead ones after",
      ["127.0.0.2", "127.0.0.3", "127.0.0.4"], dh.ranked(port))
took = time.monotonic() - t
check(f"all probed at once: one timeout, not one each ({took:.1f}s)", True, took < 2 * dh.PROBE_TIMEOUT)
check("a banner is needed for ssh: a silent connect is not alive", False, dh.answers("127.0.0.3", port, 0.5))

probes = []
kept_probe = dh.probe_all
dh.probe_all = lambda a, p, timeout=1.0: (probes.append(tuple(a)), kept_probe(a, p, timeout))[1]
check("within TTL the ranking stands, unprobed", (["127.0.0.2", "127.0.0.3", "127.0.0.4"], 0),
      (dh.ranked(port), len(probes)))
dh.forget(port)
dh.ranked(port)
check("forget(): the next ranked() probes again", 1, len(probes))
dh.clock = lambda: time.time() + dh.TTL + 1
dh.ranked(port)
check("past TTL it probes again", 2, len(probes))
dh.clock = time.time

# The lease flips: the live address moves to 127.0.0.4.
live.close()
moved, _ = None, None
moved = socket.socket(); moved.bind(("127.0.0.4", port)); moved.listen(4)
def accept_banner(s):
    while True:
        try:
            c, _ = s.accept()
        except OSError:
            return
        c.sendall(b"SSH-2.0-x\r\n")
threading.Thread(target=accept_banner, args=(moved,), daemon=True).start()
dh.forget(port)
check("after the flip the new address ranks first", "127.0.0.4", dh.ranked(port)[0])

# LAN before tailnet when both answer.
dh.probe_all = lambda a, p, timeout=1.0: {x: True for x in a}
dh.ADDRESSES = ("100.64.0.15", "192.0.2.180")
check("both answer: LAN before tailnet", ["192.0.2.180", "100.64.0.15"], dh.ranked(99, fresh=True))
check("both answer, tailnet_first (the VLM, the game-yield probe): tailnet before LAN", ["100.64.0.15", "192.0.2.180"],
      dh.ranked(99, tailnet_first=True))
dh.probe_all = lambda a, p, timeout=1.0: {x: x != "100.64.0.15" for x in a}
check("tailnet_first: a silent tailnet address still ranks after the answering LAN one", ["192.0.2.180", "100.64.0.15"],
      dh.ranked(98, fresh=True, tailnet_first=True))
dh.probe_all = lambda a, p, timeout=1.0: {x: True for x in a}

# Only the tailnet answers: the desktop is asked for its LAN address, which then ranks first.
dh.ADDRESSES = ("192.0.2.198", "100.64.0.15")
dh.probe_all = lambda a, p, timeout=1.0: {x: x in ("100.64.0.15", "192.0.2.77") for x in a}
asked = []
def learn(via, timeout=30):
    asked.append(via)
    st = dh._load(); st["learned"] = {"t": dh.clock(), "addresses": ["192.0.2.77"]}; dh._save(st)
    return ["192.0.2.77"]
dh.learn = learn
dh.SSH_PORT = 22
got = dh.ranked(22, fresh=True)
check("only the tailnet answers: the LAN lease is learned over it and ranks first",
      (["100.64.0.15"], "192.0.2.77"), (asked, got[0]))
check("a learned address counts as the desktop", True, dh.is_desktop("192.0.2.77"))

# ocr_remote.by_path: every desktop address, ranked; other hosts kept.
import ocr_remote
ocr_remote.desktop_hosts.ranked = lambda port=22, fresh=False: ["192.0.2.77", "100.64.0.15", "192.0.2.198"]
check("by_path: desktop hosts become the live ranking, with their user",
      ["tester@192.0.2.77", "tester@100.64.0.15", "tester@192.0.2.198"], ocr_remote.by_path(["tester@192.0.2.198"]))
check("by_path: a test's loopback host is left alone", ["me@127.0.0.1"], ocr_remote.by_path(["me@127.0.0.1"]))

# vlm_reader.resolve: every URL asked at once; a dead LAN URL costs one timeout, not a "down".
import vlm_reader as vlm
vlm.URLS = ["http://192.0.2.198:8000", "http://192.0.2.180:8000", "http://198.51.100.15:8000"]
asked = []
def answers(url):
    asked.append(url)
    if "192.0.2.198" in url:
        time.sleep(vlm.CONNECT_TIMEOUT)  # the stale lease: a connect timeout
        return False
    return True
vlm._answers = answers
vlm.URL, vlm._RESOLVED[0] = vlm.URLS[0], False
t = time.monotonic()
got = vlm.resolve()
took = time.monotonic() - t
check("resolve: the dead LAN URL loses to the next live LAN one", "http://192.0.2.180:8000", got)
check(f"resolve: one timeout in parallel, not one per URL ({took:.1f}s)", True, took < vlm.CONNECT_TIMEOUT + 1.5)
check("resolve: every URL asked", 3, len(set(asked)))

print("FAILS", fails)
sys.stdout.flush()
sys.exit(1 if fails else 0)
