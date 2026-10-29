"""A vision-language model as one more reader of scanned clue columns.

Any OCR pipeline can use it as a voter: column_text() transcribes each clue
column of a page image (its boxes taken from the other readers' lines), and
pick() reads one clue the readers disagree on, shown their readings. The
model is qwen3.8-vl-27b behind llama-swap on the GPU host
(VLM_READER_URL / VLM_READER_MODEL; an empty URL turns it off). When the
server does not answer (desktop off, model missing) reachable() is False and
a caller reads exactly as without it; version() names what its readings
depend on, for a caller's input hash. While Paul games on the desktop
(tools/desktop_busy.py) it is not reachable either, and ask() raises as
when the server is down: it is asked again once the desktop is idle.

A read the edition queue starts (DEFER_ENV set) never reads on without the
model (Paul 10-13: "If the vision model is down and you need it just go onto
the next scan and do it when it is back"): wanted(), a reader's check before
it asks, raises Down when the model is not reachable, and a reply lost
mid-read (ask() failing or yielding) makes guard() raise Down at the read's
next puzzle write or ledger row (scan_queue.file_puzzle, scan_queue.append),
so the read ends deferred, writing nothing, and the queue holds it until
up() says the model answers again. What never asks (a Trove article that is
no crossword, a scan, a fetch) reads and files as before.

Prompts: vlm_column_prompt.md and vlm_pick_prompt.md. Replies are cached by
a hash of the model, prompt and image under ~/.cache/vlm_reader, so a re-run
asks nothing new.
"""
import base64
import hashlib
import io
import contextlib
import contextvars
import json
import os
import random
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import desktop_busy
import desktop_hosts
from ocr_clues import unhyphen

TOOLS = Path(__file__).resolve().parent
#: The desktop's VLM addresses, tailnet first (tools/local_config.py); URL is
#: the one in use: VLM_READER_URL if set (it alone, no fallback), else the
#: first of URLS that answers (resolve()), the LAN one until then.
URLS = sorted(desktop_hosts.VLM_URLS, key=lambda u: not desktop_hosts.tailnet(u.split("//")[1].rsplit(":", 1)[0]))
URL = os.environ.get("VLM_READER_URL", URLS[0] if URLS else "")  # no local config: no VLM
#: Seconds every URL has to answer, all asked at once (resolve): the tailnet
#: path goes quiet for seconds in bursts.
CONNECT_TIMEOUT = 3
_RESOLVED = [False]
MODEL = os.environ.get("VLM_READER_MODEL", "qwen3.8-vl-27b")
PROMPT = TOOLS / "vlm_column_prompt.md"
PICK_PROMPT = TOOLS / "vlm_pick_prompt.md"
CACHE = Path(os.environ.get("CT_VLM_CACHE") or os.path.expanduser("~/.cache/vlm_reader"))  # CT_VLM_CACHE: an offline A/B's own (empty) cache
#: The scans print ~17px a line; the model reads them better twice the size.
UPSCALE = 2
#: Padding round a column's text, in page pixels.
PAD = 10

_UP = {}
#: This process's asks since spent() last said: real server calls by kind
#: ("read" a column, "pick" a clue, "other"), and cache hits.
_SPENT = {"read": 0, "pick": 0, "other": 0, "cached": 0}
#: When ask() last yielded to a game: reachable() stays False a while after,
#: so a caller does not take a read that lost its VLM half-way for a full one.
_YIELDED = [float("-inf")]


#: Set (to anything) in a read unit's environment by the edition queue: a
#: read there that needs the model while it is down ends deferred (Down),
#: never read without it.
DEFER_ENV = "CT_VLM_DEFER"
#: Whether this process wanted the model and went without it: wanted() found
#: it unreachable, or an ask failed or yielded mid-read. Never cleared.
_MISSED = [False]
#: How many asks this process left unanswered for the drainer (spooled, or refused as the
#: spool was full): each ends its read deferred. A reader that sees it move between two
#: steps knows the answers it judged the first by are not all in, and the read will run
#: again once they are: unanswered().
_UNANSWERED = [0]


def unanswered():
    return _UNANSWERED[0]


class Down(RuntimeError):
    """A read that needs the model met it down, under DEFER_ENV: the read
    ends deferred (edition_commit.EXITS["vlm"]), writing nothing."""


def wanted():
    """reachable(), asked by a reader about to use the model. When it is not
    (and a URL is set, or none was ever configured, see unconfigured(): an
    explicitly empty VLM_READER_URL turns the model off, and the read goes on
    without it) the miss is noted, and under DEFER_ENV it raises Down."""
    if reachable():
        return True
    if unconfigured():
        _MISSED[0] = True
        _CAUSE[0] = UNCONFIGURED
        if os.environ.get(DEFER_ENV):
            raise Down(f"{UNCONFIGURED}; the read waits for it")
    elif URL:
        _MISSED[0] = True
        if os.environ.get(DEFER_ENV):
            raise Down(f"VLM {MODEL} at {URL} is down ({_CAUSE[0] or 'unreachable'})")
    return False


#: Why the VLM is not used when no address was ever given (cause()).
UNCONFIGURED = "VLM URL not configured (no VLM_READER_URL, no VLM in ~/.config/cryptic-teacher/local.json)"


def unconfigured():
    """Whether there is no VLM address and nobody asked for none: VLM_READER_URL
    unset and the host has no VLM in its local config (desktop_hosts.VLM_URLS).
    That is a host that lost its config (10-21: a commit moved the addresses to
    ~/.config/cryptic-teacher/local.json and the live queue had no such file, so every
    read ran OCR-only for 30 minutes, unlogged), never a choice: the OCR-only
    opt-out is an explicitly set, empty VLM_READER_URL."""
    return not URL and "VLM_READER_URL" not in os.environ


def missed():
    """Whether this process wanted the model and went without it (_MISSED)."""
    return _MISSED[0]


def guard(what):
    """Raise Down, under DEFER_ENV, when this process went without the model
    it wanted (missed): `what` (a puzzle write, a ledger row) would record a
    read made without it."""
    if _MISSED[0] and os.environ.get(DEFER_ENV):
        if _CAUSE[0] == "spooled":
            raise Down(f"{len(spooled_by(os.getpid()))} VLM asks spooled for the drainer; {what} not written")
        if _CAUSE[0] == "spool full":
            raise Down(f"VLM spool full; {what} not written")
        if _CAUSE[0] == UNCONFIGURED:
            raise Down(f"{UNCONFIGURED}; {what} not written")
        raise Down(f"VLM {MODEL} at {URL} went down mid-read ({_CAUSE[0] or 'unknown'}); {what} not written")


