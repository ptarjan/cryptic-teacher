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
click) and the page shell, row script and Mac publishing the Listener's
checklist shares (page, script, publish; tools/gale_listener.py).

    python3 tools/gale_inbox.py sync [--render]   # publish the progress page, tick the Listener, kick the pass
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
import tarfile
import time
import urllib.parse
from pathlib import Path
import archive_coverage
import dir_cache
import file_archive_org_puzzles as fa
import gale_docs
import gale_fetch
import pypdf
import trove_grid

TOOLS = Path(__file__).resolve().parent

HOST = os.environ.get("GALE_INBOX_HOST", "pt@host.docker.internal")
#: The Mac folder the Gale pages and the checklists live in, on the Media
#: disk: the SMB share "Media", Z: on the Windows desktop (SHARE).
GALE_ROOT = "/Volumes/Media/Gale crosswords"
SHARE = r"Z:\Gale crosswords"


LISTENER_INBOX = f"{GALE_ROOT}/Listener"
CHECKLIST_NAME = "Checklist.html"


SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "HostKeyAlias=localhost",
       "-i", os.path.expanduser("~/.ssh/host_hatch")]
#: This module's and tools/gale_fetch.py's state.
HOME = Path(os.path.expanduser("~/.cache/gale_inbox"))
CHECKLIST = HOME / CHECKLIST_NAME


#: The edition dirs' listings and staged matches between ticks (dir_cache.save).
DIR_CACHE = HOME / "dir_cache.pickle"
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

PORTAL = "https://abresearchportal.ca/collections"
#: Where the portal's archive tile lands (its actions/auth.php redirects
#: here): Gale lets an Alberta IP in and sets the browser's session. A
#: Gale link opened before it asks for a password.
SESSION = "https://link.gale.com/apps/{}?u=alberta_portal&id=Alberta&sid=geolinks"
#: A Gale article opens from its document id.
DOC_URL = "https://go.gale.com/ps/retrieve.do?docId=GALE%7C{}&prodId=TTDA&userGroupName=alberta_portal"
#: Gale's advanced search as a GET (its own form's fields): document title
#: containing the word, published On the date (dateMode 2, era 1 = AD).
SEARCH = "https://go.gale.com/ps/advancedSearch.do"
DOC_ID = re.compile(r"GALE[\W_]{0,3}([A-Z]{2}\d{8,12})", re.IGNORECASE)
#: Where else a saved file names its document: the permalink its PDF's
#: citation prints ("link.gale.com/apps/doc/IF0500468517/").
CITED_DOC = re.compile(r"link\.gale\.com/apps/doc/([A-Z]{2}\d{8,12})\b", re.IGNORECASE)
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

#: [held()] while a sync tick runs: the tick files no puzzle, so its five
#: reads of the series' directory give one answer. Empty outside a sync.
_TICK_HELD = []


def held():
    """{number: date} of every filed Times puzzle (read once a sync tick)."""
    if _TICK_HELD:
        return _TICK_HELD[0]
    return fa.held_dates(fa.TIMES.series)


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
    squares = fa.grids_on(img, shaped=square)
    grids = shaped or squares
    if not grids:
        return grids

    def width(b):
        return b[2] - b[0]

    def is_lattice(b):
        return trove_grid.lattice(img.crop((max(0, b[0] - 6), max(0, b[1] - 6), b[2] + 6, b[3] + 6)))
    widest = max(grids, key=width)
    if is_lattice(widest):
        return grids
    rest = sorted((b for b in shaped + [list(b) for b in squares] if list(b) != list(widest)), key=width, reverse=True)
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
    return done


# ------------------------------------------------------------ staging

#: A staged edition's "how" when tools/gale_fetch.py laid it out.
FETCHED_HOW = "fetched"


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
    with tempfile.TemporaryDirectory() as t:
        (Path(t) / name).write_bytes(data)
        read = images(Path(t) / name)
    d.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".gale_fetch-", dir=cache))
    tmp = work / d.name
    tmp.mkdir()
    leaves, grid = [], False
    for img, _ in read:
        page, found = scaled(img)
        grid |= found
        leaf = len(leaves)
        page.save(tmp / f"leaf_{leaf:04d}.jpg", quality=92)
        leaves.append({"leaf": leaf, "width": page.width, "height": page.height, "file": name})
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
    return d


