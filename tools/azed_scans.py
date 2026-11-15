#!/usr/bin/env python3
"""File the Azeds the SUNDAY magazine (Kolkata, Hindusthan Standard) printed in 1974-76, from the Digital Library
of India's page scans on archive.org (downloads.AZED_SCANS: <item>/leaf_NNNN.jpg, djvu.xml.gz, pages.json).

    python3 tools/azed_scans.py numbers            # each page's puzzle number, with the readings behind it
    python3 tools/azed_scans.py read [N ...]       # read and print each puzzle's verdict, file nothing
    python3 tools/azed_scans.py file [N ...]       # file what reads whole

Each page carries the week's puzzle (heading, clues, a blank barred 12x12 grid) and the PREVIOUS week's solution
grid and notes in a box: the solution to No N is on the page of No N+1.

  - The page's number is read off its lines: "AZED CROSSWORD No. N", the title line "No.N: ...", and the notes
    heading "AZED No N Solution and notes" (N+1). Readings that disagree, or out of the item's range, refuse the page.
  - The clue columns are found from the djvu layout and read by every ocr_clues.READERS reader and voted, as
    tools/privateeye_scans.py does for the Eye: a clue the readings do not agree on is blank and the puzzle is not
    filed (no puzzle is filed with a blank clue).
  - The puzzle's grid is the 12x12 lattice on the page that is not the solution grid (the one by the notes heading);
    tools/ios_barred.py fits its bars as mirror pairs, the clue lists settling the unsure ones. It stands only when
    every listed clue lies on a light of its length and every light has a clue.
  - The answers are read off the next page's solution grid (ios_barred.solution_reads): a light with a sure word
    is answered, the rest left. A puzzle filed with some answers is partly answered.
  - The file has a "year" only: the weeks are counted from the Observer dates we hold (puzzle_year), the magazine
    ran them about ten months late.
"""
import datetime
import gzip
import json
import re
import sys
import xml.etree.ElementTree as ET

import downloads

TOOL = "tools/azed_scans.py"
SERIES = "azed"
#: The printed numbers an item holds (the notes' brief), a little wide: a reading outside is a misread.
RANGES = {"dli.bengal.10689.22028": (42, 50), "dli.bengal.10689.23415": (72, 111),
          "dli.bengal.10689.13117": (87, 102), "dli.bengal.10689.15514": (109, 155),
          "dli.bengal.10689.20788": (156, 173)}
#: Rows (in word heights) the solution grid may lie from the notes heading, and the margin cut round a grid.
NOTES_HEAD = re.compile(r"solu\w*\s+and\s+notes", re.IGNORECASE)
SOLVED = re.compile(r"\bAZED\s+(?!CROSS)N\w?\W{0,3}\s*(\d{1,3}(?:\s\d{1,2})?)\W", re.IGNORECASE)
TITLED = re.compile(r"^\W{0,2}N[o0]\W{0,3}(\d{2,3})\W")
CROSSED = re.compile(r"\bAZED\W*\s*CROSSWORD\W{0,3}\s*N\w?\W{0,3}\s*(\d{1,3}(?:\s\d{1,2})?)\b", re.IGNORECASE)
MARGIN = 40
#: Numbers of weeks apart that the Observer's puzzle and a number's anchor lie: Azed is weekly.
WEEK = datetime.timedelta(days=7)


def item_dir(item):
    return downloads.AZED_SCANS / item


def items():
    return json.loads((downloads.AZED_SCANS / "index.json").read_text())


_OBJECTS = {}


def objects(item):
    """The item's OBJECT elements, one per leaf, in order (parsed once)."""
    if item not in _OBJECTS:
        with gzip.open(item_dir(item) / "djvu.xml.gz") as f:
            root = ET.fromstring(f.read())
        _OBJECTS[item] = list(root.iter("OBJECT"))
    return _OBJECTS[item]