def went_without(what):
    """Note that a read made elsewhere (the desktop's, tools/ocr_remote.py)
    lost the model it was sent with, then guard(what)."""
    _MISSED[0] = True
    guard(what)


#: Seconds up()'s answer stands: the queue asks once a minute at most, never once a unit.
UP_EVERY = 60
_UP_AT = [float("-inf"), False]


#: Whether the last reachable() found the server not answering (a timeout or
#: refusal), as against busy (a game, a chat model) or not listing MODEL.
_UNREACHED = [False]
#: A server that answered at the last up() and then fails to answer is asked
#: again UP_RETRIES times, UP_RETRY_WAIT seconds apart, before up() says down:
#: the desktop under load answers /v1/models late now and then, and one late
#: answer must not defer the queue's ~850 scans for a minute (and log "VLM down").
UP_RETRIES = 2
UP_RETRY_WAIT = 5


def up():
    """reachable() asked afresh at most every UP_EVERY seconds, for a
    long-running process (the edition queue): reachable() itself answers
    once a process, for a read that must not change its mind half-way.
    A server that was up and does not answer is down only after
    UP_RETRIES more asks also find it silent (UP_RETRY_WAIT apart)."""
    if time.monotonic() - _UP_AT[0] >= UP_EVERY:
        was = _UP_AT[1]
        _UP.pop(MODEL, None)
        got = reachable()
        for _ in range(UP_RETRIES):
            if got or not was or not _UNREACHED[0]:
                break
            time.sleep(UP_RETRY_WAIT)
            _UP.pop(MODEL, None)
            got = reachable()
        _UP_AT[:] = [time.monotonic(), got]
    return _UP_AT[1]


#: How long llama-swap's /running answer stands, like desktop_busy.PROBE_EVERY's.
CHAT_EVERY = 30
#: ... and when it did not answer (a server down costs its 3s connect each ask).
CHAT_DOWN_EVERY = 120
_CHAT = [float("-inf"), None, True]


def chat_model():
    """The other model llama-swap has loaded and ready, or None: asking for
    ours would evict it from the card, and a room (#local-model) is using
    it. Its ttl unloads it after idle minutes, then ours loads again. An
    answer that does not come or parse is no chat model; asked at most once
    every CHAT_EVERY seconds."""
    if time.monotonic() - _CHAT[0] < (CHAT_EVERY if _CHAT[2] else CHAT_DOWN_EVERY):
        return _CHAT[1]
    answered = True
    try:
        req = urllib.request.Request(f"{URL}/running", headers={"User-Agent": "cryptic-teacher"})
        loaded = json.load(urllib.request.urlopen(req, timeout=3)).get("running", [])
        other = sorted(m["model"] for m in loaded if m.get("state") == "ready" and m.get("model") != MODEL)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        other, answered = [], False
    _CHAT[:] = [time.monotonic(), other[0] if other else None, answered]
    return _CHAT[1]


def _answers(url):
    """Whether `url` answers /v1/models within CONNECT_TIMEOUT."""
    try:
        req = urllib.request.Request(f"{url}/v1/models", headers={"User-Agent": "cryptic-teacher"})
        json.load(urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT))
        return True
    except (OSError, ValueError):
        return False


def resolve():
    """The URL in use, found once a process: URL itself when it is not one of
    URLS (an override), else the first of URLS (URL's first, then tailnet before
    tailnet) that answers, every one asked at once, which URL is then set to
    and kept until it stops answering (reachable then resolves again). A LAN
    address gone stale (DHCP) costs one short timeout in parallel with the
    rest, never the VLM, and never one timeout per address in turn. When none
    answers URL stays and the next call asks again."""
    global URL
    if _RESOLVED[0] or not URL:
        return URL
    if URL in URLS:
        found = _first_answering([URL] + sorted((u for u in _candidates() if u != URL), key=lambda u: not _on_tailnet(u)))
        if found:
            URL = found
            _RESOLVED[0] = True
    else:
        _RESOLVED[0] = True
    return URL


def _candidates():
    """URLS, and while it is the json's own list, the VLM at any LAN address
    the desktop last reported (desktop_hosts.learned): a lease the json
    never listed is still found."""
    if sorted(URLS) != sorted(desktop_hosts.VLM_URLS):
        return list(URLS)
    return list(dict.fromkeys([*URLS, *(f"http://{a}:{desktop_hosts.VLM_PORT}" for a in desktop_hosts.learned())]))


def _on_tailnet(url):
    return desktop_hosts.tailnet(urllib.parse.urlparse(url).hostname or "")


def _first_answering(urls):
    """The first of `urls` that answers (_answers), all asked at once; None
    when none does within CONNECT_TIMEOUT."""
    import threading
    got = {}

    def one(u):
        got[u] = _answers(u)
    threads = [threading.Thread(target=one, args=(u,), daemon=True) for u in urls]
    for t in threads:
        t.start()
    end = time.monotonic() + CONNECT_TIMEOUT + 1
    for t in threads:
        t.join(max(0.0, end - time.monotonic()))
    return next((u for u in urls if got.get(u)), None)


def busy():
    """Why the desktop the server is on is busy, or None: Paul gaming
    (desktop_busy), or another model loaded that we would evict."""
    resolve()
    host = urllib.parse.urlparse(URL).hostname
    why = desktop_busy.busy([f"{desktop_busy.USER}@{host}"]) if host else None
    if why or not URL:
        return why
    other = chat_model()
    return f"{other} is loaded, in use by a chat room" if other else None


def reachable():
    """Whether the server answers and lists MODEL, asked once a process, and
    the desktop it is on is not busy."""
    _UNREACHED[0] = False
    if dryrun():
        return True
    if not URL:
        return False
    resolve()
    if time.monotonic() - _YIELDED[0] < desktop_busy.PROBE_EVERY or busy():
        return False
    if MODEL not in _UP:
        ids = _models()
        if ids is None and _RESOLVED[0] and URL in URLS:
            # The address found before stopped answering (the LAN lease
            # moved under a long-running queue): every URL is tried again.
            was = URL
            _RESOLVED[0] = False
            if resolve() != was:
                ids = _models()
        _UNREACHED[0] = ids is None
        _UP[MODEL] = MODEL in (ids or ())
    return _UP[MODEL]


#: How long a read rides out a dropped link before calling the VLM down: the
#: tailnet path re-handshakes for about a minute when the Mac's tailscaled
#: resets (10-22: every 15-20 min), and a read deferred for that redoes its OCR.
BLIP_SECONDS = float(os.environ.get("CT_VLM_BLIP_SECONDS", "90"))


