#!/usr/bin/env python3
"""File the Listener crossword from the Listener Team's archive PDFs.

    python3 tools/listener_puzzles.py [--dry-run]

The Listener Team's site (listenercrossword.com) prints clue text for only five
historic puzzles, each as a pair of vector PDFs at /PDF/Archive/: List<nnnn>.pdf
holds the grid and clues, List<nnnn>s.pdf the filled grid. The grid is drawn
cell by cell as a table, every side of every cell its own thin filled
rectangle, so a bar is a side drawn thicker than a cell border and a square
outside a shaped grid is one with no letter in the solution. The clues are two
columns that may run onto a second page; each column is read top to bottom
across the pages before the next.

The other source of Listener clue text, the Wayback captures of the Times'
article pages, held five full clue lists (3974, 3975, 3985, 3999, 4016) when
this was written: four alter their entries, and 3985's grid holds unclued
thematic lights that its solution notes do not place, so none is filed.

A Listener whose entries go into the grid altered (reversed, jumbled, letters
dropped, several letters to a cell) or that is numerical has no faithful
representation here: the solution field is both the clue's answer and the
grid's letters. Those are listed in SKIP with the reason and never filed.
"""
import argparse
import io
import logging
import re
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import series as series_meta
from fetch_puzzle import puzzle_path, write_puzzle_file

SERIES = "listener"
CACHE = Path.home() / "cryptic-setter-data" / "listener"
SITE = "https://www.listenercrossword.com"
GENERATOR = "tools/listener_puzzles.py"
UA = {"User-Agent": "Mozilla/5.0 (cryptic-teacher; github.com/ptarjan/cryptic-teacher)"}

#: The archive PDFs, with the print day the site's 1930-31 year pages give.
PDFS = {1: "1930-04-02", 3: "1930-04-16", 29: "1930-10-15", 93: "1932-01-06",
        111: "1932-05-11"}

#: Puzzles read and deliberately not filed: their entries are not their answers.
SKIP = {
    3: "shaped grid: the outline of India, and a barred grid here has no "
       "squares outside it",
    29: "entries altered: Latin quotation words entered reversed, truncated or "
        "with letters transposed or omitted",
    93: "entries altered: several lights are entered reversed or as anagrams "
        "(rev., anag., mixed)",
    111: "numerical: every light is a number",
}

#: A cell side at least this thick (points) is a bar; borders are 0.8-1.0.
BAR_THICKNESS = 1.4


def get(url, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:
            if getattr(e, "code", None) == 404 or attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def pdf_bytes(name):
    """The archive PDF `name` ("List0001.pdf"), cached under CACHE/pdf."""
    path = CACHE / "pdf" / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(f"{SITE}/PDF/Archive/{name}"))
        time.sleep(2)
    return path.read_bytes()


# ------------------------------------------------------------------ the PDF