def lines_of(item, leaf):
    """privateeye_scans.page_lines of one leaf."""
    import privateeye_scans as pes
    return pes.page_lines(ET.tostring(objects(item)[leaf]))


def to_number(text):
    return int(text.replace(" ", ""))


def readings(lines):
    """{"notes": [M], "titled": [N], "crossed": [N]}: the numbers the page's lines name; M is the number of the
    puzzle whose solution and notes the page prints (N less the item's lag, 2 but for item 22028's 1)."""
    out = {"notes": [], "titled": [], "crossed": []}
    for ws in lines:
        text = " ".join(w[4] for w in ws)
        for m in SOLVED.finditer(text):
            out["notes"].append(to_number(m.group(1)))
        for m in CROSSED.finditer(text):
            out["crossed"].append(to_number(m.group(1)))
        m = TITLED.match(text)
        if m:
            out["titled"].append(int(m.group(1)))
    return out


def pages():
    """[(item, leaf)] of every page index.json lists, item by item."""
    return [(item, leaf) for item, meta in items().items() for leaf in meta["pages"]]


def item_lag(item, got):
    """How many puzzles the solution on a page lies behind the page's own: the commonest titled - notes of the
    item's pages that print both (2, item 22028's 1)."""
    gaps = [t - m for g in got.values() for t in g["titled"] for m in g["notes"] if 0 < t - m < 4]
    return max(set(gaps), key=gaps.count) if gaps else 2


def candidates(item, g, lag):
    """The numbers a page's readings name (in the item's range), the notes' made the page's by the lag."""
    lo, hi = RANGES[item]
    seen = set(g["titled"]) | set(g["crossed"]) | {m + lag for m in g["notes"]}
    return {n for n in seen if lo <= n <= hi}


def numbering(item):
    """({leaf: number}, {leaf: why not}, {leaf: readings}, lag) of an item's pages. A page whose readings agree
    has its number; one whose readings differ takes the one candidate that lies between its neighbours' numbers
    (the pages run one way, up or down); one that names none takes the number between neighbours two apart."""
    leaves = items()[item]["pages"]
    got = {leaf: readings(lines_of(item, leaf)) for leaf in leaves}
    lag = item_lag(item, got)
    cands = {leaf: candidates(item, got[leaf], lag) for leaf in leaves}
    got_number = {leaf: next(iter(c)) for leaf, c in cands.items() if len(c) == 1}
    sure = [(leaf, got_number[leaf]) for leaf in leaves if leaf in got_number]
    up = len(sure) > 1 and (sure[-1][1] - sure[0][1]) * (sure[-1][0] - sure[0][0]) > 0
    out, why = {}, {}
    for k, leaf in enumerate(leaves):
        before = [n for l, n in sure if l < leaf]
        after = [n for l, n in sure if l > leaf]
        lo, hi = (before[-1] if before else None), (after[0] if after else None)
        if not up:
            lo, hi = hi, lo
        if leaf in got_number:
            out[leaf] = got_number[leaf]
            continue
        inside = [n for n in cands[leaf] if (lo is None or lo < n) and (hi is None or n < hi)]
        if len(inside) == 1:
            out[leaf] = inside[0]
        elif not cands[leaf] and lo is not None and hi is not None and hi - lo == 2:
            out[leaf] = lo + 1
        else:
            why[leaf] = (f"the headings disagree: {sorted(cands[leaf])}" if cands[leaf]
                         else "no heading names a number in the item's range")
    return out, why, got, lag


def numbered():
    """({number: [(item, leaf)]}, {(item, leaf): why not}, {(item, leaf): readings}) of every page."""
    by, why, seen = {}, {}, {}
    for item in items():
        out, bad, got, lag = numbering(item)
        for leaf, n in out.items():
            by.setdefault(n, []).append((item, leaf))
        for leaf in bad:
            why[(item, leaf)] = bad[leaf]
        for leaf, g in got.items():
            seen[(item, leaf)] = dict(g, lag=lag, number=out.get(leaf))
    return by, why, seen


