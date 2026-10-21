#!/usr/bin/env python3
"""Every London Times edition of 1930-2014 (YEARS, the run Gale's Times
Digital Archive holds) with no puzzle filed (wanted), in next_up's order
(ORDER): Times No 1, then the 1974-99 editions archive.org has no scan of,
then 2014, then 2000-13, then the rest of 1930-99, each newest first; and
the other papers' Gale archives' unfiled dates (OTHERS, other_wanted).

tools/gale_fetch.py downloads them itself (Paul 2026-10-11) and lays each
out as its date's edition (lay_out_fetched), CACHE/Gale<Paper><year>UKEnglish/
<date>, its leaves scaled to an archive.org scan's grid size (scaled), for
tools/file_archive_org_puzzles.py, which reads it like any scan. An edition
laid out in the last FRESH seconds is read within minutes by the full pass
(tools/ocr_full_pass.sh), whose queue starts it ahead of everything planned
(edition_queue.fresh); when no pass runs, sync starts one for it (kick).
This module also renders the Times progress page (checklist: nothing to
click) and publishes it to the Mac (publish).

    python3 tools/gale_inbox.py sync [--render]   # publish the progress page, kick the pass
    python3 tools/gale_inbox.py checklist [--out FILE]
    python3 tools/gale_inbox.py shrink            # lay out smaller every staged leaf over MAX_PAGE_PIXELS

Every minute (the cryptic-gale-inbox plugin) a sync re-renders the progress
page when tools/gale_fetch.py logged a download, or RENDER_EVERY.
"""
import argparse
import collections
import contextlib
import copy
import datetime
import hashlib
import html
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
import archive_coverage
import file_archive_org_puzzles as fa
import gale_docs
import gale_fetch
import local_config
import media_manifest
import pypdf
import trove_grid

TOOLS = Path(__file__).resolve().parent

HOST = os.environ.get("GALE_INBOX_HOST") or local_config.get("mac_host")
#: The media host's folder the Gale pages and the progress page live in, on the
#: media disk (the local config's media_root).
GALE_ROOT = local_config.path("media_root") + "/Gale crosswords"
CHECKLIST_NAME = "Checklist.html"


SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "HostKeyAlias=localhost",
       *(["-i", local_config.path("mac_ssh_key")] if local_config.get("mac_ssh_key") else [])]
#: This module's and tools/gale_fetch.py's state.
HOME = Path(os.path.expanduser("~/.cache/gale_inbox"))
CHECKLIST = HOME / CHECKLIST_NAME


LOCK = HOME / "sync.lock"
#: A tick re-renders the progress page when tools/gale_fetch.py logged a
#: download, else this often, so a puzzle the full pass filed leaves it.
RENDER_EVERY = 3600
#: An edition laid out this recently and unread is one the full pass's queue
#: reads first (edition_queue.fresh); a tick that finds one while no pass
#: runs starts the pass (kick) with TICK, from its own worktree.
FRESH = fa.FRESH
TICK = TOOLS / "corpus_queue.sh"
TICK_LOG = Path(os.path.expanduser("~/.cache/corpus_queue/kick.log"))
CACHE = fa.CACHE
ITEM = "GaleTimes{}UKEnglish"
#: Any Gale paper's item: the Times' ITEM or an OTHERS paper's.
GALE_ITEM = re.compile(r"Gale[A-Za-z]+\d{4}UKEnglish")
#: The SSD manifest of the editions laid out under CACHE (lay_out_fetched):
#: what a tick reads instead of the media disk.
EDITIONS = media_manifest.GALE_EDITIONS
#: An edition dir's name under ITEM.
ISO_DAY = re.compile(r"\d{4}-\d\d-\d\d")
PAGES = (".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".gif", ".webp")
#: The years Gale's Times Digital Archive holds that the checklist asks for; it ends with 2014.
YEARS = range(1930, 2015)
#: The classes of a 1974-99 edition the checklist asked for before it took
#: every unfiled date (no archive.org scan): next_up keeps them first.
WANTED = ("no-scan", "canberra-reprint")
#: wanted()'s class for an unfiled date archive.org holds a scan of.
SCAN_UNFILED = "scan-unfiled"
#: An archive.org Times grid is ~680-770 px wide; a Gale page is scaled so
#: its grid is this wide, the size the filer's pixel spans were set on.
GRID_WIDTH = 720

#: A Gale article opens from its document id.
DOC_URL = "https://go.gale.com/ps/retrieve.do?docId=GALE%7C{}&prodId=TTDA&userGroupName=alberta_portal"
DOC_ID = re.compile(r"GALE[\W_]{0,3}([A-Z]{2}\d{8,12})", re.IGNORECASE)
#: Text only a Gale download's citation page prints.
GALE_TEXT = re.compile(r"Gale Document Number|link\.gale\.com|Gale Primary Sources|Gale, a Cengage"
                       r"|Times Digital Archive|Listener Historical Archive", re.IGNORECASE)

MONTHS = {m: i for i, ms in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1) for m in [ms]}
MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"


def date_patterns(year):
    """[(pattern, order)] of the ways a file name spells a date whose year
    matches the regex `year`: 1988-01-12, 12 Jan 1988, Jan 12 1988."""
    return [(re.compile(r"(?<!\d)(" + year + r")[-_. ]?(0[1-9]|1[0-2])[-_. ]?(0[1-9]|[12]\d|3[01])(?!\d)"), "ymd"),
            (re.compile(r"(?<!\d)([0-3]?\d)(?:st|nd|rd|th)?[-_. ,]*" + MON + r"[-_. ,]*(" + year + r")(?!\d)",
                        re.IGNORECASE), "dmy"),
            (re.compile(MON + r"[-_. ]*([0-3]?\d)(?:st|nd|rd|th)?[-_. ,]*(" + year + r")(?!\d)", re.IGNORECASE), "mdy")]


