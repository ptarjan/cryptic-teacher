#!/usr/bin/env python3
"""The London Times editions of 1974-99 archive.org holds no scan of, read
from the crossword pages Paul downloads BY HAND from Gale's Times Digital
Archive (through the Alberta Research Portal).

Only tools/gale_docs.py asks Gale anything: each sync looks up the next
editions' document ids, so their rows link straight to Gale's Download. This
writes a checklist of the editions to fetch, and lays
each page Paul saves into his inbox out as one more Times edition for
tools/file_archive_org_puzzles.py, which reads it like any scan: our
readers' and the VLM's readings voted on, the Canberra reprint's beside them.

    python3 tools/gale_inbox.py sync [--render]   # sweep Gale files in, mirror, stage, publish the checklist
    python3 tools/gale_inbox.py stage --inbox DIR # stage a local folder of pages (no Mac)
    python3 tools/gale_inbox.py checklist [--out FILE]
    python3 tools/gale_inbox.py match FILE...     # which edition each file is, and how that was read

Paul only presses Gale's Download. Every minute (the cryptic-gale-inbox
plugin) sync sweeps each Gale file out of the Windows desktop's and the Mac's
Downloads, and any page saved straight into GALE_ROOT, into its paper's inbox
(INBOXES), recognised by Gale's document id in its name or Gale's citation in
its text and routed by the archive that citation names; nothing else there is
touched. The Times inbox is HOST_INBOX on the Mac, reached over the
container's ssh hatch; its mirror is MIRROR. A file is matched to its edition by the date in its
name, else the puzzle number in its name, else the date a Gale PDF's
citation prints, else the number our readers read in its title ("The Times
Crossword Puzzle No 17,563"); a number gives the date its filed neighbours
put it on. Every page of one date is one edition directory,
CACHE/GaleTimes<year>UKEnglish/<date>, its leaves scaled to an archive.org
scan's grid size; its sources-<key>.json is named for what the inbox holds
for that date, so a file added or replaced changes the edition's files
(input_hash, the first part of file_archive_org_puzzles.inputs_of) and makes
that edition, and no other, due. An edition laid out in the last FRESH
seconds is read within minutes: sync starts tools/gale_read.sh for it
(fresh_unread), which files it under the Gale pages' own ledger
(file_archive_org_puzzles.GALE); the full pass reads the rest, the Gale
slices first.
"""
import argparse
import bisect
import collections
import contextlib
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

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import archive_coverage
import code_reach
import file_archive_org_puzzles as fa
import gale_arrived
import gale_docs
import pypdf

HOST = os.environ.get("GALE_INBOX_HOST", "pt@host.docker.internal")
#: The Mac folder every Gale page lands in, on the Media disk: the SMB share
#: "Media", Z: on the Windows desktop (SHARE). A page saved straight into it,
#: or a Gale file found in either machine's Downloads, is moved into its
#: paper's folder (INBOXES); each paper's checklist is written into it.
GALE_ROOT = "/Volumes/Media/Gale crosswords"
SHARE = r"Z:\Gale crosswords"
INBOXES = {"times": f"{GALE_ROOT}/Times", "listener": f"{GALE_ROOT}/Listener"}
HOST_INBOX = INBOXES["times"]
LISTENER_INBOX = INBOXES["listener"]
CHECKLIST_NAME = "Checklist.html"
#: Where the desktop's Chrome saves downloads (Z:\Downloads\chrome): swept
#: like Downloads, at any age.
CHROME = "/Volumes/Media/Downloads/chrome"
#: The Windows desktop Paul browses Gale on; its Downloads is swept too.
DESKTOP = os.environ.get("GALE_DESKTOP", "micro@100.68.145.15")
#: A Downloads file older than this is not looked at: Gale files are swept
#: within minutes of landing, and older ones are Paul's own.
RECENT_DAYS = 2
#: A file this new may still be being written.
SETTLE_SECONDS = 15
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "HostKeyAlias=localhost",
       "-i", os.path.expanduser("~/.ssh/host_hatch")]
MIRROR = Path(os.path.expanduser("~/.cache/gale_inbox/files"))
CHECKLIST = Path(os.path.expanduser("~/.cache/gale_inbox")) / CHECKLIST_NAME
UNMATCHED = MIRROR.parent / "unmatched.json"
#: Each inbox file's match, by name, size and mtime: a tick re-reads only what moved.
MATCHES = MIRROR.parent / "matches.json"
#: The code match() reaches: a change to it re-reads every file.
MATCHER = code_reach.key("gale_inbox", {"match"})[:12]
#: The most seconds a stage spends matching files afresh: a code change
#: re-reads every file (minutes each batch), and the minute tick must stay
#: short. Files never matched go first, so a fresh download is never queued
#: behind re-reads; a file not re-read yet keeps its last match (same name,
#: size and mtime, under the code before).
MATCH_SECONDS = 60
#: The Downloads files already looked at and found not to be Gale's.
SEEN = MIRROR.parent / "seen.json"
LOCK = MIRROR.parent / "sync.lock"
#: A tick re-renders the checklist when the inbox moved, else this often,
#: so a puzzle the full pass filed leaves it.
RENDER_EVERY = 3600
#: An edition laid out this recently is read by tools/gale_read.sh (READ_JOB),
#: started by the tick that sees it unread; one laid out before is the full
#: pass's. An hour covers a run that ended early or a host that was down.
FRESH = 3600
READ_JOB = TOOLS / "gale_read.sh"
READ_LOG = Path(os.path.expanduser("~/.cache/gale_read.log"))
CACHE = fa.CACHE
ITEM = "GaleTimes{}UKEnglish"
PAGES = gale_arrived.PAGES
YEARS = range(1974, 2000)
#: The classes of an edition the checklist asks for: no archive.org scan.
WANTED = ("no-scan", "canberra-reprint")
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
DOC_ID, BARE_DOC = gale_arrived.DOC_ID, gale_arrived.BARE_DOC
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


DATES = date_patterns(r"19[789]\d")
#: A Times cryptic number of 1974-99 (13,676 to ~21,400); Times issue
#: numbers (59,000-66,000) and Gale document ids never fall in it.
NUMBER = re.compile(r"(?<![\d,.])(1[3-9]|2[01])[,.]?(\d{3})(?![\d,])")
#: The citation a Gale PDF prints: "The Times, 12 Jan. 1988, p. 18", or
#: its download's citation page, the article's title quoted first:
#: '"The Times Crossword Puzzle No 17,244." Times, 3 Jan. 1987, p. 20.'
CITED = re.compile(r'(?:"[^"]{0,200}"\s*(?:The\s+)?Times|The Times[^,]{0,40}),\s*(?:\w+,\s*)?([0-3]?\d)\s+' + MON
                   + r"\s*(19[789]\d)(?:,\s*p\.?\s*(\d+))?", re.IGNORECASE)
#: The article title a Gale download's citation page quotes: '"Concise
#: Crossword No 1154." Times, 13 Jan. 1987'.
CITED_TITLE = re.compile(r'"([^"]{1,200}?)\.?"\s*(?:The\s+)?Times,')


# ------------------------------------------------------------ numbers and dates