# ---------------------------------------------------------------- the year

def held_dates():
    """{number: date} of the Azeds the corpus holds (puzzles/azed/<year>/azed-N.json)."""
    from pathlib import Path
    out = {}
    for path in sorted((Path(__file__).resolve().parent.parent / "puzzles" / SERIES).glob("*/azed-*.json"))[:40]:
        p = json.loads(path.read_text())
        if p.get("date"):
            out[p["number"]] = datetime.date.fromisoformat(p["date"])
    return out


def puzzle_year(number, held):
    """The year the Observer printed Azed `number`, counting weeks from the nearest held one."""
    near = min(held, key=lambda n: abs(n - number))
    return held[near] + WEEK * (number - near)


# ---------------------------------------------------------------- the grids

#: A grid box this far from square (long side over short) is no Azed grid; one smaller (pixels a side) is a thumbnail.
SQUARE = 1.15
SMALLEST = 240


def spans(rules):
    """[(first, last)] of every 12-cell stretch of the rules found `rules` (pixels, ascending) could be, at their
    median pitch: more than 12 cells found, each window of 13 rules; fewer (the outer rules lost to a clue column
    or a margin), the rules put out by the missing cells' pitch on either side."""
    import numpy as np
    n = len(rules) - 1
    if n < 4:
        return []
    pitch = float(np.median(np.diff(rules)))
    if n >= 12:
        return [(rules[i], rules[i + 12]) for i in range(n - 11)]
    return [(rules[0] - k * pitch, rules[-1] + (12 - n - k) * pitch) for k in range(12 - n + 1)]


def evened(gray, g):
    """listener_grid grid `g` re-read on an even 12x12 lattice (Azed is always 12x12): the rules found are counted
    wrong (13 columns, 11 rows) when a bar or a printed number reads as a rule or an outer rule is lost. Each
    12-cell stretch the rules could make (spans), and the grid's box, is read; the one with no blocks whose bars
    lie most symmetric stands. None when no frame is a square of a grid's size."""
    import ios_barred
    import listener_grid as lg
    import trove_grid
    ink = gray < trove_grid.otsu(gray)
    H, W = gray.shape
    bx0, by0, bx1, by1 = g["box"]
    frames = [(by0, by1, bx0, bx1)]
    if g.get("lattice"):
        ys, xs = g["lattice"]
        frames += [(a, b, c, d) for a, b in spans(list(ys)) for c, d in spans(list(xs))]
    best = None
    for y0, y1, x0, x1 in frames:
        y0, y1, x0, x1 = int(round(y0)), int(round(y1)), int(round(x0)), int(round(x1))
        h, w = y1 - y0, x1 - x0
        if y0 < 0 or x0 < 0 or y1 > H or x1 > W or min(h, w) < SMALLEST or max(h, w) > SQUARE * min(h, w):
            continue
        dark = lg.darkness(gray[y0:y1, x0:x1])
        ry = [round(i * h / 12) for i in range(13)]
        rx = [round(i * w / 12) for i in range(13)]
        rows, sides, thin = lg.read_box(ink[y0:y1, x0:x1], dark, ry, rx)
        if any("#" in r for r in rows) or not any(set(r) - {"."} for r in rows):
            continue  # text or a picture, no barred grid (Azed prints no blocks)
        share = ios_barred.symmetry(rows)
        if best is None or share > best[0]:
            best = (share, {"box": (x0, y0, x1, y1), "rows": rows, "why": None, "filled": 0.0, "sides": sides,
                            "thin": thin, "lattice": ([y + y0 for y in ry], [x + x0 for x in rx])})
    return best[1] if best else None


