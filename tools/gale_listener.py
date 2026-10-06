#!/usr/bin/env python3
"""The Listener crosswords of 1930-91, read from the pages Paul saves BY HAND
from Gale's Listener Historical Archive (through the Alberta Research Portal).

Gale's terms forbid scripted access: nothing here requests anything from
Gale or the portal. It writes a checklist of the puzzles to save, from the
Listener Team's year index (listenercrossword.com /Years/Y<year>.html, read
for the numbers and dates only), and reads each page Paul saves into his
inbox with the clue OCR every scan filer shares (tools/ocr_clues.py's
readers, tools/archive_org_listener.py's vote).

    python3 tools/gale_listener.py sync               # mirror the Mac's inbox, read new pages, publish the checklist
    python3 tools/gale_listener.py read --inbox DIR [--store DIR]   # read a local folder (no Mac)
    python3 tools/gale_listener.py checklist [--out FILE]
    python3 tools/gale_listener.py match FILE...      # which puzzle each file is, and how that was read

The inbox is gi.LISTENER_INBOX on the Mac, mirrored to MIRROR over the ssh hatch
as tools/gale_inbox.py mirrors the Times'. A file is matched to its puzzle
by the date in its name, else the puzzle number in its name, else the date a
Gale PDF's citation prints, else the number our readers read in its title
("Crossword No. 1,234"); a date gives the puzzle the index puts on that
issue. Each file is read once: STORE/ledger.json is keyed by the file's
sha256 (and VERSION), so a re-run reads only files new or changed.

What a page gives is its clues: STORE/listener-N.json, the reading
tools/archive_org_listener.py writes (clue text and count by light, the
vote's blanks, the source). A puzzle file needs the grid and answers too,
which a barred grid's clues alone do not give; those readings are the input
of that later step, and nothing here writes puzzles/listener.
"""
import argparse
import datetime
import hashlib
import html
import json
import os
import re
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import archive_org_listener as al
import file_archive_org_puzzles as fa
import gale_inbox as gi
import listener_puzzles as lp
import ocr_clues

#: The Listener folder under the Gale root on the Mac's Media disk
#: (gi.LISTENER_INBOX), shared to the desktop as Z:\\Gale crosswords\\Listener;
#: the checklist is published to the root beside the Times'.
FOLDER = "Gale crosswords/Listener on the Media disk (Z:\\Gale crosswords\\Listener on the desktop)"
CHECKLIST_NAME = "Listener checklist.html"
HOME = Path(os.path.expanduser("~/.cache/gale_listener"))
MIRROR = HOME / "files"
CHECKLIST = HOME / CHECKLIST_NAME
OCR_CACHE = HOME / "ocr"
#: The readings and the ledger: derived from Paul's pages, kept beside the
#: series' other source data.
STORE = lp.CACHE / "gale"
YEARS = lp.CACHE / "years"
#: The Listener magazine's last issue; the puzzle moved to The Times after it.
FIRST_YEAR, LAST_ISSUE = 1930, datetime.date(1991, 1, 3)
#: Bumped when the reading changes, so every file is read again.
VERSION = 1
PORTAL = gi.PORTAL
DOC_URL = "https://go.gale.com/ps/retrieve.do?docId=GALE%7C{}&prodId=LSNR&userGroupName=alberta_portal"

DATES = gi.date_patterns(r"19[2-9]\d")
#: A puzzle number in a file name: after "No", "Listener", "Crossword" or
#: "#", or a bare number that is no year of the run.
LABELLED = re.compile(r"(?:\bno|listener|crossword|puzzle|#)\W{0,3}(\d[,.]?\d{0,3})(?![\d,])", re.IGNORECASE)
BARE = re.compile(r"(?<![\d,.])(\d{1,4})(?![\d,])")
#: The citation a Gale PDF prints: "The Listener, vol. 3, no. 64, 2 Apr. 1930, p. 612".
CITED = re.compile(r"The Listener\b[^\n]{0,80}?([0-3]?\d)\s+" + gi.MON + r"\s*(19[2-9]\d)(?:,\s*p\.?\s*(\d+))?",
                   re.IGNORECASE)
#: The title our readers read on the page.
TITLE = re.compile(r"crossword\W{0,3}(?:puzzle\W{0,3})?n[o0]\.?\s*(\d[,.]?\d{0,3})(?![\d,])", re.IGNORECASE)


# ------------------------------------------------------------ the index

