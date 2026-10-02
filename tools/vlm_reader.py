"""A vision-language model as one more reader of scanned clue columns.

Any OCR pipeline can use it as a voter: column_text() transcribes each clue
column of a page image (its boxes taken from the other readers' lines), and
pick() reads one clue the readers disagree on, shown their readings. The
model is Qwen3-VL-8B behind llama-swap on Paul's desktop 3090
(VLM_READER_URL / VLM_READER_MODEL; an empty URL turns it off). When the
server does not answer (desktop off, model missing) reachable() is False and
a caller reads exactly as without it; version() names what its readings
depend on, for a caller's input hash.

Prompts: vlm_column_prompt.md and vlm_pick_prompt.md. Replies are cached by
a hash of the model, prompt and image under ~/.cache/vlm_reader, so a re-run
asks nothing new.
"""
import base64
import hashlib
import io
import json
import os
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
URL = os.environ.get("VLM_READER_URL", "http://100.68.145.15:8090")
MODEL = os.environ.get("VLM_READER_MODEL", "qwen3.0-vl-8b")
PROMPT = TOOLS / "vlm_column_prompt.md"
PICK_PROMPT = TOOLS / "vlm_pick_prompt.md"
CACHE = Path(os.path.expanduser("~/.cache/vlm_reader"))
#: The scans print ~17px a line; the model reads them better twice the size.
UPSCALE = 2
#: Padding round a column's text, in page pixels.
PAD = 10

_UP = {}


def reachable():
    """Whether the server answers and lists MODEL; asked once a process."""
    if not URL:
        return False
    if MODEL not in _UP:
        try:
            req = urllib.request.Request(f"{URL}/v1/models", headers={"User-Agent": "cryptic-teacher"})
            ids = {m.get("id") for m in json.load(urllib.request.urlopen(req, timeout=3)).get("data", [])}
            _UP[MODEL] = MODEL in ids
        except (OSError, ValueError):
            _UP[MODEL] = False
    return _UP[MODEL]


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


def ask(img, prompt, max_tokens=1500):
    """The model's reply to `prompt` about a PIL image, cached."""
    data = png(img)
    key = hashlib.sha1(MODEL.encode() + b"\0" + prompt.encode() + b"\0" + data).hexdigest()
    path = CACHE / f"{key}.txt"
    if path.exists():
        return path.read_text()
    body = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}},
                {"type": "text", "text": prompt}]}]}
    req = urllib.request.Request(f"{URL}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "cryptic-teacher"})
    try:
        reply = json.load(urllib.request.urlopen(req, timeout=600))
    except OSError as e:
        # Down mid-run (the desktop rebooted): the rest of the run reads without it.
        _UP[MODEL] = False
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
    enlarged) on its own: a page's column, or a Trove article's text zone."""
    return ask(image, PROMPT.read_text()).strip()


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
    return text.splitlines()[0].strip()
