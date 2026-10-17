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
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import desktop_busy
import desktop_hosts
from ocr_clues import unhyphen

TOOLS = Path(__file__).resolve().parent
#: The desktop's VLM addresses, LAN first (tools/desktop_hosts.json); URL is
#: the one in use: VLM_READER_URL if set (it alone, no fallback), else the
#: first of URLS that answers (resolve()), the LAN one until then.
URLS = list(desktop_hosts.VLM_URLS)
URL = os.environ.get("VLM_READER_URL", URLS[0])
#: Seconds every URL has to answer, all asked at once (resolve): the tailnet
#: path goes quiet for seconds in bursts.
CONNECT_TIMEOUT = 3
_RESOLVED = [False]
MODEL = os.environ.get("VLM_READER_MODEL", "qwen3.8-vl-27b")
PROMPT = TOOLS / "vlm_column_prompt.md"
PICK_PROMPT = TOOLS / "vlm_pick_prompt.md"
CACHE = Path(os.path.expanduser("~/.cache/vlm_reader"))
#: The scans print ~17px a line; the model reads them better twice the size.
UPSCALE = 2
#: Padding round a column's text, in page pixels.
PAD = 10

_UP = {}
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


class Down(RuntimeError):
    """A read that needs the model met it down, under DEFER_ENV: the read
    ends deferred (edition_commit.EXITS["vlm"]), writing nothing."""


def wanted():
    """reachable(), asked by a reader about to use the model. When it is not
    (and a URL is set: an empty one turns the model off, and the read goes
    on without it) the miss is noted, and under DEFER_ENV it raises Down."""
    if reachable():
        return True
    if URL:
        _MISSED[0] = True
        if os.environ.get(DEFER_ENV):
            raise Down(f"VLM {MODEL} at {URL} is down")
    return False


def missed():
    """Whether this process wanted the model and went without it (_MISSED)."""
    return _MISSED[0]


def guard(what):
    """Raise Down, under DEFER_ENV, when this process went without the model
    it wanted (missed): `what` (a puzzle write, a ledger row) would record a
    read made without it."""
    if _MISSED[0] and os.environ.get(DEFER_ENV):
        raise Down(f"VLM {MODEL} at {URL} went down mid-read; {what} not written")


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
    URLS (an override), else the first of URLS (URL's first, then LAN before
    tailnet) that answers, every one asked at once, which URL is then set to
    and kept until it stops answering (reachable then resolves again). A LAN
    address gone stale (DHCP) costs one short timeout in parallel with the
    rest, never the VLM, and never one timeout per address in turn. When none
    answers URL stays and the next call asks again."""
    global URL
    if _RESOLVED[0] or not URL:
        return URL
    if URL in URLS:
        found = _first_answering([URL] + sorted((u for u in _candidates() if u != URL), key=_on_tailnet))
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
    if list(URLS) != list(desktop_hosts.VLM_URLS):
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


def _models():
    """The model ids URL lists, or None when it does not answer."""
    try:
        req = urllib.request.Request(f"{URL}/v1/models", headers={"User-Agent": "cryptic-teacher"})
        return {m.get("id") for m in json.load(urllib.request.urlopen(req, timeout=3)).get("data", [])}
    except (OSError, ValueError):
        return None


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


def ask(img, prompt, max_tokens=1500):
    """The model's reply to `prompt` about a PIL image, cached."""
    return ask_png(png(img), prompt, max_tokens)


def ask_png(data, prompt, max_tokens=1500):
    """ask() of the image whose png() is `data`."""
    key = hashlib.sha1(MODEL.encode() + b"\0" + prompt.encode() + b"\0" + data).hexdigest()
    path = CACHE / f"{key}.txt"
    if path.exists():
        return path.read_text()
    why = busy()
    if why:
        _YIELDED[0] = time.monotonic()
        _MISSED[0] = True
        raise RuntimeError(f"VLM {MODEL} at {URL} yields: desktop busy ({why})")
    body = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}},
                {"type": "text", "text": prompt}]}]}
    req = urllib.request.Request(f"{URL}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "cryptic-teacher"})
    try:
        for tried in range(QUEUE_FULL_TRIES):
            try:
                reply = json.load(urllib.request.urlopen(req, timeout=600))
                break
            except urllib.error.HTTPError as e:
                # 429: llama-swap's queue is full (many reads ask at once). The
                # server is up and busy, not down: wait for room and ask again.
                if e.code not in RETRY_CODES or tried == QUEUE_FULL_TRIES - 1:
                    raise
                time.sleep(min(QUEUE_FULL_WAIT * (tried + 1), 60) * (0.5 + random.random()))
    except OSError as e:
        # Down mid-run (the desktop rebooted): the rest of the run reads without it.
        _UP[MODEL] = False
        _MISSED[0] = True
        raise RuntimeError(f"VLM {MODEL} at {URL} failed: {e}") from e
    text = reply["choices"][0]["message"]["content"] or ""
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(text)
    tmp.replace(path)
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
        out.append((max(0, min(l[2] for l in got) - PAD), max(0, min(l[0] for l in got) - PAD),
                    min(img.width, max(l[3] for l in got) + PAD), min(img.height, max(l[1] for l in got) + PAD)))
    return out


def crop(img, box):
    c = img.crop(box).convert("RGB")
    return c.resize((c.width * UPSCALE, c.height * UPSCALE))


def column_text(img, wins, readings):
    """The model's transcription of every clue column, top to bottom and
    left to right, one printed line a line."""
    parts = [read(crop(img, box)) for box in boxes(img, wins, readings) if box]
    return "\n".join(p for p in parts if p)


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
