#!/usr/bin/env python3
"""The Times Jumbo cryptics (1997-2014) read from the Saturday Times pages
tools/gale_fetch.py downloads from Gale's Times Digital Archive, one
GALE_<docId>.pdf each in <Gale crosswords>/TimesJumbo/Fetched (no edition
layout, like the Listener's and the Times' Fetched folders).

A page's citation ('"Jumbo Crossword 392." Times, 9 Mar. 2002, p. 68')
gives its date and mostly its number ("Jumbo Crossword." alone from 2012: the
number is then read off the page's prize text, "sent to: Jumbo 1,033"; gale_jumbo's
date_of is a holiday out at times, so it is never taken). The clue lists are
cut and read as tools/gale_listener.py reads a Saturday Times page's Listener
block (its title words swapped for "Jumbo Crossword"), the grid is read off
the page's largest square patch of ink (trove_grid), and a light the clues
do not reach is filed blank, so only a puzzle with every clue filed (fa.complete).
The solution is printed in a later issue as its own article, which is not
fetched, so the file is unsolved; puzzles/timesjumbo's held numbers are never
written over.

    python3 tools/gale_jumbo_read.py read NAME     # read one saved page
    python3 tools/gale_jumbo_read.py plan          # the pages not yet read

The standing pass plans each unread page as a unit (tools/edition_queue.py,
paper "listener", rel "jumbo:NAME"), ahead of the Listener's own pages.
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path
import downloads
import gale_inbox as gi
import file_archive_org_puzzles as fa

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
SERIES = "timesjumbo"
TOOL = "tools/gale_jumbo_read.py"
SAVED = downloads.GALE_CROSSWORDS / "TimesJumbo" / "Fetched"
STORE = Path(os.path.expanduser("~/.cache/gale_jumbo"))
LEDGER = "ledger.jsonl"
#: Bumped when the reading changes, so every page is read again.
VERSION = 1
PREFIX = "jumbo:"
CITED = re.compile(r'^\W*"([^"]*)"\s*Times\b\W*([0-3]?\d)\s+' + gi.MON + r"\s*(\d{4})", re.IGNORECASE)
CITED_NUMBER = re.compile(r"jumbo\s+cross\s?word\W{0,3}(?:n[o0]\W{0,3})?(\d[\d,. ]{0,5})", re.IGNORECASE)
ENTRY = re.compile(r"sent\s+to\W+jumbo\s+(?:cross\s?word\s+)?(\d[\d,. ]{0,5})", re.IGNORECASE)
TITLE_WORD = re.compile(r"^\W*j?umbo\W*$", re.IGNORECASE)
#: The Jumbo numbers the Times printed to 2014.
NUMBERS = range(100, 1100)
#: A grid on the page, in the page's pixels: 23x23 or 27x27 cells.
GRID_PX = (600, 3600)


def figure(text):
    n = int(re.sub(r"\D", "", text or "") or 0)
    return n if n in NUMBERS else None


def cite_of(cite):
    """(number or None, date) the page's citation gives, or None."""
    m = CITED.search(re.sub(r"\s+", " ", cite or ""))
    if not m:
        return None
    n = CITED_NUMBER.search(m.group(1))
    day = datetime.date(int(m.group(4)), gi.MONTHS[m.group(3)[:3].lower()], int(m.group(2)))
    return (figure(n.group(1)) if n else None), day


def page_files(saved=SAVED):
    d = Path(saved)
    return sorted(p for p in d.iterdir() if p.suffix.lower() == ".pdf" and p.is_file()
                  and not p.name.startswith(".")) if d.is_dir() else []


def load_ledger(store=STORE):
    out = {}
    path = Path(store) / LEDGER
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            out[row["file"]] = row
    return out


def append_row(row, store=STORE):
    Path(store).mkdir(parents=True, exist_ok=True)
    with open(Path(store) / LEDGER, "a") as f:
        f.write(json.dumps(row) + "\n")


def plan(saved=SAVED, store=STORE):
    """One unit per saved page not read at VERSION, newest first."""
    done = load_ledger(store)
    reason = "never read (Gale fetch)"
    todo = [p for p in page_files(saved) if (done.get(p.name) or {}).get("version") != VERSION]
    todo.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"rel": PREFIX + p.name, "rank": fa.RANKS[reason], "reason": reason, "needs": []} for p in todo]