def _blip_waits():
    """Pauses between tries while the link may be re-handshaking (BLIP_SECONDS in all)."""
    left, wait = BLIP_SECONDS, 5.0
    while left > 0:
        yield min(wait, left)
        left -= wait
        wait = min(wait * 2, 30.0)


def _models():
    """The model ids URL lists, or None when it does not answer (within BLIP_SECONDS)."""
    waits = _blip_waits()
    while True:
        try:
            req = urllib.request.Request(f"{URL}/v1/models", headers={"User-Agent": "cryptic-teacher"})
            return {m.get("id") for m in json.load(urllib.request.urlopen(req, timeout=3)).get("data", [])}
        except ValueError:
            return None
        except OSError:
            pause = next(waits, None)
            if pause is None:
                return None
            time.sleep(pause)


def version():
    """What the readings depend on: the model and both prompts."""
    h = hashlib.sha1(MODEL.encode())
    h.update(PROMPT.read_bytes())
    h.update(PICK_PROMPT.read_bytes())
    return h.hexdigest()[:10]


def png(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def encoder():
    """What png()'s bytes depend on here: Pillow's version (its row filters)
    and the zlib it deflates with."""
    import PIL
    from PIL import features
    return f"{PIL.__version__}/{features.version('zlib')}"


#: The modes Pillow writes as filtered rows deflated with Z_FILTERED, as
#: png_as() remakes them (a palette image's rows are deflated otherwise).
FILTERED_MODES = ("1", "L", "RGB", "RGBA")


def png_as(img, theirs):
    """png(img) as a host whose encoder() is `theirs` makes it, or None when
    this one cannot: Pillow's filtered rows (the same at any level),
    deflated by Python's zlib as Pillow's encoder deflates them, cut into
    IDAT chunks as ImageFile._save cuts them. A host whose Pillow deflates
    with another zlib (zlib-ng) makes other bytes for the same pixels, and
    the cache is keyed by those bytes."""
    import struct
    import zlib

    import PIL
    from PIL import ImageFile
    if theirs != f"{PIL.__version__}/{zlib.ZLIB_RUNTIME_VERSION}" or img.mode not in FILTERED_MODES:
        return None
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=0)
    data = buf.getvalue()
    before, idat, after, pos = [data[:8]], [], [], 8
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        if kind == b"IDAT":
            idat.append(data[pos + 8:pos + 8 + n])
        else:
            (after if idat else before).append(data[pos:pos + 12 + n])
        pos += 12 + n
    z = zlib.compressobj(6, zlib.DEFLATED, 15, 9, zlib.Z_FILTERED)
    stream = z.compress(zlib.decompress(b"".join(idat))) + z.flush()
    size = max(ImageFile.MAXBLOCK, img.size[0] * 4)
    chunks = [stream[i:i + size] for i in range(0, len(stream), size)]
    return b"".join(before + [struct.pack(">I4s", len(c), b"IDAT") + c + struct.pack(">I", zlib.crc32(b"IDAT" + c))
                              for c in chunks] + after)


#: A 429 from the server (its queue is full) is asked again after a wait, this
#: many tries in all: 19 of 328 asks drew one at 14 concurrent reads, and each
#: used to end its read deferred and log "VLM down" with the VLM serving.
#: Still 8 tries was too few: with ~30 reads asking a one-slot llama-server
#: (337 of 466 asks drew a 429 in one morning) the last try often drew one
#: too, and ~120 reads a pass ended deferred with the VLM serving. 20 tries
#: wait ~17 min at most, under ocr_remote.EDITION_TIMEOUT. A 502/503/504
#: (llama-swap's upstream hiccup: three 502s after 30-42s) is asked again too.
QUEUE_FULL_TRIES = 20
QUEUE_FULL_WAIT = 10
RETRY_CODES = (429, 502, 503, 504)


#: Why the model last went unused: "HTTP 429", "timeout", "refused", "yield: ..."
#: (cause()). Every "VLM down"/deferred line carries it, so an audit counts causes.
_CAUSE = [""]
#: In-flight asks allowed at once, host-wide: the server's slot count (llama-server
#: -np), read once from its /props `total_slots`, else SLOTS_FALLBACK. Locks are
#: flock files in the temp dir (like ocr_remote.local_slot): they matter only while
#: the asking processes live, and flock frees them when those die, so /tmp suffices.
SLOTS_FALLBACK = 1
_SLOTS = [None]
#: Extra asks kept in flight beyond slots() (env CT_VLM_PIPELINE, default 1): the
#: server queues them behind the running one (it still answers one per slot at a
#: time, nothing batched), so the GPU never idles while the next ask polls the
#: lock, encodes and uploads. Their clock includes the wait for the one ahead,
#: so REQUEST_TIMEOUT grows by one request's worth per extra ask.
PIPELINE = int(os.environ.get("CT_VLM_PIPELINE", "1"))
REQUEST_TIMEOUT = 600


def cause():
    """Why the last ask failed or yielded, "" if none has."""
    return UNCONFIGURED if unconfigured() else _CAUSE[0]