def find_twelve(gray):
    """Every 12x12 grid of the page `gray`: those listener_grid found so, the others (a lattice of 13x11 rules, or
    none) re-read evenly over their frames (evened)."""
    import listener_grid as lg
    out = []
    for g in lg.find_grids(gray):
        if g.get("rows") and len(g["rows"]) == 12 and all(len(r) == 12 for r in g["rows"]) and g.get("lattice"):
            out.append(g)
            continue
        e = evened(gray, g)
        if e is not None:
            out.append(e)
    return out


def grids_of(img, lines):
    """(puzzle grid, solution grid): the page's two 12x12 lattices of rules (listener_grid dicts), the solution
    the one nearest the notes heading; None for either not found."""
    import numpy as np
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    found = find_twelve(gray)
    head = [(ws[0][0], ws[0][1]) for ws in lines if NOTES_HEAD.search(" ".join(w[4] for w in ws))]
    if not found:
        return None, None
    if not head or len(found) < 2:
        return max(found, key=area), None
    hx, hy = head[0]
    near = min(found, key=lambda g: abs(g["box"][0] - hx) + abs(g["box"][1] - hy))
    rest = [g for g in found if g is not near]
    return max(rest, key=area), near


def area(g):
    return (g["box"][2] - g["box"][0]) * (g["box"][3] - g["box"][1])


#: Rows starting this far (pixels) right of a clue column's left edge are not its own lines.
OWN_LINES = 120
#: A split piece of a clue line starts within this many pixels of the piece before it.
JOIN = 60


def clipped(boxes, lines):
    """`boxes` (privateeye_scans.columns) with each cut at the right edge of its own lines: Azed prints one clue
    column, so the box ran to the page's edge (the notes box with its own ACROSS and DOWN headings beside it) and
    its rows merged with those words. Its own lines are those that start at its left edge."""
    import privateeye_scans as pes
    rows = [pes.boxed(ws) for ws in lines]
    out = []
    for x0, y0, x1, y1 in boxes:
        mine = [r for r in rows if x0 <= r[0] + 8 <= x0 + OWN_LINES and y0 <= r[1] and r[3] <= y1]
        # A clue's line djvu split ("29 What" then "---- is lifeless? ... possibly) (4)") runs on from a line that starts at
        # the edge: the pieces butted against its end (within JOIN pixels, on its band) are its own too.
        grown = list(mine)
        for _ in range(4):
            more = [r for r in rows if r not in grown and y0 <= r[1] and r[3] <= y1 and any(
                0 <= r[0] - g[2] <= JOIN and r[1] < g[3] and g[1] < r[3] for g in grown)]
            if not more:
                break
            grown += more
        out.append((x0, y0, min(x1, max(r[2] for r in grown) + 8) if grown else x1, y1))
    return out


def by_grid(cols, rows):
    """`cols` (privateeye_scans.column_cols) with each reading's clue numbers put right by the grid's light order:
    a side whose reading prints as many numbered clues as the grid has lights there is renumbered in sequence, a
    number misread ("25" for 20) then no longer splits the readings. A side that does not match is left."""
    import privateeye_scans as pes
    import reconstruct_grid as rg
    lights = rg.light_cells(rows)
    want = [sorted(n for (n, d) in lights if d == side) for side in ("across", "down")]

    def wrapped(words):
        fixed = []
        for side, lines in enumerate(cols(words)):
            lines = list(lines)
            idx = [i for i, ln in enumerate(lines) if pes.CLUE_NUMBER.match(ln[4])]
            if len(idx) == len(want[side]):
                for i, n in zip(idx, want[side]):
                    m = pes.CLUE_NUMBER.match(lines[i][4])
                    lines[i] = lines[i][:4] + (lines[i][4][:m.start(1)] + str(n) + lines[i][4][m.end(1):],)
            fixed.append(lines)
        return fixed
    wrapped.named = cols.named
    return wrapped


