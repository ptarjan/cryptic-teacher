#!/usr/bin/env python3
"""File the newest Times Literary Supplement crossword off the TLS's own page image.

    python3 tools/tls_puzzles.py --latest      # daily_update.sh: file the newest issue (exit 3: held)

The TLS crossword is fortnightly. the-tls.com publishes each as a WordPress
article (category 95, "Crossword 1620") whose body is one picture of the
printed page: the title and setter ("TLS Crossword 1620 by Agenor") over the
15x15 blocked grid on the left, the Across and Down clues set in columns
below and beside it (a clue may run on into the next column), and at bottom
right the previous puzzle's filled solution grid and the prize small print;
the print issue's date is in the page's footer. The WordPress JSON listing
(LISTING) needs no login, newest first.

The picture is read deterministically: the grid is the region the long ruled
lines bound (grid_box), its cells sampled by tools/genius_puzzles.py's
grid_of_images; the text columns are the bands below and right of the grid,
split at their printed vertical rules, the right-hand column cut above the
solution grid, each read by tools/ocr_clues.py's English PP-OCRv5 reader
("en5") and parsed by genius_puzzles.parse_text. A puzzle is filed only when
the grid's lights are the clue list's, every enumeration the length of its
light (ft_pdf_puzzles.grid_matches); it is filed unsolved, with no answers,
as genius_puzzles.unsolved files one, until timesforthetimes blogs it
(tools/file_times_puzzles.py). The id and date follow file_times_puzzles':
tls-<number>, dated by the print issue (a Friday).
"""
import argparse
import datetime
import html
import json
import re
import sys
import time
import urllib.request
import clue_text
import downloads
import file_blog_puzzles
import ft_pdf_puzzles as fpp
import genius_puzzles
import ocr_clues
import reconstruct_grid as rg
import series as series_meta
from fetch_puzzle import puzzle_path, write_puzzle_file


SERIES = "tls"
CATEGORY = "TLS Crossword"
CACHE = downloads.ROOT / "tls"
GENERATOR = "tools/tls_puzzles.py"
UA = {"User-Agent": "Mozilla/5.0"}
LISTING = ("https://www.the-tls.com/wp-json/wp/v2/tls_articles?article_category=95&per_page=3"
           "&_fields=id,date,link,title,content")
TITLE = re.compile(r"Crossword\s+(\d{3,5})\b")
IMAGE = re.compile(r'<img[^>]+src="([^"?]+/crossword-\d+[^"?]*\.(?:jpe?g|png))', re.IGNORECASE)
#: The clue reader: English PP-OCRv5 keeps the spaces RapidOCR's "ch" loses here.
READER = "en5"
BYLINE = re.compile(r"Crossword\s*(\d{3,5})\s*by\s*([A-Z][A-Za-z]+)")
FOOTER_DATE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)"
                         r"\s+(\d{1,2}),?\s+(\d{4})")
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                      "August", "September", "October", "November", "December"], 1)}


def get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def runs(mask):
    """[(start, end)] of the True runs in a 1-d boolean array, end exclusive."""
    out, start = [], None
    for i, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i))
            start = None
    return out


def lattice(centres):
    """The longest run of evenly spaced lines among `centres` (sorted), as
    (first, last), or None: the grid's rulings, not a column rule or the
    title's underline that stands near them."""
    best = None
    for i, c in enumerate(centres):
        for d in centres[i + 1:]:
            pitch = d - c
            if pitch < 15:
                continue
            chain, at = [c], c
            for e in centres:
                if e > at and abs(e - at - pitch) <= max(2, pitch * 0.06):
                    chain.append(e)
                    at = e
            if len(chain) >= 5 and (best is None or len(chain) > len(best)):
                best = chain
    return best and (best[0], best[-1])


def grid_box(a):
    """(x0, y0, x1, y1) of the grid in the grey array `a` (0 ink, 1 paper):
    the outermost of its evenly spaced ruled lines in the page's left part,
    each vertical one ruling at least half the page's height."""
    import numpy as np
    h, w = a.shape
    ink = a < 0.8
    cols = runs(ink[:, : int(w * 0.6)].sum(axis=0) > 0.5 * h)
    xs = lattice([(s + e - 1) / 2 for s, e in cols])
    if not xs:
        return None
    x0, x1 = int(xs[0]), int(round(xs[1]))
    rows = runs(ink[:, x0:x1 + 1].sum(axis=1) > 0.9 * (x1 - x0))
    ys = lattice([(s + e - 1) / 2 for s, e in rows])
    if not ys:
        return None
    y0, y1 = int(ys[0]), int(round(ys[1]))
    if abs((x1 - x0) - (y1 - y0)) > 0.05 * (x1 - x0):
        return None
    return x0, y0, x1, y1