def held():
    """{number: date} of every filed Times puzzle."""
    return fa.held_dates(fa.TIMES.series)


#: Every date the Times printed in YEARS (archive_coverage.PRINTED: no
#: Sundays, no Christmas Day, none in the 1978-79 shutdown), and each one's
#: place in that run.
PRINTED = [datetime.date.fromisoformat(d) for d in archive_coverage.printed_dates("times", datetime.date(2000, 1, 31))
           if d >= "1973"]
ISSUE = {d: i for i, d in enumerate(PRINTED)}


_SORTED = {}


def _sorted(by_number):
    """(by date, by number): the filed (number, date) pairs on a printed
    date, sorted each way; kept per mapping, which checklist asks thousands
    of times."""
    k = (id(by_number), len(by_number))
    if k not in _SORTED:
        pairs = [(m, d) for m, d in by_number.items() if d in ISSUE]
        _SORTED.clear()
        _SORTED[k] = (sorted(pairs, key=lambda p: p[1]), sorted(pairs))
    return _SORTED[k]


def neighbours(value, by_number, field):
    """The filed (number, date) either side of `value`, a date (field 1) or
    a number (field 0); one equal to it is neither."""
    rows = _sorted(by_number)[1 - field]
    keys = [r[field] for r in rows]
    lo, hi = bisect.bisect_left(keys, value), bisect.bisect_right(keys, value)
    return (rows[lo - 1] if lo else None), (rows[hi] if hi < len(rows) else None)


def number_on(day, by_number):
    """(number, sure) of the Times cryptic printed on `day`: sure when the
    printed issues counted from the filed puzzles either side agree, else
    the issues counted from the nearer one."""
    lo, hi = neighbours(day, by_number, 1)
    up = lo and lo[0] + ISSUE[day] - ISSUE[lo[1]]
    down = hi and hi[0] - (ISSUE[hi[1]] - ISSUE[day])
    if up and down:
        return (up, True) if up == down else ((up, False) if day - lo[1] <= hi[1] - day else (down, False))
    return (up or down or fa.expected_number(day)), False


def day_of(number, by_number):
    """The date No `number` printed on, or None: the printed issues counted
    from the filed puzzles either side must agree on it."""
    lo, hi = neighbours(number, by_number, 0)
    if not lo or not hi:
        return None
    up, down = ISSUE[lo[1]] + number - lo[0], ISSUE[hi[1]] - (hi[0] - number)
    return PRINTED[up] if up == down and 0 <= up < len(PRINTED) else None


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


def name_number(name):
    """The Times cryptic number a file name spells, or None."""
    m = NUMBER.search(DOC_ID.sub(" ", name))
    return int(m.group(1) + m.group(2)) if m else None


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


def scaled(img):
    """(`img` as an archive.org page holds a puzzle, whether a grid was found
    on it): scaled so its widest grid is GRID_WIDTH wide (unscaled when none
    is found) and set on a white page SCAN_WIDTH wide, the size the filer's
    pixel spans are set at. A whole page (Gale's page download) is read at
    an archive.org page's width first, where a photo or a table is too big
    to pass for its grid; a clipping, its widest square patch of ink."""
    from PIL import Image
    at = fa.SCAN_WIDTH / img.width
    grids = [[v / at for v in b] for b in fa.grids_on(img.resize((fa.SCAN_WIDTH, round(img.height * at))))] \
        or fa.grids_on(img, shaped=square)
    if grids:
        k = GRID_WIDTH / max(b[2] - b[0] for b in grids)
        if abs(k - 1) >= 0.05:
            img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    page = Image.new("RGB", (max(fa.SCAN_WIDTH, img.width + 2 * MARGIN), img.height + 2 * MARGIN), "white")
    page.paste(img, (MARGIN, MARGIN))
    return page, bool(grids)


#: Only breaks a tie between readers who read different title numbers.
MID_DAY = datetime.date(1987, 1, 1)


def title_number(img, key):
    """The puzzle number our readers read in a page's title, or None: in the
    filer's bands by each grid, else anywhere a grid's height over it (the
    Saturday prize puzzle's entry form sets its title ~500px up)."""
    found = fa.ocr_titles(img, fa.TIMES, MID_DAY, key)
    if found:
        return found[0][0]
    for i, (x0, y0, x1, y1) in enumerate(fa.grids_on(img)):
        w = x1 - x0
        above = img.crop((max(0, x0 - w // 2), max(0, y0 - (y1 - y0)), min(img.width, x1 + w // 2), y0))
        titles, _ = fa.ocr_headings(above, fa.TIMES, f"{key}_over{i}")
        if titles:
            return titles[0][0]
    return None


def doc_id(name, cite=""):
    """The Gale document a saved file is, off its name (DOC_ID, BARE_DOC) or
    its citation's permalink (CITED_DOC), upper-cased; None when neither
    names one."""
    m = CITED_DOC.search(cite or "")
    return gale_arrived.name_doc(name) or (m.group(1).upper() if m else None)


def edition_url(ms):
    """A laid-out edition's pages.json "url": its first named document's
    page at Gale (a match made before doc_id read bare names is named off
    its file now), else the portal."""
    doc = next((d for m in ms if (d := m.get("docId") or doc_id(m["file"]))), None)
    return DOC_URL.format(doc) if doc else PORTAL


def match(path, by_number):
    """{"date", "number", "how", "page", "docId", "pages": [image]} for a
    saved file; "date" None (and "why") when nothing names its edition."""
    name = path.name
    out = {"file": name, "page": None}
    read = images(path)
    laid = [scaled(img) for img, _ in read]
    pages = out["pages"] = [page for page, _ in laid]
    out["grid"] = any(found for _, found in laid)
    cite = read[0][1] if read else ""
    out["docId"] = doc_id(name, cite)
    t = CITED_TITLE.search(cite or "")
    out["cited"] = t and t.group(1).strip()
    day, number = name_date(name), name_number(name)
    if day:
        out.update(date=day, how="file name date")
    elif number:
        out.update(number=number, how="file name number")
    else:
        m = CITED.search(cite or "")
        if m:
            out.update(date=datetime.date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1))),
                       how="PDF citation", page=int(m.group(4)) if m.group(4) else None)
        else:
            key = "gale_" + hashlib.sha1(name.encode()).hexdigest()[:12]
            number = next((n for i, img in enumerate(pages) if (n := title_number(img, f"{key}_{i}"))), None)
            if number:
                out.update(number=number, how="title read")
    if "date" not in out and out.get("number"):
        out["date"] = day_of(out["number"], by_number)
        if out["date"] is None:
            out["why"] = f"No {out['number']}: the filed puzzles either side do not run unbroken, so no date"
    if "date" not in out:
        out.update(date=None, why="no date or number in the name, citation or title")
    if not pages:
        out.update(date=None, why="no page image in the file")
    return out