def fetched_dir(d):
    """Is edition dir `d` one tools/gale_fetch.py laid out (lay_out_fetched)?"""
    found = staged_year(d.parent).get(d.name, ((), None))[1]
    return bool(found) and all(m.get("how") == FETCHED_HOW for m in found)


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


def mirror(out=sys.stdout, *, host_inbox, into):
    """Copy the Mac inbox's page files (the Listener's) to `into`: the new and changed ones;
    a file gone from the inbox goes from the mirror. Only the Mac is asked.
    How many files it copied or dropped."""
    q = shlex.quote
    listing = ssh(f"mkdir -p {q(host_inbox)} && cd {q(host_inbox)} && "
                  "find . -maxdepth 1 -type f -exec stat -f '%z %m %N' {} +; exit 0", text=True).stdout
    there = {}
    for line in listing.splitlines():
        size, mtime, name = line.split(" ", 2)
        name = name.removeprefix("./")
        if Path(name).suffix.lower() in PAGES:
            there[name] = (int(size), int(mtime))
    into.mkdir(parents=True, exist_ok=True)
    want = [n for n, (size, mtime) in there.items()
            if not (into / n).exists() or (into / n).stat().st_size != size
            or int((into / n).stat().st_mtime) != mtime]
    for i in range(0, len(want), 100):
        batch = want[i:i + 100]
        blob = ssh(f"cd {q(host_inbox)} && tar cf - -- {' '.join(q(n) for n in batch)}").stdout
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            for member in tar.getmembers():
                if member.isfile() and Path(member.name).name in there:
                    dest = into / Path(member.name).name
                    dest.write_bytes(tar.extractfile(member).read())
                    os.utime(dest, (member.mtime, member.mtime))
        print(f"copied {len(batch)} file(s) from the Mac inbox", file=out)
    dropped = 0
    for p in into.iterdir():
        if p.name not in there:
            p.unlink()
            dropped += 1
            print(f"dropped {p.name}: gone from the Mac inbox", file=out)
    return len(want) + dropped


def publish(path=CHECKLIST, host_inbox=GALE_ROOT, polled=False):
    """Copy a checklist into the Mac folder under its own name. A page is
    replaced whole (written aside, then renamed). A `polled` file (a status
    file, which an open page loads every POLL_SECONDS) is rewritten in
    place: Windows reads it over SMB through a cached handle, which goes on
    serving a renamed-over file's old copy; a half-written one fails to
    parse and the next poll reads it whole."""
    q = shlex.quote
    dest = q(host_inbox + '/' + path.name)
    if polled:
        ssh(f"mkdir -p {q(host_inbox)} && cat > {dest}", input=path.read_bytes())
        return
    tmp = f"{host_inbox}/.{path.name}.tmp"
    ssh(f"mkdir -p {q(host_inbox)} && cat > {q(tmp)} && mv -f {q(tmp)} {dest}", input=path.read_bytes())


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


def other_wanted(prod, cache=CACHE, today=None):
    """[date] of each edition of OTHERS[prod] in its Gale years with no
    puzzle filed and none laid out, newest first."""
    other = OTHERS[prod]
    today = today or datetime.datetime.now().astimezone().date()
    filed = archive_coverage.corpus(other.series)[0]
    laid = {}
    out = []
    for d in printed(other, min(today, datetime.date(other.years[-1], 12, 31))):
        if d.year not in other.years or d.isoformat() in filed:
            continue
        if d.year not in laid:
            year = cache / other.item.format(d.year)
            laid[d.year] = set(os.listdir(year)) if year.is_dir() else set()
        if d.isoformat() not in laid[d.year]:
            out.append(d)
    return out[::-1]


def fresh_unread(cache=CACHE, rows=None, now=None):
    """The "<item>/<date>" of each Gale edition laid out in the last FRESH
    seconds that has no reading of its current files in the ledger."""
    rows = archive_coverage.ledger() if rows is None else rows
    now = time.time() if now is None else now
    out = []
    # An edition's pages.json is written before the rename that lays it out
    # moves its year dir: a year dir unmoved for FRESH holds no fresh one.
    years = [cache / y for y in dir_cache.listed(cache) if re.fullmatch(ITEM.format(r"\d+"), y)]
    for pages in (p for y in years if now - y.stat().st_mtime <= FRESH for p in y.glob("*/pages.json")):
        d = pages.parent
        if now - pages.stat().st_mtime > FRESH:
            continue
        row = rows.get(f"{d.parent.name}/{d.name}") or {}
        if "inputs" not in row or row.get("filesHash") != fa.input_hash(d):
            out.append(f"{d.parent.name}/{d.name}")
    return sorted(out)


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


