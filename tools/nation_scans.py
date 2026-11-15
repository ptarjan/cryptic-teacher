#!/usr/bin/env python3
"""File the Nation crosswords (1926-49) from archive.org's page scans of the magazine (downloads.NATION_SCANS).

    python3 tools/nation_scans.py check 1948-01-03        # read one issue's puzzle, print the verdict, file nothing
    python3 tools/nation_scans.py file [--from DATE]      # file every issue's puzzle that reads whole (4 at a time)

scan_fetch.py nation keeps one folder per issue (djvu.xml.gz, leaf_NNNN.jpg, pages.json) and index.json, whose
per-issue `pages` are the leaves that name a crossword puzzle (the contents page and the puzzle's own).

  - The puzzle's leaf is the listed one that has clue columns; its heading "Crossword Puzzle No. N" names the
    number (near the weekly count from the printed No 244 of 1948-01-03, a reading far off is a misread).
  - The clue columns are read by every ocr_clues.READERS reader and voted, as tools/privateeye_scans.py does
    for the Eye: a clue the readings do not agree on is blank and the puzzle is not filed. The Nation's
    across list prints its numbers where the OCR loses them, so the clue numbers are set right by the grid's
    light order (azed_scans.by_grid) when the counts match.
  - The grid is the blocked square lattice listener_grid reads off the page (bars it thinks it sees are
    misreads: the Nation prints none). It stands only when every listed clue lies on a light of its length
    and every light has a clue.
  - The answers are the NEXT issue's "Solution to Puzzle No. N" list, printed as text: each word must fit its
    light and every crossing must agree, else the puzzle is filed with no answers (origin unsolved), as the
    thenation.com files are.
  - The number is the printed one (fetch_nation's 1-25 are its own series of 2009 reprints); an issue whose DATE
    we already hold from thenation.com is skipped, and a printed number held for another date is refused.
"""
import datetime
import gzip
import json
import multiprocessing
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import downloads

TOOL = "tools/nation_scans.py"
SERIES = "nation"
#: The printed number the weekly count is anchored on, and how far a heading may lie from the count.
ANCHOR = (datetime.date(1948, 1, 3), 244)
REACH = 12
HEADING = re.compile(r"cross\W?word\s+puzzle\W{0,3}\s*n[o0]\W{0,3}\s*(\d{1,4})\b", re.IGNORECASE)
SOLVED = re.compile(r"solution\s+to\s+(?:cross\W?word\s+)?puzzle\W{0,3}\s*n[o0]\W{0,3}\s*(\d{1,4})\b", re.IGNORECASE)
#: Days apart the issue printing a solution lies from the puzzle's.
NEXT_WITHIN = 21
SQUARES = (13, 15, 17, 19, 21, 11, 9)


def items():
    """{date: meta} of the issues whose crossword pages were fetched (index.json `pages` not empty)."""
    return {d: m for d, m in all_issues().items() if m.get("pages")}


def item_dir(item):
    return downloads.NATION_SCANS / item


_OBJECTS = {}


def objects(item):
    """The item's OBJECT elements, one per leaf, in order (parsed once)."""
    if item not in _OBJECTS:
        with gzip.open(item_dir(item) / "djvu.xml.gz") as f:
            root = ET.fromstring(f.read())
        _OBJECTS[item] = list(root.iter("OBJECT"))
    return _OBJECTS[item]


def lines_of(item, leaf):
    import privateeye_scans as pes
    return pes.page_lines(ET.tostring(objects(item)[leaf]))


def text_of(ws):
    return " ".join(w[4] for w in ws)


# ---------------------------------------------------------------- the number

def expected_number(day):
    return ANCHOR[1] + round((day - ANCHOR[0]).days / 7)


def number_of(lines, day):
    """The puzzle number the page's heading prints, or None. From 1944 on it must lie within REACH of the
    weekly count; the readings that do are voted (the commonest)."""
    seen = [int(m.group(1)) for ws in lines for m in HEADING.finditer(text_of(ws))]
    if day.year >= 1944:
        seen = [n for n in seen if abs(n - expected_number(day)) <= REACH]
    return max(set(seen), key=seen.count) if seen else None