def match_anywhere(path, by_number):
    """match(path, by_number) run on the desktop when tools/ocr_remote.py
    can (the file's bytes sent; the same match and the same pages back, the
    title readings it cached written under CROPS), else here in
    local_slot()."""
    import ocr_remote
    from PIL import Image
    got = ocr_remote.call("gale_match", path.name, {n: d.isoformat() for n, d in by_number.items()},
                          data=path.read_bytes())
    if got is None:
        with ocr_remote.local_slot():
            return match(path, by_number)
    (got, back), at, pages = got, 0, []
    for n in got["pages"]:
        page = Image.open(io.BytesIO(back[at:at + n]))
        page.load()
        pages.append(page)
        at += n
    with tarfile.open(fileobj=io.BytesIO(back[at:])) as t:
        t.extractall(fa.CROPS, filter="data")
    m = got["match"]
    return {**m, "date": m["date"] and datetime.date.fromisoformat(m["date"]), "pages": pages}


#: What a Windows file name cannot hold.
NOT_IN_NAMES = set('<>:"/\\|?*')


def match_there(data, name, held):
    """tools/ocr_remote.py's "gale_match", run on the desktop: ({"match":
    match() of the saved file `data` named `name`, its date ISO, "pages":
    [PNG length]}, the pages' PNGs then a tar of the title readings it
    cached), `held` its {number: ISO date}; raises when it opened a file it
    was not sent."""
    import gc
    import tempfile

    import ocr_remote
    if NOT_IN_NAMES & set(name):
        raise ValueError(f"{name!r} cannot be a file name there")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        path = root / name
        path.write_bytes(data)
        crops, sent = ocr_remote.sent_crops(root)
        fa.CROPS = crops
        ocr_remote._WATCH[:] = [(str(root), str(TOOLS.parent)), []]
        try:
            m = match(path, {int(n): datetime.date.fromisoformat(d) for n, d in held.items()})
        finally:
            missing, ocr_remote._WATCH[:] = ocr_remote._WATCH[1], [None, []]
        if missing:
            raise FileNotFoundError("opened files it was not sent: " + ", ".join(sorted(set(missing))[:5]))
        pngs = []
        for page in m.pop("pages"):
            buf = io.BytesIO()
            page.save(buf, format="PNG", compress_level=1)  # lossless: the Mac lays out these pixels
            pngs.append(buf.getvalue())
        m["date"] = m["date"] and m["date"].isoformat()
        gc.collect()  # closes the file, which Windows will not delete open
        return {"match": m, "pages": [len(p) for p in pngs]}, b"".join(pngs) + ocr_remote.changed(crops, sent)


# ------------------------------------------------------------ staging

def source_key(files):
    """What the inbox holds for one date, by name, size and content."""
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(f"{p.name}:{p.stat().st_size}:".encode() + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:16]


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
    edition only relinked is no fresh page for tools/gale_read.sh."""
    row = json.loads(pages.read_text())
    if row.get("url") == url:
        return
    st = pages.stat()
    tmp = pages.with_name(pages.name + ".tmp")
    tmp.write_text(json.dumps({**row, "url": url}, indent=1))
    os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
    tmp.replace(pages)


def stage(inbox=MIRROR, cache=CACHE, out=sys.stdout, unmatched=UNMATCHED, matches=MATCHES,
          seconds=MATCH_SECONDS):
    """Lay each date's pages in `inbox` out as one edition directory under
    `cache` (re-laid only when what the inbox holds for it moved; a date
    the inbox no longer holds is removed); the files that matched no
    edition are listed in `unmatched`. {date: [match]}; the unmatched
    under None."""
    by_number = held()
    files = sorted(p for p in Path(inbox).iterdir() if p.is_file() and p.suffix.lower() in PAGES) \
        if Path(inbox).exists() else []
    known, kept = load(matches, {}), {}
    #: Each file's match under any code, by name, size and mtime.
    stale = {k.split("\t", 1)[1]: v for k, v in known.items()}
    by_date = collections.defaultdict(list)
    deadline = time.monotonic() + seconds
    deferred = 0
    idents = {p: f"{p.name}\t{p.stat().st_size}\t{int(p.stat().st_mtime)}" for p in files}
    for p in sorted(files, key=lambda p: idents[p] in stale):
        ident = idents[p]
        k = f"{MATCHER}\t{ident}"
        m = known.get(k)
        if m is None and time.monotonic() > deadline:
            m = stale.get(ident)
            deferred += 1
            if m is None:
                continue
            k = next(key for key in known if key.endswith("\t" + ident))
        elif m is None:
            try:
                m = match_anywhere(p, by_number)
            except (OSError, ValueError, pypdf.errors.PyPdfError) as e:  # reported, not fatal
                m = {"file": p.name, "date": None, "why": f"unreadable: {type(e).__name__}: {e}", "pages": []}
            m["date"] = m["date"] and m["date"].isoformat()
            # Kept as it goes: a tick killed mid-way loses one file's match.
            known[k] = {f: v for f, v in m.items() if f != "pages"}
            save_json(matches, known)
        kept[k] = {f: v for f, v in m.items() if f != "pages"}
        m = dict(m, path=p, date=m["date"] and datetime.date.fromisoformat(m["date"]))
        by_date[m["date"]].append(m)
    save_json(matches, kept)
    if deferred:
        print(f"{deferred} file(s) left to match next tick (MATCH_SECONDS)", file=out)
    staged = set()
    for day, ms in by_date.items():
        if day is None:
            continue
        d = cache / ITEM.format(day.year) / day.isoformat()
        staged.add(d)
        key = source_key([m["path"] for m in ms])
        if (d / f"sources-{key}.json").exists():
            relink(d / "pages.json", edition_url(ms))
            continue
        # Laid out beside it and swapped in, so a reader of the edition sees
        # the old one or the new, not half of each.
        tmp = d.with_name(d.name + ".new")
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        leaves = []
        for m in ms:
            pages = m.get("pages")
            if pages is None:
                pages = match_anywhere(m["path"], by_number)["pages"]
            for img in pages:
                leaf = len(leaves)
                img.save(tmp / f"leaf_{leaf:04d}.jpg", quality=92)
                leaves.append({"leaf": leaf, "width": img.width, "height": img.height, "file": m["file"]})
        item = ITEM.format(day.year)
        (tmp / "pages.json").write_text(json.dumps({
            "item": item, "edition": day.isoformat(), "date": day.isoformat(), "leaves": len(leaves),
            "crossword_pages": leaves, "url": edition_url(ms)}, indent=1))
        (tmp / f"sources-{key}.json").write_text(json.dumps(
            [{k: (v.isoformat() if isinstance(v, datetime.date) else v) for k, v in m.items()
              if k not in ("pages", "path")} for m in ms], indent=1))
        if d.exists():
            shutil.rmtree(d)
        tmp.rename(d)
        print(f"staged {item}/{day} from {', '.join(m['file'] for m in ms)} ({ms[0]['how']})", file=out)
    unmatched.parent.mkdir(parents=True, exist_ok=True)
    unmatched.write_text(json.dumps([{"file": m["file"], "why": m.get("why", "")} for m in by_date.get(None, ())]
                                    + [{"file": m["file"], "date": day.isoformat(), "why": "no crossword grid found on it"}
                                       for day, ms in by_date.items() if day for m in ms if m.get("grid") is False],
                                    indent=1))
    for item in cache.glob(ITEM.format("*")):
        for d in item.iterdir():
            if d.is_dir() and d.name.endswith(".new"):
                shutil.rmtree(d)  # a lay-out a killed tick left half done
            elif deferred:
                continue  # a file not matched yet may hold this date
            elif d.is_dir() and d not in staged:
                shutil.rmtree(d)
                print(f"removed {item.name}/{d.name}: no longer in the inbox", file=out)
    return dict(by_date)


# ------------------------------------------------------------ the Mac's inbox

#: An ssh to the Mac that has not answered in this long is dead: the tick
#: fails (and the next retries) rather than hold its plugin's 900 s limit.
SSH_SECONDS = 120


def ssh(command, **kw):
    return subprocess.run(SSH + [HOST, command], check=True, capture_output=True, timeout=SSH_SECONDS, **kw)


def mirror(out=sys.stdout, host_inbox=HOST_INBOX, into=MIRROR):
    """Copy the Mac inbox's page files to `into`: the new and changed ones;
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