def rules(a, x0, y0, x1, y1):
    """The x of each printed vertical rule in the band: a column nearly all
    of whose pixels in the band are ink-ish, away from the band's edges."""
    import numpy as np
    band = a[y0:y1, x0:x1] < 0.9
    frac = band.mean(axis=0)
    out = []
    for s, e in runs(frac > 0.6):
        x = x0 + (s + e) // 2
        if x - x0 > 40 and x1 - x > 40:
            out.append(x)
    return out


def solution_top(a, x0, y0, x1, y1):
    """The y where the previous solution's grid starts in a column: the first
    row more than half of whose width is ink, else y1."""
    band = a[y0:y1, x0:x1] < 0.8
    for i, frac in enumerate(band.mean(axis=1)):
        if frac > 0.6:
            return y0 + i
    return y1


#: This typeface's own slips: a minus sign for the en dash ("(–, Jane
#: Austen)") and an underscore for a printed blank (24 down's "“__ brillig").
#: The generic ones (space lost after a number or before a bracket) live in clue_text.
TIDY = [(re.compile("\u2212"), "\u2013"),
        (re.compile(r"_+\s*"), ocr_clues.BLANK + " ")]


def printed_lines(words):
    """[(x0, y0, x1, y1)] of each printed row of `words`, as lines_of rows them."""
    rows, row, top, height = [], [], None, 0
    for w in sorted(words, key=lambda w: (w[1], w[0])):
        if row and w[1] > top + height / 2:
            rows.append(row)
            row = []
        if not row:
            top, height = w[1], w[3] - w[1]
        row.append(w)
    if row:
        rows.append(row)
    return [(min(w[0] for w in r), min(w[1] for w in r), max(w[2] for w in r), max(w[3] for w in r)) for r in rows]


