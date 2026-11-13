#!/usr/bin/env python3
"""The TLS (Times Literary Supplement) crosswords, 1992-2014, read from the
pages tools/gale_fetch.py downloads from Gale's TLS Historical Archive, one
GALE_<docId>.pdf each in <Gale crosswords>/TLS/Fetched (no edition layout,
like the Times Jumbo's Fetched folder, whose reader this one follows).

A page's citation ('"TLS Crossword 1018." Times Literary Supplement, 28 Mar.
2014, p. 31') gives its number and date. The clue lists are cut and read as
tools/gale_jumbo_read.py reads a Jumbo page (its title words swapped for "TLS
Crossword"), the grid is the page's 15x15 patch of ink (trove_grid), and a
light the clues do not reach is filed blank, so only a puzzle with every clue
filed (fa.complete) is written. The file is unsolved; puzzles/tls' held
numbers are never written over.

    python3 tools/gale_tls_read.py read NAME     # read one saved page
    python3 tools/gale_tls_read.py plan          # the pages not yet read

The standing pass plans each unread page as a unit (tools/edition_queue.py,
paper "listener", rel "tls:NAME"), after the Jumbo's pages.
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
import gale_jumbo_read as jr

TOOLS = Path(__file__).resolve().parent
SERIES = "tls"
TOOL = "tools/gale_tls_read.py"
SAVED = downloads.GALE_CROSSWORDS / "TLS" / "Fetched"
STORE = Path(os.path.expanduser("~/.cache/gale_tls"))
LEDGER = "ledger.jsonl"
#: Bumped when the reading changes, so every page is read again.
VERSION = 1
PREFIX = "tls:"
CITED = re.compile(r'^\W*"([^"]*)"\s*Times\s+Literary\s+Supplement\b\W*([0-3]?\d)\s+' + gi.MON + r"\s*(\d{4})",
                   re.IGNORECASE)
CITED_NUMBER = re.compile(r"t\W?l\W?s\s+cross\s?w[a-z]{0,3}d\W{0,3}(?:n[o0]\W{0,3})?(\d[\d,. ]{0,5})", re.IGNORECASE)
TITLE_WORD = re.compile(r"^\W*t\W?l\W?s\W*$", re.IGNORECASE)
#: The TLS numbers printed 1992-2014 (No 102 on 5 June 1992; 1,396 and up are the-tls.com's).
NUMBERS = range(100, 1400)
SIZES = (15,)
CRASH_LIMIT = jr.CRASH_LIMIT


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
    return jr.page_files(saved)


def load_ledger(store=STORE):
    return jr.load_ledger(store)


def append_row(row, store=STORE):
    jr.append_row(row, store)


def read_done(row):
    """Whether a ledger row is a verdict of this VERSION (a crashed attempt under CRASH_LIMIT is not)."""
    return bool(row) and row.get("version") == VERSION and not (
        row.get("failed") and row.get("attempts", 1) < CRASH_LIMIT)


def plan(saved=SAVED, store=STORE):
    """One unit per saved page not read at VERSION (or whose last attempt crashed), newest first."""
    done = load_ledger(store)
    reason = "never read (Gale fetch)"
    todo = [p for p in page_files(saved) if not read_done(done.get(p.name))]
    todo.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"rel": PREFIX + p.name, "rank": fa.RANKS[reason], "reason": reason, "needs": []} for p in todo]


def pick_grid(boxes, reader, pads=(6, 0.08)):
    """(box, grid, None) of the first of `boxes` whose `reader(box, pad)` reads a 15x15 lattice, else
    (None, None, why of the first refusal)."""
    first = None
    for box in boxes:
        for pad in pads:
            g, why = reader(box, pad if pad >= 1 else int(pad * (box[2] - box[0])))
            if g and len(g) in SIZES:
                return box, g, None
            if first is None:
                first = why if not g else f"the grid on the page is {len(g)}x{len(g)}, not a TLS's"
            if g:
                break
    return None, None, first


def read_page(path, store=STORE, asker=None):
    """(verdict, puzzle or None) of one saved page. `asker` stands in for the VLM (jr.vlm_mended)."""
    import gale_listener as gl
    import archive_org_jumbo as aj
    import trove_grid
    img, cite = gi.images(path)[0]
    verdict = {"file": path.name}
    cited = cite_of(cite)
    if not cited:
        verdict["refused"] = "no TLS citation on the page"
        return verdict, None
    day = cited[1]
    if cited[0] is None:
        verdict["refused"] = "no TLS number in the citation"
        return verdict, None
    n = cited[0]
    key = gl.image_key(img)
    verdict.update(number=n, numberFrom="citation", date=day.isoformat())
    boxes = jr.grid_boxes(img)
    if not boxes:
        verdict["refused"] = "no grid on the page"
        return verdict, None
    gpath = Path(store) / "grids" / f"{path.stem}.png"
    gpath.parent.mkdir(parents=True, exist_ok=True)

    def reader(box, pad):
        img.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(img.width, box[2] + pad),
                  min(img.height, box[3] + pad))).save(gpath)
        return trove_grid.read_grid(gpath)

    box, g, why = pick_grid(boxes, reader)
    if not g:
        box, g, again = pick_grid(jr.extra_boxes(img, boxes), reader)
        why = again or why
    if not g:
        verdict["refused"] = f"grid unread: {why}"
        return verdict, None
    old, old_titles, old_cuts = gl.TITLE_WORD, gl.times_titles, gl.times_cuts
    gl.TITLE_WORD = TITLE_WORD
    gl.times_titles = jr.with_fallback_title(old_titles, img.width)
    gl.times_cuts = jr.widest_cuts(old_cuts, gl)
    try:
        blocks = gl.times_blocks(img, key)
    finally:
        gl.TITLE_WORD, gl.times_titles, gl.times_cuts = old, old_titles, old_cuts
    if not blocks:
        verdict["refused"] = "no TLS clue lists found on the page"
        return verdict, None
    lengths = {f"{k[0]}-{k[1]}": len(cells) for k, cells in aj.rg.light_cells(g).items()}
    read, laid = gl.times_read(blocks, lengths)
    verdict.update({k: v for k, v in read.items() if k in ("agreed", "clues", "refused")})
    if laid is None:
        return verdict, None
    voted = dict(laid)
    laid, blank = aj.lay_on(dict(laid), g)
    verdict["lights"] = len(laid)
    blank = {**(read.get("blank") or {}), **blank}
    tails = {t for _, _, group in laid.values() for t in (group or [])[1:]}
    for lid, (text, _, _) in laid.items():
        if lid not in tails and not (text or "").strip():
            blank.setdefault(lid, jr.UNLAID)
    laid, blank, asked = jr.vlm_mended(blocks, laid, blank, lengths, gl, asker, voted)
    if asked:
        verdict["vlmColumns"] = asked
    verdict["lights"] = len(laid)
    verdict["blank"] = sorted(blank)
    verdict["why"] = {k: str(v)[:80] for k, v in sorted(blank.items())}
    doc = jr.DOC_ID.search(path.name.upper())
    url = f"https://link.gale.com/apps/doc/{doc.group(0)}/TLSH?sid=bookmark-TLSH" if doc else None
    puzzle = fa.build(n, day, g, "image", laid, None, 0, series=SERIES, name=f"TLS crossword No {n:,}",
                      url=url, printed=read.get("asPrinted"))
    verdict["whole"] = bool(fa.complete(puzzle))
    return verdict, puzzle


def read_unit(rel, saved=SAVED, store=STORE):
    """Read one saved page (a unit's rel, "tls:NAME" or NAME), file its puzzle when whole and no file holds
    the number; the ledger row appended. Returns "read", "current" or "failed"."""
    import scan_queue
    from fetch_puzzle import puzzle_path, write_puzzle_file
    name = rel[len(PREFIX):] if rel.startswith(PREFIX) else rel
    path = Path(saved) / name
    before = load_ledger(store).get(name)
    if not path.exists() or read_done(before):
        return "current"
    try:
        verdict, puzzle = read_page(path, store)
    except Exception as e:  # any raise: the page stays due (read_done) until CRASH_LIMIT attempts
        attempts = (before or {}).get("attempts", 0) + 1
        verdict, puzzle = {"file": name, "failed": f"crashed: {type(e).__name__}: {e}", "attempts": attempts}, None
        print(verdict["failed"], file=sys.stderr)
        append_row({**verdict, "version": VERSION if attempts >= CRASH_LIMIT else None}, store)
        return "failed"
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