def wanted_of_laid(laid):
    """ios_barred's `wanted` of the voted clues: [(numbers, direction, length)] of each single-light clue."""
    out = []
    for lid, (text, enum, group) in laid.items():
        n, d = lid.split("-")
        if group or re.match(r"See \d", text or ""):
            continue
        digits = [int(x) for x in re.findall(r"\d+", str(enum or ""))]
        out.append((frozenset([int(n)]), d, sum(digits) if digits else None))
    return out


def fitted(grid, laid):
    """(rows, None) or (None, why): the bars of the puzzle's lattice, set by the clue lists, kept when the lights
    are the listed clues' (each of its length) and no more."""
    import ios_barred
    import reconstruct_grid as rg
    rows, why = ios_barred.read_found(grid, wanted_of_laid(laid))
    if rows is None:
        return None, why
    lights = rg.light_cells(rows)
    for lid, (text, enum, group) in laid.items():
        n, d = lid.split("-")
        if (int(n), d) not in lights:
            shown = {s: sorted(k[0] for k in lights if k[1] == s) for s in ("across", "down")}
            return None, f"clue {lid} has no light on the grid (lights {shown}; clues {sorted(laid)})"
        digits = [int(x) for x in re.findall(r"\d+", str(enum or ""))]
        if not group and digits and sum(digits) != len(lights[(int(n), d)]) and not re.match(r"See \d", text or ""):
            return None, f"clue {lid} counts {sum(digits)} but its light is {len(lights[(int(n), d)])}"
    bare = sorted(f"{n}-{d}" for (n, d) in lights if f"{n}-{d}" not in laid)
    if bare:
        return None, f"lights with no clue: {', '.join(bare)}"
    return rows, None


def answers(img, lines, rows):
    """({(number, direction): word}, stats) off the solution grid of the page `img` (the next puzzle's)."""
    import ios_barred
    puzzle, solution = grids_of(img, lines)
    if solution is None:
        return {}, {"refused": "no solution grid by the notes heading"}
    x0, y0, x1, y1 = solution["box"]
    window = img.crop((max(0, x0 - MARGIN), max(0, y0 - MARGIN), x1 + MARGIN, y1 + MARGIN))
    return ios_barred.solution_reads(window, rows, find=find_twelve)


# ---------------------------------------------------------------- reading a page

def read_page(item, leaf, number):
    """(number, laid, grid rows, why not) of one page: the clues voted, the grid fitted."""
    import ocr_clues
    import privateeye_scans as pes
    from PIL import Image
    lines = lines_of(item, leaf)
    boxes = clipped(pes.columns(lines), lines)
    if not boxes:
        return number, None, None, "no clue columns found in the page's layout"
    path = item_dir(item) / f"leaf_{leaf:04d}.jpg"
    img = Image.open(path)
    words = {"djvu": [w for ws in lines for w in ws]}
    for which in ocr_clues.READERS:
        words[which] = []
        for b in boxes:
            words[which] += pes.column_words(img, b, which, f"azed_{item[-5:]}_{leaf}_{'-'.join(map(str, b))}")
    cols = pes.column_cols(boxes)
    grid, _ = grids_of(img, lines)
    if grid is not None:
        import ios_barred
        prelim, _ = ios_barred.read_found(grid, None)
        if prelim is not None:
            cols = by_grid(cols, prelim)
    verdict, laid = pes.voted(words, cols)
    if laid is None:
        return number, None, None, f"the readings do not parse: {verdict.get('refused')}"
    blank = verdict.get("blank") or {}
    deferred = ""
    if blank:
        laid, blank, deferred = pes.vlm_filled(img, boxes, words, cols, laid, blank)
    if blank:
        return number, None, None, f"{len(blank)} clues the readings do not agree on{deferred}: " + \
            "; ".join(f"{k}: {v}" for k, v in sorted(blank.items())[:4])
    laid = pes.linked_across(pes.directed_links(pes.named_links(laid, cols.named)))
    empty = sorted(lid for lid, (t, _, _) in laid.items() if not (t or "").strip())
    if empty:
        return number, None, None, f"clues with no words: {', '.join(empty)}"
    if grid is None:
        return number, laid, None, "no 12x12 lattice of rules on the page"
    rows, why = fitted(grid, laid)
    return number, laid, rows, why