def _staged_in(d):
    """(the sources-*.json names, the last one parsed or None) of edition
    dir `d`: kept in dir_cache's memo (and so between ticks, dir_cache.save)
    until the dir moves, not read off the media mount again."""
    _, names, memo = dir_cache.seen(d)
    srcs = tuple(n for n in names if n.startswith("sources-") and n.endswith(".json"))
    if "sources" not in memo:
        memo["sources"] = json.loads((d / srcs[-1]).read_text()) if srcs else None
    return srcs, memo["sources"]


def staged_year(year_dir):
    """{day: (its sources-*.json names, the last one parsed or None)} of
    each edition dir in `year_dir` ({} when it is no dir). A day dir's
    sources-*.json change only as stage renames a whole dir in or removes
    one, each of which moves the year dir (relink rewrites pages.json alone),
    so the answer is kept in the year dir's memo while the year dir is
    unmoved: one stat, not one a day."""
    try:
        _, names, memo = dir_cache.seen(year_dir)
    except (FileNotFoundError, NotADirectoryError):
        return {}
    if "staged" not in memo:
        found = {}
        for day in names:
            try:
                found[day] = _staged_in(year_dir / day)
            except (FileNotFoundError, NotADirectoryError):
                continue
        memo["staged"] = found
    return memo["staged"]


def has_sources(d, name):
    """Whether edition dir `d` holds sources file `name` (staged_year)."""
    return name in staged_year(d.parent).get(d.name, ((), None))[0]


def staged_matches(cache=CACHE):
    """{date: [match]} of the inbox pages staged as editions (stage's
    sources-*.json). Each year dir is stat-ed, not its editions, while it
    is unmoved (staged_year); a dir not named for a date (a .new one a
    killed stage left) is no edition."""
    out = {}
    years = re.compile(ITEM.format(r"\d+"))
    for item in dir_cache.listed(cache):
        if not years.fullmatch(item):
            continue
        for day, (_, found) in staged_year(cache / item).items():
            if found is not None and ISO_DAY.fullmatch(day):
                out[datetime.date.fromisoformat(day)] = copy.deepcopy(found)
    return out


#: The Listener checklist's "next up": POOL rows, all shown and none moved
#: as they are clicked; next up shows the linked rows first (page).
POOL = 60


#: A row clicked this long ago whose file has not arrived turns amber: the
#: download may have failed.
LATE_MINUTES = 15
#: How often an open checklist reads its status file (status_js).
POLL_SECONDS = 5
#: A status file older than this is not being written: the page falls back
#: to reloading itself every RELOAD_SECONDS. A sync publishes it at its start
#: and end, and between them spends up to two Gale allowances (GALE_SECONDS
#: each) plus staging, so this must exceed that.
STALE_SECONDS = 720
RELOAD_SECONDS = 180


