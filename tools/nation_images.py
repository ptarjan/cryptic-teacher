#!/usr/bin/env python3
"""The Nation's own pictures of its grids: the blank grid every page prints
(wp-content/uploads/YYYY/MM/grid<N>.jpg, 3198 on) and the filled solution
grid the next page prints beside the setters' notes (s<N>.jpg, from 3524
"solution<N>.jpg" alone, which is then the only key).

The blank grid is read by pixels, no model: the grid's outer lines are found
as the columns and rows that are mostly dark, the cells are cut evenly
between them, and a cell is a block when its middle is dark. A reading
counts only if its numbering is the clue list's, light for light (number,
direction, length; a linked light's length free but its group's total
held), so a misread cell is a refused grid, never a wrong one. It replaces
the search wherever the page prints a grid: 3505 and 3507 ran the search out
of budget, and an asymmetric grid (3348, 3442, 3481) the search never builds.

The solution grid is read by the VLM (tools/vlm_reader.py), row by row, and
is held to the grid it must fill: same blocks, one letter per white cell. An
answer comes from it only where the whole reading agrees with the pixels.
While the VLM is down the read is skipped (VlmDown), and the puzzle stays due
(memory: cryptic-defer-scans-when-vlm-down).

    python3 tools/nation_images.py grid 3505      # print the read grid
    python3 tools/nation_images.py solution 3524  # print the read letters
"""
import io
import re
import sys
import urllib.request

import fetch_nation as fn
import reconstruct_grid as rg

IMAGES = fn.DIR / "images"
UPLOAD = r"https?://[^\"' ]*?/wp-content/uploads/\d{4}/\d{2}/"
# The blank grid: "grid3505.jpg". The solution: "s3504.jpg", "Solution-3523.jpg",
# "solution3525.jpg", and 3527's page names 3526's "solution3536.jpg".
GRID_IMG = re.compile(UPLOAD + r"grid(\d+)\.(?:jpg|png)", re.I)
SOLUTION_IMG = re.compile(UPLOAD + r"(?:s|solution-?)(\d+)\.(?:jpg|png)", re.I)
DARK = 110          # a grey level below this is ink
LINE = 200          # below this is drawn on (a thin ruled line greys out in a JPEG)
BLOCK = 0.75        # a cell whose middle is this dark is a block; a letter's ink is far less


class VlmDown(Exception):
    """The solution read needs the VLM and it did not answer."""


def image_url(page, kind):
    """The page's blank grid ("grid") or the solution it prints ("solution",
    the previous puzzle's), full size, or None."""
    pattern = GRID_IMG if kind == "grid" else SOLUTION_IMG
    m = pattern.search(page)
    return m.group(0) if m else None


def fetch(url):
    """The image's bytes, cached under downloads.NATION/images."""
    path = IMAGES / url.rsplit("/", 1)[1]
    if not path.is_file():
        req = urllib.request.Request(url, headers={"User-Agent": fn.UA})
        with urllib.request.urlopen(req, timeout=40) as r:
            data = r.read()
        IMAGES.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path.read_bytes()


def _gray(data):
    from PIL import Image
    img = Image.open(io.BytesIO(data)).convert("L")
    return img, img.load()


def _lines(px, w, h, horizontal, lo=0, hi=None):
    """Indices (rows if `horizontal`, else columns) at least 60% dark over
    [lo, hi) of the other axis: the grid's ruled lines and block runs."""
    hi = hi if hi is not None else (w if horizontal else h)
    span = hi - lo
    out = []
    for i in range(h if horizontal else w):
        dark = sum(1 for j in range(lo, hi)
                   if (px[j, i] if horizontal else px[i, j]) < LINE)
        if dark >= 0.6 * span:
            out.append(i)
    return out


def frame(data):
    """(left, top, right, bottom) of the grid in the image: the outermost
    mostly-dark columns, then the outermost mostly-dark rows between them.
    A solution picture's notes beside the grid are text, never 60% ink."""
    img, px = _gray(data)
    w, h = img.size
    cols = _lines(px, w, h, horizontal=False)
    if len(cols) < 2:
        return None
    left, right = cols[0], cols[-1]
    rows = _lines(px, w, h, horizontal=True, lo=left, hi=right + 1)
    if len(rows) < 2:
        return None
    return left, rows[0], right, rows[-1]