def read_answers(by, seen, number, rows):
    """({(n, d): word}, note) off the page that prints puzzle `number`'s solution: the one whose notes heading
    names it, else the page of number + the item's lag."""
    from PIL import Image
    nxt = [k for k, g in seen.items() if number in g["notes"]] or by.get(number + 2, [])
    nxt = [k for k in nxt if seen[k]["number"] is not None]
    if len(nxt) != 1:
        return {}, "no one page prints the solution"
    item, leaf = nxt[0]
    img = Image.open(item_dir(item) / f"leaf_{leaf:04d}.jpg")
    got, stats = answers(img, lines_of(item, leaf), rows)
    return got, stats.get("refused") or f"{len(got)} of {stats.get('lights')} lights read"


# ---------------------------------------------------------------- building

def build(number, laid, rows, item, leaf, solved, year):
    """The puzzle of one read page (file_archive_org_puzzles.build), a year for its date, `solved` its answers."""
    import file_archive_org_puzzles as fa
    puzzle = fa.build(number, year, rows, "image", dict(laid), item, leaf, series=SERIES,
                      name=f"Azed No {number}", url=f"https://archive.org/details/{item}/page/n{leaf}/mode/1up")
    puzzle["date"] = year.isoformat()
    for e in puzzle["entries"]:
        word = solved.get((e["number"], e["direction"]))
        if word and not e.get("group") and len(word) == e["length"]:
            e["solution"] = word
        else:
            e.pop("solution", None)
    puzzle["source"] = {"publisher": "Observer", "url": puzzle["source"]["url"], "retrievedFrom": "archive.org",
                        "acquiredBy": TOOL, "acquiredOn": datetime.date.today().isoformat(),
                        "gridOrigin": "published"}
    return puzzle


def main(argv):
    mode, wanted = (argv[1] if len(argv) > 1 else "numbers"), {int(a) for a in argv[2:] if a.isdigit()}
    since = max([int(a[:-1]) for a in argv[2:] if a.endswith("+")], default=None)  # "165+": every page from 165
    by, why, seen = numbered()
    if mode == "numbers":
        for (item, leaf), g in seen.items():
            print(item[-5:], leaf, g["number"], g, why.get((item, leaf), ""))
        dup = {n: v for n, v in by.items() if len(v) > 1}
        print("numbers", len(by), "duplicates", dup, "unnumbered", len(why))
        return 0
    from fetch_puzzle import puzzle_path, write_puzzle_file
    held = held_dates()
    filed = partial = 0
    refused = {}
    for number in sorted(by):
        if (wanted or since is not None) and number not in wanted and not (since is not None and number >= since):
            continue
        # A number two scans hold (23415 and 13117 overlap) is read from each in turn, the first that reads whole.
        for item, leaf in by[number]:
            n, laid, rows, bad = read_page(item, leaf, number)
            if not bad and rows is not None:
                break
        if bad or rows is None:
            refused[number] = bad
            print(number, "refused:", bad)
            continue
        solved, note = read_answers(by, seen, number, rows)
        print(number, "whole;", note)
        if mode == "file":
            puzzle = build(number, laid, rows, item, leaf, solved, puzzle_year(number, held))
            try:
                write_puzzle_file(puzzle_path(SERIES, number), puzzle, generator=TOOL)
            except Exception as e:  # a refused write is that puzzle's reason, not the run's end
                refused[number] = f"the write was refused: {e}"
                print(number, refused[number])
                continue
        filed += 1
        partial += bool(solved)
    print(f"whole {filed}, with some answers {partial}, refused {len(refused)}")
    for n, w in sorted(refused.items()):
        print(" ", n, w)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