#: The Mac's arrival watcher (tools/gale_arrived.py): its copy of the
#: script, its launchd job and log. The sync installs them, and again
#: whenever this tree's script or job differs from what it last installed.
MAC_HOME = "/Users/pt"
WATCHER = f"{MAC_HOME}/.local/lib/gale-arrived/gale_arrived.py"
WATCHER_PLIST = f"{MAC_HOME}/Library/LaunchAgents/{gale_arrived.LABEL}.plist"
WATCHER_LOG = f"{MAC_HOME}/Library/Logs/gale-arrived.log"
WATCHER_PYTHON = "/usr/local/bin/python3"
#: The folders a Gale download lands in on the Mac (collect sweeps them).
WATCHED = (CHROME, f"{MAC_HOME}/Downloads")
WATCHER_STAMP = MIRROR.parent / "watcher.sha"


def install_watcher(out=sys.stdout, run=None, stamp=WATCHER_STAMP):
    """Install the arrival watcher on the Mac when what this tree would
    install differs from the last install; reload its job only when the job
    itself changed. Whether it installed."""
    code = (TOOLS / "gale_arrived.py").read_bytes()
    job = gale_arrived.plist(WATCHER_PYTHON, WATCHER, WATCHED, f"{GALE_ROOT}/{gale_arrived.NAME}", WATCHER_LOG)
    want = hashlib.sha256(code + job.encode()).hexdigest()
    if load(stamp, None) == want:
        return False
    q, run, label = shlex.quote, run or ssh, f"gui/$(id -u)/{gale_arrived.LABEL}"
    run(f"mkdir -p {q(str(Path(WATCHER).parent))} && cat > {q(WATCHER + '.tmp')} && mv -f {q(WATCHER + '.tmp')} {q(WATCHER)}",
        input=code)
    # bootout returns before the job is gone, so bootstrap waits for it.
    new = q(WATCHER_PLIST + ".new")
    run(f"cat > {new} && if cmp -s {new} {q(WATCHER_PLIST)} && launchctl print {label} >/dev/null 2>&1; "
        f"then rm -f {new}; else mv -f {new} {q(WATCHER_PLIST)}; launchctl bootout {label} 2>/dev/null; "
        f"for i in $(seq 40); do launchctl print {label} >/dev/null 2>&1 || break; sleep 0.25; done; "
        f"launchctl bootstrap gui/$(id -u) {q(WATCHER_PLIST)}; fi", input=job.encode())
    save_json(stamp, want)
    print(f"installed the arrival watcher ({gale_arrived.LABEL}) on the Mac", file=out)
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


def paper_of(name, text):
    """Which inbox ("times", "listener") a Gale file belongs in: its
    citation's archive, else a paper its name or text names; else the Times,
    which most of what is asked for is."""
    for rx, paper in ((r"Listener Historical Archive", "listener"), (r"Times Digital Archive", "times"),
                      (r"\bThe Listener\b", "listener"), (r"\bThe Times\b", "times")):
        if re.search(rx, text):
            return paper
    return "listener" if re.search(r"listener", name, re.IGNORECASE) else "times"


def classify(name, text, dropped):
    """The inbox a file goes to, or None to leave it alone. A page file put
    in the drop folder is Paul's for Gale whatever it holds; one in Downloads
    only when it is recognisably Gale's."""
    if Path(name).suffix.lower() not in PAGES:
        return None
    if dropped or is_gale(name, text):
        return paper_of(name, text)
    return None


def needs_text(name, dropped):
    """Must a file's bytes be read to place it? A PDF's citation says which
    paper it is; an image in Downloads is Gale's only by its name."""
    suffix = Path(name).suffix.lower()
    return suffix == ".pdf" if dropped else (suffix == ".pdf" and not DOC_ID.search(name))


def free_name(name, taken):
    """`name`, or `name (2)` and on, whichever `taken` does not hold."""
    stem, suffix, i = Path(name).stem, Path(name).suffix, 2
    out = name
    while out in taken:
        out, i = f"{stem} ({i}){suffix}", i + 1
    return out


def load(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def parse_listing(text):
    """[(where, size, mtime, name)] of the `where size mtime name` lines."""
    rows = []
    for line in text.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4 and parts[1].isdigit() and parts[2].lstrip("-").isdigit():
            rows.append((parts[0], int(parts[1]), int(parts[2]), parts[3].removeprefix("./")))
    return rows


def collect(out=sys.stdout, seen_path=SEEN, now=None):
    """Move every Gale file in the drop folder, the Mac's and desktop's
    Downloads and CHROME into its paper's inbox; leave every other file alone. How many
    it moved."""
    now = now or time.time()
    seen = load(seen_path, {})
    q = shlex.quote
    #: where: (its folder in the shell, what the log calls it)
    swept = {"drop": (q(GALE_ROOT), "the drop folder"), "downloads": ('"$HOME"/Downloads', "Mac Downloads"),
             "chrome": (q(CHROME), "Chrome downloads")}
    dirs = {**{w: d for w, (d, _) in swept.items()}, **{p: q(d) for p, d in INBOXES.items()}}
    script = [f"mkdir -p {' '.join(q(d) for d in [GALE_ROOT, *INBOXES.values()])}"]
    for where, place in dirs.items():
        recent = f"-mtime -{RECENT_DAYS}" if where == "downloads" else ""
        script.append(f"(cd {place} 2>/dev/null && find . -maxdepth 1 -type f {recent} "
                      f"-exec stat -f '{where}%t%z%t%m%t%N' {{}} +)")
    rows = parse_listing(ssh("; ".join(script) + "; exit 0", text=True).stdout)
    taken = {paper: {n for w, _, _, n in rows if w == paper} for paper in INBOXES}
    sizes = {(w, n): z for w, z, _, n in rows}
    moves, moved = [], 0

    def place(paper, name, size):
        """The name a file gets in `paper`'s inbox, or None when the same
        file (name and size) is there already."""
        if sizes.get((paper, name)) == size:
            return None
        dest = free_name(name, taken[paper])
        taken[paper].add(dest)
        return dest

    for where, size, mtime, name in rows:
        if where not in swept or now - mtime < SETTLE_SECONDS:
            continue
        key = f"mac:{name}:{size}:{mtime}"
        if key in seen or Path(name).suffix.lower() not in PAGES:
            continue
        dropped = where == "drop"
        src = f"{swept[where][0]}/{q(name)}"
        text = pdf_text(ssh(f"cat {src}").stdout) if needs_text(name, dropped) else ""
        paper = classify(name, text, dropped)
        if paper is None:
            seen[key] = "not Gale"
            continue
        dest = place(paper, name, size)
        if dest is None:
            moves.append(f"rm -f {src}")
            print(f"{name}: already in {paper}, removed the copy", file=out)
        else:
            moves.append(f"mv -n {src} {q(INBOXES[paper] + '/' + dest)}")
            print(f"{name}: moved from {swept[where][1]} to {paper}/{dest}", file=out)
        moved += 1
    if moves:
        ssh(" && ".join(moves))
    moved += collect_desktop(out, seen, place, now)
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(seen, indent=0))
    return moved