def cause_of(e):
    """A short cause for exception `e`: HTTP status, timeout, refused or the error's name."""
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    r = getattr(e, "reason", e)
    if isinstance(r, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(r, ConnectionRefusedError):
        return "refused"
    return type(r).__name__


def slots():
    """The server's slot count: /props total_slots (llama-swap's /upstream/MODEL/props),
    else SLOTS_FALLBACK. Asked once a process."""
    if _SLOTS[0] is None:
        n = SLOTS_FALLBACK
        try:
            props = json.load(urllib.request.urlopen(f"{URL}/upstream/{MODEL}/props", timeout=5))
            n = max(1, int(props.get("total_slots") or n))
        except Exception:
            pass
        _SLOTS[0] = n
    return _SLOTS[0]


#: Drainer threads waiting for a slot leave a file named for their pid in the temp dir's
#: vlm_reader.draining/: direct askers (slot() without priority) hold off while a live
#: other process has one, so spooled asks are not starved by reads asking directly.
_DRAINING = [0]
_DRAINING_LOCK = threading.Lock()


def _draining_dir():
    return Path(tempfile.gettempdir()) / "vlm_reader.draining"


def drainer_waiting():
    """Whether a live process other than this one has a drainer thread waiting for a slot."""
    try:
        files = list(_draining_dir().iterdir())
    except OSError:
        return False
    found = False
    for f in files:
        if not f.name.isdigit() or not _alive(int(f.name)):
            f.unlink(missing_ok=True)
        elif int(f.name) != os.getpid():
            found = True
    return found


@contextlib.contextmanager
def _draining():
    mark = _draining_dir() / str(os.getpid())
    with _DRAINING_LOCK:
        _DRAINING[0] += 1
        try:
            mark.parent.mkdir(parents=True, exist_ok=True)
            mark.touch()
        except OSError:
            pass
    try:
        yield
    finally:
        with _DRAINING_LOCK:
            _DRAINING[0] -= 1
            if not _DRAINING[0]:
                mark.unlink(missing_ok=True)


@contextlib.contextmanager
def slot(priority=False):
    """Hold one of slots() host-wide lock files for one request. Waiting here is
    queueing, not the server being down: it never marks anything missed. `priority`
    (the drainer): marks itself as waiting; without it, polling holds off while
    another process's drainer waits."""
    import fcntl  # POSIX only: the desktop (Windows) imports this module without using the lock
    n = slots() + max(0, PIPELINE)
    ctx = _draining() if priority else contextlib.nullcontext()
    with ctx:
        while True:
            if not priority and drainer_waiting():
                time.sleep(random.uniform(1.0, 3.0))
                continue
            for i in range(n):
                f = open(Path(tempfile.gettempdir()) / f"vlm_reader.slot.{i}.lock", "w")
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    f.close()
                    continue
                break
            else:
                time.sleep(random.uniform(0.2, 1.0))
                continue
            break
    try:  # the marker is gone: the slot is held until the request ends
        yield
    finally:
        f.close()


#: A process with an ask under way (waiting for a slot, or in flight) leaves a file
#: named for its pid in the temp dir's vlm_reader.waiting/; the queue counts them
#: (waiting_now) to start no read the VLM could not serve soon. Ends with the ask.
_ASKING = [0]


def _waiting_dir():
    return Path(tempfile.gettempdir()) / "vlm_reader.waiting"


#: Env CT_VLM_DRYRUN=1 (never set by the queue): a hand-run read counts its asks
#: instead of making them. A cached ask answers from the cache; one that is not is
#: neither sent nor spooled: it is noted in DRYRUN_ASKS and answered "" (unreadable),
#: so the read finishes in OCR time. At exit the tally is one JSON line on stderr
#: (dryrun_tally): the asks per page. reachable()/wanted() say True
#: then, so the read takes the path that asks. Nothing is written, no key changes.
DRYRUN_ENV = "CT_VLM_DRYRUN"
DRYRUN_ASKS = []
#: Cached answers a dry run replayed, by kind ("read"/"pick"/"other").
CACHED_KINDS = {}


def dryrun():
    return os.environ.get(DRYRUN_ENV, "0") not in ("", "0")


def dryrun_size(data):
    """(width, height) from a PNG's header."""
    import struct
    try:
        return struct.unpack(">II", data[16:24])
    except struct.error:
        return (0, 0)


def dryrun_tally():
    """The asks a dry run noted: {"dryrun": true, "read": n, "pick": n, "other": n, "cached": n, "asks": [...]}."""
    got = {"dryrun": True, "cached": _SPENT["cached"]}
    for k in ("read", "pick", "other"):
        got[k] = sum(a["kind"] == k for a in DRYRUN_ASKS)
    got["cached_kinds"] = dict(CACHED_KINDS)
    got["asks"] = list(DRYRUN_ASKS)
    return got


def _print_tally():
    sys.stderr.write(json.dumps(dryrun_tally(), default=str) + "\n")


if dryrun():
    import atexit
    atexit.register(_print_tally)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        pass  # exists, not ours
    return True


def waiting_now():
    """How many live processes have an ask under way: files of pids still running
    (stale ones, of a process killed mid-ask, are removed)."""
    n = 0
    try:
        files = list(_waiting_dir().iterdir())
    except OSError:
        return 0
    for f in files:
        if f.name.isdigit() and _alive(int(f.name)):
            n += 1
        else:
            f.unlink(missing_ok=True)
    return n


@contextlib.contextmanager
def asking():
    """Mark this process as waiting for the VLM for the length of one ask."""
    mark = _waiting_dir() / str(os.getpid())
    try:
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.touch()
    except OSError:
        pass
    _ASKING[0] += 1
    try:
        yield
    finally:
        _ASKING[0] -= 1
        if not _ASKING[0]:
            mark.unlink(missing_ok=True)


def _moved_to_other():
    """After an ask to URL failed to connect or timed out: re-resolve once
    over the other candidates (_first_answering), and when one answers make
    it URL and return True. False for an override URL or when none answers,
    so a lease flap costs seconds, not a read."""
    global URL
    if URL not in URLS:
        return False
    found = _first_answering(sorted((u for u in _candidates() if u != URL), key=lambda u: not _on_tailnet(u)))
    if not found:
        return False
    sys.stderr.write(f"vlm_reader: {URL} stopped answering, now {found}\n")
    URL = found
    _RESOLVED[0] = True
    return True


def _kind(prompt):
    """Which ask `prompt` is: read() or pick_in()'s."""
    if prompt == PROMPT.read_text():
        return "read"
    return "pick" if prompt.startswith(PICK_PROMPT.read_text().split("{", 1)[0]) else "other"


def spent():
    """The asks counted since the last call, then reset: {"read", "pick",
    "other": real server calls, "cached": answers the cache gave}."""
    got = dict(_SPENT)
    _SPENT.update(dict.fromkeys(_SPENT, 0))
    return got


def vlm_note():
    """What an edition's log line says of its asks: "vlm 2 reads, 3 picks, 1 cached"
    ("vlm 0" with none), spent()'s."""
    n = spent()
    parts = [f"{n[k]} {k}s" for k in ("read", "pick") if n[k]] + ([f"{n['cached']} cached"] if n["cached"] else [])
    return "vlm " + (", ".join(parts) or "0")


def ask(img, prompt, max_tokens=1500):
    """The model's reply to `prompt` about a PIL image, cached."""
    return ask_png(png(img), prompt, max_tokens)


def ask_key(data, prompt):
    """The cache key of the ask of the image whose png() is `data`."""
    return hashlib.sha1(MODEL.encode() + b"\0" + prompt.encode() + b"\0" + data).hexdigest()


#: Env CT_VLM_SPOOL (set by the queue on the reads it starts; "0" or unset: off): a read
#: whose ask is not cached does not wait for the VLM's slot: it spools the ask and
#: raises Spooled (it ends deferred, writing nothing: guard), and the queue's drainer
#: (drain_one) asks the server and caches the answer; the read runs again then.
SPOOL_ENV = "CT_VLM_SPOOL"
#: A spooled ask's files in spool_dir(): KEY.png, KEY.json (prompt, max_tokens, the
#: asking pid, when) marking it queued, and KEY.json.work while a drainer asks it.
CLAIMED = ".json.work"


class Spooled(RuntimeError):
    """An ask was spooled for the drainer instead of asked: the read ends deferred. `keys`: the
    asks this process spooled and waits on (empty when none it can wait for: the spool was full,
    or another host spooled it)."""

    def __init__(self, msg, keys=()):
        super().__init__(msg)
        self.keys = list(keys)


#: Env CT_VLM_SPOOL_WAIT: seconds (default SPOOL_WAIT; 0: never) a read that has just spooled asks
#: waits here for the drainer's answers, when the spool is shallow (spool_shallow), before it ends
#: deferred. 10-24 04:20-04:41: the GPU sat at 0% at ~2.6 asks/min, 18 units' slots full of CPU work,
#: while each FT never-read read did ~60 s of OCR, spooled 1-3 asks, ended deferred, had them answered
#: in seconds by an idle drainer and then waited out a 120 s+ backoff to redo that OCR and find the
#: next stage's 1-3 asks: 90 FT starts in 20 min for 22 filings. Waiting, the read goes on to its next
#: stage's asks at once, its OCR done once. A deep spool still defers: then waiting holds a unit for
#: minutes for nothing the drainer could not do with the read gone.
SPOOL_WAIT_ENV = "CT_VLM_SPOOL_WAIT"
SPOOL_WAIT = 180
#: Seconds a process waits so all told (well under the queue's READ_SECONDS kill, 1200).
SPOOL_WAIT_TOTAL = 480
#: Seconds between looks at the cache while waiting.
SPOOL_POLL = 1.0
_WAITED = [0.0]
#: Set within a batch (batched): an ask spooled there raises at once, and the batch waits once for all.
_BATCH = contextvars.ContextVar("vlm_batch", default=False)


def spool_wait_seconds():
    try:
        return max(0.0, float(os.environ.get(SPOOL_WAIT_ENV, SPOOL_WAIT)))
    except ValueError:
        return float(SPOOL_WAIT)


def feed_target():
    """The asks the queue keeps the VLM fed with (edition_queue.vlm_feed_target): CT_VLM_FEED
    (default 4), at least slots() + PIPELINE."""
    try:
        n = int(os.environ.get("CT_VLM_FEED", "4"))
    except ValueError:
        n = 4
    return max(n, slots() + PIPELINE)


def spool_shallow(keys):
    """Whether the spool's asks other than `keys` are below feed_target(): the drainer is short of
    work and comes to `keys` within seconds."""
    mine = set(keys)
    return len([k for k in spooled() if k not in mine]) < feed_target()


def answered(key):
    return (CACHE / f"{key}.txt").exists()


def wait_answered(keys):
    """Whether every ask of `keys` (spooled by this process) is answered, waiting for the drainer
    up to spool_wait_seconds() (and what is left of SPOOL_WAIT_TOTAL) when the spool is shallow
    (spool_shallow). False at once under a deep spool, outside the queue's spool (SPOOL_ENV), or
    when an ask leaves the spool unanswered (the drainer dropped it)."""
    keys = [k for k in dict.fromkeys(keys) if not answered(k)]
    if not keys:
        return True
    budget = min(spool_wait_seconds(), SPOOL_WAIT_TOTAL - _WAITED[0])
    if budget <= 0 or os.environ.get(SPOOL_ENV, "0") in ("", "0") or not spool_shallow(keys):
        return False
    t0 = time.monotonic()
    try:
        while True:
            keys = [k for k in keys if not answered(k)]
            if not keys:
                return True
            if time.monotonic() - t0 >= budget or not any(pending(k) for k in keys):
                return False
            time.sleep(SPOOL_POLL)
    finally:
        _WAITED[0] += time.monotonic() - t0


def flags():
    """This process's miss state (missed, cause, unanswered), for restore() after a wait."""
    return _MISSED[0], _CAUSE[0], _UNANSWERED[0]


def restore(snap):
    _MISSED[0], _CAUSE[0], _UNANSWERED[0] = snap


@contextlib.contextmanager
def batched():
    """Within the block an ask spooled raises Spooled at once (no wait_answered of its own): the
    caller spools every ask of its pass, then settled() waits once for them all."""
    tok = _BATCH.set(True)
    try:
        yield
    finally:
        _BATCH.reset(tok)


def settled(snap, errors):
    """After a batch (batched) caught the Spooled `errors`: True when each was an ask this process
    spooled (keys) and wait_answered got them all in; the miss state is then put back as it was at
    the batch's start (`snap`, flags()) and the caller asks those again, from the cache. False:
    the caller raises as before, and the read ends deferred."""
    if not errors or any(not e.keys for e in errors):
        return False
    if not wait_answered([k for e in errors for k in e.keys]):
        return False
    restore(snap)
    return True


def joined(errors):
    """One Spooled for a batch's `errors`, carrying all their keys."""
    return Spooled(str(errors[-1]), [k for e in errors for k in e.keys])


def spool_dir():
    return CACHE / "spool"


def vlm_spool_max():
    """Spooled asks (spooled()) at which a read spools no more and ends deferred, and the queue
    holds back the reads that deferred so (env CT_VLM_SPOOL_MAX, default 200). A number in
    ~/.cache/corpus_queue/vlm_spool_max (env CT_VLM_SPOOL_MAX_FILE) beats the env, so the depth
    is tunable live: a deep spool adds no throughput, it only delays new code's asks."""
    try:
        with open(os.path.expanduser(os.environ.get("CT_VLM_SPOOL_MAX_FILE") or "~/.cache/corpus_queue/vlm_spool_max")) as f:
            return max(1, int(f.read().strip()))
    except (OSError, ValueError):
        pass
    try:
        return max(1, int(os.environ.get("CT_VLM_SPOOL_MAX", "200")))
    except ValueError:
        return 200


def full_mark(pid):
    """The file a read of process `pid` leaves when its ask was refused for a full spool."""
    return spool_dir() / f"full.{pid}"


def _unit_label():
    """The queue unit ("paper/rel") whose read is asking, from CT_EDITION_UNIT; "" outside one."""
    try:
        u = json.loads(os.environ.get("CT_EDITION_UNIT") or "{}").get("unit") or {}
        return f"{u['paper']}/{u['rel']}" if u.get("rel") else ""
    except (ValueError, AttributeError, KeyError):
        return ""


_WHY = contextvars.ContextVar("vlm_why", default="")


@contextlib.contextmanager
def because(why):
    """Within the block, asks spooled are tagged `why` in vlm_asks.log. Logging only: the reason
    is in the spool entry, never in the prompt, the cache key or any output."""
    tok = _WHY.set("".join(str(why).split())[:80])
    try:
        yield
    finally:
        _WHY.reset(tok)


def _log_ask(key, entry):
    """One line in vlm_asks.log per real server call the drainer made: when, key, kind, the unit
    that spooled it (so a page's real asks can be tallied against its final outcome), and last
    `why=<trigger>` (no spaces) when the caller said why (because)."""
    try:
        p = Path(os.path.expanduser(os.environ.get("CT_VLM_ASK_LOG") or "~/.cache/corpus_queue/vlm_asks.log"))
        p.parent.mkdir(parents=True, exist_ok=True)
        why = "".join(str(entry.get("why") or "").split())
        with open(p, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S', time.gmtime())} vlm ask {entry.get('unit') or '?'} "
                    f"{_kind(entry.get('prompt', ''))} {key[:12]}{' why=' + why if why else ''}\n")
    except OSError:
        pass


def put_spool(key, data, prompt, max_tokens):
    """Queue the ask `key` for the drainer (png first, the json that marks it last)."""
    d = spool_dir()
    d.mkdir(parents=True, exist_ok=True)
    if (CACHE / f"{key}.txt").exists():
        return
    if (d / f"{key}.json").exists() or (d / f"{key}{CLAIMED}").exists():
        # Another read's ask: this one waits on it too (spooled_by finds it by this mark), so
        # its read ends spooled, not "the VLM is down".
        (d / f"{key}.wait.{os.getpid()}").touch()
        return
    (d / f"{key}.png").write_bytes(data)
    tmp = d / f"{key}.tmp"
    tmp.write_text(json.dumps({"prompt": prompt, "max_tokens": max_tokens, "pid": os.getpid(), "at": time.time(),
                               "unit": _unit_label(), "why": _WHY.get()}))
    tmp.replace(d / f"{key}.json")


def _entry(key):
    d = spool_dir()
    for name in (f"{key}.json", f"{key}{CLAIMED}"):
        if (d / name).exists():
            return d / name
    return None


def pending(key):
    """Whether the ask `key` is spooled and not yet answered."""
    return _entry(key) is not None


def spooled():
    """The spooled asks' keys, oldest first (claimed ones included)."""
    try:
        files = [f for f in spool_dir().iterdir() if f.name.endswith(".json") or f.name.endswith(CLAIMED)]
        return [f.name.split(".")[0] for f in sorted(files, key=lambda f: f.stat().st_mtime)]
    except OSError:
        return []


def spooled_by(pid):
    """The keys of the asks process `pid` spooled and nobody has answered."""
    out = []
    for k in spooled():
        try:
            if json.loads(_entry(k).read_text()).get("pid") == pid or (spool_dir() / f"{k}.wait.{pid}").exists():
                out.append(k)
        except (OSError, ValueError, AttributeError):
            pass
    return out


#: The claims (KEY.json.work paths) this process's drain_one holds now: release_claims queues them
#: again before the process re-execs (edition_queue's hot reload), which ends its drainer threads
#: mid-ask. 10-29 01:14: a re-exec left three claims that no drainer took again for 6 min.
_MINE = set()
_MINE_LOCK = threading.Lock()
#: A claim no live process can be asking: its claimer's pid is gone, or (older entries, no pid)
#: it was claimed longer ago than an ask can last (REQUEST_TIMEOUT per ask in flight) plus this.
CLAIM_GRACE = 120


def _claimer(f):
    try:
        got = json.loads(f.read_text())
        return got.get("claimed_by") if isinstance(got, dict) else None
    except (OSError, ValueError):
        return None


def requeue_claimed(start=True):
    """Queue claimed asks again that no live drainer is asking; their count. A claim names its
    claimer's pid (drain_one): stale when that process is gone, or is this one and the claim is not
    among this image's own (_MINE: a re-exec keeps the pid, and ended the threads mid-ask). Another
    live process's claims are left (a hand drainer mid-ask). A claim without a pid (older code's)
    is stale at a drainer's `start` (as before), else once older than an ask can take."""
    d = spool_dir()
    n = 0
    with _MINE_LOCK:
        mine = set(_MINE)
    for f in (d.glob(f"*{CLAIMED}") if d.exists() else []):
        if f in mine:
            continue
        pid = _claimer(f)
        if pid is None:
            try:
                age = time.time() - f.stat().st_ctime  # the claim's rename
            except OSError:
                continue
            stale = start or age > REQUEST_TIMEOUT * (1 + max(0, PIPELINE)) + CLAIM_GRACE
        else:
            stale = pid == os.getpid() or not _alive(pid)  # this pid's, not in _MINE: an image before a re-exec
        if not stale:
            continue
        try:
            f.rename(f.with_name(f.name[:-len(CLAIMED)] + ".json"))
            n += 1
        except OSError:
            pass  # another drainer took it back first
    return n


def release_claims():
    """Queue this process's own claims again (it is about to exec or exit mid-ask); their count."""
    with _MINE_LOCK:
        mine = list(_MINE)
        _MINE.clear()
    n = 0
    for f in mine:
        try:
            f.rename(f.with_name(f.name[:-len(CLAIMED)] + ".json"))
            n += 1
        except OSError:
            pass
    return n


def _clear_waits(d, key):
    for w in d.glob(f"{key}.wait.*"):
        w.unlink(missing_ok=True)


def _by_read(files):
    """`files` (oldest first) regrouped by the asking process, the read nearest done first
    (fewest asks left, then oldest), all its asks together: reads complete one at a time,
    not all at once."""
    groups = {}
    for f in files:
        try:
            pid = json.loads(f.read_text()).get("pid")
        except (OSError, ValueError, AttributeError):
            pid = None
        groups.setdefault(pid if pid is not None else f.name, []).append(f)
    return [f for g in sorted(groups.values(), key=len) for f in g]  # stable: oldest first among equals


def drain_one():
    """Ask the server the oldest queued spooled ask and cache its answer; its key, or None
    when none is queued or the ask failed (it stays queued). Threads may call it together:
    a claim is an atomic rename."""
    d = spool_dir()
    if not any(d.glob("*.json")):
        MISS[0] = "nothing queued (every spooled ask is claimed)"
        return None
    # The slot first, the claim second: a claimed ask is always being asked, never waiting
    # (a .json.work that waited was lost with a dead drainer and hid from the others).
    with slot(priority=True):
        try:
            queued = _by_read(sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime))
        except OSError:
            return None
        for f in queued:
            claim = f.with_name(f.name[:-len(".json")] + CLAIMED)
            try:
                f.rename(claim)
            except OSError:
                continue  # another thread has it
            with _MINE_LOCK:
                _MINE.add(claim)
            try:
                got = _drain_claimed(d, f, claim)
            finally:
                with _MINE_LOCK:
                    _MINE.discard(claim)
            if got is _NEXT:
                continue
            return got
        MISS[0] = "every queued ask was answered already or torn"
    return None