def text_runs(data):
    """[(page, x, y, size, text)] of every Tj/TJ, each at its own position.

    Read off the content stream rather than through pypdf's text extraction,
    which merges a right-column clue number into the left-column line beside
    it. The fonts are the standard WinAnsi ones, so a string's bytes are
    cp1252; a TJ kern wider than a fifth of an em is a space."""
    import pypdf
    from pypdf.generic import ContentStream
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    reader = pypdf.PdfReader(io.BytesIO(data))
    runs = []

    def text(v):
        return v.original_bytes.decode("cp1252", "replace") if hasattr(v, "original_bytes") else str(v)

    for page_no, page in enumerate(reader.pages):
        contents = page.get_contents()
        if contents is None:
            continue
        ctm, stack = [1, 0, 0, 1, 0, 0], []
        tm = lm = [1, 0, 0, 1, 0, 0]
        size, leading = 12.0, 0.0
        for operands, op in ContentStream(contents, reader).operations:
            if op == b"q":
                stack.append(ctm)
            elif op == b"Q" and stack:
                ctm = stack.pop()
            elif op == b"cm":
                m = [float(v) for v in operands]
                ctm = [m[0] * ctm[0] + m[1] * ctm[2], m[0] * ctm[1] + m[1] * ctm[3],
                       m[2] * ctm[0] + m[3] * ctm[2], m[2] * ctm[1] + m[3] * ctm[3],
                       m[4] * ctm[0] + m[5] * ctm[2] + ctm[4], m[4] * ctm[1] + m[5] * ctm[3] + ctm[5]]
            elif op == b"BT":
                tm = lm = [1, 0, 0, 1, 0, 0]
            elif op == b"Tf":
                size = float(operands[1])
            elif op == b"TL":
                leading = float(operands[0])
            elif op == b"Tm":
                tm = lm = [float(v) for v in operands]
            elif op in (b"Td", b"TD"):
                tx, ty = float(operands[0]), float(operands[1])
                if op == b"TD":
                    leading = -ty
                tm = lm = [lm[0], lm[1], lm[2], lm[3],
                           lm[4] + tx * lm[0] + ty * lm[2], lm[5] + tx * lm[1] + ty * lm[3]]
            elif op in (b"T*", b"'", b'"'):
                tm = lm = [lm[0], lm[1], lm[2], lm[3], lm[4] - leading * lm[2], lm[5] - leading * lm[3]]
            if op in (b"Tj", b"TJ", b"'", b'"'):
                if op == b"TJ":
                    t = "".join(text(v) if not isinstance(v, (int, float)) and not hasattr(v, "as_numeric")
                                else (" " if float(v) < -200 else "") for v in operands[0])
                else:
                    t = text(operands[-1])
                x = tm[4] * ctm[0] + tm[5] * ctm[2] + ctm[4]
                y = tm[4] * ctm[1] + tm[5] * ctm[3] + ctm[5]
                scale = abs(tm[3] * ctm[3]) or 1
                if t.strip():
                    runs.append((page_no, x, y, size * scale, t))
    return runs


def _cluster(values, tol=3.0):
    """Sorted centres of `values` grouped within tol."""
    groups = []
    for v in sorted(values):
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def _index(edges, v):
    """The span of `edges` that holds v, or None."""
    for i in range(len(edges) - 1):
        if edges[i] <= v < edges[i + 1]:
            return i
    return None


def _nearest(edges, v, tol=3.0):
    best = min(range(len(edges)), key=lambda i: abs(edges[i] - v))
    return best if abs(edges[best] - v) <= tol else None


def read_solution(data):
    """{"rows", "cols", "letters": {(y, x): L}, "numbers": {(y, x): n},
    "bars": [...]} from a solution PDF: the lattice from the cell sides, the
    letters and numbers placed by position, a side thicker than BAR_THICKNESS
    between two lettered cells a bar."""
    import ft_pdf_puzzles as ftp
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    _, ops = ftp.ops_of(data)
    dark = [r for r in ftp.filled_rects(ops) if r[4]]
    vert = [r for r in dark if r[2] - r[0] < 4 and r[3] - r[1] > 10]
    horiz = [r for r in dark if r[3] - r[1] < 4 and r[2] - r[0] > 10]
    xs = _cluster((r[0] + r[2]) / 2 for r in vert)
    ys = _cluster((r[1] + r[3]) / 2 for r in horiz)
    ys_top = sorted(ys, reverse=True)
    cols, rows = len(xs) - 1, len(ys) - 1
    ys_up = sorted(ys)

    def cell(px, py):
        x = _index(xs, px)
        yi = _index(ys_up, py)
        return None if x is None or yi is None else (rows - 1 - yi, x)

    letters, numbers = {}, {}
    for _page, x, y, size, text in text_runs(data):
        t = text.strip()
        if size > 10 and re.fullmatch(r"[A-Z]", t):
            c = cell(x + 2, y + 3)
            if c:
                letters[c] = t
        elif size < 10 and re.fullmatch(r"\d{1,2}", t):
            c = cell(x + 1, y + 2)
            if c:
                numbers[c] = int(t)

    thick = defaultdict(float)
    for r in vert:
        i = _nearest(xs, (r[0] + r[2]) / 2)
        yi = _index(ys_up, (r[1] + r[3]) / 2)
        if i is not None and yi is not None:
            key = ("v", rows - 1 - yi, i)
            thick[key] = max(thick[key], r[2] - r[0])
    for r in horiz:
        i = _nearest(ys_top, (r[1] + r[3]) / 2)
        x = _index(xs, (r[0] + r[2]) / 2)
        if i is not None and x is not None:
            key = ("h", i, x)
            thick[key] = max(thick[key], r[3] - r[1])
    bars = []
    for y in range(rows):
        row = ""
        for x in range(cols):
            right = (x + 1 < cols and (y, x) in letters and (y, x + 1) in letters
                     and thick[("v", y, x + 1)] >= BAR_THICKNESS)
            below = (y + 1 < rows and (y, x) in letters and (y + 1, x) in letters
                     and thick[("h", y + 1, x)] >= BAR_THICKNESS)
            row += "+" if right and below else "r" if right else "b" if below else "."
        bars.append(row)
    return {"rows": rows, "cols": cols, "letters": letters, "numbers": numbers, "bars": bars}