def powershell(script, timeout=120):
    """Run a PowerShell script on the desktop; its stdout, or None when the
    desktop is off or unreachable."""
    import base64
    enc = base64.b64encode(("[Console]::OutputEncoding=[Text.Encoding]::UTF8\n" + script)
                           .encode("utf-16-le")).decode()
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", DESKTOP,
                            f"powershell -NoProfile -NonInteractive -EncodedCommand {enc}"],
                           capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return None
    return r.stdout if r.returncode == 0 else None


def ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def collect_desktop(out, seen, place, now):
    """collect for the desktop's Downloads: a Gale file is copied into its
    inbox on the Mac, then deleted from the desktop."""
    downloads = "(Join-Path $env:USERPROFILE 'Downloads')"
    listing = powershell(
        f"Get-ChildItem -LiteralPath {downloads} -File | Where-Object {{ $_.LastWriteTime -gt (Get-Date).AddDays(-{RECENT_DAYS}) }}"
        " | ForEach-Object { \"desktop`t$($_.Length)`t$(([DateTimeOffset]$_.LastWriteTimeUtc).ToUnixTimeSeconds())`t$($_.Name)\" }")
    if listing is None:  # off or asleep, as it is most of the night: swept next time
        return 0
    import base64
    moved = 0
    for _, size, mtime, name in parse_listing(listing):
        key = f"desktop:{name}:{size}:{mtime}"
        if key in seen or Path(name).suffix.lower() not in PAGES or now - mtime < SETTLE_SECONDS:
            continue
        path = f"(Join-Path {downloads} {ps_quote(name)})"
        if not needs_text(name, False) and not DOC_ID.search(name):
            seen[key] = "not Gale"
            continue
        blob = powershell(f"[Convert]::ToBase64String([IO.File]::ReadAllBytes({path}))")
        if blob is None:
            continue
        data = base64.b64decode(blob.strip())
        paper = classify(name, pdf_text(data) if needs_text(name, False) else "", False)
        if paper is None or len(data) != size:
            seen[key] = "not Gale" if paper is None else "short read"
            continue
        dest = place(paper, name, size)
        if dest is not None:
            ssh(f"cat > {shlex.quote(INBOXES[paper] + '/' + dest)}", input=data)
        if powershell(f"Remove-Item -LiteralPath {path}") is None:
            seen[key] = "copied; could not delete"
        print(f"{name}: moved from desktop Downloads to {paper}/{dest or '(already there)'}", file=out)
        moved += 1
    return moved


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
    """[(date, class)] of every 1974-99 Times edition archive.org holds no
    scan of and no puzzle file holds."""
    today = today or datetime.datetime.now().astimezone().date()
    return [(datetime.date.fromisoformat(d), cls) for d, cls, _ in archive_coverage.unfiled(fa.TIMES, today)
            if cls in WANTED and int(d[:4]) in YEARS]


def fresh_unread(cache=CACHE, rows=None, now=None):
    """The "<item>/<date>" of each Gale edition laid out in the last FRESH
    seconds that has no reading of its current files in the ledger."""
    rows = archive_coverage.ledger() if rows is None else rows
    now = time.time() if now is None else now
    out = []
    for pages in cache.glob(ITEM.format("*") + "/*/pages.json"):
        d = pages.parent
        if now - pages.stat().st_mtime > FRESH:
            continue
        row = rows.get(f"{d.parent.name}/{d.name}") or {}
        if "inputs" not in row or row.get("filesHash") != fa.input_hash(d):
            out.append(f"{d.parent.name}/{d.name}")
    return sorted(out)


def start_reads(out=sys.stdout, job=READ_JOB, log=READ_LOG):
    """Start `job` detached when a fresh edition waits to be read; a run
    already reading keeps its tree's lease and the new start exits at once."""
    waiting = fresh_unread()
    if not waiting:
        return None
    log.parent.mkdir(parents=True, exist_ok=True)
    # Without this tick's worktree marks, so the job takes a worktree of its
    # own (tools/nightly_worktree.sh): this tree is reset every tick.
    env = {k: v for k, v in os.environ.items() if k not in ("CT_IN_WORKTREE", "CT_MAIN_CHECKOUT")}
    with open(log, "a") as f:
        p = subprocess.Popen(["bash", str(job)], stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True, close_fds=True, env=env)
    print(f"started {job.name} (pid {p.pid}) for {len(waiting)} fresh edition(s): {', '.join(waiting[:5])}; "
          f"log {log}", file=out)
    return p


def staged_matches(cache=CACHE):
    """{date: [match]} of the inbox pages staged as editions (stage's
    sources-*.json)."""
    return {datetime.date.fromisoformat(src.parent.name): json.loads(src.read_text())
            for src in cache.glob(ITEM.format("*") + "/*/sources-*.json")}


def staged_files(cache=CACHE):
    """{date: [file name]} of the inbox pages staged as editions."""
    return {day: [m["file"] for m in ms] for day, ms in staged_matches(cache).items()}


#: The checklist's "next up": BATCH rows shown at a time, refilled from a
#: POOL rendered so a click needs no new render; Download links are looked
#: up (gale_docs.resolve, at its pace) for every wanted edition, in next-up
#: order (LOOKAHEAD None: all), so every row has one, not just next up's;
#: next up shows the linked rows first (page).
BATCH = 15
POOL = 60
LOOKAHEAD = None


#: A row clicked this long ago whose file has not arrived turns amber: the
#: download may have failed.
LATE_MINUTES = 15
#: How long a clicked row stays in next up before it moves to Clicked and
#: the next row takes its place.
MOVE_SECONDS = 3
#: How often an open checklist reads its status file (status_js).
POLL_SECONDS = 5
#: A status file older than this is not being written: the page falls back
#: to reloading itself every RELOAD_SECONDS. A sync publishes it at its start
#: and end, and between them spends up to two Gale allowances (GALE_SECONDS
#: each) plus staging, so this must exceed that.
STALE_SECONDS = 720
RELOAD_SECONDS = 180