def text_of(img, box):
    """The text READER reads in `box` of the page, row by row, each printed
    blank (24 down's "__ brillig") put in as ocr_clues.BLANK."""
    crop = img.crop(box)
    words = ocr_clues.read_words(crop, READER)
    heights = sorted(w[3] - w[1] for w in words if re.fullmatch(r"[A-Za-z]{2,12}\W?", w[4]))
    if words and heights:
        blanks = ocr_clues.blank_strokes(crop, printed_lines(words), words, heights[len(heights) // 2])
        words = ocr_clues.with_blanks(words, blanks)
    text = ocr_clues.lines_of(words)
    for rx, to in TIDY:
        text = rx.sub(to, text)
    return clue_text.tidy_ocr_clues(text, scope="column")


def read_image(img, web_date):
    """{number, setter, date, clues, grid, preamble, origin} off the page image,
    or raises ValueError saying what could not be read."""
    import numpy as np
    a = np.asarray(img.convert("L"), dtype=np.float32) / 255
    h, w = a.shape
    box = grid_box(a)
    if not box:
        raise ValueError("no ruled square grid found in the page image")
    gx0, gy0, gx1, gy1 = box
    pad = 6
    # The columns below the grid (to its right edge) and right of it (to the
    # page's ruled title line), each split at the printed rules between them.
    below = (gx0 - pad, gy1 + pad, gx1 + pad, h)
    right = (gx1 + pad, gy0 - pad, w, h)
    # The footer line (date, title, page) is below every column: stop above it.
    foot = h
    for s, e in runs((a[gy1:, :] < 0.5).any(axis=1)):
        foot = gy1 + s
    columns = []
    for bx0, by0, bx1, by1 in (below, right):
        cuts = [bx0] + rules(a, bx0, by0, bx1, min(by1, foot)) + [bx1]
        for cx0, cx1 in zip(cuts, cuts[1:]):
            if cx1 - cx0 > 80:
                columns.append([cx0 + 2, by0, cx1 - 2, min(by1, foot) - 2])
    if len(columns) < 2:
        raise ValueError("could not find the clue columns")
    # The last column carries the previous puzzle's solution under its clues.
    last = columns[-1]
    last[3] = solution_top(a, *last) - 2
    text = "\n".join(text_of(img, tuple(c)) for c in columns)
    title = text_of(img, (0, 0, w, max(gy0 - 2, 10)))
    footer = text_of(img, (0, foot - 4, w, h))
    flat = genius_puzzles.flat(text)
    out = genius_puzzles.parse_text(flat)
    m = BYLINE.search(title)
    if not m:
        raise ValueError(f"no byline in the title {title!r}")
    out["number"], out["setter"] = int(m.group(1)), m.group(2)
    d = FOOTER_DATE.search(footer)
    if d:
        out["date"] = datetime.date(int(d.group(3)), MONTHS[d.group(1)], int(d.group(2))).isoformat()
    else:
        # The print issue is the Friday on or after the web posting.
        day = datetime.date.fromisoformat(web_date[:10])
        out["date"] = (day + datetime.timedelta(days=(4 - day.weekday()) % 7)).isoformat()
    out["preamble"] = None
    genius_puzzles.see_links(out["clues"])
    grid = genius_puzzles.grid_of_images([img.crop((gx0, gy0, gx1 + 1, gy1 + 1))], out["clues"])
    if not grid:
        raise ValueError("could not read the grid's cells")
    genius_puzzles.turn_links(out["clues"], set(rg.light_cells(grid)))
    out["grid"] = grid
    out["origin"] = "the TLS's page image"
    out["text"] = flat
    return out


def unsolved(number, page, url):
    """(puzzle, None) or (None, why not): the grid and clues with no answers."""
    entries = fpp.entries_of(page, None, page["grid"])
    if entries is None:
        return None, "a light has no clue"
    rec = {"post_id": None, "link": url, "date": None, "series": CATEGORY, "number": number,
           "setter": page["setter"], "entries": entries}
    row = {"grid": page["grid"], "number": number, "how": page["origin"]}
    puzzle, why = file_blog_puzzles.build(rec, row, SERIES, datetime.date.fromisoformat(page["date"]), page["setter"])
    if why:
        return None, why
    puzzle["source"] = {"url": url, "gridOrigin": "published"}
    return puzzle, None


def latest(log=print):
    """The newest TLS crossword: one listing request, its image, and file it
    unsolved. 3 when it is already held, else 0 and tools/fetch_puzzle.py
    reindex(); 1 when it could not be read or filed. A bot
    challenge page in place of the listing is a soft skip (3)."""
    from PIL import Image
    rows = None
    for wait in (0, 10):
        time.sleep(wait)
        try:
            rows = json.loads(get(LISTING))
            break
        except ValueError:
            # the-tls.com sometimes answers with an HTML challenge page.
            continue
    if rows is None:
        # Weather, not a fault: exit 3 like "nothing new", so the unit does
        # not fail and back off. A challenge that never lifts shows as a
        # silent series: coverage_report.py STALE_AFTER_DAYS["tls"] alerts.
        log("the TLS listing answered with no JSON (a bot challenge page?); skipped")
        return 3
    if not rows:
        log("the TLS crossword listing is empty")
        return 1
    row = rows[0]
    m = TITLE.search(html.unescape(row["title"]["rendered"]))
    if not m:
        log(f"no crossword number in the newest title {row['title']['rendered']!r}")
        return 1
    n = int(m.group(1))
    if puzzle_path(SERIES, n).exists():
        log(f"up-to-date {series_meta.puzzle_id(SERIES, n)}")
        return 3
    im = IMAGE.search(row["content"]["rendered"])
    if not im:
        log(f"TLS {n}: no crossword image in the article")
        return 1
    path = CACHE / "image" / f"{n}{'.png' if im.group(1).lower().endswith('.png') else '.jpg'}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(get(im.group(1)))
        tmp.replace(path)
    try:
        page = read_image(Image.open(path), row["date"])
    except ValueError as e:
        log(f"TLS {n} not filed: {e}")
        return 1
    if page["number"] != n:
        log(f"TLS {n} not filed: the image is headed No {page['number']}")
        return 1
    why = fpp.grid_matches(page["grid"], page["clues"]) if page["clues"] else "no clues read"
    if why:
        log(f"TLS {n} not filed: {why}")
        return 1
    puzzle, why = unsolved(n, page, row["link"])
    if why:
        log(f"TLS {n} not filed: {why}")
        return 1
    write_puzzle_file(puzzle_path(SERIES, n), puzzle, generator=GENERATOR)
    from fetch_puzzle import reindex
    reindex()
    print(puzzle["id"])
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--latest", action="store_true", help="file the newest issue (exit 3 when held)")
    args = ap.parse_args(argv)
    if not args.latest:
        ap.print_help()
        return 2
    return latest()


if __name__ == "__main__":
    sys.exit(main())