def lights(sol):
    """{(number, direction): [(y, x), ...]} of every run of two or more
    lettered cells unbroken by a bar, numbered as the solution prints them."""
    letters, bars = sol["letters"], sol["bars"]
    out = {}
    for (y, x) in sorted(letters):
        for direction, (dy, dx), mark in (("across", (0, 1), "rr+"), ("down", (1, 0), "bb+")):
            prev = (y - dy, x - dx)
            if prev in letters and bars[prev[0]][prev[1]] not in mark:
                continue
            run = [(y, x)]
            while bars[run[-1][0]][run[-1][1]] not in mark and \
                    (run[-1][0] + dy, run[-1][1] + dx) in letters:
                run.append((run[-1][0] + dy, run[-1][1] + dx))
            if len(run) > 1:
                n = sol["numbers"].get((y, x))
                if n is None:
                    raise ValueError(f"light at row {y} col {x} {direction} has no printed number")
                out[(n, direction)] = run
    return out


CLUE_HEAD = re.compile(r"^(\d{1,2})\s+(\S.*)$")


def page_middle(data):
    import pypdf
    return float(pypdf.PdfReader(io.BytesIO(data)).pages[0].mediabox.width) / 2


def column_lines(runs, mid):
    """(left lines, right lines) of the clue area, each column read down
    every page in turn; `runs` are text_runs(), `mid` the column split.

    The clue area starts at the ACROSS heading on the first page. pypdf runs
    a right-column clue number onto the end of the left-column text beside
    it ("draw the crowds 5"), so a trailing number on a left line whose right
    line opens with a word is moved across to open it."""
    top = max((y for page, _x, y, _s, t in runs if page == 0 and t.strip().startswith("ACROSS")),
              default=None)
    by_line = defaultdict(list)
    for page, x, y, size, text in runs:
        # Small type is the grid's cell numbers, never a clue.
        if size < 9 or (page == 0 and top is not None and y > top + 2):
            continue
        by_line[(page, round(y))].append((x, text))
    # Rows a point or two apart are one row set in two fonts.
    rows = []
    for k in sorted(by_line, key=lambda k: (k[0], -k[1])):
        if rows and rows[-1][0][0] == k[0] and abs(rows[-1][0][1] - k[1]) <= 2:
            rows[-1][1].extend(by_line[k])
        else:
            rows.append((k, list(by_line[k])))
    sides = ([], [])
    for (page, _y), parts in rows:
        left = " ".join(t for x, t in sorted(parts) if x < mid)
        right = " ".join(t for x, t in sorted(parts) if x >= mid)
        left, right = re.sub(r"\s+", " ", left).strip(), re.sub(r"\s+", " ", right).strip()
        m = re.search(r"^(.*\S)\s+(\d{1,2})$", left)
        if m and right and not right[0].isdigit():
            left, right = m.group(1), f"{m.group(2)} {right}"
        if left:
            sides[0].append(left)
        if right:
            sides[1].append(right)
    return sides