def puzzle_leaf(item, leaves):
    """(leaf, lines) of the listed leaf that prints the puzzle: a heading and the most counted clue lines (the
    contents page names the puzzle too, with no clues)."""
    import privateeye_scans as pes
    best = None
    for leaf in leaves:
        lines = lines_of(item, leaf)
        if not any(HEADING.search(text_of(ws)) for ws in lines):
            continue
        size = sum(1 for ws in lines if pes.COUNTED.search(text_of(ws)))
        if size >= 8 and (best is None or size > best[0]):
            best = (size, leaf, lines)
    return (best[1], best[2]) if best else (None, None)


# ---------------------------------------------------------------- the grid

def blocked(rows):
    """`rows` with the bars listener_grid thinks it saw made plain cells: the Nation prints blocks only."""
    return ["".join("#" if c == "#" else "." for c in r) for r in rows]


def grids_of(img):
    """[(rows, box)] of every square blocked lattice listener_grid finds on the page, largest first."""
    import listener_grid as lg
    import numpy as np
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    out = []
    for g in lg.find_grids(gray):
        rows = g.get("rows")
        if not rows or len(rows) != len(rows[0]) or len(rows) not in SQUARES:
            continue
        if not all(len(r) == len(rows) for r in rows):
            continue
        x0, y0, x1, y1 = g["box"]
        out.append(((x1 - x0) * (y1 - y0), blocked(rows), tuple(g["box"])))
    return [(r, b) for _, r, b in sorted(out, key=lambda t: -t[0])]


#: Lines this many line heights apart end a clue column.
COLUMN_GAP = 5.0