def blocks(data, size):
    """The grid as rows of "." and "#", read as `size` x `size` cells, or None."""
    box = frame(data)
    if box is None:
        return None
    img, px = _gray(data)
    left, top, right, bottom = box
    cw, ch = (right - left) / size, (bottom - top) / size
    if min(cw, ch) < 6:
        return None
    out = []
    for y in range(size):
        row = ""
        for x in range(size):
            # The middle half of the cell, clear of the lines and of the
            # clue number in its corner.
            # A filled grid's bold letter can ink the middle as dark as a
            # block, so a corner no letter reaches must be dark too: the
            # lower-right, or the upper-left (s3524's last column is cut off
            # at the picture's edge). A white cell's middle is never dark, so
            # a blank grid's clue number in that corner cannot make a block.
            ink = lambda xs, ys: _ink(px, left, top, cw, ch, x, y, xs, ys)
            dark = min(ink((0.3, 0.75), (0.35, 0.75)),
                       max(ink((0.78, 0.9), (0.8, 0.9)), ink((0.1, 0.22), (0.1, 0.22))))
            row += "#" if dark >= BLOCK else "."
        out.append(row)
    return tuple(out)


def _ink(px, left, top, cw, ch, x, y, xs, ys):
    """The dark share of cell (x, y)'s part xs x ys (fractions of the cell)."""
    x0, x1 = int(left + (x + xs[0]) * cw), int(left + (x + xs[1]) * cw)
    y0, y1 = int(top + (y + ys[0]) * ch), int(top + (y + ys[1]) * ch)
    cells = [px[i, j] for i in range(x0, max(x1, x0 + 1)) for j in range(y0, max(y1, y0 + 1))]
    return sum(1 for v in cells if v < DARK) / len(cells)


def fits(grid, across, down, groups):
    """Does `grid` number exactly as the clue list does? Every light's number
    and direction, its length where the list prints one, and each linked
    group's total."""
    got = {(n, d): length for n, d, length in rg.lights_from_grid(grid)}
    want = [(lg[0], d, lg[1]) for d, ls in (("across", across), ("down", down)) for lg in ls]
    if len(got) != len(want):
        return False
    for n, d, length in want:
        if (n, d) not in got or (length is not None and got[(n, d)] != length):
            return False
    lights = {"across": across, "down": down}
    for members, total in groups or ():
        if sum(got[(lights[d][i][0], d)] for d, i in members) != total:
            return False
    return True


def printed_grid(page, across, down, groups):
    """(grid, None) from the page's blank grid picture, or (None, why not)."""
    url = image_url(page, "grid")
    if url is None:
        return None, "the page prints no grid picture"
    try:
        data = fetch(url)
    except OSError as e:
        return None, f"grid picture not fetched: {e}"
    for size in fn.SIZES:
        grid = blocks(data, size)
        if grid is not None and fits(grid, across, down, groups):
            return grid, None
    return None, "the grid picture does not number as the clue list"


ROWS_PROMPT = """This is a filled-in {size}x{size} crossword grid. Transcribe it row by row, top to bottom: one line per row, exactly {size} characters each, a capital letter for each white square and # for each black square. Output only the {size} lines."""