def year_page(year, cache=YEARS, fetch=True):
    """The Listener Team's index page for `year`, cached; fetched at their
    1-2 s pace when missing (listenercrossword.com, never Gale)."""
    path = cache / f"Y{year}.html"
    if not path.exists():
        if not fetch:
            return ""
        cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(lp.get(f"{lp.SITE}/Years/Y{year}.html"))
        time.sleep(2)
    return path.read_text(errors="replace")


CELL = re.compile(r'<td class="(num|title|setter|date)">(.*?)</td>', re.DOTALL)


def parse_year(text, year):
    """[{number, title, setter, date}] of one year page's rows."""
    out, row = [], {}
    for cls, raw in CELL.findall(text):
        val = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        if cls == "num":
            row = {"number": int(val)} if val.isdigit() else {}
        elif row:
            row[cls] = val
            if cls == "date":
                try:
                    day, mon = val.split()
                    row["date"] = datetime.date(year, gi.MONTHS[mon[:3].lower()], int(day))
                except (ValueError, KeyError):
                    row = {}
                    continue
                row["setter"] = None if row.get("setter") in ("—", "") else row.get("setter")
                out.append(row)
                row = {}
    return out


def index(cache=YEARS, fetch=True):
    """[{number, title, setter, date}] of every Listener the magazine printed."""
    rows = {}
    for y in range(FIRST_YEAR, LAST_ISSUE.year + 1):
        for r in parse_year(year_page(y, cache, fetch), y):
            if r["date"] <= LAST_ISSUE:
                rows[r["number"]] = r
    return [rows[n] for n in sorted(rows)]


def by_date(idx, day):
    """The puzzle printed in the issue of `day` (within its week), or None."""
    near = [r for r in idx if abs((r["date"] - day).days) <= 3]
    return min(near, key=lambda r: abs((r["date"] - day).days)) if near else None


# ------------------------------------------------------------ matching a file

def name_number(name):
    """The Listener number a file name spells, or None."""
    name = gi.DOC_ID.sub(" ", name)
    for rx, m in ((LABELLED, None), (BARE, None)):
        for m in rx.finditer(name):
            n = int(re.sub(r"\D", "", m.group(1)))
            if rx is LABELLED or not 1929 <= n <= 1991:
                return n
    return None