def parse_clues(left, right, wanted):
    """{(number, direction): clue text} for the lights in `wanted`, read
    after the ACROSS and DOWN headings. A line opens a clue when it starts
    with a number the section still expects; anything else continues the clue
    before it."""
    clues, section, current = {}, None, None
    both = False
    for i, line in enumerate(left + right):
        if i == len(left) and both:
            # "ACROSS DOWN" as one heading over both columns.
            section, current = "down", None
        head = re.match(r"^(ACROSS|DOWN)\b\s*(DOWN\b)?\s*(.*)$", line)
        if head:
            section, current = head.group(1).lower(), None
            both = both or bool(head.group(2))
            line = head.group(3)
            if not line:
                continue
        if section is None or not line:
            continue
        m = CLUE_HEAD.match(line)
        if m and (int(m.group(1)), section) in wanted and (int(m.group(1)), section) not in clues:
            current = (int(m.group(1)), section)
            clues[current] = m.group(2).strip()
        elif current:
            clues[current] = f"{clues[current]} {line}".strip()
    return {k: re.sub(r"\s+", " ", v).replace(" ,", ",").strip() for k, v in clues.items()}


def read_title(data):
    first = re.sub(r"\s+", " ", text_runs(data)[0][4]).strip()
    m = re.match(r"Listener Crossword No\s*(\d+)\s*:\s*(.+?)(?:\s+by\s+(\S.*))?$", first)
    return (int(m.group(1)), m.group(2).strip(), m.group(3)) if m else (None, None, None)


def assemble(number, puzzle_pdf, solution_pdf, date):
    """(puzzle, None) or (None, why not)."""
    got, title, setter = read_title(puzzle_pdf)
    if got != number:
        return None, f"PDF says No {got}"
    sol = read_solution(solution_pdf)
    grid_lights = lights(sol)
    left, right = column_lines(text_runs(puzzle_pdf), page_middle(puzzle_pdf))
    clues = parse_clues(left, right, set(grid_lights))
    missing = sorted(set(grid_lights) - set(clues))
    if missing:
        return None, f"no clue for {missing[0][0]}-{missing[0][1]}"
    entries = []
    for (n, direction), cells in sorted(grid_lights.items(), key=lambda kv: (kv[0][1] != "across", kv[0][0])):
        entries.append({
            "number": n, "direction": direction,
            "position": {"x": cells[0][1], "y": cells[0][0]}, "length": len(cells),
            "clue": {"text": clues[(n, direction)]},
            "solution": "".join(sol["letters"][c] for c in cells),
        })
    url = f"{SITE}/PDF/Archive/List{number:04d}.pdf"
    puzzle = {
        "id": series_meta.puzzle_id(SERIES, number),
        "number": number,
        "series": SERIES,
        "name": name(number, title),
        "date": date,
        "dimensions": {"cols": sol["cols"], "rows": sol["rows"]},
    }
    if setter:
        puzzle["setter"] = setter
    if any(set(row) - {"."} for row in sol["bars"]):
        puzzle["bars"] = sol["bars"]
    # provenance.stamp() derives the rest of both on write.
    puzzle["source"] = {"url": url}
    puzzle["solutions"] = {"origin": "published"}
    puzzle["entries"] = entries
    return puzzle, None


def name(number, title):
    """Every Listener prints its title beside its number."""
    return f"Listener crossword No {number:,}: {title}"


def file_pdfs(write=True, log=print):
    filed = []
    for number, date in sorted(PDFS.items()):
        if number in SKIP:
            log(f"  {number}: skipped, {SKIP[number]}")
            continue
        try:
            puzzle, why = assemble(number, pdf_bytes(f"List{number:04d}.pdf"),
                                   pdf_bytes(f"List{number:04d}s.pdf"), date)
        except Exception as e:  # noqa: BLE001 — a malformed PDF is one puzzle
            puzzle, why = None, f"unreadable: {type(e).__name__}: {e}"[:200]
        if puzzle is None:
            log(f"  {number}: {why}")
            continue
        if write:
            write_puzzle_file(puzzle_path(SERIES, number), puzzle, generator=GENERATOR)
        filed.append(puzzle["id"])
        log(f"  filed {puzzle['id']}" + ("" if write else " (dry run)"))
    return filed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    file_pdfs(write=not ap.parse_args(argv).dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