def solution_letters(number, grid):
    """{(y, x): letter} for Nation `number`'s solution picture, held to
    `grid`, or (None, why). Raises VlmDown when the model does not answer.
    Two reads: the grid, and the grid with its cells laid out column by
    column (each cell pasted upright, so a column reads as a row). Each read
    line counts only where its letter runs are the grid line's white runs;
    a cell read in both must agree."""
    import vlm_reader
    path = fn.PAGES / f"puzzle-no-{number + 1}.html"
    if not path.is_file():
        return None, "the next page, which prints the solution, is not held"
    url = image_url(path.read_text(), "solution")
    if url is None:
        return None, "the next page prints no solution picture"
    data = fetch(url)
    size = len(grid)
    seen = blocks(data, size)
    if seen is None or seen != tuple(grid):
        return None, "the solution picture's blocks are not the grid's"
    if not vlm_reader.wanted():
        raise VlmDown("the VLM is down")
    prompt = ROWS_PROMPT.format(size=size)
    try:
        by_row = vlm_reader.ask(_cells(data, size, False), prompt, max_tokens=800)
        by_col = vlm_reader.ask(_cells(data, size, True), prompt, max_tokens=800)
    except RuntimeError as e:
        raise VlmDown(str(e)) from e
    columns = ["".join(row[x] for row in grid) for x in range(size)]
    rows = read_lines(by_row, grid)
    cols = read_lines(by_col, columns)
    out, disputed = dict(rows), set()
    for (x, y), ch in cols.items():
        if out.get((y, x), ch) != ch:
            disputed.add((y, x))   # the two reads differ: neither is kept
        out[(y, x)] = ch
    for cell in disputed:
        del out[cell]
    if not out:
        return None, "no line of either read is the grid's"
    return out, None


def _cells(data, size, transpose):
    """The picture's grid redrawn cell by cell, column by column when
    `transpose` (cell (x, y) drawn at (y, x)), every letter upright."""
    from PIL import Image
    img, _ = _gray(data)
    left, top, right, bottom = frame(data)
    cw, ch = (right - left) / size, (bottom - top) / size
    w, h = int(round(cw)), int(round(ch))
    out = Image.new("L", (w * size, h * size), 255)
    for y in range(size):
        for x in range(size):
            box = (int(left + x * cw), int(top + y * ch), int(left + x * cw) + w, int(top + y * ch) + h)
            at = (y * w, x * h) if transpose else (x * w, y * h)
            out.paste(img.crop(box), at)
    return out


def _png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def read_lines(reply, lines):
    """{(i, j): letter} for square j of line i, from the model's lines, kept
    only for a line whose letter runs (split at any number of blocks: the
    model writes "###" as "#" and drops a trailing one) are, in count and
    length, that line's white runs in `lines`."""
    got = [re.sub(r"[^A-Z#.]", "", line.upper()) for line in reply.splitlines()]
    got = [g for g in got if g]
    out = {}
    if len(got) != len(lines):
        return out
    for i, (text, want) in enumerate(zip(got, lines)):
        runs = [m for m in re.finditer(r"[^#]+", want)]
        letters = [r for r in re.split(r"[#.]+", text) if r]
        if [len(r) for r in letters] != [m.end() - m.start() for m in runs]:
            continue
        for m, word in zip(runs, letters):
            for k, c in enumerate(word):
                out[(i, m.start() + k)] = c
    return out


def key_from_letters(letters, grid, across, down):
    """nation_key's key ({(direction, index): (letters, note)}) from a read
    solution grid: every light whose squares all read, in clue-list order."""
    cells = rg.light_cells(grid)
    key = {}
    for d, lights in (("across", across), ("down", down)):
        for i, lg in enumerate(lights):
            run = cells.get((lg[0], d))
            if run and all(c in letters for c in run):
                key[(d, i)] = ("".join(letters[c] for c in run), "")
    return key


def main(argv):
    if len(argv) != 2 or argv[0] not in ("grid", "solution"):
        raise SystemExit(__doc__)
    n = int(argv[1])
    page = (fn.PAGES / f"puzzle-no-{n}.html").read_text()
    read, why = fn.read_page(page, fn.original_dates())
    if read is None:
        raise SystemExit(why)
    _, _, across, down, groups = read
    grid, why = printed_grid(page, across, down, groups)
    if grid is None:
        raise SystemExit(why)
    if argv[0] == "grid":
        print("\n".join(grid))
        return
    letters, why = solution_letters(n, grid)
    if letters is None:
        raise SystemExit(why)
    print("\n".join("".join(letters.get((y, x), "#") for x in range(len(grid)))
                    for y in range(len(grid))))


if __name__ == "__main__":
    main(sys.argv[1:])
