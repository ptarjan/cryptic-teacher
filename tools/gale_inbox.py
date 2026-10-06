#!/usr/bin/env python3
"""The London Times editions of 1974-99 archive.org holds no scan of, read
from the crossword pages Paul downloads BY HAND from Gale's Times Digital
Archive (through the Alberta Research Portal).

Gale's terms forbid scripted access: nothing here requests anything from
Gale or the portal. It writes a checklist of the editions to fetch, and lays
each page Paul saves into his inbox out as one more Times edition for
tools/file_archive_org_puzzles.py, which reads it like any scan: our
readers' and the VLM's readings voted on, the Canberra reprint's beside them.

    python3 tools/gale_inbox.py sync              # mirror the Mac's inbox, stage, publish the checklist
    python3 tools/gale_inbox.py stage --inbox DIR # stage a local folder of pages (no Mac)
    python3 tools/gale_inbox.py checklist [--out FILE]
    python3 tools/gale_inbox.py match FILE...     # which edition each file is, and how that was read

The inbox is HOST_INBOX on the Mac, reached over the container's ssh hatch;
its mirror is MIRROR. A file is matched to its edition by the date in its
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
import collections
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
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import pypdf

import archive_coverage
import file_archive_org_puzzles as fa

#: Where Paul saves pages, on the Mac; the checklist is written beside them.
HOST = os.environ.get("GALE_INBOX_HOST", "pt@host.docker.internal")
HOST_INBOX = "Documents/Times crosswords (Gale)"
CHECKLIST_NAME = "Checklist.html"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "HostKeyAlias=localhost",
       "-i", os.path.expanduser("~/.ssh/host_hatch")]
MIRROR = Path(os.path.expanduser("~/.cache/gale_inbox/files"))
CHECKLIST = Path(os.path.expanduser("~/.cache/gale_inbox")) / CHECKLIST_NAME
UNMATCHED = MIRROR.parent / "unmatched.json"
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
#: A Gale article opens from its document id (the one link the portal
#: session opens without a date search); no URL opens a date.
DOC_URL = "https://go.gale.com/ps/retrieve.do?docId=GALE%7C{}&prodId=TTDA&userGroupName=alberta_portal"
DOC_ID = re.compile(r"GALE\W{0,3}([A-Z]{2}\d{8,12})", re.IGNORECASE)

MONTHS = {m: i for i, ms in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1) for m in [ms]}
MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
ISO = re.compile(r"(?<!\d)(19[789]\d)[-_. ]?(0[1-9]|1[0-2])[-_. ]?(0[1-9]|[12]\d|3[01])(?!\d)")
DMY = re.compile(r"(?<!\d)([0-3]?\d)(?:st|nd|rd|th)?[-_. ,]*" + MON + r"[-_. ,]*(19[789]\d)(?!\d)", re.IGNORECASE)
MDY = re.compile(MON + r"[-_. ]*([0-3]?\d)(?:st|nd|rd|th)?[-_. ,]*(19[789]\d)(?!\d)", re.IGNORECASE)
#: A Times cryptic number of 1974-99 (13,676 to ~21,400); Times issue
#: numbers (59,000-66,000) and Gale document ids never fall in it.
NUMBER = re.compile(r"(?<![\d,.])(1[3-9]|2[01])[,.]?(\d{3})(?![\d,])")
#: The citation a Gale PDF prints: "The Times, 12 Jan. 1988, p. 18".
CITED = re.compile(r"The Times[^,]{0,40},\s*(?:\w+,\s*)?([0-3]?\d)\s+" + MON + r"\s*(19[789]\d)(?:,\s*p\.?\s*(\d+))?",
                   re.IGNORECASE)


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


def neighbours(key, by_number):
    """The filed (number, date) either side of `key`(number, date)."""
    lo = max(((m, d) for m, d in by_number.items() if key(m, d) < 0 and d in ISSUE), default=None)
    hi = min(((m, d) for m, d in by_number.items() if key(m, d) > 0 and d in ISSUE), default=None)
    return lo, hi


def number_on(day, by_number):
    """(number, sure) of the Times cryptic printed on `day`: sure when the
    printed issues counted from the filed puzzles either side agree, else
    the issues counted from the nearer one."""
    lo, hi = neighbours(lambda m, d: (d > day) - (d < day), by_number)
    up = lo and lo[0] + ISSUE[day] - ISSUE[lo[1]]
    down = hi and hi[0] - (ISSUE[hi[1]] - ISSUE[day])
    if up and down:
        return (up, True) if up == down else ((up, False) if day - lo[1] <= hi[1] - day else (down, False))
    return (up or down or fa.expected_number(day)), False


def day_of(number, by_number):
    """The date No `number` printed on, or None: the printed issues counted
    from the filed puzzles either side must agree on it."""
    lo, hi = neighbours(lambda m, d: (m > number) - (m < number), by_number)
    if not lo or not hi:
        return None
    up, down = ISSUE[lo[1]] + number - lo[0], ISSUE[hi[1]] - (hi[0] - number)
    return PRINTED[up] if up == down and 0 <= up < len(PRINTED) else None


def name_date(name):
    """The date a file name spells, or None."""
    for rx, order in ((ISO, "ymd"), (DMY, "dmy"), (MDY, "mdy")):
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
    """`img` as an archive.org page holds a puzzle: scaled so its widest
    grid is GRID_WIDTH wide (unscaled when none is found) and set on a white
    page SCAN_WIDTH wide, the size the filer's pixel spans are set at."""
    from PIL import Image
    grids = fa.grids_on(img, shaped=square)
    if grids:
        k = GRID_WIDTH / max(b[2] - b[0] for b in grids)
        if abs(k - 1) >= 0.05:
            img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    page = Image.new("RGB", (max(fa.SCAN_WIDTH, img.width + 2 * MARGIN), img.height + 2 * MARGIN), "white")
    page.paste(img, (MARGIN, MARGIN))
    return page