#: Why the last drain_one sent nothing (edition_queue's drainer logs it when it stalls).
MISS = [""]
_NEXT = object()


def _drain_claimed(d, f, claim):
    """drain_one's ask of the entry `f` it has claimed (renamed to `claim`): its key, None when the
    ask failed (queued again, at the back), or _NEXT when there was nothing to ask (dropped)."""
    key = f.name[:-len(".json")]
    png = d / f"{key}.png"
    if (CACHE / f"{key}.txt").exists() or not png.exists():
        # Answered already (a read spooled it again while it was asked), or its png is gone:
        # nothing to ask, and it must not block the entries behind it.
        if not (CACHE / f"{key}.txt").exists():
            sys.stderr.write(f"vlm_reader: dropped spooled ask {key[:8]}: no png\n")
        claim.unlink(missing_ok=True)
        png.unlink(missing_ok=True)
        _clear_waits(d, key)
        return _NEXT
    try:
        got = json.loads(claim.read_text())
        data = png.read_bytes()
        if not isinstance(got, dict) or "prompt" not in got or "max_tokens" not in got or not data:
            raise ValueError("empty or truncated entry")
    except ValueError as e:
        # A torn entry (10-24: a container stop left 0-byte .json and .png, their writes never
        # synced): it can never be asked. Requeued, it came back first every time (no pid: a read
        # of its own, the fewest asks) and each drain_one returned None, so the drainer asked
        # one ask in ~3 min. Dropped like an orphan; its read spools it again.
        sys.stderr.write(f"vlm_reader: dropped spooled ask {key[:8]}: {e}\n")
        claim.unlink(missing_ok=True)
        png.unlink(missing_ok=True)
        _clear_waits(d, key)
        return _NEXT
    except OSError:
        got = None
    if got is not None:
        # The claimer's pid in the claim: requeue_claimed takes back only a claim no live process asks.
        try:
            tmp = claim.with_name(f"{key}.claim.{os.getpid()}.{threading.get_ident()}")
            tmp.write_text(json.dumps({**got, "claimed_by": os.getpid(), "claimed_at": time.time()}))
            st = claim.stat()
            if claim.exists():
                tmp.replace(claim)
                os.utime(claim, (st.st_atime, st.st_mtime))  # its place in the queue (spooled: by mtime) kept
            else:
                tmp.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        if got is None:
            raise OSError("entry unreadable")
        ask_png(data, got["prompt"], got["max_tokens"], spool=False, held=True)
        _log_ask(key, got)
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        MISS[0] = f"the ask failed: {cause() or type(e).__name__} ({str(e)[:120]})"
        try:
            claim.rename(f)
            os.utime(f)  # to the back of the queue: one bad entry does not block the rest
        except OSError:
            pass
        return None
    except BaseException:
        try:
            claim.rename(f)  # anything else (a bug): queued again, never left claimed
        except OSError:
            pass
        raise
    claim.unlink(missing_ok=True)
    png.unlink(missing_ok=True)
    _clear_waits(d, key)
    MISS[0] = ""
    return key