def script(store, status_src, stamp, arrived_src=gale_arrived.NAME):
    """The checklists' row state. A row is one of: to fetch (its Download
    button), clicked and waiting for its file ("downloading... clicked
    HH:MM", an undo, no Download), clicked LATE_MINUTES ago with no file
    (amber, a retry), downloaded (a document its row's links name is in
    `arrived_src`, the Mac's arrival watcher's, tools/gale_arrived.py:
    seconds after the file lands, and counted then), or arrived ("in the
    inbox", the sync's). Clicks are kept in the
    browser (localStorage `store`, key: when) so a reload keeps them; what
    arrived is the page's own data-in and its status file (status_js),
    read with `arrived_src` every POLL_SECONDS by a script tag, which a file:// page may load
    where it may not fetch. A status naming a newer page reloads it once;
    a status that stops coming reloads the page every RELOAD_SECONDS. #next
    shows the first BATCH rows not clicked: a row clicked MOVE_SECONDS ago
    (or arrived) moves to #done, under "Clicked", and the next takes its
    place; the first one to fetch is highlighted. A click anywhere on a row
    to fetch is a click on its Download (a.dl). A middle click on a link opens a tab
    without a click event, so it runs the link's onclick (the mark) itself."""
    js = """<script>
const S=STORE,C=S+'At',BATCH=SIZE,MOVE=MOVESEC*1e3,LATE=LATEMIN*60e3,PAGE=STAMP,SRC=SOURCE,ASRC=ARRIVALS,
  LOADED=Date.now();
let IN=new Set(),AT=PAGE*1000,ARR={},BASE=null,GOT=0;
function get(n){return JSON.parse(localStorage.getItem(n)||'[]')}
function clicks(){const v=localStorage.getItem(C);if(v)return JSON.parse(v);const m={};get(S).forEach(k=>m[k]=0);return m}
function keep(m){localStorage.setItem(C,JSON.stringify(Object.fromEntries(
  Object.entries(m).sort((a,b)=>a[1]-b[1]).slice(-5000))))}
function hm(t){return t?new Date(t).toTimeString().slice(0,5):'earlier'}
function state(r,m,now){const k=r.dataset.k;if(r.dataset.in||IN.has(k))return'in';
  if((r.dataset.doc||'').split(' ').some(d=>d&&d in ARR))return'got';
  return k in m?(now-m[k]>LATE?'late':'wait'):''}
function badge(r,s,t){const b=r.querySelector('.st');if(!b||b.dataset.s===s+t)return;b.dataset.s=s+t;b.className='st '+s;
  const k=r.dataset.k,u=' <a href="#" onclick="unmark(\\''+k+'\\');return false">undo</a>',
    a=r.querySelector('a.dl')||r.querySelector('a.go');
  b.innerHTML=s==='in'?'&#10003; in the inbox':s==='got'?'&#10003; downloaded, checking&hellip;':s==='wait'?'downloading&hellip; clicked '+hm(t)+u
    :s==='late'?'clicked '+hm(t)+', not arrived: <a class="retry" target="gale" onclick="mark(\\''+k+'\\')">retry?</a>'+u:'';
  const x=b.querySelector('a.retry');if(x&&a)x.href=a.href}
function show(){const m=clicks(),now=Date.now(),got=new Set();let n=0,c=0,lit=false;
  document.querySelectorAll('tr[data-k]').forEach(r=>{const s=state(r,m,now);r.dataset.s=s;if(s==='got')got.add(r.dataset.k);
    for(const c of['wait','late','got','in'])r.classList.toggle('s-'+c,s===c);
    badge(r,s,m[r.dataset.k]||0);r.classList.toggle('dlrow',!s&&!!r.querySelector('a.dl'))});
  const nx=document.getElementById('next'),dn=document.getElementById('done');
  if(nx&&dn){[...document.querySelectorAll('tr[data-i]')].sort((a,b)=>a.dataset.i-b.dataset.i).forEach(r=>{
    const s=r.dataset.s,gone=!!s&&(s==='in'||s==='got'||now-(m[r.dataset.k]||0)>=MOVE);
    (gone?dn:nx).tBodies[0].appendChild(r);
    if(gone){c++;r.hidden=false;r.classList.remove('next');return}
    const on=n<BATCH;if(on)n++;r.hidden=!on;const x=on&&!lit&&!s;r.classList.toggle('next',x);if(x)lit=true});
    document.getElementById('clicked').hidden=!c}
  GOT=got.size;count();const mo=document.getElementById('more');if(mo)mo.hidden=n>0;
  const a=document.getElementById('age'),old=now-AT>STALE*1e3;
  if(a){a.textContent='Arrivals last checked '+hm(AT)+' ('+Math.round((now-AT)/60e3)+' min ago)'
    +(old?': the status file is not updating, so this page reloads itself every 3 minutes':'; this page updates itself.');
    a.classList.toggle('old',old)}}
function mark(k){const m=clicks();m[k]=Date.now();keep(m);show();setTimeout(show,MOVE+50)}
function unmark(k){const m=clicks();delete m[k];keep(m);show()}
function count(){const s=BASE;if(!s||s.done==null)return;const d=Math.min(s.done+GOT,s.total),
  p=document.getElementById('prog'),f=n=>n.toLocaleString('en');
  if(p){p.value=d;p.max=Math.max(s.total,1)}
  const c=document.getElementById('count');if(c)c.textContent=f(d)+' of '+f(s.total);
  const t=document.getElementById('togo');if(t)t.textContent=f(s.total-d)}
function galeArrived(a){ARR=a||{};show()}
function galeStatus(s){IN=new Set(s.in);AT=s.at*1000;BASE=s;
  if(s.page>PAGE&&sessionStorage.getItem(S+'Page')!==String(s.page)){
    sessionStorage.setItem(S+'Page',s.page);location.reload()}else show()}
function load(u){const x=document.createElement('script');x.src=u+'?'+Date.now();
  x.onload=x.onerror=()=>x.remove();document.head.appendChild(x)}
function poll(){load(SRC);load(ASRC)}
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
    for k, v in (("STORE", json.dumps(store)), ("SOURCE", json.dumps(status_src)), ("ARRIVALS", json.dumps(arrived_src)), ("SIZE", str(BATCH)),
                 ("LATEMIN", str(LATE_MINUTES)), ("STAMP", str(stamp)), ("STALE", str(STALE_SECONDS)),
                 ("RELOAD", str(RELOAD_SECONDS)), ("POLL", str(POLL_SECONDS)), ("MOVESEC", str(MOVE_SECONDS))):
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
.st.wait{background:#dde8f6;color:#123}.st.got{background:#bfe6c8;color:#063}.st.late{background:#ffc24d;color:#4a2c00}.st.in{background:#17803a;color:#fff}
.st a{color:inherit}tr.s-wait .acts,tr.s-late .acts,tr.s-got .acts,tr.s-in .acts{display:none}tr.s-in td{color:#777}
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
               + f'<a class="go" href="{e(r["search"])}" target="gale"{"" if dl else mk}>Open in Gale</a>'
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
    rows)]. Rows are _row's; `columns` the paper's own, between the row's
    Download and its status; `steps` the paper's own items of the how-to
    and `order` how next up is ordered (inline HTML). Next up is the first
    POOL of `next_rows` with a Download link first, in their order, so a
    click on any row it shows downloads; one with none (no lookup yet, or
    Gale has none) follows them. `status`, when given, gets the page's stamp
    and arrived rows, for publish_status."""
    e = html.escape
    next_rows = ([r for r in next_rows if r.get("dl")] + [r for r in next_rows if not r.get("dl")])[:POOL]
    stamp = int(time.time())
    every = [r for r in next_rows] + [r for _, _, rs in years for r in rs]
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
Showing {min(BATCH, len(next_rows))} of the next {len(next_rows)} {e(what)}. A row you click moves down to <i>Clicked</i>
a moment later and the next one takes its place. The highlighted row is the one to do next.</p>
<p id="more" hidden>All of these are clicked: <b>Refresh</b> once they arrive for more.</p>
<table id="next">{head}""")
        out += [_row(dict(r, i=i)) for i, r in enumerate(next_rows)]
        out.append(f"""</table>