def script(store, status_src, stamp):
    """The checklists' row state. A row is one of: to fetch (its Download
    button), clicked and waiting for its file ("downloading... clicked
    HH:MM", an undo, no Download), clicked LATE_MINUTES ago with no file
    (amber, a retry), or arrived ("in the inbox", the sync's); a row to
    fetch says TO DO. Clicks are kept in the
    browser (localStorage `store`, key: when) so a reload keeps them; what
    arrived is the page's own data-in and its status file (status_js),
    read every POLL_SECONDS by a script tag, which a file:// page may load
    where it may not fetch. A status naming a newer page reloads it once;
    a status that stops coming reloads the page every RELOAD_SECONDS. #next
    shows all its rows and never moves one (a browser agent works down it,
    Paul 2026-10-11): a clicked row is marked where it is, the first to
    fetch is highlighted, and #left counts those still to fetch. A click anywhere on a row
    to fetch is a click on its Download (a.dl). A middle click on a link opens a tab
    without a click event, so it runs the link's onclick (the mark) itself."""
    js = """<script>
const S=STORE,C=S+'At',LATE=LATEMIN*60e3,PAGE=STAMP,SRC=SOURCE,
  LOADED=Date.now();
let IN=new Set(),AT=PAGE*1000,BASE=null;
function get(n){return JSON.parse(localStorage.getItem(n)||'[]')}
function clicks(){const v=localStorage.getItem(C);if(v)return JSON.parse(v);const m={};get(S).forEach(k=>m[k]=0);return m}
function keep(m){localStorage.setItem(C,JSON.stringify(Object.fromEntries(
  Object.entries(m).sort((a,b)=>a[1]-b[1]).slice(-5000))))}
function hm(t){return t?new Date(t).toTimeString().slice(0,5):'earlier'}
function state(r,m,now){const k=r.dataset.k;if(r.dataset.in||IN.has(k))return'in';
  return k in m?(now-m[k]>LATE?'late':'wait'):''}
function badge(r,s,t){const b=r.querySelector('.st');if(!b||b.dataset.s===s+t)return;b.dataset.s=s+t;b.className='st '+s;
  const k=r.dataset.k,u=' <a href="#" onclick="unmark(\\''+k+'\\');return false">undo</a>',
    a=r.querySelector('a.dl')||r.querySelector('a.go');
  b.innerHTML=s==='in'?'&#10003; DONE: in the inbox':s==='wait'?'CLICKED: downloading&hellip; clicked '+hm(t)+u
    :s==='late'?'CLICKED '+hm(t)+', not arrived: <a class="retry" target="gale" onclick="mark(\\''+k+'\\')">retry?</a>'+u
    :r.querySelector('a.dl')?'TO DO':'';
  const x=b.querySelector('a.retry');if(x&&a)x.href=a.href}
function show(){const m=clicks(),now=Date.now();let n=0,lit=false;
  document.querySelectorAll('tr[data-k]').forEach(r=>{const s=state(r,m,now);r.dataset.s=s;
    for(const c of['wait','late','in'])r.classList.toggle('s-'+c,s===c);
    badge(r,s,m[r.dataset.k]||0);r.classList.toggle('dlrow',!s&&!!r.querySelector('a.dl'))});
  const nx=document.getElementById('next');
  if(nx){nx.querySelectorAll('tr[data-i]').forEach(r=>{const x=!r.dataset.s&&!!r.querySelector('a.dl');
    if(x)n++;r.classList.toggle('next',x&&!lit);if(x)lit=true})}
  const lf=document.getElementById('left');if(lf)lf.textContent=n;
  count();const mo=document.getElementById('more');if(mo)mo.hidden=n>0;
  const a=document.getElementById('age'),old=now-AT>STALE*1e3;
  if(a){a.textContent='Arrivals last checked '+hm(AT)+' ('+Math.round((now-AT)/60e3)+' min ago)'
    +(old?': the status file is not updating, so this page reloads itself every 3 minutes':'; this page updates itself.');
    a.classList.toggle('old',old)}}
function mark(k){const m=clicks();m[k]=Date.now();keep(m);show()}
function unmark(k){const m=clicks();delete m[k];keep(m);show()}
function count(){const s=BASE;if(!s||s.done==null)return;const d=Math.min(s.done,s.total),
  p=document.getElementById('prog'),f=n=>n.toLocaleString('en');
  if(p){p.value=d;p.max=Math.max(s.total,1)}
  const c=document.getElementById('count');if(c)c.textContent=f(d)+' of '+f(s.total);
  const t=document.getElementById('togo');if(t)t.textContent=f(s.total-d)}
function galeStatus(s){IN=new Set(s.in);AT=s.at*1000;BASE=s;
  if(s.page>PAGE&&sessionStorage.getItem(S+'Page')!==String(s.page)){
    sessionStorage.setItem(S+'Page',s.page);location.reload()}else show()}
function load(u){const x=document.createElement('script');x.src=u+'?'+Date.now();
  x.onload=x.onerror=()=>x.remove();document.head.appendChild(x)}
function poll(){load(SRC)}
function cp(b,t){const done=()=>{b.textContent='Copied'};
  const fb=()=>{const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();
  document.execCommand('copy');a.remove();done()};
  if(navigator.clipboard&&window.isSecureContext)navigator.clipboard.writeText(t).then(done,fb);else fb()}
addEventListener('DOMContentLoaded',()=>{show();poll()})
setInterval(()=>{const now=Date.now();
  if(now-AT>STALE*1e3&&now-LOADED>RELOAD*1e3)location.reload();else{poll();show()}},POLL*1e3)
addEventListener('click',ev=>{const r=ev.target.closest('tr.dlrow');
  if(r&&!ev.target.closest('a,button,summary'))r.querySelector('a.dl').click()})
addEventListener('auxclick',ev=>{const a=ev.button===1&&ev.target.closest('a[target=gale][onclick]');if(a)a.onclick()})
</script>"""
    for k, v in (("STORE", json.dumps(store)), ("SOURCE", json.dumps(status_src)),
                 ("LATEMIN", str(LATE_MINUTES)), ("STAMP", str(stamp)), ("STALE", str(STALE_SECONDS)),
                 ("RELOAD", str(RELOAD_SECONDS)), ("POLL", str(POLL_SECONDS))):
        js = js.replace(k, v)
    return js