def ask_png(data, prompt, max_tokens=1500, spool=None, held=False):
    """ask() of the image whose png() is `data`. `spool` (default: env SPOOL_ENV set, not "0"):
    an ask not cached is queued for drain_one and Spooled raised, not asked. `held`: the caller
    holds a slot() already (drain_one)."""
    key = ask_key(data, prompt)
    path = CACHE / f"{key}.txt"
    if path.exists():
        _SPENT["cached"] += 1
        if dryrun():
            CACHED_KINDS[_kind(prompt)] = CACHED_KINDS.get(_kind(prompt), 0) + 1
        return path.read_text()
    if dryrun():
        if not any(a["key"] == key[:12] for a in DRYRUN_ASKS):
            DRYRUN_ASKS.append({"kind": _kind(prompt), "size": list(dryrun_size(data)), "key": key[:12]})
        return ""
    why = busy()
    if why:
        _YIELDED[0] = time.monotonic()
        _MISSED[0] = True
        _CAUSE[0] = f"yield: desktop busy ({why})"
        raise RuntimeError(f"VLM {MODEL} at {URL} yields: desktop busy ({why})")
    if spool is None:
        spool = os.environ.get(SPOOL_ENV, "0") not in ("", "0")
    if spool:
        if not pending(key) and len(spooled()) >= vlm_spool_max():
            # The spool is at its cap: spool nothing; the read ends deferred, and the queue starts it
            # again once the spool is below the cap (it finds the mark).
            try:
                spool_dir().mkdir(parents=True, exist_ok=True)
                full_mark(os.getpid()).touch()
            except OSError:
                pass
            _MISSED[0] = True
            _CAUSE[0] = "spool full"
            _UNANSWERED[0] += 1
            raise Spooled(f"VLM ask {key[:8]} not spooled: VLM spool full")
        put_spool(key, data, prompt, max_tokens)
        if path.exists():  # answered meanwhile
            return path.read_text()
        if not _BATCH.get() and wait_answered([key]):  # a shallow spool: the drainer answers it in seconds
            return path.read_text()
        _MISSED[0] = True
        _CAUSE[0] = "spooled"
        _UNANSWERED[0] += 1
        raise Spooled(f"VLM ask {key[:8]} spooled for the drainer", [key])
    body = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}},
                {"type": "text", "text": prompt}]}]}
    def request():
        return urllib.request.Request(f"{URL}/v1/chat/completions", data=json.dumps(body).encode(),
                                      headers={"Content-Type": "application/json", "User-Agent": "cryptic-teacher"})
    moved = False
    blips = _blip_waits()
    while True:
        req = request()
        try:
            for tried in range(QUEUE_FULL_TRIES):
                try:
                    with asking(), (contextlib.nullcontext() if held else slot()):
                        reply = json.load(urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT * (1 + max(0, PIPELINE))))
                    break
                except urllib.error.HTTPError as e:
                    _CAUSE[0] = cause_of(e)
                    # 429: llama-swap's queue is full (many reads ask at once). The
                    # server is up and busy, not down: wait for room and ask again.
                    if e.code not in RETRY_CODES or tried == QUEUE_FULL_TRIES - 1:
                        raise
                    time.sleep(min(QUEUE_FULL_WAIT * (tried + 1), 60) * (0.5 + random.random()))
            break
        except OSError as e:
            if not moved and not isinstance(e, urllib.error.HTTPError) and cause_of(e) in ("timeout", "refused", "URLError", "OSError", "gaierror") \
                    and _moved_to_other():
                moved = True  # the address found at startup went stale (DHCP lease flap): once more, there
                continue
            pause = None if isinstance(e, urllib.error.HTTPError) else next(blips, None)
            if pause is not None and cause_of(e) in ("refused", "URLError", "OSError", "gaierror"):
                time.sleep(pause)  # a link blip (BLIP_SECONDS): ask again before calling it down
                continue
            # Down mid-run (the desktop rebooted): the rest of the run reads without it.
            _UP[MODEL] = False
            _MISSED[0] = True
            _CAUSE[0] = cause_of(e)
            raise RuntimeError(f"VLM {MODEL} at {URL} failed ({_CAUSE[0]}): {e}") from e
    text = reply["choices"][0]["message"]["content"] or ""
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(text)
    tmp.replace(path)
    _SPENT[_kind(prompt)] += 1
    return text