<div id="clicked" hidden><h3>Clicked</h3><p>Downloading or already in the inbox.</p>
<table id="done">{head}</table></div>""")
    out.append(f"<h2>Everything, by year</h2><p>{e(years_note)}</p>")
    for y, summary, rs in years:
        out.append(f"<details><summary><b>{y}</b>: {e(summary)}</summary><table>{head}")
        out += [_row(r) for r in rs]
        out.append("</table></details>")
    return "\n".join(out) + "\n"

def search_for(n):
    """What to type in Gale's search box for Times cryptic No `n`."""
    return f'"Crossword Puzzle No {n:,}"'


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


def titleless(staged, ledger, cache=CACHE):
    """{date: [match]} of the staged editions whose current files
    (input_hash) the filer's current scan code (scan_current) scanned and
    read no Times Crossword title on; a scan that failed is no reading.
    `staged` is staged_matches'."""
    out = {}
    for day, ms in staged.items():
        d = cache / ITEM.format(day.year) / day.isoformat()
        row = ledger.get(f"{d.parent.name}/{d.name}") or {}
        scan = row.get("scan") or {}
        if d.exists() and fa.scan_current(row, fa.input_hash(d)) and "failed" not in scan and not scan.get("puzzles"):
            out[day] = ms
    return out


def to_set_aside(staged, rows, by_number, untitled):
    """[(file, date, why)] of the inbox files that are not a page the list
    wants, each with the reason it is moved out (set_aside): a second copy
    of a Gale document the inbox holds; a page Gale's citation names as
    another article (the Concise's); a page for an edition the list does
    not ask for; and, unless its citation names the cryptic, a page with no
    grid on it or none of whose titles our readers read (`untitled`,
    titleless()), once the matcher has read its citation. A page whose
    citation names the cryptic stays: Gale's cryptic page is the one to
    read, whatever our readers make of it."""
    asked, filed = {d for d, _ in rows}, set(by_number.values())
    out = []
    for day, ms in sorted(staged.items()):
        by_doc = collections.defaultdict(list)
        for m in ms:
            by_doc[m.get("docId") or doc_id(m["file"]) or m["file"]].append(m)
        for doc, copies in by_doc.items():
            keep = min(copies, key=lambda m: (not cryptic_cited(m), len(m["file"]), m["file"]))
            out += [(m["file"], day, f"a second copy of Gale document {doc}") for m in copies if m is not keep]
            if keep.get("cited") and not cryptic_cited(keep):
                out.append((keep["file"], day, f"Gale's citation names it \"{keep['cited']}\", not the cryptic"))
            elif day not in asked and day not in filed:
                out.append((keep["file"], day, f"read as {day:%a %d %b %Y}, an edition the list does not ask for"))
            elif cryptic_cited(keep) or "cited" not in keep:
                continue  # Gale's cryptic page; or matched before citations were read: next tick
            elif keep.get("grid") is False:
                out.append((keep["file"], day, "no crossword grid on it"))
            elif day in untitled:
                out.append((keep["file"], day, "no Times Crossword title read on it"))
    return out


#: Where set_aside moves a file, in its inbox: the sweep and mirror look
#: only at the inbox's own files, so it is out of every count.
ASIDE = "Set aside"
#: Each file set aside: {file: {"date", "why", "at"}}.
SET_ASIDE = MIRROR.parent / "set_aside.json"
#: How long a file set aside is listed on the page.
ASIDE_DAYS = 7


def set_aside(plan, out=sys.stdout, host_inbox=HOST_INBOX, log=SET_ASIDE, run=None):
    """Move each file of `plan` (to_set_aside) into the inbox's ASIDE
    folder on the Mac, a name it already holds kept, and log it. How many."""
    if not plan:
        return 0
    q = shlex.quote
    dest = f"{host_inbox}/{ASIDE}"
    (run or ssh)(f"mkdir -p {q(dest)} && " + " && ".join(f"mv -n {q(host_inbox + '/' + f)} {q(dest + '/')}"
                                                          for f, _, _ in plan))
    kept = load(log, {})
    at = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    for f, day, why in plan:
        kept[f] = {"date": day and day.isoformat(), "why": why, "at": at}
        print(f"set aside {f}: {why}", file=out)
    save_json(log, kept)
    return len(plan)


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


def notes(staged, untitled, unmatched=UNMATCHED, log=SET_ASIDE, now=None):
    """[(file, what happened)] for the page: the files set aside in the last
    ASIDE_DAYS, Gale's cryptic pages our readers read no title on, and the
    files nothing names an edition of. Nothing here asks anything."""
    now = now or datetime.datetime.now().astimezone()
    out = []
    for f, e in sorted(load(log, {}).items(), key=lambda kv: kv[1]["at"], reverse=True):
        if now - datetime.datetime.fromisoformat(e["at"]) <= datetime.timedelta(days=ASIDE_DAYS):
            out.append((f, f"set aside into {ASIDE}: {e['why']}"))
    for day, ms in sorted(untitled.items()):
        out += [(m["file"], f"Gale's cryptic page for {day:%a %d %b %Y}; our readers read no title on it yet")
                for m in ms if cryptic_cited(m)]
    for m in (json.loads(unmatched.read_text()) if unmatched.exists() else []):
        if not m.get("date"):
            out.append((m["file"], f"no edition named on it ({m.get('why', '')}); left in the inbox"))
    return out


#: The Times' own item of the checklist's how-to (page).
STEPS = (
    ("A row with no Download button yet: click <b>Open in Gale</b> (Gale's results for that day's crossword),"
     " open <i>The Times Crossword Puzzle No N</i> (not the Concise) and click <b>Download</b> (PDF). If the"
     " results are empty, <b>Copy</b> the search and paste it into Gale's search box, or use <i>Browse &rarr;"
     " Browse By Date</i> and go to the page shown."),
)

#: How next_up orders, said on the page.
ORDER = ("Order: the year missing the most editions first, and oldest date first within a year; "
         "an edition leaves the list once its file arrives.")


def next_up(rows, staged, n=POOL):
    """The `n` editions to fetch first: the worst year's first (ORDER)."""
    years = collections.defaultdict(list)
    for day, cls in rows:
        years[day.year].append((day, cls))
    order = [(day, cls) for y, ds in sorted(years.items(), key=lambda kv: (-len(kv[1]), kv[0])) for day, cls in sorted(ds)]
    return [(d, c) for d, c in order if d not in staged][:n]