#: Both checklists' look.
CSS = """body{font:15px -apple-system,Segoe UI,sans-serif;margin:1.5em;max-width:72em}
td,th{padding:4px 8px;text-align:left;vertical-align:middle}tr:nth-child(even){background:#f4f4f4}
h2{margin-top:1.4em}summary{font-size:16px;margin:.4em 0;cursor:pointer}
.got{color:#070}.bad{color:#a00}.est{color:#a60;font-size:90%}#age.old{color:#a00;font-weight:bold}
.notes{color:#555;font-size:90%}.how{background:#eef6ff;padding:.5em 1em}
.start{font-size:17px;font-weight:bold}progress{width:20em;height:1.2em;vertical-align:middle}
button{font-size:14px;padding:2px 10px;cursor:pointer}.batch button{font-size:15px;margin-right:.6em}
a.dl{display:inline-block;padding:8px 18px;font-size:17px;font-weight:bold;color:#fff;background:#0a66c2;
border-radius:6px;text-decoration:none;margin:2px .8em 2px 0}a.dl:hover{background:#084f96}a.go{margin-right:.6em}
.st{display:inline-block;padding:6px 12px;border-radius:6px;font-weight:bold}.st:empty{display:none}
.agent{border:2px solid #0a66c2;padding:.4em 1em;margin:1em 0}
.st.wait{background:#dde8f6;color:#123}.st.late{background:#ffc24d;color:#4a2c00}.st.in{background:#17803a;color:#fff}
.st a{color:inherit}tr.s-wait .acts,tr.s-late .acts,tr.s-in .acts{display:none}tr.s-in td{color:#777}
tr.next td{background:#fff3b0}tr.next td:first-child{border-left:4px solid #e0a800}
tr.dlrow{cursor:pointer}tr.dlrow:hover td{background:#dcebff}"""


def status_js(path):
    """The status file beside checklist `path`: when the inbox was last
    looked at, the page it goes with, and the rows arrived."""
    return path.with_name(path.stem + ".status.js")


def publish_status(path, status=None):
    """Write and publish checklist `path`'s status file (status_js): the
    page's stamp and arrived rows from `status` (a render's), else the last
    render's, and now as when the inbox was looked at."""
    js = status_js(path)
    kept = js.with_suffix(".json")
    js.parent.mkdir(parents=True, exist_ok=True)
    if status is not None:
        kept.write_text(json.dumps(status))
    st = load(kept, {"page": 0, "in": []})
    js.write_text(f"galeStatus({json.dumps({**st, 'at': int(time.time())})});\n")
    publish(js, polled=True)


def _parts(cell):
    """A cell's HTML: plain text, or [(text, class)]."""
    if isinstance(cell, str):
        return html.escape(cell)
    return " ".join(f'<span class="{c}">{html.escape(t)}</span>' if c else html.escape(t) for t, c in cell)


def row_docs(r):
    """The Gale documents a row's links name (its Downloads' dl, its Open in
    Gale permalink's): a file named for any of them is that row's."""
    out = []
    for u in [r.get("dl"), *(u for _, u in r.get("more") or ()), r.get("search")]:
        if u:
            m = CITED_DOC.search(u)
            for d in urllib.parse.parse_qs(urllib.parse.urlsplit(u).query).get("dl", []) + ([m.group(1)] if m else []):
                if d.upper() not in out:
                    out.append(d.upper())
    return out