def boxes(img, wins, readings):
    """One page box per clue column: the span of every reading's lines in
    that column (`readings`: each reader's columns() output), padded. None
    for a column no reading has lines in. `wins` (windows()) gives the
    column count."""
    out = []
    for i in range(len(wins)):
        got = [line for cols in readings if i < len(cols) for line in cols[i]]
        if not got:
            out.append(None)
            continue
        box = (max(0, min(l[2] for l in got) - PAD), max(0, min(l[0] for l in got) - PAD),
               min(img.width, max(l[3] for l in got) + PAD), min(img.height, max(l[1] for l in got) + PAD))
        if too_small(box):
            print(f"vlm_reader: no ask for a {box[2] - box[0]}x{box[3] - box[1]} px crop (column {i}): "
                  f"too small to hold a clue column", file=sys.stderr)
            SKIPPED_SMALL.append(box)
            out.append(None)
            continue
        out.append(box)
    return out


#: A crop (page pixels) narrower or shorter than this holds no clue column: the
#: real ones are 320+ wide and 70+ tall (the 1945 Times' strip over the grid
#: ends its down clues in two columns of two lines, 327x70 and 375x73: cut at
#: 80 they left 21d, 24d and 25d out of every pick's crop, asked and answered
#: NONE on 162 reads); the junk a stray line makes is ~35 px (FT 1987-02-07: 33x36).
MIN_BOX = (120, 55)
#: Boxes boxes() refused, this process.
SKIPPED_SMALL = []