def page_words(img, key):
    """[(x0, y0, x1, y1, text)] the fine-tuned Tesseract reads over the
    whole page at its own size, to find the title and the clue lists; cached."""
    path = OCR_CACHE / f"{key}.page.{ocr_clues.reader_key('times')}.json"
    if path.exists():
        return [tuple(w) for w in json.loads(path.read_text())]
    words = ocr_clues.tesseract_words(img.convert("RGB"), ocr_clues.TESS_MODELS["times"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(words))
    return words


def image_key(img):
    return hashlib.sha256(img.tobytes()).hexdigest()[:20]


def match(path, idx, read_title=True):
    """{"number", "date", "how", "docId", "pages": [(image, key)]} for a saved
    file; "number" None (and "why") when nothing names its puzzle."""
    name = path.name
    doc = gi.DOC_ID.search(name)
    out = {"file": name, "docId": doc.group(1).upper() if doc else None, "number": None}
    read = gi.images(path)
    out["pages"] = [(img, image_key(img)) for img, _ in read]
    cite = read[0][1] if read else ""
    by_number = {r["number"]: r for r in idx}
    day = gi.name_date(name, DATES)
    if day:
        r = by_date(idx, day)
        out.update(number=r and r["number"], how="file name date")
    if out["number"] is None and (n := name_number(name)) is not None:
        out.update(number=n, how="file name number")
    if out["number"] is None and (m := CITED.search(cite or "")):
        day = datetime.date(int(m.group(3)), gi.MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
        r = by_date(idx, day)
        out.update(number=r and r["number"], how="PDF citation")
    if out["number"] is None and read_title:
        for img, key in out["pages"]:
            m = TITLE.search(ocr_clues.lines_of(page_words(img, key)))
            if m:
                out.update(number=int(re.sub(r"\D", "", m.group(1))), how="title read")
                break
    if out["number"] is not None and out["number"] not in by_number:
        out.update(why=f"No {out['number']} is not in the index of the magazine's puzzles", number=None)
    if out["number"] is None:
        out.setdefault("why", "no date or number in the name, citation or title")
    else:
        out["date"] = by_number[out["number"]]["date"]
    if not out["pages"]:
        out.update(number=None, why="no page image in the file")
    return out


# ------------------------------------------------------------ reading a page

#: A gap this wide with no word in it, down the clue lists, parts two columns.
GUTTER = 25
#: RapidOCR reads at most this tall a band (after ocr_clues.UPSCALE) unshrunk.
BAND = 900


def words_only(words):
    """The words a column's extent is measured by: a lone number with no
    words beside it (a grid's cell number) is not one."""
    out = []
    for w in words:
        if re.fullmatch(r"\W*\d{1,3}\W*", w[4]) and not any(
                o is not w and not re.fullmatch(r"\W*\d{1,3}\W*", o[4]) and 0 <= o[0] - w[2] <= 40
                and abs((o[1] + o[3]) / 2 - (w[1] + w[3]) / 2) < (w[3] - w[1]) for o in words):
            continue
        out.append(w)
    return out


def page_columns(words):
    """[across lines, down lines], each [(y0, y1, x0, x1, text)], for a page
    laid out any way: the columns are cut at the gutters, read left to right
    from the column ACROSS heads, each from the lists' top; the lines before
    DOWN are the across clues, those after it the down. None without both
    headings."""
    across = al.heading_word(words, "ACROSS")
    down = across and next((w for w in sorted(words, key=lambda w: (w[0] // 200, w[1]))
                            if fa.heading_of(w[4]) == "DOWN"
                            and (w[1] > across[3] or w[0] > across[2])), None)
    if not across or not down:
        return None
    top = across[1] - 20
    body = [w for w in words_only(words) if (w[1] + w[3]) / 2 >= top and w[0] >= across[0] - 40]
    spans = []
    for x0, _, x1, _, _ in sorted(body):
        if spans and x0 <= spans[-1][1] + GUTTER:
            spans[-1][1] = max(spans[-1][1], x1)
        else:
            spans.append([x0, x1])
    lines = {"ACROSS": [], "DOWN": []}
    side = "ACROSS"
    for x0, x1 in spans:
        col = [(w[1], w[3], w[0], w[2], w[4]) for w in body if x0 <= w[0] <= x1]
        last = None
        for line in fa.merge_rows(col):
            if last is not None and line[0] - last > 2 * fa.GAP or al.END.match(line[4]):
                break
            last = line[1]
            head = fa.heading_of(line[4])
            if head:
                side = head
                continue
            lines[side].append(line)
        if al.END.match(lines[side][-1][4] if lines[side] else ""):
            break
    return [lines["ACROSS"], lines["DOWN"]] if lines["ACROSS"] and lines["DOWN"] else None


def bands(box, located):
    """`box` cut into bands BAND tall at most, each cut between printed
    lines (the located words'), so no line is read in two."""
    x0, y0, x1, y1 = box
    out, start = [], y0
    while y1 - start > BAND:
        cut = start + BAND
        while cut > start + BAND // 2 and any(w[1] < cut < w[3] for w in located):
            cut -= 4
        out.append((x0, start, x1, cut))
        start = cut
    out.append((x0, start, x1, y1))
    return out


def read_page(img, key):
    """(verdict, {light: (text, enumeration, None)} or None) for one page:
    the clue lists found on the whole page's reading, then read by every
    ocr_clues.READERS reader band by band and voted on (al.vote)."""
    verdict = {}
    located = page_words(img, key)
    across = al.heading_word(located, "ACROSS")
    if not across:
        verdict["refused"] = "no ACROSS heading on the page"
        return verdict, None
    box = (max(0, across[0] - 60), max(0, across[1] - 20), img.width, img.height)
    words = {"page": located}
    for which in ocr_clues.READERS:
        path = OCR_CACHE / f"{key}.{'-'.join(map(str, box))}.{ocr_clues.reader_key(which)}.json"
        if path.exists():
            words[which] = [tuple(w) for w in json.loads(path.read_text())]
            continue
        got = []
        for b in bands(box, located):
            got += [(x0 + b[0], y0 + b[1], x1 + b[0], y1 + b[1], t)
                    for x0, y0, x1, y1, t in ocr_clues.read_words(img.crop(b), which)]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(got))
        words[which] = got
    return al.vote(words, verdict, cols=page_columns)


def read_file(m):
    """(verdict, laid) of the fullest page of a matched file."""
    best = ({"refused": "no page image"}, None)
    for img, key in m["pages"]:
        verdict, laid = read_page(img, key)
        if laid and (not best[1] or verdict["agreed"] > best[0]["agreed"]):
            best = (verdict, laid)
        elif not best[1] and "refused" in verdict:
            best = (verdict, None)
    return best


def reading(m, row, verdict, laid):
    """The reading written to STORE: archive_org_listener.reading's shape."""
    suspects = {lid: s for lid, (t, _, _) in laid.items() if t and (s := ocr_clues.suspect(t))}
    if suspects:
        verdict["suspect"] = {lid: [tok for tok, _ in s] for lid, s in suspects.items()}
    return {
        "id": f"listener-{row['number']}",
        "number": row["number"],
        "series": lp.SERIES,
        "name": f"Listener crossword No {row['number']:,}: {row['title']}",
        "setter": row.get("setter"),
        "date": row["date"].isoformat(),
        "source": {"publisher": "The Listener", "retrievedFrom": "gale", "file": m["file"],
                   "url": DOC_URL.format(m["docId"]) if m.get("docId") else PORTAL},
        "unfiled": "clues only: the grid and answers are still to be rebuilt",
        "verdict": verdict,
        "clues": {lid: {"text": t, "enumeration": e} for lid, (t, e, _) in laid.items()},
    }


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_ledger(store):
    path = store / "ledger.json"
    return json.loads(path.read_text()) if path.exists() else {}


def run(inbox=MIRROR, store=STORE, idx=None, out=sys.stdout, reader=read_file):
    """Read every file in `inbox` the ledger has not read at this VERSION;
    write each puzzle's reading to `store` (a fuller one replaces it).
    Returns the ledger."""
    idx = index() if idx is None else idx
    rows = {r["number"]: r for r in idx}
    store.mkdir(parents=True, exist_ok=True)
    ledger = load_ledger(store)
    files = sorted(p for p in Path(inbox).iterdir() if p.is_file() and p.suffix.lower() in gi.PAGES) \
        if Path(inbox).exists() else []
    for p in files:
        h = file_hash(p)
        if ledger.get(h, {}).get("version") == VERSION:
            continue
        entry = {"file": p.name, "version": VERSION, "readOn": datetime.datetime.now().astimezone().date().isoformat()}
        try:
            m = match(p, idx)
        except (OSError, ValueError) as e:  # reported in the ledger and the checklist
            m = {"file": p.name, "number": None, "why": f"unreadable: {type(e).__name__}: {e}", "pages": []}
        entry.update(number=m["number"], how=m.get("how"), why=m.get("why"))
        if m["number"] is not None:
            verdict, laid = reader(m)
            if laid is None:
                entry["why"] = verdict.get("refused", "no reading")
            else:
                entry.update(clues=verdict["clues"], agreed=verdict["agreed"])
                dest = store / f"listener-{m['number']}.json"
                old = json.loads(dest.read_text()) if dest.exists() else None
                if old is None or old["verdict"].get("agreed", 0) <= verdict["agreed"]:
                    dest.write_text(json.dumps(reading(m, rows[m["number"]], verdict, laid), indent=1,
                                               ensure_ascii=False) + "\n")
                    entry["reading"] = dest.name
        ledger[h] = entry
        print(f"{p.name}: " + (f"No {m['number']} ({m['how']}), " if m["number"] is not None else "")
              + (f"{entry['agreed']}/{entry['clues']} clues read" if "agreed" in entry else entry["why"]), file=out)
        (store / "ledger.json").write_text(json.dumps(ledger, indent=1, ensure_ascii=False) + "\n")
    return ledger


# ------------------------------------------------------------ the checklist

def filed_numbers(root=ROOT):
    return {int(p.stem.split("-")[1]) for p in (root / "puzzles" / lp.SERIES).glob("*/listener-*.json")}


def checklist(idx=None, store=STORE, root=ROOT):
    """The checklist page: every Listener the magazine printed, earliest
    first, with what the inbox and the corpus hold of each."""
    idx = index() if idx is None else idx
    filed = filed_numbers(root)
    ledger = load_ledger(store)
    tried = {}
    for e in ledger.values():
        if e.get("number") is not None:
            tried.setdefault(e["number"], []).append(e)
    lost = [e for e in ledger.values() if e.get("number") is None]
    got = {}
    for p in store.glob("listener-*.json"):
        r = json.loads(p.read_text())
        got[r["number"]] = r["verdict"]
    todo = [r for r in idx if r["number"] not in filed and r["number"] not in got]
    first = todo[0] if todo else None
    e = html.escape
    out = [f"""<!doctype html><meta charset="utf-8"><title>Listener crosswords to save from Gale</title>
<style>body{{font:14px -apple-system,sans-serif;margin:2em;max-width:60em}}td,th{{padding:2px 8px;text-align:left}}
tr:nth-child(even){{background:#f4f4f4}}h2{{margin-top:1.5em}}.got{{color:#070}}.bad{{color:#a00}}</style>
<h1>Listener crosswords to save from Gale: {len(todo):,} of {len(idx):,} to go</h1>
<p>Generated {datetime.datetime.now().astimezone():%Y-%m-%d %H:%M %Z} by <code>tools/gale_listener.py</code> from the
Listener Team's index (numbers and dates only) and what this folder holds. Earliest first: start at the top.</p>
<h2>How to save one</h2>
<ol>
<li>Be on an Alberta internet connection (home Wi-Fi works): the portal lets Albertans in by location, with no card or login.</li>
<li>Open <a href="{PORTAL}">the Alberta Research Portal</a> and choose <i>The Listener Historical Archive</i>.
A Gale link opened outside the portal asks for a password, so always start here.</li>
<li>Find the issue: <i>Browse &rarr; Browse By Date</i>, pick the date from the list below, and page through it
to the crossword (a grid with ACROSS and DOWN clue lists); or search for its title in quotes.</li>
<li>On the crossword's page press <i>Download</i> and save it (PDF or image, either works) into this folder,
{e(FOLDER)}. Any file name works; a name with the date (e.g. <code>1930-04-09</code>) is the surest match.</li>
<li>That's all. Each full pass reads new files once; the row below then says how many clues read.</li>
</ol>
<p>Gale's terms allow up to 50 downloads a session, by hand only: no scripts or download tools.</p>
{f'<p><b>Next to save:</b> No {first["number"]}, {first["date"]:%a %d %b %Y}, &ldquo;{e(first["title"])}&rdquo;.</p>' if first else ''}"""]
    years = {}
    for r in idx:
        years.setdefault(r["date"].year, []).append(r)
    for y, rs in sorted(years.items()):
        left = sum(1 for r in rs if r["number"] not in filed and r["number"] not in got)
        out.append(f"<h2>{y}: {left} of {len(rs)} to save</h2><table><tr><th>Issue date</th><th>No</th>"
                   "<th>Title</th><th>Setter</th><th>Status</th></tr>")
        for r in rs:
            n = r["number"]
            if n in filed:
                status = '<span class="got">filed</span>'
            elif n in got:
                v = got[n]
                status = f'<span class="got">saved: {v.get("agreed", 0)} of {v.get("clues", 0)} clues read</span>'
            elif n in tried:
                status = f'<span class="bad">saved, not read: {e(tried[n][-1].get("why") or "")}</span>'
            else:
                status = ""
            out.append(f"<tr><td>{r['date']:%a %d %b %Y}</td><td>{n}</td><td>{e(r['title'])}</td>"
                       f"<td>{e(r.get('setter') or '')}</td><td>{status}</td></tr>")
        out.append("</table>")
    if lost:
        out.append("<h2>Files that matched no puzzle</h2><p>Rename each with its issue date (e.g. 1930-04-09).</p><ul>")
        out += [f"<li>{e(m['file'])}: {e(m.get('why') or '')}</li>" for m in lost]
        out.append("</ul>")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="mirror the Mac inbox, read new pages, publish the checklist there")
    rd = sub.add_parser("read", help="read a local folder of pages")
    rd.add_argument("--inbox", type=Path, default=MIRROR)
    rd.add_argument("--store", type=Path, default=STORE)
    cl = sub.add_parser("checklist", help="write the checklist")
    cl.add_argument("--out", type=Path, default=CHECKLIST)
    cl.add_argument("--store", type=Path, default=STORE)
    mt = sub.add_parser("match", help="which puzzle each file is")
    mt.add_argument("files", nargs="+", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "match":
        idx = index()
        for f in a.files:
            m = match(f, idx)
            print(f"{f.name}: " + (f"No {m['number']}, {m['date']} ({m['how']})" if m["number"] is not None
                                   else f"unmatched ({m['why']})") + f", {len(m['pages'])} page image(s)")
        return 0
    if a.cmd == "checklist":
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(checklist(store=a.store))
        print(f"wrote {a.out}")
        return 0
    if a.cmd == "sync":
        gi.mirror(host_inbox=gi.LISTENER_INBOX, into=MIRROR)
    run(a.inbox if a.cmd == "read" else MIRROR, a.store if a.cmd == "read" else STORE)
    if a.cmd == "sync":
        CHECKLIST.parent.mkdir(parents=True, exist_ok=True)
        CHECKLIST.write_text(checklist())
        gi.publish(CHECKLIST, host_inbox=gi.GALE_ROOT)
        print(f"checklist published to {gi.GALE_ROOT}/{CHECKLIST.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
