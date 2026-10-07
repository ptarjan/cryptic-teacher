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
that edition, and no other, due for the full pass.
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
import file_archive_org_puzzles as fa
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
#: The code a match is read by: a change to it re-reads every file.
MATCHER = hashlib.sha256(b"".join((TOOLS / f).read_bytes() for f in (
    "gale_inbox.py", "file_archive_org_puzzles.py", "trove_grid.py"))).hexdigest()[:12]
#: The Downloads files already looked at and found not to be Gale's.
SEEN = MIRROR.parent / "seen.json"
LOCK = MIRROR.parent / "sync.lock"
#: A tick re-renders the checklist when the inbox moved, else this often,
#: so a puzzle the full pass filed leaves it.
RENDER_EVERY = 3600
CACHE = fa.CACHE
ITEM = "GaleTimes{}UKEnglish"
PAGES = (".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".gif", ".webp")
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


DATES = date_patterns(r"19[789]\d")
#: A Times cryptic number of 1974-99 (13,676 to ~21,400); Times issue
#: numbers (59,000-66,000) and Gale document ids never fall in it.
NUMBER = re.compile(r"(?<![\d,.])(1[3-9]|2[01])[,.]?(\d{3})(?![\d,])")
#: The citation a Gale PDF prints: "The Times, 12 Jan. 1988, p. 18", or
#: its download's citation page, the article's title quoted first:
#: '"The Times Crossword Puzzle No 17,244." Times, 3 Jan. 1987, p. 20.'
CITED = re.compile(r'(?:"[^"]{0,200}"\s*(?:The\s+)?Times|The Times[^,]{0,40}),\s*(?:\w+,\s*)?([0-3]?\d)\s+' + MON
                   + r"\s*(19[789]\d)(?:,\s*p\.?\s*(\d+))?", re.IGNORECASE)


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


def match(path, by_number):
    """{"date", "number", "how", "page", "docId", "pages": [image]} for a
    saved file; "date" None (and "why") when nothing names its edition."""
    name = path.name
    doc = DOC_ID.search(name)
    out = {"file": name, "docId": doc.group(1).upper() if doc else None, "page": None}
    read = images(path)
    laid = [scaled(img) for img, _ in read]
    pages = out["pages"] = [page for page, _ in laid]
    out["grid"] = any(found for _, found in laid)
    cite = read[0][1] if read else ""
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


# ------------------------------------------------------------ staging

def source_key(files):
    """What the inbox holds for one date, by name, size and content."""
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(f"{p.name}:{p.stat().st_size}:".encode() + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:16]


def stage(inbox=MIRROR, cache=CACHE, out=sys.stdout, unmatched=UNMATCHED, matches=MATCHES):
    """Lay each date's pages in `inbox` out as one edition directory under
    `cache` (re-laid only when what the inbox holds for it moved; a date
    the inbox no longer holds is removed); the files that matched no
    edition are listed in `unmatched`. {date: [match]}; the unmatched
    under None."""
    by_number = held()
    files = sorted(p for p in Path(inbox).iterdir() if p.is_file() and p.suffix.lower() in PAGES) \
        if Path(inbox).exists() else []
    known, kept = load(matches, {}), {}
    by_date = collections.defaultdict(list)
    for p in files:
        st = p.stat()
        k = f"{MATCHER}\t{p.name}\t{st.st_size}\t{int(st.st_mtime)}"
        m = known.get(k)
        if m is None:
            try:
                m = match(p, by_number)
            except (OSError, ValueError, pypdf.errors.PyPdfError) as e:  # reported, not fatal
                m = {"file": p.name, "date": None, "why": f"unreadable: {type(e).__name__}: {e}", "pages": []}
            m["date"] = m["date"] and m["date"].isoformat()
        kept[k] = {f: v for f, v in m.items() if f != "pages"}
        m = dict(m, path=p, date=m["date"] and datetime.date.fromisoformat(m["date"]))
        by_date[m["date"]].append(m)
    matches.parent.mkdir(parents=True, exist_ok=True)
    matches.write_text(json.dumps(kept, indent=0))
    staged = set()
    for day, ms in by_date.items():
        if day is None:
            continue
        d = cache / ITEM.format(day.year) / day.isoformat()
        staged.add(d)
        key = source_key([m["path"] for m in ms])
        if (d / f"sources-{key}.json").exists():
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
                pages = [page for img, _ in images(m["path"]) for page, _ in [scaled(img)]]
            for img in pages:
                leaf = len(leaves)
                img.save(tmp / f"leaf_{leaf:04d}.jpg", quality=92)
                leaves.append({"leaf": leaf, "width": img.width, "height": img.height, "file": m["file"]})
        doc = next((m["docId"] for m in ms if m.get("docId")), None)
        item = ITEM.format(day.year)
        (tmp / "pages.json").write_text(json.dumps({
            "item": item, "edition": day.isoformat(), "date": day.isoformat(), "leaves": len(leaves),
            "crossword_pages": leaves, "url": DOC_URL.format(doc) if doc else PORTAL}, indent=1))
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
            if d.is_dir() and d not in staged:
                shutil.rmtree(d)
                print(f"removed {item.name}/{d.name}: no longer in the inbox", file=out)
    return dict(by_date)


# ------------------------------------------------------------ the Mac's inbox

def ssh(command, **kw):
    return subprocess.run(SSH + [HOST, command], check=True, capture_output=True, **kw)


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


def publish(path=CHECKLIST, host_inbox=GALE_ROOT):
    """Copy a checklist into the Mac folder, under its own name."""
    ssh(f"mkdir -p {shlex.quote(host_inbox)} && cat > {shlex.quote(host_inbox + '/' + path.name)}",
        input=path.read_bytes())


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


def staged_files(cache=CACHE):
    """{date: [file name]} of the inbox pages staged as editions."""
    out = {}
    for src in cache.glob(ITEM.format("*") + "/*/sources-*.json"):
        out[datetime.date.fromisoformat(src.parent.name)] = [m["file"] for m in json.loads(src.read_text())]
    return out


#: The checklist's "next up": BATCH rows shown at a time, from a POOL
#: rendered so the next batch needs no new render; links are looked up for
#: the first LOOKAHEAD.
BATCH = 15
POOL = 60
LOOKAHEAD = 200


#: A row clicked this long ago whose file has not arrived turns amber: the
#: download may have failed.
LATE_MINUTES = 15
#: How often an open checklist reads its status file (status_js).
POLL_SECONDS = 15
#: A status file older than this is not being written: the page falls back
#: to reloading itself every RELOAD_SECONDS.
STALE_SECONDS = 240
RELOAD_SECONDS = 180


def script(store, status_src, stamp):
    """The checklists' row state. A row is one of: to fetch (its Download
    button), clicked and waiting for its file ("downloading... clicked
    HH:MM", an undo, no Download), clicked LATE_MINUTES ago with no file
    (amber, a retry), or arrived ("in the inbox"). Clicks are kept in the
    browser (localStorage `store`, key: when) so a reload keeps them; what
    arrived is the page's own data-in and its status file (status_js),
    read every POLL_SECONDS by a script tag, which a file:// page may load
    where it may not fetch. A status naming a newer page reloads it once;
    a status that stops coming reloads the page every RELOAD_SECONDS. "Next
    batch" hides the clicked rows of #next and shows the next BATCH; the
    first one to fetch is highlighted. A click anywhere on a row to fetch is
    a click on its Download (a.dl). A middle click on a link opens a tab
    without a click event, so it runs the link's onclick (the mark) itself."""
    js = """<script>
const S=STORE,H=S+'Hidden',C=S+'At',BATCH=SIZE,LATE=LATEMIN*60e3,PAGE=STAMP,SRC=SOURCE,LOADED=Date.now();
let IN=new Set(),AT=PAGE*1000;
function get(n){return JSON.parse(localStorage.getItem(n)||'[]')}
function put(n,s){localStorage.setItem(n,JSON.stringify([...new Set(s)].slice(-5000)))}
function clicks(){const v=localStorage.getItem(C);if(v)return JSON.parse(v);const m={};get(S).forEach(k=>m[k]=0);return m}
function keep(m){localStorage.setItem(C,JSON.stringify(Object.fromEntries(
  Object.entries(m).sort((a,b)=>a[1]-b[1]).slice(-5000))))}
function hm(t){return t?new Date(t).toTimeString().slice(0,5):'earlier'}
function state(r,m,now){const k=r.dataset.k;if(r.dataset.in||IN.has(k))return'in';
  return k in m?(now-m[k]>LATE?'late':'wait'):''}
function badge(r,s,t){const b=r.querySelector('.st');if(!b||b.dataset.s===s+t)return;b.dataset.s=s+t;b.className='st '+s;
  const k=r.dataset.k,u=' <a href="#" onclick="unmark(\\''+k+'\\');return false">undo</a>',
    a=r.querySelector('a.dl')||r.querySelector('a.go');
  b.innerHTML=s==='in'?'&#10003; in the inbox':s==='wait'?'downloading&hellip; clicked '+hm(t)+u
    :s==='late'?'clicked '+hm(t)+', not arrived: <a class="retry" target="gale" onclick="mark(\\''+k+'\\')">retry?</a>'+u:'';
  const x=b.querySelector('a.retry');if(x&&a)x.href=a.href}
function show(){const m=clicks(),h=new Set(get(H)),now=Date.now();let n=0,lit=false;
  document.querySelectorAll('tr[data-k]').forEach(r=>{const s=state(r,m,now);r.dataset.s=s;
    for(const c of['wait','late','in'])r.classList.toggle('s-'+c,s===c);
    badge(r,s,m[r.dataset.k]||0);r.classList.toggle('dlrow',!s&&!!r.querySelector('a.dl'))});
  document.querySelectorAll('#next tr[data-k]').forEach(r=>{const on=!h.has(r.dataset.k)&&n<BATCH;
    if(on)n++;r.hidden=!on;const nx=on&&!lit&&!r.dataset.s;r.classList.toggle('next',nx);if(nx)lit=true});
  const mo=document.getElementById('more');if(mo)mo.hidden=n>0;
  const a=document.getElementById('age'),old=now-AT>STALE*1e3;
  if(a){a.textContent='Arrivals last checked '+hm(AT)+' ('+Math.round((now-AT)/60e3)+' min ago)'
    +(old?': the status file is not updating, so this page reloads itself every 3 minutes':'; this page updates itself.');
    a.classList.toggle('old',old)}}
function mark(k){const m=clicks();m[k]=Date.now();keep(m);show()}
function unmark(k){const m=clicks();delete m[k];keep(m);put(H,get(H).filter(x=>x!==k));show()}
function nextBatch(){const h=get(H);
  document.querySelectorAll('#next tr[data-k]').forEach(r=>{if(!r.hidden&&r.dataset.s)h.push(r.dataset.k)});
  put(H,h);show()}
function galeStatus(s){IN=new Set(s.in);AT=s.at*1000;
  if(s.page>PAGE&&sessionStorage.getItem(S+'Page')!==String(s.page)){
    sessionStorage.setItem(S+'Page',s.page);location.reload()}else show()}
function poll(){const x=document.createElement('script');x.src=SRC+'?'+Date.now();
  x.onload=x.onerror=()=>x.remove();document.head.appendChild(x)}
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
    for k, v in (("STORE", json.dumps(store)), ("SOURCE", json.dumps(status_src)), ("SIZE", str(BATCH)),
                 ("LATEMIN", str(LATE_MINUTES)), ("STAMP", str(stamp)), ("STALE", str(STALE_SECONDS)),
                 ("RELOAD", str(RELOAD_SECONDS)), ("POLL", str(POLL_SECONDS))):
        js = js.replace(k, v)
    return js


#: Both checklists' look.
CSS = """body{font:15px -apple-system,Segoe UI,sans-serif;margin:1.5em;max-width:72em}
td,th{padding:4px 8px;text-align:left;vertical-align:middle}tr:nth-child(even){background:#f4f4f4}
h2{margin-top:1.4em}summary{font-size:16px;margin:.4em 0;cursor:pointer}
.got{color:#070}.bad{color:#a00}.est{color:#a60;font-size:90%}#age.old{color:#a00;font-weight:bold}
.redo{background:#fee;border:2px solid #c00;padding:.5em 1em}.how{background:#eef6ff;padding:.5em 1em}
.start{font-size:17px;font-weight:bold}progress{width:20em;height:1.2em;vertical-align:middle}
button{font-size:14px;padding:2px 10px;cursor:pointer}.batch button{font-size:15px;margin-right:.6em}
a.dl{display:inline-block;padding:8px 18px;font-size:17px;font-weight:bold;color:#fff;background:#0a66c2;
border-radius:6px;text-decoration:none;margin:2px .8em 2px 0}a.dl:hover{background:#084f96}a.go{margin-right:.6em}
.st{display:inline-block;padding:6px 12px;border-radius:6px;font-weight:bold}.st:empty{display:none}
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
    publish(js)


def _parts(cell):
    """A cell's HTML: plain text, or [(text, class)]."""
    if isinstance(cell, str):
        return html.escape(cell)
    return " ".join(f'<span class="{c}">{html.escape(t)}</span>' if c else html.escape(t) for t, c in cell)


def _row(r):
    """One row: {"date", "cells", "status", and, for one to fetch, "key",
    "search" (Open in Gale), "dl" (Download, or None), "label", "copy" (a
    search to copy, or None), "arrived"}."""
    k = r.get("key")
    get = ""
    if k and r.get("arrived"):
        get = '<span class="st in">&#10003; in the inbox</span>'
    elif k:
        e, mk, dl = html.escape, f' onclick="mark(\'{k}\')"', r.get("dl")
        get = ('<span class="acts">'
               + (f'<a class="dl" href="{e(dl)}" target="gale"{mk}>{e(r.get("label") or "Download")}</a>' if dl else "")
               + f'<a class="go" href="{e(r["search"])}" target="gale"{"" if dl else mk}>Open in Gale</a>'
               + (f' <button onclick="cp(this,{e(json.dumps(r["copy"]))})">Copy</button> <code>{e(r["copy"])}</code>'
                  if r.get("copy") else "")
               + '</span><span class="st"></span>')
    attrs = (f' data-k="{k}"' + (' data-in="1" class="s-in"' if r.get("arrived") else "")) if k else ""
    return (f'<tr{attrs}><td>{r["date"]:%a %d %b %Y}</td><td>{get}</td>'
            + "".join(f"<td>{_parts(c)}</td>" for c in r["cells"]) + f"<td>{_parts(r['status'])}</td></tr>")


def page(*, paper, prod, name, store, done, total, done_word, folder, steps, redo, order, what, next_rows,
         years_note, years, columns, status=None):
    """A checklist page, either paper's: progress, the files to check, how to
    save one, the next `next_rows` in batches, then `years` [(year, summary,
    rows)]. Rows are _row's; `columns` the paper's own, between the row's
    Download and its status; `steps` the paper's own items of the how-to
    and `order` how next up is ordered (inline HTML). `status`, when given, gets the page's stamp and arrived
    rows, for publish_status."""
    e = html.escape
    stamp = int(time.time())
    every = [r for r in next_rows] + [r for _, _, rs in years for r in rs]
    if status is not None:
        status.update(page=stamp, **{"in": sorted({r["key"] for r in every if r.get("key") and r.get("arrived")})})
    head = ("<tr><th>Date</th><th>Get it</th>" + "".join(f"<th>{e(c)}</th>" for c in columns)
            + "<th>Status</th></tr>")
    title = f"{paper} crosswords from Gale"
    archive = gale_docs.PRODUCTS[prod][2]
    out = [f"""<!doctype html><meta charset="utf-8">
<title>{e(title)}: {done:,} of {total:,}</title>
<style>{CSS}</style>
{script(store, urllib.parse.quote(status_js(Path(name)).name), stamp)}
<h1>{e(title)}</h1>
<p><progress value="{done}" max="{max(total, 1)}"></progress> <b>{done:,} of {total:,}</b> {e(done_word)}, {total - done:,} to go.
Updated {datetime.datetime.fromtimestamp(stamp).astimezone():%a %d %b %H:%M}. <span id="age"></span></p>"""]
    if redo:
        out.append('<div class="redo"><h2 style="margin-top:0">Check these files</h2><ul>')
        out += [f"<li><b>{e(f)}</b>: {e(why)}</li>" for f, why in redo]
        out.append("</ul></div>")
    out.append(f"""<div class="how"><p class="start">1. <a href="{SESSION.format(prod)}" target="gale">Start Gale session</a>
(once per sitting, on an Alberta connection such as home Wi-Fi; no login)</p>
<ol start="2"><li>Click <b>Download</b> on the highlighted row: Gale saves the page as a PDF, and it is moved from
Downloads into <code>{e(folder)}</code> for you. The row says <i>downloading&hellip;</i> until the file arrives,
then <b>&#10003; in the inbox</b>, usually within a minute or two. A row whose file has not come {LATE_MINUTES} minutes
after its click turns amber: retry it.</li>
{"".join(f"<li>{s}</li>" for s in steps)}</ol>
<p>If Gale asks for a password, start from <a href="{PORTAL}">the Alberta Research Portal</a> (choose
<i>{e(archive)}</i>), then come back here. Gale allows 50 downloads a session.</p></div>""")
    if next_rows:
        out.append(f"""<h2>Next up</h2><p>{order}</p>
<p class="batch"><button onclick="nextBatch()">Next batch</button><button onclick="location.reload()">Refresh</button>
Showing {min(BATCH, len(next_rows))} of the next {len(next_rows)} {e(what)}. <b>Next batch</b> hides the rows you clicked and shows the next
ones. The highlighted row is the one to do next.</p>
<p id="more" hidden>All of these are clicked: <b>Refresh</b> once they arrive for more.</p>
<table id="next">{head}""")
        out += [_row(r) for r in next_rows]
        out.append("</table>")
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
    archive `prod`: the day's crossword pages, one click from the page."""
    q = [("inputFieldNames[0]", "TI"), ("inputFieldValues[0]", title), ("dateIndices", "DA"),
         ("dateLimiterValues[DA].dateMode", "2"), ("dateLimiterValues[DA].fromYear", f"{day.year}"),
         ("dateLimiterValues[DA].fromMonth", f"{day.month:02}"), ("dateLimiterValues[DA].fromDay", f"{day.day:02}"),
         ("dateLimiterValues[DA].fromEra", "1"), ("searchType", "AdvancedSearchForm"), ("method", "doSearch"),
         ("searchMethod", "advanced"), ("searchResultsType", "SingleTab"), ("prodId", prod),
         ("userGroupName", "alberta_portal")]
    return f"{SEARCH}?{urllib.parse.urlencode(q)}"


def problems(rows, by_number, staged, unmatched=UNMATCHED):
    """[(file, what to do)] of the inbox files that are not a wanted page:
    no edition named, no grid on it, or a date the list does not ask for."""
    out = []
    for m in (json.loads(unmatched.read_text()) if unmatched.exists() else []):
        if m.get("date"):
            out.append((m["file"], (f"read as {m['date']}, but no crossword grid was found on it. If it is not the "
                                    "crossword page, delete it and download the right page.")))
        else:
            out.append((m["file"], (f"no edition found ({m.get('why', '')}). Rename it with the date, "
                                    "e.g. 1988-01-12, or delete it.")))
    asked, filed = {d for d, _ in rows}, set(by_number.values())
    for day, files in sorted(staged.items()):
        if day not in asked and day not in filed:
            out += [(f, f"read as {day:%a %d %b %Y}, which is not on the list: the wrong issue? Delete it if so.")
                    for f in files]
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


def checklist(rows=None, cache=CACHE, unmatched=UNMATCHED, docs=None, status=None):
    """The Times checklist (page): progress, any page that needs redoing,
    the next editions to fetch with what to search for, then every wanted
    edition by year, the worst year first."""
    rows = wanted() if rows is None else rows
    by_number = held()
    pages = usual_pages()
    ledger = archive_coverage.ledger()
    staged = staged_files(cache)
    docs = gale_docs.load() if docs is None else docs
    years = collections.defaultdict(list)
    for day, cls in rows:
        years[day.year].append((day, cls))
    filed = set(by_number.values())
    done = len(staged)
    total = done + sum(day not in staged for day, _ in rows)

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
        else:
            status = "Canberra reprint only" if cls == "canberra-reprint" else ""
        return {"key": day.isoformat(), "date": day, "arrived": day in staged, "dl": gale_docs.link("TTDA", day, docs),
                "search": search_url(day), "copy": search_for(n), "status": status,
                "cells": [[(f"{n:,}", "")] + ([] if sure else [("number estimated: check the date", "est")]),
                          page_of(day.year)]}

    return page(
        paper="Times", prod="TTDA", name=CHECKLIST_NAME, store="galeCopied", done=done, total=total,
        done_word="arrived", folder=SHARE + "\\Times", redo=problems(rows, by_number, staged, unmatched),
        steps=STEPS,
        order=ORDER, what="editions", next_rows=[row(d, c) for d, c in next_up(rows, staged)],
        years_note="The worst year first. An edition leaves this list once its puzzle is filed.",
        years=[(y, f"{len(ds)} missing, {sum(d in staged for d, _ in ds)} arrived", [row(d, c) for d, c in sorted(ds)])
               for y, ds in sorted(years.items(), key=lambda kv: (-len(kv[1]), kv[0]))],
        columns=["No", "Page"], status=status)

#: Gale is asked for links (gale_docs.resolve) at most this often, whatever
#: the tick's own schedule: the pace Paul allowed.
LOOKUP_EVERY = 180
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


def last_render(path=CHECKLIST):
    return path.stat().st_mtime if path.exists() else 0


@contextlib.contextmanager
def locked():
    """Held while a mirror is written: the tick and the full pass's syncs
    take turns."""
    import fcntl
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def sync(out=sys.stdout, force=False):
    """One tick: sweep Gale files into their inboxes; mirror the Times inbox
    and, when it moved (or RENDER_EVERY passed), stage it and publish the
    checklist; publish its status file either way, so an open page knows
    when the inbox was last looked at; then the Listener's
    (gale_listener.tick)."""
    import gale_listener  # imports this module, so not at the top
    with locked():
        moved = collect(out)
        changed = mirror(out)
        ask = gale_due()
        by_number = held()
        linked = ask and gale_docs.resolve(
            "TTDA", [(d, number_on(d, by_number)[0]) for d, _ in next_up(wanted(), staged_files(), LOOKAHEAD)], out)
        status = None
        if force or moved or changed or linked or time.time() - last_render() > RENDER_EVERY:
            stage(MIRROR, out=out)
            CHECKLIST.parent.mkdir(parents=True, exist_ok=True)
            status = {}
            CHECKLIST.write_text(checklist(status=status))
            publish()
            print(f"checklist published to {GALE_ROOT}/{CHECKLIST_NAME}", file=out)
        publish_status(CHECKLIST, status)
        gale_listener.tick(out, force, ask)


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
            m = match(f, by_number)
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