def too_small(box):
    return box[2] - box[0] < MIN_BOX[0] or box[3] - box[1] < MIN_BOX[1]


def crop(img, box):
    c = img.crop(box).convert("RGB")
    return c.resize((c.width * UPSCALE, c.height * UPSCALE))


def column_text(img, wins, readings):
    """The model's transcription of every clue column, top to bottom and
    left to right, one printed line a line."""
    parts = read_all([crop(img, box) for box in boxes(img, wins, readings) if box])
    return "\n".join(p for p in parts if p)


def read_all(images):
    """read() of each image. A Spooled ask does not stop the rest: every column not
    cached is spooled in one pass (the drainer asks them in turn), then, unless settled() gets
    their answers in (a shallow spool), Spooled is raised."""
    snap, out, errs, images = flags(), [], [], list(images)
    with batched():
        for i, im in enumerate(images):
            try:
                out.append(read(im))
            except Spooled as e:
                errs.append(e)
                out.append(i)
    if errs:
        if not settled(snap, errs):
            raise joined(errs)
        out = [read(images[o]) if isinstance(o, int) else o for o in out]
    return out


#: A column box (page pixels) read again for another crop window of the same page, within
#: this overlap (intersection over union) of one already read, is not asked again: the window
#: loop re-cuts the same print a few pixels apart (FT 1980-10-25: the first column 746x2002,
#: 754x2018 and 746x2004 in three windows, the second 744x1166 and 750x1170, each a separate
#: ask of ~10 s for the same words). 0.95 is a margin of ~15 px on a 800 px column.
NEAR_BOX = 0.95
#: scope -> [(box, reading)] of the columns this process has read for a page; the newest
#: NEAR_SCOPES scopes are kept.
_NEAR = {}
NEAR_SCOPES = 8


def overlap(a, b):
    """Intersection over union of two boxes (x0, y0, x1, y1)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def read_columns(scope, img, boxes):
    """read_all of each box's crop, except a box that nearly is one this process has read under
    `scope` (a page's name) takes that reading. A Spooled ask does not stop the rest, and a
    shallow spool's answers are waited for (settled)."""
    seen = _NEAR.setdefault(scope, [])
    while len(_NEAR) > NEAR_SCOPES:
        _NEAR.pop(next(iter(_NEAR)))
    snap, errs, boxes = flags(), [], list(boxes)

    def column(box):
        near = next((t for b, t in seen if overlap(b, box) >= NEAR_BOX), None)
        if near is not None:
            return near
        text = read(crop(img, box))
        if text.strip():
            seen.append((tuple(box), text))
        return text

    out, left = [], set()
    with batched():
        for i, box in enumerate(boxes):
            try:
                out.append(column(box))
            except Spooled as e:
                errs.append(e)
                left.add(i)
                out.append(None)
    if errs:
        if not settled(snap, errs):
            raise joined(errs)
        out = [column(box) if i in left else t for i, (box, t) in enumerate(zip(boxes, out))]  # from the cache
    return out


def read(image):
    """The model's transcription of one clue column already cropped (and
    enlarged) on its own: a page's column, or a Trove article's text zone.
    The model runs a clue's printed lines together, keeping the hyphen of a
    word broken over a line end: unhyphen() joins it."""
    return unhyphen(ask(image, PROMPT.read_text()).strip())


def pick(img, wins, readings, lid, candidates):
    """The model's text for one clue (light "N-across"), shown the clue
    columns and the readers' differing readings; None when it finds none."""
    cols = [b for b in boxes(img, wins, readings) if b]
    if not cols:
        return None
    box = (min(b[0] for b in cols), min(b[1] for b in cols), max(b[2] for b in cols), max(b[3] for b in cols))
    return pick_in(crop(img, box), lid, candidates)


def pick_in(image, lid, candidates):
    """pick() shown an image of the clue columns already cropped."""
    number, direction = lid.split("-")
    listed = "\n".join(f"{i}. {c}" for i, c in enumerate(dict.fromkeys(candidates), 1)) or "(none)"
    prompt = PICK_PROMPT.read_text().format(number=number, direction=direction,
                                            heading=direction.upper(), candidates=listed)
    text = ask(image, prompt, max_tokens=200).strip().strip('"').strip()
    if not text or text.upper().startswith("NONE"):
        return None
    return unhyphen(text.splitlines()[0].strip())