def checklist(rows=None, cache=CACHE, unmatched=UNMATCHED, docs=None, status=None, ledger=None, log=SET_ASIDE):
    """The Times checklist (page): progress, what was sorted automatically
    (notes), the next editions to fetch with what to search for, then every
    wanted edition by year, the worst year first. An edition whose saved
    page holds no cryptic's title (titleless) is still to fetch, unless
    Gale's citation names it the cryptic; one Gale has no cryptic for
    (not_on_gale) leaves next up, its row saying why."""
    rows = wanted() if rows is None else rows
    by_number = held()
    pages = usual_pages()
    ledger = archive_coverage.ledger() if ledger is None else ledger
    matches = staged_matches(cache)
    untitled = titleless(matches, ledger, cache)
    staged = {day: [m["file"] for m in ms] for day, ms in matches.items()
              if day not in untitled or any(cryptic_cited(m) for m in ms)}
    docs = gale_docs.load() if docs is None else docs
    aside = aside_days(log)
    gone = {day: why for day, _ in rows if (why := not_on_gale(day, docs, aside))}
    years = collections.defaultdict(list)
    for day, cls in rows:
        years[day.year].append((day, cls))
    filed = set(by_number.values())
    # Counted by the files downloaded: each page file in the inbox (one set
    # aside is not), and each wanted edition none has come for yet.
    done = sum(len(ms) for ms in matches.values()) + sum(
        1 for m in (json.loads(unmatched.read_text()) if unmatched.exists() else []) if not m.get("date"))
    total = done + sum(day not in staged and day not in gone for day, _ in rows)

    def page_of(y):
        lo, hi, most = nearest(pages, y) or (None, None, None)
        return f"p. {most} (or {lo}-{hi})" if lo else ""

    def row(day, cls):
        n, sure = number_on(day, by_number)
        st = ledger.get(f"{ITEM.format(day.year)}/{day.isoformat()}")
        if day in filed and day in staged:
            status = [("filed", "got")]
        elif st:
            status = [(f"arrived, read: {archive_coverage.verdict_class(st, {})}", "got")]
        elif day in staged:
            status = [(f"arrived ({', '.join(staged[day])})", "got")]
        elif day in gone:
            status = [(gone[day], "bad")]
        else:
            status = "Canberra reprint only" if cls == "canberra-reprint" else ""
        return {"key": day.isoformat(), "date": day, "arrived": day in staged, "dl": gale_docs.link("TTDA", day, docs),
                "search": gale_docs.permalink("TTDA", day, docs) or search_url(day), "copy": search_for(n),
                "status": status,
                "cells": [[(f"{n:,}", "")] + ([] if sure else [("number estimated: check the date", "est")]),
                          page_of(day.year)]}

    return page(
        paper="Times", prod="TTDA", name=CHECKLIST_NAME, store="galeCopied", done=done, total=total,
        done_word="files downloaded", folder=SHARE + "\\Times", notes=notes(matches, untitled, unmatched, log),
        steps=STEPS,
        order=ORDER, what="editions", next_rows=[row(d, c) for d, c in next_up(rows, {**staged, **gone}, None)],
        years_note="The worst year first. An edition leaves this list once its puzzle is filed.",
        years=[(y, f"{len(ds)} missing, {sum(d in staged for d, _ in ds)} arrived", [row(d, c) for d, c in sorted(ds)])
               for y, ds in sorted(years.items(), key=lambda kv: (-len(kv[1]), kv[0]))],
        columns=["No", "Page"], status=status)

#: Gale is asked for links (gale_docs.resolve) at most this often, whatever
#: the tick's own schedule: the pace Paul allowed.
LOOKUP_EVERY = 180
#: Each paper's Gale lookups in a tick start within this long of its own
#: start (the Times' use of its does not shorten the Listener's). Short,
#: because the next tick's sweep of the download folder waits on them.
GALE_SECONDS = 60
LOOKED_UP = MIRROR.parent / "looked_up"


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


def tidy(out=sys.stdout, cache=CACHE, ledger=None):
    """Set aside (set_aside) every staged file that is not a page the list
    wants (to_set_aside). How many."""
    matches = staged_matches(cache)
    ledger = archive_coverage.ledger() if ledger is None else ledger
    return set_aside(to_set_aside(matches, wanted(), held(), titleless(matches, ledger, cache)), out)


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
    """One tick: sweep Gale files into their inboxes; mirror the Times inbox
    and, when it moved (or RENDER_EVERY passed), stage it and publish the
    checklist; publish its status file before the Gale lookups and again
    after, so an open page knows when the inbox was last looked at; then the Listener's
    (gale_listener.tick); then start the reads of the editions just laid
    out (start_reads), and keep the Mac's arrival watcher installed
    (install_watcher). Skipped when another sync is running."""
    import gale_listener  # imports this module, so not at the top
    with locked(wait=False) as mine:
        if not mine:
            # Another sync is doing this same work: waiting behind it ran a
            # tick past its 900 s limit.
            print("another sync holds the lock; this one skips", file=out)
            return
        moved = collect(out)
        changed = mirror(out)
        # The arrivals are known now; the Gale lookups and staging below can
        # take minutes.
        publish_status(CHECKLIST)
        listener_changed = gale_listener.arrivals(out)
        ask = gale_due()
        by_number = held()
        linked = ask and gale_docs.resolve(
            "TTDA", [(d, number_on(d, by_number)[0]) for d, _ in next_up(wanted(), staged_files(), LOOKAHEAD)], out,
            until=time.monotonic() + GALE_SECONDS)
        status = None
        if force or moved or changed or linked or time.time() - last_render() > RENDER_EVERY:
            stage(MIRROR, out=out)
            if tidy(out):
                mirror(out)
                stage(MIRROR, out=out)
            CHECKLIST.parent.mkdir(parents=True, exist_ok=True)
            status = {}
            CHECKLIST.write_text(checklist(status=status))
            publish()
            print(f"checklist published to {GALE_ROOT}/{CHECKLIST_NAME}", file=out)
        publish_status(CHECKLIST, status)
        gale_listener.tick(out, force, ask, time.monotonic() + GALE_SECONDS, listener_changed)
    start_reads(out)
    install_watcher(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sy = sub.add_parser("sync", help="sweep Gale files in, mirror the Mac inbox, stage it, publish the checklist")
    sy.add_argument("--render", action="store_true", help="stage and publish even when nothing moved")
    st = sub.add_parser("stage", help="stage a local folder of pages")
    st.add_argument("--inbox", type=Path, default=MIRROR)
    cl = sub.add_parser("checklist", help="write the checklist")
    cl.add_argument("--out", type=Path, default=CHECKLIST)
    mt = sub.add_parser("match", help="which edition each file is")
    mt.add_argument("files", nargs="+", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "match":
        by_number = held()
        for f in a.files:
            m = match_anywhere(f, by_number)
            print(f"{f.name}: {m['date'] or 'unmatched'} ({m.get('how') or m.get('why')})"
                  + (f", No {m['number']}" if m.get("number") else "")
                  + (f", page {m['page']}" if m.get("page") else "")
                  + f", {len(m['pages'])} page image(s), {'a' if m.get('grid') else 'no'} grid found")
        return 0
    if a.cmd == "checklist":
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(checklist())
        print(f"wrote {a.out}")
        return 0
    if a.cmd == "sync":
        sync(force=a.render)
        return 0
    stage(a.inbox)
    return 0


if __name__ == "__main__":
    sys.exit(main())