#: A year in YEARS, as a file name or a citation spells it.
YEAR = r"19[3-9]\d|20[01]\d"
DATES = date_patterns(YEAR)
#: A Times cryptic number in a file name: 10,000-29,999 bare (1962-2019;
#: Times issue numbers, 45,000-73,000 over YEARS, and Gale document ids never
#: fall in it), or any after "No" (No 5,432 of 1951; a bare 4-digit number
#: could be a year).
NUMBER = re.compile(r"(?:(?<![a-z])n[o0]\.?[._ ]{0,2}(?:(\d{1,2})[,.]?(\d{3})|(\d{1,3}))"
                    r"|(?<![\d,.])(1\d|2\d)[,.]?(\d{3}))(?![\d,])", re.IGNORECASE)
#: The citation a Gale PDF prints: "The Times, 12 Jan. 1988, p. 18", or
#: its download's citation page, the article's title quoted first:
#: '"The Times Crossword Puzzle No 17,244." Times, 3 Jan. 1987, p. 20.'
CITED = re.compile(r'(?:"[^"]{0,200}"\s*(?:The\s+)?Times|The Times[^,]{0,40}),\s*(?:\w+,\s*)?([0-3]?\d)\s+' + MON
                   + r"\s*(" + YEAR + r")(?:,\s*p\.?\s*(\d+))?", re.IGNORECASE)


# ------------------------------------------------------------ numbers and dates

#: [True, held()?] while a sync tick runs: the tick files no puzzle, so its
#: reads of the series' directory give one answer, read on first ask (a tick
#: that renders nothing reads none). Empty outside a sync.
_TICK_HELD = []
#: Where a sync keeps held_files' parse of the filed Times puzzles between
#: ticks (one process a minute): each file is parsed again only when its stat
#: moves, not all ~13k every tick.
HELD_CACHE = HOME / "held_times.pickle"


def held():
    """{number: date} of every filed Times puzzle (read once a sync tick)."""
    if len(_TICK_HELD) > 1:
        return _TICK_HELD[1]
    if not _TICK_HELD:
        return fa.held_dates(fa.TIMES.series)
    got = _times_held()
    _TICK_HELD.append(got)
    return got