#: Only breaks a tie between readers who read different title numbers.
MID_DAY = datetime.date(1987, 1, 1)


def title_number(img, key):
    """The puzzle number our readers read in a page's title, or None."""
    found = fa.ocr_titles(img, fa.TIMES, MID_DAY, key)
    return found[0][0] if found else None


def match(path, by_number):
    """{"date", "number", "how", "page", "docId", "pages": [image]} for a
    saved file; "date" None (and "why") when nothing names its edition."""
    name = path.name
    doc = DOC_ID.search(name)
    out = {"file": name, "docId": doc.group(1).upper() if doc else None, "page": None}
    read = images(path)
    pages = out["pages"] = [scaled(img) for img, _ in read]
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


def stage(inbox=MIRROR, cache=CACHE, out=sys.stdout, unmatched=UNMATCHED):
    """Lay each date's pages in `inbox` out as one edition directory under
    `cache` (re-laid only when what the inbox holds for it moved; a date
    the inbox no longer holds is removed); the files that matched no
    edition are listed in `unmatched`. {date: [match]}; the unmatched
    under None."""
    by_number = held()
    files = sorted(p for p in Path(inbox).iterdir() if p.is_file() and p.suffix.lower() in PAGES) \
        if Path(inbox).exists() else []
    by_date = collections.defaultdict(list)
    for p in files:
        try:
            m = match(p, by_number)
        except (OSError, ValueError, pypdf.errors.PyPdfError) as e:  # reported, not fatal
            m = {"file": p.name, "date": None, "why": f"unreadable: {type(e).__name__}: {e}", "pages": []}
        m["path"] = p
        by_date[m["date"]].append(m)
    staged = set()
    for day, ms in by_date.items():
        if day is None:
            continue
        d = cache / ITEM.format(day.year) / day.isoformat()
        staged.add(d)
        key = source_key([m["path"] for m in ms])
        if (d / f"sources-{key}.json").exists():
            continue
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        leaves = []
        for m in ms:
            for img in m["pages"]:
                leaf = len(leaves)
                img.save(d / f"leaf_{leaf:04d}.jpg", quality=92)
                leaves.append({"leaf": leaf, "width": img.width, "height": img.height, "file": m["file"]})
        doc = next((m["docId"] for m in ms if m.get("docId")), None)
        item = ITEM.format(day.year)
        (d / "pages.json").write_text(json.dumps({
            "item": item, "edition": day.isoformat(), "date": day.isoformat(), "leaves": len(leaves),
            "crossword_pages": leaves, "url": DOC_URL.format(doc) if doc else PORTAL}, indent=1))
        (d / f"sources-{key}.json").write_text(json.dumps(
            [{k: (v.isoformat() if isinstance(v, datetime.date) else v) for k, v in m.items()
              if k not in ("pages", "path")} for m in ms], indent=1))
        print(f"staged {item}/{day} from {', '.join(m['file'] for m in ms)} ({ms[0]['how']})", file=out)
    unmatched.parent.mkdir(parents=True, exist_ok=True)
    unmatched.write_text(json.dumps([{"file": m["file"], "why": m.get("why", "")} for m in by_date.get(None, ())],
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


def mirror(out=sys.stdout):
    """Copy the Mac inbox's page files to MIRROR: the new and changed ones;
    a file gone from the inbox goes from the mirror. Only the Mac is asked."""
    q = shlex.quote
    ssh(f"mkdir -p \"$HOME\"/{q(HOST_INBOX)}")
    listing = ssh(f"cd \"$HOME\"/{q(HOST_INBOX)} && find . -maxdepth 1 -type f -exec stat -f '%z %m %N' {{}} +; exit 0",
                  text=True).stdout
    there = {}
    for line in listing.splitlines():
        size, mtime, name = line.split(" ", 2)
        name = name.removeprefix("./")
        if Path(name).suffix.lower() in PAGES:
            there[name] = (int(size), int(mtime))
    MIRROR.mkdir(parents=True, exist_ok=True)
    want = [n for n, (size, mtime) in there.items()
            if not (MIRROR / n).exists() or (MIRROR / n).stat().st_size != size
            or int((MIRROR / n).stat().st_mtime) != mtime]
    for i in range(0, len(want), 100):
        batch = want[i:i + 100]
        blob = ssh(f"cd \"$HOME\"/{q(HOST_INBOX)} && tar cf - -- {' '.join(q(n) for n in batch)}").stdout
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            for member in tar.getmembers():
                if member.isfile() and Path(member.name).name in there:
                    dest = MIRROR / Path(member.name).name
                    dest.write_bytes(tar.extractfile(member).read())
                    os.utime(dest, (member.mtime, member.mtime))
        print(f"copied {len(batch)} file(s) from the Mac inbox", file=out)
    for p in MIRROR.iterdir():
        if p.name not in there:
            p.unlink()
            print(f"dropped {p.name}: gone from the Mac inbox", file=out)


def publish(path=CHECKLIST):
    """Copy the checklist into the Mac inbox."""
    ssh(f"cat > \"$HOME\"/{shlex.quote(HOST_INBOX + '/' + CHECKLIST_NAME)}", input=path.read_bytes())


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
    return [(datetime.date.fromisoformat(d), cls) for d, cls, _, _ in archive_coverage.unfiled(fa.TIMES, today)
            if cls in WANTED and int(d[:4]) in YEARS]


def staged_files(cache=CACHE):
    """{date: [file name]} of the inbox pages staged as editions."""
    out = {}
    for src in cache.glob(ITEM.format("*") + "/*/sources-*.json"):
        out[datetime.date.fromisoformat(src.parent.name)] = [m["file"] for m in json.loads(src.read_text())]
    return out


def checklist(rows=None, cache=CACHE, unmatched=UNMATCHED):
    """The checklist page: every wanted edition by year, the worst year
    first, with its number, page and how to find it; then the inbox files
    that matched no edition (stage's)."""
    rows = wanted() if rows is None else rows
    by_number = held()
    pages = usual_pages()
    ledger = archive_coverage.ledger()
    staged = staged_files(cache)
    years = collections.defaultdict(list)
    for day, cls in rows:
        years[day.year].append((day, cls))
    e = html.escape
    out = [f"""<!doctype html><meta charset="utf-8"><title>Times crosswords to fetch from Gale</title>
<style>body{{font:14px -apple-system,sans-serif;margin:2em;max-width:60em}}td,th{{padding:2px 8px;text-align:left}}
tr:nth-child(even){{background:#f4f4f4}}h2{{margin-top:1.5em}}.got{{color:#070}}</style>
<h1>Times crosswords to fetch from Gale: {len(rows):,} editions</h1>
<p>Generated {datetime.datetime.now().astimezone():%Y-%m-%d %H:%M %Z} by <code>tools/gale_inbox.py</code> from the corpus and the scan
ledger. An edition leaves this list once its puzzle is filed.</p>
<p><b>How:</b> open <a href="{PORTAL}">the Alberta Research Portal</a> and choose <i>The Times Digital Archive</i>
(Gale opens no date link of its own; a link outside the portal asks for a password). Then <i>Browse &rarr;
Browse By Date</i>, enter the date, open the issue and the page, or search for the title, e.g.
<code>"Crossword Puzzle No 17,563"</code>. Open <i>The Times Crossword Puzzle No N</i> and <i>Download</i> it
into this folder (<code>~/{e(HOST_INBOX)}</code>). Any name works: a date or the puzzle number in the name
is used, else the PDF's citation, else the number read off the title. Gale's terms allow 50 downloads a
session, by hand only.</p>
<p>Numbers marked ~ are estimates (the filed puzzles either side do not run unbroken); the page is the one
archive.org's scans of that year usually have it on.</p>"""]
    for y, ds in sorted(years.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lo, hi, most = nearest(pages, y) or (None, None, None)
        out.append(f"<h2>{y}: {len(ds)} missing</h2><table><tr><th>Date</th><th>No</th><th>Page</th>"
                   "<th>Status</th></tr>")
        for day, cls in sorted(ds):
            n, sure = number_on(day, by_number)
            page = f"p. {lo}-{hi} (most {most})" if lo else ""
            row = ledger.get(f"{ITEM.format(y)}/{day.isoformat()}")
            if row:
                status = f'<span class="got">in inbox: read, {e(archive_coverage.verdict_class(row, {}))}</span>'
            elif day in staged:
                status = f'<span class="got">in inbox ({e(", ".join(staged[day]))}): next full pass</span>'
            else:
                status = "Canberra reprint only" if cls == "canberra-reprint" else ""
            out.append(f"<tr><td>{day:%a %d %b %Y}</td><td>{'' if sure else '~'}{n:,}</td><td>{page}</td>"
                       f"<td>{status}</td></tr>")
        out.append("</table>")
    lost = json.loads(unmatched.read_text()) if unmatched.exists() else []
    if lost:
        out.append("<h2>Files that matched no edition</h2><p>Rename each with its date (e.g. 1988-01-12).</p><ul>")
        out += [f"<li>{e(m['file'])}: {e(m.get('why', ''))}</li>" for m in lost]
        out.append("</ul>")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="mirror the Mac inbox, stage its pages, publish the checklist there")
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
                  + (f", page {m['page']}" if m.get("page") else "") + f", {len(m['pages'])} page image(s)")
        return 0
    if a.cmd == "checklist":
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(checklist())
        print(f"wrote {a.out}")
        return 0
    if a.cmd == "sync":
        mirror()
    stage(a.inbox if a.cmd == "stage" else MIRROR)
    if a.cmd == "sync":
        CHECKLIST.parent.mkdir(parents=True, exist_ok=True)
        CHECKLIST.write_text(checklist())
        publish()
        print(f"checklist published to ~/{HOST_INBOX}/{CHECKLIST_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