def grid_box(img):
    """The page's largest grid-shaped patch of ink, or None."""
    boxes = [b for b in gi.page_grids(img) if GRID_PX[0] <= b[2] - b[0] <= GRID_PX[1]]
    return max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])) if boxes else None


def number_of(img, key, cited, words):
    import ocr_clues
    if cited and cited[0]:
        return cited[0], "citation"
    text = ocr_clues.lines_of(words)
    for m in ENTRY.finditer(text):
        if figure(m.group(1)):
            return figure(m.group(1)), "prize text"
    return None, None


def read_page(path, store=STORE):
    """(verdict, puzzle or None) of one saved page."""
    import gale_listener as gl
    import archive_org_jumbo as aj
    import trove_grid
    img, cite = gi.images(path)[0]
    verdict = {"file": path.name}
    cited = cite_of(cite)
    if not cited:
        verdict["refused"] = "no Times citation on the page"
        return verdict, None
    day = cited[1]
    key = gl.image_key(img)
    words = gl.page_words(img, key)
    n, how = number_of(img, key, cited, words)
    if n is None:
        verdict["refused"] = "no Jumbo number in the citation or the prize text"
        return verdict, None
    verdict.update(number=n, numberFrom=how, date=day.isoformat())
    box = grid_box(img)
    if box is None:
        verdict["refused"] = "no grid on the page"
        return verdict, None
    gpath = Path(store) / "grids" / f"{path.stem}.png"
    gpath.parent.mkdir(parents=True, exist_ok=True)
    img.crop((box[0] - 6, box[1] - 6, box[2] + 6, box[3] + 6)).save(gpath)
    g, why = trove_grid.read_grid(gpath)
    if not g:
        verdict["refused"] = f"grid unread: {why}"
        return verdict, None
    old = gl.TITLE_WORD
    gl.TITLE_WORD = TITLE_WORD
    try:
        blocks = gl.times_blocks(img, key)
    finally:
        gl.TITLE_WORD = old
    if not blocks:
        verdict["refused"] = "no Jumbo clue lists found on the page"
        return verdict, None
    read, laid = gl.times_read(blocks)
    verdict.update({k: v for k, v in read.items() if k in ("agreed", "clues", "refused")})
    if laid is None:
        return verdict, None
    laid, blank = aj.lay_on(dict(laid), g)
    verdict["lights"] = len(laid)
    verdict["blank"] = sorted(blank)
    doc = gi.DOC_ID.search(path.name)
    url = f"https://link.gale.com/apps/doc/{doc.group(1).upper()}/TTDA?sid=bookmark-TTDA" if doc else None
    puzzle = fa.build(n, day, g, "image", laid, None, 0, series=SERIES, name=f"Times jumbo cryptic crossword No {n:,}",
                      url=url)
    verdict["whole"] = bool(fa.complete(puzzle))
    return verdict, puzzle


def read_unit(rel, saved=SAVED, store=STORE):
    """Read one saved page (a unit's rel, "jumbo:NAME" or NAME), file its
    puzzle when whole and no file holds the number; the ledger row appended.
    Returns "read", "current" or "failed"."""
    import scan_queue
    from fetch_puzzle import puzzle_path, write_puzzle_file
    name = rel[len(PREFIX):] if rel.startswith(PREFIX) else rel
    path = Path(saved) / name
    if not path.exists() or (load_ledger(store).get(name) or {}).get("version") == VERSION:
        return "current"
    try:
        verdict, puzzle = read_page(path, store)
    except Exception as e:  # any raise: a bad page is a verdict
        verdict, puzzle = {"file": name, "refused": f"crashed: {type(e).__name__}: {e}"}, None
        print(verdict["refused"], file=sys.stderr)
    if puzzle is not None and verdict.get("whole"):
        target = puzzle_path(SERIES, verdict["number"])
        if target.exists():
            verdict["skip"] = "already held"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            scan_queue.file_puzzle(write_puzzle_file, TOOL, target, puzzle, verdict)
    append_row({**verdict, "version": VERSION}, store)
    print(json.dumps(verdict))
    return "read"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["plan"]:
        print(len(plan()))
        return 0
    if argv[:1] == ["read"] and len(argv) > 1:
        print(read_unit(argv[1]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