def _times_held(path=None):
    """fa.held_dates of the Times, its files' parses carried in HELD_CACHE."""
    import pickle
    path = HELD_CACHE if path is None else path
    try:
        with open(path, "rb") as f:
            snap = pickle.load(f)
        for k, v in snap.items():
            fa._HELD.setdefault(k, v)
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ValueError, TypeError):
        pass
    fa._HELD_MOVED.clear()
    got = fa.held_dates(fa.TIMES.series)
    if fa._HELD_MOVED:
        fa._HELD_MOVED.clear()
        top = str(fa.ROOT / "puzzles" / fa.TIMES.series) + os.sep
        keep = {str(k): v for k, v in fa._HELD.items() if str(k).startswith(top)}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            with open(tmp, "wb") as f:
                pickle.dump(keep, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
        except OSError:
            pass
    return got


#: Where ledger_summary keeps its fold of each ledger between ticks.
LEDGER_CACHE = HOME / "ledger_summary.pickle"


def ledger_summary(ledgers=None, path=None):
    """{edition: {"filesHash": ..., "inputs": True when its row has inputs}}
    of archive_coverage's ledgers, the last row of each standing: what a
    tick asks of them (whether an edition was read, and with which files),
    without parsing their ~16 MB each minute. Each ledger is folded only
    past where the last tick stopped (kept in LEDGER_CACHE), and whole again
    when it was rewritten (another inode, shorter, or its tail moved)."""
    import pickle
    ledgers = archive_coverage.LEDGERS if ledgers is None else ledgers
    path = LEDGER_CACHE if path is None else path
    try:
        with open(path, "rb") as f:
            kept = pickle.load(f)
        if not isinstance(kept, dict):
            kept = {}
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ValueError, TypeError):
        kept = {}
    out, moved = {}, False
    for ledger in ledgers:
        k = os.fspath(ledger)
        try:
            fh = open(ledger, "rb")
        except FileNotFoundError:
            moved |= kept.pop(k, None) is not None
            continue
        with fh:
            st = os.fstat(fh.fileno())
            ino, done, tail, acc = kept.get(k, (None, 0, b"", None))
            if (acc is None or ino != st.st_ino or st.st_size < done
                    or os.pread(fh.fileno(), len(tail), done - len(tail)) != tail):
                done, tail, acc = 0, b"", {}
            fh.seek(done)
            data = fh.read()
        end = data.rfind(b"\n") + 1
        for line in data[:end].split(b"\n"):
            if line.strip():
                row = json.loads(line)
                acc[row["edition"]] = {"filesHash": row.get("filesHash"), **({"inputs": True} if "inputs" in row else {})}
        if end:
            done += end
            tail = (tail + data[:end])[-64:]
            moved = True
        kept[k] = (st.st_ino, done, tail, acc)
        out.update(acc)
    if moved:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            with open(tmp, "wb") as f:
                pickle.dump(kept, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
        except OSError:
            pass
    return out


#: Every date the Times printed in YEARS (archive_coverage.PRINTED: no
#: Sundays, no Christmas Day, none in the 1978-79 shutdown), and each one's
#: place in that run.
PRINTED = [datetime.date.fromisoformat(d)
           for d in archive_coverage.printed_dates("times", datetime.date(YEARS[-1] + 1, 1, 31))]
ISSUE = {d: i for i, d in enumerate(PRINTED)}


def name_date(name, patterns=DATES):
    """The date a file name spells, or None."""
    for rx, order in patterns:
        m = rx.search(name)
        if m:
            parts = dict(zip(order, m.groups()))
            month = parts["m"]
            month = MONTHS[month[:3].lower()] if not month.isdigit() else int(month)
            try:
                return datetime.date(int(parts["y"]), month, int(parts["d"]))
            except ValueError:
                continue
    return None


# ------------------------------------------------------------ pages

def images(path):
    """[(PIL image, citation text)] of a saved page: an image file is one;
    a PDF gives the largest image on each of its pages and the text of all."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    if path.suffix.lower() != ".pdf":
        return [(Image.open(path).convert("RGB"), "")]
    reader = pypdf.PdfReader(str(path))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    out = []
    for p in reader.pages:
        imgs = [i.image for i in p.images]
        if imgs:
            out.append((max(imgs, key=lambda i: i.width * i.height).convert("RGB"), text))
    return out


def square(box):
    """A grid's shape at any scale: the page's own size is not known."""
    w, h = box[2] - box[0], box[3] - box[1]
    return w >= 200 and 0.85 <= w / max(h, 1) <= 1.18


#: The white margin a page is set in, so a title at the crop's edge has a
#: band over it like any page's.
MARGIN = 120


def page_grids(img):
    """[box] of the grids scaled() sizes a page by: the grid-shaped ink at
    an archive.org page's width, else every square patch of ink. When the
    widest is no lattice of white cells (trove_grid.lattice) and another
    candidate is, the widest that is: a compact-era (2004-) Times page
    prints its grid ~37% of the page wide, too wide for grid_shaped() at
    SCAN_WIDTH, so the square patches were all there was, and a photo
    beside the grid is wider (Times 24,662, 24,743, 24,744)."""
    at = fa.SCAN_WIDTH / img.width
    shaped = [[v / at for v in b] for b in fa.grids_on(img.resize((fa.SCAN_WIDTH, round(img.height * at))))]
    squares = None  # the full-size search, the costliest step: made only when asked of

    def all_squares():
        nonlocal squares
        if squares is None:
            squares = fa.grids_on(img, shaped=square)
        return squares
    grids = shaped or all_squares()
    if not grids:
        return grids

    def width(b):
        return b[2] - b[0]

    def is_lattice(b):
        return trove_grid.lattice(img.crop((max(0, b[0] - 6), max(0, b[1] - 6), b[2] + 6, b[3] + 6)))
    widest = max(grids, key=width)
    if is_lattice(widest):
        return grids
    rest = sorted((b for b in shaped + [list(b) for b in all_squares()] if list(b) != list(widest)), key=width,
                  reverse=True)
    return next(([b] for b in rest if is_lattice(b)), grids)


def scaled(img):
    """(`img` as an archive.org page holds a puzzle, whether a grid was found
    on it): scaled so its widest grid is GRID_WIDTH wide (unscaled when none
    is found) and set on a white page SCAN_WIDTH wide, the size the filer's
    pixel spans are set at. A whole page (Gale's page download) is read at
    an archive.org page's width first, where a photo or a table is too big
    to pass for its grid; a clipping, its widest square patch of ink; a
    widest box that is no lattice gives way to one that is (page_grids)."""
    from PIL import Image
    grids = page_grids(img)
    k = GRID_WIDTH / max(b[2] - b[0] for b in grids) if grids else 1
    limit = capped_scale(img.width, img.height)
    if k > limit or abs(k - 1) >= 0.05:  # a page past the cap is always shrunk to it
        k, size = min(k, limit), (round if k < limit else int)  # at the cap, rounded down
        img = img.resize((size(img.width * k), size(img.height * k)), Image.LANCZOS)
    page = Image.new("RGB", (max(fa.SCAN_WIDTH, img.width + 2 * MARGIN), img.height + 2 * MARGIN), "white")
    page.paste(img, (MARGIN, MARGIN))
    return page, bool(grids)


#: The most pixels a laid-out page (leaf) may hold. An archive.org page is
#: ~3296x4500 (15 MP); a crossword-centenary article (2013-12-04, -17) whose
#: small printed grid passed for the puzzle's was scaled up to 196 and 363
#: MP, which tesseract refuses (pixCreateHeader: requested bytes >= 2^31)
#: and whose scan unit reached 11.8 GB. A page past it is laid out smaller.
MAX_PAGE_PIXELS = 36_000_000


def capped_scale(width, height, cap=None):
    """The largest scale a width x height page may be laid out at, its
    margins in and at least fa.SCAN_WIDTH wide (scaled()), and stay within
    `cap` pixels: the root of (width k + 2 MARGIN)(height k + 2 MARGIN) =
    cap, or of SCAN_WIDTH (height k + 2 MARGIN) = cap when that is narrower."""
    cap = cap or MAX_PAGE_PIXELS
    a, b, c = width * height, 2 * MARGIN * (width + height), 4 * MARGIN * MARGIN - cap
    k = (-b + (b * b - 4 * a * c) ** 0.5) / (2 * a)
    if width * k + 2 * MARGIN < fa.SCAN_WIDTH:
        k = (cap / fa.SCAN_WIDTH - 2 * MARGIN) / height
    return max(0.0, k)


def shrink_oversized(cache=CACHE, cap=None, out=sys.stdout):
    """Lay out again, smaller, every staged leaf over `cap` pixels (laid out
    before scaled() was capped): the leaf is scaled to fit and pages.json
    holds its new size. A leaf's size is the edition's input
    (file_archive_org_puzzles.input_hash), so its scan and read come due.
    Idempotent: a leaf within `cap` is left alone. [edition dir] shrunk."""
    cap = cap or MAX_PAGE_PIXELS
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    done = []
    for pj in sorted(Path(cache).glob(ITEM.format("[0-9]" * 4) + "/*/pages.json")):
        pages = json.loads(pj.read_text())
        moved = False
        for p in pages.get("crossword_pages", ()):
            if p.get("width", 0) * p.get("height", 0) <= cap:
                continue
            path = pj.parent / f"leaf_{p['leaf']:04d}.jpg"
            img = Image.open(path)
            k = min(1.0, (cap / (img.width * img.height)) ** 0.5)
            size = (int(img.width * k), int(img.height * k))
            img.draft(img.mode, size)  # decoded at a fraction of its size, not whole
            img = img.convert("RGB").resize(size, Image.LANCZOS)
            tmp = path.with_suffix(".tmp.jpg")
            img.save(tmp, quality=92)
            tmp.replace(path)
            print(f"shrank {pj.parent.parent.name}/{pj.parent.name} leaf {p['leaf']}: "
                  f"{p['width']}x{p['height']} -> {img.width}x{img.height}", file=out)
            p.update(width=img.width, height=img.height)
            moved = True
        if moved:
            pj.write_text(json.dumps(pages, indent=1))
            done.append(pj.parent)
            note_edition(pj.parent)
    return done


# ------------------------------------------------------------ staging

#: A staged edition's "how" when tools/gale_fetch.py laid it out.
FETCHED_HOW = "fetched"


def layout_pages(data):
    """({"pages": [{"width", "height", "found": a grid was found, "bytes":
    its JPEG's length}]}, the JPEGs end to end) of a Gale page PDF `data`:
    each page as lay_out_fetched lays it out (images, scaled, JPEG quality
    92). Run on the desktop when tools/ocr_remote.py can (layout_there): the
    decode, grid search and resize are ~all of tools/gale_fetch.py's CPU."""
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        path = Path(t) / "page.pdf"
        path.write_bytes(data)
        read = images(path)
    pages, jpegs = [], []
    for img, _ in read:
        page, found = scaled(img)
        buf = io.BytesIO()
        page.save(buf, "JPEG", quality=92)
        jpegs.append(buf.getvalue())
        pages.append({"width": page.width, "height": page.height, "found": bool(found), "bytes": len(jpegs[-1])})
    return {"pages": pages}, b"".join(jpegs)


def layout_there(data):
    """layout_pages, as tools/ocr_remote.py's CALLS runs it on the desktop."""
    return layout_pages(data)


def lay_out_fetched(day, doc, data, entry, cache=CACHE, prod="TTDA"):
    """Lay out the page PDF `data` tools/gale_fetch.py downloaded for `day`
    (Gale document `doc` of product `prod`, gale_docs cache `entry`) as that
    date's edition of the Times' ITEM or the OTHERS paper's item,
    as stage does a matched file, its match taken from what the download
    already knew. Returns the edition dir. It is laid out in a hidden dir
    beside the year dirs, not in one, so a sync's stage running meanwhile
    (which clears a year dir's strays) never sees it half done; the rename
    moves it in whole."""
    import tempfile
    item = ITEM if prod == "TTDA" else OTHERS[prod].item
    url = DOC_URL.format(doc) if prod == "TTDA" else gale_docs.PERMALINK.format(doc=doc, prod=prod)
    d = cache / item.format(day.year) / day.isoformat()
    name = f"GALE_{doc}.pdf"
    import ocr_remote
    got = ocr_remote.call("gale_layout", data=data)
    laid, jpegs = got if got is not None else layout_pages(data)
    d.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".gale_fetch-", dir=cache))
    tmp = work / d.name
    tmp.mkdir()
    leaves, grid, at = [], False, 0
    for p in laid["pages"]:
        grid |= p["found"]
        leaf = len(leaves)
        (tmp / f"leaf_{leaf:04d}.jpg").write_bytes(jpegs[at:at + p["bytes"]])
        at += p["bytes"]
        leaves.append({"leaf": leaf, "width": p["width"], "height": p["height"], "file": name})
    m = {"file": name, "date": day.isoformat(), "how": FETCHED_HOW, "docId": doc,
         "cited": (entry.get("title") or "").strip().rstrip(". ") or None, "page": entry.get("page"), "grid": grid}
    (tmp / "pages.json").write_text(json.dumps({
        "item": item.format(day.year), "edition": day.isoformat(), "date": day.isoformat(), "leaves": len(leaves),
        "crossword_pages": leaves, "url": url}, indent=1))
    (tmp / f"sources-{hashlib.sha256(data).hexdigest()[:16]}.json").write_text(json.dumps([m], indent=1))
    if d.exists():
        shutil.rmtree(d)
    tmp.rename(d)
    work.rmdir()
    note_edition(d, [m])
    return d


def note_edition(d, sources=None):
    """Append edition dir `d` (its files' hash, its sources, now) to the
    EDITIONS manifest; `sources` None keeps its last row's."""
    rel = f"{d.parent.name}/{d.name}"
    if sources is None:
        sources = editions().get(rel, {}).get("sources")
    media_manifest.record(EDITIONS, d, edition=rel, files=media_manifest.edition_files(d), sources=sources)


def editions():
    """{"<item>/<date>": its last EDITIONS row}."""
    return media_manifest.latest(EDITIONS, "edition")


def build_manifest(cache=CACHE, out=sys.stdout):
    """Walk the Gale items under `cache` once and write the EDITIONS manifest
    whole: a row for each laid-out edition (one with a sources-*.json), as
    note_edition would have. Never scheduled."""
    found = []
    for item in sorted(os.listdir(cache)):
        if not GALE_ITEM.fullmatch(item):
            continue
        for day in sorted(os.listdir(cache / item)):
            d = cache / item / day
            if not ISO_DAY.fullmatch(day) or not d.is_dir():
                continue
            srcs = sorted(n for n in os.listdir(d) if n.startswith("sources-") and n.endswith(".json"))
            if srcs:
                found.append({"edition": f"{item}/{day}", "files": media_manifest.edition_files(d),
                              "sources": json.loads((d / srcs[-1]).read_text()), "at": d.stat().st_mtime})
    media_manifest.write(EDITIONS, found)
    print(f"{len(found)} Gale edition(s) written to {media_manifest.path(EDITIONS)}", file=out)
    return found


def save_json(path, value):
    """Write `value` to `path` whole or not at all (a killed tick leaves the last)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=0))
    tmp.replace(path)


def relink(pages, url):
    """Set a laid-out edition's pages.json "url" to `url` (an edition laid out
    before its document was named off its file), whole or not at all, its
    mtime kept: that is when the edition was laid out (staged_at), and an
    edition only relinked is no fresh page (edition_queue.fresh)."""
    row = json.loads(pages.read_text())
    if row.get("url") == url:
        return
    st = pages.stat()
    tmp = pages.with_name(pages.name + ".tmp")
    tmp.write_text(json.dumps({**row, "url": url}, indent=1))
    os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
    tmp.replace(pages)


# ------------------------------------------------------------ the Mac's inbox

#: An ssh to the Mac that has not answered in this long is dead: the tick
#: fails (and the next retries) rather than hold its plugin's 900 s limit.
SSH_SECONDS = 120


#: ssh exits 255 when the connection itself fails (the Mac busy past
#: ConnectTimeout, a dropped hatch); that is retried a few times before the
#: tick fails, and a remote command's own failure is not.
SSH_ATTEMPTS = 3


def ssh(command, **kw):
    for attempt in range(1, SSH_ATTEMPTS + 1):
        try:
            return subprocess.run(SSH + [HOST, command], check=True, capture_output=True,
                                  timeout=SSH_SECONDS, **kw)
        except subprocess.CalledProcessError as err:
            if err.returncode != 255 or attempt == SSH_ATTEMPTS:
                raise
            time.sleep(10 * attempt)


#: {"sha": the page as last copied to the Mac, its "Updated" stamp left out;
#: "at": when}. The Mac folder is on the spinning Media disk (Paul
#: 2026-10-14: "I don't want anything regularly scanning the spinning disk"),
#: so the page lives on the SSD (CHECKLIST) and is copied over only when it
#: says something new, at most every PUBLISH_EVERY.
PUBLISHED = HOME / "Checklist.published.json"
PUBLISH_EVERY = 3600
#: The line that changes on every render: not a change worth a disk write.
STAMP = re.compile(rb"Updated [A-Z][a-z]{2} \d{2} [A-Z][a-z]{2} \d{2}:\d{2}")


def publish(path=CHECKLIST, host_inbox=GALE_ROOT, out=sys.stdout, now=None):
    """Copy the progress page into the Mac folder under its own name,
    replaced whole (written aside, then renamed), when it changed since the
    last copy and PUBLISH_EVERY has passed. A slow or absent disk is the
    next tick's retry, never the tick's failure. Returns whether it copied."""
    now = time.time() if now is None else now
    data = path.read_bytes()
    sha = hashlib.sha1(STAMP.sub(b"", data)).hexdigest()
    try:
        last = json.loads(PUBLISHED.read_text())
    except (FileNotFoundError, ValueError):
        last = {}
    if last.get("sha") == sha or now - last.get("at", 0) < PUBLISH_EVERY:
        return False
    q = shlex.quote
    dest = q(host_inbox + '/' + path.name)
    tmp = f"{host_inbox}/.{path.name}.tmp"
    try:
        ssh(f"mkdir -p {q(host_inbox)} && cat > {q(tmp)} && mv -f {q(tmp)} {dest}", input=data)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as err:
        print(f"progress page not copied to {host_inbox} ({type(err).__name__}); the next tick retries", file=out)
        return False
    PUBLISHED.parent.mkdir(parents=True, exist_ok=True)
    PUBLISHED.write_text(json.dumps({"sha": sha, "at": now}))
    return True


# ------------------------------------------------------------ picking Gale files up

def pdf_text(data, pages=3):
    """The text of a PDF's first pages; "" when it is not one."""
    import logging
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        return "\n".join(p.extract_text() or "" for p in reader.pages[:pages])
    except (pypdf.errors.PyPdfError, ValueError, TypeError, KeyError, OSError):  # not a readable PDF: not Gale's
        return ""


def is_gale(name, text):
    """Is this a Gale download: Gale's document id in its name, or Gale's
    citation in its text?"""
    return bool(DOC_ID.search(name) or GALE_TEXT.search(text))


def load(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


# ------------------------------------------------------------ the checklist

def usual_pages():
    """{year: (low, high, most)} of the page (archive.org leaf + 1) the Times
    cryptic sat on in each year's scanned editions, the ledger's."""
    by_year = collections.defaultdict(collections.Counter)
    for rel, row in archive_coverage.ledger().items():
        if fa.ITEM.match(rel.split("/")[0]) and not rel.startswith("Gale"):
            for p in (row.get("scan") or {}).get("puzzles", ()):
                by_year[int(row["scan"]["date"][:4])][p["leaf"] + 1] += 1
    out = {}
    for y, c in by_year.items():
        pages = sorted(c.elements())
        out[y] = (pages[len(pages) // 10], pages[(len(pages) * 9) // 10], c.most_common(1)[0][0])
    return out


def nearest(years, y):
    return years[min(years, key=lambda k: (abs(k - y), k))] if years else None


def wanted(today=None):
    """[(date, class)] of every Times edition in YEARS no puzzle file holds:
    class archive_coverage's for one archive.org holds no scan of (or whose
    year it has no listing of), SCAN_UNFILED for one it does (not classed
    further: that reads the ledgers and stats each edition's dir)."""
    today = today or datetime.datetime.now().astimezone().date()
    return [(datetime.date.fromisoformat(d), cls)
            for d, cls, _ in archive_coverage.unfiled(fa.TIMES, today, scanned=False, scans_as=SCAN_UNFILED)
            if cls and int(d[:4]) in YEARS]


class Other(collections.namedtuple("Other", "series years printed folder item")):
    """Another paper the portal's Gale archives hold: its series, the years
    Gale holds its crossword in, its printed (weekdays, first day) when
    archive_coverage.PRINTED has no row for it, its folder under GALE_ROOT
    and its edition item under CACHE."""


#: The other papers, fetched by tools/gale_fetch.py once no Times row is
#: left, in this order: the biggest gaps whose pages a filer's headings
#: read (file_archive_org_puzzles' TELEGRAPH, FT) first, then those with
#: none (its GALE_INDEPENDENT, GALE_SUNDAY_TIMES, GALE_TLS). Each archive's years are its
#: issuesForMonth's (read 2026-10-11): TGRH ends with 2000, FTHA (its
#: crossword from 1966) with 2010, INDA with 2016, STHA with 2006; TLSH
#: (read 2026-10-12) runs 1902 to 26 December 2014, a Friday weekly whose
#: contents first name "TLS Crossword 102" on 5 June 1992 (few before 1995).
OTHERS = {
    "TGRH": Other("telegraph", range(1925, 2001), None, "Telegraph", "GaleTelegraph{}UKEnglish"),
    "FTHA": Other("ftcryptic", range(1966, 2011), None, "FT", "GaleFT{}UKEnglish"),
    "INDA": Other("independent", range(1986, 2017), (range(6), "1986-10-07"), "Independent",
                  "GaleIndependent{}UKEnglish"),
    "STHA": Other("sundaytimes", range(1924, 2007), ((6,), "1924-12-28"), "Sunday Times",
                  "GaleSundayTimes{}UKEnglish"),
    "TLSH": Other("tls", range(1992, 2015), ((4,), "1992-01-03"), "TLS", "GaleTLS{}UKEnglish"),
}


def printed(other, until):
    """The dates `other` printed through `until`: archive_coverage's, or
    its own printed days (Christmas Day never)."""
    if other.printed is None:
        yield from (datetime.date.fromisoformat(d) for d in archive_coverage.printed_dates(other.series, until))
        return
    weekdays, first = other.printed
    d = datetime.date.fromisoformat(first)
    while d <= until:
        if d.weekday() in weekdays and (d.month, d.day) != (12, 25):
            yield d
        d += datetime.timedelta(days=1)


def other_wanted(prod, today=None, laid=None):
    """[date] of each edition of OTHERS[prod] in its Gale years with no
    puzzle filed and none laid out (the EDITIONS manifest), newest first."""
    other = OTHERS[prod]
    today = today or datetime.datetime.now().astimezone().date()
    filed = archive_coverage.corpus(other.series)[0]
    laid = set(editions()) if laid is None else laid
    out = []
    for d in printed(other, min(today, datetime.date(other.years[-1], 12, 31))):
        if d.year not in other.years or d.isoformat() in filed:
            continue
        if f"{other.item.format(d.year)}/{d.isoformat()}" not in laid:
            out.append(d)
    return out[::-1]


def fresh_unread(rows=None, now=None, laid=None):
    """The "<item>/<date>" of each Times edition laid out (or shrunk) in the
    last FRESH seconds whose files the ledger holds no reading of. Read off
    the EDITIONS manifest; the ledger is read only when one is that fresh."""
    now = time.time() if now is None else now
    laid = editions() if laid is None else laid
    fresh = {e: r for e, r in laid.items()
             if now - r["at"] <= FRESH and re.fullmatch(ITEM.format(r"\d+"), e.split("/")[0])}
    if not fresh:
        return []
    rows = ledger_summary() if rows is None else rows
    return sorted(e for e, r in fresh.items()
                  if "inputs" not in (rows.get(e) or {}) or rows[e].get("filesHash") != r["files"])


def kick(out=sys.stdout, tick=TICK, log=TICK_LOG):
    """Start the full pass (`tick` tick, detached: corpus_queue.py tick from
    its own worktree) when a fresh edition waits to be read and no pass
    runs, so a page laid out between passes waits minutes, not for the
    hourly tick. A running pass reads it first by itself; a held one stays
    held (corpus_queue.py stop holds these reads too)."""
    waiting = fresh_unread()
    if not waiting:
        return None
    import corpus_queue
    if corpus_queue.running():
        return None
    if corpus_queue.load_state().get("held"):
        print(f"{len(waiting)} fresh edition(s) wait, but the full pass is held "
              "(corpus_queue.py release lets it start)", file=out)
        return None
    log.parent.mkdir(parents=True, exist_ok=True)
    # Without this tick's worktree marks, so the tick takes its own worktree
    # (tools/nightly_worktree.sh): this tree is reset every tick.
    env = {k: v for k, v in os.environ.items() if k not in ("CT_IN_WORKTREE", "CT_MAIN_CHECKOUT")}
    with open(log, "a") as f:
        p = subprocess.Popen(["bash", str(tick), "tick"], stdout=f, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True, env=env)
    print(f"no full pass runs: started {tick.name} tick (pid {p.pid}) for {len(waiting)} fresh edition(s): "
          f"{', '.join(waiting[:5])}; log {log}", file=out)
    return p


def staged_matches(laid=None):
    """{date: [match]} of the Times editions laid out (the EDITIONS
    manifest's sources)."""
    laid = editions() if laid is None else laid
    out = {}
    years = re.compile(ITEM.format(r"\d+"))
    for e, r in laid.items():
        item, day = e.split("/")
        if years.fullmatch(item) and ISO_DAY.fullmatch(day) and r.get("sources") is not None:
            out[datetime.date.fromisoformat(day)] = copy.deepcopy(r["sources"])
    return out


#: The progress page reloads itself this often.
RELOAD_SECONDS = 180


#: The progress page's look.
CSS = """body{font:15px -apple-system,Segoe UI,sans-serif;margin:1.5em;max-width:72em}
td,th{padding:4px 8px;text-align:left;vertical-align:middle}tr:nth-child(even){background:#f4f4f4}
h2{margin-top:1.4em}"""


def cryptic_cited(m):
    """Does a staged file's Gale citation name the day's cryptic ("The
    Times Crossword Puzzle No 17,257"), the article gale_docs links?"""
    return bool(m.get("cited")) and gale_docs.crossword("TTDA", [m["cited"]]) == 0


#: The Times folder's Set aside subfolder, where files once set aside lie
#: (aside_days still reads their log).
ASIDE = "Set aside"
#: Each file set aside: {file: {"date", "why", "at"}}.
SET_ASIDE = HOME / "set_aside.json"


def aside_days(log=SET_ASIDE):
    """{date: [why]} of the dates a file was set aside for."""
    out = collections.defaultdict(list)
    for e in load(log, {}).values():
        if e.get("date"):
            out[datetime.date.fromisoformat(e["date"])].append(e["why"])
    return out


def not_on_gale(day, docs, aside):
    """Why Gale has no cryptic to fetch for `day`, or None: no issue that
    day, or an issue whose contents list no crossword and whose page saved
    for the day was set aside as another article."""
    e = docs.get(f"TTDA/{day.isoformat()}") or {}
    if e.get("why") == "Gale has no issue that day":
        return "Gale has no issue that day"
    if e.get("why") == "no crossword in the issue's contents" and any("citation names" in w for w in aside.get(day, ())):
        return "Gale's contents list no cryptic that day, and the page found for it was another puzzle"
    return None


#: How next_up orders, said on the page.
ORDER = ("Order: Times No 1 (1 Feb 1930) first; then the 1974-99 editions archive.org has no scan of, the"
         " year missing the most first and oldest date first within a year; then 2014, then 2000-13, then the"
         " rest of 1930-99, each newest first. An edition leaves the list once its puzzle is filed.")
#: Times No 1's date: the first issue goes first (Paul, 2026-10-02).
FIRST_ISSUE = datetime.date(1930, 2, 1)


def tier(day, cls):
    """Where an edition's group stands in next_up's order (ORDER)."""
    if day == FIRST_ISSUE:
        return 0
    if cls in WANTED and 1974 <= day.year <= 1999:
        return 1
    return 2 if day.year >= 2014 else 3 if day.year >= 2000 else 4


def next_up(rows, staged, n=None):
    """The `n` (default all) editions to fetch first, in ORDER: the 1974-99 scanless ones
    the year missing most first, oldest first within it; the rest newest
    first."""
    old = collections.Counter(day.year for day, cls in rows if tier(day, cls) == 1)
    order = sorted(rows, key=lambda r: (tier(*r), -old[r[0].year], r[0].toordinal()) if tier(*r) <= 1
                   else (tier(*r), 0, -r[0].toordinal()))
    return [(d, c) for d, c in order if d not in staged][:n]


#: tools/gale_fetch.py's log of each download, and of Gale's refusals.
FETCHED, LIMITS = gale_fetch.FETCHED, gale_fetch.LIMITS
#: The latest downloads listed.
LATEST = 20


def checklist(rows=None, laid=None, docs=None, ledger=None, log=SET_ASIDE,
              fetched=FETCHED, limits=LIMITS, now=None):
    """The Times progress page. tools/gale_fetch.py downloads every wanted
    edition itself, so nothing on it is to click: how many editions are
    still wanted, laid out and waiting to be read, read, and not on Gale;
    the downloader's latest files and Gale's refusals (LIMITS); then each
    year's counts, in next_up's order (ORDER)."""
    e = html.escape
    now = now or datetime.datetime.now().astimezone()
    rows = wanted() if rows is None else rows
    ledger = ledger_summary() if ledger is None else ledger
    matches = staged_matches(laid)
    docs = gale_docs.load() if docs is None else docs
    aside = aside_days(log)
    gone = {day for day, _ in rows if not_on_gale(day, docs, aside)}

    def read(day):
        return f"{ITEM.format(day.year)}/{day.isoformat()}" in ledger

    staged = [day for day, _ in rows if day in matches]
    left = len(rows) - len(staged) - len(gone - set(staged))
    got = sorted(load(fetched, {}).items(), key=lambda kv: kv[1].get("at", ""), reverse=True)
    today = sum(v.get("at", "").startswith(now.date().isoformat()) for _, v in got)
    kept = load(limits, {})
    refusals, recoveries = kept.get("refusals", []), kept.get("recoveries", [])
    years = collections.defaultdict(lambda: [0, 0, 0, 0])
    for day, _ in rows:
        y = years[day.year]
        y[0] += 1
        y[1] += day in matches and not read(day)
        y[2] += day in matches and read(day)
        y[3] += day in gone
    out = [f"""<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="{RELOAD_SECONDS}">
<title>Times crosswords from Gale: {left:,} to fetch</title>
<style>{CSS}</style>
<h1>Times crosswords from Gale</h1>
<p>Nothing here to click: <b>tools/gale_fetch.py</b> downloads each wanted edition itself, at a hand's pace,
and lays it out for the reader, which files its puzzle. Updated {now:%a %d %b %H:%M}; this page reloads every
{RELOAD_SECONDS // 60} minutes.</p>
<table><tr><th>Wanted (no puzzle filed)</th><td>{len(rows):,}</td></tr>
<tr><th>Still to fetch</th><td>{left:,}</td></tr>
<tr><th>Fetched, waiting to be read</th><td>{sum(not read(d) for d in staged):,}</td></tr>
<tr><th>Read, no puzzle filed from it</th><td>{sum(read(d) for d in staged):,}</td></tr>
<tr><th>Not on Gale</th><td>{len(gone):,}</td></tr>
<tr><th>Downloaded by the script</th><td>{len(got):,} ({today:,} today)</td></tr>
<tr><th>Gale refusals</th><td>{len(refusals)}{
        f" (last {e(refusals[-1]['at'])}, after {refusals[-1]['in_window']} in its window)" if refusals else ""}{
        f"; worked again after {recoveries[-1]['waited'] / 60:.0f} min" if recoveries else ""}</td></tr></table>
<p>{e(ORDER)}</p>"""]
    if got:
        out.append("<h2>Latest downloads</h2><table><tr><th>When</th><th>Edition</th><th>File</th></tr>")
        out += [f"<tr><td>{e(v.get('at', ''))}</td><td>{e(OTHERS[v['prod']].folder + ' ' if v.get('prod') in OTHERS else '')}"
                f"{e(v.get('date', ''))}</td><td>{e(doc)}</td></tr>"
                for doc, v in got[:LATEST]]
        out.append("</table>")
    out.append("<h2>By year</h2><table><tr><th>Year</th><th>Wanted</th><th>Waiting to be read</th>"
               "<th>Read, not filed</th><th>Not on Gale</th></tr>")
    out += [f"<tr><td>{y}</td>" + "".join(f"<td>{n:,}</td>" for n in years[y]) + "</tr>"
            for y in dict.fromkeys(d.year for d, _ in next_up(rows, (), None))]
    out.append("</table>")
    return "\n".join(out) + "\n"

def last_render(path=CHECKLIST):
    return path.stat().st_mtime if path.exists() else 0


@contextlib.contextmanager
def locked(wait=True):
    """Held while a sync runs: one at a time. With `wait` False, yields False at once when another holds
    it, else True."""
    import fcntl
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True


def sync(out=sys.stdout, force=False):
    """One tick: publish the Times progress page when tools/gale_fetch.py
    logged a download since the last (or RENDER_EVERY passed); then start
    the full pass if none runs to read the editions tools/gale_fetch.py
    laid out (kick). Skipped when another sync is running, or until the
    EDITIONS manifest is built (build-manifest)."""
    if not media_manifest.built(EDITIONS):
        print(f"{media_manifest.path(EDITIONS)} is not built yet (gale_inbox.py build-manifest); this tick skips",
              file=out)
        return
    with locked(wait=False) as mine:
        if not mine:
            # Another sync is doing this same work: waiting behind it ran a
            # tick past its 900 s limit.
            print("another sync holds the lock; this one skips", file=out)
            return
        _TICK_HELD[:] = [True]
        try:
            _sync_locked(out, force)
        finally:
            _TICK_HELD.clear()
    kick(out)


def _sync_locked(out, force):
    """sync's work under the lock."""
    if (force or time.time() - last_render() > RENDER_EVERY
            or (FETCHED.exists() and FETCHED.stat().st_mtime > last_render())):
        CHECKLIST.parent.mkdir(parents=True, exist_ok=True)
        CHECKLIST.write_text(checklist())
        if publish(out=out):
            print(f"progress page published to {GALE_ROOT}/{CHECKLIST_NAME}", file=out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sy = sub.add_parser("sync", help="publish the progress page, start the full pass")
    sy.add_argument("--render", action="store_true", help="publish even when nothing was downloaded")
    cl = sub.add_parser("checklist", help="write the progress page")
    cl.add_argument("--out", type=Path, default=CHECKLIST)
    sub.add_parser("build-manifest", help="walk the Gale editions once and write their SSD manifest (never scheduled)")
    sub.add_parser("shrink", help="lay out smaller every staged leaf over MAX_PAGE_PIXELS (its edition comes due)")
    a = ap.parse_args(argv)
    if a.cmd == "build-manifest":
        build_manifest()
        return 0
    if a.cmd == "shrink":
        print(f"{len(shrink_oversized())} edition(s) shrunk")
        return 0
    if a.cmd == "checklist":
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(checklist())
        print(f"wrote {a.out}")
        return 0
    sync(force=a.render)
    return 0


if __name__ == "__main__":
    sys.exit(main())