def clue_boxes(lines, gbox):
    """[left, right] clue column boxes of a page printing its clues in two columns under the grid (the Nation's
    way): the grid's width cut in half, the right column ending over a solution list printed below it, each
    column ending at the first gap wider than COLUMN_GAP lines."""
    import privateeye_scans as pes
    x0, y0, x1, y1 = gbox
    mid = (x0 + x1) // 2
    rows = [pes.boxed(ws) for ws in lines]
    solved = [r[1] for r in rows if SOLVED.search(r[4]) and r[0] > mid - 100 and r[1] > y1]
    below = min(solved) - 10 if solved else 10 ** 6
    out = []
    for lo, hi in ((x0 - 20, mid), (mid, x1 + 20)):
        stop = below if lo >= mid else 10 ** 6
        mine = sorted((r for r in rows if lo <= r[0] < hi and y1 - 10 <= r[1] < stop), key=lambda r: r[1])
        if not mine:
            return []
        height = sorted(r[3] - r[1] for r in mine)[len(mine) // 2]
        bottom = mine[0][3]
        for r in mine:
            if r[1] - bottom > COLUMN_GAP * height:
                break
            bottom = max(bottom, r[3])
        out.append((min(r[0] for r in mine) - 10, y1 + 5, min(hi + 40, max(r[2] for r in mine) + 10),
                    min(bottom + 10, below if lo >= mid else 10 ** 6)))
    return out


def ordered_cols(cols, rows):
    """`cols` (privateeye_scans.column_cols) with each side's clues numbered by the grid's light order: the Nation's
    across list prints its numbers where the OCR loses them. A clue ends at the line that ends in a count; a side
    whose reading has as many clues as the grid has lights there is numbered in sequence (the numbers it has set
    right too), a side that does not match is left as read."""
    import privateeye_scans as pes
    import reconstruct_grid as rg
    lights = rg.light_cells(rows)
    want = [sorted(n for (n, d) in lights if d == side) for side in ("across", "down")]

    def wrapped(words):
        fixed = []
        for side, lines in enumerate(cols(words)):
            lines, starts, fresh = list(lines), [], True
            for i, ln in enumerate(lines):
                if fresh:
                    starts.append(i)
                fresh = bool(pes.COUNTED.search(ln[4]))
            if len(starts) == len(want[side]):
                for i, n in zip(starts, want[side]):
                    text = re.sub(r"^\W{0,2}\d{1,2}\W{0,2}\s+(?=[A-Za-z(\"'‘“])", "", lines[i][4])
                    lines[i] = lines[i][:4] + (f"{n} {text}",)
            fixed.append(lines)
        return fixed
    wrapped.named = cols.named
    return wrapped


def laid_fits(rows, laid):
    """None when the lights of `rows` are the listed clues' (each of its length) and no more, else why not."""
    import reconstruct_grid as rg
    lights = rg.light_cells(rows)
    for lid, (text, enum, group) in laid.items():
        n, d = lid.split("-")
        if (int(n), d) not in lights:
            shown = {s: sorted(k[0] for k in lights if k[1] == s) for s in ("across", "down")}
            return f"clue {lid} has no light on the grid (lights {shown}; clues {sorted(laid)})"
        digits = [int(x) for x in re.findall(r"\d+", str(enum or ""))]
        if not group and digits and sum(digits) != len(lights[(int(n), d)]) and not re.match(r"See \d", text or ""):
            return f"clue {lid} counts {sum(digits)} but its light is {len(lights[(int(n), d)])}"
    bare = sorted(f"{n}-{d}" for (n, d) in lights if f"{n}-{d}" not in laid)
    if bare:
        return f"lights with no clue: {', '.join(bare)}"
    return None


# ---------------------------------------------------------------- the answers

ANSWER = re.compile(r"(\d{1,2}(?:\s*(?:and|,|&)\s*\d{1,2})*)\s*[.:—\-]*\s*([A-Z][A-Z'’\- ]*?)"
                    r"(?=\s*[;:.,]|\s+\d{1,2}\b|\s*$)")


def solution_text(lines):
    """The words of a solution list from its heading's line: the lines below it in its column, down to a gap."""
    head = next((k for k, ws in enumerate(lines) if SOLVED.search(text_of(ws))), None)
    if head is None:
        return None, None
    number = int(SOLVED.search(text_of(lines[head])).group(1))
    hx, prev = min(w[0] for w in lines[head]), max(w[3] for w in lines[head])
    out = []
    for ws in lines[head + 1:head + 60]:
        x0, y0 = min(w[0] for w in ws), min(w[1] for w in ws)
        if y0 - prev > 130 or abs(x0 - hx) > 300 or y0 < prev - 200:
            break
        out.append(text_of(ws))
        prev = max(w[3] for w in ws)
    return number, " ".join(out)


def parse_solution(text):
    """([(numbers, word)] across, [...] down) of a printed solution list, the words as printed (letters, spaces)."""
    text = re.sub(r"-\s+(?=[A-Z])", "", text)
    parts = re.split(r"\bD\s?[O0]\s?W\s?N\b", text, maxsplit=1)
    if len(parts) != 2:
        return [], []
    across = re.split(r"\bACROSS\b", parts[0], maxsplit=1)[-1]
    sides = []
    for part in (across, parts[1]):
        got = []
        for m in ANSWER.finditer(part):
            nums = [int(x) for x in re.findall(r"\d+", m.group(1))]
            word = re.sub(r"[^A-Z]", "", m.group(2).upper())
            if word:
                got.append((nums, word))
        sides.append(got)
    return sides[0], sides[1]


def answers_for(rows, laid, across, down):
    """({light id: letters}, note): the printed words laid on the grid's lights. Each side is taken in order when
    it has as many words as leads (a misread number then does no harm), else by number. A word that does not fit
    its light's length is no answer; answers that disagree at a crossing are all dropped."""
    import reconstruct_grid as rg
    lights = rg.light_cells(rows)
    tails = {t for (_, _, g) in laid.values() if g for t in g[1:]}
    leads = {side: sorted(n for (n, d) in lights if d == side and f"{n}-{d}" not in tails)
             for side in ("across", "down")}
    group = {lid: (g or [lid]) for lid, (_, _, g) in laid.items()}
    words = {}
    for side, got in (("across", across), ("down", down)):
        if len(got) == len(leads[side]):
            pairs = [(n, w) for n, (_, w) in zip(leads[side], got)]
        else:
            pairs = [(nums[0], w) for nums, w in got if nums and nums[0] in leads[side]]
        for n, w in pairs:
            lid = f"{n}-{side}"
            lens = [len(lights[tuple(int(x) if x.isdigit() else x for x in k.split("-"))]) for k in group.get(lid, [lid])] \
                if lid in group else []
            if lens and sum(lens) == len(w):
                at = 0
                for k, ln in zip(group[lid], lens):
                    words[k] = w[at:at + ln]
                    at += ln
    letters = {}
    for lid, w in words.items():
        n, d = lid.split("-")
        for cell, ch in zip(lights[(int(n), d)], w):
            if letters.setdefault(cell, ch) != ch:
                return {}, f"answers clash at {cell}"
    return words, f"{len(words)} of {len(lights)} lights answered"


def next_issue(day):
    """The first issue within NEXT_WITHIN days after `day` whose scan we hold (a djvu), as (date, meta) or None."""
    for d, m in sorted(all_issues().items()):
        gap = (datetime.date.fromisoformat(d) - day).days
        if 0 < gap <= NEXT_WITHIN and (item_dir(m["item"]) / "djvu.xml.gz").exists():
            return d, m
    return None


_ALL = {}


def all_issues():
    """{date: meta} of every issue index.json lists (parsed once)."""
    if not _ALL:
        got = json.loads((downloads.NATION_SCANS / "index.json").read_text())
        _ALL.update({m["date"]: m for m in got.values() if m.get("date")})
    return _ALL


def read_answers(day, number, rows, laid):
    """({light id: letters}, note) off the next issue's solution list for `number`."""
    nxt = next_issue(datetime.date.fromisoformat(day))
    if nxt is None:
        return {}, "no next issue scanned"
    meta = nxt[1]
    for leaf in range(len(objects(meta["item"]))):
        lines = lines_of(meta["item"], leaf)
        said, text = solution_text(lines)
        if said == number and text:
            across, down = parse_solution(text)
            if not across or not down:
                return {}, "the solution list does not parse"
            return answers_for(rows, laid, across, down)
    return {}, f"no 'Solution to Puzzle No. {number}' in the next issue"


# ---------------------------------------------------------------- reading a page

def read_page(day, meta):
    """{"number", "laid", "rows", "leaf", "why"} of one issue: the clues voted, the grid fitted."""
    import ocr_clues
    import privateeye_scans as pes
    from PIL import Image
    item = meta["item"]
    out = {"number": None, "laid": None, "rows": None, "leaf": None, "why": None}
    leaf, lines = puzzle_leaf(item, meta["pages"])
    if leaf is None:
        out["why"] = "no listed leaf prints a puzzle heading"
        return out
    out["leaf"] = leaf
    out["number"] = number_of(lines, datetime.date.fromisoformat(day))
    if out["number"] is None:
        out["why"] = "no puzzle number heading near the weekly count"
        return out
    img = Image.open(item_dir(item) / f"leaf_{leaf:04d}.jpg")
    grids = grids_of(img)
    if not grids:
        out["why"] = "no square blocked lattice on the page"
        return out
    boxes = clue_boxes(lines, grids[0][1])
    if not boxes:
        out["why"] = "no clue columns under the grid"
        return out
    words = {"djvu": [w for ws in lines for w in ws]}
    for which in ocr_clues.READERS:
        words[which] = []
        for b in boxes:
            words[which] += column_words(img, b, which, f"nation_{day}_{leaf}_{'-'.join(map(str, b))}")
    cols = pes.column_cols(boxes)
    cols = ordered_cols(cols, grids[0][0])
    verdict, laid = pes.voted(words, cols)
    if laid is None:
        out["why"] = f"the readings do not parse: {verdict.get('refused')}"
        return out
    blank = verdict.get("blank") or {}
    if blank:
        laid, blank, deferred = pes.vlm_filled(img, boxes, words, cols, laid, blank)
        if blank:
            out["why"] = f"{len(blank)} clues the readings do not agree on{deferred}: " + \
                "; ".join(f"{k}: {v}" for k, v in sorted(blank.items())[:4])
            return out
    laid = pes.linked_across(pes.directed_links(pes.named_links(laid, cols.named)))
    empty = sorted(lid for lid, (t, _, _) in laid.items() if not (t or "").strip())
    if empty:
        out["why"] = f"clues with no words: {', '.join(empty)}"
        return out
    out["laid"] = laid
    whys = []
    for rows, _ in grids:
        why = laid_fits(rows, laid)
        if why is None:
            out["rows"] = rows
            return out
        whys.append(why)
    out["why"] = f"no grid fits the clues: {whys[0]}"
    return out


def column_words(img, box, which, key):
    """pes.column_words, cached under this paper's key."""
    import file_archive_org_puzzles as fa
    import ocr_clues
    path = fa.CROPS / "rapid" / f"{key}.{ocr_clues.reader_key(which)}.json"
    if path.exists():
        return [tuple(w) for w in json.loads(path.read_text())]
    got = [(x0 + box[0], y0 + box[1], x1 + box[0], y1 + box[1], t)
           for x0, y0, x1, y1, t in ocr_clues.read_words(img.crop(box), which)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(got))
    return got


# ---------------------------------------------------------------- building

def held_dates():
    """{date: id} of the Nation puzzles up to 1949 the corpus holds (thenation.com's reprints)."""
    root = Path(__file__).resolve().parent.parent / "puzzles" / SERIES
    out = {}
    for path in sorted(root.glob("19[0-4]*/*.json")):
        p = json.loads(path.read_text())
        if p.get("date"):
            out[p["date"]] = p["id"]
    return out


def setter_of(lines):
    return "Frank W. Lewis" if any(re.search(r"\bLEWIS\b", text_of(ws), re.I) for ws in lines) else None


def build(day, number, laid, rows, item, leaf, solved, setter):
    """The puzzle of one read page (file_archive_org_puzzles.build), `solved` its answers by light id."""
    import file_archive_org_puzzles as fa
    puzzle = fa.build(number, datetime.date.fromisoformat(day), rows, "image", dict(laid), item, leaf,
                      series=SERIES, name=f"The Nation cryptic crossword No {number}",
                      url=f"https://archive.org/details/{item}/page/n{leaf}/mode/1up")
    for e in puzzle["entries"]:
        word = solved.get(f"{e['number']}-{e['direction']}")
        if word and len(word) == e["length"]:
            e["solution"] = word
        else:
            e.pop("solution", None)
    if setter:
        puzzle["setter"] = setter
    puzzle["source"] = {"publisher": "The Nation", "url": puzzle["source"]["url"], "retrievedFrom": "archive.org",
                        "acquiredBy": TOOL, "acquiredOn": datetime.date.today().isoformat(),
                        "gridOrigin": "published"}
    return puzzle


def process(day):
    """(day, puzzle or None, answered, why): one issue read through to its puzzle. Runs in a worker."""
    meta = items()[day]
    got = read_page(day, meta)
    if got["why"] or got["rows"] is None:
        return day, None, False, got["why"] or "no grid"
    solved, note = read_answers(day, got["number"], got["rows"], got["laid"])
    lines = lines_of(meta["item"], got["leaf"])
    puzzle = build(day, got["number"], got["laid"], got["rows"], meta["item"], got["leaf"], solved, setter_of(lines))
    answered = all(e.get("solution") for e in puzzle["entries"] if not re.match(r"See \d", e["clue"]["text"] or ""))
    return day, puzzle, answered, note


def refusal(day, why):
    return f"{day}: refused: {why}"


def main(argv):
    if len(argv) < 2 or argv[1] not in ("check", "file"):
        print(__doc__)
        return 2
    held = held_dates()
    if argv[1] == "check":
        day = argv[2]
        d, puzzle, answered, why = process(day)
        if puzzle is None:
            print(refusal(day, why))
            return 1
        print(day, "whole;", puzzle["id"], "answered" if answered else "unanswered", f"({why})",
              "-- date held already" if day in held else "")
        return 0
    start = argv[argv.index("--from") + 1] if "--from" in argv else ""
    days = [d for d in sorted(items()) if d >= start and d not in held]
    from fetch_puzzle import puzzle_path, write_puzzle_file
    import puzzle_paths
    filed = answered_n = 0
    refused = {}
    with multiprocessing.Pool(4) as pool:
        for day, puzzle, answered, why in pool.imap(_safe, days):
            if puzzle is None:
                refused[day] = why
                print(refusal(day, why), flush=True)
                continue
            was = puzzle_paths.find(puzzle["id"])
            if was is not None and json.loads(Path(was).read_text()).get("date") != day:
                refused[day] = f"number {puzzle['number']} is held for another date"
                print(refusal(day, refused[day]), flush=True)
                continue
            try:
                write_puzzle_file(puzzle_path(SERIES, puzzle["number"]), puzzle, generator=TOOL)
            except Exception as e:  # a refused write is that puzzle's reason, not the run's end
                refused[day] = f"the write was refused: {e}"
                print(refusal(day, refused[day]), flush=True)
                continue
            filed += 1
            answered_n += bool(answered)
            print(day, "filed", puzzle["id"], "answered" if answered else "unanswered", f"({why})", flush=True)
    print(f"whole {filed}, answered {answered_n}, refused {len(refused)}")
    return 0


def _safe(day):
    try:
        return process(day)
    except Exception as e:  # one issue's crash is its reason
        return day, None, False, f"crashed: {type(e).__name__}: {e}"


if __name__ == "__main__":
    sys.exit(main(sys.argv))