def _row(r):
    """One row: {"date", "cells", "status", and, for one to fetch, "key",
    "search" (Open in Gale), "dl" (Download, or None), "label", "more" ([(label,
    url)] further Downloads beside it), "copy" (a
    search to copy, or None), "arrived"}."""
    k = r.get("key")
    get = ""
    if k and r.get("arrived"):
        get = '<span class="st in">&#10003; in the inbox</span>'
    elif k:
        e, mk, dl = html.escape, f' onclick="mark(\'{k}\')"', r.get("dl")
        get = ('<span class="acts">'
               + (f'<a class="dl" href="{e(dl)}" target="gale"{mk}>{e(r.get("label") or "Download")}</a>' if dl else "")
               + "".join(f'<a class="dl" href="{e(u)}" target="gale"{mk}>{e(t)}</a>' for t, u in r.get("more") or ())
               + f'<a class="go" href="{e(r["search"])}" target="gale"{"" if dl else mk}>Open in Gale'
               + (f' ({e(r["what"])})' if r.get("what") and not dl else "") + '</a>'
               + (f' <button onclick="cp(this,{e(json.dumps(r["copy"]))})">Copy</button> <code>{e(r["copy"])}</code>'
                  if r.get("copy") else "")
               + '</span><span class="st"></span>')
    docs = row_docs(r)
    attrs = (f' data-k="{k}"' + (f' data-i="{r["i"]}"' if "i" in r else "")
             + (f' data-doc="{" ".join(docs)}"' if docs else "")
             + (' data-in="1" class="s-in"' if r.get("arrived") else "")) if k else ""
    return (f'<tr{attrs}><td>{r["date"]:%a %d %b %Y}</td><td>{get}</td>'
            + "".join(f"<td>{_parts(c)}</td>" for c in r["cells"]) + f"<td>{_parts(r['status'])}</td></tr>")


def page(*, paper, prod, name, store, done, total, done_word, folder, steps, notes, order, what, next_rows,
         years_note, years, columns, status=None):
    """A checklist page, either paper's: progress, the files to check, how to
    save one, the next `next_rows` in batches, then `years` [(year, summary,
    rows)], rows None for a count alone. Rows are _row's; `columns` the paper's own, between the row's
    Download and its status; `steps` the paper's own items of the how-to
    and `order` how next up is ordered (inline HTML). Next up is the first
    POOL of `next_rows` with a Download link first, in their order, so a
    click on any row it shows downloads; one with none (no lookup yet, or
    Gale has none) follows them. `status`, when given, gets the page's stamp
    and arrived rows, for publish_status."""
    e = html.escape
    next_rows = ([r for r in next_rows if r.get("dl")] + [r for r in next_rows if not r.get("dl")])[:POOL]
    stamp = int(time.time())
    every = [r for r in next_rows] + [r for _, _, rs in years for r in rs or ()]
    if status is not None:
        status.update(page=stamp, done=done, total=total,
                      **{"in": sorted({r["key"] for r in every if r.get("key") and r.get("arrived")})})
    head = ("<tr><th>Date</th><th>Get it</th>" + "".join(f"<th>{e(c)}</th>" for c in columns)
            + "<th>Status</th></tr>")
    title = f"{paper} crosswords from Gale"
    archive = gale_docs.PRODUCTS[prod][2]
    out = [f"""<!doctype html><meta charset="utf-8">
<title>{e(title)}: {done:,} of {total:,}</title>
<style>{CSS}</style>
{script(store, urllib.parse.quote(status_js(Path(name)).name), stamp)}
<h1>{e(title)}</h1>
<p><progress id="prog" value="{done}" max="{max(total, 1)}"></progress> <b id="count">{done:,} of {total:,}</b> {e(done_word)}, <span id="togo">{total - done:,}</span> to go.
Updated {datetime.datetime.fromtimestamp(stamp).astimezone():%a %d %b %H:%M}. <span id="age"></span></p>"""]
    out.append(AGENT_STEPS)
    if notes:
        out.append(f'<details class="notes"><summary>Sorted automatically ({len(notes)} file(s)); nothing to do</summary><ul>')
        out += [f"<li><b>{e(f)}</b>: {e(why)}</li>" for f, why in notes]
        out.append("</ul></details>")
    out.append(f"""<div class="how"><p class="start">1. <a href="{SESSION.format(prod)}" target="gale">Start Gale session</a>
(once per sitting, on an Alberta connection such as home Wi-Fi; no login)</p>
<ol start="2"><li>Click <b>Download</b> on the highlighted row: Gale saves the page as a PDF, and it is moved from
Downloads into <code>{e(folder)}</code> for you. The row says <i>downloading&hellip;</i> until the file lands,
<b>&#10003; downloaded</b> within seconds of it, then <b>&#10003; in the inbox</b> once it is sorted, within a few minutes. A row whose file has not come {LATE_MINUTES} minutes
after its click turns amber: retry it.</li>
{"".join(f"<li>{s}</li>" for s in steps)}</ol>
<p>If Gale asks for a password, start from <a href="{PORTAL}">the Alberta Research Portal</a> (choose
<i>{e(archive)}</i>), then come back here.</p></div>""")
    if next_rows:
        out.append(f"""<h2>Next up</h2><p>{order}</p>
<p class="batch"><button onclick="location.reload()">Refresh</button>
The next {len(next_rows)} {e(what)}; <b id="left">{sum(1 for r in next_rows if r.get("dl") and not r.get("arrived"))}</b>
of them still TO DO. Rows never move: a row you click is marked CLICKED where it is. The highlighted row is the one to do next.</p>
<p id="more" hidden>Nothing here is TO DO: <b>Refresh</b> for more.</p>
<table id="next">{head}""")
        out += [_row(dict(r, i=i)) for i, r in enumerate(next_rows)]
        out.append("</table>")
    out.append(f"<h2>Everything, by year</h2><p>{e(years_note)}</p>")
    if any(rs is None for _, _, rs in years):
        # Rows too many to lay out (21,000 Times editions, YEAR_ROWS): each year's count.
        out.append("<table><tr><th>Year</th><th>Editions</th></tr>")
        out += [f"<tr><td>{y}</td><td>{e(summary)}</td></tr>" for y, summary, _ in years]
        out.append("</table>")
        years = []
    for y, summary, rs in years:
        out.append(f"<details><summary><b>{y}</b>: {e(summary)}</summary><table>{head}")
        out += [_row(r) for r in rs]
        out.append("</table></details>")
    return "\n".join(out) + "\n"


