#!/usr/bin/env python3
"""File the Times Jumbo cryptics in archive.org's scans of The Times' Saturday editions.

    python3 tools/archive_org_jumbo.py --out ~/.cache/archive_org_crops/unfiled
    python3 tools/archive_org_jumbo.py --show NewsUK1998UKEnglish/1998-07-25_66263

From 1997 the Saturday "games" page prints "JUMBO CROSSWORD 177": a banner,
the prize text ("Entries should be sent to: Jumbo Crossword 177, The Times"),
the 27x27 grid under it, and the ACROSS and DOWN columns to the grid's right.
The facing page prints "SOLUTION TO JUMBO 175", the filled grid of the
Jumbo two weeks before. The numbers run on into today's Times Jumbo, so the
puzzle is filed as timesjumbo-N.

The clue columns are read as tools/archive_org_listener.py reads the
Listener's (read_box: archive.org's words, RapidOCR's two recognisers and
the fine-tuned Tesseract, laid by clue number where two readings agree, then
voted on by tools/file_archive_org_puzzles.py's reconcile). The grid is read
off the scan (trove_grid) and must be symmetric; a light no clue lies on by
its number and count is filed blank. The answers come from the solution
grid (trove_solution_ocr), a light only where every letter is read surely
and the grid's blocks are the puzzle's.

Only a puzzle whose every clue has text goes into puzzles/timesjumbo; any
other reading goes to --out as timesjumbo-N.json, or nowhere without it.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import archive_org_listener as listener
import file_archive_org_puzzles as fa
import file_trove_puzzles as ftp
import reconstruct_grid as rg
import trove_grid
import trove_solution_ocr

SERIES = "timesjumbo"
TOOL = "tools/archive_org_jumbo.py"
#: "JUMBO CROSSWORD 177" (the banner, its number sometimes cut short to
#: "17") and "sent to: Jumbo Crossword 177, The Times" (the prize text).
TITLE = re.compile(r"^\W*jumbo\s+cross\s?word\s+(\d[\d ]{0,4})", re.IGNORECASE)
ENTRY = re.compile(r"sent\s+to\W+jumbo\s+cross\s?word\s+(\d[\d ]{0,4})", re.IGNORECASE)
SOLUTION = re.compile(r"^\W*solution\s+to\s+jumbo\s+(?:cross\s?word\s+)?(\d[\d ]{0,4})", re.IGNORECASE)
#: The Jumbo numbers the 1990s Times printed.
NUMBERS = range(1, 400)
#: The size of a Jumbo grid and of its solution grid on the scan, in pixels.
GRID_PX = (750, 1250)
SOLUTION_PX = (750, 1400)
#: The share of a solution grid's cells that must be block or light where
#: the puzzle's grid has them.
SOLUTION_BLOCKS = 0.97


def number(m):
    return int(re.sub(r"\D", "", m.group(1)))


def scan(d):
    """{"date", "item", "puzzles": [{number, leaf, box}], "solutions": [...]}:
    a puzzle's box is its prize text's line, the number the prize text's
    (the banner's is cut short), else the banner's."""
    pages = json.loads((d / "pages.json").read_text())
    leaves = {p["leaf"] for p in pages.get("crossword_pages", ())
              if (d / f"leaf_{p['leaf']:04d}.jpg").exists()}
    found = {"date": pages["date"], "item": pages["item"], "puzzles": [], "solutions": []}
    if not leaves or not (d / "djvu.xml.gz").exists():
        return found
    for leaf, lines in fa.leaf_lines(d / "djvu.xml.gz", leaves).items():
        titles, entries = [], []
        for ws in lines:
            text = listener.line_text(ws)
            box = (min(w[0] for w in ws), min(w[1] for w in ws),
                   max(w[2] for w in ws), max(w[3] for w in ws))
            for pat, into in ((TITLE, titles), (ENTRY, entries)):
                m = pat.search(text) if pat is ENTRY else pat.match(text)
                if m and number(m) in NUMBERS:
                    into.append((number(m), box))
            m = SOLUTION.match(text)
            if m and number(m) in NUMBERS:
                found["solutions"].append({"number": number(m), "leaf": leaf, "box": box})
        if entries:
            n, box = entries[0]
        elif titles:
            n, box = titles[0]
        else:
            continue
        found["puzzles"].append({"number": n, "leaf": leaf, "box": box})
    return found


def grid_of(img, hit):
    """The grid's box: the largest ink under the prize text. Ink reaching the
    window's foot runs on below it, so the window then reaches the page's."""
    x0, _, _, y1 = hit["box"]
    crop = (max(0, x0 - 500), y1, min(img.width, x0 + 1100), min(img.height, y1 + 1400))
    box = fa.ink_box(img.crop(crop))
    if box is not None and crop[1] + box[3] >= crop[3] - 4 and crop[3] < img.height:
        crop = crop[:3] + (img.height,)
        box = fa.ink_box(img.crop(crop))
    if box is None:
        return None
    return (crop[0] + box[0], crop[1] + box[1], crop[0] + box[2], crop[1] + box[3])


def clue_box(img, grid, hit, words=()):
    """Right of the grid, from above the prize text (ACROSS stands level
    with the banner) to the foot of the page, and as wide as the two columns
    archive.org's ACROSS and DOWN headings (in `words`) show: the Times Two
    crossword's clues stand right of them. Without both headings, 0.8 of
    the grid's width. Returns (box, the x between the columns or None)."""
    gx0, _, gx1, _ = grid
    gw = gx1 - gx0
    x0, y0 = gx1 + 15, max(0, hit["box"][1] - 400)
    near = [w for w in words if x0 <= w[0] < gx1 + gw and y0 <= w[1] < grid[3]]
    across = listener.heading_word(near, "ACROSS")
    down = across and listener.heading_word(near, "DOWN", below=across)
    if across and down and down[0] - across[0] > 0.2 * gw:
        x1, split = down[0] + 1.2 * (down[0] - across[0]), down[0] - 20
    else:
        x1, split = gx1 + 0.8 * gw, None
    return (x0, y0, min(img.width, int(x1)), img.height - 10), split


def lay_on(laid, grid):
    """(laid, {light: why}) on the grid's lights: each light takes the clue
    read for it when its count fills the light (a linked clue's count may run
    past it; a "See" clue has none), and is blank otherwise."""
    out, blank = {}, {}
    for (n, d), cells in rg.light_cells(grid).items():
        lid = f"{n}-{d}"
        text, enum, group = laid.get(lid, ("", None, None))
        if lid not in laid:
            blank[lid] = "no clue read for it"
        elif text and enum and not ftp.SEE_RE.match(text) and ftp.count(enum) < len(cells):
            blank[lid] = f"its count ({enum}) is short of the light's {len(cells)}"
            text = ""
        elif text and enum and ftp.count(enum) > len(cells):
            # A linked clue: its count is the lights' together.
            enum = None
        out[lid] = (text, enum, group)
    return out, blank


def solution_boxes(img):
    """Every patch of ink on a page the size and shape of a Jumbo solution grid."""
    import numpy as np
    step = 4
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    ink = trove_grid.pooled(gray < trove_grid.otsu(gray), step)
    out = []
    for c in trove_grid.components(ink):
        _, cy, cx, h, w = c
        if SOLUTION_PX[0] <= w * step <= SOLUTION_PX[1] and 0.85 <= w / max(h, 1) <= 1.18:
            out.append((int((cx - w / 2) * step), int((cy - h / 2) * step),
                        int((cx + w / 2) * step), int((cy + h / 2) * step)))
    return out


#: In a solution grid, a block's middle is at least BLOCK_INK ink and a
#: light's (a heavy bold letter) under LIGHT_INK; the Jumbo's middle rows
#: print grey enough that trove_solution_ocr's paper test calls blocks
#: lights there.
BLOCK_INK, LIGHT_INK = 0.6, 0.9


def block_fit(gray, grid, lat):
    """Share of cells inked as `grid` has them: a block solid, a light not."""
    ink = (gray < trove_grid.otsu(gray)).astype(float)
    ok = 0
    for r, row in enumerate(grid):
        for c, ch in enumerate(row):
            a = trove_solution_ocr.cell(ink, lat, r, c, 0.2)
            m = float(a.mean()) if a.size else 0.0
            ok += m >= BLOCK_INK if ch == "#" else m < LIGHT_INK
    return ok / (len(grid) * len(grid[0]))


def find_solution(d, grid, leaves=None):
    """(leaf, box, block agreement) of the grid-sized ink on the edition's
    leaves (all, or `leaves`) whose blocks are most like `grid`'s; or None."""
    import numpy as np
    best = None
    for path in sorted(d.glob("leaf_*.jpg")):
        leaf = int(path.stem.split("_")[1])
        if leaves is not None and leaf not in leaves:
            continue
        img = fa.page(d, leaf)
        for box in solution_boxes(img):
            gray = np.asarray(img.crop(box).convert("L"))
            try:
                agree = block_fit(gray, grid, trove_solution_ocr.lattice(gray, len(grid), tight=True))
            except ValueError:
                continue
            if best is None or agree > best[2]:
                best = (leaf, box, agree)
    return best


def read_solution(sol, grid):
    """({light: answer}, stats) off the filled grid under "SOLUTION TO JUMBO
    N" (sol's leaf), or, with no heading read (archive.org's OCR misses the
    white-on-black banner), off any leaf of the edition two weeks on: the
    grid-sized ink whose blocks are the puzzle's."""
    d = sol["dir"]
    path = fa.CROPS / "solutions" / f"{d.name}_jumbo{sol['number']}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        found = find_solution(d, grid, {sol["leaf"]} if "leaf" in sol else None)
        if found is None or found[2] < SOLUTION_BLOCKS:
            return {}, {"refused": "no grid in the edition has the puzzle's blocks"
                        + (f" (best {found[2]:.2f})" if found else "")}
        fa.page(d, found[0]).crop(found[1]).save(path)
    # The blocks were matched by block_fit above; read_answers' own block
    # share (its "blocks") misreads the grey middle rows.
    answers, stats = trove_solution_ocr.read_answers(path, grid, tight=True)
    return {f"{n}-{dr}": w for (n, dr), w in answers.items()}, stats


def solutions_of(scans):
    """{number: solution} for every Jumbo in `scans` ({dir: scan}): the
    headed solution grid, else the edition two weeks on (the Jumbo's
    solution is printed then), to be searched by image."""
    out, by_date = {}, {found["date"]: d for d, found in scans.items()}
    for d, found in scans.items():
        for s in found["solutions"]:
            out.setdefault(s["number"], {**s, "dir": d})
    for d, found in scans.items():
        later = (datetime.date.fromisoformat(found["date"]) + datetime.timedelta(days=14)).isoformat()
        for hit in found["puzzles"]:
            if hit["number"] not in out and later in by_date:
                out[hit["number"]] = {"number": hit["number"], "dir": by_date[later]}
    return out


def read(d, found, hit, solutions=None):
    """(verdict, puzzle or None) for one Jumbo; `solutions` maps a number to
    its solution heading ({number, leaf, box, dir})."""
    n, leaf = hit["number"], hit["leaf"]
    verdict = {"number": n, "leaf": leaf}
    img = fa.page(d, leaf)
    grid = grid_of(img, hit)
    if grid is None:
        verdict["refused"] = "no ink under the prize text"
        return verdict, None
    gw, gh = grid[2] - grid[0], grid[3] - grid[1]
    if not (GRID_PX[0] <= gw <= GRID_PX[1] and 0.85 <= gw / max(gh, 1) <= 1.18):
        verdict["refused"] = f"the ink under the prize text is {gw}x{gh}, not a grid"
        return verdict, None
    gpath = fa.CROPS / "grids" / f"{d.name}_jumbo{n}.png"
    gpath.parent.mkdir(parents=True, exist_ok=True)
    img.crop((grid[0] - 6, grid[1] - 6, grid[2] + 6, grid[3] + 6)).save(gpath)
    g, why = trove_grid.read_grid(gpath, block_above=fa.BLOCK_ABOVE)
    if g and not trove_grid.symmetric(g):
        g, why = None, "not 180-degree symmetric"
    if not g:
        verdict["refused"] = f"grid unread: {why}"
        return verdict, None
    words = [w for ws in fa.leaf_lines(d / "djvu.xml.gz", {leaf})[leaf] for w in ws]
    box, split = clue_box(img, grid, hit, words)
    verdict, laid = listener.read_box(d, leaf, img, box, f"{d.name}_jumbo{n}_{'-'.join(map(str, box))}",
                                      verdict, split)
    if laid is None:
        return verdict, None
    blank = verdict.pop("blank", {})
    laid, more = lay_on(laid, g)
    blank = {lid: why for lid, why in {**blank, **more}.items() if lid in laid and not laid[lid][0]}
    verdict["lights"] = len(laid)
    verdict["agreed"] = sum(1 for t, _, _ in laid.values() if t)
    if blank:
        verdict["blank"] = blank
    day = datetime.date.fromisoformat(found["date"])
    puzzle = fa.build(n, day, g, "image", laid, found["item"], leaf, series=SERIES,
                      name=f"Times jumbo cryptic crossword No {n:,}")
    sol = (solutions or {}).get(n)
    if sol:
        answers, info = read_solution(sol, g)
        verdict["solutionFrom"] = f"{sol['dir'].name} leaf {sol.get('leaf', '?')}"
        verdict["solution"] = info
        verdict["answers"] = trove_solution_ocr.fill(puzzle, answers)
    return verdict, puzzle


def editions(cache=fa.CACHE):
    return [d for d in fa.edition_dirs(cache)
            if (d / "pages.json").exists() and d.name[:4] >= "1993"]


def run(cache=fa.CACHE, out_dir=None, write=True, puzzles=None, out=sys.stdout):
    """Read every cached Jumbo; file the complete ones (into `puzzles`, else
    the corpus) and write the rest to `out_dir`. Returns the counts."""
    from fetch_puzzle import puzzle_path, write_puzzle_file
    scans = {d: scan(d) for d in editions(cache)}
    solutions = solutions_of(scans)
    counts = {"found": 0, "read": 0, "complete": 0, "filed": 0}
    for d, found in scans.items():
        for hit in found["puzzles"]:
            counts["found"] += 1
            try:
                verdict, puzzle = read(d, found, hit, solutions)
            except Exception as e:  # noqa: BLE001 -- one bad page is a verdict, not a crash
                verdict, puzzle = {"refused": f"crashed: {type(e).__name__}: {e}"}, None
            name = f"{SERIES}-{hit['number']}"
            if puzzle is None:
                print(f"{d.name} {name}: {verdict['refused']}", file=out)
                continue
            counts["read"] += 1
            whole = fa.complete(puzzle)
            counts["complete"] += whole
            print(f"{d.name} {name}: {verdict['agreed']}/{verdict['lights']} clues, "
                  f"{verdict.get('answers', 0)} answers", file=out)
            if not write:
                continue
            if whole:
                path = Path(puzzles) / f"{name}.json" if puzzles else puzzle_path(SERIES, hit["number"])
                if not path.exists():
                    write_puzzle_file(path, puzzle, generator=TOOL)
                    counts["filed"] += 1
            elif out_dir:
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"{name}.json").write_text(json.dumps(
                    {**puzzle, "verdict": verdict}, indent=1, ensure_ascii=False) + "\n")
    print(f"{counts['found']} Jumbos found, {counts['read']} read, {counts['complete']} with every "
          f"clue, {counts['filed']} filed", file=out)
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, help="write each incomplete reading here as timesjumbo-N.json")
    ap.add_argument("--dry-run", action="store_true", help="read and count, write nothing")
    ap.add_argument("--show", help="<item>/<edition dir>: print its readings")
    args = ap.parse_args(argv)
    if args.show:
        d = fa.CACHE / args.show
        found = scan(d)
        sols = solutions_of({e: scan(e) for e in editions()})
        for hit in found["puzzles"]:
            verdict, puzzle = read(d, found, hit, sols)
            print(json.dumps(verdict, indent=1))
            for e in (puzzle or {}).get("entries", ()):
                print(f"{e['number']:>3}-{e['direction']:6s} {e['clue'].get('text', '')} "
                      f"({e['clue'].get('enumeration')}) {e.get('solution') or ''}")
        return 0
    run(out_dir=args.out, write=not args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