#: The plain how-to a browser agent (or Paul) follows, top of each page.
AGENT_STEPS = """<section class="agent" id="instructions"><h2>Instructions</h2><ol>
<li>Click <b>Start Gale session</b> below once (it opens Gale in another tab; no login).</li>
<li>Go to <b>Next up</b>. Take the first row whose status says <b>TO DO</b> (it is highlighted).</li>
<li>Click that row's link that starts with <b>Download</b>. Gale opens the PDF or saves it in another tab;
come back to this tab. The row now says <b>CLICKED</b>.</li>
<li>Repeat with the next row that says TO DO, top to bottom. Click each row at most once; never click a
row that says CLICKED or DONE, and never use retry.</li>
<li>Stop when no row says TO DO, or when Gale shows a password or login page or an error instead of a PDF.</li>
</ol></section>"""


def search_url(day, prod="TTDA", title="crossword"):
    """Gale's results for `title` in a document title of the `day` issue of
    archive `prod`: the day's crossword pages, one click from the page. It
    names the portal's location as the working Download link does (u, p),
    besides the search form's own userGroupName and prodId."""
    q = [("inputFieldNames[0]", "TI"), ("inputFieldValues[0]", title), ("dateIndices", "DA"),
         ("dateLimiterValues[DA].dateMode", "2"), ("dateLimiterValues[DA].fromYear", f"{day.year}"),
         ("dateLimiterValues[DA].fromMonth", f"{day.month:02}"), ("dateLimiterValues[DA].fromDay", f"{day.day:02}"),
         ("dateLimiterValues[DA].fromEra", "1"), ("searchType", "AdvancedSearchForm"), ("method", "doSearch"),
         ("searchMethod", "advanced"), ("searchResultsType", "SingleTab"), ("prodId", prod),
         ("userGroupName", "alberta_portal"), ("u", "alberta_portal"), ("p", prod)]
    return f"{SEARCH}?{urllib.parse.urlencode(q)}"


def cryptic_cited(m):
    """Does a staged file's Gale citation name the day's cryptic ("The
    Times Crossword Puzzle No 17,257"), the article gale_docs links?"""
    return bool(m.get("cited")) and gale_docs.crossword("TTDA", [m["cited"]]) == 0


#: Where set_aside moves a file, in its inbox: the sweep and mirror look
#: only at the inbox's own files, so it is out of every count.
ASIDE = "Set aside"
#: Each file set aside: {file: {"date", "why", "at"}}.
SET_ASIDE = HOME / "set_aside.json"
#: How long a file set aside is listed on the page.
ASIDE_DAYS = 7


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


def next_up(rows, staged, n=POOL):
    """The `n` editions to fetch first, in ORDER: the 1974-99 scanless ones
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


def checklist(rows=None, cache=CACHE, docs=None, ledger=None, log=SET_ASIDE,
              fetched=FETCHED, limits=LIMITS, now=None):
    """The Times progress page. tools/gale_fetch.py downloads every wanted
    edition itself, so nothing on it is to click: how many editions are
    still wanted, laid out and waiting to be read, read, and not on Gale;
    the downloader's latest files and Gale's refusals (LIMITS); then each
    year's counts, in next_up's order (ORDER)."""
    e = html.escape
    now = now or datetime.datetime.now().astimezone()
    rows = wanted() if rows is None else rows
    ledger = archive_coverage.ledger() if ledger is None else ledger
    matches = staged_matches(cache)
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

#: The Listener's Gale link lookups (gale_docs.resolve) run at most this
#: often, whatever the tick's own schedule: the pace Paul allowed.
LOOKUP_EVERY = 180
#: The Listener's Gale lookups in a tick start within this long of its
#: start. Short, because the next tick's sweep waits on them.
GALE_SECONDS = 60
LOOKED_UP = HOME / "looked_up"


def gale_due(now=None, path=LOOKED_UP):
    """Is a Gale lookup due (LOOKUP_EVERY since the last, a few seconds'
    slack for a tick's start)? Marks it done when it is."""
    now = now or time.time()
    if path.exists() and now - path.stat().st_mtime < LOOKUP_EVERY - 10:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, (now, now))
    return True


def last_render(path=CHECKLIST):
    return path.stat().st_mtime if path.exists() else 0


@contextlib.contextmanager
def locked(wait=True):
    """Held while a mirror is written: the tick and the full pass's syncs
    take turns. With `wait` False, yields False at once when another holds
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
    logged a download since the last (or RENDER_EVERY passed); then the
    Listener's (gale_listener.tick); then start the full pass if none runs
    to read the editions tools/gale_fetch.py laid out (kick). Skipped when
    another sync is running."""
    import gale_listener  # imports this module, so not at the top
    with locked(wait=False) as mine:
        if not mine:
            # Another sync is doing this same work: waiting behind it ran a
            # tick past its 900 s limit.
            print("another sync holds the lock; this one skips", file=out)
            return
        _TICK_HELD[:] = [fa.held_dates(fa.TIMES.series)]
        dir_cache.load(DIR_CACHE)
        try:
            _sync_locked(out, force, gale_listener)
        finally:
            _TICK_HELD.clear()
            dir_cache.save(DIR_CACHE)
    kick(out)


def _sync_locked(out, force, gale_listener):
    """sync's work under the lock."""
    listener_changed = gale_listener.arrivals(out)
    ask = gale_due()
    if (force or time.time() - last_render() > RENDER_EVERY
            or (FETCHED.exists() and FETCHED.stat().st_mtime > last_render())):
        CHECKLIST.parent.mkdir(parents=True, exist_ok=True)
        CHECKLIST.write_text(checklist())
        publish()
        print(f"progress page published to {GALE_ROOT}/{CHECKLIST_NAME}", file=out)
    gale_listener.tick(out, force, ask, time.monotonic() + GALE_SECONDS, listener_changed)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sy = sub.add_parser("sync", help="publish the progress page, tick the Listener, start the full pass")
    sy.add_argument("--render", action="store_true", help="publish even when nothing was downloaded")
    cl = sub.add_parser("checklist", help="write the progress page")
    cl.add_argument("--out", type=Path, default=CHECKLIST)
    sub.add_parser("shrink", help="lay out smaller every staged leaf over MAX_PAGE_PIXELS (its edition comes due)")
    a = ap.parse_args(argv)
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
